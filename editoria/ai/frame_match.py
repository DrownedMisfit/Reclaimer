"""
«¿Dónde sale?» dentro de UN clip: cuánto se parece cada momento a lo que escribiste (y a tus ✓/✗), para pintarlo
en la barra de tiempo de la ventana «🎯 Ejemplo» y saltar de un sitio probable al siguiente.

Puro numpy (las huellas y el vector del texto se calculan antes, en segundo plano).
"""
from __future__ import annotations

import numpy as np


def _unit(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float32)
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


def _z(s: np.ndarray) -> np.ndarray:
    return (s - s.mean()) / (s.std() + 1e-6) if len(s) > 1 else np.zeros_like(s)


def curve(vecs, text_vec=None, pos=None, neg=None) -> np.ndarray:
    """Nivel 0–1 por fotograma: dónde más se parece (comparado con el resto del clip)."""
    v = _unit(vecs)
    n = len(v)
    if n == 0:
        return np.zeros(0, np.float32)
    zt = _z(v @ _unit(text_vec)) if text_vec is not None else None
    mu = v.mean(0)
    c = _unit(v - mu)                       # centrado: lo que distingue cada plano dentro del clip
    if pos is not None and len(pos):        # tus ✓ mandan; el texto solo ayuda un poco
        p = _unit(np.asarray(pos, np.float32) - mu)
        z = _z((c @ p.T).max(1)) + (0.35 * zt if zt is not None else 0.0)
    elif zt is not None:
        z = zt
    else:
        return np.zeros(n, np.float32)
    if neg is not None and len(neg):
        q = _unit(np.asarray(neg, np.float32) - mu)
        z = z - 0.7 * np.clip(_z((c @ q.T).max(1)), 0, None)
    z = np.asarray(z, np.float32)
    if n >= 3:                              # un poco de suavizado (un fotograma suelto no es una aparición)
        z = np.convolve(np.pad(z, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
    return (1.0 / (1.0 + np.exp(-2.2 * (z - 0.9)))).astype(np.float32)


def peaks(times, levels, thr: float = 0.5, gap: float = 1.5) -> list[float]:
    """Los momentos más probables: el mejor de cada tramo por encima del umbral (en orden de tiempo)."""
    out: list[tuple[float, float]] = []
    cur: tuple[float, float] | None = None
    last_t = None
    for t, lv in zip(times, levels):
        t, lv = float(t), float(lv)
        if lv >= thr:
            if cur is not None and last_t is not None and t - last_t <= gap:
                if lv > cur[1]:
                    cur = (t, lv)
            else:
                if cur is not None:
                    out.append(cur)
                cur = (t, lv)
            last_t = t
    if cur is not None:
        out.append(cur)
    return [t for t, _ in out]


def level_at(times, levels, t: float) -> float:
    if times is None or not len(times):
        return 0.0
    k = int(np.argmin(np.abs(np.asarray(times) - t)))
    return float(levels[k])
