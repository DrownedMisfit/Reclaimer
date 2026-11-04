"""
✂ Elegir los tramos de un video para el edit musical: lo reproduces y con UN botón marcas la entrada y la salida
(«[ Entrada» → «Salida ]», o la tecla I): al marcar la salida, el tramo se añade solo. La IA solo sacará planos de esos
tramos (sin tramos = todo el video).
· La barra enseña los tramos elegidos (naranja), la entrada marcada (raya amarilla) y el cabezal; clic = ir ahí.
· Lo ya elegido no se duplica: si marcas encima de un tramo que ya tienes, solo se añade la parte nueva.
· Espacio = reproducir / pausa · ← → = 1 s · Mayús+← → = 10 s.
· 🔍 Acercar / alejar la barra: Ctrl+rueda (o «🔍−» «🔍+», junto a −1 s / +1 s); a los lados de la barra, entre qué
  tiempos estás viendo. Acercada, la rueda sola se mueve por el video y la vista sigue al cabezal.
· ⬛ Rayitas amarillas DEBAJO de la barra = donde la imagen se queda completamente negra (se busca sola al abrir,
  después de las escenas, y se guarda). Lo que ARRASTRAS no incluye esas partes en negro (queda en trozos).
El reproductor es propio (FFmpeg): el de Qt, con el visor principal abierto, se quedaba en negro y colgaba al cerrar.
Si el video tiene copia ligera, se usa (va más fluido).
"""
from __future__ import annotations

import collections
import math
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core import media as media_tools
from .common import fmt_time

FPS = 25
VW = 640                       # anchura a la que se decodifica (rápido y suficiente para elegir)
MIN_SPAN = 3.0                 # 🔍 lo más que se acerca la barra: 3 s de lado a lado
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def play_source(m) -> str:
    """La copia ligera si ya existe (un cuarto o media): mismo tiempo, mucho más rápida de leer."""
    from ..core import proxies
    for lv in ("quarter", "half"):
        if proxies.has_proxy(m.path, lv):
            return proxies.proxy_path(m.path, lv)
    return m.path


# ------------------------------------------------------------------ reproductor propio (FFmpeg)
class _Video(QThread):
    """Decodifica desde t0 y entrega los fotogramas a su hora (tiempo real)."""
    frame = Signal(QImage, float)

    def __init__(self, path: str, t0: float, w: int, h: int, parent=None):
        super().__init__(parent)
        self.path, self.t0, self.w, self.h = path, t0, w, h
        self._stop = threading.Event()
        self.proc = None

    def stop(self):
        self._stop.set()
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def run(self):
        self.proc = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{self.t0:.3f}",
                                      "-i", self.path, "-an", "-sn", "-vf", f"fps={FPS},scale={self.w}:{self.h}",
                                      "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        size = self.w * self.h * 3
        start = time.monotonic()
        n = 0
        while not self._stop.is_set():
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                break
            wait = start + n / FPS - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if self._stop.is_set():
                break
            img = QImage(buf, self.w, self.h, 3 * self.w, QImage.Format_RGB888).copy()
            self.frame.emit(img, self.t0 + n / FPS)
            n += 1
        try:
            self.proc.kill()
            self.proc.wait(2)
        except Exception:  # noqa: BLE001
            pass


class _Audio(QObject):
    """El sonido desde t0 (FFmpeg → altavoces). Si no hay salida de audio, el video sigue sin sonido."""

    def __init__(self, path: str, t0: float, parent=None):
        super().__init__(parent)
        self.queue: collections.deque = collections.deque()
        self._stop = threading.Event()
        self.sink = self.dev = None
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            out = QMediaDevices.defaultAudioOutput()
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.Int16)
            if out is None or out.isNull() or not out.isFormatSupported(fmt):
                return
            self.sink = QAudioSink(out, fmt, self)
            self.sink.setVolume(0.7)
            self.dev = self.sink.start()
        except Exception:  # noqa: BLE001
            self.sink = None
            return
        self.proc = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t0:.3f}",
                                      "-i", path, "-vn", "-ac", "2", "-ar", "48000", "-f", "s16le", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._feed)
        self.timer.start()
        self._pending = b""

    def _read(self):
        while not self._stop.is_set():
            b = self.proc.stdout.read(19200)          # 0,1 s
            if not b:
                break
            self.queue.append(b)

    def _feed(self):
        if self.sink is None or self.dev is None:
            return
        free = self.sink.bytesFree()
        while free > 0 and (self._pending or self.queue):
            if not self._pending:
                self._pending = self.queue.popleft()
            n = self.dev.write(self._pending[:free])
            if n <= 0:
                break
            self._pending = self._pending[n:]
            free -= n

    def stop(self):
        self._stop.set()
        if self.sink is None:
            return
        self.timer.stop()
        try:
            self.proc.kill()
        except OSError:
            pass
        try:
            self.sink.stop()
        except RuntimeError:
            pass


class _Still(QThread):
    """El fotograma de un momento (al parar o al hacer clic en la barra). Siempre el último que pediste."""
    frame = Signal(QImage, float)

    def __init__(self, path: str, w: int, h: int, parent=None):
        super().__init__(parent)
        self.path, self.w, self.h = path, w, h
        self.want: float | None = None
        self._lock = threading.Lock()
        self._alive = True

    def ask(self, t: float):
        with self._lock:
            self.want = t
        if not self.isRunning():
            self.start()

    def run(self):
        while self._alive:
            with self._lock:
                t, self.want = self.want, None
            if t is None:
                return
            r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t:.3f}",
                                       "-i", self.path, "-frames:v", "1", "-vf", f"scale={self.w}:{self.h}",
                                       "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], timeout=30)
            size = self.w * self.h * 3
            if r.returncode == 0 and len(r.stdout) >= size:
                img = QImage(r.stdout[:size], self.w, self.h, 3 * self.w, QImage.Format_RGB888).copy()
                self.frame.emit(img, t)


