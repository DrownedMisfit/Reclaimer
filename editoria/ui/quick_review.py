"""
✓ Revisión guiada (antes «Revisión rápida»; ventana NO modal): recorre UNA A UNA, en el orden del video, SOLO los sitios
donde la IA duda, para no tener que revisar el video entero y decidir sin ratón.

  · Avisos del proyecto con hora (los de «Lista de avisos», ai/audit.py): pantalla negra, plano repetido, plano fijo
    largo, el tema no encaja con lo que se ve, saltos de volumen…; y el B-roll que la IA puso SOLO por parecido (sin
    que nombres lo que se ve): Enter = lo que propone la IA (otro clip / rellenar el hueco), O = está bien así (no
    vuelve a salir: project.review_ok), Supr = quitar ese clip.

  · Propuestas pendientes de la limpieza de voz (silencios, muletillas, repeticiones, tomas…):
    Enter = aceptar (se corta), Supr = rechazar (se ignora).
  · Cortes de audio que pueden estar mal (líneas rojas):
    Enter = aplicar su sugerencia (si la tiene; si no, «Está bien así»); O = «Está bien así»;
    Supr = ajustarlo a mano (abre el panel «Corte de audio»; no decide nada).

Teclas: Enter o A aceptar · O «está bien así» · Supr o R rechazar / quitar · → o Espacio siguiente sin decidir · ← anterior · P escuchar · Esc cerrar.
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
HINT = ("Enter/A lo que propone la IA · O está bien así · Supr/R rechazar o quitar · →/Espacio saltar · "
        "← anterior · P escuchar · Esc cerrar")
SKIP_AUDIT = {"Cortes"}          # (los cortes dudosos ya entran como «cut», con su sugerencia)
AUDIT_ICON = {"Imagen": "⬛", "Repetición": "🔁", "Ritmo": "⏱", "Continuidad": "🧩", "Audio": "🔊",
              "Subtítulos": "💬", "Textos": "🔤"}


@dataclass
class Item:
    kind: str                 # "sug" (propuesta de la IA) | "cut" (corte dudoso) | "audit" (aviso) | "broll" (B-roll dudoso)
    ref: str                  # id de la propuesta | clave del corte | clave del aviso o del clip (review_ok)
    t: float | None           # momento en la línea de tiempo (None = fuera de ella)
    track_id: str = ""        # solo cortes
    media_id: str = ""        # solo propuestas
    data: dict | None = None  # aviso: el del audit; B-roll: {"clip", "reason"}


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


BROLL_MAX = 20        # B-roll dudoso como mucho en una revisión (la IA aún no guarda su seguridad: que no inunde)


def _codigo(issue: dict) -> str:
    """El tipo de aviso sin sus números («Plano de 12 s» y «Plano de 9 s» son el mismo tipo)."""
    import re
    return re.sub(r"[\d.,:]+", "#", str(issue.get("message", "")))[:48]


def audit_key(issue: dict) -> str:
    """Clave para «está bien así»: con clip, sin la hora (editar antes no la cambia); sin clip, al segundo."""
    base = f"audit|{issue.get('category', '')}|{_codigo(issue)}"
    if issue.get("target"):
        return f"{base}|{issue['target']}"
    t = issue.get("time")
    return f"{base}|t{int(round(float(t))) if t is not None else ''}"


def broll_doubtful(p) -> list:
    """Clips de B-roll que la IA puso SOLO por parecido de imagen: ni nombras lo que se ve («mencionas…») ni es el
    gameplay de fondo que sigue donde iba. Son los que más fallan."""
    from ..core.model import ORIGIN_AI
    out = []
    for c in p.clips.values():
        note = c.note or ""
        if c.origin != ORIGIN_AI or not note.startswith("B-roll IA"):
            continue
        reason = note.split(":", 1)[1].strip() if ":" in note else ""
        if "mencionas" in reason or reason.startswith("gameplay"):
            continue
        out.append((c, reason))
    return out


def build_queue(p, cut_issues: list[dict], audit_issues: list[dict] | None = None, scope: str = "todo") -> list[Item]:
    """Todo lo que hay que revisar, en el orden en que aparece en el video. scope «voz»: solo la limpieza de voz y
    los cortes (como la antigua revisión rápida)."""
    items = []
    for s in pending_suggestions(p):
        span = timeline_span(p, s)
        items.append(Item("sug", s.id, span[0] if span else None, media_id=s.media_id))
    for c in cut_issues:
        items.append(Item("cut", c["key"], float(c["t"]), track_id=c["track_id"]))
    if scope != "voz":
        ok = set(p.review_ok)
        vistos = set()
        for a in audit_issues or []:
            if a.get("time") is None or a.get("category") in SKIP_AUDIT:
                continue
            k = audit_key(a)
            if k in ok or k in vistos:
                continue
            vistos.add(k)
            d = dict(a)
            tc = p.clips.get(a.get("target") or "")
            d["off"] = float(a["time"]) - float(tc.start) if tc is not None else None   # (sigue al clip si se mueve)
            items.append(Item("audit", k, float(a["time"]), data=d))
        en_avisos = {a.get("target") for a in audit_issues or [] if a.get("target")}
        n_broll = 0
        for c, reason in sorted(broll_doubtful(p), key=lambda x: x[0].start):
            k = f"broll|{c.id}"
            if k in ok or c.id in en_avisos:
                continue                          # (si ya tiene un aviso, sale una sola vez)
            if n_broll >= BROLL_MAX:
                break
            n_broll += 1
            items.append(Item("broll", k, float(c.start), data={"clip": c.id, "reason": reason}))
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
        self.setWindowTitle("✓ Revisión guiada")
        self.scope = "todo"
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
        self.btn_prev = self._btn("← Anterior", "Vuelve al anterior (tecla ←)", self._prev)
        self.btn_listen = self._btn("▶ Escuchar", "Vuelve a escuchar (tecla P): 1,5 s antes y 1,5 s después",
                                    self._listen)
        self.btn_accept = self._btn("✓ Aceptar", "Enter o A. Propuesta: se corta. Corte dudoso: aplica su sugerencia "
                                    "(o lo da por bueno si no tiene)", self._accept)
        self.btn_ok = self._btn("○ Está bien así", "O. Lo das por bueno sin tocarlo y no vuelve a salir (cortes, "
                                "avisos y B-roll)", self._ok)
        self.btn_reject = self._btn("✗ Rechazar", "Supr o R. Propuesta: se ignora. Corte dudoso: ajustarlo a mano. "
                                    "Aviso o B-roll: quitar ese clip de encima", self._reject)
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
    def start(self, scope: str = "todo"):
        """scope «todo»: la voz, los cortes, los avisos del proyecto y el B-roll dudoso; «voz»: solo lo de la voz."""
        p = self.ctrl.project
        self.scope = scope
        self.timeline.refresh_cut_issues()
        avisos, self._audit_err = [], ""
        if scope != "voz":
            try:
                from ..ai.audit import run_audit
                self.ctrl.ensure_timeline_peaks(wait=False)    # (lo que ya esté: no decodifica audio largo aquí)
                avisos, _n = run_audit(p, self.ctrl.missing, self.ctrl.peaks, self.ctrl.clip_vecs)
            except Exception as exc:  # noqa: BLE001 - sin avisos, la revisión sigue con lo demás
                avisos, self._audit_err = [], str(exc)
        self._generales = sum(1 for a in avisos if a.get("time") is None)
        self.queue = build_queue(p, self.timeline.cut_issues, avisos, scope)
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
        if j is None or cut_check.junction_key(j) != it.ref:
            j2 = next((x for x in cut_check.junctions(p) if cut_check.junction_key(x) == it.ref), None)
            j = j2 or j                            # (se movió por un corte anterior: el mismo, por su clave)
        if j is None:
            return None
        key = cut_check.junction_key(j)
        if key in p.cut_ok:
            return None
        it.ref, it.t = key, float(j["t"])
        return j

    def _clip_of(self, it: Item):
        cid = (it.data or {}).get("clip") if it.kind == "broll" else (it.data or {}).get("target")
        c = self.ctrl.project.clips.get(cid) if cid else None
        if c is not None:                          # la hora sigue al clip aunque edites antes
            off = (it.data or {}).get("off")
            it.t = float(c.start) + (float(off) if off is not None and it.kind == "audit" else 0.0)
        return c

    def _capa(self, c) -> bool:
        """¿El clip es una capa de video de encima (B-roll, imagen…)? Nunca la pista principal, la voz ni la música."""
        p = self.ctrl.project
        vt = [t for t in p.tracks if t.kind == "video"]
        return c is not None and bool(vt) and c.track_id != vt[-1].id and any(t.id == c.track_id for t in vt)

    def _ia_ocupada(self) -> bool:
        ap = getattr(self.win, "ai_panel", None)
        return ap is not None and getattr(ap, "job", None) is not None

    def _valid(self, it: Item) -> bool:
        if it.kind == "sug":
            s = self._sug(it.ref)
            return s is not None and s.status == SUG_PENDING and s.cuttable
        if it.kind in ("audit", "broll"):
            if it.ref in self.ctrl.project.review_ok:
                return False
            if it.kind == "broll" or (it.data or {}).get("target"):
                return self._clip_of(it) is not None   # (el clip ya no está: resuelto de otra forma)
            return True
        return self._junction(it) is not None

    def _fix_of(self, it: Item) -> tuple[str, object] | None:
        """Lo que propone la IA para un aviso o un B-roll dudoso: («otro clip», (a, b)) | («rellenar», (pista, a, b))."""
        from ..core.model import ORIGIN_AI
        p = self.ctrl.project
        c = self._clip_of(it)
        if c is not None:
            if (self._capa(c) and c.origin == ORIGIN_AI and not c.locked
                    and (it.kind == "broll" or (it.data or {}).get("category") in
                         ("Repetición", "Ritmo", "Continuidad", "Imagen"))):
                return "otro clip", (float(c.start), float(c.start + c.duration), c.track_id)
            return None
        if it.kind == "audit" and (it.data or {}).get("category") == "Imagen" and it.t is not None:
            vt = [t for t in p.tracks if t.kind == "video"]
            if not vt:
                return None
            ids = {t.id for t in vt}
            segs = [(c2.start, c2.start + c2.duration) for c2 in p.clips.values() if c2.track_id in ids]
            t = it.t + 0.05
            if any(a <= t < b for a, b in segs):
                return None                        # (ya no hay negro ahí)
            a = max([b for _a, b in segs if b <= t], default=0.0)
            b = min([a2 for a2, _b in segs if a2 >= t], default=None)
            if b is not None and b - a >= 0.3:
                return "rellenar", (vt[-1].id, float(a), float(b))   # el negro exacto, en la pista principal
        return None

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
        elif it.kind in ("audit", "broll"):
            self.timeline.set_highlight_suggestion("")
            d = it.data or {}
            c = self._clip_of(it)
            if c is not None:
                self.timeline.set_selection([c.id])
            if it.kind == "broll":
                nombre = p.media[c.media_id].name if c is not None and c.media_id in p.media else "clip"
                self.title.setText(f"🎞 B-roll dudoso · {fmt_time(it.t)}")
                self.why.setText(f"La IA puso «{nombre}» solo porque se parece a lo que dices"
                                 + (f" ({d.get('reason')})" if d.get("reason") else "") + ". ¿Encaja?")
            else:
                cat = d.get("category", "Aviso")
                self.title.setText(f"{AUDIT_ICON.get(cat, '⚠')} {cat} · {fmt_time(it.t)}")
                self.why.setText(d.get("message", "") + (f"\n{d['detail']}" if d.get("detail") else ""))
            self.words.setText(self._said_near(it.t))
            if valid:
                fix = self._fix_of(it)
                self.sugg.setText({"otro clip": "💡 Enter: la IA pone otro clip en este tramo",
                                   "rellenar": "💡 Enter: la IA rellena este hueco con B-roll"}.get(
                    fix[0] if fix else "", "💡 Arréglalo en la línea de tiempo si hace falta; O = está bien así, "
                                           "→ = seguir.") + ("  ·  Supr: quitar este clip" if c is not None else ""))
                self.sugg.show()
            else:
                self.why.setText("Este ya está resuelto o lo diste por bueno.")
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
        elif it.kind in ("audit", "broll"):
            f2 = self._fix_of(it) if valid else None
            self.btn_accept.setText("🔁 Otro clip" if f2 and f2[0] == "otro clip" else
                                    "✚ Rellenar" if f2 else "✓ Aceptar")
        else:
            self.btn_accept.setText("✓ Aceptar")
        self.btn_reject.setText("✕ Quitar clip" if it.kind in ("audit", "broll") else "✗ Rechazar")
        for b in (self.btn_accept, self.btn_reject):
            b.setEnabled(valid)
        if it.kind in ("audit", "broll"):
            self.btn_accept.setEnabled(valid and self._fix_of(it) is not None)
            self.btn_reject.setEnabled(valid and self._clip_of(it) is not None)
        self.btn_ok.setEnabled(valid and it.kind != "sug")
        self.btn_listen.setEnabled(it.t is not None)
        self.btn_prev.setEnabled(self.i > 0)
        self.btn_next.setEnabled(True)
        self.setFocus()
        self._listen()

    def _said_near(self, t: float | None) -> str:
        """Lo que dices en la narración alrededor de ese momento (para decidir sin escuchar)."""
        if t is None:
            return ""
        p = self.ctrl.project
        try:
            dentro = []
            for c in p.clips.values():
                if c.media_id in p.transcripts and c.start - 0.01 <= t <= c.start + c.duration + 0.01:
                    src = c.source_in + (t - c.start) * float(getattr(c, "speed", 1.0) or 1.0)
                    ws = _words(p, c.media_id)
                    antes = [str(w[2]) for w in ws if src - 4.0 <= float(w[0]) <= src][-CONTEXT:]
                    despues = [str(w[2]) for w in ws if src < float(w[0]) <= src + 4.0][:CONTEXT]
                    dentro.append(f"…{' '.join(antes)} ▸ {' '.join(despues)}…")
                    break
            return dentro[0] if dentro else ""
        except Exception:  # noqa: BLE001 - sin contexto, se decide escuchando
            return ""

    def _show_summary(self):
        self.finished = True
        n = len(self.queue)
        p = self.ctrl.project
        acc = sum(1 for v in self.done.values() if v in ("aceptada", "bien así"))
        rej = sum(1 for v in self.done.values() if v in ("rechazada", "quitada"))
        ia = sum(1 for v in self.done.values() if v == "pedida a la IA")
        other = sum(1 for it in self.queue if self._key(it) not in self.done and not self._valid(it))
        undecided = n - len(self.done) - other
        self.title.setText("Revisión terminada" if n else "Nada que revisar")
        self.counter.setText(f"{n} de {n}" if n else "0")
        self.bar.setValue(len(self.done))
        self.why.setText("")
        self.words.setText("")
        self.note.setText("" if n else "No hay nada dudoso: ni propuestas pendientes, ni cortes, ni avisos. "
                                       "(¿Ya transcribiste y analizaste la narración?)")
        dur1 = p.duration()
        lines = [f"Aceptadas {acc}, rechazadas {rej}, sin decidir {undecided}"
                 + (f", pedidas a la IA {ia}" if ia else "")
                 + (f", resueltas de otra forma {other}" if other else "") + "."]
        if getattr(self, "_generales", 0):
            lines.append(f"Hay {self._generales} aviso(s) generales sin momento concreto: míralos en la lista de avisos "
                         "(Ctrl+R).")
        if getattr(self, "_audit_err", ""):
            lines.append(f"No pude revisar los avisos del proyecto: {self._audit_err}")
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
        if it.kind in ("audit", "broll"):
            fix = self._fix_of(it)
            if fix is None:
                self.note.setText("Aquí la IA no tiene arreglo automático: arréglalo en la línea de tiempo, O = está "
                                  "bien así, → = seguir.")
                return
            if self._ia_ocupada():
                self.note.setText("La IA sigue con el anterior: espera a que termine (O y → sí funcionan).")
                return
            if fix[0] == "otro clip":
                a, b, tr = fix[1]
                self.timeline.gap_ai_requested.emit(tr, a, b, True)   # la IA rehace ese tramo EN la pista del clip
            else:
                tr, a, b = fix[1]
                self.timeline.gap_ai_requested.emit(tr, a, b, True)   # la IA rellena el negro
            if not self._ia_ocupada():
                self.note.setText("La IA no pudo empezar (mira el aviso de la barra de estado o del panel IA ✨).")
                return
            self._record(it, "pedida a la IA")
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
        if it.kind == "sug":
            self.note.setText("Para dejar el audio como está, Supr (rechazar); para cortarlo, Enter.")
            return
        if not self._valid(it):
            self.note.setText("Este ya no está o lo diste por bueno: salta a la siguiente con →.")
            return
        if it.kind in ("audit", "broll"):
            self.ctrl.approve_review(it.ref)
            self._record(it, "bien así")
            return
        self.ctrl.approve_cut(it.ref)
        self._record(it, "aceptada")

    def _reject(self):
        if self.finished or not self.queue:
            return
        it = self.queue[self.i]
        if it.kind in ("audit", "broll"):
            c = self._clip_of(it) if self._valid(it) else None
            if c is None or not self._capa(c):
                self.note.setText("Aquí no hay un clip de encima que quitar (la voz, la música y la pista principal "
                                  "no se quitan desde aquí): O = está bien así, → = seguir.")
                return
            if self._ia_ocupada():
                self.note.setText("La IA sigue con el anterior: espera a que termine (O y → sí funcionan).")
                return
            if not self.ctrl.delete_clips(self.ctrl.linked_ids([c.id]), False):
                self.note.setText("No se pudo quitar (¿está bloqueado?).")
                return
            self._record(it, "quitada")
            return
        if it.kind == "cut":
            if self._valid(it):
                if getattr(self.win, "cut_fix", None) is None:     # (antes fallaba si el panel aún no se había abierto)
                    from .cut_fix import CutFixPanel
                    self.win.cut_fix = CutFixPanel(self.win)
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
        while self.i < len(self.queue) and self._key(self.queue[self.i]) not in self.done \
                and not self._valid(self.queue[self.i]):
            self.i += 1                            # (lo que se resolvió por el camino, fuera)
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
        elif it.kind in ("audit", "broll"):
            c = self._clip_of(it)
            if c is not None:
                start, end = c.start - 0.5, min(c.start + c.duration, c.start + MAX_SPAN) + 0.5
            elif it.t is not None:
                start, end = it.t - 2.0, it.t + 2.0
            else:
                return
        else:
            if it.t is None:
                return
            start, end = it.t - PAD, it.t + PAD
        self.engine.play_ranges([(max(0.0, start), end)])

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
