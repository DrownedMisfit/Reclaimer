"""
Módulo de IA: PRIMERA VERSIÓN AUTOMÁTICA de un video comentado.

Une los demás módulos (transcripción, limpieza, temas, B-roll, zooms, audio, subtítulos,
revisión) y añade los «toques de cine». Aquí está la lógica sin interfaz; la ventana que
lo ejecuta paso a paso es ui/auto_dialog.py.

Lo aprendido de tu canal (videos de análisis de 5–25 min): B-roll a pantalla completa
(gameplay, tráilers, entrevistas) que cambia cada ~4–7 s (Shorts 2,5–4 s; nunca menos de 3 s / 2 s: con
más cortes no se aprecia lo que enseñas), sin subtítulos dentro del video y con la intro en planos largos.
Si hay música de fondo, los cortes caen en sus golpes (mejor al empezar compás o en los fuertes).
"""
from __future__ import annotations

from ..core import transform

# Qué se limpia de la voz automáticamente (las tomas repetidas: se queda la mejor, la que elige la IA)
CLEAN_KINDS = ("silence", "noise", "filler", "repeat", "retake")

KEN_BURNS_MIN = 3.5     # planos de al menos estos segundos llevan un zoom lento
KEN_BURNS_Z = 1.08      # cuánto se acerca (video)
KEN_BURNS_Z_IMG = 1.14  # en imágenes fijas, más (si no, parecen congeladas)
DIP = 0.22              # segundos de fundido a negro a cada lado de un cambio de tema


def cleanup_ids(suggestions, media_id: str, kinds=CLEAN_KINDS) -> list[str]:
    """Sugerencias de limpieza pendientes que se pueden cortar sin preguntar."""
    return [s.id for s in suggestions
            if s.media_id == media_id and s.status == "pending" and s.cuttable and s.kind in kinds
            and (s.data or {}).get("auto", True) is not False]     # «muy muy», «no no»: pueden ser a propósito


def broll_items(slots: list[dict], media: dict, start_at_zero: bool = True) -> list[dict]:
    """El mejor clip de cada hueco, listo para insert_ranges. El primero empieza en 0 (sin negro)."""
    items = []
    for i, s in enumerate(slots):
        if not s.get("candidates"):
            continue
        a = 0.0 if (i == 0 and start_at_zero) else s["start"]
        want = s["end"] - a

        def room(cand):
            m_ = media.get(cand["media_id"])
            return want if (m_ is None or m_.kind == "image" or not m_.duration) else m_.duration
        # el mejor candidato que LLENA el hueco (si el primero es más corto, quedaba negro hasta el siguiente)
        c = next((x for x in s["candidates"] if room(x) >= want - 0.05), s["candidates"][0])
        dur = want
        m = media.get(c["media_id"])
        src = c["source_in"]
        if m is not None and m.kind != "image" and m.duration:
            if a < s["start"]:          # se adelanta: empezar antes en el clip si se puede
                src = max(0.0, src - (s["start"] - a))
            if src + dur > m.duration:  # no cabe desde ahí: se empieza antes en el clip
                src = max(0.0, m.duration - dur)
            dur = min(dur, m.duration - src)
        if dur > 0.3:
            items.append({"media_id": c["media_id"], "start": a, "duration": dur, "source_in": src,
                          "note": f"B-roll IA: {c['reason']}"})
    # Si aun así queda un hueco (clip corto), el siguiente empieza antes (si su clip lo permite)
    for x, y in zip(items, items[1:]):
        gap = y["start"] - (x["start"] + x["duration"])
        if gap > 0.04:
            my = media.get(y["media_id"])
            back = gap if (my is None or my.kind == "image") else min(gap, y["source_in"])
            y["start"] -= back
            y["duration"] += back
            if my is not None and my.kind != "image":
                y["source_in"] -= back
    return items


def ken_burns(c, is_image: bool, k: int) -> list[dict]:
    """Zoom lento durante todo el plano: alterna acercarse y alejarse, con un leve desplazamiento."""
    a = 0.0 if is_image else c.source_in
    b = a + c.duration
    z = KEN_BURNS_Z_IMG if is_image else KEN_BURNS_Z
    z0, z1 = (1.0, z) if k % 2 == 0 else (z, 1.0)
    x0, x1 = (0.47, 0.53) if k % 4 < 2 else (0.53, 0.47)
    return [{"t": round(a, 3), "z": z0, "x": x0, "y": 0.5, "i": "linear"},
            {"t": round(b, 3), "z": z1, "x": x1, "y": 0.5, "i": "linear"}]


def punch(c, is_image: bool) -> list[dict]:
    """Zoom de golpe al empezar el plano (1,15 → 1 en 0,3 s): da energía en estilo dinámico."""
    a = 0.0 if is_image else c.source_in
    return [{"t": round(a, 3), "z": 1.15, "x": 0.5, "y": 0.5},
            {"t": round(a + min(0.3, c.duration * 0.5), 3), "z": 1.0, "x": 0.5, "y": 0.5}]


def cinematic_changes(p, clip_ids: list[str], topic_starts: list[float], *, ken: bool = True,
                      dips: bool = True, fade_ends: bool = True, punch_every: int = 0) -> dict[str, dict]:
    """Cambios para batch_clip_props: zoom lento en los planos largos sin zoom, fundido a negro
    breve en cada cambio de tema y fundido al empezar y al acabar el video."""
    clips = sorted((p.clips[i] for i in clip_ids if i in p.clips), key=lambda c: c.start)
    changes: dict[str, dict] = {}

    def fx_of(c) -> dict:
        return changes.setdefault(c.id, {}).setdefault("fx", dict(c.fx or {}))

    k = 0
    for c in clips:
        m = p.media_of(c)
        if m is None:
            continue
        is_img = m.kind == "image"
        if punch_every and not transform.is_zoomed(c.zoom_kf) and k % punch_every == 0 and c.duration < KEN_BURNS_MIN:
            changes.setdefault(c.id, {})["zoom_kf"] = punch(c, is_img)
            k += 1
        elif (ken or is_img) and not transform.is_zoomed(c.zoom_kf) and (is_img or c.duration >= KEN_BURNS_MIN):
            changes.setdefault(c.id, {})["zoom_kf"] = ken_burns(c, is_img, k)
            k += 1
        else:
            k += 1 if punch_every else 0
    if dips:
        for t in topic_starts:
            before = next((c for c in clips if abs(c.end - t) < 1.5), None)
            after = next((c for c in clips if before is not None and abs(c.start - before.end) < 0.02), None)
            if before is None or after is None or before.duration < 1.0 or after.duration < 1.0:
                continue
            fx_of(before)["fade_out"] = DIP
            fx_of(after)["fade_in"] = DIP
    if fade_ends and clips:
        fx_of(clips[0])["fade_in"] = 0.6
        fx_of(clips[-1])["fade_out"] = 1.2
    return changes


def snap_to_cuts(t: float, cuts: list[float], tol: float = 1.5) -> float | None:
    near = min(cuts, key=lambda c: abs(c - t), default=None)
    return near if near is not None and abs(near - t) <= tol else None


def music_items(music, start: float, end: float) -> list[dict]:
    """La canción repetida las veces que haga falta para cubrir [start, end)."""
    if music is None or music.duration <= 1.0 or end - start < 1.0:
        return []
    items, t = [], start
    while t < end - 0.5:
        dur = min(music.duration, end - t)
        items.append({"media_id": music.id, "start": t, "duration": dur, "source_in": 0.0,
                      "note": "Música de fondo (IA)"})
        t += dur
    return items
