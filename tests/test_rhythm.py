"""
Prueba del RECONOCIMIENTO DE RITMO de la música que pones a mano (golpes sobre el bombo, compases, golpes
fuertes, drop y partes), que se hace solo al poner la canción en la pista de música, y de su uso:
rayitas en la canción, imán a los golpes, marcadores del drop y cortes del video al ritmo.
Usa una carpeta de datos TEMPORAL (caché del ritmo).
Ejecutar:  .venv/Scripts/python.exe tests/test_rhythm.py <carpeta_salida>
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from editoria.ai import music_analysis, rhythm  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from test_edits2 import BEAT, BPM, DROP, make_song  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    saved = st.value("timeline/iman_ritmo")
    song_path = os.path.join(out, "cancion_ritmo.wav")
    make_song(song_path)

    # --- 1) El análisis
    t0 = time.time()
    r = rhythm.analyze(song_path)
    t_first = time.time() - t0
    assert abs(r["tempo"] - BPM) < 3, r["tempo"]
    assert r["drop"] is not None and abs(r["drop"] - DROP) < 0.2, r["drop"]
    kicks = np.arange(DROP, 26.0, BEAT)                          # bombos reales del drop
    b = np.array(r["beats"])
    off = [float(np.min(np.abs(b - k))) for k in kicks]
    assert np.median(off) < 0.04, f"los golpes no caen en el bombo: {np.median(off):.3f}"
    assert set(r["downbeats"]) <= set(r["beats"]) and len(r["downbeats"]) >= len(r["beats"]) // 4 - 1
    assert r["strong"] and all(s >= 7.3 for s in r["strong"]), r["strong"][:5]   # nada fuerte en la intro (solo platillo)
    assert any(s["kind"] == "drop" for s in r["sections"])
    t0 = time.time()
    assert rhythm.analyze(song_path) == r
    assert time.time() - t0 < 0.2, "la segunda vez sale de la caché"
    print(f"✓ ritmo: {rhythm.summary(r)} · golpes sobre el bombo (desvío {np.median(off) * 1000:.0f} ms) · "
          f"{t_first:.1f} s la 1.ª vez, instantáneo después")
    tl = rhythm.to_timeline(r, 10.0, 10.0, 2.0)
    assert all(2.0 <= t < 12.0 for t in tl["beats"]) and tl["drop"] is not None and abs(tl["drop"] - (DROP - 8)) < 0.2

    # Preferencia por el compás / golpe fuerte al llevar cortes al ritmo
    snap = music_analysis.snap_points([1.05], [1.0, 1.1], prefer=[1.1])
    assert snap == {1.05: 1.1}, snap
    snap = music_analysis.snap_points([1.0], [1.0, 1.5], prefer=[1.5])
    assert snap == {1.0: 1.0}, snap

    # --- 2) En la aplicación: se reconoce solo al poner la canción en la pista de música
    vid = os.path.join(out, "r_video.mp4")
    if not os.path.exists(vid):
        rr = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                             "testsrc2=s=640x360:r=30:d=40", "-c:v", "libx264", "-preset", "ultrafast", vid],
                            capture_output=True)
        assert rr.returncode == 0, rr.stderr
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    msgs = []
    ctrl.message.connect(msgs.append)
    ids = ctrl.import_paths([song_path, vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    song_id = next(i for i in ids if p.media[i].name == "cancion_ritmo.wav")
    vid_id = next(i for i in ids if i != song_id)
    music_tr = p.track(ctrl.ensure_role_track("musica"))
    voice_tr = next(t for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is None)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    # Una canción en la pista de NARRACIÓN (sin categoría Música) no se analiza sola
    ctrl.add_media([song_id], voice_tr.id, 0.0)
    pump(app, 0.5)
    assert song_id not in ctrl.rhythm_busy and song_id not in ctrl.rhythm, "la voz no se analiza como música"
    ctrl.undo_stack.undo()
    ctrl.add_media([song_id], music_tr.id, 2.0)
    music_clip = p.clips_on(music_tr.id)[0]
    assert song_id in ctrl.rhythm_busy or song_id in ctrl.rhythm
    t0 = time.time()
    while song_id not in ctrl.rhythm and time.time() - t0 < 60:
        pump(app, 0.1)
    assert song_id in ctrl.rhythm, "se reconoce el ritmo solo"
    assert any("🥁 Ritmo de «cancion_ritmo.wav»" in m for m in msgs), msgs[-3:]
    rt = ctrl.rhythm_on_timeline()
    assert abs(rt["drops"][0] - (2.0 + r["drop"])) < 1e-3
    assert abs(rt["beats"][0] - (2.0 + r["beats"][0])) < 1e-3
    print(f"✓ al poner la canción en «{music_tr.name}» se reconoce sola: {msgs[-1]}")

    # La timeline lo dibuja y el imán se pega a los golpes
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "ritmo_timeline.png"))
    tl = win.timeline
    tl.set_snap_rhythm(True)
    beat = rt["beats"][len(rt["beats"]) // 2]
    near = beat + 4 / tl.pps                                     # 4 píxeles al lado
    assert abs(tl._snap(near, tl._snap_targets(set())) - beat) < 1e-6, "el imán pega al golpe"
    assert abs(tl._snap(near, tl._snap_targets({music_clip.id})) - near) < 1e-6 or \
        any(abs(near - x) * tl.pps <= tl.SNAP_PX for x in tl._snap_targets({music_clip.id})), \
        "no se pega a los golpes de la canción que se arrastra"
    tl.set_snap_rhythm(False)
    assert beat not in tl._snap_targets(set())
    tl.set_snap_rhythm(True)
    print("✓ imán a los golpes (y se puede quitar en Timeline → «🥁 Imán también a los golpes»)")

    # Menú del clip
    menu = QMenu()
    tl._rhythm_menu(menu, [music_clip])
    texts = [a.text() for a in menu.actions()]
    assert any("Poner marcadores en el drop" in t for t in texts) and any("BPM" in t for t in texts), texts
    # Marcadores del drop y las partes (un paso de deshacer)
    n0 = len(p.markers)
    n = ctrl.add_rhythm_markers([music_clip.id])
    drops = [m for m in p.markers if m.label == "💥 Drop"]
    assert n >= 1 and drops and abs(drops[0].time - (2.0 + r["drop"])) < 0.01, [(m.label, m.time) for m in p.markers]
    ctrl.undo_stack.undo()
    assert len(p.markers) == n0
    ctrl.undo_stack.redo()
    print(f"✓ marcadores del ritmo: {', '.join(f'{m.label} {m.time:.1f}s' for m in p.markers)}")

    # Cortes del video llevados al ritmo (prefiriendo inicio de compás / golpe fuerte)
    for k, (a, d) in enumerate(((2.0, 5.37), (7.37, 4.21), (11.58, 6.0))):
        ctrl.add_media([vid_id], v1.id, a)
        c = max(p.clips_on(v1.id), key=lambda x: x.start)
        ctrl.set_clip_props([c.id], "dur", duration=d, source_in=float(k * 7))
    vc = p.clips_on(v1.id)
    cuts = [x.end for x, y in zip(vc, vc[1:]) if abs(y.start - x.end) < 0.01]
    assert len(cuts) == 2, [(x.start, x.end) for x in vc]
    rt = ctrl.rhythm_on_timeline([music_clip.id])
    targets = music_analysis.snap_points(cuts, rt["beats"], prefer=rt["downbeats"] + rt["strong"] + rt["drops"])
    assert ctrl.snap_cuts(v1.id, targets)
    vc = p.clips_on(v1.id)
    new_cuts = [x.end for x in vc[:-1]]
    allb = np.array(rt["beats"])
    assert all(np.min(np.abs(allb - c)) < 1e-3 for c in new_cuts), new_cuts
    print(f"✓ cortes del video al ritmo: {[round(c, 2) for c in cuts]} → {[round(c, 2) for c in new_cuts]}")

    # Proyecto nuevo: se olvida; al reabrir/añadir otra vez sale de la caché al instante
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    if saved is None:
        st.remove("timeline/iman_ritmo")
    else:
        st.setValue("timeline/iman_ritmo", saved)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
