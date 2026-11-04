"""
Prueba del motor de EDITS 2.0 (estilos, cortes según la estructura de la canción, velocity, efectos).
Ejecutar:  .venv/Scripts/python.exe tests/test_edits2.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import edit_engine, edit_maker, music_analysis  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402

BPM, SR = 128.0, 44100
INTRO, BUILD, DROP, STOP, END = 0.0, 7.5, 15.0, 26.25, 34.0
BEAT = 60 / BPM


def make_song(path: str):
    """Intro (acordes y platillo), subida (caja cada vez más rápida), drop (bombo + caja en 2 y 4 + bajo),
    una parada en seco y vuelta al drop."""
    rng = np.random.default_rng(3)
    t = np.arange(int(END * SR)) / SR
    y = 0.06 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277 * t) + np.sin(2 * np.pi * 330 * t))

    def add(at, sig, gain):
        i = int(at * SR)
        n = min(len(sig), len(y) - i)
        if n > 0:
            y[i:i + n] += gain * sig[:n]

    def kick():
        tt = np.arange(int(0.25 * SR)) / SR
        return np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)

    def snare():
        n = int(0.12 * SR)
        tt = np.arange(n) / SR
        return (rng.standard_normal(n) * 0.7 + 0.5 * np.sin(2 * np.pi * 200 * tt)) * np.exp(-tt * 30)

    def hat():
        n = int(0.03 * SR)
        return np.diff(rng.standard_normal(n + 1)) * np.linspace(1, 0, n)

    for b in np.arange(INTRO, BUILD, BEAT):
        add(b, hat(), 0.12)
    k = 0
    for b in np.arange(BUILD, DROP - 1e-6, BEAT):   # subida: caja en cada golpe, luego en medios
        add(b, snare(), 0.25 + 0.4 * (b - BUILD) / (DROP - BUILD))
        if b > DROP - 4 * BEAT:
            add(b + BEAT / 2, snare(), 0.6)
        k += 1
    for j, b in enumerate(np.arange(DROP, END - 1e-6, BEAT)):
        if STOP - 1e-3 <= b < STOP + 2 * BEAT - 1e-3:
            continue                                  # parada: dos golpes de silencio
        add(b, kick(), 0.9)
        if j % 2 == 1:
            add(b, snare(), 0.7)
        add(b + BEAT / 2, hat(), 0.2)
        add(b, 0.3 * np.sin(2 * np.pi * 55 * np.arange(int(BEAT * SR)) / SR), 1.0)
    i0, i1 = int(STOP * SR), int((STOP + 2 * BEAT) * SR)
    y[i0:i1] *= 0.003                                  # la parada: casi silencio
    y = np.clip(y / np.abs(y).max() * 0.9, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def check_plan(plan, song, start, name):
    cl = plan["clips"]
    for a, b in zip(cl, cl[1:]):
        assert abs(a["start"] + a["duration"] - b["start"]) < 0.01, (name, "hueco", a, b)
    end = cl[-1]["start"] + cl[-1]["duration"]
    assert abs(end - plan["music"]["duration"]) < 0.05, (name, end, plan["music"])
    # Cada plano nuevo (no la 2.ª parte de un velocity ni una congelación) empieza en un golpe o subdivisión
    beats = np.array(song["beats"]) - start
    q = np.sort(np.concatenate([beats] + [beats[:-1] + (beats[1:] - beats[:-1]) * f for f in (0.25, 0.5, 0.75)]))
    firsts = [c for k, c in enumerate(cl) if k == 0 or c["media_id"] != cl[k - 1]["media_id"] or
              abs(c["source_in"] - (cl[k - 1]["source_in"] + cl[k - 1]["duration"] * cl[k - 1]["speed"])) > 0.02]
    firsts = [c for c in firsts if c["start"] > beats[0] + 0.01 and c["speed"] != 0]
    off = max(min(abs(q - c["start"])) for c in firsts)
    assert off < 0.03, (name, "corte fuera del ritmo", off)
    return cl


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    s = QSettings("EditorIA", "EditorIA")
    saved_style = s.value("edits/estilo")
    ff = media_tools.ffmpeg()
    song_path = os.path.join(out, "cancion2.wav")
    make_song(song_path)
    clips = []
    for name, src in (("accion.mp4", "testsrc2=s=1280x720:r=30:d=60"),
                      ("fractal.mp4", "mandelbrot=s=1280x720:r=30"),
                      ("vida.mp4", "life=s=320x180:r=30:mold=10:ratio=0.5:death_color=#203040")):
        p = os.path.join(out, "e2_" + name)
        if not os.path.exists(p):
            args = [ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "60",
                    "-vf", "scale=1280:720,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", p]
            r = subprocess.run(args, capture_output=True)
            assert r.returncode == 0, r.stderr.decode(errors="replace")
        clips.append(p)

    # --- 1) Estructura de la canción
    song = edit_maker.analyze_song(song_path)
    edit_engine.enrich(song, media_tools.decode_mono(song_path, music_analysis.SR), music_analysis.SR)
    assert abs(song["tempo"] - BPM) < 3, song["tempo"]
    drop = edit_maker.find_drop(song)
    assert drop is not None and abs(drop - DROP) < 0.2, drop
    kinds = [(round(x["a"], 1), x["kind"]) for x in song["sections"]]
    assert any(k == "drop" and abs(a - DROP) < 2.5 for a, k in kinds), kinds
    assert any(k in ("build", "intro") and a < DROP for a, k in kinds), kinds
    assert any(abs(a - STOP) < 0.3 for a, _d in song["stops"]), song["stops"]
    print(f"✓ canción: {song['tempo']:.0f} BPM, drop {drop:.2f} s, paradas {song['stops']}, secciones {kinds}")

    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})

    # --- 2) Los estilos
    plans = {}
    for st in edit_engine.STYLES:
        plan = edit_engine.plan_v2(song, srcs, style=st, length=None, quotes=["Esto es una prueba", "Y aquí viene"])
        cl = check_plan(plan, song, plan["music"]["source_in"], st)
        plans[st] = plan
        for c in cl:
            src = next(x for x in srcs if x["media_id"] == c["media_id"])
            assert c["source_in"] + c["duration"] * max(c["speed"], 0.01) <= src["duration"] + 0.05, c
        print(f"  ✓ {st}: {plan['summary']}")
    ph = plans["phonk"]["clips"]
    assert {0.35, 2.4} <= {c["speed"] for c in ph}, "velocity"
    d_rel = plans["phonk"]["drop"]
    at_drop = next(c for c in ph if abs(c["start"] - d_rel) < 0.03)
    assert at_drop["fx"].get("flash") and at_drop["fx"].get("shake"), at_drop
    frz = [c for c in ph if c["speed"] == 0]
    assert frz and abs(frz[0]["start"] - (STOP - plans["phonk"]["music"]["source_in"])) < 0.3, frz
    bn = plans["epico_bn"]["clips"]
    assert all(c["color"]["saturation"] == -1.0 and c["fx"].get("letterbox") for c in bn)
    assert next(c for c in bn if abs(c["start"] - plans["epico_bn"]["drop"]) < 0.03)["fx"].get("invert")
    assert any(c["speed"] == 0.5 and c["smooth"] for c in bn), "cámara lenta suave en lo tranquilo"
    assert not any(c["fx"].get("flash") or c["fx"].get("shake") for c in plans["cine"]["clips"])
    assert any(c.get("trans") for c in plans["cine"]["clips"])
    assert any(c["fx"].get("glitch") for c in plans["hype"]["clips"])
    n = lambda pl: len({c["shot"] for c in pl["clips"]})   # noqa: E731
    assert n(plans["hype"]) > n(plans["phonk"]) > n(plans["cine"]), (n(plans["hype"]), n(plans["phonk"]),
                                                                       n(plans["cine"]))
    # Cortes antes del drop más rápidos al final de la subida
    pre = [c for c in ph if plans["phonk"]["drop"] - 4 < c["start"] < plans["phonk"]["drop"] and c["speed"] != 2.4]
    early = [c for c in ph if c["start"] < plans["phonk"]["drop"] - 6 and c["speed"] != 2.4]
    assert np.median([c["duration"] for c in pre]) < np.median([c["duration"] for c in early]), "la subida acelera"
    # Opciones: quitar efectos
    off = edit_engine.plan_v2(song, srcs, style="phonk", length=None, overrides={
        "velocity": False, "impact": "", "shake": False, "punch": False, "strobe": False, "freeze": False,
        "grain": 0.0, "vignette": 0.0, "grade": {}, "transitions": "", "extras": False})
    assert {c["speed"] for c in off["clips"]} == {1.0}
    assert not any(set(c["fx"]) - {"fade_in", "fade_out"} for c in off["clips"]), off["clips"][:3]
    assert not any(c.get("color") or c.get("trans") or c["zoom"] and c["zoom"][0][1] > 1.15
                   for c in off["clips"])
    p30 = edit_engine.plan_v2(song, srcs, style="phonk", length=20.0)
    assert abs(p30["music"]["duration"] - 20.0) < 2.5, p30["music"]
    print("✓ estilos distintos entre sí, velocity, impact frames, congelar en la parada, opciones que se quitan")

    # --- 3) En la aplicación
    app = QApplication(sys.argv)
    from editoria.ui.edit_dialog import EditDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    ctrl.set_project_format("edit")
    p = ctrl.project
    ctrl.import_paths([song_path] + clips)
    while ctrl.analyzing:
        pump(app, 0.1)
    by_name = {m.name: m.id for m in p.media.values()}
    plan = edit_engine.plan_v2(song, srcs, style="epico_bn", length=None,
                               overrides={"slowmo_calm": False})   # sin minterpolate: export rápido
    for c in plan["clips"]:
        c["media_id"] = by_name[c["media_id"]]
    plan["music"]["media_id"] = by_name["cancion2.wav"]
    ctrl.apply_edit_plan(plan, layout="auto")
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    vc = p.clips_on(v1.id)
    assert len(vc) == len(plan["clips"])
    assert {round(c.speed, 2) for c in vc} >= {0.35, 2.4, 0.0}, {c.speed for c in vc}
    assert all(c.color and c.color["saturation"] == -1.0 for c in vc)
    assert any((c.fx or {}).get("trans") for c in vc) and any((c.fx or {}).get("invert") for c in vc)
    fast = next(c for c in vc if c.speed == 2.4 and c.zoom_kf == [])
    assert fast.src_len > fast.duration * 2.3
    ctrl.undo_stack.undo()
    assert not p.clips_on(v1.id)
    ctrl.undo_stack.redo()
    assert len(p.clips_on(v1.id)) == len(plan["clips"])
    print(f"✓ en la timeline: {len(vc)} planos con velocidad, color, transiciones y efectos; deshacer en un paso")
    t_drop = plan["drop"] + 0.03
    win.engine.seek(t_drop)
    pump(app, 0.8)
    layer = win.preview.canvas.layers[v1.id]
    assert layer.neg.isVisible() and layer.bars[0].isVisible(), "el visor muestra el negativo y las barras"
    assert layer.neg.zValue() < layer.bars[0].zValue(), "las barras siguen negras con el negativo"
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "edits2_ui.png"))

    mp4 = os.path.join(out, "edit2.mp4")
    args, total = build_command(p, ExportOptions(path=mp4, width=540, height=960, fps=30, encoder="gpu",
                                                 bitrate_mbps=6), ff, os.path.join(out, "f2.txt"))
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2500:]
    dur = media_tools.probe(mp4)["duration"]
    assert abs(dur - total) < 0.3, (dur, total)

    def frame(t):
        r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", mp4, "-frames:v", "1",
                                   "-vf", "scale=54:96", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        return np.frombuffer(r.stdout, np.uint8).reshape(96, 54, 3).astype(int)
    f = frame(plan["drop"] + 1.2)
    assert np.abs(f[:, :, 0] - f[:, :, 1]).mean() < 6, "blanco y negro"
    assert f[:6].mean() < 20 and f[-6:].mean() < 20, "barras de cine"
    took = time.time() - t0
    print(f"✓ exportado {total:.1f} s en {took:.1f} s (blanco y negro con barras)")
    # los planos seguidos se encadenan (antes: una capa por plano sobre todo el video → ~650 s aquí)
    assert took < 240, f"exportar el edit tardó {took:.0f} s"

    # --- 4) La ventana
    dlg = EditDialog(ctrl, win)
    dlg.style.setCurrentIndex(dlg.style.findData("epico_bn"))
    o = dlg.options()
    assert o["style"] == "epico_bn" and o["overrides"]["impact"] == "invert" and o["overrides"]["letterbox"] > 0
    dlg.opt["letterbox"].setChecked(False)
    dlg.opt["velocity"].setChecked(False)
    dlg.length.setCurrentIndex(dlg.length.findData(30.0))
    o = dlg.options()
    assert o["overrides"]["letterbox"] == 0 and o["overrides"]["velocity"] is False and o["length"] == 30.0
    assert dlg.style.findData("halo") < 0, "sin estilos con nombres concretos (se fusionó con Hype gaming)"
    assert not any("Halo" in dlg.style.itemText(i) for i in range(dlg.style.count()))
    dlg.style.setCurrentIndex(dlg.style.findData("cine"))
    assert not dlg.opt["velocity"].isChecked() and dlg.opt["letterbox"].isChecked()
    dlg.show()
    pump(app, 0.3)
    dlg.grab().save(os.path.join(out, "edits2_dialog.png"))
    dlg.close()
    print("✓ ventana: estilos, duración 30/45/60 y cada efecto activable")

    if saved_style is None:
        s.remove("edits/estilo")
    else:
        s.setValue("edits/estilo", saved_style)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
