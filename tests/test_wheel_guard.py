"""
Prueba de que la rueda del ratón NO cambia sin querer las casillas del Inspector (el usuario se encontró un «Fundido de
entrada» de 0,1 s en todos los trozos de su voz): sin haber hecho clic en la casilla, la rueda desplaza el panel y el
valor no cambia; con la casilla elegida (clic), la rueda sí la cambia.
Ejecutar:  .venv/Scripts/python.exe tests/test_wheel_guard.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QScrollArea, QVBoxLayout,  # noqa: E402
                               QWidget)


def wheel(w, steps=2):
    for _ in range(steps):
        ev = QWheelEvent(QPointF(5, 5), QPointF(w.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, 120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(w, ev)


def main():
    app = QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    spin = QDoubleSpinBox()
    spin.setRange(0, 5)
    spin.setSingleStep(0.05)
    combo = QComboBox()
    combo.addItems(["uno", "dos", "tres"])
    lay.addWidget(spin)
    lay.addWidget(combo)
    for _ in range(40):
        lay.addWidget(QDoubleSpinBox())
    area.setWidget(inner)
    area.resize(300, 200)
    area.show()
    app.processEvents()
    spin.clearFocus()                       # (al abrirse, la primera casilla toma el foco sola)
    area.setFocus()
    app.processEvents()
    wheel(spin)
    wheel(combo)
    app.processEvents()
    assert spin.value() == 0.0 and combo.currentIndex() == 0, (spin.value(), combo.currentIndex())
    print("✓ sin hacer clic: la rueda no cambia ni la casilla ni la lista")
    spin.setFocus()
    app.processEvents()
    wheel(spin)
    app.processEvents()
    assert abs(spin.value() - 0.1) < 1e-9, spin.value()
    print("✓ con la casilla elegida (clic), la rueda sí la cambia")
    print("TODO OK")


if __name__ == "__main__":
    main()
