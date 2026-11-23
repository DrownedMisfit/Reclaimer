"""
🖼 Miniaturas de las rejillas: los fotogramas del video DENTRO de su propia casilla («hover scrub», como en Premiere o
en Resolve). Al mover el ratón de izquierda a derecha sobre la miniatura de un video, la casilla enseña el fotograma de
ese punto del video, con una línea fina abajo que marca por dónde va; al salir, vuelve la miniatura de siempre. Las
imágenes no cambian. Sin sonido y sin ventanas flotantes (23/11, a petición del usuario: antes salían una vista grande
flotante y su animación; ahora todo se ve en la misma casilla).

  activar_scrub(vista, dato, etiqueta=None)   vista = QListWidget o QTreeWidget; dato(item) -> ruta del archivo o None
                                              etiqueta(item) -> QLabel con la miniatura (casillas hechas con un widget)
  ajustar_rejilla(lista, ancho, alto)         rejilla donde ningún nombre se corta

Rendimiento (hay rejillas de cientos de archivos):
  · Una tira por video (N_FOTOGRAMAS a la resolución de la casilla) en datos\\cache\\tira_scrub, con clave por archivo
    y fecha (core/media.cache_key): la segunda vez es instantáneo. En memoria, las últimas EN_MEMORIA tiras.
  · Se saca SOLO para la casilla bajo el ratón, tras un momento quieto encima (pasar de largo no pide nada), en un
    hilo propio de prioridad mínima y de una en una (FFmpeg con prioridad baja y un hilo por entrada).
  · Mientras no está, la casilla enseña su miniatura normal: nada espera.
  · Mover el ratón solo cambia el icono de esa casilla (sin avisar al modelo: no se recoloca la lista).
  · Apagado mientras reproduces o exportas (ui/cola_analisis.pausa_automatica): no roba CPU.
"""
from __future__ import annotations

import os
import subprocess
from collections import OrderedDict

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap

N_FOTOGRAMAS = 12
ESPERA_MS = 150              # (quieto encima de una casilla este rato: se pide su tira)
EN_MEMORIA = 48              # (tiras que se guardan cargadas)
MAX_PENDIENTES = 2           # (en cola, las últimas casillas que miraste; lo demás se olvida)
ANCHO_MAX = 480              # (cada fotograma de la tira, como mucho)


# ------------------------------------------------------------------ la tira en disco
_CARPETA: list[str] = []


def _carpeta() -> str:
    if not _CARPETA or not os.path.isdir(_CARPETA[0]):
        from ..core.paths import cache_dir
        _CARPETA[:] = [str(cache_dir("tira_scrub"))]
    return _CARPETA[0]


def ruta_tira(ruta: str, ancho: int) -> str:
    from ..core import media as MEDIA
    return os.path.join(_carpeta(), f"{MEDIA.cache_key(ruta)}_{int(ancho)}.jpg")


_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def _correr(args: list[str], cancelado=None, timeout: float = 60.0, salida: bool = False):
    """FFmpeg con prioridad baja; se mata si se cancela o tarda demasiado. Devuelve (ok, bytes de la salida)."""
    import time
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE if salida else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=_SIN_VENTANA)
    except OSError:
        return False, b""
    fin = time.monotonic() + timeout
    while True:
        try:
            datos, _ = proc.communicate(timeout=0.25)
            return proc.returncode == 0, datos or b""
        except subprocess.TimeoutExpired:
            if (cancelado is not None and cancelado()) or time.monotonic() > fin:
                proc.kill()
                proc.communicate()
                return False, b""


