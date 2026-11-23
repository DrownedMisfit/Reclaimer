"""
🖼 Ctrl+V pega una imagen copiada fuera (internet, otra app) en el cabezal y en Medios; si lo último que copiaste
   fueron clips de Reclaimer, Ctrl+V pega esos clips.
Ejecutar:  .venv/Scripts/python.exe tests/test_pegar_imagen.py <carpeta_salida>
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
from PySide6.QtWidgets import QApplication  # noqa: E402

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_IMAGE
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    for _ in range(10):
        app.processEvents()
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor("#c03030"))
    QApplication.clipboard().setImage(img)
    app.processEvents()
    win.engine.seek(2.0) if hasattr(win.engine, "seek") else None
    antes = len(win.ctrl.project.clips)
    win._paste()
    app.processEvents()
    imgs = [m for m in win.ctrl.project.media.values() if m.kind == KIND_IMAGE]
    assert imgs and os.path.isfile(imgs[0].path) and "Imágenes pegadas" in imgs[0].path, imgs
    assert len(win.ctrl.project.clips) == antes + 1, (antes, len(win.ctrl.project.clips))
    c = next(c for c in win.ctrl.project.clips.values() if c.media_id == imgs[0].id)
    print(f"✓ imagen copiada → Medios ({os.path.basename(imgs[0].path)}) y en la línea a los {c.start:.2f} s")
    win.ctrl.copy_clips([c.id])
    win._copia_externa = False                      # (lo que hace Ctrl+C de clips)
    win._paste()
    app.processEvents()
    assert len([m for m in win.ctrl.project.media.values() if m.kind == KIND_IMAGE]) == 1, "volvió a pegar la imagen"
    assert len(win.ctrl.project.clips) == antes + 2, len(win.ctrl.project.clips)
    print("✓ tras copiar clips de Reclaimer, Ctrl+V pega esos clips (no la imagen)")
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
