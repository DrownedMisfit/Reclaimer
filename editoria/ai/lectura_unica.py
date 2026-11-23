"""
⚡ LECTURA ÚNICA: una sola descodificación de cada video alimenta a TODOS sus análisis.

Antes, cada análisis abría y descodificaba el mismo video por su cuenta (movimiento, siluetas, escenas, negros, barras,
pistas, huellas CLIP, miniatura, tira…): unas 7 veces por archivo. Descodificar es lo que más cuesta (un 1080p AV1 de
3 min: ~45 s de procesador cada vez). Ahora FFmpeg lo descodifica UNA vez y reparte cada fotograma:

  · un grafo con «split»: una rama por análisis, cada una a su ritmo y tamaño (el MISMO filtro que usaba cada análisis
    por su cuenta), hacia tuberías con nombre de Windows (sin archivos temporales grandes);
  · escenas y negros (miran TODOS los fotogramas) en grafos aparte: FFmpeg los ejecuta en paralelo;
  · las barras negras (8 tramos de 2 s) y los 12 momentos de las pistas/CLIP salen de la misma lectura (trim/select).

Cada análisis guarda su resultado en SU caché de siempre (mismo archivo, mismo formato, mismo cálculo: las clases
Accumulator de cada módulo): quien lo pida después lo encuentra hecho. Nada pesado nuevo en disco (la miniatura guarda
unas decenas de KB por hora de video).

  usar(path, duración, análisis)  -> ¿conviene la lectura única para ese análisis? (si no, cada uno lee como siempre)
  asegurar(path, duración, necesarios, extras=None, progress, cancelled, pausado, baja) -> informe de tiempos
  asegurar_o_seguir(...)          igual, pero si algo falla no se queja: quien llama sigue con su lectura de siempre
  falta(path, duración, análisis) -> los que aún no están hechos
  al_esperar                      la cola de análisis (ui/cola_analisis.py) pone aquí a quién avisar cuando alguien
                                  espera a un archivo que se está leyendo (para subirle la prioridad)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from .base import Cancelled, check_cancel, report

LARGO = 10 * 60          # a partir de aquí (s), movimiento y tira solo miran fotogramas clave (como hasta ahora)
TODOS = ("movimiento", "siluetas", "escenas", "negros", "barras", "pistas", "clip", "a_fondo", "miniatura", "tira",
         "huella")
SOLO_CORTOS = ("barras", "pistas", "clip")   # miran unos pocos momentos: no merece leer el video entero solo por ellos
DE_CLAVES = ("movimiento", "tira")           # en videos largos solo usan los fotogramas clave
ACTIVA = True            # (las pruebas la apagan para comparar con la lectura de siempre)
al_esperar = None        # fn(path): alguien espera a que termine la lectura de ese archivo

_NOMBRE = {"movimiento": "movimiento", "siluetas": "siluetas", "escenas": "escenas", "negros": "imágenes negras",
           "barras": "barras negras", "pistas": "pistas de tipo", "clip": "huellas de los clips",
           "a_fondo": "entender a fondo", "miniatura": "fotogramas para la miniatura",
           "tira": "tira de la línea de tiempo", "huella": "huella visual por plano"}


# ------------------------------------------------------------------ qué se puede y qué falta
def _clip_listo() -> bool:
    try:
        from . import embeddings
        return embeddings.is_available()[0] and embeddings.is_downloaded("clip_image")
    except Exception:  # noqa: BLE001
        return False


def _caras_listo() -> bool:
    try:
        from .transcription import models_dir
        return (models_dir() / "caras" / "face_detection_yunet_2023mar.onnx").exists()
    except Exception:  # noqa: BLE001
        return False


def _modesto() -> bool:
    try:
        from ..core import hw
        return bool(hw.equipo()["modesto"])
    except Exception:  # noqa: BLE001
        return False


def disponible(nombre: str) -> bool:
    """¿Se puede hacer sin descargar nada? (las huellas CLIP y las caras necesitan su modelo ya descargado)."""
    if nombre in ("clip", "a_fondo"):
        return _clip_listo()
    if nombre == "miniatura":
        return _caras_listo()
    return nombre in TODOS


def usar(path: str, duration: float, nombre: str) -> bool:
    if not ACTIVA or os.environ.get("RECLAIMER_SIN_LECTURA_UNICA"):
        return False
    if nombre not in TODOS or not os.path.isfile(path) or not disponible(nombre):
        return False
    # Los que miran unos pocos momentos (barras, pistas, huellas de los clips) no provocan una lectura entera: por su
    # cuenta tardan poco (saltan a esos momentos). Se aprovechan cuando el video se lee igualmente (o al importarlo).
    return nombre not in SOLO_CORTOS


def hecho(nombre: str, path: str, duration: float) -> bool:
    try:
        if nombre == "movimiento":
            from .edit_maker import _profile_path
            return os.path.exists(_profile_path(path))
        if nombre == "siluetas":
            from .silhouette_id import _index_path
            return os.path.exists(_index_path(path))
        if nombre == "escenas":
            from ..core import scene_cuts
            return scene_cuts.whole_scores(path) is not None
        if nombre == "negros":
            from ..core import black_frames
            return black_frames.cached(path) is not None
        if nombre == "barras":
            from ..core import black_bars
            return black_bars.cached(path)[0]
        if nombre == "pistas":
            from .clip_analysis import _cues_path
            return _cues_path(path).exists()
        if nombre == "clip":
            from .clip_analysis import _cache_path
            return os.path.exists(_cache_path(path))
        if nombre == "a_fondo":
            from .library_understanding import _deep_path
            return os.path.exists(_deep_path(path))
        if nombre == "miniatura":
            from .thumb_frames import _scored_path
            return os.path.exists(_scored_path(path))
        if nombre == "tira":
            from ..ui.filmstrip import sprite_path
            p = sprite_path(path, duration)
            return os.path.exists(p) and os.path.getsize(p) > 0
        if nombre == "huella":
            from ..core import huella_plano
            return huella_plano.hecho(path)
    except Exception:  # noqa: BLE001
        return False
    return False


def falta(path: str, duration: float, nombres=TODOS) -> list[str]:
    return [n for n in nombres if n in TODOS and not hecho(n, path, duration)]


def extras_por_defecto() -> list[str]:
    """Lo que se aprovecha a calcular cuando ya se está leyendo el video (barato al lado de descodificar). Las huellas
    CLIP de cada segundo («entender a fondo») no: cuestan mucho procesador; solo si se piden."""
    out = ["movimiento", "siluetas", "escenas", "negros", "barras", "pistas", "tira", "huella"]
    if not _modesto():          # (modo ligero: sin caras ni CLIP)
        out += ["miniatura", "clip"]
    return [n for n in out if disponible(n)]


# ------------------------------------------------------------------ un archivo, una lectura a la vez
_cerrojos: dict[str, threading.Lock] = {}
_cerrojos_lock = threading.Lock()


def _cerrojo(path: str) -> threading.Lock:
    k = os.path.normcase(os.path.abspath(path))
    with _cerrojos_lock:
        return _cerrojos.setdefault(k, threading.Lock())


def asegurar(path: str, duration: float, necesarios, extras=None, progress=None, cancelled=None, pausado=None,
             baja=False) -> dict:
    """Hace (de una sola lectura) los análisis «necesarios» que falten y, de paso, los «extras» que falten
    (None = extras_por_defecto()). Si otro hilo ya está leyendo ese archivo, espera a que acabe (y avisa a
    al_esperar para que le suban la prioridad). baja: True o una función (¿va en prioridad baja ahora?).
    Devuelve {"pasada": s, "analisis": {nombre: s}, …} o {}."""
    lock = _cerrojo(path)
    if not lock.acquire(blocking=False):
        if al_esperar is not None:
            try:
                al_esperar(path)
            except Exception:  # noqa: BLE001
                pass
        while not lock.acquire(timeout=0.2):
            check_cancel(cancelled)
    try:
        if not duration:
            duration = float(media_tools.probe(path).get("duration") or 0.0)
        nec = [n for n in dict.fromkeys(necesarios) if n in TODOS and disponible(n) and not hecho(n, path, duration)]
        if necesarios and not nec:
            return {}
        ext = extras_por_defecto() if extras is None else list(extras)
        quiero = [n for n in dict.fromkeys(nec + ext) if n in TODOS and disponible(n) and not hecho(n, path, duration)]
        if "escenas" in quiero and "huella" not in quiero and not hecho("huella", path, duration):
            quiero.append("huella")     # 🧬 los planos van con su huella (casi gratis al lado de descodificar)
        claves = duration > LARGO and bool(nec) and all(n in DE_CLAVES for n in nec)
        if claves:              # ⚡ solo fotogramas clave (rápido): lo demás necesita leerlo entero
            quiero = [n for n in quiero if n in DE_CLAVES]
        if not quiero:
            return {}
        return _pasada(path, duration, quiero, claves, progress, cancelled, pausado, baja)
    finally:
        lock.release()


def asegurar_o_seguir(path: str, duration: float, necesarios, cancelled=None, progress=None,
                      extras=None) -> dict | None:
    """Como asegurar(), pero un fallo no para a nadie: se apunta en el registro y quien llama lee como siempre."""
    try:
        return asegurar(path, duration, necesarios, extras, progress, cancelled)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001
        _registrar()
        return None


def _registrar():
    import traceback
    try:
        from ..core.paths import log_path
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} (lectura única) ===\n{traceback.format_exc()}")
    except OSError:
        pass


# ------------------------------------------------------------------ las ramas (una por análisis)
class _Ctx:
    def __init__(self, path: str, duration: float, claves: bool, tmp: str):
        self.path, self.duration, self.claves, self.tmp = path, duration, claves, tmp
        self.largo = duration > LARGO
        self.fin = 0.0           # hasta dónde (s) hace falta leer como poco (las barras miran tramos sueltos)
        self.baja = False        # trabajo automático: FFmpeg y los lectores en prioridad baja
        self._n = 0

    def etiqueta(self, base: str) -> str:
        self._n += 1
        return f"{base}{self._n}"

    def archivo(self, nombre: str) -> str:
        return os.path.join(self.tmp, nombre)


def _esc(path: str) -> str:
    """Una ruta dentro de un filtro de FFmpeg (como en core/scene_cuts.py)."""
    return path.replace(chr(92), "/").replace(":", chr(92) + ":")


class _Salida:
    def __init__(self, etiqueta: str, tipo: str, w: int = 0, h: int = 0, fn=None, args=None):
        self.etiqueta, self.tipo, self.w, self.h, self.fn, self.args = etiqueta, tipo, w, h, fn, args or []
        self.frames = 0


class _Rama:
    nombres: tuple = ()
    propio = False           # True: su propio grafo (FFmpeg lo ejecuta en paralelo con los demás)

    def __init__(self, ctx: _Ctx):
        self.ctx = ctx
        self.salidas: list[_Salida] = []
        self.t = 0.0          # segundos de trabajo propio (sin contar la descodificación, que es de todos)
        self.error = ""

    def _raw(self, w: int, h: int, fn) -> str:
        lab = self.ctx.etiqueta("o")
        self.salidas.append(_Salida(lab, "raw", w, h, fn))
        return lab

    def _null(self) -> str:
        lab = self.ctx.etiqueta("o")
        self.salidas.append(_Salida(lab, "null"))
        return lab

    def esperados(self, fps: float) -> int:
        return int(self.ctx.duration * fps)

    def completo(self, ok: bool, salida: _Salida, fps: float) -> bool:
        """¿Se leyó entero? (si FFmpeg acabó mal, solo se guarda lo que llegó casi completo)."""
        return ok or salida.frames >= 0.9 * self.esperados(fps)

    def grafo(self, entrada: str) -> str:
        raise NotImplementedError

    def terminar(self, ok: bool):
        raise NotImplementedError


class _Movimiento(_Rama):
    nombres = ("movimiento",)

    def grafo(self, entrada):
        from .edit_maker import MotionAccumulator, PW, PH
        self.acc = MotionAccumulator()
        lab = self._raw(PW, PH, self.acc.add)
        return f"{entrada}{MotionAccumulator.FILTER},format=rgb24[{lab}]"

    def terminar(self, ok):
        from .edit_maker import STEP, save_profile
        if self.completo(ok, self.salidas[0], 1 / STEP):
            save_profile(self.ctx.path, self.acc.result(), self.ctx.largo)


class _Siluetas(_Rama):
    nombres = ("siluetas",)

    def grafo(self, entrada):
        from .silhouette_id import INDEX_FILTER, MAP_H, MAP_W, STEP, color_bins
        self.times, self.maps = [], []

        def add(buf):
            self.maps.append(color_bins(np.frombuffer(buf, np.uint8).reshape(MAP_H, MAP_W, 3)))
            self.times.append(round(len(self.times) * STEP, 2))
        lab = self._raw(MAP_W, MAP_H, add)
        return f"{entrada}{INDEX_FILTER},format=rgb24[{lab}]"

    def terminar(self, ok):
        from .silhouette_id import STEP, save_index
        if self.completo(ok, self.salidas[0], 1 / STEP):
            save_index(self.ctx.path, self.times, self.maps)


class _AFondo(_Rama):
    nombres = ("a_fondo",)

    def grafo(self, entrada):
        from . import embeddings
        from .library_understanding import CENTER_FILTER, FULL_FILTER, STEP, DeepAccumulator
        self.acc = DeepAccumulator(embeddings.get("clip_image"), max(1, int(self.ctx.duration / STEP)))

        def add(buf):
            a = np.frombuffer(buf, np.uint8).reshape(448, 224, 3)
            self.acc.add(a[:224], a[224:])
        lab = self._raw(224, 448, add)
        f, c, ff, fc = (self.ctx.etiqueta(x) for x in ("af", "ac", "aF", "aC"))
        return (f"{entrada}fps={1 / STEP:g},split[{f}][{c}];[{f}]{FULL_FILTER},format=rgb24[{ff}];"
                f"[{c}]{CENTER_FILTER},format=rgb24[{fc}];[{ff}][{fc}]vstack[{lab}]")

    def terminar(self, ok):
        from .library_understanding import STEP
        if self.completo(ok, self.salidas[0], 1 / STEP):
            self.acc.finish(self.ctx.path, "video", self.ctx.duration)


class _Momentos(_Rama):
    """Los 12 momentos repartidos por el clip: huellas CLIP («clip») y pistas de gameplay/cinemática («pistas»).
    select toma, para cada momento T, el primer fotograma con t ≥ T: lo mismo que «-ss T -frames:v 1»."""

    def __init__(self, ctx, quiero):
        super().__init__(ctx)
        self.nombres = tuple(n for n in ("clip", "pistas") if n in quiero)

    def grafo(self, entrada):
        from .clip_analysis import sample_times
        self.times = sample_times(self.ctx.duration)
        ts = [f"{max(0.0, t):.3f}" for t in self.times]
        expr = "+".join(f"gte(t,{T})*(lt(prev_t,{T})+isnan(prev_t))" for T in ts)
        self.f224, self.f192 = [], []
        outs = []
        if "clip" in self.nombres:
            from . import embeddings
            self.enc = embeddings.get("clip_image")
            outs.append((self._raw(224, 224, lambda b: self.f224.append(np.frombuffer(b, np.uint8).reshape(224, 224, 3))),
                         "scale=224:224:force_original_aspect_ratio=increase,crop=224:224,format=rgb24"))
        if "pistas" in self.nombres:
            from .shot_cues import H, W
            outs.append((self._raw(W, H, lambda b: self.f192.append(np.frombuffer(b, np.uint8).reshape(H, W, 3))),
                         f"scale={W}:{H},format=rgb24"))
        if len(outs) == 1:
            return f"{entrada}select='{expr}',{outs[0][1]}[{outs[0][0]}]"
        a, b = self.ctx.etiqueta("m"), self.ctx.etiqueta("m")
        return (f"{entrada}select='{expr}',split[{a}][{b}];[{a}]{outs[0][1]}[{outs[0][0]}];"
                f"[{b}]{outs[1][1]}[{outs[1][0]}]")

    def terminar(self, ok):
        if "clip" in self.nombres and len(self.f224) == len(self.times):
            from .clip_analysis import save_frames
            save_frames(self.ctx.path, self.times, np.stack(self.f224), self.enc)
        if "pistas" in self.nombres and len(self.f192) == len(self.times):
            from . import shot_cues
            from .clip_analysis import save_cues
            fr = np.stack(self.f192)
            save_cues(self.ctx.path, shot_cues.analyze(fr) if len(fr) >= 3 else {"type": None, "view": None})


class _Barras(_Rama):
    """cropdetect en 8 tramos de 2 s, como «-ss T -i video -t 2 -vf fps=4,cropdetect…» (trim + setpts hacen lo mismo
    que el -ss preciso de FFmpeg: los tiempos de cada tramo empiezan en 0)."""
    nombres = ("barras",)

    def grafo(self, entrada):
        from ..core import black_bars
        self.W, self.H = black_bars._probe_size(self.ctx.path)
        self.metas = []
        if self.W <= 0 or self.H <= 0:       # (sin tamaño: no hay nada que mirar; se guarda «sin barras»)
            return f"{entrada}trim=end_frame=1[{self._null()}]"
        times = [float(f"{t:.2f}") for t in black_bars.sample_times(self.ctx.duration)]
        labs = [self.ctx.etiqueta("b") for _ in times]
        vivo = self.ctx.etiqueta("b")
        # (+1 rama con salida: un grafo solo con nullsink no vale, y FFmpeg para cuando acaban sus salidas; esta deja
        # pasar un fotograma y sigue abierta hasta el final del último tramo)
        parts = [f"{entrada}split={len(times) + 1}" + "".join(f"[{x}]" for x in labs) + f"[{vivo}]",
                 f"[{vivo}]trim=end={max(times) + 4:g},select='eq(n,0)'[{self._null()}]"]
        self.ctx.fin = max(self.ctx.fin, max(times) + 3)
        for T, lab in zip(times, labs):
            meta = self.ctx.archivo(f"barras_{lab}.txt")
            self.metas.append(meta)
            parts.append(f"[{lab}]trim=start={T:g}:end={T + 3:g},setpts=PTS-{T:g}/TB,fps=4,"
                         f"cropdetect=limit=24:round=2:reset=0,metadata=print:file='{_esc(meta)}',"
                         f"trim=duration=2,nullsink")
        return ";".join(parts)

    def terminar(self, ok):
        from ..core import black_bars
        if self.W <= 0 or self.H <= 0:
            black_bars.save_area(self.ctx.path, [], 0, 0)
            return
        if not ok:
            return
        black_bars.save_area(self.ctx.path, [_ultimo_crop(m) for m in self.metas], self.W, self.H)


def _ultimo_crop(meta: str):
    """El último recorte que apuntó cropdetect antes de los 2 s del tramo (w, h, x, y) o None."""
    import re
    try:
        with open(meta, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    last, cur, t = None, {}, None
    for line in txt.splitlines():
        m = re.match(r"frame:\d+\s+pts:\S+\s+pts_time:([\d.\-]+)", line)
        if m:
            if cur.keys() >= {"w", "h", "x", "y"} and t is not None and t < 2.0 + 1e-6:
                last = (cur["w"], cur["h"], cur["x"], cur["y"])
            cur, t = {}, float(m.group(1))
            continue
        m = re.match(r"lavfi\.cropdetect\.(w|h|x|y)=(-?\d+)", line.strip())
        if m:
            cur[m.group(1)] = int(m.group(2))
    if cur.keys() >= {"w", "h", "x", "y"} and t is not None and t < 2.0 + 1e-6:
        last = (cur["w"], cur["h"], cur["x"], cur["y"])
    if last is None:
        return None
    w, h, x, y = last
    return (w, h, x, y) if w > 8 and h > 8 else None


class _Miniatura(_Rama):
    nombres = ("miniatura",)

    def grafo(self, entrada):
        from .thumb_frames import FILTER, STEP, W_SMALL, score_frame, small_height
        h = small_height(self.ctx.path)
        self.items = []

        def add(buf):
            t = STEP / 2 + len(self._vistos) * STEP
            self._vistos.append(t)
            got = score_frame(np.frombuffer(buf, np.uint8).reshape(h, W_SMALL, 3))
            if got is not None:
                self.items.append([round(t, 2), float(got[0]), got[1]])
        self._vistos = []
        lab = self._raw(W_SMALL, h, add)
        return f"{entrada}{FILTER},format=rgb24[{lab}]"

    def terminar(self, ok):
        from .thumb_frames import STEP, save_scored
        if self.completo(ok, self.salidas[0], 1 / STEP):
            save_scored(self.ctx.path, self.items)


class _Tira(_Rama):
    nombres = ("tira",)

    def grafo(self, entrada):
        from ..ui.filmstrip import sprite_filter, sprite_path
        self.out = sprite_path(self.ctx.path, self.ctx.duration)
        self.tmp_jpg = self.out + ".tmp.jpg"
        lab = self.ctx.etiqueta("o")
        self.salidas.append(_Salida(lab, "args", args=["-frames:v", "1", "-q:v", "5", self.tmp_jpg]))
        return f"{entrada}{sprite_filter(self.ctx.duration)}[{lab}]"

    def terminar(self, ok):
        if ok and os.path.exists(self.tmp_jpg) and os.path.getsize(self.tmp_jpg) > 0:
            os.replace(self.tmp_jpg, self.out)
        elif os.path.exists(self.tmp_jpg):
            os.remove(self.tmp_jpg)


class _Escenas(_Rama):
    nombres = ("escenas",)
    propio = True

    def grafo(self, entrada):
        from ..core import scene_cuts
        self.meta = self.ctx.archivo("escenas.txt")
        lab = self._null()
        return f"{entrada}{scene_cuts.scene_filter(self.meta)}[{lab}]"

    def terminar(self, ok):
        from ..core import scene_cuts
        if ok:
            scene_cuts.save_whole(self.ctx.path, scene_cuts.read_meta(self.meta, 0.0))


class _Negros(_Rama):
    nombres = ("negros",)
    propio = True

    def grafo(self, entrada):
        from ..core import black_frames
        lab = self._null()
        return f"{entrada}{black_frames.FILTER}[{lab}]"

    def terminar(self, ok):
        from ..core import black_frames
        if ok:
            try:
                with open(self.ctx.archivo("ffmpeg.log"), encoding="utf-8", errors="replace") as f:
                    black_frames.save_from_log(self.ctx.path, f.read())
            except OSError:
                pass


class _Huella(_Rama):
    """🧬 Huella visual por plano (core/huella_plano.py): un dHash de 64 bits cada 1/8 de segundo."""
    nombres = ("huella",)

    def grafo(self, entrada):
        from ..core import huella_plano as HP
        self.acc = HP.Acumulador()
        lab = self._raw(HP.W, HP.H, self.acc.add)
        return f"{entrada}{HP.FILTER}[{lab}]"

    def terminar(self, ok):
        from ..core import huella_plano as HP
        if self.completo(ok, self.salidas[0], 1 / HP.STEP):
            HP.guardar(self.ctx.path, self.acc.resultado())


_RAMAS = {"movimiento": _Movimiento, "siluetas": _Siluetas, "a_fondo": _AFondo, "barras": _Barras,
          "miniatura": _Miniatura, "tira": _Tira, "escenas": _Escenas, "negros": _Negros, "huella": _Huella}


# ------------------------------------------------------------------ tuberías con nombre (Windows)
class _Tuberia:
    def __init__(self, nombre: str):
        import _winapi
        self.nombre = nombre
        self.h = _winapi.CreateNamedPipe(nombre, _winapi.PIPE_ACCESS_INBOUND, _winapi.PIPE_WAIT, 1,
                                         1 << 20, 1 << 20, 0, _winapi.NULL)
        self.conectada = False

    def conectar(self):
        import _winapi
        try:
            _winapi.ConnectNamedPipe(self.h, _winapi.NULL)
        except OSError as e:
            if getattr(e, "winerror", 0) != 535:      # ERROR_PIPE_CONNECTED: FFmpeg ya la abrió (también vale)
                raise
        self.conectada = True

    def soltar(self):
        """Si FFmpeg nunca la abrió (salió antes), se abre desde aquí y se cierra: el lector deja de esperar."""
        if self.conectada:
            return
        import _winapi
        try:
            h = _winapi.CreateFile(self.nombre, _winapi.GENERIC_WRITE, 0, _winapi.NULL, _winapi.OPEN_EXISTING, 0,
                                   _winapi.NULL)
            _winapi.CloseHandle(h)
        except OSError:
            pass


def _prioridad_hilo(baja: bool):
    """Este hilo (lector y su CLIP) en prioridad baja mientras el trabajo es automático; normal si lo esperas tú."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), -1 if baja else 0)   # BELOW_NORMAL / NORMAL
    except Exception:  # noqa: BLE001
        pass


