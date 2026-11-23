"""
🧰 PANEL DE HERRAMIENTAS A LA DERECHA DEL VISOR (fase 5 de «Edita desde tu voz», 23/11): las herramientas que antes
abrían una ventana flotante (Exportar, Eliminar silencios, Mezcla…) y el panel de «Edita desde tu voz» viven aquí,
como PESTAÑAS, en el hueco a la derecha de la imagen (hijo del área de dibujo del visor, como el menú rápido) o, si no
cabe, como pestaña «Herramienta» junto al Inspector. Nunca flotando.

  · Como mucho 3 pestañas. La activa lleva su nombre completo; las demás, su icono y su nombre corto (si ni así
    caben, solo el icono); nunca cortadas y con el nombre entero en el tooltip.
  · Al abrir una 4.ª, la más antigua que no esté fijada (chincheta) ni trabajando vuelve a su sitio guardando su
    estado: al reabrirla está como estaba.
  · Cerrar: la ✕, doble clic en la pestaña o Esc. Ctrl+Tab pasa de una a otra.
  · Punto de acento en el botón que la abre (el de la izquierda, la barra…): clic en él la trae al frente.
  · El menú rápido del clip elegido (ui/menu_rapido.py) sale DELANTE, dentro del panel, sin contar en el límite; al
    quitar la selección vuelve la herramienta.
  · Confirmaciones dentro del panel, como barra «Sí / No» (confirmar()).

USO (cualquier herramienta):
    h = herramientas.de(win)          # (win.herramientas: uno por ventana)
    h.abrir("exportar", widget, "Exportar video", corto="Exportar", icono="download", boton=btn,
            trabajando=lambda: dlg.exportando(), al_cerrar=None, conservar=False)
    h.abrir("mezcla", fabrica=lambda: MixDialog(win), titulo=…)   # crea solo si no estaba abierta ni guardada
    h.dialogo("silencios", lambda: SilenceDialog(win, ids), "Eliminar silencios", "Silencios", "scissors")
        (un QDialog de siempre pasa a pestaña: accept/reject/done la cierran; si se esconde sola —exportar mientras
         sigue—, se guarda y vuelve cuando se enseña otra vez)
    h.cerrar(clave) · h.al_frente(clave) · h.abierta(clave) · h.widget(clave) · h.activa · h.fijar(clave)
    h.confirmar("¿Reemplazar el archivo?", al_si, al_no)            barra «Sí / No» dentro del panel
  conservar=True: el widget es de otro (p. ej. el panel de «Edita desde tu voz»): al cerrar no se destruye.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import diseno as D

MAX_PESTANAS = 3
ANCHO = 330                  # (px de diseño) ancho del panel en el hueco del visor, si hay sitio
ANCHO_MIN = 240               # (px de diseño) lo menos que se le deja si la herramienta y sus pestañas caben
ALTO_MIN = 300
CLAVE_CLIP = "__clip__"       # (la pestaña del menú rápido: no cuenta en el límite)


@dataclass
class _Herramienta:
    clave: str
    widget: QWidget
    titulo: str
    corto: str
    icono: str | None
    al_cerrar: object = None
    trabajando: object = None
    boton: QWidget | None = None
    conservar: bool = False
    fijada: bool = False
    orden: int = 0
    caja: QScrollArea | None = None
    pestana: QToolButton | None = None
    extra: dict = field(default_factory=dict)

    def ocupada(self) -> bool:
        try:
            return bool(self.trabajando and self.trabajando())
        except RuntimeError:
            return False


class _Pestana(QToolButton):
    doble = Signal()

    def mouseDoubleClickEvent(self, ev):          # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.doble.emit()
            return
        super().mouseDoubleClickEvent(ev)


class _Punto(QWidget):
    """El punto de acento en el botón que abre la herramienta (arriba a la derecha; no recibe clics)."""

    def __init__(self, boton: QWidget):
        super().__init__(boton)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setObjectName("punto_herramienta")
        lado = D.px(7)
        self.resize(lado, lado)
        boton.installEventFilter(self)
        self._colocar()

    def _colocar(self):
        b = self.parentWidget()
        self.move(max(0, b.width() - self.width() - D.px(2)), D.px(2))
        self.raise_()

    def eventFilter(self, obj, ev):               # noqa: N802
        if ev.type() in (QEvent.Resize, QEvent.Show):
            self._colocar()
        return False

    def paintEvent(self, _ev):                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(D.colores()["acento"]))
        p.drawEllipse(self.rect().adjusted(0, 0, -1, -1))
        p.end()


class _BarraConfirmar(QFrame):
    """«¿…?  [Sí] [No]» dentro del panel (en vez de una ventana de pregunta)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("herr_confirmar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(D.px(8), D.px(6), D.px(8), D.px(6))
        lay.setSpacing(D.px(6))
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        lay.addWidget(self.texto, 1)
        self.si = QPushButton("Sí")
        self.si.setObjectName("primary")
        self.no = QPushButton("No")
        lay.addWidget(self.si)
        lay.addWidget(self.no)
        self._al_si = self._al_no = None
        self.si.clicked.connect(lambda: self._responder(True))
        self.no.clicked.connect(lambda: self._responder(False))
        self.hide()

    def preguntar(self, texto: str, al_si, al_no=None, si: str = "Sí", no: str = "No"):
        self.texto.setText(texto)
        self.si.setText(si)
        self.no.setText(no)
        self._al_si, self._al_no = al_si, al_no
        self.show()
        self.si.setFocus(Qt.OtherFocusReason)

    def _responder(self, si: bool):
        fn = self._al_si if si else self._al_no
        self._al_si = self._al_no = None
        self.hide()
        if fn is not None:
            fn()

    @property
    def abierta(self) -> bool:
        return not self.isHidden()


class PanelHerramientas(QFrame):
    """Lo que se ve: la fila de pestañas (con chincheta y ✕ de la activa), la barra de confirmar y la herramienta."""

    def __init__(self, host: "Herramientas"):
        super().__init__()
        self.host = host
        self.setObjectName("panel_herramientas")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(4), D.px(4), D.px(4), D.px(4))
        lay.setSpacing(D.px(4))
        self.fila = QWidget()
        self.fila.setObjectName("herr_fila")
        fl = QHBoxLayout(self.fila)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(D.px(2))
        from .diseno import FilaFluida
        # (si no caben en una fila, en dos —con su icono y su nombre—: antes que ensanchar el panel o mandarlo junto al
        #  Inspector)
        self.zona_pestanas = self.lay_pestanas = FilaFluida(espacio=D.px(2))
        fl.addWidget(self.zona_pestanas, 1)
        self.btn_fijar = QToolButton()
        self.btn_fijar.setCheckable(True)
        self.btn_fijar.setAutoRaise(True)
        self.btn_fijar.setFocusPolicy(Qt.NoFocus)
        self.btn_fijar.setToolTip("Fijar: esta herramienta no se cierra sola al abrir otras (como mucho van 3)")
        self.btn_fijar.toggled.connect(lambda on: host.fijar(host.activa, on) if host.activa else None)
        self.btn_cerrar = QToolButton()
        self.btn_cerrar.setAutoRaise(True)
        self.btn_cerrar.setFocusPolicy(Qt.NoFocus)
        self.btn_cerrar.setToolTip("Cerrar esta herramienta (Esc o doble clic en su pestaña)")
        self.btn_cerrar.clicked.connect(lambda: host.cerrar(host.activa) if host.activa else None)
        fl.addWidget(self.btn_fijar)
        fl.addWidget(self.btn_cerrar)
        lay.addWidget(self.fila)
        self.confirmar = _BarraConfirmar()
        lay.addWidget(self.confirmar)
        self.pila = QStackedWidget()
        self.vacia = QWidget()                     # (el sitio del menú rápido cuando va delante)
        self.pila.addWidget(self.vacia)
        lay.addWidget(self.pila, 1)
        D.medida(self, lambda w: w._estilo())
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self, context=Qt.WidgetWithChildrenShortcut)
        self._esc.activated.connect(lambda: host.cerrar(host.activa) if host.activa else None)

    def _estilo(self):
        c, f = D.colores(), D.fichas()
        self.setStyleSheet(
            f"#panel_herramientas {{ background: {f['bloque']}; border: 1px solid {f['bloque_borde']}; "
            f"border-radius: {D.px(6)}px; }}"
            f"#panel_herramientas QToolButton#herr_pestana {{ color: {c['tenue']}; border: none; "
            f"border-bottom: 2px solid transparent; padding: {D.px(2)}px {D.px(5)}px; }}"
            f"#panel_herramientas QToolButton#herr_pestana:hover {{ color: {c['texto']}; }}"
            f"#panel_herramientas QToolButton#herr_pestana:checked {{ color: {c['texto']}; "
            f"border-bottom: 2px solid {c['acento']}; }}"
            f"#herr_confirmar {{ background: {f['control_hover_arriba']}; border: 1px solid {c['acento']}; "
            f"border-radius: {D.px(4)}px; }}")
        self.btn_fijar.setIcon(D.icono("pin", c["tenue"], 14))
        self.btn_cerrar.setIcon(D.icono("x", c["tenue"], 14))
        self.host.rehacer_pestanas()

    def ancho_minimo_fila(self) -> int:
        return self.btn_fijar.sizeHint().width() + self.btn_cerrar.sizeHint().width() + D.px(16)


