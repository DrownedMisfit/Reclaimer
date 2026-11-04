"""
Prueba de 🎯 «Respetar las palabras» y del ⚠ aviso de voz en «Eliminar silencio» (el usuario: «está cortando mis
palabras… hay que buscar la precisión del final y el inicio de las palabras; que sea una opción en el menú donde corto
los silencios»), con la voz de Windows (Sabina, es-MX) y ruido de fondo:
  · ⚠ predicción: con «Solo volumen» y un umbral alto (como Resolve) se marca en rojo la voz que se cortaría; con el
    modo seguro, nada;
  · con las palabras afinadas, NINGÚN modo híbrido corta dentro de una palabra (tampoco «Como Resolve», con el umbral
    alto: ahí sigue mandando en las pausas);
  · la ventana: la opción «🎯 Respetar las palabras», la línea de tiempo pinta el rojo y el texto avisa.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_silence_words.py <carpeta_salida>
"""
from __future__ import annotations

import os
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

import numpy as np  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import test_silence_voz as T
    from editoria.core import silence as S
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO
    frases = [T.read(p) for p in T.tts(out)]
    path = os.path.join(out, "voz.wav")
    clean = T.build(frases, -62, path, seed=11)
    # «palabras afinadas»: cada palabra repartida dentro de donde suena su frase (como deja el alineador)
    words, t = [], 0.8
    for f, pausa, text in zip(frases, T.PAUSAS, T.FRASES):
        nz = np.nonzero(np.abs(f) > 1e-4)[0]
        d = (nz[-1] + 1 - nz[0]) / T.SR
        ws = text.split()
        for i, w in enumerate(ws):
            words.append([round(t + i * d / len(ws), 3), round(t + (i + 1) * d / len(ws), 3), w, 1.0])
        t += d + pausa

    ctrl = ProjectController()
    (mid,) = ctrl.import_now([path])
    while ctrl.analyzing:
        app.processEvents()
    tr = next(t_ for t_ in ctrl.project.tracks if t_.kind == TRACK_AUDIO)
    ctrl.add_media([mid], tr.id, 0.0)
    p = ctrl.project
    clips = p.clips_on(tr.id)
    fps = p.fps

    def plan(**st):
        base = {"threshold_db": -20.0, "before": 0, "after": 1, "min_frames": 2, "mode": "hibrido", "clicks": False}
        base.update(st)
        return S.plan(p, clips, fps, base)

    def eaten(regs):
        return T.eaten_ms(regs, clean)               # (un solo clip desde 0: línea de tiempo = archivo)

    # 1) ⚠ predicción
    vol = plan(mode="volumen")
    hits = S.voice_hits(p, clips, vol)
    assert eaten(vol) > 300 and sum(b - a for a, b in hits) > 0.3, (eaten(vol), hits[:3])
    safe = plan(protect="max")
    assert eaten(safe) <= 7 and sum(b - a for a, b in S.voice_hits(p, clips, safe)) < 0.05
    print(f"✓ ⚠ predicción: «Solo volumen» a -20 dB se come {eaten(vol):.0f} ms de voz y se marca en rojo "
          f"({sum(b - a for a, b in hits):.1f} s); el modo seguro, nada")

    # 2) palabras afinadas: nada dentro de una palabra
    res_free = plan(protect="resolve")
    ctrl.set_transcript(mid, {"words": words, "aligned": True})
    res_lock = plan(protect="resolve")
    inw = np.zeros(len(clean), bool)
    for w in words:
        inw[int(w[0] * T.SR):int(w[1] * T.SR)] = True
    voice = np.abs(clean) > 10 ** (-60 / 20)

    def in_words(regs):
        return sum(int((voice & inw)[int(a * T.SR):int(b * T.SR)].sum()) for a, b in regs) / T.SR * 1000
    assert in_words(res_free) > 300, in_words(res_free)
    assert in_words(res_lock) <= 5, in_words(res_lock)
    assert sum(b - a for a, b in res_lock) > 0.5 * sum(b - a for a, b in safe)
    for prot in ("max", "media"):
        assert in_words(plan(protect=prot)) <= 5, prot
    no_lock = plan(protect="resolve", words=False)
    assert in_words(no_lock) > 300, "sin la opción, como antes"
    print(f"✓ con las palabras afinadas, «Como Resolve» a -20 dB ya no corta dentro de ninguna palabra "
          f"({in_words(res_free):.0f} → {in_words(res_lock):.0f} ms) y sigue quitando pausas "
          f"({sum(b - a for a, b in res_lock):.1f} s); sin la opción, como antes")

    # 3) la ventana
    from editoria.ui.main_window import MainWindow
    from editoria.ui.silence_dialog import SilenceDialog
    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    pump(app, 0.3)
    c2 = win.ctrl
    (m2,) = c2.import_now([path])
    while c2.analyzing:
        pump(app, 0.1)
    atr = next(t_ for t_ in c2.project.tracks if t_.kind == TRACK_AUDIO)
    c2.add_media([m2], atr.id, 0.0)
    c2.set_transcript(m2, {"words": words, "aligned": True})
    cid = c2.project.clips_on(atr.id)[0].id
    dlg = SilenceDialog(win, [cid])
    t0 = time.time()
    while not dlg._ready and time.time() - t0 < 60:
        pump(app, 0.1)
    assert hasattr(dlg, "words_cb") and "Respetar las palabras" in dlg.words_cb.text()
    dlg.mode.setCurrentIndex(dlg.mode.findData("volumen"))
    dlg.ctl["threshold_db"][1].setValue(-20.0)
    pump(app, 0.5)
    assert win.timeline.preview_voice and "Cortaría" in dlg.info.text(), dlg.info.text()
    dlg.mode.setCurrentIndex(dlg.mode.findData("hibrido"))
    dlg.protect.setCurrentIndex(dlg.protect.findData("max"))
    pump(app, 0.5)
    assert not win.timeline.preview_voice and "Sin tocar tu voz" in dlg.info.text(), dlg.info.text()
    print("✓ ventana: «🎯 Respetar las palabras»; el aviso «⚠ Cortaría X s de tu voz» y el rojo en la línea de "
          "tiempo aparecen con «Solo volumen» y se van con el modo seguro")
    dlg.reject()
    pump(app, 0.2)
    assert not win.timeline.preview_voice

    # 4) sin transcripción: la ventana transcribe (aquí simulado: Whisper, con sus tiempos movidos 0,3 s) y afina
    from editoria.ai import align as A, transcription as TR
    if A.available()[0]:
        TR.is_available = lambda: (True, "")
        TR.is_downloaded = lambda _k: True
        fake = [[w[0] + 0.3, w[1] + 0.3, w[2], 0.9] for w in words]
        dur = len(clean) / T.SR
        fake.append([dur + 0.5, dur + 1.0, "adiós", 0.5])   # (Whisper a veces se pasa del final: no debe romperse)
        TR.transcribe = lambda *_a, **_k: {"language": "es", "model": "simulado", "words": [list(w) for w in fake],
                                           "segments": [[0.0, 1.0, 0, len(fake)]]}
        import shutil
        path3 = os.path.join(out, "voz_sin_transcribir.wav")
        shutil.copyfile(path, path3)
        (m3,) = c2.import_now([path3])
        while c2.analyzing:
            pump(app, 0.1)
        c2.add_media([m3], atr.id, c2.project.duration() + 1.0)
        cid3 = next(c.id for c in c2.project.clips_on(atr.id) if c.media_id == m3)
        dlg = SilenceDialog(win, [cid3])
        dlg.show()
        assert dlg.words_cb.isEnabled() and dlg.words_cb.isChecked()
        t0 = time.time()
        while not dlg._ready and time.time() - t0 < 60:
            pump(app, 0.1)
        assert dlg._ready and dlg.b_ok.isEnabled(), "se puede eliminar YA, sin esperar a la transcripción"
        while not (c2.project.transcripts.get(m3) or {}).get("aligned") and time.time() - t0 < 240:
            pump(app, 0.2)
        trn = c2.project.transcripts.get(m3) or {}
        assert "afinadas" in dlg.info.text(), dlg.info.text()
        assert dlg._ready and trn.get("aligned") and trn.get("segments") and trn.get("language") == "es", (trn.keys(), dlg._ready, dlg.info.text())
        print(f"✓ sin transcripción: «Eliminar» al momento; mientras, transcribe y afina ({len(trn['words'])} palabras) "
              "en el panel de tareas, la guarda completa y la vista previa se pone al día sola")
        dlg.reject()
        pump(app, 0.2)
    c2.undo_stack.setClean()
    c2._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
