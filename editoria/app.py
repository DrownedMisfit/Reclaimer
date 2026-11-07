"""Arranque de la aplicación."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME
from .core.paths import log_path
from .ui.main_window import MainWindow
from .ui.theme import apply_dark_theme


def _install_error_handler():
    """Cualquier error inesperado se guarda en un registro y se muestra, sin cerrar el programa."""
    shown: dict[str, float] = {}          # el mismo error repetido: se anota, pero no abre otra ventana
    open_now: set[str] = set()

    def handler(exc_type, exc, tb):
        import time
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}")
        except OSError:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)
        key = f"{exc_type.__name__}: {exc}"
        if not QApplication.instance() or key in open_now or time.time() - shown.get(key, 0) < 30:
            return
        shown[key] = time.time()
        open_now.add(key)
        try:
            QMessageBox.critical(None, "Error inesperado",
                                 f"Ocurrió un error (el programa sigue abierto):\n\n{exc}\n\n"
                                 f"Detalles guardados en:\n{log_path()}")
        finally:
            open_now.discard(key)
    sys.excepthook = handler


_crash_file = None


def _install_crash_log():
    """Si el programa se cierra de golpe (un fallo dentro de Qt, FFmpeg o un modelo), Python no llega a
    avisar: faulthandler deja escrito dónde murió, para poder arreglarlo. También se guardan los avisos
    graves de Qt."""
    global _crash_file
    import faulthandler
    try:
        path = log_path().with_name("cierres_inesperados.log")
        _crash_file = open(path, "a", encoding="utf-8")
        _crash_file.write(f"\n=== sesión {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
        _crash_file.flush()
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError:
        return
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def qt_messages(mode, _ctx, msg):
        if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            try:
                _crash_file.write(f"[Qt {datetime.now():%H:%M:%S}] {msg}\n")
                _crash_file.flush()
            except (OSError, ValueError):
                pass
    qInstallMessageHandler(qt_messages)


def _migrate_data(app):
    """Una sola vez: los datos que había en C: (modelos de IA, caché, copias…) se mudan a F:/Reclaimer/datos."""
    from .core.paths import app_data_dir, migrate_old_data, old_data_dir
    if old_data_dir() is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QProgressDialog
    dlg = QProgressDialog(f"Moviendo los datos de Reclaimer de C: a {app_data_dir()}…\n(solo esta vez)",
                          None, 0, 100)
    dlg.setWindowTitle("Reclaimer")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(460)
    dlg.show()

    def progress(done, total, _name):
        dlg.setMaximum(max(1, total))
        dlg.setValue(done)
        app.processEvents()
    try:
        migrate_old_data(progress)
    except Exception:  # noqa: BLE001 - mudar nunca debe impedir abrir el programa
        pass
    dlg.close()


def _no_console_fix():
    """Reclaimer se abre SIN consola (pythonw): no hay dónde escribir y cualquier librería que enseñe su
    progreso (descargas de modelos de IA, tqdm…) fallaba con «'NoneType' object has no attribute 'write'».
    Se le da una salida que no va a ninguna parte, y las barras de progreso de consola se apagan."""
    import os
    if sys.stdout is None or sys.stderr is None:
        sink = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = sink
        if sys.stderr is None:
            sys.stderr = sink
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")


_ultimo_congelado_ms = [0.0]


def _congelar_memoria(win):
    """Lo que ya vive (proyecto, ventanas, modelos cargados) sale del recolector de basura de Python: sus pausas de
    la generación 2 (60–300 ms tras editar) dejan de caer en medio de la edición. Antes se descongela para que cada
    vez se recoja la basura de verdad (si no, los objetos que mueren después se quedarían sin liberar)."""
    import gc
    import time
    if _ultimo_congelado_ms[0] > 100:            # el aviso solo cuando suele tardar
        win.statusBar().showMessage("Optimizando memoria…")
        QApplication.processEvents()
    t0 = time.perf_counter()
    gc.unfreeze()
    gc.collect()
    gc.freeze()
    _ultimo_congelado_ms[0] = (time.perf_counter() - t0) * 1000
    if _ultimo_congelado_ms[0] > 100:
        win.statusBar().clearMessage()


def _instalar_congelado_memoria(win):
    """Tras 3 s de arranque, y de nuevo (con un pequeño retardo, para que pase el trabajo) al abrir o cambiar de
    proyecto. NO tras cada transcripción o cambio de medios: media_changed salta muy a menudo (cada clip analizado) y
    cada pasada cuesta ~160 ms en un proyecto grande, así que crearía los tirones que quiere evitar."""
    from PySide6.QtCore import QTimer
    retardo = QTimer(win)
    retardo.setSingleShot(True)
    retardo.setInterval(2000)
    retardo.timeout.connect(lambda: _congelar_memoria(win))
    ctrl = win.ctrl
    ctrl.project_replaced.connect(lambda *_: retardo.start())
    QTimer.singleShot(3000, lambda: _congelar_memoria(win))


def run(argv: list[str]) -> int:
    _no_console_fix()
    if sys.platform == "win32":
        try:  # para que Windows muestre el icono de Reclaimer en la barra de tareas (y no el de Python)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Reclaimer.Editor")
        except Exception:  # noqa: BLE001
            pass
    from PySide6.QtCore import QCoreApplication, Qt as _Qt
    QCoreApplication.setAttribute(_Qt.AA_ShareOpenGLContexts)   # (el buscador de PNG del taller usa un navegador)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("EditorIA")   # (nombre interno: conserva tus ajustes guardados)
    from .ui.branding import app_icon
    app.setWindowIcon(app_icon())
    apply_dark_theme(app)
    _migrate_data(app)
    _install_error_handler()
    _install_crash_log()
    win = MainWindow()
    win.show()
    _instalar_congelado_memoria(win)
    win.try_recover()
    if len(argv) > 1 and argv[1].lower().endswith(".eia"):
        win.open_project(argv[1])
    rc = app.exec()
    # Si algún trabajo de la IA no paró a tiempo, se sale sin destruir su hilo a medias (tu proyecto ya está
    # guardado): así nunca hay un «cierre inesperado» al cerrar.
    from .ui.task_window import stop_all
    if stop_all(4000) or not getattr(win, "_pool_idle", True):
        sys.stdout.flush()
        sys.stderr.flush()
        import os
        os._exit(rc)
    return rc
