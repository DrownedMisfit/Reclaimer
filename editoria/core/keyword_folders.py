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
  match(term, folders)    la carpeta cuyo alias coincide con el término (tolera plural simple y variantes: «GTA V»,
                          «gta5», «GTA cinco» y «GTA 5» son la misma) o None
  canon(text)             forma canónica para agrupar variantes de una palabra clave («GTA-V» → «gta 5»; números
                          hasta 9999 en palabras, español e inglés; «&»/«and» → «y»; ordinal final como entrega)
  compacta(text)          canon sin espacios ni artículo inicial («Spider-Man» = «spiderman», «The Witcher» = «Witcher»)
  leer_numero(ws, i)      (valor, palabras) del número escrito que empieza en ws[i] («dos mil setenta y siete» → 2077)
  safe_name(term)         nombre válido para Windows
  create_folder(root, t)  crea (o reutiliza) la carpeta del término y devuelve su ruta
  add_files(folder, paths) copia videos/imágenes (archivos o carpetas) a la carpeta y devuelve las rutas finales
  terms(folders)          el label de cada carpeta (para detectar menciones)
  link_folder / unlink_folder / linked   carpetas ENLAZADAS del PC (no se copian): raíz/_enlaces.json
  link_file / unlink_file / linked_files ARCHIVOS ENLAZADOS del PC (no se copian): clave «_archivos» del mismo JSON
  delete_keyword(root, t, trash_fn)      manda a la Papelera solo la subcarpeta propia; los enlaces no se tocan
  create_from_mentions(root, terms)      crea las subcarpetas de varias palabras de una vez (sin duplicar)
  move_files(paths, folder)              MUEVE archivos (con su «.creditos.json») a otra carpeta, nombre único
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from functools import lru_cache

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


# Números escritos y romanos → cifras (para canon). Los romanos solo cuentan tras otra palabra («GTA V»), nunca solos.
# 20/11: números hasta 9999 en palabras, en español e inglés («veintitrés», «treinta y uno», «dos mil setenta y siete»,
# «twenty twenty», «two thousand seventy seven»). «un»/«una» no son números (son artículos).
_UNID = {"uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9}
_UNID_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_DIEZ_29 = {"diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
            "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
            "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
            "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
_TEENS_EN = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
             "seventeen": 17, "eighteen": 18, "nineteen": 19}
_DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
            "noventa": 90}
_DECENAS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
               "ninety": 90}
_CIENTOS = {"ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
            "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600,
            "seiscientas": 600, "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
            "novecientos": 900, "novecientas": 900}
