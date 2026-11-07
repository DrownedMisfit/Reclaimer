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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QScrollArea, QTabWidget,  # noqa: E402
                               QVBoxLayout, QWidget)


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
    tabs = QTabWidget()                     # (como las pestañas de «Caras graciosas»: 👀 Ojos · 😮 Emociones…)
    for n in ("Ojos", "Emociones", "Cabeza", "Rasgos"):
        tabs.addTab(QWidget(), n)
    lay.addWidget(spin)
    lay.addWidget(combo)
    lay.addWidget(tabs)
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
    wheel(tabs.tabBar())
    app.processEvents()
    assert spin.value() == 0.0 and combo.currentIndex() == 0, (spin.value(), combo.currentIndex())
    assert tabs.currentIndex() == 0, tabs.currentIndex()
    print("✓ sin hacer clic: la rueda no cambia ni la casilla, ni la lista, ni la pestaña")
    spin.setFocus()                         # tener el foco NO basta (el usuario: «trato de bajar y cambio valores»)
    app.processEvents()
    wheel(spin)
    app.processEvents()
    assert spin.value() == 0.0, spin.value()
    print("✓ con el foco pero sin clic, la rueda tampoco la cambia")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    le = spin.lineEdit()                    # el clic real cae en la casilla de texto del número
    QApplication.sendEvent(le, QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(le.mapToGlobal(QPoint(5, 5))),
                                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(le, QMouseEvent(QEvent.MouseButtonRelease, QPointF(5, 5),
                                           QPointF(le.mapToGlobal(QPoint(5, 5))), Qt.LeftButton, Qt.NoButton,
                                           Qt.NoModifier))
    spin.setFocus()
    app.processEvents()
    wheel(spin)
    app.processEvents()
    assert abs(spin.value() - 0.1) < 1e-9, spin.value()
    print("✓ con clic en la casilla, la rueda sí la cambia")
    QApplication.sendEvent(spin, QEvent(QEvent.Leave))   # el ratón sale de la casilla (sigue con el foco)
    wheel(spin)
    app.processEvents()
    assert abs(spin.value() - 0.1) < 1e-9 and spin.hasFocus(), spin.value()
    print("✓ al sacar el ratón de la casilla, la rueda vuelve a desplazar el panel (aunque siga con el foco)")
    wheel(le)                               # la rueda sobre la parte de texto del número tampoco lo cambia
    app.processEvents()
    assert abs(spin.value() - 0.1) < 1e-9, spin.value()
    print("TODO OK")


if __name__ == "__main__":
    main()
