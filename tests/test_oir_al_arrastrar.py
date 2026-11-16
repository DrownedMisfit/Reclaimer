"""
Prueba de 🔊 «oír al arrastrar la barra roja» (PlaybackEngine.scrub) y de que «✂ Eliminar silencio» no bloquea la
línea de tiempo y empieza con lo básico. Sin ventanas visibles y SIN sonido (en pruebas la tarjeta no suena: se
comprueba que la mezcla en directo arranca y se para).
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_oir_al_arrastrar.py [carpeta_temporal]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = sys.argv[1] if len(sys.argv) > 1 else None
if _BASE:
    os.makedirs(_BASE, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="oir_", dir=_BASE)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "datos")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO  # noqa: E402


def pump(app, s=0.2):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    pump(app, 0.4)
    ctrl = win.ctrl
    wav = os.path.join(_TMP, "voz.wav")             # tono con pausas: «habla» y «calla»
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=f=300:d=8", "-af", "volume='if(lt(mod(t,2),1.2),1,0)':eval=frame", wav],
                   check=True, creationflags=media_tools.NO_WINDOW)
    (mid,) = ctrl.import_now([wav])
    while ctrl.analyzing:
        pump(app, 0.05)
    a1 = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    ids = ctrl.add_media([mid], a1.id, 0.0)
    assert ids
    pump(app, 0.3)
    eng = win.engine
    assert eng.live is not None, "sin la mezcla en directo no hay nada que oír"

    # 🔊 arrastrar la barra roja (en pausa): suena un trocito y se calla solo
    eng.live.prepare(2.0)
    t0 = time.time()
    while not eng.live.mixer.ready_at(2.0) and time.time() - t0 < 5:
        pump(app, 0.05)
    eng._scrub_ult = 0.0
    win.timeline.scrub_requested.emit(2.0)
    assert eng.live.playing, "al arrastrar no arrancó el sonido"
    pump(app, 0.35)
    assert not eng.live.playing, "el trocito no se calló solo"
    # muchos movimientos seguidos: no se amontonan (como mucho uno cada 70 ms) y al final se calla
    for k in range(20):
        win.timeline.scrub_requested.emit(2.0 + k * 0.01)
    pump(app, 0.5)
    assert not eng.live.playing
    # reproduciendo, arrastrar no mete trocitos encima
    eng.play()
    pump(app, 0.2)
    win.timeline.scrub_requested.emit(3.0)
    assert eng.playing
    eng.pause()
    # se puede apagar
    QSettings("EditorIA", "EditorIA").setValue("reproduccion/oir_al_arrastrar", "false")
    eng._scrub_ult = 0.0
    win.timeline.scrub_requested.emit(2.0)
    assert not eng.live.playing
    QSettings("EditorIA", "EditorIA").remove("reproduccion/oir_al_arrastrar")
    print("✓ al arrastrar la barra roja suena un trocito (y se calla); reproduciendo o apagado, no")

    # ✂ Eliminar silencio: la ventana NO bloquea y empieza con lo básico
    qs = QSettings("EditorIA", "EditorIA")
    for k in ("silencio/ultimo", "silencio/basico_v1", "silencio/hibrido_visto", "silencio/davinci_visto",
              "silencio/palabras", "silencio/mas_opciones"):
        qs.remove(k)
    win.timeline.set_selection(ids)
    win.open_silence()
    pump(app, 0.5)
    dlg = win._silence_dialog
    assert dlg is not None and dlg.isVisible() and not dlg.isModal(), "la ventana bloquea la línea de tiempo"
    assert dlg.mode.currentData() == "volumen", dlg.mode.currentData()
    assert not any(cb.isChecked() for cb in (dlg.clicks, dlg.voice_model, dlg.words_cb, dlg.learn_cb)), \
        "hay funciones extra activadas de entrada"
    assert not dlg.more_btn.isChecked(), "«Más opciones» desplegado de entrada"
    t0 = time.time()
    while not dlg.regions and time.time() - t0 < 10:
        pump(app, 0.1)
    assert dlg.regions, "no encontró los silencios del tono"
    # con la ventana abierta: mover el cabezal funciona y «Escuchar sin silencios» reproduce saltándolos
    win.timeline.seek_requested.emit(1.0)
    pump(app, 0.1)
    assert abs(eng.time - 1.0) < 0.05
    dlg._escuchar()
    pump(app, 0.2)
    assert eng.playing and eng._ranges is not None
    eng.pause()
    # alguien que ya lo usaba: sus extras se apagan UNA vez y sus números se quedan
    dlg.close()
    pump(app, 0.2)
    qs.setValue("silencio/ultimo", json.dumps({"threshold_db": -40.0, "before": 3, "after": 5, "min_frames": 9,
                                               "mode": "hibrido", "protect": "davinci", "clicks": True,
                                               "voice_model": True, "words": True}))
    qs.remove("silencio/basico_v1")
    win.open_silence()
    pump(app, 0.4)
    dlg = win._silence_dialog
    assert dlg.ctl["threshold_db"][1].value() == -40.0 and dlg.mode.currentData() == "hibrido"
    assert not dlg.clicks.isChecked()
    dlg.close()
    pump(app, 0.2)
    print("✓ eliminar silencio: no bloquea, básico de entrada, escuchar cómo queda; lo de antes, sin extras")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
