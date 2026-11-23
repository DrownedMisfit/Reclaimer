"""
🔴 PRUEBA de la fase 1b de la línea de tiempo (20/11, idea del usuario): puntos de unión en el audio.
Tras eliminar silencios, cada unión de dos piezas pegadas lleva un punto arriba (final de la pieza de la izquierda) y
otro abajo (inicio de la de la derecha). Comprueba:
  · palabra cortada (por la transcripción o porque la voz suena en el borde) → punto rojo; unión limpia → gris;
  · arrastrar el punto de arriba +3 fotogramas → la pieza crece exactamente 3, lo de detrás se recorre eso mismo con su
    contenido intacto, el video sigue en sincronía y un Ctrl+Z lo deshace; lo mismo con el punto de abajo;
  · el imán se pega al final estimado de la palabra (y sale «+N fotogramas»);
  · TODAS las pistas (bloqueante de Fable): narración en 3 piezas + 2 subtítulos + 2 B-roll sin vincular, +3 y −3 con el
    punto de arriba y el de abajo en la 1.ª y la 2.ª unión → todo sigue sobre la misma palabra; un texto bloqueado detrás
    → aviso y nada cambia; una música que cruza la unión con +3 → quieta y entera; una capa de escena que cruza la unión
    en otra pista (4b) → +3 avisa y −3 la recorta igual;
  · 500 uniones → el pintado sigue fluido (no empeora más de un 10 %);
  · el botón ◉ y la casilla de «4 · Cortes de audio» van a la par y se recuerdan.
Ejecutar:  .venv/Scripts/python.exe tests/test_puntos_union.py <carpeta_salida>
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

# una pantalla de prueba de 1920×1080 (como test_barra_sin_cortes): sin ella la «offscreen» mide ~800–1000 px, la
# ventana no llega a 1600 y a 120 px/s la unión de 5,95 s quedaba fuera de la línea de tiempo
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_union_{os.getpid()}.json"
with open(os.path.join(_RAIZ, _CFG), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"dpr": 1}]}')
__import__("atexit").register(lambda: os.path.exists(os.path.join(_RAIZ, _CFG)) and os.remove(os.path.join(_RAIZ, _CFG)))
os.chdir(_RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QScrollBar  # noqa: E402

QMenu.exec = lambda self, *a: None


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
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "puntos_union")
    os.makedirs(out, exist_ok=True)
    capturas = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp",
                            "timeline_fase1b")
    os.makedirs(capturas, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui.timeline import TimelineWidget
    apply_dark_theme(app)

    # un video con su voz: tono con silencios en [2, 3], [5, 6] y [8, 9] s
    vid = os.path.join(out, "voz_con_silencios.mp4")
    if not os.path.exists(vid):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=12", "-f", "lavfi", "-i", "sine=f=440:d=12", "-af",
                        "volume=enable='between(t,2,3)+between(t,5,6)+between(t,8,9)':volume=0",
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
    # lo que deja «Eliminar silencio»: piezas del mismo archivo, pegadas, con saltos en el archivo
    piezas = [(0.0, 0.0, 2.05),        # unión 1 (2.05 → 2.95): en silencio por los dos lados → gris / gris
              (2.05, 2.95, 1.55),      # unión 2 (4.50 → 5.95): la voz suena al final de la izquierda → rojo / gris
              (3.60, 5.95, 2.35),      # unión 3 (8.30 → 8.95): «palabra» (7.6–8.6) sigue tras el corte → rojo / gris
              (5.95, 8.95, 2.00)]
    ctrl.insert_ranges([{"media_id": mid, "start": a, "source_in": s, "duration": d} for a, s, d in piezas],
                       v1.id, "Piezas")
    assert ctrl.ensure_peaks(mid, wait=True) is not None, "sin forma de onda"   # (la de la línea de tiempo)
    ctrl.project.transcripts[mid] = {"words": [[7.6, 8.6, "palabra"]], "segments": []}
    ctrl.transcript_changed.emit(mid)
    pump(app, 0.3)
    p = ctrl.project
    a1 = next(c.track_id for c in p.clips.values() if p.track(c.track_id).kind == TRACK_AUDIO)

    def piezas_de(tid):
        return sorted(ctrl.project.clips_on(tid), key=lambda c: c.start)

    def foto():
        return sorted((c.id, round(c.start, 6), round(c.duration, 6), round(c.source_in, 6))
                      for c in ctrl.project.clips.values())

    msgs = []
    ctrl.message.connect(lambda m: msgs.append(m))

    # 0) botón ◉ y casilla: a la par y recordados
    chk = win.chk_puntos_union
    btn = tl._dots_button()
    tl.set_union_dots(False)                  # (la copia de tus ajustes puede traerlos encendidos)
    assert not tl.union_dots and not chk.isChecked() and not btn.isChecked()
    btn.click()
    pump(app, 0.05)
    assert tl.union_dots and chk.isChecked() and btn.isChecked()
    assert str(QSettings("EditorIA", "EditorIA").value("timeline/puntos_union")) == "true"
    chk.setChecked(False)
    assert not tl.union_dots and not btn.isChecked()
    assert str(QSettings("EditorIA", "EditorIA").value("timeline/puntos_union")) == "false"
    chk.setChecked(True)
    assert tl.union_dots and btn.isChecked()
    otro = TimelineWidget(ctrl, QScrollBar())
    assert otro.union_dots, "se recuerda (otra línea de tiempo nueva lo lee)"
    otro.deleteLater()
    g = btn.geometry()
    add = tl._corner_buttons()[0].geometry()
    assert g.left() >= add.right() and g.width() >= 14, (g, add)
    assert btn.toolTip() and chk.toolTip()
    print("✓ botón ◉ (a la derecha de «➕ Pista») y casilla de «4 · Cortes de audio»: van a la par y se recuerdan")

    # 1) rojo donde parece cortada; gris en las uniones limpias
    tl.pps, tl.scroll = 120.0, 0.0
    tl._update_scrollbar()
    pump(app, 0.2)
    tl.repaint()
    pts = {(round(j["t"], 3), lado): (x, y, rojo, est, mot) for j, lado, x, y, rojo, est, mot in tl._union_puntos()}
    assert len(pts) == 6, (sorted(pts), [(round(j["t"], 3), round(j["out"], 3), round(j["in"], 3)) for j in
                                          tl._union_juntas()[0]],
                           [(round(c.start, 3), round(c.duration, 3), round(c.source_in, 3)) for c in piezas_de(a1)],
                           tl.width(), tl.x_for(5.95))
    esperado = {(2.05, "arriba"): False, (2.05, "abajo"): False, (3.6, "arriba"): True, (3.6, "abajo"): False,
                (5.95, "arriba"): True, (5.95, "abajo"): False}
    got = {k: v[2] for k, v in pts.items()}
    assert got == esperado, got
    assert "palabra" in pts[(5.95, "arriba")][4], pts[(5.95, "arriba")]
    ia = ctrl.project.track_index(a1)                   # el de ARRIBA, a media altura (no tapa el nombre ni las
    ty_a, th_a = tl.track_y(ia), tl.track_h(ia)         # palabras sobre la onda); el de abajo, abajo
    assert abs(pts[(2.05, "arriba")][1] - (ty_a + th_a / 2)) <= 1.5, (pts[(2.05, "arriba")][1], ty_a, th_a)
    assert pts[(2.05, "abajo")][1] > ty_a + th_a * 0.75, (pts[(2.05, "abajo")][1], ty_a, th_a)
    assert cerca(pts[(5.95, "arriba")][3], 5.95 + (8.6 - 8.3), 1e-6), pts[(5.95, "arriba")][3]
    est2 = pts[(3.6, "arriba")][3]
    assert est2 is not None and 3.6 + 0.45 <= est2 <= 3.6 + 0.56, est2      # (la voz calla a los 5.0 s del archivo)
    img = tl.grab().toImage()
    for k, rojo in esperado.items():
        x, y = pts[k][0], pts[k][1]
        c = img.pixelColor(int(round(x)), int(round(y)))
        es_rojo = c.red() > 200 and c.green() < 120
        assert es_rojo == rojo, (k, c.name())
    tl.grab().copy(0, 0, min(tl.width(), 1600), min(tl.height(), 300)).save(os.path.join(capturas, "puntos.png"))
    print("✓ rojo donde la palabra sigue tras el corte o la voz suena en el borde; gris discreto en las uniones limpias")

    def mover(x, y, mods=Qt.NoModifier):
        ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))),
                         Qt.LeftButton, Qt.LeftButton, mods)
        tl.mouseMoveEvent(ev)

    def arrastrar(k, dx, captura=None, alt=False):
        x, y = pts[k][0], pts[k][1]
        mods = Qt.AltModifier if alt else Qt.NoModifier          # (Alt + arrastrar = quitar audio)
        QTest.mousePress(tl, Qt.LeftButton, mods, QPoint(int(round(x)), int(round(y))))
        assert (tl._drag or {}).get("type") == "union_dot", tl._drag
        mover(x + dx / 2, y, mods)
        mover(x + dx, y, mods)
        d = dict(tl._drag)
        if captura:
            tl.repaint()
            tl.grab().copy(0, 0, min(tl.width(), 1600), min(tl.height(), 300)).save(os.path.join(capturas, captura))
        QTest.mouseRelease(tl, Qt.LeftButton, mods, QPoint(int(round(x + dx)), int(round(y))))
        pump(app, 0.1)
        return d

    tres = 3 / FPS * tl.pps                                    # 3 fotogramas, en píxeles
    # 2) punto de arriba de la unión 1: +3 fotogramas
    antes = foto()
    from types import SimpleNamespace as _NS        # (copias de los valores: los clips se modifican en su sitio)

    def valores(tid):
        return [_NS(start=c.start, duration=c.duration, source_in=c.source_in) for c in piezas_de(tid)]
    A0, V0 = valores(a1), valores(v1.id)
    d = arrastrar((2.05, "arriba"), tres + 1, "arrastre_mas3.png")
    assert tl._union_frames(d) == 3 and not d["iman"], d
    vista = d.get("vista") or {}                        # 🔴 en vivo (antes de soltar): la pieza ya crecía y lo de
    assert A0 and abs(vista[piezas_de(a1)[0].id].duration - (A0[0].duration + 0.1)) < 1e-6, vista   # detrás se movía
    assert abs(vista[piezas_de(a1)[1].id].start - (A0[1].start + 0.1)) < 1e-6
    assert abs(vista[piezas_de(v1.id)[1].id].start - (V0[1].start + 0.1)) < 1e-6, "el video de detrás también"
    A, V = piezas_de(a1), piezas_de(v1.id)
    for X, X0 in ((A, A0), (V, V0)):
        assert cerca(X[0].duration, X0[0].duration + 0.1) and cerca(X[0].source_in, X0[0].source_in), (X[0].duration, X0[0].duration, d, msgs[-3:])
        for c, c0 in zip(X[1:], X0[1:]):
            assert cerca(c.start, c0.start + 0.1) and cerca(c.source_in, c0.source_in) and cerca(c.duration, c0.duration)
    for a, v in zip(A, V):
        assert cerca(a.start, v.start) and cerca(a.duration, v.duration) and cerca(a.source_in, v.source_in)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes, "un Ctrl+Z lo deja como estaba"
    print("✓ punto de arriba +3 fotogramas: la pieza crece 0.100 s, lo de detrás se recorre eso con su contenido intacto, "
          "el video igual; un Ctrl+Z")

    # 3) punto de abajo de la unión 1: +3 fotogramas (hacia la izquierda = más audio al principio de la derecha)
    d = arrastrar((2.05, "abajo"), -(tres + 1))
    assert tl._union_frames(d) == 3, d
    A, V = piezas_de(a1), piezas_de(v1.id)
    for X, X0 in ((A, A0), (V, V0)):
        assert cerca(X[0].start, X0[0].start) and cerca(X[0].duration, X0[0].duration)
        assert cerca(X[1].start, X0[1].start) and cerca(X[1].duration, X0[1].duration + 0.1)
        assert cerca(X[1].source_in, X0[1].source_in - 0.1)
        for c, c0 in zip(X[2:], X0[2:]):
            assert cerca(c.start, c0.start + 0.1) and cerca(c.source_in, c0.source_in) and cerca(c.duration, c0.duration)
    for a, v in zip(A, V):
        assert cerca(a.start, v.start) and cerca(a.duration, v.duration) and cerca(a.source_in, v.source_in)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes
    print("✓ punto de abajo +3 fotogramas: la pieza de la derecha gana 0.100 s por delante sin moverse, lo de detrás se "
          "recorre eso, el video igual; un Ctrl+Z")

    # 3b) 23/11: el SENTIDO decide, sea cual sea el punto; arrastrar nunca quita audio (solo con Alt)
    def dura():
        return [round(c.duration, 4) for c in piezas_de(a1)]
    D0 = dura()
    d = arrastrar((2.05, "arriba"), -(tres + 1))               # punto de ARRIBA hacia ← = principio de la derecha
    assert d["cid"] == piezas_de(a1)[1].id and d["edge"] == "left" and tl._union_frames(d) == 3, d
    assert cerca(dura()[0], D0[0]) and cerca(dura()[1], D0[1] + 0.1) and cerca(piezas_de(a1)[2].start, A0[2].start + 0.1)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes
    d = arrastrar((2.05, "abajo"), tres + 1)                   # punto de ABAJO hacia → = final de la izquierda
    assert d["cid"] == piezas_de(a1)[0].id and d["edge"] == "right" and tl._union_frames(d) == 3, d
    assert cerca(dura()[0], D0[0] + 0.1) and cerca(dura()[1], D0[1])
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes
    for k_, dx_, quien in (((2.05, "arriba"), -(tres + 1), 0), ((2.05, "abajo"), tres + 1, 1)):
        d = arrastrar(k_, dx_, alt=True)                        # Alt: ← quita del final de la izquierda, → del principio
        assert tl._union_frames(d) == -3 and cerca(dura()[quien], D0[quien] - 0.1), (k_, d, dura())
        ctrl.undo_stack.undo()
        pump(app, 0.05)
        assert foto() == antes
    print("✓ el sentido decide: ← recupera el principio de la derecha y → el final de la izquierda desde cualquiera de "
          "los dos puntos; arrastrar nunca quita audio, Alt + arrastrar sí; un Ctrl+Z cada uno")

    # 4) el imán: cerca del final estimado de la palabra, se pega (al fotograma de después)
    tl.repaint()
    pts = {(round(j["t"], 3), lado): (x, y, rojo, est, mot) for j, lado, x, y, rojo, est, mot in tl._union_puntos()}
    k = (5.95, "arriba")
    destino = tl._union_snap(pts[k][3], "arriba")
    dx = tl.x_for(destino) - pts[k][0] - 5                      # (5 px antes: dentro del imán)
    d = arrastrar(k, dx, "iman.png")
    assert d["iman"] and cerca(d["t"], destino), d
    P3 = piezas_de(a1)[2]
    assert cerca(P3.end, destino) and P3.end >= pts[k][3] - 1e-6, (P3.end, destino)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes
    print(f"✓ el imán se pega al final estimado de «palabra» ({destino:.3f} s, +{round((destino - 5.95) * FPS)} "
          "fotogramas) y la palabra queda entera")

    # 4b) desfase: una capa de escena en otra pista que CRUZA la unión (con +3 se queda quieta) → avisa y no toca nada;
    #     con −3 ese tramo sale también de ella y la escena sigue en sincronía
    from editoria.core import scenes
    with ctrl.sin_abrir_editor():
        ctrl.add_text(1.5, 1.0, "rótulo")
    rot = next(c for c in ctrl.project.clips.values() if c.text is not None)
    p3_id = piezas_de(a1)[2].id

    def marcar(pp):
        pp.clips[rot.id].note = scenes.PREFIJO + "e1"
        pp.clips[p3_id].note = scenes.PREFIJO + "e1"
    ctrl._edit("escena de prueba", marcar)
    con_escena = foto()
    tl.repaint()
    pts = {(round(j["t"], 3), lado): (x, y, rojo, est, mot) for j, lado, x, y, rojo, est, mot in tl._union_puntos()}
    msgs.clear()
    arrastrar((2.05, "arriba"), tres + 1)
    assert foto() == con_escena and msgs and "desincron" in msgs[-1], msgs
    msgs.clear()
    rot_dur = ctrl.project.clips[rot.id].duration
    p3_ini = piezas_de(a1)[2].start
    arrastrar((2.05, "arriba"), -(tres + 1), alt=True)
    assert foto() != con_escena and not msgs, msgs
    capas = [c for c in ctrl.project.clips.values() if c.text is not None]
    assert cerca(sum(c.duration for c in capas), rot_dur - 0.1), [(c.start, c.duration) for c in capas]
    assert cerca(piezas_de(a1)[2].start, p3_ini - 0.1)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == con_escena
    while foto() != antes and ctrl.undo_stack.canUndo():
        ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes
    print("✓ una capa de escena que cruza la unión en otra pista: con +3 se desfasaría → avisa y no toca nada; con −3 "
          "ese tramo sale también de ella y sigue en sincronía")

    # 4c) TODAS las pistas: narración en 3 piezas + 2 subtítulos + 2 B-roll SIN vincular, después de lo anterior
    O = 20.0                                                    # (lejos de las piezas de arriba: no se tocan)
    voz = os.path.join(out, "voz_larga.wav")
    musica = os.path.join(out, "musica.wav")
    broll_v = os.path.join(out, "broll_sin_sonido.mp4")
    for ruta, args in ((voz, ["-f", "lavfi", "-i", "sine=f=220:d=30"]),
                       (musica, ["-f", "lavfi", "-i", "sine=f=880:d=15"]),
                       (broll_v, ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=10", "-an", "-c:v", "libx264",
                                  "-preset", "ultrafast"])):
        if not os.path.exists(ruta):
            subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y"] + args + [ruta], check=True)
    mvoz, mmus, mbr = ctrl.import_now([voz, musica, broll_v])
    while ctrl.analyzing:
        pump(app, 0.1)
    base_n = ctrl.undo_stack.index()

    def pista_nueva(kind):
        ya = {t.id for t in ctrl.project.tracks}
        ctrl.add_track(kind)
        return next(t.id for t in ctrl.project.tracks if t.id not in ya)
    an = pista_nueva(TRACK_AUDIO)
    ctrl.insert_ranges([{"media_id": mvoz, "start": O + a, "source_in": s, "duration": d}
                        for a, s, d in ((0.0, 0.0, 2.0), (2.0, 3.0, 3.0), (5.0, 7.0, 4.0))], an, "Narración")
    ctrl.project.transcripts[mvoz] = {"words": [[0.2, 1.0, "hola"]], "segments": []}
    vb = pista_nueva(TRACK_VIDEO)
    ctrl.insert_ranges([{"media_id": mbr, "start": O + 3.0, "source_in": 1.0, "duration": 1.5},
                        {"media_id": mbr, "start": O + 6.0, "source_in": 4.0, "duration": 2.0}], vb, "B-roll", volume=0.0)
    with ctrl.sin_abrir_editor():
        ctrl.add_text(O + 2.5, 1.0, "subtítulo uno")
        ctrl.add_text(O + 5.5, 1.0, "subtítulo dos")
    pump(app, 0.2)
    P = ctrl.project
    nar = piezas_de(an)
    subs = sorted((c for c in P.clips.values() if c.text is not None), key=lambda c: c.start)
    brs = sorted((c for c in P.clips.values() if c.media_id == mbr), key=lambda c: c.start)
    assert len(nar) == 3 and len(subs) == 2 and len(brs) == 2 and not any(c.link for c in brs), (nar, subs, brs)
    encima = [c.id for c in subs + brs]
    base4 = foto()

    def suena(cid):
        """qué segundo del ARCHIVO de la narración suena donde empieza ese clip (None: ahí no hay narración)"""
        c = ctrl.project.clips[cid]
        for n in ctrl.project.clips_on(an):
            if n.start - 1e-9 <= c.start < n.end - 1e-9:
                return round(n.source_in + (c.start - n.start), 4)
        return None

    def mapa():
        return {i: (suena(i), round(ctrl.project.clips[i].duration, 6), round(ctrl.project.clips[i].source_in, 6))
                for i in encima}
    m0 = mapa()
    assert all(v[0] is not None for v in m0.values()), m0
    N0 = valores(an)
    t3 = 3 / FPS
    casos = []                                    # (nombre, pieza, borde, t, crece la pieza k, lo de detrás desde k)
    for k_u, u in ((0, O + 2.0), (1, O + 5.0)):
        izq, der = nar[k_u].id, nar[k_u + 1].id
        casos += [(f"unión {k_u + 1} arriba +3", izq, "right", u + t3, k_u, +1),
                  (f"unión {k_u + 1} arriba −3", izq, "right", u - t3, k_u, -1),
                  (f"unión {k_u + 1} abajo +3", der, "left", u - t3, k_u + 1, +1),
                  (f"unión {k_u + 1} abajo −3", der, "left", u + t3, k_u + 1, -1)]
    for nombre, cid, edge, t, k, sg in casos:
        msgs.clear()
        n0 = ctrl.undo_stack.index()
        ctrl.ripple_trim_sincro(cid, edge, t)
        pump(app, 0.02)
        assert not msgs and ctrl.undo_stack.index() - n0 == 1, (nombre, msgs)
        N = piezas_de(an)
        assert len(N) == 3, nombre
        dd = sg * 0.1
        for j, (c, c0) in enumerate(zip(N, N0)):
            if j < k:
                assert cerca(c.start, c0.start) and cerca(c.duration, c0.duration) and cerca(c.source_in, c0.source_in)
            elif j == k:
                si = c0.source_in - dd if edge == "left" else c0.source_in
                assert cerca(c.start, c0.start) and cerca(c.duration, c0.duration + dd) and cerca(c.source_in, si), \
                    (nombre, c.start, c.duration, c.source_in)
            else:
                assert cerca(c.start, c0.start + dd) and cerca(c.duration, c0.duration) and \
                    cerca(c.source_in, c0.source_in), (nombre, j, c.start)
        assert mapa() == m0, (nombre, "algo de encima quedó corrido respecto a la voz", m0, mapa())
        ctrl.undo_stack.undo()
        pump(app, 0.02)
        assert foto() == base4, f"{nombre}: un Ctrl+Z no lo deja como estaba"
    print("✓ narración en 3 piezas + 2 subtítulos + 2 B-roll sin vincular: +3 y −3, arriba y abajo, en la 1.ª y la 2.ª "
          "unión → la pieza cambia 3 fotogramas, lo de detrás se recorre en TODAS las pistas y todo sigue sobre la "
          "misma palabra; un Ctrl+Z cada uno")

    # un arrastre de verdad en la 2.ª unión (punto de abajo, −3)
    assert ctrl.ensure_peaks(mvoz, wait=True) is not None, "sin forma de onda de la narración"
    tl.pps, tl.scroll = 120.0, O - 1.0
    tl._update_scrollbar()
    pump(app, 0.2)
    tl.repaint()
    pts = {(round(j["t"], 3), lado): (x, y, rojo, est, mot) for j, lado, x, y, rojo, est, mot in tl._union_puntos()}
    msgs.clear()
    d = arrastrar((round(O + 5.0, 3), "abajo"), tres + 1, alt=True)
    assert tl._union_frames(d) == -3 and not msgs, (d, msgs)
    assert cerca(piezas_de(an)[2].duration, N0[2].duration - 0.1) and mapa() == m0, mapa()
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base4
    print("✓ arrastre de verdad del punto de abajo con Alt −3 en la 2.ª unión: subtítulos y B-roll siguen sobre la misma palabra")

    # un texto bloqueado detrás (otra pista): avisa y no toca nada, con +3 y con −3
    ctrl._edit("bloquear subtítulo", lambda pp: setattr(pp.clips[subs[1].id], "locked", True))
    bloq = foto()
    for t, que in ((O + 2.0 + t3, "+3"), (O + 2.0 - t3, "−3")):
        msgs.clear()
        ctrl.ripple_trim_sincro(nar[0].id, "right", t)
        assert foto() == bloq and msgs and "🔒" in msgs[-1], (que, msgs)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == base4
    print(f"✓ un texto bloqueado detrás en otra pista: +3 y −3 avisan y no tocan nada («{msgs[-1][:50]}…»)")

    # una música que CRUZA la unión (otra pista): con +3 se queda quieta y entera; lo de detrás se recorre igual
    am = pista_nueva(TRACK_AUDIO)
    (mus,) = ctrl.insert_ranges([{"media_id": mmus, "start": O + 1.0, "source_in": 2.0, "duration": 6.0}], am, "Música")
    con_mus = foto()
    M0 = (ctrl.project.clips[mus].start, ctrl.project.clips[mus].duration, ctrl.project.clips[mus].source_in)
    msgs.clear()
    ctrl.ripple_trim_sincro(nar[0].id, "right", O + 2.0 + t3)
    mc = ctrl.project.clips[mus]
    assert not msgs and (mc.start, mc.duration, mc.source_in) == M0, (msgs, M0, (mc.start, mc.duration, mc.source_in))
    assert len(ctrl.project.clips_on(am)) == 1 and mapa() == m0
    assert cerca(piezas_de(an)[1].start, N0[1].start + 0.1)
    ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == con_mus
    print("✓ una música que cruza la unión: con +3 se queda quieta y entera (sin partirse); lo de detrás se recorre")
    while ctrl.undo_stack.index() > base_n:
        ctrl.undo_stack.undo()
    pump(app, 0.05)
    assert foto() == antes

    # 5) 500 uniones → el pintado sigue fluido
    ctrl.add_track(TRACK_VIDEO)
    vtracks = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO]
    v_otro = next(t for t in vtracks if t.id != v1.id)
    items = [{"media_id": mid, "start": 10.0 + i * 0.2, "source_in": round((i * 0.3) % 11.0, 3), "duration": 0.2}
             for i in range(540)]
    ctrl.insert_ranges(items, v_otro.id, "500 uniones")
    pump(app, 0.5)
    n_j = len(tl._union_juntas()[0])
    assert n_j >= 500, n_j
    tl.pps = max(8.0, (tl.width() - tl.HEADER_W - 20) / 109.0)
    tl.scroll = 10.0
    tl._update_scrollbar()
    pump(app, 0.2)

    def medir():
        tl.repaint()                                            # (calienta memorias)
        ts = []
        for _ in range(4):
            a = time.perf_counter()
            for _ in range(5):
                tl.repaint()
            ts.append((time.perf_counter() - a) / 5 * 1000)
        return min(ts)
    tl.set_union_dots(False)
    sin = medir()
    tl.set_union_dots(True)
    t_primero = time.perf_counter()
    tl.__dict__.pop("_union_memo", None)
    tl.repaint()
    primero = (time.perf_counter() - t_primero) * 1000
    con = medir()
    vis = len(tl._union_puntos(*tl._vis)) // 2
    tl.grab().copy(0, 0, min(tl.width(), 1600), min(tl.height(), 400)).save(os.path.join(capturas, "500_uniones.png"))
    print(f"  {vis} uniones a la vista: pintado {sin:.1f} ms sin puntos · {con:.1f} ms con puntos · el primero (calcula "
          f"todas) {primero:.0f} ms")
    assert con <= sin * 1.10, f"el pintado empeora más de un 10 %: {sin:.1f} → {con:.1f} ms"
    assert primero < 400, primero
    print(f"✓ {vis} uniones a la vista: el pintado no empeora más de un 10 % ({sin:.1f} → {con:.1f} ms)")
    # arrastrar un punto con la vista previa en vivo: cada movimiento repinta solo de la unión a la derecha
    pts5 = [pt for pt in tl._union_puntos(*tl._vis) if pt[1] == "arriba"]
    j5, _l, x5, y5 = pts5[len(pts5) // 2][:4]
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(x5)), int(round(y5))))
    assert (tl._drag or {}).get("type") == "union_dot", tl._drag
    ts_mov = []
    for k in range(1, 9):
        a_ = time.perf_counter()
        mover(x5 + k * 2.0, y5)
        app.processEvents()
        ts_mov.append((time.perf_counter() - a_) * 1000)
    assert tl._drag.get("vista"), "vista previa en vivo"
    mover(x5, y5)                                       # (vuelve a su sitio: al soltar no cambia nada)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(x5)), int(round(y5))))
    pump(app, 0.05)
    mov = sorted(ts_mov)[len(ts_mov) // 2]
    print(f"  arrastrar un punto con vista previa: {mov:.1f} ms por movimiento (repintar todo: {sin:.1f} ms)")
    assert mov <= sin * 1.10, f"el arrastre en vivo no puede costar más que repintar todo: {mov:.1f} > {sin:.1f} ms"
    print("✓ arrastrar un punto con la vista previa en vivo cuesta como mucho un repintado")

    ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
