"""
Barra «🎵 Edit» de la línea de tiempo (solo se ve si hay un edit musical hecho por la IA):

  👍 Funciona · 👎 No funciona — califica el edit ENTERO (el que está bajo el cabezal). Si lo retocaste a mano,
                                 cuenta tu versión (y pesa más): la IA aprende de tus cambios.
                                 👎 además VETA esos planos: ya no vuelven a salir (Remix, Mix ni edits nuevos).
                                 Con solo unos planos seleccionados, 👎 los veta y rehace ese tramo al momento.
  ⛔ Aquí no                   — como 👎 con planos seleccionados, pero SOLO para ese tramo: se cambian al momento y
                                 ya no se sugieren ahí (en otras partes del edit sí pueden salir).
  🔀 Remix                     — lo rehace entero de otra manera (otros planos, cortes, transiciones y efectos),
                                 siempre sobre el ritmo de la canción y con lo aprendido.
  🎛 Mix                       — rehace SOLO los planos que selecciones (o el tramo marcado con I / O) y te
                                 lleva al principio de ese tramo para verlo.
  👍 además COCINA el edit en un ⧉ clip compuesto (se reproduce fluido). Para Remix / Mix / 👎 se vuelve a
  separar solo (también con clic derecho → «Deshacer clip compuesto»).
Los trabajos pesados van en segundo plano (indicador naranja encima del visor).
"""
from __future__ import annotations

import random

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton

from ..core.model import KIND_VIDEO, TRACK_VIDEO


