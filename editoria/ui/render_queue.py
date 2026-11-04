"""
🚀 Cola de exportación (como la «Render Queue» de Resolve): varias exportaciones, una detrás de otra.

Cada trabajo guarda una FOTO del proyecto en el momento de añadirlo (así puedes seguir editando sin
cambiar lo que ya está en la cola) y sus ajustes (resolución, códec, tramo, solo audio…).
"""
from __future__ import annotations

import os
from ..core.paths import temp_dir as _temp_dir
import time
from dataclasses import asdict

from PySide6.QtCore import QObject, QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..core import media as media_tools
from ..core.model import Project
from ..export.ffmpeg_export import ExportOptions, build_command

STATUS = {"pending": "⏳ En cola", "running": "▶ Exportando", "done": "✓ Listo", "error": "✗ Falló",
          "cancelled": "■ Cancelado"}


class RenderQueue(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: list[dict] = []
        self.proc: QProcess | None = None
        self.current: dict | None = None
        self._stop = False

    # ---------------------------------------------------------------- trabajos
    def add(self, project: Project, opts: ExportOptions, name: str, rng: tuple[float, float] | None = None) -> dict:
        snap = project
        if rng:
            from ..core.project_tools import slice_project
            snap = slice_project(project, *rng)
        job = {"name": name, "snapshot": snap.to_dict(), "opts": asdict(opts), "status": "pending",
               "progress": 0.0, "error": "", "added": time.strftime("%H:%M")}
        self.jobs.append(job)
        self.changed.emit()
        return job

    def remove(self, i: int):
        if 0 <= i < len(self.jobs) and self.jobs[i] is not self.current:
            del self.jobs[i]
            self.changed.emit()

    def clear_done(self):
        self.jobs = [j for j in self.jobs if j["status"] in ("pending", "running")]
        self.changed.emit()

    @property
    def running(self) -> bool:
        return self.proc is not None

    # ---------------------------------------------------------------- ejecutar
    def start(self):
        if self.proc is not None:
            return
        self._stop = False
        self._next()

    def stop(self):
        self._stop = True
        if self.proc is not None:
            self.current["status"] = "cancelled"
            self.proc.kill()

    def _next(self):
        job = next((j for j in self.jobs if j["status"] == "pending"), None)
        if job is None or self._stop:
            self.current = None
            self.changed.emit()
            return
        opts = ExportOptions(**job["opts"])
        os.makedirs(os.path.dirname(opts.path) or ".", exist_ok=True)
        script = os.path.join(str(_temp_dir()), f"editoria_cola_{id(job)}.txt")
        try:
            project = Project.from_dict(job["snapshot"])
            args, total = build_command(project, opts, media_tools.ffmpeg(), script)
        except (ValueError, RuntimeError) as exc:
            job["status"], job["error"] = "error", str(exc)
            self.changed.emit()
            self._next()
            return
        job["status"], job["total"], job["t0"] = "running", total, time.time()
        self.current = job
        self._log: list[str] = []
        from . import export_runner
        self.proc = export_runner.make(project, opts, self)      # por trozos a la vez, si se puede
        if self.proc is None:
            self.proc = QProcess(self)
            self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        export_runner.start(self.proc, args, opts)
        self.changed.emit()

    def _read(self):
        job = self.current
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    secs = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                job["progress"] = min(1.0, secs / job["total"]) if job.get("total") else 0.0
                self.changed.emit()
            elif not line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time=",
                                      "dup_frames=", "drop_frames=", "speed=", "progress=")):
                self._log = (self._log + [line])[-40:]

    def _finished(self, code, _status):
        job, proc = self.current, self.proc
        self.proc = None
        if proc is not None:
            proc.deleteLater()
        if job is not None:
            if job["status"] != "cancelled":
                if code == 0:
                    job["status"], job["progress"] = "done", 1.0
                    job["secs"] = int(time.time() - job.get("t0", time.time()))
                else:
                    job["status"], job["error"] = "error", "\n".join(self._log[-8:])
        self.changed.emit()
        self._next()


