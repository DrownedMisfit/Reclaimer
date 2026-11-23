"""
◈ COLA ÚNICA DE ANÁLISIS: los análisis en segundo plano pasan por aquí, en orden de prioridad.

  · Prioridades: ALTA = lo que estás usando ahora · MEDIA = lo recién importado o descargado · BAJA = cuando el PC está
    libre (nadie ha tocado el teclado ni el ratón en el último minuto).
  · Pocos trabajos pesados a la vez (uno por cada 8 núcleos, hasta 3) y los de la tarjeta gráfica de uno en uno.
  · 🔋 Portátil sin enchufar (core/energia.py): lo de prioridad MEDIA espera como lo de BAJA (a que el PC esté libre),
    de uno en uno y con prioridad mínima; lo que esperas tú (ALTA) sigue igual.
  · Pausa sola mientras reproduces o exportas (lo de prioridad ALTA sigue: lo estás esperando tú). Si llega algo más
    urgente y no hay hueco, el menos urgente se pausa (no se pierde lo hecho) y sigue después.
  · Cancelable (uno o todos) y nunca bloquea la interfaz: cada trabajo va en su BackgroundJob (hilo aparte; se ve en
    «◈ Tareas de la IA» y stop_all lo detiene al cerrar). Los automáticos van con prioridad baja del sistema.
  · Estado consultable (para un indicador único y la lista de «cuánto tardó cada análisis»): cola().estado().

  cola() -> la cola (una para todo el programa)
  cola().poner(fn, titulo, prioridad, clave, pesado, gpu, maneja_pausa, archivo, al_terminar, al_fallar) -> Trabajo
      fn(progress, control) -> resultado. control() = ¿cancelado? (si el trabajo NO maneja la pausa, control() espera
      mientras dure); control.pausado() = ¿en pausa? (para los que se pausan solos, como la lectura única)
  cola().subir(clave, prioridad) · cancelar(trabajo o clave) · cancelar_todo() · pausar(motivo, sí/no) · cerrar()
  analizar_archivo(path, duración, prioridad, quiero) -> Trabajo (la lectura única de ai/lectura_unica.py)
  AlImportar(ctrl): empieza a analizar lo que importas o descargas (prioridad MEDIA). Abrir un proyecto no analiza nada.
  pausa_automatica() -> ¿reproduciendo o exportando? (el scrub de las miniaturas, ui/miniaturas.py, se apaga)
"""
from __future__ import annotations

import itertools
import os
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal

ALTA, MEDIA, BAJA = 0, 1, 2
NOMBRE_PRIORIDAD = {ALTA: "alta", MEDIA: "media", BAJA: "baja"}
LIBRE_S = 60.0           # el PC está «libre» si nadie lo toca en este tiempo
_ids = itertools.count(1)


def _segundos_sin_usar() -> float:
    """Desde cuándo nadie toca el teclado ni el ratón (en todo Windows)."""
    try:
        import ctypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = _LII()
        lii.cbSize = ctypes.sizeof(_LII)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:  # noqa: BLE001
        pass
    return 0.0


EDITANDO_S = 2.0         # «estás editando»: tocaste el teclado o el ratón en Reclaimer en los últimos 2 s


def _reclaimer_delante() -> bool:
    """¿La ventana activa de Windows es de Reclaimer (este proceso)?"""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:  # noqa: BLE001
        return False


def _usuario_editando() -> bool:
    """Estás usando Reclaimer ahora mismo (arrastrar, escribir, mover la línea de tiempo…): lo automático espera."""
    return _segundos_sin_usar() < EDITANDO_S and _reclaimer_delante()


