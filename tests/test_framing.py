"""
Prueba de encuadre: zoom con la rueda y arrastre en el visor, fotogramas clave,
pantalla dividida, y comparación visor vs. exportación.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_framing.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import transform  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    a, b, img = (os.path.join(out, n) for n in ("a.mp4", "b.mp4", "foto.png"))
    ff = media_tools.ffmpeg()
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "testsrc2=s=1920x1080:r=30:d=10", "-c:v", "libx264", a])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "mandelbrot=s=1280x720:r=30,trim=duration=10", "-c:v", "libx264", b])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "smptehdbars=s=1280x720",
                           "-frames:v", "1", img])
    ia, ib, ii = ctrl.import_paths([a, b, img])
    while ctrl.analyzing:
        pump(app, 0.1)
    v2, v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO]
    ca = ctrl.add_media([ia], v1.id, 0.0)[0]
    cb = ctrl.add_media([ib], v2.id, 5.0)[0]
    ci = ctrl.add_media([ii], v1.id, 10.0)[0]

    # 1) Zoom con la rueda y arrastre en el visor (clip seleccionado)
    win.timeline.set_selection([ca])
    pump(app, 0.2)
    assert win.preview.canvas.framing_enabled
    win.engine.seek(1.0)
    win.preview.canvas.framing_wheel.emit(6)      # acercar
    win.preview.canvas.framing_drag.emit(0.10, 0.08)  # mover el encuadre
    c = ctrl.project.clips[ca]
    assert len(c.zoom_kf) == 1 and c.zoom_kf[0]["z"] > 1.9, c.zoom_kf
    assert c.zoom_kf[0]["x"] < 0.5 and c.zoom_kf[0]["y"] < 0.5, "arrastrar a la derecha mira más a la izquierda"
    n_undo = ctrl.undo_stack.count()
    print(f"✓ zoom fijo con rueda/arrastre: {c.zoom_kf[0]}")

    # 2) Animación: clave en 1 s (zoom actual) y clave en 4 s sin zoom
    win.inspector._add_kf()
    win.engine.seek(4.0)
    win.inspector.zoom.setValue(100)
    c = ctrl.project.clips[ca]
    assert len(c.zoom_kf) >= 2, c.zoom_kf
    assert abs(transform.value_at(c.zoom_kf, 0.2)[0] - c.zoom_kf[0]["z"]) < 1e-6  # el zoom se mantiene desde el inicio
    assert abs(transform.value_at(c.zoom_kf, 4.0)[0] - 1.0) < 1e-6
    z_mid = transform.value_at(c.zoom_kf, 2.5)[0]
    assert 1.0 < z_mid < c.zoom_kf[0]["z"]
    print(f"✓ zoom animado: {len(c.zoom_kf)} claves, en 2.5 s zoom={z_mid:.2f}")
    # Las claves siguen al contenido aunque se recorte el inicio del clip
    ctrl.trim_clip(ca, "left", 0.5)
    c = ctrl.project.clips[ca]
    assert abs(transform.value_at(c.zoom_kf, 2.5)[0] - z_mid) < 1e-6
    ctrl.undo_stack.undo()

    # 3) Pantalla dividida en el inspector
    win.timeline.set_selection([cb])
    pump(app, 0.2)
    win.inspector.layout_combo.setCurrentText("Mitad derecha")
    assert ctrl.project.clips[cb].layout == transform.LAYOUTS["Mitad derecha"]
    win.timeline.set_selection([ca])
    pump(app, 0.2)
    win.inspector.layout_combo.setCurrentText("Mitad izquierda")
    print("✓ pantalla dividida")

    # 4) Imagen con zoom (efecto Ken Burns)
    ctrl.set_zoom_keyframes(ci, [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5},
                                 {"t": 5.0, "z": 1.6, "x": 0.7, "y": 0.4}], "Ken Burns")

    # 5) Visor vs exportación en varios momentos
    W, H = 960, 540
    ctrl.set_settings(width=W, height=H)
    mp4 = os.path.join(out, "encuadre.mp4")
    args, total = build_command(ctrl.project, ExportOptions(path=mp4, width=W, height=H, fps=30, encoder="gpu",
                                                            bitrate_mbps=6), ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    win.timeline.set_selection([])
    for t in (0.5, 2.5, 6.0, 13.0):
        win.engine.seek(t)
        pump(app, 1.0)
        win.preview.canvas.grab().save(os.path.join(out, f"visor_{t}.png"))
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", str(t), "-i", mp4, "-frames:v", "1",
                               os.path.join(out, f"export_{t}.png")])
    win.grab().save(os.path.join(out, "ventana.png"))
    print(f"✓ exportado {total:.1f} s; capturas en {out}")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()


if __name__ == "__main__":
    main()
