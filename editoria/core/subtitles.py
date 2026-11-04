"""
Subtítulos a partir de la transcripción, ya ajustados a la timeline
(si cortaste un silencio, los subtítulos se mueven con la voz).

Un "bloque" (Cue) es lo que aparece en pantalla de una vez: 1 o 2 líneas de texto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import mapping
from .model import Project, SubtitleStyle

SENTENCE_END = (".", "?", "!", "…")

# El estilo de los Shorts (el que pidió el usuario con una imagen de referencia): letra blanca muy gruesa y redondeada
# con sombra suave, a lo mucho 3 palabras a la vez, centrada sobre el borde de abajo del video del medio
SHORTS = "Shorts · 3 palabras"
# Palabras que no deben quedarse sueltas al FINAL de un bloque («Rumor del | día» → «Rumor | del día»)
# · artículos y preposiciones: SIEMPRE con la palabra de después («el | jefe» nunca)
WEAK_HARD = {"de", "del", "la", "el", "los", "las", "lo", "un", "una", "unos", "unas", "a", "al", "en", "con", "por",
             "para", "su", "sus", "mi", "mis", "tu", "tus", "muy", "the", "a", "an", "of", "to", "in", "on", "my",
             "your"}
# · conjunciones y verbos cortos: mejor no, pero si no queda otra se leen bien al final («es que | el jefe final»)
WEAK_SOFT = {"y", "o", "u", "e", "que", "se", "no", "ni", "es", "and"}
WEAK_END = WEAK_HARD | WEAK_SOFT

# Estilos predefinidos (solo los campos que cambian respecto a SubtitleStyle)
PRESETS: dict[str, dict] = {
    # (tamaño 6,9: «Rumor del día» ocupa el 64 % del ancho, como en su imagen; caben ~20 letras por línea)
    SHORTS: dict(font="Segoe UI Black", size=6.9, bold=True, uppercase=False, strip_punct=True,
                 color="#FFFFFF", highlight="#FFD400", outline_color="#000000", outline=0.10, shadow=0.35,
                 box=False, position="bottom", margin=30.5, max_chars=18, max_lines=2, max_words=3,
                 animation="none"),
    # Como en tus Shorts: blanco con contorno, debajo del video, frases cortas
    "Mis Shorts": dict(font="Arial", size=3.6, bold=False, uppercase=False, strip_punct=False,
                       color="#FFFFFF", highlight="#FFD400", outline_color="#000000", outline=0.20,
                       box=False, position="bottom", margin=26.0, max_chars=24, max_lines=2,
                       animation="none"),
    "YouTube clásico": dict(font="Arial", size=5.0, bold=True, uppercase=False, strip_punct=False,
                            color="#FFFFFF", highlight="#FFD400", outline_color="#000000", outline=0.30,
                            box=False, position="bottom", margin=7.0, max_chars=42, max_lines=2,
                            animation="none"),
    "Caja oscura": dict(font="Segoe UI", size=4.6, bold=True, uppercase=False, strip_punct=False,
                        color="#FFFFFF", highlight="#4FC3FF", outline_color="#000000", outline=0.0,
                        box=True, box_color="#000000", box_opacity=0.65, position="bottom", margin=6.0,
                        max_chars=42, max_lines=2, animation="fade"),
    "Shorts dinámico": dict(font="Arial Black", size=7.5, bold=True, uppercase=True, strip_punct=True,
                            color="#FFFFFF", highlight="#FFD400", outline_color="#000000", outline=0.55,
                            box=False, position="middle", margin=0.0, max_chars=16, max_lines=2,
                            animation="karaoke"),
    "Minimalista": dict(font="Segoe UI", size=4.2, bold=False, uppercase=False, strip_punct=False,
                        color="#FFFFFF", highlight="#FFD400", outline_color="#000000", outline=0.18,
                        box=False, position="bottom", margin=5.0, max_chars=48, max_lines=1,
                        animation="fade"),
}


@dataclass
class CueWord:
    start: float
    end: float
    text: str
    index: int          # posición en la transcripción (para resaltados)


@dataclass
class Cue:
    start: float
    end: float
    lines: list[list[CueWord]] = field(default_factory=list)

    @property
    def words(self) -> list[CueWord]:
        return [w for line in self.lines for w in line]

    def text(self, sep: str = "\n") -> str:
        return sep.join(" ".join(w.text for w in line) for line in self.lines)


def timeline_words(p: Project, media_id: str) -> list[tuple[float, float, str, int]]:
    """Palabras que suenan en la timeline: [(t_ini, t_fin, texto, índice)], ordenadas."""
    words = p.transcripts.get(media_id, {}).get("words", [])
    index = mapping.SourceIndex(p, media_id)
    out = []
    for i, w in enumerate(words):
        mid = (w[0] + w[1]) / 2
        t = index.time(mid)
        if t is None:
            continue  # palabra cortada
        out.append((max(0.0, t - (mid - w[0])), t + (w[1] - mid), w[2], i))
    out.sort()
    return out


def _balance(words: list[CueWord], max_lines: int) -> list[list[CueWord]]:
    """Reparte las palabras en líneas de longitud parecida."""
    if max_lines <= 1 or len(words) < 2:
        return [words]
    total = len(" ".join(w.text for w in words))
    best, best_k = None, 1
    for k in range(1, len(words)):
        a = len(" ".join(w.text for w in words[:k]))
        diff = abs(a - (total - a - 1))
        if best is None or diff < best:
            best, best_k = diff, k
    return [words[:best_k], words[best_k:]]


def _clean(text: str, style: SubtitleStyle | None) -> str:
    if style is not None and style.strip_punct:
        text = re.sub(r"[.,;:…]+$", "", text)
    if style is not None and style.uppercase:
        text = text.upper()
    return text


def _bare(text: str) -> str:
    return re.sub(r"[^\wáéíóúüñ]", "", text.lower())


def _split_best(seg: list[tuple], max_words: int, limit: int) -> list[list[tuple]]:
    """Reparte una frase (ya sin pausas ni puntos dentro) en bloques de a lo mucho max_words palabras, probando
    TODAS las formas y quedándose con la que mejor se lee: ningún bloque acaba en «de / la / que…», casi nunca
    una palabra sola, mejor 2–3 palabras y nada más largo que lo que cabe."""
    n = len(seg)
    best = [0.0] + [float("inf")] * n
    cut = [0] * (n + 1)
    for e in range(1, n + 1):
        for k in range(1, max_words + 1):
            b = e - k
            if b < 0:
                break
            blk = seg[b:e]
            c = best[b]
            last = _bare(blk[-1][2])
            if e < n and last in WEAK_HARD:
                c += 6.0                          # «Rumor del | día»: no
            elif e < n and last in WEAK_SOFT:
                c += 3.0
            if k == 1 and n > 1:
                c += 2.5                          # una palabra sola, solo si no queda otra
            c += 0.4 * (max_words - k)            # mejor bloques llenos (menos cambios de pantalla)
            if len(" ".join(x[2] for x in blk)) > limit:
                c += 20.0
            if c < best[e]:
                best[e], cut[e] = c, b
    out, e = [], n
    while e > 0:
        out.append(seg[cut[e]:e])
        e = cut[e]
    return out[::-1]


def build_cues(p: Project, media_id: str, max_chars: int = 42, max_lines: int = 2,
               max_dur: float = 5.0, max_gap: float = 0.6, hold: float = 0.25,
               style: SubtitleStyle | None = None, max_words: int = 0) -> list[Cue]:
    words = timeline_words(p, media_id)
    limit = max_chars * max_lines
    groups: list[list[tuple]] = []
    cur: list[tuple] = []
    for w in words:
        if cur:
            length = len(" ".join(x[2] for x in cur)) + 1 + len(w[2])
            too_long = (length > limit or w[1] - cur[0][0] > max_dur) if not max_words else w[1] - cur[0][0] > 12.0
            if w[0] - cur[-1][1] > max_gap or too_long:
                groups.append(cur)
                cur = []
        cur.append(w)
        if w[2].rstrip().endswith(SENTENCE_END) or (max_words and w[2].rstrip().endswith((",", ";", ":"))):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    if max_words:                               # cada frase, en bloques de a lo mucho N palabras (los mejores)
        groups = [blk for g in groups for blk in _split_best(g, max_words, limit)]

    cues: list[Cue] = []
    prev_text = ""
    for g in groups:
        cw = [CueWord(a, b, text, idx) for a, b, text, idx in g]
        # Mayúscula al empezar frase (p. ej. si se cortó la muletilla de delante)
        if not prev_text or prev_text.rstrip().endswith(SENTENCE_END):
            cw[0].text = cw[0].text[:1].upper() + cw[0].text[1:]
        prev_text = g[-1][2]
        for w in cw:
            w.text = _clean(w.text, style)
        cw = [w for w in cw if w.text]
        if cw:
            one = max_words and len(" ".join(w.text for w in cw)) <= max_chars   # cabe en una línea: una línea
            cues.append(Cue(cw[0].start, cw[-1].end + hold, _balance(cw, 1 if one else max_lines)))
    # Que ningún bloque se solape con el siguiente
    for a, b in zip(cues, cues[1:]):
        a.end = min(a.end, b.start - 0.01)
        if b.start - a.end < 0.3:  # huecos minúsculos: mejor sin parpadeo
            a.end = b.start - 0.01
        a.end = max(a.end, a.start + 0.3)
    return cues


def styled_cues(p: Project) -> list[Cue]:
    """Bloques según el estilo de subtítulos del proyecto."""
    st = p.subtitles
    if not st.media_id or st.media_id not in p.transcripts:
        return []
    return build_cues(p, st.media_id, max_chars=st.max_chars, max_lines=st.max_lines,
                      max_dur=3.0 if st.animation == "karaoke" else 5.0, style=st,
                      max_words=int(getattr(st, "max_words", 0) or 0))


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text()}\n"
              for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)
