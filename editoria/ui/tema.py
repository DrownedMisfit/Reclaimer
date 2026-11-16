"""
🎨 El tema de la interfaz. Desde el 14/11 hay grises (los oscuros no dejaban ver dónde empieza y termina cada cosa):
  · «grafito»  gris neutro y sobrio, con capas sutiles y bordes finos pero nítidos (como Premiere o Final Cut);
  · «pizarra»  el mismo con un toque frío, azulado (moderno);
  · «gris»     más claro, con más contraste en los bordes;
  · «oscuro»   el de antes, estilo DaVinci.
Se elige en Ventana → «🎨 Tema» y se aplica al volver a abrir Reclaimer. Sin ventanas de Qt: lo leen theme.py y
common.py al cargarse.

  nombre() -> clave del tema · es_gris() -> ¿alguno de los grises? · paleta() -> {colores de la interfaz}
  linea() -> {colores de la línea de tiempo} · aclarar(hex) / aclarar_texto(css, no_tocar)
"""
from __future__ import annotations

import re

KEY = "interfaz/tema"
TEMAS = ("grafito", "pizarra", "gris", "oscuro")
POR_DEFECTO = "grafito"
NOMBRES = {"grafito": "Grafito (sobrio, profesional)", "pizarra": "Pizarra (gris frío, moderno)",
           "gris": "Gris claro (más contraste)", "oscuro": "Oscuro (el de antes)"}

# Colores de la interfaz (theme.py) por tema. «oscuro» no está: usa los de siempre.
PALETAS = {
    "grafito": dict(BG="#2e3033", BG_DEEP="#222326", HEADER="#28292c", RAISED="#3b3d42", RAISED_HI="#46494f",
                    FIELD="#252629", BORDER="#46484e", BORDER_HI="#5d6068", TEXT="#e9eaed", TEXT_DIM="#b3b6bd",
                    TEXT_FAINT="#868991", SUBE=0.07, FRIO=0.0),
    "pizarra": dict(BG="#2d3036", BG_DEEP="#212328", HEADER="#272a30", RAISED="#3a3e46", RAISED_HI="#454a53",
                    FIELD="#24272c", BORDER="#454a54", BORDER_HI="#5b616c", TEXT="#e7e9ee", TEXT_DIM="#afb4be",
                    TEXT_FAINT="#838995", SUBE=0.07, FRIO=0.012),
    "gris": dict(BG="#3a3c41", BG_DEEP="#2c2e32", HEADER="#33353a", RAISED="#4b4e55", RAISED_HI="#585b63",
                 FIELD="#2f3135", BORDER="#62656d", BORDER_HI="#7c7f88", TEXT="#f1f2f5", TEXT_DIM="#c8cad1",
                 TEXT_FAINT="#9da0a8", SUBE=0.17, FRIO=0.0),
}
# Colores de la línea de tiempo (common.COLORS) por tema
LINEAS = {
    "grafito": {"bg": "#292a2d", "panel": "#323337", "panel_alt": "#2d2e31", "line": "#45474d", "text": "#e9eaed",
                "text_dim": "#b3b6bd", "clip_disabled": "#55565b", "track_video": "#313439", "track_audio": "#2f3433",
                "topic_band": "#2c2d31", "grip": "#292a2d", "grip_line": "#1f2022", "meter_bg": "#222326",
                "header": "#323337", "header_sel": "#3d424b", "header_line": "#1f2022"},
    "pizarra": {"bg": "#282b30", "panel": "#31343a", "panel_alt": "#2c2f34", "line": "#444952", "text": "#e7e9ee",
                "text_dim": "#afb4be", "clip_disabled": "#53575e", "track_video": "#30353d", "track_audio": "#2e3536",
                "topic_band": "#2b2e34", "grip": "#282b30", "grip_line": "#1e2024", "meter_bg": "#212328",
                "header": "#31343a", "header_sel": "#3b4250", "header_line": "#1e2024"},
    "gris": {"bg": "#35373b", "panel": "#404247", "panel_alt": "#3a3c40", "line": "#5c5f66", "text": "#eef0f3",
             "text_dim": "#c2c5cc", "clip_disabled": "#5e5f65", "track_video": "#3e434c", "track_audio": "#3b453f",
             "topic_band": "#383b41", "grip": "#35373b", "grip_line": "#26282b", "meter_bg": "#2c2e32",
             "header": "#404247", "header_sel": "#4c5361", "header_line": "#26282b"},
}
_cache: str | None = None


def nombre() -> str:
    global _cache
    if _cache is None:
        try:
            from PySide6.QtCore import QSettings
            v = str(QSettings("EditorIA", "EditorIA").value(KEY, POR_DEFECTO))
        except Exception:  # noqa: BLE001
            v = POR_DEFECTO
        _cache = v if v in TEMAS else POR_DEFECTO
    return _cache


def es_gris() -> bool:
    return nombre() in PALETAS


def paleta() -> dict:
    return PALETAS.get(nombre(), {})


def linea() -> dict:
    return LINEAS.get(nombre(), {})


def aclarar(hexcol: str) -> str:
    """Un gris oscuro suelto (de una hoja de estilos) → su equivalente en el tema. Lo que tiene color no cambia."""
    p = paleta()
    if not p:
        return hexcol
    h = hexcol.lstrip("#")
    if len(h) != 6:
        return hexcol
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn > 0.12:                         # (con color: naranja, rojo, azul de los clips… igual)
        return hexcol
    if mx < 0.075:                             # (casi negro = fondo de video o de imagen: se queda negro)
        return hexcol
    sube = float(p.get("SUBE", 0.1))
    d = sube * max(0.25, 1.0 - 0.9 * mx)       # (continuo y siempre creciente: ningún gris se cruza con otro)
    frio = float(p.get("FRIO", 0.0))
    canal = lambda c, k: max(0, min(255, int(round((c + d + k) * 255))))   # noqa: E731
    return f"#{canal(r, -frio):02x}{canal(g, 0.0):02x}{canal(b, frio):02x}"


def qc(hexcol: str):
    """QColor de un gris dibujado a mano, ya en el tema (en «oscuro», el de siempre)."""
    from PySide6.QtGui import QColor
    return QColor(aclarar(hexcol))


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def aclarar_texto(css: str, no_tocar: set[str]) -> str:
    """Todos los grises sueltos de una hoja de estilos, al tema (salvo los de «no_tocar», que ya son del tema)."""
    keep = {c.lower() for c in no_tocar}
    return _HEX.sub(lambda m: m.group(0) if m.group(0).lower() in keep else aclarar(m.group(0)), css)
