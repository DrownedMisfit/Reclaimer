"""
🌑 PRUEBA de la Sombra (21/11, el «Drop Shadow» de Resolve: Efectos → «Sombra» + Inspector → Efectos → «Sombra»):
aplicarla a 2 clips elegidos es UN paso (un Ctrl+Z la quita) y exportar un PNG recortado da la sombra con SU SILUETA,
desplazada por ángulo y distancia y del color elegido. Deja una captura offscreen del visor para mirarla.
Ejecutar:  .venv/Scripts/python.exe tests/test_sombra.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

QDialog.exec = lambda self, *a: 0               # (ninguna ventana modal ni menú real puede parar la prueba)
QMenu.exec = lambda self, *a: None
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.No))

W, H = 640, 360
FALLOS: list[str] = []


def check(cond, msg):
    print(("✓ " if cond else "✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    return np.frombuffer(img.constBits(), np.uint8, bpl * h).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).astype(int)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_sombra"))
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    import cv2
    from editoria.core import decor
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO, Project
    from editoria.core.still import render_frame
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()

    # material: fondo gris, un PNG RECORTADO (círculo blanco sobre transparente) y un video corto
    gris, png, vid = (os.path.join(out, n) for n in ("gris.png", "circulo.png", "video.mp4"))
    cv2.imwrite(gris, np.full((H, W, 3), 128, np.uint8))
    rgba = np.zeros((300, 300, 4), np.uint8)
    cv2.circle(rgba, (150, 150), 120, (255, 255, 255, 255), -1, cv2.LINE_AA)
    cv2.imwrite(png, rgba)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=30:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True,
                   stdin=subprocess.DEVNULL)

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.5)
    ctrl, ins = win.ctrl, win.inspector
    ctrl.set_settings(width=W, height=H)
    m_gris, m_png, m_vid = ctrl.import_now([gris, png, vid])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    p = ctrl.project
    if not any(t.kind == TRACK_VIDEO for t in p.tracks):
        ctrl.add_track(TRACK_VIDEO)
    v1 = next(t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO)
    c_gris = ctrl.add_media([m_gris], v1.id, 0.0, audio=False)[0]
    c_vid = next(i for i in ctrl.add_media([m_vid], v1.id, p.clips[c_gris].end, audio=False)
                 if p.track(p.clips[i].track_id).kind == TRACK_VIDEO)
    c_png = ctrl.add_media([m_png], v1.id, 0.0, audio=False)[0]       # (ocupado: va a la pista de encima)
    t_img = min(p.clips[c_png].end, p.clips[c_gris].end) / 2

    # 1) Efectos → Sombra en 2 clips elegidos (un video y el PNG): la de fábrica, UN paso, y abre su sección
    win.show_panel(win.effects)
    win.timeline.set_selection([c_vid, c_png])
    pump(app, 0.3)
    i0 = ctrl.undo_stack.index()
    win.effects.b_sombra.click()
    pump(app, 0.5)
    fab = decor.sombra(**decor.SOMBRA_EFECTO)
    check(all((p.clips[i].fx or {}).get("shadow") == fab for i in (c_vid, c_png)) and ctrl.undo_stack.index() == i0 + 1,
          f"Efectos → Sombra: la pequeña de fábrica en los 2 clips, en UN paso ({fab})")
    check(ins.secciones["sombra"].isVisible() and ins.sombra_fuerza.hasFocus(),
          "abre Inspector → Efectos → «Sombra» con el foco en «Fuerza»")
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    check(all("shadow" not in (p.clips[i].fx or {}) for i in (c_vid, c_png)), "un Ctrl+Z la quita de los dos")

    # (una línea: arrastrar un control del Inspector = un solo paso)
    win.timeline.set_selection([c_png])
    pump(app, 0.3)
    ins.poner_sombra()
    i0, vd = ctrl.undo_stack.index(), ins.sombra_angulo
    vd._poner_arrastre(True), [vd.setValue(a) for a in (120, 100, 90)], vd._poner_arrastre(False)
    check(ctrl.undo_stack.index() == i0 + 1 and abs(decor.shadow_of(p.clips[c_png].fx)["angle"] - 90) < 1e-9,
          "arrastrar el ángulo en el Inspector es UN paso")

    # 2) exportar el PNG recortado: sombra azul con SU silueta, desplazada por ángulo y distancia
    sin = {k: v for k, v in (p.clips[c_png].fx or {}).items() if k != "shadow"}
    ctrl.set_clip_props([c_png], "Sin sombra", fx=sin or None)
    ruta0 = os.path.join(out, "export_sin_sombra.png")
    render_frame(Project.from_dict(p.to_dict()), t_img, ruta0, ff)
    medida = decor.sombra(1.0, 135.0, 0.04, 0.003, "#0000FF")
    ctrl.set_clip_props([c_png], "Sombra de prueba", fx=dict(sin, shadow=medida))
    ruta = os.path.join(out, "export_sombra.png")
    render_frame(Project.from_dict(p.to_dict()), t_img, ruta, ff)
    img = rgb(QImage(ruta))
    blanco = (img > 200).all(2)
    caja = [(lambda ys, xs: (xs.min(), ys.min(), xs.max(), ys.max()))(*np.nonzero(b)) for b in
            ((rgb(QImage(ruta0)) > 200).all(2), blanco)]
    check(all(abs(int(a) - int(b)) <= 1 for a, b in zip(*caja)), f"con la sombra nueva el clip mide lo mismo que sin "
          f"ella (no encoge; la sombra sale por fuera): {caja[0]} → {caja[1]}")
    azul = (img[..., 2] - img[..., 0] > 60) & (img[..., 2] - img[..., 1] > 60)
    d = int(round(medida["dx"] * min(W, H)))
    esperado = np.zeros_like(blanco)
    esperado[d:, d:] = blanco[:-d, :-d]
    esperado &= ~blanco
    iou = (azul & esperado).sum() / max(1, (azul | esperado).sum())
    ys, xs = np.nonzero(blanco)
    r = int(np.sqrt(blanco.sum() / np.pi))
    esquina = img[int(ys.mean()) + int(1.2 * r) + d - 5, int(xs.mean()) + int(1.2 * r) + d - 5]  # (transparente)
    check(iou > 0.6 and not (esquina[2] - esquina[0] > 60),
          f"la sombra sigue la SILUETA del círculo desplazada {d} px abajo a la derecha (IoU {iou:.2f}; la esquina "
          f"transparente del PNG no da sombra: {esquina.tolist()})")
    check(azul.sum() > 300 and img[azul].mean(0)[2] > 200, f"del color elegido (azul {img[azul].mean(0).round().tolist()})")

    # (una línea: un fx["shadow"] de antes, sin color, sigue negro y con la cadena de FFmpeg de siempre)
    vieja = {"shadow": {"opacity": 0.6, "blur": 0.02, "dx": 0.008, "dy": 0.012}}
    check(decor.shadow_of(vieja)["color"] == "#000000" and "lutrgb" not in "".join(
          decor.ffmpeg_frame(0, vieja, 300, 300, W, H, "s")[0]), "una sombra de antes (sin color) sigue igual: negra")

    # (un video a pantalla completa con la sombra de fábrica se exporta bien: la sombra cae fuera y la imagen no cambia)
    t_vid = (p.clips[c_vid].start + p.clips[c_vid].end) / 2
    rv0, rv1 = os.path.join(out, "export_video_sin.png"), os.path.join(out, "export_video_sombra.png")
    render_frame(Project.from_dict(p.to_dict()), t_vid, rv0, ff)
    ctrl.set_clip_props([c_vid], "Sombra de fábrica", fx=dict(p.clips[c_vid].fx or {}, shadow=fab))
    render_frame(Project.from_dict(p.to_dict()), t_vid, rv1, ff)
    dif = np.abs(rgb(QImage(rv0)).astype(int) - rgb(QImage(rv1)).astype(int)).mean() if os.path.isfile(rv1) else 999
    check(dif < 3, f"video a pantalla completa con la sombra de fábrica: exporta y la imagen no cambia (dif {dif:.2f})")

    # captura offscreen del visor con la sombra de fábrica (para mirarla)
    ctrl.set_clip_props([c_png], "Sombra de fábrica", fx=dict(p.clips[c_png].fx or {}, shadow=fab))
    win.timeline.set_selection([])
    win.engine.seek(t_img)
    pump(app, 0.4)
    cv = win.preview.canvas
    cap = QImage(cv.W, cv.H, QImage.Format_RGB888)
    cap.fill(QColor(0, 0, 0))
    pt = QPainter(cap)
    pt.setRenderHint(QPainter.SmoothPixmapTransform)
    cv.scene().render(pt, QRectF(0, 0, cv.W, cv.H), QRectF(0, 0, cv.W, cv.H))
    pt.end()
    cap.save(os.path.join(out, "visor_sombra.png"))
    print(f"(capturas: {os.path.join(out, 'visor_sombra.png')} · {ruta})")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print("\n✗ FALLOS:\n  " + "\n  ".join(FALLOS))
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
