"""
✎ Corregir una palabra de la transcripción, con alternativas al momento (clic derecho en la palabra).

  alternatives(path, words, idx, model_name, language, progress, cancelled) -> ["a ver", "haber", …]
      Vuelve a ESCUCHAR solo ese trocito (unos segundos alrededor de la palabra) con Whisper de varias maneras —sin
      contexto, con las frases de antes, más «suelto»— y devuelve lo que oye justo donde está la palabra: lo más
      repetido primero y nunca lo que ya pone. Tarda unos segundos (el modelo se queda cargado).
  learned(word) -> ["corrección", …]       cómo la corregiste otras veces (lo más usado primero)
  remember(wrong, right)                   cada corrección se guarda (datos/correcciones_texto.json)
  vocabulary() / add_vocabulary(word)      palabras que Whisper tendrá en cuenta al transcribir (nombres de juegos,
                                           personas…): datos/vocabulario.json
  with_punct(original, new)                la corrección conserva los signos de la palabra («haber,» → «a ver,»)
"""
from __future__ import annotations

import collections
import json
import os
import re
import time

import numpy as np

from ..core.paths import app_data_dir
from .base import CancelFn, ProgressFn, check_cancel, report

SR = 16000
PAD = 0.15            # margen alrededor de la palabra para reconocer lo que oye «en su sitio»
_LEAD = "¿¡\"'«(["
_TRAIL = ".,;:!?…\"'»)]"


def core(word: str) -> str:
    """La palabra sin los signos de alrededor."""
    return word.strip().lstrip(_LEAD).rstrip(_TRAIL).strip()


def with_punct(original: str, new: str) -> str:
    o = original.strip()
    lead = o[:len(o) - len(o.lstrip(_LEAD))]
    trail = o[len(o.rstrip(_TRAIL)):]
    return f"{lead}{core(new)}{trail}"


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", core(text).lower())


# ------------------------------------------------------------------ correcciones y vocabulario guardados
def _path(name: str) -> str:
    return os.path.join(str(app_data_dir()), name)


def _read(name: str, default):
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    try:
        with open(_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def remember(wrong: str, right: str) -> None:
    w, r = _key(wrong), core(right)
    if not w or not r or w == _key(r):
        return
    data = _read("correcciones_texto.json", {})
    d = data.setdefault(w, {})
    d[r] = d.get(r, 0) + 1
    _write("correcciones_texto.json", data)


def learned(word: str) -> list[str]:
    d = _read("correcciones_texto.json", {}).get(_key(word), {})
    return [r for r, _n in sorted(d.items(), key=lambda x: -x[1])]


def vocabulary() -> list[str]:
    return [w for w in _read("vocabulario.json", []) if isinstance(w, str) and w.strip()]


def add_vocabulary(word: str) -> bool:
    w = core(word)
    voc = vocabulary()
    if not w or any(v.lower() == w.lower() for v in voc):
        return False
    _write("vocabulario.json", voc + [w])
    return True


def hotwords() -> str | None:
    """Para Whisper: las palabras del vocabulario (o nada)."""
    voc = vocabulary()
    return " ".join(voc[-60:]) if voc else None


# ------------------------------------------------------------------ volver a escuchar
def _decode(path: str, a: float, b: float) -> np.ndarray:
    from ..core import media as media_tools
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{a:.3f}", "-t",
                               f"{b - a:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                              timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-200:] or "no se pudo leer el audio")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def window(words: list, idx: int) -> tuple[float, float]:
    """El trocito a escuchar: unas palabras antes y después (entre 1 y 2,5 s a cada lado: corto = rápido)."""
    w0, w1 = float(words[idx][0]), float(words[idx][1])
    a = float(words[max(0, idx - 3)][0]) - 0.3
    b = float(words[min(len(words) - 1, idx + 3)][1]) + 0.3
    return max(0.0, min(a, w0 - 1.0), w0 - 2.5), min(max(b, w1 + 1.0), w1 + 2.5)


def heard_at(found: list, w0: float, w1: float) -> str:
    """Lo que se oyó justo donde está la palabra: las palabras que caen al menos a la mitad dentro de ella (con un
    margen pequeño, porque los tiempos de una escucha y otra no coinciden del todo; la de al lado no se cuela)."""
    a, b = w0 - PAD / 3, w1 + PAD / 3
    got = [w[2] for w in found if min(b, w[1]) - max(a, w[0]) >= 0.5 * max(0.02, w[1] - w[0])]
    return core(" ".join(core(x) for x in got if core(x)))


def rank(original: str, candidates: list[str]) -> list[str]:
    """Las alternativas distintas de lo que ya pone, lo más repetido primero (con su forma más común)."""
    cnt: collections.Counter = collections.Counter()
    form: dict[str, collections.Counter] = {}
    for c in candidates:
        c = core(c)
        k = _key(c)
        if not k or k == _key(original):
            continue
        cnt[k] += 1
        form.setdefault(k, collections.Counter())[c] += 1
    out = []
    for k, _n in cnt.most_common():
        c = form[k].most_common(1)[0][0]
        if core(original)[:1].islower() and c[:1].isupper() and c[1:] == c[1:].lower() and " " not in c:
            c = c[:1].lower() + c[1:]           # (la mayúscula era solo por empezar el trocito)
        out.append(c)
    return out


def spot(window_words: list[str], k: int, hyp: str) -> str:
    """En una interpretación del trocito entero, lo que corresponde a la palabra k (se alinean las palabras de lo que
    ya pone con las de lo que se oye: «… el compadre se siente …» frente a «… el combate se siente …» → «combate»)."""
    from difflib import SequenceMatcher
    A = [core(w).lower() for w in window_words]
    raw = [x for x in hyp.split() if core(x)]
    B = [core(x).lower() for x in raw]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, A, B, autojunk=False).get_opcodes():
        if not i1 <= k < i2:
            continue
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            return core(raw[j1 + k - i1])
        if tag == "replace" and i2 - i1 == 1 and j2 - j1 <= 3:       # una palabra que eran varias («haber» → «a ver»)
            return core(" ".join(raw[j1:j2]))
        return ""
    return ""


