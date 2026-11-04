"""
Prueba de los FUNDIDOS con tiradores (como Resolve) y de los bordes de la línea de tiempo:
  · tirador blanco en las esquinas de arriba del clip: arrastrar = fundido de salida/entrada (imagen y sonido),
    de fotograma en fotograma, en un solo paso de Ctrl+Z; se ve el triángulo oscuro;
  · al exportar: la imagen acaba en negro y el sonido en silencio;
  · seleccionado = borde ROJO sólido; candado gris si la pista está libre, ámbar solo si está bloqueada;
    las herramientas activas no llevan borde naranja.
Ejecutar:  .venv/Scripts/python.exe tests/test_fades_borders.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import effects
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.common import COLORS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "freaks.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=320x180:d=8:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=8", "-shortest", "-pix_fmt", "yuv420p", vid], check=True)
    assert abs(effects.fade_gain({"fade_out": 2.0}, 7.0, 8.0) - 0.5) < 1e-6 and effects.fade_gain({}, 1, 8) == 1.0

    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p, tl = win.ctrl, win.ctrl.project, win.timeline
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ids = ctrl.add_media([mid], v1.id, 0.0)
    vc = next(i for i in ids if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    ac = next(i for i in ids if p.track(p.clips[i].track_id).kind == TRACK_AUDIO)
    tl.fit() if hasattr(tl, "fit") else None
    pump(app, 0.2)

    # --- seleccionado = borde rojo sólido ---
    tl.set_selection([vc])
    pump(app, 0.2)
    img = tl.grab().toImage()
    r = tl.clip_rect(p.clips[vc])
    px = img.pixelColor(int(r.center().x()), int(r.top() + 1))
    assert px.red() > 190 and px.green() < 110 and px.blue() < 110, px.name()
    assert COLORS["clip_sel"].name() == "#ec3a32"
    print("✓ seleccionado: borde ROJO sólido (como Resolve)")

    # --- tirador de fundido de salida en la imagen: arrastrar 2 s hacia dentro ---
    def drag_handle(cid, key, seconds):
        c = p.clips[cid]
        rr = tl._fade_handle_rects(c, tl.clip_rect(c))[key]
        start = QPoint(int(rr.center().x()), int(rr.center().y()))
        dx = int(round(seconds * tl.pps)) * (-1 if key == "fade_out" else 1)
        QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, start)
        for k in range(1, 6):
            QTest.mouseMove(tl, QPoint(start.x() + dx * k // 5, start.y()))
            pump(app, 0.02)
        QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(start.x() + dx, start.y()))
        pump(app, 0.1)

    n0 = ctrl.undo_stack.count()
    drag_handle(vc, "fade_out", 2.0)
    fo = float((p.clips[vc].fx or {}).get("fade_out", 0))
    assert abs(fo - 2.0) < 0.15, fo
    assert abs(fo * p.fps - round(fo * p.fps)) < 0.01, "de fotograma en fotograma"
    assert ctrl.undo_stack.count() == n0 + 1 and ctrl.undo_stack.undoText() == "Fundido de salida"
    print(f"✓ tirador de la esquina derecha → fundido de salida de la imagen: {fo:.2f} s (un paso de Ctrl+Z)")
    tl.set_selection([ac])
    pump(app, 0.1)
    drag_handle(ac, "fade_out", 2.0)
    drag_handle(ac, "fade_in", 1.0)
    fa = p.clips[ac].fx or {}
    assert abs(float(fa.get("fade_out", 0)) - 2.0) < 0.15 and abs(float(fa.get("fade_in", 0)) - 1.0) < 0.15, fa
    print("✓ en el sonido: fundido de salida y de entrada con sus tiradores")
    img = tl.grab().toImage()
    ra = tl.clip_rect(p.clips[ac])
    inside = img.pixelColor(int(ra.right() - 4), int(ra.top() + ra.height() * 0.35))
    outside = img.pixelColor(int(ra.center().x()), int(ra.top() + ra.height() * 0.35))
    assert inside.lightness() < outside.lightness(), (inside.name(), outside.name())
    print("✓ se ve el triángulo oscuro del fundido")
    ctrl.undo_stack.undo()
    assert not float((p.clips[ac].fx or {}).get("fade_in", 0))
    ctrl.undo_stack.redo()

    # --- exportar: la imagen acaba en negro y el sonido en silencio ---
    outv = os.path.join(out, "fundido.mp4")
    args, _ = build_command(p, ExportOptions(path=outv, width=320, height=180, fps=30.0, encoder="cpu",
                                             bitrate_mbps=3, subtitles=False, loudnorm=False),
                            ff, os.path.join(out, "f.txt"))
    assert subprocess.run(args, capture_output=True).returncode == 0

    def luma(t):
        r_ = subprocess.run([ff, "-v", "error", "-ss", f"{t}", "-i", outv, "-frames:v", "1", "-f", "rawvideo",
                             "-pix_fmt", "gray", "-"], capture_output=True)
        return float(np.frombuffer(r_.stdout, np.uint8).mean())

    def rms(a, b):
        r_ = subprocess.run([ff, "-v", "error", "-ss", f"{a}", "-t", f"{b - a}", "-i", outv, "-vn", "-ac", "1",
                             "-f", "s16le", "-"], capture_output=True)
        x = np.frombuffer(r_.stdout, np.int16).astype(np.float32)
        return float(np.sqrt((x ** 2).mean())) if x.size else 0.0
    assert luma(3.0) > 200 and luma(7.0) < 160 and luma(7.9) < 40, (luma(3.0), luma(7.0), luma(7.9))
    assert rms(7.8, 7.98) < rms(3.0, 3.2) * 0.25 and rms(0.0, 0.1) < rms(3.0, 3.2) * 0.5
    print("✓ exportado: la imagen acaba en negro y el sonido sube al principio y baja al final")

    # --- candados y herramientas ---
    tl.set_selection([])
    ctrl.set_track_props(v1.id, "Bloquear pista", locked=True)
    pump(app, 0.2)
    img = tl.grab().toImage()
    lock_r, _vis = tl._header_buttons(p.track_index(v1.id))
    c_lock = img.pixelColor(int(lock_r.center().x()), int(lock_r.bottom() - 3))
    i_free = next(i for i, t in enumerate(p.tracks) if not t.locked)
    free_r, _ = tl._header_buttons(i_free)
    c_free = img.pixelColor(int(free_r.center().x()), int(free_r.bottom() - 3))
    assert c_lock.red() > c_lock.blue() + 25, c_lock.name()
    assert abs(c_free.red() - c_free.blue()) < 25, c_free.name()
    print("✓ candado: gris discreto si la pista está libre; ámbar solo si está bloqueada")
    assert win.tool_snap.objectName() == "tltool" and "tltool:checked" in app.styleSheet()
    print("✓ herramientas activas (selección, imán, enlace…): un poco más claras, sin borde naranja")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
