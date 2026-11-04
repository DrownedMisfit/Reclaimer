"""
Prueba de 🎙 voz en off, 📑 capítulos para YouTube y 📸 exportar fotograma:
  · capítulos: reglas de YouTube (0:00, mínimo 3, 10 s o más, horas en videos largos) y nombres editables
    que se guardan en los marcadores (Ctrl+Z);
  · voz en off: SIN tocar tu micrófono (se simula el sonido que entra): la toma se guarda en WAV, cae en la
    pista de voz en el cabezal, no tapa nada, Ctrl+Z la quita; al parar el video, la toma se para;
  · fotograma: PNG a la resolución del proyecto, con lo que se ve (efectos y textos), y copiado al portapapeles.
Ejecutar:  .venv/Scripts/python.exe tests/test_voice_chapters_still.py <carpeta_salida>
"""
from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave

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

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

VOZ_KEYS = ("voz/microfono", "voz/reproducir", "voz/silenciar", "voz/cuenta")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def sine(seconds: float, rate: int = 48000) -> bytes:
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * i / rate))) for i in range(n))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in VOZ_KEYS}          # tus ajustes de la voz en off quedan como estaban
    app = QApplication(sys.argv)
    try:
        run(app, out)
    finally:
        for k, v in keep.items():
            st.remove(k) if v is None else st.setValue(k, v)


