"""
Ecualizador paramétrico por clip (como el del Inspector de DaVinci Resolve) y balance.

Cada clip puede tener 4 bandas. Cada banda: {"on", "type", "f" (Hz), "g" (dB), "q"}.
Tipos: "hp" (corte de graves), "lowshelf" (estante grave), "bell" (campana),
       "highshelf" (estante agudo), "lp" (corte de agudos).
La curva que se dibuja usa las mismas fórmulas (RBJ) que los filtros de FFmpeg que se
aplican al exportar, así que lo que ves es lo que se oye.
"""
from __future__ import annotations

import numpy as np

TYPES = {"hp": "Corte de graves", "lowshelf": "Estante grave", "bell": "Campana",
         "highshelf": "Estante agudo", "lp": "Corte de agudos"}
# Nombres cortos para las columnas B1…B6 (como en DaVinci Resolve)
TYPE_SHORT = {"hp": "⟋", "lowshelf": "▔╲", "bell": "◠", "highshelf": "╱▔", "lp": "⟍"}
CURVE_COLOR = "#3ec7d6"   # cian, como el ecualizador de Fairlight
BAND_COLORS = [CURVE_COLOR] * 6
F_MIN, F_MAX = 20.0, 20000.0
G_MAX = 24.0
N_BANDS = 6


def _b(on, t, f, g=0.0, q=1.0):
    return {"on": on, "type": t, "f": float(f), "g": float(g), "q": float(q)}


def default_bands() -> list[dict]:
    """6 bandas como en DaVinci Resolve: B1 corte de graves y B6 corte de agudos (apagados),
    B2 estante grave, B3–B4 campanas y B5 estante agudo."""
    return [_b(False, "hp", 80), _b(True, "lowshelf", 100, q=0.7), _b(True, "bell", 400),
            _b(True, "bell", 2500), _b(True, "highshelf", 8000, q=0.7), _b(False, "lp", 18000)]


PRESETS = {
    # Tu ajuste de DaVinci Resolve (captura del 11/09/2026): voz más grave, neutra y masculina
    "Mi voz": [_b(False, "hp", 97), _b(True, "lowshelf", 80, 0.0, 0.7), _b(True, "bell", 242, 4.2, 1.0),
               _b(True, "bell", 3500, 1.5, 1.0), _b(True, "highshelf", 20, 1.0, 0.7), _b(False, "lp", 19000)],
    "Plano": default_bands(),
    "Voz clara": [_b(True, "hp", 80, q=0.7), _b(True, "lowshelf", 100, q=0.7), _b(True, "bell", 250, -3.0, 1.2),
                  _b(True, "bell", 3500, 3.0, 1.0), _b(True, "highshelf", 10000, 2.0, 0.7), _b(False, "lp", 18000)],
    "Voz más grave": [_b(True, "hp", 70, q=0.7), _b(True, "lowshelf", 120, 2.5, 0.7), _b(True, "bell", 250, 3.0, 1.0),
                      _b(True, "bell", 3000, 1.0, 1.0), _b(True, "highshelf", 9000, -1.0, 0.7), _b(False, "lp", 18000)],
    "Quitar retumbe": [_b(True, "hp", 100, q=0.7), _b(True, "lowshelf", 100, q=0.7), _b(True, "bell", 200, -5.0, 1.4),
                       _b(True, "bell", 2500), _b(True, "highshelf", 8000, q=0.7), _b(False, "lp", 18000)],
    "Más brillo": [_b(False, "hp", 80), _b(True, "lowshelf", 100, q=0.7), _b(True, "bell", 400),
                   _b(True, "bell", 5000, 2.5, 0.8), _b(True, "highshelf", 9000, 4.0, 0.7), _b(False, "lp", 18000)],
    "Teléfono / radio": [_b(True, "hp", 400, q=0.9), _b(True, "lowshelf", 100, q=0.7), _b(True, "bell", 1200, 4.0, 1.0),
                         _b(True, "bell", 2500), _b(True, "highshelf", 8000, q=0.7), _b(True, "lp", 3200, q=0.9)],
}


