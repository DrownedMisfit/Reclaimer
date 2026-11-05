"""
≈ Licuar (como «Licuar» de Photoshop): deformar con un pincel una capa de la miniatura — inflar los ojos, agrandar
la boca, estirar la cara… (las miniaturas «graciosas» de YouTube). El usuario: «con deformar puedas hacer esto en
las miniaturas… lo haría gracioso».

Se guarda en la capa como un campo de desplazamientos en una cuadrícula N×N (fracciones del contenido):
    lay["liquify"] = {"n": N, "dx": <base64 float16>, "dy": <base64 float16>}
Cada píxel del resultado en (u, v) toma el color de (u + dx, v + dy) del contenido original (en fracciones 0–1).
Los trazos se COMPONEN: un trazo nuevo deforma lo ya deformado.

  stroke(lay, modo, cx, cy, radio, fuerza, aspecto, mover)   un toque del pincel (modo: inflar, encoger,
                                                              empujar, restaurar); radio en fracción del ALTO
  apply(rgba, lay) -> rgba                                    la capa deformada (se llama al dibujarla)
  clear(lay)
"""
from __future__ import annotations

import base64

import cv2
import numpy as np

N = 96
MODES = ("inflar", "encoger", "empujar", "restaurar")


def _enc(a: np.ndarray) -> str:
    return base64.b64encode(a.astype(np.float16).tobytes()).decode("ascii")


def _dec(s: str, n: int) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), np.float16).astype(np.float32).reshape(n, n)


def field(lay: dict) -> tuple[np.ndarray, np.ndarray] | None:
    liq = lay.get("liquify")
    if not liq:
        return None
    try:
        n = int(liq["n"])
        return _dec(liq["dx"], n), _dec(liq["dy"], n)
    except Exception:  # noqa: BLE001 - dato roto: se ignora
        return None


def _store(lay: dict, dx: np.ndarray, dy: np.ndarray):
    if float(np.abs(dx).max(initial=0)) < 1e-4 and float(np.abs(dy).max(initial=0)) < 1e-4:
        lay.pop("liquify", None)
        return
    lay["liquify"] = {"n": int(dx.shape[0]), "dx": _enc(dx), "dy": _enc(dy)}


def clear(lay: dict):
    lay.pop("liquify", None)


def _grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return np.meshgrid(t, t)          # U (x), V (y)


def stroke(lay: dict, mode: str, cx: float, cy: float, radius: float, strength: float,
           aspect: float = 16 / 9, move: tuple[float, float] = (0.0, 0.0), core: float = 0.0):
    """Un toque del pincel en (cx, cy) (fracciones del contenido). radius: fracción del ALTO del contenido.
    aspect: ancho / alto del contenido (para que el pincel sea redondo). move: lo que se arrastró (fracciones).
    core: parte del radio (0–1) que va entera, sin suavizar (✋ Estirar: 0.5, lo agarrado sigue al ratón)."""
    f0 = field(lay)
    dx, dy = f0 if f0 is not None else (np.zeros((N, N), np.float32), np.zeros((N, N), np.float32))
    n = dx.shape[0]
    U, V = _grid(n)
    du, dv = (U - cx) * aspect, (V - cy)
    d2 = (du * du + dv * dv) / max(radius * radius, 1e-8)
    if core > 0:                # núcleo firme: esa parte va entera con el ratón; de ahí al borde, suave
        t = np.clip((np.sqrt(d2) - core) / max(1.0 - core, 1e-6), 0.0, 1.0)
        fall = 1.0 - t * t * (3.0 - 2.0 * t)
    else:
        fall = np.clip(1.0 - d2, 0.0, 1.0) ** 2                   # suave: 1 en el centro, 0 en el borde
    s = float(strength)
    if mode == "restaurar":
        k = 1.0 - np.clip(s * fall, 0.0, 1.0)
        _store(lay, dx * k, dy * k)
        return
    if mode == "inflar":                                          # se toma de más cerca del centro → crece
        ox, oy = -(U - cx) * s * fall, -(V - cy) * s * fall
    elif mode == "encoger":                                       # se toma de más lejos → se achica
        ox, oy = (U - cx) * s * fall, (V - cy) * s * fall
    elif mode == "empujar":                                       # lo de detrás del pincel viene con él
        ox, oy = -move[0] * s * fall, -move[1] * s * fall
    else:
        return
    # componer: el resultado en P toma lo que ya había en P + op(P)
    mx = ((U + ox) * (n - 1)).astype(np.float32)
    my = ((V + oy) * (n - 1)).astype(np.float32)
    odx = cv2.remap(dx, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    ody = cv2.remap(dy, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    _store(lay, (ox + odx).astype(np.float32), (oy + ody).astype(np.float32))


_PIX: dict = {}


def _pixels(w: int, h: int):
    if (w, h) not in _PIX:
        if len(_PIX) > 6:
            _PIX.clear()
        _PIX[(w, h)] = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return _PIX[(w, h)]


def apply(rgba: np.ndarray, lay: dict) -> np.ndarray:
    f = field(lay)
    if f is None:
        return rgba
    dx, dy = f
    h, w = rgba.shape[:2]
    fx = cv2.resize(dx, (w, h), interpolation=cv2.INTER_LINEAR)
    fy = cv2.resize(dy, (w, h), interpolation=cv2.INTER_LINEAR)
    xs, ys = _pixels(w, h)
    mx = cv2.scaleAdd(fx, float(w - 1), xs)
    my = cv2.scaleAdd(fy, float(h - 1), ys)
    return cv2.remap(rgba, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
