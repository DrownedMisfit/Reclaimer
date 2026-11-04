"""
Prueba del visor:
  · un clip a pantalla completa con ✂ recorte de sujeto (fondo quitado) deja VER la pista de debajo
    (antes el visor daba por hecho que lo tapaba todo y la de debajo ni se cargaba: salía negro);
  · uno normal a pantalla completa sí la tapa (no se reproduce lo que no se ve);
  · el nombre del video/proyecto de la cabecera del visor se cambia con un clic, Ctrl+Z lo deshace,
    y se usa al exportar.
Ejecutar:  .venv/Scripts/python.exe tests/test_viewer_layers.py <carpeta_salida>
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

from PySide6.QtCore import Qt  # noqa: E402
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
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    files = {}
    for col in ("red", "blue"):
        files[col] = os.path.join(out, f"{col}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=320x180:d=4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", files[col]], check=True)
    mask = os.path.join(out, "mascara.mkv")                 # mitad izquierda = sujeto, derecha = fondo quitado
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=320x180:d=4:r=30,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                    "-pix_fmt", "gray", "-c:v", "ffv1", mask], check=True)
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
    win.engine.seek(1.0)
    pump(app, 0.4)
    assert canvas.layer(v2.id).box.isVisible() and not canvas.layer(v1.id).box.isVisible(), \
        "un clip normal a pantalla completa tapa la pista de debajo"
    print("✓ clip normal a pantalla completa: la pista de debajo no se carga (no se ve)")
    ctrl.set_clip_props([top], "Recortar sujeto", fx={"subject_mask": {"mask": mask, "a": 0.0, "fps": 30.0,
                                                                        "invert": False}})
    win.engine.seek(1.5)
    pump(app, 0.5)
    assert canvas.layer(v1.id).box.isVisible(), "con el fondo quitado, la pista de debajo tiene que verse"
    assert canvas.layer(v2.id).box.zValue() > canvas.layer(v1.id).box.zValue()
    print("✓ con ✂ recorte de sujeto, se ve la pista de debajo (detrás del sujeto)")
    ctrl.undo_stack.undo()
    win.engine.seek(1.0)
    pump(app, 0.3)
    assert not canvas.layer(v1.id).box.isVisible()
    print("✓ Ctrl+Z (quitar el recorte) → vuelve a taparla")

    # El nombre del video/proyecto
    title = win.preview.title_label
    assert title.text() == p.name
    QTest.mouseClick(title, Qt.LeftButton)
    title.selectAll()
    QTest.keyClicks(title, "Rese")             # (QTest se cae con letras como la ñ: el resto, con insert)
    title.insert("ña Gears of War")
    QTest.keyClick(title, Qt.Key_Return)
    pump(app, 0.2)
    assert p.name == "Reseña Gears of War", p.name
    assert ctrl.undo_stack.undoText().startswith("Nombre") and ctrl.dirty, ctrl.undo_stack.undoText()
    assert win.default_export_path().endswith("Reseña Gears of War.mp4"), win.default_export_path()
    assert "Reseña Gears of War" in win.windowTitle(), win.windowTitle()
    print("✓ clic en el nombre → escribir → Intro: es el nombre del proyecto y del archivo al exportar")
    QTest.mouseClick(title, Qt.LeftButton)
    title.selectAll()
    QTest.keyClicks(title, "otra cosa")
    QTest.keyClick(title, Qt.Key_Escape)
    pump(app, 0.2)
    assert p.name == "Reseña Gears of War" and title.text() == "Reseña Gears of War"
    print("✓ Esc deja el nombre como estaba")
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert p.name == "Proyecto sin título" and title.text() == "Proyecto sin título", (p.name, title.text())
    print("✓ Ctrl+Z vuelve al nombre anterior")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
