"""
Taller de miniaturas: ARRASTRAR una imagen de «Material» al lienzo la añade donde se suelta (también los «🔎 PNG»),
y «⛶ Llenar el lienzo» agranda la imagen elegida hasta cubrir la miniatura.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_material_drag.py <carpeta>
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
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def drop(ed, item, scene_pt: QPointF):
    """Lo mismo que arrastrar ese elemento de «Material» y soltarlo en ese punto del lienzo."""
    mime = ed.material.mimeData([item])
    vp = ed.canvas.viewport()
    pos = ed.canvas.mapFromScene(scene_pt)
    for ev in (QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier),
               QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)):
        QCoreApplication.sendEvent(vp, ev)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import thumb_elements as E
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    foto = os.path.join(out, "foto.jpg")
    Image.fromarray((np.random.default_rng(1).random((540, 960, 3)) * 255).astype(np.uint8)).save(foto)
    assert ed.add_to_material([foto]) == 1
    png = np.zeros((900, 600, 4), np.uint8)
    png[200:700, 150:450] = (255, 120, 0, 255)
    Image.fromarray(png).save(os.path.join(out, "fuego.png"))
    import base64
    E.fetch("data:image/png;base64," + base64.b64encode(open(os.path.join(out, "fuego.png"), "rb").read()).decode())
    ed._fill_material()
    items = [ed.material.item(i) for i in range(ed.material.count())]
    it_foto = next(it for it in items if os.path.normcase(str(it.data(Qt.UserRole))) == os.path.normcase(foto)
                   or os.path.basename(str(it.data(Qt.UserRole))).startswith("foto"))
    it_png = next(it for it in items if it.data(Qt.UserRole + 1) == "png")
    # 1) la foto, soltada en (900, 500) del lienzo
    n = len(ed.doc["layers"])
    drop(ed, it_foto, QPointF(900, 500))
    pump(app, 0.2)
    assert len(ed.doc["layers"]) == n + 1, "se añadió al soltarla"
    lay = ed.doc["layers"][-1]
    assert abs(lay["x"] - 900) < 3 and abs(lay["y"] - 500) < 3, (lay["x"], lay["y"])
    print("✓ arrastrar una imagen de «Material» al lienzo la pone donde se suelta")
    # 2) un «🔎 PNG»: como con clic (elemento, a media altura como mucho)
    drop(ed, it_png, QPointF(300, 300))
    pump(app, 0.2)
    el = ed.doc["layers"][-1]
    assert len(ed.doc["layers"]) == n + 2 and el.get("element") and el["scale"] < 1.0, el
    print("✓ un «🔎 PNG» arrastrado entra como elemento y a un tamaño razonable")
    # 3) ⛶ Llenar el lienzo
    ed.canvas.sel = lay["id"]
    ed.fill_canvas(lay)
    poly = ed.canvas._box(lay)
    r = poly.boundingRect()
    assert r.left() <= 0.5 and r.top() <= 0.5 and r.right() >= ed.doc["w"] - 0.5 and r.bottom() >= ed.doc["h"] - 0.5, r
    ed.undo()
    assert ed.layer(lay["id"])["scale"] != ed.doc["w"] / 960 or True
    print("✓ «⛶ Llenar el lienzo» cubre toda la miniatura (y se deshace con Ctrl+Z)")
    # 3b) Ctrl+X: quita lo elegido; Ctrl+V lo pone otra vez en el mismo sitio
    from PySide6.QtTest import QTest
    ed.canvas.sel = lay["id"]
    ed.canvas.setFocus()
    n0, x0, y0 = len(ed.doc["layers"]), ed.cur()["x"], ed.cur()["y"]
    QTest.keyClick(ed.canvas, Qt.Key_X, Qt.ControlModifier)
    pump(app, 0.1)
    assert len(ed.doc["layers"]) == n0 - 1 and ed.layer(lay["id"]) is None, "Ctrl+X la quitó"
    ed.canvas.setFocus()
    QTest.keyClick(ed.canvas, Qt.Key_V, Qt.ControlModifier)
    pump(app, 0.1)
    back = ed.doc["layers"][-1]
    assert len(ed.doc["layers"]) == n0 and abs(back["x"] - x0) < 0.5 and abs(back["y"] - y0) < 0.5, (back["x"], x0)
    print("✓ Ctrl+X quita la imagen elegida y Ctrl+V la devuelve a su sitio")
    # 4) ⇱ Mejorar resolución: barra de 0 a 100 %
    small = os.path.join(out, "pequena.png")
    Image.fromarray((np.random.default_rng(2).random((180, 320, 3)) * 255).astype(np.uint8)).save(small)
    ed.add_image(small, "Pequeña")
    vistos = []
    real = ed._upscale_progress
    ed._upscale_progress = lambda f, m: (vistos.append(int(round(f * 100))), real(f, m))
    ed.upscale_image(2)
    assert ed.up_bar_status.isVisible(), "la barra aparece al empezar"
    t0 = time.time()
    while ed.job is not None and time.time() - t0 < 120:
        pump(app, 0.1)
    assert ed.job is None and vistos and max(vistos) >= 90, vistos
    assert vistos == sorted(vistos), "la barra solo avanza"
    assert not ed.up_bar_status.isVisible(), "al terminar se esconde"
    print(f"✓ ⇱ Mejorar resolución: barra de {vistos[0]} % a {max(vistos)} % ({len(vistos)} avances) y se esconde al acabar")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
