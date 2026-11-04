"""
Prueba automática del núcleo: importar, editar, deshacer, guardar/abrir y exportar.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_core.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def make_media(folder: str) -> None:
    ff = media_tools.ffmpeg()
    os.makedirs(os.path.join(folder, "Gameplay", "Combat"), exist_ok=True)
    os.makedirs(os.path.join(folder, "Cinematics"), exist_ok=True)
    os.makedirs(os.path.join(folder, "Voz"), exist_ok=True)
    os.makedirs(os.path.join(folder, "Images"), exist_ok=True)
    jobs = [
        ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=6", "-f", "lavfi", "-i", "sine=f=330:d=6",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", os.path.join(folder, "Gameplay", "Combat", "pelea_01.mp4")],
        ["-f", "lavfi", "-i", "mandelbrot=s=1920x1080:r=30", "-t", "5",
         "-c:v", "libx264", os.path.join(folder, "Cinematics", "intro.mp4")],
        ["-f", "lavfi", "-i", "sine=f=220:d=12", "-af", "volume=0.5",
         os.path.join(folder, "Voz", "narracion.wav")],
        ["-f", "lavfi", "-i", "smptebars=s=800x600", "-frames:v", "1",
         os.path.join(folder, "Images", "captura.png")],
    ]
    for j in jobs:
        r = media_tools.run_quiet([ff, "-v", "error", "-y"] + j)
        assert r.returncode == 0, r.stderr.decode()


def wait_analysis(app, ctrl, timeout=60):
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.05)
    assert not ctrl.analyzing, "el análisis no terminó"


def main():
    app = QCoreApplication(sys.argv)
    # junto al programa (nunca en el TEMP de C:) y se borra al terminar
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
    os.makedirs(root, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="editoria_test_", dir=root)
    __import__("atexit").register(__import__("shutil").rmtree, tmp, True)
    lib = os.path.join(tmp, "Proyecto_Gears")
    make_media(lib)

    ctrl = ProjectController()
    msgs = []
    ctrl.message.connect(msgs.append)
    ids = ctrl.import_folder(lib)
    assert len(ids) == 4, ids
    wait_analysis(app, ctrl)

    by_name = {m.name: m for m in ctrl.project.media.values()}
    pelea = by_name["pelea_01.mp4"]
    assert pelea.category == "Gameplay" and pelea.tags == ["Combat"], (pelea.category, pelea.tags)
    assert abs(pelea.duration - 6) < 0.2 and pelea.width == 1280 and pelea.has_audio
    assert by_name["intro.mp4"].category == "Cinemáticas"
    assert by_name["narracion.wav"].category == "Narración"
    assert by_name["captura.png"].category == "Imágenes"
    assert pelea.id in ctrl.thumbs and by_name["narracion.wav"].id in ctrl.peaks
    print("✓ importación y clasificación")

    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    v2 = [t for t in p.tracks if t.kind == TRACK_VIDEO][0]
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([pelea.id, by_name["intro.mp4"].id], v1.id, 0.0)
    ctrl.add_media([by_name["narracion.wav"].id], a1.id, 0.0)
    ctrl.add_media([by_name["captura.png"].id], v2.id, 2.0)
    assert abs(p.duration() - 12) < 0.2, p.duration()

    # cortar y deshacer
    n = len(p.clips)
    ctrl.split(3.0)
    assert len(p.clips) == n + 4, len(p.clips)  # pelea (imagen y su sonido), narración e imagen se cortan en 3.0
    ctrl.undo_stack.undo()
    assert len(ctrl.project.clips) == n
    ctrl.undo_stack.redo()
    assert len(ctrl.project.clips) == n + 4
    ctrl.undo_stack.undo()
    print("✓ dividir / deshacer / rehacer")

    # bloqueo: no se puede tocar una pista bloqueada
    ctrl.set_track_props(a1.id, "Bloquear", locked=True)
    narr = p.clips_on(a1.id)[0]
    assert ctrl.delete_clips([narr.id]) is None and narr.id in p.clips
    assert any("bloqueada" in m for m in msgs)
    ctrl.set_track_props(a1.id, "Desbloquear", locked=False)
    print("✓ bloqueos respetados")

    # recortar y mover
    first = p.clips_on(v1.id)[0]
    ctrl.trim_clip(first.id, "left", 1.0)
    first = p.clips[first.id]
    assert abs(first.start - 1.0) < 1e-6 and abs(first.source_in - 1.0) < 1e-6
    ctrl.trim_clip(first.id, "left", -5)  # no puede ir antes del inicio del archivo
    assert abs(p.clips[first.id].start) < 1e-6
    print("✓ recortes")

    # guardar y abrir
    proj_path = os.path.join(tmp, "Proyecto.eia")
    assert ctrl.save(proj_path) and not ctrl.dirty
    v = ctrl.save_version()
    assert v.endswith("Proyecto_v01.eia"), v
    ctrl2 = ProjectController()
    ctrl2.load(proj_path)
    assert ctrl2.project.timeline_state() == ctrl.project.timeline_state()
    wait_analysis(app, ctrl2)
    print("✓ guardar / versiones / abrir")

    # exportar con CPU y con GPU AMD
    for codec, enc in [("h264", "cpu"), ("h264", "gpu"), ("hevc", "gpu")]:
        out = os.path.join(tmp, f"export_{codec}_{enc}.mp4")
        opts = ExportOptions(path=out, width=1280, height=720, fps=30, codec=codec, encoder=enc,
                             bitrate_mbps=8)
        args, total = build_command(ctrl.project, opts, media_tools.ffmpeg(),
                                    os.path.join(tmp, "filtro.txt"))
        t0 = time.time()
        r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
        if r.returncode != 0:
            print(open(os.path.join(tmp, "filtro.txt"), encoding="utf-8").read())
            print(r.stderr.decode(errors="replace")[-3000:])
            raise SystemExit(f"✗ exportación {codec}/{enc} falló")
        info = media_tools.probe(out)
        assert abs(info["duration"] - total) < 0.25, (info, total)
        assert info["width"] == 1280 and info["has_audio"]
        print(f"✓ exportación {codec}/{enc}: {info['duration']:.2f}s en {time.time() - t0:.1f}s")

    print("\nTODO OK — carpeta de prueba:", tmp)


if __name__ == "__main__":
    main()
