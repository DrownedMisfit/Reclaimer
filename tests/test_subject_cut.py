"""
Prueba de ✂ Recortar sujeto con IA (SAM 2.1 en el motor de IA): se marca la pelota con un clic, la IA la sigue
en todo el clip y el fondo se vuelve transparente (se ve la pista de debajo) en el visor y al exportar;
invertir deja el fondo y quita la pelota.
Necesita F:\\Reclaimer\\motor_ia (si no está, la prueba lo dice y termina bien).
Ejecutar:  .venv/Scripts/python.exe tests/test_subject_cut.py <carpeta_salida>
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


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.core import motor_ia
    ok, why = motor_ia.available("sam")
    if not ok:
        print(f"(sin motor de IA: {why}) TODO OK")
        return
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.subject_cut_dialog import SubjectCutDialog
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    ball = os.path.join(out, "pelota.mp4")      # pelota roja que cruza sobre un fondo con textura
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
                    "-f", "lavfi", "-i", "color=c=red:s=60x60:d=2,format=rgba,geq=r='255':g='30':b='30':"
                    "a='if(lt(hypot(X-30,Y-30),27),255,0)'", "-filter_complex", "[0][1]overlay=x='40+80*t':y=60",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", ball], check=True)
    blue = os.path.join(out, "azul.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", blue], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 320, 180
        bid, mid = ctrl.import_now([blue, ball])
        while ctrl.analyzing:
            pump(app, 0.1)
        v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
        ctrl.add_media([bid], v1.id, 0.0)
        top = ctrl.add_media([mid], v2.id, 0.0)[0]
        dlg = SubjectCutDialog(ctrl, top, 1.0, win)
        cx = (40 + 80 * dlg.t0 + 30) / 320       # centro de la pelota en ese fotograma
        dlg.view.points = [(cx, 90 / 180, 1)]
        dlg._update_buttons()
        assert dlg.b_go.isEnabled()
        t0 = time.time()
        dlg.start()
        while manager().tasks and time.time() - t0 < 600:
            pump(app, 0.3)
        pump(app, 0.3)
        sm = (p.clips[top].fx or {}).get("subject_mask")
        assert sm and os.path.exists(sm["mask"]), p.clips[top].fx
        print(f"✓ la IA siguió a la pelota en todo el clip ({time.time() - t0:.0f} s)")
        win.engine.seek(1.0)
        pump(app, 0.5)
        eff = win.preview.canvas.layer(v2.id).box.graphicsEffect()
        assert eff is not None and getattr(eff, "smask", None), "el visor lo aplica"
        print("✓ el visor recorta la pelota (lo de fuera, transparente)")
        mp4 = os.path.join(out, "x.mp4")

        def export():
            args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                      loudnorm=False), ff, os.path.join(out, "f.txt"))
            r = subprocess.run(args, capture_output=True)
            assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
            return M.frame_rgb(mp4, 1.0, 320).astype(int)
        fr = export()
        bx = int(40 + 80 * 1.0 + 30)
        assert fr[90, bx][0] > 170 and fr[90, bx][2] < 100, ("la pelota se ve", fr[90, bx])
        assert fr[20, 20][2] > 170 and fr[20, 20][0] < 80, ("el fondo se fue: se ve el azul de debajo", fr[20, 20])
        print("✓ exportado: queda la pelota y donde estaba el fondo se ve la pista de debajo")
        ctrl.set_clip_props([top], "inv", fx=dict(p.clips[top].fx, subject_mask=dict(sm, invert=True)))
        fr = export()
        assert fr[90, bx][2] > 170, ("invertido: la pelota se fue (se ve el azul)", fr[90, bx])
        assert fr[20, 20][2] < 200 or fr[20, 20][0] > 60, ("y el fondo queda", fr[20, 20])
        print("✓ invertido: se quita la pelota y queda el fondo")
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
