"""
Prueba de los temas limpios: los trozos diminutos se unen al de al lado, dos seguidos iguales se juntan, y si
borras la narración los temas que se quedan sin sonido debajo se van también (un solo Ctrl+Z lo devuelve todo).
Ejecutar:  .venv/Scripts/python.exe tests/test_topics_tidy.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
import time  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, Marker, new_id
    wav = os.path.join(out, "voz.wav")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=600", wav],
                   check=True)
    ctrl = ProjectController()
    p = ctrl.project
    (mid,) = ctrl.import_now([wav])
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    (cid,) = ctrl.add_media([mid], a1.id, 0.0)
    spans = [(0, 120, "INTRODUCCIÓN"), (120, 126, "COMBATE"), (126, 300, "HISTORIA"), (300, 450, "CONCLUSIÓN"),
             (450, 600, "CONCLUSIÓN")]
    p.markers = [Marker(new_id(), a, lab, "#888", end=b, kind="topic") for a, b, lab in spans]
    ctrl._tidy_topics(p)
    tp = sorted((m for m in p.markers if m.kind == "topic"), key=lambda m: m.time)
    assert [m.label for m in tp] == ["INTRODUCCIÓN", "HISTORIA", "CONCLUSIÓN"], [(m.label, m.time, m.end) for m in tp]
    assert tp[0].end == 126 and tp[-1].end == 600, [(m.label, m.time, m.end) for m in tp]
    print("✓ temas limpios: el trozo diminuto se une al anterior y las dos «CONCLUSIÓN» seguidas son una")
    ctrl.delete_clips([cid])
    assert not any(m.kind == "topic" for m in p.markers), "sin narración, sin temas"
    ctrl.undo_stack.undo()
    assert sum(1 for m in p.markers if m.kind == "topic") == 3 and cid in p.clips
    ctrl.remove_all_topics()
    assert not any(m.kind == "topic" for m in p.markers)
    print("✓ al borrar la narración se van sus temas (Ctrl+Z los devuelve) · «Quitar todos los temas»")
    ctrl.undo_stack.undo()
    n = ctrl.keep_topics({"HISTORIA"})
    tp = [m for m in p.markers if m.kind == "topic"]
    assert n == 1 and len(tp) == 1 and tp[0].label == "HISTORIA" and abs(tp[0].time) < 1e-6, tp
    assert abs(p.duration() - 174.0) < 0.5, p.duration()
    ctrl.undo_stack.undo()
    assert abs(p.duration() - 600.0) < 0.5
    print("✓ «Quedarme solo con estos temas»: lo demás se quita y se junta (Ctrl+Z vuelve)")

    # Mandar a Medios (con la ventana): un video corto con dos temas
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "partida.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=300:d=8", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", vid],
                   check=True)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    c2 = win.ctrl
    (vmid,) = c2.import_now([vid])
    while c2.analyzing:
        app.processEvents()
        time.sleep(0.05)
    v1 = [t for t in c2.project.tracks if t.kind == TRACK_VIDEO][-1]
    c2.add_media([vmid], v1.id, 0.0)
    c2.project.markers = [Marker(new_id(), 0.0, "COMBATE", "#c33", end=3.0, kind="topic"),
                          Marker(new_id(), 3.0, "HISTORIA", "#36c", end=6.0, kind="topic"),
                          Marker(new_id(), 6.0, "COMBATE", "#c33", end=8.0, kind="topic")]
    win.topics_to_media({"COMBATE"})
    t0 = time.time()
    while manager().tasks and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.05)
    seg = [m for m in c2.project.media.values() if m.category == "Temas · Combate"]
    assert len(seg) == 2 and all("combate" in m.tags for m in seg), [(m.name, m.category) for m in seg]
    durs = sorted(round(M.probe(m.path)["duration"]) for m in seg)
    assert durs == [2, 3], durs
    print("✓ «Mandar a Medios»: cada tramo de «Combate» es un video en «Temas · Combate» (con su palabra clave)")
    c2.undo_stack.setClean()
    c2._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
