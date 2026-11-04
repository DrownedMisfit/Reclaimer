"""
Módulo de IA: ⭐ MIS EFECTOS PARA LA IA.

Tú eliges tus efectos favoritos (de imagen, sonidos y transiciones). La IA busca en el video los momentos
donde encajan y te los propone; tú dices ✓ (se pone) o ✗ (no), o eliges tú los clips. Aprende de cada
respuesta: qué efecto te gusta en qué tipo de momento y con qué tipo de imagen.

Momentos que reconoce (en tiempo de la timeline):
  tema        cambio de tema de tu narración          corte     corte entre dos clips pegados
  golpe       golpe fuerte de la música               drop      el drop (y «antes_drop» para subidas)
  senala      dices «miren», «fíjense»…               pasado    hablas del pasado («hace años», «en 2007»…)
  negativo    «error», «desastre», «bug»…             positivo  «increíble», «brutal», «épico»…
  inicio/final del video                              accion / calma / oscuro: lo que se ve en el clip
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid

import numpy as np

from ..core.model import KIND_AUDIO, TRACK_VIDEO, Project
from ..core.paths import app_data_dir

# ------------------------------------------------------------------ qué sabe de cada efecto
# efectos de imagen: (nombre, valor, cómo se aplica) — moment: empieza en ese instante (se corta el clip si
# hace falta) · start/end: al empezar/acabar el clip · clip: todo el clip
LOOK_INFO = {
    "flash": ("Destello", 0.15, "moment"), "shake": ("Temblor", 0.4, "moment"),
    "glitch": ("Glitch RGB", 0.4, "moment"), "invert": ("Negativo", 0.08, "moment"),
    "fade_in": ("Fundido de entrada", 0.5, "start"), "fade_out": ("Fundido de salida", 0.8, "end"),
    "bw": ("Blanco y negro", 1.0, "clip"), "vignette": ("Viñeta", 0.6, "clip"), "grain": ("Grano", 0.5, "clip"),
    "blur": ("Desenfoque", 0.5, "clip"), "oldfilm": ("Película antigua", 1.0, "clip"),
    "warm": ("Tono cálido", 0.6, "clip"), "cold": ("Tono frío", 0.6, "clip"), "letterbox": ("Barras de cine", 0.11, "clip"),
    "rgbsplit": ("Separación RGB", 0.5, "clip"), "glow": ("Brillo soñador", 0.5, "clip"),
    "motionblur": ("Desenfoque de movimiento", 0.6, "clip"), "punchy": ("Contraste intenso", 0.6, "clip"),
    "vhs": ("VHS", 0.7, "clip"), "flicker": ("Parpadeo", 0.6, "clip"), "roll": ("Giro de cámara", 0.4, "moment"),
    "lightleak": ("Destello de luz", 0.6, "clip"),
}
LOOK_PRIOR = {
    "flash": {"drop": .9, "golpe": .5, "tema": .45, "senala": .6, "positivo": .5, "accion": .35, "corte": .15},
    "shake": {"drop": .8, "golpe": .45, "accion": .6, "negativo": .35, "positivo": .3},
    "glitch": {"negativo": .8, "tema": .4, "corte": .3, "golpe": .3, "drop": .4},
    "invert": {"drop": .75, "golpe": .3},
    "fade_in": {"inicio": .9, "tema": .45},
    "fade_out": {"final": .9, "tema": .35},
    "bw": {"pasado": .75, "negativo": .25, "oscuro": .3},
    "oldfilm": {"pasado": .9},
    "warm": {"pasado": .45, "calma": .4, "positivo": .25},
    "cold": {"oscuro": .65, "negativo": .35},
    "vignette": {"calma": .45, "oscuro": .5, "inicio": .3, "pasado": .3},
    "grain": {"pasado": .5, "calma": .25, "oscuro": .3},
    "blur": {"calma": .15},
    "letterbox": {"calma": .5, "inicio": .4, "positivo": .3},
    "rgbsplit": {"accion": .5, "drop": .45, "negativo": .3},
    "glow": {"calma": .55, "positivo": .5, "pasado": .3},
    "motionblur": {"accion": .6, "drop": .5},
    "punchy": {"accion": .5, "drop": .45, "positivo": .3},
    "vhs": {"pasado": .8, "calma": .2},
    "flicker": {"drop": .55, "golpe": .4, "oscuro": .4, "negativo": .3},
    "roll": {"drop": .6, "golpe": .5, "accion": .4},
    "lightleak": {"calma": .5, "positivo": .5, "inicio": .4, "pasado": .4},
}
SOUND_PRIOR = {   # por la categoría del sonido de Reclaimer (o por palabras del nombre de tu archivo)
    "Transiciones": {"tema": .8, "corte": .35, "inicio": .3},
    "Golpes": {"drop": .9, "golpe": .45, "senala": .4, "positivo": .45, "accion": .3},
    "Tensión": {"antes_drop": .85, "tema": .25},
    "Digital": {"negativo": .6, "corte": .25, "senala": .35},
    "": {"tema": .4, "golpe": .35, "senala": .3},
}
SOUND_WORDS = [("Transiciones", ("whoosh", "swoosh", "swish", "woosh", "barrido", "transition")),
               ("Golpes", ("impact", "impacto", "hit", "boom", "golpe", "punch", "drop", "thud", "slam")),
               ("Tensión", ("riser", "rise", "subida", "tension", "build")),
               ("Digital", ("glitch", "click", "clic", "ui", "beep", "digital", "error"))]
TRANS_PRIOR = {"tema": .8, "corte": .25, "calma": .3, "pasado": .3}
CTX_ES = {"tema": "cambio de tema", "corte": "corte entre clips", "golpe": "golpe fuerte de la música",
          "drop": "drop de la música", "antes_drop": "llega al drop", "senala": "dices «{w}»",
          "pasado": "hablas del pasado («{w}»)", "negativo": "algo negativo («{w}»)",
          "positivo": "algo impresionante («{w}»)", "inicio": "inicio del video", "final": "final del video",
          "accion": "se ve acción", "calma": "plano tranquilo", "oscuro": "escena oscura o tensa",
          "elegido": "clip elegido por ti"}
FREQ = {"pocos": (0.55, 10.0), "normal": (0.42, 5.0), "muchos": (0.3, 2.5)}   # (nota mínima, separación s)

WORD_RULES = [
    ("pasado", r"\b(hace (unos |muchos )?(anos|decadas|tiempo)|en su (dia|epoca|momento)|recuerdo|recuerdan|"
               r"recordemos|originalmente|el original|en (19|20)\d\d|la primera vez|en aquel entonces|antano)\b", 0.8),
    ("negativo", r"\b(error|errores|fallo|fallos|bug|bugs|desastre|problema|problemas|horrible|roto|rota|"
                 r"decepcion|decepcionante|fracaso|lo peor|terrible)\b", 0.7),
    ("positivo", r"\b(increible|epico|epica|brutal|impresionante|espectacular|maravilla|obra maestra|lo mejor|"
                 r"alucinante)\b", 0.7),
]
VISUAL_PROMPTS = {"accion": ["una explosión", "disparos y combate", "una pelea intensa"],
                  "calma": ["un paisaje tranquilo", "el cielo y la naturaleza en calma"],
                  "oscuro": ["una escena oscura y tenebrosa", "terror en la oscuridad"]}


def effect_info(key: str) -> dict:
    """{"type": look|sound|transition, "name", "apply", "prior", "value"} de una clave
    (look:flash · sfx:whoosh · file:C:/…/boom.wav · trans:fade)."""
    kind, _, ref = key.partition(":")
    if kind == "look":
        name, val, apply = LOOK_INFO.get(ref, (ref, 0.5, "clip"))
        return {"type": "look", "name": name, "apply": apply, "prior": LOOK_PRIOR.get(ref, {}), "value": val,
                "fx": ref}
    if kind == "trans":
        from ..core.transitions import NAMES
        return {"type": "transition", "name": NAMES.get(ref, ref), "apply": "cut", "prior": TRANS_PRIOR,
                "trans": ref}
    if kind == "sfx":
        from ..core.sfx import CATALOG
        name, cat, _d = CATALOG.get(ref, (ref, "", ""))
        prior = SOUND_PRIOR.get(cat, SOUND_PRIOR[""])
        return {"type": "sound", "name": name, "apply": "sound", "prior": prior, "category": cat}
    base = os.path.splitext(os.path.basename(ref))[0]
    low = base.lower()
    cat = next((c for c, words in SOUND_WORDS if any(w in low for w in words)), "")
    return {"type": "sound", "name": base, "apply": "sound", "prior": SOUND_PRIOR[cat], "category": cat}


# ------------------------------------------------------------------ lo aprendido
_lock = threading.Lock()


def _store_path() -> str:
    return str(app_data_dir() / "aprendizaje_efectos.json")


def load_store() -> dict:
    with _lock:
        try:
            with open(_store_path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}


def learn(effect_key: str, ctx: str, vec, good: bool) -> None:
    """✓ / ✗ de una propuesta: cuenta para ese tipo de momento y recuerda cómo era la imagen."""
    with _lock:
        try:
            with open(_store_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        st = data.setdefault(effect_key, {"ctx": {}, "pos": [], "neg": []})
        pn = st["ctx"].setdefault(ctx, [0, 0])
        pn[0 if good else 1] += 1
        if vec is not None:
            side = st["pos" if good else "neg"]
            side.append([round(float(x), 4) for x in np.asarray(vec, np.float32)])
            del side[:-60]
        tmp = _store_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _store_path())


def score(effect_key: str, info: dict, m: dict, store: dict) -> float:
    if info["apply"] == "cut" and not m.get("at_cut"):
        return 0.0
    prior = info["prior"].get(m["kind"], 0.0)
    if m["kind"] == "elegido":
        prior = 0.6
    st = store.get(effect_key, {})
    pos, neg = st.get("ctx", {}).get(m["kind"], [0, 0])
    if prior <= 0 and pos == 0:
        return 0.0
    s = (prior * 2 + pos) / (2 + pos + neg) * (0.6 + 0.4 * float(m.get("w", 1.0)))
    v = m.get("vec")
    if v is not None and (st.get("pos") or st.get("neg")):
        v = np.asarray(v, np.float32)
        sp = float(np.max(np.asarray(st["pos"], np.float32) @ v)) if st.get("pos") else 0.72
        sn = float(np.max(np.asarray(st["neg"], np.float32) @ v)) if st.get("neg") else 0.72
        s += 0.8 * (sp - sn)
    return s


# ------------------------------------------------------------------ momentos del video
def visual_clips(p: Project) -> list:
    order = {t.id: i for i, t in enumerate(p.tracks)}
    out = []
    for c in p.clips.values():
        tr = p.track(c.track_id)
        m = p.media.get(c.media_id)
        if tr is None or tr.kind != TRACK_VIDEO or c.text is not None or not c.enabled or m is None \
                or m.kind == KIND_AUDIO:
            continue
        out.append(c)
    out.sort(key=lambda c: (order.get(c.track_id, 99), c.start))
    return out


def top_clip(clips: list, t: float):
    """El clip que se ve en t (la pista de más arriba)."""
    for c in clips:
        if c.start - 1e-4 <= t < c.end - 1e-4:
            return c
    return None


def clip_vec(p: Project, clip_vecs: dict, c, t: float | None = None):
    tv = clip_vecs.get(c.media_id)
    if tv is None or not len(tv[0]):
        return None
    times = np.asarray(tv[0], np.float32)
    vecs = np.asarray(tv[1], np.float32)
    m = p.media.get(c.media_id)
    if m is not None and m.kind == "image":
        v = vecs.mean(0)
    elif t is None:
        a, b = c.source_in, c.source_in + c.src_len
        sel = (times >= min(a, b) - 0.5) & (times <= max(a, b) + 0.5)
        v = vecs[sel].mean(0) if sel.any() else vecs[int(np.argmin(np.abs(times - (a + b) / 2)))]
    else:
        local = min(max(t, c.start), c.end) - c.start
        v = vecs[int(np.argmin(np.abs(times - c.src_at(local))))]
    return v / (np.linalg.norm(v) + 1e-9)


def _word_hits(words: list) -> list[tuple[str, float, float, str]]:
    """(tipo, segundo, fuerza, frase) en la narración."""
    from ..core.organize import normalize
    from .visual_suggestions import TRIGGERS
    norm, offsets, text = [], [], ""
    for w in words:
        offsets.append(len(text))
        n = re.sub(r"[^a-z0-9ñ ]", "", normalize(w[2]))
        norm.append(n)
        text += n + " "
    rules = [("senala", pat, st) for pat, st in TRIGGERS] + list(WORD_RULES)
    out = []
    for kind, pat, st in rules:
        for mt in re.finditer(pat, text):
            i = max(k for k, off in enumerate(offsets) if off <= mt.start())
            j = max(k for k, off in enumerate(offsets) if off <= max(mt.start(), mt.end() - 1))
            phrase = " ".join(w[2] for w in words[i:j + 1]).strip(" ,.;:¿?¡!")
            out.append((kind, float(words[i][0]), st, phrase))
    return out


def find_moments(p: Project, clip_vecs: dict, rhythm: dict, *, scope: tuple[float, float] | None = None,
                 clip_ids: set | None = None, text_vecs: dict | None = None) -> list[dict]:
    """[{t, kind, w, word, clip_id, at_cut, vec}] — los momentos donde podría ir un efecto."""
    from ..core import subtitles
    from . import rhythm as RH
    clips = visual_clips(p)
    if not clips:
        return []
    chosen = [c for c in clips if c.id in clip_ids] if clip_ids else None
    lo, hi = scope if scope else (0.0, max(c.end for c in clips))
    if chosen:
        lo, hi = min(c.start for c in chosen), max(c.end for c in chosen)
    out: list[dict] = []
    cut_ids = {}   # clip que empieza en un corte → su inicio
    by_track: dict[str, list] = {}
    for c in clips:
        by_track.setdefault(c.track_id, []).append(c)
    for lst in by_track.values():
        lst.sort(key=lambda c: c.start)
        for a, b in zip(lst, lst[1:]):
            if abs(b.start - a.end) < 0.05:
                cut_ids[b.id] = b.start
    cuts = sorted(set(cut_ids.values()))

    def add(t, kind, w=1.0, word=None, target=None, at_cut=None):
        if not (lo - 1e-3 <= t <= hi + 1e-3):
            return
        c = target or top_clip(clips, t) or top_clip(clips, t - 0.05)
        if c is None or (chosen and c.id not in clip_ids):
            return
        ac = at_cut if at_cut is not None else (c.id in cut_ids and abs(c.start - t) < 0.05)
        out.append({"t": round(float(t), 3), "kind": kind, "w": float(w), "word": word, "clip_id": c.id,
                    "at_cut": bool(ac), "vec": clip_vec(p, clip_vecs, c, t)})

    for c in clips:
        if c.id in cut_ids and c is top_clip(clips, c.start + 1e-3):
            add(c.start, "corte", 0.6, target=c, at_cut=True)
    if chosen:
        for c in chosen:
            add(c.start, "elegido", 1.0, target=c, at_cut=c.id in cut_ids)
    first = min(clips, key=lambda c: c.start)
    last = max(clips, key=lambda c: c.end)
    add(first.start, "inicio", 1.0, target=first)
    add(max(last.start, last.end - 0.05), "final", 1.0, target=last)
    for mk in p.markers:
        if mk.kind == "topic" and mk.time > first.start + 1.0:
            t = min(cuts, key=lambda x: abs(x - mk.time)) if cuts and min(abs(x - mk.time) for x in cuts) <= 1.5 \
                else mk.time
            add(t, "tema", 1.0, word=mk.label)
    # música
    for c in p.clips.values():
        r = rhythm.get(c.media_id)
        if r is None or c.retimed or not c.enabled:
            continue
        tl = RH.to_timeline(r, c.source_in, c.duration, c.start)
        down = set(round(x, 3) for x in tl["downbeats"])
        for t in tl["strong"]:
            add(t, "golpe", 0.9 if round(t, 3) in down else 0.6)
        if tl["drop"] is not None:
            add(tl["drop"], "drop", 1.0)
            add(tl["drop"], "antes_drop", 1.0)
    # narración
    for mid in p.transcripts:
        if mid not in p.media:
            continue
        words = [(a, b, txt) for a, b, txt, _i in subtitles.timeline_words(p, mid)]
        for kind, t, st, phrase in _word_hits(words):
            add(t, kind, st, word=phrase)
    # lo que se ve
    if text_vecs:
        vis = [c for c in clips if lo - 1e-3 <= c.start <= hi and (not chosen or c.id in clip_ids)]
        cv = [(c, clip_vec(p, clip_vecs, c)) for c in vis]
        cv = [(c, v) for c, v in cv if v is not None]
        if len(cv) >= 3:
            mat = np.stack([v for _c, v in cv])
            mu = mat.mean(0)
            cen = mat - mu
            cen /= np.linalg.norm(cen, axis=1, keepdims=True) + 1e-9
            for kind, tv in text_vecs.items():
                s = cen @ (tv / (np.linalg.norm(tv) + 1e-9))
                z = (s - s.mean()) / (s.std() + 1e-9)
                for (c, _v), zz in zip(cv, z):
                    if zz > 1.2:
                        add(c.start, kind, min(1.0, float(zz) / 2.2), target=c, at_cut=c.id in cut_ids)
    out.sort(key=lambda m: m["t"])
    return out


def visual_text_vecs() -> dict:
    from . import embeddings
    enc = embeddings.get("clip_text")
    return {k: enc.encode(v).mean(0) for k, v in VISUAL_PROMPTS.items()}


# ------------------------------------------------------------------ propuestas
def reason(m: dict) -> str:
    txt = CTX_ES.get(m["kind"], m["kind"])
    return txt.format(w=(m.get("word") or "")[:40]) if "{w}" in txt else txt + (
        f": «{m['word'][:40]}»" if m["kind"] == "tema" and m.get("word") else "")


def propose(p: Project, moments: list[dict], keys: list[str], store: dict, freq: str = "normal",
            limit: int = 80) -> list[dict]:
    """Las mejores propuestas, sin amontonar: [{id, effect, name, kind, reason, t, clip_id, at_cut, score, vec}]"""
    thr, gap = FREQ.get(freq, FREQ["normal"])
    infos = {k: effect_info(k) for k in keys}
    cands = []
    for m in moments:
        for k, info in infos.items():
            s = score(k, info, m, store)
            if s >= thr:
                cands.append((s, k, m))
    cands.sort(key=lambda x: -x[0])
    chosen: list[dict] = []
    clip_looks: set = set()
    for s, k, m in cands:
        info = infos[k]
        typ = info["type"]
        c = p.clips.get(m["clip_id"])
        if c is None:
            continue
        # Sin amontonar: se separan los efectos de la misma clase (instantes de imagen entre sí, transiciones
        # entre sí, sonidos de la misma familia entre sí); los de todo el clip, uno por clip.
        if typ == "sound":
            group = "sound:" + info.get("category", "")
        elif typ == "transition":
            group = "trans"
        else:
            group = "clip" if info["apply"] == "clip" else "punct"
        if group != "clip" and any(o["group"] == group and abs(o["t"] - m["t"]) < gap for o in chosen):
            continue
        if any(o["effect"] == k and abs(o["t"] - m["t"]) < 2 * gap for o in chosen):
            continue
        if typ == "look":
            fx = c.fx or {}
            if fx.get(info["fx"]):
                continue
            if info["apply"] == "clip":
                if c.id in clip_looks:
                    continue
                clip_looks.add(c.id)
        if typ == "transition" and (c.fx or {}).get("trans"):
            continue
        chosen.append({"id": uuid.uuid4().hex[:10], "effect": k, "name": info["name"], "kind": m["kind"],
                       "reason": reason(m), "t": m["t"], "clip_id": m["clip_id"], "at_cut": m["at_cut"],
                       "score": round(float(s), 3), "vec": m.get("vec"), "group": group,
                       "apply": info["apply"]})
        if len(chosen) >= limit:
            break
    chosen.sort(key=lambda o: o["t"])
    return chosen
