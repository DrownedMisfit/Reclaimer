"""
Prueba de ⊞ Composición: el visor enseña los huecos (2, 3, 4, 6 o 9) con un «+»; soltar algo de Medios en un
hueco lo pone ahí (en su pista propia «⊞ Composición»); fuera de los huecos va de fondo («⊞ Fondo», debajo);
se exporta tal cual; Ctrl+Z.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_composition.py <carpeta_salida>
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

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
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
    from editoria.core import transform
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.common import MEDIA_MIME
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    s4 = transform.comp_slots(4, 1920, 1080)
    s3v = transform.comp_slots(3, 1080, 1920)
    assert len(s4) == 4 and len(transform.comp_slots(9, 1920, 1080)) == 9
    assert all(abs(s["x"] - s3v[0]["x"]) < 1e-6 for s in s3v), "en vertical van unos encima de otros"
    print("✓ plantillas de 2, 3, 4, 6 y 9 huecos (en vertical, unos encima de otros)")

    red = os.path.join(out, "rojo.png")
    blue = os.path.join(out, "azul.png")
    for path, col in ((red, "red"), (blue, "blue")):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x320",
                        "-frames:v", "1", path], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 950)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        ctrl.set_project_format("short")
        p = ctrl.project
        rid, bid = ctrl.import_now([red, blue])
        pump(app, 0.3)
        pv = win.preview
        pv.set_composition(4)
        cv = pv.canvas
        assert cv.comp.isVisible() and len(cv.comp.slots) == 4
        pump(app, 0.2)
        cv.grab().save(os.path.join(out, "huecos.png"))

        def drop(mid, scene_pt):
            md = QMimeData()
            md.setData(MEDIA_MIME, mid.encode())
            pos = QPointF(cv.mapFromScene(scene_pt))
            cv.dropEvent(QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
            pump(app, 0.1)
        slot = cv.comp.slots[1]
        drop(rid, cv.comp.rect_of(slot).center())
        drop(bid, QPointF(p.width * 0.01, p.height * 0.005))          # fuera de los huecos → fondo
        comp = [t for t in p.tracks if t.role == "comp"]
        bg = [t for t in p.tracks if t.role == "fondo"]
        assert comp and bg and comp[0].name.startswith("⊞") and bg[0].name.startswith("⊞")
        rc = p.clips_on(comp[0].id)[0]
        assert rc.media_id == rid and rc.layout["x"] == slot["x"] and rc.layout["w"] == slot["w"]
        bc = p.clips_on(bg[0].id)[0]
        assert bc.media_id == bid and bc.layout["w"] == 1.0
        vtracks = [t for t in p.tracks if t.kind == "video"]
        assert vtracks[0].role == "comp" and vtracks[-1].role == "fondo", [t.name for t in vtracks]
        print("✓ soltar en el hueco 2 → «⊞ Composición» con ese encuadre; fuera de los huecos → «⊞ Fondo» (debajo)")
        tl = win.timeline
        idx = {t.id: i for i, t in enumerate(p.tracks)}
        mains = [t for t in p.tracks if t.kind == "video" and t.role not in ("comp", "fondo")]
        auds = [t for t in p.tracks if t.kind == "audio"]
        assert tl.view_mode() == "comp" and win.view_comp.isVisibleTo(win) and win.view_comp.isChecked()
        assert tl.track_h(idx[comp[0].id]) > 0 and tl.track_h(idx[bg[0].id]) > 0
        assert all(tl.track_h(idx[t.id]) == 0 for t in mains) and all(tl.track_h(idx[t.id]) > 0 for t in auds)
        tl.set_view("main")
        assert tl.track_h(idx[comp[0].id]) == 0 and all(tl.track_h(idx[t.id]) > 0 for t in mains)
        assert win.view_main.isChecked() and not win.view_comp.isChecked() and "(2)" in win.view_comp.text() and "Pistas de composición" in win.view_comp.text() and "Pistas de composición" in win.view_comp.text()
        tl.repaint()
        print("✓ la composición tiene su propia línea de tiempo: «⊞ Pistas de composición (2)» enseña solo sus pistas (y el "
              "audio); «▤ Principal», tu montaje sin ellas")

        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=270, height=480, fps=30, encoder="cpu",
                                                  loudnorm=False), M.ffmpeg(), os.path.join(out, "f.txt"))
        subprocess.run(args, check=True, capture_output=True)
        fr = M.frame_rgb(mp4, 1.0, 270).astype(int)
        h, w = fr.shape[:2]
        cx, cy = int((slot["x"] + slot["w"] / 2) * w), int((slot["y"] + slot["h"] / 2) * h)
        assert fr[cy, cx][0] > 180 and fr[cy, cx][2] < 80, ("rojo en su hueco", fr[cy, cx])
        corner = fr[2, 2]
        assert corner[2] > 150 and corner[0] < 80, ("el fondo azul alrededor", corner)
        print("✓ exportado: la imagen en su hueco y el fondo detrás")
        ctrl.undo_stack.undo()
        ctrl.undo_stack.undo()
        assert not p.clips
        pv.set_composition(0)
        assert not cv.comp.isVisible()
        print("✓ Ctrl+Z quita lo puesto; «Sin composición» quita los huecos")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
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
