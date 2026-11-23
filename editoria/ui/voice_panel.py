"""
Panel «Limpieza de voz»: transcribir la narración, detectar silencios/muletillas/
repeticiones y revisar las sugerencias una a una (Escuchar · Aplicar · Ignorar · Restaurar).
"""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..ai import transcription, voice_cleanup
from ..core import mapping
from ..core.media import decode_mono
from ..core.model import KIND_AUDIO, KIND_VIDEO, SUG_APPLIED, SUG_PENDING, SUG_REJECTED, TRACK_AUDIO
from . import diseno as D
from . import theme as T
from .common import SUGGESTION_COLORS, fmt_time
from .help import set_help
from .jobs import BackgroundJob

SR = 16000
STATUS_TEXT = {SUG_PENDING: "Pendiente", SUG_APPLIED: "Aplicada", SUG_REJECTED: "Ignorada"}
# (los botones de «Sugerencias»: solo icono; lo que hacen, en su tooltip)
TIP_ESCUCHAR = "Escuchar\nReproduce ese momento (con un segundo antes y después). Doble clic también."
TIP_COMPARAR = "Comparar\nEscucha las dos tomas, una detrás de otra."
TIP_APLICAR = "Aplicar\nCorta lo elegido de la línea de tiempo (Ctrl+Z lo deshace)."
TIP_ELEGIR_TOMA = "Elegir toma…\nQuedarte con la toma 1 o la 2 (la IA recomienda una) o mantener las dos."
TIP_IGNORAR = "Ignorar\nNo se corta: pasa a «Ignoradas» (desde ahí se puede recuperar)."
TIP_RECUPERAR = "Recuperar\nVuelve a dejarla pendiente."
TIP_RESTAURAR = "Restaurar\nDevuelve a la línea de tiempo un corte ya aplicado."


def cut_kinds() -> set[str]:
    """Las casillas «Quitar» de «Qué buscar» (también deciden qué sale tachado en el texto)."""
    s = QSettings("EditorIA", "EditorIA")
    return {k for k, d in voice_cleanup.AUTO_DEFAULTS.items()
            if str(s.value(f"limpieza_auto/{k}", d)).lower() in ("true", "1")}


# 🧹 La tabla «Qué buscar» (una sola, columnas «Marcar» y «Quitar»; antes eran dos listas que repetían opciones).
#    (fila, texto, tooltip, ¿hay limpieza automática para ella?, por qué no). La clave de la fila = la de «Quitar»
#    (limpieza_auto/<clave>, la de siempre); la de «Marcar» está en AJUSTE_MARCAR (limpieza/<ajuste>, la de siempre).
FILAS_LIMPIEZA = (
    ("silence", "Silencios largos", "Según «Mayores de» y «Pausa que deja»: siempre queda una pausa natural.", True, ""),
    ("filler", "Muletillas seguras", "eh, mmm… Las que nunca son palabras de verdad (y las de «Mis muletillas»).",
     True, ""),
    ("filler_soft", "Posibles muletillas", "este, bueno, o sea… Solo cuando van seguidas de una pausa.\nRevisa antes "
     "si hablas así a propósito.", True, ""),
    ("repeat", "Palabras repetidas", "«el el», «pro… problema» (también las cortadas). Las que suelen ser a propósito "
     "(«muy muy», «no no») se marcan pero no se quitan solas.", True, ""),
    ("retake", "Tomas repetidas", "Dices una frase dos o más veces: la IA se queda con la toma más completa y limpia "
     "(verás por qué en «Sugerencias»).", True, ""),
    ("noise", "Respiraciones y ruidos", "Sonidos entre palabras que no son voz. Mejor revisarlas: a veces una "
     "respiración da naturalidad.", True, ""),
    ("similar", "Frases parecidas", "Dos frases seguidas que dicen lo mismo con otras palabras.", False,
     "Las frases parecidas solo se avisan: no se quitan solas.\nSi sobra una, táchala en «Texto» o aplícala en "
     "«Sugerencias»."),
    ("doubt", "Palabras dudosas", "Whisper no estaba seguro de esa palabra: puede estar cortada o mal pronunciada.",
     False, "Una palabra dudosa solo se avisa: escúchala en «Sugerencias» y decide tú."),
    ("clipping", "Saturación", "El volumen llegó al máximo y se distorsionó (conviene regrabar o bajar la ganancia).",
     False, "La saturación solo se avisa: no se arregla cortando."),
)
AJUSTE_MARCAR = {"silence": "silencios", "filler": "muletillas", "filler_soft": "muletillas_posibles",
                 "repeat": "repetidas", "retake": "tomas", "noise": "ruidos", "similar": "parecidas",
                 "doubt": "dudosas", "clipping": "saturacion"}
VERSION_AJUSTES_LIMPIEZA = 2


def _si(v, defecto: bool) -> bool:
    return str(defecto if v is None else v).lower() in ("true", "1")


def migrar_ajustes_limpieza(s: QSettings) -> bool:
    """De las dos listas viejas a la tabla «Marcar · Quitar», una sola vez y sin perder ningún ajuste:
    · «Quitar» = las casillas de «⚡ Limpieza automática» (limpieza_auto/…): las mismas claves, sin tocar.
    · «Marcar» = las de «qué buscar» (limpieza/…). «Muletillas (eh, este…)» era una sola casilla: «Muletillas seguras»
      sigue en limpieza/muletillas y «Posibles muletillas» (limpieza/muletillas_posibles, nueva) empieza igual.
    · «Frases parecidas» antes solo se buscaban con «Tomas repetidas» marcada: si las tomas estaban apagadas, las
      parecidas quedan apagadas (el análisis da lo mismo que antes).
    True si migró ahora."""
    try:
        version = int(s.value("limpieza/version_tabla", 1))
    except (TypeError, ValueError):
        version = 1
    if version >= VERSION_AJUSTES_LIMPIEZA:
        return False
    d = voice_cleanup.CleanupOptions()
    if s.value("limpieza/muletillas_posibles") is None and s.value("limpieza/muletillas") is not None:
        s.setValue("limpieza/muletillas_posibles", _si(s.value("limpieza/muletillas"), d.fillers))
    if s.value("limpieza/tomas") is not None and not _si(s.value("limpieza/tomas"), d.retakes) and \
            _si(s.value("limpieza/parecidas"), d.similar):
        s.setValue("limpieza/parecidas", False)
    s.setValue("limpieza/version_tabla", VERSION_AJUSTES_LIMPIEZA)
    return True


