"""
Marcas de la regla de la línea de tiempo: cada origen guarda las suyas y se muestran juntas. Así, las banderitas
de «🎬 Clips» (lo que dijiste) y las de «🔎 Buscar en lo que dijiste» no se pisan.
"""
from __future__ import annotations

_ORIGENES = ("clips", "buscar")

# 🔑 Qué palabras clave se ven en la regla (lo mismo en «Dijiste…» y en el botón de la esquina de la regla):
#   «todas» = todas las palabras · «elegida» = solo la elegida en la lista · «ninguna» = ocultas (nada se pierde).
MODOS = ("todas", "elegida", "ninguna")
NOMBRE_MODO = {"todas": "Todas", "elegida": "Elegida", "ninguna": "Ninguna"}
ICONO_MODO = {"todas": "eye", "elegida": "crosshair", "ninguna": "eye-off"}
TIP_MODO = {"todas": "Todas: banderitas de todas las palabras clave en la regla (la elegida, resaltada)",
            "elegida": "Elegida: solo las banderitas de la palabra elegida en «Dijiste…» (la fila ⚡ de material "
                       "va aparte, con su propio botón)",
            "ninguna": "Ninguna: oculta las banderitas y los chips de palabras clave (no se pierde nada; al elegir "
                       "una palabra en la lista, vuelve a «Elegida»)"}
CORTADA = "✂"          # (tras el icono de origen: «🎬✂ Palabra» = dicho en una parte que quitaste)


def modo_guardado() -> str:
    """El último modo elegido (por defecto, «todas»). Lo de antes («📍 Todas» sí / no) se respeta."""
    from PySide6.QtCore import QSettings
    st = QSettings("EditorIA", "EditorIA")
    v = str(st.value("clips/modo_marcas", "") or "")
    if v in MODOS:
        return v
    viejo = st.value("clips/todas_en_linea")
    if viejo is not None:
        return "todas" if str(viejo).lower() == "true" else "elegida"
    return "todas"


def guardar_modo(modo: str) -> None:
    from PySide6.QtCore import QSettings
    if modo in MODOS:
        QSettings("EditorIA", "EditorIA").setValue("clips/modo_marcas", modo)


def siguiente_modo(modo: str) -> str:
    return MODOS[(MODOS.index(modo) + 1) % len(MODOS)] if modo in MODOS else MODOS[0]


def set_source(timeline, origen: str, marcas) -> None:
    fuentes = getattr(timeline, "_marcas_por_origen", None)
    if fuentes is None:
        fuentes = {}
        timeline._marcas_por_origen = fuentes
    fuentes[origen] = list(marcas or [])
    juntas = []
    for k in _ORIGENES:
        juntas += fuentes.get(k, [])
    timeline.set_hint_marks(juntas)
