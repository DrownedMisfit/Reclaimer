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

import math
import os
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

# Palabras (sin acentos) que, en el nombre, carpeta o etiquetas QUE PONES TÚ, delatan de qué va un clip.
# Así «Cinemáticas/personajes» cuenta como PERSONAJES aunque la IA diga otra cosa.
TOPIC_WORDS = {
    "INTRODUCCIÓN": {"trailer", "trailers", "key", "portada", "logo", "titulo"},
    "HISTORIA Y NARRATIVA": {"historia", "narrativa", "trama", "cinematica", "cinematicas", "lore", "guion"},
    "CINEMATOGRAFÍA": {"cinematica", "cinematicas", "historia"},
    "PERSONAJES": {"personaje", "personajes", "protagonista"},
    "COMBATE": {"combate", "pelea", "jefe", "boss", "armas", "gameplay"},
    "JUGABILIDAD": {"gameplay", "jugabilidad", "exploracion", "mecanicas", "combate"},
    "DISEÑO DE NIVELES": {"niveles", "mapa", "exploracion", "mundo"},
    "DIFICULTAD": {"combate", "jefe", "boss", "gameplay"},
    "RENDIMIENTO": {"rendimiento", "fps", "tecnico", "gameplay", "combate", "exploracion"},
    "GRÁFICOS": {"graficos", "paisaje", "paisajes", "visual", "entorno"},
    "SONIDO Y MÚSICA": {"musica", "banda", "sonora", "ost", "sonido", "concierto"},
    "CONCLUSIÓN": {"trailer", "trailers", "key", "portada", "logo"},
}
AFFINITY = 0.15                      # empujón si la carpeta/nombre/etiquetas de tu clip encajan con el tema
NEWS_CUES = ("anunci", "segun", "noticia", "informa")   # frases que suelen llevar una captura de titular
GAMEPLAY_TOPICS = {"COMBATE", "JUGABILIDAD", "DIFICULTAD", "RENDIMIENTO", "DISEÑO DE NIVELES"}
IMG_EVERY = 75.0                     # como mucho una imagen encima del B-roll cada N segundos

# ---------------------------------------------------------------- registro de tramos usados
# taken = {media_id: [(a, b), ...]}: qué trozo de cada archivo ya está en el video. Un tramo nuevo debe quedar a
# TAKEN_MARGIN s de los demás. Una imagen se reserva entera (0, inf): solo entra una vez.
TAKEN_MARGIN = 0.5
TAKEN_STEP = 0.5


def _overlaps(rngs: list[tuple[float, float]], a: float, b: float) -> bool:
    return any(a < y + TAKEN_MARGIN and b > x - TAKEN_MARGIN for x, y in rngs)


def find_free(taken: dict, mid: str, src0: float, dur: float, cdur: float) -> float | None:
    """Inicio libre (el más cercano a src0) para un tramo de `dur` s dentro de un archivo de `cdur` s. None si no
    queda ningún trozo libre: entonces ese clip se descarta para el hueco (no se repite)."""
    if dur <= 0:
        return None
    hi = max(0.0, cdur - dur)
    rngs = taken.get(mid, [])
    v0 = min(max(0.0, src0), hi)
    if not _overlaps(rngs, v0, v0 + dur):
        return v0
    k = 1                                  # busca hacia atrás y hacia delante desde v0, de medio en medio segundo
    while True:
        lo_v, hi_v = v0 - k * TAKEN_STEP, v0 + k * TAKEN_STEP
        in_lo, in_hi = lo_v >= 0.0, hi_v <= hi
        if not in_lo and not in_hi:
            return None
        if in_lo and not _overlaps(rngs, lo_v, lo_v + dur):
            return lo_v
        if in_hi and not _overlaps(rngs, hi_v, hi_v + dur):
            return hi_v
        k += 1


def claim(taken: dict, mid: str, src: float, dur: float, image: bool = False) -> tuple[float, float]:
    rng = (0.0, math.inf) if image else (src, src + dur)
    taken.setdefault(mid, []).append(rng)
    return rng


def release(taken: dict, mid: str, rng: tuple[float, float]) -> None:
    rngs = taken.get(mid, [])
    if rng in rngs:
        rngs.remove(rng)


