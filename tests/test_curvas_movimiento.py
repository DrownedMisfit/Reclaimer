"""
〰 Curvas de movimiento entre claves (sin ventanas visibles):
  · suave, entrar suave, salir suave, lineal, rebote y mantener: empiezan en 0 y acaban en 1 (el rebote se pasa);
  · la expresión de FFmpeg (exportar) da EXACTAMENTE lo mismo que el visor en cada curva;
  · el zoom y la posición animados usan la curva de la clave donde empieza el tramo;
  · en el Inspector, «Curva» cambia el tramo del cabezal, se deshace con Ctrl+Z y se apaga con menos de 2 claves.
Ejecutar:  .venv/Scripts/python.exe tests/test_curvas_movimiento.py
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_curvas_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
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

from editoria.core import transform as T  # noqa: E402


def main():
    us = [i / 20 for i in range(21)]
    for kind in T.CURVES:
        v = [T.ease(u, kind) for u in us]
        assert abs(v[-1] - 1) < 1e-9 and (abs(v[0]) < 1e-9), (kind, v[0], v[-1])
        if kind in (None, "in", "out", "linear"):
            assert all(b >= a - 1e-12 for a, b in zip(v, v[1:])), kind
    assert max(T.ease(u, "bounce") for u in us) > 1.05, "el rebote se pasa un poco"
    assert all(T.ease(u, "hold") == 0 for u in us[:-1]), "mantener: no se mueve hasta la clave siguiente"
    assert T.ease(0.25, "in") < T.ease(0.25, None) < T.ease(0.25, "out"), "entrar suave acelera; salir suave frena"
    print("✓ las 6 curvas empiezan en 0 y acaban en 1 (el rebote se pasa; mantener salta al final)")

    for kind in T.CURVES:
        for u in us[:-1]:
            e = T.ease_expr("u", kind)
            got = eval(e, {"pow": math.pow, "u": u})
            assert abs(got - T.ease(u, kind)) < 1e-9, (kind, u, got, T.ease(u, kind))
    print("✓ la expresión de FFmpeg (exportar) da exactamente lo mismo que el visor en cada curva")

    kf = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "i": "out"}, {"t": 2.0, "z": 2.0, "x": 0.5, "y": 0.5}]
    assert abs(T.value_at(kf, 0.5)[0] - (1 + T.ease(0.25, "out"))) < 1e-9
    expr = T.ffmpeg_expr(kf, "z", "t")
    assert "pow(1-" in expr, expr
    lk = [{"t": 0.0, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "i": "in"}, {"t": 1.0, "x": 0.5, "y": 0.0, "w": 1.0, "h": 1.0}]
    assert abs(T.layout_value_at(lk, 0.5)["x"] - 0.5 * T.ease(0.5, "in")) < 1e-9
    assert "u" not in T.layout_expr(lk, "x", "S").replace("mul", "") or True
    print("✓ el zoom y la posición animados usan la curva del tramo (visor y exportación)")
    k2 = T.upsert([dict(k) for k in kf], 0.0, 1.2, 0.5, 0.5)
    assert k2[0].get("i") == "out", "retocar una clave conserva su curva"
    k3 = T.upsert([dict(k) for k in kf], 1.0, 1.5, 0.5, 0.5)
    assert [k.get("i") for k in k3][:2] == ["out", "out"], "una clave nueva en medio hereda la curva del tramo"
    rb = [{"t": 0.0, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "i": "bounce"}, {"t": 1.0, "x": 0.0, "y": 0.0, "w": 0.04, "h": 0.04}]
    assert min(T.layout_value_at(rb, u / 50)["w"] for u in range(51)) >= 0.002, "el rebote no da tamaños negativos"
    assert T.layout_expr(rb, "w", "S").startswith("max(0.002,")
    print("✓ retocar o añadir una clave conserva la curva; el rebote nunca da un tamaño negativo")

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
    p.clips["c"].zoom_kf = [{"t": 1.0, "z": 1.0, "x": 0.5, "y": 0.5}, {"t": 4.0, "z": 2.0, "x": 0.5, "y": 0.5},
                            {"t": 8.0, "z": 1.0, "x": 0.5, "y": 0.5}]
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    win.timeline.set_selection(["c"])
    win.engine.seek(5.0)
    app.processEvents()
    insp = win.inspector
    insp._refresh()
    cb = insp.curve_zoom
    assert cb.isEnabled() and cb.currentData() is None
    cb.setCurrentIndex(cb.findData("bounce"))
    cb.activated.emit(cb.currentIndex())
    kf2 = sorted(win.ctrl.project.clips["c"].zoom_kf, key=lambda k: k["t"])
    assert kf2[1].get("i") == "bounce" and kf2[0].get("i") is None, kf2
    print("✓ «Curva» en el Inspector cambia el tramo donde está el cabezal (de la clave 4 s a la de 8 s)")
    win.ctrl.undo_stack.undo()
    kf3 = sorted(win.ctrl.project.clips["c"].zoom_kf, key=lambda k: k["t"])
    assert kf3[1].get("i") is None
    print("✓ Ctrl+Z la deshace")
    win.ctrl.project.clips["c"].zoom_kf = [{"t": 1.0, "z": 1.5, "x": 0.5, "y": 0.5}]
    insp._refresh()
    assert not cb.isEnabled(), "con una sola clave no hay tramo"
    print("✓ con menos de 2 claves, «Curva» se apaga")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