# ====================================================================================== el anfitrión
class Herramientas(QObject):
    cambio = Signal()

    def __init__(self, win, columna: QWidget | None = None):
        """win: la ventana (atajos, «parent()» de los diálogos). columna: si se da, el panel va ARRIBA de esa columna
        (p. ej. la derecha de Miniatura) en vez de en el hueco del visor o junto al Inspector."""
        super().__init__(win)
        self.win = win
        self.columna = columna
        self._ts: dict[str, _Herramienta] = {}       # abiertas (con pestaña), en orden de pestañas
        self._guardadas: dict[str, _Herramienta] = {}  # vueltas a su sitio con su estado (por el límite o escondidas)
        self._puntos: dict[int, _Punto] = {}
        self._orden = 0
        self.activa: str | None = None
        self._clip_delante = False                   # (el menú rápido delante, en la pestaña «Clip»)
        self._herramienta_pedida = False             # (clic en una pestaña con un clip elegido: la herramienta manda)
        self._interno = 0                            # (escondiendo / enseñando desde aquí: no es la herramienta)
        self.panel = PanelHerramientas(self)
        self.garaje = QWidget()                      # (donde esperan las guardadas: escondido, nunca una ventana)
        self.garaje.hide()
        self.caja_dock = None
        self.dock = None
        self.donde: str | None = None                # "hueco" | "pestana" | "columna" | None
        self.llenar = None                           # (columna) llenar() → True: el panel usa todo el alto libre
        if columna is None:
            self.canvas = win.preview.canvas
            self.vp = self.canvas.viewport()
            self.marco = QWidget(self.vp)
            self.marco.setObjectName("herramientas_hueco")
            QVBoxLayout(self.marco).setContentsMargins(0, 0, 0, 0)
            self.marco.hide()
            self.vp.installEventFilter(self)
        else:                                        # (arriba de la columna; lo de debajo, igual que siempre)
            self.canvas = self.vp = None
            self.marco = columna
            columna.layout().insertWidget(0, self.panel, 1)
            pol = self.panel.sizePolicy()
            pol.setVerticalPolicy(QSizePolicy.Expanding)
            self.panel.setSizePolicy(pol)
            self.panel.hide()
            self.donde = "columna"
            columna.installEventFilter(self)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(0)
        self._t.timeout.connect(self.recolocar)
        self._tab = QShortcut(QKeySequence("Ctrl+Tab"), win, context=Qt.WindowShortcut)
        self._tab.activated.connect(lambda: self.siguiente(1))
        self._tab_atras = QShortcut(QKeySequence("Ctrl+Shift+Tab"), win, context=Qt.WindowShortcut)
        self._tab_atras.activated.connect(lambda: self.siguiente(-1))
        tl = getattr(win, "timeline", None)
        if tl is not None and hasattr(tl, "selection_changed"):
            tl.selection_changed.connect(self._seleccion_cambio)

    # ------------------------------------------------------------------ consultar
    def claves(self) -> list[str]:
        return list(self._ts)

    def abierta(self, clave: str) -> bool:
        return clave in self._ts

    def guardada(self, clave: str) -> bool:
        return clave in self._guardadas

    def widget(self, clave: str) -> QWidget | None:
        t = self._ts.get(clave) or self._guardadas.get(clave)
        return t.widget if t is not None else None

    def contiene(self, w: QWidget) -> bool:
        return any(t.widget is w for t in list(self._ts.values()) + list(self._guardadas.values()))

    @property
    def visible(self) -> bool:
        if self.columna is not None:
            return not self.panel.isHidden()
        return (self.donde == "hueco" and self.marco.isVisible()) or \
            (self.donde == "pestana" and self.dock is not None and self.dock.isVisible())

    def clip_delante(self) -> bool:
        return self._clip_delante and self.donde == "hueco" and self.visible

    # ------------------------------------------------------------------ abrir
    def abrir(self, clave: str, widget: QWidget | None = None, titulo: str = "", corto: str | None = None,
              icono: str | None = None, *, fabrica=None, al_cerrar=None, trabajando=None, boton=None,
              conservar: bool = False, foco: QWidget | None = None) -> QWidget | None:
        """Abre (o trae al frente) la herramienta. Si estaba guardada, vuelve como estaba (el widget de entonces)."""
        t = self._ts.get(clave)
        if t is None and clave in self._guardadas:
            t = self._guardadas.pop(clave)
        if t is None:
            if widget is None and fabrica is not None:
                widget = fabrica()
            if widget is None:
                return None
            t = _Herramienta(clave, widget, titulo or clave, corto or titulo or clave, icono, al_cerrar, trabajando,
                             boton, conservar)
            widget.installEventFilter(self)
        else:
            for k, v in (("al_cerrar", al_cerrar), ("trabajando", trabajando), ("boton", boton)):
                if v is not None:
                    setattr(t, k, v)
            if titulo:
                t.titulo, t.corto = titulo, corto or t.corto
        if clave not in self._ts:
            self._orden += 1
            t.orden = self._orden
            self._ts[clave] = t
            self._meter(t)
            self._limite(clave)
        self._herramienta_pedida = True
        self._clip_delante = False
        self._activar(clave)
        self.mostrar()
        self._punto(t, True)
        if foco is not None:
            QTimer.singleShot(0, lambda f=foco: f.isVisible() and f.setFocus(Qt.OtherFocusReason))
        self.cambio.emit()
        return t.widget

    def dialogo(self, clave: str, fabrica, titulo: str, corto: str | None = None, icono: str | None = None,
                boton=None, trabajando=None) -> QDialog | None:
        """Un QDialog de siempre como pestaña (lo crea con fabrica() si no estaba abierto ni guardado)."""
        def crear():
            dlg = fabrica()
            adaptar_dialogo(dlg, self, clave)
            return dlg
        return self.abrir(clave, None, titulo, corto, icono, fabrica=crear, trabajando=trabajando, boton=boton)

    def _meter(self, t: _Herramienta):
        caja = QScrollArea()
        caja.setObjectName("herr_caja")
        caja.setWidgetResizable(True)
        caja.setFrameShape(QFrame.NoFrame)
        caja.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        caja.setStyleSheet("QScrollArea#herr_caja { background: transparent; border: none; }")
        caja.viewport().setAutoFillBackground(False)
        cont = QWidget()                           # (la herramienta pegada arriba; lo que sobra, debajo y vacío)
        cont.setObjectName("herr_contenido")
        cont.setStyleSheet("QWidget#herr_contenido { background: transparent; }")
        vl = QVBoxLayout(cont)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self._interno += 1
        try:
            vl.addWidget(t.widget)
            vl.addStretch(1)
            caja.setWidget(cont)
            t.widget.show()
        finally:
            self._interno -= 1
        t.caja = caja
        self.panel.pila.addWidget(caja)
        b = _Pestana()
        b.setObjectName("herr_pestana")
        b.setCheckable(True)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _c=False, k=t.clave: self._clic_pestana(k))
        b.doble.connect(lambda k=t.clave: self.cerrar(k))
        t.pestana = b
        self.panel.lay_pestanas.addWidget(b)

    def _sacar(self, t: _Herramienta):
        """La quita del panel (sin destruirla): al garaje."""
        self._interno += 1
        try:
            if t.caja is not None:
                cont = t.caja.takeWidget()
                t.widget.hide()
                t.widget.setParent(self.garaje)
                if cont is not None:
                    cont.deleteLater()
                self.panel.pila.removeWidget(t.caja)
                t.caja.deleteLater()
                t.caja = None
            if t.pestana is not None:
                self.panel.lay_pestanas.removeWidget(t.pestana)   # (fuera de la fila ya: nada la mira borrada)
                t.pestana.hide()
                t.pestana.deleteLater()
                t.pestana = None
        finally:
            self._interno -= 1

    def _limite(self, nueva: str):
        """Más de 3: la más antigua sin fijar ni trabajando vuelve a su sitio (guardada, con su estado)."""
        while len(self._ts) > MAX_PESTANAS:
            cand = sorted((t for k, t in self._ts.items() if k != nueva and not t.fijada and not t.ocupada()),
                          key=lambda t: t.orden)
            if not cand:
                break                                   # (todas fijadas o trabajando: se queda una de más)
            self._guardar(cand[0])

    def _guardar(self, t: _Herramienta):
        self._ts.pop(t.clave, None)
        self._sacar(t)
        if t.conservar:                                 # (es de otro: «volver a su sitio» = cerrarla en su dueño)
            self._punto(t, False)
            self._llamar(t.al_cerrar)
        else:
            self._guardadas[t.clave] = t
            self._punto(t, t.ocupada())
        if self.activa == t.clave:
            self.activa = None
        self._despues_de_quitar()

    # ------------------------------------------------------------------ cerrar
    def cerrar(self, clave: str | None, por_usuario: bool = True):
        """✕ / doble clic / Esc (por_usuario) o su dueño (por_usuario=False). Un QDialog se cierra con reject() (su
        lógica de siempre); si está trabajando, se guarda (sigue, y vuelve con su botón)."""
        if not clave:
            return
        t = self._ts.get(clave) or self._guardadas.get(clave)
        if t is None:
            return
        if clave in self._guardadas and clave not in self._ts:
            if not por_usuario:
                self._guardadas.pop(clave, None)
                self._punto(t, False)
            return
        if por_usuario and isinstance(t.widget, QDialog) and not t.conservar:
            t.widget.reject()                           # (accept/reject/done → _terminado; si se esconde → guardada)
            return
        if por_usuario and t.ocupada() and not t.conservar:
            self._guardar(t)
            return
        self._ts.pop(clave, None)
        self._sacar(t)
        self._punto(t, False)
        if self.activa == clave:
            self.activa = None
        if por_usuario:
            self._llamar(t.al_cerrar)
        if not t.conservar:
            t.widget.deleteLater()
        self._despues_de_quitar()

    def _terminado(self, clave: str, w: QWidget):
        """Un QDialog hosted terminó (accept / reject / done): fuera."""
        t = self._ts.get(clave) or self._guardadas.get(clave)
        if t is None or t.widget is not w:
            return
        self._guardadas.pop(clave, None)
        if clave in self._ts:
            self._ts.pop(clave)
            self._sacar(t)
        self._punto(t, False)
        if self.activa == clave:
            self.activa = None
        w.deleteLater()
        self._despues_de_quitar()

    def _despues_de_quitar(self):
        if self.activa is None and self._ts:
            self._activar(max(self._ts.values(), key=lambda t: t.orden).clave)
        if not self._ts:
            self.ocultar()
        self.rehacer_pestanas()
        self.cambio.emit()

    @staticmethod
    def _llamar(fn):
        if fn is not None:
            try:
                fn()
            except RuntimeError:
                pass

    # ------------------------------------------------------------------ al frente, fijar, Ctrl+Tab
    def _clic_pestana(self, clave: str):
        self._herramienta_pedida = True
        self._clip_delante = False
        self._activar(clave)
        self._avisar_menu()

    def al_frente(self, clave: str):
        if clave in self._ts:
            self._clic_pestana(clave)
            self.mostrar()
        elif clave in self._guardadas:
            t = self._guardadas[clave]
            self.abrir(clave, t.widget, t.titulo, t.corto, t.icono)

    def fijar(self, clave: str | None, si: bool = True):
        t = self._ts.get(clave or "")
        if t is not None and t.fijada != bool(si):
            t.fijada = bool(si)
            self.rehacer_pestanas()

    def siguiente(self, paso: int = 1):
        ks = list(self._ts)
        if len(ks) < 2:
            return
        i = ks.index(self.activa) if self.activa in ks else -1
        self._clic_pestana(ks[(i + paso) % len(ks)])

    def _activar(self, clave: str):
        t = self._ts.get(clave)
        if t is None:
            return
        self.activa = clave
        if not self._clip_delante and t.caja is not None:
            self.panel.pila.setCurrentWidget(t.caja)
        self.rehacer_pestanas()
        self.recolocar()

    # ------------------------------------------------------------------ el menú rápido, delante
    def _seleccion_cambio(self, *_a):
        self._herramienta_pedida = False

    def poner_clip(self, si: bool) -> bool:
        """El menú rápido pide ir delante (si=True: hay un clip elegido). Devuelve si va DENTRO del panel."""
        if not (self.donde == "hueco" and self.visible and self._ts):
            if self._clip_delante:
                self._clip_delante = False
                self.rehacer_pestanas()
            return False
        quiere = bool(si) and not self._herramienta_pedida
        if quiere != self._clip_delante:
            self._clip_delante = quiere
            if quiere:
                self.panel.pila.setCurrentWidget(self.panel.vacia)
            elif self.activa in self._ts and self._ts[self.activa].caja is not None:
                self.panel.pila.setCurrentWidget(self._ts[self.activa].caja)
            self.rehacer_pestanas()
            self.recolocar()
        return self._clip_delante

    def rect_clip(self) -> QRect | None:
        """Dónde va el menú rápido (en coordenadas del área de dibujo) cuando va delante."""
        if not self.clip_delante():
            return None
        g = self.panel.pila.geometry()
        tl = self.panel.mapTo(self.vp, g.topLeft())
        return QRect(tl, g.size())

    def _avisar_menu(self):
        mr = getattr(self.win, "menu_rapido", None)
        if mr is not None:
            try:
                mr.pedir()
            except RuntimeError:
                pass

    # ------------------------------------------------------------------ pestañas: nombre entero o corto, nunca cortado
    def rehacer_pestanas(self):
        p = getattr(self, "panel", None)
        if p is None:                                   # (aún creándose: el estilo se pone antes que el panel)
            return
        c = D.colores()
        pestanas = [(k, t) for k, t in self._ts.items() if t.pestana is not None]
        # la del menú rápido (sin contar en el límite)
        clip = getattr(self, "_pestana_clip", None)
        if self._clip_delante and clip is None:
            clip = self._pestana_clip = _Pestana()
            clip.setObjectName("herr_pestana")
            clip.setCheckable(True)
            clip.setFocusPolicy(Qt.NoFocus)
            clip.setText("Clip")
            clip.setToolTip("El menú rápido del clip elegido (sin clip elegido vuelve la herramienta)")
            clip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            p.lay_pestanas.insertWidget(0, clip)
        if clip is not None:
            clip.setVisible(self._clip_delante)
            clip.setChecked(self._clip_delante)
            clip.setIcon(D.icono("move", c["texto"], 14))
        for k, t in pestanas:
            b = t.pestana
            act = (k == self.activa and not self._clip_delante)
            b.setChecked(act)
            b.setIcon(D.icono(t.icono, c["texto"] if act else c["tenue"], 14) if t.icono else D.icono("x", "transparent", 1))
            b.setIconSize(QSize(D.px(14), D.px(14)))
            b.setToolTip(t.titulo + ("  (fijada)" if t.fijada else "") + ("\nTrabajando…" if t.ocupada() else ""))
        # SIEMPRE icono + nombre (el usuario: «compactando, pero sin que dejen de decir el nombre»): todas con su nombre
        # corto y la activa con el entero si cabe. El ancho de todas con el corto es lo mínimo que pide el panel.
        extra = p.ancho_minimo_fila() + (clip.sizeHint().width() + D.px(2) if clip is not None and clip.isVisible()
                                         else 0)
        total = 0
        for k, t in pestanas:
            b = t.pestana
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setText(t.corto)
            total += b.sizeHint().width() + D.px(2)
        self._ancho_fila = extra + max([t.pestana.sizeHint().width() for k, t in pestanas] or [0])
        at_ = self._ts.get(self.activa or "")
        if at_ is not None and at_.pestana is not None and not self._clip_delante and at_.titulo != at_.corto:
            corto_w = at_.pestana.sizeHint().width()
            at_.pestana.setText(at_.titulo)
            if extra + at_.pestana.sizeHint().width() > (p.width() or D.px(ANCHO)) or (
                    extra + total - corto_w + at_.pestana.sizeHint().width() > (p.width() or D.px(ANCHO))
                    and len(pestanas) == 1):
                at_.pestana.setText(at_.corto)         # (no cabe el entero: el corto, nunca cortado ni sin nombre)
        for k, t in pestanas:
            t.pestana.setMinimumWidth(t.pestana.sizeHint().width())   # (nunca cortada: si no cabe, el panel crece)
        at = self._ts.get(self.activa or "")
        p.btn_fijar.blockSignals(True)
        p.btn_fijar.setChecked(bool(at and at.fijada))
        p.btn_fijar.blockSignals(False)
        p.btn_fijar.setIcon(D.icono("pin", c["acento"] if (at and at.fijada) else c["tenue"], 14))
        p.btn_fijar.setVisible(at is not None and not self._clip_delante)
        p.btn_cerrar.setVisible(at is not None and not self._clip_delante)
        if self.dock is not None:                       # (junto al Inspector: la pestaña con el nombre de la herramienta)
            nombre = "Clip" if self._clip_delante else (at.corto if at is not None else "Herramienta")
            if self.dock.windowTitle() != nombre:
                self.dock.setWindowTitle(nombre)
                self.dock.nombre = nombre

    # ------------------------------------------------------------------ punto en el botón de la izquierda
    def _punto(self, t: _Herramienta, si: bool):
        b = t.boton
        if b is None:
            return
        try:
            pt = self._puntos.get(id(b))
            if si:
                if pt is None:
                    pt = self._puntos[id(b)] = _Punto(b)
                pt.show()
                pt.raise_()
            elif pt is not None:
                if not any(o.boton is b for o in list(self._ts.values()) + list(self._guardadas.values())
                           if o is not t and (o.clave in self._ts or o.ocupada())):
                    pt.hide()
        except RuntimeError:
            self._puntos.pop(id(b), None)

    # ------------------------------------------------------------------ confirmar dentro del panel
    def confirmar(self, texto: str, al_si, al_no=None, si: str = "Sí", no: str = "No"):
        def y_recolocar(fn):
            def hecho():
                if fn is not None:
                    fn()
                self._t.start()
            return hecho
        self.panel.confirmar.preguntar(texto, y_recolocar(al_si), y_recolocar(al_no), si, no)
        self._t.start()

    # ------------------------------------------------------------------ dónde va: hueco del visor o junto al Inspector
    def _hueco(self) -> QRect | None:
        if self.columna is not None:
            return None
        try:
            fr = self.canvas.mapFromScene(self.canvas.frame.rect()).boundingRect()
        except Exception:  # noqa: BLE001
            return None
        izq = max(0, fr.right() + 1)
        if izq >= self.vp.width():
            return None
        return QRect(izq, 0, self.vp.width() - izq, self.vp.height())

    _ancho_fila = 0

    def ancho_necesario(self) -> int:
        """Lo MÍNIMO que pide el panel: la herramienta activa y la fila de pestañas con sus nombres cortos (nada
        cortado). El panel prefiere ANCHO si hay sitio."""
        w = D.px(ANCHO_MIN)
        t = self._ts.get(self.activa or "")
        if t is not None:
            try:
                t.widget.ensurePolished()               # (sin pulir, las etiquetas que parten línea piden su texto
                for hijo in t.widget.findChildren(QWidget):   #  entero de ancho: parecía que no cabía)
                    hijo.ensurePolished()
                if t.widget.layout() is not None:
                    t.widget.layout().activate()
                w = max(w, t.widget.minimumSizeHint().width() + D.px(10))
            except RuntimeError:
                pass
        return max(w, int(self._ancho_fila or 0))

    def cabe(self) -> bool:
        if self.columna is not None:
            return False
        h = self._hueco()
        return h is not None and h.width() >= self.ancho_necesario() + D.px(12) and h.height() >= D.px(ALTO_MIN)

    def alto_contenido(self, ancho: int) -> int:
        """Lo que mide lo que se ve (pestañas, la barra de confirmar y la herramienta a ese ancho): el panel no es más
        alto que eso y el visor recupera el resto (regla «sin huecos»)."""
        p = self.panel
        lay = p.layout()
        m = lay.contentsMargins()
        lf = p.fila.layout()
        alto_fila = lf.totalHeightForWidth(max(10, ancho - m.left() - m.right())) if lf.hasHeightForWidth() else -1
        h = m.top() + m.bottom() + max(alto_fila, p.fila.sizeHint().height()) + lay.spacing()
        if p.confirmar.abierta:
            h += p.confirmar.sizeHint().height() + lay.spacing()
        dentro = max(10, ancho - m.left() - m.right() - D.px(14))   # (por si sale la barra vertical: la fila
        #  de botones partida no se queda corta)
        if self._clip_delante:
            mr = getattr(self.win, "menu_rapido", None)
            try:
                h += mr.alto_necesario() if mr is not None else D.px(120)
            except (RuntimeError, AttributeError):
                h += D.px(120)
            return h
        t = self._ts.get(self.activa or "")
        if t is not None:
            w = t.widget
            try:
                hh = w.heightForWidth(dentro) if w.hasHeightForWidth() else -1
                lw = w.layout()
                if hh < 0 and lw is not None and lw.hasHeightForWidth():
                    hh = lw.totalHeightForWidth(dentro)
                h += max(hh, w.sizeHint().height(), w.minimumSizeHint().height()) + D.px(2)
            except RuntimeError:
                pass
        return h

    def mostrar(self):
        if self.columna is not None:
            self.panel.show()
            self.rehacer_pestanas()
            self.recolocar()
            return
        if self.cabe():
            if self.donde != "hueco":
                self._soltar_dock()
                self.marco.layout().addWidget(self.panel)
                self.donde = "hueco"
            self.panel.show()
            self.recolocar()
            self.marco.show()
            self.marco.raise_()
            self._avisar_menu()
            return
        if self.dock is None:
            self.caja_dock = QWidget()
            QVBoxLayout(self.caja_dock).setContentsMargins(0, 0, 0, 0)
            self.dock = self.win._dock("herramientas", "Herramienta", self.caja_dock)
            self.win.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            ins = getattr(self.win, "docks", {}).get("inspector")
            if ins is not None:
                self.win.tabifyDockWidget(ins, self.dock)
        if self.donde != "pestana":
            self.marco.hide()
            self.caja_dock.layout().addWidget(self.panel)
            self.donde = "pestana"
            ins = getattr(self.win, "docks", {}).get("inspector")
            if ins is not None and self._ancho_previo is None:
                self._ancho_previo = ins.width()     # (al irse, el lado derecho vuelve a su ancho de antes)
        self.caja_dock.setMinimumWidth(min(self.ancho_necesario(), D.px(560)))
        self.panel.show()
        self.dock.show()
        self.dock.raise_()
        self.rehacer_pestanas()
        self._avisar_menu()
        self._t.start()                                  # (ya pulida y colocada, ¿cabe junto al visor? se mira otra vez)

    _ancho_previo = None

    def _soltar_dock(self):
        """Fuera de la pestaña junto al Inspector: escondida y el lado derecho, al ancho que tenía (si no, el visor
        se queda estrecho y la siguiente herramienta ya no cabría en el hueco)."""
        if self.dock is None:
            return
        self.dock.hide()
        if self.caja_dock is not None:
            self.caja_dock.setMinimumWidth(0)
        ins = getattr(self.win, "docks", {}).get("inspector")
        if ins is not None and self._ancho_previo:
            try:
                self.win.resizeDocks([ins], [int(self._ancho_previo)], Qt.Horizontal)
            except RuntimeError:
                pass
        self._ancho_previo = None

    def ocultar(self):
        if self.columna is not None:
            self.panel.hide()
            return
        self.marco.hide()
        self._soltar_dock()
        if self.donde == "pestana":
            self.donde = None                        # (la próxima vez se vuelve a mirar si cabe en el hueco)
        if self._clip_delante:
            self._clip_delante = False
        self._avisar_menu()

    def recolocar(self):
        if self.columna is not None:                  # (arriba de la columna: a la altura de su contenido)
            if not self._ts:
                return
            # (como mucho su contenido; si la columna no da para todo, comparte con lo de debajo —nunca la agranda—)
            ancho = max(10, self.columna.width())
            lleno = bool(self.llenar and self.llenar())
            alto = 16777215 if lleno else self.alto_contenido(ancho)
            self.panel.setMinimumHeight(min(alto, D.px(120)))
            self.panel.setMaximumHeight(alto)
            self.rehacer_pestanas()
            return
        if self.donde == "pestana" and self._ts and self.dock is not None and self.dock.isVisible():
            if self.cabe():                             # (ya cabe junto al visor —p. ej. tras pulirse y partir sus
                self.mostrar()                          #  textos, o al cerrar la ancha—: a su sitio, el hueco)
            return
        if self.donde != "hueco" or not self._ts or self.marco.isHidden() and not self.panel.isVisibleTo(self.marco):
            return
        if not self.cabe():                             # (se estrechó el visor: a la pestaña junto al Inspector)
            self.mostrar()
            return
        h = self._hueco()
        m = D.px(6)
        w = min(h.width() - 2 * m, max(D.px(ANCHO), self.ancho_necesario()))
        x = h.right() - w - m + 1
        alto = min(h.height() - 2 * m, self.alto_contenido(w))     # (no más alto que lo que tiene: pegado arriba)
        self.marco.setGeometry(x, m, w, alto)
        self.rehacer_pestanas()

    # ------------------------------------------------------------------ eventos
    def eventFilter(self, obj, ev):                     # noqa: N802
        if self.columna is not None and obj is self.columna:
            if ev.type() == QEvent.Resize and self._ts:
                self._t.start()
            return False
        if obj is self.vp:
            if ev.type() == QEvent.Resize and self.donde in ("hueco", "pestana") and self._ts:
                self._t.start()
            return False
        if self._interno or not isinstance(obj, QWidget):
            return False
        et = ev.type()
        if et == QEvent.LayoutRequest and self.donde in ("hueco", "pestana", "columna") and self._ts:
            self._t.start()                              # (la herramienta creció o encogió: el panel, con ella)
        clave = next((k for k, t in list(self._ts.items()) + list(self._guardadas.items()) if t.widget is obj), None)
        if clave is None:
            return False
        if et == QEvent.HideToParent and clave in self._ts:
            QTimer.singleShot(0, lambda k=clave, w=obj: self._se_escondio(k, w))
        elif et in (QEvent.ShowToParent, QEvent.Show) and clave in self._guardadas:
            QTimer.singleShot(0, lambda k=clave: self.al_frente(k))
        return False

    def _se_escondio(self, clave: str, w: QWidget):
        """La herramienta se escondió sola (p. ej. exportar con «Ir a Miniatura»): se guarda con su estado y vuelve
        cuando se enseñe otra vez. Si ya terminó (QDialog acabado), _terminado la quitó."""
        t = self._ts.get(clave)
        if t is None or t.widget is not w or self._interno:
            return
        try:
            if not w.isHidden():
                return
        except RuntimeError:
            return
        if isinstance(w, QDialog) and not t.conservar and not t.ocupada():
            self._terminado(clave, w)                    # (un diálogo que se cierra con close(): se cierra su pestaña)
            return
        self._guardar(t)


