"""
♻ «Restaurar este video»: un clip cuyo archivo se borró por error (a la Papelera) vuelve con el clic derecho;
   en Medios se quita con ⌫ (Supr ya no quita nada ahí).
Ejecutar:  .venv/Scripts/python.exe tests/test_restaurar_papelera.py <carpeta_salida>
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
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.No)   # (sin diálogos: no quita nada)

import time  # noqa: E402

from PySide6.QtCore import QFile, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ruta = os.path.join(_TMP, "video borrado por error.mp4")
    with open(ruta, "wb") as f:
        f.write(os.urandom(4096))
    p = Project.new()
    v1 = next(t for t in p.tracks if t.kind == "video")
    p.media["v"] = MediaItem(id="v", path=ruta, kind=KIND_VIDEO, name=os.path.basename(ruta), duration=5.0,
                             probed=True)
    p.clips["c"] = Clip(id="c", media_id="v", track_id=v1.id, start=0.0, source_in=0.0, duration=5.0)
    win.ctrl.set_project(p) if hasattr(win.ctrl, "set_project") else setattr(win.ctrl, "project", p)
    app.processEvents()
    assert QFile.moveToTrash(ruta) and not os.path.exists(ruta)
    win.ctrl.missing.add("v")
    from PySide6.QtCore import QPoint
    menu = win.timeline.build_clip_menu(p.clips["c"], win.timeline.mapToGlobal(QPoint(40, 40)))
    primera = next(a for a in menu.actions() if not a.isSeparator())
    assert primera.text() == "Restaurar este video", primera.text()
    primera.trigger()
    t0 = time.time()
    while ("v" in win.ctrl.missing or not os.path.exists(ruta)) and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)
    assert os.path.exists(ruta) and "v" not in win.ctrl.missing, (os.path.exists(ruta), win.ctrl.missing)
    print("✓ clic derecho en el clip «NO ENCONTRADO» → «♻ Restaurar este video» lo saca de la Papelera")

    tree = win.library.tree if hasattr(win, "library") else win.media.tree
    pedidos = []
    tree.delete_pressed.connect(lambda: pedidos.append(1))
    win.library._rebuild()
    app.processEvents()
    tree.setFocus()
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    from editoria.ui.library import ROLE_MEDIA
    itr = QTreeWidgetItemIterator(tree)
    while itr.value() is not None:
        if itr.value().data(0, ROLE_MEDIA):
            itr.value().setSelected(True)
            break
        itr += 1
    assert tree.selected_media_ids(), "no hay medio elegido en Medios"
    QTest.keyClick(tree, Qt.Key_Delete)
    assert not pedidos, "Supr no debe quitar de Medios"
    QTest.keyClick(tree, Qt.Key_Backspace)
    assert pedidos, "⌫ debe quitar de Medios"
    print("✓ en Medios: ⌫ quita, Supr ya no")
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
