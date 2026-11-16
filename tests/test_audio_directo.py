"""
🎧 Audio en directo (sin ventanas y SIN QUE SUENE NADA: EDITORIA_SIN_SONIDO=1):
  · la mezcla saca el audio del archivo tal cual (también al cruzar un trozo de 8 s) y en su sitio de la línea de tiempo;
  · el volumen del clip se aplica; un clip silenciado (pista muda) no suena;
  · el ecualizador se oye: un corte de graves a 1 kHz quita un tono de 100 Hz y deja uno de 5 kHz;
  · cambiar el EQ mientras suena no da chasquidos (pasa del filtro viejo al nuevo con un fundido);
  · el EQ de la mezcla coincide con la curva que dibuja el Inspector (las mismas fórmulas que FFmpeg);
  · en el visor, con la mezcla encendida, las pistas de audio no usan su reproductor (suena la mezcla); con J/L a 2×,
    vuelven los reproductores.
Ejecutar:  .venv/Scripts/python.exe tests/test_audio_directo.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import wave

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMP = tempfile.mkdtemp(prefix="reclaimer_audio_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402

from editoria.core import equalizer as E  # noqa: E402
from editoria.core import live_mix as LM  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402

SR = LM.SR


def wav(ruta, x):
    x = np.clip(x, -1, 1)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def esperar(dec, ruta, t, n):
    for _ in range(400):
        x = dec.get(ruta, t, n)
        if x is not None:
            return x
        time.sleep(0.01)
    raise AssertionError("no se decodificó")


def banda(x, f):
    spec = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x))))
    k = int(round(f * len(x) / SR))
    return float(spec[k - 2:k + 3].max())


def main():
    t = np.arange(int(SR * 10)) / SR
    rampa = (t * 0.05).astype(np.float32)               # (sube despacio: se ve si un trozo se descoloca)
    ruta_r = os.path.join(_TMP, "rampa.wav")
    wav(ruta_r, np.stack([rampa, rampa], 1))
    dec = LM.Decoder()
    x = esperar(dec, ruta_r, 7.9, int(SR * 0.3))        # cruza de un trozo de 8 s al siguiente
    s0 = int(round(7.9 * SR))
    ref = rampa[s0:s0 + len(x)]
    assert np.max(np.abs(x[:, 0] - ref)) < 1e-3, np.max(np.abs(x[:, 0] - ref))
    print("✓ la mezcla lee el archivo tal cual, también al cruzar de un trozo de 8 s al siguiente")

    tonos = 0.4 * np.sin(2 * np.pi * 100 * t) + 0.4 * np.sin(2 * np.pi * 5000 * t)
    ruta_t = os.path.join(_TMP, "tonos.wav")
    wav(ruta_t, np.stack([tonos, tonos], 1).astype(np.float32))
    clip = Clip("c1", "m1", "a1", 2.0, 1.0, 5.0, volume=0.5)
    mx = LM.Mixer(dec)
    mx.plan = LM.Plan(sources=[LM.Source("c1", ruta_t, 2.0, 7.0, 1.0, clip)])
    esperar(dec, ruta_t, 1.0, SR)
    esperar(dec, ruta_t, 3.0, SR)
    bloque = mx.render(1.99, 1024)                       # el clip empieza a mitad del bloque
    k0 = int(round(0.01 * SR))
    assert np.max(np.abs(bloque[:k0 - 1])) == 0 and np.max(np.abs(bloque[k0 + 1:])) > 0.05
    trozo = np.concatenate([mx.render(3.0 + i * 1024 / SR, 1024) for i in range(16)])
    orig = 0.5 * tonos[int(2.0 * SR):int(2.0 * SR) + len(trozo)]
    assert np.max(np.abs(trozo[:, 0] - orig)) < 2e-3, np.max(np.abs(trozo[:, 0] - orig))
    print("✓ cada clip suena en su sitio (empieza en la muestra justa) y con su volumen (×0,5)")

    mx.plan = LM.Plan(sources=[LM.Source("c1", ruta_t, 2.0, 7.0, 1.0, clip, audible=False)])
    assert np.max(np.abs(mx.render(3.0, 1024))) == 0
    print("✓ pista muda o en solo de otra: no suena")

    hp = {"on": True, "bands": [{"on": True, "type": "hp", "f": 1000.0, "g": 0.0, "q": 0.7}]}
    limpio = trozo
    mx = LM.Mixer(dec)
    mx.plan = LM.Plan(sources=[LM.Source("c1", ruta_t, 2.0, 7.0, 1.0, clip, eq=hp)])
    eqd = np.concatenate([mx.render(3.0 + i * 1024 / SR, 1024) for i in range(16)])[4096:]
    limpio = limpio[4096:]
    r100 = banda(eqd, 100) / banda(limpio, 100)
    r5k = banda(eqd, 5000) / banda(limpio, 5000)
    assert r100 < 0.05 and 0.9 < r5k < 1.1, (r100, r5k)
    print(f"✓ el ecualizador se oye: corte de graves a 1 kHz → 100 Hz ×{r100:.3f}, 5 kHz ×{r5k:.2f}")

    freqs = np.array([60.0, 250.0, 1000.0, 4000.0, 12000.0])
    eq = {"on": True, "bands": E.PRESETS["Voz clara"]}
    ir = LM.eq_fir(eq)
    H = np.abs(np.fft.rfft(ir, 1 << 16))
    got = 20 * np.log10(H[(freqs * (1 << 16) / SR).round().astype(int)] + 1e-12)
    want = E.response_db(eq, freqs)
    assert np.max(np.abs(got - want)) < 0.5, (got, want)
    print("✓ lo que se oye coincide con la curva del Inspector (±0,5 dB; mismas fórmulas que FFmpeg al exportar)")

    mx = LM.Mixer(dec)
    src = LM.Source("c1", ruta_t, 2.0, 7.0, 1.0, clip, eq=None)
    mx.plan = LM.Plan(sources=[src])
    partes = []
    for i in range(24):
        if i == 12:                                       # sube +12 dB los graves mientras suena
            mx.plan = LM.Plan(sources=[LM.Source("c1", ruta_t, 2.0, 7.0, 1.0, clip, eq={"on": True, "bands": [
                {"on": True, "type": "lowshelf", "f": 300.0, "g": 12.0, "q": 0.7}]})])
        partes.append(mx.render(3.0 + i * 1024 / SR, 1024))
    y = np.concatenate(partes)[:, 0]
    salto = np.max(np.abs(np.diff(y)))
    normal = np.max(np.abs(np.diff(y[:12 * 1024])))
    assert salto < normal * 3.5, (salto, normal)
    print(f"✓ cambiar el EQ mientras suena no da chasquidos (salto máx. {salto:.3f} frente a {normal:.3f} sin cambio)")

    # ---------------------------------------------------------------- en el visor
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    eng = win.engine
    assert eng.live is not None and eng.live.ok, "la mezcla en directo se abre (sin tarjeta en las pruebas)"
    p = Project.new()
    a1 = next(tr for tr in p.tracks if tr.kind == "audio")
    p.media["m1"] = MediaItem(id="m1", path=ruta_t, kind=KIND_AUDIO, name="tonos.wav", duration=10.0, probed=True,
                              has_audio=True)
    p.clips["c1"] = Clip("c1", "m1", a1.id, 0.0, 0.0, 8.0)
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    eng._refresh()
    assert "c1" in eng._live_ids
    eng.play()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    lane = eng._audio.get(a1.id)
    from PySide6.QtMultimedia import QMediaPlayer
    assert lane is None or lane.player.playbackState() != QMediaPlayer.PlayingState, "suena la mezcla, no el reproductor"
    assert eng.live.playing and eng.live.position() is not None
    print("✓ en el visor, la pista de audio suena por la mezcla en directo (su reproductor queda quieto)")
    win.ctrl.set_clip_audio(["c1"], "EQ", eq={"on": True, "bands": [
        {"on": True, "type": "bell", "f": 400.0, "g": 6.0, "q": 1.0}]})
    app.processEvents()
    assert eng.live.mixer.plan.sources[0].eq["bands"][0]["g"] == 6.0
    print("✓ mover el EQ en el Inspector llega a la mezcla al momento (sin parar)")
    eng.jkl("l")
    app.processEvents()
    assert eng.rate == 2.0 and not eng.live.playing and not eng._live_on()
    print("✓ con L a 2× vuelven los reproductores de siempre (la mezcla se aparta)")
    eng.pause()
    win.a_live_audio.setChecked(False)
    assert not eng._live_on()
    win.a_live_audio.setChecked(True)
    assert eng._live_on()
    print("✓ Reproducción → «🎧 Audio en directo» la apaga y la enciende")
    win.ctrl.undo_stack.setClean()
    win.close()
    eng.live.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
