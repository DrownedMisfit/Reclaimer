"""Ventana «Seguir personaje u objeto»: marcas qué seguir y la IA crea un zoom que lo acompaña."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..ai import tracking
from ..core import transform
from .common import fmt_time
from .jobs import BackgroundJob

ZOOMS = [("Automático (encaja el objeto)", None), ("130 %", 1.3), ("150 %", 1.5), ("200 %", 2.0), ("300 %", 3.0)]
SPANS = [("Hasta el final del clip", None), ("5 segundos", 5.0), ("10 segundos", 10.0), ("20 segundos", 20.0)]


class FrameSelector(QWidget):
    """Muestra el fotograma; se arrastra para dibujar el recuadro. Las caras detectadas se pueden pulsar."""
    box_changed = Signal()

    def __init__(self, image: QImage):
        super().__init__()
        self.image = image
        self.box: QRectF | None = None     # en proporciones 0–1
        self.faces: list[QRectF] = []
        self._from: QPointF | None = None
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    def _rect(self) -> QRectF:
        """Zona donde se dibuja la imagen (manteniendo proporciones)."""
        iw, ih = self.image.width(), self.image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_norm(self, p: QPointF) -> QPointF:
        r = self._rect()
        return QPointF(min(max((p.x() - r.left()) / r.width(), 0), 1), min(max((p.y() - r.top()) / r.height(), 0), 1))

    def _to_view(self, b: QRectF) -> QRectF:
        r = self._rect()
        return QRectF(r.left() + b.x() * r.width(), r.top() + b.y() * r.height(), b.width() * r.width(),
                      b.height() * r.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111316"))
        p.drawImage(self._rect(), self.image)
        p.setRenderHint(QPainter.Antialiasing)
        for f in self.faces:
            p.setPen(QPen(QColor("#39c5cf"), 2, Qt.DashLine))
            p.drawRect(self._to_view(f))
        if self.box is not None:
            p.setPen(QPen(QColor("#ffd166"), 3))
            p.drawRect(self._to_view(self.box))
            p.setPen(QColor("#ffd166"))
            p.drawText(self._to_view(self.box).topLeft() + QPointF(4, -6), "Seguir esto")
        p.end()

    def mousePressEvent(self, e):
        n = self._to_norm(e.position())
        for f in self.faces:  # clic sobre una cara detectada = elegirla
            if f.contains(n):
                self.box = QRectF(f)
                self.box_changed.emit()
                self.update()
                return
        self._from = n

    def mouseMoveEvent(self, e):
        if self._from is not None:
            self.box = QRectF(self._from, self._to_norm(e.position())).normalized()
            self.update()

    def mouseReleaseEvent(self, _e):
        if self._from is not None and self.box is not None and (self.box.width() < 0.01 or self.box.height() < 0.01):
            self.box = None
        self._from = None
        self.box_changed.emit()
        self.update()


class TrackingDialog(QDialog):
    def __init__(self, ctrl, clip_id: str, t: float, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.clip_id = clip_id
        self.setWindowTitle("🎯 Seguir personaje u objeto")
        self.job: BackgroundJob | None = None
        c = ctrl.project.clips[clip_id]
        self.media = ctrl.project.media_of(c)
        self.src_t = ctrl.clip_source_time(clip_id, t)
        frame = tracking.grab_frame(self.media.path, self.src_t, 960, self.media.width, self.media.height)
        if frame is None:
            raise RuntimeError("No se pudo leer el fotograma.")
        self._frame = frame
        img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_BGR888).copy()

        info = QLabel(f"Dibuja un recuadro alrededor de lo que quieres seguir (personaje, cara, arma, enemigo…). "
                      f"Se empezará en {fmt_time(t)} y el zoom lo acompañará.")
        info.setWordWrap(True)
        self.selector = FrameSelector(img)
        self.selector.box_changed.connect(self._update_buttons)
        self.btn_faces = QPushButton("👤 Detectar caras")
        self.btn_faces.setToolTip("Busca caras en el fotograma: luego haz clic en la que quieras seguir.")
        self.btn_faces.clicked.connect(self._detect_faces)
        self.zoom = QComboBox()
        for label, _v in ZOOMS:
            self.zoom.addItem(label)
        self.span = QComboBox()
        for label, _v in SPANS:
            self.span.addItem(label)
        self.ease = QCheckBox("Entrada suave (acercarse poco a poco)")
        self.ease.setChecked(True)
        p = ctrl.project
        self.vertical = QCheckBox("📱 Sin zoom: llenar la pantalla vertical y que el encuadre lo siga")
        self.vertical.setToolTip("Para Shorts y edits: el clip horizontal llena la pantalla (recortando los lados) "
                                 "y el recorte acompaña a lo que marques.")
        self.vertical.setVisible(p.height > p.width and self.media.width > self.media.height * 1.1)
        self.vertical.toggled.connect(lambda on: (self.zoom.setEnabled(not on), self.ease.setEnabled(not on)))
        form = QFormLayout()
        form.addRow("Zoom", self.zoom)
        form.addRow("Seguir", self.span)
        form.addRow(self.ease)
        form.addRow(self.vertical)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = QLabel()
        self.status.setObjectName("dim")
        self.btn_go = QPushButton("🎯 Seguir")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._start)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self._cancel)
        row = QHBoxLayout()
        row.addWidget(self.btn_faces)
        row.addStretch()
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_go)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.selector, 1)
        lay.addLayout(form)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.resize(1000, 760)
        self._update_buttons()

    def _update_buttons(self):
        self.btn_go.setEnabled(self.selector.box is not None and self.job is None)
        if self.selector.box is None and self.job is None:
            self.status.setText("Arrastra con el ratón sobre la imagen para marcar qué seguir.")
        elif self.job is None:
            self.status.setText("Listo. Pulsa «Seguir».")

    def _detect_faces(self):
        try:
            faces = tracking.detect_faces(self._frame)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Caras", f"No se pudo usar el detector de caras:\n{exc}")
            return
        self.selector.faces = [QRectF(x, y, w, h) for x, y, w, h, _c in faces]
        if not faces:
            self.status.setText("No se encontró ninguna cara: dibuja tú el recuadro.")
        elif len(faces) == 1:
            self.selector.box = QRectF(self.selector.faces[0])
            self.status.setText("1 cara encontrada y elegida. Pulsa «Seguir».")
        else:
            self.status.setText(f"{len(faces)} caras encontradas: haz clic en la que quieras seguir.")
        self.selector.update()
        self._update_buttons()

    def _start(self):
        b = self.selector.box
        if b is None:
            return
        c = self.ctrl.project.clips[self.clip_id]
        m = self.media
        clip_end_src = c.source_in + c.src_len
        span = SPANS[self.span.currentIndex()][1]
        end = min(clip_end_src, self.src_t + span) if span else clip_end_src
        zoom = ZOOMS[self.zoom.currentIndex()][1]
        ease_from = self.src_t - 0.6 if self.ease.isChecked() and self.src_t - 0.6 >= c.source_in else None
        start, box = self.src_t, (b.x(), b.y(), b.width(), b.height())

        def work(progress, cancelled):
            samples = tracking.track(m.path, start, end, box, m.width, m.height, progress=progress,
                                     cancelled=cancelled)
            return samples

        self.job = BackgroundJob(work, self)
        self.job.progress.connect(lambda f, t: (self.progress.setValue(int(f * 1000)), self.status.setText(t)))
        vertical = self.vertical.isChecked() and not self.vertical.isHidden()
        self.job.done.connect(lambda s: self._apply_vertical(s) if vertical else self._apply(s, zoom, ease_from, end))
        self.job.failed.connect(lambda msg: self.status.setText(f"✗ {msg}"))
        self.job.finished.connect(self._finished)
        self.progress.setVisible(True)
        self.btn_go.setEnabled(False)
        self.job.start()

    def _apply(self, samples, zoom, ease_from, end):
        if len(samples) < 3:
            QMessageBox.warning(self, "Seguir", "Se perdió el objeto casi al empezar. Prueba con un recuadro "
                                                "más ajustado o en otro momento del clip.")
            return
        kf = tracking.follow_keyframes(samples, zoom=zoom, ease_in_from=ease_from)
        c = self.ctrl.project.clips[self.clip_id]
        before = [k for k in c.zoom_kf if k["t"] < (ease_from if ease_from is not None else samples[0][0]) - 0.05]
        after = [k for k in c.zoom_kf if k["t"] > samples[-1][0] + 0.05]
        merged = transform.sorted_kf(before + kf + after)
        self.ctrl.set_zoom_keyframes(self.clip_id, merged, "IA · Seguir objeto", origin_ai=True)
        lost_early = samples[-1][0] < end - 0.6
        msg = (f"✓ Seguimiento aplicado ({len(kf)} fotogramas clave). "
               + (f"Se perdió el objeto en el segundo {samples[-1][0] - c.source_in + c.start:.1f} de la timeline."
                  if lost_early else "Se siguió hasta el final."))
        self.ctrl.message.emit(msg)
        self.accept()

    def _apply_vertical(self, samples):
        """📱 El recorte vertical acompaña a lo que marcaste (sin zoom); fuera de ese tramo, lo que ya hubiera."""
        from ..ai import reframe
        if len(samples) < 3:
            QMessageBox.warning(self, "Seguir", "Se perdió el objeto casi al empezar. Prueba con un recuadro "
                                                "más ajustado o en otro momento del clip.")
            return
        p = self.ctrl.project
        c = p.clips[self.clip_id]
        box = c.layout or {"w": 1.0, "h": 1.0}
        aspect = (box.get("w", 1.0) * p.width) / max(1e-6, box.get("h", 1.0) * p.height)
        kf = reframe.from_samples(samples, self.media.width, self.media.height, aspect)
        old = (c.layout or {}).get("follow") or []
        merged = sorted([k for k in old if k["t"] < samples[0][0] - 0.05 or k["t"] > samples[-1][0] + 0.05] + kf,
                        key=lambda k: k["t"])
        self.ctrl.set_follow(self.clip_id, merged, "🎯 Encuadre vertical que sigue el objeto")
        self.ctrl.message.emit("📱 El encuadre vertical sigue lo que marcaste.")
        self.accept()

    def _finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.progress.setVisible(False)
        self._update_buttons()

    def _cancel(self):
        if self.job is not None:
            self.job.cancel()
        else:
            self.reject()

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
        super().closeEvent(e)
