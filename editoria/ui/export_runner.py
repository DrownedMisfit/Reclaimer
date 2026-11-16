"""
La exportación EN PARALELO (export/parallel.py) con la misma cara que un QProcess de FFmpeg, para que la ventana
Exportar y la cola de exportación la usen igual: readyReadStandardOutput + readAllStandardOutput() con líneas
«out_time_us=…», finished(código, estado), kill(), waitForFinished().
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

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


def make_single(project, opts, script: str, parent=None, cues=None):
    """Exportar de una vez: un QProcess de FFmpeg o, si los subtítulos van como imágenes (Neón, palabra a
    palabra…), un SubsFirstProcess que primero las dibuja en segundo plano (build_command con raster=False)."""
    from ..export.ffmpeg_export import raster_needed
    if raster_needed(project, opts):
        return SubsFirstProcess(project, opts, script, parent, cues=cues)
    proc = QProcess(parent)
    proc.setProcessChannelMode(QProcess.MergedChannels)
    return proc


ORPHAN_AGE = 12 * 3600      # s: carpetas de imágenes de subtítulos más viejas que esto, de exportaciones que no acabaron


def sweep_orphans():
    """Al arrancar: borra las carpetas de imágenes de subtítulos que dejó una exportación interrumpida (Reclaimer
    cerrado de golpe, apagón…). Solo las de la ventana Exportar y de la cola, con su nombre exacto, en la carpeta
    temporal de Reclaimer, y solo si llevan ORPHAN_AGE sin tocarse (otra ventana de Reclaimer podría estar usándolas)."""
    import re
    import shutil
    pat = re.compile(r"^(editoria_export_filtro|editoria_cola_\d+)_subs$")
    try:
        root = str(temp_dir())
        names = os.listdir(root)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(root, name)
        if not pat.match(name) or not os.path.isdir(path):
            continue
        try:
            newest = max([os.path.getmtime(path)] + [os.path.getmtime(os.path.join(path, f)) for f in os.listdir(path)])
        except OSError:
            continue
        if now - newest > ORPHAN_AGE:
            shutil.rmtree(path, ignore_errors=True)


def cleanup(script: str):
    """Borra las imágenes de subtítulos de esa exportación (su carpeta propia)."""
    import shutil
    from ..export.ffmpeg_export import subs_dir
    if script:
        for _ in range(10):              # (Windows suelta los archivos un instante después de cerrar FFmpeg)
            shutil.rmtree(subs_dir(script), ignore_errors=True)
            if not os.path.exists(subs_dir(script)):
                break
            time.sleep(0.1)


def make(project, opts, parent=None, cues=None):
    """Un ParallelProcess si compensa partir el video (o None: entonces, de una vez). cues: las frases ya calculadas
    (p. ej. las del video entero al exportar solo el tramo marcado)."""
    total = opts.duration or project.duration()
    chunks = parallel.plan(project, opts, total)
    if not chunks:
        return None
    return ParallelProcess(project, opts, chunks, total, parent, cues=cues)


class ParallelProcess(QObject):
    readyReadStandardOutput = Signal()
    finished = Signal(int, int)

    def __init__(self, project, opts, chunks, total, parent=None, cues=None):
        super().__init__(parent)
        self.total = total
        self.n = len(chunks)
        work = os.path.join(str(temp_dir()), f"exportar_trozos_{new_id()}")
        self.job = parallel.ParallelExport(project, opts, media_tools.ffmpeg(), work, chunks, total, cues=cues)
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


class SubsFirstProcess(QObject):
    """Como un QProcess de FFmpeg, pero antes dibuja las imágenes de los subtítulos EN SEGUNDO PLANO (con progreso:
    el primer SUBS_PART de la barra; cancelable). Luego lanza FFmpeg y reenvía su progreso."""
    readyReadStandardOutput = Signal()
    finished = Signal(int, int)
    SUBS_PART = 0.15

    def __init__(self, project, opts, script, parent=None, cues=None):
        super().__init__(parent)
        self.project, self.opts, self.script, self.cues = project, opts, script, cues
        self.subs_failed = False
        self.total = opts.duration or project.duration()
        self.n = 1
        self._buf: list[str] = []
        self._frac = 0.0
        self._cancel = False
        self._err = None
        self._thread = None
        self._proc = None
        self._args = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

    def start(self, program, args):
        from ..export.ffmpeg_export import prepare_subtitles
        self._args = (program, list(args))

        def go():
            try:
                prepare_subtitles(self.project, self.opts, self.script, cues=self.cues,
                                  progress=lambda f: setattr(self, "_frac", f), cancelled=lambda: self._cancel)
            except Exception as exc:  # noqa: BLE001 - se informa en el registro de la ventana
                self._err = str(exc)
        self._thread = threading.Thread(target=go, daemon=True)
        self._thread.start()
        self._timer.start()

    def processId(self) -> int:
        return int(self._proc.processId() or 0) if self._proc is not None else 0

    def _tick(self):
        self._buf.append(f"out_time_us={int(self._frac * self.SUBS_PART * self.total * 1e6)}")
        self.readyReadStandardOutput.emit()
        if self._thread is not None and self._thread.is_alive():
            return
        self._timer.stop()
        if self._cancel or self._err:
            self.subs_failed = True                  # (la ventana no reintenta con el procesador: no era FFmpeg)
            self._buf.append(f"✗ Subtítulos: {self._err or 'cancelado'}")
            self.readyReadStandardOutput.emit()
            self.finished.emit(1, 0)
            return
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._forward)
        self._proc.finished.connect(lambda code, st: self.finished.emit(code, int(getattr(st, "value", st))))
        self._proc.start(self._args[0], self._args[1])
        if getattr(self.opts, "low_priority", False):
            parallel.lower_priority(self.processId())

    def _forward(self):
        data = bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        k = self.SUBS_PART
        for line in data.splitlines():
            if line.startswith(("out_time_us=", "out_time_ms=")):
                name, _, val = line.partition("=")
                try:
                    us = int(val)
                except ValueError:
                    continue
                line = f"{name}={int(k * self.total * 1e6 + (1 - k) * us)}"
            self._buf.append(line)
        self.readyReadStandardOutput.emit()

    def readAllStandardOutput(self) -> bytes:
        out, self._buf = self._buf, []
        return ("\n".join(out) + "\n").encode() if out else b""

    def kill(self):
        self._cancel = True
        if self._proc is not None:
            self._proc.kill()

    def waitForFinished(self, ms: int = 3000) -> bool:
        if self._thread is not None:
            self._thread.join(ms / 1000)
        if self._proc is not None:
            return self._proc.waitForFinished(ms)
        return self._thread is None or not self._thread.is_alive()
