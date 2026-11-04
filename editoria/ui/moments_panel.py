"""
Panel «🔎 Momentos»: busca DÓNDE aparece algo en tus medios y ponlo en la línea de tiempo.

  qué buscas  →  qué encontró (miniaturas, apariciones de inicio a fin)  →  qué puedes hacer

Busca por texto («la Lancer», «un coche rojo»), por una imagen de referencia o por un nombre que
la IA ya aprendió. Cada resultado se puede ver, recortar, insertar en el cabezal, poner en lugar
del clip seleccionado, añadir detrás de él o guardar en favoritos.
"""
from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import QEvent, QItemSelectionModel, QMimeData, QObject, QPointF, QRect, QRectF, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..ai import moments as MO
from ..core import media as media_tools
from ..core.model import KIND_AUDIO, KIND_IMAGE, TRACK_VIDEO
from ..core.paths import cache_dir
from .common import fmt_tc
from .help import set_help
from .jobs import BackgroundJob


def _thumb(path: str, t: float) -> str | None:
    out = os.path.join(str(cache_dir("momentos")), f"{media_tools.cache_key(path)}_{t:.1f}.jpg")
    if not os.path.exists(out):
        media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}",
                               "-i", path, "-frames:v", "1", "-vf", "scale=320:-2", out], timeout=30)
    return out if os.path.exists(out) else None


_ICONS: dict[str, QIcon] = {}


def icon_for(path: str) -> QIcon:
    """Las miniaturas se leen del disco una sola vez (antes, cada ✓/✗ las volvía a cargar todas)."""
    ic = _ICONS.get(path)
    if ic is None:
        ic = QIcon(QPixmap(path))
        if len(_ICONS) > 600:
            _ICONS.clear()
        _ICONS[path] = ic
    return ic


