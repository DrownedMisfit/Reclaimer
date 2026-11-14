"""
💬 Cada botón o atajo que no puede hacer nada dice por qué y qué hacer (sin ventanas visibles): borrar, bloquear o pegar
sin nada elegido/copiado, reproducir el tramo sin entrada/salida, la IA sin instrucción ni transcripción, buscar sin
texto, el inspector sin clip, los efectos sin elegir uno y la narración sin archivo.
Ejecutar:  .venv/Scripts/python.exe tests/test_avisos.py
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

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    pump(app, 0.4)
    msgs = []
    win.ctrl.message.connect(msgs.append)
    win.timeline.set_selection([])

    def barra():
        return win.statusBar().currentMessage()

    def ultimo():
        return msgs[-1] if msgs else ""

    win.statusBar().clearMessage()
    win._delete(False)
    assert "Supr" in barra(), barra()
    win._toggle_lock()
    assert "bloquear" in barra(), barra()
    win.statusBar().clearMessage()
    win._paste()
    assert barra(), "pegar sin nada copiado no dijo nada"
    win.statusBar().clearMessage()
    win._paste_insert()
    assert barra(), "pegar insertando sin nada copiado no dijo nada"
    print("✓ borrar, bloquear y pegar sin nada elegido o copiado dicen qué hacer")

    win.ctrl.project.mark_in = win.ctrl.project.mark_out = None
    win.engine.play_marked()
    assert "(I)" in ultimo() and "(O)" in ultimo(), ultimo()
    print("✓ reproducir el tramo marcado sin entrada/salida explica I y O")

    ai = win.ai_panel
    ai.director_text.setPlainText("")
    ai.interpret()
    assert ai.status.text().startswith("Escribe"), ai.status.text()
    ai.detect_topics()
    assert "transcribe" in ai.status.text().lower(), ai.status.text()
    ai.apply_zooms(False)
    assert "transcribe" in ai.status.text().lower(), ai.status.text()
    print("✓ la IA sin instrucción o sin transcripción dice qué falta")

    mp = win.moments
    mp.query.setText("")
    mp.search_text()
    assert mp.status.text().startswith("Escribe"), mp.status.text()
    win.library.semantic_search("")
    assert "Escribe" in ultimo(), ultimo()
    print("✓ buscar sin texto pide qué buscar")

    win.inspector._add_kf()
    assert "clip" in ultimo(), ultimo()
    win.effects.add_at_playhead(None)
    assert "efecto" in ultimo(), ultimo()
    win.voice._add_narration_to_timeline()
    assert "narración" in ultimo() or "pista de audio" in ultimo(), ultimo()
    print("✓ inspector, efectos y voz avisan si falta algo")
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
