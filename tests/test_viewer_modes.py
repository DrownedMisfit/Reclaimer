"""
Prueba de los MODOS del visor (abajo a la izquierda, como en DaVinci Resolve):
  · ✂ Recortar: arrastrar el borde derecho esconde ese lado (transparente: se ve la pista de debajo) en el visor
    y al exportar; un paso de Ctrl+Z;
  · 🔍 Zoom dinámico: rectángulo verde (inicio) y rojo (final) → dos claves de zoom;
  · ✏ Anotaciones: dibujar a mano en el visor; se ven solo un rato y no se exportan; «Borrar las de aquí».
Ejecutar:  .venv/Scripts/python.exe tests/test_viewer_modes.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPointF, QSettings, Qt  # noqa: E402
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
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    files = {}
    for col in ("red", "blue"):
        files[col] = os.path.join(out, f"{col}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180:d=4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", files[col]], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, canvas = win.ctrl, win.preview.canvas
        p = ctrl.project
        p.width, p.height = 320, 180
        rid, bid = ctrl.import_now([files["red"], files["blue"]])
        while ctrl.analyzing:
            pump(app, 0.1)
        v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
        ctrl.add_media([rid], v1.id, 0.0)
        top = ctrl.add_media([bid], v2.id, 0.0)[0]
        win.timeline.set_selection([top])
        win.engine.seek(1.0)
        pump(app, 0.4)
        vp = canvas.viewport()

        def at(x, y):
            return canvas.mapFromScene(QPointF(x * canvas.W, y * canvas.H))

        # ✂ Recortar: borde derecho hacia dentro un 30 %
        canvas.set_mode("crop")
        pump(app, 0.2)
        assert win.preview.btn_mode.text().startswith("✂")
        n0 = ctrl.undo_stack.count()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at(0.999, 0.5))
        for k in range(1, 6):
            QTest.mouseMove(vp, at(0.999 - 0.06 * k, 0.5))
            pump(app, 0.02)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at(0.70, 0.5))
        pump(app, 0.3)
        cr = (p.clips[top].layout or {}).get("crop")
        assert cr and 0.25 < cr["r"] < 0.35 and cr["l"] == 0, p.clips[top].layout
        assert ctrl.undo_stack.count() == n0 + 1
        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        fr = M.frame_rgb(mp4, 1.0, 320).astype(int)
        assert fr[90, 60][2] > 170, ("lo que se queda: el azul", fr[90, 60])
        assert fr[90, 300][0] > 170 and fr[90, 300][2] < 80, ("lo recortado: se ve el rojo de debajo", fr[90, 300])
        print(f"✓ ✂ Recortar: el borde derecho se esconde ({cr['r']:.0%}) y se ve la pista de debajo (visor y export)")

        # 🔍 Zoom dinámico: mover el rectángulo ROJO (final)
        canvas.set_mode("dynzoom")
        pump(app, 0.3)
        rects = canvas._dz_rects()
        assert len(rects) == 2, canvas._dz
        rb = rects[1]
        start = canvas.mapFromScene(rb.center())
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(vp, canvas.mapFromScene(rb.center() + QPointF(20, 10)))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, canvas.mapFromScene(rb.center() + QPointF(20, 10)))
        pump(app, 0.3)
        kf = p.clips[top].zoom_kf
        assert len(kf) == 2 and kf[0]["z"] < kf[1]["z"], kf
        print(f"✓ 🔍 Zoom dinámico: del verde (×{kf[0]['z']:.2f}) al rojo (×{kf[1]['z']:.2f}) a lo largo del clip")

        # ✏ Anotaciones
        canvas.set_mode("annotate")
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at(0.2, 0.2))
        for k in range(1, 8):
            QTest.mouseMove(vp, at(0.2 + 0.05 * k, 0.2 + 0.03 * k))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at(0.55, 0.41))
        pump(app, 0.2)
        assert len(p.annotations) == 1 and len(p.annotations[0]["strokes"][0]) >= 8
        assert canvas.ann_overlay.items, "se ve en el visor"
        win.engine.seek(4.0)        # dura 3 s desde 1.0
        pump(app, 0.2)
        assert not canvas.ann_overlay.items
        win.engine.seek(1.5)
        pump(app, 0.2)
        win.preview.act_clear_ann.trigger()
        pump(app, 0.1)
        assert not p.annotations
        canvas.set_mode("transform")
        print("✓ ✏ Anotaciones: se dibujan, se ven un rato (no se exportan) y se borran")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
