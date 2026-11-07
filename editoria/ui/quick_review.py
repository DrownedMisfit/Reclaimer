"""
⚡ Revisión rápida con teclas (ventana NO modal): recorre UNA A UNA, en el orden del video, lo que la IA propone y los
cortes de audio dudosos, para decidir sin ratón.

  · Propuestas pendientes de la limpieza de voz (silencios, muletillas, repeticiones, tomas…):
    Enter = aceptar (se corta), Supr = rechazar (se ignora).
  · Cortes de audio que pueden estar mal (líneas rojas):
    Enter = aplicar su sugerencia (si la tiene; si no, «Está bien así»); O = «Está bien así»;
    Supr = ajustarlo a mano (abre el panel «Corte de audio»; no decide nada).

Teclas: Enter o A aceptar · O «está bien así» (cortes) · Supr o R rechazar · → o Espacio siguiente sin decidir · ← anterior · P escuchar · Esc cerrar.
Cada decisión es un paso de Ctrl+Z. Las propuestas «Solo aviso» (frases que suenan parecido) no entran aquí.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..ai import voice_cleanup
from ..core import cut_check, mapping
from ..core.model import SUG_PENDING
from .common import fmt_time

PAD = 1.5             # segundos antes y después que se reproducen
MAX_SPAN = 6.0        # un silencio de más de esto se escucha solo sus primeros segundos (y el final)
CONTEXT = 6           # palabras de contexto antes y después
HINT = ("Enter/A aceptar (en un corte: aplica su sugerencia) · O «está bien así» · Supr/R rechazar · "
        "→/Espacio saltar · ← anterior · P escuchar · Esc cerrar")


@dataclass
class Item:
    kind: str                 # "sug" (propuesta de la IA) | "cut" (corte de audio dudoso)
    ref: str                  # id de la propuesta | clave del corte
    t: float | None           # momento en la línea de tiempo (None = fuera de ella)
    track_id: str = ""        # solo cortes
    media_id: str = ""        # solo propuestas


# ----------------------------------------------------------------- lógica (sin ventanas)
def pending_suggestions(p) -> list:
    """Propuestas que aún se pueden decidir: pendientes, cortables y de la limpieza de voz (no las tachadas a mano)."""
    return [s for s in p.suggestions if s.status == SUG_PENDING and s.cuttable and s.kind != "manual"
            and s.kind in voice_cleanup.KINDS]


def timeline_span(p, s) -> tuple[float, float] | None:
    """Dónde está el fragmento de una propuesta en la línea de tiempo: (inicio, fin), o None si no está."""
    parts = mapping.map_range(p, s.media_id, s.start, s.end)
    if not parts:
        return None
    return parts[0][1], parts[-1][2]


def build_queue(p, cut_issues: list[dict]) -> list[Item]:
    """Todo lo que hay que revisar, en el orden en que aparece en el video."""
    items = []
    for s in pending_suggestions(p):
        span = timeline_span(p, s)
        items.append(Item("sug", s.id, span[0] if span else None, media_id=s.media_id))
    for c in cut_issues:
        items.append(Item("cut", c["key"], float(c["t"]), track_id=c["track_id"]))
    items.sort(key=lambda it: (it.t is None, it.t or 0.0))
    return items


def _words(p, media_id: str) -> list:
    return (p.transcripts.get(media_id) or {}).get("words") or []


def suggestion_context(p, s) -> str:
    """Lo dicho alrededor de la propuesta; lo que se quitaría va entre ✂."""
    ws = _words(p, s.media_id)
    if not ws:
        return "Sin transcripción: la propuesta se basa solo en el sonido."
    a, b = s.start, s.end
    before = [str(w[2]) for w in ws if float(w[1]) <= a + 0.03][-CONTEXT:]
    inside = [str(w[2]) for w in ws if float(w[1]) > a + 0.03 and float(w[0]) < b - 0.03]
    after = [str(w[2]) for w in ws if float(w[0]) >= b - 0.03][:CONTEXT]
    text = f"…{' '.join(before)}  ✂ {' '.join(inside) or '(silencio)'} ✂  {' '.join(after)}…"
    if s.alt_start is not None and s.alt_end is not None:
        alt = [str(w[2]) for w in ws if float(w[1]) > s.alt_start + 0.03 and float(w[0]) < s.alt_end - 0.03]
        text += f"\nLa otra toma: {' '.join(alt) or '(silencio)'}"
    return text


def cut_context(p, j: dict) -> str:
    """Lo que se dice justo antes y justo después del corte (✂ = el corte)."""
    ws = _words(p, j["media_id"])
    if not ws:
        return "Sin transcripción: el aviso se basa solo en el sonido."
    before = [str(w[2]) for w in ws if float(w[1]) <= j["out"] + 0.03][-CONTEXT:]
    after = [str(w[2]) for w in ws if float(w[0]) >= j["in"] - 0.03][:CONTEXT]
    return f"…{' '.join(before)}  ✂  {' '.join(after)}…"


# ----------------------------------------------------------------- ventana
class QuickReview(QWidget):
    def __init__(self, win):
        super().__init__(win, Qt.Window)          # ventana propia, junto al programa, sin bloquearlo
        self.win = win
        self.ctrl = win.ctrl
        self.engine = win.engine
        self.timeline = win.timeline
        self.setWindowTitle("⚡ Revisión rápida")
        self.setMinimumWidth(500)
        self.setFocusPolicy(Qt.StrongFocus)
        self.queue: list[Item] = []
        self.i = 0
        self.done: dict[str, str] = {}            # «sug:id» / «cut:clave» → «aceptada» | «rechazada»
        self.dur0 = 0.0
        self.finished = False

        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        row = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setStyleSheet("font-weight: bold;")
        row.addWidget(self.counter)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(10)
        row.addWidget(self.bar, 1)
        lay.addLayout(row)
        self.why = QLabel()
        self.why.setWordWrap(True)
        lay.addWidget(self.why)
        self.sugg = QLabel()                      # sugerencia de un corte dudoso
        self.sugg.setWordWrap(True)
        self.sugg.setStyleSheet("color: #7fd1ae;")
        self.sugg.hide()
        lay.addWidget(self.sugg)
        self.words = QLabel()
        self.words.setWordWrap(True)
        self.words.setStyleSheet("color: #c7ccd4;")
        self.words.setToolTip("Lo que se dice alrededor (✂ = lo que se quitaría o el corte)")
        lay.addWidget(self.words)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #e8833a;")
        lay.addWidget(self.note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 13px;")
        self.summary.hide()
        lay.addWidget(self.summary)

        btns = QHBoxLayout()
        self.btn_prev = self._btn("← Anterior", "Vuelve a la propuesta anterior (tecla ←)", self._prev)
        self.btn_listen = self._btn("▶ Escuchar", "Vuelve a escuchar (tecla P): 1,5 s antes y 1,5 s después",
                                    self._listen)
        self.btn_accept = self._btn("✓ Aceptar", "Enter o A. Propuesta: se corta. Corte dudoso: aplica su sugerencia "
                                    "(o lo da por bueno si no tiene)", self._accept)
        self.btn_ok = self._btn("○ Está bien así", "O. Solo cortes dudosos: lo das por bueno sin tocarlo", self._ok)
        self.btn_reject = self._btn("✗ Rechazar", "Supr o R. Propuesta: se ignora. Corte dudoso: ajustarlo a mano",
                                    self._reject)
        self.btn_next = self._btn("Saltar →", "Siguiente sin decidir (tecla → o Espacio)", self._next)
        for b in (self.btn_prev, self.btn_listen, self.btn_accept, self.btn_ok, self.btn_reject, self.btn_next):
            btns.addWidget(b)
        lay.addLayout(btns)
        bottom = QHBoxLayout()
        hint = QLabel(HINT)
        hint.setStyleSheet("color: #9da2ab;")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        self.btn_close = self._btn("Cerrar", "Esc", self.close)
        bottom.addWidget(self.btn_close)
        lay.addLayout(bottom)

    @staticmethod
    def _btn(text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)       # que las teclas lleguen siempre a la ventana (ni Espacio ni Enter pulsan botones)
        b.clicked.connect(lambda _c=False: slot())
        return b

    # ------------------------------------------------------------ arrancar
    def start(self):
        p = self.ctrl.project
        self.timeline.refresh_cut_issues()
        self.queue = build_queue(p, self.timeline.cut_issues)
        self.i = 0
        self.done = {}
        self.dur0 = p.duration()
        self.finished = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._show()

    # ------------------------------------------------------------ datos de un elemento
    def _key(self, it: Item) -> str:
        return f"{it.kind}:{it.ref}"

    def _sug(self, ref: str):
        return next((s for s in self.ctrl.project.suggestions if s.id == ref), None)

    def _junction(self, it: Item) -> dict | None:
        """El corte dudoso tal como está ahora (o None si ya no existe o lo diste por bueno). Actualiza su clave/tiempo."""
        p = self.ctrl.project
        if it.t is None:
            return None
        j = cut_check.junction_at(p, it.track_id, it.t)
        if j is None:
            return None
        key = cut_check.junction_key(j)
        if key in p.cut_ok:
            return None
        it.ref, it.t = key, float(j["t"])
        return j

    def _valid(self, it: Item) -> bool:
        if it.kind == "sug":
            s = self._sug(it.ref)
            return s is not None and s.status == SUG_PENDING and s.cuttable
        return self._junction(it) is not None

    def _peaks(self, media_id: str):
        return self.ctrl.ensure_peaks(media_id, wait=True)

    # ------------------------------------------------------------ mostrar
    def _show(self):
        n = len(self.queue)
        if self.i >= n:
            self._show_summary()
            return
        self.finished = False
        self.summary.hide()
        self.sugg.hide()
        p = self.ctrl.project
        it = self.queue[self.i]
        decided = self.done.get(self._key(it))
        self.counter.setText(f"{self.i + 1} de {n}")
        self.bar.setRange(0, n)
        self.bar.setValue(len(self.done))
        valid = self._valid(it)
        fix = None
        if it.kind == "sug":
            s = self._sug(it.ref)
            self.timeline.set_highlight_suggestion(it.ref if s else "")
            if s is not None:
                self.win.voice.select_suggestion(s.id)
            if s is not None and valid:
                kind_name = voice_cleanup.KINDS.get(s.kind, (s.kind,))[0]
                self.title.setText(f"✂ {kind_name} · {fmt_time(it.t) if it.t is not None else '—'}")
                why = s.label + (f"\n{s.detail}" if s.detail else "")
                self.why.setText(why)
                self.words.setText(suggestion_context(p, s))
            else:
                self.title.setText(f"Propuesta {self.i + 1}")
                self.why.setText("Esta propuesta ya no está pendiente.")
                self.words.setText("")
        else:
            self.timeline.set_highlight_suggestion("")
            j = self._junction(it) if valid else None
            if j is not None:
                issue = cut_check.check_junction(p, j, peaks_fn=self._peaks)
                reasons = issue["reasons"] if issue else ["Revísalo: el aviso es de antes de tus últimos cambios."]
                fix = issue["fix"] if issue else None
                self.title.setText(f"⚠ Corte de audio · {fmt_time(j['t'])}")
                self.why.setText("Revisa este corte:\n• " + "\n• ".join(reasons))
                self.words.setText(cut_context(p, j))
                self.sugg.setText(f"💡 Sugerencia: {fix['text']}  (Enter la aplica)" if fix else
                                  "💡 Sin sugerencia: Enter lo da por bueno (o O); Supr lo ajusta a mano.")
                self.sugg.show()
            else:
                self.title.setText(f"Corte {self.i + 1}")
                self.why.setText("Este corte ya no está o lo diste por bueno.")
                self.words.setText("")
        if decided:
            self.note.setText(f"Ya decidiste esta: {decided}. Puedes cambiarla con Ctrl+Z.")
        else:
            self.note.setText("")
        if it.kind == "cut":
            self.btn_accept.setText("✓ Aplicar sugerencia" if fix else "✓ Está bien así")
        else:
            self.btn_accept.setText("✓ Aceptar")
        for b in (self.btn_accept, self.btn_reject):
            b.setEnabled(valid)
        self.btn_ok.setEnabled(valid and it.kind == "cut")
        self.btn_listen.setEnabled(it.t is not None)
        self.btn_prev.setEnabled(self.i > 0)
        self.btn_next.setEnabled(True)
        self.setFocus()
        self._listen()

    def _show_summary(self):
        self.finished = True
        n = len(self.queue)
        p = self.ctrl.project
        acc = sum(1 for v in self.done.values() if v == "aceptada")
        rej = sum(1 for v in self.done.values() if v == "rechazada")
        other = sum(1 for it in self.queue if self._key(it) not in self.done and not self._valid(it))
        undecided = n - len(self.done) - other
        self.title.setText("Revisión terminada" if n else "Nada que revisar")
        self.counter.setText(f"{n} de {n}" if n else "0")
        self.bar.setValue(len(self.done))
        self.why.setText("")
        self.words.setText("")
        self.note.setText("" if n else "No hay propuestas pendientes ni cortes dudosos. "
                                       "(¿Ya transcribiste y analizaste la narración?)")
        dur1 = p.duration()
        lines = [f"Aceptadas {acc}, rechazadas {rej}, sin decidir {undecided}"
                 + (f", resueltas de otra forma {other}" if other else "") + "."]
        if n:
            lines.append(f"La duración del proyecto pasó de {fmt_time(self.dur0)} a {fmt_time(dur1)} "
                         f"(−{max(0.0, self.dur0 - dur1):.1f} s).")
        self.timeline.refresh_cut_issues()
        mine = {it.ref for it in self.queue if it.kind == "cut"}
        new_cuts = [c for c in self.timeline.cut_issues if c["key"] not in mine]
        if new_cuts:
            lines.append(f"Tus cambios han hecho aparecer {len(new_cuts)} corte(s) dudoso(s) nuevo(s): "
                         "revísalos en la línea de tiempo (⚠ Cortes).")
        self.summary.setText("\n".join(lines))
        self.summary.show()
        for b in (self.btn_accept, self.btn_reject, self.btn_listen, self.btn_next):
            b.setEnabled(False)
        self.btn_prev.setEnabled(n > 0)
        self.engine.pause()

    # ------------------------------------------------------------ acciones
    def _record(self, it: Item, result: str):
        self.done[self._key(it)] = result
        self.timeline.refresh_cut_issues()
        self._next()

    def _accept(self):
        if self.finished or not self.queue:
            return
        it = self.queue[self.i]
        if not self._valid(it):
            self.note.setText("Esta ya no está pendiente: salta a la siguiente con →.")
            return
        if it.kind == "sug":
            if not self.ctrl.apply_suggestions([it.ref]):
                self.note.setText("No se pudo aplicar (mira el aviso en la barra de estado).")
                return
            self._record(it, "aceptada")
            return
        # corte dudoso: aplica su sugerencia; si no tiene, lo da por bueno
        p = self.ctrl.project
        j = self._junction(it)
        issue = cut_check.check_junction(p, j, peaks_fn=self._peaks) if j is not None else None
        fix = issue["fix"] if issue is not None else None
        if fix is None:
            self.ctrl.approve_cut(it.ref)
            self._record(it, "aceptada")
            return
        new_t = it.t + fix["delta"] if fix["side"] == "antes" else it.t
        if self.ctrl.adjust_cut(it.track_id, it.t, fix["side"], fix["delta"]) is None:
            self.note.setText("No se pudo aplicar la sugerencia (mira el aviso en la barra de estado). "
                              "Supr lo ajusta a mano.")
            return
        it.t = new_t
        self.timeline.refresh_cut_issues()
        if self._still_issue(it):
            self._show()
            self.note.setText("Sugerencia aplicada. Sigue habiendo aviso: Enter lo intenta otra vez, "
                              "o Supr lo ajusta a mano.")
            return
        self._record(it, "aceptada")

    def _still_issue(self, it: Item) -> bool:
        """¿Sigue habiendo aviso (y no lo diste por bueno) en ese corte, tras un cambio?"""
        p = self.ctrl.project
        j = cut_check.junction_at(p, it.track_id, it.t)
        if j is None or cut_check.junction_key(j) in p.cut_ok:
            return False
        return cut_check.check_junction(p, j, peaks_fn=self._peaks) is not None

    def _ok(self):
        """O: «Está bien así» para un corte dudoso (sin tocarlo)."""
        if self.finished or not self.queue:
            return
        it = self.queue[self.i]
        if it.kind != "cut":
            self.note.setText("«Está bien así» (O) es para los cortes dudosos; las propuestas se aceptan con Enter.")
            return
        if not self._valid(it):
            self.note.setText("Este corte ya no está o lo diste por bueno: salta a la siguiente con →.")
            return
        self.ctrl.approve_cut(it.ref)
        self._record(it, "aceptada")

    def _reject(self):
        if self.finished or not self.queue:
            return
        it = self.queue[self.i]
        if it.kind == "cut":
            if self._valid(it):
                self.win.cut_fix.show_issue(it.track_id, it.t)
                self.raise_()
                self.activateWindow()
                self.setFocus()
                self.note.setText("Ajústalo en el panel «Corte de audio». Cuando acabes, → para seguir.")
            return
        if not self._valid(it):
            self.note.setText("Esta ya no está pendiente: salta a la siguiente con →.")
            return
        self.ctrl.reject_suggestions([it.ref])
        self._record(it, "rechazada")

    def _next(self):
        if self.i < len(self.queue):
            self.i += 1
        self._show()

    def _prev(self):
        if not self.queue:
            return
        self.i = max(0, self.i - 1) if not self.finished else len(self.queue) - 1
        self._show()

    def _listen(self):
        if self.finished or not self.queue:
            return
        it = self.queue[self.i]
        p = self.ctrl.project
        if it.kind == "sug":
            s = self._sug(it.ref)
            span = timeline_span(p, s) if s is not None else None
            if span is None:
                self.note.setText("Ese fragmento no está en la línea de tiempo: no hay nada que escuchar.")
                return
            a, b = span
            start, end = a - PAD, min(b, a + MAX_SPAN) + PAD
        else:
            if it.t is None:
                return
            start, end = it.t - PAD, it.t + PAD
        self.engine.play_ranges([(start, end)])

    # ------------------------------------------------------------ teclas
    def keyPressEvent(self, e):
        k = e.key()
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return super().keyPressEvent(e)
        rep = e.isAutoRepeat()            # mantener Enter pulsado no debe aceptar cien cortes seguidos
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_A):
            if not rep:
                self._accept()
        elif k == Qt.Key_O:
            if not rep:
                self._ok()
        elif k in (Qt.Key_Delete, Qt.Key_R):
            if not rep:
                self._reject()
        elif k in (Qt.Key_Right, Qt.Key_Space):
            self._next()
        elif k == Qt.Key_Left:
            self._prev()
        elif k == Qt.Key_P:
            self._listen()
        elif k == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        try:
            self.engine.pause()
            self.timeline.set_highlight_suggestion("")
        except Exception:  # noqa: BLE001 - cerrar nunca debe fallar
            pass
        super().closeEvent(e)
