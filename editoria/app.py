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
    QTimer.singleShot(3000, win, lambda: _congelar_memoria(win))   # (con la ventana como dueña: si se cierra antes, no salta)


def marca_arranque(texto: str) -> None:
    """Una línea en datos\\registros\\arranque.log (lo abre main.py): Reclaimer.exe la busca para saber que el programa
    llegó a abrir («ventana visible») y no avisar de un fallo que no hubo."""
    import os
    if texto == "ventana visible":
        os.environ["RECLAIMER_VENTANA_VISIBLE"] = "1"   # (main.py: un fallo después ya no es «no pudo abrirse»)
    ruta = os.environ.get("RECLAIMER_ARRANQUE_LOG")
    if not ruta:
        return
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {texto} pid={os.getpid()}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 🔒 una sola ventana de Reclaimer por carpeta de datos
_instancia: dict = {}


def _nombre_servidor(datos) -> str:
    import hashlib
    import os
    h = hashlib.sha1(os.path.normcase(os.path.abspath(str(datos))).encode("utf-8")).hexdigest()[:16]
    return f"ReclaimerInstancia_{h}"


def bloquear_instancia(datos, espera_ms: int = 100):
    """Intenta ser LA instancia de esa carpeta de datos (QLockFile en datos\\instancia.lock). Devuelve el bloqueo
    (guárdalo mientras viva el programa) o None si ya hay otra abierta con esa carpeta. Si la otra murió de golpe,
    el bloqueo se recupera solo (Qt mira si su proceso sigue vivo)."""
    import os
    from PySide6.QtCore import QLockFile
    os.makedirs(str(datos), exist_ok=True)
    lock = QLockFile(os.path.join(str(datos), "instancia.lock"))
    lock.setStaleLockTime(0)              # (solo se da por muerto si su proceso ya no existe)
    if lock.tryLock(espera_ms):
        return lock
    if lock.error() == QLockFile.LockFailedError and lock.removeStaleLockFile() and lock.tryLock(espera_ms):
        return lock
    return None


def _pasar_a_la_otra(datos, argv: list[str], espera_ms: int = 30000) -> bool:
    """Ya hay un Reclaimer abierto con estos datos: le pasa el proyecto (si se abrió con uno) y le pide que se ponga
    delante. True si contestó."""
    import json
    import os
    from PySide6.QtNetwork import QLocalSocket
    eia = next((a for a in argv[1:] if a.lower().endswith(".eia")), "")
    if sys.platform == "win32":
        try:                              # (para que la otra pueda ponerse delante: Windows no deja robar el foco)
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception:  # noqa: BLE001
            pass
    msg = (json.dumps({"abrir": os.path.abspath(eia) if eia else ""}, ensure_ascii=False) + "\n").encode("utf-8")
    import time
    t0 = time.time()
    while (time.time() - t0) * 1000 < espera_ms:
        sock = QLocalSocket()
        sock.connectToServer(_nombre_servidor(datos))
        if sock.waitForConnected(1000):
            sock.write(msg)
            sock.waitForBytesWritten(2000)
            # (la otra contesta en cuanto atiende: si aún está arrancando, puede tardar unos segundos)
            ok = sock.waitForReadyRead(max(1000, int(espera_ms - (time.time() - t0) * 1000)))
            sock.disconnectFromServer()
            return ok
        time.sleep(0.3)
    return False


def _escuchar_otras(datos):
    """La instancia viva escucha: otra que se abra con estos datos le pasa su proyecto y se cierra."""
    import json
    from PySide6.QtNetwork import QLocalServer
    nombre = _nombre_servidor(datos)
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.UserAccessOption)
    if not srv.listen(nombre):
        QLocalServer.removeServer(nombre)       # (uno viejo que quedó de un cierre de golpe)
        if not srv.listen(nombre):
            return None
    pendientes: list[str] = []
    _instancia["pendientes"] = pendientes

    def nueva():
        while srv.hasPendingConnections():
            sock = srv.nextPendingConnection()
            buf = bytearray()

            def leer(s=sock, b=buf):
                b += bytes(s.readAll())
                if not b.endswith(b"\n"):
                    return                       # (aún no llegó entera)
                try:
                    ruta = str(json.loads(b.decode("utf-8", "replace").strip()).get("abrir") or "")
                except (ValueError, AttributeError):
                    ruta = ""
                b.clear()
                s.write(b"ok\n")
                s.flush()
                pendientes.append(ruta)
                _instancia["avisado"] = False    # (otra petición: vuelve al frente y avisa otra vez)
                _atender_pendientes()
            sock.readyRead.connect(leer)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                leer()
    srv.newConnection.connect(nueva)
    return srv