def adaptar_dialogo(dlg: QDialog, host: Herramientas, clave: str) -> QDialog:
    """Un QDialog pasa a ser el contenido de una pestaña: sin marco de ventana, sin ancho mínimo de ventana, los
    desplegables al ancho de su texto (no estirados) y sus formularios con la etiqueta encima si no cabe al lado.
    accept / reject / done → se cierra la pestaña; los diálogos pueden preguntar con host.confirmar (dlg.herramientas)."""
    from PySide6.QtWidgets import QComboBox, QFormLayout
    dlg.setWindowFlags(Qt.Widget)
    dlg.setModal(False)
    dlg.setSizeGripEnabled(False)
    dlg.setMinimumSize(0, 0)
    if dlg.layout() is not None:                   # (márgenes de panel, no de ventana: más sitio para lo de dentro)
        dlg.layout().setContentsMargins(D.px(4), D.px(4), D.px(4), D.px(4))
    dlg.herramientas = host
    dlg.en_panel = True
    ventana = host.win                             # (dentro del panel, parent() sería la caja: el diálogo sigue viendo
    dlg.parent = lambda: ventana                   #  la ventana, como antes; solo cambia para el código Python)
    for cb in dlg.findChildren(QComboBox):
        cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        pol = cb.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Maximum)
        cb.setSizePolicy(pol)
    for fl in dlg.findChildren(QFormLayout):
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
    _partir_textos(dlg)
    compactar = getattr(dlg, "compactar", None)
    if callable(compactar):
        compactar()
    dlg.finished.connect(lambda _r, k=clave, w=dlg: host._terminado(k, w))
    return dlg


