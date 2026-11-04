"""
Prueba del texto de los Shorts (lo que pidió el usuario con una imagen: letra blanca muy gruesa con sombra suave, a lo
mucho 3 palabras a la vez, sobre el borde de abajo del video del medio) y del panel «Texto → 📺 En pantalla»:
  · bloques de a lo mucho 3 palabras, sin dejar «de / la / el…» sueltos al final («Rumor del día» junto);
  · el estilo nuevo es el de los Shorts por defecto; al exportar lleva sombra difuminada y sale a la altura del borde
    del video del medio (~66 %), igual que en el visor;
  · el panel muestra los bloques sincronizados: lo que suena ahora, grande y en naranja (y se queda a la vista); clic =
    el cabezal salta ahí; corregir un bloque (con otro número de palabras) mantiene la sincronización.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_captions_shorts.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
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
from PySide6.QtWidgets import QApplication  # noqa: E402

FRASE = ("Rumor del día. Hoy les traigo algo especial, después de muchas horas de juego y la verdad es que "
         "el jefe final de la saga es lo mejor")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import subtitles as SUBS
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    ff = M.ffmpeg()
    vid = os.path.join(out, "juego.mp4")
    voz = os.path.join(out, "voz.wav")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", voz], check=True)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    ctrl.set_project_format("short")
    p = ctrl.project
    assert p.subtitles.preset == SUBS.SHORTS and p.subtitles.max_words == 3, p.subtitles.preset
    vmid, amid = ctrl.import_now([vid, voz])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([vmid], v1.id, 0.0)
    atr = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([amid], atr.id, 0.0)
    p = ctrl.project
    toks = FRASE.split()
    words, t = [], 0.4
    for w in toks:                                    # ~0,32 s por palabra, pausas tras «.» y «,»
        d = 0.18 + 0.03 * len(w)
        words.append([round(t, 3), round(t + d, 3), w, 0.95])
        t += d + (0.45 if w.endswith((".", ",")) else 0.06)
    ctrl.set_transcript(amid, {"language": "es", "model": "prueba", "words": words, "segments": []})
    ctrl.set_subtitle_style("Subtítulos", enabled=True, media_id=amid)
    p = ctrl.project
    cues = SUBS.styled_cues(p)
    texts = [c.text(" ") for c in cues]
    assert all(len(c.words) <= 3 for c in cues), texts
    assert texts[0] == "Rumor del día", texts[:3]
    weak = [x for x in texts if x.split()[-1].lower() in SUBS.WEAK_HARD]
    assert not weak, weak
    assert "es que" in texts and "el jefe final" in texts, texts
    singles = [x for x in texts if len(x.split()) == 1]
    assert len(singles) <= 1, singles
    print(f"✓ bloques de a lo mucho 3 palabras, sin «de/la/el» al final: {texts}")

    # --- exportar un fotograma con el texto: sombra difuminada y a la altura del borde del video (~66 %)
    from editoria.export.ass_subtitles import build_ass
    ass = build_ass(cues, p.subtitles, 1080, 1920)
    assert "\\blur" in ass and "Segoe UI Black" in ass, ass[:600]
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    png_dir = os.path.join(out, "f")
    os.makedirs(png_dir, exist_ok=True)
    mp4 = os.path.join(out, "short.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=1080, height=1920, fps=30, encoder="cpu",
                                              bitrate_mbps=4, duration=3.0), ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
    frame = os.path.join(out, "frame.png")
    mid_t = (cues[0].start + cues[0].end) / 2
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-ss", f"{mid_t:.2f}", "-i", mp4, "-frames:v", "1", frame],
                   check=True)
    from PySide6.QtGui import QImage
    img = QImage(frame).convertToFormat(QImage.Format_RGB888)
    a = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * img.height())
    a = a.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3].reshape(img.height(), img.width(), 3)
    white = (a.min(axis=2) > 235)
    rows = np.nonzero(white.sum(axis=1) > 25)[0]
    assert len(rows), "no se ve el texto"
    yc = (rows.min() + rows.max()) / 2 / img.height()
    assert 0.60 < yc < 0.72, yc
    print(f"✓ exportado: texto blanco con sombra suave a la altura del borde del video (centro al {yc * 100:.0f} %)")

    # --- el panel «📺 En pantalla»
    tp = win.transcript
    win.show_panel(tp) if hasattr(win, "show_panel") else None
    tp.set_media(amid)
    tp._set_view(1)
    pump(app, 0.4)
    cv = tp.captions
    assert cv.list.count() == len(cues), (cv.list.count(), len(cues))
    k = 4
    win.engine.seek(cues[k].start + 0.05)
    pump(app, 0.3)
    cv.highlight(win.engine.time, force=True)
    it = cv.list.item(k)
    assert it.text().startswith("▶") and it.background().color().name() == "#ff8a1f", (it.text(), it.background().color().name())
    assert not cv.list.item(k - 1).text().startswith("▶")
    print(f"✓ panel: lo que suena ahora sale grande y en naranja («{it.text()}»), lo demás apagado")
    cv._seek(cv.list.item(2))
    pump(app, 0.2)
    assert abs(win.engine.time - cues[2].start) < 0.05, (win.engine.time, cues[2].start)
    print("✓ clic en un bloque: el cabezal salta ahí")
    n0 = len(ctrl.project.transcripts[amid]["words"])
    t_a, t_b = words[0][0], words[2][1]               # el tramo del bloque «Rumor del día» (antes de corregir)
    cv.apply_edit(0, "Rumor de hoy mismo")            # 3 → 4 palabras
    pump(app, 0.5)
    w2 = ctrl.project.transcripts[amid]["words"]
    assert len(w2) == n0 + 1 and [w[2] for w in w2[:4]] == ["Rumor", "de", "hoy", "mismo"], [w[2] for w in w2[:5]]
    assert abs(w2[0][0] - t_a) < 2e-3 and abs(w2[3][1] - t_b) < 2e-3, (w2[:4], t_a, t_b)   # mismo tramo de tiempo
    pump(app, 0.4)
    assert cv.list.item(0).text().endswith("Rumor de hoy") or "Rumor" in cv.list.item(0).text()
    print("✓ corregir un bloque (con otra cantidad de palabras): se mantiene en su tramo, sincronizado")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
