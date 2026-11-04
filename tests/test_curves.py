"""
Prueba de las curvas de volumen y opacidad («〰 Curvas»), la opacidad y los modos de fusión
(medidos en el video exportado) y su edición con el ratón.
Ejecutar:  .venv/Scripts/python.exe tests/test_curves.py <carpeta_salida>
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
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import curves as K  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def rms(samples: np.ndarray, a: float, b: float, sr: int = 16000) -> float:
    x = samples[int(a * sr):int(b * sr)]
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    tone = os.path.join(out, "tono.wav")
    gray = os.path.join(out, "gris.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=6",
                    "-af", "volume=4", tone], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:r=30:d=4",
                    "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv444p", gray], check=True)
    assert abs(K.value_at([{"t": 1, "v": 1}, {"t": 2, "v": 0}], 1.5) - 0.5) < 1e-9

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height = 320, 180
    tid, gid = ctrl.import_now([tone, gray])
    t0 = time.time()
    while tid not in ctrl.peaks and time.time() - t0 < 30:
        pump(app, 0.1)
    a2 = p.track(ctrl.ensure_role_track("musica"))
    A = ctrl.add_media([tid], a2.id, 0.0)[0]

    # --- curva de volumen: 100 % hasta el segundo 2, baja a 0 en el 4
    ctrl.set_curve(A, "vol", [{"t": 2.0, "v": 1.0}, {"t": 4.0, "v": 0.0}])
    c = p.clips[A]
    assert abs(K.gain(c, 1.0) - 1.0) < 1e-6 and abs(K.gain(c, 3.0) - 0.5) < 1e-6 and K.gain(c, 5.0) == 0.0
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    wav = os.path.join(out, "curva.wav")
    args, _ = build_command(p, ExportOptions(path=wav, audio_only=True, loudnorm=False), ff, os.path.join(out, "fa.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    snd = media_tools.decode_mono(wav, 16000)
    l1, l3, l5 = rms(snd, 0.5, 1.5), rms(snd, 2.9, 3.1), rms(snd, 4.5, 5.5)
    assert l3 < l1 * 0.65 and l5 < l1 * 0.02 and l3 > l1 * 0.3, (l1, l3, l5)
    from editoria.core import meters
    assert meters.track_levels(p, ctrl.peaks, 5.0).get(a2.id, 0.0) < 1e-6
    print(f"✓ curva de volumen exportada: {l1:.3f} → {l3:.3f} → {l5:.4f} (y el vúmetro la sigue)")

    # --- opacidad y fusión (V1 gris, V2 gris encima)
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    v2, v1 = vids[0], vids[-1]
    bot = next(i for i in ctrl.add_media([gid], v1.id, 0.0) if p.clips[i].track_id == v1.id)
    top = next(i for i in ctrl.add_media([gid], v2.id, 0.0) if p.clips[i].track_id == v2.id)
    ctrl.set_color([bot], {"exposure": -1.0})         # abajo, más oscuro (≈ 64)

    def luma_export(name):
        mp4 = os.path.join(out, name)
        args, _ = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                 bitrate_mbps=8, loudnorm=False), ff, os.path.join(out, "fv.txt"))
        rr = subprocess.run(args, capture_output=True, text=True)
        assert rr.returncode == 0, rr.stderr[-1500:]
        return float(media_tools.frame_rgb(mp4, 1.0, 160).astype(np.float32).mean())
    normal = luma_export("normal.mp4")
    ctrl.set_curve(top, "op", level=0.5)
    half = luma_export("medio.mp4")
    ctrl.set_curve(top, "op", level=1.0)
    ctrl.set_clip_props([top], "fusión", blend="screen")
    screen = luma_export("pantalla.mp4")
    ctrl.set_clip_props([top], "fusión", blend="multiply")
    mult = luma_export("multiplicar.mp4")
    assert abs(normal - 128) < 8, normal
    assert 85 < half < 110, half                       # mitad entre 128 y ~64
    assert screen > normal + 25 and mult < 70, (screen, mult)
    print(f"✓ opacidad y fusión exportadas: normal {normal:.0f}, 50 % {half:.0f}, pantalla {screen:.0f}, "
          f"multiplicar {mult:.0f}")
    ctrl.set_clip_props([top], "fusión", blend="normal")

    # --- curva de opacidad (con tiempo): de 0 a 1
    ctrl.set_curve(top, "op", [{"t": 0.0, "v": 0.0}, {"t": 2.0, "v": 1.0}])
    mp4 = os.path.join(out, "op_curva.mp4")
    args, _ = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                             bitrate_mbps=8, loudnorm=False), ff, os.path.join(out, "fo.txt"))
    assert subprocess.run(args, capture_output=True).returncode == 0
    early = float(media_tools.frame_rgb(mp4, 0.2, 160).mean())
    late = float(media_tools.frame_rgb(mp4, 3.0, 160).mean())
    assert early < late - 30, (early, late)
    print(f"✓ curva de opacidad: aparece poco a poco ({early:.0f} → {late:.0f})")

    # --- visor
    win.engine.user_seek(1.0)
    pump(app, 0.2)
    layer = win.preview.canvas.layer(v2.id)
    assert abs(layer.box.opacity() - 0.5) < 0.05, layer.box.opacity()
    ctrl.set_clip_props([top], "fusión", blend="screen")
    win.engine.user_seek(1.0)
    pump(app, 0.2)
    from editoria.ui.preview import LookEffect
    eff = layer.box.graphicsEffect()
    assert isinstance(eff, LookEffect) and eff.blend == "screen"
    print("✓ visor: la opacidad sigue la curva y el modo de fusión se aplica")

    # --- Inspector
    win.timeline.set_selection([top])
    win.inspector.set_selection([top])
    win.inspector.opacity.setValue(70)
    assert abs(p.clips[top].opacity - 0.7) < 1e-6
    win.inspector.blend_combo.setCurrentIndex(win.inspector.blend_combo.findData("multiply"))
    assert p.clips[top].blend == "multiply"
    print("✓ Inspector → Video: opacidad y fusión")

    # --- con el ratón («〰 Curvas»)
    tl = win.timeline
    win.tool_curves.setChecked(True)
    tl.set_curves(True)
    tl.fit()
    pump(app, 0.2)
    ctrl.set_curve(A, "vol", [])
    c = p.clips[A]
    r = tl.clip_rect(c)
    area = tl._curve_area(c, r)
    xa = int(r.left() + 1.0 * tl.pps)
    ya = int(area.bottom() - tl._curve_value(c, "vol", 1.0) * area.height())
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(xa, ya))
    assert len(p.clips[A].vol_kf) == 1, p.clips[A].vol_kf
    # arrastrar ese punto hacia abajo = baja el volumen ahí
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(xa, ya))
    QTest.mouseMove(tl, QPoint(xa, ya + 12))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(xa, ya + 12))
    assert p.clips[A].vol_kf[0]["v"] < 0.9, p.clips[A].vol_kf
    # clic derecho = borrar el punto
    c = p.clips[A]
    yk = int(area.bottom() - tl._curve_value(c, "vol", 1.0) * area.height())
    QTest.mouseClick(tl, Qt.RightButton, Qt.NoModifier, QPoint(xa, yk))
    assert p.clips[A].vol_kf == []
    # Mayús+arrastrar la línea = todo el clip más bajo
    c = p.clips[A]
    yl = int(area.bottom() - tl._curve_value(c, "vol", 2.0) * area.height())
    xl = int(r.left() + 2.0 * tl.pps)
    QTest.mousePress(tl, Qt.LeftButton, Qt.ShiftModifier, QPoint(xl, yl))
    QTest.mouseMove(tl, QPoint(xl, yl + 10))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.ShiftModifier, QPoint(xl, yl + 10))
    assert p.clips[A].volume < 0.95, p.clips[A].volume
    tl.grab().save(os.path.join(out, "curvas.png"))
    print("✓ con el ratón: clic = punto, arrastrar = moverlo, clic derecho = borrarlo, Mayús+arrastrar = todo")

    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
