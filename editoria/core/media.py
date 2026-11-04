"""
Lectura de archivos multimedia con FFmpeg: información (duración, resolución, FPS),
miniaturas y forma de onda del audio. Todo se guarda en caché para no repetir trabajo.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .model import KIND_VIDEO
from .paths import cache_dir

# Evita que se abran ventanas negras de consola al llamar a FFmpeg en Windows.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

PEAK_RATE = 1000  # valores de forma de onda por segundo (1 ms: de cerca se ve dónde empieza y acaba cada palabra)


@functools.lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    # Ubicación típica cuando FFmpeg se instaló con winget.
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        for exe in packages.glob(f"*FFmpeg*/**/bin/{name}.exe"):
            return str(exe)
    return None


def ffmpeg() -> str:
    exe = find_tool("ffmpeg")
    if not exe:
        raise RuntimeError("No se encontró FFmpeg. Instálalo con: winget install Gyan.FFmpeg")
    return exe


def ffprobe() -> str:
    exe = find_tool("ffprobe")
    if not exe:
        raise RuntimeError("No se encontró ffprobe (viene con FFmpeg).")
    return exe


def run_quiet(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    # stdin cerrado: FFmpeg nunca se queda esperando al teclado
    return subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW, timeout=timeout)


def cache_key(path: str) -> str:
    try:
        st = os.stat(path)
        mt, size = st.st_mtime_ns, st.st_size
    except OSError:          # el archivo ya no está (se movió o se borró): una clave igual, sin fallar
        mt, size = 0, 0
    raw = f"{os.path.normcase(os.path.abspath(path))}|{mt}|{size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _rate(text: str | None) -> float:
    if not text or text in ("0/0", "0"):
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(text)


def probe(path: str) -> dict:
    r = run_quiet([ffprobe(), "-v", "error", "-print_format", "json",
                   "-show_format", "-show_streams", path], timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "ffprobe falló")
    data = json.loads(r.stdout or b"{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or 0) or float((video or audio or {}).get("duration") or 0)
    return {
        "duration": duration,
        "width": int(video.get("width", 0)) if video else 0,
        "height": int(video.get("height", 0)) if video else 0,
        "fps": round(_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")), 3) if video else 0.0,
        "has_audio": audio is not None,
        "channels": int(audio.get("channels", 0)) if audio else 0,
        "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio"),   # OBS: varias pistas
        "has_video": video is not None,
    }


def thumbnail(path: str, kind: str, duration: float) -> str | None:
    out = cache_dir("miniaturas") / f"{cache_key(path)}.jpg"
    if out.exists():
        return str(out)
    args = [ffmpeg(), "-v", "error", "-y"]
    if kind == KIND_VIDEO:
        args += ["-ss", f"{min(max(duration * 0.1, 0.0), 10.0):.2f}"]
    args += ["-i", path, "-frames:v", "1", "-vf", "scale=320:-2", str(out)]
    r = run_quiet(args, timeout=60)
    return str(out) if r.returncode == 0 and out.exists() else None


def decode_mono(path: str, sample_rate: int = 16000) -> np.ndarray:
    """Decodifica el audio de cualquier archivo a mono float32 (-1..1)."""
    r = run_quiet([ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1",
                   "-ar", str(sample_rate), "-f", "s16le", "-"], timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "no se pudo leer el audio")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def sample_frames(path: str, times: list[float], size: int = 224) -> np.ndarray:
    """Fotogramas en esos momentos, recortados al centro a size×size RGB (para la IA)."""
    from concurrent.futures import ThreadPoolExecutor
    vf = f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}"
    frame_bytes = size * size * 3

    def one(t: float) -> bytes | None:
        r = run_quiet([ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
                       "-frames:v", "1", "-vf", vf, "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], timeout=120)
        return r.stdout if r.returncode == 0 and len(r.stdout) == frame_bytes else None

    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = [f for f in pool.map(one, times) if f]
    if not frames:
        raise RuntimeError("no se pudieron leer fotogramas")
    return np.frombuffer(b"".join(frames), dtype=np.uint8).reshape(len(frames), size, size, 3)


def frame_rgb(path: str, t: float, width: int = 480) -> np.ndarray | None:
    """Un fotograma entero (sin recortar) en el segundo t, de width de ancho, RGB uint8 (H, W, 3)."""
    info = probe(path)
    w0, h0 = int(info.get("width") or 0), int(info.get("height") or 0)
    if not w0 or not h0:
        return None
    w = min(width, w0) // 2 * 2
    h = max(2, int(round(h0 * w / w0 / 2)) * 2)
    r = run_quiet([ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
                   "-vf", f"scale={w}:{h}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], timeout=60)
    if r.returncode != 0 or len(r.stdout) != w * h * 3:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w, 3)


def waveform_peaks(path: str) -> np.ndarray | None:
    """Picos de volumen (PEAK_RATE por segundo) para dibujar la forma de onda en la timeline."""
    # (a 16 kHz: con 8 kHz se perdía casi todo lo de más de 4 kHz, justo donde suenan la «s», la «f» y la «z», y los
    # finales de palabra con esas letras no se veían)
    out = cache_dir("formas_de_onda") / f"{cache_key(path)}_v2.npy"
    if out.exists():
        return np.load(out).astype(np.float32)
    sample_rate = 16000
    samples = decode_mono(path, sample_rate)
    block = sample_rate // PEAK_RATE
    n = len(samples) // block
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    peaks = np.abs(samples[: n * block].reshape(n, block)).max(axis=1)
    np.save(out, peaks.astype(np.float16))
    return peaks.astype(np.float32)
