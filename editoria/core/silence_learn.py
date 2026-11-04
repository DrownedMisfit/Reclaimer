"""
◈ El corte de silencios aprende de lo que TÚ haces después (el usuario: «que aprenda de mis acciones»).

Al quitar silencios se apunta cada borde que creó el corte (dónde terminaba la voz a la izquierda y dónde empezaba a la
derecha, en tiempo del archivo). Si luego tú:
  · ALARGAS ese borde (el final de una palabra se había ido): quería más margen ahí;
  · lo ACORTAS más: sobraba margen.
Cada borde cuenta una vez (lo último que dejaste); si lo devuelves a como estaba (o deshaces), deja de contar. Partir un
trozo en dos o borrarlo no cuenta. Con al menos MIN_OBS retoques de un lado, la siguiente vez se ajusta ese margen (la
mediana de lo que moviste, con tope).

  snapshot(project, clip_ids) / new_edges(project, before) — al cortar
  observe(project, edges) — tras cada cambio (con calma); guarda en datos/modelos/silencio_aprendido.json
  learned() -> {"before": s, "after": s, "n_before": k, "n_after": k}   ·   reset()
"""
from __future__ import annotations

import json
import os
import time

MIN_OBS = 3                 # retoques de un lado antes de ajustar
KEEP = 60                   # los últimos 60 de cada lado
MAX_MOVE = 0.6              # más que esto no es «afinar un borde» (es otra edición)
MIN_MOVE = 0.004
CLAMP = (-0.15, 0.40)       # lo que se ajusta como mucho (segundos)
TOL = 0.002


def _path() -> str:
    from .paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "modelos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "silencio_aprendido.json")


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _path())


def _src_out(c) -> float:
    return float(c.source_in) + float(c.src_len)


def snapshot(project, clip_ids) -> dict:
    """Antes de cortar: los trozos de esos archivos {id: (media_id, desde, hasta)} (tiempo del archivo)."""
    mids = {project.clips[i].media_id for i in clip_ids if i in project.clips}
    return {c.id: (c.media_id, float(c.source_in), _src_out(c)) for c in project.clips.values()
            if c.media_id in mids and c.text is None}


def new_edges(project, before: dict) -> list[dict]:
    """Después de cortar: los bordes que creó el corte (no estaban antes). Solo de las pistas de audio (o del video
    con sonido propio si no hay audio aparte): así un retoque de imagen+sonido vinculados no cuenta dos veces."""
    from .model import TRACK_AUDIO
    old_starts: dict[str, list] = {}
    old_ends: dict[str, list] = {}
    for mid, a, b in before.values():
        old_starts.setdefault(mid, []).append(a)
        old_ends.setdefault(mid, []).append(b)
    mids = set(old_starts)
    clips = [c for c in project.clips.values() if c.media_id in mids and c.text is None]
    audio = [c for c in clips if project.track(c.track_id) is not None
             and project.track(c.track_id).kind == TRACK_AUDIO]
    use = audio or [c for c in clips if not c.link]
    out = []
    for c in use:
        if not any(abs(c.source_in - a) < TOL for a in old_starts.get(c.media_id, [])):
            out.append({"clip": c.id, "side": "before", "src": float(c.source_in), "media": c.media_id})
        if not any(abs(_src_out(c) - b) < TOL for b in old_ends.get(c.media_id, [])):
            out.append({"clip": c.id, "side": "after", "src": _src_out(c), "media": c.media_id})
    return out


def observe(project, edges: list[dict]) -> int:
    """Mira cómo están ahora esos bordes y apunta tus retoques. Devuelve cuántos retoques cuentan ahora."""
    if not edges:
        return 0
    d = _load()
    obs = d.setdefault("obs", {})
    changed = False
    for e in edges:
        key = f"{e['clip']}:{e['side']}"
        c = project.clips.get(e["clip"])
        if c is None:                            # borrado / deshecho el corte: no cuenta
            continue
        if e["side"] == "before":
            delta = e["src"] - float(c.source_in)          # > 0: lo alargaste hacia atrás (más margen antes)
        else:
            cur = _src_out(c)
            delta = cur - e["src"]                          # > 0: lo alargaste hacia delante (más margen después)
            if delta < -MIN_MOVE and any(o.media_id == c.media_id and o.id != c.id and abs(o.source_in - cur) < 0.04
                                         for o in project.clips.values()):
                delta = 0.0                                 # (partiste el trozo en dos: no es un retoque del borde)
        if abs(delta) < MIN_MOVE or abs(delta) > MAX_MOVE:
            if key in obs:
                del obs[key]
                changed = True
            continue
        if obs.get(key, {}).get("delta") != round(delta, 4):
            obs[key] = {"side": e["side"], "delta": round(delta, 4), "t": time.time()}
            changed = True
    for side in ("before", "after"):                         # solo los últimos KEEP de cada lado
        ks = sorted((k for k, v in obs.items() if v["side"] == side), key=lambda k: obs[k]["t"])
        for k in ks[:-KEEP]:
            del obs[k]
            changed = True
    if changed:
        _save(d)
    return len(obs)


def learned() -> dict:
    """Lo aprendido: cuánto margen añadir (o quitar) antes y después de cada frase."""
    import statistics
    obs = _load().get("obs", {})
    out = {}
    for side in ("before", "after"):
        vals = [v["delta"] for v in obs.values() if v["side"] == side]
        out["n_" + side] = len(vals)
        out[side] = (min(CLAMP[1], max(CLAMP[0], statistics.median(vals))) if len(vals) >= MIN_OBS else 0.0)
    return out


def describe(lr: dict) -> str:
    parts = []
    for side, name in (("before", "antes"), ("after", "después")):
        if lr.get("n_" + side, 0) >= MIN_OBS and abs(lr.get(side, 0)) >= 0.005:
            parts.append(f"{lr[side] * 1000:+.0f} ms {name}")
    return ", ".join(parts)


def reset() -> None:
    try:
        os.remove(_path())
    except OSError:
        pass
