"""
⚡ Pre-render de zonas pesadas en el visor (sin ventanas visibles):
  · qué es «pesado»: lo que el visor no enseña (grano, glitch, tono, desenfoque de movimiento, cámara lenta suave) o
    calcula fotograma a fotograma (máscara IA, pantalla verde, zonas, efectos de edit, capas de ajuste); el color no;
  · un clip pesado largo se parte en trozos de unos 8 s, sin cortar nunca dentro de una transición;
  · se prepara primero lo cercano al cabezal y solo a menos de 2 min;
  · en el visor se ve el render (el grano de verdad) y los efectos del visor de debajo se apagan mientras tanto;
  · Reproducción → «⚡ Pre-render de efectos pesados en el visor» lo apaga (las transiciones siguen).
Ejecutar:  .venv/Scripts/python.exe tests/test_prerender_pesado.py
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_pesado_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass


def esperar(app, cond, s=40.0):
    end = time.perf_counter() + s
    while time.perf_counter() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def main():
    gris = os.path.join(_TMP, "gris.mp4")
    subprocess.run([_FF, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=30",
                    "-pix_fmt", "yuv420p", gris], check=True)
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("visor/transiciones_reales", "true")
    st.setValue("visor/prerender_efectos", "true")
    from editoria.core import zone_render as ZR
    from editoria.core.model import KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui.main_window import MainWindow

    p = Project.new()
    v1 = next(tr for tr in p.tracks if tr.kind == "video" and tr.name == "V1")
    p.media["g"] = MediaItem(id="g", path=gris, kind=KIND_VIDEO, name="gris", duration=30, width=640, height=360,
                             fps=30, probed=True, has_audio=False)
    p.clips["a"] = Clip("a", "g", v1.id, 0.0, 0.0, 20.0)
    p.clips["a"].fx = {"grain": 0.9}
    p.clips["b"] = Clip("b", "g", v1.id, 20.0, 0.0, 6.0)
    p.clips["b"].color = {"exposure": 0.5}
    assert ZR.heavy_reason(p, p.clips["a"]) == "grain" and ZR.heavy_reason(p, p.clips["b"]) is None
    for fx in ({"glitch": 0.5}, {"warm": 0.4}, {"motionblur": 0.5}, {"glow": 0.3}, {"blur_regions": [{"x": 0.5}]}):
        assert ZR.heavy_reason(p, Clip("x", "g", v1.id, 0, 0, 1, fx=fx)), fx
    assert ZR.heavy_reason(p, Clip("x", "g", v1.id, 0, 0, 1, speed=0.5, smooth=True)) == "cámara lenta suave"
    print("✓ pesado = lo que el visor no enseña o calcula lento (grano, glitch, tono, desenfoque de movimiento, "
          "resplandor, zonas, cámara lenta suave); el color no")

    zs = ZR.zones(p, heavy=True)
    assert [(z.t0, z.t1, z.why) for z in zs] == [(0.0, 8.0, "fx"), (8.0, 16.0, "fx"), (16.0, 20.0, "fx")], zs
    p.clips["b"].fx = {"trans": {"type": "fade", "dur": 1.0}}
    zs = ZR.zones(p, heavy=True)
    assert zs[-1].t1 == 20.5 and all(not (z.t0 < 19.5 < z.t1 and z.t0 > 19.5) for z in zs), zs
    assert ZR.zones(p, heavy=False)[0].t0 == 19.5
    print("✓ un clip pesado de 20 s se parte en trozos de ~8 s; la transición del final va entera en el último")
    from editoria.core import effects as EF
    q = ZR._slice(p, 8.0, 16.0)
    assert abs(q.clips["a"].fx.get("_t0", 0) - 8.0) < 1e-6
    lf = " ".join(EF.ffmpeg_filters({"flicker": 0.5, "lightleak": 0.5, "shake": 2, "_t0": 8.0}, 8.0, 640, 360))
    assert "(t+8.0000)" in lf and "(T+8.0000)" in lf and "mod(t*" not in lf, lf
    assert "(t+" not in " ".join(EF.ffmpeg_filters({"flicker": 0.5}, 8.0, 640, 360)), "sin trozo, igual que antes"
    p2 = Project.from_dict(p.to_dict())
    p2.clips["a"].fx = {"grain": 0.9, "fade_in": 3.0}
    z2 = ZR.zones(p2, heavy=True)
    assert z2[0].a == 0.0 and all(abs(round(z.a * 60) - z.a * 60) < 1e-6 for z in z2), z2
    adj = MediaItem(id="adj", path=gris, kind=KIND_VIDEO, name="ajuste", duration=30, gen={"kind": "adjust"})
    p2.media["adj"] = adj
    assert ZR.heavy_reason(p2, Clip("x", "adj", v1.id, 0, 0, 5, color={"exposure": 0.2})) is None
    assert ZR.heavy_reason(p2, Clip("x", "adj", v1.id, 0, 0, 5, fx={"vhs": 0.4}))
    print("✓ cada trozo sigue el tiempo del clip (parpadeo, luz, temblor, glitch…), nunca empieza en mitad de un "
          "fundido, va en la rejilla de fotogramas; una capa de ajuste solo de color no es pesada")

    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    zp = win.engine.zones
    win.engine.seek(10.0)
    assert esperar(app, lambda: any(z.t0 <= 10.0 < z.t1 and z.key in zp.ready for z in zp.zones)), "no se preparó"
    print("✓ se prepara primero el trozo donde está el cabezal")
    assert esperar(app, lambda: (win.engine._sync() or True) and zp.item.isVisible(), 10)
    img = zp.item.pixmap().toImage()
    vals = [img.pixelColor(x, y).red() for x in range(40, img.width() - 40, 37) for y in range(40, img.height() - 40, 29)]
    assert max(vals) - min(vals) > 12, (min(vals), max(vals))          # (un gris liso daría 0)
    print(f"✓ el visor enseña el grano de verdad (gris de {min(vals)} a {max(vals)}, no un gris liso)")

    lay = next(iter(win.engine.preview.canvas.layers.values()))
    from PySide6.QtWidgets import QGraphicsColorizeEffect
    eff = QGraphicsColorizeEffect()
    lay.box.setGraphicsEffect(eff)
    win.engine._sync()
    assert zp.item.isVisible() and not eff.isEnabled(), "los efectos de debajo se apagan mientras se ve el tramo"
    assert eff in zp._off
    win.engine.seek(5.0)                                  # (otro trozo del mismo clip: siguen apagados)
    assert esperar(app, lambda: (win.engine._sync() or True) and zp.item.isVisible(), 20)
    win.engine.seek(24.0)
    win.engine._sync()
    assert not zp.item.isVisible() and zp._off == [], "y vuelven al salir"
    print("✓ mientras se ve el tramo, los efectos del visor de debajo no se calculan (y vuelven al salir)")

    largo = Project.new()
    lv = next(tr for tr in largo.tracks if tr.kind == "video" and tr.name == "V1")
    largo.media["g"] = p.media["g"]
    for i in range(40):                                   # 400 s de clips con grano
        largo.clips[f"c{i}"] = Clip(f"c{i}", "g", lv.id, i * 10.0, 0.0, 10.0, fx={"grain": 0.5})
    win.ctrl._replace(largo, None)
    win.ctrl.missing = set()
    win.engine.seek(0.0)
    zp.recalc()
    pend = [z for z, _q in zp._queue] + [z for z in zp.zones if z.key in zp.ready]
    assert pend and max(z.t0 for z in pend) < 130 and len(zp.zones) > 40, (len(zp.zones), max(z.t0 for z in pend))
    print(f"✓ con 400 s pesados solo se preparan los trozos a menos de 2 min del cabezal ({len(pend)} de "
          f"{len(zp.zones)})")
    estados = {m[2] for m in win.timeline.render_marks}
    assert "far" in estados and estados & {"ok", "work", "wait"}, estados
    print(f"✓ la rayita de la regla distingue listo / preparándose / en cola / lejos ({sorted(estados)})")
    win.engine.seek(300.0)
    win.engine._sync()
    assert any(abs(z.t0 - 300) < 60 for z, _q in zp._queue) or any(z.t0 <= 300 < z.t1 for z in zp.zones
                                                                     if z.key in zp.ready)
    print("✓ al irte lejos, se preparan los de allí")

    win.a_prerender_fx.setChecked(False)
    assert not zp.zones
    win.a_prerender_fx.setChecked(True)
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