def _lector(tub: _Tuberia, salida: _Salida, rama: _Rama, parar: threading.Event):
    import _winapi
    import msvcrt
    try:
        tub.conectar()
        fd = msvcrt.open_osfhandle(tub.h, os.O_RDONLY)
    except OSError:
        try:      # (no llegó a conectar: la tubería se cierra aquí, que nadie más la va a usar)
            _winapi.CloseHandle(tub.h)
        except OSError:
            pass
        return
    n = salida.w * salida.h * 3
    baja = None
    with os.fdopen(fd, "rb") as f:
        while True:
            if baja is not rama.ctx.baja:
                baja = rama.ctx.baja
                _prioridad_hilo(baja)
            try:
                buf = f.read(n)
            except OSError:
                break
            if len(buf) < n:
                break
            if parar.is_set() or rama.error:
                continue           # (se sigue vaciando la tubería para que FFmpeg no se quede esperando)
            t0 = time.perf_counter()
            try:
                salida.fn(buf)
                salida.frames += 1
            except Exception as e:  # noqa: BLE001 - un análisis que falla no para a los demás
                rama.error = f"{e.__class__.__name__}: {e}"
            rama.t += time.perf_counter() - t0


def _prioridad_proceso(proc, baja: bool):
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(int(proc._handle), 0x4000 if baja else 0x20)  # BELOW_NORMAL / NORMAL
    except Exception:  # noqa: BLE001
        pass


