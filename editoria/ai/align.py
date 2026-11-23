"""
🎯 Alineación de palabras (como WhisperX): Whisper dice QUÉ palabras se dijeron, pero dónde empieza y acaba cada una lo
sabe mal (hasta 0,4 s de error medido con la voz del usuario). Aquí un modelo wav2vec2 en español
(jonatasgrosman/wav2vec2-large-xlsr-53-spanish, Apache-2.0) escucha el audio letra a letra cada 20 ms y, con el texto ya
conocido, se busca el camino más probable (alineación forzada CTC): cada palabra queda en su sitio con ~20 ms de
precisión. Sirve para cortar silencios sin comerse palabras, para los subtítulos y para dibujar las palabras en la onda.

  available() -> (bool, motivo)
  align_words(path, words, progress=None, cancelled=None) -> palabras afinadas [[inicio, fin, texto, prob], …]

El modelo vive en motor_ia/alineador_es (descargado una vez, con permiso del usuario).
⚡ Con el motor de IA y una tarjeta gráfica, el modelo escucha en la tarjeta (servidor de voz del motor, el mismo que
transcribe): medido en una RX 9060 XT, 90 s de voz de ~30 s a ~2 s. Sin tarjeta, en el procesador, como siempre.
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
    return bool(transcript and transcript.get("words") and not transcript.get("aligned")
                and transcript.get("hasta") is None)          # (a medias: se afina cuando esté entera)


def refined(transcript: dict, new_words: list) -> dict:
    """La transcripción con las palabras afinadas (y marcada, para no repetirlo)."""
    return dict(transcript, words=new_words, aligned=True)


def _load():
    global _model
    if _model is None:
        import torch
        from transformers import Wav2Vec2ForCTC
        torch.set_num_threads(max(2, (os.cpu_count() or 4) // 2))
        _model = Wav2Vec2ForCTC.from_pretrained(model_dir()).eval()
    return _model, vocab()


_vocab: dict = {}


def vocab() -> dict:
    """Las letras que conoce el modelo (sin cargar el modelo: cuando escucha la tarjeta no hace falta)."""
    global _vocab
    if not _vocab:
        import json
        with open(os.path.join(model_dir(), "vocab.json"), encoding="utf-8") as f:
            _vocab = json.load(f)
    return _vocab


# ------------------------------------------------------------------ ⚡ en la tarjeta (servidor de voz del motor)
_sin_tarjeta = False                       # (el motor dijo que no hay tarjeta, o falló 2 veces: el resto, procesador)
_fallos_tarjeta = 0


def _tarjeta_ok() -> bool:
    if _sin_tarjeta or os.environ.get("EDITORIA_TARJETA_MOTOR") == "0":
        return False
    try:
        from PySide6.QtCore import QSettings
        if str(QSettings("EditorIA", "EditorIA").value("voz/tarjeta_motor", "true")).lower() != "true":
            return False
    except Exception:  # noqa: BLE001
        pass
    from ..core import motor_ia
    ta = motor_ia.DATOS_MOTOR / ".venv" / "Lib" / "site-packages" / "torchaudio" / "__init__.py"
    return motor_ia.PYTHON.exists() and ta.exists()


def _emisiones_tarjeta(audio: np.ndarray, tramos: list, progress=None, cancelled=None) -> list | None:
    """log-probabilidades de cada tramo, calculadas en la tarjeta. None = no se pudo (se hace en el procesador)."""
    global _sin_tarjeta, _fallos_tarjeta
    if not tramos or not _tarjeta_ok():
        return None
    import tempfile
    import wave
    from ..core import media as media_tools
    from ..core import motor_ia
    from ..core.paths import temp_dir
    fd, wav = tempfile.mkstemp(prefix="alinear_", suffix=".wav", dir=str(temp_dir()))
    os.close(fd)
    npz = wav[:-4] + ".npz"
    try:
        with wave.open(wav, "wb") as w:              # (16 kHz mono, por trozos de 60 s)
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            paso = 60 * SR
            for i in range(0, len(audio), paso):
                w.writeframes((np.clip(audio[i:i + paso], -1, 1) * 32767).astype("<i2").tobytes())
        ruta = motor_ia.servidor_voz().pedir(
            {"cmd": "emisiones", "ffmpeg": media_tools.ffmpeg(), "entrada": wav, "salida": npz,
             "tramos": [[round(float(a), 3), round(float(b), 3)] for a, b in tramos]},
            progress, cancelled)
        with np.load(ruta) as z:
            out = [z[f"e{i}"] if f"e{i}" in z.files else None for i in range(len(tramos))]
        _fallos_tarjeta = 0
        return out
    except Exception as exc:  # noqa: BLE001 - la tarjeta no pudo: en el procesador
        if cancelled is not None and cancelled():
            return [None] * len(tramos)
        _fallos_tarjeta += 1
        if isinstance(exc, motor_ia.SinTarjeta) or _fallos_tarjeta >= 2:
            _sin_tarjeta = True
        return None
    finally:
        for x in (wav, npz):
            try:
                os.remove(x)
            except OSError:
                pass


def emissions_many(audio: np.ndarray, tramos: list, progress=None, cancelled=None, label: str = "") -> list:
    """log-probabilidades [T, letras] de cada tramo [inicio, fin] (s) del audio (None si es demasiado corto). En la
    tarjeta si se puede (todos de una vez); si no, en el procesador, uno a uno."""
    got = _emisiones_tarjeta(audio, tramos, progress, cancelled)
    if got is not None:
        return got
    out = []
    for i, (a, b) in enumerate(tramos):
        if cancelled and cancelled():
            out += [None] * (len(tramos) - i)
            break
        if progress:
            progress(i / max(1, len(tramos)), label or f"🎯 Afinando palabras… {i + 1}/{len(tramos)}")
        seg = audio[int(float(a) * SR):int(float(b) * SR)]
        out.append(_emissions(seg) if len(seg) >= SR // 10 else None)
    return out


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
    vocab_ = vocab()
    audio = media_tools.decode_mono(path, SR).astype(np.float32)
    dur = len(audio) / SR
    # (nada más allá del final del audio: Whisper a veces se pasa un poco en la última palabra)
    out = [[min(float(w[0]), dur), min(float(w[1]), dur)] + list(w[2:]) for w in words]
    wins = _windows(words)
    tramos = [(max(0.0, float(words[i][0]) - PAD), min(dur, float(words[j - 1][1]) + PAD)) for i, j in wins]
    ems = emissions_many(audio, tramos, progress, cancelled)
    for wi, (i, j) in enumerate(wins):
        if cancelled and cancelled():
            break
        a, _b = tramos[wi]
        em = ems[wi]
        if em is None:
            continue
        toks, owner, pos = [], [], []
        for k in range(i, j):
            tk = _tokens(words[k][2] if len(words[k]) > 2 else "", vocab_)
            if not tk:
                continue
            if toks:
                toks.append(vocab_["|"])
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
