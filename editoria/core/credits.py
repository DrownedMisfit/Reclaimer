"""
Créditos de los clips: de dónde sale cada clip usado en el proyecto.

Un clip con créditos tiene «<video>.creditos.json» al lado ({"title", "channel", "url", …}).

  collect(project)            -> [créditos] de los medios del proyecto que lo tengan (sin duplicados)
  text(credits)               -> texto en español para la descripción de YouTube ("" si no hay)
  save_next_to(export, proj)  -> escribe «<video>.creditos.txt» junto al video exportado (None si no hay)
"""
from __future__ import annotations

import json
import os


def collect(project) -> list[dict]:
    out: list[dict] = []
    vistos: set[str] = set()
    for m in (getattr(project, "media", None) or {}).values():
        ruta = os.path.splitext(getattr(m, "path", "") or "")[0] + ".creditos.json"
        if not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(datos, dict):
            continue
        clave = datos.get("url") or datos.get("title") or ruta
        if clave in vistos:
            continue
        vistos.add(clave)
        out.append(datos)
    return out


def text(credits: list[dict]) -> str:
    lineas: list[str] = []
    vistos: set[str] = set()
    for c in credits or []:
        titulo = c.get("title") or "Sin título"
        canal = c.get("channel") or ""
        video = c.get("url") or ""                       # (el enlace del VIDEO usado, como se suele acreditar)
        linea = f"• «{titulo}»" + (f" — {canal}" if canal else "") + (f": {video}" if video else "")
        if linea in vistos:
            continue
        vistos.add(linea)
        lineas.append(linea)
    if not lineas:
        return ""
    return "🎬 Clips usados en este video:\n" + "\n".join(lineas)


def save_next_to(export_path: str, project) -> str | None:
    texto = text(collect(project))
    if not texto:
        return None
    ruta = os.path.splitext(export_path)[0] + ".creditos.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    return ruta
