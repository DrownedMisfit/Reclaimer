"""
Panel «Limpieza de voz»: transcribir la narración, detectar silencios/muletillas/
repeticiones y revisar las sugerencias una a una (Escuchar · Aplicar · Ignorar · Restaurar).
"""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..ai import transcription, voice_cleanup
from ..core import mapping
from ..core.media import decode_mono
from ..core.model import KIND_AUDIO, KIND_VIDEO, SUG_APPLIED, SUG_PENDING, SUG_REJECTED, TRACK_AUDIO
from .common import SUGGESTION_COLORS, fmt_time
from .help import set_help
from .jobs import BackgroundJob

SR = 16000
STATUS_TEXT = {SUG_PENDING: "Pendiente", SUG_APPLIED: "✓ Aplicada", SUG_REJECTED: "Ignorada"}


def cut_kinds() -> set[str]:
    """Las casillas de «⚡ Limpieza automática» (también deciden qué sale tachado en el texto)."""
    s = QSettings("EditorIA", "EditorIA")
    return {k for k, d in voice_cleanup.AUTO_DEFAULTS.items()
            if str(s.value(f"limpieza_auto/{k}", d)).lower() in ("true", "1")}


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
        lay.setContentsMargins(6, 6, 6, 6)

        # --- Narración ---
        row = QHBoxLayout()
        row.addWidget(QLabel("Narración:"))
        self.media_combo = QComboBox()
        self.media_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.media_combo.setMinimumContentsLength(14)
        self.media_combo.currentIndexChanged.connect(self._on_media_changed)
        row.addWidget(self.media_combo, 1)
        lay.addLayout(row)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setObjectName("hint")
        self.banner_btn = QPushButton("Añadir la narración a la pista A1")
        self.banner_btn.clicked.connect(self._add_narration_to_timeline)
        lay.addWidget(self.banner)
        lay.addWidget(self.banner_btn)

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
        self.status = QLabel()
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._result_msg = ""
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
        g1.addWidget(self.btn_transcribe, 3, 0, 1, 2)
        lay.addWidget(self.sec1)

        # --- 2. Limpieza ---
        self.sec2 = set_help(_Section("2 · Limpieza de voz — qué buscar"), "limpieza")
        g2 = QGridLayout(self.sec2.body)
        g2.setContentsMargins(4, 2, 4, 2)
        self.chk_sil = QCheckBox("Silencios largos, mayores de")
        self.min_sil = QDoubleSpinBox()
        self.min_sil.setRange(0.3, 5.0)
        self.min_sil.setSingleStep(0.1)
        self.min_sil.setSuffix(" s")
        self.keep = QDoubleSpinBox()
        self.keep.setRange(0.0, 1.5)
        self.keep.setSingleStep(0.05)
        self.keep.setSuffix(" s")
        self.keep.setToolTip("Las pausas naturales nunca se eliminan del todo: se deja este margen.")
        self.chk_noise = QCheckBox("Respiraciones/ruidos")
        self.chk_fill = QCheckBox("Muletillas (eh, este…)")
        self.chk_rep = QCheckBox("Palabras repetidas")
        self.chk_take = QCheckBox("Tomas repetidas")
        self.chk_similar = QCheckBox("Frases que suenan parecido")
        self.chk_similar.setToolTip("Dos frases seguidas que dicen lo mismo con otras palabras. Solo se avisan: "
                                    "no se tachan solas.")
        self.chk_doubt = QCheckBox("Palabras dudosas")
        self.chk_clip = QCheckBox("Saturación")
        g2.addWidget(self.chk_sil, 0, 0)
        g2.addWidget(self.min_sil, 0, 1)
        g2.addWidget(QLabel("    dejando una pausa de"), 1, 0)
        g2.addWidget(self.keep, 1, 1)
        for i, chk in enumerate((self.chk_noise, self.chk_fill, self.chk_rep,
                                 self.chk_take, self.chk_similar, self.chk_doubt, self.chk_clip)):
            g2.addWidget(chk, 2 + i // 2, i % 2)
        self.my_fillers = QLineEdit()
        self.my_fillers.setPlaceholderText("p. ej.: ¿por qué?, la verdad, o sea")
        self.my_fillers.setToolTip("Las muletillas que sabes que dices, separadas por comas. Se proponen para quitar "
                                   "y salen tachadas en el texto.\nCon «?» solo cuenta si es una pregunta suelta "
                                   "(«¿por qué?» sí; «¿por qué lo hicieron?» no).")
        g2.addWidget(QLabel("Mis muletillas"), 6, 0)
        g2.addWidget(self.my_fillers, 6, 1)
        self.btn_analyze = QPushButton("🔍 Volver a analizar")
        self.btn_analyze.setToolTip("Analiza de nuevo con estas opciones (no repite la transcripción).")
        self.btn_analyze.clicked.connect(self.analyze)
        g2.addWidget(self.btn_analyze, 7, 0, 1, 2)
        lay.addWidget(self.sec2)
        self._load_options()

        # --- ⚡ Limpieza automática ---
        auto = set_help(QGroupBox("⚡ Limpieza automática"), "limpieza_auto")
        ga = QGridLayout(auto)
        self.auto_chk = {}
        for i, (key, text, tip, default) in enumerate((
                ("filler", "Muletillas seguras (eh, mmm…)", "Las que nunca son palabras de verdad.", True),
                ("filler_soft", "Posibles muletillas (este, bueno, o sea…)", "Solo cuando van seguidas de una pausa. "
                 "Revisa antes si hablas así a propósito.", False),
                ("repeat", "Palabras repetidas y cortadas", "«el el», «pro… problema». Las repeticiones que suelen "
                 "ser a propósito («muy muy», «no no») no se tocan.", True),
                ("retake", "Tomas repetidas (la IA elige la mejor)", "Se queda la toma más completa y limpia; "
                 "verás por qué en la lista.", True),
                ("silence", "Silencios largos", "Según los ajustes de arriba (siempre deja una pausa natural).", True),
                ("noise", "Respiraciones y ruidos", "Mejor revisarlas: a veces una respiración da naturalidad.", False))):
            chk = QCheckBox(text)
            chk.setToolTip(tip)
            chk.setChecked(str(self.settings.value(f"limpieza_auto/{key}", default)).lower() in ("true", "1"))
            chk.toggled.connect(lambda on, k=key: (self.settings.setValue(f"limpieza_auto/{k}", on),
                                                   self.cut_rules_changed.emit()))
            ga.addWidget(chk, i // 2, i % 2)
            self.auto_chk[key] = chk
        self.btn_auto_clean = QPushButton("⚡ Limpiar automáticamente")
        self.btn_auto_clean.setObjectName("primary")
        self.btn_auto_clean.setToolTip("Aplica de una vez las sugerencias marcadas arriba (un solo Ctrl+Z). "
                                       "Cualquier corte se puede devolver con «↺ Restaurar».")
        self.btn_auto_clean.clicked.connect(self.auto_clean)
        ga.addWidget(self.btn_auto_clean, 3, 0, 1, 2)
        self.auto_after = QCheckBox("Hacerlo solo al terminar de transcribir o analizar")
        self.auto_after.setChecked(str(self.settings.value("limpieza_auto/al_terminar", False)).lower() in ("true", "1"))
        self.auto_after.toggled.connect(lambda on: self.settings.setValue("limpieza_auto/al_terminar", on))
        ga.addWidget(self.auto_after, 4, 0, 1, 2)
        lay.addWidget(auto)

        # --- 3. Sugerencias ---
        box3 = set_help(QGroupBox("3 · Sugerencias de la IA"), "sugerencias")
        v3 = QVBoxLayout(box3)
        frow = QHBoxLayout()
        self.f_status = QComboBox()
        self.f_status.addItem("Pendientes", SUG_PENDING)
        self.f_status.addItem("Aplicadas", SUG_APPLIED)
        self.f_status.addItem("Ignoradas", SUG_REJECTED)
        self.f_status.addItem("Todas", "")
        self.f_kind = QComboBox()
        self.f_kind.addItem("Todos los tipos", "")
        for k, (label, _c) in voice_cleanup.KINDS.items():
            self.f_kind.addItem(self._icons[k], label, k)
        self.f_status.currentIndexChanged.connect(self._rebuild_list)
        self.f_kind.currentIndexChanged.connect(self._rebuild_list)
        frow.addWidget(self.f_status)
        frow.addWidget(self.f_kind, 1)
        v3.addLayout(frow)
        self.summary = QLabel()
        self.summary.setObjectName("dim")
        v3.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tiempo", "Sugerencia", "Estado"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setColumnWidth(0, 82)
        self.tree.setColumnWidth(1, 210)
        self.tree.setMinimumHeight(220)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.listen())
        v3.addWidget(self.tree, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.detail.setStyleSheet("color: #c7ccd4; padding: 4px;")
        v3.addWidget(self.detail)
        b1 = QHBoxLayout()
        self.btn_listen = QPushButton("▶ Escuchar")
        self.btn_listen.setToolTip("Reproduce ese momento (con un segundo antes y después). Doble clic también.")
        self.btn_apply = QPushButton("✓ Aplicar")
        self.btn_reject = QPushButton("✗ Ignorar")
        self.btn_restore = QPushButton("↺ Restaurar")
        self.btn_restore.setToolTip("Devuelve a la timeline un corte ya aplicado.")
        self.btn_listen.clicked.connect(self.listen)
        self.btn_apply.clicked.connect(self.apply_selected)
        self.btn_reject.clicked.connect(self.reject_selected)
        self.btn_restore.clicked.connect(self.restore_selected)
        for b in (self.btn_listen, self.btn_apply, self.btn_reject, self.btn_restore):
            b1.addWidget(b)
        v3.addLayout(b1)
        self.btn_apply_all = QPushButton("Aplicar todas las de la lista")
        self.btn_apply_all.clicked.connect(self.apply_all_visible)
        v3.addWidget(self.btn_apply_all)
        # Limpio, como Resolve: arriba la narración y cómo va; lo demás, en pestañas
        from .tabs import tabbed, untitle
        for sec in (self.sec1, self.sec2):
            sec.header.hide()
            sec.set_expanded(True)
        untitle(auto, box3)
        self.tabs = tabbed([("Transcribir", [self.sec1]), ("Limpiar", [self.sec2, auto]),
                            ("Sugerencias", [box3], True)])
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

    # ------------------------------------------------------------ opciones
    def _load_options(self):
        s = self.settings
        d = voice_cleanup.CleanupOptions()

        def b(key, default):
            return str(s.value(f"limpieza/{key}", default)).lower() in ("true", "1")

        self.chk_sil.setChecked(b("silencios", d.silences))
        self.min_sil.setValue(float(s.value("limpieza/min_silencio", d.min_silence)))
        self.keep.setValue(float(s.value("limpieza/pausa", d.keep_pause)))
        self.chk_noise.setChecked(b("ruidos", d.noises))
        self.chk_fill.setChecked(b("muletillas", d.fillers))
        self.chk_rep.setChecked(b("repetidas", d.repeated_words))
        self.chk_take.setChecked(b("tomas", d.retakes))
        self.chk_similar.setChecked(b("parecidas", d.similar))
        self.chk_doubt.setChecked(b("dudosas", d.doubtful))
        self.chk_clip.setChecked(b("saturacion", d.clipping))
        self.my_fillers.setText(str(s.value("limpieza/mis_muletillas", "")))
        from ..ai import verbatim
        ok, why = verbatim.available()
        self.chk_literal.setEnabled(ok)
        self.chk_literal.setChecked(ok and str(s.value("transcripcion/literal", True)).lower() in ("true", "1"))
        if not ok:
            self.chk_literal.setToolTip(self.chk_literal.toolTip() + f"\n\nNo disponible: {why}")
        idx = self.model_combo.findData(s.value("transcripcion/modelo", "equilibrado"))
        self.model_combo.setCurrentIndex(max(0, idx))
        idx = self.lang_combo.findData(s.value("transcripcion/idioma", "es"))
        self.lang_combo.setCurrentIndex(max(0, idx))

    def options(self) -> voice_cleanup.CleanupOptions:
        o = voice_cleanup.CleanupOptions(
            silences=self.chk_sil.isChecked(), min_silence=self.min_sil.value(),
            keep_pause=self.keep.value(), noises=self.chk_noise.isChecked(),
            fillers=self.chk_fill.isChecked(), repeated_words=self.chk_rep.isChecked(),
            retakes=self.chk_take.isChecked(), similar=self.chk_similar.isChecked(),
            doubtful=self.chk_doubt.isChecked(), clipping=self.chk_clip.isChecked(),
            my_fillers=tuple(x.strip() for x in self.my_fillers.text().split(",") if x.strip()))
        s = self.settings
        for key, val in (("silencios", o.silences), ("min_silencio", o.min_silence), ("pausa", o.keep_pause),
                         ("ruidos", o.noises), ("muletillas", o.fillers), ("repetidas", o.repeated_words),
                         ("tomas", o.retakes), ("parecidas", o.similar), ("dudosas", o.doubtful),
                         ("saturacion", o.clipping), ("mis_muletillas", self.my_fillers.text().strip())):
            s.setValue(f"limpieza/{key}", val)
        s.setValue("transcripcion/modelo", self.model_combo.currentData())
        s.setValue("transcripcion/idioma", self.lang_combo.currentData())
        if self.chk_literal.isEnabled():
            s.setValue("transcripcion/literal", self.chk_literal.isChecked())
        return o

    # ----------------------------------------------------------- narración
    def media_id(self) -> str | None:
        return self.media_combo.currentData()

    def _refresh_media(self):
        current = self.media_id()
        p = self.ctrl.project
        items = [m for m in p.media.values()
                 if m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)]
        items.sort(key=lambda m: (m.category != "Narración", m.kind != KIND_AUDIO, m.name.lower()))
        self.media_combo.blockSignals(True)
        self.media_combo.clear()
        for m in items:
            self.media_combo.addItem(m.name, m.id)
        idx = self.media_combo.findData(current)
        self.media_combo.setCurrentIndex(idx if idx >= 0 else (0 if items else -1))
        self.media_combo.blockSignals(False)
        self._on_media_changed()

    def _on_media_changed(self):
        self._result_msg = ""
        self.media_selected.emit(self.media_id() or "")
        self._update_state()
        self._rebuild_list()

    def _update_state(self):
        mid = self.media_id()
        p = self.ctrl.project
        busy = self.job is not None
        has = bool(mid)
        tr = p.transcripts.get(mid) if mid else None
        self.btn_transcribe.setEnabled(has and not busy)
        self.btn_transcribe.setText("🎙 Transcribir de nuevo" if tr else "🎙 Transcribir y analizar")
        self.btn_analyze.setEnabled(has and not busy)
        on_timeline = bool(mid and mapping.clips_of_media(p, mid))
        if not has:
            self.banner.setText("Importa tu narración en Medios.")
        elif not on_timeline:
            self.banner.setText("La narración todavía no está en la timeline. Puedes transcribirla "
                                "igualmente, pero para aplicar cortes tiene que estar en la timeline.")
        self.banner.setVisible(not has or not on_timeline)
        self.banner_btn.setVisible(has and not on_timeline)
        if not busy:
            if tr:
                n = len(tr.get("words", []))
                self.status.setText(f"✓ Transcrita: {n} palabras (texto en la pestaña «Texto»)."
                                    + (f"\n{self._result_msg}" if self._result_msg else ""))
            elif has:
                self.status.setText("Sin transcribir. La primera vez se descargará el modelo de voz."
                                    + (f"\n{self._result_msg}" if self._result_msg else ""))
            else:
                self.status.setText("")
        # Con sugerencias ya hechas, se enseña su pestaña directamente
        has_sug = bool(mid) and any(s.media_id == mid for s in p.suggestions)
        if not busy and has_sug != getattr(self, "_had_sug", None):
            self._had_sug = has_sug
            if hasattr(self, "tabs"):
                self.tabs.setCurrentIndex(2 if has_sug else 0)

    def _add_narration_to_timeline(self):
        mid = self.media_id()
        tracks = [t for t in self.ctrl.project.tracks if t.kind == TRACK_AUDIO]
        if mid and tracks:
            m = self.ctrl.project.media[mid]
            self.ctrl.add_media([mid], tracks[0].id if m.kind == KIND_AUDIO else None, 0.0)
            self._update_state()

    # ------------------------------------------------------------- tareas
    def _start_job(self, fn, on_done, label):
        self.job = BackgroundJob(fn, self)
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
        self.status.setText(text)

    def _on_failed(self, msg):
        self._result_msg = f"✗ {msg}" if msg != "Cancelado." else "Cancelado."
        if msg != "Cancelado.":
            QMessageBox.warning(self, "No se pudo completar", msg)

    def _on_job_finished(self):
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
        """🎙 Transcribir. analyze=False (lo pide «⚡ Subtítulos para Short»): solo el texto, rápido; sin buscar
        bostezos, titubeos, respiraciones ni tomas repetidas (el usuario: «que no se active de manera automática cuando
        vaya a subtitular»). Eso se puede analizar después con «Transcribir y analizar» / «Analizar»."""
        mid = self.media_id()
        if not mid or self.job:
            return
        ok, why = transcription.is_available()
        if not ok:
            QMessageBox.warning(self, "Transcripción", why)
            return
        if mid in self.ctrl.project.transcripts:
            r = QMessageBox.question(self, "Transcribir de nuevo",
                                     "Esta narración ya está transcrita. Si la transcribes de nuevo "
                                     "se perderán las correcciones que hiciste en el texto.\n\n¿Continuar?")
            if r != QMessageBox.Yes:
                return
        path = self.ctrl.project.media[mid].path
        model, lang, opts = self.model_combo.currentData(), self.lang_combo.currentData(), self.options()
        literal = analyze and self.chk_literal.isEnabled() and self.chk_literal.isChecked()

        def work(progress, cancelled):
            progress(0.0, "Leyendo el audio…")
            samples = self.audio.get(path)
            def part(lo, hi):        # con la escucha literal, cada paso es media barra
                return lambda f, t: progress(lo + (hi - lo) * f, t)
            tr = transcription.transcribe(samples, model, lang, part(0.0, 0.5) if literal else progress, cancelled,
                                          fillers=analyze)
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

        self._start_job(work, self._on_transcribed, "Preparando…")

    def _on_transcribed(self, result):
        mid, tr, items, opts = result
        self.ctrl.set_transcript(mid, tr)
        if self.ctrl.project.subtitles.media_id not in self.ctrl.project.transcripts:
            self.ctrl.set_subtitle_style("Texto de los subtítulos", media_id=mid)
        if items is None:                          # (solo el texto, para los subtítulos: sin sugerencias)
            self._result_msg = f"✓ Transcrita: {len(tr.get('words', []))} palabras (sin buscar errores al hablar)."
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
        self._result_msg = (f"✓ {n} sugerencias. Revísalas abajo: todavía no se ha cortado nada."
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
        self.btn_reject.setText("↶ Recuperar" if sel and all(s.status == SUG_REJECTED for s in sel)
                                else "✗ Ignorar")
        self.btn_restore.setEnabled(any(s.status == SUG_APPLIED for s in sel))
        if one and one.kind == "retake" and one.status == SUG_PENDING:
            self.btn_apply.setText("✓ Elegir toma…")
            self.btn_listen.setText("▶ Comparar")
        else:
            self.btn_apply.setText("✓ Aplicar")
            self.btn_listen.setText("▶ Escuchar")
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
        if ask and QMessageBox.question(self, "Limpieza automática",
                                        f"Se quitarán: {summary}.\n\nEn las tomas repetidas se queda la que eligió "
                                        "la IA. Todo se deshace con un Ctrl+Z, o corte a corte con «↺ Restaurar»."
                                        ) != QMessageBox.Yes:
            return 0
        n = self.ctrl.apply_suggestions([s.id for s in sugs]) or 0
        if n:
            self.ctrl.message.emit(f"⚡ Limpieza automática: {summary}. Revisa en «Aplicadas» y restaura lo que quieras.")
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
