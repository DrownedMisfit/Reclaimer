"""
Renderizado más rápido (sin ventanas):
  · el ducking de la música con muchos tramos de voz ya no rompe el sonido (FFmpeg no acepta >32 sumandos seguidos);
  · el AAC de Windows (aac_mf) se detecta bien y se usa (hasta 320 kbps);
  · las imágenes quietas se decodifican UNA vez y el resultado es el mismo que con «-loop 1»;
  · exportando por trozos, el volumen final sale a −14 LUFS (medido una vez + ganancia + limitador).
Ejecutar:  .venv/Scripts/python.exe tests/test_render_speed.py <carpeta>
"""
from __future__ import annotations

import os
import re
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

NW = 0x08000000


def run(args):
    return subprocess.run(args, capture_output=True, text=True, creationflags=NW)


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_render_speed")
    os.makedirs(out, exist_ok=True)
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication(sys.argv)
    from editoria.core import audio_fx as AF
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, Project, new_id
    from editoria.export import ffmpeg_export as FE
    from editoria.export import parallel as P
    ff = M.ffmpeg()

    # ---------------------------------------------------------------- ducking con muchos tramos
    for n in (33, 200):
        iv = [(i * 2.0 + 1.0, i * 2.0 + 1.6) for i in range(n)]
        vol = AF.ffmpeg_duck_volume(iv, 0.0, n * 2.0 + 2, -12.0)
        r = run([ff, "-v", "error", "-f", "lavfi", "-i", f"sine=f=440:d={n * 2 + 2}", "-af", vol, "-f", "null", "-"])
        assert r.returncode == 0, (n, r.stderr[-300:])
    print("✓ ducking con 33 y 200 tramos de voz: FFmpeg lo acepta (antes fallaba el sonido desde ~33)")

    # ---------------------------------------------------------------- aac_mf
    FE._AAC_MF = None
    a = FE.aac_args(384)
    r = run([ff, "-hide_banner", "-encoders"])
    if " aac_mf " in r.stdout:
        assert a[:2] == ["-c:a", "aac_mf"] and a[-1] == "320k", a
        print("✓ el AAC de Windows se detecta y se usa (384 kbps → 320, su máximo)")
    else:
        assert a[:2] == ["-c:a", "aac"], a
        print("✓ sin AAC de Windows: el de FFmpeg (como antes)")

    # ---------------------------------------------------------------- imágenes una vez = mismo resultado
    png = os.path.join(out, "foto.png")
    assert run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=1", "-frames:v", "1",
                png]).returncode == 0
    vid = os.path.join(out, "fondo.mp4")
    assert run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=4", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid]).returncode == 0
    p = Project.new()
    p.width, p.height, p.fps = 320, 180, 30
    p.loudnorm = False
    vts = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    mv = MediaItem(new_id(), vid, "video", "fondo", duration=4.0, width=320, height=180, fps=30.0, probed=True)
    mi = MediaItem(new_id(), png, "image", "foto", duration=0.0, width=1280, height=720, probed=True)
    p.media[mv.id], p.media[mi.id] = mv, mi
    p.clips[new_id()] = Clip(new_id(), mv.id, vts[-1].id, 0.0, 0.0, 4.0)
    ci = Clip(new_id(), mi.id, vts[0].id, 0.5, 0.0, 3.0)
    ci.layout = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
    ci.zoom_kf = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5}, {"t": 3.0, "z": 1.4, "x": 0.5, "y": 0.5}]
    p.clips[ci.id] = ci
    salidas = {}
    for una_vez in (True, False):
        FE.STILLS_ONCE = una_vez
        o = os.path.join(out, f"img_{'nuevo' if una_vez else 'antes'}.mkv")
        opts = FE.ExportOptions(path=o, width=320, height=180, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False)
        args, _t = FE.build_command(p, opts, ff, os.path.join(out, f"f{int(una_vez)}.txt"))
        if una_vez:
            assert "-loop" not in args, "la imagen ya no entra con -loop 1"
        r = run(args)
        assert r.returncode == 0, r.stderr[-800:]
        salidas[una_vez] = o
    FE.STILLS_ONCE = True
    r = run([ff, "-hide_banner", "-i", salidas[True], "-i", salidas[False], "-lavfi", "[0:v][1:v]psnr", "-f", "null",
             "-"])
    m = re.search(r"average:(\S+)", r.stderr)
    assert m, r.stderr[-500:]
    psnr = float("inf") if m.group(1) == "inf" else float(m.group(1))
    i1, i2 = M.probe(salidas[True]), M.probe(salidas[False])
    assert abs(i1["duration"] - i2["duration"]) < 0.05, (i1, i2)
    assert psnr >= 45, psnr
    print(f"✓ imágenes decodificadas una vez: mismo video que con «-loop 1» (PSNR {psnr} dB, misma duración)")

    # …y fotograma a fotograma a 60 y 29,97 FPS, con duraciones de cualquier tipo (la revisión de Fable vio que, sin la
    # base de tiempo de la imagen, a 60 FPS acababa un fotograma antes y se veía la capa de abajo)
    for fps in (60.0, 29.97):
        r2 = Project.new()
        r2.width, r2.height, r2.fps = 320, 180, fps
        r2.loudnorm = False
        vt2 = [t for t in r2.tracks if t.kind == TRACK_VIDEO]
        r2.media[mv.id], r2.media[mi.id] = mv, mi
        r2.clips[new_id()] = Clip(new_id(), mv.id, vt2[-1].id, 0.0, 0.0, 4.0)
        t = 0.1
        for d in (0.6, 1.0333, 0.35, 0.8167):
            c2 = Clip(new_id(), mi.id, vt2[0].id, round(t, 4), 0.0, d)
            c2.layout = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
            r2.clips[c2.id] = c2
            t += d + 0.15
        md5 = {}
        for una_vez in (True, False):
            FE.STILLS_ONCE = una_vez
            o = os.path.join(out, f"img60_{int(una_vez)}.mkv")
            opts = FE.ExportOptions(path=o, width=320, height=180, fps=fps, encoder="cpu", bitrate_mbps=4,
                                    loudnorm=False)
            args, _t = FE.build_command(r2, opts, ff, os.path.join(out, f"g{int(una_vez)}.txt"))
            rr = run(args)
            assert rr.returncode == 0, rr.stderr[-600:]
            fm = run([ff, "-v", "error", "-i", o, "-map", "0:v", "-f", "framemd5", "-"])
            md5[una_vez] = [ln.split(",")[-1].strip() for ln in fm.stdout.splitlines() if ln and not ln.startswith("#")]
        FE.STILLS_ONCE = True
        assert len(md5[True]) == len(md5[False]), (fps, len(md5[True]), len(md5[False]))
        dif = sum(1 for a_, b_ in zip(md5[True], md5[False]) if a_ != b_)
        assert dif == 0, (fps, dif)
        print(f"  ✓ a {fps:g} FPS: los {len(md5[True])} fotogramas, idénticos a los de «-loop 1»")

    # ---------------------------------------------------------------- −14 LUFS por trozos
    nar = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    q = Project.new()
    q.width, q.height, q.fps = 320, 180, 30
    q.loudnorm = True
    v1 = [t for t in q.tracks if t.kind == TRACK_VIDEO][-1]
    a1 = next(t for t in q.tracks if t.kind == TRACK_AUDIO)
    colores = []
    for i, col in enumerate(("red", "green", "blue", "yellow")):
        path = os.path.join(out, f"{col}.mp4")
        assert run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180:r=30:d=8", "-c:v",
                    "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path]).returncode == 0
        mm = MediaItem(new_id(), path, "video", col, duration=8.0, width=320, height=180, fps=30.0, probed=True)
        q.media[mm.id] = mm
        q.clips[new_id()] = Clip(new_id(), mm.id, v1.id, i * 7.0, 0.5, 7.0)
        colores.append(mm)
    ma = MediaItem(new_id(), nar, "audio", "narración", duration=28.0, has_audio=True, channels=1, probed=True)
    q.media[ma.id] = ma
    q.clips[new_id()] = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 28.0, volume=0.3)   # (bajita: hay que subirla)
    total = q.duration()
    o = os.path.join(out, "trozos.mp4")
    opts = FE.ExportOptions(path=o, width=320, height=180, fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=True)
    chunks = P.plan(q, opts, total)
    assert chunks and len(chunks) >= 2, chunks
    P.ParallelExport(q, opts, ff, os.path.join(out, "trabajo"), chunks, total).run()
    lufs = P.measure_lufs(ff, o)
    assert lufs is not None and abs(lufs - (-14.0)) <= 1.0, lufs
    r = run([ff, "-hide_banner", "-i", o, "-af", "ebur128=peak=sample", "-f", "null", "-"])
    pk = re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", r.stderr)
    assert pk and float(pk[-1]) <= -1.5, pk[-3:]
    print(f"✓ por trozos: {lufs:.1f} LUFS (objetivo −14) y pico {float(pk[-1]):.1f} dBFS, sin saturar")
    print("TODO OK")


if __name__ == "__main__":
    main()
