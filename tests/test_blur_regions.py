"""
Prueba del «◌ Desenfoque en zona» (cuadro y círculo): se exporta desenfocado solo en la zona, el visor lo
muestra, y se arrastra con el ratón en el visor (dentro = mover, esquina = tamaño) con deshacer.
Usa una carpeta de datos TEMPORAL.
Ejecutar:  .venv/Scripts/python.exe tests/test_blur_regions.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def sharp(img: np.ndarray) -> float:
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def grab_rgb(widget) -> np.ndarray:
    img = widget.grab().toImage().convertToFormat(widget.grab().toImage().Format.Format_RGB888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return a[:, :w * 3].reshape(h, w, 3).copy()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    vid = os.path.join(out, "detalle.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=1280x720:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
                        "-pix_fmt", "yuv420p", vid], check=True)
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    ctrl = win.ctrl
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media(ids, v1.id, 0.0)
    c = ctrl.project.clips_on(v1.id)[0]
    win.timeline.set_selection([c.id])
    pump(app, 0.2)

    # Añadir un cuadro y un círculo desde Efectos
    win.effects.add_region("rect")
    win.effects.add_region("ellipse")
    regs = ctrl.project.clips[c.id].fx["blur_regions"]
    assert [r["shape"] for r in regs] == ["rect", "ellipse"]
    fx = dict(ctrl.project.clips[c.id].fx)
    fx["blur_regions"] = [dict(regs[0], x=0.25, y=0.5, w=0.3, h=0.5), dict(regs[1], x=0.75, y=0.5)]
    ctrl.set_clip_props([c.id], "zonas", fx=fx)
    pump(app, 0.3)

    # Exportar y comparar con el original: zonas borrosas, el resto igual
    mp4 = os.path.join(out, "zonas.mp4")
    args, _t = build_command(ctrl.project, ExportOptions(path=mp4, width=1280, height=720, fps=30, encoder="cpu",
                                                         bitrate_mbps=12), media_tools.ffmpeg(),
                             os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]
    f_out = media_tools.frame_rgb(mp4, 2.0, 1280)
    f_in = media_tools.frame_rgb(vid, 2.0, 1280)
    H, W = f_out.shape[:2]

    def area(img, cx, cy, w, h):
        return img[int((cy - h / 2) * H) + 4:int((cy + h / 2) * H) - 4, int((cx - w / 2) * W) + 4:int((cx + w / 2) * W) - 4]
    s_rect = sharp(area(f_out, 0.25, 0.5, 0.2, 0.3)), sharp(area(f_in, 0.25, 0.5, 0.2, 0.3))
    circ = fx["blur_regions"][1]
    s_circ = sharp(area(f_out, 0.75, 0.5, circ["w"] * 0.5, circ["h"] * 0.5)), sharp(area(f_in, 0.75, 0.5, circ["w"] * 0.5, circ["h"] * 0.5))
    s_mid = sharp(area(f_out, 0.5, 0.12, 0.12, 0.15)), sharp(area(f_in, 0.5, 0.12, 0.12, 0.15))
    assert s_rect[0] < s_rect[1] * 0.35 and s_circ[0] < s_circ[1] * 0.35, (s_rect, s_circ)
    assert s_mid[0] > s_mid[1] * 0.6, s_mid
    cv2.imwrite(os.path.join(out, "exportado.png"), cv2.cvtColor(f_out, cv2.COLOR_RGB2BGR))
    print(f"✓ exportado: cuadro y círculo desenfocados (nitidez {s_rect[0]:.0f} vs {s_rect[1]:.0f} y "
          f"{s_circ[0]:.0f} vs {s_circ[1]:.0f}); fuera de las zonas igual ({s_mid[0]:.0f} vs {s_mid[1]:.0f})")

    # El visor también lo muestra
    canvas = win.preview.canvas
    win.engine.seek(2.0)
    pump(app, 1.2)
    shot = grab_rgb(canvas)
    canvas.grab().save(os.path.join(out, "visor_zonas.png"))
    layer = canvas.layers[v1.id]
    sr = canvas.mapFromScene(layer.box.mapRectToScene(layer.box.rect())).boundingRect()
    vh, vw = shot.shape[:2]

    def varea(cx, cy, w, h):
        x0, y0 = sr.left() + (cx - w / 2) * sr.width(), sr.top() + (cy - h / 2) * sr.height()
        return shot[max(0, int(y0)):int(y0 + h * sr.height()), max(0, int(x0)):int(x0 + w * sr.width())]
    v_in, v_out = sharp(varea(0.25, 0.5, 0.2, 0.3)), sharp(varea(0.5, 0.12, 0.12, 0.15))
    if v_out > 50:      # sin pantalla real puede que no se pinte el video
        assert v_in < v_out * 0.5, (v_in, v_out)
        print(f"✓ visor: la zona se ve desenfocada (nitidez {v_in:.0f} frente a {v_out:.0f} fuera)")
    else:
        print("· visor: sin imagen de video en esta prueba (solo se comprueba el arrastre)")
    assert len(canvas.reg_overlay.shapes) == 2, "se ven los contornos para arrastrar"

    # Arrastrar: mover el cuadro (desde su centro) y agrandar el círculo (desde su esquina)
    def vp(scene_pt: QPointF) -> QPoint:
        return canvas.mapFromScene(scene_pt)
    rects = canvas._reg_rects()
    start = vp(rects[0].center())
    end = start + QPoint(int(sr.width() * 0.1), int(sr.height() * 0.05))
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(canvas.viewport(), start + QPoint(5, 2))
    QTest.mouseMove(canvas.viewport(), end)
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, end)
    pump(app, 0.2)
    r0 = ctrl.project.clips[c.id].fx["blur_regions"][0]
    assert abs(r0["x"] - 0.35) < 0.03 and abs(r0["y"] - 0.55) < 0.03, r0
    rects = canvas._reg_rects()
    corner = vp(rects[1].bottomRight())
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, corner)
    QTest.mouseMove(canvas.viewport(), corner + QPoint(-20, -20))
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, corner + QPoint(-20, -20))
    pump(app, 0.2)
    r1 = ctrl.project.clips[c.id].fx["blur_regions"][1]
    assert r1["w"] < circ["w"] - 0.01, (r1, circ)
    ctrl.undo_stack.undo()
    assert abs(ctrl.project.clips[c.id].fx["blur_regions"][1]["w"] - circ["w"]) < 1e-3
    print(f"✓ arrastre en el visor: mover (x {regs and 0.25:.2f}→{r0['x']:.2f}) y cambiar tamaño desde la esquina; Ctrl+Z")
    win.effects.clear_regions()
    assert not (ctrl.project.clips[c.id].fx or {}).get("blur_regions") and not canvas.reg_overlay.shapes

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    st = QSettings("EditorIA", "EditorIA")
    for k in ("ventana/paneles", "guia/colocada", "geometry", "efectos/zona_intensidad"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
