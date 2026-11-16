"""
⧉ Transiciones reales en el visor (sin ventanas visibles):
  · al poner una transición, su tramo se renderiza en segundo plano y el visor lo enseña encima de las pistas;
  · a mitad de un «Deslizar ←» se ve el clip nuevo entrando por la derecha (imagen de verdad, no un fundido);
  · fuera del tramo no se enseña; cambiar el tipo rehace el tramo; con la opción apagada no se enseña nada;
  · los tramos se reutilizan de la caché (misma clave = mismo archivo).
Ejecutar:  .venv/Scripts/python.exe tests/test_transiciones_visor.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()
_TMP = tempfile.mkdtemp(prefix="reclaimer_transvisor_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass


def pump(app, s):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=30.0):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def main():
    rojo, azul = os.path.join(_TMP, "rojo.mp4"), os.path.join(_TMP, "azul.mp4")
    for path, col in ((rojo, "red"), (azul, "blue")):
        subprocess.run([_FF, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={col}:s=640x360:r=30:d=6",
                        "-pix_fmt", "yuv420p", path], check=True)
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("EditorIA", "EditorIA").setValue("visor/transiciones_reales", "true")
    from editoria.core import zone_render as ZR
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    p = Project.new()
    v1 = next(tr for tr in p.tracks if tr.kind == "video" and tr.name == "V1")
    for mid, path in (("mr", rojo), ("ma", azul)):
        p.media[mid] = MediaItem(id=mid, path=path, kind=KIND_VIDEO, name=mid, duration=6, width=640, height=360,
                                 fps=30, probed=True, has_audio=False)
    p.clips["c1"] = Clip("c1", "mr", v1.id, 0.0, 1.0, 3.0)
    p.clips["c2"] = Clip("c2", "ma", v1.id, 3.0, 1.0, 3.0)
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    win.ctrl.set_transition(["c2"], "slideleft", 1.0)
    zp = win.engine.zones
    assert zp is not None
    assert esperar(app, lambda: zp.zones and zp.zones[0].key in zp.ready), "el tramo no se preparó"
    z = zp.zones[0]
    assert (z.t0, z.t1) == (2.5, 3.5), z
    print(f"✓ al poner «Deslizar ←», su tramo se prepara solo en segundo plano ({os.path.basename(zp.ready[z.key])})")
    from PySide6.QtCore import QPointF
    tl = win.timeline
    assert esperar(app, lambda: tl.render_marks and tl.render_marks[0][2] == "ok", 5), tl.render_marks
    y0, hh = tl._render_band()
    m = tl.render_mark_at(QPointF(tl.x_for(3.0), y0 + hh / 2))
    assert m is not None and m[2] == "ok" and m[3] == "trans", m
    assert tl.render_mark_at(QPointF(tl.x_for(1.0), y0 + hh / 2)) is None
    print("✓ en la regla, una rayita verde marca el tramo ya listo (con su explicación al pasar el ratón)")

    win.engine.seek(3.0)
    assert esperar(app, lambda: (win.engine._sync() or True) and zp.item.isVisible(), 10), "no se ve en el visor"
    img = zp.item.pixmap().toImage()
    izq, der = img.pixelColor(int(img.width() * 0.2), img.height() // 2), img.pixelColor(int(img.width() * 0.8),
                                                                                              img.height() // 2)
    assert izq.red() > 150 and izq.blue() < 100, (izq.red(), izq.blue())
    assert der.blue() > 150 and der.red() < 100, (der.red(), der.blue())
    print("✓ a mitad del tramo el visor enseña el deslizamiento de verdad: rojo a la izquierda, azul entrando por la "
          "derecha")
    r = zp.item.sceneBoundingRect()
    cv = win.engine.preview.canvas
    assert abs(r.width() - cv.W) < 2 and abs(r.height() - cv.H) < 2, (r, cv.W, cv.H)
    print("✓ ocupa justo el lienzo (sin aplastar)")

    win.ctrl.set_clip_props(["c1"], "Opacidad", opacity=0.5) if hasattr(win.ctrl, "set_clip_props") else None
    win.engine._sync()
    assert not zp.item.isVisible(), "con el cabezal en el tramo, un cambio no puede dejar la imagen vieja encima"
    assert esperar(app, lambda: (win.engine._sync() or True) and zp.item.isVisible(), 15), "no vuelve tras el cambio"
    print("✓ al cambiar algo con el cabezal dentro, se quita la imagen vieja y vuelve la nueva en cuanto está")

    win.engine.seek(1.0)
    win.engine._sync()
    assert not zp.item.isVisible(), "fuera del tramo no se enseña"
    print("✓ fuera del tramo, el visor de siempre")

    k_old = z.key
    win.ctrl.set_transition(["c2"], "wipeleft", 1.0)
    assert esperar(app, lambda: zp.zones and zp.zones[0].key != k_old and zp.zones[0].key in zp.ready)
    print("✓ cambiar el tipo de transición rehace su tramo")
    assert ZR.cached(zp.zones[0]) == zp.ready[zp.zones[0].key]

    win.a_real_trans.setChecked(False)
    win.engine.seek(3.0)
    win.engine._sync()
    assert not zp.item.isVisible() and not zp.zones
    win.a_real_trans.setChecked(True)
    assert esperar(app, lambda: zp.zones and zp.zones[0].key in zp.ready, 10)
    print("✓ Reproducción → «⧉ Transiciones reales en el visor» lo apaga y lo enciende (reutiliza la caché)")

    from editoria.core import transitions as TR
    c1, c2 = win.ctrl.project.clips["c1"], win.ctrl.project.clips["c2"]
    assert TR.auto_dur("hblur", c1, c2) == 0.25 and TR.auto_dur("fadeblack", c1, c2) == 0.7
    golpes = [i * 0.6 for i in range(20)]                          # canción a 100 BPM: un golpe cada 0,6 s
    assert TR.auto_dur("fade", c1, c2, golpes) == 0.6, TR.auto_dur("fade", c1, c2, golpes)
    assert TR.auto_dur("hblur", c1, c2, golpes) == 0.3, "½ golpe: lo más cercano a un latigazo rápido"
    assert TR.auto_dur("fade", c1, c2, [20 + i * 0.6 for i in range(20)]) == 0.5, "fuera de la canción: lo típico"
    corto = Clip("x", "mr", v1.id, 0.0, 0.0, 0.3)
    assert TR.auto_dur("fadeblack", corto, c2) <= 0.27, "nunca más de lo que permiten los clips"
    win.ctrl.set_transition(["c2"], "hblur", None)
    assert win.ctrl.project.clips["c2"].fx["trans"] == {"type": "hblur", "dur": 0.25}
    print("✓ ⏱ duración automática: la típica de cada tipo; con música, ½, 1 o 2 golpes; nunca más de lo que cabe")
    # 9:16: el tramo se renderiza con el lado mayor a 960 y se ve con el aspecto del lienzo
    pv = Project.new()
    pv.width, pv.height = 1080, 1920
    vv = next(tr for tr in pv.tracks if tr.kind == "video" and tr.name == "V1")
    pv.media.update(win.ctrl.project.media)
    pv.clips["c1"] = Clip("c1", "mr", vv.id, 0.0, 1.0, 3.0)
    pv.clips["c2"] = Clip("c2", "ma", vv.id, 3.0, 1.0, 3.0)
    win.ctrl._replace(pv, None)
    win.ctrl.missing = set()
    viejas = {z_.key for z_ in zp.zones}
    win.ctrl.set_transition(["c2"], "slideleft", 1.0)
    assert esperar(app, lambda: zp.zones and zp.zones[0].key not in viejas and zp.zones[0].key in zp.ready)
    info = M.probe(zp.ready[zp.zones[0].key])
    assert (info.get("width"), info.get("height")) == (540, 960), info
    win.engine.seek(3.0)
    assert esperar(app, lambda: (win.engine._sync() or True) and zp.item.isVisible(), 10)
    r = zp.item.sceneBoundingRect()
    assert abs(r.width() - 1080) < 2 and abs(r.height() - 1920) < 2, r
    print("✓ en vertical (9:16): render de 540×960 y en el visor con su aspecto")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
