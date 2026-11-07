"""
«📍 Poner donde lo dices» (lógica sin ventanas): un clip de Medios en los momentos de una palabra, con su frase
(2–6 s; sin transcripción, 4 s), y el reparto de varios archivos por momentos (uno de cada, cíclico).
Lo usan el panel 🎬 Clips y Medios ▸ 🔑 Palabras clave, así que el resultado es el mismo en los dos sitios.
Un solo paso de deshacer por tanda.

  colocar(ctrl, media_id, hits, avisar)  → (ok, aviso)
  repartir(ctrl, ids, hits)              → (puestos, aviso)
  mmss(t)                                → «mm:ss» (o «h:mm:ss»)
"""
from __future__ import annotations

from . import overlay
from .model import KIND_VIDEO

DURACION_MIN, DURACION_MAX, DURACION_SIN_VOZ = 2.0, 6.0, 4.0     # segundos del clip «donde lo dices»


def mmss(t: float) -> str:
    t = max(0, int(round(t or 0)))
    h, rest = divmod(t, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _tl(h: dict):
    return h.get("tl")


def duracion_frase(proyecto, t: float) -> float:
    """Duración (s) de «donde lo dices» en el momento t: la frase que se dice ahí, entre 2 y 6 s; 4 s sin voz."""
    d = overlay.voice_duration(proyecto, t)
    return DURACION_SIN_VOZ if d is None else min(DURACION_MAX, max(DURACION_MIN, d))


def colocar(ctrl, media_id: str, hits: list[dict], avisar: bool = True) -> tuple[bool, str]:
    """Pone el clip de Medios en cada momento con hora. Devuelve (ok, texto para mostrar)."""
    proyecto = ctrl.project
    m = proyecto.media.get(media_id)
    marcados = sorted((h for h in hits if _tl(h) is not None), key=lambda h: h["tl"])
    if m is None:
        return False, "Ese clip ya no está en Medios."
    if not marcados:
        return False, "No hay momentos con hora donde ponerlo."
    tiempos = [float(h["tl"]) for h in marcados]
    duraciones = [duracion_frase(proyecto, t) for t in tiempos]
    if m.kind == KIND_VIDEO:
        src = min(3.0, 0.1 * float(m.duration or 0))   # salta los logos del principio
    else:
        src = 0.0                                       # las imágenes no tienen principio que saltar
    ids = ctrl.place_clip_at(media_id, tiempos, duraciones, src)
    if not ids:
        return False, "No pude ponerlo: no hay sitio libre o el archivo aún se está analizando."
    if avisar:
        return True, "✓ Puesto en " + " y ".join(mmss(t) for t in tiempos)
    return True, ""


def repartir(ctrl, ids: list[str], hits: list[dict]) -> tuple[list[float], str]:
    """Momento 1 → archivo 1, momento 2 → archivo 2… (cíclico). Un solo paso de Ctrl+Z para toda la tanda."""
    marcados = sorted((h for h in hits if _tl(h) is not None), key=lambda h: h["tl"])
    if not ids or not marcados:
        return [], ""
    grupos: dict[str, list[dict]] = {}
    for k, h in enumerate(marcados):
        grupos.setdefault(ids[k % len(ids)], []).append(h)
    macro = len(grupos) > 1
    if macro:
        ctrl.undo_stack.beginMacro("📍 Poner donde lo dices")
    puestos: list[float] = []
    try:
        for mid, hs in grupos.items():
            ok, _msg = colocar(ctrl, mid, hs, avisar=False)
            if ok:
                puestos += [float(h["tl"]) for h in hs]
    finally:
        if macro:
            ctrl.undo_stack.endMacro()
    if puestos:
        return puestos, f"✓ Puesto {len(puestos)} vez/veces en " + " y ".join(mmss(t) for t in sorted(puestos))
    return [], ""