class _AudioCache:
    """Guarda en memoria el último audio decodificado (para no repetirlo)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._key: str | None = None
        self._samples: np.ndarray | None = None

    def get(self, path: str) -> np.ndarray:
        with self._lock:
            if self._key != path or self._samples is None:
                self._samples = decode_mono(path, SR)
                self._key = path
            return self._samples


def _dot(color: QColor) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return QIcon(pix)


class _Section(QWidget):
    """Sección plegable: un título que se puede pulsar para mostrar/ocultar el contenido."""

    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self.header = QPushButton()
        self.header.setFlat(True)
        self.header.setStyleSheet("QPushButton { text-align: left; font-weight: bold; color: #c7ccd4;"
                                  " padding: 4px 2px; border: none; border-bottom: 1px solid #3a3f4a; }")
        self.header.clicked.connect(lambda: self.set_expanded(not self.body.isVisible()))
        self.body = QWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.set_expanded(True)

    def set_expanded(self, on: bool):
        self.body.setVisible(on)
        self.header.setText(("▾ " if on else "▸ ") + self._title)


class VoicePanel(QWidget):
    media_selected = Signal(str)        # narración elegida
    suggestion_selected = Signal(str)   # para resaltarla en la timeline
    cut_rules_changed = Signal()        # cambiaron las casillas de ⚡ (lo tachado en el texto cambia)
    quick_review_requested = Signal()   # ⚡ Revisión rápida con teclas (ver ui/quick_review.py)
    subtitles_requested = Signal()      # 💬 «Subtítulos» al lado de «Transcribir» (abre su panel)

    def __init__(self, ctrl, engine, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.settings = QSettings("EditorIA", "EditorIA")
        self.audio = _AudioCache()
        self.job: BackgroundJob | None = None
        self._icons = {k: _dot(c) for k, c in SUGGESTION_COLORS.items()}

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(D.px(D.M2), D.px(D.M2), D.px(D.M2), D.px(D.M1))
        lay.setSpacing(D.px(D.M1))

        # --- Narración --- (📝 vive en la página «Transcripción y subtítulos»: IA ✨ → «🎙 Transcribir» se lleva
        # narr_box con set_transcriber; aquí, en «Limpieza», queda una línea con la narración elegida y «📝 Cambiar»)
        self.narr_box = QWidget()
        nb = QVBoxLayout(self.narr_box)
        nb.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Narración:"))
        self.media_combo = QComboBox()
        self.media_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.media_combo.setMinimumContentsLength(14)
        self.media_combo.currentIndexChanged.connect(self._on_media_changed)
        row.addWidget(self.media_combo, 1)
        nb.addLayout(row)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setObjectName("hint")
        self.banner_btn = QPushButton("Añadir la narración a la pista A1")
        self.banner_btn.clicked.connect(self._add_narration_to_timeline)
        nb.addWidget(self.banner)
        nb.addWidget(self.banner_btn)
        lay.addWidget(self.narr_box)
        # (lo que se limpia: la narración elegida, a la vista; se elige en 📝 Transcripción)
        # (diseño de ui/diseno.py: punto de estado · nombre con «…» si no cabe · icono «Cambiar»)
        self.narr_fila = QWidget()
        nf = D.fila_fija(QHBoxLayout(self.narr_fila))
        nf.setContentsMargins(0, 0, 0, 0)
        nf.setSpacing(D.px(D.M2))
        self.narr_punto = D.PuntoEstado()
        self.narr_info = D.EtiquetaElidida()
        D.poner_letra(self.narr_info, D.LETRA_M, T.TEXT)
        self.narr_info.setFixedHeight(D.px(D.ALTO_CAMPO))
        self.narr_cambiar = D.BotonIcono("replace", "Cambiar la narración\nLa narración (tu voz) se elige en «Voz y "
                                         "texto → 1 · Transcribir»", plano=True)
        self.narr_cambiar.clicked.connect(lambda: self._ir_a_narracion())
        nf.addWidget(self.narr_punto)
        nf.addWidget(self.narr_info, 1)
        nf.addWidget(self.narr_cambiar)
        self.narr_fila.setVisible(False)              # (se ve cuando narr_box se va a la página de Transcripción)
        lay.addWidget(self.narr_fila)

        # --- Estado (siempre visible) ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setVisible(False)
        prow = QHBoxLayout()
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.btn_cancel)
        self.status = QLabel()                          # (corto: «Sin transcribir»; la explicación, en su tooltip)
        self.status.setWordWrap(True)
        D.poner_letra(self.status, D.LETRA_P, D.GRIS_TITULO)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._result_msg = ""
        self._result_corto = ""
        self._cargando = False
        self._quitar_recordado: dict[str, bool] = {}     # («Quitar» que se apagó al desmarcar «Marcar»)
        self._por_marcar = False
        lay.addLayout(prow)
        lay.addWidget(self.status)

        # --- 1. Transcripción ---
        self.sec1 = set_help(_Section("1 · Transcripción"), "transcripcion")
        g1 = QGridLayout(self.sec1.body)
        g1.setContentsMargins(4, 2, 4, 2)
        self.model_combo = QComboBox()
        for key, (_name, label) in transcription.MODELS.items():
            self.model_combo.addItem(label, key)
            self.model_combo.setItemData(self.model_combo.count() - 1,
                                         f"Descarga la primera vez: {transcription.DOWNLOAD_SIZE[key]}",
                                         Qt.ToolTipRole)
        self.lang_combo = QComboBox()
        for code, label in transcription.LANGUAGES.items():
            self.lang_combo.addItem(label, code)
        self.btn_transcribe = QPushButton("🎙 Transcribir y analizar")
        self.btn_transcribe.setObjectName("primary")
        self.btn_transcribe.clicked.connect(self.transcribe)
        self.chk_literal = QCheckBox("🔁 Escucha literal (no se salta las tomas repetidas)")
        self.chk_literal.setToolTip("Whisper a veces escribe una sola vez lo que dijiste dos veces, y esa toma no se "
                                    "podría quitar.\nUn segundo oído escucha todo letra a letra y recupera lo que "
                                    "faltaba.\nTarda más o menos el doble (en tu PC, gratis y sin internet).")
        g1.addWidget(QLabel("Modelo"), 0, 0)
        g1.addWidget(self.model_combo, 0, 1)
        g1.addWidget(QLabel("Idioma"), 1, 0)
        g1.addWidget(self.lang_combo, 1, 1)
        g1.addWidget(self.chk_literal, 2, 0, 1, 2)
        self.btn_subtitulos = QPushButton("💬 Subtítulos")
        self.btn_subtitulos.setToolTip("Abre el panel de subtítulos: crearlos desde la transcripción, su estilo "
                                       "(palabra a palabra, Neón…) y exportarlos en .srt.")
        self.btn_subtitulos.clicked.connect(self.subtitles_requested.emit)
        fila_tr = QHBoxLayout()
        fila_tr.setSpacing(6)
        fila_tr.addWidget(self.btn_transcribe, 3)
        fila_tr.addWidget(self.btn_subtitulos, 1)
        g1.addLayout(fila_tr, 3, 0, 1, 2)
        lay.addWidget(self.sec1)

        # --- 2. Limpieza --- (diseño profesional de ui/diseno.py: «Silencios», UNA tabla «Marcar · Quitar», «Mis
        # muletillas» y el pie con «Volver a analizar» + «Limpiar»; antes eran dos listas con las mismas opciones)
        self.limpiar_vista = set_help(QWidget(), "limpieza")
        self.sec2 = self.limpiar_vista                  # (el nombre de siempre)
        lv = QVBoxLayout(self.limpiar_vista)
        lv.setContentsMargins(D.px(D.M1), 0, D.px(D.M1), D.px(D.M1))
        lv.setSpacing(D.px(D.M1))
        lv.addWidget(D.TituloSeccion("Silencios"))
        self.min_sil = D.ValorDeslizable(0.3, 5.0, 0.1, 2, "s")
        self.keep = D.ValorDeslizable(0.0, 1.5, 0.05, 2, "s")
        self.fila_min_sil = D.FilaInspector("Mayores de", self.min_sil, "Los silencios más largos que esto se marcan "
                                            "(fila «Silencios largos»).\nArrastra el número a los lados o haz clic "
                                            "para escribirlo.")
        self.fila_keep = D.FilaInspector("Pausa que deja", self.keep, "Las pausas naturales nunca se eliminan del "
                                         "todo: se deja este margen.")
        lv.addWidget(self.fila_min_sil)
        lv.addWidget(self.fila_keep)
        lv.addWidget(D.TituloSeccion("Qué buscar"))
        self.tabla = D.TablaCasillas([
            ("marcar", "Marcar", "La IA lo detecta y lo enseña en «Sugerencias» (no corta nada).\n«Volver a "
             "analizar» busca lo que esté marcado aquí."),
            ("quitar", "Quitar", "Lo borra sola al pulsar «Limpiar» (todo de una vez, un solo Ctrl+Z).\nTambién "
             "decide qué sale tachado en el texto.")])
        for clave, texto, tip, se_quita, por_que in FILAS_LIMPIEZA:
            self.tabla.agregar_fila(clave, texto, tip, {"marcar": False, "quitar": False if se_quita else None},
                                    {"quitar": por_que})
        set_help(self.tabla.cabeceras["quitar"], "limpieza_auto")
        lv.addWidget(self.tabla)
        t = self.tabla.casilla
        self.chk_sil, self.chk_fill, self.chk_fill_soft = t("silence", "marcar"), t("filler", "marcar"), \
            t("filler_soft", "marcar")
        self.chk_rep, self.chk_take, self.chk_noise = t("repeat", "marcar"), t("retake", "marcar"), \
            t("noise", "marcar")
        self.chk_similar, self.chk_doubt, self.chk_clip = t("similar", "marcar"), t("doubt", "marcar"), \
            t("clipping", "marcar")
        self.auto_chk = {k: t(k, "quitar") for k in voice_cleanup.AUTO_DEFAULTS}    # (las de «Limpiar»)
        self.my_fillers = D.campo_texto("¿por qué?, o sea",
                                        "Las muletillas que sabes que dices, separadas por comas. Se proponen para "
                                        "quitar y salen tachadas en el texto.\nCon «?» solo cuenta si es una "
                                        "pregunta suelta («¿por qué?» sí; «¿por qué lo hicieron?» no).")
        self.fila_mis = D.FilaInspector("Mis muletillas", self.my_fillers)
        lv.addSpacing(D.px(D.M1))
        lv.addWidget(self.fila_mis)
        # (el pie: una línea fina encima, «Volver a analizar» de solo icono y «Limpiar», el único con el acento)
        lv.addSpacing(D.px(D.M2))
        lv.addWidget(D.LineaSeparadora())
        pie = D.fila_fija(QHBoxLayout())
        pie.setContentsMargins(0, D.px(D.M2), 0, 0)
        pie.setSpacing(D.px(D.M1))
        self.btn_analyze = D.BotonIcono("refresh-cw", "Volver a analizar\nBusca de nuevo lo marcado en «Marcar» "
                                        "(no repite la transcripción).", D.ALTO_PRINCIPAL)
        self.btn_analyze.clicked.connect(lambda: self.analyze())
        self.btn_auto_clean = D.BotonPrincipal("Limpiar", "wand-sparkles",
                                               "Quita de una vez lo marcado en «Quitar» (un solo Ctrl+Z).\nCualquier "
                                               "corte se puede devolver con «Restaurar» en «Sugerencias».")
        self.btn_auto_clean.clicked.connect(lambda: self.auto_clean())
        set_help(self.btn_auto_clean, "limpieza_auto")
        pie.addWidget(self.btn_analyze)
        pie.addWidget(self.btn_auto_clean, 1)
        lv.addLayout(pie)
        self.auto_after = D.CasillaTexto("Al terminar de transcribir")
        self.auto_after.setToolTip("Hacerlo solo al terminar de transcribir o analizar")
        self.auto_after.setChecked(str(self.settings.value("limpieza_auto/al_terminar", False)).lower() in ("true", "1"))
        self.auto_after.toggled.connect(lambda on: self.settings.setValue("limpieza_auto/al_terminar", on))
        lv.addWidget(self.auto_after)
        self.tabla.cambiado.connect(self._casilla_cambiada)
        self._load_options()

        # --- 3. Sugerencias --- (diseño de ui/diseno.py, 20/11: filtros, tabla de filas de 22 px, acciones de solo icono
        # monocromo con su tooltip —antes ▶ ✓ ✗ ↺ con texto— y el pie con la revisión guiada y «Aplicar todas»)
        box3 = set_help(QGroupBox("3 · Sugerencias de la IA"), "sugerencias")
        v3 = QVBoxLayout(box3)
        v3.setSpacing(D.px(D.M1))
        frow = QHBoxLayout()
        frow.setSpacing(D.px(D.M1))
        self.f_status = QComboBox()
        self.f_status.addItem("Pendientes", SUG_PENDING)
        self.f_status.addItem("Aplicadas", SUG_APPLIED)
        self.f_status.addItem("Ignoradas", SUG_REJECTED)
        self.f_status.addItem("Todas", "")
        self.f_status.setToolTip("Qué sugerencias se ven: pendientes, aplicadas, ignoradas o todas")
        self.f_kind = QComboBox()
        self.f_kind.addItem("Todos los tipos", "")
        for k, (label, _c) in voice_cleanup.KINDS.items():
            self.f_kind.addItem(self._icons[k], label, k)
        self.f_kind.setToolTip("Solo un tipo (silencios, muletillas, tomas repetidas…)")
        for cb in (self.f_status, self.f_kind):
            D.alto_fijo(cb)
        self.f_status.currentIndexChanged.connect(self._rebuild_list)
        self.f_kind.currentIndexChanged.connect(self._rebuild_list)
        frow.addWidget(self.f_status)
        frow.addWidget(self.f_kind, 1)
        v3.addLayout(frow)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        D.poner_letra(self.summary, D.LETRA_P, D.GRIS_TITULO)
        v3.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tiempo", "Sugerencia", "Estado"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        D.filas_compactas(self.tree)                    # (filas de 22 px, la letra del diseño)
        self.tree.setColumnWidth(0, D.px(76))
        self.tree.setColumnWidth(1, D.px(210))
        self.tree.setMinimumHeight(220)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.listen())
        v3.addWidget(self.tree, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        D.poner_letra(self.detail, D.LETRA_P, T.TEXT_DIM)
        v3.addWidget(self.detail)
        b1 = D.fila_fija(QHBoxLayout())                 # (cuatro iconos: caben siempre en una fila)
        b1.setSpacing(D.px(D.M1))
        self.btn_listen = D.BotonIcono("play", TIP_ESCUCHAR)
        self.btn_apply = D.BotonIcono("check", TIP_APLICAR)
        self.btn_reject = D.BotonIcono("x", TIP_IGNORAR)
        self.btn_restore = D.BotonIcono("rotate-ccw", TIP_RESTAURAR)
        self.btn_listen.clicked.connect(lambda: self.listen())
        self.btn_apply.clicked.connect(lambda: self.apply_selected())
        self.btn_reject.clicked.connect(lambda: self.reject_selected())
        self.btn_restore.clicked.connect(lambda: self.restore_selected())
        for b in (self.btn_listen, self.btn_apply, self.btn_reject, self.btn_restore):
            b1.addWidget(b)
        b1.addStretch(1)
        v3.addLayout(b1)
        # (el pie: una línea fina encima, la revisión guiada de solo icono y «Aplicar todas»)
        v3.addSpacing(D.px(D.M1))
        v3.addWidget(D.LineaSeparadora())
        pie = QHBoxLayout()
        pie.setContentsMargins(0, D.px(D.M1), 0, 0)
        pie.setSpacing(D.px(D.M1))
        self.btn_quick = QPushButton("Revisión guiada")          # (función principal: con su nombre a la vista)
        self.btn_quick.setIcon(D.icono("keyboard"))
        self.btn_quick.setToolTip("Revisión guiada de la voz\nRecorre una a una las propuestas pendientes y los cortes "
                                  "dudosos, con teclas: Enter aceptar, Supr rechazar, → saltar (Ctrl+Shift+Q = todo el "
                                  "video)")
        self.btn_quick.clicked.connect(lambda: self.quick_review_requested.emit())
        self.btn_apply_all = QPushButton("Aplicar todas las de la lista")
        self.btn_apply_all.setIcon(D.icono("check-check"))
        self.btn_apply_all.setToolTip("Corta de una vez todas las pendientes que se ven en la lista (pregunta antes; "
                                      "Ctrl+Z lo deshace)")
        self.btn_apply_all.clicked.connect(lambda: self.apply_all_visible())
        pie.addWidget(self.btn_quick, 1)
        pie.addWidget(self.btn_apply_all, 1)
        v3.addLayout(pie)
        # Limpio, como Resolve: arriba la narración y cómo va; lo demás, en pestañas
        from .tabs import tabbed, untitle
        self.sec1.header.hide()
        self.sec1.set_expanded(True)
        untitle(box3)
        self.tabs = tabbed([("Transcribir", [self.sec1]), ("Limpiar", [self.limpiar_vista]),
                            ("Sugerencias", [box3], True)], clave="limpieza")
        for i in range(self.tabs.count()):              # (sin emojis de colores en los títulos: sobrio)
            if self.tabs.tabText(i) in ("Limpiar", "Sugerencias"):
                self.tabs._secs[i].head.setText(self.tabs.tabText(i))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(content)
        outer.addWidget(self.tabs, 1)

        self._list_timer = QTimer(self)
        self._list_timer.setSingleShot(True)
        self._list_timer.setInterval(120)
        self._list_timer.timeout.connect(self._rebuild_list)
        ctrl.media_changed.connect(self._refresh_media)
        ctrl.project_changed.connect(self._list_timer.start)
        ctrl.project_replaced.connect(self._refresh_media)
        ctrl.transcript_changed.connect(lambda _m: self._update_state())
        self._refresh_media()
        self.precargar_al_pasar(self.btn_transcribe)

    def precargar_al_pasar(self, boton):
        """⚡ Al pasar el ratón por ese botón (Transcribir, ⚡ Subtítulos) el modelo de voz empieza a cargarse: al
        pulsarlo ya está listo. Solo entonces ocupa memoria de la tarjeta (el usuario: «al pasar el ratón»)."""
        boton.installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Enter and isinstance(obj, QPushButton) and obj.isEnabled():
            self._precargar()
        return super().eventFilter(obj, ev)

    def _precargar(self, *_):
        """⚡ El modelo de voz se va cargando en segundo plano: al pulsar «Transcribir» ya está listo (en la tarjeta,
        10–17 s menos de espera). Sin ventana (pruebas), nada."""
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() in ("offscreen", "minimal") or self.job is not None:
            return
        key = self.model_combo.currentData()
        if key:
            transcription.precargar(key)

    # ------------------------------------------------------------ opciones
    def _load_options(self):
        s = self.settings
        d = voice_cleanup.CleanupOptions()
        migrar_ajustes_limpieza(s)
        defecto = {"silence": d.silences, "filler": d.fillers, "filler_soft": d.soft_fillers,
                   "repeat": d.repeated_words, "retake": d.retakes, "noise": d.noises, "similar": d.similar,
                   "doubt": d.doubtful, "clipping": d.clipping}
        self._cargando = True                   # (cargar no es «el usuario cambió una casilla»)
        try:
            for fila, ajuste in AJUSTE_MARCAR.items():
                self.tabla.casilla(fila, "marcar").setChecked(_si(s.value(f"limpieza/{ajuste}"), defecto[fila]))
            for k, chk in self.auto_chk.items():
                chk.setChecked(_si(s.value(f"limpieza_auto/{k}"), voice_cleanup.AUTO_DEFAULTS[k]))
        finally:
            self._cargando = False
        try:
            self.min_sil.setValue(float(s.value("limpieza/min_silencio", d.min_silence)))
            self.keep.setValue(float(s.value("limpieza/pausa", d.keep_pause)))
        except (TypeError, ValueError):
            self.min_sil.setValue(d.min_silence)
            self.keep.setValue(d.keep_pause)
        self.my_fillers.setText(str(s.value("limpieza/mis_muletillas", "")))
        from ..ai import verbatim
        ok, why = verbatim.available()
        self.chk_literal.setEnabled(ok)
        self.chk_literal.setChecked(ok and str(s.value("transcripcion/literal", True)).lower() in ("true", "1"))
        if not ok:
            self.chk_literal.setToolTip(self.chk_literal.toolTip() + f"\n\nNo disponible: {why}")
        from ..core import hw
        por_defecto = "rapido" if hw.equipo()["modesto"] else "equilibrado"   # (PC modesto: el modelo ligero)
        idx = self.model_combo.findData(s.value("transcripcion/modelo", por_defecto))
        self.model_combo.setCurrentIndex(max(0, idx))
        idx = self.lang_combo.findData(s.value("transcripcion/idioma", "es"))
        self.lang_combo.setCurrentIndex(max(0, idx))

    def options(self) -> voice_cleanup.CleanupOptions:
        o = voice_cleanup.CleanupOptions(
            silences=self.chk_sil.isChecked(), min_silence=self.min_sil.value(),
            keep_pause=self.keep.value(), noises=self.chk_noise.isChecked(),
            fillers=self.chk_fill.isChecked(), soft_fillers=self.chk_fill_soft.isChecked(),
            repeated_words=self.chk_rep.isChecked(),
            retakes=self.chk_take.isChecked(), similar=self.chk_similar.isChecked(),
            doubtful=self.chk_doubt.isChecked(), clipping=self.chk_clip.isChecked(),
            my_fillers=tuple(x.strip() for x in self.my_fillers.text().split(",") if x.strip()))
        s = self.settings
        for key, val in (("silencios", o.silences), ("min_silencio", o.min_silence), ("pausa", o.keep_pause),
                         ("ruidos", o.noises), ("muletillas", o.fillers), ("muletillas_posibles", o.soft_fillers),
                         ("repetidas", o.repeated_words),
                         ("tomas", o.retakes), ("parecidas", o.similar), ("dudosas", o.doubtful),
                         ("saturacion", o.clipping), ("mis_muletillas", self.my_fillers.text().strip())):
            s.setValue(f"limpieza/{key}", val)
        s.setValue("transcripcion/modelo", self.model_combo.currentData())
        s.setValue("transcripcion/idioma", self.lang_combo.currentData())
        if self.chk_literal.isEnabled():
            s.setValue("transcripcion/literal", self.chk_literal.isChecked())
        return o

    def _casilla_cambiada(self, fila: str, col: str, on: bool):
        """Una casilla de la tabla: se guarda al momento. «Quitar» necesita «Marcar» (para quitarlo, la IA tiene que
        encontrarlo): marcar «Quitar» marca «Marcar»; desmarcar «Marcar» desmarca «Quitar» y, al volver a marcarla,
        «Quitar» vuelve a estar como estaba."""
        if self._cargando:
            return
        recordado = self._quitar_recordado
        if col == "quitar":
            self.settings.setValue(f"limpieza_auto/{fila}", on)
            if not self._por_marcar:
                recordado.pop(fila, None)               # (lo cambió el usuario: manda lo nuevo)
            marcar = self.tabla.casilla(fila, "marcar")
            if on and marcar is not None and not marcar.isChecked():
                marcar.setChecked(True)
            self.cut_rules_changed.emit()
        else:
            self.settings.setValue(f"limpieza/{AJUSTE_MARCAR[fila]}", on)
            quitar = self.tabla.casilla(fila, "quitar")
            if quitar is None:
                return
            self._por_marcar = True
            try:
                if not on and quitar.isChecked():
                    recordado[fila] = True
                    quitar.setChecked(False)
                elif on and recordado.pop(fila, False) and not quitar.isChecked():
                    quitar.setChecked(True)
            finally:
                self._por_marcar = False

    def _poner_resultado(self, corto: str, largo: str = ""):
        """El resultado de la última tarea: corto en la línea de estado, entero en su tooltip."""
        self._result_corto = corto
        self._result_msg = largo or corto

    # ----------------------------------------------------------- narración
    def media_id(self) -> str | None:
        return self.media_combo.currentData()

    def _refresh_media(self):
        current = self.media_id()
        p = self.ctrl.project
        items = [m for m in p.media.values()
                 if m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)]
        items.sort(key=lambda m: self._orden_narracion(m))
        self.media_combo.blockSignals(True)
        self.media_combo.clear()
        for m in items:
            self.media_combo.addItem(m.name, m.id)
        idx = self.media_combo.findData(current)
        self.media_combo.setCurrentIndex(idx if idx >= 0 else (0 if items else -1))
        self.media_combo.blockSignals(False)
        self._on_media_changed()

    def _orden_narracion(self, m):
        """🎙 Lo que más parece tu narración, primero: la categoría «Narración»; luego lo que está en la línea de
        tiempo (lo más largo); los efectos de sonido y lo muy corto (un clic de cámara, un golpe…), al final."""
        p = self.ctrl.project
        cat = (m.category or "").lower()
        efecto = any(w in cat for w in ("efecto", "sonido", "sfx", "música", "music")) or \
            0 < float(m.duration or 0) < 15
        en_linea = sum(c.duration for c in p.clips.values() if c.media_id == m.id)
        return (m.category != "Narración", efecto, -en_linea, -float(m.duration or 0), m.name.lower())

    def _on_media_changed(self):
        self._poner_resultado("")
        self.media_selected.emit(self.media_id() or "")
        self._update_state()
        self._rebuild_list()

    def _poner_narr_info(self):
        """La línea «Narración: …» de Limpieza (la elección está en 📝 Transcripción)."""
        lbl = getattr(self, "narr_info", None)
        if lbl is None:
            return
        nombre = self.media_combo.currentText()
        lbl.setText(nombre if nombre else "Ninguna narración")
        lbl.poner_tooltip_extra("Narración (tu voz): " + (nombre or "ninguna") + "\nSe elige en «Voz y texto → 1 · "
                                "Transcribir»")

    def _ir_a_narracion(self):
        win = self.window()
        if hasattr(win, "abrir_seccion"):
            win.abrir_seccion("voz_texto", "transcribir")   # («1 · Transcribir», con la narración arriba)
            self.media_combo.setFocus()

    def _update_state(self):
        self._poner_narr_info()
        mid = self.media_id()
        p = self.ctrl.project
        busy = self.job is not None
        has = bool(mid)
        tr = p.transcripts.get(mid) if mid else None
        self.btn_transcribe.setEnabled(has and not busy)
        a_medias = bool(tr) and tr.get("hasta") is not None
        self.btn_transcribe.setText("🎙 Seguir transcribiendo" if a_medias else
                                    "🎙 Transcribir de nuevo" if tr else "🎙 Transcribir y analizar")
        self.btn_analyze.setEnabled(has and not busy)
        on_timeline = bool(mid and mapping.clips_of_media(p, mid))
        if not has:
            self.banner.setText("Importa tu narración en Medios.")
        elif not on_timeline:
            self.banner.setText("La narración no está en la línea de tiempo")   # (20/11: el detalle, al tooltip)
            self.banner.setToolTip("Puedes transcribirla igualmente, pero para aplicar cortes tiene que estar en la "
                                   "línea de tiempo.")
        self.banner.setVisible(not has or not on_timeline)
        self.banner_btn.setVisible(has and not on_timeline)
        punto = getattr(self, "narr_punto", None)
        if punto is not None:                   # (gris = nada · ámbar = sin transcribir · verde = listo)
            punto.setEstado("listo" if tr and not a_medias else "pendiente" if has else "nada")
            punto.setToolTip("Transcrita" if tr and not a_medias else "Sin transcribir del todo" if has else
                             "Ninguna narración")
        if not busy:                            # (estado corto; la explicación, en el tooltip)
            if a_medias:
                corto = f"Transcrita hasta {fmt_time(float(tr['hasta']))}"
                largo = "La transcripción se cortó. Pulsa «Seguir transcribiendo» para el resto."
            elif tr:
                corto = f"Transcrita · {len(tr.get('words', []))} palabras"
                largo = "El texto está en la pestaña «Texto»."
            elif has:
                corto, largo = "Sin transcribir", "La primera vez se descargará el modelo de voz."
            else:
                corto, largo = "Sin narración", "Importa tu narración en Medios."
            if self._result_corto:
                corto += f" · {self._result_corto}"
                largo += f"\n{self._result_msg}"
            self.status.setText(corto)
            self.status.setToolTip(largo)
        # Con sugerencias ya hechas, se enseña su pestaña directamente
        has_sug = bool(mid) and any(s.media_id == mid for s in p.suggestions)
        if not busy and has_sug != getattr(self, "_had_sug", None):
            self._had_sug = has_sug
            if hasattr(self, "tabs"):               # (por nombre: «Transcribir» se fue a la pestaña IA)
                quiero = "Sugerencias" if has_sug else "Limpiar"
                for i in range(self.tabs.count()):
                    if self.tabs.tabText(i) == quiero:
                        self.tabs.setCurrentIndex(i)
                        break

    def _add_narration_to_timeline(self):
        mid = self.media_id()
        tracks = [t for t in self.ctrl.project.tracks if t.kind == TRACK_AUDIO]
        if mid and tracks:
            m = self.ctrl.project.media[mid]
            self.ctrl.add_media([mid], tracks[0].id if m.kind == KIND_AUDIO else None, 0.0)
            self._update_state()
        elif not mid:
            self.ctrl.message.emit("Elige antes tu narración (el archivo de tu voz) arriba, en este panel.")
        else:
            self.ctrl.message.emit("No hay ninguna pista de audio: añade una (clic derecho en la línea de tiempo → "
                                   "Añadir pista de audio).")

    # ------------------------------------------------------------- tareas
    def _start_job(self, fn, on_done, label, on_partial=None):
        self.job = BackgroundJob(fn, self, with_partial=on_partial is not None)
        if on_partial is not None:
            self.job.partial.connect(on_partial)
        self.job.progress.connect(self._on_progress)
        self.job.done.connect(on_done)
        self.job.failed.connect(self._on_failed)
        self.job.finished.connect(self._on_job_finished)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.btn_cancel.setVisible(True)
        self.status.setText(label)
        self._update_state()
        self.job.start()

    def _on_progress(self, frac, text):
        if frac <= 0:
            self.progress.setRange(0, 0)  # barra "ocupada" (p. ej. descargando el modelo)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(frac * 1000))
        hasta = getattr(self, "_hasta", None)
        self.status.setText(text + (f" · texto hasta {fmt_time(hasta)}" if hasta else ""))
        self.status.setToolTip(f"El texto hasta {fmt_time(hasta)} ya se puede usar (Texto, subtítulos, palabras "
                               "clave…) mientras se transcribe el resto." if hasta else "")

    def _on_failed(self, msg):
        if msg == "Cancelado.":
            self._poner_resultado("Cancelado")
        else:
            self._poner_resultado("No se pudo completar", f"No se pudo completar: {msg}")
        if msg != "Cancelado.":
            QMessageBox.warning(self, "No se pudo completar", msg)

    def _on_job_finished(self):
        self._hasta = None
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self._update_state()

    def _cancel(self):
        if self.job:
            self.job.cancel()
            self.status.setText("Cancelando… (termina el fragmento actual)")

    def shutdown(self):
        """Al cerrar el programa: detener cualquier tarea en curso."""
        job = self.job
        if job is not None and job.isRunning():
            job.cancel()
            if not job.wait(8000):
                job.terminate()
                job.wait(2000)

    def transcribe(self, analyze: bool = True):
        """🎙 Transcribir. analyze=False (lo pide «⚡ Subtítulos»): solo el texto, rápido; sin buscar
        bostezos, titubeos, respiraciones ni tomas repetidas (el usuario: «que no se active de manera automática cuando
        vaya a subtitular»). Eso se puede analizar después con «Transcribir y analizar» / «Analizar»."""
        mid = self.media_id()
        if not mid or self.job:
            return
        ok, why = transcription.is_available()
        if not ok:
            QMessageBox.warning(self, "Transcripción", why)
            return
        prev = self.ctrl.project.transcripts.get(mid)
        start_at = 0.0
        if prev and prev.get("hasta") is not None:            # 📝 se cortó a medias: seguir desde ahí
            hasta = float(prev["hasta"])
            r = QMessageBox.question(self, "Transcripción a medias",
                                     f"Esta narración está transcrita hasta {fmt_time(hasta)}.\n\n"
                                     "Sí = seguir desde ahí (lo hecho se queda) · No = empezar de cero",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return
            start_at = hasta if r == QMessageBox.Yes else 0.0
        elif prev:
            r = QMessageBox.question(self, "Transcribir de nuevo",
                                     "Esta narración ya está transcrita. Si la transcribes de nuevo "
                                     "se perderán las correcciones que hiciste en el texto.\n\n¿Continuar?")
            if r != QMessageBox.Yes:
                return
        path = self.ctrl.project.media[mid].path
        model, lang, opts = self.model_combo.currentData(), self.lang_combo.currentData(), self.options()
        literal = analyze and self.chk_literal.isEnabled() and self.chk_literal.isChecked()
        import copy
        prev = copy.deepcopy(prev) if prev else prev        # (el hilo no lee lo que el usuario esté cambiando)
        # al empezar de cero con una transcripción anterior: los bloques solo cuando pasen de lo que ya había (si
        # se cancela, lo anterior sigue ahí)
        tope = float("inf") if (prev and start_at == 0 and prev.get("hasta") is None) else \
            (float(prev["hasta"]) if prev and start_at == 0 else 0.0)

        def work(progress, cancelled, emit):
            progress(0.0, "Leyendo el audio…")
            samples = self.audio.get(path)
            def part(lo, hi):        # con la escucha literal, cada paso es media barra
                return lambda f, t: progress(lo + (hi - lo) * f, t)
            # 📝 por bloques: cada 3 min de audio, lo hecho llega a la línea de tiempo (del segundo 0 al final)
            tr = transcription.transcribe(samples, model, lang, part(0.0, 0.5) if literal else progress, cancelled,
                                          fillers=analyze, start_at=start_at,
                                          partial=lambda t: emit((mid, t)) if t["hasta"] > tope else None,
                                          prev=prev if start_at else None)
            if literal:
                from ..ai import align, verbatim
                try:
                    tr = verbatim.recover(samples, tr, model, lang, part(0.5, 1.0), cancelled)
                finally:
                    align.unload()
            tr = voice_cleanup.refine_transcript(samples, SR, tr)      # (tiempos finos: subtítulos a tiempo)
            if not analyze:
                return mid, tr, None, opts
            progress(1.0, "Analizando la narración…")
            items = voice_cleanup.analyze(samples, SR, tr["words"], opts, None, cancelled)
            return mid, tr, items, opts

        self._start_job(work, self._on_transcribed, "Preparando…", on_partial=self._on_partial)

    def _on_partial(self, res):
        """📝 Un bloque más: las palabras hasta ahí ya se pueden usar (Texto, subtítulos, palabras clave, cortes…)."""
        mid, tr = res
        if mid not in self.ctrl.project.media:
            return
        self._hasta = float(tr.get("hasta") or 0.0)
        self.ctrl.set_transcript(mid, tr)
        self.ctrl.message.emit(f"📝 Texto listo hasta {fmt_time(self._hasta)}: ya puedes usarlo mientras se "
                               "transcribe el resto.")

    def _on_transcribed(self, result):
        mid, tr, items, opts = result
        if mid not in self.ctrl.project.media:     # (el proyecto se reinició mientras tanto: no se mete en el nuevo)
            return
        self.ctrl.set_transcript(mid, tr)
        if self.ctrl.project.subtitles.media_id not in self.ctrl.project.transcripts:
            self.ctrl.set_subtitle_style("Texto de los subtítulos", media_id=mid)
        if items is None:                          # (solo el texto, para los subtítulos: sin sugerencias)
            self._poner_resultado("sin analizar", "Solo el texto: sin buscar errores al hablar.")
            self._update_state()
            return
        self._store_suggestions(mid, items, opts)

    def analyze(self):
        mid = self.media_id()
        if not mid or self.job:
            return
        path = self.ctrl.project.media[mid].path
        words = self.ctrl.project.transcripts.get(mid, {}).get("words")
        opts = self.options()

        def work(progress, cancelled):
            progress(0.0, "Leyendo el audio…")
            samples = self.audio.get(path)
            return mid, voice_cleanup.analyze(samples, SR, words, opts, progress, cancelled), opts

        self._start_job(work, lambda r: self._store_suggestions(*r), "Analizando…")

    def _store_suggestions(self, mid, items, opts):
        cuttable = {k: v[1] for k, v in voice_cleanup.KINDS.items()}
        self.ctrl.set_suggestions(mid, items, opts.kinds(), cuttable)
        n = len(items)
        no_words = not self.ctrl.project.transcripts.get(mid)
        self._poner_resultado(f"{n} sugerencias",
                              f"{n} sugerencias. Revísalas en «Sugerencias»: todavía no se ha cortado nada."
                              + (" (Sin transcripción solo se buscan silencios y saturación.)" if no_words else ""))
        self.f_status.setCurrentIndex(0)
        self._update_state()
        if getattr(self, "auto_after", None) is not None and self.auto_after.isChecked():
            self.auto_clean(ask=False)

    # --------------------------------------------------------- sugerencias
    def _visible_suggestions(self):
        mid = self.media_id()
        status, kind = self.f_status.currentData(), self.f_kind.currentData()
        return [s for s in self.ctrl.project.suggestions
                if s.media_id == mid and s.kind in voice_cleanup.KINDS
                and (not status or s.status == status) and (not kind or s.kind == kind)]

    def _timeline_time(self, s) -> float | None:
        p = self.ctrl.project
        if s.status == SUG_APPLIED:
            f = mapping.find_cut(p, s.media_id, s.applied_start, s.applied_end)
            return f[2] if f else None
        parts = mapping.map_range(p, s.media_id, s.start, s.end)
        return parts[0][1] if parts else None

    def _rebuild_list(self):
        selected = set(self.selected_ids())
        self.tree.blockSignals(True)
        self.tree.clear()
        p = self.ctrl.project
        mid = self.media_id()
        all_s = [s for s in p.suggestions if s.media_id == mid and s.kind in voice_cleanup.KINDS]
        for s in self._visible_suggestions():
            t = self._timeline_time(s)
            when = fmt_time(t) if t is not None else "—"
            it = QTreeWidgetItem([when, s.label, STATUS_TEXT.get(s.status, s.status)])
            it.setIcon(0, self._icons.get(s.kind, QIcon()))
            it.setData(0, Qt.UserRole, s.id)
            tip = s.label + (f"\n{s.detail}" if s.detail else "")
            if t is None and s.status == SUG_PENDING:
                tip += "\n(Este fragmento no está en la timeline)"
                it.setForeground(0, QColor("#6b7280"))
            for col in range(3):
                it.setToolTip(col, tip)
            if s.status == SUG_APPLIED:
                it.setForeground(2, QColor("#57ab5a"))
            elif s.status == SUG_REJECTED:
                for col in range(3):
                    it.setForeground(col, QColor("#6b7280"))
            if not s.cuttable:
                it.setText(2, "Solo aviso" if s.status == SUG_PENDING else it.text(2))
            self.tree.addTopLevelItem(it)
            if s.id in selected:
                it.setSelected(True)
        self.tree.blockSignals(False)
        pend = [s for s in all_s if s.status == SUG_PENDING and s.cuttable]
        secs = sum(s.end - s.start for s in pend if s.kind != "retake")
        n_app = sum(1 for s in all_s if s.status == SUG_APPLIED)
        self.summary.setText(f"{len(pend)} pendientes (~{secs:.1f} s que se pueden quitar) · "
                             f"{n_app} aplicadas" if all_s else "Todavía no hay sugerencias.")
        # (🎨 20/11: sin ninguna sugerencia, solo esa línea —ni la tabla vacía de 220 px ni los filtros ni los iconos—;
        #  con sugerencias, aunque el filtro no deje ver ninguna, todo a la vista para poder cambiarlo)
        hay = bool(all_s)
        for w_ in (self.tree, self.f_status, self.f_kind, self.btn_listen, self.btn_apply, self.btn_reject,
                   self.btn_restore, self.detail):
            if w_.isHidden() == hay:
                w_.setVisible(hay)
        self.btn_apply_all.setText(f"Aplicar todas las de la lista ({self.tree.topLevelItemCount()})")
        self._on_selection()

    def selected_ids(self) -> list[str]:
        return [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]

    def _selected(self):
        ids = set(self.selected_ids())
        return [s for s in self.ctrl.project.suggestions if s.id in ids]

    def select_suggestion(self, sid: str):
        """Seleccionar desde la timeline."""
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) == sid:
                self.tree.clearSelection()
                it.setSelected(True)
                self.tree.scrollToItem(it)
                return

    def _on_selection(self):
        sel = self._selected()
        one = sel[0] if len(sel) == 1 else None
        self.detail.setText((one.label + ("\n" + one.detail if one.detail else "")) if one else
                            (f"{len(sel)} seleccionadas" if sel else ""))
        self.btn_listen.setEnabled(one is not None)
        self.btn_apply.setEnabled(any(s.status == SUG_PENDING and s.cuttable for s in sel))
        self.btn_reject.setEnabled(any(s.status != SUG_APPLIED for s in sel))
        if sel and all(s.status == SUG_REJECTED for s in sel):
            self.btn_reject.poner_icono("undo-2", TIP_RECUPERAR)
        else:
            self.btn_reject.poner_icono("x", TIP_IGNORAR)
        self.btn_restore.setEnabled(any(s.status == SUG_APPLIED for s in sel))
        if one and one.kind == "retake" and one.status == SUG_PENDING:
            self.btn_apply.poner_icono("list-checks", TIP_ELEGIR_TOMA)     # (otra acción, otro icono)
            self.btn_listen.poner_icono("columns-2", TIP_COMPARAR)
        else:
            self.btn_apply.poner_icono("check", TIP_APLICAR)
            self.btn_listen.poner_icono("play", TIP_ESCUCHAR)
        self.suggestion_selected.emit(one.id if one else "")

    def listen(self):
        sel = self._selected()
        if len(sel) != 1:
            return
        s = sel[0]
        p = self.ctrl.project
        if s.status == SUG_APPLIED:
            f = mapping.find_cut(p, s.media_id, s.applied_start, s.applied_end)
            if f:
                self.engine.play_ranges([(f[2] - 2.0, f[2] + 2.0)])
            return
        if s.kind == "retake" and s.alt_start is not None:
            r1 = mapping.map_range(p, s.media_id, s.start, s.end)
            r2 = mapping.map_range(p, s.media_id, s.alt_start, s.alt_end)
            ranges = [(r[0][1] - 0.2, r[-1][2] + 0.2) for r in (r1, r2) if r]
            self.engine.play_ranges(ranges)
            return
        parts = mapping.map_range(p, s.media_id, s.start, s.end)
        if not parts:
            self.ctrl.message.emit("Ese fragmento no está en la timeline.")
            return
        self.engine.play_ranges([(parts[0][1] - 1.0, parts[-1][2] + 1.0)])

    def apply_selected(self):
        sel = [s for s in self._selected() if s.status == SUG_PENDING and s.cuttable]
        if not sel:
            return
        if len(sel) == 1 and sel[0].kind == "retake":
            menu = QMenu(self)
            best = (sel[0].data or {}).get("best", 2)
            star = "  ⭐ la recomienda la IA"
            a2 = menu.addAction("Quedarme con la TOMA 2 (quitar la 1)" + (star if best == 2 else ""))
            a1 = menu.addAction("Quedarme con la TOMA 1 (quitar la 2)" + (star if best == 1 else ""))
            if (sel[0].data or {}).get("reason"):
                info = menu.addAction("Por qué: " + sel[0].data["reason"])
                info.setEnabled(False)
            menu.addSeparator()
            both = menu.addAction("Mantener ambas (ignorar)")
            cmp_ = menu.addAction("▶ Comparar primero")
            chosen = menu.exec(self.btn_apply.mapToGlobal(self.btn_apply.rect().bottomLeft()))
            if chosen is a2:
                self.ctrl.apply_suggestions([sel[0].id], keep_first=False)
            elif chosen is a1:
                self.ctrl.apply_suggestions([sel[0].id], keep_first=True)
            elif chosen is both:
                self.ctrl.reject_suggestions([sel[0].id])
            elif chosen is cmp_:
                self.listen()
            return
        self.ctrl.apply_suggestions([s.id for s in sel])

    def reject_selected(self):
        sel = [s for s in self._selected() if s.status != SUG_APPLIED]
        if sel:
            unreject = all(s.status == SUG_REJECTED for s in sel)
            self.ctrl.reject_suggestions([s.id for s in sel], rejected=not unreject)

    def restore_selected(self):
        sel = [s for s in self._selected() if s.status == SUG_APPLIED]
        if sel:
            self.ctrl.restore_suggestions([s.id for s in sel])

    def auto_candidates(self) -> list:
        """Sugerencias pendientes que la limpieza automática quitaría con las casillas marcadas (lo que tachaste o
        destachaste en el texto manda)."""
        mid = self.media_id()
        on = {k for k, chk in self.auto_chk.items() if chk.isChecked()}
        return [s for s in self.ctrl.project.suggestions if s.media_id == mid and voice_cleanup.will_cut(s, on)]

    def auto_clean(self, ask: bool = True) -> int:
        """⚡ Aplica de una vez las sugerencias elegidas (muletillas, repeticiones, mejores tomas…)."""
        sugs = self.auto_candidates()
        if not sugs:
            self.ctrl.message.emit("No hay nada pendiente que limpiar con esas casillas "
                                   "(¿ya transcribiste y analizaste la narración?).")
            return 0
        counts = {}
        for s in sugs:
            name = voice_cleanup.KINDS.get(s.kind, (s.kind,))[0]
            counts[name] = counts.get(name, 0) + 1
        summary = ", ".join(f"{n} {k.lower()}" for k, n in counts.items())
        if ask and QMessageBox.question(self, "Limpiar",
                                        f"Se quitarán: {summary}.\n\nEn las tomas repetidas se queda la que eligió "
                                        "la IA. Todo se deshace con un Ctrl+Z, o corte a corte con «↺ Restaurar»."
                                        ) != QMessageBox.Yes:
            return 0
        n = self.ctrl.apply_suggestions([s.id for s in sugs]) or 0
        if n:
            self.ctrl.message.emit(f"Limpieza: {summary}. Revisa en «Aplicadas» y restaura lo que quieras.")
        return n

    def apply_all_visible(self):
        sugs = [s for s in self._visible_suggestions() if s.status == SUG_PENDING and s.cuttable]
        retakes = [s for s in sugs if s.kind == "retake"]
        if not sugs:
            self.ctrl.message.emit("No hay sugerencias pendientes que aplicar en la lista.")
            return
        secs = sum(s.end - s.start for s in sugs)
        text = (f"Se aplicarán {len(sugs)} cortes (~{secs:.1f} s) en TODAS las pistas, "
                "cerrando los huecos.\n\nPodrás deshacerlo con Ctrl+Z o restaurar cortes uno a uno.")
        if retakes:
            text += (f"\n\nIncluye {len(retakes)} tomas repetidas: en cada una se quedará la que eligió la IA (⭐, "
                     "la más completa y limpia). Si prefieres revisarlas antes, filtra por tipo.")
        if QMessageBox.question(self, "Aplicar sugerencias", text) == QMessageBox.Yes:
            self.ctrl.apply_suggestions([s.id for s in sugs])
