"""
🎙 «Edita desde tu voz» — el botón insignia y su panel (23/11, plan notas_claude/PLAN_EDITA_DESDE_TU_VOZ.md).

  · El botón va arriba, junto al logo, con el acento y siempre a la vista. Brilla suave hasta el primer uso (sin
    ventanas de bienvenida). Dice el paso («Paso 2 de 3 · 40 %») y, mientras trabaja, lleva al lado una «x» para
    cancelar. Al reabrir el proyecto sigue donde iba (Project.edita_voz + la transcripción guardada por archivo).
  · Su panel se abre en el hueco a la derecha del visor (junto al menú rápido del clip); si no cabe, como pestaña
    junto al Inspector. Nunca en una ventana flotante. Las preguntas son barras dentro del panel, no diálogos.
  · Paso 1 «Tu voz»: [Elegir grabación] abre la carpeta de OBS (o la última usada, o Vídeos) y debajo salen las
    grabaciones más recientes de esa carpeta, la primera arriba. Casos: varias partes, OBS grabando todavía, nube o
    red (copia en la caché), formato raro (copia convertida), varias pistas (la 2 de OBS; si duda, se elige
    escuchando), la imagen del juego (solo la voz / también su imagen), voz mezclada (separarla), voz ya editada
    (se salta el paso 2).
  · La transcripción empieza al elegir el archivo, antes de colocarlo, por trozos de 1 min: los pasos 2 y 3 pueden
    empezar con los primeros minutos. Nunca bloquea la ventana; el progreso va en el botón y se puede cancelar.
    Si cambias de pestaña (Horizontal / Vertical) sigue con su proyecto; lo hecho se guarda por archivo.

El paso 2 («Pule tu voz») y el 3 («Arma tu video») se enchufan con EditaVoz.poner_paso(n, widget).
instalar(win) lo engancha (una línea en main_window, tras el menú rápido).
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from ..core import edita_voz as EV
from . import diseno as D

AJ_USADO = "edita_voz/usado"
AJ_CARPETA = "edita_voz/ultima_carpeta"
BLOQUE = 60.0                  # la transcripción entrega lo hecho cada minuto de audio
ANCHO_PANEL = 330              # (px de diseño) ancho del panel en el hueco del visor
TIP_BOTON = ("Edita desde tu voz: eliges la grabación de tu voz y Reclaimer la coloca, la transcribe, te ayuda a "
             "pulirla (tomas repetidas, trabas, pausas) y arma el video con tu material. Nada se corta sin tu ✓; "
             "todo se deshace con Ctrl+Z.")


def QFontPeso():
    """El peso de los títulos (seminegrita)."""
    from PySide6.QtGui import QFont
    return QFont.DemiBold


def _ajustes() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


def _fmt(s: float) -> str:
    s = max(0, int(s))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ====================================================================================== piezas pequeñas
class Barra(QFrame):
    """Una pregunta dentro del panel (en vez de un diálogo): texto + botones. preguntar(texto, [(clave, texto, tip)],
    al_responder(clave))."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ev_barra")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(8), D.px(6), D.px(8), D.px(6))
        lay.setSpacing(D.px(4))
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        self.texto.setFont(D.fuente(D.LETRA_P))
        lay.addWidget(self.texto)
        self.fila = QVBoxLayout()            # (uno debajo de otro: nunca cortados en un panel estrecho)
        self.fila.setSpacing(D.px(3))
        lay.addLayout(self.fila)
        self._fn = None
        self.botones: dict[str, QPushButton] = {}
        self.hide()

    def preguntar(self, texto: str, opciones: list, al_responder, tip: str = ""):
        for b in self.botones.values():        # (sin recorrer el layout desde Python)
            b.hide()
            b.deleteLater()
        self.botones = {}
        self.texto.setText(texto)
        self.texto.setToolTip(tip)
        self._fn = al_responder
        for i, op in enumerate(opciones):
            clave, txt = op[0], op[1]
            b = QPushButton(txt)
            if i == 0:
                b.setObjectName("primary")
            if len(op) > 2 and op[2]:
                b.setToolTip(op[2])
            b.clicked.connect(lambda _=False, k=clave: self.responder(k))
            self.fila.addWidget(b)
            self.botones[clave] = b
        c = D.colores()
        self.setStyleSheet(f"#ev_barra {{ background: {D.fichas()['bloque']}; border: 1px solid {c['acento']}; "
                           f"border-radius: {D.px(5)}px; }}")
        self.show()
        if opciones:
            QTimer.singleShot(0, lambda: self.botones and next(iter(self.botones.values())).setFocus())

    def responder(self, clave: str):
        fn, self._fn = self._fn, None
        self.hide()
        if fn is not None:
            fn(clave)

    @property
    def abierta(self) -> bool:
        return not self.isHidden()


class FilaGrabacion(QFrame):
    """Una grabación reciente: nombre entero (en varias líneas si hace falta) y fecha · tamaño. Clic = elegirla."""
    elegida = Signal(str)

    def __init__(self, ruta: str, parent=None):
        super().__init__(parent)
        self.ruta = ruta
        self.setObjectName("ev_fila")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(D.px(6), D.px(3), D.px(6), D.px(3))
        lay.setSpacing(D.px(6))
        ic = QLabel()
        es_video = os.path.splitext(ruta)[1].lower() in EV.VIDEO_EXT
        ic.setPixmap(D.pixmap_icono("film" if es_video else "mic", D.colores()["tenue"], D.px(14)))
        ic.setAlignment(Qt.AlignTop)
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        nombre = QLabel(os.path.basename(ruta))
        nombre.setWordWrap(True)
        nombre.setFont(D.fuente(D.LETRA_P))
        try:
            st = os.stat(ruta)
            meta = f"{time.strftime('%d/%m %H:%M', time.localtime(st.st_mtime))} · {st.st_size / 1e6:.0f} MB"
        except OSError:
            meta = ""
        m = QLabel(meta)
        m.setFont(D.fuente(D.LETRA_P - 1))
        m.setStyleSheet(f"color: {D.colores()['tenue']};")
        col.addWidget(nombre)
        col.addWidget(m)
        lay.addLayout(col, 1)
        self.setToolTip(ruta)
        f = D.fichas()
        self.setStyleSheet(f"#ev_fila {{ border: 1px solid transparent; border-radius: {D.px(4)}px; }}"
                           f"#ev_fila:hover, #ev_fila:focus {{ background: {f['control_hover_arriba']}; "
                           f"border-color: {f['control_borde']}; }}")

    def mousePressEvent(self, e):          # noqa: N802
        if e.button() == Qt.LeftButton:
            self.elegida.emit(self.ruta)
        super().mousePressEvent(e)

    def keyPressEvent(self, e):            # noqa: N802
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.elegida.emit(self.ruta)
            return
        super().keyPressEvent(e)


