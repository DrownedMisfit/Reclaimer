"""
Paneles agrupados (agrupación del 20/11, aprobada por el usuario: «tenemos la pantalla llena de cosas que están en el
mismo espacio»): UN panel con secciones escalonadas en el orden de trabajo, en vez de varios paneles en pestañas.

  Acordeon(secciones)        [(clave, título, widget, ayuda)] → cabeceras numeradas; se abre UNA sección a la vez y
                             ocupa todo el alto que queda (cada panel de dentro trae su propio desplazamiento).
  .abrir(clave)              abre esa sección (la de antes se pliega) y la recuerda (QSettings «agrupados/<nombre>»).
  Sin huecos (20/11): la sección abierta solo se queda el alto libre si enseña algo que crece (una lista, un texto…:
  tabs.quiere_crecer); si no —p. ej. «Transcripción» sin transcripción o todo plegado—, el alto libre va al final y
  la ventana se lo puede dar al panel vecino del mismo lado (MainWindow._ceder_alto).
  .abierta() -> clave        .widget_de(clave) / .clave_de(widget)
  .cambiada(clave)           señal al abrir una sección
  Con poco alto (menos de ALTO_COMPACTO px a la vista, p. ej. a 1366×768) las cabeceras cerradas se esconden y la de la
  sección abierta despliega la lista de todas: el contenido no pierde el alto de cinco cabeceras.

Se usa para «Voz y texto» (Transcribir → Transcripción → Subtítulos → Palabras clave → Voz IA) y para «Audio»
(Limpieza → Mezcla y música → Sonoridad). Sin lógica propia: los paneles de dentro son los de siempre.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtWidgets import QMenu, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget


class Acordeon(QWidget):
    cambiada = Signal(str)
    @staticmethod
    def poner_hoja_cabecera(cab) -> None:
        """🎨 La cabecera con «profundidad sutil» (ui/diseno.py): degradado mínimo y bisel de 1 px (se rehace sola
        al cambiar de tema o de acento)."""
        from .diseno import cabecera_estandar      # (la cabecera de sección del programa: 24 px)
        cabecera_estandar(cab, "QPushButton")

    ALTO_COMPACTO = 430        # (menos alto a la vista que esto: solo la cabecera abierta, con la lista de todas)

    def __init__(self, nombre: str, secciones: list[tuple[str, str, QWidget, str]], parent=None):
        super().__init__(parent)
        self.nombre = nombre
        self.setObjectName("acordeon")
        self._orden: list[str] = []
        self._cab: dict[str, QPushButton] = {}
        self._cont: dict[str, QWidget] = {}
        self._titulo: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self._lay = lay
        for i, (clave, titulo, w, ayuda) in enumerate(secciones, start=1):
            cab = QPushButton()                       # (un QToolButton centraba el texto: este, a la izquierda)
            cab.setObjectName("seccionacordeon")
            cab.setCheckable(True)
            cab.setFlat(True)
            cab.setFocusPolicy(Qt.NoFocus)
            cab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cab.setToolTip(ayuda)
            self.poner_hoja_cabecera(cab)             # (en cada cabecera: en el acordeón entero repintaba todo)
            cab.clicked.connect(lambda _c=False, k=clave: self.abrir(k))
            self._titulo[clave] = f"{i} · {titulo}"
            lay.addWidget(cab)
            w.setParent(self)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self._sangria(w)                          # (el contenido, con la sangría de sección bajo su cabecera)
            lay.addWidget(w, 1)
            w.hide()
            w.installEventFilter(self)                # (se plegó o cambió algo dentro: repartir el alto otra vez)
            self._orden.append(clave)
            self._cab[clave] = cab
            self._cont[clave] = w
        lay.addStretch(0)                             # (el alto libre cuando la abierta no lo usa: al final)
        self._abierta = None
        self._compacto = False
        self._vigilado = None
        from PySide6.QtCore import QTimer
        self._t_crecer = QTimer(self)
        self._t_crecer.setSingleShot(True)
        self._t_crecer.setInterval(0)
        self._t_crecer.timeout.connect(self._estirar)
        self._menu = QMenu(self)
        for clave in self._orden:
            self._menu.addAction(self._titulo[clave], lambda k=clave: self.abrir(k))
        guardada = str(QSettings("EditorIA", "EditorIA").value(f"agrupados/{nombre}", "") or "")
        self.abrir(guardada if guardada in self._cont else self._orden[0], guardar=False)

    def abrir(self, clave: str, guardar: bool = True):
        if clave not in self._cont:
            return
        for k in self._orden:
            on = k == clave
            self._cont[k].setVisible(on)
            self._cab[k].setChecked(on)
            self._cab[k].setText(("▾  " if on else "▸  ") + self._titulo[k])
        self._abierta = clave
        self._poner_compacto(self._compacto, forzar=True)
        self._estirar()
        if guardar:
            QSettings("EditorIA", "EditorIA").setValue(f"agrupados/{self.nombre}", clave)
        self.cambiada.emit(clave)

    @staticmethod
    def _sangria(w: QWidget):
        """Una sola rejilla: el contenido de cada sección empieza SANGRIA_SECCION px a la derecha de su cabecera."""
        from . import diseno as D
        from PySide6.QtWidgets import QScrollArea
        objetivo = w.widget() if isinstance(w, QScrollArea) and w.widget() is not None else w
        lay = objetivo.layout()
        if lay is None:
            return
        propio = lay.contentsMargins().left()

        def poner(_w, lay=lay, propio=propio):        # (se rehace al cambiar «Letra»: refrescar_escala)
            m = lay.contentsMargins()
            quiero = max(propio, D.px(D.SANGRIA_SECCION))
            if m.left() != quiero:
                lay.setContentsMargins(quiero, m.top(), m.right(), m.bottom())
        D.medida(objetivo, poner)

    # ------------------------------------------------------------------ poco alto: cabeceras compactas
    def _poner_compacto(self, on: bool, forzar: bool = False):
        if on == self._compacto and not forzar:
            return
        self._compacto = on
        for k in self._orden:
            cab, abierta = self._cab[k], k == self._abierta
            cab.setVisible(abierta or not on)
            if on and abierta:
                cab.setMenu(self._menu)               # (clic = la lista de todas las secciones)
            elif cab.menu() is not None:
                cab.setMenu(None)

    def compacto(self) -> bool:
        return self._compacto

    def showEvent(self, ev):
        super().showEvent(ev)
        vp = self.parentWidget()                   # (la parte que se ve de la zona con desplazamiento del panel)
        if vp is not None and vp is not self._vigilado:
            if self._vigilado is not None:
                try:
                    self._vigilado.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._vigilado = vp
            vp.installEventFilter(self)
        if vp is not None:
            self._poner_compacto(vp.height() < self.ALTO_COMPACTO)

    def eventFilter(self, obj, ev):
        if obj is self._vigilado and ev.type() == QEvent.Resize:
            self._poner_compacto(obj.height() < self.ALTO_COMPACTO)
        elif ev.type() == QEvent.LayoutRequest and obj in self._cont.values():
            self._revisar_crecer()
        return False

    # ------------------------------------------------------------------ sin huecos: el alto libre, a quien lo usa
    def _revisar_crecer(self):
        """(tabs.avisar_contenido o un cambio dentro de una sección) → repartir el alto en cuanto Qt termine."""
        self._t_crecer.start()

    def quiere_crecer(self) -> bool:
        """¿La sección abierta enseña algo que aprovecha alto extra (lista, texto…)? Si no, el alto libre sobra aquí."""
        from .tabs import quiere_crecer
        w = self._cont.get(self._abierta) if self._abierta else None
        return w is not None and quiere_crecer(w)

    def _estirar(self):
        from .tabs import avisar_contenido
        crece = self.quiere_crecer()
        for k in self._orden:
            w = self._cont[k]
            on = crece and k == self._abierta
            if self._lay.stretch(self._lay.indexOf(w)) != (1 if on else 0):
                self._lay.setStretchFactor(w, 1 if on else 0)
            pol = QSizePolicy.Expanding if on else QSizePolicy.Preferred
            if w.sizePolicy().verticalPolicy() != pol:
                w.setSizePolicy(QSizePolicy.Preferred, pol)
        fin = 2 * len(self._orden)                    # (cabecera + contenido por sección; luego el estirable)
        if self._lay.stretch(fin) != (0 if crece else 1):
            self._lay.setStretch(fin, 0 if crece else 1)
        if crece != getattr(self, "_crecia", None):
            self._crecia = crece
            avisar_contenido(self.parentWidget())     # (la ventana: ceder alto al vecino o pedirlo)

    def abierta(self) -> str | None:
        return self._abierta

    def claves(self) -> list[str]:
        return list(self._orden)

    def widget_de(self, clave: str) -> QWidget | None:
        return self._cont.get(clave)

    def titulo(self, clave: str) -> str:
        """«N · Título» de la sección (sin ▸/▾)."""
        return self._titulo.get(clave, "")

    def cabecera(self, clave: str) -> QPushButton | None:
        return self._cab.get(clave)

    def clave_de(self, widget: QWidget) -> str | None:
        """La sección que contiene widget (él mismo o uno de sus hijos)."""
        for k, w in self._cont.items():
            if w is widget or w.isAncestorOf(widget):
                return k
        return None


class PanelSinHuecos(QWidget):
    """Un panel con UN solo contenido (22/11: las pestañas de «Palabras clave», su propio panel) y la regla «sin huecos»
    del Acordeon: si lo que se ve crece (una lista, un texto…: tabs.quiere_crecer) se queda todo el alto; si no —p. ej.
    «Dijiste…» sin narración transcrita—, su contenido va arriba y seguido, el alto libre al final, y la ventana se lo
    puede dar al panel vecino del mismo lado (MainWindow._ceder_alto)."""

    def __init__(self, contenido: QWidget, parent=None):
        super().__init__(parent)
        self._w = contenido
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(contenido, 1)
        lay.addStretch(0)
        self._lay = lay
        self._crecia = None
        from PySide6.QtCore import QTimer
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(0)
        self._t.timeout.connect(self._estirar)
        contenido.installEventFilter(self)
        if isinstance(contenido, QTabWidget):
            contenido.currentChanged.connect(lambda _i: self._t.start())
        self._estirar()

    def contenido(self) -> QWidget:
        return self._w

    def eventFilter(self, obj, ev):
        if obj is self._w and ev.type() in (QEvent.LayoutRequest, QEvent.Show):
            self._t.start()
        return False

    def _revisar_crecer(self):
        self._t.start()

    def quiere_crecer(self) -> bool:
        from .tabs import quiere_crecer
        return quiere_crecer(self._w)

    def _estirar(self):
        from .tabs import avisar_contenido
        crece = self.quiere_crecer()
        if self._lay.stretch(0) != (1 if crece else 0):
            self._lay.setStretch(0, 1 if crece else 0)
            self._lay.setStretch(1, 0 if crece else 1)
        pol = QSizePolicy.Expanding if crece else QSizePolicy.Preferred
        if self._w.sizePolicy().verticalPolicy() != pol:
            self._w.setSizePolicy(QSizePolicy.Preferred, pol)
        if crece != self._crecia:
            self._crecia = crece
            avisar_contenido(self.parentWidget())     # (la ventana: ceder alto al vecino o pedirlo)


class PestanasAjustadas(QTabWidget):
    """Pestañas que piden EXACTAMENTE el alto de la página que se ve (más su barra, si se ve), calculado al mismo
    ancho: sin hueco debajo de una página corta y sin heredar el alto de la pestaña más alta (un QTabWidget pide el de
    todas: en «4 · Palabras clave», «Buscar material» obligaba a «Dijiste…» a desplazar todo el panel y su cabecera
    quedaba fuera de la vista). Una pestaña apagada solo apaga su botón (la página no se toca).
    iconos_si_no_cabe([...]): con poco ancho, cada pestaña pasa a su icono y el nombre al tooltip (nada recortado).
    (Una sola clase para todo el programa: inspector_secciones la reexporta.)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _i: self.updateGeometry())
        self._nombres: list[str] = []
        self._iconos: list[str] = []
        self._compactas = False

    # ---- pestañas apagadas: solo el botón
    def setTabEnabled(self, i: int, on: bool):     # noqa: N802
        self.__dict__.setdefault("_activas", {})[i] = bool(on)
        self.tabBar().setTabEnabled(i, bool(on))      # (la barra puede ir escondida; la página no se toca)

    def isTabEnabled(self, i: int) -> bool:        # noqa: N802
        return self.__dict__.get("_activas", {}).get(i, True)

    # ---- con poco ancho, solo iconos
    def iconos_si_no_cabe(self, iconos: list[str]):
        """Si los nombres de las pestañas no caben a lo ancho, cada pestaña pasa a su icono (Lucide) y el nombre va al
        tooltip; con sitio, otra vez su nombre. Así ninguna pestaña sale recortada a 200 px."""
        self.tabBar().setElideMode(Qt.ElideNone)      # (nunca «Buscar mat…»: o cabe entero o va su icono)
        self._nombres = [self.tabText(i) for i in range(self.count())]
        self._iconos = list(iconos)
        self._revisar_pestanas()

    def _ancho_nombres(self) -> int:
        fm = self.tabBar().fontMetrics()
        return sum(fm.horizontalAdvance(t) + 30 for t in self._nombres)

    def _revisar_pestanas(self):
        if not self._nombres:
            return
        compactas = self._ancho_nombres() > self.width() - 4
        if compactas == self._compactas and (compactas or self.tabText(0) == self._nombres[0]):
            return
        self._compactas = compactas
        from PySide6.QtGui import QIcon
        from . import diseno as D
        for i, nombre in enumerate(self._nombres[:self.count()]):
            if compactas and i < len(self._iconos):
                self.setTabText(i, "")
                self.setTabIcon(i, D.icono(self._iconos[i]))
                tip = self.tabToolTip(i)
                if not tip.startswith(nombre):
                    self.setTabToolTip(i, f"{nombre}: {tip}" if tip else nombre)
            else:
                self.setTabText(i, nombre)
                self.setTabIcon(i, QIcon())

    def poner_nombre(self, i: int, texto: str):
        """Otro nombre para la pestaña i (p. ej. con su cuenta: «Resultados (12)»), también si ahora sale solo su icono
        (entonces va al tooltip); se vuelve a mirar si caben todas con su nombre."""
        if not (0 <= i < len(self._nombres)):
            self.setTabText(i, texto)
            return
        if self._nombres[i] == texto:
            return
        viejo, self._nombres[i] = self._nombres[i], texto
        if self._compactas:
            tip = self.tabToolTip(i)
            self.setTabToolTip(i, texto + tip[len(viejo):] if tip.startswith(viejo) else tip)
        else:
            self.setTabText(i, texto)
        self._revisar_pestanas()

    def tabTextCompleto(self, i: int) -> str:      # noqa: N802
        """El nombre de la pestaña aunque ahora salga solo su icono."""
        return self._nombres[i] if 0 <= i < len(self._nombres) else self.tabText(i)

    def resizeEvent(self, ev):                     # noqa: N802
        super().resizeEvent(ev)
        self._revisar_pestanas()

    # ---- medidas: las de la página de delante
    def _barra(self) -> int:
        tb = self.tabBar()
        return tb.sizeHint().height() if tb is not None and not tb.isHidden() else 0

    def hasHeightForWidth(self) -> bool:           # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:       # noqa: N802
        pg = self.currentWidget()
        if pg is None:
            return self._barra()
        return (pg.heightForWidth(w) if pg.hasHeightForWidth() else pg.sizeHint().height()) + self._barra()

    def sizeHint(self):                            # noqa: N802
        from PySide6.QtCore import QSize
        pg = self.currentWidget()
        ancho = max([self.widget(i).sizeHint().width() for i in range(self.count())] + [0])
        return QSize(ancho, (pg.sizeHint().height() if pg is not None else 0) + self._barra())

    def minimumSizeHint(self):                     # noqa: N802
        from PySide6.QtCore import QSize
        pg = self.currentWidget()
        tb = self.tabBar()
        ancho = max([self.widget(i).minimumSizeHint().width() for i in range(self.count())] +
                    [tb.minimumSizeHint().width() if not tb.isHidden() else 0])
        alto = pg.minimumSizeHint().expandedTo(pg.minimumSize()).height() if pg is not None else 0
        return QSize(ancho, alto + self._barra())
