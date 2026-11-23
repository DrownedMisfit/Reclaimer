"""
⬛ Imágenes negras (sin IA): dónde el video se queda COMPLETAMENTE en negro — un fundido a negro, una pantalla de
carga, un fotograma negro suelto… FFmpeg (blackdetect) mira cada fotograma a 160 px: si casi toda la imagen (98 %)
está por debajo de un gris muy oscuro, es negra. Un fondo negro con texto encima NO cuenta. Se guarda: la segunda
vez que abres el mismo video sale al momento.

  detect(path, duration) -> [[inicio, fin], …] en segundos del ARCHIVO (también los de un solo fotograma)
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import media as media_tools
from .paths import cache_dir

PIX_TH = 0.05        # lo oscuro que tiene que ser un píxel para contar como negro (0 = negro puro)
PIC_TH = 0.98        # qué parte de la imagen tiene que serlo


FILTER = f"scale=160:-2,blackdetect=d=0:pix_th={PIX_TH}:pic_th={PIC_TH}"   # (la lectura única usa el mismo)


def cache_file(path: str) -> str:
    return os.path.join(str(cache_dir("negros")), f"{media_tools.cache_key(path)}_{PIX_TH}_{PIC_TH}.json")


def cached(path: str) -> list[list[float]] | None:
    try:
        with open(cache_file(path), encoding="utf-8") as f:
            return [list(x) for x in json.load(f)]
    except (OSError, ValueError):
        return None


def save_from_log(path: str, txt: str) -> list[list[float]]:
    """Los tramos negros que escribió blackdetect en el registro de FFmpeg; se guardan."""
    out = [[round(float(a), 3), round(float(b), 3)]
           for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", txt)]
    try:
        with open(cache_file(path), "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


def detect(path: str, duration: float | None = None, progress=None, cancelled=None) -> list[list[float]]:
    got = cached(path)
    if got is not None:
        return got
    from ..ai import lectura_unica     # ⚡ una sola lectura del video para todos los análisis (ai/lectura_unica.py)
    if lectura_unica.usar(path, duration or 0.0, "negros"):
        lectura_unica.asegurar_o_seguir(path, duration or 0.0, ["negros"], cancelled,
                                        (lambda f, _t: progress(f)) if progress else None)
        got = cached(path)
        if got is not None:
            return got
    cf = cache_file(path)
    log = cf + ".log"                         # (a un archivo: por una tubería, un video con mucho negro la llenaba)
    with open(log, "w", encoding="utf-8", errors="replace") as lf:
        p = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "info", "-nostats",
                              "-skip_loop_filter", "all",   # ⚡ como en las escenas: más rápido y para esto da igual
                              "-i", path, "-an", "-sn",
                              "-vf", FILTER,
                              "-f", "null", "-progress", "pipe:1", "-"],
                             stdout=subprocess.PIPE, stderr=lf, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in p.stdout:
            if cancelled is not None and cancelled():
                p.kill()
                p.wait()
                raise RuntimeError("Cancelado.")
            if line.startswith("out_time_us=") and progress and duration:
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        rc = p.wait()
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        os.remove(log)
    except OSError:
        txt = ""
    if rc != 0:
        raise RuntimeError("No se pudo leer el video: " + txt.strip()[-200:])
    return save_from_log(path, txt)
