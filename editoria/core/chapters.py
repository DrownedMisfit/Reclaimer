"""
📑 Capítulos para la descripción de YouTube, desde tus marcadores (o desde los temas de la narración).

Reglas de YouTube para que salgan los capítulos en la barra del video:
  · el primero empieza en 0:00 (si tu primer marcador está en los primeros 10 s, pasa a 0:00; si no, se
    añade «Intro» en 0:00);
  · al menos 3 capítulos;
  · cada uno dura 10 s o más (los que quedan más cortos se juntan con el anterior).

  candidates(project, source) -> [(tiempo, título, marker_id)]
  build(chapters, duration) -> (texto para pegar, avisos)
  lista(chapters, duration) -> ([(tiempo, título)], avisos)   los capítulos ya con las reglas (lo que usa build)
  ffmetadata(project, duration) -> texto | None   📍 los capítulos para meterlos DENTRO del MP4 (FFmpeg)
"""
from __future__ import annotations

from .model import Project

MIN_LEN = 10.0
AUTO_PREFIXES = ("Corte de escena",)       # marcadores que pone Reclaimer solo (no son capítulos)
COLOR_OBS = "#e5484d"                      # (las marcas de OBS son fallos al grabar, no capítulos)


def _es_capitulo(m) -> bool:
    """Un marcador que vale como capítulo: con nombre propio (no «Marcador 3»), sin resolver, ni marca de OBS."""
    import re
    nombre = (m.label or "").strip()
    return (bool(nombre) and not nombre.startswith(AUTO_PREFIXES) and not re.fullmatch(r"Marcador \d+", nombre)
            and not getattr(m, "resuelto", False) and (m.color or "").lower() != COLOR_OBS)


def fmt(t: float, long: bool) -> str:
    t = int(max(0.0, t))
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if long else f"{m}:{s:02d}"


def candidates(p: Project, source: str = "auto") -> list[tuple[float, str, str]]:
    """source: «marcadores» · «temas» (los temas de la narración) · «auto» (marcadores si los hay; si no, temas)."""
    marks = [(m.time, (m.label or "").strip(), m.id) for m in p.markers if m.kind != "topic" and _es_capitulo(m)]
    topics = [(m.time, (m.label or "").strip(), m.id) for m in p.markers if m.kind == "topic"]
    if source == "marcadores":
        out = marks
    elif source == "temas":
        out = topics
    else:
        out = marks if len(marks) >= 2 else (topics or marks)
    return sorted(out, key=lambda x: x[0])


def build(chapters: list[tuple[float, str]], duration: float) -> tuple[str, list[str]]:
    merged, warn = lista(chapters, duration)
    long = duration >= 3600 or any(t >= 3600 for t, _ in merged)
    text = "\n".join(f"{fmt(t, long)} {title}" for t, title in merged)
    return text, warn


def lista(chapters: list[tuple[float, str]], duration: float) -> tuple[list[tuple[float, str]], list[str]]:
    """Los capítulos con las reglas de YouTube (el primero en 0:00, 10 s o más cada uno) y los avisos."""
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
    return merged, warn


def _esc(t: str) -> str:
    """Un título para ffmetadata: «=», «;», «#», «\\» y los saltos de línea van escapados."""
    out = []
    t = str(t).rstrip("\\")   # (una «\» al final + salto de línea = continuación en FFmpeg: se come el capítulo siguiente)
    for ch in t.replace("\r\n", "\n"):
        if ch in "=;#\\":
            out.append("\\" + ch)
        elif ch in "\r\n":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def validos(p: Project, duration: float, source: str = "auto") -> int:
    """Cuántos capítulos quedan con las reglas de YouTube (la casilla de Exportar viene marcada si son 3 o más)."""
    cand = candidates(p, source)
    if not cand or duration <= 0:
        return 0
    return len(lista([(t, title) for t, title, _id in cand], duration)[0])


def ffmetadata(p: Project, duration: float, source: str = "auto") -> str | None:
    """📍 Los capítulos (los mismos de la descripción: candidates + reglas de YouTube) en el formato de FFmpeg para
    meterlos DENTRO del MP4 (los reproductores y YouTube los enseñan en la barra). None si no hay ninguno con sitio."""
    if duration <= 0:
        return None
    cand = candidates(p, source)
    if not cand:
        return None
    merged, _warn = lista([(t, title) for t, title, _id in cand], duration)
    merged = [(t, title) for t, title in merged if t < duration - 0.5]
    if not merged:
        return None
    lineas = [";FFMETADATA1"]
    for k, (t, title) in enumerate(merged):
        fin = merged[k + 1][0] if k + 1 < len(merged) else duration
        lineas += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(round(t * 1000))}", f"END={int(round(fin * 1000))}",
                   f"title={_esc(title)}"]
    return "\n".join(lineas) + "\n"
