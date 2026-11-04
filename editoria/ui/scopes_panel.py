"""
Panel «📊 Gráficas» (los scopes de Resolve): forma de onda, desfile RGB, histograma y vectorscopio del
fotograma que se ve en el cabezal, con su corrección de color. Solo trabaja si el panel está a la vista.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core import scopes
from ..core.model import TRACK_VIDEO
from .help import set_help


class _Signals(QObject):
    done = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            res = self.fn()
        except Exception:  # noqa: BLE001 - una gráfica fallida no debe molestar
            res = None
        try:
            self.signals.done.emit(res)
        except RuntimeError:          # el panel ya se cerró mientras se calculaba: no hay a quién avisar
            pass


class ScopesPanel(QWidget):
    def __init__(self, ctrl, engine, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine = ctrl, engine
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        self.mode = QComboBox()
        for key, name in scopes.MODES.items():
            self.mode.addItem(name, key)
        self.mode.currentIndexChanged.connect(lambda _i: self.schedule(0))
        row.addWidget(QLabel("Ver"))
        row.addWidget(self.mode, 1)
        lay.addLayout(row)
        self.image = QLabel("Pon el cabezal sobre un clip de video o imagen.")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(150)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image.setStyleSheet("background: #101012; border-radius: 4px;")
        lay.addWidget(self.image, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dim")
        lay.addWidget(self.info)
        set_help(self, "graficas")
        self._busy = False
        self._again = False
        self._last_frame = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        engine.time_changed.connect(lambda _t: self.schedule(1000 if engine.playing else 250))
        ctrl.project_changed.connect(lambda: self.schedule(300))

    def schedule(self, ms: int):
        try:
            if self.isVisible() and not (self._timer.isActive() and self._timer.remainingTime() < ms):
                self._timer.start(ms)
        except RuntimeError:          # el panel ya se cerró (al cerrar la ventana llegan avisos rezagados)
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self.schedule(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_last()

    def top_clip(self, t: float):
        """El clip de video/imagen que se ve arriba del todo en t."""
        p = self.ctrl.project
        for tr in p.tracks:                       # la primera pista de video de la lista es la de arriba
            if tr.kind != TRACK_VIDEO or tr.hidden:
                continue
            c = p.clip_at(tr.id, t)
            if c is not None and c.enabled and c.text is None and p.media_of(c) is not None \
                    and p.media_of(c).id not in self.ctrl.missing:
                return c
        return None

    def refresh(self):
        if not self.isVisible():
            return
        if self._busy:
            self._again = True
            return
        t = self.engine.time
        c = self.top_clip(t)
        if c is None:
            self.image.setPixmap(QPixmap())
            self.image.setText("Pon el cabezal sobre un clip de video o imagen.")
            self.info.setText("")
            return
        mode = self.mode.currentData()
        cid, color = c.id, dict(c.color) if c.color else None
        bypass = getattr(self.engine, "color_bypass", False)

        def work():
            from ..core import color as C
            frame = self.ctrl.frame_at(cid, t, 480)
            if frame is None:
                return None
            if color and not bypass and not C.is_neutral(color):
                frame = C.apply_rgb8(frame, color)
            return scopes.render(mode, frame), scopes.warnings(frame)

        self._busy = True
        job = _Job(work)
        job.signals.done.connect(self._done)
        QThreadPool.globalInstance().start(job)

    def _done(self, res):
        self._busy = False
        if res is not None:
            img, warns = res
            self._last_frame = img
            self._show_last()
            self.info.setText("\n".join(warns) if warns else "✓ Sin zonas quemadas ni aplastadas.")
        if self._again:
            self._again = False
            self.schedule(50)

    def _show_last(self):
        img = self._last_frame
        if img is None:
            return
        h, w = img.shape[:2]
        q = QImage(img.data, w, h, w * 3, QImage.Format_RGB888).copy()
        pm = QPixmap.fromImage(q).scaled(self.image.width() - 4, self.image.height() - 4, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation)
        self.image.setPixmap(pm)
