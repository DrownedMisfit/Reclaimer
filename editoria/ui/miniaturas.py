"""
🖼 Miniaturas que se ven: al pasar el ratón por una miniatura de una rejilla, una vista GRANDE flotante (sin robar el
foco y sin salirse de la pantalla); si es un video, va pasando fotogramas suyos en bucle (sin sonido) para ver qué es.

  activar_vista_grande(lista, dato)   lista = QListWidget; dato(item) -> ruta de un archivo, o QPixmap, o None
  tira_de(ruta, n)                     los n fotogramas (caché en datos\\cache\\tira_hover; en segundo plano)

Lo usan 🌐 Descargas, 🔑 Palabras clave (Resultados y Descargas), 😂 Memes y «Todo lo descargado».
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

ANCHO = 420                  # (vista grande: 360–480 px)
N_FOTOGRAMAS = 8
RETARDO_MS = 350             # (pasar por encima sin querer no la abre)
PASO_MS = 450                # (cada fotograma de la tira)


def _carpeta_tira(ruta: str) -> str:
    from ..core import media as MEDIA
    from ..core.paths import cache_dir
    return os.path.join(str(cache_dir("tira_hover")), MEDIA.cache_key(ruta))


def tira_guardada(ruta: str, n: int = N_FOTOGRAMAS) -> list[str]:
    d = _carpeta_tira(ruta)
    fs = [os.path.join(d, f"{k:02d}.jpg") for k in range(n)]
    return fs if all(os.path.isfile(f) and os.path.getsize(f) > 0 for f in fs) else []


def tira_de(ruta: str, n: int = N_FOTOGRAMAS, cancelado=None) -> list[str]:
    """Los n fotogramas repartidos por el video (FFmpeg salta a cada punto: rápido también en videos largos)."""
    hechos = tira_guardada(ruta, n)
    if hechos:
        return hechos
    from ..core import media as MEDIA
    try:
        dur = float(MEDIA.probe(ruta).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        dur = 0.0
    if dur <= 0:
        return []
    d = _carpeta_tira(ruta)
    os.makedirs(d, exist_ok=True)
    out = []
    for k in range(n):
        if cancelado is not None and cancelado():
            return []
        t = dur * (k + 0.5) / n
        f = os.path.join(d, f"{k:02d}.jpg")
        if not os.path.isfile(f):
            MEDIA.run_quiet([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", ruta,
                             "-frames:v", "1", "-vf", f"scale={ANCHO}:-2", "-q:v", "4", f], timeout=30)
        if os.path.isfile(f) and os.path.getsize(f) > 0:
            out.append(f)
    return out


class VistaGrande(QLabel):
    """La ventanita flotante (tipo ayuda emergente: no roba el foco)."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("QLabel { background: #111316; border: 1px solid #3a3d44; }")
        self.setAlignment(Qt.AlignCenter)
        self.cuadros: list[QPixmap] = []
        self.i = 0
        self.ruta = None
        self._t = QTimer(self)
        self._t.setInterval(PASO_MS)
        self._t.timeout.connect(self._siguiente)
        self._job = None

    def mostrar(self, dato, cerca: QPoint):
        self._t.stop()
        self.cuadros, self.i, self.ruta = [], 0, None
        if isinstance(dato, QPixmap):
            pm = dato
        elif isinstance(dato, str) and os.path.isfile(dato):
            self.ruta = dato
            pm = self._primera(dato)
            self._pedir_tira(dato)
        else:
            return
        if pm is None or pm.isNull():
            pm = QPixmap(ANCHO, int(ANCHO * 9 / 16))
            pm.fill(QColor("#111316"))
        self._poner(pm)
        self._colocar(cerca)
        self.show()
        self.raise_()

    def _primera(self, ruta: str) -> QPixmap | None:
        from ..core.model import KIND_IMAGE, kind_for_path
        if kind_for_path(ruta) == KIND_IMAGE:
            return QPixmap(ruta)
        tira = tira_guardada(ruta)
        if tira:
            self.cuadros = [QPixmap(f) for f in tira]
            if len(self.cuadros) > 1:
                self._t.start()
            return self.cuadros[0]
        from .clips_panel import _miniatura_ruta
        png = _miniatura_ruta(ruta)
        return QPixmap(png) if os.path.isfile(png) else None

    def _pedir_tira(self, ruta: str):
        from ..core.model import KIND_VIDEO, kind_for_path
        if self.cuadros or kind_for_path(ruta) != KIND_VIDEO:
            return
        from .jobs import BackgroundJob
        if self._job is not None:
            self._job.cancel()
        job = BackgroundJob(lambda _p, c, r=ruta: (r, tira_de(r, cancelado=c)), self)
        job.done.connect(self._llego_tira)
        self._job = job
        job.start()

    def _llego_tira(self, res):
        ruta, fs = res if isinstance(res, tuple) else (None, [])
        if ruta != self.ruta or not fs or not self.isVisible():
            return
        self.cuadros = [QPixmap(f) for f in fs]
        self.i = 0
        self._poner(self.cuadros[0])
        self._t.start()

    def _siguiente(self):
        if not self.cuadros or not self.isVisible():
            self._t.stop()
            return
        self.i = (self.i + 1) % len(self.cuadros)
        self._poner(self.cuadros[self.i])

    def _poner(self, pm: QPixmap):
        pm = pm.scaled(QSize(ANCHO, int(ANCHO * 9 / 16 * 1.6)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self.cuadros and len(self.cuadros) > 1:          # (una barrita: qué parte del video se ve)
            pm = QPixmap(pm)
            p = QPainter(pm)
            ancho = pm.width() / len(self.cuadros)
            p.fillRect(QRect(int(self.i * ancho), pm.height() - 4, max(2, int(ancho)), 4), QColor(255, 255, 255, 190))
            p.end()
        self.setPixmap(pm)
        self.resize(pm.width() + 2, pm.height() + 2)

    def _colocar(self, cerca: QPoint):
        pantalla = QApplication.screenAt(cerca) or QApplication.primaryScreen()
        g = pantalla.availableGeometry() if pantalla is not None else QRect(0, 0, 1920, 1080)
        x, y = cerca.x() + 18, cerca.y() + 18
        if x + self.width() > g.right():
            x = cerca.x() - self.width() - 18
        if y + self.height() > g.bottom():
            y = g.bottom() - self.height()
        self.move(max(g.left(), x), max(g.top(), y))

    def esconder(self):
        self._t.stop()
        self.hide()

    # ⌨ (22/11) «se esconde al teclear» con CUALQUIER tecla y esté donde esté el foco: una tecla que es un atajo de la
    #   ventana (→ «Fotograma siguiente», Espacio…) se la quedaba el atajo y nunca llegaba a la lista (el vigía no la
    #   veía y la vista grande seguía encima). Mientras se ve, un filtro de toda la aplicación mira el teclado.
    def showEvent(self, e):                       # noqa: N802
        super().showEvent(e)
        app = QApplication.instance()
        if app is not None and not getattr(self, "_mirando_teclas", False):
            self._mirando_teclas = True
            app.installEventFilter(self)

    def hideEvent(self, e):                       # noqa: N802
        super().hideEvent(e)
        app = QApplication.instance()
        if app is not None and getattr(self, "_mirando_teclas", False):
            self._mirando_teclas = False
            app.removeEventFilter(self)

    def eventFilter(self, _obj, ev):              # noqa: N802
        if ev.type() in (QEvent.KeyPress, QEvent.ShortcutOverride) and self.isVisible():
            self.esconder()
        return False


_VISTA: VistaGrande | None = None


def vista() -> VistaGrande:
    global _VISTA
    if _VISTA is None:
        _VISTA = VistaGrande()
    return _VISTA


def ajustar_rejilla(lista, ancho_celda: int, alto_icono: int) -> None:
    """Rejilla de miniaturas (QListWidget en modo icono) donde ningún nombre se corta: cada celda tiene el alto que
    pide el nombre más largo, entero y en varias líneas (Qt parte por palabras o, si no cabe, por letras)."""
    from PySide6.QtCore import QRect
    fm = lista.fontMetrics()
    libre = max(20, ancho_celda - 8)
    alto_txt = fm.height()
    for i in range(lista.count()):
        r = fm.boundingRect(QRect(0, 0, libre, 100000), Qt.TextWordWrap | Qt.TextWrapAnywhere, lista.item(i).text())
        alto_txt = max(alto_txt, r.height())
    lista.setGridSize(QSize(ancho_celda, alto_icono + 14 + alto_txt + 4))


_ESTADO_APP = [False]


def esconder_vista_grande() -> None:
    """Esconde la vista grande si está a la vista (p. ej. porque la lista se va a rehacer)."""
    global _VISTA
    if _VISTA is not None:
        try:
            _VISTA.esconder()
        except RuntimeError:
            _VISTA = None


def _vigilar_aplicacion() -> None:
    """Si el editor deja de ser la aplicación activa (Alt+Tab, otra ventana encima…), la vista grande se va."""
    if _ESTADO_APP[0]:
        return
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return
    _ESTADO_APP[0] = True
    app.applicationStateChanged.connect(lambda st: st != Qt.ApplicationActive and esconder_vista_grande())


class _Vigia(QObject):
    """Mira el ratón sobre la rejilla: tras un momento quieto encima de una miniatura, la vista grande. Se esconde al
    salir, hacer clic, rodar, teclear, al cambiar de ventana o de aplicación y cuando la lista se rehace."""

    def __init__(self, lista, dato):
        super().__init__(lista)
        self.lista, self.dato = lista, dato
        self.item = None
        self._pos = None
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(RETARDO_MS)
        self._t.timeout.connect(self._abrir)
        lista.viewport().setMouseTracking(True)
        lista.viewport().installEventFilter(self)
        lista.installEventFilter(self)
        modelo = lista.model()
        for sen in (modelo.rowsRemoved, modelo.modelReset, modelo.layoutChanged):
            sen.connect(self._olvidar)
        self._ventana = None
        _vigilar_aplicacion()

    def _olvidar(self, *_a):
        self.item = None
        self._t.stop()
        esconder_vista_grande()

    def _mirar_ventana(self):
        """La ventana de la lista (también avisa si se desactiva: un diálogo encima, otra ventana…)."""
        w = self.lista.window()
        if w is not self._ventana:
            if self._ventana is not None:
                try:
                    self._ventana.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._ventana = w
            w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self._ventana:
            if t in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.WindowStateChange):
                self._olvidar()
            return False
        if obj is self.lista:
            if t in (QEvent.KeyPress, QEvent.Hide, QEvent.FocusOut):
                self._olvidar()
            return False
        if t == QEvent.MouseMove:
            self._mirar_ventana()
            self._pos = ev.position().toPoint()
            it = self.lista.itemAt(self._pos)
            if it is not self.item:
                self.item = it
                esconder_vista_grande()
                if it is not None:
                    self._t.start()
                else:
                    self._t.stop()
        elif t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel, QEvent.Hide, QEvent.KeyPress):
            self._olvidar()
        return False

    def _abrir(self):
        it = self.item
        if it is None or self._pos is None:
            return
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        if QGuiApplication.applicationState() != Qt.ApplicationActive and not getattr(self.lista, "_vista_sin_foco",
                                                                                    False):
            return                                   # (el editor no es la aplicación activa)
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self.lista.window():
            return                                   # (un diálogo encima)
        if not self.lista.isVisible():
            return
        vp = self.lista.viewport()
        pos = vp.mapFromGlobal(QCursor.pos())
        if not vp.rect().contains(pos) or self.lista.itemAt(pos) is not it:
            return                                   # (el ratón ya no está sobre esa miniatura)
        try:
            dato = self.dato(it)
        except Exception:  # noqa: BLE001
            dato = None
        if dato is not None:
            vista().mostrar(dato, QCursor.pos())


def activar_vista_grande(lista, dato) -> _Vigia:
    """dato(item) -> ruta de un archivo, QPixmap o None."""
    v = _Vigia(lista, dato)
    lista._vigia_vista = v
    return v
