"""
Prueba de ⧉ Clip compuesto «cocinado»: varios clips (video + efectos + texto + sonido) se renderizan a UN video
y lo sustituyen en la línea de tiempo (el visor reproduce un solo archivo); «Deshacer clip compuesto» devuelve
los originales; Ctrl+Z; el proyecto lo recuerda al guardar.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_compound.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "texto/mi_estilo")}
    app = QApplication(sys.argv)
    from editoria.core import compound as CP
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "rojo.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", vid], check=True)
    try:
        st.remove("texto/mi_estilo")
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height, p.fps = 320, 180, 30.0
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        made = ctrl.add_media([mid], v1.id, 0.0)
        vc = next(i for i in made if p.clips[i].track_id == v1.id)
        ctrl.set_clip_props([vc], "bn", fx={"bw": 1.0})                 # un efecto (blanco y negro)
        tx = ctrl.add_text(0.5, 2.0, "HOLA", blur_under=0.0)
        before = {i: (c.start, c.duration) for i, c in p.clips.items()}
        assert len(before) == 3, before                                 # video + su sonido + texto
        win.make_compound([vc, tx])
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 120:
            pump(app, 0.2)
        pump(app, 0.5)
        comp = [c for c in p.clips.values() if c.media_id in p.compounds and c.track_id == v1.id]
        assert len([c for c in p.clips.values() if c.media_id in p.compounds]) == 2, "video + su sonido vinculado"
        assert len(comp) == 1, [(c.id, c.media_id) for c in p.clips.values()]
        cc = comp[0]
        assert cc.track_id == v1.id and abs(cc.start) < 1e-6 and abs(cc.duration - 3.0) < 0.05
        assert not any(i in p.clips for i in before), "los originales ya no están (cocinados dentro)"
        cm = p.media[cc.media_id]
        assert cm.category == "Clips compuestos" and os.path.dirname(cm.path) == CP.out_dir()
        fr = M.frame_rgb(cm.path, 1.5, 320).astype(int)
        px = fr[100, 40]
        assert abs(px[0] - px[1]) < 25 and abs(px[1] - px[2]) < 25, ("el blanco y negro va cocinado", px)
        assert (fr > 200).all(axis=2).sum() > 30, "el texto va cocinado dentro"
        assert M.probe(cm.path)["has_audio"], "con su sonido"
        print(f"✓ ⧉ 3 clips (video con efecto + su sonido + texto) cocinados en 1 de {cc.duration:.1f} s, "
              "con el efecto, el texto y el sonido dentro")

        mp4 = os.path.join(out, "final.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), M.ffmpeg(), os.path.join(out, "f.txt"))
        subprocess.run(args, check=True, capture_output=True)
        assert abs(M.probe(mp4)["duration"] - 3.0) < 0.2
        print("✓ el proyecto se exporta igual con el clip compuesto")

        back = ctrl.break_compound(cc.id)
        assert len(back) == 3 and {p.clips[i].start for i in back} == {before[i][0] for i in before}
        assert not any(c.media_id in p.compounds and c.id in p.clips for c in [cc])
        ctrl.undo_stack.undo()
        assert any(c.media_id in p.compounds for c in p.clips.values()), "Ctrl+Z: vuelve el compuesto"
        ctrl.undo_stack.undo()
        assert len(p.clips) == 3 and vc in p.clips and tx in p.clips, "Ctrl+Z otra vez: los originales"
        ctrl.undo_stack.redo()
        path = os.path.join(out, "p.eia")
        ctrl.save(path)
        ctrl.load(path)
        assert len(ctrl.project.compounds) == 1
        print("✓ «Deshacer clip compuesto» devuelve los originales; Ctrl+Z; se guarda con el proyecto")
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
