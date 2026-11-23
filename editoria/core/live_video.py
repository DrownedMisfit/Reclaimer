"""
🎞 Motor de video propio (como el de DaVinci / Kdenlive / Shotcut): cada archivo se decodifica con PyAV en su propio
hilo, a la resolución con la que se ve en el visor, con fotogramas por delante al reproducir, saltos exactos en pausa y
una caché de los recientes (arrastrar el cabezal por donde ya pasaste es instantáneo). Sin Qt: la imagen se entrega como
bytes RGBA; ui/preview.py la pone en el visor.

  FrameSource(path)            un archivo; .want(t, playing, size) pide; .frame_at(t) → (pts, w, h, bytes) o None
  .trim(n)                     deja solo n fotogramas (pistas que no se ven: menos memoria)
  .close(wait=0)               .cerrado: ¿ya se cerró? (quien la guarde la vuelve a abrir si la necesita)
  cerrar_fuentes(rutas)        🔓 cierra TODAS las abiertas de esos archivos o carpetas (las use quien las use)
  retener(rutas, s) / retenido(ruta)   durante s segundos ninguna fuente nueva abre esos archivos (se borran o mueven)

Los fotogramas se guardan por su tiempo REAL (pts, desde el inicio del archivo): bien con videos de fps variable
(móviles), con archivos que no empiezan en 0 (.ts) y al final del archivo. Tramos ya decodificados seguidos: lo pedido
dentro de un tramo está «servido» aunque no haya un fotograma justo en ese instante. Rotación del móvil aplicada.
Memoria con tope (CACHE_BYTES por archivo). Si un archivo no da imagen, .error y el visor vuelve a sus reproductores.

⚡ Rendimiento cuidando el equipo (20/11):
  · lo pesado (más que 1080p, o HEVC/AV1/VP9) se REPRODUCE con la TARJETA GRÁFICA (D3D11VA/DXVA2) si la hay: HEVC 4K
    a 30 fps pasa de ~0,8 núcleos a ~0,25 (y la batería lo agradece). En pausa (saltos, arrastrar el cabezal) va con el
    procesador, que salta antes (4K: ~120 ms frente a ~250); el cambio se hace con lo ya decodificado por delante, sin
    que se note. Con la batería, siempre la tarjeta. Si la tarjeta no puede, el procesador. Apagable con
    RECLAIMER_DECOD_GRAFICA=0 o USAR_GRAFICA = False.
  · hilos con tope (core/energia.py): nunca más de la mitad de los núcleos; con la batería, 2 y menos lectura por delante.
  · saltos en pausa más rápidos: hasta llegar al fotograma pedido NO se convierte ninguno de los anteriores (antes, hasta
    45 conversiones por salto); se convierte el pedido, se enseña, y luego los pocos de justo antes (paso atrás).
  · reproduciendo, lo ya visto se suelta enseguida (queda ATRAS_S): la memoria no crece hasta el tope.
"""
from __future__ import annotations

import bisect
import threading
import time

AHEAD_S = 0.6            # cuánto va por delante al reproducir (con la batería, la mitad)
BEHIND_N = 8             # en pausa, también se guardan los fotogramas de justo antes (paso atrás / arrastre hacia atrás)
BEHIND_BYTES = 48 * 1024 * 1024   # (tope de esos anteriores sin convertir mientras se busca el pedido: en 4K, 2–3)
ATRAS_S = 0.5            # reproduciendo, lo ya visto que se guarda (pausar y dar un paso atrás sin decodificar)
CACHE_BYTES = 160 * 1024 * 1024
USAR_GRAFICA = True      # decodificar lo pesado con la tarjeta gráfica (si la hay)
MAX_W = 3840             # nunca más ancho que esto (el visor pide su ancho real: con uno de más de 1920 px, un
                         # 4K en pausa se ve tan nítido como con Qt; la lectura por delante se acorta sola)
MAX_FALLOS = 12          # intentos seguidos sin imagen → error (el visor usa sus reproductores)
RESPIRO_S = 0.03         # en pausa: lo que se espera tras enseñar el pedido antes de convertir los de justo antes
SEGUIR_S = 2.5           # lo pedido hasta 2,5 s por delante de lo decodificado: se sigue decodificando (sin saltar)


_DISPOSITIVO: list = []   # [nombre o None]: la tarjeta para decodificar (se mira una vez)

