"""
«✂ Eliminar silencio» (como el de DaVinci Resolve): umbral, antes del inicio, después del final, mínimo a
eliminar y fundido cruzado. Detección «🎚 Híbrido» (por defecto: lo de «Voz precisa» y además los microsilencios que
Resolve quita por volumen, solo donde es silencio de verdad), «🎙 Voz precisa» (una IA reconoce dónde hablas y cada
borde se ajusta cada 5 ms; no se come principios ni finales de palabras ni la engaña el ruido) o «🔊 Solo volumen»
(como Resolve). Mientras mueves los controles, la línea de tiempo marca en naranja lo que se
quitará. Ajustes guardados: los del usuario (de Resolve) y los que guarde aquí.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QPushButton, QRadioButton, QSlider, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import silence as S
from ..core.model import TRACK_AUDIO, TRACK_VIDEO
from .jobs import BackgroundJob

KEY = "silencio/ajustes"
MORE_KEY = "silencio/mas_opciones"                  # ⚙ Más opciones: abierto o plegado (lo recuerda)
INFO_TIP = ("Los silencios se marcan en naranja en la línea de tiempo (en rojo, la voz que se cortaría). Si sale ⚠: "
            "prueba «🎯 Respetar las palabras», la protección «Máxima» o el modo «🎚 Híbrido».")


def _dur(s: float) -> str:
    if s >= 59.5:
        t = round(s)
        return f"{t // 60} min {t % 60} s"
    return f"{s:.1f} s"


def saved_presets() -> dict:
    try:
        own = json.loads(str(QSettings("EditorIA", "EditorIA").value(KEY, "{}")))
    except ValueError:
        own = {}
    return {**S.PRESETS, **own}


class SilenceDialog(QDialog):
    def __init__(self, win, clip_ids: list[str]):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.clip_ids = clip_ids
        self.setWindowTitle("✂ Eliminar silencio")
        self.setMinimumWidth(460)
        p = self.ctrl.project
        self.fps = p.fps
        lay = QVBoxLayout(self)
        # ¿Solo lo seleccionado o toda la pista? (con un solo trozo seleccionado, casi siempre se quiere la pista entera)
        self._sel_ids = list(clip_ids)
        tids = list(dict.fromkeys(p.clips[i].track_id for i in clip_ids if i in p.clips))
        self._track_all = [c.id for tid in tids for c in p.clips_on(tid)
                           if p.media_of(c) is not None and c.text is None
                           and (p.media_of(c).kind == "audio" or p.media_of(c).has_audio)]
        self.who = QLabel()
        self.who.setWordWrap(True)
        lay.addWidget(self.who)
        self.scope = None
        if len(self._track_all) > len(self._sel_ids):
            srow = QHBoxLayout()
            srow.addWidget(QLabel("Aplicar a"))
            self.scope = QComboBox()
            tnames = ", ".join(f"«{p.track(t).name}»" for t in tids)
            self.scope.addItem(f"Toda la pista {tnames} ({len(self._track_all)} clips)", "pista")
            self.scope.addItem(f"Solo lo seleccionado ({len(self._sel_ids)} clip"
                               f"{'s' if len(self._sel_ids) != 1 else ''})", "sel")
            self.scope.setCurrentIndex(0 if len(self._sel_ids) == 1 else 1)
            self.scope.currentIndexChanged.connect(lambda _i: self._on_scope())
            srow.addWidget(self.scope, 1)
            lay.addLayout(srow)
            if self.scope.currentData() == "pista":
                self.clip_ids = list(self._track_all)
        self._update_who()
        # ── lo esencial, arriba: los 4 controles, el fundido y el resumen
        grid = QGridLayout()
        self.ctl: dict[str, tuple[QSlider, object]] = {}
        rows = (("threshold_db", "Umbral", -60.0, 0.0, "dB", True),
                ("before", "Antes del inicio", 0, 30, "fotogramas", False),
                ("after", "Después del final", 0, 30, "fotogramas", False),
                ("min_frames", "Mínimo a eliminar", 1, 90, "fotogramas", False))
        tips = {"threshold_db": "Por debajo de este volumen se considera silencio (más bajo = solo lo muy callado). "
                                "Con «Híbrido» y «Voz precisa», además, lo que pase de este volumen y destaque del ruido se conserva "
                                "siempre (risas, gritos, golpes fuertes).",
                "before": "Silencio que se conserva antes de que vuelva a sonar (para no comerse el inicio).",
                "after": "Silencio que se conserva después de que deja de sonar (para no cortar el final).",
                "min_frames": "Los silencios más cortos que esto se respetan (pausas naturales)."}
        for r, (key, label, lo, hi, unit, is_float) in enumerate(rows):
            sl = QSlider(Qt.Horizontal)
            sl.setRange(int(lo * 10) if is_float else lo, int(hi * 10) if is_float else hi)
            if is_float:
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setDecimals(1)
                spin.setSingleStep(0.5)
            else:
                spin = QSpinBox()
                spin.setRange(lo, hi)
            spin.setKeyboardTracking(False)
            sl.setToolTip(tips[key])
            spin.setToolTip(tips[key])
            sl.valueChanged.connect(lambda v, s=spin, f=is_float: s.setValue(v / 10 if f else v))
            spin.valueChanged.connect(lambda v, s=sl, f=is_float: (s.blockSignals(True), s.setValue(int(round(v * 10))
                                      if f else int(v)), s.blockSignals(False), self._changed()))
            lab = QLabel(label)
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lab, r, 0)
            grid.addWidget(sl, r, 1)
            grid.addWidget(spin, r, 2)
            grid.addWidget(QLabel(unit), r, 3)
            self.ctl[key] = (sl, spin)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.crossfade = QCheckBox("Fundido cruzado de audio")
        self.crossfade.setToolTip("Sin «clics» en los cortes: el sonido se funde en cada uno de ellos.")
        lay.addWidget(self.crossfade)
        self.info = QLabel("Midiendo el sonido…")
        self.info.setWordWrap(True)
        self.info.setToolTip(INFO_TIP)
        lay.addWidget(self.info)

        # ── «⚙ Más opciones»: plegado por defecto (recuerda si lo dejaste abierto)
        self.more_btn = QToolButton()
        self.more_btn.setCheckable(True)
        self.more_btn.setAutoRaise(True)
        self.more_btn.setToolTip("Detección, protección de la voz, ajustes guardados, IA, palabras y qué se mueve.")
        self.more_box = QWidget()
        mb = QVBoxLayout(self.more_box)
        mb.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.more_btn)
        lay.addWidget(self.more_box)
        prow = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("Ajustes guardados…", None)
        for name in saved_presets():
            self.preset.addItem(name, name)
        self.preset.activated.connect(self._load_preset)
        b_save = QPushButton("💾 Guardar como ajuste…")
        b_save.clicked.connect(self._save_preset)
        prow.addWidget(self.preset, 1)
        prow.addWidget(b_save)
        mb.addLayout(prow)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Detección"))
        self.mode = QComboBox()
        self.mode.addItem("🎚 Híbrido (recomendado)", "hibrido")
        self.mode.addItem("🎙 Voz precisa", "voz")
        self.mode.addItem("🔊 Solo volumen (como Resolve)", "volumen")
        self.mode.setToolTip("Híbrido: todo lo de «Voz precisa» y además quita lo que Resolve quita por volumen y la IA "
                             "deja: los microsilencios entre dos palabras dichas de corrido y el seguro de los bordes de "
                             "cada frase cuando ahí ya es silencio de verdad (micro limpio). Nunca la pausa de una «p» o "
                             "«t» dentro de una palabra (con transcripción lo sabe seguro).\n"
                             "Voz precisa: una IA reconoce dónde hablas (no la engaña el ruido de fondo) y cada borde se "
                             "ajusta cada 5 ms hasta que el sonido de verdad se apaga (también las «s» y «f» suaves).\n"
                             "Solo volumen: corta todo lo que esté por debajo del umbral, como Resolve (con voz baja o "
                             "ruido de fondo se puede comer palabras).")
        self.mode.currentIndexChanged.connect(lambda _i: (self._sync_protect(), self._changed()))
        mrow.addWidget(self.mode, 1)
        mb.addLayout(mrow)
        prow2 = QHBoxLayout()
        prow2.addWidget(QLabel("🛡 Protección de la voz"))
        self.protect = QComboBox()
        self.protect.addItem("Como DaVinci (recomendado)", "davinci")
        self.protect.addItem("Máxima", "max")
        self.protect.addItem("Media", "media")
        self.protect.addItem("Solo el umbral (sin proteger)", "resolve")
        self.protect.setToolTip(
            "Solo con «🎚 Híbrido». Cuánto mandas tú con el umbral:\n"
            "· Como DaVinci: el umbral decide lo que se quita, igual que en DaVinci Resolve (moverlo se nota), y "
            "solo se protege la voz clara (donde la IA está segura de que hablas y se te oye bien).\n"
            "· Máxima: no se come voz nunca; el umbral casi no cambia nada (manda la IA).\n"
            "· Media: como Máxima, pero quita también microsilencios muy callados entre palabras.\n"
            "· Solo el umbral: el umbral decide todo, sin proteger la voz (puede comerse finales suaves).")
        self.protect.currentIndexChanged.connect(lambda _i: self._changed())
        prow2.addWidget(self.protect, 1)
        mb.addLayout(prow2)
        self.clicks = QCheckBox("🖱 Quitar clics y tics fuera de la voz")
        self.clicks.setToolTip("Golpecitos de pocos milisegundos que destacan mucho de lo que hay alrededor (ratón, "
                               "teclado…). Solo se quitan si no hay voz a menos de 60 ms (nunca se toca una «p», «t» o "
                               "«k» de tus palabras). Funciona con «🎚 Híbrido» y «🎙 Voz precisa».")
        self.clicks.setChecked(True)
        self.clicks.toggled.connect(lambda _v: self._changed())
        mb.addWidget(self.clicks)
        from ..ai import voice_model as VM
        vinfo = VM.info() if VM.available() else None
        self.voice_model = QCheckBox("◈ IA entrenada con tu voz"
                                     + (f" ({vinfo.get('minutes', 0):.0f} min)" if vinfo else " (aún sin entrenar)"))
        self.voice_model.setToolTip("Un modelo que aprendió de TUS grabaciones dónde empiezan y acaban tus palabras: "
                                    "protege lo que es palabra y quita los restos de silencio que dejan los márgenes de "
                                    "seguridad. Aprende solo cada vez que transcribes (menú Voz → Entrenar). Funciona "
                                    "con «🎚 Híbrido».")
        self.voice_model.setChecked(bool(vinfo))
        self.voice_model.setEnabled(bool(vinfo))
        self.voice_model.toggled.connect(lambda _v: self._changed())
        mb.addWidget(self.voice_model)
        from ..ai import align as _al, transcription as _tr
        ok_words = _al.available()[0] and _tr.is_available()[0] and _tr.is_downloaded("equilibrado")
        self.words_cb = QCheckBox("🎯 Respetar las palabras")
        self.words_cb.setToolTip(
            "Lo más preciso. Antes de cortar, la IA transcribe (si hace falta) y marca cada palabra con ~20 ms de "
            "precisión: nada de lo que está DENTRO de una palabra se corta, en ningún modo (tampoco «Como Resolve»: el "
            "umbral manda en pausas, respiraciones y ruido). La primera vez tarda (unos 20 s por minuto de audio); "
            "queda guardado.\n"
            "Además, la IA aprende tu voz con cada grabación.")
        self.words_cb.setChecked(ok_words and str(QSettings("EditorIA", "EditorIA").value("silencio/palabras", "true"))
                                 .lower() == "true")
        self.words_cb.setEnabled(ok_words)
        self.words_cb.toggled.connect(self._words_toggled)
        mb.addWidget(self.words_cb)
        from ..core import silence_learn as SL
        self._learned = SL.learned()
        what = SL.describe(self._learned)
        n = self._learned["n_before"] + self._learned["n_after"]
        self.learn_cb = QCheckBox("◈ Usar lo aprendido de tus retoques" + (f" ({what})" if what else " (aún no)"))
        self.learn_cb.setToolTip("Si después de cortar alargas a mano el borde de un trozo (se fue el final de una "
                                 "palabra) o lo acortas más, Reclaimer lo apunta y la siguiente vez ajusta ese margen solo "
                                 "(la mediana de lo que moviste). Partir o borrar trozos no cuenta; deshacer tu retoque, "
                                 "tampoco. Funciona con «🎚 Híbrido» y «🎙 Voz precisa».\n"
                                 f"Retoques hasta ahora: {n}" + ("" if what else
                                                                 f" (hacen falta {SL.MIN_OBS} de un mismo lado)"))
        self.learn_cb.setChecked(bool(what))
        self.learn_cb.setEnabled(bool(what))
        self.learn_cb.toggled.connect(lambda _v: self._changed())
        mb.addWidget(self.learn_cb)
        self.scope_all = QRadioButton("Mover todo lo de detrás (todas las pistas)")
        self.scope_all.setToolTip("Mover todo lo de detrás (todas las pistas: nada se desincroniza).")
        self.scope_track = QRadioButton("Solo estos clips (y su imagen o sonido vinculado)")
        self.scope_track.setToolTip("Solo en estos clips y su imagen o sonido vinculado: lo de detrás no se mueve.")
        self.scope_all.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.scope_all)
        grp.addButton(self.scope_track)
        mb.addWidget(self.scope_all)
        mb.addWidget(self.scope_track)
        qs_ui = QSettings("EditorIA", "EditorIA")
        self.more_btn.setChecked(str(qs_ui.value(MORE_KEY, "false")).lower() == "true")
        self._show_more(self.more_btn.isChecked())
        self.more_btn.toggled.connect(self._toggle_more)

        brow = QHBoxLayout()
        brow.addStretch()
        b_cancel = QPushButton("Cancelar")
        b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton("Eliminar")
        self.b_ok.setObjectName("primary")
        self.b_ok.setEnabled(False)
        self.b_ok.clicked.connect(self._apply)
        brow.addWidget(b_cancel)
        brow.addWidget(self.b_ok)
        lay.addLayout(brow)

        self.regions: list[tuple[float, float]] = []
        self._ready = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._recompute)
        self._set(self._last())
        clips = [p.clips[i] for i in dict.fromkeys(self._sel_ids + self._track_all) if i in p.clips]
        paths = list(dict.fromkeys(p.media_of(c).path for c in clips if p.media_of(c)))

        self._clips_all, self._paths = clips, paths
        self._job = None
        self._start_job()
        if hasattr(self.win, "learn_voice_pending"):      # ◈ lo apuntado al transcribir se aprende ahora, que se usa
            self.win.learn_voice_pending()

    def _show_more(self, on: bool):
        self.more_box.setVisible(bool(on))
        self.more_btn.setText("⚙ Más opciones " + ("▾" if on else "▸"))
        self.adjustSize()

    def _toggle_more(self, on: bool):
        self._show_more(on)
        QSettings("EditorIA", "EditorIA").setValue(MORE_KEY, "true" if on else "false")

    def _start_job(self):
        """1) Rápido: escuchar dónde hablas (la IA y el volumen; se guarda): en cuanto acaba, ya puedes eliminar.
        2) Con «🎯 Respetar las palabras», en el panel de tareas: transcribir (si hace falta) y afinar cada palabra; al
        terminar, la vista previa se recalcula sola, más precisa (y la IA aprende tu voz con ello)."""
        paths = self._paths

        def work(prog, _cancelled):
            for k, path in enumerate(paths):           # la voz (IA) y el volumen; se guardan para la próxima vez
                prog(k / max(1, len(paths)), "La IA está escuchando dónde hablas…")
                S.analyze(path)
                S.frame_levels(path, self.fps)
            return True

        def done(_r):
            self._ready = True
            self._recompute()
            # 🎯 a los 1,5 s y solo si la ventana sigue abierta (cargar Whisper no se puede interrumpir: si la abres y
            # la cierras enseguida, no se pone a transcribir para nada)
            QTimer.singleShot(1500, self, lambda: self._start_words() if self.isVisible() else None)
        self._ready = False
        self.b_ok.setEnabled(False)
        self.info.setText("🎙 La IA está escuchando dónde hablas… (la primera vez; luego es instantáneo)")
        self._job = BackgroundJob(work, self)
        self._job.done.connect(done)
        self._job.failed.connect(lambda m: self.info.setText("✗ " + m))
        self._job.start()

    def _words_todo(self) -> dict:
        """media_id → (ruta, palabras sin afinar o None = transcribir)."""
        from ..ai import align
        p = self.ctrl.project
        todo = {}
        if not self.words_cb.isChecked():
            return todo
        for c in self._clips_all:
            m = p.media_of(c)
            if m is None or m.id in todo or m.id in getattr(self.win, "_aligning", set()):
                continue
            tr = p.transcripts.get(m.id)
            if tr is None or not tr.get("words"):
                todo[m.id] = (m.path, None)
            elif align.needs(tr):
                todo[m.id] = (m.path, [list(w) for w in tr["words"]])
        return todo

    def _start_words(self):
        """🎯 Transcribir (si hace falta) y afinar las palabras, en el panel de tareas (no bloquea «Eliminar»)."""
        from ..ai import align
        if getattr(self, "_words_task", None) is not None:
            return
        todo = self._words_todo()
        if not todo:
            return
        steps = 2 * len(todo)

        def work(prog, cancelled):
            from ..ai import transcription as TR
            from ..core import media as media_tools
            out = {}
            try:
                for k, (mid, (path, words)) in enumerate(todo.items()):
                    if cancelled():
                        break
                    full_tr = None
                    if words is None:                   # sin transcripción: se transcribe aquí (completa)
                        prog(2 * k / steps, "🎯 Transcribiendo tu voz (para saber dónde está cada palabra)…")
                        full_tr = TR.transcribe(media_tools.decode_mono(path, 16000), "equilibrado", "es",
                                                lambda f, t, k=k: prog((2 * k + f) / steps, "🎯 " + t), cancelled)
                        words = full_tr["words"]
                    new = align.align_words(path, words, lambda f, t, k=k: prog(
                        (2 * k + 1 + f) / steps, "🎯 Afinando dónde empieza y acaba cada palabra…"), cancelled)
                    out[mid] = (full_tr, None if full_tr else words, new)
            finally:
                align.unload()
            return out

        def done(res):
            self._words_task = None
            n = 0
            for mid, (full_tr, old, new) in (res or {}).items():
                now = self.ctrl.project.transcripts.get(mid)
                if full_tr is not None:                 # transcrita aquí: se guarda completa y ya afinada
                    if now is not None and now.get("words"):
                        continue
                    self.ctrl.set_transcript(mid, align.refined(full_tr, new))
                elif now and [w[2] for w in now.get("words", [])] == [w[2] for w in old] and len(new) == len(old):
                    self.ctrl.set_transcript(mid, align.refined(now, new))
                else:
                    continue
                n += 1
                if hasattr(self.win, "learn_voice"):
                    self.win.learn_voice(mid, new)
            try:
                if n and self.isVisible():
                    self._words_note = "<br>🎯 Palabras afinadas: la vista previa ya las respeta."
                    self._recompute()
            except RuntimeError:                        # (la ventana ya se cerró: lo afinado queda guardado igual)
                pass

        def fail(_m):
            self._words_task = None
        from .task_window import manager
        self._words_task = manager().start("🎯 Afinar palabras para cortar silencios", work, done, fail)

    def _words_toggled(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue("silencio/palabras", "true" if on else "false")
        if on and self._ready:
            self._start_words()                         # (transcribe/afina lo que falte)
        self._changed()

    def _update_who(self):
        p = self.ctrl.project
        names = sorted({p.media_of(p.clips[i]).name for i in self.clip_ids if i in p.clips and p.media_of(p.clips[i])})
        self.who.setText(f"En: <b>{', '.join(names[:3])}{'…' if len(names) > 3 else ''}</b> ({len(self.clip_ids)} clips)")

    def _on_scope(self):
        self.clip_ids = list(self._track_all if self.scope.currentData() == "pista" else self._sel_ids)
        self._update_who()
        self._changed()

    # ---------------------------------------------------------------- ajustes
    def settings(self) -> dict:
        st = {k: float(spin.value()) if k == "threshold_db" else int(spin.value())
              for k, (_sl, spin) in self.ctl.items()}
        st["mode"] = self.mode.currentData()
        st["protect"] = self.protect.currentData()
        st["voice_model"] = self.voice_model.isChecked()
        st["words"] = self.words_cb.isChecked()
        if self.learn_cb.isChecked():
            st["learned"] = {"before": self._learned["before"], "after": self._learned["after"]}
        st["clicks"] = self.clicks.isChecked()
        return st

    def _set(self, st: dict):
        for k, (_sl, spin) in self.ctl.items():
            if k in st:
                spin.setValue(st[k])
        if st.get("mode") in ("hibrido", "voz", "volumen"):        # (los ajustes de Resolve no lo traen: se queda el elegido)
            self.mode.setCurrentIndex(max(0, self.mode.findData(st["mode"])))
        if "clicks" in st:
            self.clicks.setChecked(bool(st["clicks"]))
        if st.get("protect") in S.PROTECT:
            self.protect.setCurrentIndex(max(0, self.protect.findData(st["protect"])))
        self._sync_protect()

    def _sync_protect(self):
        """La protección de la voz es del modo híbrido; en «Voz precisa» manda la IA y el umbral no se usa."""
        self.protect.setEnabled(self.mode.currentData() == "hibrido")
        voz = self.mode.currentData() == "voz"
        sl, spin = self.ctl["threshold_db"]
        for w in (sl, spin):
            w.setToolTip("En «🎙 Voz precisa» decide la IA (dónde hablas): el umbral solo hace que lo que suene más fuerte "
                         "que él se conserve siempre (risas, gritos, golpes). Para que el umbral mande, «🎚 Híbrido» "
                         "con «Como DaVinci»." if voz else
                         "Por debajo de este volumen se considera silencio (más bajo = solo lo muy callado), como en "
                         "DaVinci Resolve. Con «Híbrido», lo que pase de este volumen y destaque del ruido se conserva "
                         "siempre (risas, gritos, golpes fuertes).")

    def _last(self) -> dict:
        qs = QSettings("EditorIA", "EditorIA")
        try:
            st = json.loads(str(qs.value("silencio/ultimo", "")))
        except ValueError:
            st = dict(next(iter(S.PRESETS.values())))
        # 🎚 La primera vez con el modo híbrido: lo trae puesto (hace todo lo de «Voz precisa» y más); luego, lo tuyo
        if str(qs.value("silencio/hibrido_visto", "false")).lower() != "true":
            qs.setValue("silencio/hibrido_visto", "true")
            if st.get("mode", "voz") == "voz":
                st = dict(st, mode="hibrido")
        # 🎚 «Como DaVinci» (el umbral manda): la primera vez se pone, también si venías de «Voz precisa» o «Media»
        # (ahí el umbral no cambiaba nada); luego se respeta lo que elijas
        if str(qs.value("silencio/davinci_visto", "false")).lower() != "true":
            qs.setValue("silencio/davinci_visto", "true")
            st = dict(st, mode="hibrido" if st.get("mode", "hibrido") in ("voz", "hibrido") else st.get("mode"),
                      protect="davinci")
            qs.setValue("silencio/ultimo", json.dumps(st))   # (si cierras sin eliminar, se queda igual)
        return st

    def _load_preset(self, i: int):
        name = self.preset.itemData(i)
        if name:
            self._set(saved_presets()[name])

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Guardar ajuste", "Nombre del ajuste:")
        if not ok or not name.strip():
            return
        st = QSettings("EditorIA", "EditorIA")
        try:
            own = json.loads(str(st.value(KEY, "{}")))
        except ValueError:
            own = {}
        own[name.strip()] = self.settings()
        st.setValue(KEY, json.dumps(own))
        self.preset.addItem(name.strip(), name.strip())

    # ---------------------------------------------------------------- vista previa
    def _changed(self):
        self._timer.start()

    def _recompute(self):
        if not self._ready:
            return
        p = self.ctrl.project
        clips = [p.clips[i] for i in self.clip_ids if i in p.clips]
        self.regions = S.plan(p, clips, self.fps, self.settings())
        total = sum(b - a for a, b in self.regions)
        hits = S.voice_hits(p, clips, self.regions)          # ⚠ la predicción: ¿se cortaría voz?
        # como Resolve: se oscurece solo en las pistas que se cortan (las demás llevan una marca fina en la regla)
        tracks = list(dict.fromkeys(c.track_id for c in clips))
        self.win.timeline.set_preview_regions(self.regions, hits, tracks=tracks or None)
        if self.regions:
            hv = sum(b - a for a, b in hits)
            warn = (f"<br><span style='color:#ff6b66'><b>⚠ Cortaría {hv:.1f} s de tu voz</b></span>"
                    if hv >= 0.05 else "<br>✓ Sin tocar tu voz.")
            n = len(self.regions)
            self.info.setText(f"Se quitarán <b>{n} silencio{'s' if n != 1 else ''} · {_dur(total)}</b>"
                              + warn + getattr(self, "_words_note", ""))
        else:
            self.info.setText("Con estos ajustes no hay silencios que quitar." + self._why_none(p, clips))
        self.b_ok.setEnabled(bool(self.regions))

    def _why_none(self, p, clips) -> str:
        """Por qué no se quita nada: pausas por debajo del umbral más cortas que el mínimo o que los márgenes."""
        if self.mode.currentData() == "voz":
            return ("<br>En «🎙 Voz precisa» manda la IA, no el umbral: cambia a «🎚 Híbrido» con «Como DaVinci» para "
                    "que el umbral mande.")
        try:
            st = self.settings()
            d = S.short_pauses(p, clips, self.fps, st)
        except Exception:  # noqa: BLE001 - sin explicación, el aviso de siempre
            return ""
        if not d["total"]:
            return (f"<br>Nada baja de {st['threshold_db']:.1f} dB: sube el umbral (más cerca de 0) para que cuente como "
                    "silencio lo que es más fuerte.")
        # ¿bajando el mínimo y los márgenes saldría algo? (se comprueba de verdad: si no, el consejo sería falso)
        try:
            prueba = S.plan(p, clips, self.fps, dict(st, min_frames=1, before=0, after=0, learned=None))
        except Exception:  # noqa: BLE001
            prueba = []
        if prueba:
            return (f"<br>Hay {d['total']} pausas por debajo del umbral, pero son más cortas que «Mínimo a eliminar» "
                    f"({d['min_frames']} fotogramas) o se las comen los márgenes: bajándolos se quitarían "
                    f"{len(prueba)} (las de 1–3 fotogramas suelen ser pausas entre palabras: puede sonar cortado).")
        return (f"<br>Hay {d['total']} pausas por debajo del umbral, pero están dentro de tu voz (sílabas flojas o el "
                "cierre de una «p», «t» o «k»): quitarlas se comería palabras. "
                + ("Si aun así quieres, «Solo el umbral» en la protección." if st.get("protect") != "resolve" else ""))

    def _apply(self):
        from ..core import silence_learn as SL
        st = {k: v for k, v in self.settings().items() if k != "learned"}
        QSettings("EditorIA", "EditorIA").setValue("silencio/ultimo", json.dumps(st))
        before = SL.snapshot(self.ctrl.project, self.clip_ids)
        n = self.ctrl.remove_silence(self.clip_ids, self.regions,
                                     "all" if self.scope_all.isChecked() else "track", self.crossfade.isChecked())
        if n:
            if hasattr(self.win, "track_silence_edges"):       # ◈ para aprender de tus retoques
                self.win.track_silence_edges(SL.new_edges(self.ctrl.project, before))
            if hasattr(self.win, "learn_voice_pending"):  # ◈ y lo que se afinó al cortar, también
                self.win.learn_voice_pending()
            self.accept()

    def done(self, r):
        self.win.timeline.set_preview_regions([])
        if self._job is not None and self._job.isRunning():
            self._job.wait(5000)
        t = getattr(self, "_words_task", None)
        if t is not None and getattr(t, "job", None) is not None:
            try:
                t.job.cancel()                  # al cerrar, se para (lo ya afinado no se pierde: queda guardado)
            except RuntimeError:
                pass
        super().done(r)


def targets(win) -> tuple[list[str], str]:
    """Clips a los que se aplica: los seleccionados con sonido; si no hay, la narración (o la 1ª pista de audio
    con algo). Devuelve (ids, aviso)."""
    p = win.ctrl.project
    sel = [cid for cid in win.timeline.selected if cid in p.clips]
    ok = []
    for cid in sel:
        c = p.clips[cid]
        m = p.media_of(c)
        tr = p.track(c.track_id)
        if m is None or c.text is not None:
            continue
        if m.kind == "audio" or (m.has_audio and tr.kind == TRACK_AUDIO):
            ok.append(cid)
        elif tr.kind == TRACK_VIDEO and m.has_audio:
            partners = [o.id for o in win.ctrl.partners(p, c) if p.track(o.track_id).kind == TRACK_AUDIO]
            ok.extend(partners or [cid])
    ok = list(dict.fromkeys(ok))
    if ok:
        return ok, ""
    for tr in p.tracks:
        if tr.kind == TRACK_AUDIO and p.clips_on(tr.id):
            return [c.id for c in p.clips_on(tr.id)], f"No había clips con sonido seleccionados: uso la pista «{tr.name}»."
    return [], "No hay audio en la línea de tiempo."
