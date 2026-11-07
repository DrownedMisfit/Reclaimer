"""
Prueba de las caras graciosas (editoria/ai/funny_faces.py) con una cara de dibujo y los 5 puntos simulados:
  · cada preset nuevo: sus trazos están dentro de la imagen, deforma la capa, y el taller lo deshace con Ctrl+Z;
  · «Mirar…» mueve la pupila en la dirección pedida (centroide de un punto oscuro antes/después);
  · intensidad: «Exagerado» desplaza más que «Suave»; «Todas las caras» cambia las dos caras (y sin ella, solo una);
  · GROUPS reparte todas las claves de PRESETS sin repetir, y el taller muestra las pestañas.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_funny_faces.py <carpeta>
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_caras_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import liquify as L  # noqa: E402
from editoria.ai import funny_faces as FF  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def white_px(rgba, box):
    a = rgba[box[1]:box[3], box[0]:box[2]]
    return int((a[..., 0] > 128).sum())


def cara_en(im, ox=0, pupilas=False):
    """Una cara de dibujo centrada en x = 640 + ox: óvalo gris, ojos blancos (y pupilas negras), boca blanca."""
    cv2.ellipse(im, (640 + ox, 360), (170, 230), 0, 0, 360, (90, 90, 90, 255), -1)
    for x in (570, 710):
        cv2.circle(im, (x + ox, 300), 18, (255, 255, 255, 255), -1)
        if pupilas:
            cv2.circle(im, (x + ox, 300), 7, (0, 0, 0, 255), -1)
    cv2.ellipse(im, (640 + ox, 470), (55, 14), 0, 0, 360, (255, 255, 255, 255), -1)
    cv2.circle(im, (640 + ox, 380), 9, (200, 200, 200, 255), -1)          # nariz (para «Nariz grande»)
    box =(470.0 + ox, 130.0, 340.0, 460.0)
    return {"box": box, "re": (570.0 + ox, 300.0), "le": (710.0 + ox, 300.0), "nose": (640.0 + ox, 380.0),
            "mr": (585.0 + ox, 470.0), "ml": (695.0 + ox, 470.0)}


def lienzo(w=1280, h=720):
    im = np.zeros((h, w, 4), np.uint8)
    im[..., 3] = 255
    return im


def centroide_oscuro(rgba, box):
    """Centro de los píxeles casi negros dentro de la caja (la pupila)."""
    x0, y0, x1, y1 = box
    a = rgba[y0:y1, x0:x1]
    ys, xs = np.nonzero((a[..., 0] < 60) & (a[..., 3] > 128))
    assert len(xs) > 10, "no se ve la pupila"
    return float(xs.mean()) + x0, float(ys.mean()) + y0


def test_presets():
    keys = [k for k, _l, _t in FF.PRESETS]
    assert len(keys) == len(set(keys)), "claves de PRESETS repetidas"
    flat = [k for _g, claves in FF.GROUPS for k in claves]
    assert sorted(flat) == sorted(keys), (set(flat) ^ set(keys))
    assert len(flat) == len(set(flat)), "una clave en dos grupos"
    for k, label, tip in FF.PRESETS:
        assert label and tip and " " in label, (k, label)
    im = lienzo()
    face = cara_en(im)
    for k in keys:
        tr = FF.strokes(face, k, 1280, 720)
        assert tr, k
        for mode, x, y, r, s, mv in tr:
            assert mode in L.MODES and 0 <= x <= 1 and 0 <= y <= 1 and r > 0, (k, mode, x, y, r)
    print(f"✓ {len(keys)} presets en {len(FF.GROUPS)} grupos (sin repetir); todos sus trazos caen dentro de la imagen")


def test_each_preset(out):
    keys = [k for k, _l, _t in FF.PRESETS]
    im = lienzo()
    face = cara_en(im, pupilas=True)
    cv2.imwrite(os.path.join(out, "cara.png"), im)
    for k in keys:
        lay = {}
        assert FF.apply(lay, k, im, face), k
        assert "liquify" in lay, k
        res = L.apply(im, lay)
        assert not np.array_equal(res, im), f"{k} no cambió la cara"
        back = json.loads(json.dumps(lay))              # se guarda en el documento
        assert np.array_equal(L.apply(im, back), res), k
    print(f"✓ cada uno de los {len(keys)} presets deforma la capa y se guarda en el documento")


def test_directions(out):
    im = lienzo()
    face = cara_en(im, pupilas=True)
    base = L.apply(im, {})
    box = (530, 240, 610, 340)                          # alrededor del ojo derecho
    x0, y0 = centroide_oscuro(base, box)
    casos = {"arriba": (0, -1), "abajo": (0, 1), "izquierda": (-1, 0), "derecha": (1, 0)}
    for k, (dx, dy) in casos.items():
        lay = {}
        FF.apply(lay, k, im, face)
        x1, y1 = centroide_oscuro(L.apply(im, lay), box)
        avance = (x1 - x0) * dx + (y1 - y0) * dy
        lateral = abs((x1 - x0) * dy - (y1 - y0) * dx)
        assert avance > 6 and lateral < avance / 3, (k, x0, y0, x1, y1)     # se mueve en la dirección pedida
    # bizco: la pupila del ojo derecho se va hacia la nariz (a la derecha de la imagen)
    lay = {}
    FF.apply(lay, "bizco", im, face)
    x1, _ = centroide_oscuro(L.apply(im, lay), box)
    assert x1 - x0 > 6, (x0, x1)
    print("✓ Mirar arriba/abajo/izquierda/derecha y Bizco mueven la pupila hacia donde toca")


def test_intensidad(out):
    im = lienzo()
    face = cara_en(im, pupilas=True)
    box = (530, 240, 610, 340)
    x0, y0 = centroide_oscuro(L.apply(im, {}), box)
    desp = {}
    for nombre, val in FF.INTENSIDADES:
        lay = {}
        assert FF.apply(lay, "arriba", im, face, intensity=val)
        _x, y1 = centroide_oscuro(L.apply(im, lay), box)
        desp[nombre] = y0 - y1
    assert desp["Suave"] > 1 and desp["Suave"] < desp["Normal"] < desp["Exagerado"], desp
    assert desp["Exagerado"] > 1.8 * desp["Suave"], desp
    print(f"✓ intensidad: subir la pupila {desp['Suave']:.1f} px (suave), {desp['Normal']:.1f} (normal), "
          f"{desp['Exagerado']:.1f} px (exagerado)")


def test_todas(out):
    im = lienzo()
    f1 = cara_en(im, ox=-380)
    f2 = cara_en(im, ox=380)
    cv2.imwrite(os.path.join(out, "dos_caras.png"), im)
    zona = lambda cx: (cx - 40, 260, cx + 40, 340)      # noqa: E731 - el ojo izquierdo de cada cara
    izq, der = zona(570 - 380), zona(570 + 380)
    base = L.apply(im, {})
    a0, b0 = white_px(base, izq), white_px(base, der)
    antes = FF.faces
    FF.faces = lambda rgba: [f1, f2]
    try:
        lay = {}
        assert FF.apply(lay, "ojos", im, all_faces=True, intensity=1.0)
        res = L.apply(im, lay)
        assert white_px(res, izq) > a0 * 1.3 and white_px(res, der) > b0 * 1.3, (a0, b0, white_px(res, izq))
        lay2 = {}
        assert FF.apply(lay2, "ojos", im)                 # sin «Todas las caras»: solo la más grande
        res2 = L.apply(im, lay2)
        assert white_px(res2, izq) > a0 * 1.3 and white_px(res2, der) == b0, (white_px(res2, der), b0)
    finally:
        FF.faces = antes
    print("✓ Todas las caras: las dos caras cambian; sin la casilla, solo la más grande")


def test_editor(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtWidgets import QTabWidget
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
    im = lienzo()
    face = cara_en(im, pupilas=True)
    Image.fromarray(im).save(path)
    ed.add_image(path, "Foto", fill=True)
    assert ed.cur() is not None and ed.cur()["kind"] == "image"
    ed.act_liq.trigger()                                  # el panel ≈ Licuar muestra las pestañas
    pump(app, 0.1)
    tabs = [t for t in ed.findChildren(QTabWidget) if t.count() == len(FF.GROUPS)]
    assert tabs, "no está el panel de grupos"
    assert [tabs[0].tabText(i) for i in range(tabs[0].count())] == [g for g, _c in FF.GROUPS]
    FF_faces = FF.faces
    FF.faces = lambda rgba: [face]
    try:
        for k, _label, _tip in FF.PRESETS:
            assert ed.funny_face(k) and ed.cur().get("liquify"), k
            ed.undo()
            assert not ed.cur().get("liquify"), f"Ctrl+Z no quitó {k}"
    finally:
        FF.faces = FF_faces
    print(f"✓ taller: {len(FF.PRESETS)} presets, cada uno con un paso de deshacer; pestañas por grupo")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    test_presets()
    test_each_preset(out_)
    test_directions(out_)
    test_intensidad(out_)
    test_todas(out_)
    test_editor(out_)
    print("TODO OK")
