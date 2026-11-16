"""
Arreglos de la caza de bugs (interfaz):
1) El nombre del proyecto solo se edita con un clic: al arrancar y al salir de 🎬 Escenas el foco va a la línea de
   tiempo (antes S escribía «s» en el nombre: «sssssProyecto sin título»).
2) ⌨ Atajos: los secundarios (S para dividir) cuentan al buscar choques; poner S en otra orden se la quita solo a
   «Dividir» (Ctrl+B se queda); ↺ devuelve también la S; Ctrl+Z está reservado.
3) Miniatura (vertical): «Moverlo a la zona libre» deja el texto fuera del recorte del feed de Shorts.
4) «Guardar movimiento» limpia la barra invertida del nombre.
5) Reinicio de proyecto sale antes de 🎬 Escenas.
Ejecutar:  .venv/Scripts/python.exe tests/test_bugs_interfaz.py <carpeta_salida>
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.activateWindow()
    for _ in range(5):
        app.processEvents()
    tit = win.preview.title_label
    nombre0 = win.ctrl.project.name

    # 1) el nombre no se queda con el foco
    assert tit.focusPolicy() == Qt.ClickFocus
    tit.setFocus(Qt.TabFocusReason)
    app.processEvents()
    assert not tit.hasFocus(), "por Tab (o por el foco automático) no se entra al nombre"
    win.go_page("scenes")
    app.processEvents()
    win.go_page("edit")
    for _ in range(5):
        app.processEvents()
    assert not tit.hasFocus(), "al salir de Escenas el nombre no se queda con el foco"
    QTest.keyClick(win.timeline, Qt.Key_S)
    app.processEvents()
    assert win.ctrl.project.name == nombre0 and "s" not in tit.text()[:1], tit.text()
    tit.setFocus(Qt.MouseFocusReason)
    app.processEvents()
    assert tit.hasFocus(), "con un clic sí se escribe"
    tit.clearFocus()
    app.processEvents()
    win.preview.title_label.editar()                  # (F2: «Cambiar el nombre del proyecto»)
    app.processEvents()
    assert tit.hasFocus() and tit.selectedText() == tit.text(), "F2 deja el nombre listo para escribir"
    tit.clearFocus()
    assert any(a.shortcut() == QKeySequence("F2") for a, _d in win.shortcut_actions.values())
    print("✓ el nombre del proyecto solo se edita con un clic o con F2; S no escribe en él")

    # 2) atajos secundarios
    from editoria.ui.shortcuts_dialog import ShortcutsDialog
    acts = win.shortcut_actions
    k_div = next(k for k, (a, _d) in acts.items() if QKeySequence("S") in a.shortcuts())
    otra = next(k for k, (a, _d) in acts.items() if a.shortcut().isEmpty() and k != k_div)
    dlg = ShortcutsDialog(acts, win)
    a_div = acts[k_div][0]
    primero = a_div.shortcut()
    assert "S" in dlg.editors[k_div].toolTip(), "los de más se ven en el tooltip"
    assert dlg.set_shortcut(otra, QKeySequence("S"), ask=False)
    assert QKeySequence("S") not in a_div.shortcuts() and a_div.shortcut() == primero, a_div.shortcuts()
    assert acts[otra][0].shortcut() == QKeySequence("S")
    from editoria.ui.shortcuts_dialog import extra_permitido
    assert not extra_permitido(k_div, "S"), "la S quitada no vuelve a «Dividir» al reiniciar"
    dlg._reset(otra)
    dlg._reset(k_div)
    assert QKeySequence("S") in a_div.shortcuts(), "↺ devuelve también la S"
    assert not dlg.set_shortcut(otra, QKeySequence("Ctrl+Z"), ask=False), "Ctrl+Z es de Deshacer"
    dlg.close()
    print("✓ atajos: la S de «Dividir» cuenta, se quita sola, vuelve con ↺; Ctrl+Z reservado")

    # 3) zona libre en Shorts respeta el recorte del feed
    from editoria.core import thumb_review as R
    from editoria.core import thumbnail as T
    doc = T.new_doc("short")
    lay = T.text_layer(doc, "HOLA")
    doc["layers"].append(lay)
    lay["y"] = 30
    avisos = R.analyze(doc)
    fix = next(a["fix"] for a in avisos if a.get("fix") and a["fix"].get("action") == "avoid_zones")
    doc2 = R.apply_fix(doc, fix)
    textos = [a["text"] for a in R.analyze(doc2)]
    assert not any("se corta en el feed" in t or "zona tapada" in t for t in textos), textos
    print("✓ Shorts: «Moverlo a la zona libre» lo deja fuera del recorte del feed")

    # 4) barra invertida en el nombre de un movimiento
    from editoria.core import scenes
    ruta = scenes.guardar_movimiento({"tipo": "accion", "anim": "propia", "dur": 1.0,
                                      "claves": [{"t": 0, "x": 0, "y": 0}]}, "Salto" + chr(92) + "giro")
    assert os.path.isfile(ruta) and chr(92) not in os.path.basename(ruta), ruta
    print("✓ «Guardar movimiento» limpia la barra invertida")

    # 5) reinicio con Escenas abierta: primero se sale
    win.go_page("scenes")
    app.processEvents()
    pg = win._scenes_widget
    pg.sucia = False
    assert win._antes_de_vaciar()
    app.processEvents()
    assert getattr(win, "_scenes_widget", None) is None, "Escenas se cierra antes de vaciar"
    print("✓ reinicio de proyecto: sale antes de 🎬 Escenas")

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
