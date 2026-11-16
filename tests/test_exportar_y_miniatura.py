"""
🖼 Mientras exportas (video, Short o edit) puedes ir a hacer la miniatura: «🖼 Ir a Miniatura mientras exporta»
esconde la ventana de exportar (la exportación sigue), abre la página Miniatura y, al terminar, la ventana vuelve
con el resultado. Exportación real de 2 s (un color sólido), sin abrir nada.
Ejecutar:  .venv/Scripts/python.exe tests/test_exportar_y_miniatura.py <carpeta_salida>
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


def pump(app, s, hasta=None):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        if hasta is not None and hasta():
            return True
        time.sleep(0.02)
    return False


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from editoria.ui.main_window import MainWindow
    from editoria.ui.export_dialog import ExportDialog
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        ctrl = win.ctrl
        ctrl.add_generator({"kind": "solid", "c1": "#336699", "c2": "#336699"}, 0.0, 90.0)   # (que dure un rato)
        dlg = ExportDialog(ctrl, win)
        win._export_dlg = dlg
        destino = os.path.join(out, "prueba_miniatura.mp4")
        if os.path.exists(destino):
            os.remove(destino)
        dlg.out.setText(destino)
        dlg.show()
        pump(app, 0.2)
        assert not dlg.btn_mini.isVisible(), "antes de exportar no hace falta"
        dlg._start()
        assert pump(app, 20, lambda: dlg.proc is not None), "empezó a exportar"
        assert dlg.btn_mini.isVisible(), "mientras exporta: «🖼 Ir a Miniatura mientras exporta»"
        dlg.btn_mini.click()
        pump(app, 0.3)
        assert not dlg.isVisible() and win.page_buttons["thumb"].isChecked(), "a Miniatura, con la exportación detrás"
        print("✓ exportando: «🖼 Ir a Miniatura mientras exporta» esconde la ventana y abre Miniatura")
        assert dlg.exportando(), "la exportación de prueba aún va (si no, Exportar abriría otra revisión)"
        win.export()                                   # otra vez Exportar: enseña la que va, no abre otra
        pump(app, 0.2)
        assert win._export_dlg is dlg and dlg.isVisible() and dlg.exportando()
        dlg.reject()                                   # Esc: se esconde y sigue exportando
        pump(app, 0.2)
        assert not dlg.isVisible() and dlg.exportando()
        print("✓ volver a pulsar Exportar enseña la exportación en curso; Esc no la para")
        assert pump(app, 300, lambda: dlg.proc is None), "terminó"
        pump(app, 0.3)
        assert dlg.isVisible(), "al terminar vuelve la ventana de exportar"
        assert os.path.isfile(destino) and os.path.getsize(destino) > 1000, "el video se exportó igual"
        print("✓ la exportación siguió detrás y, al terminar, la ventana vuelve con el resultado")
        dlg.close()
        win.go_page("edit")
        pump(app, 0.2)
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
