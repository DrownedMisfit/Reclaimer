"""
✨ Toques finales (23/11): la lógica de «Primera versión automática» que sirve DESPUÉS de armar el video, sin interfaz.
La usan el paso 3 de «Edita desde tu voz» (ui/paso_arma.py, sección «Toques finales») y la ventana de siempre
(ui/auto_dialog.py), sin duplicar código. Cada toque es UN paso de Ctrl+Z (un_paso).

Lo que va en un hilo (sin tocar el proyecto) y lo que se aplica en el de la interfaz:
  temas:      detectar_temas(words, progress, cancelled) [hilo] → poner_temas(ctrl, mid, segmentos)
  estilo:     poner_estilo(ctrl, estilo, pista_broll)            natural = no toca nada
  zooms:      plan_zooms(ctrl, mid) → trabajo_zooms(plan, …) [hilo] → poner_zooms(ctrl, items)
  música:     poner_musica(ctrl, media_id) · ritmo(path) [hilo] → cortes_a_ritmo(ctrl, media_id, res, pista_broll)
  volumen:    poner_volumen(ctrl)                                 −14 LUFS (loudnorm)
  subtítulos: poner_subtitulos(ctrl, mid)
  revisión:   revision(ctrl) → (avisos, resumen)
NO están (a propósito): el ecualizador «Mi voz» / «Mejorar la voz» (la voz de OBS ya viene igualada) ni la limpieza de
silencios y muletillas (eso es el paso 2, a mano).
"""
from __future__ import annotations

from contextlib import contextmanager

from ..core import mapping
from ..core.model import KIND_IMAGE, ORIGIN_AI, TRACK_VIDEO
from .base import Cancelled

ESTILOS = [("natural", "Natural"), ("dynamic", "Dinámico"), ("cinematic", "Cinematográfico")]
NOMBRE_ESTILO = {"natural": "Natural — limpio y discreto",
                 "dynamic": "Dinámico — más cambios y zooms de golpe",
                 "cinematic": "Cinematográfico — zoom lento, transiciones con whoosh, cortes a ritmo de la música",
                 "custom": "Personalizado"}


@contextmanager
def un_paso(ctrl, texto: str):
    """Todo lo de dentro, UN paso de Ctrl+Z."""
    ctrl.undo_stack.beginMacro(texto)
    try:
        yield
    finally:
        ctrl.undo_stack.endMacro()


def pista_broll(ctrl, voz_mid: str | None) -> str | None:
    """La pista de video del B-roll: la de más arriba que no es la de la voz ni está bloqueada."""
    p = ctrl.project
    narr = {c.track_id for c in mapping.clips_of_media(p, voz_mid)} if voz_mid else set()
    for t in reversed([t for t in p.tracks if t.kind == TRACK_VIDEO]):
        if t.id not in narr and not t.locked:
            return t.id
    return None


# ------------------------------------------------------------------ temas y capítulos
def detectar_temas(words: list, progress=None, cancelled=None) -> list[dict]:
    from . import topic_detection
    if len(words or []) < 30:
        return []
    return topic_detection.detect_topics(words, progress=progress, cancelled=cancelled)


def poner_temas(ctrl, mid: str, segmentos: list[dict]) -> tuple[int, list[str]]:
    """(cuántos temas, sus nombres). Un Ctrl+Z (set_topics ya es un paso)."""
    if not segmentos:
        return 0, []
    n = ctrl.set_topics(mid, segmentos) or 0
    nombres = list(dict.fromkeys(m.label for m in ctrl.project.markers if m.kind == "topic"))
    return n, nombres


