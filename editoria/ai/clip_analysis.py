"""
Módulo de IA: CLASIFICACIÓN DE CLIPS.

Mira varios fotogramas de cada clip y decide:
  - Tipo: Gameplay / Cinemática / Menú / Pantalla de carga
  - Contenido: combate, exploración, diálogo, jefe, paisaje...
Además guarda la "huella" de cada fotograma para poder buscar clips con frases
("Marcus peleando contra varios enemigos") y proponer B-roll.

Funciona "sin entrenamiento" (zero-shot): compara cada fotograma con descripciones
escritas de cada categoría. Por eso añadir una categoría nueva es solo escribir frases.
"""
from __future__ import annotations

import os

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from . import embeddings
from .base import CancelFn, ProgressFn, check_cancel, report

VERSION = 1  # cambia si cambia el análisis (invalida la caché)

TYPE_PROMPTS = {
    "Gameplay": ["a screenshot of video game gameplay with a HUD, health bar and crosshair",
                 "third person shooter gameplay, the player aiming a gun at enemies",
                 "a video game character running through a level, gameplay footage"],
    "Cinemáticas": ["a cinematic cutscene from a video game with black letterbox bars",
                    "a dramatic close-up of a character's face in a movie scene",
                    "a cinematic shot of characters talking in a cutscene"],
    "Menús": ["a video game menu screen with text options",
              "a settings menu with a list of options",
              "an inventory or map screen of a video game"],
    "Pantalla de carga": ["a loading screen with a progress bar",
                          "a black screen with a small logo or text"],
}

CONTENT_PROMPTS = {
    "combate": ["characters fighting and shooting at enemies", "an intense battle with explosions and gunfire",
                "melee combat against monsters"],
    "jefe": ["a fight against a giant boss monster", "a huge creature attacking the player"],
    "exploración": ["a character walking and exploring an environment", "a quiet corridor or path",
                    "a character walking through ruins"],
    "diálogo": ["two characters talking to each other", "a conversation scene with subtitles"],
    "personaje": ["a close-up portrait of a character's face", "a character's face showing emotion"],
    "paisaje": ["a wide landscape view with sky", "a scenic vista of a city or ruins"],
    "vehículo": ["driving a vehicle", "a vehicle chase"],
    "arma": ["a close-up of a weapon", "the player holding a large gun"],
    "texto en pantalla": ["a screen full of text and menus", "subtitles and interface text"],
    "oscuro": ["a dark scene at night", "a creepy horror atmosphere in darkness"],
}

_prompt_cache: dict[str, tuple[list[str], np.ndarray]] = {}


def _label_vectors(name: str, prompts: dict[str, list[str]]) -> tuple[list[str], np.ndarray]:
    """Una huella media por categoría (a partir de sus frases)."""
    if name not in _prompt_cache:
        enc = embeddings.get("clip_text")
        labels = list(prompts)
        vecs = []
        for label in labels:
            v = enc.encode(prompts[label]).mean(axis=0)
            vecs.append(v / np.linalg.norm(v))
        _prompt_cache[name] = (labels, np.stack(vecs))
    return _prompt_cache[name]


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


def sample_times(duration: float, max_frames: int = 12, every: float = 4.0) -> list[float]:
    """Momentos repartidos por el clip (uno cada ~4 s, entre 3 y 12)."""
    if duration <= 0:
        return [0.0]
    n = int(min(max_frames, max(3, round(duration / every))))
    return [duration * (i + 0.5) / n for i in range(n)]


