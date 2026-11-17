"""
Panel «Efectos»: ⭐ mis efectos para la IA (los propone donde encajan y aprende de tus ✓/✗), sonidos (los de
Reclaimer y tu carpeta de efectos descargados), efectos de imagen para los clips seleccionados,
transiciones y fuentes de efectos gratis en internet (con su licencia).
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QMimeData, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QDrag
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import fx_preview_ui as FXP
from ..core import sfx
from ..core.model import TRACK_AUDIO
from .common import EFFECT_MIME, MEDIA_MIME
from .help import set_help

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aif", ".aiff")

# Fuentes revisadas (octubre de 2026). Lo importante: que puedas usarlas en videos monetizados.
SOURCES = [
    ("Kenney.nl — paquetes de audio", "https://kenney.nl/assets/category:Audio",
     "Impactos, interfaz, ciencia ficción… CC0 (dominio público): sin atribución, uso comercial. Lo más seguro."),
    ("Sonniss · GDC Game Audio Bundle", "https://gdc.sonniss.com/",
     "Decenas de GB de efectos de cine profesionales (whooshes, impactos, ambientes). Libres de derechos, "
     "uso comercial sin atribución; prohibido revender los sonidos sueltos o usarlos para entrenar IA."),
    ("Freesound (filtra «Creative Commons 0»)", "https://freesound.org/search/?f=license:%22Creative+Commons+0%22",
     "Enorme biblioteca. Usa solo los marcados CC0 (los CC-BY piden atribución en la descripción)."),
    ("Mixkit — efectos de sonido", "https://mixkit.co/free-sound-effects/",
     "Gratis y sin registro. Revisa su licencia antes (no la pude verificar completa)."),
    ("Mixkit — luces y overlays de video", "https://mixkit.co/free-stock-video/light-leak/",
     "Destellos de luz y texturas para poner encima del video. Revisa su licencia antes."),
]

LOOKS = [  # (clave, texto, valor, ayuda)
    ("bw", "⚫ Blanco y negro", 1.0, "Quita el color."),
    ("vignette", "◐ Viñeta", 0.6, "Oscurece los bordes: centra la mirada."),
    ("grain", "░ Grano de película", 0.5, "Textura de cine."),
    ("blur", "◌ Desenfoque", 0.5, "Desenfoca el clip (ideal de fondo para un texto)."),
    ("glitch", "▚ Glitch RGB", 0.4, "Separa los colores al empezar el clip (segundos)."),
    ("oldfilm", "🎞 Película antigua", 1.0, "Tono vintage, grano y viñeta."),
    ("warm", "☀ Tono cálido", 0.6, "Más naranja."),
    ("cold", "❄ Tono frío", 0.6, "Más azul."),
    ("flash", "✦ Destello al entrar", 0.15, "Destello blanco al empezar (segundos)."),
    ("shake", "≋ Temblor al entrar", 0.4, "La imagen tiembla al empezar (segundos)."),
    ("fade_in", "▶ Fundido de entrada", 0.5, "Aparece desde negro (segundos)."),
    ("fade_out", "■ Fundido de salida", 0.8, "Se va a negro al final (segundos)."),
    # Los de los edits musicales (velocity, phonk, AMV)
    ("rgbsplit", "🌈 Separación RGB", 0.5, "Los colores se separan un poco (aberración cromática)."),
    ("glow", "✨ Brillo soñador", 0.5, "Lo claro brilla y se difumina (glow)."),
    ("motionblur", "≈ Desenfoque de movimiento", 0.6, "Estela entre fotogramas (ideal en el acelerón)."),
    ("punchy", "🔥 Contraste intenso", 0.6, "Más contraste, color y nitidez."),
    ("vhs", "📼 VHS", 0.7, "Líneas, colores corridos y ruido de cinta."),
    ("flicker", "⚡ Parpadeo", 0.6, "La luz parpadea en todo el clip."),
    ("roll", "↻ Giro de cámara al entrar", 0.4, "La imagen gira y se endereza (segundos)."),
    ("lightleak", "☀ Destello de luz", 0.6, "Una luz cálida cruza la imagen."),
    ("duotone", "🟣 Duotono", 1.0, "Dos tonos: sombras moradas y luces verdes (edits estilizados)."),
    ("lines", "⚡ Destello de líneas", 0.13, "Al empezar el clip, un haz de líneas verticales blancas cruza el "
     "centro (unos 4 fotogramas; ponlo en el clip de después de un corte). La duración se cambia en el "
     "Inspector → Efectos."),
    ("focus_in", "🔍 Entrar enfocando", 0.3, "El clip empieza muy desenfocado y se enfoca (0,3 s). La duración se "
     "cambia en el Inspector → Efectos."),
]



VOLUMEN_SONIDOS = 0.5     # 🔊 los efectos de sonido entran a la mitad (el usuario: «suenan muy fuertes»)

def _hay_sonidos_internet() -> bool:
    """¿Está la parte solo local de 🌐 buscar sonidos? (en la versión publicada no viene)."""
    try:
        from . import sounds_internet  # noqa: F401
        return True
    except ImportError:
        return False

class _SoundTree(QTreeWidget):
    """Lista de sonidos que se puede arrastrar a la timeline."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):
        ids = [self.panel.media_for(it.data(0, Qt.UserRole)) for it in items if it.data(0, Qt.UserRole)]
        md = QMimeData()
        md.setData(MEDIA_MIME, ",".join(i for i in ids if i).encode())
        return md


def filtrar_arbol(tree, text: str):
    """Deja a la vista solo los sonidos cuyo nombre o descripción contienen el texto (y sus grupos)."""
    t = text.lower().strip()
    for i in range(tree.topLevelItemCount()):
        g = tree.topLevelItem(i)
        visible = 0
        for k in range(g.childCount()):
            it = g.child(k)
            show = not t or t in (it.text(0) + " " + it.text(1)).lower()
            it.setHidden(not show)
            visible += show
        g.setHidden(visible == 0)


class SoundBrowser(QWidget):
    """🔊 Sonidos a mano en Medios: los mismos que en «Efectos» (los de Reclaimer, los guardados de internet y tu
    carpeta), con su buscador, 🌐 buscar en internet y ➕ poner en el cabezal. Usa el panel de efectos por dentro."""

    def __init__(self, fx, parent=None):
        super().__init__(parent)
        self.fx = fx
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("🔎 Buscar sonido (whoosh, golpe, aplausos…)")
        self.search.setToolTip("Busca en tus sonidos. Intro o «🌐» lo busca en internet si no está.")
        v.addWidget(self.search)
        self.tree = _SoundTree(fx)
        self.tree.setHeaderLabels(["Sonido", "Para qué"])
        self.tree.setColumnWidth(0, 170)
        self.tree.setToolTip("Clic = escuchar · doble clic = poner en el cabezal · o arrástralo a la línea de tiempo.")
        self.tree.itemClicked.connect(fx._preview)
        self.tree.itemDoubleClicked.connect(lambda it, _c: fx.add_at_playhead(it) if it is not None and
                                            it.data(0, Qt.UserRole) else None)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.tree, 1)
        fila = QHBoxLayout()
        b_add = QPushButton("➕ Al cabezal")
        b_add.setToolTip("Pone el sonido elegido donde está el cabezal (en su pista de efectos, a la mitad de volumen).")
        b_add.clicked.connect(lambda: fx.add_at_playhead(self.tree.currentItem()))
        fila.addWidget(b_add)
        self.b_web = None
        if _hay_sonidos_internet():
            self.b_web = QPushButton("🌐 Internet")
            self.b_web.setToolTip("Busca un sonido concreto en internet («motor de coche», «puerta que cruje»), "
                                  "lo escuchas y lo guardas en tus sonidos o lo pones en el cabezal.")
            self.b_web.clicked.connect(lambda: fx.open_sound_search(self.search.text().strip()))
            fila.addWidget(self.b_web)
        b_dir = QPushButton("📁")
        b_dir.setFixedWidth(34)
        b_dir.setToolTip("Elige la carpeta donde guardas tus efectos de sonido descargados.")
        b_dir.clicked.connect(fx._choose_folder)
        fila.addWidget(b_dir)
        v.addLayout(fila)
        self.search.textChanged.connect(lambda t: filtrar_arbol(self.tree, t))
        self.search.returnPressed.connect(self._intro)
        self.tree._buscador = self.search          # (al refrescar la lista, el filtro escrito se mantiene)
        fx.registrar_arbol(self.tree)

    def _intro(self):
        """Intro: si no hay ningún sonido con ese nombre, se busca en internet."""
        hay = any(not self.tree.topLevelItem(i).isHidden() for i in range(self.tree.topLevelItemCount()))
        if not hay and self.b_web is not None and self.search.text().strip():
            self.fx.open_sound_search(self.search.text().strip())

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        ref = it.data(0, Qt.UserRole) if it else None
        if ref:
            self.fx._star_menu(ref, self.tree.viewport().mapToGlobal(pos))


class _FxList(QListWidget):
    """Lista de efectos (⭐ mis efectos, transiciones) que se arrastra encima de un clip de la timeline."""

    def __init__(self, prefix: str = ""):
        super().__init__()
        self.prefix = prefix
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):
        md = QMimeData()
        keys = [it.data(Qt.UserRole) for it in items if it.data(Qt.UserRole)]
        if keys:
            md.setData(EFFECT_MIME, (self.prefix + keys[0]).encode())
        return md


