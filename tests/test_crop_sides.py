"""
⬚ Recortar arrastrando los rectángulos del centro de cada lado (taller de miniaturas):
  · arrastrar el lado derecho hacia dentro recorta por la derecha y el lado izquierdo NO se mueve (también girada y
    en espejo);
  · mientras se arrastra, la imagen NO se vuelve a procesar (fluido): solo una vez al soltar;
  · Ctrl+Z lo deshace.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_crop_sides.py <carpeta>
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


def mouse(canvas, kind, scene_pt: QPointF):
    pos = QPointF(canvas.mapFromScene(scene_pt))
    gpos = QPointF(canvas.viewport().mapToGlobal(pos.toPoint()))
    btn = Qt.LeftButton
    typ = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    ev = QMouseEvent(typ, pos, gpos, Qt.NoButton if kind == "move" else btn,
                     Qt.NoButton if kind == "release" else btn, Qt.NoModifier)
    {"press": canvas.mousePressEvent, "move": canvas.mouseMoveEvent, "release": canvas.mouseReleaseEvent}[kind](ev)


def corners(ed, lay):
    poly = ed.canvas._box(lay)
    return [poly.at(i) for i in range(4)]


def near(a, b, tol=1.5):
    return abs(a.x() - b.x()) < tol and abs(a.y() - b.y()) < tol


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    img = np.zeros((400, 800, 3), np.uint8)
    img[:, :400] = (230, 30, 30)                      # mitad izquierda roja, derecha azul
    img[:, 400:] = (30, 30, 230)
    path = os.path.join(out, "mitades.png")
    Image.fromarray(img).save(path)
    for rot, flip in ((0.0, False), (30.0, True)):
        ed.add_image(path, "Mitades")
        lay = ed.cur()
        lay.update(x=640.0, y=360.0, scale=1.0, rotation=rot, flip=flip)
        ed.commit("prueba")
        ed.canvas.sel = lay["id"]
        c0 = corners(ed, lay)
        lados = ed.canvas._side_points(c0)
        # coger el lado derecho de la IMAGEN (en espejo se ve a la izquierda: el asa va con la imagen)
        side = "r"
        start = lados[side]
        center = sum(c0, QPointF()) / 4
        destino = start + (center - start) * 1.0          # hasta el centro: queda la mitad
        calls = {"n": 0}
        real = T._image_content
        T._image_content = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1]
        mouse(ed.canvas, "press", start)
        n_press = calls["n"]
        t0 = time.perf_counter()
        for i in range(1, 31):
            mouse(ed.canvas, "move", start + (destino - start) * (i / 30))
            ed.canvas.viewport().repaint()
        per_move = (time.perf_counter() - t0) / 30 * 1000
        assert calls["n"] == n_press, "mientras se arrastra no se vuelve a procesar la imagen"
        mouse(ed.canvas, "release", destino)
        T._image_content = real
        c = lay["crop"]
        assert abs(c[2] - 0.5) < 0.03 and c[0] == 0 and c[1] == 0 and c[3] == 1, c
        c1 = corners(ed, lay)
        # el lado contrario (el izquierdo del contenido) sigue donde estaba
        assert near(c1[0], c0[0]) and near(c1[3], c0[3]), (c0, c1)
        rendered, cw, ch = T.render_layer(lay)
        arr = T.qimage_to_rgba(rendered)
        m = arr[arr.shape[0] // 2, arr.shape[1] // 2]
        assert m[0] > 150 and m[2] < 100, ("queda la parte roja", m)
        print(f"✓ recortar por un lado (giro {rot:g}°, espejo {'sí' if flip else 'no'}): crop {c}, el otro lado no "
              f"se mueve; {per_move:.1f} ms por movimiento, sin volver a procesar la imagen")
        ed.undo()
        assert ed.layer(lay["id"]) is None or ed.layer(lay["id"]).get("crop") in (None, [0, 0, 1, 1],
                                                                                  [0.0, 0.0, 1.0, 1.0])
    print("✓ Ctrl+Z deshace el recorte")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
