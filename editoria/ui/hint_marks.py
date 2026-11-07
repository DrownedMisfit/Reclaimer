"""
Marcas de la regla de la línea de tiempo: cada origen guarda las suyas y se muestran juntas. Así, las banderitas
de «🎬 Clips» (lo que dijiste) y las de «🔎 Buscar en lo que dijiste» no se pisan.
"""
from __future__ import annotations

_ORIGENES = ("clips", "buscar")


def set_source(timeline, origen: str, marcas) -> None:
    fuentes = getattr(timeline, "_marcas_por_origen", None)
    if fuentes is None:
        fuentes = {}
        timeline._marcas_por_origen = fuentes
    fuentes[origen] = list(marcas or [])
    juntas = []
    for k in _ORIGENES:
        juntas += fuentes.get(k, [])
    timeline.set_hint_marks(juntas)
