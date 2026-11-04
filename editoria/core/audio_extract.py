"""
«🎵 Convertir en solo audio» (Medios): saca el sonido de un video a un archivo de audio.

Sin perder calidad: si el sonido ya es AAC o MP3 (lo normal en videos de YouTube) se COPIA tal cual (rápido,
idéntico); si no, se convierte a AAC 256 kbps. Va a la carpeta «Audio extraído» de Reclaimer (nunca junto a tus
originales), con el nombre del video.
"""
from __future__ import annotations

import os
import re
import subprocess

from . import media as media_tools
from .paths import PROGRAM_DIR

COPY = {"aac": ".m4a", "mp3": ".mp3"}      # códecs que se copian sin tocar


def out_dir() -> str:
    from .paths import app_data_dir
    base = app_data_dir() if os.environ.get("EDITORIA_DATOS") else PROGRAM_DIR   # (las pruebas: su carpeta)
    d = base / "Audio extraído"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def audio_codec(path: str) -> str | None:
    r = subprocess.run([media_tools.ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=codec_name", "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    c = (r.stdout or "").strip().splitlines()
    return c[0].strip() if c else None


def _free_name(folder: str, stem: str, ext: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*]+', " ", stem).strip() or "audio"
    p = os.path.join(folder, stem + ext)
    n = 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return p


def extract(path: str, duration: float = 0.0, progress=None, cancelled=None, folder: str | None = None) -> str:
    """Saca el audio de `path`. Devuelve la ruta del archivo nuevo. progress(fracción 0–1)."""
    codec = audio_codec(path)
    if not codec:
        raise ValueError(f"«{os.path.basename(path)}» no tiene sonido.")
    copy = codec in COPY
    ext = COPY.get(codec, ".m4a")
    out = _free_name(folder or out_dir(), os.path.splitext(os.path.basename(path))[0], ext)
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", path, "-vn", "-sn", "-dn", "-map", "0:a:0"]
    args += ["-c:a", "copy"] if copy else ["-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    if ext == ".m4a":
        args += ["-movflags", "+faststart"]
    args += ["-progress", "pipe:1", out]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for line in proc.stdout:
            if cancelled is not None and cancelled():
                proc.kill()
                break
            if line.startswith("out_time_us=") and duration > 0 and progress is not None:
                try:
                    progress(min(0.999, int(line.split("=", 1)[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if cancelled is not None and cancelled():
        if os.path.exists(out):
            os.remove(out)
        from ..ai.base import Cancelled
        raise Cancelled()
    if proc.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        err = (proc.stderr.read() if proc.stderr else "")[-300:]
        if os.path.exists(out):
            os.remove(out)
        raise RuntimeError(f"No se pudo sacar el audio de «{os.path.basename(path)}». {err}".strip())
    return out
