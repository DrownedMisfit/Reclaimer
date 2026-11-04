"""
Prueba de lo aprendido de los EDITS DE EJEMPLO del usuario (no es una opción: la IA lo conoce como estilos y efectos):
  · la herramienta interna que analiza un edit (aquí uno hecho a mano: imágenes que cambian en los bombos y, entre
    medias, la MISMA imagen con otro color en las cajas) ve que los cortes van a los golpes, los cambios de look y
    los planos quietos;
  · estilo «🎴 Estilizado»: cambios de look en los golpes (solo los suyos: duotono, negativo, glitch…), sin saltar en
    el video, casi todo quieto, casi sin destellos y final largo; sin cortes por debajo del mínimo ni rachas iguales;
  · estilo «📜 Historia / lore»: parpadeo justo antes del plano final;
  · todos los estilos: los cortes van a los golpes fuertes;
  · 🟣 Duotono: al exportar y en el visor, las sombras moradas y las luces verdes.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_reference.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402

from editoria.ai import edit_engine, edit_maker, edit_reference as ER, music_analysis  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from test_edit_variety import BEAT, END, INTRO_END, make_song, shots_of  # noqa: E402


def make_example(path: str, song: str):
    """Imágenes fijas: una nueva cada 2 bombos; en la caja de en medio, la misma imagen con otro color."""
    W, H, F = 192, 108, 24
    rng = np.random.default_rng(1)
    n = int(END * F)
    frames = np.zeros((n, H, W, 3), np.uint8)
    cur, img_id = None, None
    for i in range(n):
        t = i / F
        k = int((t - INTRO_END) // BEAT) if t >= INTRO_END else -1
        new_id = (k // 2) if k >= 0 else -1
        if new_id != img_id:
            img_id = new_id
            cur = np.empty((H, W, 3), np.uint8)
            cur[:] = rng.integers(30, 200, 3)                 # fondo de un color y figuras encima
            for _ in range(14):
                x, y = rng.integers(0, W - 40), rng.integers(0, H - 30)
                cur[y:y + rng.integers(15, 40), x:x + rng.integers(20, 60)] = rng.integers(40, 255, 3)
        look = k >= 0 and k % 2 == 1
        # otro look (tono morado, como en tus ejemplos), la MISMA imagen
        frames[i] = np.clip(cur.astype(np.int16) * 0.45 + np.array([140, 0, 120]), 0, 255).astype(np.uint8)             if look else cur
    p = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(F), "-i", "-", "-i", song, "-shortest", "-c:v", "libx264",
                          "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", path], stdin=subprocess.PIPE)
    p.communicate(frames.tobytes())
    assert p.returncode == 0


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    song_p = os.path.join(out, "cancion.wav")
    make_song(song_p)
    ex = os.path.join(out, "mi ejemplo.mp4")
    make_example(ex, song_p)
    prof = ER.analyze(ex)
    assert prof["accent_sync"] > 0.3 and prof["look_share"] > 0.3 and prof["still_share"] > 0.7, prof
    m = ER.mix([prof])
    print(f"✓ la herramienta ve el ejemplo: cortes a los golpes {prof['accent_sync']:.0%}, cambios de look "
          f"{prof['look_share']:.0%}, planos quietos {prof['still_share']:.0%} · «{ER.describe(m)}»")

    clips = []
    for i, src in enumerate(("testsrc2", "mandelbrot")):
        p = os.path.join(out, f"clip{i}.mp4")
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"{src}=s=320x180:r=30", "-t", "45", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", p], check=True)
        clips.append(p)
    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})
    song = edit_maker.analyze_song(song_p)
    edit_engine.enrich(song, media_tools.decode_mono(song_p, music_analysis.SR), music_analysis.SR)
    from editoria.ai import edit_feedback
    assert edit_feedback.learned("phonk").get("ref") is None, "ya no es una opción escondida"

    est = edit_engine.plan_v2(song, srcs, style="estilizado", length=None)
    allowed = set(edit_engine.STYLES["estilizado"]["taste"]["looks"])
    looks = [c for c in est["clips"] if c.get("look")]
    assert len(looks) >= 3 and {c["look"] for c in looks} <= allowed, [c["look"] for c in looks]
    for c in looks:
        prev = next(o for o in est["clips"] if o["shot"] == c["shot"] and o is not c and
                    abs(o["start"] + o["duration"] - c["start"]) < 1e-3)
        assert abs(prev["source_in"] + prev["duration"] * prev.get("speed", 1.0) - c["source_in"]) < 0.01
    sh = shots_of(est)
    still = np.mean([not s["zoom"] for s in sh if s["kind"] == "drop"])
    flashes = sum(1 for c in est["clips"] if c["fx"].get("flash"))
    assert still > 0.6 and flashes <= 1, (still, flashes)
    total = est["music"]["duration"]
    assert sh[-1]["dur"] >= min(6.0, 0.18 * total) * 0.85, sh[-1]["dur"]
    mn = edit_engine.MIN_SHOT["normal"] * 0.85
    drop = est.get("drop")
    short = [s for s in sh[1:-1] if s["dur"] < mn and not (drop is not None and drop - 4 * BEAT - 0.05 <= s["start"] < drop)]
    assert len(short) <= 2, [(round(s["start"], 2), round(s["dur"], 2)) for s in short]
    main_ = [s for s in sh if s["kind"] == "drop"]
    runs = sum(1 for a, b, c in zip(main_, main_[1:], main_[2:])
               if max(abs(a["dur"] - b["dur"]), abs(b["dur"] - c["dur"])) <= 0.1 * max(a["dur"], b["dur"], c["dur"]))
    assert runs == 0, [round(s["dur"], 2) for s in main_]
    print(f"✓ 🎴 Estilizado: {len(looks)} cambios de look en los golpes ({', '.join(sorted({c['look'] for c in looks}))}), "
          f"{still:.0%} quietos, {flashes} destellos, final de {sh[-1]['dur']:.1f} s")
    his = edit_engine.plan_v2(song, srcs, style="historia", length=None)
    hs = [c for c in his["clips"] if c["fx"].get("flicker")]
    last = his["clips"][-1]["shot"]
    assert hs and all(c["shot"] != last for c in hs), "parpadeo antes del final"
    print("✓ 📜 Historia / lore: parpadeo rápido justo antes del plano final")
    acc = np.array(sorted(set(song["kick_t"]) | set(song["snare_t"])))
    ph = edit_engine.plan_v2(song, srcs, style="phonk", length=None)
    st0 = ph["music"]["source_in"]
    cuts = [s["start"] + st0 for s in shots_of(ph)[1:] if s["kind"] == "drop"]
    near = np.mean([np.min(np.abs(acc - t)) < 0.06 for t in cuts])
    assert near > 0.8, near
    print(f"✓ todos los estilos: {near:.0%} de los cortes en golpes fuertes")

    # 🟣 Duotono
    from editoria.core import effects as FXM
    assert "duotone" in FXM.LOOKS
    ff = media_tools.ffmpeg()
    grad = os.path.join(out, "grad.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=200x60:d=1,format=gray,geq=lum='X*255/W'", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", grad], check=True)
    duo = os.path.join(out, "duo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", grad, "-vf",
                    ",".join(FXM.look_filters({"duotone": 1.0}) + ["format=yuv420p"]), duo], check=True)
    fr = media_tools.frame_rgb(duo, 0.5, 200).astype(int)
    dark, light = fr[30, 8], fr[30, 192]
    assert dark[2] > dark[1] and dark[0] > dark[1] and light[1] > 200 and light[1] > light[0], (dark, light)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.preview import _edit_looks
    px = np.zeros((1, 2), np.uint32)
    px[0, 0], px[0, 1] = 0xFF000000, 0xFFFFFFFF
    o = _edit_looks(px.copy(), 2, 1, {"duotone": 1.0}).view(np.uint8).reshape(1, 2, 4)
    assert tuple(o[0, 0, :3][::-1]) == FXM.DUO_A and tuple(o[0, 1, :3][::-1]) == FXM.DUO_B, o
    print(f"✓ 🟣 Duotono: sombras moradas {tuple(int(v) for v in dark[:3])} y luces verdes {tuple(int(v) for v in light[:3])}, igual en el visor")
    print("TODO OK")


if __name__ == "__main__":
    main()
