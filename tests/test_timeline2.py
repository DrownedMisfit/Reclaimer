"""
Prueba de la línea de tiempo «profesional»: rectángulo de selección, huecos (Supr), mover sin
tapar clips, soltar sin sobrescribir y arrastrar archivos desde Windows.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline2.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import KIND_IMAGE, TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    files = {
        "a.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast"],
        "b_con_sonido.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi", "-i",
                             "sine=f=300:d=3", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest"],
        "musica.wav": ["-f", "lavfi", "-i", "sine=f=220:d=4"],
        "captura.png": ["-f", "lavfi", "-i", "smptebars=s=640x360", "-frames:v", "1"],
    }
    paths = {}
    for name, args in files.items():
        p = os.path.join(out, name)
        subprocess.run([ff, "-nostdin", "-v", "error", "-y"] + args + [p], check=True)
        paths[name] = p
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl, tl = win.ctrl, win.timeline
    tl.set_linked(True)
    ctrl.split_av = True
    ids = dict(zip(files, ctrl.import_now([paths[n] for n in files])))
    assert all(ctrl.project.media[i].probed or ctrl.project.media[i].kind == KIND_IMAGE for i in ids.values())
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]

    # --- 1) Soltar sin sobrescribir
    a = ctrl.add_media([ids["a.mp4"]], v1.id, 0.0)[0]
    created = ctrl.add_media([ids["b_con_sonido.mp4"]], v1.id, 5.0)
    b, b_audio = created[0], created[1]
    over = ctrl.add_media([ids["a.mp4"]], v1.id, 1.0)       # encima de «a»
    assert p.clips[over[0]].track_id != v1.id and abs(p.clips[a].duration - 3.0) < 0.05
    ctrl.undo_stack.undo()
    print("✓ soltar encima de un clip no lo tapa: va a otra pista libre")

    tl.fit()
    pump(app, 0.2)

    def pt(t, track_id):
        i = p.track_index(track_id)
        return QPoint(int(tl.x_for(t)), int(tl.track_y(i) + tl.track_h(i) / 2))

    # --- 2) Clic en un hueco + Supr: lo de detrás se desplaza
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, pt(4.0, v1.id))
    assert tl.gap is not None and tl.gap[0] == v1.id and abs(tl.gap[1] - 3.0) < 0.05 and abs(tl.gap[2] - 5.0) < 0.05, tl.gap
    win._delete(False)
    assert abs(p.clips[b].start - 3.0) < 0.05 and abs(p.clips[b_audio].start - 3.0) < 0.05
    print("✓ clic en el hueco + Supr: el clip (y su sonido vinculado) se desplaza hasta tocar al anterior")
    ctrl.undo_stack.undo()
    assert abs(p.clips[b].start - 5.0) < 0.05

    # --- 3) Si su sonido vinculado chocaría en su pista, solo se mueve lo que cabe
    av = p.track(p.clips[b_audio].track_id)
    blocker = ctrl.add_media([ids["musica.wav"]], av.id, 0.5)[0]    # 0,5–4,5 en la pista del sonido
    assert p.clips[blocker].track_id == av.id
    ctrl.close_gap(v1.id, 3.0, 5.0)
    assert abs(p.clips[b].start - 4.5) < 0.06, p.clips[b].start
    for t in p.tracks:
        cs = p.clips_on(t.id)
        assert all(x.end <= y.start + 1e-6 for x, y in zip(cs, cs[1:])), "nada encimado"
    print("✓ hueco con el sonido bloqueado por otro audio: avanza solo hasta donde cabe (sin encimar)")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()

    # --- 4) Arrastrar un clip encima de otro: se detiene al tocarlo
    tl.set_selection([])
    bp = pt(6.5, v1.id)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, bp)
    QTest.mouseMove(tl, bp - QPoint(10, 0))
    QTest.mouseMove(tl, bp - QPoint(int(4.5 * tl.pps), 0))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, bp - QPoint(int(4.5 * tl.pps), 0))
    assert abs(p.clips[b].start - 3.0) < 0.06 and abs(p.clips[a].duration - 3.0) < 0.05, \
        (p.clips[b].start, p.clips[a].duration)
    print("✓ arrastrar un clip sobre otro: se detiene pegado a él, sin taparlo")
    ctrl.undo_stack.undo()

    # --- 5) Rectángulo de selección
    tl.set_selection([])
    start = QPoint(int(tl.x_for(-0.0) + 2), int(tl.track_y(0) + 2))
    end = pt(9.0, av.id) + QPoint(0, 10)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(tl, start + QPoint(20, 20))
    QTest.mouseMove(tl, end)
    win.grab().save(os.path.join(out, "rectangulo.png"))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, end)
    assert {a, b, b_audio} <= tl.selected, tl.selected
    print(f"✓ rectángulo de selección: {len(tl.selected)} clips (video y audio)")

    # --- 6) Arrastrar archivos desde Windows a la línea de tiempo
    tl.set_selection([])
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(paths["captura.png"]), QUrl.fromLocalFile(paths["musica.wav"])])
    target = pt(12.0, v1.id)
    for ev in (QDragEnterEvent(target, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier),
               QDragMoveEvent(target, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)):
        QApplication.sendEvent(tl, ev)
    QApplication.sendEvent(tl, QDropEvent(QPointF(target), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    new = [p.clips[i] for i in tl.selected]
    kinds = {p.media[c.media_id].name: p.track(c.track_id).kind for c in new}
    assert kinds.get("captura.png") == TRACK_VIDEO and kinds.get("musica.wav") == TRACK_AUDIO, kinds
    img = next(c for c in new if p.media[c.media_id].name == "captura.png")
    assert abs(img.start - 12.0) < 0.3, img.start
    print("✓ archivos desde Windows: la imagen a una pista de video y el audio a una de audio, donde se soltaron")

    # --- 7) Cerrar todos los huecos de una pista
    n = ctrl.close_all_gaps(v1.id)
    cs = p.clips_on(v1.id)
    assert n and all(abs(x.end - y.start) < 1e-3 for x, y in zip(cs, cs[1:])) and cs[0].start < 1e-6, \
        [(c.start, c.end) for c in cs]
    print(f"✓ «Eliminar todos los huecos de esta pista»: {n} huecos cerrados")
    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
