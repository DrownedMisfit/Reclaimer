"""
Prueba de los dos efectos nuevos (16/11): ⚡ «Destello de líneas» (un haz de líneas verticales blancas cruza el centro
unos 4 fotogramas al empezar el clip) y 🔍 «Entrar enfocando» (empieza muy desenfocado y se enfoca en 0,3 s).
Comprueba que se ven en sus fotogramas (y no en otros), que el desenfoque baja con el tiempo, que la exportación es
igual a lo que dibuja el visor (mismas franjas, mismo desenfoque), que el visor los pone y que el panel Efectos los
trae con su vista previa.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles ni sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_efectos_destello_enfoque.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H, FPS = 640, 360, 30


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def frames(ff, mp4, idxs):
    sel = "+".join(f"eq(n\\,{i})" for i in idxs)
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-i", mp4, "-vf", f"select={sel}", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
    arr = np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, 3)
    assert len(arr) == len(idxs), (len(arr), idxs)
    return dict(zip(idxs, arr))


def export(ctrl, ff, path, out):
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    args, _t = build_command(ctrl.project, ExportOptions(path=path, width=W, height=H, fps=FPS, encoder="cpu",
                                                         bitrate_mbps=12, max_quality=True, subtitles=False),
                             ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]


def visor_lines(bg: np.ndarray, fx: dict, t: float) -> np.ndarray:
    """Lo que dibuja el visor (preview.paint_lines con effects.lines_px) encima del fotograma sin efecto."""
    from editoria.core import effects
    from editoria.ui.preview import paint_lines
    a = np.ascontiguousarray(bg)
    img = QImage(a.data, W, H, W * 3, QImage.Format_RGB888).copy()
    p = QPainter(img)
    paint_lines(p, QRectF(0, 0, W, H), effects.lines_px(fx, t, W))
    p.end()
    img = img.convertToFormat(QImage.Format_RGB888)
    bpl = img.bytesPerLine()
    return np.frombuffer(img.constBits(), np.uint8, count=bpl * H).reshape(H, bpl)[:, :W * 3].reshape(H, W, 3).copy()


def check_fps(ff, out, fps, plano, detalle):
    """([paso visto en cada fotograma exportado], [paso del visor], peor diferencia del desenfoque) a esos fps."""
    from editoria.core import effects as E
    from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project, Track, new_id
    from editoria.export.ffmpeg_export import ExportOptions, build_command

    def exp(src, fx, name, dur):
        p = Project(width=W, height=H, fps=float(fps))
        tr = Track(new_id(), TRACK_VIDEO, "V1")
        p.tracks.append(tr)
        m = MediaItem(new_id(), src, KIND_VIDEO, "x", duration=dur, width=W, height=H, fps=30.0, has_audio=False,
                      probed=True)
        p.media[m.id] = m
        c = Clip(new_id(), m.id, tr.id, 0.0, 0.0, 0.6, fx=fx)
        p.clips[c.id] = c
        path = os.path.join(out, f"{name}_{fps}.mp4")
        args, _t = build_command(p, ExportOptions(path=path, width=W, height=H, fps=fps, encoder="cpu",
                                                  bitrate_mbps=12, max_quality=True, subtitles=False,
                                                  video_only=True), ff, os.path.join(out, "fps.txt"))
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-800:]
        r = subprocess.run([ff, "-nostdin", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        return np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, 3)
    fxl = {"lines": 0.13}
    a, b = exp(plano, fxl, "lin", 1.0).astype(float), exp(plano, None, "sin", 1.0).astype(float)
    got, want = [], []
    for n in range(int(0.25 * fps)):
        t = n / fps
        want.append(E._step(t, E.LINES_Q) if E.lines_px(fxl, t, W) else -1)
        bg = b[n].mean(-1).mean(0)
        prof = a[n].mean(-1).mean(0) - bg
        errs = {}
        for k in range(-1, 5):
            al = np.zeros(W)
            for x, bw, aa in (E.lines_px(fxl, k * E.LINES_Q, W) if k >= 0 else []):
                al[x:x + bw] = 1 - (1 - al[x:x + bw]) * (1 - aa)
            errs[k] = float(np.abs(prof - al * (255 - bg)).mean())
        got.append(min(errs, key=errs.get))
    fb, fc = exp(detalle, None, "dsin", 3.0), exp(detalle, {"focus_in": 0.3}, "dcon", 3.0)
    worst = max(float(np.abs(E.blur_bgra(fb[n], E.focus_sigma({"focus_in": 0.3}, n / fps, min(W, H))).astype(int)
                             - fc[n].astype(int)).mean()) for n in range(int(0.4 * fps)))
    return got, want, worst


def sharp(a: np.ndarray) -> float:
    import cv2
    g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import effects
    from editoria.core import fx_previews
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme

    ff = M.ffmpeg()
    plano = os.path.join(out, "plano.mp4")
    detalle = os.path.join(out, "detalle.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x30405a:s={W}x{H}:r={FPS}:d=1",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", plano], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", detalle], check=True)

    # Funciones comunes (visor y exportación): pasos fijos de tiempo
    fxl, fxf = {"lines": 0.13}, {"focus_in": 0.3}
    assert [bool(effects.lines_px(fxl, k / 30, W)) for k in range(6)] == [True] * 4 + [False] * 2
    sig = [effects.focus_sigma(fxf, k / 30, H) for k in range(12)]
    assert sig[0] > 10 and all(a > b for a, b in zip(sig[:8], sig[1:9])) and sig[9] == sig[10] == 0.0, sig
    assert effects.is_active(fxl) and effects.is_active(fxf)
    assert effects.lines_px({"lines": 3.0}, 0.6, W) == [] and effects.lines_px({"lines": 3.0}, 0.45, W)
    assert effects.focus_sigma({"focus_in": 9.0}, 1.6, H) == 0.0 and effects.focus_sigma({"focus_in": 9.0}, 1.0, H) > 0
    g = ",".join(effects.ffmpeg_filters({**fxl, **fxf}, 2.0, W, H))
    assert g.count(":planes=") == 2 and g.count("sendcmd") == 1 and "drawbox" not in g and "444" not in g, g[:300]
    assert set(effects.visible_of({**fxl, **fxf})) == {"lines", "focus_in"}
    print(f"✓ destello: 4 fotogramas (0,13 s; máx. 0,5 s); un solo par de desenfoques con sendcmd; enfoque: sigma {sig[0]:.1f} → {sig[4]:.1f} → 0 a los 0,3 s")

    # A 24 y 60 fps: cada fotograma exportado enseña el MISMO paso que el visor (líneas) y el mismo desenfoque
    for fr_ in (24, 60):
        chk = check_fps(ff, out, fr_, plano, detalle)
        assert chk[0] == chk[1] and chk[2] < 3.0, (fr_, chk)
    print("✓ a 24 y 60 fps las líneas cambian en el mismo fotograma que en el visor y el desenfoque coincide")

    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    pid, did = ctrl.import_paths([plano, detalle])
    while ctrl.analyzing:
        pump(app, 0.1)
    ctrl.set_settings(width=W, height=H, fps=float(FPS))
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]

    # 1) ⚡ Destello de líneas: plano liso de 1 s + otro de 1 s con el destello (en el corte)
    a_id = ctrl.add_media([pid], v1.id, 0.0)[0]
    b_id = ctrl.add_media([pid], v1.id, 1.0)[0]
    ctrl.batch_clip_props({b_id: {"fx": dict(fxl)}}, "prueba")
    p = ctrl.project
    b = p.clips[b_id]
    start_n = round(b.start * FPS)
    mp4 = os.path.join(out, "lineas.mp4")
    export(ctrl, ff, mp4, out)
    idx = [start_n - 1] + [start_n + k for k in range(6)]
    fr = frames(ff, mp4, idx)
    bg = fr[start_n + 5]
    lum = lambda a: a.astype(float).mean(-1)     # noqa: E731
    base = float(lum(bg).mean())
    peaks = []
    for k in range(4):
        n = start_n + k
        cols = lum(fr[n]).mean(0)
        peaks.append(float(cols.max() - base))
        assert cols.max() > base + 120, f"fotograma {n}: debería verse el destello ({cols.max():.0f} vs {base:.0f})"
        centro = cols[int(W * 0.3):int(W * 0.7)].mean() - base
        borde = np.r_[cols[:int(W * 0.08)], cols[-int(W * 0.08):]].mean() - base
        assert centro > borde + 15, (n, centro, borde)
        vis = visor_lines(bg, fxl, k / FPS)
        d = np.abs(vis.astype(int) - fr[n].astype(int))
        assert d.mean() < 3.0 and np.percentile(d.max(-1), 99) < 40, f"fotograma {n}: visor ≠ exportación ({d.mean():.2f})"
    for n in (start_n - 1, start_n + 4):
        assert np.abs(lum(fr[n]).mean(0) - base).max() < 6, f"fotograma {n}: no debería haber destello"
    print(f"✓ destello de líneas: visible en los fotogramas {start_n}–{start_n + 3} (líneas +{min(peaks):.0f} de "
          "brillo, más en el centro), nada antes ni después; la exportación = lo que dibuja el visor")

    # 2) 🔍 Entrar enfocando: clip con detalle (sin y con el efecto)
    ctrl.delete_clips([a_id, b_id])
    c_id = ctrl.add_media([did], v1.id, 3.0)[0]
    p = ctrl.project
    c0 = round(p.clips[c_id].start * FPS)
    sin = os.path.join(out, "sin_enfoque.mp4")
    export(ctrl, ff, sin, out)
    ctrl.batch_clip_props({c_id: {"fx": dict(fxf)}}, "prueba")
    con = os.path.join(out, "enfoque.mp4")
    export(ctrl, ff, con, out)
    idx = [c0 + k for k in range(12)]
    fs, fc = frames(ff, sin, idx), frames(ff, con, idx)
    nit = [sharp(fc[n]) for n in idx]
    ref = sharp(fs[c0 + 11])
    assert nit[0] < ref * 0.05, (nit[0], ref)
    assert all(b_ >= a_ * 0.98 for a_, b_ in zip(nit[:9], nit[1:10])), nit
    for k in (9, 10, 11):
        assert np.abs(fc[c0 + k].astype(int) - fs[c0 + k].astype(int)).mean() < 1.0, k
    worst = 0.0
    for k in range(9):
        s = effects.focus_sigma(fxf, k / FPS, min(W, H))
        vis = effects.blur_bgra(fs[c0 + k], s)                 # lo que hace el visor (LookEffect)
        d = float(np.abs(vis.astype(int) - fc[c0 + k].astype(int)).mean())
        worst = max(worst, d)
        assert d < 3.0, f"fotograma {k}: el desenfoque del visor y el exportado no coinciden ({d:.2f})"
    print(f"✓ entrar enfocando: nitidez {nit[0]:.0f} → {nit[4]:.0f} → {nit[8]:.0f} → nítido ({ref:.0f}) a los 0,3 s; "
          f"desenfoque del visor = exportado (diferencia media ≤ {worst:.2f}/255)")

    # 3) El visor pone los dos efectos (capa con el desenfoque y capa de líneas)
    from editoria.ui.preview import LookEffect
    ctrl.batch_clip_props({c_id: {"fx": {"focus_in": 0.3, "lines": 0.13}}}, "prueba")
    win.engine.seek(3.0 + 1 / FPS)
    pump(app, 0.6)
    layer = win.preview.canvas.layers[v1.id]
    eff = layer.box.graphicsEffect()
    assert isinstance(eff, LookEffect) and eff.focus > 0, eff
    assert layer.lines.parentItem() is None, "las líneas van fuera de la capa (su efecto no las toca)"
    assert layer.lines.isVisible() and layer.lines.bars == effects.lines_px({"lines": 0.13}, 1 / FPS,
                                                                            int(round(layer.box.rect().width())))
    win.engine.seek(3.6)
    pump(app, 0.6)
    eff = layer.box.graphicsEffect()
    assert not layer.lines.isVisible() and (eff is None or getattr(eff, "focus", 0) == 0)
    print("✓ visor: al empezar el clip, desenfoque y líneas; a los 0,6 s, ni una cosa ni la otra")
    # Volteado y con recorte de bordes: como al exportar, las líneas NO se voltean y SÍ se recortan
    from editoria.core import transform as TF
    ctrl.batch_clip_props({c_id: {"layout": dict(TF.FULL, flip_h=True, crop={"l": 0.2, "t": 0.0, "r": 0.0,
                                                                                   "b": 0.0})}}, "prueba")
    win.engine.seek(3.0 + 1 / FPS)
    pump(app, 0.6)
    assert layer.lines.isVisible() and layer.lines.transform().isIdentity(), layer.lines.transform()
    assert layer.lines.keep is not None and layer.lines.keep.left() > layer.box.rect().left() + 1
    print("✓ visor con la capa volteada y recortada: las líneas no se voltean y se recortan (como al exportar)")

    # 4) Panel Efectos: los dos botones con su vista previa; el Inspector, su duración
    from editoria.ui.effects_panel import LOOKS
    keys = {k: v for k, _t, v, _h in LOOKS}
    assert keys.get("lines") == 0.13 and keys.get("focus_in") == 0.3
    for k in ("lines", "focus_in"):
        assert fx_previews.thumb("look", k) and fx_previews.anim("look", k), f"falta la vista previa de {k}"
        assert fx_previews.anim_plain("look", k), f"falta la versión «sin efecto» de {k}"
    ins = win.inspector
    assert ins.fx_spins["lines"].maximum() == 0.5 and ins.fx_spins["focus_in"].maximum() == 1.5
    print("✓ panel Efectos: «⚡ Destello de líneas» y «🔍 Entrar enfocando» con vista previa; duración en el Inspector")

    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
