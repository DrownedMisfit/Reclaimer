"""
Prueba de «Aparición seleccionada» (🔎 Momentos):
  · un momento muy corto (1 s) se amplía a 3 s alrededor del mejor instante para poder usarlo;
  · «▶ Ver» pasa a «⏹ Parar» y se puede parar (también con Esc, y al usarlo);
  · «Usar: insertar en el cabezal» lo pone en la línea de tiempo; también se puede arrastrar mientras se ve.
Ejecutar:  .venv/Scripts/python.exe tests/test_moments_use.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import moments as MO
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "partida.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                    "-pix_fmt", "yuv420p", vid], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    mp = win.moments
    win.show_panel(mp)
    mp.results = [MO.Moment(mid, 10.0, 11.0, 10.5, 3.0, "video")]
    mp.grid.clear()
    mp.grid.addItem("momento")
    mp.grid.setCurrentRow(0)
    mp._select(0)
    assert abs(mp.t_in.value() - 9.0) < 0.05 and abs(mp.t_out.value() - 12.0) < 0.05, (mp.t_in.value(),
                                                                                         mp.t_out.value())
    print("✓ un momento de 1 s se amplía a 3 s alrededor del mejor instante (lo puedes cambiar en Desde/hasta)")
    mp.preview()
    pump(app, 0.3)
    assert mp.b_play.text().startswith("⏹") and mp.video.isVisible()
    mp.preview()                         # otra vez = parar
    assert mp.b_play.text().startswith("▶") and not mp.video.isVisible() and mp.frame.isVisible()
    mp.preview()
    pump(app, 0.2)
    mp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not mp.video.isVisible()
    print("✓ «▶ Ver» ↔ «⏹ Parar» (y Esc la para)")
    mp.preview()
    pump(app, 0.2)
    assert mp.drag_payload() == f"{mid}|9.000|12.000", mp.drag_payload()
    win.engine.seek(0.0)
    n = len(ctrl.project.clips)
    mp.place("insert")
    new = [c for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_VIDEO]
    assert len(ctrl.project.clips) > n and any(abs(c.duration - 3.0) < 0.05 for c in new)
    assert not mp.video.isVisible(), "al usarlo, la vista previa se para"
    print("✓ «Usar: insertar en el cabezal» lo pone en la línea de tiempo (3 s); arrastrarlo también vale al verlo")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
