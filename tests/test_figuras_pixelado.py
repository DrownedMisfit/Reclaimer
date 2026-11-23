"""
Prueba de ▭ Figuras geométricas (página ✦ Efectos): el VISOR enseña lo mismo que la EXPORTACIÓN.
  · 🙈 tapar con PIXELADO (cuadro y círculo): en la exportación la zona sale en bloques del tamaño que pinta el visor
    (block_px) y fuera de las zonas la imagen no cambia; el visor tiene los mismos bloques;
  · ▭ ◯ figuras de color: en el mismo sitio y del mismo color en el visor y en la exportación; fuera del círculo (las
    esquinas de su caja) se ve el video en los dos;
  · B5 cambiar el color con un rectángulo y un círculo elegidos = UN solo Ctrl+Z, mensaje sin «(▭)»; con las figuras
    bloqueadas no se crea ningún generador sin usar.
Fuente: una imagen fija de ruido (comparaciones exactas, sin movimiento). Sin ventanas visibles, sin sonido.
Ejecutar (con el turno):  turno.py tests/test_figuras_pixelado.py [carpeta_salida]
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
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog  # noqa: E402

FALLOS = []


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def cerca(a, b, tol=16):
    return all(abs(int(x) - int(y)) < tol for x, y in zip(a, b))


def saltos(zona: np.ndarray) -> int:
    """Columnas donde la imagen cambia de golpe (en una zona pixelada: solo en los bordes de los bloques)."""
    d = np.abs(np.diff(zona.astype(int), axis=1)).sum(axis=2).mean(axis=0)
    return int((d > 25).sum())


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_figuras_pixelado")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core.model import TRACK_VIDEO
    from editoria.core.motion_track import block_px
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    ff = media_tools.ffmpeg()
    # colores que cambian despacio + ruido fino en bloques de 4 px (sin pixelar, cada pocas columnas cambia; pixelado
    # = bloques lisos de colores distintos). Del tamaño del proyecto: nada se reescala al comparar.
    rng = np.random.default_rng(7)
    W, H = 1920, 1080
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    campo = np.stack([128 + 80 * np.sin(xx / 37 + c) * np.cos(yy / 53 - c) for c in (0.0, 2.1, 4.2)], axis=2)
    fino = np.kron(rng.integers(-40, 41, (H // 4, W // 4, 3)), np.ones((4, 4, 1), np.int64))
    ruido = np.ascontiguousarray(np.clip(campo + fino, 0, 255).astype(np.uint8))
    png = os.path.join(out, "ruido.png")
    QImage(ruido.tobytes(), W, H, W * 3, QImage.Format_RGB888).save(png)
    vid = os.path.join(out, "ruido.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", png, "-t", "4", "-r", "30", "-c:v",
                    "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv444p", vid], check=True)
    win = MainWindow()
    win.show()
    win.resize(1600, 950)
    pump(app, 0.6)
    ctrl, eng, pv, ep = win.ctrl, win.engine, win.preview, win.effects
    p = ctrl.project
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media(ids, v1.id, 0.0)
    pump(app, 0.4)
    vclip = next(c for c in p.clips.values() if p.track(c.track_id).kind == TRACK_VIDEO)
    PW, PH = p.width, p.height
    print(f"   proyecto {PW}×{PH}")

    print("— 🙈 zonas pixeladas —")
    eng.seek(1.0)
    win.timeline.set_selection([vclip.id])
    pump(app, 0.2)
    ep.region_mode.setCurrentIndex(ep.region_mode.findData("pixel"))
    ep.add_region("rect")
    ep.add_region("ellipse")
    regs = p.clips[vclip.id].fx["blur_regions"]
    chk(len(regs) == 2 and all(r.get("mode") == "pixel" for r in regs), "dos zonas nuevas, pixeladas")
    fx = dict(p.clips[vclip.id].fx)
    fx["blur_regions"] = [dict(regs[0], x=0.25, y=0.5, w=0.3, h=0.5), dict(regs[1], x=0.78, y=0.5, w=0.2, h=0.3)]
    ctrl.set_clip_props([vclip.id], "Mover zonas", fx=fx)
    pump(app, 0.2)
    chk(ep.zonas.count() == 2 and "pixelado" in ep.zonas.item(0).text(), "la lista enseña las dos zonas pixeladas")

    print("— ▭ ◯ figuras de color —")
    eng.seek(0.0)
    cid = ep.add_shape("rect")
    cid2 = ep.add_shape("ellipse")
    chk(bool(cid and cid2) and p.clips[cid].track_id != vclip.track_id, "las figuras van encima, en otra pista")
    ctrl.set_clip_props([cid], "Mover", layout=dict(p.clips[cid].layout, x=0.40, y=0.05, w=0.2, h=0.15))
    ctrl.set_clip_props([cid2], "Mover", layout=dict(p.clips[cid2].layout, x=0.40, y=0.70, w=0.2, h=0.25))
    pump(app, 0.3)
    col = ep._color_fig
    rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))

    # exportación
    mp4 = os.path.join(out, "export.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=PW, height=PH, fps=30, encoder="cpu",
                                              bitrate_mbps=40), ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
    if not chk(r.returncode == 0, "exporta con zonas pixeladas y figuras"):
        print(r.stderr.decode(errors="replace")[-1500:])
        sys.exit(1)
    fo = media_tools.frame_rgb(mp4, 2.0, PW)
    eh, ew = fo.shape[:2]
    import cv2
    fi = cv2.resize(media_tools.frame_rgb(vid, 2.0, W), (ew, eh), interpolation=cv2.INTER_AREA)

    def ex(fx_, fy_, img=fo):
        return img[int(fy_ * eh), int(fx_ * ew)]
    chk(cerca(ex(0.5, 0.125), rgb), f"exportación: rectángulo de su color ({tuple(ex(0.5, 0.125))} ≈ {rgb})")
    chk(cerca(ex(0.5, 0.825), rgb), f"exportación: círculo de su color en el centro ({tuple(ex(0.5, 0.825))})")
    chk(cerca(ex(0.595, 0.71), ex(0.595, 0.71, fi), 40), "exportación: la esquina de la caja del círculo deja ver el video")
    zona = fo[int(0.30 * eh):int(0.70 * eh), int(0.12 * ew):int(0.38 * ew)]
    blo = block_px(0.3 * PW, 0.5 * PH, regs[0]["amount"], "pixel") * ew / PW
    s_ex = saltos(zona)
    print(f"   exportación: {s_ex} saltos en {zona.shape[1]} px (bloque {blo:.0f} px → ~{zona.shape[1] / blo:.0f})")
    chk(1 <= s_ex <= zona.shape[1] / blo + 3, "exportación: la zona sale en bloques del tamaño del visor")
    chk(saltos(fi[int(0.30 * eh):int(0.70 * eh), int(0.12 * ew):int(0.38 * ew)]) > 5 * max(1, s_ex),
        "(sin pixelar, esa zona cambia en casi cada columna)")
    zc = fo[int(0.42 * eh):int(0.58 * eh), int(0.74 * ew):int(0.82 * ew)]
    chk(saltos(zc) <= zc.shape[1] / 4, "exportación: el círculo pixelado también")
    fuera = np.abs(fo[int(0.05 * eh):int(0.22 * eh), int(0.03 * ew):int(0.3 * ew)].astype(int)
                   - fi[int(0.05 * eh):int(0.22 * eh), int(0.03 * ew):int(0.3 * ew)].astype(int)).mean()
    chk(fuera < 8, f"exportación: fuera de las zonas y figuras, la imagen igual ({fuera:.1f})")

    # visor
    win.timeline.set_selection([])
    eng.seek(2.0)
    pump(app, 1.5)
    cv = pv.canvas
    cv.fit_view()
    pump(app, 0.5)
    img = cv.grab().toImage().convertToFormat(QImage.Format_RGB888)
    img.save(os.path.join(out, "visor.png"))
    cv2.imwrite(os.path.join(out, "exportacion.png"), cv2.cvtColor(fo, cv2.COLOR_RGB2BGR))
    iw, ih = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * ih).reshape(
        ih, img.bytesPerLine())[:, :iw * 3].reshape(ih, iw, 3).copy()
    fr = cv.mapFromScene(cv.frame.sceneBoundingRect()).boundingRect()

    def vx(fx_, fy_):
        return a[int(fr.top() + fy_ * fr.height()), int(fr.left() + fx_ * fr.width())]
    print(f"   visor: lienzo {iw}×{ih}, video {fr.width()}×{fr.height()}")
    chk(cerca(vx(0.5, 0.125), rgb), f"visor: el rectángulo en el mismo sitio y color ({tuple(vx(0.5, 0.125))})")
    chk(cerca(vx(0.5, 0.825), rgb), f"visor: el círculo en el mismo sitio y color ({tuple(vx(0.5, 0.825))})")
    chk(not cerca(vx(0.595, 0.71), rgb, 40),
        f"visor: la esquina de la caja del círculo deja ver el video ({tuple(vx(0.595, 0.71))})")
    zv = a[int(fr.top() + 0.30 * fr.height()):int(fr.top() + 0.70 * fr.height()),
           int(fr.left() + 0.12 * fr.width()):int(fr.left() + 0.38 * fr.width())]
    s_vi = saltos(zv)
    print(f"   visor: {s_vi} saltos en {zv.shape[1]} px (exportación {s_ex} en {zona.shape[1]})")
    chk(zv.std() > 5 and abs(s_vi - s_ex) <= 3, "visor y exportación: los mismos bloques en la zona pixelada")

    print("— B5 cambiar el color de un rectángulo y un círculo a la vez —")
    win.timeline.set_selection([cid, cid2])
    pump(app, 0.1)
    i0 = ctrl.undo_stack.index()
    n_media = len(p.media)
    orig = QColorDialog.getColor
    QColorDialog.getColor = staticmethod(lambda *a_, **k_: QColor("#00ff00"))
    try:
        ep._color_figura()
        chk(ctrl.undo_stack.index() == i0 + 1, f"un solo Ctrl+Z ({ctrl.undo_stack.index() - i0} pasos)")
        chk(all(p.media_of(p.clips[x]).gen["c1"] == "#00ff00" for x in (cid, cid2)), "las dos figuras, de verde")
        chk({p.media_of(p.clips[x]).gen["kind"] for x in (cid, cid2)} == {"rect", "ellipse"},
            "cada una conserva su forma")
        chk("(▭)" not in ep.look_status.text() and "2 figura" in ep.look_status.text(),
            f"mensaje sin «(▭)»: «{ep.look_status.text()}»")
        ctrl.undo_stack.undo()
        chk(all(p.media_of(p.clips[x]).gen["c1"] == col for x in (cid, cid2)), "Ctrl+Z devuelve las dos a su color")
        ctrl.set_clip_props([cid, cid2], "Bloquear", locked=True)
        n_media = len(p.media)
        i1 = ctrl.undo_stack.index()
        QColorDialog.getColor = staticmethod(lambda *a_, **k_: QColor("#123456"))
        ep._color_figura()
        chk(len(p.media) == n_media and ctrl.undo_stack.index() == i1,
            "bloqueadas: no cambia nada ni deja generadores sin usar")
        chk(not any((m.gen or {}).get("c1") == "#123456" for m in p.media.values()), "ningún generador #123456")
    finally:
        QColorDialog.getColor = orig
        QSettings("EditorIA", "EditorIA").remove("efectos/color_figura")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
