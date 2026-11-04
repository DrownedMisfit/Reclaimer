"""
Prueba de ▦ Guías del visor: tercios, centro, zona segura (Shorts/TikTok en vertical) y borde del encuadre;
se recuerdan y no salen al exportar.
Ejecutar:  .venv/Scripts/python.exe tests/test_guides.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
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
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "visor/guias")}
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        st.remove("visor/guias")
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        win.ctrl.set_project_format("short")
        pump(app, 0.3)
        pv = win.preview
        g = pv.canvas.guides
        assert not g.isVisible() and pv.btn_guides.text().startswith("▦")
        for key in ("thirds", "safe", "frame"):
            pv._guide_acts[key].setChecked(True)
        pump(app, 0.2)
        assert g.isVisible() and g.modes == {"thirds", "safe", "frame"}
        assert set(str(st.value("visor/guias")).split(",")) == {"thirds", "safe", "frame"}
        assert (g.W, g.H) == (1080, 1920)
        pv.canvas.grab().save(os.path.join(out, "guias.png"))
        print("✓ ▦ Guías: tercios + zona segura de Shorts/TikTok + borde, en vertical; se recuerdan")
        # Como el menú de Resolve: una relación de aspecto a la vez (redes / cine), áreas de seguridad y reglas
        ks = [k for k in pv._guide_acts if k.startswith("a:") and k != "a:"]
        pv._guide_acts[ks[0]].setChecked(True)          # 1:1
        pv._guide_acts[ks[3]].setChecked(True)          # 1.91:1 → quita el 1:1
        for key in ("action", "title", "rulers"):
            pv._guide_acts[key].setChecked(True)
        pump(app, 0.2)
        asp = [m for m in g.modes if m.startswith("a:")]
        assert asp == [ks[3]] and not pv._guide_acts[ks[0]].isChecked(), g.modes
        assert {"action", "title", "rulers"} <= g.modes
        pv.canvas.grab().save(os.path.join(out, "guias_resolve.png"))
        pv._guide_acts[ks[3]].setChecked(False)          # sin ninguna = «Predet.»
        assert pv._guide_acts["a:"].isChecked() and not any(m.startswith("a:") for m in g.modes)
        print("✓ guías como Resolve: una relación de aspecto a la vez (1:1, 4:5, 9:16, 1.91, 16:9, cine…), "
              "acción/título y reglas")
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
