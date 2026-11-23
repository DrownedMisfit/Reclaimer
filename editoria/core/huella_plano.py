"""
🧬 HUELLA VISUAL POR PLANO (fase 14): saber si dos trozos de video enseñan el MISMO momento, aunque vengan de archivos
distintos (una cinemática que también sale en un tráiler, una captura que ya está en otra grabación…).

  · Cada video se mira a 8 fotogramas por segundo y de cada fotograma se guardan DOS dHash de 64 bits (la imagen a
    9×8 en gris: ¿cada píxel es más claro que el de su derecha?): el del contenido SIN bandas negras y el de su centro
    (85 %), para que la misma escena con bandas o con un poco de zoom siga casando. Aguanta otra compresión, otro tamaño y retoques de
    brillo; no mira el sonido. Los fotogramas casi lisos (negro, blanco, un fundido) no cuentan: se parecen a todo.
  · Se calcula en la LECTURA ÚNICA (ai/lectura_unica.py, rama «huella»: casi gratis al lado de descodificar) y se
    guarda por archivo en la caché «huellas» (100–170 KB por hora de video). Sin lectura única, `calcular()` lo hace
    con su propio FFmpeg (pruebas, o quien lo necesite ya).
  · Plano = tramo entre dos cortes de escena (core/scene_cuts.py, la misma detección que «Escenas sin usar»).
  · Dos trozos son el mismo momento si casan (distancia ≤ UMBRAL bits) al menos MIN_VOTOS fotogramas DISTINTOS de
    cada lado, con el MISMO desfase de tiempo y a lo largo de al menos MIN_TRAMO segundos (un parecido suelto, o un
    plano quieto parecido unos instantes, no basta).

  cargar(path) -> Huella | None             lo guardado (None: aún no se miró; nunca espera)
  calcular(path, duracion, cancelled)        lo calcula ya con FFmpeg (y lo guarda)
  planos(path, duracion) -> [(a, b)]         los planos del archivo (si ya se miraron sus escenas; si no, [])
  Indice(trozos)                             índice de fotogramas para buscar coincidencias sin comparar todo con todo
  coincidencias(indice, hashes) -> (qi, di)  qué fotogramas consultados casan con cuáles del índice
  votar(ta, tb) -> (votos, desde, hasta)     ¿casan con un desfase constante? (y qué tramo de «a» cubre)
  segmentos(tq, td) -> [(a, b)]              los tramos de «q» que casan con desfase constante (varios a la vez)
"""
from __future__ import annotations

import os
import subprocess
import threading

import numpy as np

from . import media as media_tools
from .paths import cache_dir

STEP = 0.125                # segundos entre fotogramas mirados (8 por segundo: dos copias del mismo video casi nunca
                            # caen en el mismo instante; a 4 por segundo, con mucho movimiento, ya no casaban)
W, H = 40, 24               # lo que llega de FFmpeg por fotograma (gris pequeño): de ahí salen los dos dHash 8×8
FILTER = f"fps={1 / STEP:g},scale={W}:{H}:flags=area,format=rgb24"
NEGRO = 18                  # una fila o columna del borde con todo por debajo de esto es banda negra
CENTRO = 0.85               # el 2.º hash mira el centro (85 % de alto y ancho): aguanta un zoom del 80–90 %
# Barrido con videos reales (21/11, revisiones de Fable): con 12 bits y 3 votos, el 20–31 % de los trozos de un video
# «casaba» con otro distinto (el dHash 9×8 confunde cualquier «cielo arriba, suelo abajo»). v3: cada fotograma lleva
# DOS hashes (el contenido sin bandas negras y su centro) y se cruzan todos con todos. Con 4 bits, 5 fotogramas
# DISTINTOS de cada lado y 1 s de tramo: ≤ 1 % de falsos; la misma escena recomprimida, con otro brillo o un texto
# encima, al 100 %; con bandas negras (arriba y abajo o a los lados) 90–97 % (antes 1–2 %); con zoom al 80–90 % ~40 %
# (antes 3–21 %); desfasada (otra codificación) ~86 %.
UMBRAL = 4                  # bits distintos (de 64) para decir «es el mismo fotograma» (dos al azar: ~32)
LISO = 3.0                  # desviación de gris por debajo de la cual el fotograma no cuenta (negro, blanco, fundido)
CAP = 48                    # como mucho tantas coincidencias por fotograma y banda (un plano quieto larguísimo)
MIN_VOTOS = 5               # fotogramas DISTINTOS (de cada lado) que casan con el mismo desfase
MIN_TRAMO = 1.0             # s: lo que casa tiene que durar al menos esto (8 fotogramas seguidos casi iguales no son
                            # 8 pruebas: a 8 por segundo, los vecinos se parecen siempre)
