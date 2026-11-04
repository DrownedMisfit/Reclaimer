"""
Escuchar tus palabras + el MOVIMIENTO de la imagen (sencillo y rápido, sin modelos pesados).

  · Dices «paisaje», «ciudad», «edificio», «cielo»… → mejor los momentos QUIETOS (escenario, fondo).
  · Dices «personaje», «pelea», «carro», «persecución»… → mejor los momentos CON MOVIMIENTO.
  · Dices «gameplay» / «cinemática» → mejor los clips de ese tipo.
El movimiento sale del análisis que Reclaimer ya guarda de cada video (edit_maker.motion_profile): no se
calcula nada nuevo; si un video aún no se analizó, simplemente no hay empujón.
"""
from __future__ import annotations

import os
import re

import numpy as np

QUIET = {"paisaje", "paisajes", "escenario", "escenarios", "edificio", "edificios", "ciudad", "ciudades", "cielo",
         "montaña", "montañas", "bosque", "castillo", "ruinas", "mapa", "fondo", "lugar", "lugares", "vista",
         "vistas", "arquitectura", "calle", "pueblo", "atardecer", "amanecer", "mundo", "ambiente", "estatua"}
MOVING = {"personaje", "personajes", "pelea", "peleas", "combate", "combates", "carro", "carros", "coche",
          "coches", "vehículo", "vehículos", "persecución", "explosión", "explosiones", "disparo", "disparos",
          "dispara", "corre", "corriendo", "salto", "batalla", "acción", "enemigo", "enemigos", "jefe",
          "monstruo", "criatura", "golpe", "ataque", "ataca", "huye", "vuela", "nave", "moto", "caballo"}
GAMEPLAY = {"gameplay", "jugabilidad", "jugando", "partida", "controles", "mecánicas", "mecánica"}
CINEMATIC = {"cinemática", "cinemáticas", "cinematica", "cinematicas", "cutscene", "cutscenes", "escena",
             "escenas", "tráiler", "trailer"}
BOOST = 0.05          # empujón en la puntuación del B-roll (las similitudes van de ~0,2 a ~0,35)
_cache: dict[str, np.ndarray | None] = {}


def wants(text: str) -> dict:
    w = set(re.findall(r"[a-záéíóúñü]+", (text or "").lower()))
    q, mv = len(w & QUIET), len(w & MOVING)
    return {"motion": "quiet" if q > mv else ("moving" if mv > q else None),
            "type": "Gameplay" if w & GAMEPLAY else ("Cinemáticas" if w & CINEMATIC else None)}


def _profile(path: str) -> np.ndarray | None:
    if path in _cache:
        return _cache[path]
    arr = None
    try:
        from .edit_maker import _profile_path
        pp = _profile_path(path)
        if os.path.exists(pp):
            m = np.load(pp)["motion"].astype(np.float32)
            hi = float(np.percentile(m, 90)) if len(m) else 0.0
            arr = np.clip(m / hi, 0, 1) if hi > 1e-6 else np.zeros_like(m)
    except (OSError, ValueError, KeyError):
        arr = None
    _cache[path] = arr
    return arr


def level(path: str, t: float, span: float = 1.0) -> float | None:
    """Movimiento 0 (quieto) – 1 (mucho) alrededor del segundo t de ese archivo (None si no está analizado)."""
    from .edit_maker import STEP
    arr = _profile(path) if path else None
    if arr is None or not len(arr):
        return None
    a = max(0, int((t - span / 2) / STEP))
    b = min(len(arr), max(a + 1, int((t + span / 2) / STEP)))
    return float(arr[a:b].mean())


def bias(w: dict, path: str, t: float, ai_type: str = "") -> float:
    """Empujón (−BOOST … +2·BOOST) para un momento según lo que dijiste."""
    out = 0.0
    if w.get("motion"):
        lv = level(path, t)
        if lv is not None:
            out += BOOST * ((1 - lv) if w["motion"] == "quiet" else lv) * 2 - BOOST
    if w.get("type") and ai_type:
        out += BOOST if ai_type == w["type"] else -BOOST * 0.5
    return out
