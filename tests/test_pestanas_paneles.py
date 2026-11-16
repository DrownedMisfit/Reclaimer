"""
☰ Pestañas de los paneles sin deslizar:
  · si no caben con su nombre, se quedan con su icono (el nombre sale al pasar el ratón) y caben enteras;
  · si hay sitio, vuelven a su nombre;
  · arriba a la derecha, «☰ Paneles» lista todos (por lado) y abre el que eliges.
Ejecutar:  .venv/Scripts/python.exe tests/test_pestanas_paneles.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication, QTabBar  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.reset_layout()
    pump(app, 0.3)
    from PySide6.QtCore import Qt
    win.resizeDocks([win.docks["inspector"]], [440], Qt.Horizontal)   # (el ancho del panel derecho en pantalla)
    pump(app, 2.0)                                   # (incluye el repaso periódico de las pestañas)
    try:
        # (sin ventana la pantalla virtual es pequeña: el panel derecho mide ~120 px, así que deben quedar los iconos)
        for k in ("inspector", "voice", "history"):
            d = win.docks[k]
            assert d.windowTitle() == win.ICONO_PANEL[k], (k, d.windowTitle())
            assert d.toggleViewAction().text() == d.nombre, "el menú «Ventana» sigue con el nombre completo"
        tb = next((x for x in win.findChildren(QTabBar) if x.parent() is win and x.isVisible()
                   and "⚙" in [x.tabText(i) for i in range(x.count())]), None)
        assert tb is not None, "la fila de pestañas del Inspector, con su icono"
        i = [tb.tabText(j) for j in range(tb.count())].index("⚙")
        assert tb.tabToolTip(i) == "Inspector", tb.tabToolTip(i)
        print(f"✓ panel derecho: {tb.count()} pestañas con su icono (caben sin deslizar); el nombre al pasar el ratón")
        win.docks["history"].setFloating(True)
        pump(app, 1.8)
        assert win.docks["history"].windowTitle() == "Historial", "suelto: con su nombre completo"
        win.docks["history"].setFloating(False)
        pump(app, 0.3)
        from PySide6.QtCore import Qt as _Qt
        win.removeDockWidget(win.docks["scopes"])     # solo en su zona (sin fila de pestañas): con su nombre
        win.addDockWidget(_Qt.TopDockWidgetArea, win.docks["scopes"])
        win.docks["scopes"].show()
        pump(app, 1.8)
        assert win.docks["scopes"].windowTitle() == win.docks["scopes"].nombre, win.docks["scopes"].windowTitle()
        print("✓ un panel suelto o solo en su zona recupera su nombre")
        win.grab().save(os.path.join(out, "pestanas.png"))
        win._llenar_menu_paneles()
        acciones = [a.text() for a in win._menu_paneles.actions() if a.text()]
        assert any("Inspector" in a for a in acciones) and any("Limpieza" in a for a in acciones), acciones
        hist = next(a for a in win._menu_paneles.actions() if "Historial" in a.text())
        hist.trigger()
        pump(app, 0.3)
        d = win.docks["history"]
        assert d.isVisible() and not d.visibleRegion().isEmpty(), "«☰ Paneles» → Historial lo pone delante"
        print("✓ «☰ Paneles»: todos los paneles por lado; elegir uno lo pone delante")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
