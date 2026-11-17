"""Ventana «🎯 Seguimiento» (como el seguimiento de DaVinci Resolve / CapCut / After Effects).

Arriba el fotograma con el recuadro del objeto; debajo una barra para recorrer el clip (verde = seguido, rojo =
dudoso, ◆ amarillo = clave manual). En cualquier fotograma se puede arrastrar o redimensionar el recuadro: eso es una
clave manual (manda sobre lo automático; entre claves se interpola). «Seguir» lo hace solo hacia delante, hacia atrás
o en los dos sentidos desde el fotograma elegido (en segundo plano, cancelable). El recorrido se guarda en el clip y
se usa para: 🔍 zoom que lo sigue, 📱 encuadre vertical, 🙈 desenfocar/pixelar, 📌 pegar otro clip al objeto.
Teclas: ← → un fotograma, Mayús+← → un segundo, Inicio/Fin.
"""
from __future__ import annotations

import atexit
import weakref

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from ..ai import tracking
from ..core import motion_track as MT
from ..core.model import TRACK_AUDIO
from .common import fmt_time
from .jobs import BackgroundJob

ZOOMS = [("Automático (encaja el objeto)", None), ("130 %", 1.3), ("150 %", 1.5), ("200 %", 2.0), ("300 %", 3.0)]
SPANS = [("Hasta el final (o la clave siguiente)", None), ("5 segundos", 5.0), ("10 segundos", 10.0),
         ("20 segundos", 20.0)]
USES = [("zoom", "🔍 Zoom que lo sigue"), ("vertical", "📱 Encuadre vertical que lo sigue"),
        ("blur", "🙈 Desenfocar / pixelar lo seguido"), ("pin", "📌 Pegar un clip de encima al objeto")]
COLORS = {"manual": "#ffd166", "auto": "#39c5cf", "interp": "#c9ced6", "lost": "#ef476f", "none": "#7d838c"}
HANDLE = 7          # radio (px) de las esquinas para redimensionar


class FrameSelector(QWidget):
    """El fotograma con el recuadro: arrastrar dentro = mover, en una esquina = cambiar el tamaño, fuera = dibujar
    otro. Al soltar, box_edited (clave manual). Las caras detectadas se pueden pulsar."""
    box_changed = Signal()
    box_edited = Signal(QRectF)

    def __init__(self, image: QImage):
        super().__init__()
        self.image = image
        self.box: QRectF | None = None     # en proporciones 0–1 (esquina de arriba a la izquierda + tamaño)
        self.state = "none"                # manual / auto / interp / lost / none (color del recuadro)
        self.faces: list[QRectF] = []
        self._drag: dict | None = None
        self.setMinimumSize(560, 315)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setToolTip("Arrastra dentro del recuadro para moverlo, desde una esquina para cambiar su tamaño, o fuera "
                        "para dibujar otro. Cada cambio es una clave manual en este fotograma.")

    def set_image(self, image: QImage):
        self.image = image
        self.update()

    def _rect(self) -> QRectF:
        iw, ih = max(1, self.image.width()), max(1, self.image.height())
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
            col = QColor(COLORS.get(self.state, COLORS["auto"]))
            v = self._to_view(self.box)
            p.setPen(QPen(col, 3 if self.state == "manual" else 2,
                          Qt.DashLine if self.state in ("lost", "none") else Qt.SolidLine))
            p.drawRect(v)
            p.setBrush(col)
            for c in (v.topLeft(), v.topRight(), v.bottomLeft(), v.bottomRight()):
                p.drawEllipse(c, 4, 4)
            p.setBrush(Qt.NoBrush)
            p.drawLine(v.center() + QPointF(-6, 0), v.center() + QPointF(6, 0))
            p.drawLine(v.center() + QPointF(0, -6), v.center() + QPointF(0, 6))
        p.end()

    def _corner_at(self, pos: QPointF) -> int | None:
        if self.box is None:
            return None
        v = self._to_view(self.box)
        for i, c in enumerate((v.topLeft(), v.topRight(), v.bottomLeft(), v.bottomRight())):
            if abs(c.x() - pos.x()) <= HANDLE + 2 and abs(c.y() - pos.y()) <= HANDLE + 2:
                return i
        return None

    def mousePressEvent(self, e):
        n = self._to_norm(e.position())
        for f in self.faces:  # clic sobre una cara detectada = elegirla
            if f.contains(n):
                self.box = QRectF(f)
                self.faces = []
                self.update()
                self.box_changed.emit()
                self.box_edited.emit(QRectF(self.box))
                return
        corner = self._corner_at(e.position())
        if corner is not None:
            self._drag = {"mode": "resize", "corner": corner, "orig": QRectF(self.box)}
        elif self.box is not None and self.box.contains(n):
            self._drag = {"mode": "move", "from": n, "orig": QRectF(self.box)}
        else:
            self._drag = {"mode": "new", "from": n, "orig": QRectF(self.box) if self.box else None}

    def mouseMoveEvent(self, e):
        d = self._drag
        if d is None:
            c = self._corner_at(e.position())
            self.setCursor(Qt.SizeFDiagCursor if c in (0, 3) else Qt.SizeBDiagCursor if c in (1, 2) else
                           Qt.SizeAllCursor if self.box is not None and self.box.contains(self._to_norm(e.position()))
                           else Qt.CrossCursor)
            return
        n = self._to_norm(e.position())
        if d["mode"] == "new":
            self.box = QRectF(d["from"], n).normalized()
        elif d["mode"] == "move":
            o = d["orig"]
            dx = min(max(n.x() - d["from"].x(), -o.left()), 1 - o.right())
            dy = min(max(n.y() - d["from"].y(), -o.top()), 1 - o.bottom())
            self.box = o.translated(dx, dy)
        else:
            o = d["orig"]
            fixed = (o.bottomRight(), o.bottomLeft(), o.topRight(), o.topLeft())[d["corner"]]
            self.box = QRectF(fixed, n).normalized()
        self.update()

    def mouseReleaseEvent(self, _e):
        d, self._drag = self._drag, None
        if d is None:
            return
        if self.box is not None and (self.box.width() < 0.01 or self.box.height() < 0.01):
            self.box = d.get("orig")
            self.update()
            return
        if self.box is not None and self.box != d.get("orig"):
            self.box_changed.emit()
            self.box_edited.emit(QRectF(self.box))
        self.update()


