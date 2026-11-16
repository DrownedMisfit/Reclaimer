"""
📱 Miniatura de un Short: el feed de inicio la enseña más ancha que 9:16 (recorta arriba y abajo).
  · guía «▦ Recorte del feed de Shorts (recomendado)», puesta de entrada en las miniaturas verticales;
  · 👁 Vista previa: la tarjeta del feed recortada (≈ 208×285);
  · ⚕ Analizar avisa si un texto cae en lo que se recorta.
Ejecutar:  .venv/Scripts/python.exe tests/test_miniatura_feed.py <carpeta_salida>
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

from PySide6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumb_review as R
    from editoria.ui.main_window import MainWindow
    QSettings("EditorIA", "EditorIA").remove("miniatura/guias")
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = None
    try:
        ed = win.open_thumbnail("short")
        pump(app, 0.3)
        assert ed.doc["format"] == "short"
        assert ed.guides_combo.currentData() == "feed" and ed.canvas.guides == "feed", ed.guides_combo.currentData()
        print("✓ miniatura vertical: la guía «Recorte del feed de Shorts» viene puesta (recomendada)")
        y0, y1 = R.feed_ventana(ed.doc)
        assert 0 < y0 < y1 < ed.doc["h"] and abs(ed.doc["w"] / (y1 - y0) - R.FEED_SHORTS) < 0.01
        im = R.simulate_feed(ed.doc, 208)
        assert abs(im.width() / im.height() - R.FEED_SHORTS) < 0.02, (im.width(), im.height())
        print(f"✓ vista previa del feed: {im.width()}×{im.height()} (recorta arriba y abajo)")
        ed.add_text("EDITS Y SHORTS", "title")
        lay = ed.cur()
        lay["y"] = y0 * 0.4                                # arriba del todo: se corta en el feed
        ed.commit("prep")
        avisos = [f["text"] for f in R.analyze(ed.doc) if f["level"] == "warn"]
        assert any("feed de Shorts" in a for a in avisos), avisos
        lay["y"] = ed.doc["h"] / 2
        ed.commit("prep2")
        avisos = [f["text"] for f in R.analyze(ed.doc) if f["level"] == "warn"]
        assert not any("feed de Shorts" in a for a in avisos), avisos
        print("✓ ⚕ Analizar avisa si un texto cae en lo que recorta el feed (y no si está en la zona clara)")
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        if ed is not None:
            ed.close()
            pump(app, 0.2)
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
