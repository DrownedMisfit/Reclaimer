"""
Módulo de IA: QUITAR EL FONDO (recortar al sujeto) — local y gratis.

Usa el modelo IS-Net «general use» (el de la herramienta libre rembg; licencia Apache-2.0).
Devuelve una MÁSCARA en grises del tamaño de la imagen (blanco = se ve, negro = transparente),
que luego se puede retocar a mano con el pincel (borrar / recuperar).

  remove(path)              → automático: el sujeto principal
  remove(path, box=(…))     → semiautomático: lo que hay dentro del recuadro que marcaste
"""
from __future__ import annotations

import os
import threading
import uuid

import cv2
import numpy as np

from ..core.paths import cache_dir
from .transcription import models_dir

SIZE = 1024
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
_lock = threading.Lock()
_session = None


def model_path() -> str:
    return str(models_dir() / "recorte" / "isnet-general-use.onnx")


def is_available() -> bool:
    return os.path.exists(model_path())


def download(progress=None) -> str:
    """Descarga el modelo (~180 MB) la primera vez."""
    import urllib.request
    out = model_path()
    if os.path.exists(out):
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if progress:
        progress(0.0, "Descargando el modelo para quitar fondos (~180 MB, solo la primera vez)…")
    tmp = out + ".part"
    urllib.request.urlretrieve(MODEL_URL, tmp)
    os.replace(tmp, out)
    return out


def _sess():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            _session = ort.InferenceSession(download(), providers=["CPUExecutionProvider"])
        return _session


def _predict(rgb: np.ndarray) -> np.ndarray:
    """Máscara 0–1 del sujeto para una imagen RGB uint8 (del mismo tamaño)."""
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    x = (x - 0.5) / 1.0
    x = x.transpose(2, 0, 1)[None]
    s = _sess()
    out = s.run(None, {s.get_inputs()[0].name: x})[0][0, 0]
    out = (out - out.min()) / max(1e-6, out.max() - out.min())
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)


def remove(path: str, box: tuple[float, float, float, float] | None = None, margin: float = 0.06) -> str:
    """Crea la máscara del sujeto y devuelve su ruta (PNG en grises, mismo tamaño que la imagen).
    box = (x0, y0, x1, y1) en 0–1: solo se busca el sujeto dentro de ese recuadro."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("No se pudo leer la imagen.")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.float32)
    if box:
        x0, y0, x1, y1 = box
        mx, my = (x1 - x0) * margin, (y1 - y0) * margin
        a = int(max(0, (x0 - mx) * w)), int(max(0, (y0 - my) * h))
        b = int(min(w, (x1 + mx) * w)), int(min(h, (y1 + my) * h))
        if b[0] - a[0] < 8 or b[1] - a[1] < 8:
            raise RuntimeError("El recuadro es demasiado pequeño.")
        mask[a[1]:b[1], a[0]:b[0]] = _predict(rgb[a[1]:b[1], a[0]:b[0]])
        # Fuera del recuadro marcado no hay nada
        inner = np.zeros_like(mask)
        inner[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 1
        inner = cv2.GaussianBlur(inner, (0, 0), max(2, int(min(w, h) * 0.01)))
        mask *= np.clip(inner * 1.5, 0, 1)
    else:
        mask = _predict(rgb)
    # Bordes limpios: quitar «neblina» suave y conservar el detalle (pelo, bordes)
    mask = np.clip((mask - 0.08) / 0.84, 0, 1)
    out = os.path.join(str(cache_dir("recortes")), f"mask_{uuid.uuid4().hex[:12]}.png")
    cv2.imwrite(out, (mask * 255).astype(np.uint8))
    return out


def paint(mask_path: str | None, image_path: str, strokes: list[tuple[float, float]], radius: float,
          restore: bool, size: tuple[int, int] | None = None) -> str:
    """Pincel: borra (o recupera) a lo largo de los puntos (píxeles de la imagen original).
    Devuelve una máscara NUEVA (así deshacer funciona)."""
    if mask_path and os.path.exists(mask_path):
        m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    else:
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        h, w = img.shape[:2] if img is not None else (size[1], size[0])
        m = np.full((h, w), 255, np.uint8)
    val = 255 if restore else 0
    r = max(1, int(radius))
    pts = [(int(x), int(y)) for x, y in strokes]
    for i, p in enumerate(pts):
        cv2.circle(m, p, r, val, -1, lineType=cv2.LINE_AA)
        if i:
            cv2.line(m, pts[i - 1], p, val, 2 * r, lineType=cv2.LINE_AA)
    out = os.path.join(str(cache_dir("recortes")), f"mask_{uuid.uuid4().hex[:12]}.png")
    cv2.imwrite(out, m)
    return out


def subject_box(mask_path: str) -> tuple[float, float, float, float] | None:
    """Caja (0–1) de lo que quedó visible: para reencuadrar al sujeto recortado."""
    m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if m is None:
        return None
    ys, xs = np.nonzero(m > 128)
    if not len(xs):
        return None
    h, w = m.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h
