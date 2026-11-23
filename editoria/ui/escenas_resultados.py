"""
🎬 Resultados de Escenas (columna de la derecha de la página, bajo «lo elegido»).

Cada escena creada (con «🎬 Crear escena» o ya puesta en la línea de tiempo) sale aquí con su miniatura, su nombre
entero y su duración, y con sus acciones SIEMPRE a la vista:
  · Copiar (Ctrl+C con ella elegida): en el editor, Ctrl+V la pega en el cabezal (el portapapeles de clips de siempre:
    controller.copy_scene_clip + paste_clips).
  · Poner en el cabezal: la pone ya en la línea de tiempo, en el cabezal del editor (un paso de Ctrl+Z).
  · Abrir para editar: la carga en la página.
  · Arrastrarla a la línea de tiempo también vale (lleva el medio de Medios ▸ «🎬 Escenas»: MEDIA_MIME).
La escena sigue guardándose en Medios como siempre.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from . import diseno as D
from . import theme as T

ANCHO_MINI, ALTO_MINI = 156, 88          # (16:9; en proyectos verticales la miniatura va centrada)


def _miniatura(ruta: str, w: int, h: int) -> QPixmap:
    """La miniatura de la escena (PNG transparente) sobre un damero oscuro, del tamaño pedido (sin deformar)."""
    pm = QPixmap(w, h)
    pm.fill(QColor("#15171a"))
    p = QPainter(pm)
    cuadro = max(4, h // 6)
    for y in range(0, h, cuadro):
        for x in range(0, w, cuadro):
            if (x // cuadro + y // cuadro) % 2:
                p.fillRect(x, y, cuadro, cuadro, QColor("#1d2024"))
    if ruta and os.path.isfile(ruta):
        img = QPixmap(ruta)
        if not img.isNull():
            img = img.scaled(QSize(w, h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - img.width()) // 2, (h - img.height()) // 2, img)
    p.setPen(QColor(T.BORDER))
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    p.end()
    return pm


class EtiquetaPartida(QLabel):
    """Texto ENTERO en varias líneas: por palabras y, si una palabra (o un nombre sin espacios) no cabe, por letras
    (como «Carpeta: …» de Descargas). Nunca se corta ni pide más ancho del que tiene."""

    def __init__(self, texto: str = "", parent=None):
        super().__init__(parent)
        self._completo = ""
        self._ancho_hecho = -1
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setWordWrap(False)
        self.poner(texto)

    def poner(self, texto: str):
        self._completo = str(texto or "")
        self._ancho_hecho = -1
        self._partir()

    def texto_completo(self) -> str:
        return self._completo

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._partir()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.FontChange:
            self._ancho_hecho = -1
            self._partir()

    def _partir(self):
        from .descargas_generales import partir_en_lineas
        libre = max(20, self.width() - 2) if self.width() > 30 else D.px(ANCHO_MINI)
        if libre == self._ancho_hecho:
            return
        self._ancho_hecho = libre
        texto = partir_en_lineas(self.fontMetrics(), self._completo, libre)
        if texto != self.text():
            self.setText(texto)
            self.updateGeometry()


class TarjetaResultado(QFrame):
    """Una escena del panel: miniatura, nombre (en varias líneas si hace falta), duración y sus 3 botones."""
    elegida = Signal(str)

    def __init__(self, panel, eid: str, nombre: str, dura: float, ruta: str, media_id: str):
        super().__init__()
        self.panel, self.eid, self.media_id = panel, eid, media_id
        self.setObjectName("tarjeta_resultado")
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"«{nombre}» · {dura:.1f} s\nClic = elegirla (Ctrl+C la copia) · arrástrala a la línea de "
                        "tiempo para ponerla ahí · doble clic = abrirla para editar")
        self._desde: QPoint | None = None
        col = QVBoxLayout(self)
        col.setContentsMargins(D.px(D.M1), D.px(D.M1), D.px(D.M1), D.px(D.M1))
        col.setSpacing(D.px(2))
        self.mini = QLabel()                              # (miniatura grande arriba: se reconoce de un vistazo)
        self.mini.setPixmap(_miniatura(ruta, D.px(ANCHO_MINI), D.px(ALTO_MINI)))
        self.mini.setFixedSize(D.px(ANCHO_MINI), D.px(ALTO_MINI))
        col.addWidget(self.mini, 0, Qt.AlignHCenter)
        self.nombre = EtiquetaPartida(nombre)              # (el nombre entero, en varias líneas: nunca cortado)
        D.poner_letra(self.nombre, D.LETRA_M)
        col.addWidget(self.nombre)
        self.dura = QLabel(f"{dura:.1f} s".replace(".", ","))
        D.poner_letra(self.dura, D.LETRA_P, D.GRIS_TITULO)
        botones = D.fila_fija(QHBoxLayout())              # (duración a la izquierda, acciones a la derecha)
        botones.setContentsMargins(0, 0, 0, 0)
        botones.setSpacing(D.px(D.M1))
        botones.addWidget(self.dura)
        botones.addStretch(1)
        self.b_copiar = D.BotonIcono("copy", "Copiar (Ctrl+C): en el editor, Ctrl+V la pega en el cabezal")
        self.b_cabezal = D.BotonIcono("arrow-down-to-line", "Poner en el cabezal: la pone ya en la línea de tiempo, "
                                                            "donde está el cabezal del editor (Ctrl+Z la quita)")
        self.b_editar = D.BotonIcono("square-pen", "Abrir para editar: la carga aquí (al guardar cambian todos sus "
                                                   "clips)")
        self.b_copiar.clicked.connect(lambda: self.panel.copiar(self.eid))
        self.b_cabezal.clicked.connect(lambda: self.panel.poner_en_cabezal(self.eid))
        self.b_editar.clicked.connect(lambda: self.panel.abrir(self.eid))
        for b in (self.b_copiar, self.b_cabezal, self.b_editar):
            b.setFocusPolicy(Qt.NoFocus)
            botones.addWidget(b)
        col.addLayout(botones)
        self.poner_elegida(False)

    def poner_elegida(self, on: bool):
        c = D.colores()
        borde = T.ACCENT if on else c.get("borde", T.BORDER)
        self.setStyleSheet(f"#tarjeta_resultado {{ border: 1px solid {borde}; border-radius: 4px; "
                           f"background: {c.get('relieve', 'transparent') if on else 'transparent'}; }}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._desde = e.position().toPoint()
            self.panel.elegir(self.eid)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._desde is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position().toPoint() - self._desde).manhattanLength() < 8:
            return
        self._desde = None
        md = self.mime()
        if md is None:
            return
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(self.mini.pixmap())
        drag.exec(Qt.CopyAction)

    def mime(self) -> QMimeData | None:
        """Lo que lleva al arrastrarla: su medio de Medios ▸ «🎬 Escenas» (la línea de tiempo lo pone como clip de
        escena con lo que dura, igual que pegarla)."""
        mid = self.panel.medio_de(self.eid)
        if not mid:
            return None
        from .common import MEDIA_MIME
        md = QMimeData()
        md.setData(MEDIA_MIME, mid.encode())
        return md

    def mouseReleaseEvent(self, e):
        self._desde = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.panel.abrir(self.eid)


class PanelResultados(QWidget):
    """La lista de resultados (escenas creadas) con sus acciones. page = la página Escenas."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.win, self.ctrl = page.win, page.ctrl
        self.tarjetas: dict = {}
        D.medida(self, lambda w: w.setMinimumWidth(D.px(ANCHO_MINI + 3 * D.M2 + 6) if w.tarjetas else D.px(120)))
        self.elegido: str | None = None
        self.tarjetas: dict[str, TarjetaResultado] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(D.px(D.M1))
        cab = D.fila_fija(QHBoxLayout())
        cab.setContentsMargins(D.px(D.M1), 0, D.px(D.M1), 0)
        self.titulo = D.TituloSeccion("Resultados")
        self.titulo.setToolTip("Las escenas creadas: cópialas (Ctrl+C) y pégalas en la línea de tiempo (Ctrl+V), "
                               "ponlas en el cabezal, arrástralas a la línea de tiempo o ábrelas para editarlas. "
                               "También están en Medios ▸ «🎬 Escenas».")
        cab.addWidget(self.titulo, 1)
        v.addLayout(cab)
        self.vacio = QLabel("Aún no hay escenas creadas")
        self.vacio.setToolTip("Pulsa «🎬 Crear escena» arriba: la escena sale aquí con su miniatura, lista para "
                              "copiar y pegar en la línea de tiempo.")
        D.poner_letra(self.vacio, D.LETRA_P, D.GRIS_TITULO)
        self.vacio.setContentsMargins(D.px(D.M2), 0, D.px(D.M2), 0)
        self.vacio.setWordWrap(True)
        v.addWidget(self.vacio)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.caja = QWidget()
        self.lista = QVBoxLayout(self.caja)
        self.lista.setContentsMargins(D.px(D.M1), 0, D.px(D.M1), D.px(D.M1))
        self.lista.setSpacing(D.px(D.M1))
        self.lista.addStretch(1)
        self.area.setWidget(self.caja)
        v.addWidget(self.area, 1)
        sc = QShortcut(QKeySequence.Copy, self)              # (Ctrl+C con una elegida: la copia)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: self.copiar(self.elegido) if self.elegido else None)
        self.setFocusPolicy(Qt.ClickFocus)
        self.refrescar()

    # ---- datos
    def escenas(self) -> list[dict]:
        """Las escenas que ya son un resultado (tienen su medio en Medios ▸ «🎬 Escenas»), la más nueva arriba."""
        from ..core import scenes
        p = self.ctrl.project
        return [e for e in reversed(list(p.scenes.values()))
                if not scenes.es_comparativa(e) and e.get("media_id") and e["media_id"] in p.media]

    def medio_de(self, eid: str) -> str | None:
        e = self.ctrl.project.scenes.get(eid)
        return e.get("media_id") if e else None

    def refrescar(self):
        from ..core import scenes
        p = self.ctrl.project
        for t in self.tarjetas.values():
            self.lista.removeWidget(t)
            t.hide()                                      # (fuera ya: no se pinta un instante encima de la nueva)
            t.setParent(None)
            t.deleteLater()
        self.tarjetas = {}
        escenas = self.escenas()
        for e in escenas:
            m = p.media.get(e["media_id"])
            t = TarjetaResultado(self, e["id"], e.get("nombre") or "Escena", scenes.largo(e),
                                 m.path if m is not None else "", e["media_id"])
            self.lista.insertWidget(self.lista.count() - 1, t)
            t.show()                                      # (al momento: Qt lo dejaría para la vuelta siguiente)
            self.tarjetas[e["id"]] = t
        if self.elegido not in self.tarjetas:
            self.elegido = None
        for k, t in self.tarjetas.items():
            t.poner_elegida(k == self.elegido)
        self.titulo.setText(f"Resultados · {len(escenas)}" if escenas else "Resultados")
        self.vacio.setVisible(not escenas)
        self.area.setVisible(bool(escenas))
        # (vacía, estrecha: el sitio para el visor; con escenas, el ancho de sus tarjetas)
        self.setMinimumWidth(D.px(ANCHO_MINI + 3 * D.M2 + 6) if escenas else D.px(120))
        self.setMaximumWidth(16777215 if escenas else D.px(150))

    def elegir(self, eid: str):
        self.elegido = eid
        for k, t in self.tarjetas.items():
            t.poner_elegida(k == eid)
        self.setFocus()

    # ---- acciones
    def copiar(self, eid: str | None) -> bool:
        if not eid or not self.ctrl.copy_scene_clip(eid):
            return False
        self.win._copia_externa = False                    # (Ctrl+V pegará esta escena, no lo de Windows)
        self.elegir(eid)
        nombre = self.ctrl.project.scenes[eid].get("nombre") or "Escena"
        self.win.statusBar().showMessage(f"«{nombre}» copiada: en el editor, Ctrl+V la pega en el cabezal.", 8000)
        return True

    def poner_en_cabezal(self, eid: str) -> list[str]:
        """La pone ya en la línea de tiempo del editor, en su cabezal (un paso de Ctrl+Z)."""
        if not self.copiar(eid):
            return []
        t = float(getattr(self.win.engine, "time", 0.0) or 0.0)
        try:
            hechos = self.ctrl.paste_clips(t)
        except Exception as exc:  # noqa: BLE001 - EditError: se dice y no se pierde nada
            self.win.statusBar().showMessage(str(exc) or "No se pudo poner la escena.", 8000)
            return []
        hechos = hechos if isinstance(hechos, list) else []
        if hechos:
            tl = getattr(self.win, "timeline", None)
            if tl is not None:
                tl.set_selection(hechos)
            nombre = self.ctrl.project.scenes[eid].get("nombre") or "Escena"
            self.win.statusBar().showMessage(f"«{nombre}» puesta en el cabezal ({t:.1f} s) · Ctrl+Z en el editor "
                                             "la quita.", 8000)
            self.page._llenar_escenas()
        return hechos

    def abrir(self, eid: str):
        pg = self.page
        if eid == pg.escena.get("id"):
            return
        if pg.sucia and pg._tiene_contenido() and not pg._descartar_ok():
            return
        esc, aviso = self.ctrl.scene_state(eid)
        pg._cargar(esc, False, aviso)
        self.elegir(eid)
