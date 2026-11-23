"""
📍 PRUEBA de la fase 5 de la línea de tiempo: marcadores automáticos en una capa + índice.
  · con narracion_prueba (que trae una toma repetida, muletillas y una palabra repetida) y una toma repetida más,
    fabricada: salen tomas, muletillas, cortes dudosos (sin repetir el que cae encima de una propuesta), marcas de
    OBS, temas, tus marcadores con su nota, huecos sin imagen y material repetido; cada sitio una sola vez;
  · navegación (siguiente / anterior, con filtro de tipos) y Mayús+↑ / Mayús+↓ en la ventana;
  · «está bien así» quita la marca (cada fuente con su estado) y Ctrl+Z la devuelve;
  · «Quitar todas las tomas viejas» en UN Ctrl+Z: queda la última toma de cada una (también con 3 y 4 tomas y la
    mejor la 1.ª: se quitan todas menos la última, y la capa pinta una marca por toma que sobra);
  · el índice cabe en un lateral estrecho; la capa de 1 h de proyecto se calcula en menos de 30 ms;
  · M+M: la nota del marcador en el índice; los atajos nuevos no chocan con ninguno;
  · la capa se pinta en la regla (tooltip) y el índice cuenta y filtra bien.
Sin ventanas visibles (offscreen), datos aislados. Ejecutar:  .venv/Scripts/python.exe tests/test_marcadores_auto.py <c>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None          # (no se abre ningún menú de verdad; solo por si acaso)


def _vigilante(segundos: float = 420.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "marcadores_auto")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import repetition_detection as REP
    from editoria.core import marcadores_auto as MA
    from editoria.core import media as M
    from editoria.core import repetidos as R
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, Marker, Suggestion, new_id
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    wav = os.path.join(RAIZ, "tests", "assets", "narracion_prueba.wav")
    words = json.load(open(os.path.join(RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json"),
                           encoding="utf-8"))["words"]
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12",
                        "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.6)
    ctrl, tl = win.ctrl, win.timeline
    nid, vmid = ctrl.import_now([wav, vid])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    p = ctrl.project
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([nid], a1.id, 0.0)
    p = ctrl.project
    # 🎙 la transcripción de la narración (ya trae una toma repetida) + otra toma FABRICADA en la pausa de 3,7–7,1 s
    p.transcripts[nid] = {"words": words}
    sugs = [dict(d, kind="retake") for d in REP.find_retakes(words)] + \
        [dict(d, kind="filler") for d in REP.find_fillers(words)] + \
        [dict(d, kind="repeat") for d in REP.find_repeated_words(words)]
    sugs.append({"kind": "retake", "start": 4.0, "end": 5.0, "alt_start": 5.5, "alt_end": 6.5,
                 "label": "Toma repetida (fabricada)", "detail": "", "data": {"best": 2}})
    for d in sugs:
        p.suggestions.append(Suggestion(new_id(), d["kind"], nid, float(d["start"]), float(d["end"]),
                                        d.get("label", ""), d.get("detail", ""), alt_start=d.get("alt_start"),
                                        alt_end=d.get("alt_end"), data=dict(d.get("data") or {})))
    n_tomas = sum(1 for d in sugs if d["kind"] == "retake")
    assert n_tomas >= 2, sugs
    # 🎬 video solo en 0–5 s (lo demás de la voz es un hueco sin imagen) y dos clips que repiten el mismo tramo
    c1 = Clip(new_id(), vmid, v1.id, 0.0, 0.0, 5.0)
    p.clips[c1.id] = c1
    # 📍 marcadores: uno tuyo con nota, una marca de OBS (roja) y un tema
    p.markers += [Marker(new_id(), 15.0, "Revisar", note="sube la música"),
                  Marker(new_id(), 22.0, "NG", color="#e5484d"),
                  Marker(new_id(), 0.0, "Introducción", kind="topic", end=7.0, origin="ai")]
    p.markers.sort(key=lambda m: m.time)
    ctrl._bump_rev()
    ctrl.project_changed.emit()
    ret = next(s for s in p.suggestions if s.kind == "retake")
    cuts = [{"key": "sobre_toma", "t": ret.start + 0.1, "track_id": a1.id, "reasons": ["Palabra cortada"]},
            {"key": "suelto", "t": 25.0, "track_id": a1.id, "reasons": ["La voz suena en el corte"]}]

    # ---------------------------------------------------------------- 1) la capa
    capa = MA.capa(p, cuts, None)
    n = MA.contar(capa)
    print("capa:", n)
    assert n["toma"] == n_tomas and n["muletilla"] >= 2, n
    assert n["duda"] == 1 and capa[[m.ref for m in capa].index("suelto")].tipo == "duda", \
        "el corte encima de una propuesta no sale dos veces"
    assert n["obs"] == 1 and n["tema"] == 1 and n["marcador"] == 1, n
    assert any(m.tipo == "marcador" and "sube la música" in m.texto for m in capa), "la nota, en el texto"
    assert n["hueco"] == 1, n
    hueco = next(m for m in capa if m.tipo == "hueco")
    assert abs(hueco.t - 5.0) < 0.05 and hueco.fin > 25, hueco
    assert [m.t for m in capa] == sorted(m.t for m in capa), "en el orden del video"
    assert len({(m.tipo, m.ref) for m in capa}) == len(capa), "cada sitio una vez"
    c2 = Clip(new_id(), vmid, v1.id, 40.0, 1.0, 3.0)                       # repite 1–3 s del archivo
    p.clips[c2.id] = c2
    ctrl._bump_rev()
    capa = MA.capa(p, cuts, R.mapa(p, ctrl.missing))
    assert {m.ref for m in capa if m.tipo == "repetido"} == {c1.id, c2.id}, [m for m in capa if m.tipo == "repetido"]
    # silencios y ruidos de Limpieza NO entran (ya salen allí)
    p.suggestions.append(Suggestion(new_id(), "silence", nid, 4.0, 6.5, "Silencio largo"))
    assert len(MA.capa(p, cuts, None)) == len([m for m in capa if m.tipo != "repetido"])

    # ---------------------------------------------------------------- 2) navegación
    vistos, t = [], -1.0
    while (mk := MA.siguiente(capa, t, 1)) is not None:
        vistos.append(mk)
        t = mk.t
    assert len(vistos) == len({m.t for m in capa}), (len(vistos), len(capa))
    assert MA.siguiente(capa, 26.0, -1, {"duda"}).ref == "suelto"
    assert MA.siguiente(capa, 0.5, 1, {"obs"}).t == 22.0

    # ---------------------------------------------------------------- 3) está bien así + Ctrl+Z
    n_hist = ctrl.undo_stack.index()
    MA.dar_por_revisada(ctrl, hueco)
    assert not any(m.tipo == "hueco" for m in MA.capa(p, cuts, None)), "el hueco revisado no vuelve a salir"
    mk_obs = next(m for m in capa if m.tipo == "obs")
    MA.dar_por_revisada(ctrl, mk_obs)
    assert next(m for m in p.markers if m.id == mk_obs.ref).resuelto
    assert not any(m.tipo == "obs" for m in MA.capa(p, cuts, None))
    assert ctrl.undo_stack.index() == n_hist + 2, "un Ctrl+Z cada uno"
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()
    p = ctrl.project
    assert any(m.tipo == "hueco" for m in MA.capa(p, cuts, None)) and any(m.tipo == "obs" for m in MA.capa(p, cuts, None))

    # ---------------------------------------------------------------- 4) quitar todas las tomas viejas (un Ctrl+Z)
    def voz():
        return sorted((round(c.start, 3), round(c.duration, 3), round(c.source_in, 3))
                      for c in p.clips.values() if c.media_id == nid)
    antes = voz()
    largo0 = sum(d for _s, d, _i in antes)
    n_hist = ctrl.undo_stack.index()
    msg = MA.quitar_tomas_viejas(ctrl)
    print("tomas:", msg)
    p = ctrl.project
    assert msg.startswith("✓") and ctrl.undo_stack.index() == n_hist + 1, msg
    quitado = largo0 - sum(d for _s, d, _i in voz())
    esperado = sum(s.end - s.start for s in p.suggestions if s.kind == "retake")
    assert abs(quitado - esperado) < 0.15, (quitado, esperado)
    assert not MA.tomas_viejas(p) and not any(m.tipo == "toma" for m in MA.capa(p, [], None))
    # se quedó la ÚLTIMA toma: la 2.ª de la fabricada (5,5–6,5 s del archivo) sigue en la línea de tiempo
    assert any(c.source_in <= 5.6 and c.source_in + c.src_len >= 6.4 for c in p.clips.values() if c.media_id == nid)
    ctrl.undo_stack.undo()
    p = ctrl.project
    assert voz() == antes and len(MA.tomas_viejas(p)) == n_tomas, "un Ctrl+Z lo devuelve todo"

    # ---------------------------------------------------------------- 4b) 3 y 4 tomas con la mejor la 1.ª
    for n_t in (3, 4):
        for s in p.suggestions:
            if s.kind == "retake" and s.status == "pending":
                s.status = "rejected"
        tomas = [(14.5 + 3.0 * k, 15.5 + 3.0 * k) for k in range(n_t)]      # (en la narración: 14,5–25,5 s)
        for k in range(1, n_t):                        # como _retake_items: una pareja (toma, la MEJOR = la 1.ª)
            p.suggestions.append(Suggestion(new_id(), "retake", nid, tomas[0][0], tomas[0][1], f"{n_t} tomas", "",
                                            alt_start=tomas[k][0], alt_end=tomas[k][1], data={"best": 1}))
        ctrl._bump_rev()
        marcas_t = [m for m in MA.capa(p, [], None) if m.tipo == "toma"]
        assert len(marcas_t) == n_t - 1 and len({(m.t, m.fin) for m in marcas_t}) == n_t - 1, \
            f"{n_t} tomas: una marca por cada toma que sobra ({len(marcas_t)})"
        antes = voz()
        largo0 = sum(d for _s, d, _i in antes)
        n_hist = ctrl.undo_stack.index()
        msg = MA.quitar_tomas_viejas(ctrl)
        p = ctrl.project
        print(f"{n_t} tomas:", msg)
        assert msg.startswith(f"✓ Quitadas {n_t - 1} toma") and ctrl.undo_stack.index() == n_hist + 1, msg
        quitado = largo0 - sum(d for _s, d, _i in voz())
        assert abs(quitado - (n_t - 1) * 1.0) < 0.1, (n_t, quitado)
        ult = tomas[-1]
        assert any(c.source_in <= ult[0] + 0.05 and c.source_in + c.src_len >= ult[1] - 0.05
                   for c in p.clips.values() if c.media_id == nid), "queda la ÚLTIMA toma"
        for a_, b_ in tomas[:-1]:
            assert not any(c.source_in < b_ - 0.05 and c.source_in + c.src_len > a_ + 0.05
                           for c in p.clips.values() if c.media_id == nid), f"la toma {a_} se quitó"
        assert not MA.tomas_viejas(p), "el botón no se queda encendido"
        ctrl.undo_stack.undo()
        p = ctrl.project
        assert voz() == antes
    for s in p.suggestions:                            # (vuelven las de antes para lo que sigue)
        if s.kind == "retake" and s.label in ("3 tomas", "4 tomas"):
            s.status = "rejected"
        elif s.kind == "retake" and s.status == "rejected":
            s.status = "pending"
    ctrl._bump_rev()
    # rapidez: 1 h de narración (9000 palabras, 800 trozos, 120 propuestas, 60 cortes dudosos, 40 marcadores)
    from editoria.core.model import KIND_AUDIO, KIND_VIDEO as _KV, MediaItem, Project
    q = Project.new(minimal=True)
    vz = MediaItem(new_id(), "/falso/voz.wav", KIND_AUDIO, "voz.wav", duration=4000.0, probed=True)
    cam = MediaItem(new_id(), "/falso/cam.mp4", _KV, "cam.mp4", duration=4000.0, probed=True)
    q.media[vz.id], q.media[cam.id] = vz, cam
    qa = [t for t in q.tracks if t.kind == TRACK_AUDIO][0]
    qv = [t for t in q.tracks if t.kind == TRACK_VIDEO][0]
    q.transcripts[vz.id] = {"words": [[i * 0.4, i * 0.4 + 0.3, f"p{i}", 1.0] for i in range(9000)]}
    for i in range(800):
        q.clips[f"n{i}"] = Clip(f"n{i}", vz.id, qa.id, i * 4.4, i * 4.5, 4.4)
        if i % 4:
            q.clips[f"v{i}"] = Clip(f"v{i}", cam.id, qv.id, i * 4.4, i * 4.5, 4.4)
    for i in range(120):
        q.suggestions.append(Suggestion(new_id(), "filler" if i % 2 else "retake", vz.id, i * 30.0, i * 30.0 + 0.8,
                                        "x", alt_start=i * 30.0 + 1, alt_end=i * 30.0 + 1.8))
    for i in range(40):
        q.markers.append(Marker(new_id(), i * 80.0, "m"))
    qcuts = [{"key": f"c{i}", "t": i * 55.0 + 3, "track_id": qa.id, "reasons": ["x"]} for i in range(60)]
    MA.capa(q, qcuts, None)
    t0 = time.perf_counter()
    for _k in range(3):
        mq = MA.capa(q, qcuts, None)
    t_capa = (time.perf_counter() - t0) / 3 * 1000
    print(f"capa con 1 h de proyecto: {len(mq)} marcas en {t_capa:.1f} ms")
    assert t_capa < 30, t_capa

    # ---------------------------------------------------------------- 5) la ventana: capa, Mayús+↑/↓, M+M, índice
    capa_v = win.capa_marcas
    tl.cut_issues = cuts
    capa_v.poner_tipos(set(MA.TIPOS))
    capa_v.recalcular()
    assert tl.capa is capa_v and capa_v.marcas, "la capa de la ventana, al día"
    tl.repaint()
    toma = next(m for m in capa_v.marcas if m.tipo == "toma")
    from PySide6.QtCore import QPointF
    tl.set_playhead(toma.t, follow=True)
    pump(app, 0.2)
    tl.repaint()
    got = tl.marca_en(QPointF(tl.x_for(toma.t), tl.RULER_H - 3))
    assert got is not None and got.tipo in tl.CAPA_PINTA, got
    # atajos: Mayús+↑ / Mayús+↓ en la línea de tiempo, y ninguna otra acción con ellos
    from PySide6.QtGui import QAction, QKeySequence
    acts = {a.text(): a for a in tl.actions()}
    sig, ant = acts["Ir a la marca siguiente"], acts["Ir a la marca anterior"]
    assert sig.shortcut() == QKeySequence("Shift+Down") and ant.shortcut() == QKeySequence("Shift+Up")
    todos = [a for a in win.findChildren(QAction) if not a.shortcut().isEmpty()]
    for k in ("Shift+Up", "Shift+Down", "M"):
        con = [a.text() for a in todos if a.shortcut() == QKeySequence(k)]
        assert len(con) == 1, (k, con)
    win.engine.user_seek(0.0)
    tl.set_playhead(0.0)
    pump(app, 0.2)
    primero = capa_v.siguiente(0.0, 1)
    sig.trigger()
    pump(app, 0.2)
    assert abs(win.engine.time - primero.t) < 0.05, (win.engine.time, primero.t)
    sig.trigger()
    pump(app, 0.2)
    ant.trigger()
    pump(app, 0.2)
    assert abs(win.engine.time - primero.t) < 0.05, "anterior vuelve a la primera"
    # filtro: solo OBS → Mayús+↓ salta a la marca de OBS
    capa_v.poner_tipos({"obs"})
    win.engine.user_seek(1.0)
    tl.set_playhead(1.0)
    pump(app, 0.2)
    sig.trigger()
    pump(app, 0.2)
    assert abs(win.engine.time - 22.0) < 0.05, win.engine.time
    capa_v.poner_tipos(set(MA.TIPOS))
    # el índice: cuenta y filtra
    panel = win.marcadores_panel
    tl._cut_timer.stop()
    tl.cut_issues = cuts                                  # (los cortes dudosos fabricados, otra vez al día)
    capa_v.recalcular()
    panel.refrescar()
    assert panel.lista.count() == len(capa_v.marcas), (panel.lista.count(), len(capa_v.marcas))
    assert panel.botones["toma"].text() == f"Tomas · {n_tomas}", panel.botones["toma"].text()
    panel.botones["toma"].setChecked(False)
    pump(app, 0.1)
    assert "toma" not in capa_v.tipos and panel.lista.count() == len(capa_v.marcas) - n_tomas
    panel.botones["toma"].setChecked(True)
    assert panel.btn_tomas.text().endswith(f"· {n_tomas}") and panel.btn_tomas.isEnabled()
    for b in panel.botones.values():
        assert b.minimumWidth() >= b.sizeHint().width(), "texto entero"
    assert panel.minimumSizeHint().width() <= 260, f"cabe en un lateral estrecho ({panel.minimumSizeHint().width()} px)"
    panel.resize(240, 600)
    panel.fila_tipos.resize(240, panel.fila_tipos.heightForWidth(240))
    panel.fila_tipos.actualizar()
    for b in panel.botones.values():                   # (en 240 px los interruptores bajan de fila, ninguno cortado)
        assert b.geometry().right() <= 240 and b.width() >= b.sizeHint().width(), (b.text(), b.geometry())
    # M+M: el índice está en su sección «Marcadores» del Inspector (gancho de verdad); la nota de ESE marcador
    from editoria.ui import marcadores_panel as MP
    assert "marcadores" in win.inspector.secciones and win.inspector._marcadores_w is panel, \
        "el índice, en su sección del Inspector"
    assert panel.window() is win and MP.instalar(win) is None, "puesto una sola vez"
    n_marc = len(p.markers)
    win.engine.user_seek(18.0)
    tl.set_playhead(18.0)
    pump(app, 0.2)
    win._marker()                                         # M: marcador nuevo en 18 s
    p = ctrl.project
    assert len(p.markers) == n_marc + 1
    nuevo = next(m for m in p.markers if abs(m.time - 18.0) < 0.05)
    win._marker()                                         # M otra vez en el mismo sitio: su nota (no otro marcador)
    p = ctrl.project
    assert len(p.markers) == n_marc + 1, "M+M no añade otro marcador"
    assert panel.marca_elegida() is not None and panel.marca_elegida().ref == nuevo.id and panel.nota.isEnabled()
    panel.nota.setText("cambiar plano")
    panel.nota.returnPressed.emit()
    assert next(m for m in ctrl.project.markers if m.id == nuevo.id).note == "cambiar plano"
    # «está bien así» desde el índice
    i_suelto = next(i for i in range(panel.lista.count()) if panel.lista.item(i).data(MP.ROL_MARCA).ref == "suelto")
    panel.lista.setCurrentRow(i_suelto)
    panel.btn_ok.click()
    assert "suelto" in ctrl.project.cut_ok
    print("✓ test_marcadores_auto: todo bien")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    main()
