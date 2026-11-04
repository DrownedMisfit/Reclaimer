"""
La exportación EN PARALELO (export/parallel.py) con la misma cara que un QProcess de FFmpeg, para que la ventana
Exportar y la cola de exportación la usen igual: readyReadStandardOutput + readAllStandardOutput() con líneas
«out_time_us=…», finished(código, estado), kill(), waitForFinished().
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import media as media_tools
from ..core.model import new_id
from ..core.paths import temp_dir
from ..export import parallel


def start(proc, args, opts):
    """Arranca la exportación (un QProcess de FFmpeg o un ParallelProcess). Con «Dejar libre el PC», FFmpeg va en
    prioridad baja: lo que estés usando (un juego, el propio editor) va primero."""
    proc.start(args[0], args[1:])
    if getattr(opts, "low_priority", False) and not isinstance(proc, ParallelProcess):
        parallel.lower_priority(int(proc.processId() or 0))


def make(project, opts, parent=None):
    """Un ParallelProcess si compensa partir el video (o None: entonces, de una vez)."""
    total = opts.duration or project.duration()
    chunks = parallel.plan(project, opts, total)
    if not chunks:
        return None
    return ParallelProcess(project, opts, chunks, total, parent)


class ParallelProcess(QObject):
    readyReadStandardOutput = Signal()
    finished = Signal(int, int)

    def __init__(self, project, opts, chunks, total, parent=None):
        super().__init__(parent)
        self.total = total
        self.n = len(chunks)
        work = os.path.join(str(temp_dir()), f"exportar_trozos_{new_id()}")
        self.job = parallel.ParallelExport(project, opts, media_tools.ffmpeg(), work, chunks, total)
        self._buf: list[str] = []
        self._code = None
        self._thread = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)

    def start(self, *_a):
        def go():
            try:
                self.job.run()
                self._code = 0
            except Exception as exc:  # noqa: BLE001 - se informa en el registro de la ventana
                self._buf.extend(self.job.log + [f"✗ {exc}"])
                self._code = 1
        self._thread = threading.Thread(target=go, daemon=True)
        self._thread.start()
        self._timer.start()

    def _tick(self):
        self._buf.append(f"out_time_us={int(self.job.fraction() * self.total * 1e6)}")
        self.readyReadStandardOutput.emit()
        if self._code is not None and not self._thread.is_alive():
            self._timer.stop()
            self.readyReadStandardOutput.emit()
            self.finished.emit(self._code, 0)

    def readAllStandardOutput(self) -> bytes:
        out, self._buf = self._buf, []
        return ("\n".join(out) + "\n").encode() if out else b""

    def kill(self):
        self.job.stop()

    def waitForFinished(self, ms: int = 3000) -> bool:
        if self._thread is not None:
            self._thread.join(ms / 1000)
        return self._thread is None or not self._thread.is_alive()

    def wait_seconds(self) -> float:      # para pruebas
        t0 = time.time()
        while self._thread is not None and self._thread.is_alive():
            time.sleep(0.05)
        return time.time() - t0