# 🔓 Soltar archivos (21/11): en Windows un archivo abierto no se puede borrar, mover ni renombrar («WinError 32»).
_VIVAS = __import__("weakref").WeakSet()   # todas las FrameSource abiertas (las guarde quien las guarde)
_VIVAS_LOCK = threading.Lock()
_RETENIDOS: dict = {}     # clave (ruta normalizada) → hasta cuándo (monotonic) no se abre


def clave_ruta(ruta: str) -> str:
    import os
    try:
        return os.path.normcase(os.path.abspath(str(ruta)))
    except (TypeError, ValueError):
        return ""


def _toca(clave: str, claves) -> bool:
    """¿clave es una de claves o está dentro de alguna (carpeta)?"""
    import os
    if not clave:
        return False
    if clave in claves:
        return True
    return any(clave.startswith(c.rstrip(os.sep) + os.sep) for c in claves if c)


def retener(rutas, segundos: float = 3.0) -> None:
    """Durante «segundos», ninguna fuente nueva abre esos archivos (o lo de dentro de esas carpetas): el visor espera
    a que se borren o se muevan en vez de volver a abrirlos entre medias. segundos <= 0 = ya no se retienen."""
    fin = time.monotonic() + max(0.0, float(segundos))
    with _VIVAS_LOCK:
        for r in rutas or []:
            k = clave_ruta(r)
            if not k:
                continue
            if segundos > 0:
                _RETENIDOS[k] = fin
            else:
                _RETENIDOS.pop(k, None)


def retenido(ruta: str) -> bool:
    if not _RETENIDOS:
        return False
    ahora = time.monotonic()
    with _VIVAS_LOCK:
        for k in [k for k, fin in _RETENIDOS.items() if fin <= ahora]:
            del _RETENIDOS[k]
        vivos = list(_RETENIDOS)
    return bool(vivos) and _toca(clave_ruta(ruta), vivos)


def fuentes_abiertas() -> list:
    """Las FrameSource sin cerrar (diagnóstico y pruebas)."""
    with _VIVAS_LOCK:
        return [s for s in list(_VIVAS) if not s.cerrado]


def cerrar_fuentes(rutas, espera: float = 1.0) -> int:
    """🔓 Cierra TODAS las FrameSource de esos archivos (o de lo que haya dentro de esas carpetas), estén donde estén
    (visor, fotograma suelto, transiciones…), y espera como mucho «espera» s en total a que sus hilos suelten el archivo.
    Quien las guarde ve .cerrado y abre otra cuando la necesite. Se puede llamar desde cualquier hilo. Devuelve cuántas."""
    claves = {k for k in (clave_ruta(r) for r in rutas or []) if k}
    if not claves:
        return 0
    with _VIVAS_LOCK:
        fuentes = [s for s in list(_VIVAS) if _toca(clave_ruta(s.path), claves)]
    for s in fuentes:
        s.close()
    fin = time.monotonic() + max(0.0, espera)
    for s in fuentes:
        if s._th is not threading.current_thread():
            s._th.join(max(0.0, fin - time.monotonic()))
    return len(fuentes)


def dispositivo_grafica() -> str | None:
    """«d3d11va» (o «dxva2») si PyAV puede decodificar con la tarjeta gráfica en este equipo; None si no."""
    import os
    if not USAR_GRAFICA or os.environ.get("RECLAIMER_DECOD_GRAFICA") == "0":
        return None
    if not _DISPOSITIVO:
        disp = None
        try:
            from av.codec.hwaccel import hwdevices_available
            hay = set(hwdevices_available())
            disp = next((d for d in ("d3d11va", "dxva2") if d in hay), None)
        except Exception:  # noqa: BLE001 - PyAV sin aceleración: el procesador
            disp = None
        _DISPOSITIVO.append(disp)
    return _DISPOSITIVO[0]


