"""Ventana de exportación: un clic para YouTube / TikTok / ver en Windows (con el códec que recomiendan),
o «Personalizado» con resolución, FPS, códec, GPU/CPU y bitrate. Si la tarjeta gráfica falla, se reintenta
sola con el procesador."""
from __future__ import annotations

import os
import subprocess
from ..core.paths import temp_dir as _temp_dir
import time

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QVBoxLayout)

from ..core import media as media_tools
from ..export.ffmpeg_export import PRESETS, TARGETS, ExportOptions, build_command, target_bitrate, target_size
from .common import fmt_time


def _default_export_dir() -> str:
    """Si el proyecto aún no tiene carpeta: F:/Reclaimer/Exportados (junto al programa, no en C:)."""
    from ..core.paths import user_dir
    d = user_dir() / "Exportados"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


class ExportDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle("Exportar video")
        self.setMinimumWidth(560)
        self.proc: QProcess | None = None
        self._retried_cpu = False
        self.target = "custom"
        self.total = 0.0
        self._log: list[str] = []
        p = ctrl.project

        self.preset = QComboBox()
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.preset.activated.connect(lambda _i: self._apply_preset(self.preset.currentText()))   # (el mismo otra vez)
        self._fill_presets()
        self.width_box = QSpinBox()
        self.width_box.setRange(16, 7680)
        self.width_box.setSingleStep(2)
        self.height_box = QSpinBox()
        self.height_box.setRange(16, 4320)
        self.height_box.setSingleStep(2)
        size = QHBoxLayout()
        size.addWidget(self.width_box)
        size.addWidget(QLabel("×"))
        size.addWidget(self.height_box)
        self.fps = QComboBox()
        self.fps.addItems(["24", "25", "30", "50", "60"])
        self.fps.setCurrentText(f"{p.fps:g}" if f"{p.fps:g}" in ["24", "25", "30", "50", "60"] else "30")
        self.codec = QComboBox()
        self.codec.addItem("H.264 (máxima compatibilidad)", "h264")
        self.codec.addItem("H.265 / HEVC (menos peso, misma calidad)", "hevc")
        self.encoder = QComboBox()
        from ..core import hw
        marca = hw.label()
        self.encoder.addItem(f"Tarjeta gráfica {marca} (rápido)" if marca else "Tarjeta gráfica (rápido)", "gpu")
        if not marca:
            self.encoder.setItemData(0, "Este equipo no tiene un codificador de video por tarjeta gráfica que funcione: "
                                        "se usará el procesador.", Qt.ToolTipRole)
        self.encoder.addItem("Procesador (más lento, muy compatible)", "cpu")
        self.bitrate = QDoubleSpinBox()
        self.bitrate.setRange(1, 200)
        self.bitrate.setSuffix(" Mbps")
        self.bitrate.setDecimals(0)

        st = QSettings("EditorIA", "EditorIA")
        default_dir = str(st.value("exportar/carpeta", "") or "") or \
            (os.path.dirname(ctrl.path) if ctrl.path else _default_export_dir())
        self.out = QLineEdit(os.path.join(default_dir, f"{p.name}.mp4"))
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self.out)
        out_row.addWidget(browse)

        # Destino de un clic
        from PySide6.QtWidgets import QButtonGroup, QWidget
        self.targets = QButtonGroup(self)
        trow = QHBoxLayout()
        for key, label, apps in [(k, t["name"], t.get("apps", "")) for k, t in TARGETS.items()] +                 [("custom", "⚙ Personalizado", "tú eliges todo")]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setMinimumHeight(38)
            b.setProperty("target", key)
            self.targets.addButton(b)
            col = QVBoxLayout()                       # el botón y, debajo, para qué apps sirve
            col.setSpacing(2)
            col.addWidget(b)
            pie = QLabel(apps)
            pie.setObjectName("dim")
            pie.setAlignment(Qt.AlignCenter)
            col.addWidget(pie)
            trow.addLayout(col)
        self.targets.buttonClicked.connect(lambda b: self._apply_target(b.property("target")))
        self.target_info = QLabel("")
        self.target_info.setWordWrap(True)
        self.target_info.setObjectName("dim")
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(0, 0, 0, 0)
        prow = QHBoxLayout()
        prow.addWidget(self.preset, 1)
        self.btn_save_preset = QPushButton("💾 Guardar…")
        self.btn_save_preset.setToolTip("Guarda estos ajustes (resolución, FPS, códec, calidad, subtítulos…) con un "
                                        "nombre: saldrán en esta lista con ★, como en Shotcut")
        self.btn_save_preset.clicked.connect(lambda: self.save_preset())
        self.btn_del_preset = QPushButton("🗑")
        self.btn_del_preset.setFixedWidth(32)
        self.btn_del_preset.setToolTip("Borra el preset tuyo elegido (★)")
        self.btn_del_preset.clicked.connect(lambda: self.delete_preset())
        prow.addWidget(self.btn_save_preset)
        prow.addWidget(self.btn_del_preset)
        form.addRow("Preset", prow)
        form.addRow("Resolución", size)
        form.addRow("Fotogramas por segundo", self.fps)
        form.addRow("Códec", self.codec)
        form.addRow("Codificar con", self.encoder)
        form.addRow("Calidad (bitrate)", self.bitrate)
        self.subs = QCheckBox("Incluir los subtítulos dentro del video")
        self.subs.setChecked(p.subtitles.enabled)
        self.subs.setEnabled(p.subtitles.enabled)
        if not p.subtitles.enabled:
            self.subs.setToolTip("Actívalos primero en la pestaña «Subtítulos».")
        rng = p.marked_range()
        self.only_marked = QCheckBox("Solo el tramo marcado (de la entrada I a la salida O)")
        self.only_marked.setEnabled(rng is not None)
        if rng:
            self.only_marked.setText(f"Solo el tramo marcado ({fmt_time(rng[0])} → {fmt_time(rng[1])})")
        else:
            self.only_marked.setToolTip("Marca un tramo en la línea de tiempo con I (entrada) y O (salida).")
        form2 = QFormLayout()
        form2.addRow("Subtítulos", self.subs)
        form2.addRow("Tramo", self.only_marked)
        self.max_q = QCheckBox("Máxima calidad (tarda casi el doble; a esta calidad casi no se nota)")
        self.max_q.setToolTip("La tarjeta gráfica analiza cada fotograma antes de comprimirlo. Para YouTube y TikTok "
                              "no hace falta: ellos vuelven a comprimir el video.")
        self.max_q.setChecked(str(QSettings("EditorIA", "EditorIA").value("exportar/max_calidad", "false")) == "true")
        self.max_q.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "exportar/max_calidad", "true" if on else "false"))
        form2.addRow("Calidad", self.max_q)
        self.low_prio = QCheckBox("Dejar libre el PC (puedes seguir usándolo mientras exporta; tarda algo más)")
        self.low_prio.setToolTip("La exportación va en prioridad baja y con la mitad de trozos a la vez: lo que estés "
                                 "usando (otro programa, un juego o el propio editor) va primero y no da tirones.")
        self.low_prio.setChecked(str(QSettings("EditorIA", "EditorIA").value("exportar/prioridad_baja", "false"))
                                 == "true")
        self.low_prio.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "exportar/prioridad_baja", "true" if on else "false"))
        form2.addRow("Mientras exporta", self.low_prio)
        form2.addRow("Guardar en", out_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        self.status = QLabel(f"Duración del video: {fmt_time(p.duration())}")
        self.status.setObjectName("dim")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setVisible(False)
        self.log_view.setFixedHeight(140)

        self.btn_export = QPushButton("Exportar")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._start)
        self.btn_queue = QPushButton("➕ Añadir a la cola")
        self.btn_queue.setToolTip("Guarda esta exportación (con el proyecto tal como está ahora) para hacer varias "
                                  "seguidas desde Archivo → 🚀 Cola de exportación.")
        self.btn_queue.clicked.connect(self._enqueue)
        self.btn_queue.setVisible(hasattr(parent, "render_queue"))
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self._close_or_cancel)
        self.btn_open = QPushButton("Abrir carpeta")
        self.btn_open.setVisible(False)
        self.btn_open.clicked.connect(self._reveal)
        # 🖼 Mientras exporta: ir a hacer la miniatura (el diálogo se esconde y vuelve al terminar)
        self.btn_mini = QPushButton("🖼 Ir a Miniatura mientras exporta")
        self.btn_mini.setToolTip("Sigue exportando en segundo plano (el avance sale abajo, en la barra de estado) y "
                                 "vuelve aquí al terminar")
        self.btn_mini.setVisible(False)
        self.btn_mini.clicked.connect(self._a_miniatura)
        self._oculto = False
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_open)
        buttons.addWidget(self.btn_mini)
        buttons.addStretch()
        buttons.addWidget(self.btn_close)
        buttons.addWidget(self.btn_queue)
        buttons.addWidget(self.btn_export)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>¿Para dónde es?</b>"))
        lay.addLayout(trow)
        lay.addWidget(self.target_info)
        lay.addWidget(self.advanced)
        lay.addLayout(form2)
        lay.addSpacing(8)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.log_view)
        lay.addLayout(buttons)

        # Preset inicial según la resolución del proyecto
        match = next((name for name, (w, h, _b) in PRESETS.items() if (w, h) == (p.width, p.height)),
                     "YouTube 1080p")
        self.preset.setCurrentText(match)
        self._apply_preset(match)
        # 📱 Proyecto vertical (Shorts, Edits): «▯ Vertical» elegido solo. Si no, el último destino que usaste (sin
        # quedarse en «Vertical» con un video horizontal)
        vertical = p.height > p.width               # (el último destino, recordado aparte para vertical y horizontal)
        clave = "exportar/destino_vertical" if vertical else "exportar/destino_horizontal"
        last = str(st.value(clave, "tiktok" if vertical else str(st.value("exportar/destino", "youtube"))))
        if last not in TARGETS and last != "custom" or (last == "tiktok" and not vertical):
            last = "tiktok" if vertical else "youtube"
        self._clave_destino = clave
        self._apply_target(last)

    def _apply_target(self, key: str):
        """Un destino: pone tamaño, 60 FPS (o los del proyecto), códec, bitrate y el nombre del archivo."""
        self.target = key
        for b in self.targets.buttons():
            b.setChecked(b.property("target") == key)
        QSettings("EditorIA", "EditorIA").setValue("exportar/destino", key)
        if getattr(self, "_clave_destino", None):
            QSettings("EditorIA", "EditorIA").setValue(self._clave_destino, key)
        custom = key not in TARGETS
        self.advanced.setVisible(custom)
        if custom:
            self.target_info.setText("Elige tú la resolución, los FPS, el códec y la calidad.")
            self.adjustSize()
            return
        p = self.ctrl.project
        w, h = target_size(key, p.width, p.height)
        self.preset.blockSignals(True)
        self.preset.setCurrentText("Personalizado")
        self.preset.blockSignals(False)
        if hasattr(self, "btn_del_preset"):
            self.btn_del_preset.setEnabled(False)
        self.width_box.setValue(w)
        self.height_box.setValue(h)
        fps = f"{p.fps:g}" if f"{p.fps:g}" in ("24", "25", "30", "50", "60") else "60"
        self.fps.setCurrentText(fps)
        self.codec.setCurrentIndex(self.codec.findData("h264"))
        br = target_bitrate(key, w, h)
        self.bitrate.setValue(br)
        t = TARGETS[key]
        self.target_info.setText(t["info"].format(w=w, h=h, fps=fps, br=f"{br:g}"))
        folder = os.path.dirname(self.out.text()) or _default_export_dir()
        name = p.name + (f" - {t['suffix']}" if t["suffix"] else "")
        self.out.setText(os.path.join(folder, f"{name}.mp4"))
        self.adjustSize()

    # ------------------------------------------------------------ ★ tus presets (como Shotcut)
    @staticmethod
    def _user_presets() -> dict:
        import json
        try:
            d = json.loads(QSettings("EditorIA", "EditorIA").value("exportar/mis_presets", "{}") or "{}")
            return d if isinstance(d, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _fill_presets(self, select: str | None = None):
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(list(PRESETS))
        for name in self._user_presets():
            if str(name).strip():
                self.preset.addItem("★ " + str(name))
        self.preset.addItem("Personalizado")
        if select:
            self.preset.setCurrentText(select)
        self.preset.blockSignals(False)
        if hasattr(self, "btn_del_preset"):
            self.btn_del_preset.setEnabled(self.preset.currentText().startswith("★ "))

    def save_preset(self, name: str | None = None) -> bool:
        import json
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Guardar preset", "Nombre (p. ej. «Mis reseñas 1440p»):")
            if not ok:
                return False
        name = (name or "").strip()
        while name.startswith("★"):
            name = name[1:].strip()
        name = name[:60]
        if not name:
            return False
        d = self._user_presets()
        d[name] = {"w": self.width_box.value(), "h": self.height_box.value(), "fps": self.fps.currentText(),
                   "codec": self.codec.currentData(), "encoder": self.encoder.currentData(),
                   "bitrate": self.bitrate.value(), "max_q": self.max_q.isChecked(),
                   "low_prio": self.low_prio.isChecked()}
        if self.subs.isEnabled():                 # (sin subtítulos en el proyecto no se guarda «apagados»)
            d[name]["subs"] = self.subs.isChecked()
        QSettings("EditorIA", "EditorIA").setValue("exportar/mis_presets", json.dumps(d, ensure_ascii=False))
        self._fill_presets("★ " + name)
        self.status.setText(f"★ Preset «{name}» guardado.") if hasattr(self, "status") else None
        return True

    def delete_preset(self) -> bool:
        import json
        cur = self.preset.currentText()
        if not cur.startswith("★ "):
            return False
        d = self._user_presets()
        d.pop(cur[2:], None)
        QSettings("EditorIA", "EditorIA").setValue("exportar/mis_presets", json.dumps(d, ensure_ascii=False))
        self._fill_presets("Personalizado")
        return True

    def _apply_preset(self, name):
        if hasattr(self, "btn_del_preset"):
            self.btn_del_preset.setEnabled(name.startswith("★ "))
        if name in PRESETS:
            w, h, br = PRESETS[name]
            self.width_box.setValue(w)
            self.height_box.setValue(h)
            self.bitrate.setValue(br)
        elif name.startswith("★ "):
            d = self._user_presets().get(name[2:])
            if not isinstance(d, dict):
                return
            try:
                self.width_box.setValue(int(d.get("w", self.width_box.value())))
                self.height_box.setValue(int(d.get("h", self.height_box.value())))
                if str(d.get("fps")) in [self.fps.itemText(i) for i in range(self.fps.count())]:
                    self.fps.setCurrentText(str(d["fps"]))
                for box, key in ((self.codec, "codec"), (self.encoder, "encoder")):
                    i = box.findData(d.get(key))
                    if i >= 0:
                        box.setCurrentIndex(i)
                import math
                br = float(d.get("bitrate", self.bitrate.value()))
                if math.isfinite(br):
                    self.bitrate.setValue(br)
                for attr, key in (("subs", "subs"), ("max_q", "max_q"), ("low_prio", "low_prio")):
                    box = getattr(self, attr, None)
                    if box is not None and key in d and box.isEnabled():
                        box.setChecked(bool(d[key]))
            except (TypeError, ValueError, OverflowError):
                pass

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar video", self.out.text(), "Video MP4 (*.mp4)")
        if path:
            self.out.setText(path)

    def _options(self) -> ExportOptions:
        path = self.out.text().strip()
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        return ExportOptions(path=path, width=self.width_box.value() // 2 * 2,
                             height=self.height_box.value() // 2 * 2, fps=float(self.fps.currentText()),
                             codec=self.codec.currentData(), encoder=self.encoder.currentData(),
                             bitrate_mbps=self.bitrate.value(), subtitles=self.subs.isChecked(),
                             target=self.target, max_quality=self.max_q.isChecked(),
                             low_priority=self.low_prio.isChecked())

    def _enqueue(self):
        win = self.parent()
        opts = self._options()
        rng = self.ctrl.project.marked_range() if self.only_marked.isChecked() else None
        name = self.preset.currentText() + (" · tramo" if rng else "")
        win.render_queue.add(self.ctrl.project, opts, name, rng)
        self.status.setText(f"✓ Añadido a la cola ({len(win.render_queue.jobs)}). Archivo → 🚀 Cola de exportación.")
        win.open_queue()

    def _start(self):
        opts = self._options()
        os.makedirs(os.path.dirname(opts.path) or ".", exist_ok=True)
        if os.path.exists(opts.path):
            r = QMessageBox.question(self, "Sobrescribir", f"Ya existe:\n{opts.path}\n\n¿Reemplazarlo?")
            if r != QMessageBox.Yes:
                return
        QSettings("EditorIA", "EditorIA").setValue("exportar/carpeta", os.path.dirname(opts.path))
        self._retried_cpu = False
        self._run(opts)

    def _run(self, opts):
        script = os.path.join(str(_temp_dir()), "editoria_export_filtro.txt")
        try:
            # una COPIA del proyecto tal como está al pulsar Exportar: si mientras tanto cambias de pestaña o editas
            # (con «🖼 Ir a Miniatura»), lo que se exporta no se mezcla; el reintento con el procesador usa la misma
            import copy
            base = getattr(self, "_reintento_base", None) or copy.deepcopy(self.ctrl.project)
            self._reintento_base = None
            self._proyecto = base
            project = base
            rng = project.marked_range() if self.only_marked.isChecked() else None
            cues = None
            if rng:
                from ..core.project_tools import slice_project
                project = slice_project(project, *rng)
                if opts.subtitles and base.subtitles.enabled:   # las frases del video entero, desde la marca I
                    from ..core.subtitles import shift_cues, styled_cues
                    cues = shift_cues(styled_cues(base), *rng)
            # Se escribe en «<nombre>.parcial.mp4»: solo si sale bien pasa a llamarse como pediste (cancelar o un
            # fallo no deja un video roto con el nombre final ni destruye el que había al elegir «Reemplazar»)
            from dataclasses import replace

            from ..export.ffmpeg_export import partial_path
            work = replace(opts, path=partial_path(opts.path))
            # (raster=False: los subtítulos Neón / palabra a palabra se dibujan luego, en segundo plano)
            args, self.total = build_command(project, work, media_tools.ffmpeg(), script, cues=cues, raster=False)
        except (ValueError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "No se puede exportar", str(exc))
            return
        self._opts = opts               # (la ruta FINAL: la que se enseña al terminar)
        self._partial = work.path
        from . import export_runner as _er
        _er.track_partial(work.path)    # (si Reclaimer se cierra de golpe, se borra al arrancar)
        self._log = []
        self.log_view.clear()
        self.log_view.setVisible(False)
        self.btn_open.setVisible(False)
        from . import export_runner
        # Más rápido: por trozos a la vez (cortando por los cortes del montaje); si no se puede, de una vez
        self.proc = export_runner.make(project, work, self, cues=cues)
        parallel = self.proc is not None
        self._script = script
        if not parallel:
            self.proc = export_runner.make_single(project, work, script, self, cues=cues)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self._t0 = time.time()
        export_runner.start(self.proc, args, work)
        self.btn_export.setEnabled(False)
        self.btn_close.setText("Cancelar")
        self.btn_mini.setVisible(hasattr(self.parent(), "go_page"))
        self.status.setText(f"Exportando en {self.proc.n} trozos a la vez…" if parallel else "Exportando…")

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    secs = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                frac = min(1.0, secs / self.total) if self.total else 0
                self.progress.setValue(int(frac * 1000))
                self.progress.setFormat(f"{frac * 100:.0f} %")
                elapsed = time.time() - self._t0
                if frac > 0.02:
                    left = elapsed / frac - elapsed
                    self.status.setText(f"Exportando… {fmt_time(secs, False)} de {fmt_time(self.total, False)}"
                                        f" · quedan ~{int(left)} s")
                    if self._oculto and self.parent() is not None:      # (en Miniatura: el avance, abajo)
                        self.parent().statusBar().showMessage(f"⬆ {frac * 100:.0f} % · " + self.status.text(), 5000)
            elif not line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=",
                                      "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=")):
                self._log.append(line)
                self._log = self._log[-80:]

    def _finished(self, code, _status):
        self.btn_export.setEnabled(True)
        self.btn_close.setText("Cerrar")
        self.btn_mini.setVisible(False)
        proc, self.proc = self.proc, None
        subs_failed = bool(getattr(proc, "subs_failed", False))     # (falló el dibujo de los subtítulos, no FFmpeg)
        if proc is not None:
            proc.deleteLater()
        from .export_runner import discard_partial, finish_partial, looks_like_encoder_failure
        partial = getattr(self, "_partial", "")
        if code == 0 and self._cancelled:
            code = 1                              # (cancelaste: no se da por bueno aunque FFmpeg acabara justo)
        if code == 0 and not finish_partial(partial, self._opts.path):
            code = 1                              # (no se pudo poner el nombre final: se cuenta como fallo)
            self._log.append(f"✗ No se pudo renombrar {partial} → {self._opts.path} (¿está abierto en otro programa?)")
        if code != 0:
            discard_partial(partial)              # (el archivo bueno de antes, si lo había, sigue intacto)
        if code == 0:
            self.progress.setValue(1000)
            self.progress.setFormat("100 %")
            self.status.setText(f"✓ Listo en {int(time.time() - self._t0)} s: {self._opts.path}")
            self.btn_open.setVisible(True)
            try:          # 📝 descripción completa (capítulos, créditos, tu pie, hashtags) junto al video
                from ..core import description as DS
                from .description_dialog import prefs
                pr = getattr(self, "_proyecto", None) or self.ctrl.project     # (el que se exportó)
                par, pie = prefs(pr, self.ctrl.path)
                texto = DS.default_text(pr, par, pie)
                if texto.strip():
                    ruta = os.path.splitext(self._opts.path)[0] + ".descripcion.txt"
                    with open(ruta, "w", encoding="utf-8") as f:
                        f.write(texto + "\n")
                    self.status.setText(self.status.text() + f"\n📝 Descripción para YouTube: "
                                                             f"{os.path.basename(ruta)}")
            except Exception:  # noqa: BLE001 - la descripción nunca estropea una exportación
                pass
        elif self._cancelled:
            self.status.setText("Exportación cancelada.")
        elif (self._opts.encoder == "gpu" and not self._retried_cpu and not subs_failed
              and looks_like_encoder_failure(self._log)):     # (disco lleno o archivo que falta: no se reintenta)
            # La tarjeta gráfica falló (driver, tamaño raro…): se reintenta sola con el procesador
            from dataclasses import replace
            self._retried_cpu = True
            self._reintento_base = getattr(self, "_proyecto", None)      # (el mismo proyecto, no el de ahora)
            self._run(replace(self._opts, encoder="cpu"))
            self.status.setText("La tarjeta gráfica no pudo; exportando con el procesador (más lento, muy seguro)…")
            return
        else:
            self.status.setText("✗ La exportación falló. Detalles:")
            self.log_view.setPlainText("\n".join(self._log))
            self.log_view.setVisible(True)
            if self._opts.encoder == "gpu":
                self.status.setText("✗ La exportación falló. Prueba con «Codificar con: Procesador». Detalles:")
        self._cancelled = False
        from . import export_runner
        export_runner.cleanup(getattr(self, "_script", ""))      # (las imágenes de los subtítulos, fuera)
        if self._oculto:                          # (estabas en Miniatura: vuelve con el resultado, sin robar el foco)
            self._oculto = False
            self.show()
            self.raise_()
            win = self.parent()
            if win is not None and hasattr(win, "statusBar"):
                win.statusBar().showMessage("⬆ " + self.status.text().splitlines()[0], 8000)

    _cancelled = False

    def exportando(self) -> bool:
        return self.proc is not None

    def reject(self):
        """Esc / cerrar con la exportación en marcha: se esconde y sigue (vuelve al terminar); sin exportar, se cierra."""
        if self.proc is not None:
            self._oculto = True
            self.hide()
            win = self.parent()
            if win is not None and hasattr(win, "statusBar"):
                win.statusBar().showMessage("⬆ Sigue exportando; al terminar vuelve la ventana de exportar.", 8000)
            return
        super().reject()

    def abort_for_exit(self, ms: int = 3000):
        """Al cerrar el programa: para la exportación, espera un momento y borra el archivo a medias y los temporales
        (el aviso de «terminado» ya no llega: el programa se está cerrando)."""
        from . import export_runner
        proc = self.proc
        self._cerrando_app = True
        self._oculto = False
        self._cancelled = True
        if proc is not None:
            try:
                proc.kill()
                proc.waitForFinished(ms)
            except RuntimeError:
                pass
        export_runner.cleanup(getattr(self, "_script", ""))
        export_runner.discard_partial(getattr(self, "_partial", ""))

    def _a_miniatura(self):
        """🖼 Esconde el diálogo (la exportación sigue: FFmpeg va aparte) y abre la página Miniatura."""
        win = self.parent()
        self._oculto = True
        self.hide()
        if win is not None and hasattr(win, "go_page"):
            win.go_page("thumb")
            win.statusBar().showMessage("⬆ " + self.status.text() + " — al terminar vuelve la ventana de exportar.",
                                        8000)

    def _close_or_cancel(self):
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()
        else:
            self.accept()

    def _reveal(self):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(self._opts.path)])

    def closeEvent(self, e):
        if self.proc is not None and not getattr(self, "_cerrando_app", False):
            e.ignore()                           # (la X, como Esc: sigue exportando escondida; «Cancelar» la para)
            self.reject()
            return
        if self.proc is not None:
            self.abort_for_exit()
        super().closeEvent(e)