def _nbest(model, clip: np.ndarray, language: str, before: str, n: int = 5) -> list[str]:
    """UNA escucha y sus n mejores interpretaciones del trocito entero. Whisper trabaja siempre con 30 s de audio
    (lo que más tarda es eso), así que pedirle varias a la vez cuesta casi lo mismo que pedirle una."""
    from faster_whisper.audio import pad_or_trim
    from faster_whisper.tokenizer import Tokenizer
    enc = model.encode(pad_or_trim(model.feature_extractor(clip)))
    tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=language or "es")
    prev = tok.encode(" " + before.strip()) if before.strip() else []
    prompt = model.get_prompt(tok, prev, without_timestamps=True, hotwords=hotwords())
    res = model.model.generate(enc, [prompt], beam_size=max(5, n), num_hypotheses=n,
                               max_length=getattr(model, "max_length", 448), suppress_blank=True,
                               suppress_tokens=[-1])[0]
    return [tok.decode(seq).strip() for seq in res.sequences_ids]


def alternatives(path: str, words: list, idx: int, model_name: str = "large-v3-turbo", language: str = "es",
                 progress: ProgressFn = None, cancelled: CancelFn = None) -> list[str]:
    from . import transcription
    w0, w1 = float(words[idx][0]), float(words[idx][1])
    a, b = window(words, idx)
    report(progress, 0.05, "Escuchando otra vez…")
    clip = _decode(path, a, b)
    check_cancel(cancelled)
    model = transcription._load(model_name)
    before = " ".join(core(w[2]) for w in words[max(0, idx - 14):idx] if float(w[1]) < a + 0.05)
    inside = [i for i, w in enumerate(words) if a <= (float(w[0]) + float(w[1])) / 2 <= b]
    report(progress, 0.3, "Escuchando otra vez…")
    t0 = time.monotonic()
    found: list[str] = []
    try:                                     # las 5 mejores interpretaciones de una sola escucha
        hyps = _nbest(model, clip, language, before)
        found = [spot([words[i][2] for i in inside], inside.index(idx), h) for h in hyps] if idx in inside else []
    except Exception:  # noqa: BLE001 - (si esta versión de Whisper no lo permite, se escucha de la forma normal)
        hyps = []
    TIMES.append(round(time.monotonic() - t0, 2))
    out = rank(words[idx][2], found)
    if not out:                              # no oyó nada distinto: una escucha más, «más suelta»
        check_cancel(cancelled)
        report(progress, 0.65, "Escuchando otra vez…")
        t0 = time.monotonic()
        segs, _info = model.transcribe(clip, language=language or None, word_timestamps=True, vad_filter=False,
                                       condition_on_previous_text=False, temperature=0.7, best_of=3,
                                       initial_prompt=before or None, hotwords=hotwords())
        got = [[a + float(w.start), a + float(w.end), w.word.strip()] for s in segs for w in (s.words or [])
               if w.word.strip()]
        out = rank(words[idx][2], [heard_at(got, w0, w1)])
        TIMES.append(round(time.monotonic() - t0, 2))
    report(progress, 1.0, "Listo.")
    return out[:6]


TIMES: list[float] = []         # (cuánto tarda cada escucha: para las pruebas)
