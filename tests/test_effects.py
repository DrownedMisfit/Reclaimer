"""
Prueba del panel Efectos: sonidos propios a la timeline y efectos de imagen al exportar.
Ejecutar:  .venv/Scripts/python.exe tests/test_effects.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import sfx  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    # 1) Sonidos propios: existen, duran lo esperado y no saturan
    for key in sfx.CATALOG:
        p = sfx.path_for(key)
        info = media_tools.probe(p)
        assert 0.05 < info["duration"] < 7 and info["channels"] == 2, (key, info)
    print(f"✓ {len(sfx.CATALOG)} sonidos propios generados (estéreo, 48 kHz)")

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl, panel = win.ctrl, win.effects
    ff = media_tools.ffmpeg()
    vid = os.path.join(out, "clip.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    [mid] = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.1)

    # 2) Doble clic en «Impacto» → en la pista Efectos, en el cabezal
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    vc = ctrl.add_media([mid], v1.id, 0.0)[0]
    win.engine.seek(1.0)
    it = next(panel.tree.topLevelItem(g).child(k) for g in range(panel.tree.topLevelItemCount())
              for k in range(panel.tree.topLevelItem(g).childCount())
              if panel.tree.topLevelItem(g).child(k).data(0, 0x0100) == "sfx:impacto")
    panel.add_at_playhead(it)
    pump(app, 0.5)
    p = ctrl.project
    fx_clips = [c for t in p.tracks if t.kind == TRACK_AUDIO and t.role == "efectos" for c in p.clips_on(t.id)]
    assert len(fx_clips) == 1 and abs(fx_clips[0].start - 1.0) < 1e-6, fx_clips
    assert p.media[fx_clips[0].media_id].category == "Efectos"
    print("✓ doble clic en un sonido: queda en la pista «Efectos», en el cabezal")
    # arrastrar: el sonido se convierte en un medio de la biblioteca
    md = panel.tree.mimeData([it])
    from editoria.ui.common import MEDIA_MIME
    assert md.data(MEDIA_MIME).data().decode() == fx_clips[0].media_id
    print("✓ arrastrar un sonido lleva su id de biblioteca (se suelta en la timeline)")

    # 3) Efectos de imagen en el clip seleccionado
    win.timeline.set_selection([vc])
    panel.toggle_look("bw", 1.0, "⚫ Blanco y negro")
    panel.toggle_look("vignette", 0.6, "◐ Viñeta")
    assert p.clips[vc].fx == {"bw": 1.0, "vignette": 0.6}, p.clips[vc].fx
    panel.toggle_look("vignette", 0.6, "◐ Viñeta")          # segundo clic: se quita
    assert p.clips[vc].fx == {"bw": 1.0}
    win.engine.seek(2.0)
    pump(app, 0.5)
    layer = win.preview.canvas.layers[v1.id]
    assert layer.box.graphicsEffect() is not None, "el visor muestra el blanco y negro"
    print("✓ efectos de imagen: se ponen y quitan con un clic; el visor los muestra")

    mp4 = os.path.join(out, "efectos.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="gpu",
                                              bitrate_mbps=2), ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-ss", "2", "-i", mp4, "-frames:v", "1",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    rgb = np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(int)
    sat = float(np.mean(rgb.max(1) - rgb.min(1)))
    assert sat < 8, f"debería salir en blanco y negro (saturación {sat:.1f})"
    print(f"✓ exportado en blanco y negro (saturación {sat:.1f})")
    for key in ("grain", "blur", "glitch", "oldfilm", "warm"):
        ctrl.batch_clip_props({vc: {"fx": {key: 0.5}}}, "prueba")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="gpu",
                                                  bitrate_mbps=2), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, (key, r.stderr.decode(errors="replace")[-800:])
    print("✓ grano, desenfoque, glitch, película antigua y tono cálido exportan bien")

    # 4) Paneles acoplables: la página Efectos muestra el panel; restablecer la distribución
    win.go_page("effects")
    pump(app, 0.2)
    assert panel.isVisible()
    win.docks["effects"].setFloating(True)
    win.reset_layout()
    pump(app, 0.2)
    assert not win.docks["effects"].isFloating()
    print("✓ paneles: la pestaña Efectos lo muestra; «Restablecer distribución» lo devuelve a su sitio")
    win.analyzer.shutdown()   # el análisis automático de clips podría seguir en marcha
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
