"""Prueba manual de transcripción + limpieza: python tests\\try_voice.py [audio] [modelo]"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editoria.ai import transcription, voice_cleanup  # noqa: E402
from editoria.core.media import decode_mono  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "assets",
                                                          "narracion_prueba.wav")
model = sys.argv[2] if len(sys.argv) > 2 else "equilibrado"
samples = decode_mono(path, 16000)
t0 = time.time()
last = [0.0]


def prog(f, text):
    if time.time() - last[0] > 2:
        print(f"  {f:4.0%} {text}")
        last[0] = time.time()


res = transcription.transcribe(samples, model, "es", prog)
dt = time.time() - t0
print(f"transcrito en {dt:.1f}s (audio {len(samples) / 16000:.1f}s), idioma={res['language']}")
for w in res["words"]:
    print(f"  {w[0]:6.2f}-{w[1]:6.2f}  {w[2]:<16} {w[3]:.2f}")
sug = voice_cleanup.analyze(samples, 16000, res["words"], voice_cleanup.CleanupOptions())
print("\nSUGERENCIAS:")
for s in sug:
    print(f"  [{s['kind']:8}] {s['start']:6.2f}-{s['end']:6.2f}  {s['label']}")
    if s.get("alt_start") is not None:
        print(f"             alt {s['alt_start']:.2f}-{s['alt_end']:.2f}")
