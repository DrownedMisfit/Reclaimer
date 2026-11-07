"""
✂ Ajuste de los cortes de audio (la línea roja de la línea de tiempo).

Un panel pequeño, no modal:
  · arriba, la lista de TODOS los cortes dudosos del proyecto (mm:ss · motivo): clic en uno = ir ahí; «◀ Anterior» y
    «Siguiente ▶»; un contador «3 de 7»;
  · la SUGERENCIA del corte actual («💡 Sugerencia: …») con «✓ Aplicar sugerencia»;
  · las palabras de alrededor, y a mano: «Antes del corte» y «Después del corte» (−40 ms, +40 ms, +120 ms), Escuchar,
    «✓ Está bien así», «↺ Devolver todo el silencio»;
  · «✓ Aplicar todas las sugerencias» (todas en un solo paso de Deshacer).
Al aplicar o dar por bueno un corte, si su aviso desaparece el panel pasa solo al siguiente corte dudoso.
Cada acción es un paso de Deshacer (Ctrl+Z).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..core import cut_check
from .common import fmt_time

# (texto del botón, cuánto se mueve el corte en segundos). Positivo = recupera audio; negativo = quita más.
STEPS = [("−40 ms", -0.04), ("+40 ms", 0.04), ("+120 ms", 0.12)]
MAX_PASADAS = 5    # «Aplicar todas»: pasadas como mucho (cada una puede dejar un aviso nuevo que arreglar)


def aplicar_sugerencias(ctrl, timeline) -> tuple[int, int]:
    """Aplica la sugerencia de cada corte dudoso, de derecha a izquierda (lo de antes no se mueve). Un arreglo puede
    dejar otro aviso (p. ej. la voz que vuelve a quedar en el borde): se repite mientras cambie algo, con un tope de
    pasadas. Hay que llamarla dentro de un paso de deshacer (beginMacro/endMacro). Devuelve (cambios, cortes que
    quedan para revisar a mano)."""
    hechas = 0
    peaks_fn = lambda mid: ctrl.ensure_peaks(mid, wait=True)  # noqa: E731  (la forma de onda, al momento)
    for _pasada in range(MAX_PASADAS):
        timeline.refresh_cut_issues()
        issues = sorted(timeline.cut_issues, key=lambda i: i["t"], reverse=True)
        cambios = 0
        for it in issues:
            p = ctrl.project
            j = cut_check.junction_at(p, it["track_id"], it["t"])     # el estado de ahora
            issue = cut_check.check_junction(p, j, peaks_fn=peaks_fn) if j is not None else None
            fix = issue["fix"] if issue is not None else None
            if fix is None or ctrl.adjust_cut(j["track_id"], j["t"], fix["side"], fix["delta"]) is None:
                continue
            cambios += 1
        hechas += cambios
        if not cambios:
            break
    return hechas, timeline.refresh_cut_issues()


class _ClicFilter(QObject):
    """Convierte el clic izquierdo de una etiqueta en una llamada (sin cambiar cómo se ve)."""

    def __init__(self, etiqueta, fn):
        super().__init__(etiqueta)
        self._fn = fn

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            self._fn()
            return True
        return False


def conectar_clic(etiqueta, fn):
    """Hace que una etiqueta (p. ej. el «⚠ N cortes» de la barra) llame a fn() al pulsarla."""
    etiqueta.installEventFilter(_ClicFilter(etiqueta, fn))
    etiqueta.setCursor(Qt.PointingHandCursor)


class CutFixPanel(QFrame):
    def __init__(self, win):
        super().__init__(win, Qt.Tool)
        self.ctrl = win.ctrl
        self.engine = win.engine
        self.timeline = win.timeline
        self.track_id = ""
        self.t = 0.0
        self.setWindowTitle("Corte de audio")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        # ---- lista de cortes dudosos y navegación
        nav = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setStyleSheet("font-weight: bold;")
        nav.addWidget(self.counter)
        nav.addStretch()
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.setToolTip("Corte dudoso anterior (también Alt+←)")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        nav.addWidget(self.btn_prev)
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.setToolTip("Corte dudoso siguiente (también Alt+→)")
        self.btn_next.clicked.connect(lambda: self._step(1))
        nav.addWidget(self.btn_next)
        lay.addLayout(nav)
        self.list = QListWidget()
        self.list.setMaximumHeight(120)
        self.list.setToolTip("Todos los cortes dudosos del proyecto: clic en uno para ir ahí")
        self.list.itemClicked.connect(lambda it: self._goto(self.list.row(it)))
        lay.addWidget(self.list)

        # ---- el corte actual
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.title)
        self.reasons = QLabel()
        self.reasons.setWordWrap(True)
        lay.addWidget(self.reasons)
        self.sugg = QLabel()
        self.sugg.setWordWrap(True)
        self.sugg.setStyleSheet("color: #7fd1ae;")
        lay.addWidget(self.sugg)
        self.btn_apply = QPushButton("✓ Aplicar sugerencia")
        self.btn_apply.setMinimumHeight(34)
        self.btn_apply.setStyleSheet("font-weight: bold;")
        self.btn_apply.setToolTip("Aplica la sugerencia de este corte; si su aviso desaparece, pasa al siguiente")
        self.btn_apply.clicked.connect(self._apply_fix)
        lay.addWidget(self.btn_apply)
        self.words = QLabel()
        self.words.setWordWrap(True)
        self.words.setToolTip("Lo que se dice justo antes y justo después del corte (✂ = el corte)")
        lay.addWidget(self.words)

        self.step_buttons: list[QPushButton] = []
        for side, name, tip in (
                ("antes", "Antes del corte", "Mueve el FINAL del clip de la izquierda: +40 ms recupera audio que se "
                                             "cortó; −40 ms quita más"),
                ("despues", "Después del corte", "Mueve el PRINCIPIO del clip de la derecha: +40 ms recupera audio "
                                                 "que se cortó; −40 ms quita más")):
            row = QHBoxLayout()
            lab = QLabel(name)
            lab.setMinimumWidth(130)
            row.addWidget(lab)
            for text, delta in STEPS:
                b = QPushButton(text)
                b.setToolTip(tip)
                b.clicked.connect(lambda _c=False, s=side, d=delta: self._adjust(s, d))
                row.addWidget(b)
                self.step_buttons.append(b)
            lay.addLayout(row)

        bottom = QHBoxLayout()
        self.btn_listen = QPushButton("▶ Escuchar")
        self.btn_listen.setToolTip("Reproduce 1,5 s antes del corte y 1,5 s después")
        self.btn_listen.clicked.connect(self._listen)
        bottom.addWidget(self.btn_listen)
        self.btn_ok = QPushButton("✓ Está bien así")
        self.btn_ok.setToolTip("Lo das por bueno: su línea roja desaparece (Ctrl+Z lo devuelve)")
        self.btn_ok.clicked.connect(self._approve)
        bottom.addWidget(self.btn_ok)
        self.btn_all = QPushButton("↺ Devolver todo el silencio")
        self.btn_all.setToolTip("Vuelve a poner el silencio entero que se cortó aquí")
        self.btn_all.clicked.connect(self._restore_all)
        bottom.addWidget(self.btn_all)
        lay.addLayout(bottom)

        self.btn_apply_all = QPushButton("✓ Aplicar todas las sugerencias")
        self.btn_apply_all.setToolTip("Aplica la sugerencia de cada corte dudoso que tenga una. Todo en un solo paso "
                                      "de Deshacer (Ctrl+Z)")
        self.btn_apply_all.clicked.connect(self._apply_all)
        lay.addWidget(self.btn_apply_all)

    # ------------------------------------------------------------------ datos
    def _peaks(self, media_id: str):
        return self.ctrl.ensure_peaks(media_id, wait=True)

    def _issues(self) -> list[dict]:
        return self.timeline.cut_issues

    def _index_of(self, track_id: str, t: float) -> int | None:
        for k, it in enumerate(self._issues()):
            if it["track_id"] == track_id and abs(it["t"] - t) <= 0.01:
                return k
        return None

    def _next_index(self, t: float, step: int) -> int:
        """Índice del corte dudoso anterior (step < 0) o siguiente (step > 0) a t; al pasar del último vuelve al
        primero, y al pasar del primero, al último."""
        issues = self._issues()
        if step > 0:
            cand = [k for k in range(len(issues)) if issues[k]["t"] > t + 0.02]
            return cand[0] if cand else 0
        cand = [k for k in range(len(issues)) if issues[k]["t"] < t - 0.02]
        return cand[-1] if cand else len(issues) - 1

    def show_issue(self, track_id: str, t: float):
        self.track_id, self.t = track_id, t
        self.timeline.refresh_cut_issues()
        self._refresh()
        self.show()
        self.raise_()

    def _refresh(self):
        p = self.ctrl.project
        self.timeline.refresh_cut_issues()
        issues = self._issues()
        k = self._index_of(self.track_id, self.t)
        self._fill_list(k)
        n = len(issues)
        if k is not None:
            self.counter.setText(f"{k + 1} de {n}")
        else:
            self.counter.setText(f"{n} por revisar" if n else "Ninguno por revisar")
        self.btn_prev.setEnabled(n > 0)
        self.btn_next.setEnabled(n > 0)
        self.btn_apply_all.setEnabled(n > 0)

        j = cut_check.junction_at(p, self.track_id, self.t)
        if j is None:
            self.title.setText("Este corte ya no está: quedó unido o lo cambiaste.")
            self.reasons.setText("")
            self.sugg.setText("")
            self.words.setText("")
            for b in self.step_buttons + [self.btn_listen, self.btn_ok, self.btn_all, self.btn_apply]:
                b.setEnabled(False)
            return
        self.t = j["t"]
        for b in self.step_buttons + [self.btn_listen, self.btn_all]:
            b.setEnabled(True)
        gap = j["in"] - j["out"]
        tr = p.track(j["track_id"])
        self.title.setText(f"Corte de audio en {fmt_time(j['t'])} · pista {tr.name if tr else ''} · "
                           f"silencio cortado: {gap * 1000:.0f} ms")
        key = cut_check.junction_key(j)
        approved = key in p.cut_ok
        self.btn_ok.setEnabled(not approved)
        issue = cut_check.check_junction(p, j, peaks_fn=self._peaks)
        fix = issue["fix"] if issue is not None else None
        if approved:
            self.reasons.setText("✓ Lo diste por bueno. Si lo cambias, vuelve a revisarse.")
            self.sugg.setText("")
        elif issue is None:
            self.reasons.setText("✓ No veo nada raro: ni palabras cortadas ni sonido en el borde.")
            self.sugg.setText("")
        else:
            tag = "⚠ Revisa este corte:" if issue["severity"] == "alta" else "Revisa este corte:"
            self.reasons.setText(tag + "\n• " + "\n• ".join(issue["reasons"]))
            self.sugg.setText(f"💡 Sugerencia: {fix['text']}" if fix else
                              "💡 Sin sugerencia: revísalo a mano (Escuchar o los botones de abajo).")
        self.btn_apply.setEnabled(fix is not None and not approved)
        self.words.setText(self._words_text(p, j))

    def _fill_list(self, k: int | None):
        self.list.blockSignals(True)
        self.list.clear()
        for i, it in enumerate(self._issues()):
            motivo = it["reasons"][0] if it["reasons"] else "Revisar"
            self.list.addItem(QListWidgetItem(f"{fmt_time(it['t'], frac=False)} · {motivo}"))
        if k is not None:
            self.list.setCurrentRow(k)
        else:
            self.list.clearSelection()
        self.list.blockSignals(False)

    def _words_text(self, p, j: dict) -> str:
        ws = (p.transcripts.get(j["media_id"]) or {}).get("words") or []
        if not ws:
            return "Sin transcripción: el aviso se basa solo en el sonido."
        before = [str(w[2]) for w in ws if float(w[1]) <= j["out"] + 0.03][-4:]
        after = [str(w[2]) for w in ws if float(w[0]) >= j["in"] - 0.03][:4]
        return f"…{' '.join(before)}  ✂  {' '.join(after)}…"

    # ------------------------------------------------------------- navegación
    def _goto(self, k: int):
        """Lleva el cabezal al corte dudoso k (como ◀ ▶ de la barra) y lo muestra en el panel."""
        issues = self._issues()
        if not (0 <= k < len(issues)):
            return
        it = issues[k]
        self.track_id, self.t = it["track_id"], it["t"]
        self.engine.user_seek(self.t)
        self.timeline.set_playhead(self.t, follow=True)
        self._refresh()

    def _step(self, step: int):
        if not self._issues():
            return
        self._goto(self._next_index(self.t, step))

    def _after_change(self, new_t: float):
        """Tras un cambio: si el aviso sigue, el panel se queda; si desapareció, pasa solo al siguiente corte."""
        self.t = new_t
        self.timeline.refresh_cut_issues()
        if self._index_of(self.track_id, new_t) is None and self._issues():
            self._goto(self._next_index(new_t, 1))
        else:
            self._refresh()

    # ------------------------------------------------------------- acciones
    def _apply_fix(self):
        p = self.ctrl.project
        j = cut_check.junction_at(p, self.track_id, self.t)
        if j is None:
            return
        issue = cut_check.check_junction(p, j, peaks_fn=self._peaks)
        fix = issue["fix"] if issue is not None else None
        if fix is None:
            return
        self._adjust(fix["side"], fix["delta"])

    def _adjust(self, side: str, delta: float):
        if self.ctrl.adjust_cut(self.track_id, self.t, side, delta) is None:
            return                          # el controlador ya dijo por qué no (barra de estado)
        self._after_change(self.t + delta if side == "antes" else self.t)

    def _restore_all(self):
        j = cut_check.junction_at(self.ctrl.project, self.track_id, self.t)
        if j is None:
            return
        if self.ctrl.adjust_cut(self.track_id, j["t"], "antes", j["in"] - j["out"]) is None:
            return
        self._after_change(self.t)

    def _approve(self):
        j = cut_check.junction_at(self.ctrl.project, self.track_id, self.t)
        if j is None:
            return
        self.ctrl.approve_cut(cut_check.junction_key(j))
        self._after_change(self.t)

    def _apply_all(self):
        """Aplica la sugerencia de cada corte dudoso (ver aplicar_sugerencias), en un solo paso de Deshacer."""
        stack = self.ctrl.undo_stack
        stack.beginMacro("Aplicar sugerencias de cortes")
        try:
            hechas, quedan = aplicar_sugerencias(self.ctrl, self.timeline)
        finally:
            stack.endMacro()
        aviso = f"✂ Sugerencias aplicadas ({hechas} cambios)"
        if quedan:
            aviso += f"; quedan {quedan} cortes para revisar a mano"
        self.ctrl.message.emit(aviso + ". Ctrl+Z las deshace todas.")
        self._refresh()

    def _listen(self):
        self.engine.play_ranges([(max(0.0, self.t - 1.5), self.t + 1.5)])
