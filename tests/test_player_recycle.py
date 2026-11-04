"""
Prueba de que cambiar de proyecto / de pestaña NO apaga los reproductores (QMediaPlayer.stop() a veces se quedaba
bloqueado para siempre: Reclaimer congelado). Se apartan en pausa y los reutilizan las pistas nuevas:
  · 20 cambios de pestaña con video y audio cargados: nunca se llama a stop(), no se acumulan reproductores,
    y el visor sigue mostrando la imagen de la pestaña.
Ejecutar:  .venv/Scripts/python.exe tests/test_player_recycle.py <carpeta_salida>
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    try:
        run()
    finally:
        QSettings("EditorIA", "EditorIA").remove("espacios")   # (aunque falle: tus ajustes de pestañas limpios)


def run():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    QSettings("EditorIA", "EditorIA").remove("espacios")
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=d=8", "-shortest", "-pix_fmt", "yuv420p", vid], check=True)
    stops = []
    real_stop = QMediaPlayer.stop
    QMediaPlayer.stop = lambda self: (stops.append(1), real_stop(self))[1]
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    try:
        check(app, win, vid, stops, real_stop)
    finally:
        QMediaPlayer.stop = real_stop
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.workspaces.started = False                  # al cerrar no guarda la pestaña en tus ajustes
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
    print("TODO OK")


def check(app, win, vid, stops, real_stop):
    from editoria.core.model import TRACK_VIDEO
    ctrl, ws, eng = win.ctrl, win.workspaces, win.engine
    for fmt in ("youtube", "edit"):
        ws.switch(fmt)
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        ctrl.add_media([mid], [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1].id, 0.0)
        eng.seek(2.0)
        eng.play()
        pump(app, 0.4)
        eng.pause()
    for k in range(4):                                   # calentamiento: cada pestaña con sus pistas
        ws.switch("youtube" if k % 2 else "edit")
        pump(app, 0.1)
    n_players = len(win.findChildren(QMediaPlayer)) + len(eng.findChildren(QMediaPlayer))
    t0 = time.time()
    for k in range(20):
        ws.switch("youtube" if k % 2 else "edit")
        eng.seek(1.0 + (k % 3))
        if k % 4 == 0:
            eng.play()
            pump(app, 0.15)
            eng.pause()
        pump(app, 0.05)
    took = time.time() - t0
    n_after = len(win.findChildren(QMediaPlayer)) + len(eng.findChildren(QMediaPlayer))
    assert not stops, f"no se debe apagar ningún reproductor al cambiar de pestaña ({len(stops)})"
    assert n_after == n_players, (n_players, n_after)
    pump(app, 0.5)
    # la capa de la pista QUE TIENE el clip (la otra pista de video está vacía: es normal que no enseñe nada)
    tid = next(t.id for t in ctrl.project.tracks if t.kind == TRACK_VIDEO and ctrl.project.clips_on(t.id))
    layer = win.preview.canvas.layers[tid]
    assert layer.box.isVisible(), "el visor sigue enseñando la pista de la pestaña"
    print(f"✓ 20 cambios de pestaña en {took:.1f} s: ningún reproductor apagado (se reutilizan: "
          f"{n_players} → {n_after}), sin congelarse")


if __name__ == "__main__":
    main()