def pesado(w: int, h: int, codec: str = "") -> bool:
    """¿Merece la tarjeta gráfica? Más que 1080p, o HEVC/AV1/VP9 desde 720p (caros con el procesador)."""
    if w * h > 1920 * 1088:
        return True
    return (codec or "").lower() in ("hevc", "h265", "av1", "libdav1d", "vp9") and w * h >= 1280 * 720


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
        self.hw: str | None = None                # tarjeta con la que decodifica («d3d11va»…) o None (procesador)
        self.hilos = 0                            # hilos del decodificador (diagnóstico y pruebas)
        self.convertidos = 0                      # fotogramas convertidos a RGBA (diagnóstico y pruebas)
        self._bateria = False
        self._t_want = 0.0
        self.a_tarjeta_tras = None                # segundos tras ▶ en que pasó a la tarjeta (diagnóstico)
        self.ultimo_salto_hecho = True
        self.ultimo_salto: tuple = ()             # (espera, saltar y decodificar, fotogramas) del último salto (ms)
        self._puede_hw = False                    # ¿este archivo se puede (y merece) decodificar con la tarjeta?
        self._t_play = 0.0                        # desde cuándo se reproduce (monotonic)
        self._th = threading.Thread(target=self._run, name="video_decode", daemon=True)
        with _VIVAS_LOCK:
            _VIVAS.add(self)                      # (🔓 cerrar_fuentes la encuentra esté donde esté)
        self._th.start()

    @property
    def cerrado(self) -> bool:
        return self._closed

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
            if playing and not self._playing:
                self._t_play = time.monotonic()
            self._playing = playing
            self._gen += 1
            self._t_want = time.perf_counter()
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
        """Lo que se decodifica por delante: AHEAD_S (la mitad con la batería) o menos si no cabe (1080p60 a todo
        tamaño)."""
        w, h = self._size
        cabe = CACHE_BYTES / max(1, w * h * 4)
        return min(AHEAD_S * (0.5 if self._bateria else 1.0), 0.6 * cabe / max(1.0, self._fps))

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
            lo, hi = self._want_t - ATRAS_S, self._want_t + self._ahead() + 1.0
            if self._playing and (self._pts[0] < lo or self._pts[-1] > hi):
                # reproduciendo: lo ya visto se suelta (queda ATRAS_S para pausar y dar un paso atrás al momento), y
                # también lo de saltos de antes muy por delante: la memoria no sube hasta el tope
                i, j = bisect.bisect_left(self._pts, lo), bisect.bisect_right(self._pts, hi)
                for p in self._pts[:i] + self._pts[j:]:
                    self._bytes -= len(self._data.pop(p)[3])
                self._pts = self._pts[i:j]
                self._recortar_segs()
                if pts not in self._data:
                    return False
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
                    if len(self._segs) > 32:      # (muchos saltos en pausa: los tramos que se tocan, juntos)
                        self._recortar_segs()
                        seg = next((s for s in self._segs if s[0] - 1e-9 <= pts <= s[1] + 1e-9), seg)
            seg[0] = min(seg[0], pts)
            seg[1] = max(seg[1], pts)
            return seg

    def _abrir(self, grafica: bool = True):
        """El contenedor y su pista de video: lo pesado con la tarjeta gráfica (si la hay y se deja); hilos con tope."""
        import av
        from . import energia
        cont = av.open(self.path)
        st = cont.streams.video[0]
        cc = st.codec_context
        w, h, codec = int(cc.width or 0), int(cc.height or 0), str(cc.name or "")
        self.hw = None
        self._puede_hw = bool(dispositivo_grafica() and pesado(w, h, codec))
        disp = dispositivo_grafica() if grafica and self._puede_hw else None
        if disp:
            try:
                from av.codec.hwaccel import HWAccel
                c2 = av.open(self.path, hwaccel=HWAccel(device_type=disp, allow_software_fallback=True))
                cont.close()
                cont, st = c2, c2.streams.video[0]
                self.hw = disp
            except Exception:  # noqa: BLE001 - la tarjeta no quiere: con el procesador
                self.hw = None
        st.thread_type = "AUTO"
        self.hilos = 1 if self.hw else energia.hilos_decodificar(h)
        st.codec_context.thread_count = self.hilos
        self._bateria = energia.en_bateria()
        self._cab_previos = max(2, min(BEHIND_N, int(BEHIND_BYTES / max(1.0, max(1, w) * max(1, h) * 1.5))))
        return cont, st

    def _convertir(self, fr, size) -> tuple:
        """Fotograma de PyAV → (ancho, alto, bytes RGBA) al tamaño del visor (enderezado si es vertical del móvil)."""
        w, h = size
        rot = int(getattr(fr, "rotation", 0) or 0) % 360
        self.rotation = rot
        # 🎨 sin etiqueta de color y de más de 576 líneas: BT.709, como lo verá cualquiera en lo EXPORTADO (que va
        # etiquetado BT.709 y lleva el mismo YUV). swscale, sin etiqueta, usaría BT.601 (verde 11,219,3 en vez de 0,186,0)
        kw = {}
        try:
            if int(fr.colorspace) == 2 and fr.height > 576:
                kw["src_colorspace"] = "ITU709"
        except Exception:  # noqa: BLE001 - PyAV sin el dato: como estaba
            kw = {}
        if rot in (90, 270):              # 📱 video vertical del móvil: se endereza
            f2 = fr.reformat(width=h, height=w, format="rgba", **kw)
        else:
            f2 = fr.reformat(width=w, height=h, format="rgba", **kw)
        arr = f2.to_ndarray()
        if rot:
            import numpy as np
            arr = np.ascontiguousarray(np.rot90(arr, k=rot // 90))
        self.convertidos += 1
        return arr.shape[1], arr.shape[0], arr.tobytes()

    def _run(self):
        cont = None
        grafica_ok = True                 # (si la tarjeta da errores con este archivo, se reabre con el procesador)
        self._cab_previos = BEHIND_N
        while retenido(self.path):        # 🔓 se está borrando o moviendo: no se abre hasta que acabe (o se cierre)
            with self._lock:
                if self._closed:
                    return
                self._lock.wait(0.1)
        try:
            from . import energia
            cont, st = self._abrir(grafica=energia.en_bateria())     # (en pausa, el procesador salta antes)
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
        atras = 0.0                       # margen extra al saltar (se aprende): ver abajo
        desde = None                      # al pasar a la tarjeta: saltar al final de lo ya decodificado (no a t)
        clave = None                      # la última imagen clave decodificada (pts)
        while True:
            a_tarjeta = False
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
                    # 🎞 reproduciendo un archivo pesado con el procesador y con lo de delante ya listo: se pasa a la
                    # tarjeta gráfica (sigue desde el final de lo decodificado: da tiempo de sobra)
                    a_tarjeta = (playing and self._puede_hw and not self.hw and grafica_ok
                                 and time.monotonic() - self._t_play > 0.3)
                    if a_tarjeta:
                        # (poco después de una imagen clave: la tarjeta empieza ahí y se pone al día en ~0,1 s, con
                        # 0,6 s por delante ya listos; si no, se espera a la próxima)
                        fin = next((b for a, b in self._segs if a - half <= t <= b + half), None)
                        a_tarjeta = fin is not None and clave is not None and atras <= fin - clave <= atras + 0.8
                        desde = fin + 1.0 / self._fps if a_tarjeta else None
                    if not a_tarjeta:
                        # (nada que hacer: dormido hasta la próxima petición —want() y close() despiertan—; antes se
                        # despertaba cada 50 ms aunque no hubiera nada: en reposo, CPU para nada)
                        self._lock.wait(0.5 if playing else 5.0)
                        continue
            if a_tarjeta:
                self.a_tarjeta_tras = round(time.monotonic() - self._t_play, 2)   # (diagnóstico: s tras ▶)
                try:
                    cont.close()
                    cont, st = self._abrir(grafica=True)
                except Exception:  # noqa: BLE001 - no se pudo: con el procesador, como estaba
                    grafica_ok = False
                    cont, st = self._abrir(grafica=False)
                dec = None
                continue
            # seguir la decodificación en curso si lo pedido está por delante (o dentro) de lo ya decodificado
            seguir = dec is not None and pos_dec >= 0 and t <= pos_dec + SEGUIR_S and (self._covered(t)
                                                                                    or t >= pos_dec - half)
            if seek_malo and dec is not None and pos_dec >= 0 and t >= pos_dec - half:
                seguir = True                     # (archivo sin saltos: hacia delante, decodificando)
            recien = False
            objetivo = t
            try:
                if not seguir:
                    if not playing and self.hw and not self._bateria:
                        cont.close()              # (en pausa, el procesador salta antes que la tarjeta)
                        cont, st = self._abrir(grafica=False)
                    if desde is not None and playing and desde > t:
                        objetivo = desde
                    desde = None
                    if seek_malo:                 # (hacia atrás en un archivo sin saltos: desde el principio)
                        cont.seek(0)
                    else:
                        cont.seek(max(0, int((max(0.0, objetivo - atras) + t0) / tb)), stream=st, backward=True,
                                  any_frame=False)
                    self.seeks += 1
                    self.ultimo_salto_hecho = False
                    t_salto = time.perf_counter()
                    n_dec = 0
                    dec = cont.decode(st)
                    seg = None
                    pos_dec = -1.0
                    recien = True
                    fallos += 1
                    if fallos > MAX_FALLOS:
                        self.error = "no da imagen en ese punto"
                        break
                n = 0
                guardar_desde = t - half
                # ⚡ en pausa, los de justo antes del pedido se guardan SIN convertir (pocos) y se convierten DESPUÉS de
                # enseñar el pedido: el salto ya no paga hasta 45 conversiones que quizá nadie mire
                previos: list = []
                for fr in dec:
                    if fr.time is None:
                        continue
                    pts = float(fr.time) - t0
                    pos_dec = pts
                    if fr.key_frame:
                        clave = pts
                    if recien:
                        n_dec += 1
                    if recien and n == 0 and pts > objetivo + half and objetivo - atras > 1e-3 and not seek_malo:
                        # 🎯 el salto cayó DESPUÉS de lo pedido: con fotogramas B (HEVC de x265, móviles) el índice va
                        # por el orden de decodificación y la imagen clave de justo después «parece» anterior. Se
                        # vuelve a saltar con más margen (5 fotogramas → 10 → 20…) y el margen se queda para este
                        # archivo (antes: «no da imagen en ese punto» y la pista volvía a los reproductores de siempre).
                        atras = 5.0 / self._fps if atras <= 0 else atras * 2
                        dec = None
                        break
                    if pts >= guardar_desde - 1e-6:
                        with self._lock:
                            ya = pts in self._data and size == self._size
                        if ya:                                    # (ya decodificado: no se convierte otra vez)
                            seg = self._extend_seg(seg, pts)
                        else:
                            w2, h2, data = self._convertir(fr, size)
                            if self._store(pts, w2, h2, data, size):
                                seg = self._extend_seg(seg, pts)
                            if recien and not self.ultimo_salto_hecho:
                                ahora = time.perf_counter()
                                self.ultimo_salto = (round((t_salto - self._t_want) * 1000, 1),
                                                     round((ahora - t_salto) * 1000, 1), n_dec)
                                self.t_listo = ahora      # (diagnóstico: cuándo quedó listo el pedido)
                                self.ultimo_salto_hecho = True
                        if previos:
                            # (antes de los anteriores, un respiro: la interfaz recoge y enseña el pedido sin
                            # pelearse por el GIL con estas conversiones; si mientras llega otra petición, ni se hacen)
                            with self._lock:
                                if self._gen == gen and not self._closed:
                                    self._lock.wait(RESPIRO_S)
                        for p0, f0 in reversed(previos):          # (del más cercano al más lejano)
                            with self._lock:
                                if self._gen != gen or self._closed:
                                    break
                            w2, h2, data = self._convertir(f0, size)
                            if self._store(p0, w2, h2, data, size):
                                seg = self._extend_seg(seg, p0)
                        previos = []
                    else:
                        seg = None                # (este no se guarda ahora: el tramo seguido se corta aquí)
                        if not playing:
                            previos.append((pts, fr))
                            if len(previos) > self._cab_previos:
                                del previos[0]
                    n += 1
                    with self._lock:
                        cambio = self._gen != gen or self._closed
                        if cambio and not self._closed and self._playing == playing and self._size == size:
                            # una petición nueva que sigue por delante de lo que se está decodificando (reproducir
                            # pide cada 15 ms): se sigue sin cortar. Antes se cortaba en cada fotograma y, con una
                            # imagen clave a más de 1 s, se volvía a saltar sin llegar nunca («no da imagen»).
                            t2 = self._tope(self._want_t)
                            if pos_dec - half <= t2 <= max(pos_dec, t) + SEGUIR_S:
                                t, gen, cambio = t2, self._gen, False
                                hasta = t + (self._ahead() if playing else 0.0)
                                guardar_desde = t - half
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
                if self.hw and grafica_ok:        # (la tarjeta no puede con este archivo: con el procesador)
                    grafica_ok = False
                    try:
                        cont.close()
                        cont, st = self._abrir(grafica=False)
                        continue
                    except Exception:  # noqa: BLE001
                        self.error = "no se puede volver a abrir"
                        break
                fallos += 1
                if fallos > MAX_FALLOS:
                    self.error = "el archivo da errores al decodificar"
                    break
                time.sleep(0.01)
        try:
            cont.close()
        except Exception:  # noqa: BLE001
            pass
