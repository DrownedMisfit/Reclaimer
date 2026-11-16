"""
🎨 Ruedas de color Lift / Gamma / Gain (como la página Color de Resolve): una por zona (sombras, medios, luces).
  · arrastrar el punto dentro del círculo = empujar esa zona hacia ese color (más lejos del centro = más fuerte);
  · la barra de debajo = más clara / más oscura esa zona;
  · doble clic en el círculo = volver al centro; doble clic en la barra = volver a 0.
Mayús al arrastrar = movimiento fino. Emiten `changed([x, y, brillo])` mientras arrastras y `released` al soltar.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget


class _Disc(QWidget):
    moved = Signal(float, float)
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.x, self.y = 0.0, 0.0
        self.setMinimumSize(78, 78)
        self.setMaximumSize(150, 150)                # (en un Inspector ancho no crecen sin fin)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.CrossCursor)
        self._drag = None

    def heightForWidth(self, w: int) -> int:
        return w

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(130, 130)

    def hasHeightForWidth(self) -> bool:
        return True

    def _geo(self):
        s = min(self.width(), self.height()) - 6
        return QPointF(self.width() / 2, self.height() / 2), s / 2

    def set_pos(self, x: float, y: float):
        self.x, self.y = x, y
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, r = self._geo()
        # Círculo de color: 0° = rojo a la derecha, 120° = verde, 240° = azul (igual que core/color.wheel_rgb).
        # QConicalGradient gira en sentido contrario a las agujas con la y hacia arriba: se le pasan los mismos ángulos
        cg = QConicalGradient(c, 0)
        for k in range(13):
            a = k / 12
            col = QColor.fromHsvF((a * 1.0) % 1.0, 0.75, 0.9)
            cg.setColorAt(a, col)
        p.setPen(QPen(QColor("#2b2f36"), 1))
        p.setBrush(QBrush(cg))
        p.drawEllipse(c, r, r)
        rg = QRadialGradient(c, r)
        rg.setColorAt(0.0, QColor(40, 42, 48, 255))
        rg.setColorAt(1.0, QColor(40, 42, 48, 60))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        pt = QPointF(c.x() + self.x * r, c.y() - self.y * r)
        if abs(self.x) + abs(self.y) > 1e-4:
            p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            p.drawLine(c, pt)
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawEllipse(pt, 5, 5)

    def _to_xy(self, pos: QPointF):
        c, r = self._geo()
        x, y = (pos.x() - c.x()) / max(r, 1), -(pos.y() - c.y()) / max(r, 1)
        d = math.hypot(x, y)
        if d > 1:
            x, y = x / d, y / d
        return x, y

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._drag = (QPointF(e.position()), self.x, self.y)
        self._fino = bool(e.modifiers() & Qt.ShiftModifier)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        fino = bool(e.modifiers() & Qt.ShiftModifier)
        if fino != getattr(self, "_fino", False):     # (cambia Mayús a mitad: se re-ancla, el punto no salta)
            self._fino = fino
            self._drag = (QPointF(e.position()), self.x, self.y)
        p0, x0, y0 = self._drag
        if e.modifiers() & Qt.ShiftModifier:          # fino: el punto se mueve a un cuarto de velocidad
            c, r = self._geo()
            d = (QPointF(e.position()) - p0) / max(r, 1) * 0.25
            x, y = x0 + d.x(), y0 - d.y()
            n = math.hypot(x, y)
            if n > 1:
                x, y = x / n, y / n
        else:
            x, y = self._to_xy(QPointF(e.position()))
        self.set_pos(x, y)
        self.moved.emit(x, y)

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        if (QPointF(e.position()) - self._drag[0]).manhattanLength() < 2:   # clic sin arrastrar: ir ahí
            x, y = self._to_xy(QPointF(e.position()))
            self.set_pos(x, y)
            self.moved.emit(x, y)
        self._drag = None
        self.released.emit()

    def mouseDoubleClickEvent(self, e):
        self._drag = None
        self.set_pos(0.0, 0.0)
        self.moved.emit(0.0, 0.0)
        self.released.emit()


class _Level(QSlider):
    reset = Signal()

    def mouseDoubleClickEvent(self, e):
        self.setValue(0)
        self.reset.emit()


class ColorWheel(QWidget):
    changed = Signal(list)              # [x, y, brillo]

    def __init__(self, title: str, tip: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        self.disc = _Disc(self)
        self.level = _Level(Qt.Horizontal)
        self.level.setRange(-100, 100)
        self.level.setSingleStep(2)
        self.level.setPageStep(10)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("color: #8b909a; font-size: 10px;")
        lay.addWidget(self.title)
        lay.addWidget(self.disc, 0, Qt.AlignHCenter)
        self.level.setMaximumWidth(150)
        lay.addWidget(self.level, 0, Qt.AlignHCenter)
        lay.addWidget(self.value)
        self.setToolTip(tip + "\n\nArrastra el punto hacia un color · barra = más clara / más oscura\n"
                              "Doble clic = volver al centro (o a 0 en la barra) · Mayús = movimiento fino")
        self.disc.moved.connect(lambda _x, _y: self._emit())
        self.level.valueChanged.connect(lambda _v: self._emit())
        self._loading = False

    def values(self) -> list:
        return [round(self.disc.x, 3), round(self.disc.y, 3), round(self.level.value() / 100, 3)]

    def set_values(self, x: float, y: float, lv: float):
        self._loading = True
        try:
            self.disc.set_pos(x, y)
            self.level.setValue(int(round(lv * 100)))
        finally:
            self._loading = False
        self._show()

    def _show(self):
        x, y, lv = self.values()
        fuerza = math.hypot(x, y)
        if fuerza < 1e-3 and abs(lv) < 1e-3:
            self.value.setText("0")
            return
        ang = (math.degrees(math.atan2(y, x)) + 360) % 360
        self.value.setText((f"{int(round(fuerza * 100))} % · {int(round(ang))}°" if fuerza >= 1e-3 else "")
                           + (f"  {lv:+.2f}" if abs(lv) >= 1e-3 else ""))

    def _emit(self):
        self._show()
        if not self._loading:
            self.changed.emit(self.values())


def wheel_box(parent=None):
    """Las tres ruedas en fila: {"lift": ColorWheel, "gamma": …, "gain": …} y el widget que las contiene."""
    from PySide6.QtWidgets import QHBoxLayout
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    tips = {"lift": "Sombras (Lift): las partes oscuras de la imagen",
            "gamma": "Medios (Gamma): los tonos intermedios (piel, cielo, paredes…)",
            "gain": "Luces (Gain): las partes claras de la imagen"}
    titles = {"lift": "Sombras", "gamma": "Medios", "gain": "Luces"}
    wheels = {}
    for k in ("lift", "gamma", "gain"):
        wheels[k] = ColorWheel(titles[k], tips[k], w)
        lay.addWidget(wheels[k], 1)
    return w, wheels
