"""
«Carpetas por palabra clave»: el usuario crea en su ordenador una carpeta por tema (p. ej. «Fortnite», «Minecraft»)
con videos e imágenes suyos. Cuando en su narración dice esa palabra, Reclaimer le ofrece ese material.
Sin Qt.

  VIDEO_EXT / IMAGE_EXT   extensiones que cuentan como material (audio y lo demás se ignoran)
  default_root()          ~/Videos/Reclaimer - Clips por palabra (no la crea)
  norm(text)              minúsculas, sin tildes, solo letras/números/espacios
  folder_keys(name)       alias de un nombre de carpeta («Fortnite, fortnait» → ["fortnite", "fortnait"])
  list_folders(root)      una entrada por palabra: name, label, path, own_path (None si no hay subcarpeta),
                          links (carpetas enlazadas del PC), keys, files (propios + enlazados, recientes primero),
                          linked_files (los que vienen de un enlace), count
  match(term, folders)    la carpeta cuyo alias coincide con el término (tolera plural simple) o None
  safe_name(term)         nombre válido para Windows
  create_folder(root, t)  crea (o reutiliza) la carpeta del término y devuelve su ruta
  add_files(folder, paths) copia videos/imágenes (archivos o carpetas) a la carpeta y devuelve las rutas finales
  terms(folders)          el label de cada carpeta (para detectar menciones)
  link_folder / unlink_folder / linked   carpetas ENLAZADAS del PC (no se copian): raíz/_enlaces.json
  link_file / unlink_file / linked_files ARCHIVOS ENLAZADOS del PC (no se copian): clave «_archivos» del mismo JSON
  delete_keyword(root, t, trash_fn)      manda a la Papelera solo la subcarpeta propia; los enlaces no se tocan
  create_from_mentions(root, terms)      crea las subcarpetas de varias palabras de una vez (sin duplicar)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata

from .model import IMAGE_EXT, KIND_IMAGE, KIND_VIDEO, VIDEO_EXT, kind_for_path

_SEP = re.compile(r"[,;|]")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MEDIA_KINDS = (KIND_VIDEO, KIND_IMAGE)


def default_root() -> str:
    return os.path.join(os.path.expanduser("~"), "Videos", "Reclaimer - Clips por palabra")


def norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("'", "").replace("’", "")
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    return " ".join(s.split())


def _aliases_raw(name: str) -> list[str]:
    return [x.strip() for x in _SEP.split(str(name or "")) if x.strip()]


def folder_keys(name: str) -> list[str]:
    out: list[str] = []
    for alias in _aliases_raw(name):
        k = norm(alias)
        if k and k not in out:
            out.append(k)
    return out


def _is_media(path: str) -> bool:
    return kind_for_path(path) in _MEDIA_KINDS


def _media_under(folder: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirs, names in os.walk(folder):
        for n in names:
            full = os.path.join(dirpath, n)
            if _is_media(full):
                out.append(os.path.abspath(full))
    return out


def _mtime(f: str) -> float:
    try:
        return os.path.getmtime(f)
    except OSError:
        return 0.0


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _read_links(root: str) -> dict:
    """{palabra: [rutas de carpetas del PC]} (raíz/_enlaces.json). Un archivo roto se trata como vacío."""
    try:
        with open(os.path.join(root, "_enlaces.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[str(k)] = [str(x) for x in v if isinstance(x, str) and x]
    return out


def _load_raw(root: str) -> dict:
    """El _enlaces.json tal cual: {palabra: [carpetas]} y, aparte, la clave reservada «_archivos» con los archivos
    enlazados {palabra: [archivos]}. Un archivo roto se trata como vacío."""
    try:
        with open(os.path.join(root, "_enlaces.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_raw(root: str, data: dict) -> None:
    os.makedirs(root, exist_ok=True)
    dest = os.path.join(root, "_enlaces.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dest)


def _write_links(root: str, data: dict) -> None:
    """Guarda las carpetas enlazadas ({palabra: [carpetas]}) y conserva los archivos enlazados («_archivos»)."""
    raw = _load_raw(root)
    nuevo = {k: v for k, v in raw.items() if isinstance(v, dict)}
    nuevo.update(data)
    _save_raw(root, nuevo)


def _read_files(root: str) -> dict:
    """{palabra: [rutas de archivos del PC enlazados]} (la clave «_archivos» de _enlaces.json)."""
    arch = _load_raw(root).get("_archivos")
    out: dict = {}
    if isinstance(arch, dict):
        for k, v in arch.items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v if isinstance(x, str) and x]
    return out


def _write_files(root: str, files: dict) -> None:
    raw = _load_raw(root)
    if files:
        raw["_archivos"] = files
    else:
        raw.pop("_archivos", None)
    _save_raw(root, raw)


def _keys_of_link(data: dict, term: str) -> list[str]:
    """Claves del JSON que corresponden al término (mismo nombre o alias)."""
    t = norm(term)
    if not t:
        return []
    return [k for k in data if norm(k) == t or t in folder_keys(k)]


def list_folders(root: str) -> list[dict]:
    if not root or not os.path.isdir(root):
        return []
    links = _read_links(root)
    files_map = _read_files(root)
    groups: list[dict] = []
    for name in os.listdir(root):
        if name.startswith((".", "_")):
            continue
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        groups.append({"name": name, "own": os.path.abspath(path), "links": [], "file_links": [],
                       "keys": folder_keys(name)})

    def _grupo(key: str) -> dict | None:
        ks = folder_keys(key)
        if not ks:
            return None
        g = next((g for g in groups if set(g["keys"]) & set(ks)), None)
        if g is None:                                     # palabra que solo tiene enlaces (sin carpeta propia)
            g = {"name": key.strip(), "own": None, "links": [], "file_links": [], "keys": []}
            groups.append(g)
        for k in ks:
            if k not in g["keys"]:
                g["keys"].append(k)
        return g

    for key, paths in links.items():                     # palabras que solo tienen carpetas enlazadas
        g = _grupo(key)
        if g is None:
            continue
        for p in paths:
            if not any(_same(p, x) for x in g["links"]):
                g["links"].append(os.path.abspath(p))
    for key, paths in files_map.items():                 # archivos enlazados (sin copiar)
        g = _grupo(key)
        if g is None:
            continue
        for p in paths:
            if not any(_same(p, x) for x in g["file_links"]):
                g["file_links"].append(os.path.abspath(p))

    res: list[dict] = []
    for g in groups:
        own_files = _media_under(g["own"]) if g["own"] else []
        linked_files: list[str] = []
        for lp in g["links"]:
            if os.path.isdir(lp):
                linked_files += [f for f in _media_under(lp) if f not in own_files and f not in linked_files]
        for fp in g["file_links"]:
            if os.path.isfile(fp) and fp not in own_files and fp not in linked_files:
                linked_files.append(fp)
        files = own_files + linked_files
        files.sort(key=_mtime, reverse=True)
        aliases = _aliases_raw(g["name"])
        label = aliases[0] if aliases else g["name"].strip()
        res.append({"name": g["name"], "label": label,
                    "path": g["own"] or os.path.abspath(os.path.join(root, safe_name(g["name"]))),
                    "own_path": g["own"], "links": list(g["links"]), "keys": list(g["keys"]),
                    "file_links": [f for f in g["file_links"] if os.path.isfile(f)],
                    "files": files, "linked_files": linked_files, "count": len(files)})
    res.sort(key=lambda f: f["label"].lower())
    return res


def linked(root: str, term: str) -> list[str]:
    """Carpetas del PC enlazadas a la palabra."""
    data = _read_links(root)
    out: list[str] = []
    for k in _keys_of_link(data, term):
        out += [p for p in data[k] if p not in out]
    return out


def link_folder(root: str, term: str, path: str) -> str:
    """Enlaza una carpeta del PC a la palabra (no se copia nada). Una carpeta dentro de la raíz no se enlaza."""
    ap = os.path.abspath(path)
    if not os.path.isdir(ap):
        raise ValueError("Esa carpeta no existe.")
    if _inside(ap, root):
        raise ValueError("Esa carpeta ya está dentro de la carpeta de Reclaimer: es una subcarpeta propia.")
    data = _read_links(root)
    keys = _keys_of_link(data, term)
    key = keys[0] if keys else str(term or "").strip()
    if not key or not folder_keys(key):
        raise ValueError("Falta el nombre de la palabra clave.")
    lista = data.setdefault(key, [])
    if not any(_same(ap, p) for p in lista):
        lista.append(ap)
    _write_links(root, data)
    return ap


def unlink_folder(root: str, term: str, path: str) -> bool:
    """Quita el enlace (la carpeta del PC no se toca)."""
    data = _read_links(root)
    quitado = False
    for k in _keys_of_link(data, term):
        antes = len(data[k])
        data[k] = [p for p in data[k] if not _same(p, path)]
        quitado = quitado or len(data[k]) != antes
        if not data[k]:
            del data[k]
    if quitado:
        _write_links(root, data)
    return quitado


def link_file(root: str, term: str, path: str) -> str:
    """Enlaza un ARCHIVO del PC a la palabra sin copiarlo (videos grandes). Un archivo ya dentro de la carpeta de
    Reclaimer no se enlaza: ya es propio de una palabra."""
    ap = os.path.abspath(path)
    if not os.path.isfile(ap):
        raise ValueError("Ese archivo no existe.")
    if not _is_media(ap):
        raise ValueError("Solo se pueden enlazar videos e imágenes.")
    if _inside(ap, root):
        raise ValueError("Ese archivo ya está dentro de la carpeta de Reclaimer: es propio de una palabra clave.")
    links = _read_links(root)
    files = _read_files(root)
    keys = _keys_of_link(links, term) or _keys_of_link(files, term)
    key = keys[0] if keys else str(term or "").strip()
    if not key or not folder_keys(key):
        raise ValueError("Falta el nombre de la palabra clave.")
    lista = files.setdefault(key, [])
    if not any(_same(ap, p) for p in lista):
        lista.append(ap)
    _write_files(root, files)
    return ap


def unlink_file(root: str, term: str, path: str) -> bool:
    """Quita el enlace de un archivo (el archivo NO se toca)."""
    files = _read_files(root)
    quitado = False
    for k in _keys_of_link(files, term):
        antes = len(files[k])
        files[k] = [p for p in files[k] if not _same(p, path)]
        quitado = quitado or len(files[k]) != antes
        if not files[k]:
            del files[k]
    if quitado:
        _write_files(root, files)
    return quitado


def linked_files(root: str, term: str) -> list[str]:
    """Archivos del PC enlazados a la palabra."""
    files = _read_files(root)
    out: list[str] = []
    for k in _keys_of_link(files, term):
        out += [p for p in files[k] if p not in out]
    return out


def delete_keyword(root: str, term: str, trash_fn) -> dict:
    """Quita una palabra clave: manda a la Papelera (trash_fn) SOLO su subcarpeta propia de Reclaimer y quita sus
    enlaces del JSON (carpetas y archivos). Las carpetas y archivos enlazados del PC NUNCA se tocan (solo se
    desvinculan)."""
    out = {"trashed": None, "files": 0, "unlinked": 0}
    car = match(term, list_folders(root))
    if car is None:
        return out
    own = car.get("own_path")
    if own and _inside(own, root) and not _same(own, root):
        out["files"] = len(_media_under(own))
        if not trash_fn(own):
            raise OSError(f"No pude mandar a la Papelera: {own}")
        out["trashed"] = own
    ks = set(car.get("keys") or []) | {norm(term)}
    data = _read_links(root)
    for k in [k for k in data if set(folder_keys(k)) & ks]:
        out["unlinked"] += len(data.pop(k))
    if out["unlinked"]:
        _write_links(root, data)
    files = _read_files(root)
    quitados = 0
    for k in [k for k in files if set(folder_keys(k)) & ks]:
        quitados += len(files.pop(k))
    if quitados:
        _write_files(root, files)
    out["unlinked"] += quitados
    return out


def create_from_mentions(root: str, terms: list[str]) -> list[str]:
    """Crea la subcarpeta propia de cada palabra (sin duplicar). Devuelve las carpetas NUEVAS."""
    creadas: list[str] = []
    folders = list_folders(root)
    vistos: set = set()
    for t in terms or []:
        k = norm(t)
        if not k or k in vistos:
            continue
        vistos.add(k)
        car = match(t, folders)
        if car is not None and car.get("own_path"):
            continue
        path = car["path"] if car is not None else os.path.join(root, safe_name(t))
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            creadas.append(os.path.abspath(path))
    return creadas


def match(term: str, folders: list[dict]) -> dict | None:
    t = norm(term)
    if not t:
        return None
    for f in folders:                       # coincidencia exacta primero
        if t in f.get("keys", []):
            return f
    for f in folders:                       # plural simple: «fortnites» ↔ «fortnite», «bosses» ↔ «boss»
        for k in f.get("keys", []):
            if t == k + "s" or t == k + "es" or k == t + "s" or k == t + "es":
                return f
    return None


def safe_name(term: str) -> str:
    s = _INVALID.sub("", str(term or "")).strip()
    s = s.rstrip(". ")
    return s or "Sin nombre"


def create_folder(root: str, term: str) -> str:
    """La subcarpeta propia de la palabra (la crea si no existe; si solo tenía enlaces, le añade la suya)."""
    existing = match(term, list_folders(root))
    path = existing["path"] if existing is not None else os.path.join(root, safe_name(term))
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def _unique_dest(folder: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    dest = os.path.join(folder, name)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return dest


def _inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:                      # distinta unidad
        return False


def add_files(folder: str, paths: list[str]) -> list[str]:
    os.makedirs(folder, exist_ok=True)
    sources: list[str] = []
    seen: set[str] = set()
    for p in paths or []:
        if os.path.isdir(p):
            cands = sorted(_media_under(p))
        elif os.path.isfile(p) and _is_media(p):
            cands = [os.path.abspath(p)]
        else:
            continue
        for c in cands:
            if c not in seen:
                seen.add(c)
                sources.append(c)
    out: list[str] = []
    for src in sources:
        if _inside(src, folder):            # ya está en la carpeta: no se copia
            out.append(src)
            continue
        dest = _unique_dest(folder, os.path.basename(src))
        shutil.copy2(src, dest)
        out.append(os.path.abspath(dest))
    return out


def terms(folders: list[dict]) -> list[str]:
    return [f["label"] for f in folders]
