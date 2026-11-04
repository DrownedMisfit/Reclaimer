"""
Prueba del ecualizador (pestaña Audio del panel Detalles): presets, arrastrar bandas,
copiar a todo el archivo, exportación y «Escuchar con EQ».
Ejecutar:  .venv/Scripts/python.exe tests/test_eq.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import equalizer as E  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def band_level(path: str, f: float) -> float:
    s = media_tools.decode_mono(path, 48000)
    n = 32768
    acc = 0
    for h in range(0, len(s) - n, n):
        acc = acc + np.abs(np.fft.rfft(s[h:h + n] * np.hanning(n))) ** 2
    freqs = np.fft.rfftfreq(n, 1 / 48000)
    sel = (freqs > f / 1.05) & (freqs < f * 1.05)
    return float(10 * np.log10(acc[sel].mean() + 1e-12))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    noise = os.path.join(out, "ruido_rosa.wav")
    media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "anoisesrc=color=pink:d=12:a=0.2", noise])
    (mid,) = ctrl.import_paths([noise])
    while ctrl.analyzing:
        pump(app, 0.1)
    a1 = [t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO][0]
    ctrl.set_track_props(a1.id, "sin efectos", fx={})
    cid = ctrl.add_media([mid], a1.id, 0.0)[0]
    ctrl.split(6.0, [cid])
    clips = ctrl.project.clips_on(a1.id)
    win.timeline.set_selection([clips[0].id])
    win.engine.seek(2.0)
    pump(app, 0.6)
    insp = win.inspector
    assert insp.clip_tabs.isTabVisible(2) and not insp.clip_tabs.isTabVisible(1), "audio: pestaña Audio sí, Video no"
    insp.clip_tabs.setCurrentIndex(2)
    # Preset y arrastrar la banda 3 (como con el ratón)
    insp._on_eq_preset(insp.eq_preset.findText("Voz clara"))
    n0 = ctrl.undo_stack.count()
    for g in (4.0, 6.0, 8.0):
        b = dict(ctrl.project.clips[clips[0].id].eq["bands"][2], g=g, f=3000.0)
        insp.eq_graph.band_changed.emit(2, b)
    assert ctrl.undo_stack.count() == n0 + 1, "arrastrar un punto = un solo paso de deshacer"
    eq = ctrl.project.clips[clips[0].id].eq
    assert eq["bands"][2]["g"] == 8.0 and eq["bands"][0]["type"] == "hp"
    pump(app, 0.8)
    assert insp.eq_graph.spectrum is not None, "se dibuja el espectro del audio"
    print("✓ preset «Voz clara» + arrastrar banda 3 a +8 dB en 3 kHz (un solo deshacer)")
    insp._eq_to_all()
    assert ctrl.project.clips[clips[1].id].eq == eq
    print("✓ copiado a todos los clips del mismo archivo")
    # Preset «Mi voz» (el de DaVinci Resolve del usuario) en un clip, para la captura
    insp._on_eq_preset(next(i for i in range(insp.eq_preset.count())
                            if insp.eq_preset.itemText(i) == "Mi voz"))
    mine = ctrl.project.clips[clips[0].id].eq
    assert [b["on"] for b in mine["bands"]] == [False, True, True, True, True, False]
    assert mine["bands"][2]["f"] == 242 and mine["bands"][2]["g"] == 4.2
    print("✓ preset «Mi voz» (6 bandas, como en DaVinci Resolve)")
    pump(app, 0.8)
    win.right_tabs.setCurrentWidget(insp)
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "ecualizador.png"))
    insp.eq_graph.grab().save(os.path.join(out, "grafica.png"))
    ctrl.undo_stack.undo()
    eq = ctrl.project.clips[clips[0].id].eq

    # Exportar solo audio y medir el efecto real
    plain = os.path.join(out, "sin_eq.wav")
    media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", noise, "-ar", "48000", plain])
    with_eq = os.path.join(out, "con_eq.wav")
    ctrl.set_settings(loudnorm=False)
    args, _ = build_command(ctrl.project, ExportOptions(path=with_eq, audio_only=True, loudnorm=False),
                            media_tools.ffmpeg(), os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1200:]
    for f in (50, 250, 3000):
        expected = float(E.response_db(eq, np.array([f]))[0])
        measured = band_level(with_eq, f) - band_level(plain, f)
        print(f"  {f:5d} Hz: esperado {expected:+.1f} dB · medido {measured:+.1f} dB")
        assert abs(measured - expected) < 1.5, (f, expected, measured)
    print("✓ la exportación aplica exactamente la curva que se ve")

    # «Escuchar con EQ»
    win.audio_monitor.start()
    t0 = time.time()
    while (win.audio_monitor.job is not None or win.audio_monitor.player.source().isEmpty()) and time.time() - t0 < 30:
        pump(app, 0.1)
    assert not win.audio_monitor.player.source().isEmpty()
    first = win.audio_monitor.player.source().toLocalFile()
    insp._on_band(1, dict(eq["bands"][1], g=-8.0))
    pump(app, 0.4)
    t0 = time.time()
    while win.audio_monitor.player.source().toLocalFile() == first and time.time() - t0 < 30:
        pump(app, 0.1)
    assert win.audio_monitor.player.source().toLocalFile() != first, "el bucle se actualiza al cambiar el EQ"
    win.audio_monitor.stop()
    print("✓ «Escuchar con EQ»: se prepara y se actualiza sola al cambiar una banda")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
