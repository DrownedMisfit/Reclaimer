"""
Prueba de imagen y sonido separados y vinculados (como en DaVinci Resolve) y de la forma de onda.
Ejecutar:  .venv/Scripts/python.exe tests/test_link.py <carpeta_salida>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    vid = os.path.join(out, "gameplay_con_sonido.mp4")
    # Video de 10 s: sonido los primeros 6 s, luego silencio (para ver «fin del sonido»)
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10",
                        "-f", "lavfi", "-i", "sine=f=330:d=6", "-af", "apad=whole_dur=10,volume=0.5",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", vid],
                       capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
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
    [mid] = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    p = ctrl.project
    assert mid in ctrl.peaks, "forma de onda del sonido del video"
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]

    # --- 1) Al poner el video, su sonido va debajo, vinculado
    created = ctrl.add_media([mid], v1.id, 1.0)
    assert len(created) == 2, created
    vc, ac = p.clips[created[0]], p.clips[created[1]]
    atr = p.track(ac.track_id)
    assert atr.kind == TRACK_AUDIO and atr.name == "Audio de video"
    assert p.tracks.index(atr) == p.tracks.index(v1) + 1, "la pista de audio va justo debajo del video"
    assert vc.link and vc.link == ac.link
    assert (ac.start, ac.duration, ac.source_in) == (vc.start, vc.duration, vc.source_in)
    print("✓ al poner un video: imagen en V1 y su sonido justo debajo («Audio de video»), vinculados")

    tl.fit()
    tl.zoom(1.0)
    pump(app, 0.2)

    def center(c):
        r = tl.clip_rect(c)
        return QPoint(int(r.center().x()), int(r.center().y()))

    # --- 2) Clic = se seleccionan los dos; arrastrar = se mueven juntos
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, center(vc))
    assert tl.selected == {vc.id, ac.id}, tl.selected
    assert win.inspector._ids == [vc.id] and win.inspector._audio_id == ac.id, "el Inspector lo trata como uno"
    start0 = vc.start
    a = center(vc)
    b = a + QPoint(int(2.0 * tl.pps), 0)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(tl, a + QPoint(10, 0))
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, b)
    vc, ac = p.clips[vc.id], p.clips[ac.id]
    assert abs(vc.start - ac.start) < 1e-6 and vc.start > start0 + 1.0, (vc.start, ac.start)
    assert p.track(ac.track_id).kind == TRACK_AUDIO
    print(f"✓ clic selecciona los dos y al arrastrar se mueven juntos ({start0:.1f} → {vc.start:.1f} s)")

    # --- 3) Recortar el borde derecho del video recorta también el sonido
    r = tl.clip_rect(vc)
    a = QPoint(int(r.right() - 2), int(r.center().y()))
    b = a - QPoint(int(3.0 * tl.pps), 0)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(tl, a - QPoint(10, 0))
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, b)
    vc, ac = p.clips[vc.id], p.clips[ac.id]
    assert abs(vc.end - ac.end) < 1e-6 and vc.duration < 8.0, (vc.end, ac.end, vc.duration)
    print(f"✓ recortar uno recorta el otro (los dos duran {vc.duration:.1f} s)")

    # --- 4) Alt+clic: solo el sonido; se puede mover por separado (y deshacer)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.AltModifier, center(ac))
    assert tl.selected == {ac.id}, tl.selected
    a = center(ac)
    b = a + QPoint(int(1.0 * tl.pps), 0)
    QTest.mousePress(tl, Qt.LeftButton, Qt.AltModifier, a)
    QTest.mouseMove(tl, a + QPoint(10, 0))
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.AltModifier, b)
    assert p.clips[ac.id].start > p.clips[vc.id].start + 0.5
    ctrl.undo_stack.undo()
    assert abs(p.clips[ac.id].start - p.clips[vc.id].start) < 1e-6
    print("✓ Alt+clic: solo el sonido (se mueve por separado; deshacer lo vuelve a juntar)")

    # --- 5) Cuchilla: corta los dos; las mitades quedan vinculadas por parejas
    win.set_tool("blade")
    vc = p.clips[vc.id]
    t_cut = vc.start + vc.duration / 2
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl.x_for(t_cut)), int(tl.clip_rect(vc).center().y())))
    win.set_tool("select")
    vids = p.clips_on(v1.id)
    auds = p.clips_on(ac.track_id)
    assert len(vids) == 2 and len(auds) == 2, (len(vids), len(auds))
    assert vids[0].link == auds[0].link and vids[1].link == auds[1].link and vids[0].link != vids[1].link
    print("✓ la cuchilla corta imagen y sonido; cada mitad sigue vinculada con la suya")

    # --- 6) Exportar: el sonido sale una vez (no doble) y a su volumen
    def export_level(name):
        mp4 = os.path.join(out, name)
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="gpu",
                                                  bitrate_mbps=2, loudnorm=False), ff, os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
        r = subprocess.run([ff, "-nostdin", "-hide_banner", "-i", mp4, "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return float(re.search(r"max_volume: (-?[\d.]+) dB", r.stderr).group(1))
    linked_db = export_level("vinculado.mp4")
    ctrl.split_av = False
    c_old = ctrl.add_media([mid], v1.id, 30.0)
    assert len(c_old) == 1, "sin separar: como antes, un solo clip con el sonido dentro"
    ctrl.delete_clips([c.id for c in p.clips.values() if c.start < 29])
    embedded_db = export_level("dentro.mp4")
    assert abs(linked_db - embedded_db) < 1.0, (linked_db, embedded_db)
    print(f"✓ exportación: mismo volumen separado ({linked_db:.1f} dB) que dentro del video ({embedded_db:.1f} dB)")
    ctrl.undo_stack.undo()   # vuelven los clips vinculados
    sep = ctrl.separate_audio(c_old)
    assert isinstance(sep, list) and len(sep) == 1 and p.clips[c_old[0]].link
    print("✓ «Separar el audio» en un clip antiguo crea su sonido vinculado")
    ctrl.split_av = True

    # --- 7) Desvincular: ya se mueven por separado
    vids = p.clips_on(v1.id)
    ctrl.unlink_clips([vids[0].id])
    assert not p.clips[vids[0].id].link
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, center(p.clips[vids[0].id]))
    assert tl.selected == {vids[0].id}
    print("✓ desvincular: cada parte se selecciona sola")

    # --- 8) Guardar y abrir conserva los vínculos
    path = os.path.join(out, "vinculos.eia")
    ctrl.save(path)
    links = {c.id: c.link for c in p.clips.values()}
    ctrl.load(path)
    assert {c.id: c.link for c in ctrl.project.clips.values()} == links
    print("✓ guardar/abrir conserva los vínculos")

    # --- 9) Forma de onda: estilos, dB, silencios, pistas altas (capturas)
    tl.fit()
    shots = []
    for style, db, h in (("espejo", False, 54), ("rectificada", False, 84), ("contorno", True, 84),
                         ("espejo", True, 124)):
        tl.set_wave(style=style, db=db, silence=True, audio_h=h)
        pump(app, 0.3)
        f = os.path.join(out, f"onda_{style}_{'db' if db else 'lin'}_{h}.png")
        tl.grab().save(f)
        shots.append(f)
    tl.set_wave(style="espejo", db=False, silence=True, audio_h=54)
    win.grab().save(os.path.join(out, "link_ui.png"))
    print("✓ forma de onda: espejo / rectificada / contorno, escala dB, silencios y pistas altas")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
