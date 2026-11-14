"""
🖼 Medios → 🔑 Palabras clave: los archivos de tus carpetas (aún no en el proyecto) salen con su miniatura, no con un
icono de archivo en blanco; un video roto no se reintenta en cada repintado (sin ventanas visibles).
Ejecutar:  .venv/Scripts/python.exe tests/test_medios_miniaturas_kw.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()                       # (antes de cambiar LOCALAPPDATA: FFmpeg de winget se busca ahí)
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMP = tempfile.mkdtemp(prefix="reclaimer_mini_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    raiz = os.path.join(_TMP, "carpetas")
    os.makedirs(os.path.join(raiz, "Volcan"), exist_ok=True)
    bueno = os.path.join(raiz, "Volcan", "lava.mp4")
    subprocess.run([_FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-c:v", "libx264",
                    "-preset", "ultrafast", bueno], check=True, creationflags=M.NO_WINDOW)
    roto = os.path.join(raiz, "Volcan", "roto.mp4")
    open(roto, "wb").write(b"\0" * 4096)
    from editoria.ui import clips_panel as CP
    QSettings("EditorIA", "EditorIA").setValue(CP.RAIZ_CLAVE, raiz)
    llamadas = []
    real = CP._hacer_miniatura
    CP._hacer_miniatura = lambda r, s: (llamadas.append(os.path.basename(r)), real(r, s))[1]
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    lib = win.library
    lib._rebuild() if hasattr(lib, "_rebuild") else lib.refresh()
    pump(app, 3.0)
    it = lib._kw_items_ruta.get(bueno)
    assert it is not None and lib._kw_clave(bueno) in lib._kw_iconos, (it, list(lib._kw_iconos))
    assert it.text(2) == "en tu carpeta", it.text(2)
    print("✓ el archivo de tu carpeta sale con su miniatura (y «en tu carpeta»), no con un icono en blanco")
    assert lib._kw_clave(roto) in lib._kw_mini_fallidas
    llamadas.clear()
    lib._rebuild() if hasattr(lib, "_rebuild") else lib.refresh()
    pump(app, 1.0)
    assert "roto.mp4" not in llamadas and "lava.mp4" not in llamadas, llamadas
    print("✓ al repintar Medios no se rehace nada: ni la miniatura ya hecha ni la del video roto")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
