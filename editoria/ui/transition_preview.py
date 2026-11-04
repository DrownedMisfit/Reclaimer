"""
«▶ Ver la transición»: el visor muestra un clip por pista (solo puede aproximar las transiciones con un
fundido), así que aquí se renderiza en pequeño el tramo exacto alrededor del corte (unos 3 s) y se
reproduce en bucle. Tarda pocos segundos y no toca tus archivos.
"""
from __future__ import annotations

import os
import subprocess
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ..core import media as media_tools
from ..core.paths import cache_dir
from ..core.project_tools import slice_project
from ..export.ffmpeg_export import ExportOptions, build_command

SPAN = 1.6     # segundos antes y después del corte


def render_cut(project, t: float, width: int = 480) -> str:
    """Renderiza [t-SPAN, t+SPAN] a un mp4 pequeño y devuelve su ruta."""
    a, b = max(0.0, t - SPAN), min(project.duration(), t + SPAN)
    part = slice_project(project, a, b)
    h = max(2, int(round(width * project.height / project.width / 2)) * 2)
    out_dir = str(cache_dir("transiciones"))
    out = os.path.join(out_dir, f"trans_{uuid.uuid4().hex[:8]}.mp4")
    opts = ExportOptions(path=out, width=width, height=h, fps=project.fps, encoder="cpu",
                         bitrate_mbps=3, subtitles=False, loudnorm=False)
    args, _total = build_command(part, opts, media_tools.ffmpeg(), os.path.join(out_dir, "filtro.txt"))
    r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("No se pudo preparar la vista previa de la transición.")
    return out


def decode_frames(path: str, max_frames: int = 300) -> tuple[list[QImage], float]:
    """Todos los fotogramas del vídeo pequeño (RGB) y sus fotogramas por segundo."""
    info = media_tools.probe(path)
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    fps = float(info.get("fps") or 30.0) or 30.0
    if not w or not h:
        return [], fps
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-i", path, "-frames:v",
                               str(max_frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], timeout=60)
    n = len(r.stdout) // (w * h * 3)
    out = []
    for i in range(n):
        chunk = r.stdout[i * w * h * 3:(i + 1) * w * h * 3]
        out.append(QImage(chunk, w, h, 3 * w, QImage.Format_RGB888).copy())
    return out, fps


class TransitionPreview(QDialog):
    """Repite en bucle el tramo renderizado. Se reproducen los fotogramas directamente (sin el reproductor
    de vídeo de Qt, que podía dejar colgado el programa al cerrar esta ventana mientras el visor también
    reproducía)."""

    def __init__(self, path: str, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("▶ " + title)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.video = QLabel()
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setMinimumSize(320, 180)
        self.video.setStyleSheet("background: #000;")
        lay.addWidget(self.video, 1)
        info = QLabel("Así queda exactamente al exportar (se repite en bucle, sin sonido).")
        info.setObjectName("dim")
        lay.addWidget(info)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        lay.addWidget(close)
        self.frames, fps = decode_frames(path)
        self.i = 0
        self.timer = QTimer(self)
        self.timer.setInterval(max(15, int(round(1000 / fps))))
        self.timer.timeout.connect(self._next)
        if self.frames:
            self._next()
            self.timer.start()
        else:
            self.video.setText("No se pudo leer la vista previa.")

    def _next(self):
        if not self.frames:
            return
        img = self.frames[self.i % len(self.frames)]
        self.i += 1
        self.video.setPixmap(QPixmap.fromImage(img).scaled(self.video.size(), Qt.KeepAspectRatio,
                                                           Qt.SmoothTransformation))

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
