"""
Vúmetros: el nivel de sonido de cada pista (y el total) en un instante, calculado con las formas de onda
que el programa ya guarda (PEAK_RATE valores por segundo). No reproduce nada ni gasta memoria extra.
"""
from __future__ import annotations

import math

from .media import PEAK_RATE
from .model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Project


def _level(peaks, c, t: float) -> float:
    s = c.src_at(t - c.start)
    i = int(s * PEAK_RATE)
    if i < 0 or i >= len(peaks):
        return 0.0
    w = max(1, int(0.02 * PEAK_RATE))
    a, b = max(0, i - w), min(len(peaks), i + w + 1)     # un poco alrededor (±20 ms), como un medidor de picos
    from .curves import gain
    return float(peaks[a:b].max()) * gain(c, t)


def track_levels(p: Project, peaks: dict, t: float) -> dict[str, float]:
    """{id_pista: nivel 0–1+} de las pistas que suenan en t (con su volumen, solo y silencio)."""
    out: dict[str, float] = {}
    for tr in p.tracks:
        if tr.kind not in (TRACK_AUDIO, TRACK_VIDEO) or not p.audible(tr):
            continue
        c = p.clip_at(tr.id, t)
        m = p.media_of(c) if c else None
        if c is None or not c.enabled or m is None or c.speed <= 0 or m.id not in peaks:
            continue
        if tr.kind == TRACK_VIDEO and (c.link or m.kind != KIND_VIDEO or not m.has_audio):
            continue                     # su sonido va por su pista de audio
        if tr.kind == TRACK_AUDIO and not (m.kind == KIND_AUDIO or m.has_audio):
            continue
        out[tr.id] = _level(peaks[m.id], c, t)
    return out


def total(levels: dict[str, float]) -> float:
    """Suma aproximada de varias pistas (energía): dos pistas iguales = +3 dB."""
    return math.sqrt(sum(v * v for v in levels.values()))


def to_db(v: float) -> float:
    return 20 * math.log10(max(v, 1e-5))
