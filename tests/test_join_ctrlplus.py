"""
⇤ Ctrl++ (juntar) «sea donde sea» (sin ventanas visibles):
  · con un clip elegido en una pista SIN huecos (su pista queda elegida), junta igual toda la línea de tiempo;
  · cierra también los huequitos de menos de un fotograma (antes solo los de 0,05 s o más);
  · arregla los solapes diminutos (de redondeo) entre dos trozos de la misma pista;
  · lo vinculado sigue sincronizado; un solo Ctrl+Z.
Ejecutar:  .venv/Scripts/python.exe tests/test_join_ctrlplus.py
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

from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, Project  # noqa: E402


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
    pump(app, 0.3)
    ctrl, tl = win.ctrl, win.timeline
    p = Project.new()
    p.fps = 30.0
    v2, v1, a1 = p.tracks
    p.media["voz"] = MediaItem(id="voz", path="voz.wav", kind=KIND_AUDIO, name="voz.wav", duration=100.0, probed=True)
    p.media["vid"] = MediaItem(id="vid", path="v.mp4", kind=KIND_VIDEO, name="v.mp4", duration=100.0, probed=True,
                               width=320, height=180, fps=30.0)
    # la voz en trozos: un huequito de 10 ms (menos de un fotograma), uno de 0,5 s y un solape de redondeo de 8 ms
    trozos = [(0.0, 0.0, 4.0), (4.010, 5.0, 3.0), (7.510, 9.0, 2.0), (9.502, 12.0, 3.0)]
    for k, (st, si, du) in enumerate(trozos):
        p.clips[f"a{k}"] = Clip(id=f"a{k}", media_id="voz", track_id=a1.id, start=st, source_in=si, duration=du)
    p.clips["v"] = Clip(id="v", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=12.5)
    ctrl.project = p
    ctrl.project_changed.emit()
    pump(app, 0.1)

    # 🔗 las uniones se ven: rojo el huequito, naranja el solape; el hueco de 0,5 s no es una «unión»
    jn = tl._joins()
    tipos = sorted((round(t, 3), tipo) for tid, t, tipo, _c in jn["marcas"] if tid == a1.id)
    assert tipos == [(4.005, "hueco"), (9.506, "solape")], tipos
    tl.resize(1400, 500)
    tl.pps, tl.scroll = 80.0, 0.0
    from PySide6.QtCore import QPointF
    ya = tl.track_y(p.track_index(a1.id)) + tl.track_h(p.track_index(a1.id)) / 2
    assert tl.join_at(QPointF(tl.x_for(4.005), ya)) == ("hueco", 0.010000000000000231) or         tl.join_at(QPointF(tl.x_for(4.005), ya))[0] == "hueco"
    tl.repaint()
    print("✓ uniones: el huequito de 10 ms en rojo y el solape de 8 ms en naranja (con su aviso al pasar el ratón)")

    # un clip elegido en una pista SIN huecos (su pista queda elegida): antes, Ctrl++ «no hacía nada»
    tl.set_selection(["v"])
    tl.set_channels([v1.id])
    assert tl.channel_ids() == [v1.id]
    pasos = ctrl.undo_stack.index()
    win._join_right()
    p = ctrl.project
    assert abs(p.clips["a1"].start - 4.0) < 1e-6, "el huequito de 10 ms se cierra"
    assert abs(p.clips["a2"].end - p.clips["a3"].start) < 1e-6, "el solape de 8 ms se arregla"
    assert abs(p.clips["a2"].duration - 1.992) < 1e-6
    assert p.clips["a2"].start - p.clips["a1"].end > 0.4, "el hueco de 0,5 s (de otra pista) NO se toca"
    assert ctrl.undo_stack.index() == pasos + 1, "un solo Ctrl+Z"
    print("✓ con un clip elegido en otra pista, Ctrl++ cierra los huequitos y solapes diminutos de las demás "
          "(los huecos grandes, puestos a propósito, se quedan)")
    jn = tl._joins()
    assert [tipo for tid, _t, tipo, _c in jn["marcas"] if tid == a1.id] == ["ok", "ok"]
    assert jn["lados"]["a0"] == [False, True]
    tl.repaint()
    print("✓ ya juntos: cada unión es una línea fina y los lados pegados se dibujan rectos (la onda sigue sin cortes)")
    tl.set_channels([])
    win._join_right()                                        # sin pista elegida: TODA la línea de tiempo
    p = ctrl.project
    voz = sorted((c for c in p.clips.values() if c.track_id == a1.id), key=lambda c: c.start)
    for x, y in zip(voz, voz[1:]):
        assert abs(x.end - y.start) < 1e-6, ("debería quedar pegado", x.end, y.start)
    print("✓ sin pista elegida, Ctrl++ junta toda la línea de tiempo (también el hueco de 0,5 s)")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    p = ctrl.project
    assert abs(p.clips["a1"].start - 4.010) < 1e-9
    print("✓ un Ctrl+Z lo devuelve todo")

    # vinculado: video + su sonido con un huequito: se juntan los dos
    q = Project.new()
    q.fps = 30.0
    w2, w1, b1 = q.tracks
    q.media["vid"] = p.media["vid"]
    for k, st in enumerate((0.0, 3.02)):
        q.clips[f"v{k}"] = Clip(id=f"v{k}", media_id="vid", track_id=w1.id, start=st, source_in=st, duration=3.0,
                                link=f"L{k}")
        q.clips[f"s{k}"] = Clip(id=f"s{k}", media_id="vid", track_id=b1.id, start=st, source_in=st, duration=3.0,
                                link=f"L{k}")
    ctrl.project = q
    ctrl.project_changed.emit()
    tl.set_selection([])
    tl.set_channels([])
    win._join_right()
    q = ctrl.project
    assert abs(q.clips["v1"].start - 3.0) < 1e-6 and abs(q.clips["s1"].start - 3.0) < 1e-6
    print("✓ el huequito de 20 ms (menos de un fotograma) se cierra en la imagen y en su sonido a la vez")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
