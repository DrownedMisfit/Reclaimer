"""
🔁 Convertir videos y audios (menú «Convertir»): a MP4 (H.264 + AAC, se abre en todas partes) o a MP3.

  · MP4: si el video ya es H.264/H.265 con audio AAC (o sin audio), solo se cambia el «envoltorio»: instantáneo y
    sin perder nada. Si no, se recodifica (tarjeta gráfica NVIDIA, AMD o Intel; si falla, el procesador) con buena calidad.
    Un audio pedido como «MP4» sale como .m4a (AAC).
  · MP3: 320 kbps.
Nunca toca el original: el resultado va a la carpeta que elijas, con el mismo nombre (y «(2)» si ya existe).
"""
from __future__ import annotations

import os
import subprocess

from . import media as media_tools
from .audio_extract import _free_name


def _codecs(path: str) -> tuple[str | None, str | None]:
    def one(sel):
        r = subprocess.run([media_tools.ffprobe(), "-v", "error", "-select_streams", sel, "-show_entries",
                            "stream=codec_name", "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout.strip().splitlines() or [None])[0]
    return one("v:0"), one("a:0")


def plan(path: str, fmt: str) -> tuple[str, list[str]]:
    """(extensión, argumentos de salida de FFmpeg) para convertir path a fmt ("mp4" | "mp3")."""
    v, a = _codecs(path)
    if fmt == "mp3":
        return ".mp3", ["-vn", "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "48000"]
    if v is None or v in ("mjpeg", "png"):          # audio (o portada): AAC en .m4a
        return ".m4a", ["-vn"] + (["-c:a", "copy"] if a == "aac" else ["-c:a", "aac", "-b:a", "256k"])
    if v in ("h264", "hevc") and a in (None, "aac"):
        return ".mp4", ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart"]
    return ".mp4", ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "{venc}", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]


def convert(path: str, fmt: str, folder: str, duration: float = 0.0, progress=None, cancelled=None) -> str:
    os.makedirs(folder, exist_ok=True)
    ext, outargs = plan(path, fmt)
    out = _free_name(folder, os.path.splitext(os.path.basename(path))[0], ext)
    from . import hw
    gpu = hw.video_encoder("h264")
    tries = ([hw.quality_args(gpu)] if gpu else []) + [["-c:v", "libx264", "-preset", "medium", "-crf", "18"]] \
        if "{venc}" in outargs else [[]]
    last = ""
    for venc in tries:
        args = []
        for x in outargs:
            if x == "-c:v" and venc:
                continue
            if x == "{venc}":
                args += venc
                continue
            args.append(x)
        cmd = [media_tools.ffmpeg(), "-nostdin", "-y", "-hide_banner", "-v", "error", "-progress", "pipe:1",
               "-i", path] + args + [out]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in p.stdout:
            if cancelled is not None and cancelled():
                p.kill()
                p.wait()
                try:
                    os.remove(out)
                except OSError:
                    pass
                raise RuntimeError("Cancelado.")
            if line.startswith("out_time_us=") and progress and duration > 0:
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        last = p.stderr.read()
        if p.wait() == 0:
            return out
    try:
        os.remove(out)
    except OSError:
        pass
    raise RuntimeError("No se pudo convertir: " + last.strip()[-300:])
