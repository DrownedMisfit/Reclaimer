"""
🔖 Marcas de OBS: los capítulos que pones con una tecla mientras grabas (OBS 30.2+, grabación «MP4 híbrido»,
con el complemento «Additional Chapter Hotkeys» para ponerles nombre: «NG», «Fallo», «Bien»...).

Sin Qt. Dos cosas:
  · read_chapters(path): lee los capítulos del archivo con ffprobe → [{"t": segundos, "title": str}];
  · suggest_cut(t, words): qué tramo quitar por una marca en t: desde el inicio de la frase que se estaba diciendo
    justo antes de la marca hasta la marca (o hasta la siguiente palabra, si la marca cae en una pausa).
"""
from __future__ import annotations

import json
import subprocess

from . import media as media_tools

PAUSA_FRASE = 0.4        # pausa (s) entre palabras que separa una frase de la anterior
SIN_TRANSCRIPCION = 3.0  # sin transcripción: cuántos segundos antes de la marca se quitan


def read_chapters(path: str) -> list[dict]:
    """Capítulos del archivo (en segundos del archivo) con su título. Sin capítulos o sin poder leerlo → []."""
    try:
        r = media_tools.run_quiet([media_tools.ffprobe(), "-v", "error", "-show_chapters",
                                   "-print_format", "json", path], timeout=60)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    try:
        chapters = json.loads(r.stdout.decode("utf-8", errors="replace")).get("chapters") or []
    except (ValueError, AttributeError):
        return []
    return parse_chapters(chapters)


def parse_chapters(chapters: list) -> list[dict]:
    """Capítulos tal como los da ffprobe ({start_time, tags:{title}}) → [{"t", "title"}], ordenados."""
    out = []
    for ch in chapters:
        try:
            t = float(ch.get("start_time", 0.0))
        except (TypeError, ValueError):
            continue
        title = str(((ch.get("tags") or {}).get("title") or "")).strip()
        if t <= 0.0005 and not title:          # el capítulo inicial sin nombre que pone OBS siempre
            continue
        out.append({"t": round(max(0.0, t), 3), "title": title or f"Marca {len(out) + 1}"})
    out.sort(key=lambda c: c["t"])
    return out


def suggest_cut(t: float, words: list | None) -> tuple[float, float]:
    """Tramo (a, b) del archivo a quitar por una marca en t (segundos del archivo).
    words: transcripción [[inicio, fin, texto, ...], ...] en segundos del archivo."""
    ws = sorted((w for w in (words or []) if len(w) >= 2), key=lambda w: float(w[0]))
    if not ws:
        return (round(max(0.0, t - SIN_TRANSCRIPCION), 3), round(t, 3))
    starts = [float(w[0]) for w in ws]
    ends = [float(w[1]) for w in ws]

    # índice de la palabra que se decía justo antes de la marca (la que la contiene, si la marca cae dentro)
    inside = next((k for k in range(len(ws)) if starts[k] <= t < ends[k]), None)
    if inside is not None:
        e = inside
        # la marca cae a mitad de una palabra: esa palabra también se va (no se deja media palabra suelta); hasta
        # la siguiente palabra si está pegada, o hasta el final de esta
        nxt = starts[inside + 1] if inside + 1 < len(ws) else ends[inside]
        b = nxt if nxt - ends[inside] < PAUSA_FRASE else ends[inside]
    else:
        before = [k for k in range(len(ws)) if ends[k] <= t]
        if not before:                                    # la marca está antes de cualquier palabra
            nxt = next((starts[k] for k in range(len(ws)) if starts[k] > t), t)
            return (round(max(0.0, t - SIN_TRANSCRIPCION), 3), round(max(t, min(nxt, t)), 3))
        e = before[-1]
        after = [starts[k] for k in range(len(ws)) if starts[k] >= t]
        b = after[0] if after else t                      # la marca cae en una pausa: hasta la siguiente palabra

    # la frase: retrocede mientras no haya una pausa de PAUSA_FRASE o más
    i = e
    while i > 0 and starts[i] - ends[i - 1] < PAUSA_FRASE:
        i -= 1
    a = starts[i]
    if b - a <= 0.05:                                     # tramo vacío: al menos la frase de la marca
        a = min(a, max(0.0, t - SIN_TRANSCRIPCION))
        b = max(b, t)
    return (round(max(0.0, a), 3), round(max(b, a), 3))
