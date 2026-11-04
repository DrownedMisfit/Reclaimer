"""
Prueba de ✍ «Texto en pantalla» en la pestaña «Texto» (el usuario no encontraba dónde escribir el texto y lo quiere
ahí):
  · sin texto seleccionado: lo explica y ofrece «T Añadir texto aquí»;
  · «Añadir texto aquí»: texto nuevo en el cabezal, seleccionado y listo para escribir;
  · lo que escribes llega al texto del video (y el Inspector enseña lo mismo); Ctrl+Z lo deshace;
  · al elegir otro texto, enseña el suyo; con un clip que no es texto, se esconde el cuadro.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_text_writer.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.4)
    w, ctrl = win.text_writer, win.ctrl
    assert w.parentWidget() is win.transcript or w.parent() is win.transcript, "en la pestaña «Texto»"
    win.timeline.set_selection([])
    pump(app, 0.1)
    assert not w.edit.isVisible() and w.b_add.isVisible() and "Selecciona un texto" in w.info.text()
    print("✓ sin texto seleccionado: lo explica y ofrece «T Añadir texto aquí»")
    win.engine.seek(1.0)
    w.b_add.click()
    pump(app, 0.2)
    cid = w.clip_id
    assert cid and ctrl.project.clips[cid].text is not None, (cid, w.info.text())
    assert abs(ctrl.project.clips[cid].start - win.engine.time) < 0.05, (ctrl.project.clips[cid].start, win.engine.time)
    assert w.edit.isVisible() and win.timeline.selected == {cid}
    print("✓ «Añadir texto aquí»: texto nuevo en el cabezal, seleccionado y listo para escribir")
    idx = ctrl.undo_stack.index()
    w.edit.setPlainText("Rumor del día")
    pump(app, 0.6)
    assert ctrl.project.clips[cid].text["content"] == "Rumor del día", ctrl.project.clips[cid].text
    assert win.inspector.text_edit.toPlainText() == "Rumor del día", win.inspector.text_edit.toPlainText()
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert ctrl.undo_stack.index() == idx and ctrl.project.clips[cid].text["content"] != "Rumor del día"
    assert w.edit.toPlainText() == ctrl.project.clips[cid].text["content"]
    print("✓ lo que escribes llega al texto del video (el Inspector enseña lo mismo); Ctrl+Z lo deshace")
    ctrl.undo_stack.redo()
    win.engine.seek(8.0)
    w.b_add.click()
    pump(app, 0.2)
    cid2 = w.clip_id
    w.edit.setPlainText("Segundo")
    pump(app, 0.6)
    win.timeline.set_selection([cid])
    pump(app, 0.2)
    assert w.clip_id == cid and w.edit.toPlainText() == "Rumor del día", w.edit.toPlainText()
    assert ctrl.project.clips[cid2].text["content"] == "Segundo"
    win.timeline.set_selection([cid, cid2])
    pump(app, 0.1)
    assert not w.edit.isVisible() and "varios" in w.info.text()
    print("✓ al elegir otro texto enseña el suyo; con varios, pide elegir uno")
    win.right_tabs.setCurrentWidget(win.transcript) if hasattr(win, "right_tabs") else None
    win.timeline.set_selection([cid])
    pump(app, 0.3)
    w.grab().save(os.path.join(out, "texto_en_pantalla.png"))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
