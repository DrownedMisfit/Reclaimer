"""
🎨 COLOR DE CADA CLIP POR SU ORIGEN (fase 7): el montaje se distingue de un vistazo (narración, gameplay, cinemática,
tráiler, noticia o captura, meme, B-roll de la IA, palabra clave, escena, música, efectos). Sale de lo que ya se sabe:
la categoría y el tipo que la IA vio en Medios, la nota del clip (quién lo puso), la pista (su papel) y si el archivo
tiene transcripción. El «Color de clip» que eliges tú manda siempre; lo desconocido se queda con el color de su tipo.

  ORIGENES                     clave -> (nombre, color)
  origen(c, m, tipo_pista, papel, narraciones) -> clave | None
  color_pista(papel) -> color | None   el de la insignia de una pista con papel (voz, música, efectos)
"""
from __future__ import annotations

import os

# (paleta revisada 21/11: entre los colores de una misma pista ΔE ≥ 20 y todos con contraste ≥ 4,5:1 con el texto
#  del título (#e6e6e8); «sin clasificar» tiene su gris propio: un azul o un verde ya no dicen «gameplay» o «narración»
#  si no se sabe)
ORIGENES: dict[str, tuple[str, str]] = {
    "narracion": ("Narración", "#2a6e4e"),
    "musica": ("Música", "#6a4f9a"),
    "efectos": ("Efectos de sonido", "#7a5c12"),
    "audio": ("Sonido sin clasificar", "#4f5a62"),
    "gameplay": ("Gameplay", "#2f5c9c"),
    "cinematica": ("Cinemática", "#166b64"),
    "trailer": ("Tráiler", "#a04614"),
    "noticia": ("Noticia o captura", "#5f5f2c"),
    "meme": ("Meme", "#a03080"),
    "broll_ia": ("B-roll de la IA", "#326c16"),
    "palabra": ("Palabra clave", "#7c5a00"),
    "escena": ("Escena", "#3a46a8"),
    "imagen": ("Imagen", "#7f42ab"),
    "texto": ("Texto", "#b02838"),
    "sin_clasificar": ("Sin clasificar", "#5d6068"),
}
PAPEL = {"voz": "narracion", "musica": "musica", "efectos": "efectos"}
_TRAILER = ("trailer", "tráiler", "teaser")
_NOTICIA = ("noticia", "news", "titular", "captura", "screenshot", "tweet")


_MEMES: list = []


def _es_meme(ruta: str) -> bool:
    """¿Está en la biblioteca de memes? (la carpeta se mira una vez: antes, una vez por clip y por repintado)."""
    if not _MEMES:
        try:
            from . import memes
            _MEMES.append(os.path.normcase(os.path.abspath(memes.carpeta())))
        except Exception:  # noqa: BLE001
            _MEMES.append("")
    base = _MEMES[0]
    return bool(base) and os.path.normcase(str(ruta or "")).startswith(base + os.sep)


def _txt(*partes) -> str:
    return " ".join(str(x or "") for x in partes).lower()


def origen(c, m, tipo_pista: str, papel: str = "", narraciones=()) -> str | None:
    """La clave de ORIGENES de un clip (lo que no se sabe: «sin clasificar», «sonido sin clasificar» o «imagen»).
    Sin Qt; barato (unas comparaciones)."""
    if c.text is not None:
        return "texto"
    if m is None:
        return None
    if tipo_pista == "audio":
        if papel in PAPEL:
            return PAPEL[papel]
        cat = m.category or ""
        if m.id in narraciones or cat == "Narración":
            return "narracion"
        if cat == "Música":
            return "musica"
        if cat in ("Efectos de sonido", "Efectos"):
            return "efectos"
        return "audio"
    nota = c.note or ""
    if nota.startswith("🎬 "):
        return "escena"
    if nota.startswith("B-roll IA") or nota.startswith("IA · B-roll"):
        return "broll_ia"
    if nota.startswith("🔑"):
        return "palabra"
    if _es_meme(m.path):
        return "meme"
    nombre = _txt(m.name, os.path.basename(os.path.dirname(m.path or "")), " ".join(m.tags or []))
    if any(w in nombre for w in _TRAILER):
        return "trailer"
    if any(w in nombre for w in _NOTICIA):
        return "noticia"
    cat, tipo = m.category or "", m.ai_type or ""
    if cat == "Gameplay" or tipo == "Gameplay":
        return "gameplay"
    if cat == "Cinemáticas" or tipo == "Cinemáticas":
        return "cinematica"
    return "imagen" if m.kind == "image" else "sin_clasificar"


def color_pista(papel: str) -> str | None:
    clave = PAPEL.get(papel or "")
    return ORIGENES[clave][1] if clave else None
