"""
Medir el volumen de un trozo de sonido (para «Normalizar volumen…», como en Resolve):
  measure(path, a, b) -> {"peak": dBFS del pico, "lufs": volumen percibido (LUFS integrado)}
gain_for(m, mode, target) -> cuántos dB subir/bajar:
  mode "peak"  → que el pico quede en target (p. ej. −1 dBFS)
  mode "lufs"  → que el volumen percibido quede en target (p. ej. −14 LUFS, lo de YouTube), sin pasar de −1 dBFS
"""
from __future__ import annotations

import re

from . import media as media_tools


def measure(path: str, a: float, b: float) -> dict | None:
    dur = max(0.05, b - a)
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-hide_banner", "-ss", f"{max(0.0, a):.3f}",
                               "-t", f"{dur:.3f}", "-i", path, "-vn", "-af", "ebur128=peak=true",
                               "-f", "null", "-"], timeout=600)
    txt = r.stderr.decode(errors="replace")
    summary = txt[txt.rfind("Summary:"):] if "Summary:" in txt else txt
    mi = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    mp = re.search(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS", summary)
    if not mi or not mp:
        return None
    to_f = lambda s: -120.0 if "inf" in s else float(s)   # noqa: E731
    return {"lufs": to_f(mi.group(1)), "peak": to_f(mp.group(1))}


def gain_for(m: dict, mode: str, target: float) -> float:
    if m["peak"] <= -100:           # silencio: no se toca
        return 0.0
    if mode == "peak":
        return target - m["peak"]
    g = target - m["lufs"]
    return min(g, -1.0 - m["peak"])   # sin saturar
