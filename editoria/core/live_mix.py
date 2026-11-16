"""
🎧 Mezcla en directo (como Fairlight en DaVinci Resolve): el sonido del visor sale de aquí, no de los reproductores de
Qt, así que el ecualizador, el balance, el volumen, las curvas, los fundidos y la música que baja cuando hablas se oyen
MIENTRAS suena y al instante de cambiarlos. Sin Qt (la salida a la tarjeta está en ui/live_audio.py).

  Decoder()                     el audio de cada archivo: entero y continuo en la caché (memmap) y, mientras se
                                prepara, trozos de 8 s; get(ruta, desde, n, mono) → muestras o None (se piden solas)
  Source                        un clip que suena: ruta, dónde empieza, desde qué segundo del archivo, volumen…
  Plan(sources, speech, mute)   lo que suena ahora (se cambia entero desde el hilo de la interfaz)
  Mixer(decoder)                render(t0, n) → bloque (n, 2) float32 con todo mezclado y el EQ de cada clip
  eq_fir(eq)                    respuesta al impulso del EQ (las mismas fórmulas RBJ que FFmpeg al exportar)

El EQ se aplica con convolución por bloques (FFT): mismo sonido que los filtros de FFmpeg, sin scipy. Al cambiar el EQ,
el bloque siguiente pasa del filtro viejo al nuevo con un fundido corto (sin chasquidos).
"""
from __future__ import annotations

import subprocess
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from . import curves, effects
from . import equalizer as E
from . import media as M
from .audio_fx import duck_gain

SR = 48000
CHUNK_S = 8.0
CHUNK_N = int(SR * CHUNK_S)
FIR_N = 4096                # taps del EQ (85 ms: de sobra para campanas y estantes; los cortes de graves muy bajos
                            # se recortan suavemente al final)


