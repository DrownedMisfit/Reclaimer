"""
¿Gameplay o cinemática? ¿Primera o tercera persona? Con pistas SENCILLAS (rápido, sin modelos pesados):

  · Barras negras arriba y abajo                          → cinemática
  · Cosas FIJAS con bordes marcados en las esquinas/bordes  → gameplay (vida, mapa, munición, botones)
    mientras el resto de la imagen cambia
  · Algo fijo abajo en el centro (arma, manos)              → primera persona
  · El centro cambia menos que lo de alrededor (personaje)  → tercera persona

cues(path, times) lee 12 fotogramas pequeños del cuadro completo (192×108) y devuelve
{"type": "Gameplay" | "Cinemáticas" | None, "view": "primera persona" | "tercera persona" | None, ...}.
"""
from __future__ import annotations

import numpy as np

from ..core import media as media_tools

W, H = 192, 108


def read_small(path: str, times) -> np.ndarray | None:
    from concurrent.futures import ThreadPoolExecutor
    nbytes = W * H * 3

    def one(t):
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
                                   "-i", path, "-frames:v", "1", "-vf", f"scale={W}:{H}", "-pix_fmt", "rgb24",
                                   "-f", "rawvideo", "-"], timeout=60)
        return r.stdout if r.returncode == 0 and len(r.stdout) == nbytes else None
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = [f for f in pool.map(one, list(times)) if f]
    if len(frames) < 3:
        return None
    return np.frombuffer(b"".join(frames), np.uint8).reshape(len(frames), H, W, 3)


def analyze(frames: np.ndarray) -> dict:
    import cv2
    g = frames.astype(np.float32).mean(axis=3)                    # (N, H, W) gris
    std = g.std(axis=0)                                           # cuánto cambia cada píxel entre momentos
    edges = np.mean([np.abs(cv2.Sobel(f, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(f, cv2.CV_32F, 0, 1))
                     for f in g], axis=0)
    motion = float(np.median(std))
    static_edge = (std < 10) & (edges > 60)                       # fijo y con bordes marcados (HUD, letras, arma)
    band_y, band_x = int(H * 0.16), int(W * 0.16)
    border = np.zeros((H, W), bool)
    border[:band_y] = border[-band_y:] = True
    border[:, :band_x] = border[:, -band_x:] = True
    # bandas negras de cine (arriba y abajo) no cuentan como HUD
    top = frames[:, :int(H * 0.1)].reshape(len(frames), -1).max(axis=1)
    bot = frames[:, -int(H * 0.1):].reshape(len(frames), -1).max(axis=1)
    letterbox = float(np.mean((top < 28) & (bot < 28)))
    if letterbox >= 0.5:
        border[:int(H * 0.14)] = border[-int(H * 0.14):] = False
    hud = float(static_edge[border].mean()) if motion > 6 else 0.0
    bc = np.zeros((H, W), bool)
    bc[int(H * 0.62):, int(W * 0.32):int(W * 0.68)] = True
    first = float(static_edge[bc].mean()) if motion > 6 else 0.0
    cen = np.zeros((H, W), bool)
    cen[int(H * 0.3):int(H * 0.8), int(W * 0.36):int(W * 0.64)] = True
    ring = ~cen & ~border
    center_ratio = float(np.median(std[cen]) / max(1e-3, np.median(std[ring]))) if motion > 6 else 1.0
    typ = None
    if letterbox >= 0.5 and hud < 0.03:
        typ = "Cinemáticas"
    elif hud >= 0.015:
        typ = "Gameplay"
    view = None
    if typ == "Gameplay" or (typ is None and motion > 6):
        if first >= 0.12:
            view = "primera persona"
        elif center_ratio < 0.6:
            view = "tercera persona"
    return {"type": typ, "view": view, "hud": round(hud, 3), "letterbox": round(letterbox, 2),
            "first": round(first, 3), "center_ratio": round(center_ratio, 2), "motion": round(motion, 1)}


def cues(path: str, times) -> dict:
    fr = read_small(path, times)
    if fr is None:
        return {"type": None, "view": None}
    return analyze(fr)