LIMITE_TEXTO = 250            # (px de diseño) una etiqueta o casilla más ancha parte su texto en líneas


def _partir_textos(dlg: QWidget):
    """En ~300 px nada se corta ni ensancha el panel: las etiquetas largas parten línea; las casillas y opciones de
    texto largo pasan a «casilla + texto que parte línea» (clic en el texto = clic en la casilla); las pestañas de
    un QTabWidget, con flechas si no caben."""
    from PySide6.QtWidgets import QAbstractButton, QBoxLayout, QCheckBox, QFormLayout, QLayout, QRadioButton, QTabWidget
    lim = D.px(LIMITE_TEXTO)
    for lb in dlg.findChildren(QLabel):
        if not lb.wordWrap() and lb.text() and lb.pixmap().isNull() and lb.minimumSizeHint().width() > lim:
            lb.setWordWrap(True)
    for tw in dlg.findChildren(QTabWidget):
        tw.setUsesScrollButtons(True)
        tw.tabBar().setExpanding(False)
    for b in dlg.findChildren(QAbstractButton):
        if not isinstance(b, (QCheckBox, QRadioButton)) or not b.text() or b.sizeHint().width() <= lim:
            continue
        padre = b.parentWidget()
        if padre is None:
            continue
        lay = next((l for l in padre.findChildren(QLayout) if l.indexOf(b) >= 0), None)
        if lay is None and padre.layout() is not None and padre.layout().indexOf(b) >= 0:
            lay = padre.layout()
        if not isinstance(lay, (QBoxLayout, QFormLayout)):
            continue
        cont = QWidget()
        hl = QHBoxLayout(cont)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(D.px(4))
        texto = QLabel(b.text().replace("&", ""))
        texto.setWordWrap(True)
        texto.setToolTip(b.toolTip())
        texto.setEnabled(b.isEnabled())
        texto.setCursor(Qt.PointingHandCursor)
        texto.mousePressEvent = lambda _e, bb=b: bb.click() if bb.isEnabled() else None
        if isinstance(lay, QFormLayout):
            fila, rol = lay.getWidgetPosition(b)
            lay.removeWidget(b)
            b.setText("")
            hl.addWidget(b, 0, Qt.AlignTop)
            hl.addWidget(texto, 1)
            lay.setWidget(fila, rol, cont)
        else:
            i = lay.indexOf(b)
            b.setText("")
            hl.addWidget(b, 0, Qt.AlignTop)          # (al meterla aquí sale de su sitio anterior)
            hl.addWidget(texto, 1)
            lay.insertWidget(i, cont)
        b.texto_partido = texto
    # filas de botones que no caben: en una fila que se parte (FilaFluida), en su mismo sitio y orden
    from PySide6.QtWidgets import QHBoxLayout as _H, QPushButton, QToolButton
    from .diseno import FilaFluida
    grupos: dict[int, tuple] = {}
    for b in dlg.findChildren(QAbstractButton):
        if not isinstance(b, (QPushButton, QToolButton)) or b.parentWidget() is None:
            continue
        lay = next((l for l in b.parentWidget().findChildren(QLayout) if isinstance(l, _H) and l.indexOf(b) >= 0),
                   None)
        if lay is None and isinstance(b.parentWidget().layout(), _H) and b.parentWidget().layout().indexOf(b) >= 0:
            lay = b.parentWidget().layout()
        if lay is not None:
            grupos.setdefault(id(lay), (lay, []))[1].append(b)
    for lay, bs in grupos.values():
        if lay.minimumSize().width() <= lim and (len(bs) < 2 or
                                                 sum(b.sizeHint().width() for b in bs) + D.px(6) * len(bs) <= lim):
            continue
        padre = bs[0].parentWidget()                 # (toda la fila: botones, etiquetas y desplegables, en su orden)
        bs = [w for w in padre.findChildren(QWidget) if w.parentWidget() is padre and lay.indexOf(w) >= 0]
        bs.sort(key=lambda b: lay.indexOf(b))
        i = lay.indexOf(bs[0])
        fila = FilaFluida(espacio=D.px(6))
        for b in bs:
            oculto = b.isHidden()
            fila.addWidget(b)                        # (sale de su fila de antes)
            if oculto:
                b.hide()
        lay.insertWidget(i, fila, 1)


