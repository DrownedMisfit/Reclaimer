"""
Prueba de la corrección de color en 4 hilos (visor a pantalla completa): el resultado debe ser IGUAL, píxel a píxel,
al de un solo hilo, con tamaños de todo tipo (también con filas que no se reparten a partes iguales) y con
transparencia. Y que sea más rápido en un fotograma grande.
Ejecutar:  .venv/Scripts/python.exe tests/test_color_hilos.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from editoria.core import color as C  # noqa: E402


def main():
    rng = np.random.default_rng(11)
    look = {"exposure": 0.6, "contrast": 0.3, "saturation": -0.5, "temperature": 0.4}
    tamanos = [(40, 40), (400, 400), (1081, 1001), (1080, 1920), (2160, 1000)]
    for h, w in tamanos:
        px = rng.integers(0, 2 ** 32, size=(h, w), dtype=np.uint64).astype(np.uint32)
        px[:, :7] = 0xFF000000 | (px[:, :7] & 0x00FFFFFF)          # opacos (lo normal en el visor)
        px[::5, ::3] &= 0x00FFFFFF                                    # transparentes: conservan su alfa
        ref = C._apply_argb32_un_hilo(px.copy(), look)
        got = C.apply_argb32(px.copy(), look)
        assert got.shape == ref.shape and got.dtype == np.uint32, (got.shape, got.dtype)
        assert np.array_equal(got, ref), f"{h}×{w}: distinto del de un hilo en {int((got != ref).sum())} píxeles"
    print(f"✓ {len(tamanos)} tamaños (también filas que no se reparten a partes iguales): píxel a píxel = un hilo")

    # neutro: sin color, la misma imagen (se usa así en el visor)
    px = rng.integers(0, 2 ** 32, size=(1080, 1920), dtype=np.uint64).astype(np.uint32)
    assert np.array_equal(C.apply_argb32(px.copy(), {}), C._apply_argb32_un_hilo(px.copy(), {}))

    px = rng.integers(0, 2 ** 32, size=(1080, 1920), dtype=np.uint64).astype(np.uint32)
    C.apply_argb32(px.copy(), look)                                    # (tabla en caché y pool creado)
    t0 = time.perf_counter()
    for _ in range(10):
        C.apply_argb32(px, look)
    t_hilos = (time.perf_counter() - t0) / 10 * 1000
    t0 = time.perf_counter()
    for _ in range(10):
        C._apply_argb32_un_hilo(px, look)
    t_uno = (time.perf_counter() - t0) / 10 * 1000
    print(f"✓ fotograma 1920×1080: {t_uno:.1f} ms en un hilo → {t_hilos:.1f} ms en 4 hilos")
    print("TODO OK")


if __name__ == "__main__":
    main()
