"""
Taller de miniaturas (YouTube y Shorts), pensado para entenderse a simple vista (estilo Adobe Express):

  [ formato · deshacer · alinear · ordenar ·······  vista previa · exportar ]
  [ Material / Texto / Elementos / Fondo / Capas ]  [   LIENZO   ]  [ Propiedades de lo elegido ]

Clic en algo del lienzo = elegirlo; arrastrar = moverlo (se pega al centro); asas de las esquinas =
tamaño; asa redonda de arriba = girar. Supr = borrar · Ctrl+D = duplicar · flechas = mover poquito.
Todo se guarda con el proyecto.
"""
from __future__ import annotations

import copy
import json
import math
import os
import time

import cv2
import numpy as np

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QIcon, QImage, QImageReader, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut,
                           QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QGraphicsScene, QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
                               QToolBar, QVBoxLayout, QWidget)

from ..core import thumbnail as T
from ..core.model import KIND_IMAGE, KIND_VIDEO
from .help import set_help
from .thumb_text_bar import TextBar

HANDLE = 9          # tamaño de las asas (píxeles de pantalla)


class _ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str = "#FFFFFF"):
        super().__init__()
        self.setFixedWidth(46)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, c: str):
        self._c = c
        self.setStyleSheet(f"background:{c}; border:1px solid #555; min-height:18px;")

    def _pick(self):
        from .common import pick_color
        c = pick_color(self._c, self, "Color", alpha=True)
        if c.isValid():
            name = c.name(QColor.HexArgb) if c.alpha() < 255 else c.name()
            self.set_color(name)
            self.changed.emit(name)


EFECTOS_COLOR = ("outline", "shadow", "glow")
HISTORIAL_COLORES = 12


class _ColorHistory(QWidget):
    """Los últimos colores usados en un efecto: una fila de muestras; clic = usar ese color."""

    def __init__(self, editor, key: str, usar):
        super().__init__()
        self.editor, self.key, self.usar = editor, key, usar
        self.fila = QHBoxLayout(self)
        self.fila.setContentsMargins(26, 0, 0, 2)
        self.fila.setSpacing(4)
        self.refresh()

    def refresh(self):
        while self.fila.count():
            w = self.fila.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        colores = self.editor.color_history(self.key)
        for c in colores:
            b = QPushButton()
            b.setFixedSize(18, 18)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(f"Usar este color ({c})")
            b.setStyleSheet(f"QPushButton {{ background:{c}; border:1px solid #666; border-radius:3px; padding:0; "
                            "min-height:0; min-width:0; } QPushButton:hover { border:1px solid white; }")
            b.clicked.connect(lambda _=False, col=c: self.usar(col))
            self.fila.addWidget(b)
        self.fila.addStretch()
        self.setVisible(bool(colores))


class _SliderNum(QWidget):
    """Barrita con su número a la derecha (se escribe o se mueve con la rueda). Mientras se arrastra no se aplica en
    cada paso: espera a que pares una décima de segundo (o a que sueltes), para no atascar el ordenador."""
    applied = Signal(float)

    def __init__(self, lo: float, hi: float, val: float, scale: float = 1.0, decimals: int = 0, suffix: str = ""):
        super().__init__()
        self._scale = scale
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(round(lo * scale)), int(round(hi * scale)))
        self.slider.setValue(int(round(val * scale)))
        self.num = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            self.num.setDecimals(decimals)
        self.num.setRange(lo if decimals else int(round(lo * scale)), hi if decimals else int(round(hi * scale)))
        self.num.setValue(val if decimals else int(round(val * scale)))
        self.num.setSuffix(suffix)
        self.num.setButtonSymbols(QSpinBox.NoButtons)
        self.num.setFixedWidth(58)
        self.num.setAlignment(Qt.AlignRight)
        self._decimals = decimals
        h.addWidget(self.slider, 1)
        h.addWidget(self.num)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._apply)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.sliderReleased.connect(self._apply)
        self.num.valueChanged.connect(self._from_num)

    def value(self) -> float:
        return self.slider.value() / self._scale

    def _from_slider(self, v: int):
        self.num.blockSignals(True)
        self.num.setValue(v / self._scale if self._decimals else v)
        self.num.blockSignals(False)
        self._timer.start()

    def _from_num(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v * self._scale)) if self._decimals else int(v))
        self.slider.blockSignals(False)
        self._timer.start()

    def _apply(self):
        self._timer.stop()
        self.applied.emit(self.value())


def _a_papelera(path: str) -> bool:
    """A la Papelera de Windows (recuperable)."""
    from .library import _to_trash
    return _to_trash(path)


MAT_KIND, MAT_MEDIA = Qt.UserRole + 1, Qt.UserRole + 2     # tipo de cada imagen de «Material» y su id de Medios
RECIENTES_MAX = 80


class _MaterialList(QListWidget):
    """La lista «Material»: arrastrar una imagen al lienzo la añade donde se suelte; soltar aquí imágenes (o carpetas)
    del Explorador o del escritorio las añade al material (y a «Medios» del proyecto)."""
    dropped = Signal(list)

    def _externos(self, e) -> bool:
        return e.source() is not self and e.mimeData().hasUrls() and any(
            u.isLocalFile() for u in e.mimeData().urls())

    def dragEnterEvent(self, e):
        if self._externos(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._externos(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if self._externos(e):
            e.acceptProposedAction()
            self.dropped.emit([os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])
        else:
            e.ignore()

    def mimeData(self, items):
        from PySide6.QtCore import QMimeData, QUrl
        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items if it.data(Qt.UserRole)])
        return m


