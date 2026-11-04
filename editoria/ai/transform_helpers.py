"""Ayudas para crear fotogramas clave de zoom desde los módulos de IA."""
from __future__ import annotations

from ..core import transform


def punch_keyframes(t: float, clip_in: float, clip_out: float, z: float, x: float, y: float,
                    hold: float = 2.5, ramp: float = 0.4) -> list[dict]:
    """Zoom rápido en el segundo t del archivo: acerca, mantiene y vuelve (todo dentro del clip)."""
    a = max(clip_in, t - ramp)
    b = max(a + 0.05, t)
    c = min(clip_out, b + hold)
    d = min(clip_out, c + ramp)
    kf = [{"t": round(a, 3), "z": 1.0, "x": x, "y": y},
          {"t": round(b, 3), "z": round(z, 3), "x": x, "y": y},
          {"t": round(c, 3), "z": round(z, 3), "x": x, "y": y}]
    if d - c > 0.05:
        kf.append({"t": round(d, 3), "z": 1.0, "x": x, "y": y})
    return transform.sorted_kf(kf)


def merge_window(existing: list[dict], new: list[dict]) -> list[dict]:
    """Sustituye las claves existentes dentro del tramo de las nuevas."""
    if not new:
        return existing
    a, b = new[0]["t"], new[-1]["t"]
    keep = [k for k in existing if k["t"] < a - 0.05 or k["t"] > b + 0.05]
    return transform.sorted_kf(keep + [dict(k) for k in new])
