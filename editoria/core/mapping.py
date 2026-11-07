"""
Traducción entre el tiempo del ARCHIVO ORIGINAL y el tiempo de la TIMELINE.

Ejemplo: si cortaste un silencio al principio, la palabra que en el archivo
está en 00:10 puede aparecer en la timeline en 00:07.
"""
from __future__ import annotations

import bisect

from .model import Clip, Project

TOL = 0.005


def clips_of_media(p: Project, media_id: str) -> list[Clip]:
    """Clips de ese archivo (los fotogramas congelados no «suenan» ni avanzan: no cuentan)."""
    return sorted((c for c in p.clips.values() if c.media_id == media_id and c.speed > 0), key=lambda c: c.start)


def media_layout_key(p: Project, media_id: str) -> tuple:
    """Huella de dónde está en la timeline cada trozo de ese archivo: cambia si se mueve, corta, recorta o desactiva
    algo. Sirve para saber si hay que volver a calcular lo que depende de los tiempos de la timeline."""
    return tuple(sorted((round(c.start, 4), round(c.source_in, 4), round(c.duration, 4),
                         getattr(c, "speed", 1.0), getattr(c, "reverse", False), getattr(c, "enabled", True),
                         getattr(c, "track_id", None))
                        for c in p.clips.values() if c.media_id == media_id))


def _covers(c: Clip, s: float) -> bool:
    return c.source_in - TOL <= s < c.source_in + c.src_len


def _when(c: Clip, s: float) -> float:
    """Momento de la timeline en que el clip c muestra el segundo s del archivo (con su velocidad)."""
    if c.reverse:
        return c.start + max(0.0, c.source_in + c.src_len - s) / c.speed
    return c.start + max(0.0, s - c.source_in) / c.speed


def map_time(p: Project, media_id: str, s: float, clips: list[Clip] | None = None) -> float | None:
    """Momento de la timeline donde suena el segundo s del archivo (None si está cortado)."""
    for c in clips if clips is not None else clips_of_media(p, media_id):
        if c.speed > 0 and _covers(c, s):
            return _when(c, s)
    return None


class SourceIndex:
    """Índice rápido para traducir muchos tiempos seguidos (miles de palabras)."""

    def __init__(self, p: Project, media_id: str):
        self.clips = sorted(clips_of_media(p, media_id), key=lambda c: c.source_in)
        self._starts = [c.source_in for c in self.clips]

    def time(self, s: float) -> float | None:
        j = bisect.bisect_right(self._starts, s + TOL) - 1
        for k in range(j, max(-1, j - 4), -1):  # mira unos pocos clips hacia atrás
            c = self.clips[k]
            if _covers(c, s):
                return _when(c, s)
        return None


class DeepIndex:
    """Como SourceIndex, pero también encuentra el archivo cuando está DENTRO de un clip compuesto (⧉): el compuesto
    guarda dónde estaba cada clip original (p.compounds[id] = {"a": inicio, "clips": [...]}), así que el segundo s
    del archivo se traduce a su segundo dentro del compuesto, y ese, a la línea de tiempo (también anidados)."""

    def __init__(self, p: Project, media_id: str, _depth: int = 0):
        self.direct = SourceIndex(p, media_id)
        self.via: list[tuple[float, list, "DeepIndex"]] = []
        if _depth > 4:
            return
        for cid, comp in (getattr(p, "compounds", None) or {}).items():
            olds = [d for d in comp.get("clips", []) if d.get("media_id") == media_id and float(d.get("speed", 1)) > 0]
            if olds:
                self.via.append((float(comp.get("a", 0.0)), olds, DeepIndex(p, cid, _depth + 1)))

    def time(self, s: float) -> float | None:
        t = self.direct.time(s)
        if t is not None:
            return t
        for a, olds, inner in self.via:
            for d in olds:
                si, sp = float(d.get("source_in", 0.0)), float(d.get("speed", 1.0)) or 1.0
                dur = float(d.get("duration", 0.0))
                if si - TOL <= s < si + dur * sp:
                    t_then = float(d.get("start", 0.0)) + (s - si) / sp       # dónde estaba al hacer el compuesto
                    t = inner.time(t_then - a)                                # ese segundo del compuesto, hoy
                    if t is not None:
                        return t
        return None


def map_range(p: Project, media_id: str, a: float, b: float,
              clips: list[Clip] | None = None) -> list[tuple[Clip, float, float]]:
    """Partes del tramo [a, b] del archivo que están en la timeline: [(clip, t_ini, t_fin)]."""
    out = []
    for c in clips if clips is not None else clips_of_media(p, media_id):
        if c.speed <= 0:
            continue
        sa, sb = max(a, c.source_in), min(b, c.source_in + c.src_len)
        if sb - sa > TOL:
            ta, tb = _when(c, sa), _when(c, sb)
            out.append((c, min(ta, tb), max(ta, tb)))
    return out


def find_cut(p: Project, media_id: str, a: float, b: float,
             clips: list[Clip] | None = None) -> tuple[Clip | None, Clip | None, float] | None:
    """
    Busca dónde quedó un corte del tramo [a, b]: el clip que termina en a (L) y el
    que empieza en b (R), pegados en la timeline. Devuelve (L, R, momento_del_corte).
    """
    clips = [c for c in (clips if clips is not None else clips_of_media(p, media_id)) if not c.retimed]
    lefts = [c for c in clips if abs(c.source_in + c.duration - a) <= TOL]
    rights = [c for c in clips if abs(c.source_in - b) <= TOL]
    for L in lefts:
        for R in rights:
            if R.track_id == L.track_id and abs(R.start - L.end) <= TOL:
                return L, R, L.end
    if not lefts and len(rights) == 1 and a <= TOL:      # corte al principio del archivo
        return None, rights[0], rights[0].start
    if not rights and len(lefts) == 1:                    # corte al final del archivo
        L = lefts[0]
        if not any(c.track_id == L.track_id and c.start >= L.end - TOL and c.id != L.id
                   and c.media_id == media_id for c in clips):
            return L, None, L.end
    return None
