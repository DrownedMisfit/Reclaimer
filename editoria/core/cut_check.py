"""
Revisión de los CORTES de audio de la línea de tiempo («líneas rojas»).

Un corte es el sitio donde dos clips de audio del MISMO archivo quedan pegados en la línea de tiempo, pero en el
archivo hay un salto entre ellos (se quitó un silencio o un trozo). Si ese corte se hizo mal, se come parte de una
palabra o queda pegado a ella, o suena con la voz todavía sonando. Aquí se detectan esos casos y se propone cómo
arreglarlos (`fix`); no se cambia nada.

Sin Qt: se puede usar en pruebas y en la línea de tiempo.
"""
from __future__ import annotations

import bisect

import numpy as np

from . import mapping
from .media import PEAK_RATE
from .model import TRACK_AUDIO, Project

MIN_SKIP = 0.02        # un salto más corto que esto no es un corte (son el mismo sitio)
WORD_EDGE = 0.03       # margen para decidir si una palabra se corta o queda pegada (segundos)
WORD_PAD = 0.05        # margen que deja la sugerencia tras una palabra o antes de ella (segundos)
MIN_NUDGE = 0.03       # la sugerencia de «pegado» recupera al menos esto (segundos)
EDGE_MS = 25           # ventana de sonido justo en el borde del corte (milisegundos)
QUIET_MS = 20          # un trozo «en silencio» dura al menos esto (milisegundos)
QUIET_SEARCH = 0.3     # buscando silencio, como mucho esto hacia dentro del hueco quitado (segundos)
VOICE_PAD = 0.02       # margen tras el primer silencio que se encuentra (segundos)
NOISE_MULT = 6.0       # «voz» = pico por encima de este múltiplo del ruido de fondo del archivo…
LOUD_FLOOR = 0.05      # …y por encima de -26 dBFS (≈0.05)

_THRESHOLDS: dict[int, tuple[np.ndarray, float]] = {}   # caché: id(picos) → (picos, umbral)


def _threshold(arr: np.ndarray) -> float:
    """Umbral de «voz sonando»: ruido de fondo del archivo (percentil 20 de sus picos) × 6, sin bajar de -26 dBFS."""
    hit = _THRESHOLDS.get(id(arr))
    if hit is not None and hit[0] is arr:
        return hit[1]
    thr = max(float(np.percentile(arr, 20)) * NOISE_MULT, LOUD_FLOOR)
    if len(_THRESHOLDS) > 64:
        _THRESHOLDS.clear()
    _THRESHOLDS[id(arr)] = (arr, thr)
    return thr


def junctions(project: Project) -> list[dict]:
    """Cortes de audio de la línea de tiempo: dos clips seguidos del mismo archivo, pegados, con un salto en el archivo.
    Devuelve dicts con track_id, t (momento en la línea de tiempo), left_id, right_id, media_id, out (fin en el archivo
    del clip izquierdo) e in (inicio en el archivo del derecho)."""
    found = []
    for tr in project.tracks:
        if tr.kind != TRACK_AUDIO:
            continue
        clips = sorted((c for c in project.clips.values() if c.track_id == tr.id and not c.retimed),
                       key=lambda c: c.start)
        starts = [c.start for c in clips]
        for L in clips:
            j = bisect.bisect_left(starts, L.end - mapping.TOL)
            while j < len(clips) and starts[j] <= L.end + mapping.TOL:
                R = clips[j]
                j += 1
                if R.id == L.id or R.media_id != L.media_id or abs(R.start - L.end) > mapping.TOL:
                    continue
                out = L.source_in + L.duration
                if R.source_in - out <= MIN_SKIP:
                    continue
                found.append({"track_id": tr.id, "t": L.end, "left_id": L.id, "right_id": R.id,
                              "media_id": L.media_id, "out": out, "in": R.source_in})
    found.sort(key=lambda d: d["t"])
    return found


