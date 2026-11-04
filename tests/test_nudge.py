"""
Prueba de «¿Qué me falta?»: si falta un paso, se resalta en naranja dónde hacerlo (línea de tiempo, botón ◈ de
Medios, «➕ Añadir efecto», el nombre en la ventana del ejemplo…), y de que la línea de tiempo no se abre
aplastada aunque la distribución guardada lo esté.
Usa una carpeta de datos TEMPORAL; deja tu distribución como estaba.
Ejecutar:  .venv/Scripts/python.exe tests/test_nudge.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.ui.guide import highlighter_of
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Distribución guardada con la línea de tiempo aplastada → al abrir se agranda
    w0 = MainWindow()
    w0.resize(1600, 1000)
    w0.show()
    pump(app, 0.3)
    w0.resizeDocks([w0.docks["timeline"]], [120], Qt.Vertical)
    pump(app, 0.2)
    st.setValue("ventana/paneles", w0.saveState(3))
    st.setValue("geometry", w0.saveGeometry())
    w0.ctrl.undo_stack.setClean()
    w0.ctrl._media_dirty = False
    w0.hide()
    w0.deleteLater()
    pump(app, 0.2)
    win = MainWindow()
    win.show()
    pump(app, 0.5)
    th = win.docks["timeline"].height()
    assert th >= win.height() * 0.25, f"la línea de tiempo sigue aplastada ({th}px de {win.height()})"
    print(f"✓ la línea de tiempo no se abre aplastada ({th}px de {win.height()}) aunque se guardara así")

    hl = lambda: highlighter_of(win)  # noqa: E731

    # 1) Desenfoque sin clip seleccionado → resalta la línea de tiempo
    win.show_panel(win.effects)
    win.effects.add_region("rect")
    pump(app, 0.1)
    assert hl() is not None and hl().target is win.timeline and hl().isVisible()
    # 2) Proponer efectos sin favoritos → resalta «➕ Añadir efecto»
    win.effects.memory = []
    win.effects.propose_effects()
    assert hl().target is win.effects.b_mem_add, hl().target
    # 3) Ctrl+C sin selección (mensaje de la barra de estado) → resalta la línea de tiempo
    hl().clear()
    win._copy(False)
    assert hl().target is win.timeline
    # 4) Buscar en mis archivos sin analizar → abre Medios y resalta el botón ◈
    win.show_panel(win.moments)
    win.moments.source.setCurrentIndex(win.moments.source.findData("local"))
    win.moments.query.setText("jefe maestro")
    win.moments.search_text()
    pump(app, 0.1)
    assert hl().target is win.library.btn_analyze and win.library.btn_analyze.isVisible(), hl().target
    win.grab().save(os.path.join(out, "falta_analizar.png"))
    print("✓ resalta lo que falta: la línea de tiempo (sin selección), «➕ Añadir efecto», y el botón ◈ de "
          "Medios (abriendo esa pestaña) cuando hay que analizar antes")
    # 5) Ventana del ejemplo sin nombre → resalta el campo «¿Qué es?»
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    ids = win.ctrl.import_paths([vid])
    while win.ctrl.analyzing:
        pump(app, 0.05)
    from editoria.ui.example_dialog import ExampleDialog
    dlg = ExampleDialog(win.ctrl, ids[0], 1.0, 0.0, 3.5, "", win)
    dlg.show()
    pump(app, 0.2)
    dlg._done(True)
    dh = highlighter_of(dlg)
    assert dh is not None and dh.target is dlg.name, "resalta el campo del nombre"
    dlg.reject()
    print("✓ en la ventana del ejemplo, si falta el nombre, se resalta «¿Qué es?»")

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    st.remove("guia/colocada")
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
