"""Arranque de la aplicación."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME
from .core.paths import log_path
from .ui.theme import apply_dark_theme


def __getattr__(nombre):
    """⚡ (23/11) La ventana principal se carga DENTRO de run(), tras enseñar la ventana de arranque (son ~0,6 s de
    imports); quien pida editoria.app.MainWindow (la prueba de arranque) la recibe igual."""
    if nombre == "MainWindow":
        from .ui.main_window import MainWindow
        return MainWindow
    raise AttributeError(nombre)


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


# ---------------------------------------------------------------- ⚡ arranque rápido y sin pantallazo blanco (23/11)
def _ocultar_en_dwm(w, ocultar: bool) -> bool:
    """Windows: «encubre» la ventana (DWMWA_CLOAK) sin esconderla para Qt. Encubierta, se crea, se coloca y se pinta
    entera sin que se vea; al destaparla aparece ya pintada (sin el fondo blanco del primer instante). True si se pudo
    (fuera de Windows o sin ventana real, no hace nada)."""
    import os
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        return False
    try:
        hwnd = int(w.winId())
        ok = _dwm_encubrir(hwnd, ocultar)
        if ok and ocultar:
            _ENCUBIERTAS.add(hwnd)
        elif not ocultar:
            _ENCUBIERTAS.discard(hwnd)
        return ok
    except Exception:  # noqa: BLE001 - sin DWM: se enseña como siempre
        return False


_ENCUBIERTAS: set[int] = set()      # ventanas encubiertas ahora mismo (el vigía las destapa si algo se cuelga)


def _dwm_encubrir(hwnd: int, ocultar: bool) -> bool:
    """DWMWA_CLOAK sobre un hwnd (no pasa por Qt: el vigía lo usa desde su hilo aunque la interfaz esté parada)."""
    import ctypes
    from ctypes import wintypes
    valor = ctypes.c_int(1 if ocultar else 0)
    r = ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 13,          # 13 = DWMWA_CLOAK
                                                   ctypes.byref(valor), ctypes.sizeof(valor))
    return r == 0


def _mostrar_pintada(w, app, seguro_ms: int = 4000) -> None:
    """show() sin pantallazo blanco: encubierta → show → se atienden los eventos (pintado y colocación de paneles de
    los temporizadores a 0 ms) → se destapa ya pintada. Si algo fallara, se destapa igual (nunca queda invisible).
    🛟 Seguro: si a los seguro_ms sigue encubierta (p. ej. salió un aviso modal a mitad y su bucle se quedó esperando),
    un temporizador la destapa, cierra la ventana de arranque y lo apunta en arranque.log."""
    oculta = _ocultar_en_dwm(w, True)
    if oculta:
        from PySide6.QtCore import QTimer

        def seguro(w=w):
            try:
                hwnd = int(w.winId())
            except RuntimeError:
                return
            if hwnd in _ENCUBIERTAS:
                _ocultar_en_dwm(w, False)
                _cerrar_ventana_de_arranque(_instancia.get("arranque"))
                marca_arranque(f"seguro: destapada a la fuerza tras {seguro_ms / 1000:.0f} s (el primer pintado no "
                               f"terminó: ¿un aviso a mitad?) [{type(w).__name__}]")
        QTimer.singleShot(seguro_ms, seguro)
    try:
        w.show()
        for _ in range(3):
            app.processEvents()
    finally:
        if oculta:
            _ocultar_en_dwm(w, False)


def _vigia_arranque(segundos: float = 25.0):
    """🛟 Vigía en su propio hilo: si en `segundos` no se llega a «ventana visible» (la interfaz colgada), apunta en
    arranque.log dónde está cada hilo (para poder arreglarlo), destapa lo que siguiera encubierto y esconde la ventana
    de arranque (con llamadas de Windows que no esperan a la interfaz). Devuelve el Event que hay que marcar al
    verse la ventana."""
    import os
    import threading
    listo = threading.Event()

    def vigilar():
        if listo.wait(segundos):
            return
        ruta = os.environ.get("RECLAIMER_ARRANQUE_LOG")
        try:
            if ruta:
                import faulthandler
                with open(ruta, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} vigía: {segundos:.0f} s sin «ventana visible»: "
                            f"se destapa y se apunta dónde está cada hilo pid={os.getpid()}\n")
                    f.flush()
                    faulthandler.dump_traceback(file=f, all_threads=True)
        except Exception:  # noqa: BLE001
            pass
        if sys.platform != "win32":
            return
        for hwnd in list(_ENCUBIERTAS):
            try:
                _dwm_encubrir(hwnd, False)
            except Exception:  # noqa: BLE001
                pass
        h = _instancia.get("arranque_hwnd")
        if h:
            try:
                import ctypes
                ctypes.windll.user32.ShowWindowAsync(ctypes.c_void_p(h), 0)     # SW_HIDE, sin esperar
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=vigilar, name="vigia_arranque", daemon=True).start()
    return listo


ARRANQUE_VERSION = 2             # (súbelo si cambia el dibujo: la imagen guardada en la caché se rehace)
ARRANQUE_TAM = (440, 300)        # tamaño de la ventana de arranque (px lógicos)
_LOGO_ALTO = 132                 # alto del símbolo (px lógicos)


def _mascara_logo(alto_px: int):
    """La forma del símbolo a alto_px de alto, desde el VECTORIAL (assets/reclaimer.svg) con suavizado y 16 bits por
    canal: nítida a cualquier escala de Windows (100 %, 125 %, 150 %…). Si el SVG fallara, el PNG grande (1024)."""
    import os
    from PySide6.QtCore import QRect, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    try:
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(os.path.join(assets, "reclaimer.svg"))
        if not r.isValid():
            raise ValueError("svg")
        lado = int(alto_px / 0.93) + 8                    # (el símbolo ocupa ~92,6 % del alto de su caja de 100×100)
        im = QImage(lado, lado, QImage.Format_RGBA64_Premultiplied)
        im.fill(Qt.transparent)
        p = QPainter(im)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, lado, lado))
        p.end()
    except Exception:  # noqa: BLE001
        im = QImage(os.path.join(assets, "reclaimer_claro_1024.png"))
        if im.isNull():
            return None
        im = im.convertToFormat(QImage.Format_RGBA64_Premultiplied)
    # recortar a lo que ocupa de verdad y llevarlo al alto pedido
    import numpy as np
    a = np.frombuffer(im.constBits(), np.uint16, count=im.height() * im.bytesPerLine() // 2).reshape(
        im.height(), im.bytesPerLine() // 2)[:, 3:im.width() * 4:4]
    ys, xs = np.nonzero(a > 0)
    if not len(xs):
        return None
    im = im.copy(QRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
    if im.height() != alto_px:
        im = im.scaledToHeight(alto_px, Qt.SmoothTransformation)
    return im


def _logo_en_relieve(alto_px: int, dpr: float):
    """El símbolo con relieve sutil, en la línea de la «profundidad sutil» de diseno.py: metal acero/cromo de arriba a
    abajo, bisel de luz arriba a la izquierda, sombra interior suave abajo y sombra proyectada difusa debajo.
    (QImage de 16 bits con margen para la sombra, margen en px). Se pinta UNA vez: luego va a la caché."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
    mask = _mascara_logo(alto_px)
    if mask is None:
        return None
    w, h = mask.width(), mask.height()
    fmt = QImage.Format_RGBA64_Premultiplied            # (16 bits: degradados sin escalones)

    def vacia(ww=w, hh=h):
        im = QImage(ww, hh, fmt)
        im.fill(Qt.transparent)
        return im

    def tenir(brocha, dx=0.0, dy=0.0):               # la forma (desplazada) rellena con una brocha
        im = vacia()
        p = QPainter(im)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(im.rect(), brocha)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(QPointF(dx, dy), mask)
        p.end()
        return im

    def recortar(im, m, modo):                       # im dentro (DestinationIn) o fuera (DestinationOut) de m
        p = QPainter(im)
        p.setCompositionMode(modo)
        p.drawImage(0, 0, m)
        p.end()
        return im

    def difuminar(im, r):                            # desenfoque suave: reducir y volver a ampliar (dos pasos)
        for _ in range(2):
            ww, hh = max(1, int(im.width() / r)), max(1, int(im.height() / r))
            im = im.scaled(ww, hh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).scaled(
                im.width(), im.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            r = max(1.0, r * 0.6)
        return im

    b = 1.25 * dpr                                    # bisel: ~1,25 px lógicos
    metal = QLinearGradient(0, 0, 0, h)               # acero/cromo: claro arriba, banda de reflejo, más oscuro abajo
    for pos, col in ((0.0, "#f3f5f8"), (0.38, "#cdd2d9"), (0.52, "#a3a9b2"), (0.60, "#b9bfc7"),
                     (0.82, "#9399a3"), (1.0, "#7d838d")):
        metal.setColorAt(pos, QColor(col))
    fuera = QPainter.CompositionMode_DestinationOut
    luz = recortar(tenir(QColor(255, 255, 255, 165)), tenir(QColor(0, 0, 0), b, b), fuera)   # borde de luz
    sombra_int = recortar(difuminar(recortar(tenir(QColor(0, 0, 0, 150)), tenir(QColor(0, 0, 0), -b, -b), fuera),
                                    1.6 * dpr), mask, QPainter.CompositionMode_DestinationIn)   # sombra interior
    m = int(16 * dpr)                                 # margen para la sombra proyectada
    proyectada = vacia(w + 2 * m, h + 2 * m)
    p = QPainter(proyectada)
    p.drawImage(m, m, tenir(QColor(0, 0, 0)))
    p.end()
    proyectada = difuminar(proyectada, 5.0 * dpr)
    out = vacia(w + 2 * m, h + 2 * m)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setOpacity(0.55)
    p.drawImage(QPointF(0, 4 * dpr), proyectada)     # sombra difusa, un poco por debajo
    p.setOpacity(1.0)
    p.drawImage(m, m, tenir(metal))
    p.drawImage(m, m, sombra_int)
    p.drawImage(m, m, luz)
    p.end()
    return out, m


def _a_8_bits(img64):
    """16 → 8 bits por canal con un tramado finísimo (±1 nivel, triangular): sin bandas en los degradados oscuros."""
    import numpy as np
    from PySide6.QtGui import QImage
    img64 = img64.convertToFormat(QImage.Format_RGBA64)
    w, h = img64.width(), img64.height()
    a = np.frombuffer(img64.constBits(), np.uint16, count=h * img64.bytesPerLine() // 2).reshape(
        h, img64.bytesPerLine() // 2)[:, :w * 4].reshape(h, w, 4).astype(np.float32) / 257.0
    rng = np.random.default_rng(23)
    a[..., :3] += (rng.random((h, w, 1), dtype=np.float32) - rng.random((h, w, 1), dtype=np.float32))
    out = np.ascontiguousarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).convertToFormat(QImage.Format_ARGB32_Premultiplied)


def _pintar_arranque(fondo, texto, dpr: float):
    """La imagen entera de la ventana de arranque, en px físicos (al devicePixelRatio de la pantalla: sin escalar al
    enseñarla), pintada a 16 bits y pasada a 8 con tramado."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRadialGradient
    from .ui.theme import FONT_FAMILIES
    ancho, alto = ARRANQUE_TAM
    img = QImage(round(ancho * dpr), round(alto * dpr), QImage.Format_RGBA64_Premultiplied)
    img.fill(fondo)
    img.setDevicePixelRatio(dpr)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    halo = QRadialGradient(QPointF(ancho / 2, 112), ancho * 0.62)      # (un leve foco tras el símbolo)
    halo.setColorAt(0.0, QColor(fondo).lighter(124))
    halo.setColorAt(1.0, QColor(fondo))
    p.fillRect(QRectF(0, 0, ancho, alto), halo)
    r = _logo_en_relieve(round(_LOGO_ALTO * dpr), dpr)
    if r is not None:
        logo, m = r
        p.save()
        p.scale(1 / dpr, 1 / dpr)                                     # (la imagen del símbolo va en px físicos)
        p.drawImage(QPointF(round((ancho * dpr - logo.width()) / 2), round(46 * dpr) - m), logo)
        p.restore()
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(16)
    f.setBold(True)
    f.setHintingPreference(QFont.PreferNoHinting)                     # (mismo dibujo a 100 % y a 150 %)
    p.setFont(f)
    caja = QRectF(0, 196, ancho, 34)
    p.setPen(QColor(0, 0, 0, 120))                                    # (bisel muy leve, como el del símbolo)
    p.drawText(caja.translated(0, 1.0), Qt.AlignCenter, APP_NAME)
    p.setPen(QColor(255, 255, 255, 34))
    p.drawText(caja.translated(0, -0.6), Qt.AlignCenter, APP_NAME)
    p.setPen(QPen(texto))
    p.drawText(caja, Qt.AlignCenter, APP_NAME)
    f.setPointSizeF(9.5)
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor(texto).darker(150))
    p.drawText(QRectF(0, 234, ancho, 24), Qt.AlignCenter, "Abriendo…")
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QPen(QColor(fondo).lighter(150), 0))                     # (borde sutil de 1 px físico)
    p.scale(1 / dpr, 1 / dpr)
    p.drawRect(0, 0, img.width() - 1, img.height() - 1)
    p.end()
    out = _a_8_bits(img)
    out.setDevicePixelRatio(dpr)
    return out


def _imagen_de_arranque(fondo, texto, dpr: float):
    """La imagen de la ventana de arranque desde la caché (datos\\cache\\arranque: un PNG por tema y por escala de
    pantalla; otra escala o otro dibujo = otro archivo). La primera vez se pinta y se guarda (~0,1–0,3 s); leerla
    cuesta unos pocos ms."""
    from PySide6.QtGui import QImage, QPixmap
    ruta = None
    try:
        from .core.paths import cache_dir
        d = cache_dir("arranque")
        nombre = (f"arranque_v{ARRANQUE_VERSION}_{fondo.name()[1:]}_{texto.name()[1:]}_{round(dpr * 100)}.png")
        ruta = d / nombre
        if ruta.exists():
            im = QImage(str(ruta))
            if not im.isNull():
                pm = QPixmap.fromImage(im)
                pm.setDevicePixelRatio(dpr)
                return pm
        for viejo in d.glob("arranque_v*.png"):                      # (las de un dibujo anterior, fuera)
            if not viejo.name.startswith(f"arranque_v{ARRANQUE_VERSION}_"):
                try:
                    viejo.unlink()
                except OSError:
                    pass
    except Exception:  # noqa: BLE001 - sin caché: se pinta
        ruta = None
    img = _pintar_arranque(fondo, texto, dpr)
    if ruta is not None:
        try:
            img.save(str(ruta), "PNG")
        except Exception:  # noqa: BLE001
            pass
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


# ✨ La onda de la ventana de arranque: un resplandor cálido que sale de DETRÁS del símbolo y un reflejo que pasa por
# su metal, de izquierda a derecha (el mismo brillo que el botón «Edita desde tu voz»). Mientras se monta la ventana
# principal el hilo de la interfaz está ocupado y no puede animar nada, así que la pinta un hilo propio directamente
# sobre la ventana de arranque (Windows deja dibujar en una ventana desde cualquier hilo) y solo en el recuadro del
# símbolo: ~1 ms por cuadro, no frena el arranque.
BRILLO_COLOR = (255, 222, 150)
BRILLO_CICLO = 2.6               # s que tarda la onda en cruzar el símbolo
BRILLO_PAUSA = 1.0               # s entre una onda y la siguiente (si el arranque tarda)
BRILLO_FPS = 40
BRILLO_VERSION = 1               # (súbelo si cambia el dibujo de las capas guardadas en la caché)


def _capas_brillo(dpr: float):
    """(recuadro, halo, reflejo): el recuadro del símbolo con margen para el resplandor (px físicos, en la imagen de
    arranque) y sus dos capas, ya recortadas a ese recuadro. None si no se pudo."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    W, H = round(ARRANQUE_TAM[0] * dpr), round(ARRANQUE_TAM[1] * dpr)
    mask = _mascara_logo(round(_LOGO_ALTO * dpr))
    if mask is None:
        return None
    mask = mask.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    m = int(16 * dpr)                                          # (igual que en _logo_en_relieve / _pintar_arranque)
    x = round((W - (mask.width() + 2 * m)) / 2) + m
    y = round(46 * dpr)
    g = int(22 * dpr)                                          # margen para el resplandor
    caja = QRect(x - g, y - g, mask.width() + 2 * g, mask.height() + 2 * g).intersected(QRect(0, 0, W, H))
    ox, oy = x - caja.x(), y - caja.y()

    def lienzo():
        im = QImage(caja.width(), caja.height(), QImage.Format_ARGB32_Premultiplied)
        im.fill(Qt.transparent)
        return im

    def forma(color):
        im = lienzo()
        p = QPainter(im)
        p.drawImage(ox, oy, mask)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(im.rect(), QColor(*color))
        p.end()
        return im

    def difuminar(im, r):                                      # reducir y volver a ampliar (tres pasos)
        for _ in range(3):
            ww, hh = max(1, int(im.width() / r)), max(1, int(im.height() / r))
            im = im.scaled(ww, hh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).scaled(
                im.width(), im.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            r = max(1.0, r * 0.6)
        return im

    halo = lienzo()
    p = QPainter(halo)
    lejos = difuminar(forma((*BRILLO_COLOR, 255)), 9.0 * dpr)
    cerca = difuminar(forma((*BRILLO_COLOR, 255)), 3.0 * dpr)
    p.drawImage(0, 0, lejos)
    p.drawImage(0, 0, lejos)
    p.setOpacity(0.85)
    p.drawImage(0, 0, cerca)
    p.setOpacity(1.0)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)     # sale de DETRÁS del símbolo
    p.drawImage(ox, oy, mask)
    p.end()
    reflejo = forma((255, 244, 214, 255))
    return caja, halo, reflejo


def _capas_brillo_guardadas(dpr: float):
    """_capas_brillo desde la caché (datos\\cache\\arranque); la primera vez se pintan y se guardan."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage
    try:
        from .core.paths import cache_dir
        d = cache_dir("arranque")
        base = f"brillo_v{BRILLO_VERSION}_{round(dpr * 100)}"
        rh, rr, rc = d / f"{base}_halo.png", d / f"{base}_reflejo.png", d / f"{base}_caja.txt"
        if rh.exists() and rr.exists() and rc.exists():
            h, r = QImage(str(rh)), QImage(str(rr))
            c = [int(v) for v in rc.read_text(encoding="utf-8").split()]
            if not h.isNull() and not r.isNull() and len(c) == 4:
                return (QRect(*c), h.convertToFormat(QImage.Format_ARGB32_Premultiplied),
                        r.convertToFormat(QImage.Format_ARGB32_Premultiplied))
    except Exception:  # noqa: BLE001
        d = None
    capas = _capas_brillo(dpr)
    if capas is not None and d is not None:
        try:
            caja, h, r = capas
            h.save(str(rh), "PNG")
            r.save(str(rr), "PNG")
            rc.write_text(f"{caja.x()} {caja.y()} {caja.width()} {caja.height()}", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return capas


def _imagen_a_np(img):
    """QImage ARGB32 premultiplicada → array (alto, ancho, 4) float32 en BGRA (como está en memoria)."""
    import numpy as np
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    a = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 4]
    return a.reshape(h, w, 4).astype(np.float32)


def _cuadros_brillo(fondo, halo, reflejo, n: int) -> list:
    """Los n cuadros de UNA onda (bytes BGRA del recuadro del símbolo, listos para la ventana), todos de una vez con
    numpy: así el hilo casi no compite con la interfaz mientras se monta (con un cuadro a cada momento, pintado con
    QPainter, salían ~6 por segundo). La onda cruza de izquierda a derecha, suave al entrar y al salir; el resplandor
    sale de detrás del símbolo y el reflejo suma luz a su metal."""
    import numpy as np
    f, ha, re = _imagen_a_np(fondo), _imagen_a_np(halo), _imagen_a_np(reflejo)
    h, w = f.shape[:2]
    xs = np.arange(w, dtype=np.float32)[None, :]
    i = np.arange(n, dtype=np.float32)[:, None]
    t = 0.5 - 0.5 * np.cos(np.pi * i / max(1, n - 1))               # (avance de la onda en cada cuadro)
    fuerza = np.sin(np.pi * t)

    def franja(banda, alfa):                                          # (n, ancho): 0 lejos … 1 en el centro de la onda
        cx = -banda + (w + 2 * banda) * t
        return np.clip(1.0 - np.abs(xs - cx) / banda, 0.0, 1.0) * fuerza * alfa

    fh, fr = franja(w * 0.42, 1.0), franja(w * 0.16, 0.32)
    salida = []
    for a in range(0, n, 26):                     # (de 26 en 26: pocas llamadas —poca espera al candado— y poca memoria)
        b = min(n, a + 26)
        src = ha[None] * fh[a:b, None, :, None]
        out = src + f[None] * (1.0 - src[..., 3:4] / 255.0)           # resplandor sobre el fondo
        out += re[None] * fr[a:b, None, :, None]                      # el reflejo suma luz
        np.clip(out, 0, 255, out=out)
        out[..., 3] = 255.0
        bloque = out.astype(np.uint8)
        salida.extend(bloque[k].tobytes() for k in range(b - a))
    return salida


def _cuadros_brillo_guardados(dpr: float, caja, fondo, halo, reflejo, n: int) -> list:
    """_cuadros_brillo desde la caché (un archivo por tema y escala de pantalla, unos MB): calcularlos mientras se
    monta la ventana principal tarda segundos (el hilo compite con la interfaz por Python) y la onda llegaría tarde;
    leerlos son unos ms. La primera vez se calculan aquí y se guardan para la siguiente."""
    import zlib
    from PySide6.QtGui import QImage
    f = fondo.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    tam = caja.width() * caja.height() * 4
    clave = zlib.crc32(bytes(f.constBits())[:tam])                 # (otro tema u otro dibujo = otro archivo)
    ruta = None
    try:
        from .core.paths import cache_dir
        d = cache_dir("arranque")
        ruta = d / f"brillo_v{BRILLO_VERSION}_{round(dpr * 100)}_{n}_{clave:08x}.bin"
        if ruta.exists() and ruta.stat().st_size == n * tam:
            datos = ruta.read_bytes()
            return [datos[i * tam:(i + 1) * tam] for i in range(n)]
        for viejo in d.glob(f"brillo_v*_{round(dpr * 100)}_*.bin"):    # (los de otro tema o dibujo, fuera)
            try:
                viejo.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        ruta = None
    cuadros = _cuadros_brillo(fondo, halo, reflejo, n)
    if ruta is not None:
        try:
            tmp = ruta.with_suffix(".tmp")
            tmp.write_bytes(b"".join(cuadros))
            tmp.replace(ruta)
        except Exception:  # noqa: BLE001
            pass
    return cuadros


class _PintorVentana:
    """Copia cuadros BGRA a una ventana con GDI (vale desde cualquier hilo). Preparado una vez: cada cuadro son tres
    llamadas a Windows, que sueltan el candado de Python mientras trabajan."""

    def __init__(self, hwnd: int, x: int, y: int, w: int, h: int):
        import ctypes
        from ctypes import wintypes

        class _BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        self.u32, self.g32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        self.u32.GetDC.restype = ctypes.c_void_p
        self.u32.GetDC.argtypes = [ctypes.c_void_p]
        self.u32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.g32.SetDIBitsToDevice.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                               ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                               ctypes.c_uint, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint]
        self.bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)    # (de arriba abajo, BGRA)
        self.ref = ctypes.byref(self.bih)
        self.hwnd = ctypes.c_void_p(hwnd)
        self.x, self.y, self.w, self.h = x, y, w, h

    def pintar(self, datos: bytes) -> bool:
        hdc = self.u32.GetDC(self.hwnd)
        if not hdc:
            return False
        try:
            return bool(self.g32.SetDIBitsToDevice(hdc, self.x, self.y, self.w, self.h, 0, 0, 0, self.h, datos,
                                                   self.ref, 0))
        finally:
            self.u32.ReleaseDC(self.hwnd, hdc)


def _animar_arranque(sp, pm, dpr: float) -> None:
    """Lanza el hilo de la onda (solo en Windows de verdad: nunca en las pruebas sin pantalla). Para con
    _cerrar_ventana_de_arranque. Cualquier fallo: la ventana de arranque se queda quieta, como antes."""
    import threading
    import time
    from PySide6.QtGui import QGuiApplication, QImage
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return
    try:
        hwnd = int(sp.winId())
        base = pm.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        base.setDevicePixelRatio(1.0)
    except Exception:  # noqa: BLE001
        return
    parar = threading.Event()
    cerrojo = threading.Lock()
    _instancia["arranque_brillo"] = (parar, cerrojo)

    def hilo():
        try:
            capas = _capas_brillo_guardadas(dpr)
            if capas is None or parar.is_set():
                return
            caja, halo, reflejo = capas
            fondo = base.copy(caja)
            n = max(2, round(BRILLO_CICLO * BRILLO_FPS))
            cuadros = _cuadros_brillo_guardados(dpr, caja, fondo, halo, reflejo, n)
            if not cuadros or parar.is_set():
                return
            quieto = bytes(fondo.constBits())[:caja.width() * caja.height() * 4]   # (el símbolo tal cual, para las pausas)
            pintor = _PintorVentana(hwnd, caja.x(), caja.y(), caja.width(), caja.height())
            paso = BRILLO_CICLO / n
            while not parar.is_set():
                t0 = time.perf_counter()
                for k, datos in enumerate(cuadros):                   # una onda, al ritmo del reloj
                    espera = t0 + k * paso - time.perf_counter()
                    if espera > 0 and parar.wait(espera):
                        return
                    with cerrojo:
                        if parar.is_set():
                            return
                        pintor.pintar(datos)
                with cerrojo:
                    if parar.is_set():
                        return
                    pintor.pintar(quieto)
                if parar.wait(BRILLO_PAUSA):
                    return
        except Exception:  # noqa: BLE001 - la onda nunca impide abrir
            pass

    threading.Thread(target=hilo, name="brillo_arranque", daemon=True).start()


def _ventana_de_arranque(app):
    """🌑 Ventana de arranque oscura (el símbolo en relieve, «Reclaimer» y «Abriendo…» con los colores del tema)
    mientras se monta la ventana principal: aparece en cuanto hay Qt, sin blanco. None si no se pudo (Reclaimer abre
    igual). (Un QWidget propio y no QSplashScreen: ese espera hasta 1 s a que la ventana «se vea» antes de volver.)"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication, QPainter, QPalette
        from PySide6.QtWidgets import QWidget
        pal = app.palette()
        fondo, texto = pal.color(QPalette.Window), pal.color(QPalette.WindowText)
        scr = QGuiApplication.primaryScreen()
        dpr = max(1.0, float(scr.devicePixelRatio())) if scr is not None else 1.0   # (125 %, 150 %… tal cual)
        pm = _imagen_de_arranque(fondo, texto, dpr)

        class _Arranque(QWidget):
            def paintEvent(self, _e):                                 # noqa: N802
                p = QPainter(self)
                p.setRenderHint(QPainter.SmoothPixmapTransform)       # (si acabara en otra pantalla, sin dientes)
                p.drawPixmap(self.rect(), pm)

        # (SIN «siempre encima»: un aviso que saliera mientras arranca —un error, una pregunta— quedaba tapado detrás y
        #  parecía colgado en «Abriendo…»)
        sp = _Arranque(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        sp.setObjectName("ventana_de_arranque")
        sp.setAttribute(Qt.WA_DeleteOnClose)
        sp.setAttribute(Qt.WA_OpaquePaintEvent)
        sp.setFixedSize(*ARRANQUE_TAM)
        sp.imagen = pm                                                # (para la captura de revisión)
        if scr is not None:
            g = sp.frameGeometry()
            g.moveCenter(scr.availableGeometry().center())
            sp.move(g.topLeft())
        _instancia["arranque"] = sp
        _mostrar_pintada(sp, app, seguro_ms=1500)
        try:
            _instancia["arranque_hwnd"] = int(sp.winId())      # (el vigía la esconde aunque la interfaz se cuelgue)
        except RuntimeError:
            pass
        _animar_arranque(sp, pm, dpr)                          # ✨ la onda (en su propio hilo)
        return sp
    except Exception:  # noqa: BLE001 - la ventana de arranque nunca impide abrir
        return None


def _cerrar_ventana_de_arranque(sp) -> None:
    _instancia.pop("arranque", None)
    _instancia.pop("arranque_hwnd", None)
    brillo = _instancia.pop("arranque_brillo", None)
    if brillo is not None:                                     # (la onda para ANTES de cerrar: nunca pinta en una
        parar, cerrojo = brillo                                #  ventana ya cerrada)
        parar.set()
        if cerrojo.acquire(timeout=0.2):
            cerrojo.release()
    if sp is None:
        return
    try:
        sp.close()
    except RuntimeError:
        pass


def _filtros_globales(app) -> list:
    """Los filtros de eventos de toda la aplicación (rueda y «❓ ¿Qué hace esto?»): se apartan mientras se monta la
    ventana. Qt manda cientos de miles de eventos al construir los paneles (cambios de estilo, hijos añadidos…) y
    todos pasaban por Python: la ventana tardaba el doble (5,7 → 2,9 s medido). Al montar no hay nada que atender."""
    from .ui import help as _help_ui
    _help_ui.install(app)                    # (lo instala ya, para que MainWindow no lo ponga a mitad)
    filtros = [f for f in (getattr(app, "_wheel_guard", None), getattr(app, "_help_filter", None)) if f is not None]
    for f in filtros:
        app.removeEventFilter(f)
    return filtros


def _tras_verse(win, argv) -> None:
    """Justo después del primer pintado: el proyecto de la pestaña (o el recuperado tras un cierre inesperado) y el
    que llegó al abrir un .eia. Con un aviso discreto en la barra de estado mientras se abre."""
    try:
        barra = win.statusBar()
        barra.showMessage("📂 Abriendo el proyecto…")
        barra.repaint()                        # (se ve ya: la carga ocupa el hilo de la interfaz)
    except RuntimeError:
        return                                 # (la ventana ya se cerró)
    try:
        win.try_recover()
        if len(argv) > 1 and argv[1].lower().endswith(".eia"):
            win.open_project(argv[1])
    finally:
        try:
            if barra.currentMessage() == "📂 Abriendo el proyecto…":
                barra.clearMessage()
        except RuntimeError:
            pass
    _instancia["win"] = win
    _atender_pendientes()                 # (si otra se abrió mientras esta arrancaba)


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
    # ⚡ (23/11) Arranque: 1) la ventana de arranque oscura, enseguida; 2) la ventana principal se monta sin los
    # filtros de toda la aplicación; 3) se enseña YA pintada (encubierta hasta su primer pintado: sin pantallazo
    # blanco); 4) el proyecto se abre justo después, con la ventana ya a la vista (antes se abría entre show() y el
    # bucle de eventos: la ventana se quedaba en blanco mientras tanto).
    vigia = _vigia_arranque()             # 🛟 si se colgara antes de verse: rastro en arranque.log y nada encubierto
    arranque = _ventana_de_arranque(app)
    from .ui.main_window import MainWindow
    filtros = _filtros_globales(app)
    try:
        win = MainWindow()
    finally:
        for f in filtros:
            app.installEventFilter(f)
    try:                                  # (la pestaña donde estabas, ya elegida: sus paneles desde el primer pintado)
        win.preview.set_guides_space(win.workspaces.elegir_al_abrir())
        win._al_cambiar_pestaña(win.workspaces.current)
    except Exception:  # noqa: BLE001 - try_recover lo vuelve a hacer
        pass
    _mostrar_pintada(win, app)
    _cerrar_ventana_de_arranque(arranque)
    vigia.set()
    marca_arranque("ventana visible")
    _instalar_congelado_memoria(win)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, win, lambda: _tras_verse(win, argv))
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
