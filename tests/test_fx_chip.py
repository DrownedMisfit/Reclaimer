"""
Prueba de la ✦ pastilla «fx» de la línea de tiempo (el usuario: «una manera fácil de quitar los efectos, así como las
transiciones… con algún color que indique que hay un efecto ahí, y nada más borrarlo»):
  · un clip con efectos lleva la pastilla (los fundidos solos no cuentan); uno sin efectos, no;
  · clic en la pastilla = seleccionarla; Supr = quitar sus efectos (el fundido se queda); Ctrl+Z los devuelve;
  · clic derecho = quitar uno concreto (con sus parámetros: el temblor se lleva su intensidad).
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_fx_chip.py <carpeta>
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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui import help as help_ui
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p, tl = win.ctrl, win.ctrl.project, win.timeline
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    made = ctrl.add_media([mid], v1.id, 0.0) + ctrl.add_media([mid], v1.id, 6.0)
    a, b = [i for i in made if p.clips[i].track_id == v1.id]
    ctrl.set_clip_props([a], "fx", fx={"glitch": 0.1, "vignette": 0.6, "fade_in": 0.5, "shake": 0.3,
                                      "shake_amp": 0.02})
    ctrl.set_clip_props([b], "fx", fx={"fade_out": 0.5})          # solo un fundido: sin pastilla
    tl.fit()
    tl.repaint()
    pump(app, 0.3)
    assert a in tl._fx_chips and b not in tl._fx_chips, tl._fx_chips
    tl.grab().save(os.path.join(out, "pastilla_fx.png"))
    chip = tl._fx_chips[a]
    QTest.mouseMove(tl, chip.center().toPoint())
    pump(app, 0.1)
    assert "Viñeta" in tl.toolTip() and "Glitch" in tl.toolTip(), tl.toolTip()
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, chip.center().toPoint())
    assert tl.sel_fx == a and not tl.selected, (tl.sel_fx, tl.selected)
    print("✓ ✦ pastilla «fx» en el clip con efectos (no en el que solo tiene un fundido); al pasar el ratón dice "
          "cuáles; clic = seleccionarla")
    win._delete(False)                                         # Supr
    assert p.clips[a].fx == {"fade_in": 0.5} and a in p.clips, p.clips[a].fx
    ctrl.undo_stack.undo()
    assert set(p.clips[a].fx) == {"glitch", "vignette", "fade_in", "shake", "shake_amp"}, p.clips[a].fx
    print("✓ Supr quita sus efectos (el clip y el fundido se quedan) y Ctrl+Z los devuelve")
    tl.repaint()
    pump(app, 0.2)
    shown = []
    orig = help_ui.exec_menu
    help_ui.exec_menu = lambda menu, _pos: shown.append(menu)
    try:
        QTest.mouseClick(tl, Qt.RightButton, Qt.NoModifier, tl._fx_chips[a].center().toPoint())
    finally:
        help_ui.exec_menu = orig
    acts = {x.text(): x for x in shown[-1].actions()}
    shake = next(x for t, x in acts.items() if "Temblor" in t)
    shake.trigger()
    assert set(p.clips[a].fx) == {"glitch", "vignette", "fade_in"}, p.clips[a].fx
    print("✓ clic derecho = quitar uno concreto (el temblor se lleva su intensidad):", sorted(acts))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
