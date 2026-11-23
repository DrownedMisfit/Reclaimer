"""
◧ PRUEBA corta de la fase 6 (23/11): arrastrar el borde de un lado = todo el alto.
  · izquierda: arrastrar su borde de abajo hasta pasar la mitad de la línea de tiempo → línea del acento mientras se
    arrastra y, al soltar, a todo el alto (= «A todo el alto»); sin pasar el umbral, nada;
  · derecha: lo mismo (ventana/derecha_alto);
  · la tira de abajo de un lado a todo el alto, arrastrada hacia arriba hasta la línea de tiempo → vuelve.
Ejecutar:  .venv/Scripts/python.exe tests/test_borde_alto.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_borde_{os.getpid()}.json"
with open(os.path.join(_RAIZ, _CFG), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"dpr": 1}]}')
__import__("atexit").register(lambda: os.path.exists(os.path.join(_RAIZ, _CFG)) and os.remove(os.path.join(_RAIZ, _CFG)))
os.chdir(_RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None


def _vigilante(segundos: float = 240.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_borde_alto")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("ventana/biblioteca_alto", "false")
    st.setValue("ventana/derecha_alto", "false")
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1900, 1040)
    win.show()
    pump(app, 1.2)
    v = win.borde_alto
    assert v is not None
    tl = win.docks["timeline"]
    assert win.corner(Qt.BottomLeftCorner) == Qt.BottomDockWidgetArea

    def separador(lado):
        r, g = v._lado(lado), tl.geometry()
        assert r is not None, lado
        return QPoint(r.center().x(), int(round((r.bottom() + g.top()) / 2)))

    def arrastrar(p0, y1, captura=None):
        QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, p0)
        QTest.mouseMove(win, QPoint(p0.x(), (p0.y() + y1) // 2))
        QTest.mouseMove(win, QPoint(p0.x(), y1))
        pump(app, 0.05)
        vista = v.linea.isVisible()
        if captura:
            win.grab().save(os.path.join(out, captura))
        QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(p0.x(), y1))
        pump(app, 0.4)
        return vista

    # 1) izquierda, sin pasar el umbral: nada
    g = tl.geometry()
    p = separador("izq")
    vista = arrastrar(p, g.top() + int(g.height() * 0.25))
    assert not vista and not win.biblioteca_alto(), "sin pasar la mitad de la línea de tiempo no cambia nada"
    # 2) izquierda, pasando el umbral: línea del acento y a todo el alto
    g = tl.geometry()
    p = separador("izq")
    vista = arrastrar(p, g.top() + int(g.height() * 0.8), "izq_arrastrando.png")
    assert vista, "la línea del acento mientras arrastras"
    assert win.biblioteca_alto() and win.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea
    assert win._btn_alto.isChecked(), "es lo mismo que «A todo el alto»"
    assert not v.linea.isVisible()
    win.grab().save(os.path.join(out, "izq_todo_el_alto.png"))
    print("✓ izquierda: sin pasar la mitad de la línea de tiempo, nada; pasándola, línea del acento y a todo el alto")

    # 3) derecha (con la izquierda a todo el alto no cabe en 1900 px: lo dice y no cambia nada)
    g = tl.geometry()
    p = separador("der")
    arrastrar(p, g.top() + int(g.height() * 0.8))
    assert not win.derecha_alto() and win.corner(Qt.BottomRightCorner) == Qt.BottomDockWidgetArea
    win.set_biblioteca_alto(False)
    pump(app, 0.5)
    g = tl.geometry()
    p = separador("der")
    assert arrastrar(p, g.top() + int(g.height() * 0.8), "der_arrastrando.png")
    assert win.derecha_alto() and win.corner(Qt.BottomRightCorner) == Qt.RightDockWidgetArea, \
        (win.derecha_alto(), win.corner(Qt.BottomRightCorner))
    print("✓ derecha: igual (ventana/derecha_alto); si con la izquierda no cabe, lo dice y no cambia nada")

    # 4) la tira de abajo de la derecha, hacia arriba hasta la línea de tiempo → vuelve
    v.colocar_tiras()
    tira = v.tiras["der"]
    assert tira.isVisible(), "la tira de abajo del lado a todo el alto"
    c = QPoint(tira.width() // 2, tira.height() // 2)
    QTest.mousePress(tira, Qt.LeftButton, Qt.NoModifier, c)
    arriba = tira.mapFrom(win, QPoint(tira.geometry().center().x(), tl.geometry().top() - 30))
    QTest.mouseMove(tira, QPoint(c.x(), (c.y() + arriba.y()) // 2))
    QTest.mouseMove(tira, arriba)
    pump(app, 0.05)
    assert v.linea.isVisible()
    QTest.mouseRelease(tira, Qt.LeftButton, Qt.NoModifier, arriba)
    pump(app, 0.4)
    assert not win.derecha_alto() and win.corner(Qt.BottomRightCorner) == Qt.BottomDockWidgetArea
    print("✓ la tira de abajo, arrastrada hacia arriba hasta la línea de tiempo: el lado vuelve")
    win.set_derecha_alto(False)
    st.setValue("ventana/biblioteca_alto", "false")
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
