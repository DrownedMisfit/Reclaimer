"""
Prueba: cerrar la ventana con un trabajo largo en segundo plano NO debe colgar el programa.
Lanza un BackgroundJob de 30 s que comprueba cancelled() cada 50 ms; con el proyecto guardado se cierra la
ventana: el cierre debe tardar < 3 s y el trabajo ya no debe correr.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_close_with_job.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
import faulthandler  # noqa: E402

faulthandler.dump_traceback_later(120, exit=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai.base import Cancelled  # noqa: E402
from editoria.ui.jobs import BackgroundJob  # noqa: E402
from editoria.ui.main_window import MainWindow  # noqa: E402
from editoria.ui.theme import apply_dark_theme  # noqa: E402


def pump(app, secs: float):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)

    stopped = {"v": False}

    def work(progress, cancelled):
        t0 = time.time()
        while time.time() - t0 < 30:
            if cancelled():
                stopped["v"] = True
                raise Cancelled()
            time.sleep(0.05)
        return "fin"

    job = BackgroundJob(work, win)       # con la ventana como «dueña», igual que los trabajos de la app
    win._test_job = job
    job.start()
    pump(app, 0.5)
    assert job.isRunning(), "el trabajo debería estar en marcha"

    win.ctrl.undo_stack.setClean()       # proyecto guardado: el cierre no pregunta nada
    win.ctrl._media_dirty = False
    print("  trabajo en marcha; cerrando la ventana…", flush=True)
    t1 = time.time()
    win.close()
    dt = time.time() - t1
    print(f"  cierre: {dt:.2f} s", flush=True)
    assert not win.isVisible(), "la ventana no se cerró"
    assert dt < 3.0, f"el cierre tardó {dt:.2f} s"
    pump(app, 0.2)
    assert not job.isRunning(), "el trabajo sigue corriendo tras cerrar"
    assert stopped["v"], "el trabajo no comprobó cancelled()"
    print("  cierre con trabajo en marcha < 3 s y trabajo parado  OK")
    print("TODO OK", flush=True)


if __name__ == "__main__":
    main()
