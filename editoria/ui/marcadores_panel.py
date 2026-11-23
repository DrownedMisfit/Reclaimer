"""
📍 Marcadores automáticos en la interfaz (fase 5). La lógica está en core/marcadores_auto.py; aquí:

  · CapaViva(ctrl, timeline): la capa de marcas al día SIN coste al pintar: se recalcula 300 ms después del último
    cambio (proyecto, transcripción, cortes dudosos, material repetido) y avisa (cambio). Recuerda qué tipos se ven
    (ajuste marcas/tipos): el filtro del índice es también el de la línea de tiempo y el de Mayús+↑/↓.
  · PanelMarcadores(ctrl, capa, ir_a): el índice. Arriba, un interruptor por tipo con su cuenta (filtra); la lista en
    el orden del video (clic = el cabezal allí); debajo, «Está bien así» para la elegida, la nota del marcador
    elegido (Enter = guardar; M dos veces en el mismo sitio de la línea de tiempo la abre) y «Quitar todas las tomas
    viejas». Cada acción, un Ctrl+Z. Va en la sección «Marcadores» del Inspector (gancho poner_marcadores; instalar).
    Cabe en un lateral estrecho: los interruptores se colocan solos en las filas que hagan falta.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..core import marcadores_auto as MA

DEBOUNCE_MS = 300
CORTO = {"toma": "Tomas", "muletilla": "Muletillas", "duda": "Cortes", "obs": "OBS", "tema": "Temas",
         "hueco": "Huecos", "repetido": "Repetido", "marcador": "Míos"}
ROL_MARCA = int(Qt.UserRole) + 7


def _punto(color: str, tam: int = 10) -> QIcon:
    pm = QPixmap(tam * 2, tam * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.Antialiasing)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(color))
    q.drawEllipse(1, 1, tam - 2, tam - 2)
    q.end()
    return QIcon(pm)


class _Fluido(QWidget):
    """Botones que se colocan de izquierda a derecha y bajan de fila cuando no caben (el ancho mínimo es el del botón
    más ancho: cabe en cualquier lateral). Sin layout.itemAt: los botones son suyos y los coloca él."""

    def __init__(self, parent=None, hueco: int = 4):
        super().__init__(parent)
        self._botones: list[QWidget] = []
        self._hueco = hueco
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def poner(self, b: QWidget):
        b.setParent(self)
        self._botones.append(b)
        self.updateGeometry()

    def _colocar(self, ancho: int, mover: bool) -> int:
        x = y = alto_fila = 0
        for b in self._botones:
            if b.isHidden():
                continue
            t = b.sizeHint()
            if x > 0 and x + t.width() > ancho:
                x, y = 0, y + alto_fila + self._hueco
                alto_fila = 0
            if mover:
                b.setGeometry(x, y, min(t.width(), ancho), t.height())
            x += t.width() + self._hueco
            alto_fila = max(alto_fila, t.height())
        return y + alto_fila

    def hasHeightForWidth(self):          # noqa: N802
        return True

    def heightForWidth(self, w):          # noqa: N802
        return self._colocar(w, False)

    def sizeHint(self):                   # noqa: N802
        ancho = sum(b.sizeHint().width() + self._hueco for b in self._botones)
        return QSize(ancho, self._colocar(ancho, False))

    def minimumSizeHint(self):            # noqa: N802
        ancho = max((b.sizeHint().width() for b in self._botones), default=0)
        return QSize(ancho, self._colocar(ancho, False))

    def resizeEvent(self, e):             # noqa: N802
        self._colocar(self.width(), True)
        super().resizeEvent(e)

    def actualizar(self):
        self.updateGeometry()
        self._colocar(self.width(), True)


class CapaViva(QObject):
    cambio = Signal()

    def __init__(self, ctrl, timeline=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.timeline = timeline
        self.marcas: list[MA.Marca] = []
        guardado = QSettings("EditorIA", "EditorIA").value("marcas/tipos", None)
        todos = set(MA.TIPOS)
        self.tipos: set[str] = (set(str(guardado).split(",")) & todos) if guardado not in (None, "") else todos
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.recalcular)
        for sig in ("project_changed", "project_replaced", "media_changed", "transcript_changed"):
            s = getattr(ctrl, sig, None)
            if s is not None:
                s.connect(self._timer.start)
        if timeline is not None:
            if hasattr(timeline, "cut_issues_changed"):
                timeline.cut_issues_changed.connect(self._timer.start)
            rep = getattr(timeline, "repetidos", None)
            if rep is not None:
                rep.cambio.connect(self._timer.start)
        self._timer.start()

    def recalcular(self):
        tl = self.timeline
        cuts = list(getattr(tl, "cut_issues", None) or []) if tl is not None else []
        rep = getattr(tl, "repetidos", None) if tl is not None else None
        try:
            nuevas = MA.capa(self.ctrl.project, cuts, rep.mapa if rep is not None else None)
        except Exception:  # noqa: BLE001 - una ayuda visual nunca rompe la edición
            import logging
            logging.getLogger(__name__).exception("capa de marcas")
            nuevas = []
        if nuevas != self.marcas:
            self.marcas = nuevas
            self.cambio.emit()

    def visibles(self) -> list[MA.Marca]:
        return [m for m in self.marcas if m.tipo in self.tipos]

    def poner_tipos(self, tipos: set[str]):
        self.tipos = set(tipos) & set(MA.TIPOS)
        QSettings("EditorIA", "EditorIA").setValue("marcas/tipos", ",".join(sorted(self.tipos)))
        self.cambio.emit()

    def siguiente(self, t: float, paso: int):
        return MA.siguiente(self.marcas, t, paso, self.tipos)


class PanelMarcadores(QWidget):
    def __init__(self, ctrl, capa: CapaViva, ir_a=None, parent=None):
        super().__init__(parent)
        from . import diseno as D
        self.ctrl, self.capa, self.ir_a = ctrl, capa, ir_a
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(4))
        self.fila_tipos = _Fluido(hueco=D.px(4))
        self.botones: dict[str, QPushButton] = {}
        for tipo, (nombre, color) in MA.TIPOS.items():
            b = QPushButton(CORTO[tipo])
            b.setCheckable(True)
            b.setChecked(tipo in capa.tipos)
            b.setIcon(_punto(color))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{nombre}: verlos o no en el índice, en la línea de tiempo y con Mayús+↑ / Mayús+↓.")
            b.toggled.connect(self._filtro)
            self.fila_tipos.poner(b)
            self.botones[tipo] = b
        lay.addWidget(self.fila_tipos)
        self.vacio = D.aviso_vacio("Nada que revisar", "Aquí salen, en el orden del video, las tomas repetidas, las "
                                   "muletillas, los cortes dudosos, las marcas de OBS, los temas, los huecos sin "
                                   "imagen, el material repetido y tus marcadores.")
        lay.addWidget(self.vacio)
        self.lista = QListWidget()
        D.filas_compactas(self.lista)
        self.lista.setWordWrap(True)
        self.lista.itemClicked.connect(self._ir)
        self.lista.currentItemChanged.connect(lambda *_a: self._elegida())
        lay.addWidget(self.lista, 1)
        fila = QHBoxLayout()
        fila.setSpacing(D.px(4))
        self.btn_ok = D.BotonIcono("check", "Está bien así: la marca elegida deja de salir (Ctrl+Z la devuelve).\n"
                                            "Una propuesta de la limpieza se rechaza; un corte dudoso se da por "
                                            "bueno; un marcador queda resuelto.")
        self.btn_ok.clicked.connect(self._ok)
        fila.addWidget(self.btn_ok)
        self.nota = QLineEdit()
        self.nota.setPlaceholderText("Nota del marcador")
        self.nota.setToolTip("La nota del marcador elegido (Enter = guardar, un Ctrl+Z).\n"
                             "En la línea de tiempo, M dos veces en el mismo sitio abre aquí la nota de ese marcador.")
        self.nota.returnPressed.connect(self._guardar_nota)
        fila.addWidget(self.nota, 1)
        lay.addLayout(fila)
        self.btn_tomas = QPushButton("Quitar tomas viejas")
        self.btn_tomas.setIcon(D.icono("scissors"))
        self.btn_tomas.setToolTip("Quitar todas las tomas viejas: de cada toma repetida pendiente quita las anteriores "
                                  "y deja la última que dijiste (también con 3 o más tomas), en todas las pistas a la "
                                  "vez (un Ctrl+Z).")
        self.btn_tomas.clicked.connect(self.quitar_tomas)
        lay.addWidget(self.btn_tomas)
        capa.cambio.connect(self.refrescar)
        self.refrescar()

    # ------------------------------------------------------------ al día
    def refrescar(self):
        actual = self.marca_elegida()
        n = MA.contar(self.capa.marcas)
        for tipo, b in self.botones.items():
            b.blockSignals(True)
            b.setChecked(tipo in self.capa.tipos)
            b.blockSignals(False)
            b.setText(f"{CORTO[tipo]} · {n.get(tipo, 0)}")
            b.setMinimumWidth(b.sizeHint().width())         # (el texto entero, nunca cortado)
        self.fila_tipos.actualizar()
        self.lista.blockSignals(True)
        self.lista.clear()
        elegir = None
        for m in self.capa.visibles():
            it = QListWidgetItem(_punto(MA.TIPOS[m.tipo][1]), f"{MA._mmss(m.t)}  {m.texto}")
            it.setToolTip(f"{MA.TIPOS[m.tipo][0]} · {MA._mmss(m.t)}" +
                          (f"–{MA._mmss(m.fin)}" if m.fin else "") + f"\n{m.texto}\nClic = el cabezal aquí.")
            it.setData(ROL_MARCA, m)
            self.lista.addItem(it)
            if actual is not None and (m.tipo, m.ref) == (actual.tipo, actual.ref):
                elegir = it
        self.lista.blockSignals(False)
        if elegir is not None:
            self.lista.setCurrentItem(elegir)
        vacia = self.lista.count() == 0
        self.lista.setVisible(not vacia)
        self.vacio.setVisible(vacia)
        n_tomas = n.get("toma", 0)                         # (una marca por cada toma que se quitaría)
        self.btn_tomas.setText(f"Quitar tomas viejas · {n_tomas}")
        self.btn_tomas.setMinimumWidth(self.btn_tomas.sizeHint().width())
        self.btn_tomas.setEnabled(n_tomas > 0)
        self._elegida()

    def marca_elegida(self) -> MA.Marca | None:
        it = self.lista.currentItem()
        return it.data(ROL_MARCA) if it is not None else None

    def _elegida(self):
        m = self.marca_elegida()
        self.btn_ok.setEnabled(m is not None)
        es_marcador = m is not None and m.tipo in ("marcador", "obs")
        self.nota.setEnabled(es_marcador)
        if es_marcador and not self.nota.hasFocus():
            mk = next((x for x in self.ctrl.project.markers if x.id == m.ref), None)
            self.nota.setText(getattr(mk, "note", "") if mk is not None else "")
        elif not es_marcador:
            self.nota.clear()

    # ------------------------------------------------------------ acciones
    def _filtro(self, _on=None):
        self.capa.poner_tipos({t for t, b in self.botones.items() if b.isChecked()})

    def _ir(self, it):
        m = it.data(ROL_MARCA) if it is not None else None
        if m is not None and self.ir_a is not None:
            self.ir_a(m.t)

    def _ok(self):
        m = self.marca_elegida()
        if m is not None:
            msg = MA.dar_por_revisada(self.ctrl, m)
            self.ctrl.message.emit(msg)

    def _guardar_nota(self):
        m = self.marca_elegida()
        if m is not None and m.tipo in ("marcador", "obs"):
            self.ctrl.update_marker(m.ref, note=self.nota.text().strip())

    def quitar_tomas(self) -> str:
        msg = MA.quitar_tomas_viejas(self.ctrl)
        if msg:
            self.ctrl.message.emit(msg)
        return msg

    def editar_nota(self, marker_id: str) -> bool:
        """M+M: elige ese marcador en el índice (aunque su tipo esté oculto) y pone el foco en su nota."""
        mk = next((x for x in self.ctrl.project.markers if x.id == marker_id), None)
        if mk is None:
            return False
        tipo = "obs" if (mk.color or "").lower() == MA.COLOR_OBS else "marcador"
        if tipo not in self.capa.tipos:
            self.capa.poner_tipos(self.capa.tipos | {tipo})
        self.capa.recalcular()
        self.refrescar()
        for i in range(self.lista.count()):
            m = self.lista.item(i).data(ROL_MARCA)
            if m.ref == marker_id:
                self.lista.setCurrentRow(i)
                self.lista.scrollToItem(self.lista.item(i))
                break
        self.nota.setEnabled(True)
        self.nota.setText(getattr(mk, "note", ""))
        self.nota.setFocus()
        self.nota.selectAll()
        return True


def instalar(win) -> PanelMarcadores | None:
    """Pone el índice en la sección «Marcadores» del Inspector si tiene el gancho (poner_marcadores). Una vez."""
    ins = getattr(win, "inspector", None)
    panel = getattr(win, "marcadores_panel", None)
    if ins is None or panel is None or not hasattr(ins, "poner_marcadores") or getattr(ins, "_marcadores", None):
        return None
    ins.poner_marcadores(panel)
    ins._marcadores = panel
    return panel