def hacer_tira(ruta: str, ancho: int, cancelado=None) -> str | None:
    """La tira de N_FOTOGRAMAS repartidos por el video, uno al lado del otro (cada uno de «ancho» px). Una sola
    llamada a FFmpeg que salta a cada punto (rápido también en videos largos); si falla, uno a uno."""
    out = ruta_tira(ruta, ancho)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    from ..core import media as MEDIA
    try:
        dur = float(MEDIA.probe(ruta).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        dur = 0.0
    if dur <= 0:
        return None
    ts = [dur * (k + 0.5) / N_FOTOGRAMAS for k in range(N_FOTOGRAMAS)]
    tmp = out + ".tmp.jpg"
    args = [MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y"]
    for t in ts:
        args += ["-threads", "1", "-ss", f"{t:.3f}", "-i", ruta]
    fc = ";".join(f"[{k}:v:0]scale={ancho}:-2:flags=fast_bilinear,setsar=1[v{k}]" for k in range(N_FOTOGRAMAS))
    fc += ";" + "".join(f"[v{k}]" for k in range(N_FOTOGRAMAS)) + f"hstack=inputs={N_FOTOGRAMAS}[s]"
    args += ["-filter_complex", fc, "-map", "[s]", "-an", "-frames:v", "1", "-q:v", "5", "-threads", "1", tmp]
    ok, _ = _correr(args, cancelado)
    if ok and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, out)
        return out
    if os.path.isfile(tmp):
        os.remove(tmp)
    if cancelado is not None and cancelado():
        return None
    # (respaldo: uno a uno; el que no sale repite el anterior)
    from PySide6.QtGui import QImage
    cuadros: list = []
    for t in ts:
        if cancelado is not None and cancelado():
            return None
        ok, datos = _correr([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-threads", "1", "-ss", f"{t:.3f}", "-i", ruta,
                             "-frames:v", "1", "-vf", f"scale={ancho}:-2:flags=fast_bilinear", "-f", "image2pipe",
                             "-c:v", "mjpeg", "-q:v", "5", "pipe:1"], cancelado, 30.0, salida=True)
        img = QImage.fromData(datos) if ok and datos else QImage()
        cuadros.append(img if not img.isNull() else (cuadros[-1] if cuadros else img))
    validos = [c for c in cuadros if not c.isNull()]
    if not validos:
        return None
    alto = validos[0].height()
    tira = QImage(ancho * N_FOTOGRAMAS, alto, QImage.Format_RGB32)
    tira.fill(QColor("black"))
    p = QPainter(tira)
    for k, c in enumerate(cuadros):
        if not c.isNull():
            p.drawImage(QRect(k * ancho, 0, ancho, alto), c)
    p.end()
    if not tira.save(tmp, "JPG", 80):
        return None
    os.replace(tmp, out)
    return out


# ------------------------------------------------------------------ quién saca las tiras (de una en una)
def _pausa() -> bool:
    """▶ reproduciendo o exportando: nada de scrub (ni de sacar tiras)."""
    try:
        from .cola_analisis import pausa_automatica
        return pausa_automatica()
    except Exception:  # noqa: BLE001
        return False


class _Generador(QObject):
    lista = Signal(str, int, str)          # (ruta del video, ancho, ruta de la tira)

    def __init__(self):
        super().__init__()
        self._pend: list[tuple[str, int]] = []
        self._job = None
        self._en_marcha = None
        self._fallidos: set = set()

    def pedir(self, ruta: str, ancho: int):
        k = (ruta, int(ancho))
        if k == self._en_marcha or k in self._fallidos:
            return
        if k in self._pend:
            self._pend.remove(k)
        self._pend.insert(0, k)            # (lo último que miraste, primero)
        del self._pend[MAX_PENDIENTES:]
        self._siguiente()

    def _siguiente(self):
        if self._job is not None or not self._pend or _pausa():
            return
        from .jobs import BackgroundJob
        k = self._pend.pop(0)
        job = BackgroundJob(lambda _p, c, r=k[0], a=k[1]: hacer_tira(r, a, c))
        job.silencioso = True              # (no sale en «Tareas»: es cosa de la interfaz)
        job.title = "🖼 Fotogramas de la miniatura"
        job.done.connect(lambda res, k=k: self._fin(k, res))
        job.failed.connect(lambda _m, k=k: self._fin(k, None))
        self._job, self._en_marcha = job, k
        job.start()
        try:
            job.setPriority(QThread.LowestPriority)
        except RuntimeError:
            pass

    def _fin(self, k, res):
        self._job, self._en_marcha = None, None
        if res:
            self.lista.emit(k[0], k[1], res)
        else:
            self._fallidos.add(k)
        QTimer.singleShot(0, self._siguiente)


_GEN: list[_Generador] = []


def generador() -> _Generador:
    if not _GEN:
        _GEN.append(_Generador())
    return _GEN[0]


_MEM: OrderedDict[str, QPixmap] = OrderedDict()


def _tira_cargada(f: str) -> QPixmap | None:
    pm = _MEM.get(f)
    if pm is not None:
        _MEM.move_to_end(f)
        return pm
    if not os.path.isfile(f):
        return None
    pm = QPixmap(f)
    if pm.isNull():
        return None
    _MEM[f] = pm
    while len(_MEM) > EN_MEMORIA:
        _MEM.popitem(last=False)
    return pm


# ------------------------------------------------------------------ el scrub en la casilla
class _Scrub(QObject):
    """Mira el ratón sobre la vista; en la casilla de un video cambia su icono (o el QLabel de su widget) por el
    fotograma de ese punto y lo devuelve al salir. No toca el modelo de forma visible: sin avisos, sin recolocar."""

    def __init__(self, vista, dato, etiqueta=None):
        super().__init__(vista)
        self.vista, self.dato, self.etiqueta = vista, dato, etiqueta
        self.item = None
        self.ruta = None
        self.tira: QPixmap | None = None
        self._f = ""
        self._orig = None                  # (QIcon o QPixmap de antes)
        self._puesto = None                # (cacheKey de lo que puso el scrub)
        self._ultimo = None                # ((fotograma, píxel de la línea): nada que repintar si no cambia)
        self._zona_cache = None            # ((rect de la casilla, zona de su miniatura) en listas y árboles)
        self.medidas: list[float] = []     # (para las pruebas: segundos de cada movimiento, si se activa)
        self._medir = False
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(ESPERA_MS)
        self._t.timeout.connect(self._pedir)
        vp = vista.viewport()
        vp.setMouseTracking(True)
        vp.installEventFilter(self)
        m = vista.model()
        m.modelAboutToBeReset.connect(self._olvidar)
        for sen in (m.rowsAboutToBeRemoved, m.rowsAboutToBeMoved, m.layoutAboutToBeChanged):
            sen.connect(self._soltar)
        generador().lista.connect(self._llego)

    # ---- eventos
    def eventFilter(self, _obj, ev):       # noqa: N802
        t = ev.type()
        if t == QEvent.MouseMove:
            if ev.buttons() != Qt.NoButton:
                self._soltar()
            elif self._medir:
                import time
                t0 = time.perf_counter()
                self._mover(ev.position().toPoint())
                self.medidas.append(time.perf_counter() - t0)
            else:
                self._mover(ev.position().toPoint())
        elif t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel, QEvent.Hide,
                   QEvent.DragEnter):
            self._soltar()
        return False

    def _mover(self, pos: QPoint):
        if _pausa():
            self._soltar()
            return
        it = self.vista.itemAt(pos)
        if it is not self.item:
            self._soltar()
            if it is None:
                return
            self.item, self.ruta = it, self._ruta_de(it)
            if self.ruta:
                self._f = ruta_tira(self.ruta, self._ancho())
                self.tira = _tira_cargada(self._f)
                if self.tira is None:
                    self._t.start()
        if self.ruta and self.tira is not None:
            self._ensenar(pos)

    def _ruta_de(self, it) -> str | None:
        try:
            r = self.dato(it)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(r, str) or not r:
            return None
        from ..core.model import KIND_VIDEO, kind_for_path
        return r if kind_for_path(r) == KIND_VIDEO and os.path.isfile(r) else None

    def _ancho(self) -> int:
        w = self.vista.iconSize().width()
        if self.etiqueta is not None and self.item is not None:
            lbl = self._etiqueta(self.item)
            if lbl is not None:
                w = lbl.width()
        dpr = self.vista.viewport().devicePixelRatioF() or 1.0
        return max(32, min(ANCHO_MAX, int(round(w * dpr / 2.0)) * 2))

    def _pedir(self):
        if self.ruta and self.tira is None and self.item is not None and not _pausa():
            generador().pedir(self.ruta, self._ancho())

    def _llego(self, ruta: str, _ancho: int, f: str):
        if ruta != self.ruta or self.tira is not None or f != self._f:
            return
        self.tira = _tira_cargada(f)
        if self.tira is None:
            return
        vp = self.vista.viewport()
        pos = vp.mapFromGlobal(QCursor.pos())
        if vp.rect().contains(pos) and self.vista.itemAt(pos) is self.item:
            self._ensenar(pos)

    # ---- pintar
    def _etiqueta(self, it):
        try:
            return self.etiqueta(it) if self.etiqueta is not None else None
        except Exception:  # noqa: BLE001 - (RuntimeError: la casilla ya no existe)
            return None

    def _icono(self, it):
        from PySide6.QtWidgets import QTreeWidgetItem
        return it.icon(0) if isinstance(it, QTreeWidgetItem) else it.icon()

    def _poner_icono(self, it, ic: QIcon):
        from PySide6.QtWidgets import QTreeWidgetItem
        m = self.vista.model()
        antes = m.blockSignals(True)       # (sin dataChanged: ni itemChanged ni recolocar la lista)
        try:
            if isinstance(it, QTreeWidgetItem):
                it.setIcon(0, ic)
            else:
                it.setIcon(ic)
        finally:
            m.blockSignals(antes)
        self.vista.viewport().update(self.vista.visualItemRect(it))

    def _zona(self, r: QRect) -> QRect:
        """Dónde está la miniatura: en una rejilla, toda la casilla; en una lista o un árbol, el icono de la izquierda."""
        from PySide6.QtWidgets import QListView
        if self.etiqueta is not None:
            lbl = self._etiqueta(self.item)
            if lbl is not None:
                return QRect(lbl.mapTo(self.vista.viewport(), QPoint(0, 0)), lbl.size())
        if isinstance(self.vista, QListView) and self.vista.viewMode() == QListView.IconMode:
            return r
        if self._zona_cache is not None and self._zona_cache[0] == r:
            return self._zona_cache[1]
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QTreeWidgetItem
        it = self.item
        es_arbol = isinstance(it, QTreeWidgetItem)
        opt = QStyleOptionViewItem()
        opt.initFrom(self.vista)
        opt.rect = r
        opt.font = self.vista.font()
        opt.decorationSize = self.vista.iconSize()
        opt.decorationPosition = QStyleOptionViewItem.Left
        opt.decorationAlignment = Qt.AlignCenter
        opt.displayAlignment = Qt.AlignLeft | Qt.AlignVCenter
        opt.features = QStyleOptionViewItem.HasDecoration | QStyleOptionViewItem.HasDisplay
        if it.flags() & Qt.ItemIsUserCheckable:   # (con casilla de marcar, el icono va después)
            opt.features |= QStyleOptionViewItem.HasCheckIndicator
        opt.icon = it.icon(0) if es_arbol else it.icon()
        opt.text = it.text(0) if es_arbol else it.text()
        z = self.vista.style().subElementRect(QStyle.SE_ItemViewItemDecoration, opt, self.vista)
        if not z.isValid() or z.width() < 4:
            z = QRect(r.left(), r.top(), self.vista.iconSize().width() + 12, r.height())
        z = QRect(z.left() - 2, r.top(), z.width() + 4, r.height())
        self._zona_cache = (QRect(r), z)
        return z

    def _ensenar(self, pos: QPoint):
        it = self.item
        try:
            zona = self._zona(self.vista.visualItemRect(it))
            lbl = self._etiqueta(it) if self.etiqueta is not None else None
            actual = (lbl.pixmap() if lbl is not None else self._icono(it))
        except RuntimeError:
            self._olvidar()
            return
        if zona.width() <= 0 or (self.etiqueta is not None and lbl is None):
            return
        frac = (pos.x() - zona.left()) / zona.width()
        if not 0.0 <= frac <= 1.0:
            self._restaurar()                  # (en una lista: el ratón está sobre el nombre, no sobre la miniatura)
            return
        if self._puesto is None or actual.cacheKey() != self._puesto:
            self._orig = actual                # (la miniatura de siempre; también si llegó una nueva mientras tanto)
            self._ultimo = None
        if self._orig is None or self._orig.isNull():
            return                             # (aún sin miniatura: nada que cambiar)
        sz = (self._orig.deviceIndependentSize().toSize() if lbl is not None
              else self._orig.actualSize(self.vista.iconSize()))
        if sz.isEmpty():
            return
        idx = min(N_FOTOGRAMAS - 1, int(frac * N_FOTOGRAMAS))
        dpr = self.vista.viewport().devicePixelRatioF() or 1.0
        w, h = int(round(sz.width() * dpr)), int(round(sz.height() * dpr))
        linea = int(round(frac * w))
        if self._ultimo == (idx, linea):
            return
        self._ultimo = (idx, linea)
        pm = QPixmap(w, h)
        pm.fill(QColor("black"))
        tw = self.tira.width() / N_FOTOGRAMAS
        th = self.tira.height()
        k = min(w / tw, h / th) if tw > 0 and th > 0 else 1.0
        dw, dh = tw * k, th * k
        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF((w - dw) / 2, (h - dh) / 2, dw, dh), self.tira, QRectF(idx * tw, 0, tw, th))
        grueso = max(2, int(round(2 * dpr)))   # (la línea fina de abajo: por dónde va)
        p.fillRect(QRectF(0, h - grueso, w, grueso), QColor(0, 0, 0, 150))
        p.fillRect(QRectF(0, h - grueso, linea, grueso), QColor(255, 255, 255, 235))
        p.end()
        pm.setDevicePixelRatio(dpr)
        if lbl is not None:
            lbl.setPixmap(pm)
            self._puesto = lbl.pixmap().cacheKey()
        else:
            ic = QIcon(pm)
            self._poner_icono(it, ic)
            self._puesto = self._icono(it).cacheKey()

    def _restaurar(self):
        it, orig, puesto = self.item, self._orig, self._puesto
        self._orig = self._puesto = self._ultimo = None
        if it is None or orig is None or puesto is None:
            return
        try:
            if self.etiqueta is not None:
                lbl = self._etiqueta(it)
                if lbl is not None and lbl.pixmap().cacheKey() == puesto:
                    lbl.setPixmap(orig)
            elif self._icono(it).cacheKey() == puesto:      # (si otro puso una miniatura nueva, se queda la suya)
                self._poner_icono(it, orig)
        except RuntimeError:
            pass

    def _soltar(self, *_a):
        """El ratón se fue de la casilla (o la lista cambia): vuelve la miniatura normal."""
        self._t.stop()
        self._restaurar()
        self.item, self.ruta, self.tira, self._f, self._zona_cache = None, None, None, "", None

    def _olvidar(self, *_a):
        """La lista se vacía (sus casillas desaparecen): nada que devolver."""
        self._t.stop()
        self.item, self.ruta, self.tira, self._f, self._zona_cache = None, None, None, "", None
        self._orig = self._puesto = self._ultimo = None


def activar_scrub(vista, dato, etiqueta=None) -> _Scrub:
    """dato(item) -> ruta del archivo (o None); etiqueta(item) -> QLabel de la miniatura si la casilla es un widget."""
    s = _Scrub(vista, dato, etiqueta)
    vista._scrub = s
    return s


def ajustar_rejilla(lista, ancho_celda: int, alto_icono: int) -> None:
    """Rejilla de miniaturas (QListWidget en modo icono) donde ningún nombre se corta: cada celda tiene el alto que
    pide el nombre más largo, entero y en varias líneas (Qt parte por palabras o, si no cabe, por letras)."""
    fm = lista.fontMetrics()
    libre = max(20, ancho_celda - 8)
    alto_txt = fm.height()
    for i in range(lista.count()):
        r = fm.boundingRect(QRect(0, 0, libre, 100000), Qt.TextWordWrap | Qt.TextWrapAnywhere, lista.item(i).text())
        alto_txt = max(alto_txt, r.height())
    lista.setGridSize(QSize(ancho_celda, alto_icono + 14 + alto_txt + 4))
