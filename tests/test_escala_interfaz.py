"""
🔍 Escala de la interfaz (sin ventanas visibles):
  · «Automática»: 2K con Windows al 100 % → 125 %; 4K → 150 %; si Windows ya escala o es 1080p, no se toca;
  · las fijas (100–175 %) mandan; QT_SCALE_FACTOR puesto a mano se respeta;
  · Ventana → «🔍 Escala de la interfaz» guarda la elección (se aplica al volver a abrir Reclaimer).
Ejecutar:  .venv/Scripts/python.exe tests/test_escala_interfaz.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_escala_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.ui import ui_scale as US  # noqa: E402


def main():
    assert US.factor("auto", 2560, 1.0) == 1.25 and US.factor("auto", 3840, 1.0) == 1.5
    assert US.factor("auto", 1920, 1.0) == 1.0 and US.factor("auto", 2560, 1.25) == 1.0
    assert US.factor("auto", 0, 1.0) == 1.0, "si no se sabe la pantalla, la de siempre"
    assert US.factor("150", 1920, 1.25) == 1.5 and US.factor("100", 3840, 1.0) == 1.0
    print("✓ automática: 2K al 100 % → 125 %, 4K → 150 %; 1080p o Windows ya escalado → sin tocar; las fijas mandan")
    viejo = os.environ.pop("QT_SCALE_FACTOR", None)
    os.environ["QT_SCALE_FACTOR"] = "1.1"
    assert US.apply_before_app() == 1.1 and os.environ["QT_SCALE_FACTOR"] == "1.1"
    os.environ.pop("QT_SCALE_FACTOR", None)
    if viejo is not None:
        os.environ["QT_SCALE_FACTOR"] = viejo
    print("✓ una escala puesta a mano (QT_SCALE_FACTOR) se respeta")

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    acts = [a for a in win.ui_scale_menu.actions() if a.isCheckable()]
    assert [a.text() for a in acts] == [US.NOMBRES[o] for o in US.OPCIONES]
    acts[3].trigger()                                        # 150 %
    assert QSettings("EditorIA", "EditorIA").value(US.KEY) == "150" and US.setting() == "150"
    assert "volver a abrir" in win.statusBar().currentMessage()
    acts[0].trigger()
    assert US.setting() == "auto"
    print("✓ Ventana → «🔍 Escala de la interfaz» guarda la elección y avisa de que se aplica al volver a abrir")
    # 🎨 tema gris: los grises se aclaran, lo que tiene color no
    from editoria.ui import tema as TM
    assert TM.aclarar("#e8742f") == "#e8742f" and TM.aclarar("#3f6a94") == "#3f6a94", "con color: igual"
    assert int(TM.aclarar("#1d1e22")[1:3], 16) > 0x1d + 8, TM.aclarar("#1d1e22")    # (más claro, sin pasarse)
    css = TM.aclarar_texto("a { color: #141518; border: 1px solid #2f3137; } b { color: #e8742f; }", {"#2f3137"})
    assert "#2f3137" in css and "#e8742f" in css and "#141518" not in css, css
    tacts = [a_ for a_ in win.tema_menu.actions() if a_.isCheckable()]
    assert [a_.text() for a_ in tacts] == [TM.NOMBRES[t] for t in TM.TEMAS]
    assert len(tacts) == 4 and TM.POR_DEFECTO == "grafito", "4 temas para elegir; de entrada, grafito"
    tacts[TM.TEMAS.index("oscuro")].trigger()
    assert QSettings("EditorIA", "EditorIA").value(TM.KEY) == "oscuro" and "volver a abrir" in         win.statusBar().currentMessage()
    QSettings("EditorIA", "EditorIA").remove(TM.KEY)
    print("✓ 🎨 temas: grafito (de entrada), pizarra, gris claro y oscuro en Ventana → «🎨 Tema»")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
