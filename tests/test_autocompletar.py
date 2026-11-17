"""
Prueba de ✨ «Autocompletar» (panel IA ✨ → Inicio, en las tres pestañas):
  · lógica: usos (tramos ×N), apariciones (un clip partido = 1), libre, huecos, material y plan sin solapes;
  · el panel de verdad con un video sintético de 6 escenas de colores + una pista de audio, con parte del video ya
    usada: resumen de usos (veces y tramos); «solo el tramo marcado (I/O)»; «todos los huecos» SOLO con tramos no
    usados (ningún solape con lo usado ni entre sí) y aviso de cuánto faltó; «solo lo elegido» (un hueco); pista
    bloqueada respetada; un solo Ctrl+Z; los clips nuevos quedan elegidos;
  · en Video horizontal, Edits y Vertical el control está a la vista (y en Vertical, con el relleno de fondo).
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_autocompletar.py <c>
"""
from __future__ import annotations

import os
import random
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

from editoria.core import autocompletar as AC  # noqa: E402
from editoria.core import scene_pool as SP  # noqa: E402

EPS = 1e-3


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def overlap(a, b, x, y):
    return min(b, y) - max(a, x) > 0.01


def no_overlaps(spans):
    s = sorted(spans)
    return all(s[i][1] <= s[i + 1][0] + 0.01 for i in range(len(s) - 1))


def test_logic():
    # plan: nunca repite, nunca toca lo usado, trozos dentro del margen y dentro de los huecos
    used = [(0.0, 3.0), (6.0, 8.0)]
    mat = AC.material([(0.0, 3.0), (3.0, 6.0), (6.0, 10.0), (10.0, 14.0)], used, 14.0)
    assert mat == [(3.0, 6.0), (8.0, 10.0), (10.0, 14.0)], mat
    for orden in ("variado", "video"):
        items, faltan = AC.plan("v", mat, [(3.0, 8.0), (10.0, 20.0)], 2.0, 3.0, [], orden, random.Random(4))
        src = [(i["source_in"], i["source_in"] + i["duration"]) for i in items]
        assert no_overlaps(src), src
        assert not any(overlap(a, b, x, y) for a, b in src for x, y in used), src
        assert all(any(m0 - EPS <= a and b <= m1 + EPS for m0, m1 in mat) for a, b in src), "cada trozo, de un plano"
        assert abs(sum(i["duration"] for i in items) + faltan - 15.0) < 0.05, (items, faltan)
        assert faltan > 5.9, faltan                                           # 9 s libres para 15 s de huecos
        tl = [(i["start"], i["start"] + i["duration"]) for i in items]
        assert no_overlaps(tl) and all(3.0 - EPS <= a and b <= 20.0 + EPS for a, b in tl), tl
    items, _f = AC.plan("v", [(0.0, 30.0)], [(0.0, 12.0)], 2.0, 6.0, [], "video")
    assert [i["source_in"] for i in items] == sorted(i["source_in"] for i in items)    # en orden del video
    assert all(2.0 - EPS <= i["duration"] <= 6.0 * 1.25 + EPS for i in items), items
    beats = [k * 0.5 for k in range(100)]
    items, _f = AC.plan("v", [(0.0, 40.0)], [(1.0, 13.0)], 2.0, 4.0, beats, "variado")
    assert all(round(i["start"] + i["duration"], 3) in beats for i in items), items     # al ritmo: acaba en golpe
    assert AC.libre(14.0, used) == [(3.0, 6.0), (8.0, 14.0)]
    # nunca queda negro al final de un hueco si hay material (antes podían quedar hasta 0,25 s)
    items, faltan = AC.plan("v", [(0.0, 2.1), (5.0, 8.0)], [(0.0, 2.15)], 2.0, 2.0, [], "video")
    assert faltan == 0.0 and abs(sum(i["duration"] for i in items) - 2.15) < 1e-3, (items, faltan)
    assert all(i["duration"] >= AC.MIN_PIECE - 1e-3 for i in items), items
    r = random.Random(7)
    for _case in range(300):
        holes, t = [], 0.0
        for _h in range(r.randint(1, 4)):
            t += r.uniform(0.0, 3.0)
            d = r.uniform(0.3, 9.0)
            holes.append((round(t, 3), round(t + d, 3)))
            t += d
        mat, x = [], 0.0
        for _m in range(40):
            d = r.uniform(0.3, 8.0)
            mat.append((round(x, 3), round(x + d, 3)))
            x += d + r.uniform(0.0, 1.0)
        lo = r.choice((0.5, 1.0, 2.0, 3.0))
        hi = lo + r.choice((0.0, 1.0, 4.0))
        bts = [k * 0.5 for k in range(400)] if r.random() < 0.3 else []
        items, faltan = AC.plan("v", mat, holes, lo, hi, bts, r.choice(("video", "variado")), r)
        assert faltan <= 0.011 * len(holes), (holes, lo, hi, faltan)
        tl = [(i["start"], i["start"] + i["duration"]) for i in items]
        src = [(i["source_in"], i["source_in"] + i["duration"]) for i in items]
        assert no_overlaps(tl) and no_overlaps(src), (holes, items)
        assert all(any(g0 - EPS <= a and b <= g1 + EPS for g0, g1 in holes) for a, b in tl)
        assert all(any(m0 - EPS <= a and b <= m1 + EPS for m0, m1 in mat) for a, b in src)
    print("✓ lógica: material libre por planos, sin repetir ni tocar lo usado, en orden o variado, al ritmo; "
          "sin negro al final de los huecos (300 casos al azar)")