# ------------------------------------------------------------------ barra
RULER = 15                     # alto de la regla de tiempos (encima de la pista)
STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800)
DIV = {0.2: 2, 2: 2, 15: 3, 30: 3, 60: 4, 120: 4, 900: 3, 1800: 3, 3600: 4, 7200: 4, 10800: 3}   # rayitas pequeñas


def ruler_label(t: float, step: float) -> str:
    """Una marca de la regla con su unidad a la vista, según lo acercada que esté: «45s», «2m 30s», «1h 05m»…"""
    t = max(0.0, t + 1e-6)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    h, m = int(h), int(m)
    if step >= 3600:
        return f"{h}h" + (f" {m:02d}m" if m else "")
    if step >= 60:
        return f"{h}h {m:02d}m" if h else f"{m}m"
    sec = f"{s:04.1f}s" if step < 1 else f"{int(s):02d}s"
    if h:
        return f"{h}h {m:02d}m {sec}"
    if m:
        return f"{m}m {sec}"
    return f"{s:.1f}s" if step < 1 else f"{int(s)}s"


class _ZoomGauge(QWidget):
    """🔍 Cuánto está acercada la barra: una lupa, una barrita que se llena (vacía = el video entero, llena = lo más
    cerca) y el nivel («Todo», «×4 · 16 min»…). El usuario: «que haya como una lupa indicando qué tan cerca y lejos
    estoy»."""

    def __init__(self):
        super().__init__()
        self.level, self.text = 0.0, "Todo"
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        self._f = f
        self.setFixedSize(190, 16)
        self.setToolTip("Cuánto has acercado la barra (Ctrl+rueda o «🔍−» «🔍+»): vacía = el video entero.")

    def set(self, level: float, text: str):
        self.level, self.text = max(0.0, min(1.0, level)), text
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#e8742f") if self.level > 0.001 else QColor("#8b8f98")
        p.setPen(QPen(col, 1.6))                   # la lupa (dibujada: nítida y del color del estado)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(1.5, 1.5, 9, 9))
        p.drawLine(QPointF(9.2, 9.2), QPointF(13.5, 13.5))
        track = QRectF(19, 6, 60, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#34373e"))
        p.drawRoundedRect(track, 2, 2)
        if self.level > 0.001:
            p.setBrush(col)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(4.0, track.width() * self.level), 4), 2, 2)
        p.setFont(self._f)
        p.setPen(QColor("#a0a3ac"))
        p.drawText(QRectF(86, 0, self.width() - 86, 16), Qt.AlignLeft | Qt.AlignVCenter, self.text)


