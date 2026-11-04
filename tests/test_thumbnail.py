"""
Prueba del taller de miniaturas (fase 1: lienzo, capas, texto, ratón, deshacer, exportar, guardar).
Ejecutar:  .venv/Scripts/python.exe tests/test_thumbnail.py <carpeta_salida>
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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import thumbnail as T  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    vid = os.path.join(out, "juego.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "mandelbrot=s=1920x1080:r=30", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", vid],
                   check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    [mid] = ctrl.import_now([vid])
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([mid], v1.id, 0.0)
    win.engine.seek(1.5)
    pump(app, 0.3)

    ed = win.open_thumbnail("youtube")
    win.showNormal()                       # (el taller es una página de la ventana principal: se amplía ella)
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    assert win.central_stack.currentWidget() is ed and not win.docks["media"].isVisible(), "página Miniatura"
    assert (ed.doc["w"], ed.doc["h"]) == (1280, 720)
    # Fondo (doble clic) = fotograma del visor llenando el lienzo; y otro encima
    frame = ed.grab_frame(1.5)
    assert frame and os.path.exists(frame)
    ed.add_image(frame, "Fondo", fill=True)
    ed.layer(ed.canvas.sel)["adj"].update(blur=0.3, exposure=-0.5)
    ed.add_image(frame, "Sujeto")
    sujeto = ed.cur()
    ed.add_text("¿TODO MAL?", "title")
    title = ed.cur()
    assert [l["kind"] for l in ed.doc["layers"]] == ["image", "image", "text"]
    print("✓ fondo con un fotograma del visor, imagen encima y título")

    # Mover con el ratón (se pega al centro) y escalar desde una esquina
    cv = ed.canvas
    pump(app, 0.2)

    def to_view(x, y):
        return cv.mapFromScene(x, y)
    x0, y0 = title["x"], title["y"]
    a = to_view(x0, y0)
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(cv.viewport(), to_view(x0 + 100, y0 + 52))
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(x0 + 100, y0 + 52))
    assert abs(title["x"] - (x0 + 100)) < 4 and abs(title["y"] - 240) < 1e-6, (title["x"], title["y"])
    print("✓ arrastrar mueve el texto (y se pegó a la línea de los tercios)")
    s0 = title["scale"]
    corner = cv._handles(title)["corners"][2]
    c = cv._handles(title)["center"]
    far = c + (corner - c) * 1.5
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(corner.x(), corner.y()))
    QTest.mouseMove(cv.viewport(), to_view(far.x(), far.y()))
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(far.x(), far.y()))
    assert abs(title["scale"] / s0 - 1.5) < 0.1, title["scale"] / s0
    print(f"✓ esquina = tamaño (×{title['scale'] / s0:.2f})")

    # Propiedades y deshacer / rehacer
    ed._set(sujeto, "Contorno", **{"outline.on": True, "outline.width": 10})
    ed._set(sujeto, "Ajustes", **{"adj.contrast": 0.2})
    n = len(ed.history)
    ed.undo()
    ed.undo()
    assert not ed.layer(sujeto["id"])["outline"]["on"]
    ed.redo()
    ed.redo()
    assert ed.layer(sujeto["id"])["outline"]["on"] and ed.layer(sujeto["id"])["adj"]["contrast"] == 0.2
    print(f"✓ deshacer / rehacer ({n} pasos en el historial)")
    ed.canvas.sel = ed.doc["layers"][1]["id"]
    ed.duplicate()
    assert len(ed.doc["layers"]) == 4
    ed.delete_layer()
    assert len(ed.doc["layers"]) == 3
    ed.align("r")
    print("✓ duplicar, borrar y alinear")

    # ◇ Deformar: la esquina de arriba a la izquierda, arrastrada; el resto, en su sitio
    lay = ed.layer(ed.canvas.sel) or ed.doc["layers"][-1]
    ed.canvas.sel = lay["id"]
    before = T.render(ed.doc, 0.25)
    ed.toggle_warp(True)
    pump(app, 0.1)
    h = cv._handles(lay)
    c0, c2 = h["corners"][0], h["corners"][2]
    QTest.mousePress(cv.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(c0.x(), c0.y()))
    QTest.mouseMove(cv.viewport(), to_view(c0.x() + 60, c0.y() + 40))
    QTest.mouseRelease(cv.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(c0.x() + 60, c0.y() + 40))
    w = T.warp_of(lay)
    assert w and (w[0][0] > 0 or w[0][1] != 0) and w[2] == [0.0, 0.0], w
    h2 = cv._handles(lay)
    assert abs(h2["corners"][0].x() - (c0.x() + 60)) < 6 and abs(h2["corners"][0].y() - (c0.y() + 40)) < 6, \
        (h2["corners"][0], c0)
    assert abs(h2["corners"][2].x() - c2.x()) < 1 and abs(h2["corners"][2].y() - c2.y()) < 1, "la opuesta, quieta"
    assert T.render(ed.doc, 0.25) != before, "se ve deformada (y se exporta igual: el mismo dibujo)"
    ed.reset_warp()
    assert T.warp_of(lay) is None
    ed.undo()
    lay = ed.layer(lay["id"])
    assert T.warp_of(lay) is not None, "Ctrl+Z vuelve a la deformación"
    ed.reset_warp()
    ed.toggle_warp(False)
    print("✓ ◇ Deformar: una esquina arrastrada (las otras, quietas), se ve y se exporta igual; ↺ la quita; Ctrl+Z")
    ed.grab().save(os.path.join(out, "taller.png"))

    # Exportar (< 2 MB) y guardar con el proyecto
    jpg = os.path.join(out, "miniatura.jpg")
    nbytes = T.export(ed.doc, jpg)
    assert 0 < nbytes <= T.MAX_BYTES
    print(f"✓ exportada: {nbytes / 1024:.0f} KB (límite de YouTube: 2 MB)")
    ed.close()
    path = os.path.join(out, "proyecto.eia")
    ctrl.save(path)
    ctrl.load(path)
    assert len(ctrl.project.thumbnails["youtube"]["layers"]) == 3
    ed2 = win.open_thumbnail("youtube")
    assert len(ed2.doc["layers"]) == 3
    ed2.fmt.setCurrentIndex(ed2.fmt.findData("short"))
    assert (ed2.doc["w"], ed2.doc["h"]) == (1080, 1920) and not ed2.doc["layers"]
    print("✓ se guarda con el proyecto; YouTube y Shorts por separado")
    win.go_page("edit")                    # salir de la página: el editor vuelve como estaba
    pump(app, 0.2)
    assert win.central_stack.currentWidget() is win.preview and win.docks["media"].isVisible()
    assert len(ctrl.project.thumbnails["short"]["layers"]) == 0 and win._thumb_page is None
    print("✓ 🖼 la miniatura es una página: ocupa la ventana y al volver a «Editar» los paneles vuelven")
    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