class _MarkDelegate(QStyledItemDelegate):
    """Tarjeta de cada resultado: miniatura redondeada, título y dato secundario. Los botones ✓ / ✗ son dos
    círculos discretos en la esquina superior derecha de la miniatura: aparecen al pasar el ratón (o si ya
    está marcada). Marcada ✓: borde verde · ✗: atenuada."""
    SIZE, GAP, MARGIN = 22, 6, 6

    def __init__(self, panel):
        super().__init__(panel.grid)
        self.panel = panel
        self.hover: tuple[int, str] | None = None     # (fila, "pos"|"neg"|"") bajo el ratón
        panel.grid.setMouseTracking(True)
        panel.grid.viewport().installEventFilter(self)

    def sizeHint(self, option, index):
        """Todas las tarjetas del mismo tamaño que la cuadrícula: el recuadro de la elegida cuadra con su imagen."""
        g = self.panel.grid.gridSize()
        return QSize(g.width() - 4, g.height() - 4)

    def _thumb_rect(self, rect: QRect) -> QRectF:
        iw, ih = self.panel.grid.iconSize().width(), self.panel.grid.iconSize().height()
        return QRectF(rect.center().x() - iw / 2, rect.top() + 4, iw, ih)

    def badges(self, rect: QRect) -> tuple[QRect, QRect]:
        t = self._thumb_rect(rect)
        top = int(t.top()) + self.MARGIN
        x_no = int(t.right()) - self.SIZE - self.MARGIN
        x_ok = x_no - self.GAP - self.SIZE
        return QRect(x_ok, top, self.SIZE, self.SIZE), QRect(x_no, top, self.SIZE, self.SIZE)

    def skip_rect(self, rect: QRect) -> QRect:
        t = self._thumb_rect(rect)
        return QRect(int(t.left()) + self.MARGIN, int(t.top()) + self.MARGIN, self.SIZE, self.SIZE)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseMove, QEvent.Leave):
            new = None
            if ev.type() == QEvent.MouseMove:
                pos = ev.position().toPoint()
                idx = self.panel.grid.indexAt(pos)
                if idx.isValid():
                    vr = self.panel.grid.visualRect(idx)
                    ok, no = self.badges(vr)
                    new = (idx.row(), "pos" if ok.contains(pos) else ("neg" if no.contains(pos) else
                                                                      ("skip" if self.skip_rect(vr).contains(pos) else "")))
                    obj.setCursor(Qt.PointingHandCursor if new[1] else Qt.ArrowCursor)
            if new != self.hover:
                self.hover = new
                obj.update()
        return False

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = self.hover is not None and self.hover[0] == index.row()
        mark = index.data(Qt.UserRole + 1) or "" if self.panel.marks_enabled() else ""
        card = QRectF(rect).adjusted(2, 1, -2, -1)
        # fondo de la tarjeta
        if selected or hovered:
            painter.setPen(QPen(QColor("#e8742f") if selected else QColor(255, 255, 255, 30), 1.2))
            painter.setBrush(QColor(255, 255, 255, 16 if hovered and not selected else 10))
            painter.drawRoundedRect(card, 8, 8)
        if mark == "neg":
            painter.setOpacity(0.38)
        # miniatura recortada para llenar, con esquinas redondeadas
        t = self._thumb_rect(rect)
        path = QPainterPath()
        path.addRoundedRect(t, 6, 6)
        painter.setClipPath(path)
        painter.fillRect(t, QColor("#101114"))
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pix = icon.pixmap(QSize(int(t.width() * 2), int(t.height() * 2)))
            if not pix.isNull():
                k = max(t.width() / pix.width(), t.height() / pix.height())
                w, h = pix.width() * k, pix.height() * k
                painter.drawPixmap(QRectF(t.center().x() - w / 2, t.center().y() - h / 2, w, h), pix,
                                   QRectF(pix.rect()))
        painter.setClipping(False)
        # Barra de identificación: cuánto cree la IA que es lo que buscas (0–100 %)
        if self.panel.marks_enabled():
            painter.save()
            conf = index.data(Qt.UserRole + 2)
            bar = QRectF(t.left() + 5, t.bottom() - 9, t.width() - 10, 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRoundedRect(bar.adjusted(-2, -12, 2, 2), 4, 4)
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRoundedRect(bar, 2.5, 2.5)
            f0 = painter.font()
            f0.setPointSizeF(7.5)
            f0.setBold(True)
            painter.setFont(f0)
            if conf is None:
                painter.setPen(QColor(220, 220, 225))
                painter.drawText(QRectF(bar.left(), bar.top() - 12, bar.width(), 11), Qt.AlignLeft | Qt.AlignVCenter,
                                 "identificando…")
            else:
                c = float(conf)
                col = QColor.fromHsvF(max(0.0, min(1.0, c)) * 0.33, 0.75, 0.95)   # rojo → amarillo → verde
                painter.setBrush(col)
                painter.drawRoundedRect(QRectF(bar.left(), bar.top(), max(5.0, bar.width() * c), bar.height()), 2.5, 2.5)
                painter.setPen(QColor(235, 236, 240))
                painter.drawText(QRectF(bar.left(), bar.top() - 12, bar.width(), 11), Qt.AlignLeft | Qt.AlignVCenter,
                                 f"es lo que buscas: {round(c * 100)} %")
            painter.restore()
        if mark == "pos":
            painter.setPen(QPen(QColor("#2fbf5b"), 2.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(t.adjusted(1, 1, -1, -1), 6, 6)
        # textos: título (una línea) y dato secundario en gris
        lines = (index.data(Qt.DisplayRole) or "").split("\n")
        f = painter.font()
        f.setPointSizeF(max(7.5, f.pointSizeF() * 0.92))
        painter.setFont(f)
        fm = QFontMetrics(f)
        tw = int(t.width())
        y = int(t.bottom()) + 4
        painter.setPen(QColor("#e6e7ea"))
        painter.drawText(QRect(int(t.left()), y, tw, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                         fm.elidedText(lines[0], Qt.ElideRight, tw))
        if len(lines) > 1:
            painter.setPen(QColor("#8b8f98"))
            painter.drawText(QRect(int(t.left()), y + fm.height(), tw, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                             fm.elidedText(lines[1], Qt.ElideRight, tw))
        painter.setOpacity(1.0)
        # «Saltar» (arriba a la izquierda): esconder sin enseñarle nada a la IA
        if self.panel.marks_enabled() and hovered and not mark:
            sr = QRectF(self.skip_rect(rect))
            hot = self.hover[1] == "skip"
            painter.setPen(QPen(QColor(255, 255, 255, 60), 1) if not hot else Qt.NoPen)
            painter.setBrush(QColor("#8b8f98") if hot else QColor(12, 13, 16, 190))
            painter.drawEllipse(sr)
            pen = QPen(QColor("white"), 1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            c = sr.center()
            k = self.SIZE * 0.16
            for dx in (-k * 0.9, k * 0.5):
                painter.drawPolyline([QPointF(c.x() + dx - k * 0.6, c.y() - k), QPointF(c.x() + dx + k * 0.4, c.y()),
                                      QPointF(c.x() + dx - k * 0.6, c.y() + k)])
        # botones ✓ / ✗
        if self.panel.marks_enabled() and (hovered or mark):
            ok, no = self.badges(rect)
            for r, kind, col in ((ok, "pos", QColor("#2fbf5b")), (no, "neg", QColor("#e5484d"))):
                if mark and mark != kind and not hovered:
                    continue
                on = mark == kind
                hot = hovered and self.hover[1] == kind
                painter.setPen(QPen(QColor(255, 255, 255, 60), 1) if not (on or hot) else Qt.NoPen)
                painter.setBrush(col if (on or hot) else QColor(12, 13, 16, 190))
                painter.drawEllipse(QRectF(r))
                pen = QPen(QColor("white") if (on or hot) else QColor(235, 236, 240, 220), 2.0)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                c = QRectF(r).center()
                k = self.SIZE * 0.22
                if kind == "pos":
                    painter.drawPolyline([QPointF(c.x() - k, c.y()), QPointF(c.x() - k * 0.3, c.y() + k * 0.75),
                                          QPointF(c.x() + k, c.y() - k * 0.7)])
                else:
                    painter.drawLine(QPointF(c.x() - k * 0.8, c.y() - k * 0.8), QPointF(c.x() + k * 0.8, c.y() + k * 0.8))
                    painter.drawLine(QPointF(c.x() + k * 0.8, c.y() - k * 0.8), QPointF(c.x() - k * 0.8, c.y() + k * 0.8))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if self.panel.marks_enabled() and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            ok, no = self.badges(option.rect)
            pos = event.position().toPoint()
            if ok.contains(pos):
                self.panel.on_mark(index.row(), True)
                return True
            if no.contains(pos):
                self.panel.on_mark(index.row(), False)
                return True
            if self.skip_rect(option.rect).contains(pos) and not (index.data(Qt.UserRole + 1) or ""):
                self.panel.on_skip(index.row())
                return True
        if self.panel.marks_enabled() and event.type() == QEvent.MouseButtonPress:
            ok, no = self.badges(option.rect)
            pos = event.position().toPoint()
            if ok.contains(pos) or no.contains(pos) or self.skip_rect(option.rect).contains(pos):
                return True               # que el clic en el botón no seleccione ni arrastre
        return super().editorEvent(event, model, option, index)


class _DragFrame(QLabel):
    """La imagen de «Aparición seleccionada»: se puede arrastrar a la línea de tiempo."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._press = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() > 8:
            self._press = None
            payload = self.panel.drag_payload()
            if payload:
                from PySide6.QtGui import QDrag
                from .common import SEGMENT_MIME
                md = QMimeData()
                md.setData(SEGMENT_MIME, payload.encode())
                drag = QDrag(self)
                drag.setMimeData(md)
                pm = self.pixmap()
                if pm is not None and not pm.isNull():
                    drag.setPixmap(pm.scaledToWidth(120, Qt.SmoothTransformation))
                drag.exec(Qt.CopyAction)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)


class MomentsPanel(QWidget):
    def __init__(self, ctrl, engine, timeline, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine, self.timeline = ctrl, engine, timeline
        self.job: BackgroundJob | None = None
        self.results: list[MO.Moment] = []
        self.target_time: float | None = None    # dónde insertar (cabezal o una frase de la transcripción)
        self.query_label = ""
        self.web_results: list[dict] = []     # las que se ven, en orden (las filas de la cuadrícula)
        self.web_all: dict[str, dict] = {}    # todas las encontradas, por id
        self.web_vecs: dict = {}              # huella de cada miniatura (para aprender de ✓/✗)
        self.web_tvec = None
        self.web_query = ""
        self.web_fb = {"pos": {}, "neg": {}}
        self.web_ranked: list[dict] = []
        self.local_query = ""                 # búsqueda local con ✓/✗ (texto o nombre conocido)
        self.local_base: list = []            # lo que encontró la búsqueda
        self.local_fb = {"pos": {}, "neg": {}}
        self.local_marks: dict[str, str] = {}
        self.local_ranked: list[dict] = []
        self.asked: set[str] = set()          # lo que ya preguntó «¿es esto?» (o saltaste)
        self._pending_vecs: dict[str, str] = {}  # marcadas antes de tener su huella → miniatura
        self._downloading: set[str] = set()       # ✓ que se están guardando en Medios
        self._skipped: set[str] = set()           # «Saltar»: escondidas sin enseñarle nada a la IA
        self._dl_jobs: set = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        # --- dónde buscas: tus archivos o internet (separados)
        src = QHBoxLayout()
        src.addWidget(QLabel("Buscar en:"))
        self.source = QComboBox()
        self.source.addItem("📁 Mis archivos", "local")
        self.source.addItem("🌐 Internet (imágenes libres para uso comercial)", "web")
        self.source.addItem("🌐 Internet — también licencias con restricciones (⚠ uso bajo tu responsabilidad)",
                            "web_all")
        self.source.currentIndexChanged.connect(self._source_changed)
        src.addWidget(self.source, 1)
        self.b_google = QPushButton("Google Imágenes ↗")
        self.b_google.setToolTip("Abre la búsqueda en tu navegador (ahí revisa tú la licencia de cada imagen).")
        self.b_google.clicked.connect(self._open_google)
        self.b_google.hide()
        src.addWidget(self.b_google)
        self.b_paste = QPushButton("📋 Pegar imagen")
        self.b_paste.setToolTip("Copia una imagen en tu navegador (clic derecho → «Copiar imagen», p. ej. desde "
                                "Google Imágenes) y pégala aquí (o Ctrl+V): va directo a Medios.\n⚠ Puede tener "
                                "derechos de autor: úsala bajo tu responsabilidad (crítica / comentario).")
        self.b_paste.clicked.connect(self.paste_image)
        self.b_paste.hide()
        src.addWidget(self.b_paste)
        lay.addLayout(src)

        # --- qué buscas
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("¿Qué buscas? Un personaje, objeto, lugar, escena…")
        self.query.returnPressed.connect(self.search_text)
        b_go = QPushButton("🔎 Buscar")
        b_go.setObjectName("primary")
        b_go.clicked.connect(self.search_text)
        self.b_example = QPushButton("🎯 Ejemplo")
        self.b_example.setToolTip("Enséñale a la IA lo que buscas con un clip o imagen de tu línea de tiempo (el "
                                  "seleccionado, o el del cabezal): eliges el momento, si quieres dibujas un "
                                  "recuadro, y cuenta como una ✓. También: clic derecho en un clip o en Medios.")
        self.b_example.clicked.connect(self.example_from_timeline)
        b_img = QPushButton("🖼 Por imagen…")
        b_img.setToolTip("Elige una imagen de lo que buscas (una foto, una captura): la IA busca momentos parecidos.")
        b_img.clicked.connect(self.search_image_file)
        row.addWidget(self.query, 1)
        row.addWidget(b_go)
        row.addWidget(self.b_example)
        row.addWidget(b_img)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Lo que conoce la IA:"))
        self.known = QComboBox()
        self.known.setToolTip("Nombres que aprendió al «Entender tu biblioteca a fondo». Elige uno para ver dónde aparece.")
        self.known.activated.connect(self._known_selected)
        row2.addWidget(self.known, 1)
        b_fav = QPushButton("⭐ Favoritos")
        b_fav.clicked.connect(self.show_favorites)
        row2.addWidget(b_fav)
        lay.addLayout(row2)

        # --- qué encontró
        self.status = QLabel("Escribe lo que buscas, o elige una imagen de referencia.")
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        split = QSplitter(Qt.Vertical)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(160, 90))
        self.grid.setGridSize(QSize(176, 136))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(4)
        self.grid.currentRowChanged.connect(self._select)
        self.grid.itemDoubleClicked.connect(lambda _it: self.place("insert"))
        self.grid.setItemDelegate(_MarkDelegate(self))
        gw = QWidget()
        gl = QVBoxLayout(gw)
        gl.setContentsMargins(0, 0, 0, 0)
        self.ask_card = QFrame()
        self.ask_card.setObjectName("askcard")
        self.ask_card.setStyleSheet("#askcard { border: 1px solid rgba(232,116,47,0.55); border-radius: 6px; }")
        ak = QHBoxLayout(self.ask_card)
        ak.setContentsMargins(4, 2, 4, 2)
        ak.setSpacing(6)
        self.ask_card.setMaximumHeight(64)
        self.ask_img = QLabel()
        self.ask_img.setFixedSize(100, 56)
        self.ask_img.setAlignment(Qt.AlignCenter)
        self.ask_img.setStyleSheet("background:#000;")
        self.ask_text = QLabel()
        self.ask_text.setWordWrap(True)
        self.b_yes = QPushButton("✓ Sí")
        self.b_yes.setObjectName("primary")
        self.b_no = QPushButton("✗ No")
        self.b_skip = QPushButton("Saltar")
        for b in (self.b_yes, self.b_no, self.b_skip):
            b.setFixedHeight(26)
        self.b_yes.clicked.connect(lambda: self._answer(True))
        self.b_no.clicked.connect(lambda: self._answer(False))
        self.b_skip.clicked.connect(lambda: self._answer(None))
        ak.addWidget(self.ask_img)
        ak.addWidget(self.ask_text, 1)
        for b in (self.b_yes, self.b_no, self.b_skip):
            ak.addWidget(b)
        self.ask_card.hide()
        self._ask_id = None
        gl.addWidget(self.ask_card)
        gl.addWidget(self.grid, 1)
        self.web_bar = QWidget()
        wb = QHBoxLayout(self.web_bar)
        wb.setContentsMargins(0, 2, 0, 0)
        self.b_more = QPushButton("✨ Buscar más como las ✓")
        self.b_more.setToolTip("Trae más imágenes y las ordena por parecido a las que marcaste ✓")
        self.b_more.clicked.connect(lambda: self.search_web(self.web_query, more=True))
        self.chk_save_ok = QCheckBox("✓ = guardar en Medios")
        self.chk_save_ok.setToolTip("Al marcar ✓ una imagen de internet, se descarga y aparece en Medios (Internet).")
        from PySide6.QtCore import QSettings as _QS
        self.chk_save_ok.setChecked(str(_QS("EditorIA", "EditorIA").value("momentos/guardar_ok", "true")).lower()
                                    == "true")
        self.chk_save_ok.toggled.connect(lambda on: _QS("EditorIA", "EditorIA").setValue(
            "momentos/guardar_ok", "true" if on else "false"))
        wb.addWidget(self.chk_save_ok)
        self.chk_quality = QCheckBox("Solo buena calidad")
        self.chk_quality.setChecked(True)
        self.chk_quality.setToolTip("Esconde las imágenes pequeñas (menos de 800 px por su lado mayor).")
        self.chk_quality.toggled.connect(lambda _on: self._apply_rank() if self._web() else None)
        wb.addWidget(self.chk_quality)
        self.b_local = QPushButton("📁 Buscar en mis archivos")
        self.b_local.setToolTip("Para personajes de videojuegos casi no hay imágenes libres en internet: en tus "
                                "propios videos (gameplay, tráilers) suele estar lo mejor. Usa también «🎯 Ejemplo».")
        self.b_local.clicked.connect(self._search_local_instead)
        self.b_local.hide()
        wb.addWidget(self.b_local)
        self.chk_hidden = QCheckBox("Mostrar las escondidas")
        self.chk_hidden.setToolTip("Las que la IA cree que no son, y las que marcaste ✗")
        self.chk_hidden.toggled.connect(lambda _on: self._apply_rank() if self._web() else self._apply_local_rank())
        wb.addWidget(self.b_more)
        wb.addWidget(self.chk_hidden)
        wb.addStretch()
        self.b_top = QPushButton("⤒ Inicio")
        self.b_top.setObjectName("flat")
        self.b_top.setToolTip("Volver arriba de los resultados (la lista nunca salta sola al principio)")
        self.b_top.clicked.connect(self.grid.scrollToTop)
        wb.addWidget(self.b_top)
        self.web_bar.hide()
        gl.addWidget(self.web_bar)
        split.addWidget(gw)

        # --- qué puedes hacer
        box = QGroupBox("Aparición seleccionada")
        bl = QGridLayout(box)
        bl.setContentsMargins(6, 4, 6, 4)
        bl.setVerticalSpacing(3)
        self.video = QVideoWidget()
        self.video.setFixedSize(176, 99)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._loop_check)
        self.video.installEventFilter(self)          # arrastrar también mientras se reproduce
        self.video.setCursor(Qt.OpenHandCursor)
        self.video.setToolTip("Arrástralo a la línea de tiempo para ponerlo donde lo sueltes")
        self._vpress = None
        self.frame = _DragFrame(self)
        self.frame.setFixedSize(176, 99)
        self.frame.setToolTip("Arrástrala a la línea de tiempo para ponerla donde la sueltes")
        self.frame.setAlignment(Qt.AlignCenter)
        self.frame.setStyleSheet("background:#000;")
        bl.addWidget(self.frame, 0, 0, 4, 1)
        bl.addWidget(self.video, 0, 0, 4, 1)
        self.video.hide()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        bl.addWidget(self.info, 0, 1, 1, 3)
        bl.addWidget(QLabel("Desde"), 1, 1)
        self.t_in = QDoubleSpinBox()
        self.t_out = QDoubleSpinBox()
        for sp in (self.t_in, self.t_out):
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.setRange(0, 1e6)
        self.t_in.setToolTip("Recorta el inicio antes de insertarlo")
        self.t_out.setToolTip("Recorta el final antes de insertarlo")
        bl.addWidget(self.t_in, 1, 2)
        bl.addWidget(QLabel("hasta"), 1, 3)
        bl.addWidget(self.t_out, 1, 4)
        self.b_play = QPushButton("▶ Ver")
        self.b_play.clicked.connect(self.preview)
        b_src = QPushButton("📂 Ver en medios")
        b_src.setToolTip("Muestra el archivo de donde sale en el panel de medios")
        b_src.clicked.connect(self._show_source)
        self.b_fav = QPushButton("⭐")
        self.b_fav.setToolTip("Guardar en favoritos (o quitar)")
        self.b_fav.clicked.connect(self._toggle_fav)
        bl.addWidget(self.b_play, 2, 1)
        bl.addWidget(b_src, 2, 2)
        bl.addWidget(self.b_fav, 2, 3)
        acts = QHBoxLayout()
        for text, mode, tip in (("⤓ Usar: insertar en el cabezal", "insert", "En el cabezal (o en la frase que elegiste), "
                                 "en una pista de video libre: no tapa nada."),
                                ("⇄ Reemplazar clip", "replace", "Pone este momento en lugar del clip seleccionado "
                                 "(misma posición y duración)."),
                                ("⇥ Añadir después", "after", "Justo detrás del clip seleccionado.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mode: self.place(m))
            acts.addWidget(b)
        bl.addLayout(acts, 4, 0, 1, 5)
        for b in box.findChildren(QPushButton):
            b.setFixedHeight(26)
        box.setMaximumHeight(190)
        split.addWidget(box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        self.grid.setMinimumHeight(170)
        split.setSizes([620, 170])
        lay.addWidget(split, 1)
        set_help(self, "momentos")
        ctrl.media_changed.connect(self.refresh_known)
        self.refresh_known()

    # --------------------------------------------------------------- datos
    def _data(self) -> tuple[dict, dict]:
        p = self.ctrl.project
        data, meta = {}, {}
        for mid, (times, vecs) in self.ctrl.clip_vecs.items():
            m = p.media.get(mid)
            if m is None or m.kind == KIND_AUDIO or mid in self.ctrl.missing:
                continue
            data[mid] = {"times": times, "vecs": vecs, "kind": m.kind, "duration": m.duration}
            meta[mid] = " ".join([m.name, m.category] + list(m.tags)).replace("_", " ")
        return data, meta

    def refresh_known(self):
        u = self.ctrl.understanding or {}
        cur = self.known.currentText()
        self.known.clear()
        self.known.addItem("— elige un nombre —", None)
        for e in u.get("entities", []):
            n = len(u.get("index", {}).get(e.name, []))
            if n:
                self.known.addItem(f"{e.name}  ({n})", e.name)
        from ..ai import silhouette_id as SI
        for name, n in SI.names().items():
            self.known.addItem(f"👤 {name}  ({n} ejemplo{'s' if n != 1 else ''})", "sil:" + name)
        self.known.addItem("👤 Enseñar un personaje por su silueta…", "sil+")
        i = self.known.findText(cur)
        if i >= 0:
            self.known.setCurrentIndex(i)

    # ------------------------------------------------------------- buscar
    def search_for(self, text: str, at: float | None = None):
        """Buscar desde otro sitio (p. ej. una frase de la transcripción); at = dónde insertarlo."""
        self.query.setText(text)
        self.target_time = at
        self.search_text()

    def _web(self) -> bool:
        return self.source.currentData() in ("web", "web_all")

    def _restricted(self) -> bool:
        return self.source.currentData() == "web_all"

    def marks_enabled(self) -> bool:
        return self._web() or bool(self.local_query)

    def _source_changed(self, _i=0):
        web = self._web()
        self.web_bar.setVisible(web and bool(self.web_all))
        self.b_google.setVisible(web)
        self.b_paste.setVisible(web)
        self.known.setEnabled(not web)
        self.grid.clear()
        self.results, self.web_results = [], []
        self.ask_card.hide()
        self._ask_id = None
        if self._restricted():
            self.status.setText("⚠ Incluye imágenes con licencias que NO permiten uso comercial o cambios. Tu canal "
                                "está monetizado: úsalas bajo tu responsabilidad (p. ej. crítica o comentario) y "
                                "revisa la licencia de cada una. ✓ = se guarda en Medios.")
        else:
            self.status.setText("🌐 Internet: ✓ = esta es (se guarda en Medios) · ✗ = no es."
                                if web else "Escribe lo que buscas, o elige una imagen de referencia.")

    def _open_google(self):
        from PySide6.QtCore import QUrl as _Q
        from PySide6.QtGui import QDesktopServices
        import urllib.parse
        q = self.query.text().strip()
        if q:
            QDesktopServices.openUrl(_Q("https://www.google.com/search?tbm=isch&q=" + urllib.parse.quote(q)))

    def search_web(self, q: str, more: bool = False):
        from ..ai import image_feedback as IF
        from ..ai import web_images as WI
        if self.job is not None or not q:
            return
        from .understand_dialog import glossary_text
        if not more or q != self.web_query:
            self.web_all, self.web_vecs, self.web_results, self.web_ranked = {}, {}, [], []
            self.grid.clear()
        self.web_query = q
        self.web_fb = IF.load_feedback(q)
        self.asked = set()
        self.query_label = f"«{q}» en internet"
        queries = IF.expand_query(q, glossary_text())
        self._web_queries = list(queries)
        if more:
            titles = [self.web_all[i]["title"] for i in self.web_fb["pos"] if i in self.web_all]
            queries = IF.related_queries(titles, q) + queries
        self.status.setText(f"🌐 Buscando «{q}»" + (f" (también: {', '.join(queries[1:])})" if len(queries) > 1 else "")
                            + " en Openverse (imágenes con licencia libre)…")
        cache = str(cache_dir("momentos"))
        seen = set(self.web_all)
        pages = 4 if more else 3
        commercial = not self._restricted()

        def work(progress, cancelled, partial):
            res = WI.search_many(queries, pages=pages, seen=seen, cancelled=cancelled, commercial=commercial)
            partial(("web", res))
            try:
                tvec = IF.text_vec([q] + queries[1:2])
            except Exception:  # noqa: BLE001 - sin el modelo de IA: se muestran sin filtrar
                tvec = None
            partial(("tvec", tvec))
            for it in res:
                if cancelled():
                    break
                th = WI.thumb_path(it, cache)
                try:
                    if not os.path.exists(th):
                        WI.fetch(it["thumbnail"], th, timeout=15, limit=3_000_000)
                    vec = IF.image_vec(th) if tvec is not None else None
                    partial(("thumb", it["id"] or it["url"], th, vec))
                except Exception:  # noqa: BLE001 - una miniatura que no carga no detiene el resto
                    pass
            return len(res)

        self.job = BackgroundJob(work, self, with_partial=True)
        self.job.partial.connect(self._on_partial)
        self.job.done.connect(lambda _n: (setattr(self, "job", None), self._apply_rank(final=True),
                                          self._fill_pending_vecs()))
        self.job.failed.connect(lambda msg: (setattr(self, "job", None),
                                             self.status.setText("✗ No se pudo buscar en internet: " + msg)))
        self.job.start()

    # ---------------------------------------------------------- videos: ✓/✗ y aprender
    def _ckey(self, m) -> str:
        """La huella del archivo (para nombres de miniaturas y marcas), calculada una vez por archivo."""
        memo = self.__dict__.setdefault("_ck_memo", {})
        k = memo.get(m.path)
        if k is None:
            k = memo[m.path] = media_tools.cache_key(m.path)
        return k

    def _mkey(self, r) -> str:
        m = self.ctrl.project.media.get(r.media_id)
        base = self._ckey(m) if m else r.media_id
        return base if r.kind == "image" else f"{base}@{round(r.best, 1)}"

    def _moment_vec(self, data: dict, r):
        d = data.get(r.media_id)
        if d is None or not len(d["vecs"]):
            return None
        times = np.asarray(d["times"], np.float32)
        k = int(np.argmin(np.abs(times - r.best))) if len(times) else 0
        return np.asarray(d["vecs"][k], np.float32)

    def _apply_local_rank(self):
        """Ordena los momentos según lo que buscas y tus ✓/✗: con ✓, además busca MÁS apariciones parecidas."""
        from ..ai import image_feedback as IF
        data, _meta = self._data()
        fb = self.local_fb
        cands = list(self.local_base)
        pos_raw = np.asarray(list(fb["pos"].values()), np.float32) if fb["pos"] else None
        neg_raw = np.asarray(list(fb["neg"].values()), np.float32) if fb["neg"] else None
        if pos_raw is not None and data:
            try:
                more = MO.search_image(pos_raw, data, top=40)
            except Exception:  # noqa: BLE001
                more = []
            for r in more:
                if not any(c.media_id == r.media_id and (abs(c.best - r.best) < 2.0 or
                                                         (c.start <= r.best <= c.end)) for c in cands):
                    r.score = 0.0               # no venía de lo que escribiste: lo trae tu ✓
                    cands.append(r)
        if not data:
            self.results, self.local_marks = cands, {}
            self._fill()
            return
        sig = tuple((mid, len(d["vecs"])) for mid, d in data.items())
        cache = self.__dict__.get("_mu_cache")
        if cache is not None and cache[0] == sig:          # la media de tus videos no cambia entre ✓ y ✓
            mu = cache[1]
        else:
            n = sum(len(d["vecs"]) for d in data.values())
            mu = sum(np.asarray(d["vecs"], np.float32).sum(0) for d in data.values() if len(d["vecs"])) / max(1, n)
            self._mu_cache = (sig, mu)

        def center(v):
            c = np.atleast_2d(np.asarray(v, np.float32)) - mu
            return c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)
        by_key, vecs, base = {}, {}, {}
        for r in cands:
            k = self._mkey(r)
            if k in by_key:
                continue
            by_key[k] = r
            v = self._moment_vec(data, r)
            vecs[k] = center(v)[0] if v is not None else None
            base[k] = r.score
        marks = {k: "pos" for k in fb["pos"]} | {k: "neg" for k in fb["neg"]}
        ranked = IF.rank_items(list(by_key), base, vecs, center(pos_raw) if pos_raw is not None else None,
                               center(neg_raw) if neg_raw is not None else None, marks, hide_below=None)
        for x in ranked:
            if x["id"] in self._skipped and not x["mark"]:
                x["hidden"], x["why"] = True, "saltada"
        self.local_ranked = ranked
        show_hidden = self.chk_hidden.isChecked()
        cur = self.results[self.grid.currentRow()] if 0 <= self.grid.currentRow() < len(self.results) else None
        self.results = [by_key[x["id"]] for x in ranked if show_hidden or not x["hidden"]]
        self.local_marks = marks
        self._fill()
        self.web_bar.setVisible(True)
        self.b_more.setVisible(False)
        if cur is not None and cur in self.results:
            self.grid.setCurrentRow(self.results.index(cur))
        self._ask()

    def _mark_local(self, row: int, good: bool | None):
        from ..ai import image_feedback as IF
        if not (0 <= row < len(self.results)) or not self.local_query:
            return
        r = self.results[row]
        k = self._mkey(r)
        data, _ = self._data()
        v = self._moment_vec(data, r)
        current = "pos" if k in self.local_fb["pos"] else ("neg" if k in self.local_fb["neg"] else "")
        want = None if good is None else ("pos" if good else "neg")
        IF.mark(self.local_fb, k, v if v is not None else [0.0] * 512, None if current == want else good)
        IF.save_feedback(self.local_query, self.local_fb, "videos")
        self._apply_local_rank()
        self._refresh_entity_soon()
        n_ok, n_no = len(self.local_fb["pos"]), len(self.local_fb["neg"])
        self.status.setText(f"{self.query_label}: ✓ {n_ok} · ✗ {n_no}. Con cada ✓ busco más momentos parecidos; "
                            "lo que marcas ✗ se aparta. Se recuerda para la próxima vez.")

    def _refresh_entity_soon(self):
        """Si buscas un nombre que la IA conoce, tus ✓/✗ le enseñan cómo es (para el B-roll y las búsquedas)."""
        if not hasattr(self, "_ent_timer"):
            self._ent_timer = QTimer(self)
            self._ent_timer.setSingleShot(True)
            self._ent_timer.setInterval(2500)
            self._ent_timer.timeout.connect(self._refresh_entity)
        self._ent_timer.start()

    def _refresh_entity(self):
        from ..ai import library_understanding as LU
        u = self.ctrl.understanding
        if not u or self.job is not None:
            return
        old = getattr(self, "_ent_job", None)
        try:
            running = old is not None and old.isRunning()
        except RuntimeError:
            running = False
        if running:                       # ya hay uno: se repite al acabar (no se amontonan)
            self._ent_again = True
            return
        self._ent_again = False
        ent = next((e for e in u.get("entities", []) if LU.matches(e, self.local_query)), None)
        if ent is None:
            return
        p = self.ctrl.project
        media = [m for m in p.media.values() if m.kind in (KIND_IMAGE, "video") and m.id not in self.ctrl.missing]

        def work(_prog, _canc):
            data, meta = {}, {}
            for m in media:
                res = LU.load_deep(m.path)
                if res is not None:
                    data[m.id] = dict(res, kind=m.kind, duration=m.duration)
                    meta[m.id] = " ".join([m.name, m.category] + list(m.tags))
            return LU.build_index([ent], data, meta).get(ent.name)

        def done(hits):
            if hits is not None and self.ctrl.understanding is u:
                u.setdefault("index", {})[ent.name] = hits
                self.refresh_known()
            if getattr(self, "_ent_again", False):
                self._ent_again = False
                self._refresh_entity_soon()
        self._ent_job = BackgroundJob(work, self)
        self._ent_job.done.connect(done)
        self._ent_job.start()

    def _ask(self):
        """(La tarjeta «🤔 ¿Es esto?» de arriba ya no se usa: cada imagen lleva su barra de identificación.)"""
        self.ask_card.hide()
        self._ask_id = None
        return
        from ..ai import image_feedback as IF
        ranked = self.web_ranked if self._web() else self.local_ranked
        if not self.marks_enabled() or not ranked:
            self.ask_card.hide()
            self._ask_id = None
            return
        self._ask_id = IF.next_question(ranked, self.asked)
        self._show_question()

    def _show_question(self):
        from ..ai import web_images as WI
        if self._ask_id is None:
            self.ask_card.hide()
            return
        q = self.web_query if self._web() else self.local_query
        pix = QPixmap()
        if self._web():
            it = self.web_all.get(self._ask_id)
            if it is not None:
                th = WI.thumb_path(it, str(cache_dir("momentos")))
                pix = QPixmap(th) if os.path.exists(th) else pix
                where = it["title"][:40]
        else:
            r = next((x for x in self.results if self._mkey(x) == self._ask_id), None)
            if r is None:
                self.ask_card.hide()
                return
            m = self.ctrl.project.media.get(r.media_id)
            th = os.path.join(str(cache_dir("momentos")), f"{media_tools.cache_key(m.path)}_{r.best:.1f}.jpg") if m else ""
            pix = QPixmap(th) if th and os.path.exists(th) else pix
            where = f"{m.name[:30] if m else ''} · {fmt_tc(r.best, self.ctrl.project.fps)[:8]}"
        self.ask_img.setPixmap(pix.scaled(self.ask_img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                               if not pix.isNull() else QPixmap())
        self.ask_text.setText(f"🤔 <b>La IA encontró esto</b> ({where}). ¿Es <b>«{q}»</b>?")
        self.ask_card.show()

    def _answer(self, good: bool | None):
        key = self._ask_id
        if key is None:
            return
        self.asked.add(key)
        if good is not None:
            if self._web():
                row = next((i for i, it in enumerate(self.web_results) if (it["id"] or it["url"]) == key), -1)
                if row >= 0:
                    self.on_mark(row, good)
            else:
                row = next((i for i, r in enumerate(self.results) if self._mkey(r) == key), -1)
                if row >= 0:
                    self._mark_local(row, good)
        self._ask()

    def on_mark(self, row: int, good: bool):
        """✓ «esta es» / ✗ «no es» (pulsar otra vez la misma quita la marca)."""
        from ..ai import image_feedback as IF
        from ..ai import web_images as WI
        if not self._web():
            self._mark_local(row, good)
            return
        if not (0 <= row < len(self.web_results)):
            return
        it = self.web_results[row]
        key = it["id"] or it["url"]
        vec = self.web_vecs.get(key)
        current = "pos" if key in self.web_fb["pos"] else ("neg" if key in self.web_fb["neg"] else "")
        want = "pos" if good else "neg"
        # La huella de la imagen NUNCA se calcula aquí (cargar el modelo congelaba la ventana): si aún no
        # está, se marca ya y la huella se completa en segundo plano.
        IF.mark(self.web_fb, key, vec if vec is not None else [0.0] * 512, None if current == want else good)
        if vec is None and current != want:
            self._pending_vecs[key] = WI.thumb_path(it, str(cache_dir("momentos")))
            self._fill_pending_vecs()
        if good and current != want and self.chk_save_ok.isChecked():
            self._download_to_media(it)
        IF.save_feedback(self.web_query, self.web_fb)
        self._apply_rank()
        n_ok, n_no = len(self.web_fb["pos"]), len(self.web_fb["neg"])
        self.status.setText(f"🌐 {self.query_label}: ✓ {n_ok} buenas · ✗ {n_no} descartadas. Las parecidas a tus ✓ "
                            "suben; las parecidas a tus ✗ se apartan. «✨ Buscar más como las ✓» trae más.")

    def _download_to_media(self, it: dict):
        """✓ en una imagen de internet: se descarga (en segundo plano) y aparece en Medios («Internet»)."""
        from ..ai import web_images as WI
        key = it["id"] or it["url"]
        if it.get("media_id") in self.ctrl.project.media or key in self._downloading:
            return
        self._downloading.add(key)
        name = WI.safe_name(self.web_query) or None     # se guarda con lo que buscaste y un número
        job = BackgroundJob(lambda _p, _c: WI.download(it, name), self)

        def done(path):
            self._downloading.discard(key)
            self._dl_jobs.discard(job)
            ids = self.ctrl.import_paths([path])
            if not ids:
                return
            restricted = it["license"] and any(x in it["license"].split("-") for x in ("nc", "nd"))
            self.ctrl.set_media_props(ids, category=f"Internet/{name}" if name else "Internet",
                                      tags=[it["license_text"], it["creator"]] + (["⚠ licencia con restricciones"]
                                                                                  if restricted else []))
            it["media_id"] = ids[0]
            self.ctrl.message.emit(f"⬇ Guardada en Medios (Internet): «{it['title'][:50]}» · {it['license_text']}"
                                   + (" — da crédito en la descripción (créditos.txt)"
                                      if it["license"] not in ("cc0", "pdm") else ""))

        def failed(msg):
            self._downloading.discard(key)
            self._dl_jobs.discard(job)
            self.ctrl.message.emit(f"✗ No se pudo descargar «{it['title'][:40]}»: {msg[:120]}")
        job.done.connect(done)
        job.failed.connect(failed)
        self._dl_jobs.add(job)
        job.start()

    def paste_image(self):
        """📋 Imagen copiada en el navegador (p. ej. de Google Imágenes) → Medios, con aviso de derechos."""
        from PySide6.QtWidgets import QApplication
        from ..ai import web_images as WI
        md = QApplication.clipboard().mimeData()
        img = QApplication.clipboard().image()
        if img.isNull() and md is not None and md.hasUrls():
            local = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if local:
                from PySide6.QtGui import QImage
                img = QImage(local[0])
        if img.isNull():
            self.status.setText("📋 No hay ninguna imagen copiada. En el navegador: clic derecho sobre la imagen → "
                                "«Copiar imagen», y vuelve a pulsar «📋 Pegar imagen».")
            return
        q = self.query.text().strip()
        try:
            path = WI.save_pasted(img, q)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"✗ {exc}")
            return
        ids = self.ctrl.import_paths([path])
        if ids:
            self.ctrl.set_media_props(ids, category="Internet",
                                      tags=["© derechos de autor"] + ([q] if q else []))
        self.status.setText(f"📋 Imagen pegada y guardada en Medios ({img.width()}×{img.height()}). ⚠ Puede tener "
                            "derechos de autor: úsala para crítica/comentario y, si quieres, transfórmala "
                            "(clic derecho en el clip → «🛡 Transformar»).")

    def keyPressEvent(self, e):
        from PySide6.QtGui import QKeySequence
        if e.matches(QKeySequence.Paste) and self._web():
            self.paste_image()
            return
        if e.key() == Qt.Key_Escape and self.video.isVisible():
            self.stop_preview()
            return
        super().keyPressEvent(e)

    @staticmethod
    def _conf(r: dict, center: float = 0.0) -> float | None:
        """De la nota de la IA a «es lo que buscas: 0–100 %» (✓ = 100 %, ✗ = 0 %, sin huella aún = None)."""
        import math
        if r.get("mark") == "pos":
            return 1.0
        if r.get("mark") == "neg":
            return 0.0
        if r.get("why") == "sin miniatura todavía":
            return None
        return 1.0 / (1.0 + math.exp(-1.3 * (float(r.get("score", 0.0)) - center)))

    def on_skip(self, row: int):
        """«Saltar»: la esconde de la lista sin marcarla ✓ ni ✗ (se ve con «Mostrar las escondidas»)."""
        if self._web():
            if 0 <= row < len(self.web_results):
                it = self.web_results[row]
                self._skipped.add(it["id"] or it["url"])
                self._apply_rank()
        elif 0 <= row < len(self.results):
            self._skipped.add(self._mkey(self.results[row]))
            self._apply_local_rank()

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "video", None):
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self._vpress = e.position().toPoint()
            elif e.type() == QEvent.MouseMove and self._vpress is not None and \
                    (e.position().toPoint() - self._vpress).manhattanLength() > 8:
                self._vpress = None
                payload = self.drag_payload()
                if payload:
                    from PySide6.QtGui import QDrag
                    from .common import SEGMENT_MIME
                    md = QMimeData()
                    md.setData(SEGMENT_MIME, payload.encode())
                    drag = QDrag(self.video)
                    drag.setMimeData(md)
                    drag.exec(Qt.CopyAction)
                return True
            elif e.type() == QEvent.MouseButtonRelease:
                self._vpress = None
        return super().eventFilter(obj, e)

    def drag_payload(self) -> str | None:
        """«id|desde|hasta» del momento elegido, para soltarlo en la línea de tiempo."""
        if self._web():
            i = self.grid.currentRow()
            if not (0 <= i < len(self.web_results)):
                return None
            it = self.web_results[i]
            mid = it.get("media_id")
            if mid not in self.ctrl.project.media:
                self._download_to_media(it)
                self.status.setText("⬇ Descargando la imagen a Medios… arrástrala otra vez en un momento.")
                return None
            return f"{mid}|0|{max(1.0, self.t_out.value()):.3f}"
        r = self._cur()
        if r is None:
            return None
        a, b = self.t_in.value(), self.t_out.value()
        if r.kind == "image":
            a, b = 0.0, max(1.0, b)
        return f"{r.media_id}|{a:.3f}|{max(a + 0.2, b):.3f}"

    def _search_local_instead(self):
        q = self.query.text().strip() or self.web_query
        self.source.setCurrentIndex(self.source.findData("local"))
        self.query.setText(q)
        self.search_text()

    def _fill_pending_vecs(self):
        """Huellas de las imágenes que marcaste antes de que estuvieran listas (en segundo plano)."""
        from ..ai import image_feedback as IF
        if not self._pending_vecs or self.job is not None or getattr(self, "_vec_job", None) is not None:
            return      # si hay una búsqueda en marcha, las huellas llegan con ella
        todo = dict(self._pending_vecs)

        def work(_p, _c):
            out = {}
            for key, th in todo.items():
                try:
                    out[key] = IF.image_vec(th) if os.path.exists(th) else None
                except Exception:  # noqa: BLE001
                    out[key] = None
            return out

        def done(res):
            self._vec_job = None
            for key, vec in res.items():
                self._got_vec(key, vec)
        self._vec_job = BackgroundJob(work, self)
        self._vec_job.done.connect(done)
        self._vec_job.failed.connect(lambda _m: setattr(self, "_vec_job", None))
        self._vec_job.start()

    def _got_vec(self, key: str, vec):
        """Llega la huella de una imagen: si estaba marcada sin huella, se completa y se reordena."""
        from ..ai import image_feedback as IF
        self._pending_vecs.pop(key, None)
        if vec is None:
            return
        self.web_vecs[key] = vec
        for side in ("pos", "neg"):
            if key in self.web_fb[side]:
                self.web_fb[side][key] = list(np.asarray(vec, np.float32))
                IF.save_feedback(self.web_query, self.web_fb)
                self._apply_rank()
                break

    def _apply_rank(self, final: bool = False):
        """Ordena y filtra lo encontrado según lo que buscas y tus ✓/✗, conservando la selección."""
        from ..ai import image_feedback as IF
        if not self._web():
            return
        ids = list(self.web_all)
        qs = getattr(self, "_web_queries", [self.web_query])
        bonus = {i: IF.title_bonus(self.web_all[i]["title"], qs) for i in ids}
        ranked = IF.rank(ids, self.web_vecs, self.web_tvec, self.web_fb, bonus)
        # Calidad: las pequeñas (menos de 800 px por su lado mayor) se esconden si está activado
        if self.chk_quality.isChecked():
            for r in ranked:
                it = self.web_all[r["id"]]
                w, h = int(it.get("width") or 0), int(it.get("height") or 0)
                if w and h and max(w, h) < 800 and r["mark"] != "pos":
                    r["hidden"], r["why"] = True, f"pequeña ({w}×{h})"
        for r in ranked:
            if r["id"] in self._skipped and not r["mark"]:
                r["hidden"], r["why"] = True, "saltada"
        self.web_ranked = ranked
        show_hidden = self.chk_hidden.isChecked()
        cur = self.web_results[self.grid.currentRow()] if 0 <= self.grid.currentRow() < len(self.web_results) else None
        self.web_results = [self.web_all[r["id"]] for r in ranked if show_hidden or not r["hidden"]]
        self.b_local.setVisible(final and len(self.web_results) < 8)
        info = {r["id"]: r for r in ranked}
        self._fill_web(info)
        if cur is not None and cur in self.web_results:
            self.grid.blockSignals(True)      # se vuelve a marcar la elegida sin recargar ni mover la vista
            self.grid.setCurrentItem(self.grid.item(self.web_results.index(cur)), QItemSelectionModel.ClearAndSelect)
            self.grid.blockSignals(False)
        hidden = sum(1 for r in ranked if r["hidden"])
        if final or self.web_fb["pos"] or self.web_fb["neg"]:
            self._ask()
        if final:
            self.status.setText(f"🌐 {self.query_label}: {len(self.web_results)} imágenes"
                                + (f" · escondí {hidden} que no parecen lo que buscas" if hidden and not show_hidden
                                   else "") + ". ✓ = esta es · ✗ = no es. No se descarga nada hasta «Usar».")

    def search_text(self):
        q = self.query.text().strip()
        if not q:
            return
        if self._web():
            return self.search_web(q)
        data, meta = self._data()
        if not data:
            self.status.setText("Primero la IA tiene que analizar tus clips (botón ◈ del panel de medios, "
                                "o mejor «🔬 Entender mi biblioteca a fondo»).")
            from .nudge import nudge_for
            nudge_for(self.status.text())
            return
        # ¿Es un nombre que la IA ya aprendió? Entonces se usan sus apariciones (más fiable)
        u = self.ctrl.understanding or {}
        from ..ai.library_understanding import matches
        ent = next((e for e in u.get("entities", []) if u.get("index", {}).get(e.name) and matches(e, q)), None)
        self.local_query = q
        if ent is not None:
            self._run(lambda: MO.from_hits(u["index"][ent.name], data), f"«{ent.name}»")
            return
        paths = {mid: self.ctrl.project.media[mid].path for mid in data if mid in self.ctrl.project.media}
        self._run(lambda: MO.search_text(q, data, meta, paths=paths), f"«{q}»")

    # ------------------------------------------------------- 🎯 enseñar con un ejemplo
    def example_from_timeline(self):
        """El clip o imagen seleccionado en la línea de tiempo (o el que se ve en el cabezal)."""
        p = self.ctrl.project
        vis = [p.clips[i] for i in sorted(self.timeline.selected) if i in p.clips]
        vis = [c for c in vis if c.text is None and p.media_of(c) is not None and p.media_of(c).kind != KIND_AUDIO]
        if not vis:
            t = self.engine.time
            vis = [c for c in p.clips.values() if c.text is None and c.start <= t < c.end and c.enabled
                   and p.media_of(c) is not None and p.media_of(c).kind != KIND_AUDIO]
            vis.sort(key=lambda c: next((i for i, tr in enumerate(p.tracks) if tr.id == c.track_id), 99))
        if not vis:
            self.status.setText("🎯 Selecciona en la línea de tiempo el clip o la imagen donde se ve lo que buscas "
                                "(o clic derecho en un archivo de Medios → «🎯 Usar como ejemplo»).")
            from .nudge import nudge
            nudge(self.timeline)
            return
        self.example_from_clip(vis[0].id)

    def example_from_clip(self, clip_id: str):
        p = self.ctrl.project
        c = p.clips.get(clip_id)
        m = p.media_of(c) if c else None
        if c is None or m is None or m.kind == KIND_AUDIO:
            return
        t = self.engine.time if c.start <= self.engine.time < c.end else c.start + c.duration / 2
        src = self.ctrl.clip_source_time(c.id, t)
        a, b = sorted((self.ctrl.clip_source_time(c.id, c.start), self.ctrl.clip_source_time(c.id, c.end - 0.04)))
        self._example(m.id, src, a, b)

    def example_from_media(self, media_id: str, t: float | None = None):
        m = self.ctrl.project.media.get(media_id)
        if m is None or m.kind == KIND_AUDIO:
            return
        self._example(m.id, m.duration / 2 if t is None else t, 0.0, m.duration)

    def _example(self, media_id: str, t: float, a: float, b: float):
        from .example_dialog import ExampleDialog
        self.engine.pause()
        name = self.query.text().strip() if not self._web() else ""
        dlg = ExampleDialog(self.ctrl, media_id, t, a, b, name or self.local_query, self.window(),
                            on_example=lambda ex: self.add_example(ex, search=False))
        # Sin bloquear el editor: así el indicador de progreso (encima del visor) se puede detener
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        self._example_dlg = dlg
        dlg.finished.connect(lambda _r, d=dlg: self._example_closed(d))
        dlg.show()

    def _example_closed(self, dlg):
        nm = dlg.name.text().strip()
        if dlg.do_search and nm:
            if self._web():
                self.source.setCurrentIndex(self.source.findData("local"))
            self.query.setText(nm)
            self.search_text()
            self._refresh_entity_soon()

    def add_example(self, ex: dict, search: bool = True):
        """Guarda el ejemplo como ✓ (o ✗) de esa búsqueda y busca."""
        from ..ai import image_feedback as IF
        if self._web():
            self.source.setCurrentIndex(self.source.findData("local"))
        name = ex["name"]
        fb = IF.load_feedback(name, "videos")
        IF.mark(fb, ex["key"], ex["vec"], ex["good"])
        IF.save_feedback(name, fb, "videos")
        self.query.setText(name)
        self.status.setText(f"🎯 Ejemplo guardado como {'✓' if ex['good'] else '✗'} de «{name}»."
                            + (" Buscando…" if search else ""))
        if search:
            self.search_text()
            self._refresh_entity_soon()

    def search_image_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagen de referencia", "",
                                              "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp);;Todos (*.*)")
        if path:
            self.search_image(path)

    def search_image(self, path: str, exclude: str | None = None, label: str | None = None):
        data, _meta = self._data()
        if not data:
            self.status.setText("Primero la IA tiene que analizar tus clips.")
            from .nudge import nudge_for
            nudge_for(self.status.text())
            return
        self.local_query = ""          # por imagen: sin palabras que aprender
        self._run(lambda: MO.search_image(MO.encode_image_file(path), data, exclude=exclude),
                  label or f"parecido a «{os.path.basename(path)}»")

    def _known_selected(self, _i):
        name = self.known.currentData()
        if not name:
            return
        if name == "sil+":
            self.known.setCurrentIndex(0)
            win = self.window()
            if hasattr(win, "open_silhouette_teach"):
                win.open_silhouette_teach()
            return
        if name.startswith("sil:"):
            self.search_silhouette(name[4:])
            return
        u = self.ctrl.understanding or {}
        data, _ = self._data()
        self.query.setText(name)
        self.local_query = name
        self._run(lambda: MO.from_hits(u.get("index", {}).get(name, []), data), f"«{name}»")

    def search_silhouette(self, name: str):
        """👤 Dónde sale el personaje que le enseñaste por su silueta (recorre tus videos; lo recorrido se guarda)."""
        from ..ai import silhouette_id as SI
        p = self.ctrl.project
        videos = [(m.id, m.path, float(m.duration or 0)) for m in p.media.values()
                  if m.kind == "video" and m.id not in self.ctrl.missing]
        if not videos:
            self.status.setText("Importa antes algún video donde buscarlo.")
            return
        self.query.setText(name)
        self.local_query = ""
        self._run(lambda progress, cancelled: SI.search(name, videos, progress, cancelled), f"👤 «{name}»",
                  with_progress=True)

    def show_favorites(self):
        favs = self.ctrl.project.favorites
        p = self.ctrl.project
        self.results = [MO.Moment(f["media_id"], f["start"], f["end"], (f["start"] + f["end"]) / 2, 0.0,
                                  "image" if p.media[f["media_id"]].kind == KIND_IMAGE else "video")
                        for f in favs if f["media_id"] in p.media]
        self.query_label = "⭐ Favoritos"
        self.local_query = ""
        self.ask_card.hide()
        self._fill()

    def _run(self, fn, label: str, with_progress: bool = False):
        if self.job is not None:
            return
        self.query_label = label
        self.status.setText(f"🔎 Buscando {label} en tus medios…")
        self.grid.clear()
        p = self.ctrl.project
        paths = {m.id: m.path for m in p.media.values()}

        def work(progress, cancelled, partial):
            res = fn(progress, cancelled) if with_progress else fn()
            partial(("results", res))
            for i, r in enumerate(res):     # miniaturas, poco a poco
                if cancelled():
                    break
                th = _thumb(paths[r.media_id], r.best)
                if th:
                    partial(("lthumb", r, th))
            return len(res)

        self.job = BackgroundJob(work, self, with_partial=True)
        self.job.partial.connect(self._on_partial)
        if with_progress:
            self.job.progress.connect(lambda _f, txt: self.status.setText(txt) if txt else None)
        self.job.done.connect(lambda _n: setattr(self, "job", None))
        self.job.failed.connect(lambda msg: (setattr(self, "job", None), self.status.setText("✗ " + msg)))
        self.job.start()

    def _on_partial(self, msg):
        if msg[0] == "results":
            from ..ai import image_feedback as IF
            self.local_base = list(msg[1])
            self.asked = set()
            self.local_fb = IF.load_feedback(self.local_query, "videos") if self.local_query else {"pos": {}, "neg": {}}
            if self.local_query:
                self._apply_local_rank()
            else:
                self.results = msg[1]
                self.local_marks = {}
                self._fill()
        elif msg[0] == "lthumb":
            _k, mom, path = msg
            row = next((i for i, r in enumerate(self.results) if r is mom), -1)
            item = self.grid.item(row) if row >= 0 else None
            if item is not None:
                item.setIcon(icon_for(path))
            if row >= 0 and row == self.grid.currentRow():
                self._select(row)
            if self._ask_id is not None:
                self._show_question()
        elif msg[0] == "web":
            for it in msg[1]:
                self.web_all.setdefault(it["id"] or it["url"], it)
            self._apply_rank()
        elif msg[0] == "tvec":
            self.web_tvec = msg[1]
        elif msg[0] == "thumb":
            _k, key, path, vec = msg
            if vec is not None:
                self.web_vecs[key] = vec
                if key in self._pending_vecs:
                    self._got_vec(key, vec)
            row = next((i for i, it in enumerate(self.web_results) if (it["id"] or it["url"]) == key), -1)
            item = self.grid.item(row) if row >= 0 else None
            if item is not None:
                item.setIcon(icon_for(path))
            if row >= 0 and row == self.grid.currentRow():   # la vista grande, en cuanto hay imagen
                self._select(row)

    def _fill(self):
        self._keep_scroll()
        ranked_by = {x["id"]: x for x in (self.local_ranked if self.local_query else [])}
        mdir = str(cache_dir("momentos"))
        self.grid.clear()
        p = self.ctrl.project
        files = set()
        for r in self.results:
            m = p.media.get(r.media_id)
            if m is None:
                continue
            files.add(r.media_id)
            when = "imagen" if r.kind == "image" else f"{fmt_tc(r.start, p.fps)[:8]} → {fmt_tc(r.end, p.fps)[:8]}"
            it = QListWidgetItem(f"{m.name[:22]}\n{when}")
            it.setToolTip(f"{m.name}\n{when}" + (f"\nseguridad {r.score:.1f}" if r.score else "")
                          + ("\n\n✓ = aquí está · ✗ = no es" if self.local_query else ""))
            it.setData(Qt.UserRole + 1, self.local_marks.get(self._mkey(r), ""))
            lr = ranked_by.get(self._mkey(r))
            it.setData(Qt.UserRole + 2, self._conf(lr, 2.6) if lr else
                       (1.0 / (1.0 + __import__("math").exp(-1.3 * (r.score - 2.6))) if r.score else None))
            th = os.path.join(mdir, f"{self._ckey(m)}_{r.best:.1f}.jpg")
            if th in _ICONS or os.path.exists(th):
                it.setIcon(icon_for(th))
            self.grid.addItem(it)
        n = len(self.results)
        self.status.setText(f"{self.query_label}: {n} apariciones en {len(files)} archivo(s)." if n else
                            f"No encontré {self.query_label} en tus medios.")
        if n:
            self.grid.setCurrentRow(0)

    def _keep_scroll(self):
        """Recuerda dónde estabas en la lista y vuelve ahí después de rehacerla (no salta al principio)."""
        bar = self.grid.verticalScrollBar()
        v = bar.value()
        QTimer.singleShot(0, lambda: bar.setValue(min(v, bar.maximum())))
        return v

    def _fill_web(self, info: dict | None = None):
        from ..ai import web_images as WI
        scrolled = self._keep_scroll()
        self.grid.clear()
        cache = str(cache_dir("momentos"))
        for it in self.web_results:
            key = it["id"] or it["url"]
            r = (info or {}).get(key, {})
            res = f" · {it['width']}×{it['height']}" if it.get("width") else ""
            if it.get("license") and any(x in it["license"].split("-") for x in ("nc", "nd")):
                res += " · ⚠"
            item = QListWidgetItem(f"{it['title']}\n{it['license_text']}{res}")
            item.setToolTip(f"{it['title']}\nAutor: {it['creator']}\nLicencia: {it['license_text']}"
                            f" · {it.get('source', 'Openverse')}\n{it['page']}"
                            + (f"\n{r['why']}" if r.get("why") else "") + "\n\n✓ = esta es · ✗ = no es")
            item.setData(Qt.UserRole + 1, r.get("mark", ""))
            item.setData(Qt.UserRole + 2, self._conf(r) if r else None)
            th = WI.thumb_path(it, cache)
            if os.path.exists(th):
                item.setIcon(icon_for(th))
            self.grid.addItem(item)
        n = len(self.web_results)
        self.web_bar.setVisible(True)
        self.b_more.setEnabled(bool(self.web_fb["pos"]) or n > 0)
        if not n:
            self.status.setText(f"🌐 Sin resultados para {self.query_label}.")
        elif self.grid.currentRow() < 0 and not scrolled:
            self.grid.setCurrentRow(0)

    def _select_web(self, i: int):
        it = self.web_results[i]
        th = os.path.join(str(cache_dir("momentos")), "")
        from ..ai import web_images as WI
        th = WI.thumb_path(it, str(cache_dir("momentos")))
        pix = QPixmap(th) if os.path.exists(th) else QPixmap()
        self.frame.setPixmap(pix.scaled(self.frame.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                             if not pix.isNull() else QPixmap())
        for sp in (self.t_in, self.t_out):
            sp.setEnabled(False)
        self.t_out.setValue(4.0)
        need = "" if it["license"] in ("cc0", "pdm") else "<br>⚠ Pide dar crédito: se guarda en «créditos.txt»."
        self.info.setText(f"<b>🌐 {it['title']}</b><br>Autor: {it['creator']} · {it['license_text']} · "
                          f"{it['width']}×{it['height']}{need}")
        self.b_play.setText("🌐 Abrir su página")

    def _use_web(self, i: int) -> str | None:
        """Descarga la imagen elegida (solo ahora) y la añade a la biblioteca. Devuelve su id."""
        from ..ai import web_images as WI
        it = self.web_results[i]
        if it.get("media_id") in self.ctrl.project.media:
            return it["media_id"]
        try:
            path = WI.download(it)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"✗ No se pudo descargar: {exc}")
            return None
        ids = self.ctrl.import_now([path])
        if not ids:
            return None
        self.ctrl.set_media_props(ids, category="Internet", tags=[it["license_text"], it["creator"]])
        it["media_id"] = ids[0]
        if it["license"] not in ("cc0", "pdm"):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(it["attribution"])
            self.ctrl.message.emit("Imagen con licencia " + it["license_text"] + ": da crédito en la descripción "
                                   "del video (copiado al portapapeles y guardado en «créditos.txt»).")
        return ids[0]

    # --------------------------------------------------------- selección
    def _cur(self) -> MO.Moment | None:
        if self._web():
            return None
        i = self.grid.currentRow()
        return self.results[i] if 0 <= i < len(self.results) else None

    def _select(self, _row):
        if self._web():
            self.b_play.setText("🌐 Abrir su página")
            if 0 <= self.grid.currentRow() < len(self.web_results):
                self._select_web(self.grid.currentRow())
            return
        self.b_play.setText("▶ Ver")
        r = self._cur()
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        if self.player.playbackState() != _QMP.StoppedState:   # (parar sin necesidad a veces se queda colgado)
            self.player.pause()
        self.video.hide()
        self.frame.show()
        if r is None:
            self.info.setText("")
            return
        p = self.ctrl.project
        m = p.media[r.media_id]
        th = os.path.join(str(cache_dir("momentos")), f"{self._ckey(m)}_{r.best:.1f}.jpg")
        pix = QPixmap(th) if os.path.exists(th) else QPixmap()
        self.frame.setPixmap(pix.scaled(self.frame.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                             if not pix.isNull() else QPixmap())
        img = r.kind == "image"
        for sp in (self.t_in, self.t_out):
            sp.setEnabled(not img)
            sp.setMaximum(max(0.1, m.duration))
        a, b = r.start, r.end
        if not img and b - a < 2.0:            # muy corto para usarlo: 3 s alrededor del mejor momento
            a = max(0.0, r.best - 1.5)
            b = min(max(m.duration, a + 0.5), a + 3.0)
        self.t_in.setValue(a)
        self.t_out.setValue(b if not img else 4.0)
        where = "imagen" if img else (f"{fmt_tc(r.start, p.fps)} → {fmt_tc(r.end, p.fps)}  ({r.end - r.start:.1f} s) · "
                                      f"mejor momento {fmt_tc(r.best, p.fps)}")
        fav = any(f["media_id"] == r.media_id and abs(f["start"] - r.start) < 0.05 for f in p.favorites)
        self.b_fav.setText("⭐ Quitar" if fav else "⭐")
        self.info.setText(f"<b>{m.name}</b><br>{where}")

    def preview(self):
        if self._web():
            i = self.grid.currentRow()
            if 0 <= i < len(self.web_results):
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(self.web_results[i]["page"]))
            return
        r = self._cur()
        if r is None or r.kind == "image":
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:      # ⏹ Parar
            self.stop_preview()
            return
        m = self.ctrl.project.media[r.media_id]
        self.frame.hide()
        self.video.show()
        self.b_play.setText("⏹ Parar")
        self._loop = (self.t_in.value(), self.t_out.value())
        self.player.setSource(QUrl.fromLocalFile(self.ctrl.preview_path(m)))
        self.player.setPosition(int(self._loop[0] * 1000))
        self.player.play()

    def _loop_check(self, pos_ms: int):
        lp = getattr(self, "_loop", None)
        if lp and pos_ms / 1000 >= lp[1]:
            self.player.pause()
            self.b_play.setText("▶ Ver")

    def stop_preview(self):
        """⏹ Para la vista previa del momento y vuelve a la imagen (arrastrable)."""
        self.player.stop()
        self.video.hide()
        self.frame.show()
        self.b_play.setText("▶ Ver")

    def _show_source(self):
        r = self._cur()
        if r is not None and hasattr(self.window(), "show_panel"):
            lib = self.window().library
            self.window().show_panel(lib)
            if hasattr(lib, "select_media"):
                lib.select_media(r.media_id)

    def _toggle_fav(self):
        r = self._cur()
        if r is None:
            return
        on = self.ctrl.toggle_favorite(r.media_id, r.start, r.end, self.query_label)
        self.b_fav.setText("⭐ Quitar" if on else "⭐")

    # ------------------------------------------------------------ colocar
    def place(self, mode: str):
        if self.video.isVisible():
            self.stop_preview()
        if self._web():   # imagen de internet: se descarga ahora (la elegiste tú) y se coloca
            i = self.grid.currentRow()
            if not (0 <= i < len(self.web_results)):
                return
            mid = self._use_web(i)
            if mid is None:
                return
            self.results = [MO.Moment(mid, 0.0, 0.0, 0.0, 0.0, "image")]
            r = self.results[0]
        else:
            r = self._cur()
        if r is None:
            return
        a, b = self.t_in.value(), self.t_out.value()
        if r.kind == "image":
            a, b = 0.0, max(1.0, self.t_out.value())
        if b - a < 0.2:
            self.status.setText("El tramo es demasiado corto: revisa «Desde» y «hasta».")
            return
        sel = [c for c in (self.ctrl.project.clips.get(i) for i in self.timeline.selected)
               if c is not None and self.ctrl.project.track(c.track_id).kind == TRACK_VIDEO and c.text is None]
        target = sel[0].id if sel else None
        if mode in ("replace", "after") and target is None:
            self.status.setText("Selecciona antes en la línea de tiempo el clip de video con el que trabajar.")
            from .nudge import nudge_for
            nudge_for(self.status.text())
            return
        t = self.target_time if self.target_time is not None else self.engine.time
        cid = self.ctrl.place_segment(r.media_id, a, b - a, mode, t, target, note=f"IA: {self.query_label}")
        if isinstance(cid, str):
            self.timeline.set_selection([cid])
            self.target_time = None
            QTimer.singleShot(0, lambda: self.engine.user_seek(self.ctrl.project.clips[cid].start))
