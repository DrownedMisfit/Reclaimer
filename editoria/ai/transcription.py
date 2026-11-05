"""
Módulo de IA: TRANSCRIPCIÓN.

Convierte la narración en texto con el tiempo exacto de cada palabra, usando
Whisper (faster-whisper) en tu PC: gratis y sin internet (salvo la primera
descarga del modelo).
"""
from __future__ import annotations

import os

import numpy as np

from ..core.paths import app_data_dir
from .base import CancelFn, ProgressFn, check_cancel, report

SAMPLE_RATE = 16000

# clave -> (modelo de Whisper, descripción)
MODELS = {
    "equilibrado": ("large-v3-turbo", "Equilibrado (recomendado)"),
    "rapido": ("small", "Rápido, menos preciso"),
    "maximo": ("large-v3", "Máxima precisión, lento"),
}
DOWNLOAD_SIZE = {"equilibrado": "1,6 GB", "rapido": "0,5 GB", "maximo": "3 GB"}

LANGUAGES = {"es": "Español", "en": "Inglés", "": "Detectar automáticamente"}

# Ayuda a que Whisper NO borre las muletillas (así luego se pueden detectar).
FILLER_PROMPT = "Eh... mmm, bueno, este, o sea, pues eso."

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_loaded: dict[str, object] = {}


def is_available() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "Falta el componente de transcripción. Ejecuta INSTALAR.bat."
    return True, ""


def models_dir():
    # EDITORIA_MODELOS: las pruebas usan datos temporales pero los modelos ya descargados (no se bajan otra vez)
    import os
    from pathlib import Path
    d = Path(os.environ["EDITORIA_MODELOS"]) if os.environ.get("EDITORIA_MODELOS") else app_data_dir() / "modelos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_downloaded(model_key: str) -> bool:
    name = MODELS[model_key][0]
    return any(models_dir().glob(f"models--*--faster-whisper-{name}/snapshots/*/model.bin"))


