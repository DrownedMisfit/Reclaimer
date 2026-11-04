"""
Módulo de IA: DETECCIÓN DE TEMAS de la narración.

1. Divide la transcripción en frases.
2. Compara cada frase con descripciones de temas típicos de una crítica de videojuegos.
3. Agrupa frases seguidas del mismo tema (cambiar de tema "cuesta", para que no salte
   de un tema a otro en cada frase) y une los trozos demasiado cortos.

Resultado: [(inicio, fin, TEMA, confianza)] en tiempo del archivo de narración.
"""
from __future__ import annotations

import numpy as np

from . import embeddings
from .base import CancelFn, ProgressFn, check_cancel, report
from .repetition_detection import split_phrases

# Tema -> (color, frases de ejemplo de cómo se habla de él)
TOPICS: dict[str, tuple[str, list[str]]] = {
    "INTRODUCCIÓN": ("#9aa1ad", ["hola a todos, bienvenidos a un nuevo video",
                                 "hoy vamos a hablar de este juego", "en este video voy a analizar"]),
    "HISTORIA Y NARRATIVA": ("#b083f0", ["la historia del juego y su narrativa", "el guion y la trama",
                                         "el desarrollo de la historia no tiene ritmo",
                                         "el final de la historia y los giros argumentales"]),
    "PERSONAJES": ("#f778ba", ["los personajes y su desarrollo", "el protagonista y sus compañeros",
                               "la personalidad y las motivaciones del personaje"]),
    "COMBATE": ("#e5534b", ["el combate y los enfrentamientos", "las armas y los disparos",
                            "pelear contra los enemigos", "los tiroteos se sienten pesados"]),
    "JUGABILIDAD": ("#f0883e", ["la jugabilidad y las mecánicas", "los controles y el movimiento",
                                "el sistema de progresión y las habilidades"]),
    "CINEMATOGRAFÍA": ("#39c5cf", ["las cinemáticas y la dirección de cámara", "los planos y la puesta en escena",
                                   "las escenas cinematográficas están muy bien trabajadas"]),
    "GRÁFICOS": ("#57ab5a", ["los gráficos y el apartado visual", "la iluminación y las texturas",
                             "el diseño artístico y los efectos visuales"]),
    "SONIDO Y MÚSICA": ("#4f8cff", ["la banda sonora y la música", "el diseño de sonido y el doblaje"]),
    "RENDIMIENTO": ("#8b949e", ["el rendimiento, los fps y los errores técnicos", "bugs y problemas técnicos",
                                "tiempos de carga y estabilidad", "técnicamente el juego funciona bien",
                                "el apartado técnico y la optimización"]),
    "DISEÑO DE NIVELES": ("#d4a72c", ["el diseño de los niveles y escenarios", "el mundo y la exploración",
                                      "los mapas y los entornos"]),
    "DIFICULTAD": ("#c69026", ["la dificultad del juego", "es demasiado fácil o demasiado difícil"]),
    "COMPARACIÓN": ("#e3b341", ["la comparación con el juego original", "el remake cambia respecto al original",
                                "en la versión original era diferente"]),
    "CONCLUSIÓN": ("#9aa1ad", ["en conclusión, mi opinión final", "para terminar, vale la pena comprarlo",
                               "gracias por ver el video, nos vemos en el próximo"]),
}


def topic_color(name: str) -> str:
    return TOPICS.get(name, ("#9aa1ad", []))[0]


_topic_vecs: tuple[list[str], list[np.ndarray]] | None = None


def _topic_vectors():
    global _topic_vecs
    if _topic_vecs is None:
        enc = embeddings.get("sentence")
        names = list(TOPICS)
        _topic_vecs = (names, [enc.encode(TOPICS[n][1]) for n in names])
    return _topic_vecs


