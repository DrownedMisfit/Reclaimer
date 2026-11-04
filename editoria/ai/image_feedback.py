"""
Buscador de imágenes de internet que APRENDE de ti: ✓ «esta es» / ✗ «no es».

1. Busca más: varias páginas y también los nombres del glosario («Jefe Maestro = Master Chief»).
2. La IA local (CLIP) mide cuánto se parece cada imagen a lo que escribiste y esconde las que claramente no.
3. Tus ✓ suben las parecidas a esas; tus ✗ quitan esa y apartan las muy parecidas. Se recuerda por búsqueda.
Todo en tu PC: a internet solo van las búsquedas de texto (como en cualquier buscador).
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata

import numpy as np

from ..core.paths import app_data_dir

_lock = threading.Lock()


def norm_query(q: str) -> str:
    t = unicodedata.normalize("NFD", q.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ ]", " ", t)).strip()


def expand_query(q: str, glossary_text: str) -> list[str]:
    """La búsqueda y sus otros nombres (en inglés sobre todo, que es como está etiquetado Openverse)."""
    from .library_understanding import parse_glossary
    from .web_images import smart_queries
    out = smart_queries(q)
    nq = norm_query(q)
    for ent in parse_glossary(glossary_text or ""):
        names = [ent.name] + list(ent.aliases)
        if any(norm_query(n) and (norm_query(n) in nq or nq in norm_query(n)) for n in names):
            for n in names:
                if norm_query(n) != nq and n not in out:
                    out.append(n)
    return out[:4]


# ---------------------------------------------------------------- lo aprendido
def _store_path() -> str:
    return str(app_data_dir() / "aprendizaje_imagenes.json")


def _key(q: str, space: str) -> str:
    """«web»: imágenes de internet · «videos»: momentos de tus videos e imágenes."""
    return norm_query(q) if space == "web" else f"{space}:{norm_query(q)}"


# El archivo con TODAS tus búsquedas y sus ✓/✗ se lee UNA vez y se guarda en segundo plano, todo junto, cuando
# dejas de marcar (antes se leía y se reescribía entero en cada ✓/✗: cuanto más lo usabas, más lento iba).
_MEM: dict = {"data": None, "path": None}
_SAVE_DELAY = 1.0
_timer: threading.Timer | None = None


def _load_all() -> dict:
    with _lock:
        path = _store_path()
        if _MEM["data"] is None or _MEM["path"] != path:
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                raw = {}
            _MEM["data"] = {k: {side: {i: _vec_in(v) for i, v in (fb.get(side) or {}).items()}
                                for side in ("pos", "neg")} for k, fb in raw.items() if isinstance(fb, dict)}
            _MEM["path"] = path
        return _MEM["data"]


def _vec_in(v) -> np.ndarray:
    """Una huella guardada: en binario compacto (base64 de float16) o, en archivos antiguos, una lista de números."""
    if isinstance(v, str):
        import base64
        return np.frombuffer(base64.b64decode(v), np.float16).astype(np.float32)
    return np.asarray(v, np.float32)


def _vec_out(v) -> str:
    import base64
    return base64.b64encode(np.asarray(v, np.float16).tobytes()).decode("ascii")


def _write_now():
    global _timer
    with _lock:
        _timer = None
        mem, path = _MEM["data"], _MEM["path"]
        if mem is None or path is None:
            return
        # compacto: cada huella en binario (4 veces menos que 512 números en texto y mucho más rápido de escribir)
        data = {k: {side: {i: _vec_out(v) for i, v in fb.get(side, {}).items()} for side in ("pos", "neg")}
                for k, fb in mem.items()}
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except OSError:
            pass


def flush():
    """Guarda ya lo pendiente (al cerrar Reclaimer o antes de leerlo desde otro sitio)."""
    t = _timer
    if t is not None:
        t.cancel()
        _write_now()


__import__("atexit").register(flush)


def load_feedback(q: str, space: str = "web") -> dict:
    """{"pos": {id: huella}, "neg": {id: huella}} de esa búsqueda."""
    fb = _load_all().get(_key(q, space), {})
    return {"pos": dict(fb.get("pos", {})), "neg": dict(fb.get("neg", {}))}


def video_examples(names: list[str]) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Tus ✓ y ✗ de momentos de video en búsquedas que nombran a esto (p. ej. «jefe maestro» o «master chief»):
    huellas de ejemplo para el índice de «Entender mi biblioteca»."""
    wanted = [norm_query(n) for n in names if norm_query(n)]
    pos, neg = [], []
    for key, fb in _load_all().items():
        if not key.startswith("videos:"):
            continue
        q = key[len("videos:"):]
        if any(w == q or f" {w} " in f" {q} " for w in wanted):
            pos += list(fb.get("pos", {}).values())
            neg += list(fb.get("neg", {}).values())
    as_arr = lambda v: np.asarray(v, np.float32) if v else None   # noqa: E731
    return as_arr(pos), as_arr(neg)


