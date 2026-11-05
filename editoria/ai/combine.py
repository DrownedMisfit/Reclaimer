"""
🪄 Combinar (taller de miniaturas): que una imagen puesta encima de otra (unos ojos sobre una cara, un objeto sobre
una escena) parezca parte de ella. El usuario: «que la IA busque combinar estas dos imágenes para que formen
coherencia… que los ojos queden dentro de la piel del personaje».

Todo en el tamaño de la miniatura (píxeles del lienzo):
  · «integrar»: luz y color de lo de abajo → la capa toma la iluminación (sombras y luces de la zona, a gran escala),
    se acerca a su tono, recibe su grano y se le suaviza el borde.
  · «fundir»: además, clonado sin costuras (Poisson, cv2.seamlessClone NORMAL_CLONE): la textura de abajo se mezcla con
    la de encima, como si estuviera impresa en la piel.

  combine(top_rgba, below_rgb, modo, fuerza) -> rgba   (top_rgba y below_rgb del mismo tamaño)
"""
from __future__ import annotations

import cv2
import numpy as np


def _bbox(mask: np.ndarray, margin: int, w: int, h: int):
    ys, xs = np.nonzero(mask > 0.02)
    if len(xs) == 0:
        return None
    return (max(0, xs.min() - margin), max(0, ys.min() - margin), min(w, xs.max() + margin + 1),
            min(h, ys.max() + margin + 1))


def combine(top: np.ndarray, below: np.ndarray, mode: str = "integrar", strength: float = 0.7) -> np.ndarray:
    h, w = top.shape[:2]
    a = top[..., 3].astype(np.float32) / 255.0
    size = max(8, int(np.sqrt(max(1.0, float((a > 0.5).sum())))))          # tamaño típico de la capa
    box = _bbox(a, size // 2 + 12, w, h)
    if box is None:
        return top.copy()
    x0, y0, x1, y1 = box
    t = top[y0:y1, x0:x1].astype(np.float32)
    b = below[y0:y1, x0:x1, :3].astype(np.float32)
    al = a[y0:y1, x0:x1]
    s = float(np.clip(strength, 0.0, 1.0))
    inside = al > 0.5
    if inside.sum() < 16:
        return top.copy()
    lab_t = cv2.cvtColor(np.clip(t[..., :3], 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab_b = cv2.cvtColor(b.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    # 1) luz: la iluminación de abajo a gran escala (sombras de la cara), relativa a su media bajo la capa
    sigma = max(4.0, size / 5.0)
    light = cv2.GaussianBlur(lab_b[..., 0], (0, 0), sigma)
    ratio = light / max(1.0, float(light[inside].mean()))
    lab_t[..., 0] *= ratio ** (0.9 * s)
    # 2) color: se acerca al tono de lo de abajo (sin perder el contraste propio)
    for c in (1, 2):
        shift = float(lab_b[..., c][inside].mean() - lab_t[..., c][inside].mean())
        lab_t[..., c] += shift * 0.35 * s
    # 3) brillo general: que no destaque más que su entorno
    dl = float(lab_b[..., 0][inside].mean() - lab_t[..., 0][inside].mean())
    lab_t[..., 0] += dl * 0.25 * s
    rgb = cv2.cvtColor(np.clip(lab_t, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
    # 4) grano: el ruido fino de la foto de abajo
    gray = cv2.cvtColor(b.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    grain = gray - cv2.GaussianBlur(gray, (0, 0), 1.5)
    rgb += (grain * 0.8 * s)[..., None]
    out_a = cv2.GaussianBlur(al, (0, 0), 0.6 + 1.2 * s)                      # 5) borde suave (sin recorte duro)
    out_a = np.minimum(out_a, al + 0.15)
    if mode == "fundir":
        m = (al > 0.5).astype(np.uint8) * 255
        m[:2, :], m[-2:, :], m[:, :2], m[:, -2:] = 0, 0, 0, 0                 # (no puede tocar el borde)
        if m.any():
            ys, xs = np.nonzero(m)
            cx, cy = int((xs.min() + xs.max()) / 2), int((ys.min() + ys.max()) / 2)
            src = np.clip(rgb, 0, 255).astype(np.uint8)
            mix = cv2.seamlessClone(src, b.astype(np.uint8), m, (cx, cy), cv2.NORMAL_CLONE).astype(np.float32)
            k = 0.2 + 0.5 * s                                                  # cuánto se funde (con la fuerza)
            rgb = rgb * (1 - k) + mix * k
            out_a = np.maximum(out_a, 0.0)
    res = top.copy()
    res[y0:y1, x0:x1, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    res[y0:y1, x0:x1, 3] = np.clip(out_a * 255, 0, 255).astype(np.uint8)
    return res
