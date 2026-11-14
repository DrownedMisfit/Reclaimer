"""
Miniatura · más libertad:
  · ➕ contornos apilados (texto e imágenes recortadas), por fuera del primero, en su orden;
  · 🎨 relleno de las letras: degradado (de c1 arriba a c2 abajo) e imagen; las palabras con color propio lo conservan;
  · 🎚 modos de fusión: multiplicar / trama cambian la mezcla en la exportación y en el lienzo;
  · 🌗 bordes suaves y fundido desde un lado; 🖌 pincel con dureza y opacidad;
  · ⭐ mis estilos: guardar, ponérselo a otra capa (o solo a las palabras elegidas), renombrar, borrar;
  · 🖼 plantillas con huecos: la imagen ocupa justo el hueco, con su sitio y sus efectos; «Cambiar la imagen».
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_libertad.py <carpeta>
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

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.005)


def rgba(img, T):
    return T.qimage_to_rgba(img.convertToFormat(img.Format.Format_ARGB32))


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_thumb_libertad")
    os.makedirs(out, exist_ok=True)
    import faulthandler
    faulthandler.dump_traceback_later(240, exit=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumbnail as T
    from editoria.core import thumb_styles as S
    from editoria.ai import bg_removal as BR
    S.RUTA = os.path.join(out, "estilos.json")
    if os.path.exists(S.RUTA):
        os.remove(S.RUTA)
    doc = T.new_doc("youtube")

    # ---------------------------------------------------------------- ➕ contornos apilados (texto)
    t = T.text_layer(doc, "HOLA")
    t["shadow"]["on"] = False
    t["outline"].update(on=True, color="#FFFFFF", width=10)
    i1, cw1, ch1 = T.render_layer(t)
    t2 = dict(t, outlines=[{"color": "#000000", "width": 8}, {"color": "#FF0000", "width": 6}])
    i2, cw2, ch2 = T.render_layer(t2)
    assert cw2 - cw1 >= 2 * 13, (cw1, cw2)
    a = rgba(i2, T)
    fila = a[a.shape[0] // 2]
    xs = np.nonzero(fila[:, 3] > 250)[0]
    x0 = int(xs[0])
    colores = [tuple(int(v) for v in fila[x, :3]) for x in range(x0, x0 + 24)]
    rojo = next(i for i, c in enumerate(colores) if c[0] > 200 and c[1] < 60)
    negro = next(i for i, c in enumerate(colores) if max(c) < 40)
    blanco = next(i for i, c in enumerate(colores) if min(c) > 215)
    assert rojo < negro < blanco, (rojo, negro, blanco, colores)
    print("✓ texto: contornos apilados por fuera, en su orden (rojo › negro › blanco › letra)")

    # ---------------------------------------------------------------- 🎨 relleno con degradado e imagen
    g = T.text_layer(doc, "III")
    g.update(size=300, uppercase=True)
    g["shadow"]["on"] = False
    g["outline"]["on"] = False
    g["text_fill"] = {"type": "gradient", "c1": "#FFFF00", "c2": "#0000FF", "angle": 90}
    a = rgba(T.render_layer(g)[0], T)
    ys, xs = np.nonzero(a[..., 3] > 250)
    arriba = a[ys.min() + 5, xs[ys == ys.min() + 5][0] + 3, :3]
    abajo = a[ys.max() - 5, xs[ys == ys.max() - 5][0] + 3, :3]
    assert arriba[0] > 180 and arriba[2] < 90, arriba
    assert abajo[2] > 180 and abajo[0] < 90, abajo
    print("✓ relleno con degradado: amarillo arriba, azul abajo")
    rayas = np.zeros((200, 200, 3), np.uint8)
    rayas[:, :100] = (0, 255, 0)
    rayas[:, 100:] = (255, 0, 255)
    rp = os.path.join(out, "rayas.png")
    cv2.imwrite(rp, rayas)
    g["text_fill"] = {"type": "image", "path": rp}
    a = rgba(T.render_layer(g)[0], T)
    vivos = a[a[..., 3] > 250][..., :3]
    verde = ((vivos[:, 1] > 200) & (vivos[:, 0] < 60)).mean()
    magenta = ((vivos[:, 0] > 200) & (vivos[:, 1] < 60)).mean()
    assert verde > 0.2 and magenta > 0.2, (verde, magenta)
    print("✓ relleno con imagen: las letras llevan la imagen dentro")
    w = T.text_layer(doc, "UNO DOS")
    w["shadow"]["on"] = False
    w["outline"]["on"] = False
    w["text_fill"] = {"type": "gradient", "c1": "#FFFF00", "c2": "#FFFF00", "angle": 90}
    T.set_word_style(w, {1}, color="#00FF00")
    img, cw, ch = T.render_layer(w)
    a = rgba(img, T)
    w["x"], w["y"] = img.width() / 2, img.height() / 2         # (así el lienzo y la imagen de la capa coinciden)
    q = dict(T.word_quads(w, img, cw, ch))
    for i, esperado in ((0, (255, 255, 0)), (1, (0, 255, 0))):
        r = q[i].boundingRect()
        zona = a[int(r.top()):int(r.bottom()), int(r.left()):int(r.right())]
        v = zona[zona[..., 3] > 250][..., :3].mean(axis=0)
        assert np.abs(v - esperado).max() < 30, (i, v)
    print("✓ con palabras sueltas: el relleno va al texto y la palabra con color propio lo conserva")

    # ---------------------------------------------------------------- ➕ contornos apilados (imagen recortada)
    foto = np.full((400, 400, 3), (40, 40, 200), np.uint8)
    fp = os.path.join(out, "foto.png")
    cv2.imwrite(fp, foto)
    mk = np.zeros((400, 400), np.uint8)
    cv2.circle(mk, (200, 200), 120, 255, -1)
    mp = os.path.join(out, "mascara.png")
    cv2.imwrite(mp, mk)
    im = T.image_layer(fp, doc)
    im.update(scale=1.0, mask=mp)
    im["outline"].update(on=True, color="#FFFFFF", width=10)
    im["outlines"] = [{"color": "#00FF00", "width": 10}]
    im["shadow"]["on"] = False
    a = rgba(T.render_layer(im)[0], T)
    cy = a.shape[0] // 2
    fila = a[cy]
    x0 = int(np.nonzero(fila[:, 3] > 250)[0][0])
    assert fila[x0 + 4, 1] > 200 and fila[x0 + 4, 0] < 60, fila[x0 + 4]          # verde por fuera
    assert min(fila[x0 + 15, :3]) > 215, fila[x0 + 15]                         # blanco por dentro
    print("✓ imagen recortada: el contorno de más va por fuera del primero (pegatina doble)")

    # ---------------------------------------------------------------- 🌗 bordes suaves y fundido
    sq = T.image_layer(fp, doc)
    sq.update(scale=1.0, feather=0.5)
    sq["shadow"]["on"] = False
    c = T._image_content(sq, 1.0)
    assert c[200, 200, 3] == 255 and c[2, 200, 3] < 20 and 30 < c[25, 200, 3] < 230, (c[200, 200, 3], c[2, 200, 3],
                                                                                    c[25, 200, 3])
    sq.update(feather=0, fade={"bottom": 0.5})
    c = T._image_content(sq, 1.0)
    assert c[5, 200, 3] == 255 and c[150, 200, 3] == 255 and c[399, 200, 3] < 5 and 20 < c[320, 200, 3] < 235
    sq["mask"] = mp
    sq.update(fade={}, feather=0.3)
    c = T._image_content(sq, 1.0)
    assert c[200, 200, 3] == 255 and 0 < c[200, 85, 3] < 200, c[200, 85, 3]   # el borde del círculo, suave
    print("✓ bordes suaves (también del sujeto recortado) y fundido desde abajo")

    # ---------------------------------------------------------------- 🎚 modos de fusión
    d2 = T.new_doc("youtube")
    d2["bg"] = {"type": "color", "color": "#808080"}
    capa = T.shape_layer(d2, "rect")
    capa.update(w=2000, h=2000, fill="#FF8000", stroke_w=0)
    capa["shadow"]["on"] = False
    d2["layers"] = [capa]
    normal = rgba(T.render(d2, 0.25), T)[90, 160, :3]
    capa["blend"] = "multiply"
    mult = rgba(T.render(d2, 0.25), T)[90, 160, :3]
    capa["blend"] = "screen"
    trama = rgba(T.render(d2, 0.25), T)[90, 160, :3]
    assert abs(int(normal[0]) - 255) < 3 and abs(int(normal[1]) - 128) < 3, normal
    assert abs(int(mult[0]) - 128) < 4 and abs(int(mult[1]) - 64) < 4 and int(mult[2]) < 4, mult
    assert int(trama[0]) > 250 and abs(int(trama[1]) - 191) < 4 and abs(int(trama[2]) - 128) < 4, trama
    print("✓ fusión: multiplicar oscurece y trama aclara (igual que en Photoshop)")

    # ---------------------------------------------------------------- 🖌 dureza y opacidad del pincel
    full = os.path.join(out, "llena.png")
    cv2.imwrite(full, np.full((400, 400), 255, np.uint8))
    m = cv2.imread(BR.paint(full, fp, [(100, 200), (300, 200)], 30, False, alpha=0.5), cv2.IMREAD_GRAYSCALE)
    assert 120 <= m[200, 200] <= 135 and m[100, 200] == 255, (m[200, 200], m[100, 200])
    m = cv2.imread(BR.paint(full, fp, [(100, 200), (300, 200)], 30, False, hard=0.0), cv2.IMREAD_GRAYSCALE)
    assert m[200, 200] < 40 and 60 < m[229, 200] < 230, (m[200, 200], m[229, 200])
    m = cv2.imread(BR.paint(full, fp, [(100, 200), (300, 200)], 30, False), cv2.IMREAD_GRAYSCALE)
    assert m[200, 200] == 0 and m[240, 200] == 255
    print("✓ pincel: opacidad 50 % borra la mitad; dureza 0 deja el borde suave; por defecto, como antes")

    # ---------------------------------------------------------------- ⭐ estilos (núcleo)
    est = S.add("Rojo gordo", t2)
    assert est and est["kind"] == "text" and "outlines" in est["style"] and "text" not in est["style"]
    otro = T.text_layer(doc, "ADIÓS")
    cambios = S.changes(otro, est)
    assert "size" not in cambios and "x" not in cambios and cambios["outlines"] == t2["outlines"]
    assert S.changes(im, est) == {}
    assert S.rename("Rojo gordo", "text", "Mi título") and [e["name"] for e in S.of_kind("text")] == ["Mi título"]
    S.add("Imagen", im)
    assert len(S.load()) == 2
    S.remove("Imagen", "image")
    assert [e["name"] for e in S.load()] == ["Mi título"]
    print("✓ estilos: se guardan solo el aspecto (sin texto, sitio ni tamaño), se renombran y se borran")

    # ---------------------------------------------------------------- 🖼 huecos (núcleo)
    ancha = np.zeros((300, 900, 3), np.uint8)
    ancha[:, :450] = (255, 0, 0)
    ancha[:, 450:] = (0, 0, 255)
    ap = os.path.join(out, "ancha.png")
    cv2.imwrite(ap, ancha)
    base = T.image_layer(fp, doc)
    base.update(scale=0.8, x=300.0, y=250.0, rotation=12.0, blend="screen")
    base["glow"]["on"] = True
    hueco = T.slot_from(base)
    assert hueco["slot"] and hueco["kind"] == "shape" and abs(hueco["w"] - 320) < 1.5 and abs(hueco["h"] - 320) < 1.5
    assert hueco["rotation"] == 12.0 and hueco["blend"] == "screen" and hueco["glow"]["on"]
    nueva = T.fill_box(hueco, ap, doc)
    bw, bh = T.box_size(nueva)
    assert abs(bw - 320) < 2 and abs(bh - 320) < 2, (bw, bh)
    assert (nueva["x"], nueva["y"], nueva["rotation"], nueva["blend"]) == (300.0, 250.0, 12.0, "screen")
    assert abs(nueva["crop"][0] - 1 / 3) < 0.01 and abs(nueva["crop"][2] - 2 / 3) < 0.01, nueva["crop"]
    print("✓ hueco: la imagen ocupa justo su caja (recortada por el centro, sin deformarse) con su sitio y efectos")

    # ---------------------------------------------------------------- en el taller
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    cv = ed.canvas
    ed.add_text("PRIMERO", "title")
    a_ = ed.cur()
    n0 = len(a_.get("outlines") or [])
    ed.add_outline(a_)
    pump(app, 0.05)
    assert len(a_["outlines"]) == n0 + 1
    ed.add_text("SEGUNDO", "title")
    b_ = ed.cur()
    est = ed.save_style("Doble", a_)
    assert est is not None
    ed.canvas.sel = b_["id"]
    ed._fill_props()
    pos = ed.pos
    assert ed.apply_style(est) == 1
    assert b_["outlines"] == a_["outlines"] and b_["text"] == "SEGUNDO" and ed.pos == pos + 1
    ed.undo()
    b_ = ed.cur()
    assert b_.get("outlines") != a_["outlines"]
    ed.redo()
    b_ = ed.cur()
    print("✓ taller: ➕ otro contorno, 💾 guardar estilo, clic = ponérselo a otra capa (un Ctrl+Z)")
    # solo a la palabra elegida
    ed.add_text("TRES CUATRO", "title")
    c_ = ed.cur()
    rojo = {"name": "Rojo", "kind": "text", "style": {"color": "#FF0000", "font": "Arial", "spacing": 1.4}}
    cv.set_words({1}, c_)
    ed.apply_style(rojo)
    c_ = ed.cur()
    assert c_["word_styles"]["1"]["color"] == "#FF0000" and c_["color"] != "#FF0000" and c_["spacing"] != 1.4
    print("✓ con palabras elegidas, el estilo va solo a ellas (lo que se puede por palabra)")
    cv.set_words(set(), c_)
    # fusión y bordes suaves desde el panel (los controles existen) y en el lienzo
    ed.add_image(fp, "Foto")
    f_ = ed.cur()
    ed._set(f_, "Fusión", blend="multiply")
    ed._set(f_, "Bordes suaves", feather=0.2)
    assert ed.cur()["blend"] == "multiply" and ed.cur()["feather"] == 0.2
    from PySide6.QtWidgets import QComboBox, QPushButton
    ed._fill_props()
    pump(app, 0.05)
    fus = [c for c in ed.props.findChildren(QComboBox) if c.findData("multiply") >= 0] if hasattr(ed, "props") else \
        [c for c in ed.findChildren(QComboBox) if c.findData("multiply") >= 0]
    assert fus and fus[-1].currentData() == "multiply"
    cv.viewport().repaint()
    pump(app, 0.1)
    textos = [b.text() for b in ed.findChildren(QPushButton) if b.isVisibleTo(ed)]
    assert any("Cambiar la imagen" in x for x in textos) and any("Guardar este estilo" in x for x in textos)
    print("✓ panel: Fusión, 🌗 Bordes suaves, 🔁 Cambiar la imagen y ⭐ Mis estilos a la vista")
    # pincel: dureza y opacidad se recuerdan y van al trazo
    ed.set_brush_opt("alpha", 0.4)
    ed.set_brush_opt("hard", 0.25)
    ed.__dict__.pop("_brush_opts", None)
    assert abs(ed.brush_opt("alpha") - 0.4) < 1e-6 and abs(ed.brush_opt("hard") - 0.25) < 1e-6
    ed.set_brush_opt("alpha", 1.0)
    ed.set_brush_opt("hard", 1.0)
    # plantilla con huecos
    ed.add_image(ap, "Ancha")
    path = ed.save_template("Prueba huecos", slots=True)
    assert os.path.exists(path)
    n = ed.use_template(path)
    huecos = [l for l in ed.doc["layers"] if l.get("slot")]
    assert n >= 3 and len(huecos) == 2, (n, len(huecos))
    hz = huecos[0]
    caja = T.box_size(hz)
    ed.canvas.sel = hz["id"]
    ed.add_image(ap, "Ancha")                        # con un hueco elegido, «añadir» lo llena
    puesta = ed.cur()
    assert puesta["kind"] == "image" and not puesta.get("slot")
    assert sum(1 for l in ed.doc["layers"] if l.get("slot")) == 1
    bw, bh = T.box_size(puesta)
    assert abs(bw - caja[0]) < 2 and abs(bh - caja[1]) < 2, (bw, bh, caja)
    print("✓ plantilla con huecos: las imágenes quedan como huecos y lo que añades va al hueco elegido, a su medida")
    # cambiar la imagen de una capa: misma caja
    antes = T.box_size(puesta)
    otra = ed.replace_image(puesta, fp)
    assert otra is not None and abs(T.box_size(otra)[0] - antes[0]) < 2 and abs(T.box_size(otra)[1] - antes[1]) < 2
    print("✓ 🔁 Cambiar la imagen: la nueva ocupa la misma caja")
    # lienzo: los huecos se dibujan y la fusión no rompe el repintado
    cv.viewport().repaint()
    pump(app, 0.1)

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    ed.close()
    pump(app, 0.2)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
