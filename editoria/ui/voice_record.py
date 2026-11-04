"""
🎙 «Grabar voz en off»: hablas mientras ves el video y la toma cae en la pista de voz, en el cabezal.

  · Micrófono a elegir (se recuerda) y medidor de nivel (verde bien · amarillo alto · rojo satura).
  · Cuenta atrás de 3 s; el video se reproduce mientras grabas y el sonido del proyecto se silencia
    (así no se cuela en el micrófono; se puede cambiar).
  · Cada toma es un WAV aparte («Grabaciones de voz», junto al proyecto). Nunca tapa nada: si en ese sitio ya hay
    audio, va a otra pista. Ctrl+Z quita la toma de la línea de tiempo (el archivo se queda).
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from ..core import voice_record as VR
from ..core.model import TRACK_AUDIO
from .common import fmt_time


class VoiceRecordDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl, self.engine = win, win.ctrl, win.engine
        self.settings = QSettings("EditorIA", "EditorIA")
        self.setWindowTitle("🎙 Grabar voz en off")
        self.setModal(False)
        from . import help as help_ui
        help_ui.set_help(self, "voz_off")
        lay = QVBoxLayout(self)
        tip = QLabel("Pon el cabezal donde empieza tu narración y pulsa <b>⏺ Grabar</b>: tras la cuenta atrás, el "
                     "video se reproduce y grabas mientras lo ves. <b>⏹ Parar</b> (o Espacio) y la toma queda en la "
                     "pista de voz. Ctrl+Z la quita.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        row.addWidget(QLabel("Micrófono"))
        self.mic = QComboBox()
        devs = QMediaDevices.audioInputs()
        default = QMediaDevices.defaultAudioInput()
        last = str(self.settings.value("voz/microfono", "") or "")
        for d in devs:
            self.mic.addItem(d.description(), d)
        idx = next((i for i, d in enumerate(devs) if d.description() == last), -1)
        if idx < 0:
            idx = next((i for i, d in enumerate(devs) if d.id() == default.id()), 0)
        if devs:
            self.mic.setCurrentIndex(idx)
        self.mic.currentIndexChanged.connect(self._open_mic)
        row.addWidget(self.mic, 1)
        lay.addLayout(row)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(10)
        self.meter.setToolTip("Nivel del micrófono: habla normal y que llegue a la zona amarilla sin tocar el rojo.")
        lay.addWidget(self.meter)
        self.c_play = QCheckBox("Reproducir el video mientras grabas")
        self.c_play.setChecked(str(self.settings.value("voz/reproducir", "true")) == "true")
        self.c_mute = QCheckBox("Silenciar el sonido del proyecto mientras grabas (que no se cuele en el micro)")
        self.c_mute.setChecked(str(self.settings.value("voz/silenciar", "true")) == "true")
        self.c_count = QCheckBox("Cuenta atrás de 3 s")
        self.c_count.setChecked(str(self.settings.value("voz/cuenta", "true")) == "true")
        for c in (self.c_play, self.c_mute, self.c_count):
            lay.addWidget(c)
        self.big = QLabel("")
        self.big.setAlignment(Qt.AlignCenter)
        self.big.setStyleSheet("font-size: 22pt; font-weight: 700; color: #ff5a4f;")
        lay.addWidget(self.big)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.b_rec = QPushButton("⏺  Grabar")
        self.b_rec.setObjectName("primary")
        self.b_rec.clicked.connect(self.toggle)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns.addWidget(self.b_rec)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lay.addLayout(btns)
        self.source = None
        self.io = None
        self.fmt = None
        self.take: VR.WavTake | None = None
        self.recording = False
        self.t0 = 0.0
        self.n_takes = 0
        self._count = 0
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._countdown)
        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._show_time)
        self.resize(520, 300)
        self.engine.playing_changed.connect(self._playing_changed)
        if not devs:
            self.status.setText("No se encuentra ningún micrófono. Conéctalo (o revisa en Windows → Privacidad → "
                                "Micrófono que las aplicaciones de escritorio puedan usarlo).")
            self.b_rec.setEnabled(False)
        else:
            self._open_mic()

    # ------------------------------------------------------------ micrófono
    def _format(self, dev) -> QAudioFormat:
        f = QAudioFormat()
        f.setChannelCount(1)
        f.setSampleRate(48000)
        f.setSampleFormat(QAudioFormat.Int16)
        if dev.isFormatSupported(f):
            return f
        pf = dev.preferredFormat()
        f.setSampleRate(pf.sampleRate())
        f.setChannelCount(pf.channelCount())
        if dev.isFormatSupported(f):
            return f
        return pf

    def _close_mic(self):
        if self.source is not None:
            try:
                self.source.stop()
            except RuntimeError:
                pass
            self.source.deleteLater()
        self.source, self.io = None, None

    def _open_mic(self, *_):
        if self.recording:
            return
        self._close_mic()
        dev = self.mic.currentData()
        if dev is None:
            return
        self.settings.setValue("voz/microfono", dev.description())
        self.fmt = self._format(dev)
        self.source = QAudioSource(dev, self.fmt, self)
        self.io = self.source.start()
        if self.io is None:
            self.status.setText("No se pudo abrir el micrófono (¿lo está usando otro programa, o falta el permiso "
                                "de Windows → Privacidad → Micrófono?).")
            self.b_rec.setEnabled(False)
            return
        self.io.readyRead.connect(self._read)
        self.b_rec.setEnabled(True)
        self.status.setText(f"Micrófono listo · {self.fmt.sampleRate()} Hz. Habla para ver el nivel.")

    def _sample_bytes(self) -> int:
        return {QAudioFormat.Int16: 2, QAudioFormat.Float: 4, QAudioFormat.UInt8: 1,
                QAudioFormat.Int32: 4}.get(self.fmt.sampleFormat(), 2) if self.fmt else 2

    def _read(self):
        if self.io is None:
            return
        data = bytes(self.io.readAll())
        self.feed(data)

    def feed(self, data: bytes):
        """Llega sonido del micrófono (también se usa en las pruebas, sin micrófono de verdad)."""
        lv = VR.level(data, self._sample_bytes())
        self.meter.setValue(int(lv * 100))
        color = "#e5413c" if lv > 0.95 else ("#e8c33a" if lv > 0.6 else "#3fbf62")
        self.meter.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
        if self.recording and self.take is not None:
            self.take.write(data)

    # ------------------------------------------------------------ grabar
    def toggle(self):
        if self.recording or self._tick.isActive():
            self.stop()
        else:
            self.start()

    def start(self):
        if self.fmt is None:
            return
        for k, c in (("voz/reproducir", self.c_play), ("voz/silenciar", self.c_mute), ("voz/cuenta", self.c_count)):
            self.settings.setValue(k, "true" if c.isChecked() else "false")
        self.engine.pause()
        self.t0 = self.engine.time
        self.b_rec.setText("⏹  Parar")
        self.mic.setEnabled(False)
        if self.c_count.isChecked():
            self._count = 3
            self.big.setText("3")
            self._tick.start()
        else:
            self._go()

    def _countdown(self):
        self._count -= 1
        if self._count > 0:
            self.big.setText(str(self._count))
        else:
            self._tick.stop()
            self._go()

    def _go(self):
        ch = self.fmt.channelCount() if self.fmt else 1
        self.take = VR.WavTake(VR.take_path(self.ctrl.path), self.fmt.sampleRate() if self.fmt else 48000, ch,
                               self._sample_bytes())
        if self.io is not None:
            self.io.readAll()                       # lo de la cuenta atrás no entra en la toma
        self.recording = True
        self._started = time.time()
        self.big.setText("● GRABANDO")
        if self.c_play.isChecked():
            self.engine.mute_all = self.c_mute.isChecked()
            self.engine.seek(self.t0)
            self.engine.play()
        self._clock.start()

    def _playing_changed(self, playing: bool):
        """Si paras el video (Espacio en la ventana principal) o llega al final: la toma también se para."""
        if not playing and self.recording and self.c_play.isChecked():
            self.stop()

    def _show_time(self):
        if self.recording:
            self.status.setText(f"● Grabando · {fmt_time(time.time() - self._started)}  (⏹ Parar o Espacio)")

    def stop(self):
        if self._tick.isActive():                   # parado en la cuenta atrás: no se graba nada
            self._tick.stop()
            self._reset_ui()
            self.status.setText("Cancelado.")
            return
        if not self.recording:
            return
        if self.io is not None:
            self._read()                            # lo último que quedaba en el búfer
        self.recording = False
        self._clock.stop()
        self.engine.pause()
        self.engine.mute_all = False
        take, self.take = self.take, None
        dur = take.close() if take else 0.0
        self._reset_ui()
        if take is None or dur < 0.3:
            self.status.setText("La toma es demasiado corta: no se ha puesto en la línea de tiempo.")
            return
        self.place(take.path, self.t0, dur)

    def _reset_ui(self):
        self.big.setText("")
        self.b_rec.setText("⏺  Grabar")
        self.mic.setEnabled(True)

    def place(self, path: str, t0: float, dur: float):
        """La toma, en la pista de voz en el sitio donde empezaste (nunca tapa nada)."""
        ctrl = self.ctrl
        ids = ctrl.import_now([path])
        if not ids:
            self.status.setText(f"✗ No se pudo importar la toma ({path}).")
            return
        mid = ids[0]
        ctrl.set_media_props([mid], category="Voz en off")
        p = ctrl.project
        tid = ctrl._role_track(p, "voz", create=False) or next(
            (t.id for t in p.tracks if t.kind == TRACK_AUDIO and not t.locked), None)
        if tid is None:
            self.status.setText("✗ No hay ninguna pista de audio libre (¿están todas bloqueadas?).")
            return
        ctrl.add_media([mid], tid, t0)
        self.n_takes += 1
        self.engine.seek(t0)
        self.status.setText(f"✓ Toma {self.n_takes} ({fmt_time(dur)}) en la línea de tiempo, en {fmt_time(t0)}. "
                            "Ctrl+Z la quita; ⏺ Grabar para otra.")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.toggle()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        if self.recording or self._tick.isActive():
            self.stop()
        self._close_mic()
        self.engine.mute_all = False
        try:
            self.engine.playing_changed.disconnect(self._playing_changed)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)
