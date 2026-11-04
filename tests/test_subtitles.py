"""
Prueba de subtítulos incrustados: bloques, resaltados, estilos, exportación y
comparación visual visor (QPainter) vs. exportación (FFmpeg/libass).
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_subtitles.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import voice_cleanup  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402
from editoria.core.subtitles import PRESETS, styled_cues  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402
from editoria.ui.subtitle_item import paint_subtitle  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
W, H = 960, 540


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    gp = os.path.join(out, "fondo.mp4")
    media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                           f"testsrc2=s={W}x{H}:r=30:d=30", "-vf", "hue=s=0.25", "-c:v", "libx264", gp])
    ctrl = ProjectController()
    narr = os.path.join(ASSETS, "narracion_prueba.wav")
    nid, gid = ctrl.import_paths([narr, gp])
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.05)
    p = ctrl.project
    ctrl.set_settings(width=W, height=H)
    ctrl.add_media([nid], [t for t in p.tracks if t.kind == TRACK_AUDIO][0].id, 0)
    ctrl.add_media([gid], [t for t in p.tracks if t.kind == TRACK_VIDEO][-1].id, 0)
    samples = media_tools.decode_mono(narr, 16000)
    tr = json.load(open(os.path.join(ASSETS, "narracion_prueba.transcripcion.json"), encoding="utf-8"))
    tr = voice_cleanup.refine_transcript(samples, 16000, tr)
    ctrl.set_transcript(nid, tr)
    items = voice_cleanup.analyze(samples, 16000, tr["words"], voice_cleanup.CleanupOptions())
    ctrl.set_suggestions(nid, items, voice_cleanup.CleanupOptions().kinds(),
                         {k: v[1] for k, v in voice_cleanup.KINDS.items()})
    ctrl.apply_suggestions([s.id for s in ctrl.project.suggestions if s.kind == "silence"])

    # Activar y resaltar «lento»
    ctrl.set_subtitle_style("Activar", enabled=True, media_id=nid)
    words = ctrl.project.transcripts[nid]["words"]
    lento = [i for i, w in enumerate(words) if w[2].lower().startswith("lento")]
    ctrl.set_emphasis(lento, True)
    assert ctrl.project.subtitles.emphasis == lento
    ctrl.undo_stack.undo()
    assert ctrl.project.subtitles.emphasis == []
    ctrl.undo_stack.redo()
    print("✓ resaltar palabras (con deshacer)")

    # Cambios seguidos de estilo = un solo paso de deshacer
    n0 = ctrl.undo_stack.count()
    for s in (5.2, 5.4, 5.6):
        ctrl.set_subtitle_style(size=s)
    assert ctrl.undo_stack.count() == n0 + 1, (ctrl.undo_stack.count(), n0)
    print("✓ cambios seguidos de estilo se agrupan en un paso")

    sheet = []
    for name in PRESETS:
        ctrl.set_subtitle_style(f"Estilo {name}", preset=name, **PRESETS[name])
        cues = styled_cues(ctrl.project)
        st = ctrl.project.subtitles
        assert cues
        for c in cues:
            assert len(c.lines) <= st.max_lines
            # Ninguna línea mucho más larga que el máximo (una palabra larga puede pasarse un poco)
            assert all(len(" ".join(w.text for w in line)) <= st.max_chars * 1.6 for line in c.lines), c.text()
        # Momento: mitad de la frase con «lento»
        target = next(c for c in cues if any(w.index in lento for w in c.words))
        lw = next(w for w in target.words if w.index in lento)
        t = (lw.start + lw.end) / 2
        mp4 = os.path.join(out, f"sub_{name}.mp4")
        args, total = build_command(ctrl.project, ExportOptions(path=mp4, width=W, height=H, fps=30,
                                                                encoder="gpu", bitrate_mbps=6),
                                    media_tools.ffmpeg(), os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True, creationflags=media_tools.NO_WINDOW)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
        frame = os.path.join(out, f"frame_{name}.png")
        media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", mp4,
                               "-frames:v", "1", frame])
        # Lo mismo dibujado por el visor
        img = QImage(W, H, QImage.Format_RGB32)
        img.fill(QColor("#556070"))
        ptr = QPainter(img)
        paint_subtitle(ptr, target, ctrl.project.subtitles, t, W, H)
        ptr.end()
        prev = os.path.join(out, f"preview_{name}.png")
        img.save(prev)
        sheet += [frame, prev]
        print(f"✓ {name}: {len(cues)} bloques, exportado {total:.1f} s — «{target.text(' / ')}»")

    # Hoja de comparación: export (izq) vs visor (der)
    inputs = []
    for f in sheet:
        inputs += ["-i", f]
    n = len(sheet)
    graph = "".join(f"[{i}:v]scale=480:270[s{i}];" for i in range(n)) + \
            "".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout=" + \
            "|".join(f"{(i % 2) * 480}_{(i // 2) * 270}" for i in range(n)) + "[v]"
    res = os.path.join(out, "comparacion.png")
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-v", "error", "-y"] + inputs +
                              ["-filter_complex", graph, "-map", "[v]", res])
    assert r.returncode == 0, r.stderr.decode()
    print("comparación:", res)


if __name__ == "__main__":
    main()
