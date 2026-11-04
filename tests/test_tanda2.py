"""
Prueba de la tanda 2 (2ª parte): rampas de velocidad, cámara lenta suave, reducir ruido, estabilizar,
detectar cortes de escena y la cola de exportación.
Ejecutar:  .venv/Scripts/python.exe tests/test_tanda2.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def duration_of(path: str) -> float:
    import re
    err = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-i", path], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    scenes = os.path.join(out, "escenas.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-f", "lavfi", "-t", "3", "-i", "mandelbrot=s=320x180:r=30",
                    "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=f=330:d=9",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]", "-map", "3:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", scenes], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height = 320, 180
    [mid] = ctrl.import_now([scenes])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    made = ctrl.add_media([mid], v1.id, 0.0)
    A = next(i for i in made if p.clips[i].track_id == v1.id)
    ctrl.trim_clip(A, "right", 4.0)
    made_b = ctrl.add_media([mid], v1.id, 4.0)
    B = next(i for i in made_b if p.clips[i].track_id == v1.id)
    stack = ctrl.undo_stack

    # --- rampa de velocidad
    src0, src1 = p.clips[A].source_in, p.clips[A].source_in + p.clips[A].src_len
    created = ctrl.speed_ramp(A, "rapido_lento_rapido")
    vids = sorted((p.clips[i] for i in created if p.track(p.clips[i].track_id).kind == TRACK_VIDEO),
                  key=lambda c: c.start)
    auds = [p.clips[i] for i in created if p.track(p.clips[i].track_id).kind == TRACK_AUDIO]
    n = len(ctrl.RAMPS["rapido_lento_rapido"][1])
    assert len(vids) == n and len(auds) == n
    for a, b in zip(vids, vids[1:]):
        assert abs(a.end - b.start) < 1e-6 and abs(a.source_in + a.src_len - b.source_in) < 1e-6
    assert abs(vids[0].source_in - src0) < 1e-6 and abs(vids[-1].source_in + vids[-1].src_len - src1) < 1e-6
    assert vids[0].speed > 1.5 and min(c.speed for c in vids) < 0.5 and all(c.link for c in vids)
    assert any(c.smooth for c in vids if c.speed < 1)
    assert abs(p.clips[B].start - vids[-1].end) < 1e-6                 # lo de detrás se movió
    print(f"✓ rampa: {n} tramos seguidos, mismo material ({src0:.1f}→{src1:.1f} s), dura {vids[-1].end:.2f} s; "
          "lo de detrás se mueve")

    # --- exportar la rampa con cámara lenta suave
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    mp4 = os.path.join(out, "rampa.mp4")
    args, total = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                 bitrate_mbps=4, loudnorm=False), ff, os.path.join(out, "f1.txt"))
    assert "minterpolate" in open(os.path.join(out, "f1.txt"), encoding="utf-8").read()
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]
    assert abs(duration_of(mp4) - total) < 0.2, (duration_of(mp4), total)
    print(f"✓ exportada con cámara lenta suave (fotogramas inventados): {total:.1f} s")
    stack.undo()
    assert len([c for c in p.clips.values() if c.track_id == v1.id]) == 2
    print("✓ deshacer quita la rampa entera")

    # --- reducir ruido y estabilizar
    from editoria.core import enhance
    win.timeline.set_selection([A])
    win.inspector.set_selection([A])
    insp = win.inspector
    assert insp.enhance_box.isVisible() or insp.enhance_box.isVisibleTo(insp)
    insp.denoise.setValue(60)
    assert abs(p.clips[A].fx["denoise"] - 0.6) < 1e-6
    insp.stab.setChecked(True)
    t0 = time.time()
    while getattr(insp, "_stab_job", None) is not None and time.time() - t0 < 60:
        pump(app, 0.1)
    st = (p.clips[A].fx or {}).get("stab")
    assert isinstance(st, dict) and os.path.exists(st["trf"]), p.clips[A].fx
    args, total = build_command(p, ExportOptions(path=os.path.join(out, "mejorar.mp4"), width=320, height=180,
                                                 fps=30, encoder="cpu", bitrate_mbps=4, loudnorm=False),
                                ff, os.path.join(out, "f2.txt"))
    script = open(os.path.join(out, "f2.txt"), encoding="utf-8").read()
    assert "vidstabtransform" in script and "hqdn3d" in script, script[:500]
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]
    ctrl.trim_clip(A, "left", 0.5)       # el trozo cambió: estabilizador de una pasada
    assert enhance.stab_filter(p.clips[A]).startswith("deshake")
    stack.undo()
    print("✓ reducir ruido + estabilizar (2 pasadas; si recortas el clip, 1 pasada) exportan bien")

    # --- cortes de escena
    cuts = enhance.scene_cuts(p.media[mid].path, 0.0, 9.0)
    assert len(cuts) == 2 and abs(cuts[0] - 3.0) < 0.1 and abs(cuts[1] - 6.0) < 0.1, cuts
    Bc = p.clips[B]
    t_line = [Bc.start + (s - Bc.source_in) for s in cuts if Bc.source_in < s < Bc.source_in + Bc.src_len]
    n0 = stack.index()
    k = ctrl.split_at_times(B, t_line)
    assert k == len(t_line) and stack.index() == n0 + 1, (k, t_line, stack.index(), n0)
    pieces = [c for c in p.clips.values() if c.track_id == v1.id and c.start >= Bc.start - 1e-6]
    assert len(pieces) == k + 1, (len(pieces), k, [(c.start, c.duration) for c in pieces])
    stack.undo()
    ctrl.add_markers(t_line)
    assert sum(1 for m in p.markers if m.label.startswith("Corte de escena")) == len(t_line)
    print(f"✓ cortes de escena: {cuts} → cortar ahí (un solo deshacer) o marcadores")

    # --- cola de exportación (con «foto» del proyecto)
    q = win.render_queue
    q.add(p, ExportOptions(path=os.path.join(out, "cola_video.mp4"), width=320, height=180, fps=30,
                           encoder="cpu", bitrate_mbps=4, loudnorm=False), "Video")
    q.add(p, ExportOptions(path=os.path.join(out, "cola_audio.wav"), audio_only=True, loudnorm=False), "Audio")
    ctrl.set_mark("in", 1.0)
    ctrl.set_mark("out", 2.5)
    q.add(p, ExportOptions(path=os.path.join(out, "cola_tramo.mp4"), width=320, height=180, fps=30,
                           encoder="cpu", bitrate_mbps=4, loudnorm=False), "Tramo", p.marked_range())
    total_before = p.duration()
    ctrl.delete_clips([B])                       # cambiar el proyecto DESPUÉS de añadir: la cola no cambia
    win.open_queue()
    dlg = win._queue_dialog
    assert dlg.table.rowCount() == 3
    dlg.b_run.click()
    t0 = time.time()
    while (q.running or any(j["status"] == "pending" for j in q.jobs)) and time.time() - t0 < 180:
        pump(app, 0.2)
    assert [j["status"] for j in q.jobs] == ["done"] * 3, [(j["status"], j["error"][-300:]) for j in q.jobs]
    assert abs(duration_of(os.path.join(out, "cola_video.mp4")) - total_before) < 0.2
    assert abs(duration_of(os.path.join(out, "cola_tramo.mp4")) - 1.5) < 0.2
    assert os.path.getsize(os.path.join(out, "cola_audio.wav")) > 10000
    dlg.grab().save(os.path.join(out, "cola.png"))
    print("✓ cola: 3 exportaciones seguidas (video, solo audio, tramo) con el proyecto tal como estaba al añadirlas")

    win.analyzer.shutdown()
    stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
