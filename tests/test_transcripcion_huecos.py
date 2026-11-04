"""
Prueba de la transcripción sin huecos (3/11/2026: en un Short de 82 s Whisper se quedó escribiendo «... ... ...» y se
saltó 21 s: los subtítulos desaparecían a partir del minuto):
  · se detectan los tramos con voz que se quedaron sin palabras (y no los silencios de verdad);
  · fill_holes los vuelve a escuchar y mete lo que se dice en su sitio (con Whisper de verdad, si está descargado);
  · «⚡ Subtítulos para Short» transcribe SIN buscar errores al hablar (bostezos, titubeos, respiraciones…) y en el
    modo rápido (fillers=False); «Transcribir y analizar» sí los busca.
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_transcripcion_huecos.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(ROOT, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(ROOT, "datos", "modelos"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import transcription as T  # noqa: E402
from editoria.core import media as M  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NARRATION = os.path.join(ASSETS, "narracion_prueba.wav")
CACHE = os.path.join(ASSETS, "narracion_prueba.transcripcion.json")


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def test_holes():
    a = M.decode_mono(NARRATION, 16000)
    tr = json.load(open(CACHE, encoding="utf-8"))
    words = tr["words"]
    assert T.holes(a, words) == [], T.holes(a, words)          # completa: ningún hueco (sus pausas no cuentan)
    cut = [w for w in words if not 7.5 < w[0] < 16.5]           # «se salta» unos 9 s de voz
    h = T.holes(a, cut)
    assert len(h) == 1 and h[0][0] < 8.5 and h[0][1] > 15.5, h
    silent = np.zeros(16000 * 10, np.float32)                   # un silencio de verdad no es un hueco
    silent[:16000] = 0.2 * np.sin(np.arange(16000) / 5)
    assert T.holes(silent, [[0.0, 1.0, "hola", 0.9]]) == []
    print(f"✓ huecos: completa = ninguno; quitando 9 s de voz = {h}; un silencio de verdad no cuenta")
    if not T.is_downloaded("equilibrado"):
        print("· (sin el modelo descargado no se prueba la nueva escucha)")
        return
    model = T._load(T.MODELS["equilibrado"][0])
    fixed = T.fill_holes(a, dict(tr, words=cut), model, "es")
    back = [w for w in fixed["words"] if 7.5 < w[0] < 16.5]
    lost = [w for w in words if 7.5 < w[0] < 16.5]
    assert len(back) >= 0.7 * len(lost) and fixed.get("filled"), (len(back), len(lost), fixed.get("filled"))
    assert [w[0] for w in fixed["words"]] == sorted(w[0] for w in fixed["words"])
    assert sum(b - a_ for _s, _e, a_, b in fixed["segments"]) == len(fixed["words"])
    print(f"✓ se vuelve a escuchar: {len(back)} de {len(lost)} palabras de vuelta en su sitio: "
          + " ".join(w[2] for w in back))


def test_subtitles_no_analysis():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import voice_cleanup
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    (mid,) = ctrl.import_now([NARRATION])
    while ctrl.analyzing:
        pump(app, 0.1)
    win.voice.refresh() if hasattr(win.voice, "refresh") else None
    pump(app, 0.3)
    tr = json.load(open(CACHE, encoding="utf-8"))
    calls = {"fillers": [], "analyze": 0}
    orig_t, orig_a = T.transcribe, voice_cleanup.analyze

    def fake_transcribe(samples, model, lang, progress=None, cancelled=None, fillers=True):
        calls["fillers"].append(fillers)
        return json.loads(json.dumps(tr))

    def fake_analyze(*a, **k):
        calls["analyze"] += 1
        return orig_a(*a, **k)
    T.transcribe = fake_transcribe
    voice_cleanup.analyze = fake_analyze
    try:
        win.subtitles.quick_short()                             # ⚡ Subtítulos para Short
        t0 = time.time()
        while (mid not in ctrl.project.transcripts or win.voice.job) and time.time() - t0 < 60:
            pump(app, 0.1)
        pump(app, 0.3)
        st = ctrl.project.subtitles
        assert mid in ctrl.project.transcripts and st.enabled and st.media_id == mid, st
        assert calls == {"fillers": [False], "analyze": 0}, calls
        assert not [s for s in ctrl.project.suggestions if s.media_id == mid], "sin sugerencias de errores"
        print("✓ «⚡ Subtítulos para Short»: transcribe en el modo rápido, pone los subtítulos y NO busca errores al "
              "hablar (ninguna sugerencia)")
        from PySide6.QtWidgets import QMessageBox
        old_q = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        try:
            win.voice.transcribe()                              # «Transcribir y analizar»: sí analiza
        finally:
            QMessageBox.question = old_q
        t0 = time.time()
        while win.voice.job and time.time() - t0 < 60:
            pump(app, 0.1)
        pump(app, 0.3)
        assert calls["fillers"] == [False, True] and calls["analyze"] == 1, calls
        print("✓ «Transcribir y analizar» (Limpieza) sí busca los errores, con las muletillas")
    finally:
        T.transcribe, voice_cleanup.analyze = orig_t, orig_a
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)


if __name__ == "__main__":
    test_holes()
    test_subtitles_no_analysis()
    print("TODO OK")
