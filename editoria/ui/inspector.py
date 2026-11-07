"""Panel derecho: propiedades del clip seleccionado / ajustes del proyecto, y pestaña de IA."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QInputDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QSlider,
                               QTabWidget, QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

import json

import numpy as np

from ..core import equalizer as E
from ..core import media as media_tools
from ..core import transform
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
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_project_page())
        self.stack.addWidget(self._build_clip_page())
        self.stack.addWidget(self._build_multi_page())
        self.stack.addWidget(self._build_text_page())
        self.eq_graph.installEventFilter(self)      # al mostrarse la gráfica del ecualizador, se calcula su espectro

        # Con scroll: así el panel nunca empuja ni aplasta la timeline
        scroll = QScrollArea()
        scroll.setWidget(self.stack)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 0, 6)
        lay.addWidget(scroll)
        ctrl.project_changed.connect(self._refresh)
        ctrl.media_changed.connect(self._refresh)
        if engine is not None:
            engine.time_changed.connect(lambda _t: self._refresh_framing())
            engine.time_changed.connect(lambda _t: (not engine.playing and self.eq_graph.isVisible()
                                                    and self._clip() is not None and self._spectrum_timer.start()))
        self._refresh()

    # -------------------------------------------------------------- páginas
    def _build_project_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        set_help(w, "proyecto")
        title = QLabel("Proyecto")
        title.setObjectName("title")
        self.project_name = _dim()
        form = QFormLayout()
        self.format_combo = QComboBox()
        for key, (label, _w, _h) in FORMATS.items():
            self.format_combo.addItem(label, key)
        self.format_combo.currentIndexChanged.connect(self._on_format)
        form.addRow("Tipo", self.format_combo)
        self.res_combo = QComboBox()
        for label, _w, _h in RESOLUTIONS:
            self.res_combo.addItem(label)
        self.fps_combo = QComboBox()
        for f in FPS_OPTIONS:
            self.fps_combo.addItem(f"{f:g} fps")
        form.addRow("Resolución", self.res_combo)
        form.addRow("Fotogramas", self.fps_combo)
        self.res_combo.currentIndexChanged.connect(self._on_res)
        self.fps_combo.currentIndexChanged.connect(self._on_fps)
        self.project_stats = _dim()
        lay.addWidget(title)
        lay.addWidget(self.project_name)
        lay.addLayout(form)
        lay.addWidget(self.project_stats)
        lay.addStretch()
        return w

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
        self.volume = QSpinBox()
        self.volume.setRange(0, 200)
        self.volume.setSuffix(" %")
        self.volume.setKeyboardTracking(False)
        self.volume.valueChanged.connect(self._on_volume)
        self.enabled = QCheckBox("Activo (se ve y se oye)")
        self.enabled.toggled.connect(self._on_enabled)
        self.locked = QCheckBox("🔒 Bloqueado")
        self.locked.setToolTip("Nadie, ni la IA, podrá modificar este clip hasta que lo desbloquees.")
        self.locked.toggled.connect(self._on_locked)
        pform.addRow(self.enabled)
        pform.addRow(self.locked)

        # --- Velocidad (como «Cambiar velocidad del clip» de Resolve, tecla R) ---
        self.speed_box = QGroupBox("Velocidad")
        sl = QVBoxLayout(self.speed_box)
        row = QHBoxLayout()
        self.speed = QSpinBox()
        self.speed.setRange(10, 400)
        self.speed.setSingleStep(5)
        self.speed.setSuffix(" %")
        self.speed.setKeyboardTracking(False)
        self.speed.setFixedWidth(78)
        self.speed.setToolTip("100 % = normal · 50 % = cámara lenta · 200 % = el doble de rápido.\n"
                              "El clip se alarga o se acorta; su sonido vinculado también (sin voz de ardilla).")
        self.speed.valueChanged.connect(lambda v: self._on_speed(speed=v / 100))
        row.addWidget(self.speed)
        for pct in (25, 50, 100, 200, 400):
            b = QPushButton(f"{pct}%")
            b.setFixedWidth(44)
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
        self.smooth = QCheckBox("✨ Cámara lenta suave (inventa fotogramas; exportar tarda más)")
        self.smooth.setToolTip("Como el Speed Warp de Resolve: al exportar, los fotogramas que faltan se crean "
                               "analizando el movimiento. Solo por debajo del 100 %.")
        self.smooth.toggled.connect(lambda on: self._loading or (self._ids and self.ctrl.set_clip_props(
            self._targets(), "Cámara lenta suave", smooth=on)))
        sl.addWidget(self.smooth)
        rr = QHBoxLayout()
        self.ramp = QComboBox()
        self.ramp.addItem("📈 Rampa de velocidad…", "")
        for key, (name, _f) in self.ctrl.RAMPS.items():
            self.ramp.addItem(name, key)
        self.ramp.setToolTip("Divide el clip en tramos que cambian de velocidad poco a poco (típico de los edits).")
        self.ramp.activated.connect(self._on_ramp)
        self.btn_view_speed = QPushButton("▶ Ver cómo queda")
        self.btn_view_speed.setToolTip("Prepara unos segundos alrededor del cabezal tal como saldrán al exportar.")
        self.btn_view_speed.clicked.connect(self._view_here)
        rr.addWidget(self.ramp, 1)
        rr.addWidget(self.btn_view_speed)
        sl.addLayout(rr)
        self.btn_freeze = QPushButton("❄ Congelar la imagen desde el cabezal (Mayús+R)")
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
        self.zoom = QSpinBox()
        self.zoom.setRange(100, 600)
        self.zoom.setSingleStep(10)
        self.zoom.setSuffix(" %")
        self.zoom.setKeyboardTracking(False)
        self.fx = QSpinBox()
        self.fx.setRange(0, 100)
        self.fx.setSuffix(" %")
        self.fx.setKeyboardTracking(False)
        self.fy = QSpinBox()
        self.fy.setRange(0, 100)
        self.fy.setSuffix(" %")
        self.fy.setKeyboardTracking(False)
        for spin in (self.zoom, self.fx, self.fy):
            spin.valueChanged.connect(self._on_framing)
        center = QHBoxLayout()
        center.addWidget(QLabel("X"))
        center.addWidget(self.fx)
        center.addWidget(QLabel("Y"))
        center.addWidget(self.fy)
        self.kf_label = QLabel()
        self.kf_label.setObjectName("dim")
        kb = QHBoxLayout()
        self.btn_prev_kf = QPushButton("◀")
        self.btn_prev_kf.setToolTip("Ir al fotograma clave anterior")
        self.btn_add_kf = QPushButton("◆ Clave aquí")
        self.btn_add_kf.setToolTip("Añade un fotograma clave en el cabezal: el zoom se animará "
                                   "suavemente entre las claves.")
        self.btn_del_kf = QPushButton("✕ Clave")
        self.btn_del_kf.setToolTip("Quita el fotograma clave que está justo en el cabezal")
        self.btn_next_kf = QPushButton("▶")
        self.btn_next_kf.setToolTip("Ir al fotograma clave siguiente")
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
        fl.addRow("Zoom", self.zoom)
        fl.addRow("Centro", center)
        fl.addRow(kb)
        fl.addRow(self.kf_label, self.btn_reset_zoom)
        lay_row = QHBoxLayout()
        lay_row.addWidget(self.layout_combo, 1)
        self.btn_unstretch = QPushButton("Sin deformar")
        self.btn_unstretch.setToolTip("La imagen está estirada o aplastada (asas a media arista del visor). "
                                      "Esto le devuelve su proporción original, en la misma caja.")
        self.btn_unstretch.clicked.connect(self._unstretch)
        self.btn_unstretch.hide()
        lay_row.addWidget(self.btn_unstretch)
        fl.addRow("En pantalla", lay_row)
        # 🎞 Posición y tamaño animados (como los fotogramas clave de «Transformar» en Resolve)
        lk = QHBoxLayout()
        self.btn_prev_lk = QPushButton("◀")
        self.btn_prev_lk.setToolTip("Ir a la clave de posición/tamaño anterior")
        self.btn_add_lk = QPushButton("◆ Clave")
        self.btn_add_lk.setToolTip("Fotograma clave de POSICIÓN Y TAMAÑO en el cabezal (la primera activa la "
                                   "animación). Después mueve el cabezal y arrastra o escala la capa en el visor: "
                                   "cada cambio crea la clave de ese momento. Entre claves, movimiento suave.")
        self.btn_del_lk = QPushButton("✕ Clave")
        self.btn_del_lk.setToolTip("Quita la clave de posición/tamaño que está justo en el cabezal")
        self.btn_next_lk = QPushButton("▶")
        self.btn_next_lk.setToolTip("Ir a la clave de posición/tamaño siguiente")
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
        self.lk_label = QLabel()
        self.lk_label.setObjectName("dim")
        fl.addRow("Posición y tamaño", lk)
        fl.addRow(self.lk_label, self.btn_clear_lk)
        self.btn_track = QPushButton("🎯 Seguir personaje u objeto…")
        self.btn_track.setToolTip("Marca algo en el fotograma y la IA crea un zoom que lo sigue.")
        self.btn_track.clicked.connect(lambda: self._ids and self.track_requested.emit(self._ids[0]))
        fl.addRow(self.btn_track)

        # --- Efectos (edits): destello, fundidos y temblor ---
        self.effects_box = QGroupBox("Efectos")
        ef = QFormLayout(self.effects_box)
        self.fx_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (("flash", "Destello"), ("fade_in", "Fundido de entrada"),
                           ("fade_out", "Fundido de salida"), ("shake", "Temblor")):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 5.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setSuffix(" s")
            spin.setSpecialValueText("—")
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, k=key: self._on_fx(k, v))
            self.fx_spins[key] = spin
            ef.addRow(label, spin)
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

        lay.addWidget(self.clip_title)
        lay.addWidget(self.clip_origin)
        self.clip_tabs = QTabWidget()
        tab_clip = QWidget()
        tl = QVBoxLayout(tab_clip)
        tl.setContentsMargins(0, 6, 0, 0)
        tl.addWidget(info)
        tl.addWidget(props)
        tl.addWidget(self.speed_box)
        tl.addWidget(self._build_enhance_box())
        tl.addWidget(self.effects_box)
        tl.addWidget(note_box)
        tl.addStretch()
        tab_video = QWidget()
        tv = QVBoxLayout(tab_video)
        tv.setContentsMargins(0, 6, 0, 0)
        from .transform_box import TransformBox
        self.transform_box = TransformBox(self)       # ⤧ Tamaño, posición, rotación, voltear y relleno, a la mano
        tv.addWidget(self.transform_box)
        tv.addWidget(self.frame_box)
        from ..core.curves import BLEND_MODES
        self.blend_box = QGroupBox("Opacidad y modo de fusión")
        bf = QFormLayout(self.blend_box)
        orow = QHBoxLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity_val = QLabel("100 %")
        self.opacity_val.setFixedWidth(46)
        self.opacity.valueChanged.connect(self._on_opacity)
        orow.addWidget(self.opacity, 1)
        orow.addWidget(self.opacity_val)
        bf.addRow("Opacidad", orow)
        self.blend_combo = QComboBox()
        for key, name, _f, _q in BLEND_MODES:
            self.blend_combo.addItem(name, key)
        self.blend_combo.currentIndexChanged.connect(self._on_blend)
        bf.addRow("Fusión", self.blend_combo)
        self.op_kf_info = _dim()
        self.op_kf_info.setWordWrap(True)
        bf.addRow(self.op_kf_info)
        set_help(self.blend_box, "fusion")
        tv.addWidget(self.blend_box)
        tv.addStretch()
        set_help(tab_clip, "clip")
        set_help(self.frame_box, "encuadre")
        self.clip_tabs.addTab(tab_clip, "Clip")
        self.clip_tabs.addTab(tab_video, "Video")
        self.clip_tabs.addTab(self._build_audio_tab(), "Audio")
        self.clip_tabs.addTab(self._build_color_tab(), "Color")
        self.clip_tabs.currentChanged.connect(lambda i: setattr(self, "_last_tab", i))
        self._last_tab = 0
        lay.addWidget(self.clip_tabs)
        lay.addStretch()
        return w

    def _build_color_tab(self) -> QWidget:
        """Pestaña «Color» (como la página Color de Resolve, en sencillo). Se ve igual en el visor y al exportar."""
        from ..core import color as C
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        self.color_box = QGroupBox("Corrección de color")
        form = QFormLayout(self.color_box)
        self.color_sliders: dict[str, QSlider] = {}
        self.color_values: dict[str, QLabel] = {}
        for k in C.KEYS:
            row = QHBoxLayout()
            sl = QSlider(Qt.Horizontal)
            lo, hi = C.RANGES.get(k, (-1.0, 1.0))
            sl.setRange(int(lo * 100), int(hi * 100))
            sl.setSingleStep(2)
            sl.setPageStep(10)
            val = QLabel("0")
            val.setFixedWidth(42)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sl.valueChanged.connect(lambda v, kk=k: self._on_color_slider(kk, v))
            sl.setToolTip("Doble clic en el número = volver a 0")
            row.addWidget(sl, 1)
            row.addWidget(val)
            self.color_sliders[k], self.color_values[k] = sl, val
            form.addRow(C.LABELS[k], row)
        lr = QHBoxLayout()
        self.btn_lut = QPushButton("🎨 Cargar LUT (.cube)…")
        self.btn_lut.setToolTip("Un «look» de color en formato .cube (los de Resolve, Premiere, cámaras…)")
        self.btn_lut.clicked.connect(self._choose_lut)
        self.lut_name = _dim()
        self.btn_lut_off = QPushButton("✕")
        self.btn_lut_off.setFixedWidth(30)
        self.btn_lut_off.setToolTip("Quitar el LUT")
        self.btn_lut_off.clicked.connect(lambda: self._set_color_field(lut=None))
        lr.addWidget(self.btn_lut)
        lr.addWidget(self.lut_name, 1)
        lr.addWidget(self.btn_lut_off)
        form.addRow(lr)
        mr = QHBoxLayout()
        self.lut_mix = QSlider(Qt.Horizontal)
        self.lut_mix.setRange(0, 100)
        self.lut_mix.valueChanged.connect(lambda v: self._loading or self._set_color_field(lut_mix=v / 100))
        mr.addWidget(self.lut_mix)
        form.addRow("Intensidad del LUT", mr)
        br = QHBoxLayout()
        self.btn_auto_color = QPushButton("✨ Color automático")
        self.btn_auto_color.setToolTip("Corrige exposición, contraste y balance de blancos mirando el fotograma "
                                       "del cabezal (suave: nunca exagera).")
        self.btn_auto_color.clicked.connect(lambda: self._ids and self.ctrl.auto_color(self._ids, self.engine.time))
        b_reset = QPushButton("↺ Restablecer")
        b_reset.clicked.connect(lambda: self._ids and self.ctrl.set_color(self._ids, None, "Quitar color"))
        br.addWidget(self.btn_auto_color)
        br.addWidget(b_reset)
        form.addRow(br)
        self.color_bypass = QCheckBox("👁 Ver sin corrección (comparar antes / después)")
        self.color_bypass.toggled.connect(self._on_color_bypass)
        form.addRow(self.color_bypass)
        self.color_box.setToolTip("Para repetir el color en otros clips: Ctrl+C en este y Alt+V en los otros → "
                                  "«Color».")
        set_help(self.color_box, "color")
        lay.addWidget(self.color_box)
        lay.addStretch()
        return w

    def _on_opacity(self, v: int):
        self.opacity_val.setText(f"{v} %")
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
        self.opacity_val.setText(f"{int(round(c.opacity * 100))} %")
        i = self.blend_combo.findData(c.blend or "normal")
        self.blend_combo.setCurrentIndex(max(0, i))
        self.op_kf_info.setText(f"〰 Curva de opacidad con {len(c.op_kf)} puntos (edítala con «〰 Curvas» en la "
                                "línea de tiempo)." if c.op_kf else "Para que cambie con el tiempo: «〰 Curvas» en la "
                                                                   "línea de tiempo.")

    def _color_now(self) -> dict:
        c = self._clip()
        return dict((c.color if c else None) or {})

    def _on_color_slider(self, key: str, v: int):
        self.color_values[key].setText(f"{v / 100:+.2f}" if v else "0")
        if self._loading or not self._ids:
            return
        col = self._color_now()
        col[key] = round(v / 100, 3)
        from ..core import color as C
        self.ctrl.set_color(self._ids, col, "Color: " + C.LABELS[key].split(" (")[0].lower())

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
        self.clip_tabs.setTabVisible(3, visual)
        if not visual:
            return
        self.color_box.setEnabled(editable)
        col = c.color or {}
        for k, sl in self.color_sliders.items():
            v = int(round(float(col.get(k, 0) or 0) * 100))
            sl.setValue(v)
            self.color_values[k].setText(f"{v / 100:+.2f}" if v else "0")
        lut = col.get("lut")
        self.lut_name.setText(os.path.basename(lut) if lut else "sin LUT")
        self.lut_name.setToolTip(lut or "")
        self.btn_lut_off.setEnabled(bool(lut))
        self.lut_mix.setEnabled(bool(lut))
        self.lut_mix.setValue(int(round(float(col.get("lut_mix", 1.0)) * 100)))

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        top = QFormLayout()
        top.addRow("Volumen", self.volume)
        self.pan = QSlider(Qt.Horizontal)
        self.pan.setRange(-100, 100)
        self.pan.setToolTip("Balance: izquierda ← → derecha (doble clic en la etiqueta = centro)")
        self.pan_label = QLabel("C")
        self.pan_label.setFixedWidth(34)
        self.pan.valueChanged.connect(self._on_pan)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("I"))
        prow.addWidget(self.pan, 1)
        prow.addWidget(QLabel("D"))
        prow.addWidget(self.pan_label)
        top.addRow("Balance", prow)
        lay.addLayout(top)

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
        self.btn_monitor = QPushButton("🎧 Escuchar con EQ")
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
        lay.addWidget(box)
        lay.addStretch()
        return w

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
        self.pan_label.setText("C" if v == 0 else (f"I{-v}" if v < 0 else f"D{v}"))
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
        self.pan_label.setText("C" if not c.pan else (f"I{-round(c.pan * 100)}" if c.pan < 0 else f"D{round(c.pan * 100)}"))
        n_same = sum(1 for o in self.ctrl.project.clips.values() if o.media_id == c.media_id)
        self.btn_eq_all.setVisible(n_same > 1)
        self.btn_eq_all.setText(f"Aplicar a los {n_same} clips de este archivo")
        if self._spectrum_key != (c.id, round(self._now(), 1)) and self.eq_graph.isVisible():
            self._spectrum_timer.start()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
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
        from PySide6.QtWidgets import QColorDialog, QFontComboBox, QGroupBox, QScrollArea, QToolButton
        from ..core.title_render import FACTORY
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        ol.addWidget(sc)
        w = QWidget()
        sc.setWidget(w)
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
        lay.addWidget(_spell(self.text_edit))          # ✍ ortografía (español de México / inglés / mixto)
        self.tw: dict = {}            # clave → (widget, cómo poner su valor)

        def reset_btn(keys):
            b = QToolButton()
            b.setText("↺")
            b.setToolTip("Volver al valor de fábrica")
            b.setAutoRaise(True)
            b.clicked.connect(lambda: self._set_text(**{k: FACTORY[k] for k in keys}))
            return b

        def row(form, label, widget, keys):
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(widget, 1)
            h.addWidget(reset_btn(keys))
            holder = QWidget()
            holder.setLayout(h)
            form.addRow(label, holder)

        def spin(key, lo, hi, step, suffix="", dec=1, scale=1.0):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(dec)
            sp.setSuffix(suffix)
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
        self.text_size = spin("size", 1.0, 40.0, 0.5, " % del alto")
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
        for key, txt in (("left", "⯇ Izq."), ("center", "≡ Centro"), ("right", "Der. ⯈")):
            tb = QToolButton()
            tb.setText(txt)
            tb.setCheckable(True)
            tb.clicked.connect(lambda _=False, k=key: self._set_text(align=k))
            self._align_btns[key] = tb
            al.addWidget(tb)
        al.addStretch(1)
        ha = QWidget()
        ha.setLayout(al)
        self.tw["align"] = (ha, lambda v: [b.setChecked(k == v) for k, b in self._align_btns.items()])
        row(f, "Justificado", ha, ["align"])
        self.text_pos = QComboBox()
        self.text_pos.addItem("Personalizada")
        for name, _x, _y in self.TEXT_POSITIONS:
            self.text_pos.addItem(name)
        self.text_pos.currentTextChanged.connect(self._on_text_pos)
        row(f, "Posición", self.text_pos, ["x", "y"])
        xy = QHBoxLayout()
        self.text_x = QDoubleSpinBox()
        self.text_y = QDoubleSpinBox()
        for sp, key in ((self.text_x, "x"), (self.text_y, "y")):
            sp.setRange(-100000, 100000)
            sp.setDecimals(0)
            sp.valueChanged.connect(lambda v, k=key: self._set_text(**{k: round(v / self._canvas_px(k), 4)}))
        self.tw["x"] = (self.text_x, lambda v: self.text_x.setValue(float(v) * self._canvas_px("x")))
        self.tw["y"] = (self.text_y, lambda v: self.text_y.setValue(float(v) * self._canvas_px("y")))
        xy.addWidget(QLabel("X"))
        xy.addWidget(self.text_x)
        xy.addWidget(QLabel("Y"))
        xy.addWidget(self.text_y)
        hxy = QWidget()
        hxy.setLayout(xy)
        f.addRow("", hxy)
        zr = QHBoxLayout()
        self.text_zx = spin("zoom_x", 0.05, 10, 0.05, "", 3)
        self.text_zy = spin("zoom_y", 0.05, 10, 0.05, "", 3)
        self.text_zlink = QCheckBox("🔗")
        self.text_zlink.setChecked(True)
        self.text_zlink.setToolTip("Zoom igual en X e Y")
        self.text_zx.valueChanged.connect(lambda v: self.text_zlink.isChecked() and not self._loading and
                                          self._set_text(zoom_x=round(v, 3), zoom_y=round(v, 3)))
        zr.addWidget(QLabel("X"))
        zr.addWidget(self.text_zx)
        zr.addWidget(self.text_zlink)
        zr.addWidget(QLabel("Y"))
        zr.addWidget(self.text_zy)
        hz = QWidget()
        hz.setLayout(zr)
        row(f, "Zoom", hz, ["zoom_x", "zoom_y"])
        row(f, "Ángulo de rotación", spin("rotation", -360, 360, 1, "°", 1), ["rotation"])
        lay.addWidget(g)

        # --- Trazo
        g = QGroupBox("Trazo")
        f = QFormLayout(g)
        row(f, "Color", color_btn("stroke_color"), ["stroke_color"])
        row(f, "Tamaño", spin("stroke_size", 0, 60, 1, " %", 0), ["stroke_size"])
        row(f, "", check("stroke_outside", "Solo afuera"), ["stroke_outside"])
        lay.addWidget(g)

        # --- Sombra (se activa con la casilla del título)
        g = QGroupBox("Sombra")
        g.setCheckable(True)
        g.toggled.connect(lambda v: self._set_text(shadow=bool(v)))
        self.tw["shadow"] = (g, lambda v, g=g: g.setChecked(bool(v)))
        f = QFormLayout(g)
        row(f, "Color", color_btn("shadow_color"), ["shadow_color"])
        so = QHBoxLayout()
        so.addWidget(QLabel("X"))
        so.addWidget(spin("shadow_x", -100, 100, 1, " %", 0))
        so.addWidget(QLabel("Y"))
        so.addWidget(spin("shadow_y", -100, 100, 1, " %", 0))
        hso = QWidget()
        hso.setLayout(so)
        row(f, "Desplazamiento", hso, ["shadow_x", "shadow_y"])
        row(f, "Desenfoque", spin("shadow_blur", 0, 100, 1, " %", 0), ["shadow_blur"])
        row(f, "Opacidad", spin("shadow_opacity", 0, 100, 5, " %", 0, 100.0), ["shadow_opacity"])
        lay.addWidget(g)

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
        bc = QHBoxLayout()
        bc.addWidget(QLabel("X"))
        bc.addWidget(spin("box_cx", -300, 300, 2, " %", 0))
        bc.addWidget(QLabel("Y"))
        bc.addWidget(spin("box_cy", -300, 300, 2, " %", 0))
        hbc = QWidget()
        hbc.setLayout(bc)
        row(f, "Centro", hbc, ["box_cx", "box_cy"])
        row(f, "Opacidad", spin("box_opacity", 0, 100, 5, " %", 0, 100.0), ["box_opacity"])
        lay.addWidget(g)

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
        lay.addWidget(g)

        # --- Memoria
        self.text_remember = QCheckBox("Recordar mis valores para los textos nuevos")
        self.text_remember.setToolTip("Lo que cambies (fuente, color, sombra, fondo…) se usa al crear textos nuevos.")
        self.text_remember.setChecked(str(QSettings("EditorIA", "EditorIA").value("texto/recordar", "true")).lower()
                                      == "true")
        self.text_remember.toggled.connect(lambda v: QSettings("EditorIA", "EditorIA").setValue(
            "texto/recordar", "true" if v else "false"))
        lay.addWidget(self.text_remember)
        rr = QHBoxLayout()
        b_mine = QPushButton("⭐ Aplicar mi estilo")
        b_mine.setToolTip("Pone en este texto tus valores recordados.")
        b_mine.clicked.connect(self._apply_my_text_style)
        b_fac = QPushButton("↺ Todo de fábrica")
        b_fac.clicked.connect(lambda: self._set_text(**{k: v for k, v in FACTORY.items() if k != "content"}))
        rr.addWidget(b_mine)
        rr.addWidget(b_fac)
        lay.addLayout(rr)
        lay.addStretch()
        return outer

    def _canvas_px(self, axis: str) -> float:
        p = self.ctrl.project
        return float(p.width if axis == "x" else p.height)

    def _cur_text(self) -> dict:
        c = self.ctrl.project.clips.get(self._ids[0]) if len(self._ids) == 1 else None
        return dict(c.text) if c is not None and c.text else {}

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
        name = next((n for n, x, y in self.TEXT_POSITIONS
                     if abs(x - t.get("x", 0.5)) < 0.01 and abs(y - t.get("y", 0.5)) < 0.01), "Personalizada")
        self.text_pos.setCurrentText(name)

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

    def _build_multi_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.multi_title = QLabel()
        self.multi_title.setObjectName("title")
        row = QHBoxLayout()
        b_lock = QPushButton("🔒 Bloquear todos")
        b_unlock = QPushButton("🔓 Desbloquear todos")
        b_lock.clicked.connect(lambda: self.ctrl.set_clip_props(self._ids, "Bloquear clips", locked=True))
        b_unlock.clicked.connect(lambda: self.ctrl.set_clip_props(self._ids, "Desbloquear clips", locked=False))
        row.addWidget(b_lock)
        row.addWidget(b_unlock)
        lay.addWidget(self.multi_title)
        lay.addLayout(row)
        lay.addStretch()
        return w

    # ------------------------------------------------------------- refresco
    def set_selection(self, ids: list[str]):
        """Una imagen y su sonido vinculado se muestran como un solo clip (como en Resolve):
        la pestaña Audio y el volumen actúan sobre el sonido."""
        ids = list(ids)
        self._all_ids = ids
        self._audio_id = None
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

    def _aclip(self):
        """El clip cuyo sonido se edita: el sonido vinculado o el propio clip."""
        if self._audio_id and self._audio_id in self.ctrl.project.clips:
            return self.ctrl.project.clips[self._audio_id]
        return self._clip()

    def _targets(self) -> list[str]:
        """Todos los clips seleccionados (incluido el sonido vinculado)."""
        return [i for i in getattr(self, "_all_ids", self._ids) if i in self.ctrl.project.clips] or self._ids

    def _refresh(self):
        self._loading = True
        try:
            p = self.ctrl.project
            self._ids = [i for i in self._ids if i in p.clips]
            if not self._ids:
                self.stack.setCurrentIndex(0)
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
            elif len(self._ids) > 1:
                self.stack.setCurrentIndex(2)
                self.multi_title.setText(f"{len(self._ids)} clips seleccionados")
            else:
                c = p.clips[self._ids[0]]
                if c.text is not None:
                    self.stack.setCurrentIndex(3)
                    self._fill_text_page(c)
                    return
                self.stack.setCurrentIndex(1)
                m = p.media_of(c)
                tr = p.track(c.track_id)
                self.clip_title.setText(m.name if m else "¿?")
                if c.origin == ORIGIN_AI:
                    self.clip_origin.setText("🟧 Creado por la IA")
                    self.clip_origin.setStyleSheet("color: #ff9f1c;")
                else:
                    self.clip_origin.setText("Creado por ti")
                    self.clip_origin.setStyleSheet("color: #9aa1ad;")
                self.clip_file.setText(os.path.basename(m.path) if m else "")
                self.clip_file.setToolTip(m.path if m else "")
                self.clip_track.setText(tr.name if tr else "")
                self.clip_pos.setText(f"{fmt_time(c.start)} → {fmt_time(c.end)}")
                self.clip_dur.setText(fmt_time(c.duration))
                if m and m.kind == KIND_IMAGE:
                    self.clip_src.setText("imagen fija")
                else:
                    self.clip_src.setText(f"{fmt_time(c.source_in)} → {fmt_time(c.source_in + c.src_len)}")
                ac = self._aclip() or c
                self.volume.setValue(round(ac.volume * 100))
                self.enabled.setChecked(c.enabled)
                self.locked.setChecked(c.locked)
                if not self.note.hasFocus():
                    self.note.setPlainText(c.note)
                editable = not c.locked and not (tr and tr.locked)
                self.volume.setEnabled(editable)
                self.enabled.setEnabled(editable)
                self.note.setReadOnly(not editable)
                visual = bool(m and m.kind != "audio") and not (tr and tr.kind == TRACK_AUDIO)
                self.frame_box.setVisible(visual)
                self.frame_box.setEnabled(editable)
                has_audio = bool(m and (m.kind == "audio" or m.has_audio))
                if self._audio_id:
                    self.clip_track.setText(f"{tr.name if tr else ''}  +  🔗 {p.track(ac.track_id).name}")
                self.clip_tabs.setTabVisible(1, visual)
                self.clip_tabs.setTabVisible(2, has_audio)
                self.clip_tabs.widget(2).setEnabled(editable)
                if self.clip_tabs.isTabVisible(self._last_tab):
                    self.clip_tabs.setCurrentIndex(self._last_tab)
                if has_audio:
                    self._refresh_audio_tab(ac, m)
                self.btn_track.setVisible(bool(m and m.kind == "video") and visual)
                self._refresh_speed(c, m, editable)
                self._refresh_enhance(c, m, editable)
                self._refresh_color(c, visual, editable)
                self._refresh_blend(c, visual, editable)
                fxd = c.fx or {}
                for key, spin in self.fx_spins.items():
                    spin.setValue(float(fxd.get(key, 0.0)))
                    spin.setEnabled(editable)
                for key in ("flash", "shake"):   # en el audio solo tienen sentido los fundidos
                    lbl = self.effects_box.layout().labelForField(self.fx_spins[key])
                    self.fx_spins[key].setVisible(visual)
                    if lbl:
                        lbl.setVisible(visual)
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
        finally:
            self._loading = False

    # ------------------------------------------------------------- cambios
    def _on_res(self, idx):
        if not self._loading:
            _l, w, h = RESOLUTIONS[idx]
            cur = self.ctrl.project.format
            fmt = (cur if cur in ("short", "edit") else "short") if h > w else "youtube"
            if fmt != cur:
                self.ctrl.set_project_format(fmt)
            self.ctrl.set_settings(width=w, height=h)

    def _refresh_speed(self, c, m, editable: bool):
        can = bool(m and m.kind != KIND_IMAGE)
        self.speed_box.setVisible(can)
        if not can:
            return
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
        self.enhance_box = QGroupBox("🛠 Mejorar imagen")
        f = QFormLayout(self.enhance_box)
        row = QHBoxLayout()
        self.denoise = QSlider(Qt.Horizontal)
        self.denoise.setRange(0, 100)
        self.denoise_val = QLabel("—")
        self.denoise_val.setFixedWidth(42)
        self.denoise.valueChanged.connect(self._on_denoise)
        row.addWidget(self.denoise, 1)
        row.addWidget(self.denoise_val)
        f.addRow("Reducir ruido", row)
        srow = QHBoxLayout()
        self.stab = QCheckBox("Estabilizar")
        self.stab.setToolTip("Quita el temblor de la cámara. Al activarlo se analiza el movimiento (unos segundos).")
        self.stab.toggled.connect(self._on_stab)
        self.stab_amount = QSlider(Qt.Horizontal)
        self.stab_amount.setRange(10, 100)
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

    def _fx_now(self) -> dict:
        c = self._clip()
        return dict((c.fx if c else None) or {})

    def _on_denoise(self, v: int):
        self.denoise_val.setText(f"{v} %" if v else "—")
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
        self.denoise_val.setText(f"{v} %" if v else "—")
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
                self._view_dialog = TransitionPreview(path, "Cómo queda", self.window())
                self._view_dialog.show()
        self._view_job.done.connect(lambda path: end(path))
        self._view_job.failed.connect(lambda m: end(msg=m))
        self._view_job.start()

    def _on_speed(self, speed: float | None = None, reverse: bool | None = None):
        if self._loading or not self._ids:
            return
        ids = self._targets()
        self.ctrl.set_speed(ids, speed=speed, reverse=reverse, ripple=self.ripple_speed.isChecked())

    def focus_speed(self):
        """Tecla R: lleva a la velocidad del clip seleccionado."""
        self.clip_tabs.setCurrentIndex(0)
        if self.speed_box.isVisible():
            self.speed.setFocus()
            self.speed.selectAll()

    def _on_fx(self, key: str, value: float):
        if self._loading or not self._ids:
            return
        names = {"flash": "Destello", "fade_in": "Fundido de entrada", "fade_out": "Fundido de salida",
                 "shake": "Temblor"}
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
                                  f"Animado: {n} claves" + (" · ◆ aquí" if on_kf else ""))
            self.btn_del_kf.setEnabled(on_kf and n >= 2)
            self.btn_prev_kf.setEnabled(n >= 2)
            self.btn_next_kf.setEnabled(n >= 2)
            # 🎞 posición y tamaño
            times = self.ctrl.layout_key_times(c.id)
            nl = len(c.layout_kf)
            here = any(abs(t - self._now()) <= 0.05 for t in times)
            self.lk_label.setText("Quieto (◆ Clave para animarlo)" if not nl else
                                  f"Animado: {nl} clave{'s' if nl != 1 else ''}" + (" · ◆ aquí" if here else ""))
            self.btn_del_lk.setEnabled(here)
            self.btn_prev_lk.setEnabled(bool(times))
            self.btn_next_lk.setEnabled(bool(times))
            self.btn_clear_lk.setEnabled(bool(nl))
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

    def _del_kf(self):
        c = self._clip()
        if c is not None:
            self.ctrl.remove_zoom_keyframe(c.id, self.ctrl.clip_source_time(c.id, self._now()))

    def _jump_kf(self, direction: int):
        c = self._clip()
        if c is None or self.engine is None or not c.zoom_kf:
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
