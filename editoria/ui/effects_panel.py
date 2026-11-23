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
                               QLabel, QLineEdit, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import diseno as D
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



# 🎨 Filtros = el aspecto y el color de todo el clip; lo demás de LOOKS es ✦ Efecto (se mueve o cambia con el tiempo)
FILTROS = ("bw", "vignette", "grain", "blur", "oldfilm", "warm", "cold", "rgbsplit", "glow", "punchy", "vhs", "duotone")


class _Etiquetas:
    """Un aviso que sale a la vez en varias etiquetas (las columnas Efectos, Filtros y Figuras: cada una el suyo)."""

    def __init__(self, *labels):
        self.labels = labels

    def setText(self, t: str):
        for lb in self.labels:
            lb.setText(t)

    def text(self) -> str:
        return self.labels[0].text()

    def setToolTip(self, t: str):              # noqa: N802  (la explicación, en el tooltip de todas)
        for lb in self.labels:
            lb.setToolTip(t)

    def toolTip(self) -> str:                  # noqa: N802
        return self.labels[0].toolTip()


VOLUMEN_SONIDOS = 0.5     # 🔊 los efectos de sonido entran a la mitad (el usuario: «suenan muy fuertes»)

def _hay_sonidos_internet() -> bool:
    """¿Está la parte solo local de 🌐 buscar sonidos? (en la versión publicada no viene)."""
    try:
        from . import sounds_internet  # noqa: F401
        return True
    except ImportError:
        return False

class _ConColumnas:
    """Elementos de la lista de sonidos con la forma de usar del árbol de antes: text(0) = el nombre, text(1) = «para
    qué» (o su subcarpeta) y data(0, rol) = data(rol)."""

    def text(self, col: int = 0) -> str:
        if col == 0:
            return QListWidgetItem.text(self)
        return str(QListWidgetItem.data(self, D.ROL_DETALLE) or "")

    def data(self, *a):
        return QListWidgetItem.data(self, a[-1])


class _ItemSonido(_ConColumnas, QListWidgetItem):
    pass


class _GrupoSonidos(_ConColumnas, QListWidgetItem):
    """La cabecera de un grupo («Reclaimer · Golpes»…): childCount()/child(k) como el grupo del árbol de antes."""

    def __init__(self, texto: str):
        super().__init__(texto)
        self._hijos: list = []

    def childCount(self) -> int:               # noqa: N802
        return len(self._hijos)

    def child(self, k: int):
        return self._hijos[k] if 0 <= k < len(self._hijos) else None

    def isExpanded(self) -> bool:              # noqa: N802
        return not QListWidgetItem.data(self, D.ROL_PLEGADO)

    def setExpanded(self, on: bool):           # noqa: N802
        lw = self.listWidget()
        if lw is not None:
            lw.plegar(self, not on)


class _SoundTree(D.ListaAdaptable):
    """Lista de sonidos que se puede arrastrar a la timeline: en 1, 2 o 3 columnas según el ancho (diseno.ListaAdaptable),
    con sus grupos plegables. Se usa como el árbol de antes (topLevelItem(i).child(k), data(0, rol))."""

    def __init__(self, panel, clave: str = ""):
        super().__init__(clave=clave, ancho_min=150)
        self.panel = panel
        self._grupos_l: list = []
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):
        ids = [self.panel.media_for(it.data(0, Qt.UserRole)) for it in items if it.data(0, Qt.UserRole)]
        md = QMimeData()
        md.setData(MEDIA_MIME, ",".join(i for i in ids if i).encode())
        return md

    def clear(self):
        self._grupos_l = []
        super().clear()

    def topLevelItemCount(self) -> int:        # noqa: N802
        return len(self._grupos_l)

    def topLevelItem(self, i: int):            # noqa: N802
        return self._grupos_l[i] if 0 <= i < len(self._grupos_l) else None


