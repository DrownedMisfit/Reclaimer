"""
1) ↔ La ventana nunca pide más ancho que la pantalla: con muchos paneles a los lados, sus mínimos bajan, y la cabecera
   del visor deja los botones solo con su icono cuando no caben (antes pedía ~1740 px y Qt cortaba la derecha).
2) 🌐 Buscar videos en internet para el material, a la vista en IA ✨ → Inicio: abre 🔑 → 🌐 Internet y busca.
Ejecutar:  .venv/Scripts/python.exe tests/test_ancho_y_online.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    for _ in range(20):
        app.processEvents()

    # 1) ancho: todos los paneles posibles a la vista, en columnas a izquierda y derecha
    for k, d in win.docks.items():
        if k in ("timeline", "guide"):
            continue
        d.setFloating(False)
        d.show()
    izq = [d for k, d in win.docks.items() if win.dockWidgetArea(d) == Qt.LeftDockWidgetArea][:2]
    der = [d for k, d in win.docks.items() if win.dockWidgetArea(d) == Qt.RightDockWidgetArea][:2]
    if len(izq) == 2:
        win.splitDockWidget(izq[0], izq[1], Qt.Horizontal)   # (dos columnas, como al arrastrar la pestaña IA)
    if len(der) == 2:
        win.splitDockWidget(der[0], der[1], Qt.Horizontal)
    for _ in range(10):
        app.processEvents()
    win._ajustar_paneles()
    for _ in range(10):
        app.processEvents()
    pant = win.screen().availableGeometry().width()
    minimo = win.minimumSizeHint().width()
    assert minimo <= max(pant - 16, 1200), (minimo, pant)
    print(f"✓ con paneles en columnas la ventana pide {minimo} px (pantalla {pant} px): no se corta la derecha")
    pv = win.preview
    largo = pv.quick["silence"].property("texto_completo") or pv.quick["silence"].text()
    pv._ajustar_cabecera(420)
    assert pv.quick["silence"].text() == "✂" and largo in pv.quick["silence"].toolTip(), pv.quick["silence"].text()
    assert not pv.lbl_calidad.isVisibleTo(pv.header)
    pv._ajustando_cab = True                     # (sin que la cabecera se recalcule con su ancho real, estrecho aquí)
    pv._ajustar_cabecera(1900)
    assert pv.quick["silence"].text() == largo and pv.lbl_calidad.isVisibleTo(pv.header)
    pv._ajustando_cab = False
    assert pv.header.minimumSizeHint().width() < 700, pv.header.minimumSizeHint().width()
    print("✓ cabecera del visor: solo iconos cuando no cabe (el nombre en el tooltip) y vuelve al ensancharse")

    # 2) material de internet a la vista en IA
    from editoria.ui import clips_panel
    ai = win.ai_panel
    if not getattr(clips_panel, "HAY_INTERNET", False):
        assert not ai.online.isVisibleTo(ai)
        print("✓ sin la parte local no sale el buscador de internet")
    else:
        assert not ai.online.isHidden()
        buscado = []
        win.clips._buscar = lambda term, mods, kind: buscado.append(term)     # (sin internet en la prueba)
        assert ai.buscar_online("perro corriendo en la playa")
        app.processEvents()
        assert win.clips.pestanas.currentIndex() == 1 and buscado == ["perro corriendo en la playa"]
        assert win.docks["clips"].isVisible()
        print("✓ 🌐 IA → Inicio: busca videos en internet y abre 🔑 → 🌐 Internet con los resultados")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
