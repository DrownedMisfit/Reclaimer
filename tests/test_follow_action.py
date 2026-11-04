"""
Prueba de 🎯 ENCUADRE VERTICAL QUE SIGUE LA ACCIÓN (Shorts y edits con clips horizontales):
  · un cuadro blanco cruza de izquierda a derecha sobre un fondo QUIETO con textura: el recorte vertical lo sigue
    (al final está a la derecha); un solo paso de Ctrl+Z; el clip llena la pantalla («cover»);
  · al exportar, el cuadro se ve al final (con el recorte centrado se saldría); el visor mueve la imagen igual;
  · con una cámara que gira (todo el fondo se desplaza) y nada más moviéndose, el encuadre se queda en el centro;
  · «Quitar» vuelve al recorte centrado.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_follow_action.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import reframe
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    tex = os.path.join(out, "fondo.png")         # fondo con textura (como un escenario de juego), oscuro
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x180:d=1",
                    "-vf", "eq=brightness=-0.35:saturation=0.4", "-frames:v", "1", tex], check=True)
    vid = os.path.join(out, "accion.mp4")       # cuadro blanco de izquierda a derecha, fondo quieto
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", tex, "-f", "lavfi", "-i",
                    "color=c=white:s=36x36:d=6", "-filter_complex",
                    "[0:v]crop=320:180:0:0[bg];[bg][1:v]overlay=x='20+t*42':y=72:shortest=1,format=yuv420p",
                    "-t", "6", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    pan = os.path.join(out, "camara.mp4")       # la cámara gira (todo el fondo se desplaza) y nada más se mueve
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", tex, "-vf",
                    "crop=320:180:x='t*40':y=0,format=yuv420p", "-t", "6", "-r", "30", "-c:v", "libx264",
                    "-preset", "ultrafast", pan], check=True)

    kf_pan = reframe.follow_path(pan, 0.0, 6.0, 320, 180, 1080 / 1920)
    xs = [k["x"] for k in kf_pan]
    assert kf_pan and max(abs(x - 0.5) for x in xs) < 0.08, xs
    print(f"✓ cámara girando sin acción: el encuadre se queda en el centro ({min(xs):.2f}–{max(xs):.2f})")

    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    p.width, p.height, p.format = 180, 320, "short"
    (vid_id,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    cid = ctrl.add_media([vid_id], v1.id, 0.0)[0]
    n0 = ctrl.undo_stack.count()
    win.follow_action([cid])
    t0 = time.time()
    while not (p.clips[cid].layout or {}).get("follow") and time.time() - t0 < 60:
        pump(app, 0.1)
    lay = p.clips[cid].layout
    assert lay.get("fit") == "cover" and lay.get("follow"), lay
    assert ctrl.undo_stack.count() == n0 + 1
    from editoria.core import transform
    x1, x5 = transform.follow_at(lay, 1.0), transform.follow_at(lay, 5.0)
    assert x5 - x1 > 0.3 and x5 > 0.6, (x1, x5)
    print(f"✓ el recorte vertical sigue al cuadro: x {x1:.2f} → {x5:.2f} (un paso de Ctrl+Z, llena la pantalla)")

    def white_in_export(name):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=180, height=320, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        fr = M.frame_rgb(mp4, 5.0, 180).astype(int)
        return int(((fr[..., 0] > 230) & (fr[..., 1] > 230) & (fr[..., 2] > 230)).sum())
    n_follow = white_in_export("sigue.mp4")
    win.engine.seek(5.0)
    pump(app, 0.5)
    layer = win.preview.canvas.layers[v1.id]
    assert layer.content_rect.left() < -1, layer.content_rect     # la imagen corrida: el recorte va a la derecha
    ctrl.set_follow(cid, None, "Quitar")
    assert "follow" not in (p.clips[cid].layout or {}) and p.clips[cid].layout.get("fit") == "cover"
    n_center = white_in_export("centrado.mp4")
    assert n_follow > 300 and n_center < n_follow / 3, (n_follow, n_center)
    print(f"✓ exportado: con «sigue la acción» el cuadro se ve al final ({n_follow} px), centrado no ({n_center}); "
          "el visor mueve el recorte igual · «Quitar» vuelve al centrado")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
