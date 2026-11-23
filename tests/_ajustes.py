"""
Las pruebas NO deben tocar tus ajustes de la ventana: esto guarda la distribución de paneles y el tamaño de la
ventana al empezar y los devuelve al terminar (pase lo que pase en la prueba).

  import _ajustes  (en cada prueba que abre la ventana principal)
"""
from __future__ import annotations

import atexit
import os

# 🎙 Las pruebas transcriben con el procesador (y sus modelos falsos); solo test_transcribir_tarjeta usa la tarjeta
os.environ.setdefault("EDITORIA_TARJETA_MOTOR", "0")

# 🔒 Las pruebas NUNCA escriben en tus ajustes de verdad (el registro de Windows): trabajan con una COPIA en un .ini
# temporal (ver editoria/_ajustes_prueba.py). El lanzador de pruebas ya pone RECLAIMER_AJUSTES_PRUEBA; si no, aquí.
_DIR_INI = os.environ.setdefault("RECLAIMER_AJUSTES_PRUEBA", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp", f"ajustes_{os.getpid()}"))
import sys as _sys  # noqa: E402
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from editoria import _ajustes_prueba  # noqa: E402
_ajustes_prueba.activar(_DIR_INI)
from PySide6.QtCore import QSettings  # noqa: E402  (ya la de prueba)
# 👋 la guía de primer uso NUNCA sale en las pruebas (además de no salir sin ventana: ui/guia_primer_uso)
QSettings("EditorIA", "EditorIA").setValue("guia_primer_uso/no_mostrar", True)
atexit.register(__import__("shutil").rmtree, _DIR_INI, True)

KEYS = ("ventana/paneles", "geometry", "reproduccion/proxy", "reproduccion/copias_auto")
_st = QSettings("EditorIA", "EditorIA")
_st.beginGroup("secciones")                         # qué secciones plegables dejaste abiertas
KEYS = KEYS + tuple("secciones/" + k for k in _st.allKeys()) + tuple(
    f"secciones/edit_musical/{t}" for t in ("Canción y estilo", "Efectos", "Clips", "Frases"))
_st.endGroup()
_st.beginGroup("espacios")                          # 🗂 pestañas de trabajo (cuál estaba abierta y sus proyectos)
KEYS = KEYS + ("espacios/actual",) + tuple("espacios/" + k for k in _st.allKeys()) + tuple(
    f"espacios/{t}/ruta" for t in ("youtube", "edit", "short"))
_st.endGroup()
_snap = {k: _st.value(k) for k in KEYS}
# Y TODOS los demás ajustes tal como estaban (los nuevos que vaya añadiendo Reclaimer también quedan protegidos:
# p. ej. «🤝 Dejar que Claude edite conmigo», el idioma de la ortografía, la vista del panel Texto…)
_all = {k: _st.value(k) for k in _st.allKeys()}


def _devolver():
    st = QSettings("EditorIA", "EditorIA")
    for k in st.allKeys():                   # lo que creó la prueba, fuera
        if k not in _all and k not in _snap:
            st.remove(k)
    for k, v in _all.items():
        st.setValue(k, v)
    for k, v in _snap.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    st.sync()


atexit.register(_devolver)

# Si una prueba se cuelga, antes de que el lanzador la corte (900 s) deja escrito DÓNDE estaba cada hilo
import faulthandler  # noqa: E402
import sys  # noqa: E402
try:
    sys.stdout.reconfigure(line_buffering=True)      # lo impreso no se pierde si la cortan
except (AttributeError, ValueError):
    pass
faulthandler.dump_traceback_later(840, exit=True)
