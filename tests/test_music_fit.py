"""
Prueba de «Ajustar la música a la duración» (por compases).
Ejecutar:  PYTHONUTF8=1 .venv\\Scripts\\python.exe tests\\test_music_fit.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import music_fit, rhythm  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402

SR = 22050
BPM = 120.0
SONG_S = 90.0
BEAT = 60.0 / BPM
SEC_BARS = 16


def make_song(path: str) -> None:
    """Canción sintética de 90 s a 120 BPM: bombo en cada golpe, caja en 2 y 4; cambia de sección cada 16 compases."""
    rng = np.random.default_rng(7)
    n = int(SONG_S * SR)
    y = np.zeros(n, dtype=np.float64)
    t_all = np.arange(n) / SR

    def add(t0, sig):
        i0 = int(t0 * SR)
        if i0 >= n:
            return
        k = min(len(sig), n - i0)
        y[i0:i0 + k] += sig[:k]

    tk = np.arange(int(0.30 * SR)) / SR
    kick = 0.9 * np.sin(2 * np.pi * (50 + 70 * np.exp(-tk * 40)) * tk) * np.exp(-tk * 9)
    kick[:60] += 0.6 * rng.standard_normal(60) * np.linspace(1, 0, 60)     # golpe con «chasquido» al empezar
    tsn = np.arange(int(0.15 * SR)) / SR
    snare = 0.35 * rng.standard_normal(len(tsn)) * np.exp(-tsn * 35)
    that = np.arange(int(0.05 * SR)) / SR
    hat = 0.08 * np.diff(rng.standard_normal(len(that) + 1)) * np.exp(-that * 90)
    beats = int(SONG_S / BEAT)
    for b in range(beats):
        t0 = b * BEAT
        bar = b // 4
        sec = bar // SEC_BARS
        add(t0, kick)
        if sec >= 1 and b % 2 == 1:
            add(t0, snare)
        add(t0 + BEAT / 2, hat)                # corcheas en todo el tema
        if sec >= 2 and b % 4 == 0:          # bajo en cada compás de la sección 3
            f = 110.0
            tb = np.arange(int(BEAT * 4 * SR)) / SR
            add(t0, 0.25 * np.sin(2 * np.pi * f * tb) * np.exp(-tb * 1.2))
    y = np.clip(y / max(1e-9, np.max(np.abs(y))) * 0.9, -1, 1)
    pcm = (y * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def make_noise(path: str) -> None:
    rng = np.random.default_rng(3)
    y = 0.3 * rng.standard_normal(int(SONG_S * SR))
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def make_video(path: str, secs: float) -> None:
    ff = media_tools.ffmpeg()
    r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                               f"testsrc=size=160x90:rate=5:duration={secs}", "-an",
                               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path])
    assert r.returncode == 0, r.stderr.decode(errors="replace")


def near_downbeat(t: float, downs: list[float], tol: float = 0.03) -> bool:
    return any(abs(t - d) <= tol for d in downs)


def check_plan(name: str, plan, info, target: float, song: float, expect_ends: bool = True):
    total = sum(d for _, d in plan)
    assert abs(total - target) <= 0.5, (name, total, target)
    downs = info["downbeats"]
    # principio y final de la canción conservados
    assert plan[0][0] == 0.0, (name, plan[0])
    last_end = plan[-1][0] + plan[-1][1]
    assert abs(last_end - song) < 0.05, (name, "el final no es el de la canción", last_end)
    # cortes al inicio de compás (los que empiezan en la canción)
    for k, (src, dur) in enumerate(plan[1:], start=1):
        assert near_downbeat(src, downs), (name, k, "inicio fuera de compás", src)
    # finales de trozo en compás, salvo el trozo que acaba a mitad de compás (el que va justo antes del final)
    for k, (src, dur) in enumerate(plan[:-1]):
        if k == len(plan) - 2:
            continue
        assert near_downbeat(src + dur, downs), (name, k, "final fuera de compás", src + dur)
    print(f"  {name}: {len(plan)} trozos, total {total:.3f} s (pedido {target:g}), "
          f"el último acaba a {last_end:.2f} s de {song:g} s")


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    song_path = os.path.join(out, "cancion.wav")
    noise_path = os.path.join(out, "ruido.wav")
    video_path = os.path.join(out, "video150.mp4")
    make_song(song_path)
    make_noise(noise_path)
    make_video(video_path, 150)

    # 1) El análisis de ritmo reconoce la canción
    info = rhythm.analyze(song_path)
    print(f"ritmo: {info['tempo']} BPM, {len(info['downbeats'])} compases, "
          f"secciones {[s['kind'] for s in info['sections']]}")
    assert abs(info["tempo"] - BPM) < 3, info["tempo"]
    assert len(info["downbeats"]) >= 30, len(info["downbeats"])

    # 2) plan_fit a 60 s y a 150 s: compases, total ±0,5 s, principio y final conservados
    p60 = music_fit.plan_fit(info, SONG_S, 60.0)
    check_plan("60 s", p60, info, 60.0, SONG_S)
    p150 = music_fit.plan_fit(info, SONG_S, 150.0)
    check_plan("150 s", p150, info, 150.0, SONG_S)
    assert sum(d for _, d in p150) > SONG_S, "a 150 s debe repetir secciones"
    assert sum(d for _, d in p60) < SONG_S, "a 60 s debe quitar secciones"

    # 3) sin ritmo (ruido, o sin compases) cae al modo de siempre
    ninfo = rhythm.analyze(noise_path)
    print(f"  ruido: {len(ninfo.get('downbeats') or [])} compases hallados, pulso regular: {music_fit._regular(ninfo)}")
    assert not music_fit._regular(ninfo), "el ruido no debe parecer un pulso"
    for tgt in (60.0, 150.0):
        pl = music_fit.plan_fit(ninfo, SONG_S, tgt)
        assert pl == music_fit._fallback(SONG_S, tgt), (tgt, pl)
        assert abs(sum(d for _, d in pl) - tgt) < 0.01
    print("  ruido: sin pulso → modo de siempre (canción entera / repetir con fundidos)  OK")
    pl = music_fit.plan_fit({}, SONG_S, 150.0)
    assert pl == music_fit._fallback(SONG_S, 150.0)

    # 4) En un proyecto: el clip de música de 90 s en un video de 150 s queda en trozos, en un paso de Ctrl+Z
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    ctrl = win.ctrl
    ids = ctrl.import_paths([song_path, video_path])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.02)
    p = ctrl.project
    mid_song = next(i for i in ids if p.media[i].kind == "audio")
    mid_vid = next(i for i in ids if p.media[i].kind == "video")
    vt = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    at = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([mid_vid], vt.id, 0.0)
    ctrl.add_media([mid_song], at.id, 0.0)
    music_clip = next(c for c in p.clips_on(at.id) if c.media_id == mid_song)
    assert abs(music_clip.duration - SONG_S) < 0.05, music_clip.duration
    before_state = p.timeline_state()
    print(f"  proyecto: duración {p.duration():.2f} s, clip de música {music_clip.duration:.2f} s")

    rinfo = ctrl.rhythm.get(mid_song) or rhythm.analyze(p.media[mid_song].path)
    ctrl._on_rhythm(mid_song, rinfo)
    plan = music_fit.plan_fit(rinfo, p.media[mid_song].duration, p.duration())
    ok = music_fit.apply_to_clip(ctrl, music_clip.id, plan, "Ajustar la música a la duración")
    assert ok, "apply_to_clip no aplicó nada"
    pieces = sorted((c for c in ctrl.project.clips_on(at.id) if c.media_id == mid_song), key=lambda c: c.start)
    total = pieces[-1].end - pieces[0].start
    assert abs(total - p.duration()) <= 0.5, (total, p.duration())
    assert abs(pieces[0].start) < 1e-6
    for a, b in zip(pieces, pieces[1:]):
        assert abs(b.start - a.end) < 0.01, ("hueco o solape entre trozos", a.end, b.start)
        assert (a.fx or {}).get("fade_out", 0) > 0 and (b.fx or {}).get("fade_in", 0) > 0, "sin fundidos en la unión"
    assert (pieces[-1].fx or {}).get("fade_out", 0) > 0, "sin fundido final"
    print(f"  proyecto: {len(pieces)} trozos de música, suman {total:.3f} s, fundidos en las uniones  OK")

    # un solo paso de deshacer vuelve al clip original
    ctrl.undo_stack.undo()
    back = [c for c in ctrl.project.clips_on(at.id) if c.media_id == mid_song]
    assert len(back) == 1 and abs(back[0].duration - SONG_S) < 0.05, [c.duration for c in back]
    assert ctrl.project.timeline_state() == before_state, "Ctrl+Z no devolvió el estado original"
    print("  Ctrl+Z: vuelve al clip original en un solo paso  OK")

    print("TODO OK", flush=True)


if __name__ == "__main__":
    main()