def normalize(eq: dict | None) -> dict:
    """Siempre 6 bandas (los proyectos antiguos tenían 4: se añaden B1 y B6 apagados)."""
    if not eq:
        return {"on": False, "bands": default_bands()}
    bands = [dict(b) for b in eq.get("bands", [])]
    if len(bands) == 4:
        bands = [_b(False, "hp", 80)] + bands + [_b(False, "lp", 18000)]
    while len(bands) < N_BANDS:
        bands.append(default_bands()[len(bands)])
    return {"on": eq.get("on", True), "bands": bands[:N_BANDS]}


def is_active(eq: dict | None) -> bool:
    return bool(eq and eq.get("on", True) and any(
        b.get("on") and (b["type"] in ("hp", "lp") or abs(b.get("g", 0.0)) > 0.05) for b in eq.get("bands", [])))


# ------------------------------------------------------------ respuesta
def _biquad(b: dict, sr: float = 48000.0):
    """Coeficientes RBJ (los mismos que usa FFmpeg)."""
    f, g, q = float(b["f"]), float(b.get("g", 0.0)), max(0.1, float(b.get("q", 0.7)))
    A = 10 ** (g / 40)
    w0 = 2 * np.pi * min(f, sr * 0.49) / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    t = b["type"]
    if t == "bell":
        bb = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        aa = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif t in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(A) * alpha
        if t == "lowshelf":
            bb = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            aa = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            bb = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            aa = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    elif t == "hp":
        bb = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    else:  # lp
        bb = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    return np.array(bb) / aa[0], np.array(aa) / aa[0]


def band_response_db(b: dict, freqs: np.ndarray, sr: float = 48000.0) -> np.ndarray:
    bb, aa = _biquad(b, sr)
    z = np.exp(-1j * 2 * np.pi * freqs / sr)
    h = (bb[0] + bb[1] * z + bb[2] * z * z) / (aa[0] + aa[1] * z + aa[2] * z * z)
    return 20 * np.log10(np.abs(h) + 1e-12)


def response_db(eq: dict | None, freqs: np.ndarray) -> np.ndarray:
    total = np.zeros_like(freqs, dtype=float)
    if eq and eq.get("on", True):
        for b in eq.get("bands", []):
            if b.get("on"):
                total += band_response_db(b, freqs)
    return total


# ------------------------------------------------------------- FFmpeg
def ffmpeg_chain(eq: dict | None, pan: float = 0.0) -> str:
    """Filtros de FFmpeg para el EQ y el balance de un clip ('' si no hay nada)."""
    parts = []
    if is_active(eq):
        for b in eq["bands"]:
            if not b.get("on"):
                continue
            f, g, q = b["f"], b.get("g", 0.0), max(0.1, b.get("q", 0.7))
            t = b["type"]
            if t == "bell" and abs(g) > 0.05:
                parts.append(f"equalizer=f={f:.1f}:t=q:w={q:.3f}:g={g:.2f}")
            elif t == "lowshelf" and abs(g) > 0.05:
                parts.append(f"lowshelf=f={f:.1f}:t=q:w={q:.3f}:g={g:.2f}")
            elif t == "highshelf" and abs(g) > 0.05:
                parts.append(f"highshelf=f={f:.1f}:t=q:w={q:.3f}:g={g:.2f}")
            elif t == "hp":
                parts.append(f"highpass=f={f:.1f}:p=2:t=q:w={q:.3f}")
            elif t == "lp":
                parts.append(f"lowpass=f={f:.1f}:p=2:t=q:w={q:.3f}")
    if abs(pan) > 0.01:
        # Balance: atenúa el lado contrario (-1 = todo a la izquierda, +1 = todo a la derecha)
        left, right = min(1.0, 1 - pan), min(1.0, 1 + pan)
        parts.append(f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1")
    return ",".join(parts)


def spectrum_db(samples: np.ndarray, sr: int, freqs: np.ndarray) -> np.ndarray:
    """Espectro medio de un trozo de audio (para dibujarlo detrás de la curva del EQ)."""
    n = 4096
    if len(samples) < n:
        return np.full_like(freqs, -90.0)
    hops = range(0, len(samples) - n, n // 2)
    win = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    count = 0
    for h in hops:
        acc += np.abs(np.fft.rfft(samples[h:h + n] * win)) ** 2
        count += 1
    spec = 10 * np.log10(acc / max(count, 1) + 1e-12)
    bins = np.fft.rfftfreq(n, 1 / sr)
    out = np.interp(freqs, bins, spec)
    return out - out.max()
