"""
Prueba de ↔ ↕ DEFORMAR el video en el visor (estirar o aplastar a lo ancho o a lo alto):
  · las asas a media arista cambian SOLO el ancho (o solo el alto) y la imagen se estira hasta llenar la caja
    (sin bandas negras); la arista contraria se queda quieta; un solo paso de Ctrl+Z;
  · Shift + esquina: ancho y alto por separado; las esquinas sin Shift siguen sin deformar;
  · al exportar sale igual de deformado que en el visor; «Sin deformar» le devuelve su proporción.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_stretch.py <carpeta_salida>
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

from PySide6.QtCore import QPointF, Qt  # noqa: E402
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
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    low = os.path.join(out, "verde.mp4")
    top_f = os.path.join(out, "rojo_azul.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", low], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-filter_complex",       # mitad roja | mitad azul
                    "color=c=red:s=160x180:d=4[a];color=c=blue:s=160x180:d=4[b];[a][b]hstack",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", top_f], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, canvas = win.ctrl, win.preview.canvas
    p = ctrl.project
    p.width, p.height = 320, 180
    gid, rid = ctrl.import_now([low, top_f])
    while ctrl.analyzing:
        pump(app, 0.1)
    v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
    ctrl.add_media([gid], v1.id, 0.0)
    top = ctrl.add_media([rid], v2.id, 0.0)[0]
    win.timeline.set_selection([top])
    win.engine.seek(1.0)
    pump(app, 0.4)
    assert canvas._tf and canvas._tf["clip"] == top
    vp = canvas.viewport()

    def at(x, y):
        return canvas.mapFromScene(QPointF(x * canvas.W, y * canvas.H))

    def drag(a, b, mods=Qt.NoModifier):
        QTest.mousePress(vp, Qt.LeftButton, mods, at(*a))
        for k in range(1, 6):
            QTest.mouseMove(vp, at(a[0] + (b[0] - a[0]) * k / 5, a[1] + (b[1] - a[1]) * k / 5))
            pump(app, 0.03)
        QTest.mouseRelease(vp, Qt.LeftButton, mods, at(*b))
        pump(app, 0.3)

    def export(name):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        return M.frame_rgb(mp4, 1.0, 320).astype(int)

    def is_col(px, col):
        r, g, b = px[:3]
        return {"red": r > 170 and g < 90 and b < 90, "blue": b > 170 and r < 90,
                "green": g > 90 and r < 80 and b < 80}[col]

    # 1) asa derecha (a media arista) hasta la mitad: solo el ancho; la imagen se APLASTA (sin bandas)
    n0 = ctrl.undo_stack.count()
    drag((0.999, 0.5), (0.5, 0.5))
    lay = p.clips[top].layout
    assert lay and lay.get("fit") == "stretch", lay
    assert abs(lay["w"] - 0.5) < 0.04 and abs(lay["h"] - 1.0) < 0.01 and abs(lay["x"]) < 0.01, lay
    assert ctrl.undo_stack.count() == n0 + 1, "un solo paso de Ctrl+Z"
    layer = canvas.layers[v2.id]
    cr, br = layer.content_rect, layer.box.rect()
    assert abs(cr.width() - br.width()) < 1.5 and abs(cr.height() - br.height()) < 1.5, (cr, br)
    print(f"✓ asa derecha: solo el ancho ({lay['w']:.2f} × {lay['h']:.2f}), la imagen llena la caja (aplastada)")
    fr = export("ancho.mp4")
    for (x, y), col in (((40, 15), "red"), ((40, 165), "red"), ((120, 90), "blue"), ((240, 90), "green")):
        assert is_col(fr[y, x], col), ((x, y), col, fr[y, x])
    print("✓ al exportar: rojo|azul aplastado en la mitad izquierda (de arriba abajo), lo de debajo a la derecha")

    # 2) asa de abajo hacia arriba: ahora solo el alto
    drag((0.25, 0.999), (0.25, 0.6))
    lay2 = p.clips[top].layout
    assert abs(lay2["h"] - 0.6) < 0.04 and abs(lay2["w"] - lay["w"]) < 0.01 and abs(lay2["y"]) < 0.01, lay2
    fr = export("alto.mp4")
    assert is_col(fr[15, 40], "red") and is_col(fr[95, 40], "red") and is_col(fr[160, 40], "green"), fr[160, 40]
    print(f"✓ asa de abajo: solo el alto ({lay2['w']:.2f} × {lay2['h']:.2f}); exportado igual")

    # 3) esquina SIN Shift: escala sin cambiar la proporción de la caja · con Shift: libre
    ratio = lay2["w"] / lay2["h"]
    drag((lay2["w"] - 0.001, lay2["h"] - 0.001), (lay2["w"] * 0.8, lay2["h"] * 0.6))
    lay3 = p.clips[top].layout
    assert abs(lay3["w"] / lay3["h"] - ratio) < 0.03, (lay3, ratio)
    drag((lay3["w"] - 0.001, lay3["h"] - 0.001), (0.9, lay3["h"]), Qt.ShiftModifier)
    lay4 = p.clips[top].layout
    assert lay4["w"] > 0.85 and abs(lay4["h"] - lay3["h"]) < 0.02 and lay4["fit"] == "stretch", lay4
    print("✓ esquina: mantiene la forma · Shift+esquina: ancho y alto por separado")

    # 4) «Sin deformar» (inspector) y Ctrl+Z
    win.timeline.set_selection([])
    win.timeline.set_selection([top])
    pump(app, 0.3)
    assert not win.inspector.btn_unstretch.isHidden(), "el botón aparece si está deformado"
    win.inspector.btn_unstretch.click()
    pump(app, 0.2)
    assert p.clips[top].layout["fit"] == "contain", p.clips[top].layout
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert p.clips[top].layout["fit"] == "stretch"
    print("✓ «Sin deformar» le devuelve su proporción · Ctrl+Z vuelve a deformarlo")

    # 5) un clip con posición animada (claves): deformarlo en el visor queda en la clave y en el clip
    p.clips[top].layout = None
    ctrl.animate_layout(top, 1.0)
    pump(app, 0.3)
    win.timeline.set_selection([])
    win.timeline.set_selection([top])
    pump(app, 0.4)
    drag((0.999, 0.5), (0.7, 0.5))
    c = p.clips[top]
    assert c.layout.get("fit") == "stretch" and c.layout_kf and any(abs(k["w"] - 0.7) < 0.05 for k in c.layout_kf), \
        (c.layout, c.layout_kf)
    fr = export("animado.mp4")
    assert is_col(fr[15, 60], "red") and is_col(fr[15, 170], "blue") and is_col(fr[90, 300], "green"), fr[15, 170]
    print("✓ con claves de posición: la deformación queda en la clave y se exporta igual")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
