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

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QGraphicsScene, QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
                               QToolBar, QVBoxLayout, QWidget)

from ..core import thumbnail as T
from ..core.model import KIND_IMAGE, KIND_VIDEO
from .help import set_help

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
        c = QColorDialog.getColor(QColor(self._c), self, "Color", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            name = c.name(QColor.HexArgb) if c.alpha() < 255 else c.name()
            self.set_color(name)
            self.changed.emit(name)


class Canvas(QGraphicsView):
    """El lienzo: dibuja la miniatura y permite mover, escalar y girar capas con el ratón."""
    selected = Signal(str)          # id de la capa elegida ("" = ninguna)
    committed = Signal(str)         # terminó un arrastre: guardar en el historial

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#0b0b0d"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.sel: str = ""
        self._drag: dict | None = None
        self._guides: list = []
        self.tool: str | None = None      # None | "box" (marcar sujeto) | "erase" | "restore" (pincel)
        self.warp_mode = False            # ◇ Deformar: las esquinas se mueven cada una por su lado
        self.brush = 30                   # radio del pincel (píxeles del lienzo)
        self._stroke: list = []
        self._hover = None
        self.liq_mode = "inflar"          # ≈ Licuar: inflar | encoger | empujar | restaurar
        self.liq_strength = 0.5
        self._liq_timer = QTimer(self)    # inflar/encoger mientras se mantiene pulsado (como en Photoshop)
        self._liq_timer.setInterval(40)
        self._liq_timer.timeout.connect(self._liq_tick)

    # ------------------------------------------------------------- dibujo
    @property
    def doc(self) -> dict:
        return self.editor.doc

    def refresh(self):
        d = self.doc
        self.setSceneRect(QRectF(-40, -40, d["w"] + 80, d["h"] + 80))
        self.fitInView(QRectF(-20, -20, d["w"] + 40, d["h"] + 40), Qt.KeepAspectRatio)
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refresh()

    def drawBackground(self, p: QPainter, rect: QRectF):
        super().drawBackground(p, rect)
        d = self.doc
        p.save()
        p.setClipRect(QRectF(0, 0, d["w"], d["h"]))
        T.paint_background(p, d)
        for lay in d["layers"]:
            if not lay.get("visible", True):
                continue
            img, _w, _h = T.render_layer(lay)
            p.save()
            p.setOpacity(float(lay.get("opacity", 1.0)))
            p.setTransform(T.layer_transform(lay, img), True)
            p.drawImage(0, 0, img)
            p.restore()
        p.restore()
        p.setPen(QPen(QColor("#333"), 0))
        p.drawRect(QRectF(0, 0, d["w"], d["h"]))

    def _box(self, lay: dict) -> QPolygonF:
        """Rectángulo (girado) del contenido de la capa, en coordenadas del lienzo."""
        img, cw, ch = T.render_layer(lay)
        t = T.layer_transform(lay, img)
        x0, y0 = (img.width() - cw) / 2, (img.height() - ch) / 2
        return t.map(QPolygonF(QRectF(x0, y0, cw, ch)))

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
        d = self.doc
        k = 1 / max(self.transform().m11(), 1e-6)
        if self.tool in ("erase", "restore"):
            col = QColor(229, 65, 60, 110) if self.tool == "erase" else QColor(80, 200, 120, 110)
            if len(self._stroke) > 1:
                p.setPen(QPen(col, self.brush * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(QPolygonF(self._stroke))
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
        if self.tool == "box" and self._drag and self._drag.get("mode") == "box":
            p.setPen(QPen(QColor("#e8742f"), 2 * k, Qt.DashLine))
            p.setBrush(QColor(232, 116, 47, 40))
            p.drawRect(QRectF(self._drag["p0"], self._drag["p1"]).normalized())
        p.setPen(QPen(QColor(232, 116, 47, 160), 0, Qt.DashLine))
        for g in self._guides:
            if g[0] == "v":
                p.drawLine(QPointF(g[1], 0), QPointF(g[1], d["h"]))
            else:
                p.drawLine(QPointF(0, g[1]), QPointF(d["w"], g[1]))
        lay = self.editor.layer(self.sel)
        if lay is None or not lay.get("visible", True):
            return
        h = self._handles(lay)
        k = h["k"]
        p.setPen(QPen(QColor("#e8742f"), 1.5 * k))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF(h["corners"]))
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
        top_mid = (h["corners"][0] + h["corners"][1]) / 2
        p.drawLine(top_mid, h["rot"])
        p.drawEllipse(h["rot"], HANDLE * k * 0.6, HANDLE * k * 0.6)

    # ------------------------------------------------------------- ratón
    def _hit(self, pt: QPointF) -> str:
        for lay in reversed(self.doc["layers"]):
            if lay.get("visible", True) and self._box(lay).containsPoint(pt, Qt.OddEvenFill):
                return lay["id"]
        return ""

    def mousePressEvent(self, e):
        pt = self.mapToScene(e.position().toPoint())
        if self.tool == "liquify" and e.button() == Qt.LeftButton:
            lay = self.editor.layer(self.sel)
            if lay is None or lay.get("locked"):
                self.sel = self._hit(pt)
                self.selected.emit(self.sel)
                lay = self.editor.layer(self.sel)
            if lay is not None and not lay.get("locked"):
                c = self.content_point(lay, pt)
                self._drag = {"mode": "liquify", "lay": lay, "last": c, "pos": c}
                if self.liq_mode != "empujar":
                    self._liq_tick()
                    self._liq_timer.start()
            return
        if self.tool and e.button() == Qt.LeftButton:
            if self.tool == "box":
                self._drag = {"mode": "box", "p0": pt, "p1": pt}
            else:
                self._stroke = [pt]
                self._drag = {"mode": "brush"}
            self.viewport().update()
            return
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
            for c in ([] if self.warp_mode else h["corners"]):
                if (pt - c).manhattanLength() < tol * 1.6:
                    d0 = math.hypot(pt.x() - h["center"].x(), pt.y() - h["center"].y()) or 1
                    self._drag = {"mode": "scale", "lay": lay, "c": h["center"], "s0": lay["scale"], "d0": d0}
                    return
        hit = self._hit(pt)
        self.sel = hit
        self.selected.emit(hit)
        lay = self.editor.layer(hit)
        if lay is not None and not lay.get("locked") and e.button() == Qt.LeftButton:
            self._drag = {"mode": "move", "lay": lay, "p0": pt, "x0": lay["x"], "y0": lay["y"]}
        self.viewport().update()

    def mouseMoveEvent(self, e):
        d = self._drag
        pt = self.mapToScene(e.position().toPoint())
        if self.tool in ("erase", "restore"):
            self._hover = pt
            if d is not None:
                self._stroke.append(pt)
            self.viewport().update()
            return
        if self.tool == "liquify":
            self._hover = pt
            if d is not None and d.get("mode") == "liquify":
                c = self.content_point(d["lay"], pt)
                if self.liq_mode == "empujar":
                    last = d["last"]
                    self.editor.liquify_dab(d["lay"], c, (c["fx"] - last["fx"], c["fy"] - last["fy"]))
                    d["last"] = c
                d["pos"] = c
            self.viewport().update()
            return
        if self.tool == "box" and d is not None:
            d["p1"] = pt
            self.viewport().update()
            return
        if d is None:
            return
        lay = d["lay"]
        doc = self.doc
        self._guides = []
        if d["mode"] == "move":
            x = d["x0"] + pt.x() - d["p0"].x()
            y = d["y0"] + pt.y() - d["p0"].y()
            snap = 10 / max(self.transform().m11(), 1e-6)
            for target in (doc["w"] / 2, doc["w"] / 3, doc["w"] * 2 / 3):
                if abs(x - target) < snap:
                    x = target
                    self._guides.append(("v", target))
            for target in (doc["h"] / 2, doc["h"] / 3, doc["h"] * 2 / 3):
                if abs(y - target) < snap:
                    y = target
                    self._guides.append(("h", target))
            lay["x"], lay["y"] = round(x, 1), round(y, 1)
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
        if self.tool == "liquify" and self._drag is not None and self._drag.get("mode") == "liquify":
            self._liq_timer.stop()
            self._drag = None
            self.editor.liquify_done()
            return
        if self.tool == "box" and self._drag is not None:
            r = QRectF(self._drag["p0"], self._drag["p1"]).normalized()
            self._drag = None
            self.viewport().update()
            self.editor.cutout_box(r)
            return
        if self.tool in ("erase", "restore") and self._drag is not None:
            self._drag = None
            pts, self._stroke = self._stroke, []
            self.editor.brush_stroke(pts, self.tool == "restore")
            self.viewport().update()
            return
        if self._drag is not None:
            self._drag = None
            self._guides = []
            self.committed.emit("Mover / tamaño / giro")
            self.viewport().update()

    def content_point(self, lay: dict, pt: QPointF) -> dict:
        """Punto del lienzo → fracción del contenido de la capa (0–1) y radio del pincel (fracción del alto)."""
        img, cw, ch = T.render_layer(lay)
        inv, _ok = T.layer_transform(lay, img).inverted()
        q = inv.map(pt)
        cw, ch = max(1.0, cw), max(1.0, ch)
        return {"fx": (q.x() - (img.width() - cw) / 2) / cw, "fy": (q.y() - (img.height() - ch) / 2) / ch,
                "r": self.brush / max(float(lay.get("scale", 1.0)) * ch, 1e-6), "aspect": cw / ch}

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
            lay["x"] += dx
            lay["y"] += dy
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
        a = QAction("🖼 Usar en la miniatura", m)
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
        self.history: list[str] = [json.dumps(self.doc)]
        self.pos = 0
        self._last_label, self._last_t = "", 0.0
        self._loading = False
        self.reco: list = []          # fotogramas recomendados (IA)
        self.job = None
        self._cutouts: dict = {}          # fotograma → máscara del personaje (para no recortar dos veces)

        self.canvas = Canvas(self)
        self.canvas.selected.connect(self._on_select)
        self.canvas.committed.connect(self.commit)
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
        split.addWidget(self.canvas)
        split.addWidget(right)
        split.setSizes([360, 820, 340])
        split.setStretchFactor(1, 1)
        self._split = split
        self.setCentralWidget(split)
        self.statusBar().showMessage("Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = girar "
                                     "(Mayús: de 15 en 15) · Supr = borrar · Ctrl+D = duplicar")
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+D", self.duplicate)):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.WidgetWithChildrenShortcut)
        set_help(self, "miniatura")
        self._render_soon = QTimer(self)
        self._render_soon.setSingleShot(True)
        self._render_soon.setInterval(80)
        self._render_soon.timeout.connect(self.canvas.viewport().update)
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

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(3000)
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
                              ("🗑", "Borrar lo elegido (Supr)", self.delete_layer)):
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
        self.act_warp = tb.addAction("◇ Deformar", self.toggle_warp)       # perspectiva libre, como en Photoshop
        self.act_warp.setCheckable(True)
        self.act_warp.setToolTip("Deformar: arrastra cada esquina de lo elegido a donde quieras (perspectiva libre, "
                                 "como «Distorsionar» en Photoshop o «Corner Pin» en Resolve).")
        self.act_unwarp = tb.addAction("↺", self.reset_warp)
        self.act_unwarp.setToolTip("Quitar la deformación de lo elegido")
        self.act_liq = tb.addAction("≈ Licuar", self.toggle_liquify)          # como «Licuar» de Photoshop
        self.act_liq.setCheckable(True)
        self.act_liq.setToolTip("Licuar: pinta sobre lo elegido para inflar, encoger o empujar (ojos saltones, "
                                "bocota…). Modos, tamaño, fuerza y caras graciosas de un clic en el panel derecho.")
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
        tip = QLabel("Clic = añadir encima · doble clic = usar de fondo (llena el lienzo)")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        ml.addWidget(tip)
        self.material = QListWidget()
        self.material.setViewMode(QListView.IconMode)
        self.material.setIconSize(QSize(140, 80))
        self.material.setGridSize(QSize(150, 110))
        self.material.setResizeMode(QListView.Adjust)
        self.material.setMovement(QListView.Static)
        self.material.setWordWrap(True)
        self.material.itemClicked.connect(self._material_click)
        self.material.itemDoubleClicked.connect(lambda it: self.add_image(it.data(Qt.UserRole), "Fondo", fill=True))
        ml.addWidget(self.material, 1)
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
        # Capas
        lw = QWidget()
        ll = QVBoxLayout(lw)
        self.layers = QListWidget()
        self.layers.currentRowChanged.connect(self._layer_row)
        ll.addWidget(self.layers, 1)
        row = QHBoxLayout()
        for text, fn in (("👁", self.toggle_visible), ("🔒", self.toggle_lock), ("⇡", lambda: self.arrange(1)),
                         ("⇣", lambda: self.arrange(-1)), ("⧉", self.duplicate), ("🗑", self.delete_layer)):
            b = QPushButton(text)
            b.setFixedWidth(40)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        tabs.addTab(lw, "Capas")
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

    def _build_png_tab(self) -> QWidget:
        from PySide6.QtWidgets import QLineEdit
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 6, 4, 4)
        row = QHBoxLayout()
        self.png_query = QLineEdit()
        self.png_query.setPlaceholderText("🔎 Buscar PNG: fuego, explosión, logo de…")
        self.png_query.setClearButtonEnabled(True)
        self.png_query.returnPressed.connect(self.search_png)
        row.addWidget(self.png_query, 1)
        b = QPushButton("Buscar")
        b.setObjectName("primary")
        b.clicked.connect(self.search_png)
        row.addWidget(b)
        v.addLayout(row)
        self.png_status = QLabel("Clic derecho en una imagen → «Usar en la miniatura»")
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
        import urllib.parse
        q_full = q if "png" in q.lower() else q + " png"
        self.png_view.load(QUrl(self.PNG_URL.format(q=urllib.parse.quote_plus(q_full))))
        self._split.setSizes([max(560, self._split.sizes()[0]), *self._split.sizes()[1:]])   # (más ancho: se ve mejor)

    def use_png(self, url: str, fallback: str = ""):
        """Clic derecho → «Usar en la miniatura»: se baja, se comprueba (y se le quita el fondo liso) y se añade."""
        from ..ai import thumb_elements as E
        from .jobs import BackgroundJob
        if not url or (self._png_job is not None and self._png_job.isRunning()):
            return

        def work(_p, _c):
            try:
                return E.fetch(url)
            except Exception:  # noqa: BLE001 - la web original no deja bajarla: la de Google
                if not fallback:
                    raise
                return E.fetch(fallback)
        self.png_status.setText("⬇ Bajando la imagen…")
        self._png_job = BackgroundJob(work, self)
        self._png_job.done.connect(self._png_ready)
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
        self._add(lay, "Añadir PNG")
        self.png_status.setText(f"✓ Añadida a la miniatura y a «Material» · {e['badge']}")
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
        self.canvas.sel = sel if self.layer(sel) else ""
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

    def _refresh_layers(self):
        self.layers.blockSignals(True)
        self.layers.clear()
        for lay in reversed(self.doc["layers"]):   # arriba en la lista = delante en el lienzo
            icon = {"image": "🖼", "text": "T", "shape": "◆"}[lay["kind"]]
            flags = ("" if lay.get("visible", True) else "  (oculta)") + ("  🔒" if lay.get("locked") else "")
            it = QListWidgetItem(f"{icon}  {lay['name']}{flags}")
            it.setData(Qt.UserRole, lay["id"])
            self.layers.addItem(it)
            if lay["id"] == self.canvas.sel:
                it.setSelected(True)
                self.layers.setCurrentItem(it)
        self.layers.blockSignals(False)

    def _layer_row(self, row: int):
        it = self.layers.item(row)
        if it is not None:
            self.canvas.sel = it.data(Qt.UserRole)
            self.canvas.viewport().update()
            self._fill_props()

    def _on_select(self, lid: str):
        self._refresh_layers()
        self._fill_props()

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
            it.setToolTip(f"Recomendado por la IA: {', '.join(c.reasons)}\n{m.name if m else ''} · {c.time:.1f} s")
            self.material.addItem(it)
        for m in p.media.values():
            if m.kind == KIND_IMAGE and os.path.exists(m.path):
                it = QListWidgetItem(QIcon(QPixmap(m.path).scaled(140, 80, Qt.KeepAspectRatio,
                                                                 Qt.SmoothTransformation)), m.name[:24])
                it.setData(Qt.UserRole, m.path)
                self.material.addItem(it)
        from ..ai import thumb_elements as E
        for path in E.downloaded()[:60]:                    # 🔎 los PNG que bajaste (los últimos primero)
            it = QListWidgetItem(QIcon(QPixmap(path).scaled(140, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                 "🔎 PNG")
            it.setData(Qt.UserRole, path)
            it.setData(Qt.UserRole + 1, "png")
            it.setToolTip("PNG bajado con «🔎 PNG». Clic = añadirlo · doble clic = de fondo")
            self.material.addItem(it)

    def _material_click(self, it):
        if it.data(Qt.UserRole + 1) == "png":
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

    # ----------------------------------------------------------- ◇ deformar
    def toggle_warp(self, on: bool | None = None):
        """◇ Deformar: en lo elegido, las 4 esquinas se mueven cada una por su lado (perspectiva libre)."""
        on = self.act_warp.isChecked() if on is None else on
        self.act_warp.setChecked(on)
        if on and self.canvas.tool == "liquify":
            self.toggle_liquify(False)
        self.canvas.warp_mode = on
        self.canvas.viewport().update()
        self.statusBar().showMessage("◇ Deformar: arrastra cada esquina naranja a donde quieras · «↺» la quita"
                                     if on else "Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = "
                                                "girar", 8000)

    # ----------------------------------------------------------- ≈ Licuar
    def toggle_liquify(self, on: bool | None = None):
        on = self.act_liq.isChecked() if on is None else on
        self.act_liq.setChecked(on)
        if on and self.act_warp.isChecked():
            self.act_warp.setChecked(False)
            self.canvas.warp_mode = False
        self.canvas.tool = "liquify" if on else None
        self.canvas.setCursor(Qt.BlankCursor if on else Qt.ArrowCursor)
        self.canvas.viewport().update()
        self.statusBar().showMessage("≈ Licuar: pinta sobre lo elegido · modo, tamaño y fuerza en el panel derecho"
                                     if on else "Clic = elegir · arrastrar = mover · esquinas = tamaño · círculo = "
                                                "girar", 8000)
        self._fill_props()

    def set_liq_mode(self, mode: str):
        self.canvas.liq_mode = mode
        if self.canvas.tool != "liquify":
            self.toggle_liquify(True)

    def liquify_dab(self, lay: dict, c: dict, move: tuple[float, float]):
        """Un toque del pincel ≈ Licuar (lo llama el lienzo mientras se pinta)."""
        from ..core import liquify as L
        mode, s = self.canvas.liq_mode, float(self.canvas.liq_strength)
        k = {"inflar": 0.12, "encoger": 0.12, "restaurar": 0.3}.get(mode)
        strength = min(1.0, 0.4 + 0.6 * s) if mode == "empujar" else k * s
        L.stroke(lay, mode, c["fx"], c["fy"], c["r"], strength, c["aspect"], move)
        self.canvas.viewport().update()

    def liquify_done(self):
        self._last_label = ""
        self.commit("Licuar")
        self.canvas.viewport().update()
        self._fill_props()

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
            ok = FF.apply(lay, preset, T._image_content(lay))
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
                "empujar": "Empujar: arrastra y la imagen te sigue",
                "restaurar": "Restaurar: devuelve a su forma lo que pintes"}
        for i, (mode, label) in enumerate((("inflar", "⊕ Inflar"), ("encoger", "⊖ Encoger"),
                                           ("empujar", "➜ Empujar"), ("restaurar", "↺ Restaurar"))):
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
            for i, (key, label, tip) in enumerate(FF.PRESETS):
                b = QPushButton(label)
                b.setToolTip(tip + " (busca la cara más grande de la imagen; Ctrl+Z lo deshace)")
                b.clicked.connect(lambda _=False, k=key: self.funny_face(k))
                g.addWidget(b, 4 + i // 2, i % 2)
        off = QPushButton("↺ Quitar licuado")
        off.setToolTip("Devuelve lo elegido a su forma original")
        off.setEnabled(bool(lay.get("liquify")))
        off.clicked.connect(self.liquify_reset)
        g.addWidget(off, 8, 0, 1, 2)
        self.props_lay.addWidget(box)

    def reset_warp(self):
        lay = self.cur()
        if lay and T.warp_of(lay) and not lay.get("locked"):
            lay.pop("warp", None)
            self._last_label = ""
            self.commit("Quitar deformación")
            self.canvas.viewport().update()

    def delete_layer(self):
        lay = self.cur()
        if lay and not lay.get("locked"):
            self.doc["layers"].remove(lay)
            self.canvas.sel = ""
            self._last_label = ""
            self.commit("Borrar")
            self.canvas.viewport().update()
            self._fill_props()

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

    # ----------------------------------------------------------- recorte del sujeto
    def to_source(self, lay: dict, pt: QPointF) -> tuple[float, float]:
        """Un punto del lienzo → píxel de la imagen ORIGINAL de esa capa (para recuadros y pincel)."""
        img, cw, ch = T.render_layer(lay)
        inv, ok = T.layer_transform(lay, img).inverted()
        q = inv.map(pt)
        cx, cy = q.x() - (img.width() - cw) / 2, q.y() - (img.height() - ch) / 2
        src = QImage(lay["path"])
        x0, y0 = lay["crop"][0] * src.width(), lay["crop"][1] * src.height()
        return x0 + cx, y0 + cy

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

    def cutout_auto(self):
        lay = self.cur()
        if not lay or lay["kind"] != "image":
            return
        from ..ai import bg_removal as BR
        path = lay["path"]
        self._bg_job(lambda: BR.remove(path), lambda m: self._set_mask(lay["id"], m, "Quitar fondo"),
                     "✂ Quitando el fondo… (la primera vez se prepara el modelo)")

    def start_box(self):
        self.canvas.tool = "box"
        self.canvas.setCursor(Qt.CrossCursor)
        self.statusBar().showMessage("Dibuja un recuadro alrededor de lo que quieres conservar.")

    def cutout_box(self, r: QRectF):
        self.canvas.tool = None
        self.canvas.unsetCursor()
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
        if mode:
            self.statusBar().showMessage("Pinta sobre la imagen para " + ("borrar" if mode == "erase" else "recuperar")
                                         + ". Vuelve a pulsar el botón para terminar.")
        self._fill_props()

    def brush_stroke(self, pts: list, restore: bool):
        lay = self.cur()
        if not lay or lay["kind"] != "image" or not pts:
            return
        from ..ai import bg_removal as BR
        src_pts = [self.to_source(lay, p) for p in pts]
        radius = self.canvas.brush / max(lay["scale"], 1e-3)
        m = BR.paint(lay.get("mask"), lay["path"], src_pts, radius, restore)
        self._set_mask(lay["id"], m, "Pincel")

    def _set_mask(self, lid: str, mask: str | None, label: str):
        lay = self.layer(lid)
        if lay is None:
            return
        lay["mask"] = mask
        if mask and label in ("Quitar fondo", "Recortar sujeto"):
            if not lay["outline"]["on"]:
                lay["outline"].update(on=True, color="#FFFFFF", width=6)     # contorno tipo pegatina
                lay["shadow"].update(on=True, blur=20, dx=0, dy=10, opacity=0.6)
            self._fit(lay)
        self._last_label = ""
        self.commit(label)
        self.canvas.viewport().update()
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
        cx = sx - old[0] * src.width() + (img.width() - cw) / 2
        cy = sy - old[1] * src.height() + (img.height() - ch) / 2
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
        if lay["kind"] == "text":
            self._text_props(lay)
        elif lay["kind"] == "shape":
            self._shape_props(lay)
        else:
            self._image_props(lay)
        self._liquify_props(lay)
        self._common_props(lay)
        self._effect_props(lay)
        self._loading = False

    def _set(self, lay: dict, label: str, **kv):
        if self._loading:
            return
        for k, v in kv.items():
            if "." in k:
                a, b = k.split(".")
                lay[a][b] = v
            else:
                lay[k] = v
        self.commit(label)
        self.on_live_change()

    def _slider(self, form, label, lay, key, lo, hi, val, scale=100, sub=None):
        s = QSlider(Qt.Horizontal)
        s.setRange(int(lo * scale), int(hi * scale))
        s.setValue(int(val * scale))
        k = f"{sub}.{key}" if sub else key
        s.valueChanged.connect(lambda v: self._set(lay, label, **{k: v / scale}))
        form.addRow(label, s)
        return s

    def _text_props(self, lay):
        box = QGroupBox("Texto")
        f = QFormLayout(box)
        ed = QPlainTextEdit(lay["text"])
        ed.setFixedHeight(64)
        ed.textChanged.connect(lambda: self._set(lay, "Texto", text=ed.toPlainText(), name=ed.toPlainText()[:20]))
        f.addRow(ed)
        from .spellcheck import attach as _spell
        f.addRow(_spell(ed))
        font = QFontComboBox()
        font.setCurrentFont(lay["font"])
        font.currentFontChanged.connect(lambda fnt: self._set(lay, "Fuente", font=fnt.family()))
        f.addRow("Fuente", font)
        size = QSpinBox()
        size.setRange(8, 600)
        size.setValue(int(lay["size"]))
        size.valueChanged.connect(lambda v: self._set(lay, "Tamaño", size=v))
        f.addRow("Tamaño", size)
        wt = QComboBox()
        for label, v in (("Normal", 400), ("Semi", 600), ("Negrita", 700), ("Extra", 900)):
            wt.addItem(label, v)
        wt.setCurrentIndex(max(0, wt.findData(int(lay["weight"]))))
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
        col = _ColorButton(lay["color"])
        col.changed.connect(lambda c: self._set(lay, "Color", color=c))
        f.addRow("Color", col)
        acc = _ColorButton(lay.get("accent", T.MY_RED))         # lo escrito *entre asteriscos*
        acc.setToolTip("Color de lo que escribas *entre asteriscos* (p. ej. «ESTO ES *MALO*»)")
        acc.changed.connect(lambda c: self._set(lay, "Color de acento", accent=c))
        f.addRow("Acento *…*", acc)
        up = QCheckBox("MAYÚSCULAS")
        up.setChecked(bool(lay["uppercase"]))
        up.toggled.connect(lambda v: self._set(lay, "Mayúsculas", uppercase=v))
        f.addRow(up)
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
        sc = QDoubleSpinBox()
        sc.setRange(0.02, 20)
        sc.setSingleStep(0.05)
        sc.setValue(lay["scale"])
        sc.valueChanged.connect(lambda v: self._set(lay, "Tamaño", scale=v))
        f.addRow("Escala", sc)
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
                                                         ("dy", "Desplaz. Y", -60, 60))),
                                   ("glow", "Brillo", (("radius", "Radio", 2, 120),))):
            e = lay[key]
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
            for fk, fl, lo, hi in fields:
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setValue(int(e[fk]))
                sp.valueChanged.connect(lambda v, k=key, kk=fk, lb=label: self._set(lay, lb, **{f"{k}.{kk}": v}))
                f.addRow("    " + fl, sp)
        self.props_lay.addWidget(box)