class _RangeBar(QWidget):
    """Todo el video en una barra: tramos elegidos (naranja), entrada marcada (raya amarilla) y el cabezal.
    Con «↔ Arrastrar»: arrastrar sobre la barra = un tramo (de dónde a dónde), listo para «➕ Añadir».
    🔍 Se puede acercar: entonces la barra enseña solo de v0 a v1 (Ctrl+rueda / zoom()), y la rueda sola la mueve."""
    seek = Signal(float)
    selection = Signal()
    view_changed = Signal()

    def __init__(self, duration: float):
        super().__init__()
        self.duration = max(0.01, duration)
        self.v0, self.v1 = 0.0, self.duration      # 🔍 el trozo del video que se ve en la barra
        self.ranges: list[list[float]] = []
        self.pos = 0.0
        self.mark_in: float | None = None
        self.drag_mode = False
        self.scene_mode = False
        self.cuts: list[float] = []                # 🎬 cambios de escena (se detectan solos al abrir)
        self.scene_sel: set[int] = set()           # escenas marcadas (varias a la vez)
        self.blacks: list[list[float]] = []        # ⬛ dónde la imagen está completamente negra (se detectan solos)
        self.sel: list[float] | None = None        # el tramo arrastrado (aún sin añadir)
        self._anchor: float | None = None
        self.pressed = False
        self.setFixedHeight(38 + RULER)
        self.setCursor(Qt.PointingHandCursor)
        self._rfont = QFont(self.font())
        self._rfont.setPointSizeF(7.5)

    def ticks(self) -> tuple[float, float, list[tuple[float, str]]]:
        """⏱ La regla de lo que se ve: (paso entre números, paso de las rayitas pequeñas, [(tiempo, «etiqueta»)]).
        El paso se elige para que los números no se pisen: más cerca = segundos (y décimas), más lejos = minutos u
        horas."""
        span = self.v1 - self.v0
        pps = max(1, self.width() - 12) / span
        fm = QFontMetrics(self._rfont)
        step = next((s for s in STEPS if s * pps >= fm.horizontalAdvance(ruler_label(self.v1, s)) + 18), STEPS[-1])
        minor = step / DIV.get(step, 5)
        k0 = math.ceil(self.v0 / step - 1e-9)
        marks = []
        k = k0
        while k * step <= self.v1 + 1e-9:
            marks.append((round(k * step, 3), ruler_label(k * step, step)))
            k += 1
        return step, minor, marks

    def _x(self, t):
        return 6 + (self.width() - 12) * (t - self.v0) / (self.v1 - self.v0)

    def _t_at(self, x: float) -> float:
        t = self.v0 + (x - 6) / max(1, self.width() - 12) * (self.v1 - self.v0)
        return max(self.v0, min(self.v1, t))

    def _t(self, e) -> float:
        return self._t_at(e.position().x())

    # ------------------------------------------------ 🔍 acercar / alejar
    def zoomed(self) -> bool:
        return self.v1 - self.v0 < self.duration - 1e-6

    def set_view(self, a: float, span: float):
        span = max(min(MIN_SPAN, self.duration), min(self.duration, span))
        if span > self.duration * 0.999:                    # (sin restos de redondeo al alejar del todo)
            span = self.duration
        a = max(0.0, min(self.duration - span, a))
        self.v0, self.v1 = a, a + span
        self.view_changed.emit()
        self.update()

    def zoom(self, k: float, at: float | None = None):
        """k > 1 acerca, k < 1 aleja. El momento «at» se queda en el mismo sitio de la barra (si no se ve: el centro)."""
        span = self.v1 - self.v0
        if at is None or not self.v0 <= at <= self.v1:
            at = (self.v0 + self.v1) / 2
        f = (at - self.v0) / span
        new = max(min(MIN_SPAN, self.duration), min(self.duration, span / k))
        self.set_view(at - f * new, new)

    def pan(self, dt: float):
        self.set_view(self.v0 + dt, self.v1 - self.v0)

    def follow(self, t: float):
        """Si el cabezal se sale de lo que se ve (reproduciendo, −1 s / +1 s…), la vista lo sigue y lo centra."""
        if not self.v0 <= t <= self.v1:
            span = self.v1 - self.v0
            self.set_view(t - span / 2, span)

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:     # Ctrl+rueda = acercar / alejar donde está el ratón (como la línea
            self.zoom(1.25 ** (dy / 120), self._t_at(e.position().x()))     # de tiempo)
        elif self.zoomed():                         # acercada, la rueda sola = moverse por el video
            self.pan(-dy / 120 * 0.1 * (self.v1 - self.v0))
        else:
            e.ignore()
            return
        e.accept()

    def scenes(self) -> list[tuple[float, float]]:
        edges = [0.0] + [c for c in self.cuts if 0.0 < c < self.duration] + [self.duration]
        return list(zip(edges, edges[1:]))

    def scene_at(self, t: float) -> int:
        for i, (a, b) in enumerate(self.scenes()):
            if a <= t < b:
                return i
        return len(self.scenes()) - 1

    def snap(self, t: float) -> float:
        """Imán: a menos de 7 px de un cambio de escena, se pega a él (para no llevarte un trozo de la otra)."""
        px = 7 * (self.v1 - self.v0) / max(1, self.width() - 12)
        near = min(self.cuts, key=lambda c: abs(c - t), default=None)
        return near if near is not None and abs(near - t) <= px else t

    def mousePressEvent(self, e):
        t = self._t(e)
        self.pressed = True
        if self.scene_mode and self.cuts:          # 🎬 clic = marcar / desmarcar esa escena (varias a la vez)
            i = self.scene_at(t)
            self.scene_sel ^= {i}
            self.selection.emit()
            self.update()
            self.seek.emit(self.scenes()[i][0])
            return
        if self.drag_mode:
            if self.sel is not None and abs(e.position().x() - self._x(self.pos)) <= 6:
                # ya soltaste un tramo y pinchas SOBRE el cabezal rojo: se sigue desde ahí (el usuario: «no se debería
                # cancelar sino mantenerse»); el otro extremo se queda quieto
                a, b = self.sel
                self._anchor = a if abs(self.pos - b) <= abs(self.pos - a) else b
                t = self.pos
                self.sel = sorted([self._anchor, t])
                self.selection.emit()
                self.update()
                return
            t = self.snap(t)
            self._anchor = t
            self.sel = [t, t]
            self.selection.emit()
        self.seek.emit(t)

    def mouseMoveEvent(self, e):
        t = self._t(e)
        if self.scene_mode and self.cuts:
            return
        if self.drag_mode and self._anchor is not None:
            t = self.snap(t)
            self.sel = sorted([self._anchor, t])
            self.selection.emit()
            self.update()
        self.seek.emit(t)                       # se ve el fotograma por donde vas arrastrando

    def mouseReleaseEvent(self, e):
        self.pressed = False
        if self.drag_mode and self._anchor is not None:
            self._anchor = None
            if self.sel and self.sel[1] - self.sel[0] < 0.3:
                self.sel = None
            self.selection.emit()
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setClipRect(QRectF(4, 0, self.width() - 8, self.height()))     # 🔍 acercada: lo de fuera no se pinta
        r = QRectF(6, 11 + RULER, self.width() - 12, 16)
        p.fillRect(r, QColor("#2a2a2d"))
        # ⏱ la regla: números con su unidad (s, m, h) y rayitas, como en la línea de tiempo de Resolve
        step, minor, marks = self.ticks()
        pps = (self.width() - 12) / (self.v1 - self.v0)
        if minor * pps >= 6:
            p.setPen(QColor(255, 255, 255, 45))
            k = math.ceil(self.v0 / minor - 1e-9)
            while k * minor <= self.v1 + 1e-9:
                x = int(self._x(k * minor))
                p.drawLine(x, RULER + 4, x, RULER + 7)
                k += 1
        p.setFont(self._rfont)
        fm = p.fontMetrics()
        for t, label in marks:
            x = self._x(t)
            p.setPen(QColor(255, 255, 255, 110))
            p.drawLine(int(x), RULER + 1, int(x), RULER + 7)
            p.fillRect(QRectF(int(x), r.top(), 1, r.height()), QColor(255, 255, 255, 16))   # guía tenue en la pista
            if x + 3 + fm.horizontalAdvance(label) <= self.width() - 6:
                p.setPen(QColor("#9ca0a9"))
                p.drawText(QRectF(x + 3, 0, 200, RULER + 2), Qt.AlignLeft | Qt.AlignVCenter, label)
        for i, (a, b) in enumerate(self.scenes() if self.cuts else []):     # 🎬 escenas
            if i in self.scene_sel:
                p.fillRect(QRectF(self._x(a), r.top() - 3, max(2.0, self._x(b) - self._x(a)), r.height() + 6),
                           QColor(90, 210, 120, 150))
            elif i % 2:
                p.fillRect(QRectF(self._x(a), r.top(), max(1.0, self._x(b) - self._x(a)), r.height()),
                           QColor(255, 255, 255, 14))
        for a, b in self.ranges:
            p.fillRect(QRectF(self._x(a), r.top(), max(2.0, self._x(b) - self._x(a)), r.height()), QColor("#e8742f"))
        for a, b in self.blacks:                  # ⬛ imagen negra: rayita amarilla debajo (un solo fotograma también)
            p.fillRect(QRectF(self._x(a), r.bottom() + 3, max(3.0, self._x(b) - self._x(a)), 4), QColor("#ffd23c"))
        if self.sel is not None:                # el tramo arrastrado (verde: listo para añadir)
            a, b = self.sel
            p.fillRect(QRectF(self._x(a), r.top() - 3, max(2.0, self._x(b) - self._x(a)), r.height() + 6),
                       QColor(90, 210, 120, 150))
        if self.mark_in is not None:            # el tramo que estás marcando (hasta el cabezal)
            a, b = sorted((self.mark_in, self.pos))
            p.fillRect(QRectF(self._x(a), r.top(), max(2.0, self._x(b) - self._x(a)), r.height()),
                       QColor(255, 210, 60, 110))
            p.fillRect(QRectF(self._x(self.mark_in) - 1.5, RULER + 3, 3, 32), QColor("#ffd23c"))
        p.setPen(QColor(255, 255, 255, 95))
        for c in self.cuts:                       # raya fina en cada cambio de escena
            x = self._x(c)
            p.drawLine(int(x), int(r.top()) - 3, int(x), int(r.bottom()) + 3)
        p.fillRect(QRectF(self._x(self.pos) - 1, 1, 2, self.height() - 3), QColor("#e5413c"))   # cruza la regla


