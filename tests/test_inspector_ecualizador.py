"""
🎚 Al elegir un clip en la línea de tiempo, el Inspector abre la pestaña que toca:
  · un AUDIO → su ecualizador (pestaña «Audio»), estuvieras donde estuvieras;
  · un VIDEO → no se queda en el ecualizador: pestaña general «Clip» (si estabas en Video o Color, sigues ahí).
Ejecutar:  .venv/Scripts/python.exe tests/test_inspector_ecualizador.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, new_id  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.ui.inspector import InspectorPanel
    ctrl = ProjectController()
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    mv = MediaItem(new_id(), "/falso/v.mp4", KIND_VIDEO, "v.mp4", duration=60.0, width=1280, height=720,
                   has_audio=False, probed=True)
    ma = MediaItem(new_id(), "/falso/a.wav", KIND_AUDIO, "a.wav", duration=60.0, probed=True)
    p.media[mv.id], p.media[ma.id] = mv, ma
    cv = Clip(new_id(), mv.id, v1.id, 0.0, 0.0, 10.0)
    cv2 = Clip(new_id(), mv.id, v1.id, 10.0, 0.0, 10.0)
    ca = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 10.0)
    for c in (cv, cv2, ca):
        p.clips[c.id] = c
    ctrl.project_changed.emit()
    ins = InspectorPanel(ctrl)
    tabs = ins.clip_tabs

    ins.set_selection([cv.id])
    assert tabs.currentIndex() == 0, tabs.currentIndex()
    ins.set_selection([ca.id])
    assert tabs.currentIndex() == 2, f"un audio debe abrir su ecualizador ({tabs.currentIndex()})"
    print("✓ elegir un audio abre su ecualizador (pestaña Audio)")
    ins.set_selection([cv.id])
    assert tabs.currentIndex() == 0, f"un video no se queda en el ecualizador ({tabs.currentIndex()})"
    print("✓ elegir un video después: pestaña general «Clip», no el ecualizador")
    tabs.setCurrentIndex(3)                     # trabajando en Color…
    ins.set_selection([cv2.id])
    assert tabs.currentIndex() == 3, "si estabas en Color con un video, sigues en Color"
    ins.set_selection([ca.id])
    assert tabs.currentIndex() == 2
    print("✓ en Video/Color con videos sigues ahí; un audio siempre abre el ecualizador")
    ins.prefer_audio = True                     # 🎚 en la página Audio: elegir un video no saca del ecualizador
    mv.has_audio = True
    ins.set_selection([cv.id])
    assert tabs.currentIndex() == 2, f"en la página Audio se queda en el ecualizador ({tabs.currentIndex()})"
    print("✓ en la página Audio, elegir otro clip no te saca del ecualizador")
    print("TODO OK")


if __name__ == "__main__":
    main()
