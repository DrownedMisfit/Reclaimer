"""
Prueba del desplazamiento VERTICAL de la línea de tiempo:
- la regla (y su franja de temas, el cabezal y la esquina) se queda fija arriba de lo visible al bajar las pistas;
- un clic en la regla desplazada mueve el cabezal;
- Alt + rueda desplaza las pistas en vertical (la rueda sin modificador sigue yendo por el eje horizontal);
- un proyecto nuevo tiene UNA pista de video («V1») y UNA de audio («A1»), y poner B-roll / imágenes encima crea su
  pista («V2») si no hay ninguna.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Sin ventanas visibles.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline_vscroll.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_vscroll_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def filas(img: QImage, y0: int, h: int) -> np.ndarray:
    """Las filas [y0, y0+h) de una imagen, como píxeles."""
    img = img.convertToFormat(QImage.Format_RGB32)
    bpl = img.bytesPerLine() // 4
    a = np.frombuffer(img.constBits(), np.uint32, bpl * img.height()).reshape(img.height(), bpl)
    return a[y0:y0 + h, :img.width()].copy()


def rueda(app, tl, dx: int, dy: int, mod):
    ev = QWheelEvent(QPointF(900, 200), QPointF(tl.mapToGlobal(QPoint(900, 200))), QPoint(0, 0),
                     QPoint(dx, dy), Qt.NoButton, mod, Qt.NoScrollPhase, False)
    QApplication.sendEvent(tl, ev)
    app.processEvents()


def clic(app, tl, x: float, y: float, tipo_press=True):
    tipo = QEvent.MouseButtonPress if tipo_press else QEvent.MouseButtonRelease
    ev = QMouseEvent(tipo, QPointF(x, y), QPointF(tl.mapToGlobal(QPoint(int(x), int(y)))),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(tl, ev)
    app.processEvents()


def video_prueba() -> str:
    from editoria.core import media as MEDIA
    ruta = os.path.join(_TMP, "v.mp4")
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-t", "4", "-pix_fmt", "yuv420p", ruta], check=True, timeout=180, creationflags=0x08000000)
    return ruta


def imagen_prueba() -> str:
    ruta = os.path.join(_TMP, "i.png")
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor(200, 120, 40))
    assert img.save(ruta, "PNG"), "no pude crear la imagen de prueba"
    return ruta


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    import faulthandler                       # si algo se cuelga, a los 300 s vuelca dónde (y sale)
    faulthandler.dump_traceback_later(300, exit=True)
    app = QApplication(sys.argv)
    from editoria.core.model import Clip, KIND_IMAGE, KIND_VIDEO, MediaItem, TRACK_AUDIO, TRACK_VIDEO, new_id
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    w = MainWindow()
    w.resize(1100, 480)
    w.show()
    pump(app, 0.8)
    ctrl = w.ctrl

    # ---------------------------------------------------------- 1) proyecto nuevo: una pista de cada tipo
    ctrl.new_project()
    p = ctrl.project
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    auds = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    assert [t.name for t in vids] == ["V1"] and [t.name for t in auds] == ["A1"], [t.name for t in p.tracks]
    assert len(p.tracks) == 2
    assert auds[0].fx.get("eq") and auds[0].fx.get("compress"), auds[0].fx
    print("✓ ctrl.new_project(): exactamente 1 pista de video («V1») y 1 de audio («A1», con mejora de voz)")

    vid_path = video_prueba()
    img_path = imagen_prueba()
    vid_id, img_id = new_id(), new_id()
    p.media[vid_id] = MediaItem(id=vid_id, path=vid_path, kind=KIND_VIDEO, name="v", duration=4.0, width=320,
                                height=180, fps=25.0, has_audio=True, channels=2, probed=True)
    p.media[img_id] = MediaItem(id=img_id, path=img_path, kind=KIND_IMAGE, name="i", duration=0.0, width=320,
                                height=180, probed=True)

    # 1a) imagen ENCIMA de V1 ocupada: se crea la pista justo encima de V1 con nombre «V2»
    v1 = next(t for t in ctrl.project.tracks if t.name == "V1")
    busy = new_id()
    p.clips[busy] = Clip(busy, vid_id, v1.id, 10.0, 0.0, 3.0, volume=0.0)
    ids = ctrl.add_image_overlay([img_id], v1.id, 10.5)
    names = [t.name for t in ctrl.project.tracks]
    assert ids, "add_image_overlay no colocó la imagen"
    img_track = ctrl.project.track(ctrl.project.clips[ids[0]].track_id)
    assert img_track.name == "V2" and names == ["V2", "V1", "A1"], names
    print("✓ add_image_overlay sobre V1 ocupada: crea «V2» justo encima de V1 y pone ahí la imagen")

    # 1b) «Poner donde lo dices» (B-roll): sin pista encima, la crea («V2») sobre la principal
    ctrl.new_project()
    p = ctrl.project
    p.media[vid_id] = MediaItem(id=vid_id, path=vid_path, kind=KIND_VIDEO, name="v", duration=4.0, width=320,
                                height=180, fps=25.0, has_audio=True, channels=2, probed=True)
    cl = ctrl.place_clip_at(vid_id, [1.0], [2.0], 0.0)
    assert len(cl) == 1, cl
    names = [t.name for t in ctrl.project.tracks]
    assert names == ["V2", "V1", "A1"], names
    assert ctrl.project.clips[cl[0]].track_id == ctrl.project.tracks[0].id
    print("✓ place_clip_at (B-roll) en proyecto nuevo: crea «V2» encima de V1 sin error")

    # 1c) el helper de B-roll/imágenes: crea «V2» encima de V1 si no hay ninguna; si ya hay, la reutiliza
    ctrl.new_project()
    v1 = ctrl.project.tracks[0]
    t_id = ctrl.ensure_video_above(v1.id)
    assert t_id and [t.name for t in ctrl.project.tracks] == ["V2", "V1", "A1"], [t.name for t in ctrl.project.tracks]
    assert ctrl.ensure_video_above(v1.id) == t_id and len(ctrl.project.tracks) == 3
    print("✓ ensure_video_above(V1): crea «V2» encima de V1 una vez y luego reutiliza esa")

    # ---------------------------------------------------------- 2) muchas pistas: hay desplazamiento vertical
    ctrl.new_project()
    for _ in range(7):
        ctrl.add_track(TRACK_VIDEO)
    for _ in range(3):
        ctrl.add_track(TRACK_AUDIO)
    pump(app, 0.5)
    tl = w.timeline
    sa = tl._scroll_area()
    assert sa is not None, "la línea de tiempo no está dentro de un QScrollArea"
    vb, hb = sa.verticalScrollBar(), tl.hbar
    assert vb.maximum() > 0, "no hay desplazamiento vertical (ventana demasiado alta)"
    print(f"✓ proyecto con {len(ctrl.project.tracks)} pistas: desplazamiento vertical máximo = {vb.maximum()} px")

    # 3) la regla queda fija al bajar: sus píxeles en [vt, vt+RULER_H) son los de la regla sin desplazar
    h = tl.RULER_H
    vb.setValue(0)
    pump(app, 0.2)
    regla0 = filas(tl.grab().toImage(), 0, h)
    assert regla0.std() > 0, "la regla salió vacía"
    for frac in (0.5, 1.0):
        vb.setValue(int(vb.maximum() * frac))
        pump(app, 0.2)
        vt = vb.value()
        assert vt > 0 and -tl.y() == vt, (vt, tl.y())
        regla = filas(tl.grab().toImage(), vt, h)
        assert np.array_equal(regla0, regla), f"la regla NO se queda fija al desplazar {vt} px"
    print(f"✓ regla fija al desplazar en vertical (píxel a píxel, hasta {vt} px): tiempos, temas y esquina arriba")

    # 4) clic en la regla desplazada: mueve el cabezal (la regla fija recibe el clic, no la pista de debajo)
    vb.setValue(vb.maximum() // 2)
    pump(app, 0.2)
    vt = vb.value()
    seeks: list[float] = []
    tl.seek_requested.connect(seeks.append)
    x = tl.HEADER_W + 260
    clic(app, tl, x, vt + h // 2)
    clic(app, tl, x, vt + h // 2, tipo_press=False)
    tl.seek_requested.disconnect(seeks.append)
    assert seeks and abs(seeks[0] - tl.t_for(x)) < 1e-6, seeks
    print(f"✓ clic en la regla desplazada ({vt} px): el cabezal va a {seeks[0]:.2f} s")

    # 5) Alt + rueda: desplaza las pistas en vertical, no el eje horizontal
    vb.setValue(0)
    hb.setValue(0)
    pump(app, 0.2)
    v0, h0 = vb.value(), hb.value()
    rueda(app, tl, 0, -120, Qt.AltModifier)               # Qt en Windows: Alt pasa la rueda al eje vertical
    v1_, h1_ = vb.value(), hb.value()
    assert v1_ > v0 and h1_ == h0, (v0, v1_, h0, h1_)
    rueda(app, tl, -120, 0, Qt.AltModifier)               # y si llega por el eje X, lo mismo
    assert vb.value() > v1_ and hb.value() == h0, (vb.value(), v1_, hb.value(), h0)
    print(f"✓ Alt + rueda: desplaza en vertical ({v0} → {vb.value()} px) y no toca el horizontal")

    # 6) rueda sin modificador: horizontal, como siempre
    v0, h0 = vb.value(), hb.value()
    rueda(app, tl, 0, -120, Qt.NoModifier)
    assert hb.value() > h0 and vb.value() == v0, (h0, hb.value(), v0, vb.value())
    print("✓ rueda sin modificador: desplaza en horizontal y no en vertical")

    w.ctrl.undo_stack.setClean()                     # (sin esto, cerrar pregunta «¿guardar?» y sin pantalla se queda esperando)
    w.ctrl._media_dirty = False
    w.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
