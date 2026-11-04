"""
Prueba de 🎞 fotogramas clave de POSICIÓN y TAMAÑO de una capa:
  · claves en el tiempo del archivo (siguen al contenido); suave entre claves; Ctrl+Z;
  · al exportar, la capa está donde dicen las claves en cada fotograma (también en una imagen y en un fotograma
    exportado a mitad de la animación);
  · en el visor: la capa animada se dibuja en su sitio de ese momento; arrastrarla con la animación activa crea
    la clave del cabezal;
  · Inspector (◀ ◆ Clave ✕ Clave ▶ · Quitar animación), dividir, pegar atributos y «En pantalla» fijo.
Ejecutar:  .venv/Scripts/python.exe tests/test_layout_keys.py <carpeta_salida>
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

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H = 640, 360


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def red_box(rgb: np.ndarray):
    """Recuadro de la capa roja (fracciones x, y, w, h) en un fotograma."""
    m = (rgb[..., 0] > 160) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)
    ys, xs = np.nonzero(m)
    if len(xs) < 20:
        return None
    h, w = m.shape
    return xs.min() / w, ys.min() / h, (xs.max() + 1 - xs.min()) / w, (ys.max() + 1 - ys.min()) / h


def close(a, b, tol=0.03):
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


def frame(ff, path, t):
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(H, W, 3)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import transform as TR
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()

    # --- la interpolación (suave por defecto; lineal si se pide) ---
    kf = [{"t": 0.0, "x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2}, {"t": 2.0, "x": 0.6, "y": 0.4, "w": 0.4, "h": 0.4}]
    v = TR.layout_value_at(kf, 1.0)
    assert abs(v["x"] - 0.3) < 1e-6 and abs(v["w"] - 0.3) < 1e-6
    assert TR.layout_value_at(kf, 0.5)["x"] < 0.6 * 0.25, "suave: despacio al salir"
    assert abs(TR.layout_value_at([dict(kf[0], i="linear"), kf[1]], 0.5)["x"] - 0.15) < 1e-6
    print("✓ interpolación suave (y lineal si se pide) entre claves")

    files = {}
    for name, col, src in (("fondo", "navy", "color"), ("rojo", "red", "color")):
        files[name] = os.path.join(out, f"{name}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=c={col}:s=320x180:d=6:r=30",
                        "-pix_fmt", "yuv420p", files[name]], check=True)
    png = os.path.join(out, "rojo.png")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180", "-frames:v", "1",
                    png], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    p.width, p.height = W, H
    bid, rid, iid = ctrl.import_now([files["fondo"], files["rojo"], png])
    while ctrl.analyzing:
        pump(app, 0.1)
    v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
    ctrl.add_media([bid], v1.id, 0.0)
    (top,) = [i for i in ctrl.add_media([rid], v2.id, 0.0) if p.clips[i].track_id == v2.id]
    c = p.clips[top]
    c.source_in, c.duration = 1.0, 5.0              # el clip empieza en el segundo 1 del archivo
    A = {"x": 0.05, "y": 0.1, "w": 0.25, "h": 0.25}
    B = {"x": 0.55, "y": 0.5, "w": 0.4, "h": 0.4}
    ctrl.set_layout_key(top, 0.5, dict(TR.FULL, **A))
    ctrl.set_layout_key(top, 3.5, dict(TR.FULL, **B))
    assert [round(k["t"], 2) for k in c.layout_kf] == [1.5, 4.5], "en segundos DEL ARCHIVO"
    assert ctrl.layout_key_times(top) == [0.5, 3.5]
    mid = TR.layout_at(c, 2.0)
    assert abs(mid["x"] - 0.30) < 0.01 and abs(mid["w"] - 0.325) < 0.01, mid
    print("✓ dos claves (0,5 s y 3,5 s) guardadas en el tiempo del archivo; a mitad, a mitad de camino")

    # --- exportar: la capa está donde dicen las claves ---
    vid = os.path.join(out, "anim.mp4")
    args, _ = build_command(p, ExportOptions(path=vid, width=W, height=H, fps=30.0, encoder="cpu", bitrate_mbps=6,
                                             subtitles=False, loudnorm=False, video_only=True),
                            ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    for t, want in ((0.2, A), (2.0, TR.layout_at(c, 2.0)), (4.5, B)):
        got = red_box(frame(ff, vid, t))
        exp = (want["x"], want["y"], want["w"], want["h"])
        assert close(got, exp), (t, got, exp)
    print("✓ exportado: en 0,2 s / 2 s / 4,5 s la capa está y mide lo que dicen las claves")

    # --- fotograma exportado a mitad de la animación ---
    from editoria.core.still import render_frame
    still = os.path.join(out, "still.png")
    render_frame(p, 2.0, still, ff)
    from PIL import Image
    got = red_box(np.asarray(Image.open(still).convert("RGB").resize((W, H))))
    assert close(got, (mid["x"], mid["y"], mid["w"], mid["h"])), got
    print("✓ 📸 el fotograma a mitad de la animación también")

    # --- visor ---
    win.engine.seek(2.0)
    pump(app, 0.3)
    layer = win.preview.canvas.layer(v2.id)
    br = layer.box.rect()
    pos = layer.box.pos()
    got = (pos.x() / W + br.x() / W, pos.y() / H + br.y() / H, br.width() / W, br.height() / H)
    assert close(got, (mid["x"], mid["y"], mid["w"], mid["h"]), 0.02), got
    print("✓ visor: la capa animada se dibuja en su sitio de ese momento")

    # --- arrastrar en el visor con la animación activa = clave en el cabezal ---
    win.timeline.set_selection([top])
    win.engine.seek(5.0)
    pump(app, 0.2)
    win._tf_live(top, dict(TR.FULL, x=0.0, y=0.0, w=0.5, h=0.5))
    assert p.clips[top].layout_kf[-1]["x"] == 0.55, "mientras arrastras no se tocan las claves"
    win._tf_done(top, None, dict(TR.FULL, x=0.0, y=0.0, w=0.5, h=0.5))
    assert len(p.clips[top].layout_kf) == 3 and ctrl.layout_key_times(top)[-1] == 5.0
    ctrl.undo_stack.undo()
    assert len(p.clips[top].layout_kf) == 2
    print("✓ arrastrar/escalar en el visor con animación = clave en el cabezal (Ctrl+Z la quita)")

    # --- Inspector ---
    ins = win.inspector
    pump(app, 0.2)
    win.engine.seek(0.5)
    ins._refresh_framing()
    assert "2 claves" in ins.lk_label.text() and "aquí" in ins.lk_label.text(), ins.lk_label.text()
    ins._jump_lk(1)
    pump(app, 0.1)
    assert abs(win.engine.time - 3.5) < 0.05, win.engine.time
    ins.btn_del_lk.click()
    assert len(p.clips[top].layout_kf) == 1
    ctrl.undo_stack.undo()
    win.engine.seek(2.0)
    ins.btn_clear_lk.click()
    assert not p.clips[top].layout_kf and abs(p.clips[top].layout["x"] - mid["x"]) < 0.01, "se queda quieto donde estaba"
    ctrl.undo_stack.undo()
    assert len(p.clips[top].layout_kf) == 2
    print("✓ Inspector: ◀ ▶ saltan entre claves, ✕ Clave y «Quitar animación» (se queda donde estaba)")

    # --- dividir, pegar atributos, disposición fija ---
    ctrl.split_at_times(top, [2.0])
    pieces = sorted((x for x in p.clips.values() if x.track_id == v2.id), key=lambda x: x.start)
    assert len(pieces) == 2 and all(len(x.layout_kf) == 2 for x in pieces)
    assert close(tuple(TR.layout_at(pieces[1], 0.0)[k] for k in "xywh"), tuple(mid[k] for k in "xywh"), 0.01), \
        "al dividir, la animación sigue igual (claves en el tiempo del archivo)"
    ctrl.undo_stack.undo()
    ctrl.set_layout([top], TR.LAYOUTS["Mitad derecha"])
    assert not p.clips[top].layout_kf, "una disposición fija («En pantalla») quita la animación"
    ctrl.undo_stack.undo()
    assert len(p.clips[top].layout_kf) == 2
    print("✓ dividir conserva la animación; «En pantalla» fijo la quita (Ctrl+Z la devuelve)")

    # --- imagen: claves desde el inicio del clip, también en un trozo (exportación en paralelo / fotograma) ---
    (img_c,) = [i for i in ctrl.add_media([iid], v2.id, 6.5) if p.clips[i].track_id == v2.id]
    t_img = p.clips[img_c].start
    ctrl.set_layout_key(img_c, t_img + 0.5, dict(TR.FULL, **A))
    ctrl.set_layout_key(img_c, t_img + 2.5, dict(TR.FULL, **B))
    ic = p.clips[img_c]
    assert [round(k["t"], 2) for k in ic.layout_kf] == [0.5, 2.5]
    still2 = os.path.join(out, "still2.png")
    render_frame(p, ic.start + 1.5, still2, ff)
    got = red_box(np.asarray(Image.open(still2).convert("RGB").resize((W, H))))
    want = TR.layout_at(ic, 1.5, True)
    assert close(got, (want["x"], want["y"], want["w"], want["h"])), (got, want)
    print("✓ imágenes: claves desde el inicio del clip; bien también al exportar solo un trozo")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
