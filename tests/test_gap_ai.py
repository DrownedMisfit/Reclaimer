"""
Prueba del clic derecho en un HUECO → ✨ IA: las sugerencias usan lo que DICES durante ese hueco (no donde esté el
cabezal); «💡 Ver sugerencias» / «⚡ Rellenar» piden el B-roll solo para ese tramo y esa pista; «🔎 Buscar en
Medios» busca esa frase.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_gap_ai.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


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
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, tl = win.ctrl, win.timeline
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 0.0)
        ctrl.add_media([mid], v1.id, 8.0)
        # lo que «digo»: una frase en el hueco (3–8 s) y otra donde está el cabezal (0 s)
        tl.phrase_at = lambda t: ("el jefe maestro llega a la base", 3.5) if 3 <= t < 8 else ("otra cosa", 0.0)
        tl.playhead = 0.5
        g = ctrl.gap_at(v1.id, 5.0)
        assert g and abs(g[0] - 3.0) < 1e-3 and abs(g[1] - 8.0) < 1e-3
        menu = QMenu()
        tl._add_gap_ai(menu, v1, g)
        texts = [a.text() for a in menu.actions()]
        assert any("Ver sugerencias" in t for t in texts) and any("Rellenar este hueco" in t for t in texts)
        assert any("jefe maestro" in t for t in texts) and not any("otra cosa" in t for t in texts), texts
        print("✓ el menú del hueco usa lo que dices EN el hueco: " + next(t for t in texts if "Buscar" in t))

        calls = []
        win.ai_panel.propose = lambda rng=None, apply=False: calls.append((rng, apply))
        next(a for a in menu.actions() if "Rellenar" in a.text()).trigger()
        next(a for a in menu.actions() if "Ver sugerencias" in a.text()).trigger()
        assert calls == [((3.0, 8.0), True), ((3.0, 8.0), False)], calls
        assert win.ai_panel.track.currentData() == v1.id
        sought = []
        tl.moments_requested.disconnect()
        tl.moments_requested.connect(lambda t, a: sought.append((t, a)))
        next(a for a in menu.actions() if "Buscar en Medios" in a.text()).trigger()
        assert sought == [("el jefe maestro llega a la base", 3.0)], sought
        print("✓ «⚡ Rellenar» y «💡 Ver sugerencias» piden el B-roll solo para ese hueco y esa pista; "
              "«🔎 Buscar en Medios» busca esa frase")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
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
