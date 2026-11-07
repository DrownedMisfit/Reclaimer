"""
📝 Descripción completa para YouTube: párrafo inicial, capítulos, créditos de los clips, pie del usuario y hashtags.

Sin Qt. Las preferencias del usuario (párrafo por proyecto y pie) se leen en editoria/ui/description_dialog.py.

  hashtags(project, max_n=5) -> ["#Fortnite", "#Combate", …]   (menciones de juegos y temas de la narración)
  compose(parrafo, capitulos, creditos, pie, tags) -> texto final (las partes vacías no salen)
  default_text(project, parrafo, pie) -> texto para el archivo «<video>.descripcion.txt» al exportar
"""
from __future__ import annotations

import re

from . import chapters as CH
from . import credits as CR


def _tag(texto: str) -> str:
    palabras = re.findall(r"[^\W_]+", texto or "")
    tag = "".join(p.capitalize() for p in palabras)
    if not tag or tag[0].isdigit():
        return ""
    return "#" + tag


def hashtags(project, max_n: int = 5) -> list[str]:
    """Juegos y compañías de las menciones (primero los conocidos), luego los temas de la narración."""
    from ..ai.mentions import find_mentions
    out: list[str] = []
    vistos: set[str] = set()

    def add(texto: str) -> None:
        tag = _tag(texto)
        if tag and tag.lower() not in vistos and len(out) < max_n:
            vistos.add(tag.lower())
            out.append(tag)

    menciones = sorted(find_mentions(project), key=lambda m: -int(m.get("count", 0)))
    for m in [m for m in menciones if m.get("known")]:
        add(m["term"])
    for m in [m for m in menciones if not m.get("known")][:3]:
        add(m["term"])
    for mk in project.markers:
        if mk.kind == "topic" and mk.label:
            add(mk.label)
    return out


def compose(parrafo: str = "", capitulos: str = "", creditos: str = "", pie: str = "",
            tags: list[str] | tuple = ()) -> str:
    partes = [s.strip() for s in (parrafo, capitulos, creditos, pie) if s and s.strip()]
    if tags:
        partes.append(" ".join(tags))
    return "\n\n".join(partes)


def default_text(project, parrafo: str = "", pie: str = "") -> str:
    """Descripción con todo lo que hay en el proyecto (capítulos automáticos, créditos y hashtags)."""
    cands = CH.candidates(project, "auto")
    caps, _avisos = CH.build([(t, titulo) for t, titulo, _mid in cands], project.duration())
    if len(caps.splitlines()) < 3:           # YouTube no muestra capítulos con menos de 3
        caps = ""
    return compose(parrafo, caps, CR.text(CR.collect(project)), pie, hashtags(project))
