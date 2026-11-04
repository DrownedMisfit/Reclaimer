"""
Prueba de la 🎲 VARIEDAD de los edits musicales (el usuario: «la IA abusa de los efectos… no quiero el mismo corte,
el mismo filtro, la misma transición una tras otra»). Con una canción de 70 s (un drop largo):
  · nunca 3 planos seguidos con la misma duración (fuera de la ráfaga), y los cortes siguen cayendo en el ritmo;
  · ningún efecto de golpe (destello, temblor, glitch, giro, negativo, RGB) en dos planos seguidos;
  · el velocity solo en algunos planos (y con rampas distintas); el movimiento de cámara cambia (no el mismo seguido);
  · las transiciones se turnan; el color del estilo se matiza según la parte (el blanco y negro sigue siéndolo);
  · los efectos dependen de la canción: una canción suave lleva muchos menos que una con pegada;
  · lo mismo en el motor de Halo.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_variety.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402

from editoria.ai import edit_engine, edit_maker, music_analysis  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402

BPM, SR = 124.0, 44100
BEAT = 60 / BPM
INTRO_END, END = 8.0, 70.0
HIT_FX = ("flash", "shake", "glitch", "roll", "invert", "rgbsplit")


def make_song(path: str, soft: bool = False):
    rng = np.random.default_rng(5)
    t = np.arange(int(END * SR)) / SR
    y = 0.05 * (np.sin(2 * np.pi * 196 * t) + np.sin(2 * np.pi * 247 * t))

    def add(at, sig, gain):
        i = int(at * SR)
        n = min(len(sig), len(y) - i)
        if n > 0:
            y[i:i + n] += gain * sig[:n]
    tt = np.arange(int(0.25 * SR)) / SR
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
    n = int(0.12 * SR)
    snare = (rng.standard_normal(n) * 0.7 + 0.5 * np.sin(2 * np.pi * 200 * np.arange(n) / SR)) * np.exp(-np.arange(n) / SR * 30)
    for b in np.arange(0, INTRO_END, BEAT):
        add(b, np.diff(rng.standard_normal(int(0.03 * SR) + 1)), 0.1)
    for j, b in enumerate(np.arange(INTRO_END, END - 1e-6, BEAT)):
        acc = 1.0 if j % 8 == 0 else (0.75 + 0.25 * rng.random())       # acentos que cambian
        if soft:
            add(b, np.sin(2 * np.pi * 110 * np.arange(int(0.4 * SR)) / SR) * np.exp(-np.arange(int(0.4 * SR)) / SR * 4), 0.25)
            continue
        add(b, kick, 0.9 * acc)
        if j % 2 == 1:
            add(b, snare, 0.7 * acc)
        add(b, 0.3 * np.sin(2 * np.pi * 55 * np.arange(int(BEAT * SR)) / SR), 1.0)
    y = np.clip(y / np.abs(y).max() * 0.9, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def shots_of(plan):
    out: dict[int, dict] = {}
    for c in plan["clips"]:
        s = out.setdefault(c["shot"], {"start": c["start"], "dur": 0.0, "fx": dict(c["fx"]), "kind": c.get("kind"),
                                       "speeds": [], "zoom": c.get("zoom") or [], "trans": c.get("trans"),
                                       "color": c.get("color")})
        s["dur"] += c["duration"]
        s["speeds"].append(c["speed"])
    return [out[k] for k in sorted(out)]


def check_engine(plan, style, beat):
    shots = shots_of(plan)
    drop = plan.get("drop")
    main = [s for s in shots if s["kind"] == "drop" and s["dur"] >= 0.5 * beat]
    runs = 0
    for a, b, c in zip(main, main[1:], main[2:]):
        if max(abs(a["dur"] - b["dur"]), abs(b["dur"] - c["dur"])) <= 0.1 * max(a["dur"], b["dur"], c["dur"]):
            runs += 1
    assert runs == 0, (style, "planos iguales seguidos", [round(s["dur"], 2) for s in main])
    for a, b in zip(shots, shots[1:]):
        if drop is not None and (abs(a["start"] - drop) < 0.03 or abs(b["start"] - drop) < 0.03):
            continue
        same = [k for k in HIT_FX if k in a["fx"] and k in b["fx"]]
        assert not same, (style, "el mismo efecto en dos planos seguidos", same, a["start"], b["start"])
    vel = [s for s in main if 0.35 in s["speeds"]]
    if edit_engine.settings_for(style)["velocity"]:
        assert 0 < len(vel) < 0.8 * len(main), (style, "velocity en algunos, no en todos", len(vel), len(main))
    with_fx = [s for s in main if any(k in s["fx"] for k in HIT_FX)]
    motions = [tuple(round(z[1], 2) for z in s["zoom"]) + tuple(round(z[3], 2) for z in s["zoom"] if len(z) > 3)
               for s in main if s["zoom"] and all(len(z) > 2 and z[2] for z in s["zoom"])]
    rep = sum(1 for a, b in zip(motions, motions[1:]) if a == b)
    assert rep <= max(1, len(motions) // 8), (style, "el mismo movimiento seguido", rep, len(motions))
    tr = [s["trans"]["type"] for s in shots if s["trans"]]
    if len(tr) >= 3:
        assert len(set(tr)) >= 2, (style, "siempre la misma transición", tr)
    return len(with_fx) / max(1, len(main)), len(main)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    song_p, soft_p = os.path.join(out, "cancion.wav"), os.path.join(out, "suave.wav")
    make_song(song_p)
    make_song(soft_p, soft=True)
    clips = []
    for i, src in enumerate(("testsrc2", "mandelbrot", "life=s=320x180:mold=10:r=30:ratio=0.1")):
        p = os.path.join(out, f"clip{i}.mp4")
        lav = f"{src}=s=320x180:r=30" if "=" not in src else src
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", lav, "-t", "45",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p], check=True)
        clips.append(p)
    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})

    def analyzed(path):
        song = edit_maker.analyze_song(path)
        edit_engine.enrich(song, media_tools.decode_mono(path, music_analysis.SR), music_analysis.SR)
        return song
    song, soft = analyzed(song_p), analyzed(soft_p)
    beat = 60 / float(song["tempo"])
    rates = {}
    for style in ("phonk", "hype", "epico_bn", "inspirador", "tenso"):
        plan = edit_engine.plan_v2(song, srcs, style=style, length=None)
        rate, n = check_engine(plan, style, beat)
        rates[style] = rate
        durs = sorted({round(s["dur"], 2) for s in shots_of(plan) if s["kind"] == "drop"})
        print(f"✓ {style}: {n} planos en la parte fuerte, {len(durs)} duraciones distintas, efectos de golpe en el "
              f"{rate:.0%} (nunca el mismo seguido)")
    bn = edit_engine.plan_v2(song, srcs, style="epico_bn", length=None)
    cols = {(c["color"]["contrast"], c["color"]["saturation"]) for c in bn["clips"] if c.get("color")}
    assert all(c["color"]["saturation"] == -1.0 for c in bn["clips"]) and len(cols) >= 2, cols
    print("✓ el color del estilo cambia un poco según la parte (y el blanco y negro sigue siéndolo)")
    soft_plan = edit_engine.plan_v2(soft, srcs, style="phonk", length=None)
    hard_n = sum(1 for s in shots_of(edit_engine.plan_v2(song, srcs, style="phonk", length=None))
                 if any(k in s["fx"] for k in HIT_FX))
    soft_n = sum(1 for s in shots_of(soft_plan) if any(k in s["fx"] for k in HIT_FX))
    assert soft_n < hard_n, (soft_n, hard_n)
    print(f"✓ depende de la canción: con pegada {hard_n} planos con efecto de golpe, suave {soft_n}")
    a = edit_engine.plan_v2(song, srcs, style="phonk", length=None, seed=7)
    b = edit_engine.plan_v2(song, srcs, style="phonk", length=None, seed=8)
    sa = [(round(s["dur"], 2), tuple(sorted(k for k in s["fx"] if k in HIT_FX))) for s in shots_of(a)]
    sb = [(round(s["dur"], 2), tuple(sorted(k for k in s["fx"] if k in HIT_FX))) for s in shots_of(b)]
    assert sa != sb, "otra semilla (🔀 Remix / otro edit) → otro reparto"
    print("✓ cada edit (otra semilla) reparte los cortes y los efectos de otra manera")

    # 🔁 Sin repetir escenas (el usuario: «se repiten demasiado las mismas escenas»): 2 videos de 2 min con un corte
    # de cámara cada 4 s = 60 escenas; 50 planos → ninguna escena dos veces
    from collections import Counter
    STEP = edit_maker.STEP
    n = int(120 / STEP)
    rng_ = np.random.default_rng(3)
    fake = []
    for name in ("cinematicas_a", "cinematicas_b"):
        cut = np.zeros(n)
        cut[::int(4 / STEP)] = 1.0
        prof = {"motion": list(0.3 + 0.7 * rng_.random(n)), "bright": list(np.ones(n)), "cut": list(cut)}
        fake.append({"media_id": name, "kind": "video", "duration": 120.0, "profile": prof})
    pk = edit_maker._Picker(fake, seed=11)
    scenes = []
    for k in range(50):
        r = pk.pick(1.2, 0.3 + 0.2 * (k % 3), "main")
        scenes.append((r["media_id"], int((r["source_in"] + 0.6) // 4)))
    rep = len(scenes) - len(set(scenes))
    assert rep == 0, ("escenas repetidas", rep)
    for k in range(30):                                   # 80 planos y solo 60 escenas: repite lo justo
        r = pk.pick(1.2, 0.5, "main")
        scenes.append((r["media_id"], int((r["source_in"] + 0.6) // 4)))
    most = Counter(scenes).most_common(1)[0][1]
    assert most <= 2, ("una escena salió demasiadas veces", most)
    print(f"✓ 🔁 escenas: 50 planos de 60 escenas sin repetir ninguna; con 80 planos, ninguna más de {most} veces")

    # 🎲 Efectos: ninguno abusado. En cada edit, cada efecto de golpe sale pocas veces y con descanso entre medias
    worst = 0.0
    for style in ("phonk", "hype"):
        sh = shots_of(edit_engine.plan_v2(song, srcs, style=style, length=None))
        for key in HIT_FX:
            idx = [i for i, s in enumerate(sh) if key in s["fx"]]
            gaps = [b_ - a_ for a_, b_ in zip(idx, idx[1:])]
            assert not gaps or min(gaps) >= 3, (style, key, gaps)
            worst = max(worst, len(idx) / max(1, len(sh)))
    assert worst <= 0.25, ("un efecto en demasiados planos", worst)
    print(f"✓ 🎲 efectos: ninguno en dos planos cercanos (mín. 3 de separación) y ninguno en más del "
          f"{worst:.0%} de los planos")

    halo = edit_maker.plan_edit(song, srcs, length=None, intensity="intenso")
    main_ = [c for c in halo["clips"] if c["part"] == "main"]
    durs = [c["duration"] for c in main_]
    runs = sum(1 for x, y, z in zip(durs, durs[1:], durs[2:])
               if max(abs(x - y), abs(y - z)) <= 0.1 * max(x, y, z))
    assert runs == 0, [round(d, 2) for d in durs]
    for x, y in zip(main_, main_[1:]):
        assert not [k for k in ("flash", "shake") if k in x["fx"] and k in y["fx"]], (x, y)
    punches = sum(1 for c in main_ if c["zoom"] and c["zoom"][0][1] > 1.2)
    assert punches < 0.7 * len(main_), (punches, len(main_))
    print(f"✓ Halo: {len(main_)} planos sin rachas iguales, zoom de golpe en {punches} (no en todos), "
          "destellos y temblores sin repetirse seguidos")
    print("TODO OK")


if __name__ == "__main__":
    main()
