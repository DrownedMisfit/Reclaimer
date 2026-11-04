"""Tareas largas (transcribir, analizar) en segundo plano, sin congelar la ventana."""
from __future__ import annotations

import traceback
from datetime import datetime

import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal

# Cuánto pueden usar del PC los trabajos en segundo plano (panel «◈ Tareas de la IA»):
# full = todo · half = la mitad del tiempo (descansa tanto como trabaja) · quarter = una cuarta parte.
REST = {"full": 0.0, "half": 1.0, "quarter": 3.0}
_level = {"value": None}


def resource_level() -> str:
    if _level["value"] is None:
        from PySide6.QtCore import QSettings
        v = str(QSettings("EditorIA", "EditorIA").value("ia/recursos", "full"))
        _level["value"] = v if v in REST else "full"
    return _level["value"]


def set_resource_level(level: str):
    from PySide6.QtCore import QSettings
    if level in REST:
        _level["value"] = level
        QSettings("EditorIA", "EditorIA").setValue("ia/recursos", level)

from ..ai.base import Cancelled
from ..core.paths import log_path

# Trabajos en marcha: se guardan aquí hasta que terminan DE VERDAD. Así ningún hilo se destruye mientras corre
# (en Qt 6 eso cierra el programa de golpe: «QThread: Destroyed while thread is still running»).
_LIVE: set = set()


def live_jobs() -> list:
    out = []
    for j in list(_LIVE):
        try:
            if j.isRunning():
                out.append(j)
        except RuntimeError:
            _LIVE.discard(j)
    return out


class BackgroundJob(QThread):
    progress = Signal(float, str)
    partial = Signal(object)   # resultados parciales (p. ej. cada clip analizado)
    done = Signal(object)
    failed = Signal(str)

    on_start = None     # aviso al panel de tareas (se pone en ui/task_window.py)

    def __init__(self, fn, parent=None, with_partial: bool = False):
        """fn(progress, cancelled) -> resultado   (o fn(progress, cancelled, partial) si with_partial)
        parent: la ventana a la que pertenece. NO es su «padre» de Qt (si la ventana se cierra, el hilo no se
        destruye a medias): se le pide parar y ya no avisa a nadie; termina solo, sin cierre inesperado."""
        super().__init__(None)
        self._orphaned = False
        if parent is not None:
            try:
                parent.destroyed.connect(self._orphan)
            except (AttributeError, RuntimeError):
                pass
        self.finished.connect(self._release, Qt.QueuedConnection)
        self._fn = fn
        self._with_partial = with_partial
        self._cancel = False
        self._mark = time.monotonic()
        self.title = ""

    def _orphan(self, *_a):
        """Su ventana se cerró: que pare y que no avise a nadie (sus avisos irían a algo ya borrado)."""
        self._orphaned = True
        self._cancel = True

    def _release(self):
        QTimer.singleShot(0, lambda j=self: _LIVE.discard(j))

    def _emit(self, sig, *args):
        if not self._orphaned:
            sig.emit(*args)

    def start(self, *args):
        lvl = resource_level()
        _LIVE.add(self)
        super().start(*args)
        if lvl != "full":
            self.setPriority(QThread.LowPriority if lvl == "half" else QThread.LowestPriority)
        if BackgroundJob.on_start is not None:
            try:
                BackgroundJob.on_start(self)
            except Exception:  # noqa: BLE001 - el panel de tareas nunca debe romper un trabajo
                pass

    def _rest(self):
        """«Media» / «Un cuarto»: el trabajo descansa entre paso y paso para no quitarle potencia al editor."""
        k = REST.get(resource_level(), 0.0)
        now = time.monotonic()
        worked = now - self._mark
        if k > 0 and worked > 0.02:
            end = now + min(2.0, worked * k)
            while not self._cancel and time.monotonic() < end:
                time.sleep(0.02)
        self._mark = time.monotonic()

    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        if not self._cancel:
            self._rest()
        return self._cancel

    def run(self):
        try:
            def prog(f, t):
                self._rest()
                self._emit(self.progress, float(f), t)
            if self._with_partial:
                result = self._fn(prog, self.is_cancelled, lambda x: self._emit(self.partial, x))
            else:
                result = self._fn(prog, self.is_cancelled)
        except Cancelled:
            self._emit(self.failed, "Cancelado.")
        except Exception as exc:  # noqa: BLE001 - se informa al usuario y se registra
            try:
                with open(log_path(), "a", encoding="utf-8") as f:
                    f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} (tarea) ===\n{traceback.format_exc()}")
            except OSError:
                pass
            self._emit(self.failed, str(exc) or exc.__class__.__name__)
        else:
            self._emit(self.done, result)