def _load(name: str):
    if name not in _loaded:
        from faster_whisper import WhisperModel
        threads = max(1, (os.cpu_count() or 4) // 2)
        _loaded.clear()  # solo un modelo en memoria a la vez
        from ..core.hw import whisper_device
        device, ctype = whisper_device()        # NVIDIA lista → la tarjeta; si no, procesador (int8)
        _loaded[name] = WhisperModel(name, device=device, compute_type=ctype,
                                     cpu_threads=threads, download_root=str(models_dir()))
    return _loaded[name]


def transcribe(samples: np.ndarray, model_key: str = "equilibrado", language: str = "es",
               progress: ProgressFn = None, cancelled: CancelFn = None, fillers: bool = True) -> dict:
    """
    samples: audio mono a 16 kHz (float32).
    fillers: True (Limpieza: buscar muletillas, titubeos…) = sin lotes y con el ejemplo FILLER_PROMPT, para que
      Whisper NO borre las muletillas; False (subtítulos) = por lotes (más rápido) y sin ejemplo.
      ⚠ NUNCA el ejemplo en el modo por lotes: se le pone delante a CADA trozo de 30 s y Whisper se pierde (se queda
      escribiendo «... ... ...» y se salta frases enteras). Pasó el 3/11/2026 en un Short: de 256 palabras dichas
      salieron 101 y 21 s sin subtítulos. Sin el ejemplo, el mismo modo por lotes las saca todas.
    Al final, red de seguridad (fill_holes): un tramo con voz y sin palabras se vuelve a escuchar.
    Devuelve {"language", "model", "words": [[inicio, fin, texto, confianza], ...],
              "segments": [[inicio, fin, primera_palabra, última_palabra+1], ...]}
    Los tiempos son del archivo original (no de la timeline).
    """
    name = MODELS[model_key][0]
    report(progress, 0.0, "Cargando el modelo de voz…" if is_downloaded(model_key)
           else "Descargando el modelo de voz (solo la primera vez, puede tardar varios minutos)…")
    model = _load(name)
    check_cancel(cancelled)
    total = max(len(samples) / SAMPLE_RATE, 0.001)
    report(progress, 0.0, "Transcribiendo…")
    from .word_fix import hotwords
    # hotwords: las palabras que le pediste tener en cuenta (clic derecho en una palabra del panel Texto)
    if fillers:
        segments, info = model.transcribe(samples, language=language or None, word_timestamps=True, beam_size=5,
                                          vad_filter=True, initial_prompt=FILLER_PROMPT, hotwords=hotwords())
    else:
        from faster_whisper import BatchedInferencePipeline
        segments, info = BatchedInferencePipeline(model=model).transcribe(
            samples, language=language or None, word_timestamps=True, beam_size=5, batch_size=8)

    words: list[list] = []
    segs: list[list] = []
    for seg in segments:
        check_cancel(cancelled)
        first = len(words)
        for w in seg.words or []:
            text = w.word.strip()
            if text and text.strip(".…·- "):          # (fuera las «palabras» que son solo puntos: «...»)
                words.append([round(float(w.start), 3), round(float(w.end), 3), text,
                              round(float(w.probability), 3)])
        if len(words) > first:
            segs.append([words[first][0], words[-1][1], first, len(words)])
        m, s = divmod(int(seg.end), 60)
        report(progress, min(0.95, seg.end / total), f"Transcribiendo… {m:02d}:{s:02d} de "
                                                     f"{int(total) // 60:02d}:{int(total) % 60:02d}")
    tr = {"language": info.language, "model": name, "words": words, "segments": segs}
    tr = fill_holes(samples, tr, model, language, cancelled)
    report(progress, 1.0, f"Transcripción lista: {len(tr['words'])} palabras.")
    return tr


# ------------------------------------------------------------------ red de seguridad
HOLE_MIN = 2.5          # un tramo sin palabras de al menos 2,5 s…
HOLE_VOICE = 0.4        # …en el que al menos el 40 % suena como voz, se vuelve a escuchar


def voice_frames(samples: np.ndarray, hop: float = 0.1) -> np.ndarray:
    """Por cada 0,1 s: ¿suena como voz? (nivel cerca del de tu voz en este audio, no un silencio ni un ruido bajo)."""
    n = int(hop * SAMPLE_RATE)
    k = len(samples) // n
    if k == 0:
        return np.zeros(0, bool)
    fr = samples[:k * n].reshape(k, n)
    db = 20 * np.log10(np.sqrt((fr.astype(np.float64) ** 2).mean(axis=1)) + 1e-9)
    loud = np.percentile(db, 80)               # el nivel típico de cuando hablas
    return db > max(loud - 14.0, -50.0)


def holes(samples: np.ndarray, words: list) -> list[tuple[float, float]]:
    """Tramos sin palabras (también antes de la primera y tras la última) donde se oye voz."""
    v = voice_frames(samples)
    total = len(samples) / SAMPLE_RATE
    edges = [0.0] + [x for w in words for x in (float(w[0]), float(w[1]))] + [total]
    out = []
    for a, b in zip(edges[0::2], edges[1::2]):
        if b - a < HOLE_MIN:
            continue
        seg = v[int(a / 0.1):int(b / 0.1)]
        if len(seg) and seg.mean() >= HOLE_VOICE:
            out.append((a, b))
    return out


def fill_holes(samples: np.ndarray, tr: dict, model, language: str = "es", cancelled: CancelFn = None) -> dict:
    """Vuelve a escuchar (de uno en uno, sin ejemplo: lo más fiable) los tramos con voz que se quedaron sin texto y
    mete lo que oiga en su sitio. Lo recuperado queda en tr["filled"] = [[inicio, fin], …]."""
    words = [list(w) for w in tr.get("words", [])]
    found = holes(samples, words)
    if not found:
        return tr
    new_all, filled = [], []
    for a, b in found:
        check_cancel(cancelled)
        a0, b0 = max(0.0, a - 0.3), min(len(samples) / SAMPLE_RATE, b + 0.3)
        clip = samples[int(a0 * SAMPLE_RATE):int(b0 * SAMPLE_RATE)]
        segs, _info = model.transcribe(clip, language=language or None, word_timestamps=True, beam_size=5,
                                       vad_filter=True, condition_on_previous_text=False)
        got = [[round(a0 + float(w.start), 3), round(a0 + float(w.end), 3), w.word.strip(),
                round(float(w.probability), 3)] for s in segs for w in (s.words or [])
               if w.word.strip().strip(".…·- ")]
        got = [w for w in got if a - 0.05 <= (w[0] + w[1]) / 2 <= b + 0.05]
        if got:
            new_all += got
            filled.append([round(a, 3), round(b, 3)])
    if not new_all:
        return tr
    from .verbatim import _rebuild_segments
    merged = sorted(words + new_all, key=lambda w: w[0])
    out = dict(tr, words=merged, segments=_rebuild_segments(merged, words, tr.get("segments") or []))
    out["filled"] = list(tr.get("filled") or []) + filled
    return out
