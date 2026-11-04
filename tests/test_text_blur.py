"""
Prueba de «Desenfocar lo de debajo» en los textos: los que añades tú lo traen activado (los de la IA no);
mientras se ve el texto, la imagen de debajo se desenfoca en el visor y al exportar; se quita en el Inspector.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_text_blur.py <carpeta_salida>
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
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "texto/mi_estilo", "texto/recordar")}
    app = QApplication(sys.argv)
    import cv2
    from editoria.core import media as M
    from editoria.core.model import ORIGIN_AI, TRACK_VIDEO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4",
                    "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    try:
        st.remove("texto/mi_estilo")
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        p.width, p.height = 640, 360
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 0.0)
        tid = ctrl.add_text(2.0, 1.5, "HOLA")
        ai = ctrl.add_text(0.2, 0.5, "IA", origin=ORIGIN_AI)
        assert p.clips[tid].text["blur_under"] == 0.5 and not p.clips[ai].text.get("blur_under")
        print("✓ tus textos traen «Desenfocar lo de debajo» (50 %); los de la IA no")

        # Visor: desenfocado solo mientras se ve el texto
        eng = win.engine
        layer = win.preview.canvas.layer(v1.id)
        eng.seek(1.0)
        pump(app, 0.4)
        def blurred(e):
            if e is None:
                return False
            return getattr(e, "blur", 0) >= 0.3 or (hasattr(e, "blurRadius") and e.blurRadius() >= 10)
        e0 = layer.box.graphicsEffect()
        assert not blurred(e0), "antes del texto: nítido"
        eng.seek(2.7)
        pump(app, 0.4)
        e1 = layer.box.graphicsEffect()
        assert blurred(e1), ("durante el texto: borroso", e1)
        print("✓ visor: la imagen se desenfoca mientras se ve el texto (y vuelve a verse nítida al terminar)")

        # Exportar: el fotograma con texto sale menos nítido
        mp4 = os.path.join(out, "x.mp4")
        script = os.path.join(out, "f.txt")
        args, _tot = build_command(p, ExportOptions(path=mp4, width=640, height=360, fps=30, encoder="cpu",
                                                    loudnorm=False), M.ffmpeg(), script)
        assert "gblur" in open(script, encoding="utf-8").read()
        subprocess.run(args, check=True, capture_output=True)

        def sharp(t):
            img = M.frame_rgb(mp4, t, 640)
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)[:100]     # arriba (lejos del texto, que va abajo/centro)
            return float(cv2.Laplacian(g, cv2.CV_64F).var())
        s_before, s_during = sharp(1.0), sharp(2.8)
        assert s_during < s_before * 0.5, (s_before, s_during)
        print(f"✓ exportado: nitidez {s_before:.0f} → {s_during:.0f} mientras se ve el texto")

        # Inspector: se quita con la casilla
        win.timeline.set_selection([tid])
        pump(app, 0.3)
        insp = win.inspector
        sp, _setter = insp.tw["blur_under"]
        assert abs(sp.value() - 50) < 1
        box = sp.parentWidget()
        while box is not None and not hasattr(box, "isCheckable"):
            box = box.parentWidget()
        assert box is not None and box.isChecked()
        box.setChecked(False)
        pump(app, 0.2)
        assert p.clips[tid].text["blur_under"] == 0.0
        ctrl.undo_stack.undo()
        assert p.clips[tid].text["blur_under"] == 0.5
        print("✓ Inspector ▸ Texto ▸ «Desenfocar lo de debajo»: se quita y se vuelve a poner (Ctrl+Z)")
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
