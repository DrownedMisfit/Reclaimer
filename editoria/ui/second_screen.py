"""
🖥 Visor en la segunda pantalla: una ventana sin bordes, a pantalla completa en el otro monitor, que muestra
LO MISMO que el visor (misma escena, sin decodificar otra vez). Sin asas ni guías. No roba el foco del editor.
Esc o el mismo atajo la cierra; Espacio reproduce / pausa.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsView, QVBoxLayout, QWidget


def pantalla_secundaria():
    """(pantalla donde va el visor, si hay de verdad una segunda). Con una sola, la principal."""
    principal = QGuiApplication.primaryScreen()
    otras = [s for s in QGuiApplication.screens() if s is not principal]
    return (otras[0] if otras else principal), bool(otras)


class _VisorView(QGraphicsView):
    """Vista de SOLO lectura sobre la escena del visor: ajusta el cuadro del video manteniendo la proporción."""

    def __init__(self, canvas):
        super().__init__(canvas.scene())
        self._canvas = canvas
        self._fit_key = None
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#000000"))
        self.setInteractive(False)
        self.setFocusPolicy(Qt.NoFocus)                  # las teclas las recibe la ventana
        self.viewport().setProperty("clean_view", True)  # las capas de edición (guías, asas) no se pintan aquí

    def refit(self):
        c = self._canvas
        key = (c.W, c.H, self.width(), self.height())
        if key != self._fit_key:
            self._fit_key = key
            self.fitInView(QRectF(0, 0, c.W, c.H), Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refit()


class SecondScreenWindow(QWidget):
    closed = Signal()

    def __init__(self, canvas, toggle, close_key: str = "F11", parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # al abrirla no se roba el foco del editor
        self.setWindowTitle("Reclaimer · Visor")
        self.setStyleSheet("background: #000000;")
        self._toggle = toggle                            # (lo que hace Espacio: reproducir / pausar)
        self._close_key = QKeySequence(close_key)
        self.view = _VisorView(canvas)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self._timer = QTimer(self)                        # por si cambia el tamaño del proyecto con la ventana abierta
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.view.refit)

    def abrir(self):
        screen, _ = pantalla_secundaria()
        self.setGeometry(screen.geometry())
        self.show()                                       # (sin activateWindow: el editor sigue con el foco)
        self._timer.start()
        self.view.refit()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape or (k != Qt.Key_Space and QKeySequence(e.keyCombination()) == self._close_key):
            self.close()
        elif k == Qt.Key_Space:
            self._toggle()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)
        self.closed.emit()