# ====================================================================================== el botón insignia
class _Sol(QWidget):
    """El brillo de sol del botón insignia: una capa encima de la ventana (no la recorta la barra de arriba ni recibe
    clics) que pinta un resplandor cálido alrededor de la pastilla —sale desde detrás de ella— y una luz suave
    dentro. v = 0 (nada) … 1 (sol entero)."""
    ALCANCE = 22           # (px de diseño) hasta dónde llega el resplandor (pequeño: no tapa las pestañas)

    def __init__(self, boton: QWidget):
        win = boton.window()
        super().__init__(win)
        self.boton = boton
        self.v = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._colocar()
        self.show()
        self.raise_()

    def _colocar(self):
        r = D.px(self.ALCANCE)
        tl = self.boton.mapTo(self.parentWidget(), self.boton.rect().topLeft())
        self.setGeometry(QRect(tl, self.boton.size()).adjusted(-r, -r, r, r))

    def poner(self, v: float):
        self.v = v
        self._colocar()
        self.raise_()
        self.update()

    def paintEvent(self, e):                   # noqa: N802
        """v = avance de la onda (0 = antes del borde izquierdo … 1 = pasado el derecho). El resplandor cálido rodea
        la pastilla, pero solo donde pasa la onda; aparece y se apaga suave (sale y se vuelve detrás del botón)."""
        t = self.v
        fuerza = math.sin(math.pi * max(0.0, min(1.0, t)))
        if fuerza <= 0.01 or not self.boton.isVisible():
            return
        r = D.px(self.ALCANCE)
        pastilla = QRectF(r, r, self.boton.width(), self.boton.height())
        radio = pastilla.height() / 2
        dpr = self.devicePixelRatioF()
        img = QImage(int(self.width() * dpr) + 1, int(self.height() * dpr) + 1, QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing, True)
        q.setPen(Qt.NoPen)
        fuera = QPainterPath()
        fuera.addRect(QRectF(self.rect()))
        dentro = QPainterPath()
        dentro.addRoundedRect(pastilla, radio, radio)
        q.setClipPath(fuera.subtracted(dentro))            # el resplandor sale de DETRÁS de la pastilla
        alcance = r * 0.85
        pasos = 18
        for i in range(pasos, 0, -1):                      # capas: de fuera (tenue) a dentro (fuerte)
            d = alcance * i / pasos
            q.setBrush(QColor(255, 222, 150, int((1.0 - i / pasos) ** 2 * 60)))
            q.drawRoundedRect(pastilla.adjusted(-d, -d, d, d), radio + d, radio + d)
        q.setClipping(False)                               # la luz de dentro, suave (el texto se sigue leyendo)
        q.setBrush(QColor(255, 240, 200, 45))
        q.drawRoundedRect(pastilla, radio, radio)
        banda = max(pastilla.width() * 0.45, D.px(50))     # la onda: una franja que cruza de izquierda a derecha
        cx = pastilla.left() - banda + (pastilla.width() + 2 * banda) * t
        m = QLinearGradient(cx - banda, 0, cx + banda, 0)
        m.setColorAt(0.0, QColor(0, 0, 0, 0))
        m.setColorAt(0.5, QColor(0, 0, 0, int(255 * fuerza)))
        m.setColorAt(1.0, QColor(0, 0, 0, 0))
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        q.fillRect(QRectF(self.rect()), m)
        q.end()
        p = QPainter(self)
        p.drawImage(0, 0, img)
        p.end()


