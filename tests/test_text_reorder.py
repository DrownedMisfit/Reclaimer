"""
Prueba de «mover / copiar con el texto» (sin ventanas):
  · controller.move_range: mover la frase 2 delante de la frase 1 deja la línea de tiempo en el orden 2,1,3…; el
    B-roll que estaba sobre la frase 2 y el marcador viajan con ella; la duración total no cambia; no hay huecos ni
    solapes; las parejas vinculadas siguen de 2 en 2; un Ctrl+Z lo devuelve todo;
  · copiar duplica (duración + tramo); una pista bloqueada detrás no deja hacer nada; pegar dentro de sí mismo no;
  · por el panel Texto: seleccionar palabras, Ctrl+X, poner el cursor y Ctrl+V hace lo mismo; Esc cancela.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_text_reorder.py _pruebas_tmp/test_text_reorder
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
_TMPROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_RAIZ, "_pruebas_tmp", "test_text_reorder")
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

from PySide6.QtCore import QEvent, QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import mapping  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_IMAGE, Clip, Marker, MediaItem, Project  # noqa: E402
from editoria.ui.transcript_panel import TranscriptPanel  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
FALLOS: list[str] = []
EPS = 1e-6


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
    """Proyecto con la voz de 3 frases «cortada en trozos» (sin pausas, como tras eliminar silencio), la frase 2
    vinculada a su imagen en V1, un B-roll encima de la frase 2 en V2 y un marcador dentro de la frase 2."""
    p = Project.new()
    v2 = next(t for t in p.tracks if t.name == "V2")
    v1 = next(t for t in p.tracks if t.name == "V1")
    a1 = next(t for t in p.tracks if t.name == "A1")
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=words[-1][1] + 1.0, probed=True)
    p.media["img"] = MediaItem(id="img", path=os.path.join(_TMP, "imagen.png"), kind=KIND_IMAGE,
                               name="imagen.png", duration=5.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": copy.deepcopy(words)}}
    cum, pos = 0.0, {}
    for k, (i0, i1) in enumerate(fr):
        s0, s1 = words[i0][0], words[i1][1]
        link = "L2" if k == 1 else ""
        p.clips[f"a{k}"] = Clip(id=f"a{k}", media_id="nar", track_id=a1.id, start=cum, source_in=s0,
                                duration=s1 - s0, link=link)
        if k == 1:      # la frase 2 también está en V1 (como la imagen de un video con su sonido)
            p.clips["v1"] = Clip(id="v1", media_id="nar", track_id=v1.id, start=cum, source_in=s0,
                                 duration=s1 - s0, link=link)
        pos[k] = (cum, s1 - s0)
        cum += s1 - s0
    st2, d2 = pos[1]
    p.clips["br"] = Clip(id="br", media_id="img", track_id=v2.id, start=st2 + 0.2, source_in=0.0,
                         duration=d2 - 0.4)
    p.markers.append(Marker(id="mk", time=st2 + d2 / 2, label="marca"))

    ctrl = ProjectController()
    ctrl.project = p
    engine = EngineFalso()
    panel = TranscriptPanel(ctrl, engine)
    panel.set_media("nar")
    panel.ensure_built()
    info = {"v1": v1, "v2": v2, "a1": a1, "fr": fr, "pos": pos}
    return ctrl, panel, info


def orden(ctrl) -> list[int]:
    """Palabras de la línea de tiempo en el orden en que suenan (las que están en la timeline)."""
    p = ctrl.project
    index = mapping.SourceIndex(p, "nar")
    ts = []
    for i, w in enumerate(p.transcripts["nar"]["words"]):
        t = index.time((w[0] + w[1]) / 2)
        if t is not None:
            ts.append((round(t, 6), i))
    return [i for _t, i in sorted(ts)]


def sin_solapes_ni_huecos(p: Project, track_id: str) -> tuple[bool, bool]:
    """(sin solapes, sin huecos) de una pista, mirando sus clips en orden."""
    cs = sorted((c for c in p.clips.values() if c.track_id == track_id), key=lambda c: c.start)
    solapes = any(a.end > b.start + EPS for a, b in zip(cs, cs[1:]))
    huecos = any(abs(a.end - b.start) > EPS for a, b in zip(cs, cs[1:]))
    return not solapes, not huecos


def parejas_de_2(p: Project) -> bool:
    grupos: dict[str, list[Clip]] = {}
    for c in p.clips.values():
        if c.link:
            grupos.setdefault(c.link, []).append(c)
    return all(len(g) == 2 and abs(g[0].start - g[1].start) < EPS and abs(g[0].duration - g[1].duration) < EPS
               for g in grupos.values())


def duracion(p: Project) -> float:
    return max(c.end for c in p.clips.values())


def prueba_mover(words, n_tl):
    print("Mover la frase 2 delante de la frase 1 (move_range)")
    fr = frases(words)[:3]
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    p1, p2 = fr[0], fr[1]
    antes = copy.deepcopy(p.timeline_state())
    dur0 = duracion(p)
    st2, d2 = info["pos"][1]
    br0 = p.clips["br"].start
    mk0 = p.markers[0].time
    a, b = panel._tl_span(p2[0], p2[1])
    to = panel._tl_insert_at(p1[0])
    check(a is not None and b is not None and to is not None, f"tramo de la frase 2: [{a:.3f}, {b:.3f}) hacia {to:.3f}")
    ok = ctrl.move_range(a, b, to, copy=False)
    check(ok is True, "move_range devuelve True")
    check(abs(duracion(p) - dur0) < EPS, f"la duración total no cambia ({dur0:.3f} s → {duracion(p):.3f} s)")
    esperado = list(range(p2[0], p2[1] + 1)) + list(range(p1[0], p1[1] + 1)) + list(range(p2[1] + 1, n_tl))
    check(orden(ctrl) == esperado, "el orden en la línea de tiempo es 2,1,3… (frase 2 antes que la 1)")
    sol, hue = sin_solapes_ni_huecos(p, info["a1"].id)
    check(sol and hue, "la voz queda pegada: sin solapes ni huecos")
    check(all(sin_solapes_ni_huecos(p, t.id)[0] for t in p.tracks), "ninguna pista tiene solapes")
    check(parejas_de_2(p), "las parejas vinculadas siguen de 2 en 2")
    check(abs(p.clips["br"].start - (br0 - a + to)) < EPS and abs(p.clips["br"].duration - (d2 - 0.4)) < EPS,
          f"el B-roll sobre la frase 2 viaja con ella (ahora en {p.clips['br'].start:.3f} s)")
    check(abs(p.markers[0].time - (mk0 - a + to)) < EPS, "el marcador dentro del tramo viaja con él")
    check(ctrl.undo_stack.text(ctrl.undo_stack.index() - 1) == "Mover con el texto", "un solo paso «Mover con el texto»")
    ctrl.undo_stack.undo()
    check(p.timeline_state() == antes, "Ctrl+Z devuelve toda la línea de tiempo")
    ctrl.undo_stack.redo()
    check(orden(ctrl) == esperado, "Ctrl+Y vuelve a dejarla movida")
    ctrl.undo_stack.undo()

    print("Casos que no deben hacer nada")
    antes2 = copy.deepcopy(p.timeline_state())
    check(ctrl.move_range(a, b, a + (b - a) / 2) is False, "pegar un trozo dentro de sí mismo: no hace nada")
    check(ctrl.move_range(a, b, b) is False and p.timeline_state() == antes2, "«mover» al mismo sitio: no cambia nada")
    p = ctrl.project                                  # (tras deshacer/rehacer, el proyecto es otro objeto)
    v2 = next(t for t in p.tracks if t.name == "V2")
    v2.locked = True
    antes3 = copy.deepcopy(p.timeline_state())
    check(ctrl.move_range(a, b, to) is False and p.timeline_state() == antes3,
          "con una pista bloqueada con contenido detrás: no hace nada y avisa")
    v2.locked = False
    return ctrl, panel, info, fr


def prueba_copiar(words, n_tl):
    print("Copiar la frase 2 delante de la frase 1 (copy=True)")
    fr = frases(words)[:3]
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    p1, p2 = fr[0], fr[1]
    dur0 = duracion(p)
    antes = copy.deepcopy(p.timeline_state())
    a, b = panel._tl_span(p2[0], p2[1])
    to = panel._tl_insert_at(p1[0])
    d = b - a
    n_a1 = sum(1 for c in p.clips.values() if c.track_id == info["a1"].id)
    check(ctrl.move_range(a, b, to, copy=True) is True, "move_range(copy=True) devuelve True")
    check(abs(duracion(p) - (dur0 + d)) < EPS, f"la duración crece lo copiado (+{d:.3f} s)")
    n_a1_2 = sum(1 for c in p.clips.values() if c.track_id == info["a1"].id)
    check(n_a1_2 == n_a1 + 1, "hay una copia más de la voz")
    check(any(abs(c.start - to) < EPS and abs(c.source_in - words[p2[0]][0]) < EPS
              for c in p.clips.values() if c.track_id == info["a1"].id), "la copia está en el sitio pedido")
    check(sin_solapes_ni_huecos(p, info["a1"].id)[0], "la copia no se solapa con nada")
    check(parejas_de_2(p), "la copia de la pareja vinculada también va de 2 en 2")
    ctrl.undo_stack.undo()
    check(p.timeline_state() == antes, "Ctrl+Z quita la copia")


def prueba_panel(words, n_tl):
    print("Por el panel Texto: seleccionar, Ctrl+X, cursor, Ctrl+V")
    fr = frases(words)[:3]
    ctrl, panel, info = construir(words, fr)
    p = ctrl.project
    p1, p2 = fr[0], fr[1]
    esperado = list(range(p2[0], p2[1] + 1)) + list(range(p1[0], p1[1] + 1)) + list(range(p2[1] + 1, n_tl))
    antes = copy.deepcopy(p.timeline_state())

    panel.ensure_built()
    cur = QTextCursor(panel.view.document())
    cur.setPosition(panel._pos[p2[0]][0])
    cur.setPosition(panel._pos[p2[1]][0] + panel._pos[p2[1]][1], QTextCursor.KeepAnchor)
    panel.view.setTextCursor(cur)
    panel.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_X, Qt.ControlModifier))
    check(panel._clip is not None and panel._clip["i0"] == p2[0] and panel._clip["i1"] == p2[1] and
          not panel._clip["copy"], "Ctrl+X recuerda la frase 2 (marcada en el texto)")
    cur = QTextCursor(panel.view.document())
    cur.setPosition(panel._pos[p1[0]][0])
    panel.view.setTextCursor(cur)
    panel.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier))
    panel.ensure_built()
    check(orden(ctrl) == esperado, "Ctrl+V con el cursor al principio deja 2,1,3…")
    check(panel._clip is None, "tras mover, el recorte queda libre")
    check(parejas_de_2(p) and sin_solapes_ni_huecos(p, info["a1"].id)[0] and sin_solapes_ni_huecos(p, info["a1"].id)[1],
          "tras el Ctrl+V: parejas bien y voz sin huecos")

    print("Esc cancela un recorte; Ctrl+V sin recorte no hace nada")
    ctrl.undo_stack.undo()
    p = ctrl.project
    check(p.timeline_state() == antes, "Ctrl+Z (panel) devuelve la línea de tiempo")
    panel.ensure_built()
    cur = QTextCursor(panel.view.document())
    cur.setPosition(panel._pos[p2[0]][0])
    cur.setPosition(panel._pos[p2[1]][0] + panel._pos[p2[1]][1], QTextCursor.KeepAnchor)
    panel.view.setTextCursor(cur)
    panel.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier))
    check(panel._clip is not None and panel._clip["copy"], "Ctrl+C recuerda la frase para copiarla")
    panel.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    check(panel._clip is None, "Esc cancela")
    antes2 = copy.deepcopy(p.timeline_state())
    panel.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier))
    check(p.timeline_state() == antes2, "Ctrl+V sin nada recortado no cambia nada")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    n_tl = frases(words)[2][1] + 1
    ctrl, panel, info, fr = prueba_mover(words, n_tl)
    prueba_copiar(words, n_tl)
    prueba_panel(words, n_tl)
    app.processEvents()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)}:")
        for f in FALLOS:
            print("  -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