def run(app, out):
    from editoria.core import chapters as CH
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui import voice_record as VRUI
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # ---------------------------------------------------------------- capítulos (reglas)
    txt, warn = CH.build([(65, "Jugabilidad"), (200, "Historia"), (204, "Muy pegado"), (400, "Veredicto")], 600)
    assert txt.splitlines() == ["0:00 Intro", "1:05 Jugabilidad", "3:20 Historia", "6:40 Veredicto"], txt
    assert any("Intro" in w for w in warn) and any("Muy pegado" in w for w in warn)
    txt, warn = CH.build([(5, "Gráficos"), (30, "Jugabilidad"), (62, "Veredicto")], 90)
    assert txt.splitlines()[0] == "0:00 Gráficos", txt     # tu primer capítulo pasa a 0:00 (no se pierde)
    txt, warn = CH.build([(0, "Inicio"), (30, "Uno")], 100)
    assert any("al menos 3" in w for w in warn)
    txt, _ = CH.build([(0, "A"), (1800, "B"), (3725, "C")], 6529)
    assert txt.splitlines() == ["0:00:00 A", "0:30:00 B", "1:02:05 C"], txt
    print("✓ capítulos con las reglas de YouTube (0:00, ≥3, ≥10 s, horas en videos largos)")

    vid = os.path.join(out, "rojo.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:d=40:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=40", "-shortest", "-pix_fmt", "yuv420p", vid], check=True)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    p = ctrl.project
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([mid], v1.id, 0.0)
    ctrl.save(os.path.join(out, "Mi critica.eia"))             # tomas y fotogramas, junto al proyecto (carpeta de prueba)
    for t, name in ((0.0, "Intro"), (15.0, "Marcador 2"), (30.0, "Veredicto")):
        ctrl.add_marker(t, name)
    ctrl.add_markers([20.0], "Corte de escena")               # los que pone Reclaimer solo no cuentan
    from editoria.ui.chapters_dialog import ChaptersDialog
    dlg = ChaptersDialog(win)
    assert dlg.table.rowCount() == 3, dlg.table.rowCount()
    dlg.table.item(1, 1).setText("Jugabilidad")
    assert any(m.label == "Jugabilidad" for m in p.markers), "el nombre nuevo se guarda en su marcador"
    assert "0:15 Jugabilidad" in dlg.text.toPlainText(), dlg.text.toPlainText()
    dlg.copy()
    assert QApplication.clipboard().text() == dlg.text.toPlainText()
    ctrl.undo_stack.undo()
    assert not any(m.label == "Jugabilidad" for m in p.markers)
    dlg.close()
    print("✓ «Capítulos para YouTube»: desde los marcadores, nombres editables (Ctrl+Z) y 📋 copiar")

    # ---------------------------------------------------------------- voz en off (sin micrófono de verdad)
    class _NoMic:
        @staticmethod
        def audioInputs():
            return []

        @staticmethod
        def defaultAudioInput():
            return None
    VRUI.QMediaDevices = _NoMic
    from PySide6.QtMultimedia import QAudioFormat
    rec = VRUI.VoiceRecordDialog(win)
    assert not rec.b_rec.isEnabled() and "micrófono" in rec.status.text()
    fmt = QAudioFormat()
    fmt.setSampleRate(48000)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.Int16)
    rec.fmt = fmt
    rec.c_count.setChecked(False)
    rec.c_play.setChecked(False)
    win.engine.seek(1.0)
    n_clips = len(p.clips)
    rec.start()
    assert rec.recording
    rec.feed(sine(2.0))
    assert rec.meter.value() > 20
    rec.stop()
    pump(app, 0.3)
    takes = [c for c in p.clips.values() if p.media_of(c) and p.media_of(c).category == "Voz en off"]
    assert len(p.clips) == n_clips + 1 and len(takes) == 1, (len(p.clips), n_clips)
    take = takes[0]
    assert p.track(take.track_id).kind == TRACK_AUDIO and abs(take.start - 1.0) < 0.05 and abs(take.duration - 2.0) < 0.1
    path = p.media_of(take).path
    with wave.open(path) as w:
        assert w.getframerate() == 48000 and abs(w.getnframes() / 48000 - 2.0) < 0.01
    assert os.path.basename(os.path.dirname(path)) == "Grabaciones de voz"
    linked_audio = [c for c in p.clips.values() if p.track(c.track_id).kind == TRACK_AUDIO and c.media_id == mid]
    assert all(c.track_id != take.track_id or c.end <= take.start or c.start >= take.end for c in linked_audio), \
        "la toma no tapa el audio que ya había"
    print(f"✓ voz en off: toma WAV de 2 s en {take.start:.1f} s, en una pista de audio sin tapar nada "
          f"(«{os.path.basename(path)}»)")
    ctrl.undo_stack.undo()
    assert take.id not in p.clips and os.path.exists(path), "Ctrl+Z la quita de la línea de tiempo (el archivo queda)"
    print("✓ Ctrl+Z quita la toma de la línea de tiempo; el WAV se conserva")

    rec.c_play.setChecked(True)
    rec.c_mute.setChecked(True)
    win.engine.seek(0.5)
    rec.start()
    pump(app, 0.2)
    assert rec.recording and win.engine.playing and win.engine.mute_all, "graba viendo el video, en silencio"
    rec.feed(sine(1.0))
    win.engine.pause()                                        # Espacio en la ventana principal
    pump(app, 0.3)
    assert not rec.recording and not win.engine.mute_all, "al parar el video, la toma se para y vuelve el sonido"
    rec.close()
    print("✓ grabando: el video se reproduce, el proyecto en silencio; al pararlo, la toma termina")

    # ---------------------------------------------------------------- fotograma
    ctrl.add_text(3.0, 2.0, "HOLA")
    win.engine.seek(3.2)
    assert os.path.normcase(os.path.dirname(win.default_export_path())) == os.path.normcase(out)
    before = set(os.listdir(out))
    win.export_frame()
    from editoria.ui.task_window import manager
    t0 = time.time()
    while manager().tasks and time.time() - t0 < 120:
        pump(app, 0.2)
    pump(app, 0.3)
    folder = os.path.dirname(win.default_export_path())
    new = [f for f in set(os.listdir(folder)) - before if f.endswith(".png")]
    assert new, win.statusBar().currentMessage()
    png = os.path.join(folder, new[0])
    from PySide6.QtGui import QImage
    img = QImage(png)
    assert (img.width(), img.height()) == (p.width, p.height), (img.width(), img.height())
    c = img.pixelColor(20, 20)
    assert c.red() > 180 and c.green() < 80, c.name()
    small = img.scaled(192, 108)
    light = sum(1 for x in range(192) for y in range(108) if small.pixelColor(x, y).green() > 180)
    assert light > 15, f"el texto «HOLA» (que está en pantalla en ese instante) tiene que salir: {light}"
    assert not QApplication.clipboard().image().isNull(), "copiado al portapapeles"
    print(f"✓ 📸 fotograma: PNG {img.width()}×{img.height()} con lo que se ve, y copiado al portapapeles ({new[0]})")
    os.remove(png)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)          # como hace Reclaimer al salir (miniaturas de la toma recién importada, etc.)
    print("TODO OK")


if __name__ == "__main__":
    main()
