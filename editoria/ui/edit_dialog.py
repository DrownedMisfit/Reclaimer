"""
Ventana «Crear edit musical»: eliges la canción, el ESTILO y los clips; la IA escucha la canción
(bombo, caja, compases, subidas, drop y pausas), mira el movimiento de tus clips y monta el edit
en la timeline al ritmo de la música. Cada efecto se puede activar o quitar.
Todo queda como clips normales: se puede mover, cambiar o deshacer (Ctrl+Z).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from ..ai import edit_engine, edit_maker
from ..core import media as media_tools
from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO
from . import fx_preview_ui as FXP
from . import help as help_ui
from .common import fmt_time
from .jobs import BackgroundJob


class EditDialog(QDialog):
    def __init__(self, ctrl, parent=None, embedded: bool = False):
        """embedded: dentro de la ventana principal, como panel (pestaña «Edits», a pantalla completa): las opciones en
        un panel y la lista de clips (self.clips_page) en otro, con miniaturas grandes; sin «Cerrar»."""
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.ctrl = ctrl
        self.job: BackgroundJob | None = None
        self._runs = 0   # cada «otra versión» elige otros planos
        self.setWindowTitle("🎵 Crear edit musical")
        self.resize(720, 720)
        help_ui.set_help(self, "edit_musical")
        lay = QVBoxLayout(self)
        form = QFormLayout()

        row = QHBoxLayout()
        self.song = QComboBox()
        self.song.setToolTip("Arrastra aquí una canción (o un video: se usa su sonido) desde tus carpetas, o un video "
                             "de la lista «Clips» de abajo.")
        self.song.setAcceptDrops(True)
        self.song.installEventFilter(self)
        row.addWidget(self.song, 1)
        pick = QPushButton("Otra canción…")
        pick.clicked.connect(self._pick_song)
        row.addWidget(pick)
        form.addRow("Canción", row)

        self.style = QComboBox()
        for key, st in edit_engine.STYLES.items():
            self.style.addItem(st["name"], key)
        form.addRow("Estilo", self.style)
        self.style_desc = QLabel("")
        self.style_desc.setWordWrap(True)
        self.style_desc.setObjectName("hint")
        form.addRow("", self.style_desc)

        self.length = QComboBox()
        for label, secs in (("Automático (~40 s alrededor del drop)", 40.0), ("30 segundos", 30.0),
                            ("45 segundos", 45.0), ("60 segundos", 60.0), ("Corto (~20 s)", 20.0),
                            ("Toda la canción", None)):
            self.length.addItem(label, secs)
        form.addRow("Duración", self.length)

        self.density = QComboBox()
        self.density.setToolTip("Cada cuánto corta, siempre en los golpes y compases de la canción. Cortes muy seguidos "
                                 "(ráfaga): solo una vez y si la canción es enérgica (rock, metal…); para ponerlos tú, "
                                 "«⚡ Ráfaga» en la barra de la línea de tiempo.")
        for label, key in (("Tranquilo (planos de 2 compases)", "tranquilo"), ("Normal (un plano por compás)", "normal"),
                           ("Intenso (cada 2 golpes en el drop)", "intenso"),
                           ("Frenético (un corte por golpe en el drop)", "frenetico")):
            self.density.addItem(label, key)
        form.addRow("Cortes", self.density)

        self.bg = QComboBox()
        for label, key in (("Fondo desenfocado", "blur"), ("Bandas negras", "none")):
            self.bg.addItem(label, key)
        form.addRow("Fondo (vertical)", self.bg)

        self.impact = QComboBox()
        for label, key in (("Destello blanco", "flash"), ("Imagen invertida (negativo)", "invert"),
                           ("Ninguno", "")):
            self.impact.addItem(label, key)
        self.impact.setToolTip("El «impact frame»: un fotograma de golpe en el drop y en las cajas fuertes.")
        form.addRow("Golpe en el drop", self.impact)
        page_song = QWidget()
        song_lay = QVBoxLayout(page_song)
        song_lay.addLayout(form)

        box = QGroupBox("")
        box.setToolTip("El estilo los elige; puedes cambiar cualquiera.")
        grid = QGridLayout(box)
        self.opt: dict[str, QCheckBox] = {}
        for i, (key, label, tip) in enumerate((
                ("velocity", "Velocity", "Cámara lenta justo en el golpe y acelerón hasta el siguiente."),
                ("shake", "Temblor con el bajo", "La imagen tiembla en los bombos fuertes y en el drop."),
                ("punch", "Zoom de golpe", "Zoom rápido que vuelve, al empezar cada compás fuerte."),
                ("glitch", "Glitch RGB", "Los colores se separan en las cajas fuertes."),
                ("strobe", "Estrobo en la subida", "Cortes muy rápidos con destellos justo antes del drop."),
                ("freeze", "Congelar en las paradas", "Si la música se calla de golpe, la imagen se congela."),
                ("slowmo_calm", "Cámara lenta en lo tranquilo", "Intro y pausas a media velocidad, suave."),
                ("transitions", "Transiciones en lo tranquilo", "Fundidos o latigazos solo en las partes calmadas."),
                ("grade", "Color del estilo", "Corrección de color (p. ej. blanco y negro contrastado)."),
                ("grain", "Grano", "Grano de película."),
                ("vignette", "Viñeta", "Bordes oscuros."),
                ("letterbox", "Barras de cine", "Franjas negras arriba y abajo."),
                ("extras", "Efectos de edit", "RGB, brillo soñador, contraste, VHS, parpadeo en el drop, giros de "
                                              "cámara, destellos de luz y desenfoque en el acelerón (según el estilo)."))):
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            FXP.attach(cb, "edit", key)             # 🎞 cómo se ve: icono y, al pasar el ratón, en movimiento
            self.opt[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        form = QFormLayout()

        game = QHBoxLayout()
        self.sound = QComboBox()
        self.sound.addItem("Sin el sonido de los clips", "none")
        self.sound.addItem("Todo el sonido de los clips, bajito", "all")
        self.sound.addItem("Solo los diálogos (sin el ruido de fondo)", "voice")
        self.sound.setToolTip("«Solo los diálogos»: la IA (Demucs, en tu tarjeta gráfica) separa las voces de la "
                              "música del juego, las explosiones y el ambiente. La canción no se toca.")
        self.game_vol = QDoubleSpinBox()
        self.game_vol.setRange(0.05, 1.0)
        self.game_vol.setSingleStep(0.05)
        self.game_vol.setValue(0.25)
        self.game_vol.setPrefix("Volumen ")
        self.game_vol.setEnabled(False)

        def _sound_changed(_i):
            k = self.sound.currentData()
            self.game_vol.setEnabled(k != "none")
            self.game_vol.setValue(0.8 if k == "voice" else 0.25)
        self.sound.currentIndexChanged.connect(_sound_changed)
        game.addWidget(self.sound)
        game.addWidget(self.game_vol)
        game.addStretch(1)
        form.addRow("Opción de sonido", game)
        song_lay.addLayout(form)
        song_lay.addStretch(1)

        page_clips = QWidget()
        clips_lay = QVBoxLayout(page_clips)
        self.clips = QListWidget()
        self.clips.setToolTip("Arrastra aquí videos o imágenes desde tus carpetas para usarlos en el edit.")
        self.clips.setAcceptDrops(True)
        self.clips.viewport().setAcceptDrops(True)
        self.clips.viewport().installEventFilter(self)
        self.clips.itemDoubleClicked.connect(self.pick_ranges)
        self.clips.setIconSize(QSize(160, 90) if embedded else QSize(64, 36))   # (en la pestaña Edits, grandes)
        # (sin altura fija: tan alta como lo que hay, de 2 a 8 filas; los nombres largos se recortan por el medio y
        # no hay barra lateral: antes la lista se desplazaba y se perdían las casillas y el principio del nombre)
        self.clips.setTextElideMode(Qt.ElideMiddle)
        self.clips.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.clips.setMouseTracking(True)                       # miniatura grande al pasar el ratón
        self.clips.itemEntered.connect(self._hover_clip)
        self._big = QLabel(self, Qt.ToolTip)
        self._big.setStyleSheet("background: #111; border: 1px solid #4a8fe0; padding: 2px;")
        self._big.hide()
        self._thumbs: dict[str, str] = {}
        self._thumb_job = None
        self.clips.setToolTip("Los marcados entran en el edit. Doble clic = elegir sus tramos. Arrastra aquí videos o "
                              "imágenes desde tus carpetas.\nArrastra un video a «Canción» (o clic derecho → «Usar "
                              "como canción») y su sonido será la canción.")
        # 🎵 un video de la lista → «Canción» (sin tener que convertirlo antes en Medios)
        from PySide6.QtWidgets import QAbstractItemView
        self.clips.setDragEnabled(True)
        self.clips.setDragDropMode(QAbstractItemView.DragOnly)      # (los archivos de fuera los recoge eventFilter)
        self.clips.setContextMenuPolicy(Qt.CustomContextMenu)
        self.clips.customContextMenuRequested.connect(self._clip_menu)
        clips_lay.addWidget(self.clips)
        sel = QHBoxLayout()
        for text, on in (("Todos", True), ("Ninguno", False)):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.clicked.connect(lambda _=False, v=on: self._check_all(v))
            sel.addWidget(b)
        sel.addStretch(1)
        self.b_ranges = QPushButton("✂ Elegir tramos…")
        self.b_ranges.setToolTip("Del video elegido en la lista, marca a mano de dónde a dónde puede sacar planos "
                                 "la IA (también con doble clic en el video).")
        self.b_ranges.clicked.connect(lambda: self.pick_ranges(self.clips.currentItem()))
        sel.addWidget(self.b_ranges)
        clips_lay.addLayout(sel)

        page_quotes = QWidget()
        quotes_lay = QVBoxLayout(page_quotes)
        self.quotes = QPlainTextEdit()
        self.quotes.setToolTip("Frases de la intro: opcional, una por línea; la última sale palabra por palabra.")
        self.quotes.setPlaceholderText("Esto no es el final\nEs solo el comienzo\nY aquí empieza todo")
        quotes_lay.addWidget(self.quotes, 1)
        from .spellcheck import attach as _spell
        quotes_lay.addWidget(_spell(self.quotes))
        krow = QHBoxLayout()
        krow.addWidget(QLabel("🔑 Planos donde se dice:"))
        self.kw = QLineEdit()
        self.kw.setPlaceholderText("Marcus, traición, explosión…")
        self.kw.setToolTip("La IA busca esas palabras en el sonido de tus videos (ligero: solo donde se habla) y "
                           "prefiere los planos donde se dicen.")
        krow.addWidget(self.kw, 1)
        self.kw_drop = QCheckBox("Uno en el drop")
        self.kw_drop.setChecked(True)
        krow.addWidget(self.kw_drop)
        quotes_lay.addLayout(krow)

        # Limpio, como Resolve: secciones una debajo de otra que se abren y cierran con su flecha (▾ / ▸);
        # «Clips» abierta de entrada. Abajo, siempre, cómo va y los botones.
        from .tabs import sections
        partes = [("Canción y estilo", page_song, True), ("Efectos", box, True if embedded else False)]
        if not embedded:
            partes.append(("Clips", page_clips, True))
        partes.append(("Frases", page_quotes, False))
        self.clips_page = page_clips if embedded else None      # (en la pestaña Edits, en su propio panel)
        self.sections_area, self.sections = sections(partes, key="edit_musical_panel" if embedded else "edit_musical")
        self.sections_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.sections_area, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = QPushButton("Cerrar")
        self.cancel_btn.clicked.connect(self._cancel)
        self.go = QPushButton("🎵  Crear edit")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._start)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.go)
        lay.addLayout(btns)
        if embedded:                                 # (como panel: «Cerrar» no tiene sentido; solo sirve para detener)
            self.cancel_btn.setText("Detener")
            self.cancel_btn.setToolTip("Detiene el edit que se está creando")
            self.cancel_btn.hide()
            ctrl.media_changed.connect(lambda: self._fill(self.song.currentData()) if self.job is None else None)
        for sec in self.sections.values():         # al abrir o cerrar una sección, el tamaño justo
            sec.head.toggled.connect(lambda _on: QTimer.singleShot(0, self._fit))
        self._fill()
        self.style.currentIndexChanged.connect(self._style_changed)
        last = QSettings("EditorIA", "EditorIA").value("edits/estilo", "phonk")
        last = "hype" if last == "halo" else last          # (el estilo antiguo se fusionó con «Hype gaming»)
        self.style.setCurrentIndex(max(0, self.style.findData(last)))
        self._style_changed()

    def _style_changed(self, *_):
        key = self.style.currentData()
        st = edit_engine.STYLES.get(key) or edit_engine.STYLES["phonk"]
        self.style_desc.setText(st["desc"])
        self.density.setCurrentIndex(max(0, self.density.findData(st["density"])))
        self.impact.setCurrentIndex(max(0, self.impact.findData(st["impact"])))
        for k, cb in self.opt.items():
            cb.setChecked(True if k == "extras" else bool(st.get(k)))
            cb.setEnabled(True)
        self.impact.model().item(1).setEnabled(True)

    # ------------------------------------------------------------ datos
    def _fill(self, select_song: str | None = None):
        p = self.ctrl.project
        self.song.clear()
        songs = [m for m in p.media.values() if m.kind == KIND_AUDIO and m.id not in self.ctrl.missing]
        songs.sort(key=lambda m: (not any(w in m.category.lower() for w in ("músic", "music", "song")), m.name))
        for m in songs:
            self.song.addItem(f"{m.name}  ({fmt_time(m.duration)})", m.id)
        if select_song:
            self.song.setCurrentIndex(max(0, self.song.findData(select_song)))
        checked = {self.clips.item(i).data(Qt.UserRole) for i in range(self.clips.count())
                   if self.clips.item(i).checkState() == Qt.Checked}
        self.clips.clear()
        for m in sorted(p.media.values(), key=lambda m: (m.kind != KIND_VIDEO, m.name)):
            if m.kind not in (KIND_VIDEO, KIND_IMAGE) or m.id in self.ctrl.missing:
                continue
            extra = fmt_time(m.duration) if m.kind == KIND_VIDEO else "imagen"
            if m.kind == KIND_VIDEO and m.edit_ranges:
                extra += f"   ·  ✂ {len(m.edit_ranges)} tramo(s), {sum(b - a for a, b in m.edit_ranges):.0f} s"
            it = QListWidgetItem(f"{'🎞' if m.kind == KIND_VIDEO else '🖼'}  {m.name}   ·  {extra}")
            it.setData(Qt.UserRole, m.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (not checked or m.id in checked) else Qt.Unchecked)
            if m.id in self._thumbs:
                it.setIcon(QIcon(self._thumbs[m.id]))
            it.setToolTip(m.name)
            self.clips.addItem(it)
        self._fit_list()
        self._load_thumbs()
        if not songs:
            self.status.setText("Primero importa una canción (o pulsa «Otra canción…»).")

    def _fit_list(self):
        """La lista de clips, tan alta como sus filas (de 2 a 8; si hay más, se desplaza dentro)."""
        if self.embedded:                            # (en su panel ocupa todo el alto)
            return
        n = self.clips.count()
        row = self.clips.sizeHintForRow(0) if n else 0
        row = max(row, self.clips.iconSize().height() + 6, self.fontMetrics().height() + 8)
        self.clips.setFixedHeight(row * max(2, min(8, n)) + 2 * self.clips.frameWidth() + 4)
        if self.isVisible():
            QTimer.singleShot(0, self._fit)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        if self.embedded:                            # (como panel, el tamaño lo pone la ventana principal)
            return
        """El tamaño justo: lo que ocupa lo que hay (sin huecos vacíos), nunca más alto que la pantalla y siempre
        dentro de ella. Los botones de abajo siempre se ven; si no cabe todo, las secciones se desplazan."""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QWidget
        scr = (QWidget.screen(self) or QGuiApplication.primaryScreen()).availableGeometry()
        inner = self.sections_area.widget()
        inner.layout().activate()
        content = inner.sizeHint().height() + 2 * self.sections_area.frameWidth() + 4
        lay = self.layout()
        rest = lay.sizeHint().height() - self.sections_area.sizeHint().height()
        frame = self.frameGeometry().height() - self.geometry().height()
        h = min(content + rest, scr.height() - frame - 16)
        # ancho: el que pide lo de dentro + la barra de desplazamiento (si no, se cortaba por la derecha)
        m = lay.contentsMargins()
        need = (inner.minimumSizeHint().width() + self.sections_area.verticalScrollBar().sizeHint().width()
                + m.left() + m.right() + 2 * self.sections_area.frameWidth() + 4)
        w = min(max(self.width(), need, self.minimumSizeHint().width()), scr.width() - 16)
        self.resize(w, max(h, self.minimumSizeHint().height()))
        g = self.frameGeometry()
        x = min(max(g.left(), scr.left() + 8), scr.right() - g.width() - 8)
        y = min(max(g.top(), scr.top() + 8), scr.bottom() - g.height() - 8)
        if (x, y) != (g.left(), g.top()):
            self.move(x, y)

    def _load_thumbs(self):
        """Miniaturas de los clips, poco a poco y sin parar la ventana (se guardan: la próxima vez, al instante)."""
        p = self.ctrl.project
        todo = [(m.id, m.path, m.kind, m.duration) for m in p.media.values()
                if m.kind in (KIND_VIDEO, KIND_IMAGE) and m.id not in self._thumbs and m.id not in self.ctrl.missing]
        if not todo or self._thumb_job is not None:
            return

        def work(progress, cancelled, partial):
            for mid, path, kind, dur in todo:
                if cancelled():
                    break
                th = media_tools.thumbnail(path, kind, dur)
                if th:
                    partial((mid, th))

        def got(msg):
            mid, th = msg
            self._thumbs[mid] = th
            for i in range(self.clips.count()):
                it = self.clips.item(i)
                if it.data(Qt.UserRole) == mid:
                    it.setIcon(QIcon(th))
        self._thumb_job = BackgroundJob(work, self, with_partial=True)
        self._thumb_job.partial.connect(got)
        self._thumb_job.finished.connect(lambda: setattr(self, "_thumb_job", None))
        self._thumb_job.start()

    def _hover_clip(self, it):
        """Al pasar el ratón por un clip: su miniatura en grande, al lado."""
        th = self._thumbs.get(it.data(Qt.UserRole)) if it is not None else None
        if not th:
            self._big.hide()
            return
        pm = QPixmap(th)
        if pm.isNull():
            self._big.hide()
            return
        self._big.setPixmap(pm.scaled(360, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._big.adjustSize()
        r = self.clips.visualItemRect(it)
        pos = self.clips.viewport().mapToGlobal(r.topLeft())
        x = pos.x() + 80
        y = pos.y() - self._big.height() - 6
        if y < 0:
            y = pos.y() + r.height() + 6
        self._big.move(x, y)
        self._big.show()
        self._big.raise_()

    def pick_ranges(self, it):
        """✂ Los tramos de ese video que puede usar la IA (se guardan con el proyecto)."""
        from .range_picker import RangePicker
        if it is None:
            self.status.setText("Elige primero un video de la lista.")
            return
        m = self.ctrl.project.media.get(it.data(Qt.UserRole))
        if m is None or m.kind != KIND_VIDEO:
            self.status.setText("Los tramos son para videos (las imágenes se usan enteras).")
            return
        dlg = RangePicker(m, m.edit_ranges, self)
        if dlg.exec():
            self.ctrl.set_media_props([m.id], edit_ranges=dlg.ranges())
            row = self.clips.row(it)
            self._fill(select_song=self.song.currentData())
            self.clips.setCurrentRow(row)
            n = len(m.edit_ranges)
            self.status.setText(f"✂ «{m.name}»: " + (f"{n} tramo(s) elegido(s); la IA solo usará esos."
                                                     if n else "se usará el video entero."))

    def _check_all(self, on: bool):
        for i in range(self.clips.count()):
            self.clips.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _pick_song(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir canción", "",
                                              "Audio o video (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.mp4 "
                                              "*.mkv *.mov *.webm *.avi);;Todos (*.*)")
        if path:
            self.use_song_file(path)

    def use_song_file(self, path: str):
        """La canción desde un archivo: un audio se usa tal cual; de un video se saca su sonido (sin perder
        calidad, a «Audio extraído»)."""
        from ..core.model import kind_for_path
        kind = kind_for_path(path)
        if kind == KIND_AUDIO:
            ids = self.ctrl.import_now([path])
            if ids:
                self.ctrl.set_media_props(ids, category="Música")
                self._fill(select_song=ids[0])
            return
        if kind != KIND_VIDEO:
            self.status.setText("Eso no es un audio ni un video.")
            return
        from ..core import audio_extract
        self.status.setText("🎵 Sacando el sonido del video para usarlo de canción…")

        def work(progress, cancelled):
            return audio_extract.extract(path, 0.0, lambda f: progress(f, "🎵 Sacando el sonido…"), cancelled)

        def done(wav):
            ids = self.ctrl.import_now([wav])
            if ids:
                self.ctrl.set_media_props(ids, category="Música")
                self._fill(select_song=ids[0])
                self.status.setText(f"✓ Canción: el sonido de «{os.path.basename(path)}».")
        self._song_job = BackgroundJob(work, self)
        self._song_job.done.connect(done)
        self._song_job.failed.connect(lambda m: self.status.setText("✗ " + m))
        self._song_job.start()

    def eventFilter(self, obj, e):
        """Soltar archivos de tus carpetas: en «Canción» = la canción; en la lista = clips para el edit."""
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Leave and obj is self.clips.viewport():
            self._big.hide()
        from_list = obj is self.song and e.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop) \
            and getattr(e, "source", lambda: None)() is self.clips
        if from_list:                                   # 🎵 un clip de la lista soltado en «Canción»
            if e.type() == QEvent.Drop:
                it = self.clips.currentItem()
                if it is not None:
                    self.use_clip_as_song(it.data(Qt.UserRole))
            e.setDropAction(Qt.CopyAction)
            e.accept()
            return True
        if e.type() in (QEvent.DragEnter, QEvent.DragMove) and e.mimeData().hasUrls():
            e.acceptProposedAction()
            return True
        if e.type() == QEvent.Drop and e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if obj is self.song and paths:
                self.use_song_file(paths[0])
            elif paths:
                self.add_clip_files(paths)
            e.acceptProposedAction()
            return True
        return super().eventFilter(obj, e)

    def _clip_menu(self, pos):
        it = self.clips.itemAt(pos)
        m = self.ctrl.project.media.get(it.data(Qt.UserRole)) if it is not None else None
        if m is None or m.kind != KIND_VIDEO:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("🎵 Usar como canción", lambda: self.use_clip_as_song(m.id))
        menu.addAction("✂ Elegir tramos…", lambda: self.pick_ranges(it))
        help_ui.exec_menu(menu, self.clips.viewport().mapToGlobal(pos))

    def use_clip_as_song(self, media_id: str):
        """🎵 Un video de la lista como canción: se usa su sonido (como «Convertir en solo audio», sin salir de aquí).
        Ese video deja de estar marcado como clip (sus imágenes no entran en el edit; se puede volver a marcar). Si ya
        se había sacado su sonido antes, se reutiliza."""
        p = self.ctrl.project
        m = p.media.get(media_id)
        if m is None or m.kind != KIND_VIDEO:
            self.status.setText("Para la canción, arrastra un video.")
            return
        for i in range(self.clips.count()):
            if self.clips.item(i).data(Qt.UserRole) == media_id:
                self.clips.item(i).setCheckState(Qt.Unchecked)
        from ..core import audio_extract
        stem = os.path.splitext(os.path.basename(m.path))[0]
        folder = os.path.normcase(os.path.abspath(audio_extract.out_dir()))
        for a in p.media.values():                   # ya se había sacado: se reutiliza
            if a.kind == KIND_AUDIO and a.id not in self.ctrl.missing and \
                    os.path.normcase(os.path.dirname(os.path.abspath(a.path))) == folder and \
                    os.path.splitext(os.path.basename(a.path))[0] in (stem, *(f"{stem} ({n})" for n in range(2, 10))):
                self._fill(select_song=a.id)
                self.status.setText(f"✓ Canción: el sonido de «{m.name}» (ya estaba sacado). Lo quité de los clips; "
                                    "márcalo si también quieres sus imágenes.")
                return
        self.use_song_file(m.path)
        self.status.setText(f"🎵 Sacando el sonido de «{m.name}» para usarlo de canción… (lo quité de los clips; "
                            "márcalo si también quieres sus imágenes)")

    def add_clip_files(self, paths):
        from ..core.model import kind_for_path
        vids = [p_ for p_ in paths if kind_for_path(p_) in (KIND_VIDEO, KIND_IMAGE)]
        auds = [p_ for p_ in paths if kind_for_path(p_) == KIND_AUDIO]
        if auds:
            self.use_song_file(auds[0])
        if vids:
            ids = self.ctrl.import_now(vids)
            self._fill(select_song=self.song.currentData())
            for i in range(self.clips.count()):
                if self.clips.item(i).data(Qt.UserRole) in ids:
                    self.clips.item(i).setCheckState(Qt.Checked)

    # ------------------------------------------------------------ crear
    def options(self) -> dict:
        quotes = [q for q in self.quotes.toPlainText().splitlines() if q.strip()]
        key = self.style.currentData()
        dens = self.density.currentData()
        st = edit_engine.STYLES[key]
        ov = {"density": dens, "impact": self.impact.currentData()}
        for k, cb in self.opt.items():
            on = cb.isChecked()
            if k == "transitions":
                ov[k] = (st["transitions"] or "fade") if on else ""
            elif k == "grade":
                ov[k] = (st["grade"] or {"contrast": 0.2}) if on else {}
            elif k in ("grain", "vignette", "letterbox"):
                ov[k] = (float(st[k]) or {"grain": 0.3, "vignette": 0.45, "letterbox": 0.11}[k]) if on else 0.0
            else:
                ov[k] = on
        return {"style": key, "length": self.length.currentData(), "quotes": quotes, "seed": 7 + self._runs,
                "overrides": ov}

    def _start(self):
        p = self.ctrl.project
        self._proj_start = p                         # (si al acabar el proyecto es otro, no se pone en él)
        song_id = self.song.currentData()
        if not song_id:
            QMessageBox.information(self, "Edit musical", "Elige una canción.")
            return
        song = p.media[song_id]
        if song.duration <= 0:
            QMessageBox.information(self, "Edit musical", "La canción todavía se está analizando. Prueba en un momento.")
            return
        sources = []
        for i in range(self.clips.count()):
            it = self.clips.item(i)
            if it.checkState() != Qt.Checked:
                continue
            m = p.media[it.data(Qt.UserRole)]
            sources.append({"media_id": m.id, "path": m.path, "kind": m.kind, "duration": m.duration,
                            "name": m.name})
        if not any(s["kind"] == KIND_VIDEO for s in sources):
            QMessageBox.information(self, "Edit musical", "Marca al menos un video.")
            return
        opts = self.options()
        ranges = {s["media_id"]: [list(r) for r in p.media[s["media_id"]].edit_ranges]
                  for s in sources if p.media[s["media_id"]].edit_ranges}
        if ranges:                               # ✂ solo de los tramos elegidos a mano (también en Remix/Mix)
            opts["ranges"] = ranges
        self._ctx = {"options": dict(opts), "sources": [s["media_id"] for s in sources]}
        from ..ai import edit_feedback               # lo que aprendió de tus 👍/👎 (y 📚 de tus edits de ejemplo)
        opts["learned"] = edit_feedback.learned(opts["style"])
        opts["avoid"] = self.ctrl.edit_avoid()        # 👎 planos vetados en este proyecto: no vuelven a salir
        QSettings("EditorIA", "EditorIA").setValue("edits/estilo", self.style.currentData())
        self.go.setEnabled(False)
        self.cancel_btn.setText("Cancelar")
        self.bar.show()
        from ..ai import keywords as KW
        query = KW.parse_query(self.kw.text())
        vids = [s for s in sources if s["kind"] == KIND_VIDEO and p.media[s["media_id"]].has_audio]
        transcripts = {s["media_id"]: p.transcripts.get(s["media_id"]) for s in vids}
        ctx = self._ctx

        def work(prog, cancelled):
            if query and vids:              # 🔑 primero, dónde se dicen tus palabras (ligero)
                hits = {}
                for i, s in enumerate(vids):
                    got = KW.find(s["path"], query, transcripts.get(s["media_id"]),
                                  lambda f, t, i=i: prog(0.3 * (i + f) / len(vids), "🔑 " + t), cancelled)
                    if got:
                        hits[s["media_id"]] = [round(h["t0"], 3) for h in got]
                opts["keyword_hits"], opts["keyword_drop"] = hits, self.kw_drop.isChecked()
                ctx["options"]["keyword_hits"], ctx["options"]["keyword_drop"] = hits, self.kw_drop.isChecked()
                n = sum(len(v) for v in hits.values())
                prog(0.3, f"🔑 {n} momento(s) con tus palabras" if n else "🔑 No se dicen esas palabras")

                def prog2(f, t):
                    prog(0.3 + 0.7 * f, t)
                return edit_maker.make_edit(song.path, song.id, sources, opts, prog2, cancelled)
            return edit_maker.make_edit(song.path, song.id, sources, opts, prog, cancelled)
        self.job = BackgroundJob(work, self)
        self.job.progress.connect(self._on_progress)
        self.job.done.connect(self._on_done)
        self.job.failed.connect(self._on_failed)
        self.job.start()
        if self.embedded:
            self.cancel_btn.show()

    def _on_progress(self, frac: float, text: str):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)

    def _on_done(self, plan: dict):
        self.job = None
        if self.embedded:
            self.cancel_btn.hide()
        if getattr(self, "_proj_start", self.ctrl.project) is not self.ctrl.project:
            self.bar.hide()
            self.go.setEnabled(True)
            self.status.setText("✗ Cambiaste de proyecto mientras se creaba el edit: no se puso. Vuelve a crearlo.")
            return
        if self.sound.currentData() == "voice" and not plan.get("_dialogue_done"):
            self._separate_then_apply(plan)
            return
        self.bar.hide()
        try:
            self.ctrl.apply_edit_plan(plan, layout=self.bg.currentData(),
                                      game_volume=self.game_vol.value() if self.sound.currentData() != "none" else 0.0,
                                      ctx=getattr(self, "_ctx", None))
        except Exception as exc:  # noqa: BLE001 - p. ej. pista bloqueada
            self._on_failed(str(exc))
            return
        self.plan = plan
        self._runs += 1
        learned = ""
        if plan.get("learned_n"):
            from ..ai import edit_feedback
            what = edit_feedback.describe(edit_feedback.learned(plan.get("style", "")))
            learned = f"\n◈ Con lo que aprendió de {plan['learned_n']} notas tuyas" + (f": {what}." if what else ".")
        self.status.setText("✓ " + plan["summary"] + "." + learned +
                            "\nMuévelo o cámbialo a tu gusto · califícalo con 👍/👎 (barra de la línea de tiempo) · "
                            "🔀 Remix lo rehace entero · 🎛 Mix rehace solo lo que selecciones.")
        self.go.setEnabled(True)
        self.go.setText("🎵  Crear otra versión")
        self.cancel_btn.setText("Detener" if self.embedded else "Cerrar")
        tl = getattr(self.parent(), "timeline", None) if self.embedded else None
        if tl is not None:                           # (como panel: que se vea el edit entero en la línea de tiempo)
            tl.fit()

    def _separate_then_apply(self, plan: dict):
        """🗣 Antes de montar: los videos del edit, con solo los diálogos (una vez por archivo; se guarda)."""
        from ..ai import dialogue
        from .jobs import BackgroundJob
        p = self.ctrl.project
        vids = [p.media[mid] for mid in dict.fromkeys(it["media_id"] for it in plan.get("clips", []))
                if mid in p.media and p.media[mid].kind == "video" and p.media[mid].has_audio]

        def work(progress, cancelled):
            out = {}
            for i, m in enumerate(vids):
                out[m.id] = dialogue.isolate(
                    m.path, lambda f, t, i=i, m=m: progress((i + f) / max(1, len(vids)), f"🗣 «{m.name}»: {t}"),
                    cancelled)
            return out

        def done(paths: dict):
            voice = {}
            for mid, wav in paths.items():
                got = self.ctrl.import_now([wav])
                if got:
                    self.ctrl.set_media_props(got, category="Diálogos (IA)")
                    voice[mid] = got[0]
            self._ctx = dict(getattr(self, "_ctx", None) or {}, dialogue=voice)
            plan["_dialogue_done"] = True
            self._on_done(plan)

        self.status.setText("🗣 Separando los diálogos del ruido de fondo (Demucs, en tu tarjeta gráfica)…")
        self.job = BackgroundJob(work, self)
        self.job.progress.connect(self._on_progress)
        self.job.done.connect(done)
        self.job.failed.connect(self._on_failed)
        self.job.start()

    def _on_failed(self, msg: str):
        self.job = None
        if self.embedded:
            self.cancel_btn.hide()
        self.bar.hide()
        self.go.setEnabled(True)
        self.cancel_btn.setText("Detener" if self.embedded else "Cerrar")
        self.status.setText("✗ " + msg)

    def reject(self):
        if self.embedded:                            # (como panel: Esc no lo oculta; solo detiene si está creando)
            if self.job is not None:
                self.job.cancel()
            return
        super().reject()

    def _cancel(self):
        if self.job is not None:
            self.job.cancel()
            return
        if not self.embedded:
            self.accept()

    def closeEvent(self, e):
        self._big.hide()
        FXP.hide()
        if self._thumb_job is not None:
            self._thumb_job.cancel()
            self._thumb_job.wait(3000)
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
        super().closeEvent(e)
