"""
Módulo de IA: SELECCIÓN DE B-ROLL.

Para cada frase de la narración busca en la biblioteca los clips cuyo contenido
encaja con lo que estás diciendo, y propone el mejor momento de cada clip.

Tiene en cuenta:
  - lo que dices (la frase) y el tema de esa parte (COMBATE, CINEMATOGRAFÍA…)
  - de QUIÉN o QUÉ hablas: si la IA entendió tu biblioteca a fondo (ai/library_understanding.py)
    y nombras al «Jefe Maestro», pone un plano donde aparece (imagen, cinemática o gameplay)
  - si no nombras nada concreto: gameplay continuo de fondo (sigue el mismo clip; cambia con el tema)
  - no repetir clips (ni el mismo trozo de un clip)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import embeddings
from .base import CancelFn, ProgressFn, check_cancel, report

# Cómo se "ve" cada tema (ayuda a la IA a elegir imágenes acordes)
TOPIC_VISUALS = {
    "INTRODUCCIÓN": "the title screen or key art of a video game",
    "HISTORIA Y NARRATIVA": "a cinematic story cutscene with characters",
    "PERSONAJES": "a close-up of a video game character's face",
    "COMBATE": "intense combat gameplay, shooting enemies",
    "JUGABILIDAD": "video game gameplay footage",
    "CINEMATOGRAFÍA": "a cinematic cutscene with dramatic camera angles",
    "GRÁFICOS": "beautiful detailed graphics, scenic environment",
    "SONIDO Y MÚSICA": "an atmospheric scene",
    "RENDIMIENTO": "fast paced gameplay footage",
    "DISEÑO DE NIVELES": "a wide view of a video game level and environment",
    "DIFICULTAD": "a hard fight against many enemies",
    "COMPARACIÓN": "a side by side comparison of two versions of a game",
    "CONCLUSIÓN": "the title screen or key art of a video game",
}

# Qué tipo de clip pega más con cada tema (pequeño empujón, no obligación)
TOPIC_TYPE_BONUS = {
    "COMBATE": "Gameplay", "JUGABILIDAD": "Gameplay", "RENDIMIENTO": "Gameplay", "DIFICULTAD": "Gameplay",
    "CINEMATOGRAFÍA": "Cinemáticas", "HISTORIA Y NARRATIVA": "Cinemáticas", "PERSONAJES": "Cinemáticas",
}
TOPIC_TAG = {"COMBATE": "combate", "PERSONAJES": "personaje", "DISEÑO DE NIVELES": "exploración",
             "GRÁFICOS": "paisaje", "HISTORIA Y NARRATIVA": "diálogo"}


# Más pausado (2026-10, como en los edits): con tantos cortes no se aprecia lo que enseñas. Por formato:
# (de, a) segundos por plano por defecto y el MÍNIMO que nunca se rompe (ni con el ritmo «Rápido»).
PACE_DEFAULT = {"short": (2.5, 4.0), "edit": (2.5, 4.0), "youtube": (4.0, 7.0)}
PACE_FLOOR = {"short": 2.0, "edit": 2.0, "youtube": 3.0}


def floor_pace(st: "BrollSettings", fmt: str) -> "BrollSettings":
    """Nunca más cortes de la cuenta: planos de al menos PACE_FLOOR segundos (y max ≥ min + 1)."""
    lo = max(st.min_len, PACE_FLOOR.get(fmt, 3.0))
    st.min_len, st.max_len = round(lo, 2), round(max(st.max_len, lo + 1.0), 2)
    return st


@dataclass
class BrollSettings:
    min_len: float = 4.0           # cambiar de clip cada 4–7 s (YouTube); Shorts 2,5–4 s (ver PACE_DEFAULT)
    max_len: float = 7.0
    prefer: list[str] = field(default_factory=list)   # (ya no se usa: decide la IA por el contenido)
    continuous: bool = True        # gameplay continuo de fondo cuando no nombras nada concreto
    avoid_repeats: bool = True
    candidates: int = 3


@dataclass
class ClipInfo:
    media_id: str
    name: str
    kind: str            # video | image
    duration: float
    ai_type: str
    tags: list[str]
    times: np.ndarray
    vecs: np.ndarray
    meta: str = ""       # lo que se sabe del clip en palabras (tipo, etiquetas, carpeta, nombre)
    path: str = ""       # el archivo (para el movimiento: quieto / con movimiento)


def make_slots(words: list[tuple[float, float, str, int]], st: BrollSettings,
               topics: list[tuple[float, float, str]]) -> list[dict]:
    """Divide la narración (ya en tiempo de timeline) en huecos de min_len–max_len segundos."""
    slots: list[dict] = []
    cur: list = []
    for i, w in enumerate(words):
        cur.append(w)
        dur = cur[-1][1] - cur[0][0]
        nxt_gap = words[i + 1][0] - w[1] if i + 1 < len(words) else 99
        sentence_end = w[2].rstrip().endswith((".", "?", "!", "…"))
        if dur >= st.max_len or (dur >= st.min_len and (sentence_end or nxt_gap > 0.6)) or i == len(words) - 1:
            slots.append({"start": cur[0][0], "words": cur})
            cur = []
    # Cada hueco dura hasta que empieza el siguiente (sin huecos negros entre clips)
    for i, s in enumerate(slots):
        s["end"] = slots[i + 1]["start"] if i + 1 < len(slots) else s["words"][-1][1] + 0.3
        s["text"] = " ".join(w[2] for w in s["words"])
        mid = (s["start"] + s["end"]) / 2
        s["topic"] = next((name for a, b, name in topics if a <= mid < b), "")
        del s["words"]
    # Huecos demasiado cortos (frase final suelta): se unen con el anterior
    merged: list[dict] = []
    for s in slots:
        if merged and s["end"] - s["start"] < st.min_len * 0.6:
            merged[-1]["end"] = s["end"]
            merged[-1]["text"] += " " + s["text"]
        else:
            merged.append(s)
    return split_long(merged, st.max_len, st.min_len)


def split_long(slots: list[dict], max_len: float, min_len: float = 0.0) -> list[dict]:
    """Divide en partes iguales los huecos más largos que el ritmo pedido (p. ej. una pausa larga), sin que ninguna
    parte quede por debajo del mínimo (si no, un hueco de 4,2 s con máximo 4 s salía en dos planos de 2,1 s)."""
    out: list[dict] = []
    for s in slots:
        dur = s["end"] - s["start"]
        n = max(1, int(-(-dur // max_len)))  # techo
        if min_len > 0:                      # (con un 15 % de margen: si pides «cada 3–5 s», manda el máximo)
            n = max(1, min(n, int(dur // (min_len * 0.85))))
        for k in range(n):
            out.append(dict(s, start=s["start"] + dur * k / n, end=s["start"] + dur * (k + 1) / n))
    return out


def _reason(clip: ClipInfo, topic: str, query_terms: str) -> str:
    from ..core.organize import words as split_words
    bits = []
    said = {w for w in split_words(query_terms) if len(w) >= 4} & {w for w in split_words(clip.meta) if len(w) >= 4}
    if said:
        bits.append("mencionas: " + ", ".join(sorted(said)))
    if clip.ai_type:
        bits.append(clip.ai_type)
    shared = [t for t in clip.tags if t in query_terms or TOPIC_TAG.get(topic) == t]
    if shared:
        bits.append("se ve: " + ", ".join(shared))
    elif clip.tags:
        bits.append("se ve: " + clip.tags[0])
    if topic:
        bits.append(f"tema {topic.lower()}")
    return " · ".join(bits)


def propose(slots: list[dict], clips: list[ClipInfo], st: BrollSettings, used: dict[str, int] | None = None,
            progress: ProgressFn = None, cancelled: CancelFn = None, query: str | None = None) -> list[dict]:
    """Añade a cada hueco sus clips candidatos: slot["candidates"] = [{media_id, score, source_in, duration, reason}]."""
    if not slots or not clips:
        return slots
    enc = embeddings.get("clip_text", progress)
    report(progress, 0.2, "Entendiendo cada frase…")
    texts = [s["text"] for s in slots]
    q = enc.encode(texts)
    if query:  # Modo Director: lo que pediste pesa más que la frase
        qv = enc.encode([query])[0]
        q = 0.35 * q + 0.65 * qv
        q /= np.linalg.norm(q, axis=1, keepdims=True)
    # Lo que se SABE de cada clip (tus carpetas y etiquetas, p. ej. «Marcus») frente a cada frase
    from ..core.organize import words as split_words
    sent = embeddings.get("sentence", progress)
    meta_texts = [f"{query}. {t}" if query else t for t in texts]
    meta_sims = sent.encode(meta_texts) @ sent.encode([c.meta or c.name for c in clips]).T   # [huecos, clips]
    clip_words = [{w for w in split_words(c.meta) if len(w) >= 4} for c in clips]
    topic_names = sorted({s["topic"] for s in slots if s["topic"]})
    topic_vecs = dict(zip(topic_names, enc.encode([TOPIC_VISUALS.get(t, t) for t in topic_names])))
    check_cancel(cancelled)

    used = dict(used or {})               # media_id -> veces usado
    used_ranges: dict[str, list[tuple[float, float]]] = {}
    for i, s in enumerate(slots):
        if i % 10 == 0:
            report(progress, 0.3 + 0.7 * i / len(slots), f"Buscando clips para cada frase… {i}/{len(slots)}")
            check_cancel(cancelled)
        v = q[i]
        if s["topic"] in topic_vecs:
            v = v + 0.6 * topic_vecs[s["topic"]]
            v = v / np.linalg.norm(v)
        slot_len = s["end"] - s["start"]
        scored = []
        slot_words = {w for w in split_words(s["text"] + " " + (query or "")) if len(w) >= 4}
        from . import motion_words
        said = motion_words.wants(s["text"] + " " + (query or ""))   # «paisaje» → quieto, «pelea» → movimiento
        for j, c in enumerate(clips):
            sims = c.vecs @ v
            k = int(sims.argmax())
            score = float(0.8 * sims[k] + 0.2 * sims.mean())
            score += 0.04 * max(0.0, float(meta_sims[i, j]))
            exact = slot_words & clip_words[j]
            if exact:
                score += 0.03       # dices una palabra que está en sus etiquetas/carpeta (p. ej. «Marcus»)
            # Preferencias y contexto (empujones pequeños)
            if c.ai_type in st.prefer:
                score += 0.012 * (len(st.prefer) - st.prefer.index(c.ai_type))
            if c.kind == "image" and "Imágenes" in st.prefer:
                score += 0.012 * (len(st.prefer) - st.prefer.index("Imágenes"))
            if TOPIC_TYPE_BONUS.get(s["topic"]) == c.ai_type:
                score += 0.02
            if TOPIC_TAG.get(s["topic"]) in c.tags:
                score += 0.015
            if c.ai_type in ("Menús", "Pantalla de carga") and c.ai_type not in st.prefer:
                score -= 0.08     # en una crítica casi nunca quieres un menú de fondo
            if c.kind == "video" and c.duration < slot_len * 0.7:
                score -= 0.02     # demasiado corto para cubrir el hueco
            if st.avoid_repeats:
                score -= 0.03 * used.get(c.media_id, 0)
            # El mejor momento del clip, evitando trozos ya usados
            best_t = float(c.times[k])
            if said["motion"] or said["type"]:
                score += motion_words.bias(said, c.path, best_t, c.ai_type)
            if c.kind == "video":
                src = min(max(0.0, best_t - slot_len * 0.4), max(0.0, c.duration - slot_len))
                for a, b in used_ranges.get(c.media_id, []):
                    if src < b and src + slot_len > a:
                        score -= 0.03
                        break
                dur = min(slot_len, c.duration) if c.duration > 0 else slot_len
            else:
                src, dur = 0.0, slot_len
            scored.append({"media_id": c.media_id, "score": score, "source_in": src, "duration": dur,
                           "reason": _reason(c, s["topic"], s["text"].lower()), "name": c.name})
        scored.sort(key=lambda d: -d["score"])
        s["_all"] = scored
        s["candidates"] = scored[:st.candidates]
        if scored:
            best = scored[0]
            used[best["media_id"]] = used.get(best["media_id"], 0) + 1
            used_ranges.setdefault(best["media_id"], []).append(
                (best["source_in"], best["source_in"] + best["duration"]))
    report(progress, 1.0, f"Propuesta lista: {len(slots)} huecos.")
    return slots


def _is_gameplay(c: ClipInfo) -> bool:
    return c.kind == "video" and ("gameplay" in (c.ai_type or "").lower() or "gameplay" in (c.meta or "").lower())


def understand_slots(slots: list[dict], clips: list[ClipInfo], st: BrollSettings,
                     understanding: dict | None) -> list[dict]:
    """Ajusta la propuesta con lo que la IA entendió:
    - Si en la frase nombras a alguien/algo que aparece en tu biblioteca → ese plano primero.
    - Si no → gameplay continuo: sigue el mismo clip de gameplay donde se quedó (cambia al cambiar de tema).
    El primer candidato de cada hueco es el que se coloca al rellenar automáticamente."""
    from .library_understanding import matches, norm
    by_id = {c.media_id: c for c in clips}
    entities = (understanding or {}).get("entities", [])
    index = (understanding or {}).get("index", {})
    used_hits: set[tuple[str, float]] = set()
    base: dict | None = None            # gameplay de fondo: {"media_id", "src", "topic"}
    gameplay = [c for c in clips if _is_gameplay(c)]
    for s in slots:
        L = s["end"] - s["start"]
        text = s["text"]
        # 1) ¿Nombras a alguien o algo que la IA reconoce en tus clips?
        ments = []
        for e in entities:
            if e.name in index and matches(e, text):
                pos = min((norm(text).find(norm(n)) for n in e.all_names() if norm(n) in norm(text)), default=0)
                ments.append((pos, e))
        ments.sort(key=lambda x: x[0])
        chosen = []
        for _pos, e in ments:
            for h in index[e.name]:
                c = by_id.get(h.media_id)
                if c is None or (h.media_id, round(h.start, 1)) in used_hits:
                    continue
                if c.kind == "image":
                    src, dur = 0.0, L
                else:
                    lo = h.start if h.end - h.start >= L else max(0.0, h.time - L * 0.5)
                    hi = max(lo, min(h.end, c.duration) - L) if h.end - h.start >= L else lo
                    src = min(max(lo, h.time - L * 0.4), hi)
                    src = max(0.0, min(src, max(0.0, c.duration - L)))
                    dur = min(L, c.duration - src) if c.duration > 0 else L
                kind = "imagen" if c.kind == "image" else (c.ai_type or "video").lower()
                chosen.append({"media_id": c.media_id, "score": 1.0 + h.score / 10, "source_in": src,
                               "duration": dur, "name": c.name, "entity": e.name,
                               "reason": f"mencionas «{e.name}» → aparece aquí ({kind})"})
                if len(chosen) >= st.candidates:
                    break
            if chosen:
                break
        if chosen:
            used_hits.add((chosen[0]["media_id"], round(next(h.start for h in index[chosen[0]["entity"]]
                                                               if h.media_id == chosen[0]["media_id"]), 1)))
            others = [x for x in s.get("candidates", []) if x["media_id"] not in {c["media_id"] for c in chosen}]
            s["candidates"] = (chosen + others)[:st.candidates]
            s["entity"] = chosen[0]["entity"]
            if base is not None:
                base["src"] += L          # el gameplay «sigue corriendo» mientras se ve el otro plano
            continue
        # 2) Gameplay continuo de fondo
        if not st.continuous or not gameplay:
            continue
        c = by_id.get(base["media_id"]) if base else None
        if base is None or c is None or base["topic"] != s["topic"] or base["src"] + L > c.duration - 0.2:
            pool = [x for x in s.get("_all", []) if x["media_id"] in {g.media_id for g in gameplay}]
            if base is not None:   # al cambiar de tema, otro clip si hay
                pool = [x for x in pool if x["media_id"] != base["media_id"]] or pool
            if not pool:
                continue
            best = pool[0]
            c = by_id[best["media_id"]]
            base = {"media_id": c.media_id, "src": float(best["source_in"]), "topic": s["topic"]}
            why = "gameplay de fondo · " + best.get("reason", "")
        else:
            why = "gameplay continuo (sigue donde iba)"
        src = min(base["src"], max(0.0, c.duration - L))
        cand = {"media_id": c.media_id, "score": 1.0, "source_in": src, "duration": min(L, c.duration - src),
                "name": c.name, "reason": why}
        others = [x for x in s.get("candidates", []) if x["media_id"] != c.media_id]
        s["candidates"] = ([cand] + others)[:st.candidates]
        base["src"] = src + L
    for s in slots:
        s.pop("_all", None)
    return slots


def propose_understood(slots: list[dict], clips: list[ClipInfo], st: BrollSettings,
                       used: dict[str, int] | None = None, understanding: dict | None = None,
                       progress: ProgressFn = None, cancelled: CancelFn = None) -> list[dict]:
    """propose() + lo que la IA entendió de tu biblioteca (nombres) + gameplay continuo."""
    slots = propose(slots, clips, st, used, progress, cancelled)
    return understand_slots(slots, clips, st, understanding)
