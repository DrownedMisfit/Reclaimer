"""
Prueba de la interfaz sin mostrarla en pantalla: crea la ventana, importa medios,
monta una timeline, simula acciones y guarda una captura.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_ui.py <carpeta_de_medios> <captura.png>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.model import ORIGIN_AI, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.ui.main_window import MainWindow  # noqa: E402
from editoria.ui.theme import apply_dark_theme  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    folder, shot = sys.argv[1], sys.argv[2]
    if not os.path.isdir(folder) or not any(os.scandir(folder)):    # sin videos de prueba: se crean
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_core import make_media
        make_media(folder)
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    ctrl.import_folder(folder)
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    p = ctrl.project
    by_name = {m.name: m for m in p.media.values()}
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    v2 = [t for t in p.tracks if t.kind == TRACK_VIDEO][0]
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([by_name["pelea_01.mp4"].id, by_name["intro.mp4"].id], v1.id, 0.0)
    ctrl.add_media([by_name["narracion.wav"].id], a1.id, 0.0)
    created = ctrl.add_media([by_name["captura.png"].id], v2.id, 2.0, origin=ORIGIN_AI)
    ctrl.split(4.0, [p.clips_on(a1.id)[0].id])
    ctrl.set_clip_props([p.clips_on(a1.id)[1].id], "Bloquear", locked=True)
    ctrl.set_track_props(p.tracks[-1].id, "Bloquear", locked=True)
    ctrl.add_marker(1.0, "INTRODUCCIÓN")
    ctrl.add_marker(6.0, "COMBATE")
    win.timeline.set_selection(created)
    win.engine.seek(2.5)
    pump(app, 1.5)
    win.timeline.fit()
    pump(app, 0.5)

    # Reproducir un momento para comprobar que el motor no falla
    win.engine.play()
    pump(app, 1.0)
    assert win.engine.time > 2.6, win.engine.time
    win.engine.pause()
    win.engine.seek(2.5)
    pump(app, 0.5)

    # Ratón: mover un clip 1 segundo y recortar otro por su borde derecho
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    tl = win.timeline
    intro = p.clips_on(v1.id)[1]
    old_start = intro.start
    r = tl.clip_rect(intro)
    a = QPoint(int(r.center().x()), int(r.center().y()))
    b = a + QPoint(int(tl.pps * 1.0), 0)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(tl, a + QPoint(8, 0))
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, b)
    moved = ctrl.project.clips[intro.id].start
    assert 0.8 < moved - old_start < 1.2, (old_start, moved)
    pelea = ctrl.project.clips_on(v1.id)[0]
    r = tl.clip_rect(pelea)
    a = QPoint(int(r.right()) - 2, int(r.center().y()))
    b = a - QPoint(int(tl.pps * 2.0), 0)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(tl, a - QPoint(8, 0))
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, b)
    new_dur = ctrl.project.clips[pelea.id].duration
    assert 3.6 < new_dur < 4.4, new_dur
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    assert abs(ctrl.project.clips[intro.id].start - old_start) < 1e-6
    assert abs(ctrl.project.clips[pelea.id].duration - 6.0) < 0.05
    print("✓ mover / recortar con el ratón y deshacer")
    p = ctrl.project
    win.timeline.set_selection(created)
    win.engine.seek(2.5)
    pump(app, 0.5)

    win.grab().save(shot)
    print("captura:", shot, "| clips:", len(p.clips), "| tiempo:", round(win.engine.time, 2))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()


if __name__ == "__main__":
    main()