def _atender_pendientes():
    win = _instancia.get("win")
    pend = _instancia.get("pendientes")
    if win is None or not pend:
        return
    if not _instancia.get("avisado"):      # (al frente una vez; no cada segundo mientras espera)
        _al_frente(win)
    rutas = [r for r in pend if r]
    if not rutas:
        pend[:] = []
        return
    # Con una ventana abierta encima (un diálogo, una pregunta) o una tarea en marcha, el proyecto NO se abre aún:
    # se queda pendiente y se vuelve a mirar cada segundo (abrirlo a la fuerza podía romper lo que estabas haciendo)
    ocupado = ""
    try:
        if QApplication.activeModalWidget() is not None:
            ocupado = "hay una ventana abierta"
        elif getattr(win, "workspaces", None) is not None:
            ocupado = win.workspaces._busy()
    except Exception:  # noqa: BLE001
        ocupado = ""
    if ocupado:
        if not _instancia.get("avisado"):
            _instancia["avisado"] = True
            try:
                import os
                win.statusBar().showMessage(f"📂 {os.path.basename(rutas[0])}: se abrirá en cuanto termines "
                                            f"({ocupado}).", 10000)
            except Exception:  # noqa: BLE001
                pass
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1000, _atender_pendientes)
        return
    _instancia["avisado"] = False
    pend[:] = []
    for ruta in rutas:
        win.open_project(ruta)


def _al_frente(win):
    try:
        if win.isMinimized():
            win.showNormal()
        win.show()
        win.raise_()
        win.activateWindow()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(win.winId()))
    except Exception:  # noqa: BLE001 - ponerse delante nunca debe fallar
        pass


def soltar_instancia():
    """Al salir: el bloqueo y el servidor, fuera YA (antes de esperar a los trabajos que quedan): si no, abrir
    Reclaimer otra vez enseguida decía «ya está abierto, pero no responde»."""
    srv = _instancia.pop("server", None)
    if srv is not None:
        try:
            srv.close()
        except RuntimeError:
            pass
    lock = _instancia.pop("lock", None)
    if lock is not None:
        try:
            lock.unlock()
        except RuntimeError:
            pass


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
    try:                                       # 🔍 escala de la interfaz (2K/4K con Windows al 100 %: más grande)
        from .ui.ui_scale import apply_before_app
        apply_before_app()
    except Exception:  # noqa: BLE001 - sin esto, la de siempre
        pass
    app = QApplication(argv)
    # 🔒 Una sola ventana por carpeta de datos: dos a la vez se pisaban el autoguardado, el aviso de «se cerró
    # inesperadamente» y el puente de Claude. La segunda le pasa el proyecto a la que ya está abierta y se cierra.
    # (📦 La prueba de arranque —RECLAIMER_SALIR_TRAS— se la salta: si no, con tu Reclaimer abierto le pasaría el
    # turno a tu ventana y daría la prueba por buena sin haber arrancado nada)
    from .core.paths import app_data_dir as _datos
    import os as _os
    _salir = _os.environ.get("RECLAIMER_SALIR_TRAS")          # 📦 prueba de arranque (versión todo en uno): se cierra sola
    if not _salir:
        _lock = bloquear_instancia(_datos())
        if _lock is None:
            if _pasar_a_la_otra(_datos(), argv):
                marca_arranque("ventana ya abierta (le paso el proyecto)")
                return 0
            import time as _t
            t0 = _t.time()                       # (quizá la otra se estaba cerrando: se espera a que suelte el bloqueo)
            while _lock is None and _t.time() - t0 < 3.0:
                _lock = bloquear_instancia(_datos(), 300)
            if _lock is None:
                marca_arranque("error avisado: otra ventana no responde")
                QMessageBox.warning(None, APP_NAME, "Reclaimer ya está abierto, pero no responde.\n\n"
                                                    "Espera un momento y vuelve a intentarlo. Si sigue igual, ciérralo "
                                                    "desde el Administrador de tareas (Ctrl+Mayús+Esc).")
                return 1
        _instancia["lock"] = _lock
        _instancia["server"] = _escuchar_otras(_datos())
    if _salir:
        from PySide6.QtCore import QTimer as _QT

        def _fin():
            try:
                from .core.paths import app_data_dir
                from PySide6.QtCore import QSettings as _QS
                from .core import motor_ia as _mi
                from .core.paths import user_dir
                (app_data_dir() / "arranque_ok.txt").write_text(      # (lo que comprueba la prueba)
                    f"ok\ndatos={app_data_dir()}\nmis_cosas={user_dir()}\n"
                    f"ajustes={_QS('EditorIA', 'EditorIA').fileName()}\nmotor={_mi.DATOS_MOTOR}\n", encoding="utf-8")
            finally:
                app.quit()
        _QT.singleShot(int(float(_salir) * 1000), _fin)
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
    marca_arranque("ventana visible")
    _instalar_congelado_memoria(win)
    win.try_recover()
    if len(argv) > 1 and argv[1].lower().endswith(".eia"):
        win.open_project(argv[1])
    _instancia["win"] = win
    _atender_pendientes()                 # (si otra se abrió mientras esta arrancaba)
    rc = app.exec()
    _instancia.pop("win", None)
    soltar_instancia()                    # (otra puede abrirse ya, aunque esta tarde un poco en terminar)
    # Si algún trabajo de la IA no paró a tiempo, se sale sin destruir su hilo a medias (tu proyecto ya está
    # guardado): así nunca hay un «cierre inesperado» al cerrar.
    from .ui.task_window import stop_all
    if stop_all(4000) or not getattr(win, "_pool_idle", True):
        # (antes de salir: ajustes al disco, lo pendiente de image_feedback y las demás tareas de salida)
        from .ui.jobs import salir_sin_romper
        salir_sin_romper(rc)
    return rc
