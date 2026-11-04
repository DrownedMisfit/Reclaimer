"""
Prueba: quitar huecos (espacios vacíos entre clips) en las pistas de AUDIO, con clic + Supr y con
Timeline → «⇤ Eliminar huecos» (todas las de audio / video / todas / una pista), y el botón «🔠 Letra».
Ejecutar:  .venv/Scripts/python.exe tests/test_gaps_audio.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def spans(p, tid):
    return [(round(c.start, 3), round(c.end, 3)) for c in p.clips_on(tid)]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    vid, voz, mus, img = (os.path.join(out, n) for n in ("v.mp4", "voz.wav", "musica.wav", "foto.png"))
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=10",
                    "-f", "lavfi", "-i", "sine=f=440:d=10", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", vid], check=True)
    for path, f in ((voz, 220), (mus, 330)):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={f}:d=10", path], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x36", "-frames:v", "1",
                    img], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    c = win.ctrl
    p = c.project
    vm, nm, mm, im = c.import_now([vid, voz, mus, img])
    vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    v2, v1 = vtracks[0], vtracks[-1]
    a_tracks = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    nar, music = a_tracks[0], p.track(c.ensure_role_track("musica"))
    made = c.add_media([vm], v1.id, 0.0)
    c.add_media([nm], nar.id, 0.0)
    c.add_media([mm], music.id, 0.0)
    c.add_media([im], v2.id, 0.0)
    c.add_media([im], v2.id, 7.0)                       # imagen suelta con hueco (pista de video)
    av = next(t for t in p.tracks if t.kind == TRACK_AUDIO and t.name.endswith("Audio de video"))

    def cut_out(tid, a, b):
        cl = next(x for x in p.clips_on(tid) if x.start < a < x.end)
        c.split(a, [cl.id] + [o.id for o in c.partners(p, cl)])
        cl = next(x for x in p.clips_on(tid) if x.start <= a + 1e-6 < x.end)
        c.split(b, [cl.id] + [o.id for o in c.partners(p, cl)])
        mid = next(x for x in p.clips_on(tid) if abs(x.start - a) < 1e-6)
        c.delete_clips([mid.id] + [o.id for o in c.partners(p, mid)])

    cut_out(v1.id, 2.0, 3.0)         # video + su sonido: hueco de 1 s en V1 y en «Audio de video»
    cut_out(nar.id, 4.0, 6.0)        # narración: hueco de 2 s
    cut_out(music.id, 1.0, 1.5)      # música: hueco de 0,5 s
    before_img = spans(p, v2.id)
    assert spans(p, nar.id) == [(0, 4), (6, 10)] and spans(p, av.id) == [(0, 2), (3, 10)]

    # --- clic en el hueco de la narración + Supr
    tl = win.timeline
    tl.fit()
    pump(app, 0.2)
    i = p.track_index(nar.id)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_for(5.0)), int(tl.track_y(i) + tl.track_h(i) / 2)))
    assert tl.gap is not None and tl.gap[0] == nar.id
    QTest.keyClick(tl, Qt.Key_Delete)
    assert spans(p, nar.id) == [(0, 4), (4, 8)], spans(p, nar.id)
    c.undo_stack.undo()
    print("✓ clic en un hueco de AUDIO + Supr lo elimina")

    # --- Timeline → Eliminar huecos → en todas las pistas de audio (un solo deshacer)
    idx = c.undo_stack.index()
    n = c.close_gaps_on("audio")
    assert n == 3, n
    assert spans(p, nar.id) == [(0, 4), (4, 8)] and spans(p, music.id) == [(0, 1), (1, 9.5)]
    assert spans(p, av.id) == [(0, 2), (2, 9)] and spans(p, v1.id) == [(0, 2), (2, 9)]   # su imagen va con él
    assert spans(p, v2.id) == before_img, "una imagen suelta en video no debe moverse"
    assert c.undo_stack.index() == idx + 1
    c.undo_stack.undo()
    print("✓ «⇤ Eliminar huecos → en todas las pistas de audio»: narración, música y sonido de video "
          "(su imagen lo acompaña); lo demás no se mueve; un solo Ctrl+Z")

    # --- solo video / todas / la pista del clip elegido
    c.close_gaps_on("video")
    assert spans(p, v2.id) == [(0, 5), (5, 10)] and spans(p, nar.id) == [(0, 4), (6, 10)]
    c.undo_stack.undo()
    win.timeline.set_selection([p.clips_on(music.id)[0].id])
    win._close_gaps_selected_track()
    assert spans(p, music.id) == [(0, 1), (1, 9.5)] and spans(p, nar.id) == [(0, 4), (6, 10)]
    c.undo_stack.undo()
    c.close_gaps_on(None)
    assert all(len(spans(p, t.id)) < 2 or spans(p, t.id)[1][0] == spans(p, t.id)[0][1]
               for t in (nar, music, av, v1, v2))
    print("✓ también: solo en video, en todas, o solo en la pista del clip elegido")

    # --- menús visibles
    titles = []
    for a in win.menuBar().actions():
        if a.text().replace("&", "") == "Timeline":
            titles = [x.text() for x in a.menu().actions()]
    assert any("Eliminar huecos" in t for t in titles), titles
    menu = QMenu()
    orig = __import__("editoria.ui.help", fromlist=["exec_menu"]).exec_menu
    import editoria.ui.timeline as TLmod
    captured = {}
    TLmod.help_ui.exec_menu = lambda m, _pos: captured.setdefault("acts", [x.text() for x in m.actions()])
    tl._track_menu(p.track(nar.id), QPoint(0, 0))
    TLmod.help_ui.exec_menu = orig
    assert any("huecos de TODAS las pistas de audio" in t for t in captured["acts"]), captured
    print("✓ menú Timeline → «⇤ Eliminar huecos» y clic derecho en la cabecera de la pista")

    # --- botón «🔠 Letra» siempre a la vista
    opened = []
    win.open_font_size = lambda: opened.append(1)
    win.btn_font.clicked.disconnect()
    win.btn_font.clicked.connect(win.open_font_size)
    win.btn_font.click()
    assert win.btn_font.isVisible() and opened
    print("✓ botón «🔠 Letra» en la barra de arriba")

    win.analyzer.shutdown()
    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
