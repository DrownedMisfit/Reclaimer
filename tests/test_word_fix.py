"""
Prueba de ✎ corregir una palabra de la transcripción (clic derecho en el panel «Texto»):
  · lo básico: signos que se conservan, lo que se oye «en su sitio», ordenar alternativas, correcciones y
    vocabulario guardados;
  · 🎙 «Volver a escuchar» DE VERDAD con Whisper: se estropea una palabra («combate» → «compadre») y lo que oye otra vez
    tiene que traer «combate» (usa el modelo ya descargado; si no está, esta parte se salta);
  · el menú del panel: alternativas, «escribir», «en todo el texto», «tener en cuenta al transcribir».
Sin mostrar ninguna ventana. Ejecutar:  .venv\\Scripts\\python.exe tests\\test_word_fix.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(ROOT, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(ROOT, "datos", "modelos"))   # los ya descargados
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QInputDialog, QMenu  # noqa: E402

from editoria.ai import word_fix as WF  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NARRATION = os.path.join(ASSETS, "narracion_prueba.wav")
CACHE = os.path.join(ASSETS, "narracion_prueba.transcripcion.json")


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def test_basics():
    assert WF.with_punct("¿haber,", "a ver") == "¿a ver,"
    assert WF.with_punct("War.", "guerra") == "guerra." and WF.core("«Hola!»") == "Hola"
    found = [[1.0, 1.3, "El"], [1.32, 1.8, "combate,"], [1.85, 2.1, "se"]]
    assert WF.heard_at(found, 1.33, 1.79) == "combate"
    assert WF.heard_at([[1.0, 1.3, "a"], [1.31, 1.6, "ver"]], 1.0, 1.6) == "a ver"
    r = WF.rank("haber", ["A ver", "a ver", "haber", "Haber.", "aver", "a ver"])
    assert r == ["a ver", "aver"], r                  # lo más repetido primero, nunca lo que ya pone
    assert WF.rank("Gears", ["gears", "Gear"]) == ["Gear"]
    assert WF.spot(["El", "compadre", "se", "siente"], 1, "El combate se siente") == "combate"
    assert WF.spot(["no", "haber", "dicho"], 1, "No a ver dicho.") == "a ver"
    assert WF.spot(["el", "combate", "se"], 1, "el combate se") == "combate"      # igual: rank lo descarta
    assert WF.spot(["el", "combate", "se"], 1, "el se") == ""
    words = [[i * 0.5, i * 0.5 + 0.4, f"p{i}"] for i in range(40)]
    a, b = WF.window(words, 20)
    assert 6.0 <= a < 10.0 and 10.4 < b <= 14.4, (a, b)
    assert WF.window(words, 0)[0] == 0.0
    print("✓ signos conservados, lo que se oye en su sitio, alternativas ordenadas y el trocito a escuchar")
    assert WF.learned("haber") == []
    WF.remember("haber,", "a ver")
    WF.remember("Haber", "a ver")
    WF.remember("haber", "aver")
    assert WF.learned("¿Haber?") == ["a ver", "aver"], WF.learned("haber")
    assert WF.hotwords() is None
    assert WF.add_vocabulary("Gears of War.") and not WF.add_vocabulary("gears of war")
    assert WF.vocabulary() == ["Gears of War"] and WF.hotwords() == "Gears of War"
    print("✓ las correcciones se recuerdan (la más usada primero) y el vocabulario para Whisper")


def test_relisten():
    from editoria.ai import transcription
    if not transcription.is_downloaded("equilibrado"):
        print("· (sin el modelo descargado: «volver a escuchar» de verdad no se prueba)")
        return
    tr = json.load(open(CACHE, encoding="utf-8"))
    words = [list(w) for w in tr["words"]]
    i = next(k for k, w in enumerate(words) if w[2] == "combate")
    words[i][2] = "compadre"                          # Whisper «se equivocó»
    t0 = time.time()
    alts = WF.alternatives(NARRATION, words, i, tr["model"], "es")
    dt = time.time() - t0
    assert alts and any(a.lower() == "combate" for a in alts), alts
    print(f"✓ 🎙 volver a escuchar de verdad: «compadre» → {alts} en {dt:.1f} s (con cargar el modelo)")
    j = next(k for k, w in enumerate(words) if w[2] == "narrativa")
    words[j][2] = "narrativas"
    WF.TIMES.clear()
    t0 = time.time()
    alts = WF.alternatives(NARRATION, words, j, tr["model"], "es")
    dt = time.time() - t0
    assert any(a.lower() == "narrativa" for a in alts), alts
    print(f"✓ otra palabra con el modelo ya cargado: «narrativas» → {alts} en {dt:.1f} s (escuchas: {WF.TIMES})")


def test_panel():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    from editoria.ui import help as help_ui
    from editoria.core.model import MediaItem
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    tr = json.load(open(CACHE, encoding="utf-8"))
    p.media["voz"] = MediaItem("voz", NARRATION, "audio", "narracion_prueba.wav", duration=28.7, probed=True)
    p.transcripts["voz"] = tr
    tp = win.transcript
    tp._set_view(0)                                   # la vista «Transcripción»
    tp.set_media("voz")
    pump(app, 0.3)
    words = p.transcripts["voz"]["words"]
    i = next(k for k, w in enumerate(words) if w[2] == "combate")
    # el menú del clic derecho, con lo de corregir arriba
    shown = []
    orig_exec = help_ui.exec_menu
    help_ui.exec_menu = lambda menu, _pos: shown.append([a.text() for a in menu.actions()])
    try:
        pos = tp.view.cursorRect(tp.view.textCursor()).center()
        from PySide6.QtGui import QTextCursor
        c = QTextCursor(tp.view.document())
        c.setPosition(tp._pos[i][0] + 1)
        pos = tp.view.cursorRect(c).center()
        tp._context_menu(pos)
        acts = shown[-1]
        assert acts[0].startswith("🎙 Volver a escuchar") or any("Volver a escuchar" in a for a in acts[:4]), acts
        assert any(a.startswith("✎ Escribir la correcta") for a in acts), acts
        assert any(a.startswith("Cambiar en todo el texto (2 veces)") for a in acts), acts     # «combate» sale 2
        assert any("al transcribir" in a for a in acts), acts
        print("✓ clic derecho en «combate»: volver a escuchar, escribir, en todo el texto (2), tener en cuenta")
        # elegir una alternativa (conserva los signos y se recuerda)
        tp._replace_word(i, "embate")
        assert words[i][2] == "embate" and WF.learned("combate") == ["embate"]
        tp._context_menu(pos)
        assert any(a.startswith("embate") for a in shown[-1]) is False   # (ya no pone «combate»: la palabra es otra)
        tp._replace_word(i, "combate")
        tp._context_menu(pos)
        assert any(a.startswith("embate") and "como antes" in a for a in shown[-1]), shown[-1]
        print("✓ lo que corregiste antes sale arriba («como antes»)")
        # en todo el texto
        orig_get = QInputDialog.getText
        QInputDialog.getText = staticmethod(lambda *a, **k: ("pelea", True))
        try:
            tp._edit_all(i)
        finally:
            QInputDialog.getText = orig_get
        assert sum(1 for w in words if WF.core(w[2]) == "pelea") == 2 and not any(w[2] == "combate" for w in words)
        print("✓ «Cambiar en todo el texto»: las 2 «combate» → «pelea»")
        # lo que llega al volver a escuchar: un menú con lo que se oye
        j = next(k for k, w in enumerate(words) if WF.core(w[2]) == "lento")
        tp._show_alternatives(j, words[j][2], ["lentos", "lenta"], pos)
        assert shown[-1][1:3] == ["lentos", "lenta"], shown[-1]
        tp._add_vocab("Gears")
        assert "Gears" in WF.vocabulary()
    finally:
        help_ui.exec_menu = orig_exec
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("✓ lo que se oye sale en un menú para elegir; «tener en cuenta» guarda la palabra")


if __name__ == "__main__":
    test_basics()
    test_relisten()
    test_panel()
    print("TODO OK")
