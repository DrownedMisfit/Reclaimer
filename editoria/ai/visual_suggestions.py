"""
Módulo de IA: SUGERENCIAS VISUALES según lo que dices.

Busca en la narración momentos en los que señalas algo ("miren cómo…", "fíjense en…",
"en esta escena", "el rostro de…") y propone un zoom rápido (acercar, mantener, volver)
sobre el clip que se ve en ese momento. Si hay una cara en el fotograma, el zoom va a la cara.
Nunca se aplica solo: aparece como sugerencia.
"""
from __future__ import annotations

import re

from ..core.organize import normalize
from . import transform_helpers as th

# (expresión, fuerza): las "fuertes" casi siempre piden señalar algo en pantalla
TRIGGERS = [
    (r"\b(miren|mirad|mira|fijense|fijaos|fijate|observen|observad|observa|presten atencion|atencion a)\b", 1.0),
    (r"\b(aqui (se ve|puedes ver|pueden ver|vemos|podemos ver)|en esta escena|este detalle|en este momento|"
     r"como pueden ver|como se ve)\b", 0.7),
    (r"\b(el rostro|la cara|la expresion|los ojos|su mirada)\b", 0.8),
]
FACE_WORDS = re.compile(r"\b(rostro|cara|expresion|ojos|mirada|gesto)\b")


def find_zoom_moments(words: list, min_gap: float = 4.0) -> list[dict]:
    """Momentos de la narración que piden un zoom: [{start, end, label, detail, face}]."""
    if not words:
        return []
    norm = [normalize(w[2]) for w in words]
    # Texto con la posición de cada palabra, para buscar expresiones de varias palabras
    text, offsets = "", []
    for i, w in enumerate(norm):
        offsets.append(len(text))
        text += re.sub(r"[^a-z0-9ñ ]", "", w) + " "
    out: list[dict] = []
    for pattern, strength in TRIGGERS:
        for m in re.finditer(pattern, text):
            i = max(k for k, off in enumerate(offsets) if off <= m.start())
            ctx = " ".join(w[2] for w in words[i:i + 9])
            around = " ".join(norm[i:i + 12])
            out.append({"start": words[i][0], "end": words[min(i + 8, len(words) - 1)][1],
                        "strength": strength, "face": bool(FACE_WORDS.search(around)),
                        "label": f"Zoom: «{ctx}…»",
                        "detail": "Estás señalando algo en pantalla: un zoom ayuda a que se vea."
                                  + (" Mencionas una cara: se intentará centrar en ella." if
                                     FACE_WORDS.search(around) else "")})
    out.sort(key=lambda d: (d["start"], -d["strength"]))
    # Expresiones seguidas (≤ 2,5 s) son el mismo momento: "Miren cómo cambia el rostro…".
    groups: list[list[dict]] = []
    for d in out:
        if groups and d["start"] - groups[-1][-1]["start"] <= 2.5:
            groups[-1].append(d)
        else:
            groups.append([d])
    kept: list[dict] = []
    for g in groups:
        best = max(g, key=lambda d: d["strength"])
        anchor = min((d for d in g if d["strength"] == best["strength"]), key=lambda d: d["start"])
        item = dict(anchor, face=any(d["face"] for d in g))
        if item["face"] and not anchor["face"]:
            item["detail"] += " Mencionas una cara: se intentará centrar en ella."
        # Una sugerencia como mucho cada min_gap segundos
        if kept and item["start"] - kept[-1]["start"] < min_gap:
            if item["strength"] > kept[-1]["strength"]:
                kept[-1] = item
            continue
        kept.append(item)
    return kept


def punch_in(start_src: float, clip_in: float, clip_out: float, z: float, x: float, y: float,
             hold: float = 2.5, ramp: float = 0.4) -> list[dict]:
    """Fotogramas clave de un zoom rápido: acercar en `ramp` s, mantener `hold` s y volver."""
    return th.punch_keyframes(start_src, clip_in, clip_out, z, x, y, hold, ramp)


COMPARE = re.compile(r"\b(el original|la original|juego original|version original|el remake|en el remake|"
                     r"comparad[oa]s? con|en comparacion|si (lo )?comparamos|a diferencia de|frente a|"
                     r"respecto a|versus|vs|mientras que en|antes y (despues|ahora))\b")


def find_compare_moments(words: list, min_gap: float = 8.0) -> list[dict]:
    """Momentos en los que comparas dos cosas: se sugiere una pantalla dividida."""
    if not words:
        return []
    norm = [re.sub(r"[^a-z0-9ñ ]", "", normalize(w[2])) for w in words]
    text, offsets = "", []
    for w in norm:
        offsets.append(len(text))
        text += w + " "
    out: list[dict] = []
    for m in COMPARE.finditer(text):
        i = max(k for k, off in enumerate(offsets) if off <= m.start())
        start = words[max(0, i - 3)][0]
        if out and start - out[-1]["start"] < min_gap:
            continue
        ctx = " ".join(w[2] for w in words[max(0, i - 3):i + 8])
        out.append({"start": start, "end": words[min(i + 8, len(words) - 1)][1],
                    "label": f"Comparación: «{ctx}…»",
                    "detail": "Estás comparando: una pantalla dividida con las dos cosas ayuda a ver "
                              "la diferencia."})
    return out
