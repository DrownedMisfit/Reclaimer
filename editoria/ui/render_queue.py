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
from ..export.ffmpeg_export import ExportOptions, build_command, partial_path

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
        opts = self._free_path(opts)
        job = {"name": name, "snapshot": snap.to_dict(), "opts": asdict(opts), "status": "pending",
               "progress": 0.0, "error": "", "added": time.strftime("%H:%M")}
        self.jobs.append(job)
        self.changed.emit()
        return job

    @staticmethod
    def _key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _free_path(self, opts: ExportOptions) -> ExportOptions:
        """Dos trabajos de la cola nunca escriben en el mismo archivo: si ya hay uno en cola o exportándose con esa
        ruta, este se llama «<nombre> (2)», «(3)»… (un nombre nuevo que tampoco exista ya en la carpeta)."""
        taken = {self._key(j["opts"]["path"]) for j in self.jobs if j["status"] in ("pending", "running")}
        try:                       # (y la que esté haciendo la ventana Exportar)
            dlg = getattr(self.parent(), "_export_dlg", None)
            if dlg is not None and dlg.exportando() and getattr(dlg, "_opts", None) is not None:
                taken.add(self._key(dlg._opts.path))
        except (AttributeError, RuntimeError):
            pass
        if self._key(opts.path) not in taken:
            return opts
        from dataclasses import replace
        stem, ext = os.path.splitext(opts.path)
        k = 2
        while True:
            cand = f"{stem} ({k}){ext}"
            if self._key(cand) not in taken and not os.path.exists(cand):
                return replace(opts, path=cand)
            k += 1

    def busy(self) -> bool:
        """¿Exportando o con trabajos por exportar?"""
        return self.proc is not None or any(j["status"] == "pending" for j in self.jobs)

    def pending_count(self) -> int:
        return sum(1 for j in self.jobs if j["status"] == "pending")

    def abort(self, ms: int = 3000):
        """Al cerrar el programa: para lo que se esté exportando, espera un momento y borra sus temporales y el
        archivo a medias (el final, si ya existía, queda como estaba)."""
        proc = self.proc
        self.stop()
        if proc is not None:
            try:
                proc.waitForFinished(ms)
            except RuntimeError:
                pass
        from . import export_runner
        export_runner.cleanup(getattr(self, "_script", ""))
        export_runner.discard_partial(getattr(self, "_partial", ""))

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
        while True:
            job = next((j for j in self.jobs if j["status"] == "pending"), None)
            if job is None or self._stop:
                self.current = None
                self.changed.emit()
                return
            if self._launch(job):
                return
            self.changed.emit()          # (ese falló al prepararse: sigue con el siguiente)

    def _launch(self, job: dict, cpu: bool = False) -> bool:
        """Arranca un trabajo. Si no se puede ni preparar (carpeta sin permiso, proyecto roto…), lo marca como
        fallido y devuelve False: la cola nunca se queda parada en silencio."""
        from dataclasses import replace

        from . import export_runner
        script = os.path.join(str(_temp_dir()), f"editoria_cola_{id(job)}.txt")
        try:
            opts = ExportOptions(**job["opts"])
            if cpu:
                opts = replace(opts, encoder="cpu")
            os.makedirs(os.path.dirname(opts.path) or ".", exist_ok=True)
            # Se escribe en «<nombre>.parcial.mp4»; solo si sale bien pasa a llamarse como pediste
            work = replace(opts, path=partial_path(opts.path))
            project = Project.from_dict(job["snapshot"])
            args, total = build_command(project, work, media_tools.ffmpeg(), script, raster=False)
            job["status"], job["total"], job["t0"] = "running", total, job.get("t0") or time.time()
            job["cpu"] = cpu
            self.current = job
            self._log: list[str] = []
            self._script, self._partial, self._final = script, work.path, opts.path
            self._encoder = opts.encoder
            export_runner.track_partial(work.path)      # (si Reclaimer se cierra de golpe, se borra al arrancar)
            proc = export_runner.make(project, work, self)      # por trozos a la vez, si se puede
            if proc is None:
                proc = export_runner.make_single(project, work, script, self)
            self.proc = proc
            proc.readyReadStandardOutput.connect(self._read)
            proc.finished.connect(self._finished)
            export_runner.start(proc, args, work)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo al preparar: ese trabajo falla y la cola sigue
            self.proc = None
            self.current = None
            export_runner.cleanup(script)
            job["status"], job["error"] = "error", str(exc) or exc.__class__.__name__
            return False
        self.changed.emit()
        return True

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
        subs_failed = bool(getattr(proc, "subs_failed", False))     # (falló el dibujo de los subtítulos, no FFmpeg)
        from . import export_runner
        export_runner.cleanup(getattr(self, "_script", ""))      # (guion, textos y subtítulos, fuera)
        partial, final = getattr(self, "_partial", ""), getattr(self, "_final", "")
        if job is not None:
            if job["status"] != "cancelled" and code == 0 and export_runner.finish_partial(partial, final):
                job["status"], job["progress"] = "done", 1.0
                job["secs"] = int(time.time() - job.get("t0", time.time()))
            else:
                export_runner.discard_partial(partial)
                if job["status"] != "cancelled":
                    if (code != 0 and getattr(self, "_encoder", "") == "gpu" and not job.get("cpu")
                            and not subs_failed and not self._stop
                            and export_runner.looks_like_encoder_failure(self._log)):
                        # La tarjeta gráfica falló (driver, tamaño raro…): se reintenta sola con el procesador
                        # (no si el fallo es de disco lleno o de un archivo que falta: fallaría igual)
                        job["status"], job["progress"] = "pending", 0.0
                        if self._launch(job, cpu=True):
                            return
                    if job["status"] != "error":
                        job["status"] = "error"
                        job["error"] = ("\n".join(self._log[-8:]) if code != 0
                                        else "No se pudo poner el nombre final al video.")
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
        _ayuda_cola = ("Añade exportaciones desde «Exportar → ➕ Añadir a la cola» o con los botones de abajo. "
                       "Cada una guarda cómo estaba el proyecto al añadirla.")   # (20/11: al tooltip de la tabla)
        self.table = QTableWidget(0, 4)
        self.table.setToolTip(_ayuda_cola)
        self.table.setHorizontalHeaderLabels(["Exportación", "Archivo", "Estado", "Progreso"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        quick = QHBoxLayout()
        self._lbl_rapido = QLabel("Añadir rápido:")
        quick.addWidget(self._lbl_rapido)
        self._rapidos: list[QPushButton] = []
        for text, kind in (("🔊 Solo audio (WAV)", "audio"), ("⟦ ⟧ Tramo marcado", "range"),
                           ("🎞 El video en 4K", "4k")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind: self.quick_add(k))
            quick.addWidget(b)
            self._rapidos.append(b)
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
        self._acciones, self._b_close, self._lay = [self.b_run, b_rm, b_clear, b_open], b_close, lay
        row.addStretch()
        row.addWidget(b_close)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        queue.changed.connect(self.refresh)
        self.refresh()

    def compactar(self):
        """🧰 Como pestaña del panel de herramientas (lote 1, 23/11), en ~300 px: la tabla sin la columna del archivo
        (va en el tooltip de cada fila), los botones en rejilla de dos y sin «Cerrar» (ya está la ✕)."""
        from . import compacto as _compacto
        _compacto.ajustar_zonas(self)     # (el contenido de cada zona, al ancho visible menos la barra)
        from . import compacto
        self._compacta = True
        self.table.setColumnHidden(1, True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for b in self._rapidos:
            b.setToolTip("Añadir rápido a la cola")
        compacto.ocultar(self._lbl_rapido, self._b_close)
        i = self._lay.indexOf(self.table) + 1
        compacto.rejilla(self._lay, self._rapidos, 2, i)
        compacto.rejilla(self._lay, self._acciones, 2, i + 1)
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
                if col == 0:
                    it.setToolTip(o["path"])            # (en el panel, la columna del archivo no se ve)
                if col == 2 and j["status"] == "error":
                    it.setToolTip(j.get("error", ""))
                self.table.setItem(i, col, it)
        self.b_run.setText("■ Detener" if self.queue.running else "▶ Exportar todo")
        pending = sum(1 for j in jobs if j["status"] == "pending")
        self.status.setText(f"{len(jobs)} en la lista · {pending} por exportar" if jobs else "La cola está vacía.")
