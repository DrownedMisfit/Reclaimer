"""
🔁 Escucha literal: que no se pierda ninguna toma repetida.

Whisper aprendió con textos «limpios», así que cuando repites una frase («el día de ayer estaba jugando… el día de ayer
estaba trabajando») muchas veces escribe solo una: la toma que sobra NO sale en el texto y no se puede quitar. Aquí un
segundo oído lo comprueba:

1. El modelo wav2vec2 en español del alineador (align.py) escucha TODO el audio letra a letra, cada 20 ms, sin
   «arreglar» nada: si lo dijiste dos veces, lo escribe dos veces (con faltas: «estava», pero da igual).
2. Se alinea lo que oyó con lo que escribió Whisper por cómo suena cada palabra (b/v, s/z/c, ll/y… valen lo mismo;
   las cifras, en palabras). Donde el oído literal tiene palabras DE MÁS, Whisper se saltó algo (si hay dos tomas
   iguales, se marca la que no tiene nada de Whisper a esa hora).
3. Ese trozo se vuelve a transcribir con Whisper, corto y en «modo literal» (sin el contexto anterior y con un ejemplo
   de frases repetidas). Si Whisper sigue sin escribirlo y se parece a algo dicho al lado (una toma repetida), se
   quedan las palabras del oído literal; si no se parece (suelen ser nombres que oye raro), se deja como estaba.
Probado con una narración real de 12 min: Whisper se había comido 14 trozos, casi todos tomas repetidas.

  available() -> (bool, motivo)
  literal_words(audio, progress, cancelled) -> [[inicio, fin, texto, confianza], …]
  find_missed(words, literal) -> [[inicio, fin, texto_oído], …]
  recover(audio, transcript, model_key, language, progress, cancelled) -> transcripción con lo recuperado
      (en transcript["recovered"]: [[inicio, fin, texto, "whisper" | "oído"], …])

Todo en el procesador y sin internet. Tarda más o menos lo que la transcripción.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np

from . import align
from .base import CancelFn, ProgressFn, check_cancel, report

SR = 16000
WINDOW, STEP = 20.0, 19.0      # el oído literal escucha tramos de 20 s que se solapan 1 s
MIN_LETTERS = 7                # lo que falta tiene que ser algo de verdad (no una letra suelta)
MIN_DUR = 0.45
MIN_CONF = 0.55                # el oído literal tiene que estar razonablemente seguro
CONTEXT = 2.5                  # se vuelve a transcribir con un poco de antes y después
MAX_CLIP = 28.0

# Un ejemplo de cómo escribir: con las repeticiones y las muletillas (Whisper imita el estilo del ejemplo)
VERBATIM_PROMPT = ("Eh... el día de ayer, el día de ayer estaba... perdón, el día de ayer estaba trabajando, ¿no? "
                   "O sea, este, lo que, lo que quiero decir es que...")


def available() -> tuple[bool, str]:
    return align.available()


# ------------------------------------------------------------------ cómo suena una palabra
_SUBS = [(r"qu(?=[ei])", "k"), (r"gu(?=[ei])", "g"), (r"c(?=[ei])", "s"), (r"g(?=[ei])", "j"), (r"ll", "y"),
         (r"ch", "C"), (r"c", "k"), (r"z", "s"), (r"v", "b"), (r"w", "u"), (r"x", "ks"), (r"h", ""), (r"q", "k")]


_UNITS = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis "
          "diecisiete dieciocho diecinueve veinte veintiuno veintidos veintitres veinticuatro veinticinco veintiseis "
          "veintisiete veintiocho veintinueve").split()
_TENS = "_ _ _ treinta cuarenta cincuenta sesenta setenta ochenta noventa".split()
_HUNDREDS = "_ ciento doscientos trescientos cuatrocientos quinientos seiscientos setecientos ochocientos " \
            "novecientos".split()


def spell(n: int) -> str:
    """Un número dicho en voz alta («2024» → «dos mil veinticuatro»): Whisper escribe cifras y el oído literal
    oye palabras."""
    if n < 30:
        return _UNITS[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " y " + _UNITS[n % 10])
    if n < 1000:
        if n == 100:
            return "cien"
        return _HUNDREDS[n // 100] + ("" if n % 100 == 0 else " " + spell(n % 100))
    if n < 1_000_000:
        k, r = divmod(n, 1000)
        return ("mil" if k == 1 else spell(k) + " mil") + ("" if r == 0 else " " + spell(r))
    return " ".join(_UNITS[int(d)] for d in str(n))


def _spoken(text: str) -> str:
    return re.sub(r"\d+", lambda m: " " + spell(int(m.group())) + " ", str(text))


def sound(word: str) -> str:
    """Cómo suena (para comparar Whisper con el oído literal): sin acentos ni signos y con las letras que se
    pronuncian igual unificadas. «Estava» y «estaba» suenan igual."""
    w = unicodedata.normalize("NFD", str(word).lower())
    w = "".join(ch for ch in w if unicodedata.category(ch) != "Mn")
    w = re.sub(r"[^a-zñ]", "", w)
    for pat, rep in _SUBS:
        w = re.sub(pat, rep, w)
    return re.sub(r"(.)\1+", r"\1", w)          # «rr» = «r», «ll» ya es «y»


# ------------------------------------------------------------------ oído literal
def _greedy(em: np.ndarray, inv: dict[int, str], offset: float, lo: float, hi: float) -> list[list]:
    """Lo que oye el modelo sin texto de referencia: la letra más probable cada 20 ms (CTC). Solo se devuelven las
    palabras cuyo centro cae en [lo, hi) (así los tramos solapados no repiten palabras)."""
    best = em.argmax(axis=1)
    prob = np.exp(em.max(axis=1))
    out, letters, f0, f1, confs, prev = [], [], -1, -1, [], -1
    sep = next((k for k, v in inv.items() if v == "|"), 4)

    def flush():
        if letters:
            a, b = offset + f0 * align.FRAME, offset + (f1 + 1) * align.FRAME
            if lo <= (a + b) / 2 < hi:
                out.append([round(a, 3), round(b, 3), "".join(letters), round(float(np.mean(confs)), 3)])

    for t, k in enumerate(best):
        k = int(k)
        if k == prev:
            if k not in (align.BLANK, sep) and letters:
                f1 = t
            continue
        prev = k
        if k == align.BLANK:
            continue
        if k == sep:
            flush()
            letters, confs = [], []
            continue
        ch = inv.get(k, "")
        if len(ch) != 1:                         # <s>, </s>, <unk>
            continue
        if not letters:
            f0 = t
        letters.append(ch)
        confs.append(float(prob[t]))
        f1 = t
    flush()
    return out


def literal_words(audio: np.ndarray, progress: ProgressFn = None, cancelled: CancelFn = None) -> list[list]:
    """Todo lo que se oye en el audio, palabra a palabra, tal cual (con faltas de ortografía)."""
    _m, vocab = align._load()
    inv = {v: k for k, v in vocab.items()}
    dur = len(audio) / SR
    starts = list(np.arange(0.0, max(dur - 1.0, 0.0) + 1e-6, STEP)) or [0.0]
    out: list[list] = []
    for n, a in enumerate(starts):
        check_cancel(cancelled)
        m, s = divmod(int(a), 60)
        report(progress, n / len(starts), f"🔁 Escuchando palabra por palabra… {m:02d}:{s:02d} de "
                                          f"{int(dur) // 60:02d}:{int(dur) % 60:02d}")
        b = min(dur, a + WINDOW)
        seg = audio[int(a * SR):int(b * SR)]
        if len(seg) < SR // 5:
            continue
        lo = 0.0 if n == 0 else a + (WINDOW - STEP) / 2
        hi = dur + 1 if n == len(starts) - 1 else a + STEP + (WINDOW - STEP) / 2
        out += _greedy(align._emissions(seg), inv, a, lo, hi)
    out.sort(key=lambda w: w[0])
    report(progress, 1.0, f"🔁 Oído literal: {len(out)} palabras.")
    return out


# ------------------------------------------------------------------ comparar
def _chunks(words: list, literal: list, max_len: float = 60.0) -> list[tuple[float, float]]:
    """Tramos de hasta ~1 min partidos en pausas donde no hay ninguna palabra (de ninguno de los dos)."""
    spans = sorted([(float(w[0]), float(w[1])) for w in words] + [(float(w[0]), float(w[1])) for w in literal])
    if not spans:
        return []
    out, start, reach = [], spans[0][0], spans[0][1]
    for a, b in spans[1:]:
        if a - reach >= 0.25 and a - start >= max_len / 2:
            out.append((start, (reach + a) / 2))
            start = (reach + a) / 2
        reach = max(reach, b)
        if reach - start >= max_len * 2:          # sin pausas en 2 min: se parte igual
            out.append((start, reach))
            start = reach
    out.append((start, reach + 0.01))
    return out


def _support(W: list, a: float, b: float) -> int:
    """Cuántas palabras de Whisper suenan entre a y b."""
    return sum(1 for w in W if a - 0.3 <= (float(w[0]) + float(w[1])) / 2 <= b + 0.3)


def find_missed(words: list, literal: list) -> list[list]:
    """Trozos que el oído literal escuchó y Whisper no escribió: [[inicio, fin, texto_oído], …]. Se alinean las dos
    listas por cómo suena cada palabra (las faltas del oído literal, los nombres que oye raro o las palabras que junta
    no cuentan: solo cuenta lo que tiene palabras DE MÁS). Si lo que sobra está repetido al lado (dos tomas iguales),
    se marca la toma donde Whisper no tiene nada escrito."""
    out = []
    for c0, c1 in _chunks(words, literal):
        W = [w for w in words if c0 <= (float(w[0]) + float(w[1])) / 2 < c1]
        L = [w for w in literal if c0 <= (float(w[0]) + float(w[1])) / 2 < c1]
        # las cifras de Whisper, dichas en palabras (cada palabra cuenta aparte para comparar)
        ws = [s for w in W for s in (sound(x) for x in _spoken(w[2]).split()) if s]
        ls = [sound(w[2]) for w in L]
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, ws, ls, autojunk=False).get_opcodes():
            if tag not in ("insert", "replace"):
                continue
            extra = sum(len(x) for x in ls[j1:j2]) - sum(len(x) for x in ws[i1:i2])
            if tag == "replace" and (j2 - j1) - (i2 - i1) < 2:
                continue                               # misma cantidad de palabras: una falta, no algo nuevo
            if extra < MIN_LETTERS:
                continue
            k1, k2 = j1, j2
            n = j2 - j1                                # ¿la misma secuencia justo antes o después? (la otra toma)
            for t in (j1 - n, j2):
                if 0 <= t and t + n <= len(ls) and ls[t:t + n] == ls[j1:j2]:
                    here = _support(W, float(L[j1][0]), float(L[j2 - 1][1]))
                    there = _support(W, float(L[t][0]), float(L[t + n - 1][1]))
                    if there < here:
                        k1, k2 = t, t + n
            seg = L[k1:k2]
            a, b = float(seg[0][0]), float(seg[-1][1])
            if b - a < MIN_DUR or float(np.mean([w[3] for w in seg])) < MIN_CONF:
                continue
            out.append([round(a, 3), round(b, 3), " ".join(w[2] for w in seg)])
    return out


def _repeats_nearby(heard: str, words: list, a: float, b: float, span: float = 12.0) -> bool:
    """¿Lo oído se parece a algo que Whisper escribió cerca? (una toma repetida). Si no, es mejor no meter palabras
    del oído literal: suelen ser nombres que oye raro («godward» = God of War)."""
    h = sound(heard.replace(" ", ""))
    near = "".join(sound(x) for w in words if a - span <= w[0] <= b + span for x in _spoken(w[2]).split())
    if len(h) < 4 or not near:
        return False
    m = SequenceMatcher(None, h, near, autojunk=False)
    return sum(blk.size for blk in m.get_matching_blocks()) >= 0.75 * len(h)


# ------------------------------------------------------------------ recuperar
def _merge(regions: list, gap: float = 1.0) -> list[list]:
    out: list[list] = []
    for a, b, t in sorted(regions):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2] += " " + t
        else:
            out.append([a, b, t])
    return out


def _clip_bounds(a: float, b: float, literal: list, dur: float) -> tuple[float, float]:
    """El trozo a transcribir otra vez: con un poco de contexto y empezando/terminando en una pausa."""
    a0, b0 = max(0.0, a - CONTEXT), min(dur, b + CONTEXT)
    if b0 - a0 > MAX_CLIP:
        a0, b0 = max(0.0, (a + b) / 2 - MAX_CLIP / 2), min(dur, (a + b) / 2 + MAX_CLIP / 2)
    for w in literal:                                  # que no parta una palabra por la mitad
        if w[0] < a0 < w[1]:
            a0 = max(0.0, w[0] - 0.05)
        if w[0] < b0 < w[1]:
            b0 = min(dur, w[1] + 0.05)
    return a0, b0


def _whisper_clip(model, clip: np.ndarray, language: str) -> list[list]:
    segments, _info = model.transcribe(clip, language=language or None, word_timestamps=True, beam_size=5,
                                       condition_on_previous_text=False, initial_prompt=VERBATIM_PROMPT,
                                       vad_filter=False, temperature=0.0)
    out = []
    for seg in segments:
        for w in seg.words or []:
            if w.word.strip():
                out.append([float(w.start), float(w.end), w.word.strip(), float(w.probability)])
    return out


def _letters(ws: list) -> int:
    return sum(len(sound(x)) for w in ws for x in _spoken(w[2]).split())


def _rebuild_segments(words: list, old_words: list, old_segments: list) -> list[list]:
    """Los párrafos de antes, con las palabras nuevas metidas donde caen por tiempo."""
    if not words:
        return []
    bounds = sorted(float(old_words[a][0]) for _s, _e, a, b in old_segments if 0 <= a < b <= len(old_words))
    if not bounds:
        return [[words[0][0], words[-1][1], 0, len(words)]]
    out, first, k = [], 0, 1
    for i, w in enumerate(words):
        mid = (float(w[0]) + float(w[1])) / 2
        while k < len(bounds) and mid >= bounds[k]:
            if i > first:
                out.append([words[first][0], words[i - 1][1], first, i])
                first = i
            k += 1
    out.append([words[first][0], words[-1][1], first, len(words)])
    return out


def recover(audio: np.ndarray, transcript: dict, model_key: str = "equilibrado", language: str = "es",
            progress: ProgressFn = None, cancelled: CancelFn = None, literal: list | None = None) -> dict:
    """La transcripción con lo que Whisper se había saltado ya escrito. literal = lo que ya oyó el oído literal
    (si se tiene; si no, se escucha ahora)."""
    from . import transcription
    words = [list(w) for w in transcript.get("words", [])]
    dur = len(audio) / SR

    def sub(lo, hi):
        return (lambda f, t: report(progress, lo + (hi - lo) * max(0.0, f), t)) if progress else None

    if literal is None:
        literal = literal_words(audio, sub(0.0, 0.7), cancelled)
    missed = _merge(find_missed(words, literal))
    if not missed:
        report(progress, 1.0, "🔁 Whisper no se saltó nada.")
        return dict(transcript, words=words, literal=True, recovered=[])
    model = transcription._load(transcription.MODELS[model_key][0])
    recovered, new_words = [], list(words)
    for n, (a, b, heard) in enumerate(missed):
        check_cancel(cancelled)
        report(progress, 0.7 + 0.3 * n / len(missed), f"🔁 Recuperando lo que Whisper se saltó… {n + 1}/{len(missed)}")
        c0, c1 = _clip_bounds(a, b, literal, dur)
        old = [w for w in new_words if c0 <= (w[0] + w[1]) / 2 < c1]
        fresh = [[round(c0 + w[0], 3), round(c0 + w[1], 3), w[2], round(w[3], 3)]
                 for w in _whisper_clip(model, audio[int(c0 * SR):int(c1 * SR)], language)]
        fresh = [w for w in fresh if c0 <= (w[0] + w[1]) / 2 < c1]
        need = _letters(old) + 0.6 * len(sound(heard.replace(" ", "")))
        if fresh and _letters(fresh) >= need:
            how, inside = "whisper", fresh                   # Whisper, en corto, ya lo escribe entero
        else:
            # se queda lo del oído literal, pero SOLO en los huecos donde Whisper no escribió nada (si no, se
            # mezclarían las dos versiones: «entrevista entrevista que que…») y si parece una toma repetida
            heard_w = [[w[0], w[1], w[2], min(0.5, w[3])] for w in literal if a <= (w[0] + w[1]) / 2 <= b
                       and not any(o[0] < w[1] and w[0] < o[1] for o in old)]
            if _letters(heard_w) < MIN_LETTERS or not _repeats_nearby(" ".join(w[2] for w in heard_w), words, a, b):
                continue                                     # se deja como estaba
            how, heard = "oído", " ".join(w[2] for w in heard_w)
            inside = sorted(old + heard_w, key=lambda w: w[0])
        keep = [w for w in new_words if not c0 <= (w[0] + w[1]) / 2 < c1]
        new_words = sorted(keep + inside, key=lambda w: w[0])
        recovered.append([round(a, 3), round(b, 3), heard, how])
    for k in range(1, len(new_words)):                        # nunca encimadas
        if new_words[k][0] < new_words[k - 1][1]:
            mid = round((new_words[k][0] + new_words[k - 1][1]) / 2, 3)
            new_words[k - 1][1] = new_words[k][0] = mid
    segments = _rebuild_segments(new_words, words, transcript.get("segments") or [])
    report(progress, 1.0, f"🔁 Recuperados {len(recovered)} trozos que Whisper se había saltado.")
    return dict(transcript, words=new_words, segments=segments, literal=True, recovered=recovered,
                aligned=False)
