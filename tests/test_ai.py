"""
Prueba de la Fase 2: análisis de clips, búsqueda por contenido, temas y B-roll.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_ai.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import broll_selection, clip_analysis, embeddings, topic_detection  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import ORIGIN_AI, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.core.subtitles import timeline_words  # noqa: E402

FONT = "C\\:/Windows/Fonts/arialbd.ttf"
REVIEW = """Hola a todos y bienvenidos a un nuevo video. Hoy vamos a hablar de un juego de acción y de si merece la pena jugarlo.
Empecemos por la historia. La trama sigue a un grupo de soldados en una guerra desesperada contra un enemigo misterioso. El problema de la narrativa es que el ritmo es muy irregular y muchos momentos importantes pasan demasiado rápido.
Los personajes tampoco ayudan mucho. El protagonista tiene algunos momentos emotivos, pero sus compañeros son casi caricaturas y casi no muestran emociones.
Ahora hablemos del combate, que es lo mejor del juego. Los tiroteos se sienten pesados y contundentes. Cubrirse detrás de las paredes y flanquear a los enemigos funciona de maravilla.
En cuanto a las cinemáticas, están muy bien trabajadas. La dirección de cámara y los planos le dan un aire de película de acción, y la animación facial es increíble.
Técnicamente el juego va muy bien. Mantiene sesenta fotogramas por segundo casi siempre y no encontré errores graves. Los tiempos de carga son muy cortos.
En conclusión, es un juego muy sólido con una historia irregular. Gracias por ver el video, nos vemos en el próximo."""


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def make_clips(folder: str) -> dict[str, str]:
    ff = media_tools.ffmpeg()
    clips = {
        "menu.mp4": ["-f", "lavfi", "-i",
                     "color=c=0x101830:s=1280x720:d=8,"
                     f"drawtext=fontfile='{FONT}':text='NUEVA PARTIDA':fontsize=60:fontcolor=white:x=120:y=200,"
                     f"drawtext=fontfile='{FONT}':text='CONTINUAR':fontsize=60:fontcolor=gray:x=120:y=300,"
                     f"drawtext=fontfile='{FONT}':text='OPCIONES':fontsize=60:fontcolor=gray:x=120:y=400,"
                     f"drawtext=fontfile='{FONT}':text='SALIR':fontsize=60:fontcolor=gray:x=120:y=500"],
        "escena_cine.mp4": ["-f", "lavfi", "-i", "mandelbrot=s=1280x540:r=30,trim=duration=10",
                            "-vf", "pad=1280:720:0:90:black"],
        "fuego.mp4": ["-f", "lavfi", "-i",
                      "cellauto=s=1280x720:rule=18:r=30,trim=duration=12,colorchannelmixer=rr=1:gg=0.4:bb=0.1"],
        "barras.mp4": ["-f", "lavfi", "-i", "smptehdbars=s=1280x720:d=9"],
        "fondo_azul.png": ["-f", "lavfi", "-i", "gradients=s=1280x720:c0=0x2050ff:c1=0x88ccff:d=1", "-frames:v", "1"],
    }
    paths = {}
    for name, args in clips.items():
        out = os.path.join(folder, name)
        extra = [] if name.endswith(".png") else ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y"] + args + extra + [out])
        assert r.returncode == 0, (name, r.stderr.decode())
        paths[name] = out
    # Narración "muda" de 150 s (la transcripción se simula con el guion)
    narr = os.path.join(folder, "voz.wav")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "sine=f=200:d=150", "-af", "volume=0.2", narr])
    paths["voz.wav"] = narr
    return paths


def fake_transcript() -> dict:
    words, t = [], 0.0
    for w in REVIEW.split():
        d = 0.08 * len(w) + 0.12
        words.append([round(t, 2), round(t + d, 2), w, 0.99])
        t += d + (0.6 if w.endswith(".") else 0.05)
    return {"language": "es", "model": "simulado", "words": words, "segments": [[0, t, 0, len(words)]]}


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
    ctrl = win.ctrl
    paths = make_clips(out)
    ids = dict(zip(paths, ctrl.import_paths(list(paths.values()))))
    while ctrl.analyzing:
        pump(app, 0.1)

    # 1) Análisis de clips (como lo haría el gestor en segundo plano)
    t0 = time.time()
    for name, mid in ids.items():
        m = ctrl.project.media[mid]
        if m.kind == "audio":
            continue
        res = clip_analysis.analyze_clip(m.path, m.kind, m.duration)
        ctrl.set_media_ai(mid, res)
        print(f"  {name:16} → {res['type']:18} {res['tags']}  (confianza {res['type_conf']:.2f})")
    print(f"✓ análisis de clips en {time.time() - t0:.1f} s")
    media = ctrl.project.media
    assert media[ids["escena_cine.mp4"]].ai_type == "Cinemáticas", media[ids["escena_cine.mp4"]].ai_type
    assert media[ids["menu.mp4"]].ai_type == "Menús", media[ids["menu.mp4"]].ai_type
    assert media[ids["escena_cine.mp4"]].category == "Cinemáticas"  # categoría automática
    # Caché: segunda vez instantáneo
    t0 = time.time()
    clip_analysis.analyze_clip(media[ids["fuego.mp4"]].path, "video", media[ids["fuego.mp4"]].duration)
    assert time.time() - t0 < 1.0
    print("✓ tipos correctos (cinemática por bandas negras, menú) y caché")

    # 2) Búsqueda por contenido (en español)
    p = ctrl.project
    metas = {mid: clip_analysis.metadata_text(p.media[mid].name, p.media[mid].category, p.media[mid].ai_type,
                                              p.media[mid].ai_tags, p.media[mid].tags) for mid in ctrl.clip_vecs}
    q = "el menú principal del juego con opciones"
    vec = embeddings.get("clip_text").encode([q])[0]
    res = clip_analysis.search(vec, ctrl.clip_vecs, meta=clip_analysis.metadata_scores(q, metas))
    assert res[0][0] == ids["menu.mp4"], [(ctrl.project.media[r[0]].name, round(r[1], 3)) for r in res]
    q = "fuego y llamas naranjas"
    vec = embeddings.get("clip_text").encode([q])[0]
    res = clip_analysis.search(vec, ctrl.clip_vecs, meta=clip_analysis.metadata_scores(q, metas))
    print("  «fuego y llamas naranjas» →", [ctrl.project.media[r[0]].name for r in res[:3]])
    print("✓ búsqueda por contenido")

    # Búsqueda desde la interfaz
    win.library.btn_ai_search.setChecked(True)
    win.library.search.setText("pantalla de menú con opciones")
    win.library.semantic_search("pantalla de menú con opciones")
    while win.library._search_job is not None:
        pump(app, 0.1)
    assert win.library._results and win.library._results[0][0] == ids["menu.mp4"]
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "1_busqueda.png"))

    # 3) Temas
    p = ctrl.project
    nid = ids["voz.wav"]
    ctrl.add_media([nid], [t for t in p.tracks if t.kind == TRACK_AUDIO][0].id, 0.0)
    ctrl.set_transcript(nid, fake_transcript())
    segs = topic_detection.detect_topics(ctrl.project.transcripts[nid]["words"])
    n = ctrl.set_topics(nid, segs)
    labels = [m.label for m in sorted(ctrl.project.markers, key=lambda m: m.time) if m.kind == "topic"]
    print("  temas:", labels)
    assert labels[0] == "INTRODUCCIÓN" and labels[-1] == "CONCLUSIÓN" and "COMBATE" in labels, labels
    assert n == len(labels) >= 5
    topics = sorted((m for m in ctrl.project.markers if m.kind == "topic"), key=lambda m: m.time)
    for a, b in zip(topics, topics[1:]):
        assert abs(a.end - b.time) < 1e-6, "los temas deben ser contiguos"
    # Mover el borde de un tema
    t_old = topics[2].time
    ctrl.move_topic_start(topics[2].id, t_old + 2.0)
    tp = sorted((m for m in ctrl.project.markers if m.kind == "topic"), key=lambda m: m.time)
    assert abs(tp[2].time - (t_old + 2)) < 1e-6 and abs(tp[1].end - (t_old + 2)) < 1e-6
    ctrl.undo_stack.undo()
    print(f"✓ {n} temas como bandas en la timeline (y se pueden ajustar)")

    # 4) B-roll
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    # Un clip puesto "a mano" que la IA no debe tapar
    ctrl.insert_ranges([{"media_id": ids["barras.mp4"], "start": 20.0, "source_in": 0, "duration": 6.0}],
                       v1.id, "Clip manual")
    st = broll_selection.BrollSettings()
    words = timeline_words(ctrl.project, nid)
    tps = [(m.time, m.end, m.label) for m in ctrl.project.markers if m.kind == "topic"]
    slots = broll_selection.make_slots(words, st, tps)
    lens = [s["end"] - s["start"] for s in slots]
    print(f"  {len(slots)} huecos, duración {min(lens):.1f}–{max(lens):.1f} s")
    assert min(lens) >= st.min_len * 0.6 and max(lens) <= st.max_len + 3
    win.right_tabs.setCurrentWidget(win.ai_panel)
    win.ai_panel.propose()
    while win.ai_panel.job is not None:
        pump(app, 0.1)
    pump(app, 0.3)
    assert win.ai_panel.slots and all(s.get("candidates") for s in win.ai_panel.slots)
    used = {}
    for s in win.ai_panel.slots:
        used[s["candidates"][0]["media_id"]] = used.get(s["candidates"][0]["media_id"], 0) + 1
    print("  reparto del mejor candidato:", {ctrl.project.media[k].name: v for k, v in used.items()})
    assert len(used) >= 3, "no debe usar siempre el mismo clip"
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "2_propuesta.png"))

    # Automático: solo huecos libres
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    win.ai_panel.auto_fill()
    pump(app, 0.3)
    v1_clips = ctrl.project.clips_on(v1.id)
    manual = [c for c in v1_clips if c.origin != ORIGIN_AI]
    assert len(manual) == 1 and manual[0].start == 20.0 and abs(manual[0].duration - 6.0) < 1e-6
    ai = [c for c in v1_clips if c.origin == ORIGIN_AI]
    assert ai and all(not (c.start < 26.0 and c.end > 20.0) for c in ai), "la IA tapó el clip manual"
    for a, b in zip(v1_clips, v1_clips[1:]):
        assert a.end <= b.start + 1e-6
    print(f"✓ B-roll automático: {len(ai)} clips de IA, el clip manual intacto")
    ctrl.undo_stack.undo()
    assert not [c for c in ctrl.project.clips_on(v1.id) if c.origin == ORIGIN_AI]
    ctrl.undo_stack.redo()
    print("✓ deshacer/rehacer el B-roll")

    # Guardar / abrir mantiene análisis y temas
    path = os.path.join(out, "fase2.eia")
    ctrl.save(path)
    from editoria.core.controller import ProjectController
    c2 = ProjectController()
    c2.load(path)
    assert len(c2.clip_vecs) == len(ctrl.clip_vecs), (len(c2.clip_vecs), len(ctrl.clip_vecs))
    assert c2.project.media[ids["menu.mp4"]].ai_type == "Menús"
    assert [m.label for m in c2.project.markers if m.kind == "topic"] == labels
    print("✓ guardar/abrir conserva análisis y temas")

    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "3_broll.png"))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