class Canvas(QGraphicsView):
    """El lienzo: dibuja la miniatura y permite mover, escalar y girar capas con el ratón. Clic derecho en una
    capa: su menú (cortar, copiar, orden, llenar, quitar fondo, mejorar, cara graciosa, eliminar…)."""

    def mouseDoubleClickEvent(self, e):
        if self.tool or e.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(e)
        hit = self._hit(self.mapToScene(e.position().toPoint()))
        changed = bool(hit) and hit != self.sel
        if changed:                                    # doble clic en OTRA capa del lienzo: esa pasa a ser la elegida
            self._drag = None
            self.multi.clear()
            self.sel = hit
            self.selected.emit(hit)
            self.viewport().update()
        lay = self.editor.layer(hit)
        if lay is not None and lay["kind"] == "text" and not lay.get("locked"):
            palabra = self.word_at(lay, self.mapToScene(e.position().toPoint()))
            if palabra is not None:                    # doble clic en una palabra: esa queda elegida (barra = solo ella)
                self.set_words({palabra}, lay, panel=False)
            self.editor.edit_text(lay, palabra)        # (en un texto, además, a escribirlo: como siempre)
            return
        if changed:
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        if self.tool:                                  # (con un pincel activo, el clic derecho no hace nada)
            return
        pt = self.mapToScene(e.pos())
        hit = self._hit(pt)
        if hit and hit != self.sel:
            self.sel = hit
            self.selected.emit(hit)
        self.viewport().update()
        self.editor.layer_menu(self.editor.layer(hit) if hit else None).exec(e.globalPos())
    selected = Signal(str)          # id de la capa elegida ("" = ninguna)
    committed = Signal(str)         # terminó un arrastre: guardar en el historial
    zoomChanged = Signal(float)     # el zoom (1 = la miniatura entera a la vista)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self._liq_finishing: dict[str, int] = {}   # capa → turno: su versión buena se está haciendo en segundo plano
        self._liq_jobs: list = []
        self._draft_memo = None           # (id, licuado, reducción, imagen): la vista rápida del último toque
        self._last: dict[str, tuple] = {}  # capa → la última imagen buena (se sigue viendo mientras se hace la nueva)
        self._bg_jobs: dict[str, object] = {}   # capa → su dibujo en segundo plano (como mucho uno por capa)
        self._size_live = ""              # la capa a la que se le está cambiando el tamaño (no se redibuja hasta soltar)
        self._size_timer = QTimer(self)   # Alt + rueda: «terminó» cuando deja de girar un momento
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(180)
        self._size_timer.timeout.connect(self._size_end)
        self._words: set[int] = set()     # palabras elegidas del texto elegido (la barra y el panel solo las cambian a ellas)
        self._words_of = ""               # de qué capa son
        self._ink: QImage | None = None   # 🖌 el trazo en curso, a tamaño de pantalla (solo se le añade lo nuevo)
        self._ink_key = None
        self._ink_done = True
        self._bs: dict | None = None      # 🖌 Recuperar: lo borrado visible y lo pintado (se actualiza solo lo tocado)
        self._bs_job = None
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#0b0b0d"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.sel: str = ""
        self._drag: dict | None = None
        self._guides: list = []
        self.tool: str | None = None      # None | "box" (marcar sujeto) | "erase" | "restore" (pincel) | "blurzone"
        self.blur_shape = "rect"          # 🌫 la forma de la zona que se crea: "rect" | "ellipse"
        self.warp_mode = False            # ◇ Deformar: las esquinas se mueven cada una por su lado
        self.brush = 30                   # radio del pincel (píxeles del lienzo)
        self._stroke: list = []
        self._hover = None
        self._crop_prev: dict | None = None    # ⬚ recortando con un lado: la imagen entera y el recorte al vuelo
        self.multi: set[str] = set()            # Mayús+clic / Ctrl+A: varias capas elegidas (se mueven y borran juntas)
        self.liq_mode = "inflar"          # ≈ Licuar: inflar | encoger | empujar | restaurar
        self.liq_strength = 0.5
        self._liq_timer = QTimer(self)    # inflar/encoger mientras se mantiene pulsado (como en Photoshop)
        self._liq_timer.setInterval(40)
        self._liq_timer.timeout.connect(self._liq_tick)
        self.zoom = 1.0                   # 1 = encajada; Ctrl + rueda acerca o aleja, donde esté el ratón
        self.guides = ""                  # "" | "centro" | "tercios" | "cuartos" | "youtube" (lo que tapa YouTube)
        self._pan = None
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)         # soltar imágenes: del Explorador, del navegador «🔎 PNG», de «Medios»…
        self.viewport().setAcceptDrops(True)

    # ------------------------------------------------------------- dibujo
    @property
    def doc(self) -> dict:
        return self.editor.doc

    def refresh(self):
        """Encaja la miniatura (y aplica el zoom). Se puede ir más allá del borde: hay sitio alrededor."""
        d = self.doc
        self.setSceneRect(QRectF(-d["w"], -d["h"], d["w"] * 3, d["h"] * 3))
        vp = self.viewport().size()
        k0 = min(vp.width() / (d["w"] + 40), vp.height() / (d["h"] + 40)) if vp.width() > 0 else 1.0
        from PySide6.QtGui import QTransform
        self.setTransform(QTransform.fromScale(k0 * self.zoom, k0 * self.zoom))
        if self.zoom <= 1.0001:
            self.centerOn(d["w"] / 2, d["h"] / 2)
        self.viewport().update()

    def set_zoom(self, z: float, anchor: QPointF | None = None):
        """Zoom (1 = encajada), manteniendo quieto el punto del lienzo que está bajo el ratón."""
        z = max(0.2, min(8.0, float(z)))
        if abs(z - self.zoom) < 1e-6:
            return
        before = self.mapToScene(anchor.toPoint()) if anchor is not None else None
        self.zoom = z
        self.refresh()
        if before is not None:
            after = self.mapToScene(anchor.toPoint())
            c = self.mapToScene(self.viewport().rect().center())
            self.centerOn(c + (before - after))
        self.zoomChanged.emit(self.zoom)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.AltModifier:                      # Alt + rueda: agrandar / achicar lo elegido
            lay = self.editor.layer(self.sel)
            delta = e.angleDelta().y() or e.angleDelta().x()     # (con Alt, Windows manda la rueda «de lado»)
            if lay is not None and not lay.get("locked") and delta:
                self._size_live = lay["id"]             # ⚡ se ve al vuelo; la imagen buena, al dejar de girar
                self._size_timer.start()
                lay["scale"] = round(max(0.02, float(lay["scale"]) * 1.06 ** (delta / 120.0)), 4)
                self.viewport().update()
                self.editor.on_live_change()
                self.committed.emit("Tamaño (rueda)")
            e.accept()
            return
        if e.modifiers() & Qt.ControlModifier:                 # Ctrl + rueda: acercar / alejar donde está el ratón
            steps = e.angleDelta().y() / 120.0
            self.set_zoom(self.zoom * (1.2 ** steps), e.position())
            e.accept()
            return
        super().wheelEvent(e)                                   # (rueda sola: mover arriba/abajo; Mayús: a los lados)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refresh()

    def drawBackground(self, p: QPainter, rect: QRectF):
        super().drawBackground(p, rect)
        d = self.doc
        marco = QRectF(0, 0, d["w"], d["h"])
        for lay in d["layers"]:                                 # lo que se sale del encuadre, en tenue
            if not lay.get("visible", True):
                continue
            if not lay.get("blur_area") and marco.contains(self._outer(lay)):
                continue                                        # ⚡ entera dentro: esta pasada no se vería
            p.save()
            p.setOpacity(float(lay.get("opacity", 1.0)) * 0.28)
            self._draw_layer(p, lay)
            p.restore()
        p.save()
        p.setClipRect(QRectF(0, 0, d["w"], d["h"]))
        T.paint_background(p, d)
        for lay in d["layers"]:
            if not lay.get("visible", True):
                continue
            p.save()
            p.setOpacity(float(lay.get("opacity", 1.0)))
            if not lay.get("blur_area"):
                p.setCompositionMode(T.blend_mode(lay))         # 🎚 modo de fusión (multiplicar, trama…)
            self._draw_layer(p, lay)
            p.restore()
        p.restore()
        p.setPen(QPen(QColor("#333"), 0))
        p.drawRect(QRectF(0, 0, d["w"], d["h"]))

    def _draw_layer(self, p: QPainter, lay: dict):
        if lay.get("blur_area"):                                # 🌫 zona borrosa: lo de debajo, desenfocado
            idx = next((i for i, l in enumerate(self.doc["layers"]) if l is lay), 0)
            T.paint_blur_area(p, self.doc, idx, lay, 1.0)
            return
        cp = self._crop_prev
        if cp is not None and cp["id"] == lay["id"]:            # ⬚ recortando: sin volver a procesar la imagen
            p.setTransform(cp["t"], True)
            p.setClipRect(self._crop_rect(cp))
            p.drawImage(0, 0, cp["img"])
            return
        img, _w, _h = self._render(lay)
        p.setTransform(T.layer_transform(lay, img), True)
        p.drawImage(0, 0, img)
        bs = self._brush_view(lay, img)
        if bs is not None:                                      # 🖌 Recuperar: en su sitio entre las capas (el texto, encima)
            p.drawImage(QPointF((img.width() - bs["w"]) / 2, (img.height() - bs["h"]) / 2), bs["qimg"])

    def _view(self) -> float:
        """Píxeles de pantalla por píxel del lienzo (el zoom de la vista)."""
        return max(self.transform().m11(), 1e-3)

    def _render(self, lay: dict):
        """La imagen de la capa: mientras se arrastra ≈ Licuar / ✋ Estirar (y hasta que la buena esté hecha en segundo
        plano), la vista rápida; si no, la buena. Antes cada movimiento del ratón recalculaba contorno, brillo y sombra
        (1–3 s con una imagen grande). La vista rápida se guarda: el mismo toque no se vuelve a deformar al pintarlo,
        al buscar el punto y al ver el recuadro."""
        d = self._drag
        if (d is not None and d.get("mode") == "liquify" and d.get("lay") is lay) or (
                lay.get("id") in self._liq_finishing and not T.is_rendered(lay)):
            liq = lay.get("liquify")
            kd = T.draft_k(lay, self._view())
            m = self._draft_memo
            same = m is not None and m[0] == lay.get("id") and m[2] == kd
            if same and m[1] is liq:
                return m[3]                       # mismo licuado (liquify._store crea un dict nuevo en cada toque)
            img, cw, ch, st = T.draft_render(lay, kd, m[4] if same else None)   # solo lo tocado desde el toque anterior
            self._draft_memo = (lay.get("id"), liq, kd, (img, cw, ch), st)
            return img, cw, ch
        lid = lay.get("id")
        got = self._last.get(lid)
        forma = (lay.get("path"), lay.get("crop"), lay.get("text"))                        # (recortar o cambiar de archivo
        last = got[0] if got is not None and got[1] == forma else None                    # no se puede ver con la vieja)
        if last is not None and not lay.get("blur_area") and not T.is_rendered(lay):
            # ⚡ Nunca se congela por dibujar: mientras llega la imagen buena se sigue viendo la última, ya con su sitio y
            # su tamaño nuevos. El tamaño, hasta soltar (dibujarla en cada movimiento del ratón no serviría de nada);
            # las imágenes, además, en segundo plano.
            if lid == self._size_live:
                return last
            if lay.get("kind") == "image":
                self._render_bg(lay)
                return last
        res = T.render_layer(lay)
        self._last[lid] = (res, forma)
        return res

    def _render_bg(self, lay: dict):
        """Dibuja la capa en segundo plano. Al terminar se repinta: si mientras tanto volvió a cambiar, _render lo pide
        otra vez (así nunca hay más de un dibujo por capa, por deprisa que muevas el deslizador)."""
        lid = lay["id"]
        if lid in self._bg_jobs:
            return
        from .jobs import BackgroundJob
        snap = copy.deepcopy(lay)
        job = BackgroundJob(lambda _p, _c: T.render_layer(snap), self)

        def fin(*_a):
            if self._bg_jobs.get(lid) is job:
                self._bg_jobs.pop(lid, None)
            try:
                actual = self.editor.layer(lid)
                if actual is not None and T.is_rendered(actual):
                    self._last[lid] = (T.render_layer(actual), (actual.get("path"), actual.get("crop"),
                                                                actual.get("text")))
                self.viewport().update()
                if self._drag is None and not self._bg_jobs:
                    self.editor._refresh_layers()
            except RuntimeError:                       # (la ventana ya se cerró)
                pass
        job.done.connect(fin)
        job.failed.connect(fin)
        self._bg_jobs[lid] = job
        job.start()

    def wait_renders(self, ms: int = 3000):
        """Espera a que acaben los dibujos en segundo plano (al cerrar el taller)."""
        for job in list(self._bg_jobs.values()):
            job.wait(ms)

    def _size_end(self):
        if self._size_live:
            self._size_live = ""
            self.viewport().update()

    # ------------------------------------------------------------- 🖌 pincel: solo se dibuja lo nuevo
    def _brush_key(self, lay: dict, img: QImage) -> tuple:
        return (lay["id"], lay.get("path"), tuple(lay.get("crop") or ()), lay.get("mask"),
                json.dumps(lay.get("adj"), sort_keys=True), T.image_k(img))

    def _brush_view(self, lay: dict, img: QImage) -> dict | None:
        """🖌 Recuperar: lo borrado de la capa, tenue, y lo que vas pintando, ya como la imagen real."""
        if self.tool != "restore" or lay.get("id") != self.sel or lay.get("kind") != "image" or lay.get("liquify") \
                or not lay.get("mask"):
            return None
        bs = self._bs
        if bs is not None and bs["pending"] is not None and self._drag is None and not self.editor.brush_busy() \
                and T.is_rendered(lay):
            m, bs["pending"] = bs["pending"], None      # ya está dibujada la buena: lo pintado pasa a ser parte de ella
            bs["live"][:] = 0
            bs["ghost"] = ((255 - m.astype(np.uint16)) * 90 // 255).astype(np.uint8)
            bs["ov"][..., 3] = (bs["ghost"].astype(np.uint16) * bs["src_a"] // 255).astype(np.uint8)
        key = self._brush_key(lay, img)
        if bs is None or bs["key"] != key:
            self._brush_prepare(lay, img, key)
            return None
        return bs

    def _brush_prepare(self, lay: dict, img: QImage, key: tuple):
        """Prepara en segundo plano la imagen sin máscara (al activar el pincel: el primer trazo no espera)."""
        if self._bs_job is not None:
            return
        from .jobs import BackgroundJob
        snap, k = copy.deepcopy(lay), T.image_k(img)
        cw, ch = T._core_size(lay, img)

        def work(_p, _c):
            rgba = T.image_unmasked(snap, k)
            return rgba, T.mask_core(snap, k, rgba.shape[1], rgba.shape[0])
        job = BackgroundJob(work, self)

        def fin(res=None):
            self._bs_job = None
            if not isinstance(res, tuple):
                return
            rgba, m = res
            h, w = rgba.shape[:2]
            if abs(w - cw) > 1 or abs(h - ch) > 1:
                return
            ghost = ((255 - m.astype(np.uint16)) * 90 // 255).astype(np.uint8)      # lo borrado, a un 35 %
            src_a = rgba[..., 3].copy()
            ov = rgba.copy()
            ov[..., 3] = (ghost.astype(np.uint16) * src_a // 255).astype(np.uint8)
            self._bs = {"key": key, "w": w, "h": h, "ov": ov, "src_a": src_a, "ghost": ghost,
                        "live": np.zeros((h, w), np.uint8), "pending": None,
                        "qimg": QImage(ov.data, w, h, w * 4, QImage.Format_RGBA8888)}
            try:
                self.viewport().update()
            except RuntimeError:
                pass
        job.done.connect(fin)
        job.failed.connect(lambda _m: fin())
        self._bs_job = job
        job.start()

    def _bs_ink(self, a: QPointF, b: QPointF) -> bool:
        """Pinta el tramo a–b sobre la vista de Recuperar (solo el trocito tocado). False = aún no está lista."""
        lay = self.editor.layer(self.sel)
        if lay is None or self.tool != "restore":
            return False
        img, _cw, _ch = self._render(lay)
        bs = self._bs
        if bs is None or bs["key"] != self._brush_key(lay, img):
            return False
        inv, ok = T.layer_transform(lay, img).inverted()
        if not ok:
            return False
        x0, y0 = (img.width() - bs["w"]) / 2, (img.height() - bs["h"]) / 2
        pa, pb = inv.map(a), inv.map(b)
        r = max(1, int(self.brush / max(T.layer_scale(lay, img), 1e-6)))
        p0, p1 = (int(pa.x() - x0), int(pa.y() - y0)), (int(pb.x() - x0), int(pb.y() - y0))
        cv2.line(bs["live"], p0, p1, int(255 * self.editor.brush_opt("alpha")), 2 * r + 1, cv2.LINE_AA)
        xa, xb = max(0, min(p0[0], p1[0]) - r - 3), min(bs["w"], max(p0[0], p1[0]) + r + 4)
        ya, yb = max(0, min(p0[1], p1[1]) - r - 3), min(bs["h"], max(p0[1], p1[1]) + r + 4)
        if xa < xb and ya < yb:
            roi = np.maximum(bs["live"][ya:yb, xa:xb], bs["ghost"][ya:yb, xa:xb]).astype(np.uint16)
            bs["ov"][ya:yb, xa:xb, 3] = (roi * bs["src_a"][ya:yb, xa:xb] // 255).astype(np.uint8)
        return True

    def _ink_seg(self, a: QPointF, b: QPointF):
        """Añade el tramo a–b a la tinta del trazo (rojo = borrar). Volver a dibujar el trazo entero en cada movimiento
        era lo que lo hacía ir a saltos: cuanto más largo, más lento."""
        vp = self.viewport().size()
        vt = self.viewportTransform()
        key = (vp.width(), vp.height(), vt.m11(), vt.m22(), vt.m31(), vt.m32())
        tramos = [(a, b)]
        if self._ink is None or self._ink_key != key:         # (zoom o tamaño nuevos: la tinta se rehace)
            self._ink = QImage(max(1, vp.width()), max(1, vp.height()), QImage.Format_ARGB32_Premultiplied)
            self._ink.fill(Qt.transparent)
            self._ink_key = key
            tramos = list(zip(self._stroke, self._stroke[1:])) or [(a, b)]
        col = QColor(229, 65, 60) if self.tool == "erase" else QColor(80, 200, 120)
        p = QPainter(self._ink)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(col, self.brush * 2 * vt.m11(), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for u, v in tramos:
            p.drawLine(vt.map(u), vt.map(v))
        p.end()

    def _brush_seg(self, a: QPointF, b: QPointF):
        if not self._bs_ink(a, b):
            self._ink_seg(a, b)

    def _brush_dirty(self, *pts) -> QRect:
        """La zona de pantalla que tocan esos puntos con el pincel: solo esa se repinta."""
        r = QRect()
        rad = self.brush + 4 / max(self.transform().m11(), 1e-6)
        for pt in pts:
            if pt is not None:
                q = self.mapFromScene(QRectF(pt.x() - rad, pt.y() - rad, 2 * rad, 2 * rad)).boundingRect()
                r = r.united(q.adjusted(-3, -3, 3, 3))
        return r

    def brush_done(self, lid: str, mask: str, core):
        """Llegó el resultado de un trazo."""
        bs = self._bs
        if bs is not None and bs["key"][0] == lid and core is not None:
            bs["key"] = bs["key"][:3] + (mask,) + bs["key"][4:]
            bs["pending"] = core if core.shape == (bs["h"], bs["w"]) else None
        self._ink_done = True
        self.viewport().update()

    # ------------------------------------------------------------- palabras del texto elegido
    def active_words(self, lay: dict | None = None) -> set[int]:
        """Las palabras elegidas de esa capa (de la elegida si no se dice); vacío si son de otra o ya no existen."""
        lay = lay if lay is not None else self.editor.layer(self.sel)
        if lay is None or lay.get("kind") != "text" or lay.get("id") != self._words_of or lay.get("id") != self.sel:
            return set()
        return {i for i in self._words if i < len(T.word_spans(lay.get("text", "")))}

    def set_words(self, words: set[int], lay: dict | None = None, panel: bool = True):
        """Elige esas palabras. panel=False: sin rehacer el panel (cuando el cambio viene del propio cuadro de texto)."""
        lay = lay if lay is not None else self.editor.layer(self.sel)
        lid = lay.get("id", "") if lay is not None and words else ""
        if words == self._words and lid == self._words_of:
            return
        self._words, self._words_of = set(words), lid
        self.viewport().update()
        if panel:
            self.editor._fill_props()

    def word_at(self, lay: dict, pt: QPointF) -> int | None:
        """La palabra de ese texto que hay en ese punto del lienzo (None = ninguna)."""
        if lay is None or lay.get("kind") != "text":
            return None
        img, cw, ch = self._render(lay)
        for i, q in T.word_quads(lay, img, cw, ch):
            if q.containsPoint(pt, Qt.OddEvenFill):
                return i
        return None

    def _finish_liquify(self, lay: dict):
        """Al soltar: la versión buena (con los efectos rehechos sobre lo licuado) se dibuja en segundo plano; mientras,
        se sigue viendo la rápida. Así soltar no congela la ventana."""
        if lay.get("kind") != "image" or not lay.get("liquify") or T.is_rendered(lay):
            return
        from .jobs import BackgroundJob
        lid = lay["id"]
        turn = self._liq_finishing.get(lid, 0) + 1
        self._liq_finishing[lid] = turn
        snap = copy.deepcopy(lay)

        def fin(*_a, lid=lid, turn=turn):
            if self._liq_finishing.get(lid) == turn:
                self._liq_finishing.pop(lid, None)
                self.viewport().update()
                try:
                    self.editor._refresh_layers()
                except Exception:  # noqa: BLE001
                    pass
        job = BackgroundJob(lambda _p, _c: T.render_layer(snap), self)
        job.done.connect(fin)
        job.failed.connect(fin)
        job.finished.connect(lambda j=job: self._liq_jobs.remove(j) if j in self._liq_jobs else None)
        self._liq_jobs.append(job)
        job.start()

    # ------------------------------------------------------------- ⬚ recortar con los lados
    @staticmethod
    def _crop_rect(cp: dict) -> QRectF:
        x0, y0, x1, y1 = cp["crop"]
        return QRectF(cp["px"] + x0 * cp["fw"], cp["py"] + y0 * cp["fh"], (x1 - x0) * cp["fw"], (y1 - y0) * cp["fh"])

    def _crop_start(self, lay: dict, side: str) -> dict:
        """La imagen entera (sin recorte) colocada justo debajo de la capa: se prepara UNA vez al empezar."""
        full = copy.deepcopy(lay)
        full["crop"] = [0.0, 0.0, 1.0, 1.0]
        full["x"] = full["y"] = 0.0
        fimg, fw, fh = T.render_layer(full)
        px, py = (fimg.width() - fw) / 2, (fimg.height() - fh) / 2
        c = [float(v) for v in (lay.get("crop") or [0, 0, 1, 1])]
        o = T.layer_transform(full, fimg).map(QPointF(px + (c[0] + c[2]) / 2 * fw, py + (c[1] + c[3]) / 2 * fh))
        full["x"], full["y"] = float(lay["x"]) - o.x(), float(lay["y"]) - o.y()   # (lo visible, donde está)
        t = T.layer_transform(full, fimg)
        inv, _ok = t.inverted()
        return {"id": lay["id"], "side": side, "img": fimg, "fw": fw, "fh": fh, "px": px, "py": py, "t": t,
                "inv": inv, "crop": c, "c0": list(c)}

    def _crop_move(self, cp: dict, pt: QPointF):
        q = cp["inv"].map(pt)
        u = min(1.0, max(0.0, (q.x() - cp["px"]) / max(1.0, cp["fw"])))
        v = min(1.0, max(0.0, (q.y() - cp["py"]) / max(1.0, cp["fh"])))
        x0, y0, x1, y1 = cp["crop"]
        m = 0.02                                                # (nunca menos del 2 %)
        s = cp["side"]
        if s == "l":
            x0 = min(u, x1 - m)
        elif s == "r":
            x1 = max(u, x0 + m)
        elif s == "t":
            y0 = min(v, y1 - m)
        else:
            y1 = max(v, y0 + m)
        cp["crop"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]

    def _crop_end(self, lay: dict, cp: dict):
        x0, y0, x1, y1 = cp["crop"]
        c = cp["t"].map(QPointF(cp["px"] + (x0 + x1) / 2 * cp["fw"], cp["py"] + (y0 + y1) / 2 * cp["fh"]))
        lay["crop"] = cp["crop"]
        lay["x"], lay["y"] = round(c.x(), 2), round(c.y(), 2)

    @staticmethod
    def _side_points(corners: list) -> dict:
        p0, p1, p2, p3 = corners[:4]
        return {"t": (p0 + p1) / 2, "r": (p1 + p2) / 2, "b": (p2 + p3) / 2, "l": (p3 + p0) / 2}

    def _crop_allowed(self, lay: dict | None) -> bool:
        return bool(lay) and lay["kind"] == "image" and not lay.get("locked") and not self.warp_mode \
            and not T.warp_of(lay)

    def _box(self, lay: dict) -> QPolygonF:
        """Rectángulo (girado) del contenido de la capa, en coordenadas del lienzo."""
        cp = self._crop_prev
        if cp is not None and cp["id"] == lay["id"]:            # (recortando: el recuadro sigue al ratón)
            return cp["t"].map(QPolygonF(self._crop_rect(cp)))
        img, cw, ch = self._render(lay)
        t = T.layer_transform(lay, img)
        x0, y0 = (img.width() - cw) / 2, (img.height() - ch) / 2
        return t.map(QPolygonF(QRectF(x0, y0, cw, ch)))

    def _outer(self, lay: dict) -> QRectF:
        """Lo que ocupa la capa en el lienzo, con sus márgenes de sombra y brillo."""
        img, _cw, _ch = self._render(lay)
        return T.layer_transform(lay, img).mapRect(QRectF(0, 0, img.width(), img.height()))

    def _handles(self, lay: dict) -> dict:
        poly = self._box(lay)
        pts = [poly.at(i) for i in range(4)]
        k = 1 / max(self.transform().m11(), 1e-6)
        top_mid = (pts[0] + pts[1]) / 2
        center = sum(pts, QPointF()) / 4
        v = top_mid - center
        n = math.hypot(v.x(), v.y()) or 1
        rot = top_mid + v / n * 34 * k
        return {"corners": pts, "rot": rot, "center": center, "k": k}

    def drawForeground(self, p: QPainter, rect: QRectF):
        if getattr(self.editor, "text_bar", None) is not None:
            self.editor.text_bar.update_pos()             # la barra de texto sigue a lo elegido (se oculta si no aplica)
        d = self.doc
        k = 1 / max(self.transform().m11(), 1e-6)
        if self._ink is not None:
            cur_ink = self.editor.layer(self.sel)
            if self._ink_done and not self.editor.brush_busy() and self._drag is None and (
                    cur_ink is None or T.is_rendered(cur_ink)):
                self._ink = None                 # el resultado ya se ve: fuera la tinta
            else:
                p.save()
                p.resetTransform()
                p.setOpacity(0.43 * max(0.3, self.editor.brush_opt("alpha")))
                p.drawImage(0, 0, self._ink)
                p.restore()
        if self.tool in ("erase", "restore"):
            if self._hover is not None:
                p.setPen(QPen(QColor("white"), 1.2 * k))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(self._hover, self.brush, self.brush)
        if self.tool == "liquify" and self._hover is not None:
            p.setPen(QPen(QColor("white"), 1.2 * k))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._hover, self.brush, self.brush)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1.0 * k, Qt.DotLine))
            p.drawEllipse(self._hover, self.brush + 1.5 * k, self.brush + 1.5 * k)
        if self.tool in ("box", "blurzone") and self._drag and self._drag.get("mode") == "box":
            p.setPen(QPen(QColor("#e8742f"), 2 * k, Qt.DashLine))
            p.setBrush(QColor(232, 116, 47, 40))
            r = QRectF(self._drag["p0"], self._drag["p1"]).normalized()
            if self.tool == "blurzone" and self.blur_shape == "ellipse":
                p.drawEllipse(r)
            else:
                p.drawRect(r)
        for sl in d["layers"]:                            # 🖼 huecos de plantilla: qué hacer con ellos
            if sl.get("slot") and sl.get("visible", True):
                r = self._box(sl).boundingRect()
                p.save()
                f = p.font()
                f.setPixelSize(max(6, int(min(r.width(), r.height()) * 0.09)))
                p.setFont(f)
                p.setPen(QColor(225, 225, 235))
                p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, "🖼\nSuelta aquí una imagen")
                p.restore()
        self._paint_guides(p, k)
        p.setPen(QPen(QColor(232, 116, 47, 160), 0, Qt.DashLine))
        for g in self._guides:
            if g[0] == "v":
                p.drawLine(QPointF(g[1], 0), QPointF(g[1], d["h"]))
            else:
                p.drawLine(QPointF(0, g[1]), QPointF(d["w"], g[1]))
        for oid in self.multi - {self.sel}:               # las otras elegidas (Mayús+clic): recuadro discontinuo
            o = self.editor.layer(oid)
            if o is not None and o.get("visible", True):
                p.setPen(QPen(QColor("#e8742f"), 1.5 * k, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(self._box(o))
        lay = self.editor.layer(self.sel)
        if lay is None or not lay.get("visible", True):
            return
        h = self._handles(lay)
        k = h["k"]
        p.setPen(QPen(QColor("#e8742f"), 1.5 * k))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF(h["corners"]))
        elegidas = self.active_words(lay)
        if elegidas:                             # las palabras elegidas, resaltadas
            img, cw, ch = self._render(lay)
            p.setPen(QPen(QColor("#ffb27a"), 1.5 * k))
            p.setBrush(QColor(232, 116, 47, 70))
            for i, q in T.word_quads(lay, img, cw, ch):
                if i in elegidas:
                    p.drawPolygon(q)
            p.setBrush(Qt.NoBrush)
        if lay.get("locked"):
            return
        if self.warp_mode:                       # ◇ Deformar: rombos naranjas en las esquinas (sin asa de giro)
            p.setBrush(QColor("#e8742f"))
            p.setPen(QPen(QColor("white"), 1.2 * k))
            r = HANDLE * k * 0.8
            for c in h["corners"]:
                p.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - r), QPointF(c.x() + r, c.y()),
                                         QPointF(c.x(), c.y() + r), QPointF(c.x() - r, c.y())]))
            return
        p.setBrush(QColor("white"))
        for c in h["corners"]:
            p.drawRect(QRectF(c.x() - HANDLE * k / 2, c.y() - HANDLE * k / 2, HANDLE * k, HANDLE * k))
        if (self._crop_allowed(lay) or self._is_zone(lay)) and not self.multi - {lay["id"]}:   # ⬚ recortar (y 🌫 zona)
            rot = float(lay.get("rotation", 0))
            for side, c in self._side_points(h["corners"]).items():
                p.save()
                p.translate(c)
                p.rotate(rot)
                w_, h_ = (HANDLE * 1.9 * k, HANDLE * 0.62 * k) if side in "tb" else (HANDLE * 0.62 * k, HANDLE * 1.9 * k)
                p.drawRect(QRectF(-w_ / 2, -h_ / 2, w_, h_))
                p.restore()
        top_mid = (h["corners"][0] + h["corners"][1]) / 2
        p.drawLine(top_mid, h["rot"])
        p.drawEllipse(h["rot"], HANDLE * k * 0.6, HANDLE * k * 0.6)

    def _paint_guides(self, p: QPainter, k: float):
        d = self.doc
        W, H = d["w"], d["h"]
        if self.guides in ("centro", "tercios", "cuartos"):
            n = {"centro": 2, "tercios": 3, "cuartos": 4}[self.guides]
            p.setPen(QPen(QColor(90, 200, 255, 170), 1.2 * k, Qt.DashLine))
            for i in range(1, n):
                p.drawLine(QPointF(W * i / n, 0), QPointF(W * i / n, H))
                p.drawLine(QPointF(0, H * i / n), QPointF(W, H * i / n))
        elif self.guides == "youtube":                          # lo que tapan YouTube y Shorts encima de la imagen
            zones = ([(0.855, 0.86, 0.985, 0.965, "Duración")] if d.get("format") != "short" else
                     [(0.0, 0.0, 1.0, 0.07, "Barra de arriba"), (0.83, 0.42, 0.99, 0.9, "Botones"),
                      (0.0, 0.8, 0.8, 0.97, "Título y canal")])
            f = p.font()
            f.setPixelSize(max(10, int(H * 0.022)))
            p.setFont(f)
            for x0, y0, x1, y1, name in zones:
                r = QRectF(W * x0, H * y0, W * (x1 - x0), H * (y1 - y0))
                p.setPen(QPen(QColor(255, 80, 80, 200), 1.2 * k, Qt.DashLine))
                p.setBrush(QColor(255, 60, 60, 45))
                p.drawRect(r)
                p.setPen(QColor(255, 200, 200))
                p.drawText(r, Qt.AlignCenter, name)
            p.setBrush(Qt.NoBrush)

    # ------------------------------------------------------------- 🌫 zona borrosa: asas
    def _is_zone(self, lay: dict | None) -> bool:
        return bool(lay) and bool(lay.get("blur_area")) and not lay.get("locked") and not self.warp_mode

    def _zone_press(self, lay: dict, pt: QPointF, h: dict, tol: float) -> bool:
        """🌫 Zona: una esquina (tamaño libre en las dos direcciones) o un lado (solo ancho o solo alto)."""
        if T.warp_of(lay):
            return False
        img, _cw, _ch = self._render(lay)
        w0, h0 = float(img.width()), float(img.height())
        cands = [((pt - c).manhattanLength(), ("corner", i)) for i, c in enumerate(h["corners"])]
        cands += [((pt - c).manhattanLength(), ("side", s)) for s, c in self._side_points(h["corners"]).items()]
        cands = [c for c in cands if c[0] < tol * 1.6]
        if not cands:
            return False
        _dist, (kind, which) = min(cands, key=lambda x: x[0])
        t0 = T.layer_transform(lay, img)
        inv, _ok = t0.inverted()
        loc = [QPointF(0, 0), QPointF(w0, 0), QPointF(w0, h0), QPointF(0, h0)]    # esquinas en su marco: TL, TR, BR, BL
        self._drag = {"mode": "zone", "lay": lay, "kind": kind, "which": which, "t0": t0, "inv": inv,
                      "w0": w0, "h0": h0, "loc": loc}
        return True

    def _zone_move(self, d: dict, pt: QPointF, mods):
        """Estira la zona en SU marco (gira con ella): la esquina o el lado opuesto se queda quieto."""
        q = d["inv"].map(pt)
        w0, h0, which = d["w0"], d["h0"], d["which"]
        if d["kind"] == "corner":
            a = d["loc"][(which + 2) % 4]                           # la esquina opuesta: no se mueve
            ax, ay, qx, qy = a.x(), a.y(), q.x(), q.y()
            if mods & Qt.ShiftModifier:                             # Mayús: proporcional (círculo / cuadrado perfecto)
                dx, dy = abs(qx - ax), abs(qy - ay)
                if dx / max(w0, 1.0) > dy / max(h0, 1.0):
                    dy = dx * h0 / max(w0, 1.0)
                else:
                    dx = dy * w0 / max(h0, 1.0)
                qx = ax + math.copysign(dx, (qx - ax) or 1.0)
                qy = ay + math.copysign(dy, (qy - ay) or 1.0)
            x_lo, x_hi = sorted((ax, qx))
            y_lo, y_hi = sorted((ay, qy))
        elif which in ("l", "r"):                                   # solo el ancho
            x_lo, x_hi = sorted((w0 if which == "l" else 0.0, q.x()))
            y_lo, y_hi = 0.0, h0
        else:                                                       # solo el alto
            x_lo, x_hi = 0.0, w0
            y_lo, y_hi = sorted((h0 if which == "t" else 0.0, q.y()))
        nw, nh = max(8.0, x_hi - x_lo), max(8.0, y_hi - y_lo)
        c = d["t0"].map(QPointF((x_lo + x_hi) / 2, (y_lo + y_hi) / 2))
        d["lay"].update(x=round(c.x(), 1), y=round(c.y(), 1), w=int(round(nw)), h=int(round(nh)))

    # ------------------------------------------------------------- ratón
    def _hit(self, pt: QPointF) -> str:
        for lay in reversed(self.doc["layers"]):
            if lay.get("visible", True) and self._box(lay).containsPoint(pt, Qt.OddEvenFill):
                return lay["id"]
        return ""

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:                       # botón del medio: arrastrar para moverse
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        pt = self.mapToScene(e.position().toPoint())
        if self.tool == "liquify" and e.button() == Qt.LeftButton:
            lay = self.editor.layer(self.sel)
            if lay is not None and not self._box(lay).containsPoint(pt, Qt.OddEvenFill):
                hit = self._hit(pt)
                if hit and hit != self.sel:            # otra capa: se elige (y la herramienta se apaga)
                    self.sel = hit
                    self.selected.emit(hit)
                    self.viewport().update()
                    return
            if lay is None or lay.get("locked"):
                self.sel = self._hit(pt)
                self.selected.emit(self.sel)
                lay = self.editor.layer(self.sel)
                if self.tool != "liquify":
                    return
            if lay is not None and not lay.get("locked"):
                c = self.content_point(lay, pt)
                self._drag = {"mode": "liquify", "lay": lay, "last": c, "pos": c}
                if self.liq_mode != "empujar":
                    self._liq_tick()
                    self._liq_timer.start()
            return
        if self.tool and e.button() == Qt.LeftButton:
            if self.tool in ("box", "blurzone"):
                self._drag = {"mode": "box", "p0": pt, "p1": pt}
            else:
                if self._ink_done:
                    self._ink = None
                self._ink_done = False
                self._stroke = [pt]
                self._drag = {"mode": "brush"}
                self._brush_seg(pt, pt)
                self.viewport().update(self._brush_dirty(pt))
                return
            self.viewport().update()
            return
        if e.button() == Qt.LeftButton and e.modifiers() & Qt.ControlModifier and self._word_press(pt):
            return
        if e.button() == Qt.LeftButton:          # un clic normal deja de elegir palabras
            self.set_words(set())
        lay = self.editor.layer(self.sel)
        if lay is not None and not lay.get("locked") and e.button() == Qt.LeftButton:
            h = self._handles(lay)
            tol = HANDLE * h["k"]
            if self.warp_mode:                   # ◇ coger una esquina y llevarla a donde quieras
                for i, c in enumerate(h["corners"]):
                    if (pt - c).manhattanLength() < tol * 1.8:
                        self._drag = {"mode": "warp", "lay": lay, "i": i}
                        return
            elif (pt - h["rot"]).manhattanLength() < tol * 1.6:
                self._drag = {"mode": "rot", "lay": lay, "c": h["center"], "r0": lay["rotation"],
                              "a0": math.degrees(math.atan2(pt.y() - h["center"].y(), pt.x() - h["center"].x()))}
                return
            if self._is_zone(lay) and self._zone_press(lay, pt, h, tol):     # 🌫 zona: esquinas y lados
                return
            # esquinas (tamaño) y centros de los lados (⬚ recortar): gana el asa más cercana al ratón
            cands = [((pt - c).manhattanLength(), "scale", None)
                     for c in ([] if self.warp_mode else h["corners"]) if (pt - c).manhattanLength() < tol * 1.6]
            if self._crop_allowed(lay):
                cands += [((pt - c).manhattanLength(), "crop", side)
                          for side, c in self._side_points(h["corners"]).items()
                          if (pt - c).manhattanLength() < tol * 1.5]
            if cands:
                _dist, kind, side = min(cands, key=lambda x: x[0])
                if kind == "crop":
                    self._crop_prev = self._crop_start(lay, side)
                    self._drag = {"mode": "crop", "lay": lay}
                else:
                    d0 = math.hypot(pt.x() - h["center"].x(), pt.y() - h["center"].y()) or 1
                    self._size_live = lay["id"]  # ⚡ se ve al vuelo; la imagen buena, al soltar
                    self._drag = {"mode": "scale", "lay": lay, "c": h["center"], "s0": lay["scale"], "d0": d0}
                return
        hit = self._hit(pt)
        if e.modifiers() & Qt.ShiftModifier and e.button() == Qt.LeftButton:   # Mayús+clic: varias a la vez
            if hit:
                if self.sel:
                    self.multi.add(self.sel)
                if hit in self.multi and len(self.multi) > 1:
                    self.multi.discard(hit)
                    hit = next(iter(self.multi))
                else:
                    self.multi.add(hit)
            self.sel = hit
            self.selected.emit(hit)
            self.viewport().update()
            return
        cur = self.editor.layer(self.sel)
        if (hit and self.sel and hit != self.sel and hit not in self.multi and cur is not None
                and cur.get("visible", True) and not cur.get("locked") and e.button() == Qt.LeftButton):
            hit = self.sel        # la capa elegida (en «Capas» o antes) es la que se mueve; otra se elige con doble clic
        if hit not in self.multi:
            self.multi.clear()
        self.sel = hit
        self.selected.emit(hit)
        lay = self.editor.layer(hit)
        if lay is not None and not lay.get("locked") and e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.AltModifier:              # Alt+arrastrar: se arrastra una copia
                lay = self.editor.duplicate_here(lay)
                self.multi.clear()
            group = [lay] if lay["id"] not in self.multi else \
                [l for l in self.doc["layers"] if l["id"] in self.multi and not l.get("locked")]
            others = [self._box(o).boundingRect() for o in self.doc["layers"]
                      if o.get("visible", True) and o not in group]
            bb = self._box(lay).boundingRect()
            for g in group[1:]:
                bb = bb.united(self._box(g).boundingRect())
            self._drag = {"mode": "move", "lay": lay, "p0": pt, "x0": lay["x"], "y0": lay["y"],
                          "group": [(g, g["x"], g["y"]) for g in group], "bb": bb, "others": others,
                          "word": self.word_at(lay, pt) if e.modifiers() & Qt.ControlModifier else None}
        self.viewport().update()

    def _word_press(self, pt: QPointF) -> bool:
        """Con alguna palabra ya elegida, Ctrl + clic añade otra (o la quita) y arrastrando va añadiendo las que toque.
        Sin ninguna elegida, Ctrl sigue siendo «mover sin que se pegue» (y un Ctrl + clic sin mover elige la palabra)."""
        if self.tool or not self.active_words():
            return False
        lay = self.editor.layer(self.sel)
        palabra = self.word_at(lay, pt) if lay is not None and not lay.get("locked") else None
        if palabra is None:                      # no era el texto elegido: ¿otro texto?
            otra = self.editor.layer(self._hit(pt))
            if otra is None or otra.get("locked"):
                return False
            palabra = self.word_at(otra, pt)
            if palabra is None:
                return False
            lay = otra
            self.multi.clear()
            self.sel = lay["id"]
            self.selected.emit(lay["id"])
        ahora = set(self.active_words(lay))
        ahora ^= {palabra}
        self.set_words(ahora, lay)
        self._drag = {"mode": "words", "lay": lay}
        return True

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            delta = e.position() - self._pan
            self._pan = e.position()
            k = self.transform().m11() or 1.0
            self.centerOn(self.mapToScene(self.viewport().rect().center()) - delta / k)
            return
        d = self._drag
        pt = self.mapToScene(e.position().toPoint())
        if self.tool in ("erase", "restore"):
            antes, self._hover = self._hover, pt
            previo = None
            if d is not None and self._stroke:
                previo = self._stroke[-1]
                self._stroke.append(pt)
                self._brush_seg(previo, pt)
            self.viewport().update(self._brush_dirty(antes, previo, pt))    # ⚡ solo la zona tocada
            return
        if self.tool == "liquify":
            self._hover = pt
            if d is not None and d.get("mode") == "liquify":
                c = self.content_point(d["lay"], pt)
                if self.liq_mode == "empujar":
                    last = d["last"]
                    mx, my = c["fx"] - last["fx"], c["fy"] - last["fy"]
                    dist = math.hypot(mx * c["aspect"], my)
                    steps = max(1, min(40, math.ceil(dist / max(c["r"] * 0.2, 1e-6))))
                    # (un arrastre rápido, en pasos pequeños: no se desgarra; todos los pasos en una sola pasada)
                    self.editor.liquify_dabs(d["lay"], [
                        (dict(c, fx=last["fx"] + mx * i / steps, fy=last["fy"] + my * i / steps),
                         (mx / steps, my / steps)) for i in range(1, steps + 1)])
                    d["last"] = c
                d["pos"] = c
            self.viewport().update()
            return
        if self.tool in ("box", "blurzone") and d is not None:
            d["p1"] = pt
            if self.tool == "blurzone" and e.modifiers() & Qt.ShiftModifier:   # Mayús: círculo / cuadrado perfecto
                dx, dy = pt.x() - d["p0"].x(), pt.y() - d["p0"].y()
                s = max(abs(dx), abs(dy))
                d["p1"] = QPointF(d["p0"].x() + math.copysign(s, dx or 1.0), d["p0"].y() + math.copysign(s, dy or 1.0))
            self.viewport().update()
            return
        if d is None:
            self._hover_cursor(pt)
            return
        if d["mode"] == "words":
            palabra = self.word_at(d["lay"], pt)
            if palabra is not None and palabra not in self.active_words(d["lay"]):
                self.set_words(self.active_words(d["lay"]) | {palabra}, d["lay"])
            return
        lay = d["lay"]
        doc = self.doc
        self._guides = []
        if d["mode"] == "zone":                          # 🌫 zona: una esquina o un lado, en su marco
            self._zone_move(d, pt, e.modifiers())
            self.viewport().update()
            self.editor.on_live_change()
            return
        if d["mode"] == "crop":                          # (solo se recalcula el recuadro: fluido)
            self._crop_move(self._crop_prev, pt)
            self.viewport().update()
            return
        if d["mode"] == "move":
            dx, dy = pt.x() - d["p0"].x(), pt.y() - d["p0"].y()
            if not e.modifiers() & Qt.ControlModifier:     # guías inteligentes (Ctrl = moverla sin que se pegue)
                snap = 8 / max(self.transform().m11(), 1e-6)
                bb, W, H = d["bb"], doc["w"], doc["h"]
                tx = [0.0, W / 3, W / 2, W * 2 / 3, W] + [v for r in d["others"]
                                                          for v in (r.left(), r.center().x(), r.right())]
                ty = [0.0, H / 3, H / 2, H * 2 / 3, H] + [v for r in d["others"]
                                                          for v in (r.top(), r.center().y(), r.bottom())]
                for axis, edges, targets in (("v", (bb.left(), bb.center().x(), bb.right()), tx),
                                             ("h", (bb.top(), bb.center().y(), bb.bottom()), ty)):
                    off = dx if axis == "v" else dy
                    best = None
                    for e_ in edges:
                        for t in targets:
                            gap = t - (e_ + off)
                            if abs(gap) < snap and (best is None or abs(gap) < abs(best[0])):
                                best = (gap, t)
                    if best is not None:
                        if axis == "v":
                            dx += best[0]
                        else:
                            dy += best[0]
                        self._guides.append((axis, best[1]))
            for g, gx, gy in d.get("group") or [(lay, d["x0"], d["y0"])]:
                g["x"], g["y"] = round(gx + dx, 1), round(gy + dy, 1)
        elif d["mode"] == "warp":
            # dónde cae el ratón en la capa SIN deformar → cuánto se separa esa esquina de su sitio
            img, cw, ch = T.render_layer(lay)
            inv, ok = T.layer_transform(lay, img, warp=False).inverted()
            if ok:
                q = inv.map(pt)
                src = T.content_quad(lay, img).at(d["i"])
                w = T.warp_of(lay) or [[0.0, 0.0] for _ in range(4)]
                w[d["i"]] = [round((q.x() - src.x()) / max(1.0, cw), 4), round((q.y() - src.y()) / max(1.0, ch), 4)]
                lay["warp"] = w
        elif d["mode"] == "scale":
            dist = math.hypot(pt.x() - d["c"].x(), pt.y() - d["c"].y())
            lay["scale"] = round(max(0.02, d["s0"] * dist / d["d0"]), 4)
        elif d["mode"] == "rot":
            a = math.degrees(math.atan2(pt.y() - d["c"].y(), pt.x() - d["c"].x()))
            r = d["r0"] + a - d["a0"]
            if e.modifiers() & Qt.ShiftModifier:
                r = round(r / 15) * 15
            elif abs(((r + 180) % 360) - 180) < 2:
                r = 0.0
            lay["rotation"] = round(r, 1)
        self.viewport().update()
        self.editor.on_live_change()

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() == Qt.MiddleButton:
            self._pan = None
            self.setCursor(Qt.BlankCursor if self.tool in ("liquify", "erase", "restore") else Qt.ArrowCursor)
            return
        if self.tool == "liquify" and self._drag is not None and self._drag.get("mode") == "liquify":
            self._liq_timer.stop()
            lay = self._drag.get("lay")
            self._drag = None
            if lay is not None:
                self._finish_liquify(lay)
            self.editor.liquify_done()
            return
        if self.tool in ("box", "blurzone") and self._drag is not None:
            r = QRectF(self._drag["p0"], self._drag["p1"]).normalized()
            self._drag = None
            self.viewport().update()
            if self.tool == "blurzone":
                self.editor.blur_zone_done(r)
            else:
                self.editor.cutout_box(r)
            return
        if self.tool in ("erase", "restore") and self._drag is not None:
            self._drag = None
            pts, self._stroke = self._stroke, []
            self.editor.brush_stroke(pts, self.tool == "restore")
            self.viewport().update()
            return
        if self._drag is not None and self._drag.get("mode") == "crop":
            lay, cp = self._drag["lay"], self._crop_prev
            self._drag = None
            changed = cp is not None and cp["crop"] != cp["c0"]
            if changed:
                self._crop_end(lay, cp)              # (aquí, y solo aquí, se procesa la imagen recortada)
            self._crop_prev = None
            if changed:
                self.committed.emit("Recortar")
            self.viewport().update()
            return
        if self._drag is not None:
            d = self._drag
            era_palabras = d.get("mode") == "words"
            self._drag = None
            if d.get("word") is not None and (d["lay"]["x"], d["lay"]["y"]) == (d["x0"], d["y0"]):
                self.set_words({d["word"]}, d["lay"])     # Ctrl + clic sin mover: esa palabra
            self._guides = []
            self._size_live = ""
            if not era_palabras:
                self.committed.emit("Mover / tamaño / giro")
            self.viewport().update()

    def _hover_cursor(self, pt: QPointF):
        """Encima de un lado de lo elegido: la flecha de recortar."""
        if self.tool:
            return
        lay = self.editor.layer(self.sel)
        cur = Qt.ArrowCursor
        if (self._crop_allowed(lay) or self._is_zone(lay)) and lay.get("visible", True):
            h = self._handles(lay)
            for side, c in self._side_points(h["corners"]).items():
                if (pt - c).manhattanLength() < HANDLE * h["k"] * 1.5:
                    ang = (float(lay.get("rotation", 0)) + (90 if side in "tb" else 0)) % 180
                    cur = Qt.SizeHorCursor if ang < 45 or ang > 135 else Qt.SizeVerCursor
                    break
        if self.cursor().shape() != cur:
            self.setCursor(cur)

    # ------------------------------------------------------------- soltar imágenes
    def _acepta(self, mime) -> bool:
        from .common import MEDIA_MIME
        return mime.hasUrls() or mime.hasImage() or mime.hasFormat(MEDIA_MIME)

    def dragEnterEvent(self, e):
        if self._acepta(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._acepta(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if self._acepta(e.mimeData()):
            e.acceptProposedAction()
            self.editor.drop_on_canvas(e.mimeData(), self.mapToScene(e.position().toPoint()))
        else:
            e.ignore()

    def content_point(self, lay: dict, pt: QPointF) -> dict:
        """Punto del lienzo → fracción del contenido de la capa (0–1) y radio del pincel (fracción del alto)."""
        img, cw, ch = self._render(lay)
        inv, _ok = T.layer_transform(lay, img).inverted()
        q = inv.map(pt)
        cw, ch = max(1.0, cw), max(1.0, ch)
        return {"fx": (q.x() - (img.width() - cw) / 2) / cw, "fy": (q.y() - (img.height() - ch) / 2) / ch,
                "r": self.brush / max(T.layer_scale(lay, img) * ch, 1e-6), "aspect": cw / ch}

    def _liq_tick(self):
        d = self._drag
        if d and d.get("mode") == "liquify" and self.liq_mode != "empujar":
            self.editor.liquify_dab(d["lay"], d["pos"], (0.0, 0.0))

    def keyPressEvent(self, e):
        lay = self.editor.layer(self.sel)
        if lay is None:
            return super().keyPressEvent(e)
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if e.key() in moves and not lay.get("locked"):
            dx, dy = moves[e.key()]
            for g in self.editor.selected_layers():
                g["x"] += dx
                g["y"] += dy
            self.viewport().update()
            self.committed.emit("Mover")
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.editor.delete_layer()
        else:
            super().keyPressEvent(e)


class _PngView(QWidget):
    """Google Imágenes (solo PNG con fondo transparente) dentro del taller. Clic derecho en una imagen →
    «Usar en la miniatura». El perfil se guarda en los datos de Reclaimer (cookies de Google: se acepta una vez)."""
    use_image = Signal(str, str)        # (imagen, la pequeña por si la grande no se deja bajar)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from ..core.paths import app_data_dir
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self._profile = QWebEngineProfile("png", self)
        root = os.path.join(str(app_data_dir()), "navegador_png")
        self._profile.setPersistentStoragePath(root)
        self._profile.setCachePath(os.path.join(root, "cache"))
        self._profile.downloadRequested.connect(self._on_download)
        self._dl_cb = None
        self.bg = False                     # (modo Fondo: el menú dice «Usar de fondo»)
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(self._profile, self.view))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.view)

    def load(self, url):
        self.view.load(url)

    _BIG_JS = ("JSON.stringify(Array.from(document.images).filter(i => i.src.startsWith('http') && "
               "!i.src.includes('gstatic.com') && i.naturalWidth > 200).map(i => i.src))")

    def _menu(self, pos):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu
        req = self.view.lastContextMenuRequest()
        url = req.mediaUrl().toString() if req is not None else ""
        m = QMenu(self)
        a = QAction("🖼 Usar de fondo" if self.bg else "🖼 Usar en la miniatura", m)
        a.setEnabled(bool(url))
        a.triggered.connect(lambda: self._use(url, pos))
        m.addAction(a)
        m.addSeparator()
        m.addAction("← Atrás", self.view.back)
        m.exec(self.view.mapToGlobal(pos))

    def download(self, url: str, done):
        """Baja la imagen con el navegador (con sus cookies y su «de dónde vienes»): las webs que rechazan a un
        programa sí se la dan. done(ruta) al terminar; done("") si falla."""
        import tempfile
        from PySide6.QtCore import QUrl
        from ..core.paths import cache_dir
        self._dl_cb = done
        self._dl_dir = tempfile.mkdtemp(prefix="nav_", dir=str(cache_dir("png_web")))
        self._dl_token = getattr(self, "_dl_token", 0) + 1
        tok = self._dl_token
        self.view.page().download(QUrl(url), "imagen")
        QTimer.singleShot(30000, lambda: self._dl_token == tok and self._dl_done(""))   # (si nunca llega)

    def _on_download(self, req):
        if self._dl_cb is None:
            req.cancel()
            return
        req.setDownloadDirectory(self._dl_dir)
        req.setDownloadFileName("imagen" + os.path.splitext(req.downloadFileName())[1])

        def changed(_state=None):
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest as D
            st = req.state()
            if st == D.DownloadState.DownloadCompleted:
                self._dl_done(os.path.join(req.downloadDirectory(), req.downloadFileName()))
            elif st in (D.DownloadState.DownloadCancelled, D.DownloadState.DownloadInterrupted):
                self._dl_done("")
        req.stateChanged.connect(changed)
        req.accept()
        changed()

    def _dl_done(self, path: str):
        cb, self._dl_cb = self._dl_cb, None
        if cb is not None:
            cb(path)

    def _use(self, url: str, pos):
        """Si es la miniatura pequeña de Google, se abre (clic) y se coge la imagen grande de su página."""
        if url.startswith("http") and "gstatic.com" not in url:
            self.use_image.emit(url, "")
            return
        import json

        def before(r):
            seen = set(json.loads(r or "[]"))
            from PySide6.QtCore import QPoint
            from PySide6.QtTest import QTest
            QTest.mouseClick(self.view.focusProxy() or self.view, Qt.LeftButton, Qt.NoModifier, QPoint(pos))
            self._poll(seen, url, time.time())
        self.view.page().runJavaScript(self._BIG_JS, 0, before)

    def _poll(self, seen: set, small: str, t0: float):
        import json

        def got(r):
            new = [u for u in json.loads(r or "[]") if u not in seen]
            if new:
                self.use_image.emit(new[0], small)
            elif time.time() - t0 > 3.5:
                self.use_image.emit(small, "")          # (no salió la grande: la pequeña)
            else:
                QTimer.singleShot(250, lambda: self._poll(seen, small, t0))
        try:
            self.view.page().runJavaScript(self._BIG_JS, 0, got)
        except RuntimeError:                       # (se cerró el taller mientras tanto)
            pass


