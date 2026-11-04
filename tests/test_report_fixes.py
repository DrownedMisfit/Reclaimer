"""
Prueba de los fallos que encontró el informe de funciones repetidas:
  · «✕ Quitar todos los efectos» quita solo los efectos (la transición, la pantalla verde… se quedan);
  · «Eliminar todos los huecos de esta pista» no toca una pista bloqueada;
  · «Bloquear clip» (menú) hace lo mismo que Ctrl+L con una selección mezclada: bloquea todos;
  · «Añadir texto/marcador aquí» va donde haces clic, no al cabezal.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_report_fixes.py <carpeta_salida>
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

from PySide6.QtCore import QPoint  # noqa: E402
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
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl, p, tl = win.ctrl, win.ctrl.project, win.timeline
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a = ctrl.add_media([mid], v1.id, 0.0)[0]
    b = ctrl.add_media([mid], v1.id, 5.0)[0]

    ctrl.set_clip_props([b], "fx", fx={"flash": 0.1, "shake": 0.3, "shake_amp": 0.02, "bw": True,
                                       "trans": {"type": "fade", "dur": 0.5}, "chroma": {"color": "#00ff00"}})
    tl.set_selection([b])
    pump(app, 0.1)
    win.effects.clear_looks() if hasattr(win, "effects") else None
    fx = p.clips[b].fx or {}
    assert "trans" in fx and "chroma" in fx and not ({"flash", "shake", "shake_amp", "bw"} & set(fx)), fx
    print("✓ «Quitar todos los efectos» deja la transición y la pantalla verde")

    v1.locked = True
    n = ctrl.undo_stack.count()
    ctrl.close_all_gaps(v1.id)
    assert p.clips[b].start == 5.0 and ctrl.undo_stack.count() == n
    v1.locked = False
    print("✓ una pista bloqueada no pierde sus huecos")

    ctrl.set_clip_props([a], "lock", locked=True)
    tl.set_selection([a, b])
    menu_holder = {}
    from editoria.ui import help as help_ui
    orig_exec = help_ui.exec_menu
    help_ui.exec_menu = lambda m, *a_, **k: menu_holder.setdefault("m", m) and None
    try:
        tl._clip_menu(p.clips[b], tl.mapToGlobal(QPoint(10, 10)))
    finally:
        help_ui.exec_menu = orig_exec
    act = next(x for x in menu_holder["m"].actions() if x.text().startswith("Bloquear clip"))
    act.trigger()
    assert p.clips[a].locked and p.clips[b].locked, "con mezcla, bloquea todos (como Ctrl+L)"
    ctrl.set_clip_props([a, b], "unlock", locked=False)
    print("✓ «Bloquear clip» con una selección mezclada bloquea todos (como Ctrl+L)")

    win.engine.seek(1.0)
    pump(app, 0.2)
    y = tl.track_y(p.track_index(v1.id)) + 10
    x = tl.x_for(20.0)
    menu_holder.clear()
    help_ui.exec_menu = lambda m, *a_, **k: menu_holder.setdefault("m", m) and None
    try:
        tl._clip_menu(None, tl.mapToGlobal(QPoint(int(x), int(y))))
    finally:
        help_ui.exec_menu = orig_exec
    txt = next(x_ for x_ in menu_holder["m"].actions() if "Añadir texto aquí" in x_.text())
    txt.trigger()
    texts = [c for c in p.clips.values() if c.text is not None]
    assert texts and abs(texts[0].start - 20.0) < 0.3, [c.start for c in texts]
    print(f"✓ «Añadir texto aquí» va donde hiciste clic ({texts[0].start:.1f} s), no al cabezal (1 s)")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
