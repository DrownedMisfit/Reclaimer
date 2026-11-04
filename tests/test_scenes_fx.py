"""
Prueba de ✂ Cortar en los cambios de escena (sin IA) y de los efectos nuevos de edits musicales:
  · un video con 3 escenas se corta justo en los 2 cambios (también su sonido vinculado); un paso de Ctrl+Z;
  · funciona aunque el clip empiece a mitad del archivo (tiempos del archivo → línea de tiempo);
  · efectos nuevos (RGB, brillo, desenfoque de movimiento, contraste, VHS, parpadeo, giro, destello de luz):
    exportan sin errores, se ven en el visor y los estilos del edit los usan.
Ejecutar:  .venv/Scripts/python.exe tests/test_scenes_fx.py <carpeta_salida>
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

NEW = {"rgbsplit": 0.6, "glow": 0.6, "motionblur": 0.6, "punchy": 0.7, "vhs": 0.7, "flicker": 0.7, "roll": 0.8,
       "lightleak": 0.7}


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
    app = QApplication(sys.argv)
    from editoria.ai import edit_engine
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "cinematica.mp4")     # 0–3 s escena A · 3–6 s escena B · 6–8 s escena C (con sonido)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-f", "lavfi", "-i", "mandelbrot=s=320x180:r=30", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=330:d=8",
                    "-filter_complex", "[1]trim=duration=3,setpts=PTS-STARTPTS[m];[0][m][2]concat=n=3:v=1:a=0[v]",
                    "-map", "[v]", "-map", "3:a", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 320, 180
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        made = ctrl.add_media([mid], v1.id, 2.0)
        vc = next(i for i in made if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
        ctrl.trim_clip(vc, "left", 3.0)           # el clip empieza en el segundo 1 del archivo (en la línea: 3 s)
        c = p.clips[vc]
        assert abs(c.source_in - 1.0) < 0.05 and abs(c.start - 3.0) < 0.05, (c.source_in, c.start)
        n0 = ctrl.undo_stack.count()
        win.cut_scenes([vc], "normal")
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 60:
            pump(app, 0.1)
        vids = sorted((x for x in p.clips.values() if x.track_id == v1.id), key=lambda x: x.start)
        starts = [round(x.start, 2) for x in vids]
        assert len(vids) == 3 and abs(starts[1] - 5.0) < 0.05 and abs(starts[2] - 8.0) < 0.05, starts
        auds = [x for x in p.clips.values() if p.track(x.track_id).kind == TRACK_AUDIO]
        assert len(auds) == 3, "el sonido vinculado también se corta"
        assert ctrl.undo_stack.count() == n0 + 1
        ctrl.undo_stack.undo()
        assert len([x for x in p.clips.values() if x.track_id == v1.id]) == 1
        print(f"✓ ✂ cambios de escena: cortado justo en {starts[1]} s y {starts[2]} s (y su sonido); un Ctrl+Z")

        # Efectos nuevos: exportan, se ven en el visor y los estilos los usan
        ctrl.undo_stack.redo()
        piece = vids[1].id if vids[1].id in p.clips else next(iter(x.id for x in p.clips.values()
                                                                    if x.track_id == v1.id))
        for key, val in NEW.items():
            ctrl.set_clip_props([piece], key, fx={key: val})
            args, _t = build_command(p, ExportOptions(path=os.path.join(out, f"{key}.mp4"), width=320, height=180,
                                                      fps=30, encoder="cpu", loudnorm=False),
                                     ff, os.path.join(out, "f.txt"))
            r = subprocess.run(args, capture_output=True)
            assert r.returncode == 0, (key, r.stderr.decode(errors="replace")[-600:])
        ctrl.set_clip_props([piece], "look", fx={"rgbsplit": 0.6, "glow": 0.5})
        win.engine.seek(p.clips[piece].start + 0.5)
        pump(app, 0.3)
        eff = win.preview.canvas.layer(v1.id).box.graphicsEffect()
        assert eff is not None and getattr(eff, "extra", {}).get("rgbsplit"), "el visor los aplica"
        win.preview.canvas.grab()      # dibuja con los efectos (que no falle)
        uses = {k for s in edit_engine.STYLES.values() for k in ("rgbsplit", "glow", "punchy", "vhs") if s.get(k)}
        assert uses == {"rgbsplit", "glow", "punchy", "vhs"}, uses
        assert any(s.get("flicker_drop") for s in edit_engine.STYLES.values())
        print("✓ efectos nuevos (RGB, brillo, movimiento, contraste, VHS, parpadeo, giro, luz): exportan, se ven y "
              "los estilos del edit los usan")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
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
