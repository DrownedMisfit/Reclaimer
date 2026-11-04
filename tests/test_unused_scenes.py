"""
Prueba de 🎬 «Escenas sin usar» (panel IA ✨ → Inicio):
  · escenas por cortes (las largas en trozos), cuáles no salen en la línea de tiempo, huecos con audio debajo;
  · en los huecos: tu orden, al ritmo (cada plano termina en un golpe) o, sin ritmo, cada escena lo que dura;
  · «Desde cero»: solo tus escenas, un plano por compás, turnándolas y siguiendo por donde se quedó cada una;
  · el panel de verdad: busca las escenas, enseña solo las no usadas, numera el orden en que las eliges, las mete en
    los huecos y «Desde cero»; Ctrl+Z lo deshace.
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_unused_scenes.py <c>
"""
from __future__ import annotations

import os
import subprocess
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editoria.core import scene_pool as SP  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def test_logic():
    sc = SP.scenes_from_cuts([3.0, 6.0, 30.0], 34.0)
    assert sc[:2] == [(0.0, 3.0), (3.0, 6.0)] and all(b - a <= 8.0 + 1e-6 for a, b in sc), sc
    assert sum(1 for a, b in sc if 6.0 <= a < 30.0) == 3, sc          # 24 s sin cortes → 3 trozos de 8 s
    beats = [i * 0.5 for i in range(200)]                              # 120 BPM
    # en los huecos, al ritmo: cada plano termina en un golpe y como mucho 2 compases (4 s)
    items = SP.fill_items([("v", 10.0, 13.3), ("v", 20.0, 29.0), ("w", 0.0, 1.7)], [(5.0, 14.0)], beats)
    assert [round(i["start"], 2) for i in items] == [5.0, 8.0, 12.0], items
    assert [round(i["duration"], 2) for i in items] == [3.0, 4.0, 1.5], items      # 3,3 → 3 · 9 → 4 · 1,7 → 1,5
    assert all(round(i["start"] + i["duration"], 3) in beats for i in items)
    # sin ritmo: cada escena lo que dura (o hasta que se acaba el hueco); lo que no cabe, fuera
    items = SP.fill_items([("v", 10.0, 13.3), ("v", 20.0, 29.0), ("w", 0.0, 1.7)], [(5.0, 14.0)], [])
    assert [(i["start"], i["duration"]) for i in items] == [(5.0, 3.3), (8.3, 5.7)], items
    print("✓ huecos: en tu orden; con ritmo cada plano acaba en un golpe (máx. 2 compases); sin ritmo, lo que dura")
    # desde cero: un plano por compás (4 golpes = 2 s), turnando y siguiendo por donde se quedó cada escena
    items = SP.scratch_items([("a", 0.0, 6.0), ("b", 10.0, 20.0)], 0.0, 8.0, beats)
    assert [i["media_id"] for i in items] == ["a", "b", "a", "b"], items
    assert [i["source_in"] for i in items] == [0.0, 10.0, 2.0, 12.0], items
    assert all(abs(i["duration"] - 2.0) < 1e-6 for i in items)
    print("✓ desde cero: un plano por compás, turnando tus escenas y siguiendo por donde se quedó cada una")


