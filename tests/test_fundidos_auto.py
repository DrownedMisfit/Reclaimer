"""
〰 PRUEBA de la fase 3 de la línea de tiempo (20/11): volumen visible y fundidos solos.
  · cada unión de voz (trozos pegados con un salto en el archivo) lleva 2 fotogramas de fundido a cada lado; un corte
    sin salto (dividir) no lleva nada; tras «Eliminar silencio», todas las uniones con fundido;
  · música (bordes libres): fundido corto; sonido del B-roll: 4 fotogramas; voz al principio y efectos cortos: nada;
  · en el visor (fade_gain) y en la exportación: sin chasquido (el salto entre muestras en la unión, como el de un
    tono continuo); sin la regla, el chasquido de siempre;
  · la casilla «Fundidos automáticos» (Limpieza y mezcla → 4 · Cortes de audio): apagada quita todos (un Ctrl+Z) y
    queda como antes; tus fundidos no se tocan;
  · la línea de volumen se ve siempre en los audios y se arrastra sin el modo 〰 (sube o baja el clip).
Ejecutar:  .venv/Scripts/python.exe tests/test_fundidos_auto.py <carpeta_salida>
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

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
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
SR = 48000


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def cerca(a, b, tol=1e-4):
    return a is not None and abs(a - b) <= tol


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "fundidos_auto")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import effects as E
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    voz = os.path.join(out, "voz.wav")
    musica = os.path.join(out, "musica.wav")
    efecto = os.path.join(out, "efecto.wav")
    broll = os.path.join(out, "broll.mp4")
    for ruta, args in ((voz, ["-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000"]),
                       (musica, ["-f", "lavfi", "-i", "sine=f=330:d=20:sample_rate=48000"]),
                       (efecto, ["-f", "lavfi", "-i", "sine=f=880:d=3:sample_rate=48000"]),
                       (broll, ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8", "-f", "lavfi", "-i",
                                "sine=f=550:d=8", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                                "-shortest"])):
        if not os.path.exists(ruta):
            subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y"] + args + [ruta], check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.8)
    ctrl, tl = win.ctrl, win.timeline
    P = ctrl.project
    P.fps = FPS
    assert ctrl.fundidos_auto, "encendidos por defecto"
    chk = win.chk_fundidos
    assert chk.isChecked() and chk.toolTip() and chk.parentWidget() is win.chk_puntos_union.parentWidget()
    mv, mm, me, mb = ctrl.import_now([voz, musica, efecto, broll])
    while ctrl.analyzing:
        pump(app, 0.1)
    P.transcripts[mv] = {"words": [[0.5, 1.0, "hola"]], "segments": []}     # (es tu voz)

    def pista_nueva(kind):
        ya = {t.id for t in P.tracks}
        ctrl.add_track(kind)
        return next(t.id for t in P.tracks if t.id not in ya)
    an = pista_nueva(TRACK_AUDIO)
    # voz en 3 trozos pegados con saltos en el archivo (fases del tono distintas: sin fundido, chasquido)
    ctrl.insert_ranges([{"media_id": mv, "start": 0.0, "source_in": 0.0, "duration": 2.0},
                        {"media_id": mv, "start": 2.0, "source_in": 3.00037, "duration": 2.0},
                        {"media_id": mv, "start": 4.0, "source_in": 6.00113, "duration": 2.0}], an, "Voz")
    f2 = 2 / FPS

    def voz_trozos():
        return sorted(P.clips_on(an), key=lambda c: c.start)
    a, b, c = voz_trozos()
    fx = [E.audio_fades(x.fx) for x in (a, b, c)]
    assert cerca(fx[0][0], 0.0) and cerca(fx[0][1], f2), fx                # (al principio de la voz: nada)
    assert cerca(fx[1][0], f2) and cerca(fx[1][1], f2), fx
    assert cerca(fx[2][0], f2) and cerca(fx[2][1], 0.0), fx                # (al final: nada)
    # en el visor: el volumen baja a 0 justo en la unión y vuelve a 1 a los 2 fotogramas
    assert E.fade_gain(b.fx, 0.0, b.duration) == 0.0 and E.fade_gain(b.fx, f2 + 1e-3, b.duration) == 1.0
    assert E.fade_gain(a.fx, a.duration, a.duration) == 0.0
    print(f"✓ uniones de voz: {round(f2 * 1000)} ms (2 fotogramas) a cada lado; al principio y al final, nada; el "
          "visor baja a 0 en la unión")

    # dividir (sin salto en el archivo): ese corte no lleva fundido (no hay chasquido que tapar)
    n0 = ctrl.undo_stack.index()
    ctrl.split(1.0, [a.id])
    a1, a2 = voz_trozos()[:2]
    assert cerca(E.audio_fades(a1.fx)[1], 0.0) and cerca(E.audio_fades(a2.fx)[0], 0.0), (a1.fx, a2.fx)
    assert cerca(E.audio_fades(a2.fx)[1], f2)
    ctrl.undo_stack.undo()
    assert ctrl.undo_stack.index() == n0
    print("✓ dividir sin salto en el archivo: ese corte sin fundido (no baja el volumen)")

    # tu fundido manda si es mayor; el automático no lo toca
    ctrl.set_clip_props([b.id], "Fundido de entrada", fx=dict(P.clips[b.id].fx or {}, fade_in=0.5))
    b = P.clips[b.id]
    assert E.audio_fades(b.fx)[0] == 0.5 and (b.fx or {}).get("fade_in") == 0.5
    ctrl.undo_stack.undo()

    # música (bordes libres), sonido del B-roll y un efecto corto
    am = pista_nueva(TRACK_AUDIO)
    (mus,) = ctrl.insert_ranges([{"media_id": mm, "start": 1.0, "source_in": 0.0, "duration": 6.0}], am, "Música")
    (sfx,) = ctrl.insert_ranges([{"media_id": me, "start": 8.0, "source_in": 0.0, "duration": 2.0}], am, "Efecto")
    vb = pista_nueva(TRACK_VIDEO)
    ids_b = ctrl.insert_ranges([{"media_id": mb, "start": 1.0, "source_in": 0.0, "duration": 3.0}], vb, "B-roll")
    snd_b = next(i for i in ids_b if P.track(P.clips[i].track_id).kind == TRACK_AUDIO)
    vid_b = next(i for i in ids_b if P.track(P.clips[i].track_id).kind == TRACK_VIDEO)
    assert E.audio_fades(P.clips[mus].fx) == (ctrl.FUNDIDO_MUSICA, ctrl.FUNDIDO_MUSICA), P.clips[mus].fx
    assert E.audio_fades(P.clips[sfx].fx) == (0.0, 0.0), P.clips[sfx].fx
    fb = round(4 / FPS, 4)
    assert E.audio_fades(P.clips[snd_b].fx) == (fb, fb), P.clips[snd_b].fx
    assert not (P.clips[vid_b].fx or {}).get("afade_in"), "la imagen del B-roll no se funde (solo su sonido)"
    print("✓ música: 0,3 s al empezar y al acabar; sonido del B-roll: 4 fotogramas; efecto corto y la imagen: nada")

    # «Eliminar silencio» en la voz: todas las uniones nuevas con fundido
    n0 = ctrl.undo_stack.index()
    ctrl.remove_silence([voz_trozos()[0].id], [(0.6, 0.9), (2.5, 2.8)], scope="track")
    vt = voz_trozos()
    juntas = [(x, y) for x, y in zip(vt, vt[1:]) if abs(x.end - y.start) < 1e-3]
    assert len(juntas) >= 4, [(round(x.start, 3), round(x.end, 3)) for x in vt]
    for x, y in juntas:
        assert cerca(E.audio_fades(x.fx)[1], f2) and cerca(E.audio_fades(y.fx)[0], f2), (x.fx, y.fx)
    while ctrl.undo_stack.index() > n0:
        ctrl.undo_stack.undo()
    print(f"✓ tras «Eliminar silencio»: las {len(juntas)} uniones con fundido")

    # exportación: sin chasquido con la regla; con ella apagada, el chasquido de siempre
    for x in (mus, sfx, *ids_b):                        # (solo la voz, para medir sus uniones)
        P.clips[x].volume = 0.0
    P.clips[next(t for t in ids_b)].volume = 0.0
    ff = M.ffmpeg()

    def exporta(nombre):
        wav = os.path.join(out, nombre)
        args, _ = build_command(P, ExportOptions(path=wav, audio_only=True, loudnorm=False), ff,
                                os.path.join(out, nombre + ".txt"))
        r = subprocess.run(args, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-800:]
        return M.decode_mono(wav, SR)

    def saltos(snd):
        d = np.abs(np.diff(snd))
        tono = float(np.percentile(d[int(0.3 * SR):int(1.7 * SR)], 99.5))   # (el tono continuo)
        en = [float(d[int((t - 0.004) * SR):int((t + 0.004) * SR)].max()) for t in (2.0, 4.0)]
        return tono, en
    con = exporta("con_fundidos.wav")
    tono, en_con = saltos(con)
    chk.setChecked(False)                             # (la casilla: la regla, apagada)
    pump(app, 0.02)
    sin = exporta("sin_fundidos.wav")
    _t2, en_sin = saltos(sin)
    print(f"  salto entre muestras: tono {tono:.4f} · uniones con fundidos {[round(x, 4) for x in en_con]} · sin "
          f"{[round(x, 4) for x in en_sin]}")
    assert max(en_con) <= tono * 1.3, "con fundidos no debe haber chasquido"
    assert max(en_sin) > tono * 2.0, "la prueba debe tener chasquido sin fundidos (si no, no mide nada)"
    print("✓ exportación: con fundidos, el salto en las uniones es como el del tono (sin chasquido); sin ellos, "
          "el chasquido de siempre")

    # la línea de volumen, siempre a la vista en los audios, y se arrastra sin el modo 〰
    tl.set_curves(False)
    tl.pps, tl.scroll = 120.0, 0.0
    tl._update_scrollbar()
    pump(app, 0.2)
    tl.repaint()
    v = voz_trozos()[1]
    r = tl.clip_rect(v)
    area = tl._curve_area(v, r)
    y = area.bottom() - tl._db_norm(v.volume) * area.height()
    img = tl.grab().toImage()
    img.save(os.path.join(out, "linea_volumen.png"))
    x = int(r.center().x())
    col = [img.pixelColor(x, int(y) + dy) for dy in (-1, 0, 1)]
    fondo = img.pixelColor(x, int(y) + 6)
    hay = any(q.red() - fondo.red() > 40 and q.blue() <= fondo.blue() + 30 for q in col)   # (más amarilla que el clip)
    assert hay, ("la línea de volumen debe verse sin el modo 〰", [q.name() for q in col], fondo.name())
    vol0 = v.volume
    tl.set_selection([v.id])              # (22/11: la línea se agarra con el clip ya elegido)
    n0 = ctrl.undo_stack.index()
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, int(round(y))))
    assert (tl._drag or {}).get("type") == "curve_level", tl._drag
    ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y + 20), QPointF(tl.mapToGlobal(QPoint(x, int(y + 20)))),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    tl.mouseMoveEvent(ev)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, int(y + 20)))
    pump(app, 0.05)
    assert P.clips[v.id].volume < vol0 * 0.9, (vol0, P.clips[v.id].volume)
    assert P.clips[v.id].start == v.start, "arrastrar la línea no mueve el clip"
    while ctrl.undo_stack.index() > n0:
        ctrl.undo_stack.undo()
    assert abs(P.clips[v.id].volume - vol0) < 1e-6
    print("✓ la línea de volumen se ve siempre en los audios y se arrastra sin el modo 〰 (baja el volumen, no mueve "
          "el clip)")

    # apagada: nada automático en ningún clip; deshacer y rehacer lo respetan (la regla es la de ahora)
    def ninguno():
        return not any(k in (x.fx or {}) for x in ctrl.project.clips.values() for k in ("afade_in", "afade_out"))
    assert ninguno()
    ctrl.set_clip_props([voz_trozos()[0].id], "vol", volume=0.9)       # (una edición con la regla apagada)
    ctrl.undo_stack.undo()
    assert ninguno(), "deshacer con la regla apagada no devuelve fundidos automáticos"
    ctrl.undo_stack.undo()                                            # (pasos de cuando estaba encendida)
    assert ninguno(), "ni los pasos de cuando estaba encendida"
    ctrl.undo_stack.redo()
    assert ninguno()
    # guardar con la regla encendida y abrir con ella apagada: ninguno
    chk.setChecked(True)
    pump(app, 0.02)
    assert ctrl.fundidos_auto and cerca(E.audio_fades(voz_trozos()[1].fx)[0], f2)
    ruta = os.path.join(out, "con_fundidos.eia")
    ctrl.save(ruta)
    chk.setChecked(False)
    pump(app, 0.02)
    assert not ctrl.fundidos_auto and str(QSettings("EditorIA", "EditorIA").value("audio/fundidos_auto")) == "false"
    assert ninguno()
    ctrl.load(ruta)
    assert ninguno(), "abrir con la regla apagada: sin los automáticos de quien guardó"
    chk.setChecked(True)
    pump(app, 0.02)
    P = ctrl.project
    assert cerca(E.audio_fades(voz_trozos()[1].fx)[0], f2), "encendida: vuelven al momento"
    chk.setChecked(False)
    pump(app, 0.02)
    ctrl.load(ruta)
    chk.setChecked(True)
    pump(app, 0.02)
    print("✓ «Fundidos automáticos» apagada: ninguno (como antes); deshacer, rehacer y abrir un proyecto guardado con "
          "ellos lo respetan; encendida, vuelven; la casilla va a la par y se recuerda")

    P.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
