"""
Módulo de IA: BUSCAR MOMENTOS (apariciones) en tus medios.

Encuentra DÓNDE aparece algo en tus videos e imágenes y lo devuelve como apariciones con
inicio y fin (no solo un fotograma suelto). Si algo vuelve a aparecer mucho después, es otra
aparición. Sirve para cualquier contenido (juegos, películas, series, podcasts, vlogs…).

Tres formas de buscar:
  - por texto: «la Lancer», «un coche rojo», «una explosión» (español o inglés),
  - por imagen de referencia: una foto o captura de lo que buscas,
  - por un nombre que la IA ya aprendió (ver library_understanding.py).

Usa las huellas visuales que ya calculó el análisis de clips (mejor si se analizó «a fondo»:
un fotograma por segundo; si no, solo unos pocos por clip y las apariciones serán aproximadas).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import embeddings


@dataclass
class Moment:
    media_id: str
    start: float
    end: float
    best: float          # el segundo más claro
    score: float         # seguridad (z: cuántas veces más que lo normal)
    kind: str = "video"  # video | image


def _robust_z(x: np.ndarray) -> np.ndarray:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826 + 1e-6
    return (x - med) / mad


def _collapse(times: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Varios vectores por segundo (plano entero + centro): nos quedamos con el mejor de cada segundo."""
    order = np.argsort(times, kind="stable")
    t, s = times[order], scores[order]
    ut, inv = np.unique(np.round(t, 2), return_inverse=True)
    best = np.full(len(ut), -1e9)
    np.maximum.at(best, inv, s)
    return ut, best


def segments(times: np.ndarray, scores: np.ndarray, thr: float, duration: float,
             gap: float = 2.5, pad: float = 0.5) -> list[tuple[float, float, float, float]]:
    """Agrupa los segundos que superan el umbral en apariciones [(inicio, fin, mejor, puntuación)]."""
    out = []
    cur = None
    for t, s in zip(times, scores):
        if s < thr:
            continue
        if cur is not None and t - cur[1] <= gap:
            cur[1] = t
            if s > cur[3]:
                cur[2], cur[3] = t, s
        else:
            if cur is not None:
                out.append(cur)
            cur = [t, t, t, s]
    if cur is not None:
        out.append(cur)
    res = []
    for a, b, best, s in out:
        a, b = max(0.0, a - pad), b + pad
        if duration:
            b = min(duration, b)
        if b - a < 1.0:                       # mínimo un segundo para poder usarlo
            b = min(duration or a + 1.0, a + 1.0)
        res.append((round(a, 2), round(b, 2), round(float(best), 2), float(s)))
    return res


def _search(score_fn, data: dict[str, dict], thr: float, top: int, min_results: int = 6) -> list[Moment]:
    """score_fn(vecs) -> puntuación por vector. data: {mid: {"times","vecs","kind","duration"}}."""
    mids = list(data)
    if not mids:
        return []
    raw = [score_fn(np.asarray(data[m]["vecs"], np.float32)) for m in mids]
    z_all = _robust_z(np.concatenate(raw))
    out: list[Moment] = []
    k = 0
    per_media = []
    for m, r in zip(mids, raw):
        z = z_all[k:k + len(r)]
        k += len(r)
        t, s = _collapse(np.asarray(data[m]["times"], np.float32), z)
        per_media.append((m, t, s))
    for level in (thr, thr * 0.7, thr * 0.5):     # si casi no hay nada, ser un poco menos exigente
        out = []
        for m, t, s in per_media:
            d = data[m]
            if d.get("kind") == "image":
                if float(s.max()) >= level:
                    out.append(Moment(m, 0.0, 0.0, 0.0, float(s.max()), "image"))
                continue
            for a, b, best, sc in segments(t, s, level, float(d.get("duration") or 0)):
                out.append(Moment(m, a, b, best, sc))
        if len(out) >= min_results:
            break
    out.sort(key=lambda x: -x.score)
    return out[:top]


