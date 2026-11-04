"""
Prueba del cierre inesperado «QThread: Destroyed while thread is still running»: si se cierra la ventana dueña de
un trabajo en segundo plano mientras corre, el programa NO se cae; el trabajo para, ya no avisa a nadie y se
suelta solo al terminar. Y al cerrar el programa, stop_all espera a todos.
Ejecutar:  .venv/Scripts/python.exe tests/test_job_lifetime.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication(sys.argv)
    from editoria.ui import jobs
    from editoria.ui.jobs import BackgroundJob
    from editoria.ui.task_window import stop_all

    got = []

    def slow(progress, cancelled):
        for _ in range(60):          # ~1,2 s; ignora «cancelado» a propósito al principio
            time.sleep(0.02)
        return "hecho"

    # 1) La ventana dueña se destruye mientras el trabajo corre → sin caída
    w = QWidget()
    job = BackgroundJob(slow, w)
    job.done.connect(lambda r: got.append(r))
    job.start()
    del job
    pump(app, 0.2)
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)     # la ventana se borra de verdad
    pump(app, 0.2)
    assert jobs.live_jobs() and list(jobs._LIVE)[0]._orphaned
    assert jobs.live_jobs(), "el trabajo sigue vivo (guardado), no se destruyó a medias"
    pump(app, 1.6)
    assert not jobs.live_jobs() and not jobs._LIVE, "al terminar se suelta solo"
    assert got == [], "ya no avisa a la ventana borrada"
    print("✓ cerrar la ventana mientras su trabajo corre: sin cierre inesperado; el trabajo acaba y se suelta")

    # 2) Un diálogo con trabajo, cerrado de golpe (como Momentos / Ejemplo)
    d = QDialog()
    j2 = BackgroundJob(lambda p, c, part: [part(i) or time.sleep(0.05) for i in range(20) if not c()], d,
                       with_partial=True)
    parts = []
    j2.partial.connect(lambda x: parts.append(x))
    j2.start()
    pump(app, 0.15)
    d.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    del d, j2
    pump(app, 1.5)
    assert not jobs._LIVE and len(parts) < 20
    print(f"✓ diálogo cerrado a mitad: el trabajo paró ({len(parts)} de 20 avisos) y no se cayó nada")

    # 3) Normal: sigue funcionando igual
    j3 = BackgroundJob(lambda p, c: 42)
    j3.done.connect(lambda r: got.append(r))
    j3.start()
    pump(app, 0.5)
    assert got == [42] and not jobs._LIVE
    # 4) stop_all espera a los que quedan
    j4 = BackgroundJob(lambda p, c: [time.sleep(0.02) for _ in range(500) if not c()])
    j4.start()
    pump(app, 0.1)
    left = stop_all(3000)
    assert left == [] and not j4.isRunning()
    print("✓ trabajos normales igual que siempre; al cerrar, stop_all para y espera a todos")
    print("TODO OK")


if __name__ == "__main__":
    main()
