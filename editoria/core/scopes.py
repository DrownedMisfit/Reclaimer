"""
Gráficas de video (los «scopes» de Resolve) de un fotograma RGB:
  histogram   → curvas de R, G, B y luminancia (cuántos píxeles hay de cada brillo)
  waveform    → brillo (alto) de cada columna de la imagen (ancho): ver si algo está quemado o aplastado
  parade      → lo mismo, por separado para R, G y B (equilibrio de color)
  vectorscope → tono y saturación: el centro es gris; cuanto más lejos, más saturado; la línea = piel
Cada función devuelve una imagen RGB uint8 lista para dibujar.
"""
from __future__ import annotations

import numpy as np

W_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
MODES = {"waveform": "Forma de onda", "parade": "Desfile RGB", "histogram": "Histograma",
         "vectorscope": "Vectorscopio"}


def _tone(counts: np.ndarray, color) -> np.ndarray:
    """Cuentas → intensidad (escala logarítmica, como un scope de verdad)."""
    v = np.log1p(counts.astype(np.float32))
    v = v / max(float(v.max()), 1e-6)
    return (v[..., None] * np.asarray(color, np.float32)[None, None, :]).clip(0, 255)


def waveform(rgb: np.ndarray, w: int = 320, h: int = 160) -> np.ndarray:
    lum = (rgb.astype(np.float32) @ W_LUMA).astype(np.int32)
    H, Wi = lum.shape
    xs = (np.arange(Wi) * w // Wi)[None, :].repeat(H, 0)
    ys = (255 - lum) * (h - 1) // 255
    counts = np.zeros((h, w), np.int32)
    np.add.at(counts, (ys.ravel(), xs.ravel()), 1)
    return _grid(_tone(counts, (120, 255, 140)).astype(np.uint8), h)


def parade(rgb: np.ndarray, w: int = 320, h: int = 160) -> np.ndarray:
    out = np.zeros((h, w, 3), np.float32)
    third = w // 3
    H, Wi = rgb.shape[:2]
    xs = (np.arange(Wi) * third // Wi)[None, :].repeat(H, 0).ravel()
    for i, col in enumerate(((255, 70, 70), (70, 255, 90), (90, 140, 255))):
        ys = ((255 - rgb[..., i].astype(np.int32)) * (h - 1) // 255).ravel()
        counts = np.zeros((h, third), np.int32)
        np.add.at(counts, (ys, xs), 1)
        out[:, i * third:(i + 1) * third] = _tone(counts, col)
    return _grid(out.astype(np.uint8), h)


def histogram(rgb: np.ndarray, w: int = 320, h: int = 160) -> np.ndarray:
    img = np.zeros((h, w, 3), np.float32)
    chans = [rgb[..., 0], rgb[..., 1], rgb[..., 2], (rgb.astype(np.float32) @ W_LUMA).astype(np.uint8)]
    colors = ((255, 60, 60), (60, 230, 80), (80, 130, 255), (200, 200, 200))
    xs = np.arange(w)
    for ch, col in zip(chans, colors):
        hist = np.bincount(ch.ravel(), minlength=256).astype(np.float32)
        hist = np.sqrt(hist)
        hist = hist / max(float(hist.max()), 1e-6)
        vals = np.interp(xs, np.linspace(0, w - 1, 256), hist)
        tops = (h - 1 - vals * (h - 4)).astype(np.int32)
        mask = np.arange(h)[:, None] >= tops[None, :]
        img[mask] += np.asarray(col, np.float32) * 0.45
    return img.clip(0, 255).astype(np.uint8)


def vectorscope(rgb: np.ndarray, size: int = 200) -> np.ndarray:
    x = rgb.reshape(-1, 3).astype(np.float32) / 255
    y = x @ W_LUMA
    cb = (x[:, 2] - y) / 1.8556
    cr = (x[:, 0] - y) / 1.5748
    r = size // 2 - 6
    px = (size // 2 + cb * 2 * r).astype(np.int32).clip(0, size - 1)
    py = (size // 2 - cr * 2 * r).astype(np.int32).clip(0, size - 1)
    counts = np.zeros((size, size), np.int32)
    np.add.at(counts, (py, px), 1)
    img = _tone(counts, (230, 230, 230))
    # Círculo, centro y línea del tono de piel (≈ 123°)
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.hypot(xx - size / 2, yy - size / 2)
    img[np.abs(d - r) < 0.8] = (70, 70, 80)
    ang = np.deg2rad(123)
    t = np.linspace(0, r, r * 2)
    lx = (size / 2 + np.cos(ang) * t).astype(int)
    ly = (size / 2 - np.sin(ang) * t).astype(int)
    img[ly.clip(0, size - 1), lx.clip(0, size - 1)] = (220, 150, 90)
    return img.astype(np.uint8)


def _grid(img: np.ndarray, h: int) -> np.ndarray:
    """Líneas guía a 0, 25, 50, 75 y 100 % (como en Resolve)."""
    img = img.copy()
    for k in range(5):
        y = int(round((h - 1) * k / 4))
        img[y, :] = np.maximum(img[y, :], (55, 55, 60))
    return img


def render(mode: str, rgb: np.ndarray) -> np.ndarray:
    return {"waveform": waveform, "parade": parade, "histogram": histogram, "vectorscope": vectorscope}[mode](rgb)


def warnings(rgb: np.ndarray) -> list[str]:
    """Avisos en palabras: quemado, aplastado, muy oscuro, muy saturado."""
    lum = rgb.astype(np.float32) @ W_LUMA
    out = []
    burnt = float((rgb.max(axis=-1) >= 254).mean())
    crushed = float((rgb.max(axis=-1) <= 1).mean())
    if burnt > 0.02:
        out.append(f"⚠ {burnt:.0%} de la imagen está quemada (blanco puro): baja la exposición o las luces.")
    if crushed > 0.05:
        out.append(f"⚠ {crushed:.0%} está en negro puro: sube las sombras si se pierde detalle.")
    mid = float(np.median(lum))
    if mid < 40:
        out.append("La imagen está muy oscura (prueba ✨ Color automático o sube la exposición).")
    sat = float(np.mean(rgb.max(axis=-1).astype(np.int32) - rgb.min(axis=-1)))
    if sat > 120:
        out.append("Colores muy saturados: en YouTube pueden verse chillones.")
    return out
