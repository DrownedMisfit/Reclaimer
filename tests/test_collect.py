"""
Prueba de 📦 RECOPILAR PROYECTO:
  · «Solo lo que se usa»: de un video de 30 s con 2 pistas de audio solo quedan los trozos usados (+ margen), con
    las DOS pistas; al exportar la copia se ve EXACTAMENTE lo mismo que el original (cada segundo tiene su propio
    gris); la transcripción y las claves de zoom se ajustan; lo que no se usa no va;
  · «Completos»: copia exacta; al mover la carpeta entera, el proyecto encuentra sus archivos en «Medios»;
  · cancelar no deja ninguna copia a medias; tu proyecto original no cambia.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_collect.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import shutil
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
    keep = {k: QSettings("EditorIA", "EditorIA").value(k) for k in ("recopilar/carpeta", "recopilar/trozos")}
    app = QApplication(sys.argv)
    try:
        run(app, out)
    finally:
        st = QSettings("EditorIA", "EditorIA")
        for k, v in keep.items():
            st.remove(k) if v is None else st.setValue(k, v)
    print("TODO OK")


def run(app, out):
    from editoria.core import collect as CO
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.collect_dialog import CollectDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    vid = os.path.join(out, "partida.mp4")          # cada segundo, un gris distinto · 2 pistas de audio
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=30:d=30,format=gray,geq=lum='mod(floor(T)*8+8,256)'",
                    "-f", "lavfi", "-i", "sine=f=300:d=30", "-f", "lavfi", "-i", "sine=f=900:d=30",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", vid], check=True)
    img = os.path.join(out, "logo.png")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=orange:s=64x64:d=1",
                    "-frames:v", "1", img], check=True)
    unused = os.path.join(out, "sin_usar.png")
    shutil.copy(img, unused)
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    p.width, p.height = 160, 90
    p.name = "Mi partida"
    vid_id, img_id, _un = ctrl.import_now([vid, img, unused])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a_id = ctrl.add_media([vid_id], v1.id, 0.0)[0]
    c1 = p.clips[a_id]
    for c in [c for c in p.clips.values() if c.link == c1.link]:
        c.source_in, c.duration = 20.0, 3.0               # 0–3 s ← segundos 20–23 del archivo
    b_id = ctrl.add_media([vid_id], v1.id, 3.0)[0]
    c2 = p.clips[b_id]
    for c in [c for c in p.clips.values() if c.link == c2.link]:
        c.source_in, c.duration, c.start = 5.0, 1.5, 3.0  # 3–4,5 s ← segundos 5–6,5
    c1.zoom_kf = [{"t": 21.0, "z": 1.5, "x": 0.5, "y": 0.5}]
    li = ctrl.add_media([img_id], [t for t in p.tracks if t.kind == TRACK_VIDEO][0].id, 1.0)[0]
    p.clips[li].layout = {"x": 0.8, "y": 0.0, "w": 0.2, "h": 0.2, "fit": "contain", "bg": "none"}
    p.transcripts[vid_id] = {"language": "es", "words": [[5.2, 5.6, "hola", 0.9], [12.0, 12.4, "fuera", 0.9],
                                                         [21.0, 21.5, "mundo", 0.9]],
                             "segments": [[5.2, 21.5, 0, 3]]}
    orig_paths = {k: m.path for k, m in p.media.items()}

    def export(proj, name, ts):
        mp4 = os.path.join(out, name)
        args, _t = build_command(proj, ExportOptions(path=mp4, width=160, height=90, fps=30, encoder="cpu",
                                                     loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        return [int(M.frame_rgb(mp4, t, 160).astype(int)[60, 20].mean()) for t in ts]

    ts = [0.5, 1.6, 2.5, 3.3, 4.2]
    ref = export(p, "original.mp4", ts)

    # 1) «Solo lo que se usa» desde la ventana
    dest = os.path.join(out, "copias")
    dlg = CollectDialog(win)
    dlg.dest.setText(dest)
    dlg.r_trim.setChecked(True)
    pump(app, 0.1)
    assert "recortados" in dlg.info.text(), dlg.info.text()
    dlg.b_go.click()
    t0 = time.time()
    while dlg.result_path is None and time.time() - t0 < 180:
        pump(app, 0.1)
        assert "⚠️" not in dlg.status.text(), dlg.status.text()
    path = dlg.result_path
    assert path and os.path.exists(path), dlg.status.text()
    dlg.close()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    from editoria.core.model import Project
    q = Project.from_dict(data)
    qm = q.media[vid_id]
    assert "Medios" in qm.path and os.path.exists(qm.path) and qm.duration < 15, (qm.path, qm.duration)
    info = M.probe(qm.path)
    assert info.get("audio_streams") == 2, info
    assert _un not in q.media and img_id in q.media, list(q.media)
    words = q.transcripts[vid_id]["words"]
    assert [w[2] for w in words] == ["hola", "mundo"], words
    qc1 = q.clips[a_id]
    assert abs(qc1.zoom_kf[0]["t"] - (qc1.source_in + 1.0)) < 0.1, (qc1.source_in, qc1.zoom_kf)
    got = export(q, "copia.mp4", ts)
    assert all(abs(a - b) <= 6 for a, b in zip(ref, got)), (ref, got)
    assert len(set(ref)) >= 4 and min(ref) > 40, ref        # (cada instante, un gris distinto: se comprueba de verdad)
    print(f"✓ «solo lo que se usa»: video de 30 s → {qm.duration:.1f} s con sus 2 pistas de audio; exportado igual "
          f"que el original {got}; transcripción y claves ajustadas; lo no usado no va")
    assert {k: m.path for k, m in p.media.items()} == orig_paths, "tu proyecto no cambia"

    # 2) completos + mover la carpeta entera
    path2 = CO.run(p, dest, False, False, lambda f, t: None, lambda: False)
    q2 = Project.from_dict(json.load(open(path2, encoding="utf-8")))
    assert os.path.getsize(q2.media[vid_id].path) == os.path.getsize(vid)
    moved = os.path.join(out, "movida")
    shutil.move(os.path.dirname(path2), moved)
    ctrl.load(os.path.join(moved, os.path.basename(path2)))
    pump(app, 0.3)
    assert not ctrl.missing and all(moved in m.path for m in ctrl.project.media.values()), ctrl.missing
    print("✓ «completos»: copia exacta; moviendo la carpeta entera, el proyecto encuentra sus archivos en «Medios»")

    # 3) cancelar: nada a medias
    before = set(os.listdir(dest))
    try:
        CO.run(p, dest, True, False, lambda f, t: None, lambda: True)
        raise AssertionError("debía cancelarse")
    except Exception as exc:  # noqa: BLE001
        assert exc.__class__.__name__ == "Cancelled", exc
    assert set(os.listdir(dest)) == before
    print("✓ cancelar no deja ninguna copia a medias")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)


if __name__ == "__main__":
    main()
