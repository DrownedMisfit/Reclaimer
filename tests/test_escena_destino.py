"""
🎬 Escenas → «Enviar a»: la escena puede ir a otra pestaña (Video horizontal, Edits o Vertical). De entrada marca la
pestaña en la que estás; si eliges otra, se cambia a ella, se lleva sus personajes (medios) y se pone en el mismo tiempo.
También: las pestañas se llaman «Video horizontal», «Edits» y «Vertical».
Ejecutar:  .venv/Scripts/python.exe tests/test_escena_destino.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication.instance() or QApplication([])
    from PIL import Image
    from editoria.core import scenes
    from editoria.ui.main_window import MainWindow
    from editoria.ui.workspaces import TABS
    assert [t for _k, t in TABS] == ["🎬  Video horizontal", "🎵  Edits", "📱  Vertical"], TABS
    print("✓ pestañas: «Video horizontal», «Edits» y «Vertical»")
    png = os.path.join(_TMP, "personaje.png")
    Image.new("RGBA", (200, 300), (200, 40, 40, 255)).save(png)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ws, ctrl = win.workspaces, win.ctrl
        ws.switch("youtube")
        pump(app, 0.2)
        mid = ctrl.import_now([png], quiet=True)[0]
        win.go_page("scenes")
        pump(app, 0.3)
        pg = win._scenes_widget
        assert pg.destino.currentData() == "youtube", "de entrada, la pestaña en la que estás"
        pg._añadir_actor(mid)
        a0 = float(pg.escena["a"])
        pg.destino.setCurrentIndex(pg.destino.findData("short"))
        assert pg.aplicar()
        pump(app, 0.4)
        assert ws.current == "short", ws.current
        p = ctrl.project
        assert p.format == "short"
        rutas = {os.path.normcase(m.path) for m in p.media.values()}
        assert os.path.normcase(png) in rutas, "se llevó su personaje a Medios de Vertical"
        clips = [c for c in p.clips.values() if c.note.startswith("🎬")]
        assert clips and abs(min(c.start for c in clips) - a0) < 0.05, (len(clips), a0)
        assert any(scenes for scenes in p.scenes.values()), "la escena está en el proyecto de Vertical"
        print("✓ «Enviar a: 📱 Vertical»: la escena va a esa pestaña, con su personaje y en el mismo tiempo")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
