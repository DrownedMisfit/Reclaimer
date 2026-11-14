"""Panel «Subtítulos»: activar los subtítulos dentro del video y elegir su estilo."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFontComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from ..core.subtitles import PRESETS
from .help import set_help

POSITIONS = [("bottom", "Abajo"), ("middle", "Centro"), ("top", "Arriba")]
ANIMATIONS = [("none", "Ninguna"), ("fade", "Aparecer suave"), ("pop", "Rebote"),
              ("karaoke", "Karaoke (resalta la palabra que dices)")]


class ColorButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self._color = "#FFFFFF"
        self.setFixedSize(48, 24)
        self.clicked.connect(self._pick)

    def set_color(self, hex_color: str):
        if hex_color == self._color and self.styleSheet():
            return                      # el mismo color: no se vuelve a aplicar el estilo
        self._color = hex_color
        self.setStyleSheet(f"QPushButton {{ background: {hex_color}; border: 1px solid #6b7280;"
                           f" border-radius: 4px; }}")

    def _pick(self):
        from .common import pick_color
        c = pick_color(self._color, self, self._title)
        if c.isValid():
            self.set_color(c.name().upper())
            self.color_changed.emit(self._color)


def _dim(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


class SubtitlesPanel(QWidget):
    transcribe_requested = Signal()      # ⚡ «Subtítulos para Short»: transcribir antes (lo hace la pestaña Limpieza)

    def __init__(self, ctrl, preferred_media=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self._preferred_media = preferred_media or (lambda: "")
        self._loading = False

        content = QWidget()
        set_help(content, "subtitulos")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(6, 6, 6, 6)

        # ⚡ Lo de siempre en un clic: transcribe (si hace falta), activa los subtítulos y les pone el estilo Short
        self.btn_quick = QPushButton("⚡ Subtítulos para Short")
        self.btn_quick.setObjectName("primary")
        self.btn_quick.setToolTip("En un clic: transcribe tu narración (si aún no lo está), activa los subtítulos "
                                  "y les pone el estilo «Mis Shorts». Luego puedes retocarlos en las pestañas.")
        self.btn_quick.clicked.connect(self.quick_short)
        lay.addWidget(self.btn_quick)
        self._pending = None

        self.enabled = QCheckBox("Mostrar subtítulos dentro del video")
        f = QFont(self.font())
        f.setBold(True)
        self.enabled.setFont(f)
        self.enabled.toggled.connect(self._on_enabled)
        lay.addWidget(self.enabled)
        self.info = _dim("")
        self.info.setObjectName("hint")
        lay.addWidget(self.info)

        form0 = QFormLayout()
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(self._on_source)
        form0.addRow("Texto de", self.source)
        prow = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(PRESETS))
        apply_preset = QPushButton("Aplicar estilo")
        apply_preset.clicked.connect(self._apply_preset)
        prow.addWidget(self.preset, 1)
        prow.addWidget(apply_preset)
        form0.addRow("Estilo", prow)
        lay.addLayout(form0)

        # --- Letra ---
        g1 = QGroupBox("Letra")
        f1 = QFormLayout(g1)
        self.font_box = QFontComboBox()
        self.font_box.currentFontChanged.connect(lambda fnt: self._set(font=fnt.family()))
        self.size = QDoubleSpinBox()
        self.size.setRange(1.5, 15.0)
        self.size.setSingleStep(0.25)
        self.size.setSuffix(" % del alto")
        self.size.valueChanged.connect(lambda v: self._set(size=v))
        self.bold = QCheckBox("Negrita")
        self.bold.toggled.connect(lambda v: self._set(bold=v))
        self.upper = QCheckBox("MAYÚSCULAS")
        self.upper.toggled.connect(lambda v: self._set(uppercase=v))
        self.strip = QCheckBox("Sin comas ni puntos")
        self.strip.toggled.connect(lambda v: self._set(strip_punct=v))
        row = QHBoxLayout()
        row.addWidget(self.bold)
        row.addWidget(self.upper)
        f1.addRow("Fuente", self.font_box)
        f1.addRow("Tamaño", self.size)
        f1.addRow(row)
        f1.addRow(self.strip)
        lay.addWidget(g1)

        # --- Colores ---
        g2 = QGroupBox("Colores")
        f2 = QFormLayout(g2)
        self.c_text = ColorButton("Color del texto")
        self.c_text.color_changed.connect(lambda c: self._set(color=c))
        self.c_hl = ColorButton("Color de resaltado")
        self.c_hl.color_changed.connect(lambda c: self._set(highlight=c))
        self.c_out = ColorButton("Color del contorno")
        self.c_out.color_changed.connect(lambda c: self._set(outline_color=c))
        self.outline = QDoubleSpinBox()
        self.outline.setRange(0.0, 2.0)
        self.outline.setSingleStep(0.05)
        self.outline.setSuffix(" %")
        self.outline.valueChanged.connect(lambda v: self._set(outline=v))
        orow = QHBoxLayout()
        orow.addWidget(self.c_out)
        orow.addWidget(QLabel("grosor"))
        orow.addWidget(self.outline, 1)
        self.box = QCheckBox("Caja de fondo")
        self.box.toggled.connect(lambda v: self._set(box=v))
        self.c_box = ColorButton("Color de la caja")
        self.c_box.color_changed.connect(lambda c: self._set(box_color=c))
        self.box_op = QSpinBox()
        self.box_op.setRange(0, 100)
        self.box_op.setSuffix(" % opaca")
        self.box_op.valueChanged.connect(lambda v: self._set(box_opacity=v / 100))
        brow = QHBoxLayout()
        brow.addWidget(self.box)
        brow.addWidget(self.c_box)
        brow.addWidget(self.box_op, 1)
        f2.addRow("Texto", self.c_text)
        f2.addRow("Resaltado", self.c_hl)
        f2.addRow("Contorno", orow)
        self.shadow = QDoubleSpinBox()
        self.shadow.setRange(0.0, 2.0)
        self.shadow.setSingleStep(0.05)
        self.shadow.setSuffix(" % (0 = sin sombra)")
        self.shadow.setToolTip("Sombra suave y difuminada debajo de las letras (como en los Shorts): se leen mejor sobre "
                               "cualquier imagen.")
        self.shadow.valueChanged.connect(lambda v: self._set(shadow=v))
        f2.addRow("Sombra suave", self.shadow)
        f2.addRow(brow)
        lay.addWidget(g2)

        # --- Posición y líneas ---
        g3 = QGroupBox("Posición y líneas")
        f3 = QFormLayout(g3)
        self.position = QComboBox()
        for key, label in POSITIONS:
            self.position.addItem(label, key)
        self.position.currentIndexChanged.connect(lambda: self._set(position=self.position.currentData()))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 40.0)
        self.margin.setSingleStep(0.5)
        self.margin.setSuffix(" % desde el borde")
        self.margin.valueChanged.connect(lambda v: self._set(margin=v))
        self.chars = QSpinBox()
        self.chars.setRange(8, 80)
        self.chars.setSuffix(" letras por línea")
        self.chars.valueChanged.connect(lambda v: self._set(max_chars=v))
        self.lines = QComboBox()
        self.lines.addItem("1 línea", 1)
        self.lines.addItem("2 líneas", 2)
        self.lines.currentIndexChanged.connect(lambda: self._set(max_lines=self.lines.currentData()))
        f3.addRow("Posición", self.position)
        f3.addRow("Margen", self.margin)
        f3.addRow("Máximo", self.chars)
        f3.addRow("Líneas", self.lines)
        self.words = QComboBox()
        self.words.addItem("Sin límite", 0)
        for k in (1, 2, 3, 4, 5):
            self.words.addItem(f"{k} como mucho", k)
        self.words.setToolTip("Cuántas palabras salen a la vez en pantalla (en los Shorts, 3). No deja «de / la / el» "
                              "sueltos al final de un bloque.")
        self.words.currentIndexChanged.connect(lambda: self._set(max_words=self.words.currentData()))
        f3.addRow("Palabras a la vez", self.words)
        lay.addWidget(g3)

        # --- Animación ---
        g4 = QGroupBox("Animación")
        f4 = QFormLayout(g4)
        self.anim = QComboBox()
        for key, label in ANIMATIONS:
            self.anim.addItem(label, key)
        self.anim.currentIndexChanged.connect(lambda: self._set(animation=self.anim.currentData()))
        f4.addRow(self.anim)
        lay.addWidget(g4)

        # --- Palabras resaltadas ---
        g5 = QGroupBox("Palabras resaltadas")
        v5 = QVBoxLayout(g5)
        self.emph_list = _dim("")
        self.emph_list.setStyleSheet("color: #e6e8ec;")
        v5.addWidget(self.emph_list)
        clear = QPushButton("Quitar todos los resaltados")
        clear.clicked.connect(lambda: self.ctrl.set_emphasis(list(self.ctrl.project.subtitles.emphasis), False))
        v5.addWidget(clear)
        self.style_widgets = [self.source, g1, g2, g3, g4, g5, self.preset, apply_preset]

        # Limpio, como Resolve: arriba lo esencial; el estilo, en pestañas
        from .tabs import tabbed, untitle
        untitle(g1, g2, g3, g4)
        self.tabs = tabbed([("Letra", [g1]), ("Colores", [g2]), ("Posición", [g3]), ("Animación", [g4, g5])])
        set_help(self.tabs, "subtitulos")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(content)
        outer.addWidget(self.tabs, 1)

        from .common import lazy_refresh
        self._lazy = lazy_refresh(self, self.refresh)      # oculto: no se rehace en cada edición
        ctrl.project_changed.connect(self._lazy)
        ctrl.media_changed.connect(self._lazy)
        ctrl.transcript_changed.connect(self._lazy)
        ctrl.transcript_changed.connect(           # (con la transcripción entera, no con un bloque a medias)
            lambda m: self._finish_quick(m) if m and m == self._pending
            and (ctrl.project.transcripts.get(m) or {}).get("hasta") is None else None)
        self.refresh()

    # ------------------------------------------------------------ cambios
    def _set(self, text: str = "Estilo de subtítulos", **props):
        if not self._loading:
            self.ctrl.set_subtitle_style(text, **props)

    def _on_source(self):
        mid = self.source.currentData() or ""
        if not self._loading and mid != self.ctrl.project.subtitles.media_id:
            # Los resaltados son de la otra narración: se quitan
            self._set("Texto de los subtítulos", media_id=mid, emphasis=[])

    def _on_enabled(self, on: bool):
        if self._loading:
            return
        st = self.ctrl.project.subtitles
        props = {"enabled": on}
        if on and st.media_id not in self.ctrl.project.transcripts:
            preferred = self._preferred_media()
            mid = preferred if preferred in self.ctrl.project.transcripts else \
                next(iter(self.ctrl.project.transcripts), "")
            props["media_id"] = mid
        self.ctrl.set_subtitle_style("Activar subtítulos" if on else "Desactivar subtítulos", **props)

    def quick_short(self):
        """⚡ Transcribir (si hace falta) → activar subtítulos → estilo «Mis Shorts»."""
        mid = self._preferred_media() or ""
        p = self.ctrl.project
        if not mid or mid not in p.media:
            self.info.setText("Primero elige o importa tu narración (pestaña «Limpieza»).")
            return
        if mid in p.transcripts and p.transcripts[mid].get("hasta") is None:
            self._finish_quick(mid)
            return
        self._pending = mid
        self.info.setText("⚡ Transcribiendo tu narración… al terminar se ponen los subtítulos solos.")
        self.transcribe_requested.emit()

    def _finish_quick(self, mid: str):
        self._pending = None
        from ..core.subtitles import SHORTS
        name = SHORTS if SHORTS in PRESETS else next(iter(PRESETS))
        self.ctrl.set_subtitle_style("⚡ Subtítulos para Short", enabled=True, media_id=mid, preset=name,
                                     **PRESETS[name])
        self.info.setText(f"✓ Subtítulos puestos con el estilo «{name}» (a lo mucho 3 palabras a la vez). Míralos y "
                          "corrígelos en «Texto → 📺 En pantalla».")

    def _apply_preset(self):
        name = self.preset.currentText()
        self.ctrl.set_subtitle_style(f"Estilo de subtítulos: {name}", preset=name, **PRESETS[name])

    # ------------------------------------------------------------ refresco
    def refresh(self):
        self._loading = True
        try:
            p = self.ctrl.project
            st = p.subtitles
            self.enabled.setChecked(st.enabled)
            self.source.clear()
            for mid in p.transcripts:
                if mid in p.media:
                    self.source.addItem(p.media[mid].name, mid)
            self.source.setCurrentIndex(max(0, self.source.findData(st.media_id)))
            if not p.transcripts:
                if self._pending is None:
                    self.info.setText("")                    # (el botón de arriba ya lo dice)
            elif st.enabled and st.media_id not in p.transcripts:
                self.info.setText("Elige de qué narración salen los subtítulos.")
            else:
                self.info.setText("")
            self.info.setVisible(bool(self.info.text()))
            self.enabled.setEnabled(bool(p.transcripts))
            for w in self.style_widgets:
                w.setEnabled(st.enabled)

            if st.preset in PRESETS:
                self.preset.setCurrentText(st.preset)
            self.font_box.setCurrentFont(QFont(st.font))
            self.size.setValue(st.size)
            self.bold.setChecked(st.bold)
            self.upper.setChecked(st.uppercase)
            self.strip.setChecked(st.strip_punct)
            self.c_text.set_color(st.color)
            self.c_hl.set_color(st.highlight)
            self.c_out.set_color(st.outline_color)
            self.outline.setValue(st.outline)
            self.box.setChecked(st.box)
            self.c_box.set_color(st.box_color)
            self.box_op.setValue(round(st.box_opacity * 100))
            self.position.setCurrentIndex(max(0, self.position.findData(st.position)))
            self.margin.setValue(st.margin)
            self.chars.setValue(st.max_chars)
            self.lines.setCurrentIndex(max(0, self.lines.findData(st.max_lines)))
            self.words.setCurrentIndex(max(0, self.words.findData(int(getattr(st, "max_words", 0) or 0))))
            if hasattr(self, "shadow"):
                self.shadow.setValue(float(getattr(st, "shadow", 0.0) or 0.0))
            self.anim.setCurrentIndex(max(0, self.anim.findData(st.animation)))

            words = p.transcripts.get(st.media_id, {}).get("words", [])
            emph = [words[i][2] for i in st.emphasis if 0 <= i < len(words)]
            self.emph_list.setText("⭐ " + " · ".join(emph) if emph else "Ninguna todavía.")
        finally:
            self._loading = False
