"""
🖼 Imágenes encima de un video («overlay»): duración automática por la frase que se dice y estilo de colocación.

Al soltar una imagen en una pista de video que tiene otro video debajo (en ese momento):
  · dura lo que dura la frase que se dice en ese instante (pausa > 0,35 s antes y después), entre 1,5 y 6 s;
    sin transcripción, la duración por defecto de siempre;
  · estilo «Encima, fondo desenfocado y sombra» (por defecto): centrada a ~70 % del alto, con sombra, entra con una
    escala del 92 % al 100 % y un fundido (0,25 s), sale con fundido, y el video de debajo se desenfoca SOLO mientras
    está la imagen.

Los estilos son los efectos que ya existen (fotogramas clave de posición y tamaño, fundido de entrada, sombra y
opacidad), así que se ven igual en el visor y al exportar. Aquí solo hay reglas puras (sin ventanas ni Qt); el
controlador (controller.add_image_overlay / set_image_style) hace los cambios y el deshacer.
"""
from __future__ import annotations

import bisect

from .model import DEFAULT_IMAGE_DURATION, KIND_IMAGE, TRACK_VIDEO, Project

PAUSE = 0.35          # pausa (s) que separa dos frases
DUR_MIN, DUR_MAX = 1.5, 6.0
ENTER = 0.25          # entrada suave (s): escala 92 % → 100 % y fundido
EXIT = 0.3            # salida con fundido (s)
SHRINK = 0.92
BLUR = 0.6            # desenfoque del video de debajo (0–1, como el efecto «Desenfoque»)
DECOR_KEYS = ("enter", "shadow", "outline")

AUTO_BOX = {"x": 0.05, "y": 0.15, "w": 0.9, "h": 0.7, "fit": "contain", "bg": "none"}   # ~70 % del alto
# Nombre de cada estilo, en el orden del menú «🖼 Estilo de imagen»
STYLES = [
    ("auto", "Encima, fondo desenfocado y sombra"),
    ("corner", "Esquina superior derecha"),
    ("left", "Costado izquierdo"),
    ("right", "Costado derecho"),
    ("full", "Pantalla completa"),
    ("none", "Sin animación"),
]
STYLE_NAMES = dict(STYLES)


def phrase_run(words: list, s: float) -> tuple[float, float] | None:
    """Frase (inicio, fin) en segundos del archivo que se dice en s. Una frase es un tramo de palabras seguidas en
    el que ninguna pausa supera PAUSE. None si s cae en un silencio largo (o no hay palabras)."""
    if not words:
        return None
    starts = [w[0] for w in words]
    j = bisect.bisect_right(starts, s) - 1
    if j < 0:
        if starts[0] - s > PAUSE:
            return None
        j = 0
    if s > words[j][1] + PAUSE:
        return None
    a = j
    while a > 0 and words[a][0] - words[a - 1][1] <= PAUSE:
        a -= 1
    b = j
    while b < len(words) - 1 and words[b + 1][0] - words[b][1] <= PAUSE:
        b += 1
    return float(words[a][0]), float(words[b][1])


def voice_duration(p: Project, t: float) -> float | None:
    """Lo que QUEDA de la frase que se dice en el momento t (segundos de la timeline), según las transcripciones del
    proyecto: la imagen termina cuando termina la frase aunque se suelte a mitad. None si no hay transcripción ahí."""
    if not p.transcripts:
        return None
    for c in p.clips.values():
        if c.media_id not in p.transcripts or c.speed <= 0 or not (c.start <= t < c.end):
            continue
        words = (p.transcripts.get(c.media_id) or {}).get("words") or []
        src = c.src_at(min(max(t - c.start, 0.0), c.duration))
        run = phrase_run(words, src)
        if run is not None:
            return max(0.0, run[1] - max(src, run[0])) / c.speed
    return None


def auto_duration(p: Project, t: float) -> tuple[float, bool]:
    """(duración de una imagen soltada en t, ¿viene de la frase?)."""
    d = voice_duration(p, t)
    if d is None:
        return DEFAULT_IMAGE_DURATION, False
    return min(DUR_MAX, max(DUR_MIN, d)), True


def visual_under(p: Project, track_id: str, a: float, b: float) -> list:
    """Clips de video (o imágenes) en pistas DEBAJO de track_id (en la pantalla, las de abajo van después en la lista)
    que se solapan con [a, b)."""
    idx = p.track_index(track_id)
    lower = {t.id for i, t in enumerate(p.tracks) if i > idx and t.kind == TRACK_VIDEO}
    return [c for c in p.clips.values() if c.track_id in lower and c.text is None and c.start < b - 1e-6
            and c.end > a + 1e-6]


def _box(x: float, y: float, w: float, h: float) -> dict:
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4), "fit": "contain", "bg": "none"}


def style_plan(style: str, dur: float) -> dict:
    """Lo que cambia un estilo: {layout, layout_kf, op_kf, fx (decoración), blur (¿desenfocar lo de debajo?)}.
    Las claves de posición y de opacidad van en segundos desde el inicio del clip (es una imagen)."""
    dur = max(0.2, float(dur))
    out_fade = [{"t": 0.0, "v": 1.0}, {"t": round(max(0.0, dur - EXIT), 3), "v": 1.0}, {"t": round(dur, 3), "v": 0.0}]
    fade_in = {"enter": {"from": "fade", "dur": ENTER}, "shadow": {"opacity": 0.6}}
    if style == "auto":
        a = AUTO_BOX
        sw, sh = a["w"] * SHRINK, a["h"] * SHRINK
        small = _box(a["x"] + (a["w"] - sw) / 2, a["y"] + (a["h"] - sh) / 2, sw, sh)
        full = _box(a["x"], a["y"], a["w"], a["h"])
        return {"layout": dict(full), "layout_kf": [dict(small, t=0.0), dict(full, t=ENTER)], "op_kf": out_fade,
                "fx": fade_in, "blur": True}
    if style in ("corner", "left", "right"):
        box = {"corner": _box(0.62, 0.06, 0.33, 0.33), "left": _box(0.03, 0.15, 0.45, 0.7),
               "right": _box(0.52, 0.15, 0.45, 0.7)}[style]
        return {"layout": box, "layout_kf": [], "op_kf": out_fade, "fx": fade_in, "blur": False}
    if style == "full":
        return {"layout": None, "layout_kf": [], "op_kf": [], "fx": {}, "blur": False}
    # «none» (sin animación): centrada como el automático, sin sombra, sin fundidos ni desenfoque
    return {"layout": dict(AUTO_BOX), "layout_kf": [], "op_kf": [], "fx": {}, "blur": False}
