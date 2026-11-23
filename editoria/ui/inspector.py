"""Panel derecho: propiedades del clip seleccionado / ajustes del proyecto, y pestaña de IA."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QInputDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

import json

import numpy as np

from ..core import equalizer as E
from ..core import media as media_tools
from ..core import transform
from . import diseno as D
from .eq_widget import EqGraph
from .help import set_help
from ..core.model import FORMATS, KIND_IMAGE, ORIGIN_AI, TRACK_AUDIO
from .common import fmt_time

RESOLUTIONS = [("1920 × 1080 (YouTube 1080p)", 1920, 1080), ("2560 × 1440 (YouTube 1440p)", 2560, 1440),
               ("3840 × 2160 (YouTube 4K)", 3840, 2160), ("1080 × 1920 (Shorts vertical)", 1080, 1920)]
FPS_OPTIONS = [24.0, 25.0, 30.0, 50.0, 60.0]


def _dim(text=""):
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(True)
    # Que un texto largo (p. ej. una ruta) nunca ensanche el panel
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


def _vd(lo, hi, paso, dec, unidad="", entero=False, **kw) -> D.ValorDeslizable:
    """Un número del diseño (deslizador fino + número que se escribe o se arrastra) en lugar de un QSpinBox."""
    return D.ValorDeslizable(lo, hi, paso, dec, unidad, entero=entero, **kw)


def _fila(etiqueta: str, control, tip: str = "") -> D.FilaInspector:
    """Fila etiqueta/control del diseño (la etiqueta gris en su columna fija)."""
    if not isinstance(control, QWidget):          # (un layout: dentro de un widget)
        w = QWidget()
        control.setContentsMargins(0, 0, 0, 0)
        w.setLayout(control)
        control = w
    return D.FilaInspector(etiqueta, control, tip)


def _muestras_espectro(path: str, src: float):
    """3 s de audio (mono, 16 kHz) para el espectro del ecualizador. Corre en segundo plano."""
    try:
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0, src - 1):.2f}",
                                   "-t", "3", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                                   "-f", "s16le", "-"], timeout=10)
        return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768 if r.returncode == 0 else None
    except Exception:  # noqa: BLE001 - el espectro es solo una ayuda visual
        return None


class InspectorPanel(QWidget):
    track_requested = Signal(str)   # «Seguir personaje u objeto» en este clip
    ramp_done = Signal(list)        # rampa de velocidad creada: seleccionar sus tramos
    def __init__(self, ctrl, engine=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self._ids: list[str] = []
        self._all_ids: list[str] = []
        self._audio_id: str | None = None
        self._loading = False

        self.monitor = None
        self._spectrum_key = None
        self._spectrum_timer = QTimer(self)
        self._spectrum_timer.setSingleShot(True)
        self._spectrum_timer.setInterval(350)
        self._spectrum_timer.timeout.connect(self._update_spectrum)
        self._trans_id: str | None = None           # 🎞 transición elegida en la línea de tiempo (clip de la derecha)
        self._modo = "proyecto"                     # proyecto | clip | audio | texto | varios | transicion
        self._pestana_codigo = False                # (el código cambia de pestaña: no cuenta como elección)
        self.secciones: dict = {}                   # clave → Seccion
        self._aplicados: dict = {}                  # efecto → su Seccion en la pestaña Efectos
        self._build_project_page()
        self._build_clip_page()
        self._build_multi_page()
        self._texto_tmp = self._build_text_page()   # (se guarda: lo que lleva pasa a sus secciones)
        # (sin desplazamiento propio: ya se desplaza todo el panel, a lo alto, y así nunca empuja ni aplasta la
        # timeline; una sola barra en vez de dos o tres, ↔ responsive)
        self._componer()
        self.eq_graph.installEventFilter(self)      # al mostrarse la gráfica del ecualizador, se calcula su espectro
        self.stack = _PaginaCompat(self)            # (lo de antes: 0 proyecto · 1 clip · 2 varios · 3 texto)
        self._un_paso_por_arrastre()                # (arrastrar un número = UN solo Ctrl+Z)
        ctrl.project_changed.connect(self._refresh)
        ctrl.media_changed.connect(self._refresh)
        if engine is not None:
            engine.time_changed.connect(lambda _t: self._refresh_framing())
            engine.time_changed.connect(lambda _t: (not engine.playing and self.eq_graph.isVisible()
                                                    and self._clip() is not None and self._spectrum_timer.start()))
        self._refresh()

    # -------------------------------------------------------------- arrastrar un número = un solo paso
    def _un_paso_por_arrastre(self):
        """Mientras arrastras el número o el deslizador de un ValorDeslizable se ve en vivo, pero todo el arrastre
        es UN solo paso de deshacer (los cambios van dentro de un «macro» del historial que se cierra al soltar).
        La velocidad, además, no se aplica hasta soltar (cada cambio rehace la pista con su ripple)."""
        self._paso_abierto = False
        self._vel_inicio = None
        for vd in self.findChildren(D.ValorDeslizable):
            if vd is self.speed:
                continue
            vd.antes_de_cambiar.connect(lambda vd=vd: self._abrir_paso(vd))
            vd.arrastre.connect(lambda on: None if on else self._cerrar_paso())
        self.speed.arrastre.connect(self._arrastre_velocidad)

    def _abrir_paso(self, vd):
        if self._paso_abierto or self._loading or not self._ids:
            return
        fila = vd.parentWidget()
        while fila is not None and not isinstance(fila, D.FilaInspector):
            fila = fila.parentWidget()
        nombre = fila.etiqueta.text() if fila is not None else "valor"
        self.ctrl.undo_stack.beginMacro(f"Ajustar {nombre.lower()}")
        self._paso_abierto = True

    def _cerrar_paso(self):
        if not self._paso_abierto:
            return
        self._paso_abierto = False
        st = self.ctrl.undo_stack
        st.endMacro()
        cmd = st.command(st.index() - 1)
        if cmd is not None and cmd.childCount() == 0:   # (nada cambió de verdad: sin paso vacío)
            st.undo()

    def hideEvent(self, ev):                    # noqa: N802
        self._cerrar_paso()                     # (oculto a mitad de arrastre: el paso de deshacer nunca queda abierto)
        super().hideEvent(ev)

    def _arrastre_velocidad(self, on: bool):
        if on:
            self._vel_inicio = self.speed.value()
            return
        inicio, self._vel_inicio = self._vel_inicio, None
        if inicio is not None and self.speed.value() != inicio:
            self._on_speed(speed=self.speed.value() / 100)

    # -------------------------------------------------------------- páginas
    def _build_project_page(self):
        """«Proyecto» (con nada elegido): formato, sonoridad, mezcla y música, narración y subtítulos."""
        w = self._g_formato = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        set_help(w, "proyecto")
        self.project_name = _dim()
        from . import diseno as D                   # (🎨 20/11: las filas del Inspector —misma columna de etiquetas—)
        self.format_combo = QComboBox()
        for key, (label, _w, _h) in FORMATS.items():
            self.format_combo.addItem(label, key)
        self.format_combo.currentIndexChanged.connect(self._on_format)
        self.res_combo = QComboBox()
        for label, _w, _h in RESOLUTIONS:
            self.res_combo.addItem(label)
        self.fps_combo = QComboBox()
        for f in FPS_OPTIONS:
            self.fps_combo.addItem(f"{f:g} fps")
        self.res_combo.currentIndexChanged.connect(self._on_res)
        self.fps_combo.currentIndexChanged.connect(self._on_fps)
        for cb in (self.format_combo, self.res_combo, self.fps_combo):
            D.alto_fijo(cb)
        self.project_stats = _dim()
        lay.setSpacing(D.px(D.M1))
        lay.addWidget(self.project_name)
        lay.addWidget(D.FilaInspector("Tipo", self.format_combo, "Para qué es el video (cambia su forma)"))
        lay.addWidget(D.FilaInspector("Resolución", self.res_combo, "El tamaño en píxeles del video exportado"))
        lay.addWidget(D.FilaInspector("Fotogramas", self.fps_combo, "Fotogramas por segundo del video exportado"))
        lay.addWidget(self.project_stats)
        # 📊 Sonoridad
        g = self._g_sonoridad = QWidget()
        v = QVBoxLayout(g)
        v.setContentsMargins(0, 0, 0, 0)
        self.chk_loudnorm = QCheckBox("Normalizar a −14 LUFS al exportar")
        self.chk_loudnorm.setToolTip("Al exportar, el volumen final se ajusta solo a −14 LUFS con el pico ≤ −1 dBTP "
                                     "(lo que piden YouTube, TikTok e Instagram)")
        self.chk_loudnorm.toggled.connect(lambda on: self._loading or self.ctrl.set_settings(loudnorm=bool(on)))
        self.btn_lufs = QPushButton("Medir la sonoridad (LUFS)")
        self.btn_lufs.setToolTip("Mide toda la mezcla (en segundo plano) y te dice cuántos dB subir o bajar; puedes "
                                 "aplicarlo con un Ctrl+Z para deshacerlo (lo mismo que «LUFS» del visor)")
        self.btn_lufs.clicked.connect(self._medir_lufs)
        v.addWidget(self.chk_loudnorm)
        v.addWidget(self.btn_lufs)
        # 🎚 Mezcla y música · 🗣 Narración · ❞ Subtítulos (sus paneles completos, a un clic)
        self.mezcla_info = _dim()
        self.narracion_info = _dim()
        self.chk_subs = QCheckBox("Subtítulos en el video")
        self.chk_subs.setToolTip("Enciende o apaga los subtítulos del proyecto (su estilo, en el panel Subtítulos)")
        self.chk_subs.toggled.connect(lambda on: self._loading or self.ctrl.set_subtitle_style(
            "Subtítulos " + ("activados" if on else "desactivados"), enabled=bool(on)))
        self._g_mezcla = self._caja_panel(self.mezcla_info, "Abrir Mezcla y música", "audio_mix",
                                          "Música, bajar la música cuando hablas y la mezcla de la IA")
        self._g_narracion = self._caja_panel(self.narracion_info, "Abrir Voz IA (narración)", "voz_ia",
                                             "Narración con voz sintética o grabada")
        self._g_subtitulos = self._caja_panel(self.chk_subs, "Abrir Subtítulos", "subtitles",
                                              "Letra, colores, posición y animación de los subtítulos")

    def _caja_panel(self, arriba: QWidget, texto: str, panel: str, tip: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(arriba)
        b = QPushButton(texto)
        b.setToolTip(tip)
        b.clicked.connect(lambda: self._abrir_panel(panel))
        v.addWidget(b)
        return w

    def _abrir_panel(self, clave: str):
        win = self.window()
        d = (getattr(win, "docks", None) or {}).get(clave)
        if d is not None and hasattr(win, "show_panel"):
            win.show_panel(getattr(d, "panel", None) or d.widget())

    def _medir_lufs(self):
        lo = getattr(self.engine, "loudness", None)
        if lo is not None:
            lo.start(self.window())

    def _build_clip_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.clip_title = QLabel()
        self.clip_title.setObjectName("title")
        self.clip_title.setWordWrap(True)
        self.clip_origin = QLabel()
        self.clip_origin.setWordWrap(True)
        info = QGroupBox("Información")
        form = QFormLayout(info)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)     # (cada dato debajo de su nombre: nunca se corta)
        self.clip_file = _dim()
        self.clip_track = QLabel()
        self.clip_pos = QLabel()
        self.clip_dur = QLabel()
        self.clip_src = QLabel()
        form.addRow("Archivo", self.clip_file)
        form.addRow("Pista", self.clip_track)
        form.addRow("Posición", self.clip_pos)
        form.addRow("Duración", self.clip_dur)
        form.addRow("Fragmento original", self.clip_src)

        props = QGroupBox("Ajustes")
        pform = QFormLayout(props)
        self.volume = _vd(0, 200, 1, 0, "%", entero=True)
        self.volume.setToolTip("Volumen del clip (100 % = como se grabó)")
        self.volume.valueChanged.connect(self._on_volume)
        self.enabled = QCheckBox("Activo (se ve y se oye)")
        self.enabled.toggled.connect(self._on_enabled)
        self.locked = QCheckBox("Bloqueado")
        self.locked.setIcon(_glifo("🔒"))
        self.locked.setToolTip("Nadie, ni la IA, podrá modificar este clip hasta que lo desbloquees.")
        self.locked.toggled.connect(self._on_locked)
        pform.addRow(self.enabled)
        pform.addRow(self.locked)

        # --- Velocidad (como «Cambiar velocidad del clip» de Resolve, tecla R) ---
        self.speed_box = QGroupBox("Velocidad")
        sl = QVBoxLayout(self.speed_box)
        self.speed = _vd(10, 400, 5, 0, "%", entero=True)
        self.speed.setToolTip("100 % = normal · 50 % = cámara lenta · 200 % = el doble de rápido.\n"
                              "El clip se alarga o se acorta; su sonido vinculado también (sin voz de ardilla).")
        self.speed.valueChanged.connect(lambda v: None if self.speed.arrastrando() else self._on_speed(speed=v / 100))
        sl.addWidget(_fila("Velocidad", self.speed))
        row = QHBoxLayout()
        for pct in (25, 50, 100, 200, 400):
            b = QPushButton(f"{pct}%")
            b.setMinimumWidth(44)                   # (no fijo: con letra grande, «400%» cabe entero)
            b.clicked.connect(lambda _=False, v=pct: self._on_speed(speed=v / 100))
            row.addWidget(b)
        sl.addLayout(row)
        self.reverse = QCheckBox("◀ Hacia atrás (reversa)")
        self.reverse.toggled.connect(lambda on: self._on_speed(reverse=on))
        self.ripple_speed = QCheckBox("Mover lo que viene detrás")
        self.ripple_speed.setChecked(True)
        self.ripple_speed.setToolTip("Si el clip se alarga o se acorta, lo que hay detrás en su pista se mueve "
                                     "(sin tapar nada ni dejar huecos).")
        r2 = QHBoxLayout()
        r2.addWidget(self.reverse)
        r2.addWidget(self.ripple_speed)
        sl.addLayout(r2)
        self.smooth = QCheckBox("Cámara lenta suave")
        self.smooth.setToolTip("Inventa fotogramas (exportar tarda más). Como el Speed Warp de Resolve: al exportar, "
                               "los fotogramas que faltan se crean analizando el movimiento. Solo por debajo del 100 %.")
        self.smooth.toggled.connect(lambda on: self._loading or (self._ids and self.ctrl.set_clip_props(
            self._targets(), "Cámara lenta suave", smooth=on)))
        sl.addWidget(self.smooth)
        rr = QHBoxLayout()
        self.ramp = QComboBox()
        self.ramp.addItem("Rampa de velocidad…", "")
        for key, (name, _f) in self.ctrl.RAMPS.items():
            self.ramp.addItem(name, key)
        self.ramp.setToolTip("Divide el clip en tramos que cambian de velocidad poco a poco (típico de los edits).")
        self.ramp.activated.connect(self._on_ramp)
        self.btn_view_speed = QPushButton("Ver cómo queda")
        self.btn_view_speed.setIcon(D.icono("play"))
        self.btn_view_speed.setToolTip("Prepara unos segundos alrededor del cabezal tal como saldrán al exportar.")
        self.btn_view_speed.clicked.connect(self._view_here)
        rr.addWidget(self.ramp, 1)
        rr.addWidget(self.btn_view_speed)
        sl.addLayout(rr)
        self.btn_freeze = QPushButton("Congelar la imagen (Mayús+R)")
        self.btn_freeze.setIcon(D.icono("snowflake"))
        self.btn_freeze.setToolTip("La imagen se queda quieta desde el cabezal hasta el final del clip; "
                                   "el sonido sigue igual.")
        self.btn_freeze.clicked.connect(lambda: self._ids and self.ctrl.freeze_frame(self.engine.time, self._ids[0]))
        sl.addWidget(self.btn_freeze)
        self.speed_info = _dim()
        self.speed_info.setWordWrap(True)
        sl.addWidget(self.speed_info)

        # --- Encuadre y zoom ---
        self.frame_box = QGroupBox("Encuadre y zoom")
        fl = QFormLayout(self.frame_box)
        self.zoom = _vd(100, 600, 10, 0, "%", entero=True)
        self.zoom.setToolTip("Cuánto se acerca la imagen (100 % = sin zoom)")
        self.fx = _vd(0, 100, 1, 0, "%", entero=True)
        self.fx.setToolTip("Centro del zoom, de izquierda a derecha")
        self.fy = _vd(0, 100, 1, 0, "%", entero=True)
        self.fy.setToolTip("Centro del zoom, de arriba abajo")
        for spin in (self.zoom, self.fx, self.fy):
            spin.valueChanged.connect(self._on_framing)
        self.kf_label = QLabel()
        self.kf_label.setObjectName("dim")
        kb = QHBoxLayout()                          # (si no caben, bajan de fila: responsive)
        kb.setSpacing(D.px(D.M1))
        self.btn_prev_kf = D.BotonIcono("chevron-left", "Ir al fotograma clave anterior")
        self.btn_add_kf = QPushButton("Clave aquí")
        self.btn_add_kf.setIcon(D.icono("diamond-plus"))
        self.btn_add_kf.setToolTip("Añade un fotograma clave en el cabezal: el zoom se animará "
                                   "suavemente entre las claves.")
        self.btn_del_kf = QPushButton("Quitar clave")
        self.btn_del_kf.setIcon(D.icono("diamond-minus"))
        self.btn_del_kf.setToolTip("Quita el fotograma clave que está justo en el cabezal")
        self.btn_next_kf = D.BotonIcono("chevron-right", "Ir al fotograma clave siguiente")
        for b in (self.btn_prev_kf, self.btn_add_kf, self.btn_del_kf, self.btn_next_kf):
            kb.addWidget(b)
        self.btn_prev_kf.clicked.connect(lambda: self._jump_kf(-1))
        self.btn_next_kf.clicked.connect(lambda: self._jump_kf(1))
        self.btn_add_kf.clicked.connect(self._add_kf)
        self.btn_del_kf.clicked.connect(self._del_kf)
        self.btn_reset_zoom = QPushButton("Quitar zoom")
        self.btn_reset_zoom.clicked.connect(
            lambda: self._ids and self.ctrl.set_zoom_keyframes(self._ids[0], [], "Quitar zoom"))
        self.layout_combo = QComboBox()
        for name in transform.LAYOUTS:
            self.layout_combo.addItem(name)
        self.layout_combo.currentTextChanged.connect(self._on_layout)
        self.curve_zoom = self._curve_combo("zoom")
        fl.addRow(D.TituloSeccion("Zoom con claves"))
        fl.addRow(_fila("Zoom", self.zoom))
        fl.addRow(_fila("Centro X", self.fx))
        fl.addRow(_fila("Centro Y", self.fy))
        fl.addRow(kb)
        fl.addRow(self.kf_label, self.btn_reset_zoom)
        fl.addRow(_fila("Curva", self.curve_zoom))
        lay_row = QHBoxLayout()
        lay_row.addWidget(self.layout_combo, 1)
        self.btn_unstretch = QPushButton("Sin deformar")
        self.btn_unstretch.setToolTip("La imagen está estirada o aplastada (asas a media arista del visor). "
                                      "Esto le devuelve su proporción original, en la misma caja.")
        self.btn_unstretch.clicked.connect(self._unstretch)
        self.btn_unstretch.hide()
        lay_row.addWidget(self.btn_unstretch)
        fl.addRow(_fila("En pantalla", lay_row))
        # 🎞 Posición y tamaño animados (como los fotogramas clave de «Transformar» en Resolve)
        lk = QHBoxLayout()
        lk.setSpacing(D.px(D.M1))
        self.btn_prev_lk = D.BotonIcono("chevron-left", "Ir a la clave de posición/tamaño anterior")
        self.btn_add_lk = QPushButton("Clave")
        self.btn_add_lk.setIcon(D.icono("diamond-plus"))
        self.btn_add_lk.setToolTip("Fotograma clave de POSICIÓN Y TAMAÑO en el cabezal (la primera activa la "
                                   "animación). Después mueve el cabezal y arrastra o escala la capa en el visor: "
                                   "cada cambio crea la clave de ese momento. Entre claves, movimiento suave.")
        self.btn_del_lk = QPushButton("Quitar")
        self.btn_del_lk.setIcon(D.icono("diamond-minus"))
        self.btn_del_lk.setToolTip("Quita la clave de posición/tamaño que está justo en el cabezal")
        self.btn_next_lk = D.BotonIcono("chevron-right", "Ir a la clave de posición/tamaño siguiente")
        self.btn_clear_lk = QPushButton("Quitar animación")
        self.btn_clear_lk.setToolTip("Se queda quieto con la posición y el tamaño del cabezal")
        for b in (self.btn_prev_lk, self.btn_add_lk, self.btn_del_lk, self.btn_next_lk):
            lk.addWidget(b)
        self.btn_prev_lk.clicked.connect(lambda: self._jump_lk(-1))
        self.btn_next_lk.clicked.connect(lambda: self._jump_lk(1))
        self.btn_add_lk.clicked.connect(lambda: self._clip() and self.ctrl.animate_layout(self._clip().id, self._now()))
        self.btn_del_lk.clicked.connect(
            lambda: self._clip() and self.ctrl.remove_layout_key(self._clip().id, self._now()))
        self.btn_clear_lk.clicked.connect(
            lambda: self._clip() and self.ctrl.clear_layout_animation(self._clip().id, self._now()))
        self.curve_lk = self._curve_combo("layout")
        self.lk_label = QLabel()
        self.lk_label.setObjectName("dim")
        fl.addRow(D.TituloSeccion("Posición y tamaño animados"))
        fl.addRow(lk)
        fl.addRow(self.lk_label, self.btn_clear_lk)
        fl.addRow(_fila("Curva", self.curve_lk))
        self.track_box = self._build_track_box("clip")      # 🎯 Seguimiento (en la pestaña Video)

        # --- Efectos (edits): destello, fundidos y temblor ---
        self.effects_box = QGroupBox("Efectos")
        ef = QFormLayout(self.effects_box)
        self.fx_spins: dict[str, D.ValorDeslizable] = {}
        self._fx_filas: dict[str, QWidget] = {}
        for key, label in (("flash", "Destello"), ("fade_in", "Fundido de entrada"),
                           ("fade_out", "Fundido de salida"), ("shake", "Temblor"),
                           ("lines", "Destello de líneas"), ("focus_in", "Entrar enfocando")):
            spin = _vd(0.0, {"lines": 0.5, "focus_in": 1.5}.get(key, 5.0), 0.05, 2, "s")   # (cortos por naturaleza)
            spin.setSpecialValueText("—")
            spin.setToolTip(f"{label}: cuántos segundos dura (— = sin él)")
            spin.valueChanged.connect(lambda v, k=key: self._on_fx(k, v))
            self.fx_spins[key] = spin
            self._fx_filas[key] = _fila(label, spin)
            ef.addRow(self._fx_filas[key])
        set_help(self.effects_box, "efectos")

        note_box = QGroupBox("Nota / instrucción")
        nlay = QVBoxLayout(note_box)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Nota o instrucción para este clip…")
        self.note.setFixedHeight(80)
        save_note = QPushButton("Guardar nota")
        save_note.clicked.connect(self._on_note)
        nlay.addWidget(self.note)
        nlay.addWidget(save_note, alignment=Qt.AlignRight)

        self._g_info, self._g_props, self._g_note = info, props, note_box
        set_help(info, "clip")
        self.speed_box.setTitle("")
        self.speed_box.setFlat(True)
        from .transform_box import TransformBox
        self.transform_box = TransformBox(self)       # ⤧ Tamaño, posición, rotación, voltear y relleno, a la mano
        from ..core.curves import BLEND_MODES
        self.blend_box = QGroupBox("Opacidad y modo de fusión")
        bf = QFormLayout(self.blend_box)
        self.opacity = _vd(0, 100, 1, 0, "%", entero=True)
        self.opacity.setToolTip("Cuánto se ve el clip (0 % = transparente)")
        self.opacity.valueChanged.connect(self._on_opacity)
        bf.addRow(_fila("Opacidad", self.opacity))
        self.blend_combo = QComboBox()
        for key, name, _f, _q in BLEND_MODES:
            self.blend_combo.addItem(name, key)
        self.blend_combo.currentIndexChanged.connect(self._on_blend)
        bf.addRow(_fila("Fusión", self.blend_combo, "Cómo se mezcla con lo de debajo"))
        self.op_kf_info = _dim()
        self.op_kf_info.setWordWrap(True)
        bf.addRow(self.op_kf_info)
        set_help(self.blend_box, "fusion")
        set_help(self.frame_box, "encuadre")
        # ✂ Recorte (como el «Recorte» de DaVinci): lo mismo que «Recortar» en el visor, con números
        self.crop_box = QGroupBox()                  # (un grupo, como las demás secciones: misma sangría)
        cf = QFormLayout(self.crop_box)
        self.crop_spins: dict = {}
        for k, nombre in (("l", "Izquierda"), ("r", "Derecha"), ("t", "Arriba"), ("b", "Abajo")):
            sp = _vd(0.0, 98.0, 1.0, 1, "%")
            sp.setToolTip(f"Cuánto se recorta por {nombre.lower()} (también con «Recortar» en el visor)")
            sp.valueChanged.connect(lambda v, kk=k: self._on_crop(kk, v))
            self.crop_spins[k] = sp
            cf.addRow(_fila(nombre, sp))
        # 🌗 Suavizar bordes (22/11, la «Softness» de Resolve): el borde de lo que se ve se desvanece a transparente
        tip_sv = ("El borde de la imagen (o lo recortado) se desvanece a transparente en vez de un corte seco; también "
                  "sin recorte.\n0 = corte seco · al activarlo, un 5 % del lado corto.\nCon bordes suaves el "
                  "contorno de color no se pinta (vuelve al quitarlo) y la sombra sigue la forma desvanecida.")
        self.suave_on = QCheckBox("")
        self.suave_on.setToolTip(tip_sv)
        self.suave_on.toggled.connect(self._on_suave_on)
        self.suave_val = _vd(0.0, 50.0, 0.5, 1, "%")
        self.suave_val.setToolTip(tip_sv)
        self.suave_val.valueChanged.connect(self._on_suave)
        fila_sv = QWidget()
        hl_sv = QHBoxLayout(fila_sv)
        hl_sv.setContentsMargins(0, 0, 0, 0)
        hl_sv.addWidget(self.suave_on)
        hl_sv.addWidget(self.suave_val, 1)
        cf.addRow(_fila("Suavizar bordes", fila_sv, tip_sv))
        return w

    def _on_suave_on(self, on: bool):
        if self._loading:
            return
        from ..core import decor
        v = (self.suave_val.value() or decor.SUAVIZAR_DEFECTO * 100) if on else 0.0
        self._loading = True
        self.suave_val.setValue(v)
        self._loading = False
        self._on_suave(v)

    def _on_suave(self, v: float):
        """🌗 fx["suavizar"] (fracción del lado corto) en los clips de imagen/video elegidos. Arrastrar = un paso."""
        if self._loading or not self._ids:
            return
        p = self.ctrl.project
        ids = []
        for cid in self._ids:
            c = p.clips.get(cid)
            m = p.media_of(c) if c is not None else None
            if c is not None and c.text is None and m is not None and m.kind in ("video", "image"):
                ids.append(cid)
        for cid in ids:
            c = p.clips[cid]
            fx = dict(c.fx or {})
            if v > 0:
                fx["suavizar"] = round(float(v) / 100, 4)
            else:
                fx.pop("suavizar", None)
            self.ctrl.set_clip_props([cid], "🌗 Suavizar bordes", fx=fx or None)
        if self.suave_on.isChecked() != (v > 0):
            self._loading = True
            self.suave_on.setChecked(v > 0)
            self._loading = False

    def _build_color_tab(self) -> QWidget:
        """Pestaña «Color» (como la página Color de Resolve, en sencillo). Se ve igual en el visor y al exportar."""
        from ..core import color as C
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        self.color_box = QGroupBox("Corrección de color")
        form = QFormLayout(self.color_box)
        from .color_wheels import wheel_box
        wbox, self.color_wheels = wheel_box(self.color_box)      # 🎨 Lift / Gamma / Gain, como en Resolve
        for k_, wh in self.color_wheels.items():
            wh.changed.connect(lambda v, kk=k_: self._on_color_wheel(kk, v))
        form.addRow(wbox)
        form.addRow(D.TituloSeccion("Ajustes"))
        self.color_sliders: dict[str, D.ValorDeslizable] = {}
        for k in C.KEYS:
            lo, hi = C.RANGES.get(k, (-1.0, 1.0))
            # (el valor, en centésimas como antes —40 = +0,40—; se ve con dos decimales)
            sl = _vd(int(lo * 100), int(hi * 100), 2, 2, "", entero=True, factor=100, signo=True)
            sl.valueChanged.connect(lambda v, kk=k: self._on_color_slider(kk, v))
            nombre, _p, resto = C.LABELS[k].partition(" (")
            sl.setToolTip(f"{nombre}{(': ' + resto.rstrip(')')) if resto else ''} (0 = sin cambio; arrastra el "
                          "número o escríbelo)")
            self.color_sliders[k] = sl
            form.addRow(_fila(nombre, sl))
        form.addRow(D.TituloSeccion("LUT"))
        lr = QHBoxLayout()
        self.btn_lut = QPushButton("Cargar LUT (.cube)…")
        self.btn_lut.setToolTip("Un «look» de color en formato .cube (los de Resolve, Premiere, cámaras…)")
        self.btn_lut.clicked.connect(self._choose_lut)
        self.lut_name = D.EtiquetaElidida("sin LUT")     # (una línea: si no cabe, «…» y entero en su tooltip)
        D.poner_letra(self.lut_name, D.LETRA_P, D.GRIS_TITULO)
        self.btn_lut_off = D.BotonIcono("x", "Quitar el LUT")
        self.btn_lut_off.clicked.connect(lambda: self._set_color_field(lut=None))
        lr = D.fila_fija(lr)                         # (el nombre del LUT y su ✕; el botón, en su propia fila)
        lr.addWidget(self.lut_name, 1)
        lr.addWidget(self.btn_lut_off)
        form.addRow(self.btn_lut)
        form.addRow(lr)
        self.lut_mix = _vd(0, 100, 1, 0, "%", entero=True)
        self.lut_mix.setToolTip("Cuánto se nota el LUT (100 % = entero)")
        self.lut_mix.valueChanged.connect(lambda v: self._loading or self._set_color_field(lut_mix=v / 100))
        form.addRow(_fila("Intensidad", self.lut_mix))
        br = QHBoxLayout()
        self.btn_auto_color = QPushButton("Color automático")
        self.btn_auto_color.setIcon(D.icono("wand-sparkles"))
        self.btn_auto_color.setToolTip("Corrige exposición, contraste y balance de blancos mirando el fotograma "
                                       "del cabezal (suave: nunca exagera).")
        self.btn_auto_color.clicked.connect(lambda: self._ids and self.ctrl.auto_color(self._ids, self.engine.time))
        b_reset = QPushButton("Restablecer")
        b_reset.setIcon(D.icono("rotate-ccw"))
        b_reset.setToolTip("Quita toda la corrección de color del clip (Ctrl+Z lo deshace)")
        b_reset.clicked.connect(lambda: self._ids and self.ctrl.set_color(self._ids, None, "Quitar color"))
        br.addWidget(self.btn_auto_color)
        br.addWidget(b_reset)
        form.addRow(br)
        self.color_bypass = QCheckBox("Ver sin corrección")
        self.color_bypass.setToolTip("Comparar antes / después: el visor enseña el clip sin la corrección de color")
        self.color_bypass.toggled.connect(self._on_color_bypass)
        form.addRow(self.color_bypass)
        self.color_box.setToolTip("Para repetir el color en otros clips: Ctrl+C en este y Alt+V en los otros → "
                                  "«Color».")
        set_help(self.color_box, "color")
        lay.addWidget(self.color_box)
        lay.addStretch()
        return w

    def _on_opacity(self, v: int):
        if self._loading or not self._ids:
            return
        self.ctrl.set_curve(self._ids[0], "op", level=v / 100, text="Opacidad")

    def _on_blend(self, _i: int):
        if self._loading or not self._ids:
            return
        self.ctrl.set_clip_props(self._ids, "Modo de fusión", blend=self.blend_combo.currentData())

    def _refresh_blend(self, c, visual: bool, editable: bool):
        self.blend_box.setVisible(visual)
        if not visual:
            return
        self.blend_box.setEnabled(editable)
        self.opacity.setValue(int(round(c.opacity * 100)))
        i = self.blend_combo.findData(c.blend or "normal")
        self.blend_combo.setCurrentIndex(max(0, i))
        self.op_kf_info.setText(f"〰 Curva de opacidad con {len(c.op_kf)} puntos (edítala con «〰 Curvas» en la "
                                "línea de tiempo)." if c.op_kf else "Para que cambie con el tiempo: «〰 Curvas» en la "
                                                                   "línea de tiempo.")

    def _color_now(self) -> dict:
        c = self._clip()
        return dict((c.color if c else None) or {})

    def _on_color_slider(self, key: str, v: int):
        if self._loading or not self._ids:
            return
        col = self._color_now()
        col[key] = round(v / 100, 3)
        from ..core import color as C
        self.ctrl.set_color(self._ids, col, "Color: " + C.LABELS[key].split(" (")[0].lower())

    def _on_color_wheel(self, key: str, v: list):
        if self._loading or not self._ids:
            return
        from ..core import color as C
        col = self._color_now()
        if max(abs(float(x)) for x in v) < 1e-4:
            col.pop(key, None)
        else:
            col[key] = [round(float(x), 3) for x in v]
        self.ctrl.set_color(self._ids, col, "Color: rueda de " + C.WHEEL_LABELS[key].lower())

    def _set_color_field(self, **kv):
        if not self._ids:
            return
        col = self._color_now()
        for k, v in kv.items():
            if v is None:
                col.pop(k, None)
            else:
                col[k] = v
        self.ctrl.set_color(self._ids, col, "LUT" if "lut" in kv else "Intensidad del LUT")

    def _choose_lut(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ..core import color as C
        path, _ = QFileDialog.getOpenFileName(self, "Elegir un LUT", "", "LUT de color (*.cube)")
        if not path:
            return
        try:
            C.read_cube(path)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "LUT", f"No se pudo leer ese LUT: {ex}")
            return
        col = self._color_now()
        col["lut"] = path
        col.setdefault("lut_mix", 1.0)
        self.ctrl.set_color(self._ids, col, "LUT")

    def _on_color_bypass(self, on: bool):
        self.engine.color_bypass = on
        self.engine.refresh_sources()

    def _refresh_color(self, c, visual: bool, editable: bool):
        from ..core import color as C
        if not visual:
            return
        self.color_box.setEnabled(editable)
        col = c.color or {}
        for k, sl in self.color_sliders.items():
            v = int(round(float(col.get(k, 0) or 0) * 100))
            sl.setValue(v)
        for k, wh in self.color_wheels.items():
            wh.set_values(*C.wheel(col, k))
        lut = col.get("lut")
        self.lut_name.setText(os.path.basename(lut) if lut else "sin LUT")
        self.lut_name.poner_tooltip_extra(lut or "")
        self.btn_lut_off.setEnabled(bool(lut))
        self.lut_mix.setEnabled(bool(lut))
        self.lut_mix.setValue(int(round(float(col.get("lut_mix", 1.0)) * 100)))

    def _build_audio_tab(self):
        w = QWidget()
        top = QFormLayout(w)
        top.setContentsMargins(0, 0, 0, 0)
        top.addRow(_fila("Volumen", self.volume))
        self.pan = _vd(-100, 100, 1, 0, "", entero=True,
                       formato=lambda v: "C" if v == 0 else (f"I{-v}" if v < 0 else f"D{v}"))
        self.pan.setToolTip("Balance: izquierda (−) ← → derecha (+); 0 = centro")
        self.pan.valueChanged.connect(self._on_pan)
        top.addRow(_fila("Balance", self.pan))

        set_help(w, "audio_clip")
        box = QGroupBox("Ecualizador")
        set_help(box, "ecualizador")
        bl = QVBoxLayout(box)
        hdr = QHBoxLayout()
        self.eq_on = QCheckBox("Activado")
        self.eq_on.toggled.connect(self._on_eq_on)
        self.eq_preset = QComboBox()
        self.eq_preset.activated.connect(self._on_eq_preset)
        self._fill_presets()
        hdr.addWidget(self.eq_on)
        hdr.addStretch()
        hdr.addWidget(self.eq_preset)
        bl.addLayout(hdr)
        self.eq_graph = EqGraph()
        self.eq_graph.band_changed.connect(self._on_band)
        bl.addWidget(self.eq_graph)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        grid.setProperty("responsive_columnas", 1)   # (estrecho: las bandas en bloques, B1 B2 B3 | B4…; ↔ responsive)
        self.band_rows = []
        for i in range(E.N_BANDS):
            on = QPushButton(f"B {i + 1}")
            on.setCheckable(True)
            on.setToolTip("Activar / desactivar esta banda")
            on.setStyleSheet("QPushButton { padding: 3px 0; border-radius: 9px; color: #7d8590; }"
                             "QPushButton:checked { color: #ff5a5f; background: #2b2d33; border-color: #5a3036; }")
            typ = QComboBox()
            typ.setToolTip("Tipo de filtro")
            for key in E.TYPES:
                typ.addItem(E.TYPE_SHORT[key], key)
                typ.setItemData(typ.count() - 1, E.TYPES[key], Qt.ToolTipRole)
            freq = QSpinBox()
            freq.setRange(20, 20000)
            freq.setKeyboardTracking(False)
            freq.setButtonSymbols(QSpinBox.NoButtons)
            freq.setToolTip("Frecuencia (Hz)")
            gain = QDoubleSpinBox()
            gain.setRange(-24, 24)
            gain.setSingleStep(0.5)
            gain.setDecimals(1)
            gain.setKeyboardTracking(False)
            gain.setButtonSymbols(QDoubleSpinBox.NoButtons)
            gain.setToolTip("Ganancia (dB)")
            q = QDoubleSpinBox()
            q.setRange(0.1, 10)
            q.setSingleStep(0.1)
            q.setDecimals(1)
            q.setKeyboardTracking(False)
            q.setButtonSymbols(QDoubleSpinBox.NoButtons)
            q.setToolTip("Ancho (Q): más alto = más estrecho")
            for row, wid in enumerate((on, typ, freq, gain, q)):
                wid.setMinimumWidth(44)
                wid.setMaximumWidth(64)
                grid.addWidget(wid, row, i)
            on.toggled.connect(lambda _v, k=i: self._on_band_row(k))
            typ.currentIndexChanged.connect(lambda _v, k=i: self._on_band_row(k))
            for spin in (freq, gain, q):
                spin.valueChanged.connect(lambda _v, k=i: self._on_band_row(k))
            self.band_rows.append((on, typ, freq, gain, q))
        for row, unit in ((2, "Hz"), (3, "dB"), (4, "Q")):
            lbl = QLabel(unit)
            lbl.setObjectName("dim")
            grid.addWidget(lbl, row, E.N_BANDS)
        bl.addLayout(grid)
        brow = QHBoxLayout()
        self.btn_monitor = QPushButton("Escuchar con EQ")
        self.btn_monitor.setIcon(D.icono("headphones"))
        self.btn_monitor.setCheckable(True)
        self.btn_monitor.setToolTip("Repite en bucle unos segundos del cabezal con el ecualizador y se "
                                    "actualiza al momento cuando cambias algo.")
        self.btn_monitor.clicked.connect(lambda: self.monitor and self.monitor.toggle())
        self.btn_eq_all = QPushButton("Aplicar a todo este archivo")
        self.btn_eq_all.setToolTip("Copia este ecualizador y balance a todos los clips del mismo archivo "
                                   "(p. ej. la narración, que queda dividida tras quitar silencios).")
        self.btn_eq_all.clicked.connect(self._eq_to_all)
        reset = QPushButton("Reiniciar")
        reset.clicked.connect(lambda: self._set_eq({"on": True, "bands": E.default_bands()}, "Reiniciar ecualizador"))
        brow.addWidget(self.btn_monitor)
        brow.addWidget(self.btn_eq_all)
        brow.addWidget(reset)
        bl.addLayout(brow)
        self.monitor_status = _dim()
        bl.addWidget(self.monitor_status)
        box.setTitle("")
        box.setFlat(True)
        self._g_volumen, self._g_eq = w, box

    def _colocar_velocidad(self, con_sonido: bool):
        """🐢 Con sonido: debajo del ecualizador (pestaña Audio); sin sonido: en Video, tras Composición."""
        destino = self._audio_lay if con_sonido else self._tl_clip
        if getattr(self, "_vel_en", None) is destino:
            return
        if getattr(self, "_vel_en", None) is not None:
            self._vel_en.removeWidget(self.speed_sec)
        tras = self.secciones["ecualizador"] if con_sonido else self.secciones["composicion"]
        destino.insertWidget(destino.indexOf(tras) + 1, self.speed_sec)
        self._vel_en = destino

    def set_monitor(self, monitor):
        self.monitor = monitor
        monitor.state_changed.connect(self.btn_monitor.setChecked)
        monitor.status.connect(self.monitor_status.setText)

    def _eq_of(self, c) -> dict:
        return E.normalize(c.eq)

    def _set_eq(self, eq: dict, text: str = "Ecualizador"):
        c = self._aclip()
        if c is not None and not self._loading:
            self.ctrl.set_clip_audio([c.id], text, eq=eq)

    def _on_band(self, i: int, band: dict):
        c = self._aclip()
        if c is None:
            return
        eq = self._eq_of(c)
        bands = [dict(b) for b in eq["bands"]]
        bands[i] = band
        self._set_eq({"on": True, "bands": bands})

    def _on_band_row(self, i: int):
        if self._loading:
            return
        c = self._aclip()
        if c is None:
            return
        on, typ, freq, gain, q = self.band_rows[i]
        self._on_band(i, {"on": on.isChecked(), "type": typ.currentData(), "f": float(freq.value()),
                          "g": float(gain.value()), "q": float(q.value())})

    def _on_eq_on(self, on: bool):
        c = self._aclip()
        if c is not None and not self._loading:
            self._set_eq(dict(self._eq_of(c), on=on), "Activar ecualizador" if on else "Desactivar ecualizador")

    def _user_presets(self) -> dict:
        try:
            return json.loads(QSettings("EditorIA", "EditorIA").value("eq/presets", "{}") or "{}")
        except (TypeError, ValueError):
            return {}

    def _fill_presets(self):
        self.eq_preset.clear()
        self.eq_preset.addItem("Presets…")
        for name in E.PRESETS:
            self.eq_preset.addItem(name, ("app", name))
        user = self._user_presets()
        if user:
            self.eq_preset.insertSeparator(self.eq_preset.count())
            for name in user:
                self.eq_preset.addItem(f"★ {name}", ("user", name))
        self.eq_preset.insertSeparator(self.eq_preset.count())
        self.eq_preset.addItem("💾 Guardar como preset…", ("save", ""))
        if user:
            self.eq_preset.addItem("🗑 Borrar un preset mío…", ("delete", ""))

    def _on_eq_preset(self, idx: int):
        data = self.eq_preset.itemData(idx)
        self.eq_preset.setCurrentIndex(0)
        if not data:
            return
        kind, name = data
        c = self._aclip()
        if kind == "app":
            self._set_eq({"on": True, "bands": [dict(b) for b in E.PRESETS[name]]}, f"Ecualizador: {name}")
        elif kind == "user":
            bands = self._user_presets().get(name)
            if bands:
                self._set_eq(E.normalize({"on": True, "bands": bands}), f"Ecualizador: {name}")
        elif kind == "save" and c is not None:
            name, ok = QInputDialog.getText(self, "Guardar preset", "Nombre del preset (p. ej. «Mi voz 2»):")
            if ok and name.strip():
                user = self._user_presets()
                user[name.strip()] = self._eq_of(c)["bands"]
                QSettings("EditorIA", "EditorIA").setValue("eq/presets", json.dumps(user, ensure_ascii=False))
                self._fill_presets()
                self.ctrl.message.emit(f"Preset «{name.strip()}» guardado: lo tendrás en todos tus proyectos.")
        elif kind == "delete":
            user = self._user_presets()
            name, ok = QInputDialog.getItem(self, "Borrar preset", "¿Cuál?", list(user), 0, False)
            if ok and name in user:
                del user[name]
                QSettings("EditorIA", "EditorIA").setValue("eq/presets", json.dumps(user, ensure_ascii=False))
                self._fill_presets()

    def _on_pan(self, v: int):
        c = self._aclip()
        if c is not None and not self._loading:
            self.ctrl.set_clip_audio([c.id], "Balance", pan=v / 100)

    def _eq_to_all(self):
        c = self._aclip()
        if c is None:
            return
        ids = [o.id for o in self.ctrl.project.clips.values()
               if o.media_id == c.media_id and not o.locked and not self.ctrl.project.track(o.track_id).locked]
        self.ctrl.set_clip_audio(ids, "Ecualizador en todo el archivo", eq=c.eq, pan=c.pan)
        self.ctrl.message.emit(f"Ecualizador copiado a {len(ids)} clips del mismo archivo.")

    def _refresh_audio_tab(self, c, m):
        eq = self._eq_of(c)
        self.eq_on.setChecked(bool(c.eq and c.eq.get("on", True)))
        self.eq_graph.set_eq(eq)
        for (on, typ, freq, gain, q), b in zip(self.band_rows, eq["bands"]):
            on.setChecked(bool(b.get("on")))
            typ.setCurrentIndex(max(0, typ.findData(b["type"])))
            freq.setValue(int(round(b["f"])))
            gain.setValue(float(b.get("g", 0.0)))
            gain.setVisible(b["type"] not in ("hp", "lp"))
            q.setValue(float(b.get("q", 0.7)))
            q.setVisible(b["type"] == "bell")
            for wid in (typ, freq, gain, q):
                wid.setEnabled(bool(b.get("on")))
        self.pan.setValue(int(round(c.pan * 100)))
        n_same = sum(1 for o in self.ctrl.project.clips.values() if o.media_id == c.media_id)
        self.btn_eq_all.setVisible(n_same > 1)
        self.btn_eq_all.setText(f"Aplicar a los {n_same} clips de este archivo")
        if self._spectrum_key != (c.id, round(self._now(), 1)) and self.eq_graph.isVisible():
            self._spectrum_timer.start()

    def _pestanas_que_caben(self):
        """Las 7 pestañas en una fila: si no caben con su nombre, «Proyecto» (la última) se queda en su icono, con el
        nombre en el tooltip (nada cortado ni una fila de más)."""
        from . import diseno as D
        bots = getattr(self, "botones_pestana", [])
        if not bots:
            return
        b = bots[-1]
        if not hasattr(b, "_nombre"):
            b._nombre = b.text()
            b._tip = b.toolTip()
        lay = self.fila_pestanas.layout()
        visibles = [x for x in bots if not x.isHidden()]
        fm = b.fontMetrics()
        lleno = sum(fm.horizontalAdvance(x._nombre if x is b else x.text()) + 12 for x in visibles) + \
            lay.spacing() * max(0, len(visibles) - 1)
        icono_solo = lleno > self.fila_pestanas.width()
        if icono_solo and b.text():
            b.setText("")
            b.setIcon(D.icono("settings-2"))
            b.setToolTip(f"{b._nombre}: {b._tip}")
        elif not icono_solo and not b.text():
            b.setText(b._nombre)
            from PySide6.QtGui import QIcon
            b.setIcon(QIcon())
            b.setToolTip(b._tip)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "fila_pestanas", None) and ev.type() == QEvent.Resize:
            self._pestanas_que_caben()
            return False
        if obj is self.eq_graph and ev.type() == QEvent.Show and self._clip() is not None:
            self._spectrum_key = None                  # se acaba de mostrar: el espectro se calcula ahora
            self._spectrum_timer.start()
        return super().eventFilter(obj, ev)

    def _update_spectrum(self):
        """Espectro del ecualizador: solo si la gráfica se ve, y el ffmpeg corre en segundo plano (no congela)."""
        if not self.eq_graph.isVisible():
            return
        c = self._aclip()
        m = self.ctrl.project.media_of(c) if c else None
        if c is None or m is None or (self.engine is not None and self.engine.playing):
            return
        self._spectrum_key = (c.id, round(self._now(), 1))
        src = self.ctrl.clip_source_time(c.id, self._now())
        self._spectrum_token = getattr(self, "_spectrum_token", 0) + 1
        tok = self._spectrum_token
        from .jobs import BackgroundJob
        path = m.path
        job = BackgroundJob(lambda _p, _c: _muestras_espectro(path, src), self)

        def llego(samples, tok=tok):
            if tok == self._spectrum_token and self.eq_graph.isVisible():   # solo el último pedido
                self.eq_graph.set_spectrum(samples, 16000)
        job.done.connect(llego)
        self._spectrum_job = job                       # (se guarda para que no la recoja el recolector)
        job.start()

    TEXT_POSITIONS = [("Arriba", 0.5, 0.12), ("Centro", 0.5, 0.5), ("Abajo", 0.5, 0.85),
                      ("Arriba izquierda", 0.25, 0.08), ("Arriba derecha", 0.75, 0.08),
                      ("Abajo izquierda", 0.25, 0.9), ("Abajo derecha", 0.75, 0.9)]

    def _build_text_page(self) -> QWidget:
        """Texto en pantalla, como el «Texto» de Resolve: Texto · Trazo · Sombra · Fondo. Cada opción con ↺
        (valor de fábrica). Lo que cambias se recuerda como «mi estilo» para los textos nuevos."""
        from PySide6.QtGui import QColor, QFont, QFontDatabase
        from PySide6.QtWidgets import QColorDialog, QFontComboBox, QGroupBox, QToolButton
        from ..core.title_render import FACTORY
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        w = QWidget()                               # (sin desplazamiento propio: se desplaza todo el panel)
        ol.addWidget(w)
        lay = QVBoxLayout(w)
        set_help(w, "texto_pantalla")
        title = QLabel("Texto en pantalla")
        title.setObjectName("title")
        self.text_origin = QLabel()
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(70)
        self.text_edit.setPlaceholderText("Escribe el texto (Enter = nueva línea)")
        self._txt_timer = QTimer(self)
        self._txt_timer.setSingleShot(True)
        self._txt_timer.setInterval(350)
        self._txt_timer.timeout.connect(lambda: self._set_text(content=self.text_edit.toPlainText()))
        self.text_edit.textChanged.connect(lambda: None if self._loading else self._txt_timer.start())
        lay.addWidget(title)
        lay.addWidget(self.text_origin)
        lay.addWidget(self.text_edit)
        from .spellcheck import attach as _spell
        self._spell_w = _spell(self.text_edit)          # ✍ ortografía (español de México / inglés / mixto)
        lay.addWidget(self._spell_w)
        self.tw: dict = {}            # clave → (widget, cómo poner su valor)

        def reset_btn(keys):
            b = QToolButton()                       # (↺ con su icono monocromo; plano, como los de las secciones)
            b.setIcon(D.icono("rotate-ccw"))
            b.setToolTip("Volver al valor de fábrica")
            b.setAccessibleName("Volver al valor de fábrica")
            b.setAutoRaise(True)
            b.clicked.connect(lambda: self._set_text(**{k: FACTORY[k] for k in keys}))
            return b

        def row(form, label, widget, keys, extra=None):
            """(diseño nuevo: la etiqueta gris en su columna, el control y su ↺ al lado, que nunca baja de fila)"""
            h = D.fila_fija(QHBoxLayout())
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(D.px(D.M1))
            h.addWidget(widget, 1)
            if extra is not None:
                h.addWidget(extra)
            h.addWidget(reset_btn(keys))
            holder = QWidget()
            holder.setLayout(h)
            form.addRow(D.FilaInspector(label, holder))

        def spin(key, lo, hi, step, suffix="", dec=1, scale=1.0, deslizador=True):
            sp = D.ValorDeslizable(lo, hi, step, dec, suffix.strip(), deslizador=deslizador)
            sp.valueChanged.connect(lambda v, k=key: self._set_text(**{k: round(v / scale, 4)}))
            self.tw[key] = (sp, lambda v, sp=sp: sp.setValue(float(v) * scale))
            return sp

        def color_btn(key):
            b = QPushButton()
            b.setFixedSize(46, 22)

            def pick():
                cur = QColor(str(self._cur_text().get(key, FACTORY[key])))
                from .common import pick_color
                c = pick_color(cur, self, "Color")
                if c.isValid():
                    self._set_text(**{key: c.name().upper()})
            b.clicked.connect(pick)
            self.tw[key] = (b, lambda v, b=b: b.setStyleSheet(f"background:{v}; border:1px solid #666;"))
            return b

        def check(key, text):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda v, k=key: self._set_text(**{k: bool(v)}))
            self.tw[key] = (cb, lambda v, cb=cb: cb.setChecked(bool(v)))
            return cb

        # --- Texto
        g = QGroupBox("Texto")
        f = QFormLayout(g)
        self.text_font = QFontComboBox()
        self.text_font.currentFontChanged.connect(lambda fo: self._set_text(font=fo.family(), font_style=""))
        self.tw["font"] = (self.text_font, lambda v: self.text_font.setCurrentFont(QFont(str(v))))
        row(f, "Fuente", self.text_font, ["font", "font_style"])
        self.text_ftype = QComboBox()
        self.text_ftype.activated.connect(lambda _i: self._set_text(font_style=self.text_ftype.currentData() or ""))

        def set_ftype(v):
            fam = str(self._cur_text().get("font", FACTORY["font"]))
            self.text_ftype.clear()
            self.text_ftype.addItem("Normal (según Negrita/Cursiva)", "")
            for st in QFontDatabase.styles(fam):
                self.text_ftype.addItem(st, st)
            self.text_ftype.setCurrentIndex(max(0, self.text_ftype.findData(v or "")))
        self.tw["font_style"] = (self.text_ftype, set_ftype)
        row(f, "Tipo", self.text_ftype, ["font_style"])
        row(f, "Color", color_btn("color"), ["color"])
        self.text_size = spin("size", 1.0, 40.0, 0.5, " %")      # (la explicación, en la ayuda: cabe estrecho)
        self.text_size.setToolTip("Tamaño de la letra, en % del alto del video.")
        row(f, "Tamaño", self.text_size, ["size"])
        row(f, "Interletrado", spin("tracking", -20, 100, 1, " %", 0), ["tracking"])
        row(f, "Interlineado", spin("line_spacing", -50, 200, 5, " %", 0), ["line_spacing"])
        sty = QHBoxLayout()
        for key, txt, tip in (("bold", "B", "Negrita"), ("italic", "I", "Cursiva"), ("underline", "U", "Subrayado"),
                              ("strike", "S", "Tachado")):
            tb = QToolButton()
            tb.setText(txt)
            tb.setToolTip(tip)
            tb.setCheckable(True)
            fo = tb.font()
            fo.setBold(key == "bold")
            fo.setItalic(key == "italic")
            fo.setUnderline(key == "underline")
            fo.setStrikeOut(key == "strike")
            tb.setFont(fo)
            tb.toggled.connect(lambda v, k=key: self._set_text(**{k: bool(v)}))
            self.tw[key] = (tb, lambda v, tb=tb: tb.setChecked(bool(v)))
            sty.addWidget(tb)
        sty.addStretch(1)
        hs = QWidget()
        hs.setLayout(sty)
        row(f, "Estilo", hs, ["bold", "italic", "underline", "strike"])
        self.text_case = QComboBox()
        for label, key in (("Mayús. y minús. combinadas", "normal"), ("TODO MAYÚSCULAS", "upper"),
                           ("todo minúsculas", "lower"), ("Cada Palabra En Mayúscula", "title")):
            self.text_case.addItem(label, key)
        self.text_case.activated.connect(lambda _i: self._set_text(case=self.text_case.currentData()))
        self.tw["case"] = (self.text_case, lambda v: self.text_case.setCurrentIndex(
            max(0, self.text_case.findData(v))))
        row(f, "Mayús./Minús.", self.text_case, ["case"])
        al = QHBoxLayout()
        self._align_btns = {}
        for key, ic, txt in (("left", "align-left", "Izquierda"), ("center", "align-center", "Centro"),
                             ("right", "align-right", "Derecha")):
            tb = QToolButton()
            tb.setIcon(D.icono(ic))
            tb.setToolTip(txt)
            tb.setAccessibleName(txt)
            tb.setCheckable(True)
            tb.clicked.connect(lambda _=False, k=key: self._set_text(align=k))
            self._align_btns[key] = tb
            al.addWidget(tb)
        al.addStretch(1)
        ha = QWidget()
        ha.setLayout(al)
        self.tw["align"] = (ha, lambda v: [b.setChecked(k == v) for k, b in self._align_btns.items()])
        row(f, "Justificado", ha, ["align"])
        self._g_txt_fuente = g
        g = QGroupBox("Posición")                    # (en su propia sección, como en DaVinci)
        f = QFormLayout(g)
        self.text_pos = QComboBox()
        self.text_pos.addItem("Personalizada")
        for name, _x, _y in self.TEXT_POSITIONS:
            self.text_pos.addItem(name)
        self.text_pos.currentTextChanged.connect(self._on_text_pos)
        row(f, "Posición", self.text_pos, ["x", "y"])
        self.text_x = D.ValorDeslizable(-100000, 100000, 1, 0, "px", deslizador=False)
        self.text_y = D.ValorDeslizable(-100000, 100000, 1, 0, "px", deslizador=False)
        for sp, key in ((self.text_x, "x"), (self.text_y, "y")):
            sp.valueChanged.connect(lambda v, k=key: self._set_text(**{k: round(v / self._canvas_px(k), 4)}))
        self.text_x.setToolTip("De izquierda a derecha, en píxeles del video (arrastra el número o escríbelo)")
        self.text_y.setToolTip("De arriba abajo, en píxeles del video")
        self.tw["x"] = (self.text_x, lambda v: self.text_x.setValue(float(v) * self._canvas_px("x")))
        self.tw["y"] = (self.text_y, lambda v: self.text_y.setValue(float(v) * self._canvas_px("y")))
        row(f, "X", self.text_x, ["x"])
        row(f, "Y", self.text_y, ["y"])
        self.text_zx = spin("zoom_x", 0.05, 10, 0.05, "", 3)
        self.text_zy = spin("zoom_y", 0.05, 10, 0.05, "", 3)
        self.text_zlink = D.BotonIcono("link", "Zoom igual en X e Y\nClic: por separado", D.ALTO_CONTROL, plano=True)
        self.text_zlink.setCheckable(True)
        self.text_zlink.setChecked(True)
        self.text_zlink.toggled.connect(lambda on: self.text_zlink.poner_icono(
            "link" if on else "unlink", "Zoom igual en X e Y\nClic: por separado" if on else
            "Zoom X e Y por separado\nClic: iguales"))
        self.text_zx.valueChanged.connect(lambda v: self.text_zlink.isChecked() and not self._loading and
                                          self._set_text(zoom_x=round(v, 3), zoom_y=round(v, 3)))
        row(f, "Zoom X", self.text_zx, ["zoom_x", "zoom_y"], self.text_zlink)
        row(f, "Zoom Y", self.text_zy, ["zoom_x", "zoom_y"])
        row(f, "Ángulo de rotación", spin("rotation", -360, 360, 1, "°", 1), ["rotation"])
        self._g_txt_pos = g

        # --- Trazo
        g = QGroupBox("Trazo")
        f = QFormLayout(g)
        row(f, "Color", color_btn("stroke_color"), ["stroke_color"])
        row(f, "Tamaño", spin("stroke_size", 0, 60, 1, " %", 0), ["stroke_size"])
        row(f, "", check("stroke_outside", "Solo afuera"), ["stroke_outside"])
        self._g_txt_trazo = g

        # --- Sombra (se activa con la casilla del título)
        g = QGroupBox("Sombra")
        g.setCheckable(True)
        g.toggled.connect(lambda v: self._set_text(shadow=bool(v)))
        self.tw["shadow"] = (g, lambda v, g=g: g.setChecked(bool(v)))
        f = QFormLayout(g)
        row(f, "Color", color_btn("shadow_color"), ["shadow_color"])
        row(f, "Desplazar X", spin("shadow_x", -100, 100, 1, " %", 0), ["shadow_x"])
        row(f, "Desplazar Y", spin("shadow_y", -100, 100, 1, " %", 0), ["shadow_y"])
        row(f, "Desenfoque", spin("shadow_blur", 0, 100, 1, " %", 0), ["shadow_blur"])
        row(f, "Opacidad", spin("shadow_opacity", 0, 100, 5, " %", 0, 100.0), ["shadow_opacity"])
        self._g_txt_sombra = g

        # --- Fondo
        g = QGroupBox("Fondo")
        g.setCheckable(True)
        g.toggled.connect(lambda v: self._set_text(box=bool(v)))
        self.tw["box"] = (g, lambda v, g=g: g.setChecked(bool(v)))
        f = QFormLayout(g)
        row(f, "Color", color_btn("box_color"), ["box_color"])
        row(f, "Color de contorno", color_btn("box_outline_color"), ["box_outline_color"])
        row(f, "Ancho de contorno", spin("box_outline_width", 0, 40, 1, " %", 0), ["box_outline_width"])
        row(f, "Ancho", spin("box_width", 0, 300, 2, " %", 0), ["box_width"])
        row(f, "Altura", spin("box_height", 0, 300, 2, " %", 0), ["box_height"])
        row(f, "Esquinas", spin("box_radius", 0, 50, 1, " %", 0), ["box_radius"])
        row(f, "Centro X", spin("box_cx", -300, 300, 2, " %", 0), ["box_cx"])
        row(f, "Centro Y", spin("box_cy", -300, 300, 2, " %", 0), ["box_cy"])
        row(f, "Opacidad", spin("box_opacity", 0, 100, 5, " %", 0, 100.0), ["box_opacity"])
        self._g_txt_fondo = g

        # --- Desenfocar lo de debajo (mientras se ve el texto)
        g = QGroupBox("Desenfocar lo de debajo")
        g.setCheckable(True)
        g.setToolTip("Mientras se ve este texto, el video o la imagen de debajo se desenfoca (en el visor y al "
                     "exportar): el texto se lee mejor.")
        g.toggled.connect(lambda v: self._set_text(blur_under=0.5 if v else 0.0))
        f = QFormLayout(g)
        row(f, "Intensidad", spin("blur_under", 0, 100, 5, " %", 0, 100.0), ["blur_under"])
        sp_w, sp_set = self.tw["blur_under"]

        def set_both(v, sp_set=sp_set, g=g):     # la casilla del grupo sigue a la intensidad
            sp_set(v)
            g.blockSignals(True)
            g.setChecked(float(v or 0) > 0)
            g.blockSignals(False)
        self.tw["blur_under"] = (sp_w, set_both)
        self._sp_set_blur = sp_set
        self._g_txt_desenf = g

        # --- 📝 Fondo borroso alrededor (un recuadro que desenfoca lo de debajo; ver core/nota_texto.py)
        from ..core.nota_texto import ZONE_DEFAULTS
        g = QGroupBox("Fondo borroso alrededor")
        g.setCheckable(True)
        g.setToolTip("Un recuadro alrededor del texto que desenfoca el video de debajo (en el visor y al exportar). "
                     "Sigue al texto si lo mueves.")
        g.toggled.connect(lambda v: self._set_text(zone_blur=bool(v)))
        self.tw["zone_blur"] = (g, lambda v, g=g: g.setChecked(bool(v)))
        f = QFormLayout(g)

        def slider(key, hi, tip, especial="", maximo=""):
            s = D.ValorDeslizable(0, hi, 1, 0, "%", entero=True)
            if especial:
                s.setSpecialValueText(especial)
            if maximo:
                s.poner_texto_maximo(maximo)
            s.setToolTip(tip)
            s.valueChanged.connect(lambda x, k=key: self._set_text(**{k: round(x / 100, 2)}))

            def put(v, s=s, k=key):
                v = ZONE_DEFAULTS[k] if v is None else float(v)
                s.blockSignals(True)
                s.setValue(int(round(v * 100)))
                s.blockSignals(False)
            self.tw[key] = (s, put)
            return s
        f.addRow(D.FilaInspector("Tamaño", slider("zone_size", 100, "A la izquierda, ajustado al texto; a la "
                                                  "derecha crece hasta cubrir toda la pantalla.", "Ajustado",
                                                  "Toda la pantalla")))
        f.addRow(D.FilaInspector("Fuerza", slider("zone_strength", 100, "Cuánto se desenfoca lo de debajo.")))
        f.addRow(D.FilaInspector("Oscurecer", slider("zone_dark", 90, "Oscurece un poco lo desenfocado.")))
        self._g_txt_borroso = g

        # --- Memoria
        self.text_remember = QCheckBox("Recordar mis valores para los textos nuevos")
        self.text_remember.setToolTip("Lo que cambies (fuente, color, sombra, fondo…) se usa al crear textos nuevos.")
        self.text_remember.setChecked(str(QSettings("EditorIA", "EditorIA").value("texto/recordar", "true")).lower()
                                      == "true")
        self.text_remember.toggled.connect(lambda v: QSettings("EditorIA", "EditorIA").setValue(
            "texto/recordar", "true" if v else "false"))
        self._g_txt_plantilla = QWidget()
        _pl = QVBoxLayout(self._g_txt_plantilla)
        _pl.setContentsMargins(0, 0, 0, 0)
        _pl.addWidget(self.text_remember)
        rr = QHBoxLayout()
        b_mine = QPushButton("Aplicar mi estilo")
        b_mine.setIcon(D.icono("palette"))
        b_mine.setToolTip("Pone en este texto tus valores recordados.")
        b_mine.clicked.connect(self._apply_my_text_style)
        b_fac = QPushButton("Todo de fábrica")
        b_fac.setIcon(D.icono("rotate-ccw"))
        b_fac.setToolTip("Todos los valores de fábrica en este texto (lo escrito se queda)")
        b_fac.clicked.connect(lambda: self._set_text(**{k: v for k, v in FACTORY.items() if k != "content"}))
        rr.addWidget(b_mine)
        rr.addWidget(b_fac)
        _pl.addLayout(rr)
        tr_ = QHBoxLayout()                      # 🅣 plantillas de título
        self.text_template = QComboBox()
        self.text_template.setToolTip("Pone en este texto el estilo de una plantilla (lo que has escrito se queda).\n"
                                      "Las ★ son las tuyas.")
        self.text_template.activated.connect(self._apply_text_template)
        self.btn_save_template = QPushButton("Guardar como plantilla")
        self.btn_save_template.setIcon(D.icono("star"))
        self.btn_save_template.setToolTip("Guarda el estilo de este texto (fuente, colores, caja, posición, fundido) "
                                          "como plantilla tuya: sale con ★ en el botón «Títulos» y aquí.")
        self.btn_save_template.clicked.connect(lambda: self.save_text_template())
        tr_.addWidget(self.text_template, 1)
        tr_.addWidget(self.btn_save_template)
        _pl.addLayout(tr_)
        self._fill_templates()
        self.text_track_box = self._build_track_box("text")   # 📌 pegar el texto a un objeto seguido
        # ✨ fundido al aparecer y al irse
        self._g_txt_anim = QWidget()
        af = QFormLayout(self._g_txt_anim)
        af.setContentsMargins(0, 0, 0, 0)
        row(af, "Fundido", spin("fade", 0.0, 3.0, 0.05, " s", 2), ["fade"])
        self.tw["fade"][0].setToolTip("Segundos de fundido al aparecer y al irse (en el visor y al exportar)")
        return outer

    # -------------------------------------------------------------- 🎯 seguimiento / 📌 pegar a un objeto
    def _build_track_box(self, kind: str) -> QGroupBox:
        box = QGroupBox("🎯 Seguimiento" if kind == "clip" else "📌 Seguir a un objeto")
        v = QVBoxLayout(box)
        info = _dim()
        info.setWordWrap(True)
        row = QHBoxLayout()
        pin = QPushButton("📌 Pegar a un objeto seguido…")
        pin.setToolTip("Que este clip (texto, imagen, emoji, flecha, título…) siga a un objeto del video de debajo, "
                       "conservando el desfase con el que lo colocaste")
        pin.clicked.connect(self._pin_requested)
        unpin = QPushButton("✕ Despegar")
        unpin.setToolTip("Deja de seguir al objeto: se queda donde está en el cabezal")
        unpin.clicked.connect(lambda: self._clip_or_text() and self.ctrl.unpin(self._clip_or_text().id, self._now()))
        if kind == "clip":
            self.btn_track = QPushButton("🎯 Seguimiento…")
            self.btn_track.setToolTip("Sigue un personaje u objeto (solo o a mano, hacia delante y hacia atrás) y úsalo: "
                                      "zoom que lo sigue, encuadre vertical, desenfocarlo/pixelarlo o pegarle algo")
            self.btn_track.clicked.connect(lambda: self._ids and self.track_requested.emit(self._ids[0]))
            self.btn_unblur = QPushButton("🙈 Quitar lo tapado")
            self.btn_unblur.setToolTip("Quita el desenfoque/pixelado que acompaña al objeto")
            self.btn_unblur.clicked.connect(lambda: self._clip() and self.ctrl.remove_track_blur(self._clip().id))
            row.addWidget(self.btn_track)
            row.addWidget(self.btn_unblur)
            self.track_info, self.btn_pin, self.btn_unpin = info, pin, unpin
        else:
            self.text_track_info, self.btn_pin_text, self.btn_unpin_text = info, pin, unpin
        row.addWidget(pin)
        row.addWidget(unpin)
        row.addStretch()
        v.addWidget(info)
        v.addLayout(row)
        return box

    def _clip_or_text(self):
        return self.ctrl.project.clips.get(self._ids[0]) if len(self._ids) == 1 else None

    def _pin_requested(self):
        c = self._clip_or_text()
        if c is None:
            return
        if self.engine is not None and hasattr(self.engine, "pause"):
            self.engine.pause()
        from .pegar_dialog import abrir
        abrir(self.ctrl, c.id, self._now(), self.window())

    def _refresh_track_box(self, c, m=None):
        """Qué recorridos tiene el clip, a qué está pegado y qué se puede hacer."""
        from ..core import motion_track as MT
        info = self.ctrl.pinned_info(c)
        pinned = f"📌 Pegado a «{info.get('name') or 'Objeto'}»." if info else ""
        if c.text is not None:
            self.text_track_info.setText(pinned or "Quieto (no sigue a nada).")
            self.btn_unpin_text.setVisible(bool(info))
            return
        is_video = bool(m and m.kind == "video")
        trks = [x for x in MT.tracks_of(c) if not MT.is_empty(x)]
        lines = []
        if is_video:
            lines.append(("🎯 " + ", ".join(x.get("name", "Objeto") for x in trks)) if trks else
                         "Sin recorridos.")
            if (c.fx or {}).get("tracked_blur"):
                lines.append("🙈 Tapa lo que se sigue.")
        if pinned:
            lines.append(pinned)
        self.track_info.setText("  ".join(lines) or "Quieto (no sigue a nada).")
        self.btn_track.setVisible(is_video)
        self.btn_unblur.setVisible(bool((c.fx or {}).get("tracked_blur")))
        self.btn_unpin.setVisible(bool(info))

    def _canvas_px(self, axis: str) -> float:
        p = self.ctrl.project
        return float(p.width if axis == "x" else p.height)

    def _cur_text(self) -> dict:
        c = self.ctrl.project.clips.get(self._ids[0]) if len(self._ids) == 1 else None
        return dict(c.text) if c is not None and c.text else {}

    def _fill_templates(self):
        from ..core import title_templates as TT
        self.text_template.blockSignals(True)
        self.text_template.clear()
        self.text_template.addItem("Plantilla…", None)
        for key, name in TT.all_templates():
            self.text_template.addItem(name, key)
        self.text_template.setCurrentIndex(0)
        self.text_template.blockSignals(False)

    def _apply_text_template(self, i: int):
        key = self.text_template.itemData(i)
        self.text_template.setCurrentIndex(0)
        if key and self._ids:
            self.ctrl.apply_text_template(list(self._ids), key)

    def save_text_template(self, name: str | None = None):
        from PySide6.QtWidgets import QInputDialog
        from ..core import title_templates as TT
        c = self.ctrl.project.clips.get(self._ids[0]) if len(self._ids) == 1 else None
        if c is None or c.text is None:
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, "Guardar como plantilla", "Nombre de la plantilla:")
            if not ok:
                return None
        try:
            key = TT.save_user(name, c.text, c.duration)
        except ValueError as ex:
            self.ctrl.message.emit(str(ex))
            return None
        self._fill_templates()
        self.ctrl.message.emit(f"★ Plantilla «{key[1:]}» guardada: está en el botón «Títulos» y en «Plantilla…».")
        return key

    def _apply_my_text_style(self):
        from ..core.title_render import my_style
        st = my_style()
        if st:
            self._set_text(**st)

    def _fill_text_page(self, c):
        from ..core.title_render import FACTORY, _get
        t = c.text
        self.text_origin.setText("🟧 Creado por la IA" if c.origin == ORIGIN_AI else "Creado por ti")
        if not self.text_edit.hasFocus():
            self.text_edit.setPlainText(str(t.get("content", "")))
        for key, (_w, setter) in self.tw.items():
            setter(_get(t, key) if key in FACTORY else t.get(key))
        from .inspector_secciones import apagada as _ap
        for k in ("texto_trazo", "texto_animacion"):
            self.secciones[k].set_on(not _ap(c, k))
        name = next((n for n, x, y in self.TEXT_POSITIONS
                     if abs(x - t.get("x", 0.5)) < 0.01 and abs(y - t.get("y", 0.5)) < 0.01), "Personalizada")
        self.text_pos.setCurrentText(name)
        self._refresh_track_box(c)

    def _set_text(self, **props):
        if not self._loading and len(self._ids) == 1:
            self.ctrl.set_text_props(self._ids[0], **props)
            from ..core.title_render import remember_style
            if self.text_remember.isChecked():
                remember_style(props)

    def _on_text_pos(self, name: str):
        for n, x, y in self.TEXT_POSITIONS:
            if n == name:
                self._set_text(x=x, y=y)

    def _build_multi_page(self):
        """«Varios clips»: lo común a todos (bloquear, activar, opacidad, fusión y volumen)."""
        w = self._g_varios_archivo = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.multi_title = QLabel()
        self.multi_title.setObjectName("title")
        self.multi_title.setWordWrap(True)
        row = QHBoxLayout()
        b_lock = QPushButton("Bloquear todos")
        b_lock.setIcon(_glifo("🔒"))
        b_unlock = QPushButton("Desbloquear todos")
        b_unlock.setIcon(_glifo("🔓"))
        b_lock.clicked.connect(lambda: self.ctrl.set_clip_props(self._ids, "Bloquear clips", locked=True))
        b_unlock.clicked.connect(lambda: self.ctrl.set_clip_props(self._ids, "Desbloquear clips", locked=False))
        row.addWidget(b_lock)
        row.addWidget(b_unlock)
        row2 = QHBoxLayout()
        b_on = QPushButton("Activar todos")
        b_off = QPushButton("Desactivar todos")
        b_on.setToolTip("Que se vean y se oigan")
        b_off.setToolTip("Que no se vean ni se oigan (siguen en la línea de tiempo)")
        b_on.clicked.connect(lambda: self.ctrl.set_clip_props(self._targets(), "Activar clips", enabled=True))
        b_off.clicked.connect(lambda: self.ctrl.set_clip_props(self._targets(), "Desactivar clips", enabled=False))
        row2.addWidget(b_on)
        row2.addWidget(b_off)
        lay.addWidget(self.multi_title)
        lay.addLayout(row)
        lay.addLayout(row2)
        # 🎞 opacidad y fusión de todos
        v = self._g_varios_video = QWidget()
        vf = QFormLayout(v)
        vf.setContentsMargins(0, 0, 0, 0)
        self.multi_opacity = QSpinBox()
        self.multi_opacity.setRange(0, 100)
        self.multi_opacity.setSuffix(" %")
        self.multi_opacity.setKeyboardTracking(False)
        self.multi_opacity.setToolTip("La misma opacidad en todos los clips elegidos")
        self.multi_opacity.valueChanged.connect(lambda x: self._loading or self.ctrl.set_clip_props(
            self._visuales(), "Opacidad de varios clips", opacity=x / 100, op_kf=[]))
        vf.addRow("Opacidad", self.multi_opacity)
        from ..core.curves import BLEND_MODES
        self.multi_blend = QComboBox()
        for key, name, _f, _q in BLEND_MODES:
            self.multi_blend.addItem(name, key)
        self.multi_blend.activated.connect(lambda _i: self.ctrl.set_clip_props(
            self._visuales(), "Modo de fusión de varios clips", blend=self.multi_blend.currentData()))
        vf.addRow("Fusión", self.multi_blend)
        # 🔊 volumen de todos
        au = self._g_varios_audio = QWidget()
        af = QFormLayout(au)
        af.setContentsMargins(0, 0, 0, 0)
        self.multi_volume = QSpinBox()
        self.multi_volume.setRange(0, 200)
        self.multi_volume.setSuffix(" %")
        self.multi_volume.setKeyboardTracking(False)
        self.multi_volume.setToolTip("El mismo volumen en todos los clips con sonido elegidos")
        self.multi_volume.valueChanged.connect(lambda x: self._loading or self.ctrl.set_clip_props(
            self._sonoros(), "Volumen de varios clips", volume=x / 100))
        af.addRow("Volumen", self.multi_volume)
        # 🎞 transición elegida en la línea de tiempo
        t = self._g_transicion = QWidget()
        tf = QFormLayout(t)
        tf.setContentsMargins(0, 0, 0, 0)
        from ..core import transitions as TR
        self.trans_info = _dim()
        tf.addRow(self.trans_info)
        self.trans_tipo = QComboBox()
        for k, n, d in TR.CATALOG:
            self.trans_tipo.addItem(n, k)
            self.trans_tipo.setItemData(self.trans_tipo.count() - 1, d, Qt.ToolTipRole)
        self.trans_tipo.activated.connect(lambda _i: self._poner_transicion())
        tf.addRow("Tipo", self.trans_tipo)
        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(TR.MIN_DUR, TR.MAX_DUR)
        self.trans_dur.setSingleStep(0.05)
        self.trans_dur.setDecimals(2)
        self.trans_dur.setSuffix(" s")
        self.trans_dur.setKeyboardTracking(False)
        self.trans_dur.valueChanged.connect(lambda _v: self._loading or self._poner_transicion(auto=False))
        tf.addRow("Duración", self.trans_dur)
        self.trans_auto = QCheckBox("Duración automática")
        self.trans_auto.setToolTip("Según el tipo de transición y, si hay música, a ritmo")
        self.trans_auto.toggled.connect(lambda on: self._loading or self._poner_transicion(auto=on))
        tf.addRow(self.trans_auto)
        tb = QHBoxLayout()
        self.btn_trans_ver = QPushButton("▶ Ver cómo queda")
        self.btn_trans_ver.setToolTip("Prepara unos segundos alrededor del corte tal como saldrán al exportar")
        self.btn_trans_ver.clicked.connect(self._ver_transicion)
        self.btn_trans_quitar = QPushButton("Quitar")
        self.btn_trans_quitar.setIcon(_glifo("🗑"))
        self.btn_trans_quitar.setToolTip("Quita la transición (los clips quedan igual; Ctrl+Z la devuelve)")
        self.btn_trans_quitar.clicked.connect(lambda: self._trans_id and self.ctrl.set_transition(
            [self._trans_id], None))
        tb.addWidget(self.btn_trans_ver)
        tb.addWidget(self.btn_trans_quitar)
        tf.addRow(tb)
        # 🎬 escena y clip compuesto (en Archivo)
        e = self._g_escena = QWidget()
        el = QHBoxLayout(e)
        el.setContentsMargins(0, 0, 0, 0)
        self.btn_editar_escena = QPushButton("Editar escena")
        self.btn_editar_escena.setIcon(_glifo("🎬"))
        self.btn_editar_escena.setToolTip("La abre en la página «Escenas» (también con doble clic en el clip)")
        self.btn_editar_escena.clicked.connect(self._editar_escena)
        self.btn_deshacer_compuesto = QPushButton("Deshacer clip compuesto")
        self.btn_deshacer_compuesto.setToolTip("Devuelve los clips originales en su sitio (Ctrl+Z lo deshace)")
        self.btn_deshacer_compuesto.clicked.connect(self._deshacer_compuesto)
        el.addWidget(self.btn_editar_escena)
        el.addWidget(self.btn_deshacer_compuesto)
        el.addStretch(1)

    # ------------------------------------------------------------- 🗂 pestañas fijas y secciones (fase 2)
    def _componer(self):
        """Las pestañas FIJAS (Video · Audio · Efectos · Transición · Texto · Archivo · Proyecto) con sus secciones,
        en el orden de la tabla de PROPUESTA_INTERFAZ.md (c). Las que no aplican salen apagadas."""
        from . import inspector_secciones as SEC
        self._build_audio_tab()
        self._color_tmp = self._build_color_tab()
        self._build_enhance_box()
        self.color_box.setTitle("")
        self.color_box.setFlat(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 0, 6)
        lay.setSpacing(4)
        cab = QWidget()
        cl = QVBoxLayout(cab)
        cl.setContentsMargins(2, 0, 2, 0)
        cl.setSpacing(0)
        self.clip_title = QLabel()
        self.clip_title.setObjectName("title")
        self.clip_title.setWordWrap(True)
        self.clip_origin = QLabel()
        self.clip_origin.setWordWrap(True)
        cl.addWidget(self.clip_title)
        cl.addWidget(self.clip_origin)
        lay.addWidget(cab)
        self.clip_tabs = SEC.PestanasAjustadas()
        self.clip_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)   # (lo que sobra, al final)
        self.clip_tabs.setDocumentMode(True)
        self.clip_tabs.setUsesScrollButtons(True)       # (su barra va escondida: que no pida ancho)
        self.clip_tabs.tabBar().setExpanding(False)
        self._pag: dict = {}
        self._lay_pag: dict = {}
        for k, nombre, tip in SEC.PESTANAS:
            pg = QWidget()
            pl = QVBoxLayout(pg)
            pl.setContentsMargins(0, 6, 0, 0)
            pl.setSpacing(6)
            self.clip_tabs.addTab(pg, nombre)
            self.clip_tabs.setTabToolTip(self.clip_tabs.count() - 1, tip)
            self._pag[k], self._lay_pag[k] = pg, pl
        self.clip_tabs.currentChanged.connect(self._pestana_cambiada)
        self.clip_tabs.currentChanged.connect(lambda _i: self.clip_tabs.updateGeometry())
        # (la barra de pestañas de Qt no se parte en dos filas: botones con nombre que bajan de fila si no caben,
        # nunca «…» ni flechas; la pestaña de Qt queda por dentro con su estado)
        self.clip_tabs.tabBar().hide()
        self.fila_pestanas = QWidget()
        self.fila_pestanas.setObjectName("pestanas_inspector")
        fp = QHBoxLayout(self.fila_pestanas)
        fp.setContentsMargins(0, 0, 0, 0)
        fp.setSpacing(2)
        self.botones_pestana: list = []
        for i, (k, nombre, tip) in enumerate(SEC.PESTANAS):
            b = SEC.BotonPestana(nombre)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, i=i: self.clip_tabs.setCurrentIndex(i))
            fp.addWidget(b)
            self.botones_pestana.append(b)
        fp.addStretch(1)
        self.fila_pestanas.installEventFilter(self)     # (con poco ancho, «Proyecto» pasa a su icono)
        lay.addWidget(self.fila_pestanas)
        lay.addWidget(self.clip_tabs)
        lay.addStretch()

        def sec(pagina, clave, titulo, cuerpo, abierta=False, interruptor=False, reinicio=False, vigilar=None,
                ayuda=""):
            caja = QWidget()                       # (lo que se pliega; dentro, el grupo con su propia visibilidad)
            cv = QVBoxLayout(caja)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.addWidget(cuerpo)
            if isinstance(cuerpo, QGroupBox):
                cuerpo.setTitle("")
                cuerpo.setFlat(True)
                from .diseno import grupo_sin_titulo
                grupo_sin_titulo(cuerpo)           # (sin el hueco que reservaba el título)
            s_ = SEC.Seccion(clave, titulo, caja, abierta, interruptor, reinicio,
                             cuerpo if vigilar is None else vigilar, ayuda)
            s_.encendida.connect(lambda on, k=clave: self._sec_encendida(k, on))
            s_.restablecer.connect(lambda k=clave: self._sec_restablecer(k))
            self.secciones[clave] = s_
            self._lay_pag[pagina].addWidget(s_)
            return s_

        # --- Video
        sec("video", "transformar", "Transformar", self.transform_box, True, True, True,
            ayuda="Tamaño, posición, rotación, voltear y relleno")
        sec("video", "recorte", "Recorte", self.crop_box, True, True, True,
            ayuda="Recortar los bordes (lo mismo que «Recortar» en el visor)")
        sec("video", "encuadre", "Zoom dinámico y encuadre", self.frame_box, True, True, True,
            ayuda="Zoom con fotogramas clave, centro, disposición en pantalla y posición y tamaño animados")
        sec("video", "composicion", "Composición", self.blend_box, False, True, True,
            ayuda="Opacidad y modo de fusión")
        self.speed_sec = SEC.Seccion("velocidad", "Velocidad", self.speed_box, False, False, True,
                                     ayuda="Velocidad del clip (tecla R): porcentaje, marcha atrás, congelar imagen "
                                           "y cámara lenta suave")
        self.speed_sec.restablecer.connect(lambda: self._sec_restablecer("velocidad"))
        self.secciones["velocidad"] = self.speed_sec
        self._tl_clip = self._lay_pag["video"]
        self._tl_clip.addWidget(self.speed_sec)
        self._vel_en = self._tl_clip
        sec("video", "reencuadre", "Reencuadre vertical", self._caja_reencuadre(), False,
            ayuda="En un proyecto vertical: fondo borroso arriba y abajo, o llenar la pantalla con un recorte que "
                  "sigue la acción")
        sec("video", "mejorar", "Mejorar imagen", self.enhance_box, False, True, True,
            ayuda="Reducir ruido, estabilizar y detectar cortes de escena")
        sec("video", "seguimiento", "Seguimiento", self.track_box, ayuda="Seguir un personaje u objeto y usarlo")
        sec("video", "color", "Color", self.color_box, False, True, True,
            ayuda="Corrección de color: ruedas, ajustes, LUT y color automático")
        sec("video", "varios_video", "Varios clips", self._g_varios_video, True,
            ayuda="Lo común a todos los clips elegidos")
        # --- Audio
        sec("audio", "volumen", "Volumen y balance", self._g_volumen, True, True, True,
            ayuda="Apagar = silenciar el clip sin perder su volumen")
        sec("audio", "ecualizador", "Ecualizador", self._g_eq, True, True, True)
        self._audio_lay = self._lay_pag["audio"]
        sec("audio", "varios_audio", "Varios clips", self._g_varios_audio, True,
            ayuda="El mismo volumen en todos los clips con sonido elegidos")
        # --- Efectos
        sec("efectos", "efectos_edits", "Destello, fundidos y temblor", self.effects_box, True, True, True)
        sec("efectos", "sombra", "Sombra", self._build_sombra_box(), True, True, True,
            ayuda="Una sombra detrás del clip para darle profundidad, como el «Drop Shadow» de Resolve: sigue la forma "
                  "de la imagen (un PNG recortado da su silueta) · ● = apagarla sin perderla · ↺ = la pequeña de fábrica")
        self._aplicados_lay = self._lay_pag["efectos"]
        self.efectos_vacio = QWidget()             # (marca dónde van los efectos aplicados; no se ve)
        self.efectos_vacio.setFixedHeight(0)
        self._pag["efectos"].setToolTip("Los efectos de la página Efectos que pongas en el clip salen aquí, cada uno "
                                        "con su interruptor")
        self._aplicados_lay.addWidget(self.efectos_vacio)
        # --- Transición
        sec("transicion", "transicion", "Transición", self._g_transicion, True, False, True,
            ayuda="Tipo y duración de la transición elegida · ↺ = la de siempre")
        self._pag["transicion"].setToolTip("Elige una transición en la línea de tiempo (el rombo entre dos clips) "
                                           "para cambiar su tipo y su duración")
        # --- Texto
        cont = QWidget()
        ccl = QVBoxLayout(cont)
        ccl.setContentsMargins(0, 0, 0, 0)
        for w_ in (self.text_origin, self.text_edit, self._spell_w):
            ccl.addWidget(w_)
        sec("texto", "texto_contenido", "Contenido", cont, True)
        sec("texto", "texto_fuente", "Fuente y estilo", self._g_txt_fuente, True, reinicio=True)
        sec("texto", "texto_posicion", "Posición", self._g_txt_pos, True, reinicio=True)
        sec("texto", "texto_trazo", "Trazo", self._g_txt_trazo, False, True, True)
        s_sombra = sec("texto", "texto_sombra", "Sombra", self._g_txt_sombra, False, True, True)
        s_fondo = sec("texto", "texto_fondo", "Fondo", self._g_txt_fondo, False, True, True)
        s_desenf = sec("texto", "texto_desenfocar", "Desenfocar lo de debajo", self._g_txt_desenf, False, True, True,
                       ayuda="Mientras se ve el texto, lo de debajo se desenfoca (en el visor y al exportar)")
        s_borroso = sec("texto", "texto_borroso", "Fondo borroso alrededor", self._g_txt_borroso, False, True, True,
                        ayuda="Un recuadro alrededor del texto que desenfoca el video de debajo")
        sec("texto", "texto_animacion", "Fundido y animación", self._g_txt_anim, False, True, True)
        sec("texto", "texto_plantilla", "Plantilla y mi estilo", self._g_txt_plantilla)
        sec("texto", "texto_pegar", "Pegar a un objeto", self.text_track_box)
        set_help(self._pag["texto"], "texto_pantalla")
        # (los grupos que se encendían con su casilla: ahora con el ● de su sección)
        for s_, grupo, clave in ((s_sombra, self._g_txt_sombra, "shadow"), (s_fondo, self._g_txt_fondo, "box"),
                                 (s_borroso, self._g_txt_borroso, "zone_blur")):
            grupo.setCheckable(False)
            self.tw[clave] = (s_.boton, lambda v, s_=s_: s_.set_on(bool(v)))
        self._g_txt_desenf.setCheckable(False)
        sp_w = self.tw["blur_under"][0]
        self.tw["blur_under"] = (sp_w, lambda v, s_=s_desenf: (self._sp_set_blur(v), s_.set_on(float(v or 0) > 0)))
        # --- Archivo
        sec("archivo", "informacion", "Información", self._g_info, True)
        sec("archivo", "ajustes", "Ajustes", self._g_props, True)
        sec("archivo", "escena", "Escena y clip compuesto", self._g_escena, True)
        sec("archivo", "nota", "Nota para la IA", self._g_note, False)
        sec("archivo", "varios_archivo", "Varios clips", self._g_varios_archivo, True)
        # --- Proyecto
        sec("proyecto", "formato", "Formato", self._g_formato, True)
        sec("proyecto", "sonoridad", "Sonoridad", self._g_sonoridad, True)
        sec("proyecto", "mezcla", "Mezcla y música", self._g_mezcla, True)
        sec("proyecto", "narracion", "Narración", self._g_narracion, False)
        sec("proyecto", "subtitulos", "Subtítulos del proyecto", self._g_subtitulos, False)
        for pl in self._lay_pag.values():
            pl.addStretch(1)
        for pg, clave in (("video", "clip"), ("archivo", "clip"), ("audio", "audio_clip"), ("efectos", "efectos"),
                          ("transicion", "transiciones"), ("proyecto", "proyecto")):
            set_help(self._pag[pg], clave)                  # (F1 y clic derecho: lo que no tenga la suya propia)
        set_help(self.fila_pestanas, "clip")
        self._con_interruptor = {k for k, s_ in self.secciones.items() if s_.boton.isEnabled()}

    def poner_en(self, clave: str, widget: QWidget, arriba: bool = False) -> bool:
        """Mete un panel que ya existe dentro de una sección del Inspector (para la ventana: p. ej. los Subtítulos
        en «Proyecto → Subtítulos del proyecto», la Mezcla y música en «Proyecto → Mezcla y música»). True si se pudo."""
        s_ = self.secciones.get(clave)
        if s_ is None or widget is None:
            return False
        caja = s_.body.layout()
        if arriba:
            caja.insertWidget(0, widget)
        else:
            caja.addWidget(widget)
        widget.show()
        return True

    # ---- 📍 gancho de la fase 5: el índice de marcas (ui/marcadores_panel.instalar)
    def poner_marcadores(self, widget: QWidget) -> bool:
        """Pone `widget` (el índice de marcas) como sección propia «Marcadores» en Proyecto, plegable como las demás
        (se recuerda si la dejas abierta). Una vez: si ya está, no hace nada. True si quedó puesta."""
        if widget is None or "marcadores" in self.secciones:
            return False
        from . import inspector_secciones as SEC
        caja = QWidget()                           # (lo que se pliega, como en las demás secciones)
        cv = QVBoxLayout(caja)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(widget)
        widget.show()
        s_ = SEC.Seccion("marcadores", "Marcadores", caja, False, False, False, widget,
                         "Índice de marcas en el orden del video: tomas repetidas, muletillas, cortes dudosos, marcas "
                         "de OBS, temas, huecos, material repetido y tus marcadores. Clic en una = el cabezal allí")
        self.secciones["marcadores"] = s_
        lay = self._lay_pag["proyecto"]
        lay.insertWidget(max(0, lay.count() - 1), s_)    # (antes del espacio libre del final de la página)
        self._marcadores_w = widget
        return True

    def mostrar_marcadores(self) -> bool:
        """«Cada acción abre su panel» (M+M = escribir la nota de un marcador): enseña el Inspector, la pestaña
        Proyecto y la sección «Marcadores» desplegada, con el foco en su campo de nota. True si quedó a la vista."""
        s_ = self.secciones.get("marcadores")
        if s_ is None:
            return False
        if not s_.is_open():
            s_.set_open(True, save=False)
        nota = getattr(getattr(self, "_marcadores_w", None), "nota", None)
        win = self.window()
        if hasattr(win, "abrir_para_usar"):
            return bool(win.abrir_para_usar(nota if nota is not None else s_, nota))
        s_.show()
        if nota is not None:
            nota.setFocus(Qt.OtherFocusReason)
        return s_.isVisible()

    def _caja_reencuadre(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.reenc_info = _dim()
        v.addWidget(self.reenc_info)
        h = QHBoxLayout()
        self.btn_reenc_borroso = QPushButton("Fondo borroso")
        self.btn_reenc_borroso.setToolTip("El video entero en el centro y arriba y abajo su propia imagen borrosa "
                                          "(como tus Shorts)")
        self.btn_reenc_borroso.clicked.connect(lambda: self._clip() and self.ctrl.set_fill(
            [self._clip().id], __import__("editoria.core.fill", fromlist=["x"]).DEFAULT))
        self.btn_reenc_seguir = QPushButton("Seguir la acción")
        self.btn_reenc_seguir.setToolTip("Llena la pantalla vertical y el recorte sigue lo que pasa (se analiza en "
                                         "segundo plano; Ctrl+Z lo deshace)")
        self.btn_reenc_seguir.clicked.connect(self._seguir_accion)
        self.btn_reenc_quitar = QPushButton("Quitar")
        self.btn_reenc_quitar.setToolTip("Quita el fondo borroso y el recorte que sigue la acción")
        self.btn_reenc_quitar.clicked.connect(self._quitar_reencuadre)
        for b in (self.btn_reenc_borroso, self.btn_reenc_seguir, self.btn_reenc_quitar):
            h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        return w

    def _seguir_accion(self):
        c = self._clip()
        win = self.window()
        if c is not None and hasattr(win, "follow_action"):
            win.follow_action([c.id])

    def _quitar_reencuadre(self):
        from ..core import fill as FILL
        c = self._clip()
        if c is None:
            return
        pila = self.ctrl.undo_stack
        cambios = FILL.of(c.fx) is not None or bool((c.layout or {}).get("follow"))
        if not cambios:
            return
        pila.beginMacro("Quitar el reencuadre vertical")
        try:
            if FILL.of(c.fx) is not None:
                self.ctrl.set_fill([c.id], None)
            if (self.ctrl.project.clips[c.id].layout or {}).get("follow"):
                self.ctrl.set_follow(c.id, None, "Quitar «sigue la acción»")
        finally:
            pila.endMacro()

    def _refresh_reencuadre(self, c, m, editable: bool):
        from ..core import fill as FILL
        relleno = FILL.of(c.fx) is not None
        sigue = bool((c.layout or {}).get("follow"))
        self.reenc_info.setText("Con fondo borroso." if relleno else "Sigue la acción." if sigue else
                                "Sin reencuadre.")
        self.btn_reenc_seguir.setEnabled(editable and bool(m and m.kind == "video")
                                         and hasattr(self.window(), "follow_action"))
        self.btn_reenc_borroso.setEnabled(editable and not relleno)
        self.btn_reenc_quitar.setEnabled(editable and (relleno or sigue))

    def _pestana_cambiada(self, i: int):
        if not self._pestana_codigo:
            self._pestana_usuario = i
        self._sincronizar_botones()

    def _sincronizar_botones(self):
        """Las pestañas: la de delante marcada; las que no aplican, atenuadas con su porqué en el tooltip. Sin nada
        elegido solo vale «Proyecto» (que ya es el título): la fila entera se esconde —sin seis pestañas grises que
        parecían un fallo ni hueco bajo el título—."""
        from .inspector_secciones import INDICE, PESTANAS
        cur = self.clip_tabs.currentIndex()
        bots = getattr(self, "botones_pestana", [])
        solo_proyecto = all(not self.clip_tabs.isTabEnabled(i) for i in range(len(bots)) if i != INDICE["proyecto"])
        for i, b in enumerate(bots):
            activa = self.clip_tabs.isTabEnabled(i)
            b.setEnabled(activa)
            b.setChecked(i == cur)
            base = PESTANAS[i][2]
            tip = base if activa else base + "\n\n(No aplica a lo elegido: elige un clip de ese tipo en la línea de " \
                                             "tiempo)"
            if not b.text():                          # («Proyecto» en solo icono lleva su nombre delante)
                tip = f"{PESTANAS[i][1]}: {tip}"
            if b.toolTip() != tip:
                b.setToolTip(tip)
        fila = getattr(self, "fila_pestanas", None)
        if fila is not None and fila.isHidden() != solo_proyecto:
            fila.setVisible(not solo_proyecto)

    def pestana_activa(self) -> str:
        from .inspector_secciones import PESTANAS
        return PESTANAS[self.clip_tabs.currentIndex()][0]

    def ir_a(self, clave: str) -> bool:
        """Pone delante esa pestaña (si está activa). Ej.: ir_a("audio") desde la página Audio."""
        from .inspector_secciones import INDICE
        i = INDICE.get(clave, -1)
        if i < 0 or not self.clip_tabs.isTabEnabled(i):
            return False
        self.clip_tabs.setCurrentIndex(i)
        return True

    def _aplicar_pestanas(self, activas: set, deseada: str):
        from .inspector_secciones import INDICE, PESTANAS
        activas = set(activas) | {"proyecto"}
        self._pestana_codigo = True
        try:
            for k, _n, _t in PESTANAS:
                self.clip_tabs.setTabEnabled(INDICE[k], k in activas)
            self.clip_tabs.setCurrentIndex(INDICE[deseada if deseada in activas else "proyecto"])
        finally:
            self._pestana_codigo = False
        self._sincronizar_botones()

    def _pestana_para(self, modo: str, activas: set, nuevo: bool, visual: bool = True, sonido: bool = False) -> str:
        """Qué pestaña se pone delante al elegir algo: la de lo elegido; si eliges otro clip del mismo tipo, sigues
        donde estabas (un audio siempre abre su ecualizador; un video no se queda en el ecualizador salvo en la
        página Audio)."""
        from .inspector_secciones import PESTANAS
        cur = PESTANAS[self.clip_tabs.currentIndex()][0]
        if modo in ("proyecto", "transicion", "texto"):
            if modo == "texto" and not nuevo and cur in activas and cur != "proyecto":
                return cur
            return modo
        if modo == "audio":
            return "audio" if nuevo or cur not in activas or cur == "proyecto" else cur
        if modo == "clip":
            if getattr(self, "prefer_audio", False) and sonido:
                return "audio"
            if cur in activas and cur not in ("audio", "proyecto"):
                return cur
            return "video" if visual else "audio"
        if cur in activas and cur != "proyecto":            # varios
            return cur
        return next((k for k in ("video", "audio", "efectos", "archivo") if k in activas), "proyecto")

    def _ver_secciones(self, modo: str):
        varios = modo == "varios"
        for k in ("varios_video", "varios_audio", "varios_archivo"):
            self.secciones[k].setVisible(varios)
        for k in ("transformar", "recorte", "encuadre", "composicion", "mejorar", "seguimiento", "color",
                  "reencuadre", "volumen", "ecualizador", "informacion", "ajustes", "nota"):
            if varios:
                self.secciones[k].setVisible(False)
        if varios:
            self.speed_sec.setVisible(False)
        self.secciones["transicion"].setVisible(modo == "transicion")
        if modo not in ("clip", "varios"):
            self.secciones["sombra"].setVisible(False)       # (🌑 solo con un clip de video o imagen)
        if varios:
            self.secciones["escena"].setVisible(False)

    # ---- ● / ↺ de cada sección
    def _ids_para(self, clave: str) -> list[str]:
        if clave == "volumen":
            ac = self._aclip()
            return [ac.id] if ac is not None else self._ids
        if clave == "transicion":
            return [self._trans_id] if self._trans_id else []
        return list(self._ids)

    def _sec_encendida(self, clave: str, on: bool):
        if self._loading:
            return
        if clave == "ecualizador":
            self._on_eq_on(on)
            return
        nativos = {"texto_sombra": "shadow", "texto_fondo": "box", "texto_borroso": "zone_blur"}
        if clave in nativos:
            self._set_text(**{nativos[clave]: bool(on)})
            return
        from . import inspector_secciones as SEC
        p = self.ctrl.project
        if clave == "sombra":            # 🌑 ● sin sombra guardada = poner la de fábrica; si no, apagar / encender
            from ..core import decor
            clips = self._sombra_clips()
            sin_nada = [c.id for c in clips if self._sombra_de(c) is None]
            if on:
                cambios = [(c.id, SEC.cambios_encender(c, clave)) for c in clips if SEC.apagada(c, clave)]
            else:
                cambios = [(c.id, SEC.cambios_apagar(c, clave)) for c in clips if decor.shadow_of(c.fx) is not None]
            cambios = [(i, pr) for i, pr in cambios if pr]
            if on and sin_nada:
                pila = self.ctrl.undo_stack
                pila.beginMacro("Encender sombra")
                try:
                    self.poner_sombra(sin_nada)
                    self._aplicar_cambios(cambios, "Encender sombra") if cambios else None
                finally:
                    pila.endMacro()
            else:
                self._aplicar_cambios(cambios, ("Encender" if on else "Apagar") + " sombra")
            return
        if clave == "texto_desenfocar" and on and not SEC.apagada(self._clip(), clave):
            self._set_text(blur_under=0.5)              # (nunca tuvo: se enciende con lo de siempre)
            return
        nombre = self.secciones[clave].head.text() if clave in self.secciones else clave
        cambios = []
        for cid in self._ids_para(clave):
            c = p.clips.get(cid)
            props = SEC.cambios_encender(c, clave) if on else SEC.cambios_apagar(c, clave)
            if props:
                cambios.append((cid, props))
        self._aplicar_cambios(cambios, ("Encender " if on else "Apagar ") + nombre)

    def _aplicar_cambios(self, cambios: list, texto: str):
        """Aplica [(clip, props)] en UN paso de Ctrl+Z (nada = ningún paso vacío; el ● vuelve a su sitio). El texto
        del clip va por set_text_props (set_clip_props ya tiene un parámetro «text»)."""
        if not cambios:
            self._refresh()
            return
        pila = self.ctrl.undo_stack
        pila.beginMacro(texto)
        try:
            for cid, props in cambios:
                props = dict(props)
                txt = props.pop("text", None)
                if props:
                    self.ctrl.set_clip_props([cid], texto, **props)
                if txt is not None:
                    self.ctrl.set_text_props(cid, **txt)
        finally:
            pila.endMacro()

    def _sec_restablecer(self, clave: str):
        if self._loading:
            return
        from ..core.title_render import FACTORY
        from ..core.nota_texto import ZONE_DEFAULTS
        texto = {"texto_fuente": ["font", "font_style", "color", "size", "tracking", "line_spacing", "bold", "italic",
                                  "underline", "strike", "case", "align"],
                 "texto_posicion": ["x", "y", "zoom_x", "zoom_y", "rotation"],
                 "texto_trazo": ["stroke_color", "stroke_size", "stroke_outside"],
                 "texto_sombra": [k for k in FACTORY if k.startswith("shadow")],
                 "texto_fondo": [k for k in FACTORY if k.startswith("box")],
                 "texto_desenfocar": ["blur_under"], "texto_animacion": ["fade"]}
        if clave in texto:
            self._set_text(**{k: FACTORY[k] for k in texto[clave]})
            return
        if clave == "texto_borroso":
            self._set_text(**ZONE_DEFAULTS)
            return
        if clave == "velocidad":
            if self._ids:
                self.ctrl.set_speed(self._targets(), speed=1.0, reverse=False, ripple=self.ripple_speed.isChecked())
            return
        if clave == "ecualizador":
            self._set_eq({"on": True, "bands": E.default_bands()}, "Reiniciar ecualizador")
            return
        if clave == "transicion":
            from ..core import transitions as TR
            if self._trans_id:
                self.ctrl.set_transition([self._trans_id], TR.DEFAULT, None if TR.auto_on() else 0.5)
            return
        from . import inspector_secciones as SEC
        if clave == "sombra":            # 🌑 ↺ = la pequeña de fábrica (encendida), no quitarla
            from ..core import decor
            changes = {}
            for c in self._sombra_clips():
                fx = SEC._fx_sin_apagado(dict(c.fx or {}), "sombra")
                fx["shadow"] = decor.sombra(**decor.SOMBRA_EFECTO)
                changes[c.id] = {"fx": fx}
            if changes:
                self.ctrl.batch_clip_props(changes, "Restablecer sombra")
            return
        p = self.ctrl.project
        nombre = self.secciones[clave].head.text() if clave in self.secciones else clave
        cambios = [(cid, SEC.cambios_restablecer(p.clips.get(cid), clave)) for cid in self._ids_para(clave)]
        self._aplicar_cambios([(cid, pr) for cid, pr in cambios if pr], f"Restablecer {nombre}")

    def _refrescar_interruptores(self, c):
        """El ● de cada sección según el clip (encendida / apagada)."""
        from . import inspector_secciones as SEC
        for k in self._con_interruptor:
            s_ = self.secciones.get(k)
            if s_ is None:
                continue
            if k == "ecualizador":
                on = bool(c is not None and c.eq and c.eq.get("on", True))
                ac = self._aclip()
                on = bool(ac is not None and ac.eq and ac.eq.get("on", True)) if ac is not None else on
            elif k in ("texto_sombra", "texto_fondo", "texto_borroso", "texto_desenfocar"):
                continue                               # (los pone _fill_text_page con su valor)
            elif k == "sombra":                        # (encendida = la lleva puesta)
                from ..core import decor
                cs = self._sombra_clips()
                c0 = next((x for x in cs if c is not None and x.id == c.id), cs[0] if cs else None)
                on = bool(c0 is not None and decor.shadow_of(c0.fx) is not None)
            elif k == "volumen":
                ac = self._aclip()
                on = not SEC.apagada(ac, "volumen")
            else:
                on = not SEC.apagada(c, k)
            s_.set_on(on)

    # ---- efectos aplicados (página Efectos), cada uno con ● y 🗑
    def _refrescar_aplicados(self, c):
        from ..core import effects as EFX
        from . import inspector_secciones as SEC
        claves = []
        if c is not None and c.text is None:
            claves = list(EFX.visible_of(c.fx))
            claves = [k for k in claves if k not in ("flash", "shake", "lines", "focus_in")]   # (ya en su sección)
            for k in ((c.fx or {}).get(SEC.APAGADO) or {}):
                if k.startswith("efecto:") and k.split(":", 1)[1] not in claves:
                    claves.append(k.split(":", 1)[1])
        if list(self._aplicados) != claves:
            for k, s_ in list(self._aplicados.items()):
                self._aplicados_lay.removeWidget(s_)
                s_.hide()
                s_.deleteLater()
                self.secciones.pop(f"efecto:{k}", None)
            self._aplicados = {}
            for k in claves:
                cuerpo = QWidget()
                h = QHBoxLayout(cuerpo)
                h.setContentsMargins(0, 0, 0, 0)
                h.addStretch(1)
                b = QPushButton("Quitar")
                b.setIcon(_glifo("🗑"))
                b.setToolTip("Quita este efecto del clip (Ctrl+Z lo devuelve)")
                b.clicked.connect(lambda _c=False, kk=k: QTimer.singleShot(0, lambda: self._quitar_efecto(kk)))
                h.addWidget(b)
                clave = f"efecto:{k}"
                s_ = SEC.Seccion(clave, self._nombre_efecto(k), cuerpo, True, True, False,
                                 ayuda="Sus ajustes, en la página Efectos")
                s_.encendida.connect(lambda on, kk=clave: self._sec_encendida(kk, on))
                self.secciones[clave] = s_
                self._aplicados_lay.insertWidget(self._aplicados_lay.indexOf(self.efectos_vacio), s_)
                self._aplicados[k] = s_
        for k, s_ in self._aplicados.items():
            s_.set_on(not SEC.apagada(c, f"efecto:{k}"))


    @staticmethod
    def _nombre_efecto(k: str) -> str:
        try:
            from .effects_panel import LOOKS
            nombres = {kk: t for kk, t, _v, _h in LOOKS}
        except Exception:  # noqa: BLE001
            nombres = {}
        return nombres.get(k, {"letterbox": "▭ Barras de cine", "invert": "◑ Negativo"}.get(k, k))

    def _quitar_efecto(self, k: str):
        from ..core import effects as EFX
        from . import inspector_secciones as SEC
        c = self._clip()
        if c is None:
            return
        fx = EFX.without(c.fx, [k]) or {}
        fx = SEC._fx_sin_apagado(fx, f"efecto:{k}")
        self.ctrl.set_clip_props([c.id], f"✦ Quitar {self._nombre_efecto(k)}", fx=fx or None)

    # ---- recorte
    def _on_crop(self, k: str, v: float):
        c = self._clip()
        if self._loading or c is None:
            return
        box = dict(self.transform_box._box_now(c))
        crop = dict(box.get("crop") or {})
        crop[k] = round(v / 100, 4)
        contrario = {"l": "r", "r": "l", "t": "b", "b": "t"}[k]
        crop[k] = min(crop[k], round(0.98 - float(crop.get(contrario, 0.0)), 4))
        crop = {kk: vv for kk, vv in crop.items() if vv > 1e-4}
        if crop:
            box["crop"] = crop
        else:
            box.pop("crop", None)
        if c.layout is None:
            box["bg"] = "none"
        self.ctrl.set_clip_layout(c.id, box, self._now(), "✂ Recorte")

    def _refresh_crop(self, c):
        box = self.transform_box._box_now(c) if c is not None else {}
        crop = box.get("crop") or {}
        for k, sp in self.crop_spins.items():
            sp.setValue(float(crop.get(k, 0.0)) * 100)
        from ..core import decor
        sv = decor.suavizar_of(c.fx) if c is not None else 0.0
        self.suave_val.setValue(sv * 100)
        self.suave_on.setChecked(sv > 0)

    # ---- transición
    def set_transition(self, rid: str | None):
        """🎞 Transición elegida en la línea de tiempo (id del clip de la DERECHA del corte); None = ninguna."""
        self._trans_id = rid
        if rid:
            self._ids = []
            self._all_ids = []
            self._audio_id = None
        self._refresh()

    def _mirar_transicion(self):
        """(sin enganche en la ventana) la línea de tiempo elige una transición vaciando la selección y luego
        guardando cuál: se mira justo después."""
        tl = getattr(self.window(), "timeline", None)
        rid = getattr(tl, "sel_trans", None)
        if rid != self._trans_id and not self._ids:
            self.set_transition(rid)

    def _poner_transicion(self, auto: bool | None = None):
        if self._loading or not self._trans_id:
            return
        if auto is None:
            auto = self.trans_auto.isChecked()
        self.ctrl.set_transition([self._trans_id], self.trans_tipo.currentData(),
                                 None if auto else float(self.trans_dur.value()))

    def _ver_transicion(self):
        c = self.ctrl.project.clips.get(self._trans_id or "")
        if c is None or self.engine is None:
            return
        self.engine.user_seek(c.start) if hasattr(self.engine, "user_seek") else None
        self._view_here()

    def _refresh_transicion(self):
        from ..core import transitions as TR
        p = self.ctrl.project
        c = p.clips.get(self._trans_id or "")
        t = TR.of(c) if c is not None else None
        apag = (c.fx or {}).get("apagado", {}).get("transicion") if c is not None else None
        if t is None and apag:
            t = ((apag.get("fx") or {}).get("trans")) or None
        prev = TR.previous(p, c) if c is not None else None
        if c is None or t is None:
            return False
        nm = lambda x: (p.media_of(x).name if x is not None and p.media_of(x) else "¿?")   # noqa: E731
        self.trans_info.setText(f"Entre «{nm(prev)}» y «{nm(c)}» ({fmt_time(c.start)})")
        self.trans_tipo.setCurrentIndex(max(0, self.trans_tipo.findData(t.get("type"))))
        self.trans_dur.setValue(float(t.get("dur", 0.5)))
        self.trans_auto.setChecked(False)               # (la duración automática se calcula al ponerla)
        return True

    # ---- escena / clip compuesto
    def _escena_de(self, c):
        from ..core import scenes as _sc
        eid = _sc.id_de_nota(c.note) if c is not None else None
        return eid if eid and eid in self.ctrl.project.scenes else None

    def _editar_escena(self):
        eid = self._escena_de(self._clip())
        tl = getattr(self.window(), "timeline", None)
        if eid and tl is not None and hasattr(tl, "scene_open_requested"):
            tl.scene_open_requested.emit(eid)

    def _deshacer_compuesto(self):
        c = self._clip()
        if c is None or not self.ctrl.is_compound(c.id):
            return
        ids = self.ctrl.break_compound(c.id)
        tl = getattr(self.window(), "timeline", None)
        if ids and tl is not None:
            tl.set_selection(ids)

    def _visuales(self) -> list[str]:
        p = self.ctrl.project
        return [i for i in self._ids if i in p.clips and p.track(p.clips[i].track_id) is not None
                and p.track(p.clips[i].track_id).kind != TRACK_AUDIO]

    def _sonoros(self) -> list[str]:
        p = self.ctrl.project
        out = []
        for i in self._targets():
            c = p.clips.get(i)
            m = p.media_of(c) if c else None
            if c is not None and c.text is None and m is not None and (m.kind == "audio" or m.has_audio):
                out.append(i)
        return out

    # ------------------------------------------------------------- refresco
    def set_selection(self, ids: list[str]):
        """Una imagen y su sonido vinculado se muestran como un solo clip (como en Resolve):
        la pestaña Audio y el volumen actúan sobre el sonido."""
        if getattr(self, "_paso_abierto", False):
            self._cerrar_paso()
        tm = getattr(self, "_txt_timer", None)
        if tm is not None and tm.isActive():         # (lo escrito y aún sin guardar va a SU texto: nunca se pierde)
            tm.stop()
            self._set_text(content=self.text_edit.toPlainText())
        ids = list(ids)
        self._nuevo = ids != list(getattr(self, "_all_ids", [])) or bool(self._trans_id)
        self._all_ids = ids
        self._audio_id = None
        self._trans_id = None
        p = self.ctrl.project
        clips = [p.clips[i] for i in ids if i in p.clips]
        if len(clips) == 2 and clips[0].link and clips[0].link == clips[1].link:
            kinds = {c.id: p.track(c.track_id).kind for c in clips}
            vis = [c for c in clips if kinds[c.id] != TRACK_AUDIO]
            aud = [c for c in clips if kinds[c.id] == TRACK_AUDIO]
            if len(vis) == 1 and len(aud) == 1:
                ids = [vis[0].id]
                self._audio_id = aud[0].id
        self._ids = ids
        self._refresh()
        self._nuevo = False
        if not ids:
            QTimer.singleShot(0, self._mirar_transicion)

    def _aclip(self):
        """El clip cuyo sonido se edita: el sonido vinculado o el propio clip."""
        if self._audio_id and self._audio_id in self.ctrl.project.clips:
            return self.ctrl.project.clips[self._audio_id]
        return self._clip()

    def _targets(self) -> list[str]:
        """Todos los clips seleccionados (incluido el sonido vinculado)."""
        return [i for i in getattr(self, "_all_ids", self._ids) if i in self.ctrl.project.clips] or self._ids

    def _cabecera(self, titulo: str, origen: str = "", color: str = "#9aa1ad"):
        """El nombre de lo elegido. (20/11, auditoría) «Creado por ti» y el nombre del proyecto van al tooltip del
        nombre —unos 20 px más para lo que se ajusta—; «Creado por la IA» (naranja) se queda a la vista."""
        self.clip_title.setText(titulo)
        self.clip_title.setToolTip(f"{titulo}\n{origen}" if origen else titulo)
        a_la_vista = bool(origen) and color != "#9aa1ad"
        self.clip_origin.setText(origen if a_la_vista else "")
        self.clip_origin.setStyleSheet(f"color: {color};")
        self.clip_origin.setVisible(a_la_vista)

    def _refresh(self):
        self._loading = True
        nuevo = getattr(self, "_nuevo", False)
        try:
            p = self.ctrl.project
            self._ids = [i for i in self._ids if i in p.clips]
            if self._trans_id and (self._ids or self._trans_id not in p.clips):
                self._trans_id = None
            self._refresh_project(p)
            if not self._ids and self._trans_id and self._refresh_transicion():
                self._modo = "transicion"
                self._cabecera("Transición")
                self._ver_secciones("transicion")
                self._aplicar_pestanas({"transicion"}, "transicion")
                self._refrescar_interruptores(None)
            elif not self._ids:
                self._modo = "proyecto"
                self._cabecera("Proyecto", p.name or "")
                self._ver_secciones("proyecto")
                self._refrescar_aplicados(None)
                self._aplicar_pestanas(set(), "proyecto")
            elif len(self._ids) > 1:
                self._modo = "varios"
                self._refresh_varios(p, nuevo)
            else:
                c = p.clips[self._ids[0]]
                if c.text is not None:
                    self._modo = "texto"
                    self._cabecera("Texto en pantalla", "🟧 Creado por la IA" if c.origin == ORIGIN_AI else
                                   "Creado por ti", "#ff9f1c" if c.origin == ORIGIN_AI else "#9aa1ad")
                    self._ver_secciones("texto")
                    self._fill_text_page(c)
                    self._refrescar_aplicados(None)
                    tr = p.track(c.track_id)
                    self._aplicar_pestanas({"texto", "archivo"}, self._pestana_para("texto", {"texto", "archivo"},
                                                                                    nuevo))
                    ed = not c.locked and not (tr and tr.locked)
                    self._pag["texto"].setEnabled(ed)
                    self._editable(ed, ("texto",))
                    self._refresh_archivo(c, p.media_of(c), tr)
                    self._refrescar_interruptores(c)
                else:
                    self._refresh_clip(p, c, nuevo)
        finally:
            self._loading = False

    def _refresh_project(self, p):
        self.project_name.setText(p.name)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(p.format)))
        for idx, (_l, w, h) in enumerate(RESOLUTIONS):
            if (w, h) == (p.width, p.height):
                self.res_combo.setCurrentIndex(idx)
        if p.fps in FPS_OPTIONS:
            self.fps_combo.setCurrentIndex(FPS_OPTIONS.index(p.fps))
        self.project_stats.setText(
            f"Duración: {fmt_time(p.duration())}\n{len(p.clips)} clips · "
            f"{len(p.media)} archivos en la biblioteca · {len(p.markers)} marcadores")
        self.chk_loudnorm.setChecked(bool(getattr(p, "loudnorm", True)))
        subs = getattr(p, "subtitles", None)
        self.chk_subs.setChecked(bool(getattr(subs, "enabled", False)))
        musica = [t for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is not None]
        self.mezcla_info.setText(f"{len(musica)} pista(s) de música que bajan cuando hablas." if musica else
                                 "Ninguna pista de música baja cuando hablas.")
        self.narracion_info.setText(f"{len(p.transcripts)} archivo(s) con la narración transcrita." if
                                    p.transcripts else "Aún no hay narración transcrita.")

    def _refresh_varios(self, p, nuevo: bool):
        clips = [p.clips[i] for i in self._ids]
        vis = self._visuales()
        son = self._sonoros()
        self._cabecera(f"{len(self._ids)} clips seleccionados", "Lo común a todos")
        self.multi_title.setText(f"{len(self._ids)} clips seleccionados")
        self._ver_secciones("varios")
        self._editable(True, ("efectos",))
        self._refrescar_aplicados(None)
        self.multi_opacity.setValue(int(round((p.clips[vis[0]].opacity if vis else 1.0) * 100)))
        self.multi_blend.setCurrentIndex(max(0, self.multi_blend.findData(p.clips[vis[0]].blend if vis else "normal")))
        self.multi_volume.setValue(int(round((p.clips[son[0]].volume if son else 1.0) * 100)))
        self.secciones["varios_video"].setVisible(bool(vis))
        self.secciones["varios_audio"].setVisible(bool(son))
        fxd = clips[0].fx or {}
        for key, spin in self.fx_spins.items():
            spin.setValue(float(fxd.get(key, 0.0)))
        activas = {"efectos", "archivo"} | ({"video"} if vis else set()) | ({"audio"} if son else set())
        self._aplicar_pestanas(activas, self._pestana_para("varios", activas, nuevo))
        self._refrescar_interruptores(clips[0])
        self._refresh_sombra(p.clips[vis[0]] if vis else None)

    def _refresh_archivo(self, c, m, tr):
        self.clip_file.setText(os.path.basename(m.path) if m else ("Texto en pantalla" if c.text is not None else ""))
        self.clip_file.setToolTip(m.path if m else "")
        self.clip_track.setText(tr.name if tr else "")
        self.clip_pos.setText(f"{fmt_time(c.start)} → {fmt_time(c.end)}")
        self.clip_dur.setText(fmt_time(c.duration))
        if m and m.kind == KIND_IMAGE or c.text is not None:
            self.clip_src.setText("imagen fija" if c.text is None else "—")
        else:
            self.clip_src.setText(f"{fmt_time(c.source_in)} → {fmt_time(c.source_in + c.src_len)}")
        self.enabled.setChecked(c.enabled)
        self.locked.setChecked(c.locked)
        if not self.note.hasFocus():
            self.note.setPlainText(c.note)
        editable = not c.locked and not (tr and tr.locked)
        self.enabled.setEnabled(editable)
        self.note.setReadOnly(not editable)
        escena = self._escena_de(c)
        compuesto = bool(self.ctrl.is_compound(c.id)) if hasattr(self.ctrl, "is_compound") else False
        self.btn_editar_escena.setVisible(bool(escena))
        self.btn_deshacer_compuesto.setVisible(compuesto)
        self.secciones["escena"].setVisible(bool(escena) or compuesto)
        for k in ("informacion", "ajustes", "nota"):
            self.secciones[k].setVisible(True)

    def _refresh_clip(self, p, c, nuevo: bool):
        m = p.media_of(c)
        tr = p.track(c.track_id)
        if c.origin == ORIGIN_AI:
            self._cabecera(m.name if m else "¿?", "🟧 Creado por la IA", "#ff9f1c")
        else:
            self._cabecera(m.name if m else "¿?", "Creado por ti")
        self._refresh_archivo(c, m, tr)
        ac = self._aclip() or c
        self.volume.setValue(round(ac.volume * 100))
        editable = not c.locked and not (tr and tr.locked)
        self.volume.setEnabled(editable)
        visual = bool(m and m.kind != "audio") and not (tr and tr.kind == TRACK_AUDIO)
        self._ver_secciones("clip")
        self.frame_box.setVisible(visual)
        self.frame_box.setEnabled(editable)
        has_audio = bool(m and (m.kind == "audio" or m.has_audio))
        if self._audio_id:
            self.clip_track.setText(f"{tr.name if tr else ''}  +  🔗 {p.track(ac.track_id).name}")
        for k in ("transformar", "recorte", "encuadre", "composicion", "seguimiento", "color", "reencuadre"):
            self.secciones[k].setVisible(visual)
        self.secciones["reencuadre"].setVisible(visual and p.height > p.width)
        for k in ("volumen", "ecualizador"):
            self.secciones[k].setVisible(has_audio)
        self._pag["audio"].setEnabled(editable)
        self.crop_box.setEnabled(editable)
        if has_audio:
            self._refresh_audio_tab(ac, m)
        self.track_box.setVisible(visual)
        self.track_box.setEnabled(editable)
        self._refresh_track_box(c, m)
        self._refresh_speed(c, m, editable)
        self._refresh_enhance(c, m, editable)
        self.secciones["mejorar"].setVisible(not self.enhance_box.isHidden())
        self._refresh_reencuadre(c, m, editable)
        self._refresh_color(c, visual, editable)
        self._refresh_blend(c, visual, editable)
        if visual:
            self._refresh_crop(c)
        fxd = c.fx or {}
        for key, spin in self.fx_spins.items():
            spin.setValue(float(fxd.get(key, 0.0)))
            spin.setEnabled(editable)
        for key in ("flash", "shake", "lines", "focus_in"):   # en el audio solo tienen sentido los fundidos
            self._fx_filas[key].setVisible(visual)
        name = next((n for n, lay_ in {**transform.LAYOUTS, **transform.HIDDEN_LAYOUTS}.items()
                     if (c.layout or transform.FULL) == lay_), None)
        for hn in transform.HIDDEN_LAYOUTS:      # los antiguos solo aparecen en el clip que los tiene
            i = self.layout_combo.findText(hn)
            if hn == name and i < 0:
                self.layout_combo.addItem(hn)
            elif hn != name and i >= 0:
                self.layout_combo.removeItem(i)
        self.layout_combo.setCurrentText(name or "Pantalla completa")
        self.btn_unstretch.setVisible((c.layout or {}).get("fit") == "stretch")
        self._refresh_framing()
        self._refrescar_aplicados(c)
        self._refrescar_interruptores(c)
        self._refresh_sombra(c if visual else None, editable)
        activas = {"efectos", "archivo"} | ({"video"} if visual else set()) | ({"audio"} if has_audio else set())
        modo = "clip" if visual else "audio"
        self._modo = modo
        self._aplicar_pestanas(activas, self._pestana_para(modo, activas, nuevo, visual, has_audio))
        self._editable(editable, ("video", "audio", "efectos"))
        self.transform_box.setEnabled(editable)

    def _editable(self, editable: bool, paginas):
        """Un clip bloqueado: sus ●/↺ tampoco se pueden pulsar."""
        for k, s_ in self.secciones.items():
            if any(self._pag[pg].isAncestorOf(s_) for pg in paginas):
                s_.set_editable(editable)

    # ------------------------------------------------------------- cambios
    def _on_res(self, idx):
        if not self._loading:
            _l, w, h = RESOLUTIONS[idx]
            cur = self.ctrl.project.format
            fmt = (cur if cur in ("short", "edit") else "short") if h > w else "youtube"
            pila = self.ctrl.undo_stack
            pila.beginMacro("Resolución del proyecto")      # (formato y tamaño: un solo Ctrl+Z)
            try:
                if fmt != cur:
                    self.ctrl.set_project_format(fmt)
                self.ctrl.set_settings(width=w, height=h)
            finally:
                pila.endMacro()

    def _refresh_speed(self, c, m, editable: bool):
        can = bool(m and m.kind != KIND_IMAGE)
        self.speed_sec.setVisible(can)
        if not can:
            return
        self._colocar_velocidad(bool(m.kind == "audio" or m.has_audio))
        self.speed_box.setEnabled(editable)
        frozen = c.speed <= 0
        self.speed.setValue(100 if frozen else int(round(c.speed * 100)))
        self.reverse.setChecked(c.reverse)
        self.reverse.setEnabled(not frozen)
        self.smooth.setVisible(m.kind == "video" and 0 < c.speed < 0.999)
        self.smooth.setChecked(c.smooth)
        self.ramp.setEnabled(not frozen)
        self.btn_freeze.setVisible(m.kind == "video" and not frozen)
        if frozen:
            self.speed_info.setText(f"❄ Imagen congelada en el segundo {fmt_time(c.source_in)} del archivo. "
                                    "Pon otra velocidad para que vuelva a moverse desde ahí.")
        elif c.retimed:
            way = "hacia atrás, " if c.reverse else ""
            self.speed_info.setText(f"Usa {fmt_time(c.src_len)} del archivo ({way}{c.speed * 100:g} %) → "
                                    f"dura {fmt_time(c.duration)} en el video.")
        else:
            self.speed_info.setText("")

    def _build_enhance_box(self) -> QGroupBox:
        """«🛠 Mejorar imagen»: reducir ruido, estabilizar y detectar cortes de escena."""
        self.enhance_box = QGroupBox("Mejorar imagen")
        f = QFormLayout(self.enhance_box)
        self.denoise = _vd(0, 100, 1, 0, "%", entero=True)
        self.denoise.setSpecialValueText("—")
        self.denoise.setToolTip("Cuánto ruido (grano de la cámara) se quita (— = nada)")
        self.denoise.valueChanged.connect(self._on_denoise)
        f.addRow(_fila("Reducir ruido", self.denoise))
        srow = QHBoxLayout()
        self.stab = QCheckBox("Estabilizar")
        self.stab.setToolTip("Quita el temblor de la cámara. Al activarlo se analiza el movimiento (unos segundos).")
        self.stab.toggled.connect(self._on_stab)
        self.stab_amount = _vd(10, 100, 1, 0, "%", entero=True)
        self.stab_amount.setToolTip("Cuánto se suaviza el movimiento")
        self.stab_amount.valueChanged.connect(self._on_stab_amount)
        srow.addWidget(self.stab)
        srow.addWidget(self.stab_amount, 1)
        f.addRow(srow)
        self.btn_scenes = QPushButton("✂ Detectar cortes de escena…")
        self.btn_scenes.setToolTip("Encuentra cada cambio de plano del clip (tráilers, cinemáticas) para cortar ahí "
                                   "o poner marcadores, como la «Scene Cut Detection» de Resolve.")
        self.btn_scenes.clicked.connect(self._detect_scenes)
        f.addRow(self.btn_scenes)
        self.enhance_info = _dim()
        self.enhance_info.setWordWrap(True)
        self.enhance_info.setText("Se ve al exportar o con «▶ Ver cómo queda» (en Velocidad).")
        f.addRow(self.enhance_info)
        set_help(self.enhance_box, "mejorar")
        return self.enhance_box

    # ------------------------------------------------------------- 🌑 Sombra (21/11, el «Drop Shadow» de Resolve)
    def _build_sombra_box(self) -> QGroupBox:
        """Efectos → «Sombra» del clip (video o imagen): color, fuerza, ángulo, distancia y desenfoque, como el «Drop
        Shadow» de Resolve. Se guarda en fx["shadow"] (core/decor.py) y sigue la forma (el alfa) de la imagen."""
        self.sombra_box = QGroupBox("Sombra")
        f = QFormLayout(self.sombra_box)
        self.sombra_color = QPushButton()
        self.sombra_color.setToolTip("Color de la sombra (negro = la de siempre)")
        D.medida(self.sombra_color, lambda w: w.setFixedSize(D.px(46), D.px(D.ALTO_CAMPO)))
        self.sombra_color.clicked.connect(self._elegir_color_sombra)
        self.sombra_fuerza = _vd(0, 100, 1, 0, "%", entero=True)
        self.sombra_fuerza.setToolTip("Cuánto se ve la sombra (0 % = nada, 100 % = el color entero)")
        self.sombra_angulo = _vd(-180, 180, 1, 0, "°", entero=True)
        self.sombra_angulo.setToolTip("Hacia dónde cae, como una brújula: 0° = arriba, 90° = derecha, 135° = abajo a "
                                      "la derecha, 180° = abajo, −90° = izquierda")
        self.sombra_distancia = _vd(0.0, 5.0, 0.1, 1, "%")
        self.sombra_distancia.setToolTip("Cuánto se separa del clip (en % del lado corto de la pantalla)")
        self.sombra_desenfoque = _vd(0.0, 10.0, 0.1, 1, "%")
        self.sombra_desenfoque.setToolTip("Lo suave que es su borde (en % del lado corto de la pantalla)")
        for campo, w_ in (("opacity", self.sombra_fuerza), ("angle", self.sombra_angulo),
                          ("distance", self.sombra_distancia), ("blur", self.sombra_desenfoque)):
            w_.valueChanged.connect(lambda v, k=campo: self._on_sombra(k, v))
        self._sombra_filas = [_fila("Color", self.sombra_color), _fila("Fuerza", self.sombra_fuerza),
                              _fila("Ángulo", self.sombra_angulo), _fila("Distancia", self.sombra_distancia),
                              _fila("Desenfoque", self.sombra_desenfoque)]
        for fila in self._sombra_filas:
            f.addRow(fila)
        fila_b = QWidget()
        hb = QHBoxLayout(fila_b)
        hb.setContentsMargins(0, 0, 0, 0)
        self.btn_sombra_poner = QPushButton("Poner sombra")
        self.btn_sombra_poner.setIcon(D.icono("sombra"))
        self.btn_sombra_poner.setToolTip("Una sombra pequeña y suave detrás del clip para darle profundidad (sigue la "
                                         "forma de un PNG recortado). Ctrl+Z la quita")
        self.btn_sombra_poner.clicked.connect(lambda: self.poner_sombra())
        self.btn_sombra_quitar = QPushButton("Quitar")
        self.btn_sombra_quitar.setIcon(D.icono("trash-2"))
        self.btn_sombra_quitar.setToolTip("Quita la sombra del clip (Ctrl+Z la devuelve)")
        self.btn_sombra_quitar.clicked.connect(lambda: QTimer.singleShot(0, self.quitar_sombra))
        hb.addWidget(self.btn_sombra_poner)
        hb.addStretch(1)
        hb.addWidget(self.btn_sombra_quitar)
        f.addRow(fila_b)
        return self.sombra_box

    def _sombra_clips(self) -> list:
        """Los clips elegidos que pueden llevar sombra (de video o imagen, no textos ni audio)."""
        p = self.ctrl.project
        out = []
        for cid in self._visuales():
            c = p.clips.get(cid)
            m = p.media_of(c) if c is not None else None
            if c is not None and c.text is None and m is not None and m.kind in ("video", KIND_IMAGE):
                out.append(c)
        return out

    @staticmethod
    def _sombra_de(c) -> dict | None:
        """La sombra del clip (o la guardada al apagarla con ●), con todos sus valores."""
        from ..core import decor
        from . import inspector_secciones as SEC
        sh = decor.shadow_of(c.fx)
        if sh is None and SEC.apagada(c, "sombra"):
            sh = decor.shadow_of(((c.fx or {})[SEC.APAGADO]["sombra"] or {}).get("fx") or {})
        return sh

    def _refresh_sombra(self, c, editable: bool = True):
        """La sección «Sombra»: a la vista con un clip de video o imagen; sin sombra, solo «Poner sombra» (sin huecos)."""
        from ..core import decor
        s_ = self.secciones.get("sombra")
        if s_ is None:
            return
        clips = self._sombra_clips()
        if c is None or not clips:
            s_.setVisible(False)
            return
        c = next((x for x in clips if x.id == c.id), clips[0])
        s_.setVisible(True)
        sh = self._sombra_de(c)
        hay = sh is not None
        for fila in self._sombra_filas:
            fila.setVisible(hay)
        self.btn_sombra_poner.setVisible(not hay)
        self.btn_sombra_quitar.setVisible(hay)
        v = sh or decor.shadow_of({"shadow": dict(decor.SOMBRA_EFECTO)})
        self.sombra_fuerza.setValue(int(round(float(v["opacity"]) * 100)))
        self.sombra_angulo.setValue(int(round(float(v["angle"]))))
        self.sombra_distancia.setValue(round(float(v["distance"]) * 100, 1))
        self.sombra_desenfoque.setValue(round(float(v["blur"]) * 100, 1))
        self.sombra_color.setStyleSheet(f"background:{v['color']}; border:1px solid #666;")
        self._sombra_color_ahora = v["color"]
        from . import inspector_secciones as SEC
        s_.body.setEnabled(bool(editable) and not SEC.apagada(c, "sombra"))   # (sin sombra: «Poner sombra» a mano)

    def _on_sombra(self, campo: str, valor):
        """Un control de la sombra cambió: a todos los clips elegidos que la llevan (un paso; arrastrar = uno solo)."""
        if self._loading or not self._ids:
            return
        if campo == "color":
            v = valor
        else:
            v = float(valor) / (100.0 if campo in ("opacity", "distance", "blur") else 1.0)
        nombres = {"opacity": "fuerza", "angle": "ángulo", "distance": "distancia", "blur": "desenfoque",
                   "color": "color"}
        self._cambiar_sombra({campo: v}, f"Sombra: {nombres[campo]}")

    def _cambiar_sombra(self, cambios: dict, texto: str):
        from ..core import decor
        changes = {}
        for c in self._sombra_clips():
            sh = decor.shadow_of(c.fx)
            if sh is None:
                continue
            sh.update(cambios)
            fx = dict(c.fx or {})
            fx["shadow"] = decor.sombra(sh["opacity"], sh["angle"], sh["distance"], sh["blur"], sh["color"])
            changes[c.id] = {"fx": fx}
        if changes:
            self.ctrl.batch_clip_props(changes, texto)

    def _elegir_color_sombra(self):
        from PySide6.QtGui import QColor
        from .common import pick_color
        col = pick_color(QColor(getattr(self, "_sombra_color_ahora", "#000000")), self, "Color de la sombra")
        if col.isValid():
            self.poner_color_sombra(col.name())

    def poner_color_sombra(self, color: str):
        """El color de la sombra de los clips elegidos (un Ctrl+Z)."""
        from ..core import decor
        self._on_sombra("color", decor.color_sombra(color))

    def poner_sombra(self, ids: list[str] | None = None, texto: str = "Sombra") -> int:
        """🌑 Pone la sombra de fábrica (pequeña y sutil, decor.SOMBRA_EFECTO) a los clips de video o imagen dados (o a
        los elegidos) que no la tienen, en UN paso de Ctrl+Z. Devuelve cuántos."""
        from ..core import decor
        from . import inspector_secciones as SEC
        p = self.ctrl.project
        if ids is None:
            clips = self._sombra_clips()
        else:
            clips = []
            for cid in ids:
                c = p.clips.get(cid)
                m = p.media_of(c) if c is not None else None
                tr = p.track(c.track_id) if c is not None else None
                if (c is not None and c.text is None and m is not None and m.kind in ("video", KIND_IMAGE)
                        and not (tr is not None and tr.kind == TRACK_AUDIO)):
                    clips.append(c)
        changes = {}
        for c in clips:
            if decor.shadow_of(c.fx) is not None:
                continue
            fx = SEC._fx_sin_apagado(dict(c.fx or {}), "sombra")
            fx["shadow"] = decor.sombra(**decor.SOMBRA_EFECTO)
            changes[c.id] = {"fx": fx}
        return self.ctrl.batch_clip_props(changes, texto) if changes else 0

    def quitar_sombra(self):
        """Quita la sombra (también la apagada) de los clips elegidos, en un paso de Ctrl+Z."""
        from . import inspector_secciones as SEC
        changes = {}
        for c in self._sombra_clips():
            fx = dict(c.fx or {})
            if "shadow" not in fx and not SEC.apagada(c, "sombra"):
                continue
            fx.pop("shadow", None)
            fx = SEC._fx_sin_apagado(fx, "sombra")
            changes[c.id] = {"fx": fx or None}
        if changes:
            self.ctrl.batch_clip_props(changes, "Quitar sombra")

    def _fx_now(self) -> dict:
        c = self._clip()
        return dict((c.fx if c else None) or {})

    def _on_denoise(self, v: int):
        if self._loading or not self._ids:
            return
        fx = self._fx_now()
        if v:
            fx["denoise"] = v / 100
        else:
            fx.pop("denoise", None)
        self.ctrl.set_clip_props(self._ids, "Reducir ruido", fx=fx or None)

    def _on_stab(self, on: bool):
        if self._loading or not self._ids:
            return
        c = self._clip()
        fx = self._fx_now()
        if not on:
            fx.pop("stab", None)
            self.ctrl.set_clip_props([c.id], "Quitar estabilización", fx=fx or None)
            return
        from ..core import enhance
        from .jobs import BackgroundJob
        m = self.ctrl.project.media_of(c)
        cid, path, a, d = c.id, m.path, c.source_in, c.src_len
        amount = self.stab_amount.value() / 100
        self.enhance_info.setText("Analizando cómo tiembla la imagen…")
        self.stab.setEnabled(False)
        self._stab_job = BackgroundJob(lambda prog, canc: enhance.analyze_stab(path, a, d, prog, canc), self)

        def done(trf):
            self._stab_job = None
            self.stab.setEnabled(True)
            cc = self.ctrl.project.clips.get(cid)
            if cc is None:
                return
            ffx = dict(cc.fx or {})
            ffx["stab"] = {"amount": amount, "trf": trf, "src": [a, d]}
            self.ctrl.set_clip_props([cid], "Estabilizar", fx=ffx)
            self.enhance_info.setText("✓ Estabilizado: se aplica al exportar (y en «▶ Ver cómo queda»).")

        def failed(msg):
            self._stab_job = None
            self.stab.setEnabled(True)
            self.enhance_info.setText("✗ " + msg)
            self._loading = True
            self.stab.setChecked(False)
            self._loading = False
        self._stab_job.done.connect(done)
        self._stab_job.failed.connect(failed)
        self._stab_job.start()

    def _on_stab_amount(self, v: int):
        if self._loading or not self._ids:
            return
        fx = self._fx_now()
        if isinstance(fx.get("stab"), dict):
            fx["stab"] = dict(fx["stab"], amount=v / 100)
            self.ctrl.set_clip_props(self._ids, "Cuánto estabilizar", fx=fx)

    def _detect_scenes(self):
        from PySide6.QtWidgets import QMessageBox
        from ..core import enhance
        from .jobs import BackgroundJob
        c = self._clip()
        if c is None or getattr(self, "_scene_job", None) is not None:
            return
        m = self.ctrl.project.media_of(c)
        cid, path, a, d = c.id, m.path, c.source_in, c.src_len
        self.btn_scenes.setEnabled(False)
        self.btn_scenes.setText("Buscando cambios de plano…")
        self._scene_job = BackgroundJob(lambda _p, canc: enhance.scene_cuts(path, a, d, cancelled=canc), self)

        def done(cuts):
            self._scene_job = None
            self.btn_scenes.setEnabled(True)
            self.btn_scenes.setText("✂ Detectar cortes de escena…")
            cc = self.ctrl.project.clips.get(cid)
            if cc is None:
                return
            from ..core import mapping
            times = [t for s in cuts if (t := mapping.map_time(self.ctrl.project, cc.media_id, s, [cc])) is not None]
            if not times:
                self.enhance_info.setText("No encontré cambios de plano en este clip.")
                return
            box = QMessageBox(self)
            box.setWindowTitle("Cortes de escena")
            box.setText(f"Encontré {len(times)} cambios de plano en este clip.")
            b_cut = box.addButton("✂ Cortar ahí", QMessageBox.AcceptRole)
            b_mark = box.addButton("⚑ Poner marcadores", QMessageBox.ActionRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            self._scene_box = box
            box.exec()
            if box.clickedButton() is b_cut:
                self.ctrl.split_at_times(cid, times)
            elif box.clickedButton() is b_mark:
                self.ctrl.add_markers(times)

        def failed(msg):
            self._scene_job = None
            self.btn_scenes.setEnabled(True)
            self.btn_scenes.setText("✂ Detectar cortes de escena…")
            self.enhance_info.setText("✗ " + msg)
        self._scene_job.done.connect(done)
        self._scene_job.failed.connect(failed)
        self._scene_job.start()

    def _refresh_enhance(self, c, m, editable: bool):
        vis = bool(m and m.kind in ("video", "image")) and self.ctrl.project.track(c.track_id).kind != TRACK_AUDIO
        self.enhance_box.setVisible(vis)
        if not vis:
            return
        self.enhance_box.setEnabled(editable)
        fx = c.fx or {}
        v = int(round(float(fx.get("denoise", 0) or 0) * 100))
        self.denoise.setValue(v)
        st = fx.get("stab") if isinstance(fx.get("stab"), dict) else None
        video = m.kind == "video" and c.speed > 0
        self.stab.setVisible(video)
        self.stab_amount.setVisible(video)
        self.btn_scenes.setVisible(video)
        self.stab.setChecked(bool(st))
        self.stab_amount.setEnabled(bool(st))
        self.stab_amount.setValue(int(round(float(st["amount"]) * 100)) if st else 50)

    def _on_ramp(self, i: int):
        key = self.ramp.itemData(i)
        self.ramp.setCurrentIndex(0)
        if key and self._ids:
            created = self.ctrl.speed_ramp(self._ids[0], key, ripple=self.ripple_speed.isChecked())
            if isinstance(created, list):
                self.ramp_done.emit(created)

    def _view_here(self):
        from .jobs import BackgroundJob
        from .transition_preview import TransitionPreview, render_cut
        if getattr(self, "_view_job", None) is not None:
            return
        p, t = self.ctrl.project, self.engine.time
        self.btn_view_speed.setEnabled(False)
        self.btn_view_speed.setText("Preparando…")
        self._view_job = BackgroundJob(lambda _p, _c: render_cut(p, t), self)

        def end(path=None, msg=None):
            self._view_job = None
            self.btn_view_speed.setEnabled(True)
            self.btn_view_speed.setText("▶ Ver cómo queda")
            if path:
                from .herramientas import abrir_dialogo
                self.window().herramientas.cerrar("ver_como_queda", por_usuario=False) if hasattr(
                    self.window(), "herramientas") else None
                self._view_dialog = abrir_dialogo(self, "ver_como_queda",
                                                  lambda: TransitionPreview(path, "Cómo queda", self.window()),
                                                  "Cómo queda", "Cómo queda", "film")
        self._view_job.done.connect(lambda path: end(path))
        self._view_job.failed.connect(lambda m: end(msg=m))
        self._view_job.start()

    def _on_speed(self, speed: float | None = None, reverse: bool | None = None):
        if self._loading or not self._ids:
            return
        ids = self._targets()
        self.ctrl.set_speed(ids, speed=speed, reverse=reverse, ripple=self.ripple_speed.isChecked())

    def focus_speed(self):
        """Tecla R: lleva a la velocidad del clip seleccionado (abre su sección)."""
        if self.speed_sec.isHidden():                    # (oculta a propósito = imagen; en otra pestaña no cuenta)
            self.ctrl.message.emit("🐢 La velocidad es para videos y audios (no para imágenes).")
            return
        self.ir_a("audio" if getattr(self, "_vel_en", None) is getattr(self, "_audio_lay", 0) else "video")
        self.speed_sec.head.blockSignals(True)            # (se abre ahora, sin quedar recordada como abierta)
        self.speed_sec.set_open(True, save=False)
        self.speed_sec.head.blockSignals(False)
        if self.speed_sec.isVisible():
            self.speed.setFocus()
            self.speed.selectAll()

    def _on_fx(self, key: str, value: float):
        if self._loading or not self._ids:
            return
        names = {"flash": "Destello", "fade_in": "Fundido de entrada", "fade_out": "Fundido de salida",
                 "shake": "Temblor", "lines": "Destello de líneas", "focus_in": "Entrar enfocando"}
        p = self.ctrl.project
        for cid in self._ids:
            c = p.clips.get(cid)
            if c is None:
                continue
            fx = dict(c.fx or {})
            if value > 0:
                fx[key] = round(value, 3)
            else:
                fx.pop(key, None)
            self.ctrl.set_clip_props([cid], names[key], fx=fx or None)

    def _on_format(self, _idx):
        if not self._loading:
            self.ctrl.set_project_format(self.format_combo.currentData())

    def _on_fps(self, idx):
        if not self._loading:
            self.ctrl.set_settings(fps=FPS_OPTIONS[idx])

    def _on_volume(self, v):
        if not self._loading and self._ids:
            ac = self._aclip()
            self.ctrl.set_clip_props([ac.id] if ac is not None else self._ids, "Cambiar volumen", volume=v / 100)

    def _on_enabled(self, on):
        if not self._loading and self._ids:
            self.ctrl.set_clip_props(self._targets(), "Activar/desactivar clip", enabled=on)

    def _on_locked(self, on):
        if not self._loading and self._ids:
            self.ctrl.set_clip_props(self._targets(), "Bloquear clip" if on else "Desbloquear clip", locked=on)

    # ------------------------------------------------------------ encuadre
    # ------------------------------------------------------------ 〰 curvas de movimiento
    def _curve_combo(self, which: str) -> QComboBox:
        cb = QComboBox()
        for kind, name in transform.CURVES.items():
            cb.addItem(name, kind)
        cb.setToolTip("〰 Cómo se mueve entre la clave anterior al cabezal y la siguiente: suave, acelerando, "
                      "frenando al llegar, a velocidad fija, con rebote o saltando de golpe. Se ve igual al "
                      "exportar. Ctrl+Z lo deshace. (El zoom nunca baja de 100 %: al volver a 100 % no rebota.)")
        cb.setEnabled(False)
        cb.activated.connect(lambda _i, w=which, b=cb: self._set_curve(w, b.currentData()))
        return cb

    def _layout_s(self, c) -> float:
        m = self.ctrl.project.media_of(c)
        local = self._now() - c.start
        return local if (m is not None and m.kind == "image") else self.ctrl.clip_source_time(c.id, self._now())

    def _show_curve(self, cb: QComboBox, kf: list, s: float):
        cb.blockSignals(True)
        cb.setEnabled(len(kf) >= 2)
        kind = None
        if len(kf) >= 2:
            pts = sorted(kf, key=lambda k: k["t"])
            prev = [k for k in pts[:-1] if k["t"] <= s + 1e-3]
            kind = (prev[-1] if prev else pts[0]).get("i")
        i = cb.findData(kind)
        cb.setCurrentIndex(max(0, i))
        cb.blockSignals(False)

    def _set_curve(self, which: str, kind):
        c = self._clip()
        if c is None or self._loading:
            return
        s = self.ctrl.clip_source_time(c.id, self._now()) if which == "zoom" else self._layout_s(c)
        self.ctrl.set_kf_curve(c.id, which, s, kind)

    def _clip(self):
        if len(self._ids) != 1:
            return None
        return self.ctrl.project.clips.get(self._ids[0])

    def _now(self) -> float:
        return self.engine.time if self.engine is not None else 0.0

    def _refresh_framing(self):
        c = self._clip()
        if hasattr(self, "transform_box"):
            self.transform_box.refresh()
        if c is None or self.frame_box.isHidden():
            return
        was = self._loading
        self._loading = True
        try:
            src = self.ctrl.clip_source_time(c.id, self._now())
            z, x, y = transform.value_at(c.zoom_kf, src)
            self.zoom.setValue(round(z * 100))
            self.fx.setValue(round(x * 100))
            self.fy.setValue(round(y * 100))
            n = len(c.zoom_kf)
            on_kf = any(abs(k["t"] - src) <= 0.05 for k in c.zoom_kf)
            self.kf_label.setText("Sin zoom" if not transform.is_zoomed(c.zoom_kf) and n <= 1 else
                                  "Zoom fijo" if n == 1 else
                                  f"Animado: {n} claves" + (" · clave aquí" if on_kf else ""))
            self.btn_del_kf.setEnabled(on_kf and n >= 2)
            self.btn_prev_kf.setEnabled(n >= 2)
            self.btn_next_kf.setEnabled(n >= 2)
            # 🎞 posición y tamaño
            times = self.ctrl.layout_key_times(c.id)
            nl = len(c.layout_kf)
            here = any(abs(t - self._now()) <= 0.05 for t in times)
            self.lk_label.setText("Quieto" if not nl else       # (la explicación, en su tooltip)
                                  f"Animado: {nl} clave{'s' if nl != 1 else ''}" + (" · clave aquí" if here else ""))
            self.lk_label.setToolTip("Pulsa «Clave» para animar la posición y el tamaño" if not nl else "")
            self.btn_del_lk.setEnabled(here)
            self.btn_prev_lk.setEnabled(bool(times))
            self.btn_next_lk.setEnabled(bool(times))
            self.btn_clear_lk.setEnabled(bool(nl))
            self._show_curve(self.curve_zoom, c.zoom_kf, src)
            self._show_curve(self.curve_lk, c.layout_kf or [], self._layout_s(c))
        finally:
            self._loading = was

    def _on_framing(self):
        c = self._clip()
        if self._loading or c is None:
            return
        self.ctrl.set_zoom_at(c.id, self._now(), self.zoom.value() / 100, self.fx.value() / 100,
                              self.fy.value() / 100)

    def nudge_framing(self, dx: float, dy: float, zoom_steps: float = 0.0):
        """Encuadre desde el visor: arrastrar (dx, dy en fracción de pantalla) o rueda (pasos)."""
        c = self._clip()
        if c is None:
            return
        m = self.ctrl.project.media_of(c)
        if m is None or m.kind == "audio":
            return
        src = self.ctrl.clip_source_time(c.id, self._now())
        z, x, y = transform.value_at(c.zoom_kf, src)
        box = c.layout or transform.FULL
        if zoom_steps:
            z = min(max(z * (1.12 ** zoom_steps), 1.0), transform.MAX_ZOOM)
        if z > 1.0:
            x -= dx / box["w"] / z
            y -= dy / box["h"] / z
        self.ctrl.set_zoom_at(c.id, self._now(), z, x, y)

    def _add_kf(self):
        c = self._clip()
        if c is not None:
            self.ctrl.add_zoom_keyframe(c.id, self._now())
        else:
            self.ctrl.message.emit("Elige antes un clip en la línea de tiempo para ponerle un fotograma clave.")

    def _del_kf(self):
        c = self._clip()
        if c is not None:
            self.ctrl.remove_zoom_keyframe(c.id, self.ctrl.clip_source_time(c.id, self._now()))

    def _jump_kf(self, direction: int):
        c = self._clip()
        if c is None or self.engine is None or not c.zoom_kf:
            if self.engine is not None:
                self.ctrl.message.emit("Este clip aún no tiene fotogramas clave de zoom: ponle uno con ◆."
                                       if c is not None else "Elige antes un clip en la línea de tiempo.")
            return
        m = self.ctrl.project.media_of(c)
        offset = c.start - (0.0 if (m and m.kind == "image") else c.source_in)
        times = sorted(k["t"] + offset for k in c.zoom_kf)
        now = self._now()
        target = [t for t in times if t > now + 0.02] if direction > 0 else [t for t in times if t < now - 0.02]
        if target:
            self.engine.user_seek(target[0] if direction > 0 else target[-1])

    def _jump_lk(self, direction: int):
        c = self._clip()
        if c is None or self.engine is None:
            return
        times = self.ctrl.layout_key_times(c.id)
        now = self._now()
        target = [t for t in times if t > now + 0.02] if direction > 0 else [t for t in times if t < now - 0.02]
        if target:
            self.engine.user_seek(target[0] if direction > 0 else target[-1])

    def _on_layout(self, name: str):
        c = self._clip()
        layouts = {**transform.LAYOUTS, **transform.HIDDEN_LAYOUTS}
        if self._loading or c is None or name not in layouts:
            return
        layout = layouts[name]
        self.ctrl.set_layout([c.id], None if layout == transform.FULL else layout)

    def _unstretch(self):
        c = self._clip()
        if c is not None and (c.layout or {}).get("fit") == "stretch":
            self.ctrl.set_layout([c.id], dict(c.layout, fit="contain", bg="none"))

    def _on_note(self):
        if self._ids:
            self.ctrl.set_clip_props(self._ids, "Editar nota", note=self.note.toPlainText().strip())


class _PaginaCompat:
    """(lo de antes) inspector.stack.currentIndex(): 0 proyecto · 1 clip · 2 varios · 3 texto · 4 transición."""

    def __init__(self, ins):
        self.ins = ins

    def currentIndex(self) -> int:
        return {"proyecto": 0, "clip": 1, "audio": 1, "varios": 2, "texto": 3, "transicion": 4}.get(self.ins._modo, 0)


def _glifo(ch: str):
    """Icono monocromo (del tema) para un símbolo."""
    try:
        from .theme import glyph_icon
        return glyph_icon(ch, 16)
    except Exception:  # noqa: BLE001
        from PySide6.QtGui import QIcon
        return QIcon()