# Números de UNA palabra (para mentions: «GTA seis», «Halo veintitrés»): 1–99 y «cien».
NUM_UNA = {k: str(v) for d in (_UNID, _UNID_EN, _DIEZ_29, _TEENS_EN, _DECENAS, _DECENAS_EN) for k, v in d.items()}
NUM_UNA["cien"] = "100"
_EMPIEZA_NUM = set(NUM_UNA) | set(_CIENTOS) | {"mil"}
_NUM_PAL = NUM_UNA          # (nombre antiguo, por compatibilidad)
# Ordinales: solo como número de entrega, al final del nombre y tras otra palabra que no sea artículo
# («Halo segundo» → «halo 2»; «el segundo» y «un segundo» no).
ORDINALES = {"segundo": 2, "segunda": 2, "tercero": 3, "tercera": 3, "tercer": 3, "cuarto": 4, "cuarta": 4,
             "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6, "septimo": 7, "septima": 7, "octavo": 8,
             "octava": 8, "noveno": 9, "novena": 9, "decimo": 10, "decima": 10,
             "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}
ARTICULOS = {"the", "el", "la", "los", "las", "lo", "un", "una", "unos", "unas", "a", "an", "mi", "su", "este",
             "esta", "ese", "esa", "cada", "otro", "otra"}
_ROMANOS = {r.lower(): str(i) for i, r in enumerate(
    ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI"], start=2)}
_LETRAS_NUM = re.compile(r"^([a-z]{2,})(\d{1,3})$")


def _menor_mil(ws, i: int):
    """(valor 1–999, palabras que ocupa) del número escrito que empieza en ws[i], o None."""
    n = len(ws)
    j, val, ok = i, 0, False
    w = ws[j] if j < n else None
    if w == "cien":
        return 100, 1
    if w in _CIENTOS:
        val, j, ok = _CIENTOS[w], j + 1, True
    elif w in _UNID_EN and j + 1 < n and ws[j + 1] == "hundred":
        val, j, ok = _UNID_EN[w] * 100, j + 2, True
        if j + 1 < n and ws[j] == "and" and (ws[j + 1] in _UNID_EN or ws[j + 1] in _TEENS_EN
                                            or ws[j + 1] in _DECENAS_EN):
            j += 1
    w = ws[j] if j < n else None
    if w in _DECENAS or w in _DECENAS_EN:
        val, j, ok = val + (_DECENAS.get(w) or _DECENAS_EN[w]), j + 1, True
        if w in _DECENAS and j + 1 < n and ws[j] == "y" and ws[j + 1] in _UNID:
            val, j = val + _UNID[ws[j + 1]], j + 2
        elif w in _DECENAS_EN and j < n and ws[j] in _UNID_EN:
            val, j = val + _UNID_EN[ws[j]], j + 1
    elif w in _DIEZ_29 or w in _TEENS_EN:
        val, j, ok = val + (_DIEZ_29.get(w) or _TEENS_EN[w]), j + 1, True
    elif w in _UNID or w in _UNID_EN:
        val, j, ok = val + (_UNID.get(w) or _UNID_EN[w]), j + 1, True
    return (val, j - i) if ok else None


def leer_numero(ws, i: int = 0):
    """(valor, palabras que ocupa) del número escrito en palabras que empieza en ws[i] (claves sin tildes), o None.
    Hasta 9999: «dos mil setenta y siete» → 2077, «mil novecientos noventa y ocho» → 1998, «twenty twenty» → 2020,
    «nineteen eighty four» → 1984. Un número de cifras («2077») también vale (una palabra)."""
    n = len(ws)
    if i >= n:
        return None
    w = ws[i]
    if w.isdigit() and len(w) <= 4:
        return int(w), 1
    if w not in _EMPIEZA_NUM and w not in _TEENS_EN and w not in _DECENAS_EN:
        return None
    r = _menor_mil(ws, i)
    j = i
    if w == "mil":
        val, j = 1000, i + 1
    elif r and i + r[1] < n and ws[i + r[1]] in ("mil", "thousand") and r[0] < 10:
        val, j = r[0] * 1000, i + r[1] + 1
    else:
        if r and r[1] <= 2 and 10 <= r[0] <= 99 and (w in _TEENS_EN or w in _DECENAS_EN):   # año en inglés
            r2 = _menor_mil(ws, i + r[1])
            if r2 and 10 <= r2[0] <= 99 and r2[1] <= 2 and ws[i + r[1]] not in _UNID_EN:
                return r[0] * 100 + r2[0], r[1] + r2[1]
        return r
    if j + 1 < n and ws[j] == "and" and _menor_mil(ws, j + 1):
        j += 1
    r2 = _menor_mil(ws, j)
    if r2:
        val, j = val + r2[0], j + r2[1]
    return val, j - i


def _cifras(ws: list) -> list:
    """Las palabras con los números escritos ya en cifras («dos mil setenta y siete» → «2077»)."""
    out: list = []
    i, n = 0, len(ws)
    while i < n:
        w = ws[i]
        if w in _EMPIEZA_NUM or w in _TEENS_EN or w in _DECENAS_EN:
            r = leer_numero(ws, i)
            if r:
                out.append(str(r[0]))
                i += r[1]
                continue
        out.append(w)
        i += 1
    return out


@lru_cache(maxsize=65536)
def canon(text: str) -> str:
    """Forma canónica de una palabra clave para agrupar sus variantes: sin tildes ni mayúsculas, guiones como
    espacios, letras pegadas a su número separadas («gta5» → «gta 5»), números escritos (hasta 9999, español e inglés)
    y romanos en cifras («GTA cinco», «GTA V», «GTA-V» → «gta 5»; «Cyberpunk dos mil setenta y siete» → «cyberpunk
    2077»), apóstrofos fuera («Assassin's» = «Assassins»), «&» / «and» → «y», y un ordinal al final del nombre como
    número de entrega («Halo segundo» → «halo 2»). «X» tras «series» no es 10 («Xbox Series X»)."""
    s = norm(str(text or "").replace("-", " ").replace("_", " ").replace("&", " y "))
    ws: list[str] = []
    for w in s.split():
        m = _LETRAS_NUM.match(w)
        ws += [m.group(1), m.group(2)] if m else [w]
    ws = _cifras(ws)
    if len(ws) >= 3 and ws[-2] in ("parte", "part") and (ws[-1].isdigit() or ws[-1] in _ROMANOS):
        del ws[-2]
    out: list[str] = []
    ult = len(ws) - 1
    for i, x in enumerate(ws):
        if out and x in _ROMANOS and out[-1] not in ARTICULOS and not (x == "x" and out[-1] == "series"):
            x = _ROMANOS[x]
        elif x == "and":
            x = "y"
        elif i == ult and out and x in ORDINALES and out[-1] not in ARTICULOS and not out[-1].isdigit():
            x = str(ORDINALES[x])
        out.append(x)
    return " ".join(out)


_ARTICULO_INICIAL = {"the", "el", "la", "los", "las"}


def compactar(palabras) -> str:
    """Palabras canónicas → clave sin espacios («spider man» → «spiderman»), sin el artículo inicial si no deja algo
    corto o ambiguo («the witcher 3» → «witcher3»; «la x» y «el 2» se quedan). Dos números seguidos no se pegan."""
    ws = list(palabras)
    if len(ws) >= 2 and ws[0] in _ARTICULO_INICIAL:
        resto = "".join(ws[1:])
        if len(resto) >= 3 and not resto.isdigit() and len(ws[1]) >= 3:
            ws = ws[1:]
    out = ""
    for w in ws:
        if out and out[-1].isdigit() and w[:1].isdigit():
            out += " "
        out += w
    return out


@lru_cache(maxsize=65536)
def junta(text: str) -> str:
    """Como compacta() pero SIN quitar el artículo: «Los Ángeles» → «losangeles» (≠ «Ángeles»)."""
    out = ""
    for w in canon(text).split():
        if out and out[-1].isdigit() and w[:1].isdigit():
            out += " "
        out += w
    return out


@lru_cache(maxsize=65536)
def compacta(text: str) -> str:
    """Clave para comparar variantes de una palabra clave: canon() sin espacios ni artículo inicial. «Spider-Man»,
    «spiderman» y «Spider Man» → «spiderman»; «The Witcher» y «Witcher» → «witcher»; «Assassin's Creed» y «Assassins
    Creed» → «assassinscreed»; «Ratchet & Clank» y «Ratchet and Clank» → «ratchetyclank»; «GTA cinco» → «gta5»."""
    return compactar(canon(text).split())


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
    c = canon(term)                         # variantes: «GTA V», «gta5», «GTA cinco» ↔ la carpeta «GTA 5»
    if c:
        for f in folders:
            for alias in _aliases_raw(f.get("name") or f.get("label") or ""):
                if canon(alias) == c:
                    return f
    k = compacta(term)                      # sin espacios ni artículo: «spiderman» ↔ «Spider-Man», «Witcher» ↔ «The…»
    if k and len(k) >= 3:
        for f in folders:
            for alias in _aliases_raw(f.get("name") or f.get("label") or ""):
                if compacta(alias) == k:
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


def move_files(paths: list[str], folder: str, sidecars: tuple[str, ...] = (".creditos.json",)) -> tuple[list, list]:
    """MUEVE archivos a «folder» (p. ej. de lo bajado de internet a una carpeta del usuario). Cada uno se lleva sus
    archivos acompañantes (mismo nombre + «.creditos.json») con el nombre nuevo; si ya existe uno igual, se usa
    «nombre (2).ext». Devuelve (movidos [(origen, destino)], fallos [(origen, motivo)]). Si un archivo no se puede
    mover (abierto en otro programa…), se queda donde estaba y no deja copias a medias en el destino."""
    os.makedirs(folder, exist_ok=True)
    movidos: list = []
    fallos: list = []
    from .soltar_archivos import soltando
    # (🔓 el visor, el motor propio y los análisis los sueltan antes: abiertos, Windows no deja moverlos; al acabar,
    #  bien o mal, el visor puede volver a abrirlos)
    with soltando([x for x in paths or [] if x and not _same(os.path.dirname(os.path.abspath(x)), folder)]):
        for p in dict.fromkeys(os.path.abspath(x) for x in paths or []):
            if not os.path.isfile(p):
                fallos.append((p, "ya no existe"))
                continue
            if _same(os.path.dirname(p), folder):        # ya está ahí
                movidos.append((p, p))
                continue
            dest = _unique_dest(folder, os.path.basename(p))
            try:
                shutil.move(p, dest)
            except OSError as exc:
                if os.path.isfile(p) and os.path.exists(dest):   # (otra unidad: copió pero no pudo borrar el original)
                    try:
                        os.remove(dest)
                    except OSError:
                        pass
                fallos.append((p, str(exc)))
                continue
            base_src, base_dst = os.path.splitext(p)[0], os.path.splitext(dest)[0]
            for suf in sidecars:
                if os.path.isfile(base_src + suf):
                    try:
                        shutil.move(base_src + suf, base_dst + suf)
                    except OSError:
                        pass
            movidos.append((p, os.path.abspath(dest)))
    return movidos, fallos
