"""
Mejorar la imagen de un clip (como en Resolve Studio): reducir ruido, estabilizar y detectar cortes de escena.
Todo con FFmpeg, en tu PC.

  Clip.fx["denoise"] = 0–1                → hqdn3d al exportar
  Clip.fx["stab"] = {"amount": 0–1, "trf": análisis, "src": [inicio, duración]}
                                          → vidstab (2 pasadas); si el clip cambió, deshake (1 pasada)
  scene_cuts(ruta, inicio, duración)      → segundos (del archivo) donde cambia el plano
"""
from __future__ import annotations

import os
import re
import subprocess

from . import media as media_tools
from .media import cache_key
from .paths import cache_dir


def denoise_filter(amount: float) -> str:
    a = max(0.0, min(1.0, float(amount)))
    if a <= 0:
        return ""
    return f"hqdn3d={1.5 + 6 * a:.2f}:{1.0 + 4.5 * a:.2f}:{3 + 9 * a:.2f}:{2.0 + 7 * a:.2f},"


def _vidstab_path(path: str) -> str:
    """Ruta escrita como la entiende un filtro de FFmpeg (igual que en los subtítulos): C\\:/carpeta/archivo."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "")


def trf_path(path: str, start: float, dur: float) -> str:
    return os.path.join(str(cache_dir("estabilizar")), f"{cache_key(path)}_{start:.3f}_{dur:.3f}.trf")


def analyze_stab(path: str, start: float, dur: float, progress=None, cancelled=None) -> str:
    """1ª pasada: mide cómo tiembla la imagen en ese trozo del archivo. Devuelve el archivo de análisis."""
    out = trf_path(path, start, dur)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    tmp = out + ".part"
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
            "-i", path, "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result='{_vidstab_path(tmp)}'",
            "-f", "null", "-"]
    if progress:
        progress(0.1, "Analizando cómo tiembla la imagen…")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            raise RuntimeError("Cancelado.")
        try:
            proc.wait(0.3)
        except subprocess.TimeoutExpired:
            pass
    err = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
    if proc.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError("No se pudo analizar el movimiento: " + err[-300:])
    os.replace(tmp, out)
    return out


def stab_filter(c) -> str:
    """2ª pasada (al exportar). Si el clip ya no usa el mismo trozo del análisis, estabilizador de 1 pasada."""
    st = (c.fx or {}).get("stab")
    if not isinstance(st, dict) or float(st.get("amount", 0)) <= 0:
        return ""
    amount = float(st["amount"])
    smooth = int(4 + 26 * amount)
    trf = st.get("trf")
    a, d = (st.get("src") or [None, None])[:2]
    same = a is not None and abs(a - c.source_in) < 0.02 and abs(d - c.src_len) < 0.05
    if trf and os.path.exists(trf) and same:
        return (f"vidstabtransform=input='{_vidstab_path(trf)}':smoothing={smooth}:optzoom=1:interpol=bicubic,"
                f"unsharp=5:5:0.6:3:3:0.3,")
    return "deshake=rx=32:ry=32,"


def scene_cuts(path: str, start: float, dur: float, sensitivity: str = "normal", cancelled=None) -> list[float]:
    """Cambios de plano (segundos DEL ARCHIVO) en [start, start+dur]. Es el MISMO detector que el clic derecho
    «✂ Cortar en los cambios de escena» (core/scene_cuts.py: rápido, se guarda, sensibilidad normal / alta)."""
    from . import scene_cuts as SC
    return SC.detect(path, start, start + dur, sensitivity if sensitivity in SC.THRESHOLD else "normal",
                     None, cancelled)