class ThumbnailEditor(QMainWindow):
    closed = Signal()               # se cerró (o saliste de la página): la ventana principal vuelve al editor

    def __init__(self, win, fmt: str | None = None):
        super().__init__(win)
        self.win = win
        self.ctrl = win.ctrl
        self.setWindowTitle("🖼 Miniatura — Reclaimer")
        self.resize(1500, 900)
        p = self.ctrl.project
        fmt = fmt or ("short" if p.format in ("short", "edit") else "youtube")
        self.doc = copy.deepcopy(p.thumbnails.get(fmt)) if p.thumbnails.get(fmt) else T.new_doc(fmt)
        self._brush_q: list = []          # 🖌 trazos por aplicar (en segundo plano y en orden)
        self._brush_job = None
        self._hist_rows: list = []        # filas de colores usados del panel (se actualizan sin rehacer el panel)
        self.history: list[str] = [json.dumps(self.doc)]
        self.pos = 0
        self._last_label, self._last_t = "", 0.0
        self._loading = False
        self.reco: list = []          # fotogramas recomendados (IA)
        self.job = None
        self._cutouts: dict = {}          # fotograma → máscara del personaje (para no recortar dos veces)

        self.canvas = Canvas(self)
        self.canvas.setProperty("own_menu", True)          # (clic derecho: el menú de la capa, con la ayuda al final)
        self.canvas.selected.connect(self._on_select)
        self.canvas.committed.connect(self.commit)
        self.text_bar = TextBar(self)                       # barra flotante del texto elegido (thumb_text_bar.py)
        self._build_toolbar()
        left = self._build_left()
        self.props = QWidget()
        self.props_lay = QVBoxLayout(self.props)
        self.props_lay.setAlignment(Qt.AlignTop)
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setWidget(self.props)
        right.setMinimumWidth(320)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self._build_layers_panel())
        split.addWidget(self.canvas)
        split.addWidget(right)
        split.setSizes([360, 200, 820, 340])
        split.setStretchFactor(2, 1)
        self._split = split
        self.setCentralWidget(split)
        self.statusBar().showMessage("Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = girar "
                                     "(Mayús: de 15 en 15) · Supr = borrar · Ctrl+D = duplicar")
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+D", self.duplicate)):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Escape"), self.canvas, activated=self.select_tool, context=Qt.WidgetShortcut)
        for w in (self.canvas, self.layers):
            QShortcut(QKeySequence.SelectAll, w, activated=self.select_all, context=Qt.WidgetShortcut)   # Ctrl+A
            for seq, d in (("Ctrl+PgUp", 1), ("Ctrl+PgDown", -1), ("Ctrl+Shift+PgUp", 999), ("Ctrl+Shift+PgDown", -999)):
                QShortcut(QKeySequence(seq), w, activated=lambda d=d: self.arrange(d), context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+0"), self.canvas, activated=lambda: self.canvas.set_zoom(1.0),
                  context=Qt.WidgetShortcut)
        for w in (self.canvas, self.layers):
            QShortcut(QKeySequence.Copy, w, activated=self.copy_layer, context=Qt.WidgetShortcut)
            QShortcut(QKeySequence.Cut, w, activated=self.cut_layer, context=Qt.WidgetShortcut)   # Ctrl+X
            QShortcut(QKeySequence.Paste, w, activated=self.paste, context=Qt.WidgetShortcut)
        set_help(self, "miniatura")
        self._render_soon = QTimer(self)
        self._render_soon.setSingleShot(True)
        self._render_soon.setInterval(80)
        self._render_soon.timeout.connect(self.canvas.viewport().update)
        self._mat_icons: dict = {}               # ruta → (fecha, icono): rehacer la lista no vuelve a leer las imágenes
        self._mat_soon = QTimer(self)            # «Material» al día: lo que importes en Medios aparece solo
        self._mat_soon.setSingleShot(True)
        self._mat_soon.setInterval(250)
        self._mat_soon.timeout.connect(self._fill_material)
        for sig in ("media_changed", "project_replaced"):
            if hasattr(self.ctrl, sig):
                getattr(self.ctrl, sig).connect(self._mat_soon.start)
        self.refresh_all()
        if any(c.media_id for c in self.ctrl.project.clips.values()):   # si hay video: buscar ya
            QTimer.singleShot(300, self.find_best_frames)

    # ----------------------------------------------------------- recomendados
    def _material_sources(self) -> list[dict]:
        """Los trozos de video usados en la línea de tiempo (si no hay, toda la biblioteca)."""
        p = self.ctrl.project
        used: dict[str, list] = {}
        for c in p.clips.values():
            m = p.media_of(c)
            tr = p.track(c.track_id)
            if m is not None and m.kind == KIND_VIDEO and tr is not None and tr.kind == "video" \
                    and m.id not in self.ctrl.missing:
                used.setdefault(m.id, []).append((c.source_in, c.source_in + c.src_len))
        if not used:
            used = {m.id: [] for m in p.media.values() if m.kind == KIND_VIDEO and m.id not in self.ctrl.missing}
        out = []
        for mid, rs in used.items():
            m = p.media[mid]
            rs.sort()
            merged = []
            for a, b in rs:
                if merged and a <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            out.append({"media_id": mid, "path": m.path, "kind": "video", "duration": m.duration,
                        "ranges": [tuple(x) for x in merged]})
        return out

    def find_best_frames(self):
        if self.job is not None:
            return
        src = self._material_sources()
        if not src:
            self.reco_status.setText("Importa los clips de tu video para que la IA busque los mejores fotogramas.")
            return
        p = self.ctrl.project
        topic = " · ".join([p.name] + list(dict.fromkeys(m.label.lower() for m in p.markers if m.kind == "topic")))
        from ..ai import thumb_frames
        from .jobs import BackgroundJob
        self.reco_btn.setEnabled(False)
        self.job = BackgroundJob(lambda prog, canc: thumb_frames.find(src, topic, 12, prog, canc), self)
        self.job.progress.connect(lambda _f, t: self.reco_status.setText(t))
        self.job.done.connect(self._reco_done)
        self.job.failed.connect(lambda msg: (self._reco_end(), self.reco_status.setText("✗ " + msg)))
        self.job.start()

    def _reco_end(self):
        self.job = None
        self.reco_btn.setEnabled(True)

    def _reco_done(self, res):
        self._reco_end()
        self.reco = res
        self.reco_status.setText(f"✨ {len(res)} fotogramas recomendados (arriba). Pasa el ratón para ver por qué."
                                 if res else "No encontré fotogramas claros (¿todo es muy oscuro o borroso?).")
        self._fill_material()

    def showEvent(self, e):
        super().showEvent(e)
        if hasattr(self, "_mat_soon"):           # (al volver a la página: lo importado mientras tanto)
            self._mat_soon.start()

    def closeEvent(self, e):
        if hasattr(self, "_mat_soon"):
            self._mat_soon.stop()
            for sig in ("media_changed", "project_replaced"):
                try:
                    getattr(self.ctrl, sig).disconnect(self._mat_soon.start)
                except (AttributeError, RuntimeError, TypeError):
                    pass
        if self.job is not None:
            self.job.cancel()
            self.job.wait(3000)
        t0 = time.time()
        while self.brush_busy() and time.time() - t0 < 6:         # (los trazos que falten: que no se pierdan)
            QApplication.processEvents()
            time.sleep(0.01)
        self.canvas.wait_renders()
        self._learn()
        self._save()
        super().closeEvent(e)
        if not getattr(self, "_gone", False):
            self.closed.emit()                     # (en la página Miniatura: el editor vuelve a su sitio)

    # ----------------------------------------------------------- barra
    def _build_toolbar(self):
        tb = QToolBar("Miniatura")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.fmt = QComboBox()
        self.fmt.addItem("▭  YouTube (1280×720)", "youtube")
        self.fmt.addItem("▯  Shorts (1080×1920)", "short")
        self.fmt.setCurrentIndex(self.fmt.findData(self.doc["format"]))
        self.fmt.currentIndexChanged.connect(self._change_format)
        tb.addWidget(self.fmt)
        tb.addSeparator()
        for text, tip, fn in (("↶", "Deshacer (Ctrl+Z)", self.undo), ("↷", "Rehacer (Ctrl+Y)", self.redo),
                              ("⧉ Duplicar", "Duplicar lo elegido (Ctrl+D)", self.duplicate),
                              ("⇡ Adelante", "Poner delante", lambda: self.arrange(1)),
                              ("⇣ Atrás", "Poner detrás", lambda: self.arrange(-1)),
                              ("🗑 Eliminar", "Eliminar lo seleccionado (Supr)", self.delete_layer),
                              ("Eliminar todo", "Quitar todas las capas (las bloqueadas se quedan). Ctrl+Z las recupera",
                               self.delete_all)):
            a = tb.addAction(text, fn)
            a.setToolTip(tip)
        tb.addSeparator()
        al = QComboBox()
        al.addItem("Alinear…")
        for label, key in (("Centrar en horizontal", "ch"), ("Centrar en vertical", "cv"), ("A la izquierda", "l"),
                           ("A la derecha", "r"), ("Arriba", "t"), ("Abajo", "b")):
            al.addItem(label, key)
        al.activated.connect(lambda i: (self.align(al.itemData(i)), al.setCurrentIndex(0)) if i else None)
        tb.addWidget(al)
        tb.addSeparator()
        self.act_select = tb.addAction("↖ Seleccionar", self.select_tool)   # el ratón normal (elegir y mover)
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)
        self.act_select.setToolTip("Seleccionar (Esc): el ratón normal para elegir, mover, cambiar el tamaño y girar")
        self.act_warp = tb.addAction("◇ Deformar", self.toggle_warp)       # perspectiva libre, como en Photoshop
        self.act_warp.setCheckable(True)
        self.act_warp.setToolTip("Deformar: arrastra cada esquina de lo elegido a donde quieras (perspectiva libre, "
                                 "como «Distorsionar» en Photoshop o «Corner Pin» en Resolve).")
        self.act_unwarp = tb.addAction("↺", self.reset_warp)
        self.act_unwarp.setToolTip("Quitar la deformación de lo elegido")
        self.act_liq = tb.addAction("≈ Licuar", self._liq_button)              # como «Licuar» de Photoshop
        self.act_liq.setCheckable(True)
        self.act_liq.setToolTip("Licuar: pinta sobre lo elegido para inflar, encoger o empujar (ojos saltones, "
                                "bocota…). Modos, tamaño, fuerza y caras graciosas de un clic en el panel derecho.")
        self.act_stretch = tb.addAction("✋ Estirar", self.toggle_stretch)     # «Deformación hacia delante» de PS
        self.act_stretch.setCheckable(True)
        self.act_stretch.setToolTip("Estirar: agarra lo que hay dentro del círculo y llévalo con el ratón; lo de "
                                    "alrededor se estira con ello. El tamaño del círculo, en el panel derecho.")
        tb.addSeparator()
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMenu, QToolButton
        self.blur_btn = QToolButton()                       # 🌫 zona borrosa: círculo o cuadrado, arrastrando
        self.blur_btn.setText("🌫 Borroso ▾")
        self.blur_btn.setToolTip("Zona borrosa: elige círculo o cuadrado, arrástralo sobre el lienzo y estíralo como "
                                 "quieras. Desenfoca lo que hay debajo (para tapar o difuminar una parte).")
        self.blur_btn.setPopupMode(QToolButton.InstantPopup)
        blur_menu = QMenu(self.blur_btn)
        blur_menu.addAction("◯ Círculo", lambda: self.start_blur_zone("ellipse"))
        blur_menu.addAction("▢ Cuadrado", lambda: self.start_blur_zone("rect"))
        self.blur_btn.setMenu(blur_menu)
        tb.addWidget(self.blur_btn)
        self.tpl_btn = QToolButton()
        self.tpl_btn.setText("📐 Plantillas")
        self.tpl_btn.setToolTip("Guarda una miniatura como plantilla y reutiliza su composición en otra")
        self.tpl_btn.setPopupMode(QToolButton.InstantPopup)
        tpl_menu = QMenu(self.tpl_btn)
        tpl_menu.aboutToShow.connect(lambda: self._templates_menu(tpl_menu))
        self.tpl_btn.setMenu(tpl_menu)
        tb.addWidget(self.tpl_btn)
        self.act_short = tb.addAction("📱 Pasar a Short", self.to_short)
        self.act_short.setToolTip("Crea la miniatura vertical del Short a partir de esta de YouTube (luego la ajustas)")
        self.ab_btn = QToolButton()
        self.ab_btn.setText("⚖ Comparar A/B")
        self.ab_btn.setToolTip("Guarda dos versiones de la miniatura (A y B) y compáralas lado a lado para quedarte "
                               "con la mejor")
        self.ab_btn.setPopupMode(QToolButton.InstantPopup)
        ab_menu = QMenu(self.ab_btn)
        ab_menu.addAction("📸 Guardar como A", lambda: self.ab_save("A"))
        ab_menu.addAction("📸 Guardar como B", lambda: self.ab_save("B"))
        ab_menu.addSeparator()
        self.act_ab_side = ab_menu.addAction("⚖ Ver A y B lado a lado…", self.ab_compare)
        ab_menu.addSeparator()
        self.act_ab_clear = ab_menu.addAction("Borrar A y B", self.ab_clear)
        ab_menu.aboutToShow.connect(self._ab_update)
        self.ab_btn.setMenu(ab_menu)
        self._ab_update()
        tb.addWidget(self.ab_btn)
        tb.addSeparator()
        self.guides_combo = QComboBox()
        for label, key in (("▦ Sin guías", ""), ("▦ Centro", "centro"), ("▦ Tercios", "tercios"),
                           ("▦ Cuartos", "cuartos"), ("▦ Lo que tapa YouTube", "youtube")):
            self.guides_combo.addItem(label, key)
        self.guides_combo.setToolTip("Guías encima de la miniatura para colocar las cosas: el centro, tercios (regla "
                                     "de los tercios), cuartos, o lo que tapa YouTube (la duración en los videos; "
                                     "los botones y el título en los Shorts). No salen al exportar.")
        self.guides_combo.currentIndexChanged.connect(self._guides_changed)
        tb.addWidget(self.guides_combo)
        self.act_zoom_out = tb.addAction("−", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25))
        self.act_zoom_out.setToolTip("Alejar (Ctrl + rueda hacia atrás): para ver lo que se sale del encuadre")
        self.act_zoom_fit = tb.addAction("100 %", lambda: self.canvas.set_zoom(1.0))
        self.act_zoom_fit.setToolTip("Encajar la miniatura entera (Ctrl+0)")
        self.act_zoom_in = tb.addAction("+", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25))
        self.act_zoom_in.setToolTip("Acercar (Ctrl + rueda hacia delante). Botón del medio del ratón: moverse")
        self.canvas.zoomChanged.connect(lambda z: self.act_zoom_fit.setText(f"{round(z * 100)} %"))
        # con ≈ Licuar / ✋ Estirar, al cambiar el zoom cambia la resolución de la vista rápida: se prepara otra vez
        self.canvas.zoomChanged.connect(lambda _z: self._warm_liquify() if self.canvas.tool == "liquify" else None)
        g0 = QSettings("EditorIA", "EditorIA").value("miniatura/guias", "", type=str)
        self.guides_combo.setCurrentIndex(max(0, self.guides_combo.findData(g0)))
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        for text, tip, fn in (("👁 Vista previa", "Cómo se verá en YouTube a tamaño real (¿se entiende en pequeño?)",
                               self.preview),
                              ("⚕ Analizar", "La IA revisa legibilidad, contraste, tamaño de la cara, cantidad de texto…",
                               self.analyze),
                              ("✨ Mejorar", "Ajustes suaves y razonables (sin saturar ni llenar de efectos)",
                               self.improve)):
            a = tb.addAction(text, fn)
            a.setToolTip(tip)
        tb.addSeparator()
        a = tb.addAction("⬇  Exportar…", self.export)
        a.setToolTip("Guarda la imagen (JPG por debajo de 2 MB, el límite de YouTube, o PNG)")

    # ----------------------------------------------------------- izquierda
    def _build_left(self) -> QWidget:
        tabs = QTabWidget()
        # Material
        mat = QWidget()
        ml = QVBoxLayout(mat)
        row = QHBoxLayout()
        b1 = QPushButton("📷 Fotograma del visor")
        b1.setToolTip("Añade lo que se ve ahora en el visor, a resolución completa")
        b1.clicked.connect(self.add_viewer_frame)
        b2 = QPushButton("📁 Desde archivo…")
        b2.clicked.connect(self.add_from_file)
        row.addWidget(b1)
        row.addWidget(b2)
        ml.addLayout(row)
        self.reco_btn = QPushButton("✨ Buscar los mejores fotogramas de mi video")
        self.reco_btn.setToolTip("La IA revisa los clips de tu video y propone los fotogramas con más posibilidades: "
                                 "caras grandes, personajes, nitidez, contraste y relación con el tema.")
        self.reco_btn.clicked.connect(self.find_best_frames)
        ml.addWidget(self.reco_btn)
        self.reco_status = QLabel("")
        self.reco_status.setObjectName("dim")
        self.reco_status.setWordWrap(True)
        ml.addWidget(self.reco_status)
        tip = QLabel("Clic = añadir encima · doble clic = de fondo · arrastra aquí tus imágenes o carpetas")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        ml.addWidget(tip)
        self.btn_folders = QPushButton("📁 Carpetas")
        self.btn_folders.setCheckable(True)
        self.btn_folders.setToolTip("Tus carpetas de material (Fuego, Ojos, Agua…) y las tuyas del disco, en orden de "
                                    "abecedario. Vuelve a pulsar para ver las imágenes sueltas")
        self.btn_folders.toggled.connect(self._show_folders)
        ml.addWidget(self.btn_folders)
        self.material = _MaterialList()
        self.material.setDragEnabled(True)
        self.material.setAcceptDrops(True)
        self.material.setDragDropMode(QListWidget.DragDrop)
        self.material.setDefaultDropAction(Qt.CopyAction)
        self.material.dropped.connect(self.add_to_material)
        self.material.setViewMode(QListView.IconMode)
        self.material.setIconSize(QSize(140, 80))
        self.material.setGridSize(QSize(150, 110))
        self.material.setResizeMode(QListView.Adjust)
        self.material.setMovement(QListView.Static)
        self.material.setWordWrap(True)
        self.material.itemClicked.connect(self._material_click)
        self.material.itemDoubleClicked.connect(lambda it: self.add_image(it.data(Qt.UserRole), "Fondo", fill=True))
        self.material.setProperty("own_menu", True)          # clic derecho: quitar / a la Papelera (+ «¿Qué hace esto?»)
        self.material.setContextMenuPolicy(Qt.CustomContextMenu)
        self.material.customContextMenuRequested.connect(self._material_menu)
        QShortcut(QKeySequence.Delete, self.material, lambda: self._material_quitar(self.material.currentItem()),
                  context=Qt.WidgetShortcut)
        from PySide6.QtWidgets import QStackedWidget
        from .material_folders import FolderBrowser
        self.mat_stack = QStackedWidget()
        self.mat_stack.addWidget(self.material)
        self.folders = None                      # (la vista de carpetas se crea la primera vez que se abre)
        ml.addWidget(self.mat_stack, 1)
        self._FolderBrowser = FolderBrowser
        tabs.addTab(mat, "Material")
        tabs.insertTab(0, self._build_proposals_tab(), "✨ Propuestas")
        tabs.insertTab(2, self._build_png_tab(), "🔎 PNG")
        # Texto
        txt = QWidget()
        tl = QVBoxLayout(txt)
        # 🔥 Mi estilo (el de las miniaturas del usuario): Anton blanco y *rojo* con borde y resplandor, el recuadro
        # del logo y el marco rojo
        mine = QLabel("Mi estilo")
        mine.setObjectName("sectionhead")
        tl.addWidget(mine)
        for label, tip, fn in (
                ("🔥 Texto de impacto", "2–3 palabras enormes en Anton, blancas con la *palabra clave* en rojo, borde "
                                       "negro y resplandor rojo. Escribe *entre asteriscos* lo que va en rojo.",
                 lambda: self.add_text("ESTO ES *MALO*", "impact")),
                ("▭ Recuadro del logo", "Recuadro negro con borde rojo arriba: pon encima el logo del juego.",
                 self.add_logo_box),
                ("🟥 Marco rojo a lo elegido", "Borde rojo y sombra a la imagen elegida (un producto, un personaje "
                                              "recortado…).", self.red_frame)):
            b = QPushButton(label)
            b.setMinimumHeight(40)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tl.addWidget(b)
        other = QLabel("Más textos")
        other.setObjectName("sectionhead")
        tl.addWidget(other)
        for label, preset, sample in (("Título grande", "title", "TÍTULO"), ("Subtítulo", "subtitle", "Subtítulo"),
                                      ("Etiqueta con caja", "label", "ETIQUETA")):
            b = QPushButton(label)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, pr=preset, s=sample: self.add_text(s, pr))
            tl.addWidget(b)
        tl.addStretch()
        tabs.addTab(txt, "Texto")
        # Elementos
        el = QWidget()
        eg = QGridLayout(el)
        for k, (label, fn) in enumerate((("▭ Rectángulo", lambda: self.add_shape("rect")),
                                         ("◯ Círculo", lambda: self.add_shape("ellipse")),
                                         ("➜ Flecha", lambda: self.add_shape("arrow")),
                                         ("▤ Degradado oscuro", self.add_dark_gradient))):
            b = QPushButton(label)
            b.setMinimumHeight(44)
            b.clicked.connect(fn)
            eg.addWidget(b, k // 2, k % 2)
        eg.setRowStretch(3, 1)
        tabs.addTab(el, "Formas")
        # Fondo
        bgw = QWidget()
        bl = QFormLayout(bgw)
        self.bg_type = QComboBox()
        self.bg_type.addItem("Color", "color")
        self.bg_type.addItem("Degradado", "gradient")
        self.bg_type.currentIndexChanged.connect(self._bg_changed)
        self.bg_c1 = _ColorButton("#101014")
        self.bg_c2 = _ColorButton("#000000")
        self.bg_c1.changed.connect(lambda _c: self._bg_changed())
        self.bg_c2.changed.connect(lambda _c: self._bg_changed())
        self.bg_angle = QSpinBox()
        self.bg_angle.setRange(0, 360)
        self.bg_angle.setSuffix("°")
        self.bg_angle.valueChanged.connect(lambda _v: self._bg_changed())
        bl.addRow("Tipo", self.bg_type)
        bl.addRow("Color", self.bg_c1)
        bl.addRow("Segundo color", self.bg_c2)
        bl.addRow("Ángulo", self.bg_angle)
        tabs.addTab(bgw, "Fondo")
        self.left_tabs = tabs
        return tabs

    # ----------------------------------------------------------- propuestas
    def _build_proposals_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Texto para la miniatura</b> (corto: no es el título)"))
        self.sugg_box = QWidget()
        self.sugg_lay = QGridLayout(self.sugg_box)
        self.sugg_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.sugg_box)
        self.prop_text = QPlainTextEdit()
        self.prop_text.setFixedHeight(46)
        self.prop_text.setPlaceholderText("Escribe tu frase o elige una de arriba")
        lay.addWidget(self.prop_text)
        from .spellcheck import attach as _spell
        lay.addWidget(_spell(self.prop_text))
        b = QPushButton("✨ Crear 3 propuestas")
        b.setObjectName("primary")
        b.setMinimumHeight(36)
        b.clicked.connect(self.make_proposals)
        brow = QHBoxLayout()
        brow.addWidget(b, 1)
        b_img = QPushButton("🖼 Usar una imagen mía…")
        b_img.setMinimumHeight(36)
        b_img.setToolTip("Las propuestas parten de esa imagen (también usan las imágenes que ya tengas en el lienzo).")
        b_img.clicked.connect(self.proposals_from_file)
        brow.addWidget(b_img)
        lay.addLayout(brow)
        self.prop_status = QLabel("")
        self.prop_status.setWordWrap(True)
        self.prop_status.setObjectName("hint")
        self.prop_status.setToolTip("Parten de tu imagen (o de los fotogramas de tu video). Elige una y edítala: lo que "
                                    "cambies se recordará para las siguientes.")
        lay.addWidget(self.prop_status)
        self.prop_list = QListWidget()
        self.prop_list.setViewMode(QListView.IconMode)
        self.prop_list.setIconSize(QSize(300, 169))
        self.prop_list.setGridSize(QSize(310, 205))
        self.prop_list.setResizeMode(QListView.Adjust)
        self.prop_list.setMovement(QListView.Static)
        self.prop_list.setWordWrap(True)
        self.prop_list.itemClicked.connect(self._use_proposal)
        lay.addWidget(self.prop_list, 1)
        srow = QHBoxLayout()
        self.style_lbl = QLabel()
        self.style_lbl.setWordWrap(True)
        self.style_lbl.setObjectName("dim")
        srow.addWidget(self.style_lbl, 1)
        bs = QPushButton("🎨 Mi estilo…")
        bs.setToolTip("Que la IA aprenda de tus miniaturas (y de referencias que te gusten)")
        bs.clicked.connect(self.open_style)
        srow.addWidget(bs)
        lay.addLayout(srow)
        self._proposals = []
        self._base_proposal = None
        QTimer.singleShot(0, self._fill_suggestions)
        QTimer.singleShot(0, self._style_label)
        return w

    def open_style(self):
        from .thumb_style_dialog import StyleDialog
        StyleDialog(self).exec()
        self._style_label()
        self._fill_suggestions()

    def _style_label(self):
        from .thumb_style_dialog import load
        st = load()
        prof = (st.get("propio") or {})
        n = prof.get("n", 0)
        if n and st.get("usar", True):
            self.style_lbl.setText(f"🎨 Usando tu estilo (aprendido de {n} miniaturas).")
        elif n:
            self.style_lbl.setText("🎨 Tu estilo está aprendido, pero desactivado.")
        else:
            self.style_lbl.setText("🎨 Aún no conozco tu estilo: enséñame tus miniaturas.")

    def _fill_suggestions(self):
        from ..ai import thumb_proposals as P
        p = self.ctrl.project
        topics = list(dict.fromkeys(m.label.title() for m in p.markers if m.kind == "topic"))
        name = p.name if p.name != "Proyecto sin título" else ""
        if not name and self.ctrl.path:
            name = os.path.splitext(os.path.basename(self.ctrl.path))[0]
        texts = P.suggest_texts(name, topics) if name else ["¿QUÉ PASÓ?", "TODO MAL", "¡POR FIN!", "ANTES vs AHORA"]
        mw = self._prefs().get("max_words")
        if mw:   # las frases con tu número de palabras primero
            texts = sorted(texts, key=lambda t: len(t.split()) > mw)
        while self.sugg_lay.count():
            it = self.sugg_lay.takeAt(0).widget()
            if it is not None:
                it.setParent(None)
        for i, t in enumerate(texts[:6]):
            b = QPushButton(t)
            b.setToolTip("Usar esta frase")
            b.clicked.connect(lambda _=False, tt=t: self.prop_text.setPlainText(tt))
            self.sugg_lay.addWidget(b, i // 2, i % 2)
        if texts and not self.prop_text.toPlainText():
            self.prop_text.setPlainText(texts[0])

    def _learned(self) -> dict:
        from PySide6.QtCore import QSettings
        try:
            return json.loads(str(QSettings("EditorIA", "EditorIA").value("miniatura/preferencias", "{}")))
        except ValueError:
            return {}

    def _prefs(self) -> dict:
        """Tu estilo aprendido de tus miniaturas (y referencias) + lo que corregiste a mano (esto manda)."""
        from ..ai import thumb_style as S
        from .thumb_style_dialog import load
        st = load()
        use = st.get("usar", True)
        base = S.to_prefs(st.get("propio") if use else None, st.get("refs") if use else None,
                          self.doc["format"], self.doc["w"], defaults=True)
        return {**base, **self._learned()}

    def _learn(self):
        """Lo que cambiaste en la propuesta elegida se recuerda para las siguientes."""
        if self._base_proposal is None:
            return
        from PySide6.QtCore import QSettings
        from ..ai import thumb_proposals as P
        prefs = P.learn(self._learned(), self._base_proposal, self.doc)
        QSettings("EditorIA", "EditorIA").setValue("miniatura/preferencias", json.dumps(prefs))

    def proposals_from_file(self):
        """🖼 Las propuestas a partir de una imagen tuya."""
        path, _ = QFileDialog.getOpenFileName(self, "Imagen para las propuestas", "",
                                              "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp)")
        if path:
            self.make_proposals([path])

    def _source_images(self) -> list[str]:
        """De dónde parten las propuestas: tus imágenes del lienzo (no los elementos ni los recortes de pegatina),
        luego los fotogramas recomendados y, si no hay, el del cabezal."""
        mine = [l["path"] for l in self.doc["layers"] if l["kind"] == "image" and l.get("path")
                and os.path.exists(l["path"]) and not l.get("element")]
        frames = list(dict.fromkeys(mine)) + [c.path for c in self.reco]
        if not frames:
            f = self.grab_frame(self.win.engine.time)
            frames = [f] if f else []
        return frames

    def make_proposals(self, frames: list[str] | None = None):
        from ..ai import thumb_proposals as P
        self._learn()
        frames = [f for f in (frames or self._source_images()) if f]
        if not frames:
            self.prop_status.setText("Elige una imagen («🖼 Usar una imagen mía…») o pon el cabezal sobre tu video.")
            return
        text = self.prop_text.toPlainText().strip() or "TÍTULO"
        if self.job is not None:
            self.prop_status.setText("Espera un momento: estoy terminando otra tarea…")
            return
        fmt, prefs = self.doc["format"], self._prefs()
        cuts = self._cutouts

        def work():
            from ..ai import bg_removal as BR
            src = P.subject_frame(frames)
            if src and src not in cuts and BR.is_available():
                try:
                    cuts[src] = BR.remove(src)
                except Exception:
                    cuts[src] = None
            return P.proposals(fmt, frames, text, prefs, cuts)

        self.prop_status.setText("✨ Preparando propuestas (recortando al personaje)…")
        self._bg_job(work, self._show_proposals, "✨ Preparando propuestas…")

    def _show_proposals(self, props):
        self._proposals = props
        self.prop_list.clear()
        for name, d in self._proposals:
            img = T.render(d, 300 / d["w"]) if d["format"] == "youtube" else T.render(d, 169 / d["h"])
            it = QListWidgetItem(QIcon(QPixmap.fromImage(img)), name)
            self.prop_list.addItem(it)
        self.prop_status.setText("Elige una (clic) y edítala. Puedes volver aquí y elegir otra.")

    # ----------------------------------------------------------- 🔎 PNG (Google Imágenes dentro del taller)
    PNG_URL = "https://www.google.com/search?tbm=isch&tbs=ic:trans,ift:png&q={q}"
    BG_URL = "https://www.google.com/search?tbm=isch&tbs=isz:l,iar:{ar}&q={q}"     # modo Fondo: grandes; ar = w (horizontal) / t (vertical)
    _PNG_PLACEHOLDER = {"png": "🔎 Buscar PNG: fuego, explosión, logo de…",
                        "fondo": "🔎 Buscar fondo: ciudad de noche, bosque, espacio…"}
    _PNG_HINT = {"png": "Clic derecho en una imagen → «Usar en la miniatura»",
                 "fondo": "Clic derecho en una imagen → «Usar de fondo»"}

    def _build_png_tab(self) -> QWidget:
        from PySide6.QtWidgets import QButtonGroup, QLineEdit
        from PySide6.QtCore import QSettings
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 6, 4, 4)
        self._png_mode = "fondo" if QSettings("EditorIA", "EditorIA").value(
            "miniatura/busqueda_modo", "png", type=str) == "fondo" else "png"
        modos = QHBoxLayout()
        self.png_btn_png = QPushButton("✂ PNG recortado")
        self.png_btn_png.setCheckable(True)
        self.png_btn_png.setToolTip("Busca PNG con fondo transparente: se pone encima de la miniatura, a media altura. "
                                    "Si tiene un fondo liso, se lo quita.")
        self.png_btn_fondo = QPushButton("🖼 Fondo")
        self.png_btn_fondo.setCheckable(True)
        self.png_btn_fondo.setToolTip("Busca imágenes grandes para el fondo de la miniatura (anchas en YouTube, altas "
                                      "en Shorts). Se ponen detrás de todo, cubriendo el lienzo, sin quitarles nada.")
        self._png_group = QButtonGroup(w)
        self._png_group.setExclusive(True)
        for b in (self.png_btn_png, self.png_btn_fondo):
            self._png_group.addButton(b)
            modos.addWidget(b)
        (self.png_btn_fondo if self._png_mode == "fondo" else self.png_btn_png).setChecked(True)
        modos.addStretch(1)
        v.addLayout(modos)
        self._png_group.buttonClicked.connect(self._png_mode_changed)
        row = QHBoxLayout()
        self.png_query = QLineEdit()
        self.png_query.setPlaceholderText(self._PNG_PLACEHOLDER[self._png_mode])
        self.png_query.setClearButtonEnabled(True)
        self.png_query.returnPressed.connect(self.search_png)
        row.addWidget(self.png_query, 1)
        b = QPushButton("Buscar")
        b.setObjectName("primary")
        b.clicked.connect(self.search_png)
        row.addWidget(b)
        v.addLayout(row)
        from PySide6.QtCore import QSettings
        from ..ai import thumb_elements as E
        self.png_nowm = QCheckBox("Sin marca de agua")
        self.png_nowm.setToolTip("Quita de la búsqueda los bancos de imágenes que ponen marca de agua: "
                                 + ", ".join(s.split(".")[0] if s != "stock.adobe.com" else "Adobe Stock"
                                             for s in E.WATERMARK_SITES) + ".")
        self.png_nowm.setChecked(QSettings("EditorIA", "EditorIA").value("miniatura/png_sin_marca", True, type=bool))
        self.png_nowm.toggled.connect(self._png_nowm_changed)
        v.addWidget(self.png_nowm)
        self.png_status = QLabel(self._PNG_HINT[self._png_mode])
        self.png_status.setObjectName("hint")
        self.png_status.setWordWrap(True)
        self.png_status.setToolTip("Se usa la imagen grande (de la página original), no la miniatura de Google. "
                                   "Se comprueba sola: si es PNG transparente y su tamaño; si tiene un fondo liso "
                                   "(blanco, negro), se lo quita.")
        v.addWidget(self.png_status)
        self.png_box = QVBoxLayout()
        v.addLayout(self.png_box, 1)
        self.png_view = None
        self._png_job = None
        return w

    def search_png(self):
        q = self.png_query.text().strip()
        if not q:
            return
        if self.png_view is None:                  # (el navegador se crea la primera vez que buscas)
            self.png_view = _PngView(self)
            self.png_view.use_image.connect(self.use_png)
            self.png_box.addWidget(self.png_view, 1)
        from PySide6.QtCore import QUrl
        self.png_view.bg = self._png_mode == "fondo"           # (el menú dice «Usar de fondo» en este modo)
        self.png_view.load(QUrl(self._search_url(q)))
        self._split.setSizes([max(560, self._split.sizes()[0]), *self._split.sizes()[1:]])   # (más ancho: se ve mejor)

    def _search_url(self, q: str) -> str:
        """La búsqueda de Google Imágenes según el modo. PNG: con transparencia. Fondo: imágenes grandes y de la
        forma del lienzo (anchas en YouTube, altas en Shorts), sin la palabra «png»."""
        import urllib.parse
        from ..ai import thumb_elements as E
        if self._png_mode == "fondo":
            d = self.doc
            ar = "w" if d["format"] == "youtube" or d["w"] > d["h"] else "t"
            q_full = q + " wallpaper"
        else:
            q_full = q if "png" in q.lower() else q + " png"
        if self.png_nowm.isChecked():
            q_full += E.no_watermark_query()
        quoted = urllib.parse.quote_plus(q_full)
        if self._png_mode == "fondo":
            return self.BG_URL.format(ar=ar, q=quoted)
        return self.PNG_URL.format(q=quoted)

    def _png_mode_changed(self, btn):
        """Cambio de modo (PNG recortado / Fondo): se recuerda y, si hay búsqueda escrita, se repite."""
        from PySide6.QtCore import QSettings
        modo = "fondo" if btn is self.png_btn_fondo else "png"
        self._png_mode = modo
        QSettings("EditorIA", "EditorIA").setValue("miniatura/busqueda_modo", modo)
        self.png_query.setPlaceholderText(self._PNG_PLACEHOLDER[modo])
        self.png_status.setText(self._PNG_HINT[modo])
        if self.png_view is not None:
            self.png_view.bg = modo == "fondo"
            if self.png_query.text().strip():
                self.search_png()

    def _png_nowm_changed(self, on: bool):
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue("miniatura/png_sin_marca", bool(on))
        if self.png_view is not None and self.png_query.text().strip():
            self.search_png()                      # (se repite la búsqueda con el filtro nuevo)

    def use_png(self, url: str, fallback: str = ""):
        """Clic derecho → «Usar en la miniatura»: se baja, se comprueba (y se le quita el fondo liso) y se añade."""
        from ..ai import thumb_elements as E
        from .jobs import BackgroundJob
        if not url or (self._png_job is not None and self._png_job.isRunning()):
            return

        bg = self._png_mode == "fondo"             # (Fondo: la imagen tal cual; PNG: se le quita el fondo liso)

        def work(_p, _c):
            try:
                return E.fetch(url, keep_bg=bg)
            except Exception:  # noqa: BLE001 - la web original no deja bajarla: la de Google
                if not fallback:
                    raise
                return E.fetch(fallback, keep_bg=bg)
        self.png_status.setText("⬇ Bajando la imagen…")
        self._png_site = E.watermark_site(url)     # (para avisar: ese banco suele poner marca de agua)
        self._png_job = BackgroundJob(work, self)
        self._png_job.done.connect(self._bg_ready if bg else self._png_ready)
        self._png_job.failed.connect(lambda m: self._png_failed(url, m))
        self._png_job.start()

    def _png_failed(self, url: str, msg: str):
        """La web no deja bajarla desde el programa (403…): que la baje el navegador del taller."""
        if self.png_view is not None and url.startswith("http"):
            self.png_status.setText("⬇ La página no la deja bajar directo; probando con el navegador…")
            self.png_view.download(url, lambda path: self.use_png(path) if path else
                                   self.png_status.setText("✗ Esa página no deja bajar la imagen. Prueba con otra."))
            return
        last = (msg or "").strip().splitlines()[-1:] or [""]
        self.png_status.setText("✗ No se pudo usar esa imagen. Prueba con otra. (" + last[0][:80] + ")")

    def _png_ready(self, e: dict):
        lay = T.image_layer(e["path"], self.doc, "PNG")
        lay["element"] = True                      # (no cuenta como «tu imagen» para las propuestas)
        h = self.doc["h"] * 0.5
        if e["h"] > h:                             # grande: a la mitad del alto del lienzo
            lay["scale"] = round(h / e["h"], 4)
        pos = getattr(self, "_drop_pos", None)
        if pos is not None:
            lay["x"], lay["y"] = round(pos.x(), 1), round(pos.y(), 1)
            self._drop_pos = None
        self._add(lay, "Añadir PNG")
        self.png_status.setText(f"✓ Añadida a la miniatura y a «Material» · {e['badge']}")
        site = getattr(self, "_png_site", None)
        if site:
            self.png_status.setText(self.png_status.text() + f"\n⚠ Viene de {site}: suele llevar marca de agua")
            self._png_site = None
        self._fill_material()

    def _bg_ready(self, e: dict):
        """Modo Fondo: la imagen va detrás de todo, cubriendo el lienzo (tal cual, sin quitarle nada)."""
        self.add_image(e["path"], "Fondo", fill=True)
        txt = f"✓ Puesta de fondo · {e['w']}×{e['h']}"
        if e["w"] < self.doc["w"] or e["h"] < self.doc["h"]:
            txt += "\n⚠ Es pequeña: puede verse borrosa"
        site = getattr(self, "_png_site", None)
        if site:
            txt += f"\n⚠ Viene de {site}: suele llevar marca de agua"
            self._png_site = None
        self.png_status.setText(txt)
        self._fill_material()

    def _use_proposal(self, it):
        i = self.prop_list.row(it)
        if not (0 <= i < len(self._proposals)):
            return
        self._learn()
        self.doc = copy.deepcopy(self._proposals[i][1])
        self._base_proposal = copy.deepcopy(self.doc)
        self.canvas.sel = ""
        self._last_label = ""
        self.commit("Propuesta " + self._proposals[i][0][:1])
        self.refresh_all()
        self.statusBar().showMessage(f"«{self._proposals[i][0]}» en el lienzo: edítala a tu gusto (Ctrl+Z para volver).",
                                     8000)

    # ----------------------------------------------------------- datos
    def layer(self, lid: str) -> dict | None:
        return next((l for l in self.doc["layers"] if l["id"] == lid), None)

    def cur(self) -> dict | None:
        return self.layer(self.canvas.sel)

    def commit(self, label: str = "Cambio"):
        """Guarda el estado en el historial (deshacer) y en el proyecto."""
        now = time.time()
        snap = json.dumps(self.doc)
        if snap == self.history[self.pos]:
            return
        merge = label == self._last_label and now - self._last_t < 0.8 and self.pos == len(self.history) - 1 \
            and self.pos > 0
        if merge:
            self.history[self.pos] = snap
        else:
            self.history = self.history[:self.pos + 1] + [snap]
            self.history = self.history[-150:]
            self.pos = len(self.history) - 1
        self._last_label, self._last_t = label, now
        self._save()
        self._refresh_layers()

    def _save(self):
        self.ctrl.project.thumbnails[self.doc["format"]] = copy.deepcopy(self.doc)
        self.ctrl._set_media_dirty()

    def _restore(self):
        sel = self.canvas.sel
        self.doc = json.loads(self.history[self.pos])
        if not self.layer(sel):          # (lo elegido ya no existe, p. ej. al deshacer «Combinar»: la de arriba)
            vis = [l for l in self.doc["layers"] if l.get("visible", True)]
            sel = vis[-1]["id"] if vis and sel else ""
        self.canvas.sel = sel
        self._sel_prev = sel
        self._save()
        self.refresh_all()

    def undo(self):
        if self.pos > 0:
            self.pos -= 1
            self._last_label = ""
            self._restore()

    def redo(self):
        if self.pos < len(self.history) - 1:
            self.pos += 1
            self._last_label = ""
            self._restore()

    def on_live_change(self):
        self._render_soon.start()

    def refresh_all(self):
        self._loading = True
        if hasattr(self, "act_short"):
            self.act_short.setVisible(self.doc["format"] == "youtube")
        bg = self.doc.get("bg") or {}
        self.bg_type.setCurrentIndex(max(0, self.bg_type.findData(bg.get("type", "color"))))
        self.bg_c1.set_color(bg.get("c1", bg.get("color", "#101014")))
        self.bg_c2.set_color(bg.get("c2", "#000000"))
        self.bg_angle.setValue(int(bg.get("angle", 90)))
        self._loading = False
        self.canvas.refresh()
        self._refresh_layers()
        self._fill_props()
        self._fill_material()

    def _build_layers_panel(self) -> QWidget:
        """Columna «Capas», siempre a la vista junto al lienzo: arriba = delante. Se reordena arrastrando."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 6, 4, 4)
        head = QLabel("Capas")
        head.setObjectName("sectionhead")
        v.addWidget(head)
        self.layers = QListWidget()
        self.layers.setIconSize(QSize(56, 56))
        self.layers.setSpacing(2)
        self.layers.setDragDropMode(QListWidget.InternalMove)
        self.layers.setDefaultDropAction(Qt.MoveAction)
        self.layers.setToolTip("Arriba = delante. Arrastra una capa para cambiarla de sitio · clic = elegirla")
        self.layers.currentRowChanged.connect(self._layer_row)
        self.layers.model().rowsMoved.connect(lambda *_a: self._layers_dragged())
        self.layers.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layers.setProperty("own_menu", True)          # (su menú lleva «❓ ¿Qué hace esto?» al final)
        self.layers.customContextMenuRequested.connect(self._layers_menu)
        QShortcut(QKeySequence(Qt.Key_Delete), self.layers, activated=self.delete_layer,
                  context=Qt.WidgetShortcut)
        v.addWidget(self.layers, 1)
        grid = QGridLayout()
        grid.setSpacing(3)
        for i, (text, tip, fn) in enumerate((("👁", "Mostrar / ocultar", self.toggle_visible),
                                             ("🔒", "Bloquear / desbloquear", self.toggle_lock),
                                             ("⧉", "Duplicar (Ctrl+D)", self.duplicate),
                                             ("⇡", "Poner delante", lambda: self.arrange(1)),
                                             ("⇣", "Poner detrás", lambda: self.arrange(-1)),
                                             ("🗑", "Eliminar lo seleccionado (Supr)", self.delete_layer))):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            grid.addWidget(b, i // 3, i % 3)
        v.addLayout(grid)
        b_all = QPushButton("🗑 Eliminar todo")
        b_all.setToolTip("Quita todas las capas (las bloqueadas se quedan). Ctrl+Z las recupera")
        b_all.clicked.connect(self.delete_all)
        v.addWidget(b_all)
        w.setMinimumWidth(170)
        return w

    def _layers_dragged(self):
        """Se soltó una capa en otro sitio de la lista: el lienzo sigue el nuevo orden."""
        ids = [self.layers.item(i).data(Qt.UserRole) for i in range(self.layers.count())]
        by_id = {l["id"]: l for l in self.doc["layers"]}
        if sorted(ids) != sorted(by_id):
            return
        self.doc["layers"] = [by_id[i] for i in reversed(ids)]       # (arriba en la lista = delante)
        self._last_label = ""
        self.commit("Ordenar capas")
        self.canvas.viewport().update()

    def _refresh_layers(self):
        self.layers.blockSignals(True)
        self.layers.clear()
        for lay in reversed(self.doc["layers"]):   # arriba en la lista = delante en el lienzo
            flags = ("" if lay.get("visible", True) else "  (oculta)") + ("  🔒" if lay.get("locked") else "")
            it = QListWidgetItem(self._layer_icon(lay), f"{lay['name']}{flags}")
            it.setToolTip({"image": "Imagen", "text": "Texto", "shape": "Forma"}[lay["kind"]])
            it.setData(Qt.UserRole, lay["id"])
            self.layers.addItem(it)
            if lay["id"] == self.canvas.sel:
                it.setSelected(True)
                self.layers.setCurrentItem(it)
        self.layers.blockSignals(False)
        self._row_buttons()

    def _row_buttons(self):
        """En la capa elegida de la lista: 👁 mostrar/ocultar y 🗑 eliminar, ahí mismo."""
        from PySide6.QtWidgets import QToolButton
        for i in range(self.layers.count()):
            if self.layers.itemWidget(self.layers.item(i)) is not None:
                self.layers.removeItemWidget(self.layers.item(i))
        it = self.layers.currentItem()
        lay = self.layer(it.data(Qt.UserRole)) if it is not None else None
        if lay is None:
            return
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 4, 0)
        h.setSpacing(2)
        h.addStretch(1)
        for text, tip, fn in ((("👁" if lay.get("visible", True) else "◌"),
                               "Ocultar" if lay.get("visible", True) else "Mostrar", self.toggle_visible),
                              ("🗑", "Eliminar (Supr)", self.delete_layer)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, f=fn: QTimer.singleShot(0, f))   # (después: la lista se rehace)
            if fn == self.delete_layer and lay.get("locked"):
                b.setEnabled(False)
                b.setToolTip("Bloqueada: desbloquéala para eliminarla")
            h.addWidget(b)
        w.setAttribute(Qt.WA_TranslucentBackground)
        self.layers.setItemWidget(it, w)

    def _layers_menu(self, pos):
        it = self.layers.itemAt(pos)
        lay = self.layer(it.data(Qt.UserRole)) if it is not None else None
        if it is not None:
            self.layers.setCurrentItem(it)
        self.layer_menu(lay).exec(self.layers.viewport().mapToGlobal(pos))

    def layer_menu(self, lay: dict | None):
        """Clic derecho en una capa (en la lista o en el lienzo): todo lo que se puede hacer con ella."""
        from PySide6.QtWidgets import QMenu
        from .help import add_help_action
        m = QMenu(self)
        if lay is None:                                     # en un hueco: solo pegar
            m.addAction("📋 Pegar\tCtrl+V", self.paste)
            add_help_action(m, "miniatura", self)
            return m
        self.canvas.sel = lay["id"]
        locked = bool(lay.get("locked"))

        def act(menu, text, fn, enabled=True):
            a = menu.addAction(text, fn)
            a.setEnabled(enabled)
            return a
        act(m, "✂ Cortar\tCtrl+X", self.cut_layer, not locked)
        act(m, "⧉ Copiar\tCtrl+C", self.copy_layer)
        act(m, "📋 Pegar\tCtrl+V", self.paste)
        act(m, "⧉ Duplicar\tCtrl+D", self.duplicate)
        m.addSeparator()
        orden = m.addMenu("Orden")
        L = self.doc["layers"]
        i = L.index(lay)
        act(orden, "⤒ Al frente del todo", lambda: self.arrange(len(L)), i < len(L) - 1)
        act(orden, "↑ Poner delante", lambda: self.arrange(1), i < len(L) - 1)
        act(orden, "↓ Poner detrás", lambda: self.arrange(-1), i > 0)
        act(orden, "⤓ Al fondo del todo", lambda: self.arrange(-len(L)), i > 0)
        act(m, "↔ Voltear (espejo)", lambda: self._set(lay, "Voltear", flip=not lay.get("flip")), not locked)
        act(m, "👁 Ocultar" if lay.get("visible", True) else "👁 Mostrar", self.toggle_visible)
        act(m, "🔓 Desbloquear" if locked else "🔒 Bloquear", self.toggle_lock)
        act(m, "🌫 Quitar desenfoque" if float(lay.get("blur", 0) or 0) > 0 else "🌫 Desenfocar",
            lambda: self.toggle_blur(lay), not locked and not lay.get("blur_area"))
        if lay["kind"] == "image":
            m.addSeparator()
            act(m, "⛶ Llenar el lienzo", lambda: self.fill_canvas(lay), not locked)
            act(m, "🌫 Fondo desenfocado detrás", lambda: self.blur_background(lay))
            act(m, "✂ Quitar fondo", self.cutout_auto, not locked)
            img = QImage(lay["path"])
            mejor = m.addMenu("⇱ Mejorar resolución")
            for f in (2, 4):
                act(mejor, f"×{f}", lambda _=False, f=f: self.upscale_image(f),
                    not locked and self.job is None and img.width() * img.height() * f * f <= self.MAX_UPSCALE_PX)
            try:
                from ..ai import funny_faces as FF
                caras = m.addMenu("😜 Cara graciosa")
                etiq = {k: lb for k, lb, _t in FF.PRESETS}
                for titulo, claves in FF.GROUPS:
                    sub = caras.addMenu(titulo)
                    for key in claves:
                        act(sub, etiq[key], lambda _=False, k=key: self.funny_face(k), not locked)
            except Exception:  # noqa: BLE001
                pass
        if lay.get("warp") or lay.get("liquify"):
            m.addSeparator()
            if lay.get("warp"):
                act(m, "◇ Quitar deformación", self.reset_warp, not locked)
            if lay.get("liquify"):
                act(m, "≈ Quitar licuado", self.liquify_reset, not locked)
        m.addSeparator()
        act(m, "🗑 Eliminar\tSupr", self.delete_layer, not locked)
        add_help_action(m, "miniatura", self)
        return m

    def _layer_icon(self, lay: dict) -> QIcon:
        """Miniatura de la capa (sobre un damero, para que se vea lo transparente)."""
        if lay.get("blur_area") is not None:              # 🌫 zona borrosa: no tiene imagen propia → su forma, difusa
            pm = QPixmap(56, 56)
            pm.fill(QColor("#2a2a2e"))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            for r, a in ((22, 40), (18, 70), (14, 110)):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(200, 210, 230, a))
                rect = QRectF(28 - r, 28 - r, 2 * r, 2 * r)
                p.drawEllipse(rect) if lay.get("shape") == "ellipse" else p.drawRoundedRect(rect, 3, 3)
            p.end()
            return QIcon(pm)
        try:
            img, _w, _h = self.canvas._render(lay)          # (recién licuada: la rápida hasta que esté la buena)
            pm = QPixmap.fromImage(img).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:  # noqa: BLE001
            return QIcon()
        out = QPixmap(56, 56)
        out.fill(QColor("#2a2a2e"))
        p = QPainter(out)
        for y in range(0, 56, 8):
            for x in range(0, 56, 8):
                if (x // 8 + y // 8) % 2:
                    p.fillRect(x, y, 8, 8, QColor("#3a3a40"))
        p.drawPixmap((56 - pm.width()) // 2, (56 - pm.height()) // 2, pm)
        p.end()
        return QIcon(out)

    def _layer_row(self, row: int):
        it = self.layers.item(row)
        if it is not None:
            self.canvas.sel = it.data(Qt.UserRole)
            self._tool_off_if_other(self.canvas.sel)
            self._row_buttons()
            self.canvas.viewport().update()
            self._fill_props()

    def _on_select(self, lid: str):
        if lid != self.canvas._words_of:
            self.canvas.set_words(set(), panel=False)
        self._tool_off_if_other(lid)
        self._refresh_layers()
        self._fill_props()

    def _tool_off_if_other(self, lid: str):
        """Al cambiar a OTRA capa, la herramienta (Licuar, Estirar, Deformar, pinceles) se apaga: era para la
        anterior. Se vuelve al ratón normal con la nueva elegida."""
        prev = getattr(self, "_sel_prev", None)
        self._sel_prev = lid
        if prev is not None and lid != prev and (self.canvas.tool or self.canvas.warp_mode):
            self.select_tool()

    # ----------------------------------------------------------- añadir
    def _fill_material(self):
        """Imágenes de la biblioteca y fotogramas guardados (los recomendados se añaden en la fase siguiente)."""
        self.material.clear()
        p = self.ctrl.project
        for c in self.reco:
            m = p.media.get(c.media_id)
            it = QListWidgetItem(QIcon(QPixmap(c.path).scaled(140, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                 "✨ " + ", ".join(c.reasons[:2]))
            it.setData(Qt.UserRole, c.path)
            it.setData(MAT_KIND, "reco")
            it.setToolTip(f"Recomendado por la IA: {', '.join(c.reasons)}\n{m.name if m else ''} · {c.time:.1f} s")
            self.material.addItem(it)
        vistas: set[str] = set()
        for m in reversed(list(p.media.values())):         # tus imágenes de «Medios», las últimas primero
            if m.kind == KIND_IMAGE and os.path.exists(m.path):
                vistas.add(os.path.normcase(os.path.abspath(m.path)))
                it = QListWidgetItem(self._mat_icon(m.path), m.name[:24])
                it.setData(Qt.UserRole, m.path)
                it.setData(MAT_KIND, "medios")
                it.setData(MAT_MEDIA, m.id)
                it.setToolTip(f"{m.name}\nDe «Medios» · clic = añadir encima · doble clic = de fondo · "
                              "arrástrala al lienzo")
                self.material.addItem(it)
        for path in self._recientes():                      # 📁 las que pusiste desde tus carpetas
            k = os.path.normcase(os.path.abspath(path))
            if k in vistas:
                continue
            vistas.add(k)
            it = QListWidgetItem(self._mat_icon(path), "📁 " + os.path.basename(path)[:22])
            it.setData(Qt.UserRole, path)
            it.setData(MAT_KIND, "reciente")
            it.setToolTip(f"{os.path.basename(path)}\nDe tus carpetas: {os.path.dirname(path)}\n"
                          "Clic = añadir encima · doble clic = de fondo · clic derecho = quitar")
            self.material.addItem(it)
        from ..ai import thumb_elements as E
        for path in E.downloaded()[:60]:                    # 🔎 los PNG que bajaste (los últimos primero)
            it = QListWidgetItem(QIcon(QPixmap(path).scaled(140, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                 "🔎 PNG")
            it.setData(Qt.UserRole, path)
            it.setData(MAT_KIND, "png")
            it.setToolTip("PNG bajado con «🔎 PNG». Clic = añadirlo · doble clic = de fondo · clic derecho = borrar")
            self.material.addItem(it)

    # ----------------------------------------------------------- 📁 imágenes de tus carpetas en «Material»
    @staticmethod
    def _ajustes_lista(clave: str) -> list[str]:
        from PySide6.QtCore import QSettings
        try:
            v = json.loads(str(QSettings("EditorIA", "EditorIA").value(clave, "[]")))
            return [str(x) for x in v] if isinstance(v, list) else []
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _guardar_lista(clave: str, lista: list[str]):
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue(clave, json.dumps(lista[:RECIENTES_MAX]))

    def _de_fuera(self, path: str) -> bool:
        """¿Es una imagen tuya (de tus carpetas)? No lo es si ya está en Medios o es un archivo interno de Reclaimer
        (PNG bajados, fotogramas…)."""
        from ..core.paths import cache_dir
        k = os.path.normcase(os.path.abspath(path))
        interno = os.path.normcase(os.path.abspath(str(cache_dir("png_web").parent)))
        if k.startswith(interno + os.sep):
            return False
        return not any(os.path.normcase(os.path.abspath(m.path)) == k for m in self.ctrl.project.media.values())

    def _recordar(self, path: str):
        """Una imagen de tus carpetas que pones en la miniatura queda en «Material» (también en otros proyectos)."""
        try:
            if not path or not os.path.isfile(path) or not self._de_fuera(path):
                return
            path = os.path.abspath(path)
            k = os.path.normcase(path)
            lista = [x for x in self._ajustes_lista("miniatura/recientes") if os.path.normcase(x) != k]
            self._guardar_lista("miniatura/recientes", [path] + lista)
            quitadas = [x for x in self._ajustes_lista("miniatura/recientes_quitadas") if os.path.normcase(x) != k]
            self._guardar_lista("miniatura/recientes_quitadas", quitadas)
            self._mat_soon.start()
        except Exception:  # noqa: BLE001 - recordar nunca estorba al añadir
            pass

    def _recientes(self) -> list[str]:
        """Las tuyas de tus carpetas: las que pusiste (las últimas primero) y las que ya usan las miniaturas de este
        proyecto; sin las que quitaste de «Material» ni las que ya no existen."""
        quitadas = {os.path.normcase(x) for x in self._ajustes_lista("miniatura/recientes_quitadas")}
        rutas = list(self._ajustes_lista("miniatura/recientes"))
        docs = [self.doc] + [d for d in self.ctrl.project.thumbnails.values() if isinstance(d, dict)]
        for d in docs:
            for lay in d.get("layers") or []:
                if isinstance(lay, dict) and lay.get("type") == "image" and lay.get("path"):
                    rutas.append(str(lay["path"]))
        out, vistas = [], set()
        for r in rutas:
            k = os.path.normcase(os.path.abspath(r))
            if k in vistas or k in quitadas or not os.path.isfile(r) or not self._de_fuera(r):
                continue
            vistas.add(k)
            out.append(os.path.abspath(r))
        return out[:RECIENTES_MAX]

    # ----------------------------------------------------------- clic derecho en «Material»: quitar / Papelera
    def _material_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        from . import help as H
        it = self.material.itemAt(pos)
        menu = QMenu(self.material)
        if it is not None:
            self.material.setCurrentItem(it)
            tipo = it.data(MAT_KIND)
            if tipo == "png":
                menu.addAction("🗑 Borrar este PNG", lambda: self._material_quitar(it))
            else:
                textos = {"medios": "✕ Quitar de Material y de Medios (el archivo se queda)",
                          "reciente": "✕ Quitar de Material (el archivo se queda en tu carpeta)",
                          "reco": "✕ Quitar esta propuesta"}
                menu.addAction(textos.get(tipo, "✕ Quitar de Material"), lambda: self._material_quitar(it))
                if tipo in ("medios", "reciente"):
                    menu.addAction("🗑 Eliminar el archivo (a la Papelera)…", lambda: self._material_papelera(it))
        H.add_help_action(menu, H.help_key_for(self.material), self)
        if not menu.isEmpty():
            H.exec_menu(menu, self.material.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _material_quitar(self, it) -> bool:
        """✕ Quitar (Supr): de la lista (y de Medios si venía de ahí); los archivos se quedan en el disco. Los PNG
        bajados con «🔎 PNG» sí se borran (son de Reclaimer; van a la Papelera)."""
        if it is None:
            return False
        tipo, path = it.data(MAT_KIND), str(it.data(Qt.UserRole) or "")
        ok = True
        if tipo == "medios":
            ok = self.ctrl.remove_media([it.data(MAT_MEDIA)])   # avisa si se está usando en la línea de tiempo
            if not ok:
                self.statusBar().showMessage(f"«{os.path.basename(path)}» se usa en la línea de tiempo: quita antes "
                                             "sus clips.", 6000)
        elif tipo == "reciente":
            k = os.path.normcase(path)
            self._guardar_lista("miniatura/recientes",
                                [x for x in self._ajustes_lista("miniatura/recientes") if os.path.normcase(x) != k])
            self._guardar_lista("miniatura/recientes_quitadas",
                                [path] + self._ajustes_lista("miniatura/recientes_quitadas"))
        elif tipo == "png":
            ok = not os.path.exists(path) or _a_papelera(path)
            if not ok:
                self.statusBar().showMessage("No pude borrar ese PNG.", 5000)
        elif tipo == "reco":
            self.reco = [c for c in self.reco if c.path != path]
        if ok:
            self._fill_material()
            self.statusBar().showMessage("🗑 PNG borrado (está en la Papelera)." if tipo == "png"
                                         else f"✕ «{os.path.basename(path)}» quitada de «Material».", 5000)
        return ok

    def _material_papelera(self, it) -> bool:
        """🗑 Manda el archivo a la Papelera de Windows (recuperable), tras preguntar."""
        if it is None:
            return False
        tipo, path = it.data(MAT_KIND), str(it.data(Qt.UserRole) or "")
        if tipo == "medios" and self.ctrl.project.is_media_used(it.data(MAT_MEDIA)):
            self.statusBar().showMessage(f"«{os.path.basename(path)}» se usa en la línea de tiempo: quita antes "
                                         "sus clips.", 6000)
            return False
        if QMessageBox.question(self, "Eliminar el archivo",
                                f"¿Mandar «{os.path.basename(path)}» a la Papelera de Windows?\n\n{path}\n\n"
                                "Se puede recuperar desde la Papelera.") != QMessageBox.Yes:
            return False
        if not self._material_quitar(it):
            return False
        if os.path.exists(path) and not _a_papelera(path):
            self.statusBar().showMessage(f"No pude mandar «{os.path.basename(path)}» a la Papelera.", 6000)
            return False
        self.statusBar().showMessage(f"🗑 «{os.path.basename(path)}» está en la Papelera.", 6000)
        return True

    def _mat_icon(self, path: str) -> QIcon:
        try:
            t = os.path.getmtime(path)
        except OSError:
            t = 0
        got = self._mat_icons.get(path)
        if got is None or got[0] != t:
            got = (t, QIcon(QPixmap(path).scaled(140, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self._mat_icons[path] = got
        return got[1]

    def _show_folders(self, on: bool):
        """📁 Carpetas ↔ imágenes sueltas (la vista de carpetas se crea la primera vez)."""
        if on and self.folders is None:
            self.folders = self._FolderBrowser(self)
            self.folders.imageChosen.connect(lambda p: self._add_png_or_image(p))
            self.folders.imageBackground.connect(lambda p: self.add_image(p, "Fondo", fill=True))
            self.folders.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
            self.mat_stack.addWidget(self.folders)
        self.mat_stack.setCurrentWidget(self.folders if on else self.material)

    def _add_png_or_image(self, path: str):
        """Clic en una imagen de una carpeta: si es un PNG con transparencia va como elemento (encima, a media
        altura); si no, como imagen."""
        from ..ai import thumb_elements as E
        m = E.measure(path)
        if m and m[2] > 0.05:
            self._recordar(path)
            self._png_ready({"path": path, "w": m[0], "h": m[1], "badge": f"{m[0]}×{m[1]}"})
        else:
            self.add_image(path, os.path.splitext(os.path.basename(path))[0])

    def _material_click(self, it):
        if it.data(MAT_KIND) == "png":
            from ..ai import thumb_elements as E
            m = E.measure(it.data(Qt.UserRole))
            if m:
                self._png_ready({"path": it.data(Qt.UserRole), "w": m[0], "h": m[1], "badge": f"{m[0]}×{m[1]}"})
            return
        self.add_image(it.data(Qt.UserRole), it.text())

    def _add(self, lay: dict, label: str):
        self.doc["layers"].append(lay)
        self.canvas.sel = lay["id"]
        self.canvas.viewport().update()
        self._last_label = ""
        self.commit(label)
        self._fill_props()

    def add_image(self, path: str, name: str = "Imagen", fill: bool = False):
        if not path or not os.path.exists(path):
            return
        hueco = self.cur()
        if not fill and hueco is not None and hueco.get("slot") and not hueco.get("locked"):
            self.replace_image(hueco, path)              # 🖼 con un hueco elegido, la imagen va a él
            return
        self._recordar(path)
        lay = T.image_layer(path, self.doc, name[:30], fill=fill)
        if fill:   # un fondo va detrás de todo
            self.doc["layers"].insert(0, lay)
            self.canvas.sel = lay["id"]
            self._last_label = ""
            self.commit("Fondo")
            self.canvas.viewport().update()
            self._fill_props()
            return
        self._add(lay, "Añadir imagen")

    IMG_EXT = (".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".webp", ".bmp", ".gif", ".tif", ".tiff")

    def add_to_material(self, paths: list[str]) -> int:
        """Imágenes (o carpetas con imágenes) soltadas en «Material» desde el PC: entran en «Medios» del proyecto y
        salen en «Material» listas para usar. Devuelve cuántas."""
        files: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                for d, _dirs, names in os.walk(p):
                    files += [os.path.join(d, n) for n in sorted(names) if n.lower().endswith(self.IMG_EXT)]
            elif p.lower().endswith(self.IMG_EXT):
                files.append(p)
        files = files[:300]
        if not files:
            self.statusBar().showMessage("Ahí no hay imágenes (PNG, JPG, WEBP…).", 5000)
            return 0
        self.ctrl.import_now(files)
        self._fill_material()
        self.statusBar().showMessage(f"✓ {len(files)} imagen(es) en «Material» (y en «Medios»)", 6000)
        return len(files)
    VID_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

    def _video_frame(self, path: str, t: float) -> str | None:
        from ..core import media as media_tools
        from ..core.paths import cache_dir
        out = os.path.join(str(cache_dir("miniaturas_material")), f"{media_tools.cache_key(path)}_{t:.2f}.png")
        if not os.path.exists(out):
            media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}",
                                   "-i", path, "-frames:v", "1", out], timeout=60)
        return out if os.path.exists(out) else None

    def drop_on_canvas(self, mime, pt: QPointF) -> int:
        """Se soltó algo en el lienzo: imágenes (o un fotograma de un video) donde se soltaron. Devuelve cuántas."""
        from .common import MEDIA_MIME
        paths: list[str] = []
        web: list[str] = []
        for u in mime.urls():
            if u.isLocalFile():
                paths.append(os.path.normpath(u.toLocalFile()))
            elif u.scheme() in ("http", "https", "data"):
                web.append(u.toString())
        if mime.hasFormat(MEDIA_MIME):              # desde «Medios» (imágenes y videos del proyecto)
            for mid in bytes(mime.data(MEDIA_MIME).data()).decode().split(","):
                m = self.ctrl.project.media.get(mid)
                if m is None:
                    continue
                if m.kind == KIND_IMAGE:
                    paths.append(m.path)
                elif m.kind == KIND_VIDEO:
                    f = self._video_frame(m.path, max(0.0, float(m.duration or 3) / 3))
                    if f:
                        paths.append(f)
        imgs = []
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in self.IMG_EXT:
                imgs.append(p)
            elif ext in self.VID_EXT:
                f = self._video_frame(p, 1.0)
                if f:
                    imgs.append(f)
        if not imgs and not web and mime.hasImage():   # una imagen sin archivo (p. ej. copiada de una web)
            from ..core.paths import cache_dir
            import hashlib
            q = QImage(mime.imageData())
            if not q.isNull():
                out = os.path.join(str(cache_dir("png_web")), "soltada_" + hashlib.md5(
                    bytes(q.constBits())[:65536]).hexdigest()[:12] + ".png")
                q.save(out)
                imgs.append(out)
        destino = self.layer(self.canvas._hit(pt)) if imgs else None
        alt = bool(QApplication.keyboardModifiers() & Qt.AltModifier)
        puestas = 0
        if destino is not None and not destino.get("locked") and (
                destino.get("slot") or (alt and destino["kind"] == "image" and not destino.get("blur_area"))):
            self.replace_image(destino, imgs.pop(0))     # 🖼 en un hueco (o Alt sobre una imagen): la sustituye
            puestas = 1
            if not imgs:
                return 1
        from ..core.paths import cache_dir as _cache_dir
        png_dir = os.path.normcase(os.path.normpath(str(_cache_dir("png_web"))))
        for i, p in enumerate(imgs[:12]):
            self._recordar(p)
            lay = T.image_layer(p, self.doc, os.path.splitext(os.path.basename(p))[0][:30])
            if os.path.normcase(os.path.dirname(os.path.normpath(p))) == png_dir:   # un «🔎 PNG»: como con clic
                lay["element"] = True
                q = QImage(p)
                if not q.isNull() and q.height() > self.doc["h"] * 0.5:
                    lay["scale"] = round(self.doc["h"] * 0.5 / q.height(), 4)
            lay["x"], lay["y"] = round(pt.x() + 30 * i, 1), round(pt.y() + 30 * i, 1)
            self._last_label = ""
            self._add(lay, "Soltar imagen")
        if not imgs and web:                       # de una web: se baja y se comprueba como en «🔎 PNG»
            self._drop_pos = pt
            self.use_png(web[0])
            return 1
        if not imgs and not puestas:
            self.statusBar().showMessage("Eso no es una imagen (ni un video del que sacar un fotograma).", 5000)
        return len(imgs) + puestas

    def add_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagen", "", "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.add_image(path, os.path.basename(path))

    def add_viewer_frame(self):
        """Fotograma de lo que se ve en el visor, a resolución completa (del archivo original)."""
        path = self.grab_frame(self.win.engine.time)
        if path:
            self.add_image(path, "Fotograma")
        else:
            QMessageBox.information(self, "Miniatura", "En el cabezal no hay ningún video o imagen.")

    def grab_frame(self, t: float) -> str | None:
        from ..core import media as media_tools
        from ..core.paths import cache_dir
        p = self.ctrl.project
        for tr in p.tracks:
            if tr.kind != "video" or tr.hidden:
                continue
            c = p.clip_at(tr.id, t)
            m = p.media_of(c) if c else None
            if c is None or m is None or m.kind not in (KIND_VIDEO, KIND_IMAGE):
                continue
            if m.kind == KIND_IMAGE:
                return m.path
            src = self.ctrl.clip_source_time(c.id, t)
            out = os.path.join(str(cache_dir("miniaturas_material")), f"{media_tools.cache_key(m.path)}_{src:.2f}.png")
            if not os.path.exists(out):
                media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{src:.3f}",
                                       "-i", m.path, "-frames:v", "1", out], timeout=60)
            return out if os.path.exists(out) else None
        return None

    def add_text(self, text: str, preset: str):
        lay = T.text_layer(self.doc, text, preset)
        if preset == "label":   # etiqueta: caja de color detrás del texto
            box = T.shape_layer(self.doc, "rect")
            box.update(name="Caja de etiqueta", w=420, h=96, radius=12, fill="#FFD400", x=lay["x"], y=lay["y"])
            self.doc["layers"].append(box)
        self._add(lay, "Añadir texto")

    def add_shape(self, shape: str):
        self._add(T.shape_layer(self.doc, shape), "Añadir forma")

    def add_logo_box(self):
        self._add(T.logo_box_layer(self.doc), "Recuadro del logo")

    def red_frame(self):
        lay = self.cur()
        if lay is None or lay["kind"] != "image" or lay.get("locked"):
            self.statusBar().showMessage("Elige primero una imagen en el lienzo.", 5000)
            return
        T.red_frame(lay)
        self._last_label = ""
        self.commit("Marco rojo")
        self.canvas.viewport().update()
        self._fill_props()

    def add_dark_gradient(self):
        """Degradado de negro a transparente: da contraste al texto sin tapar la imagen."""
        lay = T.shape_layer(self.doc, "rect")
        lay.update(name="Degradado oscuro", w=self.doc["w"], h=self.doc["h"], radius=0, x=self.doc["w"] / 2,
                   y=self.doc["h"] / 2, gradient={"on": True, "c1": "#E6000000", "c2": "#00000000", "angle": 0})
        self._add(lay, "Degradado")

    # ----------------------------------------------------------- acciones
    def duplicate(self):
        lay = self.cur()
        if lay:
            i = self.doc["layers"].index(lay)
            c = T.clone(lay)
            self.doc["layers"].insert(i + 1, c)
            self.canvas.sel = c["id"]
            self._last_label = ""
            self.commit("Duplicar")
            self.canvas.viewport().update()
            self._fill_props()

    # ----------------------------------------------------------- copiar y pegar (Ctrl+C / Ctrl+V)
    # La capa copiada se guarda AQUÍ (con sus efectos); al portapapeles de Windows solo va su imagen (para pegarla en
    # otro programa). ⚠ Nada de QMimeData hecho a mano en el portapapeles: PySide lo borra dos veces al cerrar y el
    # programa se cae (0xC0000005).
    @staticmethod
    def _img_huella(img) -> tuple:
        if img is None or img.isNull():
            return ()
        small = img.convertToFormat(QImage.Format_RGBA8888).scaled(16, 16, Qt.IgnoreAspectRatio,
                                                                   Qt.FastTransformation)
        px = T.qimage_to_rgba(small).astype(int) // 16                  # (tolerante a pequeñas diferencias)
        return (img.width(), img.height(), px.tobytes())

    def copy_layer(self) -> bool:
        """Ctrl+C: copia lo elegido (la capa entera, con sus efectos; y su imagen, para pegarla en otro programa)."""
        from PySide6.QtWidgets import QApplication
        lay = self.cur()
        if lay is None:
            return False
        self._clip = json.dumps(lay)
        self._paste_n = 0
        try:
            img = T.render_layer(lay)[0]
            QApplication.clipboard().setImage(img)
            self._clip_huella = self._img_huella(QApplication.clipboard().image())
        except Exception:  # noqa: BLE001
            self._clip_huella = ()
        self.statusBar().showMessage(f"Copiado: {lay['name']} · Ctrl+V para pegar", 4000)
        return True

    def cut_layer(self) -> bool:
        """Ctrl+X: quita lo elegido (si te arrepientes, Ctrl+V lo vuelve a poner en el mismo sitio, o Ctrl+Z)."""
        lay = self.cur()
        if lay is None or lay.get("locked") or not self.copy_layer():
            return False
        self._paste_n = -1                    # (el primer pegado, justo donde estaba)
        name = lay["name"]
        self.delete_layer()
        self.statusBar().showMessage(f"Cortado: {name} · Ctrl+V lo vuelve a poner", 5000)
        return True

    def paste(self) -> bool:
        """Ctrl+V: pega la capa copiada (un poco desplazada, encima) o, si después se copió otra cosa fuera, esa
        imagen o esos archivos."""
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        m = cb.mimeData()
        clip = getattr(self, "_clip", None)
        mio = clip is not None and (m is None or not (m.hasImage() or m.hasUrls())
                                    or (m.hasImage() and self._img_huella(cb.image()) == getattr(self, "_clip_huella", ())))
        if mio:
            self._paste_n = getattr(self, "_paste_n", 0) + 1
            c = T.clone(json.loads(clip))                         # (ya va 30 px a un lado; cada pegado, 30 más)
            c["x"], c["y"] = float(c["x"]) + 30 * (self._paste_n - 1), float(c["y"]) + 30 * (self._paste_n - 1)
            c["locked"] = False
            self._last_label = ""
            self._add(c, "Pegar")
            return True
        if m is None:
            return False
        center = QPointF(self.doc["w"] / 2, self.doc["h"] / 2)
        return self.drop_on_canvas(m, center) > 0                # (una imagen o archivos copiados en otro sitio)

    # ----------------------------------------------------------- ◇ deformar
    def toggle_warp(self, on: bool | None = None):
        """◇ Deformar: en lo elegido, las 4 esquinas se mueven cada una por su lado (perspectiva libre)."""
        on = self.act_warp.isChecked() if on is None else on
        self.act_warp.setChecked(on)
        if on and self.canvas.tool == "liquify":
            self.toggle_liquify(False)
        self.canvas.warp_mode = on
        self._sync_tools()
        self.canvas.viewport().update()
        self.statusBar().showMessage("◇ Deformar: arrastra cada esquina naranja a donde quieras · «↺» la quita"
                                     if on else "Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = "
                                                "girar", 8000)

    # ----------------------------------------------------------- ↖ Seleccionar (ratón normal)
    def select_tool(self):
        """Deja cualquier herramienta (Licuar, Deformar, pinceles, recuadro) y vuelve al ratón normal."""
        self.canvas.multi.clear()
        self.canvas.set_words(set(), panel=False)
        self.act_liq.setChecked(False)
        self.act_warp.setChecked(False)
        self.canvas.warp_mode = False
        self.canvas._liq_timer.stop()
        self.canvas._drag = None
        self.canvas._stroke = []
        self.canvas._hover = None
        self.canvas.tool = None
        self.canvas.unsetCursor()
        self.canvas.viewport().update()
        self._sync_tools()
        self.statusBar().showMessage("Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = girar", 6000)
        self._fill_props()

    def _sync_tools(self):
        """Marca el botón de la herramienta activa (y «↖ Seleccionar» cuando no hay ninguna)."""
        if hasattr(self, "act_select"):
            self.act_select.setChecked(self.canvas.tool is None and not self.canvas.warp_mode)
        if hasattr(self, "act_stretch"):
            liq = self.canvas.tool == "liquify"
            self.act_stretch.setChecked(liq and self.canvas.liq_mode == "empujar")
            self.act_liq.setChecked(liq and self.canvas.liq_mode != "empujar")

    # ----------------------------------------------------------- ≈ Licuar
    def _guides_changed(self, _i: int = 0):
        from PySide6.QtCore import QSettings
        self.canvas.guides = self.guides_combo.currentData() or ""
        QSettings("EditorIA", "EditorIA").setValue("miniatura/guias", self.canvas.guides)
        self.canvas.viewport().update()

    def _liq_button(self):
        """Botón «≈ Licuar»: si venías de «✋ Estirar», vuelve a inflar."""
        on = self.act_liq.isChecked()
        if on and self.canvas.liq_mode == "empujar":
            self.canvas.liq_mode = "inflar"
        self.toggle_liquify(on)

    def toggle_stretch(self, on: bool | None = None):
        """✋ Estirar: lo que hay dentro del círculo sigue al ratón y arrastra lo de alrededor."""
        on = self.act_stretch.isChecked() if on is None else on
        if on:
            self.canvas.liq_mode = "empujar"
            self.toggle_liquify(True)
            self.statusBar().showMessage("✋ Estirar: agarra y arrastra · tamaño del círculo en el panel derecho · "
                                         "Esc = ratón normal", 8000)
        else:
            self.toggle_liquify(False)

    def toggle_liquify(self, on: bool | None = None):
        on = self.act_liq.isChecked() if on is None else on
        if on and self.act_warp.isChecked():
            self.act_warp.setChecked(False)
            self.canvas.warp_mode = False
        self.canvas.tool = "liquify" if on else None
        self.canvas.setCursor(Qt.BlankCursor if on else Qt.ArrowCursor)
        if on:
            self._warm_liquify()
        self._sync_tools()
        self.canvas.viewport().update()
        self.statusBar().showMessage("≈ Licuar: pinta sobre lo elegido · modo, tamaño y fuerza en el panel derecho"
                                     if on else "Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = "
                                                "girar", 8000)
        self._fill_props()

    def _warm_liquify(self):
        """⚡ Prepara en segundo plano los efectos (contorno, brillo, sombra) de lo elegido para la vista rápida de
        Licuar / Estirar: así el primer toque no espera."""
        lay = self.cur()
        if lay is None or lay.get("kind") != "image" or not any(
                lay.get(k, {}).get("on") for k in ("outline", "glow", "shadow")):
            return
        from .jobs import BackgroundJob
        snap = copy.deepcopy(lay)
        kd = T.draft_k(lay, self.canvas._view())            # la misma reducción que usará la vista rápida
        job = BackgroundJob(lambda _p, _c: T.draft_effects(snap, kd), self)
        self._warm_jobs = [j for j in getattr(self, "_warm_jobs", []) if j.isRunning()] + [job]
        job.start()

    def set_liq_mode(self, mode: str):
        self.canvas.liq_mode = mode
        if self.canvas.tool != "liquify":
            self.toggle_liquify(True)
        self._sync_tools()

    def liquify_dab(self, lay: dict, c: dict, move: tuple[float, float]):
        """Un toque del pincel ≈ Licuar (lo llama el lienzo mientras se pinta)."""
        self.liquify_dabs(lay, [(c, move)])

    def liquify_dabs(self, lay: dict, dabs: list):
        """Varios toques seguidos (lista de (punto, movimiento)); el campo se decodifica y se guarda una sola vez."""
        from ..core import liquify as L
        mode, s = self.canvas.liq_mode, float(self.canvas.liq_strength)
        k = {"inflar": 0.12, "encoger": 0.12, "restaurar": 0.3}.get(mode)
        strength = 1.0 if mode == "empujar" else k * s          # (estirar: el centro sigue al ratón exacto)
        L.stroke_many(lay, [(mode, c["fx"], c["fy"], c["r"], strength, c["aspect"], move,
                             0.5 if mode == "empujar" else 0.0) for c, move in dabs])
        self.canvas.viewport().update()

    def liquify_done(self):
        self._last_label = ""
        self.commit("Licuar")
        self.canvas.viewport().update()
        # (antes: _fill_props() rehacía todo el panel derecho al soltar; basta con habilitar «↺ Quitar licuado»)
        try:
            self._liq_off.setEnabled(bool(self.cur() and self.cur().get("liquify")))
        except (AttributeError, RuntimeError):
            pass

    def liquify_reset(self):
        from ..core import liquify as L
        lay = self.cur()
        if lay and lay.get("liquify") and not lay.get("locked"):
            L.clear(lay)
            self._last_label = ""
            self.commit("Quitar licuado")
            self.canvas.viewport().update()
            self._fill_props()

    def funny_face(self, preset: str) -> bool:
        """😜 Cara graciosa de un clic sobre la cara más grande de lo elegido (un paso de deshacer)."""
        from ..ai import funny_faces as FF
        from PySide6.QtWidgets import QApplication
        lay = self.cur()
        if lay is None or lay.get("locked") or lay["kind"] != "image":
            self.statusBar().showMessage("Elige una imagen con una cara.", 5000)
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            inten, todas = FF.ajustes()
            ok = FF.apply(lay, preset, T._image_content(lay), intensity=inten, all_faces=todas)
        except Exception as ex:  # noqa: BLE001 - sin modelo de caras (sin internet la 1.ª vez)
            ok = False
            self.statusBar().showMessage(f"No pude buscar la cara: {ex}"[:160], 8000)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.statusBar().showMessage("No encontré ninguna cara en esta imagen.", 6000)
            return False
        self._last_label = ""
        self.commit(dict((k, n) for k, n, _t in FF.PRESETS).get(preset, "Cara graciosa")[2:])
        self.canvas.viewport().update()
        self._fill_props()
        return True

    def _liquify_props(self, lay):
        from PySide6.QtWidgets import QButtonGroup
        from ..ai import funny_faces as FF
        box = QGroupBox("≈ Licuar")
        g = QGridLayout(box)
        grp = QButtonGroup(box)
        tips = {"inflar": "Inflar: agranda lo que hay bajo el pincel (mantén pulsado para más)",
                "encoger": "Encoger: achica lo que hay bajo el pincel",
                "empujar": "Estirar: agarra lo del círculo y llévalo con el ratón (lo de alrededor se estira)",
                "restaurar": "Restaurar: devuelve a su forma lo que pintes"}
        for i, (mode, label) in enumerate((("inflar", "⊕ Inflar"), ("encoger", "⊖ Encoger"),
                                           ("empujar", "✋ Estirar"), ("restaurar", "↺ Restaurar"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tips[mode])
            b.setChecked(self.canvas.tool == "liquify" and self.canvas.liq_mode == mode)
            b.clicked.connect(lambda _=False, m=mode: self.set_liq_mode(m))
            grp.addButton(b)
            g.addWidget(b, i // 2, i % 2)
        size = QSpinBox()
        size.setRange(5, 400)
        size.setSuffix(" px")
        size.setValue(self.canvas.brush)
        size.setToolTip("Tamaño del pincel (radio, en píxeles de la miniatura)")
        size.valueChanged.connect(lambda v: setattr(self.canvas, "brush", v))
        force = QSlider(Qt.Horizontal)
        force.setRange(5, 100)
        force.setValue(int(self.canvas.liq_strength * 100))
        force.setToolTip("Fuerza del pincel")
        force.valueChanged.connect(lambda v: setattr(self.canvas, "liq_strength", v / 100))
        g.addWidget(QLabel("Tamaño"), 2, 0)
        g.addWidget(size, 2, 1)
        g.addWidget(QLabel("Fuerza"), 3, 0)
        g.addWidget(force, 3, 1)
        if lay["kind"] == "image":
            from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QTabWidget, QWidget
            inten, todas = FF.ajustes()
            fila = QHBoxLayout()
            fila.addWidget(QLabel("Intensidad:"))
            ig = QButtonGroup(box)
            for txt, val in FF.INTENSIDADES:
                ib = QPushButton(txt)
                ib.setCheckable(True)
                ib.setChecked(abs(val - inten) < 1e-6)
                ib.setToolTip(f"Intensidad {txt.lower()}: multiplica la fuerza y el desplazamiento de las caras")
                ib.clicked.connect(lambda _=False, v=val: FF.guardar("miniatura/caras_intensidad", v))
                ig.addButton(ib)
                fila.addWidget(ib)
            g.addLayout(fila, 4, 0, 1, 2)
            chk = QCheckBox("Todas las caras")
            chk.setChecked(todas)
            chk.setToolTip("Aplica la cara graciosa a todas las caras de la imagen, no solo a la más grande")
            chk.toggled.connect(lambda v: FF.guardar("miniatura/caras_todas", bool(v)))
            g.addWidget(chk, 5, 0, 1, 2)
            etiq = {k: (lb, tp) for k, lb, tp in FF.PRESETS}
            tabs = QTabWidget()
            for titulo, claves in FF.GROUPS:
                pag = QWidget()
                rej = QGridLayout(pag)
                for i, key in enumerate(claves):
                    lb, tp = etiq[key]
                    b = QPushButton(lb)
                    b.setToolTip(tp + " (busca la cara o caras de la imagen; Ctrl+Z lo deshace)")
                    b.clicked.connect(lambda _=False, k=key: self.funny_face(k))
                    rej.addWidget(b, i // 2, i % 2)
                tabs.addTab(pag, titulo)
            g.addWidget(tabs, 6, 0, 1, 2)
        off = QPushButton("↺ Quitar licuado")
        off.setToolTip("Devuelve lo elegido a su forma original")
        off.setEnabled(bool(lay.get("liquify")))
        off.clicked.connect(self.liquify_reset)
        self._liq_off = off                 # (al soltar, liquify_done solo lo habilita: sin rehacer el panel)
        g.addWidget(off, 7, 0, 1, 2)
        self.props_lay.addWidget(box)

    def reset_warp(self):
        lay = self.cur()
        if lay and T.warp_of(lay) and not lay.get("locked"):
            lay.pop("warp", None)
            self._last_label = ""
            self.commit("Quitar deformación")
            self.canvas.viewport().update()

    def fill_canvas(self, lay: dict | None = None):
        """⛶ La imagen cubre toda la miniatura, centrada (sin girar)."""
        lay = lay or self.cur()
        if not lay or lay.get("locked"):
            return
        _img, cw, ch = T.render_layer(lay)
        d = self.doc
        lay.update(scale=round(max(d["w"] / max(1, cw), d["h"] / max(1, ch)), 4), x=d["w"] / 2, y=d["h"] / 2,
                   rotation=0.0)
        self._last_label = ""
        self.commit("Llenar el lienzo")
        self.canvas.viewport().update()
        self._fill_props()

    def delete_layer(self):
        lay = self.cur()
        if lay and len(self.selected_layers()) > 1:          # varias elegidas (Mayús+clic): todas
            ids = {l["id"] for l in self.selected_layers()}
            self.doc["layers"] = [l for l in self.doc["layers"] if l["id"] not in ids]
            self.canvas.sel = ""
            self.canvas.multi.clear()
            self._last_label = ""
            self.commit("Borrar")
            self.canvas.viewport().update()
            self._fill_props()
            return
        if lay and not lay.get("locked"):
            self.doc["layers"].remove(lay)
            self.canvas.sel = ""
            self._last_label = ""
            self.commit("Borrar")
            self.canvas.viewport().update()
            self._fill_props()

    def selected_layers(self) -> list[dict]:
        """Las capas elegidas que se pueden tocar: las de Mayús+clic, o la elegida."""
        ids = set(self.canvas.multi) | ({self.canvas.sel} if self.canvas.sel else set())
        if self.canvas.sel and self.canvas.sel not in self.canvas.multi:
            ids = {self.canvas.sel}
        return [l for l in self.doc["layers"] if l["id"] in ids and not l.get("locked")]

    def edit_text(self, lay: dict, palabra: int | None = None):
        """Doble clic en un texto del lienzo: el cuadro para escribirlo, con la palabra (o todo el texto) elegida."""
        self.canvas.sel = lay["id"]
        self._fill_props()
        ed = getattr(self, "_text_edit", None)
        try:
            if ed is not None:
                ed.setFocus()
                spans = T.word_spans(lay.get("text", ""))
                if palabra is not None and palabra < len(spans):
                    self._select_in_box(ed, spans[palabra][0], spans[palabra][1])
                else:
                    ed.selectAll()
        except RuntimeError:
            pass

    @staticmethod
    def _select_in_box(ed, a: int, b: int):
        """Marca [a, b) en el cuadro de texto sin que eso cambie las palabras elegidas en el lienzo."""
        cur = ed.textCursor()
        cur.setPosition(a)
        cur.setPosition(b, QTextCursor.KeepAnchor)
        ed.blockSignals(True)
        ed.setTextCursor(cur)
        ed.blockSignals(False)

    def _box_selection(self, ed, lay: dict):
        """Lo que marcas en el cuadro de texto queda elegido en el lienzo."""
        if self._loading or self.canvas.sel != lay.get("id"):
            return
        cur = ed.textCursor()
        self.canvas.set_words(T.words_in_span(ed.toPlainText(), cur.selectionStart(), cur.selectionEnd())
                              if cur.hasSelection() else set(), lay, panel=False)

    def _set_text(self, lay: dict, nuevo: str):
        """Reescribir el texto: cada estilo propio sigue a su palabra."""
        kv = {"text": nuevo, "name": nuevo[:20]}
        if lay.get("word_styles"):
            kv["word_styles"] = T.remap_word_styles(lay.get("text", ""), nuevo, lay["word_styles"])
        self._set(lay, "Texto", **kv)

    def select_all(self):
        """Ctrl+A: todas las capas visibles (para moverlas o borrarlas juntas)."""
        ids = [l["id"] for l in self.doc["layers"] if l.get("visible", True) and not l.get("locked")]
        if not ids:
            return
        self.canvas.multi = set(ids)
        self.canvas.sel = ids[-1]
        self.canvas.selected.emit(ids[-1])
        self.canvas.viewport().update()
        self.statusBar().showMessage(f"{len(ids)} capas elegidas · arrastra para moverlas juntas · Supr las borra", 5000)

    def duplicate_here(self, lay: dict) -> dict:
        """Alt+arrastrar: una copia justo encima (en el mismo sitio); se arrastra la copia."""
        c = T.clone(lay)
        c["x"], c["y"] = lay["x"], lay["y"]
        L = self.doc["layers"]
        L.insert(L.index(lay) + 1, c)
        self.canvas.sel = c["id"]
        return c

    # ----------------------------------------------------------- 🌫 fondo desenfocado detrás
    def blur_background(self, lay: dict | None = None):
        """La misma imagen, llenando la miniatura, desenfocada y oscura, DETRÁS de lo elegido: el sujeto resalta."""
        lay = lay or self.cur()
        if not lay or lay["kind"] != "image":
            return
        bg = copy.deepcopy(lay)
        bg["id"] = __import__("uuid").uuid4().hex[:10]
        bg["name"] = "Fondo desenfocado"
        for k in ("mask", "liquify", "warp"):
            bg.pop(k, None)
        for k in ("outline", "shadow", "glow"):
            if isinstance(bg.get(k), dict):
                bg[k]["on"] = False
        bg["locked"] = False
        bg["opacity"] = 1.0
        bg["adj"] = dict(bg.get("adj") or {}, blur=0.4, exposure=-0.45, saturation=-0.1, vignette=0.45)
        _img, cw, ch = T.render_layer(bg)
        d = self.doc
        bg.update(scale=round(max(d["w"] / max(1, cw), d["h"] / max(1, ch)) * 1.02, 4), x=d["w"] / 2, y=d["h"] / 2,
                  rotation=0.0)
        L = d["layers"]
        L.insert(L.index(lay), bg)
        self._last_label = ""
        self.commit("Fondo desenfocado")
        self.canvas.viewport().update()
        self._fill_props()

    # ----------------------------------------------------------- 📐 plantillas propias
    @staticmethod
    def templates_dir() -> str:
        from ..core.paths import app_data_dir
        d = os.path.join(str(app_data_dir()), "plantillas_miniatura")
        os.makedirs(d, exist_ok=True)
        return d

    def templates(self, fmt: str | None = None) -> list[tuple[str, str]]:
        """[(nombre, ruta)] de las plantillas guardadas de ese formato, las últimas primero."""
        fmt = fmt or self.doc["format"]
        out = []
        for f in sorted(os.listdir(self.templates_dir()), key=lambda n: -os.path.getmtime(
                os.path.join(self.templates_dir(), n))):
            if f.endswith(".json"):
                try:
                    t = json.load(open(os.path.join(self.templates_dir(), f), encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if t.get("format") == fmt:
                    out.append((t.get("name") or f[:-5], os.path.join(self.templates_dir(), f)))
        return out

    def save_template(self, name: str, slots: bool = False) -> str:
        """Guarda la composición. slots: las imágenes (no los PNG de adorno) quedan como 🖼 huecos donde poner otras."""
        import re
        name = name.strip() or "Plantilla"
        slug = re.sub(r"[^\w\- ]+", "", name).strip()[:60] or "plantilla"
        path = os.path.join(self.templates_dir(), f"{slug}.json")
        doc = copy.deepcopy(self.doc)
        capas = []
        for l in doc["layers"]:
            if l.get("kind") == "image" and not l.get("blur_area"):
                if slots and not l.get("element"):
                    l = T.slot_from(l)
                else:
                    l["box"] = [round(v, 1) for v in T.box_size(l)]   # (si un día falta la imagen: hueco de su tamaño)
            capas.append(l)
        doc["layers"] = capas
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"name": name, "format": doc["format"], "doc": doc}, fh, ensure_ascii=False)
        try:
            T.render(doc, 320 / doc["w"]).save(path[:-5] + ".png")
        except Exception:  # noqa: BLE001 - sin vista previa, la plantilla sirve igual
            pass
        self.statusBar().showMessage(f"📐 Plantilla «{name}» guardada", 5000)
        return path

    def use_template(self, path: str) -> int:
        """La composición de la plantilla en esta miniatura (las imágenes que ya no existen se saltan)."""
        t = json.load(open(path, encoding="utf-8"))
        doc = t["doc"]
        layers, faltan = [], 0
        for l in doc.get("layers", []):
            if l.get("kind") == "image" and not os.path.exists(l.get("path", "")):
                faltan += 1
                if l.get("box"):                         # 🖼 la imagen ya no está: queda un hueco de su tamaño
                    layers.append(T.slot_from({**l, "id": __import__("uuid").uuid4().hex[:10]}, tuple(l["box"])))
                continue
            c = copy.deepcopy(l)
            c.pop("box", None)
            c["id"] = __import__("uuid").uuid4().hex[:10]
            layers.append(c)
        self.doc["layers"] = layers
        if doc.get("bg"):
            self.doc["bg"] = copy.deepcopy(doc["bg"])
        self.canvas.sel = ""
        self.canvas.multi.clear()
        self._last_label = ""
        self.commit("Usar plantilla")
        self.canvas.viewport().update()
        self._fill_props()
        huecos = sum(1 for l in layers if l.get("slot"))
        self.statusBar().showMessage(f"📐 Plantilla «{t.get('name', '')}»" + (
            f" ({faltan} imagen(es) ya no estaban en tu PC)" if faltan else "") + (
            f" · 🖼 {huecos} hueco(s): suelta una imagen en cada uno" if huecos else "") + " · Ctrl+Z la quita", 8000)
        return len(layers)

    def _templates_menu(self, menu):
        from PySide6.QtWidgets import QInputDialog
        menu.clear()
        menu.addAction("💾 Guardar esta miniatura como plantilla…", lambda: (
            lambda r: self.save_template(r[0]) if r[1] and r[0].strip() else None)(
            QInputDialog.getText(self, "Plantilla", "Nombre de la plantilla:")))
        a = menu.addAction("🖼 Guardar como plantilla con huecos…", lambda: (
            lambda r: self.save_template(r[0], slots=True) if r[1] and r[0].strip() else None)(
            QInputDialog.getText(self, "Plantilla con huecos", "Nombre de la plantilla:")))
        a.setToolTip("Las imágenes quedan como huecos: al usarla, sueltas tus imágenes en ellos y toman su tamaño, "
                     "sitio y efectos; los textos y formas se quedan")
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        ts = self.templates()
        if not ts:
            a = menu.addAction("(todavía no hay plantillas de este formato)")
            a.setEnabled(False)
        for name, path in ts[:30]:
            png = path[:-5] + ".png"
            a = menu.addAction(QIcon(png) if os.path.exists(png) else QIcon(), name, lambda p=path: self.use_template(p))
            a.setToolTip("Usar esta composición (Ctrl+Z la quita)")
        menu.addSeparator()
        menu.addAction("📂 Abrir la carpeta de plantillas", lambda: os.startfile(self.templates_dir()))   # noqa: S606

    # ----------------------------------------------------------- 📱 de YouTube a Short
    def to_short(self, ask: bool = True) -> bool:
        """La miniatura de YouTube recolocada en vertical (1080×1920) como punto de partida para la del Short."""
        if self.doc["format"] != "youtube" or not self.doc["layers"]:
            return False
        p = self.ctrl.project
        if ask and p.thumbnails.get("short") and p.thumbnails["short"].get("layers"):
            r = QMessageBox.question(self, "Pasar a Short", "Ya tienes una miniatura de Short. ¿La cambio por la "
                                                             "versión vertical de esta? (Ctrl+Z en el Short la recupera)")
            if r != QMessageBox.StandardButton.Yes:
                return False
        W, H = self.doc["w"], self.doc["h"]
        sh = T.new_doc("short")
        SW, SH = sh["w"], sh["h"]
        sh["bg"] = copy.deepcopy(self.doc.get("bg") or sh["bg"])
        k = SW / W
        for lay in self.doc["layers"]:
            c = copy.deepcopy(lay)
            bb = self.canvas._box(lay).boundingRect()
            if bb.width() >= W * 0.9 and bb.height() >= H * 0.9:    # un fondo: que llene el vertical
                f = max(SW / max(1.0, bb.width()), SH / max(1.0, bb.height()))
                c.update(scale=round(float(c["scale"]) * f, 4), x=SW / 2, y=SH / 2)
            else:                                                    # lo demás, en la franja central
                c.update(scale=round(float(c["scale"]) * k, 4), x=round(float(c["x"]) * k, 1),
                         y=round(SH / 2 + (float(c["y"]) - H / 2) * k, 1))
            sh["layers"].append(c)
        old = p.thumbnails.get("short")
        p.thumbnails["short"] = sh
        self.fmt.setCurrentIndex(self.fmt.findData("short"))          # (abre la del Short)
        if old and old.get("layers"):
            self.history = [json.dumps(old), json.dumps(sh)]
            self.pos = 1
        self.statusBar().showMessage("📱 Versión Short creada a partir de la de YouTube: recoloca lo que haga falta", 7000)
        return True

    def delete_all(self):
        keep = [l for l in self.doc["layers"] if l.get("locked")]
        if len(keep) == len(self.doc["layers"]):
            return
        self.doc["layers"] = keep
        self.canvas.sel = ""
        self._last_label = ""
        self.commit("Eliminar todo")
        self.canvas.viewport().update()
        self._fill_props()
        self.statusBar().showMessage("Se quitaron todas las capas" + (" (menos las bloqueadas)" if keep else "")
                                     + ". Ctrl+Z las recupera.", 6000)

    def arrange(self, d: int):
        lay = self.cur()
        if not lay:
            return
        L = self.doc["layers"]
        i = L.index(lay)
        j = max(0, min(len(L) - 1, i + d))
        L.insert(j, L.pop(i))
        self._last_label = ""
        self.commit("Ordenar")
        self.canvas.viewport().update()

    def align(self, how: str):
        lay = self.cur()
        if not lay or lay.get("locked"):
            return
        br = self.canvas._box(lay).boundingRect()
        W, H = self.doc["w"], self.doc["h"]
        m = 0.05 * min(W, H)
        if how == "ch":
            lay["x"] = W / 2
        elif how == "cv":
            lay["y"] = H / 2
        elif how == "l":
            lay["x"] += m - br.left()
        elif how == "r":
            lay["x"] += (W - m) - br.right()
        elif how == "t":
            lay["y"] += m - br.top()
        elif how == "b":
            lay["y"] += (H - m) - br.bottom()
        self._last_label = ""
        self.commit("Alinear")
        self.canvas.viewport().update()

    def toggle_visible(self):
        lay = self.cur()
        if lay:
            lay["visible"] = not lay.get("visible", True)
            self._last_label = ""
            self.commit("Mostrar / ocultar")
            self.canvas.viewport().update()

    def toggle_lock(self):
        lay = self.cur()
        if lay:
            lay["locked"] = not lay.get("locked")
            self._last_label = ""
            self.commit("Bloquear")
            self.canvas.viewport().update()

    BLUR_DEFAULT = 12

    def toggle_blur(self, lay: dict | None = None) -> bool:
        """🌫 Desenfocar la capa entera (clic derecho) o quitarle el desenfoque. La fuerza se ajusta en el panel
        («Desenfoque»). Un paso de deshacer."""
        lay = lay or self.cur()
        if lay is None or lay.get("locked"):
            return False
        on = float(lay.get("blur", 0) or 0) > 0
        self._last_label = ""
        self._set(lay, "Quitar desenfoque" if on else "Desenfocar", blur=0 if on else self.BLUR_DEFAULT)
        self._fill_props()
        self.canvas.viewport().update()
        return True

    def _bg_changed(self, *_):
        if self._loading:
            return
        t = self.bg_type.currentData()
        self.doc["bg"] = ({"type": "color", "color": self.bg_c1._c} if t == "color" else
                          {"type": "gradient", "c1": self.bg_c1._c, "c2": self.bg_c2._c, "angle": self.bg_angle.value()})
        self.commit("Fondo")
        self.canvas.viewport().update()

    def _change_format(self, _i):
        fmt = self.fmt.currentData()
        if fmt == self.doc["format"]:
            return
        self._save()
        p = self.ctrl.project
        self.doc = copy.deepcopy(p.thumbnails[fmt]) if p.thumbnails.get(fmt) else T.new_doc(fmt)
        self.history, self.pos = [json.dumps(self.doc)], 0
        self.canvas.sel = ""
        self.refresh_all()
        self._ab_update()

    # ----------------------------------------------------------- ⚖ A y B
    @property
    def _ab(self) -> dict:
        """⚖ A y B por formato ({"youtube": {"A": json, "B": json}}), guardados CON el proyecto (no se pierden al
        cerrar Reclaimer)."""
        return self.ctrl.project.thumbnails.setdefault("ab", {})

    def ab_save(self, which: str):
        """Guarda una copia de la miniatura actual como A o B (de este formato; se guarda con el proyecto)."""
        self._ab.setdefault(self.doc["format"], {})[which] = json.dumps(self.doc)
        self.ctrl._set_media_dirty()
        self._ab_update()
        self.statusBar().showMessage(f"📸 {which} guardada · «⚖ Comparar A/B» las pone una frente a otra", 5000)

    def ab_clear(self):
        self._ab.pop(self.doc["format"], None)
        self.ctrl._set_media_dirty()
        self._ab_update()
        self.statusBar().showMessage("A y B borradas", 4000)

    def _ab_update(self):
        par = self._ab.get(self.doc["format"], {})
        self.act_ab_side.setEnabled("A" in par and "B" in par)
        self.act_ab_clear.setEnabled(bool(par))

    def ab_compare(self):
        from .thumb_compare import CompareDialog
        par = self._ab.get(self.doc["format"], {})
        if "A" not in par or "B" not in par:
            return
        dlg = CompareDialog(self, par["A"], par["B"], self._title(), self.use_ab)
        dlg.exec()

    def use_ab(self, which: str) -> bool:
        """Pone la versión A o B en la miniatura (Ctrl+Z vuelve a lo de antes)."""
        snap = self._ab.get(self.doc["format"], {}).get(which)
        if not snap:
            return False
        self.doc = json.loads(snap)
        self.canvas.sel = ""
        self.canvas.multi.clear()
        self._last_label = ""
        self.commit(f"Quedarme con {which}")
        self.refresh_all()
        self.statusBar().showMessage(f"⚖ Te quedas con {which} · Ctrl+Z vuelve a la anterior", 6000)
        return True

    # ----------------------------------------------------------- recorte del sujeto
    def to_source(self, lay: dict, pt: QPointF) -> tuple[float, float]:
        """Un punto del lienzo → píxel de la imagen ORIGINAL de esa capa (para recuadros y pincel)."""
        return self._to_source_many(lay, [pt])[0]

    def _to_source_many(self, lay: dict, pts: list) -> list[tuple[float, float]]:
        """to_source de muchos puntos. ⚡ Antes abría la imagen entera POR CADA punto del trazo: decenas de segundos."""
        img, cw, ch = self.canvas._render(lay)
        inv, _ok = T.layer_transform(lay, img).inverted()
        k = T.image_k(img)                                          # (la imagen dibujada puede ir reducida)
        sz = QImageReader(lay["path"]).size()
        x0, y0 = lay["crop"][0] * sz.width(), lay["crop"][1] * sz.height()
        mx, my = (img.width() - cw) / 2, (img.height() - ch) / 2
        out = []
        for pt in pts:
            q = inv.map(pt)
            out.append((x0 + (q.x() - mx) / k, y0 + (q.y() - my) / k))
        return out

    def _bg_job(self, fn, done, label):
        from .jobs import BackgroundJob
        if self.job is not None:
            return
        self.statusBar().showMessage(label)
        self.job = BackgroundJob(lambda _p, _c: fn(), self)
        self.job.done.connect(lambda r: (setattr(self, "job", None), done(r)))
        self.job.failed.connect(lambda m: (setattr(self, "job", None),
                                           self.statusBar().showMessage("✗ " + m, 8000)))
        self.job.start()

    # ----------------------------------------------------------- 🪄 combinar con lo de abajo
    def _combine_props(self, lay):
        box = QGroupBox("🪄 Combinar con lo de abajo")
        g = QGridLayout(box)
        below = self.doc["layers"].index(lay) > 0
        force = _SliderNum(0, 1, getattr(self, "_comb_strength", 0.6), 100, suffix=" %")
        force.setToolTip("Cuánto se adapta a lo de abajo")
        force.applied.connect(lambda v: setattr(self, "_comb_strength", v))
        g.addWidget(QLabel("Fuerza"), 0, 0)
        g.addWidget(force, 0, 1)
        for i, (mode, label, tip) in enumerate((
                ("integrar", "🪄 Integrar", "Toma la luz, las sombras, el tono y el grano de lo que tiene debajo y "
                                           "suaviza su borde: deja de parecer pegado."),
                ("fundir", "🫥 Fundir", "Además la mezcla con lo de abajo (clonado sin costuras): queda como impresa "
                                       "en la piel o en la escena."))):
            b = QPushButton(label)
            b.setToolTip(tip + " Sale como capa nueva; la original queda oculta debajo. Ctrl+Z lo deshace.")
            b.setEnabled(below and not lay.get("locked"))
            b.clicked.connect(lambda _=False, m=mode: self.combine_layer(m))
            g.addWidget(b, 1, i)
        if not below:
            box.setToolTip("No hay nada debajo con que combinarla")
        self.props_lay.addWidget(box)

    def combine_layer(self, mode: str) -> bool:
        """🪄 La capa elegida, integrada con lo que tiene debajo (sale como capa nueva; la original, oculta)."""
        from ..ai import combine as C
        from ..core.paths import cache_dir
        from PySide6.QtWidgets import QApplication
        import hashlib
        import numpy as np
        lay = self.cur()
        if lay is None or lay.get("locked") or lay["kind"] != "image":
            return False
        i = self.doc["layers"].index(lay)
        if i == 0:
            self.statusBar().showMessage("No hay nada debajo con que combinarla.", 5000)
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            below = T.qimage_to_rgba(T.render(dict(self.doc, layers=self.doc["layers"][:i]), 1.0))[..., :3]
            top = T.qimage_to_rgba(T.render_alone(self.doc, lay))
            res = C.combine(top, below, mode, float(getattr(self, "_comb_strength", 0.6)))
        finally:
            QApplication.restoreOverrideCursor()
        ys, xs = np.nonzero(res[..., 3] > 2)
        if len(xs) == 0:
            self.statusBar().showMessage("Esa capa no se ve en la miniatura.", 5000)
            return False
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        crop = np.ascontiguousarray(res[y0:y1, x0:x1])
        path = os.path.join(str(cache_dir("miniaturas_material")),
                            f"comb_{hashlib.md5(crop.tobytes()).hexdigest()[:14]}.png")
        T.rgba_to_qimage(crop).save(path)
        new = T.image_layer(path, self.doc, (lay["name"] + " (combinada)")[:30])
        new.update(x=float(x0 + x1) / 2, y=float(y0 + y1) / 2, scale=1.0)
        if lay.get("element"):
            new["element"] = True
        lay["visible"] = False                                   # (la original se queda debajo, oculta)
        self.doc["layers"].insert(i + 1, new)
        self.canvas.sel = new["id"]
        self._sel_prev = new["id"]
        self._last_label = ""
        self.commit("Combinar" if mode == "integrar" else "Fundir")
        self.canvas.viewport().update()
        self._fill_props()
        self.statusBar().showMessage("🪄 Combinada con lo de abajo (la original queda oculta en «Capas»).", 6000)
        return True

    # ----------------------------------------------------------- ⇱ mejorar resolución (upscale)
    MAX_UPSCALE_PX = 40_000_000

    def _upscale_props(self, lay):
        from PySide6.QtGui import QImageReader
        sz = QImageReader(lay["path"]).size()      # solo la cabecera: QImage(path) decodificaba el PNG entero (~140 ms)
        w, h = (sz.width(), sz.height()) if sz.isValid() else (0, 0)
        box = QGroupBox("⇱ Resolución")
        g = QGridLayout(box)
        k = float(lay.get("scale", 1.0))
        info = QLabel(f"{w}×{h} px · se ve a ×{k:.1f}" + ("  ⚠ borrosa" if k > 1.3 else ""))
        info.setToolTip("Tamaño real de la imagen y cuánto se agranda en la miniatura. Por encima de ×1.3 se nota "
                        "borrosa: mejora su resolución.")
        g.addWidget(info, 0, 0, 1, 2)
        for i, f in enumerate((2, 4)):
            b = QPushButton(f"⇱ Mejorar ×{f}")
            b.setToolTip(f"Agranda la imagen ×{f} con IA (más nítida que estirarla), en tu PC y sin tarjeta gráfica. "
                         "Se ve igual de grande en el lienzo, pero con más detalle. Ctrl+Z lo deshace.")
            b.setEnabled(w * h * f * f <= self.MAX_UPSCALE_PX and self.job is None)
            b.clicked.connect(lambda _=False, f=f: self.upscale_image(f))
            g.addWidget(b, 1, i)
        from PySide6.QtWidgets import QProgressBar
        self.up_bar = QProgressBar()                      # 0–100 % mientras se mejora (se ve solo entonces)
        self.up_bar.setRange(0, 100)
        self.up_bar.setFormat("%p %")
        self.up_bar.setValue(getattr(self, "_up_pct", None) or 0)
        self.up_bar.setVisible(getattr(self, "_up_pct", None) is not None)
        g.addWidget(self.up_bar, 2, 0, 1, 2)
        self.props_lay.addWidget(box)

    def _upscale_progress(self, frac: float, msg: str):
        pct = max(0, min(100, int(round(frac * 100))))
        self._up_pct = pct
        for bar in (getattr(self, "up_bar", None), getattr(self, "up_bar_status", None)):
            try:
                if bar is not None:
                    bar.setValue(pct)
                    bar.setVisible(True)
            except RuntimeError:                          # (el panel se rehízo: su barra ya no existe)
                pass
        self.statusBar().showMessage(msg)

    def _upscale_end(self):
        self._up_pct = None
        for bar in (getattr(self, "up_bar", None), getattr(self, "up_bar_status", None)):
            try:
                if bar is not None:
                    bar.setVisible(False)
            except RuntimeError:
                pass

    def upscale_image(self, factor: int):
        """⇱ Mejorar resolución ×2/×4 del archivo de la capa (sin recortes ni ajustes: se aplican después)."""
        from ..ai import upscale as U
        from ..core.paths import cache_dir
        from .jobs import BackgroundJob
        import hashlib
        lay = self.cur()
        if lay is None or lay["kind"] != "image" or lay.get("locked") or self.job is not None:
            return
        lid, path = lay["id"], lay["path"]
        rgba = T.qimage_to_rgba(QImage(path))
        h, w = rgba.shape[:2]
        if w * h * factor * factor > self.MAX_UPSCALE_PX:
            self.statusBar().showMessage("Esa imagen ya es muy grande para agrandarla más.", 6000)
            return
        folder = str(cache_dir("miniaturas_material"))
        out = os.path.join(folder, f"x{factor}_{hashlib.md5(rgba.tobytes()).hexdigest()[:14]}.png")

        def work(progress, cancelled):
            if not os.path.exists(out):
                big = U.upscale(rgba, factor, lambda f, m: progress(f, m), cancelled)
                T.rgba_to_qimage(big).save(out)
            return out

        if getattr(self, "up_bar_status", None) is None:        # la barra de abajo (se ve aunque elijas otra capa)
            from PySide6.QtWidgets import QProgressBar
            self.up_bar_status = QProgressBar()
            self.up_bar_status.setRange(0, 100)
            self.up_bar_status.setFormat("⇱ %p %")
            self.up_bar_status.setFixedWidth(220)
            self.statusBar().addPermanentWidget(self.up_bar_status)
        self._upscale_progress(0.0, f"⇱ Mejorando la resolución ×{factor}… ({U.kind_for(w, h).upper()})")
        self.job = BackgroundJob(work, self)
        self.job.progress.connect(self._upscale_progress)
        self.job.done.connect(lambda p: (self._upscale_end(), self._upscaled(lid, p, factor)))
        self.job.failed.connect(lambda m: (setattr(self, "job", None), self._upscale_end(),
                                           self.statusBar().showMessage("✗ No se pudo mejorar: " + m[:120], 8000)))
        self.job.start()
        self._fill_props()

    def _upscaled(self, lid: str, path: str, factor: int):
        self.job = None
        lay = self.layer(lid)
        if lay is None:
            return
        lay["path"] = path
        lay["scale"] = round(float(lay.get("scale", 1.0)) / factor, 5)   # (se ve igual de grande, con más detalle)
        self._last_label = ""
        self.commit(f"Mejorar resolución ×{factor}")
        self.canvas.viewport().update()
        self._refresh_layers()
        self._fill_props()
        img = QImage(path)
        self.statusBar().showMessage(f"✓ Resolución mejorada: ahora {img.width()}×{img.height()} px", 8000)

    def cutout_auto(self):
        lay = self.cur()
        if not lay or lay["kind"] != "image":
            return
        from ..ai import bg_removal as BR
        path = lay["path"]
        self._bg_job(lambda: BR.remove(path), lambda m: self._set_mask(lay["id"], m, "Quitar fondo"),
                     "✂ Quitando el fondo… (la primera vez se prepara el modelo)")

    # ----------------------------------------------------------- 🌫 zona borrosa
    def start_blur_zone(self, shape: str = "rect"):
        """🌫 Borroso ▾: arrastra sobre el lienzo el círculo o el cuadrado que va a desenfocar (Mayús = perfecto)."""
        if self.act_liq.isChecked():
            self.toggle_liquify(False)
        self.canvas.multi.clear()
        self.canvas.tool = "blurzone"
        self.canvas.blur_shape = shape
        self.canvas.setCursor(Qt.CrossCursor)
        self._sync_tools()
        self.statusBar().showMessage("Arrastra sobre el lienzo: se crea la zona borrosa (Mayús = "
                                     + ("círculo" if shape == "ellipse" else "cuadrado") + " perfecto)", 8000)

    def blur_zone_done(self, r: QRectF):
        """Al soltar: la zona con ese tamaño y sitio (sin arrastrar: una de tamaño normal centrada en el clic)."""
        shape = self.canvas.blur_shape
        self.canvas.tool = None
        self.canvas.unsetCursor()
        self._sync_tools()
        if r.width() < 6 or r.height() < 6:
            c = r.center()
            r = QRectF(c.x() - self.doc["w"] * 0.125, c.y() - self.doc["h"] * 0.125,
                       self.doc["w"] * 0.25, self.doc["h"] * 0.25)
        lay = T.blur_area_layer(self.doc, shape, r.center().x(), r.center().y(), r.width(), r.height())
        self._add(lay, "Zona borrosa")
        self.statusBar().showMessage("Zona borrosa creada: estírala con sus asas · «Fuerza» en el panel", 6000)

    def start_box(self):
        self.canvas.tool = "box"
        self.canvas.setCursor(Qt.CrossCursor)
        self._sync_tools()
        self.statusBar().showMessage("Dibuja un recuadro alrededor de lo que quieres conservar.")

    def cutout_box(self, r: QRectF):
        self.canvas.tool = None
        self.canvas.unsetCursor()
        self._sync_tools()
        lay = self.cur()
        if not lay or lay["kind"] != "image" or r.width() < 6 or r.height() < 6:
            return
        from ..ai import bg_removal as BR
        src = QImage(lay["path"])
        pts = [self.to_source(lay, c) for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight())]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        box = (max(0, min(xs)) / src.width(), max(0, min(ys)) / src.height(),
               min(src.width(), max(xs)) / src.width(), min(src.height(), max(ys)) / src.height())
        path = lay["path"]
        self._bg_job(lambda: BR.remove(path, box), lambda m: self._set_mask(lay["id"], m, "Recortar sujeto"),
                     "✂ Recortando lo que marcaste…")

    def set_brush(self, mode: str | None):
        if hasattr(self, "act_liq"):
            self.act_liq.setChecked(False)
        self.canvas.tool = mode
        self.canvas.setCursor(Qt.BlankCursor if mode else Qt.ArrowCursor)
        self._sync_tools()
        if mode:
            self.statusBar().showMessage("Pinta sobre la imagen para " + ("borrar" if mode == "erase" else "recuperar")
                                         + ". Vuelve a pulsar el botón para terminar.")
        self._fill_props()

    def brush_stroke(self, pts: list, restore: bool):
        lay = self.cur()
        if not lay or lay["kind"] != "image" or not pts:
            return
        radius = self.canvas.brush / max(lay["scale"], 1e-3)
        self._brush_q.append((lay["id"], self._to_source_many(lay, pts), radius, restore, restore and self.brush_smart(),
                              self.brush_opt("hard"), self.brush_opt("alpha")))
        self._brush_next()

    def brush_busy(self) -> bool:
        return self._brush_job is not None or bool(self._brush_q)

    @staticmethod
    def brush_smart() -> bool:
        from PySide6.QtCore import QSettings
        return str(QSettings("EditorIA", "EditorIA").value("miniatura/recuperar_sujeto", "true")).lower() == "true"

    @staticmethod
    def set_brush_smart(on: bool):
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue("miniatura/recuperar_sujeto", "true" if on else "false")

    BRUSH_OPTS = {"hard": ("miniatura/pincel_dureza", 1.0, 0.0), "alpha": ("miniatura/pincel_opacidad", 1.0, 0.05)}

    def brush_opt(self, name: str) -> float:
        """🖌 Dureza (1 = borde nítido) u opacidad (1 = del todo) del pincel; se recuerdan entre sesiones."""
        memo = self.__dict__.setdefault("_brush_opts", {})
        if name not in memo:
            from PySide6.QtCore import QSettings
            clave, defecto, minimo = self.BRUSH_OPTS[name]
            try:
                memo[name] = max(minimo, min(1.0, float(QSettings("EditorIA", "EditorIA").value(clave, defecto))))
            except (TypeError, ValueError):
                memo[name] = defecto
        return memo[name]

    def set_brush_opt(self, name: str, v: float):
        from PySide6.QtCore import QSettings
        clave, _defecto, minimo = self.BRUSH_OPTS[name]
        v = max(minimo, min(1.0, float(v)))
        self.__dict__.setdefault("_brush_opts", {})[name] = v
        QSettings("EditorIA", "EditorIA").setValue(clave, v)

    def _brush_next(self):
        """Los trazos se aplican en segundo plano y en orden: se puede seguir pintando sin esperar."""
        if self._brush_job is not None or not self._brush_q:
            return
        lid, src_pts, radius, restore, smart, hard, alpha = self._brush_q.pop(0)
        lay = self.layer(lid)
        if lay is None:
            return self._brush_next()
        from ..ai import bg_removal as BR
        from .jobs import BackgroundJob
        snap = copy.deepcopy(lay)
        img, cw, ch = self.canvas._render(lay)
        k = T.image_k(img)

        def work(_p, _c):
            m = BR.paint(snap.get("mask"), snap["path"], src_pts, radius, restore, smart=smart, hard=hard, alpha=alpha)
            return m, T.mask_core({**snap, "mask": m}, k, int(cw), int(ch))
        job = BackgroundJob(work, self)

        def fin(res=None):
            self._brush_job = None
            if isinstance(res, tuple):
                self._set_mask(lid, res[0], "Pincel")
                self.canvas.brush_done(lid, res[0], res[1])
            else:
                self.canvas.brush_done(lid, "", None)
            self._brush_next()
        job.done.connect(fin)
        job.failed.connect(lambda m: (self.statusBar().showMessage(f"No se pudo aplicar el pincel: {m}", 8000), fin()))
        self._brush_job = job
        job.start()

    def _set_mask(self, lid: str, mask: str | None, label: str):
        lay = self.layer(lid)
        if lay is None:
            return
        tenia = lay.get("mask")
        lay["mask"] = mask
        if mask and label in ("Quitar fondo", "Recortar sujeto"):
            if not lay["outline"]["on"]:
                lay["outline"].update(on=True, color="#FFFFFF", width=6)     # contorno tipo pegatina
                lay["shadow"].update(on=True, blur=20, dx=0, dy=10, opacity=0.6)
            self._fit(lay)
        self._last_label = ""
        self.commit(label)
        self.canvas.viewport().update()
        if label != "Pincel" or not tenia:              # (cada trazo no rehace el panel: se puede seguir pintando)
            self._fill_props()
        self.statusBar().showMessage("✓ Listo. Retoca con el pincel si hace falta (Ctrl+Z para deshacer).", 6000)

    def _fit(self, lay: dict) -> bool:
        """Recorta la imagen a lo que quedó visible SIN moverlo de sitio (así las asas abrazan al sujeto)."""
        from ..ai import bg_removal as BR
        b = BR.subject_box(lay["mask"]) if lay.get("mask") else None
        if not b:
            return False
        m = 0.02
        new = [max(0, b[0] - m), max(0, b[1] - m), min(1, b[2] + m), min(1, b[3] + m)]
        old = lay["crop"]
        new = [max(new[0], old[0]), max(new[1], old[1]), min(new[2], old[2]), min(new[3], old[3])]
        if new[2] - new[0] < 0.01 or new[3] - new[1] < 0.01:
            return False
        img, cw, ch = T.render_layer(lay)
        src = QImage(lay["path"])
        sx, sy = (new[0] + new[2]) / 2 * src.width(), (new[1] + new[3]) / 2 * src.height()
        k = T.image_k(img)
        cx = (sx - old[0] * src.width()) * k + (img.width() - cw) / 2
        cy = (sy - old[1] * src.height()) * k + (img.height() - ch) / 2
        c = T.layer_transform(lay, img).map(QPointF(cx, cy))      # dónde está ahora el centro del sujeto
        lay["crop"] = new
        lay["x"], lay["y"] = round(c.x(), 2), round(c.y(), 2)
        return True

    def fit_to_subject(self):
        lay = self.cur()
        if lay and self._fit(lay):
            self._last_label = ""
            self.commit("Encuadrar al sujeto")
            self.canvas.viewport().update()

    # ----------------------------------------------------------- revisión
    def _title(self) -> str:
        p = self.ctrl.project
        return p.name if p.name and p.name != "Proyecto sin título" else "Título de tu video"

    def preview(self):
        from PySide6.QtWidgets import QDialog
        from ..core import thumb_review as R
        dlg = QDialog(self)
        dlg.setWindowTitle("Vista previa — así se verá")
        lay = QVBoxLayout(dlg)
        warns = [f for f in R.analyze(self.doc) if f["level"] == "warn"]
        head = QLabel("✓ Se entiende a tamaño pequeño." if not warns else
                      f"⚠ {len(warns)} cosas a revisar: pulsa «⚕ Analizar» para verlas y arreglarlas.")
        head.setStyleSheet("font-size: 11pt; padding: 4px;")
        lay.addWidget(head)
        row = QHBoxLayout()
        sizes = R.SHORTS_SIZES if self.doc["format"] == "short" else R.YT_SIZES
        for label, width in sizes:
            col = QVBoxLayout()
            im = R.simulate(self.doc, width, self._title())
            pic = QLabel()
            pic.setPixmap(QPixmap.fromImage(im))
            col.addWidget(pic, alignment=Qt.AlignTop)
            t = QLabel(f"<b>{self._title()[:48]}</b><br><span style='color:#9aa1ad'>Tu canal · 12 k vistas</span>")
            t.setWordWrap(True)
            t.setFixedWidth(max(width, 150))
            col.addWidget(t)
            cap = QLabel(f"{label} · {width} px de ancho")
            cap.setObjectName("dim")
            col.addWidget(cap)
            col.addStretch()
            row.addLayout(col)
        lay.addLayout(row)
        dlg.setStyleSheet("QDialog { background: #0f0f0f; }")
        dlg.exec()

    def analyze(self):
        from PySide6.QtWidgets import QDialog
        from ..core import thumb_review as R
        dlg = QDialog(self)
        dlg.setWindowTitle("Analizar miniatura")
        dlg.resize(620, 460)
        lay = QVBoxLayout(dlg)
        found = R.analyze(self.doc)
        icons = {"ok": "✓", "warn": "⚠", "tip": "💡"}
        fixes = []
        for f in found:
            row = QHBoxLayout()
            lb = QLabel(f"{icons[f['level']]}  {f['text']}")
            lb.setWordWrap(True)
            if f["level"] == "ok":
                lb.setObjectName("dim")
            row.addWidget(lb, 1)
            if f.get("fix"):
                fixes.append(f["fix"])
                b = QPushButton(f["fix"].get("label", "Aplicar"))
                b.clicked.connect(lambda _=False, fx=f["fix"], bb=None: self._apply_fix(fx))
                b.clicked.connect(lambda _=False, btn=b: (btn.setEnabled(False), btn.setText("✓ Hecho")))
                row.addWidget(b)
            lay.addLayout(row)
        lay.addStretch()
        bottom = QHBoxLayout()
        if fixes:
            all_b = QPushButton(f"Aplicar todo ({len(fixes)})")
            all_b.setObjectName("primary")
            all_b.clicked.connect(lambda: ([self._apply_fix(fx) for fx in fixes], dlg.accept()))
            bottom.addWidget(all_b)
        bottom.addStretch()
        close = QPushButton("Cerrar")
        close.clicked.connect(dlg.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        dlg.exec()

    def _apply_fix(self, fix: dict):
        from ..core import thumb_review as R
        self.doc = R.apply_fix(self.doc, fix)
        self._last_label = ""
        self.commit(fix.get("label", "Arreglo"))
        self.canvas.viewport().update()
        self._fill_props()

    def improve(self):
        from ..core import thumb_review as R
        self.doc = R.auto_improve(self.doc)
        self._last_label = ""
        self.commit("Mejorar automáticamente")
        self.canvas.viewport().update()
        self._fill_props()
        self.statusBar().showMessage("✨ Mejorada con ajustes suaves (Ctrl+Z para deshacer).", 6000)

    def export(self):
        name = os.path.splitext(os.path.basename(self.ctrl.path or "miniatura"))[0]
        start = os.path.join(os.path.dirname(self.ctrl.path) if self.ctrl.path else os.path.expanduser("~"),
                             f"{name} - miniatura{' short' if self.doc['format'] == 'short' else ''}.jpg")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar miniatura", start, "JPG (*.jpg);;PNG (*.png)")
        if not path:
            return
        n = T.export(self.doc, path)
        self.statusBar().showMessage(f"✓ Miniatura guardada ({n / 1024:.0f} KB): {path}", 10000)

    # ----------------------------------------------------------- propiedades
    def _fill_props(self):
        self._hist_rows = []
        while self.props_lay.count():
            w = self.props_lay.takeAt(0).widget()
            if w is not None:   # quitarlo ya (si no, se ve encima del nuevo hasta que Qt lo borre)
                w.hide()
                w.setParent(None)
                w.deleteLater()
        lay = self.cur()
        if lay is None:
            lb = QLabel("Elige algo en el lienzo (o en «Capas») para ver sus opciones.\n\n"
                        "Empieza por «🖼 Material»: un fotograma de tu video de fondo (doble clic) y otro delante.")
            lb.setWordWrap(True)
            lb.setObjectName("dim")
            self.props_lay.addWidget(lb)
            return
        self._loading = True
        title = QLabel(f"<b>{lay['name']}</b>")
        self.props_lay.addWidget(title)
        self._styles_props(lay)
        if lay["kind"] == "text":
            self._text_props(lay)
        elif lay.get("blur_area"):
            self._zone_props(lay)
        elif lay.get("slot"):
            self._slot_props(lay)
        elif lay["kind"] == "shape":
            self._shape_props(lay)
        else:
            self._image_props(lay)
        zona = bool(lay.get("blur_area"))
        if not zona:
            self._liquify_props(lay)
        self._common_props(lay)
        if not zona:
            self._effect_props(lay)
        self._loading = False

    def _set(self, lay: dict, label: str, **kv):
        if self._loading:
            return
        efectos = [k for k in EFECTOS_COLOR if any(x.split(".")[0] == k for x in kv)]
        antes = {k: self._word_props(lay)[k].get("color") for k in efectos}
        palabras = self.canvas.active_words(lay)
        if palabras and all(k.split(".")[0] in T.WORD_KEYS for k in kv):     # solo a las palabras elegidas
            T.set_word_style(lay, palabras, **kv)
            self.commit(f"{label} (palabra)")
        else:
            for k, v in kv.items():
                if "." in k:
                    a, b = k.split(".")
                    lay[a][b] = v
                else:
                    lay[k] = v
            self.commit(label)
        for k in efectos:                                    # 🎨 los colores usados, para cada efecto
            ahora = self._word_props(lay)[k].get("color")
            if ahora != antes[k]:
                self.remember_color(k, antes[k], ahora)
        self.on_live_change()

    def color_history(self, key: str) -> list[str]:
        return self._ajustes_lista(f"miniatura/colores_{key}")[:HISTORIAL_COLORES]

    def remember_color(self, key: str, *colores):
        """Apunta los colores (el último, el primero de la fila) sin repetir, y actualiza las filas del panel."""
        lista = self.color_history(key)
        for c in colores:
            if c:
                lista = [c] + [x for x in lista if x.casefold() != str(c).casefold()]
        self._guardar_lista(f"miniatura/colores_{key}", lista[:HISTORIAL_COLORES])
        vivas = []
        for fila in self._hist_rows:
            try:
                if fila.key == key:
                    fila.refresh()
                vivas.append(fila)
            except RuntimeError:                              # (panel rehecho)
                pass
        self._hist_rows = vivas

    def _slider(self, form, label, lay, key, lo, hi, val, scale=100, sub=None):
        """Barrita con su número a la derecha (el número va en centésimas: 0.45 → 45)."""
        s = _SliderNum(lo, hi, val, scale)
        k = f"{sub}.{key}" if sub else key
        s.applied.connect(lambda v: self._set(lay, label, **{k: round(v, 4)}))
        form.addRow(label, s)
        return s

    def _word_props(self, lay: dict) -> dict:
        """Lo que enseña el panel: la capa o, con palabras elegidas, la primera de ellas."""
        elegidas = self.canvas.active_words(lay)
        return T.word_view(lay, min(elegidas)) if elegidas else lay

    def _text_props(self, lay):
        box = QGroupBox("Texto")
        f = QFormLayout(box)
        ed = QPlainTextEdit(lay["text"])
        ed.setFixedHeight(64)
        ed.setToolTip("Marca aquí una o varias palabras (o haz doble clic en una en el lienzo; Ctrl + clic para añadir "
                      "más) y lo que cambies se aplica solo a ellas.")
        self._text_edit = ed                       # (doble clic en el texto del lienzo → aquí, para escribir)
        ed.textChanged.connect(lambda: self._set_text(lay, ed.toPlainText()))
        ed.selectionChanged.connect(lambda: self._box_selection(ed, lay))
        vista = self._word_props(lay)              # (con palabras elegidas, el panel enseña cómo son ellas)
        f.addRow(ed)
        from .spellcheck import attach as _spell
        f.addRow(_spell(ed))
        font = QFontComboBox()
        font.setCurrentFont(vista["font"])
        font.currentFontChanged.connect(lambda fnt: self._set(lay, "Fuente", font=fnt.family()))
        f.addRow("Fuente", font)
        size = QSpinBox()
        size.setRange(8, 600)
        size.setValue(int(vista["size"]))
        size.valueChanged.connect(lambda v: self._set(lay, "Tamaño", size=v))
        f.addRow("Tamaño", size)
        wt = QComboBox()
        for label, v in (("Normal", 400), ("Semi", 600), ("Negrita", 700), ("Extra", 900)):
            wt.addItem(label, v)
        wt.setCurrentIndex(max(0, wt.findData(int(vista["weight"]))))
        wt.currentIndexChanged.connect(lambda _i: self._set(lay, "Grosor", weight=wt.currentData()))
        f.addRow("Grosor", wt)
        self._slider(f, "Espaciado", lay, "spacing", 0.7, 1.6, lay["spacing"])
        self._slider(f, "Interlineado", lay, "line", 0.6, 1.6, lay["line"])
        al = QComboBox()
        for label, v in (("Centro", "center"), ("Izquierda", "left"), ("Derecha", "right")):
            al.addItem(label, v)
        al.setCurrentIndex(max(0, al.findData(lay["align"])))
        al.currentIndexChanged.connect(lambda _i: self._set(lay, "Alineación", align=al.currentData()))
        f.addRow("Alineación", al)
        col = _ColorButton(vista["color"])
        col.changed.connect(lambda c: self._set(lay, "Color", color=c))
        f.addRow("Color", col)
        self._text_fill_rows(f, lay)
        acc = _ColorButton(lay.get("accent", T.MY_RED))         # lo escrito *entre asteriscos*
        acc.setToolTip("Color de lo que escribas *entre asteriscos* (p. ej. «ESTO ES *MALO*»)")
        acc.changed.connect(lambda c: self._set(lay, "Color de acento", accent=c))
        f.addRow("Acento *…*", acc)
        up = QCheckBox("MAYÚSCULAS")
        up.setChecked(bool(lay["uppercase"]))
        up.toggled.connect(lambda v: self._set(lay, "Mayúsculas", uppercase=v))
        f.addRow(up)
        self.props_lay.addWidget(box)
        elegidas = self.canvas.active_words(lay)
        spans = T.word_spans(lay.get("text", ""))
        if elegidas and max(elegidas) - min(elegidas) + 1 == len(elegidas):   # (contiguas: también marcadas en el cuadro)
            self._select_in_box(ed, spans[min(elegidas)][0], spans[max(elegidas)][1])

    def _zone_props(self, lay):
        box = QGroupBox("🌫 Zona borrosa")
        f = QFormLayout(box)
        self._slider(f, "Fuerza", lay, "radius", 2, 60, float(lay["blur_area"].get("radius", 18)), scale=1,
                     sub="blur_area")
        forma = QComboBox()
        forma.addItem("◯ Círculo", "ellipse")
        forma.addItem("▢ Cuadrado", "rect")
        forma.setCurrentIndex(max(0, forma.findData(lay.get("shape", "rect"))))

        def cambiar(i, lay=lay, forma=forma):
            s = forma.itemData(i)
            self._set(lay, "Forma", shape=s, name="🌫 Borroso (círculo)" if s == "ellipse" else "🌫 Borroso (cuadrado)")
        forma.activated.connect(cambiar)
        f.addRow("Forma", forma)
        self.props_lay.addWidget(box)

    def _shape_props(self, lay):
        box = QGroupBox("Forma")
        f = QFormLayout(box)
        for key, label in (("w", "Ancho"), ("h", "Alto"), ("radius", "Esquinas")):
            sp = QSpinBox()
            sp.setRange(0, 4000)
            sp.setValue(int(lay[key]))
            sp.valueChanged.connect(lambda v, k=key, lb=label: self._set(lay, lb, **{k: v}))
            f.addRow(label, sp)
        fill = _ColorButton(lay["fill"])
        fill.changed.connect(lambda c: self._set(lay, "Relleno", fill=c))
        f.addRow("Relleno", fill)
        g = QCheckBox("Degradado")
        g.setChecked(bool(lay["gradient"]["on"]))
        g.toggled.connect(lambda v: self._set(lay, "Degradado", **{"gradient.on": v}))
        f.addRow(g)
        c1, c2 = _ColorButton(lay["gradient"]["c1"]), _ColorButton(lay["gradient"]["c2"])
        c1.changed.connect(lambda c: self._set(lay, "Degradado", **{"gradient.c1": c}))
        c2.changed.connect(lambda c: self._set(lay, "Degradado", **{"gradient.c2": c}))
        row = QHBoxLayout()
        row.addWidget(c1)
        row.addWidget(c2)
        f.addRow("De → a", row)
        ang = QSpinBox()
        ang.setRange(0, 360)
        ang.setValue(int(lay["gradient"]["angle"]))
        ang.valueChanged.connect(lambda v: self._set(lay, "Degradado", **{"gradient.angle": v}))
        f.addRow("Ángulo", ang)
        self.props_lay.addWidget(box)

    def _image_props(self, lay):
        cut = QGroupBox("✂ Recorte del sujeto (quitar fondo)")
        cg = QGridLayout(cut)
        b_auto = QPushButton("✂ Quitar fondo")
        b_auto.setToolTip("La IA recorta al sujeto principal automáticamente")
        b_auto.clicked.connect(self.cutout_auto)
        b_box = QPushButton("⬚ Marcar con recuadro")
        b_box.setToolTip("Dibuja un recuadro alrededor de lo que quieres conservar")
        b_box.clicked.connect(self.start_box)
        b_er = QPushButton("🖌 Borrar")
        b_er.setCheckable(True)
        b_er.setChecked(self.canvas.tool == "erase")
        b_er.clicked.connect(lambda on: self.set_brush("erase" if on else None))
        b_re = QPushButton("🖌 Recuperar")
        b_re.setCheckable(True)
        b_re.setChecked(self.canvas.tool == "restore")
        b_re.clicked.connect(lambda on: self.set_brush("restore" if on else None))
        size = QSpinBox()
        size.setRange(3, 200)
        size.setSuffix(" px")
        size.setValue(self.canvas.brush)
        size.valueChanged.connect(lambda v: setattr(self.canvas, "brush", v))
        lista = QCheckBox("Recuperar solo el sujeto")
        lista.setChecked(self.brush_smart())
        lista.setToolTip("Pinta por encima sin miedo: se recupera solo lo que se parece a lo que ya se ve (el personaje), "
                         "siguiendo sus bordes, y no el fondo. Desactívalo para recuperar exactamente lo que pintes.")
        lista.toggled.connect(self.set_brush_smart)
        self._lista_sujeto = lista
        cg.addWidget(lista, 9, 0, 1, 2)
        dur = _SliderNum(0, 1, self.brush_opt("hard"), 100, suffix=" %")
        dur.setToolTip("Dureza del borde del pincel: 100 % = nítido; menos = suave (borrar o recuperar sin que se note "
                       "el corte)")
        dur.applied.connect(lambda v: self.set_brush_opt("hard", v))
        opa = _SliderNum(0.05, 1, self.brush_opt("alpha"), 100, suffix=" %")
        opa.setToolTip("Cuánto borra o recupera cada trazo: 100 % = del todo; 50 % = la mitad (queda semitransparente). "
                       "Dentro de un mismo trazo no se suma")
        opa.applied.connect(lambda v: self.set_brush_opt("alpha", v))
        cg.addWidget(QLabel("Dureza"), 4, 0)
        cg.addWidget(dur, 4, 1)
        cg.addWidget(QLabel("Opacidad"), 5, 0)
        cg.addWidget(opa, 5, 1)
        b_fit = QPushButton("Encuadrar al sujeto")
        b_fit.clicked.connect(self.fit_to_subject)
        b_fit.setEnabled(bool(lay.get("mask")))
        b_none = QPushButton("Quitar el recorte")
        b_none.clicked.connect(lambda: self._set_mask(lay["id"], None, "Quitar recorte"))
        b_none.setEnabled(bool(lay.get("mask")))
        cg.addWidget(b_auto, 0, 0)
        cg.addWidget(b_box, 0, 1)
        cg.addWidget(b_er, 1, 0)
        cg.addWidget(b_re, 1, 1)
        cg.addWidget(QLabel("Tamaño del pincel"), 2, 0)
        cg.addWidget(size, 2, 1)
        cg.addWidget(b_fit, 3, 0)
        cg.addWidget(b_none, 3, 1)
        self.props_lay.addWidget(cut)
        box = QGroupBox("Imagen: ajustes")
        f = QFormLayout(box)
        a = lay["adj"]
        for key, label, lo, hi in (("exposure", "Exposición", -1.5, 1.5), ("contrast", "Contraste", -0.8, 0.8),
                                   ("saturation", "Saturación", -1, 1), ("temperature", "Temperatura", -1, 1),
                                   ("shadows", "Sombras", -1, 1), ("highlights", "Luces", -1, 1),
                                   ("sharpen", "Nitidez", 0, 1), ("blur", "Desenfoque", 0, 1),
                                   ("vignette", "Viñeta", 0, 1)):
            self._slider(f, label, lay, key, lo, hi, a.get(key, 0.0), sub="adj")
        reset = QPushButton("Restablecer ajustes")
        reset.clicked.connect(lambda: (lay.update(adj=dict(T.ADJ_DEFAULT)), self.commit("Restablecer"),
                                       self.on_live_change(), self._fill_props()))
        f.addRow(reset)
        self.props_lay.addWidget(box)
        self._soft_props(lay)
        self._upscale_props(lay)
        self._combine_props(lay)
        crop = QGroupBox("Recortar (%)")
        cf = QGridLayout(crop)
        for i, (label, idx) in enumerate((("Izquierda", 0), ("Arriba", 1), ("Derecha", 2), ("Abajo", 3))):
            sp = QSpinBox()
            sp.setRange(0, 100)
            val = lay["crop"][idx] * 100
            sp.setValue(int(round(val if idx < 2 else 100 - val)))
            sp.setSuffix(" %")

            def ch(v, i_=idx):
                c = list(lay["crop"])
                c[i_] = v / 100 if i_ < 2 else 1 - v / 100
                if c[2] - c[0] > 0.05 and c[3] - c[1] > 0.05:
                    self._set(lay, "Recortar", crop=c)
            sp.valueChanged.connect(ch)
            cf.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            cf.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        self.props_lay.addWidget(crop)

    def _common_props(self, lay):
        box = QGroupBox("Posición")
        f = QFormLayout(box)
        self._slider(f, "Opacidad", lay, "opacity", 0, 1, lay["opacity"])
        if not lay.get("blur_area"):                 # (una zona borrosa ya es el desenfoque: sin este)
            bl = self._slider(f, "Desenfoque", lay, "blur", 0, 60, float(lay.get("blur", 0) or 0), scale=1)
            bl.setToolTip("🌫 Desenfoca toda la capa (0 = nítida). También con clic derecho → «Desenfocar»")
        if not lay.get("blur_area"):
            fu = QComboBox()
            for clave, nombre, _m in T.BLENDS:
                fu.addItem(nombre, clave)
            fu.setCurrentIndex(max(0, fu.findData(lay.get("blend") or "normal")))
            fu.setToolTip("Cómo se mezcla con lo de debajo. Multiplicar oscurece (sombras, texturas, manchas); Trama "
                          "aclara (fuego, chispas, humo o luces sobre fondo negro: el negro desaparece); Superponer y "
                          "Luz suave dan contraste y color sin tapar")
            fu.activated.connect(lambda _i: self._set(lay, "Fusión", blend=fu.currentData()))
            f.addRow("Fusión", fu)
        sc = QDoubleSpinBox()
        sc.setRange(0.02, 20)
        sc.setSingleStep(0.05)
        sc.setValue(lay["scale"])
        sc.valueChanged.connect(lambda v: self._set(lay, "Tamaño", scale=v))
        f.addRow("Escala", sc)
        if lay["kind"] == "image":
            b_swap = QPushButton("🔁 Cambiar la imagen…")
            b_swap.setToolTip("Pone otra imagen en su lugar: mismo sitio, tamaño, giro y efectos (también: Alt + soltar "
                              "una imagen encima de esta)")
            b_swap.clicked.connect(lambda: self.replace_image(lay))
            f.addRow(b_swap)
            b_fill = QPushButton("⛶ Llenar el lienzo")
            b_fill.setToolTip("Agranda la imagen hasta cubrir toda la miniatura y la centra (lo que sobra queda fuera)")
            b_fill.clicked.connect(lambda: self.fill_canvas(lay))
            f.addRow(b_fill)
            b_blur = QPushButton("🌫 Fondo desenfocado detrás")
            b_blur.setToolTip("Pone esta misma imagen llenando la miniatura, desenfocada y oscura, DETRÁS de ella: "
                              "el sujeto resalta (mejor si ya le quitaste el fondo)")
            b_blur.clicked.connect(lambda: self.blur_background(lay))
            f.addRow(b_blur)
        rot = QDoubleSpinBox()
        rot.setRange(-360, 360)
        rot.setSuffix("°")
        rot.setValue(lay["rotation"])
        rot.valueChanged.connect(lambda v: self._set(lay, "Giro", rotation=v))
        f.addRow("Giro", rot)
        fl = QCheckBox("Voltear (espejo)")
        fl.setChecked(bool(lay.get("flip")))
        fl.toggled.connect(lambda v: self._set(lay, "Voltear", flip=v))
        f.addRow(fl)
        self.props_lay.addWidget(box)

    def _effect_props(self, lay):
        box = QGroupBox("Efectos")
        f = QFormLayout(box)
        for key, label, fields in (("outline", "Contorno", (("width", "Grosor", 1, 60),)),
                                   ("shadow", "Sombra", (("blur", "Difuminado", 0, 80), ("dx", "Desplaz. X", -60, 60),
                                                         ("dy", "Desplaz. Y", -60, 60), ("opacity", "Opacidad", 0, 1))),
                                   ("glow", "Brillo", (("radius", "Radio", 2, 120), ("opacity", "Opacidad", 0, 1)))):
            e = self._word_props(lay)[key]
            on = QCheckBox(label)
            on.setChecked(bool(e["on"]))
            on.toggled.connect(lambda v, k=key, lb=label: self._set(lay, lb, **{f"{k}.on": v}))
            col = _ColorButton(e["color"])
            col.changed.connect(lambda c, k=key, lb=label: self._set(lay, lb, **{f"{k}.color": c}))
            row = QHBoxLayout()
            row.addWidget(on)
            row.addStretch()
            row.addWidget(col)
            f.addRow(row)

            def usar(c, k=key, lb=label, boton=col):
                boton.set_color(c)
                self._set(lay, lb, **{f"{k}.color": c})
            hist = _ColorHistory(self, key, usar)                # 🎨 los colores que ya usaste en este efecto
            self._hist_rows.append(hist)
            f.addRow(hist)
            for fk, fl, lo, hi in fields:
                pct = fk == "opacity"                          # (la opacidad, en %)
                sp = _SliderNum(lo, hi, float(e.get(fk, 0.7 if pct else 0)), 100 if pct else 1,
                                suffix=" %" if pct else "")
                sp.applied.connect(lambda v, k=key, kk=fk, lb=label, p=pct:
                                   self._set(lay, lb, **{f"{k}.{kk}": round(v, 3) if p else int(v)}))
                f.addRow("    " + fl, sp)
            if key == "outline" and lay["kind"] in ("text", "image"):
                self._extra_outline_rows(f, lay)
        self.props_lay.addWidget(box)

    # ----------------------------------------------------------- ➕ contornos apilados
    def _extra_outline_rows(self, form, lay):
        extras = list(lay.get("outlines") or [])

        def cambiar(i, **kv):
            lst = copy.deepcopy(lay.get("outlines") or [])
            if i < len(lst):
                lst[i].update(kv)
                self._set(lay, "Contorno de más", outlines=lst)

        def quitar(i):
            self._set(lay, "Quitar contorno", outlines=[o for j, o in enumerate(lay.get("outlines") or []) if j != i])
            QTimer.singleShot(0, self._fill_props)
        for i, o in enumerate(extras[:T.EXTRA_OUTLINES_MAX]):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"    {i + 2}.º"))
            col = _ColorButton(o.get("color", "#000000"))
            col.setToolTip("Color de este contorno (va por fuera del anterior)")
            col.changed.connect(lambda c, i=i: (cambiar(i, color=c), self.remember_color("outline", c)))
            row.addWidget(col)
            sp = _SliderNum(1, 60, float(o.get("width", 8)), 1)
            sp.setToolTip("Grosor de este contorno")
            sp.applied.connect(lambda v, i=i: cambiar(i, width=int(v)))
            row.addWidget(sp, 1)
            x = QPushButton("✕")
            x.setFixedWidth(28)
            x.setToolTip("Quitar este contorno")
            x.clicked.connect(lambda _=False, i=i: quitar(i))
            row.addWidget(x)
            form.addRow(row)
        if len(extras) < T.EXTRA_OUTLINES_MAX:
            b = QPushButton("➕ Otro contorno por fuera")
            b.setToolTip("Apila otro contorno alrededor del anterior (p. ej. blanco y, por fuera, negro: el clásico de "
                         "YouTube). Hasta 3 de más")
            b.clicked.connect(lambda: self.add_outline(lay))
            form.addRow(b)

    def add_outline(self, lay: dict):
        lst = copy.deepcopy(lay.get("outlines") or [])
        if len(lst) >= T.EXTRA_OUTLINES_MAX:
            return
        prev = lst[-1]["color"] if lst else lay["outline"].get("color", "#000000")
        lst.append({"color": "#000000" if QColor(prev).lightness() > 128 else "#FFFFFF",
                    "width": int(lst[-1]["width"]) if lst else max(6, int(lay["outline"].get("width", 8)))})
        self._set(lay, "Otro contorno", outlines=lst)
        QTimer.singleShot(0, self._fill_props)

    # ----------------------------------------------------------- 🎨 relleno de las letras
    def _pick_image(self, titulo: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, titulo, self._ajustes_lista("miniatura/carpeta_imagenes")[0]
                                              if self._ajustes_lista("miniatura/carpeta_imagenes") else "",
                                              "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.jfif)")
        if path:
            self._guardar_lista("miniatura/carpeta_imagenes", [os.path.dirname(path)])
        return path

    def _text_fill_rows(self, f, lay):
        tf = dict(lay.get("text_fill") or {})
        tipo = tf.get("type", "color")
        rel = QComboBox()
        for nombre, v in (("Color", "color"), ("Degradado", "gradient"), ("Imagen", "image")):
            rel.addItem(nombre, v)
        rel.setCurrentIndex(max(0, rel.findData(tipo)))
        rel.setToolTip("Con qué se rellenan las letras: un color, un degradado o una imagen (fuego, metal, una "
                       "captura del juego…). Las palabras con color propio lo conservan")

        def cambiar(_i):
            t = rel.currentData()
            nuevo = {"c1": "#FFD400", "c2": "#E5232A", "angle": 90, "path": "", "zoom": 1.0,
                     **(lay.get("text_fill") or {}), "type": t}
            if t == "image" and not (nuevo["path"] and os.path.exists(nuevo["path"])):
                ruta = self._pick_image("Imagen para rellenar las letras")
                if not ruta:
                    rel.setCurrentIndex(max(0, rel.findData((lay.get("text_fill") or {}).get("type", "color"))))
                    return
                nuevo["path"] = ruta
            self._set(lay, "Relleno de letras", text_fill=nuevo)
            QTimer.singleShot(0, self._fill_props)
        rel.activated.connect(cambiar)
        f.addRow("Relleno", rel)

        def poner(**kv):
            self._set(lay, "Relleno de letras", text_fill={**(lay.get("text_fill") or {}), **kv})
        if tipo == "gradient":
            c1, c2 = _ColorButton(tf.get("c1", "#FFD400")), _ColorButton(tf.get("c2", "#E5232A"))
            c1.changed.connect(lambda c: poner(c1=c))
            c2.changed.connect(lambda c: poner(c2=c))
            row = QHBoxLayout()
            row.addWidget(c1)
            row.addWidget(QLabel("→"))
            row.addWidget(c2)
            row.addStretch()
            f.addRow("    De → a", row)
            ang = _SliderNum(0, 360, float(tf.get("angle", 90)), 1, suffix="°")
            ang.setToolTip("Dirección del degradado: 90° = de arriba a abajo; 0° = de izquierda a derecha")
            ang.applied.connect(lambda v: poner(angle=int(v)))
            f.addRow("    Ángulo", ang)
        elif tipo == "image":
            b = QPushButton("📂 " + (os.path.basename(tf.get("path", "")) or "Elegir imagen…")[:28])
            b.setToolTip("Cambiar la imagen de dentro de las letras")
            b.clicked.connect(lambda: (lambda r: (poner(path=r), QTimer.singleShot(0, self._fill_props)) if r else None)(
                self._pick_image("Imagen para rellenar las letras")))
            f.addRow("    Imagen", b)
            zo = _SliderNum(0.5, 4, float(tf.get("zoom", 1.0)), 100, suffix=" %")
            zo.setToolTip("Acercar la imagen de dentro de las letras")
            zo.applied.connect(lambda v: poner(zoom=round(v, 3)))
            f.addRow("    Zoom", zo)

    # ----------------------------------------------------------- 🌗 bordes suaves
    def _soft_props(self, lay):
        box = QGroupBox("🌗 Bordes suaves")
        f = QFormLayout(box)
        fe = _SliderNum(0, 1, float(lay.get("feather", 0) or 0), 100, suffix=" %")
        fe.setToolTip("Difumina el borde de la imagen hacia dentro (también el del sujeto recortado): se funde con lo "
                      "de detrás sin un corte duro")
        fe.applied.connect(lambda v: self._set(lay, "Bordes suaves", feather=round(v, 3)))
        f.addRow("Difuminar borde", fe)
        for lado, nombre in (("bottom", "Fundir abajo"), ("top", "Fundir arriba"), ("left", "Fundir izquierda"),
                             ("right", "Fundir derecha")):
            sl = _SliderNum(0, 1, float((lay.get("fade") or {}).get(lado, 0) or 0), 100, suffix=" %")
            sl.setToolTip("Hasta dónde se va desvaneciendo la imagen desde ese lado (p. ej. un personaje que se funde "
                          "con el fondo por abajo)")
            sl.applied.connect(lambda v, ld=lado: self._set(lay, "Fundido",
                                                            fade={**(lay.get("fade") or {}), ld: round(v, 3)}))
            f.addRow(nombre, sl)
        self.props_lay.addWidget(box)

    # ----------------------------------------------------------- ⭐ mis estilos
    def _styles_props(self, lay):
        from ..core import thumb_styles as S
        kind = S.kind_of(lay)
        if not kind:
            return
        box = QGroupBox("⭐ Mis estilos")
        g = QGridLayout(box)
        g.setSpacing(4)
        estilos = S.of_kind(kind)[:24]
        for i, est in enumerate(estilos):
            b = QPushButton(est["name"])
            b.setToolTip(f"Ponerle el estilo «{est['name']}» a lo elegido · clic derecho = renombrar, actualizar o "
                         "borrar")
            if kind == "text":
                b.setIcon(self._style_icon(est))
                b.setIconSize(QSize(44, 20))
            b.clicked.connect(lambda _=False, e=est: self.apply_style(e))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, e=est, btn=b: self._style_menu(e, btn.mapToGlobal(pos)))
            g.addWidget(b, i // 2, i % 2)
        guardar = QPushButton("💾 Guardar este estilo…")
        guardar.setToolTip("Guarda el aspecto de lo elegido (fuente, colores, contornos, sombra, brillo, relleno, "
                           "fusión…) para ponérselo a otra capa con un clic. No guarda el texto, la imagen ni el sitio")
        guardar.clicked.connect(lambda: self.save_style_dialog(lay))
        g.addWidget(guardar, (len(estilos) + 1) // 2, 0, 1, 2)
        self.props_lay.addWidget(box)

    def _style_icon(self, est: dict) -> QIcon:
        memo = self.__dict__.setdefault("_style_icons", {})
        clave = json.dumps(est, sort_keys=True, default=str)
        if clave not in memo:
            muestra = T.text_layer(self.doc, "Aa")
            muestra.update(copy.deepcopy(est["style"]))
            muestra["size"] = 64
            try:
                img, _cw, _ch = T.render_layer(muestra)
                memo[clave] = QIcon(QPixmap.fromImage(img).scaled(88, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:  # noqa: BLE001 - sin muestra, el botón sirve igual
                memo[clave] = QIcon()
        return memo[clave]

    def save_style_dialog(self, lay: dict):
        from PySide6.QtWidgets import QInputDialog
        from ..core import thumb_styles as S
        n = len(S.of_kind(S.kind_of(lay) or ""))
        name, ok = QInputDialog.getText(self, "Guardar estilo", "Nombre del estilo:", text=f"Estilo {n + 1}")
        if ok and name.strip():
            self.save_style(name, lay)

    def save_style(self, name: str, lay: dict) -> dict | None:
        from ..core import thumb_styles as S
        est = S.add(name, lay)
        if est:
            self.statusBar().showMessage(f"⭐ Estilo «{est['name']}» guardado: clic en él para ponérselo a otra capa", 6000)
            self._fill_props()
        return est

    def apply_style(self, est: dict) -> int:
        """Pone ese estilo a lo elegido (a todas las capas de su tipo; en un texto con palabras elegidas, solo a ellas)."""
        from ..core import thumb_styles as S
        cur = self.cur()
        capas = [l for l in self.selected_layers() if S.kind_of(l) == est["kind"]]
        if not capas:
            return 0
        palabras = self.canvas.active_words(cur) if cur is not None else set()
        for l in capas:
            cambios = S.changes(l, est)
            if l is cur and palabras:
                T.set_word_style(l, palabras, **{k: v for k, v in cambios.items() if k in T.WORD_KEYS})
            else:
                l.update(cambios)
        self._last_label = ""
        self.commit(f"Estilo «{est['name']}»")
        self.on_live_change()
        self._fill_props()
        return len(capas)

    def _style_menu(self, est: dict, pos):
        from PySide6.QtWidgets import QInputDialog, QMenu
        from ..core import thumb_styles as S
        m = QMenu(self)
        m.addAction("✏ Renombrar…", lambda: (lambda r: (S.rename(est["name"], est["kind"], r[0]), self._fill_props())
                                             if r[1] and r[0].strip() else None)(
            QInputDialog.getText(self, "Renombrar estilo", "Nombre:", text=est["name"])))
        cur = self.cur()
        if cur is not None and S.kind_of(cur) == est["kind"]:
            m.addAction("↻ Actualizar con lo elegido", lambda: self.save_style(est["name"], cur))
        m.addSeparator()
        m.addAction("🗑 Borrar este estilo", lambda: (S.remove(est["name"], est["kind"]), self._fill_props()))
        m.exec(pos)

    # ----------------------------------------------------------- 🖼 huecos y cambiar la imagen
    def _slot_props(self, lay):
        box = QGroupBox("🖼 Hueco para una imagen")
        v = QVBoxLayout(box)
        b = QPushButton("📂 Poner una imagen…")
        b.setToolTip("La imagen ocupa justo el hueco (se recorta por el centro, sin deformarse) y toma sus efectos. "
                     "También: suelta una imagen encima, o con el hueco elegido haz clic en una de «🖼 Material»")
        b.clicked.connect(lambda: self.replace_image(lay))
        v.addWidget(b)
        self.props_lay.addWidget(box)

    def replace_image(self, lay: dict, path: str | None = None) -> dict | None:
        """Pone esa imagen en lugar de la capa (un hueco o una imagen), con su caja, su sitio y sus efectos."""
        if lay is None or lay.get("locked"):
            return None
        path = path or self._pick_image("Elegir imagen")
        if not path or not os.path.exists(path):
            return None
        idx = next((i for i, l in enumerate(self.doc["layers"]) if l is lay or l["id"] == lay["id"]), None)
        if idx is None:
            return None
        nueva = T.fill_box(lay, path, self.doc)
        self.doc["layers"][idx] = nueva
        self._recordar(path)
        self.canvas.sel = nueva["id"]
        self.canvas.multi.clear()
        self._last_label = ""
        self.commit("Poner imagen en el hueco" if lay.get("slot") else "Cambiar la imagen")
        self.canvas.viewport().update()
        self._fill_props()
        return nueva

