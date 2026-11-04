"""
Clasificación básica de archivos por el nombre de sus carpetas.

Ejemplo: /Proyecto_Gears/Gameplay/Combat/clip.mp4 -> categoría "Gameplay", etiqueta "Combat".
Esta es la versión sin IA (Fase 1). En la Fase 2, el módulo ai/clip_classification
analizará el contenido real de cada clip.
"""
from __future__ import annotations

import os
import re
import unicodedata

from .model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar textos ("Cinemáticas" == "cinematicas")."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", normalize(text)) if w]


# (categoría, palabras clave, tipos de archivo permitidos)
CATEGORY_RULES = [
    ("Narración", {"voz", "voice", "narracion", "narration", "voiceover", "vo", "locucion"}, {KIND_AUDIO}),
    ("Música", {"music", "musica", "ost", "soundtrack", "bso"}, {KIND_AUDIO}),
    ("Efectos de sonido", {"sfx", "efectos", "fx", "sonidos", "sounds"}, {KIND_AUDIO}),
    ("Gameplay", {"gameplay", "jugabilidad", "partida"}, {KIND_VIDEO, KIND_IMAGE}),
    ("Cinemáticas", {"cinematic", "cinematics", "cinematica", "cinematicas", "cutscene", "cutscenes"},
     {KIND_VIDEO, KIND_IMAGE}),
    ("Imágenes", {"images", "image", "imagenes", "imagen", "fotos", "screenshots", "capturas", "img"},
     {KIND_IMAGE}),
]

FALLBACK_CATEGORY = {KIND_VIDEO: "Videos", KIND_AUDIO: "Audio", KIND_IMAGE: "Imágenes"}

# Orden en el que se muestran las categorías en la biblioteca.
CATEGORY_ORDER = ["Narración", "Gameplay", "Cinemáticas", "Videos", "Imágenes",
                  "Música", "Efectos de sonido", "Audio"]


def _match(text: str, kind: str) -> tuple[str, set[str]] | None:
    ws = set(words(text))
    for category, keywords, kinds in CATEGORY_RULES:
        if kind in kinds and ws & keywords:
            return category, keywords
    return None


def classify(path: str, kind: str, root: str | None = None) -> tuple[str, list[str]]:
    """Devuelve (categoría, etiquetas) para un archivo."""
    folder = os.path.dirname(os.path.abspath(path))
    if root:
        rel = os.path.relpath(folder, os.path.abspath(root))
        parts = [] if rel in (".", "") else rel.split(os.sep)
    else:
        parts = []
    candidates = parts + ([os.path.basename(folder)] if not parts else []) + \
        [os.path.splitext(os.path.basename(path))[0]]

    category, keywords = None, set()
    for text in candidates:
        found = _match(text, kind)
        if found:
            category, keywords = found
            break
    category = category or FALLBACK_CATEGORY.get(kind, "Sin clasificar")
    # Las subcarpetas que no son la propia categoría se vuelven etiquetas (ej. "Combat", "Marcus").
    tags = [p for p in parts if not (set(words(p)) & keywords)]
    return category, tags


def matches_query(query: str, *fields: str) -> bool:
    """Búsqueda básica: todas las palabras de la consulta deben aparecer en algún campo."""
    q = words(query)
    if not q:
        return True
    haystack = " ".join(normalize(f) for f in fields)
    return all(w in haystack for w in q)
