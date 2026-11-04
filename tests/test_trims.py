"""
Prueba de los recortes avanzados (como el modo Trim de DaVinci Resolve): ripple, roll, slip y slide,
también con el ratón (herramienta ⇿ Recorte y Ctrl+borde).
Ejecutar:  .venv/Scripts/python.exe tests/test_trims.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def close(a, b, tol=1e-6):
    return abs(a - b) < tol


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    src = os.path.join(out, "clip.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=10", "-f", "lavfi", "-i", "sine=f=440:d=10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", src], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    [mid] = ctrl.import_now([src])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ids = []
    for k in range(3):     # tres trozos seguidos del segundo 2–5 del archivo
        made = ctrl.add_media([mid], v1.id, 3.0 * k)
        vid = next(i for i in made if p.clips[i].track_id == v1.id)
        ctrl.trim_clip(vid, "left", 3.0 * k + 2.0)
        c = p.clips[vid]
        ctrl.move_clips({x.id: (3.0 * k, x.track_id) for x in [c] + ctrl.partners(p, c)})
        ctrl.trim_clip(vid, "right", 3.0 * k + 3.0)
        ids.append(vid)
    A, B, C = (p.clips[i] for i in ids)
    assert [(c.start, c.duration, c.source_in) for c in (A, B, C)] == [(0, 3, 2), (3, 3, 2), (6, 3, 2)], \
        [(c.start, c.duration, c.source_in) for c in (A, B, C)]
    Ba = ctrl.partners(p, B)[0]
    stack = ctrl.undo_stack

    # --- ripple (borde derecho): A más largo, B y C se apartan (su sonido también)
    ctrl.ripple_trim(A.id, "right", 4.0)
    assert close(p.clips[A.id].duration, 4) and close(p.clips[B.id].start, 4) and close(p.clips[C.id].start, 7)
    assert close(p.clips[Ba.id].start, 4)
    stack.undo()
    # --- ripple (borde izquierdo): quita medio segundo del principio de B; B no se mueve
    ctrl.ripple_trim(B.id, "left", 3.5)
    b = p.clips[B.id]
    assert close(b.start, 3) and close(b.source_in, 2.5) and close(b.duration, 2.5) and close(p.clips[C.id].start, 5.5)
    stack.undo()
    print("✓ ripple: alargar/acortar mueve lo de detrás (y el sonido vinculado), sin huecos")

    # --- roll: mover el corte A|B
    ctrl.roll_edit(B.id, 3.5)
    a, b = p.clips[A.id], p.clips[B.id]
    assert close(a.duration, 3.5) and close(b.start, 3.5) and close(b.source_in, 2.5) and close(b.duration, 2.5)
    assert close(p.clips[C.id].start, 6) and close(p.clips[Ba.id].start, 3.5)
    lo, hi = ctrl.roll_limits(B.id)
    assert close(lo, 1.0) and close(hi, 5.95), (lo, hi)  # B tiene 2 s de material antes; C limita a la derecha
    stack.undo()
    print("✓ roll: el corte se mueve; uno se alarga, el otro se acorta; nada más cambia")

    # --- slip: misma posición y duración, otra parte del archivo (con límites)
    ctrl.slip_clip(B.id, 1.0)
    b = p.clips[B.id]
    assert close(b.start, 3) and close(b.duration, 3) and close(b.source_in, 3) and close(p.clips[Ba.id].source_in, 3)
    ctrl.slip_clip(B.id, -10.0)
    assert close(p.clips[B.id].source_in, 0.0)
    stack.undo()
    stack.undo()
    print("✓ slip: enseña otra parte del video sin moverse (y no se sale del archivo)")

    # --- slide: B se desliza; A se alarga y C se acorta (su inicio en el archivo avanza)
    ctrl.slide_clip(B.id, 1.0)
    a, b, c = p.clips[A.id], p.clips[B.id], p.clips[C.id]
    assert close(a.duration, 4) and close(b.start, 4) and close(b.source_in, 2) and close(c.start, 7)
    assert close(c.source_in, 3) and close(c.duration, 2)
    assert close(p.clips[Ba.id].start, 4)
    stack.undo()
    print("✓ slide: se desliza entre sus vecinos sin dejar huecos (y su sonido igual)")

    # --- con velocidad y al revés también cuadra
    ctrl.set_speed([B.id], reverse=True, ripple=False)
    before = p.clips[B.id].src_at(0.0)
    ctrl.ripple_trim(B.id, "right", 5.0, linked=False)
    b = p.clips[B.id]
    assert close(b.duration, 2) and close(b.src_at(0.0), before), (b.src_at(0.0), before)
    stack.undo()
    stack.undo()
    print("✓ al revés: acortar el final no cambia la imagen del principio")

    # --- con el ratón
    tl = win.timeline
    win.timeline.zoom(1.0)
    pump(app, 0.2)

    def pt(t, clip):
        i = p.track_index(clip.track_id)
        return QPoint(int(tl.x_for(t)), int(tl.track_y(i) + tl.track_h(i) / 2))

    def drag(a, b, mods=Qt.NoModifier):
        QTest.mousePress(tl, Qt.LeftButton, mods, a)
        for k in range(1, 6):
            QTest.mouseMove(tl, a + (b - a) * (k / 5))
        QTest.mouseRelease(tl, Qt.LeftButton, mods, b)
        pump(app, 0.1)

    A, B = p.clips[A.id], p.clips[B.id]
    pps = tl.pps
    win.set_tool("select")
    win.timeline.snapping = False
    drag(pt(A.end - 0.5 / pps, A), pt(A.end - 0.5 / pps, A) + QPoint(int(0.5 * pps), 0), Qt.ControlModifier)
    assert close(p.clips[A.id].duration, 3.5, 0.06) and close(p.clips[B.id].start, 3.5, 0.06), \
        (p.clips[A.id].duration, p.clips[B.id].start)
    stack.undo()
    win.set_tool("trim")
    assert win.tool_trim.isChecked()
    B = p.clips[B.id]
    mid_b = pt(B.start + 1.5, B)
    drag(mid_b, mid_b + QPoint(int(0.6 * pps), 0))
    assert close(p.clips[B.id].start, 3) and close(p.clips[B.id].source_in, 2.6, 0.06), p.clips[B.id].source_in
    stack.undo()
    drag(mid_b, mid_b + QPoint(int(0.6 * pps), 0), Qt.ShiftModifier)
    assert close(p.clips[B.id].start, 3.6, 0.06) and close(p.clips[A.id].duration, 3.6, 0.06)
    stack.undo()
    edge = pt(B.start + 0.5 / pps, B)
    drag(edge, edge + QPoint(int(0.5 * pps), 0), Qt.ShiftModifier)
    assert close(p.clips[A.id].duration, 3.5, 0.06) and close(p.clips[B.id].start, 3.5, 0.06), \
        (p.clips[A.id].duration, p.clips[B.id].start)
    stack.undo()
    win.set_tool("select")
    print("✓ con el ratón: Ctrl+borde = ripple · ⇿ centro = slip · Mayús+centro = slide · Mayús+borde = roll")

    win.analyzer.shutdown()
    stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
