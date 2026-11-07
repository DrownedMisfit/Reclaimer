"""Ventana principal: une biblioteca, visor, inspector y timeline."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QSizePolicy, QToolBar,
                               QPushButton, QScrollArea, QScrollBar, QTabWidget,
                               QUndoView, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..core.controller import ProjectController
from ..core import transform
from ..core.model import FORMATS, TRACK_AUDIO, TRACK_VIDEO
from ..core.paths import autosave_path, session_lock_path
from .ai_manager import ClipAnalysisManager
from .audio_monitor import AudioMonitor
from .ai_panel import AIPanel
from . import help as help_ui
from .export_dialog import ExportDialog
from .common import fmt_tc
from .help import set_help
from .inspector import InspectorPanel
from .library import LibraryPanel
from .preview import PlaybackEngine, PreviewPanel, decodificar_grafica
from .subtitles_panel import SubtitlesPanel
from .timeline import TimelineWidget
from .transcript_panel import TranscriptPanel
from .voice_panel import VoicePanel
from . import intro_outro_dialog
from .hint_marks import set_source as marcas_set

PROJECT_FILTER = "Proyecto de Reclaimer (*.eia)"
AUTOSAVE_MS = 60_000

SHORTCUTS_HELP = """
<b>Reproducción</b><br>
Espacio — reproducir / pausar<br>
J / K / L — hacia atrás / parar / hacia delante (pulsa J o L otra vez = 2×, 4×, 8×)<br>
I / O — marcar entrada / salida · Mayús+I / Mayús+O — ir a ellas · Alt+X — quitarlas<br>
Alt+/ — reproducir de la entrada a la salida · Ctrl+/ — repetir en bucle<br>
← / → — fotograma anterior / siguiente<br>
Inicio / Fin — ir al principio / al final<br><br>
<b>Edición</b><br>
S — dividir en el cabezal (lo seleccionado, o todo lo no bloqueado)<br>
Supr — eliminar clips seleccionados (o el hueco seleccionado)<br>Arrastrar en zona vacía — rectángulo de selección<br>
Mayús+Supr — eliminar y cerrar el hueco<br>
Ctrl+L — bloquear / desbloquear clips seleccionados<br>
Ctrl++ — juntar: todo se pega a la izquierda (sin huecos) en el canal seleccionado o en toda la línea de tiempo<br>
Ctrl+Mayús+Supr — eliminar silencio (como en Resolve)<br>
Ctrl+C / Ctrl+X / Ctrl+V — copiar / cortar / pegar clips en el cabezal · Alt+V — pegar atributos<br>
R — velocidad del clip · Mayús+R — congelar la imagen desde el cabezal<br>
Alt+T — transición (disolver) en el corte más cercano<br>
M — añadir marcador en el cabezal<br>
Ctrl+Z / Ctrl+Y — deshacer / rehacer<br>
Ctrl+A — seleccionar todos los clips<br><br>
<b>Timeline</b><br>
Rueda — desplazarse · Ctrl+rueda — zoom · Mayús+rueda — subir/bajar<br>
+ / − — acercar / alejar · Ctrl+0 — ajustar todo a la ventana<br>
Arrastra el borde de un clip para recortarlo; arrastra el clip para moverlo.<br>
Ctrl+arrastrar borde — ripple (lo de detrás se mueve) · Ctrl+Mayús+borde — mover el corte (roll)<br>
Mayús+T — herramienta ⇿ Recorte: centro = slip (otra parte del video) · Mayús+centro = slide<br><br>
<b>Voz</b><br>
Ctrl+T — transcribir y analizar · Ctrl+Shift+T — volver a analizar<br>
En «Texto»: clic en una palabra = ir a ese momento, doble clic = corregirla<br><br>
<b>Edición avanzada</b><br>
T — añadir texto en el cabezal · Ctrl+R — revisar el proyecto<br>
Con un clip seleccionado: arrastrar en el visor = mover encuadre · rueda = zoom<br><br>
<b>Proyecto</b><br>
Ctrl+N nuevo · Ctrl+O abrir · Ctrl+S guardar · Ctrl+Alt+S guardar versión · Ctrl+E exportar<br>
Ctrl+1 / Ctrl+2 / Ctrl+3 — pestaña 🎬 YouTube / 🎵 Edits / 📱 Shorts (lo de la que dejas queda guardado)<br>
Ctrl+Mayús+R — 🎙 grabar voz en off · Ctrl+Mayús+K — 📑 capítulos para YouTube · Ctrl+Alt+G — 📸 fotograma (PNG)
"""


class _PanelSwitcher:
    """Compatibilidad con el antiguo panel de pestañas: setCurrentWidget(panel) lo muestra delante."""

    def __init__(self, win):
        self.win = win
        self._order = ["inspector", "voice", "transcript", "subtitles", "ai", "history"]

    def setCurrentWidget(self, widget):
        self.win.show_panel(widget)

    def widget(self, i: int):
        return self.win.docks[self._order[i]].panel

    def count(self) -> int:
        return len(self._order)


class MainWindow(QMainWindow):
    _motor_warning = Signal(str)        # aviso desde la comprobación del motor de IA (en segundo plano)

    def __init__(self):
        super().__init__()
        self.ctrl = ProjectController(self)
        from .workspaces import Workspaces
        self.workspaces = Workspaces(self)   # 🗂 pestañas: Video de YouTube · Edits · Shorts (cada una su proyecto)
        from .learning import Learner
        self.learner = Learner(self.ctrl, self)   # ◈ aprendizaje de tu estilo (apagado si no lo activas)
        self.settings = QSettings("EditorIA", "EditorIA")

        # --- paneles ---
        self.analyzer = ClipAnalysisManager(self.ctrl, self)
        self.library = LibraryPanel(self.ctrl, self.analyzer)
        self.preview = PreviewPanel()
        self.preview.title_label.renamed.connect(lambda n: self.ctrl.rename_project(n))
        self.workspaces.switched.connect(self.preview.set_guides_space)   # ▦ guías de cada pestaña (Edits/Shorts: 9:16)
        self.engine = PlaybackEngine(self.ctrl, self.preview, self)
        self.inspector = InspectorPanel(self.ctrl, self.engine)
        help_ui.install(QApplication.instance())
        set_help(self.preview, "visor")
        self.audio_monitor = AudioMonitor(self.ctrl, self.engine, self)
        self.inspector.set_monitor(self.audio_monitor)
        self.engine.playing_changed.connect(lambda playing: playing and self.audio_monitor.on
                                            and self.audio_monitor.stop())
        self.voice = VoicePanel(self.ctrl, self.engine)
        self.transcript = TranscriptPanel(self.ctrl, self.engine)
        self.subtitles = SubtitlesPanel(self.ctrl, lambda: self.voice.media_id() or "")
        # ⚡ subtítulos: solo el texto (sin buscar bostezos, titubeos, respiraciones…)
        self.subtitles.transcribe_requested.connect(lambda: self.voice.transcribe(analyze=False))
        history = QWidget()
        hl = QVBoxLayout(history)
        hl.setContentsMargins(6, 6, 6, 6)
        self.history = QUndoView(self.ctrl.undo_group)      # el historial de la pestaña activa (🗂)
        set_help(history, "historial")
        self.history.setEmptyLabel("Proyecto abierto")
        hl.addWidget(self.history, 1)
        self.hbar = QScrollBar(Qt.Horizontal)
        self.timeline = TimelineWidget(self.ctrl, self.hbar)
        scroll = QScrollArea()
        scroll.setWidget(self.timeline)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.ai_panel = AIPanel(self.ctrl, self.engine, self.timeline, lambda: self.voice.media_id() or "")
        self.ctrl.split_av = str(QSettings("EditorIA", "EditorIA").value("timeline/separar_audio", "true")).lower() == "true"
        from .proxy_manager import ProxyManager
        self.proxies = ProxyManager(self.ctrl, self)
        self.proxies.status.connect(lambda t: self.statusBar().showMessage(t, 8000))
        self.proxies.ready.connect(self.engine.refresh_sources)
        # La lista «Calidad» muestra la que de verdad se usa (antes, al abrir, decía «Completa» aunque
        # estuviera guardada «Un cuarto»)
        qi = self.preview.quality.findData(self.proxies.level)
        if qi >= 0:
            self.preview.quality.blockSignals(True)
            self.preview.quality.setCurrentIndex(qi)
            self.preview.quality.blockSignals(False)
        self.preview.quality.currentIndexChanged.connect(
            lambda _i: self.set_proxy_level(self.preview.quality.currentData()))
        self.preview.quick["silence"].clicked.connect(self.open_silence)
        self.preview.quick["gaps"].clicked.connect(self._gaps_menu)
        self.ai_panel.btn_understand.clicked.connect(self.open_understand)
        self.ai_panel.btn_moments.clicked.connect(lambda: self.open_moments(""))
        self.ai_panel.action_requested.connect(self._ai_card)
        self.ai_panel.btn_first.clicked.connect(self.open_auto)
        from .effects_panel import EffectsPanel
        from .moments_panel import MomentsPanel
        self.effects = EffectsPanel(self.ctrl, self.engine, self.timeline)
        self.moments = MomentsPanel(self.ctrl, self.engine, self.timeline)
        from .clips_panel import ClipsPanel           # 🎬 «Dijiste Fortnite en 0:12» → tráileres y gameplay para bajar
        self.clips = ClipsPanel(self.ctrl, self.timeline)
        self.clips.seek_requested.connect(self.engine.user_seek)
        self.clips.hints_changed.connect(lambda m: marcas_set(self.timeline, "clips", m))   # 🎬 marcas de «Dijiste…»
        self.transcript.search_marks_changed.connect(lambda m: marcas_set(self.timeline, "buscar", m))   # 🔎 Buscar
        self.timeline.moments_requested.connect(self.open_moments)
        self.timeline.gap_ai_requested.connect(self._gap_ai)
        self.timeline.similar_requested.connect(self.find_similar)
        self.timeline.example_requested.connect(
            lambda cid: (self.show_panel(self.moments), self.moments.example_from_clip(cid)))
        self.timeline.impact_requested.connect(self.add_impact)
        self.timeline.broll_range_requested.connect(lambda a, b: self.ai_panel.propose((a, b), apply=True))
        self.transcript.moments_requested.connect(lambda t, a: self.open_moments(t, None if a < 0 else a))
        timeline_box = QWidget()
        tl = QVBoxLayout(timeline_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.timeline_box = timeline_box
        tl.addWidget(self._timeline_toolbar())
        tl.addWidget(scroll, 1)
        tl.addWidget(self.hbar)

        # Centro: el visor. Alrededor, paneles acoplables (como en Resolve/Premiere): se arrastran por
        # su título a cualquier lado, se juntan en pestañas, se sacan como ventana flotante y, con doble
        # clic en el título, vuelven a su sitio. La distribución se recuerda al cerrar.
        # (en una pila: la página 🖼 Miniatura pone el taller en su sitio, como las páginas de Resolve)
        from PySide6.QtWidgets import QStackedWidget
        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.preview)
        self.setCentralWidget(self.central_stack)
        self._thumb_page: dict | None = None        # en la página Miniatura: lo que había (paneles, atajos)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks |
                            QMainWindow.AllowTabbedDocks | QMainWindow.GroupedDragging)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        self.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.BottomDockWidgetArea)
        self.docks: dict[str, QDockWidget] = {}
        self._dock("timeline", "Línea de tiempo", timeline_box, closable=False)
        self._dock("media", "Medios", self.library)
        self._dock("effects", "Efectos", self.effects)
        self._dock("ai", "IA ✨", self.ai_panel)
        self._dock("moments", "🔎 Momentos", self.moments)
        self._dock("clips", "🎬 Clips", self.clips)
        self._dock("inspector", "Inspector", self.inspector)
        self._dock("voice", "Limpieza", self.voice)
        self._dock("transcript", "Texto", self.transcript)
        self._dock("subtitles", "Subtítulos", self.subtitles)
        self._dock("history", "Historial", history)
        from .scopes_panel import ScopesPanel
        self.scopes = ScopesPanel(self.ctrl, self.engine)
        self._dock("scopes", "📊 Gráficas", self.scopes)
        from .guide import GuidePanel
        self.guide = GuidePanel(self)
        self._dock("guide", "📖 Guía", self.guide)
        from .task_window import TasksPanel, manager
        self.tasks_panel = TasksPanel(self)
        self._dock("tasks", "◈ Tareas de la IA", self.tasks_panel)
        from .guided_panel import GuidedPanel      # 🧭 Montaje guiado: los pasos de un montaje (página propia)
        self.guided = GuidedPanel(self)
        self._dock("guided", "🧭 Montaje guiado", self.guided)
        manager().open_panel.connect(self.open_tasks)
        self.docks["guide"].toggleViewAction().toggled.connect(lambda on: on or self.guide.clear())
        self.right_tabs = _PanelSwitcher(self)   # compatibilidad: right_tabs.setCurrentWidget(panel)
        self._default_layout()
        self._default_state = self.saveState(3)
        saved = self.settings.value("ventana/paneles")
        self._sizes_pending = saved is None
        if saved is not None:
            try:
                self.restoreState(saved, 3)
            except Exception:  # noqa: BLE001 - un estado guardado roto no impide abrir
                pass
        for key, tb in (("top", self._top_bar()), ("pages", self._page_bar())):
            bar = QToolBar(key)
            bar.setObjectName("bar_" + key)
            bar.setMovable(False)
            bar.setFloatable(False)
            bar.toggleViewAction().setVisible(False)
            bar.addWidget(tb)
            tb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.addToolBar(Qt.TopToolBarArea if key == "top" else Qt.BottomToolBarArea, bar)

        # --- conexiones ---
        self.engine.time_changed.connect(lambda t: self.timeline.set_playhead(t, follow=self.engine.playing))
        self.engine.time_changed.connect(lambda t: self.tl_timecode.setText(fmt_tc(t, self.ctrl.project.fps)))
        self.engine.time_changed.connect(self._update_meter)
        self.timeline.seek_requested.connect(self.engine.user_seek)
        self.timeline.selection_changed.connect(self.inspector.set_selection)
        from .text_writer import OnScreenText           # ✍ escribir el texto seleccionado en la pestaña «Texto»
        self.text_writer = OnScreenText(self.ctrl, self.engine, self.timeline)
        self.transcript.layout().insertWidget(0, self.text_writer)
        self.timeline.selection_changed.connect(self.text_writer.set_selection)
        self.timeline.suggestion_clicked.connect(self._on_timeline_suggestion)
        self.timeline.selection_changed.connect(self._update_framing_mode)
        self.inspector.track_requested.connect(self.open_tracking)
        self.timeline.track_requested.connect(self.open_tracking)      # también con clic derecho en el clip
        self.inspector.ramp_done.connect(self.timeline.set_selection)
        self.preview.canvas.framing_drag.connect(lambda dx, dy: self.inspector.nudge_framing(dx, dy))
        self.preview.canvas.region_changed.connect(self._on_region_changed)
        # Al volver a Reclaimer (Alt+Tab): si recuperaste de la Papelera o conectaste el disco de algún archivo
        # que faltaba, sus clips dejan de salir en rojo solos
        from PySide6.QtWidgets import QApplication as _QA
        _QA.instance().applicationStateChanged.connect(
            lambda st: self.ctrl.recheck_missing() if st == Qt.ApplicationActive and self.ctrl.missing else None)
        self.preview.canvas.dynzoom_done.connect(self._dynzoom_done)
        self.preview.canvas.annotation_added.connect(self._annotation_added)
        self.preview.canvas.mode_changed.connect(lambda _m: self._update_transform_edit())
        self.preview.act_clear_ann.triggered.connect(self._clear_annotations)
        self.preview.canvas.transform_live.connect(self._tf_live)
        # 👆 clic en una capa del visor = seleccionarla (Ctrl+clic = la de debajo), como en Resolve
        self.preview.canvas.pick_clip_cb = self._clip_on_track_now
        self.preview.canvas.layer_picked.connect(self._pick_from_viewer)
        self.preview.canvas.transform_done.connect(self._tf_done)
        self.preview.canvas.subtitle_edit.connect(self._subtitle_edit_from_viewer)
        self.engine.time_changed.connect(lambda _t: self._update_transform_edit())
        self.ctrl.project_changed.connect(self._update_transform_edit)
        self.ctrl.project_changed.connect(lambda: self._update_region_edit())
        self.preview.canvas.framing_wheel.connect(lambda steps: self.inspector.nudge_framing(0, 0, steps))
        self.voice.media_selected.connect(self.transcript.set_media)
        self.voice.cut_rules_changed.connect(self.transcript.refresh)
        self.voice.suggestion_selected.connect(self.timeline.set_highlight_suggestion)
        self.voice.quick_review_requested.connect(self.open_quick_review)
        self.transcript.set_media(self.voice.media_id() or "")
        self.library.add_requested.connect(self._add_at_playhead)
        self.library.add_at_times_requested.connect(self._add_at_times)          # 🔑 en las palabras clave
        self.library.keyword_target = lambda: self.timeline.keyword_target(self.engine.time)
        self.library.add_moment_requested.connect(self._add_moment)
        self.library.example_requested.connect(
            lambda mid, t: (self.show_panel(self.moments), self.moments.example_from_media(mid, t)))
        self.ctrl.message.connect(lambda msg: self.statusBar().showMessage(msg, 8000))
        self.ctrl.dirty_changed.connect(self._update_title)
        self.ctrl.project_replaced.connect(self._update_title)
        self.ctrl.project_changed.connect(self._update_title)

        self.ctrl.clips_placed.connect(self._auto_scene_cuts)     # ✂ «Cortar por escenas» (opción de Medios)
        from .claude_bridge import ClaudeBridge, enabled as _mcp_enabled
        self.claude_bridge = ClaudeBridge(self)        # 🤝 opcional y apagado por defecto (menú Ayuda)
        self._aligning: set[str] = set()
        self.ctrl.transcript_changed.connect(self._maybe_align)
        # ◈ el corte de silencios aprende de tus retoques: tras cada cambio (con calma) se miran sus bordes
        self._sil_edges: list[dict] = []
        self._sil_timer = QTimer(self)
        self._sil_timer.setSingleShot(True)
        self._sil_timer.setInterval(1500)
        self._sil_timer.timeout.connect(self._observe_silence_edges)
        self.ctrl.project_changed.connect(lambda *_: self._sil_timer.start() if self._sil_edges else None)
        self.ctrl.project_replaced.connect(lambda *_: self._sil_edges.clear())
        self._build_actions()
        if _mcp_enabled():
            self.claude_bridge.start()
        self._motor_warning.connect(lambda t: self.statusBar().showMessage(t, 20000))
        QTimer.singleShot(20000, self._check_motor_soon)     # sin prisa, cuando ya estás editando
        self.apply_font_scale()
        self._update_title()
        self.statusBar().showMessage("Bienvenido. Empieza importando tu narración y tus clips (panel izquierdo).")

        from .saving import SaveManager
        self.saving = SaveManager(self)      # 💾 guardado en vivo y copias de seguridad (como Resolve)
        self._autosave = QTimer(self)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        # La primera vez que abres Reclaimer, la guía te saluda (después, F1)
        if not self.settings.value("guia/vista") and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.settings.setValue("guia/vista", True)
            QTimer.singleShot(900, lambda: self.open_guide("inicio"))

        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
            self._fit_to_screen()
        else:
            self.resize(1600, 950)
            self.setWindowState(Qt.WindowMaximized)    # sin tamaño guardado: toda la pantalla, sobre la barra
        # «¿Qué me falta?»: si un mensaje dice que falta un paso, se resalta en naranja dónde hacerlo
        from .nudge import nudge_for
        self.statusBar().messageChanged.connect(lambda txt: nudge_for(txt))
        self.ctrl.message.connect(lambda txt: nudge_for(txt))

    # --------------------------------------------------------------- UI
    def _timeline_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("panelheader")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 3, 8, 3)
        self.tl_timecode = QLabel("00:00:00:00")
        self.tl_timecode.setObjectName("bigtimecode")
        self.tl_timecode.setToolTip("Tiempo del cabezal (horas:minutos:segundos:fotograma)")
        self.tl_name = QLabel("Línea de tiempo")
        self.tl_name.setObjectName("dim")
        lay.addWidget(self.tl_timecode)
        lay.addSpacing(10)
        lay.addWidget(self.tl_name)
        lay.addSpacing(18)

        def btn(text, tip, slot=None, checkable=False):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCheckable(checkable)
            if slot:
                b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        # Herramientas (como en Resolve): selección, cuchilla e imán
        self.tool_select = btn("➤", "Herramienta de selección (A)", lambda: self.set_tool("select"), True)
        self.tool_blade = btn("✂", "Herramienta cuchilla (B): clic en un clip para cortarlo ahí",
                              lambda: self.set_tool("blade"), True)
        self.tool_trim = btn("⇿", "Recorte avanzado (Mayús+T), como el modo Trim de Resolve:\n"
                                  "borde = ripple (lo de detrás se mueve) · Mayús+borde en un corte = mover el corte (roll)\n"
                                  "centro = cambiar la parte que se ve (slip) · Mayús+centro = deslizar entre vecinos (slide)\n"
                                  "Con la herramienta normal: Ctrl+borde = ripple · Ctrl+Mayús+borde = roll",
                             lambda: self.set_tool("trim"), True)
        self.tool_curves = btn("〰", "Curvas (Mayús+C): ver y editar el volumen (clips de audio) y la opacidad "
                                     "(clips de video) a lo largo del tiempo.\nClic en la línea = punto nuevo · "
                                     "arrastrar un punto = moverlo · clic derecho = borrarlo · Mayús+arrastrar la "
                                     "línea = subir/bajar toda", lambda on: self.timeline.set_curves(on), True)
        self.tool_snap = btn("∩", "Imán (N): los clips se pegan a otros clips, al cabezal, a los marcadores y a "
                                   "los golpes de la música",
                             lambda on: self.timeline.set_snapping(on), True)
        self.tool_link = btn("🔗", "Selección vinculada (Ctrl+Mayús+L): la imagen y el sonido de un video se "
                                   "mueven, recortan y cortan juntos. Alt+clic = solo uno de los dos.",
                             lambda on: self.set_linked(on), True)
        for b_ in (self.tool_select, self.tool_blade, self.tool_trim, self.tool_curves, self.tool_snap, self.tool_link):
            b_.setObjectName("tltool")      # activas: solo un poco más claras (sin borde naranja: no avisan de nada)
        self.tool_select.setChecked(True)
        self.tool_snap.setChecked(True)
        self.tool_link.setChecked(self.timeline.linked)
        lay.addSpacing(12)
        btn("Dividir", "Dividir en el cabezal (S)", self._split)
        # ⚡ Ráfaga de cortes (a mano: la IA ya no las hace sola salvo una en canciones enérgicas)
        from PySide6.QtWidgets import QMenu as _QMenu, QToolButton as _QTB
        self.btn_burst = _QTB()
        self.btn_burst.setText("⚡ Ráfaga")
        self.btn_burst.setFocusPolicy(Qt.NoFocus)
        self.btn_burst.setPopupMode(_QTB.MenuButtonPopup)
        self.btn_burst.setToolTip("⚡ Ráfaga de cortes al ritmo de la canción: 1 compás desde el cabezal, cortando a "
                                  "medio golpe; cada trozo salta a otro plano.\nFlechita: 2 compases, más rápida o "
                                  "entre las marcas I–O. Ctrl+Z la deshace.")
        self.btn_burst.clicked.connect(lambda: self.burst(1, 2))
        bm = _QMenu(self.btn_burst)
        bm.addAction("⚡ 1 compás (medio golpe)", lambda: self.burst(1, 2))
        bm.addAction("⚡ 2 compases (medio golpe)", lambda: self.burst(2, 2))
        bm.addAction("⚡⚡ 1 compás muy rápida (cuarto de golpe)", lambda: self.burst(1, 4))
        bm.addAction("⚡ Al golpe, entre las marcas I – O", lambda: self.burst(0, 1))
        bm.addAction("⚡ Medio golpe, entre las marcas I – O", lambda: self.burst(0, 2))
        self.btn_burst.setMenu(bm)
        lay.addWidget(self.btn_burst)
        btn("Eliminar", "Eliminar seleccionados (Supr)", lambda: self._delete(False))
        btn("🗑 Vaciar", "Vaciar la línea de tiempo: quita todos los clips, textos y marcadores (tus archivos "
                       "siguen en Medios). Ctrl+Z lo devuelve todo.", self.clear_timeline)
        self.btn_bars = btn("▭ Quitar barras", "Quitar las barras negras de los videos (los clips seleccionados o, si "
                            "no hay ninguno, todos): se detectan solas y el video se encuadra como si no las tuviera.\n"
                            "Ctrl+Z las devuelve (o vuelve a pulsarlo).", self.remove_black_bars)
        btn("⚑", "Añadir marcador en el cabezal (M)", self._marker)
        btn("T", "Añadir texto en el cabezal (T)", lambda: self.ctrl.add_text(self.engine.time, 4.0, "Texto"))
        lay.addSpacing(12)
        from .edit_actions import EditBar
        self.edit_bar = EditBar(self)          # 👍 · 👎 · 🔀 Remix · 🎛 Mix (si hay un edit musical)
        lay.addWidget(self.edit_bar)
        # ⊞ Dos vistas de la línea de tiempo: tu montaje y la composición (sus pistas propias, sin mezclarse)
        self.view_main = btn("▤ Principal", "Tu montaje (sin las pistas de la composición)",
                             lambda: self.timeline.set_view("main"), True)
        self.view_comp = btn("⊞ Pistas de composición", "Solo las pistas de la composición (⊞ Composición y ⊞ Fondo) y el "
                                              "audio para cuadrar el tiempo. Es el mismo video: se ve y se exporta todo junto.",
                             lambda: self.timeline.set_view("comp"), True)
        for b_ in (self.view_main, self.view_comp):
            b_.setObjectName("tltool")
        self.timeline.view_changed_cb = self._sync_view_buttons
        self.ctrl.project_changed.connect(self._sync_view_buttons)
        self.ctrl.project_replaced.connect(lambda: self.timeline.set_view("main"))
        self._sync_view_buttons()
        self.timeline.compound_requested.connect(self.make_compound)
        self.timeline.cutout_requested.connect(self.open_subject_cut)
        self.timeline.silhouette_requested.connect(self.open_silhouette_teach)
        self.timeline.dialogue_requested.connect(self.separate_dialogue)
        self.timeline.keywords_requested.connect(lambda mids: self.open_keywords(mids))
        self.timeline.scene_cuts_requested.connect(
            lambda ids, sens: self.cut_scenes(ids, sens.replace("+marcas", ""), sens.endswith("+marcas")))
        self.timeline.topics_requested.connect(self.open_topics_tool)
        self.library.keywords_requested.connect(lambda mids: self.open_keywords(mids))
        self.library.obs_marks_requested.connect(lambda mids: self.read_obs_marks(mids))
        self.preview.canvas.comp_drop.connect(self._comp_drop)
        # ⚠ Cortes de audio que pueden estar mal (líneas rojas): contador y ◀ ▶ para ir de uno a otro
        self.cut_fix = None                     # el panel de ajuste (se crea la primera vez)
        self.cut_badge = QLabel("")
        self.cut_badge.setStyleSheet("color: #ff3b30; font-weight: bold;")
        self.cut_badge.setToolTip("Cortes de audio que pueden estar mal: se comieron parte de una palabra, quedaron "
                                  "pegados a ella o suenan con la voz todavía sonando.\n"
                                  "La línea roja marca cada uno: clic en ella para revisarlo y ajustarlo.")
        lay.addWidget(self.cut_badge)
        from .cut_fix import conectar_clic
        conectar_clic(self.cut_badge, lambda: self._open_cut_issue(0))     # clic en el texto: lista de cortes
        self.btn_cut_prev = btn("◀", "Corte de audio anterior (Alt+←)", lambda: self._go_cut(-1))
        self.btn_cut_next = btn("▶", "Corte de audio siguiente (Alt+→)", lambda: self._go_cut(1))
        self.timeline.cut_issues_changed.connect(self._sync_cut_badge)
        self.timeline.cut_issue_clicked.connect(self._open_cut_issue)
        self._sync_cut_badge(0)
        lay.addStretch()
        btn("−", "Alejar (−)", lambda: self.timeline.zoom(1 / 1.5))
        btn("+", "Acercar (+)", lambda: self.timeline.zoom(1.5))
        btn("⤢", "Ver toda la timeline (Ctrl+0)", self.timeline.fit)
        return bar

    def _sync_cut_badge(self, n: int):
        """⚠ N cortes: el contador y ◀ ▶ solo se ven si hay alguno que revisar."""
        self.cut_badge.setText(f"⚠ {n} corte{'s' if n != 1 else ''}" if n else "")
        for w in (self.cut_badge, self.btn_cut_prev, self.btn_cut_next):
            w.setVisible(n > 0)

    def _go_cut(self, step: int):
        """◀ ▶ (Alt+← / Alt+→): lleva el cabezal al corte de audio anterior o siguiente y abre su ajuste."""
        issues = self.timeline.cut_issues
        if not issues:
            self.ctrl.message.emit("No hay cortes de audio que revisar.")
            return
        now = self.engine.time
        order = sorted(range(len(issues)), key=lambda k: issues[k]["t"])
        if step > 0:
            cand = [k for k in order if issues[k]["t"] > now + 0.02] or order[:1]     # al pasar del último, vuelve
            k = cand[0]
        else:
            cand = [k for k in order if issues[k]["t"] < now - 0.02] or order[-1:]
            k = cand[-1]
        t = issues[k]["t"]
        self.engine.user_seek(t)
        self.timeline.set_playhead(t, follow=True)
        self._open_cut_issue(k)

    def _open_cut_issue(self, k: int):
        """Abre (o recoloca) el panel de ajuste del corte k de la línea de tiempo."""
        issues = self.timeline.cut_issues
        if not (0 <= k < len(issues)):
            return
        if self.cut_fix is None:
            from .cut_fix import CutFixPanel
            self.cut_fix = CutFixPanel(self)
        self.cut_fix.show_issue(issues[k]["track_id"], issues[k]["t"])

    def _sync_vh_menu(self):
        for a in self.vh_actions:
            a.setChecked(a.data() == self.timeline.video_h)

    def _sync_wave_menu(self):
        tl = self.timeline
        for a in self.wave_menu.actions():
            d = a.data()
            if not d:
                continue
            key, val = d
            a.setChecked({"style": tl.wave_style == val, "db": tl.wave_db, "silence": tl.wave_silence,
                          "words": tl.wave_words,
                          "audio_h": tl.audio_h == val}[key])

    def _dock(self, key: str, title: str, widget: QWidget, closable: bool = True) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName("dock_" + key)
        d.panel = widget
        if key != "timeline":
            # Cada panel puede encogerse (con barra de desplazamiento) en vez de aplastar la línea de tiempo
            from PySide6.QtWidgets import QScrollArea
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QScrollArea.NoFrame)
            sc.setWidget(widget)
            d.setWidget(sc)
        else:
            d.setWidget(widget)
        feats = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        if closable:
            feats |= QDockWidget.DockWidgetClosable
        d.setFeatures(feats)
        d.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.docks[key] = d
        return d

    _OCULTOS_AL_INICIO = ("guide", "tasks", "guided")     # se abren cuando se pide (Ventana o su página)

    def _default_layout(self):
        """Distribución inicial (como en Resolve): [Medios] | [Visor] | [Inspector] arriba y la línea de
        tiempo sola abajo, a todo lo ancho. Junto a la línea de tiempo no hay nada por defecto: si
        quieres, arrastra ahí cualquier panel (por su pestaña o su título)."""
        d = self.docks
        for dock in d.values():
            if dock.isFloating():
                dock.setFloating(False)
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, d["timeline"])
        self.addDockWidget(Qt.LeftDockWidgetArea, d["media"])
        self.tabifyDockWidget(d["media"], d["effects"])
        self.tabifyDockWidget(d["media"], d["ai"])
        self.tabifyDockWidget(d["media"], d["moments"])
        self.tabifyDockWidget(d["media"], d["clips"])
        self.addDockWidget(Qt.RightDockWidgetArea, d["inspector"])
        for k in ("voice", "transcript", "subtitles", "history", "scopes"):
            self.tabifyDockWidget(d["inspector"], d[k])
        # 🧭 Montaje guiado: debajo del inspector (a la derecha), así se ve a la vez que 🎬 Clips (a la izquierda)
        self.addDockWidget(Qt.RightDockWidgetArea, d["guided"])
        self.splitDockWidget(d["inspector"], d["guided"], Qt.Vertical)
        # La guía flota aparte (así nunca tapa ni oculta la opción que te está enseñando)
        self.addDockWidget(Qt.RightDockWidgetArea, d["tasks"])   # al lado; se puede soltar y arrastrar
        self.addDockWidget(Qt.RightDockWidgetArea, d["guide"])
        d["guide"].setFloating(True)
        for key, dock in d.items():
            dock.setVisible(key not in self._OCULTOS_AL_INICIO)
        d["media"].raise_()
        d["inspector"].raise_()
        self.resizeDocks([d["media"], d["inspector"]], [380, 440], Qt.Horizontal)
        self.resizeDocks([d["timeline"]], [380], Qt.Vertical)

    def reset_layout(self):
        self.restoreState(self._default_state, 3)
        for key, dock in self.docks.items():
            dock.setVisible(key not in self._OCULTOS_AL_INICIO)
        self.docks["media"].raise_()
        self.docks["inspector"].raise_()
        QTimer.singleShot(0, self._apply_dock_sizes)

    def apply_font_scale(self):
        """Aplica Ventana → Tamaño de letra (paneles y menús / global) al momento."""
        from .theme import apply_fonts, scaled_style
        ui, tl = apply_fonts(QApplication.instance())
        self.timeline_box.setStyleSheet(scaled_style(tl))     # la línea de tiempo usa solo la escala global
        self.timeline.set_text_scale(tl)
        k = max(1.0, ui)                                       # barras de alto fijo: que quepa la letra
        for name, base in (("pagebar", 58), ("topbar", 30)):
            w = self.findChild(QWidget, name)
            if w is not None:
                w.setFixedHeight(int(base * k))
        self.preview.header.setFixedHeight(int(30 * k))

    def open_font_size(self):
        from .font_dialog import FontSizeDialog
        FontSizeDialog(self).exec()

    def open_guide(self, lesson: str | None = None):
        """📖 Guía paso a paso (F1). La primera vez aparece flotando a la derecha."""
        d = self.docks["guide"]
        d.show()
        d.raise_()
        if d.isFloating() and not self.settings.value("guia/colocada"):
            g = self.geometry()
            d.resize(400, 640)
            d.move(g.right() - 420, g.top() + 100)
            self.settings.setValue("guia/colocada", True)
        if lesson:
            self.guide.open_lesson(lesson)

    def show_panel(self, widget: QWidget):
        """Muestra y pone delante el panel que contiene ese widget (esté donde esté)."""
        for dock in self.docks.values():
            if getattr(dock, "panel", None) is widget or dock.widget() is widget:
                dock.show()
                dock.raise_()
                return dock
        return None

    def set_proxy_level(self, level: str):
        """Resolución de reproducción de la línea de tiempo: Completa / Media / Un cuarto."""
        self.proxies.set_level(level)
        for a in getattr(self, "proxy_actions", {}).values():
            a.setChecked(a.data() == level)
        i = self.preview.quality.findData(level)
        if i >= 0 and self.preview.quality.currentIndex() != i:
            self.preview.quality.blockSignals(True)
            self.preview.quality.setCurrentIndex(i)
            self.preview.quality.blockSignals(False)

    def set_linked(self, on: bool):
        self.timeline.set_linked(on)
        self.tool_link.setChecked(on)
        if hasattr(self, "act_linked"):
            self.act_linked.setChecked(on)

    def _set_split_av(self, on: bool):
        self.ctrl.split_av = on
        self.settings.setValue("timeline/separar_audio", on)

    def set_tool(self, tool: str):
        self.timeline.set_tool(tool)
        self.tool_select.setChecked(tool == "select")
        self.tool_blade.setChecked(tool == "blade")
        self.tool_trim.setChecked(tool == "trim")

    # ------------------------------------------------ barras tipo DaVinci Resolve
    def _about(self):
        from .branding import symbol_pixmap
        box = QMessageBox(self)
        box.setWindowTitle(f"Acerca de {APP_NAME}")
        box.setIconPixmap(symbol_pixmap(96))
        box.setText(f"<span style='font-size:18pt; letter-spacing:6px'>RECLAIMER</span><br>"
                    f"<span style='color:#9aa1ad'>versión {__version__}</span>")
        box.setInformativeText("Editor de video con asistente de IA, 100 % local y gratis.<br>"
                               "Videos de YouTube, Shorts y edits musicales.<br><br>"
                               "La IA propone; tú decides. Todo se puede deshacer.")
        from .. import SUPPORT_URL
        if SUPPORT_URL:
            box.setInformativeText(box.informativeText() + f"<br><br>Es gratis. Si te sirve: "
                                   f"<a href='{SUPPORT_URL}'>♥ invítame un café</a>")
            box.setTextFormat(Qt.RichText)
            box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.exec()

    def _top_bar(self) -> QWidget:
        from .branding import symbol_pixmap
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(30)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        logo = QLabel()
        logo.setPixmap(symbol_pixmap(18))
        logo.setToolTip("Reclaimer")
        brand = QLabel("RECLAIMER")
        brand.setStyleSheet("color: #c9cad0; letter-spacing: 4px; font-size: 8pt; font-weight: 600;")
        lay.addWidget(logo)
        lay.addSpacing(4)
        lay.addWidget(brand)
        lay.addSpacing(14)
        self.btn_show_media = QPushButton("🗂  Medios")
        self.btn_show_media.setObjectName("flat")
        self.btn_show_media.setToolTip("Mostrar el panel de medios")
        self.btn_show_media.clicked.connect(lambda: self.show_panel(self.library))
        self.project_title = QLabel()
        self.project_title.setObjectName("dim")
        self.btn_show_inspector = QPushButton("Inspector  ☰")
        self.btn_show_inspector.setObjectName("flat")
        self.btn_show_inspector.setToolTip("Mostrar el inspector")
        self.btn_show_inspector.clicked.connect(lambda: self.show_panel(self.inspector))
        lay.addWidget(self.btn_show_media)
        lay.addStretch()
        lay.addWidget(self.workspaces.bar)
        lay.addSpacing(10)
        lay.addWidget(self.project_title)
        lay.addStretch()
        self.btn_font = QPushButton("🔠 Letra")
        self.btn_font.setObjectName("flat")
        self.btn_font.setToolTip("Hacer las letras más grandes o más pequeñas (también en Ventana → Tamaño de letra)")
        self.btn_font.clicked.connect(self.open_font_size)
        lay.addWidget(self.btn_font)
        lay.addSpacing(6)
        lay.addWidget(self.btn_show_inspector)
        return bar

    PAGES = [("media", "🗂", "Medios"), ("effects", "✦", "Efectos"), ("edit", "🎞", "Editar"),
             ("guided", "🧭", "Montaje guiado"),
             ("fairlight", "🎚", "Audio"), ("ai", "✨", "IA"), ("thumb", "🖼", "Miniatura"), ("deliver", "🚀", "Entrega")]

    def _page_bar(self) -> QWidget:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton

        from .theme import glyph_icon
        bar = QWidget()
        bar.setObjectName("pagebar")
        bar.setFixedHeight(58)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(6)
        lay.addStretch()
        self.page_buttons = {}
        for key, icon, label in self.PAGES:            # icono de un color encima del nombre, como en Resolve
            b = QToolButton()
            b.setText(label)
            b.setIcon(glyph_icon(icon, 22))
            b.setIconSize(QSize(22, 22))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setObjectName("page")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=key: self.go_page(k))
            self.page_buttons[key] = b
            lay.addWidget(b)
        lay.addStretch()
        self.page_buttons["edit"].setChecked(True)
        return bar

    def go_page(self, key: str):
        """Cambiar de «página» como en Resolve (todas trabajan sobre el mismo proyecto)."""
        if key != "thumb" and self._thumb_page is not None and getattr(self, "_thumb_editor", None) is not None:
            self._thumb_editor.close()             # sale de 🖼 Miniatura (se guarda) y vuelve el editor
        for k, b in self.page_buttons.items():
            b.setChecked(k == key)
        if key == "media":
            self.show_panel(self.library)
            self.library.search.setFocus()
        elif key == "effects":
            self.show_panel(self.effects)
            self.show_panel(self.inspector)
        elif key == "edit":
            self.show_panel(self.library)
            self.show_panel(self.inspector)
        elif key == "guided":
            self.show_panel(self.guided)
            self.show_panel(self.clips)         # a la izquierda; el guiado, a la derecha: se ven a la vez
        elif key == "fairlight":
            sel = list(self.inspector._ids)   # una imagen con su sonido vinculado cuenta como uno
            c = self.ctrl.project.clips.get(sel[0]) if len(sel) == 1 else None
            m = self.ctrl.project.media_of(c) if c else None
            if m and (m.kind == "audio" or m.has_audio):
                self.right_tabs.setCurrentWidget(self.inspector)
                self.inspector.clip_tabs.setCurrentIndex(2)
            else:
                self.right_tabs.setCurrentWidget(self.ai_panel)
                self.ai_panel.show_audio_section()
                self.statusBar().showMessage("Selecciona un clip de audio para ver su ecualizador en el Inspector.",
                                             6000)
        elif key == "ai":
            self.show_panel(self.ai_panel)
            self.show_panel(self.voice)
        elif key == "thumb":
            self.open_thumbnail()
        elif key == "deliver":
            self.export()
            for k, b in self.page_buttons.items():
                b.setChecked(k == "edit")

    def _build_actions(self):
        mb = self.menuBar()
        self.btn_learning = QPushButton("◈ Aprendizaje IA")
        self.btn_learning.setObjectName("flat")
        self.btn_learning.setToolTip("Que la IA aprenda (o no) de tu forma de editar. Tú lo controlas todo.")
        self.btn_learning.clicked.connect(self.open_learning)
        corner = self._corner = QWidget()      # (guardado: si no, Python lo borra con sus botones)
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 4, 0)
        cl.setSpacing(4)
        self.btn_quick_export = QPushButton("⚡ Exportar rápido")
        self.btn_quick_export.setObjectName("flat")
        self.btn_quick_export.setToolTip("Como el «Exportación rápida» de Resolve: eliges para dónde y a qué carpeta "
                                         "de tu PC, y se exporta en segundo plano (puedes seguir editando).")
        self.btn_quick_export.clicked.connect(self.quick_export)
        cl.addWidget(self.btn_quick_export)
        cl.addWidget(self.btn_learning)
        mb.setCornerWidget(corner, Qt.TopRightCorner)
        self.learner.changed.connect(self._learning_badge)
        self._learning_badge()

        from .shortcuts_dialog import saved_shortcut
        self.shortcut_actions = {}     # «Menú/Orden» → (acción, atajo de fábrica): ⌨ Personalizar atajos

        def act(menu, text, shortcut, slot, tip=None):
            a = QAction(text, self)
            key = f"{menu.title().replace('&', '')}/{text}"
            default = shortcut or ""
            mine = saved_shortcut(key)
            if mine is not None:
                shortcut = mine          # el que elegiste tú (o "" = sin atajo)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            self.shortcut_actions[key] = (a, default)
            a.triggered.connect(slot)
            if tip:
                a.setStatusTip(tip)
            menu.addAction(a)
            self.addAction(a)  # para que el atajo funcione siempre
            return a

        m = mb.addMenu("&Archivo")
        act(m, "Nuevo proyecto", "Ctrl+N", self.new_project)
        self.menu_templates = m.addMenu("Nuevo desde plantilla ▸")      # 📋 plantillas de proyecto
        self.menu_templates.setToolTip("Proyecto nuevo con el formato, las pistas y el estilo de subtítulos de una "
                                       "plantilla (sin clips ni medios).")
        self.menu_templates.aboutToShow.connect(self._fill_templates_menu)
        act(m, "Abrir proyecto…", "Ctrl+O", self.open_project)
        act(m, "Guardar", "Ctrl+S", self.save)
        act(m, "Guardar como…", "Ctrl+Shift+S", self.save_as)
        act(m, "📋 Guardar como plantilla…", None, self.save_as_template)
        act(m, "Guardar nueva versión (v01, v02…)", "Ctrl+Alt+S", self.save_version)
        act(m, "💾 Guardado y copias de seguridad…", None, lambda: self.saving.open_settings())
        act(m, "⟲ Recuperar una copia de seguridad…", None, lambda: self.saving.open_settings())
        act(m, "📦 Recopilar proyecto (copia con todos sus archivos)…", None, self.open_collect)
        m.addSeparator()
        # 🗂 Cambiar de pestaña de trabajo con el teclado (lo de la pestaña que dejas queda guardado)
        act(m, "🎬 Ir a la pestaña YouTube", "Ctrl+1", lambda: self.workspaces.switch("youtube"))
        act(m, "🎵 Ir a la pestaña Edits", "Ctrl+2", lambda: self.workspaces.switch("edit"))
        act(m, "📱 Ir a la pestaña Shorts", "Ctrl+3", lambda: self.workspaces.switch("short"))
        self.menu_move = m.addMenu("↪ Mover este proyecto a")          # cambia su formato y lo lleva a otra pestaña
        self.menu_move.setToolTip("Lleva el proyecto actual a otra pestaña (cambia su formato). Ctrl+Z lo devuelve.")
        self.menu_move.aboutToShow.connect(lambda: self.workspaces.fill_move_menu(self.menu_move))
        m.addSeparator()
        act(m, "Importar archivos…", "Ctrl+I", self.library.import_files_dialog)
        act(m, "Importar carpeta…", "Ctrl+Shift+I", self.library.import_folder_dialog)
        m.addSeparator()
        act(m, "Exportar video…", "Ctrl+E", self.export)
        act(m, "🚀 Cola de exportación…", "Ctrl+Shift+E", self.open_queue)
        act(m, "🖼 Crear miniatura…", "Ctrl+Shift+M", self.open_thumbnail)
        act(m, "📸 Exportar este fotograma (PNG)", "Ctrl+Alt+G", self.export_frame)
        act(m, "📝 Descripción para YouTube (capítulos, créditos…)", "Ctrl+Shift+K", self.open_chapters)
        m.addSeparator()
        act(m, "Salir", "Ctrl+Q", self.close)

        m = mb.addMenu("&Editar")
        undo = self.ctrl.undo_group.createUndoAction(self, "Deshacer")    # el de la pestaña activa
        undo.setShortcut(QKeySequence.Undo)
        redo = self.ctrl.undo_group.createRedoAction(self, "Rehacer")
        redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        m.addAction(undo)
        m.addAction(redo)
        self.addAction(undo)
        self.addAction(redo)
        m.addSeparator()
        act(m, "Copiar clips", "Ctrl+C", lambda: self._copy(False))
        act(m, "Cortar clips", "Ctrl+X", lambda: self._copy(True))
        act(m, "Pegar en el cabezal", "Ctrl+V", self._paste)
        act(m, "Pegar atributos… (efectos, zoom, sonido, velocidad)", "Alt+V", self._paste_attributes)
        act(m, "Pegar e insertar", "Ctrl+Shift+V", self._paste_insert)
        act(m, "Cortar y propagar", "Ctrl+Shift+X", self._cut_ripple)
        act(m, "Insertar espacio", None, self._insert_gap)
        from .music_fit_ui import add_music_fit_menu      # 🎵 Ajustar la música a la duración / selección
        add_music_fit_menu(self, m)
        m.addSeparator()
        act(m, "🔖 Leer marcas de OBS", None, lambda: self.read_obs_marks(),
            "Pone como marcadores rojos los capítulos que pusiste con una tecla mientras grababas en OBS")
        act(m, "🔖 Fallos marcados…", None, lambda: self.open_obs_fallos(),
            "Lista de fallos marcados en OBS: quita cada frase equivocada con un clic")
        act(m, "Eliminar atributos…", None, self._remove_attributes)
        act(m, "🎬 Mi intro y mi outro…", None, lambda: intro_outro_dialog.open_dialog(self))
        act(m, "➕ Poner mi intro y outro", None, lambda: intro_outro_dialog.put_now(self))
        m.addSeparator()
        act(m, "Activar / desactivar clip", "D", self._toggle_enabled)
        act(m, "Cambiar duración…", "Ctrl+D", self._change_duration)
        act(m, "Cambiar velocidad…", None, self._change_speed)
        act(m, "Normalizar volumen…", None, self._normalize)
        act(m, "Buscar en el panel multimedia", "Alt+F", self._find_in_media)
        act(m, "Atributos del clip…", None, self._clip_info)
        m.addSeparator()
        act(m, "Dividir en el cabezal", "S", self._split)
        act(m, "Eliminar", "Delete", lambda: self._delete(False))
        act(m, "Eliminar y cerrar hueco", "Shift+Delete", lambda: self._delete(True))
        act(m, "⇤ Juntar: todo se pega a la izquierda (canal seleccionado o todo)", "Ctrl++", self._join_right,
            "Cierra el hueco: el hueco seleccionado, el que hay a la izquierda de los clips seleccionados o el del "
            "cabezal (con su imagen o sonido vinculado). Ctrl+Z lo deshace.")
        act(m, "🗑 Vaciar la línea de tiempo…", None, self.clear_timeline)
        act(m, "Bloquear / desbloquear selección", "Ctrl+L", self._toggle_lock)
        act(m, "Seleccionar todos los clips", "Ctrl+A", self.timeline.select_all)
        act(m, "Añadir marcador", "M", self._marker)
        m.addSeparator()
        act(m, "Marcar entrada", "I", lambda: self.ctrl.set_mark("in", self.engine.time))
        act(m, "Marcar salida", "O", lambda: self.ctrl.set_mark("out", self.engine.time))
        act(m, "Ir a la entrada", "Shift+I", lambda: self._go_mark("in"))
        act(m, "Ir a la salida", "Shift+O", lambda: self._go_mark("out"))
        act(m, "Quitar entrada y salida", "Alt+X", self.ctrl.clear_marks)
        act(m, "Quitar el tramo marcado (y cerrar el hueco)", None, self.ctrl.delete_marked)
        m.addSeparator()
        act(m, "Velocidad del clip…", "R", self._speed)
        act(m, "Congelar la imagen desde el cabezal", "Shift+R", self._freeze)
        act(m, "Reproducir al revés (sí/no)", None, self._toggle_reverse)
        act(m, "✂ Eliminar silencio…", "Ctrl+Shift+Delete", self.open_silence)
        act(m, "⧉ Poner transición (disolver) en el corte", "Alt+T",
            lambda: self.ctrl.set_transition(self.ctrl.transition_targets(sorted(self.timeline.selected),
                                                                          self.engine.time), "fade", 0.5))
        m.addSeparator()
        act(m, "Herramienta de selección", "A", lambda: self.set_tool("select"))
        act(m, "Herramienta cuchilla", "B", lambda: self.set_tool("blade"))
        act(m, "Herramienta de recorte avanzado (ripple, roll, slip, slide)", "Shift+T", lambda: self.set_tool("trim"))
        act(m, "〰 Curvas de volumen y opacidad (sí/no)", "Shift+C",
            lambda: (self.tool_curves.toggle(), self.timeline.set_curves(self.tool_curves.isChecked())))
        act(m, "Imán (encajar) sí/no", "N", lambda: self.tool_snap.toggle() or
            self.timeline.set_snapping(self.tool_snap.isChecked()))
        a_rh = m.addAction("🥁 Imán también a los golpes de la música")
        a_rh.setCheckable(True)
        a_rh.setChecked(self.timeline.snap_rhythm)
        a_rh.setToolTip("Con el imán puesto, los clips y la cuchilla se pegan a los golpes y al drop de las "
                        "canciones de la pista de música (su ritmo se reconoce solo al ponerlas).")
        a_rh.toggled.connect(self.timeline.set_snap_rhythm)
        self.act_snap_rhythm = a_rh

        m = mb.addMenu("&Reproducción")
        pm = m.addMenu("Resolución de la línea de tiempo (proxy)")
        self.proxy_actions = {}
        for lv, (label, _div) in __import__("editoria.core.proxies", fromlist=["LEVELS"]).LEVELS.items():
            a = act(pm, label + ("  (original)" if lv == "full" else "  (más fluido)"), None,
                    lambda _=False, v=lv: self.set_proxy_level(v))
            a.setCheckable(True)
            a.setData(lv)
            self.proxy_actions[lv] = a
        self.proxy_actions[self.proxies.level].setChecked(True)
        pm.addSeparator()
        a_auto = pm.addAction("Tener las copias ligeras listas también en «Completa»")
        a_auto.setCheckable(True)
        a_auto.setChecked(self.proxies.extra)
        a_auto.setToolTip("Apagado (normal): solo se hacen las copias de la calidad que eliges, cuando la eliges (así "
                          "no se gasta nada si reproduces en «Completa»). Encendido: la copia «Media» de tus videos se "
                          "prepara de antemano en segundo plano. Ocupan algo de disco (en datos\\cache\\proxies).")
        a_auto.toggled.connect(self.proxies.set_extra)
        pm.addSeparator()
        a_gpu = pm.addAction("Decodificar el video con la tarjeta gráfica")
        a_gpu.setCheckable(True)
        a_gpu.setChecked(decodificar_grafica())
        a_gpu.setToolTip("Activado: menos CPU, pero un pequeño parón al abrir cada archivo. Desactivado: más suave al "
                         "cambiar de clip, usa más CPU. Se aplica al reiniciar Reclaimer.")
        a_gpu.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "reproduccion/decodificar_grafica", bool(on)))
        m.addSeparator()
        act(m, "Reproducir / pausar", "Space", self.engine.toggle)
        self.act_second = act(m, "🖥 Visor en la segunda pantalla", "F11", self.toggle_second_screen,
                              tip="Muestra el visor, grande y sin controles, en el otro monitor (Esc para cerrarlo)")
        self.act_second.setCheckable(True)
        QTimer.singleShot(0, self._restore_second_screen)
        act(m, "Hacia atrás (J: otra vez = más rápido)", "J", lambda: self.engine.jkl("j"))
        act(m, "Parar (K)", "K", lambda: self.engine.jkl("k"))
        act(m, "Hacia delante (L: otra vez = más rápido)", "L", lambda: self.engine.jkl("l"))
        act(m, "Reproducir de la entrada a la salida", "Alt+/", self.engine.play_marked)
        self.act_loop = act(m, "Repetir en bucle", "Ctrl+/", lambda on: self.engine.set_loop(on))
        self.act_loop.setCheckable(True)
        self.preview.btn_loop.toggled.connect(self.act_loop.setChecked)
        act(m, "Fotograma anterior", "Left", lambda: self.engine.step(-1))
        act(m, "Fotograma siguiente", "Right", lambda: self.engine.step(1))
        act(m, "Ir al inicio", "Home", lambda: self.engine.seek(0))
        act(m, "Ir al final", "End", lambda: self.engine.seek(self.ctrl.project.duration()))
        act(m, "Corte de audio anterior (línea roja)", "Alt+Left", lambda: self._go_cut(-1))
        act(m, "Corte de audio siguiente (línea roja)", "Alt+Right", lambda: self._go_cut(1))

        m = mb.addMenu("&Voz")
        act(m, "Transcribir y analizar la narración", "Ctrl+T",
            lambda: (self.right_tabs.setCurrentWidget(self.voice), self.voice.transcribe()))
        act(m, "Volver a analizar (silencios, muletillas…)", "Ctrl+Shift+T",
            lambda: (self.right_tabs.setCurrentWidget(self.voice), self.voice.analyze()))
        act(m, "🔎 Buscar en lo que dijiste", "Ctrl+Alt+F",           # (Ctrl+F ya es de «Buscar clips por contenido»)
            lambda: (self.right_tabs.setCurrentWidget(self.transcript), self.transcript.focus_search()))
        act(m, "Ver transcripción", None, lambda: self.right_tabs.setCurrentWidget(self.transcript))
        act(m, "Estilo de subtítulos", None, lambda: self.right_tabs.setCurrentWidget(self.subtitles))
        act(m, "Exportar subtítulos (.srt)…", None, self.transcript.export_srt)
        m.addSeparator()
        act(m, "🎙 Grabar voz en off…", "Ctrl+Shift+R", self.open_voice_record)
        act(m, "🎚 Analizar y proponer mezcla (música, diálogos y voz)…", None, self.open_mix)
        m.addSeparator()
        act(m, "◈ Entrenar la IA con mi voz", None, self.train_voice_now)
        act(m, "◈ Olvidar lo que la IA aprendió de mi voz…", None, self.forget_voice)

        # La IA vive en UN solo sitio: la pestaña «IA ✨» (antes también había un menú «IA» arriba, repetido).
        # Este menú no se enseña: solo guarda las órdenes para que sus atajos sigan funcionando.
        from PySide6.QtWidgets import QMenu as _QMenu
        m = _QMenu("&IA", self)
        self._ai_hidden_menu = m
        act(m, "◈ Analizar el contenido de los clips", None, self.library._analyze_clicked)
        act(m, "◎ Detectar temas de la narración", None,
            lambda: (self.right_tabs.setCurrentWidget(self.ai_panel), self.ai_panel.detect_topics()))
        act(m, "🎬 Proponer B-roll", None,
            lambda: (self.right_tabs.setCurrentWidget(self.ai_panel), self.ai_panel.propose()))
        act(m, "🔬 Entender mi biblioteca a fondo…", None, self.open_understand)
        act(m, "◈ Analizar a fondo lo seleccionado en Medios", None, self.analyze_selected_full)
        act(m, "🔎 Buscar momentos en mis medios…", "Ctrl+Shift+F", lambda: self.open_moments(""))
        act(m, "⧉ Comparación…", None, self.open_compare)
        act(m, "🎵 Crear edit musical…", "Ctrl+M", self.open_edit_maker)
        act(m, "⚕ Revisar el proyecto…", "Ctrl+R", self.open_audit)
        act(m, "⚡ Revisión rápida con teclas…", "Ctrl+Shift+Q", self.open_quick_review)
        act(m, "✂ Shorts desde este video…", None, lambda: __import__(
            "editoria.ui.shorts_dialog", fromlist=["open_shorts_dialog"]).open_shorts_dialog(self))
        m.addSeparator()
        act(m, "✨ Primera versión automática…", "Ctrl+Shift+A", self.open_auto)
        act(m, "📜 Montaje desde el guion…", None, lambda: __import__(
            "editoria.ui.script_dialog", fromlist=["open_script_dialog"]).open_script_dialog(self))
        act(m, "Buscar clips por contenido", "Ctrl+F",
            lambda: (self.library.btn_ai_search.setChecked(True), self.library.search.setFocus()))

        m = mb.addMenu("&Timeline")
        act(m, "T Añadir texto en el cabezal", "T", lambda: self.ctrl.add_text(self.engine.time, 4.0, "Texto"))
        act(m, "🟦 Añadir color sólido o degradado…", None, lambda: self.open_generator())
        act(m, "🎨 Añadir capa de ajuste (color y efectos a todo lo de debajo)", None, self.add_adjustment)
        act(m, "Acercar", "+", lambda: self.timeline.zoom(1.5))
        act(m, "Alejar", "-", lambda: self.timeline.zoom(1 / 1.5))
        act(m, "Ajustar a la ventana", "Ctrl+0", self.timeline.fit)
        m.addSeparator()
        act(m, "Añadir pista de video", None, lambda: self.ctrl.add_track(TRACK_VIDEO))
        act(m, "Añadir pista de audio", None, lambda: self.ctrl.add_track(TRACK_AUDIO))
        m.addSeparator()
        self.act_linked = act(m, "🔗 Selección vinculada (audio y video juntos)", "Ctrl+Shift+L",
                              lambda: self.set_linked(not self.timeline.linked))
        self.act_linked.setCheckable(True)
        self.act_linked.setChecked(self.timeline.linked)
        a = act(m, "Separar el sonido al poner un video (como en Resolve)", None,
                lambda: self._set_split_av(not self.ctrl.split_av))
        a.setCheckable(True)
        a.setChecked(self.ctrl.split_av)
        wm = m.addMenu("〰 Forma de onda")
        tl = self.timeline
        for key, label in (("espejo", "Espejo (arriba y abajo)"), ("rectificada", "Rectificada (desde abajo)"),
                           ("contorno", "Solo contorno"), ("no", "Sin forma de onda")):
            a = act(wm, label, None, lambda _=False, k=key: (tl.set_wave(style=k), self._sync_wave_menu()))
            a.setCheckable(True)
            a.setData(("style", key))
        wm.addSeparator()
        a = act(wm, "Escala en dB (se ven mejor los sonidos bajos)", None,
                lambda: (tl.set_wave(db=not tl.wave_db), self._sync_wave_menu()))
        a.setCheckable(True)
        a.setData(("db", True))
        a = act(wm, "Marcar silencios y dónde termina el sonido", None,
                lambda: (tl.set_wave(silence=not tl.wave_silence), self._sync_wave_menu()))
        a.setCheckable(True)
        a.setData(("silence", True))
        a = act(wm, "📝 Palabras sobre la onda (al acercarte; con la transcripción)", None,
                lambda: (tl.set_wave(words=not tl.wave_words), self._sync_wave_menu()))
        a.setCheckable(True)
        a.setData(("words", True))
        wm.addSeparator()
        for h, label in ((34, "Pistas de audio: compactas"), (54, "Pistas de audio: normales"),
                         (84, "Pistas de audio: altas"), (124, "Pistas de audio: muy altas")):
            a = act(wm, label, None, lambda _=False, v=h: (tl.set_wave(audio_h=v), self._sync_wave_menu()))
            a.setCheckable(True)
            a.setData(("audio_h", h))
        self.wave_menu = wm
        self._sync_wave_menu()
        hm = m.addMenu("↕ Altura de las pistas de video")
        self.vh_actions = []
        for h, label in ((34, "Compactas"), (54, "Normales"), (84, "Altas")):
            a = act(hm, label, None, lambda _=False, v=h: (tl.set_wave(video_h=v), self._sync_vh_menu()))
            a.setCheckable(True)
            a.setData(h)
            self.vh_actions.append(a)
        self._sync_vh_menu()
        m.addSeparator()
        gm = m.addMenu("⇤ Eliminar huecos (espacios vacíos entre clips)")
        act(gm, "🔊 En todas las pistas de audio", None, lambda: self.ctrl.close_gaps_on("audio"))
        act(gm, "🎞 En todas las pistas de video", None, lambda: self.ctrl.close_gaps_on("video"))
        act(gm, "En todas las pistas", None, lambda: self.ctrl.close_gaps_on(None))
        gm.addSeparator()
        act(gm, "Solo en la pista del clip seleccionado", None, self._close_gaps_selected_track)
        m.addSeparator()
        act(m, "🔒 Bloquear toda la timeline", None, lambda: self.ctrl.lock_all_tracks(True))
        act(m, "🔓 Desbloquear toda la timeline", None, lambda: self.ctrl.lock_all_tracks(False))

        m = mb.addMenu("&Ventana")
        for key in ("media", "effects", "ai", "moments", "clips", "inspector", "voice", "transcript", "subtitles", "history",
                    "scopes", "guided", "guide", "timeline"):
            m.addAction(self.docks[key].toggleViewAction())
        m.addSeparator()
        act(m, "Restablecer la distribución de paneles", None, self.reset_layout)
        m.addSeparator()
        act(m, "🔠 Tamaño de letra…", "Ctrl+Alt+=", self.open_font_size)
        act(m, "⌨ Personalizar atajos de teclado…", None, self.open_shortcuts)

        m = mb.addMenu("&Convertir")
        act(m, "🔁 Convertir videos y audios…", "Ctrl+Alt+C", lambda: self.open_convert("mp4"))
        act(m, "🎬 A MP4 (video)…", None, lambda: self.open_convert("mp4"))
        act(m, "🎵 A MP3 (solo audio)…", None, lambda: self.open_convert("mp3"))

        m = mb.addMenu("Ay&uda")
        act(m, "📖 Guía paso a paso", "F1", lambda: self.open_guide())
        act(m, "Atajos de teclado", "Ctrl+F1", self._show_shortcuts)
        act(m, "⌨ Personalizar atajos…", None, self.open_shortcuts)
        act(m, "✧ Caché y diagnóstico…", None, self.open_diagnostics)
        act(m, "◈ Motor de IA (tarjeta gráfica)…", None, self.open_motor)
        m.addSeparator()
        from .claude_bridge import enabled as _mcp_on
        a_mcp = act(m, "🤝 Dejar que Claude edite conmigo (MCP)", None, lambda: None,
                    "Opcional: Claude (en su app o en Claude Code) puede editar tu proyecto con las funciones de "
                    "Reclaimer cuando se lo pidas. Solo en tu PC; todo se deshace con Ctrl+Z.")
        a_mcp.setCheckable(True)
        a_mcp.setChecked(_mcp_on())
        a_mcp.toggled.connect(lambda on: self.claude_bridge.set_enabled(on))
        self.a_mcp = a_mcp
        m.addSeparator()
        from .. import SUPPORT_URL
        if SUPPORT_URL:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            act(m, "♥ Apoyar Reclaimer…", None, lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        act(m, "Acerca de Reclaimer", None, self._about)

        m = mb.addMenu("🔄 &Reinicio")
        act(m, "🔄 Reinicio de proyecto (empezar de cero)…", None, self.reset_project,
            "Vacía la línea de tiempo, Medios, subtítulos y marcadores de esta pestaña para empezar de cero. Antes se "
            "guarda una copia de seguridad; tus archivos no se tocan.")

    # ----------------------------------------------------------- edición
    def _update_meter(self, t: float):
        from ..core import meters
        try:
            self.preview.meter.set_level(meters.total(meters.track_levels(self.ctrl.project, self.ctrl.peaks, t)))
        except Exception:  # noqa: BLE001 - el medidor nunca interrumpe la reproducción
            pass

    def open_silence(self):
        from .silence_dialog import SilenceDialog, targets
        self.engine.pause()
        ids, note = targets(self)
        if not ids:
            self.statusBar().showMessage(note, 6000)
            return
        if note:
            self.statusBar().showMessage(note, 6000)
        self._silence_dialog = SilenceDialog(self, ids)
        self._silence_dialog.exec()

    def _gaps_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("🔊 Quitar los huecos de todas las pistas de audio", lambda: self.ctrl.close_gaps_on("audio"))
        m.addAction("🎞 Quitar los huecos de todas las pistas de video", lambda: self.ctrl.close_gaps_on("video"))
        m.addAction("Quitar los huecos de todas las pistas", lambda: self.ctrl.close_gaps_on(None))
        m.addAction("Solo en la pista del clip seleccionado", self._close_gaps_selected_track)
        b = self.preview.quick["gaps"]
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _join_right(self):
        """⇤ Ctrl++ (el atajo del usuario en Resolve): todo se pega hacia la IZQUIERDA, sin espacios vacíos, en los
        canales seleccionados (clic en un clip, en su pista o en la cabecera); sin canal, en toda la línea de tiempo.
        Lo vinculado de otras pistas (su imagen o su sonido) se mueve igual: nada se desincroniza. Un solo Ctrl+Z."""
        tl, p = self.timeline, self.ctrl.project
        chans = tl.channel_ids()
        n = self.ctrl.close_gaps_on(None, track_ids=chans or None)
        if n:
            tl.gap = None
            where = ("en " + ", ".join(tl.track_badge(p.tracks.index(p.track(t)))[0] for t in chans) if chans
                     else "en toda la línea de tiempo")
            self.statusBar().showMessage(f"⇤ Todo pegado a la izquierda {where} ({n} huecos) · Ctrl+Z lo deshace",
                                         6000)

    def _close_gaps_selected_track(self):
        sel = [cid for cid in self.timeline.selected if cid in self.ctrl.project.clips]
        tids = self.timeline.channel_ids() or list(dict.fromkeys(self.ctrl.project.clips[cid].track_id for cid in sel))
        if not tids:
            self.statusBar().showMessage("Selecciona el canal (o un clip de la pista) donde quieres quitar los huecos.",
                                         6000)
            return
        self.ctrl.close_gaps_on(track_ids=tids)

    def _copy(self, cut: bool):
        if cut and self.timeline.delete_transition():     # Ctrl+X con una transición seleccionada: se quita
            self.statusBar().showMessage("✕ Transición quitada (Ctrl+Z la devuelve).", 5000)
            return
        sel = sorted(self.timeline.selected)
        if not sel:
            self.statusBar().showMessage("Selecciona los clips que quieres " + ("cortar." if cut else "copiar."), 5000)
            return
        try:
            n = self.ctrl.copy_clips(sel, cut=cut)
        except Exception as ex:  # noqa: BLE001 - EditError
            self.statusBar().showMessage(str(ex), 6000)
            return
        self.statusBar().showMessage(f"{'✂ Cortados' if cut else '⧉ Copiados'} {n} clips. Ctrl+V los pega en el "
                                     "cabezal · Alt+V pega sus ajustes en otros clips.", 6000)

    def _paste(self):
        created = self.ctrl.paste_clips(self.engine.time)
        if isinstance(created, list):
            self.timeline.set_selection(created)

    # ------------------------------------------------------------ clic derecho como en Resolve
    def _sel_or_msg(self, what: str = "Selecciona antes los clips.") -> list[str]:
        sel = sorted(self.timeline.selected)
        if not sel:
            self.statusBar().showMessage(what, 5000)
        return sel

    def _paste_insert(self):
        created = self.ctrl.paste_insert(self.engine.time)
        if isinstance(created, list):
            self.timeline.set_selection(created)

    def _cut_ripple(self):
        sel = self._sel_or_msg("Selecciona los clips que quieres cortar.")
        if sel:
            self.ctrl.copy_clips(sel)
            self.ctrl.delete_clips(sel, ripple=True)          # (solo lo seleccionado, como Ctrl+X y Supr)

    def _insert_gap(self):
        sel = self._sel_or_msg()
        if sel:
            self.ctrl.insert_gap(sel)

    def _toggle_enabled(self):
        sel = self._sel_or_msg()
        if sel:
            off = any(not self.ctrl.project.clips[i].enabled for i in sel)
            self.ctrl.set_clip_props(self.ctrl.linked_ids(sel), "Activar/desactivar clip", enabled=off)

    def _change_duration(self):
        from PySide6.QtWidgets import QInputDialog
        sel = self._sel_or_msg()
        if not sel:
            return
        c = self.ctrl.project.clips[sel[0]]
        v, ok = QInputDialog.getDouble(self, "Cambiar duración", "Duración en segundos (lo de detrás se mueve):",
                                       round(c.duration, 2), 0.05, 36000.0, 2)
        if ok:
            self.ctrl.change_duration(sel, v)

    def _change_speed(self):
        from PySide6.QtWidgets import QInputDialog
        sel = self._sel_or_msg()
        if not sel:
            return
        c = self.ctrl.project.clips[sel[0]]
        v, ok = QInputDialog.getDouble(self, "Cambiar velocidad", "Velocidad en % (100 = normal, 50 = cámara "
                                       "lenta, 200 = el doble de rápido):", round(c.speed * 100, 1), 1.0, 10000.0, 1)
        if ok:
            self.ctrl.set_speed(sel, speed=v / 100)

    def _remove_attributes(self):
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        sel = self._sel_or_msg()
        if not sel:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Eliminar atributos")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"¿Qué ajustes vuelven a como estaban en los {len(sel)} clip(s)?"))
        boxes = {}
        for key, text in self.ctrl.ATTRIBUTES.items():
            b = QCheckBox(text)
            lay.addWidget(b)
            boxes[key] = b
        bb = QDialogButtonBox()
        bb.addButton("Eliminar", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancelar", QDialogButtonBox.RejectRole)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec():
            attrs = [k for k, b in boxes.items() if b.isChecked()]
            if attrs:
                self.ctrl.remove_attributes(sel, attrs)

    def _normalize(self):
        from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                       QFormLayout)
        sel = self._sel_or_msg("Selecciona los clips con sonido.")
        if not sel:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Normalizar volumen")
        form = QFormLayout(dlg)
        mode = QComboBox()
        mode.addItem("Volumen percibido (LUFS) — lo de YouTube", "lufs")
        mode.addItem("Pico de la muestra (dBFS)", "peak")
        form.addRow("Modo", mode)
        target = QDoubleSpinBox()
        target.setRange(-60.0, 0.0)
        target.setDecimals(1)
        target.setValue(-14.0)
        mode.currentIndexChanged.connect(lambda _i: target.setValue(-14.0 if mode.currentData() == "lufs" else -1.0))
        form.addRow("Nivel objetivo", target)
        bb = QDialogButtonBox()
        bb.addButton("Normalizar", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancelar", QDialogButtonBox.RejectRole)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = self.ctrl.normalize_volume(sel, mode.currentData(), target.value())
        finally:
            QApplication.restoreOverrideCursor()
        if n:
            self.statusBar().showMessage(f"🔊 Volumen normalizado en {n} clip(s). Ctrl+Z lo deshace.", 6000)

    def analyze_selected_full(self):
        """◈ Analizar a fondo: forma de onda, ritmo y lo demás de los medios seleccionados en Medios (a petición)."""
        ids = self.library.selected_media_ids()
        if not ids:
            self.statusBar().showMessage("Selecciona antes uno o varios archivos en 🗂 Medios.", 6000)
            return
        self.ctrl.analyze_full(ids)

    def _find_in_media(self):
        sel = self._sel_or_msg()
        c = self.ctrl.project.clips.get(sel[0]) if sel else None
        if c is not None and c.media_id in self.ctrl.project.media:
            self.show_panel(self.library)
            self.library.select_media(c.media_id)

    def _clip_info(self):
        from .common import fmt_time
        sel = self._sel_or_msg()
        c = self.ctrl.project.clips.get(sel[0]) if sel else None
        if c is None:
            return
        m = self.ctrl.project.media_of(c)
        lines = [f"Archivo: {m.name}" if m else "Texto en pantalla",
                 f"Carpeta: {os.path.dirname(m.path)}" if m else "",
                 f"En la línea de tiempo: {fmt_time(c.start, False)} → {fmt_time(c.end, False)} "
                 f"({c.duration:.2f} s)",
                 f"Del archivo: desde {fmt_time(c.source_in, False)}" if m else "",
                 f"Tamaño: {m.width}×{m.height} · {m.fps:g} FPS" if m and m.width else "",
                 f"Velocidad: {c.speed * 100:g} %" + (" · hacia atrás" if c.reverse else ""),
                 f"Volumen: {c.volume * 100:.0f} %", f"Opacidad: {c.opacity * 100:.0f} %",
                 "Hecho por la IA" if c.origin == "ai" else "Puesto por ti"]
        QMessageBox.information(self, "Atributos del clip", "\n".join(x for x in lines if x))

    def _set_label(self, ids, color: str):
        self.ctrl.set_clip_props(self.ctrl.linked_ids(ids), "Color de clip", label=color)

    def _delete_part(self, kind: str):
        sel = self._sel_or_msg()
        if sel:
            try:
                self.ctrl.delete_part(sel, kind)
            except Exception as exc:  # noqa: BLE001 - EditError
                self.statusBar().showMessage(str(exc), 6000)

    def _paste_attributes(self):
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        sel = sorted(self.timeline.selected)
        if not getattr(self.ctrl, "clipboard", None):
            self.statusBar().showMessage("Copia primero (Ctrl+C) el clip cuyos ajustes quieres repetir.", 6000)
            return
        if not sel:
            self.statusBar().showMessage("Selecciona los clips que recibirán los ajustes.", 6000)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Pegar atributos")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"¿Qué ajustes del clip copiado pongo en los {len(sel)} clips seleccionados?"))
        boxes = {}
        for key, text in self.ctrl.ATTRIBUTES.items():
            b = QCheckBox(text)
            b.setChecked(key in ("efectos", "encuadre", "audio"))
            lay.addWidget(b)
            boxes[key] = b
        bb = QDialogButtonBox()
        bb.addButton("Pegar", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancelar", QDialogButtonBox.RejectRole)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._attr_dialog = dlg
        if dlg.exec():
            attrs = [k for k, b in boxes.items() if b.isChecked()]
            if attrs:
                self.ctrl.paste_attributes(sel, attrs)

    def _go_mark(self, which: str):
        t = self.ctrl.project.mark_in if which == "in" else self.ctrl.project.mark_out
        if t is None:
            self.statusBar().showMessage("No hay " + ("entrada" if which == "in" else "salida") +
                                         " marcada (I / O).", 5000)
            return
        self.engine.user_seek(t)

    def _speed(self):
        if not self.timeline.selected:
            self.statusBar().showMessage("Selecciona un clip para cambiar su velocidad.", 5000)
            return
        self.show_panel(self.inspector)
        self.inspector.focus_speed()

    def _freeze(self):
        sel = [cid for cid in self.timeline.selected if cid in self.ctrl.project.clips]
        vis = [cid for cid in sel if self.ctrl.project.track(self.ctrl.project.clips[cid].track_id).kind == TRACK_VIDEO]
        created = self.ctrl.freeze_frame(self.engine.time, vis[0] if vis else None)
        if isinstance(created, str):
            self.timeline.set_selection([created])

    def _toggle_reverse(self):
        sel = [cid for cid in self.timeline.selected if cid in self.ctrl.project.clips]
        if not sel:
            self.statusBar().showMessage("Selecciona los clips que quieres poner al revés.", 5000)
            return
        rev = not self.ctrl.project.clips[sel[0]].reverse
        self.ctrl.set_speed(sel, reverse=rev)

    def _add_at_playhead(self, ids):
        created = self.ctrl.add_media(ids, None, self.engine.time)
        if isinstance(created, list):
            self.timeline.set_selection(created)

    def _pregunta_modo_palabra(self, una_marca: bool) -> str | None:
        """🔑 Pregunta cómo poner el video en la(s) marca(s): «partes», «entero» o None (cancelar)."""
        from ..core.model import KIND_VIDEO as _KV
        box = QMessageBox(self)
        box.setWindowTitle("Poner el video")
        if una_marca:
            box.setText("¿Cómo lo pongo en esta marca?")
            b1 = box.addButton("Un trozo (lo que dura la frase)", QMessageBox.AcceptRole)
            b1.setToolTip("Un trozo del video, de la duración de la frase que se dice en esa marca (2 a 6 s).")
            b2 = box.addButton("Entero (hasta la siguiente marca o el final)", QMessageBox.AcceptRole)
            b2.setToolTip("Desde el principio del video (tras los logos) hasta la siguiente marca de esa palabra, "
                          "el final del video o el de la línea de tiempo, lo que llegue antes.")
        else:
            box.setText("¿Cómo lo pongo en cada marca?")
            b1 = box.addButton("Por partes (recomendado)", QMessageBox.AcceptRole)
            b1.setToolTip("En cada marca va un trozo distinto y seguido del video, con la duración de la frase "
                          "que se dice ahí (2 a 6 s). Ningún tramo se repite; si no caben, se omiten y se avisa.")
            b2 = box.addButton("Entero (hasta la siguiente marca)", QMessageBox.AcceptRole)
            b2.setToolTip("En cada marca, el video desde su principio (tras los logos) hasta la siguiente marca de "
                          "esa palabra, el final del video o el de la línea de tiempo, lo que llegue antes.")
        cancelar = box.addButton("Cancelar", QMessageBox.RejectRole)
        cancelar.setToolTip("No pone nada.")
        box.setDefaultButton(b1)
        box.exec()
        pulsado = box.clickedButton()
        if pulsado is b1:
            return "partes"
        if pulsado is b2:
            return "entero"
        return None

    def _add_at_times(self, ids, times, text: str = ""):
        """🔑 Como «Añadir a la timeline (en el cabezal)», pero en cada marca de palabra clave (un solo Ctrl+Z).
        Si hay videos, pregunta primero cómo ponerlos (por partes o entero)."""
        from ..core.model import KIND_VIDEO as _KV
        modo = "partes"
        if any(self.ctrl.project.media.get(i) is not None and self.ctrl.project.media[i].kind == _KV for i in ids):
            modo = self._pregunta_modo_palabra(len(set(times)) <= 1)
            if modo is None:
                return
        created = self.ctrl.add_media_at_times(ids, times, text, modo=modo)
        if isinstance(created, list) and created:
            self.timeline.set_selection(created)
            n = len(times)
            self.statusBar().showMessage(f"🔑 Añadido en {n} sitio{'s' if n != 1 else ''}. Ctrl+Z lo deshace de "
                                         "una vez.", 6000)

    def _add_moment(self, media_id: str, moment: float):
        """Añade un clip empezando un poco antes de su mejor momento (resultado de la búsqueda IA)."""
        m = self.ctrl.project.media.get(media_id)
        tracks = [t for t in self.ctrl.project.tracks if t.kind == TRACK_VIDEO and not t.locked]
        if m is None or not tracks or m.kind == "audio":
            self._add_at_playhead([media_id])
            return
        src = 0.0 if m.kind == "image" else max(0.0, moment - 1.0)
        dur = 5.0 if m.kind == "image" else max(0.5, min(5.0, m.duration - src))
        created = self.ctrl.insert_ranges([{"media_id": media_id, "start": self.engine.time,
                                            "source_in": src, "duration": dur}],
                                          tracks[-1].id, "Añadir clip (mejor momento)")
        if isinstance(created, list):
            self.timeline.set_selection(created)

    def _split(self):
        """✂ S: corta en el cabezal lo que hay en los canales seleccionados (con su imagen o sonido vinculado); sin
        canal, en toda la línea de tiempo. Como en Resolve: no hace falta tener elegido el trozo concreto."""
        tl, p, t = self.timeline, self.ctrl.project, self.engine.time
        chans = tl.channel_ids()
        ids = None
        if chans:
            under = [c.id for tid in chans for c in p.clips_on(tid) if c.start < t < c.end]
            if not under:
                self.statusBar().showMessage("No hay nada bajo el cabezal en el canal seleccionado. (Clic en la zona "
                                             "vacía de debajo de las pistas = cortar en todos los canales.)", 7000)
                return
            ids = tl._with_links(under, False)
        if self.ctrl.split(t, ids):
            tl.set_selection([])          # (se corta por canal: no queda ningún trozo marcado; el canal, sí)

    def _sync_view_buttons(self, *_a):
        """Las pestañas de vista solo aparecen si hay composición (y marcan la que se ve)."""
        tl = self.timeline
        has = tl.has_comp()
        n = sum(1 for t in self.ctrl.project.tracks if t.role in tl.COMP_ROLES)
        self.view_comp.setText(f"⊞ Pistas de composición ({n})" if n else "⊞ Pistas de composición")
        for b_ in (self.view_main, self.view_comp):
            b_.setVisible(has)
        mode = tl.view_mode()
        self.view_main.setChecked(mode == "main")
        self.view_comp.setChecked(mode == "comp")

    def _comp_drop(self, ids, box):
        """⊞ Archivos soltados en un hueco (o en el fondo) de la composición, desde el cabezal."""
        made = self.ctrl.place_composition(ids, box, self.engine.time)
        if made:
            self.timeline.set_view("comp")             # se ve en su propia línea de tiempo
            self.timeline.set_selection(made)
            self.statusBar().showMessage("⊞ Puesto en la composición" + (" (de fondo)" if box is None else "") +
                                         ": arrástralo en el visor para moverlo · Ctrl+Z lo quita.", 8000)

    def _gap_ai(self, track_id: str, a: float, b: float, apply: bool):
        """💡 / ⚡ en un hueco: el B-roll de la IA solo para ese tramo y en esa pista."""
        ap = self.ai_panel
        i = ap.track.findData(track_id)
        if i >= 0:
            ap.track.setCurrentIndex(i)
        self.show_panel(ap)
        ap.propose((a, b), apply=apply)

    def make_compound(self, ids):
        """⧉ Cocina los clips en un solo video (en segundo plano) y los sustituye en la línea de tiempo."""
        import os
        from ..core import compound as CP
        from ..core.model import new_id
        from .task_window import manager
        try:
            q, a, b = CP.sub_project(self.ctrl.project, ids)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            return
        out = os.path.join(CP.out_dir(), f"compuesto_{new_id()}.mp4")
        n = len(CP.with_partners(self.ctrl.project, ids))
        pp = self.ctrl.project

        def snapshot():
            return sorted((i, round(pp.clips[i].start, 4), round(pp.clips[i].duration, 4), pp.clips[i].media_id)
                          for i in CP.with_partners(self.ctrl.project, ids) if i in self.ctrl.project.clips)
        before = snapshot()

        def work(progress, cancelled):
            return CP.render(q, out, lambda f: progress(f, f"⧉ Cocinando el clip compuesto · {int(f * 100)} %"),
                             cancelled)

        def done(path):
            if snapshot() != before:     # mientras se cocinaba los cambiaste (Remix, Mix, a mano…): no se pisa nada
                self.statusBar().showMessage("⧉ Esos clips cambiaron mientras se cocinaban: no se juntaron "
                                             "(vuelve a pedirlo si quieres).", 9000)
                return
            mids = self.ctrl.import_now([path])
            if not mids:
                self.statusBar().showMessage("✗ No se pudo añadir el clip compuesto.", 8000)
                return
            self.ctrl.set_media_props(mids, category="Clips compuestos")
            cid = self.ctrl.make_compound(ids, mids[0], a, b)
            if cid:
                self.timeline.set_selection([cid])
                self.statusBar().showMessage(f"⧉ {n} clips cocinados en uno ({b - a:.1f} s): el visor va más fluido. "
                                             "Clic derecho → «Deshacer clip compuesto» para volver.", 12000)
        manager().start("⧉ Clip compuesto", work, done,
                        lambda m: self.statusBar().showMessage("✗ " + m, 10000))

    def _delete(self, ripple: bool):
        if self.timeline.delete_transition():                           # transición seleccionada
            return
        if self.timeline.delete_fx():                                   # ✦ pastilla «fx» seleccionada
            return
        if not self.timeline.selected and self.timeline.delete_gap():   # hueco seleccionado
            return
        if self.timeline.selected:
            self.ctrl.delete_clips(sorted(self.timeline.selected), ripple=ripple)

    def remove_black_bars(self):
        """▭ Quitar las barras negras de los videos (los clips seleccionados o, si no hay, todos los de la línea de
        tiempo): se detectan solas (core/black_bars.py) y el clip se encuadra como si el archivo no las tuviera. Un
        Ctrl+Z las devuelve; si ya estaban quitadas en todos, pulsarlo otra vez también las devuelve."""
        from ..core import black_bars as BB
        from ..core.model import KIND_VIDEO as _KV
        from .jobs import BackgroundJob
        p = self.ctrl.project
        sel = [cid for cid in self.timeline.selected if cid in p.clips]
        clips = [c for c in (p.clips[i] for i in (sel or list(p.clips)))
                 if (m := p.media_of(c)) is not None and m.kind == _KV and m.id not in self.ctrl.missing]
        if not clips:
            self.statusBar().showMessage("No hay videos en la línea de tiempo." if not sel
                                         else "Selecciona clips de video.", 5000)
            return
        if all(BB.of(c.layout) for c in clips):          # ya sin barras: devolverlas
            changes = {}
            for c in clips:
                box = {k: v for k, v in (c.layout or {}).items() if k != "bars"}
                changes[c.id] = {"layout": None if box == transform.FULL else box}
            n = self.ctrl.batch_clip_props(changes, "▭ Devolver las barras negras")
            self.statusBar().showMessage(f"▭ Barras negras devueltas en {n} clip(s).", 6000)
            return
        if getattr(self, "_bars_job", None) is not None and self._bars_job.isRunning():
            return
        todo = {}
        for c in clips:
            m = p.media_of(c)
            todo[m.id] = (m.path, float(m.duration or 0.0))
        ids = [c.id for c in clips]

        def work(progress, cancelled):
            out = {}
            for i, (mid, (path, dur)) in enumerate(todo.items()):
                if cancelled():
                    break
                progress(i / max(1, len(todo)), f"▭ Buscando barras negras… {i + 1} de {len(todo)}")
                out[mid] = BB.detect(path, dur)
            return out

        def done(areas):
            pr = self.ctrl.project
            changes = {}
            for cid in ids:
                c = pr.clips.get(cid)
                m = pr.media_of(c) if c else None
                area = areas.get(m.id) if m else None
                if c is not None and area:
                    changes[cid] = {"layout": dict(c.layout or transform.FULL, bars=area)}
            n = self.ctrl.batch_clip_props(changes, "▭ Quitar barras negras") if changes else 0
            none = len(ids) - len(changes)
            self.statusBar().showMessage(
                (f"▭ Barras negras quitadas en {n} clip(s)." if n else "▭ No encontré barras negras.")
                + (f" {none} no tenía(n) barras." if n and none else "") + (" Ctrl+Z las devuelve." if n else ""), 8000)
        self.statusBar().showMessage("▭ Buscando barras negras…")
        self._bars_job = BackgroundJob(work, self)
        self._bars_job.progress.connect(lambda _f, msg: self.statusBar().showMessage(msg))
        self._bars_job.done.connect(done)
        self._bars_job.failed.connect(lambda msg: self.statusBar().showMessage("✗ " + msg, 8000))
        self._bars_job.start()

    def clear_timeline(self, ask: bool = True):
        """🗑 Vaciar la línea de tiempo de un golpe (con Ctrl+Z para volver). Lo bloqueado 🔒 se queda."""
        p = self.ctrl.project
        if not p.clips and not p.markers:
            self.statusBar().showMessage("La línea de tiempo ya está vacía.", 4000)
            return
        if ask and QMessageBox.question(
                self, "Vaciar la línea de tiempo",
                f"¿Quitar TODO de la línea de tiempo ({len(p.clips)} clips, textos y marcadores)?" + chr(10) * 2 +
                "Tus archivos siguen en Medios y Ctrl+Z lo devuelve todo.") != QMessageBox.Yes:
            return
        self.engine.pause()

        def fn(pr):
            keep = {c.id for c in pr.clips.values() if c.locked or (pr.track(c.track_id) and pr.track(c.track_id).locked)}
            pr.clips = {i: c for i, c in pr.clips.items() if i in keep}
            pr.markers, pr.annotations, pr.edits = [], [], []
            return len(keep)
        kept = self.ctrl._edit("🗑 Vaciar la línea de tiempo", fn)
        self.timeline.set_selection([])
        self.engine.user_seek(0.0)
        self.statusBar().showMessage("🗑 Línea de tiempo vacía" + (f" (quedan {kept} clips bloqueados 🔒)" if kept else "")
                                     + ". Ctrl+Z lo devuelve.", 8000)

    def _toggle_lock(self):
        ids = sorted(self.timeline.selected)
        if ids:
            lock = not all(self.ctrl.project.clips[i].locked for i in ids)
            self.ctrl.set_clip_props(ids, "Bloquear clip" if lock else "Desbloquear clip", locked=lock)

    def separate_dialogue(self, clip_ids: list):
        """🗣 Los clips de sonido elegidos suenan solo con los diálogos (Demucs, en segundo plano)."""
        from ..ai import dialogue
        from .task_window import manager
        p = self.ctrl.project
        mids = {p.clips[i].media_id for i in clip_ids if i in p.clips}
        files = {mid: p.media[mid].path for mid in mids if mid in p.media}

        def work(progress, cancelled):
            out = {}
            for k, (mid, path) in enumerate(files.items()):
                out[mid] = dialogue.isolate(path, lambda f, t, k=k: progress((k + f) / max(1, len(files)), t),
                                            cancelled)
            return out

        def done(paths):
            voice = {}
            for mid, wav in paths.items():
                got = self.ctrl.import_now([wav])
                if got:
                    self.ctrl.set_media_props(got, category="Diálogos (IA)")
                    voice[mid] = got[0]
            try:
                n = self.ctrl.use_dialogue(clip_ids, voice)
                self.statusBar().showMessage(f"🗣 {n} clip(s) con solo los diálogos. Ctrl+Z vuelve al original.", 9000)
            except Exception as exc:  # noqa: BLE001 - EditError
                self.statusBar().showMessage(str(exc), 8000)
        manager().start("🗣 Separar diálogos", work, done, lambda m: self.statusBar().showMessage("✗ " + m, 9000))

    def open_topics_tool(self, label: str = ""):
        """◎ Con los temas de la narración: quedarte solo con unos en la línea de tiempo y/o guardar cada tramo
        como un video en Medios (carpeta «Temas · …», con el tema como palabra clave para buscarlo luego)."""
        from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QVBoxLayout
        segs = self.ctrl.topic_segments()
        if not segs:
            self.statusBar().showMessage("No hay temas: pestaña IA ✨ → Temas → «Detectar temas».", 6000)
            return
        stats: dict[str, list[float]] = {}
        for lab, a, b in segs:
            stats.setdefault(lab, []).append(b - a)
        dlg = QDialog(self)
        dlg.setWindowTitle("◎ Temas")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("¿Con qué temas te quedas?"))
        boxes = {}
        for lab, durs in stats.items():
            cb = QCheckBox(f"{lab.title()}   ·  {len(durs)} tramo(s), {sum(durs) / 60:.1f} min")
            cb.setChecked(lab == label or not label)
            lay.addWidget(cb)
            boxes[lab] = cb
        b_keep = QPushButton("Quedarme solo con estos en la línea de tiempo")
        b_media = QPushButton("Mandar estos tramos a Medios (por si los ocupo luego)")
        b_both = QPushButton("Las dos cosas")
        b_both.setObjectName("primary")
        for b in (b_media, b_keep, b_both):
            lay.addWidget(b)
        choice = {}
        b_keep.clicked.connect(lambda: (choice.update(k=True), dlg.accept()))
        b_media.clicked.connect(lambda: (choice.update(m=True), dlg.accept()))
        b_both.clicked.connect(lambda: (choice.update(k=True, m=True), dlg.accept()))
        if not dlg.exec():
            return
        labels = {lab for lab, cb in boxes.items() if cb.isChecked()}
        if not labels:
            return
        if choice.get("m"):
            self.topics_to_media(labels)          # primero: copia de los tramos tal como están ahora
        if choice.get("k"):
            n = self.ctrl.keep_topics(labels)
            if n:
                self.statusBar().showMessage(f"◎ Te quedaste con {n} tramo(s) de: "
                                             + ", ".join(sorted(x.title() for x in labels)) + ". Ctrl+Z vuelve.",
                                             9000)

    def topics_to_media(self, labels):
        """Cada tramo de esos temas, a un video en Medios (en segundo plano), en «Temas · <tema>»."""
        from ..core import compound as CP
        from ..core.paths import app_data_dir
        from ..core.project_tools import slice_project
        from .task_window import manager
        p = self.ctrl.project
        segs = self.ctrl.topic_segments(set(labels))
        folder = app_data_dir() / "segmentos_temas"
        folder.mkdir(parents=True, exist_ok=True)
        jobs, count = [], {}
        stem = os.path.splitext(p.name)[0][:40] or "proyecto"
        for lab, a, b in segs:
            count[lab] = count.get(lab, 0) + 1
            out = str(folder / f"{stem} - {lab.title()} {count[lab]:02d}.mp4")
            jobs.append((lab, slice_project(p, a, b), out))      # copia de AHORA: aunque luego edites

        def work(progress, cancelled):
            made = []
            for i, (lab, q, out) in enumerate(jobs):
                CP.render(q, out, lambda f, i=i, lab=lab: progress(
                    (i + f) / len(jobs), f"◎ {lab.title()} {i + 1}/{len(jobs)} · {int(f * 100)} %"), cancelled)
                made.append((lab, out))
            return made

        def done(made):
            for lab, path in made:
                ids = self.ctrl.import_now([path])
                if ids:
                    self.ctrl.set_media_props(ids, category=f"Temas · {lab.title()}", tags=[lab.lower()])
            self.statusBar().showMessage(f"◎ {len(made)} tramo(s) en Medios, en «Temas · …». Búscalos por su tema.",
                                         10000)
        manager().start(f"◎ Mandar {len(jobs)} tramo(s) a Medios", work, done,
                        lambda m: self.statusBar().showMessage("✗ " + m, 9000))

    def cut_scenes(self, clip_ids: list, sensitivity: str = "normal", markers: bool = False):
        """✂ Corta los clips en cada cambio de escena (sin IA: la imagen cambia de golpe). En segundo plano."""
        from ..core import scene_cuts
        from .task_window import manager
        p = self.ctrl.project
        jobs = []
        for cid in clip_ids:
            c = p.clips.get(cid)
            m = p.media_of(c) if c else None
            if c is None or m is None or c.speed <= 0:
                continue
            a, b = sorted((c.src_at(0.0), c.src_at(c.duration)))
            jobs.append((cid, m.path, a, b))
        if not jobs:
            return

        def work(progress, cancelled):
            out = {}
            for k, (cid, path, a, b) in enumerate(jobs):
                out[cid] = scene_cuts.detect(path, a, b, sensitivity,
                                             lambda f, k=k: progress((k + f) / len(jobs), "✂ Buscando cambios de "
                                                                     f"escena · {int(100 * (k + f) / len(jobs))} %"),
                                             cancelled)
            return out

        def done(cuts):
            from ..core import mapping
            n = 0
            all_times = []
            for cid, src in cuts.items():
                cc = self.ctrl.project.clips.get(cid)
                if not src or cc is None:
                    continue
                times = [t for s in src if (t := mapping.map_time(self.ctrl.project, cc.media_id, s, [cc])) is not None]
                if markers:
                    all_times += times
                elif times:
                    n += self.ctrl.split_at_times(cid, times) or 0
            if markers and all_times:
                self.ctrl.add_markers(all_times)
                self.statusBar().showMessage(f"⚑ {len(all_times)} marcadores en los cambios de escena.", 9000)
            elif n:
                self.statusBar().showMessage(f"✂ {n} cortes en los cambios de escena. Ctrl+Z los quita.", 9000)
            else:
                self.statusBar().showMessage("No hay cambios de escena claros ahí (prueba «También cambios más "
                                             "suaves»).", 8000)
        manager().start("✂ Cambios de escena", work, done, lambda m: self.statusBar().showMessage("✗ " + m, 8000))

    def read_obs_marks(self, media_ids: list | None = None):
        """🔖 Marcas de OBS (capítulos del MP4) → marcadores rojos; ver ui/obs_marks_ui.py."""
        from .obs_marks_ui import leer_marcas
        leer_marcas(self, media_ids or None)

    def open_obs_fallos(self):
        from .obs_marks_ui import abrir_fallos
        abrir_fallos(self)

    def open_keywords(self, media_ids: list | None = None, scope: str = "timeline"):
        """🔑 Buscar palabras clave en el audio (ligero)."""
        from .keywords_dialog import KeywordsDialog
        dlg = KeywordsDialog(self, scope, media_ids)
        dlg.show()
        dlg.raise_()
        self._kw_dialog = dlg

    def burst(self, bars: int, per_beat: int):
        """⚡ Ráfaga: bars compases desde el cabezal (0 = entre las marcas I–O), per_beat cortes por golpe."""
        from ..core.controller import EditError
        p = self.ctrl.project
        if bars <= 0:
            if p.mark_in is None or p.mark_out is None or p.mark_out <= p.mark_in:
                self.statusBar().showMessage("⚡ Marca antes la entrada y la salida (I y O) del tramo.", 6000)
                return
            a, b = p.mark_in, p.mark_out
        else:
            t = self.engine.time
            beats = self.ctrl.song_beats(t - 2.0, t + 60.0)
            if len(beats) < 2:
                self.statusBar().showMessage("⚡ La ráfaga va al ritmo de la canción: pon antes una canción en una "
                                             "pista de audio (y espera a que se reconozca su ritmo 🥁).", 8000)
                return
            i = min(range(len(beats)), key=lambda k: abs(beats[k] - t))     # desde el golpe más cercano
            j = min(len(beats) - 1, i + 4 * bars)
            a, b = beats[i], beats[j]
        try:
            n = self.ctrl.burst_cuts(a, b, per_beat, sorted(self.timeline.selected))
        except EditError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        if n:
            self.statusBar().showMessage(f"⚡ Ráfaga: {n} cortes al ritmo de la canción. Ctrl+Z la deshace.", 7000)

    def open_voice_record(self):
        """🎙 Grabar la voz en off mientras ves el video (la toma cae en la pista de voz, en el cabezal)."""
        from .voice_record import VoiceRecordDialog
        dlg = getattr(self, "_voice_rec", None)
        try:
            if dlg is not None and dlg.isVisible():
                dlg.raise_()
                dlg.activateWindow()
                return
        except RuntimeError:
            pass
        self._voice_rec = VoiceRecordDialog(self)
        self._voice_rec.setAttribute(Qt.WA_DeleteOnClose)
        self._voice_rec.show()

    def open_chapters(self):
        """📑 Capítulos para la descripción de YouTube (desde los marcadores o los temas)."""
        from .description_dialog import DescriptionDialog
        DescriptionDialog(self).exec()

    def export_frame(self):
        """📸 El fotograma del cabezal como PNG, tal como saldrá en el video (y copiado al portapapeles)."""
        from ..core import media as media_tools
        from ..core.still import render_frame
        from .common import fmt_tc
        from .export_dialog import _default_export_dir
        from .task_window import manager
        p = self.ctrl.project
        if p.duration() <= 0:
            self.statusBar().showMessage("📸 La línea de tiempo está vacía.", 5000)
            return
        t = self.engine.time
        folder = os.path.dirname(self.ctrl.path) if self.ctrl.path else _default_export_dir()
        stamp = fmt_tc(t, p.fps).replace(":", "-")
        out = os.path.join(folder, f"{p.name} {stamp}.png")
        snap = p.__class__.from_dict(p.to_dict())        # una copia: puedes seguir editando mientras se hace

        def done(path):
            from PySide6.QtGui import QImage
            img = QImage(path)
            if not img.isNull():
                QApplication.clipboard().setImage(img)
            self.statusBar().showMessage(f"📸 Fotograma guardado en {path} (y copiado: Ctrl+V para pegarlo).", 10000)

        def fail(msg):
            self.statusBar().showMessage(f"✗ No se pudo exportar el fotograma: {msg[:150]}", 9000)
        manager().start("📸 Exportar fotograma", lambda _p, _c: render_frame(snap, t, out, media_tools.ffmpeg()),
                        done, fail)

    def open_silhouette_teach(self, clip_id: str | None = None):
        """👤 Enseñar un personaje por su silueta (clic encima en un fotograma del clip)."""
        from ..core.model import KIND_VIDEO as _KV
        from .silhouette_teach import SilhouetteTeachDialog
        p = self.ctrl.project
        t = self.engine.time
        if clip_id is None:
            cands = [p.clips[i] for i in sorted(self.timeline.selected) if i in p.clips]
            cands += sorted((c for c in p.clips.values() if c.start <= t < c.end), key=lambda c: c.track_id)
            cands = [c for c in cands if c.text is None and p.media_of(c) is not None and p.media_of(c).kind == _KV]
            clip_id = cands[0].id if cands else None
        if clip_id is None:
            self.statusBar().showMessage("👤 Pon el cabezal (o selecciona) un clip de video donde salga el personaje.",
                                         7000)
            return
        try:
            SilhouetteTeachDialog(self, clip_id, t).exec()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Enseñar personaje", str(exc))

    def open_subject_fx(self, clip_id: str | None = None):
        """✨ Efectos solo al personaje (la IA lo recorta y lo sigue en todo el clip)."""
        self.open_subject_cut(clip_id, fx_mode=True)

    def open_subject_cut(self, clip_id: str | None = None, fx_mode: bool = False):
        """✂ Recortar sujeto / quitar el fondo con IA (SAM 2.1) en un clip de video."""
        from ..core.model import KIND_VIDEO as _KV
        from .subject_cut_dialog import SubjectCutDialog
        p = self.ctrl.project
        if clip_id is None:
            sel = [p.clips[i] for i in sorted(self.timeline.selected) if i in p.clips]
            sel = [c for c in sel if p.media_of(c) is not None and p.media_of(c).kind == _KV]
            clip_id = sel[0].id if sel else None
        if clip_id is None:
            self.statusBar().showMessage("✂ Selecciona antes el clip de video donde está lo que quieres recortar.", 7000)
            return
        try:
            SubjectCutDialog(self.ctrl, clip_id, self.engine.time, self, fx_mode=fx_mode).exec()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Recortar sujeto", str(exc))

    def _ai_card(self, key: str):
        """Tarjetas del mapa de la IA que abren otra herramienta."""
        if key == "cutout":
            self.open_subject_cut()
            return
        if key == "compare":
            self.open_compare()
            return
        if key == "keywords":
            self.open_keywords()
            return
        if key == "auto":
            self.open_auto()
        elif key == "understand":
            self.open_understand()
        elif key == "moments":
            self.open_moments("")
        elif key == "voice":
            self.show_panel(self.voice)
        elif key == "edit":
            self.open_edit_maker()
        elif key == "audit":
            self.open_audit()

    def open_thumbnail(self, fmt: str | None = None):
        """🖼 La página «Miniatura» (como las páginas de Resolve): el taller ocupa toda la ventana, en lugar de los
        paneles del editor (el usuario: «que no sea una ventanilla… una página normal dentro del editor»). Al volver
        a otra página (o ed.close()), todo queda como estaba y la miniatura se guarda con el proyecto."""
        from PySide6.QtGui import QAction, QShortcut
        from .thumbnail_editor import ThumbnailEditor
        self.engine.pause()
        ed = getattr(self, "_thumb_editor", None)
        if ed is None or getattr(ed, "_gone", False):
            ed = self._thumb_editor = ThumbnailEditor(self, fmt)
            ed.setWindowFlags(Qt.Widget)
            ed.closed.connect(self._leave_thumb_page)
            self.central_stack.addWidget(ed)
        elif fmt and ed.fmt.findData(fmt) >= 0 and ed.fmt.currentData() != fmt:
            ed.fmt.setCurrentIndex(ed.fmt.findData(fmt))
        if self._thumb_page is None:
            # los paneles del editor se apartan (se recuerda dónde estaban) y sus atajos también, para que Ctrl+Z,
            # Supr, Ctrl+D… sean los del taller (con los dos activos, Qt no hace ninguno)
            acts = [a for a in self.findChildren(QAction) if a.shortcuts() and not self._in_thumb(a)]
            shorts = [s for s in self.findChildren(QShortcut) if s.isEnabled() and not self._in_thumb(s)]
            self._thumb_page = {"state": self.saveState(3), "acts": [(a, a.shortcutContext()) for a in acts],
                                "shorts": shorts}
            for key, d in self.docks.items():
                if key != "guide" and not d.isFloating():   # (la 📖 guía y lo flotante se quedan a la vista)
                    d.hide()
            for a in acts:
                a.setShortcutContext(Qt.WidgetShortcut)
            for s in shorts:
                s.setEnabled(False)
        self.central_stack.setCurrentWidget(ed)
        ed.show()
        ed.setFocus()
        for k, b in self.page_buttons.items():
            b.setChecked(k == "thumb")
        return ed

    def _in_thumb(self, obj) -> bool:
        ed = getattr(self, "_thumb_editor", None)
        o = obj
        while o is not None:
            if o is ed:
                return True
            o = o.parent()
        return False

    def _leave_thumb_page(self, back_to: str = "edit"):
        """Salir de la página Miniatura: el editor vuelve tal cual (paneles, atajos)."""
        st, self._thumb_page = self._thumb_page, None
        ed = getattr(self, "_thumb_editor", None)
        self.central_stack.setCurrentWidget(self.preview)
        if ed is not None:
            ed._gone = True
            self.central_stack.removeWidget(ed)
            ed.deleteLater()
            self._thumb_editor = None
        if st is not None:
            self.restoreState(st["state"], 3)
            for a, ctx in st["acts"]:
                try:
                    a.setShortcutContext(ctx)
                except RuntimeError:
                    pass
            for s in st["shorts"]:
                try:
                    s.setEnabled(True)
                except RuntimeError:
                    pass
        for k, b in self.page_buttons.items():
            b.setChecked(k == back_to)

    def open_moments(self, text: str = "", at: float | None = None):
        """Abre el buscador de momentos (y busca, si se da un texto). at = dónde insertar lo elegido."""
        self.show_panel(self.moments)
        if text:
            self.moments.search_for(text, at)
        else:
            self.moments.query.setFocus()

    def add_impact(self, clip_ids: list[str]):
        """Más impacto visual solo en esos clips: zooms de golpe en los cortos, zoom lento en los largos."""
        from ..ai.first_version import cinematic_changes
        p = self.ctrl.project
        changes = cinematic_changes(p, clip_ids, [], ken=True, dips=False, fade_ends=False,
                                    punch_every=1)   # (lo elegido, TODO con impacto: zoom de golpe a cada clip corto)
        if not changes:
            self.ctrl.message.emit("Esos clips ya tienen zoom: quítalo antes (Inspector → Video) si quieres otro.")
            return
        n = self.ctrl.batch_clip_props(changes, "IA · Más impacto visual")
        self.ctrl.message.emit(f"⚡ Más impacto en {n} clip(s): zooms de golpe y zoom lento. Ctrl+Z para deshacer.")

    def find_similar(self, clip_id: str):
        """Busca en los medios momentos parecidos a lo que se ve en un clip (en el cabezal o su centro)."""
        p = self.ctrl.project
        c = p.clips.get(clip_id)
        m = p.media_of(c) if c else None
        if c is None or m is None or m.kind == "audio":
            return
        t = self.engine.time if c.start <= self.engine.time < c.end else c.start + c.duration / 2
        src = 0.0 if m.kind == "image" else self.ctrl.clip_source_time(c.id, t)
        from ..core.paths import temp_dir as _temp_dir
        ref = os.path.join(str(_temp_dir()), "reclaimer_referencia.jpg")
        from ..core import media as media_tools
        media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{src:.2f}", "-i", m.path,
                               "-frames:v", "1", ref], timeout=30)
        from ..ai.library_understanding import _deep_path
        try:
            os.remove(_deep_path(ref))   # la referencia cambia cada vez: sin caché
        except OSError:
            pass
        self.show_panel(self.moments)
        self.moments.search_image(ref, label=f"parecido a «{m.name}» ({src:.0f} s)")

    def open_understand(self):
        from .understand_dialog import UnderstandDialog
        self.engine.pause()
        UnderstandDialog(self.ctrl, self).exec()
        self.ai_panel.refresh()
        self.moments.refresh_known()

    def open_auto(self):
        from .auto_dialog import AutoDialog
        if self.voice.job is not None or self.ai_panel.job is not None:
            QMessageBox.information(self, "Primera versión automática",
                                    "Espera a que termine la tarea de IA que está en marcha.")
            return
        self.engine.pause()
        AutoDialog(self).exec()

    def open_tasks(self):
        """◈ Tareas de la IA: al lado del visor (o donde lo hayas arrastrado)."""
        d = self.docks["tasks"]
        d.show()
        d.raise_()

    def open_shortcuts(self):
        from .shortcuts_dialog import ShortcutsDialog
        self.engine.pause()
        ShortcutsDialog(self.shortcut_actions, self).exec()

    def _fit_to_screen(self):
        """La ventana siempre dentro de lo que se ve (encima de la barra de tareas de Windows)."""
        scr = self.screen() or QApplication.primaryScreen()
        if scr is None or self.isMaximized():
            return
        av = scr.availableGeometry()
        fr = self.frameGeometry()
        if not av.contains(fr):
            w, h = min(fr.width(), av.width()), min(fr.height(), av.height())
            if w >= av.width() - 40 or h >= av.height() - 40:
                self.setWindowState(Qt.WindowMaximized)
            else:
                self.resize(w - (fr.width() - self.width()), h - (fr.height() - self.height()))
                self.move(max(av.left(), min(fr.left(), av.right() - w)), max(av.top(), min(fr.top(), av.bottom() - h)))

    def timeline_natural_height(self) -> int:
        """Lo que necesita la línea de tiempo para que se vean TODAS sus pistas sin desplazarte: barra de
        herramientas + regla + pistas + barra de desplazamiento + título del panel."""
        d = self.docks["timeline"]
        n = len(self.ctrl.project.tracks)
        title = max(0, d.height() - self.timeline_box.height()) or 22
        tb = self.timeline_box.layout().itemAt(0).widget().sizeHint().height()
        return int(title + tb + self.timeline.track_y(n) + self.timeline.NEW_ZONE + 8 + self.hbar.sizeHint().height())

    def _ensure_timeline_size(self):
        """Al abrir, la línea de tiempo siempre con su altura natural (todas las pistas a la vista), sin
        comerse el visor: entre el 22 % y el 50 % de la ventana."""
        d = self.docks.get("timeline")
        if d is None or not d.isVisible() or d.isFloating():
            return
        h = self.height()
        target = max(int(h * 0.22), min(int(h * 0.5), self.timeline_natural_height()))
        if abs(d.height() - target) > 6:
            self.resizeDocks([d], [target], Qt.Vertical)

    def _apply_dock_sizes(self):
        """Tamaños de la distribución inicial con la ventana ya abierta (antes, la línea de tiempo salía
        aplastada porque se calculaba cuando la ventana aún no tenía su tamaño)."""
        d = self.docks
        h, w = max(600, self.height()), max(900, self.width())
        self.resizeDocks([d["timeline"]], [max(int(h * 0.22), min(int(h * 0.5), self.timeline_natural_height()))],
                         Qt.Vertical)
        self.resizeDocks([d["media"], d["inspector"]], [int(w * 0.24), int(w * 0.26)], Qt.Horizontal)

    SIDE_MIN = 300          # ancho cómodo mínimo de los paneles de los lados al abrir

    def _ensure_side_widths(self):
        """Los paneles de los lados (Medios, Inspector…) con un ancho cómodo al abrir: si una distribución guardada los
        dejó en una tira («M…», «E…»), se ensanchan solos. El usuario: «no me gusta tener que estar moviendo las
        barras para que se vean las cosas del lado derecho y del lado izquierdo»."""
        w = self.width()
        if w < 1000:
            return
        for area, frac in ((Qt.LeftDockWidgetArea, 0.24), (Qt.RightDockWidgetArea, 0.26)):
            shown = [d for d in self.docks.values() if d.isVisible() and not d.isFloating()
                     and self.dockWidgetArea(d) == area]
            if shown and min(d.width() for d in shown) < self.SIDE_MIN:
                self.resizeDocks(shown, [max(self.SIDE_MIN, int(w * frac))] * len(shown), Qt.Horizontal)

    def _learning_badge(self):
        from .theme import glyph_icon
        L = self.learner                              # el punto, con su color: verde = aprendiendo
        state = "apagado" if not L.enabled else ("pausa" if L.paused else "aprendiendo")
        col = {"apagado": "#71747d", "pausa": "#e3b341", "aprendiendo": "#3ecf8e"}[state]
        self.btn_learning.setIcon(glyph_icon("⏸" if state == "pausa" else "●", 12, col, col))
        self.btn_learning.setText("Aprendizaje IA")
        self.btn_learning.setProperty("estado", state)

    def open_learning(self):
        from .learning import LearningDialog
        if getattr(self, "_learning_dlg", None) is None:
            self._learning_dlg = LearningDialog(self.learner, self)
        self._learning_dlg.refresh()
        self._learning_dlg.show()
        self._learning_dlg.raise_()
        self._learning_dlg.activateWindow()

    def open_edit_maker(self):
        from .edit_dialog import EditDialog
        self.engine.pause()
        if self.workspaces.current != "edit" and not self.ctrl.project.clips:
            self.workspaces.switch("edit")         # 🗂 los edits van en su pestaña (la actual queda guardada)
        if self.ctrl.project.format != "edit" and not self.ctrl.project.clips:
            self.ctrl.set_project_format("edit")   # proyecto vacío: directamente en vertical
        EditDialog(self.ctrl, self).exec()
        self.timeline.fit()

    def open_compare(self):
        from .compare_dialog import CompareDialog
        self.engine.pause()
        CompareDialog(self.ctrl, self.engine.time, self).exec()

    def open_tracking(self, clip_id: str):
        from ..ai.tracking import is_available
        from .tracking_dialog import TrackingDialog
        ok, why = is_available()
        if not ok:
            QMessageBox.warning(self, "Seguir", why)
            return
        self.engine.pause()
        c = self.ctrl.project.clips.get(clip_id)
        if c is None:
            return
        t = min(max(self.engine.time, c.start), c.end - 0.1)
        try:
            TrackingDialog(self.ctrl, clip_id, t, self).exec()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Seguir", str(exc))

    def _update_framing_mode(self, ids):
        """Con un clip de video/imagen seleccionado, el visor sirve para encuadrarlo."""
        ids = list(self.inspector._ids)   # una imagen con su sonido vinculado cuenta como uno
        c = self.ctrl.project.clips.get(ids[0]) if len(ids) == 1 else None
        m = self.ctrl.project.media_of(c) if c else None
        tr = self.ctrl.project.track(c.track_id) if c else None
        self.preview.canvas.set_framing_enabled(bool(m and m.kind != "audio" and tr and tr.kind != TRACK_AUDIO))
        self._update_region_edit()
        self._update_transform_edit()

    def _update_transform_edit(self):
        """⤧ Como en Resolve: el clip seleccionado (si se ve en el cabezal) muestra su caja para moverla y
        cambiarle el tamaño en el visor; cada capa es independiente y deja ver las de debajo."""
        canvas = self.preview.canvas
        c = None
        if canvas.framing_enabled:
            ids = list(self.inspector._ids)
            c = self.ctrl.project.clips.get(ids[0]) if len(ids) == 1 else None
            t = self.engine.time
            if c is not None and not (c.start - 1e-3 <= t < c.end):
                c = None
        lay = None
        if c is not None:
            from ..core import transform as _TR
            from ..core.model import KIND_IMAGE as _KI
            m_ = self.ctrl.project.media_of(c)
            lay = _TR.layout_at(c, self.engine.time - c.start, bool(m_ and m_.kind == _KI))   # 🎞 la de ahora
        canvas.set_transform_edit(c.id if c else None, lay)
        # 🔍 zoom dinámico: los rectángulos de inicio y final sobre la imagen entera
        dz = None
        if c is not None and canvas.mode == "dynzoom" and c.text is None:
            layer = canvas.layers.get(c.track_id)
            content = getattr(layer, "content_rect", None) if layer is not None else None
            if content is not None:
                kf = sorted(c.zoom_kf or [], key=lambda k: k["t"])
                if len(kf) >= 2:
                    wa = transform.window(kf[0]["z"], kf[0]["x"], kf[0]["y"])
                    wb = transform.window(kf[-1]["z"], kf[-1]["x"], kf[-1]["y"])
                    ra, rb = {"x": wa[0], "y": wa[1], "s": wa[2]}, {"x": wb[0], "y": wb[1], "s": wb[2]}
                else:
                    ra, rb = {"x": 0.0, "y": 0.0, "s": 1.0}, {"x": 0.15, "y": 0.15, "s": 0.7}
                dz = (layer.box.mapRectToScene(content), ra, rb)
        canvas.set_dynzoom_edit(c.id if dz else None, dz[0] if dz else None, dz[1] if dz else None,
                                dz[2] if dz else None)
        t = self.engine.time
        canvas.set_annotations([a for a in self.ctrl.project.annotations
                                if a["t"] - 1e-3 <= t < a["t"] + a.get("dur", 3.0)])

    def _dynzoom_done(self, clip_id: str, a: dict, b: dict):
        """🔍 Zoom dinámico: del rectángulo verde (al empezar el clip) al rojo (al acabar), suave."""
        c = self.ctrl.project.clips.get(clip_id)
        m = self.ctrl.project.media_of(c) if c else None
        if c is None or m is None:
            return
        if m.kind == "image":
            t0, t1 = 0.0, c.duration
        else:
            t0, t1 = sorted((c.src_at(0.0), c.src_at(c.duration)))
        kf = [{"t": round(t, 3), "z": round(1.0 / max(0.05, r["s"]), 4), "x": round(r["x"] + r["s"] / 2, 4),
               "y": round(r["y"] + r["s"] / 2, 4)} for t, r in ((t0, a), (t1, b))]
        self.ctrl.set_clip_props([clip_id], "🔍 Zoom dinámico", zoom_kf=kf)

    def _annotation_added(self, item: dict):
        t = self.engine.time

        def fn(p):
            p.annotations.append(dict(item, t=round(t, 3), dur=3.0))
        self.ctrl._edit("✏ Anotación", fn)

    def _clear_annotations(self):
        t = self.engine.time

        def fn(p):
            p.annotations = [a for a in p.annotations if not (a["t"] - 1e-3 <= t < a["t"] + a.get("dur", 3.0))]
        self.ctrl._edit("Borrar anotaciones", fn)

    def follow_action(self, clip_ids: list[str]):
        """🎯 Clips horizontales en un Short/edit: llenan la pantalla vertical y el recorte sigue la acción
        (en segundo plano; cada clip, su propio paso de Ctrl+Z)."""
        from ..ai import reframe
        from .jobs import BackgroundJob
        p = self.ctrl.project
        jobs = []
        for cid in clip_ids:
            c = p.clips.get(cid)
            m = p.media_of(c) if c else None
            if c is None or m is None:
                continue
            box = c.layout or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
            aspect = (box.get("w", 1.0) * p.width) / max(1e-6, box.get("h", 1.0) * p.height)
            a, b = sorted((c.source_in, c.source_in + c.src_len))
            jobs.append((cid, m.path, a, b, m.width, m.height, aspect))
        if not jobs:
            return

        def work(progress, cancelled):
            out = {}
            for k, (cid, path, a, b, w, h, aspect) in enumerate(jobs):
                def prog(f, t, k=k):
                    progress((k + f) / len(jobs), t)
                out[cid] = reframe.follow_path(path, a, b, w, h, aspect, prog, cancelled)
            return out

        def done(res):
            n = 0
            for cid, kf in res.items():
                if cid in self.ctrl.project.clips and kf:
                    self.ctrl.set_follow(cid, kf)
                    n += 1
            self.engine._sync()
            self.ctrl.message.emit(f"🎯 Encuadre vertical que sigue la acción en {n} clip(s). Si no te gusta: "
                                   "Ctrl+Z o clic derecho → «Quitar «sigue la acción»»." if n else
                                   "🎯 Ese clip ya se ve entero en vertical: no hay nada que seguir.")
        job = BackgroundJob(work, self)
        job.title = "🎯 Encuadre que sigue la acción"
        job.done.connect(done)
        job.failed.connect(lambda msg: self.ctrl.message.emit(f"🎯 No se pudo: {msg}"))
        self._follow_job = job
        self.ctrl.message.emit("🎯 Mirando dónde está la acción… (puedes seguir editando)")
        job.start()

    def open_mix(self):
        """🎛 La IA propone cómo debe ir la música (tramo a tramo, con su motivo); no cambia nada hasta que aceptas."""
        from .mix_dialog import MixDialog
        MixDialog(self).exec()

    def open_collect(self):
        """📦 Copia del proyecto con todos sus archivos en una carpeta (respaldo / otro disco / otro PC)."""
        from .collect_dialog import CollectDialog
        CollectDialog(self).exec()

    def open_generator(self, gen: dict | None = None, clip_ids: list[str] | None = None):
        """🟦 Color sólido o degradado (nuevo en el cabezal, o cambiar el de esos clips)."""
        from .generator_dialog import GeneratorDialog
        GeneratorDialog(self, gen, clip_ids).exec()

    def add_adjustment(self):
        """🎨 Capa de ajuste en el cabezal (5 s, encima de todo): lo que le pongas (color, efectos) se aplica a todo lo
        de debajo mientras dura."""
        made = self.ctrl.add_generator({"kind": "adjust"}, self.engine.time, 5.0)
        if made:
            self.timeline.set_selection([made])
            self.ctrl.message.emit("🎨 Capa de ajuste añadida: ponle color o efectos en el Inspector y se aplican a "
                                   "todo lo que hay debajo. Alárgala o acórtala como cualquier clip.")

    def _clip_on_track_now(self, track_id: str) -> str | None:
        from ..core import generators as _G
        p = self.ctrl.project
        c = p.clip_at(track_id, self.engine.time)
        if c is None or not c.enabled or c.text is not None or _G.is_adjust(p.media_of(c)):
            return None
        return c.id

    def _pick_from_viewer(self, clip_id: str):
        tl = self.timeline
        tl.set_selection(self.ctrl.linked_ids([clip_id]) if tl.linked else [clip_id])

    def _tf_live(self, clip_id: str, box: dict):
        c = self.ctrl.project.clips.get(clip_id)
        if c is not None:              # solo para verlo mientras arrastras (se guarda al soltar, con Ctrl+Z)
            if c.layout_kf:            # 🎞 animado: una caja provisional (las claves no se tocan hasta soltar)
                from ..core import transform as _TR
                _TR.LIVE[c.id] = dict(box)
            else:
                c.layout = dict(box)
            self.engine._sync()

    def _tf_done(self, clip_id: str, orig, box):
        c = self.ctrl.project.clips.get(clip_id)
        if c is None:
            return
        from ..core import transform as _TR
        _TR.LIVE.pop(clip_id, None)
        if c.layout_kf:          # 🎞 animado: lo que haces en el visor es la clave de ESTE momento
            self.ctrl.set_layout_key(clip_id, self.engine.time, dict(box) if box else dict(_TR.FULL),
                                     "Mover / escalar (clave)")
            self.engine._sync()
            return
        c.layout = dict(orig) if orig else None        # lo de antes, para que Ctrl+Z vuelva ahí
        self.ctrl.set_clip_props([clip_id], "Mover / escalar en el visor" if box else "Pantalla completa",
                                 layout=dict(box) if box else None)
        self.engine._sync()

    def _update_region_edit(self):
        """Con un clip seleccionado que tiene desenfoque por zonas, el visor muestra las zonas para arrastrarlas."""
        from ..core import effects
        ids = list(getattr(self.inspector, "_ids", []) or [])
        c = self.ctrl.project.clips.get(ids[0]) if len(ids) == 1 else None
        regions = effects.blur_regions(c.fx) if c else []
        self.preview.canvas.set_region_edit(c.id if c else None, c.track_id if c else None, regions)

    def _on_region_changed(self, clip_id: str, regions: list):
        c = self.ctrl.project.clips.get(clip_id)
        if c is None:
            return
        fx = dict(c.fx or {})
        fx["blur_regions"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                              for r in regions]
        self.ctrl.set_clip_props([clip_id], "Mover desenfoque", fx=fx)

    def _on_timeline_suggestion(self, sid: str):
        self.right_tabs.setCurrentWidget(self.voice)
        s = next((s for s in self.ctrl.project.suggestions if s.id == sid), None)
        if s is None:
            return
        if self.voice.f_status.currentData() not in ("", s.status) or \
                self.voice.f_kind.currentData() not in ("", s.kind):
            self.voice.f_status.setCurrentIndex(self.voice.f_status.findData(""))
            self.voice.f_kind.setCurrentIndex(0)
        self.voice.select_suggestion(sid)

    def _marker(self):
        self.ctrl.add_marker(self.engine.time)

    def _show_shortcuts(self):
        box = QMessageBox(self)
        box.setWindowTitle("Atajos de teclado")
        box.setTextFormat(Qt.RichText)
        box.setText(SHORTCUTS_HELP)
        box.exec()

    # ----------------------------------------------------------- archivo
    def _update_title(self):
        pname = self.ctrl.project.name
        name = os.path.basename(self.ctrl.path) if self.ctrl.path else (
            pname if pname and pname != "Proyecto sin título" else "Proyecto sin guardar")
        self.setWindowTitle(f"{'● ' if self.ctrl.dirty else ''}{name} — {APP_NAME}")
        if hasattr(self, "project_title"):
            # la pestaña ya dice si es Video, Edit o Short: aquí solo el nombre
            self.project_title.setText("·  " + os.path.splitext(name)[0] + ("  ●" if self.ctrl.dirty else ""))
            self.tl_name.setText(self.ctrl.project.name)

    def _confirm_discard(self) -> bool:
        """Si hay cambios sin guardar, pregunta. Devuelve False si el usuario cancela."""
        if not self.ctrl.dirty:
            return True
        r = QMessageBox.question(self, "Cambios sin guardar", "¿Guardar los cambios del proyecto actual?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_project(self):
        """Ctrl+N: proyecto nuevo en la pestaña actual (🎬 Video · 🎵 Edits · 📱 Shorts)."""
        self.workspaces.new_here()
        if self.workspaces.current == "edit":
            QTimer.singleShot(0, self.open_edit_maker)

    def open_project(self, path: str | None = None):
        if not path:
            start = self.settings.value("last_dir", os.path.expanduser("~"))
            path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", start, PROJECT_FILTER)
        if path:
            try:
                if self.workspaces.open_into(path):          # a la pestaña de su tipo
                    self.settings.setValue("last_dir", os.path.dirname(path))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "No se pudo abrir", str(exc))

    def save(self) -> bool:
        if not self.ctrl.path:
            return self.save_as()
        self.ctrl.save()
        self.statusBar().showMessage("Proyecto guardado.", 4000)
        return True

    def save_as(self) -> bool:
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto",
                                              os.path.join(start, f"{self.ctrl.project.name}.eia"),
                                              PROJECT_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".eia"):
            path += ".eia"
        self.ctrl.save(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.statusBar().showMessage(f"Proyecto guardado en {path}", 5000)
        return True

    def save_version(self):
        if not self.ctrl.path and not self.save_as():
            return
        self.ctrl.save()
        v = self.ctrl.save_version()
        if v:
            self.statusBar().showMessage(f"Versión guardada: {os.path.basename(v)}", 6000)

    def default_export_path(self) -> str:
        p = self.ctrl.project
        from .export_dialog import _default_export_dir
        folder = os.path.dirname(self.ctrl.path) if self.ctrl.path else _default_export_dir()
        return os.path.join(folder, f"{p.name}.mp4")

    @property
    def render_queue(self):
        if getattr(self, "_render_queue", None) is None:
            from .render_queue import RenderQueue
            self._render_queue = RenderQueue(self)
            self._render_queue.changed.connect(self._queue_status)
        return self._render_queue

    def _queue_status(self):
        q = self._render_queue
        if q.current is not None:
            self.statusBar().showMessage(f"🚀 Cola: exportando «{q.current['name']}» "
                                         f"{q.current['progress'] * 100:.0f} %", 3000)

    def open_motor(self):
        """◈ Cómo está el motor de IA (PyTorch en la tarjeta NVIDIA o AMD, SAM 2.1, Demucs) e instalar / reparar."""
        from PySide6.QtWidgets import QApplication as _QA
        from ..core import motor_ia
        _QA.setOverrideCursor(Qt.WaitCursor)
        try:
            st = motor_ia.status()
        finally:
            _QA.restoreOverrideCursor()
        if not st["installed"]:
            text = "El motor de IA no está instalado (hace falta para ✂ Recortar sujeto y 🗣 Separar diálogos)."
        elif st["gpu"]:
            text = f"✓ El motor de IA funciona con tu tarjeta gráfica: {st['name']}.\nPyTorch {st['torch']}."
        elif st["vendor"]:
            marca, drv = (("NVIDIA", "de NVIDIA (570 o más nuevo)") if st["vendor"] == "nvidia"
                          else ("AMD", "AMD Adrenalin (26.2.2 o más nuevo)"))
            text = (f"⚠ El motor está instalado pero tu tarjeta {marca} NO se detecta: la IA irá por el procesador "
                    f"(mucho más lenta).\nActualiza el controlador {drv} y pulsa «Reparar».")
        else:
            text = f"✓ El motor de IA está instalado (irá por el procesador). PyTorch {st['torch']}."
        if st["installed"] and not st["sam"]:
            text += "\n⚠ Falta el modelo SAM 2.1: pulsa «Reparar»."
        box = QMessageBox(self)
        box.setWindowTitle("◈ Motor de IA")
        box.setText(text)
        b_inst = box.addButton("Reparar" if st["installed"] else "Instalar", QMessageBox.AcceptRole)
        b_dir = box.addButton("Abrir la carpeta", QMessageBox.ActionRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_inst:
            motor_ia.open_installer()
            self.statusBar().showMessage("◈ Se abrió el instalador del motor de IA en otra ventana.", 8000)
        elif box.clickedButton() is b_dir:
            os.startfile(str(motor_ia.ROOT))    # noqa: S606 - abrir la carpeta en el Explorador

    def _check_motor_soon(self):
        """Al arrancar (sin prisa): si hay motor y tarjeta NVIDIA o AMD pero la IA no la ve, se avisa."""
        import threading
        from ..core import motor_ia
        if not motor_ia.PYTHON.exists() or os.environ.get("EDITORIA_DATOS"):
            return

        def work():
            st = motor_ia.status()
            if st["installed"] and st["vendor"] and not st["gpu"]:
                marca = "NVIDIA" if st["vendor"] == "nvidia" else "AMD"
                self._motor_warning.emit(f"⚠ La IA no detecta tu tarjeta {marca} (irá por el procesador, más lenta). "
                                         "Ayuda → «◈ Motor de IA…» para ver qué pasa.")
        threading.Thread(target=work, daemon=True).start()

    def open_diagnostics(self):
        from .diagnostics_dialog import DiagnosticsDialog
        self.engine.pause()
        DiagnosticsDialog(self).exec()

    def open_convert(self, fmt: str = "mp4"):
        """🔁 Convertir videos y audios a MP4 / MP3 (arrastrando desde tus carpetas)."""
        from .convert_window import ConvertWindow
        dlg = getattr(self, "_convert", None)
        if dlg is None:
            dlg = self._convert = ConvertWindow(self, fmt)
        (dlg.mp3 if fmt == "mp3" else dlg.mp4).setChecked(True)
        dlg.show()
        dlg.raise_()

    def quick_export(self):
        """⚡ Exportar rápido: destino (YouTube / TikTok / Windows) y carpeta de tu PC en un menú; se exporta
        en segundo plano por la cola (con los ajustes recomendados de cada destino)."""
        from PySide6.QtCore import QSettings as _QS
        from PySide6.QtWidgets import QMenu
        from ..export.ffmpeg_export import TARGETS, ExportOptions, target_bitrate, target_size
        from .convert_window import quick_folders
        from .export_dialog import _default_export_dir
        p = self.ctrl.project
        if p.duration() <= 0:
            self.statusBar().showMessage("La línea de tiempo está vacía: no hay nada que exportar.", 6000)
            return
        st = _QS("EditorIA", "EditorIA")
        folder = str(st.value("exportar/carpeta", "") or _default_export_dir())
        menu = QMenu(self)
        head = menu.addAction(f"Guardar en: {folder}")
        head.setEnabled(False)
        fm = menu.addMenu("📁 Cambiar carpeta")
        for name, path in quick_folders():
            fm.addAction(f"{name}  ({path})", lambda p_=path: (st.setValue("exportar/carpeta", p_), self.quick_export()))
        fm.addAction("Otra…", lambda: (lambda d: d and (st.setValue("exportar/carpeta", d), self.quick_export()))(
            QFileDialog.getExistingDirectory(self, "Exportar en…", folder)))
        menu.addSeparator()

        def go(key):
            from .audit_dialog import revision_previa
            if not revision_previa(self):
                return
            w, h = target_size(key, p.width, p.height)
            t = TARGETS[key]
            name = p.name + (f" - {t['suffix']}" if t["suffix"] else "")
            path = os.path.join(folder, f"{name}.mp4")
            k = 2
            while os.path.exists(path):
                path = os.path.join(folder, f"{name} ({k}).mp4")
                k += 1
            fps = p.fps if p.fps in (24, 25, 30, 50, 60) else 60
            opts = ExportOptions(path=path, width=w, height=h, fps=float(fps), codec="h264", encoder="gpu",
                                 bitrate_mbps=target_bitrate(key, w, h), target=key)
            self.render_queue.add(p, opts, "⚡ " + t["name"])
            self.render_queue.start()
            self.statusBar().showMessage(f"⚡ Exportando para {t['name']} en segundo plano → {path}", 9000)
        for key in ("youtube", "tiktok", "windows"):
            menu.addAction(TARGETS[key]["name"], lambda k_=key: go(k_))
        menu.addSeparator()
        menu.addAction("⚙ Más opciones… (Ctrl+E)", self.export)
        menu.exec(self.btn_quick_export.mapToGlobal(self.btn_quick_export.rect().bottomLeft()))

    def open_queue(self):
        from .render_queue import QueueDialog
        dlg = getattr(self, "_queue_dialog", None)
        if dlg is None:
            dlg = self._queue_dialog = QueueDialog(self, self.render_queue)
        dlg.show()
        dlg.raise_()

    def export(self):
        """Antes de exportar se revisa el proyecto; si hay avisos importantes se muestran (audit_dialog.revision_previa)."""
        from .audit_dialog import revision_previa
        if revision_previa(self):
            ExportDialog(self.ctrl, self).exec()

    def open_audit(self):
        from .audit_dialog import AuditDialog
        self.engine.pause()
        AuditDialog(self.ctrl, self.engine, self.timeline, self).exec()

    def open_quick_review(self):
        """⚡ Revisión rápida con teclas (Ctrl+Shift+Q): propuestas de la IA y cortes dudosos, uno a uno. No es modal."""
        from .quick_review import QuickReview
        if self.voice.job is not None or self.ai_panel.job is not None:
            QMessageBox.information(self, "Revisión rápida", "Espera a que termine la tarea de IA que está en marcha.")
            return
        if getattr(self, "quick_review", None) is None:
            self.quick_review = QuickReview(self)
        self.quick_review.start()

    # ------------------------------------------------------- 📋 plantillas de proyecto
    def _fill_templates_menu(self):
        from ..core import project_templates as pt
        m = self.menu_templates
        m.clear()
        items = pt.list_templates()
        if not items:
            a = m.addAction("(Todavía no hay plantillas: guarda una con «Guardar como plantilla…»)")
            a.setEnabled(False)
            return
        for t in items:
            label = FORMATS.get(t["formato"], ("",))[0]
            a = m.addAction(f"{t['nombre']}  ·  {label}".rstrip(" ·"))
            a.triggered.connect(lambda _c=False, path=t["ruta"]: self.new_from_template(path))

    def new_from_template(self, path: str):
        """Proyecto nuevo con la configuración de una plantilla (en la pestaña de su tipo). Sin clips ni medios."""
        from ..core import project_templates as pt
        try:
            tpl = pt.load(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Plantilla", f"No se pudo leer la plantilla: {exc}")
            return
        fmt = tpl.get("formato") if tpl.get("formato") in FORMATS else "youtube"
        ws = self.workspaces
        if fmt != ws.current and not ws.switch(fmt):
            return
        before = self.ctrl.project
        ws.new_here()                         # pregunta antes si hay cambios sin guardar
        if self.ctrl.project is before:       # cancelaste: no tocamos el proyecto actual
            return
        name = str(tpl.get("nombre") or "")
        # Un solo paso de deshacer; el proyecto nuevo está vacío, así que solo cambia su configuración
        if self.ctrl._edit(f"Plantilla «{name}»", lambda p: pt.apply(p, tpl)) is None:
            self.statusBar().showMessage("No se pudo aplicar la plantilla.", 6000)
            return
        self.statusBar().showMessage(f"📋 Proyecto nuevo desde la plantilla «{name}».", 6000)

    def save_as_template(self):
        """Archivo → Guardar como plantilla…: formato, pistas y ajustes de audio, subtítulos (sin clips ni medios)."""
        from PySide6.QtWidgets import QInputDialog
        from ..core import project_templates as pt
        p = self.ctrl.project
        name, ok = QInputDialog.getText(self, "Guardar como plantilla",
                                        "Nombre de la plantilla (p. ej. «Mi YouTube con voz»):",
                                        text=FORMATS.get(p.format, ("Plantilla",))[0].split(" ", 1)[-1])
        name = name.strip()
        if not ok or not name:
            return
        if os.path.exists(pt.template_path(name)) and QMessageBox.question(
                self, "Guardar como plantilla", f"Ya hay una plantilla «{name}». ¿La reemplazo?") != QMessageBox.Yes:
            return
        pt.save(p, name)
        self.statusBar().showMessage(f"📋 Plantilla guardada: «{name}». Se usa en Archivo → Nuevo desde plantilla.", 7000)

    def _do_autosave(self):
        if self.ctrl.dirty:
            try:
                self.ctrl.write_autosave()
            except OSError:
                pass

    def try_recover(self):
        """Si el programa se cerró de golpe la última vez, ofrece recuperar el autoguardado."""
        self.workspaces.start()          # 🗂 la pestaña donde estabas, con su proyecto
        self.preview.set_guides_space(self.workspaces.current)
        lock, auto = session_lock_path(), autosave_path()
        if lock.exists() and auto.exists():
            r = QMessageBox.question(
                self, "Recuperar trabajo",
                "Parece que el programa se cerró inesperadamente la última vez.\n\n"
                "¿Quieres recuperar el último autoguardado?")
            if r == QMessageBox.Yes:
                try:
                    import json
                    with open(auto, encoding="utf-8") as f:
                        esp = json.load(f).get("_espacio")
                    if esp and esp != self.workspaces.current:   # 🗂 era de otra pestaña: se recupera en la suya
                        self.workspaces.switch(esp)
                    self.ctrl.load(str(auto), recovered=True)
                    self.statusBar().showMessage("Proyecto recuperado. Guárdalo con Ctrl+S.", 10000)
                except (OSError, ValueError) as exc:
                    QMessageBox.warning(self, "No se pudo recuperar", str(exc))
        lock.write_text("abierto", encoding="utf-8")

    def _auto_scene_cuts(self, clip_ids: list):
        """✂ Los videos marcados en Medios con «Cortar en cada cambio de escena» llegan ya cortados (si hay cambios)."""
        from ..core.model import TRACK_VIDEO
        p = self.ctrl.project
        ids = [cid for cid in clip_ids if (c := p.clips.get(cid)) is not None and p.media_of(c) is not None
               and getattr(p.media_of(c), "scene_cut", False) and p.media_of(c).kind == "video"
               and p.track(c.track_id).kind == TRACK_VIDEO]
        if ids:
            self.cut_scenes(ids)

    def reset_project(self):
        """🔄 Reinicio de proyecto: esta pestaña vuelve a estar vacía (línea de tiempo, Medios, subtítulos, marcadores).
        Antes se guarda una copia de seguridad de cómo estaba; el archivo .eia (si tiene) y tus videos no se tocan."""
        p = self.ctrl.project
        if not p.clips and not p.media:
            self.statusBar().showMessage("El proyecto ya está vacío.", 5000)
            return
        r = QMessageBox.question(
            self, "🔄 Reinicio de proyecto",
            "¿Empezar de cero en esta pestaña?\n\nSe vacían la línea de tiempo, Medios, subtítulos y marcadores.\n"
            "Antes se guarda una COPIA DE SEGURIDAD de cómo está ahora (Archivo → copias de seguridad).\n"
            "Tus videos y audios no se tocan" + (f", ni tu archivo «{os.path.basename(self.ctrl.path)}»"
                                                 if self.ctrl.path else "") + ".",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if r != QMessageBox.Yes:
            return
        backup = self.workspaces.reset_here()
        self.statusBar().showMessage("🔄 Proyecto vacío. Copia de lo anterior: " + (backup or "—"), 12000)

    def _maybe_align(self, media_id: str):
        """🎯 Transcripción nueva: sus palabras se afinan en segundo plano (alineación con IA, ~20 ms) para cortar
        silencios sin comerse palabras, para los subtítulos y para verlas sobre la onda. Empieza a los 3 s y solo si
        Reclaimer sigue abierto (cargar el modelo no se puede interrumpir: no se empieza justo al cerrar)."""
        from ..ai import align
        if align.needs(self.ctrl.project.transcripts.get(media_id)) and media_id not in self._aligning:
            QTimer.singleShot(3000, self, lambda mid=media_id: self._start_align(mid) if self.isVisible() else None)

    def _start_align(self, media_id: str):
        from ..ai import align
        tr = self.ctrl.project.transcripts.get(media_id)
        if not align.needs(tr) or media_id in self._aligning or not align.available()[0]:
            return
        m = self.ctrl.project.media.get(media_id)
        if m is None or not os.path.exists(m.path):
            return
        self._aligning.add(media_id)
        words, path = [list(w) for w in tr["words"]], m.path

        def work(progress, cancelled):
            try:
                return align.align_words(path, words, progress, cancelled)
            finally:
                align.unload()

        def done(new, mid=media_id, old=words):
            self._aligning.discard(mid)
            now = self.ctrl.project.transcripts.get(mid)
            if now and [w[2] for w in now.get("words", [])] == [w[2] for w in old] and len(new) == len(old):
                self.ctrl.set_transcript(mid, align.refined(now, new))
                self.statusBar().showMessage(f"🎯 Palabras de «{m.name}» afinadas con la IA (±20 ms).", 6000)
                self.learn_voice(mid, new)

        def fail(_err, mid=media_id):
            self._aligning.discard(mid)
        from .task_window import manager
        manager().start(f"🎯 Afinar palabras de «{m.name}»", work, done, fail)

    def learn_voice(self, media_id: str, words: list):
        """◈ Palabras recién afinadas: la grabación solo se APUNTA para aprender tu voz (instantáneo, sin gastar nada).
        Se aprende cuando se usa: al abrir «✂ Eliminar silencio» (learn_voice_pending) o con Voz → Entrenar."""
        import importlib.util
        if importlib.util.find_spec("torch") is None:
            return
        m = self.ctrl.project.media.get(media_id)
        if m is None or not os.path.exists(m.path):
            return
        from ..ai import voice_model as VM
        try:
            VM.queue_example(m.path, words)
        except OSError:
            pass

    def learn_voice_pending(self) -> bool:
        """◈ Si hay grabaciones apuntadas, la IA aprende tu voz ahora en segundo plano (al usar «Eliminar silencio»).
        Devuelve True si empezó."""
        import importlib.util
        if importlib.util.find_spec("torch") is None:
            return False
        from ..ai import voice_model as VM
        if not VM.pending() or getattr(self, "_learning_voice", False):
            return False
        self._learning_voice = True

        def done(rep):
            self._learning_voice = False
            if rep:
                v = rep.get("val") or {}
                self.statusBar().showMessage(
                    f"◈ La IA aprendió tu voz con {rep['minutes']:.0f} min de ejemplos"
                    + (f" · en una grabación que no vio: {v['acierto'] * 100:.1f} % de acierto, bordes a "
                       f"{v['borde_mediana_ms']:.0f} ms" if v else ""), 9000)

        def fail(_e):
            self._learning_voice = False
        from .task_window import manager
        manager().start("◈ Aprender tu voz", lambda p, c: VM.learn_pending(p, c), done, fail)
        return True

    def train_voice_now(self):
        """◈ Menú Voz: vuelve a entrenar con los ejemplos guardados (o explica cómo conseguirlos)."""
        import importlib.util
        from ..ai import voice_model as VM
        if importlib.util.find_spec("torch") is not None and VM.pending():
            try:
                VM.process_pending()           # lo apuntado al transcribir cuenta ya
            except Exception:  # noqa: BLE001
                pass
        mins = VM.examples_minutes()
        if importlib.util.find_spec("torch") is None:
            QMessageBox.information(self, "◈ Entrenar la IA con tu voz",
                                    "Falta PyTorch en el entorno de Reclaimer para entrenar.")
            return
        if mins < VM.MIN_TRAIN_MIN:
            QMessageBox.information(
                self, "◈ Entrenar la IA con tu voz",
                f"Hay {mins:.1f} min de ejemplos de tu voz y hacen falta al menos {VM.MIN_TRAIN_MIN:.0f}.\n\n"
                "Se consiguen solos: cada vez que transcribes una grabación tuya, la IA afina sus palabras y la guarda "
                "como ejemplo.")
            return

        def done(rep):
            if not rep:
                return
            v = rep.get("val") or {}
            QMessageBox.information(
                self, "◈ Entrenar la IA con tu voz",
                f"Listo: la IA aprendió tu voz con {rep['minutes']:.0f} min de ejemplos ({rep['examples']} grabaciones)."
                + (f"\n\nEn una grabación que no vio al entrenar acierta el {v['acierto'] * 100:.1f} % del tiempo y "
                   f"marca el principio y el final de lo que dices a {v['borde_mediana_ms']:.0f} ms (mediana)."
                   if v else "")
                + "\n\nSe usa sola al eliminar silencios (modo híbrido).")
        from .task_window import manager
        manager().start("◈ Aprender tu voz", lambda p, _c: VM.train_from_examples(progress=p), done,
                        lambda e: QMessageBox.warning(self, "◈ Entrenar la IA con tu voz", f"No se pudo: {e}"))

    def forget_voice(self):
        from ..ai import voice_model as VM
        if QMessageBox.question(self, "◈ Olvidar tu voz",
                                f"¿Borrar lo que la IA aprendió de tu voz ({VM.examples_minutes():.0f} min de "
                                "ejemplos y el modelo)?\n\nTus grabaciones no se tocan.",
                                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        import shutil
        shutil.rmtree(VM.examples_dir(), ignore_errors=True)
        for p in (VM.model_path(), VM.model_path()[:-4] + ".json"):
            if os.path.exists(p):
                os.remove(p)
        self.statusBar().showMessage("◈ Olvidado: la IA ya no usa lo aprendido de tu voz.", 6000)

    def track_silence_edges(self, edges: list[dict]):
        """Los bordes que acaba de crear «Eliminar silencio» (se vigilan los últimos 400)."""
        self._sil_edges = (self._sil_edges + list(edges))[-400:]

    def _observe_silence_edges(self):
        from ..core import silence_learn as SL
        try:
            SL.observe(self.ctrl.project, self._sil_edges)
        except OSError:
            pass

    def _mcp_back_on(self):
        """Cierre cancelado: el puente de Claude vuelve a estar disponible si estaba activado."""
        from .claude_bridge import enabled
        if enabled():
            self.claude_bridge.start()

    # ---- 🖥 visor en la segunda pantalla · ✏ corregir subtítulos desde el visor
    SECOND_KEY = "visor/segunda_pantalla"

    def toggle_second_screen(self, _on=False):
        from .second_screen import SecondScreenWindow
        win = getattr(self, "_second", None)
        if win is not None and win.isVisible():
            win.close()
            return
        if win is None:
            self._second = win = SecondScreenWindow(self.preview.canvas, self.engine.toggle, "F11", self)
            win.closed.connect(self._second_closed)
        win.abrir()
        self.act_second.setChecked(True)
        QSettings("EditorIA", "EditorIA").setValue(self.SECOND_KEY, True)

    def _second_closed(self):
        self.act_second.setChecked(False)
        if not getattr(self, "_second_closing", False):   # cerrada a propósito (Esc / F11): no se vuelve a abrir sola
            QSettings("EditorIA", "EditorIA").setValue(self.SECOND_KEY, False)

    def _restore_second_screen(self):
        """Al arrancar: solo si estaba abierta al cerrar Y de verdad hay una segunda pantalla."""
        from .second_screen import pantalla_secundaria
        if str(QSettings("EditorIA", "EditorIA").value(self.SECOND_KEY, "false")).lower() == "true" \
                and pantalla_secundaria()[1]:
            self.toggle_second_screen()

    def _subtitle_edit_from_viewer(self, indices, clicked: int, rect):
        from .subtitle_edit import SubtitleEditor
        ed = getattr(self, "_sub_editor", None)
        if ed is None:
            self._sub_editor = ed = SubtitleEditor(self.ctrl, self.preview.canvas.viewport())
        mid = self.ctrl.project.subtitles.media_id
        if not mid:
            return
        ed.open(mid, list(indices), clicked, rect)

    def closeEvent(self, e):
        win = getattr(self, "_second", None)
        if win is not None and win.isVisible():        # al cerrar el programa, la segunda pantalla queda «abierta» para la próxima vez
            QSettings("EditorIA", "EditorIA").setValue(self.SECOND_KEY, True)
            self._second_closing = True
            win.close()
            self._second_closing = False
        self.engine.pause()
        if self._thumb_page is not None and getattr(self, "_thumb_editor", None) is not None:
            self._thumb_editor.close()            # 🖼 sale del taller (se guarda) y los paneles vuelven a su sitio
        try:
            self.claude_bridge.stop()               # (si se cancela el cierre, se vuelve a encender abajo)
        except (AttributeError, RuntimeError):
            pass
        # Solo se pregunta por tareas que lanzaste tú; el análisis automático de clips y las copias
        # ligeras (proxies) se detienen solas al cerrar y continúan la próxima vez.
        if self.voice.job is not None or self.ai_panel.job is not None:
            r = QMessageBox.question(self, "Tarea en curso",
                                     "Se está transcribiendo o analizando la narración.\n"
                                     "¿Cancelar la tarea y cerrar?")
            if r != QMessageBox.Yes:
                e.ignore()
                self._mcp_back_on()
                return
        try:                                 # 🗂 lo de esta pestaña queda guardado (sin nombre: en su archivo;
            ok = self.workspaces.store() if self.workspaces.started else self._confirm_discard()
        except (OSError, TypeError, ValueError) as exc:     # si no se pudiera, se pregunta como siempre
            self.statusBar().showMessage(f"⚠ No se pudo guardar la pestaña: {exc}", 8000)
            ok = self._confirm_discard()
        if not ok:                           #    con nombre: guardado en vivo, o te pregunta si lo tienes apagado)
            e.ignore()
            self._mcp_back_on()
            return
        self.saving.stop()               # el guardado en vivo se para antes de cerrar
        self.learner.on_close()          # último resumen; después no queda nada funcionando
        from .task_window import stop_all
        stop_all()                       # trabajos en segundo plano: se paran y se espera un momento
        self.voice.shutdown()
        self.audio_monitor.stop()
        self.analyzer.shutdown()
        self._pool_idle = self.ctrl.shutdown(3000)   # análisis de archivos (miniatura, forma de onda) a medias
        self.ai_panel.shutdown()
        self.proxies.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("ventana/paneles", self.saveState(3))
        session_lock_path().unlink(missing_ok=True)
        autosave_path().unlink(missing_ok=True)
        e.accept()

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_sizes_pending", False):
            self._sizes_pending = False
            QTimer.singleShot(0, self._apply_dock_sizes)
        # siempre al abrir: la línea de tiempo con todas sus pistas a la vista (también tras maximizar)
        QTimer.singleShot(0, self._ensure_timeline_size)
        QTimer.singleShot(400, self._ensure_timeline_size)
        QTimer.singleShot(0, self._ensure_side_widths)
        QTimer.singleShot(400, self._ensure_side_widths)
        QTimer.singleShot(0, self.timeline.fit)