def _user_words(c: "ClipInfo") -> tuple[set[str], set[str]]:
    """Lo que TÚ decidiste del clip (nunca lo que adivina la IA). (específico, genérico):
    específico = carpeta donde está, nombre y tus etiquetas; genérico = carpeta de arriba y categoría
    («Cinemáticas» sirve para todo lo de dentro, así que solo cuenta si lo específico no dice nada)."""
    from ..core.organize import words as split_words
    d = os.path.dirname(c.path or "")
    spec = split_words(" ".join([os.path.basename(d), os.path.splitext(c.name)[0], " ".join(c.user_tags)]))
    gen = split_words(" ".join([os.path.basename(os.path.dirname(d)), c.category or ""]))
    return set(spec), set(gen)


def _normalize(text: str) -> str:
    from ..core.organize import normalize
    return normalize(text)


def affinities(clips: list["ClipInfo"]) -> dict[str, set[str]]:
    """media_id -> temas a los que encaja el clip según lo que pusiste tú (TOPIC_WORDS)."""
    out = {}
    for c in clips:
        spec, gen = _user_words(c)
        t = {x for x, ws in TOPIC_WORDS.items() if ws & spec}
        out[c.media_id] = t or {x for x, ws in TOPIC_WORDS.items() if ws & gen}
    return out


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
    images_overlay: bool = False   # las imágenes van ENCIMA del B-roll (pick_overlays), no a pantalla completa


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
    category: str = ""   # la categoría que pusiste tú (carpeta de la biblioteca), aparte de lo que adivina la IA
    user_tags: list[str] = field(default_factory=list)   # tus etiquetas (sin las de la IA)


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


def _is_news(c: ClipInfo) -> bool:
    """Captura de un titular («Noticias» o «noticia» en el nombre o la carpeta)."""
    from ..core.organize import normalize
    return "noticia" in normalize(f"{c.name} {c.category} {c.path or ''}")


def propose(slots: list[dict], clips: list[ClipInfo], st: BrollSettings, used: dict[str, int] | None = None,
            progress: ProgressFn = None, cancelled: CancelFn = None, query: str | None = None,
            taken: dict | None = None) -> list[dict]:
    """Añade a cada hueco sus clips candidatos: slot["candidates"] = [{media_id, score, source_in, duration, reason}].
    Un tramo ya usado en otro hueco NO es candidato (se descarta, no se penaliza). `taken` es el registro de tramos
    (ver find_free); el mejor candidato de cada hueco queda reservado en él (slot["_claim"])."""
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
    taken = {} if taken is None else taken
    aff = affinities(clips)               # lo que pusiste tú (carpetas, nombre, etiquetas) → temas
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
        later_topics = {x["topic"] for x in slots[i + 1:] if x["topic"]}   # temas que salen más adelante
        news_slot = any(cue in _normalize(s["text"]) for cue in NEWS_CUES)
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
            # Tu carpeta/nombre/etiquetas dicen de qué va el clip (+0,15); si es de OTRO tema que sale más adelante,
            # no lo gastes aquí (-0,06): se reserva para ese tema
            if s["topic"] in aff[c.media_id]:
                score += AFFINITY
            elif aff[c.media_id] & later_topics:
                score -= 0.06
            if news_slot and _is_news(c):
                score += AFFINITY  # «anunció», «según»… → la captura del titular
            if c.ai_type in ("Menús", "Pantalla de carga") and c.ai_type not in st.prefer:
                score -= 0.08     # en una crítica casi nunca quieres un menú de fondo
            if c.kind == "video" and c.duration < slot_len * 0.7:
                score -= 0.02     # demasiado corto para cubrir el hueco
            if st.avoid_repeats:
                score -= 0.03 * used.get(c.media_id, 0)
            # El mejor momento del clip; si ese trozo ya está usado en otro hueco, el tramo libre más cercano
            best_t = float(c.times[k])
            if said["motion"] or said["type"]:
                score += motion_words.bias(said, c.path, best_t, c.ai_type)
            if c.kind == "video":
                dur = min(slot_len, c.duration) if c.duration > 0 else slot_len
                src0 = min(max(0.0, best_t - slot_len * 0.4), max(0.0, c.duration - dur))
                src = find_free(taken, c.media_id, src0, dur, c.duration if c.duration > 0 else src0 + dur)
                if src is None:
                    continue      # no queda ningún trozo libre de ese clip: se descarta
            else:
                src, dur = 0.0, slot_len
                if c.media_id in taken:
                    continue      # una imagen, una sola vez
            scored.append({"media_id": c.media_id, "score": score, "source_in": src, "duration": dur,
                           "reason": _reason(c, s["topic"], s["text"].lower()), "name": c.name, "kind": c.kind})
        scored.sort(key=lambda d: -d["score"])
        s["_all"] = scored
        # B-roll: sin imágenes cuando van encima (pick_overlays las coloca aparte)
        vids = [x for x in scored if not (st.images_overlay and x["kind"] == "image")]
        s["candidates"] = vids[:st.candidates]
        if vids:
            best = vids[0]
            used[best["media_id"]] = used.get(best["media_id"], 0) + 1
            rng = claim(taken, best["media_id"], best["source_in"], best["duration"], image=best["kind"] == "image")
            s["_claim"] = {"media_id": best["media_id"], "rng": rng}
    report(progress, 1.0, f"Propuesta lista: {len(slots)} huecos.")
    return slots


