"""
🖼 Miniatura, texto en el lienzo:
  · escribiendo el texto (tras doble clic en una palabra), pulsar y arrastrar dentro elige las palabras desde donde
    pulsaste hasta donde llegas (también quedan marcadas en el cuadro de texto);
  · con UNA palabra elegida y mal escrita, la barra del texto enseña «✍ ¿correcta?» con las sugerencias y al elegir
    una se corrige (cada estilo sigue en su palabra; Ctrl+Z la devuelve).
Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_arrastre_ortografia.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import spelling as SP
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    try:
        ed = win.open_thumbnail("youtube")
        pump(app, 0.3)
        cv = ed.canvas
        ed.add_text("ESTO ES MLAO", "title")
        lay = ed.cur()
        for k in ("shadow", "outline", "glow"):
            lay[k]["on"] = False
        ed.commit("prep")
        cv.set_zoom(8.0)
        cv.centerOn(lay["x"], lay["y"])
        cv.sel = lay["id"]
        ed._fill_props()
        pump(app, 0.2)

        def centro(i):
            img, cw, ch = cv._render(lay)
            return dict(T.word_quads(lay, img, cw, ch))[i].boundingRect().center()

        def ev(kind, pt, buttons=Qt.LeftButton):
            vp = cv.mapFromScene(pt)
            return QMouseEvent(kind, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), Qt.LeftButton, buttons,
                               Qt.NoModifier)

        def enviar(e):
            QApplication.sendEvent(cv.viewport(), e)
            app.processEvents()

        # 1) doble clic en «ESTO» (modo escribir) y arrastrar hasta «MLAO»
        cv.set_words({0}, lay)
        p0, p2 = centro(0), centro(2)
        enviar(ev(QEvent.MouseButtonPress, p0))
        enviar(ev(QEvent.MouseMove, centro(1)))
        enviar(ev(QEvent.MouseMove, p2))
        enviar(ev(QEvent.MouseButtonRelease, p2, Qt.NoButton))
        assert cv.active_words(lay) == {0, 1, 2}, cv.active_words(lay)
        assert (lay["x"], lay["y"]) == (ed.cur()["x"], ed.cur()["y"]), "arrastrar dentro del texto no lo mueve"
        print("✓ escribiendo el texto: arrastrar dentro elige las palabras hasta donde llegas (no lo mueve)")

        # 2) ortografía: «MLAO» mal escrita → «✍ ¿…?»
        SP.preload("mixto")
        t0 = time.time()
        while not SP.ready("mixto") and time.time() - t0 < 20:
            pump(app, 0.1)
        assert SP.ready("mixto"), "diccionarios cargados"
        cv.set_words({2}, lay)
        ed.text_bar._sig = None
        ed.text_bar.update_pos()
        pump(app, 0.3)
        tb = ed.text_bar
        assert tb.btn_orto.isVisibleTo(tb), "palabra mal escrita: «✍ ¿…?» a la vista"
        tb._llenar_menu_orto()                         # (las sugerencias se buscan al abrir el menú)
        sug = [a.text() for a in tb._menu_orto.actions() if a.isEnabled() and not a.isSeparator()]
        print(f"✓ «MLAO» mal escrita: {tb.btn_orto.text()} · sugerencias: {sug[:4]}")
        primera = next(a for a in tb._menu_orto.actions() if a.isEnabled() and not a.isSeparator())
        palabra = primera.text()
        primera.trigger()
        pump(app, 0.2)
        assert ed.cur()["text"] == "ESTO ES " + palabra, ed.cur()["text"]
        print(f"✓ elegir la sugerencia corrige el texto: «{ed.cur()['text']}»")
        cv.set_words({0}, lay)
        tb._sig = None
        tb.update_pos()
        assert not tb.btn_orto.isVisibleTo(tb), "una palabra bien escrita no enseña el botón"

        # 3) panel derecho: cada grupo tras su título; Texto abierto, Posición/Efectos cerrados; se recuerda
        from PySide6.QtCore import QSettings
        from editoria.ui.tabs import Section
        for k in ("Posición", "Efectos", "Texto"):
            QSettings("EditorIA", "EditorIA").remove(f"secciones/miniatura/{k}")
        cv.set_words(set(), lay)
        ed._fill_props()
        pump(app, 0.2)
        secs = {sec.head.text(): sec for sec in ed.props.findChildren(Section)}
        assert {"Posición", "Efectos", "Texto"} <= set(secs), sorted(secs)
        assert secs["Texto"].head.isChecked() and not secs["Posición"].head.isChecked() and             not secs["Efectos"].head.isChecked()
        secs["Efectos"].head.setChecked(True)          # la abres…
        ed._fill_props()                               # …eliges otra cosa y vuelves: sigue abierta
        pump(app, 0.2)
        secs = {sec.head.text(): sec for sec in ed.props.findChildren(Section)}
        assert secs["Efectos"].head.isChecked(), "lo que usas se queda abierto"
        print("✓ panel derecho: cada grupo tras su título (clic = abrir); lo que dejas abierto, abierto se queda")
        from editoria.ui.thumbnail_editor import _Muestra
        ed.remember_color("outline", "#FF0000", "#00FF00")
        ed._fill_props()
        pump(app, 0.2)
        ms = ed.props.findChildren(_Muestra)
        assert ms and all(m.width() >= 24 and m.height() >= 24 for m in ms), [(m.width(), m.height()) for m in ms]
        print("✓ los colores usados son cuadros de 24 px (antes rayitas imposibles de pulsar)")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        ed_ = getattr(win, "_thumb_editor", None)
        if ed_ is not None:
            ed_.close()                                # (guarda la miniatura: luego el proyecto, como limpio)
            pump(app, 0.2)
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
