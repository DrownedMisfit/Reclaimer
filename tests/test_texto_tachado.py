"""
Prueba de «editar con el texto»: tomas que se repiten / se medio repiten / suenan parecido, coletillas («¿no?») y
muletillas propias, la escucha literal (comparar Whisper con el oído letra a letra), tachar y destachar, elegir
toma, tachar a mano, el resumen y «✂ Cortar lo tachado". Sin mostrar ninguna ventana y sin descargar modelos.
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_texto_tachado.py
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editoria.ai import repetition_detection as rep  # noqa: E402
from editoria.ai import verbatim, voice_cleanup  # noqa: E402
from editoria.core import subtitles  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import SUG_APPLIED, TRACK_AUDIO  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NARRATION = os.path.join(ASSETS, "narracion_prueba.wav")
CACHE = os.path.join(ASSETS, "narracion_prueba.transcripcion.json")
ON = {k for k, v in voice_cleanup.AUTO_DEFAULTS.items() if v}


def words_of(text: str, t0: float = 0.0, step: float = 0.3, pause_after: dict | None = None) -> list[list]:
    """Palabras con tiempos inventados (0,3 s cada una; pausa_after = {índice: segundos de pausa detrás})."""
    out, t = [], t0
    for i, w in enumerate(text.split()):
        out.append([round(t, 3), round(t + step - 0.05, 3), w, 0.95])
        t += step + (pause_after or {}).get(i, 0.0)
    return out


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def test_logic():
    # 1) «Se medio repite» dentro de UNA frase (sin punto ni pausa entre las tomas)
    ws = words_of("El día de ayer yo estaba jugando el día de ayer estaba trabajando en la oficina.")
    takes = rep.find_retakes(ws)
    assert len(takes) == 1, [d["label"] for d in takes]
    d = takes[0]
    assert d["data"]["level"] == "medio" and d["data"]["best"] == 2, d
    gone = " ".join(w[2] for w in ws if d["start"] <= (w[0] + w[1]) / 2 <= d["end"])
    assert gone == "El día de ayer yo estaba jugando", gone
    assert d["label"].startswith("Se medio repite"), d["label"]
    print("✓ se medio repite (misma frase):", d["label"], "· quita:", gone)

    # 2) «Se repite» casi igual, en dos frases, con lo que dijiste después
    ws = words_of("Esto es muy importante para mí. Esto es muy importante para mí, de verdad. Y ahora vamos con el "
                  "combate.", pause_after={5: 0.8, 13: 0.8})
    d = rep.find_retakes(ws)[0]
    assert d["data"]["level"] == "igual", d["data"]
    assert d["data"]["after"].startswith("Y ahora vamos"), d["data"]["after"]
    assert "Después dijiste" in d["detail"]
    print("✓ se repite + «después dijiste»:", d["data"]["after"])

    # 3) La empezaste y la volviste a empezar
    ws = words_of("Lo que quiero decir. Lo que quiero decir es que el juego está roto.", pause_after={3: 0.7})
    d = rep.find_retakes(ws)[0]
    assert d["data"]["level"] == "igual" and d["data"]["best"] == 2, d["data"]
    print("✓ empezada y repetida → se repite")

    # 4) Frases normales con palabras comunes NO son tomas («de la…»)
    ws = words_of("La historia de la saga es larga. La música de la saga es buena y el arte también lo es.",
                  pause_after={6: 0.7})
    assert not rep.find_retakes(ws), rep.find_retakes(ws)
    print("✓ dos frases distintas que empiezan parecido: sin toma repetida")

    # 5) Coletillas «¿no?» y muletillas propias («¿por qué?» solo si es pregunta suelta)
    ws = words_of("Eso fue lo que pasó, ¿no? ¿Por qué? Porque sí. ¿Por qué lo hicieron así? La verdad es que no sé.")
    f = rep.find_fillers(ws, mine=("¿por qué?", "la verdad"))
    labels = [x["label"] for x in f]
    assert "Posible muletilla: «¿no?»" in labels, labels
    assert sum(1 for x in labels if "tuya" in x and "Por" in x) == 1, labels
    assert any("tuya" in x and "verdad" in x.lower() for x in labels), labels
    print("✓ coletilla y muletillas propias:", labels)

    # 6) «Suena parecido» (con un modelo de frases falso) y que NO se tache solo
    ws = words_of("Ayer me puse a trabajar en casa todo el día. Lo que hice ayer fue trabajar en casa sin parar. "
                  "Después salí a correr un rato por el parque.", pause_after={9: 0.8, 19: 0.8})
    def fake(texts):
        v = np.array([[1.0, 0.0] if "trabajar" in t else [0.0, 1.0] for t in texts], np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    sim = rep.find_similar(ws, fake, rep.find_retakes(ws))
    assert len(sim) == 1 and sim[0]["data"]["level"] == "parecido" and sim[0]["data"]["auto"] is False, sim

    class S:  # sugerencia mínima para will_cut
        status, cuttable, kind, label = "pending", True, "retake", sim[0]["label"]
        data = sim[0]["data"]
    assert not voice_cleanup.will_cut(S, ON)
    S.data = dict(sim[0]["data"], tachar=True)
    assert voice_cleanup.will_cut(S, ON)
    print("✓ suena parecido: se avisa y solo se quita si lo tachas")

    # 7) Escucha literal: cómo suena y qué se saltó Whisper
    assert verbatim.sound("estava") == verbatim.sound("estaba") and verbatim.sound("hecho") == verbatim.sound("echo")
    assert verbatim.sound("ahí") != verbatim.sound("así")
    whisper = words_of("Esa entrevista es del 2024. Ocurrió hace más de dos años.", t0=40.0, pause_after={4: 4.0})
    heard = (words_of("esa entrevista es del dos mil veinticuatro", t0=40.0) +
             words_of("ocurrio hace mas de dos", t0=42.6) +
             words_of("ocurrio hace mas de dos años", t0=45.6))
    missed = verbatim.find_missed(whisper, heard)
    assert len(missed) == 1 and 42.4 < missed[0][0] < 42.8 and missed[0][1] < 44.3, missed
    # las cifras de Whisper («2024») no cuentan como algo que se saltó
    assert verbatim.spell(2024) == "dos mil veinticuatro"
    assert not verbatim.find_missed(whisper[:5], words_of("esa entrebista es del dos mil veinticuatro", t0=40.0))
    print("✓ escucha literal: encuentra la toma que Whisper no escribió →", missed[0])
    segs = verbatim._rebuild_segments(whisper[:3] + heard[5:7] + whisper[3:], whisper, [[40.0, 41.5, 0, 5],
                                                                                         [46.0, 48.0, 5, 11]])
    assert segs[0][2] == 0 and segs[-1][3] == 13, segs


def test_controller_and_ui():
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui import transcript_panel as tp_mod

    app = QApplication.instance() or QApplication(sys.argv)
    apply_dark_theme(app)
    from PySide6.QtCore import QSettings
    st = QSettings("EditorIA", "EditorIA")             # casillas de ⚡ como vienen (al terminar se devuelven las tuyas)
    for k, v in voice_cleanup.AUTO_DEFAULTS.items():
        st.setValue(f"limpieza_auto/{k}", v)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    (nid,) = ctrl.import_paths([NARRATION])
    while ctrl.analyzing:
        pump(app, 0.1)
    p = ctrl.project
    ctrl.add_media([nid], [t for t in p.tracks if t.kind == TRACK_AUDIO][0].id, 0.0)
    samples = media_tools.decode_mono(NARRATION, 16000)
    tr = voice_cleanup.refine_transcript(samples, 16000, json.load(open(CACHE, encoding="utf-8")))
    tr["aligned"] = True                          # (la prueba no espera al alineador)
    ctrl.set_transcript(nid, tr)
    opts = voice_cleanup.CleanupOptions(similar=False)
    items = voice_cleanup.analyze(samples, 16000, tr["words"], opts)
    ctrl.set_suggestions(nid, items, opts.kinds(), {k: v[1] for k, v in voice_cleanup.KINDS.items()})
    win.voice.media_combo.setCurrentIndex(win.voice.media_combo.findData(nid))
    pump(app, 0.5)
    panel = win.transcript
    win.right_tabs.setCurrentWidget(panel)
    panel._set_view(0)
    panel._rebuild()

    def struck_words() -> list[str]:
        out = []
        for i, (pos, n) in panel._pos.items():
            cur = panel.view.textCursor()
            cur.setPosition(pos + 1)
            fmt = cur.charFormat()
            if fmt.fontStrikeOut() and fmt.foreground().color() == tp_mod.STRUCK:
                out.append(tr["words"][i][2])
        return out

    s0 = struck_words()
    assert "bastante" in s0 and "Eh," in s0, s0
    assert "demasiado" not in s0 and "este," not in s0, s0     # «este» es solo una posible muletilla
    assert "✂ Cortar (" in panel.btn_cut.text(), panel.btn_cut.text()
    print("✓ texto: lo que se quitará sale tachado en rojo:", " ".join(s0), "·", panel.btn_cut.text())

    words = tr["words"]
    i_bast = next(i for i, w in enumerate(words) if w[2] == "bastante")
    i_dem = next(i for i, w in enumerate(words) if w[2] == "demasiado")
    retake = next(s for s in ctrl.project.suggestions if s.kind == "retake")
    # Clic en lo tachado → se queda las dos tomas
    assert panel._toggle_word(i_bast)
    panel._rebuild()
    assert "bastante" not in struck_words() and "demasiado" not in struck_words()
    # Clic en una toma sin tachar → se tacha ESA (y se queda la otra)
    assert panel._toggle_word(i_dem)
    panel._rebuild()
    sw = struck_words()
    assert "demasiado" in sw and "bastante" not in sw, sw
    r = next(s for s in ctrl.project.suggestions if s.id == retake.id)
    assert r.data["best"] == 1 and voice_cleanup.cut_range(r) == (r.alt_start, r.alt_end)
    print("✓ clic: destachar y elegir la otra toma")

    # Tachar a mano «Hola a todos,» (selección + Supr) y destachar una muletilla
    panel._cross_words([0, 1, 2])
    panel._rebuild()
    assert {"Hola", "a", "todos,"} <= set(struck_words()), struck_words()
    i_este = next(i for i, w in enumerate(words) if w[2] == "este,")
    assert panel._toggle_word(i_este)                 # sugerida sin tachar → se tacha
    panel._rebuild()
    assert "este," in struck_words()
    assert panel._toggle_word(i_este)                 # y otra vez → se queda
    panel._rebuild()
    assert "este," not in struck_words()
    manual = [s for s in ctrl.project.suggestions if s.kind == "manual"]
    assert len(manual) == 1 and voice_cleanup.will_cut(manual[0], ON)
    print("✓ tachar a mano, tachar y destachar una muletilla")

    # Resumen: grupos, casillas y que una casilla tache/destache
    panel._set_view(2)
    pump(app, 0.3)
    panel.summary.rebuild()
    tree = panel.summary.tree
    tops = {tree.topLevelItem(i).data(0, Qt.UserRole + 2): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
    assert {"filler", "manual"} <= set(tops) and ({"igual", "medio"} & set(tops)), list(tops)
    take_row = (tops.get("igual") or tops.get("medio")).child(0)
    assert "⭐" in take_row.text(0) and take_row.checkState(0) == Qt.Checked, take_row.text(0)
    assert any("Después dijiste" in take_row.child(k).text(0) for k in range(take_row.childCount()))
    eh_row = next(tops["filler"].child(k) for k in range(tops["filler"].childCount())
                  if "Eh" in tops["filler"].child(k).text(0))
    eh_row.setCheckState(0, Qt.Unchecked)
    pump(app, 0.3)
    eh = next(s for s in ctrl.project.suggestions if s.kind == "filler" and "Eh" in s.label)
    assert eh.data.get("tachar") is False, eh.data
    print("✓ resumen:", ", ".join(tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())))

    # ✂ Cortar lo tachado (sin preguntar en la prueba)
    real_q = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        panel.cut_marked()
    finally:
        QMessageBox.question = real_q
    pump(app, 0.3)
    texts = [w[2] for w in subtitles.timeline_words(ctrl.project, nid)]
    assert "Hola" not in texts and "demasiado" not in texts and "bastante" in texts, texts
    assert "principio." not in texts, texts                        # la toma que sobra, con el resto de su frase
    assert "este," in texts and "Eh," in texts, texts               # los que destachaste se quedan
    assert any(s.status == SUG_APPLIED and s.kind == "manual" for s in ctrl.project.suggestions)
    print("✓ cortar lo tachado →", " ".join(texts))
    ctrl.undo_stack.undo()
    texts = [w[2] for w in subtitles.timeline_words(ctrl.project, nid)]
    assert "Hola" in texts and "demasiado" in texts, texts
    print("✓ un Ctrl+Z lo devuelve todo")

    # 3 horas de texto: dibujarlo y el resumen tienen que ir rápido
    big = []
    base = [w[2] for w in words]
    t = 0.0
    while len(big) < 30000:
        for w in base:
            big.append([round(t, 3), round(t + 0.25, 3), w, 0.9])
            t += 0.36
    big_tr = {"words": big, "segments": [[big[i][0], big[min(i + 40, len(big)) - 1][1], i, min(i + 40, len(big))]
                                         for i in range(0, len(big), 40)]}
    big_items = voice_cleanup.analyze(np.zeros(int(t * 100), np.float32), 100, big, voice_cleanup.CleanupOptions(
        silences=False, noises=False, clipping=False, similar=False))
    ctrl.set_transcript(nid, big_tr)
    ctrl.set_suggestions(nid, big_items, opts.kinds(), {k: v[1] for k, v in voice_cleanup.KINDS.items()})
    t0 = time.time()
    panel._rebuild()
    t_text = time.time() - t0
    t0 = time.time()
    panel.summary.rebuild()
    t_sum = time.time() - t0
    print(f"✓ 30 000 palabras ({len(big_items)} sugerencias): texto en {t_text:.1f} s, resumen en {t_sum:.1f} s")
    assert t_text < 15 and t_sum < 15, (t_text, t_sum)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()


if __name__ == "__main__":
    test_logic()
    test_controller_and_ui()
    print("\nTODO OK")
