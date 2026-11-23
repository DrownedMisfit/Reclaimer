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
from ..core.model import FORMATS, TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO
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
← / → — fotograma anterior / siguiente · Mayús+← / Mayús+→ — 5 segundos atrás / adelante (botones −5s / +5s)<br>
Inicio / Fin — ir al principio / al final<br>
Barra del visor: «1×» = velocidad 1× → 2× → 4× → 8× → 1× · 🔊 = volumen de escucha (clic = silenciar) · LUFS = sonoridad para plataformas<br><br>
<b>Edición</b><br>
S — dividir en el cabezal (lo seleccionado, o todo lo no bloqueado)<br>
Supr — eliminar clips seleccionados (o el hueco seleccionado)<br>Arrastrar en zona vacía — rectángulo de selección<br>
Mayús+Supr — eliminar y cerrar el hueco<br>
Ctrl+L — bloquear / desbloquear clips seleccionados<br>
Ctrl++ — juntar: todo se pega a la izquierda (sin huecos) en el canal seleccionado o en toda la línea de tiempo<br>
Ctrl+Mayús+Supr — eliminar silencio (como en Resolve)<br>
Ctrl+C / Ctrl+X / Ctrl+V — copiar / cortar / pegar clips en el cabezal (Ctrl+V también pega una imagen copiada de internet) · Alt+V — pegar atributos<br>
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
Con un clip seleccionado: arrastrar en el visor = mover encuadre · rueda = zoom<br>
Visor: rueda — zoom de la vista · Alt+rueda — subir/bajar la vista · rueda pulsada + arrastrar — moverla<br><br>
<b>Proyecto</b><br>
Ctrl+N nuevo · Ctrl+O abrir · Ctrl+S guardar · Ctrl+Alt+S guardar versión · Ctrl+E exportar<br>
Ctrl+1 / Ctrl+2 / Ctrl+3 — pestaña 🎬 Video horizontal / 🎵 Edits / 📱 Vertical (lo de la que dejas queda guardado)<br>
Ctrl+Mayús+R — 🎙 grabar voz en off · Ctrl+Mayús+K — 📑 capítulos para YouTube · Ctrl+Alt+G — 📸 fotograma (PNG)
"""


class _TituloCorto(QLabel):
    """El nombre del proyecto en la barra de arriba: si no cabe, se acorta con «…» (entero en el tooltip). Así no
    obliga a una ventana más ancha (con el nombre entero, la barra de arriba pedía ~280 px más)."""

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        s.setWidth(min(s.width(), self.fontMetrics().horizontalAdvance("·  Proyecto…") + 4))
        return s

    def setText(self, t: str):
        super().setText(t)
        self.setToolTip(t.replace("·", "").strip())

    def paintEvent(self, _e):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        p.drawText(r, int(self.alignment()) | Qt.AlignVCenter,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width()))


class _PestanasEnDosFilas(QWidget):
    """Fase 1: las pestañas de un grupo de paneles en DOS FILAS con su nombre completo cuando en una no caben (Qt solo
    sabe hacer una fila). Va encima de la fila de pestañas de Qt (hija suya: se mueve, se oculta y se borra con ella),
    que se hace el doble de alta para dejarle sitio. La capa NO se queda el ratón: la fila de Qt lo recibe traducido a
    la pestaña que está debajo en la capa, así que un clic la elige y arrastrarla saca o mueve el panel como siempre."""

    def __init__(self, barra, win):
        super().__init__(barra)
        self.barra, self.win = barra, win
        self.activa = False
        self.tabs = []                   # [(índice de la pestaña de Qt, nombre, ancho, icono)]
        self.alto_fila = 28
        self._encima = -1
        self._pulsada = None             # (pestaña, punto en la capa, punto en la fila de Qt) mientras se arrastra
        self._reenviando = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        barra.setMouseTracking(True)
        barra.installEventFilter(self)
        barra.currentChanged.connect(lambda _i: self.update())
        self.hide()

    @staticmethod
    def filas(anchos, disp):
        """Reparte las pestañas (por su ancho) en filas que caben en disp, en orden."""
        filas, fila, usado = [], [], 0
        for i, a in enumerate(anchos):
            if fila and usado + a > disp:
                filas.append(fila)
                fila, usado = [], 0
            fila.append(i)
            usado += a
        if fila:
            filas.append(fila)
        return filas

    def poner(self, tabs, alto_fila: int):
        hoja = f"QTabBar::tab {{ height: {alto_fila * 2 - 14}px; }}"
        if self.barra.styleSheet() != hoja:
            self.barra.setStyleSheet(hoja)            # (la fila de Qt, el doble de alta: Qt deja el sitio)
        firma_nueva = [(i, n, a) for i, n, a, _ic in tabs]
        cambia = (firma_nueva, alto_fila) != ([(i, n, a) for i, n, a, _ic in self.tabs], self.alto_fila) or \
            not self.activa
        self.tabs, self.alto_fila, self.activa = tabs, alto_fila, True
        self.firma = self._firma()
        if self.geometry() != self.barra.rect():
            self.setGeometry(self.barra.rect())
        if self.isHidden():
            self.show()
            self.raise_()
        if cambia:
            self.update()

    def quitar(self):
        self.activa = False
        self._pulsada = None
        self.hide()
        if self.barra.styleSheet():
            self.barra.setStyleSheet("")

    def rects(self):
        from PySide6.QtCore import QRect
        disp = max(1, self.width() - 4)
        out = []
        for f, fila in enumerate(self.filas([t[2] for t in self.tabs], disp)):
            x = 2
            for j in fila:
                i, n, a = self.tabs[j][:3]
                out.append((i, n, QRect(x, f * self.alto_fila, a, self.alto_fila)))
                x += a
        return out

    def _firma(self):
        return [self.barra.tabData(i) for i in range(self.barra.count())]

    def _en(self, pos):
        return next((i for i, _n, r in self.rects() if r.contains(pos)), -1)

    def _reenviar(self, ev, pos_qt):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        nuevo = QMouseEvent(ev.type(), QPointF(pos_qt), QPointF(self.barra.mapToGlobal(pos_qt)), ev.button(),
                            ev.buttons(), ev.modifiers())
        self._reenviando = True
        try:
            QApplication.sendEvent(self.barra, nuevo)
        finally:
            self._reenviando = False

    def eventFilter(self, obj, ev):
        if obj is not self.barra or not self.activa or self._reenviando:
            return False
        t = ev.type()
        if self._firma() != getattr(self, "firma", None):   # (otras pestañas en esta fila: hasta que se decida otra vez)
            self.quitar()
            return False
        if t == ev.Type.Resize:
            self.setGeometry(self.barra.rect())
            return False
        if t in (ev.Type.MouseButtonPress, ev.Type.MouseButtonDblClick):
            p = ev.position().toPoint()
            i = self._en(p)
            if i < 0 or i >= self.barra.count():
                return True
            dentro = self.barra.tabRect(i).center()
            self._pulsada = (i, p, dentro)
            self._reenviar(ev, dentro)
            self.update()
            return True
        if t == ev.Type.MouseMove:
            p = ev.position().toPoint()
            if self._pulsada is not None and ev.buttons():
                _i, p0, dentro = self._pulsada
                self._reenviar(ev, dentro + (p - p0))       # (el arrastre, desde su pestaña de Qt)
                return True
            i = self._en(p)
            if i != self._encima:
                self._encima = i
                self.update()
            return True
        if t == ev.Type.MouseButtonRelease:
            if self._pulsada is not None:
                _i, p0, dentro = self._pulsada
                self._pulsada = None
                self._reenviar(ev, dentro + (ev.position().toPoint() - p0))
                self.update()
            return True
        if t == ev.Type.ToolTip:
            from PySide6.QtWidgets import QToolTip
            i = self._en(ev.pos())
            if 0 <= i < self.barra.count() and self.barra.tabToolTip(i):
                QToolTip.showText(ev.globalPos(), self.barra.tabToolTip(i), self.barra)
            else:
                QToolTip.hideText()
            return True
        if t == ev.Type.Leave:
            self._encima = -1
            self.update()
        return False

    def paintEvent(self, _e):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QPainter, QPen
        from .theme import BG, TEXT_DIM, acento
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        actual = self.barra.currentIndex()
        iconos = {t[0]: t[3] for t in self.tabs}
        for i, n, r in self.rects():
            vivo = i in (actual, self._encima)
            ic = iconos.get(i)
            x = r.left() + 8
            if ic is not None and not ic.isNull():
                ic.paint(p, QRect(x, r.center().y() - 7, 14, 14), Qt.AlignCenter,
                         ic.Mode.Normal, ic.State.On if vivo else ic.State.Off)
                x += 18
            p.setPen(QColor("white") if vivo else QColor(TEXT_DIM))
            p.drawText(QRect(x, r.top(), r.right() - x - 6, r.height()), Qt.AlignLeft | Qt.AlignVCenter, n)
            if i == actual:
                p.setPen(QPen(acento(), 2))
                p.drawLine(r.left() + 4, r.bottom() - 1, r.right() - 4, r.bottom() - 1)
        p.end()


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
        self.workspaces.switched.connect(lambda tab: self.apply_tab_panels(tab))   # 🗂 los paneles de esa pestaña
        self.workspaces.switched.connect(lambda _tab: QTimer.singleShot(0, self._sync_interruptores))
        self._barra_shorts()                                              # 📱 Transcribir, Subtítulos… en Shorts
        self.workspaces.switched.connect(self._al_cambiar_pestaña)
        self.engine = PlaybackEngine(self.ctrl, self.preview, self)
        try:                                    # 🔎 «Material por frases» en Medios, bajo «Archivos / Carpeta»
            from .material_por_frases_panel import instalar as _instalar_mpf
            _instalar_mpf(self)
        except Exception:                       # (si fallara, el resto de la ventana arranca igual; se apunta en
            try:                                #  registros\errores.log: con el acceso directo no hay consola)
                import time as _t
                import traceback as _tb
                from ..core.paths import log_path as _log
                with open(_log(), "a", encoding="utf-8") as _f:
                    _f.write(f"\n[{_t.strftime('%Y-%m-%d %H:%M:%S')}] «Material por frases» en Medios:\n"
                             f"{_tb.format_exc()}")
            except Exception:  # noqa: BLE001
                pass
        try:                                    # 🔁 bandejas «No usados» / «Usados 2+ veces» en Medios (fase 4)
            from .repetidos_ui import instalar_bandejas as _instalar_bandejas
            _instalar_bandejas(self)
        except Exception:                       # (si fallara, la ventana arranca igual; se apunta en errores.log)
            try:
                import time as _t
                import traceback as _tb
                from ..core.paths import log_path as _log
                with open(_log(), "a", encoding="utf-8") as _f:
                    _f.write(f"\n[{_t.strftime('%Y-%m-%d %H:%M:%S')}] Bandejas de Medios:\n{_tb.format_exc()}")
            except Exception:  # noqa: BLE001
                pass
        # 〰 fundidos automáticos en los cortes de sonido (fase 3; se recuerda, encendidos por defecto)
        self.ctrl.fundidos_auto = str(self.settings.value("audio/fundidos_auto", "true")).lower() == "true"
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
        # 🗣 Una narración de la Voz IA ya tiene su texto exacto: 🎙 Transcribir pregunta antes de pisarlo (el botón
        # del transcriptor, la barra de Vertical, Ctrl+T… todos pasan por voice.transcribe)
        _transcribir = self.voice.transcribe
        try:
            self.voice.btn_transcribe.clicked.disconnect(_transcribir)
        except (RuntimeError, TypeError):
            pass
        self.voice.transcribe = self._transcribir_con_aviso(_transcribir)
        self.voice.btn_transcribe.clicked.connect(self.voice.transcribe)
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
        self._crear_marcas()                      # 📍 marcadores automáticos: la capa y su índice (fase 5)
        from .escenas_ajustes_ui import vigilar as _vigilar_escenas
        _vigilar_escenas(self.ctrl)               # 🎬 PNG de Escenas: lo aplicado no se borra; lo que falte, se repone
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
        self.clips.foco_changed.connect(self.timeline.set_hint_focus)    # 🔑 la elegida, resaltada
        self.clips.modo_changed.connect(self.timeline.set_marcas_modo)   # 🔑 Todas / Elegida / Ninguna, a la par
        self.timeline.marcas_modo_changed.connect(self.clips.set_modo)
        self.clips.fila_kw_changed.connect(self.timeline.poner_fila_kw)  # ⚡ fila de material: botón, menú y regla
        self.timeline.kw_fila_changed.connect(self.clips.set_fila_kw)
        self.clips.set_fila_kw(self.timeline.kw_visible)
        self.timeline.hint_word_clicked.connect(self.clips.elegir_palabra)   # 🔑 clic en la muesca de otra
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
        timeline_box.setObjectName("timeline_box")
        tl = QVBoxLayout(timeline_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.timeline_box = timeline_box
        tl.addWidget(self._timeline_toolbar())
        from .resumen_linea import ResumenLinea           # 🗺 todo el video en una franja (fase 8)
        self.resumen = ResumenLinea(self.ctrl, self.timeline)
        tl.addWidget(self.resumen)
        self.engine.time_changed.connect(self.resumen.cabezal_movido)     # (su raya del cabezal, al día)
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
        # (de entrada, la línea de tiempo a todo el ancho de abajo; «◧ A todo el alto» pone la biblioteca hasta abajo,
        #  como DaVinci: ver _esquina_biblioteca)
        self.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.BottomDockWidgetArea)
        self.docks: dict[str, QDockWidget] = {}
        self._dock("timeline", "Línea de tiempo", timeline_box, closable=False)
        self._dock("media", "Medios", self.library)
        self._dock("effects", "Transiciones y efectos", self.effects)   # («Efectos» = la pestaña del Inspector)
        self._dock("ai", "IA ✨", self.ai_panel)
        self._dock("moments", "🔎 Momentos", self.moments)
        from .descargas_generales import DescargasGenerales     # 🌐 buscar y bajar lo que quieras (sin palabra)
        self.descargas_web = DescargasGenerales(self.ctrl, self.timeline)
        self._dock("descargas_web", "🌐 Descargas", self.descargas_web)
        from .memes_panel import MemesPanel                     # 😂 tu biblioteca de memes (todos los proyectos)
        self.memes = MemesPanel(self.ctrl, self)
        self._dock("memes", "😂 Memes", self.memes)
        self._dock("clips", "🔑 Palabras clave", self.clips)
        from .keywords_window import KeywordsWindow           # 🗂 la carpeta de la palabra elegida (a la derecha)
        self.kw_folders = KeywordsWindow(self.clips, acoplado=True)
        self.clips.carpetas_dock = self.kw_folders
        self._dock("kw_folders", "🗂 Carpetas", self.kw_folders)
        # 🔑 Página «Palabras clave»: la búsqueda (📁 Mi carpeta | 🌐 Internet) en su propia columna (📥 lo descargado
        # vive dentro de 🗂 Carpetas: keywords_window / descargas_panel)
        self._dock("kw_buscar", "🔎 Buscar material", self.clips.sacar_busqueda())
        self._dock("inspector", "Inspector", self.inspector)
        self._dock("voice", "Limpieza", self.voice)
        self.ai_panel.set_transcriber(self.voice)            # 🎙 el transcriptor, en la pestaña «IA ✨»
        self._acceso_voz_ia_en_transcribir()
        self._dock("transcript", "Transcripción", self.transcript)
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
        from .clip_material_panel import ClipMaterialPanel     # 🎞 lo que se sabe del clip elegido (pestaña YouTube)
        self.material = ClipMaterialPanel(self)
        self._dock("material", "🎞 Material del clip", self.material)
        from .edit_dialog import EditDialog                    # 🎵 el edit musical como parte de la ventana (Edits)
        self.edit_panel = EditDialog(self.ctrl, self, embedded=True)
        self._dock("edit_opts", "🎵 Edit musical", self.edit_panel)
        self._dock("edit_clips", "🎞 Clips del edit", self.edit_panel.clips_page)
        from .voz_ia_panel import VozIAPanel                   # 🗣 Voz IA: pegar el guion y que lo lea una voz sintética
        self.voz_ia = VozIAPanel(self)
        self._dock("voz_ia", "🗣 Voz IA", self.voz_ia)
        # 🎚 «Audio inteligente» (antes una subpestaña de IA ✨): su propio panel, en la página 🎚 Audio (y en Editar)
        self._dock("audio_mix", "🎚 Mezcla y música", self.ai_panel.sacar_audio())
        # 🔊 Sonidos (antes la pestaña «Sonidos» de Efectos, con 🌐 buscar en internet): su panel, en la página 🎚 Audio
        self._dock("sounds", "🔊 Sonidos", self.effects.sacar_sonidos())
        # ✦ (agrupación 20/11) las columnas de la página Efectos de antes: ya no hay página; solo quedan sus nombres para
        # las distribuciones guardadas viejas (absorbidos: llevan al panel Efectos)
        for _k, _t in (("fx_trans", "⧉ Transiciones"), ("fx_efectos", "✦ Efectos"), ("fx_filtros", "🎨 Filtros"),
                       ("fx_figuras", "▭ Figuras geométricas")):
            self._dock(_k, _t, QWidget())
        manager().open_panel.connect(self.open_tasks)
        self.docks["guide"].toggleViewAction().toggled.connect(lambda on: on or self.guide.clear())
        self.right_tabs = _PanelSwitcher(self)   # compatibilidad: right_tabs.setCurrentWidget(panel)
        self._agrupar_paneles()                    # (agrupación 20/11: «Voz y texto» y «Audio»; ver la tabla)
        for _k in self.TAB_MANAGED:               # 🗂 lo que enciendas o apagues tú en una pestaña, se recuerda
            self.docks[_k].toggleViewAction().triggered.connect(lambda on, k=_k: self._remember_tab_panel(k, on))
        self._default_layout()
        self._default_state = self.saveState(3)
        saved = self.settings.value("ventana/paneles")
        self._sizes_pending = saved is None
        if saved is not None:
            try:
                self.restoreState(saved, 3)
            except Exception:  # noqa: BLE001 - un estado guardado roto no impide abrir
                pass
        self._migrar_voz_izquierda(saved is not None)   # (22/11: Voz y texto a la izquierda; Palabras clave, aparte)
        if str(self.settings.value("paneles/pestanas_v1", "false")).lower() != "true":
            # (una vez: 🔑 Palabras clave y 🎞 Material del clip, a la derecha, y el edit musical en su sitio, aunque
            # tuvieras una distribución guardada de antes)
            self.settings.setValue("paneles/pestanas_v1", "true")
            for k in ("clips", "material", "edit_opts"):
                self.addDockWidget(Qt.RightDockWidgetArea, self.docks[k])
                self.tabifyDockWidget(self.docks["inspector"], self.docks[k])
            self.addDockWidget(Qt.LeftDockWidgetArea, self.docks["edit_clips"])
            self.tabifyDockWidget(self.docks["media"], self.docks["edit_clips"])
        if str(self.settings.value("paneles/carpetas_v1", "false")).lower() != "true":
            # (una vez: la pestaña nueva «🗂 Carpetas», junto al Inspector, aunque tuvieras una distribución guardada)
            self.settings.setValue("paneles/carpetas_v1", "true")
            self.addDockWidget(Qt.RightDockWidgetArea, self.docks["kw_folders"])
            self.tabifyDockWidget(self.docks["inspector"], self.docks["kw_folders"])
            self.docks["kw_folders"].setVisible(True)
        if str(self.settings.value("paneles/voz_ia_v1", "false")).lower() != "true":
            # (una vez: la pestaña nueva «🗣 Voz IA», junto al Inspector, aunque tuvieras una distribución guardada;
            # se ve o no según la pestaña de trabajo: apply_tab_panels)
            self.settings.setValue("paneles/voz_ia_v1", "true")
            self.addDockWidget(Qt.RightDockWidgetArea, self.docks["voz_ia"])
            self.tabifyDockWidget(self.docks["inspector"], self.docks["voz_ia"])
        if saved is not None and str(self.settings.value("paneles/audio_mix_v1", "false")).lower() != "true":
            # (una vez, con una distribución guardada de antes: «🎚 Mezcla y música» —antes la subpestaña «Audio» de
            # IA ✨— en pestaña junto a IA ✨, donde la tenías; si IA ✨ está suelta o cerrada, a la izquierda)
            self._colocar_audio_mix()
        self.settings.setValue("paneles/audio_mix_v1", "true")
        if saved is not None and str(self.settings.value("paneles/sonidos_v1", "false")).lower() != "true":
            # (una vez, con una distribución de antes: «🔊 Sonidos» —antes la pestaña «Sonidos» de Efectos— en pestaña
            # junto a «🎚 Mezcla y música» (o IA ✨ / Medios), a la vista)
            self._colocar_junto("sounds", ("audio_mix", "effects", "ai", "media"))
        self.settings.setValue("paneles/sonidos_v1", "true")
        QTimer.singleShot(0, self.apply_tab_panels)            # 🗂 los paneles de la pestaña con la que se abre
        QTimer.singleShot(0, self._ajustar_paneles)            # ↔ nada cortado por la derecha en ningún panel
        QTimer.singleShot(0, self.timeline.setFocus)           # (S, Supr, Ctrl+Z… van al editor desde el principio)
        for key, tb in (("top", self._top_bar()), ("paneles", self._barra_paneles()), ("pages", self._page_bar())):
            if key == "paneles":
                self.addToolBarBreak(Qt.TopToolBarArea)   # (su propia fila, debajo de la de arriba)
            bar = QToolBar(key)
            bar.setObjectName("bar_" + key)
            bar.setMovable(False)
            bar.setFloatable(False)
            bar.toggleViewAction().setVisible(False)
            bar.addWidget(tb)
            tb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.addToolBar(Qt.BottomToolBarArea if key == "pages" else Qt.TopToolBarArea, bar)
            if key == "paneles":
                self._tb_paneles = bar
        self._fila_paneles_aparte()

        # --- conexiones ---
        self.engine.time_changed.connect(lambda t: self.timeline.set_playhead(t, follow=self.engine.playing))
        self.engine.time_changed.connect(lambda t: self.tl_timecode.setText(fmt_tc(t, self.ctrl.project.fps)))
        self.engine.time_changed.connect(lambda _t: self._poner_total_tl())
        self.ctrl.project_changed.connect(self._poner_total_tl)
        self.ctrl.project_replaced.connect(self._poner_total_tl)
        self.engine.time_changed.connect(self._update_meter)
        self.engine.time_changed.connect(self.clips.al_cabezal)          # 🧭 más cercana / más lejana
        self.timeline.seek_requested.connect(self.engine.user_seek)
        # ⏱ al ALARGAR un clip arrastrando su borde, el visor enseña el fotograma nuevo (lo que se va a destapar)
        self.timeline.edge_frame_requested.connect(lambda mid, s: self.engine.mostrar_fotograma(mid, s))
        self.timeline.edge_frame_released.connect(self.engine.soltar_fotograma)
        self.timeline.scrub_requested.connect(self.engine.scrub)      # 🔊 se oye al arrastrar la barra roja
        self.timeline.selection_changed.connect(self.inspector.set_selection)
        from .text_writer import OnScreenText           # ✍ escribir el texto seleccionado en la pestaña «Texto»
        self.text_writer = OnScreenText(self.ctrl, self.engine, self.timeline)
        self.transcript.layout().insertWidget(0, self.text_writer)
        self.timeline.selection_changed.connect(self.text_writer.set_selection)
        self.ctrl.creado_por_ti.connect(self._abrir_lo_creado)   # 🧭 lo que creas, con su editor a la vista y el foco
        self.inspector.text_edit.installEventFilter(self)        # (Esc = volver a la línea de tiempo; Deshacer y
        #                                                           Rehacer = los del proyecto, ver eventFilter)
        from .tramos_texto import TramosTexto                    # ✍ deshacer por tramos, como en un editor de texto
        self.tramos_texto = TramosTexto(self.ctrl, self.inspector)
        self.timeline.suggestion_clicked.connect(self._on_timeline_suggestion)
        self.timeline.selection_changed.connect(self._update_framing_mode)
        self.inspector.track_requested.connect(self.open_tracking)
        self.timeline.track_requested.connect(self.open_tracking)      # también con clic derecho en el clip
        self._copia_externa = True                    # 🖼 Ctrl+V: lo copiado fuera (imagen, archivos) si es lo último
        QApplication.clipboard().dataChanged.connect(self._al_cambiar_portapapeles)
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
        self.preview.canvas.pick_text_cb = self._text_at_now     # 📝 clic en un texto del visor = elegirlo
        self.preview.canvas.layer_picked.connect(self._pick_from_viewer)
        self.preview.canvas.transform_done.connect(self._tf_done)
        self.preview.canvas.transform_started.connect(self._tf_started)
        self.preview.canvas.transform_cancel.connect(self._tf_cancel)
        from . import menu_rapido                       # ⚡ menú rápido del clip en el hueco del visor (22/11)
        self.menu_rapido = menu_rapido.instalar(self)
        self.preview.canvas.subtitle_edit.connect(self._subtitle_edit_from_viewer)
        self.engine.time_changed.connect(lambda _t: self._update_transform_edit())
        self.ctrl.project_changed.connect(self._update_transform_edit)
        self.ctrl.project_changed.connect(lambda: self._update_region_edit())
        self.preview.canvas.framing_wheel.connect(lambda steps: self.inspector.nudge_framing(0, 0, steps))
        self.voice.media_selected.connect(self.transcript.set_media)
        self.voice.cut_rules_changed.connect(self.transcript.refresh)
        self.voice.suggestion_selected.connect(self.timeline.set_highlight_suggestion)
        self.voice.quick_review_requested.connect(lambda: self.open_quick_review("voz"))
        self.voice.subtitles_requested.connect(self.open_subtitles)
        self.voice.precargar_al_pasar(self.subtitles.btn_quick)        # (⚡ Subtítulos también transcribe)
        self.transcript.set_media(self.voice.media_id() or "")
        self.library.add_requested.connect(self._add_at_playhead)
        self.library.add_at_times_requested.connect(self._add_at_times)          # 🔑 en las palabras clave
        self.library.keyword_target = lambda: self.timeline.keyword_target(self.engine.time)
        from .keyword_arrange_ui import KeywordArranger
        self.kw_arranger = KeywordArranger(self)                                # ⚡ fila de palabras clave
        self.library.add_moment_requested.connect(self._add_moment)
        self.library.anim_requested.connect(self.open_image_anim)
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
        self.ctrl.project_replaced.connect(lambda *_: self.moments.limpiar())        # (resultados de otro proyecto)
        self.ctrl.project_replaced.connect(lambda *_: self._fill_edit_panel())       # (canciones y clips de este)
        self._build_actions()
        if _mcp_enabled():
            self.claude_bridge.start()
        self._motor_warning.connect(lambda t: self.statusBar().showMessage(t, 20000))
        QTimer.singleShot(20000, self._check_motor_soon)     # sin prisa, cuando ya estás editando
        QTimer.singleShot(900, self._bienvenida_si_toca)     # 👋 la primera vez: qué viene y qué es opcional
        from . import export_runner                          # 🧹 imágenes de subtítulos de exportaciones interrumpidas
        QTimer.singleShot(5000, export_runner.sweep_orphans)
        movidos = os.environ.get("RECLAIMER_DATOS_MOVIDOS")
        if movidos:                                           # (paths.app_data_dir: no se podía escribir junto al programa)
            QTimer.singleShot(2500, lambda: self.statusBar().showMessage(
                f"📦 En la carpeta de Reclaimer no se puede escribir: tus datos se guardan en {movidos}", 60000))
        self.apply_font_scale()
        self._update_title()
        self.statusBar().showMessage("Bienvenido. Empieza importando tu narración y tus clips (panel izquierdo).")

        from .saving import SaveManager
        self.saving = SaveManager(self)      # 💾 guardado en vivo y copias de seguridad (como Resolve)
        self._autosave = QTimer(self)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        # 👋 La primera vez que abres Reclaimer: la guía de primer uso (6 pasos; sale sola UNA vez, se salta cuando
        # quieras y vuelve en Ayuda → «Guía de primer uso»). No con un diálogo a la vista, un proyecto abriéndose o una
        # exportación (lo reintenta un rato). Nunca en las pruebas ni sin ventana. La guía larga sigue en F1.
        self.guia_primer_uso = None
        from .guia_primer_uso import al_arrancar as _guia_arranque, debe_mostrarse as _guia_debe
        if _guia_debe(self.settings):
            QTimer.singleShot(1200, lambda: _guia_arranque(self))

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
    def _poner_total_tl(self, *_a):
        """⏱ «/ duración total» al lado del reloj grande de la línea de tiempo."""
        lbl = getattr(self, "tl_total", None)
        if lbl is None:
            return
        try:
            total = self.ctrl.project.duration()
        except Exception:  # noqa: BLE001 - un reloj nunca para la edición
            return
        txt = "/ " + fmt_tc(total, self.ctrl.project.fps)
        if lbl.text() != txt:
            lbl.setText(txt)
            reloj = getattr(self, "tl_timecode", None)      # (si la barra no cabe y «/ total» se esconde —último
            if reloj is not None:                           #  recurso de _tl_fit_bar—, sigue en el tooltip del reloj)
                reloj.setToolTip("Tiempo del cabezal (horas:minutos:segundos:fotograma)\nDuración total: "
                                 + fmt_tc(total, self.ctrl.project.fps))

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
        self.tl_total = QLabel("/ 00:00:00:00")          # ⏱ la duración total de la línea de tiempo
        self.tl_total.setObjectName("dim")
        self.tl_total.setToolTip("Duración total del video en la línea de tiempo")
        lay.addSpacing(4)
        lay.addWidget(self.tl_total)
        lay.addSpacing(10)
        lay.addWidget(self.tl_name)
        lay.addSpacing(10)
        # ↶ ↷ Deshacer / Rehacer siempre a la vista (lo esencial que faltaba), activos según la pila de cambios
        self.btn_undo = QPushButton("↶ Deshacer")
        self.btn_redo = QPushButton("↷ Rehacer")
        for b_, tip_, slot_ in ((self.btn_undo, "Deshacer el último cambio (Ctrl+Z)", self.ctrl.undo_group.undo),
                                (self.btn_redo, "Rehacer lo deshecho (Ctrl+Y o Ctrl+Mayús+Z)", self.ctrl.undo_group.redo)):
            b_.setObjectName("tltool")
            b_.setToolTip(tip_)
            b_.setFocusPolicy(Qt.NoFocus)
            b_.clicked.connect(slot_)
            lay.addWidget(b_)
        self.ctrl.undo_group.canUndoChanged.connect(self.btn_undo.setEnabled)
        self.ctrl.undo_group.canRedoChanged.connect(self.btn_redo.setEnabled)
        self.btn_undo.setEnabled(self.ctrl.undo_group.canUndo())
        self.btn_redo.setEnabled(self.ctrl.undo_group.canRedo())
        lay.addSpacing(10)

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
        self.btn_dividir = btn("Dividir", "Dividir en el cabezal (Ctrl+B o S)", self._split)
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
        self.btn_burst.setVisible(False)        # (13/11: vive en «⋯ Más»; el botón queda para el código y los atajos)
        lay.addWidget(self.btn_burst)
        self.btn_eliminar = btn("Eliminar", "Eliminar seleccionados (Supr)", lambda: self._delete(False))
        from . import diseno as _Dz                 # (icono monocromo: si la barra no cabe, se quedan solo con él)
        self.btn_dividir.setIcon(_Dz.icono("scissors"))
        self.btn_eliminar.setIcon(_Dz.icono("trash-2"))
        btn("🗑 Vaciar", "Vaciar la línea de tiempo: quita todos los clips, textos y marcadores (tus archivos "
                       "siguen en Medios). Ctrl+Z lo devuelve todo.", self.clear_timeline)
        self.btn_bars = btn("▭ Quitar barras", "Quitar las barras negras de los videos (los clips seleccionados o, si "
                            "no hay ninguno, todos): se detectan solas y el video se encuadra como si no las tuviera.\n"
                            "Ctrl+Z las devuelve (o vuelve a pulsarlo).", self.remove_black_bars)
        btn("⚑", "Añadir marcador en el cabezal (M)", self._marker)
        btn("T", "Añadir texto en el cabezal (T)", lambda: self.ctrl.add_text(self.engine.time, 4.0, "Texto"))
        self.btn_titles = btn("Títulos", "Plantillas de título: un texto con estilo ya hecho (título grande, rótulo "
                                   "inferior, capítulo, meme, cita…) en el cabezal. Las ★ son las tuyas (Inspector → "
                                   "texto → «★ Guardar como plantilla»).")
        self.btn_titles.setMenu(self._titles_menu(self.btn_titles))
        from . import diseno as _Dt                 # (icono monocromo; sin sitio, solo el icono)
        self.btn_titles.setIcon(_Dt.icono("type"))
        lay.addSpacing(12)
        # 13/11: lo de uso frecuente, a la vista (antes solo con clic derecho o en un menú)
        self.btn_broll = btn("✨ B-roll", "Proponer B-roll: la IA elige clips de tu material para lo que dices "
                             "(panel IA ✨; nada se pone sin que lo aceptes)", self._toolbar_broll)
        self.btn_scenes = btn("🎬 Escenas", "Cambios de escena de los clips elegidos (sin IA: donde la imagen cambia "
                              "de golpe): cortarlos, también los cambios suaves, o solo poner un marcador en cada uno "
                              "(como Kdenlive). Ctrl+Z lo deshace.")
        sm = _QMenu(self.btn_scenes)
        sm.addAction("✂ Cortar en los cambios claros", lambda: self._toolbar_scenes("normal"))
        sm.addAction("✂ Cortar también en los suaves (menús, fundidos)", lambda: self._toolbar_scenes("alta"))
        sm.addSeparator()
        sm.addAction("⚑ Solo poner un marcador en cada cambio", lambda: self._toolbar_scenes("normal", True))
        self.btn_scenes.setMenu(sm)
        self.btn_vertical = btn("📱 Vertical", "Encuadre vertical que sigue la acción: los clips horizontales elegidos "
                                "llenan la pantalla 9:16 y el recorte sigue lo que pasa (Shorts y Edits)",
                                self._toolbar_vertical)
        self.ctrl.project_changed.connect(self._sync_vertical_btn)
        self.ctrl.project_replaced.connect(self._sync_vertical_btn)
        self._sync_vertical_btn()
        self.btn_thumb = btn("🖼 Miniatura", "Abrir el editor de la miniatura de este video", lambda: self.open_thumbnail())
        # (agrupación 20/11: B-roll vive en IA ✨, Miniatura es su página de abajo y exportar es la página Entrega;
        #  «Escenas» —cortar donde cambia el plano, NO la página Escenas— pasa a «⋯ Más → ✂ Cambios de plano»)
        # (decisión del usuario: exportar = la página «Entrega» de abajo, Ctrl+E y «⚡ Exportar rápido»; este botón ya
        #  no se ve —se conserva el objeto para quien lo use desde el código—)
        self._btn_export_tl = self.btn_export = btn("⬆ Exportar", "Exportar el video (Ctrl+E)", self.export)
        for b_ in (self.btn_broll, self.btn_thumb, self.btn_scenes, self._btn_export_tl):
            b_.setVisible(False)
        self.btn_scenes.setMenu(None)
        # ⋯ Más: lo de uso ocasional, a un clic y con su nombre (los atajos siguen igual)
        self.btn_more = _QTB()
        self.btn_more.setText("⋯ Más")
        self.btn_more.setObjectName("tltool")
        self.btn_more.setFocusPolicy(Qt.NoFocus)
        from . import diseno as _Dm                       # ✂ legible como los demás botones de la barra (era blanco)

        def _hoja_mas():
            c = _Dm.colores()
            return (f"QToolButton {{ background: {c['relieve']}; border: 1px solid {c['borde']}; border-radius: 5px; "
                    f"padding: 5px 12px; color: {c['texto']}; }}"
                    f"QToolButton:hover {{ background: {c['relieve_hi']}; border-color: {c['borde_hi']}; }}"
                    f"QToolButton:pressed {{ background: {c['fondo']}; }}"
                    "QToolButton::menu-indicator { image: none; width: 0px; }")
        _Dm.poner_hoja(self.btn_more, _hoja_mas)
        self.btn_more.setPopupMode(_QTB.InstantPopup)
        self.btn_more.setToolTip("Más herramientas: ⚡ Ráfaga de cortes al ritmo y 〰 Curvas de volumen/opacidad")
        more = _QMenu(self.btn_more)
        cm_ = more.addMenu("✂ Cambios de plano")
        cm_.setToolTipsVisible(True)
        cm_.setToolTip("Donde la imagen de los clips elegidos cambia de golpe (sin IA): cortarlos, también los cambios "
                       "suaves, o solo poner un marcador en cada uno (como Kdenlive). Ctrl+Z lo deshace.")
        for a_ in sm.actions():
            cm_.addAction(a_)
        self.menu_cambios_plano = cm_
        rm = more.addMenu("⚡ Ráfaga de cortes al ritmo")
        for a_ in bm.actions():
            rm.addAction(a_)
        self.act_curves = more.addAction("〰 Curvas de volumen y opacidad (Mayús+C)")
        self.act_curves.setCheckable(True)
        self.act_curves.triggered.connect(lambda on: (self.tool_curves.setChecked(on), self.timeline.set_curves(on)))
        more.aboutToShow.connect(lambda: self.act_curves.setChecked(self.tool_curves.isChecked()))
        more.aboutToShow.connect(lambda m_=more: self._tl_mas_extra(m_))     # (lo que la barra estrecha mandó aquí)
        self.btn_more.setMenu(more)
        lay.addWidget(self.btn_more)
        self.tool_curves.setVisible(False)       # (13/11: vive en «⋯ Más»; Mayús+C sigue igual)
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
        self.timeline.anim_requested.connect(self.open_image_anim)
        self.timeline.scene_requested.connect(lambda a, b: self.open_scenes(rango=(a, b)))
        self.timeline.scene_open_requested.connect(lambda eid: self.open_scenes(escena_id=eid))
        self.timeline.template_requested.connect(self.put_template)
        self.timeline.scene_cuts_requested.connect(
            lambda ids, sens: self.cut_scenes(ids, sens.replace("+marcas", ""), sens.endswith("+marcas")))
        self.timeline.topics_requested.connect(self.open_topics_tool)
        self.library.keywords_requested.connect(lambda mids: self.open_keywords(mids))
        self.library.obs_marks_requested.connect(lambda mids: self.read_obs_marks(mids))
        self.preview.canvas.comp_drop.connect(self._comp_drop)
        self.preview.canvas.comp_accion.connect(lambda nombre, args: __import__("editoria.core.composicion", fromlist=["accion"]).accion(self.ctrl, self.engine.time, nombre, args))   # ⊞ vaciar, ⇄, encuadrar… un hueco
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
        from PySide6.QtWidgets import QSlider as _QSl      # 🔍 deslizador de zoom (como Resolve), entre − y +
        self.zoom_slider = _QSl(Qt.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFocusPolicy(Qt.NoFocus)
        self.zoom_slider.setFixedWidth(84)
        self.zoom_slider.setToolTip("Zoom de la línea de tiempo: arrastra = acercar o alejar alrededor del cabezal "
                                    "(también Ctrl+rueda, − y +)")
        self.zoom_slider.valueChanged.connect(self._zoom_desde_deslizador)
        self.timeline.vista_cambia.connect(self._sync_zoom_slider)
        lay.addWidget(self.zoom_slider)
        btn("+", "Acercar (+)", lambda: self.timeline.zoom(1.5))
        from . import diseno as _Dz
        self.btn_detalle = _Dz.BotonIcono("search", "Detalle: 10 s alrededor del cabezal (otra vez = el zoom de antes)",
                                          plano=False)
        self.btn_detalle.setObjectName("tltool")
        self.btn_detalle.setIcon(_Dz.icono("search"))         # (el icono también como QIcon: lo pinta BotonIcono)
        self.btn_detalle.setFocusPolicy(Qt.NoFocus)
        self.btn_detalle.clicked.connect(self.timeline.detalle)
        lay.addWidget(self.btn_detalle)
        btn("⤢", "Ver toda la timeline (Ctrl+0)", self.timeline.fit)
        # 📐 Si no cabe todo, los botones con nombre enseñan solo su icono (el nombre sigue en el tooltip) y la barra
        # nunca obliga a la ventana a ser más ancha que tu pantalla.
        from PySide6.QtWidgets import QLayout as _QL
        lay.setSizeConstraint(_QL.SetNoConstraint)
        bar.setMinimumWidth(1)                   # (explícito: manda sobre lo que pide su contenido)
        self.tl_name.setMaximumWidth(220)
        self._tl_compact = {}
        for b_ in bar.findChildren(QPushButton) + [self.btn_more]:
            t_ = b_.text()
            if " " in t_ and not t_[0].isalnum():               # «✨ B-roll» → «✨»
                self._tl_compact[b_] = (t_, t_.split(" ", 1)[0])
        for b_ in (self.btn_dividir, self.btn_eliminar, self.btn_titles):   # (con icono: compactos = solo el icono)
            self._tl_compact[b_] = (b_.text(), "")
        self._tl_compact[self.btn_more] = ("⋯ Más", "Más")      # (compacto, la palabra: tres puntitos no se leían)
        self._tl_bar = bar
        bar.installEventFilter(self)
        self.tool_curves.toggled.connect(        # 〰 Curvas activas: «⋯ Más» lo dice (el botón de Curvas no se ve)
            lambda on: self._tl_set(self.btn_more, "⋯ Más 〰" if on else "⋯ Más", "Más 〰" if on else "Más"))
        return bar

    def _tl_set(self, b_, full: str, short: str | None = None):
        """Cambia el texto de un botón de la barra respetando el modo compacto (y la reajusta)."""
        if not hasattr(self, "_tl_compact"):
            b_.setText(full)
            return
        self._tl_compact[b_] = (full, short or full.split(" ", 1)[0])
        b_.setText(full)
        self._tl_refit()

    def _tl_refit(self, *_a):
        """Lo que enseña la barra cambió (⚠ cortes, 📱, vistas, nombre…): se vuelve a encajar."""
        if getattr(self, "_tl_bar", None) is not None:
            QTimer.singleShot(0, self._tl_fit_bar)

    def _tl_ancho_minimo(self) -> int:
        """Lo que necesita la barra de la línea de tiempo con todo en modo compacto (solo iconos, sin el nombre del
        proyecto): por debajo de esto sus botones se cortarían. Se mide de verdad (con lo que se ve ahora) y se
        recuerda mientras no cambie lo que enseña ni la letra."""
        bar = getattr(self, "_tl_bar", None)
        if bar is None:
            return 0
        import shiboken6
        from .responsive import widgets_en               # (sin itemAt: ver responsive.py)
        # (por su puntero de C++: id() de un envoltorio de PySide cambia de una vez a otra y la medida se repetía sin
        #  fin —cada medida cambia textos, Qt avisa de un cambio de distribución y se volvía a medir—)
        firma = (tuple(shiboken6.getCppPointer(w)[0] for w in widgets_en(bar.layout())
                       if (not w.isHidden() or w in getattr(self, "_tl_a_mas", [])) and w is not self.tl_name
                       and w is not self.tl_total and w is not getattr(self, "zoom_slider", None)
                       and w is not getattr(self, "btn_detalle", None)),
                 bar.font().pointSizeF(), tuple(c[1] for c in self._tl_compact.values()))
        guardado = getattr(self, "_tl_min_cache", None)
        if guardado is not None and guardado[0] == firma:
            return guardado[1]
        if getattr(self, "_tl_ocupada", False):            # (a medias de colocar la barra: lo último medido vale)
            return guardado[1] if guardado is not None else 0
        self._tl_ocupada = True
        try:
            return self._tl_medir_minimo(bar, firma)
        finally:
            self._tl_ocupada = False

    def _tl_medir_minimo(self, bar, firma) -> int:
        antes = {b_: b_.text() for b_ in self._tl_compact}
        nombre = self.tl_name.isVisibleTo(bar)
        total = self.tl_total.isVisibleTo(bar)
        sl = getattr(self, "zoom_slider", None)
        desl = sl.isVisibleTo(bar) if sl is not None else False
        extra = [w_ for w_ in [getattr(self, "btn_detalle", None)] + list(getattr(self, "_tl_a_mas", [])) if w_]
        vis_extra = [w_.isVisibleTo(bar) for w_ in extra]
        for b_, (_full, short) in self._tl_compact.items():
            b_.setText(short)
        self.tl_name.setVisible(False)
        self.tl_total.setVisible(True)          # («/ total», el deslizador, «Detalle» y lo que fue a «Más» cuentan:
        if sl is not None:                      #  esconderlos es el último recurso, no lo normal)
            sl.setVisible(True)
        for w_ in extra:
            w_.setVisible(True)
        ancho = bar.layout().sizeHint().width()
        for w_, v_ in zip(extra, vis_extra):
            w_.setVisible(v_)
        for b_, t_ in antes.items():
            b_.setText(t_)
        self.tl_name.setVisible(nombre)
        self.tl_total.setVisible(total)
        if sl is not None:
            sl.setVisible(desl)
        self._tl_min_cache = (firma, ancho)
        return ancho

    def biblioteca_alto(self) -> bool:
        """«◧ A todo el alto» (Ventana y la barra de arriba): ¿los paneles de la izquierda llegan hasta abajo?"""
        return str(self.settings.value("ventana/biblioteca_alto", "false")).lower() == "true"

    def set_biblioteca_alto(self, on: bool):
        self.settings.setValue("ventana/biblioteca_alto", "true" if on else "false")
        for a in (getattr(self, "_btn_alto", None), getattr(self, "_act_alto", None)):
            if a is not None and a.isChecked() != on:
                a.setChecked(on)
        self._esquina_biblioteca()

    def _esquina_biblioteca(self):
        """↔ De entrada la línea de tiempo ocupa todo el ancho de abajo (el usuario: «por defecto la línea del tiempo
        debería estar como estaba antes»). Con «◧ A todo el alto», como DaVinci: los paneles de la izquierda (la
        biblioteca) llegan hasta abajo y la línea de tiempo empieza a su derecha, sin poder taparlo todo: la biblioteca
        nunca baja de lo que pide su contenido y no puede ensancharse tanto que la barra de la línea de tiempo deje de
        caber ni con solo iconos (se le pone un ancho máximo). Si ni con la biblioteca en su mínimo cabe (pantallas
        pequeñas), la línea de tiempo vuelve a todo el ancho: nunca se corta un botón. El Inspector se queda encima de
        la línea de tiempo, como en DaVinci (con las dos esquinas, a 1366 px la línea de tiempo se quedaba en ~660 px)."""
        if not hasattr(self, "docks"):
            return
        tl = self.docks.get("timeline")
        sin_limite = 16777215
        quiero, maximo = Qt.BottomDockWidgetArea, sin_limite
        if self.biblioteca_alto() and tl is not None and not tl.isFloating() and \
                self.dockWidgetArea(tl) == Qt.BottomDockWidgetArea:
            izq = [d for k, d in self.docks.items() if k != "timeline" and not d.isHidden() and not d.isFloating()
                   and self.dockWidgetArea(d) == Qt.LeftDockWidgetArea]
            if izq:
                necesita = self._tl_ancho_minimo() + 8         # (+ el separador)
                minimo_izq = max(max(self.PANEL_MIN, d.minimumWidth(), d.minimumSizeHint().width()) for d in izq)
                if self.width() - minimo_izq >= necesita:
                    quiero, maximo = Qt.LeftDockWidgetArea, self.width() - necesita
        for k, d in self.docks.items():             # (la biblioteca, sin poder comerse la línea de tiempo)
            lim = maximo if (maximo != sin_limite and not d.isFloating()
                             and self.dockWidgetArea(d) == Qt.LeftDockWidgetArea) else sin_limite
            if k != "timeline" and d.maximumWidth() != lim:
                d.setMaximumWidth(lim)
        if self.corner(Qt.BottomLeftCorner) != quiero:
            self.setCorner(Qt.BottomLeftCorner, quiero)
            QTimer.singleShot(0, self._ensure_timeline_size)
            QTimer.singleShot(0, self._tl_fit_bar)       # (revisión: que la barra no se vea cortada ~0,3 s)
        # (encendido pero sin sitio en esta pantalla: el botón, atenuado y diciéndolo en su tooltip)
        sin_efecto = self.biblioteca_alto() and quiero != Qt.LeftDockWidgetArea
        btn = getattr(self, "_btn_alto", None)
        if btn is not None and bool(btn.property("sin_efecto")) != sin_efecto:
            btn.setProperty("sin_efecto", sin_efecto)
            base = btn.property("tip_base") or btn.toolTip()
            btn.setProperty("tip_base", base)
            btn.setToolTip(base + ("\n\n⚠ Ahora no cabe en esta pantalla: la línea de tiempo no tendría sitio para "
                                   "todos sus botones a la derecha de la biblioteca, así que sigue a todo el ancho."
                                   if sin_efecto else ""))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "_tl_bar", None) and ev.type() == ev.Type.Resize:
            self._tl_fit_bar()                   # (en el acto: que no se vea la barra aplastada un instante)
        ins = getattr(self, "inspector", None)
        if ins is not None and obj is getattr(ins, "text_edit", None) and \
                ev.type() in (ev.Type.ShortcutOverride, ev.Type.KeyPress):
            # 🧭 tras «T» el foco está en el cuadro del texto: Esc vuelve a la línea de tiempo (como en «Texto en
            # pantalla») y Ctrl+Z, mientras el cuadro no tenga nada suyo que deshacer, deshace el texto recién creado
            if ev.key() == Qt.Key_Escape:
                if ev.type() == ev.Type.KeyPress:
                    self.timeline.setFocus()
                ev.accept()
                return True
            accion = self._atajo_historial(ev)
            if accion is not None:
                # ↶ UN solo historial: Deshacer/Rehacer (con los atajos que tengan) son siempre los del proyecto, no los
                # del cuadro (antes, tras «T» + escribir, un Ctrl+Z deshacía en el cuadro y el siguiente no hacía nada
                # visible). Lo escrito y aún sin guardar se guarda antes, y el cuadro se pone al día después.
                if ev.type() == ev.Type.ShortcutOverride:
                    if ins._txt_timer.isActive():
                        ins._txt_timer.stop()
                        ins._set_text(content=obj.toPlainText())
                    QTimer.singleShot(0, self._cuadro_texto_al_dia)
                return True                      # (el cuadro no se lo queda: salta el Deshacer/Rehacer del editor)
        return super().eventFilter(obj, ev)

    def _atajo_historial(self, ev):
        """La acción Deshacer o Rehacer de la ventana cuyo atajo (el que tenga asignado) es esa tecla; si no, None."""
        from PySide6.QtGui import QKeySequence as _QKS
        try:
            tecla = _QKS(ev.keyCombination())
        except (AttributeError, TypeError):
            return None
        for a in (getattr(self, "_act_deshacer", None), getattr(self, "_act_rehacer", None)):
            if a is not None and any(s.matches(tecla) == _QKS.ExactMatch for s in a.shortcuts()):
                return a
        return None

    def _cuadro_texto_al_dia(self):
        """Tras Deshacer/Rehacer desde el cuadro del texto del Inspector: enseña lo que dice ahora el texto; si el texto
        ya no está (se deshizo al crearlo), el foco vuelve a la línea de tiempo."""
        ins = self.inspector
        ed = ins.text_edit
        c = self.ctrl.project.clips.get(ins._ids[0]) if len(ins._ids) == 1 else None
        if c is None or c.text is None or not ed.isVisible():
            if ed.hasFocus() or QApplication.focusWidget() is None or ins.isAncestorOf(QApplication.focusWidget()):
                self.timeline.setFocus()
            return
        txt = str(c.text.get("content", ""))
        viejo = ed.toPlainText()
        if viejo != txt:
            from .tramos_texto import donde_cambio
            ins._loading = True
            try:
                ed.setPlainText(txt)
                cur = ed.textCursor()
                cur.setPosition(donde_cambio(viejo, txt))       # (el cursor, donde estaba el cambio)
                ed.setTextCursor(cur)
            finally:
                ins._loading = False
        self.tramos_texto.cortar()                   # (lo que escribas ahora es un paso nuevo)

    def _tl_reloj_ancho(self):
        """⏱ El reloj grande (y «/ total») con su ancho de verdad: el de «00:00:00:00» en SU letra monoespaciada (la de
        la hoja de estilo, ya aplicada). Así el diseño nunca lo aprieta por debajo de su texto: si falta sitio, antes
        se quedan en solo icono los botones (_tl_fit_bar) y después se esconde el nombre del proyecto."""
        for lbl, muestra in ((getattr(self, "tl_timecode", None), "00:00:00:00"),
                             (getattr(self, "tl_total", None), "/ 00:00:00:00")):
            if lbl is None:
                continue
            lbl.ensurePolished()
            fm = lbl.fontMetrics()
            m = lbl.contentsMargins()
            ancho = max(fm.horizontalAdvance(muestra), fm.horizontalAdvance(lbl.text())) + m.left() + m.right() + 2
            if lbl.minimumWidth() != ancho:
                lbl.setMinimumWidth(ancho)

    def _tl_fit_bar(self):
        """Modo compacto de la barra de la línea de tiempo según el ancho que tiene."""
        bar = getattr(self, "_tl_bar", None)
        if bar is None:
            return
        # (✂ nunca dos a la vez: enseñar o esconder botones mientras se mide puede colocar la barra al momento y volver
        #  a entrar aquí; la medida de dentro escondía después un botón que la de fuera ya había devuelto a la barra
        #  —escondido pero fuera de «Más», y el diseño lo saltaba dejándolo encima de otro—. Se repite al acabar.)
        if getattr(self, "_tl_ocupada", False):
            QTimer.singleShot(0, self._tl_fit_bar)
            return
        self._tl_ocupada = True
        try:
            self._tl_colocar(bar)
        finally:
            self._tl_ocupada = False

    def _tl_colocar(self, bar):
        self._tl_reloj_ancho()
        for b_ in getattr(self, "_tl_a_mas", []):          # (lo que mandó a «Más» la vez anterior, otra vez a la vista)
            b_.setVisible(True)
        self._tl_a_mas = []
        from PySide6.QtWidgets import QToolButton as _QTBf
        for b_ in bar.findChildren(QPushButton) + bar.findChildren(_QTBf):
            b_.setMinimumWidth(0)                          # (medir de cero: con otra letra, los de antes no valen)
            b_.ensurePolished()
        for b_, (full, _short) in self._tl_compact.items():   # medir con los nombres completos
            b_.setText(full)

        def cabe():
            bar.layout().invalidate()                      # (sin lo memorizado por el diseño: medidas de AHORA)
            return bar.layout().sizeHint().width() <= bar.width()
        # escalones, de lo menos necesario a lo más: deslizador de zoom → «Detalle» → nombres a iconos → nombre del
        # proyecto → «/ total» → botones a «Más» (siguen ahí, en su menú). Así nada se monta encima de nada.
        sl = getattr(self, "zoom_slider", None)
        bd = getattr(self, "btn_detalle", None)
        for w_ in (sl, bd):
            if w_ is not None:
                w_.setVisible(True)
        self.tl_total.setVisible(True)
        for w_ in (sl, bd):
            if w_ is not None and not cabe():
                w_.setVisible(False)
        # de uno en uno, primero lo menos importante (Exportar y B-roll conservan su nombre hasta el final)
        self.tl_name.setVisible(True)
        prio = [getattr(self, n, None) for n in ("btn_bars", "btn_thumb", "btn_scenes", "btn_vertical",
                                                  "btn_more", "btn_titles", "btn_broll", "btn_export", "btn_dividir",
                                                  "btn_eliminar",
                                                  "btn_undo", "btn_redo")]
        orden = [b_ for b_ in self._tl_compact if b_ not in prio] + [b_ for b_ in prio if b_ in self._tl_compact]
        for b_ in orden:
            if bar.layout().sizeHint().width() <= bar.width():
                break
            pareja = (self.btn_undo, self.btn_redo) if b_ in (self.btn_undo, self.btn_redo) else (b_,)
            for b2 in pareja:                          # (↶ ↷ con su nombre hasta el final, y siempre los dos igual)
                if b2 not in self._tl_compact:
                    continue
                full, short = self._tl_compact[b2]
                b2.setText(short)
                if not b2.toolTip().startswith(full):
                    b2.setToolTip(full + " — " + b2.toolTip())
        if not cabe():                                         # sin el nombre del proyecto
            self.tl_name.setVisible(False)
        if not cabe():                                         # sin «/ total» (en el tooltip del reloj)
            self.tl_total.setVisible(False)
        if not cabe():                                         # y lo que quede, a «⋯ Más» (de lo menos usado a lo más)
            for b_ in self._tl_para_mas(bar):
                if cabe():
                    break
                b_.setVisible(False)
                self._tl_a_mas.append(b_)
        # ✂ nunca un texto cortado: el diseño no los aprieta por debajo de lo que piden (si no caben con nombre, ya
        #   son solo icono). TAMBIÉN las herramientas de un solo símbolo (➤ ✂ ⇿ ∩ 🔗 ⚑ T − + ⤢): sin mínimo, con la
        #   barra justa Qt les quitaba 2 px y el símbolo salía cortado (36 de 38 px en Edits)
        for b_ in list(self._tl_compact) + [w for w in bar.findChildren(QPushButton) if w not in self._tl_compact]:
            if b_.isVisible() and b_.text():
                b_.setMinimumWidth(b_.sizeHint().width())
        # (esto puede pasar EN MEDIO de que el diseño coloca la barra —al cambiar de tamaño—: lo que se volvió a ver o se
        #  escondió aquí no se recolocaba y un botón que vuelve de «Más» se quedaba en su sitio viejo, encima de otro)
        from editoria.ui.responsive import widgets_en as _we
        for w_ in _we(bar.layout()):                    # (lo memorizado de cada pieza —medida, si se ve— fuera)
            w_.updateGeometry()
        bar.layout().invalidate()
        bar.layout().activate()
        QTimer.singleShot(0, bar.layout().activate)

    def _tl_para_mas(self, bar) -> list:
        """Los botones que pueden ir a «⋯ Más» cuando la barra no cabe, de lo menos usado a lo más (deshacer, rehacer,
        selección, cuchilla, dividir y eliminar se quedan siempre)."""
        todos = [b_ for b_ in bar.findChildren(QPushButton) if b_.isVisibleTo(bar)]

        def por(sim):
            if sim == "titulos":
                return getattr(self, "btn_titles", None)
            for b_ in todos:
                full = self._tl_compact.get(b_, (b_.text(), ""))[0]
                if b_.text() == sim or full.startswith(sim):
                    return b_
            return None
        out = []
        for sim in ("▭", "🗑", "titulos", "T", "⚑", "⤢", "🔗", "∩", "⇿", "−", "+"):
            b_ = por(sim)
            if b_ is not None and b_.isVisibleTo(bar) and b_ not in out:
                out.append(b_)
        return out

    def _tl_mas_extra(self, menu):
        """En «⋯ Más», los botones que la barra estrecha mandó aquí (mismo nombre del tooltip, mismo efecto)."""
        for a_ in [a_ for a_ in menu.actions() if a_.property("de_la_barra")]:
            menu.removeAction(a_)
        ocultos = [b_ for b_ in getattr(self, "_tl_a_mas", []) if not b_.isVisible()]
        if not ocultos:
            return
        sep = menu.addSeparator()
        sep.setProperty("de_la_barra", True)
        for b_ in ocultos:
            nombre = (b_.toolTip() or b_.text()).split("\n")[0].split(" — ")[0]
            a_ = menu.addAction(nombre)
            a_.setProperty("de_la_barra", True)
            if b_.isCheckable():
                a_.setCheckable(True)
                a_.setChecked(b_.isChecked())
            a_.setToolTip(b_.toolTip())
            a_.triggered.connect(lambda _=False, bb=b_: bb.click())

    # ------------------------------------------------------------ botones de la barra de la línea de tiempo
    def _sel_video_clips(self) -> list[str]:
        p = self.ctrl.project
        return [i for i in sorted(self.timeline.selected) if i in p.clips and p.clips[i].text is None
                and (p.media_of(p.clips[i]) is not None and p.media_of(p.clips[i]).kind == "video")]

    def _toolbar_broll(self):
        self.show_panel(self.ai_panel)
        self.ai_panel.propose()

    def _toolbar_scenes(self, sensitivity: str = "normal", markers: bool = False):
        ids = self._sel_video_clips()
        if not ids:
            self.statusBar().showMessage("🎬 Elige antes los clips de video (clic en uno; Ctrl+clic para varios).", 6000)
            return
        self.cut_scenes(ids, sensitivity, markers)

    def _toolbar_vertical(self):
        ids = self._sel_video_clips()
        if not ids:
            self.statusBar().showMessage("📱 Elige antes los clips horizontales que quieres encuadrar en vertical.", 6000)
            return
        self.follow_action(ids)

    def _sync_vertical_btn(self, *_):
        """📱 Solo tiene sentido en un proyecto vertical (Shorts / Edits)."""
        p = self.ctrl.project
        b = getattr(self, "btn_vertical", None)
        if b is not None:
            b.setVisible(p.height > p.width)
            self._tl_refit()

    def _sync_cut_badge(self, n: int):
        """⚠ N cortes: el contador y ◀ ▶ solo se ven si hay alguno que revisar."""
        self.cut_badge.setText(f"⚠ {n} corte{'s' if n != 1 else ''}" if n else "")
        for w in (self.cut_badge, self.btn_cut_prev, self.btn_cut_next):
            w.setVisible(n > 0)
        self._tl_refit()

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

    def _cut_panel_visible(self, vis: bool):
        """✂ Con el panel de cortes a la vista, su corte lleva la línea roja en la pista; oculto, ninguno."""
        cf = self.cut_fix
        if vis and cf is not None and cf.track_id:
            self.timeline.set_cut_issue_selected(cf.track_id, cf.t)
        elif not vis:
            self.timeline.set_cut_issue_selected(None, None)

    def _open_cut_issue(self, k: int):
        """Abre (o recoloca) el panel de ajuste del corte k de la línea de tiempo."""
        issues = self.timeline.cut_issues
        if not (0 <= k < len(issues)):
            return
        self.cut_fix_panel().show_issue(issues[k]["track_id"], issues[k]["t"])

    def cut_fix_panel(self):
        """✂ El panel de cortes, creado y ACOPLADO (pestaña de la derecha, junto al Inspector) la primera vez. Lo usan
        también la revisión guiada y el montaje guiado (antes lo creaban suelto, flotando en una esquina)."""
        if self.cut_fix is None:
            from .cut_fix import CutFixPanel
            self.cut_fix = CutFixPanel(self)
            d = self._dock("cortes", "✂ Corte de audio", self.cut_fix)
            self.addDockWidget(Qt.RightDockWidgetArea, d)
            self._sitio_sin_pestanas("cortes")             # (debajo del Inspector: sin fila de pestañas repetida)
            d.visibilityChanged.connect(self._cut_panel_visible)
            # (tras Ctrl+Z o «✓ Quitar todos los avisos», la lista y el dibujo al día)
            self.timeline.cut_issues_changed.connect(
                lambda _n: self.cut_fix._refresh() if self.cut_fix.isVisible() and self.cut_fix.track_id else None)
            QTimer.singleShot(0, self._ajustar_paneles)        # (un panel nuevo: tampoco se corta)
        return self.cut_fix

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

    # ☰ Icono de cada panel (monocromo) para las pestañas que no caben con su nombre
    ICONO_PANEL = {"media": "▤", "effects": "✦", "ai": "✧", "moments": "⌕", "clips": "⚷", "kw_folders": "▣",
                   "inspector": "⚙", "voice": "✂", "transcript": "¶", "subtitles": "❞", "history": "↺",
                   "scopes": "▥", "guide": "?", "tasks": "◈", "guided": "⌖", "material": "▦", "edit_opts": "♫",
                   "edit_clips": "♪", "cortes": "✄", "voz_ia": "≋", "kw_buscar": "⌕",
                   "audio_mix": "∿", "sounds": "♬", "fx_trans": "⧉", "fx_efectos": "✦", "fx_filtros": "◐",
                   "fx_figuras": "▭", "memes": "☺", "descargas_web": "⇩", "voz_texto": "¶", "audio": "∿",
                   "palabras": "⚷"}

    def _llenar_menu_paneles(self):
        """☰ Paneles: todos, agrupados por lado; el que eliges se muestra y se pone delante."""
        m = self._menu_paneles
        m.clear()
        lados = ((Qt.RightDockWidgetArea, "Derecha"), (Qt.LeftDockWidgetArea, "Izquierda"),
                 (Qt.BottomDockWidgetArea, "Abajo"), (Qt.TopDockWidgetArea, "Arriba"))
        for area, nombre in lados:
            docks = [(k, d) for k, d in self.docks.items() if k != "timeline" and not d.isFloating()
                     and self.dockWidgetArea(d) == area and not getattr(d, "absorbido", False)]
            if not docks:
                continue
            m.addSection(nombre)
            for k, d in docks:
                a = m.addAction(f"{self.ICONO_PANEL.get(k, '•')}  {self._nombre_panel(d)}",
                                lambda k_=k: self._mostrar_desde_menu(k_))
                a.setCheckable(True)
                a.setChecked(d.isVisible() and not d.visibleRegion().isEmpty())
        for nombre_g, clave_g, acordeon in (("Voz y texto", "voz_texto", getattr(self, "voz_texto", None)),
                                            ("Limpieza y mezcla", "audio", getattr(self, "audio_panel", None))):
            if acordeon is None:
                continue
            m.addSection(nombre_g)                       # (sus secciones, a un clic: nada se pierde)
            for k in acordeon.claves():
                m.addAction("    " + acordeon.titulo(k),
                            lambda d_=clave_g, k_=k: self.abrir_seccion(d_, k_))
        pal = getattr(self, "_pal_tabs", None)
        if pal is not None:
            m.addSection("Palabras clave")               # (sus pestañas, a un clic)
            for i in range(pal.count()):
                m.addAction("    " + pal.tabTextCompleto(i), lambda w_=pal.widget(i): self.show_panel(w_))
        flot =[(k, d) for k, d in self.docks.items() if d.isFloating() and not getattr(d, "absorbido", False)]
        if flot:
            m.addSection("Sueltos")
            for k, d in flot:
                m.addAction(f"{self.ICONO_PANEL.get(k, '•')}  {self._nombre_panel(d)}",
                            lambda k_=k: self._mostrar_desde_menu(k_))

    def _mostrar_desde_menu(self, k: str):
        """☰ Paneles → un panel: se enseña y se pone delante. Los de 🔑 Palabras clave y las columnas de ✦ Efectos solo
        viven en su página: fuera de ella, el menú lleva a su página (show_panel), nunca los deja sueltos en Editar."""
        d = self.docks[k]
        if getattr(d, "absorbido", False):
            self.show_panel(d.panel)
            return
        if k in self.SIN_PESTANAS:
            self._sitio_sin_pestanas(k)
        d.show()
        d.raise_()

    _ORDEN_VENTANA = ("media", "effects", "ai", "moments", "descargas_web", "memes", "voz_texto", "palabras", "audio",
                      "clips", "kw_buscar", "kw_folders",
                      "fx_trans", "fx_efectos", "fx_filtros", "fx_figuras",
                      "inspector", "voice", "audio_mix", "sounds", "transcript",
                      "subtitles", "voz_ia", "material", "edit_opts", "edit_clips", "history", "scopes", "guided",
                      "tasks", "cortes", "guide", "timeline")

    def _llenar_menu_ventana(self):
        """Menú «Ventana»: cada panel con su casilla (encender o cerrar); ninguno se queda fuera."""
        m = getattr(self, "_menu_ventana", None)
        if m is None:
            return
        for a in list(m.actions()):
            if a is self._sep_ventana:
                break
            m.removeAction(a)
        claves = [k for k in self._ORDEN_VENTANA if k in self.docks] + \
            [k for k in self.docks if k not in self._ORDEN_VENTANA]
        claves = [k for k in claves if not getattr(self.docks[k], "absorbido", False)]
        acts = [self.docks[k].toggleViewAction() for k in claves]
        if "cortes" not in self.docks:                 # (✂ se crea al usarlo: hasta entonces, una entrada que lo abre)
            if getattr(self, "_act_cortes", None) is None:
                self._act_cortes = QAction("✂ Corte de audio", self)
                self._act_cortes.triggered.connect(self.abrir_corte_audio)
            acts.append(self._act_cortes)
        m.insertActions(self._sep_ventana, acts)

    @staticmethod
    def _nombre_panel(d) -> str:
        return getattr(d, "nombre", "") or d.windowTitle()

    def _poner_titulo(self, d, texto: str):
        """El título del panel (lo que sale en su pestaña); el menú «Ventana» sigue con el nombre completo."""
        if d.windowTitle() != texto:
            d.setWindowTitle(texto)
            d.toggleViewAction().setText(self._nombre_panel(d))

    PESTANA_RELLENO = 22       # (lo que una pestaña añade a su texto; se mide de verdad en cuanto hay pestañas)
    HOJA_SIN_PESTANAS = ("QTabBar { max-height: 0px; } QTabBar::tab { height: 0px; min-height: 0px; max-height: 0px; "
                         "padding: 0px; margin: 0px; border: none; font-size: 1px; } "
                         "QTabBar QToolButton { max-height: 0px; max-width: 0px; }")

    def _nombre_limpio(self, d) -> str:
        """El nombre de un panel sin los emojis de color («🔎 Momentos» → «Momentos», «IA ✨» → «IA»): el de las
        pestañas y los interruptores (el menú Ventana sigue con el suyo)."""
        import re
        nombre = self._nombre_panel(d)
        partes = [x for x in nombre.split() if re.search(r"\w", x)]
        return " ".join(partes) or nombre

    def _icono_pestaña(self, k: str):
        """El icono monocromo del panel (ICONO_PANEL) para su pestaña (se guarda: no se dibuja en cada repaso)."""
        cache = self.__dict__.setdefault("_iconos_pestaña", {})
        if k not in cache:
            from .theme import TEXT_DIM, glyph_icon
            cache[k] = glyph_icon(self.ICONO_PANEL.get(k, "•"), 14, TEXT_DIM, "#ffffff")
        return cache[k]

    def _pestañas_que_caben(self):
        """Las pestañas de los paneles, con su NOMBRE COMPLETO (fase 1; nunca «…»): en una fila si caben; si no, en DOS
        FILAS de pestañas (_PestanasEnDosFilas, encima de la fila de Qt, que se hace el doble de alta); solo si ni así
        caben, su icono (el nombre, al pasar el ratón). Solo cuenta lo que se ve: el ancho de cada fila de pestañas de
        la distribución de ahora (no las filas viejas que deja Qt): la etiqueta no cambia sola si no se toca nada.
        (Qt reescribe el texto de cada pestaña con el título del panel: por eso se cambia el título, no la pestaña.)"""
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QTabBar
        import shiboken6
        por_puntero = {shiboken6.getCppPointer(d)[0]: (k, d) for k, d in self.docks.items()}
        en_fila = set()                                   # (los que están en una fila de pestañas a la vista)
        for tb in self.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly):
            capa = getattr(tb, "_dos_filas", None)
            if not tb.isVisible() or not tb.count():
                if capa is not None and capa.activa:      # (Qt retira la fila y luego la reutiliza para otro grupo)
                    capa.quitar()
                continue
            if not getattr(tb, "_vigilada", False):
                tb._vigilada = True
                tb.installEventFilter(self._vigia_pestañas)
                # (sin cambiar su modo de «…»: con ElideNone Qt pedía laterales más anchos y el visor se cortaba; los
                #  nombres en una fila solo se ponen si caben enteros, medidos de verdad)
            grupo = [por_puntero.get(tb.tabData(i)) for i in range(tb.count())]
            if any(g is None for g in grupo):
                continue
            # (Qt deja filas viejas «visibles» fuera de la ventana: solo cuenta si de verdad está en pestaña con otros)
            if not any(self.tabifiedDockWidgets(d) for _k, d in grupo) or tb.width() <= 0:
                continue
            sin_fila = all(k in getattr(self, "interruptores", {}) for k, _d in grupo)
            if not sin_fila and tb.styleSheet() == self.HOJA_SIN_PESTANAS:
                tb.setStyleSheet("")        # (revisión: un grupo mixto —Tareas, Montaje guiado…— recupera su fila YA,
                #                             antes de mirar su posición: sin alto estaba fuera y se saltaba siempre)
            # (y solo la fila que está pegada encima de su panel: una fila vieja de otro ancho que siga a la vista
            #  —p. ej. tras un restoreState directo— pedía otros títulos y las etiquetas cambiaban solas sin parar)
            delante = next((d for _k, d in grupo if not d.isHidden() and not d.visibleRegion().isEmpty()), None)
            if delante is not None:
                g, gd = tb.geometry(), QRect(delante.mapTo(self, QPoint(0, 0)), delante.size())
                if abs(g.bottom() + 1 - gd.top()) > 3 or abs(g.left() - gd.left()) > 3:
                    continue
            # 🎛 En Editar, los paneles con su interruptor arriba NO llevan fila de pestañas (el usuario: «la 1, como
            # DaVinci»; salían dos veces): la fila de Qt se queda sin alto y el interruptor elige cuál se ve delante.
            # En las páginas sus pestañas siguen.
            if sin_fila:
                if capa is not None and capa.activa:
                    capa.quitar()
                if tb.styleSheet() != self.HOJA_SIN_PESTANAS:
                    tb.setStyleSheet(self.HOJA_SIN_PESTANAS)
                for k, d in grupo:
                    if not d.isFloating() and self.tabifiedDockWidgets(d):
                        en_fila.add(k)
                        self._poner_titulo(d, self._nombre_limpio(d))
                continue
            if tb.styleSheet() == self.HOJA_SIN_PESTANAS:
                tb.setStyleSheet("")
            fm = tb.fontMetrics()
            relleno = [tb.tabSizeHint(i).width() - fm.horizontalAdvance(tb.tabText(i))
                       - (tb.iconSize().width() + 4 if not tb.tabIcon(i).isNull() else 0) for i in range(tb.count())]
            relleno = max(relleno) if relleno else self.PESTANA_RELLENO
            # (el nombre sin emoji de color —como en los interruptores— y delante su icono monocromo)
            nombres = [self._nombre_limpio(d) for _k, d in grupo]
            glifos = [self._icono_pestaña(k) for k, _d in grupo]
            hueco_icono = 18
            anchos = [fm.horizontalAdvance(n) + relleno + hueco_icono for n in nombres]
            disp = tb.width() - 4
            iconos = [self.ICONO_PANEL.get(k, n) for (k, _d), n in zip(grupo, nombres)]
            con_icono = True
            if sum(anchos) <= disp:
                modo, titulos = "una", nombres
            elif sum(a - hueco_icono for a in anchos) <= disp:   # (en una fila con el nombre, sin icono delante)
                modo, titulos, con_icono = "una", nombres, False
            elif len(_PestanasEnDosFilas.filas(anchos, disp)) <= 2:
                # (debajo de las dos filas, la fila de Qt con los iconos: con los nombres, Qt ensanchaba el lateral
                #  hasta su largo y dejaba el visor en su mínimo)
                modo, titulos = "dos", iconos
            else:
                modo, titulos = "iconos", iconos
            if modo == "dos":
                if capa is None:
                    capa = tb._dos_filas = _PestanasEnDosFilas(tb, self)
                capa.poner([(i, n, a, g) for i, (n, a, g) in enumerate(zip(nombres, anchos, glifos))], fm.height() + 14)
            elif capa is not None and capa.activa:
                capa.quitar()
            for i, ((k, d), t) in enumerate(zip(grupo, titulos)):
                tb.setTabToolTip(i, self._nombre_limpio(d))
                quiero = glifos[i] if modo == "una" and con_icono else None   # (en «iconos», el título es el glifo)
                if quiero is not None:
                    tb.setTabIcon(i, quiero)
                elif not tb.tabIcon(i).isNull():
                    from PySide6.QtGui import QIcon
                    tb.setTabIcon(i, QIcon())
                if d.isFloating() or not self.tabifiedDockWidgets(d):   # (una fila vieja aún lo nombra: no cuenta)
                    continue
                en_fila.add(k)
                self._poner_titulo(d, t)
        for k, d in self.docks.items():                   # suelto o solo en su zona (sin pestañas): su nombre
            if k not in en_fila:
                self._poner_titulo(d, self._nombre_limpio(d))

    def _pestañas_pronto(self, *_a):
        if not hasattr(self, "_t_pestañas"):
            return
        try:
            if not self._t_pestañas.isActive():    # (no reiniciar: al reproducir llegan avisos cada fotograma)
                self._t_pestañas.start()
        except RuntimeError:                       # (la ventana se está cerrando)
            pass

    def _dock(self, key: str, title: str, widget: QWidget, closable: bool = True) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName("dock_" + key)
        d.panel = widget
        d.nombre = title                                    # (el título puede quedarse en su icono si no cabe)
        if not hasattr(self, "_t_pestañas"):                # (⚡ una vez: revisar las pestañas tras cada cambio)
            from PySide6.QtCore import QObject, QEvent

            class _Vigia(QObject):
                def __init__(self, win):
                    super().__init__(win)
                    self.win = win

                def eventFilter(self, obj, ev):
                    if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded, QEvent.LayoutRequest):
                        self.win._pestañas_pronto()
                    return False
            self._vigia_pestañas = _Vigia(self)
            self.installEventFilter(self._vigia_pestañas)      # (filas de pestañas nuevas al recolocar paneles)
            self._t_pestañas = QTimer(self)
            self._t_pestañas.setSingleShot(True)
            self._t_pestañas.setInterval(120)
            self._t_pestañas.timeout.connect(self._pestañas_que_caben)
            self._t_pestañas.timeout.connect(self._que_quepa_en_pantalla)   # (y que la ventana quepa en la pantalla)
            self._t_pestañas.timeout.connect(self._esquina_biblioteca)      # (biblioteca a todo el alto si cabe)
            self._t_pestañas.timeout.connect(self._revisar_crecer)          # (sin huecos: alto al vecino que lo usa)
            # (Qt vuelve a poner los nombres largos al recolocar paneles sin avisar: un repaso ligero de vez en cuando)
            self._t_pestañas_ciclo = QTimer(self)
            self._t_pestañas_ciclo.setInterval(1500)
            self._t_pestañas_ciclo.timeout.connect(self._pestañas_que_caben)
            self._t_pestañas_ciclo.start()
        d.visibilityChanged.connect(self._pestañas_pronto)
        d.dockLocationChanged.connect(self._pestañas_pronto)
        d.topLevelChanged.connect(self._pestañas_pronto)
        if key in self.MOVIDOS:
            # (agrupación 20/11: su contenido vive en «Voz y texto», «Audio» o el Inspector y se adapta ahí UNA vez;
            #  el panel suelto de antes solo queda como nombre para distribuciones viejas → arranque más rápido)
            d.setWidget(QWidget())
        elif key != "timeline":
            # Cada panel puede encogerse (con barra de desplazamiento VERTICAL) en vez de aplastar la línea de tiempo;
            # a lo ancho, su contenido se adapta (↔ responsive: nada se corta, esté donde esté el panel)
            from . import responsive
            d.setWidget(responsive.ZonaPanel(widget, self.PANEL_MIN if key != "guide" else 0))
            responsive.adaptar(widget)
        else:
            d.setWidget(widget)
        feats = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        if closable:
            feats |= QDockWidget.DockWidgetClosable
        d.setFeatures(feats)
        # (el usuario: los paneles solo se acomodan a los LADOS del visor —varias columnas a cada lado, sí—, nunca encima
        #  del visor ni encima o debajo de la línea de tiempo; la línea de tiempo es la de abajo)
        d.setAllowedAreas(Qt.AllDockWidgetAreas if key == "timeline" else
                          Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.docks[key] = d
        return d

    # 🔑 los paneles de la página «Palabras clave»: solo se ven en ella (fuera de ella, siempre ocultos)
    PAGINA_KW = ("clips", "kw_buscar", "kw_folders")
    # ✦ los paneles de la página «Efectos» (una columna por categoría): solo se ven en ella
    PAGINA_FX = ("fx_trans", "fx_efectos", "fx_filtros", "fx_figuras")
    # (agrupación 20/11) paneles que ya no salen sueltos: viven dentro de «Voz y texto», «Audio» o el Inspector
    MOVIDOS = ("clips", "kw_folders", "kw_buscar", "transcript", "subtitles", "voz_ia", "voice", "audio_mix",
               "material")     # (su contenido se mudó: ver _agrupar_paneles)
    ABSORBIDOS = MOVIDOS + PAGINA_FX
    _OCULTOS_AL_INICIO = ("guide", "tasks", "guided", "cortes", "history", "scopes") + PAGINA_KW + PAGINA_FX + \
        ABSORBIDOS    # se abren cuando se pide (Historial y Gráficas: ☰ Paneles)
    # 🗂 Paneles de cada pestaña (lo de entrada; lo que cambies tú desde Ventana se recuerda por pestaña). YouTube: sin
    # Texto ni Subtítulos (no los usa en las reseñas) y con 🔑 Palabras clave y 🎞 Material del clip; Edits: el edit
    # musical a pantalla completa (opciones a la derecha, clips a la izquierda), sin lo de la voz; Shorts: subtítulos.
    # 🗣 Voz IA: a la vista en Vertical (Shorts leídos por la IA); en las otras, con «🗣 Que lo lea la IA» o Ventana.
    # (agrupación 20/11: Limpieza/Mezcla → «Audio»; Transcribir/Transcripción/Subtítulos/Palabras clave/Voz IA →
    #  «Voz y texto»; Material del clip → Inspector → Archivo)
    TAB_PANELS = {
        "youtube": {"audio": True, "voz_texto": False, "palabras": True, "edit_opts": False, "edit_clips": False},
        "edit": {"edit_opts": True, "edit_clips": True, "audio": False, "voz_texto": False, "palabras": False},
        "short": {"audio": True, "voz_texto": True, "palabras": False, "edit_opts": False, "edit_clips": False},
    }
    TAB_MANAGED = ("audio", "voz_texto", "palabras", "edit_opts", "edit_clips")

    def _remember_tab_panel(self, key: str, on: bool):
        tab = getattr(getattr(self, "workspaces", None), "current", "youtube")
        self.settings.setValue(f"paneles_pestana/{tab}/{key}", "true" if on else "false")

    # (agrupación 20/11) lo que recordabas por pestaña de los paneles de antes → su panel agrupado
    _MIGRAR_PESTANA = {"voz_ia": "voz_texto", "subtitles": "voz_texto", "transcript": "voz_texto", "clips": "voz_texto",
                       "voice": "audio", "audio_mix": "audio"}

    def _migrar_paneles_pestana(self):
        """Una vez: «paneles_pestana/<pestaña>/voz_ia = true» (o Subtítulos, Texto, Palabras clave) abre «Voz y texto»
        en esa pestaña; Limpieza o Mezcla y música, «Audio». Las claves viejas se borran."""
        st = self.settings
        if str(st.value("paneles/agrupacion_migrada", "") or "") == "1":
            return
        for tab in ("youtube", "edit", "short"):
            nuevos: dict = {}
            for viejo, nuevo in self._MIGRAR_PESTANA.items():
                v = st.value(f"paneles_pestana/{tab}/{viejo}")
                if v is None:
                    continue
                nuevos[nuevo] = nuevos.get(nuevo, False) or str(v).lower() == "true"
                st.remove(f"paneles_pestana/{tab}/{viejo}")
            for nuevo, on in nuevos.items():
                if on:                                     # (cerrado antes = lo de fábrica de la pestaña)
                    st.setValue(f"paneles_pestana/{tab}/{nuevo}", "true")
        st.setValue("paneles/agrupacion_migrada", "1")

    def _migrar_voz_izquierda(self, habia_distribucion: bool):
        """Una vez (22/11): «Voz y texto» pasa a la izquierda y «Palabras clave» —antes su sección 4— es un panel propio
        a la derecha. Lo que recordabas de «Voz y texto» por pestaña de trabajo vale también para «Palabras clave»; con
        una distribución guardada, «Voz y texto» va en pestaña junto a Medios (o solo a la izquierda) y «Palabras clave»
        junto al Inspector, cada uno como estaba (a la vista o no): ningún panel huérfano ni hueco."""
        st = self.settings
        if str(st.value("paneles/voz_izq_v1", "") or "") == "1":
            return
        st.setValue("paneles/voz_izq_v1", "1")
        if str(st.value("paneles/lado/voz_texto", "") or "") == "izq":
            st.remove("paneles/lado/voz_texto")             # (ahora es su lado de fábrica)
        for tab in ("youtube", "edit", "short"):
            v = st.value(f"paneles_pestana/{tab}/voz_texto")
            if v is not None and st.value(f"paneles_pestana/{tab}/palabras") is None:
                st.setValue(f"paneles_pestana/{tab}/palabras", v)
        if not habia_distribucion:
            return
        d = self.docks
        for k, area, ancla_k in (("voz_texto", Qt.LeftDockWidgetArea, "media"),
                                 ("palabras", Qt.RightDockWidgetArea, "inspector")):
            dk, ancla = d[k], d.get(ancla_k)
            if dk.isFloating() or self.dockWidgetArea(dk) == area:
                continue
            visible = not dk.isHidden()
            if ancla is not None and not ancla.isFloating() and self.dockWidgetArea(ancla) == area:
                self.tabifyDockWidget(ancla, dk)
            else:
                self.addDockWidget(area, dk)
            dk.setVisible(visible)

    def apply_tab_panels(self, tab: str | None = None):
        """Enseña los paneles de esa pestaña (y sube a la vista los suyos: en Edits, el edit musical)."""
        self._migrar_paneles_pestana()
        tab = tab or getattr(getattr(self, "workspaces", None), "current", "youtube")
        conf = self.TAB_PANELS.get(tab, {})
        subir = []
        for key in self.TAB_MANAGED:
            if key not in conf:
                continue
            mine = self.settings.value(f"paneles_pestana/{tab}/{key}")
            on = conf[key] if mine is None else str(mine).lower() == "true"
            d = self.docks.get(key)
            if d is None:
                continue
            if d.toggleViewAction().isChecked() != on:
                d.setVisible(on)
            if on and conf[key]:
                subir.append(d)
        for d in subir:
            if tab == "edit":
                d.raise_()
        self._ocultar_absorbidos()


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
        self.tabifyDockWidget(d["media"], d["descargas_web"])
        self.tabifyDockWidget(d["media"], d["memes"])
        self.tabifyDockWidget(d["media"], d["edit_clips"])
        self.tabifyDockWidget(d["media"], d["sounds"])        # (🔊 los sonidos, donde estaba Efectos)
        self.tabifyDockWidget(d["media"], d["voz_texto"])     # (22/11: Transcripción, Subtítulos… a la izquierda)
        for k in self.PAGINA_FX:                               # (✦ ocultos: van a su página)
            self.tabifyDockWidget(d["media"], d[k])
        self.addDockWidget(Qt.RightDockWidgetArea, d["inspector"])
        for k in ("palabras", "audio", "edit_opts"):
            self.tabifyDockWidget(d["inspector"], d[k])
        self.addDockWidget(Qt.RightDockWidgetArea, d["history"], Qt.Vertical)   # (Historial y Gráficas —☰ Paneles—:
        self.tabifyDockWidget(d["history"], d["scopes"])                  #  debajo, con SU fila, sin repetir nombres)
        for k in self.ABSORBIDOS:                          # (absorbidos por «Voz y texto», «Audio» o el Inspector)
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
        self._restaurar_paneles(self._default_state)
        for key, dock in self.docks.items():
            dock.setVisible(key not in self._OCULTOS_AL_INICIO)
        self.docks["media"].raise_()
        self.docks["inspector"].raise_()
        QTimer.singleShot(0, self._apply_dock_sizes)
        try:
            self.apply_tab_panels()              # (los paneles que tocan en esta pestaña, no todos)
        except Exception:  # noqa: BLE001
            pass
        self._lados_de_fabrica()                 # (↔ y cada interruptor otra vez en la fila de su lado de fábrica)

    def _lados_de_fabrica(self):
        """«Restablecer distribución»: olvida los lados que elegiste (paneles/lado/*), devuelve cada interruptor a la fila
        de su lado de fábrica y cada panel a ese lado: fila y lado siguen coincidiendo."""
        self.settings.beginGroup("paneles/lado")
        self.settings.remove("")
        self.settings.endGroup()
        for k in list(getattr(self, "interruptores", {})):
            self._mover_interruptor(k, self._lado_de_fabrica(k))
        self._paneles_a_su_sitio()
        if hasattr(self, "_altos_a_mano"):
            self._altos_a_mano.clear()

    PANEL_MIN = 200        # (ancho mínimo de entrada de un panel; puede bajar hasta lo que pide su contenido adaptado)

    def _ajustar_paneles(self):
        """↔ Ningún panel corta su contenido, esté donde esté y mida lo que mida (ui/responsive.py): las etiquetas, los
        botones y las casillas parten su texto en varias líneas, los desplegables se estrechan («…» y el texto entero al
        pasar el ratón), las filas bajan a la línea siguiente y las rejillas pasan a una columna. Cada panel (su
        responsive.ZonaPanel) nunca se deja estrechar más de lo que su contenido adaptado necesita (≈150–200 px)."""
        from . import responsive
        for key, d in self.docks.items():
            panel = getattr(d, "panel", None)
            if key == "timeline" or panel is None:
                continue
            responsive.adaptar_una_vez(panel)
            if d.minimumWidth() > 0:
                d.setMinimumWidth(0)                  # (el mínimo lo da su zona: lo que pide el contenido)
        self._que_quepa_en_pantalla()

    def _que_quepa_en_pantalla(self):
        """↔ La ventana nunca pide más ancho que la pantalla: si los paneles de los lados (más el visor) no caben, su
        ancho mínimo de entrada (PANEL_MIN) baja hasta lo que su contenido adaptado necesita (nunca menos: se cortaría).
        Sin esto, con varios paneles en columnas, Qt cortaba la derecha de Reclaimer y no dejaba soltar paneles allí."""
        from . import responsive
        try:
            pant = (self.screen() or QApplication.primaryScreen()).availableGeometry().width()
        except Exception:  # noqa: BLE001
            return
        if getattr(self, "_cabiendo", False):
            return
        self._cabiendo = True
        try:
            # (los abiertos aunque estén detrás de otra pestaña: también cuentan para el ancho de su zona)
            zonas = [d.widget() for k, d in self.docks.items() if k not in ("timeline", "guide")
                     and d.toggleViewAction().isChecked() and not d.isFloating()
                     and isinstance(d.widget(), responsive.ZonaPanel)]
            if not zonas:
                return
            lim = pant - 16
            holgura = lim - self.minimumSizeHint().width()
            if holgura > 80:                            # sobra sitio: los que bajaron vuelven hacia su mínimo
                for z in zonas:
                    if z.preferido < self.PANEL_MIN and holgura > 80:
                        z.poner_preferido(min(self.PANEL_MIN, z.preferido + holgura - 60))
                        holgura = lim - self.minimumSizeHint().width()
            sobra = self.minimumSizeHint().width() - lim
            for _vuelta in range(40):                    # no cabe: bajan de a poco hasta lo que pide su contenido
                if sobra <= 0:
                    break
                altos = [z for z in zonas if z.preferido > z.necesita()]
                if not altos:
                    break
                paso = max(8, min(40, sobra))
                for z in altos:
                    z.poner_preferido(max(z.necesita(), z.preferido - paso))
                sobra = self.minimumSizeHint().width() - lim
        finally:
            self._cabiendo = False


    def _restaurar_paneles(self, estado):
        """Vuelve a poner los paneles de Editar tal como estaban (al salir de una página o al restablecer) sin dos
        fallos de Qt que salieron en la sonda del 20/11:
          · la pila del centro recordaba el ancho mínimo de la página de la que se sale (🎬 Escenas pide ~1840 px)
            hasta procesar sus eventos; restoreState() repartía con ese mínimo viejo, los laterales se quedaban en su
            mínimo (~200 px) y la ventana crecía a ~2250–2300 px, más que la pantalla → ahora se le pide el mínimo nuevo
            ANTES de restaurar y, si aun así la ventana quedó más grande que la pantalla, se devuelve a ella;
          · restoreState() deja a la vista barras de pestañas viejas de la página anterior («🔎 Buscar material ·
            🗂 Carpetas · 📥 Descargado» quedaba pintada encima de la cabecera del visor en Audio, Transcripción y
            Miniatura) → _barras_sueltas_fuera()."""
        self.central_stack.updateGeometry()          # (el mínimo del centro, el de ahora: no el de la página de antes)
        lay = self.layout()
        if lay is not None:
            lay.invalidate()
        self.restoreState(estado, 3)
        self._fila_paneles_aparte()
        self._ocultar_absorbidos()
        self._ventana_en_pantalla()
        QTimer.singleShot(0, self._ventana_en_pantalla)    # (y otra vez con el mínimo ya recalculado)
        QTimer.singleShot(0, self._barras_sueltas_fuera)

    def _agrupar_paneles(self):
        """🗂 Agrupación del 20/11 (aprobada por el usuario; tabla en notas_claude/PROPUESTA_INTERFAZ.md):
        · «Voz y texto» (a la izquierda desde el 22/11): 1 Transcribir (de IA ✨) · 2 Transcripción · 3 Subtítulos ·
          4 Voz IA;
        · «Palabras clave» (22/11: su propio panel, a la derecha): Dijiste… · Carpetas · Buscar material;
        · «Audio»: 1 Limpieza · 2 Mezcla y música · 3 Sonoridad (la casilla −14 LUFS y «Medir», en UN solo sitio);
        · Material del clip → Inspector → Archivo → Información.
        Los paneles de dentro son los de siempre (misma lógica); sus paneles sueltos de antes quedan absorbidos:
        ocultos para siempre y fuera de Ventana y ☰ Paneles (show_panel / go_page llevan a su sección)."""
        from PySide6.QtWidgets import QTabWidget
        from .paneles_agrupados import Acordeon
        d = self.docks
        # ⚠ los paneles MOVIDOS nunca van en la zona con desplazamiento de su panel suelto de antes (_dock): si fueran,
        #   esa zona (oculta) los seguiría redimensionando a SU ancho y el contenido se saldría del panel agrupado
        from .paneles_agrupados import PestanasAjustadas
        pal = PestanasAjustadas()   # (piden el alto de la pestaña de delante: «Dijiste…» no hereda el de «Buscar material»)
        pal.setObjectName("palabrastabs")
        pal.setDocumentMode(True)
        for k, titulo, tip in (("clips", "Dijiste…", "Lo que dices en la narración: cada palabra clave y sus momentos"),
                               ("kw_folders", "Carpetas", "La carpeta de la palabra elegida (y lo descargado)"),
                               ("kw_buscar", "Buscar material", "Buscar material para la palabra: tu carpeta o "
                                                                "internet")):
            pal.addTab(d[k].panel, titulo)
            pal.setTabToolTip(pal.count() - 1, tip)
        pal.iconos_si_no_cabe(["mic", "folder-open", "search"])   # (estrecho: icono y el nombre en el tooltip)
        self._pal_tabs = pal
        from .paneles_agrupados import PanelSinHuecos
        self._pal_panel = PanelSinHuecos(pal)      # (sin huecos: si la pestaña de delante no crece, el alto, al final)
        # (22/11, el usuario: «se me dificultaba navegar entre esos menús, probablemente porque están en el mismo
        #  espacio»: «Voz y texto» pasa a la IZQUIERDA —con Medios, Efectos…— y «Palabras clave» es su propio panel a
        #  la derecha, con todo el alto para Dijiste… · Carpetas · Buscar material)
        if str(self.settings.value("agrupados/voz_texto", "") or "") == "palabras":
            self.settings.setValue("agrupados/voz_texto", "transcripcion")   # (la sección que ya no está aquí)
        transcr = self.ai_panel.sacar_transcriptor() or QWidget()
        self.voz_texto = Acordeon("voz_texto", [
            ("transcribir", "Transcribir", transcr, "La narración (qué archivo es tu voz), el modelo y transcribir"),
            ("transcripcion", "Transcripción", self.transcript, "El texto de lo que se dice: buscar, ir y cortar "
                                                                 "por texto"),
            ("subtitulos", "Subtítulos", self.subtitles, "Los subtítulos del video y su estilo"),
            ("voz_ia", "Voz IA", self.voz_ia, "Que una voz sintética lea tu guion")])
        self._dock("voz_texto", "Voz y texto", self.voz_texto)
        self._dock("palabras", "Palabras clave", self._pal_panel)
        self.audio_panel = Acordeon("audio", [
            ("limpieza", "Limpieza", self.voice, "Limpiar la voz: silencios, muletillas, repeticiones y sugerencias"),
            ("mezcla", "Mezcla y música", d["audio_mix"].panel, "Mejorar la voz, la música y bajarla cuando hablas"),
            ("sonoridad", "Sonoridad", self._caja_sonoridad(), "El volumen final para YouTube, TikTok e Instagram "
                                                               "(−14 LUFS): al exportar y medir"),
            ("cortes", "Cortes de audio", self._caja_cortes(), "Los cortes con salto de volumen o chasquido: "
                                                              "revisarlos y suavizarlos uno a uno")])
        self._dock("audio", "Limpieza y mezcla", self.audio_panel)   # («Audio» = la pestaña del Inspector)
        if hasattr(self.transcript, "transcribir_pedido"):   # (sin transcripción: «Transcribir» → 1 · Transcribir)
            self.transcript.transcribir_pedido.connect(lambda: self.abrir_seccion("voz_texto", "transcribir"))
        # (20/11, auditoría: a 768 px de alto, al abrir una sección el panel quedaba desplazado y su cabecera oculta:
        #  al abrir una sección, la zona del panel vuelve arriba del todo)
        for _k, _ac in (("voz_texto", self.voz_texto), ("audio", self.audio_panel)):
            _ac.cambiada.connect(lambda _s, k=_k: QTimer.singleShot(0, lambda: self._zona_arriba(k)))
            self.docks[_k].visibilityChanged.connect(
                lambda on, k=_k: on and QTimer.singleShot(0, lambda: self._zona_arriba(k)))
        from . import responsive
        responsive.adaptar(self.material)
        self.inspector.poner_en("informacion", self.material)  # 🎞 Material del clip → Inspector → Archivo
        self.material.en_columna()                           # (estrecho: nunca ensancha el Inspector)
        for k in self.ABSORBIDOS:
            dk = d[k]
            dk.absorbido = True
            dk.toggleViewAction().setVisible(False)
            dk.visibilityChanged.connect(lambda on, dk_=dk: on and QTimer.singleShot(0, dk_.hide))
            dk.toggleViewAction().toggled.connect(lambda on, dk_=dk: on and QTimer.singleShot(0, dk_.hide))
            dk.hide()

    def _zona_arriba(self, k: str):
        """La zona con desplazamiento del panel k, arriba del todo (su cabecera y la sección abierta a la vista)."""
        from PySide6.QtWidgets import QScrollArea
        d = self.docks.get(k)
        zona = d.widget() if d is not None else None
        if isinstance(zona, QScrollArea) and zona.verticalScrollBar().value():
            zona.verticalScrollBar().setValue(0)

    def _caja_cortes(self) -> QWidget:
        """✂ «Corte de audio» (antes se abría al entrar en la página Audio): el botón que lo abre y cuántos avisos hay."""
        caja = QWidget()
        v = QVBoxLayout(caja)
        v.setContentsMargins(6, 6, 6, 6)
        self.btn_corte_audio = QPushButton("✂ Abrir «Corte de audio»")
        self.btn_corte_audio.setToolTip("El panel para revisar cada corte con aviso de la línea de tiempo (salto de "
                                        "volumen o chasquido): escucharlo, suavizarlo o quitar el aviso")
        self.btn_corte_audio.clicked.connect(self.abrir_corte_audio)
        v.addWidget(self.btn_corte_audio)
        from PySide6.QtWidgets import QCheckBox
        self.chk_puntos_union = QCheckBox("Puntos de unión en el audio")      # 🔴 = el botón ◉ de la línea de tiempo
        self.chk_puntos_union.setToolTip(
            "En cada unión de dos piezas pegadas (tras eliminar silencios), un punto arriba (final de la pieza de la "
            "izquierda) y otro abajo (inicio de la de la derecha). Arrástralos en la línea de tiempo para poner o quitar "
            "audio de esa pieza: lo de detrás se recorre solo, sin comerse nada (un Ctrl+Z). Rojo = parece que la "
            "palabra quedó cortada. Es lo mismo que el botón ◉ junto a «➕ Pista»")
        self.chk_puntos_union.setChecked(self.timeline.union_dots)
        self.chk_puntos_union.toggled.connect(lambda on: self.timeline.set_union_dots(on))
        self.timeline.union_dots_toggled.connect(lambda on: (self.chk_puntos_union.blockSignals(True),
                                                             self.chk_puntos_union.setChecked(on),
                                                             self.chk_puntos_union.blockSignals(False)))
        v.addWidget(self.chk_puntos_union)
        self.chk_fundidos = QCheckBox("Fundidos automáticos")             # 〰 fase 3: sin chasquidos en los cortes
        self.chk_fundidos.setToolTip(
            "Un fundido muy corto (2 fotogramas a cada lado) en cada unión de tu voz, también tras eliminar "
            "silencios, y fundidos cortos al empezar y acabar la música y el sonido del B-roll: sin chasquidos al "
            "cortar. Se ven en la línea de volumen de los audios y salen igual al exportar. Apagado: todo como antes "
            "(tus fundidos no se tocan)")
        self.chk_fundidos.setChecked(self.ctrl.fundidos_auto)
        self.chk_fundidos.toggled.connect(self._cambiar_fundidos)
        v.addWidget(self.chk_fundidos)
        self.lbl_cortes = QLabel()
        self.lbl_cortes.setObjectName("dim")
        self.lbl_cortes.setWordWrap(True)
        v.addWidget(self.lbl_cortes)
        v.addStretch(1)

        def contar(_n=None):
            n = len(getattr(self.timeline, "cut_issues", []) or [])
            self.lbl_cortes.setText(f"{n} corte(s) con aviso en la línea de tiempo" if n else "Ningún corte con aviso")
        try:
            self.timeline.cut_issues_changed.connect(contar)
        except AttributeError:
            pass
        contar()
        return caja

    def abrir_corte_audio(self):
        """✂ El panel «Corte de audio» a la vista: en el primer corte con aviso, si hay alguno."""
        if getattr(self.timeline, "cut_issues", None):
            self._open_cut_issue(0)
        self.cut_fix_panel()
        d = self.docks["cortes"]
        self._sitio_sin_pestanas("cortes")
        d.show()
        d.raise_()
        self._llenar_menu_ventana()
        return d

    # (paneles sin interruptor que se abren a la derecha: debajo del Inspector, nunca en pestaña con paneles que ya
    #  tienen interruptor —si no, Qt saca la fila «Inspector · Voz y texto · …» repitiendo los nombres de arriba—)
    SIN_PESTANAS = ("history", "scopes", "cortes")

    def _sitio_sin_pestanas(self, k: str):
        d = self.docks.get(k)
        ins = self.docks.get("inspector")
        if d is None or ins is None or d.isFloating():
            return
        inter = getattr(self, "interruptores", {})
        juntos = self.tabifiedDockWidgets(d)
        if not any(self.docks.get(x) in juntos for x in inter) and self.dockWidgetArea(d) != Qt.NoDockWidgetArea:
            return
        hermano = next((self.docks[x] for x in self.SIN_PESTANAS if x != k and x in self.docks
                        and not self.docks[x].isHidden() and not self.docks[x].isFloating()
                        and not any(self.docks.get(y) in self.tabifiedDockWidgets(self.docks[x]) for y in inter)),
                       None)
        self.removeDockWidget(d)
        if hermano is not None:
            self.tabifyDockWidget(hermano, d)          # (Historial · Gráficas: SU fila, que no repite nada)
        else:                                          # (splitDockWidget con el Inspector en pestañas lo metía en ellas)
            area = self.dockWidgetArea(ins) if not ins.isFloating() else Qt.NoDockWidgetArea
            self.addDockWidget(area if area != Qt.NoDockWidgetArea else Qt.RightDockWidgetArea, d, Qt.Vertical)

    def _caja_sonoridad(self) -> QWidget:
        """📊 La sonoridad en UN solo sitio (antes: casilla en Mezcla, «LUFS» del transporte e Inspector → Proyecto):
        la casilla «Volumen final para YouTube (−14 LUFS)» y «Medir la sonoridad». El Inspector → Proyecto deja un
        acceso que trae aquí; el transporte, solo el volumen de escucha."""
        caja = QWidget()
        v = QVBoxLayout(caja)
        v.setContentsMargins(6, 6, 6, 6)
        loud = getattr(self.ai_panel, "loud", None)
        if loud is not None:
            loud.setParent(caja)
            v.addWidget(loud)
        self.btn_sonoridad = QPushButton("📊 Medir la sonoridad (LUFS)")
        self.btn_sonoridad.setToolTip("Mide el volumen percibido de toda la mezcla (LUFS integrados y pico verdadero, "
                                      "en segundo plano) y te dice cuántos dB subir o bajar para llegar a −14 LUFS con "
                                      "el pico ≤ −1 dBTP. Puedes aplicarlo (Ctrl+Z lo deshace). Clic mientras mide = "
                                      "cancelar.")
        self.btn_sonoridad.clicked.connect(lambda: self.engine.loudness.start(self))
        try:
            self.engine.loudness.busy.connect(lambda on: self.btn_sonoridad.setText(
                "⏳ Midiendo… (clic = cancelar)" if on else "📊 Medir la sonoridad (LUFS)"))
        except AttributeError:
            pass
        v.addWidget(self.btn_sonoridad)
        v.addStretch(1)
        self.preview.btn_lufs.setVisible(False)       # (el transporte: solo escuchar)
        g = getattr(self.inspector, "_g_sonoridad", None)
        if g is not None:                              # (Inspector → Proyecto → Sonoridad: un acceso, no otro control)
            g.setVisible(False)
            acceso = QPushButton("🎚 Abrir la sonoridad en «Limpieza y mezcla»")
            acceso.setObjectName("flat")
            acceso.setToolTip("La sonoridad (−14 LUFS al exportar y medir) está en el panel «Limpieza y mezcla» → "
                              "3 · Sonoridad")
            acceso.clicked.connect(lambda: self.abrir_seccion("audio", "sonoridad"))
            self.inspector.poner_en("sonoridad", acceso)
        return caja

    def _ocultar_absorbidos(self):
        """Los paneles absorbidos nunca vuelven sueltos (tampoco con una distribución guardada de antes)."""
        for k in self.ABSORBIDOS:
            dk = self.docks.get(k)
            if dk is not None and getattr(dk, "absorbido", False) and not dk.isHidden():
                dk.hide()

    def _destino_absorbido(self, widget):
        """(panel, sección) donde vive ahora un widget absorbido; None si no es de ninguno."""
        if widget is None:
            return None
        pal = getattr(self, "_pal_panel", None)
        if pal is not None and (widget is pal or pal.isAncestorOf(widget)):
            return "palabras", "palabras"              # (Dijiste… · Carpetas · Buscar material: su panel)
        for clave_g, acordeon in (("voz_texto", getattr(self, "voz_texto", None)),
                                  ("audio", getattr(self, "audio_panel", None))):
            if acordeon is not None and widget is not acordeon:
                k = acordeon.clave_de(widget)
                if k is not None:
                    return clave_g, k
        if widget is getattr(self, "material", None):
            return "inspector", "archivo"
        return None

    def mostrar_widget(self, w: QWidget) -> bool:
        """🧭 PÚBLICA y estable (la guía, la ayuda, el montaje guiado…): pone a la vista ese widget esté donde esté.
        Si vive dentro de «Voz y texto» o «Audio», abre ese panel y su sección (y su pestaña de Palabras clave); si vive
        en el Inspector, abre su pestaña y su sección plegable; si no, abre y pone delante su panel. Después lo
        desplaza a la vista. True si quedó visible."""
        if w is None:
            return False
        from PySide6.QtWidgets import QDockWidget, QScrollArea, QTabWidget
        from .inspector_secciones import Seccion       # (las plegables del Inspector: Velocidad, Color…)
        from .tabs import Section
        try:
            cadena = []
            p = w
            while p is not None and p is not self:
                cadena.append(p)
                p = p.parentWidget()
        except RuntimeError:
            return False
        agrupado = None
        for a in cadena:                               # (Voz y texto / Audio: su sección)
            for clave_g, acordeon in (("voz_texto", getattr(self, "voz_texto", None)),
                                      ("audio", getattr(self, "audio_panel", None))):
                if acordeon is not None and acordeon.clave_de(a) is not None:
                    agrupado = (clave_g, acordeon.clave_de(a))
                    break
            if agrupado:
                break
        if agrupado:
            self.abrir_seccion(*agrupado)
        else:
            dock = next((a for a in cadena if isinstance(a, QDockWidget)), None)
            if dock is not None:
                self.show_panel(getattr(dock, "panel", None) or dock.widget())
        for i, a in enumerate(cadena):                 # (pestañas y secciones plegables por el camino, de fuera a dentro)
            par = a.parentWidget()
            tabs = par.parentWidget() if par is not None else None
            if isinstance(tabs, QTabWidget) and tabs.indexOf(a) >= 0:
                j = tabs.indexOf(a)
                if tabs.isTabEnabled(j):
                    tabs.setCurrentIndex(j)
            if isinstance(a, (Section, Seccion)) and a is not w and not a.is_open():
                a.set_open(True, save=False)
        zona = next((a for a in cadena[1:] if isinstance(a, QScrollArea) and a.widget() is not None), None)
        if zona is not None:
            QTimer.singleShot(0, lambda: zona.ensureWidgetVisible(w, 0, 20) if w.isVisible() else None)
        return w.isVisibleTo(self)

    # ------------------------------------------------ 🧭 REGLA: lo que creas o pides, a la vista y listo para usar
    # (el usuario, 20/11: pulsó «T», se creó el texto y no apareció dónde escribirlo: el Inspector estaba cerrado).
    # Cualquier acción que cree algo que hay que rellenar, o que necesite que escribas algo para seguir, termina en
    # abrir_para_usar(). Lo que crea el controlador lo avisa con ctrl.creado_por_ti (solo lo tuyo: nunca lo de la IA ni lo
    # de los procesos automáticos) y aquí se abre SU editor (EDITOR_DE). Prueba permanente: tests/test_abre_su_panel.py.
    def abrir_para_usar(self, w: QWidget, foco: QWidget | None = None, seleccionar: bool = False) -> bool:
        """🧭 PÚBLICA: pone w a la vista esté donde esté (mostrar_widget: panel, pestaña, sección y desplazamiento) y, si
        se da `foco`, le deja el foco (con seleccionar=True, su texto seleccionado para escribir encima). El foco se
        vuelve a dar en cuanto Qt termina lo que tenía pendiente (abrir el panel, rellenar el Inspector…)."""
        ok = self.mostrar_widget(w)
        if foco is None:
            return ok

        def dar():
            try:
                if not foco.isVisible() or not foco.isEnabled():
                    return
                foco.setFocus(Qt.OtherFocusReason)
                if seleccionar and hasattr(foco, "selectAll"):
                    foco.selectAll()
            except RuntimeError:                       # (cerrando)
                pass
        dar()
        QTimer.singleShot(0, dar)
        return ok

    def editor_de(self, clip) -> tuple | None:
        """🧭 EDITOR_DE: dónde se rellena o ajusta lo que acabas de crear → (widget a la vista, widget con el foco o
        None, seleccionar su texto). Un texto: el cuadro del Inspector → Texto, con «Texto» ya marcado para escribir
        encima. Una capa de ajuste: Inspector → Video → Color (el foco se queda en la línea de tiempo)."""
        if clip is None:
            return None
        if clip.text is not None:
            ed = self.inspector.text_edit
            return ed, ed, True
        m = self.ctrl.project.media_of(clip)
        if m is not None and (m.gen or {}).get("kind") == "adjust":
            return self.inspector.secciones["color"], None, False
        return None

    def _abrir_lo_creado(self, ids: list):
        """🧭 ctrl.creado_por_ti: lo recién creado queda elegido y su editor, a la vista y con el foco."""
        p = self.ctrl.project
        ids = [i for i in ids if i in p.clips]
        if not ids:
            return
        destino = next((d for d in (self.editor_de(p.clips[i]) for i in ids) if d), None)
        fw = QApplication.focusWidget()
        if destino is not None and destino[1] is not None and fw is destino[1]:
            self.timeline.setFocus()           # (si no, el Inspector no pondría el texto nuevo en su cuadro)
        if set(self.timeline.selected) != set(ids):
            self.timeline.set_selection(ids)   # (→ el Inspector y «Texto en pantalla» enseñan lo nuevo)
        if destino is not None:
            self.abrir_para_usar(*destino)

    def abrir_seccion(self, panel: str, seccion: str):
        """Abre «Voz y texto», «Audio» o el Inspector delante, en esa sección (desde Escenas/Miniatura, primero a
        Editar). Devuelve el panel."""
        if getattr(self, "_scenes_state", None) is not None or getattr(self, "_thumb_page", None) is not None:
            self.go_page("edit")
        if panel == "voz_texto" and seccion == "palabras":
            panel = "palabras"                         # (22/11: «Palabras clave» ya es su propio panel)
        dk = self.docks.get(panel)
        if dk is None:
            return None
        self._paneles_a_su_sitio(solo=[panel])
        dk.show()
        dk.raise_()
        if panel == "inspector":
            self.inspector.ir_a(seccion)
        elif panel == "palabras":
            pass                                       # (sus pestañas: show_panel / mostrar_widget eligen la suya)
        else:
            acordeon = self.voz_texto if panel == "voz_texto" else self.audio_panel
            acordeon.abrir(seccion)
        self._sync_interruptores() if hasattr(self, "interruptores") else None
        return dk

    def _fila_paneles_aparte(self):
        """La fila de los paneles, siempre en su propia fila debajo de la barra de arriba: una distribución guardada de
        antes de que existiera (o la de fábrica) la ponía AL LADO de la barra de arriba y la ventana pedía ~1430 px."""
        tb = getattr(self, "_tb_paneles", None)
        if tb is not None and not self.toolBarBreak(tb):
            self.insertToolBarBreak(tb)

    def _barras_sueltas_fuera(self):
        """Barras de pestañas de los paneles: a la vista SOLO las de la distribución de ahora. Qt dejaba a la vista
        barras viejas tras restoreState() (pintadas encima de otra página) y, al entrar en 🎚 Audio, escondía las
        suyas hasta el siguiente cambio de tamaño. Se decide barra a barra y se puede llamar las veces que sea (también
        desde un clic): cada barra se marca, se vuelve a aplicar la distribución —Qt reescribe AL MOMENTO los nombres
        de las barras que usa (su posición la mueve después, con una animación de 0 ms: por eso no sirve mirarla)— y
        las que siguen marcadas son viejas: fuera. De las que usa, se enseña cada una cuyos paneles están a la vista,
        acoplados y en pestañas entre sí. No se borran: Qt guarda punteros a ellas."""
        from PySide6.QtWidgets import QTabBar
        import shiboken6
        lay = self.layout()
        if lay is None or not self.isVisible():
            return
        barras = [b for b in self.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly) if b.count()]
        if not barras:
            return
        marca = "\u2063·vieja·"
        for b in barras:
            b.setTabText(0, marca)
        r = self.rect()                                # (lo mismo que usa Qt: la ventana menos la barra de menús)
        menu = self.menuWidget()
        if menu is not None and not menu.isHidden() and not menu.isWindow():
            r.setTop(menu.geometry().bottom() + 1)
        lay.setGeometry(r)
        punteros = {shiboken6.getCppPointer(d)[0]: d for d in self.docks.values()}
        # (si Qt no reescribió ninguna —sin grupos a la vista, p. ej. en 🖼 Miniatura, o en mitad de un arrastre— no se
        #  sabe cuáles usa: entonces solo cuenta que sus paneles estén a la vista)
        aplicado = any(b.tabText(0) != marca for b in barras)
        for b in barras:
            docks = [punteros.get(b.tabData(i)) for i in range(b.count())]
            if b.tabText(0) == marca:
                b.setTabText(0, docks[0].windowTitle() if docks and docks[0] is not None else "")
                vieja = aplicado
            else:
                vieja = False
            buena = (not vieja and len(docks) >= 2
                     and all(d is not None and not d.isHidden() and not d.isFloating() for d in docks))
            if buena:
                for d in docks:                        # (en pestañas entre sí, como _pestañas_que_caben)
                    if not any(o in docks for o in self.tabifiedDockWidgets(d)):
                        buena = False
                        break
            if buena:
                if b.isHidden():
                    b.show()
            elif b.isVisible():
                b.hide()

    def _ventana_en_pantalla(self):
        """↔ Si la ventana (sin maximizar) quedó más grande que su pantalla, vuelve a caber en ella."""
        if self.isMaximized() or self.isFullScreen():
            return
        try:
            av = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        except Exception:  # noqa: BLE001
            return
        marco = self.frameGeometry()
        w = min(self.width(), av.width() - (marco.width() - self.width()))
        h = min(self.height(), av.height() - (marco.height() - self.height()))
        if (w, h) == (self.width(), self.height()):
            return
        self.resize(w, h)
        marco = self.frameGeometry()
        x = max(av.left(), min(marco.x(), av.right() + 1 - marco.width()))
        y = max(av.top(), min(marco.y(), av.bottom() + 1 - marco.height()))
        if (x, y) != (marco.x(), marco.y()):
            self.move(x, y)

    def salir_de_paginas(self) -> bool:
        """Antes de cambiar de pestaña o de proyecto, o de cerrar: se sale de 🎬 Escenas (pregunta si hay cambios sin
        aplicar) y de 🖼 Miniatura (se guarda). False = el usuario canceló."""
        if getattr(self, "_scenes_state", None) is not None:
            pg = getattr(self, "_scenes_widget", None)
            if pg is not None and not pg.volver("edit"):
                return False
        if getattr(self, "_thumb_page", None) is not None and getattr(self, "_thumb_editor", None) is not None:
            self._thumb_editor.close()
        return True

    def _colocar_audio_mix(self):
        d, ai = self.docks["audio_mix"], self.docks["ai"]
        if d.isFloating():
            d.setFloating(False)
        if not ai.isFloating() and self.dockWidgetArea(ai) != Qt.NoDockWidgetArea:
            self.tabifyDockWidget(ai, d)
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, d)
        d.setVisible(True)

    def _colocar_junto(self, key: str, vecinos: tuple):
        """Pone el panel en pestaña junto al primer vecino acoplado (si no hay, a la izquierda) y a la vista."""
        d = self.docks[key]
        if d.isFloating():
            d.setFloating(False)
        for v in vecinos:
            o = self.docks.get(v)
            if o is not None and not o.isFloating() and not o.isHidden() and \
                    self.dockWidgetArea(o) != Qt.NoDockWidgetArea:
                self.tabifyDockWidget(o, d)
                break
        else:
            self.addDockWidget(Qt.LeftDockWidgetArea, d)
        d.setVisible(True)

    def apply_font_scale(self):
        """Aplica Ventana → Tamaño de letra (paneles y menús / global) al momento."""
        from .theme import apply_fonts, scaled_style
        ui, tl = apply_fonts(QApplication.instance())
        self.timeline_box.setStyleSheet(scaled_style(tl))     # la línea de tiempo usa solo la escala global
        self.timeline.set_text_scale(tl)
        k = max(1.0, ui)                                       # barras de alto fijo: que quepa la letra
        for name, base in (("pagebar", 30), ("topbar", 30), ("barrapaneles", 30)):
            w = self.findChild(QWidget, name)
            if w is not None:
                w.setFixedHeight(int(base * k))
        self._medir_paginas()                                  # (↔ con otra letra, otros anchos de la barra de abajo)
        self._medir_interruptores()                            # (y de los interruptores de arriba)
        self.preview.poner_alto_cabecera(int(30 * k))          # (alto de cada fila: puede tener dos)
        QTimer.singleShot(0, self._ajustar_paneles)            # (con otra letra, otros anchos mínimos)
        from . import diseno                                   # (🎨 los componentes del diseño, también al momento)
        diseno.refrescar_escala()
        if getattr(self, "_tl_bar", None) is not None:         # (✂ otra letra = otros anchos: la barra, a recolocar ya,
            self._tl_min_cache = None                          #  sin esperar a que cambie de tamaño)
            self._tl_fit_bar()
            QTimer.singleShot(0, self._tl_fit_bar)

    def open_font_size(self):
        from .font_dialog import FontSizeDialog
        FontSizeDialog(self).exec()

    def example_dir(self) -> str:
        return os.path.join(os.path.expanduser("~"), "Videos", "Reclaimer", "Proyecto de ejemplo")

    def open_example(self):
        """🎓 Proyecto de ejemplo: lo crea (descarga los clips de Pexels la primera vez), lo abre y abre su lección."""
        if getattr(self, "_example_job", None) is not None:
            self.statusBar().showMessage("🎓 Ya se está preparando el proyecto de ejemplo…", 5000)
            return
        from ..core import example_project as EX
        from .jobs import BackgroundJob             # (faltaba: sin los clips descargados, fallaba al empezar)
        dest = self.example_dir()
        ruta = os.path.join(dest, EX.NOMBRE + ".eia")
        existe = os.path.isfile(ruta)
        if existe and not EX.missing(dest):
            self._open_example_file(ruta)
            return

        def work(progress, cancelled):
            if existe:                               # (falta algo: se repone sin tocar lo que practicaste)
                return ruta, EX.repair(dest, progress, cancelled)
            return EX.build(dest, progress, cancelled)

        def done(res=None):
            self._example_job = None
            if isinstance(res, tuple):
                self._open_example_file(res[0], res[1])

        def failed(msg):
            self._example_job = None
            if "ancel" in str(msg):                  # (cancelado desde Tareas: no es un error)
                self.statusBar().showMessage("🎓 Proyecto de ejemplo cancelado.", 5000)
                return
            QMessageBox.warning(self, "Proyecto de ejemplo", f"No pude preparar el proyecto de ejemplo:\n{msg}")
        job = BackgroundJob(work, self)
        job.title = "🎓 Preparando el proyecto de ejemplo"
        job.done.connect(done)
        job.failed.connect(failed)
        self._example_job = job
        self.statusBar().showMessage("🎓 Preparando el proyecto de ejemplo (la primera vez descarga 5 clips de "
                                     "Pexels, unos 15 MB)…", 10000)
        job.start()

    def _open_example_file(self, path: str, fallos: list | None = None):
        if os.path.normcase(self.ctrl.path or "") != os.path.normcase(path):
            self.open_project(path)
        if os.path.normcase(self.ctrl.path or "") == os.path.normcase(path):
            self.timeline.fit() if hasattr(self.timeline, "fit") else None
            self.open_guide("proyecto_ejemplo")
            if fallos:
                self.statusBar().showMessage(f"🎓 Proyecto de ejemplo abierto, pero faltan {len(fallos)} clip(s) de "
                                             "Pexels (¿sin internet?). Vuelve a pulsar Ayuda → «🎓 Proyecto de "
                                             "ejemplo» para intentarlo otra vez.", 15000)
            else:
                self.statusBar().showMessage("🎓 Proyecto de ejemplo abierto: sigue los pasos de la guía. Los clips son "
                                             "de Pexels (sus créditos salen solos en la descripción al exportar).", 10000)

    def abrir_guia_primer_uso(self):
        """👋 Ayuda → «Guía de primer uso» (y la primera vez que abres Reclaimer): el recorrido corto por los sitios
        de siempre (ui/guia_primer_uso.py). Al terminar, todo vuelve a como estaba."""
        from .guia_primer_uso import empezar
        return empezar(self)

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
        """Muestra y pone delante el panel que contiene ese widget (esté donde esté). Los que viven dentro de «Voz y
        texto», «Audio» o el Inspector (agrupación 20/11) abren su sección."""
        destino = self._destino_absorbido(widget)
        if destino is not None:
            dk = self.abrir_seccion(*destino)
            pal = getattr(self, "_pal_tabs", None)
            if pal is not None and pal.indexOf(widget) >= 0:
                pal.setCurrentWidget(widget)           # (Dijiste… · Carpetas · Buscar material: la suya delante)
            return dk
        for key, dock in self.docks.items():
            if getattr(dock, "panel", None) is widget or dock.widget() is widget:
                if key in self.PAGINA_FX:              # (las columnas de la página Efectos de antes: el panel Efectos)
                    return self.show_panel(self.effects)
                if self._lado_incoherente(key):        # (siempre en el lado de su interruptor)
                    self._paneles_a_su_sitio(solo=[key])
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

    def _barra_paneles(self) -> QWidget:
        """🎛 La fila de los paneles, debajo de la barra de arriba (como la de DaVinci: Panel multimedia · Efectos · … ·
        Inspector): la ÚNICA forma de elegir los paneles de los lados en Editar (sus filas de pestañas no se ven: el
        usuario, «la 1, como DaVinci»). A la izquierda lo que AÑADES, a la derecha CÓMO ES lo elegido. Marcado = el
        que se ve delante en su sitio; clic = ponerlo delante; clic en el que ya está delante = ocultarlo."""
        from .theme import BG_DEEP
        bar = QWidget()
        bar.setObjectName("barrapaneles")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(f"QWidget#barrapaneles {{ background: {BG_DEEP}; }}")
        bar.setFixedHeight(30)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        self.interruptores = {}
        # (cada interruptor en la fila del lado donde se abre su panel: si arrastras un panel al otro lado, su
        #  interruptor se muda con él y se recuerda —_lado_panel—; así fila y lado siempre coinciden)
        todos = self.INTERRUPTORES_IZQ + self.INTERRUPTORES_DER
        izq = self._fila_interruptores([x for x in todos if self._lado_panel(x[0]) == "izq"])
        der = self._fila_interruptores([x for x in todos if self._lado_panel(x[0]) == "der"])
        self._filas_inter = {"izq": izq, "der": der}
        # ◧ «A todo el alto»: los paneles de la izquierda hasta abajo (la línea de tiempo empieza a su derecha)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton
        from .theme import TEXT_DIM, glyph_icon
        self._btn_alto = QToolButton()
        self._btn_alto.setObjectName("interruptor")
        self._btn_alto.setText("A todo el alto")
        self._btn_alto.setIcon(glyph_icon("◧", 16, TEXT_DIM, "#ffffff"))
        self._btn_alto.setIconSize(QSize(16, 16))
        self._btn_alto.setCheckable(True)
        self._btn_alto.setFocusPolicy(Qt.NoFocus)
        self._btn_alto.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn_alto.setToolTip("A todo el alto: los paneles de la izquierda (Medios, Efectos, IA…) llegan hasta "
                                  "abajo y la línea de tiempo empieza a su derecha, como en DaVinci.\nApagado: la línea "
                                  "de tiempo ocupa todo el ancho de abajo. Si en tu pantalla no cabe la línea de tiempo "
                                  "con todos sus botones, se queda a todo el ancho. También en Ventana.")
        self._btn_alto.setChecked(self.biblioteca_alto())
        self._btn_alto.toggled.connect(self.set_biblioteca_alto)
        self._medir_interruptores([self._btn_alto])
        der.layout().insertWidget(0, self._btn_alto)
        der.layout().insertSpacing(1, 8)
        lay.addWidget(izq)
        lay.addStretch()
        lay.addWidget(der)
        self._barra_arriba = bar
        bar.installEventFilter(self._vigia_arriba)       # (↔ interruptores con nombre o solo icono según quepan)
        return bar

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
        self.project_title = _TituloCorto()            # (↔ se acorta con «…» si no cabe: la ventana no se ensancha)
        self.project_title.setObjectName("dim")
        # ☰ Todos los paneles en un menú (las pestañas que no caben se quedan con su icono: sin deslizar)
        from PySide6.QtWidgets import QMenu
        self.btn_show_inspector = QPushButton("☰  Paneles")
        self.btn_show_inspector.setObjectName("flat")
        self.btn_show_inspector.setToolTip("Ir a cualquier panel: Inspector, Limpieza, Subtítulos, Historial…")
        self._menu_paneles = QMenu(self.btn_show_inspector)
        self._menu_paneles.aboutToShow.connect(self._llenar_menu_paneles)
        self.btn_show_inspector.setMenu(self._menu_paneles)
        self.btn_show_media.setVisible(False)          # (fase 1: «Medios» es ahora un interruptor más; ver abajo)
        lay.addWidget(self.btn_show_media)
        lay.addStretch()
        lay.addWidget(self.workspaces.bar)
        lay.addSpacing(10)
        lay.addWidget(self.project_title)
        lay.addStretch()
        # 🖼 En la página Miniatura: exportar siempre a la vista (en su barra, con la ventana estrecha, se escondía)
        self.btn_export_thumb = QPushButton("⬇ Exportar miniatura")
        self.btn_export_thumb.setObjectName("primary")
        self.btn_export_thumb.setToolTip("Guarda la miniatura como imagen (JPG por debajo de 2 MB, el límite de "
                                         "YouTube, o PNG)")
        self.btn_export_thumb.clicked.connect(
            lambda: self._thumb_editor.export() if getattr(self, "_thumb_editor", None) is not None else None)
        self.btn_export_thumb.setVisible(False)
        lay.addWidget(self.btn_export_thumb)
        lay.addSpacing(10)
        self.btn_font = QPushButton("🔠 Letra")
        self.btn_font.setObjectName("flat")
        self.btn_font.setToolTip("Hacer las letras más grandes o más pequeñas (también en Ventana → Tamaño de letra)")
        self.btn_font.clicked.connect(self.open_font_size)
        lay.addWidget(self.btn_font)
        # 🎨 Diseño: color de acento (al momento), tema y tamaño de letra
        from PySide6.QtWidgets import QMenu as _QMenu
        self.btn_diseno = QPushButton("🎨 Diseño")
        self.btn_diseno.setObjectName("flat")
        self.btn_diseno.setToolTip("Opciones de diseño de Reclaimer: color de acento (lo elegido, lo activo y el botón "
                                   "principal; se ve al momento), tema y tamaño de letra")
        self._menu_diseno = _QMenu(self.btn_diseno)
        self._menu_diseno.setToolTipsVisible(True)
        self._menu_diseno.addSection("Color de acento")
        self._llenar_acentos(self._menu_diseno)
        self._menu_diseno.addSeparator()
        self._tema_menu(self._menu_diseno)
        self._menu_diseno.addAction("🔠 Tamaño de letra…", self.open_font_size)
        self.btn_diseno.setMenu(self._menu_diseno)
        lay.addWidget(self.btn_diseno)
        lay.addSpacing(6)
        lay.addWidget(self.btn_show_inspector)
        return bar

    # 🎛 Interruptores de la barra de arriba: (panel, nombre). El resto de paneles, en «☰ Paneles» y en Ventana.
    # (todos los paneles que pueden estar a los lados en Editar tienen el suyo: así sus filas de pestañas sobran y nada
    #  sale dos veces. «Transcripción» es el panel «Texto» —lo dicho, sincronizado—: con el nombre «Texto» se
    #  confundía con la pestaña Texto del Inspector, que es el texto en pantalla)
    # (agrupación 20/11: «Voz y texto» y «Audio» reúnen lo que antes eran 9 interruptores; Historial y Gráficas,
    #  en ☰ Paneles; Material del clip, en Inspector → Archivo)
    INTERRUPTORES_IZQ = (("media", "Medios"), ("effects", "Transiciones y efectos"), ("sounds", "Sonidos"), ("ai", "IA"),
                         ("moments", "Momentos"), ("memes", "Memes"), ("descargas_web", "Descargas"),
                         ("voz_texto", "Voz y texto"), ("edit_clips", "Clips del edit"))
    # (22/11: «Voz y texto» a la izquierda; a la derecha, «Palabras clave» y «Limpieza» con todo su sitio)
    INTERRUPTORES_DER = (("palabras", "Palabras clave"), ("audio", "Limpieza y mezcla"),
                         ("edit_opts", "Edit musical"), ("inspector", "Inspector"))
    INTERRUPTORES_TIP = {
        "media": "tus videos, imágenes y sonidos importados",
        "effects": "transiciones, efectos, filtros y figuras para arrastrar a los clips",
        "sounds": "efectos de sonido (los tuyos y de internet)",
        "ai": "las herramientas de IA: transcribir, B-roll, primera versión…",
        "clips": "la página 🔑 Palabras clave: lo que dices, buscar material, carpetas y lo descargado",
        "transcript": "el texto de lo que se dice (la transcripción), sincronizado con el video",
        "moments": "buscar momentos en tus videos por lo que se ve o se dice",
        "descargas_web": "buscar y bajar de internet lo que quieras (videos, imágenes o un enlace), sin palabra clave",
        "memes": "tu biblioteca de memes: la misma en todos tus proyectos",
        "audio_mix": "mezcla y música: bajar la música cuando hablas, sonoridad…",
        "edit_clips": "los clips del edit musical (pestaña Edits)",
        "voz_ia": "que una voz sintética lea tu guion",
        "history": "el historial de cambios (deshacer hasta un punto)",
        "scopes": "gráficas de color y de nivel de la imagen",
        "edit_opts": "las opciones del edit musical (pestaña Edits)",
        "subtitles": "los subtítulos del video y su estilo",
        "voice": "limpieza de la voz: silencios, muletillas y repeticiones",
        "material": "lo que se sabe del clip elegido (o del que está bajo el cabezal)",
        "inspector": "cómo es lo elegido: tamaño, posición, sonido, color…",
        "voz_texto": "todo lo de la voz y el texto, en orden: 1 Transcribir · 2 Transcripción · 3 Subtítulos · "
                     "4 Voz IA",
        "palabras": "las palabras clave de tu narración: Dijiste… (cada palabra y sus momentos) · Carpetas (su "
                    "material y lo descargado) · Buscar material (tu carpeta o internet)",
        "audio": "el sonido: 1 Limpieza de la voz · 2 Mezcla y música · 3 Sonoridad (−14 LUFS) · 4 Cortes de audio"}

    def _fila_interruptores(self, lista) -> QWidget:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton

        from .theme import ACCENT, TEXT, TEXT_DIM, glyph_icon
        fila = QWidget()
        fila.setObjectName("interruptores")
        fila.setStyleSheet(
            f"QToolButton#interruptor {{ background: transparent; border: none; border-bottom: 2px solid transparent;"
            f" color: {TEXT_DIM}; padding: 2px 6px; }}"
            f"QToolButton#interruptor:hover {{ color: {TEXT}; }}"
            f"QToolButton#interruptor:checked {{ color: white; border-bottom: 2px solid {ACCENT}; }}"
            f"QToolButton#interruptor[sin_efecto=\"true\"] {{ color: {TEXT_DIM}; "
            f"border-bottom: 2px dotted {TEXT_DIM}; }}")
        fl = QHBoxLayout(fila)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)
        for k, nombre in lista:
            d = self.docks.get(k)
            if d is None:
                continue
            b = QToolButton()
            b.setObjectName("interruptor")
            b.setText(nombre)
            b.setIcon(glyph_icon(self.ICONO_PANEL.get(k, "•"), 16, TEXT_DIM, "#ffffff"))
            b.setIconSize(QSize(16, 16))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setToolTip(f"{nombre}: {self.INTERRUPTORES_TIP.get(k, '')}.\nClic: lo abre delante; si ya está "
                         f"delante, lo cierra.")
            b.clicked.connect(lambda _c=False, k_=k: self._interruptor(k_))
            self._medir_interruptores([b])
            d.visibilityChanged.connect(self._interruptores_pronto)
            d.toggleViewAction().toggled.connect(self._interruptores_pronto)
            d.dockLocationChanged.connect(lambda area, k_=k: self._panel_cambio_de_lado(k_, area))
            d.topLevelChanged.connect(lambda suelto, d_=d: self._marcar_arrastre(d_, suelto))
            self.interruptores[k] = b
            fl.addWidget(b)
        if not hasattr(self, "_t_interruptores"):
            from PySide6.QtCore import QEvent, QObject
            self._t_interruptores = QTimer(self)
            self._t_interruptores.setSingleShot(True)
            self._t_interruptores.setInterval(0)
            self._t_interruptores.timeout.connect(self._sync_interruptores)

            class _VigiaArriba(QObject):
                def __init__(self, win):
                    super().__init__(win)
                    self.win = win

                def eventFilter(self, obj, ev):
                    # (también LayoutRequest: aparece «Exportar miniatura» o cambia el nombre del proyecto)
                    if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                        self.win._interruptores_que_caben()
                    return False
            self._vigia_arriba = _VigiaArriba(self)
        QTimer.singleShot(0, self._sync_interruptores)
        return fila

    def _medir_interruptores(self, botones=None):
        """Ancho de cada interruptor con su nombre y con solo el icono (con la letra de ahora); su mínimo, el icono."""
        todos = list(getattr(self, "interruptores", {}).values()) + \
            [x for x in [getattr(self, "_btn_alto", None)] if x]
        for b in botones if botones is not None else todos:
            estilo = b.toolButtonStyle()
            b.ensurePolished()
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setProperty("ancho_nombre", b.sizeHint().width())
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setProperty("ancho_icono", b.sizeHint().width())
            b.setMinimumWidth(b.sizeHint().width())      # (nunca obliga a ensanchar la ventana: como mínimo, su icono)
            b.setToolButtonStyle(estilo)
        if botones is None:
            self._interruptores_que_caben()

    def _interruptores_pronto(self, *_a):
        t = getattr(self, "_t_interruptores", None)
        if t is not None and not t.isActive():
            t.start()

    def _interruptor_abierto(self, k: str) -> bool:
        d = self.docks[k]
        if d.isHidden():
            return False
        # (si comparte sitio con otros, solo cuenta el que se ve delante: como en DaVinci, uno por sitio)
        return d.isFloating() or not self.tabifiedDockWidgets(d) or not d.visibleRegion().isEmpty()

    # (paneles que solo tienen sentido en una pestaña de trabajo: en las demás, su interruptor no sale)
    SOLO_EN_PESTANA = {"edit_opts": "edit", "edit_clips": "edit"}

    def _interruptor_util(self, k: str) -> bool:
        """¿Sale el interruptor de este panel en la pestaña de trabajo actual? Los del edit musical, solo en Edits;
        los de cada pestaña (TAB_PANELS), si esa pestaña los usa, si los encendiste tú en ella o si están abiertos.
        (Todos siguen en «Ventana».)"""
        tab = getattr(getattr(self, "workspaces", None), "current", "youtube")
        if k in self.SOLO_EN_PESTANA:
            return tab == self.SOLO_EN_PESTANA[k]
        # (agrupación 20/11: «Voz y texto» y «Audio» reúnen paneles de todas las pestañas; TAB_PANELS decide si salen
        #  ABIERTOS, no si su interruptor existe —si no, «Voz y texto» no se podía abrir en Video horizontal—)
        return True

    def _sync_interruptores(self):
        """Cada interruptor, marcado si su panel está abierto (delante o detrás de otra pestaña); y solo los de la
        pestaña de trabajo actual."""
        cambio = False
        for k, b in getattr(self, "interruptores", {}).items():
            util = self._interruptor_util(k)
            if b.isHidden() == util:
                b.setVisible(util)
                cambio = True
        if cambio:
            QTimer.singleShot(0, self._interruptores_que_caben)
        for k, b in getattr(self, "interruptores", {}).items():
            on = self._interruptor_abierto(k)
            if b.isChecked() != on:
                b.setChecked(on)

    def _interruptor(self, k: str):
        """🎛 Clic en un interruptor: abre el panel delante (en su página si solo vive en una); si ya estaba abierto y
        delante, lo cierra (como «Ventana»: en Editar se recuerda por pestaña de trabajo)."""
        d = self.docks[k]
        if self._lado_incoherente(k) and not d.isHidden():   # (abierto en el otro lado: a su lado, a la vista)
            self._paneles_a_su_sitio(solo=[k])
            self.show_panel(d.panel)
            self._sync_interruptores()
            return
        if self._paneles_a_su_sitio(solo=[k]):          # (suelto encima de la ventana: acoplado a su lado Y a la
            self.show_panel(d.panel)                    #  vista en el mismo clic —revisión: hacía falta otro—)
            self._sync_interruptores()
            return
        if getattr(self, "_scenes_state", None) is not None or getattr(self, "_thumb_page", None) is not None:
            self.go_page("edit")                        # (🎬 Escenas / 🖼 Miniatura ocupan la ventana: primero a Editar)
            if getattr(self, "_scenes_state", None) is not None or getattr(self, "_thumb_page", None) is not None:
                return                                  # (cambios sin aplicar y «Cancelar»: se queda)
            if not d.isHidden():
                d.show()
                d.raise_()
                self._sync_interruptores()
                return
        if self._interruptor_abierto(k) and not d.isHidden() and not d.visibleRegion().isEmpty():
            d.toggleViewAction().trigger()
        else:
            self.show_panel(d.panel)
        self._sync_interruptores()

    def _interruptores_que_caben(self):
        """↔ Con su nombre si caben todos; si no, todos con solo su icono (el nombre, en el tooltip). Nunca obliga a
        una ventana más ancha (cada interruptor pide como mínimo su icono)."""
        bar = getattr(self, "_barra_arriba", None)
        if bar is None or not getattr(self, "interruptores", None):
            return
        if getattr(self, "_ajustando_arriba", False):
            return
        botones = [b for b in self.interruptores.values() if not b.isHidden()] + \
            [x for x in [getattr(self, "_btn_alto", None)] if x]
        extra = sum(int(b.property("ancho_nombre")) - int(b.property("ancho_icono")) for b in botones)
        lay = bar.layout()
        # (el mínimo de la barra con todos en solo icono, sin tocarlos: así no baila)
        base = lay.minimumSize().width() - sum(b.minimumWidth() for b in botones) +             sum(int(b.property("ancho_icono")) for b in botones)
        cabe = base + extra + 24 <= bar.width()
        estilo = Qt.ToolButtonTextBesideIcon if cabe else Qt.ToolButtonIconOnly
        # (con nombre, el que cede es el nombre del proyecto —se acorta con «…»—, no un interruptor: con un nombre de
        #  proyecto largo se cortaban en «M…s». Se le pone como máximo lo que sobra; el mínimo de cada interruptor
        #  sigue siendo su icono, así la ventana se puede estrechar y entonces pasan a solo icono)
        titulo = None                                   # (el nombre del proyecto ya no va en esta fila)
        tope = 16777215
        if cabe and titulo is not None:
            m_t = titulo.minimumSizeHint().width()
            tope = max(m_t, m_t + bar.width() - base - extra - 24)
        self._ajustando_arriba = True
        try:
            for b in list(self.interruptores.values()) + [x for x in [getattr(self, "_btn_alto", None)] if x]:
                minimo = int(b.property("ancho_icono"))       # (también los escondidos: igual al volver a salir)
                if b.toolButtonStyle() != estilo:
                    b.setToolButtonStyle(estilo)
                if b.minimumWidth() != minimo:
                    b.setMinimumWidth(minimo)
            if titulo is not None and titulo.maximumWidth() != tope:
                titulo.setMaximumWidth(tope)
        finally:
            self._ajustando_arriba = False

    # (agrupación 20/11, decisión del usuario: abajo solo Editar · Escenas · Miniatura · Entrega, a la mitad de alto.
    #  Medios y Efectos → sus interruptores; Palabras clave/Audio/Transcripción → «Voz y texto» y «Audio»; Montaje
    #  guiado → botón en la barra de menús. go_page sigue aceptando esas claves y lleva a su sitio nuevo)
    PAGES = [("edit", "🎞", "Editar"), ("scenes", "🎬", "Escenas"), ("thumb", "🖼", "Miniatura"),
             ("deliver", "🚀", "Entrega")]
    # (el nombre completo de las páginas con nombre corto en la barra: en su tooltip)
    PAGE_TIPS = {"effects": "✦ Efectos (solo lo visual): Transiciones · Efectos · Filtros (color y aspecto) · "
                            "Figuras geométricas (tapar / censurar y figuras de color)",
                 "fairlight": "🎚 Audio: volumen y ecualizador, mezcla y música, limpieza de la voz, sonidos y corte "
                              "de audio",
                 "transcripcion": "📝 Transcripción y subtítulos: transcribir y la narración, el texto, los "
                                  "subtítulos y la IA (IA ✨, Momentos, Voz IA)"}
    # (14/11: «IA» ya no va en esta barra: la IA tiene UN sitio, la pestaña «IA ✨» del panel, con «✨ Más»)

    def _page_bar(self) -> QWidget:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton

        from .theme import glyph_icon
        bar = QWidget()
        bar.setObjectName("pagebar")
        bar.setFixedHeight(30)                         # (a la mitad: icono y nombre en una línea)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(6)
        lay.addStretch()
        self.page_buttons = {}
        for key, icon, label in self.PAGES:            # icono de un color encima del nombre, como en Resolve
            b = QToolButton()
            b.setText(label)
            b.setIcon(glyph_icon(icon, 16))
            b.setIconSize(QSize(16, 16))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setObjectName("page")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=key: self.go_page(k))
            b.setToolTip(self.PAGE_TIPS.get(key, label))   # (con la barra en solo iconos, el nombre aquí)
            self.page_buttons[key] = b
            lay.addWidget(b)
        lay.addStretch()
        self.page_buttons["edit"].setChecked(True)
        # ↔ La barra nunca obliga a una ventana más ancha (con 🔑 Palabras clave y 📝 Transcripción pedía ~1600 px):
        # cada botón puede quedarse en su icono (mínimo = solo icono) y, si los nombres no caben, van todos con
        # solo el icono (el nombre, en el tooltip); al ensancharse vuelven los nombres.
        from PySide6.QtCore import QEvent, QObject

        class _VigiaPaginas(QObject):
            def __init__(self, win):
                super().__init__(win)
                self.win = win

            def eventFilter(self, obj, ev):
                if ev.type() in (QEvent.Resize, QEvent.Show):
                    self.win._paginas_que_caben()
                return False
        self._vigia_paginas = _VigiaPaginas(self)
        bar.installEventFilter(self._vigia_paginas)
        self._page_bar_w = bar
        self._medir_paginas()
        return bar

    def _medir_paginas(self):
        """Ancho de cada botón de página con su nombre y con solo el icono (con la letra de ahora)."""
        for b in getattr(self, "page_buttons", {}).values():
            estilo = b.toolButtonStyle()
            b.ensurePolished()
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            corto = b.sizeHint().width()
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setProperty("ancho_largo", b.sizeHint().width())
            b.setToolButtonStyle(estilo)
            b.setMinimumWidth(corto)
        self._paginas_que_caben()

    def _paginas_que_caben(self):
        bar = getattr(self, "_page_bar_w", None)
        if bar is None or not getattr(self, "page_buttons", None):
            return
        lay = bar.layout()
        m = lay.contentsMargins()
        botones = list(self.page_buttons.values())
        largo = m.left() + m.right() + lay.spacing() * (len(botones) + 1) +             sum(int(b.property("ancho_largo") or b.sizeHint().width()) for b in botones)
        estilo = Qt.ToolButtonTextBesideIcon if bar.width() >= largo else Qt.ToolButtonIconOnly
        for b in botones:
            if b.toolButtonStyle() != estilo:
                b.setToolButtonStyle(estilo)

    def go_page(self, key: str):
        """Cambiar de «página» como en Resolve (todas trabajan sobre el mismo proyecto). Las que ya no están abajo
        (agrupación 20/11) llevan a su sitio nuevo: Palabras clave / Transcripción → «Voz y texto»; Audio → «Limpieza
        y mezcla»; Efectos → el panel «Transiciones y efectos» en Editar; Entrega → exportar. Abajo queda marcada la
        página en la que estás: lo que no tiene botón propio (🧭 Montaje guiado, Medios…) se hace en «Editar»."""
        destino = {"keywords": ("palabras", "palabras"), "transcripcion": ("voz_texto", "transcripcion"),
                   "fairlight": ("audio", "limpieza")}.get(key)
        if destino is not None:
            return self.abrir_seccion(*destino)
        if key == "effects":
            self.go_page("edit")
            return self.show_panel(self.effects)
        if key != "thumb" and self._thumb_page is not None and getattr(self, "_thumb_editor", None) is not None:
            self._thumb_editor.close()             # sale de 🖼 Miniatura (se guarda) y vuelve el editor
        if key != "scenes" and getattr(self, "_scenes_state", None) is not None:
            pg = getattr(self, "_scenes_widget", None)
            if pg is not None and not pg.volver(key):     # (cambios sin aplicar y «Cancelar»: se queda)
                for k, b in self.page_buttons.items():
                    b.setChecked(k == "scenes")
                return
        marcada = key if key in self.page_buttons else "edit"     # (Montaje guiado, Medios…: se está en Editar)
        for k, b in self.page_buttons.items():
            b.setChecked(k == marcada)
        if key == "scenes":
            self.open_scenes()
        elif key == "media":
            self.show_panel(self.library)
            self.library.search.setFocus()
        elif key == "edit":
            self.show_panel(self.library)
            self.show_panel(self.inspector)
        elif key == "guided":
            d = self.docks
            if d["guided"] in self.tabifiedDockWidgets(d["clips"]) or d["guided"].isFloating() or                     d["guided"].isHidden():      # (en pestaña con 🎬 Clips se tapaban: el guiado, debajo, a la vista)
                d["guided"].setFloating(False)
                self.removeDockWidget(d["guided"])
                self.addDockWidget(Qt.RightDockWidgetArea, d["guided"], Qt.Vertical)
            self.show_panel(self.guided)
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

        from .shortcuts_dialog import extra_permitido, saved_shortcut
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
        act(m, "Cambiar el nombre del proyecto", "F2", lambda: self.preview.title_label.editar())
        act(m, "📋 Guardar como plantilla…", None, self.save_as_template)
        act(m, "Guardar nueva versión (v01, v02…)", "Ctrl+Alt+S", self.save_version)
        act(m, "💾 Guardado y copias de seguridad…", None, lambda: self.saving.open_settings())
        act(m, "⟲ Recuperar una copia de seguridad…", None, lambda: self.saving.open_settings())
        act(m, "📦 Recopilar proyecto (copia con todos sus archivos)…", None, self.open_collect)
        m.addSeparator()
        # 🗂 Cambiar de pestaña de trabajo con el teclado (lo de la pestaña que dejas queda guardado)
        act(m, "🎬 Ir a la pestaña Video horizontal", "Ctrl+1", lambda: self.workspaces.switch("youtube"))
        act(m, "🎵 Ir a la pestaña Edits", "Ctrl+2", lambda: self.workspaces.switch("edit"))
        act(m, "📱 Ir a la pestaña Vertical", "Ctrl+3", lambda: self.workspaces.switch("short"))
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
        act(m, "⇄ Llevar a DaVinci Resolve / Premiere (XML)…", None, self.export_xml,
            "Guarda la línea de tiempo (clips, pistas, velocidad, volumen, transiciones y marcadores) en un XML que "
            "DaVinci Resolve, Premiere Pro y Final Cut 7 abren con «Importar línea de tiempo». Los archivos no se "
            "copian: el otro editor los busca donde están.")
        m.addSeparator()
        act(m, "Salir", "Ctrl+Q", self.close)

        m = mb.addMenu("&Editar")
        undo = self.ctrl.undo_group.createUndoAction(self, "Deshacer")    # el de la pestaña activa
        undo.setShortcut(QKeySequence.Undo)
        redo = self.ctrl.undo_group.createRedoAction(self, "Rehacer")
        redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self._act_deshacer, self._act_rehacer = undo, redo       # (🧭 el cuadro del texto del Inspector usa sus atajos)
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
        a_div = act(m, "Dividir en el cabezal", "Ctrl+B", self._split)      # (Ctrl+B, como en DaVinci Resolve)
        if a_div.shortcut().toString() == "Ctrl+B" and \
                extra_permitido(next(k for k, (a, _d) in self.shortcut_actions.items() if a is a_div), "S"):
            a_div.setShortcuts([QKeySequence("Ctrl+B"), QKeySequence("S")])   # (también la S de siempre)
        act(m, "Recortar el inicio hasta el cabezal (y cerrar el hueco)", "Q", lambda: self._trim_playhead("start"),
            "Quita lo que hay antes del cabezal en el clip elegido (si no, en el del canal elegido o la pista principal) "
            "y ese tramo sale de todas las pistas a la vez: nada se desincroniza")
        act(m, "Recortar el final hasta el cabezal (y cerrar el hueco)", "W", lambda: self._trim_playhead("end"),
            "Quita lo que hay después del cabezal en el clip elegido (si no, en el del canal elegido o la pista "
            "principal) y ese tramo sale de todas las pistas a la vez: nada se desincroniza")
        act(m, "Mover el clip 1 fotograma a la izquierda", ",", lambda: self._nudge_frames(-1),
            "Mueve el clip elegido (y su imagen o sonido vinculado) un fotograma antes. No tapa nada: si está pegado "
            "a otro clip, avisa y no se mueve. Varias pulsaciones seguidas se deshacen con un Ctrl+Z")
        act(m, "Mover el clip 1 fotograma a la derecha", ".", lambda: self._nudge_frames(1),
            "Mueve el clip elegido (y su imagen o sonido vinculado) un fotograma después. No tapa nada: si está "
            "pegado a otro clip, avisa y no se mueve. Varias pulsaciones seguidas se deshacen con un Ctrl+Z")
        act(m, "Seleccionar todo lo que hay desde el cabezal hacia delante", "Y", lambda: self._select_from_playhead(True),
            "Elige los clips que pasan por el cabezal o van después (solo en los canales elegidos, si hay)")
        act(m, "Seleccionar todo lo que hay desde el cabezal hacia atrás", "Alt+Y",
            lambda: self._select_from_playhead(False),
            "Elige los clips que pasan por el cabezal o van antes (solo en los canales elegidos, si hay)")
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
        # 🎬 Modos de edición (como Resolve): lo elegido en Medios, en el cabezal, en el canal elegido (fase 6)
        sub = m.addMenu("Poner lo elegido en Medios")
        sub.setToolTipsVisible(True)
        for modo, atajo, tip in (
                ("insertar", "F9", "Lo pone en el cabezal abriendo su hueco en TODAS las pistas: lo de detrás se corre "
                                   "entero y nada se desincroniza ni se tapa (lo que cruza el cabezal se parte)."),
                ("sobrescribir", "F10", "Lo pone en el cabezal tapando solo lo de la pista de destino (su sonido va a "
                                        "una pista libre: tu narración no se pisa)."),
                ("reemplazar", "Shift+F11", "El clip de la pista de destino que pasa por el cabezal enseña este archivo "
                                            "(mismo sitio y largo). En Resolve es F11; aquí F11 es el visor en la "
                                            "segunda pantalla (se cambia en ⌨ Personalizar atajos)."),
                ("encima", "F12", "Lo pone en la primera pista de video libre por encima de la de destino (o en una "
                                  "nueva arriba), en el cabezal."),
                ("al_final", "Shift+F12", "Lo pone justo detrás del último clip de la pista de destino.")):
            a_ = act(sub, self.ctrl.MODOS_EDICION[modo], atajo, lambda _=False, md=modo: self._modo_edicion(md), tip)
            a_.setToolTip(tip + "\nLa pista de destino es el canal elegido en la línea de tiempo (si no, la principal).")
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
        act(m, "⧉ Poner transición (disolver) en el corte", "Alt+T", self._alt_t)
        m.addSeparator()
        act(m, "Herramienta de selección", "A", lambda: self.set_tool("select"))
        act(m, "Herramienta cuchilla", "B", lambda: self.set_tool("blade"))
        act(m, "Herramienta de recorte avanzado (ripple, roll, slip, slide)", "Shift+T", lambda: self.set_tool("trim"))
        act(m, "〰 Curvas de volumen y opacidad (sí/no)", "Shift+C",
            lambda: (self.tool_curves.toggle(), self.timeline.set_curves(self.tool_curves.isChecked())))
        act(m, "Imán (encajar) sí/no", "N", self._toggle_snap)
        a_w = m.addAction("🗣 Imán también a las palabras de la narración")
        a_w.setCheckable(True)
        a_w.setChecked(self.timeline.snap_words)
        a_w.setToolTip("Con el imán puesto, al mover o recortar se pega a donde empieza y acaba cada palabra de tu "
                       "narración: cortes justo entre palabras. Desactivado de entrada.")
        m.setToolTipsVisible(True)
        a_w.toggled.connect(self.timeline.set_snap_words)
        self.act_snap_words = a_w
        a_mg = m.addAction("🧲 Pista principal magnética")
        a_mg.setCheckable(True)
        a_mg.setChecked(self.timeline.magnetic_main)
        a_mg.setToolTip("En la pista de video principal (la de abajo) no quedan huecos: Supr y recortar un borde "
                        "adelantan lo de detrás en TODAS las pistas (nada se desincroniza). Si algo de otra pista sigue "
                        "por debajo (tu narración), no junta y avisa. Mayús+borde recorta sin juntar.")
        a_mg.toggled.connect(self.timeline.set_magnetic_main)
        self.act_magnetic = a_mg
        a_rh = m.addAction("🥁 Imán también a los golpes de la música")
        a_rh.setCheckable(True)
        a_rh.setChecked(self.timeline.snap_rhythm)
        a_rh.setToolTip("Con el imán puesto, los clips y la cuchilla se pegan a los golpes y al drop de las "
                        "canciones de la pista de música (su ritmo se reconoce solo al ponerlas).")
        a_rh.toggled.connect(self.timeline.set_snap_rhythm)
        self.act_snap_rhythm = a_rh

        m = mb.addMenu("&Reproducción")
        a_live = act(m, "🎧 Audio en directo (ecualizador mientras suena)", None, lambda: None,
                     "Como en DaVinci Resolve: el ecualizador, el volumen, las curvas, los fundidos y la música que baja "
                     "cuando hablas se oyen mientras reproduces, al instante de cambiarlos. Los efectos de PISTA "
                     "(mejora de voz, compresor) y el volumen final solo se oyen al exportar o con «Escuchar con EQ». "
                     "Apagado: suenan los reproductores de siempre.")
        a_live.setCheckable(True)
        a_live.setChecked(self.engine.live is not None)
        a_live.toggled.connect(self.engine.set_live_audio)
        self.a_live_audio = a_live
        act(m, "Reproducir alrededor del cabezal", "/", self._play_alrededor,
            "2 s antes y 2 s después del cabezal, y el cabezal vuelve a donde estaba: revisar un corte sin mover nada")
        a_scrub = act(m, "🔊 Oír al arrastrar el cabezal", "Shift+S", lambda: None,
                      "Mientras arrastras la barra roja suena un trocito de lo que hay ahí (como en Resolve o "
                      "Premiere): así encuentras los cortes sin darle a play. Va con «🎧 Audio en directo».")
        a_scrub.setCheckable(True)
        from .preview import scrub_activo as _scrub_on
        a_scrub.setChecked(_scrub_on())
        a_scrub.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "reproduccion/oir_al_arrastrar", "true" if on else "false"))
        a_vid = act(m, "🎞 Video con motor propio (beta)", None, lambda: None,
                    "Como DaVinci, Kdenlive o Shotcut: Reclaimer decodifica el video él mismo (en segundo plano, al "
                    "tamaño con que se ve), con fotogramas por delante y una caché de los recientes: cortes sin "
                    "trabas, saltos exactos y arrastrar el cabezal más fluido. Beta: si algo falla, apágalo y vuelven "
                    "los reproductores de siempre. El sonido de los videos va por «🎧 Audio en directo».")
        a_vid.setCheckable(True)
        a_vid.setChecked(self.engine._own_video_on())
        a_vid.toggled.connect(self.engine.set_own_video)
        self.a_own_video = a_vid
        a_tr = act(m, "⧉ Transiciones reales en el visor", None, lambda: None,
                   "Cada transición (deslizar, barrido, zoom, círculo…) se prepara en segundo plano con el mismo motor "
                   "que la exportación y el visor la enseña tal cual queda (en unos segundos tras ponerla). Apagado: "
                   "el visor las aproxima con un fundido.")
        a_tr.setCheckable(True)
        from .zone_preview import enabled as _zp_on
        a_tr.setChecked(_zp_on())
        a_tr.toggled.connect(lambda on: self.engine.zones.set_enabled(on) if self.engine.zones else None)
        self.a_real_trans = a_tr
        a_fx = act(m, "⚡ Pre-render de efectos pesados en el visor", None, lambda: None,
                   "Los tramos que el visor no puede enseñar o enseña lento (grano, glitch, tono cálido o frío, "
                   "desenfoque de movimiento, cámara lenta suave, máscara de la IA, pantalla verde, desenfoque por "
                   "zonas, efectos de edit, capas de ajuste) se preparan en segundo plano, en trozos, con el mismo "
                   "motor que la exportación: se ven tal cual y la reproducción va fluida. Primero lo cercano al "
                   "cabezal. Apagado: el visor los aproxima como siempre.")
        a_fx.setCheckable(True)
        from .zone_preview import fx_enabled as _zp_fx
        a_fx.setChecked(_zp_fx())
        a_fx.toggled.connect(lambda on: self.engine.zones.set_fx_enabled(on) if self.engine.zones else None)
        self.a_prerender_fx = a_fx
        if self.engine.zones is not None:          # ⧉⚡ franja de render en la regla (verde = listo)
            self.engine.zones.marks_changed.connect(self.timeline.set_render_marks)
            self.timeline.set_render_marks(self.engine.zones.marks())
        m.addSeparator()
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
        act(m, "⏪ Retroceder 5 segundos", "Shift+Left", lambda: self.engine.nudge(-5.0))     # (botones −5s / +5s)
        act(m, "⏩ Avanzar 5 segundos", "Shift+Right", lambda: self.engine.nudge(5.0))
        act(m, "⏩ Velocidad siguiente (1× → 2× → 4× → 8× → 1×)", None, self.engine.cycle_speed)
        act(m, "▶ Velocidad normal (1×)", None, lambda: self.engine.set_speed(1.0))
        act(m, "🔇 Silenciar / quitar el silencio de la escucha", None,
            lambda: self.preview.btn_vol.model.toggle_mute())
        act(m, "📊 Sonoridad para plataformas (LUFS)…", None, lambda: self.engine.loudness.start(self))
        act(m, "Ir al inicio", "Home", lambda: self.engine.seek(0))
        act(m, "Ir al final", "End", lambda: self.engine.seek(self.ctrl.project.duration()))
        a_up = act(m, "Ir al corte anterior", "Up", lambda: self._go_edit(-1),
                   "El cabezal salta al inicio o final de clip anterior (en los canales elegidos, si hay)")
        a_dn = act(m, "Ir al corte siguiente", "Down", lambda: self._go_edit(1),
                   "El cabezal salta al inicio o final de clip siguiente (en los canales elegidos, si hay)")
        a_mu = act(m, "Ir a la marca anterior", "Shift+Up", lambda: self._go_marca(-1),
                   "El cabezal salta a la marca anterior de la capa de marcas (tomas repetidas, muletillas, cortes "
                   "dudosos, OBS, temas, huecos sin imagen, material repetido, tus marcadores; los tipos que dejes "
                   "a la vista en el índice)")
        a_md = act(m, "Ir a la marca siguiente", "Shift+Down", lambda: self._go_marca(1),
                   "El cabezal salta a la marca siguiente de la capa de marcas (los tipos que dejes a la vista en el "
                   "índice: la sección «Marcadores» del Inspector)")
        for a_ in (a_up, a_dn, a_mu, a_md):  # (↑ ↓ solo con la línea de tiempo enfocada: las listas siguen con sus flechas)
            a_.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.removeAction(a_)
            self.timeline.addAction(a_)
        act(m, "Corte de audio anterior (línea roja)", "Alt+Left", lambda: self._go_cut(-1))
        act(m, "Corte de audio siguiente (línea roja)", "Alt+Right", lambda: self._go_cut(1))

        m = mb.addMenu("&Voz")
        act(m, "🎚 Voz pareja: el mismo volumen en cada frase", None, self._voz_pareja,
            "Lleva cada frase de tu narración al mismo nivel con una ganancia suave (±6 dB como mucho, cambios en las "
            "pausas, los silencios no suben). SOLO volumen: ni ecualizador ni compresor (tu voz ya viene igualada de "
            "OBS). Se oye al momento y un Ctrl+Z lo quita. Con clips de narración elegidos, solo en ellos.")
        act(m, "Quitar la voz pareja", None, lambda: self.statusBar().showMessage(
            __import__("editoria.core.voz_pareja", fromlist=["quitar"]).quitar(
                self.ctrl, [i for i in self.timeline.selected] or None), 6000))
        act(m, "Transcribir y analizar la narración", "Ctrl+T",                # (🎙 vive en la pestaña IA)
            lambda: (self.abrir_seccion("voz_texto", "transcribir"), self.voice.transcribe()))
        act(m, "Volver a analizar (silencios, muletillas…)", "Ctrl+Shift+T",
            lambda: (self.go_page("fairlight"), self.right_tabs.setCurrentWidget(self.voice), self.voice.analyze()))
        act(m, "🔎 Buscar en lo que dijiste", "Ctrl+Alt+F",           # (Ctrl+F ya es de «Buscar clips por contenido»)
            lambda: (self.go_page("transcripcion"), self.right_tabs.setCurrentWidget(self.transcript),
                     self.transcript.focus_search()))
        act(m, "Ver transcripción", None,               # (📝 en su página: Transcripción y subtítulos)
            lambda: (self.go_page("transcripcion"), self.right_tabs.setCurrentWidget(self.transcript)))
        act(m, "Estilo de subtítulos", None,
            lambda: (self.go_page("transcripcion"), self.right_tabs.setCurrentWidget(self.subtitles)))
        act(m, "Exportar subtítulos (.srt)…", None, self.transcript.export_srt)
        m.addSeparator()
        act(m, "🎙 Grabar voz en off…", "Ctrl+Shift+R", self.open_voice_record)
        act(m, "🎚 Analizar y proponer mezcla (música, diálogos y voz)…", None, self.open_mix)
        m.addSeparator()
        act(m, "◈ Entrenar la IA con mi voz", None, self.train_voice_now)
        act(m, "◈ Olvidar lo que la IA aprendió de mi voz…", None, self.forget_voice)

        # ✨ Menú «IA ✨» a la vista (13/11: él lo pidió; antes estaba escondido y solo guardaba los atajos). Lo de la
        # voz se queda en «Voz»; lo de la IA (B-roll, temas, edit musical, Shorts, primera versión…) va aquí.
        # (Los atajos se guardan como «IA/…»: el título se cambia después de crearlos para no perder los tuyos.)
        m = mb.addMenu("&IA")
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
        act(m, "⚕ Lista de avisos del proyecto…", "Ctrl+R", self.open_audit)
        act(m, "✓ Revisión guiada (una a una)…", "Ctrl+Shift+Q", self.open_quick_review)
        act(m, "✂ Shorts desde este video…", None, lambda: __import__(
            "editoria.ui.shorts_dialog", fromlist=["open_shorts_dialog"]).open_shorts_dialog(self))
        m.addSeparator()
        act(m, "✨ Primera versión automática…", "Ctrl+Shift+A", self.open_auto)
        act(m, "📜 Montaje desde el guion…", None, lambda: __import__(
            "editoria.ui.script_dialog", fromlist=["open_script_dialog"]).open_script_dialog(self))
        act(m, "Buscar clips por contenido", "Ctrl+F",
            lambda: (self.library.btn_ai_search.setChecked(True),
                     self.abrir_para_usar(self.library.search, self.library.search, True)))
        m.setTitle("IA ✨")
        # 14/11 (él): una sola IA = la pestaña «IA ✨» del panel. El menú sale de la barra de arriba; sus acciones van al
        # botón «✨ Más» de esa pestaña y sus atajos siguen funcionando (las acciones quedan en la ventana).
        mb.removeAction(m.menuAction())           # (act() ya puso cada acción en la ventana: los atajos siguen)
        self.ai_panel.set_more_menu(m)

        m = mb.addMenu("&Timeline")
        act(m, "T Añadir texto en el cabezal", "T", lambda: self.ctrl.add_text(self.engine.time, 4.0, "Texto"))
        tm = self._titles_menu(m)
        tm.setTitle("🅣 Plantillas de título")
        m.addMenu(tm)
        act(m, "🟦 Añadir color sólido o degradado…", None, lambda: self.open_generator())
        act(m, "🎨 Añadir capa de ajuste (color y efectos a todo lo de debajo)", None, self.add_adjustment)
        act(m, "🎯 Seguimiento del clip elegido…", None,
            lambda: self.timeline.selected and self.open_tracking(sorted(self.timeline.selected)[0]))
        act(m, "📌 Pegar el clip elegido a un objeto seguido…", None,
            lambda: self.timeline.selected and self.timeline._pegar(sorted(self.timeline.selected)[0]))
        self._act_fila_kw = act(m, "Fila ⚡ de material por palabra clave", None,
                                lambda on=None: self.timeline.poner_fila_kw(self._act_fila_kw.isChecked()),
                                "Un chip por palabra clave en la regla con el material de su carpeta (gameplay o "
                                "cinemática). Lo mismo que «Dijiste…» → Material")
        self._act_fila_kw.setCheckable(True)
        self._act_fila_kw.setChecked(self.timeline.kw_visible)
        self.timeline.kw_fila_changed.connect(lambda on: (self._act_fila_kw.blockSignals(True),
                                                          self._act_fila_kw.setChecked(on),
                                                          self._act_fila_kw.blockSignals(False)))
        self.menu_clip_elegido = m.addMenu("Clip elegido")     # 🖱 = el clic derecho del clip elegido, aquí arriba
        self.menu_clip_elegido.setToolTipsVisible(True)
        self.menu_clip_elegido.aboutToShow.connect(self._llenar_menu_clip_elegido)
        act(m, "Acercar", "+", lambda: self.timeline.zoom(1.5))
        act(m, "Alejar", "-", lambda: self.timeline.zoom(1 / 1.5))
        act(m, "Detalle (10 s alrededor del cabezal)", None, self.timeline.detalle,
            "Otra vez = el zoom de antes")
        a_res = act(m, "Barra resumen de todo el video", None, lambda: None,
                    "Una franja fina encima de la línea de tiempo con todo el video: clic = ver ese momento")
        a_res.setCheckable(True)
        a_res.setChecked(self.resumen.encendida())
        a_res.toggled.connect(self.resumen.poner_visible)
        a_fit = act(m, "Ajustar a la ventana", "Ctrl+0", self.timeline.fit)
        if a_fit is not None and "Shift+Z" not in [k.toString() for k in a_fit.shortcuts()] and \
                extra_permitido(next(k for k, (a, _d) in self.shortcut_actions.items() if a is a_fit), "Shift+Z"):
            a_fit.setShortcuts(list(a_fit.shortcuts()) + [QKeySequence("Shift+Z")])   # 🔍 Mayús+Z, como en Resolve
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
        self._fill_gaps_menu(gm, lambda t, f: act(gm, t, None, f))   # (lo mismo que el botón «⇤ Huecos» del visor)
        m.addSeparator()
        act(m, "🔒 Bloquear toda la timeline", None, lambda: self.ctrl.lock_all_tracks(True))
        act(m, "🔓 Desbloquear toda la timeline", None, lambda: self.ctrl.lock_all_tracks(False))

        m = mb.addMenu("&Ventana")
        self._menu_ventana = m                      # (TODOS los paneles, también los que se crean después: ✂ Cortes)
        self._sep_ventana = m.addSeparator()
        self._llenar_menu_ventana()
        m.aboutToShow.connect(self._llenar_menu_ventana)
        act(m, "Restablecer la distribución de paneles", None, self.reset_layout)
        self._act_alto = act(m, "◧ Paneles de la izquierda a todo el alto", None, lambda: None,
                             "Los paneles de la izquierda llegan hasta abajo y la línea de tiempo empieza a su derecha, "
                             "como en DaVinci (apagado: la línea de tiempo a todo el ancho de abajo)")
        self._act_alto.setCheckable(True)
        self._act_alto.setChecked(self.biblioteca_alto())
        self._act_alto.toggled.connect(self.set_biblioteca_alto)
        m.addSeparator()
        act(m, "🔠 Tamaño de letra…", "Ctrl+Alt+=", self.open_font_size)
        self._ui_scale_menu(m)
        self._tema_menu(m)
        acm = m.addMenu("🎨 Color de acento")
        acm.setToolTipsVisible(True)
        self._llenar_acentos(acm)
        act(m, "⌨ Personalizar atajos de teclado…", None, self.open_shortcuts)

        m = mb.addMenu("&Convertir")
        act(m, "🔁 Convertir videos y audios…", "Ctrl+Alt+C", lambda: self.open_convert("mp4"))
        act(m, "🎬 A MP4 (video)…", None, lambda: self.open_convert("mp4"))
        act(m, "🎵 A MP3 (solo audio)…", None, lambda: self.open_convert("mp3"))

        m = mb.addMenu("Ay&uda")
        act(m, "📖 Guía paso a paso", "F1", lambda: self.open_guide())
        act(m, "Guía de primer uso", None, self.abrir_guia_primer_uso,
            "Un recorrido corto por lo de siempre: importar, transcribir, limpiar, recortar, palabras clave y "
            "exportar. Se salta cuando quieras y todo vuelve a como estaba.")
        act(m, "🎓 Proyecto de ejemplo", None, self.open_example,
            "Abre un proyecto genérico de YouTube para aprender sin usar tu material: una narración de prueba, "
            "música propia y clips libres de Pexels (se descargan la primera vez, con sus créditos). "
            "La guía te lleva paso a paso.")
        act(m, "Atajos de teclado", "Ctrl+F1", self._show_shortcuts)
        act(m, "⌨ Personalizar atajos…", None, self.open_shortcuts)
        act(m, "✧ Caché y diagnóstico…", None, self.open_diagnostics)
        act(m, "◈ Motor de IA (tarjeta gráfica)…", None, self.open_motor)
        act(m, "👋 Bienvenida y componentes…", None, self.open_bienvenida,
            "Lo que viene incluido y lo opcional (como el motor de IA), con su tamaño y un botón para instalarlo.")
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

        self.act_guiado = QAction("🧭 Montaje guiado", self)
        self.act_guiado.setToolTip("Los pasos de un montaje, uno a uno (antes, una página de abajo)")
        self.act_guiado.triggered.connect(lambda: self.go_page("guided"))
        mb.addAction(self.act_guiado)
        m = mb.addMenu("🔄 &Reinicio")
        act(m, "🔄 Reinicio de proyecto (empezar de cero)…", None, self.reset_project,
            "Vacía la línea de tiempo, Medios, subtítulos y marcadores de esta pestaña para empezar de cero. Antes se "
            "guarda una copia de seguridad; tus archivos no se tocan.")
        m.addSeparator()                           # ↪ ¿lo empezaste en la pestaña equivocada? llévalo a la buena
        self._tab_move_acts = {}
        from .workspaces import TABS as _TABS
        for _k, _t in _TABS:
            self._tab_move_acts[_k] = act(
                m, f"↪ Cambiar este proyecto a {_t.replace('  ', ' ')}…", None,
                lambda _=False, k=_k: self.change_project_tab(k),
                "Lo lleva a esa pestaña con su formato (Video horizontal 16:9; Edits y Vertical 9:16) y lo QUITA de esta, que queda "
                "vacía (así no se carga dos veces). Ctrl+Z devuelve el formato anterior.")
        m.aboutToShow.connect(lambda: [a.setEnabled(k != self.workspaces.current)
                                       for k, a in self._tab_move_acts.items()])

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
        viejo = getattr(self, "_silence_dialog", None)
        try:
            if viejo is not None and viejo.isVisible():
                viejo.close()                         # (una sola a la vez: la nueva, con lo seleccionado ahora)
        except RuntimeError:
            pass
        # Sin bloquear: con la ventana abierta te mueves y escuchas en la línea de tiempo para comprobar los cortes
        self._silence_dialog = SilenceDialog(self, ids)
        self._silence_dialog.setModal(False)
        self._silence_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._silence_dialog.show()

    def _fill_gaps_menu(self, m, add=None):
        """⇤ Las opciones de huecos (las mismas en el botón del visor y en el menú Timeline).
        add(texto, función): cómo se crean (en el menú Timeline, con act(): atajos personalizables)."""
        m.clear()
        add = add or (lambda t, f: m.addAction(t, f))
        m.addAction("⇤ Juntar (Ctrl++): la pista elegida, o todo si no hay ninguna", self._join_right)
        m.addSeparator()
        add("🔊 En todas las pistas de audio", lambda: self.ctrl.close_gaps_on("audio"))
        add("🎞 En todas las pistas de video", lambda: self.ctrl.close_gaps_on("video"))
        add("En todas las pistas", lambda: self.ctrl.close_gaps_on(None))
        m.addSeparator()
        add("Solo en la pista del clip seleccionado", self._close_gaps_selected_track)

    def _gaps_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        self._fill_gaps_menu(m)
        b = self.preview.quick["gaps"]
        m.exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _toggle_snap(self):
        """N: imán sí/no. A mitad de un arrastre, solo para ese arrastre (como en DaVinci Resolve)."""
        if self.timeline.dragging():
            self.timeline.snap_temp_toggle()
            return
        self.tool_snap.toggle()
        self.timeline.set_snapping(self.tool_snap.isChecked())

    def _join_right(self):
        """⇤ Ctrl++ (el atajo del usuario en Resolve): todo se pega hacia la IZQUIERDA, sin espacios vacíos, en los
        canales seleccionados (clic en un clip, en su pista o en la cabecera); sin canal, en toda la línea de tiempo.
        Lo vinculado de otras pistas (su imagen o su sonido) se mueve igual: nada se desincroniza. Un solo Ctrl+Z."""
        tl, p = self.timeline, self.ctrl.project
        chans = tl.channel_ids()
        micro = False
        if chans:          # (al hacer clic en un clip se elige su pista: si ahí no hay nada que juntar, se cierran los
            n = self.ctrl.close_gaps_on(None, track_ids=chans, quiet=True)      # huequitos de las demás; antes «nada»)
            if not n and not any(p.track(t) is not None and p.track(t).locked for t in chans):
                fr = 1.0 / max(1.0, float(p.fps or 30))
                n = self.ctrl.close_gaps_on(None, quiet=True, max_gap=2 * fr + 1e-6)
                micro = True
                if not n:
                    self.statusBar().showMessage(
                        "⇤ En la pista elegida no hay huecos, ni huequitos en las demás. Para juntar TODA la línea de "
                        "tiempo: clic en una zona vacía (sin pista elegida) y Ctrl++.", 8000)
                    return
        else:
            n = self.ctrl.close_gaps_on(None)
        if n and micro:
            tl.gap = None
            self.statusBar().showMessage(f"⇤ En la pista elegida no había huecos: cerré {n} huequito(s) o solape(s) "
                                         "diminutos de las demás pistas · Ctrl+Z lo deshace", 8000)
            return
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
        self._copia_externa = False                  # (Ctrl+V pegará estos clips, no lo del portapapeles de Windows)
        self.statusBar().showMessage(f"{'✂ Cortados' if cut else '⧉ Copiados'} {n} clips. Ctrl+V los pega en el "
                                     "cabezal · Alt+V pega sus ajustes en otros clips.", 6000)

    def _paste(self):
        if self._pegar_de_fuera():                   # 🖼 lo último copiado fue una imagen o un archivo de fuera
            return
        try:
            created = self.ctrl.paste_clips(self.engine.time)
        except Exception as exc:  # noqa: BLE001 - EditError (p. ej. no hay nada copiado)
            self.statusBar().showMessage(str(exc) or "No hay nada copiado: elige clips y pulsa Ctrl+C antes.", 6000)
            return
        if isinstance(created, list):
            self.timeline.set_selection(created)

    # ------------------------------------------------------------ 🖼 pegar imágenes copiadas fuera
    def _al_cambiar_portapapeles(self):
        self._copia_externa = True

    def _pegar_de_fuera(self) -> bool:
        """Ctrl+V con una imagen (o archivos, o la dirección de una imagen) copiada FUERA de Reclaimer después de
        tu último Ctrl+C de clips: se guarda, se importa a Medios y se pone en el cabezal. True si lo hizo."""
        from PySide6.QtCore import QUrl
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md is None:
            return False
        hay_clips = bool(getattr(self.ctrl, "_clipboard", None) or getattr(self.ctrl, "clipboard", None))
        if hay_clips and not getattr(self, "_copia_externa", False):
            return False
        pegar = getattr(getattr(self, "descargas_web", None), "pegar_portapapeles", None)
        if pegar is not None and pegar(md, self.engine.time):    # (22/11: lo copiado en Descargas, con su sonido)
            return True
        rutas = [u.toLocalFile() for u in (md.urls() if md.hasUrls() else []) if u.isLocalFile()]
        rutas = [r for r in rutas if os.path.isfile(r)]
        if rutas:
            from ..core.model import kind_for_path
            rutas = [r for r in rutas if kind_for_path(r)]
            if rutas:
                self._poner_pegado(rutas)
                return True
        if md.hasImage():
            img = cb.image()
            if not img.isNull():
                ruta = self._ruta_pegado(".png")
                if img.save(ruta, "PNG"):
                    self._poner_pegado([ruta])
                    return True
        texto = (md.text() if md.hasText() else "").strip()
        if texto.lower().startswith(("http://", "https://")) and not any(c.isspace() for c in texto) and \
                QUrl(texto).path().lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
            self._bajar_imagen_pegada(texto)
            return True
        return False

    def _ruta_pegado(self, ext: str) -> str:
        """Dónde se guarda lo pegado: junto al proyecto («Imágenes pegadas»); sin proyecto guardado, en los datos."""
        import time
        from ..core.paths import app_data_dir
        base = os.path.dirname(self.ctrl.path) if self.ctrl.path else str(app_data_dir())
        carpeta = os.path.join(base, "Imágenes pegadas")
        os.makedirs(carpeta, exist_ok=True)
        nombre = time.strftime("Pegada %Y-%m-%d %H-%M-%S")
        ruta, n = os.path.join(carpeta, nombre + ext), 2
        while os.path.exists(ruta):
            ruta, n = os.path.join(carpeta, f"{nombre} ({n}){ext}"), n + 1
        return ruta

    def _poner_pegado(self, rutas: list[str]):
        ids = [i for i in (self.ctrl.import_now(rutas) or []) if i]
        if not ids:
            self.statusBar().showMessage("No pude pegar eso en la línea de tiempo.", 6000)
            return
        created = self.ctrl.add_media(ids, None, self.engine.time)
        if isinstance(created, list) and created:
            self.timeline.set_selection(created)
        nombre = os.path.basename(rutas[0]) if len(rutas) == 1 else f"{len(rutas)} archivos"
        self.statusBar().showMessage(f"🖼 Pegado «{nombre}» en el cabezal (también está en Medios). Ctrl+Z lo quita.",
                                     8000)

    def _bajar_imagen_pegada(self, url: str):
        from .jobs import BackgroundJob
        ext = os.path.splitext(url.split("?")[0])[1].lower() or ".png"
        ruta = self._ruta_pegado(ext if len(ext) <= 5 else ".png")

        def bajar(_p, _c):
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                datos = r.read(50 * 1024 * 1024)
            with open(ruta, "wb") as f:
                f.write(datos)
            return ruta

        job = BackgroundJob(bajar, self)
        job.done.connect(lambda r: self._poner_pegado([r]))
        job.failed.connect(lambda m: self.statusBar().showMessage(f"No pude bajar la imagen copiada: {m[:120]}", 8000))
        self._job_pegado = job
        self.statusBar().showMessage("🖼 Bajando la imagen copiada…", 4000)
        job.start()

    # ------------------------------------------------------------ clic derecho como en Resolve
    def _sel_or_msg(self, what: str = "Selecciona antes los clips.") -> list[str]:
        sel = sorted(self.timeline.selected)
        if not sel:
            self.statusBar().showMessage(what, 5000)
        return sel

    def _paste_insert(self):
        try:
            created = self.ctrl.paste_insert(self.engine.time)
        except Exception as exc:  # noqa: BLE001 - EditError (p. ej. no hay nada copiado)
            self.statusBar().showMessage(str(exc) or "No hay nada copiado: elige clips y pulsa Ctrl+C antes.", 6000)
            return
        if isinstance(created, list):
            self.timeline.set_selection(created)

    def _cut_ripple(self):
        sel = self._sel_or_msg("Selecciona los clips que quieres cortar.")
        if sel:
            self.ctrl.copy_clips(sel)
            self._copia_externa = False                       # (Ctrl+V pegará estos clips)
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
                                       "lenta, 200 = el doble de rápido):", round(max(10.0, c.speed * 100), 1),
                                       10.0, 400.0, 1)
        if ok:
            ripple = getattr(getattr(self.inspector, "ripple_speed", None), "isChecked", lambda: True)()
            self.ctrl.set_speed(sel, speed=v / 100, ripple=ripple)

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
        if self.inspector.speed_sec.isHidden():          # (oculta a propósito = imagen)
            self.ctrl.message.emit("🐢 La velocidad es para videos y audios (no para imágenes).")
            return
        # 🧭 su pestaña (Video o Audio, donde viva ahora), su sección abierta, a la vista y con el foco en la velocidad
        self.abrir_para_usar(self.inspector.speed, self.inspector.speed, True)

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

    def open_image_anim(self, media_id: str | None = None):
        """🎞 «Animar imagen» (ui/image_anim_dialog.py)."""
        from . import image_anim_dialog
        self._image_anim_dlg = image_anim_dialog.abrir(self, media_id)

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
        self._tl_set(self.view_comp, f"⊞ Pistas de composición ({n})" if n else "⊞ Pistas de composición", "⊞")
        for b_ in (self.view_main, self.view_comp):
            b_.setVisible(has)
        mode = tl.view_mode()
        self.view_main.setChecked(mode == "main")
        self.view_comp.setChecked(mode == "comp")

    def _comp_drop(self, ids, box):
        """⊞ Archivos soltados en un hueco (o en el fondo) de la composición, desde el cabezal. box = una caja (o None
        = fondo) o una lista, una por archivo (varios a la vez llenan los huecos en orden; core/composicion.py)."""
        from ..core import composicion
        cajas = composicion.caja_por_id(ids, box)
        made = composicion.colocar(self.ctrl, list(zip(ids, cajas)), self.engine.time)
        fuera, self.preview.canvas.comp_fuera = getattr(self.preview.canvas, "comp_fuera", 0), 0   # (siempre a 0)
        if made:
            self.timeline.set_view("comp")             # se ve en su propia línea de tiempo
            self.timeline.set_selection(made)
            n, voz = sum(1 for c in cajas if c is not None), composicion.con_sonido(self.ctrl, made)
            self.statusBar().showMessage(
                "⊞ Puesto en la composición" + (f" ({n} a la vez)" if n > 1 else "") +
                (" (de fondo)" if n == 0 else "") +
                (f" · {fuera} no cupieron: elige más huecos en ⊞ Composición" if fuera else "") +
                (f" · suenan {voz}: silencia los que sobren en su pista" if voz > 1 else "") +
                " · Ctrl+rueda acerca · Ctrl+Z lo quita.", 10000)

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

    def _trim_playhead(self, edge: str):
        """Q / W: recorta hasta el cabezal y cierra el hueco (ver ctrl.trim_to_playhead)."""
        tl, p = self.timeline, self.ctrl.project
        sel = [i for i in sorted(tl.selected) if i in p.clips]
        nt = self.ctrl.trim_to_playhead(self.engine.time, edge, sel, tl.channel_ids(), ref_track=tl.main_track_id())
        if nt is not None:
            self.engine.user_seek(nt)
            tl.set_playhead(nt, follow=True)

    def _cambiar_fundidos(self, on: bool):
        """〰 «Fundidos automáticos» (Limpieza y mezcla → 4 · Cortes de audio): se recuerda y se aplica al momento a todo
        el proyecto. Es una preferencia, no un paso de deshacer (Ctrl+Z no la cambia: ver ctrl.set_fundidos_auto)."""
        self.settings.setValue("audio/fundidos_auto", "true" if on else "false")
        self.ctrl.set_fundidos_auto(on)

    def _nudge_frames(self, frames: int):
        """«,» / «.»: el clip elegido (con su pareja vinculada, si la selección va vinculada) se mueve 1 fotograma."""
        tl = self.timeline
        sel = self._sel_or_msg("Elige antes el clip que quieres mover (clic en él).")
        if sel:
            self.ctrl.nudge_clips(tl._with_links(sel), frames)

    def _llenar_menu_clip_elegido(self):
        """Timeline → «Clip elegido ▸»: las mismas opciones que el clic derecho en el clip elegido (lo que allí va en
        «Más ▸», aquí también), para que ninguna viva solo en el clic derecho."""
        sub = self.menu_clip_elegido
        sub.clear()
        viejo = getattr(self, "_menu_clip_armado", None)
        if viejo is not None:
            viejo.deleteLater()
        self._menu_clip_armado = None
        tl, p = self.timeline, self.ctrl.project
        sel = [i for i in sorted(tl.selected) if i in p.clips]
        if not sel:
            sub.addAction("Elige antes un clip en la línea de tiempo").setEnabled(False)
            return
        ancla = getattr(tl, "_clip_ancla", None)            # (el que pulsaste; si no, el primero de video)
        cid = ancla if ancla in sel else min(sel, key=lambda i: (p.track(p.clips[i].track_id).kind == TRACK_AUDIO,
                                                                 p.clips[i].start))
        clip = p.clips[cid]
        armado = tl.build_clip_menu(clip, tl.mapToGlobal(tl.clip_rect(clip).center().toPoint()))
        self._menu_clip_armado = armado
        for a in armado.actions():
            sub.addAction(a)

    def _go_edit(self, step: int):
        """↑ / ↓: el cabezal al corte anterior / siguiente (inicio o final de clip; en los canales elegidos, si hay)."""
        tl, t = self.timeline, self.engine.time
        medio = 0.5 / max(1.0, float(self.ctrl.project.fps or 30))
        pts = self.ctrl.edit_points(tl.channel_ids() or None)
        if step > 0:
            cand = [x for x in pts if x > t + medio]
            nt = cand[0] if cand else None
        else:
            cand = [x for x in [0.0] + pts if x < t - medio]
            nt = cand[-1] if cand else None
        if nt is None:
            self.statusBar().showMessage("No hay más cortes " + ("después" if step > 0 else "antes") + " del cabezal.",
                                         3000)
            return
        self.engine.user_seek(nt)
        tl.set_playhead(nt, follow=True)

    def _select_from_playhead(self, forward: bool):
        """Y / Alt+Y: elige los clips que pasan por el cabezal y los de delante (Y) o los de detrás (Alt+Y); en los
        canales elegidos si hay, si no en todas las pistas que se ven."""
        tl, p, t = self.timeline, self.ctrl.project, self.engine.time
        eps = 1e-6
        tids = set(tl.channel_ids()) or {tr.id for k, tr in enumerate(p.tracks) if tl.track_h(k) > 0}
        ids = [c.id for c in p.clips.values() if c.track_id in tids and (c.end > t + eps if forward else c.start < t - eps)]
        tl.set_selection(ids)
        self.statusBar().showMessage(f"{len(ids)} clip(s) elegidos desde el cabezal hacia " +
                                     ("delante." if forward else "atrás."), 4000)

    def _delete(self, ripple: bool):
        if self.timeline.delete_transition():                           # transición seleccionada
            return
        if self.timeline.delete_fx():                                   # ✦ pastilla «fx» seleccionada
            return
        if not self.timeline.selected and self.timeline.delete_gap():   # hueco seleccionado
            return
        if self.timeline.selected:
            sel = sorted(self.timeline.selected)
            main = self.timeline.main_track_id()
            if not ripple and self.timeline.magnetic_main and any(
                    c in self.ctrl.project.clips and self.ctrl.project.clips[c].track_id == main for c in sel):
                self.ctrl.magnetic_delete(sel, main)        # 🧲 junta TODAS las pistas (o deja el hueco y avisa)
                return
            self.ctrl.delete_clips(sel, ripple=ripple)
            return
        self.statusBar().showMessage("Nada elegido: haz clic en un clip (o en un hueco) y pulsa Supr.", 5000)

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
        ids = self._sel_or_msg("Elige los clips que quieres bloquear o desbloquear (Ctrl+L).")
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
        """🗣 Buscar lo que se dice en el audio (ligero). (No confundir con 🔑 Palabras clave = tus carpetas.)"""
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

    def open_voz_ia(self):
        """🗣 «Voz y texto» → 5 · Voz IA a la vista (y se queda en esta pestaña de trabajo), con el cursor en el guion."""
        if self.abrir_seccion("voz_texto", "voz_ia") is None:
            return
        self._remember_tab_panel("voz_texto", True)
        QTimer.singleShot(0, self.voz_ia.texto.setFocus)

    def open_subtitles(self):
        """💬 «Voz y texto» → 3 · Subtítulos a la vista (y se queda en esta pestaña de trabajo)."""
        if self.abrir_seccion("voz_texto", "subtitulos") is None:
            return
        self._remember_tab_panel("voz_texto", True)

    def _acceso_voz_ia_en_transcribir(self):
        """🗣 «Que lo lea la IA» en la pestaña «🎙 Transcribir» del panel IA (debajo del estado de la transcripción)."""
        st = getattr(self.ai_panel, "tr_status", None)
        lay = st.parentWidget().layout() if st is not None and st.parentWidget() is not None else None
        if lay is None:
            return
        from . import diseno as _Dv    # (21/11: con aspecto de botón e icono monocromo; antes parecían etiquetas)
        b = QPushButton("Que lo lea la IA")
        b.setIcon(_Dv.icono("audio-waveform"))
        _Dv.alto_fijo(b)
        b.setToolTip("Que lo lea la IA: ¿no quieres hablar? Pega tu guion y una voz sintética lo lee. Sale ya "
                     "transcrito: subtítulos y palabras clave al momento, sin esperar a Whisper.")
        b.clicked.connect(lambda: self.open_voz_ia())
        lay.insertWidget(lay.indexOf(st) + 1, b)
        self._btn_voz_ia_tr = b
        # 🎙 la otra forma de tener narración: grabarla tú mientras ves el video (lo mismo que Voz → Ctrl+Mayús+R)
        g = QPushButton("Grabar la narración…")
        g.setIcon(_Dv.icono("mic"))
        _Dv.alto_fijo(g)
        g.setToolTip("Grabar la narración… (voz en off): grabas tu voz mientras ves el video; la toma cae en la pista "
                     "de voz, en el cabezal (Ctrl+Mayús+R, también en el menú Voz).")
        g.clicked.connect(lambda: self.open_voice_record())
        lay.insertWidget(lay.indexOf(b) + 1, g)
        self._btn_grabar_tr = g

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
        elif key == "audio":                         # 🔊 Audio inteligente: «Audio» → 2 · Mezcla y música
            self.abrir_seccion("audio", "mezcla")
        elif key == "edit":
            self.open_edit_maker()
        elif key == "audit":
            self.open_quick_review()                 # ✓ la revisión guiada (la lista entera, desde ella o Ctrl+R)

    def open_thumbnail(self, fmt: str | None = None):
        """🖼 La página «Miniatura» (como las páginas de Resolve): el taller ocupa toda la ventana, en lugar de los
        paneles del editor (el usuario: «que no sea una ventanilla… una página normal dentro del editor»). Al volver
        a otra página (o ed.close()), todo queda como estaba y la miniatura se guarda con el proyecto."""
        from PySide6.QtGui import QAction, QShortcut
        from .thumbnail_editor import ThumbnailEditor
        if getattr(self, "_scenes_state", None) is not None:      # (desde 🎬 Escenas: primero se sale de ahí)
            pg = getattr(self, "_scenes_widget", None)
            if pg is not None and not pg.volver("thumb"):
                return None
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
        self.btn_export_thumb.setVisible(True)
        QTimer.singleShot(0, self._barras_sueltas_fuera)     # (ninguna barra de pestañas de otra página)
        for k, b in self.page_buttons.items():
            b.setChecked(k == "thumb")
        return ed

    def open_scenes(self, escena_id: str | None = None, rango: tuple[float, float] | None = None):
        """🎬 La página «Escenas» (ocupa la ventana como 🖼 Miniatura; al volver, el editor queda tal cual).
        escena_id = abrir esa escena · rango = una nueva en ese tramo · nada = la que estaba abierta, o una nueva en el
        tramo marcado (I/O) o en el cabezal."""
        from PySide6.QtGui import QAction, QShortcut

        from ..core import scenes as SC
        from .scenes_page import ScenesPage
        if self._thumb_page is not None and getattr(self, "_thumb_editor", None) is not None:
            self._thumb_editor.close()
        self.engine.pause()
        esc, aviso = None, ""
        if escena_id and escena_id in self.ctrl.project.scenes:
            esc, aviso = self.ctrl.scene_state(escena_id)     # (recolocada donde están ahora sus clips)
        elif rango is not None:
            esc = SC.nueva(rango[0], rango[1], f"Escena {len(self.ctrl.project.scenes) + 1}")
        pg = getattr(self, "_scenes_widget", None)
        if pg is not None and esc is not None and pg.escena.get("id") != esc["id"]:
            if pg.sucia and pg._tiene_contenido() and not pg._descartar_ok():
                return pg
            self.central_stack.removeWidget(pg)
            pg.deleteLater()
            pg = None
        if pg is None:
            pg = self._scenes_widget = ScenesPage(self, esc, aviso)
            pg.closed.connect(self._leave_scenes_page)
            self.central_stack.addWidget(pg)
            if esc is not None and escena_id is None:
                pg._ensuciar()
        if getattr(self, "_scenes_state", None) is None:
            acts = [a for a in self.findChildren(QAction) if a.shortcuts() and not self._in_widget(a, pg)]
            shorts = [s for s in self.findChildren(QShortcut) if s.isEnabled() and not self._in_widget(s, pg)]
            self._scenes_state = {"state": self.saveState(3), "acts": [(a, a.shortcutContext()) for a in acts],
                                  "shorts": shorts}
            for key, d in self.docks.items():
                if key != "guide" and not d.isFloating():
                    d.hide()
            for a in acts:
                a.setShortcutContext(Qt.WidgetShortcut)
            for s in shorts:
                s.setEnabled(False)
        self.central_stack.setCurrentWidget(pg)
        pg.show()
        pg.setFocus()
        for k, b in self.page_buttons.items():
            b.setChecked(k == "scenes")
        QTimer.singleShot(0, self._barras_sueltas_fuera)     # (ninguna barra de pestañas de otra página)
        return pg

    def put_template(self, archivo: str, t: float):
        """📚 Pone una animación guardada en el segundo t (desde el clic derecho de una palabra clave)."""
        from ..core import scenes as SC
        tp = next((x for x in SC.plantillas() if x.get("archivo") == archivo), None)
        if tp is None:
            self.statusBar().showMessage("Esa animación ya no está en «📚 Mis animaciones».", 6000)
            return None
        esc, faltan = SC.desde_plantilla(tp, t, self.ctrl.media_for_path)
        if not esc["actores"] and not esc["sonidos"]:
            self.statusBar().showMessage("No se encuentran los archivos de esa animación.", 8000)
            return None
        ids = self.ctrl.apply_scene(esc)
        if ids:
            self.timeline.set_selection(ids)
            msg = f"🎬 «{tp.get('nombre')}» puesta en {t:.1f} s."
            if faltan:
                msg += f" Faltan {len(faltan)} archivos (no se pusieron)."
            self.statusBar().showMessage(msg, 8000)
        return ids

    @staticmethod
    def _in_widget(obj, w) -> bool:
        o = obj
        while o is not None:
            if o is w:
                return True
            o = o.parent()
        return False

    def _leave_scenes_page(self, back_to: str = "edit"):
        """Salir de 🎬 Escenas: el editor vuelve tal cual (paneles, atajos). La página se cierra (lo aplicado ya está
        en el proyecto)."""
        st, self._scenes_state = getattr(self, "_scenes_state", None), None
        pg = getattr(self, "_scenes_widget", None)
        resaltar = getattr(pg, "resaltar", None) if pg is not None else None
        self.central_stack.setCurrentWidget(self.preview)
        if pg is not None:
            self.central_stack.removeWidget(pg)
            pg.deleteLater()
            self._scenes_widget = None
        if st is not None:
            self._restaurar_paneles(st["state"])
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
        if resaltar:                                   # 🎬 lo que se acaba de aplicar: el editor va ahí y lo resalta
            ids, t = resaltar
            self.engine.user_seek(t)
            self.timeline.set_playhead(t, follow=True)
            self.timeline.flash_clips(ids)
        QTimer.singleShot(0, self.timeline.setFocus)          # (las teclas, al editor)

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
        self.btn_export_thumb.setVisible(False)
        self.central_stack.setCurrentWidget(self.preview)
        if ed is not None:
            ed._gone = True
            self.central_stack.removeWidget(ed)
            ed.deleteLater()
            self._thumb_editor = None
        if st is not None:
            self._restaurar_paneles(st["state"])
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
        QTimer.singleShot(0, self.timeline.setFocus)          # (las teclas, al editor; no al nombre del proyecto)

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
        from .responsive import widgets_en               # (sin itemAt: ver responsive.py)
        tb = widgets_en(self.timeline_box.layout())[0].sizeHint().height()
        return int(title + tb + self.timeline.track_y(n) + self.timeline.NEW_ZONE + 8 + self.hbar.sizeHint().height())

    # (el lado de entrada de cada panel: los de la izquierda; el resto, a la derecha)
    LADO_IZQ = ("media", "effects", "ai", "moments", "descargas_web", "memes", "voz_texto", "edit_clips", "audio_mix",
                "sounds",
                "fx_trans", "fx_efectos",
                "fx_filtros", "fx_figuras")

    def _paneles_a_su_sitio(self, solo=None) -> list[str]:
        """Un panel principal (Inspector, Medios…) que quedó SUELTO encima de la ventana principal —o fuera de toda
        pantalla— vuelve acoplado a su lado de entrada (el usuario: el Inspector salía como ventana suelta «Inspector -
        Reclaimer» encima del visor, con un hueco negro donde debía estar). Y uno que una distribución vieja dejó arriba
        o abajo (ahora solo se acomodan a los lados) pasa a su lado. Al abrir y al pulsar su interruptor. La 📖 guía
        flota a propósito: no se toca.
        (20/11) Y un panel con interruptor acoplado en el lado CONTRARIO al de su interruptor vuelve a su lado (el
        usuario abrió «Inspector» —interruptor de la derecha— y salió a la izquierda, debajo de «Transiciones y
        efectos», con todo el lado derecho vacío): una distribución vieja incoherente se corrige sola al abrir."""
        from PySide6.QtGui import QGuiApplication
        movidos = []
        try:
            marco = self.frameGeometry()
            pantallas = [s.availableGeometry() for s in QGuiApplication.screens()]
        except RuntimeError:
            return movidos
        for k, d in self.docks.items():
            if k in ("timeline", "guide") or (solo is not None and k not in solo):
                continue
            if d.isFloating():
                g = d.frameGeometry()
                mover = g.intersects(marco) or not any(s.intersects(g) for s in pantallas)
            else:
                mover = self.dockWidgetArea(d) in (Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea) or \
                    self._lado_incoherente(k)
            if not mover:
                continue
            lado = self._area_lado(k)
            ancla = self._ancla_lado(k, lado)
            visible = not d.isHidden()
            d._arrastre_usuario = False                # (lo movemos nosotros: no cambia el lado de su interruptor)
            d.setFloating(False)
            if ancla is not None:
                self.tabifyDockWidget(ancla, d)
            else:
                self.addDockWidget(lado, d)
            d.setVisible(visible)
            if visible:
                d.raise_()
            movidos.append(k)
        if movidos:
            QTimer.singleShot(0, self._barras_sueltas_fuera)
            QTimer.singleShot(0, self._ajustar_paneles)
            QTimer.singleShot(0, self._ensure_side_widths)    # (nunca un panel solo en un lado a 200 px)
        return movidos

    # ------------------------------------------------ ↔ lado y fila coherentes (20/11)
    def _lado_panel(self, k: str) -> str:
        """«izq» o «der»: el lado donde se abre el panel k y la fila donde está su interruptor (siempre el mismo). Lo
        de fábrica: INTERRUPTORES_IZQ / LADO_IZQ a la izquierda y el resto a la derecha; si lo arrastraste al otro
        lado, el que elegiste (QSettings «paneles/lado/<k>»)."""
        v = str(self.settings.value(f"paneles/lado/{k}", "") or "")
        if v in ("izq", "der"):
            return v
        return self._lado_de_fabrica(k)

    def _lado_de_fabrica(self, k: str) -> str:
        return "izq" if k in dict(self.INTERRUPTORES_IZQ) or k in self.LADO_IZQ else "der"

    def _area_lado(self, k: str):
        return Qt.LeftDockWidgetArea if self._lado_panel(k) == "izq" else Qt.RightDockWidgetArea

    def _lado_incoherente(self, k: str) -> bool:
        """¿El panel k (con interruptor) está acoplado en el lado contrario al de su interruptor?"""
        d = self.docks.get(k)
        if d is None or k not in getattr(self, "interruptores", {}) or d.isFloating():
            return False
        zona = self.dockWidgetArea(d)
        return zona in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea) and zona != self._area_lado(k)

    def _ancla_lado(self, k: str, lado):
        """Con quién va en pestaña un panel que vuelve a su lado: Medios o el Inspector si están allí a la vista; si no,
        otro panel a la vista de ese lado con interruptor de ese lado; None = solo en su lado."""
        d = self.docks.get(k)
        inter = getattr(self, "interruptores", {})
        prefer = ["media" if lado == Qt.LeftDockWidgetArea else "inspector"] + [x for x in inter if x != k]
        for x in prefer:
            o = self.docks.get(x)
            if o is None or o is d or o.isFloating() or o.isHidden() or self.dockWidgetArea(o) != lado:
                continue
            if x in inter and self._area_lado(x) != lado:
                continue
            return o
        return None

    def _marcar_arrastre(self, d, suelto: bool):
        """El panel se soltó de su sitio con el botón del ratón pulsado: lo está arrastrando el usuario."""
        if suelto and QApplication.mouseButtons() & Qt.LeftButton:
            d._arrastre_usuario = True

    def _panel_cambio_de_lado(self, k: str, area):
        """Un panel con interruptor se acopló en un lado: si lo llevó el usuario (arrastrándolo) al otro lado, su
        interruptor pasa a la fila de ese lado y se recuerda. Lo que mueve el programa no cambia el lado."""
        d = self.docks.get(k)
        if d is None:
            return
        pulsado = bool(QApplication.mouseButtons() & Qt.LeftButton)
        if area not in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
            if not pulsado:                            # (suelto o quitado por el programa: no es un arrastre)
                d._arrastre_usuario = False
            return
        usuario = bool(getattr(d, "_arrastre_usuario", False)) or pulsado
        d._arrastre_usuario = False
        if usuario:
            self._poner_lado(k, "izq" if area == Qt.LeftDockWidgetArea else "der")
            QTimer.singleShot(0, self._ensure_side_widths)   # (el panel que se queda solo en un lado, con ancho)

    def _poner_lado(self, k: str, lado: str):
        """El panel k se abre desde ahora en ese lado y su interruptor va a la fila de ese lado (se recuerda)."""
        if lado == self._lado_de_fabrica(k):
            self.settings.remove(f"paneles/lado/{k}")
        else:
            self.settings.setValue(f"paneles/lado/{k}", lado)
        self._mover_interruptor(k, lado)

    def _mover_interruptor(self, k: str, lado: str):
        b = getattr(self, "interruptores", {}).get(k)
        filas = getattr(self, "_filas_inter", None)
        if b is None or not filas or b.parentWidget() is filas[lado]:
            return
        orden = [x for x, _n in self.INTERRUPTORES_IZQ + self.INTERRUPTORES_DER]
        destino = filas[lado]
        antes = [x for x in orden[:orden.index(k)] if x in self.interruptores
                 and self.interruptores[x].parentWidget() is destino]
        origen = b.parentWidget()
        if origen is not None and origen.layout() is not None:
            origen.layout().removeWidget(b)
        b.setParent(destino)
        # (en la fila derecha van antes «A todo el alto» y su separación)
        destino.layout().insertWidget(len(antes) + (2 if lado == "der" else 0), b)
        b.setVisible(self._interruptor_util(k))
        QTimer.singleShot(0, self._interruptores_que_caben)

    # ------------------------------------------------ sin huecos: el alto libre, al panel vecino que lo usa (20/11)
    def _revisar_crecer(self):
        """(tabs.avisar_contenido desde un panel que se plegó o abrió, y el repaso tras recolocar paneles) → repartir
        el alto de los paneles apilados en cuanto Qt termine."""
        t = getattr(self, "_t_ceder", None)
        if t is None:
            t = self._t_ceder = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(80)
            t.timeout.connect(self._ceder_alto)
        t.start()

    def _alto_que_pide(self, d) -> int | None:
        """El alto que necesita el panel d para enseñar todo lo suyo; None si aprovecha cualquier alto extra (una
        lista o un texto a la vista: tabs.quiere_crecer)."""
        from .tabs import quiere_crecer
        panel, zona = getattr(d, "panel", None), d.widget()
        if panel is None or zona is None or quiere_crecer(panel):
            return None
        lay = panel.layout()
        ancho = zona.viewport().width() if hasattr(zona, "viewport") else zona.width()
        alto = lay.totalHeightForWidth(ancho) if lay is not None and lay.hasHeightForWidth() else -1
        if alto <= 0:
            alto = max(panel.sizeHint().height(), panel.minimumSizeHint().height())
        return alto + max(0, d.height() - zona.height()) + 2

    def _columnas_lado(self, area) -> list:
        """Los paneles a la vista de un lado, por columnas (cada una de arriba abajo)."""
        docks = [d for k, d in self.docks.items() if k not in ("timeline", "guide") and not d.isHidden()
                 and not d.isFloating() and self.dockWidgetArea(d) == area and not d.visibleRegion().isEmpty()]
        cols: list = []
        for d in sorted(docks, key=lambda x: (x.x(), x.y())):
            for c in cols:
                if abs(c[0].x() - d.x()) <= 6:
                    c.append(d)
                    break
            else:
                cols.append([d])
        return [sorted(c, key=lambda x: x.y()) for c in cols]

    def _ceder_alto(self):
        """↕ Paneles apilados en el mismo lado («Voz y texto» encima de «Limpieza y mezcla»): el que enseña poco
        (secciones plegadas, sin transcripción…) se queda con lo que necesita y el resto va al vecino que lo usa (una
        lista, un texto). Nunca pisa lo que pusiste a mano con el divisor (hasta que cambien los paneles de esa
        columna)."""
        if not self.isVisible() or getattr(self, "_cediendo", False):
            return
        if getattr(self, "_scenes_state", None) is not None or getattr(self, "_thumb_page", None) is not None:
            return
        if not hasattr(self, "_altos_a_mano"):
            self._altos_a_mano = set()
        self._cediendo = True
        try:
            columnas = [c for a in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea) for c in self._columnas_lado(a)]
            firmas = {frozenset(d.objectName() for d in c) for c in columnas}
            self._altos_a_mano &= firmas               # (cambiaron los paneles de una columna: se olvida su marca)
            for area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
                for col in self._columnas_lado(area):
                    self._vigilar_divisor(col)
                    if len(col) < 2 or frozenset(d.objectName() for d in col) in self._altos_a_mano:
                        continue
                    pide = [self._alto_que_pide(d) for d in col]
                    crecen = [d for d, p in zip(col, pide) if p is None]
                    if not crecen or len(crecen) == len(col):
                        continue                       # (todos usan el alto, o ninguno: nada que ceder)
                    total = sum(d.height() for d in col)
                    fijos = {id(d): max(p, d.minimumSizeHint().height()) for d, p in zip(col, pide) if p is not None}
                    resto = total - sum(fijos.values())
                    if resto < 140 * len(crecen):
                        continue                       # (no hay sitio para que el vecino gane nada útil)
                    base = sum(d.height() for d in crecen) or 1
                    nuevos = [fijos[id(d)] if id(d) in fijos else int(resto * d.height() / base) for d in col]
                    if max(abs(n - d.height()) for n, d in zip(nuevos, col)) <= 8:
                        continue
                    self.resizeDocks(col, nuevos, Qt.Vertical)
        finally:
            self._cediendo = False

    def _vigilar_divisor(self, col):
        """Si mueves a mano el divisor entre paneles apilados (un panel cambia de alto con el botón del ratón
        pulsado), esa columna se queda como la dejas."""
        from PySide6.QtCore import QEvent, QObject
        vig = getattr(self, "_vigia_divisor", None)
        if vig is None:
            class _VigiaDivisor(QObject):
                def __init__(self, win):
                    super().__init__(win)
                    self.win = win

                def eventFilter(self, obj, ev):
                    if ev.type() == QEvent.Resize and ev.oldSize().height() != ev.size().height() and \
                            not getattr(self.win, "_cediendo", False) and self.win._boton_pulsado():
                        self.win._alto_puesto_a_mano(obj, ev.oldSize().height())
                    return False
            vig = self._vigia_divisor = _VigiaDivisor(self)
        for d in col:
            if not getattr(d, "_vigilado_divisor", False):
                d._vigilado_divisor = True
                d.installEventFilter(vig)

    TOLERANCIA_A_MANO = 3      # (px que un arrastre tiene que acumular para contar como «puesto a mano»)

    def _boton_pulsado(self) -> bool:
        """¿Está pulsado el botón izquierdo? (aparte para que las pruebas puedan simular un arrastre)"""
        return bool(QApplication.mouseButtons() & Qt.LeftButton)

    def _alto_puesto_a_mano(self, d, alto_antes: int | None = None):
        """Un panel cambió de alto con el botón pulsado (alto_antes = el que tenía justo antes). Cuenta como «puesto a
        mano» SOLO un arrastre real del divisor ENTRE paneles apilados, medido desde que se pulsó el botón (no paso a
        paso): el total de la columna sigue igual (± la tolerancia) y algún panel acumuló más que la tolerancia.
        Arrastrar despacio el divisor de la línea de tiempo (pasos de 2 px) o estirar la ventana cambian el total
        según avanzan: nunca marcan, por lenta que sea."""
        if not hasattr(self, "_altos_a_mano"):
            self._altos_a_mano = set()
        arr = getattr(self, "_arrastre_divisor", None)
        if arr is None:
            arr = self._arrastre_divisor = {}
            t = getattr(self, "_t_suelta_divisor", None)
            if t is None:                              # (al soltar el botón, el arrastre se olvida)
                t = self._t_suelta_divisor = QTimer(self)
                t.setInterval(120)
                t.timeout.connect(self._revisar_suelta_divisor)
            t.start()
        tol = self.TOLERANCIA_A_MANO
        for col in self._columnas_lado(self.dockWidgetArea(d)):
            if d in col and len(col) > 1:
                firma = frozenset(x.objectName() for x in col)
                inicio = arr.setdefault(firma, {})
                # (el alto de cada panel al empezar el arrastre: el de antes de su primer cambio en este arrastre o,
                #  si aún no ha cambiado, el que tiene ahora)
                if d.objectName() not in inicio:
                    inicio[d.objectName()] = alto_antes if alto_antes is not None else d.height()
                base = {x.objectName(): inicio.get(x.objectName(), x.height()) for x in col}
                total_ini = sum(base.values())
                total = sum(x.height() for x in col)
                movido = max(abs(x.height() - base[x.objectName()]) for x in col)
                if abs(total - total_ini) <= tol and movido > tol:
                    self._altos_a_mano.add(firma)

    def _revisar_suelta_divisor(self):
        if not self._boton_pulsado():
            self._fin_arrastre_divisor()

    def _fin_arrastre_divisor(self):
        """Se soltó el botón: el próximo arrastre se mide desde cero."""
        self._arrastre_divisor = None
        t = getattr(self, "_t_suelta_divisor", None)
        if t is not None:
            t.stop()

    def _acoplar_timeline_si_tapa(self) -> bool:
        """Al abrir: si la distribución guardada trae la línea de tiempo SUELTA (flotando: en Windows sale como una ventana
        aparte «Línea de tiempo - Reclaimer», siempre encima de la principal) y cae encima de la ventana, vuelve a su
        sitio abajo. Si no, tapaba la parte de abajo del visor (el lienzo y la barra de ▶) y el visor, sin la línea de
        tiempo debajo, se estiraba hasta abajo del todo por detrás de ella. Una línea de tiempo suelta en OTRA pantalla
        (sin tocar la ventana) se respeta. El resto de la distribución guardada no se toca."""
        d = self.docks.get("timeline")
        if d is None or not (d.isFloating() or d.window() is not self):
            return False
        suelta = d.window().frameGeometry()
        marco = self.frameGeometry()
        if self.windowState() & (Qt.WindowMaximized | Qt.WindowFullScreen) and self.screen() is not None:
            marco = marco.united(self.screen().availableGeometry())   # (al abrir maximizada aún puede dar la normal)
        comun = suelta.intersected(marco)
        area = max(1, suelta.width() * suelta.height())
        en_pantalla = any(s.geometry().contains(suelta.center()) for s in QApplication.screens())
        if en_pantalla and comun.width() * comun.height() < area * 0.1:
            return False
        if d.isFloating():
            d.setFloating(False)
        self.removeDockWidget(d)
        self.addDockWidget(Qt.BottomDockWidgetArea, d)
        d.show()
        self.statusBar().showMessage("La línea de tiempo estaba suelta encima del visor: ha vuelto a su sitio, abajo.",
                                     10000)
        return True

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
        if self.workspaces.current == "edit":          # 🎵 en la pestaña Edits, a pantalla completa (no una ventanita)
            for k in ("edit_opts", "edit_clips"):
                self.docks[k].show()
                self.docks[k].raise_()
            self.statusBar().showMessage("🎵 Elige la canción y el estilo a la derecha y los clips a la izquierda; "
                                         "luego «Crear edit».", 7000)
            return
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
        else:            # 📝 un texto seleccionado (si se ve ahora): su caja, para moverlo y escalarlo en el visor
            ids = list(self.inspector._ids)
            tc = self.ctrl.project.clips.get(ids[0]) if len(ids) == 1 else None
            t = self.engine.time
            tr_ = self.ctrl.project.track(tc.track_id) if tc is not None else None
            if tc is not None and tc.text is not None and tc.enabled and tr_ is not None and not tr_.hidden \
                    and tc.start - 1e-3 <= t < tc.end and not tc.locked and not tr_.locked:
                from ..core import nota_texto as _NT
                c = tc
                lay = _NT.text_box(tc.text, t - tc.start, canvas.W, canvas.H)
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
        if "~" in (track_id or ""):                   # 🎬 pista de una escena desplegada: es su clip de escena
            cid = track_id.split("~")[1]
            return cid if cid in p.clips else None
        c = p.clip_at(track_id, self.engine.time)
        if c is None or not c.enabled or c.text is not None or _G.is_adjust(p.media_of(c)):
            return None
        return c.id

    def _text_at_now(self, fx: float, fy: float) -> str | None:
        """📝 El texto que se ve en ese punto del visor ahora (el de la pista de más arriba), para elegirlo con un clic."""
        from ..core import nota_texto as _NT
        p = self.ctrl.project
        t = self.engine.time
        W, H = self.preview.canvas.W, self.preview.canvas.H
        for tr in p.tracks:                         # (las pistas de texto van arriba: la primera es la de encima)
            if tr.kind != TRACK_TEXT or tr.hidden or tr.locked:
                continue
            c = p.clip_at(tr.id, t)
            if c is None or not c.enabled or c.text is None or c.locked:
                continue
            b = _NT.text_box(c.text, t - c.start, W, H)
            if b["x"] <= fx <= b["x"] + b["w"] and b["y"] <= fy <= b["y"] + b["h"]:
                return c.id
        return None

    def _pick_from_viewer(self, clip_id: str):
        clip_id = self._clip_real(clip_id)
        tl = self.timeline
        tl.set_selection(self.ctrl.linked_ids([clip_id]) if tl.linked else [clip_id])

    def _clip_real(self, clip_id: str) -> str:
        """🎬 Un personaje de una escena desplegada («clip~1») es su clip de escena."""
        base = (clip_id or "").split("~")[0]
        return base if "~" in (clip_id or "") and base in self.ctrl.project.clips else clip_id

    def _tf_live(self, clip_id: str, box: dict):
        if "~" in (clip_id or ""):                    # (una pieza de una escena: se retoca en 🎬 Escenas)
            return
        c = self.ctrl.project.clips.get(clip_id)
        if c is not None and c.text is not None:     # 📝 un texto: x, y y tamaño (provisional hasta soltar)
            orig = (self.preview.canvas._tf or {}).get("orig")
            if orig:
                from ..core import nota_texto as _NT
                t0 = self.__dict__.setdefault("_tf_text0", {}).setdefault(clip_id, dict(c.text))   # (Ctrl+rueda)
                c.text = _NT.text_from_box(t0, orig, box)
                self.engine._sync()
            return
        if c is not None:              # solo para verlo mientras arrastras (se guarda al soltar, con Ctrl+Z)
            if c.layout_kf:            # 🎞 animado: una caja provisional (las claves no se tocan hasta soltar)
                from ..core import transform as _TR
                _TR.LIVE[c.id] = dict(box)
            else:
                c.layout = dict(box)
            self.engine._sync()

    def _tf_started(self, clip_id: str):
        """Empieza un arrastre en el visor: la copia del texto, la de AHORA (nunca la de un arrastre anterior)."""
        c = self.ctrl.project.clips.get(clip_id)
        t0 = self.__dict__.setdefault("_tf_text0", {})
        t0.pop(clip_id, None)
        if c is not None and c.text is not None:
            t0[clip_id] = dict(c.text)

    def _tf_cancel(self, clip_id: str, orig):
        """Soltado sin moverlo: todo como antes, sin paso de deshacer."""
        c = self.ctrl.project.clips.get(clip_id)
        t0 = self.__dict__.setdefault("_tf_text0", {}).pop(clip_id, None)
        if c is None or "~" in (clip_id or ""):
            return
        if c.text is not None:
            if t0 is not None:
                c.text = t0
        else:
            from ..core import transform as _TR
            if _TR.LIVE.pop(clip_id, None) is None and not c.layout_kf:
                c.layout = dict(orig) if orig else None
        self.engine._sync()

    def _tf_done(self, clip_id: str, orig, box):
        if "~" in (clip_id or ""):
            return
        c = self.ctrl.project.clips.get(clip_id)
        if c is None:
            return
        if c.text is not None:         # 📝 un texto: lo movido/escalado en el visor, en UN paso de deshacer
            from ..core import nota_texto as _NT
            t0 = self.__dict__.setdefault("_tf_text0", {}).pop(clip_id, None) or dict(c.text)
            c.text = t0                                # lo de antes, para que Ctrl+Z vuelva ahí
            if orig and box:
                new = _NT.text_from_box(t0, orig, box)
                ch = {k: new[k] for k in ("x", "y", "size", "zoom_x", "zoom_y") if k in new and new[k] != t0.get(k)}
                if ch:
                    self.ctrl.set_text_step(clip_id, "Mover / escalar texto en el visor", **ch)
            self.engine._sync()
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
        """M: un marcador en el cabezal. M otra vez en el mismo sitio (ya hay uno ahí) = escribir su nota (M+M)."""
        from ..core import marcadores_auto as MA
        mk = MA.marcador_en(self.ctrl.project, self.engine.time, self.ctrl.project.fps)
        if mk is not None:
            self._nota_marcador(mk.id)
            return
        self.ctrl.add_marker(self.engine.time)

    def _nota_marcador(self, marker_id: str):
        """📍 M+M: la nota de ese marcador, a la vista y con el foco (sección «Marcadores» del Inspector)."""
        panel = getattr(self, "marcadores_panel", None)
        if panel is None:
            return
        if panel.window() is self:                 # (el índice ya está en el Inspector: se enseña)
            ins = getattr(self, "inspector", None)
            if ins is not None and hasattr(ins, "mostrar_marcadores"):
                ins.mostrar_marcadores()
            else:
                self.show_panel(ins) if ins is not None else None
            panel.editar_nota(marker_id)
            return
        from PySide6.QtWidgets import QInputDialog             # (sin el gancho del Inspector todavía)
        mk = next((x for x in self.ctrl.project.markers if x.id == marker_id), None)
        if mk is None:
            return
        txt, ok = QInputDialog.getText(self, "Nota del marcador", f"Nota de «{mk.label}»:", text=mk.note)
        if ok:
            self.ctrl.update_marker(marker_id, note=txt.strip())

    def _crear_marcas(self):
        try:
            from .marcadores_panel import CapaViva, PanelMarcadores
            from .marcadores_panel import instalar as _instalar_marcas
            self.capa_marcas = CapaViva(self.ctrl, self.timeline, self)
            self.timeline.capa = self.capa_marcas
            self.capa_marcas.cambio.connect(self.timeline.update)
            self.marcadores_panel = PanelMarcadores(self.ctrl, self.capa_marcas, self._ir_a_marca)
            QTimer.singleShot(0, lambda: _instalar_marcas(self))
        except Exception:                       # (si fallara, la ventana arranca igual; se apunta en errores.log)
            try:
                import time as _t
                import traceback as _tb
                from ..core.paths import log_path as _log
                with open(_log(), "a", encoding="utf-8") as _f:
                    _f.write(f"\n[{_t.strftime('%Y-%m-%d %H:%M:%S')}] Marcadores automáticos:\n{_tb.format_exc()}")
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 🔍 zoom y navegación (fase 8)
    def _zoom_desde_deslizador(self, v: int):
        import math
        tl = self.timeline
        tl.poner_pps(tl.PPS_MIN * math.exp(v / 1000 * math.log(tl.PPS_MAX / tl.PPS_MIN)))

    def _sync_zoom_slider(self):
        import math
        tl = self.timeline
        v = int(round(1000 * math.log(max(tl.pps, tl.PPS_MIN) / tl.PPS_MIN) / math.log(tl.PPS_MAX / tl.PPS_MIN)))
        if self.zoom_slider.value() != v:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(v)
            self.zoom_slider.blockSignals(False)

    def _play_alrededor(self, antes: float = 2.0, despues: float = 2.0):
        """«/»: suena de 2 s antes a 2 s después del cabezal y el cabezal vuelve a donde estaba."""
        eng = self.engine
        previo = getattr(self, "_alrededor_t0", None)
        t0 = previo if (previo is not None and eng.playing) else eng.time   # («/» otra vez: el mismo sitio)
        self._alrededor_t0 = t0
        if eng.playing:
            eng.pause()

        def volver(playing: bool, _t=t0):
            if playing:
                return
            try:
                eng.playing_changed.disconnect(volver)
            except (RuntimeError, TypeError):
                pass
            eng.seek(_t)
            self.timeline.set_playhead(_t)
            self._alrededor_t0 = None
        eng.play_ranges([(max(0.0, t0 - antes), t0 + despues)])
        if eng.playing:
            eng.playing_changed.connect(volver)

    def _voz_pareja(self):
        """🎚 Voz pareja: lee el audio de la narración en segundo plano (puede ser largo) y aplica la curva (un Ctrl+Z)."""
        from ..core import voz_pareja as VP
        p = self.ctrl.project
        elegidos = [i for i in self.timeline.selected if i in p.clips] or None
        clips = VP._clips_voz(p, set(elegidos) if elegidos else None)
        if not clips:
            self.statusBar().showMessage("🎚 No hay ninguna narración transcrita en la línea de tiempo (o en lo "
                                         "elegido): transcríbela antes (Voz → Transcribir).", 7000)
            return
        rutas = {c.media_id: p.media[c.media_id].path for c in clips if c.media_id in p.media}

        def work(_progress, _cancelled):
            return {mid: VP.leer(ruta) for mid, ruta in rutas.items()}   # (la pista que suena: la del clip)

        def done(muestras):
            self.statusBar().showMessage(VP.igualar(self.ctrl, elegidos, muestras), 9000)
        from .jobs import BackgroundJob
        job = BackgroundJob(work, self)
        job.title = "🎚 Midiendo cada frase de la narración"
        job.done.connect(done)
        job.failed.connect(lambda msg: self.statusBar().showMessage(f"🎚 No pude leer la narración: {msg}", 7000))
        self._voz_pareja_job = job
        self.statusBar().showMessage("🎚 Midiendo cada frase de la narración…", 4000)
        job.start()

    def _modo_edicion(self, modo: str, t: float | None = None, ids=None):
        """🎬 F9/F10/Mayús+F11/F12/Mayús+F12: lo elegido en Medios, en el cabezal, en el canal elegido (o la pista
        principal). Un Ctrl+Z; los clips nuevos quedan elegidos."""
        ids = list(ids) if ids is not None else self.library.selected_media_ids()
        if not ids:
            self.statusBar().showMessage("Elige antes en 🗂 Medios lo que quieres poner (clic en un archivo).", 6000)
            return None
        p = self.ctrl.project
        m0 = p.media.get(ids[0])
        destino = None
        t_ = self.engine.time if t is None else t
        if m0 is not None:                         # (el primer canal elegido del tipo de ese archivo)
            quiere = self.ctrl.track_kind_for(m0)
            destino = next((tid for tid in self.timeline.channel_ids()
                            if p.track(tid) is not None and p.track(tid).kind == quiere), None)
            if destino is None and modo == "reemplazar":     # (o el clip elegido que pasa por el cabezal)
                elegidos = [p.clips[i] for i in self.timeline.selected if i in p.clips]
                bajo = [c for c in elegidos if c.start - 1e-6 <= t_ < c.end - 1e-6 and p.track(c.track_id) is not None
                        and p.track(c.track_id).kind == quiere]
                destino = bajo[0].track_id if bajo else None
        aviso = ""
        if modo == "reemplazar" and len(ids) > 1:
            aviso = f" Se usó el primero de {len(ids)}."
            ids = ids[:1]
        creados = self.ctrl.edit_mode(ids, modo, t_, destino)
        if isinstance(creados, list) and creados:
            self.timeline.set_selection(creados)
            self.statusBar().showMessage(f"🎬 {self.ctrl.MODOS_EDICION[modo]}: {len(creados)} clip(s). Ctrl+Z lo "
                                         "deshace." + aviso, 6000)
        return creados

    def _ir_a_marca(self, t: float):
        self.engine.user_seek(t)
        self.timeline.set_playhead(t, follow=True)

    def _go_marca(self, step: int):
        """Mayús+↑ / Mayús+↓: el cabezal a la marca anterior / siguiente de la capa (los tipos a la vista)."""
        capa = getattr(self, "capa_marcas", None)
        if capa is None:
            return
        if capa._timer.isActive():                 # (justo tras editar: al día; si no, la lista ya calculada)
            capa._timer.stop()
            capa.recalcular()
        mk = capa.siguiente(self.engine.time, step)
        if mk is None:
            self.statusBar().showMessage("No hay más marcas " + ("después" if step > 0 else "antes") + " del cabezal.",
                                         3000)
            return
        from ..core.marcadores_auto import TIPOS
        self._ir_a_marca(mk.t)
        self.statusBar().showMessage(f"{TIPOS[mk.tipo][0]}: {mk.texto}", 6000)

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
            self._tl_refit()

    def _confirm_discard(self) -> bool:
        """Si hay cambios sin guardar, pregunta. Devuelve False si el usuario cancela."""
        if not self.ctrl.dirty:
            return True
        r = QMessageBox.question(self, "Cambios sin guardar", "¿Guardar los cambios del proyecto actual?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def limpiar_interfaz(self):
        """Proyecto nuevo o reinicio: ningún panel enseña nada del proyecto anterior (Medios, palabras clave,
        internet, Momentos, edit musical, carpetas)."""
        for w, m in ((self.library, "limpiar"), (self.clips, "limpiar"), (self.moments, "limpiar")):
            try:
                getattr(w, m)()
            except Exception:  # noqa: BLE001 - un panel no impide limpiar los demás
                pass
        self._fill_edit_panel()
        try:
            self.ai_panel.plans = []
            self.ai_panel.plan_tree.clear()
            self.ai_panel.director_text.clear()
            self.transcript.search.clear()
        except Exception:  # noqa: BLE001
            pass
        dock = getattr(self, "kw_folders", None)
        if dock is not None:
            dock.term, dock._firma_vista = "", None
            if dock.isVisible():
                dock._mostrar()

    def _fill_edit_panel(self):
        ep = getattr(self, "edit_panel", None)
        if ep is None or getattr(ep, "job", None) is not None:      # (con un edit creándose no se toca)
            return
        try:
            ep._fill(ep.song.currentData())
        except Exception:  # noqa: BLE001
            pass

    def _antes_de_vaciar(self) -> bool:
        """Reinicio / proyecto nuevo: no con una tarea en marcha; la página Miniatura se cierra antes."""
        busy = self.workspaces._busy()
        if busy:
            self.statusBar().showMessage(f"Espera a que termine (está {busy}) antes de empezar de cero.", 7000)
            return False
        if not self.salir_de_paginas():           # (🎬 Escenas / 🖼 Miniatura: se guardan en el proyecto viejo)
            return False
        return True

    def new_project(self):
        """Ctrl+N: proyecto nuevo en la pestaña actual (🎬 Video · 🎵 Edits · 📱 Shorts)."""
        if not self._antes_de_vaciar():
            return
        if self.workspaces.new_here() is False:       # (canceló: el proyecto sigue y no se limpia nada)
            return
        self.limpiar_interfaz()
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

    def _bienvenida_si_toca(self):
        from . import bienvenida
        if bienvenida.toca_mostrar() and self.isVisible():
            self.open_bienvenida()

    def open_bienvenida(self):
        """👋 Bienvenida y componentes (ui/bienvenida.py)."""
        from . import bienvenida
        self._bienvenida_dlg = bienvenida.abrir(self)

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
        if st["installed"] and not st["completo"]:
            text = "⚠ La instalación del motor de IA se quedó a medias: pulsa «Continuar la instalación»."
        # «Reparar» solo cuando hay algo que arreglar (con el motor bien instalado, confunde)
        problema = (not st["installed"] or not st["completo"] or not st["sam"]
                    or bool(st["vendor"] and not st["gpu"]))
        box = QMessageBox(self)
        box.setWindowTitle("◈ Motor de IA")
        box.setText(text)
        b_inst = None
        if problema:
            b_inst = box.addButton("Instalar" if not st["installed"] else "Continuar la instalación"
                                   if not st["completo"] else "Reparar", QMessageBox.AcceptRole)
        b_dir = box.addButton("Abrir la carpeta", QMessageBox.ActionRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        if b_inst is not None and box.clickedButton() is b_inst:   # (una ventana de Reclaimer, sin consolas)
            self.abrir_motor_instalador(reparar=st["installed"], forzar=st["completo"])   # (⚠ con todo instalado)
        elif box.clickedButton() is b_dir:
            os.startfile(str(motor_ia.DATOS_MOTOR if motor_ia.DATOS_MOTOR.is_dir() else motor_ia.ROOT))    # noqa: S606

    # ------------------------------------------------------------ 📱 barra de los Shorts (encima del visor)
    def _barra_shorts(self):
        """En la pestaña Shorts, a la vista: 🎙 Transcribir, 💬 Subtítulos, 🔑 Palabras clave y ▦ Encuadrar (los
        videos horizontales, enteros en el centro con arriba y abajo borroso; también solo, al añadirlos)."""
        from PySide6.QtWidgets import QMenu, QToolButton
        st = QSettings("EditorIA", "EditorIA")
        self.ctrl.encuadre_auto_vertical = st.value("shorts/encuadre_auto", True, type=bool)
        lay = self.preview.shorts_lay

        def boton(texto, tip, fn):
            b = QPushButton(texto)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            lay.addWidget(b)
            return b
        boton("🎙 Transcribir", "Transcribe la narración (para subtítulos, palabras clave y quitar silencios)",
              lambda: (self.abrir_seccion("voz_texto", "transcribir"), self.voice.transcribe()))
        boton("🗣 Que lo lea la IA", "¿No quieres hablar? Pega tu guion y una voz sintética lo lee (ya transcrito: "
                                    "subtítulos y palabras clave al momento)", lambda: self.open_voz_ia())
        boton("💬 Subtítulos", "Subtítulos grandes para Short (después de transcribir)",
              lambda: (self.show_panel(self.subtitles), self.subtitles.btn_quick.click()))
        boton("🔑 Palabras clave", "Crea una carpeta por cada cosa que dices (después de transcribir) para poner su "
                                  "material justo donde lo nombras",
              lambda: (self.show_panel(self.library), self.library._kw_auto()))
        enc = QToolButton()
        enc.setText("▦ Encuadrar")
        enc.setToolTip("Los videos horizontales, enteros en el centro con la parte de arriba y la de abajo borrosas "
                       "(su propia imagen)")
        enc.setPopupMode(QToolButton.MenuButtonPopup)
        enc.setFocusPolicy(Qt.NoFocus)
        enc.clicked.connect(lambda: self._encuadrar_shorts(avisar=True))
        m = QMenu(enc)
        auto = m.addAction("Hacerlo solo al añadir videos y al pasar a Vertical")
        auto.setCheckable(True)
        auto.setChecked(self.ctrl.encuadre_auto_vertical)

        def cambiar(on):
            self.ctrl.encuadre_auto_vertical = bool(on)
            QSettings("EditorIA", "EditorIA").setValue("shorts/encuadre_auto", bool(on))
        auto.toggled.connect(cambiar)
        m.addAction("▦ Encuadrar ahora todos los videos", lambda: self._encuadrar_shorts(avisar=True))
        enc.setMenu(m)
        lay.addWidget(enc)
        self._btn_encuadrar = enc
        # 💬 Subtítulos automáticos (Shorts y Edits): encendido, al añadir un video se transcribe y se ponen solos.
        # Se recuerda al cerrar Reclaimer. En YouTube los subtítulos siguen siendo a mano.
        self.btn_subs_auto = QPushButton("💬 Subtítulos auto")
        self.btn_subs_auto.setObjectName("flat")
        self.btn_subs_auto.setCheckable(True)
        self.btn_subs_auto.setFocusPolicy(Qt.NoFocus)
        self.btn_subs_auto.setChecked(st.value("shorts/subtitulos_auto", True, type=bool))
        self.btn_subs_auto.setToolTip("Encendido: al añadir un video a Vertical o Edits se transcribe y se le ponen los "
                                      "subtítulos solos. Se queda como lo dejes, aunque cierres Reclaimer.")
        self.btn_subs_auto.toggled.connect(
            lambda on: QSettings("EditorIA", "EditorIA").setValue("shorts/subtitulos_auto", bool(on)))
        lay.addWidget(self.btn_subs_auto)
        self.ctrl.clips_placed.connect(self._subtitulos_auto)
        self._al_cambiar_pestaña(self.workspaces.current)

    def _subtitulos_auto(self, ids):
        """💬 Video (con sonido) añadido en Shorts o Edits y «Subtítulos auto» encendido: transcribir y subtítulos."""
        p = self.ctrl.project
        if p.format not in ("short", "edit") or not self.btn_subs_auto.isChecked():
            return
        con_voz = []
        for cid in ids:
            c = p.clips.get(cid)
            m = p.media_of(c) if c is not None else None
            if m is not None and c.text is None and not c.note.startswith("🎬") and \
                    (m.kind == "video" and m.has_audio or m.kind == "audio") and \
                    m.category not in ("Efectos", "Efectos de sonido", "Música"):
                con_voz.append(cid)
        if not con_voz or getattr(self.voice, "job", None) is not None:
            return
        ids = con_voz                               # (la voz se elige solo entre estos: nada de música o efectos)
        st = p.subtitles
        if st.media_id in p.transcripts:
            return                                  # (ya hay subtítulos, encendidos o apagados por ti: no se tocan)
        # la voz: la del video que acabas de poner (si la narración elegida no está en la línea de tiempo)
        usados = {p.clips[c].media_id for c in p.clips}
        if self.voice.media_id() not in usados:
            for cid in ids:
                c = p.clips.get(cid)
                i = self.voice.media_combo.findData(c.media_id) if c is not None else -1
                if i >= 0:
                    self.voice.media_combo.setCurrentIndex(i)
                    break
        mid = self.voice.media_id()
        t = p.transcripts.get(mid) if mid else None
        if t is not None and t.get("hasta") is not None:   # (a medias: sin preguntar, solo se avisa)
            self.statusBar().showMessage("💬 La transcripción de esa voz quedó a medias: «🎙 Transcribir» para "
                                         "terminarla y salen los subtítulos.", 8000)
            return
        proyecto = p

        def lanzar():                               # (al dispararse, se vuelve a mirar: mismo proyecto y sin trabajos)
            if self.ctrl.project is proyecto and getattr(self.voice, "job", None) is None and \
                    self.btn_subs_auto.isChecked():
                self.subtitles.quick_short()
        QTimer.singleShot(400, lanzar)              # (transcribe si hace falta y los pone)

    def _encuadrar_shorts(self, avisar: bool = False) -> int:
        if self.ctrl.project.height <= self.ctrl.project.width:
            if avisar:
                self.statusBar().showMessage("▦ Esto es para proyectos verticales (Vertical y Edits).", 5000)
            return 0
        try:
            n = self.ctrl.encuadrar_shorts()
        except Exception as exc:  # noqa: BLE001 - p. ej. un clip bloqueado
            self.statusBar().showMessage(str(exc), 6000)
            return 0
        if n or avisar:
            self.statusBar().showMessage(f"▦ {n} video{'s' if n != 1 else ''} encuadrado{'s' if n != 1 else ''} "
                                         "con arriba y abajo borroso (Ctrl+Z para quitarlo)." if n else
                                         "▦ No hay videos horizontales sin encuadrar.", 6000)
        return n

    def _al_cambiar_pestaña(self, tab: str):
        # (el encuadre automático va al pasar el proyecto a Shorts y al añadir videos, no al entrar en la pestaña:
        # si quitaste el fondo borroso de un clip, no vuelve solo)
        self.preview.shorts_bar.setVisible(tab in ("short", "edit"))        # (Shorts y Edits)
        if hasattr(self, "_btn_encuadrar"):
            self._btn_encuadrar.setVisible(tab in ("short", "edit"))

    def abrir_motor_instalador(self, reparar: bool = False, forzar: bool = False):
        """◈ La ventana de instalar el motor (una sola: si ya está abierta, se trae delante)."""
        from . import motor_install_dialog
        d = getattr(self, "_motor_dlg", None)
        try:
            if d is not None and d.isVisible():
                d.raise_()
                d.activateWindow()
                return d
        except RuntimeError:
            pass
        self._motor_dlg = motor_install_dialog.abrir(self, reparar=reparar, forzar=forzar)
        return self._motor_dlg

    def _check_motor_soon(self):
        """Al arrancar (sin prisa): si hay motor y tarjeta NVIDIA o AMD pero la IA no la ve, se avisa."""
        import threading
        from ..core import motor_ia
        if not motor_ia.PYTHON.exists() or os.environ.get("EDITORIA_DATOS"):    # (las pruebas no lo revisan)
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
            path = self.render_queue.add(p, opts, "⚡ " + t["name"])["opts"]["path"]   # (« (2)» si ya estaba en cola)
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
        previo = getattr(self, "_export_dlg", None)
        try:
            en_marcha = previo is not None and previo.exportando()
        except RuntimeError:
            en_marcha = False
        if en_marcha:                                # (ya hay una exportación escondida: se enseña esa, no otra)
            previo._oculto = False
            previo.show()
            previo.raise_()
            return
        if revision_previa(self):
            # (guardado en la ventana: con «🖼 Ir a Miniatura mientras exporta» el diálogo se esconde y sigue vivo)
            self._export_dlg = ExportDialog(self.ctrl, self)
            self._export_dlg.exec()

    def open_audit(self):
        from .audit_dialog import AuditDialog
        self.engine.pause()
        AuditDialog(self.ctrl, self.engine, self.timeline, self).exec()

    def open_quick_review(self, scope: str = "todo"):
        """✓ Revisión guiada (Ctrl+Shift+Q): solo lo dudoso, uno a uno (voz, cortes, avisos y B-roll dudoso; «voz»: solo
        lo de la voz). No es modal."""
        from .quick_review import QuickReview
        if self.voice.job is not None or self.ai_panel.job is not None:
            QMessageBox.information(self, "Revisión guiada", "Espera a que termine la tarea de IA que está en marcha.")
            return
        if getattr(self, "quick_review", None) is None:
            self.quick_review = QuickReview(self)
        self.quick_review.start(scope if isinstance(scope, str) else "todo")

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
        if not self._antes_de_vaciar():
            return
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
        self.limpiar_interfaz()
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
        self._al_cambiar_pestaña(self.workspaces.current)    # (📱 la barra si arrancas en Shorts o Edits)
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

    def change_project_tab(self, fmt: str, ask: bool = True) -> bool:
        """↪ (menú 🔄 Reinicio) Lleva el proyecto a otra pestaña y lo quita de esta (que queda vacía)."""
        ws = self.workspaces
        if fmt == ws.current:
            self.statusBar().showMessage(f"Este proyecto ya está en {ws._label(fmt)}.", 5000)
            return False
        p = self.ctrl.project
        if not p.clips and not p.media:
            self.statusBar().showMessage(f"Esta pestaña está vacía: no hay nada que llevar a {ws._label(fmt)}. "
                                         "Haz clic arriba en esa pestaña para trabajar allí.", 7000)
            return False
        if ask:
            ratio = "16:9 (horizontal)" if fmt == "youtube" else "9:16 (vertical)"
            r = QMessageBox.question(
                self, "↪ Cambiar el proyecto de pestaña",
                f"¿Llevar «{p.name or 'este proyecto'}» de {ws._label(ws.current)} a {ws._label(fmt)}?\n\n"
                f"· Pasa a formato {ratio}, con todo lo que tiene.\n"
                f"· {ws._label(ws.current)} queda VACÍA (no se carga dos veces).\n"
                "· Ctrl+Z devuelve el formato anterior.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return False
        return ws.move_to(fmt, ask=ask)

    def reset_project(self):
        """🔄 Reinicio de proyecto: esta pestaña vuelve a estar vacía (línea de tiempo, Medios, subtítulos, marcadores).
        Antes se guarda una copia de seguridad de cómo estaba; el archivo .eia (si tiene) y tus videos no se tocan."""
        if not self._antes_de_vaciar():
            return
        p = self.ctrl.project
        if not p.clips and not p.media:
            self.workspaces.reset_here()              # (aunque ya esté vacío: marcadores, nombre, ajustes… de cero)
            self.limpiar_interfaz()
            self.statusBar().showMessage("🔄 Proyecto vacío: no queda nada a la vista.", 5000)
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
        self.limpiar_interfaz()
        self.statusBar().showMessage("🔄 Proyecto vacío. Copia de lo anterior: " + (backup or "—"), 12000)

    def _maybe_align(self, media_id: str):
        """🎯 Transcripción nueva: sus palabras se afinan en segundo plano (alineación con IA, ~20 ms) para cortar
        silencios sin comerse palabras, para los subtítulos y para verlas sobre la onda. Empieza a los 3 s y solo si
        Reclaimer sigue abierto (cargar el modelo no se puede interrumpir: no se empieza justo al cerrar)."""
        from ..ai import align
        tr = self.ctrl.project.transcripts.get(media_id)
        if tr and (tr.get("estimada") or tr.get("voz_ia")):   # 🗣 Voz IA: ya sabe cada palabra (y no es tu voz)
            return
        if align.needs(tr) and media_id not in self._aligning:
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

    def _es_voz_ia(self, media_id: str | None) -> bool:
        from ..ai import tts
        p = self.ctrl.project
        m = p.media.get(media_id) if media_id else None
        tr = p.transcripts.get(media_id) if media_id else None
        return bool((m is not None and tts.ETIQUETA in (m.tags or [])) or (tr and tr.get("voz_ia")))

    def _transcribir_con_aviso(self, transcribir):
        """🎙 Transcribir, pero si la narración elegida es de la Voz IA (ya tiene su texto exacto) se pregunta antes."""
        def envoltura(analyze: bool = True):
            mid = self.voice.media_id()
            if self._es_voz_ia(mid) and (self.ctrl.project.transcripts.get(mid) or {}).get("words"):
                r = QMessageBox.question(
                    self, "🗣 Narración de la Voz IA",
                    "Esta narración la leyó la Voz IA y ya tiene su transcripción EXACTA (el texto de tu guion).\n\n"
                    "Si la transcribes con Whisper, ese texto se cambia por lo que entienda Whisper (puede equivocarse "
                    "en nombres y signos). ¿Transcribirla igualmente?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if r != QMessageBox.Yes:
                    self.statusBar().showMessage("🗣 La narración de la Voz IA sigue con su texto exacto.", 6000)
                    return None
            return transcribir(analyze)
        return envoltura

    def learn_voice(self, media_id: str, words: list):
        """◈ Palabras recién afinadas: la grabación solo se APUNTA para aprender tu voz (instantáneo, sin gastar nada).
        Se aprende cuando se usa: al abrir «✂ Eliminar silencio» (learn_voice_pending) o con Voz → Entrenar."""
        import importlib.util
        if importlib.util.find_spec("torch") is None:
            return
        m = self.ctrl.project.media.get(media_id)
        if m is None or not os.path.exists(m.path):
            return
        if self._es_voz_ia(media_id):              # 🗣 una narración de la Voz IA NUNCA enseña «tu voz»
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

    def export_xml(self, path: str | None = None):
        """⇄ La línea de tiempo en XML (xmeml 5) para DaVinci Resolve / Premiere / Final Cut 7."""
        import os as _os
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ..export.xml_export import export_xml
        if not self.ctrl.project.clips:
            self.ctrl.message.emit("La línea de tiempo está vacía: no hay nada que llevar.")
            return None
        if path is None:
            base = _os.path.splitext(self.ctrl.path)[0] if self.ctrl.path else (self.ctrl.project.name or "Reclaimer")
            path, _ = QFileDialog.getSaveFileName(self, "Llevar a DaVinci Resolve / Premiere", base + ".xml",
                                                  "XML de línea de tiempo (*.xml)")
            if not path:
                return None
        try:
            res = export_xml(self.ctrl.project, path)
        except OSError as ex:
            QMessageBox.warning(self, "XML", f"No se pudo guardar: {ex}")
            return None
        msg = f"⇄ Guardado {_os.path.basename(path)} ({res['clips']} clips): en DaVinci, Archivo → Importar → "               "Línea de tiempo; en Premiere, Archivo → Importar."
        self.ctrl.message.emit(msg + (" Ojo: " + " ".join(res["notes"]) if res["notes"] else ""))
        return res

    def _titles_menu(self, parent):
        """🅣 El menú de plantillas de título (se rehace al abrirlo: así salen las ★ que acabas de guardar)."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(parent)

        def fill():
            from ..core import title_templates as TT
            menu.clear()
            mine = []
            for key, name in TT.all_templates():
                if key.startswith("★") and not mine:
                    menu.addSeparator()
                if key.startswith("★"):
                    mine.append(key)
                menu.addAction(name, lambda k=key: self.ctrl.add_text_template(k, self.engine.time))
            if mine:
                dm = menu.addMenu("🗑 Borrar una plantilla mía")
                for key in mine:
                    dm.addAction(key[1:], lambda k=key: TT.delete_user(k))
        menu.aboutToShow.connect(fill)
        fill()
        return menu

    def _tema_menu(self, parent):
        """🎨 Ventana → Tema: gris (bordes visibles) u oscuro (el de antes). Se aplica al volver a abrir Reclaimer."""
        from PySide6.QtGui import QActionGroup
        from PySide6.QtCore import QSettings
        from . import tema as TM
        sm = parent.addMenu("🎨 Tema")
        sm.setToolTipsVisible(True)
        grupo = QActionGroup(sm)
        for t in TM.TEMAS:
            a = sm.addAction(TM.NOMBRES[t])
            a.setCheckable(True)
            a.setChecked(t == TM.nombre())
            a.setToolTip("Gris: fondos más claros y bordes marcados para ver dónde empieza y termina cada panel, "
                         "botón y pista. Oscuro: el de antes, estilo DaVinci. Se aplica al volver a abrir Reclaimer.")
            grupo.addAction(a)

            def elegir(_on=False, tt=t):
                QSettings("EditorIA", "EditorIA").setValue(TM.KEY, tt)
                self.statusBar().showMessage(f"🎨 Tema: {TM.NOMBRES[tt]}. Se aplica al volver a abrir Reclaimer.",
                                             8000)
            a.triggered.connect(elegir)
        if getattr(self, "tema_menu", None) is None:   # (está en Ventana y en «🎨 Diseño»: el primero)
            self.tema_menu = sm
        return sm

    def _llenar_acentos(self, menu):
        """🎨 Color de acento: una muestra de color y su nombre por acento; al elegir, se aplica AL MOMENTO (sin volver a
        abrir Reclaimer) y se recuerda. Está en «🎨 Diseño» (barra de arriba) y en Ventana."""
        from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
        from . import theme as TH
        grupo = QActionGroup(menu)
        if not hasattr(self, "_acciones_acento"):
            self._acciones_acento = []
        for clave, (nombre, color, _hi) in TH.ACENTOS.items():
            pm = QPixmap(32, 32)
            pm.setDevicePixelRatio(2.0)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QColor("#5d6068"))
            p.setBrush(QColor(color))
            p.drawRoundedRect(1, 1, 14, 14, 3, 3)
            p.end()
            a = menu.addAction(QIcon(pm), nombre)
            a.setCheckable(True)
            a.setChecked(clave == TH.ACENTO)
            a.setData(clave)
            a.setToolTip(f"{nombre}: el color de lo elegido, lo activo y el botón principal. Se ve al momento.")
            grupo.addAction(a)
            a.triggered.connect(lambda _on=False, k=clave: self.poner_acento(k))
            self._acciones_acento.append(a)

    def poner_acento(self, clave: str):
        """🎨 Cambia el color de acento al momento (theme.poner_acento) y marca la opción en los dos menús."""
        from . import theme as TH
        if not TH.poner_acento(clave, QApplication.instance()):
            return
        for a in getattr(self, "_acciones_acento", []):
            try:
                a.setChecked(a.data() == clave)
            except RuntimeError:
                pass
        self.statusBar().showMessage(f"🎨 Color de acento: {TH.ACENTOS[clave][0]}.", 6000)

    def _ui_scale_menu(self, parent):
        """🔍 Ventana → Escala de la interfaz (se aplica al volver a abrir Reclaimer)."""
        from PySide6.QtGui import QActionGroup
        from PySide6.QtCore import QSettings
        from . import ui_scale as US
        sm = parent.addMenu("🔍 Escala de la interfaz")
        sm.setToolTipsVisible(True)
        grupo = QActionGroup(sm)
        actual = US.setting()
        for op in US.OPCIONES:
            a = sm.addAction(US.NOMBRES[op])
            a.setCheckable(True)
            a.setChecked(op == actual)
            a.setToolTip("Agranda TODO (botones, iconos, letras y línea de tiempo), como la escala de Windows pero "
                         "solo en Reclaimer. Automática: en pantallas 2K con Windows al 100 % se ve al 125 %; en 4K, "
                         "al 150 %. Se aplica al volver a abrir Reclaimer.")
            grupo.addAction(a)

            def elegir(_on=False, o=op):
                QSettings("EditorIA", "EditorIA").setValue(US.KEY, o)
                self.statusBar().showMessage(f"🔍 Escala de la interfaz: {US.NOMBRES[o]}. Se aplica al volver a abrir "
                                             "Reclaimer.", 8000)
            a.triggered.connect(elegir)
        self.ui_scale_menu = sm
        return sm

    def _alt_t(self):
        """Alt+T: disolver en el corte (⏱ con duración automática si está puesta en el panel Efectos)."""
        from ..core import transitions as TR
        ids = self.ctrl.transition_targets(sorted(self.timeline.selected), self.engine.time)
        self.ctrl.set_transition(ids, "fade", None if TR.auto_on() else 0.5)

    def closeEvent(self, e):
        win = getattr(self, "_second", None)
        if win is not None and win.isVisible():        # al cerrar el programa, la segunda pantalla queda «abierta» para la próxima vez
            QSettings("EditorIA", "EditorIA").setValue(self.SECOND_KEY, True)
            self._second_closing = True
            win.close()
            self._second_closing = False
        self.engine.pause()
        # 🎬 Escenas con cambios sin aplicar: pregunta (Cancelar = no se cierra)
        if getattr(self, "_scenes_state", None) is not None:
            pg = getattr(self, "_scenes_widget", None)
            if pg is not None and not pg.volver("edit"):
                e.ignore()
                return
        # ⬆ Una exportación escondida («🖼 Ir a Miniatura mientras exporta»): se pregunta ahora y se para al final
        dlg_x = getattr(self, "_export_dlg", None)
        try:
            exportando = dlg_x is not None and dlg_x.exportando()
        except RuntimeError:
            exportando = False
        # 🚀 La cola de exportación (exportando o con trabajos por hacer) entra en la misma pregunta
        cola = getattr(self, "_render_queue", None)
        try:
            cola_ocupada = cola is not None and cola.busy()
        except (AttributeError, RuntimeError):
            cola_ocupada = False
        if exportando or cola_ocupada:
            partes = []
            if exportando:
                partes.append("Todavía se está exportando el video.")
            if cola_ocupada:
                n = cola.pending_count()
                partes.append("La cola de exportación " + ("está exportando" if cola.running else "tiene trabajos")
                              + (f" ({n} por exportar)." if n else "."))
            r = QMessageBox.question(self, "Exportación en curso",
                                     "\n".join(partes) + "\n\n¿Cancelar " + ("las exportaciones"
                                     if exportando and cola_ocupada else "la exportación" if exportando
                                     else "la cola") + " y cerrar?\n(Lo que está a medias se borra; los videos "
                                     "que ya tenías no se tocan.)")
            if r != QMessageBox.Yes:
                e.ignore()
                return
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
        if exportando:                   # ⬆ ya respondiste todo: ahora sí se para la exportación escondida
            try:                         # (y se borran su archivo a medias y sus temporales)
                dlg_x.abort_for_exit(3000)
            except (AttributeError, RuntimeError):
                pass
        if cola is not None:             # 🚀 la cola: se para y se borra lo que estaba a medias
            try:
                cola.abort(3000)
            except (AttributeError, RuntimeError):
                pass
        self.saving.stop()               # el guardado en vivo se para antes de cerrar
        self.learner.on_close()          # último resumen; después no queda nada funcionando
        from .task_window import stop_all
        stop_all()                       # trabajos en segundo plano: se paran y se espera un momento
        self.voice.shutdown()
        self.voz_ia.shutdown()
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
        if not getattr(self, "_tl_revisada", False):     # (solo al abrir: suelta encima del visor → a su sitio)
            self._tl_revisada = True
            self._acoplar_timeline_si_tapa()
            QTimer.singleShot(0, self._paneles_a_su_sitio)   # (y los paneles sueltos encima o fuera, a su lado)
        # siempre al abrir: la línea de tiempo con todas sus pistas a la vista (también tras maximizar)
        QTimer.singleShot(0, self._ensure_timeline_size)
        QTimer.singleShot(400, self._ensure_timeline_size)
        QTimer.singleShot(0, self._ensure_side_widths)
        wh = self.windowHandle()
        if wh is not None and not getattr(self, "_vigila_pantalla", False):
            self._vigila_pantalla = True                 # (al pasar la ventana a otra pantalla, que quepa en ella)
            wh.screenChanged.connect(lambda _s: self._pestañas_pronto())
        QTimer.singleShot(400, self._ensure_side_widths)
        QTimer.singleShot(0, self.timeline.fit)
