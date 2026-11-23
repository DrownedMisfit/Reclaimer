"""
🎬 Lateral izquierdo de Escenas (20/11, petición del usuario: «esto de arriba se mira como un desastre… quedarían bien
a la izquierda juntos, como la lógica de Medios, Efectos»).

Secciones escalonadas plegables (paneles_agrupados.Acordeon, el mismo de «Voz y texto» y «Audio»):
  1 Escena (cuál, empieza, dura, dónde, mis animaciones, fondo, enviar a, aplicar, al crearla al cabezal, quitar)
  2 Personajes · 3 Plantillas · 4 Capas · 5 Sonidos · 6 Prehechas · 7 Palabras clave · 8 PNGTuber
Arriba de la página solo queda el nombre (entero), el estado, ▶, «Crear escena» y «← Editor».

  MaterialSecciones   lo que antes era la pestaña «Material» (material.setCurrentIndex(0…3), tabText, currentIndex):
                      ahora abre la sección que toca.
  CampoNombre         el nombre de la escena: mide lo que su texto (nunca cortado).
  ListaEscenas        las escenas del proyecto, con el nombre entero en varias líneas (la elegida = la que editas).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidgetItem, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import diseno as D


# ------------------------------------------------------------------------------------------------ piezas
def boton_accion(texto: str, icono: str, tip: str) -> QPushButton:
    """Botón con texto y su icono monocromo (si lo hay); el texto entero siempre (pide su ancho)."""
    b = QPushButton(texto)
    if icono:
        b.setIcon(D.icono(icono))
    b.setToolTip(tip)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return b


def combo_entero() -> QComboBox:
    """Desplegable que pide el ancho de su opción más larga (así nunca enseña «Hacia el centro (automátic…»)."""
    c = QComboBox()
    c.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return c


class CampoNombre(QLineEdit):
    """Nombre de la escena: como mínimo mide lo que su texto (nunca se corta por la izquierda ni por la derecha)."""
    TOPE = 900

    def __init__(self, texto: str = ""):
        super().__init__(texto)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.textChanged.connect(lambda _t: self._medir())
        self._medir()

    def _medir(self):
        fm = self.fontMetrics()
        ancho = fm.horizontalAdvance(self.text() or self.placeholderText() or "Escena") + 2 * D.px(D.M3) + 8
        self._ancho_texto = min(self.TOPE, max(D.px(120), ancho))
        self.setMinimumWidth(min(self._ancho_texto, D.px(220)))   # (pide su texto; cede algo si la ventana es estrecha)
        self.updateGeometry()
        self.setCursorPosition(0) if not self.hasFocus() else None

    def sizeHint(self):                         # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(getattr(self, "_ancho_texto", D.px(200)), super().sizeHint().height())

    def setText(self, t):                       # noqa: N802
        super().setText(t)
        self._medir()


class ListaEscenas(D.ListaAdaptable):
    """Las escenas del proyecto (nombre entero + cuándo); clic = editar esa. La de ahora va elegida."""

    def __init__(self, page):
        super().__init__(clave="", ancho_min=150, max_columnas=1, ajustar_alto=True, alto_max=D.px(110))
        self.page = page
        self.setToolTip("Las escenas de este proyecto: clic = editar esa (si hay cambios sin aplicar, te lo pregunta)")
        self.itemClicked.connect(lambda it: self._elegir(it.data(Qt.UserRole)))

    def refrescar(self):
        sel = self.page.sel_escena
        self.blockSignals(True)
        self.clear()
        actual = None
        for i in range(sel.count()):
            eid = sel.itemData(i)
            if eid in ("__nueva__", "__nueva_comp__"):
                continue
            it = QListWidgetItem(sel.itemText(i).replace("  · ", chr(10)).replace("  (", chr(10) + "("))
            it.setData(Qt.UserRole, eid)
            it.setToolTip(sel.itemText(i))
            self.addItem(it)
            if eid == self.page.escena.get("id"):
                actual = it
        if actual is not None:
            self.setCurrentItem(actual)
        self.blockSignals(False)

    def _elegir(self, eid):
        sel = self.page.sel_escena
        i = sel.findData(eid)
        if i >= 0 and i != sel.currentIndex():
            sel.setCurrentIndex(i)


class _Desplazable(QScrollArea):
    """Zona con desplazamiento VERTICAL que pide el ancho mínimo de lo de dentro (así su panel nunca la deja más
    estrecha y nada se corta por la derecha). En el lateral se queda con el alto libre (nada tapado, sin huecos)."""

    def quiere_crecer(self) -> bool:
        return True

    def minimumSizeHint(self):                 # noqa: N802
        from PySide6.QtCore import QSize
        w = self.widget()
        base = super().minimumSizeHint()
        if w is None:
            return base
        barra = self.verticalScrollBar().sizeHint().width()
        return QSize(w.minimumSizeHint().width() + barra + 2, base.height())

    def eventFilter(self, obj, ev):            # noqa: N802
        from PySide6.QtCore import QEvent
        if obj is self.widget() and ev.type() == QEvent.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(obj, ev)


def _desplazable(w: QWidget) -> QScrollArea:
    a = _Desplazable()
    a.setWidgetResizable(True)
    a.setFrameShape(QFrame.NoFrame)
    a.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    a.setWidget(w)
    w.installEventFilter(a)
    return a


# ------------------------------------------------------------------------------------------------ secciones
def seccion_escena(page) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(D.px(D.M2), D.px(D.M1), D.px(D.M2), D.px(D.M2))
    v.setSpacing(D.px(D.M1))
    v.addWidget(page.lista_escenas)
    fila = D.fila_fija(QHBoxLayout())
    fila.setSpacing(D.px(D.M1))
    b_nueva = boton_accion("Nueva escena", "", "Empieza otra escena en el tramo marcado (I/O) o en el cabezal")
    b_comp = boton_accion("Nueva comparativa", "columns-2", "Toma A y B con etiqueta: lado a lado, arriba y abajo, "
                                                            "fundido o alternar")
    for b, clave in ((b_nueva, "__nueva__"), (b_comp, "__nueva_comp__")):
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(lambda _c=False, k=clave: page.sel_escena.setCurrentIndex(page.sel_escena.findData(k)))
        fila.addWidget(b)
    v.addLayout(fila)
    v.addWidget(D.TituloSeccion("Tiempo y sitio"))
    v.addWidget(D.FilaInspector("Empieza", page.desde))
    v.addWidget(D.FilaInspector("Dura", page.dura))
    v.addWidget(page._b_io)
    v.addWidget(page._b_lib)
    v.addWidget(D.TituloSeccion("Aspecto"))
    page._fila_fondo = D.FilaInspector("Fondo", page.fondo)
    v.addWidget(page._fila_fondo)
    v.addWidget(D.FilaInspector("Enviar a", page.destino))
    v.addWidget(D.TituloSeccion("Ponerla"))
    v.addWidget(page.b_aplicar)
    v.addWidget(page.al_cabezal)
    v.addWidget(page._b_quitar)
    v.addStretch(1)
    return _desplazable(w)


def seccion_pngtuber(page) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(D.px(D.M2), D.px(D.M1), D.px(D.M2), D.px(D.M2))
    v.addWidget(page._b_png)
    v.addStretch(1)
    return w


def seccion_plantillas(page) -> QWidget:
    from .escenas_plantillas import PanelPlantillas
    page.plantillas = PanelPlantillas(page)
    return page.plantillas


class Lateral(QWidget):
    """El lateral: un Acordeon con las secciones (se abre una a la vez y ocupa el alto que queda)."""

    def __init__(self, page, secciones):
        super().__init__()
        from .paneles_agrupados import Acordeon
        self.page = page
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.acordeon = Acordeon("escenas", secciones)
        v.addWidget(self.acordeon, 1)
        self._titulos = {clave: titulo for clave, titulo, _w, _a in secciones}
        D.medida(self, lambda x: x.setMinimumWidth(D.px(240)))

    def abrir(self, clave: str):
        self.acordeon.abrir(clave)

    def abierta(self) -> str | None:
        return self.acordeon.abierta()

    def titulo(self, clave: str) -> str:
        return self._titulos.get(clave, "")


class MaterialSecciones:
    """Lo que antes era la pestaña «Material» (0 Personajes · 1 Sonidos · 2 Prehechas · 3 Palabras clave)."""
    CLAVES = ("personajes", "sonidos", "prehechas", "palabras")

    def __init__(self, lateral: Lateral):
        self.lateral = lateral

    def setCurrentIndex(self, i: int):          # noqa: N802
        if 0 <= i < len(self.CLAVES):
            self.lateral.abrir(self.CLAVES[i])

    def currentIndex(self) -> int:              # noqa: N802
        a = self.lateral.abierta()
        return self.CLAVES.index(a) if a in self.CLAVES else -1

    def count(self) -> int:
        return len(self.CLAVES)

    def tabText(self, i: int) -> str:           # noqa: N802
        return self.lateral.titulo(self.CLAVES[i]) if 0 <= i < len(self.CLAVES) else ""

    def maximumWidth(self) -> int:              # noqa: N802
        return self.lateral.maximumWidth()

    def minimumWidth(self) -> int:              # noqa: N802
        return self.lateral.minimumWidth()

    def setMinimumWidth(self, w: int):          # noqa: N802
        self.lateral.setMinimumWidth(w)

    def width(self) -> int:
        return self.lateral.width()


class FormaDiseno(QVBoxLayout):
    """Como QFormLayout (addRow(etiqueta, campo) / addRow(widget) / addRow(layout)) pero con FilaInspector del
    sistema de diseño: la etiqueta pasa encima si no cabe y los desplegables piden su opción más larga (nada cortado)."""

    def __init__(self, w: QWidget):
        super().__init__(w)
        self.setContentsMargins(D.px(D.M2), D.px(D.M1), D.px(D.M2), D.px(D.M2))
        self.setSpacing(D.px(D.M1))
        self._fin = None

    def _al_final(self):
        if self._fin is None:
            self.addStretch(1)
            self._fin = self.count() - 1

    def addRow(self, a, b=None):                # noqa: N802
        if self._fin is not None:               # (siempre antes del estirado del final)
            self.takeAt(self._fin)
            self._fin = None
        if isinstance(a, QComboBox) or isinstance(b, QComboBox):
            c = b if isinstance(b, QComboBox) else a
            c.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if b is not None:
            self.addWidget(D.FilaInspector(str(a), b))
        elif isinstance(a, QWidget):
            self.addWidget(a)
        else:
            self.addLayout(a)
        self._al_final()


def desplazable(w: QWidget) -> QScrollArea:
    return _desplazable(w)
