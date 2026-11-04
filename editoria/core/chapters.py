"""
📑 Capítulos para la descripción de YouTube, desde tus marcadores (o desde los temas de la narración).

Reglas de YouTube para que salgan los capítulos en la barra del video:
  · el primero empieza en 0:00 (si tu primer marcador está en los primeros 10 s, pasa a 0:00; si no, se
    añade «Intro» en 0:00);
  · al menos 3 capítulos;
  · cada uno dura 10 s o más (los que quedan más cortos se juntan con el anterior).

  candidates(project, source) -> [(tiempo, título, marker_id)]
  build(chapters, duration) -> (texto para pegar, avisos)
"""
from __future__ import annotations

from .model import Project

MIN_LEN = 10.0
AUTO_PREFIXES = ("Corte de escena",)       # marcadores que pone Reclaimer solo (no son capítulos)


def fmt(t: float, long: bool) -> str:
    t = int(max(0.0, t))
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if long else f"{m}:{s:02d}"


def candidates(p: Project, source: str = "auto") -> list[tuple[float, str, str]]:
    """source: «marcadores» · «temas» (los temas de la narración) · «auto» (marcadores si los hay; si no, temas)."""
    marks = [(m.time, (m.label or "").strip(), m.id) for m in p.markers
             if m.kind != "topic" and not (m.label or "").startswith(AUTO_PREFIXES)]
    topics = [(m.time, (m.label or "").strip(), m.id) for m in p.markers if m.kind == "topic"]
    if source == "marcadores":
        out = marks
    elif source == "temas":
        out = topics
    else:
        out = marks if len(marks) >= 2 else (topics or marks)
    return sorted(out, key=lambda x: x[0])


def build(chapters: list[tuple[float, str]], duration: float) -> tuple[str, list[str]]:
    warn: list[str] = []
    ch = sorted(((max(0.0, float(t)), (title or "").strip() or "Capítulo") for t, title in chapters),
                key=lambda x: x[0])
    ch = [c for c in ch if duration <= 0 or c[0] < duration - 1.0]
    if ch and ch[0][0] < MIN_LEN:           # tu primer capítulo está casi al principio: pasa a empezar en 0:00
        if ch[0][0] > 0.5:
            warn.append(f"«{ch[0][1]}» pasa a empezar en 0:00 (YouTube necesita que el primero empiece ahí).")
        ch[0] = (0.0, ch[0][1])
    else:
        ch.insert(0, (0.0, "Intro"))
        if len(ch) > 1:
            warn.append("Se añadió «Intro» en 0:00 (YouTube necesita que el primer capítulo empiece ahí).")
    merged: list[tuple[float, str]] = []
    for t, title in ch:
        if merged and t - merged[-1][0] < MIN_LEN:
            warn.append(f"«{title}» empieza menos de {int(MIN_LEN)} s después de «{merged[-1][1]}»: se junta con él "
                        "(YouTube pide capítulos de 10 s o más).")
            continue
        merged.append((t, title))
    if merged and duration > 0 and duration - merged[-1][0] < MIN_LEN and len(merged) > 1:
        last = merged.pop()
        warn.append(f"«{last[1]}» dura menos de 10 s hasta el final: se quitó.")
    if len(merged) < 3:
        warn.append("YouTube necesita al menos 3 capítulos para mostrarlos: añade más marcadores con nombre "
                    "(M en la línea de tiempo) o usa los temas de la narración.")
    long = duration >= 3600 or any(t >= 3600 for t, _ in merged)
    text = "\n".join(f"{fmt(t, long)} {title}" for t, title in merged)
    return text, warn
