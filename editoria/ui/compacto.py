"""
🧰 Ayudas para que un diálogo de siempre quepa como pestaña del panel de herramientas (~300 px de ancho) sin cortarse
(23/11, lote 1 de ventanas flotantes). Las usa el método compactar() de cada diálogo, que herramientas.adaptar_dialogo
llama al meterlo en el panel. Nunca recorren layouts desde Python: cada diálogo pasa sus widgets.

  rejilla(lay, widgets, columnas=2, indice=None)   los botones de una fila larga, en una rejilla (2 por fila)
  apilar(lay, widgets, indice=None)                uno debajo de otro, a todo el ancho
  corto(widget, texto, tip=None)                    el nombre corto a la vista y el largo en el tooltip
  ocultar(*widgets)                                 fuera lo que sobra en el panel (p. ej. «Cerrar»: ya está la ✕)
  ajustar_zonas(dlg)                                cada zona con desplazamiento del diálogo: el contenido, al ancho
                                                    visible MENOS la barra vertical (nada queda debajo de la barra) y
                                                    sin barra horizontal; las etiquetas parten dentro de ese ancho
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget


def rejilla(lay, widgets: list, columnas: int = 2, indice: int | None = None) -> QWidget:
    caja = QWidget()
    g = QGridLayout(caja)
    g.setContentsMargins(0, 0, 0, 0)
    g.setSpacing(4)
    ws = [w for w in widgets if w is not None]
    for i, w in enumerate(ws):
        w.setSizePolicy(QSizePolicy.Expanding, w.sizePolicy().verticalPolicy())
        g.addWidget(w, i // columnas, i % columnas)
    if indice is None:
        lay.addWidget(caja)
    else:
        lay.insertWidget(indice, caja)
    return caja


def apilar(lay, widgets: list, indice: int | None = None) -> QWidget:
    caja = QWidget()
    v = QVBoxLayout(caja)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    for w in widgets:
        if w is not None:
            v.addWidget(w)
    if indice is None:
        lay.addWidget(caja)
    else:
        lay.insertWidget(indice, caja)
    return caja


def corto(w, texto: str, tip: str | None = None):
    lab = getattr(w, "texto_partido", None)      # (herramientas._partir_textos ya la pasó a «casilla + etiqueta»)
    if lab is not None:
        largo = lab.text()
        lab.setText(texto)
        t = tip if tip is not None else largo
        if t and t != texto:
            lab.setToolTip(t)
            w.setToolTip(t + (f"\n{w.toolTip()}" if w.toolTip() and w.toolTip() != t else ""))
        return
    largo = w.text() if hasattr(w, "text") else ""
    w.setText(texto)
    t = tip if tip is not None else largo
    if t and t != texto:
        previo = w.toolTip()
        w.setToolTip(t + (f"\n{previo}" if previo and previo != t else ""))


def ocultar(*widgets):
    for w in widgets:
        if w is not None:
            w.hide()


class _Zona(QObject):
    """Vigila el contenido de una zona con desplazamiento: su mínimo de ancho cambia → el de la zona también."""

    def __init__(self, area: QScrollArea):
        super().__init__(area)
        self.area = area
        w = area.widget()
        if w is not None:
            w.installEventFilter(self)
        self.medir()

    def medir(self):
        w = self.area.widget()
        if w is None:
            return
        barra = self.area.verticalScrollBar().sizeHint().width()
        necesita = max(w.minimumSizeHint().width(), w.minimumWidth()) + barra + 2 * self.area.frameWidth()
        if self.area.minimumWidth() != necesita:
            self.area.setMinimumWidth(necesita)

    def eventFilter(self, obj, ev):     # noqa: N802
        if ev.type() == QEvent.LayoutRequest:
            self.medir()
        return False


def ajustar_zonas(dlg) -> int:
    """Las zonas con desplazamiento (QScrollArea) de un diálogo metido en el panel: sin barra horizontal y con el
    ancho que pide su contenido MÁS la barra vertical, así cuando sale la barra no tapa nada ni se corta el texto
    (con widgetResizable Qt pone el contenido al ancho visible, pero nunca por debajo de su mínimo). Devuelve cuántas."""
    n = 0
    for a in dlg.findChildren(QScrollArea):
        if a.widget() is None or getattr(a, "_zona_ajustada", False):
            continue
        a._zona_ajustada = True
        a.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        a.setWidgetResizable(True)
        a._zona = _Zona(a)
        n += 1
    return n
