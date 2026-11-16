"""
🎨 Ruedas de color Lift / Gamma / Gain (sin ventanas visibles):
  · sin tocar = neutro (no cambia la caché de color de los proyectos de antes);
  · Sombras sube/baja lo oscuro sin mover el blanco; Luces mueve lo claro sin mover el negro; Medios mueve el gris sin
    mover los extremos;
  · empujar hacia un color (0° rojo, 120° verde, 240° azul) tiñe esa zona de ese color;
  · el .cube de exportar da lo mismo que el visor;
  · en el Inspector: arrastrar una rueda = un solo paso de deshacer, Ctrl+Z lo quita, doble clic vuelve al centro.
Ejecutar:  .venv/Scripts/python.exe tests/test_ruedas_color.py
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_ruedas_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402

from editoria.core import color as C  # noqa: E402


def g(col, *rgb):
    return C.grade(np.array([rgb], np.float32), col)[0]


def main():
    base = {"contrast": 0.2}
    assert C.is_neutral({"lift": [0, 0, 0], "gamma": [0, 0, 0], "gain": [0, 0, 0]})
    assert C.key(dict(base, lift=[0, 0, 0])) == C.key(base), "ruedas sin tocar = misma caché que antes"
    assert not C.is_neutral({"gain": [0.0, 0.0, 0.3]})
    print("✓ sin tocar es neutro (y no cambia la caché de color de los proyectos de antes)")

    lift = {"lift": [0, 0, 0.5]}
    assert g(lift, 0, 0, 0)[0] > 0.1 and abs(g(lift, 1, 1, 1)[0] - 1) < 1e-5
    gain = {"gain": [0, 0, -0.5]}
    assert abs(g(gain, 0, 0, 0)[0]) < 1e-6 and g(gain, 1, 1, 1)[0] < 0.8
    gam = {"gamma": [0, 0, 0.5]}
    assert g(gam, 0.5, 0.5, 0.5)[0] > 0.6 and abs(g(gam, 0, 0, 0)[0]) < 1e-6 and abs(g(gam, 1, 1, 1)[0] - 1) < 1e-5
    print("✓ Sombras mueve lo oscuro (no el blanco), Luces lo claro (no el negro), Medios el gris (no los extremos)")

    for ang, canal in ((0, 0), (120, 1), (240, 2)):
        x, y = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        out = g({"gamma": [x * 0.8, y * 0.8, 0]}, 0.5, 0.5, 0.5)
        assert int(np.argmax(out)) == canal, (ang, out)
    sombra = g({"lift": [-0.6, 0.0, 0]}, 0.1, 0.1, 0.1)       # 180° = cian: menos rojo en las sombras
    assert sombra[0] < sombra[1] and sombra[0] < sombra[2], sombra
    assert C.wheel({"gain": [3, 4, 9]}, "gain") == (0.6, 0.8, 1.0), "fuera del círculo o del rango: se recorta"
    assert C.wheel({"gain": ["x"]}, "gain") == (0.0, 0.0, 0.0)
    print("✓ empujar hacia un color tiñe esa zona (0° rojo, 120° verde, 240° azul; 180° quita rojo)")

    col = {"lift": [0.2, -0.1, 0.1], "gamma": [0, 0.3, -0.2], "gain": [-0.3, 0, 0.25], "saturation": 0.1}
    lut = C.read_cube(C.cube_file(col))
    C._cube_cache.clear()
    pts = np.random.default_rng(3).random((200, 3)).astype(np.float32)
    err = np.abs(C.sample(lut, pts) - C.grade(pts, col)).max()
    assert err < 0.02, err
    print(f"✓ el .cube de exportar da lo mismo que el visor (diferencia máx. {err:.4f})")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    p = Project.new()
    v1 = next(tr for tr in p.tracks if tr.kind == "video" and tr.name == "V1")
    p.media["m"] = MediaItem(id="m", path=os.path.join(_TMP, "v.mp4"), kind=KIND_VIDEO, name="v.mp4", duration=10,
                             width=1920, height=1080, fps=30, probed=True)
    p.clips["c"] = Clip("c", "m", v1.id, 0.0, 0.0, 10.0)
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    win.timeline.set_selection(["c"])
    app.processEvents()
    insp = win.inspector
    insp._refresh()
    wh = insp.color_wheels["gain"]
    n0 = win.ctrl.undo_stack.count()
    for x in (0.1, 0.2, 0.35):                      # arrastrar: varios pasos
        wh.disc.set_pos(x, 0.1)
        wh.disc.moved.emit(x, 0.1)
    wh.level.setValue(20)
    got = win.ctrl.project.clips["c"].color
    assert got and got.get("gain") == [0.35, 0.1, 0.2], got
    assert win.ctrl.undo_stack.count() == n0 + 1, "arrastrar una rueda = un solo paso de deshacer"
    print("✓ arrastrar la rueda de Luces cambia el clip en un solo paso de deshacer")
    win.ctrl.undo_stack.undo()
    assert not win.ctrl.project.clips["c"].color
    insp._refresh()
    assert wh.values() == [0.0, 0.0, 0.0], "el Inspector enseña la rueda en el centro tras Ctrl+Z"
    print("✓ Ctrl+Z lo quita y la rueda vuelve al centro")
    win.ctrl.undo_stack.redo()
    insp._refresh()
    assert wh.values() == [0.35, 0.1, 0.2]
    wh.disc.mouseDoubleClickEvent(None)
    wh.level.mouseDoubleClickEvent(None)
    assert not win.ctrl.project.clips["c"].color, win.ctrl.project.clips["c"].color
    print("✓ doble clic = vuelve al centro (y la barra a 0): el clip queda sin color")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
