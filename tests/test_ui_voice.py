"""
Prueba de la interfaz de voz sin mostrarla: transcribe con el panel, revisa sugerencias,
aplica cortes y guarda capturas.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_ui_voice.py <carpeta_capturas>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import SUG_APPLIED, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.ui.main_window import MainWindow  # noqa: E402
from editoria.ui.theme import apply_dark_theme  # noqa: E402

NARRATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "narracion_prueba.wav")


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    gp = os.path.join(out, "gameplay.mp4")
    media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                           "testsrc2=s=640x360:r=30:d=29", "-c:v", "libx264", gp])
    nid, gid = ctrl.import_paths([NARRATION, gp])
    while ctrl.analyzing:
        pump(app, 0.1)
    p = ctrl.project
    ctrl.add_media([nid], [t for t in p.tracks if t.kind == TRACK_AUDIO][0].id, 0)
    ctrl.add_media([gid], [t for t in p.tracks if t.kind == TRACK_VIDEO][-1].id, 0)
    pump(app, 0.5)

    # Transcribir desde el panel (tarea en segundo plano)
    win.right_tabs.setCurrentWidget(win.voice)
    assert win.voice.media_id() == nid
    win.voice.transcribe()
    t0 = time.time()
    while win.voice.job is not None and time.time() - t0 < 300:
        pump(app, 0.2)
    pump(app, 0.5)
    assert nid in ctrl.project.transcripts, win.voice.status.text()
    n_sug = len(ctrl.project.suggestions)
    assert n_sug >= 8, n_sug
    assert win.voice.tree.topLevelItemCount() == sum(
        1 for s in ctrl.project.suggestions if s.status == "pending"), "lista incompleta"
    print(f"✓ transcripción desde el panel: {len(ctrl.project.transcripts[nid]['words'])} palabras, "
          f"{n_sug} sugerencias · {win.voice.status.text()}")

    # Seleccionar la toma repetida y resaltar en la timeline
    for i in range(win.voice.tree.topLevelItemCount()):
        it = win.voice.tree.topLevelItem(i)
        if "toma" in it.text(1).lower():
            it.setSelected(True)
            break
    pump(app, 0.3)
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "1_sugerencias.png"))

    # Escuchar (no debe fallar) y aplicar todos los silencios con el filtro por tipo
    win.voice.listen()
    pump(app, 0.5)
    win.engine.pause()
    win.voice.f_kind.setCurrentIndex(win.voice.f_kind.findData("silence"))
    pump(app, 0.3)
    ids = [s.id for s in ctrl.project.suggestions if s.kind == "silence"]
    ctrl.apply_suggestions(ids)
    pump(app, 0.5)
    assert all(s.status == SUG_APPLIED for s in ctrl.project.suggestions if s.kind == "silence")
    assert len(win.timeline._cut_marks) == len(ids), (len(win.timeline._cut_marks), len(ids))
    win.voice.f_kind.setCurrentIndex(0)
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "2_cortes.png"))
    print(f"✓ {len(ids)} silencios aplicados y marcados con ✂ en la timeline")

    # Panel de texto: clic en una palabra mueve el cabezal
    win.right_tabs.setCurrentWidget(win.transcript)
    pump(app, 0.3)
    from PySide6.QtCore import QUrl
    win.transcript._on_anchor(QUrl("w12"))
    pump(app, 0.2)
    assert win.engine.time > 1.0, win.engine.time
    win.engine.seek(win.engine.time + 0.1)
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "3_texto.png"))
    print(f"✓ clic en palabra → cabezal en {win.engine.time:.2f} s")

    win.right_tabs.setCurrentWidget(win.right_tabs.widget(win.right_tabs.count() - 1))
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "4_historial.png"))

    # Subtítulos: activar desde el panel, resaltar una palabra y ver el visor
    win.right_tabs.setCurrentWidget(win.subtitles)
    win.subtitles.enabled.setChecked(True)
    pump(app, 0.3)
    assert ctrl.project.subtitles.enabled and ctrl.project.subtitles.media_id == nid
    words = ctrl.project.transcripts[nid]["words"]
    idx = next(i for i, w in enumerate(words) if w[2].lower().startswith("demasiado"))
    ctrl.set_emphasis([idx], True)
    win.subtitles.preset.setCurrentText("YouTube clásico")
    pump(app, 0.3)
    win.transcript._seek_word(idx)
    pump(app, 0.5)
    assert win.preview.canvas.subs._cue is not None, "no hay subtítulo en el visor"
    win.grab().save(os.path.join(out, "5_subtitulos.png"))
    print("✓ subtítulos en el visor:", win.preview.canvas.subs._cue.text(" / "))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("capturas en", out)


if __name__ == "__main__":
    main()
