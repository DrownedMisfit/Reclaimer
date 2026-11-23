"""
📍 PRUEBA de los capítulos dentro del MP4 (fase 5): un proyecto corto con marcadores con nombre se exporta (de una vez
y en trozos en paralelo) con «Capítulos dentro del video» y ffprobe encuentra los capítulos: el primero en 0:00 (las
reglas de YouTube), los títulos con caracteres raros intactos y el final del último en el final del video. Sin la
casilla, el MP4 no lleva capítulos. Datos aislados, sin ventanas.
Ejecutar:  .venv/Scripts/python.exe tests/test_capitulos_mp4.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")


_aislar_datos()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def capitulos(path: str) -> list[dict]:
    from editoria.core import media as M
    r = subprocess.run([M.ffprobe(), "-v", "error", "-show_chapters", "-print_format", "json", path],
                       capture_output=True)
    return json.loads(r.stdout or b"{}").get("chapters", [])


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "capitulos_mp4")
    os.makedirs(out, exist_ok=True)
    from dataclasses import replace

    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, Marker, Project, new_id
    from editoria.export import parallel as P
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ff = M.ffmpeg()
    vid = os.path.join(out, "v.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=36",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    wav = os.path.join(out, "tono.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=36", wav], check=True)
    p = Project.new()
    p.width, p.height, p.fps = 320, 180, 30
    p.loudnorm = False
    v1 = next(t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    mv = MediaItem(new_id(), vid, "video", "v", duration=36.0, width=320, height=180, fps=30.0, probed=True)
    ma = MediaItem(new_id(), wav, "audio", "tono", duration=36.0, has_audio=True, channels=1, probed=True)
    p.media[mv.id], p.media[ma.id] = mv, ma
    for k in range(3):                                 # tres clips seguidos (la exportación en trozos puede partir)
        c = Clip(new_id(), mv.id, v1.id, k * 12.0, k * 12.0, 12.0)
        p.clips[c.id] = c
    p.clips[new_id()] = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 36.0)
    p.markers = [Marker(new_id(), 3.0, "Empieza; el #1 = bueno"), Marker(new_id(), 14.0, "Mitad"),
                 Marker(new_id(), 26.0, "Final"),
                 Marker(new_id(), 20.0, "Marcador 4"),                      # (nombre por defecto: no es capítulo)
                 Marker(new_id(), 22.0, "NG", color="#e5484d"),             # (marca de OBS: un fallo, no capítulo)
                 Marker(new_id(), 32.0, "Ya revisado", resuelto=True)]      # (resuelto: fuera)
    total = p.duration()
    from editoria.core import chapters as CH
    assert CH.validos(p, total) == 3, CH.candidates(p)

    o1 = os.path.join(out, "con_capitulos.mp4")
    opts = ExportOptions(path=o1, width=320, height=180, fps=30, encoder="cpu", bitrate_mbps=2, loudnorm=False,
                         chapters=True)
    args, _t = build_command(p, opts, ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
    ch = capitulos(o1)
    print("capítulos:", [(round(float(c["start_time"]), 2), round(float(c["end_time"]), 2), c["tags"]["title"])
                         for c in ch])
    assert [c["tags"]["title"] for c in ch] == ["Empieza; el #1 = bueno", "Mitad", "Final"], ch
    assert abs(float(ch[0]["start_time"])) < 0.01, "el primero en 0:00 (YouTube)"
    assert abs(float(ch[1]["start_time"]) - 14.0) < 0.01 and abs(float(ch[2]["start_time"]) - 26.0) < 0.01, ch
    assert abs(float(ch[-1]["end_time"]) - total) < 0.1, ch
    print("✓ exportando de una vez: 3 capítulos, con sus títulos y sus tiempos")

    o2 = os.path.join(out, "en_trozos.mp4")
    o2opts = replace(opts, path=o2)
    chunks = P.plan(p, o2opts, total)
    assert chunks and len(chunks) >= 2, chunks
    work = os.path.join(out, "trabajo")
    P.ParallelExport(p, o2opts, ff, work, chunks, total).run()
    ch2 = capitulos(o2)
    assert [(c["tags"]["title"], round(float(c["start_time"]), 2)) for c in ch2] == \
        [(c["tags"]["title"], round(float(c["start_time"]), 2)) for c in ch], ch2
    assert M.probe(o2)["has_audio"]
    print(f"✓ exportando en {len(chunks)} trozos: los mismos capítulos")

    o3 = os.path.join(out, "sin_capitulos.mp4")
    args, _t = build_command(p, replace(opts, path=o3, chapters=False), ff, os.path.join(out, "f3.txt"))
    assert "-map_chapters" not in args
    r = subprocess.run(args, capture_output=True)
    assert r.returncode == 0 and capitulos(o3) == [], "sin la casilla, sin capítulos"
    p.markers = []
    args, _t = build_command(p, replace(opts, path=o3), ff, os.path.join(out, "f4.txt"))
    assert "-map_chapters" not in args, "sin marcadores ni temas, no se añade nada"
    print("✓ sin la casilla (o sin marcadores) el MP4 no lleva capítulos")
    meta = open(os.path.join(out, "capitulos.ffmeta"), "rb").read() if os.path.exists(
        os.path.join(out, "capitulos.ffmeta")) else b""
    assert b"\r\n" not in meta, "ffmetadata con finales de línea \\n"
    assert CH._esc("uno\r\ndos") == "uno dos", CH._esc("uno\r\ndos")
    print("TODO OK")


if __name__ == "__main__":
    main()
