"""
Módulo de IA: LIMPIEZA DE VOZ.

Reúne los detectores (silencios, ruidos, muletillas, repeticiones, tomas,
saturación) y devuelve una lista de SUGERENCIAS. No corta nada: el usuario
decide qué aplicar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import repetition_detection as rep
from . import silence_detection as sil
from .base import CancelFn, ProgressFn, check_cancel, report

# tipo -> (nombre, ¿se puede cortar?)
KINDS = {
    "silence": ("Silencio largo", True),
    "noise": ("Respiración / ruido", True),
    "filler": ("Muletilla", True),
    "repeat": ("Palabra repetida", True),
    "retake": ("Toma repetida", True),
    "doubt": ("Palabra dudosa", False),
    "clipping": ("Saturación", False),
    "manual": ("Tachado a mano", True),
}


# ⚡ Qué quita la limpieza automática si no tocas nada (las casillas de «Limpieza automática»)
AUTO_DEFAULTS = {"filler": True, "filler_soft": False, "repeat": True, "retake": True, "silence": True,
                 "noise": False}


def will_cut(s, on: set[str]) -> bool:
    """¿Se quitará esta sugerencia al «⚡ Limpiar» / «✂ Cortar lo tachado»? on = casillas marcadas. Lo que tachas o
    destachas tú en el texto (data["tachar"]) manda sobre las casillas."""
    from ..core.model import SUG_PENDING
    if s.status != SUG_PENDING or not s.cuttable:
        return False
    data = s.data or {}
    if data.get("tachar") is not None:
        return bool(data["tachar"])
    if s.kind == "manual":
        return True
    if data.get("auto") is False:          # p. ej. «muy muy» o «suena parecido»: a lo mejor es a propósito
        return False
    if s.kind == "filler":
        return ("filler_soft" if s.label.startswith("Posible") else "filler") in on
    return s.kind in on


def cut_range(s) -> tuple[float, float]:
    """El tramo que se quitaría (en las tomas repetidas, la toma que NO se queda)."""
    if s.kind == "retake" and (s.data or {}).get("best") == 1 and s.alt_start is not None:
        return s.alt_start, s.alt_end
    return s.start, s.end


@dataclass
class CleanupOptions:
    silences: bool = True
    min_silence: float = 0.8   # silencios más largos que esto…
    keep_pause: float = 0.25   # …se reducen a esta pausa (nunca se quitan del todo)
    noises: bool = True
    fillers: bool = True
    repeated_words: bool = True
    retakes: bool = True
    similar: bool = True       # «suena parecido»: frases seguidas que dicen lo mismo con otras palabras
    doubtful: bool = True
    clipping: bool = True
    my_fillers: tuple = ()     # tus muletillas («¿por qué?», «la verdad»…)

    def kinds(self) -> set[str]:
        return {k for k, on in (("silence", self.silences), ("noise", self.noises),
                                ("filler", self.fillers), ("repeat", self.repeated_words),
                                ("retake", self.retakes), ("doubt", self.doubtful),
                                ("clipping", self.clipping)) if on}


def refine_transcript(samples: np.ndarray, sr: int, transcript: dict) -> dict:
    """Ajusta los tiempos de las palabras al volumen real del audio (más precisión en cortes y subtítulos)."""
    levels = sil.analyze_levels(samples, sr)
    words = sil.refine_word_times(transcript.get("words", []), levels)
    segments = [[words[a][0], words[b - 1][1], a, b] for _s, _e, a, b in transcript.get("segments", [])
                if 0 <= a < b <= len(words)]
    return dict(transcript, words=words, segments=segments, refined=True)


def _sentence_encoder():
    """El modelo de frases (MiniLM, ya en el PC) para «suena parecido». Si no está, no se busca (sin descargar)."""
    from . import embeddings
    if not embeddings.is_available()[0] or not embeddings.is_downloaded("sentence"):
        return lambda texts: np.zeros((len(texts), 1), np.float32)
    return embeddings.get("sentence").encode


def _contains_word(a: float, b: float, words: list, min_prob: float = 0.5) -> bool:
    """¿Hay alguna palabra clara COMPLETA dentro de [a, b]? (protege palabras dichas muy bajito).
    Solo palabras completas: Whisper a veces marca el inicio de una palabra unas décimas
    antes de que suene, y eso no debe anular un silencio real."""
    return any(a <= w[0] and w[1] <= b and (len(w) < 4 or w[3] >= min_prob) for w in words)


def analyze(samples: np.ndarray, sr: int, words: list | None, opts: CleanupOptions,
            progress: ProgressFn = None, cancelled: CancelFn = None) -> list[dict]:
    """Devuelve sugerencias: dicts con kind, start, end, label, detail (tiempos del archivo original)."""
    words = words or []
    duration = len(samples) / sr
    out: list[dict] = []
    report(progress, 0.1, "Midiendo el volumen…")
    levels = sil.analyze_levels(samples, sr)
    check_cancel(cancelled)

    if opts.silences:
        report(progress, 0.3, "Buscando silencios…")
        half = opts.keep_pause / 2
        for s, e in sil.find_silences(levels, opts.min_silence):
            # Al principio y al final del archivo se deja menos pausa
            a = s if s <= 0.05 else s + half
            b = e if e >= duration - 0.05 else e - half
            if b - a < 0.15 or _contains_word(a, b, words):
                continue
            out.append({"kind": "silence", "start": a, "end": b,
                        "label": f"Silencio de {e - s:.1f} s",
                        "detail": f"Se quitarán {b - a:.2f} s y quedará una pausa natural de "
                                  f"{min(opts.keep_pause, e - s):.2f} s."})
    check_cancel(cancelled)

    if opts.noises and words:
        report(progress, 0.5, "Buscando respiraciones y ruidos…")
        for a, b in sil.find_noises(levels, words):
            out.append({"kind": "noise", "start": a, "end": b,
                        "label": f"Respiración o ruido ({b - a:.1f} s)",
                        "detail": "Sonido entre palabras que no es voz. Escúchalo antes de quitarlo."})

    if words:
        report(progress, 0.7, "Buscando muletillas y repeticiones…")
        if opts.fillers:
            out += [dict(d, kind="filler") for d in rep.find_fillers(words, opts.my_fillers)]
        if opts.repeated_words:
            out += [dict(d, kind="repeat") for d in rep.find_repeated_words(words)]
        if opts.retakes:
            takes = rep.find_retakes(words)
            out += [dict(d, kind="retake") for d in takes]
            if opts.similar:
                report(progress, 0.8, "Buscando frases que suenan parecido…")
                out += [dict(d, kind="retake") for d in rep.find_similar(words, _sentence_encoder(), takes)]
        if opts.doubtful:
            out += [dict(d, kind="doubt", detail="Whisper no estaba seguro de esta palabra: "
                                                 "puede estar cortada o mal pronunciada.")
                    for d in rep.find_doubtful(words)]
    check_cancel(cancelled)

    if opts.clipping:
        report(progress, 0.9, "Buscando saturación…")
        for a, b in sil.find_clipping(samples, sr):
            out.append({"kind": "clipping", "start": max(0.0, a), "end": b,
                        "label": "Audio saturado (clipping)",
                        "detail": "El volumen llegó al máximo y se distorsionó. "
                                  "Conviene regrabar o bajar la ganancia del micrófono."})

    for d in out:
        d["start"] = max(0.0, d["start"])
        d["end"] = min(duration, d["end"])
        d.setdefault("detail", "")
    out = [d for d in out if d["end"] - d["start"] > 0.01]
    out.sort(key=lambda d: d["start"])
    report(progress, 1.0, f"Análisis listo: {len(out)} sugerencias.")
    return out