class Trabajo:
    def __init__(self, fn, titulo: str, prioridad: int, clave, pesado: bool, gpu: bool, maneja_pausa: bool,
                 archivo: str):
        self.id = next(_ids)
        self.fn, self.titulo, self.prioridad, self.clave = fn, titulo, prioridad, clave
        self.pesado, self.gpu, self.maneja_pausa = pesado, gpu, maneja_pausa
        self.archivo = os.path.normcase(os.path.abspath(archivo)) if archivo else ""
        self.estado = "en cola"          # en cola · en marcha · en pausa · hecho · cancelado · falló
        self.progreso, self.texto, self.error = 0.0, "", ""
        self.t_cola = time.monotonic()
        self.t_inicio = self.t_fin = None
        self.t_pausa = 0.0               # tiempo en pausa (no cuenta en «cuánto tardó»)
        self._pausa_desde = None
        self.motivo_pausa = ""
        self.resultado = None
        self.informe = None              # p. ej. el de la lectura única: tiempo de la pasada y de cada análisis
        self.job = None
        self._cancel = False
        self._pausa = False
        self.al_terminar = self.al_fallar = None

    def duracion(self) -> float | None:
        """Lo que lleva (o lo que tardó) trabajando, sin las pausas."""
        if self.t_inicio is None:
            return None
        fin = self.t_fin if self.t_fin is not None else time.monotonic()
        pausa = self.t_pausa + ((time.monotonic() - self._pausa_desde) if self._pausa_desde is not None else 0.0)
        return max(0.0, fin - self.t_inicio - pausa)

    def a_dict(self) -> dict:
        d = {"id": self.id, "titulo": self.titulo, "prioridad": NOMBRE_PRIORIDAD.get(self.prioridad, "?"),
             "estado": self.estado, "progreso": round(self.progreso, 3), "texto": self.texto,
             "segundos": None if self.duracion() is None else round(self.duracion(), 2),
             "espera": round((self.t_inicio or time.monotonic()) - self.t_cola, 2), "archivo": self.archivo}
        if self.motivo_pausa and self.estado == "en pausa":
            d["motivo_pausa"] = self.motivo_pausa
        if self.error:
            d["error"] = self.error
        if self.informe:
            d["analisis"] = dict(self.informe.get("analisis", {}))
            d["pasada"] = self.informe.get("pasada")
        return d


class _Control:
    """Lo que recibe el trabajo: control() = ¿cancelado?; control.pausado() = ¿en pausa?"""

    def __init__(self, trabajo: Trabajo, job):
        self.t, self.job = trabajo, job

    def _cancelado(self) -> bool:
        return self.t._cancel or bool(getattr(self.job, "_cancel", False))

    def __call__(self) -> bool:
        if self._cancelado() or self.job.is_cancelled():
            return True
        if not self.t.maneja_pausa:
            while self.t._pausa and not self._cancelado():
                time.sleep(0.05)
        return self._cancelado()

    def baja(self) -> bool:
        """¿Va en prioridad baja? (lo automático; lo que esperas tú —ALTA— va en prioridad normal)."""
        return self.t.prioridad != ALTA

    def pausado(self) -> bool:
        if self._cancelado():
            return False
        if self.t._pausa:
            return True
        # «◈ Tareas de la IA → Media / Un cuarto»: también la lectura del video descansa (FFmpeg congelado a ratos)
        from .jobs import REST, resource_level
        k = REST.get(resource_level(), 0.0)
        return k > 0 and (time.monotonic() % (1.0 + k)) >= 1.0


