"""
Prueba de que la línea de tiempo SIEMPRE se abre con todas sus pistas a la vista (sin desplazarse) y sin comerse el
visor: sin distribución guardada, con una guardada aplastada y con una guardada demasiado alta.
Usa una carpeta de datos TEMPORAL; deja tu distribución como estaba.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline_layout.py <carpeta_salida>
"""
from __future__ import annotations

import os
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
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402


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
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    def check(label, prepare):
        prepare()
        w = MainWindow()
        w.resize(1920, 1040)
        w.show()
        pump(app, 0.8)
        n = len(w.ctrl.project.tracks)
        sa = w.timeline.parentWidget().parentWidget()
        view_h = sa.viewport().height() if isinstance(sa, QScrollArea) else w.timeline.height()
        need = w.timeline.track_y(n)
        th = w.docks["timeline"].height()
        assert view_h >= need - 2, f"{label}: no se ven todas las pistas ({view_h} < {need})"
        assert th <= w.height() * 0.5 + 6, f"{label}: se come el visor ({th} de {w.height()})"
        w.grab().save(os.path.join(out, f"{label}.png"))
        print(f"✓ {label}: línea de tiempo {th}px de {w.height()}, las {n} pistas a la vista")
        st.setValue("ventana/paneles", w.saveState(3))
        w.ctrl.undo_stack.setClean()
        w.ctrl._media_dirty = False
        w.close()
        pump(app, 0.2)
        return w

    def squash(px):
        def prep():
            w0 = MainWindow()
            w0.resize(1920, 1040)
            w0.show()
            pump(app, 0.4)
            w0.resizeDocks([w0.docks["timeline"]], [px], Qt.Vertical)
            pump(app, 0.2)
            st.setValue("ventana/paneles", w0.saveState(3))
            w0.ctrl.undo_stack.setClean()
            w0.ctrl._media_dirty = False
            w0.close()
            pump(app, 0.2)
        return prep

    check("sin_distribucion_guardada", lambda: st.remove("ventana/paneles"))
    check("guardada_aplastada", squash(110))
    check("guardada_demasiado_alta", squash(800))

    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    st.remove("guia/colocada")
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
