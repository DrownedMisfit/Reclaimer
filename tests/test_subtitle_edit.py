"""
Prueba de «✏ Corregir subtítulos desde el visor»: doble clic sobre el texto de un subtítulo visible abre el
campo con su frase (y la palabra pulsada seleccionada); Enter cambia la transcripción y el subtítulo; Esc cancela;
Ctrl+Z lo devuelve (un solo paso).
Usa una carpeta de datos TEMPORAL (no toca tus proyectos ni tus atajos).
Ejecutar:  .venv/Scripts/python.exe tests/test_subtitle_edit.py <carpeta_salida>
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
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FRASE = "el jefe final vuelve mañana por la noche"


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def send_key(app, w, k):
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
    app.processEvents()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import subtitles as SUBS
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.subtitle_item import word_rects

    ff = M.ffmpeg()
    vid = os.path.join(out, "juego.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    p = ctrl.project
    (vmid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([vmid], v1.id, 0.0)
    words, t = [], 0.4
    for w in FRASE.split():
        d = 0.3
        words.append([round(t, 3), round(t + d, 3), w, 0.95])
        t += d + 0.06
    ctrl.set_transcript(vmid, {"language": "es", "model": "prueba", "words": words, "segments": []})
    ctrl.set_subtitle_style("Subtítulos", enabled=True, media_id=vmid)
    pump(app, 0.3)
    p = ctrl.project
    cues = SUBS.styled_cues(p)
    assert cues, "debería haber subtítulos"
    cue = cues[0]
    win.engine.seek(cue.start + 0.15)
    pump(app, 0.4)
    canvas = win.preview.canvas
    shown = canvas.subs.cue_words()
    assert shown and " ".join(w.text for w in shown) == " ".join(w.text for w in cue.words), shown
    print(f"✓ subtítulo visible: «{cue.text(' ')}»")

    # doble clic sobre la palabra «jefe» (escena → viewport)
    target = next(w for w in shown if w.text == "jefe")
    rect = next(r for w, r in word_rects(cue, p.subtitles, p.width, p.height) if w.index == target.index)
    vp_pt = canvas.mapFromScene(rect.center())
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(vp_pt), QPointF(vp_pt), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(canvas.viewport(), ev)
    pump(app, 0.2)
    ed = win._sub_editor
    assert ed.isVisible(), "el campo de edición debería abrirse"
    assert ed.text().lower() == " ".join(w.text for w in shown).lower(), ed.text()   # (el campo muestra la transcripción, sin mayúscula inicial)
    assert ed.selectedText() == "jefe", ed.selectedText()
    print(f"✓ doble clic en «jefe»: se abre el campo con la frase y «jefe» seleccionada")

    # cambiar «jefe» por «cabecilla» y Enter
    n_undo = ctrl.undo_stack.count()
    ed.setText(ed.text().replace("jefe", "cabecilla"))
    send_key(app, ed, Qt.Key_Return)
    pump(app, 0.4)
    assert not ed.isVisible(), "Enter cierra el campo"
    idx = target.index
    assert ctrl.project.transcripts[vmid]["words"][idx][2] == "cabecilla", ctrl.project.transcripts[vmid]["words"][idx]
    assert ctrl.undo_stack.count() == n_undo + 1, (n_undo, ctrl.undo_stack.count())
    engine_texts = [c.text(" ") for c in win.engine._cues]
    assert any("cabecilla" in x for x in engine_texts), engine_texts
    print("✓ Enter: la transcripción cambia y el subtítulo se actualiza (un solo paso de deshacer)")

    # Ctrl+Z lo devuelve
    ctrl.undo_stack.undo()
    pump(app, 0.4)
    assert ctrl.project.transcripts[vmid]["words"][idx][2] == "jefe", ctrl.project.transcripts[vmid]["words"][idx]
    assert not any("cabecilla" in c.text(" ") for c in win.engine._cues)
    print("✓ Ctrl+Z: vuelve «jefe» en la transcripción y en el subtítulo")

    # Esc cancela
    QApplication.sendEvent(canvas.viewport(), QMouseEvent(QEvent.MouseButtonDblClick, QPointF(vp_pt),
                                                          QPointF(vp_pt), Qt.LeftButton, Qt.LeftButton,
                                                          Qt.NoModifier))
    pump(app, 0.2)
    assert ed.isVisible()
    ed.setText("otra cosa")
    send_key(app, ed, Qt.Key_Escape)
    pump(app, 0.2)
    assert not ed.isVisible() and ctrl.project.transcripts[vmid]["words"][idx][2] == "jefe"
    print("✓ Esc: cancela sin cambiar nada")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
