"""
Prueba de las transiciones: ponerlas en un corte (o el más cercano al cabezal), quitarlas, que se
ignoren si los clips se separan, el menú del clic derecho y la exportación con xfade (medida por brillo:
un clip que se aclara + un clip blanco).
Ejecutar:  .venv/Scripts/python.exe tests/test_transitions.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402
from test_speed import duration_of, expected_gray, luma_at  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    ramp = os.path.join(out, "rampa.mp4")
    white = os.path.join(out, "blanco.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "nullsrc=s=320x180:r=30:d=10,geq=lum='24*T':cb=128:cr=128,format=yuv420p",
                    "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", ramp], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=white:s=320x180:r=30:d=6,format=yuv420p",
                    "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", white], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height = 320, 180
    rid, wid = ctrl.import_now([ramp, white])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    A = ctrl.add_media([rid], v1.id, 0.0)[0]
    ctrl.trim_clip(A, "right", 5.0)                    # rampa: segundos 0–5 (quedan 5 s de material después)
    B = ctrl.add_media([wid], v1.id, 5.0)[0]           # blanco desde su segundo 0 (sin material antes)
    A, B = p.clips[A], p.clips[B]
    assert abs(A.end - B.start) < 1e-6

    # --- poner con el cabezal cerca del corte
    assert ctrl.cut_near(5.3) == B.id and ctrl.cut_near(8.0) is None
    ctrl.set_transition(ctrl.transition_targets([], 5.2), "fade", 1.0)
    from editoria.core import transitions as TR
    pairs = TR.pairs(p, v1.id)
    assert len(pairs) == 1 and pairs[0][2] == {"type": "fade", "dur": 1.0, "ai": False}
    hb, ha = TR.handles(p, p.clips[A.id])
    assert abs(ha - 5.0) < 1e-6 and TR.handles(p, p.clips[B.id])[0] == 0.0
    # seleccionando el clip de la izquierda también vale (su corte de salida)
    assert ctrl.transition_targets([A.id], 0.0) == [B.id]
    print("✓ se pone en el corte más cercano al cabezal (o el del clip seleccionado)")

    # --- exportar: disolver (mezcla en el corte), duración intacta
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    mp4 = os.path.join(out, "disolver.mp4")
    args, total = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                 bitrate_mbps=8, loudnorm=False),
                                media_tools.ffmpeg(), os.path.join(out, "f1.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    assert abs(duration_of(mp4) - total) < 0.15 and abs(total - 11.0) < 1e-6
    before, mid, after = luma_at(mp4, 4.2), luma_at(mp4, 5.0), luma_at(mp4, 5.8)
    white_g = luma_at(mp4, 8.0)
    assert abs(before - expected_gray(4.2)) < 7, before                     # aún la rampa
    lo, hi = expected_gray(5.0), white_g
    assert lo + 0.25 * (hi - lo) < mid < hi - 0.25 * (hi - lo), (mid, lo, hi)   # mitad y mitad
    assert abs(after - white_g) < 6, after
    print(f"✓ disolver exportado: antes {before:.0f}, en el corte {mid:.0f} (mezcla), después {after:.0f}")

    # --- fundido a negro
    ctrl.set_transition([B.id], "fadeblack", 1.0)
    mp4b = os.path.join(out, "negro.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4b, width=320, height=180, fps=30, encoder="cpu",
                                              bitrate_mbps=8, loudnorm=False),
                             media_tools.ffmpeg(), os.path.join(out, "f2.txt"))
    assert subprocess.run(args, capture_output=True).returncode == 0
    darkest = min(luma_at(mp4b, 4.6 + 0.1 * i) for i in range(9))
    assert darkest < 0.6 * min(before, white_g), (darkest, before, white_g)
    print(f"✓ fundido a negro: en el corte se oscurece hasta {darkest:.0f} (antes {before:.0f}, después {white_g:.0f})")

    # --- todas las del catálogo exportan sin error (aunque falte material: se alarga el borde)
    for key, name, _d in TR.CATALOG:
        ctrl.set_transition([B.id], key, 0.6)
        args, _t = build_command(p, ExportOptions(path=os.path.join(out, "t.mp4"), width=160, height=90, fps=30,
                                                  encoder="cpu", bitrate_mbps=2, loudnorm=False),
                                 media_tools.ffmpeg(), os.path.join(out, "f3.txt"))
        rr = subprocess.run(args, capture_output=True, text=True)
        assert rr.returncode == 0, (name, rr.stderr[-800:])
    print(f"✓ las {len(TR.CATALOG)} transiciones del catálogo exportan bien")

    # --- se ignora si los clips se separan; deshacer; quitar
    ctrl.move_clips({B.id: (6.0, v1.id)}) if hasattr(ctrl, "move_clips") else None
    if abs(p.clips[B.id].start - 6.0) < 1e-6:
        assert not TR.pairs(p, v1.id)
        ctrl.undo_stack.undo()
        assert TR.pairs(p, v1.id)
    ctrl.set_transition([B.id], None)
    assert not TR.pairs(p, v1.id)
    ctrl.undo_stack.undo()
    assert TR.pairs(p, v1.id)
    print("✓ si separas los clips no se aplica; quitar y deshacer funcionan")

    # --- visor (aproximación), menú del clic derecho, panel Efectos
    fx = TR.preview_fx(p, p.clips[B.id])
    assert fx and (fx.get("fade_in") or fx.get("flash"))
    win.timeline.set_selection([B.id])
    menu = QMenu()
    gpos = win.timeline.mapToGlobal(win.timeline.rect().center())
    win.timeline._transition_menu(menu, p.clips[B.id], gpos)
    titles = [a.text() for a in menu.actions()]
    assert any("Transición" in t for t in titles), titles
    eff = win.effects
    eff.trans_list.setCurrentRow([k for k, *_ in TR.CATALOG].index("hblur"))
    eff.trans_dur.setValue(0.4)
    eff.apply_transition()
    assert TR.of(p.clips[B.id]) == {"type": "hblur", "dur": 0.4}
    eff.view_transition()
    t0 = time.time()
    while eff._trans_job is not None and time.time() - t0 < 60:
        pump(app, 0.1)
    assert getattr(eff, "_trans_dialog", None) is not None, eff.trans_status.text()
    pump(app, 0.5)
    eff._trans_dialog.close()
    win.grab().save(os.path.join(out, "timeline_transicion.png"))
    print("✓ clic derecho «⧉ Transición», panel Efectos y «▶ Ver la transición» funcionan")

    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
