"""Punto de entrada: python main.py [proyecto.eia]"""
import os
import sys


def _ajustes_portatiles():
    """📦 Versión «todo en uno» (RECLAIMER_PORTABLE=1, lo pone Reclaimer.exe): sus ajustes van aparte, en
    HKEY_CURRENT_USER / Software / Reclaimer / TodoEnUno, para no mezclarse con un Reclaimer instalado en el mismo PC.
    (Siguen en el registro y no en un .ini: el registro guarda números y listas con su tipo, y Reclaimer los lee así.)"""
    if os.environ.get("RECLAIMER_PORTABLE") != "1":
        return
    import PySide6.QtCore as _qc
    base = _qc.QSettings

    class QSettings(base):
        def __init__(self, *a, **k):
            if len(a) == 2 and not k and a[0] == "EditorIA" and a[1] == "EditorIA":
                a = ("Reclaimer", os.environ.get("RECLAIMER_AJUSTES") or "TodoEnUno")   # (la prueba usa otra)
            super().__init__(*a, **k)
    _qc.QSettings = QSettings                 # (antes de cargar Reclaimer: todo lo que importe QSettings usa este)


def _registro_arranque():
    """📦 En la versión «todo en uno» Python no tiene consola (pythonw): si algo falla al abrir, se apunta en
    datos\\registros\\arranque.log (Reclaimer.exe lo enseña si el programa se cierra en los primeros segundos)."""
    if os.environ.get("RECLAIMER_PORTABLE") != "1" or sys.stderr is not None:
        return
    try:
        from editoria.core.paths import app_data_dir      # (sin Qt: solo carpetas)
        d = app_data_dir() / "registros"
        d.mkdir(parents=True, exist_ok=True)
        f = open(d / "arranque.log", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - abierto mientras viva
        sys.stderr = f
        if sys.stdout is None:
            sys.stdout = f
    except OSError:
        pass


_registro_arranque()
_ajustes_portatiles()

from editoria.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run(sys.argv))