# ------------------------------------------------------------------ ventana
class RangePicker(QDialog):
    def __init__(self, media, ranges: list | None = None, parent=None):
        super().__init__(parent)
        self.m = media
        self.src = play_source(media)
        self.dur = float(media.duration or 1.0)
        w0, h0 = (media.width or 16), (media.height or 9)
        self.vw, self.vh = VW, max(2, int(round(VW * h0 / max(1, w0) / 2)) * 2)
        self.t = 0.0
        self._closing = False
        self.video: _Video | None = None
        self.audio: _Audio | None = None
        self.still = _Still(self.src, self.vw, self.vh, self)
        self.still.frame.connect(self._show)
        self.setWindowTitle(f"✂ Tramos para el edit · {media.name}")
        self.resize(860, 640)
        lay = QVBoxLayout(self)
        tip = QLabel("Reproduce (Espacio) y marca con <b>un solo botón</b>: <b>[ Entrada</b> y, al volver a "
                     "pulsarlo, <b>Salida ]</b> (o la tecla <b>I</b>): el tramo se añade solo. La IA solo usará "
                     "planos de estos tramos (sin ninguno = todo el video).")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.screen = QLabel()
        self.screen.setAlignment(Qt.AlignCenter)
        self.screen.setMinimumHeight(300)
        self.screen.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.screen.setStyleSheet("background: #000;")
        lay.addWidget(self.screen, 1)
        self.bar = _RangeBar(self.dur)
        self.bar.ranges = [list(r) for r in (ranges or [])]
        self.bar.seek.connect(self.seek_to)
        self.bar.selection.connect(self._sel_changed)
        drow = QHBoxLayout()                      # ↔ Arrastrar: otra forma de elegir (además de Entrada/Salida)
        self.b_drag = QPushButton("↔ Arrastrar")
        self.b_drag.setCheckable(True)
        self.b_drag.setToolTip("Actívalo y ARRASTRA sobre la barra de dónde a dónde: ese trozo queda como tramo "
                               "(en verde) y lo añades con «➕ Añadir tramo». Vas viendo el fotograma mientras "
                               "arrastras.")
        self.b_drag.toggled.connect(self._drag_mode)
        self.b_keep = QCheckBox("Continuar")          # sin marcar: tras «➕ Añadir tramo», Arrastrar se apaga solo
        self.b_keep.setToolTip("Marcado: «↔ Arrastrar» sigue activo después de «➕ Añadir tramo» (para añadir varios "
                               "seguidos).\nSin marcar: se apaga solo al añadir el tramo.")
        self.b_keep.setChecked(QSettings("EditorIA", "EditorIA").value("tramos/seguir_arrastrando", False, type=bool))
        self.b_keep.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "tramos/seguir_arrastrando", on))
        self.b_scenes = QPushButton("🎬 Escenas")
        self.b_scenes.setCheckable(True)
        self.b_scenes.setEnabled(False)
        self.b_scenes.setToolTip("Las rayas finas de la barra son los cambios de escena (se detectan solos). Con esto "
                                 "activo, CLIC en una escena = marcarla o desmarcarla: puedes marcar VARIAS y añadirlas "
                                 "de una vez. Para un trozo de una escena, usa Entrada/Salida o Arrastrar (se pegan a "
                                 "los cambios de escena cercanos).")
        self.b_scenes.toggled.connect(self._scene_mode)
        self.b_add = QPushButton("➕ Añadir tramo")
        self.b_add.setEnabled(False)
        self.b_add.clicked.connect(self.add_dragged)
        self.sel_label = QLabel("")
        self.sel_label.setObjectName("dim")
        drow_at = lay.count()                     # (se coloca más abajo, cuando existen los botones −1 s / +1 s)
        brow = QHBoxLayout()                      # 🔍 a los lados de la barra: entre qué tiempos estás viendo
        self.view_from, self.view_to = QLabel(), QLabel()
        for lb, al in ((self.view_from, Qt.AlignRight), (self.view_to, Qt.AlignLeft)):
            lb.setFixedWidth(lb.fontMetrics().horizontalAdvance("0:00:00") + 8)   # fijo: la barra no baila
            lb.setAlignment(al | Qt.AlignVCenter)
            lb.setToolTip("Entre qué tiempos estás viendo la barra. Acerca o aleja con Ctrl+rueda o con «🔍−» «🔍+».")
        brow.addWidget(self.view_from)
        brow.addWidget(self.bar, 1)
        brow.addWidget(self.view_to)
        lay.addLayout(brow)
        zrow = QHBoxLayout()                      # 🔍 debajo de la barra, a la izquierda: cuánto la has acercado
        zrow.setContentsMargins(0, 0, 0, 0)
        zrow.addSpacing(self.view_from.width() + brow.spacing() + 6)
        self.zoom_gauge = _ZoomGauge()
        zrow.addWidget(self.zoom_gauge)
        zrow.addStretch(1)
        lay.addLayout(zrow)
        self.bar.view_changed.connect(self._view_changed)
        row = QHBoxLayout()
        self.b_play = QPushButton("▶")
        self.b_play.setFixedWidth(40)
        self.b_play.clicked.connect(self.toggle)
        self.time = QLabel("")
        self.time.setMinimumWidth(150)
        fr = 1.0 / float(getattr(media, "fps", 0) or 30.0)
        steps = (("−1 s", -1.0, "1 segundo atrás (←). Con «↔ Arrastrar», también arrastra el tramo verde"), ("◀|", -fr, "Un fotograma atrás (,)"),
                 ("|▶", fr, "Un fotograma adelante (.)"), ("+1 s", 1.0, "1 segundo adelante (→). Con «↔ Arrastrar», también arrastra el tramo verde"))
        self.step_btns = []
        for txt, dt, tip_ in steps:
            b_ = QPushButton(txt)
            b_.setToolTip(tip_)
            b_.setFixedWidth(46)
            b_.setAutoRepeat(True)                    # mantenido pulsado: sigue avanzando
            b_.clicked.connect(lambda _=False, d=dt: self.step(d))
            self.step_btns.append(b_)
        self.b_zoom_out = QPushButton("🔍−")
        self.b_zoom_out.setToolTip("Alejar la barra (también Ctrl + rueda del ratón hacia atrás). Del todo alejada se "
                                   "ve el video entero.")
        self.b_zoom_out.clicked.connect(lambda: self.bar.zoom(0.5, self.t))
        self.b_zoom_in = QPushButton("🔍+")
        self.b_zoom_in.setToolTip("Acercar la barra alrededor del cabezal rojo (también Ctrl + rueda del ratón). A los "
                                  "lados ves entre qué tiempos estás; con la rueda sola te mueves por el video.")
        self.b_zoom_in.clicked.connect(lambda: self.bar.zoom(2.0, self.t))
        self.b_mark = QPushButton()
        self.b_mark.setObjectName("primary")
        self.b_mark.setMinimumWidth(150)
        self.b_mark.clicked.connect(self.mark)
        self.hint = QLabel("")
        self.hint.setObjectName("dim")
        self.black_info = QLabel("")
        self.black_info.setObjectName("dim")
        self.black_info.setToolTip("Las rayitas amarillas DEBAJO de la barra marcan dónde la imagen se queda "
                                   "completamente negra (fundidos a negro, pantallas de carga, fotogramas negros "
                                   "sueltos). Clic encima = ir ahí. Un fondo negro con texto no cuenta.")
        # −1 s y +1 s juntos, centrados justo encima de la barra (el usuario los quiere ahí, uno al lado del otro);
        # los de un fotograma, junto al tiempo
        left, mid, right = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for w in (self.b_scenes, self.b_drag, self.b_keep, self.b_add):
            left.addWidget(w)
        left.addStretch(1)
        mid.addWidget(self.step_btns[0])
        mid.addWidget(self.step_btns[3])
        right.addSpacing(10)                      # 🔍 a la derecha de −1 s / +1 s (sin descentrarlos)
        right.addWidget(self.b_zoom_out)
        right.addWidget(self.b_zoom_in)
        right.addStretch(1)
        right.addWidget(self.sel_label)
        drow.addLayout(left, 1)
        drow.addLayout(mid, 0)
        drow.addLayout(right, 1)
        lay.insertLayout(drow_at, drow)
        for w in (self.b_play, self.step_btns[1], self.time, self.step_btns[2], self.b_mark, self.hint):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.black_info)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)     # Ctrl/Mayús = varios a la vez
        self.list.itemDoubleClicked.connect(lambda it: self.seek_to(it.data(Qt.UserRole)[0]))
        lay.addWidget(self.list)
        bottom = QHBoxLayout()
        b_del = QPushButton("✕ Quitar los tramos elegidos")
        b_del.clicked.connect(self.remove_selected)
        b_all = QPushButton("Usar todo el video")
        b_all.clicked.connect(self.clear)
        self.b_ok = QPushButton("✓ Listo")
        self.b_ok.setObjectName("primary")
        self.b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancelar")
        b_cancel.clicked.connect(self.reject)
        bottom.addWidget(b_del)
        bottom.addWidget(b_all)
        bottom.addStretch(1)
        bottom.addWidget(b_cancel)
        bottom.addWidget(self.b_ok)
        lay.addLayout(bottom)
        self._img: QImage | None = None
        self._view_changed()
        self._refresh()
        self.seek_to(0.0)
        self._detect_scenes()

    # ------------------------------------------------------------ imagen y tiempo
    def _show(self, img: QImage, t: float):
        self._img = img
        if self.video is not None:          # reproduciendo: el tiempo lo marca el video
            b = self.bar
            seen = b.v0 <= b.pos <= b.v1        # (si te has ido a mirar otro sitio con la rueda, no te devuelve)
            self.t = min(self.dur, t)
            self._update_time(follow=seen)
        self._paint()

    def _paint(self):
        if self._img is not None:
            self.screen.setPixmap(QPixmap.fromImage(self._img).scaled(self.screen.size(), Qt.KeepAspectRatio,
                                                                      Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._paint()

    def _update_time(self, follow: bool = True):
        self.time.setText(f"{fmt_time(self.t)} / {fmt_time(self.dur, False)}")       # con centésimas: precisión
        if follow:
            self.bar.follow(self.t)                 # 🔍 acercada: el cabezal no se sale de la vista
        self.bar.pos = self.t
        self.bar.update()

    def _view_changed(self):
        """🔍 A los lados de la barra, entre qué tiempos estás (sin acercar: de 0 a lo que dura el video)."""
        b = self.bar
        self.view_from.setText(fmt_time(b.v0, False))
        self.view_to.setText(fmt_time(b.v1, False))
        self.b_zoom_out.setEnabled(b.zoomed())
        self.b_zoom_in.setEnabled(b.v1 - b.v0 > min(MIN_SPAN, b.duration) + 1e-6)
        span = b.v1 - b.v0
        z = b.duration / span
        zmax = b.duration / min(MIN_SPAN, b.duration)
        level = math.log(z) / math.log(zmax) if zmax > 1.0001 else 0.0
        if not b.zoomed():
            text = "Todo"
        else:
            shown = (f"{span:.1f} s" if span < 10 else f"{span:.0f} s" if span < 90 else
                     f"{span / 60:.0f} min" if span < 5400 else f"{span / 3600:.1f} h")
            text = (f"×{z:.1f}" if z < 10 else f"×{z:.0f}") + f" · {shown}"
        self.zoom_gauge.set(level, text)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:      # 🔍 Ctrl+rueda en cualquier parte: la barra, alrededor del cabezal
            self.bar.zoom(1.25 ** ((e.angleDelta().y() or e.angleDelta().x()) / 120), self.t)
            e.accept()
        else:
            super().wheelEvent(e)

    def pos_s(self) -> float:
        return self.t

    def seek_to(self, t: float):
        was = self.video is not None and not self.bar.pressed     # arrastrando por la barra: en pausa
        self._stop_play()
        self.t = max(0.0, min(self.dur, float(t)))
        self._update_time()
        if was:
            self._start_play()
        else:
            self.still.ask(self.t)

    # ------------------------------------------------------------ reproducir
    def _start_play(self):
        self.video = _Video(self.src, self.t, self.vw, self.vh, self)
        self.video.frame.connect(self._show)
        self.video.finished.connect(self._ended)
        self.audio = _Audio(self.src, self.t, self)
        self.video.start()
        self.b_play.setText("⏸")

    def _stop_play(self):
        v, self.video = self.video, None
        if v is not None:
            try:
                v.frame.disconnect(self._show)
                v.finished.disconnect(self._ended)
            except (RuntimeError, TypeError):
                pass
            v.stop()
            v.wait(3000)
        if self.audio is not None:
            self.audio.stop()
            self.audio = None
        self.b_play.setText("▶")

    def _ended(self):
        if self.video is not None and not self.video.isRunning():
            self._stop_play()

    def toggle(self):
        if self.video is not None:
            self._stop_play()
            self.still.ask(self.t)
        else:
            self._start_play()

    def step(self, dt: float):
        """−1 s / +1 s / un fotograma (precisión). Si se reproduce, se pausa para ver justo ese fotograma.
        Con «↔ Arrastrar»: también ARRASTRA, como el ratón: el extremo del tramo verde donde está el cabezal se mueve y
        el otro se queda (si no hay tramo, empieza aquí). Así ves de antemano los fotogramas que vas a añadir."""
        if self.video is not None:
            self._stop_play()
        t0 = self.t
        self.seek_to(self.t + dt)
        b = self.bar
        if b.drag_mode and not b.scene_mode and self.t != t0:
            s_ = b.sel
            if s_ is not None and abs(t0 - s_[0]) < 1e-3:
                anchor = s_[1]
            elif s_ is not None and abs(t0 - s_[1]) < 1e-3:
                anchor = s_[0]
            else:
                anchor = t0                          # sin tramo (o el cabezal fuera de él): empieza aquí
            b.sel = sorted([anchor, self.t])
            b.pos = self.t
            self._sel_changed()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Comma, Qt.Key_Period):
            self.step((1 if k == Qt.Key_Period else -1) / float(getattr(self.m, "fps", 0) or 30.0))
            return
        if k in (Qt.Key_I, Qt.Key_O):
            self.mark()
        elif k == Qt.Key_Space:
            self.toggle()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            step = 10.0 if e.modifiers() & Qt.ShiftModifier else 1.0
            self.step(step if k == Qt.Key_Right else -step)      # (con «Arrastrar», también arrastra)
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------ tramos
    # ------------------------------------------------------------ 🎬 escenas
    def _detect_scenes(self):
        """Los cambios de escena del video, solos al abrir (el mismo detector del clic derecho; se guarda)."""
        from ..core import scene_cuts
        from .jobs import BackgroundJob
        path, dur = self.src, self.dur
        self.scene_job = BackgroundJob(lambda progress, cancelled: scene_cuts.detect(
            path, 0.0, dur, "normal", lambda f: progress(f, ""), cancelled), self)
        self.scene_job.progress.connect(
            lambda f, _t: self.b_scenes.setText(f"🎬 Buscando escenas… {int(f * 100)} %"))
        self.scene_job.done.connect(self._scenes_ready)
        self.scene_job.failed.connect(self._scenes_failed)
        self.b_scenes.setText("🎬 Buscando escenas…")
        self.scene_job.start()

    def _scenes_ready(self, cuts):
        self.bar.cuts = [float(c) for c in cuts or []]
        n = len(self.bar.scenes())
        self.b_scenes.setText(f"🎬 Escenas ({n})")
        self.b_scenes.setEnabled(bool(self.bar.cuts))
        self.bar.update()
        self._detect_black()

    def _scenes_failed(self, _msg):
        self.b_scenes.setText("🎬 Escenas (no se pudieron detectar)")
        self._detect_black()

    # ------------------------------------------------------------ ⬛ imágenes negras
    def _detect_black(self):
        """Dónde la imagen se queda completamente negra (rayitas amarillas debajo de la barra). Va DESPUÉS de las
        escenas, no a la vez (no carga el PC con dos lecturas del video), y se guarda."""
        if self._closing or getattr(self, "black_job", None) is not None:
            return
        from ..core import black_frames
        from .jobs import BackgroundJob
        path, dur = self.src, self.dur
        self.black_job = BackgroundJob(lambda progress, cancelled: black_frames.detect(
            path, dur, lambda f: progress(f, ""), cancelled), self)
        self.black_job.progress.connect(
            lambda f, _t: self.black_info.setText(f"⬛ Buscando negros… {int(f * 100)} %"))
        self.black_job.done.connect(self._black_ready)
        self.black_job.failed.connect(lambda _m: self.black_info.setText(""))
        self.black_info.setText("⬛ Buscando negros…")
        self.black_job.start()

    def _black_ready(self, blacks):
        self.bar.blacks = [list(x) for x in blacks or []]
        n = len(self.bar.blacks)
        self.black_info.setText(f"<span style='color:#ffd23c'>▬</span> Negro en {n} sitio{'s' if n != 1 else ''}"
                                if n else "Sin imágenes negras")
        self.bar.update()

    def _scene_mode(self, on: bool):
        if on and self.b_drag.isChecked():
            self.b_drag.setChecked(False)
        self.bar.scene_mode = on
        if not on:
            self.bar.scene_sel = set()
        self._sel_changed()
        if on:
            self.hint.setText("Clic en las escenas que quieras (varias) y «➕ Añadir».")

    def _drag_mode(self, on: bool):
        if on and self.b_scenes.isChecked():
            self.b_scenes.setChecked(False)
        self.bar.drag_mode = on
        self.bar.setCursor(Qt.SizeHorCursor if on else Qt.PointingHandCursor)
        if not on:
            self.bar.sel = None
        self._sel_changed()
        self.hint.setText("Arrastra sobre la barra de dónde a dónde (o con −1 s / +1 s, ← →) y pulsa «➕ Añadir "
                          "tramo»." if on else "")

    def _sel_changed(self):
        if self.bar.scene_sel:                         # 🎬 varias escenas marcadas
            sc = self.bar.scenes()
            tot = sum(sc[i][1] - sc[i][0] for i in self.bar.scene_sel if i < len(sc))
            n = len(self.bar.scene_sel)
            self.b_add.setEnabled(True)
            self.b_add.setObjectName("primary")
            self.b_add.style().unpolish(self.b_add)
            self.b_add.style().polish(self.b_add)
            self.b_add.setText(f"➕ Añadir {n} escena{'s' if n != 1 else ''}")
            self.sel_label.setText(f"{tot:.1f} s en total")
            self.bar.update()
            return
        self.b_add.setText("➕ Añadir tramo")
        s = self.bar.sel
        ok = s is not None and s[1] - s[0] >= 0.3
        self.b_add.setEnabled(ok)
        self.b_add.setObjectName("primary" if ok else "")
        self.b_add.style().unpolish(self.b_add)
        self.b_add.style().polish(self.b_add)
        blk = self._black_in(*s) if ok else 0.0
        self.sel_label.setText(f"{fmt_time(s[0], False)} → {fmt_time(s[1], False)}  ({s[1] - s[0]:.1f} s)" +
                               (f" · {blk:.2f} s en negro: no entran" if blk else "") if ok else "")
        self.bar.update()

    def add_dragged(self):
        if self.bar.scene_sel:                         # 🎬 las escenas marcadas, todas de una vez
            sc = self.bar.scenes()
            picked = sorted(sc[i] for i in self.bar.scene_sel if i < len(sc))
            self.bar.scene_sel = set()
            added = sum(self.add_range(a, b, seek=False) for a, b in picked)
            self.hint.setText(f"✓ {len(picked)} escena(s) añadida(s) ({added:.1f} s nuevos).")
            self._sel_changed()
            self._refresh()
            return
        s = self.bar.sel
        if s is None:
            return
        self.bar.sel = None
        self.add_range(*s, skip_black=True)            # ⬛ lo que está en negro (amarillo) no entra
        if not self.b_keep.isChecked():                # ya añadido: Arrastrar se apaga solo (salvo «Continuar»)
            msg = self.hint.text()
            self.b_drag.setChecked(False)
            self.hint.setText(msg)                     # (que se siga viendo «✓ Tramo añadido…»)
        self._sel_changed()
        self._refresh()

    def mark(self):
        """Un solo botón: la primera vez, la entrada; la siguiente, la salida (y el tramo se añade)."""
        if self.bar.mark_in is None:
            self.bar.mark_in = self.t
            self.hint.setText(f"Entrada en {fmt_time(self.t, False)}: ahora la salida.")
        else:
            a, b = sorted((self.bar.mark_in, self.t))
            self.bar.mark_in = None
            self.add_range(a, b)
        self._refresh()

    @staticmethod
    def _minus(pieces: list, holes: list) -> list:
        """Los trozos [p, q] sin lo que cae dentro de los huecos [x, y] (un trozo puede quedar partido en dos)."""
        for x, y in sorted(holes):
            nxt = []
            for p, q in pieces:
                if y <= p or x >= q:
                    nxt.append([p, q])
                    continue
                if x > p:
                    nxt.append([p, x])
                if y < q:
                    nxt.append([y, q])
            pieces = nxt
        return pieces

    def _black_in(self, p: float, q: float) -> float:
        """⬛ Cuántos segundos en negro hay entre p y q."""
        return sum(max(0.0, min(q, y) - max(p, x)) for x, y in self.bar.blacks)

    def add_range(self, a: float, b: float, seek: bool = True, skip_black: bool = False) -> float:
        """Añade [a, b] SIN lo que ya estaba elegido (no se duplica). Con skip_black (lo arrastrado), tampoco lo que está
        en negro (las rayitas amarillas): el tramo queda partido en trozos. Devuelve los segundos nuevos."""
        if b - a < 0.3:
            self.hint.setText("Tramo demasiado corto: deja correr el video (o muévete) entre entrada y salida.")
            return 0.0
        new = self._minus([[a, b]], self.bar.ranges)   # se quita lo que ya tenías elegido
        black = 0.0
        if skip_black and self.bar.blacks:
            black = sum(self._black_in(p, q) for p, q in new)
            new = self._minus(new, self.bar.blacks)
        new = [[round(p, 3), round(q, 3)] for p, q in new if q - p >= 0.3]
        added = sum(q - p for p, q in new)
        if not new:
            self.hint.setText("En ese tramo solo hay negro (o lo que ya tenías elegido): no se añade nada." if black
                              else "Ese tramo ya lo tenías elegido.")
            return 0.0
        rs = sorted(self.bar.ranges + new)
        merged: list[list[float]] = []
        for r in rs:                                   # los que se tocan: uno solo (salvo si en medio hay negro)
            if merged and r[0] <= merged[-1][1] + 0.05 and not self._black_in(merged[-1][1], r[0]):
                merged[-1][1] = max(merged[-1][1], r[1])
            else:
                merged.append(list(r))
        self.bar.ranges = merged
        dup = (b - a) - added - black
        self.hint.setText(f"✓ Tramo añadido ({added:.1f} s)" + (f"; {dup:.1f} s ya estaban elegidos" if dup > 0.2
                                                               else "") +
                          (f"; sin {black:.2f} s en negro" if black > 0 else "") + ". Sigue desde aquí.")
        if self.video is None and seek:                 # sigue desde el final del tramo
            self.seek_to(b)
        return added

    def remove_selected(self):
        sel = [it.data(Qt.UserRole) for it in self.list.selectedItems()]
        if not sel and self.list.currentItem() is not None:
            sel = [self.list.currentItem().data(Qt.UserRole)]
        if sel:
            self.bar.ranges = [x for x in self.bar.ranges if x not in sel]
            self._refresh()

    def clear(self):
        self.bar.ranges = []
        self.bar.mark_in = None
        self._refresh()

    def _refresh(self):
        self.b_mark.setText("Salida ]  (I)" if self.bar.mark_in is not None else "[ Entrada  (I)")
        self.list.clear()
        for r in self.bar.ranges:
            it = QListWidgetItem(f"{fmt_time(r[0], False)} → {fmt_time(r[1], False)}   ({r[1] - r[0]:.1f} s)")
            it.setData(Qt.UserRole, r)
            self.list.addItem(it)
        total = sum(b - a for a, b in self.bar.ranges)
        self.setWindowTitle(f"✂ Tramos para el edit · {self.m.name}" +
                            (f" · {len(self.bar.ranges)} tramo(s), {total:.0f} s" if self.bar.ranges else " · todo"))
        self.bar.update()

    def ranges(self) -> list[list[float]]:
        return [list(r) for r in self.bar.ranges]

    def done(self, r):
        self._closing = True                       # (que al cancelar las escenas no empiece la búsqueda de negros)
        for job in (getattr(self, "scene_job", None), getattr(self, "black_job", None)):
            if job is not None and job.isRunning():
                job.cancel()
                job.wait(3000)
        self._stop_play()
        self.still._alive = False
        self.still.wait(3000)
        super().done(r)
