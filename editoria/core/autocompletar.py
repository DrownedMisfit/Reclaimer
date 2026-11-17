"""
✨ Autocompletar (panel IA ✨ → Inicio, en las tres pestañas): el video que eliges tapa las partes de la línea de tiempo
donde no se ve nada, SOLO con lo que aún no usas de ese video (nunca repite un tramo ya usado ni entre los nuevos).
Reutiliza lo de 🎬 «Escenas sin usar» (core/scene_pool.py): las escenas (cortes de plano; lo largo en trozos de 8 s),
lo usado (used_by_media) y la pista de video principal.

  usos(project, media_id) -> [(desde, hasta, veces)]   tramos del archivo que ya salen (clips de video) y cuántas veces
  apariciones(project, media_id) -> int                  cuántas veces sale en la línea de tiempo (un clip partido = 1)
  libre(duracion, usados) -> [(a, b)]                    lo que queda sin usar del archivo
  huecos(project, a, b, track_id) -> [(a, b)]            donde no se ve ningún clip de video
  material(escenas, usados, duracion) -> [(a, b)]        los planos sin usar (sin tocar nada usado)
  plan(media_id, material, huecos, lo, hi, beats, orden) -> (planos, segundos que faltaron)
  (plano = {"media_id", "start", "source_in", "duration"}, como en scene_pool)
"""
from __future__ import annotations

import random

from . import scene_pool as SP
from .model import TRACK_AUDIO, TRACK_VIDEO

MIN_HOLE = 0.3       # un hueco más corto no se rellena
MIN_PIECE = 0.25     # ningún trozo más corto que esto
MIN_SRC = 0.5        # un plano libre más corto no se usa (salvo para cerrar un hueco pequeño)
EPS = 1e-3


def _used(project, media_id: str) -> list[tuple[float, float]]:
    return SP.used_by_media(project).get(media_id, [])


def usos(project, media_id: str) -> list[tuple[float, float, int]]:
    """Los tramos del archivo que ya salen, con cuántas veces sale cada uno (si dos clips se solapan en el archivo, el
    trozo común cuenta 2). Tramos seguidos con las mismas veces se juntan (un clip partido es un solo tramo)."""
    ev: list[tuple[float, int]] = []
    for a, b in _used(project, media_id):
        if b - a > EPS:
            ev += [(round(a, 3), 1), (round(b, 3), -1)]
    ev.sort()
    out: list[list] = []
    depth, last = 0, None
    for t, d in ev:
        if last is not None and depth > 0 and t - last > 0.04:
            if out and out[-1][2] == depth and abs(out[-1][1] - last) <= EPS:
                out[-1][1] = t
            else:
                out.append([last, t, depth])
        depth += d
        last = t
    return [(float(a), float(b), int(n)) for a, b, n in out]


def apariciones(project, media_id: str) -> int:
    """Cuántas veces sale el video en la línea de tiempo (pistas de video). Un clip partido en dos (seguido en la línea
    de tiempo y en el archivo, en la misma pista) cuenta como una sola vez."""
    vids = {t.id for t in project.tracks if t.kind == TRACK_VIDEO}
    cl = sorted((c for c in project.clips.values() if c.media_id == media_id and c.track_id in vids),
                key=lambda c: (c.track_id, c.start))
    n, prev = 0, None
    for c in cl:
        if prev is not None and prev.track_id == c.track_id and abs(prev.end - c.start) <= EPS and \
                abs(float(prev.source_in) + float(prev.src_len) - float(c.source_in)) <= 0.02:
            prev = c
            continue
        n += 1
        prev = c
    return n


def _resta(dominio: list, quitar: list, min_len: float) -> list[tuple[float, float]]:
    """dominio menos quitar (los dos, listas de tramos); solo lo que mide al menos min_len."""
    q = SP._union([(a, b) for a, b in quitar])
    out = []
    for a, b in SP._union([(a, b) for a, b in dominio]):
        t = a
        for x, y in q:
            if y <= t or x >= b:
                continue
            if x - t >= min_len:
                out.append((round(t, 4), round(min(x, b), 4)))
            t = max(t, y)
        if b - t >= min_len:
            out.append((round(t, 4), round(b, 4)))
    return out