# ------------------------------------------------------------------ decodificación
class Decoder:
    """El audio de cada archivo, sin cortes:
      · la primera vez se decodifica ENTERO en segundo plano a un archivo de la caché (int16 estéreo 48 kHz, continuo:
        sin clics entre trozos en MP3/AAC/Opus) y luego se lee al instante (memmap); la caché sabe si el archivo cambió;
      · mientras tanto, trozos de CHUNK_S s con FFmpeg (rápidos: suena enseguida).
    Mono: las dos salidas con el mismo canal (como al exportar; antes sonaba 3 dB más bajo)."""

    def __init__(self, max_chunks: int = 48, workers: int = 2):
        self.max_chunks = max_chunks
        self._cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._pend: dict[tuple, object] = {}             # trozo → Future (para cancelar los que ya no hacen falta)
        self._fail: set[tuple] = set()
        self._full: dict[str, np.ndarray | None] = {}     # clave del archivo → memmap (None = decodificándose)
        self._full_fail: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audio_decode")
        self._pool_full = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio_decode_full")
        self._keys: dict[tuple, str] = {}

    # --------------------------------------------------------------- claves y caché en disco
    def _key(self, path: str, mono: bool) -> str:
        k = self._keys.get((path, mono))
        if k is None:
            k = f"{M.cache_key(path)}{'_m' if mono else ''}"
            self._keys[(path, mono)] = k
        return k

    @staticmethod
    def _dir():
        from .paths import cache_dir
        return cache_dir("audio_vivo")

    @staticmethod
    def _af(mono: bool) -> list[str]:
        return ["-af", "pan=stereo|c0=c0|c1=c0"] if mono else ["-ac", "2"]

    def _full_job(self, path: str, mono: bool, key: str):
        dest = self._dir() / f"{key}.pcm"
        tmp = dest.with_suffix(".part")
        try:
            if not dest.exists():
                r = M.run_quiet([M.ffmpeg(), "-v", "error", "-nostdin", "-y", "-i", path, "-map", "0:a:0", "-vn",
                                 *self._af(mono), "-ar", str(SR), "-f", "s16le", str(tmp)], timeout=900)
                if r.returncode != 0 or not tmp.exists():
                    raise RuntimeError("ffmpeg")
                tmp.replace(dest)
                self._podar()
            mm = np.memmap(dest, dtype=np.int16, mode="r")
            mm = mm[: len(mm) // 2 * 2].reshape(-1, 2)
            with self._lock:
                self._full[key] = mm
        except Exception:  # noqa: BLE001 - se queda con los trozos
            try:
                tmp.unlink()
            except OSError:
                pass
            with self._lock:
                self._full.pop(key, None)
                self._full_fail.add(key)

    def _podar(self, tope: int = 4 * 1024 ** 3):
        """La caché en disco no pasa de ~4 GB (se van los archivos más viejos)."""
        try:
            fs = sorted(self._dir().glob("*.pcm"), key=lambda f: f.stat().st_atime)
            total = sum(f.stat().st_size for f in fs)
            for f in fs:
                if total <= tope:
                    break
                total -= f.stat().st_size
                f.unlink()
        except OSError:
            pass

    def _ensure_full(self, path: str, mono: bool) -> np.ndarray | None:
        key = self._key(path, mono)
        with self._lock:
            if key in self._full:
                return self._full[key]
            if key in self._full_fail:
                return None
            self._full[key] = None
        dest = self._dir() / f"{key}.pcm"
        if dest.exists():                                 # (ya decodificado en otra sesión: al instante)
            self._full_job(path, mono, key)
            return self._full.get(key)
        self._pool_full.submit(self._full_job, path, mono, key)
        return None

    # --------------------------------------------------------------- trozos (mientras tanto)
    def _decode(self, path: str, idx: int, mono: bool, ck: tuple):
        try:
            r = M.run_quiet([M.ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{idx * CHUNK_S:.3f}",
                             "-t", f"{CHUNK_S + 0.1:.3f}", "-i", path, "-map", "0:a:0", "-vn", *self._af(mono),
                             "-ar", str(SR), "-f", "f32le", "-"], timeout=15)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode(errors="replace")[-200:])
            a = np.frombuffer(r.stdout, dtype=np.float32)
            a = a[: len(a) // 2 * 2].reshape(-1, 2)[:CHUNK_N].copy()   # (se pide un poco de más: sin huecos)
        except Exception:  # noqa: BLE001 - sin audio o roto: ese trozo en silencio (no se reintenta en bucle)
            with self._lock:
                self._pend.pop(ck, None)
                self._fail.add(ck)
            return
        with self._lock:
            self._cache[ck] = a
            self._cache.move_to_end(ck)
            while len(self._cache) > self.max_chunks:
                self._cache.popitem(last=False)
            self._pend.pop(ck, None)

    def request(self, path: str, idx: int, mono: bool = False):
        if idx < 0:
            return
        if self._ensure_full(path, mono) is not None:
            return
        ck = (self._key(path, mono), idx)
        with self._lock:
            if ck in self._cache or ck in self._pend or ck in self._fail:
                return
            self._pend[ck] = None
        fut = self._pool.submit(self._decode, path, idx, mono, ck)
        with self._lock:
            if ck in self._pend:
                self._pend[ck] = fut

    def only(self, needed: set[tuple]):
        """Cancela los trozos pedidos que ya no hacen falta (al arrastrar el cabezal en pausa no se acumulan)."""
        with self._lock:
            for ck, fut in list(self._pend.items()):
                if ck not in needed and fut is not None and fut.cancel():
                    del self._pend[ck]

    def ready(self, path: str, t: float, mono: bool = False) -> bool:
        key = self._key(path, mono)
        with self._lock:
            if self._full.get(key) is not None:
                return True
            return (key, int(max(0.0, t) // CHUNK_S)) in self._cache or (key, int(max(0.0, t) // CHUNK_S)) in self._fail

    def get(self, path: str, t: float, n: int, mono: bool = False) -> np.ndarray | None:
        """n muestras desde el segundo t del archivo. None si aún no están (se piden solas)."""
        out = np.zeros((n, 2), np.float32)
        s0 = int(round(t * SR))
        lead = 0
        if s0 < 0:                                        # (antes del principio del archivo: silencio)
            lead = min(n, -s0)
            s0 = 0
        full = self._ensure_full(path, mono)
        if full is not None:
            a = full[s0:s0 + n - lead]
            out[lead:lead + len(a)] = a.astype(np.float32) * (1.0 / 32768.0)
            return out
        key = self._key(path, mono)
        hecho = lead
        while hecho < n:
            pos = s0 + hecho - lead
            idx = pos // CHUNK_N
            off = pos - idx * CHUNK_N
            ck = (key, idx)
            with self._lock:
                ch = self._cache.get(ck)
                if ch is not None:
                    self._cache.move_to_end(ck)
                fallo = ck in self._fail
            if fallo:
                break                                     # (trozo imposible: silencio)
            if ch is None:
                self.request(path, idx, mono)
                return None
            k = min(n - hecho, CHUNK_N - off)
            disp = max(0, min(k, len(ch) - off))
            if disp > 0:
                out[hecho:hecho + disp] = ch[off:off + disp]
            if len(ch) < CHUNK_N and off + k >= len(ch):   # (final del archivo: lo que sigue es silencio)
                break
            hecho += k
        return out

    def prefetch(self, path: str, t: float, seconds: float = 3.0, mono: bool = False) -> set[tuple]:
        if self._ensure_full(path, mono) is not None:
            return set()
        key = self._key(path, mono)
        out = set()
        for idx in range(int(max(0.0, t) // CHUNK_S), int(max(0.0, t + seconds) // CHUNK_S) + 1):
            self.request(path, idx, mono)
            out.add((key, idx))
        return out

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._pool_full.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ ecualizador
def _band_h(b: dict, w: np.ndarray) -> np.ndarray:
    bb, aa = E._biquad(b, SR)
    z = np.exp(-1j * w)
    return (bb[0] + bb[1] * z + bb[2] * z * z) / (aa[0] + aa[1] * z + aa[2] * z * z)


def eq_fir(eq: dict | None) -> np.ndarray | None:
    """Respuesta al impulso (FIR_N taps) del EQ del clip, o None si no hace nada. Misma magnitud y fase que los
    filtros IIR de FFmpeg (se calcula su respuesta compleja y se pasa al tiempo)."""
    if not E.is_active(eq):
        return None
    n = FIR_N * 4
    w = np.linspace(0, np.pi, n // 2 + 1)
    h = np.ones_like(w, dtype=complex)
    for b in E.normalize(eq)["bands"]:
        if not b.get("on"):
            continue
        if b["type"] in ("bell", "lowshelf", "highshelf") and abs(b.get("g", 0.0)) <= 0.05:
            continue
        h *= _band_h(b, w)
    ir = np.fft.irfft(h, n)[:FIR_N]
    cola = FIR_N // 8                                    # final suave: sin corte brusco de la cola
    ir[-cola:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, cola)))
    return ir.astype(np.float32)


class _Convolver:
    """Convolución por bloques (solapar y sumar) que guarda la cola entre bloques."""

    def __init__(self, ir: np.ndarray, block: int):
        self.ir = ir
        self.nfft = 1 << int(np.ceil(np.log2(block + len(ir) - 1)))
        self.H = np.fft.rfft(ir, self.nfft)[:, None]
        self.tail = np.zeros((len(ir) - 1, 2), np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        y = np.fft.irfft(np.fft.rfft(x, self.nfft, axis=0) * self.H, self.nfft, axis=0)[: n + len(self.ir) - 1]
        y = y.astype(np.float32)
        y[: len(self.tail)] += self.tail[: min(len(self.tail), len(y))]
        out = y[:n].copy()
        resto = y[n:]
        nueva = np.zeros_like(self.tail)
        nueva[: len(resto)] = resto
        if len(self.tail) > n:                          # (bloque más corto que el filtro: lo que quedaba de antes)
            nueva[: len(self.tail) - n] += self.tail[n:]
        self.tail = nueva
        return out


# ------------------------------------------------------------------ plan y mezcla
@dataclass
class Source:
    key: str                 # id del clip
    path: str
    start: float             # en la línea de tiempo
    end: float
    src_in: float            # segundo del archivo al empezar el clip
    clip: object             # copia del Clip (para curvas de volumen y fundidos)
    eq: dict | None = None
    pan: float = 0.0
    duck_db: float | None = None
    audible: bool = True
    mono: bool = False       # archivo de un canal: suena por los dos lados (como al exportar)


@dataclass
class Plan:
    sources: list[Source] = field(default_factory=list)
    speech: list[tuple[float, float]] = field(default_factory=list)
    mute: bool = False


class Mixer:
    def __init__(self, decoder: Decoder, block: int = 1024):
        self.decoder = decoder
        self.block = block
        self.plan = Plan()
        self._fx: dict[str, tuple[str, _Convolver | None]] = {}     # clip → (firma del EQ, convolución)
        self._fir_memo: dict[str, np.ndarray | None] = {}

    def reset(self):
        """Salto o nueva reproducción: las colas de los filtros no se arrastran."""
        self._fx.clear()

    def _conv(self, s: Source):
        firma = repr(s.eq) if E.is_active(s.eq) else ""
        viejo = self._fx.get(s.key)
        if viejo is not None and viejo[0] == firma:
            return viejo[1], None
        if firma not in self._fir_memo:
            if len(self._fir_memo) > 64:
                self._fir_memo.clear()
            self._fir_memo[firma] = eq_fir(s.eq) if firma else None
        ir = self._fir_memo[firma]
        nuevo = _Convolver(ir, self.block) if ir is not None else None
        self._fx[s.key] = (firma, nuevo)
        return nuevo, (viejo[1] if viejo is not None else False)

    def _gain(self, s: Source, t: float) -> float:
        if not s.audible:
            return 0.0
        g = curves.gain(s.clip, t) * effects.fade_gain(getattr(s.clip, "fx", None), t - s.start, s.end - s.start)
        if s.duck_db is not None:
            g *= duck_gain(self.plan.speech, t, s.duck_db)
        return g

    def render(self, t0: float, n: int | None = None) -> np.ndarray:
        n = n or self.block
        plan = self.plan                      # (una sola lectura: el hilo de la interfaz puede cambiarlo)
        out = np.zeros((n, 2), np.float32)
        if plan.mute:
            return out
        t1 = t0 + n / SR
        vivos = set()
        for s in plan.sources:
            if s.end <= t0 or s.start >= t1:
                continue
            vivos.add(s.key)
            a = max(0, int(round((s.start - t0) * SR)))
            b = min(n, int(round((s.end - t0) * SR)))
            if b <= a:
                continue
            ta = t0 + a / SR
            g0, g1 = self._gain(s, ta), self._gain(s, t0 + b / SR)
            conv, antes = self._conv(s)
            if g0 <= 1e-5 and g1 <= 1e-5 and conv is None:
                continue
            x = self.decoder.get(s.path, s.src_in + (ta - s.start), b - a, s.mono)
            if x is None:
                continue                                  # (aún decodificando: silencio este bloque)
            buf = np.zeros((n, 2), np.float32)
            buf[a:b] = x
            if conv is not None:
                y = conv.process(buf)
                if antes:                                 # EQ recién cambiado: fundido del viejo al nuevo
                    y_old = antes.process(buf)
                    r = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
                    y = y_old * (1 - r) + y * r
                buf = y
            elif antes:                                   # se apagó el EQ: fundido del filtrado al limpio
                y_old = antes.process(buf)
                r = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
                buf = y_old * (1 - r) + buf * r
            env = np.linspace(g0, g1, n, dtype=np.float32)[:, None]      # volumen sin saltos dentro del bloque
            if abs(s.pan) > 0.01:
                buf = buf * np.array([min(1.0, 1 - s.pan), min(1.0, 1 + s.pan)], np.float32)
            out += buf * env
        for k in [k for k in self._fx if k not in vivos]:    # clips que ya no suenan: sus filtros fuera
            del self._fx[k]
        np.clip(out, -1.0, 1.0, out=out)
        return out

    def prefetch(self, t: float, ahead: float = 3.0, solo_esto: bool = False):
        """Pide ya lo que va a sonar en los próximos segundos (los clips que empiezan pronto, también).
        solo_esto: cancela lo pedido antes que ya no hace falta (al saltar o arrastrar el cabezal)."""
        needed: set[tuple] = set()
        for s in self.plan.sources:
            if s.end > t and s.start < t + ahead and s.audible:
                desde = s.src_in + max(0.0, t - s.start)
                needed |= self.decoder.prefetch(s.path, desde, min(ahead, s.end - max(t, s.start)) + 0.5, s.mono)
        if solo_esto and hasattr(self.decoder, "only"):
            self.decoder.only(needed)

    def ready_at(self, t: float) -> bool:
        return all(self.decoder.ready(s.path, s.src_in + max(0.0, t - s.start), s.mono)
                   for s in self.plan.sources if s.start <= t < s.end and s.audible)
