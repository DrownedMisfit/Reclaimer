"""
Prueba del 🎯 SEGUIMIENTO (automático y manual) y sus usos, con un video sintético: un cuadro con textura que cruza
la pantalla en diagonal sobre un fondo quieto (posición exacta conocida en cada instante).
  · automático en los dos sentidos desde el fotograma elegido: sigue al cuadro (error pequeño), hacia atrás también;
  · un tramo tapado → dudoso (rojo) y lo recupera;
  · clave manual: manda y arrastra lo de alrededor; todo a mano: entre claves se interpola;
  · «seguir desde aquí» vuelve a seguir a partir de una corrección;
  · 🙈 desenfocar lo seguido: la zona acompaña al cuadro en el visor y en la exportación (un solo Ctrl+Z);
  · 📌 pegar un texto (que empieza más tarde) y una imagen al objeto: siguen al cuadro con su desfase (visor y
    exportación); Ctrl+Z en un paso;
  · clip volteado (visor = exportación), video movido, zoom y dividir: el tapado y lo pegado se recalculan solos;
    cada trozo guarda solo su tramo del recorrido; «pegar atributos» no copia el tapado;
  · guardar y abrir el proyecto conserva los recorridos; un proyecto viejo (sin recorridos) se abre igual.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_seguimiento.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
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
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H, OBJ = 640, 360, 64


def truth(t: float) -> tuple[float, float]:
    """Centro del cuadro (0–1) en el segundo t del video."""
    return (40 + 70 * t + OBJ / 2) / W, (60 + 30 * t + OBJ / 2) / H


def true_rect(t: float) -> QRectF:
    cx, cy = truth(t)
    return QRectF(cx - OBJ / W / 2, cy - OBJ / H / 2, OBJ / W, OBJ / H)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def wait_job(app, dlg, limit=120):
    t0 = time.time()
    while dlg.job is not None and time.time() - t0 < limit:
        pump(app, 0.05)
    assert dlg.job is None, "el seguimiento no terminó"
    pump(app, 0.1)


def centroid(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    assert len(xs) > 20, f"no se ve ({len(xs)} px)"
    return xs.mean() / mask.shape[1], ys.mean() / mask.shape[0]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import motion_track as MT
    from editoria.core import transform
    from editoria.core.model import TRACK_TEXT, TRACK_VIDEO, Project
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.preview import LookEffect
    from editoria.ui.subtitle_item import paint_title
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui.tracking_dialog import TrackingDialog
    apply_dark_theme(app)
    ff = M.ffmpeg()

    # --- video sintético: fondo gris con textura y un cuadro gris con textura que va en diagonal
    bg, obj, vid = (os.path.join(out, n) for n in ("fondo.png", "objeto.png", "cuadro.mp4"))
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:d=1",
                    "-vf", "eq=brightness=-0.4,hue=s=0", "-frames:v", "1", bg], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s={OBJ}x{OBJ}:d=1",
                    "-vf", "hue=s=0", "-frames:v", "1", obj], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", bg, "-loop", "1", "-i", obj,
                    "-filter_complex", "[0:v][1:v]overlay=x='40+70*t':y='60+30*t':shortest=1,format=yuv420p",
                    "-t", "6", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    occ = os.path.join(out, "tapado.mp4")           # lo mismo con la pantalla tapada entre 2,5 y 3,2 s
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", bg, "-loop", "1", "-i", obj,
                    "-filter_complex", "[0:v][1:v]overlay=x='40+70*t':y='60+30*t':shortest=1,"
                    "drawbox=x=0:y=0:w=iw:h=ih:color=gray:t=fill:enable='between(t,2.5,3.2)',format=yuv420p",
                    "-t", "6", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", occ], check=True)
    red = os.path.join(out, "rojo.png")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=40x40:d=1",
                    "-frames:v", "1", red], check=True)

    # --- 1. el seguidor solo (sin interfaz): pérdida y recuperación
    from editoria.ai import tracking
    r = tracking.track_auto(occ, 1.0, 6.0, (*truth(1.0), OBJ / W, OBJ / H), W, H)
    assert r["lost"] and 2.4 <= r["lost"][0][0] <= 2.7 and 3.0 <= r["lost"][0][1] <= 3.4, r["lost"]
    assert not r["stopped"] and r["end"] > 5.8, r
    err = max(max(abs(s[1] - truth(s[0])[0]), abs(s[2] - truth(s[0])[1])) for s in r["samples"])
    assert err < 0.02, err
    print(f"✓ tapado entre 2,5 y 3,2 s: tramo dudoso {r['lost'][0]} y lo recupera (error {err:.3f})")

    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    p.width, p.height = W, H
    vid_id, red_id = ctrl.import_now([vid, red])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    cid = ctrl.add_media([vid_id], v1.id, 0.0)[0]
    pump(app, 0.2)

    # --- 2. automático en los dos sentidos desde el segundo 2
    dlg = TrackingDialog(ctrl, cid, 2.0, win)
    dlg.show()
    pump(app, 0.2)
    assert abs(dlg.s - 2.0) < 0.02
    dlg._on_box_edited(true_rect(2.0))                # el usuario marca el cuadro (clave manual)
    dlg.track("both")
    assert dlg.job is not None
    wait_job(app, dlg)
    trk = dlg.trk
    sp = MT.span(trk)
    assert sp[0] < 0.1 and sp[1] > 5.8, sp
    errs = [max(abs(MT.box_at(trk, t)[0] - truth(t)[0]), abs(MT.box_at(trk, t)[1] - truth(t)[1]))
            for t in np.arange(0.0, 5.9, 0.25)]
    assert max(errs) < 0.02, errs
    back = max(errs[:8])
    print(f"✓ automático ◀▶ desde 0:02: sigue al cuadro de 0 a 6 s (error máx {max(errs):.3f}; "
          f"hacia atrás {back:.3f}); {len(trk['auto'])} muestras")

    # --- 3. clave manual: manda y arrastra lo de alrededor
    dlg.seek(4.0)
    shifted = true_rect(4.0).translated(0.05, 0.0)
    dlg._on_box_edited(shifted)
    assert dlg._state_here() == "manual"
    b4 = MT.box_at(dlg.trk, 4.0)
    assert abs(b4[0] - (truth(4.0)[0] + 0.05)) < 0.004, (b4, truth(4.0))
    near = MT.box_at(dlg.trk, 4.0 + 2 / 15)[0] - truth(4.0 + 2 / 15)[0]
    far = MT.box_at(dlg.trk, 5.5)[0] - truth(5.5)[0]
    assert 0.025 < near < 0.055 and abs(far) < 0.015, (near, far)
    print(f"✓ clave manual: manda en su fotograma y arrastra los de al lado ({near:.3f}) cada vez menos "
          f"(a 1,5 s: {far:.3f})")

    # --- 4. «seguir desde aquí»: lo automático de después estaba mal; se corrige y se vuelve a seguir
    bad = [[round(t, 4), truth(t)[0] + 0.12, truth(t)[1], OBJ / W, OBJ / H, 0.9] for t in np.arange(3.0, 6.0, 1 / 15)]
    dlg._changed(MT.replace_auto(dlg.trk, 3.0, 6.0, bad, []))
    dlg.seek(3.0)
    dlg._on_box_edited(true_rect(3.0))
    k4 = MT.manual_at(dlg.trk, 4.0)
    dlg._changed(MT.remove_manual(dlg.trk, k4[0])[0])          # (la clave mala de 4 s fuera)
    assert abs(MT.box_at(dlg.trk, 5.0)[0] - truth(5.0)[0]) > 0.08     # ahora mismo: mal
    dlg.track("fwd")
    wait_job(app, dlg)
    e5 = abs(MT.box_at(dlg.trk, 5.0)[0] - truth(5.0)[0])
    assert e5 < 0.02, e5
    print(f"✓ «Seguir desde aquí»: tras corregir en 0:03, lo de después vuelve a seguir bien (error {e5:.3f})")

    # --- 5. todo a mano: dos claves y en medio se interpola
    main_id = dlg.trk["id"]
    dlg._new_track()
    dlg.seek(1.0)
    dlg._on_box_edited(true_rect(1.0))
    dlg.seek(3.0)
    dlg._on_box_edited(true_rect(3.0))
    dlg.seek(2.0)
    assert dlg._state_here() == "interp"
    b2 = MT.box_at(dlg.trk, 2.0)
    assert abs(b2[0] - truth(2.0)[0]) < 0.003 and abs(b2[1] - truth(2.0)[1]) < 0.003, (b2, truth(2.0))
    dlg.step(1)
    dlg.step_seconds(1.0)
    assert abs(dlg.s - (2.0 + 1 / 30 + 1.0)) < 0.01, dlg.s
    print("✓ a mano: claves en 0:01 y 0:03; en 0:02 el recuadro está en medio (← → y Mayús funcionan)")
    dlg.track_combo.setCurrentIndex(dlg.track_combo.findData(main_id))
    assert dlg.trk["id"] == main_id

    # --- 6. 🙈 desenfocar lo seguido (un solo Ctrl+Z, guarda el recorrido a la vez)
    n0 = ctrl.undo_stack.count()
    dlg.use_combo.setCurrentIndex([k for k, _l in __import__("editoria.ui.tracking_dialog",
                                                             fromlist=["USES"]).USES].index("blur"))
    assert dlg.apply_use() is not None
    c = p.clips[cid]
    assert ctrl.undo_stack.count() == n0 + 1
    assert MT.find(c, main_id) is not None and c.fx.get("tracked_blur")
    for t in (1.0, 5.0):
        rg = MT.regions_at(c.fx, t)[0]
        assert abs(rg["x"] - truth(t)[0]) < 0.02 and abs(rg["y"] - truth(t)[1]) < 0.03, (t, rg, truth(t))
    ctrl.undo_stack.undo()
    c = p.clips[cid]
    assert not (c.fx or {}).get("tracked_blur") and MT.find(c, main_id) is None
    ctrl.undo_stack.redo()
    c = p.clips[cid]
    assert c.fx.get("tracked_blur") and MT.find(c, main_id) is not None
    print("✓ 🙈 tapar: la zona acompaña al cuadro (0:01 y 0:05); recorrido + tapado = un paso de Ctrl+Z")

    # En el visor: la zona del efecto se mueve con el cuadro
    win.engine.seek(5.0)
    pump(app, 0.6)
    eff = win.preview.canvas.layers[v1.id].box.graphicsEffect()
    assert isinstance(eff, LookEffect), eff
    mov = [rg for rg in eff.regions if rg.get("mode")]
    assert mov and abs(mov[0]["x"] - truth(5.0)[0]) < 0.02, mov
    print(f"✓ visor: zona en x={mov[0]['x']:.3f} (el cuadro está en {truth(5.0)[0]:.3f})")

    # --- 7. 📌 pegar un texto (empieza más tarde) y una imagen al objeto
    ref = 2.0
    ox, oy = truth(ref)
    tid_txt = ctrl.add_text(1.5, 4.4, "OO", x=round(ox, 4), y=round(oy - 0.18, 4), color="#00FF00", box=False,
                            size=9.0, stroke_size=0.0, shadow=False, blur_under=0.0)
    assert isinstance(tid_txt, str), tid_txt
    vtop = ctrl.ensure_video_above(v1.id)
    img_id = ctrl.add_media([red_id], vtop, 0.5)[0]
    bw, bh = 40 / W, 40 / H
    ctrl.set_clip_props([img_id], "colocar", layout={"x": ox + 0.15 - bw / 2, "y": oy - bh / 2, "w": bw, "h": bh,
                                                      "fit": "contain", "bg": "none"})
    assert any(cc == cid for cc, _t in ctrl.tracked_under(tid_txt))
    dlg._fill_pin_combo(tid_txt)
    dlg.use_combo.setCurrentIndex([k for k, _l in __import__("editoria.ui.tracking_dialog",
                                                             fromlist=["USES"]).USES].index("pin"))
    win.engine.seek(ref)
    pump(app, 0.2)
    n0 = ctrl.undo_stack.count()
    assert dlg.apply_use() is not None
    assert ctrl.undo_stack.count() == n0 + 1
    txt = p.clips[tid_txt].text
    assert txt.get("pos_kf") and txt.get("pegado", {}).get("track") == main_id
    for T in (2.0, 3.5, 5.0):
        dx, dy = MT.text_offset_at(txt, T - 1.5)
        ex, ey = truth(T)
        assert abs(txt["x"] + dx - ex) < 0.02 and abs(txt["y"] + dy - (ey - 0.18)) < 0.03, (T, dx, dy)
    ctrl.undo_stack.undo()
    assert not p.clips[tid_txt].text.get("pos_kf")
    ctrl.undo_stack.redo()
    txt = p.clips[tid_txt].text
    assert txt.get("pos_kf")
    assert ctrl.pin_to_track(img_id, cid, main_id, ref) is not None
    ci = p.clips[img_id]
    for T in (1.0, 3.0, 5.0):
        b = transform.layout_at(ci, T - ci.start, True)
        ccx, ccy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        assert abs(ccx - (truth(T)[0] + 0.15)) < 0.02 and abs(ccy - truth(T)[1]) < 0.03, (T, ccx, ccy)
    assert ctrl.pinned_info(ci) and ctrl.pinned_info(p.clips[tid_txt])
    print("✓ 📌 texto (empieza en 0:01.5) e imagen pegados: siguen al cuadro con su desfase; un paso de Ctrl+Z")

    # Visor del texto: dibujado donde toca
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(Qt.black)
    pt = QPainter(img)
    paint_title(pt, txt, 5.0 - 1.5, 4.4, W, H)
    pt.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine())[:, :W * 4].reshape(H, W, 4)
    gx, gy = centroid((arr[..., 1] > 200) & (arr[..., 2] < 80) & (arr[..., 0] < 80))
    assert abs(gx - truth(5.0)[0]) < 0.03 and abs(gy - (truth(5.0)[1] - 0.18)) < 0.04, (gx, gy)
    print(f"✓ visor: el texto pegado se dibuja junto al cuadro en 0:05 ({gx:.2f}, {gy:.2f})")

    # Inspector: dice a qué está pegado
    win.timeline.set_selection([tid_txt])
    pump(app, 0.3)
    assert "Pegado" in win.inspector.text_track_info.text(), win.inspector.text_track_info.text()

    # --- 8. exportación: tapado que acompaña, texto e imagen pegados
    dlg.accept()
    pump(app, 0.2)
    c = p.clips[cid]
    assert len(MT.tracks_of(c)) == 2, [x["name"] for x in MT.tracks_of(c)]      # (el hecho a mano también)
    mp4 = os.path.join(out, "seguimiento.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=W, height=H, fps=30, encoder="cpu", loudnorm=False),
                             ff, os.path.join(out, "f.txt"))
    rr = subprocess.run(args, capture_output=True)
    assert rr.returncode == 0, rr.stderr.decode(errors="replace")[-1500:]
    import cv2
    for T in (1.0, 5.0):
        fr = M.frame_rgb(mp4, T, W).astype(np.uint8)
        src = M.frame_rgb(vid, T, W).astype(np.uint8)
        cx, cy = truth(T)
        x0, y0 = int(cx * W - 24), int(cy * H - 24)

        def sharp(a):
            g = cv2.cvtColor(a[y0:y0 + 48, x0:x0 + 48], cv2.COLOR_RGB2GRAY)
            return float(cv2.Laplacian(g, cv2.CV_64F).var())
        s_exp, s_src = sharp(fr), sharp(src)
        assert s_exp < s_src * 0.2, (T, s_exp, s_src)
        f = fr.astype(int)
        rx, ry = centroid((f[..., 0] > 200) & (f[..., 1] < 70) & (f[..., 2] < 70))
        assert abs(rx - (cx + 0.15)) < 0.025 and abs(ry - cy) < 0.035, (T, rx, ry)
        if T >= 1.5:
            gx, gy = centroid((f[..., 1] > 200) & (f[..., 0] < 90) & (f[..., 2] < 90))
            assert abs(gx - cx) < 0.03 and abs(gy - (cy - 0.18)) < 0.04, (T, gx, gy)
    print("✓ exportado: el cuadro sale desenfocado donde esté (0:01 y 0:05) y el texto y la imagen lo siguen")

    def export_frame(name, T):
        mp4x = os.path.join(out, name)
        a_, _t = build_command(p, ExportOptions(path=mp4x, width=W, height=H, fps=30, encoder="cpu", loudnorm=False),
                               ff, os.path.join(out, "f2.txt"))
        r_ = subprocess.run(a_, capture_output=True)
        assert r_.returncode == 0, r_.stderr.decode(errors="replace")[-1500:]
        return M.frame_rgb(mp4x, T, W).astype(np.uint8)

    def sharp_at(fr, cx, cy):
        x0, y0 = int(cx * W - 24), int(cy * H - 24)
        g = cv2.cvtColor(fr[y0:y0 + 48, x0:x0 + 48], cv2.COLOR_RGB2GRAY)
        return float(cv2.Laplacian(g, cv2.CV_64F).var())

    def text_at(T):
        tx = p.clips[tid_txt].text
        dx, dy = MT.text_offset_at(tx, T - p.clips[tid_txt].start)
        return tx["x"] + dx, tx["y"] + dy

    # --- 8b. ↔ clip volteado: el tapado y el pegado siguen al cuadro donde SE VE (visor = exportación)
    n0 = ctrl.undo_stack.count()
    zona = {"shape": "rect", "x": 0.15, "y": 0.15, "w": 0.2, "h": 0.2, "amount": 0.8}   # ◌ zona fija (la de antes)
    ctrl.set_clip_props([cid], "voltear", layout=dict(transform.FULL, flip_h=True, flip_v=True),
                        fx=dict(p.clips[cid].fx, blur_regions=[zona]))
    assert ctrl.undo_stack.count() == n0 + 1
    win.engine.seek(5.0)
    pump(app, 0.6)
    layer = win.preview.canvas.layers[v1.id]
    eff = layer.box.graphicsEffect()
    mov = [rg for rg in eff.regions if rg.get("mode")]
    bxr = layer.box.rect()
    loc = QRectF(bxr.left() + (mov[0]["x"] - mov[0]["w"] / 2) * bxr.width(),
                 bxr.top() + (mov[0]["y"] - mov[0]["h"] / 2) * bxr.height(),
                 mov[0]["w"] * bxr.width(), mov[0]["h"] * bxr.height())
    vis_x = layer.box.mapRectToScene(loc).center().x() / win.preview.canvas.W
    vis_y = layer.box.mapRectToScene(loc).center().y() / win.preview.canvas.H
    fx_, fy_ = 1 - truth(5.0)[0], 1 - truth(5.0)[1]       # (dónde se ve el cuadro con el clip volteado)
    assert abs(vis_x - fx_) < 0.02 and abs(vis_y - fy_) < 0.03, (vis_x, vis_y, fx_, fy_)
    est = [rg for rg in eff.regions if not rg.get("mode")]          # la zona fija: en el visor, volteada con la capa
    loc2 = QRectF(bxr.left() + (est[0]["x"] - est[0]["w"] / 2) * bxr.width(),
                  bxr.top() + (est[0]["y"] - est[0]["h"] / 2) * bxr.height(),
                  est[0]["w"] * bxr.width(), est[0]["h"] * bxr.height())
    zc = layer.box.mapRectToScene(loc2).center()
    zx, zy = zc.x() / win.preview.canvas.W, zc.y() / win.preview.canvas.H
    assert abs(zx - 0.85) < 0.02 and abs(zy - 0.85) < 0.02, (zx, zy)
    tx5 = text_at(5.0)
    assert abs(tx5[0] - fx_) < 0.02, (tx5, fx_)
    fr = export_frame("volteado.mp4", 5.0)
    src_f = M.frame_rgb(vid, 5.0, W)[::-1, ::-1].copy()
    assert sharp_at(fr, fx_, fy_) < 0.2 * sharp_at(src_f, fx_, fy_)
    assert sharp_at(fr, zx, zy) < 0.2 * sharp_at(src_f, zx, zy), (sharp_at(fr, zx, zy), sharp_at(src_f, zx, zy))
    gx, _gy = centroid((fr[..., 1].astype(int) > 200) & (fr[..., 0] < 90) & (fr[..., 2] < 90))
    assert abs(gx - fx_) < 0.03, (gx, fx_)
    print(f"✓ volteado (↔ y ↕): el tapado se ve en ({vis_x:.2f}, {vis_y:.2f}) y la ◌ zona fija en ({zx:.2f}, {zy:.2f}) "
          "en el visor, y la exportación desenfoca justo ahí; el texto pegado lo sigue")
    ctrl.undo_stack.undo()

    # --- 8c. el video se mueve en la línea de tiempo: lo pegado sigue sincronizado
    ctrl.move_clips({cid: (0.5, v1.id)})
    assert abs(p.clips[cid].start - 0.5) < 1e-6
    for T in (2.5, 4.5):
        tx = text_at(T)
        ex, ey = truth(T - 0.5)
        assert abs(tx[0] - ex) < 0.02 and abs(tx[1] - (ey - 0.18)) < 0.03, (T, tx, ex, ey)
        ci = p.clips[img_id]
        b = transform.layout_at(ci, T - ci.start, True)
        assert abs(b["x"] + b["w"] / 2 - (ex + 0.15)) < 0.02, (T, b)
    ctrl.undo_stack.undo()
    print("✓ video movido 0,5 s: el texto y la imagen pegados siguen al cuadro (se recalculan solos)")

    # --- 8d. zoom en el video: el tapado se recalcula (el cuadro cae en otro sitio de la caja)
    ctrl.set_zoom_at(cid, 2.0, 1.5, 0.5, 0.5)
    left, _top, size = transform.window(1.5, 0.5, 0.5)
    rg = MT.regions_at(p.clips[cid].fx, 5.0)[0]
    ex = (truth(5.0)[0] - left) / size
    assert abs(rg["x"] - min(ex, 1 - rg["w"] / 2)) < 0.03, (rg["x"], ex)
    tx = text_at(5.0)
    assert abs(tx[0] - ex) < 0.03, (tx, ex)
    ctrl.undo_stack.undo()
    print(f"✓ zoom 150 %: el tapado y el texto se recalculan (x={rg['x']:.3f}, esperado {ex:.3f})")

    # --- 8e. dividir: cada trozo se queda con su parte del recorrido; lo pegado sigue por los dos trozos
    ctrl.split(3.0, [cid])
    pieces = sorted([c for c in p.clips.values() if c.media_id == vid_id], key=lambda c: c.start)
    assert len(pieces) == 2
    la = MT.find(pieces[0], main_id)
    ra = MT.find(pieces[1], main_id)
    assert max(r_[0] for r_ in la["auto"]) <= 3.0 + 1.0 + 1e-3 and min(r_[0] for r_ in ra["auto"]) >= 3.0 - 1.0 - 1e-3
    assert max(r_[0] for r_ in la["auto"]) >= 3.5 and min(r_[0] for r_ in ra["auto"]) <= 2.5     # (con margen)
    for T in (2.0, 5.0):
        tx = text_at(T)
        assert abs(tx[0] - truth(T)[0]) < 0.02, (T, tx)
    assert all(c.fx.get("tracked_blur") for c in pieces)
    ctrl.undo_stack.undo()
    print("✓ dividir en 0:03: cada trozo guarda su tramo (±1 s); el texto pegado sigue al cuadro en los dos")

    # --- 8f. «Pegar atributos → efectos» no copia el tapado a otro video
    cid2 = ctrl.add_media([vid_id], vtop, 6.5)[0]
    ctrl.copy_clips([cid])
    ctrl.paste_attributes([cid2], ["efectos"])
    assert not (p.clips[cid2].fx or {}).get("tracked_blur"), p.clips[cid2].fx
    ctrl.delete_clips([cid2])
    print("✓ pegar atributos: el tapado no se copia a otro video")

    # --- 8g. cerrar la ventana a mitad de un seguimiento: lo seguido hasta ahí se guarda (un paso de Ctrl+Z)
    dlg2 = TrackingDialog(ctrl, cid, 1.0, win)
    dlg2.show()
    pump(app, 0.2)
    dlg2._new_track()
    nid = dlg2.trk["id"]
    dlg2._on_box_edited(true_rect(1.0))
    dlg2.track("fwd")
    assert not dlg2.btn_new.isEnabled() and not dlg2.btn_del.isEnabled()
    pump(app, 0.4)
    n0 = ctrl.undo_stack.count()
    dlg2.reject()
    pump(app, 0.3)
    assert dlg2.job is None
    nt = MT.find(p.clips[cid], nid)
    assert nt is not None and nt["manual"] and ctrl.undo_stack.count() == n0 + 1, (nt, ctrl.undo_stack.count() - n0)
    print(f"✓ cerrar a mitad: se para, guarda lo seguido ({len(nt['auto'])} muestras) en un paso de Ctrl+Z")

    # --- 9. guardar y abrir conserva el recorrido; un proyecto viejo se abre igual
    eia = os.path.join(out, "seguimiento.eia")
    assert ctrl.save(eia, backup=False)
    before = json.dumps(MT.tracks_of(p.clips[cid]), sort_keys=True)
    ctrl.load(eia)
    pump(app, 0.3)
    p = ctrl.project
    assert json.dumps(MT.tracks_of(p.clips[cid]), sort_keys=True) == before
    assert p.clips[cid].fx.get("tracked_blur") and p.clips[tid_txt].text.get("pos_kf") and p.clips[img_id].layout_kf
    with open(eia, encoding="utf-8") as fh:
        d = json.load(fh)
    for cd in d["clips"]:
        cd.pop("motion_tracks", None)
    old = Project.from_dict(d)
    assert all(c.motion_tracks == [] for c in old.clips.values())
    print("✓ guardar y abrir: recorridos, tapado y pegados intactos; un proyecto sin recorridos se abre igual")
    assert any(t.kind == TRACK_TEXT for t in p.tracks)

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
