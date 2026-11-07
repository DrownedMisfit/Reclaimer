"""
Prueba de «🎬 Mi intro y mi outro» (sin ventanas):
  · poner intro y outro: la intro queda en 0 y lo demás se corre su duración en TODAS las pistas (sin solapes);
    la outro queda al final;
  · repetir no duplica; un solo Ctrl+Z quita todo lo que puso;
  · las elecciones se guardan por tipo de proyecto (QSettings intro_outro/<formato>/intro|outro).
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_intro_outro.py _pruebas_tmp/test_intro_outro
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_RAIZ, "_pruebas_tmp", "test_intro_outro")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import intro_outro as IO  # noqa: E402
from editoria.core import media as MEDIA  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem, Project  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
DUR_VIDEO = 12.0
DUR_INTRO, DUR_OUTRO = 2.0, 3.0
FALLOS: list[str] = []


def check(cond: bool, msg: str):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FALLOS.append(msg)


def _ffmpeg(ruta: str, dur: float, color: str):
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
                    "-shortest", "-pix_fmt", "yuv420p", "-c:a", "aac", ruta], check=True, timeout=180,
                   creationflags=0x08000000)


def _proyecto(video: str) -> Project:
    p = Project.new()                                  # pistas: V2, V1, A1
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    dur_nar = float(words[-1][1]) + 1.0
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.media["vid"] = MediaItem(id="vid", path=video, kind=KIND_VIDEO, name="gen.mp4", duration=DUR_VIDEO,
                               width=320, height=180, fps=25.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    v2, v1, a1 = p.tracks
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)
    p.clips["cv"] = Clip(id="cv", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=DUR_VIDEO)
    p.clips["cb"] = Clip(id="cb", media_id="vid", track_id=v2.id, start=4.0, source_in=1.0, duration=3.0)
    return p


def _foto(p: Project) -> dict:
    return {cid: (c.track_id, round(c.start, 4), round(c.duration, 4), c.media_id) for cid, c in p.clips.items()}


def _sin_solapes(p: Project) -> bool:
    cs = list(p.clips.values())
    return not any(a is not b and a.track_id == b.track_id and a.start < b.end - 1e-6 and b.start < a.end - 1e-6
                   for a in cs for b in cs)


def main():
    app = QApplication.instance() or QApplication([])
    raiz_media = os.path.join(_TMPROOT, "medios")
    shutil.rmtree(raiz_media, ignore_errors=True)
    os.makedirs(raiz_media)
    intro = os.path.join(raiz_media, "mi_intro.mp4")
    outro = os.path.join(raiz_media, "mi_outro.mp4")
    _ffmpeg(intro, DUR_INTRO, "red")
    _ffmpeg(outro, DUR_OUTRO, "blue")
    video = os.path.join(_TMP, "gen.mp4")
    _ffmpeg(video, DUR_VIDEO, "green")

    ctrl = ProjectController()
    ctrl.project = _proyecto(video)
    antes = _foto(ctrl.project)
    fin_antes = max(c.end for c in ctrl.project.clips.values())

    print("Poner intro y outro")
    n = IO.place(ctrl, intro, outro)
    p = ctrl.project
    check(n == 2, f"se pusieron 2 piezas (salió {n})")
    intro_m = next(m for m in p.media.values() if os.path.normcase(m.path) == os.path.normcase(intro))
    outro_m = next(m for m in p.media.values() if os.path.normcase(m.path) == os.path.normcase(outro))
    ci = [c for c in p.clips.values() if c.media_id == intro_m.id and c.start < 0.01]
    check(len(ci) >= 1 and abs(ci[0].duration - intro_m.duration) < 0.05, "la intro está en 0 con su duración")
    desp = [abs((p.clips[cid].start - antes[cid][1]) - DUR_INTRO) < 0.01 and p.clips[cid].track_id == antes[cid][0]
            for cid in antes]
    check(all(desp), "todo lo que había se corrió la duración de la intro, en su misma pista")
    check(abs(p.clips["cb"].start - (4.0 + intro_m.duration)) < 0.01, "el clip de la pista de arriba (V2) también se corrió")
    co = [c for c in p.clips.values() if c.media_id == outro_m.id]
    check(len(co) >= 1 and abs(co[0].start - (fin_antes + intro_m.duration)) < 0.02,
          "la outro empieza justo donde acaba todo lo demás")
    check(_sin_solapes(p), "ningún clip se solapa con otro en su pista")

    print("Repetir no duplica")
    despues = _foto(p)
    n2 = IO.place(ctrl, intro, outro)
    check(n2 == 0 and _foto(ctrl.project) == despues, "repetir no añade nada")

    print("Ctrl+Z")
    ctrl.undo_stack.undo()
    check(_foto(ctrl.project) == antes, "un solo Ctrl+Z devuelve la línea de tiempo tal como estaba")

    print("Elecciones por tipo de proyecto")
    IO.set_("short", intro, outro)
    check(IO.get("short") == (intro, outro) and IO.configured("short"), "se guardan para Shorts")
    IO.set_("short", "", "")
    check(not IO.configured("short"), "se pueden quitar")
    IO.set_("youtube", intro, "")
    check(IO.get("youtube") == (intro, "") and not IO.get("edit")[0], "cada tipo de proyecto va por separado")
    IO.set_("youtube", "", "")

    print("Resultado")
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones")
        return 1
    print("TODO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
