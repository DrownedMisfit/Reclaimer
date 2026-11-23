"""
Créditos de los clips: de dónde sale cada clip usado en el proyecto.

Un clip con créditos tiene «<video>.creditos.json» al lado ({"title", "channel", "url", …}).
Una narración de 🗣 Voz IA cuya voz pide atribución (CC BY) lleva el suyo con {"tipo": "voz", "title", "url"}: sale
en su propio apartado «🗣 Voz:».
Las imágenes ({"tipo": "imagen"}; p. ej. las libres de «Buscar material conforme a frases») salen en «🖼 Imágenes:»
con título, autor, LICENCIA («license_text»: con CC BY / BY-SA es obligatorio decirla) y enlace.

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
    voces: list[str] = []
    imagenes: list[str] = []
    vistos: set[str] = set()
    for c in credits or []:
        if c.get("tipo") == "voz":                       # 🗣 voz sintética con licencia que pide atribución
            linea = "• " + (c.get("title") or "Voz sintética") + (f": {c['url']}" if c.get("url") else "")
            if linea not in vistos:
                vistos.add(linea)
                voces.append(linea)
            continue
        if c.get("tipo") == "imagen":                    # 🖼 título — autor (licencia): enlace
            autor = c.get("channel") or ""
            lic = c.get("license_text") or ""
            linea = (f"• «{c.get('title') or 'Sin título'}»" + (f" — {autor}" if autor and autor != "desconocido"
                                                                  else "")
                     + (f" ({lic})" if lic else "") + (f": {c['url']}" if c.get("url") else ""))
            if linea not in vistos:
                vistos.add(linea)
                imagenes.append(linea)
            continue
        titulo = c.get("title") or "Sin título"
        canal = c.get("channel") or ""
        video = c.get("url") or ""                       # (el enlace del VIDEO usado, como se suele acreditar)
        linea = f"• «{titulo}»" + (f" — {canal}" if canal else "") + (f": {video}" if video else "")
        if linea in vistos:
            continue
        vistos.add(linea)
        lineas.append(linea)
    partes = []
    if lineas:
        partes.append("🎬 Clips usados en este video:\n" + "\n".join(lineas))
    if imagenes:
        partes.append("🖼 Imágenes:\n" + "\n".join(imagenes))
    if voces:
        partes.append("🗣 Voz:\n" + "\n".join(voces))
    return "\n\n".join(partes)


def save_next_to(export_path: str, project) -> str | None:
    texto = text(collect(project))
    if not texto:
        return None
    ruta = os.path.splitext(export_path)[0] + ".creditos.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    return ruta