def _centered(data: dict[str, dict]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    allv = np.concatenate([np.asarray(d["vecs"], np.float32) for d in data.values()])
    mu = allv.mean(0)
    return mu, {}


def search_text(query: str, data: dict[str, dict], meta: dict[str, str] | None = None,
                thr: float = 2.6, top: int = 60, paths: dict[str, str] | None = None) -> list[Moment]:
    """Momentos que encajan con una descripción (en español o inglés)."""
    enc = embeddings.get("clip_text")
    prompts = [query, f"una imagen de {query}", f"{query} en un video"]
    q = enc.encode(prompts).mean(0)
    q /= np.linalg.norm(q) + 1e-9
    res = _search(lambda v: v @ q, data, thr, top * 2)
    from . import motion_words
    said = motion_words.wants(query)
    if paths and said["motion"]:   # «paisaje» → momentos quietos · «pelea» → con movimiento
        for r in res:
            if r.media_id in paths:
                r.score += 12 * motion_words.bias({"motion": said["motion"]}, paths[r.media_id], r.best)
        res.sort(key=lambda x: -x.score)
    if meta:   # el nombre del archivo o su carpeta dice lo que buscas: un empujón
        words = {w for w in query.lower().split() if len(w) >= 4}
        for r in res:
            if words & set(meta.get(r.media_id, "").lower().split()):
                r.score += 1.0
        res.sort(key=lambda x: -x.score)
    return res[:top]


def search_image(ref_vecs: np.ndarray, data: dict[str, dict], thr: float = 2.6, top: int = 60,
                 exclude: str | None = None) -> list[Moment]:
    """Momentos parecidos a una imagen de referencia (sus huellas: plano entero y centro)."""
    data = {m: d for m, d in data.items() if m != exclude}
    if not data:
        return []
    mu_key = tuple((m, id(d["vecs"]), len(d["vecs"])) for m, d in data.items())
    hit = _MU.get("k")
    if hit is not None and hit[0] == mu_key:
        mu = hit[1]
    else:
        mu, _ = _centered(data)
        _MU["k"] = (mu_key, mu)
        _NORM.clear()
    r = np.asarray(ref_vecs, np.float32).mean(0) - mu
    r /= np.linalg.norm(r) + 1e-9

    def score(v):
        # (centrar y normalizar todos los fotogramas es lo caro: se hace una vez por archivo, no en cada ✓/✗)
        c = _NORM.get(id(v))
        if c is None or c[0] is not v:
            n = v - mu
            n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
            if len(_NORM) > 300:
                _NORM.clear()
            c = _NORM[id(v)] = (v, n)
        return c[1] @ r
    return _search(score, data, thr, top)


_MU: dict = {}
_NORM: dict = {}


def encode_image_file(path: str) -> np.ndarray:
    """Huellas de una imagen de referencia (plano entero y centro)."""
    from .library_understanding import analyze_deep
    return analyze_deep(path, "image", 0.0)["vecs"]


def from_hits(hits, data: dict[str, dict], gap: float = 2.5) -> list[Moment]:
    """Apariciones de un nombre que la IA ya aprendió (planos contiguos = una aparición)."""
    by_media: dict[str, list] = {}
    for h in hits:
        by_media.setdefault(h.media_id, []).append(h)
    out = []
    for m, hs in by_media.items():
        kind = data.get(m, {}).get("kind", "video")
        if kind == "image":
            out.append(Moment(m, 0.0, 0.0, 0.0, max(h.score for h in hs), "image"))
            continue
        hs.sort(key=lambda h: h.start)
        cur = None
        for h in hs:
            if cur is not None and h.start - cur.end <= gap:
                cur.end = max(cur.end, h.end)
                if h.score > cur.score:
                    cur.best, cur.score = h.time, h.score
            else:
                if cur is not None:
                    out.append(cur)
                cur = Moment(m, h.start, h.end, h.time, h.score)
        if cur is not None:
            out.append(cur)
    out.sort(key=lambda x: -x.score)
    return out
