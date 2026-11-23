"""
Alto de las pistas (el usuario: «cada vez que hago grandes los módulos de video y audio se crea un espacio innecesario
debajo»):
  · agrandar las pistas NO cambia el alto del panel de la línea de tiempo ni el del visor: crecen dentro y, si no
    caben, sale el desplazamiento vertical;
  · la franja de debajo de la última pista («soltar aquí = pista nueva») casi no ocupa sitio sin arrastrar nada y se
    ve («Suelta aquí para una pista nueva») mientras se arrastra algo;
  · «Ajustar las pistas al alto»: si sobra sitio, las pistas lo llenan.
Ejecutar:  .venv/Scripts/python.exe tests/test_alto_pistas.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_alto_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    pump(app, 1.0)
    tl, ctrl = win.timeline, win.ctrl
    tl.set_ajustar_alto(False)
    d = win.docks["timeline"]
    canvas = win.preview.canvas
    sa = tl._scroll_area()
    try:
        tl._set_track_size("video_h", 54)
        tl._set_track_size("audio_h", 54)
        pump(app, 0.5)
        alto_panel, alto_visor = d.height(), canvas.height()
        for key in ("video_h", "audio_h"):
            for h in (80, 110, 160):
                tl._set_track_size(key, h)
                pump(app, 0.3)
                assert abs(d.height() - alto_panel) <= 2, (key, h, d.height(), alto_panel)
                assert abs(canvas.height() - alto_visor) <= 2, (key, h, canvas.height(), alto_visor)
        print(f"✓ agrandar las pistas no cambia el panel ({alto_panel} px) ni el visor ({alto_visor} px)")

        for _k in range(3):
            ctrl.add_track(TRACK_VIDEO)
        ctrl.add_track(TRACK_AUDIO)
        pump(app, 0.5)
        n = len(ctrl.project.tracks)
        assert tl.minimumHeight() > sa.viewport().height(), (tl.minimumHeight(), sa.viewport().height())
        assert sa.verticalScrollBar().maximum() > 0, "si no caben, desplazamiento vertical"
        assert abs(d.height() - alto_panel) <= 2, "añadir pistas por el núcleo tampoco agranda el panel"
        print(f"✓ {n} pistas grandes que no caben: desplazamiento vertical (pide {tl.minimumHeight()} px, se ven "
              f"{sa.viewport().height()})")

        # la franja de abajo: mínima sin arrastrar; visible al arrastrar
        assert tl.NEW_ZONE == tl.ZONA_MIN <= 8
        assert tl.minimumHeight() == int(tl.track_y(n)) + tl.ZONA_MIN + 4, tl.minimumHeight()
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(os.path.join(_TMP, "x.mp4"))])
        open(os.path.join(_TMP, "x.mp4"), "wb").close()
        pos = QPointF(tl.HEADER_W + 100, tl.track_y(n) + 4)
        ev = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        tl.dragEnterEvent(ev)
        assert tl.NEW_ZONE == tl.ZONA_ARRASTRE and tl.minimumHeight() == int(tl.track_y(n)) + tl.ZONA_ARRASTRE + 4
        ev2 = QDragMoveEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        tl.dragMoveEvent(ev2)
        assert tl._drop is not None and tl._drop[0] == "new", tl._drop
        tl.repaint()
        tl.dragLeaveEvent(None)
        assert tl.NEW_ZONE == tl.ZONA_MIN and tl.minimumHeight() == int(tl.track_y(n)) + tl.ZONA_MIN + 4
        print(f"✓ la franja de debajo: {tl.ZONA_MIN} px sin arrastrar; {tl.ZONA_ARRASTRE} px y su rótulo mientras "
              "se arrastra algo")

        # Ajustar las pistas al alto: con pocas pistas pequeñas, llenan el panel
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        ctrl.new_project()                                  # (proyecto nuevo: dos pistas)
        pump(app, 0.4)
        tl._set_track_size("video_h", 36)
        tl._set_track_size("audio_h", 36)
        pump(app, 0.3)
        hueco = sa.viewport().height() - tl.track_y(len(ctrl.project.tracks))
        tl.set_ajustar_alto(True)
        pump(app, 0.4)
        lleno = sa.viewport().height() - tl.track_y(len(ctrl.project.tracks))
        assert lleno <= tl.ZONA_MIN + 8 or lleno < hueco - 20, (hueco, lleno)
        assert abs(d.height() - alto_panel) <= 2
        tl.set_ajustar_alto(False)
        print(f"✓ «Ajustar las pistas al alto»: lo que sobraba debajo pasa de {hueco:.0f} a {lleno:.0f} px")
    finally:
        tl.set_ajustar_alto(False)
        tl._set_track_size("video_h", 54)
        tl._set_track_size("audio_h", 54)
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
