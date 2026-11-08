"""
Prueba de ⇆ Alt + rueda sobre un clip ELEGIDO en la línea de tiempo:
- el clip (con su sonido vinculado) se desliza hacia atrás / delante SIN cambiar de tamaño;
- el movimiento es suave: muchos pasos intermedios por cada paso de la rueda y repintados cortos;
- se detiene al tocar el clip de al lado (y nunca antes del segundo 0);
- se pega a una palabra clave (banderita) y al cabezal;
- el visor enseña el cuadro en vivo y el proyecto no cambia hasta que se aplica (un solo Ctrl+Z);
- encima de un clip NO elegido, Alt + rueda sigue desplazando las pistas en vertical.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles.
Ejecutar:  .venv/Scripts/python.exe tests/test_alt_wheel_nudge.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_nudge_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secs:
        app.processEvents()
        time.sleep(0.002)


def rueda(app, tl, x: float, y: float, dy: int, mod=Qt.AltModifier):
    ev = QWheelEvent(QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))), QPoint(0, 0),
                     QPoint(0, dy), Qt.NoButton, mod, Qt.NoScrollPhase, False)
    QApplication.sendEvent(tl, ev)
    app.processEvents()


def video_prueba() -> str:
    from editoria.core import media as MEDIA
    ruta = os.path.join(_TMP, "v.mp4")
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "10", "-pix_fmt", "yuv420p",
                    "-shortest", ruta], check=True, timeout=180, creationflags=0x08000000)
    return ruta


def main():
    import faulthandler
    faulthandler.dump_traceback_later(300, exit=True)
    app = QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, MediaItem, TRACK_AUDIO, TRACK_VIDEO, new_id
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    w = MainWindow()
    w.resize(1300, 560)
    w.show()
    pump(app, 0.8)
    ctrl, tl = w.ctrl, w.timeline
    ctrl.new_project()
    p = ctrl.project
    vid = new_id()
    p.media[vid] = MediaItem(id=vid, path=video_prueba(), kind=KIND_VIDEO, name="v", duration=10.0, width=320,
                             height=180, fps=25.0, has_audio=True, channels=2, probed=True)
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a = ctrl.add_media([vid], v1.id, 2.0)            # clip A (2–12 s) con su sonido vinculado
    ctrl.trim_clip(a[0], "right", 5.0)               # A: 2–5 s
    b = ctrl.add_media([vid], v1.id, 9.0)            # clip B (9–19 s): el vecino
    p = ctrl.project
    ca = p.clips[a[0]]
    ids_a = [c.id for c in p.clips.values() if c.link and c.link == ca.link] or [a[0]]
    assert len(ids_a) == 2, f"A debería tener imagen y sonido vinculados: {ids_a}"
    dur0 = {i: p.clips[i].duration for i in ids_a}
    tl.pps, tl.scroll = 60.0, 0.0
    tl._update_scrollbar()
    tl.set_playhead(30.0)                            # lejos: el cabezal no atrae
    w.engine.user_seek(30.0)
    tl.set_selection(ids_a)
    pump(app, 0.3)

    def centro(cid):
        r = tl.clip_rect(ctrl.project.clips[cid])
        return r.center().x(), r.center().y()

    def inicio(cid):
        return ctrl.project.clips[cid].start

    # medir la suavidad: cuánto tarda cada repintado y cuántas posiciones intermedias hay
    pintados: list[float] = []
    orig_paint = tl.paintEvent

    def paint_medido(e):
        t0 = time.perf_counter()
        orig_paint(e)
        pintados.append((time.perf_counter() - t0) * 1000)
    tl.paintEvent = paint_medido
    posiciones: list[float] = []
    orig_step = tl._nudge_step

    def step_medido():
        orig_step()
        if tl._nudge is not None:
            posiciones.append(tl._nudge["d"]["dt"])
    tl._nudge_step = step_medido
    tl._nudge_anim.timeout.disconnect()
    tl._nudge_anim.timeout.connect(step_medido)

    # ------------------------------------------------ 1) un paso de rueda hacia abajo: 18 px más tarde
    pasos0 = ctrl.undo_stack.index()
    x, y = centro(a[0])
    rueda(app, tl, x, y, -120)
    pump(app, 0.15)
    assert abs(inicio(a[0]) - 2.0) < 1e-9, "el proyecto NO debe cambiar mientras se desliza"
    assert tl._nudge is not None and tl._nudge["d"]["dt"] > 0, "debería estar deslizándose"
    pump(app, 0.6)                                   # deja de girar: se aplica
    esperado = 2.0 + 18 / 60.0
    assert tl._nudge is None, "debería haberse aplicado"
    for i in ids_a:
        assert abs(inicio(i) - esperado) < 1e-6, (i, inicio(i), esperado)
        assert abs(ctrl.project.clips[i].duration - dur0[i]) < 1e-9, "no debe cambiar de tamaño"
    assert ctrl.undo_stack.index() == pasos0 + 1, "un solo paso de Ctrl+Z"
    intermedias = [d for d in posiciones if 1e-6 < d < 18 / 60.0 - 1e-6]
    print(f"✓ 1 paso de rueda: +{18 / 60.0:.3f} s (imagen y sonido juntos, mismo tamaño), un solo Ctrl+Z; "
          f"{len(intermedias)} posiciones intermedias")
    assert len(intermedias) >= 6, f"poco suave: solo {len(intermedias)} posiciones intermedias"
    ctrl.undo_stack.undo()
    assert abs(inicio(a[0]) - 2.0) < 1e-9
    print("✓ Ctrl+Z lo devuelve a su sitio")
    tl.set_selection(ids_a)

    # ------------------------------------------------ 2) muchos pasos: se detiene al tocar B (A acaba en 9 s)
    x, y = centro(a[0])
    pintados.clear()
    posiciones.clear()
    t0 = time.perf_counter()
    for _ in range(40):
        rueda(app, tl, x, y, -120)
        pump(app, 0.012)
    pump(app, 0.7)
    dur_anim = time.perf_counter() - t0
    assert abs(inicio(a[0]) - 6.0) < 1e-6, f"debería quedarse pegado a B: {inicio(a[0])}"
    assert abs(ctrl.project.clips[a[0]].end - inicio(b[0])) < 1e-6
    print(f"✓ 40 pasos: se detiene justo al tocar el clip de al lado (A acaba en {ctrl.project.clips[a[0]].end:.2f} s,"
          f" B empieza en {inicio(b[0]):.2f} s)")
    if pintados:
        pintados_s = sorted(pintados)
        med = pintados_s[len(pintados_s) // 2]
        p95 = pintados_s[int(len(pintados_s) * 0.95) - 1] if len(pintados_s) > 1 else pintados_s[0]
        print(f"  · suavidad: {len(pintados)} repintados en {dur_anim:.2f} s, mediana {med:.1f} ms, "
              f"p95 {p95:.1f} ms, máx {max(pintados):.1f} ms")
        assert p95 < 16, f"repintados demasiado lentos para 60 fps: p95 {p95:.1f} ms"

    # ------------------------------------------------ 3) hacia atrás: nunca antes del segundo 0
    tl.set_selection(ids_a)
    x, y = centro(a[0])
    for _ in range(80):
        rueda(app, tl, x, y, 120)
        pump(app, 0.004)
    pump(app, 0.7)
    assert abs(inicio(a[0])) < 1e-6, f"debería quedarse en 0: {inicio(a[0])}"
    print("✓ hacia atrás se detiene en el segundo 0")

    # ------------------------------------------------ 4) imán: se pega a la palabra clave
    tl.set_hint_marks([(1.52, "🎬 GTA 6")])
    tl.set_selection(ids_a)
    x, y = centro(a[0])
    for _ in range(5):                               # 0 → 0.3 → … → 1.5: la palabra está en 1.52
        rueda(app, tl, x, y, -120)
        pump(app, 0.03)
    pump(app, 0.7)
    assert abs(inicio(a[0]) - 1.52) < 1e-6, f"debería pegarse a la palabra clave (1.52): {inicio(a[0])}"
    print("✓ se pega a la palabra clave (empieza justo en «GTA 6»)")

    # ------------------------------------------------ 5) imán al cabezal + el visor enseña el cuadro en vivo
    tl.set_hint_marks([])
    tl.set_playhead(3.1)
    w.engine.user_seek(3.1)
    vistos: list[tuple[float, float]] = []           # (tiempo pedido al visor, inicio de A en ese momento)
    orig_seek = w.engine.user_seek

    def seek_espia(t):
        vistos.append((t, ctrl.project.clips[a[0]].start))
        orig_seek(t)
    tl.seek_requested.disconnect(w.engine.user_seek)
    tl.seek_requested.connect(seek_espia)
    tl.set_selection(ids_a)
    x, y = centro(a[0])
    for _ in range(5):                               # 1.52 → … → 3.02: el cabezal (3.1) atrae el principio
        rueda(app, tl, x, y, -120)
        pump(app, 0.03)
    pump(app, 0.15)
    assert vistos, "el visor debería recibir el cuadro mientras se desliza"
    assert all(abs(s - 1.52) > 1e-6 for _t, s in vistos[:-1]) or len(vistos) == 1, \
        "durante la vista previa el clip debe estar en su sitio nuevo"
    assert abs(inicio(a[0]) - 1.52) < 1e-9, "fuera de la vista previa el proyecto sigue igual"
    pump(app, 0.7)
    assert abs(inicio(a[0]) - 3.1) < 1e-6, f"debería pegarse al cabezal (3.1): {inicio(a[0])}"
    assert abs(vistos[-1][0] - 3.1) < 1e-6, "al aplicar, el visor vuelve al cabezal"
    print(f"✓ se pega al cabezal; el visor recibió {len(vistos)} cuadros en vivo y vuelve al cabezal al terminar")
    tl.seek_requested.disconnect(seek_espia)
    tl.seek_requested.connect(w.engine.user_seek)

    # ------------------------------------------------ 6) clip NO elegido: Alt + rueda = scroll vertical
    tl.set_selection([])
    x, y = centro(b[0])
    pasos = ctrl.undo_stack.index()
    rueda(app, tl, x, y, -120)
    assert tl._nudge is None, "sin elegir el clip no se desliza"
    pump(app, 0.6)
    assert ctrl.undo_stack.index() == pasos
    print("✓ sobre un clip no elegido, Alt + rueda no mueve nada (desplaza las pistas)")

    # ------------------------------------------------ 7) un clic a mitad aplica lo pendiente
    tl.set_selection(ids_a)
    x, y = centro(a[0])
    rueda(app, tl, x, y, 120)
    pump(app, 0.2)
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(tl, ev)
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(tl, ev)
    pump(app, 0.1)
    assert tl._nudge is None and inicio(a[0]) < 3.1 - 1e-6, "un clic debería aplicar el deslizamiento pendiente"
    print("✓ un clic a mitad aplica lo que llevabas deslizado")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    w.close()
    pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
