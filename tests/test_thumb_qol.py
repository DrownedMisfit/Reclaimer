"""
Mejoras de calidad de vida del taller de miniaturas:
  · guías inteligentes: al mover, se pega a los bordes/centros de las otras capas (Ctrl = sin pegarse);
  · Alt+arrastrar = arrastrar una copia; Alt+rueda = agrandar/achicar lo elegido;
  · Mayús+clic / Ctrl+A: varias capas; se mueven y se borran juntas;
  · 🌫 fondo desenfocado detrás; 📐 plantillas propias; 📱 pasar la de YouTube a Short.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_qol.py <carpeta>
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
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def mouse(canvas, kind, scene_pt: QPointF, mods=Qt.NoModifier):
    pos = QPointF(canvas.mapFromScene(scene_pt))
    gpos = QPointF(canvas.viewport().mapToGlobal(pos.toPoint()))
    typ = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    ev = QMouseEvent(typ, pos, gpos, Qt.NoButton if kind == "move" else Qt.LeftButton,
                     Qt.NoButton if kind == "release" else Qt.LeftButton, mods)
    {"press": canvas.mousePressEvent, "move": canvas.mouseMoveEvent, "release": canvas.mouseReleaseEvent}[kind](ev)


def drag(canvas, a: QPointF, b: QPointF, mods=Qt.NoModifier, steps=10):
    mouse(canvas, "press", a, mods)
    for i in range(1, steps + 1):
        mouse(canvas, "move", a + (b - a) * (i / steps), mods)
    mouse(canvas, "release", b, mods)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    cv = ed.canvas
    cv.setMinimumSize(1100, 640)                     # (un lienzo de tamaño normal, como en la pantalla real)
    pump(app, 0.3)
    cv.refresh()
    path = os.path.join(out, "cuadro.png")
    Image.fromarray((np.random.default_rng(3).random((200, 200, 3)) * 255).astype(np.uint8)).save(path)
    ed.add_image(path, "A")
    a = ed.cur()
    a.update(x=300.0, y=330.0, scale=2.0)
    ed.add_image(path, "B")
    b = ed.cur()
    b.update(x=900.0, y=400.0, scale=2.0)
    ed.commit("prueba")
    print("  (asa en pantalla:", round(cv._handles(a)["k"], 2), "px de lienzo por px)")
    # 1) guías inteligentes: B, llevado cerca del borde izquierdo de A (x 200), se pega exacto
    cv.sel = b["id"]
    a_left = cv._box(a).boundingRect().left()
    b_left0 = cv._box(b).boundingRect().left()
    start = QPointF(b["x"], b["y"])
    drag(cv, start, start + QPointF(a_left - b_left0 + 4, -137))
    assert abs(cv._box(b).boundingRect().left() - a_left) < 0.6, (cv._box(b).boundingRect().left(), a_left)
    x_pegado = b["x"]
    drag(cv, QPointF(b["x"], b["y"]), QPointF(b["x"] + 3, b["y"]), Qt.ControlModifier)   # Ctrl: sin pegarse
    assert abs(b["x"] - (x_pegado + 3)) < 1.5      # (sin pegarse: se queda donde se suelta)
    print("✓ guías inteligentes: se pega al borde de la otra capa (Ctrl = sin pegarse)")
    # 2) Alt+arrastrar = una copia; Alt+rueda = tamaño
    n = len(ed.doc["layers"])
    drag(cv, QPointF(b["x"], b["y"]), QPointF(b["x"] + 150, b["y"] + 20), Qt.AltModifier)
    copia = ed.cur()
    assert len(ed.doc["layers"]) == n + 1 and copia["id"] != b["id"] and abs(copia["x"] - b["x"]) > 100
    s0 = copia["scale"]
    pos = QPointF(cv.mapFromScene(QPointF(copia["x"], copia["y"])))
    cv.wheelEvent(QWheelEvent(pos, QPointF(cv.viewport().mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, 240),
                              Qt.NoButton, Qt.AltModifier, Qt.NoScrollPhase, False))
    assert copia["scale"] > s0 * 1.1, (copia["scale"], s0)
    print("✓ Alt+arrastrar arrastra una copia; Alt+rueda la agranda")
    # 3) varias: Mayús+clic en A y B, moverlas juntas, borrarlas juntas; Ctrl+A
    a.update(x=250.0, y=360.0, scale=1.0)            # (separadas, sin taparse)
    b.update(x=700.0, y=360.0, scale=1.0)
    copia.update(x=1100.0, y=360.0, scale=1.0)
    ed.commit("separar")
    cv.sel = ""
    cv.multi.clear()
    mouse(cv, "press", QPointF(a["x"], a["y"]))
    mouse(cv, "release", QPointF(a["x"], a["y"]))
    mouse(cv, "press", QPointF(b["x"], b["y"]), Qt.ShiftModifier)
    assert cv.multi == {a["id"], b["id"]}, cv.multi
    ax, bx = a["x"], b["x"]
    drag(cv, QPointF(b["x"], b["y"]), QPointF(b["x"] + 37, b["y"] + 11), Qt.ControlModifier)
    assert abs(a["x"] - (ax + 37)) < 0.6 and abs(b["x"] - (bx + 37)) < 0.6, "se movieron juntas"
    n = len(ed.doc["layers"])
    ed.delete_layer()
    assert len(ed.doc["layers"]) == n - 2 and ed.layer(a["id"]) is None and ed.layer(b["id"]) is None
    ed.undo()
    ed.select_all()
    assert len(cv.multi) == len(ed.doc["layers"]) == n
    ed.select_tool()
    assert not cv.multi
    print("✓ Mayús+clic: varias capas, se mueven y se borran juntas; Ctrl+A elige todas; Esc lo suelta")
    # 4) 🌫 fondo desenfocado detrás
    a = ed.layer(a["id"])
    n = len(ed.doc["layers"])
    ed.blur_background(a)
    i = ed.doc["layers"].index(a)
    bg = ed.doc["layers"][i - 1]
    r = cv._box(bg).boundingRect()
    assert len(ed.doc["layers"]) == n + 1 and bg["adj"]["blur"] > 0.2 and bg["adj"]["exposure"] < 0
    assert r.left() <= 0.5 and r.top() <= 0.5 and r.right() >= 1279.5 and r.bottom() >= 719.5, r
    print("✓ 🌫 fondo desenfocado: la imagen llena la miniatura detrás, desenfocada y oscura")
    # 5) 📐 plantillas
    tp = ed.save_template("Mi estilo de prueba")
    assert os.path.exists(tp) and os.path.exists(tp[:-5] + ".png")
    assert [n_ for n_, _p in ed.templates()] == ["Mi estilo de prueba"] and ed.templates("short") == []
    n_tpl = len(ed.doc["layers"])
    ed.delete_all()
    assert ed.use_template(tp) == n_tpl and len(ed.doc["layers"]) == n_tpl
    print("✓ 📐 plantilla guardada (con vista previa) y usada otra vez")
    # 5b) doble clic en un texto = escribirlo; Ctrl+RePág / AvPág = orden
    ed.add_text("HOLA MUNDO", "title")
    t = ed.cur()
    t.update(x=640.0, y=200.0)
    ed.commit("texto")
    cv.sel = ""
    pos = QPointF(cv.mapFromScene(QPointF(t["x"], t["y"])))
    cv.mouseDoubleClickEvent(QMouseEvent(QEvent.MouseButtonDblClick, pos, QPointF(cv.viewport().mapToGlobal(
        pos.toPoint())), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert cv.sel == t["id"] and ed._text_edit.textCursor().selectedText() in ("HOLA MUNDO", "HOLA", "MUNDO")
    from PySide6.QtTest import QTest
    win.activateWindow()
    cv.setFocus()
    pump(app, 0.1)
    QTest.keyClick(cv, Qt.Key_PageDown, Qt.ControlModifier | Qt.ShiftModifier)
    assert ed.doc["layers"][0]["id"] == t["id"], "al fondo del todo"
    QTest.keyClick(cv, Qt.Key_PageUp, Qt.ControlModifier)
    assert ed.doc["layers"][1]["id"] == t["id"], "un paso adelante"
    print("✓ doble clic en un texto = escribirlo; Ctrl+RePág/AvPág (con Mayús, del todo) cambian el orden")
    # 6) 📱 de YouTube a Short
    assert ed.act_short.isVisible() or not ed.isVisible()
    assert ed.to_short(ask=False)
    assert ed.doc["format"] == "short" and len(ed.doc["layers"]) == n_tpl + 1
    fondo = next(l for l in ed.doc["layers"] if l["name"] == "Fondo desenfocado")
    rr = cv._box(fondo).boundingRect()
    assert rr.top() <= 0.5 and rr.bottom() >= ed.doc["h"] - 0.5, rr
    assert not ed.act_short.isVisible()
    print("✓ 📱 pasar a Short: misma composición en vertical, el fondo llena el alto")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
