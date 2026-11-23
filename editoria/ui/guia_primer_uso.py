"""
👋 Guía de primer uso: un recorrido corto (6 pasos) la primera vez que se abre Reclaimer.

Cada paso pone a la vista un sitio real (abre su panel y su sección si están cerrados: «cada acción abre su panel»; si
no se puede, ese paso se salta), lo rodea con un recuadro del color de acento y enseña una frase corta en una burbuja:
importar → transcribir → limpiar → recortar a mano (Q / W y puntos de unión) → palabras clave y material → exportar.

  · Sale sola UNA vez (la primera vez que abres Reclaimer); «Saltar» (o Esc) la termina cuando quieras.
  · Ayuda → «Guía de primer uso» la vuelve a enseñar cuando quieras.
  · Al terminar (o saltarla), la página en la que empezó, la distribución de paneles y las secciones abiertas vuelven
    a como estaban. No se abre sola con un diálogo a la vista, un proyecto abriéndose o una exportación.
  · NUNCA sale sola en las pruebas ni sin ventana (offscreen): debe_mostrarse() lo comprueba.

Los textos, cortos y sin nombres de juegos ni de personas; los iconos, monocromos (diseno.icono).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import diseno as D

CLAVE_NO_MOSTRAR = "guia_primer_uso/no_mostrar"


def _transcribir(win):
    win.abrir_seccion("voz_texto", "transcribir")
    b = getattr(getattr(win, "voice", None), "btn_transcribe", None)
    return b if b is not None and b.isVisible() else win.voz_texto.widget_de("transcribir")


def _limpiar(win):
    win.abrir_seccion("audio", "limpieza")
    return win.audio_panel.widget_de("limpieza")


def _union(win):
    w = getattr(win, "chk_puntos_union", None)
    if w is not None:
        win.mostrar_widget(w)
    return w


def _palabras(win):
    win.abrir_seccion("palabras", "palabras")       # (22/11: su propio panel, a la derecha)
    return getattr(win, "_pal_tabs", None)


def _importar(win):
    b = getattr(getattr(win, "library", None), "btn_files", None)
    if b is not None:
        win.mostrar_widget(b)
    return b


def _exportar(win):
    return getattr(win, "page_buttons", {}).get("deliver")


# (clave, título, frase, cómo ponerlo a la vista → el control a rodear o None)
PASOS = [
    ("importar", "Importar", "Arrastra aquí tu narración y tus clips, o pulsa «Archivos».", _importar),
    ("transcribir", "Transcribir", "Transcribe la narración: de ahí salen los subtítulos, las palabras clave y la "
                                   "limpieza.", _transcribir),
    ("limpiar", "Limpiar", "Silencios, muletillas y tomas repetidas: márcalos y quítalos de una vez.", _limpiar),
    ("recortar", "Recortar a mano", "Q y W recortan el inicio o el final del clip hasta el cabezal. Los puntos de "
                                    "unión ajustan cada pegado.", _union),
    ("palabras", "Palabras clave y material", "Lo que dices, con su carpeta de material: un clic lo pone donde lo "
                                              "dices.", _palabras),
    ("exportar", "Exportar", "Cuando esté listo, «Entrega» (Ctrl+E) lo exporta con los ajustes de YouTube.",
     _exportar),
]


def en_pruebas() -> bool:
    """¿Pruebas o sin ventana? (ahí la guía nunca sale sola)."""
    from PySide6.QtGui import QGuiApplication
    return (QGuiApplication.platformName() == "offscreen" or os.environ.get("QT_QPA_PLATFORM", "").startswith(
        "offscreen") or bool(os.environ.get("RECLAIMER_AJUSTES_PRUEBA")) or bool(os.environ.get("EDITORIA_SIN_SONIDO")))


def debe_mostrarse(settings) -> bool:
    """Al abrir Reclaimer: ¿sale sola? Solo si no pediste «No volver a mostrar» y no son pruebas."""
    return not en_pruebas() and str(settings.value(CLAVE_NO_MOSTRAR, "false")).lower() not in ("true", "1")


class _Anillo(QWidget):
    """El recuadro del color de acento alrededor del sitio del paso. Los clics pasan a través (no estorba)."""

    def __init__(self, win: QWidget):
        super().__init__(win)
        self.setObjectName("guia_primer_uso_anillo")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.objetivo: QWidget | None = None

    def rect_objetivo(self) -> QRect | None:
        t, win = self.objetivo, self.parentWidget()
        if t is None or win is None:
            return None
        try:
            if not t.isVisible():
                return None
            vis = t.visibleRegion().boundingRect()
            if vis.isEmpty():
                vis = t.rect()
            return QRect(t.mapTo(win, vis.topLeft()), vis.size())
        except RuntimeError:
            return None

    def paintEvent(self, _e):
        r = self.rect_objetivo()
        if r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from .theme import acento
        rr = QRectF(r).adjusted(-4, -4, 4, 4).intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        brillo = acento()
        brillo.setAlphaF(0.25)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(brillo, 6))
        p.drawRoundedRect(rr.adjusted(-2, -2, 2, 2), 8, 8)
        linea = acento()
        linea.setAlphaF(0.95)
        p.setPen(QPen(linea, 2))
        p.drawRoundedRect(rr, 7, 7)


class _Burbuja(QFrame):
    """La burbuja del paso: título, frase, «n / total», Atrás · Siguiente, «Saltar» y «No volver a mostrar»."""

    def __init__(self, win: QWidget, guia: "GuiaPrimerUso"):
        super().__init__(win)
        self.setObjectName("guia_primer_uso_burbuja")
        from . import theme as T
        self.setStyleSheet(f"QFrame#guia_primer_uso_burbuja {{ background: {D.fichas()['menu']}; "
                           f"border: 1px solid {T.acento_rgba(0.8)}; border-radius: 6px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(D.px(D.M3), D.px(D.M2), D.px(D.M3), D.px(D.M2))
        v.setSpacing(D.px(D.M1))
        cab = QHBoxLayout()
        self.titulo = QLabel()
        D.poner_letra(self.titulo, D.LETRA_G, T.TEXT, QFont.DemiBold)
        self.cuenta = QLabel()
        D.poner_letra(self.cuenta, D.LETRA_P, T.TEXT_DIM)
        cab.addWidget(self.titulo, 1)
        cab.addWidget(self.cuenta)
        v.addLayout(cab)
        self.frase = QLabel()
        self.frase.setWordWrap(True)
        D.poner_letra(self.frase, D.LETRA_M, T.TEXT)
        v.addWidget(self.frase)
        botones = QHBoxLayout()
        botones.setSpacing(D.px(D.M1))
        self.saltar = QPushButton("Saltar")
        self.saltar.setObjectName("flat")
        self.saltar.setToolTip("Terminar la guía ahora (Esc). Todo vuelve a como estaba; se vuelve a ver en "
                               "Ayuda → «Guía de primer uso»")
        self.atras = D.BotonIcono("chevron-left", "Paso anterior")
        self.siguiente = QPushButton("Siguiente")
        self.siguiente.setObjectName("primary")
        self.siguiente.setIcon(D.icono("chevron-right"))
        self.siguiente.setLayoutDirection(Qt.RightToLeft)          # (la flecha a la derecha del texto)
        for b in (self.saltar, self.atras, self.siguiente):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        botones.addWidget(self.saltar)
        botones.addStretch(1)
        botones.addWidget(self.atras)
        botones.addWidget(self.siguiente)
        v.addLayout(botones)
        self.saltar.clicked.connect(guia.saltar)
        self.atras.clicked.connect(lambda: guia.ir(guia.i - 1, -1))
        self.siguiente.clicked.connect(lambda: guia.ir(guia.i + 1, 1))
        D.medida(self, lambda w: w.setFixedWidth(D.px(320)))


class GuiaPrimerUso(QObject):
    """El recorrido. empezar(win) la crea y la enseña; terminar() deja todo como estaba."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.i = -1
        self.vistos: list[str] = []          # (claves de los pasos que se enseñaron: para la prueba)
        self._pagina = pagina_actual(win)
        self._estado = win.saveState(3)
        self._secciones = {k: getattr(win, a).abierta() for k, a in (("voz_texto", "voz_texto"),
                                                                      ("audio", "audio_panel"))
                           if getattr(win, a, None) is not None}
        self.anillo = _Anillo(win)
        self.burbuja = _Burbuja(win, self)
        self._seguir = QTimer(self)
        self._seguir.setInterval(200)
        self._seguir.timeout.connect(self._colocar)
        win.installEventFilter(self)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)    # (Esc SIEMPRE la cierra: también tras pasar por otra
        self.activa = True                                  #  página o con el foco en cualquier control)

    # ---- recorrido
    def ir(self, i: int, sentido: int = 1) -> bool:
        """Al paso i (si su sitio no se puede enseñar, al siguiente en ese sentido). Más allá del último = terminar."""
        while 0 <= i < len(PASOS):
            clave, titulo, frase, poner = PASOS[i]
            try:
                obj = poner(self.win)
            except Exception:  # noqa: BLE001 - (ese sitio no existe en esta disposición: se salta)
                obj = None
            self._activar_layouts()
            if obj is not None and obj.isVisible():
                self.i = i
                self.vistos.append(clave)
                self.anillo.objetivo = obj
                b = self.burbuja
                b.titulo.setText(titulo)
                b.frase.setText(frase)
                b.cuenta.setText(f"{i + 1} / {len(PASOS)}")
                b.atras.setEnabled(i > 0)
                ultimo = i == len(PASOS) - 1
                b.siguiente.setText("Terminar" if ultimo else "Siguiente")
                b.siguiente.setToolTip("Terminar la guía: todo vuelve a como estaba" if ultimo else "Paso siguiente")
                self.anillo.show()
                self.burbuja.show()
                self._colocar()
                QTimer.singleShot(0, self._colocar)          # (cuando el panel recién abierto ya tiene su sitio)
                self._seguir.start()
                return True
            i += sentido
        if i >= len(PASOS):
            self.terminar(completa=True)
        return False

    def _activar_layouts(self):
        from PySide6.QtWidgets import QApplication
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    def _colocar(self):
        """El anillo cubre la ventana; la burbuja, debajo del sitio (o encima, o al lado), siempre dentro."""
        win = self.win
        try:
            self.anillo.setGeometry(win.rect())
            self.anillo.raise_()
            r = self.anillo.rect_objetivo()
            b = self.burbuja
            w = b.width()
            lay = b.layout()
            lay.activate()
            # (el alto que pide el texto PARTIDO al ancho fijo de la burbuja: con sizeHint se cortaba la última línea)
            h = max(lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else 0, lay.totalMinimumSize().height(),
                    b.minimumSizeHint().height())
            m = D.px(D.M2)
            if r is None:
                x, y = (win.width() - w) // 2, (win.height() - h) // 2
            else:
                x = min(max(m, r.center().x() - w // 2), win.width() - w - m)
                if r.bottom() + m + h < win.height() - m:
                    y = r.bottom() + m + 4
                elif r.top() - m - h > m:
                    y = r.top() - m - h - 4
                else:                                            # (un sitio alto: al lado)
                    y = min(max(m, r.center().y() - h // 2), win.height() - h - m)
                    x = r.right() + m if r.right() + m + w < win.width() else max(m, r.left() - m - w)
            b.setGeometry(x, y, w, h)
            b.raise_()
            self.anillo.update()
        except RuntimeError:
            self._seguir.stop()

    def eventFilter(self, obj, ev):
        if not self.activa:
            return False
        t = ev.type()
        if t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            from PySide6.QtWidgets import QApplication
            if QApplication.activeModalWidget() is None:        # (en un diálogo, Esc es del diálogo)
                self.saltar()
                return True
        elif obj is self.win and t == QEvent.Resize:
            QTimer.singleShot(0, self._colocar)
        return False

    def saltar(self):
        self.terminar(completa=False)

    def terminar(self, completa: bool = False):
        """Fin (entera, «Saltar» o Esc): ya no sale sola al abrir (Ayuda la enseña). Vuelve a la página en la que
        empezó y, entonces, los paneles y las secciones como estaban."""
        if not self.activa:
            return
        self.activa = False
        self._seguir.stop()
        win = self.win
        try:
            win.settings.setValue(CLAVE_NO_MOSTRAR, True)
            from PySide6.QtWidgets import QApplication
            QApplication.instance().removeEventFilter(self)
            win.removeEventFilter(self)
            for w in (self.anillo, self.burbuja):
                w.hide()
                w.deleteLater()
            if pagina_actual(win) != self._pagina:              # (pasó a Escenas, Miniatura…: primero, de vuelta)
                if hasattr(win, "salir_de_paginas") and not win.salir_de_paginas():
                    raise RuntimeError("se quedó en la otra página")   # (canceló: los paneles de allí, sin tocar)
                if self._pagina != pagina_actual(win) and self._pagina in getattr(win, "page_buttons", {}):
                    win.go_page(self._pagina)
            win.restoreState(self._estado, 3)                   # (paneles: como estaban)
            for k, clave in self._secciones.items():            # (y la sección abierta de cada panel agrupado)
                acordeon = win.voz_texto if k == "voz_texto" else win.audio_panel
                if clave and acordeon.abierta() != clave:
                    acordeon.abrir(clave)
        except RuntimeError:
            pass
        if getattr(win, "guia_primer_uso", None) is self:
            win.guia_primer_uso = None
        self.deleteLater()


def pagina_actual(win) -> str:
    """La página de abajo en la que se está (Escenas y Miniatura cambian los paneles de la ventana)."""
    if getattr(win, "_scenes_state", None) is not None:
        return "scenes"
    if getattr(win, "_thumb_page", None) is not None:
        return "thumb"
    return next((k for k, b in getattr(win, "page_buttons", {}).items() if b.isChecked()), "edit")


def ocupado(win) -> str:
    """'' si se puede enseñar la guía sola ahora; si no, por qué no (un diálogo, un proyecto abriéndose, una
    exportación)."""
    from PySide6.QtWidgets import QApplication
    if QApplication.activeModalWidget() is not None:
        return "un diálogo a la vista"
    ws = getattr(win, "workspaces", None)
    try:
        if ws is not None and ws._busy():
            return "una tarea en marcha"
    except Exception:  # noqa: BLE001
        pass
    dlg = getattr(win, "_export_dlg", None)
    try:
        if dlg is not None and dlg.exportando():
            return "una exportación"
    except RuntimeError:
        pass
    cola = getattr(win, "_render_queue", None)
    try:
        if cola is not None and getattr(cola, "ocupada", lambda: False)():
            return "la cola de exportación"
    except RuntimeError:
        pass
    if pagina_actual(win) != "edit":
        return "otra página"
    return ""


def al_arrancar(win, intentos: int = 10):
    """La primera vez que se abre Reclaimer (debe_mostrarse): si está ocupado (un diálogo, un proyecto abriéndose,
    una exportación), lo intenta otra vez en unos segundos; si sigue ocupado, la deja para el próximo arranque. Al
    enseñarla se apunta: solo sale sola UNA vez."""
    if getattr(win, "guia_primer_uso", None) is not None or not debe_mostrarse(win.settings):
        return
    if ocupado(win):
        if intentos > 0:
            QTimer.singleShot(3000, lambda: al_arrancar(win, intentos - 1))
        return
    if empezar(win) is not None:
        win.settings.setValue(CLAVE_NO_MOSTRAR, True)


def empezar(win) -> GuiaPrimerUso | None:
    """Enseña la guía desde el primer paso (si ya hay una a la vista, la deja como está). Desde Escenas o Miniatura,
    primero vuelve a Editar."""
    ya = getattr(win, "guia_primer_uso", None)
    if ya is not None and ya.activa:
        return ya
    if getattr(win, "_scenes_state", None) is not None or getattr(win, "_thumb_page", None) is not None:
        if hasattr(win, "salir_de_paginas") and not win.salir_de_paginas():
            return None
    g = GuiaPrimerUso(win)
    win.guia_primer_uso = g
    if not g.ir(0, 1):
        g.terminar(completa=False)
        return None
    return g