class BotonEditaVoz(QWidget):
    """El botón de arriba (con el acento) y su «x» de cancelar mientras trabaja."""
    pulsado = Signal()
    cancelar = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("edita_voz_boton")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(2))
        self.boton = QToolButton()
        self.boton.setObjectName("edita_voz_principal")
        self.boton.setText("Edita desde tu voz")
        self.boton.setToolTip(TIP_BOTON)
        self.boton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.boton.setCursor(Qt.PointingHandCursor)
        self.boton.setFocusPolicy(Qt.NoFocus)
        self.boton.clicked.connect(self.pulsado)
        self.x = QToolButton()
        self.x.setObjectName("edita_voz_cancelar")
        self.x.setToolTip("Cancelar lo que está haciendo «Edita desde tu voz» (lo hecho se queda y se puede deshacer)")
        self.x.setCursor(Qt.PointingHandCursor)
        self.x.setFocusPolicy(Qt.NoFocus)
        self.x.clicked.connect(self.cancelar)
        self.x.hide()
        lay.addWidget(self.boton)
        lay.addWidget(self.x)
        self._brillo = None
        self._anim = None
        D.medida(self, lambda w: w.estilo())
        if str(_ajustes().value(AJ_USADO, "false")).lower() != "true":
            self.brillar(True)

    def estilo(self):
        c = D.colores()
        alto = D.px(22)
        self.boton.setFixedHeight(alto)
        self.x.setFixedSize(alto, alto)
        self.boton.setFont(D.fuente(D.LETRA_P, QFontPeso()))
        self.boton.setIconSize(QSize(D.px(14), D.px(14)))
        self.boton.setIcon(D.icono("mic", c["sobre_acento"], 14))
        self.x.setIcon(D.icono("x", c["texto"], 14))
        self.boton.setStyleSheet(
            f"#edita_voz_principal {{ background: {c['acento']}; color: {c['sobre_acento']}; border: none; "
            f"border-radius: {D.px(11)}px; padding: 0 {D.px(10)}px 0 {D.px(8)}px; }}"
            f"#edita_voz_principal:hover {{ background: {c['acento_hi']}; }}"
            f"#edita_voz_principal:pressed {{ background: {c['acento_pulsado']}; }}")
        self.x.setStyleSheet(f"#edita_voz_cancelar {{ border: none; border-radius: {D.px(11)}px; }}"
                             f"#edita_voz_cancelar:hover {{ background: {D.fichas()['control_hover_arriba']}; }}")

    SOL_MS = 3000          # el brillo de sol: sale desde dentro, se queda un momento y se vuelve detrás del botón
    SOL_ESPERA_MS = 900    # (tras abrirse la ventana, para que se vea)

    def brillar(self, on: bool):
        """Hasta el primer uso: al abrir Reclaimer, UNA vez, un brillo que sale desde dentro del botón como un sol
        (~3 s) y se vuelve detrás de él. Nada de parpadeos ni bucles."""
        self._sin_usar = bool(on)
        if on:
            if self.isVisible():
                QTimer.singleShot(self.SOL_ESPERA_MS, self._sol)
            else:
                self._sol_al_mostrar = True
        else:
            self._sol_al_mostrar = False
            self._quitar_sol()

    def showEvent(self, e):                     # noqa: N802
        super().showEvent(e)
        if self.__dict__.get("_sol_al_mostrar"):
            self._sol_al_mostrar = False
            QTimer.singleShot(self.SOL_ESPERA_MS, self._sol)

    def _sol(self):
        if not self.__dict__.get("_sin_usar") or self._brillo is not None or not self.isVisible():
            return
        self._brillo = _Sol(self.boton)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)                # la onda cruza de izquierda a derecha…
        self._anim.setEndValue(1.0)                  # …y se apaga detrás del botón
        self._anim.setDuration(self.SOL_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._sol_paso)
        self._anim.finished.connect(self._quitar_sol)
        self._anim.start()

    def _sol_paso(self, v):
        if self._brillo is None:
            return
        self._brillo.poner(max(0.0, min(1.0, float(v))))

    def _quitar_sol(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        if self._brillo is not None:
            self._brillo.hide()
            self._brillo.deleteLater()
            self._brillo = None

    @property
    def brillando(self) -> bool:
        """Aún sin usar (el brillo de sol sale al abrir hasta que se use por primera vez)."""
        return bool(self.__dict__.get("_sin_usar"))

    def poner(self, texto: str, trabajando: bool, tip_extra: str = ""):
        self.boton.setText(texto)
        self.boton.setToolTip(texto + "\n" + TIP_BOTON + (f"\n\n{tip_extra}" if tip_extra else ""))
        self.x.setVisible(trabajando)
        self.updateGeometry()
        self._ajustar()

    # (nada cortado: si la barra de arriba no deja sitio, solo el icono; el texto entero, en el tooltip)
    def _ancho_texto(self) -> int:
        fm = self.boton.fontMetrics()
        a = D.px(22)
        return (D.px(14) + fm.horizontalAdvance(self.boton.text()) + D.px(28)
                + (a + D.px(2) if not self.x.isHidden() else 0))

    def sizeHint(self):                        # noqa: N802
        return QSize(self._ancho_texto(), D.px(22))

    def minimumSizeHint(self):                 # noqa: N802
        a = D.px(22)
        return QSize(a + (a + D.px(2) if not self.x.isHidden() else 0), a)

    def resizeEvent(self, e):                  # noqa: N802
        super().resizeEvent(e)
        self._ajustar()

    def _ajustar(self):
        solo_icono = self.isVisible() and self.width() + 1 < self._ancho_texto()
        estilo = Qt.ToolButtonIconOnly if solo_icono else Qt.ToolButtonTextBesideIcon
        if self.boton.toolButtonStyle() != estilo:
            self.boton.setToolButtonStyle(estilo)


# ====================================================================================== el panel
class PaginaVoz(QWidget):
    """Paso 1: «¿Dónde está la voz de tu video?» · [Elegir grabación] · las más recientes · preguntas · progreso."""

    def __init__(self, ev: "EditaVoz"):
        super().__init__()
        self.ev = ev
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(6))
        self.titulo = QLabel("¿Dónde está la voz de tu video?")
        self.titulo.setWordWrap(True)
        self.titulo.setFont(D.fuente(D.LETRA_G, QFontPeso()))
        lay.addWidget(self.titulo)
        self.btn_elegir = QPushButton("Elegir grabación")
        self.btn_elegir.setObjectName("primary")
        self.btn_elegir.setIcon(D.icono("folder-open", D.colores()["sobre_acento"], 16))
        self.btn_elegir.setToolTip("Abre la carpeta de grabaciones de OBS (o la última que usaste, o Vídeos). Puedes "
                                   "elegir varias partes a la vez: se colocan en orden por nombre y fecha.")
        self.btn_elegir.clicked.connect(ev.elegir_con_dialogo)
        lay.addWidget(self.btn_elegir)
        self.chk_editada = QCheckBox("Ya está editada")
        self.chk_editada.setToolTip("Tu voz ya viene editada (o es un clip compuesto): se salta «Pule tu voz» y va "
                                    "directa a «Arma tu video».")
        lay.addWidget(self.chk_editada)
        self.barra = Barra()
        lay.addWidget(self.barra)
        # progreso (en el panel y en el botón)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        self.estado.setFont(D.fuente(D.LETRA_P))
        self.estado.setStyleSheet(f"color: {D.colores()['tenue']};")
        self.estado.hide()
        lay.addWidget(self.estado)
        fila = QHBoxLayout()
        fila.setSpacing(D.px(4))
        self.barra_prog = QProgressBar()
        self.barra_prog.setRange(0, 1000)
        self.barra_prog.setTextVisible(False)
        self.barra_prog.setFixedHeight(D.px(6))
        self.btn_cancelar = QToolButton()
        self.btn_cancelar.setIcon(D.icono("x", D.colores()["texto"], 14))
        self.btn_cancelar.setToolTip("Cancelar (lo hecho se queda y se puede deshacer)")
        self.btn_cancelar.setAutoRaise(True)
        self.btn_cancelar.clicked.connect(ev.cancelar)
        fila.addWidget(self.barra_prog, 1)
        fila.addWidget(self.btn_cancelar)
        self.caja_prog = QWidget()
        self.caja_prog.setLayout(fila)
        fila.setContentsMargins(0, 0, 0, 0)
        self.caja_prog.hide()
        lay.addWidget(self.caja_prog)
        # recientes
        self.cab_recientes = QLabel("Recientes")
        self.cab_recientes.setFont(D.fuente(D.LETRA_P, QFontPeso()))
        self.cab_recientes.setStyleSheet(f"color: {D.GRIS_TITULO};")
        lay.addWidget(self.cab_recientes)
        self.lista = QVBoxLayout()
        self.lista.setSpacing(D.px(1))
        self.filas: list[FilaGrabacion] = []
        lay.addLayout(self.lista)
        lay.addStretch(1)

    def rellenar_recientes(self, carpeta: str, de_donde: str):
        for w in self.filas:                   # (sin recorrer el layout desde Python)
            w.hide()
            w.deleteLater()
        self.filas = []
        rutas = EV.recientes(carpeta) if carpeta else []
        quien = {"obs": "grabaciones de OBS", "ultima": "la última carpeta que usaste", "videos": "tu carpeta Vídeos"}
        self.cab_recientes.setText("Recientes")
        self.cab_recientes.setToolTip(f"Lo más reciente de {quien.get(de_donde, 'la carpeta')}: {carpeta}")
        self.cab_recientes.setVisible(bool(rutas))
        for r in rutas:
            f = FilaGrabacion(r)
            f.elegida.connect(lambda ruta: self.ev.elegir([ruta]))
            self.lista.addWidget(f)
            self.filas.append(f)

    def progreso(self, frac: float | None, texto: str):
        trabajando = frac is not None
        self.caja_prog.setVisible(trabajando)
        self.estado.setVisible(bool(texto))
        self.estado.setText(texto)
        if trabajando:
            if frac <= 0:
                self.barra_prog.setRange(0, 0)
            else:
                self.barra_prog.setRange(0, 1000)
                self.barra_prog.setValue(int(frac * 1000))


