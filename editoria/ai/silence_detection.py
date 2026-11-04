"""
Módulo de IA: DETECCIÓN DE SILENCIOS (y ruidos, respiraciones, saturación).

Funciona midiendo el volumen de la narración cada 10 ms. No necesita la
transcripción, pero si la hay la usa para no confundir palabras suaves con silencio.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

HOP = 0.01    # un valor de volumen cada 10 ms
FRAME = 0.02  # ventana de 20 ms


@dataclass
class Levels:
    db: np.ndarray       # volumen (dB) cada HOP segundos
    floor: float         # nivel de fondo (silencio de la sala)
    speech: float        # nivel típico de voz
    threshold: float     # por debajo de esto se considera silencio


def analyze_levels(samples: np.ndarray, sr: int) -> Levels:
    hop, win = int(sr * HOP), int(sr * FRAME)
    n = (len(samples) - win) // hop + 1
    if n <= 0:
        return Levels(np.full(1, -120.0), -120.0, -120.0, -120.0)
    cs = np.concatenate([[0.0], np.cumsum(samples.astype(np.float64) ** 2)])
    idx = np.arange(n) * hop
    rms = np.sqrt(np.maximum(cs[idx + win] - cs[idx], 0) / win)
    db = 20 * np.log10(rms + 1e-7)
    floor, speech = float(np.percentile(db, 5)), float(np.percentile(db, 95))
    threshold = floor + max(6.0, 0.3 * (speech - floor))
    return Levels(db, floor, speech, threshold)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Tramos consecutivos True: [(inicio, fin_exclusivo), ...]"""
    if len(mask) == 0:
        return []
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _fill_gaps(mask: np.ndarray, max_len: int) -> np.ndarray:
    """Rellena huecos False cortos dentro de tramos True (pequeños chasquidos)."""
    out = mask.copy()
    for a, b in _runs(~mask):
        if b - a <= max_len and a > 0 and b < len(mask):
            out[a:b] = True
    return out


def find_silences(levels: Levels, min_len: float) -> list[tuple[float, float]]:
    quiet = _fill_gaps(levels.db < levels.threshold, int(0.06 / HOP))
    half = FRAME / 2
    return [(a * HOP + half, b * HOP + half) for a, b in _runs(quiet)
            if (b - a) * HOP >= min_len]


def refine_word_times(words: list, levels: Levels) -> list:
    """
    Whisper a veces marca el inicio de una palabra unas décimas antes de que suene
    (o el final después). Aquí se ajustan los bordes al volumen real: si el borde
    cae en silencio, se mueve hasta donde empieza/termina el sonido.
    """
    quiet = _fill_gaps(levels.db < levels.threshold, int(0.06 / HOP))
    n = len(quiet)
    out = []
    for w in words:
        s, e = w[0], w[1]
        i0, i1 = int(s / HOP), min(n - 1, int(e / HOP))
        if 0 <= i0 < n and quiet[i0]:
            loud = np.flatnonzero(~quiet[i0:i1 + 1])
            if len(loud):
                s = max(s, (i0 + loud[0]) * HOP - 0.02)
        if 0 <= i1 < n and quiet[i1] and i1 > int(s / HOP):
            a = int(s / HOP)
            loud = np.flatnonzero(~quiet[a:i1 + 1])
            if len(loud):
                e = min(e, (a + loud[-1] + 1) * HOP + FRAME + 0.02)
        if e - s < 0.05:
            s, e = w[0], w[1]
        out.append([round(s, 3), round(e, 3)] + list(w[2:]))
    return out


def find_noises(levels: Levels, words: list, min_gap: float = 0.3,
                min_len: float = 0.12, margin: float = 0.1) -> list[tuple[float, float]]:
    """Sonidos entre palabras que no son palabras: respiraciones, golpes, ruidos."""
    if not words:
        return []
    loud = levels.db >= levels.threshold
    out = []
    bounds = [(0.0, words[0][0])] + [(words[i][1], words[i + 1][0]) for i in range(len(words) - 1)]
    for g0, g1 in bounds:
        g0, g1 = g0 + margin, g1 - margin
        if g1 - g0 < min_gap - 2 * margin:
            continue
        a, b = int(g0 / HOP), int(g1 / HOP)
        for r0, r1 in _runs(loud[a:b]):
            if (r1 - r0) * HOP >= min_len:
                out.append(((a + r0) * HOP, (a + r1) * HOP))
    return out


def find_clipping(samples: np.ndarray, sr: int, threshold: float = 0.985,
                  min_run: int = 3, join: float = 0.5) -> list[tuple[float, float]]:
    """Zonas donde el audio llegó al máximo y se distorsionó."""
    hot = np.abs(samples) >= threshold
    events = [a / sr for a, b in _runs(hot) if b - a >= min_run]
    regions: list[list[float]] = []
    for t in events:
        if regions and t - regions[-1][1] <= join:
            regions[-1][1] = t
        else:
            regions.append([t, t])
    return [(a - 0.05, b + 0.05) for a, b in regions]
