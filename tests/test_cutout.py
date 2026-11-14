"""
Prueba de «quitar fondo» en el taller de miniaturas: automático, recuadro, pincel (borrar/recuperar),
deshacer, encuadrar al sujeto y la propuesta B con el personaje recortado.
Ejecutar:  .venv/Scripts/python.exe tests/test_cutout.py <carpeta_salida>
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

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import bg_removal as BR  # noqa: E402
from editoria.ai import thumb_proposals as P  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def wait_job(app, ed, secs=60):
    t0 = time.time()
    while ed.job is not None and time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.05)
    pump(app, 0.2)
    assert ed.job is None, "la tarea no terminó"


def mask_mean(path, box):
    m = cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
    h, w = m.shape
    x0, y0, x1, y1 = box
    return float(m[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].mean())


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    assert BR.is_available(), "falta el modelo de recorte"
    # Imagen de prueba: un «personaje» (cuerpo + cabeza) sobre un fondo con textura
    rng = np.random.default_rng(1)
    img = (rng.random((720, 1280, 3)) * 60 + 40).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 6)
    col = (40, 60, 200)
    cv2.ellipse(img, (640, 470), (130, 170), 0, 0, 360, col, -1)
    cv2.circle(img, (640, 250), 100, col, -1)
    cv2.circle(img, (605, 235), 14, (240, 240, 240), -1)
    cv2.circle(img, (675, 235), 14, (240, 240, 240), -1)
    src = os.path.join(out, "personaje.png")
    cv2.imwrite(src, img)

    # 1) Módulo: automático y con recuadro
    m = BR.remove(src)
    inside, corner = mask_mean(m, (0.45, 0.3, 0.55, 0.8)), mask_mean(m, (0.0, 0.0, 0.15, 0.25))
    assert inside > 0.6 and corner < 0.2, (inside, corner)
    mb = BR.remove(src, (0.35, 0.15, 0.65, 1.0))
    assert mask_mean(mb, (0.0, 0.0, 0.25, 1.0)) < 0.05
    print(f"✓ recorte automático (sujeto {inside:.2f} · fondo {corner:.2f}) y con recuadro")

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ed = win.open_thumbnail("youtube")
    ed.resize(1500, 900)
    pump(app, 0.3)
    if ed.job is not None:      # se cancela la búsqueda automática de fotogramas (no hay clips)
        wait_job(app, ed)
    ed.add_image(src, "Personaje", fill=True)
    lay = ed.cur()
    n0 = len(ed.history)

    # 2) Botón «Quitar fondo» (en segundo plano) → máscara + contorno tipo pegatina
    ed.cutout_auto()
    wait_job(app, ed)
    assert lay["mask"] and os.path.exists(lay["mask"]) and lay["outline"]["on"]
    # el cuadro se ajusta al personaje y este NO se mueve de sitio
    assert lay["crop"][0] > 0.3 and lay["crop"][2] < 0.7, lay["crop"]
    assert abs(lay["x"] - 640) < 15 and abs(lay["y"] - 395) < 25, (lay["x"], lay["y"])
    rendered = ed.canvas.grab()
    rendered.save(os.path.join(out, "recortado.png"))
    print("✓ «✂ Quitar fondo» desde el panel: máscara, contorno blanco y sombra")

    # 3) Pincel: borrar con el ratón sobre la cabeza y luego recuperar
    cv = ed.canvas
    ed.set_brush("erase")
    cv.brush = 40
    before = lay["mask"]
    p0, p1 = cv.mapFromScene(560, 250), cv.mapFromScene(720, 250)
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, p0)
    for i in range(1, 6):
        QTest.mouseMove(cv.viewport(), p0 + (p1 - p0) * (i / 5))
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, p1)
    while ed.brush_busy():                       # (los trazos se aplican en segundo plano)
        app.processEvents()
    erased = lay["mask"]
    assert erased != before and mask_mean(erased, (0.47, 0.32, 0.53, 0.37)) < 0.2, \
        mask_mean(erased, (0.47, 0.32, 0.53, 0.37))
    ed.set_brush("restore")
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, p0)
    QTest.mouseMove(cv.viewport(), p1)
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, p1)
    while ed.brush_busy():
        app.processEvents()
    assert mask_mean(ed.cur()["mask"], (0.47, 0.32, 0.53, 0.37)) > 0.8
    ed.set_brush(None)
    print("✓ pincel: borrar y recuperar (en los píxeles correctos de la imagen)")

    # 4) Deshacer vuelve a la máscara anterior; luego rehacer
    ed.undo()
    assert ed.cur() is None or ed.layer(lay["id"])["mask"] == erased
    ed.redo()
    print("✓ cada retoque se puede deshacer")

    # 5) Recuadro dibujado en el lienzo
    ed.canvas.sel = lay["id"]
    ed.start_box()
    a, b = cv.mapFromScene(440, 100), cv.mapFromScene(840, 720)
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(cv.viewport(), b)
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, b)
    wait_job(app, ed)
    cur = ed.layer(lay["id"])
    assert cv.tool is None and mask_mean(cur["mask"], (0.0, 0.0, 0.2, 1.0)) < 0.05
    print("✓ «⬚ Marcar con recuadro» en el lienzo")

    # 6) Encuadrar al sujeto y quitar el recorte
    ed.canvas.sel = lay["id"]
    ed.fit_to_subject()
    c = ed.layer(lay["id"])["crop"]
    assert c[0] > 0.2 and c[2] < 0.8, c
    ed._set_mask(lay["id"], None, "Quitar recorte")
    assert ed.layer(lay["id"])["mask"] is None
    assert len(ed.history) > n0 + 5
    print("✓ encuadrar al sujeto y quitar el recorte")

    # 7) Propuesta B con el personaje recortado (como pegatina)
    props = P.proposals("youtube", [src], "¿VALE LA PENA?", {}, {src: m})
    name, d = props[1]
    fg = [l for l in d["layers"] if l.get("mask")]
    assert name.startswith("B · Personaje recortado") and fg and fg[0]["outline"]["on"], name
    from editoria.core import thumbnail as T
    T.render(d, 0.5).save(os.path.join(out, "propuesta_B.png"))
    ed._cutouts[src] = m
    ed.reco = []
    ed.grab_frame = lambda t: src
    ed.make_proposals()
    wait_job(app, ed)
    assert ed.prop_list.count() >= 2 and "recortado" in ed.prop_list.item(1).text()
    print("✓ propuesta B: personaje recortado con contorno, sobre el fondo desenfocado")

    ed.close()
    win.analyzer.shutdown()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
