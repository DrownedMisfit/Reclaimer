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
  stroke_many(lay, [args_de_stroke, ...])                     varios toques seguidos; decodifica y guarda una vez
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


def _dab(dx: np.ndarray, dy: np.ndarray, mode: str, cx: float, cy: float, radius: float, strength: float,
         aspect: float = 16 / 9, move: tuple[float, float] = (0.0, 0.0), core: float = 0.0):
    """Un toque sobre el campo ya decodificado. Devuelve el campo nuevo (dx, dy), o None si el modo no existe."""
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
        return dx * k, dy * k
    if mode == "inflar":                                          # se toma de más cerca del centro → crece
        ox, oy = -(U - cx) * s * fall, -(V - cy) * s * fall
    elif mode == "encoger":                                       # se toma de más lejos → se achica
        ox, oy = (U - cx) * s * fall, (V - cy) * s * fall
    elif mode == "empujar":                                       # lo de detrás del pincel viene con él
        ox, oy = -move[0] * s * fall, -move[1] * s * fall
    else:
        return None
    # componer: el resultado en P toma lo que ya había en P + op(P)
    mx = ((U + ox) * (n - 1)).astype(np.float32)
    my = ((V + oy) * (n - 1)).astype(np.float32)
    odx = cv2.remap(dx, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    ody = cv2.remap(dy, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return (ox + odx).astype(np.float32), (oy + ody).astype(np.float32)


def _current(lay: dict) -> tuple[np.ndarray, np.ndarray]:
    f0 = field(lay)
    return f0 if f0 is not None else (np.zeros((N, N), np.float32), np.zeros((N, N), np.float32))


def stroke(lay: dict, mode: str, cx: float, cy: float, radius: float, strength: float,
           aspect: float = 16 / 9, move: tuple[float, float] = (0.0, 0.0), core: float = 0.0):
    """Un toque del pincel en (cx, cy) (fracciones del contenido). radius: fracción del ALTO del contenido.
    aspect: ancho / alto del contenido (para que el pincel sea redondo). move: lo que se arrastró (fracciones).
    core: parte del radio (0–1) que va entera, sin suavizar (✋ Estirar: 0.5, lo agarrado sigue al ratón)."""
    dx, dy = _current(lay)
    got = _dab(dx, dy, mode, cx, cy, radius, strength, aspect, move, core)
    if got is not None:
        _store(lay, *got)


def stroke_many(lay: dict, dabs: list[tuple]):
    """Varios toques seguidos (✋ Estirar en un arrastre rápido): decodifica y guarda el campo UNA vez.
    dabs: lista de tuplas con los mismos argumentos que stroke (sin lay), en orden."""
    dx, dy = _current(lay)
    hecho = False
    for d in dabs:
        got = _dab(dx, dy, *d)
        if got is not None:
            dx, dy = got
            hecho = True
    if hecho:
        _store(lay, dx, dy)


_PIX: dict = {}


def _pixels(w: int, h: int):
    if (w, h) not in _PIX:
        if len(_PIX) > 6:
            _PIX.clear()
        _PIX[(w, h)] = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return _PIX[(w, h)]


def apply_padded(rgba: np.ndarray, lay: dict, pad: int, cw: int, ch: int) -> np.ndarray:
    """Licuar una imagen YA con sus efectos (contorno, brillo, sombra) y un margen de pad píxeles alrededor del
    contenido de cw×ch: el contorno y el brillo se deforman con el sujeto. Para la vista rápida mientras se arrastra
    (recalcular los efectos en cada toque tardaba 1–3 s con una imagen grande)."""
    f = field(lay)
    if f is None:
        return rgba
    dx, dy = f
    h, w = rgba.shape[:2]
    fx = cv2.resize(dx, (max(1, cw), max(1, ch)), interpolation=cv2.INTER_LINEAR)
    fy = cv2.resize(dy, (max(1, cw), max(1, ch)), interpolation=cv2.INTER_LINEAR)
    bottom, right = max(0, h - ch - pad), max(0, w - cw - pad)
    fx = cv2.copyMakeBorder(fx, pad, bottom, pad, right, cv2.BORDER_REPLICATE)[:h, :w]
    fy = cv2.copyMakeBorder(fy, pad, bottom, pad, right, cv2.BORDER_REPLICATE)[:h, :w]
    xs, ys = _pixels(w, h)
    mx = cv2.scaleAdd(fx, float(max(1, cw - 1)), xs)
    my = cv2.scaleAdd(fy, float(max(1, ch - 1)), ys)
    return cv2.remap(rgba, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def apply_padded_update(out: np.ndarray, rgba: np.ndarray, lay: dict, pad: int, cw: int, ch: int,
                        old: tuple[np.ndarray, np.ndarray]) -> bool:
    """Pone al día, EN SITIO, el resultado de apply_padded (out) tras un toque: solo rehace el rectángulo donde ha
    cambiado el campo respecto a old (su decodificación anterior). Mismo resultado que apply_padded (muestreo igual
    que cv2.resize). Devuelve False si no se puede (sin campo o con otro tamaño): entonces hay que rehacerlo entero."""
    f = field(lay)
    if f is None or old is None or out.shape[:2] != rgba.shape[:2]:
        return False
    dx, dy = f
    odx, ody = old
    if dx.shape != odx.shape:
        return False
    m = (dx != odx) | (dy != ody)
    if not m.any():
        return True
    n = dx.shape[0]
    cols = np.nonzero(m.any(axis=0))[0]
    rows = np.nonzero(m.any(axis=1))[0]
    h, w = out.shape[:2]
    X = np.arange(w, dtype=np.float32)
    Y = np.arange(h, dtype=np.float32)
    # posición en la cuadrícula (n) de cada píxel del resultado: como cv2.resize(INTER_LINEAR) y el margen de pad
    sx = np.clip(((np.clip(X - pad, 0, max(1, cw) - 1) + 0.5) * n / max(1, cw) - 0.5), 0, n - 1)
    sy = np.clip(((np.clip(Y - pad, 0, max(1, ch) - 1) + 0.5) * n / max(1, ch) - 0.5), 0, n - 1)
    xs = np.nonzero((sx >= cols[0] - 1) & (sx <= cols[-1] + 1))[0]
    ys = np.nonzero((sy >= rows[0] - 1) & (sy <= rows[-1] + 1))[0]
    if xs.size == 0 or ys.size == 0:
        return True
    x0, x1, y0, y1 = int(xs[0]), int(xs[-1]) + 1, int(ys[0]), int(ys[-1]) + 1
    mapx = np.ascontiguousarray(np.broadcast_to(sx[x0:x1][None, :], (y1 - y0, x1 - x0)), dtype=np.float32)
    mapy = np.ascontiguousarray(np.broadcast_to(sy[y0:y1][:, None], (y1 - y0, x1 - x0)), dtype=np.float32)
    fx = cv2.remap(dx, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    fy = cv2.remap(dy, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mx = (X[x0:x1][None, :] + fx * float(max(1, cw - 1))).astype(np.float32)
    my = (Y[y0:y1][:, None] + fy * float(max(1, ch - 1))).astype(np.float32)
    out[y0:y1, x0:x1] = cv2.remap(rgba, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=(0, 0, 0, 0))
    return True


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