def test_panel(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "escenas.mp4")
    cols = (("red", 3), ("blue", 3), ("green", 4), ("yellow", 4))
    args = [M.ffmpeg(), "-nostdin", "-v", "error", "-y"]
    for c_, d_ in cols:
        args += ["-f", "lavfi", "-i", f"color=c={c_}:s=320x180:r=30:d={d_}"]
    args += ["-filter_complex", "".join(f"[{k}:v]" for k in range(4)) + "concat=n=4:v=1:a=0[v]", "-map", "[v]",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid]
    subprocess.run(args, check=True)
    song = os.path.join(out, "cancion.wav")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", song],
                   check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    vmid, smid = ctrl.import_now([vid, song])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = SP.main_video_track(p)
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([smid], a1.id, 0.0)
    made = ctrl.add_media([vmid], v1.id, 0.0)
    red = next(i for i in made if p.clips[i].track_id == v1.id)
    ctrl.set_clip_props([red], "corto", duration=3.0)                 # solo la escena roja (0–3 s)
    for cid in [i for i in made if p.clips[i].track_id != v1.id]:
        ctrl.delete_clips([cid]) if hasattr(ctrl, "delete_clips") else None
    assert SP.gaps_over_audio(p, v1.id) == [(3.0, 12.0)], SP.gaps_over_audio(p, v1.id)
    win.ai_panel.tabs.setCurrentIndex(0)
    win.show_panel(win.ai_panel)
    us = win.ai_panel.unused_scenes
    pump(app, 0.3)
    us.scan()
    t0 = time.time()
    while (us.job is None or us.job.isRunning() or len(us.scenes.get(vmid, [])) == 0) and time.time() - t0 < 60:
        pump(app, 0.1)
    pump(app, 0.3)
    shown = [tuple(us.list.item(i).data(Qt.UserRole)) for i in range(us.list.count())]
    starts = [round(s[1]) for s in shown]
    assert starts == [3, 6, 10], (starts, us.scenes)                  # la roja (0–3) ya se usa: no sale
    assert all(not us.list.item(i).icon().isNull() for i in range(us.list.count())), "con miniatura"
    item = {round(tuple(us.list.item(i).data(Qt.UserRole))[1]): us.list.item(i) for i in range(us.list.count())}
    item[10].setSelected(True)                                        # amarilla primero
    item[3].setSelected(True)                                         # luego la azul
    assert [round(o[1]) for o in us.order] == [10, 3] and item[10].text().startswith("1 ·") \
        and item[3].text().startswith("2 ·"), (us.order, item[10].text())
    win.grab().save(os.path.join(out, "escenas_sin_usar.png"))
    print("✓ panel: busca las escenas, enseña solo las no usadas (con miniatura) y numera el orden en que las eliges")
    us.fill()
    vc = sorted((c for c in p.clips_on(v1.id)), key=lambda c: c.start)
    got = [(round(c.start, 2), round(c.source_in, 2), round(c.duration, 2)) for c in vc]
    assert got == [(0.0, 0.0, 3.0), (3.0, 10.0, 4.0), (7.0, 3.0, 3.0)], got   # amarilla 4 s y luego la azul 3 s
    pump(app, 0.3)
    left = [round(tuple(us.list.item(i).data(Qt.UserRole))[1]) for i in range(us.list.count())]
    assert left == [6], left                                          # ya solo queda la verde
    ctrl.undo_stack.undo()
    assert len(p.clips_on(v1.id)) == 1
    print("✓ «Añadir a los huecos»: amarilla y azul, en tu orden, donde hay audio y no hay video; Ctrl+Z lo quita")
    pump(app, 0.3)
    item = {round(tuple(us.list.item(i).data(Qt.UserRole))[1]): us.list.item(i) for i in range(us.list.count())}
    item[6].setSelected(True)
    item[3].setSelected(True)
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        us.scratch()
    finally:
        QMessageBox.question = orig
    vc = sorted((c for c in p.clips_on(v1.id)), key=lambda c: c.start)
    src = [(round(c.start), round(c.source_in, 2)) for c in vc]
    assert [s for s, _x in src] == [0, 2, 4, 6, 8, 10], src           # sin ritmo: cada 2 s, toda la canción
    assert [x for _s, x in src] == [6.0, 3.0, 8.0, 3.0, 6.0, 3.0], src     # verde, azul, verde (sigue), azul…
    ctrl.undo_stack.undo()
    assert [round(c.start) for c in p.clips_on(v1.id)] == [0]
    print("✓ «Desde cero»: solo la verde y la azul, turnándose cada 2 s (sin ritmo) por toda la canción; Ctrl+Z")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    test_logic()
    test_panel(out_)
    print("TODO OK")
