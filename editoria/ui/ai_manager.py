"""
Análisis de clips en segundo plano: se puede seguir editando mientras la IA
mira los clips, y los resultados aparecen en la biblioteca a medida que llegan.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from ..ai import clip_analysis, embeddings
from ..core.model import KIND_IMAGE, KIND_VIDEO
from .jobs import BackgroundJob


class ClipAnalysisManager(QObject):
    status_changed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.settings = QSettings("EditorIA", "EditorIA")
        self.job: BackgroundJob | None = None
        self.status = ""
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(1500)
        self._auto_timer.timeout.connect(self._auto)
        ctrl.media_changed.connect(self._auto_timer.start)

    @property
    def auto(self) -> bool:
        """Analizar solo los clips nuevos (se activa la primera vez que el usuario analiza)."""
        return str(self.settings.value("ia/analizar_auto", "false")).lower() == "true"

    def models_ready(self) -> bool:
        try:
            return embeddings.is_downloaded("clip_image") and embeddings.is_downloaded("clip_text")
        except Exception:  # noqa: BLE001
            return False

    def pending(self) -> list[str]:
        p = self.ctrl.project
        return [m.id for m in p.media.values()
                if m.kind in (KIND_VIDEO, KIND_IMAGE) and not m.ai_analyzed and m.id not in self.ctrl.missing
                and m.id not in self.ctrl.analyzing and (m.probed or m.kind == KIND_IMAGE)]

    def _auto(self):
        if self.auto and self.job is None and self.pending() and self.models_ready():
            self.analyze()

    def analyze(self, media_ids: list[str] | None = None):
        if self.job is not None:
            return
        ok, why = embeddings.is_available()
        if not ok:
            self._set_status(why)
            return
        ids = media_ids or self.pending()
        if not ids:
            self._set_status("✓ Todos los clips están analizados.")
            return
        self.settings.setValue("ia/analizar_auto", True)
        p = self.ctrl.project
        work_items = [(mid, p.media[mid].path, p.media[mid].kind, p.media[mid].duration) for mid in ids
                      if mid in p.media]

        def work(progress, cancelled, partial):
            clip_analysis.warm_up(progress)
            n = len(work_items)
            failed = 0
            for i, (mid, path, kind, dur) in enumerate(work_items):
                if cancelled():
                    break
                progress(i / n, f"◈ Analizando clips… {i + 1}/{n}")
                try:
                    partial((mid, clip_analysis.analyze_clip(path, kind, dur, None, cancelled)))
                except Exception:  # noqa: BLE001 - un clip roto no detiene el resto
                    failed += 1
            return n, failed

        self.job = BackgroundJob(work, self, with_partial=True)
        self.job.progress.connect(lambda _f, t: self._set_status(t))
        self.job.partial.connect(lambda r: self.ctrl.set_media_ai(*r))
        self.job.done.connect(self._on_done)
        self.job.failed.connect(lambda msg: self._set_status(f"✗ {msg}"))
        self.job.finished.connect(self._on_finished)
        self.busy_changed.emit(True)
        self.job.start()

    def _on_done(self, result):
        n, failed = result
        self._set_status(f"✓ {n - failed} clips analizados" + (f" ({failed} no se pudieron leer)" if failed else ""))

    def _on_finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.busy_changed.emit(False)
        self._auto_timer.start()  # por si se importaron más clips mientras tanto

    def cancel(self):
        if self.job:
            self.job.cancel()

    def shutdown(self):
        job = self.job
        if job is not None and job.isRunning():
            job.cancel()
            if not job.wait(8000):
                job.terminate()
                job.wait(2000)

    def _set_status(self, text: str):
        self.status = text
        self.status_changed.emit(text)