def libre(duracion: float, usados: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return _resta([(0.0, float(duracion))], usados, 0.04)


def huecos(project, a: float | None = None, b: float | None = None, track_id: str | None = None,
           min_len: float = MIN_HOLE, destino: str | None = None) -> list[tuple[float, float]]:
    """Donde no se ve nada:
      · sin tramo (a, b) → «Todos los huecos»: donde hay voz/música y ningún clip de video encima (si no hay audio,
        de 0 al final de la línea de tiempo);
      · con tramo → dentro de él, donde no hay ningún clip de video;
      · con track_id (un hueco elegido en esa pista) → dentro del tramo, donde esa pista está vacía.
    destino = la pista donde irán los trozos: TODO lo suyo tapa (también lo desactivado y los textos: nunca se borra
    nada de ella sin querer)."""
    def visible(c):
        tr = project.track(c.track_id)
        return c.enabled and tr is not None and tr.kind == TRACK_VIDEO and c.text is None

    if track_id is not None:
        tapa = [(c.start, c.end) for c in project.clips_on(track_id)]
    else:
        tapa = [(c.start, c.end) for c in project.clips.values() if visible(c)]
    if destino is not None:
        tapa += [(c.start, c.end) for c in project.clips_on(destino)]
    if a is None or b is None:
        audio = [(c.start, c.end) for c in project.clips.values() if c.enabled and
                 (tr := project.track(c.track_id)) is not None and tr.kind == TRACK_AUDIO]
        dur = project.duration()
        dominio = audio or ([(0.0, dur)] if dur > 0 else [])
    else:
        dominio = [(float(a), float(b))]
    return _resta(dominio, tapa, min_len)


def material(escenas: list[tuple[float, float]], usados: list[tuple[float, float]],
             duracion: float) -> list[tuple[float, float]]:
    """Los planos del video sin nada usado dentro (un plano usado a medias deja libre solo lo no usado). Sin escenas
    (no se analizó o no hay cortes): trozos de 8 s de todo el video."""
    if not escenas:
        escenas = SP.scenes_from_cuts([], float(duracion))
    out = []
    for a, b in escenas:
        out += _resta([(a, b)], usados, MIN_PIECE)
    return sorted(out)


def _orden_variado(n: int, rng: random.Random) -> list[int]:
    """Variado pero coherente: barajado, sin dos planos vecinos del video seguidos (si se puede)."""
    idx = list(range(n))
    rng.shuffle(idx)
    for i in range(1, n):
        if abs(idx[i] - idx[i - 1]) == 1:
            for j in range(i + 1, n):
                if abs(idx[j] - idx[i - 1]) != 1:
                    idx[i], idx[j] = idx[j], idx[i]
                    break
    return idx


def plan(media_id: str, mat: list[tuple[float, float]], holes: list[tuple[float, float]], lo: float = 2.0,
         hi: float = 6.0, beats: list[float] | None = None, orden: str = "variado",
         rng: random.Random | None = None) -> tuple[list[dict], float]:
    """Rellena los huecos con trozos de lo libre (mat): cada trozo sale de UN plano, de lo que queda sin usar de él
    (nunca se repite nada). Trozos de lo a hi s; con ritmo (beats), cada trozo termina en el golpe más cercano a lo
    que tocaba dentro de ese margen. orden «video» = sigue el video de principio a fin; «variado» = salta de plano en
    plano (barajados) y cada uno sigue por donde se quedó. Devuelve (planos, segundos que quedaron sin tapar)."""
    rng = rng or random.Random()
    lo = max(MIN_PIECE, float(lo))
    hi = max(lo, float(hi))
    beats = sorted(beats or [])
    segs = [[float(a), float(b)] for a, b in sorted(mat) if b - a >= MIN_PIECE]
    order = list(range(len(segs))) if orden == "video" else _orden_variado(len(segs), rng)
    k = 0
    out: list[dict] = []
    faltan = 0.0
    for g0, g1 in holes:
        t = float(g0)
        while g1 - t > 0.01:
            need = min(MIN_SRC, g1 - t)
            pick = None
            for step in range(len(order)):
                i = order[(k + step) % len(order)]
                if segs[i][1] - segs[i][0] >= need - EPS:
                    pick, k = i, (k + step) % len(order)
                    break
            if pick is None:
                break
            want = lo if hi - lo < EPS else rng.uniform(lo, hi)
            if beats:                                     # al ritmo: el golpe más cercano dentro del margen
                ok = [x for x in beats if t + lo - EPS <= x <= t + hi + EPS]
                if ok:
                    want = min(ok, key=lambda x: abs(x - (t + want))) - t
            s0, s1 = segs[pick]
            rem = g1 - t
            L = min(want, rem)
            if rem - L < max(MIN_PIECE, lo * 0.5):       # no dejar un trocito suelto al final del hueco
                L = rem if rem <= hi * 1.25 else (rem - lo if rem - lo >= lo else rem / 2)
            L = min(L, s1 - s0)
            left = (s1 - s0) - L
            if 0 < left < MIN_SRC and L + left <= min(rem, hi * 1.25):
                L += left                                 # ni un trocito suelto del plano (no se podría usar)
            if 0.01 < rem - L < MIN_PIECE:                # quedaría negro un instante al final del hueco:
                if s1 - s0 >= rem - EPS:
                    L = rem                               #   este plano llega hasta el final
                elif L - (MIN_PIECE - (rem - L)) >= MIN_PIECE:
                    L = rem - MIN_PIECE                   #   o deja sitio para un último trozo de otro plano
            if L < min(MIN_PIECE, rem) - EPS:
                break
            out.append({"media_id": media_id, "start": round(t, 4), "source_in": round(s0, 4),
                        "duration": round(L, 4)})
            segs[pick][0] = s0 + L
            t += L
            if orden != "video":
                k += 1                                    # el siguiente trozo, de otro plano
        if g1 - t > 0.01:
            faltan += g1 - t
    return out, round(faltan, 3)


def pista_destino(project, gap_track: str | None = None):
    """La pista donde van los trozos: la del hueco elegido (si es de video y no está bloqueada); si no, la de video
    principal; si está bloqueada, la siguiente de video sin bloquear (de abajo arriba). None si todas lo están."""
    if gap_track is not None:
        tr = project.track(gap_track)
        if tr is not None and tr.kind == TRACK_VIDEO and not tr.locked:
            return tr
        return None
    vids = [t for t in project.tracks if t.kind == TRACK_VIDEO]
    for tr in reversed(vids):                             # (la de abajo es la principal: SP.main_video_track)
        if not tr.locked:
            return tr
    return None
