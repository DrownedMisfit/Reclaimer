"""
Tira de miniaturas de la línea de tiempo (como en Resolve): a lo largo de cada clip de video se ven sus
fotogramas, no solo el primero.

Por cada video se hace UNA imagen pequeña con sus fotogramas uno al lado del otro (ffmpeg «tile»), cada pocos
segundos (en videos largos, solo de los fotogramas clave: rápido). Se guarda en datos/cache/tira y se reutiliza.
Se prepara en segundo plano, de uno en uno; mientras tanto la línea de tiempo enseña la miniatura de siempre.
"""
from __future__ import annotations

import math
import os
import subprocess

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from ..core import media as media_tools
from ..core.paths import cache_dir

TILE_H = 54            # alto de cada fotograma de la tira (px)
MAX_TILES = 400        # como mucho, fotogramas por video
LONG = 10 * 60         # a partir de aquí, solo fotogramas clave


def interval_for(duration: float) -> float:
    return max(1.0, (duration or 0) / MAX_TILES)


_SPRITE: dict[tuple, str] = {}


def sprite_path(path: str, duration: float) -> str:
    key = (path, round(duration or 0, 2), os.environ.get("EDITORIA_DATOS", ""))
    got = _SPRITE.get(key)
    if got is None:
        got = _SPRITE[key] = str(cache_dir("tira") / f"{media_tools.cache_key(path)}_{interval_for(duration):.2f}.jpg")
    return got


def make_sprite(path: str, duration: float, cancelled=None) -> str | None:
    """Crea la tira (si no existe). Devuelve su ruta o None."""
    out = sprite_path(path, duration)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    step = interval_for(duration)
    n = max(1, int(math.ceil((duration or 1) / step)) + 1)
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y"]
    if (duration or 0) > LONG:
        args += ["-skip_frame", "nokey"]
    args += ["-i", path, "-an", "-sn", "-dn", "-vf",
             f"fps=1/{step:.4f},scale=-2:{TILE_H}:flags=fast_bilinear,tile={n}x1:padding=0:margin=0",
             "-frames:v", "1", "-q:v", "5", out + ".tmp.jpg"]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        while proc.poll() is None:
            try:
                proc.wait(0.25)
            except subprocess.TimeoutExpired:
                if cancelled is not None and cancelled():
                    proc.kill()
                    return None
    except OSError:
        return None
    tmp = out + ".tmp.jpg"
    if proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, out)
        return out
    if os.path.exists(tmp):
        os.remove(tmp)
    return None


class Filmstrips(QObject):
    """Tiras listas por archivo: get(media) → (pixmap, paso en s, ancho de cada fotograma) o None (y la pide)."""
    ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._strips: dict[str, tuple[QPixmap, float, float]] = {}
        self._failed: set[str] = set()
        self._queue: list = []
        self._job = None
        self._job_media = None

    def get(self, m):
        if m is None or not m.duration or m.duration <= 0:
            return None
        s = self._strips.get(m.id)
        if s is not None:
            return s
        if m.id in self._failed:
            return None
        if (self._job and self._job_media == m.id) or any(q.id == m.id for q in self._queue):
            return None              # ya se está haciendo: no se mira el disco en cada repintado
        path = sprite_path(m.path, m.duration)
        if os.path.exists(path):
            return self._load(m, path)
        self._queue.append(m)
        self._next()
        return None

    def _load(self, m, path):
        pix = QPixmap(path)
        step = interval_for(m.duration)
        n = max(1, int(math.ceil(m.duration / step)) + 1)
        if pix.isNull():
            self._failed.add(m.id)
            return None
        s = (pix, step, pix.width() / n)
        self._strips[m.id] = s
        return s

    def _next(self):
        if self._job is not None or not self._queue:
            return
        from .jobs import BackgroundJob
        m = self._queue.pop(0)
        self._job_media = m.id
        path, dur = m.path, m.duration

        def work(progress, cancelled):
            progress(0.0, "🎞 Miniaturas de la línea de tiempo…")
            return make_sprite(path, dur, cancelled)
        job = BackgroundJob(work)
        self._job = job

        def done(res, mid=m.id, med=m):
            self._job = None
            if res:
                self._load(med, res)
                self.ready.emit(mid)
            else:
                self._failed.add(mid)
            self._next()

        def failed(_msg, mid=m.id):
            self._job = None
            self._failed.add(mid)
            self._next()
        job.done.connect(done)
        job.failed.connect(failed)
        job.start()

    def forget(self):
        self._strips.clear()
        self._failed.clear()
