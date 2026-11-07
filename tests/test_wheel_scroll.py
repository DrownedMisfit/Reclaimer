"""
Prueba de la RUEDA de la línea de tiempo: tras cada paso de rueda, lo que se ve en pantalla (los píxeles que quedaron
de desplazar la imagen y repintar solo la franja nueva) debe ser IGUAL, píxel a píxel, a un repintado completo.
Y la pastilla «fx» de un clip sigue donde está tras desplazar.
Ejecutar:  .venv/Scripts/python.exe tests/test_wheel_scroll.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def pantalla(app, win, tl):
    """Lo que hay en la ventana tal como está en su memoria de pantalla (sin repintar nada)."""
    img = app.primaryScreen().grabWindow(win.winId()).toImage().convertToFormat(QImage.Format_RGB32)
    vr = tl.visibleRegion().boundingRect()
    pos = tl.mapTo(win, vr.topLeft())
    r = QRect(pos, vr.size())
    bpl = img.bytesPerLine() // 4
    a = np.frombuffer(img.constBits(), np.uint32, bpl * img.height()).reshape(img.height(), bpl)
    return a[r.top():r.bottom() + 1, r.left():r.right() + 1].copy()


def rueda(app, tl, dy):
    ev = QWheelEvent(QPointF(900, 200), QPointF(tl.mapToGlobal(QPoint(900, 200))), QPoint(0, 0),
                     QPoint(0, dy), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(tl, ev)
    app.processEvents()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    vid = os.path.join(out, "rueda.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=40",
                    "-f", "lavfi", "-i", "sine=f=440:d=40", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", vid], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1400, 800)
    win.show()
    pump(app, 0.5)
    c = win.ctrl
    tl = win.timeline
    p = c.project
    p.fps = 30.0
    (mid,) = c.import_now([vid])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    c.add_media([mid], v1.id, 0.0)
    c.add_media([mid], v1.id, 30.0)
    while c.analyzing:
        pump(app, 0.1)
    pump(app, 0.5)
    win.resize(1400, 800)
    pump(app, 0.3)
    dur = p.duration()
    view_w = tl.width() - tl.HEADER_W
    fallos = []
    for pps in (10.0, 40.0, 150.0):
        tl.pps = pps
        tl.scroll = max(0.0, dur / 2 - view_w / 2 / pps)
        tl._update_scrollbar()
        tl.repaint()
        pump(app, 8.0)           # que terminen las miniaturas de los clips (en segundo plano) con este zoom
        malos = 0
        for k in range(16):
            rueda(app, tl, -120 if k % 10 < 7 else 120)
            pump(app, 0.3)          # las miniaturas que llegan en segundo plano repintan lo suyo antes de mirar
            A = pantalla(app, win, tl)
            tl.repaint()
            B = pantalla(app, win, tl)
            if A.shape != B.shape or not np.array_equal(A, B):
                malos += 1
                fallos.append((pps, k))
        assert malos == 0, f"zoom {pps} px/s: {malos} de 16 pasos de rueda distintos del repintado completo"
        print(f"✓ {pps:5.0f} px/s: 16 pasos de rueda = repintado completo, píxel a píxel")
    assert not fallos, fallos

    # la pastilla «fx» de un clip se desplaza con el clip (no se pierde al mover la rueda)
    c_fx = p.clips_on(v1.id)[0]
    c_fx.fx = {"glow": 1}                          # efecto de imagen: lleva su pastilla «fx»
    tl.pps = 40.0
    tl.scroll = 0.0
    tl._update_scrollbar()
    tl.repaint()
    pump(app, 0.3)
    tl.repaint()
    antes = tl._fx_chips.get(c_fx.id)
    for _ in range(3):
        rueda(app, tl, -120)
    pump(app, 0.2)
    despues = tl._fx_chips.get(c_fx.id)           # desplazada a mano por la rueda
    tl.repaint()
    real = tl._fx_chips.get(c_fx.id)              # dibujada de nuevo
    assert antes is not None and real is not None, (antes, real)
    assert despues is not None and abs(despues.x() - real.x()) < 1.5, (despues, real)
    print(f"✓ pastilla fx: tras la rueda, su sitio = el dibujado ({despues.x():.1f} px ≈ {real.x():.1f} px)")
    win.analyzer.shutdown()
    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
