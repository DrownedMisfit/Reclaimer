"""
Prueba de «≈ Licuar» y las caras graciosas del taller de miniaturas (ojos saltones, bocota…):
  · el licuado: inflar agranda, encoger achica, empujar mueve, restaurar lo quita; se guarda en el documento (JSON)
    y el dibujo con el pincel es rápido (caché del contenido sin licuar);
  · caras graciosas con los 5 puntos de una cara (ojos, nariz, comisuras) simulados: cada una deforma donde toca;
  · el taller: pintar con el pincel en el lienzo, Ctrl+Z, «↺ Quitar licuado» y un clic en «👀 Ojos saltones».
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_liquify.py <carpeta>
"""
from __future__ import annotations

import json
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
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import liquify as L  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def white_px(rgba, box=None):
    a = rgba if box is None else rgba[box[1]:box[3], box[0]:box[2]]
    return int((a[..., 0] > 128).sum())


def cara(path, w=1280, h=720):
    """Una «cara» de dibujo: óvalo gris, ojos y boca blancos, para ver dónde deforma cada cara graciosa."""
    im = np.zeros((h, w, 4), np.uint8)
    im[..., 3] = 255
    cv2.ellipse(im, (640, 360), (170, 230), 0, 0, 360, (90, 90, 90, 255), -1)
    for x in (570, 710):
        cv2.circle(im, (x, 300), 18, (255, 255, 255, 255), -1)
    cv2.ellipse(im, (640, 470), (55, 14), 0, 0, 360, (255, 255, 255, 255), -1)
    Image.fromarray(im).save(path)
    face = {"box": (470.0, 130.0, 340.0, 460.0), "re": (570.0, 300.0), "le": (710.0, 300.0), "nose": (640.0, 380.0),
            "mr": (585.0, 470.0), "ml": (695.0, 470.0)}
    return im, face


def test_core():
    img = np.zeros((360, 640, 4), np.uint8)
    img[..., 3] = 255
    cv2.circle(img, (320, 180), 20, (255, 255, 255, 255), -1)
    lay = {}
    L.stroke(lay, "inflar", 0.5, 0.5, 0.2, 0.5, 640 / 360)
    assert white_px(L.apply(img, lay)) > white_px(img) * 1.8, "inflar agranda"
    lay2 = {}
    L.stroke(lay2, "encoger", 0.5, 0.5, 0.2, 0.5, 640 / 360)
    assert white_px(L.apply(img, lay2)) < white_px(img) * 0.7, "encoger achica"
    lay3 = {}
    L.stroke(lay3, "empujar", 0.5, 0.5, 0.15, 1.0, 640 / 360, (0.1, 0.0))
    xs = np.nonzero(L.apply(img, lay3)[..., 0] > 128)[1]
    assert xs.mean() > 340, xs.mean()
    L.stroke(lay, "restaurar", 0.5, 0.5, 0.6, 1.0, 640 / 360)
    assert white_px(L.apply(img, lay)) < white_px(img) * 1.4, "restaurar devuelve la forma (poco a poco)"
    for _ in range(12):
        L.stroke(lay, "restaurar", 0.5, 0.5, 0.6, 1.0, 640 / 360)
    assert "liquify" not in lay, "restaurar del todo = sin licuado"
    back = json.loads(json.dumps(lay2))                       # se guarda en el documento (y el proyecto)
    assert np.array_equal(L.apply(img, back), L.apply(img, lay2))
    print("✓ licuar: inflar agranda, encoger achica, empujar mueve, restaurar lo quita; se guarda en el documento")


def test_faces(out):
    from editoria.ai import funny_faces as FF
    im, face = cara(os.path.join(out, "cara.png"))
    eye = (550, 280, 590, 320)
    mouth = (570, 440, 710, 500)
    for preset, region, more in (("ojos", eye, True), ("boca", mouth, True), ("carita", (400, 80, 880, 640), False)):
        lay = {}
        assert FF.apply(lay, preset, im, face)
        res = L.apply(im, lay)
        a, b = white_px(im, region), white_px(res, region)
        assert (b > a * 1.3) if more else (white_px(res) < white_px(im)), (preset, a, b)
    lay = {}
    FF.apply(lay, "estirada", im, face)
    res = L.apply(im, lay)
    rows = np.nonzero((res[..., 0] > 60).any(axis=1))[0]
    assert rows.min() < 130 - 20 and rows.max() > 590 + 20, (rows.min(), rows.max())
    for key, _label, _tip in FF.PRESETS:
        assert FF.strokes(face, key, 1280, 720), key
    print("✓ caras graciosas: ojos saltones, bocota y cara estirada deforman donde toca; carita encoge")