class QueueDialog(QDialog):
    """La lista de la cola: estado, progreso y acciones."""

    def __init__(self, win, queue: RenderQueue):
        super().__init__(win)
        self.win, self.queue = win, queue
        self.setWindowTitle("🚀 Cola de exportación")
        self.resize(760, 380)
        lay = QVBoxLayout(self)
        info = QLabel("Añade exportaciones desde «Exportar → ➕ Añadir a la cola» o con los botones de abajo. "
                      "Cada una guarda cómo estaba el proyecto al añadirla.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Exportación", "Archivo", "Estado", "Progreso"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        quick = QHBoxLayout()
        quick.addWidget(QLabel("Añadir rápido:"))
        for text, kind in (("🔊 Solo audio (WAV)", "audio"), ("⟦ ⟧ Tramo marcado", "range"),
                           ("🎞 El video en 4K", "4k")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind: self.quick_add(k))
            quick.addWidget(b)
        quick.addStretch()
        lay.addLayout(quick)
        row = QHBoxLayout()
        self.b_run = QPushButton("▶ Exportar todo")
        self.b_run.setObjectName("primary")
        self.b_run.clicked.connect(self._run)
        b_rm = QPushButton("✕ Quitar")
        b_rm.clicked.connect(lambda: self.queue.remove(self.table.currentRow()))
        b_clear = QPushButton("Limpiar terminados")
        b_clear.clicked.connect(self.queue.clear_done)
        b_open = QPushButton("📂 Abrir carpeta")
        b_open.clicked.connect(self._open)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        for b in (self.b_run, b_rm, b_clear, b_open):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_close)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        queue.changed.connect(self.refresh)
        self.refresh()

    def _run(self):
        if self.queue.running:
            self.queue.stop()
        else:
            self.queue.start()

    def _open(self):
        i = self.table.currentRow()
        jobs = self.queue.jobs
        if 0 <= i < len(jobs):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(jobs[i]["opts"]["path"])))

    def quick_add(self, kind: str):
        p = self.win.ctrl.project
        base = self.win.default_export_path()
        stem, _ext = os.path.splitext(base)
        if kind == "audio":
            opts = ExportOptions(path=stem + ".wav", audio_only=True)
            self.queue.add(p, opts, "Solo audio (WAV)")
        elif kind == "range":
            rng = p.marked_range()
            if rng is None:
                self.status.setText("Marca primero un tramo con I (entrada) y O (salida).")
                return
            opts = ExportOptions(path=stem + "_tramo.mp4", width=p.width, height=p.height, fps=p.fps)
            self.queue.add(p, opts, "Tramo marcado", rng)
        else:
            w, h = (3840, 2160) if p.width >= p.height else (2160, 3840)
            opts = ExportOptions(path=stem + "_4K.mp4", width=w, height=h, fps=p.fps, bitrate_mbps=45)
            self.queue.add(p, opts, "4K")
        self.status.setText("✓ Añadido a la cola.")

    def refresh(self):
        jobs = self.queue.jobs
        self.table.setRowCount(len(jobs))
        for i, j in enumerate(jobs):
            o = j["opts"]
            what = j["name"] + ("" if o.get("audio_only") else f" · {o['width']}×{o['height']}")
            prog = f"{j['progress'] * 100:.0f} %" if j["status"] in ("running", "done") else ""
            if j["status"] == "done" and j.get("secs") is not None:
                prog += f" ({j['secs']} s)"
            for col, text in enumerate((what, o["path"], STATUS.get(j["status"], j["status"]), prog)):
                it = QTableWidgetItem(text)
                if col == 2 and j["status"] == "error":
                    it.setToolTip(j.get("error", ""))
                self.table.setItem(i, col, it)
        self.b_run.setText("■ Detener" if self.queue.running else "▶ Exportar todo")
        pending = sum(1 for j in jobs if j["status"] == "pending")
        self.status.setText(f"{len(jobs)} en la lista · {pending} por exportar" if jobs else "La cola está vacía.")
