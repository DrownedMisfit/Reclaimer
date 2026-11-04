"""
Prueba de la ayuda con clic derecho («❓ ¿Qué hace esto?»).
Ejecutar:  .venv/Scripts/python.exe tests/test_help.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu  # noqa: E402

from editoria.ui import help as help_ui  # noqa: E402

shown: list[list[str]] = []


def fake_exec(menu, *args, **kwargs):
    shown.append([a.text() for a in menu.actions() if not a.isSeparator()])
    return None


def right_click(app, widget) -> list[str]:
    shown.clear()
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), widget.mapToGlobal(QPoint(5, 5)))
    app.sendEvent(widget, ev)
    return shown[-1] if shown else []


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 1) Todas las ayudas usadas existen
    used = set()
    for f in glob.glob(os.path.join(root, "editoria", "ui", "*.py")):
        src = open(f, encoding="utf-8").read()
        used |= set(re.findall(r'set_help\([^,]+,\s*"([a-z_]+)"\)', src))
        used |= set(re.findall(r'add_help_action\(menu,\s*"([a-z_]+)"', src))
    missing = used - set(help_ui.HELP)
    assert not missing, missing
    print(f"✓ {len(used)} ayudas usadas, todas con su explicación")

    app = QApplication(sys.argv)
    help_ui.exec_menu = fake_exec
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    checks = {
        "botón ◈ de la biblioteca": win.library.btn_analyze,
        "botón Transcribir": win.voice.btn_transcribe,
        "casilla de silencios": win.voice.chk_sil,
        "botón Proponer B-roll": win.ai_panel.btn_propose,
        "Modo Director (texto)": win.ai_panel.director_text.viewport(),
        "visor": win.preview.canvas.viewport(),
        "historial": win.history.viewport(),
    }
    for name, w in checks.items():
        acts = right_click(app, w)
        assert "❓ ¿Qué hace esto?" in acts, (name, acts)
        print(f"✓ clic derecho en {name}: {acts[-1]}" + (f" (+{len(acts) - 1} opciones normales)" if len(acts) > 1 else ""))
    # Un campo numérico conserva su menú normal (copiar, pegar…)
    spin_line = win.subtitles.size.findChild(QLineEdit)
    acts = right_click(app, spin_line)
    assert "❓ ¿Qué hace esto?" in acts and len(acts) > 3, acts
    print(f"✓ campo numérico: mantiene {len(acts) - 1} opciones normales + ayuda")
    # Menús propios: biblioteca vacía y transcripción
    win.library._context_menu(QPoint(5, 5))
    assert shown and "❓ ¿Qué hace esto?" in shown[-1], shown
    win.transcript._context_menu(QPoint(5, 5))
    assert shown and "❓ ¿Qué hace esto?" in shown[-1], shown
    print("✓ biblioteca y transcripción: la ayuda está en su menú propio")
    # La ventana de ayuda se abre con la explicación
    from PySide6.QtWidgets import QMessageBox
    texts = []
    box = help_ui.build_help_box("ecualizador", win)
    texts.append(box.text())
    assert "Arrastra un punto" in texts[-1]
    print("✓ «¿Qué hace esto?» abre la explicación (ej.: ecualizador)")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
