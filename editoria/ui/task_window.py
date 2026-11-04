"""
Trabajos largos de la IA (cargar un modelo, calcular huellas, analizar…) SIN ventanas que tapen: van en segundo
plano y se ven en un indicador discreto con contorno naranja en la barra de encima del visor (junto a «Huecos»):
qué está haciendo, una barra del 0 al 100 % y «■» para detenerlo cuando quieras. Solo aparece mientras hay
algo en marcha. Al detener, el trabajo se para en cuanto puede y su hilo sigue vivo hasta terminar de verdad
(así nunca hay un cierre inesperado).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton, QWidget

from .jobs import BackgroundJob

_ALIVE: set = set()


def _running(job) -> bool:
    """¿Sigue en marcha? (False si el trabajo ya terminó y Qt lo borró: nunca un error por eso)."""
    try:
        return bool(job.isRunning())
    except RuntimeError:
        return False      # trabajos que siguen corriendo aunque ya no interesen (detenidos)


class Task:
    def __init__(self, title: str):
        self.title, self.text, self.frac = title, title, 0.0
        self.job: BackgroundJob | None = None
        self.stopped = False
        self.auto = False


class TaskManager(QObject):
    changed = Signal()
    open_panel = Signal()

    def __init__(self):
        super().__init__()
        self.tasks: list[Task] = []
        self.history: list[tuple[str, str]] = []     # (tarea, cómo acabó) — las últimas
        BackgroundJob.on_start = self._adopt

    def _adopt(self, job: BackgroundJob):
        """Cualquier trabajo largo del programa aparece aquí (si dura más de un segundo)."""
        if getattr(job, "_task", None) is not None:
            return
        task = Task("")
        task.job, task.auto = job, True
        job._task = task
        from PySide6.QtCore import QTimer

        def progress(f, text):
            task.frac = max(0.0, min(1.0, float(f)))
            if text:
                task.text = text
                task.title = task.title or text
            if task in self.tasks:
                self.changed.emit()

        def show():
            if not _running(job) or task.stopped or task in self.tasks:
                return
            if True:
                task.title = task.title or task.text or "Trabajando…"
                task.text = task.text or task.title
                self.tasks.append(task)
                self.changed.emit()

        def end(how):
            if task in self.tasks:
                self.history.append((task.title, how))
                del self.history[:-6]
            self._remove(task)
        job.progress.connect(progress)
        job.done.connect(lambda _r: end("✓ terminado"))
        job.failed.connect(lambda m: end("■ detenido" if task.stopped or "ancelad" in m else "✗ " + m[:60]))
        job.finished.connect(lambda: end("✓ terminado"))
        QTimer.singleShot(1000, show)

    def start(self, title: str, fn, on_done=None, on_fail=None) -> Task:
        """fn(progress, cancelled) -> resultado, en segundo plano. on_done(resultado) / on_fail(mensaje)."""
        task = Task(title)
        job = BackgroundJob(fn)                 # sin padre: no se destruye con ninguna ventana
        job._task = task
        task.job = job
        _ALIVE.add(job)
        job.finished.connect(lambda j=job: _ALIVE.discard(j))

        def progress(f, text):
            if not task.stopped:
                task.frac, task.text = max(0.0, min(1.0, float(f))), text or task.text
                self.changed.emit()

        def done(res):
            if task in self.tasks:
                self.history.append((task.title, "✓ terminado"))
            self._remove(task)
            if not task.stopped and on_done:
                on_done(res)

        def failed(msg):
            if task in self.tasks:
                self.history.append((task.title, "✗ " + msg[:60]))
            self._remove(task)
            if on_fail:
                on_fail("Detenido." if task.stopped else msg)
        job.progress.connect(progress)
        job.done.connect(done)
        job.failed.connect(failed)
        self.tasks.append(task)
        job.start()
        self.changed.emit()
        return task

    def stop(self, task: Task | None = None):
        """Detiene ese trabajo (o el último que lanzaste tú; si no hay, el último automático).
        Se avisa al momento con on_fail("Detenido.")."""
        if task is None:
            mine = [t for t in self.tasks if not t.auto]
            task = (mine or self.tasks or [None])[-1]
        if task is None or task.stopped:
            return
        task.stopped = True
        try:
            task.job.cancel()
        except RuntimeError:          # el trabajo ya terminó y se borró
            self._remove(task)
            return
        self.history.append((task.title, "■ detenido"))
        del self.history[:-6]
        self._remove(task)
        if not getattr(task, "auto", False):
            try:
                task.job.failed.emit("Detenido.")  # avisa ya (el hilo acabará solo, sin esperar)
            except RuntimeError:
                pass
        if task.job not in _ALIVE and _running(task.job):
            _ALIVE.add(task.job)
            task.job.finished.connect(lambda j=task.job: _ALIVE.discard(j))

    def _remove(self, task: Task):
        if task in self.tasks:
            self.tasks.remove(task)
            self.changed.emit()


_MANAGER: TaskManager | None = None


def manager() -> TaskManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = TaskManager()
    return _MANAGER


class TaskChip(QFrame):
    """El indicador de la barra del visor: «◈ qué hace · 45 %», mini barra y ■ (detener)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskchip")
        self.setStyleSheet("#taskchip { border: 1px solid #e8742f; border-radius: 5px; background: rgba(232,116,47,0.08); }"
                           "#taskchip QLabel { color: #f2c7a8; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 1, 3, 1)
        lay.setSpacing(6)
        self.label = QLabel("")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(70, 6)
        self.bar.setStyleSheet("QProgressBar { background: #2a2b2f; border: none; border-radius: 3px; }"
                               "QProgressBar::chunk { background: #e8742f; border-radius: 3px; }")
        self.stop = QToolButton()
        self.stop.setText("■")
        self.stop.setToolTip("Detener")
        self.stop.setAutoRaise(True)
        self._shown = None
        self.stop.clicked.connect(lambda: manager().stop(self._shown))
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        lay.addWidget(self.stop)
        self.setCursor(Qt.PointingHandCursor)
        manager().changed.connect(self.refresh)
        self.refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            manager().open_panel.emit()       # abre el panel «◈ Tareas de la IA»
        super().mousePressEvent(e)

    def refresh(self):
        tasks = manager().tasks
        if not tasks:
            self.hide()
            return
        # Primero lo que lanzaste tú; si no, el trabajo automático que ya dice qué hace
        mine = [x for x in tasks if not x.auto]
        named = [x for x in tasks if x.auto and x.text and x.text != "Trabajando…"]
        t = (mine or named or tasks)[-1]
        self._shown = t
        pct = int(round(t.frac * 100))
        extra = f" (+{len(tasks) - 1})" if len(tasks) > 1 else ""
        text = t.text if len(t.text) <= 46 else t.text[:45] + "…"
        self.label.setText(f"{text} · {pct} %{extra}")
        self.bar.setValue(pct)
        self.setToolTip("\n".join(f"{x.title}: {int(x.frac * 100)} %" for x in tasks)
                        + "\nClic = ver las tareas y cuánto pueden usar del PC · ■ = detener la última")
        self.show()


def run_task(_parent, title: str, fn) -> tuple[bool, object]:
    """Versión que espera (sin congelar el editor): (True, resultado) o (False, None) si se detuvo/falló."""
    from PySide6.QtCore import QEventLoop
    loop = QEventLoop()
    out = {"ok": False, "res": None}

    def done(res):
        out.update(ok=True, res=res)
        loop.quit()
    manager().start(title, fn, done, lambda _m: loop.quit())
    loop.exec()
    return out["ok"], out["res"]


class TasksPanel(QWidget):
    """Panel «◈ Tareas de la IA» (se puede soltar y arrastrar a donde quieras; vuelve a su sitio al
    arrastrarlo de vuelta o con doble clic en su título): cuánto puede usar del PC y cada trabajo en marcha."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup, QGroupBox, QRadioButton, QVBoxLayout
        from .jobs import resource_level, set_resource_level
        lay = QVBoxLayout(self)
        g = QGroupBox("Cuánto puede usar la IA del PC")
        gl = QVBoxLayout(g)
        self.levels = QButtonGroup(self)
        for key, text, tip in (("full", "Completa", "Lo más rápido posible."),
                               ("half", "Media", "Trabaja la mitad del tiempo y en prioridad baja: el editor va "
                                                 "más fluido mientras analiza."),
                               ("quarter", "Un cuarto", "Muy tranquila: tarda bastante más, pero casi no se nota "
                                                        "mientras editas.")):
            rb = QRadioButton(f"{text} — {tip}")
            rb.setProperty("level", key)
            rb.setChecked(resource_level() == key)
            self.levels.addButton(rb)
            gl.addWidget(rb)
        self.levels.buttonClicked.connect(lambda b: set_resource_level(b.property("level")))
        lay.addWidget(g)
        self.box = QVBoxLayout()
        lay.addLayout(self.box)
        self.empty = QLabel("No hay nada en marcha.")
        self.empty.setObjectName("dim")
        lay.addWidget(self.empty)
        self.hist = QLabel("")
        self.hist.setObjectName("dim")
        self.hist.setWordWrap(True)
        lay.addWidget(self.hist)
        lay.addStretch(1)
        self._rows: dict = {}
        manager().changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        from PySide6.QtWidgets import QPushButton
        tasks = list(manager().tasks)
        for t in list(self._rows):
            if t not in tasks:
                w = self._rows.pop(t)
                w.setParent(None)
                w.deleteLater()
        for t in tasks:
            row = self._rows.get(t)
            if row is None:
                row = QFrame()
                row.setObjectName("taskchip")
                row.setStyleSheet("#taskchip { border: 1px solid #e8742f; border-radius: 6px; }")
                rl = QHBoxLayout(row)
                row.lab = QLabel()
                row.lab.setWordWrap(True)
                row.bar = QProgressBar()
                row.bar.setRange(0, 100)
                row.bar.setFixedWidth(110)
                b = QPushButton("■ Detener")
                b.clicked.connect(lambda _=False, tt=t: manager().stop(tt))
                rl.addWidget(row.lab, 1)
                rl.addWidget(row.bar)
                rl.addWidget(b)
                self.box.addWidget(row)
                self._rows[t] = row
            row.lab.setText(f"<b>{t.title}</b><br>{t.text}" if t.text != t.title else f"<b>{t.title}</b>")
            row.bar.setValue(int(round(t.frac * 100)))
        self.empty.setVisible(not tasks)
        h = manager().history
        self.hist.setText("Últimas: " + " · ".join(f"{a} ({b})" for a, b in h[-4:]) if h else "")


def stop_all(wait_ms: int = 3000):
    """Al cerrar Reclaimer: pide a todos los trabajos en segundo plano que paren y espera un poco a que lo
    hagan (así el programa se cierra limpio, sin dejar nada funcionando)."""
    import time
    from .jobs import live_jobs
    jobs = set(_ALIVE) | {t.job for t in manager().tasks if t.job is not None} | set(live_jobs())
    for t in list(manager().tasks):
        t.stopped = True
    for j in jobs:
        try:
            j.cancel()
        except RuntimeError:
            pass
    end = time.monotonic() + wait_ms / 1000
    for j in jobs:
        try:
            left = int(max(0.0, end - time.monotonic()) * 1000)
            if j.isRunning():
                j.wait(left)
        except RuntimeError:
            pass
    return [j for j in live_jobs()]      # los que aún no acabaron (casi nunca)
