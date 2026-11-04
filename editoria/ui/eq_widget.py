"""
Gráfica del ecualizador con el aspecto del de Fairlight (DaVinci Resolve):
- eje horizontal: frecuencia (Hz, 62, 250, 1K, 4K, 16K; escala logarítmica)
- a la derecha: ganancia del ecualizador (±24 dB); a la izquierda: nivel del sonido (0 a -80 dB)
- curva cian con relleno; un punto numerado por banda activa
- en gris, detrás: el espectro del audio en el cabezal
Arrastrar un punto = frecuencia y ganancia · rueda = ancho (Q) · doble clic = apagar la banda.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core import equalizer as E

LOG_MIN, LOG_MAX = math.log10(E.F_MIN), math.log10(E.F_MAX)
CYAN = QColor(E.CURVE_COLOR)


class EqGraph(QWidget):
    band_changed = Signal(int, dict)   # banda i cambiada (mientras se arrastra)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)
        self.eq: dict | None = None
        self.spectrum: np.ndarray | None = None
        self._freqs = np.logspace(LOG_MIN, LOG_MAX, 260)
        self._drag: int | None = None
        self._hover: int | None = None

    # ------------------------------------------------------- coordenadas
    def _area(self) -> QRectF:
        return QRectF(30, 8, self.width() - 62, self.height() - 26)

    def x_of(self, f: float) -> float:
        a = self._area()
        return a.left() + (math.log10(min(max(f, E.F_MIN), E.F_MAX)) - LOG_MIN) / (LOG_MAX - LOG_MIN) * a.width()

    def f_of(self, x: float) -> float:
        a = self._area()
        u = min(max((x - a.left()) / a.width(), 0.0), 1.0)
        return 10 ** (LOG_MIN + u * (LOG_MAX - LOG_MIN))

    def y_of(self, g: float) -> float:
        a = self._area()
        return a.top() + (E.G_MAX - max(-E.G_MAX, min(E.G_MAX, g))) / (2 * E.G_MAX) * a.height()

    def g_of(self, y: float) -> float:
        a = self._area()
        return min(max(E.G_MAX - (y - a.top()) / a.height() * 2 * E.G_MAX, -E.G_MAX), E.G_MAX)

    def _visible(self, i: int) -> bool:
        return bool(self.eq and self.eq["bands"][i].get("on"))

    def _node(self, i: int) -> QPointF:
        b = self.eq["bands"][i]
        g = 0.0 if b["type"] in ("hp", "lp") else b.get("g", 0.0)
        return QPointF(self.x_of(b["f"]), self.y_of(g))

    def _node_at(self, pos: QPointF) -> int | None:
        if not self.eq:
            return None
        best = None
        for i in range(len(self.eq["bands"])):
            if not self._visible(i):
                continue
            d = (self._node(i) - pos).manhattanLength()
            if d < 16 and (best is None or d < best[0]):
                best = (d, i)
        return best[1] if best else None

    # -------------------------------------------------------------- datos
    def set_eq(self, eq: dict | None):
        self.eq = eq
        self.update()

    def set_spectrum(self, samples: np.ndarray | None, sr: int = 16000):
        self.spectrum = E.spectrum_db(samples, sr, self._freqs) if samples is not None and len(samples) else None
        self.update()

    # ------------------------------------------------------------- dibujo
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1c1d20"))
        a = self._area()
        p.fillRect(a, QColor("#232428"))
        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        dim = QColor("#7d8590")
        # Rejilla horizontal: izquierda nivel (0…-80), derecha ganancia (+24…-24)
        for k in range(9):
            y = a.top() + k / 8 * a.height()
            p.setPen(QPen(QColor("#33353b"), 1))
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
            p.setPen(dim)
            p.drawText(QRectF(0, y - 7, 26, 14), Qt.AlignRight | Qt.AlignVCenter, str(-10 * k) if k else "0")
        for g in (24, 12, 0, -12, -24):
            y = self.y_of(g)
            p.setPen(dim)
            p.drawText(QRectF(a.right() + 4, y - 7, 30, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{g:+d}" if g else "0")
        p.setPen(QPen(QColor("#45484f"), 1))
        p.drawLine(QPointF(a.left(), self.y_of(0)), QPointF(a.right(), self.y_of(0)))
        # Rejilla vertical
        for fr, label in ((20, "Hz"), (62, "62"), (250, "250"), (1000, "1K"), (4000, "4K"), (16000, "16K")):
            x = self.x_of(fr)
            p.setPen(QPen(QColor("#33353b"), 1))
            if fr > 20:
                p.drawLine(QPointF(x, a.top()), QPointF(x, a.bottom()))
            p.setPen(dim)
            p.drawText(QRectF(x - 16 + (12 if fr == 20 else 0), a.bottom() + 3, 32, 14), Qt.AlignCenter, label)
        p.setClipRect(a)
        # Espectro del audio (gris, detrás)
        if self.spectrum is not None:
            path = QPainterPath(QPointF(a.left(), a.bottom()))
            for fr, db in zip(self._freqs, self.spectrum):
                path.lineTo(self.x_of(fr), a.top() + min(1.0, -min(db, 0) / 80) * a.height())
            path.lineTo(a.right(), a.bottom())
            p.fillPath(path, QColor(160, 165, 175, 40))
        if not self.eq:
            p.end()
            return
        active = self.eq.get("on", True)
        total = E.response_db(self.eq, self._freqs) if active else np.zeros_like(self._freqs)
        curve = QPainterPath()
        for k, (fr, db) in enumerate(zip(self._freqs, total)):
            pt = QPointF(self.x_of(fr), self.y_of(db))
            curve.moveTo(pt) if k == 0 else curve.lineTo(pt)
        # Relleno entre la curva y la línea de 0 dB
        fill = QPainterPath(curve)
        fill.lineTo(a.right(), self.y_of(0))
        fill.lineTo(a.left(), self.y_of(0))
        fill.closeSubpath()
        c = QColor(CYAN)
        c.setAlpha(55 if active else 20)
        p.fillPath(fill, c)
        p.setPen(QPen(CYAN if active else QColor("#5d6470"), 2))
        p.drawPath(curve)
        p.setClipping(False)
        # Puntos de las bandas activas
        f.setPointSize(8)
        p.setFont(f)
        for i, b in enumerate(self.eq["bands"]):
            if not b.get("on"):
                continue
            pt = self._node(i)
            r = 8.5 if i in (self._hover, self._drag) else 7
            p.setPen(QPen(CYAN if active else QColor("#5d6470"), 1.6))
            p.setBrush(QColor("#1c1d20"))
            p.drawEllipse(pt, r, r)
            p.setPen(QColor("#e6e8ec"))
            p.drawText(QRectF(pt.x() - 7, pt.y() - 7, 14, 14), Qt.AlignCenter, str(i + 1))
        # Información de la banda bajo el ratón
        i = self._drag if self._drag is not None else self._hover
        if i is not None:
            b = self.eq["bands"][i]
            info = f"B{i + 1} · {E.TYPES[b['type']]} · {b['f']:.0f} Hz"
            if b["type"] not in ("hp", "lp"):
                info += f" · {b.get('g', 0):+.1f} dB"
            if b["type"] == "bell":
                info += f" · Q {b.get('q', 1.0):.2f}"
            p.setPen(QColor("#e6e8ec"))
            p.drawText(QRectF(a.left() + 6, a.top() + 2, a.width() - 12, 16), Qt.AlignLeft, info)
        p.end()

    # -------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        self._drag = self._node_at(e.position())
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            h = self._node_at(pos)
            if h != self._hover:
                self._hover = h
                self.setCursor(Qt.OpenHandCursor if h is not None else Qt.ArrowCursor)
                self.update()
            return
        b = dict(self.eq["bands"][self._drag])
        b["f"] = round(self.f_of(pos.x()), 1)
        if b["type"] not in ("hp", "lp"):
            b["g"] = round(self.g_of(pos.y()), 1)
        self.setCursor(Qt.ClosedHandCursor)
        self.band_changed.emit(self._drag, b)

    def mouseReleaseEvent(self, _e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor if self._hover is not None else Qt.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._node_at(e.position())
        if i is not None:
            b = dict(self.eq["bands"][i])
            b["on"] = False
            self.band_changed.emit(i, b)

    def wheelEvent(self, e):
        i = self._node_at(e.position())
        if i is None or not self.eq:
            e.ignore()
            return
        b = dict(self.eq["bands"][i])
        b["q"] = round(min(10.0, max(0.1, b.get("q", 1.0) * (1.15 ** (e.angleDelta().y() / 120)))), 3)
        self.band_changed.emit(i, b)
        e.accept()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()
