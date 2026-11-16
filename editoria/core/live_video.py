"""
🎞 Motor de video propio (como el de DaVinci / Kdenlive / Shotcut): cada archivo se decodifica con PyAV en su propio
hilo, a la resolución con la que se ve en el visor, con fotogramas por delante al reproducir, saltos exactos en pausa y
una caché de los recientes (arrastrar el cabezal por donde ya pasaste es instantáneo). Sin Qt: la imagen se entrega como
bytes RGBA; ui/preview.py la pone en el visor.

  FrameSource(path)            un archivo; .want(t, playing, size) pide; .frame_at(t) → (pts, w, h, bytes) o None
  .trim(n)                     deja solo n fotogramas (pistas que no se ven: menos memoria)
  .close(wait=0)

Los fotogramas se guardan por su tiempo REAL (pts, desde el inicio del archivo): bien con videos de fps variable
(móviles), con archivos que no empiezan en 0 (.ts) y al final del archivo. Tramos ya decodificados seguidos: lo pedido
dentro de un tramo está «servido» aunque no haya un fotograma justo en ese instante. Rotación del móvil aplicada.
Memoria con tope (CACHE_BYTES por archivo). Si un archivo no da imagen, .error y el visor vuelve a sus reproductores.
"""
from __future__ import annotations

import bisect
import threading
import time

AHEAD_S = 0.6            # cuánto va por delante al reproducir
BEHIND_N = 45            # en pausa, también se guardan los fotogramas anteriores (paso atrás / arrastre hacia atrás)
CACHE_BYTES = 256 * 1024 * 1024
MAX_W = 1920             # nunca se decodifica más ancho que esto (memoria y coste de copiarlo al visor)
MAX_FALLOS = 12          # intentos seguidos sin imagen → error (el visor usa sus reproductores)


