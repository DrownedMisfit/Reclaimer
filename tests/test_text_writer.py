"""
Prueba de ✍ «Texto en pantalla» en la pestaña «Texto» (el usuario no encontraba dónde escribir el texto y lo quiere
ahí):
  · sin texto seleccionado: lo explica y ofrece «T Añadir texto aquí»;
  · «Añadir texto aquí»: texto nuevo en el cabezal, seleccionado y listo para escribir;
  · lo que escribes llega al texto del video (y el Inspector enseña lo mismo); Ctrl+Z lo deshace;
  · al elegir otro texto, enseña el suyo; con un clip que no es texto, se esconde el cuadro;
  · 🗑 Quitar (el elegido; sin selección, el del cabezal; apagado si no hay ninguno), Supr con el cuadro VACÍO quita
    el texto (con letras, borra letras) y Esc devuelve el foco a la línea de tiempo; todo con un Ctrl+Z;
  · visor: ↕ Alt+rueda sube/baja la vista (siempre ≥ 20 % del video a la vista; «Ajustar» la centra);
  · _acoplar_timeline_si_tapa: una línea de tiempo suelta encima de la ventana (o fuera de toda pantalla) vuelve abajo.
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
    win.go_page("transcripcion")              # (agrupación 20/11: lleva a «Voz y texto» → 2 · Transcripción)
    pump(app, 0.4)
    assert win.transcript.isVisible() and win.voz_texto.abierta() == "transcripcion",         "en «Voz y texto» → Transcripción se ve el panel del texto"
    win.timeline.set_selection([])
    pump(app, 0.1)
    # (20/11, auditoría: «Texto en pantalla» viene PLEGADO —está entero en Inspector → Texto— y se abre al escribir)
    assert not w.seccion.is_open(), "plegado por defecto"
    w.seccion.set_open(True, save=False)
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
    assert not w.edit.isVisible() and "varios" in w.info.text().lower(), w.info.text()
    print("✓ al elegir otro texto enseña el suyo; con varios, pide elegir uno")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    win.activateWindow()
    pump(app, 0.1)
    n0 = len(ctrl.project.clips)
    win.timeline.set_selection([cid2])
    pump(app, 0.4)
    assert w.b_quitar.isVisible() and w.b_quitar.isEnabled(), "🗑 a la vista y activo con un texto elegido"
    QTest.mouseClick(w.b_quitar, Qt.LeftButton)
    pump(app, 0.3)
    assert cid2 not in ctrl.project.clips and len(ctrl.project.clips) == n0 - 1
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert cid2 in ctrl.project.clips and ctrl.project.clips[cid2].text["content"] == "Segundo"
    win.timeline.set_selection([])
    c2 = ctrl.project.clips[cid2]
    win.engine.seek((c2.start + c2.end) / 2)
    pump(app, 0.5)
    assert w.b_quitar.isEnabled(), "sin selección, con el cabezal sobre un texto: 🗑 activo"
    QTest.mouseClick(w.b_quitar, Qt.LeftButton)
    pump(app, 0.3)
    assert cid2 not in ctrl.project.clips, "🗑 sin selección quita el del cabezal"
    ctrl.undo_stack.undo()
    win.timeline.set_selection([])
    win.engine.seek(ctrl.project.duration() + 5.0)  # (al final: ningún texto debajo del cabezal)
    pump(app, 0.5)
    assert not w.b_quitar.isEnabled(), "sin texto en el cabezal ni elegido: 🗑 apagado"
    print("✓ 🗑 Quitar: el elegido o el del cabezal (apagado si no hay); Ctrl+Z lo devuelve")
    win.engine.seek(ctrl.project.duration())
    w.b_add.click()
    pump(app, 0.2)
    cid3 = w.clip_id
    assert w.edit.hasFocus() or app.focusWidget() is w.edit, app.focusWidget()
    QTest.keyClick(w.edit, Qt.Key_Delete)          # («Texto» seleccionado: Supr borra las letras, no el clip)
    pump(app, 0.6)
    assert cid3 in ctrl.project.clips and not w.edit.toPlainText(), "1.er Supr: borra las letras"
    QTest.keyClick(w.edit, Qt.Key_Delete)          # (cuadro vacío: Supr quita el texto)
    pump(app, 0.3)
    assert cid3 not in ctrl.project.clips, "2.º Supr con el cuadro vacío: quita el texto"
    assert win.timeline.hasFocus() or app.focusWidget() is win.timeline, app.focusWidget()
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert cid3 in ctrl.project.clips, "Ctrl+Z lo devuelve"
    win.timeline.set_selection([cid])
    pump(app, 0.2)
    w.edit.setFocus()
    pump(app, 0.1)
    QTest.keyClick(w.edit, Qt.Key_Escape)
    pump(app, 0.1)
    assert cid in ctrl.project.clips and (win.timeline.hasFocus() or app.focusWidget() is win.timeline),         app.focusWidget()
    print("✓ Supr con letras borra letras; con el cuadro vacío quita el texto; Esc = foco a la línea de tiempo")
    # ↕ Alt+rueda en el visor
    win.go_page("edit")
    pump(app, 0.3)
    cv = win.preview.canvas
    vp = cv.viewport()
    pos = QPointF(vp.width() / 2, vp.height() / 2)

    def rueda(dy, mods, dx=0):
        g = QPointF(vp.mapToGlobal(pos.toPoint()))
        QApplication.sendEvent(vp, QWheelEvent(pos, g, QPoint(0, 0), QPoint(dx, dy), Qt.NoButton, mods,
                                               Qt.NoScrollPhase, False))
        pump(app, 0.05)
    cv.fit_view()
    pump(app, 0.1)
    c0 = cv.mapToScene(vp.rect().center()).y()
    rueda(-120, Qt.AltModifier)
    assert cv.view_dy > 0 and cv.mapToScene(vp.rect().center()).y() > c0, ("Alt+rueda abajo: la vista baja", cv.view_dy)
    rueda(0, Qt.AltModifier, dx=120)                # (en Windows, con Alt la rueda llega en X)
    assert abs(cv.view_dy) < 1.0, ("Alt+rueda arriba vuelve", cv.view_dy)
    for _ in range(60):
        rueda(-120, Qt.AltModifier)
    fr = cv.mapFromScene(cv.frame.sceneBoundingRect()).boundingRect()
    a_la_vista = min(fr.bottom(), vp.height()) - max(fr.top(), 0)
    assert a_la_vista >= 0.19 * min(fr.height(), vp.height()), ("siempre ≥ 20 % del video a la vista", a_la_vista)
    z0 = cv.view_zoom
    rueda(120, Qt.NoModifier)
    assert cv.view_zoom > z0, "la rueda sola sigue siendo el zoom"
    cv.fit_view()
    pump(app, 0.1)
    fr = cv.mapFromScene(cv.frame.sceneBoundingRect()).boundingRect()
    assert cv.view_dy == 0.0 and abs(fr.center().y() - vp.height() / 2) < 3, "«Ajustar» la centra"
    print("✓ Alt+rueda sube/baja la vista del visor (≥ 20 % a la vista); la rueda sola = zoom; Ajustar la centra")
    # 🧲 línea de tiempo suelta encima de la ventana
    d = win.docks["timeline"]
    assert not win._acoplar_timeline_si_tapa(), "acoplada: no hace nada"
    d.setFloating(True)
    d.resize(800, 300)
    d.move(win.frameGeometry().center() - QPoint(400, 150))
    pump(app, 0.2)
    assert win._acoplar_timeline_si_tapa(), "suelta encima de la ventana: vuelve abajo"
    pump(app, 0.2)
    assert not d.isFloating() and win.dockWidgetArea(d) == Qt.BottomDockWidgetArea and d.isVisible()
    d.setFloating(True)
    d.move(20000, 20000)                            # (fuera de toda pantalla: tampoco se ve)
    pump(app, 0.2)
    assert win._acoplar_timeline_si_tapa() and not d.isFloating(), "fuera de toda pantalla: vuelve abajo"
    pump(app, 0.2)
    print("✓ la línea de tiempo suelta encima de la ventana (o fuera de la pantalla) vuelve a su sitio, abajo")
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