def _viterbi(scores: np.ndarray, switch_penalty: float) -> list[int]:
    """Mejor secuencia de temas: suma de puntuaciones menos un coste por cada cambio de tema."""
    n, k = scores.shape
    best = scores[0].copy()
    back = np.zeros((n, k), dtype=np.int64)
    for i in range(1, n):
        stay = best
        jump = best.max() - switch_penalty
        jump_from = int(best.argmax())
        choose_stay = stay >= jump
        back[i] = np.where(choose_stay, np.arange(k), jump_from)
        best = np.where(choose_stay, stay, jump) + scores[i]
    path = [int(best.argmax())]
    for i in range(n - 1, 0, -1):
        path.append(int(back[i][path[-1]]))
    return path[::-1]


def detect_topics(words: list, min_seconds: float = 10.0, switch_penalty: float = 0.15,
                  progress: ProgressFn = None, cancelled: CancelFn = None) -> list[dict]:
    """words: [[ini, fin, texto, ...]] de la transcripción. Devuelve segmentos con tema."""
    if not words:
        return []
    report(progress, 0.1, "Leyendo las frases…")
    phrases = split_phrases(words, gap=0.8)
    texts = [" ".join(w[2] for w in words[a:b]) for a, b in phrases]
    enc = embeddings.get("sentence", progress)
    check_cancel(cancelled)
    report(progress, 0.4, "Entendiendo de qué hablas…")
    vecs = enc.encode(texts)
    # Contexto: cada frase se "mezcla" un poco con sus vecinas (las frases sueltas engañan)
    ctx = vecs.copy()
    ctx[1:] += 0.5 * vecs[:-1]
    ctx[:-1] += 0.5 * vecs[1:]
    ctx /= np.linalg.norm(ctx, axis=1, keepdims=True)
    names, protos = _topic_vectors()
    scores = np.stack([np.max(ctx @ p.T, axis=1) for p in protos], axis=1)  # [frases, temas]

    # Posición en el video: la introducción va al principio y la conclusión al final
    total = words[-1][1] - words[0][0] or 1.0
    pos = np.array([(words[a][0] - words[0][0]) / total for a, _b in phrases])
    intro, outro = names.index("INTRODUCCIÓN"), names.index("CONCLUSIÓN")
    scores[:, intro] += np.where(pos < 0.12, 0.10, np.where(pos > 0.25, -0.5, 0.0))
    scores[:, outro] += np.where(pos > 0.85, 0.10, np.where(pos < 0.7, -0.5, 0.0))
    check_cancel(cancelled)

    report(progress, 0.7, "Agrupando por temas…")
    path = _viterbi(scores, switch_penalty)
    segs: list[dict] = []
    for i, (a, b) in enumerate(phrases):
        start, end = words[a][0], words[b - 1][1]
        if segs and segs[-1]["topic_i"] == path[i]:
            segs[-1]["end"] = end
            segs[-1]["phr"].append(i)
        else:
            segs.append({"start": start, "end": end, "topic_i": path[i], "phr": [i]})

    # Unir trozos demasiado cortos con el vecino más parecido
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for j, s in enumerate(segs):
            if s["end"] - s["start"] >= min_seconds:
                continue
            cands = [x for x in (j - 1, j + 1) if 0 <= x < len(segs)]
            target = max(cands, key=lambda x: float(np.mean(scores[s["phr"], segs[x]["topic_i"]])))
            t = segs[target]
            t["start"], t["end"] = min(t["start"], s["start"]), max(t["end"], s["end"])
            t["phr"] = sorted(t["phr"] + s["phr"])
            del segs[j]
            changed = True
            break
    # Unir vecinos que hayan quedado con el mismo tema
    merged: list[dict] = []
    for s in segs:
        if merged and merged[-1]["topic_i"] == s["topic_i"]:
            merged[-1]["end"] = s["end"]
            merged[-1]["phr"] += s["phr"]
        else:
            merged.append(s)

    out = []
    for i, s in enumerate(merged):
        name = names[s["topic_i"]]
        conf = float(np.mean(scores[s["phr"], s["topic_i"]]))
        end = merged[i + 1]["start"] if i + 1 < len(merged) else s["end"]
        example = texts[s["phr"][0]]
        out.append({"start": s["start"], "end": end, "topic": name, "confidence": round(conf, 3),
                    "color": topic_color(name), "example": example})
    report(progress, 1.0, f"{len(out)} temas detectados.")
    return out
