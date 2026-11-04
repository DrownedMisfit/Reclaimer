"""
⧉ Clip compuesto «cocinado»: varios clips (con sus efectos, color, textos, transiciones y sonido) se
renderizan a UN video y lo sustituyen en la línea de tiempo → el visor reproduce un solo archivo ligero
(menos trabajo = más fluidez). Es reversible: «Deshacer clip compuesto» devuelve los clips originales.

  sub_project(p, ids) → (proyecto con solo esos clips, a, b)
  render(q, out, progress, cancelled) → out (H.264 de alta calidad, con el audio mezclado)
Los archivos van a datos/compuestos (no es caché: el proyecto los usa).
"""
from __future__ import annotations

import os
import subprocess

from . import media as media_tools
from .model import Project
from .paths import app_data_dir
from .project_tools import slice_project


def out_dir() -> str:
    d = app_data_dir() / "compuestos"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def with_partners(p: Project, ids) -> set[str]:
    """Los clips elegidos más su sonido/imagen vinculados."""
    ids = [getattr(i, "id", i) for i in ids]          # vale tanto la lista de ids como la de clips
    out = set(i for i in ids if i in p.clips)
    for i in list(out):
        c = p.clips[i]
        if c.link:
            out |= {o.id for o in p.clips.values() if o.link == c.link}
    return out


def sub_project(p: Project, ids) -> tuple[Project, float, float]:
    keep = with_partners(p, ids)
    if not keep:
        raise ValueError("Selecciona los clips que quieres juntar.")
    a = min(p.clips[i].start for i in keep)
    b = max(p.clips[i].end for i in keep)
    q = Project.from_dict(p.to_dict())
    q.clips = {i: c for i, c in q.clips.items() if i in keep}
    q.subtitles.enabled = False          # los subtítulos se ponen al exportar el video final
    q.loudnorm = False
    q.mark_in = q.mark_out = None
    return slice_project(q, a, b), a, b


def render(q: Project, out: str, progress=None, cancelled=None) -> str:
    """Cocina el compuesto. Rápido (lo pidió el usuario: «tarda demasiado»): con la tarjeta gráfica si la hay y, si
    es largo, en trozos a la vez (como «Exportar»: todos los núcleos). Si la tarjeta falla, se repite con el
    procesador."""
    from . import proxies
    gpu = proxies.hw_encoder()
    try:
        return _render(q, out, progress, cancelled, "gpu" if gpu else "cpu")
    except RuntimeError:
        if not gpu or (cancelled is not None and cancelled()):
            raise
        return _render(q, out, progress, cancelled, "cpu")


def _render(q: Project, out: str, progress, cancelled, encoder: str) -> str:
    from ..export import parallel
    from ..export.ffmpeg_export import ExportOptions, build_command
    opts = ExportOptions(path=out, width=q.width // 2 * 2, height=q.height // 2 * 2, fps=q.fps, codec="h264",
                         encoder=encoder, bitrate_mbps=40.0, subtitles=False, loudnorm=False)
    total = q.duration()
    chunks = parallel.plan(q, opts, total)
    if chunks:
        return _render_parallel(q, opts, out, total, chunks, progress, cancelled)
    script = out + ".filtro.txt"
    args, total = build_command(q, opts, media_tools.ffmpeg(), script)
    if "-progress" not in args:
        args = args[:1] + ["-progress", "pipe:1", "-nostats"] + args[1:]
    log_path = out + ".log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")      # (si nadie lee el canal, FFmpeg se para)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL,
                            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for line in proc.stdout:
            if cancelled is not None and cancelled():
                proc.kill()
                break
            if line.startswith("out_time_us=") and total > 0 and progress is not None:
                try:
                    progress(min(0.999, int(line.split("=", 1)[1]) / 1e6 / total))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        log.close()
        if os.path.exists(script):
            os.remove(script)
    _check_cancel(out, cancelled)
    err = ""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            err = f.read()[-400:]
        os.remove(log_path)
    except OSError:
        pass
    if proc.returncode != 0 or not os.path.exists(out):
        if os.path.exists(out):
            os.remove(out)
        raise RuntimeError("No se pudo cocinar el clip compuesto. " + err)
    return out


def _check_cancel(out: str, cancelled):
    if cancelled is not None and cancelled():
        if os.path.exists(out):
            os.remove(out)
        from ..ai.base import Cancelled
        raise Cancelled()


def _render_parallel(q: Project, opts, out: str, total: float, chunks, progress, cancelled) -> str:
    """En trozos a la vez (export/parallel.py); este hilo vigila el progreso y si se cancela."""
    import threading
    from ..export import parallel
    job = parallel.ParallelExport(q, opts, media_tools.ffmpeg(), out + ".trozos", chunks, total)
    res: dict = {}

    def work():
        try:
            res["path"] = job.run()
        except Exception as exc:  # noqa: BLE001 - se informa abajo
            res["error"] = exc
    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.3)
        if cancelled is not None and cancelled():
            job.stop()
        elif progress is not None:
            progress(min(0.999, job.fraction()))
    _check_cancel(out, cancelled)
    if "error" in res or not os.path.exists(out):
        if os.path.exists(out):
            os.remove(out)
        raise RuntimeError("No se pudo cocinar el clip compuesto. " + " ".join(job.log[-6:])[-400:])
    return out