def test_editor(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    pump(app, 0.3)
    win.setGeometry(0, 0, 1600, 1000)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    path = os.path.join(out, "cara.png")
    im, face = cara(path)
    ed.add_image(path, "Foto", fill=True)
    lay = ed.cur()
    assert lay is not None and lay["kind"] == "image"
    # ≈ Licuar con el ratón: inflar sobre un ojo, manteniendo pulsado
    ed.act_liq.trigger()
    assert ed.canvas.tool == "liquify"
    ed.set_liq_mode("inflar")
    ed.canvas.brush = 40
    ed.canvas.liq_strength = 1.0
    img, cw, ch = T.render_layer(lay)
    eye_canvas = T.layer_transform(lay, img).map(QPointF((img.width() - cw) / 2 + 570, (img.height() - ch) / 2 + 300))
    c = ed.canvas.content_point(lay, eye_canvas)
    assert abs(c["fx"] - 570 / 1280) < 0.01 and abs(c["fy"] - 300 / 720) < 0.01, c
    steps = len(ed.history)
    ed.canvas._drag = {"mode": "liquify", "lay": lay, "last": c, "pos": c}
    t0 = time.time()
    for _ in range(8):
        ed.canvas._liq_tick()
    dab_ms = (time.time() - t0) * 1000 / 8
    ed.canvas._drag = None
    ed.liquify_done()
    lay = ed.cur()
    assert lay.get("liquify") and len(ed.history) == steps + 1
    res = T.qimage_to_rgba(T.render_layer(lay)[0])
    pad_x, pad_y = (res.shape[1] - 1280) // 2, (res.shape[0] - 720) // 2
    region = (550 + pad_x, 280 + pad_y, 590 + pad_x, 320 + pad_y)
    assert white_px(res, region) > white_px(im, (550, 280, 590, 320)) * 1.1
    assert dab_ms < 150, dab_ms
    print(f"✓ pincel ≈ Licuar en el lienzo: el ojo creció ({dab_ms:.0f} ms por toque); un paso de deshacer")
    ed.undo()
    assert not ed.cur().get("liquify"), "Ctrl+Z lo quita"
    ed.redo()
    assert ed.cur().get("liquify")
    ed.liquify_reset()
    assert not ed.cur().get("liquify")
    # 😜 un clic: con la cara de dibujo (YuNet no ve caras dibujadas) se simula la detección
    from editoria.ai import funny_faces as FF
    FF_faces = FF.faces
    FF.faces = lambda rgba: [face]
    try:
        assert ed.funny_face("ojos") and ed.cur().get("liquify")
    finally:
        FF.faces = FF_faces
    ed.undo()
    assert not ed.cur().get("liquify")
    FF.faces = lambda rgba: []
    try:
        assert not ed.funny_face("boca") and "ninguna cara" in ed.statusBar().currentMessage()
    finally:
        FF.faces = FF_faces
    # ✋ Estirar con el ratón: lo que hay en el círculo llega donde se suelta (en pasos pequeños, sin desgarros)
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    ed.liquify_reset()
    ed.act_stretch.trigger()
    assert ed.canvas.tool == "liquify" and ed.canvas.liq_mode == "empujar"
    assert ed.act_stretch.isChecked() and not ed.act_liq.isChecked() and not ed.act_select.isChecked()
    lay = ed.cur()
    img, cw, ch = T.render_layer(lay)
    t = T.layer_transform(lay, img)
    ox, oy = (img.width() - cw) / 2, (img.height() - ch) / 2
    a_s, b_s = t.map(QPointF(ox + 710, oy + 300)), t.map(QPointF(ox + 860, oy + 300))   # del ojo izq. a 150 px

    def ev(kind, scene_pt, buttons):
        vp = ed.canvas.mapFromScene(scene_pt)
        return QMouseEvent(kind, QPointF(vp), QPointF(ed.canvas.viewport().mapToGlobal(vp)),
                           Qt.LeftButton, buttons, Qt.NoModifier)
    ed.canvas.brush = 60
    ed.canvas.mousePressEvent(ev(QEvent.MouseButtonPress, a_s, Qt.LeftButton))
    for i in range(1, 5):                                   # 4 movimientos grandes (un arrastre rápido)
        ed.canvas.mouseMoveEvent(ev(QEvent.MouseMove, a_s + (b_s - a_s) * (i / 4), Qt.LeftButton))
    ed.canvas.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, b_s, Qt.NoButton))
    res = T.qimage_to_rgba(T.render_layer(ed.cur())[0])
    px, py = (res.shape[1] - 1280) // 2, (res.shape[0] - 720) // 2
    near_b = white_px(res, (840 + px, 285 + py, 880 + px, 315 + py))
    left_a = white_px(res, (700 + px, 290 + py, 720 + px, 310 + py))
    assert near_b > 400 and left_a < 100, (near_b, left_a)
    ed.act_liq.trigger()                                    # «≈ Licuar» después de Estirar vuelve a inflar
    assert ed.canvas.liq_mode == "inflar" and ed.act_liq.isChecked() and not ed.act_stretch.isChecked()
    print("✓ ✋ Estirar: el ojo agarrado llegó donde se soltó el ratón (también con un arrastre rápido)")
    ed.toggle_liquify(False)
    assert ed.canvas.tool is None
    print("✓ «👀 Ojos saltones» de un clic (Ctrl+Z lo deshace), aviso si no hay cara, «↺ Quitar licuado»")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    test_core()
    test_faces(out_)
    test_editor(out_)
    print("TODO OK")
