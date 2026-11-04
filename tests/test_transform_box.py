"""
Prueba de lo del video «ejemplo de mejora para funciones Reclaimer» (como en Resolve):
  · ⤧ Inspector → Transformar: Tamaño con 🔗 (sin deformar) y sin 🔗 (aplastar), Posición, Rotación, Voltear; varios
    cambios seguidos = un solo Ctrl+Z; al exportar sale volteado y girado (y en las esquinas se ve lo de debajo);
  · ▦ Relleno (Efectos → Imagen): lo vacío alrededor del clip aplastado se llena con la propia imagen desenfocada,
    en el visor y al exportar; no se pone solo;
  · 👆 clic en una capa del visor = seleccionarla; Ctrl+clic = la de debajo.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_transform_box.py <carpeta_salida>
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
    from editoria.core import fill as FILL
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "verde.mp4")        # abajo: verde con una franja blanca arriba (para ver el relleno)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=0x20a040:s=320x180:d=4,drawbox=x=0:y=0:w=320:h=40:color=white:t=fill",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    img = os.path.join(out, "rojo_azul.png")    # encima: mitad roja | mitad azul (para ver el volteo)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-filter_complex",
                    "color=c=red:s=100x100[a];color=c=blue:s=100x100[b];[a][b]hstack", "-frames:v", "1", img],
                   check=True)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.3)
    ctrl, p, ins, canvas = win.ctrl, win.ctrl.project, win.inspector, win.preview.canvas
    p.width, p.height = 320, 180
    vid_id, img_id = ctrl.import_now([vid, img])
    while ctrl.analyzing:
        pump(app, 0.1)
    v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
    low = next(i for i in ctrl.add_media([vid_id], v1.id, 0.0) if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    top = ctrl.add_media([img_id], v2.id, 0.0)[0]
    assert p.clips[top].layout == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "contain", "bg": "none"}
    print("✓ al añadir, sin efectos automáticos: la imagen entera y alrededor se ve lo de debajo")

    def export(name, t=1.0):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1200:]
        return M.frame_rgb(mp4, t, 320).astype(int)

    # 👆 clic en el visor: selecciona la imagen (encima); Ctrl+clic, el video (debajo)
    win.engine.seek(1.0)
    pump(app, 0.4)
    win.preview.set_mode("transform") if hasattr(win.preview, "set_mode") else canvas.set_mode("transform")
    vp = canvas.viewport()
    pt = canvas.mapFromScene(QPointF(160, 90))
    win.timeline.set_selection([])
    pump(app, 0.2)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pt)
    pump(app, 0.3)
    assert top in win.timeline.selected, win.timeline.selected
    QTest.mouseClick(vp, Qt.LeftButton, Qt.ControlModifier, pt)
    pump(app, 0.3)
    assert low in win.timeline.selected and top not in win.timeline.selected, win.timeline.selected
    print("✓ clic en una capa del visor = seleccionarla · Ctrl+clic = la de debajo")

    # ⤧ Transformar (Inspector) sobre la imagen
    win.timeline.set_selection([top])
    pump(app, 0.3)
    tb = ins.transform_box
    assert not tb.isHidden(), "la sección Transformar aparece con un clip de imagen/video"
    n0 = ctrl.undo_stack.count()
    tb.w.setValue(50)                               # 🔗 enlazado: no deforma
    pump(app, 0.1)
    lay = p.clips[top].layout
    assert abs(lay["w"] - 0.5) < 0.01 and abs(lay["h"] - 0.5) < 0.01 and abs(lay["x"] - 0.25) < 0.01, lay
    tb.px.setValue(-60)
    tb.rot.setValue(20)
    pump(app, 0.1)
    assert ctrl.undo_stack.count() == n0 + 1, "varios cambios seguidos = un solo Ctrl+Z"
    lay = p.clips[top].layout
    assert abs((lay["x"] + lay["w"] / 2 - 0.5) * 320 + 60) < 1.5 and abs(lay["rot"] - 20) < 0.01, lay
    print("✓ Tamaño con 🔗 (sin deformar), Posición y Rotación · todo en un solo paso de Ctrl+Z")
    tb.rot.setValue(0)
    tb.px.setValue(0)
    tb.link.setChecked(False)
    tb.h.setValue(30)                               # sin 🔗: aplastar
    pump(app, 0.1)
    lay = p.clips[top].layout
    assert lay["fit"] == "stretch" and abs(lay["h"] - 0.3) < 0.01, lay
    tb.fh.setChecked(True)
    pump(app, 0.1)
    assert p.clips[top].layout.get("flip_h")
    fr = export("volteado.mp4")
    cy = int((lay["y"] + lay["h"] / 2) * 180)
    left, right = fr[cy, int((lay["x"] + 0.1 * lay["w"]) * 320)], fr[cy, int((lay["x"] + 0.9 * lay["w"]) * 320)]
    assert left[2] > 150 and left[0] < 90 and right[0] > 150 and right[2] < 90, (left, right)
    assert fr[5, 5][1] > 150, ("alrededor se ve el video de debajo", fr[5, 5])
    print("✓ sin 🔗 se aplasta · ↔ voltear: al exportar, el azul a la izquierda y el rojo a la derecha")
    tb.fh.setChecked(False)
    tb.rot.setValue(45)
    pump(app, 0.1)
    fr = export("girado.mp4")
    lay = p.clips[top].layout
    cx = int((lay["x"] + lay["w"] / 2) * 320)
    cy = int((lay["y"] + lay["h"] / 2) * 180)
    assert fr[cy, cx][0] > 120 or fr[cy, cx][2] > 120, ("el centro sigue siendo la imagen", fr[cy, cx])
    assert fr[3, 3][1] > 120, ("las esquinas, lo de debajo", fr[3, 3])
    print("✓ ⟳ girada 45°: al exportar, la imagen en su sitio y lo de debajo alrededor")

    # ▦ Relleno en el video de abajo, aplastado
    win.timeline.set_selection([low])
    pump(app, 0.2)
    ctrl.set_clip_layout(low, {"x": 0.0, "y": 0.3, "w": 1.0, "h": 0.4, "fit": "stretch", "bg": "none"})
    ctrl.delete_clips([top])
    fr = export("aplastado.mp4")
    assert fr[10, 160].mean() < 25, ("sin relleno, arriba negro", fr[10, 160])
    win.effects.add_fill()
    pump(app, 0.2)
    assert FILL.of(p.clips[low].fx)
    win.engine.seek(1.2)
    pump(app, 0.6)
    layer = canvas.layers[v1.id]
    assert layer.fill.isVisible(), "el visor enseña el relleno"
    fr = export("relleno.mp4")
    assert fr[10, 160][1] > 60, ("arriba, la imagen desenfocada (verde)", fr[10, 160])
    print(f"✓ ▦ Relleno: lo vacío arriba y abajo se llena con la propia imagen (arriba {tuple(int(v) for v in fr[10, 160])})")
    ins.transform_box.refresh()
    assert ins.transform_box.fill_on.isChecked()
    ins.transform_box.fill_on.setChecked(False)
    pump(app, 0.2)
    assert not FILL.of(p.clips[low].fx)
    print("✓ el relleno se quita desde el Inspector (⤧ Transformar)")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
