"""
Prueba de YouTube Shorts frente a videos normales.
Ejecutar:  .venv/Scripts/python.exe tests/test_shorts.py <carpeta_salida>
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

from editoria.ai.audit import run_audit  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core import transform  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402
from editoria.export.ffmpeg_export import ExportOptions, build_command  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


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
    ff = media_tools.ffmpeg()
    clip = os.path.join(out, "gameplay169.mp4")
    img = os.path.join(out, "captura.png")
    vert = os.path.join(out, "vertical.mp4")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=8",
                           "-c:v", "libx264", clip])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "smptehdbars=s=1200x500",
                           "-frames:v", "1", img])
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=1080x1920:r=30",
                           "-t", "4", "-c:v", "libx264", vert])
    ic, ii, iv = ctrl.import_paths([clip, img, vert])
    while ctrl.analyzing:
        pump(app, 0.1)

    ctrl.set_project_format("short")
    p = ctrl.project
    assert (p.width, p.height, p.format) == (1080, 1920, "short")
    from editoria.core.subtitles import SHORTS
    assert p.subtitles.preset == SHORTS and p.subtitles.max_words == 3 and p.subtitles.margin == 30.5,         (p.subtitles.preset, p.subtitles.max_words, p.subtitles.margin)
    print(f"✓ proyecto Short: 1080×1920 y subtítulos «{SHORTS}» (a lo mucho 3 palabras)")
    v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    c1 = ctrl.add_media([ic], v1.id, 0.0)[0]
    c2 = ctrl.add_media([ii], v2.id, 2.0)[0]
    c3 = ctrl.add_media([iv], v1.id, 8.0)[0]
    # (2026-10-10, el usuario: sin efectos automáticos al añadir — el fondo es «▦ Relleno», que pones tú)
    assert p.clips[c1].layout is None, ("horizontal abajo: entero, sin relleno automático", p.clips[c1].layout)
    assert p.clips[c2].layout == dict(transform.FULL, bg="none"), ("captura encima: entera, alrededor se ve lo de "
                                                                    "debajo", p.clips[c2].layout)
    assert p.clips[c3].layout is None, "un clip vertical llena la pantalla sin más"
    print("✓ al añadir, sin efectos automáticos: horizontal entero · captura encima con lo de debajo alrededor")
    t_id = ctrl.add_text(0.5, 3.0, "Gears of War 3 Beta")
    assert p.clips[t_id].text["y"] == 0.29 and not p.clips[t_id].text["box"]
    print("✓ etiqueta de contexto encima del video (como «Gears of War 3 Beta»)")
    ids = ctrl.add_comparison(ic, 0.0, iv, 0.0, 20.0, 3.0, ("ANTES", "AHORA"))
    lays = sorted(p.clips[i].layout["y"] for i in ids if p.clips[i].layout)
    assert lays == [0.0, 0.5], lays
    print("✓ comparación en un Short: arriba y abajo")

    # ▦ Relleno (lo pones tú): el visor llena la pantalla con la imagen desenfocada detrás del clip
    from editoria.core import fill as FILL
    ctrl.set_fill([c1], dict(FILL.DEFAULT))
    assert FILL.of(p.clips[c1].fx) and p.clips[c1].layout.get("bg") == "none"
    win.engine.seek(1.0)
    pump(app, 1.2)
    layer = win.preview.canvas.layers[v1.id]
    assert layer.fill.isVisible() and layer.fill.zValue() < layer.box.zValue(), "el visor muestra el relleno"
    win.timeline.fit()
    pump(app, 0.3)
    win.grab().save(os.path.join(out, "short_ui.png"))

    # Exportar: el fotograma es vertical y tiene contenido arriba (fondo), no negro
    mp4 = os.path.join(out, "short.mp4")
    args, _t = build_command(p, ExportOptions(path=mp4, width=540, height=960, fps=30, encoder="gpu", bitrate_mbps=4),
                             ff, os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-1500:]
    r = media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-ss", "1", "-i", mp4, "-frames:v", "1", "-vf",
                               "crop=540:200:0:0", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    top_brightness = sum(r.stdout) / max(1, len(r.stdout))
    assert top_brightness > 30, f"la parte de arriba no debería ser negra ({top_brightness:.0f})"
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", "2.5", "-i", mp4, "-frames:v", "1",
                           os.path.join(out, "short_frame.png")])
    print(f"✓ ▦ Relleno: en el visor y al exportar (brillo arriba {top_brightness:.0f}, no negro)")

    # Revisión: avisa si el Short dura más de 3 min
    ctrl.insert_ranges([{"media_id": ii, "start": 185.0, "duration": 2.0}], v1.id, "largo")
    issues, _n = run_audit(p, ctrl.missing, ctrl.peaks)
    assert any(i["category"] == "Short" and "3 minutos" in i["detail"] for i in issues)
    print("✓ revisión: avisa de un Short de más de 3 minutos")

    # Volver a video normal: fuera fondos desenfocados y subtítulos de Shorts
    ctrl.set_project_format("youtube")
    assert (p.width, p.height) == (1920, 1080)
    assert FILL.of(p.clips[c1].fx), "el relleno lo pusiste tú: se queda"
    assert p.subtitles.preset == "YouTube clásico"
    print("✓ cambiar a Video de YouTube deshace lo específico de Shorts")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
