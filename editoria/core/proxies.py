"""
Resolución de la línea de tiempo (proxies), como «Timeline Proxy Resolution» de DaVinci Resolve.

Para que la edición vaya fluida con material pesado (1440p, 4K, 60 fps), el visor puede reproducir
copias ligeras de cada video a media resolución o a un cuarto. La exportación usa SIEMPRE los
archivos originales: la calidad final no cambia.

Las copias se crean una vez (en segundo plano) y se guardan en la caché.
"""
from __future__ import annotations

import os
import subprocess

from . import media as media_tools
from .paths import cache_dir

LEVELS = {"full": ("Completa", 1), "half": ("Media", 2), "quarter": ("Un cuarto", 4)}


def proxy_path(path: str, level: str) -> str:
    return str(cache_dir("proxies") / f"{media_tools.cache_key(path)}_{level}.mp4")


def has_proxy(path: str, level: str) -> bool:
    return level != "full" and os.path.exists(proxy_path(path, level))


_HW: bool | None = None


def hw_encoder() -> bool:
    """¿Hay codificador de video por hardware AMD (AMF)? Se comprueba una vez (una prueba de 2 fotogramas)."""
    global _HW
    if _HW is None:
        try:
            r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                       "color=s=256x144:d=0.1", "-c:v", "h264_amf", "-f", "null", "-"], timeout=20)
            _HW = r.returncode == 0
        except Exception:  # noqa: BLE001
            _HW = False
    return _HW


def _video_args(hw: bool) -> list[str]:
    if hw:      # la tarjeta gráfica: ~3× más rápido y casi sin usar el procesador (sigues editando fluido)
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "26", "-qp_p", "28",
                "-g", "15", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-g", "15", "-keyint_min", "15",
            "-pix_fmt", "yuv420p", "-threads", "4"]


def make_proxies(path: str, height: int, levels: list[str], cancelled=None, progress=None,
                 duration: float = 0.0) -> list[str]:
    """Crea de UNA pasada las copias ligeras de esos niveles (el video se lee una sola vez). Devuelve las rutas.
    GOP corto (una imagen clave cada 15 fotogramas): saltar por la copia es instantáneo."""
    want = [lv for lv in dict.fromkeys(levels) if LEVELS[lv][1] > 1 and not os.path.exists(proxy_path(path, lv))]
    if not want:
        return [proxy_path(path, lv) for lv in levels if LEVELS[lv][1] > 1]
    for hw in ([True, False] if hw_encoder() else [False]):
        outs = {lv: proxy_path(path, lv) for lv in want}
        tmps = {lv: o + ".tmp.mp4" for lv, o in outs.items()}
        scales = []
        for k, lv in enumerate(want):
            h = max(144, int(height / LEVELS[lv][1]) // 2 * 2) if height else 360
            scales.append(f"[s{k}]scale=-2:{h}[v{k}]")
        graph = (f"[0:v]split={len(want)}" + "".join(f"[s{k}]" for k in range(len(want))) + ";" + ";".join(scales)
                 if len(want) > 1 else scales[0].replace("[s0]", "[0:v]"))
        args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"]
        if hw:
            args += ["-hwaccel", "d3d11va"]               # también leer el video con la gráfica
        args += ["-i", path, "-filter_complex", graph]
        for k, lv in enumerate(want):
            args += ["-map", f"[v{k}]", "-map", "0:a?"] + _video_args(hw)
            args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmps[lv]]
        # sin prisa: prioridad baja (se hace mientras editas sin quitarte fluidez)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=flags, text=True)
        stopped = False
        for line in proc.stdout:      # el avance de verdad
            if cancelled is not None and cancelled():
                proc.kill()
                stopped = True
                break
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
        ok = not stopped and proc.returncode == 0 and all(os.path.exists(t) for t in tmps.values())
        if ok:
            for lv in want:
                os.replace(tmps[lv], outs[lv])
            return [proxy_path(path, lv) for lv in levels if LEVELS[lv][1] > 1]
        for t in tmps.values():
            if os.path.exists(t):
                os.remove(t)
        if stopped:
            return []
    return []


def make_proxy(path: str, height: int, level: str, cancelled=None, progress=None,
               duration: float = 0.0) -> str | None:
    """Crea la copia ligera (si no existe). Devuelve su ruta. progress(0–1) mientras la hace."""
    if LEVELS[level][1] == 1:
        return None
    out = make_proxies(path, height, [level], cancelled, progress, duration)
    return out[0] if out else None
