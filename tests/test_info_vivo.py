"""
⏱ PRUEBA de la fase 2 de la línea de tiempo (20/11): información en vivo.
  · al mover un clip 36 fotogramas sale «+00:00:01:06» (y «−…» hacia atrás) pegado al clip, sin cortar y dentro de lo
    que se repinta del arrastre; al soltar, el clip se ha movido eso exacto;
  · al recortar (normal y ripple) sale «duración · ±cambio» y el visor se pone en el fotograma del borde (en el borde
    derecho, el último que queda);
  · al ALARGAR un clip, el visor enseña el fotograma nuevo del archivo (engine.mostrar_fotograma) y al soltar vuelve
    al cabezal;
  · «,» y «.» mueven el clip elegido (con su sonido vinculado) 1 fotograma; varias pulsaciones = un Ctrl+Z; NUNCA
    tapan nada (pegado a otro clip: avisa y no se mueve); pista bloqueada: avisa; a menos de 1 fotograma del 0, al 0;
    en el 0 avisa; también a 23,976; los atajos no chocan con ningún otro;
  · el repintado durante el arrastre no empeora más de un 10 % con la etiqueta.
Ejecutar:  .venv/Scripts/python.exe tests/test_info_vivo.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetricsF, QKeySequence, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _vigilante(segundos: float = 420.0):
    """Si la prueba se cuelga (un diálogo o un menú de verdad), sale sola y libera el turno."""
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta (¿un menú o un diálogo esperando?)", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


FPS = 30.0


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def cerca(a, b, tol=1e-6):
    return abs(a - b) <= tol


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "info_vivo")
    os.makedirs(out, exist_ok=True)
    capturas = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp",
                            "timeline_fase2")
    os.makedirs(capturas, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    vid = os.path.join(out, "video.mp4")
    if not os.path.exists(vid):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=12", "-f", "lavfi", "-i", "sine=f=440:d=12",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", vid], check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.8)
    ctrl, tl = win.ctrl, win.timeline
    ctrl.project.fps = FPS
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.insert_ranges([{"media_id": mid, "start": 1.0, "source_in": 2.0, "duration": 3.0},
                        {"media_id": mid, "start": 6.0, "source_in": 0.0, "duration": 3.0}], v1.id, "Clips")
    pump(app, 0.2)
    P = ctrl.project
    a1 = next(c.track_id for c in P.clips.values() if P.track(c.track_id).kind == TRACK_AUDIO)
    vids = sorted(P.clips_on(v1.id), key=lambda c: c.start)
    uno = vids[0].id
    tl.snapping = False
    tl.pps, tl.scroll = 120.0, 0.0
    tl._update_scrollbar()
    pump(app, 0.2)
    msgs = []
    ctrl.message.connect(lambda m: msgs.append(m))
    seeks = []
    tl.seek_requested.connect(lambda t: seeks.append(t))
    fotos, sueltas = [], []                   # ⏱ lo que se pide al visor al alargar (y que vuelva al soltar)
    tl.edge_frame_requested.connect(lambda m_, s_: fotos.append((m_, s_)))
    tl.edge_frame_released.connect(lambda: sueltas.append(1))

    def foto():
        return sorted((c.id, round(c.start, 6), round(c.duration, 6), round(c.source_in, 6), c.track_id)
                      for c in ctrl.project.clips.values())

    def mover(x, y, mods=Qt.NoModifier):
        ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))),
                         Qt.LeftButton, Qt.LeftButton, mods)
        tl.mouseMoveEvent(ev)

    def empezar(x, y, dx, mods=Qt.NoModifier):
        QTest.mousePress(tl, Qt.LeftButton, mods, QPoint(int(round(x)), int(round(y))))
        mover(x + dx / 2, y, mods)
        mover(x + dx, y, mods)
        tl._flush_seek()
        return tl._drag

    def soltar(x, y, mods=Qt.NoModifier):
        QTest.mouseRelease(tl, Qt.LeftButton, mods, QPoint(int(round(x)), int(round(y))))
        pump(app, 0.05)

    def etiqueta_bien(info, nombre):
        texto, r = info
        fm = QFontMetricsF(tl._info_font())
        assert fm.horizontalAdvance(texto) <= r.width() - 4, (nombre, "texto cortado", texto, r)
        assert r.left() >= tl.HEADER_W and r.right() <= tl.width(), (nombre, r, tl.width())
        assert r.top() >= tl._vt() + tl.RULER_H, (nombre, "debajo de la regla", r)
        assert any(x.contains(r) for x in tl._drag_rects(tl._drag)), (nombre, "fuera de lo que se repinta")

    base = foto()
    c = P.clips[uno]
    r = tl.clip_rect(c)
    x0, y0 = r.center().x(), r.center().y()
    # 1) mover +36 fotogramas → «+00:00:01:06»
    d = empezar(x0, y0, 36 / FPS * tl.pps)
    assert d and d["type"] == "move" and d.get("active"), d
    info = tl._info_vivo(d)
    assert info is not None and info[0] == "+00:00:01:06", info
    etiqueta_bien(info, "mover +36")
    tl.repaint()
    tl.grab().copy(0, 0, min(tl.width(), 1600), min(tl.height(), 400)).save(os.path.join(capturas, "mover_mas36.png"))
    # el repintado con la etiqueta no empeora más de un 10 %
    def medir():
        tl.repaint()
        ts = []
        for _ in range(5):
            a = time.perf_counter()
            for _ in range(6):
                tl.repaint()
            ts.append((time.perf_counter() - a) / 6 * 1000)
        return min(ts)
    pump(app, 0.5)                           # (que acaben de llegar tiras y formas de onda: no cuentan en el banco)
    for _ in range(10):
        tl.repaint()
    orig = tl._info_vivo
    con = sin = 1e9
    for _ in range(3):                       # (alternando: el calentamiento no cuenta en contra de ninguno)
        tl._info_vivo = lambda _d: None
        sin = min(sin, medir())
        tl._info_vivo = orig
        con = min(con, medir())
    print(f"  repintado durante el arrastre: {sin:.2f} ms sin etiqueta · {con:.2f} ms con etiqueta")
    assert con <= sin * 1.10, f"el repintado empeora más de un 10 %: {sin:.2f} → {con:.2f} ms"
    soltar(x0 + 36 / FPS * tl.pps, y0)
    assert cerca(P.clips[uno].start, 2.2), P.clips[uno].start
    assert tl._info_vivo(tl._drag) is None
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    # …y −15 fotogramas → «−00:00:00:15»
    d = empezar(x0, y0, -15 / FPS * tl.pps)
    info = tl._info_vivo(d)
    assert info is not None and info[0] == "−00:00:00:15", info
    etiqueta_bien(info, "mover −15")
    soltar(x0 - 15 / FPS * tl.pps, y0)
    assert cerca(P.clips[uno].start, 0.5), P.clips[uno].start
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    print("✓ mover: «+00:00:01:06» con 36 fotogramas y «−00:00:00:15» hacia atrás, pegada al clip, sin cortar; al soltar "
          "se movió eso exacto")

    # 2) recortar el final −15 fotogramas → «00:00:02:15 · −00:00:00:15»; el visor en el último fotograma que queda
    c = P.clips[uno]
    r = tl.clip_rect(c)
    seeks.clear()
    d = empezar(r.right() - 1, y0, -15 / FPS * tl.pps)
    assert d and d["type"] == "trim" and d["edge"] == "right", d
    info = tl._info_vivo(d)
    assert info is not None and info[0] == "00:00:02:15 · −00:00:00:15", info
    etiqueta_bien(info, "recorte final")
    assert seeks and cerca(seeks[-1], d["new_end"] - 1 / FPS), (seeks[-3:], d["new_end"])
    tl.repaint()
    tl.grab().copy(0, 0, min(tl.width(), 1600), min(tl.height(), 400)).save(os.path.join(capturas, "recorte.png"))
    soltar(r.right() - 1 - 15 / FPS * tl.pps, y0)
    assert cerca(P.clips[uno].duration, 2.5), P.clips[uno].duration
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    # recortar el inicio +6 fotogramas (más corto) → «00:00:02:24 · −00:00:00:06»; el visor en su primer fotograma
    seeks.clear()
    d = empezar(r.left() + 1, y0, 6 / FPS * tl.pps)
    info = tl._info_vivo(d)
    assert d["edge"] == "left" and info is not None and info[0] == "00:00:02:24 · −00:00:00:06", (d, info)
    assert seeks and cerca(seeks[-1], d["new_start"]), (seeks[-3:], d["new_start"])
    soltar(r.left() + 1 + 6 / FPS * tl.pps, y0)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    assert not fotos, "al acortar no hace falta el fotograma nuevo (el visor va al borde)"
    # ripple (Ctrl+borde) +9 fotogramas → «00:00:03:09 · +00:00:00:09»; ALARGA: el visor, en el fotograma nuevo
    seeks.clear()
    d = empezar(r.right() - 1, y0, 9 / FPS * tl.pps, Qt.ControlModifier)
    assert d and d["type"] == "ripple", d
    info = tl._info_vivo(d)
    assert info is not None and info[0] == "00:00:03:09 · +00:00:00:09", info
    etiqueta_bien(info, "ripple")
    assert fotos and cerca(fotos[-1][1], 2.0 + 3.3 - 1 / FPS) and not seeks, (fotos[-3:], seeks[-3:], d["t"])
    soltar(r.right() - 1 + 9 / FPS * tl.pps, y0, Qt.ControlModifier)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    fotos.clear()
    sueltas.clear()
    # alargar el final +9 fotogramas: el visor enseña el ÚLTIMO fotograma nuevo (del archivo) y no salta el cabezal
    seeks.clear()
    d = empezar(r.right() - 1, y0, 9 / FPS * tl.pps)
    assert d["type"] == "trim" and cerca(d["new_end"], 4.3), d
    assert fotos and fotos[-1][0] == mid and cerca(fotos[-1][1], 2.0 + 3.3 - 1 / FPS), fotos[-3:]
    assert not seeks, seeks
    assert win.engine.mostrar_fotograma(mid, fotos[-1][1]) is True, "el visor de verdad lo enseña (en pausa)"
    soltar(r.right() - 1 + 9 / FPS * tl.pps, y0)
    assert sueltas, "al soltar, el visor vuelve al cabezal"
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    # alargar el inicio −6 fotogramas: el PRIMER fotograma nuevo
    fotos.clear()
    sueltas.clear()
    d = empezar(r.left() + 1, y0, -6 / FPS * tl.pps)
    assert d["edge"] == "left" and fotos and cerca(fotos[-1][1], 2.0 - 0.2), (d, fotos[-3:])
    # …y si vuelve a acortar en el mismo arrastre, el visor vuelve al borde
    mover(r.left() + 1 + 3 / FPS * tl.pps, y0)
    assert sueltas, "al dejar de alargar, vuelve al cabezal"
    soltar(r.left() + 1 + 3 / FPS * tl.pps, y0)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    print("✓ alargar: el visor enseña el fotograma nuevo del archivo (último al final, primero al inicio) y vuelve al "
          "cabezal al soltar o al dejar de alargar")
    print("✓ recortar: «duración · ±cambio» (normal y ripple) y el visor en el fotograma del borde (en el final, el "
          "último que queda)")

    # 3) «,» y «.»: los atajos existen y no chocan con ninguno
    seqs = {}
    for key, (a, _d) in win.shortcut_actions.items():
        for sq in a.shortcuts():
            s = sq.toString(QKeySequence.PortableText)
            if s:
                assert s not in seqs, f"«{s}» lo usan «{seqs[s]}» y «{key}»"
                seqs[s] = key
    assert "," in seqs and "." in seqs, sorted(seqs)
    act = {s: win.shortcut_actions[seqs[s]][0] for s in (",", ".")}
    assert act["."].statusTip() and act[","].statusTip()
    tl.set_selection([uno])
    n0 = ctrl.undo_stack.index()
    for _ in range(3):
        act["."].trigger()
        pump(app, 0.02)
    A = next(x for x in P.clips.values() if x.track_id == a1 and x.link == P.clips[uno].link)
    assert cerca(P.clips[uno].start, 1.1) and cerca(A.start, 1.1), (P.clips[uno].start, A.start)
    assert ctrl.undo_stack.index() - n0 == 1, ctrl.undo_stack.index() - n0
    act[","].trigger()
    pump(app, 0.02)
    assert cerca(P.clips[uno].start, 1.0 + 2 / FPS)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base, "un Ctrl+Z deshace las pulsaciones seguidas"
    def al_cero(pp):
        for x in pp.clips.values():
            if x.link == pp.clips[uno].link:
                x.start = 0.0
    ctrl._edit("al cero", al_cero)
    f0 = foto()
    msgs.clear()
    act[","].trigger()
    pump(app, 0.02)
    assert foto() == f0 and msgs and "principio" in msgs[-1], msgs
    ctrl.undo_stack.undo()
    tl.set_selection([])
    act["."].trigger()
    pump(app, 0.02)
    assert foto() == base
    tl.set_selection([uno])
    # a menos de un fotograma del 0: se pega al 0 (no avisa)
    def casi_cero(pp):
        for x in pp.clips.values():
            if x.link == pp.clips[uno].link:
                x.start = 0.02
    ctrl._edit("casi al cero", casi_cero)
    act[","].trigger()
    pump(app, 0.02)
    A = next(x for x in P.clips.values() if x.track_id == a1 and x.link == P.clips[uno].link)
    assert P.clips[uno].start == 0.0 and A.start == 0.0, (P.clips[uno].start, A.start)
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    # pegado a otro clip (como tras eliminar silencios): avisa y NO tapa nada, ni con 5 pulsaciones
    dos = vids[1].id

    def pegar(pp):
        for x in pp.clips.values():
            if x.link == pp.clips[dos].link:
                x.start = 4.0
    ctrl._edit("pegados", pegar)
    pegados = foto()
    tl.set_selection([uno])
    msgs.clear()
    for _ in range(5):
        act["."].trigger()
        pump(app, 0.02)
    assert foto() == pegados and msgs and "taparía" in msgs[-1], msgs
    act[","].trigger()                        # (hacia el otro lado sí hay sitio)
    pump(app, 0.02)
    assert cerca(P.clips[uno].start, 1.0 - 1 / FPS)
    ctrl.undo_stack.undo()
    # elegidos los dos pegados: se mueven juntos
    tl.set_selection([uno, dos])
    act["."].trigger()
    pump(app, 0.02)
    assert cerca(P.clips[uno].start, 1.0 + 1 / FPS) and cerca(P.clips[dos].start, 4.0 + 1 / FPS)
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base
    # pista bloqueada: avisa y no se mueve
    v1t = P.track(v1.id)
    v1t.locked = True
    tl.set_selection([uno])
    msgs.clear()
    act["."].trigger()
    pump(app, 0.02)
    assert foto() == base and msgs and "🔒" in msgs[-1], msgs
    ctrl.project.track(v1.id).locked = False       # (el aviso deshizo el intento: la pista es otro objeto)
    assert not any(t_.locked for t_ in ctrl.project.tracks)
    # a 23,976 fotogramas por segundo: un fotograma exacto
    P.fps = 24000 / 1001
    act["."].trigger()
    pump(app, 0.02)
    assert cerca(P.clips[uno].start, 1.0 + 1001 / 24000), P.clips[uno].start
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    P.fps = FPS
    assert foto() == base
    print("✓ «,» / «.»: el clip elegido y su sonido se mueven 1 fotograma; 3 pulsaciones = un Ctrl+Z; nunca tapan "
          "(pegado: avisa); pista bloqueada: avisa; casi en el 0: al 0; en el 0 avisa; a 23,976 también; los atajos no "
          "chocan con ningún otro")

    ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
