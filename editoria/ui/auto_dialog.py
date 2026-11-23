"""
Ventana «✨ Primera versión automática»: de la narración a un video casi terminado, sin
estar delante de la pantalla. Ejecuta, uno detrás de otro:

  1. Poner la narración en la timeline        6. Colocar el B-roll a tu ritmo
  2. Transcribir y analizar la voz            7. Zooms en los momentos clave
  3. Limpiar la voz (silencios, muletillas…)   8. Toques de cine (zoom lento, transiciones)
  4. Analizar los clips (qué se ve)            9. Audio (tu EQ, mejorar voz, música, -14 LUFS)
  5. Detectar los temas                       10. Subtítulos y 11. Revisión final

Todo queda en la timeline como clips normales y se deshace entero con un Ctrl+Z.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from ..ai import broll_selection, clip_analysis, first_version, topic_detection, transcription, voice_cleanup
from ..ai import toques_finales as TF
from ..ai.audit import run_audit, summary
from ..ai.base import Cancelled
from ..core import equalizer, mapping, subtitles
from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, ORIGIN_AI, TRACK_AUDIO, TRACK_VIDEO
from ..core.subtitles import PRESETS as SUB_PRESETS
from . import help as help_ui
from .common import fmt_time
from .jobs import BackgroundJob
from .quick_review import pending_suggestions

SR = 16000

# Tipo de edición → (ritmo, material, estilo) por defecto
EDIT_TYPES = [
    ("comentario", "Comentario / crítica", ("normal", "mix", "dynamic")),
    ("review", "Review / análisis", ("normal", "mix", "natural")),
    ("ensayo", "Ensayo / documental", ("slow", "mix", "cinematic")),
    ("gameplay", "Gameplay comentado", ("normal", "gameplay", "natural")),
    ("short", "Short", ("fast", "mix", "dynamic")),
    ("largo", "Video largo", ("normal", "mix", "natural")),
    ("cinematico", "Cinemático", ("slow", "cinematics", "cinematic")),
    ("custom", "Personalizado", None),
]
PACES = [("fast", "Rápido (planos más cortos)", 0.75), ("normal", "Normal", 1.0),
         ("slow", "Pausado (planos largos)", 1.6)]
MATERIALS = [("mix", "Mezclar automáticamente (la IA decide por lo que dices)", []),
             ("gameplay", "Priorizar gameplay", ["Gameplay"]),
             ("cinematics", "Priorizar cinemáticas", ["Cinemáticas"]),
             ("images", "Priorizar imágenes", ["Imágenes"])]
STYLES = [("natural", "Natural — limpio y discreto"),
          ("dynamic", "Dinámico — más cambios y zooms de golpe"),
          ("cinematic", "Cinematográfico — zoom lento, transiciones con whoosh, cortes a ritmo de la música"),
          ("custom", "Personalizado — tú eliges abajo")]

STEPS = [
    ("place", "Poner la narración en la timeline"),
    ("transcribe", "Transcribir y analizar la voz"),
    ("clean", "Limpiar la voz (silencios, muletillas, repeticiones)"),
    ("clips", "Entender tus clips a fondo (quién y qué aparece)"),
    ("topics", "Detectar los temas"),
    ("broll", "Colocar el B-roll"),
    ("zooms", "Zooms en los momentos clave"),
    ("cinema", "Toques de cine (zoom lento, transiciones)"),
    ("audio", "Audio: tu ecualizador, mejorar la voz, música"),
    ("subs", "Subtítulos"),
    ("audit", "Revisión final"),
]


class AutoDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.ctrl = win.ctrl
        self.settings = QSettings("EditorIA", "EditorIA")
        self.job: BackgroundJob | None = None
        self.cancelled = False
        self.running = False
        self.report: list[str] = []
        self.issues: list[dict] = []
        self.setWindowTitle("✨ Primera versión automática")
        self.resize(600, 720)
        help_ui.set_help(self, "primera_version")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.narr = QComboBox()
        form.addRow("Narración", self.narr)
        self.music = QComboBox()
        form.addRow("Música de fondo", self.music)

        def combo(items, key, default):
            cb = QComboBox()
            for k, label, *_rest in items:
                cb.addItem(label, k)
            cb.setCurrentIndex(max(0, cb.findData(self.settings.value(key, default))))
            return cb
        short = self.ctrl.project.format in ("short", "edit")
        self.etype = combo(EDIT_TYPES, "auto/tipo", "short" if short else "comentario")
        self.pace = combo(PACES, "auto/ritmo", "fast" if short else "normal")
        self.material = combo(MATERIALS, "auto/material", "mix")
        self.style = combo(STYLES, "auto/estilo", "dynamic")
        self.etype.currentIndexChanged.connect(self._apply_type)
        form.addRow("Tipo de edición", self.etype)
        form.addRow("Ritmo", self.pace)
        form.addRow("Material", self.material)
        form.addRow("Estilo visual", self.style)
        cuts = QHBoxLayout()
        self.cut_opts: dict[str, QCheckBox] = {}
        for key, label, tip in (("silence", "Silencios", "Silencios largos (deja una pausa natural)"),
                                ("noise", "Respiraciones", "Respiraciones y ruidos entre frases"),
                                ("filler", "Muletillas", "«eh», «este», «o sea»…"),
                                ("repeat", "Repeticiones y tomas", "Palabras repetidas y tomas repetidas (se queda la última)")):
            cb = QCheckBox(label)
            cb.setToolTip(tip + ". Nunca se corta una palabra a medias.")
            cb.setChecked(bool(self.settings.value(f"auto/corte_{key}", True, type=bool)))
            self.cut_opts[key] = cb
            cuts.addWidget(cb)
        form.addRow("Quitar", cuts)
        lay.addLayout(form)

        self.opts: dict[str, QCheckBox] = {}
        short = self.ctrl.project.format in ("short", "edit")
        # 🎙 ¿Transcribir? No siempre: a veces el audio del video no es tu voz (gameplay, cinemáticas…)
        self.do_tr = QCheckBox("🎙 Transcribir la voz (apágalo si el audio no es tu voz)")
        self.do_tr.setToolTip("Sin transcribir no se puede: limpiar la voz, temas, B-roll según lo que dices, zooms "
                              "al decir «miren» ni subtítulos. Lo demás sí se hace.")
        self.do_tr.setChecked(bool(self.settings.value("auto/transcribe", True, type=bool)))
        lay.addWidget(self.do_tr)
        from ..core import intro_outro as _io
        for key, label, on in (
                ("clean", "Limpiar la voz (lo marcado en «Quitar»)", True),
                ("broll", "Colocar B-roll que encaje con lo que dices", True),
                ("zooms", "Zooms rápidos cuando dices «miren», «fíjense»… (a la cara si la hay)", True),
                ("cinema", "Toques de cine: zoom lento en los planos largos y fundido breve al cambiar de tema",
                 True),
                ("eq", "Aplicar tu ecualizador «Mi voz» y mejorar la voz", True),
                ("subs", "Subtítulos dentro del video" + (" (a lo mucho 3 palabras, letra grande)" if short else ""), short),
                ("audit", "Revisión final (pantallas negras, audio, planos largos…)", True),
                ("intro", "Poner mi intro y outro al final (las que elegiste en «🎬 Mi intro y mi outro»)",
                 _io.configured(self.ctrl.project.format))):
            cb = QCheckBox(label)
            cb.setChecked(bool(self.settings.value(f"auto/{key}", on, type=bool)))
            self.opts[key] = cb
            lay.addWidget(cb)

        self.do_tr.toggled.connect(self._tr_toggled)
        self._tr_toggled(self.do_tr.isChecked())
        self._style_hints()
        lay.addWidget(QLabel("Pasos:"))
        self.steps = QListWidget()
        self.steps.setSelectionMode(QListWidget.NoSelection)
        for _key, label in STEPS:
            self.steps.addItem(QListWidgetItem("○   " + label))
        lay.addWidget(self.steps, 1)
        self.status = QLabel("Elige la narración y pulsa «Empezar». Puedes irte: cuando vuelvas estará listo.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        btns = QHBoxLayout()
        self.btn_audit = QPushButton("⚕ Ver la revisión")
        self.btn_audit.hide()
        self.btn_audit.clicked.connect(self._open_audit)
        btns.addWidget(self.btn_audit)
        self.btn_review = QPushButton("⚡ Revisar rápido con teclas…")
        self.btn_review.setToolTip("Recorre una a una lo que la IA dejó pendiente y los cortes dudosos (Ctrl+Shift+Q)")
        self.btn_review.hide()
        self.btn_review.clicked.connect(self._open_review)
        btns.addWidget(self.btn_review)
        btns.addStretch(1)
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self._close_or_cancel)
        self.btn_go = QPushButton("✨  Empezar")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self.start)
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_go)
        lay.addLayout(btns)
        self._fill()

    # ------------------------------------------------------------ opciones
    def _fill(self):
        p = self.ctrl.project
        cands = [m for m in p.media.values() if m.id not in self.ctrl.missing and
                 (m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio))]

        def is_music(m):
            return any(w in (m.category + " " + m.name).lower() for w in ("músic", "music", "song", "canción"))

        def score(m):  # la narración: transcrita, en audio, no música, la más larga
            return (m.id in p.transcripts, m.kind == KIND_AUDIO, not is_music(m), m.duration)
        for m in sorted(cands, key=score, reverse=True):
            self.narr.addItem(f"{m.name}  ({fmt_time(m.duration)})", m.id)
        self.music.addItem("Sin música", None)
        for m in sorted((m for m in cands if m.kind == KIND_AUDIO), key=lambda m: (not is_music(m), m.name)):
            self.music.addItem(f"{m.name}  ({fmt_time(m.duration)})", m.id)
        if not cands:
            self.status.setText("Primero importa tu narración (y tus clips) en el panel de medios.")
            self.btn_go.setEnabled(False)

    def _apply_type(self, _i=0):
        """El tipo de edición propone un ritmo, un material y un estilo (todo se puede cambiar)."""
        preset = dict((k, v) for k, _l, v in EDIT_TYPES).get(self.etype.currentData())
        if not preset:
            return
        pace, material, style = preset
        for cb, val in ((self.pace, pace), (self.material, material), (self.style, style)):
            cb.setCurrentIndex(max(0, cb.findData(val)))

    def _style_hints(self):
        """◈ Si el aprendizaje está activado, preselecciona según tus preferencias ACEPTADAS (puedes cambiarlo)."""
        from ..ai import style_learning as SL
        L = getattr(self.win, "learner", None)
        if L is None or not L.enabled:
            return
        kind = self.ctrl.project.format if self.ctrl.project.format in SL.KINDS else "youtube"
        self.style_reasons = []
        for h in SL.hints(L.data, kind):
            s, v = h["setting"], h["value"]
            if s == "ritmo":
                self.pace.setCurrentIndex(max(0, self.pace.findData(v)))
            elif s == "estilo":
                self.style.setCurrentIndex(max(0, self.style.findData(v)))
            elif s == "corte_silence":
                self.cut_opts["silence"].setChecked(bool(v))
            elif s == "zooms":
                self.opts["zooms"].setChecked(bool(v))
            elif s == "musica":
                self.music.setCurrentIndex(0)
            else:
                continue
            self.style_reasons.append(h["reason"])
        if self.style_reasons:
            row = QHBoxLayout()
            lb = QLabel(f"◈ Ajustado a tu estilo ({len(self.style_reasons)} cosas). Puedes cambiar lo que quieras.")
            lb.setWordWrap(True)
            b = QPushButton("Ver razonamiento")
            b.setObjectName("flat")
            b.clicked.connect(lambda: QMessageBox.information(
                self, "¿Por qué?", "\n".join("• " + r for r in self.style_reasons)))
            row.addWidget(lb, 1)
            row.addWidget(b)
            self.layout().addLayout(row)

    def _style(self) -> str:
        return self.style.currentData() or "custom"

    def _opt(self, key: str) -> bool:
        return self.opts[key].isChecked() if key in self.opts else True

    # ------------------------------------------------------------ ejecución
    def start(self):
        self.mid = self.narr.currentData()
        if not self.mid:
            return
        if self.music.currentData() == self.mid:
            QMessageBox.information(self, "Primera versión", "La música no puede ser la misma narración.")
            return
        for key, cb in self.opts.items():
            self.settings.setValue(f"auto/{key}", cb.isChecked())
            cb.setEnabled(False)
        for key, cb in self.cut_opts.items():
            self.settings.setValue(f"auto/corte_{key}", cb.isChecked())
            cb.setEnabled(False)
        for key, cb in (("tipo", self.etype), ("ritmo", self.pace), ("material", self.material), ("estilo", self.style)):
            self.settings.setValue(f"auto/{key}", cb.currentData())
            cb.setEnabled(False)
        self.narr.setEnabled(False)
        self.music.setEnabled(False)
        self.btn_go.setEnabled(False)
        self.btn_close.setText("Cancelar")
        self.running = True
        self.t0 = time.time()
        self.win.engine.pause()
        self.ctrl.undo_stack.beginMacro("✨ Primera versión automática")
        self._run(0)

    # Cada paso termina llamando a _next (hecho), _skip (omitido) o _fail (falló)
    def _run(self, idx: int):
        self.i = idx
        if self.cancelled:
            return self._finish("Cancelado. Lo que ya se hizo se deshace con Ctrl+Z.")
        if idx >= len(STEPS):
            return self._finish()
        if not self.do_tr.isChecked() and STEPS[idx][0] in self.NEEDS_VOICE:
            self.i = idx
            self._skip("sin transcribir (lo apagaste)")
            return
        self._mark(idx, "⏳")
        self.bar.setValue(int(1000 * idx / len(STEPS)))
        try:
            getattr(self, "_step_" + STEPS[idx][0])()
        except Exception as exc:  # noqa: BLE001 - un paso que falla no rompe los demás
            self._fail(str(exc))

    NEEDS_VOICE = ("transcribe", "clean", "topics", "broll", "zooms", "subs")

    def _tr_toggled(self, on: bool):
        """Sin transcribir: lo que depende de tu voz, en gris (no se hará)."""
        self.settings.setValue("auto/transcribe", on)
        for key in ("clean", "broll", "zooms", "subs"):
            if key in self.opts:
                self.opts[key].setEnabled(on)

    def _next(self, note: str = ""):
        self._mark(self.i, "✓", note)
        QTimer.singleShot(0, lambda: self._run(self.i + 1))

    def _skip(self, why: str = "omitido"):
        self._mark(self.i, "–", why)
        QTimer.singleShot(0, lambda: self._run(self.i + 1))

    def _fail(self, msg: str):
        if self.cancelled:
            return self._finish("Cancelado. Lo que ya se hizo se deshace con Ctrl+Z.")
        self._mark(self.i, "✗", msg[:120])
        self.report.append(f"✗ {STEPS[self.i][1]}: {msg}")
        if STEPS[self.i][0] in ("place", "transcribe"):   # sin narración no se puede seguir
            return self._finish("No se pudo continuar.")
        QTimer.singleShot(0, lambda: self._run(self.i + 1))

    def _mark(self, i: int, icon: str, note: str = ""):
        it = self.steps.item(i)
        it.setText(f"{icon}   {STEPS[i][1]}" + (f"  —  {note}" if note else ""))
        color = {"✓": "#57ab5a", "✗": "#e5413c", "⏳": "#e8742f", "–": "#6b7280"}.get(icon)
        if color:
            it.setForeground(QColor(color))

    def _bg(self, work, on_result, label: str):
        """Ejecuta work(progress, cancelled) en segundo plano y luego on_result(resultado)."""
        self.status.setText(label)
        self.job = BackgroundJob(work, self)
        base = self.i / len(STEPS)
        self.job.progress.connect(lambda f, t: (self.bar.setValue(int(1000 * (base + f / len(STEPS)))),
                                                self.status.setText(t)))

        def ok(res):
            self.job = None
            try:
                note = on_result(res)
            except Exception as exc:  # noqa: BLE001
                return self._fail(str(exc))
            self._next(note or "")

        def bad(msg):
            self.job = None
            self._fail(msg)

        self.job.done.connect(ok)
        self.job.failed.connect(bad)
        self.job.start()

    def _wait_then(self, cond, fn, label: str, limit: float = 600):
        """Espera (sin bloquear la ventana) a que cond() sea cierto."""
        t0 = time.time()

        def tick():
            if self.cancelled:
                return self._finish("Cancelado.")
            if cond() or time.time() - t0 > limit:
                try:
                    return fn()
                except Exception as exc:  # noqa: BLE001
                    return self._fail(str(exc))
            self.status.setText(label)
            QTimer.singleShot(300, tick)
        tick()

    # ------------------------------------------------------------ pasos
    def _narr_clips(self):
        return mapping.clips_of_media(self.ctrl.project, self.mid)

    def _step_place(self):
        def go():
            p = self.ctrl.project
            if self._narr_clips():
                return self._next("ya estaba")
            m = p.media[self.mid]
            atr = [t for t in p.tracks if t.kind == TRACK_AUDIO]
            self.ctrl.add_media([self.mid], atr[0].id if (m.kind == KIND_AUDIO and atr) else None, 0.0)
            if not self._narr_clips():
                raise RuntimeError("no se pudo colocar (¿pista bloqueada?)")
            self._next()
        self._wait_then(lambda: self.mid not in self.ctrl.analyzing, go, "Esperando a que termine de leer la narración…")

    def _step_transcribe(self):
        p = self.ctrl.project
        voice = self.win.voice
        path = p.media[self.mid].path
        opts = voice.options()
        prev = p.transcripts.get(self.mid)
        has_tr = prev is not None and prev.get("hasta") is None        # (📝 a medias: se termina aquí)
        has_sugs = any(s.media_id == self.mid and s.kind in first_version.CLEAN_KINDS for s in p.suggestions)
        if has_tr and has_sugs:
            return self._next("ya estaba")
        ok, why = transcription.is_available()
        if not has_tr and not ok:
            raise RuntimeError(why)
        model, lang = voice.model_combo.currentData(), voice.lang_combo.currentData()
        words = p.transcripts.get(self.mid, {}).get("words")

        def work(progress, cancelled):
            progress(0.0, "Leyendo el audio…")
            samples = voice.audio.get(path)
            tr = None
            w = words
            if not has_tr:
                seguir = float(prev["hasta"]) if prev is not None and prev.get("hasta") is not None else 0.0
                tr = transcription.transcribe(samples, model, lang, progress, cancelled, start_at=seguir,
                                              prev=prev if seguir else None)
                tr = voice_cleanup.refine_transcript(samples, SR, tr)
                w = tr["words"]
            progress(0.95, "Buscando silencios, muletillas y repeticiones…")
            items = voice_cleanup.analyze(samples, SR, w, opts, None, cancelled)
            return tr, items

        def done(res):
            tr, items = res
            if tr is not None:
                self.ctrl.set_transcript(self.mid, tr)
            cuttable = {k: v[1] for k, v in voice_cleanup.KINDS.items()}
            self.ctrl.set_suggestions(self.mid, items, opts.kinds(), cuttable)
            n = len(self.ctrl.project.transcripts.get(self.mid, {}).get("words", []))
            return f"{n} palabras"
        self._bg(work, done, "🎙 Transcribiendo tu voz (la primera vez descarga el modelo)…")

    def _step_clean(self):
        if not self._opt("clean"):
            return self._skip()
        p = self.ctrl.project
        before = p.duration()
        kinds = set()
        for key, cb in self.cut_opts.items():
            if cb.isChecked():
                kinds |= {"repeat", "retake"} if key == "repeat" else {key}
        ids = first_version.cleanup_ids(p.suggestions, self.mid, tuple(kinds))
        if not ids:
            return self._next("nada que quitar")
        n = self.ctrl.apply_suggestions(ids) or 0
        saved = before - self.ctrl.project.duration()
        self.report.append(f"✂ Voz: {n} cortes, {saved:.0f} s menos (se pueden restaurar en «Limpieza»).")
        self._next(f"{n} cortes · −{saved:.0f} s")

    def _step_clips(self):
        if not (self._opt("broll") or self._opt("zooms")):
            return self._skip()
        from .understand_dialog import glossary_text, snapshot, understand
        an = self.win.analyzer

        def go():
            snap = snapshot(self.ctrl)
            snap["media"] = [m for m in snap["media"] if m["media_id"] != self.mid]
            if not snap["media"]:
                return self._skip("no hay clips")
            gloss = glossary_text()
            self.status.setText("🔬 Revisando tus clips segundo a segundo…")
            self.job = BackgroundJob(lambda prog, canc, part: understand(snap, gloss, prog, canc, part, True),
                                     self, with_partial=True)
            base = self.i / len(STEPS)
            self.job.progress.connect(lambda f, t: (self.bar.setValue(int(1000 * (base + f / len(STEPS)))),
                                                    self.status.setText(t)))
            self.job.partial.connect(lambda r: self.ctrl.set_deep_analysis(*r))

            def ok(res):
                self.job = None
                self.ctrl.understanding = res
                found = [e.name for e in res["entities"] if res["index"].get(e.name)]
                if found:
                    self.report.append("🔬 Reconoce en tus clips: " + ", ".join(found[:10]) + ".")
                self._next(f"{res['n_media']} archivos · {len(found)} nombres")

            self.job.done.connect(ok)
            self.job.failed.connect(lambda msg: (setattr(self, "job", None), self._fail(msg)))
            self.job.start()
        self._wait_then(lambda: an.job is None and not self.ctrl.analyzing, go, "Esperando al análisis de clips…")

    def _step_topics(self):
        words = self.ctrl.project.transcripts.get(self.mid, {}).get("words", [])
        if len(words) < 30:
            return self._skip("narración muy corta")

        def done(segments):
            n, names = TF.poner_temas(self.ctrl, self.mid, segments)
            if names:
                self.report.append("◎ Temas: " + ", ".join(names) + ".")
            return f"{n} temas"
        self._bg(lambda prog, canc: TF.detectar_temas(words, prog, canc), done, "◎ Buscando de qué hablas en cada parte…")

    def _broll_track(self) -> str | None:
        return TF.pista_broll(self.ctrl, self.mid)

    def _step_broll(self):
        if not self._opt("broll"):
            return self._skip()
        ai = self.win.ai_panel
        clips = [c for c in ai._clip_infos() if c.media_id != self.mid]
        if not clips:
            return self._skip("no hay clips analizados")
        tid = self._broll_track()
        if tid is None:
            return self._skip("no hay pista de video libre")
        p = self.ctrl.project
        st = ai._broll_settings()
        k = dict((x[0], x[2]) for x in PACES).get(self.pace.currentData(), 1.0)
        st.min_len, st.max_len = round(st.min_len * k, 2), round(st.max_len * k, 2)
        broll_selection.floor_pace(st, p.format)          # nunca más cortes de la cuenta (mínimo por formato)
        mat = self.material.currentData()
        st.prefer = dict((x[0], x[2]) for x in MATERIALS).get(mat, [])
        st.continuous = st.continuous and mat in ("mix", "gameplay")
        st.images_overlay = True     # las imágenes van ENCIMA del B-roll (fondo desenfocado), no a pantalla completa
        words = subtitles.timeline_words(p, self.mid)
        topics = [(m.time, m.end or m.time, m.label) for m in p.markers if m.kind == "topic"]
        used: dict[str, int] = {}
        for c in p.clips.values():
            if p.track(c.track_id).kind == TRACK_VIDEO:
                used[c.media_id] = used.get(c.media_id, 0) + 1
        vol = ai.clip_vol.value() / 100
        # tramos ya usados: ningún trozo de archivo se repite en el video, ni el MISMO momento desde otro archivo
        # (🧬 huella por plano, core/repetidos.Tomados; empieza con lo que ya sale en la línea de tiempo)
        from ..core import repetidos
        taken = repetidos.Tomados(p, getattr(self.ctrl, "missing", set()))

        und = ai.understanding_for_work()

        def work(progress, cancelled):
            u = und() if callable(und) else und
            slots = broll_selection.make_slots(words, st, topics)
            return broll_selection.propose_understood(slots, clips, st, used, u, progress, cancelled, taken=taken)

        def done(slots):
            ai._show_slots(slots)   # también quedan en la pestaña IA ✨ para cambiar clips
            items = first_version.broll_items(slots, self.ctrl.project.media, taken=taken)
            created = self.ctrl.insert_ranges(items, tid, "IA · B-roll automático", origin=ORIGIN_AI,
                                              only_gaps=True, volume=vol)
            p_ = self.ctrl.project       # solo los clips de VIDEO (no sus audios vinculados)
            self.broll_ids = [i for i in (created if isinstance(created, list) else [])
                              if i in p_.clips and p_.track(p_.clips[i].track_id).kind == TRACK_VIDEO]
            named = sum(1 for s_ in slots if s_.get("entity"))
            self.report.append(f"🎬 B-roll: {len(self.broll_ids)} planos (cada {st.min_len:g}–{st.max_len:g} s); "
                               f"en {named} muestra lo que nombras.")
            # sin repetir trozos, el material puede no alcanzar: se dice cuántos segundos quedan sin imagen
            if slots:
                span = slots[-1]["end"]          # el B-roll cubre desde 0 hasta el final de la voz
                cubierto = sum(self.ctrl.project.clips[i].duration for i in self.broll_ids
                               if i in self.ctrl.project.clips)
                if span - cubierto > 3.0:
                    self.report.append(f"⚠ {span - cubierto:.0f} s de la voz sin B-roll: no hay más material "
                                       "sin repetir trozos. Añade clips a la biblioteca y vuelve a ejecutar.")
            self._place_overlays(slots, tid)
            return f"{len(self.broll_ids)} planos"
        self._bg(work, done, "🎬 Eligiendo B-roll para cada frase…")

    def _place_overlays(self, slots: list[dict], btid: str) -> int:
        """«Imágenes encima»: cada imagen elegida (broll_selection.pick_overlays) va en la pista de video justo encima
        del B-roll, con fondo desenfocado y sombra; nunca a pantalla completa."""
        picks = [(s["start"] + 0.3, s["overlay"]) for s in slots if s.get("overlay")]
        if not picks:
            return 0
        p = self.ctrl.project
        narr = {c.track_id for c in self._narr_clips()}
        bi = p.track_index(btid)
        above = [t for t in p.tracks if t.kind == TRACK_VIDEO and not t.locked and t.id not in narr
                 and p.track_index(t.id) < bi]
        if not above:                            # (proyecto nuevo con una sola pista de video: se crea «V2» encima)
            made = self.ctrl.ensure_video_above(btid) if hasattr(self.ctrl, "ensure_video_above") else None
            p = self.ctrl.project
            t_ = p.track(made) if made else None
            if t_ is None or t_.locked or t_.id in narr:
                self.report.append("🖼 Sin pista de video encima del B-roll: las imágenes no se han colocado.")
                return 0
            above = [t_]
        top = above[-1].id
        n = 0
        for t, mid in picks:
            try:
                if self.ctrl.add_image_overlay([mid], top, t):
                    n += 1
            except Exception as exc:  # noqa: BLE001 - una imagen que falla no para el resto
                self.report.append(f"✗ imagen encima: {exc}")
        if n:
            self.report.append(f"🖼 {n} {'imagen' if n == 1 else 'imágenes'} encima del B-roll "
                               "(fondo desenfocado y sombra).")
        return n

    def _step_zooms(self):
        if not self._opt("zooms"):
            return self._skip()
        plan, n_comp = TF.plan_zooms(self.ctrl, self.mid)          # (ai/toques_finales: la misma que el paso 3)
        self.n_compare = n_comp
        if not plan:
            return self._next("sin momentos" + (f" · {n_comp} comparaciones sugeridas" if n_comp else ""))

        def done(items):
            n = TF.poner_zooms(self.ctrl, items)
            msg = f"{n} zooms"
            if n_comp:
                msg += f" · {n_comp} comparaciones sugeridas"
                self.report.append(f"⧉ {n_comp} momentos para una Comparación: revísalos en IA ✨ → "
                                   "Sugerencias visuales (necesitan que elijas los dos clips).")
            return msg
        self._bg(lambda prog, canc: TF.trabajo_zooms(plan, prog, canc), done, "🔍 Preparando zooms…")

    def _step_cinema(self):
        style = self._style()
        if style == "custom" and not self._opt("cinema"):
            return self._skip()
        tid = self._broll_track()
        if not tid or not self.ctrl.project.clips_on(tid):
            return self._skip("no hay B-roll")
        linea = TF.poner_estilo(self.ctrl, style, tid, custom_cine=self._opt("cinema"))
        if linea:
            self.report.append(linea)
        self._next(f"{len(self.ctrl.project.clips_on(tid))} planos retocados" if linea else "sin cambios")

    def _step_audio(self):
        p = self.ctrl.project
        notes = []
        narr = self._narr_clips()
        if self._opt("eq") and narr:
            eq = {"on": True, "bands": [dict(b) for b in equalizer.PRESETS["Mi voz"]], "preset": "Mi voz"}
            self.ctrl.set_clip_audio([c.id for c in narr], "Ecualizador «Mi voz»", eq=eq)
            tr = p.track(narr[0].track_id)
            if tr is not None and tr.kind == TRACK_AUDIO:
                self.ctrl.set_track_props(tr.id, "Mejorar la voz", fx=dict(tr.fx, eq=True, deess=True, compress=True))
            notes.append("EQ «Mi voz»")
        music_id = self.music.currentData()
        if music_id and TF.poner_musica(self.ctrl, music_id):     # (ai/toques_finales: la misma que el paso 3)
            notes.append("música (baja sola cuando hablas)")
        TF.poner_volumen(self.ctrl)
        notes.append("volumen final −14 LUFS")
        self.report.append("🔊 Audio: " + ", ".join(notes) + ".")
        if music_id and self._broll_track():      # con música, en TODOS los estilos: los cortes van a su ritmo
            return self._snap_to_music(music_id, notes)
        self._next(", ".join(notes))

    def _snap_to_music(self, music_id: str, notes: list[str]):
        """Con música de fondo: los cortes del B-roll caen en sus golpes (mejor al empezar compás o en los fuertes)."""
        path = self.ctrl.project.media[music_id].path

        def work(progress, cancelled):
            progress(0.0, "🥁 Escuchando el ritmo de la música…")
            return TF.ritmo(path)

        def done(res):
            n = TF.cortes_a_ritmo(self.ctrl, music_id, res, self._broll_track())
            self.report.append(f"🥁 {n} cortes llevados al ritmo de la música ({res['tempo']:g} BPM).")
            return ", ".join(notes) + f" · {n} cortes a ritmo"
        self._bg(work, done, "🥁 Llevando los cortes al ritmo de la música…")

    def _step_subs(self):
        if not self._opt("subs"):
            return self._skip()
        self._next(TF.poner_subtitulos(self.ctrl, self.mid))

    def _step_audit(self):
        if not self._opt("audit"):
            return self._skip()
        issues, resumen = TF.revision(self.ctrl)
        self.issues = issues
        warn = [i for i in issues if i.get("severity") in ("error", "warning")]
        self.report.append("⚕ " + resumen)
        self.btn_audit.setVisible(bool(issues))
        self._next(f"{len(warn)} avisos" if warn else "todo bien")

    # ------------------------------------------------------------ final
    def _poner_intro_outro(self):
        """«Poner mi intro y outro» al final, dentro del mismo paso de deshacer."""
        from ..core import intro_outro as _io
        intro, outro = _io.get(self.ctrl.project.format)
        if not (intro or outro):
            return
        try:
            n = _io.place(self.ctrl, intro, outro)
        except Exception as exc:  # noqa: BLE001 - si falla, el resto de la versión queda bien
            self.report.append(f"✗ Mi intro y mi outro: {exc}")
            return
        self.report.append(f"🎬 Intro y outro: {n} pieza(s) puesta(s)." if n else
                           "🎬 Intro y outro: ya estaban puestas.")

    def _arreglar_cortes(self):
        """Los cortes dudosos (líneas rojas) se arreglan solos con su sugerencia, dentro de este mismo paso de deshacer
        (lo mismo que «✓ Aplicar todas las sugerencias» del panel de cortes, sin abrirlo)."""
        from .cut_fix import aplicar_sugerencias
        antes = self.win.timeline.refresh_cut_issues()
        try:
            hechos, quedan = aplicar_sugerencias(self.ctrl, self.win.timeline)
        except Exception as exc:  # noqa: BLE001 - si falla, la versión queda como estaba
            self.report.append(f"✗ Cortes dudosos: {exc}")
            return
        if antes:
            self.report.append(f"✂ Cortes dudosos: {antes} al principio; {hechos} ajustes automáticos; "
                               f"quedan {quedan} para revisar a mano.")

    def _finish(self, msg: str = ""):
        if not self.running:
            return
        self.running = False
        if not msg:
            self._arreglar_cortes()
        if not msg and "intro" in self.opts and self.opts["intro"].isChecked():
            self._poner_intro_outro()
        self.ctrl.undo_stack.endMacro()
        self.bar.setValue(1000 if not msg else self.bar.value())
        mins = (time.time() - self.t0) / 60
        p = self.ctrl.project
        head = msg or f"✓ Primera versión lista en {mins:.0f} min · {fmt_time(p.duration())} de video."
        # Lo que queda por decidir: propuestas pendientes (no se aplicaron) y cortes de audio dudosos (líneas rojas)
        n_sug = len(pending_suggestions(p))
        n_cut = self.win.timeline.refresh_cut_issues()
        if n_sug or n_cut:
            self.report.append(f"⚡ Por revisar: {n_sug} propuesta(s) pendiente(s) y {n_cut} corte(s) de audio dudoso(s).")
        self.btn_review.setVisible(bool(n_sug or n_cut))
        self.status.setText(head + "\n" + "\n".join(self.report) +
                            "\n\nRevísala en el visor; todo se puede cambiar, y Ctrl+Z la deshace entera.")
        self.btn_close.setText("Cerrar")
        self.btn_close.setEnabled(True)
        self.btn_go.setText("✓ Hecho" if not msg else "Detenido")
        self.win.timeline.fit()
        self.win.engine.seek(0.0)

    def _open_review(self):
        """Cierra este resumen y abre la ⚡ Revisión rápida (que no es modal, así que no puede ir debajo de este diálogo)."""
        self.accept()
        QTimer.singleShot(0, self.win.open_quick_review)

    def _open_audit(self):
        self.win.open_audit()

    def _close_or_cancel(self):
        if self.running:
            self.cancelled = True
            if self.job is not None:
                self.job.cancel()
            self.btn_close.setEnabled(False)
            self.status.setText("Cancelando…")
            return
        self.accept()

    def closeEvent(self, e):
        if self.running:
            self._close_or_cancel()
            e.ignore()
            return
        super().closeEvent(e)
