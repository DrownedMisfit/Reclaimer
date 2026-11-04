"""
Prueba de «⭐ Mis efectos para la IA» (propone dónde poner tus efectos favoritos, ✓/✗ aprende) y de
«🎯 Buscar con un ejemplo» (un clip o imagen tuya como ✓ de lo que buscas, con recuadro opcional).
Usa una carpeta de datos TEMPORAL; las huellas de la IA se simulan (no se descarga ningún modelo).
Ejecutar:  .venv/Scripts/python.exe tests/test_fx_memory.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import wave

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
from PySide6.QtCore import QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import effect_memory as EM  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from test_edits2 import DROP, make_song  # noqa: E402

RNG = np.random.default_rng(5)


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


BASE = {k: unit(RNG.standard_normal(512)) for k in ("accion", "calma", "oscuro", "otro")}


def fake_vecs(kind: str, n: int):
    """Huellas «de mentira» parecidas a un tipo de imagen (para no cargar el modelo)."""
    return np.stack([unit(BASE[kind] + 0.35 * unit(RNG.standard_normal(512))) for _ in range(n)])


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def silence_wav(path, secs):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * secs))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    saved_mem = st.value("efectos/memoria")

    # --- 1) Qué sabe de cada efecto
    assert EM.effect_info("look:flash")["apply"] == "moment"
    assert EM.effect_info("look:oldfilm")["apply"] == "clip"
    assert EM.effect_info("sfx:whoosh_largo")["category"] == "Transiciones"
    assert EM.effect_info("file:C:/x/Big Boom Impact 03.wav")["category"] == "Golpes"
    assert EM.effect_info("trans:fade")["apply"] == "cut"
    print("✓ tipos de efecto: momento / todo el clip / sonido (también los de tu carpeta, por el nombre) / corte")

    # --- Material
    ff = media_tools.ffmpeg()
    song = os.path.join(out, "fx_cancion.wav")
    make_song(song)
    narr = os.path.join(out, "fx_narracion.wav")
    silence_wav(narr, 34.0)
    vids = []
    for name, src in (("fx_a.mp4", "testsrc2=s=640x360:r=30:d=40"), ("fx_b.mp4", "mandelbrot=s=640x360:r=30"),
                      ("fx_c.mp4", "smptebars=s=640x360:r=30"), ("fx_d.mp4", "rgbtestsrc=s=640x360:r=30")):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            r = subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "40",
                                "-c:v", "libx264", "-preset", "ultrafast", p], capture_output=True)
            assert r.returncode == 0, r.stderr
        vids.append(p)

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    ids = ctrl.import_paths([song, narr] + vids)
    while ctrl.analyzing:
        pump(app, 0.1)
    by = {p.media[i].name: i for i in ids}
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a2 = p.track(ctrl.ensure_role_track("musica"))
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is None)
    # 4 planos seguidos: 0–8 (acción) · 8–16 (tranquilo) · 16–24 (otro) · 24–32 (oscuro)
    kinds = {"fx_a.mp4": "accion", "fx_b.mp4": "calma", "fx_c.mp4": "otro", "fx_d.mp4": "oscuro"}
    for k, name in enumerate(("fx_a.mp4", "fx_b.mp4", "fx_c.mp4", "fx_d.mp4")):
        ctrl.add_media([by[name]], v1.id, 8.0 * k)
        c = max(p.clips_on(v1.id), key=lambda x: x.start)
        ctrl.set_clip_props([c.id], "dur", duration=8.0)
        ctrl.clip_vecs[by[name]] = (np.arange(40, dtype=np.float32), fake_vecs(kinds[name], 40))
    for c in list(p.clips.values()):           # sin el sonido de los videos (más simple)
        if c.track_id != v1.id and p.media[c.media_id].name.startswith("fx_") and c.media_id != by["fx_narracion.wav"]:
            ctrl.delete_clips([c.id])
    ctrl.add_media([by["fx_narracion.wav"]], a1.id, 0.0)
    ctrl.add_media([by["fx_cancion.wav"]], a2.id, 0.0)
    words = [[2.0, 2.4, "Bueno,"], [2.4, 2.9, "fíjense"], [2.9, 3.2, "en"], [3.2, 3.6, "esto."],
             [10.0, 10.3, "Hace"], [10.3, 10.8, "años"], [10.8, 11.2, "era"], [11.2, 11.6, "distinto."],
             [19.0, 19.4, "Fue"], [19.4, 19.7, "un"], [19.7, 20.2, "desastre."]]
    ctrl.set_transcript(by["fx_narracion.wav"], {"language": "es", "words": words})
    ctrl.set_topics(by["fx_narracion.wav"], [{"start": 0.0, "end": 15.9, "topic": "Intro"},
                                              {"start": 16.0, "end": 34.0, "topic": "El problema"}])
    t0 = time.time()
    while by["fx_cancion.wav"] not in ctrl.rhythm and time.time() - t0 < 60:
        pump(app, 0.1)
    assert by["fx_cancion.wav"] in ctrl.rhythm
    drop_t = ctrl.rhythm_on_timeline()["drops"][0]
    assert abs(drop_t - DROP) < 0.25, drop_t

    # --- 2) Momentos del video
    EM.visual_text_vecs = lambda: {k: BASE[k] for k in ("accion", "calma", "oscuro")}   # sin modelo
    moms = EM.find_moments(p, ctrl.clip_vecs, ctrl.rhythm, text_vecs=EM.visual_text_vecs())
    kinds_found = {m["kind"] for m in moms}
    for k in ("corte", "inicio", "final", "tema", "golpe", "drop", "antes_drop", "senala", "pasado", "negativo",
              "accion", "calma", "oscuro"):
        assert k in kinds_found, (k, sorted(kinds_found))
    tema = next(m for m in moms if m["kind"] == "tema")
    assert abs(tema["t"] - 16.0) < 1e-3 and tema["at_cut"], tema
    pas = next(m for m in moms if m["kind"] == "pasado")
    assert abs(pas["t"] - 10.0) < 1e-3 and "Hace años" in pas["word"], pas
    acc = next(m for m in moms if m["kind"] == "accion")
    assert abs(acc["t"] - 0.0) < 1e-3, acc
    print(f"✓ momentos: {len(moms)} — " + ", ".join(sorted(kinds_found)))

    # --- 3) El panel: elegir efectos y proponer
    fx = win.effects
    fx.memory = []
    for k in ("look:flash", "sfx:whoosh_largo", "look:oldfilm", "trans:fade", "sfx:riser"):
        fx.add_to_memory(k)
    assert fx.mem_list.count() == 5 and "sfx:riser" in str(st.value("efectos/memoria"))
    fx.propose_effects()
    t0 = time.time()
    while fx._fx_job is not None and time.time() - t0 < 60:
        pump(app, 0.1)
    props = fx.proposals
    got = {(x["effect"], x["kind"]) for x in props}
    assert ("look:flash", "drop") in got, got
    assert ("sfx:whoosh_largo", "tema") in got, got
    assert ("look:oldfilm", "pasado") in got, got
    assert ("trans:fade", "tema") in got, got
    assert ("sfx:riser", "antes_drop") in got, got
    assert len(win.timeline.effect_marks) == len(props) == fx.prop_tree.topLevelItemCount()
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "fx_propuestas.png"))
    print(f"✓ {len(props)} propuestas: " + "; ".join(f"{x['name']} @ {x['t']:.1f}s ({x['reason']})" for x in props))

    # --- 4) ✓ el destello del drop: corta el clip en el drop y lo pone ahí (un Ctrl+Z)
    i = next(k for k, x in enumerate(props) if x["effect"] == "look:flash" and x["kind"] == "drop")
    n_undo = ctrl.undo_stack.index()
    fx._prop_clicked(fx.prop_tree.topLevelItem(i), 3)
    c = p.clip_at(v1.id, drop_t + 0.01)
    assert abs(c.start - drop_t) < 0.01 and (c.fx or {}).get("flash"), (c.start, c.fx)
    left = p.clip_at(v1.id, drop_t - 0.05)
    assert not (left.fx or {}).get("flash")
    assert ctrl.undo_stack.index() == n_undo + 1
    assert EM.load_store()["look:flash"]["ctx"]["drop"] == [1, 0]
    ctrl.undo_stack.undo()
    assert not (p.clip_at(v1.id, drop_t + 0.01).fx or {}).get("flash")
    ctrl.undo_stack.redo()
    print(f"✓ ✓ destello: el clip se corta en el drop ({drop_t:.2f} s) y se pone ahí; Ctrl+Z lo quita")

    # --- 5) ✗ película antigua: aprende y baja la nota de ese tipo de momento
    info = EM.effect_info("look:oldfilm")
    before = EM.score("look:oldfilm", info, pas, EM.load_store())
    i = next(k for k, x in enumerate(fx.proposals) if x["effect"] == "look:oldfilm")
    fx._prop_clicked(fx.prop_tree.topLevelItem(i), 4)
    after = EM.score("look:oldfilm", info, pas, EM.load_store())
    assert after < before, (before, after)
    print(f"✓ ✗ película antigua al hablar del pasado: nota {before:.2f} → {after:.2f}")

    # Aprende por cómo es la imagen: ✓ en un plano de acción sube los parecidos
    m_acc = dict(acc, kind="golpe", w=0.6)
    m_cal = next(dict(m, kind="golpe", w=0.6) for m in moms if m["kind"] == "calma")
    s0 = EM.score("look:flash", EM.effect_info("look:flash"), m_acc, EM.load_store()) - \
        EM.score("look:flash", EM.effect_info("look:flash"), m_cal, EM.load_store())
    EM.learn("look:flash", "golpe", acc["vec"], True)
    EM.learn("look:flash", "golpe", m_cal["vec"], False)
    s1 = EM.score("look:flash", EM.effect_info("look:flash"), m_acc, EM.load_store()) - \
        EM.score("look:flash", EM.effect_info("look:flash"), m_cal, EM.load_store())
    assert s1 > s0 + 0.1, (s0, s1)
    print(f"✓ aprende por la imagen: ventaja acción vs. calma {s0:+.2f} → {s1:+.2f}")

    # --- 6) 🎯 en los clips que elijo yo (el whoosh, en el 2.º plano)
    i = next(k for k, x in enumerate(fx.proposals) if x["effect"] == "sfx:whoosh_largo")
    fx.prop_tree.setCurrentItem(fx.prop_tree.topLevelItem(i))
    target = p.clip_at(v1.id, 9.0)
    win.timeline.set_selection([target.id])
    fx.retarget_current()
    sounds = [c for c in p.clips.values() if (c.note or "").startswith("⭐ Whoosh")]
    assert sounds and abs(sounds[0].start - (target.start - 0.35)) < 0.05, [(s.start, s.note) for s in sounds]
    assert p.track(sounds[0].track_id).kind == TRACK_AUDIO
    assert EM.load_store()["sfx:whoosh_largo"]["ctx"]["elegido"][0] == 1
    print(f"✓ 🎯 whoosh puesto donde elegí ({sounds[0].start:.2f} s, en «{p.track(sounds[0].track_id).name}»)")

    # ✓ todas
    rest = len(fx.proposals)
    fx.accept_all()
    assert not fx.proposals and not win.timeline.effect_marks
    print(f"✓ «Poner todas»: {rest} más")

    # --- 7) 🎯 Buscar con un ejemplo
    from editoria.ui.example_dialog import ExampleDialog
    mp = win.moments
    calls = []
    mp.search_text = lambda: calls.append(mp.query.text())    # sin modelo de texto en la prueba
    saved = []
    dlg = ExampleDialog(ctrl, by["fx_b.mp4"], 12.0, 8.0, 16.0, "", win,
                        on_example=lambda e: (saved.append(e), mp.add_example(e, search=False)))
    dlg.show()
    t0 = time.time()
    while len(dlg.strip.frames) < 12 and time.time() - t0 < 30:
        pump(app, 0.1)
    assert dlg.view.img is not None and len(dlg.strip.frames) == 12, len(dlg.strip.frames)
    dlg._done(True)
    assert dlg.result is None and "Escribe" in dlg.msg.text(), "pide el nombre"
    dlg.name.setText("Roca gigante")
    dlg._done(True)                                # ✓ Esto es: guarda y la ventana SIGUE abierta
    ex = dlg.result
    assert ex and ex["good"] and ex["key"].endswith("@12.0") and len(ex["vec"]) == 512
    assert dlg.isVisible() and not dlg.do_search and calls == [], "«Esto es» ya no busca"
    dlg.strip.picked.emit(9.0)                     # clic en la tira de fotogramas → ese momento
    pump(app, 0.4)
    assert abs(dlg.t - 9.0) < 0.06 and abs(dlg.strip.current - 9.0) < 0.06
    dlg._done(False)                               # ✗ Esto NO es (otro momento)
    assert len(saved) == 2 and [m for _t, m in dlg.strip.marks] == [True, False] and "1 ✓ · 1 ✗" in dlg.msg.text()
    # Varios fotogramas: Ctrl+clic, Mayús+clic (tramo) y el modo «Varios fotogramas»
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    fw = dlg.strip.width() / len(dlg.strip.frames)

    def click(i, mod=Qt.NoModifier):
        QTest.mouseClick(dlg.strip, Qt.LeftButton, mod, QPoint(int((i + 0.5) * fw), 20))
    click(1)
    click(3, Qt.ControlModifier)
    assert dlg.strip.selected == {3}, dlg.strip.selected
    click(6, Qt.ShiftModifier)
    assert dlg.strip.selected == {3, 4, 5, 6}, dlg.strip.selected
    dlg.multi.setChecked(True)
    click(9)
    click(4)
    assert dlg.strip.selected == {3, 5, 6, 9} and "4 fotogramas" in dlg.sel_label.text(), dlg.strip.selected
    pump(app, 0.2)
    dlg.grab().save(os.path.join(out, "fx_ejemplo_tira.png"))
    times = dlg.strip.selected_times()
    dlg._done(True)
    assert len(saved) == 6 and [round(e["t"], 2) for e in saved[2:]] == [round(t, 2) for t in times], \
        [e["t"] for e in saved]
    assert not dlg.strip.selected and "4 fotogramas" in dlg.msg.text() and "5 ✓ · 1 ✗" in dlg.msg.text(), \
        dlg.msg.text()
    dlg._search()                                  # 🔎 Buscar (aparte)
    assert dlg.do_search and not dlg.isVisible()
    from editoria.ai import image_feedback as IF
    fb = IF.load_feedback("Roca gigante", "videos")
    assert ex["key"] in fb["pos"] and saved[1]["key"] in fb["neg"], (list(fb["pos"]), list(fb["neg"]))
    # ✓ Es esto y buscar: las dos cosas de una vez
    d3 = ExampleDialog(ctrl, by["fx_b.mp4"], 14.0, 8.0, 16.0, "Roca gigante", win)
    d3._done(True, search=True)
    assert d3.do_search and len(d3.examples) == 1
    mp.add_example(d3.result)
    assert calls == ["Roca gigante"], calls
    # con recuadro: otra clave (y se calcularía la huella del recorte)
    dlg2 = ExampleDialog(ctrl, by["fx_b.mp4"], 12.0, 8.0, 16.0, "Roca gigante", win)
    dlg2.view.rect_n = QRectF(0.2, 0.2, 0.3, 0.4)
    assert "#0.20,0.20,0.30,0.40" in dlg2.key()
    from editoria.ui.example_dialog import square_224
    sq = square_224(dlg2.view.crop())
    assert sq.shape == (224, 224, 3)
    dlg2.show()
    pump(app, 0.3)
    dlg2.grab().save(os.path.join(out, "fx_ejemplo.png"))
    dlg2.reject()
    # desde la línea de tiempo: el clip seleccionado, con su rango
    opened = []
    mp._example = lambda mid, t, a, b: opened.append((p.media[mid].name, round(t, 1), round(a, 1), round(b, 1)))
    win.timeline.set_selection([p.clip_at(v1.id, 9.0).id])
    win.engine.seek(9.5)
    pump(app, 0.2)
    mp.example_from_timeline()
    assert opened and opened[0][0] == "fx_b.mp4" and abs(opened[0][1] - 1.5) < 0.2, opened
    print(f"✓ 🎯 ejemplo: guardado como ✓ de «Roca gigante» y busca; desde la timeline abre {opened[0]}")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    if saved_mem is None:
        st.remove("efectos/memoria")
    else:
        st.setValue("efectos/memoria", saved_mem)
    for k in ("ventana/paneles", "guia/colocada"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
