"""Prueba de rendimiento con una narración larga (~14 min) simulada."""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import voice_cleanup  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO  # noqa: E402
from editoria.ui.main_window import MainWindow  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
REPS = 30


def timed(label, fn):
    t0 = time.perf_counter()
    r = fn()
    print(f"  {label}: {(time.perf_counter() - t0) * 1000:.0f} ms")
    return r


app = QApplication(sys.argv)
long_wav = os.path.join(os.environ["TEMP"], "narracion_larga.wav")
if not os.path.exists(long_wav):
    lst = os.path.join(os.environ["TEMP"], "lista.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.join(ASSETS, 'narracion_prueba.wav')}'\n" for _ in range(REPS))
    media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
                           "-i", lst, long_wav])
base = json.load(open(os.path.join(ASSETS, "narracion_prueba.transcripcion.json"), encoding="utf-8"))
dur1 = 28.710703
samples = media_tools.decode_mono(long_wav, 16000)
print(f"audio: {len(samples) / 16000 / 60:.1f} min")
words = [[w[0] + k * dur1, w[1] + k * dur1] + w[2:] for k in range(REPS) for w in base["words"]]
segs = [[s[0] + k * dur1, s[1] + k * dur1, s[2] + k * len(base["words"]), s[3] + k * len(base["words"])]
        for k in range(REPS) for s in base["segments"]]
tr = timed("refinar tiempos", lambda: voice_cleanup.refine_transcript(
    samples, 16000, {"words": words, "segments": segs, "model": "x", "language": "es"}))
opts = voice_cleanup.CleanupOptions()
items = timed("analizar", lambda: voice_cleanup.analyze(samples, 16000, tr["words"], opts))
print(f"  → {len(items)} sugerencias, {len(tr['words'])} palabras")

win = MainWindow()
win.resize(1600, 950)
win.show()
ctrl = win.ctrl
(nid,) = ctrl.import_paths([long_wav])
while ctrl.analyzing:
    app.processEvents()
    time.sleep(0.05)
ctrl.add_media([nid], [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO][0].id, 0)
ctrl.set_transcript(nid, tr)
cut = {k: v[1] for k, v in voice_cleanup.KINDS.items()}
timed("guardar sugerencias (+ refresco de paneles)", lambda: (ctrl.set_suggestions(nid, items, opts.kinds(), cut),
                                                               app.processEvents()))
timed("reconstruir lista", win.voice._rebuild_list)
timed("reconstruir texto", win.transcript._rebuild)
timed("calcular marcas timeline", win.timeline._compute_suggestions)
timed("dibujar timeline", lambda: win.timeline.grab())
sil = [s.id for s in ctrl.project.suggestions if s.kind == "silence"]
timed(f"aplicar {len(sil)} silencios", lambda: ctrl.apply_suggestions(sil))
timed("  lista", win.voice._rebuild_list)
timed("  texto", win.transcript._rebuild)
timed("  timeline", win.timeline._compute_suggestions)
if os.environ.get("PROFILE"):
    import cProfile
    import pstats
    cProfile.run("win.voice._rebuild_list(); win.transcript._rebuild()", os.path.join(os.environ["TEMP"], "prof"))
    pstats.Stats(os.path.join(os.environ["TEMP"], "prof")).sort_stats("tottime").print_stats(8)
print(f"  clips en timeline: {len(ctrl.project.clips)}")
timed("deshacer", ctrl.undo_stack.undo)
timed("highlight palabra x100", lambda: [win.transcript._highlight(t * 3.1) for t in range(100)])
ctrl.undo_stack.setClean()
ctrl._media_dirty = False
win.close()
