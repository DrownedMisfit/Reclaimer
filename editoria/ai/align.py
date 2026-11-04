"""
🎯 Alineación de palabras (como WhisperX): Whisper dice QUÉ palabras se dijeron, pero dónde empieza y acaba cada una lo
sabe mal (hasta 0,4 s de error medido con la voz del usuario). Aquí un modelo wav2vec2 en español
(jonatasgrosman/wav2vec2-large-xlsr-53-spanish, Apache-2.0) escucha el audio letra a letra cada 20 ms y, con el texto ya
conocido, se busca el camino más probable (alineación forzada CTC): cada palabra queda en su sitio con ~20 ms de
precisión. Sirve para cortar silencios sin comerse palabras, para los subtítulos y para dibujar las palabras en la onda.

  available() -> (bool, motivo)
  align_words(path, words, progress=None, cancelled=None) -> palabras afinadas [[inicio, fin, texto, prob], …]

El modelo vive en motor_ia/alineador_es (descargado una vez, con permiso del usuario). Todo en el procesador.
"""
from __future__ import annotations

import os
import unicodedata

import numpy as np

SR = 16000
FRAME = 320 / SR            # el modelo da una predicción cada 20 ms
WINDOW = 20.0               # se alinea por tramos de hasta 20 s (memoria y velocidad)
PAD = 0.6                   # margen alrededor de cada tramo (Whisper se equivoca hasta ~0,4 s)
BLANK = 0
# La alineación CTC es «picuda»: cada letra se marca en uno o dos fotogramas y el final de la palabra sale corto (medido
# con la voz del usuario: 54 s de voz quedaban fuera de las palabras). Así que cada palabra se ALARGA con el propio audio
# mientras siga sonando (hasta SNAP_DB por debajo de cómo hablas, en graves o en agudos: las «s» finales), sin pasar a
# la palabra de al lado y como mucho SNAP_TAIL / SNAP_HEAD.
SNAP_DB, SNAP_TAIL, SNAP_HEAD, HOP = 35.0, 0.45, 0.25, 0.005
_model = None


def model_dir() -> str:
    from ..core.paths import PROGRAM_DIR
    return os.path.join(str(PROGRAM_DIR), "motor_ia", "alineador_es")


def available() -> tuple[bool, str]:
    d = model_dir()
    if not os.path.exists(os.path.join(d, "pytorch_model.bin")):
        return False, "Falta el modelo de alineación (motor_ia/alineador_es)."
    import importlib.util
    if importlib.util.find_spec("torch") is None or importlib.util.find_spec("transformers") is None:
        return False, "Faltan PyTorch y transformers en el entorno de Reclaimer."
    return True, ""


def unload() -> None:
    """Libera el modelo (~1,3 GB de memoria) cuando ya no hace falta."""
    global _model
    _model = None
    import gc
    gc.collect()


def needs(transcript: dict | None) -> bool:
    """¿Esta transcripción tiene palabras sin afinar todavía?"""
    return bool(transcript and transcript.get("words") and not transcript.get("aligned"))


def refined(transcript: dict, new_words: list) -> dict:
    """La transcripción con las palabras afinadas (y marcada, para no repetirlo)."""
    return dict(transcript, words=new_words, aligned=True)