# ------------------------------------------------------------------ estilo
def poner_estilo(ctrl, estilo: str, tid: str | None, custom_cine: bool = False) -> str:
    """Zoom lento, fundidos en los cambios de tema y whoosh (solo Cinematográfico). Natural no toca nada. Devuelve
    la línea del informe ('' si no hizo nada). Un Ctrl+Z."""
    from . import first_version
    if estilo == "natural" or (estilo == "custom" and not custom_cine):
        return ""
    p = ctrl.project
    if not tid or not p.clips_on(tid):
        return ""
    with un_paso(ctrl, "✨ Toques de cine"):
        cuts = [c.start for c in p.clips_on(tid)]
        starts = []
        if estilo in ("cinematic", "custom"):         # cada tema nuevo empieza con su plano (y su transición)
            for m in p.markers:
                if m.kind != "topic" or m.time <= 1.0 or first_version.snap_to_cuts(m.time, cuts) is not None:
                    continue
                c = next((c for c in p.clips_on(tid) if c.start + 1.5 < m.time < c.end - 1.5), None)
                if c is not None and ctrl.split_at_times(c.id, [m.time], "IA · Plano nuevo en el tema"):
                    cuts.append(m.time)
        ids = [c.id for c in p.clips_on(tid)]
        for m in p.markers:
            if m.kind == "topic" and m.time > 1.0:
                t = first_version.snap_to_cuts(m.time, cuts)
                if t is not None and t not in starts:
                    starts.append(t)
        ken = estilo in ("dynamic", "cinematic", "custom")
        dips = estilo in ("cinematic", "custom")
        changes = first_version.cinematic_changes(p, ids, starts, ken=ken, dips=dips,
                                                  punch_every=3 if estilo == "dynamic" else 0)
        ctrl.batch_clip_props(changes, "IA · Toques de cine")
        nk = sum(1 for c in changes.values() if "zoom_kf" in c)
        extra = ""
        if estilo == "cinematic" and starts:            # un whoosh en cada cambio de tema
            from ..core import sfx
            wid = ctrl.import_now([sfx.path_for("whoosh_largo")])
            if wid:
                ctrl.set_media_props(wid, category="Efectos")
                fx_tid = ctrl.ensure_role_track("efectos")
                for t in starts:
                    ctrl.add_media(wid, fx_tid, max(0.0, t - 0.7), origin=ORIGIN_AI)
                extra = f", whoosh en {len(starts)} transiciones"
    nombre = NOMBRE_ESTILO.get(estilo, "").split(" —")[0]
    return (f"🎞 Estilo {nombre.lower()}: zoom en {nk} planos"
            + (f", fundido en {len(starts)} cambios de tema" if dips else "") + extra + ".")


# ------------------------------------------------------------------ zooms en momentos clave
def video_en(ctrl, t: float):
    """El clip de video/imagen visible (pista más alta, sin bloquear) en el momento t."""
    p = ctrl.project
    for tr in p.tracks:
        if tr.kind != TRACK_VIDEO or tr.hidden:
            continue
        c = p.clip_at(tr.id, t)
        if c is not None and c.enabled:
            return c if not (c.locked or tr.locked) else None
    return None


def plan_zooms(ctrl, mid: str) -> tuple[list, int]:
    """(plan para el hilo, cuántas comparaciones sugeridas). Deja las sugerencias de zoom y comparación."""
    from .visual_suggestions import find_compare_moments, find_zoom_moments
    p = ctrl.project
    words = p.transcripts.get(mid, {}).get("words", [])
    zitems = [{"kind": "zoom", "start": d["start"], "end": d["end"], "label": d["label"],
               "detail": d["detail"], "data": {"face": d["face"], "strength": d["strength"]}}
              for d in find_zoom_moments(words)]
    comps = [dict(d, kind="compare") for d in find_compare_moments(words)]
    ctrl.set_suggestions(mid, zitems + comps, {"zoom", "compare"}, {"zoom": False, "compare": False})
    plan = []
    for sg in [x for x in ctrl.project.suggestions if x.kind == "zoom" and x.media_id == mid and x.status == "pending"]:
        t = mapping.map_time(ctrl.project, mid, sg.start)
        c = video_en(ctrl, t) if t is not None else None
        m = ctrl.project.media_of(c) if c else None
        if c is None or m is None:
            continue
        is_img = m.kind == KIND_IMAGE
        cin = 0.0 if is_img else c.source_in
        plan.append((sg.id, c.id, ctrl.clip_source_time(c.id, t), m.path, m.width, m.height, is_img, cin,
                     cin + c.duration))
    return plan, len(comps)


def trabajo_zooms(plan: list, progress, cancelled) -> list:
    from . import tracking
    from .transform_helpers import punch_keyframes
    out = []
    for i, (sid, cid, src, path, w, h, is_img, cin, cout) in enumerate(plan):
        if cancelled():
            raise Cancelled()
        progress(i / max(1, len(plan)), f"🔍 Preparando zoom {i + 1}/{len(plan)}…")
        z, x, y = 1.5, 0.5, 0.5
        try:
            frame = None if is_img else tracking.grab_frame(path, src, 640, w, h)
            faces = tracking.detect_faces(frame) if frame is not None else []
        except Exception:  # noqa: BLE001
            faces = []
        if faces:
            fx, fy, fw, fh, _c = faces[0]
            x, y = fx + fw / 2, fy + fh / 2
            z = max(1.6, min(3.0, 0.4 / max(fh, 1e-3)))
        out.append((sid, cid, punch_keyframes(src, cin, cout, z, x, y)))
    return out


