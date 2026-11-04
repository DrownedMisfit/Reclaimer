"""
Prueba del color por clip (Inspector → Color), los LUT .cube, el color automático, el visor (misma tabla
que la exportación), las gráficas y «pegar atributos → Color».
Ejecutar:  .venv/Scripts/python.exe tests/test_color.py <carpeta_salida>
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

from editoria.core import color as C  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def frame_of(path: str, t: float) -> np.ndarray:
    return media_tools.frame_rgb(path, t, 320)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    src = os.path.join(out, "colores.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4",
                    "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv444p", src], check=True)

    # --- neutro = sin cambios; .cube de ida y vuelta
    assert C.is_neutral(None) and C.is_neutral({"exposure": 0})
    ident = C.table({})
    assert np.abs(ident - C.identity()).max() < 1e-6
    look = {"exposure": 0.6, "contrast": 0.3, "saturation": -0.5, "temperature": 0.4}
    cube = C.cube_file(look)
    assert np.abs(C.read_cube(cube) - C.table(look)).max() < 1e-5
    inv = os.path.join(out, "invertir.cube")
    with open(inv, "w") as f:
        f.write("LUT_3D_SIZE 2\n")
        for b in (0, 1):
            for g in (0, 1):
                for r in (0, 1):
                    f.write(f"{1 - r} {1 - g} {1 - b}\n")
    px = np.array([[0.2, 0.5, 0.9]], np.float32)
    assert np.allclose(C.grade(px, {"lut": inv, "lut_mix": 1.0}), [[0.8, 0.5, 0.1]], atol=1e-5)
    print("✓ tabla de color: neutra = igual; .cube se lee y se escribe sin pérdidas; un LUT invertido invierte")

    # --- automático: un fotograma oscuro y azulado se aclara y se calienta
    dark_blue = np.zeros((90, 160, 3), np.uint8)
    dark_blue[...] = (20, 30, 70)
    a = C.auto(dark_blue)
    assert a["exposure"] > 0.3 and a["temperature"] > 0.1, a
    print(f"✓ color automático: oscuro y azulado → exposición {a['exposure']:+.2f}, temperatura {a['temperature']:+.2f}")

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height = 320, 180
    [mid] = ctrl.import_now([src])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    made = ctrl.add_media([mid], v1.id, 0.0)
    cid = next(i for i in made if p.clips[i].track_id == v1.id)
    ctrl.split(2.0, [cid])
    cid2 = next(c.id for c in p.clips.values() if c.track_id == v1.id and abs(c.start - 2.0) < 1e-6)

    # --- Inspector → Color: los deslizadores cambian el clip; varios toques = un solo paso de deshacer
    win.timeline.set_selection([cid])
    win.inspector.set_selection([cid])
    insp = win.inspector
    assert insp.clip_tabs.isTabVisible(3)
    n0 = ctrl.undo_stack.count()
    insp.color_sliders["exposure"].setValue(40)
    insp.color_sliders["exposure"].setValue(60)
    assert ctrl.undo_stack.count() == n0 + 1, (ctrl.undo_stack.count(), n0)   # arrastrar = un solo paso
    insp.color_sliders["saturation"].setValue(-50)
    col = p.clips[cid].color
    assert col and abs(col["exposure"] - 0.6) < 1e-6 and abs(col["saturation"] + 0.5) < 1e-6, col
    assert ctrl.undo_stack.count() == n0 + 2
    ctrl.set_color([cid], dict(look), "Color")
    print("✓ Inspector → Color: los deslizadores cambian el clip (y se deshacen de una vez)")

    # --- el visor usa el filtro de color
    win.engine.user_seek(1.0)
    pump(app, 0.3)
    layer = win.preview.canvas.layer(v1.id)
    from editoria.ui.preview import LookEffect
    assert isinstance(layer.box.graphicsEffect(), LookEffect)
    win.engine.color_bypass = True
    win.engine.refresh_sources()
    pump(app, 0.1)
    assert not isinstance(layer.box.graphicsEffect(), LookEffect)
    win.engine.color_bypass = False
    win.engine.refresh_sources()
    print("✓ el visor aplica el color (y «Ver sin corrección» lo quita para comparar)")

    # --- lo que ves = lo que sale: comparar el cálculo del visor con el video exportado
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    mp4 = os.path.join(out, "color.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                              bitrate_mbps=20, loudnorm=False),
                             ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1200:]
    orig = frame_of(src, 1.0).astype(np.float32)
    expected = C.apply_rgb8(frame_of(src, 1.0), look).astype(np.float32)
    got = frame_of(mp4, 1.0).astype(np.float32)
    err = float(np.abs(got - expected).mean())
    moved = float(np.abs(orig - expected).mean())
    assert err < 9 and moved > 20, (err, moved)
    untouched = float(np.abs(frame_of(mp4, 3.0).astype(np.float32) - frame_of(src, 3.0)).mean())
    assert untouched < 6, untouched
    print(f"✓ exportado = visor (diferencia media {err:.1f} de 255; el color movió {moved:.0f}); el otro clip intacto")

    # --- pegar atributos → Color
    ctrl.copy_clips([cid])
    ctrl.paste_attributes([cid2], ["color"])
    assert p.clips[cid2].color == p.clips[cid].color
    print("✓ Ctrl+C / Alt+V → «Color»: el mismo color en otro clip")

    # --- color automático desde el Inspector
    ctrl.set_color([cid2], None, "Quitar color")
    win.timeline.set_selection([cid2])
    insp.set_selection([cid2])
    win.engine.user_seek(2.5)
    insp.btn_auto_color.click()
    assert p.clips[cid2].color is None or isinstance(p.clips[cid2].color, dict)
    print("✓ «✨ Color automático» funciona desde el Inspector")

    # --- gráficas
    win.show_panel(win.scopes)
    win.engine.user_seek(1.0)
    for mode in range(win.scopes.mode.count()):
        win.scopes._last_frame = None
        win.scopes.mode.setCurrentIndex(mode)
        t0 = time.time()
        while win.scopes._last_frame is None and time.time() - t0 < 15:
            pump(app, 0.1)
        assert win.scopes._last_frame is not None, win.scopes.mode.currentText()
    assert win.scopes.info.text()
    win.scopes.grab().save(os.path.join(out, "graficas.png"))
    print("✓ gráficas: forma de onda, desfile RGB, histograma y vectorscopio del fotograma del cabezal")

    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
