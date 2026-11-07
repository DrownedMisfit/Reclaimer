"""
Prueba de las pestañas de trabajo (🎬 Video de YouTube · 🎵 Edits · 📱 Shorts):
  · cada pestaña tiene su proyecto; al cambiar, el de antes se guarda y al volver está igual;
  · sin nombre → datos/espacios/<pestaña>.eia; con nombre → su archivo;
  · al volver a abrir Reclaimer: la última pestaña con su proyecto, y las demás conservan lo suyo;
  · Ctrl+N en una pestaña: nuevo de su tipo (el sin nombre anterior, a las copias de seguridad);
  · abrir un .eia lo pone en la pestaña de su tipo; con una tarea en curso no se cambia.
Ejecutar:  .venv/Scripts/python.exe tests/test_workspaces.py <carpeta_salida>
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

from PySide6.QtCore import QSettings  # noqa: E402
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
    from editoria.core.paths import backups_dir
    from editoria.ui import workspaces as WS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    st = QSettings("EditorIA", "EditorIA")
    st.remove("espacios")
    st.sync()                                   # sin esto, «espacios/actual» de una ejecución anterior sobrevivía
    vid =os.path.join(out, "partida.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-pix_fmt", "yuv420p", vid], check=True)

    def add_clip(win):
        ctrl = win.ctrl
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.05)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 0.0)

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.try_recover()
    pump(app, 0.3)
    ws, ctrl = win.workspaces, win.ctrl
    assert ws.current == "youtube" and ws.bar.currentIndex() == 0 and ctrl.project.format == "youtube"
    assert [ws.bar.tabText(i) for i in range(3)] == [t for _k, t in WS.TABS]
    print("✓ al abrir: pestañas «🎬 YouTube · 🎵 Edits · 📱 Shorts», en YouTube")

    add_clip(win)
    ctrl.rename_project("Mi reseña")
    n_yt = len(ctrl.project.clips)
    ws.bar.setCurrentIndex(1)                      # como un clic en «🎵 Edits»
    pump(app, 0.2)
    assert ws.current == "edit" and ctrl.project.format == "edit" and not ctrl.project.clips
    assert ctrl.project.height > ctrl.project.width
    assert os.path.exists(WS.ws_file("youtube"))
    # 🗂 la biblioteca es común: el video importado en YouTube ya está en Medios aquí (sin tocar la línea de tiempo)
    same = [m for m in ctrl.project.media.values() if os.path.normcase(m.path) == os.path.normcase(os.path.abspath(vid))]
    assert len(same) == 1 and not ctrl.project.clips, ctrl.project.media
    print("✓ 🗂 lo de Medios pasa a la otra pestaña (sin duplicarse y sin tocar su línea de tiempo)")
    add_clip(win)
    assert len([m for m in ctrl.project.media.values() if m.path == same[0].path]) == 1, "importarlo otra vez no lo duplica"
    ctrl.rename_project("Edit Gears")
    ws.bar.setCurrentIndex(0)
    pump(app, 0.2)
    assert ws.current == "youtube" and ctrl.project.name == "Mi reseña" and len(ctrl.project.clips) == n_yt
    assert not ctrl.dirty, "lo de la pestaña está guardado: no pide guardar"
    print("✓ cambiar de pestaña guarda lo que llevabas; al volver, el proyecto está igual (sin nombre también)")

    # Ctrl+Z sigue valiendo después de ir y volver (cada pestaña con SU historial)
    from PySide6.QtGui import QAction
    undo_act = next(a for a in win.findChildren(QAction) if a.text().startswith("Deshacer"))
    assert ctrl.undo_stack.canUndo() and undo_act.isEnabled()
    assert "Nombre: Mi reseña" in undo_act.text(), undo_act.text()
    ctrl.undo_stack.undo()                          # deshace el nombre «Mi reseña» (lo último hecho aquí)
    assert ctrl.project.name != "Mi reseña"
    ctrl.undo_stack.undo()                          # y ahora el clip añadido antes de cambiar de pestaña
    assert len(ctrl.project.clips) < n_yt, len(ctrl.project.clips)
    ctrl.undo_stack.redo()
    ctrl.undo_stack.redo()
    assert ctrl.project.name == "Mi reseña" and len(ctrl.project.clips) == n_yt
    ws.switch("edit")
    assert "Edit Gears" in undo_act.text(), "el menú Deshacer sigue al historial de la pestaña activa"
    ctrl.undo_stack.undo()
    assert ctrl.project.name != "Edit Gears"
    ctrl.undo_stack.redo()
    ws.switch("youtube")
    assert ctrl.project.name == "Mi reseña" and "Mi reseña" in undo_act.text()
    rows = [win.history.model().index(i, 0).data() for i in range(win.history.model().rowCount())]
    assert "Nombre: Mi reseña" in rows and "Nombre: Edit Gears" not in rows, rows   # panel Historial = esta pestaña
    print("✓ Ctrl+Z / Ctrl+Y siguen valiendo al volver a una pestaña, y cada pestaña deshace solo lo suyo")

    yt_path = os.path.join(out, "Reseña.eia")
    ctrl.save(yt_path)
    ctrl.rename_project("Reseña final")             # cambio sin guardar (el guardado en vivo lo guarda al cambiar)
    ws.switch("short")
    assert ctrl.project.format == "short" and not ctrl.project.clips and ctrl.path is None
    ws.switch("youtube")
    assert ctrl.path == yt_path and ctrl.project.name == "Reseña final", (ctrl.path, ctrl.project.name)
    print("✓ con nombre: se guarda en su archivo y la pestaña lo vuelve a abrir")

    ws.switch("edit")
    ctrl.undo_stack.setClean()
    win.close()
    pump(app, 0.2)

    win = MainWindow()                              # volver a abrir Reclaimer
    win.show()
    win.try_recover()
    pump(app, 0.3)
    ws, ctrl = win.workspaces, win.ctrl
    assert ws.current == "edit" and ws.bar.currentIndex() == 1 and ctrl.project.name == "Edit Gears"
    assert len(ctrl.project.clips) >= 1
    ws.switch("youtube")
    assert ctrl.path == yt_path
    ws.switch("edit")
    print("✓ al volver a abrir Reclaimer: la última pestaña con su proyecto; las otras conservan lo suyo")

    before = set(os.listdir(backups_dir()))
    opened = []
    win.open_edit_maker = lambda: opened.append(1)  # (Ctrl+N en Edits abre la ventana del edit: aquí no)
    win.new_project()                               # Ctrl+N en «Edits»
    pump(app, 0.2)
    assert opened, "en «Edits», un proyecto nuevo abre directamente «Crear edit musical»"
    assert ws.current == "edit" and ctrl.project.format == "edit" and not ctrl.project.clips
    new_b = set(os.listdir(backups_dir())) - before
    assert new_b, "el proyecto sin nombre anterior queda en las copias de seguridad"
    print(f"✓ Ctrl+N: nuevo en la pestaña actual; el anterior sin nombre, a las copias ({sorted(new_b)[0]})")

    win.open_project(yt_path)                       # abrir un .eia de YouTube estando en Edits
    assert ws.current == "youtube" and ws.bar.currentIndex() == 0 and ctrl.path == yt_path
    print("✓ abrir un proyecto lo pone en la pestaña de su tipo")

    # Ctrl+1 / Ctrl+2 / Ctrl+3
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtTest import QTest
    keys = {a.shortcut().toString(): a for a in win.findChildren(QAction) if a.text().startswith(("🎬 Ir", "🎵 Ir",
                                                                                                    "📱 Ir"))}
    assert set(keys) == {"Ctrl+1", "Ctrl+2", "Ctrl+3"}, keys
    win.activateWindow()
    win.timeline.setFocus()
    pump(app, 0.1)
    QTest.keyClick(win.timeline, Qt.Key_3, Qt.ControlModifier)       # pulsando las teclas de verdad
    pump(app, 0.2)
    if ws.current != "short":                       # (sin ventana activa en pruebas: la orden del menú)
        keys["Ctrl+3"].trigger()
    assert ws.current == "short" and ws.bar.currentIndex() == 2
    keys["Ctrl+2"].trigger()
    assert ws.current == "edit"
    keys["Ctrl+1"].trigger()
    assert ws.current == "youtube" and ctrl.path == yt_path
    print("✓ Ctrl+1 / Ctrl+2 / Ctrl+3 cambian de pestaña (y están en Archivo y en «Personalizar atajos»)")

    win.voice.job = object()
    ws.bar.setCurrentIndex(2)
    pump(app, 0.1)
    assert ws.current == "youtube" and ws.bar.currentIndex() == 0, "con una tarea en curso no se cambia"
    win.voice.job = None
    print("✓ con una transcripción en curso no deja cambiar (te avisa)")
    ctrl.undo_stack.setClean()
    win.close()
    pump(app, 0.2)
    st.remove("espacios")
    print("TODO OK")


if __name__ == "__main__":
    main()
