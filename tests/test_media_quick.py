"""
Prueba de lo que pidió el usuario en Medios y del reinicio:
  · «⋮» en cada archivo: Eliminar de Medios, Mover a…, Separar audio y «✂ Cortar en cada cambio de escena…»;
  · un video marcado con «✂ por escenas» llega a la línea de tiempo YA cortado en cada cambio de escena (con su
    sonido); uno sin cambios de escena se queda entero; Ctrl+Z quita los cortes; en Medios no cambia nada;
  · «🔄 Reinicio de proyecto»: pregunta, guarda una copia de seguridad, deja la pestaña vacía y no toca tu .eia.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_media_quick.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.core.paths import backups_dir
    from editoria.ui import help as help_ui
    from editoria.ui.main_window import MainWindow
    ff = M.ffmpeg()
    escenas = os.path.join(out, "tres_escenas.mp4")        # 3 escenas muy distintas (cortes de golpe en 3 s y 6 s)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=3", "-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=3",
                    "-f", "lavfi", "-i", "mandelbrot=s=640x360:r=30:end_pts=3", "-f", "lavfi", "-i", "sine=d=9",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
                    "-t", "9", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", escenas], check=True)
    seguido = os.path.join(out, "una_escena.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=d=6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", seguido], check=True)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    a, b = ctrl.import_now([escenas, seguido])
    while ctrl.analyzing:
        pump(app, 0.1)
    pump(app, 0.5)
    lib = win.library
    item = None
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(lib.tree)
    while it.value():
        if it.value().data(0, 0x0100 + 1) == a or it.value().text(0) == "tres_escenas.mp4":
            item = it.value()
            break
        it += 1
    assert item is not None and item.text(3) == "⋮", item and item.text(3)
    seen = {}
    orig = help_ui.exec_menu

    def fake(menu, _pos):
        acts = {}
        for x in menu.actions():
            acts[x.text()] = x
            if x.menu():
                acts.update({y.text(): y for y in x.menu().actions()})
        seen["acts"] = acts
    help_ui.exec_menu = fake
    try:
        lib._on_click(item, 3)
    finally:
        help_ui.exec_menu = orig
    names = list(seen["acts"])
    assert any(n.startswith("🗑 Eliminar de Medios") for n in names), names
    assert "📂 Mover a…" in names and "🎵 Separar audio (micrófono y juego)" in names, names
    sc = next(x for n, x in seen["acts"].items() if n.startswith("✂ Cortar en cada cambio de escena"))
    print("✓ «⋮»: Eliminar de Medios, Mover a…, Separar audio y «✂ Cortar en cada cambio de escena»")
    sc.trigger()                                       # marcar «✂ por escenas» en tres_escenas.mp4
    ctrl.set_media_props([b], scene_cut=True)          # y también en el que no tiene cambios de escena
    pump(app, 0.5)
    assert ctrl.project.media[a].scene_cut
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([a], v1.id, 0.0)
    t0 = time.time()
    while time.time() - t0 < 60 and len(ctrl.project.clips_on(v1.id)) < 3:
        pump(app, 0.2)
    p = ctrl.project
    vc = p.clips_on(v1.id)
    cuts = sorted(round(c.start, 2) for c in vc)
    assert len(vc) == 3 and abs(cuts[1] - 3.0) < 0.15 and abs(cuts[2] - 6.0) < 0.15, cuts
    ac = [c for t in p.tracks if t.kind == TRACK_AUDIO for c in p.clips_on(t.id) if c.media_id == a]
    assert len(ac) == 3, len(ac)
    assert len([m for m in p.media.values()]) == 2
    print(f"✓ con «✂ por escenas» llega a la línea de tiempo ya cortado en cada cambio ({cuts}), con su sonido; "
          "en Medios no cambia nada")
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert len(ctrl.project.clips_on(v1.id)) == 1
    ctrl.undo_stack.redo()
    msgs = []
    win.statusBar().messageChanged.connect(msgs.append)
    ctrl.add_media([b], v1.id, 20.0)
    t0 = time.time()
    while time.time() - t0 < 30 and not any("cambios de escena" in x for x in msgs):
        pump(app, 0.2)
    assert len([c for c in ctrl.project.clips_on(v1.id) if c.media_id == b]) == 1
    assert any("No hay cambios de escena" in x for x in msgs), msgs
    print("✓ sin cambios de escena: se queda entero y te lo dice; Ctrl+Z quita los cortes")

    # 🔄 reinicio
    eia = os.path.join(out, "mi proyecto.eia")
    ctrl.save(eia)
    size0 = os.path.getsize(eia)
    before = set(os.listdir(backups_dir()))
    orig_q = QMessageBox.question
    QMessageBox.question = lambda *a_, **k: QMessageBox.Yes
    try:
        win.reset_project()
    finally:
        QMessageBox.question = orig_q
    pump(app, 0.4)
    p = ctrl.project
    assert not p.clips and not p.media and not p.subtitles.enabled and not p.markers, (len(p.clips), len(p.media))
    new = set(os.listdir(backups_dir())) - before
    assert any("antes del reinicio" in x for x in new), new
    assert os.path.getsize(eia) == size0 and ctrl.path is None
    print("✓ «🔄 Reinicio de proyecto»: todo vacío, con copia de seguridad de lo anterior; tu .eia intacto")
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
