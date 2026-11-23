"""
🔁 MATERIAL REPETIDO (fase 4 + fase 14 «huella por plano»): qué clips de la línea de tiempo enseñan un momento que ya
sale en otro clip, aunque venga de OTRO archivo (una cinemática que también sale en un tráiler), y cómo cambiarlo.
Sin Qt: lo usan la línea de tiempo (franja + tooltip + «Cambiar»), Medios (bandejas), Autocompletar, la Primera
versión (B-roll) y lo que venga después (material por frases).

  · Mismo archivo: dos clips de video cuyo tramo del archivo se solapa (al menos 0,3 s, o un 30 % del más corto). Una
    imagen puesta dos veces también cuenta.
  · Otro archivo: con la huella por plano (core/huella_plano.py), si unos cuantos fotogramas casan con el mismo desfase.
    Si un archivo aún no tiene huella, solo se mira lo del mismo archivo (y la huella se pide a la cola, sin esperas).

  mapa(project, missing, clave) -> {clip_id: [Rep]}            (memorizado por «clave»: la versión del proyecto)
  tramo_en_linea(clip, a, b) -> (t0, t1)                       tramo del archivo → segundos de la línea de tiempo
  texto_tooltip(project, clip_id, reps) -> str                 «Este tramo ya sale en…»
  bandejas(project, missing) -> {"no_usados": [...], "usados_2": [(mid, veces)]}
  usados_con_huella(project, media_id, excluir) -> [(a, b)]    lo usado de ese archivo + lo que repite otros archivos
  Tomados(project)                                             registro de tramos para el B-roll (broll_selection.claim)
  elegir_otro_tramo(project, clip_id, missing) -> (media_id, source_in) | None
  cambiar_por_no_usado(ctrl, clip_id) -> str                   lo aplica (un Ctrl+Z) y dice qué hizo
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

from . import huella_plano as HP
from .model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO

EPS = 1e-3
SOLAPE_MIN = 0.3        # s del archivo en común para que dos clips del mismo archivo cuenten como repetidos
SOLAPE_FRAC = 0.3       # … o este trozo del más corto (clips muy cortos)
PLANO_MAX = 8.0         # un plano repetido hasta este largo cuenta ENTERO como usado; uno más largo, solo ± MARGEN
MARGEN = 2.0
MAX_REPS = 4            # otros clips que se apuntan por clip (para el tooltip; la marca no depende de esto)
VECINOS = 8             # mismo archivo: con cuántos de los siguientes se compara cada clip
NOMBRE_CAMBIAR = "Cambiar por otro tramo no usado"


@dataclass
class Rep:
    otro: str            # id del otro clip
    a: float             # tramo repetido, en segundos del ARCHIVO de este clip
    b: float
    otro_archivo: bool   # True: el otro clip es de otro archivo (lo vio la huella)


# ------------------------------------------------------------------ qué clips miran
def _visuales(project, missing=()) -> list:
    """[(clip, media)] de las pistas de video que enseñan un archivo (sin textos, generados ni escenas)."""
    vids = {t.id for t in project.tracks if t.kind == TRACK_VIDEO}
    escenas = set()
    if getattr(project, "scenes", None):
        try:
            from . import escena_clip
            escenas = {mid for mid in project.media if escena_clip.es_medio_escena(project, mid)}
        except Exception:  # noqa: BLE001
            escenas = set()
    out = []
    for c in project.clips.values():
        if c.track_id not in vids or c.text is not None:
            continue
        m = project.media.get(c.media_id)
        if m is None or m.kind not in (KIND_VIDEO, KIND_IMAGE) or m.id in missing or m.gen or m.id in escenas:
            continue
        out.append((c, m))
    return out


class _ClipFoto:
    """Lo que el mapa necesita de un clip, copiado (el cálculo puede ir en otro hilo sin leer el proyecto)."""
    __slots__ = ("id", "media_id", "source_in", "src_len")

    def __init__(self, c):
        self.id, self.media_id = c.id, c.media_id
        self.source_in, self.src_len = float(c.source_in), float(c.src_len)


class _MedioFoto:
    __slots__ = ("id", "path", "kind")

    def __init__(self, m):
        self.id, self.path, self.kind = m.id, m.path, m.kind


def instantanea(project, missing=()) -> list:
    """[(clip, medio)] copiados de lo que el mapa mira (rápido, en el hilo de la interfaz)."""
    return [(_ClipFoto(c), _MedioFoto(m)) for c, m in _visuales(project, missing)]


def _rango(c) -> tuple[float, float]:
    a = float(c.source_in)
    return a, a + max(0.0, float(c.src_len))


def tramo_en_linea(c, a: float, b: float) -> tuple[float, float]:
    """Un tramo del archivo (a, b) → (t0, t1) en la línea de tiempo, recortado al clip (velocidad y al revés)."""
    if c.speed <= 0:
        return c.start, c.end
    if c.reverse:
        l0 = (c.source_in + c.src_len - b) / c.speed
        l1 = (c.source_in + c.src_len - a) / c.speed
    else:
        l0 = (a - c.source_in) / c.speed
        l1 = (b - c.source_in) / c.speed
    l0 = min(max(l0, 0.0), c.duration)
    l1 = min(max(l1, 0.0), c.duration)
    return c.start + min(l0, l1), c.start + max(l0, l1)


# ------------------------------------------------------------------ el mapa de repetidos
_MEMO: dict = {"clave": None, "mapa": {}}


def mapa(project, missing=(), clave=None) -> dict[str, list[Rep]]:
    """{clip_id: [Rep]} de los clips que repiten material. Con «clave» (p. ej. (ctrl.rev, id(project))), se memoriza:
    pintar no recalcula nada mientras el proyecto no cambie ni llegue una huella nueva."""
    if clave is not None:
        k = (clave, HP.generacion)
        if _MEMO["clave"] == k:
            return _MEMO["mapa"]
    out = _calcular_mapa(project, missing)
    if clave is not None:
        _MEMO["clave"], _MEMO["mapa"] = (clave, HP.generacion), out
    return out


def _añadir(out: dict, cid: str, rep: Rep):
    lst = out.setdefault(cid, [])
    for r in lst:
        if r.otro == rep.otro:
            r.a, r.b = min(r.a, rep.a), max(r.b, rep.b)
            return
    if len(lst) < MAX_REPS:                           # (para el tooltip bastan unos pocos: la marca ya está)
        lst.append(rep)


def _vale_solape(a0, a1, b0, b1) -> bool:
    com = min(a1, b1) - max(a0, b0)
    return com > 0.04 and com >= min(SOLAPE_MIN, SOLAPE_FRAC * min(a1 - a0, b1 - b0))


def _mismo_archivo(out: dict, lst: list):
    """Clips del mismo archivo cuyo tramo se solapa. Ordenados por inicio en el archivo: cada uno se compara con los
    VECINOS siguientes (como mucho VECINOS) y con el que llega más lejos de los anteriores: O(n log n) aunque haya
    cientos de clips del mismo trozo."""
    if lst[0][1].kind == KIND_IMAGE:                  # una imagen puesta dos (o más) veces
        for k, (c, _m) in enumerate(lst):
            for o, _m2 in (lst[k + 1:] + lst[:k])[:MAX_REPS]:
                _añadir(out, c.id, Rep(o.id, 0.0, 0.0, False))
        return
    lst = sorted(lst, key=lambda x: float(x[0].source_in))
    lejos = None                                      # el anterior que llega más lejos en el archivo
    for i, (c, _m) in enumerate(lst):
        a0, a1 = _rango(c)
        if lejos is not None:
            b0, b1 = _rango(lejos)
            if _vale_solape(a0, a1, b0, b1):
                x0, x1 = max(a0, b0), min(a1, b1)
                _añadir(out, c.id, Rep(lejos.id, x0, x1, False))
                _añadir(out, lejos.id, Rep(c.id, x0, x1, False))
        for o, _m2 in lst[i + 1:i + 1 + VECINOS]:
            b0, b1 = _rango(o)
            if b0 >= a1 - EPS:
                break
            if _vale_solape(a0, a1, b0, b1):
                x0, x1 = max(a0, b0), min(a1, b1)
                _añadir(out, c.id, Rep(o.id, x0, x1, False))
                _añadir(out, o.id, Rep(c.id, x0, x1, False))
        if lejos is None or a1 > _rango(lejos)[1]:
            lejos = c


def _calcular_mapa(project, missing=()) -> dict[str, list[Rep]]:
    return calcular_mapa_de(instantanea(project, missing))


def calcular_mapa_de(vis: list) -> dict[str, list[Rep]]:
    """El mapa a partir de una instantánea (instantanea()): no toca el proyecto, se puede llamar en otro hilo."""
    out: dict[str, list[Rep]] = {}
    # 1) mismo archivo
    por_medio: dict[str, list] = {}
    for c, m in vis:
        por_medio.setdefault(m.id, []).append((c, m))
    for lst in por_medio.values():
        if len(lst) >= 2:
            _mismo_archivo(out, lst)
    # 2) otro archivo (huella): primero se cruzan los FOTOGRAMAS usados de cada archivo (cada uno una vez, aunque lo
    #    enseñen cien clips) y luego cada clip mira cuántos de los suyos ya salen desde otro archivo
    medios = []                                       # [(m, huella, [(clip, i0, i1)])]
    for mid, lst in por_medio.items():
        m = lst[0][1]
        if m.kind != KIND_VIDEO:
            continue
        hu = HP.cargar(m.path)
        if hu is None or not len(hu):
            continue
        cs = []
        for c, _m in lst:
            a, b = _rango(c)
            i0 = int(np.searchsorted(hu.t, a - 1e-3, "left"))
            i1 = int(np.searchsorted(hu.t, b + 1e-3, "right"))
            if i1 > i0:
                cs.append((c, i0, i1))
        if cs:
            medios.append((m, hu, cs))
    if len(medios) < 2:
        return out
    grupos, ts, hs, cubre = [], [], [], []
    for k, (m, hu, cs) in enumerate(medios):
        dif = np.zeros(len(hu) + 1, np.int32)
        for _c, i0, i1 in cs:
            dif[i0] += 1
            dif[i1] -= 1
        cub = np.cumsum(dif[:-1]) > 0
        cubre.append(cub)
        t2, h2 = hu.de(np.flatnonzero(cub & hu.ok))     # (cada fotograma con sus dos hashes)
        grupos.append(np.full(len(t2), k, np.int64))
        ts.append(t2)
        hs.append(h2)
    ind = HP.Indice(np.concatenate(grupos), np.concatenate(ts), np.concatenate(hs))
    qi, dj = HP.coincidencias(ind, ind.h)
    gq, gd = ind.grupo[qi], ind.grupo[dj]
    sel = gq != gd
    qi, dj, gq, gd = qi[sel], dj[sel], gq[sel], gd[sel]
    if not len(qi):
        return out
    M = len(medios)
    rep = [np.zeros(len(hu), bool) for _m, hu, _cs in medios]          # fotograma que ya sale desde otro archivo
    socio = [np.full(len(hu), -1, np.int64) for _m, hu, _cs in medios]  # (de qué archivo: para el tooltip)
    socio_t = [np.zeros(len(hu), np.float32) for _m, hu, _cs in medios]
    par = gq * M + gd
    orden = np.argsort(par, kind="stable")
    par, qi, dj = par[orden], qi[orden], dj[orden]
    for trozo in np.split(np.arange(len(par)), np.flatnonzero(np.diff(par)) + 1):
        x, y = divmod(int(par[trozo[0]]), M)
        tq, td = ind.t[qi[trozo]], ind.t[dj[trozo]]
        for a, b in HP.segmentos(tq, td):
            hu = medios[x][1]
            i0 = int(np.searchsorted(hu.t, a - 1e-3, "left"))
            i1 = int(np.searchsorted(hu.t, b - HP.STEP + 1e-3, "right"))
            rep[x][i0:i1] |= cubre[x][i0:i1]
            dentro = (tq >= a - 1e-3) & (tq <= b)
            fi = np.round(tq[dentro] / HP.STEP).astype(np.int64)
            socio[x][fi] = y
            socio_t[x][fi] = td[dentro]
    buscadores: dict[int, _Buscador] = {}
    for x, (m, hu, cs) in enumerate(medios):
        if not rep[x].any():
            continue
        suma = np.concatenate(([0], np.cumsum(rep[x])))
        ok = np.concatenate(([0], np.cumsum(hu.ok)))
        for c, i0, i1 in cs:
            n = int(suma[i1] - suma[i0])
            if n == 0 or n < HP.votos_necesarios(int(ok[i1] - ok[i0]), int(ok[i1] - ok[i0])):
                continue
            idx = np.flatnonzero(rep[x][i0:i1]) + i0
            a, b = float(hu.t[idx[0]]), float(hu.t[idx[-1]]) + HP.STEP
            con = idx[socio[x][idx] >= 0]
            if not len(con):
                continue
            k = int(con[len(con) // 2])
            y = int(socio[x][k])
            if y not in buscadores:
                buscadores[y] = _Buscador(medios[y][2])
            otro = buscadores[y].clip_en(float(socio_t[x][k]))
            if otro is not None:
                _añadir(out, c.id, Rep(otro.id, a, b, True))
    return out


class _Buscador:
    """Los clips de un archivo ordenados por inicio en el archivo: cuál enseña el segundo t (bisect, sin recorrerlos
    todos)."""

    def __init__(self, cs: list):
        cl = sorted((c for c, _i0, _i1 in cs), key=lambda c: float(c.source_in))
        self.clips = cl
        self.ini = np.array([float(c.source_in) for c in cl])

    def clip_en(self, t: float):
        if not self.clips:
            return None
        j = int(np.searchsorted(self.ini, t + HP.STEP, "right")) - 1
        for k in range(max(0, j), max(-1, j - VECINOS * 4), -1):
            a, b = _rango(self.clips[k])
            if a - HP.STEP <= t <= b + HP.STEP:
                return self.clips[k]
        return self.clips[min(max(j, 0), len(self.clips) - 1)]


def _nombre_pista(project, track_id: str) -> str:
    vids = [t for t in project.tracks if t.kind == TRACK_VIDEO]
    for k, t in enumerate(reversed(vids), 1):         # (la de abajo es V1, como en la cabecera)
        if t.id == track_id:
            return f"V{k}"
    return "?"


def texto_tooltip(project, clip_id: str, reps: list[Rep], fps: float = 30.0) -> str:
    """«Este tramo ya sale en…» con dónde está cada otro clip (archivo, pista y minuto)."""
    lineas = []
    for r in reps[:6]:
        o = project.clips.get(r.otro)
        if o is None:
            continue
        m = project.media.get(o.media_id)
        nombre = m.name if m else "?"
        donde = f"pista {_nombre_pista(project, o.track_id)}, en {_mmss(o.start)}"
        if r.otro_archivo:
            lineas.append(f"• «{nombre}» ({donde}): el mismo momento, de otro archivo")
        else:
            lineas.append(f"• «{nombre}» ({donde}): el mismo tramo del archivo")
    if len(reps) > 6:
        lineas.append(f"• y {len(reps) - 6} más")
    return ("Material repetido: este tramo ya sale en otro clip.\n" + "\n".join(lineas) +
            f"\nEl botón de la esquina (o el clic derecho → «{NOMBRE_CAMBIAR}») lo cambia por un plano que aún "
            "no sale, del mismo archivo o de su carpeta (un Ctrl+Z).")


def _mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


# ------------------------------------------------------------------ bandejas de Medios
def apariciones(project) -> dict[str, int]:
    """{media_id: veces que sale}. Un clip partido en dos (seguido en la línea y en el archivo, en la misma pista)
    cuenta una vez; el sonido de un video (vinculado) no cuenta aparte."""
    kinds = {t.id: t.kind for t in project.tracks}
    por: dict[tuple, list] = {}
    for c in project.clips.values():
        k = kinds.get(c.track_id)
        m = project.media.get(c.media_id)
        if k is None or m is None or c.text is not None:
            continue
        if m.kind in (KIND_VIDEO, KIND_IMAGE) and k != TRACK_VIDEO:
            continue                                  # (su sonido en una pista de audio: ya cuenta su imagen)
        if m.kind == KIND_AUDIO and k != TRACK_AUDIO:
            continue
        por.setdefault((c.media_id, c.track_id), []).append(c)
    out: dict[str, int] = {}
    for (mid, _tid), lst in por.items():
        lst.sort(key=lambda c: c.start)
        n, prev = 0, None
        for c in lst:
            if prev is not None and abs(prev.end - c.start) <= EPS and \
                    abs(float(prev.source_in) + float(prev.src_len) - float(c.source_in)) <= 0.02:
                prev = c
                continue
            n += 1
            prev = c
        out[mid] = out.get(mid, 0) + n
    return out


def bandejas(project, missing=()) -> dict:
    """«No usados»: los archivos de Medios que no salen en la línea de tiempo. «Usados 2+ veces»: los que salen dos
    veces o más (de más veces a menos). Sin los generados (colores, títulos…) ni las escenas."""
    ap = apariciones(project)
    no_usados, usados_2 = [], []
    for mid, m in project.media.items():
        if m.gen or m.kind not in (KIND_VIDEO, KIND_IMAGE, KIND_AUDIO):
            continue
        n = ap.get(mid, 0)
        if n == 0:
            no_usados.append(mid)
        elif n >= 2:
            usados_2.append((mid, n))
    usados_2.sort(key=lambda x: (-x[1], project.media[x[0]].name.lower()))
    no_usados.sort(key=lambda mid: project.media[mid].name.lower())
    return {"no_usados": no_usados, "usados_2": usados_2}


# ------------------------------------------------------------------ equivalencias entre archivos
_PLANOS: dict = {}


def _planos(path: str, dur: float) -> list[tuple[float, float]]:
    k = (os.path.normcase(os.path.abspath(path)), round(float(dur), 3))
    got = _PLANOS.get(k)
    if got is None or not got:
        got = HP.planos(path, dur)
        _PLANOS[k] = got
    return got


def ampliar_a_plano(path: str, dur: float, x0: float, x1: float) -> list[tuple[float, float]]:
    """Un momento repetido (x0–x1) → lo que cuenta como usado: su plano entero si dura hasta PLANO_MAX; si el plano
    es más largo (o no hay planos), el momento ± MARGEN."""
    x0, x1 = max(0.0, x0 - HP.STEP), min(float(dur) if dur else x1 + HP.STEP, x1 + HP.STEP)
    out = []
    for a, b in _planos(path, dur):
        if b <= x0 or a >= x1:
            continue
        if b - a <= PLANO_MAX:
            out.append((a, b))
        else:
            out.append((max(a, x0 - MARGEN), min(b, x1 + MARGEN)))
    if not out:
        out.append((max(0.0, x0 - MARGEN), (min(float(dur), x1 + MARGEN) if dur else x1 + MARGEN)))
    return out


def _equivalencias(objetivo: tuple, otros: list[tuple]) -> list[tuple[float, float]]:
    """objetivo = (path, dur, Huella); otros = [(Huella, [(a, b)])]: lo usado de cada OTRO archivo. Devuelve los tramos
    del objetivo que enseñan lo mismo que algo de eso (ampliados a su plano). Cada fotograma usado cuenta una vez."""
    path, dur, hu = objetivo
    if hu is None or not otros:
        return []
    grupos, ts, hs = [], [], []
    for k, (ho, rangos) in enumerate(otros):
        dif = np.zeros(len(ho) + 1, np.int32)
        for a, b in rangos:
            dif[int(np.searchsorted(ho.t, a - 1e-3, "left"))] += 1
            dif[int(np.searchsorted(ho.t, b + 1e-3, "right"))] -= 1
        t2, h2 = ho.de(np.flatnonzero((np.cumsum(dif[:-1]) > 0) & ho.ok))
        grupos.append(np.full(len(t2), k, np.int64))
        ts.append(t2)
        hs.append(h2)
    ind = HP.Indice(np.concatenate(grupos), np.concatenate(ts), np.concatenate(hs))
    tq, hq = hu.de(hu.ok)
    qi, dj = HP.coincidencias(ind, hq)
    if not len(qi):
        return []
    g = ind.grupo[dj]
    orden = np.argsort(g, kind="stable")
    g, qi, dj = g[orden], qi[orden], dj[orden]
    out = []
    for trozo in np.split(np.arange(len(g)), np.flatnonzero(np.diff(g)) + 1):
        for a, b in HP.segmentos(tq[qi[trozo]], ind.t[dj[trozo]]):
            out += ampliar_a_plano(path, dur, a, b - HP.STEP)
    return out


def usados_con_huella(project, media_id: str, excluir=(), missing=()) -> list[tuple[float, float]]:
    """Lo usado de ese archivo (clips de video) MÁS los tramos que enseñan un momento que ya sale desde otro archivo
    (huella por plano). Para Autocompletar, «Cambiar» y el material por frases: así no repiten momento."""
    excluir = set(excluir)
    m = project.media.get(media_id)
    out = []
    por_otro: dict[str, list] = {}
    for c, mc in _visuales(project, missing):
        if c.id in excluir:
            continue
        if c.media_id == media_id:
            out.append(_rango(c))
        elif mc.kind == KIND_VIDEO:
            por_otro.setdefault(mc.id, [mc, []])[1].append(_rango(c))
    if m is not None and m.kind == KIND_VIDEO and por_otro:
        otros = [(hu, rangos) for mc, rangos in por_otro.values() if (hu := HP.cargar(mc.path)) is not None]
        out += _equivalencias((m.path, float(m.duration or 0), HP.cargar(m.path)), otros)
    return sorted(out)


class Tomados(dict):
    """El registro de tramos usados del B-roll ({media_id: [(a, b)]}, ver ai/broll_selection.find_free) que, al
    reservar un tramo, reserva también lo MISMO en los demás archivos (huella por plano): el B-roll no repite momento
    aunque venga de otro archivo. Empieza con lo que ya sale en la línea de tiempo (y sus equivalentes)."""

    def __init__(self, project=None, missing=(), con_linea: bool = True):
        super().__init__()
        self._medios: dict[str, tuple] = {}            # mid -> (path, dur)
        self._ind = None
        self._eq: dict = {}
        if project is None:
            return
        for mid, m in project.media.items():
            if m.kind == KIND_VIDEO and mid not in missing and not m.gen:
                self._medios[mid] = (m.path, float(m.duration or 0))
        if con_linea:
            for c, m in _visuales(project, missing):
                rng = (0.0, math.inf) if m.kind == KIND_IMAGE else _rango(c)
                self.setdefault(c.media_id, []).append(rng)
                self.al_reservar(c.media_id, rng)

    def _indice(self):
        if self._ind is None:
            grupos, ts, hs, self._ids = [], [], [], []
            for mid, (path, _d) in self._medios.items():
                hu = HP.cargar(path)
                if hu is None or not len(hu):
                    continue
                t2, h2 = hu.de(hu.ok)
                grupos.append(np.full(len(t2), len(self._ids), np.int64))
                ts.append(t2)
                hs.append(h2)
                self._ids.append(mid)
            self._ind = HP.Indice(np.concatenate(grupos), np.concatenate(ts), np.concatenate(hs)) if grupos else False
        return self._ind

    def equivalentes(self, mid: str, a: float, b: float) -> list[tuple[str, tuple[float, float]]]:
        """[(otro media_id, (x, y))]: dónde sale lo mismo que el tramo (a, b) de mid en los otros archivos."""
        if mid not in self._medios or not math.isfinite(b):
            return []
        hu = HP.cargar(self._medios[mid][0])
        ind = self._indice()
        if hu is None or not ind:
            return []
        tq, hq = hu.tramo(a, b)
        if not len(tq):
            return []
        qi, dj = HP.coincidencias(ind, hq)
        g = ind.grupo[dj]
        out = []
        for k in np.unique(g):
            otro = self._ids[int(k)]
            if otro == mid:
                continue
            s = g == k
            path, dur = self._medios[otro]
            for x0, x1 in HP.segmentos(ind.t[dj[s]], tq[qi[s]]):
                out += [(otro, r) for r in ampliar_a_plano(path, dur, x0, x1 - HP.STEP)]
        return out

    def al_reservar(self, mid: str, rng: tuple[float, float]):
        eq = self.equivalentes(mid, rng[0], rng[1])
        for otro, r in eq:
            self.setdefault(otro, []).append(r)
        if eq:
            self._eq[(mid, rng)] = eq

    def al_soltar(self, mid: str, rng: tuple[float, float]):
        for otro, r in self._eq.pop((mid, rng), []):
            lst = self.get(otro, [])
            if r in lst:
                lst.remove(r)


# ------------------------------------------------------------------ cambiar por otro tramo no usado
def _candidatos(project, m, con_sonido: bool | None, missing=()) -> list:
    """El mismo archivo y, después, los de su «tema»: los videos de su misma carpeta (o, si no, de su misma
    categoría), con sonido si el clip lleva su sonido vinculado."""
    out = [m]
    carpeta = os.path.normcase(os.path.dirname(os.path.abspath(m.path)))
    mismos, cat = [], []
    for o in project.media.values():
        if o.id == m.id or o.kind != KIND_VIDEO or o.id in missing or o.gen or not o.duration:
            continue
        if con_sonido and not o.has_audio:
            continue
        if os.path.normcase(os.path.dirname(os.path.abspath(o.path))) == carpeta:
            mismos.append(o)
        elif m.category and m.category != "Sin clasificar" and o.category == m.category:
            cat.append(o)
    out += sorted(mismos, key=lambda o: o.name.lower()) + sorted(cat, key=lambda o: o.name.lower())
    return out


def _margen_grupo(c, partners) -> tuple[float, float]:
    """(cuánto antes, cuánto después) del tramo del clip llega su grupo (su sonido con J/L puede empezar antes o
    acabar después): el nuevo tramo tiene que dejar sitio a todo el grupo dentro del archivo."""
    a0, a1 = _rango(c)
    antes = max([0.0] + [a0 - float(o.source_in) for o in partners or ()])
    despues = max([0.0] + [float(o.source_in) + float(o.src_len) - a1 for o in partners or ()])
    return antes, despues


def elegir_otro_tramo(project, clip_id: str, missing=(), partners=None) -> tuple[str, float] | None:
    """(media_id, source_in) de un tramo del mismo largo que NO sale en la línea de tiempo (ni él ni su momento en otro
    archivo), de un plano libre del mismo archivo (el siguiente hacia delante, dando la vuelta) o de su tema. Deja
    sitio en el archivo a su sonido vinculado aunque vaya con J/L (si no cabe, otro tramo u otro archivo). None si no
    queda ninguno."""
    from . import autocompletar as AC
    from . import scene_pool as SP
    c = project.clips.get(clip_id)
    if c is None:
        return None
    m = project.media.get(c.media_id)
    if m is None or m.kind != KIND_VIDEO or c.speed <= 0:
        return None
    need = float(c.src_len)
    if partners is None:                              # (sus vinculados, aunque quien llama no los pase)
        partners = [o for o in project.clips.values() if c.link and o.link == c.link and o.id != c.id]
    grupo = list(partners)
    # (las pistas de OBS de la misma grabación son otros archivos con el mismo tiempo: van con él, y entonces solo
    #  vale un tramo del MISMO archivo)
    ajenos = [o for o in grupo if project.media.get(o.media_id) is not m]
    antes, despues = _margen_grupo(c, grupo)
    con_sonido = bool(grupo) or None
    for cand in ([m] if ajenos else _candidatos(project, m, con_sonido, missing)):
        dur = float(cand.duration or 0)
        if dur < need + antes + despues - EPS:
            continue
        usados = usados_con_huella(project, cand.id, excluir={clip_id} | {o.id for o in grupo}, missing=missing)
        if cand.id == m.id:
            usados.append(_rango(c))                  # (otro tramo: no vale el que ya enseña)
        escenas = _planos(cand.path, dur) or SP.scenes_from_cuts([], dur)
        libres = [(a, b) for a, b in AC.material(escenas, usados, dur) if b - a >= need - EPS]
        if cand.id == m.id:                           # el siguiente plano libre hacia delante (y luego desde el principio)
            ref = float(c.source_in)
            libres.sort(key=lambda r: ((r[0] - ref) % max(dur, EPS), r[0]))
        for a, b in libres:
            lo = max(a, antes)                        # (el grupo entero dentro del archivo)
            hi = min(b - need, dur - despues - need)
            if hi < lo - EPS:
                continue
            src = min(lo + min(0.1, (hi - lo) / 2), hi)    # (sin el primer fotograma del plano: a veces es el del corte)
            return cand.id, round(max(lo, src), 4)
    return None


def _trasladar(kfs: list, delta: float) -> list:
    """Claves de un clip de video (en segundos del archivo) movidas con su tramo: lista NUEVA (nunca se toca la vieja)."""
    return [dict(k, t=float(k.get("t", 0.0)) + delta) if isinstance(k, dict) and "t" in k else k for k in kfs or []]


def cambiar_por_no_usado(ctrl, clip_id: str) -> str:
    """Pone en el clip otro tramo no usado (mismo largo, mismo sitio en la línea de tiempo), con su sonido vinculado
    (con el mismo desfase, también con J/L) y sus claves de zoom y posición, en un Ctrl+Z. Devuelve el mensaje para
    el usuario (también si no se pudo)."""
    from .controller import EditError
    p = ctrl.project
    c = p.clips.get(clip_id)
    if c is None:
        return "Ese clip ya no está."
    m = p.media.get(c.media_id)
    if m is None or m.kind != KIND_VIDEO:
        return "Solo se puede cambiar el tramo de un clip de video."
    missing = getattr(ctrl, "missing", set())
    partners = ctrl.partners(p, c)
    elegido = elegir_otro_tramo(p, clip_id, missing, partners)
    if elegido is None:
        return (f"No queda ningún tramo sin usar de «{m.name}» ni de su carpeta que dure "
                f"{c.src_len:.1f} s: todo lo demás ya sale en la línea de tiempo.")
    nuevo_mid, nuevo_src = elegido
    viejo_mid = c.media_id
    viejo_src = float(c.source_in)            # (los valores, copiados antes de editar)
    largo = float(c.src_len)

    def fn(proj):
        cc = proj.clips.get(clip_id)
        if cc is None:
            raise EditError("Ese clip ya no está.")
        vinc = ctrl.partners(proj, cc)
        if nuevo_mid != viejo_mid and any(o.media_id != viejo_mid for o in vinc):
            # (un sonido vinculado de OTRO archivo —las pistas de OBS de la grabación— no se puede llevar a otro
            #  archivo: no se cambia nada, antes que dejar el sonido viejo bajo la imagen nueva)
            raise EditError("Su sonido va en otro archivo (pistas de OBS): solo se puede cambiar por un tramo del mismo "
                            "video, y ahí no queda ninguno libre.")
        grupo = [cc] + [o for o in vinc if o.media_id == viejo_mid or nuevo_mid == viejo_mid]
        for x in grupo:
            ctrl._check_clip(proj, x)
        delta = nuevo_src - viejo_src
        for x in grupo:
            mx = proj.media.get(nuevo_mid if x.media_id == viejo_mid else x.media_id)
            dur = float(mx.duration or 0) if mx is not None else 0.0
            ns = float(x.source_in) + delta
            if ns < -EPS or (dur and ns + float(x.src_len) > dur + EPS):
                raise EditError("Su sonido vinculado no cabría en ese tramo del archivo: no se cambia nada.")
        es_video = {x.id for x in grupo if proj.track(x.track_id).kind == TRACK_VIDEO}
        for x in grupo:
            x.source_in = max(0.0, float(x.source_in) + delta)
            if x.media_id == viejo_mid:
                x.media_id = nuevo_mid
            if x.id in es_video:                      # 🔍 las claves de zoom y posición van con su tramo
                if x.zoom_kf:
                    x.zoom_kf = _trasladar(x.zoom_kf, delta)
                if x.layout_kf:
                    x.layout_kf = _trasladar(x.layout_kf, delta)
    if not ctrl._edit(NOMBRE_CAMBIAR, fn):
        return ""
    nm = p.media.get(nuevo_mid)
    desde = _mmss(nuevo_src)
    hasta = _mmss(nuevo_src + largo)
    if nuevo_mid == viejo_mid:
        return f"✓ Ahora enseña {desde}–{hasta} de «{nm.name}», que no salía. Ctrl+Z lo deshace."
    return f"✓ Ahora enseña {desde}–{hasta} de «{nm.name}» (de la misma carpeta), que no salía. Ctrl+Z lo deshace."
