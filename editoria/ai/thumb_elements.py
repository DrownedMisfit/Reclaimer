"""
🔎 PNG para la miniatura (pestaña «🔎 PNG» del taller: Google Imágenes con «fondo transparente», dentro del editor).
El usuario: «un pequeño buscador: typee la palabra y que en automático busque el PNG».

  fetch(url) -> {"path", "w", "h", "transp", "badge", "cleaned"}   baja la imagen (también las «data:» de las
      miniaturas de Google), la guarda como PNG y la comprueba: si no tiene transparencia pero el fondo es de un color
      liso (blanco, negro), se lo quita solo. badge = «PNG transparente · 1600×1200» / «Fondo quitado · …» /
      «Sin transparencia · …» (y «pequeña» si mide menos de 400 px).
  measure(ruta) -> (ancho, alto, parte transparente 0–1)
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import urllib.request

import numpy as np

from ..core.paths import cache_dir

MIN_SIDE = 400
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}


def measure(path: str) -> tuple[int, int, float] | None:
    """(ancho, alto, parte transparente 0–1) de una imagen; None si no se puede leer."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
            if im.mode not in ("RGBA", "LA", "P") and "transparency" not in im.info:
                return w, h, 0.0
            a = np.asarray(im.convert("RGBA"))[..., 3]
            return w, h, float((a < 20).mean())
    except Exception:  # noqa: BLE001
        return None


def remove_flat_bg(rgba: np.ndarray, tol: int = 28) -> np.ndarray | None:
    """Una «pegatina» con fondo liso (blanco o negro) que toca los bordes → ese fondo transparente (relleno desde
    las esquinas, sin IA). None si el borde no es de un color liso."""
    import cv2
    h, w = rgba.shape[:2]
    rgb = np.ascontiguousarray(rgba[..., :3])
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(int)
    ref = np.median(border, axis=0)
    if np.mean(np.abs(border - ref).max(axis=1) < tol) < 0.85:
        return None
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if np.abs(rgb[y, x].astype(int) - ref).max() < tol and not mask[y + 1, x + 1]:
            cv2.floodFill(rgb.copy(), mask, (x, y), 0, (tol,) * 3, (tol,) * 3, flags)
    bg = mask[1:-1, 1:-1] > 0
    out = rgba.copy()
    out[..., 3] = np.where(bg, 0, out[..., 3])
    out[..., 3] = cv2.GaussianBlur(out[..., 3], (3, 3), 0)       # borde suave
    return out


def _read(url: str) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    if os.path.isfile(url):                         # (la bajó el navegador del taller)
        with open(url, "rb") as f:
            return f.read()
    from urllib.parse import urlsplit
    u = urlsplit(url)
    headers = dict(UA, Referer=f"{u.scheme}://{u.netloc}/",   # (muchas webs solo la dan «desde su página»)
                   Accept="image/avif,image/webp,image/png,image/*,*/*;q=0.8")
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def downloaded() -> list[str]:
    """Los PNG que se bajaron con «🔎 PNG», los últimos primero (se muestran en «Material»)."""
    folder = cache_dir("png_web")
    files = [p for p in folder.glob("*.png") if p.is_file()]
    return [str(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def fetch(url: str) -> dict:
    from PIL import Image
    raw = _read(url)
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    rgba = np.asarray(im).copy()
    tr = float((rgba[..., 3] < 20).mean())
    cleaned = False
    if tr < 0.05:                                   # sin transparencia: si el fondo es liso, se quita
        fixed = remove_flat_bg(rgba)
        if fixed is not None:
            tr2 = float((fixed[..., 3] < 20).mean())
            if 0.1 < tr2 < 0.95:
                rgba, tr, cleaned = fixed, tr2, True
    folder = str(cache_dir("png_web"))
    path = os.path.join(folder, hashlib.md5(np.asarray(im).tobytes()).hexdigest()[:16] + ".png")   # (misma imagen = mismo archivo)
    if os.path.isfile(url) and os.path.basename(os.path.dirname(url)).startswith("nav_"):
        __import__("shutil").rmtree(os.path.dirname(url), ignore_errors=True)   # (el temporal del navegador)
    Image.fromarray(rgba).save(path)
    w, h = im.size
    kind = "Fondo quitado" if cleaned else ("PNG transparente" if tr >= 0.05 else "Sin transparencia")
    badge = f"{kind} · {w}×{h}" + (" · pequeña" if min(w, h) < MIN_SIDE else "")
    return {"path": path, "w": w, "h": h, "transp": round(tr, 2), "badge": badge, "cleaned": cleaned}
