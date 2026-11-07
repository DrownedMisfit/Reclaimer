"""
😜 Caras graciosas de un clic (taller de miniaturas → «≈ Licuar»): ojos saltones, bocota, cabezón, mirar arriba,
sorpresa, enojo… como las miniaturas «graciosas» de YouTube. Busca las caras con YuNet (5 puntos: ojos, nariz y
comisuras de la boca) y aplica trazos de ≈ Licuar (core/liquify.py) en el sitio justo.

  faces(rgba) -> [{"box": (x, y, w, h), "re", "le", "nose", "mr", "ml"}]   en píxeles del contenido
  strokes(face, preset, w, h) -> [(modo, cx, cy, radio, fuerza, mover)]    en fracciones (como ≈ Licuar)
  apply(lay, preset, rgba, face=None, intensity=1.0, all_faces=False) -> bool   False si no hay cara
  PRESETS = [(clave, etiqueta, tooltip)]   GROUPS = [(grupo, [claves])]
  ajustes() -> (intensidad, todas_las_caras)   guardar(clave, valor): lo que el usuario eligió (QSettings)
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import liquify as L

PRESETS = [
    # 👀 Ojos
    ("ojos", "👀 Ojos saltones", "Infla los dos ojos"),
    ("entrecerrados", "😑 Entrecerrados", "Los párpados bajan hacia el centro de cada ojo"),
    ("arriba", "⬆ Mirar arriba", "Las pupilas miran hacia arriba"),
    ("abajo", "⬇ Mirar abajo", "Las pupilas miran hacia abajo"),
    ("izquierda", "⬅ Mirar a la izquierda", "Las pupilas miran hacia la izquierda de la imagen"),
    ("derecha", "➡ Mirar a la derecha", "Las pupilas miran hacia la derecha de la imagen"),
    ("bizco", "🤪 Bizco", "Las pupilas se van hacia la nariz"),
    ("guino", "😉 Guiño", "Cierra fuerte el ojo de la derecha de la imagen"),
    # 😮 Emociones
    ("sorpresa", "😲 Sorpresa", "Ojos saltones, boca redonda y abierta"),
    ("miedo", "😨 Miedo", "Ojos muy abiertos, cejas arriba y comisuras hacia fuera y abajo"),
    ("felicidad", "😊 Felicidad", "Comisuras arriba y ojos un poco entrecerrados"),
    ("risa", "😂 Risa", "Boca grande hacia abajo, comisuras arriba y ojos entrecerrados"),
    ("tristeza", "😢 Tristeza", "Comisuras abajo y cejas por fuera hacia abajo"),
    ("enojo", "😠 Enojo", "Cejas bajas hacia la nariz"),
    ("asco", "🤢 Asco", "La nariz se arruga hacia arriba y la boca se tuerce a un lado"),
    ("duda", "🤨 Duda", "Una ceja arriba y la boca hacia un lado"),
    # 🗿 Cabeza
    ("cabeza", "🗿 Cabezón", "Infla toda la cara"),
    ("carita", "🤏 Carita", "Encoge la cara"),
    ("estirada", "🥴 Cara estirada", "Estira la cara: la frente arriba y la barbilla abajo"),
    ("aplastada", "🥞 Cara aplastada", "Cara ancha y baja: los lados hacia fuera, arriba y abajo aplastados"),
    ("frente", "🧠 Frente enorme", "Infla la frente"),
    ("barbilla", "🧔 Barbilla enorme", "Infla la barbilla y la empuja hacia abajo"),
    # 👃 Rasgos
    ("boca", "👄 Bocota", "Agranda la boca y la abre hacia abajo"),
    ("sonrisa", "😁 Sonrisota", "Estira las comisuras hacia fuera y arriba"),
    ("nariz", "👃 Nariz grande", "Infla la nariz"),
    ("pato", "🦆 Boca de pato", "Boca estrecha en horizontal y labios hacia fuera"),
    ("labios", "💋 Labios finos", "Aprieta la boca en vertical: labios más finos"),
]

GROUPS = [
    ("👀 Ojos", ["ojos", "entrecerrados", "arriba", "abajo", "izquierda", "derecha", "bizco", "guino"]),
    ("😮 Emociones", ["sorpresa", "miedo", "felicidad", "risa", "tristeza", "enojo", "asco", "duda"]),
    ("🗿 Cabeza", ["cabeza", "carita", "estirada", "aplastada", "frente", "barbilla"]),
    ("👃 Rasgos", ["boca", "sonrisa", "nariz", "pato", "labios"]),
]

INTENSIDADES = [("Suave", 0.6), ("Normal", 1.0), ("Exagerado", 1.6)]


def ajustes() -> tuple[float, bool]:
    """La intensidad y «Todas las caras» que eligió el usuario (se recuerdan en QSettings)."""
    try:
        from PySide6.QtCore import QSettings
        st = QSettings("EditorIA", "EditorIA")
        inten = float(st.value("miniatura/caras_intensidad", 1.0))
        todas = str(st.value("miniatura/caras_todas", False)).lower() in ("true", "1")
        return (inten if inten > 0 else 1.0), todas
    except Exception:  # noqa: BLE001 - sin ajustes guardados: normal, una cara
        return 1.0, False


def guardar(clave: str, valor):
    try:
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue(clave, valor)
    except Exception:  # noqa: BLE001 - recordar la elección es opcional
        pass


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


# ---------- trazos: todo en píxeles del contenido y se convierte a fracciones al final ----------

def _geo(face: dict, w: int, h: int) -> dict:
    bx, by, bw, bh = face["box"]
    (rx, ry), (lx, ly) = face["re"], face["le"]
    (mrx, mry), (mlx, mly) = face["mr"], face["ml"]
    return {"w": w, "h": h, "bx": bx, "by": by, "bw": bw, "bh": bh, "cx": bx + bw / 2, "cy": by + bh / 2,
            "re": (rx, ry), "le": (lx, ly), "nose": tuple(face["nose"]), "mr": (mrx, mry), "ml": (mlx, mly),
            "mid": ((rx + lx) / 2, (ry + ly) / 2), "m": ((mrx + mlx) / 2, (mry + mly) / 2),
            "eye": max(1.0, math.hypot(lx - rx, ly - ry)), "mw": max(1.0, math.hypot(mlx - mrx, mly - mry))}


def _st(g: dict, modo: str, x: float, y: float, r: float, s: float = 1.0, mv: tuple = (0.0, 0.0)) -> tuple:
    """Un toque de ≈ Licuar. x, y y r en píxeles; mv = hacia dónde se lleva lo que hay bajo el pincel (píxeles)."""
    return (modo, x / g["w"], y / g["h"], r / g["h"], s, (mv[0] / g["w"], mv[1] / g["h"]))


def _sgn(v: float) -> float:
    return 1.0 if v >= 0 else -1.0


def _ojos_saltones(g):
    e = g["eye"]
    return [_st(g, "inflar", x, y, 0.7 * e, 0.75) for x, y in (g["re"], g["le"])]


def _cerrar(g, ojos, cantidad):
    """Párpados: arriba y abajo de cada ojo empujan hacia el centro (el ojo se hace más bajo). cantidad: en «ojos»."""
    e = g["eye"]
    out = []
    for x, y in ojos:
        out.append(_st(g, "empujar", x, y - 0.2 * e, 0.35 * e, 1.0, (0.0, cantidad * e)))
        out.append(_st(g, "empujar", x, y + 0.2 * e, 0.35 * e, 1.0, (0.0, -cantidad * e)))
    return out


def _mirar(g, dx, dy):
    """Pupilas: lo del centro de cada ojo se corre ~0.12 ojos hacia (dx, dy)."""
    e = g["eye"]
    return [_st(g, "empujar", x, y, 0.25 * e, 1.0, (dx * 0.12 * e, dy * 0.12 * e)) for x, y in (g["re"], g["le"])]


def _bizco(g):
    e = g["eye"]
    mx = g["mid"][0]
    return [_st(g, "empujar", x, y, 0.25 * e, 1.0, (_sgn(mx - x) * 0.12 * e, 0.0)) for x, y in (g["re"], g["le"])]


def _boca(g, bajada):
    """Bocota: la boca se agranda y el labio de abajo baja (bajada en fracción del ancho de la boca)."""
    mw = g["mw"]
    mx, my = g["m"]
    return [_st(g, "inflar", mx, my, 0.95 * mw, 0.55),
            _st(g, "empujar", mx, my + 0.25 * mw, 0.8 * mw, 1.0, (0.0, bajada * mw))]


def _sonrisa(g, sg):
    """Comisuras: sg = 1 sonrisa (arriba y afuera); sg = -1 tristeza (abajo y afuera)."""
    mw = g["mw"]
    mx, my = g["m"]
    out = [_st(g, "empujar", mx, my, 0.3 * mw, 1.0, (0.0, 0.08 * mw * sg))]
    for px, py in (g["mr"], g["ml"]):
        dx, dy = px - mx, py - my
        n = math.hypot(dx, dy) or 1.0
        out.append(_st(g, "empujar", px + dx / n * 0.08 * mw, py, 0.38 * mw, 1.0,
                       (dx / n * 0.3 * mw, dy / n * 0.3 * mw - 0.35 * mw * sg)))
    return out


def _tristeza(g):
    e = g["eye"]
    out = _sonrisa(g, -1)
    for x, y in (g["re"], g["le"]):                    # cejas: el extremo de fuera baja
        s = _sgn(x - g["mid"][0])
        out.append(_st(g, "empujar", x + s * 0.35 * e, y - 0.3 * e, 0.3 * e, 1.0, (0.0, 0.2 * e)))
    return out


def _enojo(g):
    e = g["eye"]
    out = []
    for x, y in (g["re"], g["le"]):                    # cejas: el extremo de dentro baja hacia la nariz
        s = _sgn(g["mid"][0] - x)
        out.append(_st(g, "empujar", x + s * 0.2 * e, y - 0.35 * e, 0.3 * e, 1.0, (s * 0.1 * e, 0.22 * e)))
    return out


def _lado(g, s):
    """La boca se corre hacia un lado (s = +1 derecha de la imagen, -1 izquierda)."""
    mw = g["mw"]
    mx, my = g["m"]
    return [_st(g, "empujar", mx, my, 0.7 * mw, 1.0, (s * 0.12 * mw, 0.0))]


def _sorpresa(g):
    mw = g["mw"]
    mx, my = g["m"]
    out = _ojos_saltones(g)
    for px, py in (g["mr"], g["ml"]):                  # la boca se encoge en horizontal (comisuras hacia dentro)
        out.append(_st(g, "empujar", px, py, 0.3 * mw, 1.0, (-_sgn(px - mx) * 0.15 * mw, 0.0)))
    out.append(_st(g, "empujar", mx, my - 0.2 * mw, 0.35 * mw, 1.0, (0.0, -0.15 * mw)))   # labio de arriba sube
    out.append(_st(g, "empujar", mx, my + 0.2 * mw, 0.35 * mw, 1.0, (0.0, 0.25 * mw)))    # labio de abajo baja
    return out


def _miedo(g):
    e, mw = g["eye"], g["mw"]
    mx, my = g["m"]
    out = [_st(g, "inflar", x, y, 0.8 * e, 0.9) for x, y in (g["re"], g["le"])]
    for x, y in (g["re"], g["le"]):                    # cejas arriba
        out.append(_st(g, "empujar", x, y - 0.35 * e, 0.3 * e, 1.0, (0.0, -0.2 * e)))
    for px, py in (g["mr"], g["ml"]):                  # comisuras hacia fuera y abajo
        dx, dy = px - mx, py - my
        n = math.hypot(dx, dy) or 1.0
        out.append(_st(g, "empujar", px + dx / n * 0.08 * mw, py, 0.38 * mw, 1.0,
                       (dx / n * 0.2 * mw, dy / n * 0.2 * mw + 0.2 * mw)))
    return out


def _asco(g):
    mw = g["mw"]
    mx, my = g["m"]
    nx, ny = g["nose"]
    out = [_st(g, "empujar", nx, ny + 0.6 * (my - ny), 0.4 * mw, 1.0, (0.0, -0.2 * mw))]   # nariz arrugada
    out += _lado(g, 1)
    out.append(_st(g, "empujar", *g["ml"], 0.35 * mw, 1.0, (0.0, -0.25 * mw)))            # una comisura arriba
    return out


def _duda(g):
    e = g["eye"]
    lx, ly = g["le"]
    return [_st(g, "empujar", lx, ly - 0.35 * e, 0.3 * e, 1.0, (0.0, -0.25 * e))] + _lado(g, 1)


def _estirada(g):
    bx, by, bh, cx = g["bx"], g["by"], g["bh"], g["cx"]
    return [_st(g, "empujar", cx, by + 0.12 * bh, 0.5 * bh, 1.0, (0.0, -0.14 * bh)),
            _st(g, "empujar", cx, by + 0.92 * bh, 0.5 * bh, 1.0, (0.0, 0.18 * bh))]


def _aplastada(g):
    bx, by, bw, bh, cx, cy = g["bx"], g["by"], g["bw"], g["bh"], g["cx"], g["cy"]
    return [_st(g, "empujar", bx + 0.05 * bw, cy, 0.3 * bw, 1.0, (-0.1 * bw, 0.0)),
            _st(g, "empujar", bx + 0.95 * bw, cy, 0.3 * bw, 1.0, (0.1 * bw, 0.0)),
            _st(g, "empujar", cx, by + 0.05 * bh, 0.3 * bh, 1.0, (0.0, 0.1 * bh)),
            _st(g, "empujar", cx, by + 0.95 * bh, 0.3 * bh, 1.0, (0.0, -0.1 * bh))]


def _barbilla(g):
    bh, by, cx = g["bh"], g["by"], g["cx"]
    return [_st(g, "inflar", cx, by + 0.85 * bh, 0.25 * bh, 0.6),
            _st(g, "empujar", cx, by + 0.9 * bh, 0.3 * bh, 1.0, (0.0, 0.12 * bh))]


def _pato(g):
    mw = g["mw"]
    mx, my = g["m"]
    out = [_st(g, "empujar", px, py, 0.3 * mw, 1.0, (-_sgn(px - mx) * 0.25 * mw, 0.0))
           for px, py in (g["mr"], g["ml"])]
    out.append(_st(g, "empujar", mx, my - 0.2 * mw, 0.35 * mw, 1.0, (0.0, -0.15 * mw)))   # labio de arriba fuera
    out.append(_st(g, "empujar", mx, my + 0.2 * mw, 0.35 * mw, 1.0, (0.0, 0.15 * mw)))    # labio de abajo fuera
    return out


def _labios(g):
    mw = g["mw"]
    mx, my = g["m"]
    return [_st(g, "empujar", mx, my - 0.12 * mw, 0.3 * mw, 1.0, (0.0, 0.1 * mw)),
            _st(g, "empujar", mx, my + 0.12 * mw, 0.3 * mw, 1.0, (0.0, -0.1 * mw))]


_TRAZOS = {
    "ojos": _ojos_saltones,
    "entrecerrados": lambda g: _cerrar(g, [g["re"], g["le"]], 0.07),
    "arriba": lambda g: _mirar(g, 0, -1),
    "abajo": lambda g: _mirar(g, 0, 1),
    "izquierda": lambda g: _mirar(g, -1, 0),
    "derecha": lambda g: _mirar(g, 1, 0),
    "bizco": _bizco,
    "guino": lambda g: _cerrar(g, [g["le"]], 0.16),
    "sorpresa": _sorpresa,
    "miedo": _miedo,
    "felicidad": lambda g: _sonrisa(g, 1) + _cerrar(g, [g["re"], g["le"]], 0.035),
    "risa": lambda g: _boca(g, 0.4) + _sonrisa(g, 1) + _cerrar(g, [g["re"], g["le"]], 0.07),
    "tristeza": _tristeza,
    "enojo": _enojo,
    "asco": _asco,
    "duda": _duda,
    "cabeza": lambda g: [_st(g, "inflar", g["cx"], g["cy"], 0.8 * g["bh"], 0.4)],
    "carita": lambda g: [_st(g, "encoger", g["cx"], g["cy"], 0.8 * g["bh"], 0.45)],
    "estirada": _estirada,
    "aplastada": _aplastada,
    "frente": lambda g: [_st(g, "inflar", g["cx"], g["by"] + 0.15 * g["bh"], 0.3 * g["bh"], 0.7)],
    "barbilla": _barbilla,
    "boca": lambda g: _boca(g, 0.3),
    "sonrisa": lambda g: _sonrisa(g, 1),
    "nariz": lambda g: [_st(g, "inflar", *g["nose"], 0.5 * g["eye"], 0.8)],
    "pato": _pato,
    "labios": _labios,
}


def strokes(face: dict, preset: str, w: int, h: int) -> list[tuple]:
    """Los trazos de ≈ Licuar de cada cara graciosa: (modo, cx, cy, radio, fuerza, mover) en fracciones."""
    fn = _TRAZOS.get(preset)
    return fn(_geo(face, w, h)) if fn else []


def apply(lay: dict, preset: str, rgba: np.ndarray, face: dict | None = None, intensity: float = 1.0,
          all_faces: bool = False) -> bool:
    """Aplica la cara graciosa a la cara más grande de la capa (rgba = su contenido, sin licuar).
    intensity: multiplica fuerzas y desplazamientos (suave 0.6, normal 1.0, exagerado 1.6).
    all_faces: aplica a todas las caras detectadas. face: una cara concreta (tiene prioridad)."""
    h, w = rgba.shape[:2]
    if face is not None:
        caras = [face]
    else:
        found = faces(rgba)
        if not found:
            return False
        caras = found if all_faces else found[:1]
    k = float(intensity)
    for cara in caras:
        for mode, x, y, r, s, mv in strokes(cara, preset, w, h):
            fuerza = min(s * k, 0.95) if mode in ("inflar", "encoger") else s * k   # más de 1 deformaría al revés
            L.stroke(lay, mode, x, y, r, fuerza, w / h, (mv[0] * k, mv[1] * k))
    return True
