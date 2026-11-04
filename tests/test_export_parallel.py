"""
Prueba de EXPORTAR EN PARALELO (por trozos a la vez, cortando por los cortes del montaje):
  · solo corta donde no hay nada a medias (ni transición ni texto que cruce el corte);
  · el resultado dura lo mismo, tiene el sonido entero y cada momento muestra lo mismo que exportando de una vez;
  · borra sus archivos de trabajo.
Ejecutar:  .venv/Scripts/python.exe tests/test_export_parallel.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication(sys.argv)      # los textos se dibujan con Qt (como dentro del programa)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO, Clip, MediaItem, Project, Track, new_id
    from editoria.export import parallel as P
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ff = M.ffmpeg()
    colors = ["red", "green", "blue", "yellow", "magenta", "cyan", "white", "orange", "purple", "gray"]
    p = Project.new() if hasattr(Project, "new") else Project()
    p.width, p.height, p.fps = 320, 180, 30
    p.loudnorm = False
    v1 = next(t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    for i, col in enumerate(colors):
        path = os.path.join(out, f"{col}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180:r=30:d=4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], check=True)
        m = MediaItem(new_id(), path, "video", col, duration=4.0, width=320, height=180, fps=30.0, has_audio=False, probed=True)
        p.media[m.id] = m
        c = Clip(new_id(), m.id, v1.id, i * 3.0, 0.5, 3.0)
        if i == 4:      # transición en el corte de 12 s: ahí no se puede partir
            c.fx = {"trans": {"type": "fade", "dur": 0.6}}
        p.clips[c.id] = c
    wav = os.path.join(out, "tono.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=30", wav], check=True)
    am = MediaItem(new_id(), wav, "audio", "tono", duration=30.0, has_audio=True, channels=1, probed=True)
    p.media[am.id] = am
    p.clips[new_id()] = Clip(new_id(), am.id, a1.id, 0.0, 0.0, 30.0)
    tt = Track(new_id(), TRACK_TEXT, "T")
    p.tracks.insert(0, tt)
    from editoria.core.model import TEXT_DEFAULTS
    tc = Clip(new_id(), "", tt.id, 17.0, 0.0, 2.0, text=dict(TEXT_DEFAULTS, content="hola"))   # cruza el corte de 18 s
    p.clips[tc.id] = tc
    total = p.duration()
    cuts = P.cut_points(p, total, 30.0)
    assert 12.0 not in cuts and 18.0 not in cuts and 6.0 in cuts and 21.0 in cuts, cuts
    print(f"✓ solo corta donde no hay nada a medias (no en la transición ni en el texto): {cuts}")

    o1 = os.path.join(out, "una_vez.mp4")
    o2 = os.path.join(out, "trozos.mp4")
    opts = ExportOptions(path=o1, width=320, height=180, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
    args, _t = build_command(p, opts, ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
    from dataclasses import replace
    o2opts = replace(opts, path=o2)
    chunks = P.plan(p, o2opts, total)
    assert chunks and len(chunks) >= 2, chunks
    work = os.path.join(out, "trabajo")
    P.ParallelExport(p, o2opts, ff, work, chunks, total).run()
    assert not os.path.exists(work), "borra sus archivos de trabajo"
    i1, i2 = M.probe(o1), M.probe(o2)
    assert abs(i1["duration"] - i2["duration"]) < 0.1 and abs(i2["duration"] - total) < 0.1, (i1, i2)
    assert i2["has_audio"], i2
    for t in (1.0, 5.9, 6.1, 12.0, 17.5, 18.2, 22.0, 29.0):
        f1 = M.frame_rgb(o1, t, 160).astype(int)
        f2 = M.frame_rgb(o2, t, 160).astype(int)
        d = abs(f1 - f2).mean()
        assert d < 12, (t, d)
    print(f"✓ {len(chunks)} trozos a la vez: misma duración ({i2['duration']:.2f} s), con sonido, y cada momento "
          "igual que exportando de una vez")
    # el sonido sigue entero (sin saltos entre trozos)
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-i", o2, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True)
    import numpy as np
    a = np.frombuffer(r.stdout, np.int16).astype(float)
    win = a[: len(a) // 800 * 800].reshape(-1, 800)
    rms = np.sqrt((win ** 2).mean(axis=1))
    assert rms[2:-2].min() > 0.3 * np.median(rms), "el tono suena todo el rato"
    print("✓ el sonido va entero, sin cortes entre trozos")
    print("TODO OK")


if __name__ == "__main__":
    main()
