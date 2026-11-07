"""
Prueba del «🖥 Visor en la segunda pantalla» (sin ventanas: QT_QPA_PLATFORM=offscreen):
- la ventana sin bordes usa LA MISMA escena que el visor (no decodifica otra vez);
- con una sola pantalla se usa la principal;
- Esc la cierra (y avisa una sola vez); Espacio llama a reproducir / pausar;
- no llama a activateWindow (lo parchea y cuenta).
Ejecutar:  .venv/Scripts/python.exe tests/test_second_screen.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def key(app, widget, k):
    ev = QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)
    app.processEvents()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui import second_screen as SS
    from editoria.ui.preview import Canvas

    canvas = Canvas()
    canvas.resize(800, 450)
    canvas.show()
    app.processEvents()

    # sin segunda pantalla (offscreen tiene una): se usa la principal
    scr, has_second = SS.pantalla_secundaria()
    assert scr is QGuiApplication.primaryScreen() and not has_second, (scr, has_second)
    print("✓ una sola pantalla: el visor secundario va a la principal")

    toggles = []
    win = SS.SecondScreenWindow(canvas, lambda: toggles.append(1), "F11")
    closed = []
    win.closed.connect(lambda: closed.append(1))

    activations = []
    SS.SecondScreenWindow.activateWindow = lambda self: activations.append(1)   # parche: si se llamara, se cuenta

    win.abrir()
    app.processEvents()
    assert win.isVisible(), "la ventana debería estar abierta"
    assert win.windowFlags() & Qt.FramelessWindowHint, "sin bordes"
    assert win.testAttribute(Qt.WA_ShowWithoutActivating), "no debe activarse al abrirse"
    assert win.view.scene() is canvas.scene(), "debe usar LA MISMA escena que el visor"
    assert win.geometry() == scr.geometry(), (win.geometry(), scr.geometry())
    assert win.view.viewport().property("clean_view"), "sin guías ni asas"
    print("✓ ventana sin bordes a pantalla completa, con la misma escena que el visor")

    # la vista ajusta el cuadro del video con proporción (16:9 en una ventana 16:9 = sin barras raras)
    win.view.refit()
    r = win.view.mapFromScene(canvas.frame.sceneBoundingRect()).boundingRect()
    assert r.width() > 0 and r.height() > 0, r
    print("✓ el cuadro del video se ve dentro de la vista")

    key(app, win, Qt.Key_Space)
    assert toggles == [1], toggles
    print("✓ Espacio = reproducir / pausar")

    key(app, win, Qt.Key_Escape)
    app.processEvents()
    assert not win.isVisible(), "Esc debe cerrarla"
    assert closed == [1], closed
    print("✓ Esc la cierra (una sola señal de cierre)")

    assert not activations, f"se llamó a activateWindow {len(activations)} veces"
    print("✓ nunca llama a activateWindow (no roba el foco del editor)")

    canvas.close()
    app.processEvents()
    print("TODO OK")


if __name__ == "__main__":
    main()
