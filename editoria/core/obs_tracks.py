"""
🎙 / 🎮 Pistas de audio separadas de OBS: si tu grabación tiene VARIAS pistas de audio (OBS → Salida → Grabación →
«Pistas de audio» 1, 2, 3…), cada una se saca a su archivo (copia exacta, sin perder calidad) y se reconoce:
  · la MEZCLA (todo junto: igual a la suma de las otras)  → no hace falta (duplicaría)
  · una pista en SILENCIO                                 → fuera (p. ej. el micrófono no estaba en esa pista)
  · el MICRÓFONO (tu voz): igual por izquierda y derecha (los micros son mono) y casi solo frecuencias de voz
  · el JUEGO / ESCRITORIO: estéreo y con todo tipo de sonidos
  · si en la grabación SOLO sonó tu micrófono (el juego en silencio), igual sale tu voz sola (para transcribirla)
Al poner el video en la línea de tiempo: la imagen arriba, tu voz en la pista de voz y el juego en otra, VINCULADOS
(se mueven y cortan juntos; cada uno con su volumen).

  split(path) -> {"tracks": [{"k", "path", "role": "voz"|"juego", "label"}], "note": "…"}   (se guarda: instantáneo)
Los archivos van a «Audio extraído/Pistas de OBS» (dentro de Reclaimer, nunca junto a tus grabaciones).
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import numpy as np

from . import media as media_tools
from .paths import cache_dir

SR = 16000
MAX_S = 300.0              # para reconocerlas basta con los primeros 5 minutos
SILENT_DB = -55.0
VERSION = 2                # (cambia si cambia lo que se reconoce: se vuelve a mirar)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ROLE_LABEL = {"voz": "🎙 Micrófono (tu voz)", "juego": "🎮 Juego / escritorio"}


def audio_streams(path: str) -> list[dict]:
    r = subprocess.run([media_tools.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index,codec_name,channels:stream_tags=title", "-of", "json", path],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return json.loads(r.stdout or "{}").get("streams", [])
    except ValueError:
        return []


def _pcm(path: str, k: int) -> np.ndarray:
    r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-t", f"{MAX_S}", "-i", path,
                        "-map", f"0:a:{k}", "-ac", "2", "-ar", str(SR), "-f", "s16le", "-"],
                       capture_output=True, creationflags=NO_WINDOW)
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
    return a[: len(a) // 2 * 2].reshape(-1, 2)


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    if x.std() < 1e-6 or y.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def _voice_ratio(mono: np.ndarray) -> float:
    """Qué parte de la energía está en las frecuencias de la voz (300–3400 Hz)."""
    n = 4096
    if len(mono) < n:
        return 0.0
    frames = mono[: len(mono) // n * n].reshape(-1, n)[:: max(1, len(mono) // n // 200)]
    spec = (np.abs(np.fft.rfft(frames * np.hanning(n), axis=1)) ** 2).sum(axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    tot = float(spec[f > 60].sum()) + 1e-12
    return float(spec[(f >= 300) & (f <= 3400)].sum()) / tot


def classify(path: str) -> dict:
    """{"keep": [(k, rol)], "note": texto}: qué pistas sirven y qué es cada una."""
    streams = audio_streams(path)
    if len(streams) < 2:
        return {"keep": [], "note": ""}
    data = {k: _pcm(path, k) for k in range(len(streams))}
    mono = {k: a.mean(axis=1) for k, a in data.items()}
    notes = []
    live = []
    dup = set()
    for k, a in data.items():
        peak = float(np.abs(a).max()) if a.size else 0.0
        if 20 * np.log10(peak + 1e-9) < SILENT_DB:
            notes.append(f"la pista {k + 1} está en silencio")
        else:
            live.append(k)
    # Duplicadas (p. ej. la mezcla cuando el micro no sonó): se queda la de número más alto
    for k in list(live):
        if any(o > k and abs(_corr(mono[k], mono[o])) > 0.99 for o in live):
            live.remove(k)
            dup.update(o for o in live if o > k and abs(_corr(mono[k], mono[o])) > 0.99)
            notes.append(f"la pista {k + 1} es igual a otra")
    # La mezcla = la suma de las otras
    if len(live) >= 3:
        for k in list(live):
            others = [o for o in live if o != k]
            if _corr(mono[k], sum(mono[o] for o in others)) > 0.95:
                live.remove(k)
                notes.append(f"la pista {k + 1} es la mezcla de todo")
                break
    # ¿Cuál es el micrófono? mono (izquierda = derecha) y con energía en la voz
    score = {}
    for k in live:
        a = data[k]
        stereo_same = _corr(a[:, 0], a[:, 1]) if len(a) else 0.0
        score[k] = (1.0 if stereo_same > 0.98 or streams[k].get("channels") == 1 else 0.0) + _voice_ratio(mono[k])
    if len(live) == 1 and live[0] in dup and score[live[0]] >= 1.0:
        # solo sonó tu micrófono (la mezcla = tu voz y el juego en silencio): tu voz sola, p. ej. para transcribirla
        notes.append(f"solo sonó tu micrófono (pista {live[0] + 1})")
        return {"keep": [(live[0], "voz")], "note": "; ".join(notes)}
    if len(live) < 2:
        return {"keep": [], "note": "; ".join(notes)}
    mic = max(live, key=lambda k: score[k])
    keep = [(k, "voz" if k == mic else "juego") for k in live]
    return {"keep": keep, "note": "; ".join(notes)}


def out_dir() -> str:
    from .audio_extract import out_dir as base
    d = os.path.join(base(), "Pistas de OBS")
    os.makedirs(d, exist_ok=True)
    return d


def split(path: str) -> dict:
    """Saca cada pista útil a su archivo (copia exacta si es AAC). Se guarda: la segunda vez es instantáneo."""
    cf = os.path.join(str(cache_dir("pistas_obs")), f"{media_tools.cache_key(path)}.json")
    try:
        with open(cf, encoding="utf-8") as f:
            res = json.load(f)
        if res.get("v") == VERSION and all(os.path.exists(t["path"]) for t in res.get("tracks", [])):
            return res
    except (OSError, ValueError):
        pass
    info = classify(path)
    streams = audio_streams(path)
    stem = re.sub(r'[<>:"/\\|?*]+', " ", os.path.splitext(os.path.basename(path))[0]).strip() or "grabación"
    tracks = []
    n_juego = sum(1 for _k, r in info["keep"] if r == "juego")
    for i, (k, role) in enumerate(info["keep"]):
        label = ROLE_LABEL[role] + (f" {i + 1}" if role == "juego" and n_juego > 1 else "")
        codec = (streams[k].get("codec_name") or "") if k < len(streams) else ""
        out = os.path.join(out_dir(), f"{stem} · {'Micrófono' if role == 'voz' else 'Juego'}"
                                      f"{'' if role == 'voz' or n_juego == 1 else ' ' + str(i + 1)}.m4a")
        args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", path, "-map", f"0:a:{k}", "-vn"]
        args += ["-c:a", "copy"] if codec == "aac" else ["-c:a", "aac", "-b:a", "256k"]
        r = subprocess.run(args + [out], capture_output=True, creationflags=NO_WINDOW)
        if r.returncode == 0 and os.path.exists(out):
            tracks.append({"k": k, "path": out, "role": role, "label": label})
    if len(tracks) < 2 and not (tracks and tracks[0]["role"] == "voz"):
        tracks = []
    res = {"v": VERSION, "tracks": tracks, "note": info["note"]}
    try:
        with open(cf, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    except OSError:
        pass
    return res
