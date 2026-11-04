"""
👤 Quitar fondo por movimiento (sin pantalla verde): con la CÁMARA FIJA (facecam, plano quieto), se aprende cómo
es el fondo vacío (la mediana de ~25 fotogramas: lo que se mueve no está siempre en el mismo sitio) y se vuelve
transparente todo lo que es igual al fondo. Si la cámara se mueve, no sirve: se avisa y no se aplica.

  fx["motion_key"] = {"plate": ruta del fondo vacío (png), "thr": 0.10, "soft": 0.06}
El fondo vacío se guarda en datos/fondos_quietos (lo usa el proyecto: no es caché).
"""
from __future__ import annotations

import os

import numpy as np

from . import media as media_tools
from .paths import app_data_dir

DEFAULT = {"thr": 0.10, "soft": 0.06}


def of(fx) -> dict | None:
    mk = (fx or {}).get("motion_key")
    if isinstance(mk, dict) and mk.get("plate") and os.path.exists(mk["plate"]):
        return dict(DEFAULT, **mk)
    return None


def out_dir() -> str:
    d = app_data_dir() / "fondos_quietos"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def learn_plate(path: str, a: float, b: float, progress=None, cancelled=None, n: int = 25) -> tuple[str | None, float]:
    """Aprende el fondo vacío del tramo [a, b] del archivo. Devuelve (png del fondo o None, cuánto se mueve la
    cámara 0–1). Con la cámara moviéndose (> 0,55) no se guarda nada."""
    import cv2
    frames = []
    for i in range(n):
        if cancelled is not None and cancelled():
            return None, 0.0
        t = a + (b - a) * (i + 0.5) / n
        img = media_tools.frame_rgb(path, t, 640)
        if img is not None:
            frames.append(img)
        if progress:
            progress((i + 1) / n)
    if len(frames) < 5:
        return None, 0.0
    h, w = frames[0].shape[:2]
    stack = np.stack([f if f.shape[:2] == (h, w) else cv2.resize(f, (w, h)) for f in frames]).astype(np.float32)
    plate = np.median(stack, axis=0)
    # ¿Cámara quieta? En un plano fijo, la mayor parte de la imagen casi no cambia entre fotogramas
    changing = (np.abs(stack - plate[None]).mean(axis=3) > 25).mean(axis=0)     # en cuántos fotogramas cambia
    moving = float((changing > 0.5).mean())                                     # parte de la imagen que «se mueve»
    if moving > 0.55:
        return None, moving
    out = os.path.join(out_dir(), f"{media_tools.cache_key(path)}_{a:.2f}_{b:.2f}.png")
    cv2.imwrite(out, cv2.cvtColor(plate.astype(np.uint8), cv2.COLOR_RGB2BGR))
    return out, moving


def ffmpeg_filter(k: int, mk: dict, src: str, w: int, h: int) -> list[str]:
    """[src] (w×h) → [mk{k}] con transparencia donde la imagen es igual al fondo vacío."""
    from ..export.ffmpeg_export import _filter_path
    thr, soft = float(mk["thr"]), max(0.01, float(mk["soft"]))
    lo = int(255 * thr)
    gain = 255.0 / (255 * soft)
    return [f"[{src}]format=rgb24,split=2[mka{k}][mkb{k}]",
            f"movie=filename={_filter_path(mk['plate'])}:loop=0,setpts=N/FRAME_RATE/TB,scale={w}:{h},format=rgb24[mkp{k}]",
            f"[mkb{k}][mkp{k}]blend=all_mode=difference:shortest=1,format=gray,"
            f"geq=lum='clip((lum(X,Y)*3-{lo})*{gain:.3f},0,255)',boxblur=3:1[mkm{k}]",
            f"[mka{k}]format=rgba[mkc{k}]",
            f"[mkc{k}][mkm{k}]alphamerge,format=yuva420p[mk{k}]"]


def apply_argb32(px: np.ndarray, mk: dict, plate: np.ndarray) -> np.ndarray:
    """En el visor: lo mismo con numpy (plate ya del tamaño de px, RGB)."""
    import cv2
    h, w = px.shape
    bgra = px.view(np.uint8).reshape(h, w, 4)
    rgb = bgra[..., 2::-1].astype(np.float32)
    diff = np.abs(rgb - plate.astype(np.float32)).mean(axis=2) * 3 / 255.0
    alpha = np.clip((diff - float(mk["thr"])) / max(0.01, float(mk["soft"])), 0, 1)
    alpha = cv2.blur(alpha, (5, 5))
    bgra[..., 3] = (bgra[..., 3].astype(np.float32) * alpha).astype(np.uint8)
    return px
