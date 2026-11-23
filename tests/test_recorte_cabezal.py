"""
✂ PRUEBA de la fase 1 de la línea de tiempo (20/11): recortar hasta el cabezal y moverse entre cortes.
  · Q / W (con cierre de hueco): en un clip suelto, con su audio vinculado, con una pista bloqueada, con canales elegidos
    y sin nada elegido (el tramo sale de todas las pistas; si cortaría tu narración, avisa y no toca nada) → duración y
    sincronía exactas al fotograma, el cabezal donde toca y un solo Ctrl+Z cada uno;
  · ↑ / ↓ recorren todos los cortes (con la línea de tiempo enfocada; en una lista, las flechas siguen siendo suyas);
  · Y / Alt+Y eligen lo que hay desde el cabezal hacia delante / atrás;
  · los atajos nuevos no chocan con ninguno de los que ya había.
Ejecutar:  .venv/Scripts/python.exe tests/test_recorte_cabezal.py <carpeta_salida>
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None          # (ninguna prueba de aquí abre menús; esto es solo por si acaso)


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


def fr(t: float) -> float:
    return round(t * FPS) / FPS


def cerca(a, b, tol=1e-6):
    return abs(a - b) <= tol


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "recorte_cabezal")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    vid = os.path.join(out, "v.mp4")
    voz = os.path.join(out, "voz.wav")
    if not os.path.exists(vid):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=10",
                        "-f", "lavfi", "-i", "sine=f=440:d=10", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                        "-shortest", vid], check=True)
    if not os.path.exists(voz):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", voz],
                       check=True)

    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.8)
    ctrl, tl, eng = win.ctrl, win.timeline, win.engine
    ctrl.project.fps = FPS
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([mid], v1.id, 0.0)
    ctrl.split(4.0)                                   # A [0, 4) y B [4, 10), cada uno con su sonido vinculado
    p = ctrl.project
    a1 = next(c.track_id for c in p.clips.values() if p.track(c.track_id).kind == TRACK_AUDIO)
    ctrl.add_text(20.0, 3.0, "Uno")
    ctrl.add_text(23.0, 3.0, "Dos")
    pump(app, 0.3)
    txt = next(c.track_id for c in p.clips.values() if c.text is not None)
    assert p.track(txt).kind == TRACK_TEXT
    tl.linked = True
    tl.setFocus()

    def clips(tid):
        return sorted(ctrl.project.clips_on(tid), key=lambda c: c.start)

    def foto():
        return sorted((c.id, round(c.start, 6), round(c.duration, 6), round(c.source_in, 6), c.track_id, c.link)
                      for c in ctrl.project.clips.values())

    def desfases():
        """Parejas vinculadas que ya no empiezan igual o no muestran el mismo segundo del archivo."""
        porl = {}
        for c in ctrl.project.clips.values():
            if c.link:
                porl.setdefault(c.link, []).append(c)
        return [[(round(c.start, 4), round(c.source_in, 4)) for c in cs] for cs in porl.values()
                if len(cs) == 2 and (abs(cs[0].start - cs[1].start) > 1e-6 or abs(cs[0].source_in - cs[1].source_in) > 1e-6)]

    def volver_a(estado):
        while foto() != estado and ctrl.undo_stack.canUndo():
            ctrl.undo_stack.undo()
        pump(app, 0.05)
        assert foto() == estado, "deshaciendo no vuelve al estado de antes"

    def tecla(k, mod=Qt.NoModifier):
        tl.setFocus()
        QTest.keyClick(tl, k, mod)
        pump(app, 0.05)

    def poner_cabezal(t):
        eng.user_seek(t)
        tl.set_playhead(t)

    def deshacer_igual(antes, que):
        ctrl.undo_stack.undo()
        pump(app, 0.05)
        assert foto() == antes, f"un Ctrl+Z no lo dejó como estaba ({que})"

    # 0) los atajos nuevos existen y no chocan con nada
    seqs = {}
    for key, (a, _d) in win.shortcut_actions.items():
        for sq in a.shortcuts():
            s = sq.toString(QKeySequence.PortableText)
            if s:
                assert s not in seqs, f"«{s}» lo usan «{seqs[s]}» y «{key}»"
                seqs[s] = key
    for s in ("Q", "W", "Y", "Alt+Y", "Up", "Down"):
        assert s in seqs, (s, "sin acción")
    print("✓ Q, W, Y, Alt+Y, ↑ y ↓ tienen su orden (en ⌨ Personalizar atajos) y no chocan con ningún otro atajo")

    # 1) clip suelto (texto): Q y W, lo de detrás se recorre, un Ctrl+Z
    uno, dos = clips(txt)
    antes = foto()
    tl.set_selection([uno.id])
    poner_cabezal(21.013)
    tecla(Qt.Key_Q)
    t = fr(21.013)
    uno2, dos2 = clips(txt)
    assert cerca(uno2.start, 20.0) and cerca(uno2.duration, 3.0 - (t - 20.0)), (uno2.start, uno2.duration)
    assert cerca(dos2.start, 23.0 - (t - 20.0)), dos2.start
    assert cerca(eng.time, 20.0), f"el cabezal vuelve al inicio del clip: {eng.time}"
    deshacer_igual(antes, "Q en texto")
    poner_cabezal(21.5)
    tl.set_selection([uno.id])
    tecla(Qt.Key_W)
    uno2, dos2 = clips(txt)
    assert cerca(uno2.duration, 1.5) and cerca(dos2.start, 21.5), (uno2.duration, dos2.start)
    assert cerca(eng.time, 21.5)
    deshacer_igual(antes, "W en texto")
    print("✓ clip suelto: Q quita lo de antes del cabezal (al fotograma) y W lo de después; lo de detrás se recorre; "
          "un Ctrl+Z cada uno")

    # 2) video con su audio vinculado: los dos igual, sincronía exacta
    va, vb = clips(v1.id)
    aa, ab = clips(a1)
    tl.set_selection([va.id])
    poner_cabezal(1.517)
    tecla(Qt.Key_Q)
    t = fr(1.517)
    va2, vb2 = clips(v1.id)
    aa2, ab2 = clips(a1)
    for c in (va2, aa2):
        assert cerca(c.start, 0.0) and cerca(c.duration, 4.0 - t) and cerca(c.source_in, t), (c.start, c.duration,
                                                                                              c.source_in)
    for c in (vb2, ab2):
        assert cerca(c.start, 4.0 - t) and cerca(c.source_in, 4.0), (c.start, c.source_in)
    assert cerca(eng.time, 0.0)
    deshacer_igual(antes, "Q con audio vinculado")
    tl.set_selection([va.id])
    poner_cabezal(3.0)
    tecla(Qt.Key_W)
    va2, vb2 = clips(v1.id)
    aa2, ab2 = clips(a1)
    assert cerca(va2.duration, 3.0) and cerca(aa2.duration, 3.0) and cerca(vb2.start, 3.0) and cerca(ab2.start, 3.0)
    deshacer_igual(antes, "W con audio vinculado")
    print(f"✓ con su audio vinculado: imagen y sonido pierden lo mismo ({t:.4f} s) y lo de detrás se recorre igual en las "
          "dos pistas; un Ctrl+Z")

    # 3) pista del sonido bloqueada: no se toca nada (se desincronizaría) y se avisa
    msgs = []
    ctrl.message.connect(lambda m: msgs.append(m))
    ctrl.set_track_props(a1, "Bloquear", locked=True)
    antes_l = foto()
    tl.set_selection([va.id])
    poner_cabezal(2.0)
    tecla(Qt.Key_Q)
    assert foto() == antes_l, "con la pista del sonido bloqueada no debe cambiar nada"
    assert msgs and "🔒" in msgs[-1], msgs
    ctrl.undo_stack.undo()                            # (quita el bloqueo)
    pump(app, 0.05)
    assert foto() == antes and not ctrl.project.track(a1).locked
    print(f"✓ pista bloqueada: Q no toca nada y avisa («{msgs[-1][:60]}…»)")

    # 4) canales elegidos, sin clip elegido: solo en ese canal
    tl.set_selection([])
    tl.set_channels([txt])
    v_antes = [(c.start, c.duration) for c in clips(v1.id)]    # (valores de ahora: los objetos viejos ya no valen)
    poner_cabezal(24.0)
    tecla(Qt.Key_Q)
    uno2, dos2 = clips(txt)
    assert cerca(dos2.start, 23.0) and cerca(dos2.duration, 2.0) and cerca(uno2.duration, 3.0)
    assert [(c.start, c.duration) for c in clips(v1.id)] == v_antes
    deshacer_igual(antes, "Q en el canal elegido")
    tl.set_channels([])
    print("✓ con un canal elegido y ningún clip: el tramo lo marca ese canal (lo de antes no se mueve)")

    # 4b) (Fable) lo elegido no pasa por el cabezal / cabezal justo en el corte → aviso y nada
    for sel, t_, k_, que in (([vb.id], 4.0, Qt.Key_Q, "B elegido y cabezal justo en el corte A|B"),
                             ([va.id], 4.0, Qt.Key_W, "A elegido y cabezal justo en el corte A|B"),
                             ([va.id], 6.0, Qt.Key_Q, "A elegido pero el cabezal sobre B"),
                             ([], 4.0, Qt.Key_Q, "nada elegido y cabezal justo en el corte"),
                             ([], 15.0, Qt.Key_W, "nada elegido y cabezal en un hueco de la principal")):
        tl.set_selection(sel)
        poner_cabezal(t_)
        msgs.clear()
        tecla(k_)
        assert foto() == antes and msgs and "no recorto" in msgs[-1], (que, msgs)
    tl.set_selection([])
    tl.set_channels([v1.id])
    poner_cabezal(15.0)
    msgs.clear()
    tecla(Qt.Key_Q)
    assert foto() == antes and msgs, ("canal V1 con hueco bajo el cabezal", msgs)
    tl.set_channels([])
    print("✓ cabezal justo en un corte, lo elegido lejos del cabezal o hueco en la principal / el canal: avisa y no toca "
          "nada")

    # 4c) (Fable) corte en J: el sonido de A empieza 0,5 s más tarde que su imagen
    ctrl.trim_clip(clips(a1)[0].id, "left", 0.5, linked=False)
    en_j = foto()
    tl.set_selection([clips(v1.id)[0].id])
    poner_cabezal(2.0)
    tecla(Qt.Key_Q)
    assert foto() != en_j and not desfases(), desfases()
    vb2, ab2 = clips(v1.id)[1], clips(a1)[1]
    assert cerca(vb2.start, 2.0) and cerca(ab2.start, 2.0), (vb2.start, ab2.start)
    volver_a(antes)
    # 4d) vínculo de A roto: la pareja B (sí vinculada) sigue a la par
    ctrl.unlink_clips([clips(v1.id)[0].id])
    roto = foto()
    tl.set_selection([clips(v1.id)[0].id])
    poner_cabezal(2.0)
    tecla(Qt.Key_Q)
    assert foto() != roto and not desfases(), desfases()
    assert cerca(clips(v1.id)[1].start, clips(a1)[1].start)
    volver_a(antes)
    print("✓ corte en J y vínculo roto: Q quita el tramo de todas las pistas y ninguna pareja se desfasa")

    # 4e) (Fable) capas de una escena: Q en una capa recorta las dos igual
    from editoria.core import scenes
    ctrl.add_text(0.0, 4.0, "actor")
    actor = next(c for c in ctrl.project.clips.values() if c.text is not None and c.start < 1.0)
    nota_e = scenes.PREFIJO + "esc1"
    va_id = clips(v1.id)[0].id

    def marcar(pp):
        pp.clips[actor.id].note = nota_e
        pp.clips[va_id].note = nota_e
    ctrl._edit("escena de prueba", marcar)
    tl.set_selection([va_id])
    poner_cabezal(2.0)
    tecla(Qt.Key_Q)
    a2_, va2_ = ctrl.project.clips[actor.id], clips(v1.id)[0]
    assert cerca(a2_.duration, va2_.duration) and cerca(a2_.start, va2_.start), (a2_.duration, va2_.duration)
    volver_a(antes)
    print("✓ escena con dos capas: Q en una deja las dos con el mismo inicio y la misma duración")

    # 5) sin nada elegido: el tramo sale de TODAS las pistas (en sincronía)…
    tl.set_selection([])
    poner_cabezal(6.0)
    tecla(Qt.Key_Q)                                   # (clip de la pista principal: B [4, 10) → quita [4, 6))
    va2, vb2 = clips(v1.id)
    aa2, ab2 = clips(a1)
    assert cerca(vb2.start, 4.0) and cerca(vb2.duration, 4.0) and cerca(ab2.duration, 4.0) and cerca(vb2.source_in, 6.0)
    assert cerca(clips(txt)[0].start, 18.0), "los textos de detrás se recorren lo mismo"
    assert cerca(eng.time, 4.0)
    deshacer_igual(antes, "Q sin nada elegido")
    # …pero si cortaría tu narración (otra pista con transcripción), avisa y no toca nada
    (mvoz,) = ctrl.import_now([voz])
    while ctrl.analyzing:
        pump(app, 0.1)
    ctrl.add_track(TRACK_AUDIO)
    a_voz = [t_ for t_ in ctrl.project.tracks if t_.kind == TRACK_AUDIO][-1].id
    ctrl.add_media([mvoz], a_voz, 0.0)
    ctrl.project.transcripts[mvoz] = {"words": [], "segments": []}     # (cuenta como narración)
    tl.set_selection([])
    antes_v = foto()
    msgs.clear()
    poner_cabezal(6.0)
    tecla(Qt.Key_Q)
    assert foto() == antes_v and msgs and "narración" in msgs[-1], msgs
    # (Fable) B elegido y cabezal justo en el corte, con la narración debajo: nada
    tl.set_selection([clips(v1.id)[1].id])
    poner_cabezal(4.0)
    msgs.clear()
    tecla(Qt.Key_Q)
    assert foto() == antes_v and msgs, msgs
    # (Fable) narración ELEGIDA con B-roll y texto encima: se recorta y lo de encima se mueve con ella
    ctrl.add_text(5.0, 2.0, "subtítulo")
    sub = next(c for c in ctrl.project.clips.values() if c.text is not None and abs(c.start - 5.0) < 1e-6)
    con_sub = foto()
    nar = clips(a_voz)[0]
    tl.set_selection([nar.id])
    poner_cabezal(2.0)
    tecla(Qt.Key_Q)
    nar2, sub2 = clips(a_voz)[0], ctrl.project.clips[sub.id]
    suena = nar2.source_in + (sub2.start - nar2.start)
    assert cerca(suena, 5.0), f"el texto que iba sobre el segundo 5 de la voz queda sobre el {suena:.3f}"
    assert cerca(clips(v1.id)[1].start, 2.0) and not desfases(), (clips(v1.id)[1].start, desfases())
    volver_a(con_sub)
    print("✓ sin nada elegido: el tramo sale de todas las pistas a la vez; si cortaría la narración (o el cabezal está "
          "en un corte), avisa y no toca nada; con la narración ELEGIDA se recorta y la imagen y los textos de encima se "
          "mueven con ella")

    # 6) ↑ / ↓ recorren todos los cortes (con la línea de tiempo enfocada)
    pts = ctrl.edit_points()
    poner_cabezal(0.0)
    visto = []
    for _ in range(len(pts) + 2):
        tecla(Qt.Key_Down)
        if visto and cerca(eng.time, visto[-1]):
            break
        visto.append(round(eng.time, 6))
    assert visto == [round(x, 6) for x in pts if x > 1e-6], (visto, pts)
    atras = []
    for _ in range(len(pts) + 2):
        tecla(Qt.Key_Up)
        if atras and cerca(eng.time, atras[-1]):
            break
        atras.append(round(eng.time, 6))
    assert atras == list(reversed([0.0] + visto[:-1])), (atras, visto)
    # en una lista, ↓ sigue siendo de la lista
    lista = QListWidget(win)
    lista.addItems(["uno", "dos", "tres"])
    lista.setCurrentRow(0)
    lista.show()
    lista.setFocus()
    t_antes = eng.time
    QTest.keyClick(lista, Qt.Key_Down)
    pump(app, 0.05)
    assert lista.currentRow() == 1 and cerca(eng.time, t_antes), (lista.currentRow(), eng.time)
    lista.deleteLater()
    print(f"✓ ↓ recorre los {len(visto)} cortes en orden y ↑ vuelve hasta el inicio; en una lista, ↓ sigue siendo de la "
          "lista")

    # 7) Y / Alt+Y
    poner_cabezal(5.0)
    tecla(Qt.Key_Y)
    pp = ctrl.project
    delante = {c.id for c in pp.clips.values() if c.end > 5.0 + 1e-6}
    assert set(tl.selected) == delante, (len(tl.selected), len(delante))
    tecla(Qt.Key_Y, Qt.AltModifier)
    detras = {c.id for c in pp.clips.values() if c.start < 5.0 - 1e-6}
    assert set(tl.selected) == detras, (len(tl.selected), len(detras))
    tl.set_channels([txt])
    tecla(Qt.Key_Y)
    assert set(tl.selected) == {c.id for c in clips(txt)}
    tl.set_channels([])
    print(f"✓ Y elige los {len(delante)} clips desde el cabezal hacia delante, Alt+Y los {len(detras)} de detrás; con un "
          "canal elegido, solo los de ese canal")

    ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
