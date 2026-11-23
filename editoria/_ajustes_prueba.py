"""🔒 Solo para las pruebas: con la variable RECLAIMER_AJUSTES_PRUEBA=<carpeta>, los ajustes de Reclaimer
(QSettings("EditorIA", "EditorIA")) van a un archivo .ini en esa carpeta, copiado la primera vez de los ajustes
reales (que solo se LEEN). Así una prueba que se cierra de golpe nunca deja cambios en los ajustes de verdad."""
from __future__ import annotations

import os

# Ajustes del usuario que CAMBIAN lo que hace Reclaimer y que las pruebas dan por «de fábrica»: en la copia de prueba
# no se copian (cada prueba que quiera otro valor lo pone ella). Si no, una prueba pasaba o fallaba según lo último que
# eligió el usuario en su Reclaimer (p. ej. «Ninguna» en las banderitas, «▦ Encuadrar» apagado o videos en Material).
DE_FABRICA = (
    "clips/modo_marcas",            # Todas · Elegida · Ninguna (banderitas y chips de palabras clave en la regla)
    "clips/todas_en_linea",         # (lo de antes de modo_marcas)
    "shorts/encuadre_auto",         # 📱 encajar solo un video horizontal en un proyecto vertical
    "shorts/subtitulos_auto",       # 💬 subtítulos solos al añadir un video en Shorts/Edits
    "material_frases/tipo",         # imágenes / videos / ambos (videos = la red de verdad)
    "material_frases/trozo",
)
# Grupos enteros que no se copian: «espacios/» = la pestaña de trabajo abierta (Vertical, Edits…, que decide qué
# paneles se ven) y la ruta de los proyectos de verdad de cada pestaña (una prueba no debe abrir tus proyectos).
GRUPOS_DE_FABRICA = ("espacios/",)


def activar(carpeta: str) -> None:
    import PySide6.QtCore as QtCore
    real = getattr(QtCore, "_QSettingsReal", None) or QtCore.QSettings
    if getattr(QtCore.QSettings, "_de_prueba", False):
        return
    os.makedirs(carpeta, exist_ok=True)
    real.setPath(real.IniFormat, real.UserScope, carpeta)

    class AjustesDePrueba(real):
        _de_prueba = True

        def __init__(self, *a, **k):
            if len(a) == 2 and all(isinstance(x, str) for x in a) and not k:
                super().__init__(real.IniFormat, real.UserScope, *a)
            else:
                super().__init__(*a, **k)

    copia = AjustesDePrueba("EditorIA", "EditorIA")
    if not copia.allKeys():
        original = real("EditorIA", "EditorIA")
        for k in original.allKeys():
            if k not in DE_FABRICA and not k.startswith(GRUPOS_DE_FABRICA):
                copia.setValue(k, original.value(k))
        copia.sync()
    QtCore._QSettingsReal = real
    QtCore.QSettings = AjustesDePrueba


_carpeta = os.environ.get("RECLAIMER_AJUSTES_PRUEBA")
if _carpeta:
    activar(_carpeta)
