"""
◧ Arrastrar el borde = todo el alto (23/11, fase 6 del plan «Edita desde tu voz», sección 4).

  · Paneles de un lado ENCIMA de la línea de tiempo: arrastra el borde de abajo de ese lado (el separador con la línea
    de tiempo) hacia abajo, hasta pasar la mitad de la línea de tiempo → al soltar, ese lado pasa a ocupar todo el alto
    y la línea de tiempo se corre a su lado (lo mismo que «◧ A todo el alto»; a la derecha, ventana/derecha_alto).
  · Ese lado YA a todo el alto: abajo del todo sale una tira fina (cursor ↕); arrástrala hacia arriba hasta pasar el
    borde de arriba de la línea de tiempo → vuelve como estaba.
  · Umbral claro (la mitad de la línea de tiempo / su borde de arriba) para que no salte por accidente, y mientras
    arrastras, una línea del acento donde quedaría el borde nuevo. Si no se pasa el umbral, el separador hace lo de
    siempre (cambiar el alto) y nada más.
instalar(win) lo engancha (una línea en main_window).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from . import diseno as D

MARGEN_SEP = 7          # px: distancia al separador para contar como «agarrar el borde»


class Linea(QWidget):
    """La línea del acento donde quedaría el borde (encima de todo, sin quitarle el ratón a nadie)."""

    def __init__(self, win):
        super().__init__(win)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()

    def poner(self, r: QRect | None):
        if r is None:
            self.hide()
            return
        self.setGeometry(r)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _e):            # noqa: N802
        p = QPainter(self)
        c = QColor(D.colores()["acento"])
        p.fillRect(self.rect(), c)
        p.end()


class Tira(QWidget):
    """La tira de abajo de un lado que ya está a todo el alto: arrastrarla hacia arriba lo devuelve."""

    def __init__(self, vigia: "Vigia", lado: str):
        super().__init__(vigia.win)
        self.vigia, self.lado = vigia, lado
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Arrastra hacia arriba (hasta la línea de tiempo) para que este lado deje de ocupar todo el "
                        "alto")
        self._y0 = None
        self.hide()

    def paintEvent(self, _e):            # noqa: N802
        p = QPainter(self)
        c = QColor(D.colores()["acento"] if self._y0 is not None or self.underMouse() else D.fichas()["bloque_borde"])
        p.fillRect(QRect(0, self.height() // 2 - 1, self.width(), 2), c)
        p.end()

    def enterEvent(self, e):             # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):             # noqa: N802
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):        # noqa: N802
        if e.button() == Qt.LeftButton:
            self._y0 = self.mapTo(self.vigia.win, e.position().toPoint()).y()
            self.update()

    def mouseMoveEvent(self, e):         # noqa: N802
        if self._y0 is not None:
            y = self.mapTo(self.vigia.win, e.position().toPoint()).y()
            self.vigia.mover_tira(self.lado, y)

    def mouseReleaseEvent(self, e):      # noqa: N802
        if self._y0 is not None:
            y = self.mapTo(self.vigia.win, e.position().toPoint()).y()
            self._y0 = None
            self.vigia.soltar_tira(self.lado, y)
            self.update()


class Vigia(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.linea = Linea(win)
        self.tiras = {"izq": Tira(self, "izq"), "der": Tira(self, "der")}
        self._arr = None                 # arrastre de un separador: {"lado", "y0", "umbral", "h_tl"}
        win.installEventFilter(self)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(60)
        self._t.timeout.connect(self.colocar_tiras)
        self._ciclo = QTimer(self)       # (los paneles se mueven sin avisar: un repaso ligero)
        self._ciclo.setInterval(1000)
        self._ciclo.timeout.connect(self.colocar_tiras)
        self._ciclo.start()
        QTimer.singleShot(0, self.colocar_tiras)

    # ------------------------------------------------------------------ geometría
    def _tl(self):
        d = self.win.docks.get("timeline")
        if d is None or d.isFloating() or not d.isVisible():
            return None
        return d

    def _lado(self, lado: str) -> QRect | None:
        """El rectángulo de los paneles visibles de ese lado (en coordenadas de la ventana)."""
        area = Qt.LeftDockWidgetArea if lado == "izq" else Qt.RightDockWidgetArea
        r = QRect()
        cw = self.win.centralWidget()
        arriba = cw.geometry().top() - D.px(40) if cw is not None else 0     # (debajo de las barras de arriba)
        for k, d in self.win.docks.items():
            g = d.geometry()
            if (k != "timeline" and d.isVisible() and not d.isFloating() and self.win.dockWidgetArea(d) == area
                    and g.height() > 20 and g.top() >= arriba):
                r = r.united(g)
        return None if r.isNull() else r

    def _alto(self, lado: str) -> bool:
        """¿Ese lado está DE VERDAD a todo el alto (su esquina de abajo es suya)?"""
        esquina = Qt.BottomLeftCorner if lado == "izq" else Qt.BottomRightCorner
        area = Qt.LeftDockWidgetArea if lado == "izq" else Qt.RightDockWidgetArea
        return self.win.corner(esquina) == area

    def _poner(self, lado: str, on: bool):
        if lado == "izq":
            self.win.set_biblioteca_alto(on)
        else:
            self.win.set_derecha_alto(on)

    # ------------------------------------------------------------------ separador → todo el alto
    def eventFilter(self, obj, ev) -> bool:
        if obj is not self.win:
            return False
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._empezar(ev.position().toPoint())
        elif t == QEvent.MouseMove and self._arr is not None:
            self._mover(ev.position().toPoint())
        elif t == QEvent.MouseButtonRelease and self._arr is not None:
            self._soltar(ev.position().toPoint())
        elif t in (QEvent.Resize, QEvent.LayoutRequest):
            self._t.start()
        return False

    def _empezar(self, p: QPoint):
        tl = self._tl()
        if tl is None:
            return
        g = tl.geometry()
        for lado in ("izq", "der"):
            r = self._lado(lado)
            if r is None or self._alto(lado):
                continue
            sep_y = (r.bottom() + g.top()) / 2
            if r.left() - 2 <= p.x() <= r.right() + 2 and abs(p.y() - sep_y) <= MARGEN_SEP and r.bottom() < g.top() + 2:
                self._arr = {"lado": lado, "y0": p.y(), "umbral": g.top() + g.height() / 2, "h_tl": g.height(),
                             "r": QRect(r)}
                return

    def _pasa(self, y: float) -> bool:
        return self._arr is not None and y >= self._arr["umbral"]

    def _mover(self, p: QPoint):
        a = self._arr
        if self._pasa(p.y()):
            tl = self._tl()
            g = tl.geometry() if tl is not None else QRect()
            r = a["r"]
            x = r.right() + 1 if a["lado"] == "izq" else r.left() - 3
            self.linea.poner(QRect(x, r.top(), 3, max(1, g.bottom() - r.top())))   # (el lado, hasta abajo)
        else:
            self.linea.poner(None)

    def _soltar(self, p: QPoint):
        a, self._arr = self._arr, None
        self.linea.poner(None)
        if a is None or not self._pasa_con(a, p.y()):
            return
        self._poner(a["lado"], True)
        if not self._alto(a["lado"]):          # (no cabe: la barra de la línea de tiempo no tendría sitio)
            self._poner(a["lado"], False)
            self.win.statusBar().showMessage("◧ No cabe a todo el alto: la línea de tiempo no tendría sitio para "
                                             "todos sus botones entre los dos lados.", 7000)
            return
        tl = self._tl()
        if tl is not None:                    # (la línea de tiempo, con el alto que tenía antes de arrastrar)
            QTimer.singleShot(0, lambda h=a["h_tl"]: self.win.resizeDocks([tl], [h], Qt.Vertical))
        QTimer.singleShot(50, self.colocar_tiras)

    @staticmethod
    def _pasa_con(a, y) -> bool:
        return y >= a["umbral"]

    # ------------------------------------------------------------------ tira → vuelve
    def colocar_tiras(self):
        tl = self._tl()
        for lado, tira in self.tiras.items():
            r = self._lado(lado)
            if tl is None or r is None or not self._alto(lado) or tira._y0 is not None:
                if tira._y0 is None:
                    tira.hide()
                continue
            alto = D.px(6)
            tira.setGeometry(r.left(), r.bottom() - alto + 1, r.width(), alto)
            tira.show()
            tira.raise_()

    def _umbral_tira(self) -> float:
        tl = self._tl()
        return tl.geometry().top() if tl is not None else 0.0

    def mover_tira(self, lado: str, y: int):
        r = self._lado(lado)
        if r is not None and y <= self._umbral_tira():
            tl = self._tl()
            g = tl.geometry()
            self.linea.poner(QRect(r.left(), g.top() - 2, r.width(), 3))    # (donde acabaría el lado)
        else:
            self.linea.poner(None)

    def soltar_tira(self, lado: str, y: int):
        self.linea.poner(None)
        if self._tl() is not None and y <= self._umbral_tira():
            self._poner(lado, False)
            self.tiras[lado].hide()
            QTimer.singleShot(50, self.colocar_tiras)


def instalar(win) -> Vigia | None:
    try:
        return Vigia(win)
    except Exception:  # noqa: BLE001 - la ventana sigue funcionando sin el arrastre
        import traceback
        traceback.print_exc()
        return None