def save_feedback(q: str, fb: dict, space: str = "web"):
    """Se apunta en memoria al momento y se escribe en el disco en segundo plano (1 s después del último cambio)."""
    global _timer
    data = _load_all()
    keep = {}
    for side in ("pos", "neg"):
        items = list(fb.get(side, {}).items())[-60:]
        keep[side] = {k: np.asarray(v, np.float32) for k, v in items}
    with _lock:
        data[_key(q, space)] = keep
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(_SAVE_DELAY, _write_now)
        _timer.daemon = True
        _timer.start()


def mark(fb: dict, item_id: str, vec, good: bool | None) -> dict:
    """good=True ✓, False ✗, None = quitar la marca."""
    for side in ("pos", "neg"):
        fb[side].pop(item_id, None)
    if good is not None and vec is not None:
        fb["pos" if good else "neg"][item_id] = list(np.asarray(vec, np.float32))
    return fb


# ---------------------------------------------------------------- huellas y orden
def image_vec(path: str) -> np.ndarray | None:
    """Huella CLIP de una miniatura (recorte cuadrado del centro a 224)."""
    import cv2
    from . import embeddings
    data = np.fromfile(path, np.uint8) if os.path.exists(path) else None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data is not None and len(data) else None
    if img is None:
        return None
    h, w = img.shape[:2]
    s = min(h, w)
    img = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    img = cv2.cvtColor(cv2.resize(img, (224, 224), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return embeddings.get("clip_image").encode(img[None])[0]


def text_vec(texts: list[str]) -> np.ndarray:
    from . import embeddings
    v = embeddings.get("clip_text").encode([f"una foto de {t}" for t in texts])
    m = v.mean(axis=0)
    return m / max(float(np.linalg.norm(m)), 1e-9)


def rank_items(ids: list[str], base_z: dict, vecs: dict, pos: np.ndarray | None, neg: np.ndarray | None,
               marks: dict, hide_below: float | None = -1.1) -> list[dict]:
    """Orden común (videos e internet): base_z = qué tanto encaja con lo que escribiste (ya en z);
    pos/neg = huellas de tus ✓/✗ en el MISMO espacio que vecs. marks = {id: "pos"|"neg"}."""
    have = [i for i in ids if vecs.get(i) is not None]

    def standardized(ref):
        if ref is None or not len(ref) or not have:
            return {}, {}
        raw = {i: float((ref @ vecs[i]).max()) for i in have}
        arr = np.array(list(raw.values()))
        m, s = float(arr.mean()), float(arr.std()) or 1.0
        return raw, {i: (v - m) / s for i, v in raw.items()}
    pos_raw, pos_z = standardized(pos)
    neg_raw, neg_z = standardized(neg)
    text_w = 0.5 if pos_raw else 1.0
    out = []
    for i in ids:
        mk = marks.get(i, "")
        z = float(base_z.get(i, 0.0))
        score, why, hidden = text_w * z, "", False
        if i in pos_z:
            score += 2.0 * pos_z[i]
            if pos_z[i] > 1.0 or pos_raw[i] > 0.9:
                why = "parecido a lo que marcaste ✓"
        if i in neg_z:
            score -= 1.5 * max(0.0, neg_z[i])
            closer_to_no = neg_raw[i] > 0.6 and neg_raw[i] - pos_raw.get(i, 0.0) > 0.3
            if neg_raw[i] > 0.92 or closer_to_no or \
                    (neg_z[i] > 1.2 and (not pos_raw or neg_raw[i] > pos_raw.get(i, 0) + 0.03)):
                hidden, why = True, "muy parecido a algo que marcaste ✗"
        if hide_below is not None and z < hide_below and not mk and not (i in pos_z and pos_z[i] > 0.5):
            hidden, why = True, why or "no parece lo que buscas"
        if mk == "pos":
            score, hidden = 1e6, False
        elif mk == "neg":
            hidden = True
        out.append({"id": i, "score": score, "hidden": hidden, "why": why, "mark": mk})
    out.sort(key=lambda r: -r["score"])
    return out


def next_question(ranked: list[dict], asked: set) -> str | None:
    """Qué preguntar «¿es esto?»: sin ✓ todavía, el mejor candidato (para tener un ejemplo cuanto antes);
    después, el más DUDOSO (cerca del límite entre lo que sí y lo que no): así cada respuesta enseña más."""
    shown = [r for r in ranked if not r["hidden"]]
    free = [r for r in shown if not r["mark"] and r["id"] not in asked]
    if not free:
        return None
    if not any(r["mark"] == "pos" for r in ranked):
        return free[0]["id"]
    scores = np.array([r["score"] for r in shown if not r["mark"]] or [0.0])
    mid = float(np.median(scores))
    return min(free, key=lambda r: abs(r["score"] - mid))["id"]


def title_bonus(title: str, queries: list[str]) -> float:
    """Si el título de la imagen contiene las palabras que buscas (o sus otros nombres), sube."""
    t = f" {norm_query(title)} "
    best = 0.0
    for q in queries:
        words = [w for w in norm_query(q).split() if len(w) >= 3 and w not in ("del", "los", "las", "the")]
        if words:
            best = max(best, sum(1 for w in words if f" {w} " in t or f" {w}s " in t) / len(words))
    return best


def rank(ids: list[str], vecs: dict, tvec: np.ndarray | None, fb: dict,
         bonus: dict | None = None) -> list[dict]:
    """Imágenes de internet: [{id, score, hidden, why, mark}] de mejor a peor (mismo criterio que los videos).
    hidden: no se parece a lo que buscas (bastante por debajo del resto) o es casi igual a una ✗."""
    base = {i: float(vecs[i] @ tvec) for i in ids if vecs.get(i) is not None and tvec is not None}
    vals = np.array(list(base.values()) or [0.0])
    mu, sd = float(vals.mean()), float(vals.std()) or 1.0
    base_z = {i: (v - mu) / sd + 0.9 * (bonus or {}).get(i, 0.0) for i, v in base.items()}
    pos = np.array(list(fb["pos"].values()), np.float32) if fb["pos"] else None
    neg = np.array(list(fb["neg"].values()), np.float32) if fb["neg"] else None
    marks = {k: "pos" for k in fb["pos"]} | {k: "neg" for k in fb["neg"]}
    out = rank_items(ids, base_z, vecs, pos, neg, marks, hide_below=-1.1 if tvec is not None else None)
    for r in out:
        if vecs.get(r["id"]) is None and not r["mark"]:
            r.update(score=-1.0, hidden=False, why="sin miniatura todavía")
    out.sort(key=lambda r: -r["score"])
    return out


def related_queries(titles: list[str], q: str) -> list[str]:
    """Búsquedas extra a partir de los títulos de las imágenes ✓ (las palabras que se repiten)."""
    from collections import Counter
    stop = {"the", "a", "of", "and", "in", "on", "with", "for", "de", "la", "el", "y", "en", "photo", "image",
            "jpg", "png", "file", "img", "dsc"}
    words = Counter(w for t in titles for w in set(norm_query(t).split()) if len(w) > 2 and w not in stop
                    and not w.isdigit())
    common = [w for w, n in words.most_common(4) if n >= max(1, len(titles) // 2)]
    out = []
    if common:
        out.append(" ".join(common[:3]))
        out.append(f"{q} {common[0]}")
    return out
