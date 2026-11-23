"""RECLAIMER: editor de video con asistente de IA para YouTube (videos, Shorts y edits)."""

APP_NAME = "Reclaimer"
SUPPORT_URL = "https://ko-fi.com/pigmeofurtivoyt"   # página de donaciones (Ko-fi); vacía = no se muestra «♥ Apoyar Reclaimer»
__version__ = "0.4.0"

import os as _os
import sys as _sys

# 🔒 Pruebas: NUNCA tocan los ajustes reales (registro). Con el lanzador (RECLAIMER_AJUSTES_PRUEBA) o, si una prueba se
# ejecuta directamente (tests/test_*.py, scripts en _pruebas_tmp), también: un .ini temporal propio.
_principal = _os.path.abspath(_sys.argv[0]) if _sys.argv and _sys.argv[0] else ""
if not _os.environ.get("RECLAIMER_AJUSTES_PRUEBA") and _principal and (_os.path.basename(_principal).startswith("test_")
                                                                 or _os.sep + "tests" + _os.sep in _principal
                                                                 or "_pruebas_tmp" in _principal):
    _os.environ["RECLAIMER_AJUSTES_PRUEBA"] = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                                         "_pruebas_tmp", f"ajustes_directo_{_os.getpid()}")
if _os.environ.get("RECLAIMER_AJUSTES_PRUEBA"):
    from . import _ajustes_prueba  # noqa: E402,F401
