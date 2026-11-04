"""
Módulo de IA: ANÁLISIS DE MÚSICA.

Detecta los golpes (beats) y el tempo de una canción para que los cortes caigan
"a ritmo". Funciona con matemáticas sobre el audio (sin modelos que descargar):
  1. Mide los cambios bruscos de energía por bandas de frecuencia (onsets).
  2. Busca el periodo que más se repite (tempo).
  3. Coloca una rejilla de beats ajustada a los golpes reales.
"""
from __future__ import annotations

import numpy as np

SR = 22050
HOP = 512


def onset_envelope(samples: np.ndarray, sr: int = SR, hop: int = HOP) -> np.ndarray:
    """Cuánto "golpe" hay en cada instante (flujo espectral)."""
    win = 2048
    if len(samples) < win:
        return np.zeros(1)
    n = 1 + (len(samples) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = samples[idx] * np.hanning(win)[None, :]
    mag = np.log1p(10 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # quita la tendencia
    return np.maximum(flux, 0.0)


def estimate_tempo(env: np.ndarray, sr: int = SR, hop: int = HOP,
                   lo: float = 70.0, hi: float = 180.0) -> float:
    """Tempo en BPM (pulsaciones por minuto) por autocorrelación."""
    fps = sr / hop
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lags = np.arange(len(ac))
    valid = (lags >= fps * 60 / hi) & (lags <= fps * 60 / lo)
    if not valid.any():
        return 120.0
    # Ligera preferencia por tempos "normales" (~120 BPM) para evitar el doble o la mitad
    bpm = 60 * fps / np.maximum(lags, 1)
    weight = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = np.where(valid, ac * weight, -np.inf)
    return float(60 * fps / lags[int(np.argmax(score))])


def detect_beats(samples: np.ndarray, sr: int = SR) -> dict:
    """{"tempo": bpm, "beats": [segundos], "energy": [0–1 cada 0,1 s]}"""
    env = onset_envelope(samples, sr)
    fps = sr / HOP
    tempo = estimate_tempo(env, sr)
    period = fps * 60 / tempo
    # Rejilla: probar cada desfase posible y quedarse con el que cae sobre más golpes
    best_phase, best_score = 0, -1.0
    for phase in range(int(period)):
        pos = np.arange(phase, len(env), period).astype(int)
        score = float(env[pos].sum())
        if score > best_score:
            best_phase, best_score = phase, score
    beats = []
    for pos in np.arange(best_phase, len(env), period):
        p = int(pos)
        a, b = max(0, p - 2), min(len(env), p + 3)  # pequeño ajuste al golpe real más cercano
        # + media ventana: el golpe se detecta cuando entra en la ventana de análisis
        beats.append((a + int(np.argmax(env[a:b]))) / fps + 1024 / sr)
    block = int(sr * 0.1)
    n = len(samples) // block
    rms = np.sqrt((samples[: n * block].reshape(n, block) ** 2).mean(axis=1)) if n else np.zeros(1)
    energy = rms / (rms.max() + 1e-9)
    return {"tempo": round(tempo, 1), "beats": [round(b, 3) for b in beats], "energy": energy.round(3).tolist()}


def snap_points(cuts: list[float], beats: list[float], tolerance: float = 0.3,
                prefer: list[float] | None = None) -> dict[float, float]:
    """Para cada corte, el beat más cercano (si está a menos de `tolerance` segundos).
    prefer: golpes mejores (inicio de compás, golpes fuertes, drop): si hay uno casi igual de cerca, gana."""
    arr = np.array(beats)
    pref = np.array(prefer or [])
    out = {}
    if not len(arr):
        return out
    for c in cuts:
        k = int(np.abs(arr - c).argmin())
        best = float(arr[k]) if abs(arr[k] - c) <= tolerance else None
        if len(pref):
            j = int(np.abs(pref - c).argmin())
            dp = abs(pref[j] - c)
            if dp <= tolerance and (best is None or dp <= abs(best - c) + 0.12):
                best = float(pref[j])
        if best is not None:
            out[c] = best
    return out
