"""
Módulo de IA: RECONOCER EL RITMO de la música que pones en tus videos (la misma escucha que los edits).

  · tempo y golpes, pegados al bombo real (no al contratiempo)
  · inicio de cada compás (el «1») y golpes fuertes (bombo o caja con fuerza)
  · partes de la canción (intro, subida, drop, pausa, final), el drop y las paradas
Todo en segundos del ARCHIVO. Se guarda en caché: la segunda vez es instantáneo.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from . import music_analysis

VERSION = 1
KIND_ES = {"intro": "Intro", "build": "Subida", "drop": "Drop", "break": "Pausa", "outro": "Final"}


def _cache_file(path: str) -> str:
    try:
        st = os.stat(path)
        size, mt = st.st_size, int(st.st_mtime)
    except OSError:          # la canción ya no está: sin fallar (simplemente no habrá ritmo guardado)
        size, mt = 0, 0
    key = f"{os.path.normcase(os.path.abspath(path))}|{size}|{mt}|{VERSION}"
    return str(cache_dir("ritmo") / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".json"))


def cached(path: str) -> dict | None:
    try:
        with open(_cache_file(path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def analyze(path: str, cancelled=None) -> dict:
    """{"tempo", "beats", "downbeats", "strong", "drop", "sections": [{a, b, kind}], "stops", "duration"}
    cancelled: función opcional (como en los trabajos en segundo plano); si devuelve True, se para entre etapas."""
    hit = cached(path)
    if hit is not None:
        return hit
    from . import edit_engine, edit_maker
    from .base import Cancelled
    sr = music_analysis.SR
    samples = media_tools.decode_mono(path, sr)
    if cancelled is not None and cancelled():
        raise Cancelled()
    song = edit_maker.analyze_song(path, samples)
    if cancelled is not None and cancelled():
        raise Cancelled()
    if len(song["beats"]) >= 4:
        edit_engine.enrich(song, samples, sr)
        beats = song["beats"]
        hits = song["hits"]
        phase = song.get("downbeat_phase", 0)
        downbeats = beats[phase::4]
        strong = [b for b, h in zip(beats, hits) if max(h["kick"], h["snare"]) >= 0.7]
        drop = edit_maker.find_drop(song)
        sections = [{"a": round(s["a"], 3), "b": round(s["b"], 3), "kind": s["kind"]} for s in song["sections"]]
        stops = [list(x) for x in song.get("stops", [])]
    else:   # sin ritmo claro (voz, ambiente…)
        beats, downbeats, strong, drop, sections, stops = song["beats"], [], [], None, [], []
    tempo = float(song.get("tempo", 0.0))
    if len(beats) >= 8:   # el tempo de la rejilla ya corregida (más exacto)
        tempo = 60.0 / float(np.median(np.diff(beats)))
    out = {"tempo": round(tempo, 1), "beats": [round(b, 4) for b in beats],
           "downbeats": [round(b, 4) for b in downbeats], "strong": [round(b, 4) for b in strong],
           "drop": None if drop is None else round(float(drop), 3), "sections": sections, "stops": stops,
           "duration": round(len(samples) / sr, 3)}
    try:
        tmp = _cache_file(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, _cache_file(path))
    except OSError:
        pass
    return out


def to_timeline(r: dict, source_in: float, duration: float, start: float) -> dict:
    """Los puntos de ritmo de un clip, en tiempo de la timeline (solo los que caen dentro del clip)."""
    def conv(ts):
        return [start + (t - source_in) for t in ts if source_in - 1e-6 <= t < source_in + duration]
    out = {"beats": conv(r.get("beats", [])), "downbeats": conv(r.get("downbeats", [])),
           "strong": conv(r.get("strong", [])), "drop": None, "sections": []}
    if r.get("drop") is not None and source_in <= r["drop"] < source_in + duration:
        out["drop"] = start + r["drop"] - source_in
    for s in r.get("sections", []):
        if s["b"] > source_in and s["a"] < source_in + duration:
            out["sections"].append({"a": start + max(s["a"], source_in) - source_in,
                                    "b": start + min(s["b"], source_in + duration) - source_in, "kind": s["kind"]})
    return out


def summary(r: dict) -> str:
    parts = [f"{r['tempo']:g} BPM"] if r.get("tempo") else []
    if r.get("drop") is not None:
        m, s = divmod(r["drop"], 60)
        parts.append(f"drop a los {int(m)}:{s:04.1f}")
    kinds = [KIND_ES.get(s["kind"], s["kind"]) for s in r.get("sections", [])]
    if kinds:
        parts.append(" → ".join(kinds[:8]) + ("…" if len(kinds) > 8 else ""))
    return " · ".join(parts) or "sin ritmo claro"
