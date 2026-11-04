"""
Prueba de la fluidez del VISOR con cortes rápidos en vertical:
  · cada archivo queda abierto en su propio reproductor (pool) y el siguiente plano se prepara antes: alternar
    entre dos videos cada 0,3 s ya no obliga a abrirlos una y otra vez (era lo que trababa la imagen);
  · el fondo desenfocado / las copias de arriba y abajo siguen al video (antes: 5 veces por segundo);
  · las copias van como el original (sin voltear); el espejo solo si se elige; desenfoque suave (sin cuadritos).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_preview_smooth.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.005)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "reproduccion/proxy")}
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core import transform
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui import preview as PV
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Desenfoque suave: sin cuadritos (mucha menos diferencia entre píxeles vecinos) y algo más oscuro
    img = QImage(80, 60, QImage.Format_RGB888)
    img.fill(QColor("black"))
    for x in range(0, 80, 8):
        for y in range(0, 60, 8):
            if (x + y) % 16 == 0:
                for i in range(8):
                    for j in range(8):
                        img.setPixelColor(x + i, y + j, QColor("white"))
    soft = PV._soft_blur(img, 2.2, 0.73)

    def arr(q):
        q = q.convertToFormat(QImage.Format_Grayscale8)
        return np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * q.height()).reshape(
            q.height(), q.bytesPerLine())[:, :q.width()].astype(float)
    assert np.abs(np.diff(arr(soft), axis=1)).mean() < np.abs(np.diff(arr(img), axis=1)).mean() * 0.4
    assert arr(soft).mean() < arr(img).mean()
    print("✓ fondo con desenfoque gaussiano suave (sin cuadritos) y algo más oscuro")

    ff = media_tools.ffmpeg()
    vids = []
    for name, src in (("a.mp4", "testsrc2=s=640x360:r=30:d=10"), ("b.mp4", "mandelbrot=s=640x360:r=30")):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "10",
                            "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15", p],
                           check=True)
        vids.append(p)
    song = os.path.join(out, "silencio.wav")
    with wave.open(song, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0\0" * 44100 * 8)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, eng = win.ctrl, win.engine
        ctrl.set_proxy_level("full") if hasattr(ctrl, "set_proxy_level") else None
        ctrl.set_project_format("edit")
        p = ctrl.project
        ids = ctrl.import_paths([song] + vids)
        while ctrl.analyzing:
            pump(app, 0.1)
        by = {p.media[i].name: i for i in ids}
        cuts = [{"media_id": by["a.mp4" if k % 2 == 0 else "b.mp4"], "source_in": 0.5 + 0.3 * k, "start": 0.3 * k,
                 "duration": 0.3, "fx": {}, "zoom": [], "speed": 1.0, "shot": k} for k in range(20)]
        plan = {"music": {"media_id": by["silencio.wav"], "source_in": 0.0, "duration": 6.0, "fade_out": 0},
                "clips": cuts, "texts": [], "drop": None, "style": "phonk", "sections": [], "period": 0.3}
        ctrl.apply_edit_plan(plan, layout="mirror")
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        assert all(not (c.layout or {}).get("flip") for c in p.clips_on(v1.id)), "copias sin voltear por defecto"
        layer = win.preview.canvas.layer(v1.id)
        n_bg = {"n": 0}
        real = layer._set_bg_source

        def counting(im):
            n_bg["n"] += 1
            real(im)
        layer._set_bg_source = counting
        eng.seek(0.0)
        pump(app, 1.0)
        n_bg["n"] = 0
        t0 = time.time()
        eng.play()
        pump(app, 3.0)
        eng.pause()
        secs = time.time() - t0
        lane = eng._vlanes[v1.id]
        loads = sum(s.loads for s in lane.slots)
        assert isinstance(lane, PV._VideoLane) and len(lane.slots) == PV.VIDEO_POOL
        assert loads <= 4, f"se abrieron archivos {loads} veces (antes: en cada corte)"
        assert {s.path for s in lane.slots if s.path} >= {p.media[by["a.mp4"]].path, p.media[by["b.mp4"]].path}
        rate = n_bg["n"] / secs
        assert rate >= 9, f"fondo a {rate:.1f} por segundo (antes 5)"
        assert layer._flip is False
        win.grab().save(os.path.join(out, "visor.png"))
        print(f"✓ 10 cortes alternando 2 videos: {loads} aperturas de archivo (pool de {PV.VIDEO_POOL}); "
              f"fondo a {rate:.0f} por segundo (antes 5)")

        # Exportar: copias sin voltear; espejo solo si se elige
        script = os.path.join(out, "f.txt")
        build_command(p, ExportOptions(path=os.path.join(out, "x.mp4"), width=270, height=480, fps=30,
                                       encoder="cpu"), ff, script)
        assert "vflip" not in open(script, encoding="utf-8").read()
        c0 = p.clips_on(v1.id)[0]
        ctrl.set_clip_props([c0.id], "espejo", layout=dict(transform.MIRROR_FLIP))
        build_command(p, ExportOptions(path=os.path.join(out, "x.mp4"), width=270, height=480, fps=30,
                                       encoder="cpu"), ff, script)
        assert "vflip" in open(script, encoding="utf-8").read()
        print("✓ al exportar: copias como el original; «Reflejo en espejo» solo si lo eliges")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