def junction_at(project: Project, track_id: str, t: float, tol: float = 0.01) -> dict | None:
    """El corte de esa pista justo en t (o None si ya no está)."""
    for d in junctions(project):
        if d["track_id"] == track_id and abs(d["t"] - t) <= tol:
            return d
    return None


def junction_key(j: dict) -> str:
    """Clave estable de un corte: sirve para recordar que el usuario lo dio por bueno («✓ Está bien así»)."""
    return f"{j['media_id']}|{j['out']:.3f}|{j['in']:.3f}"


class _Words:
    """Palabras de la transcripción de un archivo, ordenadas por inicio."""

    def __init__(self, words: list):
        self.w = sorted((w for w in words if len(w) >= 2), key=lambda w: float(w[0]))
        self.starts = [float(w[0]) for w in self.w]


class _Ctx:
    def __init__(self, project: Project, peaks_fn):
        self.project = project
        self.peaks_fn = peaks_fn
        self._words: dict[str, _Words | None] = {}
        self._peaks: dict[str, tuple[np.ndarray, float] | None] = {}

    def words(self, media_id: str) -> _Words | None:
        if media_id not in self._words:
            ws = (self.project.transcripts.get(media_id) or {}).get("words") or []
            self._words[media_id] = _Words(ws) if ws else None
        return self._words[media_id]

    def peaks(self, media_id: str):
        if media_id not in self._peaks:
            arr = self.peaks_fn(media_id) if self.peaks_fn is not None else None
            if arr is None or len(arr) == 0:
                self._peaks[media_id] = None
            else:
                arr = np.asarray(arr, dtype=np.float32)
                self._peaks[media_id] = (arr, _threshold(arr))
        return self._peaks[media_id]


def _edge_peak(arr: np.ndarray, a: int, b: int) -> float:
    a, b = max(0, a), min(len(arr), b)
    return float(arr[a:b].max()) if b > a else 0.0


def _quiet_distance(arr: np.ndarray, thr: float, out: float, inn: float, side: str) -> float | None:
    """Distancia (s) desde el borde del corte hasta el primer trozo en silencio hacia dentro del hueco quitado
    (como mucho QUIET_SEARCH). side «antes»: se busca desde el final de la izquierda hacia el hueco; «despues»: desde
    el principio de la derecha hacia atrás. None si no hay silencio en ese tramo."""
    R = PEAK_RATE
    m = max(1, int(round(QUIET_MS * R / 1000)))         # muestras de la ventana en silencio
    a, b = int(round(out * R)), int(round(inn * R))     # el hueco, en muestras
    lim = int(round(QUIET_SEARCH * R))
    if side == "antes":
        for s in range(a, min(b - m, a + lim) + 1):
            if _edge_peak(arr, s, s + m) < thr:
                return (s - a) / R
    else:
        for s in range(b - m, max(a, b - lim) - 1, -1):
            if _edge_peak(arr, s, s + m) < thr:
                return (b - s) / R
    return None


