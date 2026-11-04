"""
Prueba del «edit musical» automático.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit.py <carpeta_salida>
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
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import edit_maker  # noqa: E402
from editoria.core import effects  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402

BPM, DROP, DUR, SR = 128.0, 8.0, 30.0, 44100


def make_song(path: str):
    """Intro suave (acordes) y, a los 8 s, entra el bombo + bajo (el drop)."""
    t = np.arange(int(DUR * SR)) / SR
    beat = 60 / BPM
    y = 0.08 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277 * t) + np.sin(2 * np.pi * 330 * t))
    # Intro: un clic suave en cada golpe (para que haya ritmo)
    for b in np.arange(0, DROP, beat):
        i = int(b * SR)
        n = int(0.03 * SR)
        y[i:i + n] += 0.15 * np.random.default_rng(int(b * 100)).standard_normal(n) * np.linspace(1, 0, n)
    # Drop: bombo grave y bajo
    for k, b in enumerate(np.arange(DROP, DUR, beat)):
        i = int(b * SR)
        n = int(0.25 * SR)
        tt = np.arange(n) / SR
        kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
        y[i:i + n] += 0.9 * kick[:len(y) - i]
        m = int(beat * SR)
        tb = np.arange(m) / SR
        y[i:i + m] += 0.35 * np.sin(2 * np.pi * (55 if k % 8 < 4 else 65) * tb)[:len(y) - i]
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


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    song = os.path.join(out, "cancion.wav")
    make_song(song)
    clips = []
    for name, src in (("accion.mp4", "testsrc2=s=1280x720:r=30:d=40"),
                      ("fractal.mp4", "mandelbrot=s=1280x720:r=30"),
                      ("vida.mp4", "life=s=320x180:r=30:mold=10:ratio=0.5:death_color=#203040")):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            args = [ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "40",
                    "-vf", "scale=1280:720,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", p]
            r = subprocess.run(args, capture_output=True)
            assert r.returncode == 0, r.stderr.decode(errors="replace")
        clips.append(p)

    # --- 1) La canción: tempo y drop
    info = edit_maker.analyze_song(song)
    drop = edit_maker.find_drop(info)
    assert abs(info["tempo"] - BPM) < 3, info["tempo"]
    assert drop is not None and abs(drop - DROP) < 0.15, drop
    print(f"✓ canción: {info['tempo']:.0f} BPM, drop a los {drop:.2f} s (real {DROP:.2f})")

    # --- 2) El plan
    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})
    plan = edit_maker.plan_edit(info, srcs, length=None, intensity="intenso",
                                quotes=["Esto es una prueba", "Y aquí viene"])
    cl = plan["clips"]
    beats = np.array(info["beats"])
    half = np.sort(np.concatenate([beats, (beats[:-1] + beats[1:]) / 2]))
    after = [c for c in cl if c["part"] != "intro"]
    off = [min(abs(half - c["start"])) for c in after]
    assert max(off) < 0.02, f"cortes fuera del ritmo: {max(off):.3f}"
    intro = [c for c in cl if c["part"] == "intro"]
    assert intro and all(c["duration"] >= 2.0 for c in intro), [c["duration"] for c in intro]
    main_len = np.median([c["duration"] for c in after])
    # Más pausado (2026-10, lo pidió el usuario): planos de 2 golpes o más, nunca de menos de 0,8 s, y sin
    # encadenarse en planos larguísimos (como mucho 2 compases)
    assert 2 * 60 / BPM - 0.02 <= main_len <= 8 * 60 / BPM + 0.01, main_len
    assert min(c["duration"] for c in after[:-1]) >= 0.8 - 0.02, min(c["duration"] for c in after)
    first = after[0]
    assert abs(first["start"] - plan["drop"]) < 0.02 and first["fx"].get("flash"), first
    assert cl[-1]["fx"].get("fade_out"), "el final se funde a negro"
    for a, b in zip(cl, cl[1:]):
        assert abs(a["start"] + a["duration"] - b["start"]) < 0.01, "sin huecos entre planos"
    for c in cl:
        assert c["source_in"] + c["duration"] <= 40.0 + 1e-3
    words = [t for t in plan["texts"] if t["style"].get("color") == edit_maker.QUOTE_RED]
    assert len(words) == 1 and words[0]["content"] == "[VIENE]", plan["texts"]
    print(f"✓ plan: {plan['summary']}")
    print(f"  intro {len(intro)} planos largos · tras el drop mediana {main_len:.2f} s · todos los cortes a ritmo")

    # --- 3) En la aplicación: proyecto Edit, aplicar, deshacer, exportar
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    ctrl.set_project_format("edit")
    p = ctrl.project
    assert (p.width, p.height) == (1080, 1920)
    ids = ctrl.import_paths([song] + clips)
    while ctrl.analyzing:
        pump(app, 0.1)
    by_name = {m.name: m.id for m in p.media.values()}
    for c in cl:
        c["media_id"] = by_name[c["media_id"]]
    plan["music"]["media_id"] = by_name["cancion.wav"]
    created = ctrl.apply_edit_plan(plan, layout="auto")
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    vclips = p.clips_on(v1.id)
    assert len(vclips) == len(cl)
    assert all(c.layout and c.layout["fit"] == "mirrorfill" for c in vclips), "reflejo en los clips horizontales"
    assert all(c.volume == 0 for c in vclips), "sin el sonido del juego"
    music = [c for t in p.tracks if t.kind == TRACK_AUDIO for c in p.clips_on(t.id)]
    assert len(music) == 1 and abs(music[0].duration - DUR) < 0.6
    texts = [c for t in p.tracks if t.kind == TRACK_TEXT for c in p.clips_on(t.id)]
    assert len(texts) == len(plan["texts"])
    assert any(m.label == "💥 Drop" for m in p.markers)
    print(f"✓ en la timeline: {len(vclips)} planos con reflejo, canción, {len(texts)} textos y marcador del drop")
    n_undo = ctrl.undo_stack.count()
    ctrl.undo_stack.undo()
    assert not p.clips_on(v1.id) and not texts[0].id in p.clips
    ctrl.undo_stack.redo()
    assert len(p.clips_on(v1.id)) == len(cl) and ctrl.undo_stack.count() == n_undo
    print("✓ deshacer / rehacer el edit entero en un paso")

    # Visor: destello en el drop
    t_drop = plan["drop"] + 0.02
    win.engine.seek(t_drop)
    pump(app, 0.8)
    layer = win.preview.canvas.layers[v1.id]
    assert layer.fx.isVisible() and layer.fx.opacity() > 0.5, "el visor muestra el destello"
    win.engine.seek(t_drop + 1.0)
    pump(app, 0.6)
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "edit_ui.png"))

    # Inspector: los efectos se pueden cambiar
    c0 = p.clip_at(v1.id, t_drop)
    win.timeline.select_clips([c0.id]) if hasattr(win.timeline, "select_clips") else None
    ctrl.set_clip_props([c0.id], "Temblor", fx=dict(c0.fx, shake=0.6))
    assert p.clips[c0.id].fx["shake"] == 0.6

    # Exportar
    mp4 = os.path.join(out, "edit.mp4")
    args, total = build_command(p, ExportOptions(path=mp4, width=540, height=960, fps=30, encoder="gpu",
                                                 bitrate_mbps=6), ff, os.path.join(out, "f.txt"))
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]

    def luma(t):
        r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", mp4, "-frames:v", "1",
                                   "-vf", "scale=54:96", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        return np.frombuffer(r.stdout, np.uint8).mean()
    flash, before = luma(plan["drop"] + 0.01), luma(plan["drop"] - 0.08)
    normal = max(luma(plan["drop"] + 0.3), luma(plan["drop"] + 0.17))   # el mismo plano, ya sin destello
    assert flash > normal + 40 and before < 30, (flash, before, normal)
    print(f"✓ exportado {total:.1f} s en {time.time() - t0:.1f} s · brillo antes/drop/después "
          f"{before:.0f}/{flash:.0f}/{normal:.0f} (negro → destello → normal)")
    for k, tt in enumerate((1.5, plan["drop"] + 0.03, plan["drop"] + 2.0, total - 0.5)):
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", f"{tt:.3f}", "-i", mp4,
                               "-frames:v", "1", "-vf", "scale=270:-1", os.path.join(out, f"f{k}.png")])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y"] + sum([["-i", os.path.join(out, f"f{k}.png")]
                          for k in range(4)], []) + ["-filter_complex", "hstack=4", os.path.join(out, "frames.png")])
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
