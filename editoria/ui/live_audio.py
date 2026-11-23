"""
🎧 Salida del audio en directo (ver core/live_mix.py): un hilo propio con un QAudioSink que pide bloques a la mezcla.
Así el ecualizador, el volumen y lo demás se oyen MIENTRAS suena, como en DaVinci Resolve.

  LiveAudio(parent)        crea el hilo; .ok dice si hay salida de audio (si no, el visor usa sus reproductores)
  .set_plan(plan)          lo que suena (desde la interfaz; se cambia de una vez)
  .start(t) / .stop()      reproducir desde t / parar
  .position()              segundo que se está oyendo ahora (para corregir si se separa del visor)
  .close()

Pruebas: EDITORIA_SIN_SONIDO=1 → sin tarjeta (no suena nada), pero la mezcla trabaja igual.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..core import live_mix as LM

BUFFER_S = 0.14            # lo que va por delante en la tarjeta (más = más seguro; menos = responde antes)


class _Worker(QObject):
    """Vive en su hilo: abre la tarjeta y la mantiene llena con bloques de la mezcla."""

    def __init__(self, mixer: LM.Mixer, sin_sonido: bool):
        super().__init__()
        self.mixer = mixer
        self.sin_sonido = sin_sonido
        self.sink = None
        self.dev = None
        self.fmt_float = True
        self.playing = False
        self.pos = 0.0               # segundo de la línea de tiempo del próximo bloque
        self.written = 0             # muestras escritas desde start (para saber qué se oye)
        self.t_start = 0.0
        self.timer = None
        self.ok = False
        self._clock0 = 0.0
        self.listo = threading.Event()   # init() terminó (con o sin tarjeta)
        self._devices = None
        self.pedidos = 0             # arranques pedidos (los pone LiveAudio antes de avisar)
        self.atendidos = 0           # arranques atendidos: si llegan varios seguidos (scrub), solo el último
        self.t_pedido = 0.0          # cuándo se pidió el último (para compensar lo que tarda en arrancar)
        self._rampa = False          # fundido de ~5 ms en el primer bloque tras arrancar (sin chasquido)
        self._oido = (0.0, 0.0)      # (segundo que suena, cuándo se midió): lo lee la interfaz sin tocar la tarjeta

    @Slot()
    def init(self):
        try:
            self.timer = QTimer(self)
            self.timer.setInterval(8)
            self.timer.timeout.connect(self._pump)
            if self.sin_sonido:
                self.ok = True
                return
            self._abrir()
            try:
                from PySide6.QtMultimedia import QMediaDevices
                self._devices = QMediaDevices(self)
                self._devices.audioOutputsChanged.connect(self._cambio_dispositivo)
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.listo.set()

    def _cambio_dispositivo(self):
        """🎧 Enchufaste unos auriculares (o Bluetooth): la salida pasa al dispositivo nuevo sin parar."""
        seguia, t = self.playing, self.pos
        self.stop()
        if self.sink is not None:
            self.sink.deleteLater()
            self.sink = None
        self._abrir()
        if seguia and self.ok:
            self.start(t)

    def _abrir(self):
        self.ok = False
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            dev = QMediaDevices.defaultAudioOutput()
            fmt = QAudioFormat()
            fmt.setSampleRate(LM.SR)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.Float)
            if not dev.isFormatSupported(fmt):
                fmt.setSampleFormat(QAudioFormat.Int16)
                self.fmt_float = False
                if not dev.isFormatSupported(fmt):
                    return
            self.sink = QAudioSink(dev, fmt, self)
            self.sink.setBufferSize(int(LM.SR * BUFFER_S) * (8 if self.fmt_float else 4))
            self.ok = True
        except Exception:  # noqa: BLE001 - sin tarjeta o sin QtMultimedia: el visor usa sus reproductores
            self.sink = None
            self.ok = False

    @Slot(float)
    def start(self, t: float):
        self.atendidos += 1
        if self.atendidos < self.pedidos:      # (ya hay otro arranque más nuevo en cola: este sobra)
            return
        self.mixer.reset()
        self.written = 0
        self.playing = True
        if self.sink is not None:
            # 🔊 Parar antes de arrancar otra vez: si ya sonaba (clic en la línea de tiempo mientras se reproduce),
            # QAudioSink.start() sin stop() deja la salida en reposo y el audio se queda mudo hasta darle a Espacio.
            self.sink.stop()
            self.dev = self.sink.start()
        # (lo que tardó en llegar aquí y en arrancar la tarjeta: el cabezal ya avanzó eso)
        dt = max(0.0, min(0.5, time.perf_counter() - self.t_pedido)) if self.t_pedido else 0.0
        self.pos = self.t_start = t + dt
        self._clock0 = time.perf_counter()
        self._oido = (self.t_start, self._clock0)
        self._rampa = True
        self._pump()
        self.timer.start()

    @Slot()
    def stop(self):
        self.playing = False
        if self.timer is not None:
            self.timer.stop()
        if self.sink is not None:
            self.sink.stop()
            self.dev = None

    def _bytes(self, block: np.ndarray) -> bytes:
        if self.fmt_float:
            return block.astype(np.float32).tobytes()
        return (np.clip(block, -1, 1) * 32767).astype(np.int16).tobytes()

    def _pump(self):
        if not self.playing:
            return
        n = self.mixer.block
        if self.sink is None:                  # (sin tarjeta: al ritmo del reloj, para las pruebas)
            want = int((time.perf_counter() - self._clock0 + BUFFER_S) * LM.SR)
            while self.written < want:
                self.mixer.render(self.pos, n)
                self.pos += n / LM.SR
                self.written += n
            self.mixer.prefetch(self.pos)
            return
        if self.dev is None:
            return
        per = n * (8 if self.fmt_float else 4)
        while self.sink.bytesFree() >= per:
            bloque = self.mixer.render(self.pos, n)
            if self._rampa:                    # (entra en ~5 ms: sin chasquido al saltar o al hacer scrub)
                self._rampa = False
                k = min(len(bloque), max(1, int(LM.SR * 0.005)))
                bloque = np.array(bloque, dtype=np.float32, copy=True)
                bloque[:k] *= np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None] if bloque.ndim == 2 else \
                    np.linspace(0.0, 1.0, k, dtype=np.float32)
            self.dev.write(self._bytes(bloque))
            self.pos += n / LM.SR
            self.written += n
        queued = (self.sink.bufferSize() - self.sink.bytesFree()) / (8 if self.fmt_float else 4)
        self._oido = (self.t_start + (self.written - queued) / LM.SR, time.perf_counter())
        self.mixer.prefetch(self.pos)

    def heard(self) -> float:
        """Segundo que suena ahora: lo escrito menos lo que aún espera en la tarjeta. Desde el hilo de la interfaz
        solo se lee lo que midió el hilo del audio (más lo que pasó desde entonces): no se toca la tarjeta."""
        if self.sink is None:
            return self.t_start + (time.perf_counter() - self._clock0)
        oido, cuando = self._oido
        return oido + max(0.0, min(0.1, time.perf_counter() - cuando))


class LiveAudio(QObject):
    _start = Signal(float)
    _stop = Signal()
    _init = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.decoder = LM.Decoder()
        self.mixer = LM.Mixer(self.decoder)
        self._thread = QThread()
        self._thread.setObjectName("audio_en_directo")
        sin = os.environ.get("EDITORIA_SIN_SONIDO") == "1" or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        self._w = _Worker(self.mixer, sin)
        self._w.moveToThread(self._thread)
        self._init.connect(self._w.init)
        self._start.connect(self._w.start)
        self._stop.connect(self._w.stop)
        self._thread.start()
        self._init.emit()
        # (23/11) SÍ se espera aquí a que abra la tarjeta (unos 50 ms): abrirla en su hilo mientras la ventana crea sus
        # reproductores ponía a QtMultimedia a arrancar en dos hilos a la vez, y con una tarjeta real Reclaimer pudo
        # quedarse colgado en «Abriendo…» (en las pruebas no hay tarjeta y no se veía).
        self._w.listo.wait(1.5)
        self.playing = False

    @property
    def listo(self) -> bool:
        """True si ya se sabe si hay tarjeta (sin esperar)."""
        return self._w.listo.is_set()

    @property
    def ok(self) -> bool:
        self._w.listo.wait(1.5)                # (espera a que abra la tarjeta: unos ms)
        return self._w.ok

    def set_plan(self, plan: LM.Plan):
        self.mixer.plan = plan
        if not self.playing:
            return
        self.mixer.prefetch(self._w.pos)

    def prepare(self, t: float):
        """Antes de reproducir: pide lo que va a sonar (así arranca con sonido) y cancela lo pedido antes."""
        self.mixer.prefetch(t, 2.0, solo_esto=True)

    def wait_ready(self, t: float, max_s: float = 0.3):
        """Hasta max_s esperando a que esté decodificado lo que suena en t (así «Escuchar» no empieza mudo)."""
        self.mixer.prefetch(t, 2.0)
        t_fin = time.perf_counter() + max_s
        while time.perf_counter() < t_fin and not self.mixer.ready_at(t):
            time.sleep(0.01)

    def start(self, t: float):
        self.playing = True
        self._w.t_pedido = time.perf_counter()     # (para compensar lo que tarde en arrancar)
        self._w.pedidos += 1                       # (si llegan varios seguidos, el hilo del audio salta a este)
        self._start.emit(float(t))

    def stop(self):
        if self.playing:
            self.playing = False
            self._stop.emit()

    def position(self) -> float | None:
        return self._w.heard() if self.playing else None

    def close(self):
        if getattr(self, "_cerrado", False):
            return
        self._cerrado = True
        try:
            self.stop()
            self._thread.quit()
            self._thread.wait(1500)
        except RuntimeError:                         # (Qt ya lo borró al salir)
            pass
        self.decoder.close()
