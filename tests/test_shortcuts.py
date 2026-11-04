"""
Prueba de «⌨ Personalizar atajos» (cambiar, conflicto, guardar, se mantiene al reabrir, restablecer), de que
Ctrl+X quita los clips seleccionados de la línea de tiempo, y de que la línea de tiempo sale a buen tamaño
en la distribución inicial.
Usa una carpeta de datos TEMPORAL; deja tus atajos y tu distribución como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_shortcuts.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    backup = {k: st.value(k) for k in st.allKeys() if k.startswith("atajos/")}
    saved_layout = st.value("ventana/paneles")
    for k in backup:
        st.remove(k)
    st.remove("ventana/paneles")
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.shortcuts_dialog import ShortcutsDialog
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.5)
    th = win.docks["timeline"].height()
    assert th >= 1000 * 0.22 - 2, f"la línea de tiempo sale aplastada: {th}px"   # (su alto natural: todas las pistas)
    print(f"✓ distribución inicial: la línea de tiempo ocupa {th}px de 1000 (antes salía aplastada)")

    # Ctrl+X quita los clips seleccionados
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    ctrl = win.ctrl
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media(ids, v1.id, 0.0)
    c = ctrl.project.clips_on(v1.id)[0]
    win.timeline.set_selection([c.id])
    win.timeline.setFocus()
    QTest.keyClick(win.timeline, Qt.Key_X, Qt.ControlModifier)
    pump(app, 0.2)
    assert not ctrl.project.clips_on(v1.id), "Ctrl+X no quitó el clip"
    print("✓ Ctrl+X quita el clip seleccionado de la línea de tiempo")

    # Personalizar: «Cortar clips» → Ctrl+Shift+D ; poner Ctrl+N en otra orden pide quitárselo a «Nuevo proyecto»
    key = next(k for k in win.shortcut_actions if k.endswith("/Cortar clips"))
    dlg = ShortcutsDialog(win.shortcut_actions, win)
    assert dlg.set_shortcut(key, QKeySequence("Ctrl+Shift+D"), ask=False)
    assert win.shortcut_actions[key][0].shortcut() == QKeySequence("Ctrl+Shift+D")
    other = next(k for k in win.shortcut_actions if k.endswith("/Nuevo proyecto"))
    assert dlg.set_shortcut(key, QKeySequence("Ctrl+N"), ask=False)
    assert win.shortcut_actions[other][0].shortcut().isEmpty(), "el atajo repetido se quita de la otra orden"
    dlg.search.setText("cortar")
    dlg.show()
    pump(app, 0.2)
    dlg.grab().save(os.path.join(out, "atajos.png"))
    dlg.close()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()

    # Se mantiene al volver a abrir
    win2 = MainWindow()
    assert win2.shortcut_actions[key][0].shortcut() == QKeySequence("Ctrl+N")
    assert win2.shortcut_actions[other][0].shortcut().isEmpty()
    d2 = ShortcutsDialog(win2.shortcut_actions, win2)
    d2._reset(key)
    d2._reset(other)
    assert win2.shortcut_actions[key][0].shortcut() == QKeySequence("Ctrl+X")
    assert win2.shortcut_actions[other][0].shortcut() == QKeySequence("Ctrl+N")
    print("✓ atajos: cambiar, quitar el repetido a la otra orden, se guarda al reabrir y ↺ vuelve al de fábrica")
    win2.ctrl.undo_stack.setClean()
    win2.ctrl._media_dirty = False
    win2.close()

    for k in [k for k in st.allKeys() if k.startswith("atajos/")]:
        st.remove(k)
    for k, v in backup.items():
        st.setValue(k, v)
    if saved_layout is not None:
        st.setValue("ventana/paneles", saved_layout)
    else:
        st.remove("ventana/paneles")
    for k in ("guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