def letterbox_ratio(frames: np.ndarray) -> float:
    """Proporción de fotogramas con bandas negras arriba y abajo (típico de cinemáticas)."""
    h = frames.shape[1]
    band = max(2, int(h * 0.08))
    top = frames[:, :band].reshape(len(frames), -1).max(axis=1)
    bottom = frames[:, -band:].reshape(len(frames), -1).max(axis=1)
    middle = frames[:, h // 3: 2 * h // 3].reshape(len(frames), -1).mean(axis=1)
    return float(np.mean((top < 28) & (bottom < 28) & (middle > 20)))


def classify(frame_vecs: np.ndarray, letterbox: float = 0.0) -> dict:
    """Tipo y contenido de un clip a partir de las huellas de sus fotogramas."""
    t_labels, t_vecs = _label_vectors("type", TYPE_PROMPTS)
    c_labels, c_vecs = _label_vectors("content", CONTENT_PROMPTS)
    t_probs = _softmax(100 * frame_vecs @ t_vecs.T).mean(axis=0)
    if letterbox >= 0.5:  # bandas negras en la mayoría de fotogramas: casi seguro cinemática
        t_probs = t_probs.copy()
        t_probs[t_labels.index("Cinemáticas")] += 0.35 * letterbox
        t_probs /= t_probs.sum()
    c_probs = _softmax(100 * frame_vecs @ c_vecs.T).mean(axis=0)
    order = np.argsort(-c_probs)
    tags = [c_labels[i] for i in order[:3] if c_probs[i] >= 0.15 or i == order[0]]
    return {"type": t_labels[int(t_probs.argmax())], "type_conf": float(t_probs.max()), "tags": tags,
            "scores": {c_labels[i]: round(float(c_probs[i]), 3) for i in range(len(c_labels))}}


def _cache_path(path: str) -> str:
    return str(cache_dir("huellas_clips") / f"{media_tools.cache_key(path)}_v{VERSION}.npz")


def load_cached(path: str) -> tuple[np.ndarray, np.ndarray, float] | None:
    """(momentos, huellas, bandas negras) si este archivo ya se analizó antes."""
    try:
        f = _cache_path(path)
        if os.path.exists(f):
            d = np.load(f)
            return d["times"], d["vecs"].astype(np.float32), float(d["letterbox"])
    except (OSError, ValueError, KeyError):
        pass
    return None


def analyze_clip(path: str, kind: str, duration: float, progress: ProgressFn = None,
                 cancelled: CancelFn = None) -> dict:
    """Analiza un clip (o imagen). Devuelve {"times", "vecs", "type", "tags", ...}."""
    cached = load_cached(path)
    if cached is not None:
        times, vecs, lb = cached
    else:
        times = [0.0] if kind == "image" else sample_times(duration)
        check_cancel(cancelled)
        frames = media_tools.sample_frames(path, times)
        times = np.array(times[:len(frames)], np.float32)
        vecs = embeddings.get("clip_image", progress).encode(frames)
        lb = letterbox_ratio(frames) if len(frames) >= 2 else 0.0
        np.savez_compressed(_cache_path(path), times=times, vecs=vecs.astype(np.float16), letterbox=lb)
    result = classify(vecs, lb)
    if kind == "video":       # pistas sencillas (HUD fijo, barras negras, arma abajo…): mandan si son claras
        cu = simple_cues(path, duration)
        if cu.get("type"):
            result["type"] = cu["type"]
            result["type_conf"] = max(float(result.get("type_conf", 0)), 0.8)
        if cu.get("view") and cu["view"] not in result["tags"]:
            result["tags"] = list(result["tags"]) + [cu["view"]]
    result.update(times=np.asarray(times, np.float32), vecs=vecs.astype(np.float32))
    return result


def simple_cues(path: str, duration: float) -> dict:
    """¿Gameplay o cinemática? ¿Primera o tercera persona? (ver ai/shot_cues.py; se guarda en caché)."""
    import json
    cp = cache_dir("pistas") / f"{media_tools.cache_key(path)}.json"
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    from . import shot_cues
    try:
        cu = shot_cues.cues(path, sample_times(duration))
    except Exception:  # noqa: BLE001 - una pista que falla no debe parar el análisis
        return {}
    try:
        cp.write_text(json.dumps(cu, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return cu


def metadata_text(name: str, category: str, ai_type: str, ai_tags: list[str], tags: list[str]) -> str:
    """Lo que se SABE de un clip, en palabras (tipo, lo que se ve, tus etiquetas y carpetas, nombre)."""
    base = os.path.splitext(name)[0].replace("_", " ").replace("-", " ")
    # la categoría que pusiste tú va SIEMPRE (aunque la IA haya dado otro tipo)
    parts = [ai_type, category if category and category != ai_type else "", ", ".join(ai_tags), ", ".join(tags), base]
    return ". ".join(p for p in parts if p)


def metadata_scores(query: str, metas: dict[str, str]) -> dict[str, float]:
    """Parecido entre la frase y lo que se sabe de cada clip (0..1) + coincidencia exacta de palabras."""
    from ..core.organize import normalize, words
    if not metas:
        return {}
    enc = embeddings.get("sentence")
    ids = list(metas)
    qv = enc.encode([query])[0]
    mv = enc.encode([metas[i] for i in ids])
    sims = mv @ qv
    q_words = {w for w in words(query) if len(w) >= 3}
    out = {}
    for i, mid in enumerate(ids):
        exact = bool(q_words & set(words(metas[mid])))
        out[mid] = float(max(0.0, sims[i])) + (0.5 if exact else 0.0)
    return out


def search(query_vec: np.ndarray, clips: dict[str, tuple[np.ndarray, np.ndarray]],
           top: int = 30, meta: dict[str, float] | None = None) -> list[tuple[str, float, float]]:
    """
    Clips más parecidos a una frase: [(media_id, puntuación, mejor momento)].
    Mezcla lo que la IA VE (huellas de los fotogramas) con lo que se SABE del clip (meta).
    """
    out = []
    for mid, (times, vecs) in clips.items():
        sims = vecs @ query_vec
        k = int(sims.argmax())
        # El mejor fotograma manda, pero cuenta un poco que el clip entero encaje
        score = float(0.8 * sims[k] + 0.2 * sims.mean())
        if meta:
            score += 0.06 * meta.get(mid, 0.0)
        out.append((mid, score, float(times[k])))
    out.sort(key=lambda r: -r[1])
    return out[:top]


def warm_up(progress: ProgressFn = None):
    report(progress, 0.0, "Cargando la IA de imágenes…")
    embeddings.get("clip_image", progress)
    embeddings.get("clip_text", progress)
    _label_vectors("type", TYPE_PROMPTS)
    _label_vectors("content", CONTENT_PROMPTS)
