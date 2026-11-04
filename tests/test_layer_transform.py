"""
Prueba de ⤧ mover / escalar cada capa en el visor (como el «Transform» de Resolve):
  · con un clip seleccionado de la pista de arriba, arrastrarlo en el visor lo MUEVE y deja ver la de debajo;
  · una esquina o la rueda cambian su tamaño sin deformarlo; todo es un solo paso de Ctrl+Z;
  · doble clic = vuelve a pantalla completa; al exportar sale igual que en el visor.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_layer_transform.py <carpeta_salida>
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

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
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
        assert canvas._tf and canvas._tf["clip"] == top, "la capa seleccionada muestra su caja"
        assert canvas.tf_overlay.r is not None

        vp = canvas.viewport()

        def at(x, y):          # punto del lienzo (en píxeles del proyecto) → punto de la ventana del visor
            return canvas.mapFromScene(QPointF(x * canvas.W, y * canvas.H))
        n0 = ctrl.undo_stack.count()
        # arrastrar desde el centro hacia la derecha la mitad del ancho
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at(0.5, 0.5))
        for k in range(1, 6):
            QTest.mouseMove(vp, at(0.5 + 0.1 * k, 0.5))
            pump(app, 0.03)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at(1.0, 0.5))
        pump(app, 0.3)
        lay = p.clips[top].layout
        assert lay and abs(lay["x"] - 0.5) < 0.04 and abs(lay["y"]) < 0.02 and lay.get("bg") == "none", lay
        assert ctrl.undo_stack.count() == n0 + 1, "un solo paso de Ctrl+Z"
        print(f"✓ arrastrar la capa la mueve (x = {lay['x']:.2f}) en un solo paso de Ctrl+Z")
        # exportar: a la izquierda se ve la capa de abajo (rojo), a la derecha la de arriba (azul)
        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        fr = M.frame_rgb(mp4, 1.0, 320).astype(int)
        assert fr[90, 60][0] > 180 and fr[90, 60][2] < 80, ("se ve la capa de abajo", fr[90, 60])
        assert fr[90, 260][2] > 180 and fr[90, 260][0] < 80, ("la de arriba, movida", fr[90, 260])
        print("✓ al exportar: la capa de arriba está movida y se ve la de abajo (igual que en el visor)")
        # esquina inferior derecha hacia dentro → la mitad de tamaño, sin deformar
        b = p.clips[top].layout
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at(b["x"] + b["w"] - 0.001, b["h"] - 0.001))
        QTest.mouseMove(vp, at(b["x"] + b["w"] * 0.75, 0.75))
        QTest.mouseMove(vp, at(b["x"] + b["w"] * 0.5, 0.5))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at(b["x"] + b["w"] * 0.5, 0.5))
        pump(app, 0.3)
        b2 = p.clips[top].layout
        assert abs(b2["w"] - 0.5) < 0.04 and abs(b2["h"] - 0.5) < 0.04 and abs(b2["x"] - b["x"]) < 0.01, b2
        print(f"✓ esquina: tamaño sin deformar ({b2['w']:.2f} × {b2['h']:.2f}), la esquina contraria quieta")
        # rueda: más grande (un solo paso al parar)
        n1 = ctrl.undo_stack.count()
        pos = at(b2["x"] + b2["w"] / 2, b2["y"] + b2["h"] / 2)
        for _ in range(3):
            ev = QWheelEvent(QPointF(pos), QPointF(vp.mapToGlobal(pos)), QPoint(), QPoint(0, 120), Qt.NoButton,
                             Qt.ControlModifier, Qt.NoScrollPhase, False)
            canvas.wheelEvent(ev)
        pump(app, 0.8)
        b3 = p.clips[top].layout
        assert b3["w"] > b2["w"] * 1.1 and ctrl.undo_stack.count() == n1 + 1, (b3, ctrl.undo_stack.count() - n1)
        print("✓ rueda: más grande desde su centro (un solo paso de Ctrl+Z)")
        # doble clic: pantalla completa; Ctrl+Z vuelve
        QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, at(b3["x"] + b3["w"] / 2, b3["y"] + b3["h"] / 2))
        pump(app, 0.3)
        assert p.clips[top].layout is None, p.clips[top].layout
        ctrl.undo_stack.undo()
        pump(app, 0.2)
        assert p.clips[top].layout == b3
        print("✓ doble clic = pantalla completa · Ctrl+Z vuelve")
        # Alt+arrastrar sigue moviendo el encuadre (dentro de la caja), no la capa
        before = dict(p.clips[top].layout)
        QTest.mousePress(vp, Qt.LeftButton, Qt.AltModifier, at(0.6, 0.5))
        QTest.mouseMove(vp, at(0.7, 0.5))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.AltModifier, at(0.7, 0.5))
        pump(app, 0.3)
        assert p.clips[top].layout == before
        print("✓ Alt+arrastrar no mueve la capa (es el encuadre de dentro)")
        # rueda sin teclas: acerca la VISTA del visor (no cambia el video); clic en el % = ajustar
        lay0 = dict(p.clips[top].layout)
        ev = QWheelEvent(QPointF(at(0.5, 0.5)), QPointF(vp.mapToGlobal(at(0.5, 0.5))), QPoint(), QPoint(0, 240),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        canvas.wheelEvent(ev)
        pump(app, 0.1)
        assert canvas.view_zoom > 1.2 and p.clips[top].layout == lay0, canvas.view_zoom
        assert "%" in win.preview.zoom_label.text()
        win.preview.zoom_label.click()
        assert canvas.view_zoom == 1.0 and win.preview.zoom_label.text() == "Ajustar"
        print("✓ rueda = acercar la vista del visor (el video no cambia) · clic en el % = ajustar")
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
