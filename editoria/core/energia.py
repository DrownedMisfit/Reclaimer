"""
🔋 Cuidar el equipo del usuario (portátiles incluidos): ¿está sin enchufar? y cuántos hilos usar.

  en_bateria() -> bool        portátil funcionando con la batería (GetSystemPowerStatus de Windows; un PC de
                              sobremesa o algo que no se sabe → False). Se mira como mucho cada 10 s.
  hilos_decodificar(alto)     hilos para decodificar video en el visor: nunca más de la mitad de los núcleos (como el
                              banco de pruebas), menos para 1080p o menos, y solo 2 con la batería.
  hilos_ffmpeg()              hilos para los FFmpeg de fondo (copias ligeras…): la mitad de los núcleos; 2 con batería.

Para las pruebas: RECLAIMER_BATERIA=1 (o 0) simula estar con la batería (o enchufado).
"""
from __future__ import annotations

import os
import time

_cache: list = [None, 0.0]          # (valor, cuándo se miró)
CADA_S = 10.0


def _estado_windows() -> bool:
    import ctypes

    class _SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    s = _SPS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return False
    # ACLineStatus: 0 = desenchufado, 1 = enchufado, 255 = no se sabe · BatteryFlag 128 = sin batería, 255 = no se sabe
    return s.ACLineStatus == 0 and s.BatteryFlag not in (128, 255)


def en_bateria() -> bool:
    sim = os.environ.get("RECLAIMER_BATERIA")
    if sim in ("0", "1"):
        return sim == "1"
    ahora = time.monotonic()
    if _cache[0] is not None and ahora - _cache[1] < CADA_S:
        return _cache[0]
    try:
        val = _estado_windows()
    except Exception:  # noqa: BLE001 - otro sistema o algo raro: como enchufado
        val = False
    _cache[0], _cache[1] = val, ahora
    return val


def nucleos() -> int:
    return max(1, os.cpu_count() or 4)


def hilos_decodificar(alto: int = 1080) -> int:
    if en_bateria():
        return 2
    mitad = max(1, nucleos() // 2)
    return max(1, min(mitad, 4 if alto <= 1080 else 8))


def hilos_ffmpeg() -> int:
    return 2 if en_bateria() else max(1, nucleos() // 2)
