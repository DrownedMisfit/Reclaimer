"""
Panel izquierdo: biblioteca de medios, búsqueda y organización por categorías.

Búsqueda:
  - normal: por nombre, categoría, carpeta y lo que la IA vio en el clip
  - ◈ por contenido: escribe una frase ("Marcus peleando contra varios enemigos")
    y pulsa Enter; la IA ordena los clips por parecido y encuentra el mejor momento.
"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStyle,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..ai import clip_analysis, embeddings
from ..ai import keyword_glossary as KG
from ..ai.mentions import find_mentions
from ..core import keyword_folders as KF
from ..core import keyword_place as KP
from ..core.model import AUDIO_EXT, IMAGE_EXT, KIND_AUDIO, KIND_IMAGE, VIDEO_EXT
from ..core.organize import CATEGORY_ORDER, matches_query
from . import help as help_ui
from .common import MEDIA_MIME, NOAUDIO_MIME, fmt_time, modo_archivo_suelto
from .help import add_help_action, set_help
from .jobs import BackgroundJob

MEDIA_FILTER = "Medios ({});;Todos los archivos (*.*)".format(
    " ".join(f"*{e}" for e in sorted(VIDEO_EXT | AUDIO_EXT | IMAGE_EXT)))

ROLE_MEDIA = Qt.UserRole
ROLE_CATEGORY = Qt.UserRole + 1
ROLE_MOMENT = Qt.UserRole + 2   # mejor momento (resultados de la búsqueda IA)
ROLE_KW_KIND = Qt.UserRole + 3  # sección de palabras clave: "term" (palabra), "link" (carpeta del PC), "file"
ROLE_KW_TERM = Qt.UserRole + 4  # la palabra clave a la que pertenece el nodo
ROLE_PATH = Qt.UserRole + 5     # ruta: archivo de una palabra o carpeta enlazada (o la subcarpeta propia)
ROLE_KW_LINKED = Qt.UserRole + 6  # archivo que viene de una carpeta enlazada del PC
KW_SECTION = "__palabras__"     # categoría de la sección «🔑 Palabras clave» (no es una carpeta de Medios)


def _kw_root() -> str:
    """La carpeta raíz de las palabras clave (la misma que usa el panel 🎬 Clips)."""
    from .clips_panel import _raiz_guardada
    return _raiz_guardada()


def _corta_ruta(ruta: str, largo: int = 46) -> str:
    return ruta if len(ruta) <= largo else "…" + ruta[-(largo - 1):]


def _pick_terms(parent, opciones: list) -> list | None:
    """Casillas (preseleccionadas) con las palabras a crear. None si cancela."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Crear carpetas para lo que dices")
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("Se creará una carpeta por cada palabra marcada.\n"
                         "Desmarca las que no quieras."))
    cajas = []
    for op in opciones:                      # (término, veces) o (término, veces, marcada por defecto)
        term, n = op[0], op[1]
        marcada = op[2] if len(op) > 2 else True
        cb = QCheckBox(f"{term}  ·  {n} {'vez' if n == 1 else 'veces'}")
        cb.setChecked(bool(marcada))
        if not marcada:
            cb.setToolTip("Según internet no es un juego, consola ni compañía: márcala si sí es palabra clave.")
        lay.addWidget(cb)
        cajas.append((cb, term))
    botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    botones.button(QDialogButtonBox.Ok).setText("Crear")
    botones.accepted.connect(dlg.accept)
    botones.rejected.connect(dlg.reject)
    lay.addWidget(botones)
    if dlg.exec() != QDialog.Accepted:
        return None
    return [t for cb, t in cajas if cb.isChecked()]


def _to_trash(path: str) -> bool:
    """A la Papelera de Windows (recuperable). Según la versión de Qt devuelve bool o (bool, ruta)."""
    from PySide6.QtCore import QFile
    r = QFile.moveToTrash(path)
    return bool(r[0] if isinstance(r, tuple) else r)


class MediaTree(QTreeWidget):
    move_requested = Signal(list, str)     # (ids, categoría) — soltar archivos sobre una carpeta de Medios
    delete_pressed = Signal()
    kw_dropped = Signal(list, str)         # (rutas del Explorador, palabra) — soltar sobre una palabra clave
    kw_media_dropped = Signal(list, str)   # (ids de Medios, palabra) — arrastrar desde Medios a una palabra: se enlaza
    kw_header_dropped = Signal(list, bool) # (rutas o ids, ¿son de Medios?) — soltar sobre «🔑 Palabras clave»: pide nombre
    resolve_paths = None                   # función(rutas) -> ids: importa al vuelo (lo pone el panel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHeaderLabels(["Nombre", "Duración", "Info", ""])      # 4.ª: «⋮» opciones rápidas
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setIconSize(QSize(64, 36))
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 58)
        self.header().setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.header().setSectionResizeMode(3, QHeaderView.Fixed)
        self.setColumnWidth(3, 26)

    def selected_media_ids(self) -> list[str]:
        out = []
        for it in self.selectedItems():
            mid = it.data(0, ROLE_MEDIA)
            if mid and mid not in out:
                out.append(mid)
        return out

    def event(self, e):
        # Con Medios enfocado, Supr es para Medios (no para borrar clips de la línea de tiempo)
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ShortcutOverride and e.key() == Qt.Key_Delete and self.selected_media_ids():
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self.selected_media_ids():
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)

    def _folder_at(self, pos):
        it = self.itemAt(pos)
        while it is not None and it.data(0, ROLE_CATEGORY) is None:
            it = it.parent()
        return it.data(0, ROLE_CATEGORY) if it is not None else None

    def _kw_term_at(self, pos) -> str | None:
        """La palabra clave bajo el cursor (la propia o la de un enlace/archivo suyo), o None."""
        it = self.itemAt(pos)
        while it is not None:
            if it.data(0, ROLE_KW_KIND):
                return it.data(0, ROLE_KW_TERM)
            it = it.parent()
        return None

    def _urls_externos(self, e) -> list[str]:
        if e.source() is self or not e.mimeData().hasUrls():
            return []
        return [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]

    def _kw_zone(self, pos) -> tuple[str | None, bool]:
        """(palabra clave bajo el cursor, ¿está en la cabecera «🔑 Palabras clave»?)."""
        term = self._kw_term_at(pos)
        if term:
            return term, False
        it = self.itemAt(pos)
        while it is not None and it.data(0, ROLE_CATEGORY) != KW_SECTION:
            it = it.parent()
        return None, it is not None

    def dragEnterEvent(self, e):
        if e.source() is self and e.mimeData().hasFormat(MEDIA_MIME):
            e.acceptProposedAction()
        elif self._urls_externos(e) and any(self._kw_zone(e.position().toPoint())):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        pos = e.position().toPoint()
        cat = self._folder_at(pos)
        if e.source() is self and e.mimeData().hasFormat(MEDIA_MIME) and (
                (cat and cat != KW_SECTION) or any(self._kw_zone(pos))):
            e.acceptProposedAction()
        elif self._urls_externos(e) and any(self._kw_zone(pos)):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        pos = e.position().toPoint()
        term, cabecera = self._kw_zone(pos)
        if e.source() is self and e.mimeData().hasFormat(MEDIA_MIME):
            ids = [i for i in e.mimeData().data(MEDIA_MIME).data().decode().split(",") if i]
            cat = self._folder_at(pos)
            if term:                              # Medios → palabra clave: se ENLAZA (no se copia)
                self.kw_media_dropped.emit(ids, term)
            elif cabecera:
                self.kw_header_dropped.emit(ids, True)
            elif cat and cat != KW_SECTION:
                self.move_requested.emit(ids, cat)
            else:
                e.ignore()
                return
            e.acceptProposedAction()
            return
        rutas = self._urls_externos(e)
        if rutas and term:
            self.kw_dropped.emit(rutas, term)     # carpetas → enlazar · archivos → copiar o enlazar (pregunta el panel)
            e.acceptProposedAction()
        elif rutas and cabecera:
            self.kw_header_dropped.emit(rutas, False)
            e.acceptProposedAction()
        else:
            e.ignore()                            # lo demás llega al panel (importar)

    def startDrag(self, actions):
        ids = self.selected_media_ids()
        # archivos de «🔑 Palabras clave» que aún no están en Medios: se importan al vuelo para arrastrarlos
        sin_id = [it.data(0, ROLE_PATH) for it in self.selectedItems()
                  if it.data(0, ROLE_KW_KIND) == "file" and not it.data(0, ROLE_MEDIA) and it.data(0, ROLE_PATH)]
        if sin_id and self.resolve_paths is not None:
            ids += [i for i in self.resolve_paths(sin_id) if i and i not in ids]
        if not ids:
            return
        mime = QMimeData()
        mime.setData(MEDIA_MIME, QByteArray(",".join(ids).encode()))
        if self.selectedItems() and all(it.data(0, ROLE_KW_KIND) == "file" for it in self.selectedItems()):
            mime.setData(NOAUDIO_MIME, QByteArray(b"1"))     # 🔇 material de Palabras clave: sin su audio
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = self.currentItem().icon(0) if self.currentItem() else QIcon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(64, 36))
        drag.exec(Qt.CopyAction | Qt.MoveAction)


