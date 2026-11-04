"""
Prueba de ARRANQUE: abre Reclaimer exactamente como el acceso directo (main.py → editoria.app.run), espera a
que la ventana esté lista y la cierra. Así un error al cargar el programa no se escapa (las demás pruebas
crean la ventana directamente y no pasan por aquí).
Usa una carpeta de datos TEMPORAL (no toca tu autoguardado ni tus registros).
Ejecutar:  .venv/Scripts/python.exe tests/test_startup.py <carpeta_salida>
"""
from __future__ import annotations

import compileall
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes —ventana, pestañas…— quedan como estaban)


def main():
    # 1) Todos los archivos del programa se pueden cargar (sin errores de escritura)
    assert compileall.compile_dir(os.path.join(ROOT, "editoria"), quiet=1, force=True), "hay archivos con errores"
    assert compileall.compile_file(os.path.join(ROOT, "main.py"), quiet=1)
    print("✓ todos los archivos del programa se cargan")

    # 2) Arranque real, como el acceso directo
    import runpy

    from PySide6.QtCore import QTimer

    import editoria.app as A
    state = {}
    orig_show = A.MainWindow.show

    def show(self):
        orig_show(self)
        state["win"] = self

        def finish():
            state["title"] = self.windowTitle()
            state["learn"] = self.btn_learning.text()
            self.ctrl.undo_stack.setClean()
            self.ctrl._media_dirty = False
            self.close()
        QTimer.singleShot(2500, finish)
    A.MainWindow.show = show
    sys.argv = [os.path.join(ROOT, "main.py")]
    try:
        runpy.run_path(os.path.join(ROOT, "main.py"), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"salió con código {e.code}"
    assert "win" in state and "Reclaimer" in state.get("title", ""), state
    assert "Aprendizaje IA" in state.get("learn", "")
    crash = os.path.join(_TMP, "EditorIA", "registros", "cierres_inesperados.log")
    assert os.path.exists(crash) and "=== sesión" in open(crash, encoding="utf-8").read()
    from PySide6.QtCore import QSettings
    st = QSettings("EditorIA", "EditorIA")
    for k in ("ventana/paneles", "guia/colocada"):
        st.remove(k)
    print(f"✓ arranca como el acceso directo («{state['title']}»), abre la ventana y se cierra bien")
    print("TODO OK")


if __name__ == "__main__":
    main()
