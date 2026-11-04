"""
Exportar MÁS RÁPIDO: el video se parte en trozos por los cortes del montaje y cada trozo se hace en su propio
FFmpeg, varios a la vez (los filtros de FFmpeg trabajan casi en un solo núcleo; así se usan todos). El sonido se
hace una sola vez, entero (sin saltos entre trozos). Al final se juntan los trozos SIN volver a comprimir.

Solo se corta donde no hay nada a medias: ningún clip de imagen ni texto cruza el corte y no hay transición
justo ahí. Si no hay cortes así (o el video es corto), se exporta de la forma normal, de una vez.

  plan(project, opts, total) -> [(desde, hasta), …] o None
  ParallelExport(project, opts, ffmpeg, work_dir).run(progress, cancelled)   (en un hilo)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from ..core.model import TRACK_AUDIO, Project

FILTER_THREADS = max(1, (os.cpu_count() or 4) // 8)   # (8 núcleos lógicos por trozo a la vez → 2 en un 16)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
ABOVE_NORMAL = getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)
MIN_TOTAL = 20.0      # videos más cortos: de una vez (no compensa)
MIN_CHUNK = 4.0


def workers(low_priority: bool = False) -> int:
    """Trozos a la vez. Con «Dejar libre el PC», la mitad (medido: 4 a la vez tardan casi lo mismo que 8, porque el
    procesador ya va lleno; así queda sitio para lo que estés haciendo)."""
    n = os.cpu_count() or 4
    w = max(2, min(8, n // 2))
    return max(2, w // 2) if low_priority else w


def lower_priority(pid: int) -> None:
    """Pone un proceso ya en marcha en prioridad baja (Windows; en otro sistema no hace nada)."""
    if os.name != "nt" or not pid:
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x0200, False, int(pid))      # PROCESS_SET_INFORMATION
        if h:
            k32.SetPriorityClass(h, 0x4000)                # BELOW_NORMAL_PRIORITY_CLASS
            k32.CloseHandle(h)
    except (OSError, AttributeError):
        pass


def cut_points(project: Project, total: float, fps: float) -> list[float]:
    """Instantes (en la rejilla de fotogramas) donde se puede partir sin dejar nada a medias."""
    from ..core import transitions
    vis = [c for tr in project.tracks if tr.kind != TRACK_AUDIO and not tr.hidden
           for c in project.clips_on(tr.id) if c.enabled]
    if not vis:
        return []
    half = 0.6 / fps
    bad = set()
    for tr in project.tracks:
        if tr.kind == TRACK_AUDIO:
            continue
        for left, _right, t in transitions.pairs(project, tr.id):
            bad.add(round(left.end * fps))
    cand = sorted({round(c.start * fps) for c in vis} | {round(c.end * fps) for c in vis})
    out = []
    for f in cand:
        t = f / fps
        if t < MIN_CHUNK or t > total - MIN_CHUNK or f in bad or f - 1 in bad or f + 1 in bad:
            continue
        if any(c.start < t - half and c.end > t + half for c in vis):
            continue
        out.append(t)
    return out


def plan(project: Project, opts, total: float) -> list[tuple[float, float]] | None:
    if opts.audio_only or total < MIN_TOTAL:
        return None
    fps = float(opts.fps)
    cuts = cut_points(project, total, fps)
    if not cuts:
        return None
    n = min(len(cuts) + 1, workers() * 3, max(2, int(total // MIN_CHUNK)))
    chosen: list[float] = []
    for i in range(1, n):
        want = total * i / n
        t = min(cuts, key=lambda x: abs(x - want))
        if (not chosen or t - chosen[-1] >= MIN_CHUNK) and total - t >= MIN_CHUNK:
            chosen.append(t)
    chosen = sorted(set(chosen))
    if not chosen:
        return None
    end = round(total * fps) / fps
    edges = [0.0] + chosen + [end]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


class ParallelExport:
    def __init__(self, project: Project, opts, ffmpeg: str, work_dir: str, chunks: list[tuple[float, float]],
                 total: float):
        self.project, self.opts, self.ffmpeg, self.dir = project, opts, ffmpeg, os.path.abspath(work_dir)
        self.chunks, self.total = chunks, total
        self.done_s = [0.0] * len(chunks)     # segundos hechos de cada trozo
        self.audio_f = 0.0
        self.procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()
        self.cancel = False
        self.log: list[str] = []

    def fraction(self) -> float:
        v = sum(self.done_s) / max(1e-3, self.total)
        return min(1.0, 0.94 * v + 0.04 * self.audio_f)

    def stop(self):
        self.cancel = True
        with self._lock:
            for p in self.procs:
                try:
                    p.kill()
                except OSError:
                    pass

    def _run(self, args, on_time, urgent: bool = False) -> int:
        with self._lock:
            if self.cancel:
                return -1
            logf = open(os.path.join(self.dir, f"log_{len(self.procs)}.txt"), "w", encoding="utf-8",
                        errors="replace")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (BELOW_NORMAL if self.opts.low_priority else
                                                                  ABOVE_NORMAL if urgent else 0)
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=logf, text=True, creationflags=flags)
            self.procs.append(p)
        for line in p.stdout:
            if line.startswith("out_time_us="):
                try:
                    on_time(int(line.split("=", 1)[1]) / 1e6)
                except ValueError:
                    pass
        code = p.wait()
        logf.close()
        if code != 0 and not self.cancel:
            try:
                with open(logf.name, encoding="utf-8", errors="replace") as f:
                    self.log += f.read().splitlines()[-40:]
            except OSError:
                pass
        return code

    def _chunk(self, i: int) -> str:
        from ..core.project_tools import slice_project
        from .ffmpeg_export import build_command
        a, b = self.chunks[i]
        d = os.path.join(self.dir, f"trozo_{i:03d}")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(self.dir, f"trozo_{i:03d}.mp4")
        q = slice_project(self.project, a, b)
        args, _t = build_command(q, replace(self.opts, path=out, video_only=True, duration=b - a, loudnorm=False),
                                 self.ffmpeg, os.path.join(d, "filtro.txt"))
        # Varios trozos a la vez: cada FFmpeg con pocos hilos (si cada uno intenta usar TODOS, se estorban)
        th = str(FILTER_THREADS)
        args = args[:1] + ["-filter_complex_threads", th, "-filter_threads", th] + args[1:]

        def on_time(s, i=i, dur=b - a):
            self.done_s[i] = min(dur, s)
        if self._run(args, on_time) != 0:
            raise RuntimeError("cancelado" if self.cancel else f"falló el trozo {i + 1}")
        self.done_s[i] = b - a
        return out

    def _audio(self) -> str:
        """El sonido entero, ya comprimido (AAC) para juntarlo al final sin hacer nada más. Va un poco por delante de
        los trozos de video (prioridad algo más alta): solo es un proceso y, compitiendo con 8 trozos, tardaba 5× más
        que solo (medido: 2,6 s → 13,7 s); al final comprimir el AAC tardaba 7 s con todo lo demás ya terminado."""
        from .ffmpeg_export import TARGETS, aac_args, build_command
        d = os.path.join(self.dir, "audio")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(self.dir, "audio.wav")
        args, _t = build_command(self.project, replace(self.opts, path=out, audio_only=True, duration=self.total),
                                 self.ffmpeg, os.path.join(d, "filtro.txt"))

        def on_time(s):
            self.audio_f = min(1.0, s / max(1e-3, self.total))
        if self._run(args, on_time, urgent=True) != 0:
            raise RuntimeError("cancelado" if self.cancel else "falló el sonido")
        o = self.opts
        audio_k = TARGETS[o.target]["audio"] if o.target in TARGETS else o.audio_kbps
        m4a = os.path.join(self.dir, "audio.m4a")
        if self._run([self.ffmpeg, "-nostdin", "-y", "-hide_banner", "-nostats", "-progress", "pipe:1", "-i", out]
                     + aac_args(audio_k) + ["-ar", "48000", "-ac", "2", m4a], lambda s: None, urgent=True) != 0:
            raise RuntimeError("cancelado" if self.cancel else "falló el sonido")
        self.audio_f = 1.0
        return m4a

    def run(self) -> str:
        """Hace todo (bloquea: llamar desde un hilo). Devuelve la ruta final o lanza RuntimeError."""
        os.makedirs(self.dir, exist_ok=True)
        try:
            with ThreadPoolExecutor(max_workers=workers(self.opts.low_priority)) as pool:
                fa = pool.submit(self._audio)
                futs = [pool.submit(self._chunk, i) for i in range(len(self.chunks))]
                parts = []
                for f in futs:
                    try:
                        parts.append(f.result())
                    except Exception:
                        self.stop()
                        raise
                wav = fa.result()
            if self.cancel:
                raise RuntimeError("cancelado")
            lst = os.path.join(self.dir, "trozos.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for p_ in parts:
                    f.write("file '" + p_.replace("\\", "/").replace("'", "'\\''") + "'\n")
            o = self.opts
            args = [self.ffmpeg, "-nostdin", "-y", "-hide_banner", "-nostats", "-progress", "pipe:1",
                    "-f", "concat", "-safe", "0", "-i", lst, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
                    "-c", "copy", "-t", f"{self.total:.3f}", "-movflags", "+faststart", o.path]
            if self._run(args, lambda s: None) != 0:
                raise RuntimeError("cancelado" if self.cancel else "no se pudieron juntar los trozos")
            return o.path
        finally:
            for _ in range(20):         # Windows suelta los archivos un instante después
                try:
                    shutil.rmtree(self.dir)
                    break
                except OSError:
                    time.sleep(0.1)