def _judge(j: dict, ctx: _Ctx):
    """Motivos (textos en español), gravedad y posibles arreglos de un corte; None si está bien.
    Los arreglos son (lado, cuánto recupera, texto corto) sin topar con el hueco: lo elige _pick_fix."""
    reasons: list[str] = []
    cands: list[tuple[str, float, str]] = []
    severity = "media"
    out, inn = j["out"], j["in"]
    W = ctx.words(j["media_id"])
    if W is not None:
        starts, ws = W.starts, W.w
        # 1) una palabra cortada: el corte cae dentro de ella
        i_out = bisect.bisect_left(starts, out)
        for k in range(i_out - 1, max(-1, i_out - 9), -1):
            w = ws[k]
            if float(w[0]) < out < float(w[1]) - WORD_EDGE:
                reasons.append(f"Se corta el final de «{w[2]}»")
                cands.append(("antes", float(w[1]) + WORD_PAD - out, f" para no comerse «{w[2]}»"))
                severity = "alta"
                break
        i_in = bisect.bisect_left(starts, inn)
        for k in range(i_in - 1, max(-1, i_in - 9), -1):
            w = ws[k]
            if float(w[0]) + WORD_EDGE < inn < float(w[1]):
                reasons.append(f"Se corta el principio de «{w[2]}»")
                cands.append(("despues", inn - (float(w[0]) - WORD_PAD), f" para no comerse «{w[2]}»"))
                severity = "alta"
                break
        # 2) pegado: la palabra de antes termina justo en el corte, o la de después empieza justo en él
        for k in range(i_out - 1, max(-1, i_out - 5), -1):
            w = ws[k]
            if abs(out - float(w[1])) < WORD_EDGE:
                reasons.append(f"Sale demasiado pegado a «{w[2]}»")
                cands.append(("antes", max(MIN_NUDGE, WORD_PAD - abs(out - float(w[1]))),
                              f" (sale muy pegado a «{w[2]}»)"))
                break
        for k in range(i_in, min(len(ws), i_in + 4)):
            w = ws[k]
            if abs(float(w[0]) - inn) < WORD_EDGE:
                reasons.append(f"Entra demasiado pegado a «{w[2]}»")
                cands.append(("despues", max(MIN_NUDGE, WORD_PAD - abs(float(w[0]) - inn)),
                              f" (entra muy pegado a «{w[2]}»)"))
                break
    # 3) sonido: voz todavía sonando justo en el borde del corte
    pk = ctx.peaks(j["media_id"])
    if pk is not None:
        arr, thr = pk
        i = int(round(out * PEAK_RATE))
        before = _edge_peak(arr, i - EDGE_MS, i)
        j0 = int(round(inn * PEAK_RATE))
        after = _edge_peak(arr, j0, j0 + EDGE_MS)
        if max(before, after) > thr:
            reasons.append("El corte suena con la voz todavía sonando")
            severity = "alta"
            for side, loud in (("antes", before), ("despues", after)):
                if loud > thr:
                    d = _quiet_distance(arr, thr, out, inn, side)
                    if d is not None:
                        cands.append((side, d + VOICE_PAD, " (ahí la voz todavía suena)"))
    if not reasons:
        return None
    return reasons, severity, cands, inn - out


def _pick_fix(cands: list[tuple[str, float, str]], gap: float) -> dict | None:
    """La sugerencia que más recupera, sin pasar del silencio que se quitó. None si no hay ninguna."""
    best = None
    for side, delta, why in cands:
        d = min(round(delta, 3), gap)
        if d < 0.001:
            continue
        if best is None or d > best[1] + 1e-9:
            best = (side, d, why)
    if best is None:
        return None
    side, d, why = best
    lugar = "después del corte" if side == "despues" else "antes del corte"
    return {"side": side, "delta": d, "text": f"Recuperar {round(d * 1000)} ms {lugar}{why}"}


def check_junction(project: Project, j: dict, peaks_fn=None, _ctx: _Ctx | None = None) -> dict | None:
    """Aviso de UN corte (dict como los de check) o None si no tiene nada que revisar. No mira cut_ok.
    El aviso lleva «fix»: {side, delta, text} con la sugerencia (o None si no hay ninguna que proponer)."""
    res = _judge(j, _ctx or _Ctx(project, peaks_fn))
    if res is None:
        return None
    reasons, severity, cands, gap = res
    return dict(j, key=junction_key(j), reasons=reasons, severity=severity, fix=_pick_fix(cands, gap))


def check(project: Project, peaks_fn) -> list[dict]:
    """Avisos de todos los cortes de audio que el usuario aún no dio por buenos, ordenados por momento.
    peaks_fn(media_id) → picos de volumen (PEAK_RATE por segundo) o None. Sin transcripción solo se mira el sonido."""
    ok = set(project.cut_ok)
    ctx = _Ctx(project, peaks_fn)
    out = []
    for j in junctions(project):
        if junction_key(j) in ok:
            continue
        issue = check_junction(project, j, _ctx=ctx)
        if issue is not None:
            out.append(issue)
    return out
