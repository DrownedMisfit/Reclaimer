"""
Prueba del orden del texto del panel «Texto» (sin ventanas): se muestra en el ORDEN DE LA LÍNEA DE TIEMPO.
  · sin reordenar, el texto es la transcripción entera, igual que antes (un párrafo por segmento);
  · tras mover la frase 2 delante de la 1, el texto empieza por la frase 2;
  · clic en una palabra de la frase 2 lleva el cabezal a su tiempo nuevo;
  · buscar una palabra de la frase 2 da «1 de N» en ella (orden de la línea de tiempo);
  · copiar (copy=True) la frase 2 la deja dos veces en el texto;
  · Ctrl+Z devuelve el texto al orden original.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_text_order.py _pruebas_tmp/test_text_order
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import re
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_RAIZ, "_pruebas_tmp", "test_text_order")
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

from PySide6.QtCore import QEvent, QObject, QUrl, Qt, Signal  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import mapping  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_IMAGE, Clip, MediaItem, Project  # noqa: E402
from editoria.ui.transcript_panel import TranscriptPanel, _norm  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
FALLOS: list[str] = []


def check(cond: bool, msg: str):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FALLOS.append(msg)


class EngineFalso(QObject):
    """Lo mínimo que usa el panel del motor de reproducción."""
    time_changed = Signal(float)
    playing_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.time = 0.0
        self.playing = False

    def seek(self, t, *a, **k):
        self.time = t

    def user_seek(self, t, *a, **k):
        self.time = t


def frases(words) -> list[tuple[int, int]]:
    """Frases de la narración: se corta tras signo final o tras una pausa de más de 0,4 s."""
    out, ini = [], 0
    for i, w in enumerate(words):
        fin = i == len(words) - 1 or w[2][-1:] in ".?!" or (words[i + 1][0] - w[1]) > 0.4
        if fin:
            out.append((ini, i))
            ini = i + 1
    return out


def construir(words, fr) -> tuple[ProjectController, TranscriptPanel, dict]:
    """Proyecto con la voz de las frases de «fr» cortada en trozos (en ese orden), la frase 2 vinculada a su imagen
    en V1 y un B-roll encima. Los segmentos del texto son las frases (como en una transcripción real)."""
    p = Project.new()
    v2 = next(t for t in p.tracks if t.name == "V2")
    v1 = next(t for t in p.tracks if t.name == "V1")
    a1 = next(t for t in p.tracks if t.name == "A1")
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=words[-1][1] + 1.0, probed=True)
    p.media["img"] = MediaItem(id="img", path=os.path.join(_TMP, "imagen.png"), kind=KIND_IMAGE,
                               name="imagen.png", duration=5.0, probed=True)
    segs = [[words[a][0], words[b][1], a, b + 1] for a, b in frases(words)]
    p.transcripts = {"nar": {"language": "es", "words": copy.deepcopy(words), "segments": segs}}
    cum, pos = 0.0, {}
    for k, (i0, i1) in enumerate(fr):
        s0, s1 = words[i0][0], words[i1][1]
        link = "L2" if k == 1 else ""
        p.clips[f"a{k}"] = Clip(id=f"a{k}", media_id="nar", track_id=a1.id, start=cum, source_in=s0,
                                duration=s1 - s0, link=link)
        if k == 1:
            p.clips["v1"] = Clip(id="v1", media_id="nar", track_id=v1.id, start=cum, source_in=s0,
                                 duration=s1 - s0, link=link)
        pos[k] = (cum, s1 - s0)
        cum += s1 - s0
    st2, d2 = pos[1]
    p.clips["br"] = Clip(id="br", media_id="img", track_id=v2.id, start=st2 + 0.2, source_in=0.0,
                         duration=d2 - 0.4)
    ctrl = ProjectController()
    ctrl.project = p
    engine = EngineFalso()
    panel = TranscriptPanel(ctrl, engine)
    panel.set_media("nar")
    panel.ensure_built()
    return ctrl, panel, {"a1": a1, "pos": pos}


def tokens(panel) -> list[str]:
    """Palabras del texto dibujado, sin el sello de tiempo de cada párrafo."""
    out = []
    for linea in re.split(r"[\n\u2029]", panel.view.toPlainText()):
        out += linea.split()[1:]
    return out


def tiempo_real(p, words, i) -> float:
    """Momento de la línea de tiempo del inicio de la palabra i (calculado a mano, sin el panel)."""
    w = words[i]
    mid = (w[0] + w[1]) / 2
    t = mapping.SourceIndex(p, "nar").time(mid)
    return None if t is None else t - (mid - w[0])


def sin_solapes_ni_huecos(p, track_id) -> tuple[bool, bool]:
    cs = sorted((c for c in p.clips.values() if c.track_id == track_id), key=lambda c: c.start)
    return (not any(a.end > b.start + 1e-6 for a, b in zip(cs, cs[1:])),
            not any(abs(a.end - b.start) > 1e-6 for a, b in zip(cs, cs[1:])))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    fr = frases(words)[:3]
    p1, p2, p3 = fr
    n_w = len(words)
    f1 = [w[2] for w in words[p1[0]:p1[1] + 1]]
    f2 = [w[2] for w in words[p2[0]:p2[1] + 1]]
    f3 = [w[2] for w in words[p3[0]:p3[1] + 1]]
    resto = [w[2] for w in words[p3[1] + 1:]]          # sin cortar: aparecen tachados al final

    print("Sin reordenar: el texto es la transcripción entera, en su orden")
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    check(tokens(panel) == [w[2] for w in words], "el texto dibujado es la transcripción unida (sin sellos)")
    check([a.i for a in panel._anc] == list(range(n_w)), "las apariciones van en el orden del archivo")
    original = panel.view.toPlainText()
    antes = copy.deepcopy(p.timeline_state())

    print("Mover la frase 2 delante de la 1: el texto empieza por la frase 2")
    a, b = panel._tl_span(p2[0], p2[1])
    to = panel._tl_insert_at(p1[0])
    check(ctrl.move_range(a, b, to, copy=False) is True, "move_range devuelve True")
    panel.ensure_built()
    check(tokens(panel) == f2 + f1 + f3 + resto, "el texto sale 2,1,3… (orden de la línea de tiempo)")
    check(panel.view.toPlainText() != original, "el texto cambió respecto al original")
    check(tiempo_real(p, words, p2[0]) < tiempo_real(p, words, p1[0]), "la frase 2 suena antes que la 1")
    check(sin_solapes_ni_huecos(p, info["a1"].id)[1], "la voz sigue sin huecos")

    print("Clic en una palabra de la frase 2: el cabezal va a su tiempo nuevo")
    k = next(x.k for x in panel._anc if x.i == p2[1] and x.a is not None)     # la última palabra de la frase 2
    panel._on_anchor(QUrl(f"w{k}"))
    t_esp = max(0.0, tiempo_real(p, words, p2[1]) - 0.05)
    check(t_esp > 0.5, "la palabra del clic está lejos del principio (no vale 0 s por casualidad)")
    check(abs(panel.engine.time - t_esp) < 1e-3, f"cabezal en {panel.engine.time:.3f} s (esperado {t_esp:.3f} s)")

    print("Buscar una palabra de la frase 2: «1 de N» en ella")
    objetivo = words[p2[0]][2]
    panel.search.setText(objetivo)
    n_vivas = sum(1 for i, w in enumerate(words) if _norm(w[2]) == _norm(objetivo)
                  and tiempo_real(p, words, i) is not None)
    check(panel.search_count.text() == f"1 de {n_vivas}", f"contador «{panel.search_count.text()}»")
    primera = panel._hits[0][1] if panel._hits else None
    check(primera is not None and primera < tiempo_real(p, words, p1[0]),
          "la primera aparición en la línea de tiempo está en la frase 2 (antes que la 1)")
    check(panel.view.textCursor().selectedText().strip() == objetivo, "la aparición marcada en el texto es esa palabra")

    print("Copiar la frase 2 (copy=True): sale dos veces")
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    a, b = panel._tl_span(p2[0], p2[1])
    to = panel._tl_insert_at(p1[0])
    antes = copy.deepcopy(p.timeline_state())
    original = panel.view.toPlainText()
    check(ctrl.move_range(a, b, to, copy=True) is True, "move_range(copy=True) devuelve True")
    panel.ensure_built()
    check(tokens(panel) == f2 + f1 + f2 + f3 + resto, "la frase 2 aparece dos veces: 2,1,2,3…")
    dobles = [x for x in panel._anc if x.i == p2[0] and x.a is not None]
    check(len(dobles) == 2 and abs(dobles[0].a - dobles[1].a) > 0.05, "dos apariciones con tiempos distintos")
    ctrl.undo_stack.undo()
    panel.ensure_built()
    check(p.timeline_state() == antes and panel.view.toPlainText() == original,
          "Ctrl+Z vuelve al orden original")

    print("Ctrl+Z tras mover devuelve el texto al orden original")
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    original = panel.view.toPlainText()
    a, b = panel._tl_span(p2[0], p2[1])
    ctrl.move_range(a, b, panel._tl_insert_at(p1[0]), copy=False)
    panel.ensure_built()
    check(tokens(panel) != [w[2] for w in words], "movido: el texto ya no está en el orden del archivo")
    ctrl.undo_stack.undo()
    panel.ensure_built()
    check(panel.view.toPlainText() == original, "Ctrl+Z: el texto vuelve a verse igual que al principio")

    app.processEvents()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)}:")
        for f in FALLOS:
            print("  -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
