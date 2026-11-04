"""
Prueba de ✨ EFECTOS SOLO AL PERSONAJE (con la máscara del recorte de sujeto; aquí una máscara hecha a mano:
mitad izquierda = el personaje):
  · «personaje a color, fondo en B/N»: encima va una copia recortada al personaje (sin sonido ni transición) y el
    original de debajo pasa a blanco y negro → al exportar, el personaje sigue a color y el fondo sale gris;
  · «resplandor en el personaje»: el efecto va en la copia (el fondo no cambia); si la pista de encima está ocupada,
    se crea una justo encima del clip;
  · un solo paso de Ctrl+Z cada vez; la ventana abre en modo «✨ Efecto solo al personaje» con sus efectos.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_subject_fx.py <carpeta_salida>
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
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.subject_cut_dialog import SubjectCutDialog
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    red = os.path.join(out, "rojo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xd02020:s=320x180:d=4",
                    "-f", "lavfi", "-i", "sine=d=4", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", red], check=True)
    mask = os.path.join(out, "mascara.mkv")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=320x180:d=4:r=30,drawbox=x=0:y=0:w=160:h=180:color=white:t=fill",
                    "-pix_fmt", "gray", "-c:v", "ffv1", mask], check=True)
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    p.width, p.height = 320, 180
    (rid,) = ctrl.import_now([red])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    cid = next(i for i in ctrl.add_media([rid], v1.id, 0.0) if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    sm = {"mask": mask, "a": 0.0, "fps": 30.0}

    def export(name):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        return M.frame_rgb(mp4, 2.0, 320).astype(int)

    n0 = ctrl.undo_stack.count()
    copy = ctrl.subject_layer(cid, sm, "bn_fondo")
    c, cp = p.clips[cid], p.clips[copy]
    assert ctrl.undo_stack.count() == n0 + 1 and c.fx.get("bw") and cp.fx["subject_mask"]["mask"] == mask
    assert cp.volume == 0 and not cp.link and p.track_index(cp.track_id) < p.track_index(c.track_id)
    fr = export("bn_fondo.mp4")
    left, right = fr[90, 60], fr[90, 260]
    assert left[0] > 170 and left[1] < 90, ("el personaje sigue a color", left)
    assert abs(right[0] - right[1]) < 20 and abs(right[1] - right[2]) < 20, ("el fondo en gris", right)
    print(f"✓ personaje a color {tuple(int(x) for x in left[:3])} y fondo en blanco y negro {tuple(int(x) for x in right[:3])} (copia encima)")
    ctrl.undo_stack.undo()
    pump(app, 0.1)
    assert copy not in p.clips and not (p.clips[cid].fx or {}).get("bw")
    print("✓ Ctrl+Z lo quita todo de una vez")

    occupied = ctrl.subject_layer(cid, sm, "nada")            # la de encima queda ocupada
    n_tracks = len(p.tracks)
    g = ctrl.subject_layer(cid, sm, "glow")
    assert len(p.tracks) == n_tracks + 1, "pista nueva justo encima del clip"
    gi, ci = p.track_index(p.clips[g].track_id), p.track_index(p.clips[cid].track_id)
    assert gi == ci - 1 and p.clips[g].fx.get("glow") and not (p.clips[cid].fx or {}).get("glow")
    assert occupied in p.clips
    print("✓ resplandor solo en la copia del personaje; con la pista de encima ocupada se crea otra justo encima")

    dlg = SubjectCutDialog(ctrl, cid, 1.0, win, fx_mode=True)
    assert dlg.fxonly.isChecked() and dlg.preset.isEnabled() and dlg.preset.count() == len(ctrl.SUBJECT_FX)
    dlg.keep.setChecked(True)
    assert not dlg.preset.isEnabled()
    dlg.close()
    print("✓ la ventana abre en «✨ Efecto solo al personaje» con sus efectos")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
