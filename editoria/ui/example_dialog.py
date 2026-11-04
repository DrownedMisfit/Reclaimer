"""
Ventana «🎯 Ejemplo de lo que busco»: enseñas a la IA un clip o una imagen tuya.

Eliges el momento exacto donde se ve (tira de fotogramas o barra de tiempo), si quieres dibujas un RECUADRO
sobre lo que buscas (una roca, una cara, un logo… así no se fija en el fondo) y escribes qué es.
«✓ Esto es» / «✗ Esto NO es» guardan ese ejemplo y la ventana sigue abierta para marcar más momentos;
«🔎 Buscar» busca con todo lo marcado; «✓ Es esto y buscar» hace las dos cosas de una vez.
Encima de la barra de tiempo, «◈ Dónde sale» pinta en naranja los momentos que más se parecen a lo que
escribiste (y a tus ✓/✗), con ◀ ▶ para saltar de uno a otro. Al cambiar de momento, el recuadro se quita
(era de otro fotograma: no confunde a la IA).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from ..core import media as media_tools
from ..core.model import KIND_IMAGE
from . import help as help_ui


class _FrameView(QWidget):
    """El fotograma, con un recuadro opcional que se dibuja arrastrando."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img: np.ndarray | None = None
        self.pix: QPixmap | None = None
        self.rect_n: QRectF | None = None      # recuadro en fracciones (0–1) de la imagen
        self._drag: QPointF | None = None
        self.setMinimumSize(480, 270)
        self.setCursor(Qt.CrossCursor)

    def set_image(self, img: np.ndarray | None):
        self.img = img
        if img is None:
            self.pix = None
        else:
            h, w = img.shape[:2]
            qi = QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_RGB888).copy()
            self.pix = QPixmap.fromImage(qi)
        self.update()

    def _area(self) -> QRectF:
        if self.pix is None:
            return QRectF(self.rect())
        pw, ph = self.pix.width(), self.pix.height()
        k = min(self.width() / pw, self.height() / ph)
        w, h = pw * k, ph * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _norm(self, p: QPointF) -> QPointF:
        a = self._area()
        return QPointF(min(1.0, max(0.0, (p.x() - a.left()) / a.width())),
                       min(1.0, max(0.0, (p.y() - a.top()) / a.height())))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.pix is not None:
            self._drag = self._norm(e.position())
            self.rect_n = None
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            q = self._norm(e.position())
            self.rect_n = QRectF(self._drag, q).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            if self.rect_n is not None and (self.rect_n.width() < 0.03 or self.rect_n.height() < 0.03):
                self.rect_n = None      # un clic suelto quita el recuadro
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111"))
        if self.pix is None:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "Cargando…")
            return
        a = self._area()
        p.drawPixmap(a, self.pix, QRectF(self.pix.rect()))
        if self.rect_n is not None:
            r = QRectF(a.left() + self.rect_n.left() * a.width(), a.top() + self.rect_n.top() * a.height(),
                       self.rect_n.width() * a.width(), self.rect_n.height() * a.height())
            p.fillRect(QRectF(a.left(), a.top(), a.width(), r.top() - a.top()), QColor(0, 0, 0, 120))
            p.fillRect(QRectF(a.left(), r.bottom(), a.width(), a.bottom() - r.bottom()), QColor(0, 0, 0, 120))
            p.fillRect(QRectF(a.left(), r.top(), r.left() - a.left(), r.height()), QColor(0, 0, 0, 120))
            p.fillRect(QRectF(r.right(), r.top(), a.right() - r.right(), r.height()), QColor(0, 0, 0, 120))
            p.setPen(QPen(QColor("#f2a03d"), 2))
            p.drawRect(r)

    def crop(self) -> np.ndarray | None:
        if self.img is None:
            return None
        if self.rect_n is None:
            return self.img
        h, w = self.img.shape[:2]
        x0, y0 = int(self.rect_n.left() * w), int(self.rect_n.top() * h)
        x1, y1 = max(x0 + 8, int(self.rect_n.right() * w)), max(y0 + 8, int(self.rect_n.bottom() * h))
        return self.img[y0:y1, x0:x1]


