"""
✂ Recorte de sujeto con IA (SAM 2.1): la máscara del clip, ya calculada por motor_ia/trabajos/recortar.py.

  fx["subject_mask"] = {"mask": video de la máscara (gris, ffv1), "a": segundo del ARCHIVO donde empieza,
                        "fps": fotogramas por segundo de la máscara, "invert": False}
  invert=False → se queda el SUJETO (el fondo se vuelve transparente: como una pantalla verde)
  invert=True  → se queda el FONDO (el sujeto desaparece)
La máscara va en tiempo del archivo: sigue al clip aunque lo recortes, lo cambies de velocidad o lo pongas
hacia atrás. Se guarda en datos/recortes_ia (la usa el proyecto: no es caché).
"""
from __future__ import annotations

import os
import subprocess
import threading

import numpy as np

from . import media as media_tools
from .paths import app_data_dir

PREVIEW_W = 320           # la máscara en el visor (el video exportado usa la entera)
_cache: dict[str, tuple] = {}
_lock = threading.Lock()


def of(fx) -> dict | None:
    sm = (fx or {}).get("subject_mask")
    if isinstance(sm, dict) and sm.get("mask") and os.path.exists(sm["mask"]):
        return sm
    return None


def out_dir() -> str:
    d = app_data_dir() / "recortes_ia"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def ffmpeg_pre(k: int, sm: dict, src_w: int, src_h: int, source_in: float) -> list[str]:
    """[k:v] (el archivo desde source_in) → [sa{k}] con la transparencia de la máscara (en tiempo del archivo)."""
    from ..export.ffmpeg_export import _filter_path
    off = max(0.0, float(source_in) - float(sm["a"]))
    neg = ",negate" if sm.get("invert") else ""
    return [f"movie=filename={_filter_path(sm['mask'])}:seek_point={off:.4f},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h},format=gray{neg}[smk{k}]",
            f"[{k}:v]format=yuva420p[smv{k}]",
            f"[smv{k}][smk{k}]alphamerge[sa{k}]"]


def frames(path: str) -> tuple[np.ndarray, float] | None:
    """La máscara entera, pequeña, en memoria (para el visor): (N, h, w) uint8."""
    with _lock:
        if path in _cache:
            return _cache[path]
    try:
        info = media_tools.probe(path)
        w = PREVIEW_W
        h = max(2, int(round(info["height"] * w / max(1, info["width"]) / 2)) * 2)
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-i", path,
                                   "-vf", f"scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"], timeout=600)
        data = np.frombuffer(r.stdout, np.uint8)
        n = len(data) // (w * h)
        if n <= 0:
            return None
        arr = data[: n * w * h].reshape(n, h, w)
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return None
    with _lock:
        if len(_cache) >= 3:
            _cache.pop(next(iter(_cache)))
        _cache[path] = (arr, float(info.get("fps") or 30.0))
        return _cache[path]


def frame_at(sm: dict, src_t: float) -> np.ndarray | None:
    got = frames(sm["mask"])
    if got is None:
        return None
    arr, _fps = got
    i = int(round((float(src_t) - float(sm["a"])) * float(sm.get("fps") or _fps)))
    m = arr[min(len(arr) - 1, max(0, i))]
    return 255 - m if sm.get("invert") else m
