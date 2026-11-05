"""
⇱ Mejorar resolución (upscale ×2 / ×4) de una imagen de la miniatura, con IA y sin tarjeta gráfica.
El usuario: «podríamos también meter una opción para hacer un upscale a las imágenes».

Modelos de OpenCV dnn_superres (opencv-contrib, ya instalado), licencia Apache 2.0 (Saafke/EDSR_Tensorflow y
Saafke/FSRCNN_Tensorflow); se bajan la primera vez a models_dir()/upscale:
  · EDSR (≈38 MB): el de mejor calidad; para imágenes pequeñas (las que más lo necesitan: PNG de internet, logos).
  · FSRCNN (≈40 KB): muy rápido; para imágenes grandes (EDSR tardaría minutos).
La transparencia se agranda aparte (bicúbica): el modelo solo ve el color. Se procesa por trozos (memoria y avance).

  upscale(rgba, factor, progress, cancelled) -> rgba agrandada
"""
from __future__ import annotations

import os
import urllib.request

import cv2
import numpy as np

from .transcription import models_dir

BASE = "https://raw.githubusercontent.com/Saafke/{repo}/master/models/{name}"
REPO = {"edsr": "EDSR_Tensorflow", "fsrcnn": "FSRCNN_Tensorflow"}
EDSR_MAX_PX = 250_000          # más píxeles de entrada que esto: FSRCNN (EDSR en CPU es lento)
TILE = 192                     # trozos (con solape) para no gastar demasiada memoria y poder informar del avance
OVERLAP = 12


def _name(kind: str, factor: int) -> str:
    return f"{kind.upper()}_x{factor}.pb"


def model_path(kind: str, factor: int) -> str:
    return str(models_dir() / "upscale" / _name(kind, factor))


def kind_for(w: int, h: int) -> str:
    return "edsr" if w * h <= EDSR_MAX_PX else "fsrcnn"


def download(kind: str, factor: int, progress=None) -> str:
    path = model_path(kind, factor)
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = BASE.format(repo=REPO[kind], name=_name(kind, factor))
    tmp = path + ".part"
    if progress:
        progress(0.0, f"Bajando el modelo de mejorar resolución ({'38 MB' if kind == 'edsr' else '40 KB'}, una vez)…")
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)
    return path


def upscale(rgba: np.ndarray, factor: int = 2, progress=None, cancelled=None) -> np.ndarray:
    """rgba (alto, ancho, 4) uint8 → la misma imagen factor veces más grande."""
    if factor not in (2, 4):
        raise ValueError("factor 2 o 4")
    h, w = rgba.shape[:2]
    kind = kind_for(w, h)
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(download(kind, factor, progress))
    sr.setModel(kind, factor)
    bgr = cv2.cvtColor(np.ascontiguousarray(rgba[..., :3]), cv2.COLOR_RGB2BGR)
    out = np.zeros((h * factor, w * factor, 3), np.uint8)
    ys = list(range(0, h, TILE))
    xs = list(range(0, w, TILE))
    total, done = len(ys) * len(xs), 0
    for y in ys:
        for x in xs:
            if cancelled and cancelled():
                raise RuntimeError("Cancelado.")
            y0, x0 = max(0, y - OVERLAP), max(0, x - OVERLAP)
            y1, x1 = min(h, y + TILE + OVERLAP), min(w, x + TILE + OVERLAP)
            big = sr.upsample(bgr[y0:y1, x0:x1])
            oy, ox = (y - y0) * factor, (x - x0) * factor        # se pega sin el solape (sin costuras)
            th, tw = (min(h, y + TILE) - y) * factor, (min(w, x + TILE) - x) * factor
            out[y * factor:y * factor + th, x * factor:x * factor + tw] = big[oy:oy + th, ox:ox + tw]
            done += 1
            if progress:
                progress(done / total, f"⇱ Mejorando la resolución ×{factor}… {int(100 * done / total)} %")
    rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    alpha = cv2.resize(rgba[..., 3], (w * factor, h * factor), interpolation=cv2.INTER_CUBIC)
    return np.dstack([rgb, alpha])
