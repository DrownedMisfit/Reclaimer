"""
▭ Barras negras de un video (sin IA): las franjas negras de los lados o de arriba/abajo que trae el archivo (un juego
4:3 dentro de un video 16:9, una película panorámica…). FFmpeg (cropdetect) mira varios momentos repartidos por el
video y se queda con la zona MÁS GRANDE que tiene imagen: así una escena oscura (Silent Hill) no hace que se recorte
de más. Se guarda: la segunda vez sale al momento.

  detect(path, duration) -> [izquierda, arriba, ancho, alto] en fracciones 0–1 de la zona con imagen, o None si el
                            video no tiene barras (o son tan finas que no merece la pena)
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import media as media_tools
from .paths import cache_dir

SAMPLES = 8            # momentos que se miran (repartidos por el video)
MIN_BAR = 0.02         # menos de un 2 % por lado no cuenta como barra
VERSION = 1


def _probe_size(path: str) -> tuple[int, int]:
    r = subprocess.run([media_tools.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0:s=x", path], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        w, h = (int(x) for x in r.stdout.strip().splitlines()[0].split("x")[:2])
        return w, h
    except (ValueError, IndexError):
        return 0, 0


def _crop_at(path: str, t: float) -> tuple[int, int, int, int] | None:
    """La zona con imagen en 2 s a partir de t (w, h, x, y en píxeles del archivo), según cropdetect."""
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "info", "-ss", f"{t:.2f}", "-i", path, "-t", "2",
                               "-an", "-sn", "-vf", "fps=4,cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                              timeout=120)
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr.decode(errors="replace"))
    if not found:
        return None
    w, h, x, y = (int(v) for v in found[-1])
    return (w, h, x, y) if w > 8 and h > 8 else None


def detect(path: str, duration: float = 0.0) -> list[float] | None:
    key = f"{media_tools.cache_key(path)}_v{VERSION}.json"
    cf = os.path.join(str(cache_dir("barras")), key)
    try:
        with open(cf, encoding="utf-8") as f:
            return json.load(f)["area"]
    except (OSError, ValueError, KeyError):
        pass
    W, H = _probe_size(path)
    area = None
    if W > 0 and H > 0:
        d = max(0.0, duration - 2.0)
        times = [d * (i + 0.5) / SAMPLES for i in range(SAMPLES)] if d > 0 else [0.0]
        crops = [c for c in (_crop_at(path, t) for t in times) if c is not None and c[0] * c[1] >= 0.15 * W * H]
        x0 = y0 = x1 = y1 = 0
        if crops:
            # Cada borde, hacia fuera pero sin fiarse de un momento suelto: una escena oscura recorta de más y una
            # pantalla en negro o un fundido dan cualquier cosa; se ignora la cuarta parte más extrema de cada lado
            q = len(crops) // 4
            x0 = sorted(c[2] for c in crops)[q]
            y0 = sorted(c[3] for c in crops)[q]
            x1 = sorted((c[2] + c[0] for c in crops), reverse=True)[q]
            y1 = sorted((c[3] + c[1] for c in crops), reverse=True)[q]
        if x1 > x0 and y1 > y0:
            l, t_, r, b = x0 / W, y0 / H, 1 - x1 / W, 1 - y1 / H
            # solo las barras de verdad: por pares (izquierda+derecha o arriba+abajo) y de al menos un 2 %
            side = min(l, r) >= MIN_BAR
            topb = min(t_, b) >= MIN_BAR
            if side or topb:
                l, r = (l, r) if side else (0.0, 0.0)
                t_, b = (t_, b) if topb else (0.0, 0.0)
                area = [round(l, 4), round(t_, 4), round(1 - l - r, 4), round(1 - t_ - b, 4)]
    try:
        with open(cf, "w", encoding="utf-8") as f:
            json.dump({"area": area}, f)
    except OSError:
        pass
    return area


def size_without(m, area: list[float] | None) -> tuple[int, int]:
    """El tamaño del video quitando las barras (para encuadrarlo)."""
    if not area:
        return m.width, m.height
    return max(2, int(round(m.width * area[2]))), max(2, int(round(m.height * area[3])))


def of(box: dict | None) -> list[float] | None:
    """Las barras quitadas de un clip (están en su colocación: layout["bars"]), o None."""
    a = (box or {}).get("bars")
    return [float(v) for v in a] if a and len(a) == 4 and (a[2] < 0.999 or a[3] < 0.999) else None
