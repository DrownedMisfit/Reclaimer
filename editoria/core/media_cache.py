"""
🧹 Lo que Reclaimer guarda de cada medio en datos/cache (miniaturas, copias ligeras, formas de onda, análisis de la IA),
para «⟲ Reiniciar todo» de la biblioteca: encontrarlo, decir cuánto ocupa y borrarlo. NUNCA toca los archivos
originales del usuario: solo lo que el programa creó en su caché (archivos que empiezan por la clave del medio).

No entran (los usan otras cosas aunque quites el medio): fotogramas y recortes de tus miniaturas de YouTube,
estabilización de clips, nombres aprendidos (entidades), sonidos generados, carpetas de palabras clave.
"""
from __future__ import annotations

import os

from . import media as media_tools
from .paths import app_data_dir

# grupo → (nombre para el aviso, carpetas de datos/cache)
GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "miniaturas": ("Miniaturas (biblioteca, tira de fotogramas, momentos)",
                   ("miniaturas", "tira", "momentos", "escenas_miniaturas")),
    "copias": ("Copias ligeras (Calidad Media / Un cuarto)", ("proxies",)),
    "ondas": ("Formas de onda", ("formas_de_onda",)),
    "analisis": ("Análisis de la IA (lo que vio en cada clip, movimiento, planos, silencios, palabras clave)",
                 ("huellas_clips", "huellas_a_fondo", "pistas", "movimiento", "siluetas", "palabras", "pistas_obs",
                  "escenas", "silencio", "negros", "barras")),
}


def find(paths) -> dict[str, list[str]]:
    """{grupo: [archivos de la caché de esos medios]}. Un archivo es de un medio si su nombre empieza por la clave
    del medio (ruta + fecha + tamaño, 20 letras) seguida de «_» o «.»."""
    keys = {media_tools.cache_key(p) for p in paths if p}
    out: dict[str, list[str]] = {g: [] for g in GROUPS}
    if not keys:
        return out
    base = app_data_dir() / "cache"
    for group, (_name, subs) in GROUPS.items():
        for sub in subs:
            d = base / sub
            if not d.is_dir():
                continue
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                n = e.name
                if len(n) > 20 and n[:20] in keys and n[20] in "_." and e.is_file():
                    out[group].append(e.path)
    return out


def size_of(files) -> int:
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    return total


def delete(files) -> tuple[int, int]:
    """Borra esos archivos de la caché. (borrados, no se pudieron: p. ej. en uso)."""
    base = os.path.normcase(os.path.abspath(str(app_data_dir() / "cache")))
    ok = bad = 0
    for f in files:
        full = os.path.normcase(os.path.abspath(f))
        if not full.startswith(base + os.sep):          # seguridad: solo dentro de datos/cache
            bad += 1
            continue
        try:
            os.remove(f)
            ok += 1
        except OSError:
            bad += 1
    return ok, bad
