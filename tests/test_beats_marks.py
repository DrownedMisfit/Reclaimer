"""
🥁 Golpes de la música en la línea de tiempo (sin ventanas visibles; ritmo «de mentira», sin escuchar audio):
  · botón 🥁 en la esquina (junto a 🔑), siempre visible, con la explicación en el tooltip;
  · al elegir una canción se pide su ritmo (una vez); tu narración o un gameplay largo, no;
  · en la regla: golpes, compases (más largos), fuertes (naranja) y 💥 drop (rojo), y guías finas por compás;
  · el imán dice a qué se pegó: «💥 drop», «compás» o «golpe»;
  · «📍 Marcadores en cada compás» (numerados) en un solo paso de Ctrl+Z.
Ejecutar:  .venv/Scripts/python.exe tests/test_beats_marks.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_beats_", dir=_TMPROOT)
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

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.model import KIND_AUDIO, TRACK_AUDIO, Clip, MediaItem, Project  # noqa: E402

BPM = 120
P = 60 / BPM      # 0,5 s por golpe


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
    win.resize(1400, 800)
    pump(app, 0.3)
    ctrl, tl = win.ctrl, win.timeline
    p = Project.new()
    auds = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    p.media["song"] = MediaItem(id="song", path=os.path.join(_TMP, "song.mp3"), kind=KIND_AUDIO, name="song.mp3",
                                duration=40.0, probed=True)
    p.media["voz"] = MediaItem(id="voz", path=os.path.join(_TMP, "voz.wav"), kind=KIND_AUDIO, name="voz.wav",
                               duration=40.0, probed=True)
    p.transcripts = {"voz": {"language": "es", "words": [[0.0, 0.4, "hola", 0.9]]}}
    p.clips["cs"] = Clip(id="cs", media_id="song", track_id=auds[-1].id, start=2.0, source_in=0.0, duration=20.0)
    p.clips["cv"] = Clip(id="cv", media_id="voz", track_id=auds[0].id, start=0.0, source_in=0.0, duration=20.0)
    ctrl.project = p
    ctrl.project_replaced.emit()
    pump(app, 0.2)

    b = tl._beats_button()
    tl._place_corner()
    assert b.isVisible() and b.text() == "🥁" and "golpe" in b.toolTip(), (b.isVisible(), b.text())
    print("✓ botón 🥁 en la esquina, a la vista, con la explicación en el tooltip")

    pedidos = []
    real = ctrl.analyze_rhythm
    ctrl.analyze_rhythm = lambda mids, force=False: (pedidos.append(set(mids)), 0)[1]
    tl.beats_visible = True
    tl.set_selection(["cv"])
    assert not pedidos, "tu narración no se escucha como canción"
    p.media["fx"] = MediaItem(id="fx", path=os.path.join(_TMP, "fx.wav"), kind=KIND_AUDIO, name="fx.wav",
                              duration=2.0, probed=True)
    p.clips["cf"] = Clip(id="cf", media_id="fx", track_id=auds[0].id, start=30.0, source_in=0.0, duration=2.0)
    tl.set_selection(["cf"])
    assert not pedidos, "un efecto de 2 s no es una canción"
    tl.set_selection(["cs"])
    assert pedidos == [{"song"}], pedidos
    ctrl.analyze_rhythm = real
    print("✓ al elegir la canción se pide su ritmo; la narración y un efecto cortito, no")

    beats = [round(k * P, 4) for k in range(80)]
    ctrl.rhythm["song"] = {"tempo": BPM, "beats": beats, "downbeats": beats[::4], "strong": beats[::2],
                           "drop": 8.0, "sections": [], "stops": [], "duration": 40.0}
    ctrl.rhythm_changed.emit()
    bm = tl.beat_marks()
    assert bm["drops"] == [10.0] and bm["downbeats"][0] == 2.0 and len(bm["beats"]) == 40, (bm["drops"], len(bm["beats"]))
    tl.pps = 30.0
    tl.scroll = 0.0
    img = QImage(tl.size(), QImage.Format_ARGB32)
    img.fill(0)
    tl.render(img)
    xd = int(round(tl.x_for(10.0)))
    rojo = [img.pixelColor(x, tl.RULER_H - 3) for x in range(xd - 2, xd + 3)]
    assert any(c.red() > 180 and c.green() < 120 for c in rojo), [c.name() for c in rojo]
    xdown = int(round(tl.x_for(4.0)))
    blanco = [img.pixelColor(x, tl.RULER_H - 3) for x in range(xdown - 1, xdown + 2)]
    assert any(c.lightness() > 150 for c in blanco), [c.name() for c in blanco]
    print("✓ en la regla: rayas en cada golpe y compás, y la línea roja del 💥 drop")

    pts = dict((round(t, 3), n) for t, n in tl._snap_points(set()))      # 30 px/s: golpes a 15 px
    assert pts.get(10.0) == "💥 drop" and pts.get(4.0) == "compás" and pts.get(2.5) is None, \
        (pts.get(10.0), pts.get(4.0), pts.get(2.5))
    tl.pps = 80.0
    pts = dict((round(t, 3), n) for t, n in tl._snap_points(set()))      # 80 px/s: golpes a 40 px
    assert pts.get(10.0) == "💥 drop" and pts.get(4.0) == "compás" and pts.get(2.5) == "golpe", \
        (pts.get(10.0), pts.get(4.0), pts.get(2.5))
    tl.pps = 3.0
    pts = dict((round(t, 3), n) for t, n in tl._snap_points(set()))      # muy lejos: solo el drop
    assert pts.get(10.0) == "💥 drop" and pts.get(4.0) is None, (pts.get(10.0), pts.get(4.0))
    tl.pps = 80.0
    cut = dict((round(t, 3), n) for t, n in tl._snap_points({"cs"}, keep_rhythm=True))
    assert cut.get(2.5) == "golpe", "la cuchilla sobre la canción se pega a sus golpes"
    print("✓ el imán dice a qué se pegó (💥 drop, compás, golpe) y según el zoom: de lejos, solo compases o el drop; "
          "la cuchilla se pega a los golpes de su propia canción")

    n0 = len(p.markers)
    n = ctrl.add_rhythm_markers(["cs"], bars=True)
    assert n == 10 and len(ctrl.project.markers) == n0 + 10, n
    assert sorted(m.label for m in ctrl.project.markers)[:2] == ["1", "10"]
    ctrl.undo_stack.undo()
    assert len(ctrl.project.markers) == n0
    print("✓ «📍 Marcadores en cada compás»: numerados, en un solo paso de Ctrl+Z")

    tl.set_beats_visible(False)
    assert not b.isChecked()
    tl.set_beats_visible(True)
    assert b.isChecked()
    ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