def poner_zooms(ctrl, items: list) -> int:
    return (ctrl.apply_zoom_suggestions(items) or 0) if items else 0


# ------------------------------------------------------------------ música de fondo
def poner_musica(ctrl, music_id: str) -> int:
    """La canción en los huecos de la pista de música (nunca encima de tu voz), bajando sola al hablar (−12 dB), con
    fundidos. Devuelve cuántos tramos. Un Ctrl+Z."""
    from . import first_version
    if not music_id or music_id not in ctrl.project.media:
        return 0
    with un_paso(ctrl, "✨ Música de fondo"):
        mt = ctrl.project.track(ctrl.ensure_role_track("musica"))
        p = ctrl.project
        if mt.duck_db is None:
            ctrl.set_track_props(mt.id, "Bajar música al hablar", duck_db=-12.0)
        items = first_version.music_items_fit(p.media[music_id], 0.0, p.duration())
        created = ctrl.insert_ranges(items, mt.id, "IA · Música de fondo", origin=ORIGIN_AI, only_gaps=True,
                                     volume=0.35)
        if not (isinstance(created, list) and created):
            return 0
        tramos = sorted((ctrl.project.clips[i] for i in created if i in ctrl.project.clips), key=lambda c: c.start)
        ch: dict = {}

        def fx_of(c):
            return ch.setdefault(c.id, {"fx": dict(c.fx or {})})["fx"]
        fx_of(tramos[0])["fade_in"] = 1.5
        fx_of(tramos[-1])["fade_out"] = 2.5
        for a, b in zip(tramos, tramos[1:]):            # la canción vuelve a empezar: fundido cruzado de 1,5 s
            if abs(b.start - a.end) < 0.05:
                fx_of(a)["fade_out"] = 1.5
                fx_of(b)["fade_in"] = 1.5
        ctrl.batch_clip_props(ch, "Fundidos de la música")
    return len(tramos)


def ritmo(path: str) -> dict:
    from . import rhythm
    return rhythm.analyze(path)


def cortes_a_ritmo(ctrl, music_id: str, res: dict, tid: str | None) -> int:
    """Los cortes del B-roll, a los golpes de la música (mejor al empezar compás o en los fuertes). Un Ctrl+Z."""
    from . import music_analysis
    ctrl._on_rhythm(music_id, res)
    p = ctrl.project
    mt = p.track(ctrl._role_track(p, "musica", create=False) or "")
    if mt is None or tid is None:
        return 0
    clips = p.clips_on(tid)
    cuts = [a.end for a, b in zip(clips, clips[1:]) if abs(b.start - a.end) < 0.01]
    rt = ctrl.rhythm_on_timeline([c.id for c in p.clips_on(mt.id)])
    targets = music_analysis.snap_points(cuts, rt["beats"] or ctrl.beats_on_timeline(mt.id),
                                         prefer=rt["downbeats"] + rt["strong"] + rt["drops"])
    return (ctrl.snap_cuts(tid, targets) or 0) if targets else 0


# ------------------------------------------------------------------ volumen, subtítulos, revisión
def poner_volumen(ctrl) -> bool:
    """Volumen final −14 LUFS (loudnorm). True si lo cambió."""
    if ctrl.project.loudnorm:
        return False
    ctrl.set_settings(loudnorm=True)
    return True


def poner_subtitulos(ctrl, mid: str) -> str:
    from ..core.subtitles import PRESETS as SUB_PRESETS
    from ..core.subtitles import SHORTS
    p = ctrl.project
    preset = SHORTS if p.format in ("short", "edit") else p.subtitles.preset
    props = dict(SUB_PRESETS.get(preset, {}), preset=preset, enabled=True, media_id=mid)
    ctrl.set_subtitle_style("IA · Subtítulos", **props)
    return preset


def revision(ctrl) -> tuple[list, str]:
    """(avisos, resumen) de la revisión final del proyecto."""
    from .audit import run_audit, summary
    ctrl.ensure_timeline_peaks(wait=True)              # la revisión de cortes necesita la voz de cada clip
    issues, checked = run_audit(ctrl.project, ctrl.missing, ctrl.peaks, ctrl.clip_vecs)
    return issues, summary(issues, checked)
