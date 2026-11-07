"""
Miniatura · qué capa se mueve (el usuario: «si tengo seleccionada una imagen en Capas, esa es la que se mueve en el
lienzo, a menos de que seleccione otra en el lienzo con doble clic»):
  · con una capa elegida, arrastrar encima de OTRA capa mueve la elegida (no cambia la selección);
  · doble clic en otra capa del lienzo la elige; luego arrastrar mueve esa;
  · sin nada elegido, un clic elige la de arriba como siempre.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_select.py <carpeta>
"""
from __future__ import annotations

import os
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

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_thumb_select")
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    paths = []
    for i, col in enumerate(((200, 40, 40), (40, 40, 200))):
        p = os.path.join(out, f"capa_{i}.png")
        Image.fromarray(np.full((600, 1000, 3), col, np.uint8)).save(p)
        paths.append(p)
    ed.add_image(paths[0], "Abajo")                    # capa de abajo (centrada)
    abajo = ed.cur()
    ed.add_image(paths[1], "Arriba")                   # capa de arriba, encima, en el mismo sitio
    arriba = ed.cur()
    cv = ed.canvas
    centro = QPointF(float(abajo["x"]), float(abajo["y"]))

    def ev(kind, pt, buttons=Qt.LeftButton, mods=Qt.NoModifier):
        vp = cv.mapFromScene(pt)
        return QMouseEvent(kind, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), Qt.LeftButton, buttons, mods)

    def arrastrar(p0, dx):
        cv.mousePressEvent(ev(QEvent.MouseButtonPress, p0))
        cv.mouseMoveEvent(ev(QEvent.MouseMove, p0 + QPointF(dx / 2, 0), mods=Qt.ControlModifier))   # Ctrl: sin imán
        cv.mouseMoveEvent(ev(QEvent.MouseMove, p0 + QPointF(dx, 0), mods=Qt.ControlModifier))
        cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, p0 + QPointF(dx, 0), Qt.NoButton))
        pump(app, 0.05)

    # 1) elegida en «Capas» la de abajo → arrastrar sobre la de arriba mueve la de ABAJO
    ed.layers.setCurrentRow(next(i for i in range(ed.layers.count())
                                 if ed.layers.item(i).data(Qt.UserRole) == abajo["id"]))
    pump(app, 0.05)
    assert cv.sel == abajo["id"], (cv.sel, abajo["id"])
    xa, xb = float(ed.layer(abajo["id"])["x"]), float(ed.layer(arriba["id"])["x"])
    arrastrar(centro + QPointF(10, 10), 80)
    la, lb = ed.layer(abajo["id"]), ed.layer(arriba["id"])
    assert cv.sel == abajo["id"], "la selección no debe cambiar con un clic encima de otra capa"
    assert abs(float(la["x"]) - (xa + 80)) < 2 and abs(float(lb["x"]) - xb) < 0.5, (la["x"], xa, lb["x"], xb)
    print("✓ con una capa elegida en «Capas», arrastrar encima de otra mueve la elegida")
    # 2) doble clic en la de arriba (en una zona donde solo está ella) → pasa a ser la elegida
    solo_arriba = QPointF(float(lb["x"]) - 120, float(lb["y"]))
    assert cv._hit(solo_arriba) == arriba["id"]
    cv.mousePressEvent(ev(QEvent.MouseButtonPress, solo_arriba))
    cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, solo_arriba, Qt.NoButton))
    assert cv.sel == abajo["id"], "un clic simple no cambia la elegida"
    cv.mouseDoubleClickEvent(ev(QEvent.MouseButtonDblClick, solo_arriba))
    pump(app, 0.05)
    assert cv.sel == arriba["id"] and ed.cur()["id"] == arriba["id"], (cv.sel, arriba["id"])
    xb = float(ed.layer(arriba["id"])["x"])
    arrastrar(solo_arriba, -60)
    assert abs(float(ed.layer(arriba["id"])["x"]) - (xb - 60)) < 2
    print("✓ doble clic en otra capa del lienzo la elige; después se mueve esa")
    # 3) sin nada elegido, un clic elige la de arriba como siempre
    cv.sel = ""
    cv.multi.clear()
    p_top = QPointF(float(ed.layer(arriba["id"])["x"]), float(ed.layer(arriba["id"])["y"]))
    cv.mousePressEvent(ev(QEvent.MouseButtonPress, p_top))
    cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, p_top, Qt.NoButton))
    assert cv.sel == cv._hit(p_top) and cv.sel, cv.sel
    print("✓ sin nada elegido, un clic elige la capa de arriba (como siempre)")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
