"""
Ventana → 🔠 Tamaño de letra: dos controles, y se ve al momento.

  · Paneles, menús y ventanas: todo lo que NO es la línea de tiempo (biblioteca, inspector, menús, guía,
    diálogos, taller de miniaturas…).
  · Global: TODO, incluida la línea de tiempo (sus cabeceras, regla y pistas crecen para que quepa).

Ejemplo: Global 125 % y Paneles 120 % → la línea de tiempo al 125 % y el resto al 150 %.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

KEYS = {"ui": "letra/interfaz", "global": "letra/global"}


class FontSizeDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("🔠 Tamaño de letra")
        self.st = QSettings("EditorIA", "EditorIA")
        self._orig = {k: int(self.st.value(v, 100)) for k, v in KEYS.items()}
        lay = QVBoxLayout(self)
        info = QLabel("Haz las letras más grandes (o más pequeñas). Los cambios se ven al momento.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.setMinimumWidth(460)
        form = QVBoxLayout()
        self.sliders: dict[str, QSlider] = {}
        self.values: dict[str, QLabel] = {}
        for key, label, tip in (
                ("ui", "Paneles, menús y ventanas", "Todo lo que no es la línea de tiempo."),
                ("global", "Global (todo, también la línea de tiempo)", "Lo agranda todo.")):
            row = QHBoxLayout()
            sl = QSlider(Qt.Horizontal)
            sl.setRange(70, 200)
            sl.setSingleStep(5)
            sl.setPageStep(10)
            sl.setTickInterval(10)
            sl.setTickPosition(QSlider.TicksBelow)
            sl.setValue(self._orig[key])
            sl.setToolTip(tip)
            val = QLabel(f"{self._orig[key]} %")
            val.setFixedWidth(52)
            sl.valueChanged.connect(lambda v, k=key: self._changed(k, v))
            row.addWidget(sl, 1)
            row.addWidget(val)
            self.sliders[key], self.values[key] = sl, val
            title = QLabel(f"<b>{label}</b>")
            form.addWidget(title)
            form.addLayout(row)
        lay.addLayout(form)
        self.summary = QLabel()
        self.summary.setObjectName("dim")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        reset = QPushButton("↺ Volver al tamaño normal (100 %)")
        reset.clicked.connect(self._reset)
        lay.addWidget(reset)
        bb = QDialogButtonBox()
        bb.addButton("Aceptar", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancelar", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._apply)
        self._update_summary()

    def _changed(self, key: str, v: int):
        v = int(round(v / 5) * 5)
        self.values[key].setText(f"{v} %")
        self.st.setValue(KEYS[key], v)
        self._update_summary()
        self._timer.start()

    def _update_summary(self):
        ui = self.sliders["ui"].value()
        gl = self.sliders["global"].value()
        self.summary.setText(f"Línea de tiempo: {gl} % · Paneles, menús y ventanas: {round(ui * gl / 100)} %")

    def _apply(self):
        self.win.apply_font_scale()
        self.adjustSize()

    def _reset(self):
        for sl in self.sliders.values():
            sl.setValue(100)

    def reject(self):
        for k, v in self._orig.items():       # Cancelar: como estaba
            self.st.setValue(KEYS[k], v)
        self._apply()
        super().reject()
