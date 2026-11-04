"""
Prueba de la tanda 1 (edición tipo Resolve): velocidad (lento/rápido), reversa, congelar imagen,
entrada/salida (I/O), quitar el tramo marcado, exportar solo el tramo y J/K/L.
La exportación se comprueba midiendo el brillo: el video de prueba se aclara con el tiempo
(brillo = 24 × segundo), así se sabe qué segundo del archivo se ve en cada momento.
Ejecutar:  .venv/Scripts/python.exe tests/test_speed.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402

K = 24.0   # brillo por segundo del video de prueba


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def expected_gray(sec: float) -> float:
    """Brillo que se mide (gris de 0–255) para el segundo sec del archivo: el video guarda Y=K·sec en
    «rango limitado» (16–235) y al pasarlo a gris se estira."""
    return max(0.0, (K * sec - 16) * 255 / 219)


def luma_at(path: str, t: float) -> float:
    """Brillo medio del fotograma del segundo t de un video."""
    raw = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return float(np.frombuffer(raw, np.uint8).mean())


def duration_of(path: str) -> float:
    out = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-i", path], capture_output=True, text=True).stderr
    import re
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    src = os.path.join(out, "rampa.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"nullsrc=s=320x180:r=30:d=10,geq=lum='{K}*T':cb=128:cr=128,format=yuv420p",
                    "-f", "lavfi", "-i", "sine=f=440:d=10", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", src], check=True)
    app = QApplication(sys.argv)
    from editoria.core.controller import ProjectController
    from editoria.core import mapping
    ctrl = ProjectController()
    [mid] = ctrl.import_now([src])
    p = ctrl.project
    p.width, p.height = 320, 180
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a_ids = ctrl.add_media([mid], v1.id, 0.0)
    b_ids = ctrl.add_media([mid], v1.id, 10.0)
    A = next(p.clips[i] for i in a_ids if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    B = next(p.clips[i] for i in b_ids if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    A_audio = ctrl.partners(p, A)[0]
    assert (A.duration, B.start) == (10.0, 10.0)

    # --- velocidad 200 %: dura la mitad, lo de detrás se acerca, el sonido vinculado igual
    ctrl.set_speed([A.id], speed=2.0)
    A, B = p.clips[A.id], p.clips[B.id]
    A_audio = p.clips[A_audio.id]
    assert abs(A.duration - 5.0) < 1e-6 and abs(B.start - 5.0) < 1e-6, (A.duration, B.start)
    assert A_audio.speed == 2.0 and abs(A_audio.duration - 5.0) < 1e-6
    assert abs(A.src_at(2.0) - 4.0) < 1e-6
    assert mapping.map_time(p, mid, 4.0, [A]) == 2.0
    print("✓ 200 %: el clip dura la mitad, su sonido también y lo de detrás se acerca (sin huecos)")

    # --- dividir un clip rápido: los trozos siguen el archivo sin saltos
    ctrl.split(2.5, [A.id, A_audio.id])
    left = p.clips[A.id]
    right = next(c for c in p.clips.values() if c.track_id == v1.id and abs(c.start - 2.5) < 1e-6)
    assert abs(left.src_len - 5.0) < 1e-6 and abs(right.source_in - 5.0) < 1e-6, (left.src_len, right.source_in)
    print("✓ dividir a 200 %: el segundo trozo empieza justo donde acaba el primero (en el archivo)")

    # --- reversa
    ctrl.set_speed([right.id], reverse=True)
    right = p.clips[right.id]
    assert right.reverse and abs(right.src_at(0.0) - 10.0) < 1e-6 and abs(right.src_at(2.5) - 5.0) < 1e-6
    # recortar el inicio de un clip al revés quita el FINAL del archivo
    ctrl.trim_clip(right.id, "left", 3.0, linked=False)
    right = p.clips[right.id]
    assert abs(right.src_at(0.0) - 9.0) < 1e-6 and abs(right.source_in - 5.0) < 1e-6, (right.src_at(0), right.source_in)
    ctrl.undo_stack.undo()
    right = p.clips[right.id]
    print("✓ reversa: empieza por el final; recortar el inicio quita el final del archivo; deshacer funciona")

    # --- límites de recorte a 50 %
    ctrl.set_speed([B.id], speed=0.5)
    B = p.clips[B.id]
    assert abs(B.duration - 20.0) < 1e-6
    lm, _a, _b, rm = ctrl.trim_limits(B.id)
    assert abs(lm - B.start) < 1e-6 and abs(rm - B.end) < 1e-6   # usa todo el archivo: no se puede alargar
    print("✓ 50 %: dura el doble y no se puede alargar más allá del archivo")

    # --- congelar la imagen desde el cabezal
    t_freeze = B.start + 4.0          # a 50 %: segundo 2 del archivo
    fid = ctrl.freeze_frame(t_freeze, B.id)
    F = p.clips[fid]
    assert F.speed == 0.0 and abs(F.source_in - 2.0) < 1e-6 and abs(F.start - t_freeze) < 1e-6
    assert abs(F.src_at(1.0) - 2.0) < 1e-6
    print("✓ congelar (Mayús+R): desde el cabezal se queda la imagen del segundo 2 del archivo")

    # --- exportar y medir qué se ve
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    mp4 = os.path.join(out, "velocidad.mp4")
    opts = ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu", bitrate_mbps=8, loudnorm=False)
    args, total = build_command(p, opts, media_tools.ffmpeg(), os.path.join(out, "filtro.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    assert abs(duration_of(mp4) - total) < 0.15, (duration_of(mp4), total)
    checks = [
        (1.0, 2.0, "200 %"),                     # A (izq.): local 1 s → archivo 2 s
        (right.start + 0.5, right.src_at(0.5), "al revés"),
        (B.start + 2.0, 1.0, "50 %"),            # B: local 2 s → archivo 1 s
        (F.start + 0.5, 2.0, "congelado"),
        (F.start + 3.0, 2.0, "congelado"),
    ]
    for t, s_expected, name in checks:
        y = luma_at(mp4, t)
        assert abs(y - expected_gray(s_expected)) < 6, (name, t, y, s_expected, expected_gray(s_expected))
    print(f"✓ exportado ({total:.1f} s): 200 %, al revés, 50 % y congelado muestran el segundo correcto del archivo")

    # --- entrada / salida, quitar el tramo y exportar solo el tramo
    dur0 = p.duration()
    ctrl.set_mark("in", 1.0)
    ctrl.set_mark("out", 3.0)
    assert p.marked_range() == (1.0, 3.0)
    from editoria.core.project_tools import slice_project
    part = slice_project(p, 1.0, 3.0)
    assert abs(part.duration() - 2.0) < 1e-6
    mp4b = os.path.join(out, "tramo.mp4")
    args, total = build_command(part, ExportOptions(path=mp4b, width=320, height=180, fps=30, encoder="cpu",
                                                    bitrate_mbps=8, loudnorm=False),
                                media_tools.ffmpeg(), os.path.join(out, "filtro2.txt"))
    assert subprocess.run(args, capture_output=True).returncode == 0
    assert abs(duration_of(mp4b) - 2.0) < 0.15
    y = luma_at(mp4b, 0.5)     # timeline 1.5 → A a 200 % → archivo 3 s
    assert abs(y - expected_gray(3.0)) < 6, y
    ctrl.delete_marked()
    assert abs(p.duration() - (dur0 - 2.0)) < 1e-6 and p.mark_in == 1.0 and p.mark_out is None
    ctrl.undo_stack.undo()
    assert abs(p.duration() - dur0) < 1e-6
    q = type(p).from_dict(p.to_dict())
    assert (q.mark_in, q.mark_out) == (p.mark_in, p.mark_out)
    print("✓ I/O: tramo marcado, exportar solo el tramo (2 s), quitarlo cerrando el hueco, y se guarda")

    # --- velocidad en un proyecto guardado y cargado
    q = type(p).from_dict(p.to_dict())
    assert q.clips[F.id].speed == 0.0 and q.clips[right.id].reverse and q.clips[B.id].speed == 0.5
    print("✓ velocidad, reversa y congelado se guardan con el proyecto")

    # --- J / K / L e interfaz
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.ctrl.load_project(p) if hasattr(win.ctrl, "load_project") else None
    eng = win.engine
    w = win.ctrl
    [mid2] = w.import_now([src])
    w.add_media([mid2], [t for t in w.project.tracks if t.kind == TRACK_VIDEO][-1].id, 0.0)
    pump(app, 0.3)
    eng.jkl("l")
    assert eng.playing and eng.rate == 1.0
    eng.jkl("l")
    assert eng.rate == 2.0 and "2" in win.preview.rate_label.text()
    eng.jkl("l")
    assert eng.rate == 4.0
    eng.user_seek(5.0)
    eng.jkl("j")
    assert eng.rate == -1.0 and "◀◀" in win.preview.rate_label.text()
    t0 = eng.time
    pump(app, 0.4)
    assert eng.time < t0, (eng.time, t0)
    eng.jkl("k")
    assert not eng.playing and eng.rate == 1.0 and win.preview.rate_label.text() == ""
    print("✓ J/K/L: adelante 1×→2×→4×, atrás (el cabezal retrocede), K para")

    eng.user_seek(1.0)
    w.set_mark("in", 1.0)
    w.set_mark("out", 1.6)
    eng.set_loop(True)
    eng.play()
    pump(app, 1.6)
    assert eng.playing and 1.0 - 0.05 <= eng.time <= 1.65, eng.time
    eng.pause()
    eng.set_loop(False)
    print("✓ bucle: repite el tramo marcado")

    vid = next(c for c in w.project.clips.values() if w.project.track(c.track_id).kind == TRACK_VIDEO)
    win.timeline.set_selection([vid.id])
    win.inspector.set_selection([vid.id])
    win._speed()
    win.inspector.speed.setValue(50)
    pump(app, 0.1)
    vid = w.project.clips[vid.id]
    assert vid.speed == 0.5 and w.project.clips[w.partners(w.project, vid)[0].id].speed == 0.5
    win.grab().save(os.path.join(out, "inspector_velocidad.png"))
    eng.user_seek(vid.start + 3.0)
    win.timeline.set_selection([vid.id])
    win._freeze()
    assert any(c.speed == 0 for c in w.project.clips.values())
    print("✓ Inspector «Velocidad» (R) y Mayús+R funcionan desde la ventana")

    win.analyzer.shutdown()
    w.undo_stack.setClean()
    w._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
