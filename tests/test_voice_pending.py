"""
◈ La voz se aprende cuando se usa (el usuario: «solo entro a subtitular y pierdo rendimiento»):
  · al afinar las palabras de una transcripción, la grabación solo se APUNTA (no se decodifica ni se entrena);
  · el aprendizaje empieza al abrir «✂ Eliminar silencio» (learn_voice_pending) y no se lanza dos veces;
  · process_pending convierte lo apuntado en ejemplos y vacía la lista.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_voice_pending.py <carpeta>
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

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

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
WAV = os.path.join(ASSETS, "narracion_prueba.wav")


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_voice_pending")
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import voice_model as VM
    from editoria.core.model import KIND_AUDIO, MediaItem
    from editoria.ui import task_window
    from editoria.ui.main_window import MainWindow
    with open(os.path.join(ASSETS, "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
        words = json.load(f)["words"]
    assert os.path.normcase(os.path.abspath(VM.examples_dir())).startswith(os.path.normcase(os.path.abspath(_TMP)))

    lanzados = []
    original = task_window.TaskManager.start

    def contar(self, title, *a, **k):
        lanzados.append(title)
    task_window.TaskManager.start = contar
    try:
        win = MainWindow()
        win.ctrl.project.media["nar"] = MediaItem(id="nar", path=WAV, kind=KIND_AUDIO, name="narracion_prueba.wav",
                                                  duration=10.0, probed=True)
        win.learn_voice("nar", words)
        assert not lanzados, f"afinar no debe lanzar trabajos: {lanzados}"
        assert len(VM.pending()) == 1 and not VM.examples(), (VM.pending(), len(VM.examples()))
        win.learn_voice("nar", words)                      # la misma grabación otra vez: no se duplica
        assert len(VM.pending()) == 1
        print("✓ al afinar las palabras, la grabación solo se apunta (sin trabajos en segundo plano, sin duplicar)")
        import importlib.util
        if importlib.util.find_spec("torch") is not None:
            assert win.learn_voice_pending() and lanzados == ["◈ Aprender tu voz"], lanzados
            assert not win.learn_voice_pending(), "no se lanza dos veces a la vez"
            print("✓ al usar «Eliminar silencio» empieza el aprendizaje (una sola vez)")
        else:
            print("· sin PyTorch: no se entrena (como antes)")
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
    finally:
        task_window.TaskManager.start = original
    n = VM.process_pending()
    assert n == 1 and not VM.pending() and len(VM.examples()) == 1, (n, VM.pending(), len(VM.examples()))
    print("✓ process_pending: lo apuntado pasa a ejemplo de tu voz y la lista queda vacía")
    app.processEvents()
    print("TODO OK")


if __name__ == "__main__":
    main()
