"""
Prueba de Ventana → Tamaño de letra: «Paneles, menús y ventanas» (todo menos la línea de tiempo) y
«Global» (todo); se aplica al momento, Cancelar lo deja como estaba y Aceptar lo recuerda.
Ejecutar:  .venv/Scripts/python.exe tests/test_fonts.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    saved = {k: st.value(k) for k in ("letra/interfaz", "letra/global")}
    try:
        for k in saved:
            st.remove(k)
        from editoria.ui.theme import apply_dark_theme
        apply_dark_theme(app)
        from editoria.ui.main_window import MainWindow
        from editoria.ui.font_dialog import FontSizeDialog
        win = MainWindow()
        win.show()
        pump(app, 0.2)
        assert abs(app.font().pointSizeF() - 9) < 0.01 and win.timeline.ui_k == 1.0
        h0 = win.timeline.track_h(0)
        d = FontSizeDialog(win)
        d.show()
        d.sliders["ui"].setValue(150)
        pump(app, 0.4)
        assert abs(app.font().pointSizeF() - 13.5) < 0.05, app.font().pointSizeF()
        assert win.timeline.ui_k == 1.0, "«Paneles» no debe tocar la línea de tiempo"
        d.sliders["global"].setValue(120)
        pump(app, 0.4)
        assert abs(app.font().pointSizeF() - 9 * 1.5 * 1.2) < 0.05
        assert abs(win.timeline.ui_k - 1.2) < 1e-6 and win.timeline.HEADER_W == 204
        assert win.timeline.track_h(0) > h0
        assert win.findChild(QWidget, "pagebar").height() >= 46 * 1.8 - 1
        print("✓ «Paneles» agranda todo menos la línea de tiempo; «Global» agranda todo (también la línea)")
        win.grab().save(os.path.join(out, "letra_grande.png"))
        d.reject()
        pump(app, 0.3)
        assert abs(app.font().pointSizeF() - 9) < 0.01 and win.timeline.ui_k == 1.0
        print("✓ Cancelar lo deja como estaba")
        d = FontSizeDialog(win)
        d.sliders["global"].setValue(140)
        pump(app, 0.3)
        d.accept()
        assert int(st.value("letra/global")) == 140
        win2 = MainWindow()
        assert abs(win2.timeline.ui_k - 1.4) < 1e-6
        print("✓ Aceptar lo recuerda (al abrir de nuevo sigue igual)")
        for w in (win, win2):
            w.analyzer.shutdown()
            w.ctrl.undo_stack.setClean()
            w.ctrl._media_dirty = False
            w.close()
    finally:
        for k, v in saved.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
