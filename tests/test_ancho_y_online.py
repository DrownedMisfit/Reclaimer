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
    pv._ajustar_cabecera(420)
    assert not pv.lbl_calidad.isVisibleTo(pv.header)
    pv._ajustando_cab = True                     # (sin que la cabecera se recalcule con su ancho real, estrecho aquí)
    pv._ajustar_cabecera(1900)
    assert pv.lbl_calidad.isVisibleTo(pv.header)
    pv._ajustando_cab = False
    assert pv.header.minimumSizeHint().width() < 700, pv.header.minimumSizeHint().width()
    print("✓ cabecera del visor: lo que no cabe se esconde y vuelve al ensancharse")
    # (21/11: «Silencios» y «Huecos» viven en la barra del transporte —preview._ajustar_rapidos—: con nombre si caben;
    #  si no, solo su icono con el nombre en el tooltip; y si ni así, bajan a una segunda fila con su nombre. Nunca
    #  se esconden ni se cortan)
    sil = pv.quick["silence"]
    largo = sil.property("nombre_corto") or "Silencios"
    vistos = set()
    # (sin pantalla el visor mide de verdad ~400 px: al pasar de dos filas a una, la barra cambia de alto y su Resize
    #  volvía a decidir con ese ancho real; mientras se prueba cada ancho, ese aviso no se escucha)
    pv.transport.removeEventFilter(pv)
    for ancho in (1900, 700, 420, 1900):
        pv._rapidos_cortos = None                # (decide otra vez, sin el margen que evita el vaivén)
        pv._ajustar_rapidos(ancho)
        app.processEvents()
        assert sil.isVisibleTo(pv.transport), ("Silencios se esconde", ancho)
        if sil.text() == "":
            assert largo in sil.toolTip() and not sil.icon().isNull(), ("solo icono sin su nombre en el tooltip",
                                                                         ancho, sil.toolTip())
            vistos.add("icono")
        else:
            assert sil.text() == largo, (ancho, sil.text())
            vistos.add("dos filas" if pv._dos_filas else "nombre")
    assert sil.text() == largo and not pv._dos_filas, (
        "a 1900 px, en una fila y con su nombre", sil.text(), pv._dos_filas, vistos,
        pv.transport_row.sizeHint().width(), pv.btn_mode.sizeHint().width(), pv.duration_label.sizeHint().width(),
        pv.task_chip.isVisibleTo(pv.transport) and pv.task_chip.sizeHint().width())
    assert vistos - {"nombre"}, ("a 420 px o 700 px se compacta (icono o segunda fila)", vistos)
    pv.transport.installEventFilter(pv)
    print(f"✓ «Silencios» en el transporte: {', '.join(sorted(vistos))}; nunca escondido ni cortado")

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
        assert win.clips.isVisible(), "🔑 (Dijiste… · 🌐 Internet) a la vista, en su panel «Palabras clave»"
        print("✓ 🌐 IA → Inicio: busca videos en internet y abre 🔑 → 🌐 Internet con los resultados")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
