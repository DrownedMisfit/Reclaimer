"""
🎵 «Ajustar la música a…» (menú Editar): la canción del clip de música se alarga o se acorta POR COMPASES
(ai/music_fit.py) para durar lo mismo que el video o que la selección I–O. Un solo paso de Ctrl+Z.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ..ai import music_fit, rhythm
from ..core.model import KIND_AUDIO
from .jobs import BackgroundJob


def _music_clip(win):
    """El clip de música: el seleccionado (si es de audio), o el primero de la pista de música."""
    ctrl = win.ctrl
    p = ctrl.project
    for cid in sorted(getattr(win.timeline, "selected", set()) or []):
        c = p.clips.get(cid)
        m = p.media_of(c) if c else None
        if m is not None and m.kind == KIND_AUDIO and m.duration > 1.0:
            return c
    mt = p.track(ctrl._role_track(p, "musica", create=False) or "")
    if mt is not None:
        for c in sorted(p.clips_on(mt.id), key=lambda c: c.start):
            m = p.media_of(c)
            if m is not None and m.kind == KIND_AUDIO and m.duration > 1.0:
                return c
    return None


def run(win, what: str):
    """what = «video» (a la duración total) o «rango» (a la selección I–O, empezando en I)."""
    ctrl = win.ctrl
    p = ctrl.project
    c = _music_clip(win)
    if c is None:
        QMessageBox.information(win, "Ajustar la música",
                                "Selecciona antes el clip de música (o ten una pista de música con su canción).")
        return
    m = p.media_of(c)
    if what == "rango":
        if p.mark_in is None or p.mark_out is None or p.mark_out <= p.mark_in + 1.0:
            QMessageBox.information(win, "Ajustar la música",
                                    "Marca primero el inicio (I) y el final (O) de la selección.")
            return
        start, target = float(p.mark_in), float(p.mark_out - p.mark_in)
        text = "Ajustar la música a la selección"
    else:
        start, target = 0.0, float(p.duration())
        text = "Ajustar la música a la duración del video"
    if target < 2.0:
        return
    path, mid = m.path, m.id

    def work(progress, cancelled):
        progress(0.0, "🥁 Escuchando el ritmo de la música…")
        return rhythm.analyze(path, cancelled)

    def done(info):
        ctrl._on_rhythm(mid, info)
        plan = music_fit.plan_fit(info, m.duration, target)
        if not music_fit.apply_to_clip(ctrl, c.id, plan, text, start=start):
            return
        note = music_fit.describe(plan)
        win.statusBar().showMessage(f"🎵 Música ajustada por compases ({note}). Ctrl+Z la deshace.", 10000)

    job = BackgroundJob(work, win)
    job.done.connect(done)
    job.failed.connect(lambda msg: win.statusBar().showMessage(f"No se pudo ajustar la música: {msg[:200]}", 10000))
    win._music_fit_job = job          # que no la recoja el recolector mientras corre
    job.start()


def add_music_fit_menu(win, menu):
    """Añade «🎵 Ajustar la música a…» con sus dos opciones al menú dado."""
    sub = menu.addMenu("🎵 Ajustar la música a…")
    sub.setToolTip("Alarga o acorta la canción quitando o repitiendo secciones enteras por compases, "
                   "con fundidos cortos en cada unión, y la deja terminar en su final.")
    a1 = sub.addAction("la duración del video")
    a1.triggered.connect(lambda: run(win, "video"))
    a2 = sub.addAction("la selección (marcas I–O)")
    a2.triggered.connect(lambda: run(win, "rango"))
    return sub