class _Scrub(QWidget):
    """Barra para recorrer el clip: verde = seguido, rojo = dudoso, ◆ = claves manuales, raya blanca = aquí."""
    moved = Signal(float)

    def __init__(self, a: float, b: float):
        super().__init__()
        self.a, self.b = a, max(b, a + 1e-3)
        self.pos = a
        self.runs: list[tuple[float, float]] = []
        self.lost: list[list[float]] = []
        self.keys: list[float] = []
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clic o arrastrar para ir a otro fotograma. Verde: seguido · rojo: dudoso (no se usa) · "
                        "◆ amarillo: clave manual")

    def _x(self, t: float) -> float:
        return 8 + (self.width() - 16) * (t - self.a) / (self.b - self.a)

    def _t(self, x: float) -> float:
        return self.a + (self.b - self.a) * min(max((x - 8) / max(1, self.width() - 16), 0.0), 1.0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y0, h = 10, 12
        p.fillRect(QRectF(8, y0, self.width() - 16, h), QColor("#2a2e35"))
        for a, b in self.runs:
            p.fillRect(QRectF(self._x(a), y0, max(2.0, self._x(b) - self._x(a)), h), QColor("#3fb68b"))
        for a, b in self.lost:
            p.fillRect(QRectF(self._x(a), y0, max(2.0, self._x(b) - self._x(a)), h), QColor(COLORS["lost"]))
        p.setPen(QPen(QColor("#1b1d21"), 1))
        p.setBrush(QColor(COLORS["manual"]))
        for t in self.keys:
            x = self._x(t)
            p.drawPolygon(QPolygonF([QPointF(x, y0 - 4), QPointF(x + 5, y0 + h / 2), QPointF(x, y0 + h + 4),
                                     QPointF(x - 5, y0 + h / 2)]))
        x = self._x(self.pos)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(QPointF(x, 2), QPointF(x, self.height() - 2))
        p.end()

    def mousePressEvent(self, e):
        self.moved.emit(self._t(e.position().x()))

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.moved.emit(self._t(e.position().x()))


_OPEN_FRAMES = weakref.WeakSet()


@atexit.register
def _release_all():
    """Al salir: ningún lector de OpenCV abierto (sus hilos de FFmpeg, vivos al cerrar Python, lo tumbaban)."""
    for fr in list(_OPEN_FRAMES):
        try:
            fr.close()
        except Exception:  # noqa: BLE001
            pass


class _Frames:
    """Lee fotogramas sueltos para recorrer el clip (OpenCV sobre la copia ligera si existe; si no, FFmpeg).
    El lector se abre al pedir un fotograma y se suelta solo tras unos segundos sin usarse."""

    def __init__(self, path: str, src_w: int, src_h: int, width: int = 960):
        self.path, self.src_w, self.src_h, self.width = path, src_w, src_h, width
        self.cache: dict[int, QImage] = {}
        self.cap = None
        self._failed = False
        self._idle = QTimer()
        self._idle.setSingleShot(True)
        self._idle.setInterval(3000)
        self._idle.timeout.connect(self.close)
        _OPEN_FRAMES.add(self)

    def _open(self):
        if self.cap is None and not self._failed:
            try:
                import cv2
                cap = cv2.VideoCapture(self.path)
                if cap.isOpened():
                    self.cap = cap
                else:
                    cap.release()
                    self._failed = True
            except Exception:  # noqa: BLE001
                self._failed = True
        self._idle.start()

    def get(self, s: float) -> QImage | None:
        key = int(round(s * 1000))
        img = self.cache.get(key)
        if img is not None:
            return img
        frame = None
        self._open()
        if self.cap is not None:
            import cv2
            self.cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, s) * 1000.0)
            ok, f = self.cap.read()
            if ok and f is not None:
                h, w = f.shape[:2]
                if w > self.width:
                    f = cv2.resize(f, (self.width, max(2, int(round(h * self.width / w)))),
                                   interpolation=cv2.INTER_AREA)
                frame = f
        if frame is None:
            frame = tracking.grab_frame(self.path, s, self.width, self.src_w, self.src_h)
        if frame is None:
            return None
        import numpy as np
        frame = np.ascontiguousarray(frame)
        img = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_BGR888).copy()
        if len(self.cache) > 48:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = img
        return img

    def close(self):
        try:
            self._idle.stop()
        except RuntimeError:
            pass
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def _rect_to_box(r: QRectF) -> tuple[float, float, float, float]:
    return r.x() + r.width() / 2, r.y() + r.height() / 2, r.width(), r.height()


