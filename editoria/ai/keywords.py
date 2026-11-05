"""
🔑 Buscar PALABRAS CLAVE en el audio, gastando poco (procesador a medio gas, nada de tarjeta gráfica):

  1. Un detector de voz muy pequeño (Silero VAD, ya incluido) busca dónde se HABLA: el silencio, la música y
     el ruido se saltan (en gameplay o tráileres suele quedar poca voz).
  2. Solo esos trozos (cortos) se escuchan con un modelo de voz pequeño (Whisper «base», ~145 MB, una sola
     vez). (Avisarle de las palabras que buscas le hacía saltarse frases: los nombres se encuentran en el paso 3.)
  3. Se compara sin acentos ni mayúsculas y tolerando pequeños errores («Marcos» encuentra «Marcus»).
  4. Lo escuchado se guarda: la próxima búsqueda en ese archivo (con cualquier palabra) es instantánea.
     Si el archivo ya estaba transcrito del todo (Limpieza de voz), se usa eso y no se escucha nada.

  find(path, words, …) -> [{"t0", "t1", "word", "said", "context", "score"}]   (segundos del archivo)
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from .base import check_cancel, report

MODEL = "base"
SR = 16000
CHUNK = 15.0          # segundos por trozo de voz que se escucha de una vez (cortos: no se salta frases)
THREADS = 2           # pocos núcleos: puedes seguir editando mientras busca


def norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]+", " ", t).strip()


def parse_query(text: str) -> list[str]:
    """«marcus, la traición; explosión» → ["marcus", "la traicion", "explosion"]"""
    return [norm(p) for p in re.split(r"[,;\n]+", text) if norm(p)]


def _similar(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b[:5]) or b.startswith(a[:5])):   # traición / traicionó
        return max(0.86, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def match(words: list[list], query: list[str], min_score: float = 0.78) -> list[dict]:
    """words = [[ini, fin, texto, conf], …] → dónde se dice cada palabra/frase buscada."""
    toks = [(w[0], w[1], norm(w[2])) for w in words]
    toks = [t for t in toks if t[2]]
    hits = []
    for q in query:
        qw = q.split()
        n = len(qw)
        for i in range(0, max(0, len(toks) - n + 1)):
            seg = toks[i:i + n]
            score = sum(_similar(a, s[2]) for a, s in zip(qw, seg)) / n
            if score >= min_score:
                ctx = " ".join(t[2] for t in toks[max(0, i - 6):i + n + 6])
                hits.append({"t0": seg[0][0], "t1": seg[-1][1], "word": q,
                             "said": " ".join(s[2] for s in seg), "context": ctx, "score": round(score, 2)})
    hits.sort(key=lambda h: (h["t0"], -h["score"]))
    out = []
    for h in hits:                 # la misma palabra dos veces en el mismo sitio: una
        if out and abs(out[-1]["t0"] - h["t0"]) < 0.3 and out[-1]["word"] == h["word"]:
            continue
        out.append(h)
    return out


def _cache_file(path: str) -> str:
    return str(cache_dir("palabras") / f"{media_tools.cache_key(path)}_{MODEL}.json")


def cached_words(path: str) -> list | None:
    try:
        with open(_cache_file(path), encoding="utf-8") as f:
            return json.load(f)["words"]
    except (OSError, ValueError, KeyError):
        return None


def speech_regions(samples: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=350, speech_pad_ms=200,
                                                   min_speech_duration_ms=250))
    regs = [(t["start"] / SR, t["end"] / SR) for t in ts]
    merged: list[list[float]] = []
    for a, b in regs:              # se juntan los cercanos en trozos de hasta CHUNK segundos
        if merged and a - merged[-1][1] < 0.3 and b - merged[-1][0] <= CHUNK:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


_model = None


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        from .transcription import models_dir
        from ..core.hw import whisper_device
        device, ctype = whisper_device()
        _model = WhisperModel(MODEL, device=device, compute_type=ctype, cpu_threads=THREADS,
                              download_root=str(models_dir()))
    return _model


def listen(path: str, hint: list[str] | None = None, progress=None, cancelled=None,
           language: str = "es") -> list[list]:
    """Las palabras dichas en el archivo (solo donde hay voz), con su tiempo. Se guarda en caché."""
    got = cached_words(path)
    if got is not None:
        return got
    report(progress, 0.02, "🔑 Buscando dónde se habla…")
    samples = media_tools.decode_mono(path, SR)
    check_cancel(cancelled)
    regs = speech_regions(samples)
    total = sum(b - a for a, b in regs) or 1.0
    report(progress, 0.08, f"🔑 Hay voz en {total / 60:.1f} min de {len(samples) / SR / 60:.1f}; escuchando…")
    model = _load()
    words: list[list] = []
    done = 0.0
    for a, b in regs:
        check_cancel(cancelled)
        seg = samples[int(a * SR):int(b * SR)]
        if len(seg) < SR * 0.2:
            continue
        parts, _info = model.transcribe(seg, language=language or None, word_timestamps=True, beam_size=1,
                                        vad_filter=False, condition_on_previous_text=False)
        for p in parts:
            for w in p.words or []:
                if w.word.strip():
                    words.append([round(a + float(w.start), 3), round(a + float(w.end), 3), w.word.strip(),
                                  round(float(w.probability), 3)])
        done += b - a
        report(progress, 0.08 + 0.9 * done / total, f"🔑 Escuchando · {int(100 * done / total)} %")
    try:
        with open(_cache_file(path), "w", encoding="utf-8") as f:
            json.dump({"words": words, "speech": regs}, f)
    except OSError:
        pass
    return words


def find(path: str, query: list[str], transcript: dict | None = None, progress=None, cancelled=None,
         language: str = "es") -> list[dict]:
    """Dónde se dicen las palabras buscadas en ese archivo (usa la transcripción completa si ya existe)."""
    words = (transcript or {}).get("words") or listen(path, query, progress, cancelled, language)
    return match(words, query)