def _load():
    global _model, _vocab
    if _model is None:
        import json
        import torch
        from transformers import Wav2Vec2ForCTC
        torch.set_num_threads(max(2, (os.cpu_count() or 4) // 2))
        _model = Wav2Vec2ForCTC.from_pretrained(model_dir()).eval()
        with open(os.path.join(model_dir(), "vocab.json"), encoding="utf-8") as f:
            _vocab = json.load(f)
    return _model, _vocab


_vocab: dict = {}


def _tokens(text: str, vocab: dict) -> list[int]:
    """Las letras de una palabra que el modelo conoce (minúsculas; acentos raros → sin acento; lo demás fuera)."""
    out = []
    for ch in str(text).lower():
        if ch in vocab and ch not in ("|", "<pad>"):
            out.append(vocab[ch])
            continue
        base = unicodedata.normalize("NFD", ch)[0]
        if base in vocab and base.isalpha():
            out.append(vocab[base])
    return out


def _emissions(x: np.ndarray) -> np.ndarray:
    """log-probabilidades [T, letras] cada 20 ms."""
    import torch
    model, _v = _load()
    x = (x - x.mean()) / (x.std() + 1e-7)
    with torch.inference_mode():
        logits = model(torch.from_numpy(x.astype(np.float32))[None]).logits[0]
        return torch.log_softmax(logits, dim=-1).numpy()


def _force_align(em: np.ndarray, tokens: list[int]) -> list[tuple[int, int]] | None:
    """Alineación forzada CTC (Viterbi): para cada token de la secuencia, (primer, último) fotograma. Implementación
    sencilla: estados = blanco-token-blanco-token-…-blanco."""
    T, L = len(em), len(tokens)
    if L == 0 or T < L:
        return None
    S = 2 * L + 1
    lab = np.full(S, BLANK, np.int64)
    lab[1::2] = tokens
    NEG = -1e30
    dp = np.full(S, NEG)
    dp[0] = em[0, BLANK]
    dp[1] = em[0, lab[1]]
    back = np.zeros((T, S), np.int8)                  # 0 = mismo estado, 1 = desde s-1, 2 = desde s-2
    allow2 = np.zeros(S, bool)
    allow2[3::2] = lab[3::2] != lab[1:-2:2]           # saltar el blanco solo entre letras distintas
    for t in range(1, T):
        stay = dp
        prev1 = np.concatenate(([NEG], dp[:-1]))
        prev2 = np.where(allow2, np.concatenate(([NEG, NEG], dp[:-2])), NEG)
        best = np.maximum(np.maximum(stay, prev1), prev2)
        choice = np.where(best == stay, 0, np.where(best == prev1, 1, 2)).astype(np.int8)
        dp = best + em[t, lab]
        back[t] = choice
    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    if dp[s] <= NEG / 2:
        return None
    spans = [[-1, -1] for _ in range(L)]
    for t in range(T - 1, -1, -1):
        if s % 2 == 1:
            k = s // 2
            spans[k][0] = t
            if spans[k][1] < 0:
                spans[k][1] = t
        s -= int(back[t, s]) if t > 0 else 0
    return [tuple(x) for x in spans]


def _windows(words: list) -> list[tuple[int, int]]:
    """Grupos de palabras seguidas de hasta WINDOW s, partidos por las pausas más largas."""
    out, i, n = [], 0, len(words)
    while i < n:
        j = i + 1
        while j < n and float(words[j][1]) - float(words[i][0]) <= WINDOW:
            j += 1
        if j < n:                                     # partir por la pausa más larga del tramo
            gaps = [(float(words[k][0]) - float(words[k - 1][1]), k) for k in range(i + 1, j)]
            if gaps:
                g, k = max(gaps)
                if g > 0.15 or j - i > 8:
                    j = k
        out.append((i, j))
        i = j
    return out


def _env(x: np.ndarray) -> np.ndarray:
    n = int(HOP * SR)
    m = len(x) // n
    e = (x[: m * n].astype(np.float64).reshape(m, n) ** 2).mean(axis=1)
    return (10 * np.log10(e + 1e-12)).astype(np.float32)


def _snap(out: list, audio: np.ndarray) -> None:
    """Alarga el principio y el final de cada palabra mientras el audio siga sonando (ver SNAP_DB)."""
    full = _env(audio)
    hi = _env(np.diff(audio, prepend=audio[:1]))
    n = len(full)
    if n == 0 or not out:
        return
    voiced = np.zeros(n, bool)
    for w in out:
        voiced[int(w[0] / HOP):int(w[1] / HOP)] = True
    lvl = float(np.percentile(full[voiced], 90)) if voiced.any() else float(np.percentile(full, 95))
    lvl_hi = float(np.percentile(hi[voiced], 90)) if voiced.any() else float(np.percentile(hi, 95))
    sound = (full > lvl - SNAP_DB) | (hi > lvl_hi - SNAP_DB)
    for k, w in enumerate(out):
        nxt = out[k + 1][0] if k + 1 < len(out) else n * HOP
        prv = out[k - 1][1] if k > 0 else 0.0
        e = min(n, int(w[1] / HOP))
        lim = min(n, int(min(nxt - 0.01, w[1] + SNAP_TAIL) / HOP))
        while e < lim and sound[e]:
            e += 1
        b = min(n, int(w[0] / HOP))
        lim0 = max(0, int(max(prv + 0.01, w[0] - SNAP_HEAD) / HOP))
        while b > lim0 and sound[b - 1]:
            b -= 1
        w[0], w[1] = round(min(w[0], b * HOP), 3), round(max(w[1], e * HOP), 3)


def align_words(path: str, words: list, progress=None, cancelled=None) -> list:
    """Palabras con su inicio y fin afinados. Las que no se pueden alinear (números, símbolos) quedan entre sus
    vecinas, como estaban."""
    from ..core import media as media_tools
    _m, vocab = _load()
    audio = media_tools.decode_mono(path, SR).astype(np.float32)
    dur = len(audio) / SR
    # (nada más allá del final del audio: Whisper a veces se pasa un poco en la última palabra)
    out = [[min(float(w[0]), dur), min(float(w[1]), dur)] + list(w[2:]) for w in words]
    wins = _windows(words)
    for wi, (i, j) in enumerate(wins):
        if cancelled and cancelled():
            break
        if progress:
            progress(wi / max(1, len(wins)), f"🎯 Afinando palabras… {wi + 1}/{len(wins)}")
        a = max(0.0, float(words[i][0]) - PAD)
        b = min(dur, float(words[j - 1][1]) + PAD)
        seg = audio[int(a * SR):int(b * SR)]
        if len(seg) < SR // 10:
            continue
        em = _emissions(seg)
        toks, owner, pos = [], [], []
        for k in range(i, j):
            tk = _tokens(words[k][2] if len(words[k]) > 2 else "", vocab)
            if not tk:
                continue
            if toks:
                toks.append(vocab["|"])
                owner.append(-1)
            pos.append((k, len(toks), len(toks) + len(tk) - 1))
            toks += tk
            owner += [k] * len(tk)
        spans = _force_align(em, toks)
        if spans is None:
            continue
        for k, t0, t1 in pos:
            f0, f1 = spans[t0][0], spans[t1][1]
            if f0 < 0 or f1 < 0:
                continue
            out[k][0] = round(a + f0 * FRAME, 3)
            out[k][1] = round(a + (f1 + 1) * FRAME, 3)
    _snap(out, audio)
    for k in range(1, len(out)):                      # nunca encimadas
        if out[k][0] < out[k - 1][1]:
            mid = (out[k][0] + out[k - 1][1]) / 2
            out[k - 1][1] = out[k][0] = round(mid, 3)
    if progress:
        progress(1.0, "🎯 Palabras afinadas")
    return out