class PanelEditaVoz(QFrame):
    """El panel: cabecera (nombre + cerrar), los 3 pasos como pestañas pequeñas y la página del paso."""

    def __init__(self, ev: "EditaVoz"):
        super().__init__()
        self.ev = ev
        self.setObjectName("edita_voz_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(10), D.px(8), D.px(10), D.px(10))
        lay.setSpacing(D.px(8))
        self.cabecera = QWidget()               # (en la pestaña junto al Inspector sobra: el panel ya tiene título)
        cab = QHBoxLayout(self.cabecera)
        cab.setContentsMargins(0, 0, 0, 0)
        cab.setSpacing(D.px(4))
        ic = QLabel()
        ic.setPixmap(D.pixmap_icono("mic", D.colores()["acento"], D.px(16)))
        cab.addWidget(ic)
        t = QLabel("Edita desde tu voz")
        t.setFont(D.fuente(D.LETRA_M, QFontPeso()))
        cab.addWidget(t, 1)
        self.btn_cerrar = QToolButton()
        self.btn_cerrar.setIcon(D.icono("x", D.colores()["tenue"], 14))
        self.btn_cerrar.setAutoRaise(True)
        self.btn_cerrar.setToolTip("Cerrar el panel (lo que esté haciendo sigue; el botón de arriba lo vuelve a abrir)")
        self.btn_cerrar.clicked.connect(ev.cerrar_panel)
        cab.addWidget(self.btn_cerrar)
        lay.addWidget(self.cabecera)
        fila = QHBoxLayout()
        fila.setSpacing(D.px(3))
        self.chips: dict[int, QToolButton] = {}
        for n in (1, 2, 3):
            b = QToolButton()
            b.setText(f"{n} · {EV.NOMBRES_PASO[n]}")
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setToolTip({1: "Elegir la grabación de tu voz (se coloca y se empieza a transcribir)",
                          2: "Revisar las dudas de tu voz: tomas repetidas, trabas, pausas… Nada se corta sin tu ✓",
                          3: "Armar el video con tu material donde lo nombras, sin huecos"}[n])
            b.clicked.connect(lambda _=False, k=n: ev.ir_a_paso(k))
            fila.addWidget(b)
            self.chips[n] = b
        lay.addLayout(fila)
        self.pila = QStackedWidget()
        self.pagina_voz = PaginaVoz(ev)
        self.paginas: dict[int, QWidget] = {1: self.pagina_voz}
        self.pila.addWidget(self.pagina_voz)
        for n in (2, 3):
            ph = QLabel({2: "Pule tu voz: aparecerá en cuanto llegue el primer minuto transcrito.",
                         3: "Arma tu video: aparecerá en cuanto tu voz esté colocada."}[n])
            ph.setWordWrap(True)
            ph.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            ph.setStyleSheet(f"color: {D.colores()['tenue']};")
            self.paginas[n] = ph
            self.pila.addWidget(ph)
        lay.addWidget(self.pila, 1)
        from .mas_herramientas import seccion          # 🧰 lo de la pestaña IA de antes (24/11): plegado, al final
        self.mas_herramientas = seccion(ev.win)
        lay.addWidget(self.mas_herramientas)
        self.estilo()

    def heightForWidth(self, w: int) -> int:            # noqa: N802
        """(fase 6) Dentro de una zona con desplazamiento, el panel no pide el alto de TODO su contenido (la lista de
        dudas ya se desplaza sola): pide su mínimo, así ocupa lo que se ve y el botón de abajo nunca queda fuera."""
        return self.minimumSizeHint().height()

    def estilo(self):
        c, f = D.colores(), D.fichas()
        self.setStyleSheet(
            f"#edita_voz_panel {{ background: {f['bloque']}; border: 1px solid {f['bloque_borde']}; "
            f"border-radius: {D.px(6)}px; }}"
            f"#edita_voz_panel QToolButton:checked {{ background: {c['acento']}; color: {c['sobre_acento']}; "
            f"border-radius: {D.px(4)}px; }}")

    def poner_paso(self, n: int, w: QWidget):
        viejo = self.paginas.get(n)
        self.paginas[n] = w
        i = self.pila.indexOf(viejo) if viejo is not None else -1
        if i >= 0:
            self.pila.insertWidget(i, w)
            self.pila.removeWidget(viejo)
            viejo.deleteLater()
        else:
            self.pila.addWidget(w)

    def mostrar_paso(self, n: int):
        # (fase 6: el alto lo pide SOLO la página a la vista; las otras no estiran el panel ni empujan su botón de
        #  abajo fuera de la vista)
        for k, w in self.paginas.items():
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred if k == n else QSizePolicy.Ignored)
        self.pila.setCurrentWidget(self.paginas[n])
        self.pila.updateGeometry()
        for k, b in self.chips.items():            # (la activa con su nombre entero; las demás, su número)
            b.setChecked(k == n)
            b.setText(f"{k} · {EV.NOMBRES_PASO[k]}" if k == n else str(k))
            b.setSizePolicy(QSizePolicy.Expanding if k == n else QSizePolicy.Fixed, QSizePolicy.Fixed)


# ====================================================================================== dónde se ve el panel
class Anfitrion(QObject):
    """(fase 5) «Edita desde tu voz» es una pestaña más del panel de herramientas a la derecha del visor
    (ui/herramientas.py): en el hueco del visor o, si no cabe, en la pestaña «Herramienta» junto al Inspector. Nunca
    flotante. Mientras prepara o transcribe cuenta como «trabajando» (no se cierra por el límite de 3 pestañas)."""

    CLAVE = "edita_voz"

    def __init__(self, ev: "EditaVoz"):
        super().__init__(ev)
        from . import herramientas
        self.ev, self.win = ev, ev.win
        self.host = herramientas.de(self.win)

    # (lo que usaban el panel y sus pruebas: ahora es del anfitrión común)
    def _hueco(self) -> QRect | None:
        return self.host._hueco()

    def cabe(self) -> bool:
        return self.host.cabe()

    @property
    def donde(self):
        return self.host.donde

    @property
    def marco(self):
        return self.host.marco

    @property
    def dock(self):
        return self.host.dock

    def mostrar(self):
        panel = self.ev.panel
        panel.cabecera.hide()                      # (la pestaña ya lleva su nombre, su chincheta y su ✕)
        self.host.abrir(self.CLAVE, panel, "Edita desde tu voz", "Tu voz", "mic", conservar=True,
                        al_cerrar=self._cerrado, trabajando=self._trabajando,
                        boton=getattr(self.win, "btn_edita_voz", None))

    def ocultar(self):
        self.host.cerrar(self.CLAVE, por_usuario=False)

    def _cerrado(self):                            # (✕, doble clic, Esc o el límite de pestañas)
        self.ev.abierto = False

    def _trabajando(self) -> bool:
        return self.ev.job_prep is not None or self.ev.job_trans is not None

    @property
    def visible(self) -> bool:
        return self.host.visible and self.host.activa == self.CLAVE and not self.host.clip_delante()

    def recolocar(self):
        self.host.recolocar()


