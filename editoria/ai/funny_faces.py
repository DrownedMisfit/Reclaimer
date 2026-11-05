"""
😜 Caras graciosas de un clic (taller de miniaturas → «≈ Licuar»): ojos saltones, bocota, cabezón… como las
miniaturas «graciosas» de YouTube. Busca la cara más grande de la capa con YuNet (5 puntos: ojos, nariz y
comisuras de la boca) y aplica trazos de ≈ Licuar (core/liquify.py) en el sitio justo.

  faces(rgba) -> [{"box": (x, y, w, h), "re", "le", "nose", "mr", "ml"}]   en píxeles del contenido
  apply(lay, preset, rgba) -> bool                                           False si no hay cara
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import liquify as L

PRESETS = [("ojos", "👀 Ojos saltones", "Infla los dos ojos"),
           ("boca", "👄 Bocota", "Agranda la boca y la abre hacia abajo"),
           ("cabeza", "🗿 Cabezón", "Infla toda la cara"),
           ("sonrisa", "😁 Sonrisota", "Estira las comisuras hacia fuera y arriba"),
           ("estirada", "🥴 Cara estirada", "Estira la cara: la frente arriba y la barbilla abajo"),
           ("carita", "🤏 Carita", "Encoge la cara")]


def faces(rgba: np.ndarray) -> list[dict]:
    from .tracking import _face_detector
    bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR) if rgba.shape[2] == 4 else rgba
    h, w = bgr.shape[:2]
    k = min(1.0, 640 / max(w, h))
    small = cv2.resize(bgr, (max(1, int(w * k)), max(1, int(h * k)))) if k < 1 else bgr
    det = _face_detector(small.shape[1], small.shape[0])
    _ok, found = det.detect(small)
    out = []
    for f in (found if found is not None else []):
        p = [float(v) / k for v in f[:14]]
        out.append({"box": tuple(p[0:4]), "re": (p[4], p[5]), "le": (p[6], p[7]), "nose": (p[8], p[9]),
                    "mr": (p[10], p[11]), "ml": (p[12], p[13])})
    out.sort(key=lambda d: -(d["box"][2] * d["box"][3]))
    return out


def strokes(face: dict, preset: str, w: int, h: int) -> list[tuple]:
    """Los trazos de ≈ Licuar de cada cara graciosa: (modo, cx, cy, radio, fuerza, mover) en fracciones."""
    bx, by, bw, bh = face["box"]
    cx, cy = bx + bw / 2, by + bh / 2
    (rx, ry), (lx, ly) = face["re"], face["le"]
    (mrx, mry), (mlx, mly) = face["mr"], face["ml"]
    eye = max(1.0, math.hypot(lx - rx, ly - ry))
    mx, my = (mrx + mlx) / 2, (mry + mly) / 2
    mw = max(1.0, math.hypot(mlx - mrx, mly - mry))
    fx, fy = (lambda x: x / w), (lambda y: y / h)
    rr = lambda px: px / h                                   # radio: fracción del alto
    if preset == "ojos":
        return [("inflar", fx(rx), fy(ry), rr(0.7 * eye), 0.75, (0, 0)),
                ("inflar", fx(lx), fy(ly), rr(0.7 * eye), 0.75, (0, 0))]
    if preset == "boca":
        return [("inflar", fx(mx), fy(my), rr(0.95 * mw), 0.55, (0, 0)),
                ("empujar", fx(mx), fy(my + 0.25 * mw), rr(0.8 * mw), 1.0, (0, rr(0.3 * mw)))]
    if preset == "cabeza":
        return [("inflar", fx(cx), fy(cy), rr(0.8 * bh), 0.4, (0, 0))]
    if preset == "sonrisa":            # las comisuras arriba y afuera (pinceles pequeños: el centro no se mueve)
        out = [("empujar", fx(mx), fy(my), rr(0.3 * mw), 1.0, (0, fy(0.08 * mw)))]
        for (px, py) in ((mrx, mry), (mlx, mly)):
            dx, dy = px - mx, py - my
            n = math.hypot(dx, dy) or 1.0
            mvx, mvy = dx / n * 0.3 * mw, dy / n * 0.3 * mw - 0.35 * mw
            out.append(("empujar", fx(px + dx / n * 0.08 * mw), fy(py), rr(0.38 * mw), 1.0, (fx(mvx), fy(mvy))))
        return out
    if preset == "estirada":
        return [("empujar", fx(cx), fy(by + 0.12 * bh), rr(0.5 * bh), 1.0, (0, -fy(0.14 * bh))),
                ("empujar", fx(cx), fy(by + 0.92 * bh), rr(0.5 * bh), 1.0, (0, fy(0.18 * bh)))]
    if preset == "carita":
        return [("encoger", fx(cx), fy(cy), rr(0.8 * bh), 0.45, (0, 0))]
    return []


def apply(lay: dict, preset: str, rgba: np.ndarray, face: dict | None = None) -> bool:
    """Aplica la cara graciosa a la cara más grande de la capa (rgba = su contenido, sin licuar)."""
    h, w = rgba.shape[:2]
    if face is None:
        found = faces(rgba)
        if not found:
            return False
        face = found[0]
    for mode, x, y, r, s, mv in strokes(face, preset, w, h):
        L.stroke(lay, mode, x, y, r, s, w / h, mv)
    return True
