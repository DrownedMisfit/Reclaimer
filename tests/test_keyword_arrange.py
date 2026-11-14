"""
⚡ Acomodar por palabras clave (fila 🔑 de la línea de tiempo), sin red y sin ventanas:
  · tipo de cada archivo: subcarpetas «Gameplay» / «Cinemáticas» (y el nombre) mandan; si no, la IA; imágenes aparte;
  · orden de los archivos: natural (01, 2, 10) y con las subcarpetas;
  · tipo sugerido por lo que dices («la cinemática…» → 🎬) y por lo que hay en la carpeta; lo elegido a mano manda;
  · secuencia: cada mención del mismo tipo toma el trozo SIGUIENTE (sin repetir), pasa al archivo siguiente al acabarse
    y vuelve a empezar solo si se acaba todo; ✕ no pone nada; duración = la frase, sin pisar la siguiente;
  · «según lo que dices»: con huellas, el momento más parecido, pero nunca hacia atrás;
  · en el programa: chips en la regla, clic = cambiar el tipo (con Ctrl+Z), «⚡ Acomodar todo» en un solo Ctrl+Z, en la
    pista de palabras clave y sin sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_keyword_arrange.py _pruebas_tmp/test_keyword_arrange
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
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

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QScrollBar  # noqa: E402

from editoria.core import keyword_arrange as KA  # noqa: E402
from editoria.core import media as MEDIA  # noqa: E402

TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
CARPETAS = os.path.join(_TMP, "clips_por_palabra")


def prueba_nucleo():
    raiz = os.path.join(_TMP, "fake", "Halo")
    g = lambda *p: os.path.join(raiz, *p)  # noqa: E731
    assert KA.kind_of_file(g("Gameplay", "a.mp4"), [raiz]) == "gameplay"
    assert KA.kind_of_file(g("Cinemáticas", "x", "a.mp4"), [raiz]) == "cinematic"
    assert KA.kind_of_file(g("Tráilers", "a.mp4"), [raiz]) == "cinematic"
    assert KA.kind_of_file(g("cinematica final.mp4"), [raiz]) == "cinematic"
    assert KA.kind_of_file(g("a.mp4"), [raiz], "Cinemáticas") == "cinematic"
    assert KA.kind_of_file(g("a.mp4"), [raiz], "Gameplay") == "gameplay"
    assert KA.kind_of_file(g("a.mp4"), [raiz], "Menús") is None
    assert KA.kind_of_file(g("Gameplay", "a.png"), [raiz]) == "image"
    print("✓ tipo de archivo: subcarpetas y nombre mandan; si no, la IA; las imágenes aparte")

    folders = [{"label": "Halo", "keys": ["halo"], "own_path": raiz, "links": [],
                "files": [g("Gameplay", "10.mp4"), g("Gameplay", "2.mp4"), g("Gameplay", "01.mp4"),
                          g("Cinemáticas", "intro.mp4"), g("suelto.mp4"), g("foto.png")]}]
    pools = KA.build_pools(folders, lambda p: "")
    pool = pools["Halo"]
    assert [os.path.basename(p) for p in pool.gameplay] == ["01.mp4", "2.mp4", "10.mp4"], pool.gameplay
    assert [os.path.basename(p) for p in pool.cinematic] == ["intro.mp4"]
    assert [os.path.basename(p) for p in pool.unknown] == ["suelto.mp4"] and len(pool.image) == 1
    assert pool.available() == ["gameplay", "cinematic", "image", "none"]
    print("✓ orden natural de los archivos (01, 2, 10) y material por tipo")

    found = [{"term": "Halo", "media_id": "nar", "hits": [
        {"src": 10.0, "tl": 10.0, "context": "en esta parte el combate es brutal", "mods": []},
        {"src": 20.0, "tl": 20.0, "context": "la cinemática del final de", "mods": []},
        {"src": 30.0, "tl": 30.0, "context": "y luego", "mods": []},
        {"src": 31.0, "tl": 31.0, "context": "", "mods": []},
        {"src": 99.0, "tl": None, "context": "", "mods": []}]},
        {"term": "Zelda", "media_id": "nar", "hits": [{"src": 5.0, "tl": 5.0, "context": "", "mods": []}]}]
    ms = KA.collect(found, folders)
    assert [m["t"] for m in ms] == [10.0, 20.0, 30.0, 31.0], ms
    assert ms[0]["key"] == "halo|nar|10.00"
    assert KA.suggest(ms[0], pool) == "gameplay" and KA.suggest(ms[1], pool) == "cinematic"
    assert KA.suggest(ms[2], pool) == "gameplay"
    solo_cine = KA.Pool("X", cinematic=["c.mp4"])
    assert KA.suggest(ms[2], solo_cine) == "cinematic"
    print("✓ menciones con hora y tipo sugerido por lo que dices («combate» 🎮, «cinemática» 🎬)")

    dur = {g("Gameplay", "01.mp4"): 12.0, g("Gameplay", "2.mp4"): 8.0, g("Gameplay", "10.mp4"): 30.0,
           g("Cinemáticas", "intro.mp4"): 40.0, g("suelto.mp4"): 8.0}
    frase = lambda t: 4.0  # noqa: E731
    muchas = [{"key": f"halo|nar|{t:.2f}", "term": "Halo", "folder": "Halo", "t": float(t), "context": "",
               "mods": []} for t in range(0, 100, 10)]
    items, res = KA.plan(muchas, {}, pools, dur.get, frase, 200.0)
    assert len(items) == 10 and res["placed"] == 10
    vistos = []
    for it in items:
        assert it.kind == "gameplay" and it.dur == 4.0
        for p, a, b in vistos:
            assert p != it.path or it.src >= b - 1e-6 or it.src + it.dur <= a, "no repite trozos"
        vistos.append((it.path, it.src, it.src + it.dur))
    orden = [os.path.basename(it.path) for it in items]
    assert orden[:2] == ["01.mp4", "01.mp4"] and orden[2] == "2.mp4" and orden[3:9] == ["10.mp4"] * 6, orden
    assert items[0].src == 1.2 and abs(items[1].src - 5.2) < 1e-6, (items[0].src, items[1].src)
    assert orden[9] == "suelto.mp4" and res["repeated"] == 0
    print("✓ secuencia: cada mención toma el trozo siguiente, archivo tras archivo (y los «sin tipo» al final)")

    eleg = {muchas[1]["key"]: "cinematic", muchas[2]["key"]: "none", muchas[3]["key"]: "image"}
    items, res = KA.plan(muchas[:5], eleg, pools, dur.get, frase, 200.0)
    assert [it.kind for it in items] == ["gameplay", "cinematic", "image", "gameplay"], [it.kind for it in items]
    assert os.path.basename(items[1].path) == "intro.mp4" and items[2].path.endswith("foto.png")
    assert items[3].src == items[0].src + 4.0, "el gameplay sigue donde se quedó"
    cerca = [dict(muchas[0], t=0.0), dict(muchas[1], t=2.5), dict(muchas[2], t=2.8)]
    items, res = KA.plan(cerca, {}, pools, dur.get, frase, 200.0)
    assert [round(it.dur, 2) for it in items] == [2.5, 4.0] and res["skipped"] == 1, [it.dur for it in items]
    print("✓ lo elegido a mano manda (🎬, 🖼, ✕); la duración no pisa la siguiente mención")

    # según lo que dices: el momento más parecido, hacia delante
    ts = np.arange(0, 30, 1.0)
    vs = np.zeros((len(ts), 4), np.float32)
    vs[:, 0] = 1.0
    vs[22] = [0.0, 1.0, 0.0, 0.0]                         # el segundo 22 de 10.mp4 «es» lo que se dice
    vs[3] = [0.0, 1.0, 0.0, 0.0]                          # …y el 3 también, pero quedaría atrás
    vecs = {g("Gameplay", "10.mp4"): (ts, vs)}
    q = {"k2": np.array([0.0, 1.0, 0.0, 0.0], np.float32)}
    ms3 = [{"key": "k0", "folder": "Halo", "term": "Halo", "t": 0.0, "context": "", "mods": []},
           {"key": "k1", "folder": "Halo", "term": "Halo", "t": 10.0, "context": "", "mods": []},
           {"key": "k2", "folder": "Halo", "term": "Halo", "t": 20.0, "context": "algo", "mods": []}]
    pools2 = {"Halo": KA.Pool("Halo", gameplay=[g("Gameplay", "10.mp4")])}
    items, res = KA.plan(ms3, {}, pools2, dur.get, frase, 200.0, context=True, vecs_of=vecs.get, qvecs=q)
    assert items[2].by_context and abs(items[2].src - (22 - 4 * 0.3)) < 1e-6 and res["by_context"] == 1, items[2]
    items, res = KA.plan(ms3, {}, pools2, dur.get, frase, 200.0, context=False, vecs_of=vecs.get, qvecs=q)
    assert not items[2].by_context and items[2].src == items[1].src + 4.0
    print("✓ según lo que dices: salta al momento parecido (hacia delante); desactivado, va en orden")

    # --- casos que encontró la revisión (Fable 5.2)
    mezcla = [{"label": "M", "keys": ["m"], "own_path": raiz, "links": [],
               "files": [g("final.mp4"), g("01 intro.mp4"), g("Escenarios", "b.mp4")]}]
    pm = KA.build_pools(mezcla, lambda p: "")["M"]           # (antes: TypeError al comparar número con letra)
    assert [os.path.basename(p) for p in pm.unknown] == ["01 intro.mp4", "b.mp4", "final.mp4"], pm.unknown
    enl = os.path.join(_TMP, "fake", "Halo cinemáticas")
    assert KA.kind_of_file(os.path.join(enl, "x.mp4"), [raiz, enl], "", [enl]) == "cinematic"
    print("✓ nombres mezclados (01 intro / final) ordenan sin fallar; «Escenarios» no es cinemática; el nombre de "
          "la carpeta enlazada cuenta")

    def solapes(items):
        por = {}
        for it in items:
            for a, b in por.get(it.path, []):
                assert it.src >= b - 1e-6 or it.src + it.dur <= a + 1e-6, ("trozo repetido", it, a, b)
            por.setdefault(it.path, []).append((it.src, it.src + it.dur))

    A, B, U = g("Gameplay", "A.mp4"), g("Gameplay", "B.mp4"), g("U.mp4")
    dd = {A: 3.0, B: 60.0, U: 20.0}.get
    pv = {"Halo": KA.Pool("Halo", gameplay=[A, B])}
    fr = {0.0: 2.0, 10.0: 4.0, 20.0: 2.0}
    m3 = [{"key": f"k{t}", "folder": "Halo", "term": "Halo", "t": t, "context": "", "mods": []} for t in fr]
    items, res = KA.plan(m3, {}, pv, dd, fr.get, 200.0)
    solapes(items)
    assert len(items) == 3 and res["repeated"] == 0, (items, res)
    pu = {"Halo": KA.Pool("Halo", unknown=[U])}
    items, res = KA.plan(m3[:2], {"k10.0": "cinematic"}, pu, dd, fr.get, 200.0)
    assert [it.kind for it in items] == ["gameplay", "cinematic"]
    solapes(items)
    print("✓ sin trozos repetidos aunque las frases duren distinto o un video «sin tipo» sirva para 🎮 y 🎬")
    pegada = [{"key": "a", "folder": "Halo", "term": "Halo", "t": 10.0, "context": "", "mods": []},
              {"key": "b", "folder": "Halo", "term": "Halo", "t": 10.6, "context": "", "mods": []}]
    items, res = KA.plan(pegada, {"b": "none"}, pv, dd, lambda t: 4.0, 200.0)
    assert len(items) == 1 and items[0].dur == 4.0, items
    items, res = KA.plan(pegada, {}, pv, dd, lambda t: 4.0, 200.0)
    assert [it.key for it in items] == ["b"] and res["skipped"] == 1, (items, res)
    print("✓ una mención en ✕ no recorta la anterior; dos pegadas: la primera (0,6 s) no sale")


def _video(ruta: str, segundos: float):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=15", "-t", str(segundos), "-pix_fmt", "yuv420p", ruta],
                   check=True, timeout=120, creationflags=0x08000000)


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.01)


def prueba_programa(app):
    from editoria.core.controller import ProjectController
    from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project
    from editoria.ui import clips_panel as CP
    from editoria.ui.keyword_arrange_ui import KeywordArranger
    from editoria.ui.timeline import TimelineWidget
    shutil.rmtree(CARPETAS, ignore_errors=True)
    _video(os.path.join(CARPETAS, "Fortnite", "Gameplay", "01 partida.mp4"), 9.0)
    _video(os.path.join(CARPETAS, "Fortnite", "Gameplay", "02 partida.mp4"), 9.0)
    _video(os.path.join(CARPETAS, "Fortnite", "Cinemáticas", "historia.mp4"), 9.0)
    QSettings("EditorIA", "EditorIA").setValue(CP.RAIZ_CLAVE, CARPETAS)
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    for i in (3, 19, 27):                               # (la 27 va justo después de «cinemáticas»)
        words[i][2] = "Fortnite"
    dur_nar = float(words[-1][1]) + 1.0
    p = Project.new()
    v2, v1, a1 = p.tracks
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion.wav", duration=dur_nar,
                               probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)
    ctrl = ProjectController()
    ctrl.project = p

    win = QMainWindow()
    win.ctrl = ctrl
    win.timeline = TimelineWidget(ctrl, QScrollBar())
    win.timeline.resize(1400, 400)
    win.setCentralWidget(win.timeline)
    arr = KeywordArranger(win)
    tl = win.timeline
    tl.set_kw_visible(True)
    arr._toggled(True)
    t0 = time.time()
    while (arr._pool_job is not None or not tl.kw_marks) and time.time() - t0 < 30:
        pump(app, 0.05)
    marks = tl.kw_marks
    assert len(marks) == 3, marks
    tiempos = [float(words[i][0]) for i in (3, 19, 27)]
    assert all(abs(m["t"] - t) < 0.05 for m, t in zip(marks, tiempos)), ([m["t"] for m in marks], tiempos)
    assert [m["kind"] for m in marks] == ["gameplay", "gameplay", "cinematic"], [m["kind"] for m in marks]
    assert all(2.0 - 1e-6 <= m["dur"] <= 6.0 for m in marks)
    r, texto = tl._kw_rect(0)
    assert r is not None and "🎮" in texto
    tl.repaint()
    print("✓ fila 🔑: las 3 menciones en la regla con 🎮/🎬 sugerido (🎬 por «cinemáticas» antes de la palabra)")

    # clic = el tipo siguiente (y se deshace)
    k0 = marks[0]["key"]
    tl.kw_kind_requested.emit([k0], tl._kw_next(0))
    p = ctrl.project
    assert p.kw_choices[k0] == "cinematic" and tl.kw_marks[0]["kind"] == "cinematic" and tl.kw_marks[0]["manual"]
    ctrl.undo_stack.undo()
    arr._marks()
    assert k0 not in ctrl.project.kw_choices and tl.kw_marks[0]["kind"] == "gameplay"
    print("✓ clic en un chip cambia el tipo (queda elegido a mano) y Ctrl+Z lo devuelve")

    # ⚡ acomodar todo
    antes = set(ctrl.project.clips)
    pos = ctrl.undo_stack.index() if hasattr(ctrl.undo_stack, "index") else None
    arr.arrange()                                        # (primero relee las carpetas, luego acomoda)
    t0 = time.time()
    while (arr._arr_job is not None or arr._pool_job is not None) and time.time() - t0 < 60:
        pump(app, 0.05)
    pump(app, 0.1)
    p = ctrl.project
    nuevos = [p.clips[c] for c in p.clips if c not in antes]
    assert len(nuevos) == 3, len(nuevos)
    nuevos.sort(key=lambda c: c.start)
    nombres = [os.path.basename(p.media[c.media_id].path) for c in nuevos]
    assert nombres == ["01 partida.mp4", "01 partida.mp4", "historia.mp4"], nombres
    assert abs(nuevos[1].source_in - (nuevos[0].source_in + nuevos[0].duration)) < 0.01, "sigue en orden"
    assert len({c.track_id for c in nuevos}) == 1 and all(c.volume == 0 for c in nuevos)
    assert all(abs(c.start - t) < 0.05 for c, t in zip(nuevos, tiempos))
    assert all(c.track_id != a1.id for c in nuevos)
    print("✓ ⚡ Acomodar todo: gameplay en orden, la cinemática de su carpeta, una pista y sin sonido")
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes, "un Ctrl+Z lo quita todo"
    if pos is not None:
        assert ctrl.undo_stack.index() == pos
    print("✓ un Ctrl+Z quita todo lo acomodado")

    def acomodar():
        arr.arrange()
        t0 = time.time()
        while (arr._arr_job is not None or arr._pool_job is not None) and time.time() - t0 < 60:
            pump(app, 0.05)
        pump(app, 0.1)

    def de_acomodo():
        return sorted((c for c in ctrl.project.clips.values() if c.note.startswith("🔑⚡")), key=lambda c: c.start)
    acomodar()
    acomodar()                                           # dos veces: sin restos ni duplicados
    assert len(de_acomodo()) == 3, len(de_acomodo())
    tl.kw_kind_requested.emit([tl.kw_marks[1]["key"]], "none")
    acomodar()
    assert len(de_acomodo()) == 2 and all(abs(c.start - tiempos[1]) > 0.05 for c in de_acomodo())
    print("✓ volver a pulsar ⚡ sustituye lo del ⚡ anterior (sin restos); una mención pasada a ✕ se vacía")

    # clic real en un chip (y arrastrar desde él = mover el cabezal, sin cambiar nada)
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    tl.kw_kind_requested.emit([tl.kw_marks[0]["key"]], "")
    r, _t = tl._kw_rect(0)
    centro = r.center() + QPointF(0, tl._vt())

    def ev(kind, pt, buttons):
        return QMouseEvent(kind, pt, tl.mapToGlobal(pt.toPoint()).toPointF(), Qt.LeftButton, buttons, Qt.NoModifier)
    antes_k = tl.kw_marks[0]["kind"]
    tl.mousePressEvent(ev(QEvent.MouseButtonPress, centro, Qt.LeftButton))
    tl.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, centro, Qt.NoButton))
    assert tl.kw_marks[0]["kind"] != antes_k and tl.kw_marks[0]["manual"]
    k_ahora = tl.kw_marks[0]["kind"]
    tl.mousePressEvent(ev(QEvent.MouseButtonPress, centro, Qt.LeftButton))
    tl.mouseMoveEvent(ev(QEvent.MouseMove, centro + QPointF(60, 0), Qt.LeftButton))
    tl.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, centro + QPointF(60, 0), Qt.NoButton))
    assert tl.kw_marks[0]["kind"] == k_ahora, "arrastrar no cambia el tipo"
    print("✓ clic en el chip = el tipo siguiente; arrastrar desde él = mover el cabezal")

    # raíz sin carpetas: ⚡ avisa y no se queda leyendo en bucle
    vacia = os.path.join(_TMP, "sin_carpetas")
    os.makedirs(vacia, exist_ok=True)
    QSettings("EditorIA", "EditorIA").setValue(CP.RAIZ_CLAVE, vacia)
    arr.arrange()
    t0 = time.time()
    while (arr._pool_job is not None or arr._arr_job is not None) and time.time() - t0 < 20:
        pump(app, 0.05)
    pump(app, 0.5)
    assert arr._pool_job is None and arr._arr_job is None, "no debe releer las carpetas en bucle"
    assert "No hay carpetas" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
    assert tl.kw_marks == []
    print("✓ sin carpetas: ⚡ avisa y no relee en bucle")
    tl.deleteLater()
    win.deleteLater()
    app.processEvents()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import clips_panel as CP
    ajustes = QSettings("EditorIA", "EditorIA")
    try:
        prueba_nucleo()
        prueba_programa(app)
    finally:
        ajustes.remove(CP.RAIZ_CLAVE)
    print("TODO OK")


if __name__ == "__main__":
    main()