# ====================================================================================== el cerebro
class EditaVoz(QObject):
    """Estado, trabajos en segundo plano (preparar, transcribir) y el enlace botón ↔ panel."""
    cambio = Signal()
    voz_colocada = Signal(list)      # ids de los clips de la voz (el paso 3 puede empezar)
    texto_parcial = Signal(str)      # media_id: llegó un trozo más de transcripción (los pasos 2 y 3, en cadena)
    transcripcion_lista = Signal()   # toda la voz transcrita (los pasos 2 y 3 terminan lo que quede)

    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.boton: BotonEditaVoz | None = getattr(win, "btn_edita_voz", None)
        self.panel = PanelEditaVoz(self)
        self.anfitrion = Anfitrion(self)
        self.abierto = False
        self.job_prep = None
        self.job_trans = None
        self.frac: float | None = None          # la fracción del trabajo en marcha (None = nada)
        self.texto = ""
        self._pend: dict = {}
        self._jugador = None
        self._proj_trans = None                 # (el proyecto en el que empezó la transcripción)
        if self.boton is not None:
            self.boton.pulsado.connect(self.pulsar)
            self.boton.cancelar.connect(self.cancelar)
        self.ctrl.project_replaced.connect(self._al_cambiar_proyecto)
        self.refrescar()

    # ------------------------------------------------------------------ abrir / cerrar
    @property
    def pagina(self) -> PaginaVoz:
        return self.panel.pagina_voz

    def estado(self) -> dict:
        return EV.estado(self.ctrl.project)

    def pulsar(self):
        if str(_ajustes().value(AJ_USADO, "false")).lower() != "true":
            _ajustes().setValue(AJ_USADO, "true")
        if self.boton is not None:
            self.boton.brillar(False)
        if self.abierto and self.anfitrion.visible:
            self.cerrar_panel()
            return
        self.abrir()

    def abrir(self, paso: int | None = None):
        self.abierto = True
        self.anfitrion.mostrar()
        n = paso or int(self.estado().get("paso", 1))
        if not self.estado().get("voz"):
            n = 1
        self.ir_a_paso(n)

    def cerrar_panel(self):
        self.abierto = False
        self.anfitrion.ocultar()

    def ir_a_paso(self, n: int):
        self.panel.mostrar_paso(n)
        if n == 1:
            carpeta, de = self.carpeta_inicial()
            self.pagina.rellenar_recientes(carpeta, de)
            foco = self.pagina.btn_elegir
            if self.pagina.barra.abierta and self.pagina.barra.botones:
                foco = next(iter(self.pagina.barra.botones.values()))
        else:
            w = self.panel.paginas.get(n)
            if callable(getattr(w, "refrescar", None)):     # (la página, al día con el proyecto de ahora)
                w.refrescar()
            foco = getattr(w, "foco", None) or w
        if foco is not None:
            QTimer.singleShot(0, lambda f=foco: f.isVisible() and f.setFocus(Qt.OtherFocusReason))

    def poner_paso(self, n: int, w: QWidget):
        """Enchufa la página de un paso (2: Pule tu voz; 3: Arma tu video). Si tiene .foco, es donde va el foco."""
        self.panel.poner_paso(n, w)

    # ------------------------------------------------------------------ botón
    def refrescar(self):
        trabajando = self.job_prep is not None or self.job_trans is not None
        ev = self.estado()
        otro = (self.job_trans is not None and self._proj_trans is not None
                and self._proj_trans is not self.ctrl.project and self.job_prep is None)
        if otro:                                   # (transcribe la voz de la otra pestaña: aquí, su paso)
            txt = EV.texto_boton(self.ctrl.project)
        elif trabajando and (self.job_prep is not None or not ev.get("voz")):
            txt = f"Paso 1 de {EV.PASOS} · {int(round((self.frac or 0.0) * 100))} %"
        else:
            txt = EV.texto_boton(self.ctrl.project, trabajando, self.frac if trabajando else None)
        if self.boton is not None:
            self.boton.poner(txt, trabajando, ("En la otra pestaña: " if otro else "") + self.texto)
        self.pagina.progreso(self.frac if trabajando else None, self.texto)
        self.cambio.emit()

    # ------------------------------------------------------------------ paso 1: elegir
    def carpeta_inicial(self) -> tuple[str, str]:
        from PySide6.QtCore import QStandardPaths
        videos = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)
        return EV.carpeta_inicial(str(_ajustes().value(AJ_CARPETA, "") or ""), videos)

    def elegir_con_dialogo(self):
        carpeta, _de = self.carpeta_inicial()
        filtro = "Grabaciones (" + " ".join("*" + e for e in sorted(EV.EXT_GRABACION)) + ");;Todos los archivos (*)"
        rutas, _ = QFileDialog.getOpenFileNames(self.win, "¿Dónde está la voz de tu video?", carpeta, filtro)
        if rutas:
            self.elegir(rutas)

    def elegir(self, rutas: list[str]):
        rutas = [r for r in rutas if r and os.path.isfile(r)]
        if not rutas or self.job_prep is not None:
            return
        if not self.abierto:
            self.abrir(1)
        if self.boton is not None and self.boton.brillando:
            _ajustes().setValue(AJ_USADO, "true")
            self.boton.brillar(False)
        _ajustes().setValue(AJ_CARPETA, os.path.dirname(rutas[0]))
        rutas = EV.ordenar_partes(rutas)
        editada = self.pagina.chk_editada.isChecked() or any(EV.ya_editada(self.ctrl.project, None, r)
                                                              for r in rutas)
        self._pend = {"rutas": rutas, "editada": editada, "proyecto": self.ctrl.project}
        self.texto = "Mirando la grabación…"
        self.frac = 0.0
        self.refrescar()
        tam = {r: EV.tamano(r) for r in rutas}
        QTimer.singleShot(self.ESPERA_CRECE, lambda: self._mirar_crecimiento(tam))

    ESPERA_CRECE = 1200          # (ms) cuánto se espera para ver si OBS sigue escribiendo el archivo

    def _mirar_crecimiento(self, tam: dict, esperando: bool = False):
        if not self._pend:
            return
        crece = [r for r, t in tam.items() if EV.tamano(r) != t]
        if not crece:
            self._preparar()
            return
        nombre = os.path.basename(crece[0])
        if esperando:                              # (sigue creciendo: se vuelve a mirar en un rato)
            self.texto = f"Esperando a que OBS termine de grabar «{nombre}»…"
            self.refrescar()
            nuevo = {r: EV.tamano(r) for r in tam}
            QTimer.singleShot(2000, lambda: self._mirar_crecimiento(nuevo, True))
            return
        self.texto = ""
        self.frac = None
        self.refrescar()

        def resp(k):
            if k == "esperar":
                self.texto = f"Esperando a que OBS termine de grabar «{nombre}»…"
                self.frac = 0.0
                self.refrescar()
                nuevo = {r: EV.tamano(r) for r in tam}
                QTimer.singleShot(2000, lambda: self._mirar_crecimiento(nuevo, True))
            elif k == "usar":
                self._pend["creciendo"] = True
                self._preparar()
            else:
                self._pend = {}
                self.refrescar()
        self.pagina.barra.preguntar(f"OBS sigue grabando «{nombre}» (el archivo todavía crece).",
                                    [("esperar", "Esperar a que termine"), ("usar", "Usar lo que hay"),
                                     ("no", "Cancelar")], resp,
                                    tip="«Usar lo que hay» transcribe hasta donde va ahora; lo que grabes después no "
                                        "entra (vuelve a elegirla cuando acabes).")

    def _lanzar(self, fn, listo, parcial=None, nombre="prep"):
        from .jobs import BackgroundJob
        job = BackgroundJob(fn, self.win, with_partial=parcial is not None)
        job.title = "🎙 Edita desde tu voz"
        if parcial is not None:
            job.partial.connect(parcial)
        job.progress.connect(lambda f, t, n=nombre: self._progreso(n, f, t))
        job.done.connect(listo)
        job.failed.connect(lambda msg, n=nombre: self._fallo(n, msg))
        job.finished.connect(lambda n=nombre, j=job: self._fin_job(n, j))
        setattr(self, "job_" + nombre, job)
        job.start()
        self.refrescar()
        return job

    def _progreso(self, nombre: str, f: float, t: str):
        if nombre == "trans" and self.job_prep is not None:
            return                                   # (preparando la siguiente parte: manda la preparación)
        self.frac = float(f)
        self.texto = t
        self.refrescar()

    def _fallo(self, nombre: str, msg: str):
        self.texto = "Cancelado: lo hecho se queda." if msg == "Cancelado." else f"No se pudo: {msg}"
        if nombre == "prep":
            self._pend = {}
        self.ctrl.message.emit("🎙 " + self.texto)

    def _fin_job(self, nombre: str, job):
        if getattr(self, "job_" + nombre, None) is job:
            setattr(self, "job_" + nombre, None)
        if self.job_prep is None and self.job_trans is None:
            self.frac = None
        self.refrescar()

    def cancelar(self):
        for j in (self.job_prep, self.job_trans):
            if j is not None:
                j.cancel()
        if self.pagina.barra.abierta:
            self.pagina.barra.responder("no")
        self._pend = {}

    # ------------------------------------------------------------------ preparar (hilo)
    def _preparar(self):
        rutas = list(self._pend.get("rutas") or [])

        def fn(progress, cancelled):
            out = []
            n = len(rutas)
            for i, r in enumerate(rutas):
                def prog(f, t, i=i):
                    progress((i + f) / n * 0.9, t)
                item = {"orig": r, "fuente": r, "avisos": []}
                if EV.en_nube(r) or EV.en_red(r):
                    item["avisos"].append("estaba en la nube o en red: la copié a tu PC")
                    prog(0.0, f"Copiando «{os.path.basename(r)}» a tu PC (estaba en la nube o en red)…")
                    item["fuente"] = EV.copiar_a_cache(r, lambda f, t: prog(f * 0.8, t), cancelled)
                fl = EV.flujos(item["fuente"])
                if EV.necesita_convertir(item["fuente"], fl):
                    prog(0.8, f"Convirtiendo «{os.path.basename(r)}» a un formato que Reclaimer abre…")
                    item["fuente"] = EV.convertir(item["fuente"], fl)
                    item["avisos"].append("formato raro: usé una copia convertida")
                    fl = EV.flujos(item["fuente"])
                if cancelled():
                    from ..ai.base import Cancelled
                    raise Cancelled()
                item["video"] = EV.tiene_video(fl)
                prog(0.9, f"Buscando tu voz en «{os.path.basename(r)}»…")
                item["pista"] = EV.elegir_pista(item["fuente"])
                if item["pista"]["n"] == 0:
                    raise RuntimeError(f"«{os.path.basename(r)}» no tiene sonido")
                out.append(item)
            progress(0.95, "Listo para colocar tu voz…")
            return out
        self.texto = "Preparando la grabación…"
        self._lanzar(fn, self._preparado)

    def _preparado(self, items: list):
        if not self._pend:
            return
        self._pend["items"] = items
        dudosa = next((it for it in items if it["pista"]["n"] >= 2 and not it["pista"]["seguro"]), None)
        if dudosa is not None:
            self._preguntar_pista(dudosa)
            return
        self._extraer()

    def _preguntar_pista(self, it: dict):
        """Varias pistas y no está claro cuál es la voz: un botón por pista (clic = escuchar un trozo) y «Usar»."""
        n = it["pista"]["n"]
        k0 = it["pista"]["k"]
        self._pista_elegida = k0
        ops = [("usar", f"Usar la pista {k0 + 1}", "Tu voz está en esta pista")]
        for k in range(n):
            rol = it["pista"]["roles"].get(k)
            ops.append((f"oir{k}", f"Escuchar {k + 1}", f"Escuchar 6 s de la pista {k + 1}"
                        + (" (parece el micrófono)" if rol == "voz" else " (parece el juego)" if rol == "juego" else "")))

        def resp(clave):
            if clave.startswith("oir"):
                k = int(clave[3:])
                self._pista_elegida = k
                self._escuchar(EV.trozo_pista(it["fuente"], k))
                self._preguntar_pista_de_nuevo(it, k)
                return
            if clave == "usar":
                it["pista"]["k"] = self._pista_elegida
                it["pista"]["seguro"] = True
                self._preparado(self._pend.get("items") or [])
                return
            self._pend = {}
            self.refrescar()
        self.pagina.barra.preguntar(f"«{os.path.basename(it['orig'])}» tiene {n} pistas de audio. ¿En cuál está tu "
                                    "voz?", ops + [("no", "Cancelar")], resp,
                                    tip="En OBS tu voz suele ir en la pista 2. Escucha un trozo de cada una y elige.")

    def _preguntar_pista_de_nuevo(self, it, k):
        it["pista"]["k"] = k
        self._preguntar_pista(it)

    def _escuchar(self, ruta: str):
        if os.environ.get("EDITORIA_SIN_SONIDO") or not ruta or not os.path.exists(ruta):
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            if self._jugador is None:
                self._jugador = QMediaPlayer(self)
                self._salida = QAudioOutput(self)
                self._jugador.setAudioOutput(self._salida)
            self._jugador.setSource(QUrl.fromLocalFile(ruta))
            self._jugador.play()
        except Exception:  # noqa: BLE001 - sin audio: se elige igual
            pass

    def _extraer(self):
        items = list(self._pend.get("items") or [])

        def fn(progress, cancelled):
            for i, it in enumerate(items):
                p = it["pista"]
                progress(i / max(1, len(items)), f"Separando tu voz de «{os.path.basename(it['orig'])}»…")
                if p["n"] >= 2:
                    it["voz"] = EV.extraer_pista(it["fuente"], p["k"])
                    otras = [k for k in range(p["n"]) if k != p["k"] and (not p["roles"] or k in p["roles"])]
                    it["otras"] = [(k, EV.extraer_pista(it["fuente"], k)) for k in otras]
                    it["mezclada"] = False
                else:
                    it["voz"] = it["fuente"]
                    it["otras"] = []
                    it["mezclada"] = EV.mezclada(it["fuente"], 0)
                if cancelled():
                    from ..ai.base import Cancelled
                    raise Cancelled()
            return items
        self.texto = "Separando tu voz…"
        self._lanzar(fn, self._extraido)

    def _extraido(self, items: list):
        if not self._pend:
            return
        self._pend["items"] = items
        self._pend["voces"] = [it["voz"] for it in items]
        self.transcribir(self._pend["voces"])          # ⚡ empieza YA, antes de colocar
        self._preguntar_imagen()

    def _preguntar_imagen(self):
        items = self._pend.get("items") or []
        if not any(it.get("video") for it in items):
            self._pend["modo"] = "voz"
            self._preguntar_sitio()
            return

        def resp(k):
            if k in ("voz", "imagen"):
                self._pend["modo"] = k
                self._preguntar_sitio()
            else:
                self._pend = {}
                self.refrescar()
        self.pagina.barra.preguntar("La grabación trae también la imagen del juego.",
                                    [("voz", "Solo la voz"), ("imagen", "También su imagen"), ("no", "Cancelar")],
                                    resp, tip="«También su imagen»: al armar el video, la imagen del juego hace de base "
                                              "(V1) donde no haya nada mejor. Tu voz va siempre en «🎙 Micrófono».")

    def _preguntar_sitio(self):
        if not self.ctrl.project.clips:
            self._colocar(0.0)
            return
        cab = float(getattr(self.win.timeline, "playhead", 0.0) or 0.0)

        def resp(k):
            if k == "inicio":
                self._colocar(0.0)
            elif k == "cabezal":
                self._colocar(cab)
            else:
                self._pend = {}
                self.refrescar()
        self.pagina.barra.preguntar("Ya hay cosas en la línea de tiempo. ¿Dónde pongo tu voz?",
                                    [("inicio", "Al inicio"), ("cabezal", f"En el cabezal ({_fmt(cab)})"),
                                     ("no", "Cancelar")], resp,
                                    tip="Nunca se borra nada: si el sitio está ocupado, tu voz va a una pista libre.")

    def _colocar(self, t: float):
        pend, self._pend = self._pend, {}
        if pend.get("proyecto") is not self.ctrl.project:
            self.ctrl.message.emit("🎙 Cambiaste de proyecto antes de colocar tu voz: elígela otra vez aquí.")
            self.refrescar()
            return
        items = pend.get("items") or []
        modo = pend.get("modo", "voz")
        voces = [it["voz"] for it in items]
        ids = self.ctrl.import_now(voces, quiet=True)
        por_ruta = {os.path.normcase(os.path.abspath(self.ctrl.project.media[i].path)): i for i in ids}
        partes, bases = [], []
        for it in items:
            voz_mid = por_ruta.get(os.path.normcase(os.path.abspath(it["voz"])))
            if modo == "imagen" and it.get("video"):
                # (la imagen del juego NO se pone entera: «Arma tu video» la usa de base —V1— donde no haya nada mejor)
                (img,) = self.ctrl.import_now([it["fuente"]], quiet=True) or (None,)
                if img is not None:
                    bases.append(img)
            if voz_mid is not None:
                partes.append({"media_id": voz_mid, "imagen": None})
        try:
            hechos = self.ctrl.poner_voz(partes, t)
        except Exception as exc:  # noqa: BLE001 - EditError: se cuenta en el panel
            self.texto = f"No pude colocar tu voz: {exc}"
            self.refrescar()
            return
        ev = self.estado()
        ev.update({"voz": voces, "origen": [it["orig"] for it in items], "modo": modo,
                   "saltar_pule": bool(pend.get("editada")), "voz_media": [p["media_id"] for p in partes],
                   "base_media": bases, "base_media_id": bases[0] if bases else None,
                   "paso": 3 if pend.get("editada") else 2})
        ev.setdefault("trans", {})
        self.ctrl._set_media_dirty()
        avisos = [a for it in items for a in it.get("avisos", [])]
        if pend.get("creciendo"):
            avisos.append("OBS seguía grabando: entró hasta donde iba")
        self.ctrl.message.emit("🎙 Tu voz está en la línea de tiempo y se está transcribiendo."
                               + (" (" + "; ".join(dict.fromkeys(avisos)) + ")" if avisos else ""))
        self._aplicar_cache()
        self.voz_colocada.emit(list(hechos or []))
        self.refrescar()
        if any(it.get("mezclada") for it in items):
            self._ofrecer_separar(hechos)
        else:
            self.ir_a_paso(int(ev["paso"]))

    def _ofrecer_separar(self, hechos):
        p = self.ctrl.project
        voz_mids = set(self.estado().get("voz_media") or [])
        clips = [i for i in hechos or [] if i in p.clips and p.clips[i].media_id in voz_mids]

        def resp(k):
            if k == "separar" and clips and hasattr(self.win, "separate_dialogue"):
                self.win.separate_dialogue(clips)
            self.ir_a_paso(int(self.estado().get("paso", 2)))
        self.pagina.barra.preguntar("Tu voz parece mezclada con el juego o la música.",
                                    [("separar", "Separar la voz"), ("dejar", "Dejarla así")], resp,
                                    tip="«Separar la voz» deja solo lo que se dice (el motor de IA, en segundo plano). "
                                        "Ctrl+Z vuelve al original.")

    # ------------------------------------------------------------------ transcripción temprana, por trozos
    def _modelo(self) -> str:
        v = getattr(self.win, "voice", None)
        try:
            k = v.model_combo.currentData()
        except Exception:  # noqa: BLE001
            k = None
        return k or "equilibrado"

    def transcribir(self, voces: list[str]):
        """Transcribe la voz (cada parte, en orden) por trozos de 1 min; sigue desde lo ya hecho (caché por archivo
        o lo guardado en el proyecto). Nunca bloquea: el progreso va en el botón."""
        if self.job_trans is not None:
            self.job_trans.cancel()
        voces = list(voces)
        prevs = {}
        for r in voces:
            prev = EV.cache_transcripcion(r)
            mid = self._media_de(r)
            enp = self.ctrl.project.transcripts.get(mid) if mid else None
            if enp and (prev is None or len(enp.get("words") or []) > len(prev.get("words") or [])):
                prev = enp
            prevs[r] = prev
        if all(prevs.get(r) is not None and prevs[r].get("hasta") is None for r in voces):
            return                                   # (todo transcrito ya: al momento)
        model = self._modelo()
        import copy
        prevs = copy.deepcopy(prevs)

        def fn(progress, cancelled, emit):
            from ..ai import transcription, voice_cleanup
            from ..core import media as media_tools
            n = len(voces)
            for i, r in enumerate(voces):
                prev = prevs.get(r)
                if prev is not None and prev.get("hasta") is None:
                    continue
                progress(i / n, "Leyendo tu voz…")
                samples = media_tools.decode_mono(r, transcription.SAMPLE_RATE)
                dur = len(samples) / transcription.SAMPLE_RATE
                start = float(prev["hasta"]) if prev and prev.get("hasta") is not None else 0.0

                def prog(f, t, i=i):
                    progress((i + f) / n, t)

                def parcial(tr, r=r, dur=dur):
                    tr = dict(tr, _dur=round(dur, 3))
                    emit((r, tr))
                tr = transcription.transcribe(samples, model, "es", prog, cancelled, fillers=True, partial=parcial,
                                              block=BLOQUE, start_at=start, prev=prev if start else None)
                try:
                    tr = voice_cleanup.refine_transcript(samples, transcription.SAMPLE_RATE, tr)
                except Exception:  # noqa: BLE001 - los tiempos finos son un extra
                    pass
                tr = dict(tr, _dur=round(dur, 3))
                tr.pop("hasta", None)
                emit((r, tr))
            return voces
        self._proj_trans = self.ctrl.project
        self.texto = "Transcribiendo tu voz…"
        self._lanzar(fn, lambda _r: self._transcrito(), parcial=self._trozo, nombre="trans")

    def _trozo(self, res):
        """Un trozo más (o el final) de la transcripción de un archivo: se guarda por archivo y, si el proyecto de
        ahora tiene esa voz, entra en él (aunque hayas cambiado de pestaña y vuelto)."""
        ruta, tr = res
        EV.guardar_transcripcion(ruta, tr)
        self._aplicar_uno(ruta, tr)
        self.refrescar()

    def _transcrito(self):
        self.texto = "Tu voz está transcrita."
        self.refrescar()
        self.transcripcion_lista.emit()

    def _media_de(self, ruta: str) -> str | None:
        k = os.path.normcase(os.path.abspath(ruta))
        for m in self.ctrl.project.media.values():
            if os.path.normcase(os.path.abspath(m.path)) == k:
                return m.id
        return None

    def _aplicar_uno(self, ruta: str, tr: dict):
        ev = self.estado()
        mid = self._media_de(ruta)
        dur = float(tr.get("_dur") or 0.0)
        hecho = 1.0 if tr.get("hasta") is None else (min(1.0, float(tr["hasta"]) / dur) if dur > 0 else 0.0)
        if ruta in (ev.get("voz") or []):
            ev.setdefault("trans", {})[ruta] = round(hecho, 4)
        if mid is None:
            return
        actual = self.ctrl.project.transcripts.get(mid)
        if actual is not None and actual.get("hasta") is None and tr.get("hasta") is not None:
            return                                   # (ya está entera: un trozo viejo no la pisa)
        datos = {k: v for k, v in tr.items() if k != "_dur"}
        if actual is not None and len(actual.get("words") or []) == len(datos.get("words") or []) and \
                actual.get("hasta") == datos.get("hasta"):
            return
        self.ctrl.set_transcript(mid, datos)
        self.texto_parcial.emit(mid)

    def _aplicar_cache(self):
        for r in self.estado().get("voz") or []:
            tr = EV.cache_transcripcion(r)
            if tr is not None:
                self._aplicar_uno(r, tr)

    def _al_cambiar_proyecto(self):
        """Otro proyecto (abrir, nuevo o cambiar de pestaña): el botón dice SU paso; lo transcrito mientras tanto
        entra; y si se quedó a medias (cerraste Reclaimer), sigue solo en un momento."""
        self._pend = {}
        if self.pagina.barra.abierta:
            self.pagina.barra.hide()
        self._aplicar_cache()
        ev = self.estado()
        self.refrescar()
        if self.abierto:
            self.ir_a_paso(int(ev.get("paso", 1)) if ev.get("voz") else 1)
        voces = [r for r in ev.get("voz") or [] if os.path.isfile(r)]
        falta = [r for r in voces if (EV.cache_transcripcion(r) or {}).get("hasta") is not None
                 or EV.cache_transcripcion(r) is None]
        if falta and self.job_trans is None:
            QTimer.singleShot(self.ESPERA_SEGUIR, lambda p=self.ctrl.project, v=voces: (
                p is self.ctrl.project and self.job_trans is None and self.transcribir(v)))

    ESPERA_SEGUIR = 4000         # (ms) al reabrir un proyecto a medias, cuánto espera antes de seguir transcribiendo


def instalar(win) -> EditaVoz | None:
    """Crea el cerebro de «Edita desde tu voz» y lo engancha al botón de arriba (win.btn_edita_voz)."""
    try:
        ev = EditaVoz(win)
    except Exception:  # noqa: BLE001 - la ventana sigue funcionando sin la herramienta
        import traceback
        traceback.print_exc()
        return None
    from . import paso_arma, pule_voz
    pule_voz.instalar(ev)                       # paso 2 «Pule tu voz»
    paso_arma.instalar(ev)                      # paso 3 «Arma tu video» (el Armador de ui/armar_video.py)
    return ev
