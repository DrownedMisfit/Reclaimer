"""
✂ Recortar sujeto / quitar el fondo con IA (SAM 2.1): marcas QUÉ es en un fotograma y la IA lo sigue en todo el
clip (o en el tramo I–O), entendiendo su contorno y también su interior (texturas, piezas, detalles).

  Clic izquierdo = esto SÍ (punto verde) · clic derecho = esto NO (punto rojo) · arrastrar = un recuadro.
  👁 Vista previa = cómo queda en este fotograma (unos segundos) · ✂ Recortar = en todo el tramo (en segundo plano).
Quitar el fondo (queda el sujeto, como una pantalla verde) o quitar el sujeto (queda el fondo). Ctrl+Z lo quita.
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from ..core import media as media_tools
from ..core import motor_ia
from ..core import subject_mask as SMK
from ..core.model import new_id


class _Marker(QWidget):
    """El fotograma con las marcas (puntos y recuadro) y, si la hay, la vista previa de la máscara."""
    changed = Signal()

    def __init__(self, rgb: np.ndarray):
        super().__init__()
        h, w = rgb.shape[:2]
        self.img = QImage(np.ascontiguousarray(rgb).data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.points: list[tuple[float, float, int]] = []
        self.box: QRectF | None = None
        self.mask: QImage | None = None
        self._drag = None
        self.setMinimumSize(640, int(640 * h / max(1, w)))
        self.setCursor(Qt.CrossCursor)

    def _rect(self) -> QRectF:
        s = min(self.width() / self.img.width(), self.height() / self.img.height())
        w, h = self.img.width() * s, self.img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _norm(self, pos) -> tuple[float, float]:
        r = self._rect()
        return (min(1.0, max(0.0, (pos.x() - r.left()) / r.width())),
                min(1.0, max(0.0, (pos.y() - r.top()) / r.height())))

    def mousePressEvent(self, e):
        self._drag = (e.button(), self._norm(e.position()), e.position())

    def mouseMoveEvent(self, e):
        if self._drag and self._drag[0] == Qt.LeftButton and (e.position() - self._drag[2]).manhattanLength() > 8:
            (x0, y0), (x1, y1) = self._drag[1], self._norm(e.position())
            self.box = QRectF(QPointF(min(x0, x1), min(y0, y1)), QPointF(max(x0, x1), max(y0, y1)))
            self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if d is None:
            return
        if (e.position() - d[2]).manhattanLength() <= 8:
            x, y = self._norm(e.position())
            self.points.append((x, y, 0 if e.button() == Qt.RightButton else 1))
        self.mask = None
        self.update()
        self.changed.emit()

    def clear(self):
        self.points, self.box, self.mask = [], None, None
        self.update()
        self.changed.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._rect()
        p.drawImage(r, self.img)
        if self.mask is not None:
            p.setOpacity(0.55)
            p.drawImage(r, self.mask)
            p.setOpacity(1.0)
        if self.box is not None:
            p.setPen(QPen(QColor("#5fd8ff"), 2, Qt.DashLine))
            p.drawRect(QRectF(r.left() + self.box.left() * r.width(), r.top() + self.box.top() * r.height(),
                              self.box.width() * r.width(), self.box.height() * r.height()))
        for x, y, lab in self.points:
            c = QPointF(r.left() + x * r.width(), r.top() + y * r.height())
            p.setPen(QPen(QColor("black"), 2))
            p.setBrush(QColor("#3ad16b") if lab else QColor("#e5484d"))
            p.drawEllipse(c, 7, 7)


class SubjectCutDialog(QDialog):
    def __init__(self, ctrl, clip_id: str, t: float, parent=None, fx_mode: bool = False):
        super().__init__(parent)
        self.ctrl, self.clip_id = ctrl, clip_id
        p = ctrl.project
        c = p.clips[clip_id]
        self.m = p.media_of(c)
        local = min(max(t - c.start, 0.0), max(0.0, c.duration - 0.05))
        self.t0 = c.src_at(local)
        self.setWindowTitle("✂ Recortar sujeto con IA")
        lay = QVBoxLayout(self)
        tip = QLabel("Marca QUÉ quieres separar: <b>clic</b> encima = esto sí · <b>clic derecho</b> = esto no · "
                     "<b>arrastrar</b> = un recuadro. La IA (SAM 2.1) entiende su forma y su interior y lo sigue "
                     "en todo el clip aunque se mueva, gire o se tape un momento.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        rgb = media_tools.frame_rgb(self.m.path, self.t0, 960)
        if rgb is None:
            raise RuntimeError("No se pudo leer ese fotograma del video.")
        self.view = _Marker(rgb)
        self.view.changed.connect(self._update_buttons)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.keep = QRadioButton("Quitar el fondo (queda el sujeto, como pantalla verde)")
        self.drop = QRadioButton("Quitar el sujeto (queda el fondo)")
        self.fxonly = QRadioButton("✨ Efecto solo al personaje")
        self.fxonly.setToolTip("Pone una copia del clip ENCIMA recortada al personaje (el original queda debajo): lo que "
                               "le pongas a la copia solo le afecta a él; lo del clip de abajo, solo al fondo.")
        (self.fxonly if fx_mode else self.keep).setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.keep)
        grp.addButton(self.drop)
        grp.addButton(self.fxonly)
        row.addWidget(self.keep)
        row.addWidget(self.drop)
        row.addWidget(self.fxonly)
        row.addStretch(1)
        lay.addLayout(row)
        rowfx = QHBoxLayout()
        rowfx.addWidget(QLabel("Efecto:"))
        self.preset = QComboBox()
        for key, name in ctrl.SUBJECT_FX.items():
            self.preset.addItem(name, key)
        rowfx.addWidget(self.preset, 1)
        lay.addLayout(rowfx)
        self.preset.setEnabled(self.fxonly.isChecked())
        self.fxonly.toggled.connect(self.preset.setEnabled)
        if fx_mode:
            self.setWindowTitle("✨ Efecto solo al personaje")
        row2 = QHBoxLayout()
        self.fine = QCheckBox("Bordes finos (pelo, telas)")
        self.fine.setChecked(True)
        row2.addWidget(self.fine)
        row2.addWidget(QLabel("Calidad:"))
        self.quality = QComboBox()
        self.quality.addItem("Máxima (más lenta)", "max")
        if motor_ia.SAM_FAST_MODEL.exists():
            self.quality.addItem("Rápida (~2× más rápido)", "fast")
        self.quality.setToolTip("Máxima: el modelo grande de SAM 2.1 a 1280 px con bordes finos.\n"
                                "Rápida: el modelo mediano a 854 px (ideal para clips largos o para probar).")
        row2.addWidget(self.quality)
        row2.addWidget(QLabel("Tramo:"))
        self.span = QComboBox()
        self.span.addItem("Todo el clip", "clip")
        rng = p.marked_range()
        if rng and rng[0] < c.end and rng[1] > c.start:
            self.span.addItem("Entre las marcas I – O", "marks")
        row2.addWidget(self.span)
        row2.addStretch(1)
        lay.addLayout(row2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        b_clear = QPushButton("Borrar marcas")
        b_clear.clicked.connect(self.view.clear)
        self.b_prev = QPushButton("👁 Vista previa")
        self.b_prev.clicked.connect(self.preview)
        self.b_go = QPushButton("✂ Recortar")
        self.b_go.setObjectName("primary")
        self.b_go.clicked.connect(self.start)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.reject)
        for b in (b_clear, self.b_prev):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(b_close)
        btns.addWidget(self.b_go)
        lay.addLayout(btns)
        ok, why = motor_ia.available("sam")
        if not ok:
            self.status.setText("✗ " + why)
        self._ok = ok
        self._update_buttons()

    def _update_buttons(self):
        marked = bool(self.view.points or self.view.box)
        self.b_prev.setEnabled(self._ok and marked)
        self.b_go.setEnabled(self._ok and marked)

    def _job(self, mode: str, out: str, a: float = 0.0, b: float = 0.0) -> dict:
        box = self.view.box
        fast = self.quality.currentData() == "fast"
        return {"modo": mode, "ffmpeg": media_tools.ffmpeg(), "video": self.m.path, "a": a, "b": b,
                "t0": self.t0, "fps": float(self.m.fps or 30.0), "salida": out,
                "puntos": [list(pt) for pt in self.view.points],
                "caja": [box.left(), box.top(), box.right(), box.bottom()] if box else None,
                "modelo": str(motor_ia.SAM_FAST_MODEL if fast else motor_ia.SAM_MODEL),
                "config": motor_ia.SAM_FAST_CONFIG if fast else motor_ia.SAM_CONFIG, "ancho": 854 if fast else 1280,
                "bordes": self.fine.isChecked()}

    def preview(self):
        from .task_window import manager
        out = os.path.join(SMK.out_dir(), f"vista_{new_id()}.png")
        job = self._job("imagen", out)
        self.status.setText("👁 Mirando este fotograma con SAM 2.1… (unos segundos)")
        self.b_prev.setEnabled(False)

        def work(progress, cancelled):
            return motor_ia.run("recortar.py", job, progress, cancelled)

        def done(path):
            import cv2
            self._update_buttons()
            m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            try:
                os.remove(path)
            except OSError:
                pass
            if m is None:
                return
            if self.drop.isChecked():
                m = 255 - m
            h, w = m.shape
            rgba = np.zeros((h, w, 4), np.uint8)
            rgba[..., 1] = 210
            rgba[..., 2] = 255
            rgba[..., 3] = (255 - m) * 0.85          # lo que se QUITA, en azul
            self.view.mask = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            self.view.update()
            self.status.setText("👁 En azul, lo que se quitará. Si falta algo, añade un punto verde; si sobra, uno "
                                "rojo. Cuando esté bien: ✂ Recortar.")

        manager().start("👁 Vista previa del recorte", work, done,
                        lambda msg: (self._update_buttons(), self.status.setText("✗ " + msg)))

    def start(self):
        from .task_window import manager
        p = self.ctrl.project
        c = p.clips[self.clip_id]
        a = min(c.src_at(0.0), c.src_at(c.duration))
        b = max(c.src_at(0.0), c.src_at(c.duration))
        if self.span.currentData() == "marks":
            ra, rb = p.marked_range()
            la, lb = max(0.0, ra - c.start), min(c.duration, rb - c.start)
            a, b = min(c.src_at(la), c.src_at(lb)), max(c.src_at(la), c.src_at(lb))
        a, b = max(0.0, a - 0.1), min(self.m.duration or b + 0.1, b + 0.1)
        self.t0 = min(max(self.t0, a), b)
        out = os.path.join(SMK.out_dir(), f"{media_tools.cache_key(self.m.path)}_{new_id()}.mkv")
        job = self._job("video", out, a, b)
        cid, invert, ctrl = self.clip_id, self.drop.isChecked(), self.ctrl
        fx_only, preset = self.fxonly.isChecked(), self.preset.currentData()
        fps = job["fps"]

        def work(progress, cancelled):
            return motor_ia.run("recortar.py", job, progress, cancelled)

        def done(path):
            cc = ctrl.project.clips.get(cid)
            if cc is None:
                return
            if fx_only:            # ✨ copia encima, recortada al personaje, con el efecto elegido
                if ctrl.subject_layer(cid, {"mask": path, "a": round(a, 4), "fps": fps}, preset):
                    ctrl.message.emit("✨ Listo: encima va una copia recortada al personaje. Lo que le pongas a esa "
                                      "copia (Inspector) solo le afecta a él; lo del clip de abajo, al fondo. Ctrl+Z lo quita.")
                return
            fx = dict(cc.fx or {}, subject_mask={"mask": path, "a": round(a, 4), "fps": fps, "invert": invert})
            ctrl.batch_clip_props({cid: {"fx": fx}}, "✂ Recortar sujeto (IA)")
            ctrl.message.emit("✂ Recorte listo: " + ("se quitó el fondo" if not invert else "se quitó el sujeto") +
                              ". Ctrl+Z lo quita · clic derecho → ✨ IA → «Quitar el recorte» también.")

        manager().start("✂ Recortar sujeto (IA)", work, done, lambda msg: ctrl.message.emit("✗ " + msg))
        self.accept()
