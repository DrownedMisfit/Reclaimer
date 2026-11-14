"""
🗂 Paneles de cada pestaña (sin ventanas visibles):
  · Edits: el edit musical a pantalla completa como parte de la ventana (opciones a la derecha, clips a la izquierda con
    miniaturas grandes), sin Limpieza, Texto ni Subtítulos; «Crear edit musical» ya no abre una ventanita;
  · YouTube: sin Texto ni Subtítulos, con 🔑 Palabras clave y 🎞 Material del clip;
  · Shorts: con Texto y Subtítulos;
  · lo que enciendas tú desde Ventana en una pestaña se recuerda en esa pestaña.
Ejecutar:  .venv/Scripts/python.exe tests/test_tab_panels.py
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
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in st.allKeys():
        if k.startswith("paneles_pestana/"):
            st.remove(k)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1500, 900)
    pump(app, 0.5)

    def abierto(k):
        return win.docks[k].toggleViewAction().isChecked()

    assert win.workspaces.switch("edit")
    pump(app, 0.2)
    assert abierto("edit_opts") and abierto("edit_clips"), "en Edits, el edit musical a la vista"
    assert abierto("clips"), "en Edits también 🔑 Palabras clave"
    assert not abierto("transcript") and not abierto("subtitles") and not abierto("voice")
    from PySide6.QtWidgets import QDialog
    abiertos = []
    orig = QDialog.exec
    QDialog.exec = lambda self_: abiertos.append(self_) or 0
    try:
        win.open_edit_maker()
    finally:
        QDialog.exec = orig
    assert not abiertos, "en Edits, «Crear edit musical» ya no abre una ventanita"
    ep = win.edit_panel
    assert ep.embedded and ep.clips.iconSize().width() >= 160 and not ep.cancel_btn.isVisible()
    print("✓ Edits: el edit musical como parte de la ventana (opciones a la derecha, clips grandes a la izquierda), "
          "sin Limpieza/Texto/Subtítulos")

    assert win.workspaces.switch("youtube")
    pump(app, 0.2)
    assert abierto("material") and abierto("clips")
    assert not abierto("transcript") and not abierto("subtitles") and not abierto("edit_opts")
    print("✓ YouTube: 🔑 Palabras clave y 🎞 Material del clip; sin Texto ni Subtítulos")

    assert win.workspaces.switch("short")
    pump(app, 0.2)
    assert abierto("transcript") and abierto("subtitles") and not abierto("edit_opts")
    print("✓ Shorts: Texto y Subtítulos a la vista")

    assert win.workspaces.switch("youtube")
    win.docks["subtitles"].toggleViewAction().trigger()      # tú lo enciendes en YouTube
    assert abierto("subtitles")
    win.workspaces.switch("short")
    win.workspaces.switch("youtube")
    pump(app, 0.2)
    assert abierto("subtitles"), "lo que enciendes tú en una pestaña se recuerda"
    print("✓ lo que enciendas tú en una pestaña (Ventana) se recuerda en esa pestaña")

    # 🎞 Material del clip: enseña el clip elegido
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem
    p = win.ctrl.project
    p.media["m"] = MediaItem(id="m", path="no_existe.mp4", kind=KIND_VIDEO, name="Gameplay.mp4", duration=60.0,
                             probed=True, ai_type="Gameplay", ai_tags=["combate"])
    v = [t for t in p.tracks if t.kind == "video"][-1]
    p.clips["c"] = Clip(id="c", media_id="m", track_id=v.id, start=2.0, source_in=10.0, duration=4.0)
    win.ctrl.project_changed.emit()
    win.timeline.set_selection(["c"])
    pump(app, 0.2)
    txt = win.material.info.text()
    assert "Gameplay.mp4" in win.material.title.text() and "La IA ve: Gameplay · combate" in txt and "00:10" in txt, txt
    win.timeline.set_selection([])
    assert "Ningún clip" in win.material.title.text()
    print("✓ Material del clip: de dónde sale, qué vio la IA y sus acciones; sin clip, lo dice")

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