class EditBar(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("editbar")
        self.setStyleSheet("#editbar { border: 1px solid #5a4a7a; border-radius: 5px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 2, 0)
        lay.setSpacing(2)
        lay.addWidget(QLabel("🎵 Edit:"))
        self.b_like = self._btn("👍", "Este edit funciona: la IA se acerca a esto en los siguientes "
                                     "(si lo retocaste a mano, aprende de TU versión)", lambda: self.rate(1))
        self.b_dislike = self._btn("👎", "No funciona: la IA se aleja de esto y esos planos YA NO VUELVEN A SALIR.\n"
                                         "Con unos planos seleccionados: solo esos (y se cambian al momento).\n"
                                         "Ctrl+Z los vuelve a permitir.", lambda: self.rate(-1))
        self.b_not_here = self._btn("⛔ Aquí no", "Este plano no me convence EN ESTE TRAMO: se cambia al momento por "
                                                 "otro y ya no se sugiere aquí (en otras partes del edit sí puede "
                                                 "salir; para no verlo nunca más, 👎).\nSelecciona el plano (o varios) "
                                                 "del edit. Ctrl+Z lo vuelve a permitir.", self.not_here)
        self.b_remix = self._btn("🔀 Remix", "Rehacer el edit entero de otra manera (otros planos, cortes, "
                                            "transiciones y efectos), siempre al ritmo de la canción. Ctrl+Z vuelve.",
                                 self.remix)
        self.b_mix = self._btn("🎛 Mix", "Rehacer SOLO los planos seleccionados (o el tramo marcado con I / O); "
                                        "lo demás se queda igual. Ctrl+Z vuelve.", self.mix)
        for b in (self.b_like, self.b_dislike, self.b_not_here, self.b_remix, self.b_mix):
            lay.addWidget(b)
        self._busy = False
        self.ctrl.project_changed.connect(self.refresh)
        self.refresh()

    def _btn(self, text, tip, fn):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.clicked.connect(fn)
        return b

    def refresh(self):
        try:
            self.setVisible(bool(self.ctrl.project.edits))
        except RuntimeError:
            pass
        refit = getattr(self.win, "_tl_refit", None)      # (la barra de la línea de tiempo se vuelve a encajar)
        if refit is not None:
            refit()

    def _msg(self, text: str, ms: int = 9000):
        self.win.statusBar().showMessage(text, ms)

    def current(self) -> dict | None:
        rec = self.ctrl.edit_at(self.win.engine.time)
        if rec is None:
            self._msg("No hay ningún edit hecho por la IA en este proyecto (pestaña IA ✨ → «🎵 Edit musical»).")
        return rec

    # ------------------------------------------------------------------ 👍 / 👎
    def rate(self, r: int):
        from ..ai import edit_feedback
        rec = self.current()
        if rec is None:
            return
        if rec.get("style") in (None, "halo"):
            self._msg("Este edit se hizo con el estilo antiguo: crea uno con un estilo de Edits 2.0 para que aprenda.")
            return
        fp = self.ctrl.edit_fingerprint(rec)
        if fp is None:
            self._msg("Ese edit ya no tiene planos en la línea de tiempo.")
            return
        if r < 0:
            self._dislike(rec)
            return
        res = edit_feedback.record(rec["style"], fp, r, rec.get("ai_fp"))
        rec["rating"] = r
        self.ctrl._set_media_dirty()                  # se guarda con el proyecto
        what = edit_feedback.describe(edit_feedback.learned(rec["style"]))
        self._msg(("👍 Anotado: funciona" if r > 0 else "👎 Anotado: no funciona") +
                  (" (con tus cambios a mano: aprende de tu versión)" if res["manual"] else "") +
                  f". Aprendido de {res['n']} notas en este estilo" + (f": {what}." if what else ".") +
                  (" ⧉ Cocinándolo en un clip compuesto…" if r > 0 else ""), 12000)
        if r > 0:
            self._cook(rec)

    # ------------------------------------------------------------------ ⧉ cocinado
    def _compounds_in(self, rec) -> list[str]:
        p = self.ctrl.project
        a, b = rec["base"], rec["base"] + rec["duration"]
        return [c.id for c in p.clips.values() if self.ctrl.is_compound(c.id) and c.start < b - 1e-3
                and c.end > a + 1e-3]

    def _cook(self, rec):
        """👍: el edit se cocina en un ⧉ clip compuesto (planos, efectos y textos en un solo video)."""
        if self._compounds_in(rec):
            return
        p = self.ctrl.project
        ids = [c.id for c in self.ctrl.edit_clips(rec)] + [i for i in rec.get("text_ids", []) if i in p.clips]
        if ids:
            self.win.make_compound(ids)

    def _uncook(self, rec) -> bool:
        """Antes de Remix / Mix / 👎: si el edit está cocinado, se separa otra vez en sus planos."""
        for cid in self._compounds_in(rec):
            try:
                self.ctrl.break_compound(cid)
            except Exception as exc:  # noqa: BLE001 - p. ej. pista bloqueada
                self._msg(f"✗ No se pudo separar el clip compuesto: {exc}")
                return False
        return True

    def _dislike(self, rec):
        """👎: vetar los planos (los seleccionados del edit o, si no hay, todos) para que no vuelvan a salir.
        Si eran solo unos pocos, ese tramo se rehace al momento sin ellos."""
        from ..ai import edit_feedback
        if not self._uncook(rec):
            return
        clips = self.ctrl.edit_clips(rec)
        ids = {c.id for c in clips}
        sel = [i for i in self.win.timeline.selected if i in ids]
        partial = bool(sel) and len(sel) < len(ids)
        if not partial:      # el edit entero: además, la IA se aleja de este estilo de edit
            fp = self.ctrl.edit_fingerprint(rec)
            if fp is not None:
                edit_feedback.record(rec["style"], fp, -1, rec.get("ai_fp"))
            rec["rating"] = -1
        n = self.ctrl.ban_edit_clips(rec["id"], sel if partial else [c.id for c in clips])
        if not n:
            return
        if partial:
            self._msg(f"👎 {n} plano(s) vetados: ya no vuelven a salir. Cambiándolos por otros…", 9000)
            self.mix()
        else:
            self._msg(f"👎 Anotado: no funciona. Sus {n} planos quedan vetados (ya no vuelven a salir). "
                      "Pulsa 🔀 Remix para uno nuevo sin ellos · Ctrl+Z los vuelve a permitir.", 14000)

    def not_here(self):
        """⛔ Aquí no: los planos seleccionados no van en ESTE tramo; se cambian al momento por otros."""
        rec = self.current()
        if rec is None:
            return
        if rec.get("style") in (None, "halo"):
            self._msg("Este edit se hizo con el estilo antiguo: crea uno con un estilo de Edits 2.0.")
            return
        if not self._uncook(rec):
            return
        ids = {c.id for c in self.ctrl.edit_clips(rec)}
        sel = [i for i in self.win.timeline.selected if i in ids]
        if not sel:
            self._msg("⛔ Aquí no: selecciona el plano (o los planos) del edit que no quieres en ese tramo.")
            return
        n = self.ctrl.ban_edit_slot(rec["id"], sel)
        if not n:
            return
        self._msg(f"⛔ {n} plano(s) ya no se sugieren en este tramo. Cambiándolos por otros…", 9000)
        self.mix()

    # ------------------------------------------------------------------ 🔀 Remix / 🎛 Mix
    def _sources(self, rec) -> list[dict]:
        p = self.ctrl.project
        out = []
        for mid in rec.get("sources") or []:
            m = p.media.get(mid)
            if m is not None and mid not in self.ctrl.missing:
                out.append({"media_id": m.id, "path": m.path, "kind": m.kind, "duration": m.duration,
                            "name": m.name})
        if not any(s["kind"] == KIND_VIDEO for s in out):     # edits antiguos: los videos que usa
            ids = {c.media_id for c in self.ctrl.edit_clips(rec)}
            out = [{"media_id": m.id, "path": m.path, "kind": m.kind, "duration": m.duration, "name": m.name}
                   for m in (p.media[i] for i in ids if i in p.media)]
        return out

    def _options(self, rec, **extra) -> dict | None:
        from ..ai import edit_feedback
        if rec.get("style") in (None, "halo"):
            self._msg("🔀/🎛 funcionan con los estilos de Edits 2.0 (Agresivo, Épico, Hype, Cine, Emocional, VHS).")
            return None
        opts = dict(rec.get("options") or {})
        opts.setdefault("style", rec["style"])
        opts.update(seed=random.randint(100, 10 ** 6), variation=True, learned=edit_feedback.learned(rec["style"]),
                    avoid=self.ctrl.edit_avoid())
        opts.update(extra)
        return opts

    def _run(self, title: str, rec: dict, opts: dict, on_plan):
        if self._busy:
            self._msg("Ya hay un remix en marcha (indicador naranja encima del visor).")
            return
        sources = self._sources(rec)
        song = self.ctrl.project.media.get(rec.get("song_id"))
        if song is None or not sources:
            self._msg("Falta la canción o los videos de ese edit en Medios.")
            return
        from ..ai import edit_maker
        from .task_window import manager
        self._busy = True
        for b in (self.b_remix, self.b_mix):
            b.setEnabled(False)

        def work(progress, cancelled):
            return edit_maker.make_edit(song.path, song.id, sources, opts, progress, cancelled)

        def done(plan):
            self._end()
            try:
                on_plan(plan)
            except Exception as exc:  # noqa: BLE001 - p. ej. pista bloqueada
                self._msg(f"✗ {exc}")

        manager().start(title, work, done, lambda m: (self._end(), self._msg("✗ " + m)))

    def _end(self):
        self._busy = False
        for b in (self.b_remix, self.b_mix):
            b.setEnabled(True)

    def remix(self):
        rec = self.current()
        opts = self._options(rec) if rec else None
        if not opts or not self._uncook(rec):
            return

        def put(plan):
            self.ctrl.apply_edit_plan(plan, layout=rec.get("layout", "auto"), game_volume=rec.get("game_volume", 0.0),
                                      replace=rec["id"])
            notes = ", ".join(plan.get("remix") or []) or "otros planos"
            self._msg(f"🔀 Remix: {notes}. ¿Mejor? Califícalo con 👍/👎 · Ctrl+Z vuelve a la versión anterior.", 14000)
        self._run("🔀 Remix del edit", rec, opts, put)

    def go_to(self, t: float, clip_ids: list | None = None):
        """El cabezal en el PRIMER fotograma del plano nuevo (no en el último del anterior) y la línea de
        tiempo enseñándolo, para verlo y calificarlo al momento."""
        tl = self.win.timeline
        p = self.ctrl.project
        vids = [p.clips[i] for i in (clip_ids or []) if i in p.clips and p.clips[i].text is None
                and p.track(p.clips[i].track_id) is not None and p.track(p.clips[i].track_id).kind == TRACK_VIDEO]
        if vids:
            first = min(vids, key=lambda c: c.start)
            t = min(first.start + 0.5 / max(1.0, p.fps), first.end - 1e-3)   # medio fotograma DENTRO del plano
        self.win.engine.user_seek(t)
        tl.scroll = max(0.0, t - (tl.width() - tl.HEADER_W) * 0.15 / tl.pps)
        tl._update_scrollbar()
        tl.update()

    def mix_range(self, rec) -> tuple[float, float] | None:
        """El tramo a rehacer: los planos seleccionados del edit o el tramo I/O, ajustado a cortes."""
        p = self.ctrl.project
        a0, b0 = rec["base"], rec["base"] + rec["duration"]
        v1 = next((t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO), None)
        sel = [p.clips[i] for i in self.win.timeline.selected if i in p.clips]
        sel = [c for c in sel if v1 is not None and c.track_id == v1.id and c.end > a0 and c.start < b0]
        if sel:
            a, b = min(c.start for c in sel), max(c.end for c in sel)
        elif p.marked_range():
            a, b = p.marked_range()
            a, b = max(a, a0), min(b, b0)
            cuts = sorted({round(c.start, 4) for c in self.ctrl.edit_clips(rec)} | {round(b0, 4)})
            a = max([x for x in cuts if x <= a + 1e-3] or [a0])            # a cortes: siguen en el golpe
            b = min([x for x in cuts if x >= b - 1e-3] or [b0])
        else:
            return None
        return (a, b) if b - a > 0.1 else None

    def mix(self):
        from ..ai import edit_feedback
        rec = self.current()
        if rec is None:
            return
        if not self._uncook(rec):
            return
        rng = self.mix_range(rec)
        if rng is None:
            self._msg("🎛 Mix: selecciona los planos del edit que quieres rehacer (o marca un tramo con I y O).")
            return
        opts = self._options(rec, window=rec.get("window"))
        if not opts:
            return
        a, b = rng
        # ⛔ lo que no va en ESTE tramo (además de lo vetado con 👎 en todo el proyecto)
        for mid, spans in self.ctrl.edit_slot_avoid(rec["id"], a, b).items():
            opts["avoid"] = {k: list(v) for k, v in (opts.get("avoid") or {}).items()}
            opts["avoid"].setdefault(mid, []).extend(spans)
        # «Ahí no me convenció» (pesa poco): lo que había en ese tramo
        old = [c for c in self.ctrl.edit_clips(rec) if c.start >= a - 1e-3 and c.end <= b + 1e-3]
        if old:
            secs = [dict(s, a=s["a"], b=s["b"]) for s in rec.get("sections") or []]
            fp = edit_feedback.fingerprint(edit_feedback.shots_from_clips(old, rec["base"]), secs,
                                           rec.get("period") or 0.5)
            edit_feedback.record(rec["style"], fp, -1, None, where="mix")

        def put(plan):
            made = self.ctrl.mix_edit_range(rec["id"], a, b, plan)
            new = [c for c in made if c in self.ctrl.project.clips] if isinstance(made, list) else []
            if new:
                self.win.timeline.set_selection(new)
            self.go_to(a, new)
            self._msg(f"🎛 Tramo rehecho ({b - a:.1f} s). ¿Así sí? 👍/👎 · Ctrl+Z vuelve a como estaba.", 14000)
        self._run("🎛 Mix de un tramo", rec, opts, put)
