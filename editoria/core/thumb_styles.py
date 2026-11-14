"""
⭐ Mis estilos de miniatura: guardar el aspecto de un texto, una imagen o una forma (fuente, colores, contornos, sombra,
brillo, relleno, fusión…) con un nombre, y ponérselo a otra capa con un clic.

Se guardan en datos/estilos_miniatura.json: [{"name", "kind": "text" | "image" | "shape", "style": {clave: valor}}].
No guardan ni el texto, ni la imagen, ni el sitio, ni el tamaño de la capa: solo su aspecto.
"""
from __future__ import annotations

import copy
import json
import os

STYLE_KEYS = {
    "text": ("font", "weight", "italic", "spacing", "line", "color", "accent", "uppercase", "text_fill",
             "outline", "outlines", "shadow", "glow", "blend"),
    "image": ("adj", "feather", "fade", "outline", "outlines", "shadow", "glow", "blend"),
    "shape": ("fill", "stroke", "stroke_w", "radius", "gradient", "outline", "outlines", "shadow", "glow", "blend"),
}
RUTA: str | None = None          # (las pruebas la cambian para no tocar tus estilos)


def path() -> str:
    if RUTA:
        return RUTA
    from .paths import app_data_dir
    return os.path.join(str(app_data_dir()), "estilos_miniatura.json")


def kind_of(lay: dict) -> str | None:
    if lay.get("blur_area") or lay.get("slot"):
        return None
    return lay.get("kind") if lay.get("kind") in STYLE_KEYS else None


def load() -> list[dict]:
    try:
        data = json.load(open(path(), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("kind") in STYLE_KEYS and isinstance(d.get("style"), dict)]


def _save(lista: list[dict]):
    os.makedirs(os.path.dirname(path()) or ".", exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path())


def of_kind(kind: str) -> list[dict]:
    return [d for d in load() if d["kind"] == kind]


def style_of(lay: dict) -> dict:
    """El aspecto de la capa (solo las claves de su tipo que tiene)."""
    kind = kind_of(lay)
    return {k: copy.deepcopy(lay[k]) for k in STYLE_KEYS.get(kind, ()) if k in lay}


def add(name: str, lay: dict) -> dict | None:
    """Guarda el aspecto de la capa con ese nombre (si ya hay uno igual de ese tipo, lo sustituye)."""
    kind = kind_of(lay)
    name = (name or "").strip()[:40]
    if not kind or not name:
        return None
    nuevo = {"name": name, "kind": kind, "style": style_of(lay)}
    lista = [d for d in load() if not (d["kind"] == kind and d["name"].casefold() == name.casefold())]
    _save([nuevo] + lista)
    return nuevo


def remove(name: str, kind: str):
    _save([d for d in load() if not (d["kind"] == kind and d["name"] == name)])


def rename(name: str, kind: str, nuevo: str) -> bool:
    nuevo = (nuevo or "").strip()[:40]
    lista = load()
    if not nuevo or any(d["kind"] == kind and d["name"].casefold() == nuevo.casefold() and d["name"] != name
                        for d in lista):
        return False
    for d in lista:
        if d["kind"] == kind and d["name"] == name:
            d["name"] = nuevo
    _save(lista)
    return True


def changes(lay: dict, estilo: dict) -> dict:
    """Lo que hay que cambiarle a la capa para que tenga ese estilo (nada si no es de su tipo)."""
    if kind_of(lay) != estilo.get("kind"):
        return {}
    return {k: copy.deepcopy(v) for k, v in estilo["style"].items() if k in STYLE_KEYS[estilo["kind"]]}
