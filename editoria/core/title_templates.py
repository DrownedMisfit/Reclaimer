"""
🅣 Plantillas de títulos (como los «Títulos» de Resolve o Premiere, en sencillo): un estilo completo de texto
(fuente, tamaño, color, contorno, sombra, caja, posición) y su fundido de entrada/salida, listo para poner en el cabezal con un
clic. Las de fábrica y las ★ tuyas (Inspector → texto → «★ Guardar como plantilla»).

  all_templates() -> [(clave, nombre)]           las de fábrica y luego las ★ tuyas
  get(clave, vertical) -> {"content", "style", "dur"} o None
  save_user(nombre, text, dur) · delete_user(nombre)
Las tuyas se guardan en los ajustes de Reclaimer (valen para todos los proyectos).
"""
from __future__ import annotations

import json

KEY = "titulos/plantillas"

FACTORY: list[tuple[str, str, dict]] = [
    ("grande", "Título grande", {
        "content": "TÍTULO", "dur": 3.0, "fade": 0.25,
        "style": {"font": "Impact", "size": 12.0, "color": "#FFFFFF", "case": "upper", "y": 0.45, "x": 0.5,
                  "box": False, "stroke_size": 9.0, "stroke_color": "#000000", "shadow": True, "shadow_blur": 25.0,
                  "shadow_opacity": 0.6, "blur_under": 0.0}}),
    ("rotulo", "Rótulo inferior (nombre / dato)", {
        "content": "Nombre · lo que hace", "dur": 4.0, "fade": 0.2,
        "style": {"font": "Arial", "size": 4.6, "color": "#FFFFFF", "align": "left", "x": 0.27, "y": 0.84,
                  "box": True, "box_color": "#E5413C", "box_opacity": 0.92, "box_width": 30.0, "box_height": 14.0,
                  "box_radius": 12.0, "stroke_size": 0.0, "blur_under": 0.0}}),
    ("capitulo", "Capítulo (centro, pausado)", {
        "content": "Capítulo 1", "dur": 3.0, "fade": 0.5,
        "style": {"font": "Georgia", "size": 8.0, "color": "#F5E6C8", "bold": False, "italic": True, "y": 0.5,
                  "box": False, "shadow": True, "shadow_blur": 30.0, "shadow_opacity": 0.8, "tracking": 4.0,
                  "blur_under": 0.6}}),
    ("meme", "Meme (arriba, Impact)", {
        "content": "CUANDO EL JEFE…", "dur": 3.0, "fade": 0.15,
        "style": {"font": "Impact", "size": 8.5, "color": "#FFFFFF", "case": "upper", "y": 0.1, "box": False,
                  "stroke_size": 11.0, "stroke_color": "#000000", "blur_under": 0.0}}),
    ("destacado", "Palabra destacada (amarilla)", {
        "content": "¡OJO!", "dur": 2.0, "fade": 0.1,
        "style": {"font": "Arial Black", "size": 9.0, "color": "#FFD400", "case": "upper", "y": 0.5, "box": False,
                  "stroke_size": 8.0, "stroke_color": "#101114", "rotation": -4.0, "blur_under": 0.3}}),
    ("cita", "Cita", {
        "content": "«Una frase que quieres resaltar»", "dur": 5.0, "fade": 0.4,
        "style": {"font": "Georgia", "size": 5.2, "color": "#FFFFFF", "bold": False, "italic": True, "y": 0.5,
                  "box": True, "box_color": "#000000", "box_opacity": 0.55, "box_width": 40.0, "box_height": 30.0,
                  "box_radius": 8.0, "blur_under": 0.7}}),
    ("fuente", "Fuente / créditos (esquina)", {
        "content": "Fuente: …", "dur": 4.0, "fade": 0.2,
        "style": {"font": "Arial", "size": 2.6, "color": "#E8E8E8", "bold": False, "align": "right", "x": 0.86,
                  "y": 0.93, "box": True, "box_color": "#000000", "box_opacity": 0.45, "box_radius": 20.0,
                  "blur_under": 0.0}}),
    ("subrayado", "Pregunta al público", {
        "content": "¿Y tú qué opinas?", "dur": 4.0, "fade": 0.3,
        "style": {"font": "Arial", "size": 6.0, "color": "#101114", "y": 0.78, "box": True, "box_color": "#FFFFFF",
                  "box_opacity": 0.95, "box_radius": 50.0, "box_width": 35.0, "box_height": 18.0, "stroke_size": 0.0,
                  "blur_under": 0.0}}),
]
for _k, _n, _d in FACTORY:                       # (el fundido va dentro del estilo del texto: clip.text["fade"])
    _d["style"]["fade"] = _d.pop("fade", 0.15)
_FACTORY = {k: (n, d) for k, n, d in FACTORY}


def _user() -> dict:
    from PySide6.QtCore import QSettings
    try:
        d = json.loads(str(QSettings("EditorIA", "EditorIA").value(KEY, "{}") or "{}"))
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def _save(d: dict):
    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").setValue(KEY, json.dumps(d, ensure_ascii=False))


def all_templates() -> list[tuple[str, str]]:
    out = [(k, n) for k, n, _d in FACTORY]
    out += [("★" + name, "★ " + name) for name in sorted(_user())]
    return out


def get(key: str, vertical: bool = False) -> dict | None:
    if key.startswith("★"):
        t = _user().get(key[1:])
        if not isinstance(t, dict):
            return None
        t = {"content": t.get("content") or "Texto", "dur": float(t.get("dur") or 4.0),
             "style": dict(t.get("style") or {})}
    else:
        got = _FACTORY.get(key)
        if got is None:
            return None
        t = json.loads(json.dumps(got[1]))
    if vertical and not key.startswith("★"):      # (Short / edit vertical: más pequeño y dentro de la zona segura)
        st = t["style"]
        st["size"] = round(float(st.get("size", 6.0)) * 0.62, 2)
        if "x" in st:
            st["x"] = round(0.5 + (float(st["x"]) - 0.5) * 0.8, 3)
        st["y"] = round(min(0.8, max(0.18, float(st.get("y", 0.5)))), 3)
    return t


def save_user(name: str, text: dict, dur: float = 4.0) -> str:
    from .title_render import STYLE_KEYS
    name = name.strip().lstrip("★").strip()
    if not name:
        raise ValueError("Ponle un nombre a la plantilla.")
    d = _user()
    d[name] = {"content": str(text.get("content") or "Texto"), "dur": round(float(dur), 2),
               "style": {k: text[k] for k in STYLE_KEYS if k in text}}
    _save(d)
    return "★" + name


def delete_user(name: str) -> bool:
    d = _user()
    if d.pop(name.lstrip("★").strip(), None) is None:
        return False
    _save(d)
    return True