class FrameSource:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Condition()
        self._want_t = 0.0
        self._playing = False
        self._size = (960, 540)
        self._gen = 0
        self._pts: list[float] = []               # tiempos guardados (ordenados)
        self._data: dict[float, tuple] = {}       # pts → (pts, w, h, bytes)
        self._bytes = 0
        self._segs: list[list[float]] = []        # tramos decodificados seguidos [desde, hasta]
        self._fps = 30.0
        self._dur = 0.0
        self._last_pts: float | None = None       # último fotograma del archivo (al llegar al final)
        self._closed = False
        self.error: str | None = None
        self.rotation = 0
        self.seeks = 0                            # saltos hechos (diagnóstico y pruebas)
        self._th = threading.Thread(target=self._run, name="video_decode", daemon=True)
        self._th.start()

    # --------------------------------------------------------------- desde la interfaz
    def want(self, t: float, playing: bool, size: tuple[int, int] | None = None):
        with self._lock:
            if size:
                w, h = size
                if w > MAX_W:
                    h, w = max(2, int(h * MAX_W / w) // 2 * 2), MAX_W
                if (w, h) != self._size:
                    self._size = (w, h)
                    self._clear()                 # (otro tamaño: lo guardado ya no vale)
            self._want_t = self._tope(t)
            self._playing = playing
            self._gen += 1
            self._lock.notify()

    def _tope(self, t: float) -> float:
        """Más allá del final del archivo: el último fotograma (el mismo límite al pedir y al mirar)."""
        if self._last_pts is not None:
            t = min(t, self._last_pts)
        elif self._dur > 0:
            t = min(t, max(0.0, self._dur - 1.0 / self._fps))
        return max(0.0, t)

    def _clear(self):
        self._pts, self._data, self._bytes, self._segs = [], {}, 0, []

    def _covered(self, t: float) -> bool:
        half = 0.5 / self._fps
        for a, b in self._segs:
            if a - half <= t <= b + half:
                return True
        return False

    def frame_at(self, t: float):
        """El fotograma que se ve en t: el último con pts ≤ t (+ medio fotograma), si t está en un tramo servido."""
        with self._lock:
            if not self._pts:
                return None
            t = self._tope(t)
            if not self._covered(t):
                return None
            k = bisect.bisect_right(self._pts, t + 0.5 / self._fps) - 1
            return self._data[self._pts[k]] if k >= 0 else None

    def trim(self, n: int = 3):
        """Deja solo los n fotogramas más cercanos a lo último pedido (la pista no se ve: menos memoria)."""
        with self._lock:
            if len(self._pts) <= n:
                return
            k = bisect.bisect_right(self._pts, self._want_t)
            keep = set(self._pts[max(0, k - n):k + 1])
            for p in self._pts:
                if p not in keep:
                    self._bytes -= len(self._data.pop(p)[3])
            self._pts = sorted(keep)
            self._recortar_segs()

    @property
    def fps(self) -> float:
        return self._fps

    def close(self, wait: float = 0.0):
        with self._lock:
            self._closed = True
            self._lock.notify()
        if wait > 0:
            self._th.join(wait)

    # --------------------------------------------------------------- hilo
    def _ahead(self) -> float:
        """Lo que se decodifica por delante: AHEAD_S o menos si no cabe (1080p60 a todo tamaño)."""
        w, h = self._size
        cabe = CACHE_BYTES / max(1, w * h * 4)
        return min(AHEAD_S, 0.6 * cabe / max(1.0, self._fps))

    def _recortar_segs(self):
        """Cada tramo, ajustado a los fotogramas que quedan dentro (los vacíos fuera; los que se tocan, juntos)."""
        nuevos = []
        for a, b in sorted(self._segs):
            i = bisect.bisect_left(self._pts, a - 1e-9)
            j = bisect.bisect_right(self._pts, b + 1e-9) - 1
            if i > j:
                continue
            a2, b2 = self._pts[i], self._pts[j]
            if nuevos and a2 <= nuevos[-1][1] + 1.5 / self._fps:
                nuevos[-1][1] = max(nuevos[-1][1], b2)
            else:
                nuevos.append([a2, b2])
        self._segs = nuevos

    def _store(self, pts: float, w: int, h: int, data: bytes, gen_size: tuple) -> bool:
        with self._lock:
            if gen_size != self._size:
                return False                      # (de antes de cambiar el tamaño)
            if pts in self._data:
                return True
            bisect.insort(self._pts, pts)
            self._data[pts] = (pts, w, h, data)
            self._bytes += len(data)
            if self._bytes <= CACHE_BYTES:
                return True
            # tope de memoria: fuera lo de DETRÁS primero y lo más lejano; nunca lo que va a verse ya
            lo, hi = self._want_t - 2.0 / self._fps, self._want_t + self._ahead() + 1.0 / self._fps
            guardado = True
            while self._bytes > CACHE_BYTES and len(self._pts) > 8:
                p0, p1 = self._pts[0], self._pts[-1]
                cand = [p for p in (p0, p1) if not (lo <= p <= hi)]
                if not cand:
                    break
                lejos = max(cand, key=lambda p: abs(p - self._want_t))
                self._pts.remove(lejos)
                self._bytes -= len(self._data.pop(lejos)[3])
                if lejos == pts:
                    guardado = False
            self._recortar_segs()
            return guardado

    def _extend_seg(self, seg: list[float] | None, pts: float) -> list[float]:
        with self._lock:
            if seg is None or not any(s is seg for s in self._segs):
                seg = next((s for s in self._segs if s[0] - 1.5 / self._fps <= pts <= s[1] + 1.5 / self._fps), None)
                if seg is None:
                    seg = [pts, pts]
                    self._segs.append(seg)
            seg[0] = min(seg[0], pts)
            seg[1] = max(seg[1], pts)
            return seg

    def _run(self):
        cont = None
        try:
            import av
            cont = av.open(self.path)
            st = cont.streams.video[0]
            st.thread_type = "AUTO"
            rate = st.average_rate or st.guessed_rate
            self._fps = float(rate) if rate else 30.0
            tb = st.time_base
            t0 = float(st.start_time * tb) if st.start_time is not None else 0.0   # (.ts: no empiezan en 0)
            if st.duration is not None:
                self._dur = float(st.duration * tb)
            elif cont.duration:
                self._dur = cont.duration / 1e6
        except Exception as exc:  # noqa: BLE001 - archivo que PyAV no abre: el visor usa su reproductor de siempre
            self.error = str(exc)[:200]
            if cont is not None:
                try:
                    cont.close()
                except Exception:  # noqa: BLE001
                    pass
            return
        dec = None
        seg = None
        pos_dec = -1.0
        fallos = 0
        seek_malo = False                 # el archivo no deja saltar (algunos .ts): se lee siempre hacia delante
        while True:
            with self._lock:
                if self._closed:
                    break
                t, playing, size, gen = self._tope(self._want_t), self._playing, self._size, self._gen
                half = 0.5 / self._fps
                hasta = t + (self._ahead() if playing else 0.0)
                if playing:
                    falta = not self._covered(t) or not self._covered(min(hasta, self._last_pts or hasta))
                else:
                    falta = not self._covered(t)
                if not falta:
                    fallos = 0                    # (solo cuando lo pedido está servido de verdad)
                    self._lock.wait(0.05)
                    continue
            # seguir la decodificación en curso si lo pedido está por delante (o dentro) de lo ya decodificado
            seguir = dec is not None and pos_dec >= 0 and t <= pos_dec + 1.0 and (self._covered(t) or t >= pos_dec - half)
            if seek_malo and dec is not None and pos_dec >= 0 and t >= pos_dec - half:
                seguir = True                     # (archivo sin saltos: hacia delante, decodificando)
            recien = False
            try:
                if not seguir:
                    if seek_malo:                 # (hacia atrás en un archivo sin saltos: desde el principio)
                        cont.seek(0)
                    else:
                        cont.seek(max(0, int((t + t0) / tb)), stream=st, backward=True, any_frame=False)
                    self.seeks += 1
                    dec = cont.decode(st)
                    seg = None
                    pos_dec = -1.0
                    recien = True
                    fallos += 1
                    if fallos > MAX_FALLOS:
                        self.error = "no da imagen en ese punto"
                        break
                n = 0
                guardar_desde = t - (BEHIND_N / self._fps if not playing else half)
                for fr in dec:
                    if fr.time is None:
                        continue
                    pts = float(fr.time) - t0
                    pos_dec = pts
                    if pts >= guardar_desde - 1e-6:
                        w, h = size
                        rot = int(getattr(fr, "rotation", 0) or 0) % 360
                        self.rotation = rot
                        if rot in (90, 270):              # 📱 video vertical del móvil: se endereza
                            f2 = fr.reformat(width=h, height=w, format="rgba")
                        else:
                            f2 = fr.reformat(width=w, height=h, format="rgba")
                        arr = f2.to_ndarray()
                        if rot:
                            import numpy as np
                            arr = np.ascontiguousarray(np.rot90(arr, k=rot // 90))
                        if self._store(pts, arr.shape[1], arr.shape[0], arr.tobytes(), size):
                            seg = self._extend_seg(seg, pts)
                    n += 1
                    with self._lock:
                        cambio = self._gen != gen or self._closed
                    if cambio or pts >= hasta - half or n > 900:
                        break
                else:
                    if recien and n == 0 and not seek_malo:
                        seek_malo = True          # (.ts sin índice: el salto no da nada → leer hacia delante)
                        dec = None
                        continue
                    with self._lock:                      # final del archivo: el último fotograma de verdad
                        if pos_dec >= 0:
                            self._last_pts = pos_dec
                            self._want_t = self._tope(self._want_t)
                        self._lock.wait(0.05)
                    dec = None
            except Exception:  # noqa: BLE001 - un paquete roto: se salta y se sigue (con tope)
                dec = None
                fallos += 1
                if fallos > MAX_FALLOS:
                    self.error = "el archivo da errores al decodificar"
                    break
                time.sleep(0.01)
        try:
            cont.close()
        except Exception:  # noqa: BLE001
            pass
