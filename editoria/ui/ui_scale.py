"""
🔍 Escala de TODA la interfaz (botones, iconos, márgenes, letras y línea de tiempo), como la escala de Windows pero
solo en Reclaimer. En una pantalla 2K o 4K con Windows al 100 % todo se veía pequeño: en «Automática», Reclaimer se
ve al 125 % en 2K y al 150 % en 4K (si Windows ya escala, no se toca). Se aplica al abrir Reclaimer (Qt la lee al
arrancar). Ventana → «🔍 Escala de la interfaz».

  OPCIONES                     ("auto", "100", "125", "150", "175")
  factor(opcion, ancho, escala_windows) -> 1.0, 1.25…   (función pura: la usan el arranque y las pruebas)
  apply_before_app()           pone QT_SCALE_FACTOR según el ajuste (llamar ANTES de crear QApplication)
"""
from __future__ import annotations

import os
import sys

KEY = "interfaz/escala"
OPCIONES = ("auto", "100", "125", "150", "175")
NOMBRES = {"auto": "Automática (2K → 125 %, 4K → 150 %)", "100": "100 %", "125": "125 %", "150": "150 %",
           "175": "175 %"}


def factor(opcion: str, ancho: int, escala_windows: float) -> float:
    """Cuánto agrandar Reclaimer. «auto»: solo si Windows está al 100 % (si ya escala, Qt lo respeta tal cual)."""
    if opcion in OPCIONES and opcion != "auto":
        return int(opcion) / 100
    if escala_windows > 1.01:
        return 1.0
    if ancho >= 3600:
        return 1.5
    if ancho >= 2400:
        return 1.25
    return 1.0


def _pantalla() -> tuple[int, float]:
    """(ancho físico de la pantalla principal, escala de Windows) sin crear nada de Qt. Si no se sabe: (0, 1.0)."""
    if sys.platform != "win32":
        return 0, 1.0
    ancho, escala = 0, 1.0
    try:
        import ctypes
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = u.GetDC(0)
        try:
            ancho = int(g.GetDeviceCaps(hdc, 118))          # DESKTOPHORZRES: píxeles reales
        finally:
            u.ReleaseDC(0, hdc)
    except Exception:  # noqa: BLE001
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics") as k:
            escala = int(winreg.QueryValueEx(k, "AppliedDPI")[0]) / 96
    except Exception:  # noqa: BLE001
        pass
    return ancho, escala


def setting() -> str:
    try:
        from PySide6.QtCore import QSettings
        v = str(QSettings("EditorIA", "EditorIA").value(KEY, "auto"))
    except Exception:  # noqa: BLE001
        v = "auto"
    return v if v in OPCIONES else "auto"


def apply_before_app() -> float:
    """Pone la escala (QT_SCALE_FACTOR) antes de crear la aplicación. Si ya la pusiste tú a mano, se respeta."""
    if os.environ.get("QT_SCALE_FACTOR"):
        return float(os.environ["QT_SCALE_FACTOR"] or 1.0)
    ancho, escala = _pantalla()
    f = factor(setting(), ancho, escala)
    if abs(f - 1.0) > 1e-3:
        os.environ["QT_SCALE_FACTOR"] = f"{f:g}"
    return f
