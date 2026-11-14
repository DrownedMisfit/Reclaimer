"""
Audio inteligente (no destructivo: se aplica al reproducir/exportar, nunca al archivo).

- Efectos de voz por pista: reducción de ruido, ecualización, compresor y de-esser.
- Ducking: la música baja sola mientras hablas y sube en las pausas.
- Normalización final a -14 LUFS (el volumen de referencia de YouTube).
"""
from __future__ import annotations

from . import mapping
from .model import KIND_AUDIO, TRACK_AUDIO, Project

VOICE_FX = {
    "denoise": ("Reducir ruido de fondo", "afftdn=nr=12:nf=-40:tn=1"),
    "eq": ("Ecualizar voz (más clara)", "highpass=f=80,equalizer=f=250:t=q:w=1.2:g=-2,"
                                        "equalizer=f=3500:t=q:w=1:g=2.5"),
    "deess": ("De-esser (suaviza las «s»)", "deesser=i=0.4:m=0.5:f=0.5"),
    "compress": ("Compresor (volumen más parejo)", "acompressor=threshold=-20dB:ratio=3:attack=5:"
                                                   "release=150:makeup=3"),
}
FX_ORDER = ["denoise", "eq", "deess", "compress"]

LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"

ATTACK = 0.25    # segundos que tarda la música en bajar antes de que hables
RELEASE = 0.6    # segundos que tarda en volver a subir


def fx_chain(fx: dict) -> str:
    """Cadena de filtros de FFmpeg para los efectos activados de una pista."""
    return ",".join(VOICE_FX[k][1] for k in FX_ORDER if fx.get(k))


def speech_intervals(p: Project, gap: float = 0.8) -> list[tuple[float, float]]:
    """Tramos de la timeline en los que hay narración (según la transcripción, o los clips de voz)."""
    from .subtitles import timeline_words
    spans: list[tuple[float, float]] = []
    voice_tracks = [t for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is None and not t.muted]
    for mid in {c.media_id for t in voice_tracks for c in p.clips_on(t.id)}:
        m = p.media.get(mid)
        if m is None or m.kind != KIND_AUDIO:
            continue
        if mid in p.transcripts:
            spans += [(a, b) for a, b, _w, _i in timeline_words(p, mid)]
        elif m.category == "Narración":
            spans += [(c.start, c.end) for c in mapping.clips_of_media(p, mid)]
    spans.sort()
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def duck_amount(intervals: list[tuple[float, float]], t: float) -> float:
    """0 = música normal, 1 = música totalmente bajada (rampas suaves)."""
    best = 0.0
    for a, b in intervals:
        if t < a - ATTACK:
            break
        if a - ATTACK <= t < a:
            best = max(best, (t - (a - ATTACK)) / ATTACK)
        elif a <= t <= b:
            return 1.0
        elif b < t <= b + RELEASE:
            best = max(best, 1 - (t - b) / RELEASE)
    return best


def duck_gain(intervals: list[tuple[float, float]], t: float, duck_db: float) -> float:
    """Multiplicador de volumen de la música en el momento t."""
    g = 10 ** (duck_db / 20)
    return 1 - (1 - g) * duck_amount(intervals, t)


def ffmpeg_duck_volume(intervals: list[tuple[float, float]], clip_start: float, clip_end: float,
                       duck_db: float) -> str | None:
    """Filtro volume animado para un clip de música (tiempo local del clip = t)."""
    g = 10 ** (duck_db / 20)
    terms = []
    for a, b in intervals:
        if b + RELEASE < clip_start or a - ATTACK > clip_end:
            continue
        a0, b0 = a - clip_start, b - clip_start
        terms.append(f"between(t,{a0 - ATTACK:.3f},{a0:.3f})*(t-({a0 - ATTACK:.3f}))/{ATTACK}"
                     f"+between(t,{a0:.3f},{b0:.3f})"
                     f"+between(t,{b0:.3f},{b0 + RELEASE:.3f})*(1-(t-{b0:.3f})/{RELEASE})")
    if not terms:
        return None
    # FFmpeg no acepta más de ~32 sumandos seguidos en una expresión («Missing ')' or too many args»: el sonido de la
    # exportación fallaba con una narración de 5 min): se agrupan de 8 en 8 entre paréntesis (misma curva; medido)
    groups = terms
    while len(groups) > 8:
        groups = ["(" + "+".join(groups[i:i + 8]) + ")" for i in range(0, len(groups), 8)]
    amount = f"min(1,{'+'.join(groups)})"
    return f"volume='1-{1 - g:.4f}*{amount}':eval=frame"