def _is_gameplay(c: ClipInfo) -> bool:
    return c.kind == "video" and any("gameplay" in (x or "").lower() for x in (c.ai_type, c.meta, c.category))


def _set_pick(s: dict, taken: dict, mid: str, src: float, dur: float) -> None:
    """Este hueco pasa a usar (mid, src, dur) y queda reservado en el registro."""
    rng = claim(taken, mid, src, dur)
    s["_claim"] = {"media_id": mid, "rng": rng}


def _restore(s: dict, taken: dict, old: dict | None) -> None:
    """El hueco se queda con la reserva que tenía (se había liberado para decidir de nuevo)."""
    if old:
        taken.setdefault(old["media_id"], []).append(old["rng"])
        s["_claim"] = old


def understand_slots(slots: list[dict], clips: list[ClipInfo], st: BrollSettings,
                     understanding: dict | None, taken: dict | None = None) -> list[dict]:
    """Ajusta la propuesta con lo que la IA entendió:
    - Si en la frase nombras a alguien/algo que aparece en tu biblioteca → ese plano primero (una imagen
      nombrada pasa a ser «encima» del B-roll: s["_ent_img"]).
    - Si no → gameplay continuo: sigue el mismo clip de gameplay donde se quedó (cambia al cambiar de tema), solo
      con gameplay que encaje con el tema del hueco y en tramos libres.
    El primer candidato de cada hueco es el que se coloca al rellenar automáticamente."""
    from .library_understanding import matches, norm
    taken = {} if taken is None else taken
    by_id = {c.media_id: c for c in clips}
    aff = affinities(clips)
    entities = (understanding or {}).get("entities", [])
    index = (understanding or {}).get("index", {})
    used_hits: set[tuple[str, float]] = set()
    base: dict | None = None            # gameplay de fondo: {"media_id", "src", "topic"}
    gameplay = [c for c in clips if _is_gameplay(c)]
    gameplay_ids = {g.media_id for g in gameplay}
    for s in slots:
        L = s["end"] - s["start"]
        text = s["text"]
        s.pop("_ent_img", None)
        old = s.pop("_claim", None)           # la reserva de la propuesta: se libera para decidir de nuevo
        if old:
            release(taken, old["media_id"], old["rng"])
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
                    if st.images_overlay and "_ent_img" not in s:
                        s["_ent_img"] = c.media_id          # va encima, no a pantalla completa
                    continue
                lo = h.start if h.end - h.start >= L else max(0.0, h.time - L * 0.5)
                hi = max(lo, min(h.end, c.duration) - L) if h.end - h.start >= L else lo
                src = min(max(lo, h.time - L * 0.4), hi)
                src = max(0.0, min(src, max(0.0, c.duration - L)))
                dur = min(L, c.duration - src) if c.duration > 0 else L
                src = find_free(taken, c.media_id, src, dur, c.duration if c.duration > 0 else src + dur)
                if src is None:
                    continue                                   # ese trozo ya está en otro hueco
                kind = (c.ai_type or "video").lower()
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
            _set_pick(s, taken, chosen[0]["media_id"], chosen[0]["source_in"], chosen[0]["duration"])
            if base is not None:
                base["src"] += L          # el gameplay «sigue corriendo» mientras se ve el otro plano
            continue
        # 2) Gameplay continuo de fondo (solo en temas de jugabilidad y con gameplay que encaje con el tema)
        if not st.continuous or not gameplay or s["topic"] not in GAMEPLAY_TOPICS:
            _restore(s, taken, old)
            continue
        c = by_id.get(base["media_id"]) if base else None
        if base is not None and c is not None and base["topic"] == s["topic"] and base["src"] + L <= c.duration - 0.2:
            src = find_free(taken, c.media_id, base["src"], min(L, c.duration - base["src"]), c.duration)
        else:
            src = None
        if src is not None:
            why = "gameplay continuo (sigue donde iba)"
        else:
            pool = [x for x in s.get("_all", []) if x["media_id"] in gameplay_ids
                    and s["topic"] in aff.get(x["media_id"], set())]
            if base is not None:   # al cambiar de tema o acabarse el clip, otro clip si hay
                pool = [x for x in pool if x["media_id"] != base["media_id"]] or pool
            base, src, c = None, None, None
            for x in pool:
                cx = by_id[x["media_id"]]
                dur = min(L, cx.duration) if cx.duration > 0 else L
                s0 = find_free(taken, cx.media_id, x["source_in"], dur, cx.duration if cx.duration > 0 else dur)
                if s0 is not None:
                    c, src = cx, s0
                    base = {"media_id": c.media_id, "src": s0, "topic": s["topic"]}
                    break
            if c is None:
                _restore(s, taken, old)
                continue
            why = "gameplay de fondo · " + next(x for x in pool if x["media_id"] == c.media_id).get("reason", "")
        dur = min(L, c.duration - src) if c.duration > 0 else L
        cand = {"media_id": c.media_id, "score": 1.0, "source_in": src, "duration": dur,
                "name": c.name, "reason": why}
        others = [x for x in s.get("candidates", []) if x["media_id"] != c.media_id]
        s["candidates"] = ([cand] + others)[:st.candidates]
        _set_pick(s, taken, c.media_id, src, dur)
        base["src"] = src + L
    for s in slots:
        s.pop("_all", None)
    return slots