class LibraryPanel(QWidget):
    def select_media(self, media_id: str):
        """Selecciona y muestra un archivo en la lista (p. ej. «de dónde viene este momento»)."""
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if item.data(0, ROLE_MEDIA) == media_id:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return
            it += 1

    add_requested = Signal(list)               # media ids para añadir en el cabezal
    add_at_times_requested = Signal(list, list, str)   # 🔑 (media ids, instantes, texto del paso de deshacer)
    keyword_target = None                      # 🔑 función () → {"word","t","times"} o None (la pone la ventana)
    keywords_requested = Signal(list)          # 🔑 buscar palabras clave en estos archivos
    obs_marks_requested = Signal(list)         # 🔖 leer las marcas de OBS (capítulos) de estos archivos
    add_moment_requested = Signal(str, float)
    example_requested = Signal(str, object)     # 🎯 usar como ejemplo de lo que busco (media_id, segundo o None)  # media id + mejor momento (búsqueda IA)

    def __init__(self, ctrl, analyzer, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.analyzer = analyzer
        self._icons: dict[str, QIcon] = {}
        self._results: list[tuple[str, float, float]] | None = None  # búsqueda IA
        self._results_query = ""
        self._search_job: BackgroundJob | None = None
        self.setAcceptDrops(True)

        title = QLabel("Panel de medios")
        title.setObjectName("title")
        self.btn_files = QPushButton("＋ Archivos")
        self.btn_files.setToolTip("Importar uno o varios archivos")
        self.btn_folder = QPushButton("＋ Carpeta")
        self.btn_folder.setToolTip("Importar una carpeta completa (con subcarpetas)")
        self.btn_files.clicked.connect(self.import_files_dialog)
        self.btn_folder.clicked.connect(self.import_folder_dialog)
        self.btn_analyze = QPushButton("◈")
        self.btn_analyze.setFixedWidth(36)
        self.btn_analyze.setToolTip("Analizar el contenido de los clips con IA (qué se ve en cada uno).\n"
                                    "La primera vez descarga los modelos (~500 MB). Funciona en tu PC.")
        self.btn_analyze.clicked.connect(self._analyze_clicked)
        set_help(self.btn_analyze, "analizar_clips")

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self._on_search_enter)
        self.btn_ai_search = QPushButton("◈ Buscar")
        self.btn_ai_search.setCheckable(True)
        self.btn_ai_search.setToolTip("Buscar por CONTENIDO: describe lo que quieres ver y pulsa Enter.\n"
                                      "Ej.: «Marcus peleando contra varios enemigos», «una cinemática triste».")
        self.btn_ai_search.toggled.connect(self._on_mode)
        set_help(self.search, "buscar")
        set_help(self.btn_ai_search, "buscar")
        srow = QHBoxLayout()
        srow.addWidget(self.search, 1)
        srow.addWidget(self.btn_ai_search)

        self._kw_collapsed: set = set()     # palabras clave que el usuario plegó (se recuerdan al recargar)
        self.btn_kw_new = QPushButton("＋ Palabra clave")
        self.btn_kw_new.setToolTip("Crea una palabra clave (su carpeta en Reclaimer). Luego añade carpetas de tu PC.")
        self.btn_kw_auto = QPushButton("✨ Crear de lo que dices")
        self.btn_kw_auto.setToolTip("Crea una carpeta para cada palabra que dices en la narración y aún no tiene.")
        self.btn_kw_refresh = QPushButton("⟳")
        self.btn_kw_refresh.setFixedWidth(34)
        self.btn_kw_refresh.setToolTip("Volver a leer las palabras clave y sus carpetas")
        self.btn_kw_new.clicked.connect(self._kw_new_dialog)
        self.btn_kw_auto.clicked.connect(self._kw_auto)
        self.btn_kw_refresh.clicked.connect(self._rebuild)
        for b in (self.btn_kw_new, self.btn_kw_auto, self.btn_kw_refresh):
            set_help(b, "palabras_clave")
        kw_row = QHBoxLayout()
        kw_row.addWidget(self.btn_kw_new)
        kw_row.addWidget(self.btn_kw_auto, 1)
        kw_row.addWidget(self.btn_kw_refresh)

        self.tree = MediaTree()
        self.tree.resolve_paths = lambda rutas: self._kw_ids(rutas)
        self.tree.kw_dropped.connect(self._kw_drop)
        self.tree.kw_media_dropped.connect(self._kw_media_drop)
        self.tree.kw_header_dropped.connect(self._kw_header_drop)
        self.tree.itemExpanded.connect(lambda it: self._kw_track(it, False))
        self.tree.itemCollapsed.connect(lambda it: self._kw_track(it, True))
        self.tree.move_requested.connect(self._move_to)
        self.tree.delete_pressed.connect(lambda: self._remove(self.tree.selected_media_ids()))
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.setProperty("own_menu", True)
        set_help(self, "biblioteca")

        self.footer = QLabel()
        self.footer.setObjectName("dim")
        self.footer.setWordWrap(True)

        top = QHBoxLayout()                       # (sin título: la pestaña y la barra del panel ya dicen «Medios»)
        title.hide()
        top.addWidget(self.btn_files)
        top.addWidget(self.btn_folder)
        top.addStretch()
        self.btn_reset = QPushButton("⟲ Reiniciar todo")
        self.btn_reset.setToolTip("Quita TODOS los medios de la biblioteca (todas las categorías). Los archivos "
                                  "originales no se borran; antes te pregunta si borrar también sus miniaturas.")
        self.btn_reset.clicked.connect(self.reset_all)
        top.addWidget(self.btn_reset)
        top.addWidget(self.btn_analyze)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.addLayout(top)
        lay.addLayout(srow)
        lay.addLayout(kw_row)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.footer)

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(150)
        self._rebuild_timer.timeout.connect(self._rebuild)
        ctrl.media_changed.connect(self._rebuild_timer.start)
        ctrl.project_replaced.connect(self._clear_results)
        analyzer.status_changed.connect(lambda _t: self._update_footer())
        analyzer.busy_changed.connect(lambda busy: self.btn_analyze.setText("⏹" if busy else "◈"))
        self._on_mode(False)
        self._rebuild()

    # ------------------------------------------------------------- importar
    def import_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importar archivos", "", MEDIA_FILTER)
        if paths:
            self.ctrl.import_paths(paths)

    def import_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Importar carpeta completa")
        if folder:
            self.ctrl.import_folder(folder)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.ctrl.import_folder(path)
            elif path:
                self.ctrl.import_paths([path])

    # ------------------------------------------------------------ análisis
    def _analyze_clicked(self):
        if self.analyzer.job is not None:
            self.analyzer.cancel()
            return
        if not self.analyzer.models_ready():
            r = QMessageBox.question(
                self, "Analizar clips con IA",
                "La IA mirará varios fotogramas de cada clip para saber qué contiene "
                "(gameplay, cinemática, combate, exploración…) y poder buscarlos por contenido.\n\n"
                "La primera vez se descargan los modelos (~500 MB). Todo funciona en tu PC, "
                "gratis y sin enviar tus videos a ningún sitio.\n\n¿Continuar?")
            if r != QMessageBox.Yes:
                return
        self.analyzer.analyze()

    # ------------------------------------------------------------ mostrar
    def _icon_for(self, m) -> QIcon:
        thumb = self.ctrl.thumbs.get(m.id)
        if thumb:
            if thumb not in self._icons:
                pix = QPixmap(thumb)
                self._icons[thumb] = QIcon(pix.scaled(64, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return self._icons[thumb]
        style = self.style()
        if m.kind == KIND_AUDIO:
            return style.standardIcon(QStyle.SP_MediaVolume)
        return style.standardIcon(QStyle.SP_FileIcon)

    def _media_item(self, m, extra_info: str | None = None) -> QTreeWidgetItem:
        if m.id in self.ctrl.missing:
            dur, info = "—", "⚠️ no encontrado"
        elif m.id in self.ctrl.analyzing:
            dur, info = "…", "leyendo…"
        else:
            dur = "imagen" if m.kind == KIND_IMAGE else fmt_time(m.duration, frac=False)
            if m.ai_tags:
                info = "◈ " + ", ".join(m.ai_tags[:2])
            elif m.width:
                info = f"{m.width}x{m.height} · {m.fps:g} fps"
            else:
                info = "audio" if m.kind == KIND_AUDIO else ""
        if getattr(m, "scene_cut", False) and m.kind == "video":
            info = (info + " · " if info else "") + "✂ por escenas"
        it = QTreeWidgetItem([m.name, dur, extra_info if extra_info is not None else info, "⋮"])
        it.setTextAlignment(3, Qt.AlignCenter)
        it.setToolTip(3, "Opciones rápidas: eliminar, mover, separar audio, cortar por escenas")
        it.setData(0, ROLE_MEDIA, m.id)
        it.setIcon(0, self._icon_for(m))
        tags = ", ".join(m.tags) if m.tags else "—"
        tip = f"{m.path}\nCategoría: {m.category}\nEtiquetas: {tags}"
        if m.width:
            tip += f"\n{m.width}x{m.height} · {m.fps:g} fps"
        if m.ai_analyzed:
            tip += f"\n◈ La IA ve: {m.ai_type or '?'} — {', '.join(m.ai_tags) or '—'}"
        for col in range(3):
            it.setToolTip(col, tip)
        if m.id in self.ctrl.missing:
            it.setForeground(0, QColor("#e06c5f"))
        return it

    def _rebuild(self):
        media = list(self.ctrl.project.media.values())
        selected = set(self.tree.selected_media_ids())
        collapsed = {self.tree.topLevelItem(i).data(0, ROLE_CATEGORY)
                     for i in range(self.tree.topLevelItemCount())
                     if not self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)

        if self._results is not None:
            top = QTreeWidgetItem([f"◈ «{self._results_query}»  ({len(self._results)})"])
            top.setData(0, ROLE_CATEGORY, "__resultados__")
            top.setFont(0, bold)
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            best = self._results[0][1] if self._results else 1.0
            worst = self._results[-1][1] if self._results else 0.0
            for mid, score, moment in self._results:
                m = self.ctrl.project.media.get(mid)
                if m is None:
                    continue
                rel = (score - worst) / (best - worst) if best > worst else 1.0
                stars = "★" * (1 + round(rel * 2)) + "☆" * (2 - round(rel * 2))
                moment_txt = f" · en {fmt_time(moment, frac=False)}" if m.kind != KIND_IMAGE else ""
                it = self._media_item(m, f"{stars}{moment_txt}")
                it.setData(0, ROLE_MOMENT, moment)
                top.addChild(it)
            top.setExpanded(True)
            self._update_footer()
            return

        # «Internet/master chief» = carpeta «master chief» dentro de «Internet»
        groups: dict[str, dict[str, list]] = {}
        for m in media:
            main, _, subc = (m.category or "").partition("/")
            groups.setdefault(main, {}).setdefault(subc.strip(), []).append(m)
        order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
        for cat in sorted(groups, key=lambda c: (order.get(c, 99), c)):
            subs = groups[cat]
            n = sum(len(v) for v in subs.values())
            top = QTreeWidgetItem([f"{cat}  ({n})"])
            top.setData(0, ROLE_CATEGORY, cat)
            top.setFont(0, bold)
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for subc in sorted(subs, key=lambda s: (s != "", s.lower())):
                parent = top
                if subc:
                    parent = QTreeWidgetItem([f"📁 {subc}  ({len(subs[subc])})"])
                    parent.setData(0, ROLE_CATEGORY, f"{cat}/{subc}")
                    parent.setFlags(Qt.ItemIsEnabled)
                    top.addChild(parent)
                    parent.setExpanded(f"{cat}/{subc}" not in collapsed)
                for m in sorted(subs[subc], key=lambda m: m.name.lower()):
                    it = self._media_item(m)
                    parent.addChild(it)
                    if m.id in selected:
                        it.setSelected(True)
            top.setExpanded(cat not in collapsed)
        self._build_keywords(bold, KW_SECTION not in collapsed)
        self._update_footer()
        self._apply_filter()

    # ------------------------------------------------------ 🔑 palabras clave (Medios)
    def _build_keywords(self, bold: QFont, abierta: bool = True):
        """«🔑 Palabras clave»: una palabra por nodo (su carpeta propia + enlaces del PC) y, dentro, sus archivos.
        Los archivos que vienen de una carpeta enlazada llevan 🔗. Nada se copia ni se importa al pintar."""
        try:
            folders = KF.list_folders(_kw_root())
        except Exception:  # noqa: BLE001 - una carpeta rara no debe romper Medios
            folders = []
        media = self.ctrl.project.media
        by_path = {os.path.normcase(os.path.abspath(m.path)): m for m in media.values()}
        self._kw_sin_mini: list[str] = []
        self._kw_items_ruta: dict[str, QTreeWidgetItem] = {}
        self._kw_construyendo = True              # (los «expandir» de aquí no son clics del usuario)
        if not hasattr(self, "_kw_iconos"):
            self._kw_iconos: dict[str, QIcon] = {}          # ruta del archivo → su miniatura (no se relee al repintar)
            self._kw_mini_fallidas: set[str] = set()         # sin miniatura posible (video roto): no se reintenta
        sec = QTreeWidgetItem([f"🔑 Palabras clave  ({len(folders)})"])
        sec.setToolTip(0, "Tus carpetas de palabras clave: están en tu disco y valen para todos tus proyectos (por eso "
                          "no se borran al reiniciar el proyecto). Para borrar lo descargado: pestaña 🗂 Carpetas.")
        sec.setData(0, ROLE_CATEGORY, KW_SECTION)
        sec.setFont(0, bold)
        sec.setFlags(Qt.ItemIsEnabled)
        self.tree.addTopLevelItem(sec)
        for f in folders:
            term = f["label"]
            node = QTreeWidgetItem([f"{term}  ({f['count']})"])
            node.setData(0, ROLE_KW_KIND, "term")
            node.setData(0, ROLE_KW_TERM, term)
            node.setData(0, ROLE_PATH, f["own_path"] or "")
            own = f["own_path"] or "(sin subcarpeta propia: solo enlaces)"
            node.setToolTip(0, f"Carpeta de Reclaimer: {own}\n"
                               + (f"Enlazadas de tu PC: {len(f['links'])}" if f["links"] else "Sin carpetas enlazadas"))
            node.setFlags(Qt.ItemIsEnabled)
            sec.addChild(node)
            for link in f["links"]:
                ln = QTreeWidgetItem([f"🔗 {_corta_ruta(link)}"])
                ln.setData(0, ROLE_KW_KIND, "link")
                ln.setData(0, ROLE_KW_TERM, term)
                ln.setData(0, ROLE_PATH, link)
                ln.setToolTip(0, link)
                ln.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                node.addChild(ln)
            enlazados = set(f["linked_files"])
            visible = abierta and term not in self._kw_collapsed
            for path in f["files"]:
                it = self._kw_file_item(path, term, path in enlazados, by_path, cargar=visible)
                self._kw_items_ruta[path] = it
                node.addChild(it)
            node.setExpanded(term not in self._kw_collapsed)
        sec.setExpanded(abierta)
        self._kw_construyendo = False
        if self._kw_sin_mini:
            self._kw_miniaturas(list(self._kw_sin_mini))

    @staticmethod
    def _kw_clave(path: str) -> str:
        """La ruta de su miniatura (cambia si el archivo cambia: uno reemplazado no conserva la vieja)."""
        from .clips_panel import _miniatura_ruta
        return _miniatura_ruta(path)

    def _kw_icono(self, path: str):
        png = self._kw_clave(path)
        ic = self._kw_iconos.get(png)
        if ic is None:
            pm = QPixmap(png) if os.path.isfile(png) else QPixmap()
            if pm.isNull():
                return None
            ic = self._kw_iconos[png] = QIcon(pm)
        return ic

    def _kw_cargar_nodo(self, node: QTreeWidgetItem):
        """Al abrir una palabra (o la sección) plegada: sus miniaturas."""
        pend = []
        hijos = [node.child(i) for i in range(node.childCount())]
        for ch in list(hijos):
            hijos += [ch.child(i) for i in range(ch.childCount())]
        for ch in hijos:
            if ch.data(0, ROLE_KW_KIND) != "file":
                continue
            path = ch.data(0, ROLE_PATH) or ""
            ic = self._kw_icono(path)
            if ic is not None:
                ch.setIcon(0, ic)
            elif path and self._kw_clave(path) not in self._kw_mini_fallidas:
                pend.append(path)
        if pend:
            self._kw_miniaturas(pend)

    def _kw_miniaturas(self, rutas: list[str]):
        """Miniaturas de los archivos de palabras clave que aún no la tienen (en segundo plano, una vez)."""
        from .clips_panel import _hacer_miniatura, _miniatura_ruta
        from .jobs import BackgroundJob
        rutas = [r for r in rutas if self._kw_clave(r) not in self._kw_mini_fallidas][:300]
        viejo = getattr(self, "_kw_mini_job", None)
        if viejo is not None and getattr(self, "_kw_mini_rutas", None) == rutas:
            return                         # (ya se están haciendo estas mismas)
        if viejo is not None:
            viejo.cancel()
        if not rutas:
            return
        fallidas = self._kw_mini_fallidas

        def trabajo(_p, cancelado, emitir):
            for r in rutas:
                if cancelado():
                    return None
                salida = _miniatura_ruta(r)
                if os.path.isfile(salida) or _hacer_miniatura(r, salida):
                    emitir((r, salida))
                else:
                    fallidas.add(salida)
            return None

        def llego(par):
            pm = QPixmap(par[1])
            if pm.isNull():
                fallidas.add(par[1])
                return
            ic = self._kw_iconos[par[1]] = QIcon(pm)
            it = self._kw_items_ruta.get(par[0])
            if it is None:
                return
            try:
                it.setIcon(0, ic)
            except RuntimeError:          # (Medios se repintó mientras tanto)
                pass

        def fin(*_a):
            if self._kw_mini_job is job:
                self._kw_mini_job, self._kw_mini_rutas = None, None
        job = BackgroundJob(trabajo, self, with_partial=True)
        job.title = "🖼 Miniaturas de palabras clave"
        job.partial.connect(llego)
        job.done.connect(fin)
        job.failed.connect(fin)
        self._kw_mini_job, self._kw_mini_rutas = job, rutas
        job.start()

    def _kw_file_item(self, path: str, term: str, linked: bool, by_path: dict, cargar: bool = True) -> QTreeWidgetItem:
        m = by_path.get(os.path.normcase(os.path.abspath(path)))
        if m is not None:
            it = self._media_item(m)
        else:
            it = QTreeWidgetItem([os.path.basename(path), "—", "en tu carpeta", ""])
            icono = self._kw_icono(path) if cargar else None
            if icono is None:                     # (se hace en segundo plano y aparece sola; plegado: al abrirlo)
                it.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                if cargar and self._kw_clave(path) not in self._kw_mini_fallidas:
                    self._kw_sin_mini.append(path)
            else:
                it.setIcon(0, icono)
            for col in range(3):
                it.setToolTip(col, path + "\nArchivo de tu carpeta de palabras clave (en tu disco, para todos tus "
                                          "proyectos): aún no está en este proyecto. Arrástralo a la línea de tiempo "
                                          "o haz doble clic.")
        if linked:
            it.setText(0, "🔗 " + it.text(0))
            for col in range(3):
                it.setToolTip(col, (it.toolTip(col) or path) + f"\nEnlazado de tu PC (no se copia): {path}")
        it.setData(0, ROLE_KW_KIND, "file")
        it.setData(0, ROLE_KW_TERM, term)
        it.setData(0, ROLE_PATH, path)
        it.setData(0, ROLE_KW_LINKED, bool(linked))
        return it

    def _update_footer(self):
        media = self.ctrl.project.media
        n_an = len(self.ctrl.analyzing)
        text = f"{len(media)} archivos" + (f" · leyendo {n_an}…" if n_an else "")
        n_ai = sum(1 for m in media.values() if m.ai_analyzed)
        n_vis = sum(1 for m in media.values() if m.kind != KIND_AUDIO)
        if n_vis:
            text += f" · ◈ {n_ai}/{n_vis} analizados"
        if self.analyzer.status and self.analyzer.job is not None:
            text += f"\n{self.analyzer.status}"
        self.footer.setText(text)

    def _kw_track(self, it: QTreeWidgetItem, plegado: bool):
        if not plegado and not getattr(self, "_kw_construyendo", False)                 and (it.data(0, ROLE_KW_KIND) == "term" or it.data(0, ROLE_CATEGORY) == KW_SECTION):
            self._kw_cargar_nodo(it)
        if it.data(0, ROLE_KW_KIND) == "term":
            term = it.data(0, ROLE_KW_TERM)
            (self._kw_collapsed.add if plegado else self._kw_collapsed.discard)(term)

    def _filtrar_palabras(self, sec: QTreeWidgetItem, q: str):
        """La búsqueda también mira las palabras clave: se ven las que coinciden y sus archivos que coinciden."""
        qn = KF.norm(q)
        for j in range(sec.childCount()):
            node = sec.child(j)
            term_ok = not qn or qn in KF.norm(node.data(0, ROLE_KW_TERM) or "")
            visibles = 0
            for k in range(node.childCount()):
                ch = node.child(k)
                ok = term_ok or not qn or qn in KF.norm(ch.text(0))
                ch.setHidden(not ok)
                visibles += ok
            node.setHidden(not (term_ok or visibles))
            if qn and visibles:
                node.setExpanded(True)

    def _apply_filter(self):
        if self._results is not None or self.btn_ai_search.isChecked():
            return
        q = self.search.text()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, ROLE_CATEGORY) == KW_SECTION:
                self._filtrar_palabras(top, q)
                top.setHidden(False)
                continue
            visible = 0
            for j in range(top.childCount()):
                it = top.child(j)
                m = self.ctrl.project.media.get(it.data(0, ROLE_MEDIA))
                ok = m is not None and matches_query(q, m.name, m.category, " ".join(m.tags),
                                                     m.ai_type, " ".join(m.ai_tags))
                it.setHidden(not ok)
                visible += ok
            top.setHidden(visible == 0)
            if q and visible:
                top.setExpanded(True)

    # ------------------------------------------------------------- búsqueda
    def _on_mode(self, ai: bool):
        self.search.setPlaceholderText("◈ Describe lo que buscas y pulsa Enter…" if ai else
                                       "🔎 Buscar: nombre, categoría, carpeta o contenido…")
        if not ai:
            self._clear_results()
        self._apply_filter()

    def _on_search_text(self, text: str):
        if not text and self._results is not None:
            self._clear_results()
        self._apply_filter()

    def _clear_results(self):
        if self._results is not None:
            self._results = None
            self._rebuild()

    def _on_search_enter(self):
        if self.btn_ai_search.isChecked():
            self.semantic_search(self.search.text().strip())

    def semantic_search(self, query: str):
        if not query:
            self.ctrl.message.emit("Escribe qué buscar, p. ej. «coche rojo de noche».")
            return
        if self._search_job is not None:
            self.ctrl.message.emit("Espera: ya estoy buscando.")
            return
        clips = {mid: v for mid, v in self.ctrl.clip_vecs.items() if mid in self.ctrl.project.media}
        if not clips:
            QMessageBox.information(self, "Buscar por contenido",
                                    "Primero la IA tiene que analizar tus clips: pulsa el botón ◈ "
                                    "de arriba (junto a «＋ Carpeta»).")
            return

        p = self.ctrl.project
        metas = {mid: clip_analysis.metadata_text(p.media[mid].name, p.media[mid].category, p.media[mid].ai_type,
                                                  p.media[mid].ai_tags, p.media[mid].tags) for mid in clips}

        def work(progress, _cancelled):
            progress(0.0, "◈ Cargando la IA…")
            vec = embeddings.get("clip_text").encode([query])[0]
            meta = clip_analysis.metadata_scores(query, metas)
            return clip_analysis.search(vec, clips, top=40, meta=meta)

        self._results_query = query
        self.footer.setText("◈ Buscando…")
        self._search_job = BackgroundJob(work, self)
        self._search_job.done.connect(self._on_results)
        self._search_job.failed.connect(lambda msg: self.footer.setText(f"✗ {msg}"))
        self._search_job.finished.connect(self._on_search_finished)
        self._search_job.start()

    def _on_results(self, results):
        # Solo los que se parecen de verdad (relativo al mejor resultado)
        if results:
            best = results[0][1]
            results = [r for r in results if r[1] >= best - 0.06][:25]
        else:
            self.ctrl.message.emit("◈ No encontré nada parecido: prueba con otras palabras (o analiza más clips con ◈).")
        self._results = results
        self._rebuild()

    def _on_search_finished(self):
        job, self._search_job = self._search_job, None
        if job:
            job.deleteLater()

    # ----------------------------------------------------------- acciones
    def _on_double_click(self, item, _col):
        mid = item.data(0, ROLE_MEDIA)
        if not mid and item.data(0, ROLE_KW_KIND) == "file":      # archivo de una palabra: clip de palabra clave en el cabezal
            ids = self._kw_ids([item.data(0, ROLE_PATH)])
            if ids:
                self.ctrl.add_media_at_times(ids, [self._playhead()], "Añadir clip de palabra clave", modo="entero")
            return
        if not mid:
            return
        moment = item.data(0, ROLE_MOMENT)
        if moment is not None:
            self.add_moment_requested.emit(mid, float(moment))
        else:
            self.add_requested.emit([mid])

    def _context_menu(self, pos):
        it_kw = self.tree.itemAt(pos)
        if it_kw is not None and it_kw.data(0, ROLE_KW_KIND):
            self._kw_menu(it_kw, pos)
            return
        ids = self.tree.selected_media_ids()
        if not ids:
            menu = QMenu(self)
            if self.ctrl.project.media:
                menu.addAction("⟲ Reiniciar todo (quitar todos los medios)…", self.reset_all)
            add_help_action(menu, "biblioteca", self.window())
            help_ui.exec_menu(menu, self.tree.viewport().mapToGlobal(pos))
            return
        menu = QMenu(self)
        item = self.tree.itemAt(pos)
        moment = item.data(0, ROLE_MOMENT) if item else None
        if moment is not None and len(ids) == 1:
            menu.addAction(f"Añadir desde el mejor momento ({fmt_time(moment, frac=False)})",
                           lambda: self.add_moment_requested.emit(ids[0], float(moment)))
        menu.addAction("Añadir a la timeline (en el cabezal)", lambda: self.add_requested.emit(ids))
        self._keyword_actions(menu, lambda: ids)
        m0 = self.ctrl.project.media.get(ids[0])
        if len(ids) == 1 and m0 is not None and m0.kind != "audio":
            menu.addAction("🎯 Usar como ejemplo de lo que busco (aprende con ✓/✗)…",
                           lambda: self.example_requested.emit(ids[0], None if moment is None else float(moment)))
        menu.addSeparator()
        menu.addAction("Cambiar categoría…", lambda: self._change_category(ids))
        menu.addAction("Editar etiquetas…", lambda: self._edit_tags(ids))
        menu.addAction("◈ Corregir lo que vio la IA…", lambda: self._edit_ai_tags(ids))
        menu.addAction("◈ Volver a analizar", lambda: self._reanalyze(ids))
        if len(ids) == 1:
            menu.addAction("Mostrar en el Explorador", lambda: self._reveal(ids[0]))
        vids = [i for i in ids if (m := self.ctrl.project.media.get(i)) is not None and m.kind == "video"
                and m.has_audio and i not in self.ctrl.missing]
        if vids:
            menu.addAction("🎵 Separar audio (micrófono y juego)" + (f" · {len(vids)} videos" if len(vids) > 1 else ""),
                           lambda: self._separate_audio(vids))
        self._scene_action(menu, ids)
        snd = [i for i in ids if (m := self.ctrl.project.media.get(i)) is not None and i not in self.ctrl.missing
               and (m.kind == "audio" or (m.kind == "video" and m.has_audio))]
        if snd:
            menu.addAction("🗣 Buscar lo que se dice…", lambda: self.keywords_requested.emit(snd))
        if snd:
            a = menu.addAction("🔖 Leer marcas de OBS", lambda: self.obs_marks_requested.emit(snd))
            a.setToolTip("Lee los capítulos que pusiste con una tecla mientras grababas en OBS y los pone como "
                         "marcadores rojos en la línea de tiempo. Luego «🔖 Fallos marcados» te ayuda a quitarlos.")
        mv = menu.addMenu("📂 Mover a…")
        cats = sorted({m.category for m in self.ctrl.project.media.values()} | set(CATEGORY_ORDER),
                      key=lambda c: c.lower())
        for c in cats:
            label = c.replace("/", " ▸ ")
            a = mv.addAction(label, lambda cc=c: self._move_to(ids, cc))
            a.setEnabled(any(self.ctrl.project.media[i].category != c for i in ids if i in self.ctrl.project.media))
        mv.addSeparator()
        mv.addAction("➕ Carpeta nueva…", lambda: self._move_new_folder(ids))
        menu.addSeparator()
        menu.addAction("Quitar de la biblioteca\tSupr", lambda: self._remove(ids))
        menu.addAction("🗑 Eliminar el archivo (a la Papelera)…", lambda: self._trash(ids))
        add_help_action(menu, "biblioteca", self.window())
        help_ui.exec_menu(menu, self.tree.viewport().mapToGlobal(pos))

    def _change_category(self, ids):
        cats = sorted({m.category for m in self.ctrl.project.media.values()} | set(CATEGORY_ORDER))
        current = self.ctrl.project.media[ids[0]].category
        cat, ok = QInputDialog.getItem(self, "Cambiar categoría",
                                       "Categoría (puedes escribir una nueva):", cats,
                                       cats.index(current) if current in cats else 0, True)
        if ok and cat.strip():
            self.ctrl.set_media_props(ids, category=cat.strip())

    def _edit_tags(self, ids):
        current = ", ".join(self.ctrl.project.media[ids[0]].tags)
        text, ok = QInputDialog.getText(self, "Etiquetas",
                                        "Etiquetas separadas por comas (ej.: combate, Marcus, jefe):",
                                        text=current)
        if ok:
            tags = [t.strip() for t in text.split(",") if t.strip()]
            self.ctrl.set_media_props(ids, tags=tags)

    def _edit_ai_tags(self, ids):
        m = self.ctrl.project.media[ids[0]]
        text, ok = QInputDialog.getText(self, "Lo que vio la IA",
                                        "Corrige lo que se ve en el clip (separado por comas):",
                                        text=", ".join(m.ai_tags))
        if ok:
            self.ctrl.set_media_props(ids, ai_tags=[t.strip() for t in text.split(",") if t.strip()])

    def _reanalyze(self, ids):
        from ..ai.clip_analysis import _cache_path
        for mid in ids:
            m = self.ctrl.project.media.get(mid)
            if m and m.kind != KIND_AUDIO:
                try:
                    os.remove(_cache_path(m.path))
                except OSError:
                    pass
        self.ctrl.set_media_props(ids, ai_analyzed=False)
        self.analyzer.analyze([i for i in ids if self.ctrl.project.media[i].kind != KIND_AUDIO])

    def _reveal(self, mid):
        m = self.ctrl.project.media.get(mid)
        if m and os.path.exists(m.path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(m.path)])
        else:
            self.ctrl.message.emit("No encuentro el archivo en el disco (¿se movió o se borró?): no se puede mostrar.")

    # ------------------------------------------------------------ ⋮ opciones rápidas
    def _on_click(self, item, col):
        mid = item.data(0, ROLE_MEDIA) if item is not None else None
        if col == 3 and mid:
            sel = self.tree.selected_media_ids()
            ids = sel if mid in sel else [mid]
            r = self.tree.visualItemRect(item)
            from PySide6.QtCore import QPoint
            self._quick_menu(ids, self.tree.viewport().mapToGlobal(QPoint(r.right() - 4, r.bottom())))

    def _quick_menu(self, ids, global_pos):
        """⋮ Lo más usado, a un clic: eliminar de Medios, mover de carpeta, separar audio y cortar por escenas."""
        p = self.ctrl.project
        ids = [i for i in ids if i in p.media]
        if not ids:
            return
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.addAction("🗑 Eliminar de Medios (el archivo no se borra)", lambda: self._remove(ids))
        self._move_menu(menu, ids)
        vids = [i for i in ids if p.media[i].kind == "video" and p.media[i].has_audio and i not in self.ctrl.missing]
        if vids:
            a = menu.addAction("🎵 Separar audio (micrófono y juego)", lambda: self._separate_audio(vids))
            a.setToolTip("Grabación de OBS con varias pistas: tu micrófono va a «🎙 Audio de micrófono» y el juego a "
                         "«🎮 Audio del juego». Si solo tiene una pista: su audio, aparte. (No se hace solo al "
                         "importar.)")
        self._scene_action(menu, ids)
        help_ui.exec_menu(menu, global_pos)

    def _move_menu(self, menu, ids):
        mv = menu.addMenu("📂 Mover a…")
        cats = sorted({m.category for m in self.ctrl.project.media.values()} | set(CATEGORY_ORDER),
                      key=lambda c: c.lower())
        for c in cats:
            a = mv.addAction(c.replace("/", " ▸ "), lambda cc=c: self._move_to(ids, cc))
            a.setEnabled(any(self.ctrl.project.media[i].category != c for i in ids if i in self.ctrl.project.media))
        mv.addSeparator()
        mv.addAction("➕ Carpeta nueva…", lambda: self._move_new_folder(ids))

    def _scene_action(self, menu, ids):
        """✂ Al ponerlo en la línea de tiempo, se corta solo en cada cambio de escena (si no hay, se queda entero)."""
        vids = [i for i in ids if self.ctrl.project.media[i].kind == "video"]
        if not vids:
            return
        on = all(getattr(self.ctrl.project.media[i], "scene_cut", False) for i in vids)
        a = menu.addAction("✂ Cortar en cada cambio de escena al ponerlo en la línea de tiempo")
        a.setCheckable(True)
        a.setChecked(on)
        a.setToolTip("Lo arrastras a la línea de tiempo y llega ya cortado en cada cambio de escena (solo si la "
                     "imagen cambia de golpe de una escena a otra; si no hay, se queda entero). En Medios no cambia "
                     "nada. Ctrl+Z quita los cortes.")
        a.toggled.connect(lambda v: self.ctrl.set_media_props(vids, scene_cut=bool(v)))

    def _separate_audio(self, ids):
        """🎵 Separar audio: OBS con varias pistas → micrófono y juego; con una sola pista → su audio aparte."""
        from ..core import audio_extract, obs_tracks
        from ..core import media as media_tools
        from .task_window import manager
        items = [(i, self.ctrl.project.media[i].path, self.ctrl.project.media[i].duration,
                  self.ctrl.project.media[i].name) for i in ids]

        def work(progress, cancelled):
            out = []
            for k, (mid, path, dur, name) in enumerate(items):
                progress(k / len(items), f"🎵 Separando el audio de «{name[:30]}»…")
                if int(media_tools.probe(path).get("audio_streams") or 0) > 1:
                    out.append(("obs", mid, obs_tracks.split(path)))
                else:
                    out.append(("uno", mid, audio_extract.extract(path, dur, None, cancelled)))
            return out

        def done(out):
            singles = [x for kind, _m, x in out if kind == "uno"]
            for kind, mid, res in out:
                if kind == "obs":
                    self.ctrl.apply_audio_tracks(mid, res)
            if singles:
                new = self.ctrl.import_paths(singles)
                if new:
                    self.ctrl.set_media_props(new, category="Audio extraído")
            self.ctrl.message.emit("🎵 Audio separado: en Medios ▸ «🎙 Audio de micrófono» y «🎮 Audio del juego»"
                                   if not singles else
                                   f"🎵 Audio separado ({len(out)}): en Medios ▸ " +
                                   ("«🎙 Audio de micrófono», «🎮 Audio del juego» y «Audio extraído»"
                                    if len(singles) < len(out) else "Audio extraído"))
        manager().start("🎵 Separar audio", work, done, lambda msg: self.ctrl.message.emit("✗ " + msg))

    def _to_audio(self, ids):
        """Saca el sonido de los videos a «F:/Reclaimer/Audio extraído» y lo añade a Medios (carpeta «Audio extraído»)."""
        from ..core import audio_extract
        from .task_window import manager
        items = [(m.path, m.duration, m.name) for m in (self.ctrl.project.media[i] for i in ids)]

        def work(progress, cancelled):
            outs = []
            for k, (path, dur, name) in enumerate(items):
                def prog(f, k=k, name=name):
                    progress((k + f) / len(items), f"🎵 Sacando el audio de «{name[:30]}» · {int(f * 100)} %")
                prog(0.0)
                outs.append(audio_extract.extract(path, dur, prog, cancelled))
            return outs

        def done(outs):
            new = self.ctrl.import_paths(outs)
            if new:
                self.ctrl.set_media_props(new, category="Audio extraído")
            win = self.window()
            if hasattr(win, "statusBar"):
                win.statusBar().showMessage(f"🎵 Listo: {len(outs)} audio(s) en Medios ▸ Audio extraído "
                                            f"(guardado en {audio_extract.out_dir()}).", 10000)

        def failed(msg):
            win = self.window()
            if hasattr(win, "statusBar"):
                win.statusBar().showMessage("✗ " + msg, 10000)
        manager().start("🎵 Convertir en solo audio", work, done, failed)

    def _move_to(self, ids, category: str):
        ids = [i for i in ids if i in self.ctrl.project.media]
        if ids and category:
            self.ctrl.set_media_props(ids, category=category)
            self.ctrl.message.emit(f"📂 {len(ids)} archivo(s) movidos a «{category.replace('/', ' ▸ ')}».")

    def _move_new_folder(self, ids):
        cur = self.ctrl.project.media[ids[0]].category if ids else ""
        main = cur.partition("/")[0] or "Sin clasificar"
        name, ok = QInputDialog.getText(self, "Carpeta nueva", f"Nombre de la carpeta (dentro de «{main}»).\n"
                                        "Para una categoría nueva de primer nivel, empieza con «/».")
        name = (name or "").strip()
        if ok and name:
            self._move_to(ids, name[1:].strip() if name.startswith("/") else f"{main}/{name}")

    def _trash(self, ids):
        """Manda los archivos a la Papelera de Windows (se pueden recuperar) y los quita de Medios."""
        p = self.ctrl.project
        ids = [i for i in ids if i in p.media]
        if not ids:
            return
        used = [p.media[i].name for i in ids if p.is_media_used(i)]
        if used:
            QMessageBox.information(self, "Eliminar", f"«{used[0]}» se está usando en la línea de tiempo. "
                                    "Quita antes sus clips.")
            return
        names = "\n".join("• " + p.media[i].name for i in ids[:8]) + ("\n…" if len(ids) > 8 else "")
        if QMessageBox.question(self, "Eliminar archivos", f"¿Mandar a la Papelera de Windows {len(ids)} archivo(s)?"
                                f"\n\n{names}\n\nSe pueden recuperar desde la Papelera.") != QMessageBox.Yes:
            return
        paths = {i: p.media[i].path for i in ids}
        if not self.ctrl.remove_media(ids):
            return
        failed = [os.path.basename(pth) for pth in paths.values()
                  if os.path.exists(pth) and not _to_trash(pth)]
        self.ctrl.message.emit(f"🗑 {len(ids) - len(failed)} archivo(s) a la Papelera."
                               + (f" No se pudieron mover: {', '.join(failed[:3])}" if failed else ""))

    def _remove(self, ids):
        r = QMessageBox.question(self, "Quitar de la biblioteca",
                                 f"¿Quitar {len(ids)} archivo(s) de la biblioteca?\n"
                                 "Los archivos originales NO se borran del disco.")
        if r == QMessageBox.Yes:
            self.ctrl.remove_media(ids)

    # ------------------------------------------------- ⟲ Reiniciar todo
    def reset_plan(self) -> dict:
        """Qué haría «⟲ Reiniciar todo»: TODOS los medios de la biblioteca (todas las categorías), los que están en
        la línea de tiempo y los que no. (Los generados y los que van dentro de un compuesto no se tocan.)"""
        p = self.ctrl.project
        comp = set(p.compounds or {})
        inner = {c.get("media_id") for v in (p.compounds or {}).values() for c in (v or {}).get("clips", [])}
        cands = [m.id for m in p.media.values() if not getattr(m, "gen", None) and m.id not in comp
                 and m.id not in inner]
        used = [i for i in cands if p.is_media_used(i)]
        used_set = set(used)
        free = [i for i in cands if i not in used_set]
        return {"all": cands, "used": used, "free": free,
                "clips": sum(1 for c in p.clips.values() if c.media_id in used_set)}

    def reset_cache(self, removed: list[str]) -> dict:
        """Lo que Reclaimer guarda en su caché de esos medios (miniaturas, copias, ondas, análisis) y que NO
        comparte ningún medio que se queda (mismo archivo importado dos veces). {grupo: [archivos]}."""
        from ..core import media_cache as MC
        p = self.ctrl.project
        gone = set(removed)
        keep_paths = {os.path.normcase(os.path.abspath(m.path)) for m in p.media.values()
                      if m.id not in gone and m.path}
        paths = {m.path for i in gone if (m := p.media.get(i)) is not None and m.path
                 and os.path.normcase(os.path.abspath(m.path)) not in keep_paths}
        return MC.find(paths)

    def reset_all(self):
        """⟲ Reiniciar todo: quita de la biblioteca TODOS los medios (todas las categorías). Si alguno está en la
        línea de tiempo, pregunta: quitar también sus clips, o solo los que no se usan. Casilla (desmarcada): borrar
        también sus miniaturas, copias ligeras, formas de onda y análisis de la caché. Un paso de deshacer."""
        from PySide6.QtWidgets import QCheckBox
        from ..core import media_cache as MC
        plan = self.reset_plan()
        n, k = len(plan["all"]), len(plan["used"])
        if not n:
            QMessageBox.information(self, "Reiniciar todo", "No hay nada que quitar de la biblioteca.")
            return
        txt = (f"Se quitarán de la biblioteca {n} medio(s) de TODAS las categorías.\n"
               "Tus archivos originales NO se borran del disco: puedes volver a importarlos.")
        if k:
            txt += (f"\n\n⚠ {k} de ellos se están usando en la línea de tiempo ({plan['clips']} clip(s)). "
                    "¿Qué hago con esos?")
        txt += "\n\nCtrl+Z lo deshace (biblioteca y clips); lo que se borre de la caché NO vuelve."
        box = QMessageBox(QMessageBox.Warning, "⟲ Reiniciar todo", txt, QMessageBox.NoButton, self)
        if k:
            b_all = box.addButton("Quitar también sus clips de la línea de tiempo", QMessageBox.DestructiveRole)
            b_free = box.addButton("Quitar solo los que no se usan", QMessageBox.AcceptRole)
        else:
            b_all = box.addButton("Quitar todos", QMessageBox.DestructiveRole)
            b_free = None
        b_cancel = box.addButton("Cancelar", QMessageBox.RejectRole)
        box.setDefaultButton(b_cancel)
        box.setEscapeButton(b_cancel)
        chk = QCheckBox("Borrar también las miniaturas y datos guardados de estos archivos (cachés de miniaturas, "
                        "copias ligeras, ondas y análisis). Solo lo que creó Reclaimer; desmarcada = se quedan.")
        chk.setChecked(False)
        box.setCheckBox(chk)
        self._reset_box = box                     # (las pruebas pulsan sus botones)
        box.exec()
        self._reset_box = None
        clicked = box.clickedButton()
        if clicked is None or clicked is b_cancel:
            return
        if clicked is b_free:
            removed, with_clips = plan["free"], False
        else:
            removed, with_clips = plan["all"], k > 0
        if not removed:
            QMessageBox.information(self, "Reiniciar todo", "Todos los medios se están usando en la línea de "
                                    "tiempo: no se quitó nada.")
            return
        files = []
        if chk.isChecked():
            cache = self.reset_cache(removed)
            files = [f for fs in cache.values() for f in fs]
        n_removed = self.ctrl.remove_all_media(removed, with_clips)
        ok, bad = MC.delete(files) if files else (0, 0)
        for f in files:
            self._icons.pop(f, None)
        self._clear_results()
        msg = f"⟲ Biblioteca reiniciada: {n_removed} medio(s) quitados (los originales siguen en el disco)."
        if with_clips:
            msg += " Se quitaron también sus clips de la línea de tiempo."
        elif k:
            msg += f" {k} se quedan porque están en la línea de tiempo."
        if files:
            msg += f" {ok} archivo(s) de caché borrados."
            if bad:
                msg += f" {bad} no se pudieron borrar (en uso)."
        self.ctrl.message.emit(msg)

    # ------------------------------------------------- 🔑 palabras clave: acciones y menús
    def _kw_folder(self, term: str) -> dict | None:
        try:
            return KF.match(term, KF.list_folders(_kw_root()))
        except Exception:  # noqa: BLE001
            return None

    def _kw_refrescar(self, mensaje: str | None = None):
        if mensaje:
            self.ctrl.message.emit(mensaje)
        self._rebuild()

    def _kw_new_dialog(self):
        name, ok = QInputDialog.getText(self, "Nueva palabra clave",
                                        "Palabra (puedes poner alias separados por coma, p. ej. «Fortnite, fortnait»):")
        if ok and name.strip():
            self._kw_create(name.strip())

    def _kw_create(self, term: str) -> bool:
        try:
            KF.create_folder(_kw_root(), term)
        except OSError as exc:
            QMessageBox.warning(self, "Palabra clave", f"No pude crear la carpeta: {exc}")
            return False
        self._kw_refrescar(f"🔑 Palabra clave «{term}» lista. Suelta ahí tus videos e imágenes "
                           "o añade una carpeta de tu PC.")
        return True

    def _kw_auto(self):
        """✨ Crea una carpeta por cada palabra que dices en la narración y aún no tiene (pregunta cuáles)."""
        root = _kw_root()
        try:
            folders = KF.list_folders(root)
            menciones = find_mentions(self.ctrl.project, extra_terms=KF.terms(folders), glossary=KG.load())
        except Exception as exc:  # noqa: BLE001
            self.ctrl.message.emit(f"✗ No pude leer la narración: {exc}")
            return
        falta = []
        for m in menciones:
            if KG.is_no(m["term"]):
                continue                     # «no es palabra clave» (en el glosario): no se ofrece
            car = KF.match(m["term"], folders)
            if car is None or not car.get("own_path"):
                # lo que internet dice que no es juego ni compañía: se ofrece, pero sin marcar
                marcada = bool(m.get("known")) or m.get("web") not in ("ninguno", "persona")
                falta.append((m["term"], int(m["count"]), marcada))
        if not falta:
            self.ctrl.message.emit("✓ Todo lo que dices en la narración ya tiene su carpeta.")
            return
        elegidas = _pick_terms(self, falta)
        if not elegidas:
            return
        creadas = KF.create_from_mentions(root, elegidas)
        self._kw_refrescar(f"🔑 Carpetas creadas: {len(creadas)} de {len(elegidas)} palabras "
                           "(las que ya tenían carpeta no se tocan).")

    def _kw_link_dialog(self, term: str):
        carpeta = QFileDialog.getExistingDirectory(self, f"Carpeta de tu PC para «{term}»")
        if carpeta:
            self._kw_link(term, carpeta)

    def _kw_link(self, term: str, carpeta: str) -> bool:
        try:
            KF.link_folder(_kw_root(), term, carpeta)
        except ValueError as exc:
            QMessageBox.information(self, "No se puede enlazar", str(exc))
            return False
        self._kw_refrescar(f"🔗 «{os.path.basename(carpeta) or carpeta}» enlazada a «{term}». No se copió nada.")
        return True

    def _kw_modo_archivo(self) -> str | None:
        """Un archivo suelto del Explorador: «enlazar» (no copia) o «copiar». Pregunta una vez y recuerda la elección
        (QSettings «palabras_clave/soltar_archivo»). None si cancela."""
        return modo_archivo_suelto(self)

    def _kw_link_files(self, term: str, rutas: list[str]) -> bool:
        """Enlaza archivos del PC a la palabra (no los copia). Devuelve si enlazó alguno."""
        root = _kw_root()
        enlazados, errores = 0, []
        for r in rutas:
            try:
                KF.link_file(root, term, r)
                enlazados += 1
            except ValueError as exc:
                errores.append(str(exc))
        texto = f"«{term}»: " + (f"🔗 {enlazados} archivo(s) enlazado(s) (no se copian)" if enlazados
                                  else "nada que enlazar.")
        if errores:
            texto += f" · ✗ {errores[0]}"
        self._kw_refrescar(texto)
        return enlazados > 0

    def _kw_media_drop(self, ids: list, term: str):
        """Arrastrar un medio de Medios a una palabra clave: se enlaza su archivo (nunca se copia)."""
        rutas = [self.ctrl.project.media[i].path for i in ids if i in self.ctrl.project.media]
        if rutas:
            self._kw_link_files(term, rutas)

    def _kw_header_drop(self, payload: list, es_medio: bool):
        """Soltar sobre la cabecera «🔑 Palabras clave»: pide el nombre de la palabra y luego enlaza o copia."""
        nombre, ok = QInputDialog.getText(self, "Palabra clave", "¿Qué palabra clave es? (puedes poner alias "
                                          "separados por coma, p. ej. «Fortnite, fortnait»):")
        term = nombre.strip() if ok else ""
        if not term:
            return
        if es_medio:
            rutas = [self.ctrl.project.media[i].path for i in payload if i in self.ctrl.project.media]
            if rutas:
                self._kw_link_files(term, rutas)
        else:
            self._kw_drop(payload, term)

    def _kw_drop(self, rutas: list, term: str):
        """Soltar sobre una palabra: las CARPETAS se enlazan (no se copian); los ARCHIVOS se enlazan o se copian
        (pregunta una vez, o lo que se recordó)."""
        root = _kw_root()
        enlazadas, copiados, errores = 0, [], []
        for c in (r for r in rutas if os.path.isdir(r)):
            try:
                KF.link_folder(root, term, c)
                enlazadas += 1
            except ValueError as exc:
                errores.append(str(exc))
        archivos = [r for r in rutas if os.path.isfile(r)]
        enlazados_f = 0
        if archivos:
            modo = self._kw_modo_archivo()
            if modo == "enlazar":
                for a in archivos:
                    try:
                        KF.link_file(root, term, a)
                        enlazados_f += 1
                    except ValueError as exc:
                        errores.append(str(exc))
            elif modo == "copiar":
                try:
                    propia = KF.create_folder(root, term)
                    copiados = KF.add_files(propia, archivos)
                except OSError as exc:
                    errores.append(str(exc))
        partes = []
        if enlazadas:
            partes.append(f"🔗 {enlazadas} carpeta(s) enlazada(s) (no se copian)")
        if enlazados_f:
            partes.append(f"🔗 {enlazados_f} archivo(s) enlazado(s) (no se copian)")
        if copiados:
            partes.append(f"{len(copiados)} archivo(s) copiado(s)")
        texto = f"«{term}»: " + (" y ".join(partes) if partes else "nada que añadir.")
        if errores:
            texto += f" · ✗ {errores[0]}"
        self._kw_refrescar(texto)

    def _kw_ids(self, rutas: list) -> list[str]:
        """Importa al vuelo (si hace falta) y devuelve los ids de Medios."""
        rutas = [r for r in rutas if r]
        if not rutas:
            return []
        try:
            ids = self.ctrl.import_now(list(rutas))
        except Exception:  # noqa: BLE001
            return []
        return [i for i in ids if i and i in self.ctrl.project.media]

    def _kw_pick_paths(self, term: str) -> list[str]:
        """Los archivos SELECCIONADOS de esa palabra, o todos si no hay selección."""
        sel = [it.data(0, ROLE_PATH) for it in self.tree.selectedItems()
               if it.data(0, ROLE_KW_KIND) == "file" and it.data(0, ROLE_KW_TERM) == term]
        if sel:
            return sel
        car = self._kw_folder(term)
        return list(car["files"]) if car else []

    def _kw_hits(self, term: str) -> list[dict]:
        """Los momentos en que la narración dice la palabra (los mismos que en 🎬 Clips)."""
        try:
            ms = find_mentions(self.ctrl.project, extra_terms=KF.terms(KF.list_folders(_kw_root())),
                               glossary=KG.load())
        except Exception:  # noqa: BLE001
            return []
        m = next((x for x in ms if KF.norm(x["term"]) == KF.norm(term)), None)
        return list(m["hits"]) if m else []

    def _playhead(self) -> float:
        tl = getattr(self.window(), "timeline", None)
        return float(getattr(tl, "playhead", 0.0) or 0.0)

    def _kw_place(self, term: str, paths: list[str], cabezal: bool = False) -> bool:
        """📍 Poner donde lo dices (o en el cabezal): los archivos, repartidos por momentos, en un solo Ctrl+Z."""
        paths = [p for p in paths if p]
        if not paths:
            self.ctrl.message.emit(f"No hay archivos en «{term}» donde ponerlos.")
            return False
        if cabezal:
            hits = [{"tl": self._playhead(), "cabezal": True}]
        else:
            hits = self._kw_hits(term)
            if not any(h.get("tl") is not None for h in hits):
                self.ctrl.message.emit(f"«{term}» no sale con hora en tu narración: usa ⏵ Poner en el cabezal.")
                return False
        ids = self._kw_ids(paths)
        if not ids:
            self.ctrl.message.emit("No pude añadir esos archivos a Medios.")
            return False
        puestos, aviso = KP.repartir(self.ctrl, ids, hits)
        self.ctrl.message.emit(aviso or "No pude ponerlo: no hay sitio libre o el archivo aún se está analizando.")
        return bool(puestos)

    def _kw_window(self, term: str = ""):
        """🗂 La ventana amplia de palabras clave (el sitio principal de las carpetas), con esa palabra elegida."""
        panel = getattr(self.window(), "clips", None)
        if panel is None:
            return
        w = panel.abrir_ventana()
        if term:
            w.elegir_palabra(term)

    def _kw_add_file(self, path: str):
        """▶ Añadir a la timeline (en el cabezal): como clip de palabra clave (misma pista, en silencio)."""
        ids = self._kw_ids([path])
        if ids:
            self.ctrl.add_media_at_times(ids, [self._playhead()], "Añadir clip de palabra clave", modo="entero")

    def _keyword_actions(self, menu: QMenu, get_ids):
        """🔑 «Añadir en la palabra clave seleccionada» y, si esa palabra sale más veces en la línea de tiempo,
        «Añadir en todas las "<palabra>" (N)». get_ids() da los medios (se llama al elegir la opción)."""
        try:
            tgt = self.keyword_target() if callable(self.keyword_target) else None
        except Exception:  # noqa: BLE001  (sin línea de tiempo: la opción sale apagada)
            tgt = None
        if not tgt:
            a = menu.addAction("🔑 Añadir en la palabra clave seleccionada (selecciona una palabra clave en la "
                               "línea de tiempo)")
            a.setEnabled(False)
            return
        word, t, times = tgt["word"], float(tgt["t"]), list(tgt["times"])

        def go(ts, text):
            ids = get_ids()
            if ids:
                self.add_at_times_requested.emit(list(ids), list(ts), text)

        menu.addAction(f"🔑 Añadir en la palabra clave seleccionada («{word}», {fmt_time(t, frac=False)})",
                       lambda: go([t], f"Añadir en «{word}»"))
        if len(times) > 1:
            menu.addAction(f"🔑 Añadir en todas las «{word}» ({len(times)})",
                           lambda: go(times, f"Añadir en todas las «{word}» ({len(times)})"))

    def _kw_open(self, path: str):
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _kw_abrir_propia(self, term: str):
        car = self._kw_folder(term)
        if car and car.get("path"):
            try:
                os.makedirs(car["path"], exist_ok=True)
            except OSError as exc:
                self.ctrl.message.emit(f"✗ No pude crear la carpeta: {exc}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(car["path"]))

    def _reveal_path(self, path: str):
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def _kw_unlink(self, term: str, path: str):
        KF.unlink_folder(_kw_root(), term, path)
        self._kw_refrescar(f"🔗 «{_corta_ruta(path)}» desvinculada de «{term}». La carpeta de tu PC no se tocó.")

    def _kw_unlink_file(self, term: str, path: str):
        KF.unlink_file(_kw_root(), term, path)
        self._kw_refrescar(f"🔗 «{os.path.basename(path)}» desvinculado de «{term}». El archivo no se tocó.")

    def _kw_trash_file(self, path: str):
        """Quita un archivo de la carpeta propia de Reclaimer (a la Papelera, recuperable)."""
        nombre = os.path.basename(path)
        if QMessageBox.question(self, "Quitar de la palabra", f"¿Mandar «{nombre}» a la Papelera?\n"
                                "Se puede recuperar desde la Papelera de Windows.") != QMessageBox.Yes:
            return
        if not _to_trash(path):
            self.ctrl.message.emit(f"No pude mandar «{nombre}» a la Papelera.")
            return
        norm = os.path.normcase(os.path.abspath(path))
        ids = [m.id for m in self.ctrl.project.media.values()
               if os.path.normcase(os.path.abspath(m.path)) == norm and not self.ctrl.project.is_media_used(m.id)]
        if ids:
            self.ctrl.remove_media(ids)
        self._kw_refrescar(f"🗑 «{nombre}» a la Papelera.")

    def _kw_remove(self, term: str):
        """Quita la palabra: manda a la Papelera SOLO su carpeta propia; las carpetas del PC se desvinculan."""
        root = _kw_root()
        car = self._kw_folder(term)
        if car is None:
            return
        propia = car.get("own_path")
        n_propios = len(car["files"]) - len(car["linked_files"])
        n_enl = len(car["links"])
        if propia:
            texto = (f"Se manda a la Papelera la carpeta de Reclaimer de «{term}» ({n_propios} archivos).\n"
                     "Tus carpetas del PC enlazadas NO se borran: solo se desvinculan.")
            if n_enl:
                texto += f"\n\nCarpetas del PC que se desvinculan: {n_enl}."
        else:
            texto = (f"«{term}» no tiene carpeta propia: solo se desvinculan sus {n_enl} carpeta(s) del PC.\n"
                     "No se borra nada.")
        if QMessageBox.question(self, "Quitar palabra clave", f"¿Quitar la palabra clave «{term}»?\n\n{texto}") \
                != QMessageBox.Yes:
            return
        ids_propios: list[str] = []
        if propia:
            pref = os.path.normcase(os.path.abspath(propia)) + os.sep
            ids_propios = [m.id for m in self.ctrl.project.media.values()
                           if os.path.normcase(os.path.abspath(m.path)).startswith(pref)]
        if propia and hasattr(self.ctrl, "wait_analysis"):
            # (Windows no deja mover una carpeta con archivos abiertos: primero que acaben de leerse en segundo plano)
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.ctrl.wait_analysis(4000)
            finally:
                QApplication.restoreOverrideCursor()
        try:
            res = KF.delete_keyword(root, term, _to_trash)
        except OSError as exc:
            QMessageBox.warning(self, "Quitar palabra clave",
                                "No pude mandar la carpeta a la Papelera. No se ha quitado nada.\n"
                                "Algún archivo está en uso (¿se está reproduciendo o leyendo?): prueba otra vez en "
                                f"unos segundos.\n\n{exc}")
            return
        quitar = [i for i in ids_propios if not self.ctrl.project.is_media_used(i)]
        if quitar:
            self.ctrl.remove_media(quitar)
        donde = "su carpeta de Reclaimer a la Papelera" if res["trashed"] else "nada (no tenía carpeta propia)"
        self._kw_refrescar(f"🗑 «{term}» quitada: {donde}; {res['unlinked']} enlace(s) quitados. "
                           "Tus carpetas del PC siguen intactas.")

    def _kw_menu(self, item: QTreeWidgetItem, pos):
        kind = item.data(0, ROLE_KW_KIND)
        term = item.data(0, ROLE_KW_TERM) or ""
        path = item.data(0, ROLE_PATH) or ""
        menu = QMenu(self)
        if kind == "term":
            menu.addAction("🗂 Abrir en la ventana de carpetas (internet, borrar…)", lambda: self._kw_window(term))
            menu.addSeparator()
            menu.addAction("📂 Añadir carpeta de mi PC…", lambda: self._kw_link_dialog(term))
            menu.addAction("📁 Abrir carpeta", lambda: self._kw_abrir_propia(term))
            paths = self._kw_pick_paths(term)
            menu.addSeparator()
            menu.addAction(f"📍 Poner donde lo dices ({len(paths)})", lambda: self._kw_place(term, paths))
            menu.addAction("⏵ Poner en el cabezal", lambda: self._kw_place(term, paths, cabezal=True))
            menu.addSeparator()
            menu.addAction("🗑 Quitar palabra clave…", lambda: self._kw_remove(term))
        elif kind == "link":
            menu.addAction("📁 Abrir carpeta", lambda: self._kw_open(path))
            menu.addAction("Desvincular esta carpeta (no borra nada)", lambda: self._kw_unlink(term, path))
        else:
            paths = self._kw_pick_paths(term)
            menu.addAction(f"📍 Poner donde lo dices ({len(paths)})", lambda: self._kw_place(term, paths))
            menu.addAction("⏵ Poner en el cabezal", lambda: self._kw_place(term, paths, cabezal=True))
            menu.addAction("▶ Añadir a la timeline (en el cabezal)", lambda: self._kw_add_file(path))
            self._keyword_actions(menu, lambda: self._kw_ids([path]))
            menu.addAction("📁 Mostrar en el Explorador", lambda: self._reveal_path(path))
            menu.addSeparator()
            enlazados = {os.path.normcase(os.path.abspath(p)) for p in KF.linked_files(_kw_root(), term)}
            if os.path.normcase(os.path.abspath(path)) in enlazados:
                menu.addAction("Desvincular este archivo (no borra nada)", lambda: self._kw_unlink_file(term, path))
            elif item.data(0, ROLE_KW_LINKED):
                a = menu.addAction("🔗 Está en una carpeta de tu PC: no se borra desde aquí")
                a.setEnabled(False)
            else:
                menu.addAction("🗑 Quitar de la palabra (a la Papelera)…", lambda: self._kw_trash_file(path))
        add_help_action(menu, "palabras_clave", self.window())
        help_ui.exec_menu(menu, self.tree.viewport().mapToGlobal(pos))
