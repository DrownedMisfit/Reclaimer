"""
🗣 Diálogos sin ruido de fondo (Demucs v4 en el motor de IA): de un video o audio se queda SOLO con las voces
(fuera la música del juego, explosiones, ambiente). Se hace una vez por archivo, entero, y se guarda en
datos/voz_separada (el mismo tiempo que el original: los clips solo cambian de archivo).

  cached(path) -> wav ya hecho o None
  isolate(path, progress, cancelled) -> wav
"""
from __future__ import annotations

import os

from ..core import media as media_tools
from ..core import motor_ia
from ..core.paths import app_data_dir


def out_dir() -> str:
    d = app_data_dir() / "voz_separada"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _target(path: str) -> str:
    return os.path.join(out_dir(), f"{media_tools.cache_key(path)}_dialogos.wav")


def cached(path: str) -> str | None:
    t = _target(path)
    return t if os.path.exists(t) and os.path.getsize(t) > 1000 else None


def isolate(path: str, progress=None, cancelled=None) -> str:
    done = cached(path)
    if done:
        return done
    out = _target(path)
    tmp = out + ".parcial.wav"
    res = motor_ia.run("separar_voz.py", {"ffmpeg": media_tools.ffmpeg(), "entrada": path, "salida": tmp,
                                         "modelo": "htdemucs_ft"}, progress, cancelled)
    os.replace(res, out)
    return out
