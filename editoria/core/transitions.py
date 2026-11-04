"""
Transiciones entre dos clips seguidos de una pista de video (como en DaVinci Resolve).

Se guardan en el clip de la DERECHA del corte: Clip.fx["trans"] = {"type": "fade", "dur": 0.5}.
La transición se centra en el corte: empieza dur/2 antes y acaba dur/2 después, así el video no
cambia de duración. Para cruzar las imágenes hace falta un poco de material extra («handles») de
cada clip; si el archivo no lo tiene, se alarga el borde con un fotograma quieto.
Al exportar se usa el filtro xfade de FFmpeg (todo local).
"""
from __future__ import annotations

from .model import KIND_IMAGE, TRACK_VIDEO, Clip, Project

# (clave de xfade, nombre, descripción)
CATALOG: list[tuple[str, str, str]] = [
    ("fade", "Disolver", "Una imagen se funde suavemente en la otra (la más usada)."),
    ("fadeblack", "Fundido a negro", "Pasa por negro: cambio de tema o de escena."),
    ("fadewhite", "Destello blanco", "Pasa por blanco: golpe, impacto o recuerdo."),
    ("dissolve", "Disolver con grano", "Se mezclan con un grano de puntos."),
    ("hblur", "Latigazo", "Desenfoque horizontal rápido (whip): ideal en edits."),
    ("zoomin", "Zoom", "La imagen se acerca y deja paso a la siguiente."),
    ("slideleft", "Deslizar ←", "La nueva imagen entra empujando desde la derecha."),
    ("slideright", "Deslizar →", "La nueva imagen entra desde la izquierda."),
    ("wipeleft", "Barrido ←", "Una cortina recta descubre la siguiente imagen."),
    ("smoothleft", "Barrido suave ←", "Cortina con borde suave."),
    ("circleopen", "Círculo", "Se abre un círculo desde el centro."),
    ("radial", "Reloj", "Barrido circular como las agujas de un reloj."),
    ("pixelize", "Pixelado", "Se pixela y se recompone: efecto glitch/videojuego."),
    ("hlwind", "Viento", "Se deshace en tiras hacia un lado."),
    ("squeezeh", "Aplastar", "La imagen se comprime y aparece la otra."),
]
NAMES = {k: n for k, n, _d in CATALOG}
DEFAULT = "fade"
MIN_DUR, MAX_DUR = 0.1, 3.0

# Las transiciones que pone la IA: más cortas / normales / más largas (lo eliges con clic derecho en una transición)
AI_SCALES = [(0.5, "Más cortas"), (1.0, "Normales"), (1.5, "Más largas"), (2.0, "Muy largas")]


def ai_scale() -> float:
    from PySide6.QtCore import QSettings
    try:
        v = float(QSettings("EditorIA", "EditorIA").value("transiciones/escala_ia", 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return v if 0.2 <= v <= 3.0 else 1.0


def set_ai_scale(v: float):
    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").setValue("transiciones/escala_ia", float(v))


def ai_trans(ttype: str, base: float, left: Clip, right: Clip) -> dict:
    """La transición que pone la IA: su duración «base» por tu escala, marcada como de la IA."""
    return {"type": ttype, "dur": round(clamp_dur(base * ai_scale(), left, right), 3), "ai": True,
            "base": round(float(base), 3)}


def of(c: Clip) -> dict | None:
    t = (c.fx or {}).get("trans")
    return t if isinstance(t, dict) and t.get("type") in NAMES else None


def is_visual(p: Project, c: Clip) -> bool:
    tr = p.track(c.track_id)
    return c.text is None and tr is not None and tr.kind == TRACK_VIDEO and p.media_of(c) is not None


def previous(p: Project, c: Clip) -> Clip | None:
    """El clip pegado justo antes de c en su pista (si lo hay)."""
    best = None
    for o in p.clips_on(c.track_id):
        if o.id != c.id and abs(o.end - c.start) < 1e-3:
            best = o
    return best


def pairs(p: Project, track_id: str) -> list[tuple[Clip, Clip, dict]]:
    """Transiciones válidas de una pista: [(izquierda, derecha, {"type", "dur"})]."""
    out = []
    clips = p.clips_on(track_id)
    for left, right in zip(clips, clips[1:]):
        t = of(right)
        if t is None or abs(left.end - right.start) > 1e-3 or not left.enabled or not right.enabled:
            continue
        if not (is_visual(p, left) and is_visual(p, right)) or (left.layout or None) != (right.layout or None):
            continue
        d = clamp_dur(t.get("dur", 0.5), left, right)
        out.append((left, right, {"type": t["type"], "dur": d, "ai": bool(t.get("ai"))}))
    return out


def clamp_dur(d: float, left: Clip, right: Clip) -> float:
    return max(MIN_DUR, min(float(d), MAX_DUR, 0.9 * left.duration, 0.9 * right.duration))


def handles(p: Project, c: Clip) -> tuple[float, float]:
    """Segundos de material extra (en la timeline) antes y después del clip."""
    m = p.media_of(c)
    if m is None or m.kind == KIND_IMAGE or c.speed <= 0 or not m.duration:
        return 1e9, 1e9
    before = c.source_in / c.speed
    after = max(0.0, m.duration - c.source_in - c.src_len) / c.speed
    return (after, before) if c.reverse else (before, after)


def preview_fx(p: Project, c: Clip) -> dict | None:
    """Aproximación para el visor (que muestra un clip por pista): un fundido a negro (o destello)
    a cada lado del corte. El resultado exacto se ve con «▶ Ver la transición» o al exportar."""
    fx = dict(c.fx or {})
    changed = False
    t_in = None
    prev = previous(p, c)
    if prev is not None:
        for left, right, t in pairs(p, c.track_id):
            if right.id == c.id:
                t_in = t
    if t_in:
        half = t_in["dur"] / 2
        if t_in["type"] == "fadewhite":
            fx["flash"] = max(float(fx.get("flash", 0)), half)
        else:
            fx["fade_in"] = max(float(fx.get("fade_in", 0)), half)
        changed = True
    for left, right, t in pairs(p, c.track_id):
        if left.id == c.id and t["type"] != "fadewhite":
            fx["fade_out"] = max(float(fx.get("fade_out", 0)), t["dur"] / 2)
            changed = True
    return fx if changed else c.fx
