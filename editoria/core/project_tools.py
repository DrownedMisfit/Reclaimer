"""Herramientas sobre el proyecto entero (copias, recortes de un tramo)."""
from __future__ import annotations

from .model import KIND_IMAGE, Project


def slice_project(p: Project, a: float, b: float) -> Project:
    """Copia del proyecto con solo el tramo [a, b] de la timeline, empezando en 0.
    Sirve para escuchar/ver un trozo con todos los efectos sin exportar todo el video."""
    q = Project.from_dict(p.to_dict())
    keep = {}
    for c in q.clips.values():
        if c.end <= a or c.start >= b:
            continue
        cut_left = max(0.0, a - c.start)
        cut_right = max(0.0, c.end - b)
        m = q.media_of(c)
        if m is None or m.kind != KIND_IMAGE:
            c.source_in = c.piece_src(cut_left, c.duration - cut_right)
        elif cut_left > 0:          # imágenes: sus claves cuentan desde el inicio del clip, que ahora es otro
            for attr in ("layout_kf", "zoom_kf", "op_kf", "vol_kf"):
                setattr(c, attr, [dict(k, t=round(k["t"] - cut_left, 4)) for k in getattr(c, attr) or []])
        c.start = max(0.0, c.start - a)
        c.duration -= cut_left + cut_right
        if c.duration > 0.01:
            keep[c.id] = c
    q.clips = keep
    for m in q.markers:
        m.time -= a
        if m.end is not None:
            m.end -= a
    # Las transcripciones se usan para saber cuándo hablas (ducking) y para los subtítulos:
    # siguen valiendo porque se traducen a la timeline a través de los clips recortados.
    return q
