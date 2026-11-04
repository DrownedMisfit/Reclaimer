"""
Prueba del ritmo de corte de los edits y de «⚡ Ráfaga»:
  · edición automática más pausada: ningún plano más corto que el mínimo de su densidad (en segundos) salvo la
    ráfaga; con «Tranquilo», nunca ráfaga;
  · canción suave → ninguna ráfaga; canción enérgica (batería muy marcada) → como mucho UNA, justo antes del drop;
  · «⚡ Ráfaga» a mano (barra de la línea de tiempo, entre Dividir y Eliminar): cortes al ritmo exacto de la canción,
    cada trozo salta a otro plano, el sonido no se toca, Ctrl+Z la deshace.
Ejecutar:  .venv/Scripts/python.exe tests/test_burst_density.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402

BPM = 140.0
P = 60.0 / BPM


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def song(path: str, ff: str, drums: bool):
    """60 s: 20 s tranquilos y, desde el segundo 20, el «drop». Con drums: bombo y caja muy marcados todo el rato."""
    if drums:
        expr = (f"0.9*sin(2*PI*55*t)*exp(-25*mod(t,{P:.5f}))*(lt(t,20)*0.5+gte(t,20))"
                f"+0.6*(random(0)-0.5)*exp(-40*mod(t+{P:.5f},{2 * P:.5f}))*(lt(t,20)*0.5+gte(t,20))")
    else:
        expr = "0.25*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.2*t))*(lt(t,20)*0.6+gte(t,20))"
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=44100:d=60", "-c:a", "pcm_s16le", path], check=True)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import edit_engine as EE
    from editoria.ai import edit_maker as EM
    from editoria.ai import music_analysis as MA
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()

    songs = {}
    for name, drums in (("rock", True), ("suave", False)):
        path = os.path.join(out, f"{name}.wav")
        song(path, ff, drums)
        s = EM.analyze_song(path)
        EE.enrich(s, M.decode_mono(path, MA.SR), MA.SR)
        songs[name] = (path, s)
    assert EE.energetic(songs["rock"][1]) and not EE.energetic(songs["suave"][1])
    print("✓ canción enérgica (batería muy marcada) ↔ suave: bien reconocidas")

    for name, (path, s) in songs.items():
        for density in ("tranquilo", "normal", "intenso", "frenetico"):
            st = dict(EE.settings_for("phonk"), density=density)
            st["energetic"] = EE.energetic(s)
            start, end, drop = EM.choose_window(s, None)
            slots = EE._grid(s, start, end, drop, st)
            bursts = [x for x in slots if x.get("sub")]
            normal = [x for x in slots if not x.get("sub")]
            short = [x for x in normal[1:-1] if x["b"] - x["a"] < EE.MIN_SHOT[density] * 0.95
                     and not (drop is not None and abs(x["b"] - drop) < 0.05)]
            assert len(short) <= 1, (name, density, [(round(x["a"], 2), round(x["b"] - x["a"], 2)) for x in short])
            first = slots[0]["b"] - slots[0]["a"]           # nada de un trocito antes del primer golpe
            assert first >= EE.MIN_SHOT[density] * 0.9 or (drop is not None and abs(slots[1]["a"] - drop) < 0.05),                 (name, density, round(first, 2))
            if name == "suave" or density == "tranquilo":
                assert not bursts, (name, density, len(bursts))
            else:
                assert len(bursts) <= EE.BURST_BEATS * 4, len(bursts)
                if bursts:
                    assert drop is not None and all(drop - EE.BURST_BEATS * P - 0.05 <= x["a"] < drop for x in bursts)
            dur = end - start
            print(f"  {name:5s} {density:9s}: {len(slots):3d} planos en {dur:.0f} s "
                  f"({len(slots) / dur * 60:.0f}/min), ráfaga: {len(bursts)} trozos")
    print("✓ edición automática pausada; ráfaga solo en la enérgica, una vez y justo antes del drop")

    # ---------------------------------------------------------------- ⚡ Ráfaga a mano
    vids = []
    for i, src in enumerate(("testsrc2", "mandelbrot", "life")):
        v = os.path.join(out, f"v{i}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"{src}=s=320x180:r=30" + (":d=30" if src == "testsrc2" else ""), "-t", "30",
                        "-pix_fmt", "yuv420p", v], check=True)
        vids.append(v)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    ids = ctrl.import_now(vids + [songs["rock"][0]])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a2 = [t for t in p.tracks if t.kind == TRACK_AUDIO][-1]
    (vc,) = [i for i in ctrl.add_media([ids[0]], v1.id, 0.0) if p.track(p.clips[i].track_id).kind == TRACK_VIDEO]
    ctrl.add_media([ids[3]], a2.id, 0.0)
    ctrl.rhythm[ids[3]] = {"beats": [round(k * P, 4) for k in range(int(60 / P))], "tempo": BPM}
    names = [win.findChildren(type(win.btn_burst))]
    lay = win.btn_burst.parentWidget().layout()
    order = [lay.itemAt(k).widget() for k in range(lay.count()) if lay.itemAt(k).widget() is not None]
    texts = [getattr(w, "text", lambda: "")() for w in order]
    assert texts.index("Dividir") < texts.index("⚡ Ráfaga") < texts.index("Eliminar"), texts
    win.timeline.set_selection([vc])
    win.engine.seek(4.0 * P + 0.02)
    n_before = len(p.clips)
    win.burst(1, 2)
    pump(app, 0.1)
    vclips = sorted((c for c in p.clips.values() if c.track_id == v1.id), key=lambda c: c.start)
    cuts = [round(c.start, 3) for c in vclips[1:]]
    expect = [round(4 * P + k * P / 2, 3) for k in range(1, 9)]
    assert all(any(abs(x - e) < 0.01 for x in cuts) for e in expect[:-1]), (cuts, expect)
    burst_pieces = [c for c in vclips if 4 * P - 0.01 < c.start < 8 * P - 0.01]
    meds = [c.media_id for c in burst_pieces]
    assert all(a != b for a, b in zip(meds, meds[1:])), "cada trozo salta a otro plano"
    assert len(p.clips) == n_before + 8
    audio = [c for c in p.clips.values() if c.track_id == a2.id]
    assert len(audio) == 1, "el sonido (la canción) no se toca"
    print(f"✓ ⚡ Ráfaga: {len(burst_pieces)} trozos a medio golpe ({P / 2:.2f} s), cada uno de otro plano")
    ctrl.undo_stack.undo()
    vclips = [c for c in p.clips.values() if c.track_id == v1.id]
    assert len(vclips) == 1, "Ctrl+Z la deshace entera"
    p.mark_in, p.mark_out = 10 * P, 14 * P
    win.burst(0, 1)
    vclips = [c for c in p.clips.values() if c.track_id == v1.id]
    assert len(vclips) == 5, len(vclips)             # 3 cortes dentro + los 2 bordes del tramo
    print("✓ ⚡ entre las marcas I–O, al golpe; Ctrl+Z la deshace entera")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
