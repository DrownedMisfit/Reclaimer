"""
Prueba de «✂ Shorts desde este video» (sin ventanas):
  · con una narración de más de 4 minutos (la de prueba repetida y con sus palabras desplazadas):
    los tramos duran 45–75 s, no se solapan y no cortan ninguna palabra;
  · crear un Short genera un .eia en formato Short, con duración ≈ la del tramo y clips dentro de [0, dur];
  · el proyecto largo no cambia;
  · sin transcripción, también propone tramos (por volumen y silencios).
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_short_picker.py _pruebas_tmp/test_short_picker .
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(ROOT, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from editoria.ai import short_picker as SP  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import KIND_AUDIO, TRACK_AUDIO, Clip, Marker, MediaItem, Project, new_id  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def build_long_narration(src_wav, out_wav, repeats=8):
    """La narración de prueba repetida (≈4 min 20 s): un solo archivo de audio."""
    ff = media_tools.ffmpeg()
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-stream_loop", str(repeats - 1), "-i", src_wav,
                        "-c", "copy", out_wav], capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(out_wav):
        print("FALLO: ffmpeg no pudo repetir la narración:", r.stderr[-300:])
        sys.exit(1)


def build_project(long_wav, words, total, topics=True):
    p = Project.new()
    mid = new_id()
    p.media[mid] = MediaItem(id=mid, path=long_wav, kind=KIND_AUDIO, name="narracion larga", duration=total,
                             has_audio=True, probed=True, channels=1)
    audio = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    c = Clip(id=new_id(), media_id=mid, track_id=audio.id, start=0.0, source_in=0.0, duration=total)
    p.clips[c.id] = c
    p.transcripts[mid] = {"language": "es", "model": "prueba", "words": words}
    if topics:
        p.markers.append(Marker(id=new_id(), time=40.0, end=150.0, label="COMBATE", kind="topic"))
    p.name = "Reseña de prueba"
    return p, mid


def main():
    out_dir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_short_picker")
    os.makedirs(out_dir, exist_ok=True)
    for viejo in os.listdir(out_dir):          # cada prueba empieza con la carpeta vacía
        if viejo.endswith(".eia"):
            os.remove(os.path.join(out_dir, viejo))
    src =os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    src_json = os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json")
    base = wav_seconds(src)
    with open(src_json, encoding="utf-8") as f:
        base_words = json.load(f)["words"]

    long_wav = os.path.join(out_dir, "narracion_larga.wav")
    build_long_narration(src, long_wav, repeats=8)
    total = wav_seconds(long_wav)
    check(total >= 240, f"narración de prueba de {total:.0f} s (≥ 4 min)")
    words = []
    for k in range(8):
        for s, e, txt, conf in base_words:
            words.append([round(s + k * base, 3), round(e + k * base, 3), txt, conf])
    p, mid = build_project(long_wav, words, total)

    # 1) tramos
    picks = SP.pick_shorts(p, n=5, min_s=45, max_s=75)
    check(len(picks) >= 3, f"{len(picks)} propuestas")
    for pk in picks:
        d = pk["end"] - pk["start"]
        check(45 - 0.01 <= d <= 75 + 0.01, f"tramo de {d:.1f} s («{pk['title']}»)")
    ordenados = sorted(picks, key=lambda x: x["start"])
    for a, b in zip(ordenados, ordenados[1:]):
        check(b["start"] >= a["end"], f"sin solaparse: {a['end']:.2f} ≤ {b['start']:.2f}")
    scores = [pk["score"] for pk in picks]
    check(scores == sorted(scores, reverse=True), "ordenadas por puntuación")
    cortes = [(pk["start"], pk["end"]) for pk in picks for s, e, _t, _c in words
              if s + 0.03 < pk["start"] < e - 0.03 or s + 0.03 < pk["end"] < e - 0.03]
    check(not cortes, f"ningún tramo corta una palabra ({len(words)} palabras revisadas)")
    check(all(pk["title"] and pk["why"] for pk in picks), "todas tienen título y motivo")
    print("  motivos:", " | ".join(pk["why"] for pk in picks[:3]))

    # 2) el proyecto largo no cambia al crear
    antes = json.dumps(p.to_dict(), sort_keys=True, default=str)
    pk = picks[0]
    path = SP.write_short(p, pk, 1, out_dir)
    check(json.dumps(p.to_dict(), sort_keys=True, default=str) == antes, "el proyecto largo no cambia")
    check(p.format == "youtube", "el largo sigue en formato YouTube")
    check(os.path.exists(path) and path.endswith(".eia"), f"Short creado: {os.path.basename(path)}")

    # 3) el .eia del Short
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    check(d.get("project_type") == "short", "formato Short (project_type = short)")
    check((d["width"], d["height"]) == (1080, 1920), "resolución vertical 1080×1920")
    dur_short = max(c["start"] + c["duration"] for c in d["clips"])
    check(abs(dur_short - (pk["end"] - pk["start"])) < 0.05, f"duración {dur_short:.2f} s ≈ tramo")
    check(all(c["start"] >= -1e-6 and c["start"] + c["duration"] <= dur_short + 1e-3 for c in d["clips"]),
          "todos los clips dentro de [0, duración]")
    check(len(d["clips"]) >= 1, f"{len(d['clips'])} clip(s) en el Short")
    src_in = min(c["source_in"] for c in d["clips"])
    check(abs(src_in - pk["start"]) < 0.02, "el Short empieza en el tramo elegido de la narración")
    check(d["name"].startswith("Reseña de prueba — Short 1"), f"nombre: {d['name']}")
    check(d["subtitles"]["preset"] == "Shorts · 3 palabras", "subtítulos con el preajuste de Shorts")

    # 4) sin transcripción: volumen y silencios
    sin = copy.copy(p)
    sin.transcripts = {}
    picks2 = SP.pick_shorts(sin, n=3, min_s=45, max_s=75)
    check(len(picks2) >= 1, f"sin transcripción: {len(picks2)} propuestas por volumen y silencios")
    for pk2 in picks2:
        check(45 - 0.01 <= pk2["end"] - pk2["start"] <= 75 + 0.01, "sin transcripción: tramo de 45–75 s")

    print("TODO OK")


if __name__ == "__main__":
    main()
