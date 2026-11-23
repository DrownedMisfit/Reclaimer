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

    from editoria.ui.inspector_secciones import INDICE
    ins.set_selection([cv.id])
    assert ins.pestana_activa() == "video", ins.pestana_activa()
    ins.set_selection([ca.id])
    assert ins.pestana_activa() == "audio", f"un audio debe abrir su ecualizador ({ins.pestana_activa()})"
    print("✓ elegir un audio abre su ecualizador (pestaña Audio)")
    ins.set_selection([cv.id])
    assert ins.pestana_activa() == "video", f"un video no se queda en el ecualizador ({ins.pestana_activa()})"
    print("✓ elegir un video después: pestaña «Video», no el ecualizador")
    tabs.setCurrentIndex(INDICE["efectos"])     # trabajando en Efectos…
    ins.set_selection([cv2.id])
    assert ins.pestana_activa() == "efectos", "si estabas en Efectos con un video, sigues en Efectos"
    ins.set_selection([ca.id])
    assert ins.pestana_activa() == "audio"
    print("✓ en Video/Efectos/Archivo con videos sigues ahí; un audio siempre abre el ecualizador")
    ins.prefer_audio = True                     # 🎚 en la página Audio: elegir un video no saca del ecualizador
    mv.has_audio = True
    ins.set_selection([cv.id])
    assert ins.pestana_activa() == "audio", f"en la página Audio se queda en el ecualizador ({ins.pestana_activa()})"
    print("✓ en la página Audio, elegir otro clip no te saca del ecualizador")
    ins.prefer_audio = False
    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").remove("secciones/inspector/velocidad")
    ins.set_selection([ca.id])
    sec = ins.speed_sec
    assert ins._pag["audio"].isAncestorOf(sec), "con un audio, «Velocidad» va en la pestaña Audio (debajo del ecualizador)"
    lay = ins._audio_lay
    pos = [lay.itemAt(i).widget() for i in range(lay.count())]
    antes = pos[pos.index(sec) - 1]
    titulo = antes.head.text() if hasattr(antes, "head") else getattr(antes, "title", lambda: "")()
    assert antes is not None and "Ecualizador" in titulo, ("justo debajo del ecualizador", titulo)   # (plegable)
    sec.head.setChecked(False)
    assert not sec.body.isVisibleTo(sec)
    sec.head.setChecked(True)                   # (clic en su cabecera: se abre, como en Resolve)
    assert sec.body.isVisibleTo(sec)
    mv.has_audio = False
    ins.set_selection([cv2.id])
    assert ins._pag["video"].isAncestorOf(sec), "un video sin sonido: «Velocidad» en la pestaña Video"
    print("✓ «🐢 Velocidad» plegable: debajo del ecualizador con sonido, en «Video» sin sonido; se abre al pulsarla")
    ins.set_selection([ca.id])                  # tecla R con un audio y el Inspector en otra pestaña
    tabs.setCurrentIndex(INDICE["efectos"])
    sec.head.setChecked(False)
    ins.focus_speed()
    assert ins.pestana_activa() == "audio" and sec.body.isVisibleTo(sec), (ins.pestana_activa(), sec.body.isVisibleTo(sec))
    print("✓ tecla R: lleva a la velocidad y la abre, aunque estuvieras en otra pestaña")
    print("TODO OK")


if __name__ == "__main__":
    main()
