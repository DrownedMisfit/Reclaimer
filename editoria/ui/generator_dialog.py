"""
🟦 «Color sólido o degradado»: elige el tipo y los colores (con vista previa) y se añade en el cabezal. También
sirve para CAMBIAR el de un clip que ya está en la línea de tiempo (clic derecho → «🟦 Cambiar color…»).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..core import generators as G


class _ColorButton(QPushButton):
    def __init__(self, color: str, on_change):
        super().__init__()
        self.color = color
        self._on_change = on_change
        self.setFixedWidth(120)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        q = QColor(self.color)
        fg = "#000" if q.lightness() > 140 else "#fff"
        self.setText(self.color)
        self.setStyleSheet(f"background: {self.color}; color: {fg}; border: 1px solid #555;")

    def _pick(self):
        from .common import pick_color
        c = pick_color(self.color, self, "Elige el color")
        if c.isValid():
            self.color = c.name()
            self._paint()
            self._on_change()


class GeneratorDialog(QDialog):
    def __init__(self, win, gen: dict | None = None, clip_ids: list[str] | None = None):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.clip_ids = clip_ids or []
        g = G.clean(gen or {})
        self.setWindowTitle("🟦 Cambiar color" if self.clip_ids else "🟦 Color sólido o degradado")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for k in ("solid", "linear", "radial"):
            self.kind.addItem(f"{G.ICONS[k]} {G.KINDS[k]}", k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(g["kind"])))
        self.kind.currentIndexChanged.connect(self._update)
        form.addRow("Tipo", self.kind)
        self.c1 = _ColorButton(g.get("c1", G.DEFAULT["c1"]), self._update)
        self.c2 = _ColorButton(g.get("c2", G.DEFAULT["c2"]), self._update)
        self.l1, self.l2 = QLabel("Color"), QLabel("Hasta")
        form.addRow(self.l1, self.c1)
        form.addRow(self.l2, self.c2)
        self.angle = QSpinBox()
        self.angle.setRange(0, 359)
        self.angle.setWrapping(True)
        self.angle.setSuffix("°")
        self.angle.setValue(int(g.get("angle", G.DEFAULT["angle"])))
        self.angle.setToolTip("0° = de izquierda a derecha · 90° = de arriba abajo")
        self.angle.valueChanged.connect(self._update)
        self.l_angle = QLabel("Dirección")
        form.addRow(self.l_angle, self.angle)
        self.dur = QDoubleSpinBox()
        self.dur.setRange(0.2, 3600)
        self.dur.setValue(5.0)
        self.dur.setSuffix(" s")
        self.l_dur = QLabel("Duración")
        form.addRow(self.l_dur, self.dur)
        lay.addLayout(form)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(256, 160)
        lay.addWidget(self.preview)
        btns = QHBoxLayout()
        ok = QPushButton("Cambiar" if self.clip_ids else "➕ Añadir en el cabezal")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        if self.clip_ids:
            self.l_dur.hide()
            self.dur.hide()
        self._update()

    def gen(self) -> dict:
        return G.clean({"kind": self.kind.currentData(), "c1": self.c1.color, "c2": self.c2.color,
                        "angle": self.angle.value()})

    def _update(self):
        k = self.kind.currentData()
        self.l1.setText("Color" if k == "solid" else ("Desde" if k == "linear" else "Centro"))
        self.l2.setText("Hasta" if k == "linear" else "Bordes")
        for w in (self.l2, self.c2):
            w.setVisible(k != "solid")
        for w in (self.l_angle, self.angle):
            w.setVisible(k == "linear")
        p = self.ctrl.project
        pw = 256
        ph = max(16, int(round(pw * p.height / max(1, p.width))))
        if ph > 200:
            ph, pw = 200, max(16, int(round(200 * p.width / max(1, p.height))))
        img = G.render(self.gen(), pw, ph)
        q = QImage(img.data, pw, ph, pw * 4, QImage.Format_ARGB32).copy()
        self.preview.setPixmap(QPixmap.fromImage(q))

    def _accept(self):
        if self.clip_ids:
            self.ctrl.set_generator(self.clip_ids, self.gen())
        else:
            made = self.ctrl.add_generator(self.gen(), self.win.engine.time, self.dur.value())
            if made and hasattr(self.win, "timeline"):
                self.win.timeline.set_selection([made])
        self.accept()