CIERRAN = {"cerrar", "cancelar", "close", "cancel"}


def quitar_cerrar(dlg: QWidget):
    """En el panel sobra un «Cerrar» / «Cancelar» que solo cierra: ya está la ✕ de la pestaña (que hace lo mismo:
    reject). Se quedan los que hacen algo más mientras trabaja (dlg.botones_de_trabajo: p. ej. el «Cerrar» que pasa
    a «Cancelar» mientras copia o crea)."""
    from PySide6.QtWidgets import QDialogButtonBox, QPushButton
    guardar_ = {id(b) for b in getattr(dlg, "botones_de_trabajo", ()) or ()}
    for b in dlg.findChildren(QPushButton):
        if id(b) in guardar_:
            continue
        txt = "".join(ch for ch in b.text() if ch.isalpha()).lower()
        if txt not in CIERRAN:
            continue
        caja = b.parentWidget()
        if isinstance(caja, QDialogButtonBox) and caja.buttonRole(b) not in (QDialogButtonBox.RejectRole,
                                                                            QDialogButtonBox.DestructiveRole):
            continue
        b.hide()
        b.setProperty("solo_cierra", True)


def abrir_dialogo(desde, clave: str, fabrica, titulo: str, corto: str | None = None, icono: str | None = None,
                  al_terminar=None, boton=None, trabajando=None) -> QDialog | None:
    """Lo que antes era «Dialogo(...).exec()»: el QDialog como pestaña del panel de herramientas de la ventana de
    `desde` (un widget o la ventana), sin bloquear. al_terminar(resultado) cuando se cierra (accept = 1, reject = 0):
    ahí va lo que antes venía después del exec(). Sin panel (una ventana suelta, p. ej. en una prueba), ventana no
    bloqueante con el mismo al_terminar."""
    win = desde.window() if isinstance(desde, QWidget) else desde
    h = None
    w = desde if isinstance(desde, QWidget) else None
    while w is not None and h is None:               # (el anfitrión más cercano: el de Miniatura antes que el de
        cand = w.__dict__.get("herramientas") if hasattr(w, "__dict__") else None   # la ventana)
        h = cand if isinstance(cand, Herramientas) else None
        w = w.parentWidget()
    if h is None and win is not None and hasattr(win, "preview") and hasattr(win.preview, "canvas"):
        h = de(win)
    if h is not None:

        def crear():
            dlg_ = fabrica()
            quitar_cerrar(dlg_)
            return dlg_
        dlg = h.dialogo(clave, crear, titulo, corto, icono, boton=boton, trabajando=trabajando)
        if dlg is not None and al_terminar is not None and not getattr(dlg, "_al_terminar_puesto", False):
            dlg._al_terminar_puesto = True
            dlg.finished.connect(al_terminar)
        return dlg
    dlg = fabrica()
    if al_terminar is not None:
        dlg.finished.connect(al_terminar)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.open()
    return dlg


def instalar_en_columna(ventana: QWidget, columna: QWidget) -> Herramientas:
    """El mismo anfitrión arriba de una columna (p. ej. la derecha de Miniatura). columna debe tener un QVBoxLayout:
    el panel va primero y lo que ya tuviera queda debajo. ventana.herramientas = el anfitrión."""
    h = Herramientas(ventana, columna)
    ventana.herramientas = h
    return h


def de(win) -> Herramientas:
    """El anfitrión de la ventana (se crea la primera vez)."""
    h = getattr(win, "herramientas", None)
    if h is None:
        h = win.herramientas = Herramientas(win)
    return h
