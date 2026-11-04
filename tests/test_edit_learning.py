"""
Prueba de 👍/👎, 🔀 Remix y 🎛 Mix de los edits:
  · la huella de un edit (planos por parte, efectos) y lo aprendido (👍 acerca, 👎 aleja; tus cambios a mano
    pesan más y se comparan con lo que hizo la IA);
  · el motor usa lo aprendido (planos más largos en el drop, menos glitch…) sin salirse del ritmo;
  · 🔀 Remix rehace el edit entero de otra manera (Ctrl+Z vuelve); 🎛 Mix solo los planos seleccionados;
  · el proyecto recuerda sus edits al guardar y abrir.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_learning.py <carpeta_salida>
"""
from __future__ import annotations

import importlib.util
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    spec = importlib.util.spec_from_file_location("t_e2", os.path.join(ROOT, "tests", "test_edits2.py"))
    e2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2)
    from editoria.ai import edit_engine, edit_feedback as EF, edit_maker, music_analysis
    from editoria.core import media as media_tools

    song_path = os.path.join(out, "cancion.wav")
    e2.make_song(song_path)
    song = edit_maker.analyze_song(song_path)
    edit_engine.enrich(song, media_tools.decode_mono(song_path, music_analysis.SR), music_analysis.SR)
    ff = media_tools.ffmpeg()
    clips = []
    for name, src in (("a.mp4", "testsrc2=s=640x360:r=30:d=60"), ("b.mp4", "mandelbrot=s=640x360:r=30")):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "60",
                            "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", p], check=True)
        clips.append(p)
    srcs = []
    for p in clips:
        pr = media_tools.probe(p)
        srcs.append({"media_id": os.path.basename(p), "path": p, "kind": "video", "duration": pr["duration"],
                     "name": os.path.basename(p), "profile": edit_maker.motion_profile(p, pr["duration"])})

    # 1) Huella y aprendizaje
    base_plan = edit_engine.plan_v2(song, srcs, style="hype", length=None)
    fp0 = EF.fingerprint(EF.shots_from_plan(base_plan), base_plan["sections"], base_plan["period"])
    assert fp0["n"] > 10 and "drop" in fp0["len"] and fp0["rate"]["glitch"] > 0, fp0
    EF.note_created("hype", fp0)
    liked = {"len": dict(fp0["len"], drop=fp0["len"]["drop"] * 2), "rate": dict(fp0["rate"], glitch=0.0),
             "n": fp0["n"] - 6}
    r = EF.record("hype", liked, +1, ai_fp=fp0)
    assert r["manual"], "tu versión distinta de la de la IA"
    lr = EF.learned("hype")
    assert lr["len_mult"]["drop"] > 1.5 and lr["fx_mult"]["glitch"] < 0.5, lr
    assert "drop" in EF.describe(lr) and "menos glitch" in EF.describe(lr), EF.describe(lr)
    EF.record("hype", fp0, -1)                          # 👎 a lo normal: refuerza lo mismo
    lr = EF.learned("hype")
    print(f"✓ aprende: {EF.describe(lr)} (de {lr['n']} notas; tus cambios a mano pesan más)")

    # 2) El motor lo usa (y sigue en el ritmo)
    lp = edit_engine.plan_v2(song, srcs, style="hype", length=None, learned=lr)
    e2.check_plan(lp, song, lp["music"]["source_in"], "hype aprendido")
    fp1 = EF.fingerprint(EF.shots_from_plan(lp), lp["sections"], lp["period"])
    # (2026-10-10: el «normal» ya varía las duraciones —rompe rachas de planos iguales— y sale algo más largo que la
    #  rejilla pura; lo aprendido sigue siendo el doble de la rejilla: aquí se pide que se note claramente)
    assert fp1["len"]["drop"] > fp0["len"]["drop"] * 1.25, (fp1["len"], fp0["len"])
    assert fp1["rate"]["glitch"] < fp0["rate"]["glitch"], (fp1["rate"], fp0["rate"])
    print(f"✓ con lo aprendido: drop {fp0['len']['drop']:.1f} → {fp1['len']['drop']:.1f} golpes por plano, "
          f"glitch {fp0['rate']['glitch']:.2f} → {fp1['rate']['glitch']:.2f}")

    # 3) Remix: otra manera, en el ritmo; con la misma ventana para el Mix
    rx = edit_engine.plan_v2(song, srcs, style="phonk", length=None, seed=999, variation=True)
    e2.check_plan(rx, song, rx["music"]["source_in"], "remix")
    ph = edit_engine.plan_v2(song, srcs, style="phonk", length=None)
    assert rx["remix"] and [c["media_id"] for c in rx["clips"]] != [c["media_id"] for c in ph["clips"]]
    same = edit_engine.plan_v2(song, srcs, style="phonk", length=8.0, window=ph["window"], seed=5, variation=True)
    assert same["music"]["source_in"] == ph["music"]["source_in"] and same["window"] == ph["window"]
    print(f"✓ remix: {', '.join(rx['remix'])} — sin salirse de los golpes")

    # 4) En la aplicación
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui.task_window import manager
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        pump(app, 0.3)
        ctrl, bar = win.ctrl, win.edit_bar
        assert not bar.isVisible(), "sin edits, la barra no se ve"
        ctrl.set_project_format("edit")
        p = ctrl.project
        ctrl.import_paths([song_path] + clips)
        while ctrl.analyzing:
            pump(app, 0.1)
        by_name = {m.name: m.id for m in p.media.values()}
        plan = edit_engine.plan_v2(song, srcs, style="phonk", length=None)
        for c in plan["clips"]:
            c["media_id"] = by_name[c["media_id"]]
        plan["music"]["media_id"] = by_name["cancion.wav"]
        opts = {"style": "phonk", "length": None, "seed": 7}
        ctrl.apply_edit_plan(plan, layout="auto", ctx={"options": opts, "sources": [by_name["a.mp4"], by_name["b.mp4"]]})
        pump(app, 0.2)
        assert bar.isVisible() and len(p.edits) == 1
        rec = p.edits[0]
        assert rec["style"] == "phonk" and rec["ai_fp"] and rec["window"] and rec["sources"]
        # 👍 tal cual → no es «manual»; luego retoque a mano (quitar destellos) → 👍 aprende de tu versión
        n0 = len(EF.load()["entries"])
        bar.rate(+1)
        e = EF.load()["entries"][-1]
        assert len(EF.load()["entries"]) == n0 + 1 and not e["manual"] and e["style"] == "phonk"
        flashy = [c for c in ctrl.edit_clips(rec) if (c.fx or {}).get("flash")]
        for c in flashy:
            ctrl.set_clip_props([c.id], "quitar destello", fx={k: v for k, v in c.fx.items() if k != "flash"})
        bar.rate(+1)
        e = EF.load()["entries"][-1]
        assert e["manual"] and e["fp"]["rate"]["flash"] < e["ai"]["rate"]["flash"], e
        print(f"✓ 👍 al edit tal cual y 👍 a tu versión retocada (sin {len(flashy)} destellos): aprende de tus cambios")

        # 🔀 Remix (en segundo plano)
        win.engine.seek(rec["base"] + 3.0)
        old_ids = set(rec["clip_ids"])
        bar.remix()
        t0 = time.time()
        while (bar._busy or manager().tasks) and time.time() - t0 < 120:
            pump(app, 0.2)
        rec2 = p.edits[0]
        assert rec2["version"] == 2 and not (set(rec2["clip_ids"]) & old_ids), "edit rehecho entero"
        assert len(p.edits) == 1 and rec2["id"] == rec["id"]
        ctrl.undo_stack.undo()
        assert p.edits[0]["version"] == 1 and set(p.edits[0]["clip_ids"]) == old_ids, "Ctrl+Z vuelve"
        ctrl.undo_stack.redo()
        print(f"✓ 🔀 Remix: versión 2 ({', '.join(p.edits[0]['remix']) or 'otros planos'}); Ctrl+Z vuelve a la 1")

        # 🎛 Mix de dos planos del medio
        rec = p.edits[0]
        vc = sorted(ctrl.edit_clips(rec), key=lambda c: c.start)
        mid = [c for c in vc if rec["base"] + 4 < c.start < rec["base"] + rec["duration"] - 6][:2]
        a, b = min(c.start for c in mid), max(c.end for c in mid)
        outside = {c.id: (c.start, c.duration) for c in vc if c.end <= a + 1e-3 or c.start >= b - 1e-3}
        win.timeline.set_selection([c.id for c in mid])
        n_mix_before = sum(1 for x in EF.load()["entries"] if x["where"] == "mix")
        bar.mix()
        t0 = time.time()
        while (bar._busy or manager().tasks) and time.time() - t0 < 120:
            pump(app, 0.2)
        now = {c.id: (c.start, c.duration) for c in ctrl.edit_clips(p.edits[0])}
        assert all(now.get(cid) == v for cid, v in outside.items()), "lo de fuera no se toca"
        inside = [c for c in ctrl.edit_clips(p.edits[0]) if a - 1e-3 <= c.start < b - 1e-3]
        assert inside and not ({c.id for c in mid} & {c.id for c in inside}), "el tramo es nuevo"
        assert abs(min(c.start for c in inside) - a) < 1e-3 and abs(max(c.end for c in inside) - b) < 1e-3
        assert sum(1 for x in EF.load()["entries"] if x["where"] == "mix") == n_mix_before + 1
        print(f"✓ 🎛 Mix: solo {b - a:.2f} s rehechos ({len(inside)} planos nuevos); lo demás igual")
        v1 = next(t for t in reversed(p.tracks) if t.kind == "video")
        here = p.clip_at(v1.id, win.engine.time)
        first = min(inside, key=lambda c: c.start)
        assert here is not None and here.id == first.id, ("el cabezal, en el primer plano NUEVO", win.engine.time,
                                                          first.start)
        print("✓ tras el Mix, el cabezal queda en el primer fotograma del plano nuevo (no en el anterior)")

        # Guardar y abrir: recuerda sus edits
        path = os.path.join(out, "edit.eia")
        ctrl.save(path)
        ctrl.load(path)
        assert len(ctrl.project.edits) == 1 and ctrl.project.edits[0]["id"] == rec["id"]
        print("✓ el proyecto recuerda sus edits al guardar y abrir")
        win.grab().save(os.path.join(out, "barra_edit.png"))
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
