"""
Prueba de la Fase 3 (tracking, sugerencias de zoom, comparación, audio, revisión, director).
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_phase3.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import transform  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def make_media(out: str) -> dict[str, str]:
    ff = media_tools.ffmpeg()
    paths = {}

    def run(name, args):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y"] + args + [p])
            assert r.returncode == 0, (name, r.stderr.decode())
        paths[name] = p

    # Objeto con textura moviéndose (para el tracking)
    run("persecucion.mp4", ["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=8", "-f", "lavfi", "-i",
                            "mandelbrot=s=200x200:r=30", "-filter_complex",
                            "[0][1]overlay=x='100+t*120':y='100+t*55':shortest=1", "-c:v", "libx264"])
    return paths


def test_tracking(app, win, paths, out):
    from editoria.ui.tracking_dialog import TrackingDialog
    ctrl = win.ctrl
    (mid,) = ctrl.import_paths([paths["persecucion.mp4"]])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    cid = ctrl.add_media([mid], v1.id, 0.0)[0]
    dlg = TrackingDialog(ctrl, cid, 1.0, win)
    dlg.show()
    # Objeto en t=1 s: esquina (100+120, 100+55) px, 200x200, en un video de 1280x720
    dlg.selector.box = QRectF(220 / 1280, 155 / 720, 200 / 1280, 200 / 720)
    dlg._start()
    while dlg.job is not None:
        pump(app, 0.1)
    pump(app, 0.2)
    c = ctrl.project.clips[cid]
    assert len(c.zoom_kf) >= 2, c.zoom_kf
    assert c.zoom_kf[0]["z"] == 1.0, "entrada suave: empieza sin zoom"
    for t in (2.0, 4.0, 6.0):
        z, x, y = transform.value_at(c.zoom_kf, t)
        ex, ey = (100 + t * 120 + 100) / 1280, (100 + t * 55 + 100) / 720
        assert abs(x - ex) < 0.05 and abs(y - ey) < 0.06, (t, x, ex, y, ey)
        assert z > 1.1
    print(f"✓ tracking: {len(c.zoom_kf)} claves; el zoom sigue al objeto (error < 5 %)")
    win.timeline.set_selection([cid])
    win.engine.seek(4.0)
    pump(app, 0.8)
    win.grab().save(os.path.join(out, "tracking.png"))
    return cid


NARRATION = ("Hola a todos. Hoy hablamos del combate. Ahora fíjense en cómo se mueve el personaje durante "
             "la pelea. La historia es otra cosa. Miren cómo cambia el rostro del protagonista en esta escena, es increíble. "
             "Y para terminar el rendimiento es bueno.")


def fake_words(text: str) -> list:
    words, t = [], 0.3
    for w in text.split():
        words.append([round(t, 2), round(t + 0.3, 2), w, 0.99])
        t += 0.42
    return words


def test_zoom_suggestions(app, win, paths, out):
    from editoria.core import mapping
    from editoria.core.model import TRACK_AUDIO
    ctrl = win.ctrl
    ff = media_tools.ffmpeg()
    voz = os.path.join(out, "voz_zoom.wav")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=180:d=20", voz])
    (nid,) = ctrl.import_paths([voz])
    while ctrl.analyzing:
        pump(app, 0.1)
    a1 = [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([nid], a1.id, 0.0)
    # Más video después del primer clip (la segunda frase cae en el segundo ~10)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    vid = next(m.id for m in ctrl.project.media.values() if m.name == "persecucion.mp4")
    ctrl.add_media([vid], v1.id, 8.0)
    ctrl.set_transcript(nid, {"language": "es", "model": "simulado", "words": fake_words(NARRATION),
                              "segments": []})
    win.voice._refresh_media()
    idx = win.voice.media_combo.findData(nid)
    win.voice.media_combo.setCurrentIndex(idx)
    pump(app, 0.3)
    win.ai_panel.find_zoom_moments()
    zs = [s for s in ctrl.project.suggestions if s.kind == "zoom"]
    assert len(zs) == 2, [s.label for s in zs]
    assert zs[1].data.get("face"), "«el rostro» debe marcar cara"
    # La lista de limpieza de voz no debe mostrar sugerencias de zoom
    assert all(win.voice.tree.topLevelItem(i).text(1).find("Zoom") < 0
               for i in range(win.voice.tree.topLevelItemCount()))
    win.ai_panel.apply_zooms(selected_only=False)
    while win.ai_panel.job is not None:
        pump(app, 0.1)
    pump(app, 0.2)
    zs = [s for s in ctrl.project.suggestions if s.kind == "zoom"]
    assert all(s.status == "applied" for s in zs), [s.status for s in zs]
    c = ctrl.project.clips[zs[1].data["clip_id"]]
    t = mapping.map_time(ctrl.project, nid, zs[1].start)
    src = ctrl.clip_source_time(c.id, t + 1.0)
    z, _x, _y = transform.value_at(c.zoom_kf, src)
    assert z >= 1.5, (z, c.zoom_kf)
    assert transform.value_at(c.zoom_kf, ctrl.clip_source_time(c.id, t + 5))[0] < 1.01, "debe volver al zoom normal"
    print(f"✓ zoom por contexto: {len(zs)} momentos («fíjense…», «Miren cómo cambia el rostro…») aplicados")
    ctrl.undo_stack.undo()
    assert all(s.status == "pending" for s in ctrl.project.suggestions if s.kind == "zoom")
    ctrl.undo_stack.redo()
    return nid


def test_compare(app, win, out):
    import subprocess
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.compare_dialog import CompareDialog
    ctrl = win.ctrl
    ff = media_tools.ffmpeg()
    orig, remake = os.path.join(out, "original.mp4"), os.path.join(out, "remake.mp4")
    if not os.path.exists(orig):
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                               "mandelbrot=s=960x540:r=30,trim=duration=20", "-c:v", "libx264", orig])
        # El "remake": el mismo contenido pero empieza 4 s más tarde y con otro color
        media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", "4", "-i", orig, "-vf",
                               "hue=h=40:s=1.3,eq=brightness=0.05", "-c:v", "libx264", remake])
    ia, ib = ctrl.import_paths([orig, remake])
    while ctrl.analyzing:
        pump(app, 0.1)
    start = ctrl.project.duration() + 1.0
    dlg = CompareDialog(ctrl, start, win)
    dlg.a.setCurrentIndex(dlg.a.findData(ia))
    dlg.b.setCurrentIndex(dlg.b.findData(ib))
    dlg.ta.setValue(10.0)
    dlg._sync()
    while dlg.job is not None:
        pump(app, 0.1)
    print("  sincronización:", dlg.status.text())
    assert abs(dlg.tb.value() - 6.0) <= 1.0, dlg.tb.value()
    dlg._create()
    p = ctrl.project
    texts = [c for c in p.clips.values() if c.text and c.start == start]
    assert sorted(t.text["content"] for t in texts) == ["ORIGINAL", "REMAKE"]
    halves = [c for c in p.clips.values() if c.layout and c.start == start]
    assert len(halves) == 2 and {h.layout["x"] for h in halves} == {0.0, 0.5}
    print(f"✓ comparación: el remake se sincronizó solo en {dlg.tb.value():.1f} s (esperado 6,0) + etiquetas")
    # Exportar y comparar con el visor
    W, H = 960, 540
    ctrl.set_settings(width=W, height=H)
    mp4 = os.path.join(out, "comparacion.mp4")
    args, _total = build_command(p, ExportOptions(path=mp4, width=W, height=H, fps=30, encoder="gpu",
                                                  bitrate_mbps=6), ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    t = start + 2.0
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", mp4, "-frames:v", "1",
                           os.path.join(out, "comparacion_export.png")])
    win.timeline.set_selection([])
    win.engine.seek(t)
    pump(app, 1.0)
    win.preview.canvas.grab().save(os.path.join(out, "comparacion_visor.png"))
    print("✓ comparación exportada")


def _rms_db(path: str, a: float, b: float) -> float:
    import numpy as np
    s = media_tools.decode_mono(path, 16000)
    seg = s[int(a * 16000):int(b * 16000)]
    return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))


def test_audio(app, out):
    import json
    import re
    import subprocess
    from editoria.ai import voice_cleanup
    from editoria.core.audio_fx import speech_intervals
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ff = media_tools.ffmpeg()
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    narr = os.path.join(assets, "narracion_prueba.wav")
    music = os.path.join(out, "musica.wav")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=30",
                           "-af", "volume=0.3", music])
    ctrl = ProjectController()
    nid, mid = ctrl.import_paths([narr, music])
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.05)
    p = ctrl.project
    assert [t.name for t in p.tracks if t.kind == TRACK_AUDIO] == ["A1"], "proyecto nuevo: UNA pista de audio"
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    a2 = p.track(ctrl.ensure_role_track("musica"))
    assert a2.id != a1.id and a2.duck_db == -12.0 and a2.role == "musica", "la música va a su propia pista"
    ctrl.add_media([nid], a1.id, 0.0)
    ctrl.add_media([mid], a2.id, 0.0)
    samples = media_tools.decode_mono(narr, 16000)
    tr = json.load(open(os.path.join(assets, "narracion_prueba.transcripcion.json"), encoding="utf-8"))
    ctrl.set_transcript(nid, voice_cleanup.refine_transcript(samples, 16000, tr))
    speech = speech_intervals(ctrl.project)
    assert speech and speech[0][0] < 1.5, speech
    # (a) Solo música: la voz a volumen 0 (sus tiempos siguen contando para el ducking)
    narr_clip = ctrl.project.clips_on(a1.id)[0]
    ctrl.set_clip_props([narr_clip.id], "silenciar", volume=0.0)
    ctrl.set_settings(loudnorm=False)
    only_music = os.path.join(out, "solo_musica.mp4")
    args, _ = build_command(ctrl.project, ExportOptions(path=only_music, width=320, height=180, fps=15,
                                                        encoder="cpu", bitrate_mbps=1), ff, os.path.join(out, "fa.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    a, b = speech[0]
    during = _rms_db(only_music, a + 0.5, min(b, a + 2.5))
    gap_a = speech[0][1] + 0.9
    gap_b = speech[1][0] - 0.4 if len(speech) > 1 else gap_a + 1
    pause = _rms_db(only_music, gap_a, gap_b)
    print(f"  música mientras hablas: {during:.1f} dB · en la pausa: {pause:.1f} dB")
    assert 9 <= pause - during <= 15, (during, pause)
    print(f"✓ ducking: la música baja {pause - during:.1f} dB cuando hablas")
    # (b) Mezcla completa normalizada para YouTube
    ctrl.set_clip_props([narr_clip.id], "voz", volume=1.0)
    ctrl.set_settings(loudnorm=True)
    full = os.path.join(out, "mezcla.mp4")
    args, _ = build_command(ctrl.project, ExportOptions(path=full, width=320, height=180, fps=15, encoder="cpu",
                                                        bitrate_mbps=1), ff, os.path.join(out, "fb.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    r = media_tools.run_quiet([ff, "-nostdin", "-hide_banner", "-i", full, "-af", "ebur128", "-f", "null", "-"])
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr.decode(errors="replace"))[-1])
    print(f"✓ volumen final: {lufs:.1f} LUFS (objetivo YouTube: -14)")
    assert abs(lufs + 14) <= 1.5, lufs


def test_audit(app, win, out):
    from editoria.ai.audit import run_audit, summary
    from editoria.core.controller import ProjectController
    from editoria.core.model import Marker, new_id
    from editoria.ui.audit_dialog import AuditDialog
    ff = media_tools.ffmpeg()
    clip = os.path.join(out, "plano.mp4")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=15",
                           "-c:v", "libx264", clip])
    ctrl = ProjectController()
    (mid,) = ctrl.import_paths([clip])
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.05)
    m = ctrl.project.media[mid]
    m.ai_type, m.ai_tags, m.ai_analyzed = "Cinemáticas", ["diálogo"], True
    v2, v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO]
    ctrl.insert_ranges([{"media_id": mid, "start": 0, "source_in": 0, "duration": 12}], v1.id, "plano largo")
    ctrl.insert_ranges([{"media_id": mid, "start": 14, "source_in": 0, "duration": 3},
                        {"media_id": mid, "start": 17, "source_in": 5, "duration": 3}], v1.id, "repetidos")
    ctrl.insert_ranges([{"media_id": mid, "start": 2, "source_in": 0, "duration": 3}], v2.id, "oculta")
    ctrl.set_track_props(v2.id, "ocultar", hidden=True)
    ctrl.project.markers.append(Marker(new_id(), 0.0, "COMBATE", "#e5534b", origin="ai", end=12.0, kind="topic"))
    issues, checked = run_audit(ctrl.project, ctrl.missing, ctrl.peaks, ctrl.clip_vecs)
    cats = {i["category"] for i in issues}
    print("  " + summary(issues, checked))
    for i in issues:
        print(f"    {i['severity']:7} {i['category']:11} {i['message']}")
    for expected in ("Imagen", "Ritmo", "Repetición", "Continuidad", "Pistas"):
        assert expected in cats, (expected, cats)
    assert any("Pantalla negra de 2.0" in i["message"] for i in issues)
    dlg = AuditDialog(ctrl, win.engine, win.timeline, win)
    assert dlg.tree.topLevelItemCount() == len(issues)
    print("✓ revisión: encuentra pantalla negra, plano largo, repeticiones, inconsistencia y pista oculta")


def test_director(app, win, out):
    from editoria.ai import clip_analysis
    from editoria.core.controller import ProjectController  # noqa: F401
    from editoria.core.model import ORIGIN_AI, TRACK_AUDIO
    ctrl = win.ctrl
    ctrl.new_project()
    pump(app, 0.3)
    ff = media_tools.ffmpeg()
    voz = os.path.join(out, "voz_director.wav")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=180:d=40", voz])
    files = [voz, os.path.join(out, "persecucion.mp4"), os.path.join(out, "original.mp4"),
             os.path.join(out, "remake.mp4"), os.path.join(out, "plano.mp4")]
    ids = ctrl.import_paths(files)
    while ctrl.analyzing:
        pump(app, 0.1)
    for mid in ids[1:]:
        m = ctrl.project.media[mid]
        ctrl.set_media_ai(mid, clip_analysis.analyze_clip(m.path, m.kind, m.duration))
    nid = ids[0]
    a1 = [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([nid], a1.id, 0.0)
    text = ("Hoy hablamos del combate del juego. Los tiroteos se sienten pesados y el problema es que la "
            "cámara se mueve demasiado durante las peleas. Aun así el combate es lo mejor del juego.")
    ctrl.set_transcript(nid, {"language": "es", "model": "simulado", "words": fake_words(text), "segments": []})
    win.voice._refresh_media()
    win.voice.media_combo.setCurrentIndex(win.voice.media_combo.findData(nid))
    pump(app, 0.3)
    win.engine.seek(0.0)
    win.ai_panel.director_text.setPlainText(
        "En esta parte hablo durante aproximadamente 20 segundos sobre el combate. Usa gameplay de combate, "
        "cambia de clip cada 3-5 segundos y cuando diga 'el problema' haz un pequeño zoom al personaje. "
        "No agregues texto.")
    win.ai_panel.interpret()
    plan = win.ai_panel.plans[0]
    kinds = [s["kind"] for s in plan["steps"]]
    assert kinds == ["broll", "zoom_word", "no_text"], kinds
    assert plan["range"] == (0.0, 20.0), plan["range"]
    n_undo = ctrl.undo_stack.index()
    win.ai_panel.apply_plan()
    while win.ai_panel.job is not None:
        pump(app, 0.1)
    pump(app, 0.3)
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ai_clips = [c for c in p.clips_on(v1.id) if c.origin == ORIGIN_AI]
    assert ai_clips and all(c.start >= -0.01 and c.end <= 20.01 for c in ai_clips), [(c.start, c.end) for c in ai_clips]
    lens = [c.duration for c in ai_clips]
    assert all(l <= 5.6 for l in lens), lens
    assert not any(c.text for c in p.clips.values()), "no debía añadir texto"
    t_problem = next(w[0] for w in fake_words(text) if w[2] == "problema") - 0.42  # «el problema»
    zoomed = [c for c in p.clips_on(v1.id) if c.zoom_kf]
    assert len(zoomed) == 1 and zoomed[0].start <= t_problem < zoomed[0].end, [(c.start, c.end) for c in zoomed]
    z = max(k["z"] for k in zoomed[0].zoom_kf)
    assert 1.2 <= z <= 1.4, (z, zoomed[0].zoom_kf)
    print(f"✓ Modo Director: {len(ai_clips)} clips de 3–5 s en 0–20 s, zoom pequeño ({z:.2f}) en «el problema», sin textos")
    assert ctrl.undo_stack.index() == n_undo + 1, "todo el plan debe ser un solo paso de deshacer"
    ctrl.undo_stack.undo()
    assert not [c for c in ctrl.project.clips_on(v1.id) if c.origin == ORIGIN_AI]
    ctrl.undo_stack.redo()
    # Instrucciones escritas en marcadores
    ctrl.add_marker(25.0, "no modifiques esta parte")
    win.ai_panel.interpret_markers()
    assert win.ai_panel.plans and win.ai_panel.plans[0]["steps"][0]["kind"] == "lock"
    win.ai_panel.apply_plan()
    while win.ai_panel.job is not None:
        pump(app, 0.1)
    narr = [c for c in ctrl.project.clips.values() if c.media_id == nid][0]
    assert narr.locked, "la narración bajo el marcador debe quedar protegida"
    print("✓ instrucciones en marcadores («no modifiques esta parte» → protegido)")
    win.timeline.fit()
    win.right_tabs.setCurrentWidget(win.ai_panel)
    pump(app, 0.4)
    win.grab().save(os.path.join(out, "director.png"))


def test_music_sync(app, win, out):
    from editoria.core.model import TRACK_AUDIO
    ctrl = win.ctrl
    ctrl.new_project()
    pump(app, 0.3)
    ff = media_tools.ffmpeg()
    song = os.path.join(out, "bombo100.wav")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "aevalsrc='0.9*sin(2*PI*60*t)*exp(-30*mod(t-0.25,0.6))+0.1*sin(2*PI*440*t)':s=22050:d=20",
                           song])
    sid, vid = ctrl.import_paths([song, os.path.join(out, "plano.mp4")])
    while ctrl.analyzing:
        pump(app, 0.1)
    music = ctrl.project.track(ctrl.ensure_role_track("musica"))
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([sid], music.id, 0.0)
    ctrl.insert_ranges([{"media_id": vid, "start": 0.0, "source_in": 0.0, "duration": 3.0},
                        {"media_id": vid, "start": 3.0, "source_in": 4.0, "duration": 3.1},
                        {"media_id": vid, "start": 6.1, "source_in": 2.0, "duration": 2.9},
                        {"media_id": vid, "start": 9.0, "source_in": 1.0, "duration": 3.0}], v1.id, "cortes")
    panel = win.ai_panel
    panel.refresh()
    panel.music_track.setCurrentIndex(panel.music_track.findData(music.id))
    panel.track.setCurrentIndex(panel.track.findData(v1.id))
    panel.snap_to_beats()
    while panel.job is not None:
        pump(app, 0.1)
    cuts = [c.end for c in ctrl.project.clips_on(v1.id)][:-1]
    beats = [0.25 + 0.6 * k for k in range(40)]
    off = [min(abs(cut - b) for b in beats) for cut in cuts]
    print(f"  cortes: {[round(c, 2) for c in cuts]} · distancia al golpe: {[round(o * 1000) for o in off]} ms")
    assert all(o < 0.06 for o in off), off
    assert ctrl.beats, "los golpes quedan guardados para dibujarlos"
    print("✓ cortes a ritmo de la música (" + panel.status.text() + ")")


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    paths = make_media(out)
    test_tracking(app, win, paths, out)
    test_zoom_suggestions(app, win, paths, out)
    test_compare(app, win, out)
    test_audio(app, out)
    test_audit(app, win, out)
    test_director(app, win, out)
    test_music_sync(app, win, out)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