class ColaAnalisis(QObject):
    cambiado = Signal()
    terminado = Signal(object)          # Trabajo
    _pide_subir = Signal(str)           # (desde otro hilo) alguien espera a la lectura de ese archivo

    def __init__(self):
        super().__init__()
        self._trabajos: list[Trabajo] = []        # en cola, en marcha o en pausa
        self._hechos: list[Trabajo] = []          # los últimos terminados (con cuánto tardaron)
        self._motivos: set[str] = set()           # «reproducción», «exportación»…
        self._cerrada = False
        self.max_pesados = max(1, min(3, (os.cpu_count() or 4) // 8))
        self._bateria = False                     # 🔋 (se mira en cada revisión: core/energia.py)
        self.max_gpu = 1
        self._timer = QTimer(self)
        self._timer.setInterval(500)               # (¿el PC sigue libre? ¿estás editando?)
        self._timer.timeout.connect(self._revisar)
        self._pide_subir.connect(self._subir_archivo)
        try:
            from ..ai import lectura_unica
            lectura_unica.al_esperar = lambda path: self._pide_subir.emit(os.path.normcase(os.path.abspath(path)))
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- poner y quitar
    def poner(self, fn, titulo: str, prioridad: int = MEDIA, clave=None, pesado: bool = True, gpu: bool = False,
              maneja_pausa: bool = False, archivo: str = "", al_terminar=None, al_fallar=None) -> Trabajo | None:
        if self._cerrada:
            return None
        if clave is not None:
            for t in self._trabajos:
                if t.clave == clave:          # ya está: como mucho, se le sube la prioridad
                    if prioridad < t.prioridad:
                        t.prioridad = prioridad
                        self._revisar()
                    return t
        t = Trabajo(fn, titulo, prioridad, clave, pesado, gpu, maneja_pausa, archivo)
        t.al_terminar, t.al_fallar = al_terminar, al_fallar
        self._trabajos.append(t)
        self._revisar()
        return t

    def buscar(self, clave) -> Trabajo | None:
        return next((t for t in self._trabajos if t.clave == clave), None)

    def subir(self, clave_o_trabajo, prioridad: int = ALTA):
        t = clave_o_trabajo if isinstance(clave_o_trabajo, Trabajo) else self.buscar(clave_o_trabajo)
        if t is not None and prioridad < t.prioridad:
            t.prioridad = prioridad
            self._revisar()

    def _subir_archivo(self, archivo: str):
        for t in list(self._trabajos):      # (solo el que lo está leyendo: no lo que espera en la cola)
            if t.archivo and t.archivo == archivo and t.estado in ("en marcha", "en pausa"):
                self.subir(t, ALTA)

    def buscar_archivo(self, path: str) -> list:
        k = os.path.normcase(os.path.abspath(path))
        return [t for t in self._trabajos if t.archivo == k]

    def cancelar(self, clave_o_trabajo):
        t = clave_o_trabajo if isinstance(clave_o_trabajo, Trabajo) else self.buscar(clave_o_trabajo)
        if t is None:
            return
        t._cancel = True
        if t.job is not None:
            try:
                t.job.cancel()
            except RuntimeError:
                pass
        elif t in self._trabajos:             # aún no había empezado: fuera de la cola
            self._trabajos.remove(t)
            self._acabar(t, "cancelado")
        self._revisar()

    def cancelar_todo(self):
        for t in list(self._trabajos):
            self.cancelar(t)

    def cerrar(self):
        """Al cerrar Reclaimer: no empieza nada más y se cancela lo que hay."""
        self._cerrada = True
        self._timer.stop()
        self.cancelar_todo()

    def pausar(self, motivo: str, si: bool):
        """Pausa los trabajos de prioridad MEDIA y BAJA mientras haya algún motivo (p. ej. «reproducción»)."""
        cambia = (motivo in self._motivos) != bool(si)
        if si:
            self._motivos.add(motivo)
        else:
            self._motivos.discard(motivo)
        if cambia:
            self._revisar()

    # ---------------------------------------------------------------- estado
    def estado(self) -> dict:
        vivos = sorted(self._trabajos, key=lambda t: (t.prioridad, t.id))
        return {"en_marcha": [t.a_dict() for t in vivos if t.estado == "en marcha"],
                "en_pausa": [t.a_dict() for t in vivos if t.estado == "en pausa"],
                "en_cola": [t.a_dict() for t in vivos if t.estado == "en cola"],
                "hechos": [t.a_dict() for t in self._hechos[-30:]],
                "pausa_por": sorted(self._motivos), "max_pesados": self.max_pesados}

    def tiempos(self) -> list[tuple[str, float, dict]]:
        """[(trabajo, segundos, {análisis: segundos})] de los terminados: «cuánto tardó cada análisis»."""
        return [(t.titulo, round(t.duracion() or 0.0, 2), dict((t.informe or {}).get("analisis", {})))
                for t in self._hechos if t.estado == "hecho"]

    def ocupada(self) -> bool:
        return bool(self._trabajos)

    # ---------------------------------------------------------------- el reparto
    def _efectiva(self, t: Trabajo) -> int:
        """🔋 Con la batería, lo automático (MEDIA) cuenta como BAJA: espera a que el PC esté libre."""
        return BAJA if t.prioridad == MEDIA and self._bateria else t.prioridad

    def _revisar(self):
        vivos = sorted(self._trabajos, key=lambda t: (t.prioridad, t.id))
        if not vivos:
            self._timer.stop()
            self.cambiado.emit()
            return
        if not self._timer.isActive() and not self._cerrada:
            self._timer.start()
        try:
            from ..core import energia
            self._bateria = energia.en_bateria()
        except Exception:  # noqa: BLE001
            self._bateria = False
        max_pesados = 1 if self._bateria else self.max_pesados
        urgentes = any(self._efectiva(t) < BAJA for t in vivos)
        editando = any(t.prioridad != ALTA for t in vivos) and _usuario_editando()
        libre = None
        pesados = gpu = 0
        for t in vivos:
            if t._cancel:
                continue
            motivo = ""
            if self._cerrada:
                motivo = "cerrando"
            elif self._motivos and t.prioridad != ALTA:
                motivo = " y ".join(sorted(self._motivos))
            elif editando and t.prioridad != ALTA:
                motivo = "estás editando"
            elif self._efectiva(t) == BAJA:
                if urgentes:
                    motivo = "hay algo más urgente"
                else:
                    if libre is None:
                        libre = _segundos_sin_usar() >= LIBRE_S
                    if not libre:
                        motivo = ("🔋 con la batería: esperando a que el PC esté libre"
                                  if self._bateria and t.prioridad == MEDIA else "esperando a que el PC esté libre")
            if not motivo and t.pesado and pesados >= max_pesados:
                motivo = "🔋 con la batería, de uno en uno" if self._bateria else "hay algo más urgente"
            if not motivo and t.gpu and gpu >= self.max_gpu:
                motivo = "la tarjeta gráfica está ocupada"
            if motivo:
                if t.estado == "en marcha":
                    self._poner_pausa(t, motivo)
                elif t.estado == "en pausa":
                    t.motivo_pausa = motivo
                continue
            pesados += t.pesado
            gpu += t.gpu
            if t.estado == "en cola" and not self._cerrada:
                self._arrancar(t)
            elif t.estado == "en pausa":
                self._quitar_pausa(t)
            elif t.job is not None:
                self._prioridad_hilo(t)
        self.cambiado.emit()

    def _prioridad_hilo(self, t: Trabajo):
        try:
            if t.job is not None and t.job.isRunning():
                pri = self._efectiva(t)
                t.job.setPriority(QThread.NormalPriority if pri == ALTA else
                                  QThread.LowPriority if pri == MEDIA else QThread.LowestPriority)
        except RuntimeError:
            pass

    def _poner_pausa(self, t: Trabajo, motivo: str):
        t._pausa = True
        t.estado = "en pausa"
        t.motivo_pausa = motivo
        t._pausa_desde = time.monotonic()
        if t.job is not None:
            try:
                t.job.progress.emit(t.progreso, f"⏸ {t.titulo} — en pausa ({motivo})")
            except RuntimeError:
                pass

    def _quitar_pausa(self, t: Trabajo):
        if t._pausa_desde is not None:
            t.t_pausa += time.monotonic() - t._pausa_desde
            t._pausa_desde = None
        t._pausa = False
        t.estado = "en marcha"
        t.motivo_pausa = ""
        self._prioridad_hilo(t)
        if t.job is not None:
            try:
                t.job.progress.emit(t.progreso, t.texto or t.titulo)
            except RuntimeError:
                pass

    def _arrancar(self, t: Trabajo):
        from .jobs import BackgroundJob
        holder = {}

        def work(progress, _cancelled):
            return t.fn(progress, _Control(t, holder["job"]))
        job = BackgroundJob(work)
        holder["job"] = job
        job.title = t.titulo
        t.job = job
        t.estado = "en marcha"
        t.t_inicio = time.monotonic()

        def prog(f, texto):
            t.progreso = max(0.0, min(1.0, float(f)))
            if texto and not texto.startswith("⏸"):
                t.texto = texto
            self.cambiado.emit()

        def done(res):
            t.resultado = res
            if isinstance(res, dict) and "analisis" in res:
                t.informe = res
            self._fin(t, "hecho")

        def failed(msg):
            t.error = msg
            self._fin(t, "cancelado" if t._cancel or "ancelad" in msg else "falló")
        job.progress.connect(prog)
        job.done.connect(done)
        job.failed.connect(failed)
        job.start()
        self._prioridad_hilo(t)
        try:
            job.progress.emit(0.0, t.titulo)
        except RuntimeError:
            pass

    def _fin(self, t: Trabajo, como: str):
        if t in self._trabajos:
            self._trabajos.remove(t)
        self._acabar(t, como)
        QTimer.singleShot(0, self._revisar)

    def _acabar(self, t: Trabajo, como: str):
        if t._pausa_desde is not None:
            t.t_pausa += time.monotonic() - t._pausa_desde
            t._pausa_desde = None
        t.estado = como
        t.t_fin = time.monotonic()
        t._pausa = False
        self._hechos.append(t)
        del self._hechos[:-100]
        cb = t.al_terminar if como == "hecho" else t.al_fallar
        if cb is not None:
            try:
                cb(t.resultado if como == "hecho" else (t.error or como))
            except Exception:  # noqa: BLE001 - un aviso que falla no rompe la cola
                pass
        self.terminado.emit(t)
        self.cambiado.emit()


_COLA: list[ColaAnalisis] = []


def cola() -> ColaAnalisis:
    if not _COLA:
        _COLA.append(ColaAnalisis())
        for motivo, n in _AVISOS.items():        # (lo que ya pasaba antes de crearla: reproduciendo, exportando…)
            if n > 0:
                _COLA[0].pausar(motivo, True)
    return _COLA[0]


# ------------------------------------------------------------------ avisos: reproducir y exportar pausan la cola
_AVISOS: dict[str, int] = {}
_EXPORTACIONES: list = []


_SONANDO: set = set()     # qué motores están reproduciendo (con dos, parar uno no quita la pausa)


def aviso(motivo: str, si: bool):
    """exportación (u otro motivo con contador) empieza (si=True) o acaba. No crea la cola si aún no existe."""
    n = max(0, _AVISOS.get(motivo, 0) + (1 if si else -1))
    _AVISOS[motivo] = n
    if _COLA:
        _COLA[0].pausar(motivo, n > 0)


def al_reproducir(si: bool, quien=None):
    """quien: el motor que reproduce o para (None = uno solo, el de siempre)."""
    k = "motor" if quien is None else quien
    if si:
        _SONANDO.add(k)
    else:
        _SONANDO.discard(k)
    _AVISOS["reproducción"] = len(_SONANDO)
    if _COLA:
        _COLA[0].pausar("reproducción", bool(_SONANDO))


def exportacion_empieza(proc):
    """Una exportación en marcha (QProcess de FFmpeg o exportación por trozos): la cola espera a que acabe."""
    if any(p is proc for p in _EXPORTACIONES):
        return
    _EXPORTACIONES.append(proc)
    aviso("exportación", True)

    def acaba(*_a, pr=proc):
        if any(p is pr for p in _EXPORTACIONES):
            _EXPORTACIONES[:] = [p for p in _EXPORTACIONES if p is not pr]
            aviso("exportación", False)
    try:
        proc.finished.connect(acaba)
    except (AttributeError, RuntimeError, TypeError):
        acaba()
        return
    try:      # (un QProcess que ni arranca no avisa con «finished»)
        proc.errorOccurred.connect(lambda err, a=acaba: a() if int(getattr(err, "value", err)) == 0 else None)
    except (AttributeError, RuntimeError, TypeError):
        pass


def existe() -> bool:
    return bool(_COLA)


def pausa_automatica() -> bool:
    """¿Se está reproduciendo o exportando? (lo de la interfaz que gasta CPU —el scrub de las miniaturas— espera)."""
    return _AVISOS.get("reproducción", 0) > 0 or _AVISOS.get("exportación", 0) > 0


def _soltar_cola(claves) -> list[str]:
    """🔓 (core/soltar_archivos) Lo que lee esos archivos (o lo de dentro de esas carpetas) se cancela: un análisis en
    marcha, o en pausa, tiene el archivo abierto con FFmpeg. Espera corta (≤ 1 s) a que acabe. Devuelve los archivos
    que estaba leyendo (para esperar a que Windows los dé por libres)."""
    if not _COLA:
        return []
    from ..core.live_video import _toca
    c = _COLA[0]
    ts = [t for t in list(c._trabajos) if t.archivo and _toca(t.archivo, claves)]
    leyendo = [t.archivo for t in ts if t.job is not None]
    for t in ts:
        c.cancelar(t)
    fin = time.monotonic() + 1.0
    for t in ts:
        if t.job is None:
            continue
        try:
            t.job.wait(max(0, int((fin - time.monotonic()) * 1000)))
        except (RuntimeError, TypeError):
            pass
    return leyendo


def _apuntar_soltador():
    from ..core import soltar_archivos as _SA
    _SA.registrar(_soltar_cola)


_apuntar_soltador()


def cerrar_cola():
    if _COLA:
        _COLA[0].cerrar()


# ------------------------------------------------------------------ la lectura única, por la cola
def analizar_al_importar() -> bool:
    """«◈ Tareas de la IA → Analizar lo que importo» (sí por defecto)."""
    from PySide6.QtCore import QSettings
    return str(QSettings("EditorIA", "EditorIA").value("ia/analizar_al_importar", "true")).lower() == "true"


def set_analizar_al_importar(si: bool):
    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").setValue("ia/analizar_al_importar", "true" if si else "false")


def quiero_al_importar() -> list[str]:
    """Lo que se prepara al importar (prioridad MEDIA): lo barato y las huellas CLIP de los 12 momentos. En modo
    ligero (equipo modesto), solo lo barato: sin CLIP ni caras."""
    from ..ai import lectura_unica as LU
    q = ["movimiento", "siluetas", "escenas", "negros", "barras", "pistas", "tira"]
    if not LU._modesto():
        q += ["miniatura", "clip"]
    return [n for n in q if LU.disponible(n)]


def quiero_con_pc_libre() -> list[str]:
    """Lo caro (CLIP de cada segundo: «entender a fondo»), en prioridad BAJA: solo con el PC libre. Nunca en modo
    ligero."""
    from ..ai import lectura_unica as LU
    return [] if LU._modesto() or not LU.disponible("a_fondo") else ["a_fondo"]


def analizar_archivo(path: str, duration: float, prioridad: int = MEDIA, quiero=None,
                     titulo: str = "") -> Trabajo | None:
    """Pone en la cola la lectura única de un video (lo que falte de «quiero»; None = quiero_al_importar())."""
    from ..ai import lectura_unica as LU
    q = list(quiero) if quiero is not None else quiero_al_importar()
    if not q or not LU.falta(path, duration, q):
        return None

    def fn(progress, control):
        return LU.asegurar(path, duration, q, extras=[], progress=progress, cancelled=control,
                           pausado=control.pausado, baja=control.baja)
    clave = ("lectura", os.path.normcase(os.path.abspath(path)), tuple(q))
    return cola().poner(fn, titulo or f"⚡ Analizando «{os.path.basename(path)}»", prioridad,
                        clave=clave, pesado=True, maneja_pausa=True, archivo=path)


# ------------------------------------------------------------------ empezar al importar
class AlImportar(QObject):
    """Lo que importas o descargas empieza a analizarse enseguida (prioridad MEDIA, en la cola única), en vez de
    esperar a que lo pidas. Lo que ya estaba al abrir el proyecto NO se analiza (el usuario: «solo entro a subtitular y
    pierdo rendimiento»). Ajuste «ia/analizar_al_importar» (sí por defecto). En las pruebas, apagado salvo que se pida
    (RECLAIMER_ANALIZAR_AL_IMPORTAR=1)."""

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self._conocidos: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._revisar)
        self._reset()
        ctrl.project_replaced.connect(self._reset)
        ctrl.media_changed.connect(self._timer.start)

    def activo(self) -> bool:
        if os.environ.get("EDITORIA_DATOS") and os.environ.get("RECLAIMER_ANALIZAR_AL_IMPORTAR") != "1":
            return False
        return analizar_al_importar()

    def _reset(self):
        try:
            self._conocidos = set(self.ctrl.project.media)
        except Exception:  # noqa: BLE001
            self._conocidos = set()

    def _revisar(self):
        from ..core.model import KIND_VIDEO
        try:
            p = self.ctrl.project
            missing = getattr(self.ctrl, "missing", set())
            nuevos = [m for mid, m in p.media.items() if mid not in self._conocidos]
        except Exception:  # noqa: BLE001
            return
        on = self.activo()
        for m in nuevos:
            if m.kind == KIND_VIDEO and not (getattr(m, "probed", True) and m.duration):
                continue        # (aún sin medir: se mira en el siguiente aviso)
            self._conocidos.add(m.id)
            if not on or m.kind != KIND_VIDEO or m.id in missing or not os.path.isfile(m.path):
                continue
            try:
                analizar_archivo(m.path, float(m.duration), MEDIA)
                lento = quiero_con_pc_libre()
                if lento:
                    analizar_archivo(m.path, float(m.duration), BAJA, lento,
                                     f"⚡ Entendiendo a fondo «{os.path.basename(m.path)}» (con el PC libre)")
            except Exception:  # noqa: BLE001 - analizar antes es una ayuda: nunca rompe la importación
                pass
