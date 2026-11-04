"""
Prueba de «⬇ Traer mis atajos de DaVinci Resolve»: se lee keyboard.preset.xml de Resolve (solo lectura), se
traduce a atajos de Reclaimer, se enseña la lista «Ahora / En tu Resolve» y se aplican los marcados (quitándoselo
a otra orden si ya lo usaba). Usa un preset sintético; tu configuración de atajos se deja como estaba.
Ejecutar:  .venv/Scripts/python.exe tests/test_resolve_keys.py <carpeta_salida>
"""
from __future__ import annotations

import os
import struct
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

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

CTRL, ALT, SHIFT = 0x04000000, 0x08000000, 0x02000000


def qstr(s: str) -> bytes:
    raw = s.encode("utf-16-be")
    return struct.pack(">I", len(raw)) + raw


def make_preset(path: str, actions: dict[str, list[int]]):
    body = struct.pack(">I", len(actions))
    for name, keys in actions.items():
        body += qstr(name) + struct.pack(">I", len(keys))
        for k in keys:
            body += struct.pack(">II", 1, k)
    blob = struct.pack(">II", 1, 1) + qstr("Mi Resolve") + struct.pack(">II", len(body), 1) + body
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<SmKeyboardPresetList>\n <FieldsBlob/>\n'
                f" <PresetListBA>{blob.hex()}</PresetListBA>\n</SmKeyboardPresetList>\n")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    st.beginGroup("atajos")
    saved = {k: st.value(k) for k in st.allKeys()}
    st.endGroup()
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import resolve_keys as R
    from editoria.ui.main_window import MainWindow
    from editoria.ui.shortcuts_dialog import ShortcutsDialog
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    assert R.key_text(ALT | SHIFT | 0x35) == "Alt+Shift+5" and R.key_text(CTRL | ord("B")) == "Ctrl+B"
    assert R.key_text(0x01000007) == "Del" and R.key_text(0x20) == "Space"
    fake = os.path.join(out, "keyboard.preset.xml")
    make_preset(fake, {"editBladeRazor": [CTRL | ord("B")], "editAddTransition": [CTRL | ord("T")],
                       "editSnapping": [ord("N")], "markFavoriteKeywords5": [ALT | SHIFT | 0x35],
                       "editUndo": [CTRL | ord("Z"), ord("`")]})
    pres = R.read_presets(fake)
    acts = pres["Mi Resolve"]
    assert acts["editBladeRazor"] == ["Ctrl+B"] and acts["editUndo"] == ["Ctrl+Z", "`"], acts
    m = R.mapped(fake)
    assert m["Dividir en el cabezal"] == "Ctrl+B" and m["⧉ Poner transición (disolver) en el corte"] == "Ctrl+T"
    print("✓ lee el formato de Resolve (QDataStream en hexadecimal) y lo traduce a órdenes de Reclaimer")

    if os.path.exists(R.PRESET):          # tu archivo real (solo lectura)
        real = R.read_presets()
        n = max(len(a) for a in real.values())
        assert n > 100, n
        print(f"✓ tu DaVinci Resolve: {n} acciones leídas (solo lectura)")
    try:
        win = MainWindow()
        win.show()
        pump(app, 0.3)
        dlg = ShortcutsDialog(win.shortcut_actions, win)
        R.PRESET = fake
        key_split = next(k for k in win.shortcut_actions if k.endswith("/Dividir en el cabezal"))
        key_tr = next(k for k in win.shortcut_actions if k.endswith("/⧉ Poner transición (disolver) en el corte"))
        key_tx = next(k for k in win.shortcut_actions if "Transcribir y analizar" in k)
        assert win.shortcut_actions[key_tx][0].shortcut() == QKeySequence("Ctrl+T")
        seen = {}

        def accept():
            d = dlg._resolve_dialog
            from PySide6.QtWidgets import QTreeWidget
            tree = d.findChild(QTreeWidget)
            seen["rows"] = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
            d.accept()
        QTimer.singleShot(200, accept)
        n = dlg.import_resolve()
        assert n == 2, (n, seen)            # Dividir (S→Ctrl+B) y transición (Alt+T→Ctrl+T); el imán ya es N
        assert "Imán (encajar) sí/no" in seen["rows"]
        assert win.shortcut_actions[key_split][0].shortcut() == QKeySequence("Ctrl+B")
        assert win.shortcut_actions[key_tr][0].shortcut() == QKeySequence("Ctrl+T")
        assert win.shortcut_actions[key_tx][0].shortcut().isEmpty(), "Ctrl+T se le quita a «Transcribir»"
        print("✓ «⬇ Traer mis atajos de DaVinci Resolve»: lista Ahora / En tu Resolve; aplica los marcados "
              "(Ctrl+B = dividir, Ctrl+T = transición) y se lo quita a la orden que lo usaba")
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        st.beginGroup("atajos")
        for k in st.allKeys():
            st.remove(k)
        for k, v in saved.items():
            st.setValue(k, v)
        st.endGroup()
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
