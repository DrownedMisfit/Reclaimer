"""
Miniatura · palabras sueltas y fluidez:
  · doble clic en una palabra del lienzo la elige; Ctrl + clic añade o quita; un clic normal deja de elegir;
  · marcar palabras en el cuadro de texto las elige en el lienzo;
  · color, tamaño, negrita, contorno, sombra y brillo se aplican SOLO a lo elegido; un Ctrl+Z; ↺ lo devuelve;
  · cada estilo sigue a su palabra al reescribir el texto;
  · cambiar el tamaño (esquina o Alt + rueda) no redibuja la capa en cada movimiento;
  · cambiar una imagen pesada no bloquea: sigue viéndose la última y la nueva llega en segundo plano;
  · la memoria de las capas dibujadas tiene un tope.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_words.py <carpeta>
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
        time.sleep(0.01)


def color_medio(img, poly, T):
    """Color más frecuente de los píxeles opacos dentro de la caja de una palabra (en la imagen de la capa)."""
    rgba = T.qimage_to_rgba(img)
    r = poly.boundingRect()
    a = rgba[int(max(0, r.top())):int(r.bottom()), int(max(0, r.left())):int(r.right())]
    vivos = a[a[..., 3] > 250][..., :3]
    return vivos


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_thumb_words")
    os.makedirs(out, exist_ok=True)
    import faulthandler
    faulthandler.dump_traceback_later(240, exit=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    cv = ed.canvas

    # ------------------------------------------------------------ sin ventana: el modelo
    assert T.word_spans("hola  mundo\nfin") == [(0, 4), (6, 11), (12, 15)]
    assert T.words_in_span("hola mundo fin", 2, 7) == {0, 1}
    st = T.remap_word_styles("muy malo juego", "este muy malo y juego", {"1": {"color": "#FF0000"}})
    assert st == {"2": {"color": "#FF0000"}}, st
    st = T.remap_word_styles("muy malo", "muy pésimo", {"1": {"color": "#FF0000"}})
    assert st == {"1": {"color": "#FF0000"}}, f"corregir una palabra no le quita su estilo: {st}"
    print("✓ cada estilo sigue a su palabra al reescribir")

    ed.add_text("HOLA MUNDO CRUEL", "title")
    lay = ed.cur()
    lay["shadow"]["on"] = False                        # (para leer colores limpios)
    lay["outline"]["on"] = False
    lay["glow"]["on"] = False
    lay["uppercase"] = True
    ed.commit("prep")
    cv.viewport().update()
    pump(app, 0.1)

    def quads():
        img, cw, ch = cv._render(lay)
        return dict(T.word_quads(lay, img, cw, ch))

    def centro(i):
        return quads()[i].boundingRect().center()

    def ev(kind, pt, buttons=Qt.LeftButton, mods=Qt.NoModifier, boton=Qt.LeftButton):
        vp = cv.mapFromScene(pt)
        return QMouseEvent(kind, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), boton, buttons, mods)

    def enviar(e):
        QApplication.sendEvent(cv.viewport(), e)
        app.processEvents()

    def clic(pt, mods=Qt.NoModifier):
        enviar(ev(QEvent.MouseButtonPress, pt, mods=mods))
        enviar(ev(QEvent.MouseButtonRelease, pt, buttons=Qt.NoButton, mods=mods))

    # el lienzo en las pruebas es estrecho: se acerca para que las palabras se distingan bien con el ratón
    cv.set_zoom(8.0)
    cv.centerOn(lay["x"], lay["y"])
    pump(app, 0.1)
    assert len(quads()) == 3
    i_mundo = 1
    pt = centro(i_mundo)
    assert cv.word_at(lay, pt) == i_mundo, "la palabra del medio debería encontrarse con el ratón"

    # ------------------------------------------------------------ elegir en el lienzo
    cv.sel = lay["id"]
    ed._fill_props()
    cv.mouseDoubleClickEvent(ev(QEvent.MouseButtonDblClick, pt))
    app.processEvents()
    assert cv.active_words() == {i_mundo}, cv.active_words()
    box = ed._text_edit
    assert box.textCursor().selectedText() == "MUNDO", repr(box.textCursor().selectedText())
    print("✓ doble clic en una palabra del lienzo: elegida y marcada en el cuadro de texto")

    pasos0 = ed.pos
    ed.text_bar.set_color("#FF0000")
    pump(app, 0.1)
    assert lay["color"] == "#FFFFFF", "el color del texto no debe cambiar"
    assert lay["word_styles"]["1"]["color"] == "#FF0000", lay.get("word_styles")
    assert ed.pos == pasos0 + 1
    assert ed.text_bar.btn_quitar.isVisibleTo(ed.text_bar), "↺ debería verse con palabras elegidas"
    img, cw, ch = T.render_layer(lay)
    pol = {}
    t_inv = T.layer_transform(lay, img).inverted()[0]
    for i, q in T.word_quads(lay, img, cw, ch):
        pol[i] = t_inv.map(q)
    rojo = color_medio(img, pol[1], T)
    blanco = color_medio(img, pol[0], T)
    assert len(rojo) and np.median(rojo, axis=0).tolist() == [255, 0, 0], np.median(rojo, axis=0)
    assert len(blanco) and np.median(blanco, axis=0).tolist() == [255, 255, 255], np.median(blanco, axis=0)
    print("✓ el color se aplica solo a la palabra elegida (se comprueba en los píxeles)")

    # tamaño, negrita, contorno, sombra y brillo
    ed.text_bar.bump_size(1)
    ed.text_bar.set_bold(False)
    ed.text_bar.set_outline_color("#00FF00")
    ed.text_bar.set_shadow_preset("Dura")
    ed.text_bar.set_glow_color("#0000FF")
    pump(app, 0.1)
    own = lay["word_styles"]["1"]
    assert own["size"] == round(int(lay["size"]) * 1.1) and own["weight"] == 400
    assert own["outline"]["on"] and own["outline"]["color"] == "#00FF00"
    assert own["shadow"]["on"] and own["glow"]["on"] and own["glow"]["color"] == "#0000FF"
    assert not lay["outline"]["on"] and not lay["shadow"]["on"] and not lay["glow"]["on"]
    img2, cw2, ch2 = T.render_layer(lay)
    assert img2.width() > cw2, "la sombra propia de la palabra debe tener su margen"
    print("✓ tamaño, negrita, contorno, sombra y brillo: solo en la palabra")

    # el panel enseña la palabra y escribe en ella
    ed._fill_props()
    assert ed.canvas.active_words() == {i_mundo}
    assert ed._word_props(lay)["size"] == own["size"]
    ed._set(lay, "Tamaño", size=222)
    assert lay["word_styles"]["1"]["size"] == 222 and lay["size"] != 222
    print("✓ el panel de la derecha también cambia solo lo elegido")

    # Ctrl + clic añade; otro Ctrl + clic quita
    clic(centro(0), Qt.ControlModifier)
    assert cv.active_words() == {0, 1}, cv.active_words()
    clic(centro(1), Qt.ControlModifier)
    assert cv.active_words() == {0}, cv.active_words()
    print("✓ Ctrl + clic añade y quita palabras")

    # Ctrl + arrastrar: añade las que toca
    p0, p1 = centro(0), centro(2)
    cv.set_words({0}, lay)
    sitio = (lay["x"], lay["y"])
    enviar(ev(QEvent.MouseButtonPress, p0, mods=Qt.ControlModifier))
    for f in np.linspace(0, 1, 40):
        enviar(ev(QEvent.MouseMove, p0 + (p1 - p0) * float(f), mods=Qt.ControlModifier, boton=Qt.NoButton))
    enviar(ev(QEvent.MouseButtonRelease, p1, buttons=Qt.NoButton, mods=Qt.ControlModifier))
    assert cv.active_words() == {0, 1, 2}, cv.active_words()
    assert (lay["x"], lay["y"]) == sitio, "elegir palabras no debe mover el texto"
    print("✓ Ctrl + arrastrar elige las palabras por las que pasa")

    # un clic normal deja de elegir: lo siguiente va a todo el texto
    clic(centro(2))
    assert cv.active_words() == set()
    ed.text_bar.set_color("#FFFF00")
    assert lay["color"] == "#FFFF00" and lay["word_styles"]["1"]["color"] == "#FF0000"
    print("✓ sin palabras elegidas, la barra cambia todo el texto y respeta lo propio de cada palabra")

    # marcar en el cuadro de texto
    ed._fill_props()
    box = ed._text_edit
    cur = box.textCursor()
    cur.setPosition(5)
    cur.setPosition(9, cur.MoveMode.KeepAnchor)
    box.setTextCursor(cur)
    app.processEvents()
    assert cv.active_words() == {1}, cv.active_words()
    print("✓ marcar en el cuadro de texto elige esas palabras en el lienzo")

    # ↺
    ed.text_bar.clear_words()
    pump(app, 0.05)
    assert "1" not in (lay.get("word_styles") or {})
    ed.undo()
    lay = ed.cur()
    assert lay["word_styles"]["1"]["color"] == "#FF0000", "Ctrl+Z vuelve a poner su estilo"
    print("✓ ↺ devuelve la palabra al estilo del texto; Ctrl+Z lo deshace")

    # reescribir conserva el estilo en su palabra
    cv.set_words(set(), panel=False)
    ed._fill_props()
    ed._text_edit.setPlainText("OTRO HOLA MUNDO CRUEL")
    app.processEvents()
    lay = ed.cur()
    assert lay["word_styles"].get("2", {}).get("color") == "#FF0000", lay.get("word_styles")
    print("✓ al añadir una palabra delante, el estilo sigue en «MUNDO»")
    T.render_layer(lay)

    # exportar: mismo dibujo
    pix = T.render(ed.doc)
    assert not pix.isNull()

    # ------------------------------------------------------------ fluidez
    cv.set_zoom(1.0)
    pump(app, 0.1)
    foto = os.path.join(out, "grande.png")
    a = np.zeros((1944, 3456, 4), np.uint8)
    a[..., 0] = 200
    a[200:1700, 500:3000, 3] = 255
    Image.fromarray(a, "RGBA").save(foto, compress_level=1)
    ed.add_image(foto, "Grande")
    img_lay = ed.cur()
    img_lay["scale"] = 0.9
    img_lay["outline"].update(on=True, width=10)
    img_lay["glow"].update(on=True, radius=20)
    img_lay["shadow"].update(on=True, blur=20)
    ed.commit("efectos")
    T._cache.clear()
    t0 = time.perf_counter()
    T.render_layer(img_lay)
    ms = (time.perf_counter() - t0) * 1000
    print(f"  · imagen de 3456×1944 con contorno, brillo y sombra: {ms:.0f} ms (antes ~2000)")
    assert ms < 1500, f"demasiado lento: {ms:.0f} ms"
    cv.viewport().update()
    pump(app, 0.1)

    llamadas = []
    original = T.render_layer

    def espia(l):
        if not T.is_rendered(l):
            llamadas.append(l["id"])
        return original(l)
    T.render_layer = espia
    try:
        for capa in (img_lay, ed.doc["layers"][0]):
            cv.sel = capa["id"]
            cv._render(capa)
            llamadas.clear()
            h = cv._handles(capa)
            c = h["corners"][2]
            cv.viewport().update()
            vp = cv.mapFromScene(c)
            enviar(QMouseEvent(QEvent.MouseButtonPress, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)),
                               Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
            assert cv._drag and cv._drag["mode"] == "scale", cv._drag
            s0 = capa["scale"]
            for j in range(1, 25):
                q = QPoint(vp.x() + j, vp.y() + j)
                enviar(QMouseEvent(QEvent.MouseMove, QPointF(q), QPointF(cv.viewport().mapToGlobal(q)),
                                   Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            assert capa["scale"] != s0
            assert not llamadas, f"no debe redibujar la capa en cada movimiento: {len(llamadas)}"
            enviar(QMouseEvent(QEvent.MouseButtonRelease, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)),
                               Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
            t0 = time.time()
            while (cv._bg_jobs or not T.is_rendered(capa)) and time.time() - t0 < 15:
                pump(app, 0.02)
            cv.viewport().update()
            pump(app, 0.05)
            assert T.is_rendered(capa), "al soltar debe quedar la imagen buena"
        print("✓ arrastrar la esquina no redibuja la capa en cada movimiento (imagen y texto); al soltar, la buena")

        # Alt + rueda
        cv.sel = img_lay["id"]
        cv.viewport().update()
        pump(app, 0.05)
        llamadas.clear()
        for _ in range(12):
            vp = cv.viewport().rect().center()
            QApplication.sendEvent(cv.viewport(), QWheelEvent(
                QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                Qt.AltModifier, Qt.NoScrollPhase, False))
            pump(app, 0.01)
        assert not llamadas, f"Alt + rueda redibujó {len(llamadas)} veces mientras se giraba"
        t0 = time.time()
        while not T.is_rendered(img_lay) and time.time() - t0 < 15:
            pump(app, 0.03)
        assert T.is_rendered(img_lay)
        print("✓ Alt + rueda: al vuelo, y la imagen buena al dejar de girar")

        # cambiar un efecto de una imagen: en segundo plano
        llamadas.clear()
        pump(app, 0.05)
        ed._set(img_lay, "Brillo", **{"glow.radius": 33})
        t0 = time.perf_counter()
        res = cv._render(img_lay)
        ms = (time.perf_counter() - t0) * 1000
        assert img_lay["id"] in cv._bg_jobs, "una imagen pesada se dibuja en segundo plano"
        assert res is not None and ms < 60, f"el dibujo no debe bloquear: {ms:.0f} ms"
        t0 = time.time()
        while cv._bg_jobs and time.time() - t0 < 15:
            pump(app, 0.02)
        pump(app, 0.1)
        assert T.is_rendered(img_lay), "la imagen nueva debería haber llegado"
        print(f"✓ cambiar un efecto de una imagen no bloquea la ventana ({ms:.1f} ms)")
    finally:
        T.render_layer = original

    # tope de memoria
    for i in range(30):
        T._guardar(T._cache, f"x{i}", (type("I", (), {"sizeInBytes": lambda self: 60_000_000})(), 1, 1),
                   lambda v: v[0].sizeInBytes(), T._CACHE_MAX)
    total = sum(v[0].sizeInBytes() for v in T._cache.values())
    assert total <= T._CACHE_MAX, total
    T._cache.clear()
    print(f"✓ la memoria de capas dibujadas tiene tope ({T._CACHE_MAX // 1_000_000} MB)")

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