class _Filmstrip(QWidget):
    """Tira de fotogramas del clip: clic = ir a ese momento. Marca dónde estás y tus ✓/✗.
    Varios fotogramas: Ctrl+clic (añadir/quitar), Mayús+clic (un tramo) o el modo «Varios fotogramas»."""
    picked = Signal(float)
    selection_changed = Signal()

    def __init__(self, t_min: float, t_max: float, parent=None):
        super().__init__(parent)
        self.t_min, self.t_max = t_min, t_max
        self.frames: list[tuple[float, QPixmap]] = []
        self.current = t_min
        self.marks: list[tuple[float, bool]] = []
        self.selected: set[int] = set()      # índices de fotogramas seleccionados
        self.multi = False                   # modo «Varios fotogramas»: el clic normal también selecciona
        self._anchor: int | None = None
        self.level = None                    # t -> 0..1 (cuánto se parece a lo que buscas), o None
        self.setFixedHeight(70)
        self.setCursor(Qt.PointingHandCursor)

    def selected_times(self) -> list[float]:
        return [self.frames[i][0] for i in sorted(self.selected) if i < len(self.frames)]

    def set_all(self, on: bool):
        self.selected = set(range(len(self.frames))) if on else set()
        self.update()
        self.selection_changed.emit()

    def add_frame(self, t: float, img: np.ndarray):
        h, w = img.shape[:2]
        qi = QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.frames.append((t, QPixmap.fromImage(qi)))
        self.frames.sort(key=lambda x: x[0])
        self.update()

    def _x(self, t: float) -> float:
        span = max(1e-6, self.t_max - self.t_min)
        return (t - self.t_min) / span * self.width()

    def mousePressEvent(self, e):
        span = self.t_max - self.t_min
        frac = min(1.0, max(0.0, e.position().x() / max(1, self.width())))
        if self.frames:
            i = min(len(self.frames) - 1, int(frac * len(self.frames)))
            mods = e.modifiers()
            if mods & Qt.ShiftModifier and self._anchor is not None:
                a, b = sorted((self._anchor, i))
                self.selected |= set(range(a, b + 1))
            elif mods & Qt.ControlModifier or self.multi:
                self.selected ^= {i}
                self._anchor = i
            else:
                self.selected.clear()
                self._anchor = i
            self.selection_changed.emit()
            self.update()
            self.picked.emit(self.frames[i][0])
            return
        self.picked.emit(self.t_min + frac * span)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111"))
        n = max(1, len(self.frames))
        w = self.width() / n
        for i, (_t, pix) in enumerate(self.frames):
            r = QRectF(i * w, 0, w - 2, self.height() - 8)
            p.drawPixmap(r, pix, QRectF(pix.rect()))
            if i in self.selected:
                p.fillRect(r, QColor(242, 160, 61, 60))
                p.setPen(QPen(QColor("#f2a03d"), 3))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))
                p.setPen(QColor("white"))
                p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignTop | Qt.AlignRight, "✔")
            lv = self.level(_t) if self.level else 0.0
            if lv >= 0.15:      # cuánto se parece este fotograma a lo que buscas (franja naranja arriba)
                p.fillRect(QRectF(r.left(), r.top(), r.width() * lv, 4), QColor(232, 116, 47, int(120 + 135 * lv)))
        if not self.frames:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "Cargando fotogramas…")
        for t, good in self.marks:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5fd18b") if good else QColor("#e5413c"))
            p.drawEllipse(QPointF(self._x(t), self.height() - 5), 4, 4)
        x = self._x(self.current)
        p.setPen(QPen(QColor("#f2a03d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height() - 8))


class _MatchBar(QWidget):
    """«◈ Dónde sale»: naranja = se parece a lo que buscas (más intenso = más parecido); ▲ = sitios más
    probables. Clic = ir ahí."""
    picked = Signal(float)

    def __init__(self, t_min: float, t_max: float, parent=None):
        super().__init__(parent)
        self.t_min, self.t_max = t_min, t_max
        self.times: np.ndarray | None = None
        self.levels: np.ndarray | None = None
        self.peaks: list[float] = []
        self.current = t_min
        self.busy = False
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)

    def _x(self, t: float) -> float:
        return (t - self.t_min) / max(1e-6, self.t_max - self.t_min) * self.width()

    def mousePressEvent(self, e):
        frac = min(1.0, max(0.0, e.position().x() / max(1, self.width())))
        self.picked.emit(self.t_min + frac * (self.t_max - self.t_min))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b1c20"))
        h = self.height()
        if self.times is not None and len(self.times):
            ts = list(self.times)
            for k, (t, lv) in enumerate(zip(ts, self.levels)):
                a = (ts[k - 1] + t) / 2 if k else self.t_min
                b = (t + ts[k + 1]) / 2 if k + 1 < len(ts) else self.t_max
                if lv >= 0.12:
                    p.fillRect(QRectF(self._x(a), 0, max(1.0, self._x(b) - self._x(a)), h),
                               QColor(232, 116, 47, int(40 + 215 * float(lv))))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            for t in self.peaks:
                x = self._x(t)
                p.drawPolygon([QPointF(x - 4, h), QPointF(x + 4, h), QPointF(x, h - 6)])
        elif self.busy:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "◈ buscando en el clip…")
        x = self._x(self.current)
        p.setPen(QPen(QColor("#f2a03d"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))


def square_224(img: np.ndarray) -> np.ndarray:
    """La imagen (o el recorte) en un cuadrado de 224 sin deformar, con relleno gris (para la IA)."""
    import cv2
    h, w = img.shape[:2]
    s = max(h, w)
    canvas = np.full((s, s, 3), 114, np.uint8)
    canvas[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = img
    return cv2.resize(canvas, (224, 224), interpolation=cv2.INTER_AREA)


class ExampleDialog(QDialog):
    """examples: los ejemplos guardados [{"good", "name", "key", "vec", "media_id", "t"}] (on_example se llama
    con cada uno al momento) · do_search: si pulsaste «🔎 Buscar» o «✓ Es esto y buscar»."""

    def __init__(self, ctrl, media_id: str, t: float, t_min: float = 0.0, t_max: float | None = None,
                 name: str = "", parent=None, on_example=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.m = ctrl.project.media[media_id]
        self.is_image = self.m.kind == KIND_IMAGE
        self.t_min = 0.0 if self.is_image else max(0.0, t_min)
        self.t_max = 0.0 if self.is_image else max(self.t_min, min(t_max if t_max is not None else self.m.duration,
                                                                   self.m.duration - 0.05))
        self.t = 0.0 if self.is_image else min(max(t, self.t_min), self.t_max)
        self.result: dict | None = None
        self.examples: list[dict] = []
        self.do_search = False
        self.on_example = on_example
        self._strip_job = None
        self.setWindowTitle("🎯 Ejemplo de lo que busco")
        self.resize(820, 720)
        help_ui.set_help(self, "momentos")
        lay = QVBoxLayout(self)
        tip = QLabel("Elige el momento donde se ve bien lo que buscas. Si hay más cosas en la imagen, "
                     "<b>arrastra un recuadro</b> sobre lo que buscas (clic suelto = quitarlo).")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.view = _FrameView()
        lay.addWidget(self.view, 1)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(self.t_min * 10), int(self.t_max * 10))
        self.slider.setValue(int(self.t * 10))
        self.slider.valueChanged.connect(self._slide)
        self.t_label = QLabel("")
        self.match = _MatchBar(self.t_min, self.t_max)
        self.match.current = self.t
        self.match.picked.connect(lambda tt: self.slider.setValue(int(round(tt * 10))))
        self.match.setToolTip("◈ Dónde sale: en naranja, los momentos de este clip que más se parecen a lo que "
                              "escribiste en «¿Qué es?» (y a tus ✓). Clic = ir ahí · ◀ ▶ = el anterior / siguiente.")
        self.b_prev = QPushButton("◀")
        self.b_prev.setToolTip("Ir al sitio parecido anterior")
        self.b_prev.clicked.connect(lambda: self._jump(-1))
        self.b_next = QPushButton("▶")
        self.b_next.setToolTip("Ir al siguiente sitio donde parece que sale")
        self.b_next.clicked.connect(lambda: self._jump(1))
        self.match_label = QLabel("◈ Dónde sale")
        self.match_label.setObjectName("dim")
        for b in (self.b_prev, self.b_next):
            b.setFixedWidth(30)
            b.setEnabled(False)
        srow = QHBoxLayout()
        bars = QVBoxLayout()            # «Dónde sale» justo encima de la barra de tiempo, del mismo ancho
        bars.setSpacing(1)
        bars.addWidget(self.match)
        bars.addWidget(self.slider)
        srow.addLayout(bars, 1)
        srow.addWidget(self.t_label)
        lay.addLayout(srow)
        self.strip = _Filmstrip(self.t_min, self.t_max)
        self.strip.current = self.t
        self.strip.picked.connect(lambda tt: self.slider.setValue(int(round(tt * 10))))
        self.strip.selection_changed.connect(self._sel_changed)
        lay.addWidget(self.strip)
        mrow = QHBoxLayout()
        self.multi = QCheckBox("Varios fotogramas")
        self.multi.setToolTip("Con esto marcado, cada clic en la tira selecciona o quita un fotograma. "
                              "Sin marcarlo: Ctrl+clic añade/quita y Mayús+clic selecciona un tramo.")
        self.multi.toggled.connect(lambda on: setattr(self.strip, "multi", on))
        self.b_all = QPushButton("Todos")
        self.b_all.setObjectName("flat")
        self.b_all.clicked.connect(lambda: self.strip.set_all(True))
        self.b_none = QPushButton("Ninguno")
        self.b_none.setObjectName("flat")
        self.b_none.clicked.connect(lambda: self.strip.set_all(False))
        self.sel_label = QLabel("Ctrl+clic o Mayús+clic en la tira para elegir varios fotogramas.")
        self.sel_label.setObjectName("dim")
        mrow.addWidget(self.multi)
        mrow.addWidget(self.b_all)
        mrow.addWidget(self.b_none)
        mrow.addWidget(self.sel_label, 1)
        mrow.addWidget(self.match_label)
        mrow.addWidget(self.b_prev)
        mrow.addWidget(self.b_next)
        lay.addLayout(mrow)
        self.has_strip = not self.is_image and self.t_max - self.t_min > 0.2
        for w in (self.slider, self.t_label, self.strip, self.multi, self.b_all, self.b_none, self.sel_label,
                  self.match, self.match_label, self.b_prev, self.b_next):
            w.setVisible(self.has_strip)
        self.strip.level = self._level_at
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("¿Qué es?"))
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Ej.: Jefe Maestro, una roca, el logo de Xbox…")
        nrow.addWidget(self.name, 1)
        lay.addLayout(nrow)
        self.msg = QLabel("")
        self.msg.setObjectName("dim")
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        cancel = QPushButton("Cerrar")
        cancel.clicked.connect(self.reject)
        self.b_no = QPushButton("✗ Esto NO es")
        self.b_no.setToolTip("Guarda este momento como ejemplo de lo que NO es (para que no lo confunda). "
                             "La ventana sigue abierta para marcar más.")
        self.b_no.clicked.connect(lambda: self._done(False))
        self.b_yes = QPushButton("✓ Esto es")
        self.b_yes.setToolTip("Guarda este momento como ejemplo de lo que buscas. La ventana sigue abierta: "
                              "elige otro momento para enseñarle más.")
        self.b_yes.clicked.connect(lambda: self._done(True))
        self.b_search = QPushButton("🔎 Buscar")
        self.b_search.setToolTip("Busca en todos tus medios con los ejemplos que marcaste.")
        self.b_search.clicked.connect(self._search)
        self.b_both = QPushButton("✓ Es esto y buscar")
        self.b_both.setObjectName("primary")
        self.b_both.setToolTip("Guarda este momento como ✓ y busca ya.")
        self.b_both.clicked.connect(lambda: self._done(True, search=True))
        btns.addWidget(cancel)
        btns.addStretch(1)
        btns.addWidget(self.b_no)
        btns.addWidget(self.b_yes)
        btns.addWidget(self.b_search)
        btns.addWidget(self.b_both)
        lay.addLayout(btns)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._load)
        self._fv = None            # (tiempos, huellas) de los fotogramas del clip, para «Dónde sale»
        self._qvecs: dict = {}     # texto -> vector (calculado una vez)
        self._match_task = None
        self._match_again = False
        self._closed = False
        self._mtimer = QTimer(self)
        self._mtimer.setSingleShot(True)
        self._mtimer.setInterval(900)
        self._mtimer.timeout.connect(self._update_match)
        self.name.textChanged.connect(lambda _t: self._mtimer.start() if self.has_strip else None)
        self._load()
        self.name.setFocus()
        if self.has_strip:
            self._load_strip()
            if self.name.text().strip():
                self._mtimer.start()

    def _load_strip(self, n: int = 12):
        """Los fotogramas de la tira, en segundo plano (no congela la ventana)."""
        from .jobs import BackgroundJob
        span = self.t_max - self.t_min
        n = max(2, min(n, int(span / 0.4) + 1))
        times = [self.t_min + span * (i + 0.5) / n for i in range(n)]
        path = self.m.path

        def work(_progress, cancelled, partial):
            for tt in times:
                if cancelled():
                    break
                img = media_tools.frame_rgb(path, tt, 192)
                if img is not None:
                    partial((tt, img))
            return True
        self._strip_job = BackgroundJob(work, self, with_partial=True)
        self._strip_job.partial.connect(lambda x: self.strip.add_frame(*x))
        self._strip_job.start()

    # ------------------------------------------------------------------ ◈ Dónde sale
    def _index_frames(self):
        """Las huellas del análisis que ya hiciste (si cubren este tramo): instantáneo."""
        tv = self.ctrl.clip_vecs.get(self.m.id)
        if tv is None or not len(tv[0]):
            return None
        times = np.asarray(tv[0], np.float32)
        keep = (times >= self.t_min - 0.5) & (times <= self.t_max + 0.5)
        if keep.sum() < 3:
            return None
        return times[keep], np.asarray(tv[1], np.float32)[keep]

    def _update_match(self):
        """Recalcula dónde sale. Lo pesado (huellas, texto) va en segundo plano; luego es solo numpy."""
        if self._closed or not self.has_strip:
            return
        query = self.name.text().strip()
        if not query and not any(e["good"] for e in self.examples):
            self.match.times = self.match.levels = None
            self.match.peaks = []
            self._show_match()
            return
        if self._fv is None:
            self._fv = self._index_frames()
        need_frames = self._fv is None
        need_text = bool(query) and query not in self._qvecs
        if not need_frames and not need_text:
            self._apply_match()
            return
        if self._match_task is not None:          # ya hay uno: se repite al acabar
            self._match_again = True
            return
        from ..ai import embeddings
        if (need_text and not embeddings.is_downloaded("clip_text")) or \
                (need_frames and not embeddings.is_downloaded("clip_image")):
            # nunca descarga por su cuenta: solo si ya tienes la IA de imágenes
            self.match_label.setText("◈ Dónde sale (activa la IA de imágenes en Medios → ◈)")
            if need_frames or not any(e["good"] for e in self.examples):
                return
        if not need_frames and need_text and not embeddings.is_downloaded("clip_text"):
            self._apply_match()           # sin texto: con tus ✓ basta
            return
        span = self.t_max - self.t_min
        n = int(max(8, min(90, span / 1.0)))
        times = [self.t_min + span * (i + 0.5) / n for i in range(n)] if need_frames else []
        path = self.m.path

        def work(progress, cancelled):
            from ..ai import embeddings
            from ..ai.base import Cancelled
            out = {}
            if need_text:
                enc_t = embeddings.get("clip_text")
                v = enc_t.encode([query, f"una imagen de {query}", f"{query} en un video"]).mean(0)
                out["q"] = v / (np.linalg.norm(v) + 1e-9)
            if times:
                progress(0.05, "◈ Preparando la IA…")
                enc = embeddings.get("clip_image")
                ts, vs = [], []
                for i, tt in enumerate(times):
                    if cancelled():
                        raise Cancelled()
                    progress(0.1 + 0.9 * i / len(times), f"◈ Buscando «{query[:24]}» en el clip")
                    img = media_tools.frame_rgb(path, tt, 320)
                    if img is not None:
                        ts.append(tt)
                        vs.append(enc.encode(square_224(img)[None])[0])
                out["frames"] = (np.asarray(ts, np.float32), np.asarray(vs, np.float32))
            return out

        def done(res):
            self._match_task = None
            if self._closed:
                return
            if "q" in res:
                self._qvecs[query] = res["q"]
            if "frames" in res and len(res["frames"][0]) >= 2:
                self._fv = res["frames"]
            self.match.busy = False
            if self._match_again:
                self._match_again = False
                self._update_match()
            else:
                self._apply_match()

        def failed(_msg):
            self._match_task = None
            if not self._closed:
                self.match.busy = False
                self.match_label.setText("◈ Dónde sale")
                self.match.update()
        from .task_window import manager
        self.match.busy = True
        self.match_label.setText("◈ Buscando…")
        self.match.update()
        self._match_task = manager().start(f"◈ Buscando «{query[:24]}» en el clip", work, done, failed)

    def _apply_match(self):
        from ..ai import frame_match
        if self._fv is None:
            return
        query = self.name.text().strip()
        pos = [e["vec"] for e in self.examples if e["good"] and e["name"].lower() == query.lower()]
        neg = [e["vec"] for e in self.examples if not e["good"] and e["name"].lower() == query.lower()]
        times, vecs = self._fv
        q = self._qvecs.get(query) if query else None
        if q is None and not pos:
            return
        lv = frame_match.curve(vecs, q, np.asarray(pos) if pos else None, np.asarray(neg) if neg else None)
        self.match.times, self.match.levels = times, lv
        self.match.peaks = frame_match.peaks(times, lv)
        self._show_match()

    def _show_match(self):
        n = len(self.match.peaks)
        self.match_label.setText(f"◈ Dónde sale ({n})" if self.match.times is not None else "◈ Dónde sale")
        for b in (self.b_prev, self.b_next):
            b.setEnabled(n > 0)
        self.match.update()
        self.strip.update()

    def _level_at(self, t: float) -> float:
        from ..ai import frame_match
        if self.match.times is None:
            return 0.0
        return frame_match.level_at(self.match.times, self.match.levels, t)

    def _jump(self, direction: int):
        pk = self.match.peaks
        if not pk:
            return
        if direction > 0:
            nxt = next((t for t in pk if t > self.t + 0.2), pk[0])          # al final, vuelve al primero
        else:
            nxt = next((t for t in reversed(pk) if t < self.t - 0.2), pk[-1])
        self.slider.setValue(int(round(nxt * 10)))

    def done(self, r):
        self._closed = True
        self._mtimer.stop()
        if self._match_task is not None:
            from .task_window import manager
            manager().stop(self._match_task)
            self._match_task = None
        if self._strip_job is not None:
            self._strip_job.cancel()
            self._strip_job.wait(3000)
            self._strip_job = None
        super().done(r)

    def _slide(self, v: int):
        self.t = v / 10
        self.strip.current = self.t
        self.strip.update()
        self.match.current = self.t
        self.match.update()
        if self.view.rect_n is not None:     # el recuadro era de otro fotograma: fuera (no confunde a la IA)
            self.view.rect_n = None
            self.view.update()
        self._timer.start()

    def _load(self):
        self.t_label.setText(f"{int(self.t // 60)}:{self.t % 60:04.1f}")
        if self.is_image:
            import cv2
            data = np.fromfile(self.m.path, np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR) if len(data) else None
            if img is not None:
                h, w = img.shape[:2]
                k = min(1.0, 960 / max(h, w))
                img = cv2.cvtColor(cv2.resize(img, (int(w * k), int(h * k))), cv2.COLOR_BGR2RGB)
        else:
            img = media_tools.frame_rgb(self.m.path, self.t, 960)
        self.view.set_image(img)

    def key(self) -> str:
        base = media_tools.cache_key(self.m.path)
        k = base if self.is_image else f"{base}@{round(self.t, 1)}"
        r = self.view.rect_n
        if r is not None:
            k += f"#{r.left():.2f},{r.top():.2f},{r.width():.2f},{r.height():.2f}"
        return k

    def _index_vec(self, t: float):
        """La huella ya guardada del análisis (instantánea), o None si ese momento no está analizado."""
        tv = self.ctrl.clip_vecs.get(self.m.id)
        if tv is not None and len(tv[0]):
            times = np.asarray(tv[0], np.float32)
            k = int(np.argmin(np.abs(times - t)))
            if abs(float(times[k]) - t) <= 1.0 or self.is_image:
                return np.asarray(tv[1][k], np.float32)
        return None

    def vector(self) -> np.ndarray | None:
        """Huella del momento que ves (usada por las pruebas): la del índice o, si hace falta calcularla, en
        la ventana de progreso."""
        vecs = self._compute([self._spec_current()])
        return vecs[0] if vecs else None

    def _spec_current(self) -> dict:
        if self.view.rect_n is None:
            v = self._index_vec(self.t)
            if v is not None:
                return {"t": self.t, "key": self.key(), "vec": v}
        img = self.view.crop()
        return {"t": self.t, "key": self.key(), "crop": None if img is None else np.ascontiguousarray(img).copy()}

    @staticmethod
    def _work(path: str, specs: list[dict]):
        def work(progress, cancelled):
            from ..ai import embeddings
            from ..ai.base import Cancelled
            progress(0.02, "◈ Preparando la IA…")
            enc = embeddings.get("clip_image", lambda f, t: progress(0.02 + 0.5 * f, "◈ Preparando la IA…"))
            out = []
            n = len(specs)
            for i, sp in enumerate(specs):
                if cancelled():
                    raise Cancelled()
                progress(0.55 + 0.45 * i / n, f"🎯 Mirando el ejemplo {i + 1} de {n}")
                if "vec" in sp:
                    out.append(sp["vec"])
                    continue
                img = sp.get("crop")
                if img is None:
                    img = media_tools.frame_rgb(path, sp["t"], 480)
                out.append(None if img is None else enc.encode(square_224(img)[None])[0])
            progress(1.0, "Listo")
            return out
        return work

    def _compute(self, specs: list[dict]) -> list | None:
        """(Para quien necesite esperar el resultado.) Lo que no está en el índice se calcula en segundo
        plano; el progreso se ve en la barra de encima del visor."""
        if all("vec" in sp for sp in specs):
            return [sp["vec"] for sp in specs]
        from .task_window import run_task
        ok, res = run_task(self, "🎯 Preparando el ejemplo", self._work(self.m.path, specs))
        return res if ok else None

    def _sel_changed(self):
        n = len(self.strip.selected)
        self.sel_label.setText(f"{n} fotogramas seleccionados: ✓ / ✗ guardan un ejemplo por cada uno." if n > 1 else
                               ("1 fotograma seleccionado." if n == 1 else
                                "Ctrl+clic o Mayús+clic en la tira para elegir varios fotogramas."))

    def _search(self):
        if not self.name.text().strip():
            self.msg.setText("Escribe qué es (así la IA lo busca y lo aprende con ese nombre).")
            from .nudge import nudge
            nudge(self.name)
            return
        self.do_search = True
        self.accept()

    def _done(self, good: bool, search: bool = False):
        name = self.name.text().strip()
        if not name:
            self.msg.setText("Escribe qué es (así la IA lo aprende con ese nombre).")
            from .nudge import nudge
            nudge(self.name)
            return
        times = self.strip.selected_times() if self.has_strip else []
        base = media_tools.cache_key(self.m.path)
        if len(times) > 1 or (len(times) == 1 and abs(times[0] - self.t) > 0.05):
            # varios fotogramas: un ejemplo por cada uno (el recuadro solo vale para el que estás viendo)
            specs = []
            for tt in times:
                if abs(tt - self.t) <= 0.05:
                    specs.append(self._spec_current())
                else:
                    v = self._index_vec(tt)
                    sp = {"t": tt, "key": f"{base}@{round(tt, 1)}"}
                    if v is not None:
                        sp["vec"] = v
                    specs.append(sp)
        else:
            specs = [self._spec_current()]
        if all("vec" in sp for sp in specs):
            self._finish(good, name, specs, [sp["vec"] for sp in specs], search)
            return
        # Hay que calcular huellas: en segundo plano (indicador naranja encima del visor, ■ para detener)
        from .task_window import manager
        self._busy(True)
        self.msg.setText("◈ Preparando el ejemplo… (lo ves arriba del visor; ■ para detenerlo)")
        manager().start("🎯 Preparando el ejemplo", self._work(self.m.path, specs),
                        on_done=lambda vecs: self._finish(good, name, specs, vecs, search),
                        on_fail=self._failed)

    def _busy(self, on: bool):
        for b in (self.b_yes, self.b_no, self.b_both, self.b_search):
            b.setEnabled(not on)

    def _failed(self, msg: str):
        self._busy(False)
        self.msg.setText("■ Detenido: no se guardó nada." if msg.startswith("Detenido") else f"✗ {msg}")

    def _finish(self, good: bool, name: str, specs: list, vecs: list, search: bool):
        self._busy(False)
        items = [{"good": good, "name": name, "key": sp["key"], "vec": v, "media_id": self.m.id, "t": sp["t"]}
                 for sp, v in zip(specs, vecs) if v is not None]
        if not items:
            self.msg.setText("No se pudieron leer esos fotogramas.")
            return
        if len(specs) > 1:
            self.strip.set_all(False)
        for it in items:
            self.result = it
            self.examples.append(it)
            if self.on_example:
                self.on_example(it)
            self.strip.marks.append((it["t"], good))
        self.strip.update()
        if search:
            self.do_search = True
            self.accept()
            return
        n_yes = sum(1 for e in self.examples if e["good"])
        if self.has_strip:
            self._update_match()          # con tus ✓/✗ afina dónde sale
        self.view.rect_n = None
        self.view.update()
        self.msg.setText(f"{'✓' if good else '✗'} Guardado{f' ({len(items)} fotogramas)' if len(items) > 1 else ''}. «{name}»: {n_yes} ✓ · {len(self.examples) - n_yes} ✗. "
                         "Elige otro momento para enseñarle más, o pulsa «🔎 Buscar».")
