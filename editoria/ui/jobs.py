"""Tareas largas (transcribir, analizar) en segundo plano, sin congelar la ventana."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

import time

# (lo que usa la salida con un hilo vivo —_soltar, _vigilante—, importado YA: importar al salir, con un hilo ocupado
#  ejecutando Python, era muy lento —cada búsqueda en disco suelta el GIL y tarda en recuperarlo— y la salida pasaba
#  de ~3 s a 6–9 s con el PC cargado)
import ctypes  # noqa: E402,F401
import os as _os  # noqa: E402,F401
import threading as _threading  # noqa: E402,F401
try:
    from ctypes import wintypes as _wintypes  # noqa: F401
except (ImportError, ValueError):     # (fuera de Windows)
    _wintypes = None

from PySide6.QtCore import Qt, QThread, QTimer, Signal

# Cuánto pueden usar del PC los trabajos en segundo plano (panel «◈ Tareas de la IA»):
# full = todo · half = la mitad del tiempo (descansa tanto como trabaja) · quarter = una cuarta parte.
REST = {"full": 0.0, "half": 1.0, "quarter": 3.0}
_level = {"value": None}


def resource_level() -> str:
    if _level["value"] is None:
        from PySide6.QtCore import QSettings
        v = str(QSettings("EditorIA", "EditorIA").value("ia/recursos", "full"))
        _level["value"] = v if v in REST else "full"
    return _level["value"]


def set_resource_level(level: str):
    from PySide6.QtCore import QSettings
    if level in REST:
        _level["value"] = level
        QSettings("EditorIA", "EditorIA").setValue("ia/recursos", level)

from ..ai.base import Cancelled
from ..core.paths import log_path

# Trabajos en marcha: se guardan aquí hasta que terminan DE VERDAD. Así ningún hilo se destruye mientras corre
# (en Qt 6 eso cierra el programa de golpe: «QThread: Destroyed while thread is still running»).
_LIVE: set = set()


def live_jobs() -> list:
    out = []
    for j in list(_LIVE):
        try:
            if j.isRunning():
                out.append(j)
        except RuntimeError:
            _LIVE.discard(j)
    return out


SALIDA_ESPERA = 30.0     # al terminar Python, cuánto se espera (s) como mucho a los trabajos que aún no han parado
_CODIGO = {"v": None}    # el código con el que Python iba a salir (sys.exit)
_sys_exit = sys.exit


def _exit_con_codigo(code=None):
    _CODIGO["v"] = code
    _sys_exit(code)


sys.exit = _exit_con_codigo


def _codigo_salida() -> int:
    """Como Python: sys.exit() / sys.exit(None) = 0; un número = ese número; un texto = 1."""
    c = _CODIGO["v"]
    if c is None:
        return 0
    return c if isinstance(c, int) else 1


# Las tareas de salida que registra el programa (atexit) desde aquí en adelante: si hay que salir sin pasar por el
# cierre de Qt (ver salir_sin_romper), se hacen igual. (Las de PySide no: son las que se rompen con un hilo vivo.)
_TAREAS_SALIDA: list = []
_atexit_register = __import__("atexit").register


def _registrar_salida(fn, *a, **k):
    _TAREAS_SALIDA.append((fn, a, k))
    return _atexit_register(fn, *a, **k)


_atexit_unregister = __import__("atexit").unregister


def _quitar_salida(fn):
    _TAREAS_SALIDA[:] = [x for x in _TAREAS_SALIDA if x[0] != fn]
    return _atexit_unregister(fn)


__import__("atexit").register = _registrar_salida
__import__("atexit").unregister = _quitar_salida


def _hacer_tareas_salida():
    """Lo importante al salir: lo registrado con atexit (menos esto mismo), lo pendiente de image_feedback y los
    ajustes al disco."""
    hechas = set()
    for fn, a, k in reversed(list(_TAREAS_SALIDA)):
        if fn is _al_salir:
            continue
        try:
            fn(*a, **k)
            hechas.add(fn)
        except Exception:  # noqa: BLE001
            pass
    mod = sys.modules.get("editoria.ai.image_feedback")
    if mod is not None and getattr(mod, "flush", None) not in hechas:
        try:
            mod.flush()
        except Exception:  # noqa: BLE001
            pass
    try:
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").sync()
    except Exception:  # noqa: BLE001
        pass


def _soltar(jobs: list):
    """Trabajos que no paran: una referencia que nunca se suelta (nadie destruirá su objeto de Qt a medias). Su hilo
    NO se congela: si estaba ejecutando Python podría quedarse congelado con el GIL y colgar la salida."""
    import ctypes
    for j in jobs:
        try:
            ctypes.pythonapi.Py_IncRef(ctypes.py_object(j))
        except Exception:  # noqa: BLE001
            pass


VIGILANTE_S = 3.0        # si las tareas de salida tardan más, se sale igual (nunca se queda colgado)


def _vigilante(code: int):
    """Dos vigilantes: un hilo que sale a los VIGILANTE_S segundos y, por si ni ese pudiera correr, un temporizador de
    Windows (sin Python ni GIL) que llama a ExitProcess un poco después."""
    import os
    import threading

    def fuera():
        time.sleep(VIGILANTE_S)
        os._exit(code)
    threading.Thread(target=fuera, daemon=True).start()
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetProcAddress.restype = ctypes.c_void_p
        k32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        salir = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"ExitProcess")
        timer = wintypes.HANDLE()
        k32.CreateTimerQueueTimer.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.HANDLE, ctypes.c_void_p,
                                              ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.ULONG]
        # la función del temporizador recibe (parámetro, …): ExitProcess(parámetro) = salir con ese código
        k32.CreateTimerQueueTimer(ctypes.byref(timer), None, salir, ctypes.c_void_p(int(code) & 0xFFFFFFFF or None),
                                  int((VIGILANTE_S + 2.0) * 1000), 0, 0x00000008)     # WT_EXECUTEONLYONCE
        _VIGILANTES.append(timer)
    except Exception:  # noqa: BLE001
        pass


_VIGILANTES: list = []


def salir_sin_romper(code: int):
    """Salir YA con un trabajo de Qt aún vivo: primero lo importante (tareas de salida, ajustes, lo pendiente) y luego
    fuera, sin pasar por el cierre de Qt/C, que con un hilo vivo acababa con el proceso de golpe (127 / 0xC0000409).
    Con vigilante: si lo importante tarda más de VIGILANTE_S segundos, se sale igual."""
    import os
    code = int(code or 0)
    _soltar(live_jobs())
    _vigilante(code)
    _hacer_tareas_salida()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(code)


def _al_salir():
    """Al terminar Python (el programa o una prueba) con un trabajo aún en marcha —p. ej. «🎯 Afinar palabras» cargando
    su modelo, que no se puede interrumpir—: se le pide parar y se le ESPERA (cargar el modelo acaba en unos segundos y
    entonces ve que debe parar). Si aun así sigue pasado SALIDA_ESPERA: salir_sin_romper con el código de siempre."""
    vivos = live_jobs()
    if not vivos:
        return
    for j in vivos:
        try:
            j.cancel()
        except RuntimeError:
            pass
    fin = time.monotonic() + SALIDA_ESPERA
    for j in vivos:
        try:
            j.wait(max(0, int((fin - time.monotonic()) * 1000)))
        except RuntimeError:
            pass
    if live_jobs():
        salir_sin_romper(_codigo_salida())


_atexit_register(_al_salir)


class BackgroundJob(QThread):
    progress = Signal(float, str)
    partial = Signal(object)   # resultados parciales (p. ej. cada clip analizado)
    done = Signal(object)
    failed = Signal(str)

    on_start = None     # aviso al panel de tareas (se pone en ui/task_window.py)

    def __init__(self, fn, parent=None, with_partial: bool = False):
        """fn(progress, cancelled) -> resultado   (o fn(progress, cancelled, partial) si with_partial)
        parent: la ventana a la que pertenece. NO es su «padre» de Qt (si la ventana se cierra, el hilo no se
        destruye a medias): se le pide parar y ya no avisa a nadie; termina solo, sin cierre inesperado."""
        super().__init__(None)
        self._orphaned = False
        if parent is not None:
            try:
                parent.destroyed.connect(self._orphan)
            except (AttributeError, RuntimeError):
                pass
        self.finished.connect(self._release, Qt.QueuedConnection)
        self._fn = fn
        self._with_partial = with_partial
        self._cancel = False
        self._mark = time.monotonic()
        self.title = ""

    def _orphan(self, *_a):
        """Su ventana se cerró: que pare y que no avise a nadie (sus avisos irían a algo ya borrado)."""
        self._orphaned = True
        self._cancel = True

    def _release(self):
        QTimer.singleShot(0, lambda j=self: _LIVE.discard(j))

    def _emit(self, sig, *args):
        if not self._orphaned:
            sig.emit(*args)

    def start(self, *args):
        lvl = resource_level()
        _LIVE.add(self)
        super().start(*args)
        if lvl != "full":
            self.setPriority(QThread.LowPriority if lvl == "half" else QThread.LowestPriority)
        if BackgroundJob.on_start is not None:
            try:
                BackgroundJob.on_start(self)
            except Exception:  # noqa: BLE001 - el panel de tareas nunca debe romper un trabajo
                pass

    def _rest(self):
        """«Media» / «Un cuarto»: el trabajo descansa entre paso y paso para no quitarle potencia al editor."""
        k = REST.get(resource_level(), 0.0)
        now = time.monotonic()
        worked = now - self._mark
        if k > 0 and worked > 0.02:
            end = now + min(2.0, worked * k)
            while not self._cancel and time.monotonic() < end:
                time.sleep(0.02)
        self._mark = time.monotonic()

    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        if not self._cancel:
            self._rest()
        return self._cancel

    def run(self):
        try:
            def prog(f, t):
                self._rest()
                self._emit(self.progress, float(f), t)
            if self._with_partial:
                result = self._fn(prog, self.is_cancelled, lambda x: self._emit(self.partial, x))
            else:
                result = self._fn(prog, self.is_cancelled)
        except Cancelled:
            self._emit(self.failed, "Cancelado.")
        except Exception as exc:  # noqa: BLE001 - se informa al usuario y se registra
            try:
                with open(log_path(), "a", encoding="utf-8") as f:
                    f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} (tarea) ===\n{traceback.format_exc()}")
            except OSError:
                pass
            self._emit(self.failed, str(exc) or exc.__class__.__name__)
        else:
            self._emit(self.done, result)
