"""
Prueba de 🗣 Separar los diálogos del ruido de fondo (Demucs en el motor de IA): un video con una voz y mucho ruido;
el clip de sonido pasa a sonar solo con la voz (el ruido baja mucho), Ctrl+Z / «Volver al sonido original»
lo devuelve; el edit con «Solo los diálogos» usa ese sonido.
Necesita F:\\Reclaimer\\motor_ia (si no está, la prueba lo dice y termina bien).
Ejecutar:  .venv/Scripts/python.exe tests/test_dialogue.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def rms_db(path, ff, a, b):
    r = subprocess.run([ff, "-nostdin", "-v", "error", "-ss", str(a), "-t", str(b - a), "-i", path, "-ac", "1",
                        "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.float32)
    return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.core import motor_ia
    if not motor_ia.PYTHON.exists():
        print("(sin motor de IA) TODO OK")
        return
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    voice = os.path.join(ASSETS, "narracion_prueba.wav")
    vid = os.path.join(out, "juego_con_voz.mp4")      # voz (primeros 8 s) + ruido de fondo fuerte todo el rato
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=14",
                    "-i", voice, "-f", "lavfi", "-i", "anoisesrc=d=14:c=brown:a=0.25",
                    "-filter_complex", "[1]atrim=0:8,apad[v];[v][2]amix=inputs=2:duration=longest:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-t", "14", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", vid], check=True)
    try:
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
        made = ctrl.add_media([mid], v1.id, 0.0)
        aud = next(i for i in made if p.track(p.clips[i].track_id).kind == TRACK_AUDIO)
        t0 = time.time()
        win.separate_dialogue([aud])
        while manager().tasks and time.time() - t0 < 600:
            pump(app, 0.3)
        pump(app, 0.3)
        c = p.clips[aud]
        assert c.media_id != mid and (c.fx or {}).get("orig_media") == mid, (c.media_id, c.fx)
        sep = p.media[c.media_id].path
        noise_before = rms_db(vid, ff, 10, 13.5)
        noise_after = rms_db(sep, ff, 10, 13.5)
        voice_after = rms_db(sep, ff, 1, 7)
        assert noise_after < noise_before - 12, (noise_before, noise_after)
        assert voice_after > noise_after + 12, (voice_after, noise_after)
        print(f"✓ solo los diálogos ({time.time() - t0:.0f} s): ruido de fondo {noise_before:.0f} → "
              f"{noise_after:.0f} dB, la voz se queda ({voice_after:.0f} dB)")
        ctrl.restore_dialogue([aud])
        assert p.clips[aud].media_id == mid and not (p.clips[aud].fx or {}).get("orig_media")
        print("✓ «Volver al sonido original»")
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
