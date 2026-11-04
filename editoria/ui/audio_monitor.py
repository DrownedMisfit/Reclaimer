"""
«Escuchar con EQ»: repite en bucle unos segundos alrededor del cabezal con TODOS los efectos
de audio (ecualizador, balance, efectos de voz, ducking) y se vuelve a preparar sola cada
vez que cambias algo (menos de medio segundo). Qt no permite efectos de audio en directo,
así que se renderiza ese trocito con FFmpeg.
"""
from __future__ import annotations

import os
import subprocess
from ..core.paths import temp_dir as _temp_dir

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..core import media as media_tools
from ..core.project_tools import slice_project
from ..export.ffmpeg_export import ExportOptions, build_command
from .jobs import BackgroundJob

LOOP_SECONDS = 6.0


class AudioMonitor(QObject):
    state_changed = Signal(bool)
    status = Signal(str)

    def __init__(self, ctrl, engine, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.on = False
        self.start_t = 0.0
        self.job: BackgroundJob | None = None
        self._pending = False
        self._flip = 0
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.player.setAudioOutput(self.out)
        self.player.setLoops(QMediaPlayer.Infinite)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._render)
        ctrl.project_changed.connect(self._changed)

    def toggle(self):
        self.stop() if self.on else self.start()

    def start(self):
        self.engine.pause()
        self.on = True
        self.start_t = max(0.0, self.engine.time - 1.0)
        self.state_changed.emit(True)
        self._render()

    def stop(self):
        self.on = False
        self.player.stop()
        self.state_changed.emit(False)
        self.status.emit("")

    def _changed(self):
        if self.on:
            self._timer.start()

    def _render(self):
        if not self.on:
            return
        if self.job is not None:
            self._pending = True
            return
        part = slice_project(self.ctrl.project, self.start_t, self.start_t + LOOP_SECONDS)
        if part.duration() <= 0:
            self.status.emit("No hay audio en este momento.")
            return
        self._flip ^= 1  # alterna dos archivos: así no se escribe el que está sonando
        out = os.path.join(str(_temp_dir()), f"editoria_monitor_{self._flip}.wav")
        script = os.path.join(str(_temp_dir()), f"editoria_monitor_{self._flip}.txt")

        def work(_progress, _cancelled):
            args, _t = build_command(part, ExportOptions(path=out, audio_only=True, loudnorm=False),
                                     media_tools.ffmpeg(), script)
            r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                               creationflags=media_tools.NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
            return out

        self.job = BackgroundJob(work, self)
        self.job.done.connect(self._play)
        self.job.failed.connect(lambda msg: self.status.emit(f"✗ {msg}"))
        self.job.finished.connect(self._finished)
        self.status.emit("🎧 Preparando…")
        self.job.start()

    def _play(self, path: str):
        if not self.on:
            return
        pos = self.player.position()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPosition(pos)
        self.player.play()
        self.status.emit(f"🎧 Sonando en bucle ({LOOP_SECONDS:.0f} s) con los cambios. Pulsa otra vez para parar.")

    def _finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        if self._pending:
            self._pending = False
            self._render()
