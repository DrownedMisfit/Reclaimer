"""
🔇 Lo de Palabras clave entra en la línea de tiempo sin su audio (sin ventanas visibles):
  · add_media(audio=False): el video entra en silencio y sin su clip de sonido vinculado (lo normal, con él);
  · arrastrar desde la cuadrícula de una palabra (panel / ventana 🗂) lleva la marca «sin audio» y la línea de tiempo
    lo pone mudo; arrastrar desde Medios normal, con su sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_kw_sin_audio.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_sinaudio_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

from editoria.core.model import KIND_VIDEO, MediaItem, Project, TRACK_AUDIO  # noqa: E402
from editoria.ui.common import MEDIA_MIME, NOAUDIO_MIME  # noqa: E402


class _Soltar:
    """Un dropEvent de mentira con su mimeData."""
    def __init__(self, md):
        self._md = md

    def mimeData(self):
        return self._md

    def position(self):
        return QPointF(10, 10)

    def acceptProposedAction(self):
        pass


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    ctrl = win.ctrl
    p = Project.new()
    p.media["v"] = MediaItem(id="v", path=os.path.join(_TMP, "v.mp4"), kind=KIND_VIDEO, name="v.mp4", duration=5.0,
                             has_audio=True, probed=True)
    ctrl.project = p

    def audios():
        return [c for c in ctrl.project.clips.values() if ctrl.project.track(c.track_id).kind == TRACK_AUDIO]

    con = ctrl.add_media(["v"], None, 0.0)
    assert len(con) == 2 and len(audios()) == 1, con
    sin = ctrl.add_media(["v"], None, 10.0, audio=False)
    assert len(sin) == 1 and len(audios()) == 1 and ctrl.project.clips[sin[0]].volume == 0.0, sin
    print("✓ add_media(audio=False): el video entra en silencio y sin su sonido vinculado")

    from editoria.ui.clips_panel import _Lista
    lista = _Lista(arrastrar=True)
    it = QListWidgetItem("v.mp4")
    it.setData(Qt.UserRole, p.media["v"].path)
    lista.addItem(it)
    assert lista.mimeData([it]).hasFormat(NOAUDIO_MIME)
    print("✓ arrastrar desde la cuadrícula de una palabra lleva la marca «sin audio»")

    tl = win.timeline
    antes = len(audios())
    md = QMimeData()
    md.setData(MEDIA_MIME, b"v")
    md.setData(NOAUDIO_MIME, b"1")
    tl._drop = (None, 20.0)
    tl.dropEvent(_Soltar(md))
    assert len(audios()) == antes, "lo de Palabras clave no debe traer su audio"
    md2 = QMimeData()
    md2.setData(MEDIA_MIME, b"v")
    tl._drop = (None, 30.0)
    tl.dropEvent(_Soltar(md2))
    assert len(audios()) == antes + 1, "desde Medios normal, con su sonido"
    print("✓ la línea de tiempo pone mudo lo marcado y con sonido lo de Medios normal")
    ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
