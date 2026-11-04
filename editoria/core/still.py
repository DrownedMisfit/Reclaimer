"""
🖼 Exportar el fotograma actual como imagen PNG, tal como saldrá en el video (efectos, textos, capas y subtítulos):
se renderiza ese instante con el mismo motor que la exportación, a la resolución del proyecto.
"""
from __future__ import annotations

import os
import subprocess

from .model import Project
from .project_tools import slice_project


def render_frame(project: Project, t: float, out_png: str, ffmpeg: str) -> str:
    from ..export.ffmpeg_export import ExportOptions, build_command
    fps = float(project.fps or 30.0)
    total = project.duration()
    if total <= 0:
        raise ValueError("La línea de tiempo está vacía.")
    t = max(0.0, min(float(t), total - 1.0 / fps))
    # Un margen de 1 s a cada lado: si se renderizara solo ese instante, los textos y los clips «empezarían» ahí
    # y saldrían a media aparición (fundido de entrada transparente). Luego se saca justo el fotograma de t.
    a = max(0.0, t - 1.0)
    part = slice_project(project, a, min(total, t + 1.0))
    base = os.path.splitext(out_png)[0]
    tmp, script = base + ".tmp.mp4", base + ".filtro.txt"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        opts = ExportOptions(path=tmp, width=project.width, height=project.height, fps=fps, encoder="cpu",
                             bitrate_mbps=80, loudnorm=False, video_only=True, duration=part.duration())
        args, _total = build_command(part, opts, ffmpeg, script)
        r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=flags)
        if r.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError("No se pudo preparar el fotograma: " + (r.stderr or "")[-300:])
        r = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", tmp, "-ss", f"{t - a:.4f}",
                            "-frames:v", "1", out_png],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=flags)
        if r.returncode != 0 or not os.path.exists(out_png):
            raise RuntimeError("No se pudo guardar la imagen: " + (r.stderr or "")[-300:])
        return out_png
    finally:
        for f in (tmp, script):
            try:
                os.remove(f)
            except OSError:
                pass
