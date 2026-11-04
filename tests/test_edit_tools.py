"""
Prueba de: copiar/cortar/pegar clips, pegar atributos, velocidad en varios clips seguidos (siguen
pegados), solo de pista (S) y vúmetros.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_tools.py <carpeta_salida>
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
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    vid = os.path.join(out, "v.mp4")
    music = os.path.join(out, "m.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=440:d=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", vid], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=8",
                    "-af", "volume=0.5", music], check=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    vmid, amid = ctrl.import_now([vid, music])
    t0 = time.time()
    while (vmid not in ctrl.peaks or amid not in ctrl.peaks) and time.time() - t0 < 30:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a2 = p.track(ctrl.ensure_role_track("musica"))
    made = ctrl.add_media([vmid], v1.id, 0.0)
    A = next(i for i in made if p.clips[i].track_id == v1.id)
    ctrl.split(4.0, made)
    B = next(c.id for c in p.clips.values() if c.track_id == v1.id and abs(c.start - 4.0) < 1e-6)
    M = ctrl.add_media([amid], a2.id, 0.0)[0]
    stack = ctrl.undo_stack

    # --- velocidad en dos clips seguidos: siguen pegados
    ctrl.set_speed([A, B], speed=2.0)
    a, b = p.clips[A], p.clips[B]
    assert abs(a.duration - 2) < 1e-6 and abs(b.start - 2) < 1e-6 and abs(b.duration - 2) < 1e-6, \
        (a.duration, b.start, b.duration)
    stack.undo()
    print("✓ velocidad a varios clips seguidos: siguen pegados (sin huecos)")

    # --- copiar / pegar (con su sonido si está seleccionado, como con la selección vinculada 🔗), sin tapar nada
    n = ctrl.copy_clips(ctrl.linked_ids([A]))
    assert n == 2
    created = ctrl.paste_clips(4.0)          # ahí está B: debe ir a otra pista
    vids = [p.clips[i] for i in created if p.track(p.clips[i].track_id).kind == TRACK_VIDEO]
    auds = [p.clips[i] for i in created if p.track(p.clips[i].track_id).kind == TRACK_AUDIO]
    assert len(vids) == 1 and len(auds) == 1 and vids[0].track_id != v1.id
    assert vids[0].link and vids[0].link == auds[0].link and vids[0].link != p.clips[A].link
    assert abs(vids[0].start - 4.0) < 1e-6 and abs(vids[0].source_in - p.clips[A].source_in) < 1e-6
    stack.undo()
    created = ctrl.paste_clips(8.0)          # al final: libre en su misma pista
    assert any(p.clips[i].track_id == v1.id for i in created)
    stack.undo()
    snd_b = [i for i in ctrl.linked_ids([B]) if i != B]
    ctrl.copy_clips([B], cut=True)                 # Ctrl+X con SOLO el video seleccionado: su audio se queda
    assert B not in p.clips and snd_b and all(i in p.clips for i in snd_b), snd_b
    stack.undo()
    ctrl.copy_clips(ctrl.linked_ids([B]), cut=True)  # con los dos seleccionados: se van los dos
    assert B not in p.clips and not any(i in p.clips for i in snd_b)
    stack.undo()
    print("✓ copiar/cortar/pegar: EXACTAMENTE lo seleccionado (Ctrl+X de un video deja su audio); vínculo nuevo al "
          "pegar y sin tapar nada")

    # --- pegar atributos
    ctrl.set_clip_props([A], "fx", fx={"bw": 1.0, "vignette": 0.6})
    ctrl.set_zoom_at(A, 1.0, 1.5, 0.4, 0.5)
    ctrl.set_speed([A], speed=0.5)
    ctrl.copy_clips([A])
    ctrl.paste_attributes([B], ["efectos", "encuadre"])
    b = p.clips[B]
    assert b.fx and b.fx.get("bw") == 1.0 and b.zoom_kf and abs(b.zoom_kf[0]["z"] - 1.5) < 1e-6
    assert b.speed == 1.0                      # la velocidad no estaba marcada
    ctrl.paste_attributes([B], ["velocidad"])
    assert p.clips[B].speed == 0.5
    print("✓ pegar atributos: efectos y zoom; la velocidad solo si se marca")

    # --- solo de pista
    tr_m = p.track(a2.id)
    assert p.audible(tr_m) and p.audible(p.track(p.clips[ctrl.partners(p, p.clips[A])[0].id].track_id))
    ctrl.set_track_props(a2.id, "Solo", solo=True)
    other_audio = [t for t in p.tracks if t.kind == TRACK_AUDIO and t.id != a2.id]
    assert p.audible(p.track(a2.id)) and not any(p.audible(t) for t in other_audio)
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    args, _ = build_command(p, ExportOptions(path=os.path.join(out, "x.mp4"), audio_only=True),
                            ff, os.path.join(out, "f.txt"))
    script = open(os.path.join(out, "f.txt"), encoding="utf-8").read()
    assert script.count(":a]aresample") == 1, script   # una sola entrada de audio: la música
    from editoria.ai import audit
    issues, _n = audit.run_audit(p, ctrl.missing, ctrl.peaks)
    assert any("Solo" in str(i) for i in issues), issues
    print("✓ solo (S): solo suena esa pista (visor y exportación) y la Revisión lo avisa")

    # --- vúmetros
    from editoria.core import meters
    lv = meters.track_levels(p, ctrl.peaks, 1.0)
    assert set(lv) == {a2.id} and abs(lv[a2.id] - 0.0625) < 0.01, lv   # tono de prueba: 1/8 × 0.5
    ctrl.set_track_props(a2.id, "Solo", solo=False)
    lv = meters.track_levels(p, ctrl.peaks, 1.0)
    assert len(lv) >= 2, lv
    win.engine.user_seek(1.0)
    pump(app, 0.2)
    assert -25 < win.preview.meter.db < -10, win.preview.meter.db
    win.timeline.update()
    pump(app, 0.2)
    win.grab().save(os.path.join(out, "vumetros.png"))
    print(f"✓ vúmetros: nivel por pista y total en el visor ({win.preview.meter.db:.1f} dB)")

    # --- clic en la S de la cabecera
    tl = win.timeline
    i = p.track_index(a2.id)
    r = tl._solo_rect(i)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    assert p.track(a2.id).solo
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    assert not p.track(a2.id).solo
    print("✓ botón S en la cabecera de la pista")

    win.analyzer.shutdown()
    stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
