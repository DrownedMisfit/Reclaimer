"""
Corrección de color por clip (como la página Color de Resolve, en sencillo).

Clip.color = {"exposure": -2…2 (pasos), "contrast": -1…1, "saturation": -1…1, "temperature": -1…1,
              "tint": -1…1, "shadows": -1…1, "highlights": -1…1, "lut": ruta .cube, "lut_mix": 0…1}

Todo se convierte en UNA tabla de color 3D (33×33×33, el formato de los LUT .cube):
  · el visor la aplica a cada fotograma (rápido, con una tabla de 64 niveles),
  · al exportar se guarda como .cube y FFmpeg la aplica con «lut3d».
Así lo que ves es lo que sale.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from .paths import cache_dir

SIZE = 33
KEYS = ("exposure", "contrast", "saturation", "temperature", "tint", "shadows", "highlights")
LABELS = {"exposure": "Exposición", "contrast": "Contraste", "saturation": "Saturación",
          "temperature": "Temperatura", "tint": "Tinte (verde ↔ magenta)", "shadows": "Sombras",
          "highlights": "Luces"}
RANGES = {"exposure": (-2.0, 2.0)}   # el resto: -1…1


def is_neutral(color: dict | None) -> bool:
    if not color:
        return True
    return all(abs(float(color.get(k, 0) or 0)) < 1e-4 for k in KEYS) and not (color.get("lut") and
                                                                                float(color.get("lut_mix", 1)) > 0)


# ------------------------------------------------------------------- LUT .cube
_cube_cache: dict[str, np.ndarray] = {}


def read_cube(path: str) -> np.ndarray:
    """Lee un LUT .cube (3D o 1D) → tabla (N, N, N, 3) en 0–1, índice [r, g, b]."""
    if path in _cube_cache:
        return _cube_cache[path]
    size3, size1 = 0, 0
    lo, hi = np.zeros(3), np.ones(3)
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            head = line.split()[0].upper()
            if head == "LUT_3D_SIZE":
                size3 = int(line.split()[1])
            elif head == "LUT_1D_SIZE":
                size1 = int(line.split()[1])
            elif head == "DOMAIN_MIN":
                lo = np.array([float(x) for x in line.split()[1:4]])
            elif head == "DOMAIN_MAX":
                hi = np.array([float(x) for x in line.split()[1:4]])
            elif head in ("TITLE", "LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
                continue
            else:
                try:
                    rows.append([float(x) for x in line.split()[:3]])
                except ValueError:
                    continue
    data = np.asarray(rows, np.float32)
    if size3:
        if len(data) < size3 ** 3:
            raise ValueError("El archivo .cube está incompleto.")
        # En .cube el rojo cambia más rápido: data[(b*N + g)*N + r]
        lut = data[: size3 ** 3].reshape(size3, size3, size3, 3).transpose(2, 1, 0, 3)
    elif size1:
        curve = data[:size1]
        grid = np.linspace(0, 1, SIZE)
        chans = [np.interp(grid, np.linspace(0, 1, size1), curve[:, c]) for c in range(3)]
        r, g, b = np.meshgrid(chans[0], chans[1], chans[2], indexing="ij")
        lut = np.stack([r, g, b], axis=-1)
    else:
        raise ValueError("No parece un LUT .cube válido.")
    lut = np.clip((lut - lo) / np.maximum(hi - lo, 1e-6), 0, 1).astype(np.float32)
    _cube_cache[path] = lut
    return lut


def sample(lut: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Aplica una tabla 3D (interpolación trilineal) a colores rgb (…, 3) en 0–1."""
    n = lut.shape[0]
    x = np.clip(rgb, 0, 1) * (n - 1)
    i0 = np.floor(x).astype(np.int32)
    i0 = np.minimum(i0, n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for dr in (0, 1):
        wr = fr if dr else 1 - fr
        for dg in (0, 1):
            wg = fg if dg else 1 - fg
            for db in (0, 1):
                wb = fb if db else 1 - fb
                out = out + lut[r0 + dr, g0 + dg, b0 + db] * (wr * wg * wb)
    return out


# ------------------------------------------------------------------- ajustes → tabla
def grade(rgb: np.ndarray, color: dict) -> np.ndarray:
    """Los ajustes sobre colores rgb en 0–1 (en este orden: LUT, exposición, balance, contraste,
    sombras/luces, saturación)."""
    c = {k: float(color.get(k, 0) or 0) for k in KEYS}
    x = rgb.astype(np.float32)
    if color.get("lut") and os.path.exists(color["lut"]):
        mix = float(color.get("lut_mix", 1.0))
        if mix > 0:
            x = x * (1 - mix) + sample(read_cube(color["lut"]), x) * mix
    if c["exposure"]:
        x = x * (2.0 ** c["exposure"])
    if c["temperature"] or c["tint"]:
        t, ti = c["temperature"], c["tint"]
        gains = np.array([1 + 0.18 * t + 0.06 * ti, 1 - 0.12 * ti, 1 - 0.18 * t + 0.06 * ti], np.float32)
        x = x * gains
    if c["contrast"]:
        k = 1 + c["contrast"] * (0.8 if c["contrast"] > 0 else 0.6)
        x = (x - 0.5) * k + 0.5
    x = np.clip(x, 0, 1)
    if c["shadows"] or c["highlights"]:
        lum = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        sh = c["shadows"] * 0.35 * (1 - lum) ** 2
        hl = c["highlights"] * 0.35 * lum ** 2
        x = x + (sh + hl)[..., None]
    if c["saturation"]:
        lum = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        x = lum + (x - lum) * (1 + c["saturation"])
    return np.clip(x, 0, 1)


def identity(n: int = SIZE) -> np.ndarray:
    g = np.linspace(0, 1, n, dtype=np.float32)
    r, gg, b = np.meshgrid(g, g, g, indexing="ij")
    return np.stack([r, gg, b], axis=-1)


def table(color: dict, n: int = SIZE) -> np.ndarray:
    return grade(identity(n), color)


def key(color: dict) -> str:
    d = {k: round(float(color.get(k, 0) or 0), 4) for k in KEYS}
    d["lut"] = color.get("lut") or ""
    d["lut_mix"] = round(float(color.get("lut_mix", 1.0)), 3)
    if d["lut"] and os.path.exists(d["lut"]):
        d["lut_mtime"] = os.path.getmtime(d["lut"])
    return hashlib.md5(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def cube_file(color: dict) -> str:
    """Escribe (una vez) la tabla como .cube para FFmpeg y devuelve su ruta."""
    path = os.path.join(str(cache_dir("color")), f"grade_{key(color)}.cube")
    if not os.path.exists(path):
        lut = table(color)
        with open(path, "w", encoding="ascii") as f:
            f.write(f"TITLE \"Reclaimer\"\nLUT_3D_SIZE {SIZE}\n")
            data = lut.transpose(2, 1, 0, 3).reshape(-1, 3)     # el rojo cambia más rápido
            f.write("\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in data))
            f.write("\n")
    return path


# ------------------------------------------------------------------- visor (rápido)
_fast_cache: dict[str, np.ndarray] = {}


def fast_table(color: dict) -> np.ndarray:
    """Tabla de 64 niveles por canal, aplanada (262 144 × 3, uint8): un solo acceso por píxel."""
    k = key(color)
    if k not in _fast_cache:
        lut = table(color, 64)
        if len(_fast_cache) > 24:
            _fast_cache.clear()
        _fast_cache[k] = (lut.reshape(-1, 3) * 255 + 0.5).astype(np.uint8)
    return _fast_cache[k]


def apply_rgb8(img: np.ndarray, color: dict) -> np.ndarray:
    """img (H, W, 3) uint8 RGB → corregida (para el visor y las gráficas)."""
    flat = fast_table(color)
    q = (img >> 2).astype(np.int32)
    idx = (q[..., 0] << 12) | (q[..., 1] << 6) | q[..., 2]
    return flat[idx]


# ------------------------------------------------------------------- automático
def auto(rgb8: np.ndarray) -> dict:
    """Color automático a partir de un fotograma: exposición y contraste a un rango sano y balance de
    blancos por «mundo gris» (suave: nunca exagera)."""
    x = rgb8.reshape(-1, 3).astype(np.float32) / 255
    lum = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lo, mid, hi = np.percentile(lum, [2, 50, 98])
    out = {k: 0.0 for k in KEYS}
    if mid > 0.02:
        out["exposure"] = float(np.clip(np.log2(0.45 / mid) * 0.6, -1.0, 1.0))
    spread = max(hi - lo, 1e-3)
    out["contrast"] = float(np.clip((0.85 - spread) * 0.8, -0.3, 0.5))
    means = x[(lum > 0.08) & (lum < 0.92)].mean(axis=0) if ((lum > 0.08) & (lum < 0.92)).any() else x.mean(axis=0)
    r, g, b = means
    out["temperature"] = float(np.clip((b - r) / max(means.mean(), 1e-3) * 1.2, -0.6, 0.6))
    out["tint"] = float(np.clip((g - (r + b) / 2) / max(means.mean(), 1e-3) * 1.5, -0.5, 0.5))
    sat = float(np.mean(x.max(axis=1) - x.min(axis=1)))
    out["saturation"] = float(np.clip((0.22 - sat) * 1.5, -0.2, 0.35))
    return {k: round(v, 3) for k, v in out.items()}


_fast32: dict[str, np.ndarray] = {}


def apply_argb32(px: np.ndarray, color: dict) -> np.ndarray:
    """Píxeles empaquetados de Qt (uint32 0xAARRGGBB) → corregidos. ~5 ms por fotograma del visor."""
    k = key(color)
    flat = _fast32.get(k)
    if flat is None:
        lut = (table(color, 64).reshape(-1, 3) * 255 + 0.5).astype(np.uint32)
        flat = np.uint32(0xFF000000) | (lut[:, 0] << 16) | (lut[:, 1] << 8) | lut[:, 2]
        if len(_fast32) > 24:
            _fast32.clear()
        _fast32[k] = flat
    idx = (px >> 18) & 0x3F
    idx <<= 6
    idx |= (px >> 10) & 0x3F
    idx <<= 6
    idx |= (px >> 2) & 0x3F
    out = np.take(flat, idx)
    out &= 0x00FFFFFF
    out |= px & 0xFF000000          # conserva la transparencia original
    return out