class _FxButton(QPushButton):
    """Botón de efecto de imagen: clic = poner/quitar en los seleccionados · arrastrar = soltarlo en un clip."""

    def __init__(self, text: str, key: str):
        super().__init__(text)
        self.key = key
        self._press = None

    def mousePressEvent(self, e):
        self._press = e.position() if e.button() == Qt.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        from PySide6.QtWidgets import QApplication
        if self._press is not None and (e.position() - self._press).manhattanLength() >= \
                QApplication.startDragDistance():
            self._press = None
            self.setDown(False)
            md = QMimeData()
            md.setData(EFFECT_MIME, self.key.encode())
            drag = QDrag(self)
            drag.setMimeData(md)
            drag.setPixmap(self.grab())
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(e)


class EffectsPanel(QWidget):
    def __init__(self, ctrl, engine, timeline, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine, self.timeline = ctrl, engine, timeline
        self.settings = QSettings("EditorIA", "EditorIA")
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.5)                     # 🔊 al escuchar, a la mitad (suenan muy fuertes)
        self.player.setAudioOutput(self.audio_out)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(6, 6, 6, 6)

        # --- ⭐ Mis efectos para la IA ---
        self.memory: list[str] = self._load_memory()
        self.proposals: list[dict] = []
        self._fx_job = None
        g0 = QGroupBox("⭐ Mis efectos para la IA")
        v0 = QVBoxLayout(g0)
        g0.setToolTip("Elige tus efectos favoritos: la IA busca dónde encajan en el video y te los propone. "
                      "✓ = ponerlo · ✗ = ahí no. Aprende de cada respuesta.")    # (la explicación, al pasar el ratón)
        self.mem_list = _FxList()
        FXP.attach_list(self.mem_list, lambda it: FXP.split_key(it.data(Qt.UserRole) or ""))
        self.mem_list.setToolTip("Arrastra un efecto encima de un clip de la línea de tiempo para ponérselo "
                                 "(si el clip está seleccionado con otros, a todos).\nDoble clic: en los clips "
                                 "seleccionados.")
        self.mem_list.itemDoubleClicked.connect(lambda _it: self.retarget_current())
        self.mem_list.setMaximumHeight(120)
        self.mem_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mem_list.customContextMenuRequested.connect(self._mem_menu)
        v0.addWidget(self.mem_list)
        r0 = QHBoxLayout()
        self.b_mem_add = QPushButton("➕ Añadir efecto…")
        self.b_mem_add.setToolTip("También: clic derecho en un efecto de imagen, un sonido o una transición → ⭐.")
        self.b_mem_add.clicked.connect(self._mem_add_menu)
        b_mem_rm = QPushButton("✕ Quitar")
        b_mem_rm.clicked.connect(self._mem_remove_current)
        r0.addWidget(self.b_mem_add)
        r0.addWidget(b_mem_rm)
        r0.addStretch(1)
        v0.addLayout(r0)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Dónde"))
        self.fx_scope = QComboBox()
        self.fx_scope.addItem("Todo el video", "all")
        self.fx_scope.addItem("Solo los clips seleccionados", "sel")
        self.fx_scope.addItem("Entre las marcas I – O", "marks")
        r1.addWidget(self.fx_scope, 1)
        r1.addWidget(QLabel("Cuántos"))
        self.fx_freq = QComboBox()
        for label, key in (("Pocos", "pocos"), ("Normal", "normal"), ("Muchos", "muchos")):
            self.fx_freq.addItem(label, key)
        self.fx_freq.setCurrentIndex(1)
        r1.addWidget(self.fx_freq)
        v0.addLayout(r1)
        self.b_propose = QPushButton("◈ Proponer dónde ponerlos")
        self.b_propose.setObjectName("primary")
        self.b_propose.clicked.connect(self.propose_effects)
        v0.addWidget(self.b_propose)
        self.prop_tree = QTreeWidget()
        self.prop_tree.setHeaderLabels(["Momento", "Efecto", "Por qué", "✓", "✗"])
        self.prop_tree.setRootIsDecorated(False)
        self.prop_tree.setColumnWidth(0, 62)
        self.prop_tree.setColumnWidth(1, 120)
        self.prop_tree.setColumnWidth(2, 170)
        self.prop_tree.setColumnWidth(3, 28)
        self.prop_tree.setColumnWidth(4, 28)
        self.prop_tree.setMinimumHeight(170)
        self.prop_tree.itemClicked.connect(self._prop_clicked)
        self.prop_tree.currentItemChanged.connect(lambda it, _p: self._prop_focus(it))
        v0.addWidget(self.prop_tree)
        r2 = QHBoxLayout()
        b_all = QPushButton("✓ Poner todas")
        b_all.clicked.connect(self.accept_all)
        self.b_retarget = QPushButton("🎯 En los clips seleccionados")
        self.b_retarget.setToolTip("Pone el efecto de la propuesta marcada en los clips que elijas en la línea de "
                                   "tiempo (en vez de donde lo propuso la IA). También aprende de eso.")
        self.b_retarget.clicked.connect(self.retarget_current)
        b_none = QPushButton("✗ Descartar todas")
        b_none.clicked.connect(self.reject_all)
        r2.addWidget(b_all)
        r2.addWidget(self.b_retarget)
        r2.addWidget(b_none)
        v0.addLayout(r2)
        self.fx_status = QLabel("")
        self.fx_status.setWordWrap(True)
        self.fx_status.setObjectName("dim")
        v0.addWidget(self.fx_status)
        lay.addWidget(set_help(g0, "mis_efectos"))
        self._refresh_memory()
        timeline.effect_mark_clicked.connect(self._mark_clicked)
        timeline.effect_dropped.connect(self.apply_key_to)

        # --- Sonidos ---
        g1 = QGroupBox("🔊 Sonidos")
        v1 = QVBoxLayout(g1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar sonido (whoosh, impacto, glitch…)")
        self.search.textChanged.connect(self._filter)
        v1.addWidget(self.search)
        self.tree = _SoundTree(self)
        self.tree.setHeaderLabels(["Sonido", "Para qué"])
        self.tree.setColumnWidth(0, 190)
        self.tree.setMinimumHeight(260)
        self.tree.itemClicked.connect(self._preview)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._sound_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.add_at_playhead(it) if it is not None and
                                            it.data(0, Qt.UserRole) else None)
        v1.addWidget(self.tree)
        row = QHBoxLayout()
        b_add = QPushButton("➕ Poner en el cabezal")
        b_add.clicked.connect(lambda: self.add_at_playhead(self.tree.currentItem()))
        b_dir = QPushButton("📁 Mi carpeta de efectos…")
        b_dir.setToolTip("Elige la carpeta donde guardas los efectos que descargas (Kenney, Sonniss…).")
        b_dir.clicked.connect(self._choose_folder)
        row.addWidget(b_add)
        row.addWidget(b_dir)
        if _hay_sonidos_internet():
            b_web = QPushButton("🌐 Buscar en internet…")
            b_web.setToolTip("Busca un sonido concreto («motor de coche», «disparo de tanque») "
                             "en YouTube y Myinstants, lo escuchas y lo guardas o lo pones en el cabezal.")
            b_web.clicked.connect(self.open_sound_search)
            row.addWidget(b_web)
        v1.addLayout(row)
        self.tree.setToolTip("Clic = escuchar · doble clic = poner en el cabezal · o arrástralo a la línea de tiempo.")
        lay.addWidget(set_help(g1, "efectos_sonido"))

        # --- Efectos de imagen ---
        g2 = QGroupBox("🎨 Efectos de imagen (para los clips seleccionados)")
        grid = QGridLayout(g2)
        for k, (key, text, val, tip_) in enumerate(LOOKS):
            b = _FxButton(text, "look:" + key)
            FXP.attach(b, "look", key)              # 🎞 icono con el efecto y, al pasar el ratón, en movimiento
            b.setToolTip(tip_ + "\nClic: poner o quitar en los clips seleccionados.\n"
                                "Arrastrar: suéltalo encima de un clip de la línea de tiempo.\n"
                                "Clic derecho: ⭐ añadir a mis efectos para la IA.")
            b.clicked.connect(lambda _=False, kk=key, vv=val, tt=text: self.toggle_look(kk, vv, tt))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda _pos, kk=key, bb=b: self._star_menu("look:" + kk, bb.mapToGlobal(_pos)))
            grid.addWidget(b, k // 2, k % 2)
        b_clear = QPushButton("✕ Quitar todos los efectos")
        b_clear.clicked.connect(self.clear_looks)
        grid.addWidget(b_clear, (len(LOOKS) + 1) // 2, 0, 1, 2)
        rb = QHBoxLayout()
        lab = QLabel("◌ Desenfoque en zona:")
        lab.setToolTip("Desenfoca solo una parte (una cara, un logo, un dato…). Aparece en el centro del clip "
                       "seleccionado: arrástrala en el visor (dentro = mover, esquina naranja = tamaño).")
        rb.addWidget(lab)
        for shape, text in (("rect", "▭ Cuadro"), ("ellipse", "◯ Círculo")):
            b = QPushButton(text)
            b.setToolTip(lab.toolTip())
            b.clicked.connect(lambda _=False, s=shape: self.add_region(s))
            rb.addWidget(b)
        from PySide6.QtWidgets import QDoubleSpinBox as _DS
        self.region_amount = _DS()
        self.region_amount.setRange(0.1, 1.0)
        self.region_amount.setSingleStep(0.1)
        self.region_amount.setValue(float(self.settings.value("efectos/zona_intensidad", 0.6)))
        self.region_amount.setPrefix("Fuerza ")
        self.region_amount.setToolTip("Cuánto desenfoca (se recuerda). Cambia también las zonas del clip seleccionado.")
        self.region_amount.valueChanged.connect(self._region_amount)
        rb.addWidget(self.region_amount)
        b_rm = QPushButton("✕")
        b_rm.setToolTip("Quitar las zonas desenfocadas de los clips seleccionados")
        b_rm.setFixedWidth(30)
        b_rm.clicked.connect(self.clear_regions)
        rb.addWidget(b_rm)
        grid.addLayout(rb, (len(LOOKS) + 1) // 2 + 1, 0, 1, 2)
        # 🟩 Pantalla verde: un clic (el color se detecta solo) y dos controles
        ck = QHBoxLayout()
        lab_ck = QLabel("🟩 Pantalla verde:")
        lab_ck.setToolTip("Quita el fondo de color (verde, azul…) del clip seleccionado: el color se detecta "
                          "solo. Tolerancia = cuánto color se quita · Suavidad = borde suave.")
        ck.addWidget(lab_ck)
        self.b_chroma = QPushButton("Quitar fondo de color")
        self.b_chroma.setToolTip(lab_ck.toolTip())
        self.b_chroma.clicked.connect(self.add_chroma)
        ck.addWidget(self.b_chroma)
        self.ck_sim = _DS()
        self.ck_sim.setRange(0.02, 0.4)
        self.ck_sim.setSingleStep(0.01)
        self.ck_sim.setValue(0.11)
        self.ck_sim.setPrefix("Tolerancia ")
        self.ck_sim.valueChanged.connect(lambda v: self._chroma_set(similarity=round(v, 3)))
        ck.addWidget(self.ck_sim)
        self.ck_blend = _DS()
        self.ck_blend.setRange(0.0, 0.4)
        self.ck_blend.setSingleStep(0.02)
        self.ck_blend.setValue(0.07)
        self.ck_blend.setPrefix("Suavidad ")
        self.ck_blend.valueChanged.connect(lambda v: self._chroma_set(blend=round(v, 3)))
        ck.addWidget(self.ck_blend)
        b_ckx = QPushButton("✕")
        b_ckx.setToolTip("Quitar la pantalla verde de los clips seleccionados")
        b_ckx.setFixedWidth(30)
        b_ckx.clicked.connect(self.clear_chroma)
        ck.addWidget(b_ckx)
        grid.addLayout(ck, (len(LOOKS) + 1) // 2 + 2, 0, 1, 2)
        # 👤 Quitar el fondo quieto (sin pantalla verde): cámara fija, lo que no se mueve se va
        mk = QHBoxLayout()
        lab_mk = QLabel("👤 Fondo por movimiento:")
        lab_mk.setToolTip("Sin pantalla verde: con la CÁMARA FIJA (facecam, plano quieto) se aprende cómo es el "
                          "fondo vacío y se quita todo lo que no se mueve. Si la cámara se mueve, te avisa.")
        mk.addWidget(lab_mk)
        self.b_mkey = QPushButton("Quitar el fondo quieto")
        self.b_mkey.setToolTip(lab_mk.toolTip())
        self.b_mkey.clicked.connect(self.add_motion_key)
        mk.addWidget(self.b_mkey)
        self.mk_thr = _DS()
        self.mk_thr.setRange(0.02, 0.5)
        self.mk_thr.setSingleStep(0.02)
        self.mk_thr.setValue(0.10)
        self.mk_thr.setPrefix("Tolerancia ")
        self.mk_thr.valueChanged.connect(lambda v: self._mkey_set(thr=round(v, 3)))
        mk.addWidget(self.mk_thr)
        b_mkx = QPushButton("✕")
        b_mkx.setToolTip("Quitar «fondo por movimiento» de los clips seleccionados")
        b_mkx.setFixedWidth(30)
        b_mkx.clicked.connect(self.clear_motion_key)
        mk.addWidget(b_mkx)
        grid.addLayout(mk, (len(LOOKS) + 1) // 2 + 3, 0, 1, 2)
        # ▦ Relleno (como el de Resolve): lo vacío alrededor del clip, con la propia imagen ampliada y desenfocada
        rl = QHBoxLayout()
        lab_rl = QLabel("▦ Relleno:")
        lab_rl.setToolTip("Lo que queda vacío alrededor del clip (al aplastarlo, hacerlo pequeño o si no tiene la forma "
                          "de la pantalla) se llena con la MISMA imagen ampliada y desenfocada. Ajustes en el Inspector "
                          "(⤧ Transformar).")
        rl.addWidget(lab_rl)
        self.b_fill = QPushButton("Rellenar con la propia imagen")
        self.b_fill.setToolTip(lab_rl.toolTip())
        self.b_fill.clicked.connect(self.add_fill)
        rl.addWidget(self.b_fill)
        b_rlx = QPushButton("✕")
        b_rlx.setToolTip("Quitar el relleno de los clips seleccionados")
        b_rlx.setFixedWidth(30)
        b_rlx.clicked.connect(self.clear_fill)
        rl.addWidget(b_rlx)
        rl.addStretch(1)
        grid.addLayout(rl, (len(LOOKS) + 1) // 2 + 4, 0, 1, 2)
        self.look_status = QLabel("")
        self.look_status.setObjectName("dim")
        self.look_status.setWordWrap(True)
        grid.addWidget(self.look_status, (len(LOOKS) + 3) // 2 + 4, 0, 1, 2)
        lay.addWidget(set_help(g2, "efectos_imagen"))

        # --- Transiciones ---
        from ..core import transitions as TR
        from PySide6.QtWidgets import QDoubleSpinBox
        gt = QGroupBox("⧉ Transiciones (entre dos clips pegados)")
        vt = QVBoxLayout(gt)
        self.trans_list = _FxList("trans:")
        self.trans_list.setMaximumHeight(170)
        for key, name, desc in TR.CATALOG:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, key)
            it.setToolTip(desc)
            self.trans_list.addItem(it)
        self.trans_list.setCurrentRow(0)
        FXP.attach_list(self.trans_list, lambda it: ("trans", it.data(Qt.UserRole)) if it.data(Qt.UserRole) else None)
        self.trans_list.itemDoubleClicked.connect(lambda _it: self.apply_transition())
        self.trans_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trans_list.customContextMenuRequested.connect(self._trans_menu)
        vt.addWidget(self.trans_list)
        row = QHBoxLayout()
        row.addWidget(QLabel("Duración"))
        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(TR.MIN_DUR, TR.MAX_DUR)
        self.trans_dur.setSingleStep(0.1)
        self.trans_dur.setValue(0.5)
        self.trans_dur.setSuffix(" s")
        row.addWidget(self.trans_dur)
        from PySide6.QtWidgets import QCheckBox
        from PySide6.QtCore import QSettings as _QSt
        self.trans_auto = QCheckBox("⏱ Auto")
        self.trans_auto.setToolTip("Duración automática en cada corte: la típica de cada transición (un latigazo es "
                                   "rápido, un fundido a negro más pausado) y, si suena música con su ritmo "
                                   "reconocido, ajustada a ½, 1 o 2 golpes para que acabe a ritmo.")
        self.trans_auto.setChecked(str(_QSt("EditorIA", "EditorIA").value("transiciones/auto", "true")).lower()
                                   == "true")
        self.trans_dur.setEnabled(not self.trans_auto.isChecked())

        def _auto(on):
            self.trans_dur.setEnabled(not on)
            _QSt("EditorIA", "EditorIA").setValue("transiciones/auto", "true" if on else "false")
        self.trans_auto.toggled.connect(_auto)
        row.addWidget(self.trans_auto)
        row.addStretch()
        vt.addLayout(row)
        row2 = QHBoxLayout()
        b_t = QPushButton("⧉ Poner")
        b_t.setToolTip("En el corte del clip seleccionado (o en el corte más cercano al cabezal). Alt+T")
        b_t.clicked.connect(self.apply_transition)
        b_x = QPushButton("✕ Quitar")
        b_x.clicked.connect(lambda: self.apply_transition(remove=True))
        self.b_view = QPushButton("▶ Ver la transición")
        self.b_view.setToolTip("Prepara en unos segundos cómo queda exactamente y lo repite en bucle.")
        self.b_view.clicked.connect(self.view_transition)
        row2.addWidget(b_t)
        row2.addWidget(b_x)
        row2.addWidget(self.b_view)
        vt.addLayout(row2)
        self.trans_status = QLabel("")                # (para avisos; la explicación, al pasar el ratón)
        gt.setToolTip("Doble clic = poner. El visor la enseña tal cual queda unos segundos después (se prepara "
                      "sola); «▶ Ver la transición» la repite en bucle.")
        self.trans_status.setObjectName("hint")
        self.trans_status.setWordWrap(True)
        vt.addWidget(self.trans_status)
        lay.addWidget(set_help(gt, "transiciones"))

        # --- Gratis en internet ---
        g3 = QGroupBox("🌐 Efectos gratis en internet")
        v3 = QVBoxLayout(g3)
        for name, url, note in SOURCES:
            b = QPushButton(name)
            b.setObjectName("flat")
            b.setToolTip(url)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            v3.addWidget(b)
            b.setToolTip(f"{note}\n{url}")                # (la descripción, al pasar el ratón)
        g3.setToolTip("Descárgalos en una carpeta y elígela con «📁 Mi carpeta de efectos…»: aparecerán aquí.")
        lay.addWidget(set_help(g3, "efectos_internet"))
        self._trans_job = None
        # Limpio, como Resolve: cada cosa en su pestaña y las explicaciones en la ayuda emergente
        from .tabs import tabbed, untitle
        g4 = self._build_context_group()
        timeline.context_fx_requested.connect(self.propose_context_fx)
        untitle(g0, g1, g2, gt, g4)
        self.tabs = tabbed([("Imagen", [g2]), ("Transiciones", [gt]), ("Sonidos", [g1, g3]),
                            ("⭐ Para la IA", [g0]), ("✨ Lo que dices", [g4])], clave="efectos")
        self.tabs.setToolTip("")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.tabs)
        content.deleteLater()
        timeline.selection_changed.connect(lambda _ids: self._update_look_status())
        self.reload()

    # ------------------------------------------------------- ⭐ mis efectos para la IA
    def _load_memory(self) -> list[str]:
        try:
            v = json.loads(str(self.settings.value("efectos/memoria", "[]")))
            return [k for k in v if isinstance(k, str)]
        except ValueError:
            return []

    def _save_memory(self):
        self.settings.setValue("efectos/memoria", json.dumps(self.memory))
        self._refresh_memory()

    def _refresh_memory(self):
        from ..ai.effect_memory import effect_info
        icons = {"look": "🎨", "sound": "🔊", "transition": "⧉"}
        self.mem_list.clear()
        for k in self.memory:
            info = effect_info(k)
            it = QListWidgetItem(f"⭐ {icons.get(info['type'], '')} {info['name']}")
            it.setData(Qt.UserRole, k)
            sk = FXP.split_key(k)
            if sk:
                it.setIcon(FXP.icon(*sk))
            self.mem_list.addItem(it)
        if not self.memory:
            it = QListWidgetItem("(vacío) — «➕ Añadir efecto…» o clic derecho en un efecto → ⭐")
            it.setFlags(Qt.NoItemFlags)
            self.mem_list.addItem(it)

    def add_to_memory(self, key: str):
        if key not in self.memory:
            self.memory.append(key)
            self._save_memory()
        from ..ai.effect_memory import effect_info
        self.fx_status.setText(f"⭐ «{effect_info(key)['name']}» está en tus efectos para la IA.")

    def remove_from_memory(self, key: str):
        if key in self.memory:
            self.memory.remove(key)
            self._save_memory()

    def _star_menu(self, key: str, global_pos):
        menu = QMenu(self)
        if key in self.memory:
            menu.addAction("⭐ Quitar de mis efectos para la IA", lambda: self.remove_from_memory(key))
        else:
            menu.addAction("⭐ Añadir a mis efectos para la IA", lambda: self.add_to_memory(key))
        menu.exec(global_pos)

    def _sound_menu(self, pos):
        it = self.tree.itemAt(pos)
        ref = it.data(0, Qt.UserRole) if it else None
        if ref:
            self._star_menu(ref, self.tree.viewport().mapToGlobal(pos))

    def _trans_menu(self, pos):
        it = self.trans_list.itemAt(pos)
        if it:
            self._star_menu("trans:" + it.data(Qt.UserRole), self.trans_list.viewport().mapToGlobal(pos))

    def _mem_menu(self, pos):
        it = self.mem_list.itemAt(pos)
        k = it.data(Qt.UserRole) if it else None
        if k:
            menu = QMenu(self)
            menu.addAction("✕ Quitar de mis efectos", lambda: self.remove_from_memory(k))
            menu.exec(self.mem_list.viewport().mapToGlobal(pos))

    def _mem_remove_current(self):
        it = self.mem_list.currentItem()
        if it and it.data(Qt.UserRole):
            self.remove_from_memory(it.data(Qt.UserRole))

    def _mem_add_menu(self):
        from ..core import transitions as TR
        menu = QMenu(self)
        mi = menu.addMenu("🎨 Efectos de imagen")
        for key, text, _v, _h in LOOKS:
            a = mi.addAction(("⭐ " if "look:" + key in self.memory else "") + text,
                             lambda kk=key: self.add_to_memory("look:" + kk))
            a.setEnabled("look:" + key not in self.memory)
        ms = menu.addMenu("🔊 Sonidos")
        for key, (name, cat, _d) in sfx.CATALOG.items():
            a = ms.addAction(f"{name}  ·  {cat}", lambda kk=key: self.add_to_memory("sfx:" + kk))
            a.setEnabled("sfx:" + key not in self.memory)
        ms.addSeparator()
        ms.addAction("(los de tu carpeta: clic derecho sobre el sonido → ⭐)").setEnabled(False)
        mt = menu.addMenu("⧉ Transiciones")
        for key, name, _d in TR.CATALOG:
            a = mt.addAction(name, lambda kk=key: self.add_to_memory("trans:" + kk))
            a.setEnabled("trans:" + key not in self.memory)
        menu.exec(self.b_mem_add.mapToGlobal(self.b_mem_add.rect().bottomLeft()))

    def propose_effects(self):
        """La IA busca dónde encajan tus efectos (en segundo plano) y te lo propone."""
        from ..ai import effect_memory as EM
        from ..core.model import Project
        from .jobs import BackgroundJob
        if self._fx_job is not None:
            return
        if not self.memory:
            self.fx_status.setText("Primero añade tus efectos favoritos (⭐).")
            from .nudge import nudge_for
            nudge_for(self.fx_status.text())
            return
        p = self.ctrl.project
        scope, clip_ids = None, None
        mode = self.fx_scope.currentData()
        if mode == "sel":
            clip_ids = {c.id for c in self._targets()}
            if not clip_ids:
                self.fx_status.setText("Selecciona antes los clips en la línea de tiempo.")
                from .nudge import nudge_for
                nudge_for(self.fx_status.text())
                return
        elif mode == "marks":
            scope = p.marked_range()
            if not scope:
                self.fx_status.setText("Marca antes el tramo con I y O en la línea de tiempo.")
                from .nudge import nudge_for
                nudge_for(self.fx_status.text())
                return
        snap = Project.from_dict(json.loads(json.dumps(p.to_dict())))
        clip_vecs, rhythm = dict(self.ctrl.clip_vecs), dict(self.ctrl.rhythm)
        keys, freq = list(self.memory), self.fx_freq.currentData()

        def work(progress, cancelled):
            progress(0.1, "◈ Buscando momentos (temas, cortes, música, lo que dices, lo que se ve)…")
            try:
                tv = EM.visual_text_vecs() if clip_vecs else None
            except Exception:  # noqa: BLE001 - sin el modelo, sin la parte visual
                tv = None
            moments = EM.find_moments(snap, clip_vecs, rhythm, scope=scope, clip_ids=clip_ids, text_vecs=tv)
            return EM.propose(snap, moments, keys, EM.load_store(), freq), len(moments)

        self.b_propose.setEnabled(False)
        self.fx_status.setText("◈ Buscando dónde encajan tus efectos…")
        self._fx_job = BackgroundJob(work, self)

        def done(res):
            self._fx_job = None
            self.b_propose.setEnabled(True)
            props, n_mom = res
            self.proposals = [x for x in props if x["clip_id"] in self.ctrl.project.clips]
            self._fill_proposals()
            self.fx_status.setText(f"◈ {len(self.proposals)} propuestas (de {n_mom} momentos posibles). "
                                   "✓ = ponerlo · ✗ = ahí no · clic = ir ahí." if self.proposals else
                                   "No encontré buenos momentos para esos efectos. Prueba con «Muchos», con más "
                                   "efectos, o pon tú alguno con «🎯 En los clips seleccionados».")

        def failed(msg):
            self._fx_job = None
            self.b_propose.setEnabled(True)
            self.fx_status.setText("✗ " + msg)
        self._fx_job.done.connect(done)
        self._fx_job.failed.connect(failed)
        self._fx_job.start()

    def _fill_proposals(self):
        from .common import fmt_time
        self.prop_tree.clear()
        for x in self.proposals:
            it = QTreeWidgetItem([fmt_time(x["t"], False), x["name"], x["reason"], "✓", "✗"])
            it.setToolTip(2, x["reason"])
            it.setForeground(3, QColor("#5fd18b"))
            it.setForeground(4, QColor("#e5413c"))
            self.prop_tree.addTopLevelItem(it)
        self._update_marks()

    def _update_marks(self):
        cur = self.prop_tree.indexOfTopLevelItem(self.prop_tree.currentItem()) if self.prop_tree.currentItem() else -1
        self.timeline.set_effect_marks([(x["t"], x["name"]) for x in self.proposals], cur)

    def _prop_clicked(self, it, col: int):
        i = self.prop_tree.indexOfTopLevelItem(it)
        if col == 3:
            self.accept_proposals([i])
        elif col == 4:
            self.reject_proposals([i])
        else:
            self._prop_focus(it)

    def _prop_focus(self, it):
        i = self.prop_tree.indexOfTopLevelItem(it) if it else -1
        if not (0 <= i < len(self.proposals)):
            return
        x = self.proposals[i]
        self.engine.seek(x["t"])
        if x["clip_id"] in self.ctrl.project.clips:
            self.timeline.set_selection([x["clip_id"]])
        self._update_marks()

    def _mark_clicked(self, i: int):
        if 0 <= i < self.prop_tree.topLevelItemCount():
            self.prop_tree.setCurrentItem(self.prop_tree.topLevelItem(i))

    def _sound_media(self, keys) -> dict:
        out = {}
        for k in keys:
            if k.startswith(("sfx:", "file:")):
                mid = self.media_for(k)
                if mid:
                    out[k] = mid
        return out

    def accept_proposals(self, rows: list[int]):
        from ..ai import effect_memory as EM
        items = [self.proposals[i] for i in sorted(set(rows)) if 0 <= i < len(self.proposals)]
        if not items:
            return
        res = self.ctrl.apply_effect_items(items, self._sound_media({x["effect"] for x in items}))
        if res is None:
            return
        for x in items:
            EM.learn(x["effect"], x["kind"], x.get("vec"), True)
        self._drop(items)
        self.fx_status.setText(f"✓ Puesto{'s' if len(items) > 1 else ''} {len(items)} efecto(s). Ctrl+Z para deshacer.")

    def reject_proposals(self, rows: list[int]):
        from ..ai import effect_memory as EM
        items = [self.proposals[i] for i in sorted(set(rows)) if 0 <= i < len(self.proposals)]
        for x in items:
            EM.learn(x["effect"], x["kind"], x.get("vec"), False)
        self._drop(items)
        if items:
            self.fx_status.setText("✗ Anotado: la IA lo tendrá en cuenta la próxima vez.")

    def _drop(self, items):
        ids = {x["id"] for x in items}
        self.proposals = [x for x in self.proposals if x["id"] not in ids]
        self._fill_proposals()

    def accept_all(self):
        self.accept_proposals(list(range(len(self.proposals))))

    def reject_all(self):
        self.reject_proposals(list(range(len(self.proposals))))

    def retarget_current(self):
        """El efecto de la propuesta marcada (o el ⭐ marcado en la lista), en los clips que elijas tú."""
        from ..ai import effect_memory as EM
        it = self.prop_tree.currentItem()
        i = self.prop_tree.indexOfTopLevelItem(it) if it else -1
        prop = self.proposals[i] if 0 <= i < len(self.proposals) else None
        key = prop["effect"] if prop else (self.mem_list.currentItem().data(Qt.UserRole)
                                           if self.mem_list.currentItem() else None)
        if not key:
            self.fx_status.setText("Marca una propuesta (o uno de tus ⭐) y selecciona los clips en la línea de tiempo.")
            return
        if self.apply_key_to(key, list(self.timeline.selected)) and prop is not None:
            EM.learn(prop["effect"], prop["kind"], prop.get("vec"), False)      # ahí no lo querías: también se aprende
            self._drop([prop])

    def apply_key_to(self, key: str, ids: list) -> bool:
        """Pone un efecto (⭐, imagen, transición o sonido) en esos clips: al arrastrarlo encima de un clip, con
        doble clic en ⭐ o con «🎯 En los clips seleccionados». Dice claramente por qué no se pudo."""
        from ..ai import effect_memory as EM
        from .nudge import nudge_for
        p = self.ctrl.project
        info = EM.effect_info(key)
        clips = [p.clips[i] for i in ids if i in p.clips]
        if info["type"] != "sound":       # imagen y transición: solo en clips de imagen (no texto ni sonido)
            clips = [c for c in clips if c.text is None and p.track(c.track_id) is not None
                     and p.track(c.track_id).kind != TRACK_AUDIO]
        msg = None
        if not clips:
            msg = ("Selecciona en la línea de tiempo los clips donde lo quieres (o arrastra el efecto encima de un "
                   "clip de video o imagen).")
        else:
            locked = [c for c in clips if c.locked or (p.track(c.track_id) and p.track(c.track_id).locked)]
            if len(locked) == len(clips):
                msg = "🔒 Ese clip (o su pista) está bloqueado: desbloquéalo con el candado de la pista para ponerle efectos."
        if msg:
            self.fx_status.setText(msg)
            self.look_status.setText(msg)
            nudge_for(msg)
            return False
        items = [{"effect": key, "t": c.start, "clip_id": c.id} for c in clips]
        res = self.ctrl.apply_effect_items(items, self._sound_media({key}))
        if res is None:
            return False
        for c in clips:
            if c.id in p.clips:
                EM.learn(key, "elegido", EM.clip_vec(p, self.ctrl.clip_vecs, p.clips[c.id]), True)
        done = f"✓ «{info['name']}» puesto en {len(clips)} clip(s). La IA lo aprende."
        self.fx_status.setText(done)
        self.look_status.setText(done)
        return True

    # ------------------------------------------------------- ✨ efectos según lo que dices
    def _build_context_group(self) -> QGroupBox:
        """✨ Efectos según lo que dices: 🖤 gris en lo triste, 🔍 zoom a la cara en las fotos (ai/context_effects.py)."""
        from PySide6.QtWidgets import QCheckBox, QProgressBar
        self.ctx_props: list[dict] = []
        self._ctx_job = None
        st = self.settings

        def flag(key, default):
            return str(st.value("efectos/" + key, "true" if default else "false")).lower() == "true"

        g = QGroupBox("✨ Efectos según lo que dices")
        g.setToolTip("Mira lo que dices durante los clips ELEGIDOS en la línea de tiempo (sin elegir ninguno, toda la "
                     "línea de tiempo), y un poco antes, y te propone efectos con su motivo.\n"
                     "También: clic derecho en la selección → «✨ Efectos según lo que digo…».")
        v = QVBoxLayout(g)
        r = QHBoxLayout()
        lab = QLabel("🖤 Tono triste:")
        r.addWidget(lab)
        self.ctx_mode = QComboBox()
        self.ctx_mode.addItem("🖤 Blanco y negro", "bw")
        self.ctx_mode.addItem("🩶 Desaturado suave", "desat")
        self.ctx_mode.setCurrentIndex(max(0, self.ctx_mode.findData(str(st.value("efectos/ctx_modo", "bw")))))
        self.ctx_mode.setToolTip("Qué se pone cuando lo que dices es triste, una noticia fuerte o un tema difícil "
                                 "(«falleció», «tragedia», «despidos», «cancelado», «accidente», «polémica»…; "
                                 "«no murió» no cuenta).\nEn un clip largo, solo el tramo de esa frase.")
        lab.setToolTip(self.ctx_mode.toolTip())
        self.ctx_mode.currentIndexChanged.connect(
            lambda _i: st.setValue("efectos/ctx_modo", self.ctx_mode.currentData()))
        r.addWidget(self.ctx_mode, 1)
        b_words = QPushButton("📝 Mis palabras…")
        b_words.setToolTip("Añade tus palabras o frases tristes (o las que no deben contar nunca) en un archivo de "
                           "texto: una por línea.")
        b_words.clicked.connect(self._ctx_open_lexicon)
        r.addWidget(b_words)
        v.addLayout(r)
        self.ctx_name = QCheckBox("👤 Solo cuando nombro a alguien / una palabra clave")
        self.ctx_name.setToolTip("El gris solo si en esa frase (o muy cerca) dices el nombre de alguien, un nombre "
                                 "propio o una de tus palabras clave 🔑 / del glosario 📖.")
        self.ctx_zoom = QCheckBox("🔍 Zoom a la cara en las fotos")
        self.ctx_zoom.setToolTip("En las IMÁGENES con una cara o una persona: zoom dinámico suave hacia ella.\n"
                                 "Cada foto se mira una sola vez, pequeña y en segundo plano (se recuerda); "
                                 "los videos no se analizan.")
        self.ctx_star = QCheckBox("⭐ Y mis efectos para la IA")
        self.ctx_star.setToolTip("También tus ⭐ efectos favoritos donde los pide lo que dices («fíjense», «hace "
                                 "años», «desastre», «increíble»…), solo en estos clips.")
        self.ctx_direct = QCheckBox("⚡ Aplicar sin preguntar")
        self.ctx_direct.setToolTip("Pone todas las propuestas en cuanto las encuentra, sin revisarlas (un Ctrl+Z "
                                   "las quita todas).")
        for cb, key, default in ((self.ctx_name, "ctx_nombre", False), (self.ctx_zoom, "ctx_zoom", True),
                                 (self.ctx_star, "ctx_star", True), (self.ctx_direct, "ctx_directo", False)):
            cb.setChecked(flag(key, default))
            cb.toggled.connect(lambda on, k=key: st.setValue("efectos/" + k, "true" if on else "false"))
        grid = QGridLayout()
        grid.addWidget(self.ctx_name, 0, 0, 1, 2)
        grid.addWidget(self.ctx_zoom, 1, 0)
        grid.addWidget(self.ctx_star, 1, 1)
        v.addLayout(grid)
        r2 = QHBoxLayout()
        self.b_ctx = QPushButton("✨ Proponer en los clips elegidos")
        self.b_ctx.setObjectName("primary")
        self.b_ctx.setToolTip("Sin clips elegidos: en toda la línea de tiempo.")
        self.b_ctx.clicked.connect(lambda: self.propose_context_fx())
        r2.addWidget(self.b_ctx, 1)
        r2.addWidget(self.ctx_direct)
        self.b_ctx_cancel = QPushButton("✕ Cancelar")
        self.b_ctx_cancel.setToolTip("Para de buscar caras (lo encontrado hasta ahora se queda).")
        self.b_ctx_cancel.setEnabled(False)
        self.b_ctx_cancel.clicked.connect(self._ctx_cancel)
        r2.addWidget(self.b_ctx_cancel)
        v.addLayout(r2)
        self.ctx_bar = QProgressBar()
        self.ctx_bar.setRange(0, 100)
        self.ctx_bar.setTextVisible(False)
        self.ctx_bar.setMaximumHeight(6)
        self.ctx_bar.hide()
        v.addWidget(self.ctx_bar)
        self.ctx_tree = QTreeWidget()
        self.ctx_tree.setHeaderLabels(["Momento", "Efecto", "Por qué"])
        self.ctx_tree.setRootIsDecorated(False)
        self.ctx_tree.setColumnWidth(0, 80)
        self.ctx_tree.setColumnWidth(1, 140)
        self.ctx_tree.setMinimumHeight(170)
        self.ctx_tree.setToolTip("Marca las que quieres · clic = ir ahí.")
        self.ctx_tree.currentItemChanged.connect(lambda it, _p: self._ctx_focus(it))
        v.addWidget(self.ctx_tree)
        r3 = QHBoxLayout()
        b_ok = QPushButton("✓ Aplicar las marcadas")
        b_ok.setToolTip("Todas a la vez, en un solo paso de deshacer (Ctrl+Z).")
        b_ok.clicked.connect(lambda: self.ctx_apply())
        b_all = QPushButton("☑")
        b_all.setToolTip("Marcar todas")
        b_all.setFixedWidth(34)
        b_all.clicked.connect(lambda: self._ctx_check_all(True))
        b_none = QPushButton("☐")
        b_none.setToolTip("Desmarcar todas")
        b_none.setFixedWidth(34)
        b_none.clicked.connect(lambda: self._ctx_check_all(False))
        b_rej = QPushButton("✗ Descartar")
        b_rej.setToolTip("Quita de la lista las marcadas (si no hay ninguna marcada, todas).")
        b_rej.clicked.connect(self.ctx_reject)
        for w in (b_ok, b_all, b_none, b_rej):
            r3.addWidget(w)
        v.addLayout(r3)
        self.ctx_status = QLabel("")
        self.ctx_status.setObjectName("dim")
        self.ctx_status.setWordWrap(True)
        v.addWidget(self.ctx_status)
        return g

    def _ctx_open_lexicon(self):
        from ..ai import context_effects as CE
        path = CE.user_lexicon_path()
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(CE.USER_TEMPLATE)
            except OSError as exc:
                self.ctx_status.setText(f"✗ No pude crear {path}: {exc}")
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _ctx_busy(self, on: bool):
        self.b_ctx.setEnabled(not on)
        self.b_ctx_cancel.setEnabled(on)
        self.ctx_bar.setVisible(on)
        self.ctx_bar.setValue(0)

    def _ctx_cancel(self):
        if self._ctx_job is not None:
            self._ctx_job.cancel()
            self.ctx_status.setText("✕ Parando…")

    def _show_ctx_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).startswith("✨"):
                self.tabs.setCurrentIndex(i)
        win = self.window()
        if hasattr(win, "show_panel"):
            win.show_panel(self)

    def propose_context_fx(self, ids=None):
        """✨ Propuestas para los clips elegidos (ids; None = la selección; sin selección, toda la línea de tiempo):
        el léxico es instantáneo; las caras de las fotos, en segundo plano (con caché, progreso y cancelar)."""
        from ..ai import context_effects as CE
        from ..core.model import Project
        from .jobs import BackgroundJob
        from .nudge import nudge_for
        self._show_ctx_tab()
        if self._ctx_job is not None:
            self.ctx_status.setText("Ya estoy en ello…")
            return
        p = self.ctrl.project
        if ids is None:
            ids = [i for i in self.timeline.selected if i in p.clips]
        clips = CE.scope_clips(p, ids) if ids else []
        if ids and not clips:                       # (elegiste solo textos o sonido: no se mira todo)
            self.ctx_status.setText("Elige clips de video o imagen (o ninguno, para toda la línea de tiempo).")
            nudge_for(self.ctx_status.text())
            return
        donde = (f"{len(clips)} clip{'s' if len(clips) != 1 else ''} elegido{'s' if len(clips) != 1 else ''}"
                 if clips else "toda la línea de tiempo")
        if not clips:
            clips = CE.scope_clips(p)
        if not clips:
            self.ctx_status.setText("No hay clips de video o imagen en la línea de tiempo.")
            nudge_for(self.ctx_status.text())
            return
        has_words = any(mid in p.media and (tr or {}).get("words") for mid, tr in p.transcripts.items())
        imgs = CE.image_clips_for_zoom(p, clips) if self.ctx_zoom.isChecked() else []
        if not has_words and not imgs:
            self.ctx_status.setText("Primero transcribe tu narración (IA ✨ → 🎙 Transcribir): así sé lo que dices.")
            nudge_for(self.ctx_status.text())
            return
        snap = Project.from_dict(json.loads(json.dumps(p.to_dict())))
        scope_ids = [c.id for c in clips]
        mode, need = self.ctx_mode.currentData(), self.ctx_name.isChecked()
        keys = list(self.memory) if self.ctx_star.isChecked() else []
        freq = self.fx_freq.currentData()
        root = None
        if need:
            try:
                from .clips_panel import _raiz_guardada
                root = _raiz_guardada()
            except Exception:  # noqa: BLE001 - sin carpetas de palabras clave: nombres propios y glosario
                root = None
        paths = list(dict.fromkeys(snap.media[c.media_id].path for c in imgs if c.media_id in snap.media))

        def work(progress, cancelled):
            progress(0.02, "✨ Leyendo lo que dices…")
            sc = CE.scope_clips(snap, scope_ids)
            words = CE.timeline_words(snap)
            names = []
            if need and words:
                extra = glos = None
                try:
                    from ..core import keyword_folders as KF
                    extra = KF.terms(KF.list_folders(root)) if root and os.path.isdir(root) else None
                except Exception:  # noqa: BLE001
                    extra = None
                try:
                    from ..ai import keyword_glossary as KG
                    glos = KG.load()
                except Exception:  # noqa: BLE001
                    glos = None
                names = CE.mention_names(snap, extra, glos)
            tone = CE.tone_proposals(snap, sc, words, mode=mode, need_name=need, names=names) if words else []
            star = []
            if keys and words:
                try:
                    star = CE.star_proposals(snap, sc, keys, freq)
                except Exception:  # noqa: BLE001 - las ⭐ son un extra: sin ellas sigue lo demás
                    star = []
            faces, stopped = {}, False
            for k, path in enumerate(paths):
                if cancelled():
                    stopped = True
                    break
                progress(0.1 + 0.9 * k / max(1, len(paths)), f"🔍 Buscando caras en las fotos ({k + 1}/{len(paths)})…")
                faces[path] = CE.image_face(path)
            return CE.merge(tone, CE.zoom_proposals(snap, sc, faces), star), stopped

        self._ctx_busy(True)
        self.ctx_status.setText(f"✨ Mirando lo que dices en {donde}…")
        job = self._ctx_job = BackgroundJob(work, self)
        job.title = "✨ Efectos según lo que dices"
        job.progress.connect(lambda f, t: (self.ctx_bar.setValue(int(f * 100)), self.ctx_status.setText(t)))

        def done(res):
            self._ctx_job = None
            self._ctx_busy(False)
            props, stopped = res
            self.ctx_props = [x for x in props if x["clip_id"] in self.ctrl.project.clips]
            extra = " (paré de buscar caras: lo encontrado hasta ahí)" if stopped else ""
            if not self.ctx_props:
                self._ctx_fill()
                self.ctx_status.setText(f"No encontré nada triste ni caras en {donde}{extra}." +
                                        (" Prueba sin «👤 Solo cuando nombro…»." if need else ""))
                return
            self._ctx_fill()                        # (la lista al día también si aplicar falla)
            if self.ctx_direct.isChecked():
                self.ctx_apply(list(range(len(self.ctx_props))))
                return
            self.ctx_status.setText(f"✨ {len(self.ctx_props)} propuesta(s) en {donde}{extra}. Marca las que quieres "
                                    "y «✓ Aplicar las marcadas».")

        def failed(msg):
            self._ctx_job = None
            self._ctx_busy(False)
            self.ctx_status.setText("✗ " + msg)
        job.done.connect(done)
        job.failed.connect(failed)
        job.start()

    def _ctx_fill(self):
        from .common import fmt_time
        self.ctx_tree.clear()
        for x in self.ctx_props:
            it = QTreeWidgetItem([fmt_time(x["t"], False), x["name"], x["reason"]])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            for col in range(3):
                it.setToolTip(col, f"{x['name']} — {x['reason']}")
            self.ctx_tree.addTopLevelItem(it)

    def _ctx_rows(self, checked: bool = True) -> list[int]:
        return [i for i in range(self.ctx_tree.topLevelItemCount())
                if (self.ctx_tree.topLevelItem(i).checkState(0) == Qt.Checked) == checked]

    def _ctx_check_all(self, on: bool):
        for i in range(self.ctx_tree.topLevelItemCount()):
            self.ctx_tree.topLevelItem(i).setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _ctx_focus(self, it):
        i = self.ctx_tree.indexOfTopLevelItem(it) if it else -1
        if not (0 <= i < len(self.ctx_props)):
            return
        x = self.ctx_props[i]
        self.engine.seek(x["t"])
        if x["clip_id"] in self.ctrl.project.clips:
            self.timeline.set_selection([x["clip_id"]])

    def _ctx_drop(self, items):
        ids = {x["id"] for x in items}
        self.ctx_props = [x for x in self.ctx_props if x["id"] not in ids]
        self._ctx_fill()

    def ctx_apply(self, rows: list[int] | None = None):
        """Pone las propuestas marcadas (o esas filas) en UN solo paso de deshacer."""
        from ..ai import effect_memory as EM
        rows = self._ctx_rows(True) if rows is None else rows
        items = [self.ctx_props[i] for i in sorted(set(rows)) if 0 <= i < len(self.ctx_props)]
        if not items:
            self.ctx_status.setText("Marca antes alguna propuesta.")
            return
        stars = [x for x in items if x["kind"] == "star"]
        res = self.ctrl.apply_context_effects(items, self._sound_media({x["effect"] for x in stars}))
        if res is None:
            return
        for x in stars:
            EM.learn(x["effect"], x.get("star_kind", "elegido"), x.get("vec"), True)
        self._ctx_drop(items)
        self.ctx_status.setText(f"✓ Puesto{'s' if res != 1 else ''} {res} efecto{'s' if res != 1 else ''} "
                                "(un solo Ctrl+Z para deshacer).")

    def ctx_reject(self):
        from ..ai import effect_memory as EM
        rows = self._ctx_rows(True) or list(range(len(self.ctx_props)))
        items = [self.ctx_props[i] for i in rows if 0 <= i < len(self.ctx_props)]
        for x in items:
            if x["kind"] == "star":
                EM.learn(x["effect"], x.get("star_kind", "elegido"), x.get("vec"), False)
        self._ctx_drop(items)
        if items:
            self.ctx_status.setText(f"✗ {len(items)} descartada(s).")

    # ------------------------------------------------------------ sonidos
    def reload(self):
        """Rellena la lista de sonidos de este panel y la de 🔊 Sonidos en Medios (si está abierta)."""
        vivos = []
        for tree in [self.tree] + list(getattr(self, "_otros_arboles", [])):
            try:
                self._llenar(tree)
                buscador = self.search if tree is self.tree else getattr(tree, "_buscador", None)
                if buscador is not None and buscador.text().strip():
                    filtrar_arbol(tree, buscador.text())
                if tree is not self.tree:
                    vivos.append(tree)
            except RuntimeError:                       # (una lista ya cerrada)
                pass
        self._otros_arboles = vivos

    def registrar_arbol(self, tree):
        """Otra lista de sonidos (p. ej. 🔊 Sonidos en Medios) que se llena y se actualiza igual que esta."""
        self._otros_arboles = list(getattr(self, "_otros_arboles", [])) + [tree]
        self._llenar(tree)

    def _llenar(self, tree):
        tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}

        def group(name):
            if name not in groups:
                it = QTreeWidgetItem([name, ""])
                it.setFlags(it.flags() & ~Qt.ItemIsDragEnabled)
                tree.addTopLevelItem(it)
                it.setExpanded(True)
                groups[name] = it
            return groups[name]
        for key, (name, cat, desc) in sfx.CATALOG.items():
            it = QTreeWidgetItem([name, desc])
            it.setData(0, Qt.UserRole, "sfx:" + key)
            it.setToolTip(1, desc)
            group("Reclaimer · " + cat).addChild(it)
        from ..core.paths import user_dir
        web = str(user_dir() / "Sonidos de internet")       # (lo guardado con 🌐 Buscar en internet)
        if os.path.isdir(web):
            for root, _dirs, files in os.walk(web):
                for f in sorted(files):
                    if f.lower().endswith(AUDIO_EXT):
                        rel = os.path.relpath(root, web)
                        it = QTreeWidgetItem([os.path.splitext(f)[0].rsplit(" [", 1)[0], "" if rel == "." else rel])
                        it.setData(0, Qt.UserRole, "file:" + os.path.join(root, f))
                        group("🌐 De internet").addChild(it)
        folder = str(self.settings.value("efectos/carpeta", ""))
        if folder and os.path.isdir(folder):
            n = 0
            for root, _dirs, files in os.walk(folder):
                for f in sorted(files):
                    if f.lower().endswith(AUDIO_EXT):
                        rel = os.path.relpath(root, folder)
                        it = QTreeWidgetItem([os.path.splitext(f)[0], "" if rel == "." else rel])
                        it.setData(0, Qt.UserRole, "file:" + os.path.join(root, f))
                        group("Mi carpeta · " + os.path.basename(folder)).addChild(it)
                        n += 1
                        if n >= 3000:
                            return

    def _filter(self, text: str):
        filtrar_arbol(self.tree, text)

    def _path(self, ref: str) -> str:
        return sfx.path_for(ref[4:]) if ref.startswith("sfx:") else ref[5:]

    def _preview(self, it, _col=0):
        ref = it.data(0, Qt.UserRole) if it else None
        if not ref:
            return
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(self._path(ref)))
        self.player.play()

    def media_for(self, ref: str) -> str | None:
        """Importa el sonido a la biblioteca (categoría «Efectos») si hace falta y devuelve su id."""
        path = os.path.normcase(os.path.abspath(self._path(ref)))
        for m in self.ctrl.project.media.values():
            if os.path.normcase(os.path.abspath(m.path)) == path:
                return m.id
        ids = self.ctrl.import_paths([path])
        if ids:
            props = {"category": "Efectos"}
            try:   # un sonido corto se lee al instante: así se puede soltar en la timeline enseguida
                from ..core import media as media_tools
                info = media_tools.probe(path)
                props.update(duration=info["duration"], has_audio=True, channels=info["channels"], probed=True)
            except Exception:  # noqa: BLE001
                pass
            self.ctrl.set_media_props(ids, **props)
            return ids[0]
        return None

    def add_at_playhead(self, it):
        ref = it.data(0, Qt.UserRole) if it else None
        if not ref:
            self.ctrl.message.emit("Elige antes un efecto de la lista (doble clic lo pone donde está el cabezal).")
            return
        mid = self.media_for(ref)
        if not mid:
            self.ctrl.message.emit("No encuentro el archivo de ese efecto en el disco: no se puede poner.")
            return
        p = self.ctrl.project
        if p.media[mid].duration <= 0:   # recién importado: esperar a leer su duración
            from PySide6.QtCore import QTimer
            QTimer.singleShot(400, lambda: self.add_at_playhead(it))
            return
        tid = self.ctrl.ensure_role_track("efectos")     # su propia pista (nunca encima de tu voz)
        created = self.ctrl.add_media([mid], tid, self.engine.time)   # (entra a la mitad: lo hace add_media)
        if isinstance(created, list):
            self.timeline.set_selection(created)

    def open_sound_search(self, texto: str = ""):
        """🌐 Buscar un sonido en internet (parte solo local: ui/sounds_internet.py)."""
        from . import sounds_internet
        self._sound_dlg = sounds_internet.abrir(self, texto or self.search.text().strip())

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de tus efectos de sonido",
                                             str(self.settings.value("efectos/carpeta", "")))
        if d:
            self.settings.setValue("efectos/carpeta", d)
            self.reload()

    # --------------------------------------------------- efectos de imagen
    def _targets(self):
        p = self.ctrl.project
        out = []
        for cid in self.timeline.selected:
            c = p.clips.get(cid)
            tr = p.track(c.track_id) if c else None
            if c is not None and c.text is None and tr is not None and tr.kind != TRACK_AUDIO:
                out.append(c)
        return out

    def toggle_look(self, key: str, value: float, label: str):
        clips = self._targets()
        if not clips:
            self.look_status.setText("Selecciona antes uno o varios clips de video o imagen en la timeline.")
            from .nudge import nudge_for
            nudge_for(self.look_status.text())
            return
        on = not all((c.fx or {}).get(key) for c in clips)
        changes = {}
        for c in clips:
            fx = dict(c.fx or {})
            if on:
                fx[key] = value
            else:
                fx.pop(key, None)
            changes[c.id] = {"fx": fx or None}
        n = self.ctrl.batch_clip_props(changes, f"Efecto: {label.split(' ', 1)[-1]}")
        self._update_look_status()
        if n:
            self.ctrl.message.emit(f"{'Puesto' if on else 'Quitado'} «{label.split(' ', 1)[-1]}» en {n} clip(s).")

    def add_chroma(self):
        """🟩 Quita el fondo de color de los clips seleccionados (el color se detecta en el fotograma actual)."""
        from ..core import chroma as CK
        from ..core import media as media_tools
        clips = [c for c in self._targets() if c.text is None]
        if not clips:
            self.look_status.setText("Selecciona antes el clip (o la imagen) con el fondo verde.")
            from .nudge import nudge_for
            nudge_for(self.look_status.text())
            return
        p = self.ctrl.project
        changes, colors = {}, []
        no_screen = False
        for c in clips:
            m = p.media_of(c)
            if m is None:
                continue
            t = self.engine.time if c.start <= self.engine.time < c.end else c.start + c.duration / 2
            img = media_tools.frame_rgb(m.path, c.src_at(t - c.start), 320) if m.kind != "image" else None
            if img is None and m.kind == "image":
                import cv2
                import numpy as np
                data = np.fromfile(m.path, np.uint8)
                bgr = cv2.imdecode(data, cv2.IMREAD_COLOR) if len(data) else None
                img = None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            col = CK.detect(img) if img is not None else CK.DEFAULT["color"]
            if img is not None and not CK.has_screen(img, col):
                no_screen = True        # este clip no tiene fondo de color: el croma no quitaría nada
                continue
            colors.append(col)
            changes[c.id] = {"fx": dict(c.fx or {}, chroma={"color": col, "similarity": round(self.ck_sim.value(), 3),
                                                           "blend": round(self.ck_blend.value(), 3), "spill": True})}
        n = self.ctrl.batch_clip_props(changes, "🟩 Pantalla verde") if changes else 0
        if n:
            self.look_status.setText(f"🟩 Fondo de color quitado en {n} clip(s) (color detectado {colors[0]}). "
                                     "Si queda verde, sube la Tolerancia; si se come al sujeto, bájala.")
        if no_screen:
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "Pantalla verde",
                "Ese clip no tiene detrás un fondo verde (o de un solo color): la pantalla verde no puede quitar "
                "nada ahí.\n\nPara quitar el fondo de CUALQUIER video (gameplay, cinemáticas…) está «✂ Recortar "
                "sujeto»: marcas al personaje y la IA lo separa en todo el clip.\n\n¿Lo abro ahora?")
            if r == QMessageBox.Yes and hasattr(self.window(), "open_subject_cut"):
                self.window().open_subject_cut(clips[0].id)

    def add_fill(self):
        """▦ Relleno en los clips seleccionados (de video o imagen)."""
        from ..core import fill as FILL
        clips = [c for c in self._targets() if c.text is None]
        if not clips:
            self.look_status.setText("Selecciona en la línea de tiempo los clips a los que quieres poner relleno.")
            return
        if self.ctrl.set_fill([c.id for c in clips], dict(FILL.DEFAULT)):
            self.look_status.setText("▦ Relleno puesto: ajústalo en el Inspector (⤧ Transformar → Relleno).")

    def clear_fill(self):
        clips = self._targets()
        if clips:
            self.ctrl.set_fill([c.id for c in clips], None, "▦ Quitar relleno")

    def add_motion_key(self):
        """👤 Aprende el fondo vacío del clip seleccionado (en segundo plano) y quita lo que no se mueve."""
        from ..core import motion_key as MKY
        from .task_window import manager
        clips = [c for c in self._targets() if c.text is None and self.ctrl.project.media_of(c) is not None
                 and self.ctrl.project.media_of(c).kind == "video"]
        if not clips:
            self.look_status.setText("Selecciona antes el clip de video (con la cámara fija) del que quieres quitar "
                                     "el fondo.")
            from .nudge import nudge_for
            nudge_for(self.look_status.text())
            return
        c = clips[0]
        m = self.ctrl.project.media_of(c)
        a, b = c.source_in, c.source_in + max(0.5, c.src_len)
        cid, thr = c.id, round(self.mk_thr.value(), 3)

        def work(progress, cancelled):
            return MKY.learn_plate(m.path, a, b, lambda f: progress(f, f"👤 Aprendiendo el fondo vacío · "
                                                                      f"{int(f * 100)} %"), cancelled)

        def done(res):
            plate, moving = res
            if plate is None:
                self.look_status.setText(f"👤 La cámara se mueve en ese clip ({int(moving * 100)} % de la imagen "
                                         "cambia): así no se puede separar el fondo. Usa la pantalla verde o "
                                         "un clip con la cámara fija.")
                return
            cc = self.ctrl.project.clips.get(cid)
            if cc is None:
                return
            fx = dict(cc.fx or {}, motion_key={"plate": plate, "thr": thr, "soft": 0.06})
            self.ctrl.batch_clip_props({cid: {"fx": fx}}, "👤 Quitar el fondo quieto")
            self.look_status.setText("👤 Fondo quieto quitado: si queda fondo, sube la Tolerancia; si se come a la "
                                     "persona, bájala.")
        manager().start("👤 Quitar el fondo quieto", work, done, lambda msg: self.look_status.setText("✗ " + msg))

    def _mkey_set(self, **props):
        changes = {}
        for c in self._targets():
            mk = (c.fx or {}).get("motion_key")
            if mk:
                changes[c.id] = {"fx": dict(c.fx, motion_key=dict(mk, **props))}
        if changes:
            self.ctrl.batch_clip_props(changes, "Ajustar fondo por movimiento")

    def clear_motion_key(self):
        changes = {c.id: {"fx": {k: v for k, v in (c.fx or {}).items() if k != "motion_key"} or None}
                   for c in self._targets() if (c.fx or {}).get("motion_key")}
        if changes:
            self.ctrl.batch_clip_props(changes, "Quitar fondo por movimiento")

    def _chroma_set(self, **props):
        changes = {}
        for c in self._targets():
            ch = (c.fx or {}).get("chroma")
            if ch:
                changes[c.id] = {"fx": dict(c.fx, chroma=dict(ch, **props))}
        if changes:
            self.ctrl.batch_clip_props(changes, "Ajustar pantalla verde")

    def clear_chroma(self):
        changes = {c.id: {"fx": {k: v for k, v in (c.fx or {}).items() if k != "chroma"} or None}
                   for c in self._targets() if (c.fx or {}).get("chroma")}
        if changes:
            self.ctrl.batch_clip_props(changes, "Quitar pantalla verde")

    def add_region(self, shape: str):
        """◌ Una zona desenfocada (cuadro o círculo) en el centro de cada clip seleccionado."""
        from ..core import effects as E_
        from ..core import transform
        clips = self._targets()
        if not clips:
            self.look_status.setText("Selecciona antes el clip (o la imagen) donde quieres desenfocar una zona.")
            from .nudge import nudge_for
            nudge_for(self.look_status.text())
            return
        p = self.ctrl.project
        changes = {}
        for c in clips:
            box = c.layout or transform.FULL
            r = E_.new_region(shape, box["w"] * p.width, box["h"] * p.height)
            r["amount"] = round(self.region_amount.value(), 2)
            fx = dict(c.fx or {})
            fx["blur_regions"] = list(fx.get("blur_regions") or []) + [r]
            changes[c.id] = {"fx": fx}
        n = self.ctrl.batch_clip_props(changes, "Desenfoque en zona")
        if n:
            self.look_status.setText(f"◌ Zona desenfocada añadida en {n} clip(s): arrástrala en el visor (dentro = "
                                     "mover · esquina naranja = tamaño).")

    def _region_amount(self, v: float):
        self.settings.setValue("efectos/zona_intensidad", round(v, 2))
        changes = {}
        for c in self._targets():
            regs = (c.fx or {}).get("blur_regions")
            if regs:
                fx = dict(c.fx)
                fx["blur_regions"] = [dict(r, amount=round(v, 2)) for r in regs]
                changes[c.id] = {"fx": fx}
        if changes:
            self.ctrl.batch_clip_props(changes, "Fuerza del desenfoque")

    def clear_regions(self):
        changes = {}
        for c in self._targets():
            if (c.fx or {}).get("blur_regions"):
                fx = {k: v for k, v in c.fx.items() if k != "blur_regions"}
                changes[c.id] = {"fx": fx or None}
        if changes:
            self.ctrl.batch_clip_props(changes, "Quitar desenfoque en zona")

    def clear_looks(self):
        clips = self._targets()
        if clips:
            # Solo los efectos de esta lista (antes se borraba TODO: también la transición, la pantalla verde, el
            # recorte de sujeto, el estabilizado…)
            looks = {k for k, _t, _v, _h in LOOKS} | {"shake_amp"}
            changes = {}
            for c in clips:
                rest = {k: v for k, v in (c.fx or {}).items() if k not in looks}
                changes[c.id] = {"fx": rest or None}
            self.ctrl.batch_clip_props(changes, "Quitar efectos")
            self._update_look_status()

    def _update_look_status(self):
        clips = self._targets()
        if not clips:
            # Solo texto: al deseleccionar no se resalta nada (el aviso sale al pulsar una acción sin selección)
            self.look_status.setText("Selecciona clips en la timeline para ponerles efectos.")
            return
        names = {k: t.split(" ", 1)[-1] for k, t, _v, _h in LOOKS}
        on = sorted({names[k] for c in clips for k in (c.fx or {}) if k in names})
        self.look_status.setText(f"{len(clips)} clip(s) seleccionados · efectos: " + (", ".join(on) or "ninguno") +
                                 "\n(El grano, el glitch y los tonos se ven al exportar; el resto, también en el visor.)")

    # ------------------------------------------------------------- transiciones
    def apply_transition(self, remove: bool = False):
        ids = self.ctrl.transition_targets(sorted(self.timeline.selected), self.engine.time)
        it = self.trans_list.currentItem()
        key = None if remove else (it.data(Qt.UserRole) if it else "fade")
        dur = None if (self.trans_auto.isChecked() and not remove) else self.trans_dur.value()
        n = self.ctrl.set_transition(ids, key, dur)
        if isinstance(n, int):
            self.trans_status.setText(("✓ Quitada" if remove else f"✓ «{it.text()}» puesta") +
                                      (f" en {n} cortes." if n > 1 else "."))

    def view_transition(self):
        from .jobs import BackgroundJob
        from .transition_preview import TransitionPreview, render_cut
        if self._trans_job is not None:
            return
        ids = self.ctrl.transition_targets(sorted(self.timeline.selected), self.engine.time)
        p = self.ctrl.project
        c = p.clips.get(ids[0]) if ids else None
        if c is None:
            self.trans_status.setText("Pon el cabezal cerca de un corte entre dos clips (o selecciona uno).")
            return
        t = c.start
        self.trans_status.setText("Preparando la vista previa…")
        self.b_view.setEnabled(False)
        self._trans_job = BackgroundJob(lambda _p, _c: render_cut(p, t), self)

        def done(path):
            self._trans_job = None
            self.b_view.setEnabled(True)
            self.trans_status.setText("")
            self._trans_dialog = TransitionPreview(path, "Transición", self.window())
            self._trans_dialog.show()

        def failed(msg):
            self._trans_job = None
            self.b_view.setEnabled(True)
            self.trans_status.setText("✗ " + msg)
        self._trans_job.done.connect(done)
        self._trans_job.failed.connect(failed)
        self._trans_job.start()