def _suspender(proc, si: bool):
    """Pausa de verdad: FFmpeg congelado (0 % de procesador) hasta reanudarlo."""
    try:
        import ctypes
        fn = ctypes.windll.ntdll.NtSuspendProcess if si else ctypes.windll.ntdll.NtResumeProcess
        fn(int(proc._handle))
    except Exception:  # noqa: BLE001
        pass


_PASO: list = []


def _paso_libre() -> list[str]:
    """Cada fotograma tal cual (sin repetir ni quitar): -fps_mode desde FFmpeg 5.1; antes, -vsync."""
    if not _PASO:
        args = ["-fps_mode", "passthrough"]
        try:
            import re
            r = media_tools.run_quiet([media_tools.ffmpeg(), "-hide_banner", "-version"], timeout=20)
            m = re.search(r"version\s+n?(\d+)\.(\d+)", r.stdout.decode(errors="replace"))
            if m and (int(m.group(1)), int(m.group(2))) < (5, 1):
                args = ["-vsync", "passthrough"]
        except Exception:  # noqa: BLE001
            pass
        _PASO.append(args)
    return list(_PASO[0])


def _hilos_filtro() -> int:
    return max(1, min(4, (os.cpu_count() or 4) // 4))


# ------------------------------------------------------------------ la pasada
def _pasada(path, duration, quiero, claves, progress, cancelled, pausado, baja) -> dict:
    t_inicio = time.perf_counter()
    es_baja = baja if callable(baja) else (lambda: bool(baja))
    tmp = tempfile.mkdtemp(prefix="pasada_", dir=str(cache_dir("lectura_unica")))
    ctx = _Ctx(path, duration, claves, tmp)
    ctx.baja = bool(es_baja())
    ramas: list[_Rama] = []
    if "clip" in quiero or "pistas" in quiero:
        ramas.append(_Momentos(ctx, quiero))
    ramas += [_RAMAS[n](ctx) for n in quiero if n in _RAMAS]
    try:
        report(progress, 0.0, "⚡ Analizando el video (una sola lectura)…")
        # Video largo leído entero: movimiento y tira siguen con SOLO fotogramas clave (como siempre) desde una
        # segunda entrada con -skip_frame nokey (descodificar solo las claves cuesta muy poco)
        aparte = ctx.largo and not claves and any(isinstance(r, (_Movimiento, _Tira)) for r in ramas)
        grafos = [r.grafo("[0:v]") for r in ramas if r.propio]
        grupos = [("0:v", [r for r in ramas if not r.propio and not (aparte and isinstance(r, (_Movimiento, _Tira)))]),
                  ("1:v", [r for r in ramas if aparte and isinstance(r, (_Movimiento, _Tira))])]
        for entrada, grupo in grupos:
            if not grupo:
                continue
            labs = [ctx.etiqueta("s") for _ in grupo]
            head = (f"[{entrada}]split={len(labs)}" + "".join(f"[{x}]" for x in labs)) if len(labs) > 1 \
                else f"[{entrada}]null[{labs[0]}]"
            cuerpo = []
            for r, lab in zip(grupo, labs):
                g = r.grafo(f"[{lab}]")
                # (una rama que no puede hacer nada —barras de un video sin tamaño— deja su entrada en un nullsink)
                cuerpo.append(g if g else f"[{lab}]nullsink")
            grafos.insert(0, head + ";" + ";".join(cuerpo))
        if not any(r.salidas for r in ramas):
            # FFmpeg necesita al menos una salida y para cuando todas acaban (p. ej. solo las barras, que acaban en
            # nullsink): una salida a null que deja pasar un fotograma y sigue abierta hasta el final del último tramo
            sobra = _Rama(ctx)
            lab = sobra._null()
            grafos.append(f"[0:v]trim=end={ctx.fin + 1:g},select='eq(n,0)'[{lab}]")
            ramas.append(sobra)
        ff = media_tools.ffmpeg()
        args = [ff, "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-y", "-progress", "pipe:1"]
        if claves:
            args += ["-skip_frame", "nokey"]
        # ⚡ sin el filtro de desbloqueo (como ya hacían movimiento, siluetas, escenas, negros, a fondo y miniatura)
        args += ["-skip_loop_filter", "all", "-threads", "0", "-i", path]
        if aparte:
            args += ["-skip_frame", "nokey", "-skip_loop_filter", "all", "-threads", "0", "-i", path]
        args += ["-filter_complex_threads", str(_hilos_filtro())]
        for g in grafos:
            args += ["-filter_complex", g]
        tuberias: list[tuple[_Tuberia, _Salida, _Rama]] = []
        base = rf"\\.\pipe\reclaimer_lectura_{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000)}"
        for r in ramas:
            for s in r.salidas:
                args += ["-map", f"[{s.etiqueta}]"]
                if s.tipo == "raw":
                    tub = _Tuberia(f"{base}_{len(tuberias)}")
                    tuberias.append((tub, s, r))
                    # (sin -fps_mode passthrough, FFmpeg repetiría fotogramas para dar un ritmo constante: los 12
                    # momentos de select acababan siendo miles)
                    args += _paso_libre() + ["-f", "rawvideo", tub.nombre]
                elif s.tipo == "null":
                    args += ["-f", "null", "-"]
                else:
                    args += s.args
        parar = threading.Event()
        hilos = [threading.Thread(target=_lector, args=(tub, s, r, parar), daemon=True) for tub, s, r in tuberias]
        for h in hilos:
            h.start()
        log = open(ctx.archivo("ffmpeg.log"), "w", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL, text=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            log.close()
            parar.set()
            for tub, _s, _r in tuberias:
                tub.soltar()
            raise
        # 🔒 si Reclaimer muere (cuelgue, Administrador de tareas…), FFmpeg muere con él, aunque esté en pausa
        media_tools.atar_a_reclaimer(proc)
        EN_MARCHA[path] = proc
        if ctx.baja:
            _prioridad_proceso(proc, True)
        pos = {"t": 0.0}

        def leer_progreso():
            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    try:
                        pos["t"] = max(pos["t"], int(line.split("=")[1]) / 1e6)
                    except ValueError:
                        pass
        tp = threading.Thread(target=leer_progreso, daemon=True)
        tp.start()
        cancelado = False
        try:
            while proc.poll() is None:
                if cancelled is not None and cancelled():
                    cancelado = True
                    break
                b = bool(es_baja())
                if b != ctx.baja:          # (p. ej. alguien lo espera: sube a prioridad normal)
                    ctx.baja = b
                    _prioridad_proceso(proc, b)
                if pausado is not None and pausado():
                    _suspender(proc, True)
                    try:
                        while pausado() and not (cancelled is not None and cancelled()):
                            time.sleep(0.1)
                    finally:
                        _suspender(proc, False)
                    continue
                if duration > 0:
                    report(progress, min(0.99, pos["t"] / duration), "⚡ Analizando el video (una sola lectura)…")
                try:
                    proc.wait(0.1)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            log.close()
            if cancelado:
                parar.set()
            # Las tuberías que FFmpeg no llegó a abrir (p. ej. un archivo que no se puede leer) se sueltan YA: sus
            # lectores dejan de esperar al momento. Después se espera a los lectores, sin dejar de atender a cancelar.
            for tub, _s, _r in tuberias:
                tub.soltar()
            fin = time.monotonic() + 60
            for h in hilos:
                while h.is_alive() and time.monotonic() < fin:
                    h.join(0.1)
                    if not cancelado and cancelled is not None and cancelled():
                        cancelado = True
                        parar.set()
            tp.join(2)
            EN_MARCHA.pop(path, None)
        if cancelado:
            raise Cancelled()
        check_cancel(cancelled)
        ok = proc.returncode == 0
        informe = {"pasada": 0.0, "analisis": {}, "fallos": {}, "claves": claves, "ok": ok}
        for r in ramas:
            t0 = time.perf_counter()
            try:
                if not r.error and r.nombres:
                    r.terminar(ok)
            except Exception as e:  # noqa: BLE001
                r.error = f"{e.__class__.__name__}: {e}"
            r.t += time.perf_counter() - t0
            for n in r.nombres:
                informe["analisis"][n] = round(r.t / max(1, len(r.nombres)), 3)
                if r.error:
                    informe["fallos"][n] = r.error
        informe["pasada"] = round(time.perf_counter() - t_inicio, 3)
        report(progress, 1.0, "")
        _HISTORIAL.append(dict(informe, archivo=os.path.basename(path), cuando=datetime.now().isoformat(timespec="seconds")))
        del _HISTORIAL[:-50]
        if not ok and not cancelado:
            try:
                with open(ctx.archivo("ffmpeg.log"), encoding="utf-8", errors="replace") as f:
                    informe["ffmpeg"] = f.read()[-400:]
            except OSError:
                pass
        return informe
    finally:
        shutil.rmtree(tmp, True)


EN_MARCHA: dict = {}            # archivo -> su FFmpeg en marcha (para consultar o probar; no tocar desde fuera)
_HISTORIAL: list[dict] = []     # las últimas lecturas: archivo, tiempo de la pasada y de cada análisis


def historial() -> list[dict]:
    return list(_HISTORIAL)


def nombre_visible(n: str) -> str:
    return _NOMBRE.get(n, n)
