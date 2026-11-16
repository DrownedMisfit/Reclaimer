"""Punto de entrada: python main.py [proyecto.eia]"""
import faulthandler
import os
import sys
import time

# 📝 Registro de arranque: datos\registros\arranque.log (se AÑADE: la prueba de un fallo anterior no se borra; si pasa
# de ~200 KB, el viejo queda como arranque.log.1). faulthandler va lo primero, antes de cargar nada pesado: si Python
# muere de golpe al abrir (un fallo dentro de Qt o de una librería), queda escrito dónde.
ARRANQUE_MAX = 200 * 1024
_registro = None


def _abrir_registro():
    global _registro
    try:
        from editoria.core.paths import app_data_dir      # (sin Qt: solo carpetas)
        d = app_data_dir() / "registros"
        d.mkdir(parents=True, exist_ok=True)
        ruta = d / "arranque.log"
        try:
            if ruta.stat().st_size > ARRANQUE_MAX:
                os.replace(ruta, d / "arranque.log.1")
        except OSError:
            pass
        _registro = open(ruta, "a", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115 - mientras viva
        _registro.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} argv={sys.argv!r} ===\n")
        os.environ["RECLAIMER_ARRANQUE_LOG"] = str(ruta)  # (editoria.app apunta ahí «ventana visible»)
        faulthandler.enable(_registro, all_threads=True)
        # Sin consola (pythonw): lo que Python escriba como error va aquí en vez de perderse
        if sys.stderr is None:
            sys.stderr = _registro
    except Exception:  # noqa: BLE001 - el registro nunca impide abrir
        _registro = None


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


def _fallo_al_abrir():
    """Un fallo que Python no atrapó: el detalle al registro y un aviso en español (sin él, «no abría nada» y no
    quedaba rastro). Si la ventana ya se había visto, el aviso es de cierre inesperado."""
    import traceback
    texto = traceback.format_exc()
    ruta = os.environ.get("RECLAIMER_ARRANQUE_LOG", "")
    try:
        if _registro is not None:
            _registro.write(texto)
            _registro.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} error avisado pid={os.getpid()}\n")
            _registro.flush()
        elif sys.__stderr__ is not None:
            sys.__stderr__.write(texto)
    except (OSError, ValueError):
        pass
    if os.name != "nt" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":     # (pruebas: sin ventanas)
        return
    ultima = texto.strip().splitlines()[-1] if texto.strip() else ""
    abierto = os.environ.get("RECLAIMER_VENTANA_VISIBLE") == "1"     # (ya había abierto: se cerró después)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, ("Reclaimer se cerró inesperadamente." if abierto else "Reclaimer no pudo abrirse.")
            + "\n\n" + ultima[:400]
            + (f"\n\nEl detalle está en:\n{ruta}" if ruta else ""), "Reclaimer", 0x10)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    _abrir_registro()
    try:
        _ajustes_portatiles()
        from editoria.app import run
        rc = run(sys.argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - cualquier fallo al cargar o al arrancar: se apunta y se avisa
        _fallo_al_abrir()
        rc = 1
    sys.exit(rc)
