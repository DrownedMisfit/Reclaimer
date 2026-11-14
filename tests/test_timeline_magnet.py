"""
Línea de tiempo · imán y pista principal (sin ventanas visibles):
  · 🗣 imán a las palabras de la narración: DESACTIVADO de entrada; activado, pega al principio y al final de cada palabra
    (con la velocidad del clip y solo lo que se ve de él); los chips 🔑 y las banderitas siempre;
  · ∩ se ve a qué se pegó (línea con su nombre) mientras arrastras, y desaparece al soltar;
  · 🔍 Mayús+Z = ver todo el video;
  · 🧲 pista principal magnética (desactivada de entrada): Supr y recortar un borde en la pista principal juntan lo de
    detrás; en otras pistas, como siempre.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline_magnet.py <carpeta>
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, Project  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    st.remove("timeline/iman_palabras")
    st.remove("timeline/principal_magnetica")
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1500, 900)
    pump(app, 0.3)
    ctrl, tl = win.ctrl, win.timeline
    p = Project.new()
    v2, v1, a1 = p.tracks
    p.media["nar"] = MediaItem(id="nar", path="nar.wav", kind=KIND_AUDIO, name="nar.wav", duration=60.0, probed=True)
    p.media["vid"] = MediaItem(id="vid", path="vid.mp4", kind=KIND_VIDEO, name="vid.mp4", duration=60.0, probed=True,
                               width=320, height=180, fps=30.0)
    p.transcripts = {"nar": {"language": "es", "words": [[1.0, 1.4, "hola", 0.9], [2.2, 2.9, "mundo", 0.9],
                                                          [20.0, 20.5, "fuera", 0.9]]}}
    p.clips["n"] = Clip(id="n", media_id="nar", track_id=a1.id, start=10.0, source_in=0.0, duration=8.0)  # 10–18
    p.clips["m1"] = Clip(id="m1", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=5.0)
    p.clips["m2"] = Clip(id="m2", media_id="vid", track_id=v1.id, start=5.0, source_in=5.0, duration=5.0)
    p.clips["m3"] = Clip(id="m3", media_id="vid", track_id=v1.id, start=10.0, source_in=10.0, duration=5.0)
    p.clips["b"] = Clip(id="b", media_id="vid", track_id=v2.id, start=30.0, source_in=0.0, duration=3.0)
    ctrl.project = p
    ctrl.project_changed.emit()
    tl.pps = 40.0
    tl.scroll = 0.0
    pump(app, 0.1)

    # ---------------------------------------------------------------- 🗣 palabras (opcional)
    assert tl.snap_words is False and not win.act_snap_words.isChecked(), "de entrada, sin imán a las palabras"
    assert all(n != "palabra" for _t, n in tl._snap_points(set()))
    win.act_snap_words.setChecked(True)
    pts = tl._snap_points(set())
    palabras = sorted(round(t, 3) for t, n in pts if n == "palabra")
    assert palabras == [11.0, 11.4, 12.2, 12.9], palabras     # (la de 20 s no está dentro del clip)
    arr = tl._snap_arr(set())
    t = tl._snap_fast(12.18, arr)
    assert abs(t - 12.2) < 1e-9 and tl._snap_last == 12.2 and tl._snap_labels[12.2] == "palabra", (t, tl._snap_last)
    win.act_snap_words.setChecked(False)
    assert str(st.value("timeline/iman_palabras")).lower() == "false"
    print("✓ 🗣 imán a las palabras: apagado de entrada; encendido, pega al principio y al final de cada palabra")

    tl.set_kw_marks([{"key": "k", "t": 25.0, "dur": 3.0, "kind": "gameplay", "manual": False, "term": "Halo",
                      "avail": ["gameplay", "none"]}])
    tl.set_kw_visible(True)
    assert (25.0, "palabra clave") in tl._snap_points(set())
    tl.set_kw_visible(False)
    print("✓ los chips 🔑 también atraen (con la fila visible)")

    # ---------------------------------------------------------------- ∩ se ve a qué se pegó
    cb = p.clips["b"]
    y = tl.track_y(p.track_index(v2.id)) + tl.track_h(p.track_index(v2.id)) / 2

    def ev(kind, x, buttons):
        pt = QPointF(x, y)
        return QMouseEvent(kind, pt, tl.mapToGlobal(pt.toPoint()).toPointF(), Qt.LeftButton, buttons, Qt.NoModifier)
    x0 = tl.x_for(cb.start + 1.5)
    tl.mousePressEvent(ev(QEvent.MouseButtonPress, x0, Qt.LeftButton))
    destino = 15.0 + 0.1                                   # el principio del clip, cerca del final de m3 (15 s)
    tl.mouseMoveEvent(ev(QEvent.MouseMove, x0 + 30, Qt.LeftButton))
    tl.mouseMoveEvent(ev(QEvent.MouseMove, tl.x_for(destino + 1.5), Qt.LeftButton))
    assert tl._snap_hit is not None and tl._snap_hit[1] == "clip" and abs(tl._snap_hit[0] - 15.0) < 1e-6, tl._snap_hit
    tl.repaint()
    tl.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, tl.x_for(destino + 1.5), Qt.NoButton))
    assert tl._snap_hit is None
    assert abs(ctrl.project.clips["b"].start - 15.0) < 1e-6, ctrl.project.clips["b"].start
    print("✓ ∩ mientras arrastras se ve a qué se pegó («clip»); al soltar, la línea desaparece")

    # ---------------------------------------------------------------- N a mitad de un arrastre (como Resolve)
    cb = ctrl.project.clips["b"]
    x0 = tl.x_for(cb.start + 1.0)
    tl.mousePressEvent(ev(QEvent.MouseButtonPress, x0, Qt.LeftButton))
    tl.mouseMoveEvent(ev(QEvent.MouseMove, x0 + 30, Qt.LeftButton))
    assert tl.dragging() and tl.snapping
    win._toggle_snap()                                     # N: solo en este arrastre
    assert tl.snapping is False and win.tool_snap.isChecked(), "el imán general no cambia"
    tl.mouseMoveEvent(ev(QEvent.MouseMove, tl.x_for(20.0 + 0.0123 + 1.0), Qt.LeftButton))
    tl.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, tl.x_for(20.0 + 0.0123 + 1.0), Qt.NoButton))
    st = ctrl.project.clips["b"].start
    assert tl.snapping is True, "al soltar, el imán vuelve a como estaba"
    fps = float(ctrl.project.fps or 30)
    assert abs(st * fps - round(st * fps)) < 1e-6, ("sin imán, cae justo en un fotograma", st)
    print(f"✓ N a mitad del arrastre: imán apagado solo ese arrastre; sin imán, el clip cae en un fotograma ({st:.4f} s)")
    ctrl.undo_stack.undo()

    # ---------------------------------------------------------------- la cuchilla se pega a los bordes
    tl.tool = "blade"
    yn = tl.track_y(ctrl.project.track_index(a1.id)) + tl.track_h(ctrl.project.track_index(a1.id)) / 2
    xb = tl.x_for(15.0) - 4                                 # 4 px antes del final de m3 (15 s), sobre la narración
    evb = QMouseEvent(QEvent.MouseButtonPress, QPointF(xb, yn), tl.mapToGlobal(QPointF(xb, yn).toPoint()).toPointF(),
                      Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    tl.mousePressEvent(evb)
    tl.tool = None
    cortes = sorted(round(c.start, 4) for c in ctrl.project.clips.values() if c.media_id == "nar")
    assert 15.0 in cortes, cortes
    print("✓ la cuchilla se pega al borde de un clip de otra pista (corta justo en 15 s)")
    ctrl.undo_stack.undo()
    tl.tool = "select" if hasattr(tl, "tool") else None

    # ---------------------------------------------------------------- 🔍 Mayús+Z
    tl.pps = 400.0
    tl.scroll = 20.0
    acts = [a for a in win.findChildren(type(win.act_snap_words))
            if "Shift+Z" in [k.toString() for k in a.shortcuts()]]
    assert len(acts) == 1, "Mayús+Z existe una sola vez (en «Ajustar a la ventana», junto a Ctrl+0)"
    acts[0].trigger()
    dur = ctrl.project.duration()
    assert tl.scroll == 0.0 and tl.x_for(dur) <= tl.width(), (tl.scroll, tl.x_for(dur), tl.width())
    print("✓ 🔍 Mayús+Z enseña todo el video")

    # ---------------------------------------------------------------- 🧲 pista principal magnética
    assert tl.magnetic_main is False and not win.act_magnetic.isChecked(), "de entrada, sin pista magnética"
    tl.set_selection(["m2"])
    win._delete(False)
    p = ctrl.project
    assert "m2" not in p.clips and abs(p.clips["m3"].start - 10.0) < 1e-6, "sin imán: queda el hueco"
    ctrl.undo_stack.undo()
    win.act_magnetic.setChecked(True)
    p = ctrl.project
    tl.set_selection(["m2"])
    win._delete(False)
    p = ctrl.project
    assert "m2" not in p.clips and abs(p.clips["m3"].start - 5.0) < 1e-6, p.clips["m3"].start
    assert abs(p.clips["n"].start - 5.0) < 1e-6 and abs(p.clips["b"].start - 10.0) < 1e-6,         "todo lo de detrás se adelanta en TODAS las pistas (la narración sigue sincronizada)"
    ctrl.undo_stack.undo()
    p = ctrl.project
    tl.set_selection(["m3"])                              # la narración sigue por debajo de m3: no se junta
    win._delete(False)
    p = ctrl.project
    assert "m3" not in p.clips and abs(p.clips["n"].start - 10.0) < 1e-6 and abs(p.clips["b"].start - 15.0) < 1e-6
    ctrl.undo_stack.undo()
    p = ctrl.project
    print("✓ 🧲 Supr en la principal: todas las pistas a la vez; si la narración pasa por debajo, deja el hueco")
    tl.set_selection(["b"])                                # en otra pista: como siempre
    b_start = p.clips["b"].start
    m3_start = p.clips["m3"].start
    win._delete(False)
    p = ctrl.project
    assert "b" not in p.clips and abs(p.clips["m3"].start - m3_start) < 1e-6, "fuera de la principal no se junta"
    ctrl.undo_stack.undo()
    del b_start
    d = tl._advanced_drag(ctrl.project.clips["m1"], "right", QPointF(tl.x_for(5.0), 10), False, False)
    assert d is not None and d["type"] == "ripple" and d["magnet"], d
    ctrl.magnetic_trim("m1", "right", 4.0, linked=True)
    p = ctrl.project
    assert abs(p.clips["m1"].end - 4.0) < 1e-6 and abs(p.clips["m2"].start - 4.0) < 1e-6
    assert abs(p.clips["n"].start - 9.0) < 1e-6, "recortar también adelanta las otras pistas"
    ctrl.undo_stack.undo()
    ctrl.magnetic_trim("m3", "right", 14.0, linked=True)  # la narración pasa por ese punto: recorta sin juntar
    p = ctrl.project
    assert abs(p.clips["m3"].end - 14.0) < 1e-6 and abs(p.clips["n"].start - 10.0) < 1e-6
    ctrl.undo_stack.undo()
    d = tl._advanced_drag(ctrl.project.clips["m1"], "right", QPointF(tl.x_for(5.0), 10), False, True)
    assert d is None or d["type"] != "ripple"
    assert tl._advanced_drag(ctrl.project.clips["b"], "right", QPointF(tl.x_for(18.0), 10), False, False) is None
    win.act_magnetic.setChecked(False)
    print("✓ 🧲 pista principal magnética (apagada de entrada): Supr y recortar juntan en la principal; fuera, no")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
