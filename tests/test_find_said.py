"""
Prueba de «🔎 Buscar en lo que dijiste» (panel Texto, sin ventanas):
  · «análisis» con o sin tilde, en mayúsculas o con signos: N apariciones (las que están en la timeline);
  · «3 de N» en el contador; ▶ / Enter = la siguiente (el cabezal salta a ella); ◀ / Mayús+Enter = la anterior;
  · las apariciones se marcan en la regla de la timeline (🔎) y al vaciar la búsqueda se quitan;
  · frase de varias palabras («análisis final»); convive con las marcas de Clips.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_find_said.py _pruebas_tmp/test_find_said
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_RAIZ, "_pruebas_tmp", "test_find_said")
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

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollBar  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import hint_marks  # noqa: E402
from editoria.ui.timeline import TimelineWidget  # noqa: E402
from editoria.ui.transcript_panel import TranscriptPanel  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
FALLOS: list[str] = []


def check(cond: bool, msg: str):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FALLOS.append(msg)


class EngineFalso(QObject):
    """Lo mínimo que usa el panel del motor de reproducción: el cabezal y cómo se mueve."""
    time_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.time = 0.0
        self.playing = False
        self.seeks: list[float] = []

    def user_seek(self, t: float):
        self.time = t
        self.seeks.append(t)
        self.time_changed.emit(t)

    def seek(self, t: float):
        self.user_seek(t)

    def pause(self):
        pass


def _tecla(widget, tecla, shift=False):
    mods = Qt.ShiftModifier if shift else Qt.NoModifier
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, tecla, mods))
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, tecla, mods))


def main():
    app = QApplication.instance() or QApplication([])
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    # palabras de prueba: «análisis» en 4 sitios (con y sin tilde, mayúsculas, signos) y «final» tras el primero
    for i, txt in ((6, "análisis"), (20, "Análisis."), (30, "analisis"), (40, "ANÁLISIS,")):
        words[i][2] = txt
    words[7][2] = "final"                       # «análisis final» (dos palabras seguidas)
    dur_nar = float(words[-1][1]) + 1.0
    p = Project.new()
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    a1 = p.tracks[-1]
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)

    ctrl = ProjectController()
    ctrl.project = p
    motor = EngineFalso()
    panel = TranscriptPanel(ctrl, motor)
    timeline = TimelineWidget(ctrl, QScrollBar())
    panel.search_marks_changed.connect(lambda m: hint_marks.set_source(timeline, "buscar", m))
    panel.set_media("nar")
    esperados = [words[i][0] + 0.0 for i in (6, 20, 30, 40)]

    print("Buscar «análisis»")
    panel.search.setText("análisis")
    check(len(panel._hits) == 4, f"4 apariciones (salieron {len(panel._hits)})")
    check(panel.search_count.text() == "1 de 4", f"contador «1 de 4» (dice «{panel.search_count.text()}»)")
    check(len(timeline.hint_marks) == 4 and all(s.startswith("🔎") for _t, s in timeline.hint_marks),
          f"4 marcas 🔎 en la línea de tiempo ({len(timeline.hint_marks)})")
    check(motor.seeks == [], "al escribir no mueve el cabezal")
    for texto in ("analisis", "ANÁLISIS", "Analisis"):
        panel.search.setText(texto)
        check(len(panel._hits) == 4, f"«{texto}» encuentra las 4")
    panel.search.setText("análisis")

    print("Siguiente y anterior")
    panel.btn_next.click()
    check(panel.search_count.text() == "2 de 4", f"tras ▶: «2 de 4» (dice «{panel.search_count.text()}»)")
    check(abs(motor.time - (esperados[1] - 0.05)) < 0.01 and len(motor.seeks) == 1,
          f"el cabezal va a la segunda aparición ({motor.time:.2f} s)")
    _tecla(panel.search, Qt.Key_Return)
    check(panel.search_count.text() == "3 de 4", "Enter = la siguiente (3 de 4)")
    _tecla(panel.search, Qt.Key_Return, shift=True)
    _tecla(panel.search, Qt.Key_Return, shift=True)
    check(panel.search_count.text() == "1 de 4", "Mayús+Enter dos veces = la primera (1 de 4)")
    panel.btn_prev.click()
    check(panel.search_count.text() == "4 de 4" and abs(motor.time - (esperados[3] - 0.05)) < 0.01,
          "◀ desde la primera = la última (4 de 4) y el cabezal va allí")

    print("Frase de varias palabras")
    panel.search.setText("Análisis final")
    check(len(panel._hits) == 1 and panel.search_count.text() == "1 de 1", "«Análisis final» = 1 aparición")
    panel.search.setText("")
    check(panel.search_count.text() == "" and timeline.hint_marks == [], "vaciar la búsqueda quita las marcas")
    panel.search.setText("nadaqueaparezca")
    check(panel.search_count.text() == "sin resultados" and timeline.hint_marks == [], "sin resultados: sin marcas")

    print("Convive con las marcas de Clips")
    panel.search.setText("análisis")
    hint_marks.set_source(timeline, "clips", [(1.0, "🎬 Dijiste")])
    check(len(timeline.hint_marks) == 5, "las 4 de búsqueda y la de Clips juntas")
    panel.search.setText("")
    check(timeline.hint_marks == [(1.0, "🎬 Dijiste")], "al vaciar la búsqueda quedan solo las de Clips")

    print("Resultado")
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones")
        return 1
    print("TODO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
