"""
🔓 Soltar archivos antes de borrarlos, moverlos o renombrarlos (21/11).

En Windows un archivo abierto no se puede mandar a la Papelera, mover ni renombrar («WinError 32»). Reclaimer abre los
medios en varios sitios: el motor de video propio (core/live_video.FrameSource: pista mixta, fotograma suelto,
transiciones), los reproductores de Qt del visor y los análisis en segundo plano (ui/cola_analisis: lectura única,
huellas…). TODO lo que vaya a tocar un medio en el disco llama antes a:

  soltar_archivos(rutas)   rutas = archivos o carpetas (lo de dentro también). Devuelve las que siguen ocupadas.

Qué hace, rápido y sin congelar (espera corta):
  1) durante unos segundos nada nuevo abre esos archivos (live_video.retener; los reproductores de Qt también lo miran):
     el visor no los vuelve a abrir entre medias;
  2) cierra todas las FrameSource de esos archivos (live_video.cerrar_fuentes, estén donde estén);
  3) avisa a quien se haya apuntado con registrar(fn): el visor suelta sus reproductores de Qt y su fotograma suelto,
     la cola de análisis cancela lo que lee esos archivos (fn(claves) → rutas que estaba usando, para esperarlas);
  4) solo si algo los tenía abiertos, espera (como mucho «espera» s) a que Windows los dé por libres.
Después, el visor vuelve a abrir solo lo que necesite cuando haga falta (con la ruta nueva si se movió).

  with soltando(rutas):    lo mismo, y al salir (haya ido bien o mal) se quita la retención: si la operación falla y
                           el archivo sigue ahí, el visor lo vuelve a abrir al momento (no se queda 3 s sin imagen).
  dejar_de_retener(rutas)  quitar la retención a mano (p. ej. al acabar un trabajo en segundo plano).

⚠ REGLA: quien lanza un hilo que va a borrar o mover medios llama a soltar_archivos ANTES, en el hilo principal (como
descargas_generales.mover). Desde otro hilo solo se hace 1), 2) y la espera: los reproductores de Qt no se pueden tocar
fuera del hilo principal, así que si alguno tenía el archivo, la operación falla (WinError 32) y se avisa del fallo, sin
caerse (test_soltar_archivos lo prueba).
"""
from __future__ import annotations

import os
import sys
import threading
import time

RETENER_S = 3.0          # cuánto tiempo no se vuelven a abrir (lo que tarda de sobra borrar o mover uno)
ESPERA_S = 1.5           # tope de espera a que Windows los dé por libres

_SOLTADORES: list = []   # fn(claves: set[str]) -> iterable de rutas que tenía abiertas (para esperarlas)


def registrar(fn) -> None:
    """Apunta a alguien que guarda archivos abiertos (el visor, la cola de análisis). Se llama en el hilo principal."""
    if fn not in _SOLTADORES:
        _SOLTADORES.append(fn)


def clave(ruta: str) -> str:
    from .live_video import clave_ruta
    return clave_ruta(ruta)


def _hilo_principal() -> bool:
    if threading.current_thread() is not threading.main_thread():
        return False
    try:
        from PySide6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        return app is None or QThread.currentThread() is app.thread()
    except Exception:  # noqa: BLE001
        return True


def libre(ruta: str) -> bool:
    """¿Windows deja borrarlo o moverlo ya? (se pide abrirlo con permiso de BORRAR: falla si alguien lo tiene abierto sin
    compartir el borrado, que es justo lo que da «WinError 32»). Fuera de Windows, o si no existe, sí."""
    if sys.platform != "win32" or not os.path.exists(ruta):
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        DELETE, COMPARTIR, OPEN_EXISTING, BACKUP = 0x00010000, 0x7, 3, 0x02000000
        h = k32.CreateFileW(str(ruta), DELETE, COMPARTIR, None, OPEN_EXISTING, BACKUP, None)
        if h is None or h == wintypes.HANDLE(-1).value:
            return ctypes.get_last_error() not in (32, 33)        # (32/33: abierto o bloqueado por otro)
        k32.CloseHandle(h)
        return True
    except Exception:  # noqa: BLE001 - sin poder mirarlo: se da por libre (como antes)
        return True


def soltar_archivos(rutas, retener_s: float = RETENER_S, espera: float = ESPERA_S) -> list[str]:
    """🔓 Suelta esos archivos (o carpetas) de todo lo que los tenga abiertos en Reclaimer. Llamar ANTES de borrarlos,
    moverlos o renombrarlos. Devuelve las rutas que, tras la espera, siguen ocupadas (otro programa, p. ej.)."""
    from . import live_video as LV
    rutas = [str(r) for r in (rutas or []) if r]
    claves = {k for k in (LV.clave_ruta(r) for r in rutas) if k}
    if not claves:
        return []
    LV.retener(claves, retener_s)
    t0 = time.monotonic()
    abiertas = set()
    with LV._VIVAS_LOCK:
        abiertas.update(LV.clave_ruta(s.path) for s in list(LV._VIVAS)
                        if not s.cerrado and LV._toca(LV.clave_ruta(s.path), claves))
    LV.cerrar_fuentes(claves, espera=min(1.0, espera))
    principal = _hilo_principal()
    if principal:
        for fn in list(_SOLTADORES):
            try:
                for r in fn(claves) or ():
                    abiertas.add(LV.clave_ruta(r))
            except Exception:  # noqa: BLE001 - uno que falla no impide soltar lo demás
                pass
    # (carpetas: se espera a cada archivo de dentro que estaba abierto; archivos: a ellos)
    esperar = sorted(k for k in abiertas if k)
    fin = t0 + max(0.0, espera)
    ocupadas = [k for k in esperar if not libre(k)]
    while ocupadas and time.monotonic() < fin:
        if principal:
            try:
                from PySide6.QtCore import QCoreApplication
                QCoreApplication.processEvents()          # (los reproductores de Qt sueltan el archivo con su bucle)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.02)
        ocupadas = [k for k in ocupadas if not libre(k)]
    return ocupadas


def dejar_de_retener(rutas) -> None:
    """La operación acabó (bien o mal): el visor ya puede volver a abrir esos archivos (si siguen ahí)."""
    from . import live_video as LV
    LV.retener([str(r) for r in (rutas or []) if r], 0)


class soltando:
    """with soltando(rutas) as ocupadas: soltar_archivos(rutas) al entrar y dejar_de_retener(rutas) al salir, haya ido
    bien o mal (una operación que falla no deja el visor 3 s sin volver a abrir el archivo)."""

    def __init__(self, rutas, espera: float = ESPERA_S):
        self.rutas = [str(r) for r in (rutas or []) if r]
        self.espera = espera

    def __enter__(self) -> list[str]:
        return soltar_archivos(self.rutas, espera=self.espera)

    def __exit__(self, *_exc) -> bool:
        dejar_de_retener(self.rutas)
        return False
