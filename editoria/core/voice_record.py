"""
🎙 Grabar la voz en off: lo que entra por el micrófono se guarda en un WAV (sin pérdida) mientras ves el video.

  takes_dir(project_path) → carpeta de las tomas: junto al proyecto («Grabaciones de voz») o, si aún no lo
                            guardaste, F:\\Reclaimer\\Grabaciones de voz
  WavTake(path, rate, channels, sample_bytes) · write(pcm) · close() -> duración
  level(pcm, sample_bytes) -> 0…1 (pico, para el medidor)
"""
from __future__ import annotations

import os
import time
import wave

import numpy as np

from .paths import PROGRAM_DIR

FOLDER = "Grabaciones de voz"


def takes_dir(project_path: str | None) -> str:
    base = os.path.dirname(project_path) if project_path else str(PROGRAM_DIR)
    d = os.path.join(base, FOLDER)
    os.makedirs(d, exist_ok=True)
    return d


def take_path(project_path: str | None) -> str:
    return os.path.join(takes_dir(project_path), f"Voz {time.strftime('%Y-%m-%d %H-%M-%S')}.wav")


def level(pcm: bytes, sample_bytes: int = 2) -> float:
    """Pico del trozo (0…1) para el medidor."""
    if not pcm:
        return 0.0
    if sample_bytes == 2:
        a = np.frombuffer(pcm[: len(pcm) // 2 * 2], np.int16).astype(np.float32) / 32768.0
    elif sample_bytes == 4:
        a = np.frombuffer(pcm[: len(pcm) // 4 * 4], np.float32)
    else:
        a = (np.frombuffer(pcm, np.uint8).astype(np.float32) - 128.0) / 128.0
    return float(min(1.0, np.abs(a).max())) if a.size else 0.0


class WavTake:
    """Una toma: se va escribiendo a disco según llega (si se cierra el programa, lo grabado no se pierde)."""

    def __init__(self, path: str, rate: int, channels: int = 1, sample_bytes: int = 2):
        self.path, self.rate, self.channels, self.sample_bytes = path, rate, channels, sample_bytes
        self.frames = 0
        self._float = sample_bytes == 4
        self._w = wave.open(path, "wb")
        self._w.setnchannels(channels)
        self._w.setsampwidth(2 if self._float else sample_bytes)   # el WAV siempre en 16 bits (o 8)
        self._w.setframerate(rate)

    def write(self, pcm: bytes):
        if not pcm:
            return
        if self._float:                       # float32 → int16
            a = np.frombuffer(pcm[: len(pcm) // 4 * 4], np.float32)
            pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
            step = 2
        else:
            step = self.sample_bytes
        self._w.writeframesraw(pcm)
        self.frames += len(pcm) // (step * self.channels)

    def close(self) -> float:
        try:
            self._w.close()
        except Exception:  # noqa: BLE001
            pass
        return self.frames / float(self.rate or 1)
