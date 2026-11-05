"""
Prueba de la columna «Capas» del taller de miniaturas, de «Eliminar» / «Eliminar todo» y de «↖ Seleccionar»:
  · la columna está siempre a la vista (no es una pestaña), arriba = delante, con miniatura de cada capa;
  · reordenar arrastrando cambia el orden del lienzo; «🗑 Eliminar» quita la elegida; «Eliminar todo» las quita
    todas menos las bloqueadas; Ctrl+Z lo recupera;
  · «↖ Seleccionar» (o Esc) deja Licuar, Deformar o los pinceles y vuelve al ratón normal.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_layers.py <carpeta>
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
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    pump(app, 0.3)
    win.setGeometry(0, 0, 1600, 1000)
    ed = win.open_thumbnail("short")
    pump(app, 0.3)
    tabs = [ed.left_tabs.tabText(i) for i in range(ed.left_tabs.count())]
    assert "Capas" not in tabs and ed.layers.isVisible(), tabs
    print("✓ «Capas» es una columna siempre a la vista junto al lienzo (ya no una pestaña escondida)")
    paths = []
    for i, c in enumerate(((220, 40, 40), (40, 200, 60), (40, 80, 220))):
        p = os.path.join(out, f"img{i}.png")
        Image.fromarray(np.full((300, 300, 3), c, np.uint8)).save(p)
        paths.append(p)
        ed.add_image(p, f"Imagen {i + 1}")
    names = [ed.layers.item(i).text() for i in range(ed.layers.count())]
    assert names[:3] == ["Imagen 3", "Imagen 2", "Imagen 1"], names          # arriba = delante
    assert not ed.layers.item(0).icon().isNull(), "cada capa con su miniatura"
    # reordenar arrastrando: la última de la lista pasa arriba
    it = ed.layers.takeItem(2)
    ed.layers.insertItem(0, it)
    ed._layers_dragged()
    assert [l["name"] for l in ed.doc["layers"]][-1] == "Imagen 1", [l["name"] for l in ed.doc["layers"]]
    print("✓ arriba = delante, con miniatura; arrastrar en la lista cambia el orden del lienzo")
    n = len(ed.doc["layers"])
    ed.layers.setCurrentRow(0)
    ed.delete_layer()
    assert len(ed.doc["layers"]) == n - 1
    ed.undo()
    assert len(ed.doc["layers"]) == n
    ed.doc["layers"][0]["locked"] = True
    ed.commit("Bloquear")
    ed.delete_all()
    assert [l.get("locked") for l in ed.doc["layers"]] == [True], ed.doc["layers"]
    assert "Ctrl+Z" in ed.statusBar().currentMessage()
    ed.undo()
    assert len(ed.doc["layers"]) == n
    acts = [a.text() for a in ed.findChildren(type(ed.act_liq)) if a.text()]
    assert "🗑 Eliminar" in acts and "Eliminar todo" in acts, acts
    print("✓ «🗑 Eliminar» y «Eliminar todo» (las bloqueadas se quedan); Ctrl+Z lo recupera")
    # ↖ Seleccionar
    assert ed.act_select.isChecked()
    ed.act_liq.trigger()
    assert ed.canvas.tool == "liquify" and not ed.act_select.isChecked()
    ed.act_select.trigger()
    assert ed.canvas.tool is None and not ed.act_liq.isChecked() and ed.act_select.isChecked()
    ed.act_warp.trigger()
    assert ed.canvas.warp_mode and not ed.act_select.isChecked()
    ed.select_tool()                                        # (lo que hace Esc)
    assert not ed.canvas.warp_mode and ed.act_select.isChecked()
    ed.set_brush("erase")
    assert not ed.act_select.isChecked()
    ed.act_select.trigger()
    assert ed.canvas.tool is None and ed.act_select.isChecked()
    print("✓ «↖ Seleccionar» (o Esc) vuelve al ratón normal desde Licuar, Deformar y los pinceles")
    # arrastrar y soltar en el lienzo: un archivo, una imagen sin archivo y un video (su fotograma)
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QImage
    import subprocess
    from editoria.core import media as M
    n = len(ed.doc["layers"])
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(paths[1])])
    assert ed.drop_on_canvas(m, QPointF(300, 1500)) == 1
    lay = ed.doc["layers"][-1]
    assert (lay["x"], lay["y"]) == (300, 1500) and os.path.samefile(lay["path"], paths[1]), lay
    m = QMimeData()
    q = QImage(120, 80, QImage.Format_ARGB32)
    q.fill(Qt.red)
    m.setImageData(q)
    assert ed.drop_on_canvas(m, QPointF(500, 500)) == 1 and os.path.exists(ed.doc["layers"][-1]["path"])
    vid = os.path.join(out, "clip.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=3",
                    "-pix_fmt", "yuv420p", vid], check=True)
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(vid)])
    assert ed.drop_on_canvas(m, QPointF(540, 960)) == 1 and ed.doc["layers"][-1]["path"].endswith(".png")
    m = QMimeData()
    m.setText("hola")
    assert ed.drop_on_canvas(m, QPointF(10, 10)) == 0 and "no es una imagen" in ed.statusBar().currentMessage()
    assert len(ed.doc["layers"]) == n + 3
    ed.undo()
    assert len(ed.doc["layers"]) == n + 2, "cada imagen soltada es un paso de deshacer"
    ed._fill_material()
    items = [ed.material.item(i) for i in range(ed.material.count())]
    if items:
        urls = ed.material.mimeData(items[:1]).urls()
        assert urls and urls[0].isLocalFile()
    assert ed.canvas.acceptDrops()
    print("✓ arrastrar al lienzo: archivos, imágenes sin archivo y videos (un fotograma), donde se sueltan")
    # cambiar de imagen apaga la herramienta (era para la anterior) y cada imagen guarda sus propios efectos
    ids = [l["id"] for l in ed.doc["layers"] if l["kind"] == "image"][:2]
    ed.canvas.sel = ids[0]
    ed._on_select(ids[0])
    ed.act_liq.trigger()
    assert ed.canvas.tool == "liquify"
    ed.cur()["outline"]["on"] = True
    ed.canvas.sel = ids[1]
    ed._on_select(ids[1])
    assert ed.canvas.tool is None and ed.act_select.isChecked(), "al cambiar de imagen, ratón normal"
    other = next(l for l in ed.doc["layers"] if l["id"] == ids[1])
    assert not other["outline"]["on"], "los efectos de una imagen no pasan a la otra"
    ed.act_warp.trigger()
    row = next(i for i in range(ed.layers.count()) if ed.layers.item(i).data(Qt.UserRole) == ids[0])
    ed.layers.setCurrentRow(row)                              # (elegir en la lista de capas)
    assert not ed.canvas.warp_mode and ed.canvas.sel == ids[0]
    print("✓ cambiar de imagen apaga Licuar/Deformar (vuelve el ratón normal); los efectos no se mezclan")
    # en la capa elegida de la lista: 👁 ocultar y 🗑 eliminar, ahí mismo
    from PySide6.QtWidgets import QToolButton
    libre = next(i for i in range(ed.layers.count())
                 if not ed.layer(ed.layers.item(i).data(Qt.UserRole)).get("locked"))
    ed.layers.setCurrentRow(libre)
    w = ed.layers.itemWidget(ed.layers.currentItem())
    btns = {b.toolTip(): b for b in w.findChildren(QToolButton)}
    assert set(btns) == {"Ocultar", "Eliminar (Supr)"}, list(btns)
    lid = ed.canvas.sel
    btns["Ocultar"].click()
    pump(app, 0.1)
    assert not ed.layer(lid)["visible"]
    btns = {b.toolTip(): b for b in ed.layers.itemWidget(ed.layers.currentItem()).findChildren(QToolButton)}
    assert "Mostrar" in btns and "(oculta)" in ed.layers.currentItem().text()
    btns["Mostrar"].click()
    pump(app, 0.1)
    assert ed.layer(lid)["visible"]
    n = len(ed.doc["layers"])
    {b.toolTip(): b for b in ed.layers.itemWidget(ed.layers.currentItem()).findChildren(QToolButton)}[
        "Eliminar (Supr)"].click()
    pump(app, 0.1)
    assert len(ed.doc["layers"]) == n - 1 and ed.layer(lid) is None
    ed.undo()
    print("✓ capa elegida en la lista: 👁 ocultar / mostrar y 🗑 eliminar ahí mismo (y clic derecho)")
    # soltar en «Material» imágenes y carpetas del PC (Explorador / escritorio)
    from PySide6.QtCore import QMimeData, QPoint, QUrl
    from PySide6.QtGui import QDropEvent
    carpeta = os.path.join(out, "mis_imagenes")
    os.makedirs(os.path.join(carpeta, "sub"), exist_ok=True)
    for i, sub in enumerate(("", "sub")):
        Image.fromarray(np.full((64, 64, 3), 40 * (i + 2), np.uint8)).save(os.path.join(carpeta, sub, f"m{i}.png"))
    suelta = os.path.join(out, "suelta.jpg")
    Image.fromarray(np.full((64, 64, 3), 200, np.uint8)).save(suelta)
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(carpeta), QUrl.fromLocalFile(suelta)])
    ev = QDropEvent(QPoint(20, 20), Qt.CopyAction, m, Qt.LeftButton, Qt.NoModifier)
    ed.material.dropEvent(ev)
    paths_mat = [os.path.normcase(os.path.abspath(ed.material.item(i).data(Qt.UserRole)))
                 for i in range(ed.material.count())]
    for f in (os.path.join(carpeta, "m0.png"), os.path.join(carpeta, "sub", "m1.png"), suelta):
        assert os.path.normcase(os.path.abspath(f)) in paths_mat, (f, paths_mat)
    assert ed.material.acceptDrops()
    print("✓ soltar en «Material» imágenes y carpetas del PC: entran (también en «Medios»)")
    # ⇱ mejorar resolución ×2 de una imagen pequeña (con el modelo de verdad si ya está bajado)
    from editoria.ai import upscale as U
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos", "modelos", "upscale",
                        "EDSR_x2.pb")
    if not os.path.exists(U.model_path("edsr", 2)) and os.path.exists(real):   # (el que ya bajaste, sin internet)
        os.makedirs(os.path.dirname(U.model_path("edsr", 2)), exist_ok=True)
        __import__("shutil").copyfile(real, U.model_path("edsr", 2))
    if os.path.exists(U.model_path("edsr", 2)):
        chica = os.path.join(out, "chica.png")
        Image.fromarray((np.random.default_rng(3).random((60, 80, 3)) * 255).astype(np.uint8)).save(chica)
        ed.add_image(chica, "Chica")
        lay = ed.cur()
        s0 = lay["scale"]
        ed.upscale_image(2)
        t0 = time.time()
        while ed.job is not None and time.time() - t0 < 120:
            pump(app, 0.1)
        lay = ed.cur()
        from PySide6.QtGui import QImage
        q = QImage(lay["path"])
        assert (q.width(), q.height()) == (160, 120) and abs(lay["scale"] - s0 / 2) < 1e-4, (q.size(), lay["scale"])
        ed.undo()
        assert ed.cur()["path"] == chica
        print("✓ ⇱ Mejorar ×2: la imagen tiene el doble de píxeles y se ve igual de grande; Ctrl+Z lo deshace")
    else:
        print("· (sin el modelo de mejorar resolución bajado: se omite esa parte)")
    # Ctrl+C / Ctrl+V: copiar y pegar lo elegido (desde el lienzo o desde la lista de capas)
    from PySide6.QtGui import QKeySequence, QShortcut
    keys = {(s_.key().toString(), s_.parent()) for s_ in ed.findChildren(QShortcut)}
    for w in (ed.canvas, ed.layers):
        assert (QKeySequence(QKeySequence.Copy).toString(), w) in keys and             (QKeySequence(QKeySequence.Paste).toString(), w) in keys
    src = next(l for l in ed.doc["layers"] if l["kind"] == "image")
    ed.canvas.sel = src["id"]
    src["outline"]["on"] = True
    n = len(ed.doc["layers"])
    assert ed.copy_layer() and ed.paste() and ed.paste()
    a, b = ed.doc["layers"][-2], ed.doc["layers"][-1]
    assert len(ed.doc["layers"]) == n + 2 and a["path"] == src["path"] and a["outline"]["on"]
    assert (a["x"], b["x"]) == (src["x"] + 30, src["x"] + 60) and len({src["id"], a["id"], b["id"]}) == 3
    assert ed.canvas.sel == b["id"]
    ed.undo()
    assert len(ed.doc["layers"]) == n + 1
    from PySide6.QtWidgets import QApplication as _QA
    from PySide6.QtGui import QImage as _QI
    q = _QI(90, 60, _QI.Format_ARGB32)
    q.fill(Qt.blue)
    _QA.clipboard().setImage(q)                                  # una imagen copiada en otro programa
    assert ed.paste() and len(ed.doc["layers"]) == n + 2
    from PySide6.QtTest import QTest
    ed.canvas.sel = src["id"]
    win.activateWindow()                                         # (los atajos van a la ventana activa, como al usarla)
    ed.canvas.setFocus()
    pump(app, 0.1)
    _QA.clipboard().clear()
    n2 = len(ed.doc["layers"])
    QTest.keyClick(ed.canvas, Qt.Key_C, Qt.ControlModifier)
    QTest.keyClick(ed.canvas, Qt.Key_V, Qt.ControlModifier)
    pump(app, 0.1)
    assert len(ed.doc["layers"]) == n2 + 1, "las teclas Ctrl+C y Ctrl+V del lienzo (sin chocar con las del editor)"
    print("✓ Ctrl+C / Ctrl+V: copia lo elegido con sus efectos y lo pega encima (cada pegado, un poco más allá)")
    # ⚡ efectos con barrita + número, y rápidos aunque la imagen sea enorme y se vea pequeña
    import cv2
    from editoria.core import thumbnail as T
    from editoria.ui.thumbnail_editor import _SliderNum
    big = np.zeros((2000, 4200, 4), np.uint8)
    cv2.circle(big, (1000, 1000), 900, (40, 40, 40, 255), 120)
    cv2.putText(big, "LOGO", (1500, 1150), cv2.FONT_HERSHEY_SIMPLEX, 20, (30, 30, 30, 255), 70)
    logo = os.path.join(out, "logo.png")
    Image.fromarray(big).save(logo)
    ed.add_image(logo, "Logo")
    lay = ed.cur()
    lay["scale"] = 0.17
    for k_, v_ in (("outline", dict(on=True, width=2)), ("glow", dict(on=True, radius=19)),
                   ("shadow", dict(on=True, blur=18))):
        lay[k_].update(v_)
    ed.commit("Efectos")
    ed._fill_props()
    sliders = [w for w in ed.props.findChildren(_SliderNum)]
    assert len(sliders) >= 8, len(sliders)                  # grosor, difuminado, X, Y, opacidades, radio…
    radio = next(s_ for s_ in sliders if s_.slider.maximum() == 120)
    radio.slider.setValue(30)
    assert ed.cur()["glow"]["radius"] == 19, "mientras se arrastra, aún no se aplica"
    pump(app, 0.3)
    assert ed.cur()["glow"]["radius"] == 30 and radio.num.value() == 30
    radio.num.setValue(25)                                  # escribir el número también vale
    pump(app, 0.3)
    assert ed.cur()["glow"]["radius"] == 25 and radio.slider.value() == 25
    T._cache.clear()
    t0 = time.time()
    img = T.render_layer(ed.cur())[0]
    ms = (time.time() - t0) * 1000
    assert T.image_k(img) < 1 and ms < 1500, (T.image_k(img), ms)
    q = T.layer_transform(ed.cur(), img).mapRect(__import__("PySide6.QtCore", fromlist=["QRectF"]).QRectF(
        (img.width() - T.render_layer(ed.cur())[1]) / 2, 0, T.render_layer(ed.cur())[1], 1))
    assert abs(q.width() - 4200 * 0.17) < 6, q.width()      # se ve del mismo tamaño que sin reducir
    print(f"✓ ⚡ efectos con barrita + número (se aplican al parar); logo de 4200 px a ×0.17: {ms:.0f} ms")
    # 🪄 Combinar con lo de abajo: los «ojos» toman la luz y el tono de la «cara»; sale como capa nueva
    import cv2
    h_, w_ = ed.doc["h"], ed.doc["w"]
    x_ = np.linspace(1.0, 0.45, w_)[None, :, None]
    cara = np.clip(np.array([200, 150, 120])[None, None, :] * x_, 0, 255).astype(np.uint8).repeat(h_, axis=0)
    p_cara = os.path.join(out, "cara_fondo.png")
    Image.fromarray(cara).save(p_cara)
    ojos = np.zeros((h_, w_, 4), np.uint8)
    for cx in (int(w_ * 0.3), int(w_ * 0.7)):
        cv2.circle(ojos, (cx, h_ // 2), 90, (235, 235, 235, 255), -1)
    p_ojos = os.path.join(out, "ojos.png")
    Image.fromarray(ojos).save(p_ojos)
    ed.delete_all()
    ed.add_image(p_cara, "Cara", fill=True)
    ed.add_image(p_ojos, "Ojos")
    ed.cur().update(scale=1.0, x=w_ / 2, y=h_ / 2)
    ed.commit("Colocar")
    n = len(ed.doc["layers"])
    ed._comb_strength = 0.8
    assert ed.combine_layer("integrar")
    new_l = ed.cur()
    assert len(ed.doc["layers"]) == n + 1 and new_l["name"].endswith("(combinada)")
    assert not ed.doc["layers"][-2]["visible"], "la original queda oculta debajo"
    comb = T.qimage_to_rgba(__import__("PySide6.QtGui", fromlist=["QImage"]).QImage(new_l["path"]))
    yc = comb.shape[0] // 2
    izq, der = comb[yc, comb.shape[1] // 6, :3].astype(int), comb[yc, comb.shape[1] * 5 // 6, :3].astype(int)
    assert izq.sum() > der.sum() + 40, (izq, der)           # el ojo de la sombra, más oscuro
    assert izq[0] > izq[2] + 8, izq                          # y con el tono cálido de la piel
    ed.undo()
    assert len(ed.doc["layers"]) == n and ed.doc["layers"][-1]["visible"]
    assert ed.combine_layer("fundir")
    ed.undo()
    ed.canvas.sel = ed.doc["layers"][0]["id"]
    assert not ed.combine_layer("integrar") and "nada debajo" in ed.statusBar().currentMessage()
    print("✓ 🪄 Combinar: los ojos toman la luz y el tono de la cara (capa nueva, la original oculta); Fundir también")
    # 🔍 zoom con Ctrl + rueda (donde está el ratón) y ▦ guías
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    cv_ = ed.canvas
    cv_.set_zoom(1.0)
    k1 = cv_.transform().m11()
    anchor = QPointF(cv_.viewport().width() * 0.3, cv_.viewport().height() * 0.4)
    before = cv_.mapToScene(anchor.toPoint())
    ev = QWheelEvent(anchor, cv_.viewport().mapToGlobal(anchor), QPoint(0, 0), QPoint(0, 240), Qt.NoButton,
                     Qt.ControlModifier, Qt.NoScrollPhase, False)
    cv_.wheelEvent(ev)
    assert cv_.zoom > 1.3 and cv_.transform().m11() > k1 * 1.3, cv_.zoom
    after = cv_.mapToScene(anchor.toPoint())
    assert abs(after.x() - before.x()) < 6 and abs(after.y() - before.y()) < 6, (before, after)
    assert ed.act_zoom_fit.text() == f"{round(cv_.zoom * 100)} %"
    cv_.set_zoom(0.4)                                       # alejar: se ve lo que se sale del encuadre
    assert cv_.transform().m11() < k1 * 0.5
    ed.act_zoom_fit.trigger()
    assert abs(cv_.zoom - 1.0) < 1e-6 and abs(cv_.transform().m11() - k1) < 1e-6
    labels = [ed.guides_combo.itemText(i) for i in range(ed.guides_combo.count())]
    assert labels == ["▦ Sin guías", "▦ Centro", "▦ Tercios", "▦ Cuartos", "▦ Lo que tapa YouTube"], labels
    ed.guides_combo.setCurrentIndex(2)
    assert cv_.guides == "tercios"
    pix = cv_.viewport().grab().toImage()
    x3 = cv_.mapFromScene(QPointF(ed.doc["w"] / 3, ed.doc["h"] / 2))
    col = pix.pixelColor(x3.x(), x3.y())
    near = [pix.pixelColor(x3.x() + dx, x3.y()) for dx in (-1, 0, 1)]
    assert any(c.blue() > 150 and c.red() < 160 for c in near), [c.name() for c in near]
    ed.guides_combo.setCurrentIndex(4)
    assert cv_.guides == "youtube"
    ed.guides_combo.setCurrentIndex(0)
    print("✓ 🔍 Ctrl + rueda acerca/aleja donde está el ratón (− 100 % + en la barra); ▦ guías: centro, tercios…")
    # 🎨 el selector de color: sobre la ventana (no hereda el fondo rojo del botón) y en español
    from PySide6.QtWidgets import QColorDialog, QLabel
    from editoria.ui.thumbnail_editor import _ColorButton
    btn = _ColorButton("#940000")
    ed.props_lay.addWidget(btn)
    seen = {}
    real = QColorDialog.getColor

    def fake(initial, parent=None, title="", opts=QColorDialog.ColorDialogOption(0)):
        seen["parent"] = parent
        dlg = QColorDialog(initial, parent)
        dlg.setOptions(opts | QColorDialog.ColorDialogOption.DontUseNativeDialog)
        img = dlg.grab().toImage()
        seen["fondo"] = img.pixelColor(img.width() // 2, img.height() - 6)
        seen["textos"] = [lb.text() for lb in dlg.findChildren(QLabel)]
        dlg.deleteLater()
        return QColor("#00ff00")
    from PySide6.QtGui import QColor
    QColorDialog.getColor = staticmethod(fake)
    try:
        got = []
        btn.changed.connect(got.append)
        btn.click()
    finally:
        QColorDialog.getColor = real
    assert seen["parent"] is btn.window() and seen["parent"] is not btn
    f = seen["fondo"]
    assert not (f.red() > 100 and f.green() < 40), f.name()
    assert any("básicos" in t for t in seen["textos"]), seen["textos"]
    assert got == ["#00ff00"]
    print(f"✓ 🎨 el selector de color ya no sale rojo (fondo {f.name()}) y está en español")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    main(out_)
    print("TODO OK")