def filtrar_arbol(tree, text: str):
    """Deja a la vista solo los sonidos cuyo nombre o descripción contienen el texto (y sus grupos)."""
    if isinstance(tree, D.ListaAdaptable):
        tree.filtrar(text)
        return
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
        self.tree = _SoundTree(fx, clave="sonidos_medios")
        self.tree.setToolTip("Clic = escuchar · doble clic = poner en el cabezal · o arrástralo a la línea de tiempo.")
        self.tree.itemClicked.connect(lambda it: fx._preview(it))
        self.tree.itemDoubleClicked.connect(lambda it: fx.add_at_playhead(it) if it is not None and
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


class _FxList(D.ListaAdaptable):
    """Lista de efectos (⭐ mis efectos, transiciones) que se arrastra encima de un clip de la timeline. En 1, 2 o 3
    columnas según el ancho (diseno.ListaAdaptable); mide lo que su contenido, hasta alto_max px."""

    def __init__(self, prefix: str = "", clave: str = "", alto_max: int | None = None):
        super().__init__(clave=clave, ancho_min=170, ajustar_alto=True, alto_max=alto_max)
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
        self.mem_list = _FxList(alto_max=120)
        FXP.attach_list(self.mem_list, lambda it: FXP.split_key(it.data(Qt.UserRole) or ""))
        self.mem_list.setToolTip("Arrastra un efecto encima de un clip de la línea de tiempo para ponérselo "
                                 "(si el clip está seleccionado con otros, a todos).\nDoble clic: en los clips "
                                 "seleccionados.")
        self.mem_list.itemDoubleClicked.connect(lambda _it: self.retarget_current())
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
        self.tree = _SoundTree(self, clave="sonidos")
        self.tree.setMinimumHeight(260)
        self.tree.itemClicked.connect(lambda it: self._preview(it))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._sound_menu)
        self.tree.itemDoubleClicked.connect(lambda it: self.add_at_playhead(it) if it is not None and
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

        # --- Efectos de imagen --- (18/11, por categorías: ✦ Efectos = lo que se mueve o cambia con el tiempo y quitar
        # el fondo · 🎨 Filtros = el aspecto y el color de todo el clip · ▭ Figuras geométricas = tapar y figuras)
        g2 = QGroupBox("✦ Efectos (para los clips seleccionados)")
        grid = QGridLayout(g2)
        gf = QGroupBox("🎨 Filtros: aspecto y color (para los clips seleccionados)")
        gridf = QGridLayout(gf)
        n_e = n_f = 0
        for key, text, val, tip_ in LOOKS:
            b = _FxButton(text, "look:" + key)
            FXP.attach(b, "look", key)              # 🎞 icono con el efecto y, al pasar el ratón, en movimiento
            b.setToolTip(tip_ + "\nClic: poner o quitar en los clips seleccionados.\n"
                                "Arrastrar: suéltalo encima de un clip de la línea de tiempo.\n"
                                "Clic derecho: ⭐ añadir a mis efectos para la IA.")
            b.clicked.connect(lambda _=False, kk=key, vv=val, tt=text: self.toggle_look(kk, vv, tt))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda _pos, kk=key, bb=b: self._star_menu("look:" + kk, bb.mapToGlobal(_pos)))
            if key in FILTROS:
                gridf.addWidget(b, n_f // 2, n_f % 2)
                n_f += 1
            else:
                grid.addWidget(b, n_e // 2, n_e % 2)
                n_e += 1
        fila = (n_e + 1) // 2
        b_clear = QPushButton("✕ Quitar los efectos")
        b_clear.setToolTip("Quita estos efectos de los clips seleccionados (los filtros, la transición y lo demás se "
                           "quedan)")
        b_clear.clicked.connect(lambda: self.clear_looks(lambda k: k not in FILTROS))
        grid.addWidget(b_clear, fila, 0, 1, 2)
        # (22/11, el usuario: «desordenados»: etiquetas de distinto ancho, cajas sueltas y × desalineadas) → UNA fila
        # del sistema de diseño por efecto (etiqueta en su columna fija · acción · × de quitar, siempre en la misma
        # columna) y sus ajustes debajo con ValorDeslizable, con el borde derecho alineado con el de la acción
        caja_fx = QWidget()
        vfx = QVBoxLayout(caja_fx)
        vfx.setContentsMargins(0, D.px(D.M1), 0, 0)
        vfx.setSpacing(D.px(D.M1))
        vfx.addWidget(D.TituloSeccion("Fondo, relleno y sombra"))
        # 🟩 Pantalla verde: un clic (el color se detecta solo) y dos ajustes
        tip_ck = ("Quita el fondo de color (verde, azul…) del clip seleccionado: el color se detecta solo. "
                  "Tolerancia = cuánto color se quita · Suavidad = borde suave.")
        self.b_chroma = QPushButton("Quitar fondo de color")
        self.b_chroma.setToolTip(tip_ck)
        self.b_chroma.clicked.connect(self.add_chroma)
        vfx.addWidget(self._fila_efecto("Pantalla verde", self.b_chroma, tip_ck,
                                        "Quitar la pantalla verde de los clips seleccionados", self.clear_chroma))
        self.ck_sim = D.ValorDeslizable(0.02, 0.4, 0.01, 2)
        self.ck_sim.setValue(0.11)
        self.ck_sim.valueChanged.connect(lambda v: self._chroma_set(similarity=round(v, 3)))
        vfx.addWidget(self._fila_ajuste("Tolerancia", self.ck_sim, "Pantalla verde: cuánto color se quita (si "
                                        "queda verde, súbela; si se come al sujeto, bájala)", "Ajustar pantalla verde"))
        self.ck_blend = D.ValorDeslizable(0.0, 0.4, 0.02, 2)
        self.ck_blend.setValue(0.07)
        self.ck_blend.valueChanged.connect(lambda v: self._chroma_set(blend=round(v, 3)))
        vfx.addWidget(self._fila_ajuste("Suavidad", self.ck_blend, "Pantalla verde: lo suave que queda el borde",
                                        "Ajustar pantalla verde"))
        # 👤 Quitar el fondo quieto (sin pantalla verde): cámara fija, lo que no se mueve se va
        tip_mk = ("Fondo por movimiento, sin pantalla verde: con la CÁMARA FIJA (facecam, plano quieto) se aprende cómo "
                  "es el fondo vacío y se quita todo lo que no se mueve. Si la cámara se mueve, te avisa.")
        self.b_mkey = QPushButton("Quitar el fondo quieto")
        self.b_mkey.setToolTip(tip_mk)
        self.b_mkey.clicked.connect(self.add_motion_key)
        vfx.addWidget(self._fila_efecto("Fondo quieto", self.b_mkey, tip_mk,
                                        "Quitar «fondo por movimiento» de los clips seleccionados",
                                        self.clear_motion_key))
        self.mk_thr = D.ValorDeslizable(0.02, 0.5, 0.02, 2)
        self.mk_thr.setValue(0.10)
        self.mk_thr.valueChanged.connect(lambda v: self._mkey_set(thr=round(v, 3)))
        vfx.addWidget(self._fila_ajuste("Tolerancia", self.mk_thr, "Fondo quieto: cuánto se quita (si queda fondo, "
                                        "súbela; si se come a la persona, bájala)", "Ajustar fondo por movimiento"))
        # ▦ Relleno (como el de Resolve): lo vacío alrededor del clip, con la propia imagen ampliada y desenfocada
        tip_rl = ("Lo que queda vacío alrededor del clip (al aplastarlo, hacerlo pequeño o si no tiene la forma de la "
                  "pantalla) se llena con la MISMA imagen ampliada y desenfocada. Ajustes en el Inspector "
                  "(⤧ Transformar).")
        self.b_fill = QPushButton("Rellenar con la imagen")
        self.b_fill.setToolTip(tip_rl)
        self.b_fill.clicked.connect(self.add_fill)
        vfx.addWidget(self._fila_efecto("Relleno", self.b_fill, tip_rl,
                                        "Quitar el relleno de los clips seleccionados", self.clear_fill))
        # 🌑 Sombra (21/11, el «Drop Shadow» de Resolve): pequeña y suave, sigue la forma de un PNG recortado; sus
        # ajustes (color, fuerza, ángulo, distancia, desenfoque) en Inspector → Efectos → Sombra
        tip_sb = ("Una sombra pequeña y suave detrás de los clips elegidos (video o imagen) para darles profundidad, "
                  "como el «Drop Shadow» de Resolve: sigue la forma de la imagen (un PNG recortado da su silueta). Se "
                  "ajusta en el Inspector (Efectos → Sombra). Ctrl+Z la quita.")
        self.b_sombra = QPushButton("Poner sombra")
        self.b_sombra.setIcon(D.icono("sombra"))
        self.b_sombra.setToolTip(tip_sb)
        self.b_sombra.clicked.connect(self.add_shadow)
        vfx.addWidget(self._fila_efecto("Sombra", self.b_sombra, tip_sb,
                                        "Quitar la sombra de los clips seleccionados", self.clear_shadow))
        grid.addWidget(caja_fx, fila + 1, 0, 1, 2)
        st_e = QLabel("")
        st_e.setObjectName("dim")
        st_e.setWordWrap(True)
        grid.addWidget(st_e, fila + 2, 0, 1, 2)
        # 🎨 Filtros: quitar los suyos y el color del clip (Inspector → Color: ruedas, curvas, LUT .cube)
        fila_f = (n_f + 1) // 2
        b_clear_f = QPushButton("✕ Quitar los filtros")
        b_clear_f.setToolTip("Quita estos filtros de los clips seleccionados (los efectos se quedan)")
        b_clear_f.clicked.connect(lambda: self.clear_looks(lambda k: k in FILTROS))
        gridf.addWidget(b_clear_f, fila_f, 0, 1, 2)
        self.b_color = QPushButton("🎨 Color y LUT del clip (Inspector → Color)…")
        self.b_color.setToolTip("Corrección de color del clip elegido: exposición, contraste, temperatura, ruedas "
                                "Lift/Gamma/Gain, curvas, LUT .cube y ✨ color automático (en el Inspector).")
        self.b_color.clicked.connect(self._abrir_color)
        gridf.addWidget(self.b_color, fila_f + 1, 0, 1, 2)
        st_f = QLabel("")
        st_f.setObjectName("dim")
        st_f.setWordWrap(True)
        gridf.addWidget(st_f, fila_f + 2, 0, 1, 2)
        # ▭ Figuras geométricas: tapar (censurar) una zona y figuras de color
        gg, st_g = self._build_shapes_group()
        set_help(gg, "desenfoque_zona")
        set_help(gf, "efectos_imagen")
        self.look_status = _Etiquetas(st_e, st_f, st_g)
        lay.addWidget(set_help(g2, "efectos_imagen"))

        # --- Transiciones ---
        from ..core import transitions as TR
        from PySide6.QtWidgets import QDoubleSpinBox
        gt = QGroupBox("⧉ Transiciones (entre dos clips pegados)")
        vt = QVBoxLayout(gt)
        self.trans_list = _FxList("trans:", clave="transiciones", alto_max=self.ALTO_TRANS)
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
        gn = self._build_note_group()
        timeline.note_dropped.connect(self.add_note_at)
        untitle(g0, g1, g2, gt, g4, gn, gf, gg)
        # (18/11, el usuario: Efectos SOLO para lo visual, por categorías de izquierda a derecha; en la página ✦ Efectos
        # cada categoría va en su columna —sacar_categorias— y aquí, en Editar, una debajo de otra)
        self.cats: dict[str, QWidget] = {}
        self._huecos: dict[str, QWidget] = {}
        self.tabs_fx = tabbed([("Efectos de imagen", [g2]), ("📝 Nota de texto", [gn]), ("⭐ Para la IA", [g0]),
                               ("✨ Lo que dices", [g4])], name="subtabs_fx", clave="efectos_fx")
        for clave, ws in (("trans", [gt]), ("efectos", [self.tabs_fx]), ("filtros", [gf]), ("figuras", [gg])):
            cat = QWidget()
            cv = QVBoxLayout(cat)
            cv.setContentsMargins(0, 0, 0, 0)
            for w_ in ws:
                cv.addWidget(w_)
            if clave != "efectos":
                cv.addStretch(1)
            hueco = QWidget()                     # (el sitio de la categoría aquí: vuelve a él al salir de la página)
            hv = QVBoxLayout(hueco)
            hv.setContentsMargins(0, 0, 0, 0)
            hv.addWidget(cat)
            self.cats[clave], self._huecos[clave] = cat, hueco
        self._sonidos = [g1, g3]                  # (🔊 Sonidos: los saca la ventana a su panel de 🎚 Audio)
        self.tabs = tabbed([("⧉ Transiciones", [self._huecos["trans"]]), ("✦ Efectos", [self._huecos["efectos"]], True),
                            ("🎨 Filtros", [self._huecos["filtros"]]),
                            ("▭ Figuras geométricas", [self._huecos["figuras"]]),
                            ("🔊 Sonidos", [g1, g3])], clave="efectos2")
        self.tabs.setToolTip("")
        # (20/11, sin huecos: «Efectos» lleva dentro sus propias secciones; sin el margen de abajo de las dos, tras la
        #  última subsección plegada queda la misma separación que entre las demás cabeceras —antes, 12 px de más—)
        self.tabs_fx.layout().setContentsMargins(0, 2, 0, 0)
        _i_fx = self._indice_de("✦ Efectos")
        if _i_fx >= 0 and self.tabs.widget(_i_fx).layout() is not None:
            _m = self.tabs.widget(_i_fx).layout().contentsMargins()
            self.tabs.widget(_i_fx).layout().setContentsMargins(_m.left(), _m.top(), _m.right(), 0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.tabs)
        # (20/11, ↔ con mucho ancho: Transiciones | Efectos lado a lado, cada una con su barra y 🔗; ver _revisar_modo)
        self._outer = outer
        self._lado: D.ColumnasEnlazadas | None = None
        self._modo_ancho = False
        from PySide6.QtCore import QTimer as _QT
        self._t_modo = _QT(self)
        self._t_modo.setSingleShot(True)
        self._t_modo.setInterval(0)
        self._t_modo.timeout.connect(self._revisar_modo)
        content.deleteLater()
        timeline.selection_changed.connect(lambda _ids: self._update_look_status())
        timeline.selection_changed.connect(lambda _ids: self._note_load())
        ctrl.project_changed.connect(self._note_load)
        self.reload()

    # ------------------------------------------------------- ↔ lado a lado con mucho ancho
    ALTO_TRANS = 300                  # alto máximo de la lista de transiciones una debajo de otra (lado a lado, todo)
    ANCHO_LADO, ANCHO_LADO_SALIR = 720, 680     # (px a 100 %: a partir de aquí, lado a lado; por debajo, una sobre otra)

    def resizeEvent(self, ev):                 # noqa: N802
        super().resizeEvent(ev)
        if ev.oldSize().width() != ev.size().width():
            self._t_modo.start()

    def _revisar_modo(self):
        w = self.width()
        quiero = w >= D.px(self.ANCHO_LADO_SALIR if self._modo_ancho else self.ANCHO_LADO)
        if quiero != self._modo_ancho:
            self.poner_lado_a_lado(quiero)

    def _indice_trans(self) -> int:
        return self._indice_de("⧉ Transiciones")

    def _indice_de(self, titulo: str) -> int:
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == titulo:
                return i
        return -1

    # (lado a lado, debajo de las transiciones van 🎨 Filtros y ▭ Figuras: la columna izquierda no queda medio vacía)
    BAJO_TRANS = (("filtros", "🎨 Filtros"), ("figuras", "▭ Figuras geométricas"))

    def _columna_izquierda(self):
        """La columna izquierda del modo lado a lado (una vez): [transiciones] + Filtros + Figuras, plegables y con su
        propio recuerdo («secciones/efectos_lado/…», sin tocar el de una debajo de otra)."""
        if getattr(self, "_col_izq", None) is not None:
            return self._col_izq
        from .tabs import Section
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self._secs_lado: dict = {}
        for clave, titulo in self.BAJO_TRANS:
            k = self._indice_de(titulo)
            cuerpo = QWidget()
            cv = QVBoxLayout(cuerpo)
            cv.setContentsMargins(0, 0, 0, 0)
            abierta = self.tabs.secciones()[k].is_open() if k >= 0 else False
            sec = Section(self.tabs.secciones()[k].head.text() if k >= 0 else titulo, cuerpo, abierta,
                          f"secciones/efectos_lado/{clave}")
            v.addWidget(sec)
            self._secs_lado[clave] = sec
        self._col_izq = col
        return col

    def poner_lado_a_lado(self, on: bool):
        """Con mucho ancho, ⧉ Transiciones | ✦ Efectos (y lo demás de este panel) lado a lado, cada parte con su barra
        de desplazamiento y 🔗 para moverlas juntas (diseno.ColumnasEnlazadas). Sin tanto ancho, una debajo de otra
        como siempre."""
        i = self._indice_trans()
        hueco = self._huecos["trans"]
        if on == self._modo_ancho or i < 0:
            return
        self._modo_ancho = on
        if on:
            if self._lado is None:
                self._lado = D.ColumnasEnlazadas("efectos/lado_a_lado", ["Transiciones", "Efectos"])
                self._outer.addWidget(self._lado)
                self._lado.poner_contenido(0, self._columna_izquierda())
            col = self._columna_izquierda()
            col.layout().insertWidget(0, hueco)       # (la categoría ya lleva su hueco debajo: arriba del todo)
            hueco.show()
            for clave, titulo in self.BAJO_TRANS:
                k = self._indice_de(titulo)
                sec = self._secs_lado[clave]
                sec.setVisible(k >= 0)
                if k >= 0:
                    sec.body.layout().addWidget(self._huecos[clave])
                    self._huecos[clave].show()
                    self.tabs.setTabVisible(k, False)
            self._lado.poner_contenido(1, self.tabs)
            self.tabs.setTabVisible(i, False)
            self._lado.show()
            self.trans_list.poner_alto_max(None)
        else:
            self.tabs.widget(i).layout().insertWidget(0, hueco)
            hueco.show()
            self.tabs.setTabVisible(i, True)
            for clave, titulo in self.BAJO_TRANS:  # (cada una a su sección de siempre, abierta o cerrada como estaba)
                k = self._indice_de(titulo)
                if k >= 0:
                    self.tabs.widget(k).layout().insertWidget(0, self._huecos[clave])
                    self._huecos[clave].show()
                    self.tabs.setTabVisible(k, True)
            self._outer.insertWidget(0, self.tabs)
            self.tabs.show()
            self._lado.hide()
            self.trans_list.poner_alto_max(self.ALTO_TRANS)

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

    # ------------------------------------------------------- 📝 nota de texto
    def _build_note_group(self) -> QGroupBox:
        """📝 Nota de texto: escribes una nota (varias líneas), eliges fuente, tamaño y color, y la pones en el cabezal
        (o la arrastras a la línea de tiempo). Va a la pista de textos: no toca subtítulos ni transcripción. Fondo
        borroso alrededor con su barrita: de ajustado al texto a toda la pantalla (core/nota_texto.py).
        Con un texto seleccionado, lo que cambies aquí (salvo lo escrito) también le llega a él."""
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QSlider
        from ..core import nota_texto as NT
        st = self.settings
        self._note_loading = False
        g = QGroupBox("📝 Nota de texto")
        g.setToolTip("Un texto tuyo encima del video, aparte de los subtítulos y la transcripción: para señalar algo "
                     "o dejar una nota. Se mueve y se escala arrastrándolo en el visor; el resto, en el Inspector.")
        v = QVBoxLayout(g)
        self.note_text = QPlainTextEdit()
        self.note_text.setPlaceholderText("Escribe la nota…")
        self.note_text.setToolTip("El texto de la nota nueva (Enter = otra línea).")
        self.note_text.setFixedHeight(66)
        self.note_text.setPlainText(str(st.value("nota/texto", "") or ""))
        self.note_text.textChanged.connect(lambda: st.setValue("nota/texto", self.note_text.toPlainText()))
        v.addWidget(self.note_text)

        def fila(texto: str, w, tip: str, extra=None):
            r = QHBoxLayout()
            lab = QLabel(texto)
            lab.setToolTip(tip)
            w.setToolTip(tip)
            r.addWidget(lab)
            r.addWidget(w, 1)
            if extra is not None:
                r.addWidget(extra)
            v.addLayout(r)
            return lab

        self.note_font = QComboBox()
        favs = NT.fuentes()
        for i, f in enumerate(favs):
            self.note_font.addItem(f, f)
            self.note_font.setItemData(i, QFont(f, 10), Qt.FontRole)     # (las de Reclaimer, con su propia letra)
        self.note_font.insertSeparator(len(favs))
        for f in QFontDatabase.families():
            if f not in favs and not f.startswith("@"):
                self.note_font.addItem(f, f)
        self._note_font_tip = ("Arriba, las fuentes de Reclaimer (Miniatura, títulos y subtítulos); debajo, todas las "
                               "de tu PC.")
        fila("Fuente", self.note_font, self._note_font_tip)
        self.note_size = QSlider(Qt.Horizontal)
        self.note_size.setRange(10, 300)               # (décimas de % del alto del video: 1 % … 30 %)
        self.note_size_lab = QLabel()
        fila("Tamaño", self.note_size, "Más pequeña ← → más grande (en % del alto del video). En el visor también se "
             "escala con las esquinas.", self.note_size_lab)
        self.note_color = QPushButton("Color")
        self.note_color.setToolTip("El color de las letras.")
        self.note_color.clicked.connect(self._note_pick_color)
        v.addWidget(self.note_color)
        self.note_blur = QCheckBox("Fondo borroso alrededor")
        self.note_blur.setToolTip("Lo que hay debajo de la nota se ve desenfocado (el video de verdad) y la nota se lee "
                                  "mejor. Sigue al texto si lo mueves.")
        v.addWidget(self.note_blur)
        self.note_zsize = QSlider(Qt.Horizontal)
        self.note_zsize.setRange(0, 100)
        self.note_zsize_lab = QLabel()
        fila("Tamaño del borroso", self.note_zsize, "A la izquierda, solo un recuadro ajustado al texto; arrastrando "
             "a la derecha crece hasta cubrir toda la pantalla.", self.note_zsize_lab)
        self.note_zstr = QSlider(Qt.Horizontal)
        self.note_zstr.setRange(0, 100)
        self.note_zstr_lab = QLabel()
        fila("Fuerza", self.note_zstr, "Cuánto se desenfoca lo de debajo.", self.note_zstr_lab)
        self.note_zdark = QSlider(Qt.Horizontal)
        self.note_zdark.setRange(0, 90)
        self.note_zdark_lab = QLabel()
        fila("Oscurecer", self.note_zdark, "Oscurece un poco lo desenfocado (0 = nada).", self.note_zdark_lab)
        self.b_note_add = _FxButton("📝 Añadir en el cabezal", "nota:add")
        FXP.attach(self.b_note_add, "look", "nota")    # 🎞 su miniatura y, al pasar el ratón, en movimiento
        self.b_note_add.setObjectName("primary")
        self.b_note_add.setToolTip("Pone la nota en el cabezal (4 s; se alarga o acorta en la línea de tiempo).\n"
                                   "Arrastrar: suéltalo en la línea de tiempo, en el segundo que quieras.")
        self.b_note_add.clicked.connect(lambda: self.add_note_at(None))
        v.addWidget(self.b_note_add)
        self.note_status = QLabel("")
        self.note_status.setObjectName("dim")
        self.note_status.setWordWrap(True)
        v.addWidget(self.note_status)
        # Valores recordados (los de la nota nueva)
        d = NT.NOTE_STYLE

        def val(k, cast):
            try:
                return cast(st.value("nota/" + k, d[k]))
            except (TypeError, ValueError):
                return d[k]
        self._note_vals = {"font": str(val("font", str)), "size": val("size", float), "color": str(val("color", str)),
                           "zone_blur": str(st.value("nota/zone_blur", "true")).lower() == "true",
                           "zone_size": val("zone_size", float), "zone_strength": val("zone_strength", float),
                           "zone_dark": val("zone_dark", float)}
        self._note_show(self._note_vals)
        self.note_font.currentIndexChanged.connect(
            lambda _i: self._note_set("font", self.note_font.currentData() or self.note_font.currentText()))
        self.note_size.valueChanged.connect(lambda x: self._note_set("size", round(x / 10, 1)))
        self.note_blur.toggled.connect(lambda on: self._note_set("zone_blur", bool(on)))
        self.note_zsize.valueChanged.connect(lambda x: self._note_set("zone_size", round(x / 100, 2)))
        self.note_zstr.valueChanged.connect(lambda x: self._note_set("zone_strength", round(x / 100, 2)))
        self.note_zdark.valueChanged.connect(lambda x: self._note_set("zone_dark", round(x / 100, 2)))
        return g

    def _note_target(self):
        """El texto seleccionado (uno solo), si lo hay: lo que cambies en la nota le llega también a él."""
        sel = list(self.timeline.selected)
        c = self.ctrl.project.clips.get(sel[0]) if len(sel) == 1 else None
        return c if c is not None and c.text is not None else None

    def _note_show(self, vals: dict):
        """Pone los valores en los controles (sin aplicar nada)."""
        self._note_loading = True
        try:
            fam = str(vals.get("font") or "Arial")
            i = self.note_font.findData(fam)
            if i < 0:
                self.note_font.insertItem(0, fam, fam)
                i = 0
            self.note_font.setCurrentIndex(i)
            self.note_font.setToolTip(f"{fam}\n{self._note_font_tip}")
            self.note_size.setValue(int(round(float(vals.get("size") or 5.0) * 10)))
            self.note_blur.setChecked(bool(vals.get("zone_blur")))
            self.note_zsize.setValue(int(round(float(vals.get("zone_size") or 0) * 100)))
            self.note_zstr.setValue(int(round(float(vals.get("zone_strength", 0.6)) * 100)))
            self.note_zdark.setValue(int(round(float(vals.get("zone_dark", 0.2)) * 100)))
            self._note_paint_color(str(vals.get("color") or "#FFFFFF"))
            self._note_labels()
        finally:
            self._note_loading = False

    def _note_paint_color(self, hexc: str):
        from PySide6.QtGui import QIcon, QPixmap
        pm = QPixmap(14, 14)
        pm.fill(QColor(hexc))
        self.note_color.setIcon(QIcon(pm))
        self._note_color_now = hexc

    def _note_labels(self):
        self.note_size_lab.setText(f"{self.note_size.value() / 10:.1f} %")
        z = self.note_zsize.value()
        self.note_zsize_lab.setText("Ajustado" if z == 0 else ("Toda la pantalla" if z >= 100 else f"{z} %"))
        self.note_zstr_lab.setText(f"{self.note_zstr.value()} %")
        self.note_zdark_lab.setText(f"{self.note_zdark.value()} %")
        on = self.note_blur.isChecked()
        for w in (self.note_zsize, self.note_zstr, self.note_zdark):
            w.setEnabled(on)

    def _note_load(self):
        """Con un texto seleccionado, los controles enseñan los suyos; si no, los de la nota nueva."""
        if self._note_loading:
            return
        c = self._note_target()
        if c is None:
            self._note_show(self._note_vals)
            return
        from ..core import nota_texto as NT
        from ..core.title_render import _get
        t = c.text
        self._note_show({"font": _get(t, "font"), "size": _get(t, "size"), "color": _get(t, "color"),
                         **{k: t.get(k, NT.ZONE_DEFAULTS[k]) for k in NT.ZONE_KEYS}})

    def _note_set(self, key: str, value):
        if self._note_loading:
            return
        self._note_labels()
        self._note_vals[key] = value
        self.settings.setValue("nota/" + key, ("true" if value else "false") if isinstance(value, bool) else value)
        if key == "font":
            self.note_font.setToolTip(f"{value}\n{self._note_font_tip}")
        c = self._note_target()
        if c is not None:              # el texto seleccionado también cambia (Ctrl+Z; un arrastre = un paso)
            self._note_loading = True
            try:
                self.ctrl.set_text_props(c.id, **{key: value})
            finally:
                self._note_loading = False

    def _note_pick_color(self):
        from .common import pick_color
        c = pick_color(self._note_vals.get("color", "#FFFFFF"), self, "Color de la nota")
        if c.isValid():
            self.set_note_color(c.name().upper())

    def set_note_color(self, hexc: str):
        self._note_paint_color(hexc)
        self._note_set("color", hexc)

    def note_controls(self) -> dict:
        """Lo que enseñan ahora los controles (lo que ves es lo que se pone)."""
        return {"font": str(self.note_font.currentData() or self.note_font.currentText() or "Arial"),
                "size": round(self.note_size.value() / 10, 1),
                "color": getattr(self, "_note_color_now", self._note_vals.get("color", "#FFFFFF")),
                "zone_blur": self.note_blur.isChecked(), "zone_size": round(self.note_zsize.value() / 100, 2),
                "zone_strength": round(self.note_zstr.value() / 100, 2),
                "zone_dark": round(self.note_zdark.value() / 100, 2)}

    def add_note_at(self, t=None):
        """📝 La nota en el segundo t (None = el cabezal), con lo escrito y los valores de aquí. Un Ctrl+Z."""
        start = float(self.engine.time if t is None else t)
        content = self.note_text.toPlainText().strip("\n") or "Nota"
        cid = self.ctrl.add_note(start, content, **self.note_controls())
        if cid:
            self.timeline.set_selection([cid])
            from .common import fmt_time
            self.note_status.setText(f"📝 Nota añadida en {fmt_time(start)}.")
        return cid

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
            if self.tabs.tabText(i) == "✦ Efectos":
                self.tabs.setCurrentIndex(i)
        for i in range(self.tabs_fx.count()):
            if self.tabs_fx.tabText(i).startswith("✨"):
                self.tabs_fx.setCurrentIndex(i)
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
        """La lista de sonidos: cada grupo con su cabecera (plegable) y sus sonidos detrás; «para qué» (o la
        subcarpeta) en el tooltip y en la búsqueda."""
        tree.clear()
        grupos: dict[str, list] = {}

        def poner(grupo: str, nombre: str, ref: str, detalle: str):
            it = _ItemSonido(nombre)
            it.setData(Qt.UserRole, ref)
            it.setData(D.ROL_DETALLE, detalle)
            if detalle:
                it.setToolTip(detalle)
            grupos.setdefault(grupo, []).append(it)
        for key, (name, cat, desc) in sfx.CATALOG.items():
            poner("Reclaimer · " + cat, name, "sfx:" + key, desc)
        from ..core.paths import user_dir
        web = str(user_dir() / "Sonidos de internet")       # (lo guardado con 🌐 Buscar en internet)
        if os.path.isdir(web):
            for root, _dirs, files in os.walk(web):
                for f in sorted(files):
                    if f.lower().endswith(AUDIO_EXT):
                        rel = os.path.relpath(root, web)
                        poner("🌐 De internet", os.path.splitext(f)[0].rsplit(" [", 1)[0],
                              "file:" + os.path.join(root, f), "" if rel == "." else rel)
        folder = str(self.settings.value("efectos/carpeta", ""))
        if folder and os.path.isdir(folder):
            n = 0
            for root, _dirs, files in os.walk(folder):
                for f in sorted(files):
                    if f.lower().endswith(AUDIO_EXT):
                        rel = os.path.relpath(root, folder)
                        poner("Mi carpeta · " + os.path.basename(folder), os.path.splitext(f)[0],
                              "file:" + os.path.join(root, f), "" if rel == "." else rel)
                        n += 1
                        if n >= 3000:
                            break
                if n >= 3000:
                    break
        tree.setUpdatesEnabled(False)
        try:
            for nombre, hijos in grupos.items():
                g = tree.agregar_grupo(nombre, _GrupoSonidos)
                for it in hijos:
                    tree.agregar(it, g)
                g._hijos = hijos
                tree._grupos_l.append(g)
        finally:
            tree.setUpdatesEnabled(True)

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

    def _clips_sombra(self) -> list:
        p = self.ctrl.project
        return [c for c in self._targets() if c.text is None and p.media_of(c) is not None
                and p.media_of(c).kind in ("video", "image")]

    def add_shadow(self):
        """🌑 Sombra pequeña y sutil (core/decor.SOMBRA_EFECTO) en los clips elegidos de video o imagen, en UN Ctrl+Z,
        y su sección del Inspector a la vista con el foco en «Fuerza» (regla «cada acción abre su panel»)."""
        clips = self._clips_sombra()
        if not clips:
            self.look_status.setText("Selecciona antes uno o varios clips de video o imagen en la línea de tiempo.")
            from .nudge import nudge_for
            nudge_for(self.look_status.text())
            return
        win = self.window()
        ins = getattr(win, "inspector", None)
        if ins is not None:
            n = ins.poner_sombra([c.id for c in clips])
        else:                                       # (sin Inspector: lo mismo, directo)
            from ..core import decor
            from . import inspector_secciones as SEC
            changes = {c.id: {"fx": dict(SEC._fx_sin_apagado(dict(c.fx or {}), "sombra"),
                                         shadow=decor.sombra(**decor.SOMBRA_EFECTO))}
                       for c in clips if decor.shadow_of(c.fx) is None}
            n = self.ctrl.batch_clip_props(changes, "Sombra") if changes else 0
        self.look_status.setText(f"Sombra puesta en {n} clip(s)." if n else "Esos clips ya tienen sombra.")
        self.abrir_sombra()

    def abrir_sombra(self):
        """La sección «Sombra» del Inspector a la vista (abierta) y el foco en «Fuerza»."""
        win = self.window()
        ins = getattr(win, "inspector", None)
        sec = getattr(ins, "secciones", {}).get("sombra") if ins is not None else None
        if sec is None:
            return
        if hasattr(win, "go_page") and (getattr(win, "_scenes_state", None) is not None or
                                        getattr(win, "_thumb_page", None) is not None):
            win.go_page("edit")                    # (el Inspector está en Editar)
        sec.set_open(True, save=False)
        if hasattr(win, "abrir_para_usar"):
            win.abrir_para_usar(ins.sombra_fuerza, foco=ins.sombra_fuerza)
        else:
            win.show_panel(ins)
            ins.ir_a("efectos")

    def clear_shadow(self):
        clips = self._clips_sombra()
        if not clips:
            return
        from . import inspector_secciones as SEC
        changes = {}
        for c in clips:
            fx = dict(c.fx or {})
            if "shadow" in fx or SEC.apagada(c, "sombra"):
                fx.pop("shadow", None)
                changes[c.id] = {"fx": SEC._fx_sin_apagado(fx, "sombra") or None}
        if changes:
            self.ctrl.batch_clip_props(changes, "Quitar sombra")

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

    # ------------------------------------------------- filas de «Fondo, relleno y sombra» (sistema de diseño)
    def _fila_efecto(self, titulo: str, boton: QPushButton, tip: str, tip_quitar: str, quitar) -> QWidget:
        """Una fila por efecto: etiqueta en la columna fija · su acción · × de quitar (BotonIcono, misma columna en
        todas las filas)."""
        cont = QWidget()
        h = D.fila_fija(QHBoxLayout(cont))
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(D.px(D.M1))
        D.alto_fijo(boton, D.ALTO_CAMPO)
        boton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h.addWidget(boton, 1)
        bx = D.BotonIcono("x", tip_quitar)
        bx.clicked.connect(quitar)
        h.addWidget(bx)
        return D.FilaInspector(titulo, cont, tip)

    def _fila_ajuste(self, titulo: str, valor, tip: str, paso: str) -> QWidget:
        """Un ajuste del efecto de arriba: su ValorDeslizable termina donde termina la acción (deja la columna de la ×
        libre). Arrastrarlo es UN solo Ctrl+Z (como en el Inspector)."""
        cont = QWidget()
        h = D.fila_fija(QHBoxLayout(cont))
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(D.px(D.M1))
        h.addWidget(valor, 1)
        hueco = QWidget()
        D.medida(hueco, lambda w: w.setFixedSize(D.px(D.ALTO_CAMPO), 1))   # (el ancho de la ×)
        h.addWidget(hueco)
        estado = {"abierto": False}

        def abrir():
            if not estado["abierto"] and self._targets():
                self.ctrl.undo_stack.beginMacro(paso)
                estado["abierto"] = True

        def cerrar(on):
            if on or not estado["abierto"]:
                return
            estado["abierto"] = False
            st = self.ctrl.undo_stack
            st.endMacro()
            cmd = st.command(st.index() - 1)
            if cmd is not None and cmd.childCount() == 0:   # (nada cambió de verdad: sin paso vacío)
                st.undo()
        valor.antes_de_cambiar.connect(abrir)
        valor.arrastre.connect(cerrar)
        return D.FilaInspector(titulo, cont, tip)

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
            if getattr(self, "region_mode", None) is not None and self.region_mode.currentData() == "pixel":
                r["mode"] = "pixel"
            fx = dict(c.fx or {})
            fx["blur_regions"] = list(fx.get("blur_regions") or []) + [r]
            changes[c.id] = {"fx": fx}
        n = self.ctrl.batch_clip_props(changes, "Desenfoque en zona")
        self._zonas_refrescar()
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
        self._zonas_refrescar()

    # ------------------------------------------------------- ▭ figuras geométricas (tapar y figuras de color)
    def _ver_fila_zonas(self, *_a):
        """«Quitar la zona» / «Quitar todas», solo con alguna zona en la lista (al cerrar, la lista ya no existe)."""
        try:
            fila, zonas = getattr(self, "_fila_zonas", None), getattr(self, "zonas", None)
            if fila is not None and zonas is not None:
                fila.setVisible(zonas.count() > 0)
        except RuntimeError:                       # (cerrando: ya no existen)
            pass

    def _build_shapes_group(self):
        """▭ Figuras geométricas: 🙈 tapar una zona (cuadro o círculo, desenfocado o pixelado, sobre el clip elegido;
        se mueve y cambia de tamaño en el visor; 🗑 o Supr en la lista la quitan) y ▭ ◯ figuras de color encima del
        video (generadores con su caja: ⤧ Transformar en el visor). Todo con Ctrl+Z y tal cual al exportar."""
        from PySide6.QtWidgets import QDoubleSpinBox as _DS
        from PySide6.QtWidgets import QListWidget
        gg = QGroupBox("▭ Figuras geométricas")
        v = QVBoxLayout(gg)
        lab = QLabel("Tapar (censurar) en el clip elegido:")
        lab.setToolTip("Desenfoca o pixela solo una parte (una cara, un logo, un dato…). Aparece en el centro del clip "
                       "seleccionado: arrástrala en el visor (dentro = mover, esquina naranja = tamaño).\n"
                       "🎯 ¿Algo que se mueve? Inspector → «Seguir» y «taparlo»: la zona lo acompaña.")
        v.addWidget(lab)
        rb = QHBoxLayout()
        for shape, text in (("rect", "▭ Cuadro"), ("ellipse", "◯ Círculo")):
            b = QPushButton(text)
            b.setToolTip(lab.toolTip())
            b.clicked.connect(lambda _=False, s_=shape: self.add_region(s_))
            rb.addWidget(b)
        self.region_mode = QComboBox()
        self.region_mode.addItem("Desenfoque", "blur")
        self.region_mode.addItem("Pixelado", "pixel")
        self.region_mode.setToolTip("Cómo se tapa la zona nueva (las que ya hay: elige una en la lista y cámbiala)")
        self.region_mode.activated.connect(lambda _i: self._zona_poner_modo())
        rb.addWidget(self.region_mode)
        v.addLayout(rb)
        rb2 = QHBoxLayout()
        self.region_amount = _DS()
        self.region_amount.setRange(0.1, 1.0)
        self.region_amount.setSingleStep(0.1)
        self.region_amount.setValue(float(self.settings.value("efectos/zona_intensidad", 0.6)))
        self.region_amount.setPrefix("Fuerza ")
        self.region_amount.setToolTip("Cuánto desenfoca o pixela (se recuerda). Cambia también las zonas del clip "
                                      "seleccionado.")
        self.region_amount.valueChanged.connect(self._region_amount)
        rb2.addWidget(self.region_amount)
        rb2.addStretch(1)
        v.addLayout(rb2)
        self.zonas = QListWidget()
        self.zonas.setMaximumHeight(96)
        self.zonas.setToolTip("Las zonas tapadas del clip elegido. Supr (o 🗑) = quitar la elegida.\n"
                              "🎯 ¿Algo que se mueve? Inspector → «Seguir» y «taparlo»: la zona lo acompaña.")
        self.zonas.installEventFilter(self)
        v.addWidget(self.zonas)
        # (sin zonas: una línea gris en vez de una lista vacía de 96 px, y sin los botones de quitar)
        self.zonas_vacio = D.aviso_vacio("Sin zonas tapadas en el clip elegido", self.zonas.toolTip())
        v.addWidget(self.zonas_vacio)
        rz = QHBoxLayout()
        self.b_zona_rm = QPushButton("Quitar la zona")
        self.b_zona_rm.setIcon(D.icono("trash-2"))
        self.b_zona_rm.setToolTip("Quita la zona elegida en la lista (Supr en la lista). Ctrl+Z la devuelve.")
        self.b_zona_rm.clicked.connect(self.remove_region)
        b_rm = QPushButton("✕ Quitar todas")
        b_rm.setToolTip("Quitar las zonas tapadas de los clips seleccionados")
        b_rm.clicked.connect(self.clear_regions)
        rz.addWidget(self.b_zona_rm)
        rz.addWidget(b_rm)
        self._fila_zonas = QWidget()
        rz.setContentsMargins(0, 0, 0, 0)
        self._fila_zonas.setLayout(rz)
        v.addWidget(self._fila_zonas)
        D.ocultar_si_vacia(self.zonas, self.zonas_vacio)
        for senal in (self.zonas.model().rowsInserted, self.zonas.model().rowsRemoved, self.zonas.model().modelReset):
            senal.connect(self._ver_fila_zonas)
        self._ver_fila_zonas()
        lab2 = QLabel("▭ Figuras de color encima del video:")
        lab2.setToolTip("Un rectángulo o un círculo de color en el cabezal, en la pista de arriba: muévelo y cambia su "
                        "tamaño en el visor (⤧ Transformar); su duración, en la línea de tiempo.")
        v.addWidget(lab2)
        rf = QHBoxLayout()
        self._color_fig = str(self.settings.value("efectos/color_figura", "#e8742f"))
        for kind, text in (("rect", "▭ Rectángulo"), ("ellipse", "◯ Círculo")):
            b = QPushButton(text)
            b.setToolTip(lab2.toolTip())
            b.clicked.connect(lambda _=False, k_=kind: self.add_shape(k_))
            rf.addWidget(b)
        self.b_fig_color = QPushButton("■")
        self.b_fig_color.setFixedWidth(34)
        self.b_fig_color.setToolTip("Color de las figuras (y de las figuras elegidas en la línea de tiempo)")
        self.b_fig_color.clicked.connect(self._color_figura)
        self._pintar_color_fig()
        rf.addWidget(self.b_fig_color)
        v.addLayout(rf)
        self.b_fig_rm = QPushButton("Quitar la figura")
        self.b_fig_rm.setIcon(D.icono("trash-2"))
        self.b_fig_rm.setToolTip("Quita las figuras elegidas en la línea de tiempo (también Supr en la línea de "
                                 "tiempo). Ctrl+Z la devuelve.")
        self.b_fig_rm.clicked.connect(self.remove_shapes)
        v.addWidget(self.b_fig_rm)
        st = QLabel("")
        st.setObjectName("dim")
        st.setWordWrap(True)
        v.addWidget(st)
        self.timeline.selection_changed.connect(lambda _ids: self._zonas_refrescar())
        self.ctrl.project_changed.connect(self._zonas_refrescar)
        return gg, st

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "zonas", None) and ev.type() in (QEvent.KeyPress, QEvent.ShortcutOverride) and \
                ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.zonas.currentRow() >= 0:
            ev.accept()                           # (Supr en la lista quita la zona, no los clips)
            if ev.type() == QEvent.KeyPress:
                self.remove_region()
            return True
        return super().eventFilter(obj, ev)

    def _zona_clip(self):
        """El clip cuyas zonas se ven en la lista (el primero elegido que tenga, o el primero elegido)."""
        cs = self._targets()
        return next((c for c in cs if (c.fx or {}).get("blur_regions")), cs[0] if cs else None)

    def _zonas_refrescar(self, *_a):
        lst = getattr(self, "zonas", None)
        if lst is None:
            return
        c = self._zona_clip()
        fila = lst.currentRow()
        lst.blockSignals(True)
        lst.clear()
        from ..core import effects as E_
        for i, r in enumerate(E_.blur_regions(c.fx) if c else []):
            forma = "▭ Cuadro" if r["shape"] == "rect" else "◯ Círculo"
            modo = "pixelado" if r.get("mode") == "pixel" else "desenfoque"
            lst.addItem(f"Zona {i + 1} · {forma} · {modo} · fuerza {r['amount']:.1f}")
        if lst.count():
            lst.setCurrentRow(min(max(0, fila), lst.count() - 1))
        lst.blockSignals(False)
        self.b_zona_rm.setEnabled(lst.count() > 0)

    def remove_region(self):
        """🗑 Quita la zona elegida en la lista (del clip que enseña la lista). Un paso de Ctrl+Z."""
        c = self._zona_clip()
        i = self.zonas.currentRow()
        regs = list((c.fx or {}).get("blur_regions") or []) if c else []
        if not (0 <= i < len(regs)):
            self.look_status.setText("Elige en la lista la zona que quieres quitar.")
            return
        del regs[i]
        fx = dict(c.fx)
        if regs:
            fx["blur_regions"] = regs
        else:
            fx.pop("blur_regions", None)
        self.ctrl.batch_clip_props({c.id: {"fx": fx or None}}, "Quitar zona tapada")
        self._zonas_refrescar()
        self.look_status.setText(f"🗑 Zona {i + 1} quitada (Ctrl+Z la devuelve).")

    def _zona_poner_modo(self):
        """Cambia a desenfoque / pixelado la zona elegida en la lista (la nueva ya sale con el modo elegido)."""
        c = self._zona_clip()
        i = self.zonas.currentRow()
        regs = list((c.fx or {}).get("blur_regions") or []) if c else []
        if not (0 <= i < len(regs)):
            return
        r = dict(regs[i])
        if self.region_mode.currentData() == "pixel":
            r["mode"] = "pixel"
        else:
            r.pop("mode", None)
        if r == regs[i]:
            return
        regs[i] = r
        fx = dict(c.fx, blur_regions=regs)
        self.ctrl.batch_clip_props({c.id: {"fx": fx}}, "Cambiar cómo se tapa la zona")
        self._zonas_refrescar()

    def _pintar_color_fig(self):
        self.b_fig_color.setProperty("color_contenido", True)   # (color elegido por ti: el acento no lo toca)
        self.b_fig_color.setStyleSheet(f"QPushButton {{ color: {self._color_fig}; font-size: 14pt; }}")

    def _color_figura(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self._color_fig), self, "Color de la figura")
        if not c.isValid():
            return
        self._color_fig = c.name()
        self.settings.setValue("efectos/color_figura", self._color_fig)
        self._pintar_color_fig()
        figs = self._figuras_elegidas()
        if figs:
            n = self.ctrl.set_shape_color([x.id for x in figs], self._color_fig)   # (un solo Ctrl+Z)
            if n:
                resto = len(figs) - n
                self.look_status.setText(f"■ Color cambiado en {n} figura(s)."
                                         + (f" {resto} bloqueada(s), sin cambiar." if resto else ""))

    def _figuras_elegidas(self) -> list:
        from ..core import generators as G
        p = self.ctrl.project
        return [p.clips[cid] for cid in self.timeline.selected if cid in p.clips and G.is_shape(p.media_of(p.clips[cid]))]

    def add_shape(self, kind: str):
        """▭ ◯ Una figura de color en el cabezal (en la pista de arriba libre), elegida para moverla en el visor."""
        cid = self.ctrl.add_shape(kind, self._color_fig, self.engine.time)
        if cid:
            self.timeline.set_selection([cid])          # (elegida: se mueve ya en el visor)
            self.look_status.setText("▭ Figura añadida: muévela y cambia su tamaño en el visor (⤧ Transformar). "
                                     "🗑 o Supr en la línea de tiempo la quitan.")
        return cid

    def remove_shapes(self):
        figs = self._figuras_elegidas()
        if not figs:
            self.look_status.setText("Elige antes en la línea de tiempo la figura que quieres quitar.")
            return
        self.ctrl.delete_clips([c.id for c in figs])
        self.look_status.setText(f"🗑 {len(figs)} figura(s) quitada(s) (Ctrl+Z las devuelve).")

    def _abrir_color(self):
        win = self.window()
        if hasattr(win, "go_page") and (getattr(win, "_scenes_state", None) is not None or
                                        getattr(win, "_thumb_page", None) is not None):
            win.go_page("edit")                    # (el Inspector está en Editar)
        ins = getattr(win, "inspector", None)
        if ins is None:
            return
        win.show_panel(ins)
        # (fase 2: el color es la sección «Color» de la pestaña Video del Inspector —ya no hay pestaña «Color»—)
        ins.ir_a("video")
        sec = getattr(ins, "secciones", {}).get("color")
        if sec is not None:
            sec.set_open(True, save=False)
            from PySide6.QtCore import QTimer
            p = sec.parentWidget()
            while p is not None and not isinstance(p, QScrollArea):
                p = p.parentWidget()
            if p is not None:
                QTimer.singleShot(0, lambda: p.ensureWidgetVisible(sec, 0, 0))

    # ------------------------------------------------------- categorías en la página ✦ Efectos / 🔊 a 🎚 Audio
    def sacar_sonidos(self) -> QWidget:
        """🔊 Sonidos (y 🌐 sus webs) salen de Efectos a su propio panel de la página 🎚 Audio. Devuelve el panel."""
        caja = QWidget()
        v = QVBoxLayout(caja)
        v.setContentsMargins(6, 6, 6, 6)
        for k, g in enumerate(self._sonidos):
            g.setParent(caja)                     # (antes de quitar su pestaña: removeTab borra lo que quede dentro)
            v.addWidget(g, 1 if k == 0 else 0)    # (la lista de sonidos se queda con el alto que sobre)
            g.show()
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "🔊 Sonidos":
                self.tabs.removeTab(i)
                break
        self.sounds_panel = caja
        return caja

    def sacar_categorias(self, destinos: dict):
        """En la página ✦ Efectos: cada categoría (trans, efectos, filtros, figuras) a su columna."""
        for clave, dest in destinos.items():
            cat = self.cats.get(clave)
            if cat is not None and dest is not None and cat.parentWidget() is not dest:
                dest.layout().addWidget(cat)
                cat.show()

    def devolver_categorias(self):
        """Al salir de la página: cada categoría vuelve a su sitio de aquí (Editar)."""
        for clave, cat in self.cats.items():
            hueco = self._huecos[clave]
            if cat.parentWidget() is not hueco:
                hueco.layout().addWidget(cat)
                cat.show()

    def clear_looks(self, cuales=None):
        """Quita los efectos de imagen de la lista (cuales(clave) = cuáles: los efectos o los filtros; None = todos)."""
        clips = self._targets()
        if clips:
            # Solo los efectos de esta lista (antes se borraba TODO: también la transición, la pantalla verde, el
            # recorte de sujeto, el estabilizado…)
            looks = {k for k, _t, _v, _h in LOOKS if cuales is None or cuales(k)}
            if cuales is None or cuales("shake"):
                looks |= {"shake_amp"}
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
        n = len(clips)
        quien = "1 clip elegido" if n == 1 else f"{n} clips elegidos"
        self.look_status.setText(f"{quien} · " + (", ".join(on) if on else "sin efectos"))
        self.look_status.setToolTip("El grano, el glitch y los tonos se ven al exportar; el resto, también en el "
                                    "visor.")                # (20/11, auditoría: la explicación, al tooltip)

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
