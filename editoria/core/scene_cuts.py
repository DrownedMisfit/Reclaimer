"""
✂ Cambios de escena (sin IA): dónde la imagen cambia DE GOLPE — un corte de cámara en una cinemática, el paso
a otra escena, abrir el menú de pausa… FFmpeg compara cada fotograma con el anterior (a 320 px: rápido) y da
una «puntuación de cambio»; por encima del umbral, hay corte. Los destellos muy seguidos (< 0,5 s) no cuentan.

  detect(path, a, b, sensitivity) -> [segundos del ARCHIVO donde hay un corte]
sensitivity: "normal" (cortes claros) · "alta" (también cambios más suaves, p. ej. un menú encima del juego)
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import media as media_tools
from .paths import cache_dir

THRESHOLD = {"normal": 0.30, "alta": 0.18}
MIN_GAP = 0.5


def _scores(path: str, a: float, b: float, progress=None, cancelled=None) -> list[tuple[float, float]]:
    """[(segundo del archivo, puntuación de cambio)] de los fotogramas que cambian algo (≥ 0,1)."""
    key = f"{media_tools.cache_key(path)}_{a:.2f}_{b:.2f}.json"
    cf = os.path.join(str(cache_dir("escenas")), key)
    try:
        with open(cf, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)]
    except (OSError, ValueError):
        pass
    meta = cf + ".txt"
    dur = max(0.05, b - a)
    vf = f"scale=320:-2,select='gt(scene\\,0.10)',metadata=print:file='{meta.replace(chr(92), '/').replace(':', chr(92) + ':')}'"
    p = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{dur:.3f}",
                          "-skip_loop_filter", "all",   # ⚡ sin filtro de desbloqueo: ~25 % más rápido; en imágenes pequeñas para analizar no cambia nada
                          "-i", path, "-an", "-vf", vf, "-f", "null", "-progress", "pipe:1", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in p.stdout:
        if cancelled is not None and cancelled():
            p.kill()
            p.wait()
            raise RuntimeError("Cancelado.")
        if line.startswith("out_time_us=") and progress:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1e6 / dur))
            except ValueError:
                pass
    err = p.stderr.read()
    if p.wait() != 0:
        raise RuntimeError("No se pudo leer el video: " + err.strip()[-200:])
    out = []
    t = None
    try:
        with open(meta, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.search(r"pts_time:([\d.]+)", line)
                if m:
                    t = float(m.group(1))
                m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
                if m and t is not None:
                    out.append((round(a + t, 3), round(float(m.group(1)), 4)))
        os.remove(meta)
    except OSError:
        pass
    try:
        with open(cf, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


def detect(path: str, a: float, b: float, sensitivity: str = "normal", progress=None, cancelled=None) -> list[float]:
    th = THRESHOLD.get(sensitivity, 0.30)
    cuts: list[float] = []
    for t, sc in _scores(path, a, b, progress, cancelled):
        if sc < th or t - a < MIN_GAP or b - t < MIN_GAP:
            continue
        if cuts and t - cuts[-1] < MIN_GAP:
            continue
        cuts.append(t)
    return cuts
