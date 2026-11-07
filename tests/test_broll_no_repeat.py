"""
Prueba del registro de tramos usados del B-roll automático:
  · con 3 clips y 20 huecos, ningún trozo de archivo se solapa (0 solapes del mismo archivo);
  · cada imagen se usa como mucho una vez;
  · si no queda nada libre, el plano anterior se alarga en vez de repetir un trozo;
  · find_free devuelve el tramo libre más cercano, o None si el clip está lleno.
No necesita modelos de IA (los candidatos se construyen a mano, en el peor caso: todos quieren el mismo trozo).
Ejecutar:  .venv/Scripts/python.exe tests/test_broll_no_repeat.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editoria.ai import broll_selection as B  # noqa: E402
from editoria.ai import first_version  # noqa: E402


@dataclass
class M:                       # lo mínimo de un archivo multimedia que usa broll_items
    id: str
    kind: str
    duration: float


def overlaps(items: list[dict], media: dict[str, M]) -> int:
    """Pares de planos del MISMO archivo cuyos trozos se solapan más de 0,1 s."""
    n = 0
    by = {}
    for it in items:
        if media[it["media_id"]].kind == "image":
            continue
        by.setdefault(it["media_id"], []).append((it["source_in"], it["source_in"] + it["duration"]))
    for rs in by.values():
        for i, (a, b) in enumerate(rs):
            for c, d in rs[i + 1:]:
                if min(b, d) - max(a, c) > 0.1:
                    n += 1
    return n


def make_slots(n: int, L: float, cands_for) -> list[dict]:
    """n huecos de L s, uno detrás de otro; cands_for(i) da la lista de candidatos (ya ordenada)."""
    slots = []
    for i in range(n):
        s = {"start": i * L, "end": (i + 1) * L, "text": f"frase {i}", "topic": "COMBATE"}
        s["candidates"] = cands_for(i)
        slots.append(s)
    return slots


def cand(mid: str, src: float, dur: float, reason: str = "prueba") -> dict:
    return {"media_id": mid, "score": 1.0, "source_in": src, "duration": dur, "name": mid, "reason": reason}


def main() -> None:
    # ---- 1) 3 clips de 30 s y 2 imágenes; 20 huecos de 4 s (80 s de voz, caben de sobra)
    media = {"a": M("a", "video", 30.0), "b": M("b", "video", 30.0), "c": M("c", "video", 30.0),
             "i1": M("i1", "image", 0.0), "i2": M("i2", "image", 0.0)}
    # peor caso: todos los huecos piden el principio de los clips (source_in 0)
    cands = lambda i: [cand("a", 0.0, 4.0), cand("b", 0.0, 4.0), cand("c", 0.0, 4.0), cand("i1", 0.0, 4.0),
                       cand("i2", 0.0, 4.0)]
    slots = make_slots(20, 4.0, cands)
    taken: dict = {}
    items = first_version.broll_items(slots, media, start_at_zero=False, taken=taken)
    assert len(items) == 20, f"deberían salir 20 planos y salieron {len(items)}"
    assert overlaps(items, media) == 0, "hay trozos del mismo archivo solapados"
    img_used = [it["media_id"] for it in items if media[it["media_id"]].kind == "image"]
    assert len(img_used) == len(set(img_used)), f"imagen repetida: {img_used}"
    assert len(img_used) <= 2
    print(f"  20 huecos, 3 clips: {len(items)} planos, 0 solapes, imágenes usadas: {sorted(set(img_used))}")

    # ---- 2) poco material: 3 clips de 10 s (30 s) para 20 huecos de 4 s (80 s).
    #         Nunca se repite un trozo; los huecos que no caben se reparten alargando planos vecinos.
    media2 = {"a": M("a", "video", 10.0), "b": M("b", "video", 10.0), "c": M("c", "video", 10.0)}
    cands2 = lambda i: [cand("a", 0.0, 4.0), cand("b", 0.0, 4.0), cand("c", 0.0, 4.0)]
    slots2 = make_slots(20, 4.0, cands2)
    items2 = first_version.broll_items(slots2, media2, start_at_zero=False, taken={})
    assert overlaps(items2, media2) == 0, "poco material: hay trozos solapados"
    for it in items2:                                   # ningún plano se sale de su archivo
        assert it["source_in"] + it["duration"] <= media2[it["media_id"]].duration + 1e-6, it
    total = sum(it["duration"] for it in items2)
    print(f"  poco material: {len(items2)} planos, 0 solapes, {total:.1f} s de 80 s cubiertos")

    # ---- 3) find_free: el tramo libre más cercano; None si el clip está lleno
    t = {"x": [(0.0, 10.0)]}
    assert B.find_free(t, "x", 0.0, 4.0, 30.0) == 10.5, B.find_free(t, "x", 0.0, 4.0, 30.0)
    assert B.find_free(t, "x", 0.0, 4.0, 14.0) is None  # solo cabe un trozo de 4 s en 14 s si empieza a >= 10,5 s
    assert B.find_free({"y": [(0.0, 30.0)]}, "y", 5.0, 4.0, 30.0) is None
    assert B.find_free({}, "z", 7.0, 4.0, 30.0) == 7.0
    print("  find_free: tramo más cercano, None si está lleno")

    # ---- 4) pick_overlays: una imagen, como mucho una cada 75 s
    slots4 = make_slots(3, 40.0, lambda i: [])
    pool = [{"media_id": "i1", "score": 0.5}, {"media_id": "a", "score": 0.4}]
    by_id = {"i1": B.ClipInfo("i1", "i1", "image", 0.0, "", [], None, None), "a": B.ClipInfo("a", "a", "video", 30.0, "", [], None, None)}
    by_id["i1"].kind = "image"
    B.pick_overlays(slots4, [pool, pool, pool], by_id, {})
    picks = [s.get("overlay") for s in slots4 if s.get("overlay")]
    assert picks == ["i1"], picks
    print("  pick_overlays: una imagen, una vez")

    print("TODO OK")


if __name__ == "__main__":
    main()
