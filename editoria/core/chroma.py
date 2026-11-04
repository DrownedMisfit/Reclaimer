"""
🟩 Pantalla verde (chroma key): quitar un fondo de color de un clip, lo más fácil posible.

  · Un clic: el color del fondo se DETECTA solo (mira los bordes de la imagen y elige el color saturado que
    más se repite: verde, azul, el que sea).
  · Dos controles: Tolerancia (cuánto color se quita) y Suavidad (borde suave).
  · Quita también el reflejo de color sobre la persona/objeto («despill»).
La misma fórmula que el filtro «chromakey» de FFmpeg: lo que ves en el visor es lo que se exporta.
fx["chroma"] = {"color": "#00b140", "similarity": 0.11, "blend": 0.07, "spill": True}
"""
from __future__ import annotations

import numpy as np

DEFAULT = {"color": "#00b140", "similarity": 0.11, "blend": 0.07, "spill": True}


def of(fx: dict | None) -> dict | None:
    ch = (fx or {}).get("chroma")
    return dict(DEFAULT, **ch) if isinstance(ch, dict) else None


def _rgb(hexcol: str) -> tuple[int, int, int]:
    h = hexcol.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _cbcr(r, g, b):
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return cb, cr


def detect(img: np.ndarray) -> str:
    """El color del fondo (imagen RGB uint8): el color saturado más repetido en los bordes."""
    h, w = img.shape[:2]
    bw, bh = max(2, w // 12), max(2, h // 12)
    border = np.concatenate([img[:bh].reshape(-1, 3), img[-bh:].reshape(-1, 3),
                             img[:, :bw].reshape(-1, 3), img[:, -bw:].reshape(-1, 3)]).astype(np.float32)
    mx, mn = border.max(1), border.min(1)
    sat = (mx - mn) / np.maximum(mx, 1)
    keep = border[(sat > 0.35) & (mx > 60)]
    if len(keep) < len(border) * 0.15:
        return DEFAULT["color"]
    import cv2
    hsv = cv2.cvtColor(keep.astype(np.uint8).reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    hist = np.bincount(hsv[:, 0] // 6, minlength=31)
    top = int(np.argmax(hist))
    sel = keep[(hsv[:, 0] // 6) == top]
    r, g, b = np.median(sel, axis=0).astype(int)
    return f"#{r:02x}{g:02x}{b:02x}"


def has_screen(img: np.ndarray, color: str) -> bool:
    """¿De verdad hay un fondo de ese color (pantalla verde/azul) en los bordes? En un video normal (gameplay,
    cinemáticas) no lo hay, y el croma no quitaría nada."""
    h, w = img.shape[:2]
    bw, bh = max(2, w // 12), max(2, h // 12)
    border = np.concatenate([img[:bh].reshape(-1, 3), img[-bh:].reshape(-1, 3),
                             img[:, :bw].reshape(-1, 3), img[:, -bw:].reshape(-1, 3)]).astype(np.float32)
    r, g, b = _rgb(color)
    near = np.abs(border - np.array([r, g, b], np.float32)).mean(axis=1) < 45
    return float(near.mean()) >= 0.35


def ffmpeg_filter(ch: dict | None) -> str:
    """Filtros de FFmpeg (terminan con transparencia: yuva420p)."""
    if not ch:
        return ""
    r, g, b = _rgb(ch["color"])
    f = (f"chromakey=color=0x{r:02X}{g:02X}{b:02X}:similarity={float(ch['similarity']):.3f}:"
         f"blend={float(ch['blend']):.3f}")
    if ch.get("spill", True):
        f += ",format=rgba,despill=type=" + ("blue" if b > g else "green")
    return f + ",format=yuva420p"


def apply_argb32(px: np.ndarray, ch: dict) -> np.ndarray:
    """En el visor: transparencia por color (misma fórmula que chromakey) y quitar el reflejo. px = ARGB32."""
    h, w = px.shape
    bgra = px.view(np.uint8).reshape(h, w, 4)
    b = bgra[..., 0].astype(np.float32)
    g = bgra[..., 1].astype(np.float32)
    r = bgra[..., 2].astype(np.float32)
    kr, kg, kb = _rgb(ch["color"])
    kcb, kcr = _cbcr(kr, kg, kb)
    cb, cr = _cbcr(r, g, b)
    diff = np.sqrt(((cb - kcb) ** 2 + (cr - kcr) ** 2) / (255.0 * 255.0 * 2))
    sim, blend = float(ch["similarity"]), float(ch["blend"])
    if blend > 1e-4:
        alpha = np.clip((diff - sim) / blend, 0.0, 1.0)
    else:
        alpha = (diff > sim).astype(np.float32)
    if ch.get("spill", True):
        if kb > kg:
            bgra[..., 0] = np.minimum(b, (r + g) / 2).astype(np.uint8)
        else:
            bgra[..., 1] = np.minimum(g, (r + b) / 2).astype(np.uint8)
    bgra[..., 3] = (bgra[..., 3].astype(np.float32) * alpha).astype(np.uint8)
    return px