def pick_overlays(slots: list[dict], pools: list[list[dict]], by_id: dict[str, ClipInfo],
                  taken: dict | None = None, every: float = IMG_EVERY) -> None:
    """Imágenes ENCIMA del B-roll (no a pantalla completa): cada imagen va al hueco donde mejor puntúa (su nombre, su
    carpeta de tema, o una frase de noticia para las capturas). Como mucho una cada `every` s. Marca s["overlay"]."""
    taken = {} if taken is None else taken
    used: set[str] = set()
    last = -1e9
    for s, pool in zip(slots, pools):
        s.pop("overlay", None)
        cand = None
        if s.get("_ent_img") and s["_ent_img"] not in used:
            cand = s["_ent_img"]
        elif pool:
            top = pool[0]
            img = next((x for x in pool if by_id[x["media_id"]].kind == "image" and x["media_id"] not in used), None)
            if img is not None and (img is top or img["score"] >= top["score"] - 0.02):
                cand = img["media_id"]
        if cand is not None and s["start"] - last >= every:
            s["overlay"] = cand
            used.add(cand)
            claim(taken, cand, 0.0, 0.0, image=True)
            last = s["start"]


def propose_understood(slots: list[dict], clips: list[ClipInfo], st: BrollSettings,
                       used: dict[str, int] | None = None, understanding: dict | None = None,
                       progress: ProgressFn = None, cancelled: CancelFn = None,
                       taken: dict | None = None) -> list[dict]:
    """propose() + lo que la IA entendió de tu biblioteca (nombres) + gameplay continuo + imágenes encima.
    `taken` (registro de tramos usados) se pasa también a first_version.broll_items."""
    taken = {} if taken is None else taken
    slots = propose(slots, clips, st, used, progress, cancelled, taken=taken)
    pools = [s.get("_all", []) for s in slots]
    slots = understand_slots(slots, clips, st, understanding, taken=taken)
    if st.images_overlay:
        pick_overlays(slots, pools, {c.media_id: c for c in clips}, taken)
    return slots
