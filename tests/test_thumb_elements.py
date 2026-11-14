"""
Prueba del buscador «🔎 PNG» del taller de miniaturas, de las propuestas desde tu imagen y de 🔥 mi estilo:
  · una imagen de internet se comprueba: PNG transparente / fondo liso (blanco) quitado / sin transparencia + tamaño;
  · el taller: pestaña «🔎 PNG»; «Usar en la miniatura» la baja y la añade; las propuestas parten de TU imagen y
    no meten nada por su cuenta;
  · mi estilo: Anton (viene con Reclaimer), blanca con la *palabra clave* en rojo, recuadro del logo, marco rojo.
Sin ventanas y sin internet. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_elements.py <carpeta>
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
from PySide6.QtCore import Qt  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import thumb_elements as E  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def flame(path, bg=None, size=600):
    im = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((size * 0.2, size * 0.25, size * 0.8, size * 0.95), fill=(255, 110, 20, 255))
    d.polygon([(size * 0.5, size * 0.02), (size * 0.25, size * 0.5), (size * 0.75, size * 0.5)], fill=(255, 200, 0, 255))
    im.save(path)
    return path


def data_url(path):
    import base64
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


def test_logic(out):
    rgba = np.asarray(Image.open(flame(os.path.join(out, "pegatina.png"), (255, 255, 255, 255))).convert("RGBA"))
    fixed = E.remove_flat_bg(rgba)
    tr = float((fixed[..., 3] < 20).mean())
    assert fixed is not None and 0.3 < tr < 0.8 and fixed[300, 300, 3] == 255, tr
    got = E.fetch(data_url(os.path.join(out, "pegatina.png")))
    assert got["badge"] == "Fondo quitado · 600×600" and got["cleaned"], got
    got = E.fetch(data_url(flame(os.path.join(out, "fuego.png"))))
    assert got["badge"] == "PNG transparente · 600×600", got
    Image.fromarray((np.random.default_rng(2).random((300, 300, 3)) * 255).astype(np.uint8)).save(
        os.path.join(out, "foto.png"))
    got = E.fetch(data_url(os.path.join(out, "foto.png")))
    assert got["badge"] == "Sin transparencia · 300×300 · pequeña", got
    print("✓ PNG de internet: se comprueba (transparente / fondo liso quitado / sin transparencia, tamaño)")


def test_editor(out):
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtGui import QFontDatabase
    from editoria.ai import bg_removal as BR
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    BR.is_available = lambda: False
    win = MainWindow()
    win.show()
    pump(app, 0.3)
    win.showNormal()
    win.setGeometry(0, 0, 1600, 1000)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    # 🔥 mi estilo
    assert "Anton" in QFontDatabase.families(), "Anton viene con Reclaimer"
    ed.add_text("ESTO ES *MALO*", "impact")
    imp = ed.cur()
    img, _w, _h = T.render_layer(imp)
    a = T.qimage_to_rgba(img).astype(int)
    vis = a[..., 3] > 250
    # el relleno exacto de la palabra clave (#E5232A), no el resplandor rojo (#FF1E1E) que rodea todo el texto
    red = vis & (np.abs(a[..., 0] - 229) < 12) & (np.abs(a[..., 1] - 35) < 15) & (np.abs(a[..., 2] - 42) < 15)
    white = vis & (a[..., 0] > 230) & (a[..., 1] > 230) & (a[..., 2] > 230)
    assert imp["font"] == "Anton" and red.sum() > 500 and white.sum() > 500, (red.sum(), white.sum())
    xs_red, xs_white = red.any(axis=0).nonzero()[0], white.any(axis=0).nonzero()[0]
    ys_red, ys_white = red.any(axis=1).nonzero()[0], white.any(axis=1).nonzero()[0]
    assert xs_red.mean() > xs_white.mean() or ys_red.mean() > ys_white.mean(), "lo rojo es «MALO», al final"
    ed.add_logo_box()
    assert ed.cur()["stroke"] == T.MY_RED and ed.cur()["y"] < ed.doc["h"] / 3
    photo = os.path.join(out, "mi_foto.jpg")
    Image.fromarray((np.random.default_rng(1).random((720, 1280, 3)) * 255).astype(np.uint8)).save(photo)
    ed.add_image(photo, "Mi foto")
    ed.red_frame()
    assert ed.cur()["outline"]["on"] and ed.cur()["outline"]["color"] == T.MY_RED
    print(f"✓ 🔥 mi estilo: Anton blanca con *MALO* en rojo ({red.sum()} px), recuadro del logo, marco rojo")
    # 🔎 PNG: la pestaña con el buscador; clic derecho «Usar en la miniatura» → se baja, se comprueba y se añade
    tabs = [ed.left_tabs.tabText(i) for i in range(ed.left_tabs.count())]
    assert "🔎 PNG" in tabs and not hasattr(ed, "elem_list"), tabs
    n = len(ed.doc["layers"])
    ed._png_mode = "png"                 # (como PNG: no depende del modo que tengas guardado en tus ajustes)
    ed.use_png(data_url(os.path.join(out, "pegatina.png")))
    t0 = time.time()
    while len(ed.doc["layers"]) == n and time.time() - t0 < 10:
        pump(app, 0.1)
    el = ed.doc["layers"][-1]
    assert len(ed.doc["layers"]) == n + 1 and el.get("element") and el["kind"] == "image", ed.doc["layers"][-1]
    assert ed.png_status.text() == "✓ Añadida a la miniatura y a «Material» · Fondo quitado · 600×600", ed.png_status.text()
    mat = [ed.material.item(i) for i in range(ed.material.count()) if ed.material.item(i).text() == "🔎 PNG"]
    assert mat and mat[0].data(Qt.UserRole) == el["path"], "la última bajada sale primero en «Material»"
    ed.material.itemClicked.emit(mat[0])                    # clic en «Material» = otra vez al lienzo
    assert len(ed.doc["layers"]) == n + 2 and ed.doc["layers"][-1].get("element")
    print("✓ 🔎 PNG: «Usar en la miniatura» → bajada, fondo blanco quitado y añadida; también queda en «Material»")
    # «Sin marca de agua»: quita los bancos de imágenes de la búsqueda y avisa si aun así se usa uno
    ed.png_nowm.setChecked(True)            # (el valor guardado es tuyo: aquí se prueba con la casilla marcada)
    q = E.no_watermark_query()
    assert "-site:pngtree.com" in q and "-site:shutterstock.com" in q
    assert E.watermark_site("https://png.pngtree.com/fuego.png") == "pngtree.com"
    assert E.watermark_site("https://static.vecteezy.com/fuego.png") is None
    real_fetch = E.fetch
    E.fetch = lambda url, **_k: real_fetch(data_url(os.path.join(out, "pegatina.png")))
    try:
        n2 = len(ed.doc["layers"])
        ed.use_png("https://png.pngtree.com/fuego.png")
        t0 = time.time()
        while len(ed.doc["layers"]) == n2 and time.time() - t0 < 10:
            pump(app, 0.1)
        assert "⚠ Viene de pngtree.com" in ed.png_status.text(), ed.png_status.text()
    finally:
        E.fetch = real_fetch
    print("✓ «Sin marca de agua»: fuera pngtree, Shutterstock, iStock…; y aviso si se usa una de esos bancos")
    # ✨ propuestas desde TU imagen (la del lienzo), sin meter nada por su cuenta
    ed.prop_text.setPlainText("El estudio está en decadencia")
    ed.make_proposals()
    t0 = time.time()
    while not ed._proposals and time.time() - t0 < 60:
        pump(app, 0.2)
    props = ed._proposals
    assert len(props) == 3, props
    srcs = [l["path"] for _n, d in props for l in d["layers"] if l["kind"] == "image" and not l.get("element")]
    assert photo in srcs, "parten de tu imagen"
    assert not any(l.get("element") for _n, d in props for l in d["layers"]), "nada de fuego automático"
    print("✓ ✨ propuestas desde tu imagen (sin añadir elementos por su cuenta)")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    test_logic(out_)
    test_editor(out_)
    print("TODO OK")
