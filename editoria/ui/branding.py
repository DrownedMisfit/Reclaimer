"""Marca de RECLAIMER: el símbolo (un artefacto hexagonal partido en tres capas, con la del medio
ligeramente desplazada: algo antiguo, recuperado y vuelto a montar) y el icono de la aplicación."""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_PATH = os.path.join(ASSETS, "reclaimer.ico")
SYMBOL_PATH = os.path.join(ASSETS, "reclaimer.svg")


def app_icon() -> QIcon:
    if os.path.exists(ICON_PATH):
        return QIcon(ICON_PATH)
    return QIcon(SYMBOL_PATH)


def symbol_pixmap(size: int, color: str = "#ECECEA") -> QPixmap:
    """El símbolo solo (fondo transparente) en el color pedido."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    try:
        with open(SYMBOL_PATH, encoding="utf-8") as f:
            svg = f.read().replace("#ECECEA", color)
    except OSError:
        return pix
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return pix
