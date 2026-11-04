"""
Prueba de 🟩 Pantalla verde: un clic detecta el color del fondo y lo quita (en el visor y al exportar); lo de
debajo se ve a través; el sujeto se conserva; Tolerancia/Suavidad ajustables; ✕ lo quita; Ctrl+Z.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_chroma.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # junto al programa, nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    from editoria.core import chroma as CK
    from editoria.core import media as M

    # 1) Detectar y quitar (sin la app)
    g = np.zeros((90, 160, 3), np.uint8)
    g[:] = (0, 177, 64)
    g[30:60, 60:100] = (255, 255, 255)
    col = CK.detect(g)
    r, gg, b = CK._rgb(col)
    assert gg > 150 and r < 40 and b < 90, col
    blue = np.zeros_like(g)
    blue[:] = (20, 60, 230)
    assert CK._rgb(CK.detect(blue))[2] > 200
    argb = np.zeros((90, 160), np.uint32)
    bgra = argb.view(np.uint8).reshape(90, 160, 4)
    bgra[..., 0], bgra[..., 1], bgra[..., 2], bgra[..., 3] = g[..., 2], g[..., 1], g[..., 0], 255
    CK.apply_argb32(argb, dict(CK.DEFAULT, color=col))
    assert bgra[5, 5, 3] == 0 and bgra[45, 80, 3] == 255, (bgra[5, 5], bgra[45, 80])
    print(f"✓ detecta el fondo ({col}) y lo vuelve transparente; el sujeto blanco se queda")

    ff = M.ffmpeg()
    red = os.path.join(out, "fondo_rojo.mp4")
    green = os.path.join(out, "pantalla_verde.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", red], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00B140:s=320x180:d=3",
                    "-f", "lavfi", "-i", "color=c=white:s=120x80:d=3", "-filter_complex", "[0][1]overlay=100:50",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", green], check=True)

    app = QApplication(sys.argv)
    from editoria.core.model import TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 320, 180
        rid, gid = ctrl.import_now([red, green])
        while ctrl.analyzing:
            pump(app, 0.1)
        v2, v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][:2]
        ctrl.add_media([rid], v1.id, 0.0)
        gc = ctrl.add_media([gid], v2.id, 0.0)[0]
        win.timeline.set_selection([gc])
        win.engine.seek(1.0)
        pump(app, 0.3)
        fx_panel = win.effects
        fx_panel.add_chroma()
        ch = (p.clips[gc].fx or {}).get("chroma")
        assert ch and CK._rgb(ch["color"])[1] > 150, ch
        pump(app, 0.4)
        layer = win.preview.canvas.layer(v2.id)
        eff = layer.box.graphicsEffect()
        assert eff is not None and getattr(eff, "chroma", None), "el visor aplica la pantalla verde"
        fx_panel.ck_sim.setValue(0.14)
        assert abs(p.clips[gc].fx["chroma"]["similarity"] - 0.14) < 1e-6
        print("✓ un clic en «Quitar fondo de color» (color detectado en el fotograma); Tolerancia ajustable; "
              "el visor lo muestra")

        mp4 = os.path.join(out, "x.mp4")
        args, _t = build_command(p, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                  loudnorm=False), ff, os.path.join(out, "f.txt"))
        subprocess.run(args, check=True, capture_output=True)
        fr = M.frame_rgb(mp4, 1.0, 320).astype(int)
        corner, center = fr[10, 10], fr[90, 160]
        assert corner[0] > 180 and corner[1] < 90, ("el fondo rojo se ve a través", corner)
        assert center.min() > 200, ("el sujeto blanco se queda", center)
        print(f"✓ exportado: donde había verde se ve el rojo de debajo {tuple(corner)}; el sujeto se queda "
              f"{tuple(center)}")

        fx_panel.clear_chroma()
        assert not (p.clips[gc].fx or {}).get("chroma")
        ctrl.undo_stack.undo()
        assert (p.clips[gc].fx or {}).get("chroma")
        print("✓ ✕ quita la pantalla verde; Ctrl+Z la devuelve")
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
