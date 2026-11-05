"""
📁 Carpetas de «Material» (taller de miniaturas): ordenar las imágenes que se usan en las miniaturas (fuego, ojos,
agua, logos…). El usuario: «que me dé la opción de crear carpetas… ordenadas de forma de abecedario… una imagen como
principal… que me dé la opción de eliminarlas… una ruta a mi carpeta donde tengo todas las cosas… que me sugiera».

Dos clases de carpetas:
  · las de Reclaimer: datos/material/<nombre> (se crean aquí; lo que se suelta en ellas se COPIA dentro);
  · las tuyas, vinculadas (p. ej. tu carpeta de imágenes del disco): se ven en su sitio, sin copiar ni tocar nada
    (de ellas solo se puede «quitar de la lista»).
La portada de cada carpeta es la imagen marcada como «principal» o, si no, la primera.
Borrar manda a la Papelera (se puede recuperar).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import string
import unicodedata
from pathlib import Path

from .paths import app_data_dir

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
_KEY = "miniatura/carpetas_vinculadas"


def managed_root() -> Path:
    d = app_data_dir() / "material"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings("EditorIA", "EditorIA")


def sort_key(name: str) -> str:
    """Orden de abecedario sin importar tildes ni mayúsculas."""
    n = unicodedata.normalize("NFD", name.lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def is_image(path: str) -> bool:
    return path.lower().endswith(IMG_EXT)


def is_managed(path: str) -> bool:
    try:
        Path(path).resolve().relative_to(managed_root().resolve())
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ carpetas vinculadas
def linked() -> list[str]:
    v = _settings().value(_KEY, [])
    if isinstance(v, str):
        v = [v] if v else []
    return [p for p in (v or []) if os.path.isdir(p)]


def link(path: str) -> bool:
    path = os.path.normpath(path)
    if not os.path.isdir(path) or is_managed(path):
        return False
    cur = linked()
    if any(os.path.normcase(p) == os.path.normcase(path) for p in cur):
        return False
    _settings().setValue(_KEY, cur + [path])
    return True


def unlink(path: str):
    _settings().setValue(_KEY, [p for p in linked() if os.path.normcase(p) != os.path.normcase(path)])


def suggestions(limit: int = 4) -> list[str]:
    """Carpetas de imágenes que hay en el PC y aún no están vinculadas: «Imágenes» del usuario y, en la raíz de cada
    disco, las que se llaman como imágenes, fotos, recursos o miniaturas (sin buscar más hondo: es instantáneo)."""
    found: list[str] = []
    home = Path.home()
    for d in (home / "Pictures", home / "Imágenes", home / "OneDrive" / "Pictures", home / "OneDrive" / "Imágenes"):
        if d.is_dir():
            found.append(str(d))
    words = ("imagen", "image", "foto", "photo", "recurs", "miniatur", "thumbnail", "png")
    for letter in string.ascii_uppercase[2:]:                 # C:, D:, E:…
        root = Path(f"{letter}:\\")
        try:
            if not root.exists():
                continue
            for d in root.iterdir():
                if d.is_dir() and not d.name.startswith(("$", ".")) and any(w in sort_key(d.name) for w in words):
                    found.append(str(d))
        except OSError:
            continue
    have = {os.path.normcase(p) for p in linked()}
    out, seen = [], set()
    for p in found:
        k = os.path.normcase(p)
        if k not in have and k not in seen:
            seen.add(k)
            out.append(p)
    return out[:limit]


# ------------------------------------------------------------------ contenido
def roots() -> list[dict]:
    """Las carpetas de arriba del todo (las de Reclaimer y las vinculadas), en orden de abecedario."""
    out = [{"path": str(p), "name": p.name, "managed": True}
           for p in managed_root().iterdir() if p.is_dir() and not p.name.startswith(("_", "."))]
    out += [{"path": p, "name": os.path.basename(p.rstrip("\\/")) or p, "managed": False} for p in linked()]
    return sorted(out, key=lambda r: sort_key(r["name"]))


def list_dir(path: str, max_images: int = 2000) -> tuple[list[str], list[str]]:
    """(subcarpetas, imágenes) de una carpeta — solo lo de dentro, sin bajar más (rápido aunque sea enorme)."""
    folders, images = [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith((".", "$", "_portadas")):
                    continue
                if e.is_dir(follow_symlinks=False):
                    folders.append(e.path)
                elif is_image(e.name) and len(images) < max_images:
                    images.append(e.path)
    except OSError:
        pass
    folders.sort(key=lambda p: sort_key(os.path.basename(p)))
    images.sort(key=lambda p: sort_key(os.path.basename(p)))
    return folders, images


def _covers_file() -> Path:
    return managed_root() / "_portadas.json"


def _covers() -> dict:
    try:
        return json.loads(_covers_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_cover(folder: str, image: str):
    c = _covers()
    c[os.path.normcase(os.path.normpath(folder))] = image
    _covers_file().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def cover(folder: str) -> str | None:
    """La imagen «principal» de la carpeta; si no hay, la primera (o la de su primera subcarpeta, sin bajar mucho)."""
    c = _covers().get(os.path.normcase(os.path.normpath(folder)))
    if c and os.path.isfile(c):
        return c
    todo, depth = [folder], 0
    while todo and depth < 3:
        nxt = []
        for f in todo:
            subs, imgs = list_dir(f, max_images=1)
            if imgs:
                return imgs[0]
            nxt += subs[:6]
        todo, depth = nxt, depth + 1
    return None


# ------------------------------------------------------------------ cambios (solo en las de Reclaimer)
def _clean(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return name[:60] or "Carpeta"


def create(name: str, parent: str | None = None) -> str:
    base = Path(parent) if parent and is_managed(parent) else managed_root()
    name = _clean(name)
    p, i = base / name, 2
    while p.exists():
        p, i = base / f"{name} ({i})", i + 1
    p.mkdir(parents=True)
    return str(p)


def rename(folder: str, name: str) -> str | None:
    if not is_managed(folder) or Path(folder).resolve() == managed_root().resolve():
        return None
    new = Path(folder).with_name(_clean(name))
    if new.exists():
        return None
    os.rename(folder, new)
    return str(new)


def add_files(folder: str, files: list[str]) -> list[str]:
    """Copia imágenes a una carpeta de Reclaimer (las tuyas no se tocan). Devuelve las copias."""
    if not is_managed(folder):
        return []
    out = []
    for f in files:
        if not (os.path.isfile(f) and is_image(f)):
            continue
        dst = Path(folder) / os.path.basename(f)
        if dst.exists() and os.path.samefile(f, dst):
            continue
        stem, ext, i = dst.stem, dst.suffix, 2
        while dst.exists():
            dst, i = Path(folder) / f"{stem} ({i}){ext}", i + 1
        shutil.copy2(f, dst)
        out.append(str(dst))
    return out


def trash(path: str) -> bool:
    """A la Papelera (recuperable). Solo dentro de las carpetas de Reclaimer."""
    if not is_managed(path) or Path(path).resolve() == managed_root().resolve():
        return False
    from PySide6.QtCore import QFile
    ok = QFile.moveToTrash(path)
    return bool(ok[0] if isinstance(ok, tuple) else ok)
