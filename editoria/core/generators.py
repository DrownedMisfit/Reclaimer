"""
🟦 Generadores y 🎨 capas de ajuste: imágenes que crea Reclaimer (no hace falta importar nada).

  gen = {"kind": "solid" | "linear" | "radial" | "adjust", "c1": "#rrggbb", "c2": "#rrggbb", "angle": grados}

  · Color sólido / degradado: una imagen PNG del tamaño del proyecto. Se usa como cualquier imagen (posición,
    deformar, opacidad, efectos, modos de fusión…).
  · Capa de ajuste: una imagen TRANSPARENTE en una pista de video; su color y sus efectos se aplican a TODO lo que
    hay debajo mientras dura (en el visor y al exportar). Su opacidad y sus fundidos suavizan el efecto.

Los PNG van a «datos/generadores» (el nombre sale de su contenido: el mismo generador = el mismo archivo); si faltan
(p. ej. el proyecto se abre en otro PC), se vuelven a crear al abrirlo.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import numpy as np

KINDS = {"solid": "Color sólido", "linear": "Degradado", "radial": "Degradado circular", "adjust": "Capa de ajuste"}
ICONS = {"solid": "🟦", "linear": "🌈", "radial": "🔵", "adjust": "🎨"}
DEFAULT = {"kind": "solid", "c1": "#1e1e24", "c2": "#3a6df0", "angle": 90}


def gen_of(m) -> dict:
    return dict(getattr(m, "gen", None) or {}) if m is not None else {}


def is_adjust(m) -> bool:
    return gen_of(m).get("kind") == "adjust"


def is_generated(m) -> bool:
    return bool(gen_of(m).get("kind"))


def clean(gen: dict) -> dict:
    g = dict(DEFAULT, **{k: v for k, v in (gen or {}).items() if v is not None})
    if g["kind"] not in KINDS:
        g["kind"] = "solid"
    out = {"kind": g["kind"]}
    if g["kind"] != "adjust":
        out["c1"] = _hex(g["c1"])
        if g["kind"] != "solid":
            out["c2"] = _hex(g["c2"])
        if g["kind"] == "linear":
            out["angle"] = int(round(float(g.get("angle", 90)))) % 360
    return out


def name_of(gen: dict) -> str:
    g = clean(gen)
    if g["kind"] == "adjust":
        return f"{ICONS['adjust']} Capa de ajuste"
    if g["kind"] == "solid":
        return f"{ICONS['solid']} Color sólido {g['c1']}"
    return f"{ICONS[g['kind']]} {KINDS[g['kind']]} {g['c1']} → {g['c2']}"


def _hex(c) -> str:
    s = str(c or "#000000").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        int(s[:6], 16)
    except ValueError:
        s = "000000"
    return "#" + s[:6].lower().ljust(6, "0")


def _rgb(c: str) -> np.ndarray:
    s = _hex(c).lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def folder() -> str:
    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "generadores")
    os.makedirs(d, exist_ok=True)
    return d


def path_for(gen: dict, W: int, H: int) -> str:
    g = clean(gen)
    if g["kind"] == "adjust":        # transparente: basta una imagen pequeña con la forma del proyecto
        k = max(1, math.gcd(int(W), int(H)))
        W, H = int(W) // k, int(H) // k
        while W < 32 or H < 32:
            W, H = W * 2, H * 2
    key = hashlib.sha1(json.dumps([g, int(W), int(H)], sort_keys=True).encode()).hexdigest()[:12]
    return os.path.join(folder(), f"{g['kind']}_{int(W)}x{int(H)}_{key}.png")


def render(gen: dict, W: int, H: int) -> np.ndarray:
    """La imagen (alto × ancho × 4, BGRA) del generador."""
    g = clean(gen)
    if g["kind"] == "adjust":
        return np.zeros((H, W, 4), np.uint8)
    c1 = _rgb(g["c1"])
    if g["kind"] == "solid":
        rgb = np.broadcast_to(c1, (H, W, 3))
    else:
        c2 = _rgb(g["c2"])
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        if g["kind"] == "linear":     # 0° = de izquierda a derecha, 90° = de arriba abajo
            a = math.radians(g.get("angle", 90))
            dx, dy = math.cos(a), math.sin(a)
            proj = (xx - W / 2) * dx + (yy - H / 2) * dy
            half = abs(W / 2 * dx) + abs(H / 2 * dy)
            u = (proj / max(half, 1e-6) + 1) / 2
        else:                         # radial: c1 en el centro, c2 en las esquinas
            u = np.hypot(xx - W / 2, yy - H / 2) / max(math.hypot(W / 2, H / 2), 1e-6)
        u = np.clip(u, 0, 1)[..., None]
        rgb = c1 * (1 - u) + c2 * u
        rgb = rgb + np.random.default_rng(0).uniform(-0.5, 0.5, rgb.shape)      # sin escalones (bandas)
    out = np.empty((H, W, 4), np.uint8)
    out[..., :3] = np.clip(rgb[..., ::-1], 0, 255).astype(np.uint8)
    out[..., 3] = 255
    return out


def make(gen: dict, W: int, H: int) -> str:
    """Crea (si no está ya) el PNG del generador y devuelve su ruta."""
    import cv2
    path = path_for(gen, W, H)
    if os.path.exists(path):
        return path
    img = render(gen, *((int(v) for v in _size(gen, W, H))))
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("No se pudo crear la imagen del generador.")
    tmp = path + ".tmp"
    buf.tofile(tmp)
    os.replace(tmp, path)
    return path


def _size(gen: dict, W: int, H: int) -> tuple[int, int]:
    p = os.path.basename(path_for(gen, W, H))
    w, h = p.split("_")[1].split("x")
    return int(w), int(h)