def _box_to_rect(b) -> QRectF:
    cx, cy, w, h = b
    return QRectF(cx - w / 2, cy - h / 2, w, h)


class TrackingDialog(QDialog):
    def __init__(self, ctrl, clip_id: str, t: float, parent=None, use: str | None = None,
                 overlay_id: str | None = None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.clip_id = clip_id
        self.setWindowTitle("🎯 Seguimiento")
        self.job: BackgroundJob | None = None
        self._auto_apply = False
        p = ctrl.project
        c = p.clips[clip_id]
        self.media = p.media_of(c)
        if self.media is None or self.media.kind != "video":
            raise RuntimeError("El seguimiento es para clips de video.")
        m = self.media
        self.a, self.b = sorted((c.src_at(0.0), c.src_at(c.duration)))
        self.step_s = 1.0 / float(m.fps or p.fps or 30.0)
        self.s = min(max(ctrl.clip_source_time(clip_id, t), self.a), self.b)
        self.src_t = self.s
        self.frames = _Frames(ctrl.preview_path(m, 960), m.width, m.height)
        img = self.frames.get(self.s)
        if img is None:
            raise RuntimeError("No se pudo leer el fotograma.")
        # Recorridos: los del clip (copias de trabajo); se guardan al usar uno o al cerrar
        self.tracks = [dict(x) for x in MT.tracks_of(c)]
        self.dirty: set[str] = set()
        if not self.tracks:
            self.tracks = [MT.new_track(MT.unique_name(c))]
        self.trk = self.tracks[-1]
        self._pts = None

        self.selector = FrameSelector(img)
        self.selector.box_edited.connect(self._on_box_edited)
        self.selector.box_changed.connect(self._update_buttons)
        self.scrub = _Scrub(self.a, self.b)
        self.scrub.moved.connect(self.seek)

        def btn(text, tip, fn, w=None):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            if w:
                b.setFixedWidth(w)
            return b
        self.time_label = QLabel()
        self.time_label.setMinimumWidth(150)
        self.state_label = QLabel()
        self.state_label.setObjectName("dim")
        nav = QHBoxLayout()
        nav.addWidget(btn("⏮", "Al principio del clip (Inicio)", lambda: self.seek(self.a), 34))
        nav.addWidget(btn("◀", "Un fotograma atrás (←; Mayús+←: un segundo)", lambda: self.step(-1), 34))
        nav.addWidget(self.time_label)
        nav.addWidget(btn("▶", "Un fotograma adelante (→; Mayús+→: un segundo)", lambda: self.step(1), 34))
        nav.addWidget(btn("⏭", "Al final del clip (Fin)", lambda: self.seek(self.b), 34))
        nav.addWidget(self.state_label, 1)
        self.btn_key = btn("◆ Clave", "Clave manual con el recuadro de este fotograma (las claves manuales mandan sobre "
                           "lo automático; entre dos claves, el recuadro va en línea recta)", self.add_key)
        self.btn_unkey = btn("✕ Clave", "Quita la clave manual de este fotograma", self.remove_key)
        self.btn_prev_key = btn("◆◀", "Ir a la clave manual anterior", lambda: self._jump_key(-1), 40)
        self.btn_next_key = btn("▶◆", "Ir a la clave manual siguiente", lambda: self._jump_key(1), 40)
        self.btn_faces = btn("👤 Caras", "Busca caras en este fotograma: luego haz clic en la que quieras seguir.",
                             self._detect_faces)
        for w in (self.btn_prev_key, self.btn_key, self.btn_unkey, self.btn_next_key, self.btn_faces):
            nav.addWidget(w)

        # Recorrido: nombre, suavizado, hasta dónde
        self.track_combo = QComboBox()
        self.track_combo.setToolTip("Recorrido que estás editando (un clip puede tener varios: uno por objeto)")
        self.track_combo.currentIndexChanged.connect(self._on_track_combo)
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip("Nombre del recorrido (así lo eliges luego al pegar algo al objeto)")
        self.name_edit.setFixedWidth(130)
        self.name_edit.editingFinished.connect(self._on_name)
        self.smooth = QSlider(Qt.Horizontal)
        self.smooth.setRange(0, 100)
        self.smooth.setFixedWidth(110)
        self.smooth.setToolTip("Suavizado: quita los temblores de lo seguido automáticamente (las claves manuales "
                               "no se mueven)")
        self.smooth.valueChanged.connect(self._on_smooth)
        self.span = QComboBox()
        for label, _v in SPANS:
            self.span.addItem(label)
        self.span.setToolTip("Hasta dónde seguir (siempre se para antes de una clave manual: allí mandas tú)")
        row_t = QHBoxLayout()
        row_t.addWidget(QLabel("Recorrido"))
        row_t.addWidget(self.track_combo)
        row_t.addWidget(self.name_edit)
        self.btn_new = btn("＋", "Recorrido nuevo (otro objeto del mismo clip)", self._new_track, 30)
        self.btn_del = btn("🗑", "Borrar este recorrido (Ctrl+Z lo devuelve)", self._delete_track, 30)
        row_t.addWidget(self.btn_new)
        row_t.addWidget(self.btn_del)
        row_t.addSpacing(10)
        row_t.addWidget(QLabel("Suavizado"))
        row_t.addWidget(self.smooth)
        row_t.addWidget(self.span)
        row_t.addStretch()

        self.btn_back = btn("◀◀ Seguir hacia atrás", "Sigue el objeto hacia atrás desde este fotograma",
                            lambda: self.track("back"))
        self.btn_both = btn("🎯 Seguir ◀▶", "Sigue el objeto automáticamente hacia delante y hacia atrás desde este "
                            "fotograma (en segundo plano)", lambda: self.track("both"))
        self.btn_both.setObjectName("primary")
        self.btn_fwd = btn("Seguir desde aquí ▶▶", "Sigue el objeto hacia delante desde este fotograma (después de "
                           "corregir el recuadro, vuelve a seguir a partir de la corrección)", lambda: self.track("fwd"))
        self.btn_clear = btn("Borrar lo automático", "Quita todo lo seguido automáticamente (las claves manuales se "
                             "quedan)", self._clear_auto)
        row_go = QHBoxLayout()
        for w in (self.btn_back, self.btn_both, self.btn_fwd):
            row_go.addWidget(w)
        row_go.addStretch()
        row_go.addWidget(self.btn_clear)

        # Usos del recorrido
        self.use_combo = QComboBox()
        for key, label in USES:
            self.use_combo.addItem(label, key)
        self.use_combo.setToolTip("Qué hacer con el recorrido (se puede usar varias veces y para varias cosas)")
        self.opts = QStackedWidget()
        # 🔍 zoom
        wz = QWidget()
        lz = QHBoxLayout(wz)
        lz.setContentsMargins(0, 0, 0, 0)
        self.zoom = QComboBox()
        for label, _v in ZOOMS:
            self.zoom.addItem(label)
        self.zoom.setToolTip("Cuánto se acerca el zoom")
        self.ease = QCheckBox("Entrada suave")
        self.ease.setToolTip("El zoom empieza un poco antes, acercándose poco a poco")
        self.ease.setChecked(True)
        lz.addWidget(self.zoom)
        lz.addWidget(self.ease)
        lz.addStretch()
        # 📱 vertical
        wv = QWidget()
        lv = QHBoxLayout(wv)
        lv.setContentsMargins(0, 0, 0, 0)
        info_v = QLabel("Sin zoom: llena la pantalla vertical")
        info_v.setObjectName("dim")
        info_v.setToolTip("Para Shorts y edits: el clip horizontal llena la pantalla (recortando los lados) y el "
                          "recorte acompaña al objeto.")
        lv.addWidget(info_v)
        lv.addStretch()
        # 🙈 tapar
        wb = QWidget()
        lb = QHBoxLayout(wb)
        lb.setContentsMargins(0, 0, 0, 0)
        self.blur_mode = QComboBox()
        for k, v in MT.MODES.items():
            self.blur_mode.addItem(v, k)
        self.blur_mode.setToolTip("Desenfocar o pixelar (cara, matrícula, pantalla…)")
        self.blur_shape = QComboBox()
        for k, v in MT.SHAPES.items():
            self.blur_shape.addItem(v, k)
        self.blur_shape.setToolTip("Forma de la zona tapada")
        self.blur_amount = QSlider(Qt.Horizontal)
        self.blur_amount.setRange(10, 100)
        self.blur_amount.setValue(75)
        self.blur_amount.setFixedWidth(90)
        self.blur_amount.setToolTip("Fuerza del desenfoque / tamaño de los píxeles")
        self.blur_pad = QSlider(Qt.Horizontal)
        self.blur_pad.setRange(100, 200)
        self.blur_pad.setValue(125)
        self.blur_pad.setFixedWidth(90)
        self.blur_pad.setToolTip("Margen alrededor del objeto (100 % = justo su recuadro)")
        for w in (self.blur_mode, self.blur_shape, QLabel("Fuerza"), self.blur_amount, QLabel("Margen"),
                  self.blur_pad):
            lb.addWidget(w)
        lb.addStretch()
        # 📌 pegar
        wp = QWidget()
        lp = QHBoxLayout(wp)
        lp.setContentsMargins(0, 0, 0, 0)
        self.pin_combo = QComboBox()
        self.pin_combo.setToolTip("El clip que seguirá al objeto (texto, imagen, emoji, flecha, título, video…): "
                                  "conserva el desfase con el que lo colocaste en el cabezal")
        self.pin_combo.setMinimumWidth(220)
        self.pin_scale = QCheckBox("También el tamaño")
        self.pin_scale.setToolTip("Crece y encoge con el objeto (no en los textos)")
        lp.addWidget(self.pin_combo, 1)
        lp.addWidget(self.pin_scale)
        for w in (wz, wv, wb, wp):
            self.opts.addWidget(w)
        self.use_combo.currentIndexChanged.connect(lambda i: self.opts.setCurrentIndex(i))
        self.btn_apply = btn("✓ Aplicar", "Usa el recorrido para lo elegido (un solo Ctrl+Z; luego se puede editar)",
                             self.apply_use)
        self.btn_apply.setObjectName("primary")
        row_u = QHBoxLayout()
        row_u.addWidget(QLabel("Usar"))
        row_u.addWidget(self.use_combo)
        row_u.addWidget(self.opts, 1)
        row_u.addWidget(self.btn_apply)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = QLabel()
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        self.btn_cancel = btn("Cancelar", "Para el seguimiento (se queda lo seguido hasta ahora)", self._cancel)
        self.btn_close = btn("Cerrar", "Guarda el recorrido en el clip y cierra", self.accept)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.selector, 1)
        lay.addWidget(self.scrub)
        lay.addLayout(nav)
        lay.addLayout(row_t)
        lay.addLayout(row_go)
        lay.addLayout(row_u)
        lay.addWidget(self.progress)
        lay.addLayout(row)
        self.resize(1040, 800)

        for keys, fn in (("Left", lambda: self.step(-1)), ("Right", lambda: self.step(1)),
                         ("Shift+Left", lambda: self.step_seconds(-1.0)), ("Shift+Right", lambda: self.step_seconds(1.0)),
                         ("Home", lambda: self.seek(self.a)), ("End", lambda: self.seek(self.b))):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(fn)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(15)
        self._seek_timer.timeout.connect(self._load_frame)

        # Uso de entrada: lo que tenga sentido para este clip / lo que pidió quien abrió la ventana
        self._fill_pin_combo(overlay_id)
        vertical = p.height > p.width and m.width > m.height * 1.1
        start_use = use or ("pin" if overlay_id else ("vertical" if vertical else "zoom"))
        self.use_combo.setCurrentIndex(max(0, [k for k, _l in USES].index(start_use)))
        self._fill_track_combo()
        self.seek(self.s)
        self.selector.setFocus()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_quit)

    # ------------------------------------------------------------------ recorrido de trabajo
    def _points(self):
        if self._pts is None:
            self._pts = MT.points(self.trk)
        return self._pts

    def _changed(self, trk: dict):
        """El recorrido de trabajo cambió (aún sin guardar en el clip)."""
        i = next((k for k, x in enumerate(self.tracks) if x["id"] == trk["id"]), None)
        if i is None:
            self.tracks.append(trk)
        else:
            self.tracks[i] = trk
        self.trk = trk
        self.dirty.add(trk["id"])
        self._pts = None
        self._refresh()

    def _store(self, trk: dict):
        """Un recorrido que no es el que se ve ahora cambió (lo seguido en segundo plano)."""
        self.tracks = [trk if x["id"] == trk["id"] else x for x in self.tracks]
        self.dirty.add(trk["id"])

    def _fill_track_combo(self):
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for x in self.tracks:
            self.track_combo.addItem(x.get("name", "Objeto"), x["id"])
        self.track_combo.setCurrentIndex(max(0, self.track_combo.findData(self.trk["id"])))
        self.track_combo.blockSignals(False)
        self.name_edit.setText(self.trk.get("name", ""))
        self.smooth.blockSignals(True)
        self.smooth.setValue(int(round(float(self.trk.get("smooth", 0.3)) * 100)))
        self.smooth.blockSignals(False)

    def _on_track_combo(self, i: int):
        tid = self.track_combo.itemData(i)
        trk = next((x for x in self.tracks if x["id"] == tid), None)
        if trk is not None:
            self.trk = trk
            self._pts = None
            self._fill_track_combo()
            self._refresh()

    def _on_name(self):
        name = self.name_edit.text().strip()
        if name and name != self.trk.get("name"):
            self._changed(dict(self.trk, name=name))
            self._fill_track_combo()

    def _on_smooth(self, v: int):
        self._changed(dict(self.trk, smooth=v / 100.0))

    def _new_track(self):
        names = {x.get("name") for x in self.tracks}
        n = 1
        while f"Objeto {n}" in names:
            n += 1
        self.trk = MT.new_track(f"Objeto {n}", self.trk.get("fps", 15.0))
        self.tracks.append(self.trk)
        self._pts = None
        self._fill_track_combo()
        self._refresh()
        self.status.setText("Recorrido nuevo: marca el objeto con un recuadro.")

    def _delete_track(self):
        tid = self.trk["id"]
        c = self.ctrl.project.clips.get(self.clip_id)
        if c is not None and MT.find(c, tid) is not None:
            self.ctrl.set_motion_track(self.clip_id, None, tid)
        self.tracks = [x for x in self.tracks if x["id"] != tid]
        self.dirty.discard(tid)
        if not self.tracks:
            self.tracks = [MT.new_track("Objeto 1")]
        self.trk = self.tracks[-1]
        self._pts = None
        self._fill_track_combo()
        self._refresh()

    def _clear_auto(self):
        self._changed(MT.clear_auto(self.trk))

    # ------------------------------------------------------------------ moverse por el clip
    def seek(self, s: float):
        self.s = min(max(float(s), self.a), self.b)
        self._seek_timer.start()
        self._refresh()

    def _load_frame(self):
        img = self.frames.get(self.s)
        if img is not None:
            self.selector.set_image(img)

    def step(self, n: int):
        self.seek(self.s + n * self.step_s)
        self._load_frame()

    def step_seconds(self, sec: float):
        self.seek(self.s + sec)
        self._load_frame()

    def _jump_key(self, direction: int):
        ts = [r[0] for r in self.trk.get("manual") or []]
        tol = MT.tol_of(self.trk)
        cand = [t for t in ts if (t > self.s + tol if direction > 0 else t < self.s - tol)]
        if cand:
            self.seek(min(cand) if direction > 0 else max(cand))
            self._load_frame()

    def _state_here(self) -> str:
        if MT.manual_at(self.trk, self.s) is not None:
            return "manual"
        sp = MT.span(self.trk)
        if sp is None or not (sp[0] - 1e-3 <= self.s <= sp[1] + 1e-3):
            return "none"
        if MT.is_lost(self.trk, self.s):
            return "lost"
        step = 1.0 / MT.fps_of(self.trk)
        if any(abs(r[0] - self.s) <= step for r in self.trk.get("auto") or []):
            return "auto"
        return "interp"

    def _refresh(self):
        pts = self._points()
        b = MT.box_at(self.trk, self.s, pts)
        if self.selector._drag is None:
            self.selector.box = _box_to_rect(b) if b is not None else None
        st = self._state_here()
        self.selector.state = st
        self.selector.update()
        self.time_label.setText(f"{fmt_time(self._timeline_t(self.s))}  ·  fotograma {int(round(self.s / self.step_s))}")
        self.state_label.setText({"manual": "◆ Clave manual", "auto": "Seguido automáticamente",
                                  "interp": "Entre claves (línea recta)", "lost": "⚠ Dudoso: corrige el recuadro",
                                  "none": "Sin recorrido aquí"}[st])
        # Barra: tramos seguidos, dudosos y claves
        gap = 2.5 / MT.fps_of(self.trk)
        runs: list[list[float]] = []
        for t in (r[0] for r in self.trk.get("auto") or []):
            if runs and t - runs[-1][1] <= gap:
                runs[-1][1] = t
            else:
                runs.append([t, t])
        self.scrub.runs = [tuple(r) for r in runs]
        self.scrub.lost = list(self.trk.get("lost") or [])
        self.scrub.keys = [r[0] for r in self.trk.get("manual") or []]
        self.scrub.pos = self.s
        self.scrub.update()
        self._update_buttons()

    def _timeline_t(self, s: float) -> float:
        c = self.ctrl.project.clips.get(self.clip_id)
        if c is None:
            return 0.0
        if c.speed <= 0:
            return c.start
        local = (c.source_in + c.src_len - s) / c.speed if c.reverse else (s - c.source_in) / c.speed
        return c.start + min(max(local, 0.0), c.duration)

    def _update_buttons(self):
        busy = self.job is not None
        has_box = self.selector.box is not None
        for w in (self.btn_back, self.btn_both, self.btn_fwd):
            w.setEnabled(has_box and not busy)
        self.btn_key.setEnabled(has_box and not busy)
        self.btn_unkey.setEnabled(not busy and MT.manual_at(self.trk, self.s) is not None)
        self.btn_apply.setEnabled(not busy and not MT.is_empty(self.trk))
        self.btn_clear.setEnabled(not busy and bool(self.trk.get("auto")))
        self.btn_cancel.setVisible(busy)
        for w in (self.track_combo, self.name_edit, self.selector, self.btn_new, self.btn_del, self.smooth,
                  self.btn_faces):
            w.setEnabled(not busy)
        if not busy and not has_box:
            self.status.setText("Dibuja un recuadro alrededor de lo que quieres seguir (o 👤 Caras).")

    # ------------------------------------------------------------------ claves manuales
    def _on_box_edited(self, r: QRectF):
        self._changed(MT.set_manual(self.trk, self.s, _rect_to_box(r)))
        self.status.setText("◆ Clave manual. «Seguir desde aquí ▶▶» vuelve a seguir a partir de esta corrección.")

    def add_key(self):
        if self.selector.box is not None:
            self._changed(MT.set_manual(self.trk, self.s, _rect_to_box(self.selector.box)))

    def remove_key(self):
        trk, ok = MT.remove_manual(self.trk, self.s)
        if ok:
            self._changed(trk)

    def _detect_faces(self):
        import numpy as np
        img = self.selector.image.convertToFormat(QImage.Format_BGR888)
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
        frame = np.ascontiguousarray(arr[:, :img.width() * 3].reshape(img.height(), img.width(), 3))
        try:
            faces = tracking.detect_faces(frame)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Caras", f"No se pudo usar el detector de caras:\n{exc}")
            return
        self.selector.faces = [QRectF(x, y, w, h) for x, y, w, h, _c in faces]
        if not faces:
            self.status.setText("No se encontró ninguna cara: dibuja tú el recuadro.")
        elif len(faces) == 1:
            self.selector.faces = []
            self._on_box_edited(QRectF(*faces[0][:4]))
            self.status.setText("1 cara encontrada y elegida: pulsa «🎯 Seguir».")
        else:
            self.status.setText(f"{len(faces)} caras encontradas: haz clic en la que quieras seguir.")
        self.selector.update()

    # ------------------------------------------------------------------ seguir automáticamente
    def track(self, direction: str = "both"):
        """Sigue el objeto desde el fotograma actual: "fwd", "back" o "both". Se para antes de una clave manual."""
        r = self.selector.box
        if r is None or self.job is not None:
            return
        box = _rect_to_box(r)
        s0 = self.s
        prev_k, next_k = MT.neighbors(self.trk, s0)
        tol = MT.tol_of(self.trk)
        span = SPANS[self.span.currentIndex()][1]
        plan = []
        if direction in ("fwd", "both") and s0 < self.b - self.step_s / 2:
            end = self.b if next_k is None else next_k - tol
            if span:
                end = min(end, s0 + span)
            if end > s0:
                plan.append((s0, end))
        if direction in ("back", "both") and s0 > self.a + self.step_s / 2:
            end = self.a if prev_k is None else prev_k + tol
            if span:
                end = max(end, s0 - span)
            if end < s0:
                plan.append((s0, end))
        if not plan:
            self.status.setText("No hay nada que seguir en ese sentido (estás en el borde del clip o junto a una clave).")
            return
        m = self.media
        path = self.ctrl.preview_path(m, tracking.WORK_WIDTH)
        fps = MT.fps_of(self.trk)
        holder = {"tid": self.trk["id"], "out": [], "done": False}     # (lo seguido, aunque se cierre la ventana)
        self._holder = holder

        def work(progress, cancelled):
            n = len(plan)
            for i, (a, b) in enumerate(plan):
                def prog(f, txt, i=i):
                    progress((i + f) / n, txt)
                res = tracking.track_auto(path, a, b, box, m.width, m.height, fps, prog, cancelled)
                holder["out"].append((a, b, res))
                if res.get("cancelled"):
                    break
            return holder

        self.job = BackgroundJob(work, self)
        self.job.title = "🎯 Seguimiento"
        self.job.progress.connect(lambda f, t: (self.progress.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(self._on_tracked)
        self.job.failed.connect(lambda msg: self.status.setText(f"✗ {msg}"))
        self.job.finished.connect(self._finished)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.job.start()
        self._update_buttons()

    def _on_tracked(self, holder):
        if holder.get("done"):
            return
        holder["done"] = True
        trk = next((x for x in self.tracks if x["id"] == holder["tid"]), None)
        if trk is None:                     # (el recorrido se borró mientras tanto)
            return
        msgs = []
        for a, b, res in holder["out"]:
            reached = res.get("end", b)
            if res.get("cancelled") or res.get("stopped"):
                b = reached              # (lo que queda sin seguir conserva lo que hubiera)
            trk = MT.replace_auto(trk, a, b, res.get("samples") or [], res.get("lost") or [])
            sentido = "hacia atrás" if b < a else "hacia delante"
            if res.get("stopped"):
                msgs.append(f"⚠ {sentido}: se perdió en {fmt_time(self._timeline_t(reached))} (corrige el recuadro allí "
                            "y «Seguir desde aquí»)")
            elif res.get("lost"):
                msgs.append(f"{sentido}: {len(res['lost'])} tramo(s) dudoso(s) en rojo (recuperado)")
            if res.get("cancelled"):
                msgs.append("cancelado: se guarda lo seguido hasta ahí")
        if trk["id"] == self.trk["id"]:
            self._changed(trk)
        else:
            self._store(trk)
        self.status.setText(("✓ Seguido. " + " · ".join(msgs)) if msgs else
                            "✓ Seguido. Revisa con ← → y corrige si hace falta; luego «✓ Aplicar».")
        if self._auto_apply:
            self._auto_apply = False
            if len(MT.sample(self.trk, self.a, self.b)) < 3:
                QMessageBox.warning(self, "Seguir", "Se perdió el objeto casi al empezar. Prueba con un recuadro "
                                                    "más ajustado o en otro momento del clip.")
                return
            self.apply_use()

    def _finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.progress.setVisible(False)
        self._update_buttons()

    def _start(self):
        """Seguir hacia delante desde aquí con el recuadro marcado y aplicar el uso elegido (atajo de siempre)."""
        if self.selector.box is None:
            return
        if MT.manual_at(self.trk, self.s) is None:
            self._changed(MT.set_manual(self.trk, self.s, _rect_to_box(self.selector.box)))
        self._auto_apply = True
        self.track("fwd")

    # ------------------------------------------------------------------ usos
    def _fill_pin_combo(self, prefer: str | None = None):
        p = self.ctrl.project
        c = p.clips[self.clip_id]
        self.pin_combo.clear()
        linked = set(self.ctrl.linked_ids([c.id]))
        cands = [o for o in p.clips.values() if o.id not in linked and o.start < c.end - 0.01 and o.end > c.start + 0.01
                 and p.track(o.track_id) is not None and p.track(o.track_id).kind != TRACK_AUDIO]
        cands.sort(key=lambda o: (p.track_index(o.track_id), o.start))
        for o in cands:
            if o.text is not None:
                name = "🅣 " + str(o.text.get("content", "Texto")).replace("\n", " ")[:28]
            else:
                mo = p.media_of(o)
                name = ("🖼 " if mo and mo.kind == "image" else "🎬 ") + (mo.name if mo else "clip")[:28]
            self.pin_combo.addItem(f"{name}  ·  {p.track(o.track_id).name}  ·  {fmt_time(o.start)}", o.id)
        if prefer:
            self.pin_combo.setCurrentIndex(max(0, self.pin_combo.findData(prefer)))
        if not cands:
            self.pin_combo.addItem("(no hay clips encima en ese momento)", None)

    def apply_use(self):
        """Guarda el recorrido y lo usa para lo elegido: todo en un paso de Ctrl+Z."""
        key = self.use_combo.currentData()
        save = MT.clean(self.trk)
        tid = save["id"]
        if key == "zoom":
            ok = self.ctrl.track_zoom(self.clip_id, tid, ZOOMS[self.zoom.currentIndex()][1], self.ease.isChecked(),
                                      save=save)
            msg = "🔍 El zoom sigue al objeto."
        elif key == "vertical":
            ok = self.ctrl.track_vertical(self.clip_id, tid, save=save)
            msg = "📱 El encuadre vertical sigue al objeto."
        elif key == "blur":
            ok = self.ctrl.track_blur(self.clip_id, tid, self.blur_shape.currentData(), self.blur_mode.currentData(),
                                      self.blur_amount.value() / 100.0, self.blur_pad.value() / 100.0, save=save)
            msg = "🙈 Lo seguido queda tapado (visor y exportación)."
        else:
            oid = self.pin_combo.currentData()
            if not oid:
                self.status.setText("No hay ningún clip encima para pegar: pon un texto o una imagen sobre el video.")
                return None
            ref = self._timeline_t(self.s)
            eng = getattr(self.parent(), "engine", None)
            oc = self.ctrl.project.clips.get(oid)
            if eng is not None and oc is not None and oc.start <= eng.time <= oc.end:
                ref = eng.time               # (el desfase: como lo ves en el cabezal)
            ok = self.ctrl.pin_to_track(oid, self.clip_id, tid, ref, self.pin_scale.isChecked(), save=save)
            msg = "📌 El clip sigue al objeto (mantiene su desfase)."
        if ok is not None:
            self.dirty.discard(tid)
            self.ctrl.message.emit(msg)
            self.status.setText("✓ " + msg + " Ctrl+Z lo deshace.")
        return ok

    # ------------------------------------------------------------------ cerrar
    def _save_pending(self):
        """Los recorridos cambiados, en el clip: todos en un solo paso de Ctrl+Z."""
        trks = [MT.clean(x) for x in self.tracks if x["id"] in self.dirty and not MT.is_empty(x)]
        self.dirty.clear()
        if trks and self.clip_id in self.ctrl.project.clips:
            self.ctrl.set_motion_tracks(self.clip_id, trks, "🎯 Recorrido" + ("s" if len(trks) > 1 else "") +
                                        " del seguimiento")

    def _cancel(self):
        if self.job is not None:
            self.job.cancel()
        else:
            self.reject()

    def _stop_job(self):
        """Para el seguimiento, espera a que el hilo termine y se queda con lo seguido hasta ahí."""
        job = self.job
        if job is not None:
            self._auto_apply = False
            job.cancel()
            job.wait(15000)
            holder = getattr(self, "_holder", None)
            if holder is not None and not holder.get("done"):
                self._on_tracked(holder)
            self._finished()

    def done(self, r: int):
        """Cerrar (con «Cerrar», Esc o la X): lo seguido se guarda en el clip (Ctrl+Z lo quita)."""
        self._stop_job()
        self._save_pending()
        self.frames.close()
        super().done(r)

    def _on_quit(self):
        """La aplicación se cierra con la ventana abierta: nada de hilos ni lectores huérfanos."""
        try:
            self._stop_job()
            self.frames.close()
        except RuntimeError:
            pass

    def hideEvent(self, e):
        self.frames.close()
        super().hideEvent(e)

    def closeEvent(self, e):
        self._stop_job()
        super().closeEvent(e)
