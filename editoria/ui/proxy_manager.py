"""Crea en segundo plano las copias ligeras (proxies) que usa el visor con «Media» / «Un cuarto».

Automático: aunque estés en «Completa», se preparan las dos (primero la de la calidad que usas), una detrás de
otra y sin prisa; así, al cambiar a «Media» o «Un cuarto», ya están listas. Se puede apagar en
Reproducción → «Preparar copias ligeras solo»."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from ..core import proxies
from ..core.model import KIND_VIDEO
from .jobs import BackgroundJob


class ProxyManager(QObject):
    status = Signal(str)
    ready = Signal()          # hay copias nuevas: el visor debe recargar

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.settings = QSettings("EditorIA", "EditorIA")
        self.job: BackgroundJob | None = None
        self.level = str(self.settings.value("reproduccion/proxy", "full"))
        if self.level not in proxies.LEVELS:
            self.level = "full"
        self.auto = str(self.settings.value("reproduccion/copias_auto", "true")).lower() == "true"
        import os
        if os.environ.get("EDITORIA_DATOS"):          # pruebas: sin copias que nadie pidió
            self.auto = False
        ctrl.proxy_level = self.level
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.ensure)
        ctrl.media_changed.connect(self._timer.start)      # clips nuevos: también su copia ligera
        ctrl.project_replaced.connect(self._timer.start)

    def set_level(self, level: str):
        self.level = level
        self.ctrl.proxy_level = level
        self.settings.setValue("reproduccion/proxy", level)
        self.ready.emit()
        self.ensure()

    def set_auto(self, on: bool):
        self.auto = on
        self.settings.setValue("reproduccion/copias_auto", "true" if on else "false")
        if on:
            self.ensure()

    def levels(self) -> list[str]:
        """Qué copias hacer: la de la calidad que usas primero; con «automático», también las demás."""
        out = [] if self.level == "full" else [self.level]
        if self.auto:
            out += [lv for lv in ("quarter", "half") if lv not in out]
        return out

    def pending(self) -> list[tuple[str, str, int, float, str]]:
        import os
        p = self.ctrl.project
        gone = [m for m in p.media.values() if m.id not in self.ctrl.missing and not os.path.exists(m.path)]
        if gone:                 # se movió o se borró con Reclaimer abierto: se marca «no encontrado» (y se avisa)
            for m in gone:
                self.ctrl.missing.add(m.id)
            self.ctrl.message.emit(f"⚠️ No se encuentra «{gone[0].name}»" + (f" (y {len(gone) - 1} más)" if len(gone) > 1
                                   else "") + ": ¿se movió o se borró? Clic derecho → volver a enlazar.")
            self.ctrl.media_changed.emit()
        vids = [m for m in p.media.values() if m.kind == KIND_VIDEO and m.probed and m.id not in self.ctrl.missing]
        return [(m.id, m.path, m.height, m.duration, lv) for lv in self.levels() for m in vids
                if not proxies.has_proxy(m.path, lv)]

    def ensure(self):
        if self.job is not None:
            return
        todo = self.pending()
        if not todo:
            return
        label = " y ".join(dict.fromkeys(proxies.LEVELS[t[4]][0].lower() for t in todo))
        # Por video: todas sus copias de UNA pasada (se lee una vez; con la gráfica AMD, ~3× más rápido)
        groups: dict[str, list] = {}
        for mid, path, h, dur, lv in todo:
            groups.setdefault(mid, [path, h, dur, []])[3].append(lv)
        jobs = list(groups.values())
        total_s = sum(max(1.0, j[2] or 1.0) for j in jobs)

        def eta_text(sec: float) -> str:
            if sec < 60:
                return "menos de 1 min"
            return f"~{int(round(sec / 60))} min" if sec < 3600 else f"~{sec / 3600:.1f} h"

        def work(progress, cancelled):
            import time
            done, t0, before = 0, time.time(), 0.0
            for i, (path, h, dur, lvs) in enumerate(jobs):
                if cancelled():
                    break
                w = max(1.0, dur or 1.0)

                def inner(f, i=i, w=w, before=before):
                    frac = (before + f * w) / total_s
                    el = time.time() - t0
                    left = el * (1 - frac) / frac if frac > 0.02 else None
                    progress(frac, f"Copias ligeras {i + 1}/{len(jobs)}"
                                   + (f" · quedan {eta_text(left)}" if left is not None else " · calculando…"))
                inner(0.0)
                done += len(proxies.make_proxies(path, h, lvs, cancelled, inner, dur or 0.0))
                before += w
            return done

        self.job = BackgroundJob(work, self)
        self.job.progress.connect(lambda _f, t: self.status.emit(t))
        self.job.done.connect(lambda n: (self.status.emit(f"✓ {n} copias ligeras listas: la reproducción irá más fluida."),
                                         self.ready.emit()))
        self.job.failed.connect(lambda msg: self.status.emit("✗ Copias ligeras: " + msg))
        self.job.finished.connect(self._finished)
        self.status.emit(f"Creando copias ligeras ({label}) para editar con fluidez"
                         + (" (con la tarjeta gráfica)…" if proxies.hw_encoder() else "…"))
        self.job.start()

    def _finished(self):
        self.job = None
        if self.pending():
            self._timer.start()

    def shutdown(self):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
