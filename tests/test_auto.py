"""
Prueba de la «Primera versión automática»: de la narración a un video casi terminado.
Ejecutar:  .venv/Scripts/python.exe tests/test_auto.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import ORIGIN_AI, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402
from test_ai import REVIEW, make_clips  # noqa: E402
from test_edit import make_song  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def make_narration(path: str) -> dict:
    """La reseña de test_ai «leída»: un tono con forma de voz en cada palabra y silencio entre
    palabras, con pausas largas entre párrafos (para que haya silencios que limpiar)."""
    sr = 16000
    words, t = [], 0.3
    for para in REVIEW.splitlines():
        for w in para.split():
            d = 0.07 * len(w) + 0.12
            words.append([round(t, 2), round(t + d, 2), w, 0.99])
            t += d + (0.35 if w.endswith(".") else 0.06)
        t += 1.8   # pausa larga al cambiar de párrafo
    y = np.zeros(int((t + 0.5) * sr), np.float32)
    rng = np.random.default_rng(1)
    for a, b, _w, _c in words:
        i, j = int(a * sr), int(b * sr)
        tt = np.arange(j - i) / sr
        env = np.sin(np.pi * np.linspace(0, 1, j - i)) ** 0.5
        f0 = 120 + 30 * rng.random()
        y[i:j] = 0.3 * env * (np.sin(2 * np.pi * f0 * tt) + 0.5 * np.sin(4 * np.pi * f0 * tt)
                              + 0.25 * np.sin(6 * np.pi * f0 * tt))
    y += 0.002 * rng.standard_normal(len(y)).astype(np.float32)
    import wave
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return {"language": "es", "model": "simulado", "words": words, "segments": [[0, t, 0, len(words)]]}


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.auto_dialog import STEPS, AutoDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl

    clips = make_clips(out)
    clips.pop("voz.wav")
    # Sin repetir ningún trozo, 130 s de voz necesitan bastante más material distinto (cada clip deja un resto que
    # ya no cabe un plano). Los 5 clips de arriba suman ~40 s, así que se añaden 4 clips de 40 s para que el B-roll
    # cubra la voz como antes.
    ff = media_tools.ffmpeg()
    for k, rule in enumerate((30, 90, 150, 210)):
        extra = os.path.join(out, f"material_extra_{k}.mp4")
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                               f"cellauto=s=640x360:rule={rule}:r=24,trim=duration=40,"
                               "colorchannelmixer=rr=1:gg=0.5:bb=0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", extra])
        clips[f"material_extra_{k}.mp4"] = extra
    narr = os.path.join(out, "mi_narracion.wav")
    transcript = make_narration(narr)
    song = os.path.join(out, "musica.wav")
    make_song(song)
    ids = ctrl.import_paths([narr, song] + list(clips.values()))
    while ctrl.analyzing:
        pump(app, 0.1)
    p = ctrl.project
    narr_id = next(m.id for m in p.media.values() if m.name == "mi_narracion.wav")
    song_id = next(m.id for m in p.media.values() if m.name == "musica.wav")
    ctrl.set_transcript(narr_id, transcript)   # (la transcripción real ya se probó en test_voice)
    narr_len = p.media[narr_id].duration
    n_undo = ctrl.undo_stack.count()

    dlg = AutoDialog(win)
    dlg.show()
    dlg.narr.setCurrentIndex(dlg.narr.findData(narr_id))
    dlg.music.setCurrentIndex(dlg.music.findData(song_id))
    assert dlg.narr.currentData() == narr_id
    dlg.etype.setCurrentIndex(dlg.etype.findData("ensayo"))       # → pausado · mezclar · cinematográfico
    assert dlg.style.currentData() == "cinematic" and dlg.pace.currentData() == "slow"
    for cb in dlg.cut_opts.values():
        cb.setChecked(True)
    t0 = time.time()
    dlg.start()
    while dlg.running and time.time() - t0 < 900:
        pump(app, 0.2)
    assert not dlg.running, "no terminó"
    texts = [dlg.steps.item(i).text() for i in range(dlg.steps.count())]
    for t in texts:
        print("  " + t)
    assert not any(t.startswith("✗") for t in texts), "algún paso falló"
    print(f"✓ {len(STEPS)} pasos en {time.time() - t0:.0f} s")
    print("  " + dlg.status.text().replace("\n", "\n  "))
    dlg.grab().save(os.path.join(out, "auto_dialog.png"))

    # --- Resultado
    p = ctrl.project
    narr_clips = [c for c in p.clips.values() if c.media_id == narr_id]
    total_narr = sum(c.duration for c in narr_clips)
    assert total_narr < narr_len - 1.0, (total_narr, narr_len)
    print(f"✓ voz limpia: {narr_len:.1f} s → {total_narr:.1f} s")
    assert all(c.eq and c.eq["bands"][2]["g"] == 4.2 for c in narr_clips), "EQ «Mi voz»"
    topics = [m for m in p.markers if m.kind == "topic"]
    assert topics, "temas"
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    broll = p.clips_on(v1.id)
    assert len(broll) >= 4 and all(c.origin == ORIGIN_AI for c in broll)
    assert broll[0].start < 0.01, "el B-roll empieza en 0 (sin negro al principio)"
    end_voice = max(c.end for c in narr_clips)
    covered = sum(c.duration for c in broll)
    assert covered > 0.9 * end_voice, (covered, end_voice)
    for a, b in zip(broll, broll[1:]):
        assert b.start - a.end < 0.05, f"hueco negro entre {a.end:.2f} y {b.start:.2f}"
    kb = [c for c in broll if c.zoom_kf]
    assert kb, "zoom lento / zooms"
    assert (broll[0].fx or {}).get("fade_in") and (broll[-1].fx or {}).get("fade_out")
    music = [c for t in p.tracks if t.kind == TRACK_AUDIO and t.role == "musica" for c in p.clips_on(t.id)]
    assert music and abs(music[0].volume - 0.35) < 1e-6 and (music[0].fx or {}).get("fade_in")
    assert music[-1].end >= end_voice - 0.6
    fx = [c for t in p.tracks if t.kind == TRACK_AUDIO and t.role == "efectos" for c in p.clips_on(t.id)]
    assert len(fx) >= 3, "whoosh en los cambios de tema (estilo cinematográfico)"
    snap = next(r for r in dlg.report if "ritmo de la música" in r)
    assert not snap.startswith("🥁 0 "), snap
    lens = sorted(c.duration for c in broll)
    assert lens[len(lens) // 2] > 4.0, f"ritmo pausado: planos largos ({lens[len(lens) // 2]:.1f} s)"
    print(f"✓ estilo cinematográfico: {len(fx)} whooshes en transiciones, cortes a ritmo de la música, "
          f"planos de ~{lens[len(lens) // 2]:.1f} s (ritmo pausado)")
    print(f"✓ timeline: {len(broll)} planos de B-roll sin huecos, {len(kb)} con zoom, {len(topics)} temas, "
          f"música bajo la voz ({len(music)} tramo/s)")

    # Un solo Ctrl+Z deshace todo
    assert ctrl.undo_stack.count() == n_undo + 1, (ctrl.undo_stack.count(), n_undo)
    n_clips = len(p.clips)
    ctrl.undo_stack.undo()
    assert len(ctrl.project.clips) == 0 and not [m for m in ctrl.project.markers if m.kind == "topic"]
    ctrl.undo_stack.redo()
    assert len(ctrl.project.clips) == n_clips
    print("✓ un solo Ctrl+Z deshace la primera versión entera (y Ctrl+Y la recupera)")

    # IA solo sobre una parte: rehacer el B-roll de un tramo sin tocar el resto
    broll = p.clips_on(v1.id)
    a, b = broll[3].start, broll[6].end
    outside = {c.id: (c.start, c.media_id, c.source_in) for c in broll if c.end <= a + 1e-6 or c.start >= b - 1e-6}
    win.ai_panel.propose((a, b), apply=True)
    t0 = time.time()
    while win.ai_panel.job is not None and time.time() - t0 < 120:
        pump(app, 0.1)
    pump(app, 0.3)
    now = {c.id: (c.start, c.media_id, c.source_in) for c in p.clips_on(v1.id)}
    assert all(now.get(cid) == v for cid, v in outside.items()), "fuera del tramo no cambia nada"
    inside = [c for c in p.clips_on(v1.id) if c.start >= a - 1e-6 and c.end <= b + 1e-6]
    assert inside and not {c.id for c in inside} & set(outside)
    print(f"✓ «Rehacer el B-roll de esta parte»: {len(inside)} planos nuevos en {a:.1f}–{b:.1f} s; el resto intacto")
    ctrl.undo_stack.undo()
    assert {c.id: (c.start, c.media_id, c.source_in) for c in p.clips_on(v1.id)} != now
    # Más impacto visual en unos clips concretos
    sel = [c.id for c in p.clips_on(v1.id)[:4]]
    ctrl.batch_clip_props({cid: {"zoom_kf": []} for cid in sel}, "prueba")
    win.add_impact(sel)
    assert all(p.clips[cid].zoom_kf for cid in sel)
    print("✓ «Dar más impacto visual»: zooms en los clips elegidos")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()

    win.timeline.fit()
    win.engine.seek(3.0)
    pump(app, 0.8)
    win.grab().save(os.path.join(out, "auto_ui.png"))

    # Exportar (pequeño) y comprobar que hay imagen y sonido
    ff = media_tools.ffmpeg()
    mp4 = os.path.join(out, "primera_version.mp4")
    args, total = build_command(p, ExportOptions(path=mp4, width=640, height=360, fps=30, encoder="gpu",
                                                 bitrate_mbps=3), ff, os.path.join(out, "f.txt"))
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]
    r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-ss", "4", "-i", mp4, "-frames:v", "1",
                               "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    luma = np.frombuffer(r.stdout, np.uint8).mean()
    assert luma > 10, luma
    print(f"✓ exportado {total:.1f} s en {time.time() - t0:.1f} s (imagen a los 4 s: brillo {luma:.0f})")
    for k, tt in enumerate((0.3, 4.0, total / 2, total - 0.4)):
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", f"{tt:.2f}", "-i", mp4, "-frames:v", "1",
                               "-vf", "scale=320:-2", os.path.join(out, f"f{k}.png")])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y"] + sum([["-i", os.path.join(out, f"f{k}.png")]
                          for k in range(4)], []) + ["-filter_complex", "hstack=4", os.path.join(out, "frames.png")])
    dlg.close()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