def make_media(out):
    from editoria.core import media as M
    vid = os.path.join(out, "colores.mp4")
    cols = (("red", 3), ("blue", 3), ("green", 4), ("yellow", 4), ("magenta", 3), ("cyan", 3))    # 20 s
    args = [M.ffmpeg(), "-nostdin", "-v", "error", "-y"]
    for c_, d_ in cols:
        args += ["-f", "lavfi", "-i", f"color=c={c_}:s=320x180:r=30:d={d_}"]
    args += ["-filter_complex", "".join(f"[{k}:v]" for k in range(len(cols))) + f"concat=n={len(cols)}:v=1:a=0[v]",
             "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid]
    subprocess.run(args, check=True)
    song = os.path.join(out, "voz.wav")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30", song],
                   check=True)
    return vid, song


def new_clips(p, before):
    return [c for c in p.clips.values() if c.id not in before]


def test_panel(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid, song = make_media(out)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    assert win.workspaces.switch("youtube")
    p = ctrl.project
    vmid, smid = ctrl.import_now([vid, song])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = SP.main_video_track(p)
    a1 = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.add_media([smid], a1.id, 0.0)                                      # voz de 0 a 30 s
    # ya usado: la roja (0–3) en 0 s y dos veces el principio de la verde (6–8) en 20 s y 26 s
    for start, src, dur in ((0.0, 0.0, 3.0), (20.0, 6.0, 2.0), (26.0, 6.0, 2.0)):
        made = ctrl.add_media([vmid], v1.id, start, audio=False)
        cid = next(i for i in made if p.clips[i].track_id == v1.id)
        ctrl.set_clip_props([cid], "corto", source_in=src, duration=dur)
    for c in list(p.clips.values()):
        if c.media_id == vmid and p.track(c.track_id).kind != TRACK_VIDEO:
            ctrl.delete_clips([c.id])
    vc = sorted((round(c.start, 2), round(c.source_in, 2), round(c.duration, 2)) for c in p.clips_on(v1.id))
    assert vc == [(0.0, 0.0, 3.0), (20.0, 6.0, 2.0), (26.0, 6.0, 2.0)], vc
    used0 = [(c.source_in, c.source_in + c.src_len) for c in p.clips_on(v1.id)]

    t = win.ai_panel.tabs
    t.setCurrentIndex(next(i for i in range(t.count()) if t.tabText(i) == "Inicio"))
    win.show_panel(win.ai_panel)
    ac = win.ai_panel.autocompletar
    pump(app, 0.4)
    assert ac.isVisible(), "✨ Autocompletar, a la vista en IA ✨ → Inicio"
    assert ac.set_media(vmid) and ac.media_id() == vmid
    ac.refresh()
    s = ac.summary.text()
    assert AC.usos(p, vmid) == [(0.0, 3.0, 1), (6.0, 8.0, 2)], AC.usos(p, vmid)
    assert AC.apariciones(p, vmid) == 3
    assert "Sale 3 veces" in s and "00:00–00:03 ×1" in s and "00:06–00:08 ×2" in s and "libre 00:15 de 00:20" in s, s
    print(f"✓ resumen de usos: «{s}»")

    # ---- solo el tramo marcado (I/O): 5–12 s (lo vacío de ese tramo), sin faltar material
    ctrl.set_mark("in", 5.0)
    ctrl.set_mark("out", 12.0)
    ac.refresh_donde()
    ac.donde.setCurrentIndex(ac.donde.findData("io"))
    before = set(p.clips)
    n_undo = ctrl.undo_stack.count()
    ac.run()
    t0 = time.time()
    while ac.job is not None and ac.job.isRunning() and time.time() - t0 < 90:
        pump(app, 0.1)
    pump(app, 0.3)
    assert vmid in ac.scenes and len(ac.scenes[vmid]) >= 5, ac.scenes.get(vmid)     # analizó las escenas antes
    add = new_clips(p, before)
    assert add and all(c.track_id == v1.id for c in add), add
    assert all(5.0 - EPS <= c.start and c.end <= 12.0 + EPS for c in add), [(c.start, c.end) for c in add]
    assert abs(sum(c.duration for c in add) - 7.0) < 0.05, "todo el tramo tapado"
    src = [(c.source_in, c.source_in + c.src_len) for c in add]
    assert no_overlaps(src) and not any(overlap(a, b, x, y) for a, b in src for x, y in used0), src
    assert ctrl.undo_stack.count() == n_undo + 1, "un solo paso de Ctrl+Z"
    assert set(win.timeline.selected) == {c.id for c in add}, "los clips nuevos, elegidos"
    assert ac.last_missing < 0.05 and "Faltó" not in ac.info.text(), ac.info.text()
    ctrl.undo_stack.undo()
    assert set(p.clips) == before
    ctrl.clear_marks()
    print(f"✓ solo el tramo I/O: {len(add)} trozos en 5–12 s, de lo no usado, un Ctrl+Z, elegidos")

    # ---- todos los huecos: 3–20, 22–26 y 28–30 (23 s) con 15 s libres → falta material y se avisa
    ac.donde.setCurrentIndex(ac.donde.findData("todos"))
    for orden in ("video", "variado"):
        ac.orden.setCurrentIndex(ac.orden.findData(orden))
        before = set(p.clips)
        ids = ac.fill()
        add = new_clips(p, before)
        assert ids and set(ids) == {c.id for c in add}
        tl = [(c.start, c.end) for c in p.clips_on(v1.id)]
        assert no_overlaps(tl), tl
        src = [(c.source_in, c.source_in + c.src_len) for c in add]
        assert no_overlaps(src), ("los nuevos no se repiten entre sí", sorted(src))
        assert not any(overlap(a, b, x, y) for a, b in src for x, y in used0), ("nada de lo ya usado", src)
        assert all(c.duration <= 6.0 * 1.25 + EPS for c in add), [c.duration for c in add]   # (2–6 s; +25 % al cerrar)
        tapado = sum(c.duration for c in add)
        assert 13.5 < tapado <= 15.0 + 0.05, tapado
        assert abs(ac.last_missing - (23.0 - tapado)) < 0.05 and "Faltó material" in ac.info.text(), ac.info.text()
        assert all(c.volume == 0.0 for c in add), "sin su sonido"
        if orden == "video":
            ss = [c.source_in for c in sorted(add, key=lambda c: c.start)]
            assert ss == sorted(ss), ss
        ctrl.undo_stack.undo()
        assert set(p.clips) == before
    win.grab().save(os.path.join(out, "autocompletar.png"))
    print(f"✓ todos los huecos: solo tramos no usados, sin solapes, avisa «{ac.info.text().splitlines()[-1]}»")

    # ---- todo usado → aviso y nada cambia
    before = set(p.clips)
    full = ac.fill()                                    # (se gasta todo lo libre)
    after_full = set(p.clips)
    n_undo = ctrl.undo_stack.count()
    again = ac.fill()
    assert full and again is None and "material libre" in ac.info.text() and set(p.clips) == after_full, \
        ac.info.text()
    assert ctrl.undo_stack.count() == n_undo
    ctrl.undo_stack.undo()
    assert set(p.clips) == before
    print(f"✓ sin material libre: «{ac.info.text()}»")

    # ---- solo lo elegido: el hueco 22–26 de la pista principal
    win.timeline.set_selection([])
    win.timeline.gap = (v1.id, 22.0, 26.0)
    ac.refresh_donde()
    ac.donde.setCurrentIndex(ac.donde.findData("elegido"))
    assert ac.donde.currentData() == "elegido"
    before = set(p.clips)
    ac.fill()
    add = new_clips(p, before)
    assert add and all(22.0 - EPS <= c.start and c.end <= 26.0 + EPS and c.track_id == v1.id for c in add)
    assert abs(sum(c.duration for c in add) - 4.0) < 0.05
    ctrl.undo_stack.undo()
    win.timeline.gap = None
    print("✓ solo lo elegido: el hueco 22–26 s")

    # ---- pista bloqueada: la principal bloqueada → va a otra pista de video; todas bloqueadas → aviso
    ac.donde.setCurrentIndex(ac.donde.findData("todos"))
    if len([tr for tr in p.tracks if tr.kind == TRACK_VIDEO]) < 2:
        ctrl.add_track(TRACK_VIDEO)
    v1 = SP.main_video_track(p)
    ctrl.set_track_props(v1.id, "bloquear", locked=True)
    assert p.track(v1.id).locked
    main_before = sorted((c.id, c.start, c.duration, c.source_in) for c in p.clips_on(v1.id))
    before = set(p.clips)
    ids = ac.fill()
    add = new_clips(p, before)
    assert ids and add and all(c.track_id != v1.id for c in add), [c.track_id for c in add]
    assert sorted((c.id, c.start, c.duration, c.source_in) for c in p.clips_on(v1.id)) == main_before
    ctrl.undo_stack.undo()
    for tr in p.tracks:
        if tr.kind == TRACK_VIDEO and not tr.locked:
            ctrl.set_track_props(tr.id, "bloquear", locked=True)
    before = set(p.clips)
    assert ac.fill() is None and "bloqueadas" in ac.info.text() and set(p.clips) == before, ac.info.text()
    for tr in p.tracks:
        if tr.kind == TRACK_VIDEO:
            ctrl.set_track_props(tr.id, "desbloquear", locked=False)
    print("✓ pistas bloqueadas: no se tocan (va a otra pista de video; si todas lo están, avisa)")

    # ---- lo desactivado de la pista destino también tapa: no se borra
    v1 = SP.main_video_track(p)
    c26 = next(c for c in p.clips_on(v1.id) if abs(c.start - 26.0) < 1e-3)
    ctrl.set_clip_props([c26.id], "desactivar", enabled=False)
    before = set(p.clips)
    ac.donde.setCurrentIndex(ac.donde.findData("todos"))
    assert ac.fill()
    c26b = p.clips.get(c26.id)
    assert c26b is not None and abs(c26b.start - 26.0) < 1e-3 and abs(c26b.duration - 2.0) < 1e-3, "no se borra"
    assert not any(overlap(c.start, c.end, 26.0, 28.0) for c in new_clips(p, before))
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    assert p.clips[c26.id].enabled
    print("✓ un clip desactivado de la pista destino cuenta como ocupado: no se borra")

    # ---- elegido a mano: la línea de tiempo no lo pisa (Medios sí)
    import shutil
    vid2 = os.path.join(out, "otro.mp4")
    shutil.copyfile(vid, vid2)
    (v2mid,) = ctrl.import_now([vid2])
    while ctrl.analyzing:
        pump(app, 0.1)
    ac.refresh()
    ac.set_media(v2mid)
    ac._picked_by_hand()
    win.timeline.set_selection([c26.id])
    pump(app, 0.1)
    assert ac.media_id() == v2mid, "lo elegido a mano se queda"
    ac._manual_t = None
    win.timeline.set_selection([])
    win.timeline.set_selection([c26.id])
    assert ac.media_id() == vmid, "sin elegir a mano, sigue a la línea de tiempo"
    win.timeline.set_selection([])
    print("✓ el video elegido a mano no lo cambia la línea de tiempo")

    # ---- ✕ Cancelar la búsqueda de escenas: no rellena nada
    ac.set_media(vmid)
    saved = ac.scenes.pop(vmid)
    before = set(p.clips)
    ac.run()
    assert ac.btn_cancel.isEnabled()
    ac.cancel()
    t0 = time.time()
    while ac.job is not None and ac.job.isRunning() and time.time() - t0 < 60:
        pump(app, 0.1)
    pump(app, 0.3)
    assert set(p.clips) == before and "cancelada" in ac.info.text() and not ac.btn_cancel.isEnabled(), ac.info.text()
    ac.scenes[vmid] = saved
    print(f"✓ ✕ Cancelar: «{ac.info.text()}»")

    # ---- las tres pestañas: el control a la vista; en Vertical, con el relleno de fondo
    for tab in ("edit", "short", "youtube"):
        assert win.workspaces.switch(tab), tab
        pump(app, 0.3)
        win.show_panel(win.ai_panel)
        t.setCurrentIndex(next(i for i in range(t.count()) if t.tabText(i) == "Inicio"))
        pump(app, 0.4)
        assert win.ai_panel.autocompletar is ac and ac.isVisible(), tab
        ac.refresh()
        if tab == "short":
            q = ctrl.project

            def find(path):
                return next((m.id for m in q.media.values()
                             if os.path.normcase(os.path.abspath(m.path)) == os.path.normcase(os.path.abspath(path))),
                            None)
            if find(vid) is None or find(song) is None:      # (si la pestaña no los trajo de la otra)
                ctrl.import_now([x for x in (vid, song) if find(x) is None])
                while ctrl.analyzing:
                    pump(app, 0.1)
            mid, aud = find(vid), find(song)
            at = [tr for tr in q.tracks if tr.kind == TRACK_AUDIO][0]
            ctrl.add_media([aud], at.id, 0.0)
            ac.refresh()
            assert ac.set_media(mid)
            ac.donde.setCurrentIndex(ac.donde.findData("todos"))
            before = set(q.clips)
            ac.run()
            t0 = time.time()
            while ac.job is not None and ac.job.isRunning() and time.time() - t0 < 90:
                pump(app, 0.1)
            pump(app, 0.2)
            add = new_clips(q, before)
            assert add, ac.info.text()
            assert q.height > q.width and all((c.fx or {}).get("relleno") for c in add), \
                [(c.fx, c.layout) for c in add]
            ctrl.undo_stack.undo()
        print(f"✓ pestaña «{tab}»: ✨ Autocompletar a la vista" + (" (con relleno de fondo vertical)"
                                                                   if tab == "short" else ""))
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "autocompletar")
    os.makedirs(out, exist_ok=True)
    test_logic()
    test_panel(out)
    print("✓ TODO OK")
