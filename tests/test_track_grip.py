"""
Prueba de la barrita ↕ a la izquierda de las pistas: arrastrar hacia ARRIBA = pistas más grandes; hacia ABAJO =
más pequeñas (video y audio a la vez, en proporción; con los límites de los botones 🎞↕ / 🔊↕). Se recuerda.
Ejecutar:  .venv/Scripts/python.exe tests/test_track_grip.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

KEYS = ("timeline/alto_video", "timeline/alto_audio")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in KEYS}               # tus tamaños de pista quedan como estaban
    app = QApplication(sys.argv)
    try:
        run(app, st)
    finally:
        for k, v in keep.items():
            st.remove(k) if v is None else st.setValue(k, v)


def run(app, st):
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.4)
    tl = win.timeline
    tl.set_wave(video_h=54, audio_h=60)
    g = tl._grip_rect()
    assert g.width() >= 7 and g.height() > 40, g
    start = QPoint(int(g.center().x()), int(min(g.bottom() - 5, g.top() + 150)))

    def drag(dy):
        QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, start)
        for k in range(1, 6):
            QTest.mouseMove(tl, QPoint(start.x(), start.y() + dy * k // 5))
            pump(app, 0.02)
        QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(start.x(), start.y() + dy))
        pump(app, 0.1)

    y1 = tl.track_y(1)
    drag(-120)                                           # hacia arriba
    assert tl.video_h > 54 and tl.audio_h > 60, (tl.video_h, tl.audio_h)
    assert abs(tl.video_h / tl.audio_h - 54 / 60) < 0.05, "en proporción"
    assert tl.track_y(1) > y1
    assert int(st.value("timeline/alto_video")) == tl.video_h, "se recuerda"
    print(f"✓ arrastrar hacia arriba: pistas más grandes ({tl.video_h}/{tl.audio_h} px)")
    drag(400)                                            # hacia abajo (mucho): hasta el mínimo
    assert tl.video_h == tl.H_MIN and tl.audio_h == tl.H_MIN, (tl.video_h, tl.audio_h)
    print(f"✓ arrastrar hacia abajo: más pequeñas (sin bajar de {tl.H_MIN} px)")
    drag(-2000)
    assert tl.video_h == tl.H_MAX and tl.audio_h == tl.H_MAX
    print(f"✓ y sin pasar de {tl.H_MAX} px; los botones 🎞↕ / 🔊↕ siguen ahí")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
