"""
Prueba de la página «🧭 Montaje guiado»:
  · su botón va justo después de «Editar» y deja a la vista el panel guiado y 🎬 Clips a la vez;
  · los 7 pasos existen, cada uno con su botón; el paso 3 cambia con los cortes dudosos;
  · el botón del paso 6 lleva a Miniatura y volver a «Editar» funciona;
  · lo que se cambia en el proyecto desde la página guiada sigue al pasar a «Editar».
Ejecutar:  .venv/Scripts/python.exe tests/test_guided.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
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

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def visible(win, key) -> bool:
    d = win.docks[key]
    return (not d.isHidden()) and (not d.visibleRegion().isEmpty())


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    try:
        # 1) El botón de página va después de «Editar»
        keys = [k for k, _i, _l in win.PAGES]
        assert keys.index("guided") == keys.index("edit") + 1, keys
        assert win.page_buttons["guided"].text() == "Montaje guiado"
        print("✓ «Montaje guiado» está justo después de «Editar» en la barra de páginas")

        # 2) Entrar en la página: marcada, y el panel guiado y 🎬 Clips a la vista a la vez
        win.go_page("guided")
        pump(app, 0.2)
        assert win.page_buttons["guided"].isChecked() and not win.page_buttons["edit"].isChecked()
        assert visible(win, "guided") and visible(win, "clips"), (visible(win, "guided"), visible(win, "clips"))
        print("✓ al entrar: el panel guiado y 🎬 Clips están a la vista a la vez")

        # 3) Los 7 pasos, cada uno con su botón
        g = win.guided
        assert len(g.pasos) == 7
        for i, paso in enumerate(g.pasos, 1):
            botones = [paso.botones.itemAt(j).widget() for j in range(paso.botones.count())]
            assert botones and all(isinstance(b, QPushButton) for b in botones), i
        assert g.p3.botones.count() == 2 and g.p1.botones.count() == 1
        print("✓ 7 pasos, cada uno con su botón (paso 3: Revisar y Aplicar todas)")

        # 4) Paso 3 con cortes dudosos: 2 → botones activos; 0 → ✓ y desactivados
        tl = win.timeline
        tl.cut_issues = [{"t": 1.0, "track_id": "x", "key": "a", "reasons": ["r"]},
                         {"t": 2.0, "track_id": "x", "key": "b", "reasons": ["r"]}]
        tl.cut_issues_changed.emit(2)
        assert g.p3.estado.text() == "2 cortes dudosos", g.p3.estado.text()
        assert g.b3_revisar.isEnabled() and g.b3_todas.isEnabled()
        tl.cut_issues = []
        tl.cut_issues_changed.emit(0)
        assert g.p3.estado.text() == "✓ Ningún corte dudoso", g.p3.estado.text()
        assert not g.b3_revisar.isEnabled() and not g.b3_todas.isEnabled()
        assert not g.p3.hecho.isHidden(), "el ✓ del paso 3 debería verse tras haber cortado y quedar 0"
        print("✓ paso 3: con 2 cortes → «2 cortes dudosos» y botones activos; con 0 → ✓ y desactivados")

        # 5) Un cambio en el proyecto desde esta página (un marcador) sigue al pasar a «Editar»
        n_antes = len(ctrl.project.markers)
        ctrl.add_marker(3.0, "prueba guiado")
        pump(app, 0.1)
        assert len(ctrl.project.markers) == n_antes + 1
        win.go_page("edit")
        pump(app, 0.1)
        assert win.page_buttons["edit"].isChecked() and not win.page_buttons["guided"].isChecked()
        assert any(m.label == "prueba guiado" for m in ctrl.project.markers)
        print("✓ el marcador añadido en Montaje guiado sigue al pasar a Editar")

        # 6) Paso 6 → Miniatura; volver a Editar funciona
        win.go_page("guided")
        g.p6.botones.itemAt(0).widget().click()
        pump(app, 0.3)
        assert win.page_buttons["thumb"].isChecked(), "no llegó a Miniatura"
        win.go_page("edit")
        pump(app, 0.2)
        assert win.page_buttons["edit"].isChecked() and not win.page_buttons["thumb"].isChecked()
        print("✓ paso 6 lleva a Miniatura y volver a «Editar» funciona")

        # 7) Paso 1 cuenta los archivos de Medios
        win.go_page("guided")
        wav = os.path.join(out, "narracion.wav")
        shutil.copy(os.path.join(ASSETS, "narracion_prueba.wav"), wav)
        ctrl.import_now([wav])
        t0 = time.time()
        while ctrl.analyzing and time.time() - t0 < 60:
            pump(app, 0.1)
        pump(app, 1.2)
        assert g.p1.estado.text().startswith("1 archivo"), g.p1.estado.text()
        assert g.p1.hecho.isVisibleTo(g.p1)
        print(f"✓ paso 1: «{g.p1.estado.text()}» con ✓")
        print("   pasos:", " | ".join(f"{p.titulo.text()}: {p.estado.text() or '-'}" for p in g.pasos))

        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        pass
    print("TODO OK")


if __name__ == "__main__":
    main()
