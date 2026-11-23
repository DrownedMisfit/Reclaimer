"""
Prueba del visor (modo Transformar) como en Resolve, con lo que pidió el usuario («antes que recortar las estiran»):
  · en un proyecto vertical con una imagen horizontal, el recuadro va en lo que SE VE (la franja), no en todo el cuadro;
  · arrastrar un LADO recorta ese lado (sin deformar y sin mover la imagen); un solo Ctrl+Z;
  · arrastrar una ESQUINA cambia el tamaño sin deformar;
  · Alt + lado = estirar (deformar), solo a propósito.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_visor_recortar_sin_estirar.py <carpeta>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else _TMP
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ruta = os.path.join(out, "horizontal.png")
    Image.fromarray(np.full((1080, 1920, 3), (40, 160, 220), np.uint8)).save(ruta)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, cv = win.ctrl, win.preview.canvas
    ctrl.set_project_format("short")
    cv.set_canvas_size(ctrl.project.width, ctrl.project.height)
    (mid,) = ctrl.import_now([ruta])
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    (cid,) = [i for i in ctrl.add_media([mid], v1.id, 0.0) if ctrl.project.clips[i].media_id == mid]
    win.engine.seek(1.0)
    win.timeline.set_selection([cid])
    pump(app, 0.6)
    W, H = cv.W, cv.H
    r = cv.tf_overlay.r
    assert r is not None and abs(r.width() - W) < 2 and abs(r.height() - W * 1080 / 1920) < 3, r
    print(f"✓ el recuadro va en lo que se ve ({r.width():.0f}×{r.height():.0f}), no en todo el cuadro ({W}×{H})")
    vp = cv.viewport()
    # ⚡ menú rápido del clip en el hueco de la derecha: a la vista, sin tapar la imagen; sin clip, nada
    mr = win.menu_rapido
    fr = cv.mapFromScene(cv.frame.rect()).boundingRect()
    assert mr is not None and mr.isVisible() and mr.geometry().left() > fr.right(), (mr.geometry(), fr)
    assert mr.geometry().right() < vp.width() and not mr.botones["velocidad"].isVisibleTo(mr), "una imagen: sin Velocidad"
    win.timeline.set_selection([])
    pump(app, 0.3)
    assert not mr.isVisible(), "sin clip elegido: ningún panel vacío"
    win.timeline.set_selection([cid])
    pump(app, 0.3)
    mr.botones["recortar"].click()
    pump(app, 0.2)
    assert cv.mode == "crop" and mr.botones["recortar"].isChecked()
    mr.botones["transformar"].click()
    pump(app, 0.2)
    assert cv.mode == "transform"
    print("✓ menú rápido a la derecha del cuadro (sin taparlo), oculto sin clip; sus modos son los del visor")

    def at(x, y):
        return cv.mapFromScene(QPointF(x, y))

    def drag(a, b, mods=Qt.NoModifier):
        QTest.mousePress(vp, Qt.LeftButton, mods, at(*a))
        for k in range(1, 6):
            QTest.mouseMove(vp, at(a[0] + (b[0] - a[0]) * k / 5, a[1] + (b[1] - a[1]) * k / 5), -1)
            pump(app, 0.02)
        QTest.mouseRelease(vp, Qt.LeftButton, mods, at(*b))
        pump(app, 0.3)

    n0 = ctrl.undo_stack.count()
    cy = r.center().y()
    drag((r.right() - 2, cy), (r.right() - 0.25 * W, cy))
    lay = ctrl.project.clips[cid].layout
    assert lay.get("fit", "contain") == "contain" and lay.get("crop") and lay["crop"]["r"] > 0.2, lay
    assert abs(lay["w"] * W / (lay["h"] * H) - 1920 / 1080) < 0.02, ("la caja sigue con la forma de la imagen", lay)
    assert ctrl.undo_stack.count() == n0 + 1, "un solo paso de Ctrl+Z"
    r2 = cv.tf_overlay.r
    assert abs(r2.left() - r.left()) < 2 and r2.right() < r.right() - 0.2 * W, (r, r2)
    print(f"✓ lado derecho = recorte ({lay['crop']['r']:.2f}), sin deformar ni mover la imagen; un Ctrl+Z")
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    assert (ctrl.project.clips[cid].layout or {}).get("crop") is None
    r = cv.tf_overlay.r
    drag((r.right(), r.bottom()), (r.right() - 0.4 * W, r.bottom() - 0.4 * W))
    lay = ctrl.project.clips[cid].layout
    assert lay.get("fit", "contain") == "contain" and not lay.get("crop"), lay
    r3 = cv.tf_overlay.r
    assert abs(r3.width() / r3.height() - 1920 / 1080) < 0.03 and r3.width() < 0.75 * W, r3
    assert abs(r3.left() - r.left()) < 2 and abs(r3.top() - r.top()) < 2, ("la esquina contraria quieta", r, r3)
    print(f"✓ esquina = tamaño sin deformar ({r3.width():.0f}×{r3.height():.0f}), la esquina contraria quieta")
    drag((r3.left(), r3.center().y()), (r3.left() - 0.15 * W, r3.center().y()), Qt.AltModifier)
    assert ctrl.project.clips[cid].layout.get("fit") == "stretch", ctrl.project.clips[cid].layout
    print("✓ Alt + lado = estirar (solo a propósito)")
    ctrl.undo_stack.setClean()               # (sin «¿guardar cambios?» al cerrar)
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
