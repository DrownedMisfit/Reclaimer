"""
Prueba de la IA «sencilla» por movimiento y palabras:
  · lo que dices manda: «paisaje/edificio» → momentos quietos; «pelea/carro» → con movimiento;
    «gameplay»/«cinemática» → clips de ese tipo;
  · 👤 Quitar el fondo quieto (sin pantalla verde): con cámara fija se quita lo que no se mueve (visor y
    exportar); con la cámara moviéndose, avisa y no se aplica.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_motion_ai.py <carpeta_salida>
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

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    from editoria.ai import edit_maker as E
    from editoria.ai import motion_words as MW
    from editoria.core import media as M
    from editoria.core import motion_key as MK
    ff = M.ffmpeg()

    # 1) Palabras + movimiento
    assert MW.wants("aquí se ve el paisaje y la ciudad")["motion"] == "quiet"
    assert MW.wants("empieza la pelea con el jefe")["motion"] == "moving"
    assert MW.wants("en la cinemática final")["type"] == "Cinemáticas"
    assert MW.wants("el gameplay es muy fluido")["type"] == "Gameplay"
    vid = os.path.join(out, "mitad.mp4")      # 0–3 s quieto, 3–6 s con mucho movimiento
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=6,select='lt(t,3)*eq(n,0)+gte(t,3)',setpts=N/30/TB",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", "6", vid], check=True)
    q = os.path.join(out, "quieto.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                    "-vf", "trim=end_frame=1,loop=loop=-1:size=1,setpts=N/30/TB,trim=duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", q], check=True)
    mv = os.path.join(out, "movido.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", mv], check=True)
    for p_ in (q, mv):
        E.motion_profile(p_, 6.0)
    quiet = {"motion": "quiet", "type": None}
    moving = {"motion": "moving", "type": None}
    assert MW.bias(quiet, q, 2.0) > MW.bias(quiet, mv, 2.0), "«paisaje» prefiere lo quieto"
    assert MW.bias(moving, mv, 2.0) > MW.bias(moving, q, 2.0), "«pelea» prefiere lo que se mueve"
    assert MW.bias({"motion": None, "type": "Gameplay"}, "", 0, "Gameplay") > 0
    print("✓ lo que dices manda: «paisaje» → quieto · «pelea» → movimiento · «gameplay/cinemática» → ese tipo")

    # 2) Quitar el fondo quieto
    face = os.path.join(out, "facecam.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=4,hue=s=0",
                    "-f", "lavfi", "-i", "color=c=white:s=60x90:d=4", "-filter_complex",
                    "[0]trim=end_frame=1,loop=loop=-1:size=1,setpts=N/30/TB,trim=duration=4[bg];"
                    "[bg][1]overlay=x='20+60*t':y=50", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                    "yuv420p", face], check=True)
    plate, moving_f = MK.learn_plate(face, 0.0, 4.0)
    assert plate and moving_f < 0.2, moving_f
    pan = os.path.join(out, "paneo.mp4")       # la cámara se mueve: toda la imagen se desplaza
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=960x180:r=30:d=6",
                    "-vf", "crop=320:180:x='t*100':y=0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                    "yuv420p", pan], check=True)
    none, moving_m = MK.learn_plate(pan, 0.0, 6.0)
    assert none is None and moving_m > 0.55, moving_m
    print(f"✓ cámara fija: aprende el fondo vacío · cámara moviéndose ({moving_m:.0%} cambia): avisa y no se aplica")

    app = QApplication(sys.argv)
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    red = os.path.join(out, "rojo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", red], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 320, 180
        rid, fid = ctrl.import_now([red, face])
        while ctrl.analyzing:
            pump(app, 0.1)
        v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
        ctrl.add_media([rid], v1.id, 0.0)
        fc = ctrl.add_media([fid], v2.id, 0.0)[0]
        win.timeline.set_selection([fc])
        win.engine.seek(2.0)
        pump(app, 0.3)
        win.effects.add_motion_key()
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 60:
            pump(app, 0.2)
        pump(app, 0.4)
        mk = (p.clips[fc].fx or {}).get("motion_key")
        assert mk and os.path.exists(mk["plate"]), p.clips[fc].fx
        eff = win.preview.canvas.layer(v2.id).box.graphicsEffect()
        assert eff is not None and getattr(eff, "mkey", None), "el visor lo aplica"
        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1200:]
        fr = M.frame_rgb(mp4, 2.0, 320).astype(int)
        x_person = int(20 + 60 * 2.0 + 30)
        assert fr[10, 300][0] > 180 and fr[10, 300][1] < 80, ("el fondo quieto se fue: se ve el rojo", fr[10, 300])
        assert fr[95, x_person].min() > 190, ("la «persona» que se mueve se queda", fr[95, x_person])
        print("✓ exportado: el fondo quieto se fue (se ve lo de debajo) y lo que se mueve se queda")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
