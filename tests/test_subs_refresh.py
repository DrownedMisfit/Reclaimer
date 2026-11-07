"""
Prueba de la huella de los subtítulos y la voz en el visor (PlaybackEngine._refresh): no se recalcula al borrar un
B-roll (que no suena), pero sí al editar la narración: los subtítulos siguen las palabras que se mueven al quitar un
silencio, y las palabras cortadas no salen.
Ejecutar:  .venv/Scripts/python.exe tests/test_subs_refresh.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402
from editoria.core.subtitles import styled_cues  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def textos(cues):
    return [(round(c.start, 2), round(c.end, 2)) for c in cues]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    nar = os.path.join(out, "narracion.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                    "-f", "lavfi", "-i", "sine=f=300:d=20", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", nar], check=True)
    bro = os.path.join(out, "broll.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=6",
                    "-c:v", "libx264", "-preset", "ultrafast", bro], check=True)

    from editoria.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1400, 800)
    win.show()
    c = win.ctrl
    p = c.project
    p.fps = 30.0
    eng = win.engine
    nm, bm = c.import_now([nar, bro])
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    c.add_media([nm], v1.id, 0.0)
    while c.analyzing:
        pump(app, 0.1)
    # palabras cada 0,45 s (una frase cada 6), y sin cortar nada aún
    words, segs = [], []
    vocab = ["hola", "esto", "es", "una", "prueba", "de", "subtítulos"]
    for k in range(40):
        s = 0.2 + 0.45 * k
        w = vocab[k % len(vocab)] + ("." if k % 6 == 5 else "")
        words.append([round(s, 3), round(s + 0.4, 3), w, 0.95])
    segs = [[words[i][0], words[min(i + 5, 39)][1], i, min(i + 6, 40)] for i in range(0, 40, 6)]
    c.set_transcript(nm, {"language": "es", "model": "sintetico", "words": words, "segments": segs})
    c.set_subtitle_style("Subtítulos", enabled=True, media_id=nm)
    eng._refresh()
    cues_0 = list(eng._cues)
    assert cues_0, "debe haber subtítulos"
    assert textos(cues_0) == textos(styled_cues(p)), "subtítulos iniciales"
    print(f"✓ subtítulos iniciales: {len(cues_0)} bloques, iguales a los que calcula el proyecto")

    # --- borrar un B-roll (sin sonido de narración): no se recalculan voz ni subtítulos
    v_bro = [t for t in p.tracks if t.kind == TRACK_VIDEO][0]
    b_ids = c.add_media([bm], v_bro.id, 2.0)
    pump(app, 0.2)
    eng._refresh()
    cues_a = eng._cues
    b_clip = [cid for cid in p.clips if p.clips[cid].media_id == bm]
    assert b_clip, "B-roll colocado"
    c.delete_clips(b_clip)
    pump(app, 0.2)
    eng._refresh()
    assert eng._cues is cues_a, "al borrar un B-roll no se debe recalcular los subtítulos"
    print("✓ borrar un B-roll no recalcula los subtítulos (la huella ignora lo que no suena)")

    # --- editar la narración: quitar un silencio de 5,0 a 6,0 s → las palabras de después se corren 1 s
    antes = textos(eng._cues)
    n_ids = [cid for cid in p.clips if p.clips[cid].media_id == nm]
    c.remove_silence(n_ids, [(5.0, 6.0)], scope="all")
    pump(app, 0.2)
    eng._refresh()
    despues = textos(eng._cues)
    assert despues == textos(styled_cues(p)), "los subtítulos deben seguir la narración editada"
    assert despues != antes, "al quitar un silencio los subtítulos deben cambiar"
    primero_despues = [b for b in despues if b[0] >= 5.0][:1]
    primero_antes = [b for b in antes if b[0] >= 6.0][:1]
    assert primero_despues and primero_antes and abs(primero_despues[0][0] - (primero_antes[0][0] - 1.0)) < 0.05, (
        primero_despues, primero_antes)
    print(f"✓ tras quitar 1 s de silencio, los subtítulos siguen la narración: el bloque que empezaba en "
          f"{primero_antes[0][0]} s empieza ahora en {primero_despues[0][0]} s")

    win.analyzer.shutdown()
    c.undo_stack.setClean()
    c._media_dirty = False
    win.close()
    pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
