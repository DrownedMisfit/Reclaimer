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

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton, QStyle, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..ai import clip_analysis, embeddings
from ..core.model import AUDIO_EXT, IMAGE_EXT, KIND_AUDIO, KIND_IMAGE, VIDEO_EXT
from ..core.organize import CATEGORY_ORDER, matches_query
from . import help as help_ui
from .common import MEDIA_MIME, fmt_time
from .help import add_help_action, set_help
from .jobs import BackgroundJob

MEDIA_FILTER = "Medios ({});;Todos los archivos (*.*)".format(
    " ".join(f"*{e}" for e in sorted(VIDEO_EXT | AUDIO_EXT | IMAGE_EXT)))

ROLE_MEDIA = Qt.UserRole
ROLE_CATEGORY = Qt.UserRole + 1
ROLE_MOMENT = Qt.UserRole + 2   # mejor momento (resultados de la búsqueda IA)


def _to_trash(path: str) -> bool:
    """A la Papelera de Windows (recuperable). Según la versión de Qt devuelve bool o (bool, ruta)."""
    from PySide6.QtCore import QFile
    r = QFile.moveToTrash(path)
    return bool(r[0] if isinstance(r, tuple) else r)


class MediaTree(QTreeWidget):
    move_requested = Signal(list, str)     # (ids, categoría) — soltar archivos sobre una carpeta de Medios
    delete_pressed = Signal()

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

    def dragEnterEvent(self, e):
        if e.source() is self and e.mimeData().hasFormat(MEDIA_MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self and self._folder_at(e.position().toPoint()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        cat = self._folder_at(e.position().toPoint())
        if e.source() is self and cat:
            ids = [i for i in e.mimeData().data(MEDIA_MIME).data().decode().split(",") if i]
            self.move_requested.emit(ids, cat)
            e.acceptProposedAction()
        else:
            e.ignore()

    def startDrag(self, actions):
        ids = self.selected_media_ids()
        if not ids:
            return
        mime = QMimeData()
        mime.setData(MEDIA_MIME, QByteArray(",".join(ids).encode()))
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
    keywords_requested = Signal(list)          # 🔑 buscar palabras clave en estos archivos
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

        self.tree = MediaTree()
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
        top.addWidget(self.btn_analyze)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.addLayout(top)
        lay.addLayout(srow)
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
        self._update_footer()
        self._apply_filter()

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

    def _apply_filter(self):
        if self._results is not None or self.btn_ai_search.isChecked():
            return
        q = self.search.text()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
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
        if not query or self._search_job is not None:
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
        self._results = results
        self._rebuild()

    def _on_search_finished(self):
        job, self._search_job = self._search_job, None
        if job:
            job.deleteLater()

    # ----------------------------------------------------------- acciones
    def _on_double_click(self, item, _col):
        mid = item.data(0, ROLE_MEDIA)
        if not mid:
            return
        moment = item.data(0, ROLE_MOMENT)
        if moment is not None:
            self.add_moment_requested.emit(mid, float(moment))
        else:
            self.add_requested.emit([mid])

    def _context_menu(self, pos):
        ids = self.tree.selected_media_ids()
        if not ids:
            menu = QMenu(self)
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
            menu.addAction("🔑 Buscar palabras clave…", lambda: self.keywords_requested.emit(snd))
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