VERSION = 3                 # (v3: sin bandas + centro; las huellas v2 se vuelven a calcular)

_MEM: dict[str, tuple] = {}          # path normalizado -> (clave de caché, Huella | None)
_MEM_LOCK = threading.Lock()
generacion = 0                       # sube cada vez que se guarda una huella nueva (quien memoriza, recalcula)


class Huella:
    """Los fotogramas mirados de un archivo: t (segundos), h (dHash del contenido sin bandas negras), hc (dHash de su
    centro) y ok (no es liso)."""
    __slots__ = ("t", "h", "hc", "ok")

    def __init__(self, t, h, ok, hc=None):
        self.t = np.asarray(t, np.float32)
        self.h = np.asarray(h, np.uint64)
        self.hc = np.asarray(hc if hc is not None else h, np.uint64)
        self.ok = np.asarray(ok, bool)

    def de(self, sel) -> tuple[np.ndarray, np.ndarray]:
        """(tiempos, hashes) de esos fotogramas (máscara o índices), cada uno DOS veces: su hash y el de su centro (así
        se cruzan todos con todos: entero con entero, entero con centro…)."""
        t = self.t[sel]
        return np.concatenate([t, t]), np.concatenate([self.h[sel], self.hc[sel]])

    def tramo(self, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
        """(tiempos, hashes) de los fotogramas útiles entre a y b (segundos del archivo), con sus dos hashes."""
        i0 = int(np.searchsorted(self.t, a - 1e-3, "left"))
        i1 = int(np.searchsorted(self.t, b + 1e-3, "right"))
        return self.de(np.arange(i0, i1)[self.ok[i0:i1]])

    def __len__(self):
        return len(self.t)


# ------------------------------------------------------------------ cálculo
def _area(img: np.ndarray, h: int, w: int) -> np.ndarray:
    """(N, Y, X) → (N, h, w) por media de áreas (Y ≥ h, X ≥ w)."""
    _n, Y, X = img.shape
    ys = (np.arange(h) * Y) // h
    xs = (np.arange(w) * X) // w
    cy = np.diff(np.append(ys, Y)).astype(np.float32)
    cx = np.diff(np.append(xs, X)).astype(np.float32)
    a = np.add.reduceat(img, ys, axis=1) / cy[None, :, None]
    return np.add.reduceat(a, xs, axis=2) / cx[None, None, :]


def _dhash(g: np.ndarray) -> np.ndarray:
    bits = (g[:, :, 1:] > g[:, :, :-1]).reshape(len(g), 64)
    return np.packbits(bits, axis=1).view(">u8").reshape(-1).astype(np.uint64)


def cajas(g: np.ndarray) -> np.ndarray:
    """Por fotograma, (fila0, fila1, col0, col1) del contenido sin bandas negras: filas/columnas del borde con todo por
    debajo de NEGRO, solo si arriba y abajo (o izquierda y derecha) miden casi lo mismo (las bandas son simétricas: una
    escena oscura arriba no se recorta) y queda al menos un tercio."""
    _n, Hh, Ww = g.shape

    def borde(neg, L):
        todo = neg.all(axis=1)
        a = np.argmin(neg, axis=1)
        b = np.argmin(neg[:, ::-1], axis=1)
        a[todo] = 0
        b[todo] = 0
        m = np.minimum(a, b)
        return np.where((np.abs(a - b) <= max(1, L // 20)) & (m >= 1) & (L - 2 * m >= L // 3), m, 0)
    mr = borde(g.max(axis=2) <= NEGRO, Hh)
    mc = borde(g.max(axis=1) <= NEGRO, Ww)
    return np.stack([mr, Hh - mr, mc, Ww - mc], axis=1)


def hashes_de(gris: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """gris: (N, H, W) uint8 → (dHash del contenido sin bandas, dHash de su centro, ok). Vectorizado por grupos de
    fotogramas con las mismas bandas (casi siempre uno o dos)."""
    n = len(gris)
    if n == 0:
        z = np.zeros(0, np.uint64)
        return z, z, np.zeros(0, bool)
    cj = cajas(gris)
    g = gris.astype(np.float32)
    h1 = np.zeros(n, np.uint64)
    h2 = np.zeros(n, np.uint64)
    ok = np.zeros(n, bool)
    claves, inv = np.unique(cj, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    for k, (r0, r1, c0, c1) in enumerate(claves):
        sel = np.flatnonzero(inv == k)
        sub = g[sel, r0:r1, c0:c1]
        h1[sel] = _dhash(_area(sub, 8, 9))
        Y, X = int(r1 - r0), int(c1 - c0)
        dy, dx = int(round(Y * (1 - CENTRO) / 2)), int(round(X * (1 - CENTRO) / 2))
        if Y - 2 * dy < 8 or X - 2 * dx < 9:            # (franja fina sobre negro: su centro no da 8×9 → el contenido entero)
            dy = dx = 0
        h2[sel] = _dhash(_area(sub[:, dy:Y - dy, dx:X - dx], 8, 9))
        ok[sel] = sub.reshape(len(sel), -1).std(axis=1) >= LISO
    return h1, h2, ok


class Acumulador:
    """Recibe los fotogramas pequeños (rgb24, W×H) de la lectura única, uno a uno; guarda solo su gris (1 byte por
    píxel: ~28 MB por hora de video mientras dura la lectura)."""
    _PESOS = np.array([0.299, 0.587, 0.114], np.float32)

    def __init__(self):
        self._grises: list[np.ndarray] = []

    def add(self, buf: bytes):
        rgb = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        self._grises.append((rgb.astype(np.float32) @ self._PESOS).astype(np.uint8))

    def resultado(self) -> Huella:
        n = len(self._grises)
        g = np.stack(self._grises) if n else np.zeros((0, H, W), np.uint8)
        h, hc, ok = hashes_de(g)
        return Huella(np.arange(n, dtype=np.float32) * STEP, h, ok, hc)


def _ruta(path: str) -> str:
    return os.path.join(str(cache_dir("huellas")), f"{media_tools.cache_key(path)}_v{VERSION}.npz")


def guardar(path: str, hu: Huella):
    global generacion
    out = _ruta(path)
    tmp = out + ".tmp.npz"
    try:
        np.savez_compressed(tmp, t=hu.t, h=hu.h, hc=hu.hc, ok=hu.ok)
        os.replace(tmp, out)
    except OSError:
        return
    with _MEM_LOCK:
        _MEM[os.path.normcase(os.path.abspath(path))] = (out, hu)
        generacion += 1


def hecho(path: str) -> bool:
    return os.path.exists(_ruta(path))


def cargar(path: str) -> Huella | None:
    """La huella guardada de ese archivo, o None si aún no se miró. Nunca calcula ni espera (memoria en RAM)."""
    k = os.path.normcase(os.path.abspath(path))
    ruta = _ruta(path)
    with _MEM_LOCK:
        m = _MEM.get(k)
        if m is not None and m[0] == ruta and m[1] is not None:
            return m[1]
    try:
        with np.load(ruta) as z:
            hu = Huella(z["t"], z["h"], z["ok"], z["hc"] if "hc" in z.files else None)
    except (OSError, ValueError, KeyError):
        return None
    with _MEM_LOCK:
        _MEM[k] = (ruta, hu)
    return hu


def calcular(path: str, duracion: float = 0.0, cancelled=None) -> Huella | None:
    """La calcula ya con su propio FFmpeg (sin la lectura única) y la guarda. None si no se pudo leer."""
    n = W * H * 3
    p = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-skip_loop_filter", "all", "-i", path,
                          "-an", "-vf", FILTER, "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    acc = Acumulador()
    try:
        while True:
            if cancelled is not None and cancelled():
                p.kill()
                return None
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            acc.add(buf)
    finally:
        p.stdout.close()
        p.wait()
    if p.returncode != 0 and not acc._grises:
        return None
    hu = acc.resultado()
    guardar(path, hu)
    return hu


# ------------------------------------------------------------------ planos
def planos(path: str, duracion: float) -> list[tuple[float, float]]:
    """Los planos del archivo (tramos entre cortes de escena) si sus escenas ya se miraron (lectura única); si no,
    []. Nunca lee el video."""
    from . import scene_cuts
    whole = scene_cuts.whole_scores(path)
    if whole is None or not duracion:
        return []
    th = scene_cuts.THRESHOLD["normal"]
    cuts: list[float] = []
    for t, sc in whole:
        if sc < th or t < scene_cuts.MIN_GAP or duracion - t < scene_cuts.MIN_GAP:
            continue
        if cuts and t - cuts[-1] < scene_cuts.MIN_GAP:
            continue
        cuts.append(float(t))
    edges = [0.0] + cuts + [float(duracion)]
    return [(round(a, 3), round(b, 3)) for a, b in zip(edges, edges[1:]) if b - a > 0.05]


# ------------------------------------------------------------------ búsqueda de coincidencias
def popcount(x: np.ndarray) -> np.ndarray:
    return np.bitwise_count(x)


class Indice:
    """Fotogramas de muchos trozos, listos para buscar: 4 bandas de 16 bits ordenadas. Dos fotogramas a ≤ 3 bits
    comparten seguro una banda; con más diferencia casi siempre alguna (y hay muchos fotogramas por trozo)."""

    def __init__(self, grupo: np.ndarray, t: np.ndarray, h: np.ndarray):
        self.grupo = np.asarray(grupo, np.int64)      # a qué trozo pertenece cada fotograma
        self.t = np.asarray(t, np.float32)
        self.h = np.asarray(h, np.uint64)
        self._bandas = []
        for b in range(4):
            k = ((self.h >> np.uint64(16 * b)) & np.uint64(0xFFFF)).astype(np.int64)
            o = np.argsort(k, kind="stable")
            self._bandas.append((k[o], o))

    def __len__(self):
        return len(self.h)


def coincidencias(ind: Indice, hq: np.ndarray, umbral: int = UMBRAL) -> tuple[np.ndarray, np.ndarray]:
    """Pares (i de la consulta, j del índice) con distancia ≤ umbral. Sin bucles por fotograma: searchsorted."""
    hq = np.asarray(hq, np.uint64)
    if len(hq) == 0 or len(ind) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    qs, ds = [], []
    for b, (ks, orden) in enumerate(ind._bandas):
        kq = ((hq >> np.uint64(16 * b)) & np.uint64(0xFFFF)).astype(np.int64)
        lo = np.searchsorted(ks, kq, "left")
        hi = np.searchsorted(ks, kq, "right")
        cnt = np.minimum(hi - lo, CAP)
        tot = int(cnt.sum())
        if tot == 0:
            continue
        qi = np.repeat(np.arange(len(hq)), cnt)
        base = np.repeat(lo - np.concatenate(([0], np.cumsum(cnt)[:-1])), cnt)
        pos = base + np.arange(tot)
        qs.append(qi)
        ds.append(orden[pos])
    if not qs:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    qi = np.concatenate(qs)
    dj = np.concatenate(ds)
    par = np.unique(qi * len(ind) + dj)
    qi, dj = par // len(ind), par % len(ind)
    ok = popcount(hq[qi] ^ ind.h[dj]) <= umbral
    return qi[ok], dj[ok]


def votar(ta: np.ndarray, tb: np.ndarray, min_votos: int = MIN_VOTOS) -> tuple[int, float, float]:
    """Fotogramas que casan (ta[k] ↔ tb[k]): ¿con el MISMO desfase (± un fotograma)? Devuelve (votos del mejor
    desfase, primer y último tiempo de «a» que cubre). Votos < min_votos = no es el mismo momento."""
    if len(ta) == 0:
        return 0, 0.0, 0.0
    d = np.round((np.asarray(tb, np.float64) - np.asarray(ta, np.float64)) / STEP).astype(np.int64)
    vals, cnt = np.unique(d, return_counts=True)
    if len(vals) == 1:
        mejor = vals[0]
    else:
        # cada desfase suma también los de al lado (± 1 fotograma: las dos grabaciones no empiezan en el mismo instante)
        idx = {int(v): int(c) for v, c in zip(vals, cnt)}
        mejor = max(idx, key=lambda v: (idx[v] + idx.get(v - 1, 0) + idx.get(v + 1, 0), idx[v]))
    sel = np.abs(d - mejor) <= 1
    # un mismo fotograma de «a» puede casar con varios de «b» (plano quieto): cuenta una vez
    tsel = np.unique(np.asarray(ta)[sel])
    votos = int(len(tsel))
    if votos == 0:
        return 0, 0.0, 0.0
    return votos, float(tsel.min()), float(tsel.max())


def segmentos(tq, td, min_votos: int = MIN_VOTOS, hueco: float = 1.0,
              min_tramo: float = MIN_TRAMO) -> list[tuple[float, float]]:
    """Coincidencias entre dos archivos (tq[k] ↔ td[k], segundos) → los tramos de «q» que enseñan lo mismo con un
    desfase constante. Puede haber varios (un tráiler reutiliza varios planos de la misma cinemática). Un desfase (± un
    fotograma: dos codificaciones no caen en el mismo instante) vale si casan al menos min_votos fotogramas DISTINTOS
    de «q» y otros tantos distintos de «d», repartidos en al menos min_tramo segundos. Lo que vale se junta en tramos
    (cortados donde hay más de «hueco» segundos sin nada), y cada tramo cumple lo mismo por sí solo."""
    if len(tq) == 0:
        return []
    tq = np.asarray(tq, np.float64)
    td = np.asarray(td, np.float64)
    d = np.round((td - tq) / STEP).astype(np.int64)
    fq = np.round(tq / STEP).astype(np.int64)
    fd = np.round(td / STEP).astype(np.int64)
    vals, cnt = np.unique(d, return_counts=True)
    cand = vals[cnt >= 2]
    if len(cand) > 400:                                  # (los desfases con más coincidencias; el resto es ruido)
        cand = vals[np.argsort(-cnt)[:400]]
    elegidos = np.zeros(len(d), bool)
    for v in cand:
        sel = np.abs(d - v) <= 1
        uq = np.unique(fq[sel])
        if len(uq) < min_votos or (uq[-1] - uq[0]) * STEP < min_tramo:
            continue
        if len(np.unique(fd[sel])) < min_votos:
            continue
        elegidos |= sel
    if not elegidos.any():
        return []
    out = []
    fr = np.unique(fq[elegidos])
    for run in np.split(fr, np.flatnonzero(np.diff(fr) * STEP > hueco) + 1):
        if len(run) < min_votos or (run[-1] - run[0]) * STEP < min_tramo:
            continue
        dentro = elegidos & (fq >= run[0]) & (fq <= run[-1])
        if len(np.unique(fd[dentro])) >= min_votos:
            out.append((float(run[0] * STEP), float(run[-1] * STEP) + STEP))
    return out


def votos_necesarios(n_a: int, n_b: int) -> int:
    """Fotogramas de un CLIP que tienen que repetir un tramo ya validado por segmentos() para marcarlo: casi todo lo
    suyo si es corto, MIN_VOTOS si es largo."""
    n = min(n_a, n_b)
    return max(2, min(MIN_VOTOS, (n + 1) // 2))
