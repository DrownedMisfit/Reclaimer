"""
📝 Transcripción por bloques (sin ventanas; modelo de voz FALSO, no se descarga nada):
  · un audio de 10 min entrega lo hecho cada 3 min de audio (3:00, 6:00, 9:00), en orden desde el segundo 0, y al
    final la transcripción entera (sin «hasta»);
  · si se corta a medias, lo entregado se queda (con «hasta») y se puede seguir desde ahí sin repetir lo hecho;
  · panel 🎙 Voz: cada bloque llega al proyecto mientras sigue; a medias el botón dice «Seguir transcribiendo»;
  · los bloques no se afinan con la IA ni quitan los resaltados de los subtítulos.
Ejecutar:  .venv/Scripts/python.exe tests/test_transcribe_blocks.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_bloques_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402

from editoria.ai import align, transcription  # noqa: E402
from editoria.ai.base import Cancelled  # noqa: E402

SR = transcription.SAMPLE_RATE
LLAMADAS = []


class ModeloFalso:
    """Una frase cada 10 s del audio que le pasan (dice su segundo, para comprobar los tiempos)."""
    corta_en = None          # segundo del audio total en que «se corta» (para probar seguir)

    def transcribe(self, audio, **_k):
        dur = len(audio) / SR
        LLAMADAS.append(dur)

        def gen():
            t = 0.0
            while t + 10 <= dur + 1e-6:
                ws = [SimpleNamespace(word=f" p{int(t)}", start=t + 1, end=t + 2, probability=0.9),
                      SimpleNamespace(word=" hola", start=t + 3, end=t + 4, probability=0.9)]
                yield SimpleNamespace(start=t, end=t + 10, words=ws)
                t += 10
        return gen(), SimpleNamespace(language="es")


transcription._load = lambda name: ModeloFalso()
transcription.is_downloaded = lambda k: True
import faster_whisper  # noqa: E402


class _Lotes:
    def __init__(self, model):
        self.transcribe = model.transcribe


faster_whisper.BatchedInferencePipeline = _Lotes
transcription.fill_holes = lambda samples, tr, model, language="es", cancelled=None: tr


def main():
    samples = np.zeros(600 * SR, np.float32)          # 10 min
    bloques = []
    tr = transcription.transcribe(samples, partial=bloques.append, fillers=False)
    assert [b["hasta"] for b in bloques] == [180.0, 360.0, 540.0], [b["hasta"] for b in bloques]
    assert all(b["words"][0][2] == "p0" for b in bloques), "cada bloque empieza en el segundo 0"
    assert len(bloques[0]["words"]) == 36 and len(tr["words"]) == 120 and "hasta" not in tr
    assert not align.needs(bloques[0]) and align.needs(tr)
    print("✓ 10 min: bloques a las 3:00, 6:00 y 9:00 (desde el segundo 0); al final, entera y sin «hasta»")

    # se corta a los 5 min (después del primer bloque): lo entregado se queda y se sigue desde ahí
    bloques = []
    n = {"seg": 0}

    def cancelado():
        n["seg"] += 1
        return n["seg"] > 30                               # 30 frases de 10 s = 5 min
    try:
        transcription.transcribe(samples, partial=bloques.append, cancelled=cancelado, fillers=False)
        raise AssertionError("no se cortó")
    except Cancelled:
        pass
    medio = bloques[-1]
    assert medio["hasta"] == 180.0, medio["hasta"]
    LLAMADAS.clear()
    fin = transcription.transcribe(samples, partial=None, start_at=medio["hasta"], prev=medio, fillers=False)
    assert abs(LLAMADAS[0] - 420.0) < 1e-6, f"solo escucha lo que falta: {LLAMADAS[0]} s"
    inicios = [w[0] for w in fin["words"] if w[2] != "hola"]
    assert inicios == [t + 1.0 for t in range(0, 600, 10)], inicios[:20]
    assert fin["words"][36][0] == 181.0, fin["words"][36]
    assert [s[2] for s in fin["segments"]] == list(range(0, 120, 2))
    print("✓ cortada a los 5 min: queda hasta 3:00 y al seguir solo escucha los 7 min que faltan (tiempos bien)")

    # ---- panel 🎙 Voz
    from PySide6.QtWidgets import QApplication, QMessageBox
    from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.Yes)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    wav = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
    p = Project.new()
    p.media["nar"] = MediaItem(id="nar", path=wav, kind=KIND_AUDIO, name="nar.wav", duration=600.0, probed=True)
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=p.tracks[-1].id, start=0.0, source_in=0.0, duration=60)
    win.ctrl.project = p
    voice = win.voice
    voice.media_id = lambda: "nar"
    voice.audio.get = lambda path: samples
    vistos = []
    win.ctrl.transcript_changed.connect(lambda m: vistos.append((win.ctrl.project.transcripts[m].get("hasta"),
                                                                 len(win.ctrl.project.transcripts[m]["words"]))))
    from editoria.ai import voice_cleanup
    voice_cleanup.refine_transcript = lambda s, sr, t: t
    voice.transcribe(analyze=False)
    t0 = time.time()
    while voice.job is not None and time.time() - t0 < 30:
        app.processEvents()
        time.sleep(0.01)
    assert voice.job is None
    assert [v[0] for v in vistos] == [180.0, 360.0, 540.0, None], vistos
    assert "hasta" not in win.ctrl.project.transcripts["nar"]
    print(f"✓ panel 🎙 Voz: el proyecto recibe cada bloque mientras sigue ({vistos})")

    win.ctrl.project.transcripts["nar"] = dict(medio)
    voice._update_state()
    assert voice.btn_transcribe.text() == "🎙 Seguir transcribiendo", voice.btn_transcribe.text()
    assert "hasta 03:00" in voice.status.text() or "hasta 3:00" in voice.status.text(), voice.status.text()
    win.ctrl.project.subtitles.media_id = "nar"
    win.ctrl.project.subtitles.emphasis = [3]
    sig = dict(medio, words=medio["words"] + [[200.0, 201.0, "más", 0.9]], hasta=360.0)
    win.ctrl.set_transcript("nar", sig)
    assert win.ctrl.project.subtitles.emphasis == [3], "el bloque siguiente no quita los resaltados"
    print("✓ a medias: «🎙 Seguir transcribiendo» y el estado lo dice; el bloque siguiente no quita los resaltados")
    antes = [w[2] for w in win.ctrl.project.transcripts["nar"]["words"]]
    pasos = win.ctrl.undo_stack.count()
    assert win.ctrl.edit_words("nar", [0], "corregido") is None
    assert [w[2] for w in win.ctrl.project.transcripts["nar"]["words"]] == antes
    assert win.ctrl.undo_stack.count() == pasos
    print("✓ a medias no se corrige el texto (el bloque siguiente lo pisaría): avisa y no deja paso de deshacer")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
