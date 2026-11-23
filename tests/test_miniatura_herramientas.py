"""
Prueba corta: en la pestaña Miniatura, «🎨 Mi estilo» y «⚖ Comparar A y B» se abren como PESTAÑAS del panel de
herramientas de la columna derecha (el mismo anfitrión que el editor, ui/herramientas.py), sin ventana modal; las
propiedades quedan debajo, plegables; «Quedarme con A» pone la A y cierra su pestaña. Sin ventanas visibles.
Capturas en la carpeta de salida. Ejecutar:  .venv/Scripts/python.exe tests/test_miniatura_herramientas.py <carpeta>
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(ROOT, "_pruebas_tmp"), exist_ok=True)
with open(os.path.join(ROOT, "_pruebas_tmp", "pantalla_1080.json"), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"logicalBaseDpi": 96, "dpr": 1}]}')
os.chdir(ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=_pruebas_tmp/pantalla_1080.json"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def pump(app, s=0.2):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp", "miniatura_h"))
    os.makedirs(out, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1900, 1040)
    win.show()
    pump(app, 0.8)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.4)
    h = ed.herramientas
    check(h is not win.herramientas and h.donde == "columna" and not h.visible and ed._props_area.isVisible()
          and not ed._props_cab.isVisible(), "sin herramienta, las propiedades ocupan la columna derecha")

    # ---- 🎨 Mi estilo
    dlg = ed.open_style()
    pump(app, 0.3)
    check(h.abierta("mi_estilo") and dlg is not None and not dlg.isWindow() and ed._columna.isAncestorOf(dlg)
          and QApplication.activeModalWidget() is None, "Mi estilo: pestaña de la columna derecha, sin modal")
    t = h._ts["mi_estilo"].pestana
    check(t.text() and t.toolButtonStyle() != 0 and t.width() >= t.sizeHint().width(),
          f"pestaña con icono y nombre, sin cortar ({t.text()})")
    check(ed._props_cab.isVisible() and "Propiedades" in ed._props_cab.text(),
          f"debajo, las propiedades como sección plegable ({ed._props_cab.text()})")
    check(ed._props_area.isVisible(), "Mi estilo cabe: las propiedades siguen abiertas debajo (sin hueco)")
    check(not any(b.isVisible() and b.text() in ("Cerrar", "Cancelar") for b in dlg.findChildren(type(dlg.btn))),
          "sin «Cerrar» que solo cierre (está la ✕)")
    check(dlg.width() <= ed._columna.width() and dlg.minimumSizeHint().width() <= ed._columna.width(),
          f"nada más ancho que la columna ({dlg.minimumSizeHint().width()} ≤ {ed._columna.width()})")
    win.grab().save(os.path.join(out, "mi_estilo.png"))

    # ---- ⚖ Comparar A y B
    ed.ab_save("A")
    snap_a = json.dumps(ed.doc)
    ed.add_text("HOLA MUNDO", "title")
    ed.commit("texto")
    ed.ab_save("B")
    cmp_ = ed.ab_compare()
    pump(app, 0.4)
    check(h.abierta("comparar_ab") and cmp_ is not None and not cmp_.isWindow() and ed._columna.isAncestorOf(cmp_)
          and QApplication.activeModalWidget() is None, "Comparar A y B: pestaña de la columna derecha, sin modal")
    check(not ed._props_area.isVisible(), "Comparar no cabe con ellas: las propiedades se pliegan debajo")
    ga, gb = cmp_._pics["A"][0], cmp_._pics["B"][0]
    check(ga.geometry().bottom() < gb.geometry().top() and ga.pixmap().width() <= ed._columna.width(),
          f"A y B una debajo de otra, a lo ancho de la columna ({ga.pixmap().width()} px)")
    win.grab().save(os.path.join(out, "comparar.png"))
    cmp_._botones["A"].click()
    pump(app, 0.3)
    check(json.loads(json.dumps(ed.doc)) == json.loads(snap_a) and not h.abierta("comparar_ab"),
          "«Quedarme con A» pone la A y cierra su pestaña")
    print("TODO BIEN")


if __name__ == "__main__":
    main()
