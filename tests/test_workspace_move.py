"""
Prueba de «mover el proyecto a otra pestaña» (🎬 YouTube · 🎵 Edits · 📱 Shorts):
  · el proyecto cambia de formato y se lleva a la otra pestaña; la de origen queda vacía;
  · Ctrl+Z devuelve el formato anterior;
  · si el destino ya tenía trabajo: con pregunta (Cancelar no cambia nada) o sin pregunta (copia de seguridad);
  · Archivo → «↪ Mover este proyecto a» (la pestaña actual, deshabilitada) y clic derecho en la barra.
Ejecutar:  .venv/Scripts/python.exe tests/test_workspace_move.py <carpeta_salida>
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

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402


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
    from editoria.ui import help as help_ui
    from editoria.ui import workspaces as WS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    st = QSettings("EditorIA", "EditorIA")
    st.remove("espacios")
    vid = os.path.join(out, "partida.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-pix_fmt", "yuv420p", vid], check=True)

    def add_clip(win):
        ctrl = win.ctrl
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.05)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 0.0)

    def with_question(answer, fn):
        """Ejecuta fn con QMessageBox.question parcheado (devuelve «answer»); anota las preguntas hechas."""
        asked = []
        real = QMessageBox.question

        def fake(*args, **kwargs):
            asked.append(args[2] if len(args) > 2 else "")
            return answer
        QMessageBox.question = fake
        try:
            return fn(), asked
        finally:
            QMessageBox.question = real

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.try_recover()
    pump(app, 0.3)
    ws, ctrl = win.workspaces, win.ctrl
    assert ws.current == "youtube" and ctrl.project.format == "youtube"

    # ---- 1. mover un proyecto con clip y nombre de YouTube a Shorts (sin preguntar)
    add_clip(win)
    ctrl.rename_project("Mover prueba")
    n = len(ctrl.project.clips)
    assert n >= 1
    assert ws.move_to("youtube", ask=True) is False and ws.move_to("nope") is False   # no hace nada
    assert ws.move_to("short", ask=False) is True
    assert ws.current == "short" and ws.bar.currentIndex() == 2, (ws.current, ws.bar.currentIndex())
    assert ctrl.project.format == "short" and ctrl.project.width == 1080 and ctrl.project.height == 1920
    assert len(ctrl.project.clips) == n and ctrl.project.name == "Mover prueba"
    assert ws.stacks.get("short") is ctrl.undo_stack and "youtube" not in ws.stacks
    assert "Shorts" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
    print("✓ mover a Shorts: la pestaña cambia a Shorts, el proyecto es vertical 1080×1920 con su clip y su nombre")

    # ---- 2. Ctrl+Z devuelve el formato; Ctrl+Y lo vuelve a poner
    ctrl.undo_stack.undo()
    assert ctrl.project.format == "youtube", ctrl.project.format
    ctrl.undo_stack.redo()
    assert ctrl.project.format == "short"
    ws.switch("youtube")
    assert not ctrl.project.clips and ctrl.path is None, "la pestaña de origen queda vacía"
    ws.switch("short")
    assert ctrl.project.format == "short" and ctrl.project.name == "Mover prueba" and len(ctrl.project.clips) == n
    print("✓ Ctrl+Z devuelve YouTube (Ctrl+Y vuelve a Shorts); YouTube queda vacía; al volver, Shorts conserva el proyecto")

    # ---- 3. destino con trabajo: con pregunta, Cancelar no cambia nada
    ws.switch("youtube")
    add_clip(win)
    ctrl.rename_project("Ocupante")
    ws.switch("short")                                    # Shorts: «Mover prueba»; YouTube: «Ocupante» (guardado)
    assert ws.current == "short" and ctrl.project.name == "Mover prueba"
    res, asked = with_question(QMessageBox.Cancel, lambda: ws.move_to("youtube", ask=True))
    assert res is False and asked and "Ocupante" in asked[0], asked
    assert ws.current == "short" and ws.bar.currentIndex() == 2 and ctrl.project.format == "short"
    assert ctrl.project.name == "Mover prueba" and len(ctrl.project.clips) == n
    print(f"✓ destino ocupado + Cancelar: no cambia nada («{asked[0]}»)")

    # ---- 4. destino con trabajo, sin pregunta: copia de seguridad y reemplazo
    before = set(os.listdir(backups_dir()))
    assert ws.move_to("youtube", ask=False) is True
    assert ws.current == "youtube" and ws.bar.currentIndex() == 0 and ctrl.project.format == "youtube"
    assert ctrl.project.name == "Mover prueba" and len(ctrl.project.clips) == n
    new_b = sorted(set(os.listdir(backups_dir())) - before)
    assert new_b and any(f.startswith("Proyecto (youtube)_") for f in new_b), new_b
    import json
    bk = json.load(open(os.path.join(backups_dir(), new_b[0]), encoding="utf-8"))
    assert bk.get("name") == "Ocupante" and bk.get("clips"), bk.get("name")
    ws.switch("short")
    assert ctrl.project.format == "short" and not ctrl.project.clips, "Shorts queda vacía tras mover"
    ws.switch("youtube")
    assert ctrl.project.name == "Mover prueba" and len(ctrl.project.clips) == n
    print(f"✓ destino ocupado sin pregunta: copia de seguridad ({new_b[0]}) y el proyecto ocupa YouTube")

    # ---- 5. Archivo → «↪ Mover este proyecto a»: la pestaña actual deshabilitada
    ws.switch("short")
    menus = [m for m in win.findChildren(QMenu) if m.title().startswith("↪ Mover este proyecto")]
    assert len(menus) == 1, [m.title() for m in menus]
    menus[0].aboutToShow.emit()
    acts = [a for a in menus[0].actions() if not a.isSeparator()]
    assert [a.text() for a in acts] == ["🎬 YouTube", "🎵 Edits", "📱 Shorts"], [a.text() for a in acts]
    assert [a.isEnabled() for a in acts] == [True, True, False], [a.isEnabled() for a in acts]
    print("✓ Archivo → «↪ Mover este proyecto a»: las tres pestañas; la actual (Shorts) deshabilitada")

    # ---- 6. clic derecho en la barra de pestañas (menú de ayuda sustituido)
    assert ws.bar.contextMenuPolicy() == Qt.CustomContextMenu
    shown = []
    real_exec = help_ui.exec_menu
    help_ui.exec_menu = lambda menu, pos: shown.append([a.text() for a in menu.actions()])
    try:
        ws._bar_menu(QPoint(5, 5))
    finally:
        help_ui.exec_menu = real_exec
    assert shown and shown[-1] == ["↪ Mover este proyecto a «YouTube»", "↪ Mover este proyecto a «Edits»"], shown
    print("✓ clic derecho en la barra: «↪ Mover este proyecto a» para las otras dos pestañas")

    # ---- 7. menú 🔄 Reinicio → «↪ Cambiar este proyecto a…»: pregunta, lo lleva y deja la de origen vacía
    rein = [m for m in win.menuBar().findChildren(QMenu) if m.title().replace("&", "") == "🔄 Reinicio"]
    assert len(rein) == 1
    rein[0].aboutToShow.emit()
    cambiar = [a for a in rein[0].actions() if a.text().startswith("↪ Cambiar este proyecto a")]
    assert len(cambiar) == 3 and [a.isEnabled() for a in cambiar] == [True, True, False],         [(a.text(), a.isEnabled()) for a in cambiar]
    n = len(ctrl.project.clips)
    res, asked = with_question(QMessageBox.Cancel, lambda: win.change_project_tab("edit"))
    assert res is False and asked and "VACÍA" in asked[0] and ws.current == "short", asked
    res, asked = with_question(QMessageBox.Yes, lambda: win.change_project_tab("edit"))
    assert res is True and ws.current == "edit" and ctrl.project.format == "edit" and len(ctrl.project.clips) == n
    ws.switch("short")
    assert not ctrl.project.clips, "Shorts queda vacía tras llevarlo a Edits"
    res, asked = with_question(QMessageBox.Cancel, lambda: win.change_project_tab("youtube"))
    assert res is False and ws.current == "short", (asked, ws.current)       # (Cancelar: no se mueve nada)
    print("✓ 🔄 Reinicio → «↪ Cambiar este proyecto a…»: pregunta, lo lleva a Edits y Shorts queda vacía")

    ctrl.undo_stack.setClean()
    win.close()
    pump(app, 0.2)
    st.remove("espacios")
    print("TODO OK")


if __name__ == "__main__":
    main()
