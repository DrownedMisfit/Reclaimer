"""
Prueba del flujo de voz: transcribir, analizar, aplicar/restaurar cortes, subtítulos y exportar.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_voice.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from editoria.ai import transcription, voice_cleanup  # noqa: E402
from editoria.core import mapping, subtitles  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import SUG_APPLIED, SUG_PENDING, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NARRATION = os.path.join(ASSETS, "narracion_prueba.wav")
CACHE = os.path.join(ASSETS, "narracion_prueba.transcripcion.json")


def wait(app, ctrl):
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)


def main():
    app = QCoreApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="editoria_voz_")
    gameplay = os.path.join(tmp, "gameplay.mp4")
    media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                           "testsrc2=s=640x360:r=30:d=40", "-c:v", "libx264", gameplay])

    ctrl = ProjectController()
    msgs = []
    ctrl.message.connect(msgs.append)
    nid, gid = ctrl.import_paths([NARRATION, gameplay])
    wait(app, ctrl)
    p = ctrl.project
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([nid], a1.id, 0.0)
    ctrl.add_media([gid], v1.id, 0.0)
    ctrl.trim_clip(p.clips_on(v1.id)[0].id, "right", p.media[nid].duration)   # el video, tan largo como la voz
    total0 = p.duration()

    # 1) Transcribir (se guarda en caché para que la prueba sea rápida)
    samples = media_tools.decode_mono(NARRATION, 16000)
    if os.path.exists(CACHE):
        tr = json.load(open(CACHE, encoding="utf-8"))
    else:
        tr = transcription.transcribe(samples, "equilibrado", "es")
        json.dump(tr, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    y0 = next(w for w in tr["words"] if w[2] == "Y")[0]
    tr = voice_cleanup.refine_transcript(samples, 16000, tr)
    y = next(w for w in tr["words"] if w[2] == "Y")
    assert y[0] >= y0 - 0.01, (y, y0)  # afinar los tiempos nunca adelanta una palabra a antes de su sonido
    ctrl.set_transcript(nid, tr)
    assert len(tr["words"]) > 40
    print(f"✓ transcripción: {len(tr['words'])} palabras")

    # 2) Analizar
    opts = voice_cleanup.CleanupOptions()
    items = voice_cleanup.analyze(samples, 16000, tr["words"], opts)
    cuttable = {k: v[1] for k, v in voice_cleanup.KINDS.items()}
    ctrl.set_suggestions(nid, items, opts.kinds(), cuttable)
    kinds = [s.kind for s in p.suggestions]
    for k in ("silence", "filler", "repeat", "retake"):
        assert k in kinds, (k, kinds)
    print(f"✓ análisis: {len(p.suggestions)} sugerencias ({', '.join(sorted(set(kinds)))})")

    # 3) Aplicar todos los silencios
    sil = [s for s in p.suggestions if s.kind == "silence"]
    removed = sum(s.end - s.start for s in sil)
    ctrl.apply_suggestions([s.id for s in sil])
    p = ctrl.project
    assert all(s.status == SUG_APPLIED for s in p.suggestions if s.kind == "silence")
    assert abs(p.duration() - (total0 - removed)) < 0.02, (p.duration(), total0, removed)
    # El video de V1 también se acortó (cortes en todas las pistas) y sigue alineado con la voz
    v_end = max(c.end for c in p.clips_on(v1.id))
    a_end = max(c.end for c in p.clips_on(a1.id))
    assert abs(v_end - a_end) < 0.02, (v_end, a_end)
    # Ninguna palabra quedó cortada por quitar silencios
    lost = [w for w in tr["words"] if mapping.map_time(p, nid, (w[0] + w[1]) / 2) is None]
    assert not lost, lost
    print(f"✓ silencios aplicados: -{removed:.2f} s, voz y video siguen sincronizados")

    # 4) Restaurar UN corte concreto (el segundo)
    target = sorted((s for s in p.suggestions if s.kind == "silence"), key=lambda s: s.start)[1]
    d = target.applied_end - target.applied_start
    n_clips = len(p.clips)
    ctrl.restore_suggestions([target.id])
    p = ctrl.project
    t2 = next(s for s in p.suggestions if s.id == target.id)
    assert t2.status == SUG_PENDING
    assert abs(p.duration() - (total0 - removed + d)) < 0.02
    assert len(p.clips) == n_clips - 2, (len(p.clips), n_clips)  # se vuelven a unir (audio y video)
    print("✓ restaurar un solo corte")

    # 5) Deshacer / rehacer
    ctrl.undo_stack.undo()
    assert abs(ctrl.project.duration() - (total0 - removed)) < 0.02
    ctrl.undo_stack.redo()
    p = ctrl.project
    print("✓ deshacer / rehacer")

    # 6) Toma repetida: quedarse con la toma 2 (quitar la 1)
    retake = next(s for s in p.suggestions if s.kind == "retake")
    ctrl.apply_suggestions([retake.id])
    p = ctrl.project
    texts = [w[2] for w in subtitles.timeline_words(p, nid)]
    assert "bastante" not in texts and "demasiado" in texts, texts
    # Muletillas y palabra repetida
    ids = [s.id for s in p.suggestions if s.kind in ("filler", "repeat") and s.status == SUG_PENDING]
    ctrl.apply_suggestions(ids)
    p = ctrl.project
    texts = [w[2] for w in subtitles.timeline_words(p, nid)]
    assert "Eh," not in texts and "este," not in texts, texts
    print("✓ toma repetida, muletillas y repetición aplicadas →", " ".join(texts))

    # 7) Bloqueo: con la pista de video bloqueada no se puede cerrar huecos
    ctrl.set_track_props(v1.id, "Bloquear", locked=True)
    pend = [s.id for s in p.suggestions if s.status == SUG_PENDING and s.cuttable]
    if pend:
        before = ctrl.project.duration()
        assert ctrl.apply_suggestions(pend) is None
        assert ctrl.project.duration() == before and "bloqueado" in msgs[-1]
    ctrl.set_track_props(v1.id, "Desbloquear", locked=False)
    print("✓ los cortes respetan los bloqueos")

    # 8) Subtítulos .srt
    cues = subtitles.build_cues(ctrl.project, nid)
    srt = subtitles.to_srt(cues)
    assert cues and all(c.end > c.start for c in cues)
    assert all(cues[i].end <= cues[i + 1].start for i in range(len(cues) - 1))
    open(os.path.join(tmp, "subtitulos.srt"), "w", encoding="utf-8").write(srt)
    print(f"✓ subtítulos: {len(cues)} bloques")
    print(srt[:400])

    # 9) Guardar/abrir conserva transcripción y sugerencias
    path = os.path.join(tmp, "voz.eia")
    ctrl.save(path)
    c2 = ProjectController()
    c2.load(path)
    assert c2.project.transcripts[nid]["words"] == tr["words"]
    assert len(c2.project.suggestions) == len(ctrl.project.suggestions)
    wait(app, c2)
    print("✓ guardar / abrir con transcripción y sugerencias")

    # 10) Exportar el resultado
    out = os.path.join(tmp, "limpio.mp4")
    args, total = build_command(ctrl.project, ExportOptions(path=out, width=640, height=360, fps=30,
                                                            encoder="gpu", bitrate_mbps=4),
                                media_tools.ffmpeg(), os.path.join(tmp, "f.txt"))
    r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]
    info = media_tools.probe(out)
    assert abs(info["duration"] - total) < 0.25
    print(f"✓ exportado: {total0:.1f} s → {total:.1f} s  ({out})")
    print("\nTODO OK")


if __name__ == "__main__":
    main()
