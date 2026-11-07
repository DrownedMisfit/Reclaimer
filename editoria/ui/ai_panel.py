"""
Panel «Edición IA»:
  1. Temas de la narración (marcadores de tramo en la timeline).
  2. B-roll: para cada frase, clips de tu biblioteca que encajan con lo que dices.
     - Sugerir: tú eliges entre 3 candidatos (doble clic = insertar).
     - Automático: la IA rellena los huecos libres con el mejor candidato.
     La IA nunca tapa clips que ya colocaste tú, ni toca pistas bloqueadas.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QMenu, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..ai import broll_selection, clip_analysis, topic_detection
import re

from ..core import audio_fx
from ..core.organize import normalize
from ..core import mapping, subtitles
from ..core.model import KIND_AUDIO, KIND_IMAGE, ORIGIN_AI, TRACK_VIDEO
from . import help as help_ui
from .common import fmt_time
from .help import set_help
from .jobs import BackgroundJob

PREFERENCES = [("Gameplay > Cinemáticas > Imágenes", ["Gameplay", "Cinemáticas", "Imágenes"]),
               ("Cinemáticas > Gameplay > Imágenes", ["Cinemáticas", "Gameplay", "Imágenes"]),
               ("Sin preferencia", [])]


def _dim(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


def _dot(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(1, 1, 10, 10, 3, 3)
    p.end()
    return QIcon(pix)


# Mapa de la IA: (clave, icono y nombre, qué hace)
AI_CARDS = [
    ("auto", "✨ Autoedición", "Monta una primera versión completa a partir de tu voz."),
    ("understand", "🔬 Entender mis clips", "Aprende quién y qué aparece en cada segundo de tus clips."),
    ("moments", "🔎 Buscar momentos", "Encuentra dónde aparece algo y ponlo en la línea de tiempo."),
    ("voice", "🎙 Voz y limpieza", "Transcribe y quita silencios, muletillas y repeticiones."),
    ("topics", "◎ Temas", "Divide tu narración en partes (historia, combate…)."),
    ("broll", "🎬 B-roll", "Elige clips que encajan con lo que dices."),
    ("visual", "🔍 Zooms y comparaciones", "Zoom cuando dices «miren»; comparación cuando comparas."),
    ("audio", "🔊 Audio inteligente", "Mejora tu voz, baja la música al hablar, cortes a ritmo."),
    ("director", "🎬 Modo Director", "Escribe lo que quieres para una parte y la IA lo monta."),
    ("edit", "🎵 Edit musical", "Monta un edit sin comentario, a ritmo de una canción."),
    ("audit", "⚕ Revisión", "Busca errores antes de exportar: negro, audio, repetidos…"),
    ("cutout", "✂ Recortar sujeto", "Separa un personaje, roca o vehículo del fondo en todo el clip."),
    ("compare", "⧉ Comparación", "Pon dos clips lado a lado (antes / después, versiones)."),
    ("keywords", "🔑 Palabras clave", "Dónde se dice algo en tus videos y audios, gastando poco."),
]


class AIPanel(QWidget):
    action_requested = Signal(str)   # tarjeta del mapa de la IA (lo atiende la ventana principal)

    def __init__(self, ctrl, engine, timeline, preferred_media, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.timeline = timeline
        self._preferred_media = preferred_media
        self.settings = QSettings("EditorIA", "EditorIA")
        self.job: BackgroundJob | None = None
        self.slots: list[dict] = []
        self._thumbs: dict[str, QIcon] = {}

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(6, 6, 6, 6)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = _dim()
        self.status.setObjectName("hint")
        self.btn_first = QPushButton("✨  Primera versión automática…")
        self.btn_first.setObjectName("primary")
        self.btn_first.setMinimumHeight(34)
        set_help(self.btn_first, "primera_version")
        self.btn_first.hide()   # (la tarjeta «✨ Autoedición» del mapa hace lo mismo: sin botones duplicados)
        # --- Mapa de la IA: qué hace → qué encontró → qué puedes hacer (un clic) ---
        mapbox = QGroupBox("Qué puede hacer la IA por ti")
        grid = QGridLayout(mapbox)
        grid.setSpacing(4)
        self.cards: dict[str, tuple[QPushButton, QLabel]] = {}
        for k, (key, title, what) in enumerate(AI_CARDS):
            btn = QPushButton(title)
            btn.setToolTip(what)
            btn.setStyleSheet("text-align: left; padding: 5px 8px; font-weight: 600;")
            btn.clicked.connect(lambda _=False, kk=key: self._card(kk))
            btn.setMinimumHeight(34)
            st = QLabel(what)          # (lo que hizo / encontró: va en la ayuda emergente del botón)
            st.hide()
            grid.addWidget(btn, k // 2, k % 2)
            self.cards[key] = (btn, st)
        self._mapbox = set_help(mapbox, "mapa_ia")
        lay.addWidget(self.progress)
        lay.addWidget(self.status)

        # --- 1. Temas ---
        g1 = QGroupBox("1 · Temas de la narración")
        v1 = QVBoxLayout(g1)
        self.btn_topics = QPushButton("◎ Detectar temas")
        self.btn_topics.setObjectName("primary")
        self.btn_topics.clicked.connect(self.detect_topics)
        v1.addWidget(self.btn_topics)
        self.topic_list = QTreeWidget()
        self.topic_list.setHeaderLabels(["Tramo", "Tema"])
        self.topic_list.setRootIsDecorated(False)
        self.topic_list.setColumnWidth(0, 120)
        self.topic_list.setMaximumHeight(170)
        self.topic_list.itemDoubleClicked.connect(self._topic_double_click)
        self.topic_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.topic_list.customContextMenuRequested.connect(self._topic_menu)
        self.topic_list.setProperty("own_menu", True)
        v1.addWidget(self.topic_list)
        set_help(g1, "temas")

        # --- 2. B-roll ---
        g2 = QGroupBox("2 · B-roll: clips para lo que dices")
        v2 = QVBoxLayout(g2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Cambiar de clip cada"))
        self.min_len = QDoubleSpinBox()
        self.min_len.setRange(1.0, 20.0)
        self.min_len.setSingleStep(0.5)
        self.min_len.setSuffix(" s")
        self.max_len = QDoubleSpinBox()
        self.max_len.setRange(1.5, 30.0)
        self.max_len.setSingleStep(0.5)
        self.max_len.setSuffix(" s")
        row.addWidget(self.min_len)
        row.addWidget(QLabel("a"))
        row.addWidget(self.max_len)
        v2.addLayout(row)
        row2 = QHBoxLayout()
        self.btn_understand = QPushButton("🔬 Entender mi biblioteca a fondo…")
        self.btn_understand.setToolTip("La IA revisa cada segundo de tus clips y aprende quién y qué aparece, "
                                       "para mostrarlo cuando lo nombras.")
        row2.addWidget(self.btn_understand, 1)
        self.btn_moments = QPushButton("🔎 Buscar momentos…")
        self.btn_moments.setToolTip("Busca dónde aparece algo en tus medios (por texto o por imagen) y ponlo en la "
                                    "línea de tiempo.")
        row2.addWidget(self.btn_moments)
        v2.addLayout(row2)
        self.understand_label = _dim()
        self.understand_label.setWordWrap(True)
        v2.addWidget(self.understand_label)
        self.continuous = QCheckBox("Gameplay continuo de fondo cuando no nombras nada concreto")
        self.continuous.setToolTip("Sigue el mismo clip de gameplay donde se quedó (cambia al cambiar de tema), "
                                   "en vez de saltar entre clips.")
        v2.addWidget(self.continuous)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Pista"))
        self.track = QComboBox()
        row3.addWidget(self.track, 1)
        row3.addWidget(QLabel("Sonido del clip"))
        self.clip_vol = QSpinBox()
        self.clip_vol.setRange(0, 100)
        self.clip_vol.setSuffix(" %")
        self.clip_vol.setToolTip("Volumen del audio del propio clip (el del juego) bajo tu narración.")
        row3.addWidget(self.clip_vol)
        v2.addLayout(row3)
        self.avoid = QCheckBox("No repetir clips")
        v2.addWidget(self.avoid)
        self.btn_propose = QPushButton("🎬 Proponer B-roll")
        self.btn_propose.setObjectName("primary")
        self.btn_propose.clicked.connect(self.propose)
        v2.addWidget(self.btn_propose)

        self.slot_tree = QTreeWidget()
        self.slot_tree.setHeaderLabels(["Momento / clip", "Por qué"])
        self.slot_tree.setColumnWidth(0, 230)
        self.slot_tree.setIconSize(QPixmap(48, 27).size())
        self.slot_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.slot_tree.setMinimumHeight(260)
        self.slot_tree.itemDoubleClicked.connect(self._slot_double_click)
        self.slot_tree.itemSelectionChanged.connect(self._slot_selected)
        v2.addWidget(self.slot_tree, 1)
        b = QHBoxLayout()
        self.btn_insert = QPushButton("✓ Insertar elegido")
        self.btn_insert.clicked.connect(self.insert_selected)
        self.btn_auto = QPushButton("⚡ Rellenar huecos con lo mejor")
        self.btn_auto.setToolTip("Modo automático: la IA coloca el mejor clip en cada hueco LIBRE de la pista.\n"
                                 "Nunca tapa los clips que ya colocaste tú.")
        self.btn_auto.clicked.connect(self.auto_fill)
        b.addWidget(self.btn_insert)
        b.addWidget(self.btn_auto)
        v2.addLayout(b)
        set_help(g2, "broll")

        # --- 3. Zoom en momentos clave ---
        g3 = QGroupBox("3 · Sugerencias visuales (zoom y comparaciones)")
        v3 = QVBoxLayout(g3)
        self.btn_zoom_find = QPushButton("🔍 Buscar momentos (zoom y comparaciones)")
        self.btn_zoom_find.clicked.connect(self.find_zoom_moments)
        v3.addWidget(self.btn_zoom_find)
        self.zoom_list = QTreeWidget()
        self.zoom_list.setHeaderLabels(["Momento", "Lo que dices", "Estado"])
        self.zoom_list.setRootIsDecorated(False)
        self.zoom_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.zoom_list.setColumnWidth(0, 60)
        self.zoom_list.setColumnWidth(1, 220)
        self.zoom_list.setMaximumHeight(170)
        self.zoom_list.itemDoubleClicked.connect(self._zoom_preview)
        v3.addWidget(self.zoom_list)
        zb = QHBoxLayout()
        self.btn_zoom_apply = QPushButton("✓ Aplicar")
        self.btn_zoom_apply.clicked.connect(lambda: self.apply_zooms(selected_only=True))
        self.btn_zoom_ignore = QPushButton("✗ Ignorar")
        self.btn_zoom_ignore.clicked.connect(self._zoom_ignore)
        self.btn_zoom_all = QPushButton("Aplicar todos los zooms")
        self.btn_zoom_all.clicked.connect(lambda: self.apply_zooms(selected_only=False))
        for b_ in (self.btn_zoom_apply, self.btn_zoom_ignore, self.btn_zoom_all):
            zb.addWidget(b_)
        v3.addLayout(zb)
        set_help(g3, "visuales")

        # --- 4. Audio inteligente ---
        g4 = QGroupBox("4 · Audio inteligente")
        v4 = QVBoxLayout(g4)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Voz"))
        self.voice_track = QComboBox()
        self.voice_track.currentIndexChanged.connect(self._refresh_audio)
        r1.addWidget(self.voice_track, 1)
        v4.addLayout(r1)
        self.fx_checks = {}
        grid = QGridLayout()
        for i, key in enumerate(audio_fx.FX_ORDER):
            chk = QCheckBox(audio_fx.VOICE_FX[key][0])
            chk.toggled.connect(lambda on, k=key: self._set_fx(k, on))
            self.fx_checks[key] = chk
            grid.addWidget(chk, i // 2, i % 2)
        v4.addLayout(grid)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Música"))
        self.music_track = QComboBox()
        self.music_track.currentIndexChanged.connect(self._refresh_audio)
        r2.addWidget(self.music_track, 1)
        v4.addLayout(r2)
        r3 = QHBoxLayout()
        self.duck = QCheckBox("Bajar la música cuando hablo")
        self.duck.toggled.connect(self._set_duck)
        self.duck_db = QSpinBox()
        self.duck_db.setRange(-30, -3)
        self.duck_db.setSuffix(" dB")
        self.duck_db.valueChanged.connect(lambda v: self._set_duck(self.duck.isChecked()))
        r3.addWidget(self.duck)
        r3.addWidget(self.duck_db)
        v4.addLayout(r3)
        self.btn_mix = QPushButton("🎚 Analizar y proponer mezcla…")
        self.btn_mix.setToolTip("Mezcla que cambia a lo largo del video: según lo que se dice (emotivo, acción…) y la "
                                "forma de la canción. Te enseña cada cambio con su motivo antes de aplicarlo.")
        self.btn_mix.clicked.connect(lambda: hasattr(self.window(), "open_mix") and self.window().open_mix())
        v4.addWidget(self.btn_mix)
        self.loud = QCheckBox("Volumen final para YouTube (-14 LUFS)")
        self.loud.setToolTip("Normaliza el volumen del video completo al nivel que usa YouTube.")
        self.loud.toggled.connect(lambda on: not self._audio_loading and
                                  self.ctrl.set_settings(loudnorm=on))
        v4.addWidget(self.loud)
        self.btn_beats = QPushButton("🥁 Llevar los cortes del B-roll al ritmo de la música")
        self.btn_beats.setToolTip("Detecta los golpes de la música y mueve cada corte de la pista de video "
                                  "elegida en B-roll al golpe más cercano (como mucho 0,3 s).")
        self.btn_beats.clicked.connect(self.snap_to_beats)
        v4.addWidget(self.btn_beats)
        self.btn_listen_fx = QPushButton("🎧 Escuchar 10 s con los efectos (desde el cabezal)")
        self.btn_listen_fx.clicked.connect(self.listen_with_fx)
        v4.addWidget(self.btn_listen_fx)
        set_help(g4, "audio_ia")
        self._audio_group = g4

        # --- 5. Modo Director ---
        g5 = QGroupBox("5 · 🎬 Modo Director")
        v5 = QVBoxLayout(g5)
        self.director_text = QPlainTextEdit()
        self.director_text.setFixedHeight(70)
        self.director_text.setPlaceholderText("Escribe aquí tu instrucción…")
        v5.addWidget(self.director_text)
        dr = QHBoxLayout()
        self.btn_interpret = QPushButton("◈ Interpretar")
        self.btn_interpret.clicked.connect(self.interpret)
        self.btn_markers = QPushButton("📍 Leer instrucciones de los marcadores")
        self.btn_markers.setToolTip("Los marcadores de la timeline cuyo texto sea una instrucción "
                                    "(«usa cinemáticas», «no modificar»…) se aplican hasta el marcador siguiente.")
        self.btn_markers.clicked.connect(self.interpret_markers)
        dr.addWidget(self.btn_interpret)
        dr.addWidget(self.btn_markers)
        v5.addLayout(dr)
        self.plan_tree = QTreeWidget()
        self.plan_tree.setHeaderLabels(["Plan"])
        self.plan_tree.setMinimumHeight(120)
        v5.addWidget(self.plan_tree)
        pr = QHBoxLayout()
        self.btn_plan_apply = QPushButton("✓ Aplicar plan")
        self.btn_plan_apply.setObjectName("primary")
        self.btn_plan_apply.clicked.connect(self.apply_plan)
        self.btn_plan_drop = QPushButton("✗ Descartar")
        self.btn_plan_drop.clicked.connect(lambda: (self.plan_tree.clear(), setattr(self, "plans", [])))
        pr.addWidget(self.btn_plan_drop)
        pr.addWidget(self.btn_plan_apply)
        v5.addLayout(pr)
        set_help(g5, "director")
        self.plans: list[dict] = []
        self._audio_loading = False
        self._fx_player = None

        self._groups = {"topics": g1, "broll": g2, "visual": g3, "audio": g4, "director": g5}
        # Limpio, como Resolve: la portada con las herramientas y cada una en su pestaña
        from .tabs import tabbed, untitle
        untitle(mapbox, g1, g2, g3, g4, g5)
        from .unused_scenes import UnusedScenes
        self.unused_scenes = UnusedScenes(ctrl)    # 🎬 debajo de las herramientas: las escenas que aún no usas
        self.tabs = tabbed([("Inicio", [self._mapbox, self.unused_scenes], True), ("Temas", [g1], True),
                            ("B-roll", [g2], True),
                            ("Zooms", [g3], True), ("Audio", [g4]), ("Director", [g5])])
        self._tab_of = {"topics": 1, "broll": 2, "visual": 3, "audio": 4, "director": 5}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(content)
        outer.addWidget(self.tabs, 1)

        self._load_settings()
        from .common import lazy_refresh
        self._lazy = lazy_refresh(self, self.refresh)      # oculto: no se rehace en cada edición
        ctrl.project_changed.connect(self._lazy)
        ctrl.project_replaced.connect(self._on_replaced)
        ctrl.media_changed.connect(self._lazy)
        self.refresh()

    # ------------------------------------------------------------ ajustes
    def _fmt(self) -> str:
        return self.ctrl.project.format

    def _load_settings(self):
        s = self.settings
        short = self._fmt() in ("short", "edit")   # tus Shorts cambian de plano cada ~2,4 s
        self._loaded_fmt = self._fmt()
        d_lo, d_hi = broll_selection.PACE_DEFAULT.get(self._fmt(), broll_selection.PACE_DEFAULT["youtube"])
        lo = float(s.value(f"broll/min_{self._fmt()}", d_lo))
        hi = float(s.value(f"broll/max_{self._fmt()}", d_hi))
        if (lo, hi) in ((2.0, 3.0), (3.0, 6.0)):      # los valores por defecto de antes (más cortes): los nuevos
            lo, hi = d_lo, d_hi
        self.min_len.setValue(lo)
        self.max_len.setValue(hi)
        self.continuous.setChecked(str(s.value("broll/continuo", "true")).lower() == "true")
        self.clip_vol.setValue(int(s.value("broll/volumen", 0)))
        self.avoid.setChecked(str(s.value("broll/no_repetir", "true")).lower() == "true")

    def _broll_settings(self) -> broll_selection.BrollSettings:
        s = self.settings
        lo, hi = self.min_len.value(), max(self.max_len.value(), self.min_len.value() + 0.5)
        s.setValue(f"broll/min_{self._fmt()}", lo)
        s.setValue(f"broll/max_{self._fmt()}", hi)
        s.setValue("broll/continuo", self.continuous.isChecked())
        s.setValue("broll/volumen", self.clip_vol.value())
        s.setValue("broll/no_repetir", self.avoid.isChecked())
        return broll_selection.BrollSettings(min_len=lo, max_len=hi, avoid_repeats=self.avoid.isChecked(),
                                             continuous=self.continuous.isChecked())

    # ------------------------------------------------------------ refresco
    def narration(self) -> str | None:
        p = self.ctrl.project
        mid = self._preferred_media()
        if mid in p.transcripts:
            return mid
        return next((m for m in p.transcripts if m in p.media), None)

    def _on_replaced(self):
        self.slots = []
        self.slot_tree.clear()
        self.refresh()

    def _refresh_understanding(self):
        u = self.ctrl.understanding
        if u:
            found = [e.name for e in u.get("entities", []) if u.get("index", {}).get(e.name)]
            self.understand_label.setText(f"✓ Reconoce {len(found)} nombres en tus clips"
                                          + (": " + ", ".join(found[:6]) + ("…" if len(found) > 6 else "") if found else ""))
        elif any(v is not None for v in self.ctrl.clip_shots.values()):
            self.understand_label.setText("✓ Biblioteca analizada a fondo.")
        else:
            self.understand_label.setText("Sin analizar a fondo: el B-roll se elige solo por lo que se ve en "
                                          "unos pocos fotogramas de cada clip.")

    def _card(self, key: str):
        """Clic en una tarjeta del mapa: abre la herramienta o baja a su sección."""
        if key in self._groups:
            g = self._groups[key]
            self.tabs.setCurrentIndex(self._tab_of[key])
            g.setStyleSheet("QGroupBox { border: 1px solid #e8742f; }")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1200, lambda: g.setStyleSheet(""))
            if key == "topics" and self.btn_topics.isEnabled() and not any(
                    m.kind == "topic" for m in self.ctrl.project.markers):
                self.detect_topics()
            return
        self.action_requested.emit(key)

    def _refresh_cards(self):
        """La línea de estado de cada tarjeta: lo que la IA ya hizo o encontró."""
        p = self.ctrl.project
        mid = self.narration()
        n_words = len(p.transcripts.get(mid, {}).get("words", [])) if mid else 0
        pend = sum(1 for s in p.suggestions if s.status == "pending" and s.kind in
                   ("silence", "noise", "filler", "repeat", "retake"))
        topics = [m for m in p.markers if m.kind == "topic"]
        vtr = {t.id for t in p.tracks if t.kind == TRACK_VIDEO}
        ai_broll = sum(1 for c in p.clips.values() if c.origin == ORIGIN_AI and c.track_id in vtr)
        vis = sum(1 for s in p.suggestions if s.kind in ("zoom", "compare") and s.status == "pending")
        u = self.ctrl.understanding or {}
        names = [e.name for e in u.get("entities", []) if u.get("index", {}).get(e.name)]
        status = {
            "auto": "Lista: elige tu narración y pulsa." if p.media else "Importa tu narración y tus clips.",
            "understand": (f"✓ Reconoce {len(names)}: " + ", ".join(names[:3]) + ("…" if len(names) > 3 else ""))
            if names else ("✓ Analizada a fondo." if any(v is not None for v in self.ctrl.clip_shots.values())
                           else "Sin analizar a fondo todavía."),
            "moments": f"⭐ {len(p.favorites)} favoritos guardados." if p.favorites else "Busca por texto o por imagen.",
            "voice": (f"✓ {n_words} palabras" + (f" · {pend} cortes sugeridos" if pend else "")) if n_words
            else "Sin transcribir todavía.",
            "topics": f"✓ {len(topics)} temas: " + ", ".join(dict.fromkeys(m.label.title() for m in topics[:3]))
            if topics else ("Pulsa para detectarlos." if n_words else "Primero transcribe tu voz."),
            "broll": f"✓ {ai_broll} planos colocados por la IA." if ai_broll else "Sin B-roll de la IA todavía.",
            "visual": f"{vis} sugerencias pendientes." if vis else "Sin sugerencias pendientes.",
        }
        for key, (btn, lbl) in self.cards.items():
            what = dict((k, w) for k, _t, w in AI_CARDS)[key]
            lbl.setText(status.get(key, what))
            btn.setToolTip(what + ("" if status.get(key, what) == what else chr(10) + status[key]))

    def refresh(self):
        self._refresh_understanding()
        self._refresh_cards()
        p = self.ctrl.project
        if getattr(self, "_loaded_fmt", None) != p.format:
            self._load_settings()
        # Pistas de video para el B-roll
        current = self.track.currentData()
        self.track.blockSignals(True)
        self.track.clear()
        vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
        for t in reversed(vtracks):  # V1 primero
            self.track.addItem(t.name + (" 🔒" if t.locked else ""), t.id)
        idx = self.track.findData(current)
        self.track.setCurrentIndex(idx if idx >= 0 else 0)
        self.track.blockSignals(False)
        # Temas
        self.topic_list.clear()
        for m in sorted((m for m in p.markers if m.kind == "topic"), key=lambda m: m.time):
            it = QTreeWidgetItem([f"{fmt_time(m.time, False)} – {fmt_time(m.end or m.time, False)}",
                                  ("✎ " if m.origin != ORIGIN_AI else "") + m.label])
            it.setIcon(0, _dot(m.color))
            it.setData(0, Qt.UserRole, m.id)
            self.topic_list.addTopLevelItem(it)
        busy = self.job is not None
        has_narr = self.narration() is not None
        self.btn_topics.setEnabled(has_narr and not busy)
        self.btn_propose.setEnabled(has_narr and not busy)
        if not busy and not self.status.text().startswith("✓"):
            if not has_narr:
                self.status.setText("Primero transcribe tu narración (pestaña «Limpieza»).")
            elif not self.ctrl.clip_vecs:
                self.status.setText("Para el B-roll, la IA tiene que analizar tus clips: botón ◈ "
                                    "de la biblioteca.")
            elif not self.status.text().startswith("✓"):
                self.status.setText("")
        self._mark_slots()
        self._refresh_zoom_list()
        self._refresh_audio_tracks()

    # ------------------------------------------------------------- tareas
    def _start(self, fn, on_done, label):
        self.job = BackgroundJob(fn, self)
        self.job.progress.connect(lambda f, t: (self.progress.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(on_done)
        self.job.failed.connect(lambda msg: (self.status.setText(f"✗ {msg}"),
                                             msg != "Cancelado." and QMessageBox.warning(self, "IA", msg)))
        self.job.finished.connect(self._finished)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText(label)
        self.btn_topics.setEnabled(False)
        self.btn_propose.setEnabled(False)
        self.job.start()

    def _finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.progress.setVisible(False)
        self.refresh()

    def shutdown(self):
        job = self.job
        if job is not None and job.isRunning():
            job.cancel()
            if not job.wait(8000):
                job.terminate()
                job.wait(2000)

    # -------------------------------------------------------------- temas
    def detect_topics(self):
        mid = self.narration()
        if not mid or self.job:
            return
        if any(m.kind == "topic" and m.origin != ORIGIN_AI for m in self.ctrl.project.markers):
            if QMessageBox.question(self, "Detectar temas",
                                    "Ya hay temas que retocaste a mano. Si detectas de nuevo se "
                                    "sustituirán todos (puedes deshacerlo con Ctrl+Z).\n\n¿Continuar?") \
                    != QMessageBox.Yes:
                return
        words = self.ctrl.project.transcripts[mid]["words"]

        def work(progress, cancelled):
            return topic_detection.detect_topics(words, progress=progress, cancelled=cancelled)

        def done(segments):
            n = self.ctrl.set_topics(mid, segments)
            if n:
                self.status.setText(f"✓ {n} temas. Mira las bandas de color arriba de la timeline.")

        self._start(work, done, "◎ Detectando temas…")

    def _topic_double_click(self, item, _col):
        m = next((m for m in self.ctrl.project.markers if m.id == item.data(0, Qt.UserRole)), None)
        if m:
            self.engine.user_seek(m.time)

    def _topic_menu(self, pos):
        item = self.topic_list.itemAt(pos)
        m = next((m for m in self.ctrl.project.markers if item and m.id == item.data(0, Qt.UserRole)), None)
        if m:
            self.timeline._marker_menu(m, self.topic_list.viewport().mapToGlobal(pos))
        else:
            from .help import add_help_action
            menu = QMenu(self)
            add_help_action(menu, "temas", self.window())
            help_ui.exec_menu(menu, self.topic_list.viewport().mapToGlobal(pos))

    def show_audio_section(self):
        self.tabs.setCurrentIndex(self._tab_of["audio"])

    # ------------------------------------------------------- Modo Director
    def _topic_under_playhead(self):
        t = self.engine.time
        for m in self.ctrl.project.markers:
            if m.kind == "topic" and m.end is not None and m.time <= t < m.end:
                return (m.time, m.end)
        return None

    def interpret(self):
        from ..ai.director import parse
        text = self.director_text.toPlainText().strip()
        if not text:
            return
        plan = parse(text, self.engine.time, self._topic_under_playhead(), self.ctrl.project.duration())
        self.plans = [plan]
        self._show_plans()

    def interpret_markers(self):
        from ..ai.director import parse
        p = self.ctrl.project
        marks = sorted((m for m in p.markers if m.kind == "marker" and m.label), key=lambda m: m.time)
        plans = []
        for i, m in enumerate(marks):
            end = marks[i + 1].time if i + 1 < len(marks) else min(p.duration(), m.time + 15.0)
            plan = parse(m.label, m.time, (m.time, max(end, m.time + 1.0)), p.duration())
            if plan["steps"] and not m.label.startswith("🔒"):
                plan["source"] = f"Marcador «{m.label}»"
                plan["marker_id"] = m.id
                plans.append(plan)
        self.plans = plans
        self._show_plans()
        if not plans:
            self.status.setText("Ningún marcador contiene una instrucción que entienda.")

    def _show_plans(self):
        self.plan_tree.clear()
        for plan in self.plans:
            a, b = plan["range"]
            top = QTreeWidgetItem([f"{fmt_time(a, False)} – {fmt_time(b, False)}"
                                   + (f"  ({plan['source']})" if plan.get("source") else "")])
            f = QFont(self.font())
            f.setBold(True)
            top.setFont(0, f)
            self.plan_tree.addTopLevelItem(top)
            for step in plan["steps"]:
                top.addChild(QTreeWidgetItem([step["label"]]))
            for u in plan.get("unknown", []):
                it = QTreeWidgetItem(["❓ " + u])
                it.setForeground(0, QColor("#e3b341"))
                top.addChild(it)
            top.setExpanded(True)
        self.btn_plan_apply.setEnabled(any(p["steps"] for p in self.plans))

    def _director_zooms(self, plans, words):
        """Zooms «cuando diga X»: sobre el clip que se ve en ese momento (ya con el B-roll colocado)."""
        from ..ai import tracking
        from ..ai.transform_helpers import punch_keyframes
        p = self.ctrl.project
        out = []
        for plan in plans:
            a, b = plan["range"]
            for step in plan["steps"]:
                if step["kind"] != "zoom_word":
                    continue
                target = [normalize(x) for x in step["word"].split()]
                for i in range(len(words)):
                    seq = [re.sub(r"[^a-z0-9ñ]", "", normalize(w[2])) for w in words[i:i + len(target)]]
                    if seq != target or not (a <= words[i][0] <= b):
                        continue
                    t = words[i][0]
                    c = self._video_clip_at(t)
                    m = p.media_of(c) if c else None
                    if c is None or m is None:
                        continue
                    src = self.ctrl.clip_source_time(c.id, t)
                    cin = 0.0 if m.kind == KIND_IMAGE else c.source_in
                    x, y = 0.5, 0.5
                    if step["face"] and m.kind != KIND_IMAGE:
                        try:
                            faces = tracking.detect_faces(tracking.grab_frame(m.path, src, 640, m.width, m.height))
                        except Exception:  # noqa: BLE001
                            faces = []
                        if faces:
                            fx, fy, fw, fh, _c = faces[0]
                            x, y = fx + fw / 2, fy + fh / 2
                    out.append((c.id, punch_keyframes(src, cin, cin + c.duration, step["z"], x, y)))
        return out

    def apply_plan(self):
        """Ejecuta el plan: primero lo pesado en segundo plano (buscar clips, caras), luego los cambios
        en la timeline como UN solo paso de deshacer."""
        from ..ai import tracking
        from ..ai.transform_helpers import punch_keyframes
        from ..core.subtitles import timeline_words
        if not self.plans or self.job:
            return
        p = self.ctrl.project
        mid = self.narration()
        words = timeline_words(p, mid) if mid else []
        clips = self._clip_infos()
        track_id = self.track.currentData()
        used: dict[str, int] = {}
        for c in p.clips.values():
            if p.track(c.track_id).kind == TRACK_VIDEO:
                used[c.media_id] = used.get(c.media_id, 0) + 1
        plans = self.plans

        def work(progress, cancelled):
            out = {"broll": [], "zooms": []}
            for plan in plans:
                a, b = plan["range"]
                for step in plan["steps"]:
                    if step["kind"] != "broll" or not clips:
                        continue
                    st = broll_selection.BrollSettings(min_len=step["pace"][0], max_len=step["pace"][1],
                                                       prefer=step["prefer"] or list(PREFERENCES[0][1]))
                    w_in = [w for w in words if a <= w[0] < b]
                    if w_in:
                        slots = broll_selection.make_slots(w_in, st, [])
                        slots[0]["start"] = a
                        slots[-1]["end"] = b
                        slots = broll_selection.split_long(slots, st.max_len, st.min_len)
                    else:  # sin narración en esa parte: huecos regulares
                        n = max(1, int((b - a) / ((st.min_len + st.max_len) / 2)))
                        slots = [{"start": a + (b - a) * k / n, "end": a + (b - a) * (k + 1) / n,
                                  "text": step["query"], "topic": ""} for k in range(n)]
                    broll_selection.propose(slots, clips, st, used, progress, cancelled, query=step["query"])
                    out["broll"] += [s for s in slots if s.get("candidates")]
            return out

        def done(res):
            from ..ai.transform_helpers import merge_window
            stack = self.ctrl.undo_stack
            stack.beginMacro("IA · Modo Director")
            try:
                for plan in plans:
                    a, b = plan["range"]
                    for step in plan["steps"]:
                        if step["kind"] == "lock":
                            self.ctrl.lock_range(a, b, marker_id=plan.get("marker_id"))
                            res["locked"] = res.get("locked", 0) + 1
                        elif step["kind"] == "text":
                            self.ctrl.add_text(a, min(4.0, max(1.0, b - a)), step["content"], origin=ORIGIN_AI)
                items = []
                for s in res["broll"]:
                    c = s["candidates"][0]
                    m = self.ctrl.project.media.get(c["media_id"])
                    dur = s["end"] - s["start"]
                    if m and m.kind != KIND_IMAGE and m.duration:
                        dur = min(dur, m.duration - c["source_in"])
                    items.append({"media_id": c["media_id"], "start": s["start"], "duration": dur,
                                  "source_in": c["source_in"], "note": f"Modo Director: {c['reason']}"})
                if items:
                    self.ctrl.insert_ranges(items, track_id, "IA · B-roll (Director)", origin=ORIGIN_AI,
                                            volume=self.clip_vol.value() / 100)
                for cid, kf in self._director_zooms(plans, words):
                    c = self.ctrl.project.clips.get(cid)
                    if c is not None:
                        self.ctrl.set_zoom_keyframes(cid, merge_window(c.zoom_kf, kf), "IA · Zoom (Director)")
                        res["zooms"].append(cid)
            finally:
                stack.endMacro()
            done_bits = []
            if res["broll"]:
                done_bits.append(f"{len(res['broll'])} clips")
            if res["zooms"]:
                done_bits.append(f"{len(res['zooms'])} zooms")
            if res.get("locked"):
                done_bits.append(f"{res['locked']} parte(s) protegida(s)")
            self.status.setText("✓ Plan aplicado: " + (", ".join(done_bits) or "sin cambios") +
                                ". Ctrl+Z lo deshace entero.")
            self.plans = []
            self.plan_tree.clear()

        self._start(work, done, "🎬 Aplicando el plan del Director…")

    # ------------------------------------------------------- audio inteligente
    def _refresh_audio_tracks(self):
        p = self.ctrl.project
        self._audio_loading = True
        try:
            for combo, prefer_music in ((self.voice_track, False), (self.music_track, True)):
                current = combo.currentData()
                combo.clear()
                for t in p.tracks:
                    if t.kind == "audio":
                        combo.addItem(t.name, t.id)
                idx = combo.findData(current)
                if idx < 0:  # por defecto: la de música para la música, la primera para la voz
                    idx = next((i for i in range(combo.count())
                                if (p.track(combo.itemData(i)).duck_db is not None) == prefer_music), 0)
                combo.setCurrentIndex(idx)
            self.loud.setChecked(p.loudnorm)
        finally:
            self._audio_loading = False
        self._refresh_audio()

    def _refresh_audio(self):
        if getattr(self, "_audio_loading", False) and self.sender() is not None:
            return
        p = self.ctrl.project
        was = self._audio_loading
        self._audio_loading = True
        try:
            vt = p.track(self.voice_track.currentData() or "")
            for key, chk in self.fx_checks.items():
                chk.setChecked(bool(vt and vt.fx.get(key)))
                chk.setEnabled(vt is not None)
            mt = p.track(self.music_track.currentData() or "")
            self.duck.setChecked(bool(mt and mt.duck_db is not None))
            self.duck_db.setValue(int(mt.duck_db) if mt and mt.duck_db is not None else -12)
            self.duck.setEnabled(mt is not None)
        finally:
            self._audio_loading = was

    def _set_fx(self, key: str, on: bool):
        tid = self.voice_track.currentData()
        tr = self.ctrl.project.track(tid) if tid else None
        if self._audio_loading or tr is None:
            return
        self.ctrl.set_track_props(tid, f"Efecto de voz: {audio_fx.VOICE_FX[key][0]}", fx=dict(tr.fx, **{key: on}))

    def _set_duck(self, on: bool):
        tid = self.music_track.currentData()
        if self._audio_loading or not tid:
            return
        self.ctrl.set_track_props(tid, "Bajar música al hablar", duck_db=float(self.duck_db.value()) if on else None)

    def snap_to_beats(self):
        from ..ai import music_analysis, rhythm
        p = self.ctrl.project
        mtid = self.music_track.currentData()
        vtid = self.track.currentData()
        if not mtid or not vtid or self.job:
            return
        music = {c.media_id: p.media[c.media_id].path for c in p.clips_on(mtid) if c.media_id in p.media}
        if not music:
            self.ctrl.message.emit("No hay música en la pista elegida.")
            return
        todo = {mid: path for mid, path in music.items() if mid not in self.ctrl.rhythm}

        def work(progress, cancelled):
            out = {}
            for i, (mid, path) in enumerate(todo.items()):
                progress(i / max(1, len(todo)), "🥁 Escuchando el ritmo de la música…")
                out[mid] = rhythm.analyze(path)
            return out

        def done(res):
            for mid, r in res.items():
                self.ctrl._on_rhythm(mid, r)
            res = {mid: self.ctrl.rhythm[mid] for mid in music if mid in self.ctrl.rhythm}
            rt = self.ctrl.rhythm_on_timeline([c.id for c in p.clips_on(mtid)])
            clips = p.clips_on(vtid)
            cuts = [a.end for a, b in zip(clips, clips[1:]) if abs(b.start - a.end) < 0.01]
            targets = music_analysis.snap_points(cuts, rt["beats"], prefer=rt["downbeats"] + rt["strong"] +
                                                 rt["drops"])
            n = self.ctrl.snap_cuts(vtid, targets) if targets else None
            tempo = ", ".join(f"{r['tempo']:g} BPM" for r in res.values())
            self.status.setText(f"✓ {n} cortes llevados al ritmo" + (f" (tempo {tempo})" if tempo else "") + "."
                                if n else "No había cortes cerca de los golpes de la música.")
            self.timeline.update()

        self._start(work, done, "🥁 Analizando la música…")

    def listen_with_fx(self):
        """Renderiza 10 s desde el cabezal con todos los efectos y los reproduce."""
        import os
        from ..core.paths import temp_dir as _temp_dir

        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        from ..core import media as media_tools
        from ..core.project_tools import slice_project
        from ..export.ffmpeg_export import ExportOptions, build_command
        if self.job:
            return
        self.engine.pause()
        t0 = self.engine.time
        part = slice_project(self.ctrl.project, t0, t0 + 10.0)
        if part.duration() <= 0:
            self.ctrl.message.emit("No hay nada en los próximos 10 segundos.")
            return
        out = os.path.join(str(_temp_dir()), "editoria_escucha.mp4")

        def work(progress, _cancelled):
            import subprocess
            progress(0.0, "🎧 Preparando el audio con efectos…")
            opts = ExportOptions(path=out, width=320, height=180, fps=15, encoder="cpu", bitrate_mbps=1)
            args, _total = build_command(part, opts, media_tools.ffmpeg(),
                                         os.path.join(str(_temp_dir()), "editoria_escucha_filtro.txt"))
            r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                               creationflags=media_tools.NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
            return out

        def done(path):
            if self._fx_player is None:
                self._fx_player = QMediaPlayer(self)
                self._fx_out = QAudioOutput(self)
                self._fx_player.setAudioOutput(self._fx_out)
            self._fx_player.setSource(QUrl())
            self._fx_player.setSource(QUrl.fromLocalFile(path))
            self._fx_player.play()
            self.status.setText("🎧 Reproduciendo 10 s con los efectos de audio…")

        self._start(work, done, "🎧 Preparando…")

    # ------------------------------------------------------- zoom por contexto
    def _zoom_suggestions(self):
        mid = self.narration()
        return [x for x in self.ctrl.project.suggestions if x.kind in ("zoom", "compare") and x.media_id == mid]

    def _refresh_zoom_list(self):
        selected = {it.data(0, Qt.UserRole) for it in self.zoom_list.selectedItems()}
        self.zoom_list.clear()
        mid = self.narration()
        for sg in self._zoom_suggestions():
            t = mapping.map_time(self.ctrl.project, mid, sg.start) if mid else None
            state = {"pending": "Pendiente", "applied": "✓ Aplicado", "rejected": "Ignorado"}[sg.status]
            icon = "🔍" if sg.kind == "zoom" else "⧉"
            it = QTreeWidgetItem([fmt_time(t, False) if t is not None else "—",
                                  icon + " " + sg.label.replace("Zoom: ", "").replace("Comparación: ", ""), state])
            it.setData(0, Qt.UserRole, sg.id)
            it.setToolTip(1, sg.label + "\n" + sg.detail)
            if sg.status != "pending":
                it.setForeground(1, QColor("#6b7280"))
            self.zoom_list.addTopLevelItem(it)
            it.setSelected(sg.id in selected)
        has = self.narration() is not None and self.job is None
        self.btn_zoom_find.setEnabled(has)

    def find_zoom_moments(self):
        from ..ai.visual_suggestions import find_compare_moments, find_zoom_moments
        mid = self.narration()
        if not mid:
            return
        words = self.ctrl.project.transcripts[mid]["words"]
        items = [{"kind": "zoom", "start": d["start"], "end": d["end"], "label": d["label"],
                  "detail": d["detail"], "data": {"face": d["face"], "strength": d["strength"]}}
                 for d in find_zoom_moments(words)]
        comps = [dict(d, kind="compare") for d in find_compare_moments(words)]
        self.ctrl.set_suggestions(mid, items + comps, {"zoom", "compare"}, {"zoom": False, "compare": False})
        self.status.setText(f"✓ {len(items)} momentos para zoom y {len(comps)} para comparar. "
                            "Revísalos en la lista (doble clic = ver).")

    def _zoom_preview(self, item, _col):
        mid = self.narration()
        sg = next((x for x in self.ctrl.project.suggestions if x.id == item.data(0, Qt.UserRole)), None)
        t = mapping.map_time(self.ctrl.project, mid, sg.start) if (sg and mid) else None
        if t is not None:
            self.engine.play_ranges([(t - 1.0, t + 3.5)])

    def _open_compare(self, sg):
        from .compare_dialog import CompareDialog
        mid = self.narration()
        t = mapping.map_time(self.ctrl.project, mid, sg.start) if mid else None
        if t is None:
            return
        if CompareDialog(self.ctrl, t, self, origin=ORIGIN_AI).exec():
            self.ctrl.mark_suggestions_applied([sg.id])

    def _zoom_ignore(self):
        ids = [it.data(0, Qt.UserRole) for it in self.zoom_list.selectedItems()]
        if ids:
            self.ctrl.reject_suggestions(ids)

    def _video_clip_at(self, t: float):
        """Clip de video/imagen visible (pista más alta, sin bloquear) en el momento t."""
        p = self.ctrl.project
        for tr in p.tracks:
            if tr.kind != TRACK_VIDEO or tr.hidden:
                continue
            c = p.clip_at(tr.id, t)
            if c is not None and c.enabled:
                return c if not (c.locked or tr.locked) else None
        return None

    def apply_zooms(self, selected_only: bool):
        from ..ai import tracking
        from ..ai.transform_helpers import punch_keyframes
        mid = self.narration()
        if not mid or self.job:
            return
        ids = {it.data(0, Qt.UserRole) for it in self.zoom_list.selectedItems()} if selected_only else None
        sugs = [x for x in self._zoom_suggestions() if x.status == "pending" and (ids is None or x.id in ids)]
        compares = [x for x in sugs if x.kind == "compare"]
        sugs = [x for x in sugs if x.kind == "zoom"]
        if compares and selected_only:
            self._open_compare(compares[0])
            return
        p = self.ctrl.project
        plan = []  # (sugerencia, clip, segundo del archivo, ruta, ancho, alto, ¿imagen?)
        for sg in sugs:
            t = mapping.map_time(p, mid, sg.start)
            c = self._video_clip_at(t) if t is not None else None
            m = p.media_of(c) if c else None
            if c is None or m is None:
                continue
            plan.append((sg.id, c.id, self.ctrl.clip_source_time(c.id, t), m.path, m.width, m.height,
                         m.kind == KIND_IMAGE, c.source_in if m.kind != KIND_IMAGE else 0.0,
                         (c.source_in if m.kind != KIND_IMAGE else 0.0) + c.duration))
        if not plan:
            self.ctrl.message.emit("No hay video en esos momentos (o está bloqueado): no se puede hacer zoom.")
            return

        def work(progress, cancelled):
            out = []
            for i, (sid, cid, src, path, w, h, is_img, cin, cout) in enumerate(plan):
                progress(i / len(plan), f"🔍 Preparando zoom {i + 1}/{len(plan)}…")
                z, x, y = 1.5, 0.5, 0.5
                try:
                    frame = None if is_img else tracking.grab_frame(path, src, 640, w, h)
                    faces = tracking.detect_faces(frame) if frame is not None else []
                except Exception:  # noqa: BLE001 - sin detector de caras: zoom al centro
                    faces = []
                if faces:
                    fx, fy, fw, fh, _c = faces[0]
                    x, y = fx + fw / 2, fy + fh / 2
                    z = max(1.6, min(3.0, 0.4 / max(fh, 1e-3)))
                out.append((sid, cid, punch_keyframes(src, cin, cout, z, x, y)))
            return out

        def done(items):
            n = self.ctrl.apply_zoom_suggestions(items)
            if n:
                self.status.setText(f"✓ {n} zooms aplicados (rombos amarillos en los clips). Ctrl+Z para deshacer.")

        self._start(work, done, "🔍 Preparando zooms…")

    # ------------------------------------------------------------- B-roll
    def _clip_infos(self) -> list[broll_selection.ClipInfo]:
        p = self.ctrl.project
        out = []
        for mid, (times, vecs) in self.ctrl.clip_vecs.items():
            m = p.media.get(mid)
            if m is None or m.kind == KIND_AUDIO or mid in self.ctrl.missing:
                continue
            meta = clip_analysis.metadata_text(m.name, m.category, m.ai_type, m.ai_tags, m.tags)
            # ai_type = lo que adivina la IA (o la categoría si no adivinó); category/user_tags = lo que pusiste tú
            out.append(broll_selection.ClipInfo(mid, m.name, "image" if m.kind == KIND_IMAGE else "video",
                                                m.duration, m.ai_type or m.category, list(m.ai_tags) + m.tags,
                                                times, vecs, meta, m.path, category=m.category or "",
                                                user_tags=list(m.tags)))
        return out

    def propose(self, rng: tuple[float, float] | None = None, apply: bool = False):
        """Propone B-roll para la narración (o solo para el tramo rng). apply=True: lo coloca ya,
        sustituyendo solo el B-roll de la IA de ese tramo (lo tuyo no se toca)."""
        mid = self.narration()
        if not mid:
            self.ctrl.message.emit("Primero transcribe tu narración (pestaña «Limpieza»).")
            return
        if self.job:
            return
        clips = self._clip_infos()
        if not clips:
            QMessageBox.information(self, "B-roll", "Primero la IA tiene que analizar tus clips: "
                                                     "botón ◈ de la biblioteca.")
            return
        p = self.ctrl.project
        if not mapping.clips_of_media(p, mid):
            QMessageBox.information(self, "B-roll", "La narración tiene que estar en la timeline.")
            return
        st = self._broll_settings()
        words = subtitles.timeline_words(p, mid)
        if rng is not None:
            words = [w for w in words if rng[0] - 0.05 <= w[0] < rng[1]]
            if not words:
                self.ctrl.message.emit("En esa parte no hay narración: no sé qué B-roll poner.")
                return
        topics = [(m.time, m.end or m.time, m.label) for m in p.markers if m.kind == "topic"]
        used: dict[str, int] = {}
        for c in p.clips.values():
            if p.track(c.track_id).kind == TRACK_VIDEO:
                used[c.media_id] = used.get(c.media_id, 0) + 1

        und = self.understanding_for_work()

        def work(progress, cancelled):
            u = und() if callable(und) else und
            slots = broll_selection.make_slots(words, st, topics)
            return broll_selection.propose_understood(slots, clips, st, used, u, progress, cancelled)

        if apply and rng is not None:
            def done(slots):
                self._show_slots(slots)
                self._apply_range(slots, rng)
            self._start(work, done, "🎬 Rehaciendo el B-roll de esa parte…")
            return
        self._start(work, self._show_slots, "🎬 Buscando B-roll para cada frase…")

    def _apply_range(self, slots: list[dict], rng: tuple[float, float]):
        from ..ai.first_version import broll_items
        tid = self.track.currentData()
        p = self.ctrl.project
        if not tid:
            return
        a, b = rng
        old = [c.id for c in p.clips_on(tid)
               if c.origin == ORIGIN_AI and not c.locked and c.start >= a - 0.05 and c.end <= b + 0.05]
        items = broll_items(slots, p.media, start_at_zero=False)
        self.ctrl.undo_stack.beginMacro("IA · Rehacer el B-roll de una parte")
        try:
            if old:
                self.ctrl.delete_clips(self.ctrl.linked_ids(old))
            created = self.ctrl.insert_ranges(items, tid, "IA · B-roll", origin=ORIGIN_AI, only_gaps=True,
                                              volume=self.clip_vol.value() / 100)
        finally:
            self.ctrl.undo_stack.endMacro()
        n = len(created) if isinstance(created, list) else 0
        self.status.setText(f"✓ B-roll rehecho en esa parte: {n} planos (lo que pusiste tú no se tocó). Ctrl+Z para deshacer.")

    def understanding_for_work(self):
        """Lo que la IA entendió de la biblioteca. Si se analizó a fondo en otra sesión, se recalcula
        rápido (en segundo plano) a partir de la caché."""
        if self.ctrl.understanding is not None:
            return self.ctrl.understanding
        if not any(v is not None for v in self.ctrl.clip_shots.values()):
            return None
        from .understand_dialog import glossary_text, snapshot, understand
        snap, gloss, ctrl = snapshot(self.ctrl), glossary_text(), self.ctrl

        def compute():
            res = understand(snap, gloss, lambda *_a: None, lambda: False, None, deep=False)
            ctrl.understanding = res
            return res
        return compute

    def _thumb(self, mid: str) -> QIcon:
        if mid not in self._thumbs:
            path = self.ctrl.thumbs.get(mid)
            pix = QPixmap(path) if path else QPixmap()
            self._thumbs[mid] = QIcon(pix.scaled(48, 27, Qt.KeepAspectRatio, Qt.SmoothTransformation)) \
                if not pix.isNull() else QIcon()
        return self._thumbs[mid]

    def _show_slots(self, slots):
        self.slots = slots
        self.slot_tree.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        for i, s in enumerate(slots):
            text = s["text"] if len(s["text"]) < 60 else s["text"][:57] + "…"
            top = QTreeWidgetItem([f"{fmt_time(s['start'], False)}  «{text}»", s["topic"].lower()])
            top.setFont(0, bold)
            top.setData(0, Qt.UserRole, ("slot", i, -1))
            top.setToolTip(0, s["text"])
            self.slot_tree.addTopLevelItem(top)
            for k, c in enumerate(s.get("candidates", [])):
                m = self.ctrl.project.media.get(c["media_id"])
                stars = "★" * (3 - k) + "☆" * k
                it = QTreeWidgetItem([f"{stars}  {m.name if m else '?'}", c["reason"]])
                it.setIcon(0, self._thumb(c["media_id"]))
                it.setData(0, Qt.UserRole, ("cand", i, k))
                it.setToolTip(0, f"Desde {fmt_time(c['source_in'])} del clip, {c['duration']:.1f} s")
                it.setToolTip(1, c["reason"])
                top.addChild(it)
            top.setExpanded(i < 3)
        n = sum(1 for s in slots if s.get("candidates"))
        self.status.setText(f"✓ Propuesta: {n} momentos. Elige un clip para cada uno o pulsa "
                            "«Rellenar huecos con lo mejor».")
        self._mark_slots()

    def _mark_slots(self):
        """Marca con ✓ los momentos que ya tienen clip en la pista elegida."""
        tid = self.track.currentData()
        if not tid or not self.slots:
            return
        clips = self.ctrl.project.clips_on(tid)
        for i in range(self.slot_tree.topLevelItemCount()):
            it = self.slot_tree.topLevelItem(i)
            s = self.slots[i]
            mid_t = (s["start"] + s["end"]) / 2
            filled = any(c.start <= mid_t < c.end for c in clips)
            it.setForeground(0, QColor("#57ab5a") if filled else QColor("#e6e8ec"))
            text = it.text(0)
            if filled and not text.startswith("✓"):
                it.setText(0, "✓ " + text)
            elif not filled and text.startswith("✓ "):
                it.setText(0, text[2:])

    def _slot_selected(self):
        it = self.slot_tree.currentItem()
        if not it:
            return
        kind, i, _k = it.data(0, Qt.UserRole)
        s = self.slots[i]
        if not self.engine.playing:
            self.engine.user_seek(s["start"])

    def _slot_double_click(self, item, _col):
        kind, i, k = item.data(0, Qt.UserRole)
        if kind == "slot":
            s = self.slots[i]
            self.engine.play_ranges([(s["start"], s["end"])])
        else:
            self._insert(i, k)

    def insert_selected(self):
        it = self.slot_tree.currentItem()
        if not it:
            return
        kind, i, k = it.data(0, Qt.UserRole)
        self._insert(i, max(0, k))

    def _insert(self, i: int, k: int):
        s = self.slots[i]
        if not s.get("candidates"):
            return
        c = s["candidates"][k]
        item = {"media_id": c["media_id"], "start": s["start"], "duration": s["end"] - s["start"],
                "source_in": c["source_in"], "note": f"B-roll IA: {c['reason']}"}
        m = self.ctrl.project.media.get(c["media_id"])
        if m and m.kind != KIND_IMAGE and m.duration:
            item["duration"] = min(item["duration"], m.duration - c["source_in"])
        self.ctrl.insert_ranges([item], self.track.currentData(), "IA · Insertar B-roll",
                                origin=ORIGIN_AI, volume=self.clip_vol.value() / 100)

    def auto_fill(self):
        if not self.slots:
            self.ctrl.message.emit("Primero pulsa «Proponer B-roll».")
            return
        items = []
        for s in self.slots:
            if not s.get("candidates"):
                continue
            c = s["candidates"][0]
            m = self.ctrl.project.media.get(c["media_id"])
            dur = s["end"] - s["start"]
            if m and m.kind != KIND_IMAGE and m.duration:
                dur = min(dur, m.duration - c["source_in"])
            items.append({"media_id": c["media_id"], "start": s["start"], "duration": dur,
                          "source_in": c["source_in"], "note": f"B-roll IA: {c['reason']}"})
        r = QMessageBox.question(self, "Rellenar con B-roll",
                                 f"La IA colocará hasta {len(items)} clips en los huecos LIBRES de la pista "
                                 f"«{self.track.currentText()}».\nNo tapará nada de lo que ya colocaste.\n\n"
                                 "Podrás deshacerlo con Ctrl+Z o quitar clips sueltos. ¿Continuar?")
        if r == QMessageBox.Yes:
            created = self.ctrl.insert_ranges(items, self.track.currentData(), f"IA · Rellenar con B-roll",
                                              origin=ORIGIN_AI, only_gaps=True,
                                              volume=self.clip_vol.value() / 100)
            if isinstance(created, list):
                self.status.setText(f"✓ La IA insertó {len(created)} clips (borde naranja).")
