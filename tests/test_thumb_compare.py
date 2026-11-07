"""
⚖ Comparar A/B del taller de miniaturas:
  · guardar A y B (cada una una copia de la miniatura en ese momento);
  · «Ver A y B lado a lado» solo está activo si hay A y B;
  · la ventana muestra las dos versiones (grandes y en móvil) con contenido distinto;
  · «Quedarme con A/B» pone esa versión en la miniatura y se deshace con Ctrl+Z.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_compare.py <carpeta>
"""
from __future__ import annotations

import json
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

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def igual_doc(doc, snap: str) -> bool:
    return json.loads(json.dumps(doc)) == json.loads(snap)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui.thumb_compare import CompareDialog
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)

    # 0) sin A ni B: «Ver lado a lado» desactivado
    assert not ed.act_ab_side.isEnabled()
    menu = ed.ab_btn.menu()
    guardar_a = next(a for a in menu.actions() if "Guardar como A" in a.text())
    guardar_a.trigger()
    assert "A guardada" in ed.statusBar().currentMessage(), ed.statusBar().currentMessage()
    snap_a = json.dumps(ed.doc)
    assert not ed.act_ab_side.isEnabled(), "con solo A no se puede comparar"
    print("✓ guardar A (desde el menú); con solo A, «Ver lado a lado» está desactivado")

    # 1) cambiar algo y guardar B
    ed.add_text("HOLA MUNDO", "title")
    t = ed.cur()
    t.update(x=640.0, y=200.0)
    ed.commit("texto")
    ed.ab_save("B")
    assert "B guardada" in ed.statusBar().currentMessage(), ed.statusBar().currentMessage()
    snap_b = json.dumps(ed.doc)
    assert snap_a != snap_b
    assert ed.act_ab_side.isEnabled(), "con A y B sí se puede comparar"
    print("✓ cambiar algo (añadir un texto) y guardar B; ahora «Ver lado a lado» está activo")

    # 2) la ventana de comparación: dos versiones con contenido distinto (sin mostrarla)
    dlg = CompareDialog(ed, snap_a, snap_b, ed._title(), ed.use_ab)
    for oscuro_idx in (0, 1):                       # tema oscuro, luego claro
        dlg._tema.setCurrentIndex(oscuro_idx)
        grande_a = dlg._pics["A"][0].pixmap().toImage()
        grande_b = dlg._pics["B"][0].pixmap().toImage()
        movil_a = dlg._pics["A"][1].pixmap().toImage()
        movil_b = dlg._pics["B"][1].pixmap().toImage()
        for im in (grande_a, grande_b, movil_a, movil_b):
            assert not im.isNull() and im.width() > 0
        assert grande_a != grande_b, "A y B deben verse distintas (grande)"
        assert movil_a != movil_b, "A y B deben verse distintas (móvil)"
    assert dlg._botones["A"].text() == "✓ Quedarme con A" and dlg._botones["B"].text() == "✓ Quedarme con B"
    print("✓ la ventana tiene A y B grandes y en móvil, con contenido distinto (oscuro y claro)")

    # 3) «Quedarme con A» pone el doc de A; Ctrl+Z vuelve a B
    dlg._botones["A"].click()
    assert dlg.result() == QDialog.Accepted, "la ventana se cierra al elegir"
    assert igual_doc(ed.doc, snap_a), "el doc debe ser el de A"
    ed.undo()
    assert igual_doc(ed.doc, snap_b), "Ctrl+Z (undo) debe volver al doc de B"
    print("✓ «Quedarme con A» pone el diseño de A; Ctrl+Z vuelve al de B")

    # 3b) «Quedarme con B» desde la ventana (con el doc de A puesto)
    ed.redo()
    assert igual_doc(ed.doc, snap_a)
    dlg2 = CompareDialog(ed, snap_a, snap_b, ed._title(), ed.use_ab)
    dlg2._botones["B"].click()
    assert igual_doc(ed.doc, snap_b), "«Quedarme con B» pone el doc de B"
    print("✓ «Quedarme con B» pone el diseño de B")

    # 3b) A y B se guardan con el proyecto (no se pierden al cerrar)
    from editoria.core.model import Project
    d = win.ctrl.project.to_dict()
    p2 = Project.from_dict(__import__("json").loads(__import__("json").dumps(d)))
    assert set(p2.thumbnails["ab"]["youtube"]) == {"A", "B"}, p2.thumbnails.get("ab")
    print("✓ A y B se guardan con el proyecto (al abrirlo siguen ahí)")
    # 4) Borrar A y B: se desactiva todo
    ed.ab_clear()
    assert not ed.act_ab_side.isEnabled() and not ed.act_ab_clear.isEnabled()
    print("✓ «Borrar A y B» deja la comparación desactivada")

    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
