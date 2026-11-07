"""
Prueba de «deshacer de las correcciones de la transcripción» (sin ventanas):
  · corregir una palabra desde el panel Texto (✎ Escribir la correcta… y clic derecho → cambiar) es UN paso de
    Ctrl+Z / Ctrl+Y («Corregir palabra»); la transcripción y el texto dibujado cambian y vuelven;
  · «Cambiar en todo el texto» (varias apariciones) es un solo paso («Corregir texto»);
  · la corrección desde el visor (subtitle_edit.correct) es un paso «Corregir subtítulo», con y sin cambio de número
    de palabras; el subtítulo (cue) en ese tiempo cambia y se deshace;
  · una corrección sin cambios no añade ningún paso.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_transcript_undo.py _pruebas_tmp/test_transcript_undo
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_RAIZ, "_pruebas_tmp", "test_transcript_undo")
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

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollBar  # noqa: E402

from editoria.core import subtitles  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import subtitle_edit  # noqa: E402
from editoria.ui import transcript_panel as TP  # noqa: E402
from editoria.ui.timeline import TimelineWidget  # noqa: E402
from editoria.ui.transcript_panel import TranscriptPanel  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
FALLOS: list[str] = []
IDX_ANALISIS = 6          # «análisis.» (aparece 4 veces en la narración de prueba)


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

    def seek(self, t, *a, **k):
        self.time = t


class DialogoFalso:
    """Sustituye al cuadro «Corregir palabra» / «Cambiar en todo el texto»: devuelve la respuesta fijada."""
    respuesta = ""

    @staticmethod
    def getText(*_a, **_k):
        return DialogoFalso.respuesta, True


def _texto_de(ctrl, mid: str) -> str:
    return " ".join(w[2] for w in ctrl.project.transcripts[mid]["words"])


def _cue_en(ctrl, mid: str, idx: int) -> str:
    """Texto del subtítulo que contiene la palabra idx (tal como lo verá el usuario)."""
    for cue in subtitles.build_cues(ctrl.project, mid):
        if any(w.index == idx for w in cue.words):
            return cue.text(" ")
    return ""


def _repetida(words: list) -> list[int]:
    """Índices de una palabra que sale varias veces en la narración de prueba (la más repetida)."""
    from editoria.ai import word_fix
    cuentas: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        cuentas.setdefault(word_fix.core(w[2]).lower(), []).append(i)
    mas = max(cuentas.values(), key=len)
    if len(mas) >= 2:
        return mas
    raise SystemExit("La transcripción de prueba no tiene ninguna palabra repetida.")


def _etiqueta(ctrl, i: int) -> str:
    return ctrl.undo_stack.text(i)


def prueba_panel(ctrl, panel):
    mid = "nar"
    print("Corregir una palabra desde el panel Texto (✎ Escribir la correcta…)")
    words0 = copy.deepcopy(ctrl.project.transcripts[mid]["words"])
    cue0 = _cue_en(ctrl, mid, IDX_ANALISIS)
    n0 = ctrl.undo_stack.index()
    panel.ensure_built()
    TP.QInputDialog = DialogoFalso
    DialogoFalso.respuesta = "analisis"
    panel._edit_word(IDX_ANALISIS)
    check(ctrl.undo_stack.index() == n0 + 1, f"un solo paso de deshacer (pasos {n0} → {ctrl.undo_stack.index()})")
    check(_etiqueta(ctrl, n0) == "Corregir palabra", f"nombre «Corregir palabra» (es «{_etiqueta(ctrl, n0)}»)")
    check(ctrl.project.transcripts[mid]["words"][IDX_ANALISIS][2] == "analisis.", "la palabra cambió (conserva el punto de «análisis.»)")
    check(ctrl.project.transcripts[mid]["words"][IDX_ANALISIS][:2] == words0[IDX_ANALISIS][:2],
          "los tiempos de la palabra no cambian")
    cue1 = _cue_en(ctrl, mid, IDX_ANALISIS)
    check("analisis" in cue1 and cue1 != cue0, f"el subtítulo cambia («{cue1}»)")
    panel.ensure_built()
    check("analisis" in panel.view.toPlainText() and "análisis" not in panel.view.toPlainText(),
          "el panel Texto dibuja la corrección")

    print("Deshacer / rehacer (Ctrl+Z / Ctrl+Y)")
    ctrl.undo_stack.undo()
    check(ctrl.project.transcripts[mid]["words"] == words0, "Ctrl+Z devuelve la transcripción exacta")
    check(_cue_en(ctrl, mid, IDX_ANALISIS) == cue0, "el subtítulo vuelve al original")
    panel.ensure_built()
    check("análisis" in panel.view.toPlainText() and "analisis" not in panel.view.toPlainText(),
          "el panel Texto vuelve a dibujar el original")
    ctrl.undo_stack.redo()
    check(ctrl.project.transcripts[mid]["words"][IDX_ANALISIS][2] == "analisis.", "Ctrl+Y rehace la corrección")
    dif = [i for i, (a, b) in enumerate(zip(words0, ctrl.project.transcripts[mid]["words"])) if a != b]
    check(dif == [IDX_ANALISIS], f"solo cambia esa palabra (cambian {dif})")
    ctrl.undo_stack.undo()                       # deja el proyecto como estaba para lo siguiente
    check(ctrl.project.transcripts[mid]["words"] == words0, "vuelve al original antes de seguir")

    print("Sin cambios: no añade paso")
    n1 = ctrl.undo_stack.index()
    panel._replace_word(IDX_ANALISIS, "análisis")          # misma palabra
    check(ctrl.undo_stack.index() == n1, "cambiar por la misma palabra no añade paso")

    print("«Cambiar en todo el texto» (varias apariciones) = un paso")
    idxs = _repetida(words0)
    i0 = idxs[0]
    n2 = ctrl.undo_stack.index()
    panel._replace_word(i0, "zeta", everywhere=True)
    check(ctrl.undo_stack.index() == n2 + 1, "un solo paso para las apariciones")
    check(_etiqueta(ctrl, n2) == "Corregir texto", f"nombre «Corregir texto» (es «{_etiqueta(ctrl, n2)}»)")
    dif = [i for i, (a, b) in enumerate(zip(words0, ctrl.project.transcripts[mid]["words"])) if a != b]
    check(dif == idxs, f"cambian las {len(idxs)} apariciones (cambian {len(dif)})")
    ctrl.undo_stack.undo()
    check(ctrl.project.transcripts[mid]["words"] == words0, "Ctrl+Z devuelve las apariciones")

    print("Escritura de la corrección: un paso por confirmación, no por letra")
    n3 = ctrl.undo_stack.index()
    ctrl.edit_word(mid, 12, "Fortnite")
    ctrl.edit_word(mid, 12, "Fortnite2")               # segunda corrección confirmada = otro paso
    check(ctrl.undo_stack.index() == n3 + 2, "cada corrección confirmada es un paso")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    check(ctrl.project.transcripts[mid]["words"] == words0, "dos Ctrl+Z dejan la transcripción original")


def prueba_visor(ctrl):
    mid = "nar"
    print("Corrección desde el visor (subtitle_edit.correct)")
    words0 = copy.deepcopy(ctrl.project.transcripts[mid]["words"])
    cue0 = _cue_en(ctrl, mid, IDX_ANALISIS)
    n0 = ctrl.undo_stack.index()
    aviso = subtitle_edit.correct(ctrl, mid, [IDX_ANALISIS], "analisis")
    check(aviso is None, "sin aviso")
    check(ctrl.undo_stack.index() == n0 + 1, f"un solo paso (pasos {n0} → {ctrl.undo_stack.index()})")
    check(_etiqueta(ctrl, n0) == "Corregir subtítulo", f"nombre «Corregir subtítulo» (es «{_etiqueta(ctrl, n0)}»)")
    check(_cue_en(ctrl, mid, IDX_ANALISIS) != cue0 and "analisis" in _cue_en(ctrl, mid, IDX_ANALISIS),
          "el subtítulo cambia")
    ctrl.undo_stack.undo()
    check(ctrl.project.transcripts[mid]["words"] == words0 and _cue_en(ctrl, mid, IDX_ANALISIS) == cue0,
          "Ctrl+Z devuelve transcripción y subtítulo")
    ctrl.undo_stack.redo()
    check("analisis" in _cue_en(ctrl, mid, IDX_ANALISIS), "Ctrl+Y rehace el subtítulo")
    ctrl.undo_stack.undo()

    print("Corrección del visor que cambia el número de palabras (reparto en el tramo)")
    n1 = ctrl.undo_stack.index()
    aviso = subtitle_edit.correct(ctrl, mid, [0, 1], "Hola a todos")     # «Hola a» → 3 palabras
    check(aviso is None, "sin aviso")
    check(ctrl.undo_stack.index() == n1 + 1, "un solo paso")
    check(len(ctrl.project.transcripts[mid]["words"]) == len(words0) + 1, "hay una palabra más")
    ctrl.undo_stack.undo()
    check(ctrl.project.transcripts[mid]["words"] == words0, "Ctrl+Z devuelve las palabras originales")

    print("Corrección directa del controlador (edit_words) y mismo texto (no añade paso)")
    n2 = ctrl.undo_stack.index()
    subtitle_edit.correct(ctrl, mid, [IDX_ANALISIS], "análisis")
    check(ctrl.undo_stack.index() == n2, "mismo texto: no añade paso")


def main():
    global app
    app = QApplication.instance() or QApplication(sys.argv)
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        tr = json.load(f)
    words = tr["words"]
    dur_nar = float(words[-1][1]) + 1.0
    p = Project.new()
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    a1 = p.tracks[-1]
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)

    ctrl = ProjectController()
    ctrl.project = p
    engine = EngineFalso()
    panel = TranscriptPanel(ctrl, engine)
    timeline = TimelineWidget(ctrl, QScrollBar())
    panel.set_media("nar")
    try:
        prueba_panel(ctrl, panel)
        prueba_visor(ctrl)
    finally:
        timeline.deleteLater()
        panel.deleteLater()
        app.processEvents()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)}:")
        for f in FALLOS:
            print("  -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
