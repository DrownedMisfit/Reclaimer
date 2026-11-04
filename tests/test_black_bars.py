"""
Prueba de ▭ Quitar barras negras (botón «▭ Quitar barras» encima de la línea de tiempo):
  · se detectan solas: a los lados (4:3 dentro de 16:9), arriba y abajo, y nada en un video sin barras; un trozo en
    negro (fundido, pantalla de carga) no las estropea;
  · el botón las quita (en los seleccionados o en todos), Ctrl+Z las devuelve y pulsarlo otra vez también;
  · el visor encuadra con la zona sin barras y al EXPORTAR en vertical el video sale más grande, sin franjas negras.
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_black_bars.py <carpeta>
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

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def make(M, path, content, pad, black_mid=False):
    """Un video rojo de 8 s con el contenido «content» (wxh) metido en «pad» (WxH:x:y) con negro alrededor."""
    vf = f"pad={pad}:color=black"
    if black_mid:   # 1 s entero en negro en medio (como un fundido o una pantalla de carga)
        vf += ",drawbox=enable='between(t,3,4)':x=0:y=0:w=iw:h=ih:color=black:t=fill"
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=red:s={content}:r=30:d=8", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", path], check=True)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import black_bars as BB
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    side, topb, none = (os.path.join(out, n) for n in ("lados.mp4", "arriba.mp4", "sin.mp4"))
    make(M, side, "240x180", "320:180:40:0", black_mid=True)
    make(M, topb, "320x120", "320:180:0:30")
    make(M, none, "320x180", "320:180:0:0")
    a = BB.detect(side, 8.0)
    assert a and abs(a[0] - 0.125) < 0.02 and abs(a[2] - 0.75) < 0.03 and a[1] == 0 and a[3] == 1, a
    b = BB.detect(topb, 8.0)
    assert b and b[0] == 0 and b[2] == 1 and abs(b[1] - 30 / 180) < 0.02 and abs(b[3] - 120 / 180) < 0.03, b
    assert BB.detect(none, 8.0) is None
    t0 = time.time()
    assert BB.detect(side, 8.0) == a and time.time() - t0 < 0.3, "la segunda vez, al momento (se guarda)"
    print(f"✓ barras detectadas: a los lados {a} (con 1 s en negro en medio), arriba y abajo {b}; sin barras = nada")

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    p = ctrl.project
    p.width, p.height, p.fps = 180, 320, 30.0                  # vertical: sin barras, el video sale más grande
    ids = ctrl.import_now([side, none])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    made = ctrl.add_media([ids[0]], v1.id, 0.0) + ctrl.add_media([ids[1]], v1.id, 8.0)
    vc = [i for i in made if p.clips[i].track_id == v1.id]
    win.timeline.selected.clear()
    win.remove_black_bars()                                   # sin selección: todos los videos
    t0 = time.time()
    while win._bars_job.isRunning() and time.time() - t0 < 60:
        pump(app, 0.1)
    pump(app, 0.3)
    c1, c2 = (p.clips[i] for i in vc)
    assert BB.of(c1.layout) == a and BB.of(c2.layout) is None, (c1.layout, c2.layout)
    msg = win.statusBar().currentMessage()
    assert "1 clip" in msg and "no tenía" in msg, msg
    print("✓ el botón quita las barras del video que las tiene (el otro, sin barras, se queda igual):", msg)

    # el visor: encuadra con la zona sin barras
    win.engine.user_seek(1.0)
    pump(app, 0.6)
    layer = win.preview.canvas.layer(v1.id)
    from PySide6.QtWidgets import QGraphicsItem
    assert layer._bars == a and layer.clip.flags() & QGraphicsItem.ItemClipsChildrenToShape, layer._bars
    r = layer.content_rect
    assert abs(r.width() - 180) < 2 and abs(r.height() - 135) < 2, r      # 240x180 → 180x135 (antes 180x101)
    print(f"✓ visor: el contenido ocupa {r.width():.0f}x{r.height():.0f} (con barras sería 180x101)")

    # al exportar: en vertical, el borde izquierdo es ROJO (contenido), no negro (barra)
    def export_px():
        mp4 = os.path.join(out, "v.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=180, height=320, fps=30, encoder="cpu",
                                                  loudnorm=False, video_only=True), M.ffmpeg(),
                                 os.path.join(out, "f.txt"))
        subprocess.run(args, check=True, capture_output=True)
        fr = M.frame_rgb(mp4, 1.0, 180).astype(int)
        return fr[fr.shape[0] // 2, 3]
    px = export_px()
    assert px[0] > 150 and px[1] < 80 and px[2] < 80, ("sin barras: rojo hasta el borde", px)
    ctrl.undo_stack.undo()                                    # Ctrl+Z: vuelven las barras
    assert BB.of(p.clips[vc[0]].layout) is None
    px2 = export_px()
    assert px2.max() < 40, ("con barras: el borde es negro", px2)
    ctrl.undo_stack.redo()
    win.timeline.selected = {vc[0]}
    win.remove_black_bars()                                   # ya sin barras: otra vez = devolverlas
    assert BB.of(p.clips[vc[0]].layout) is None and p.clips[vc[0]].layout is None
    print(f"✓ exportado en vertical: borde {tuple(px)} (rojo) sin barras y {tuple(px2)} (negro) con ellas; "
          "Ctrl+Z y pulsarlo otra vez las devuelven")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
