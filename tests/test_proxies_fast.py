"""
Prueba de las COPIAS LIGERAS (proxies) más rápidas:
  · todas las copias de un video de UNA pasada (media y un cuarto), con la tarjeta gráfica AMD si la hay
    (~3× más rápido) y, si no, con el procesador como antes;
  · cada copia a su tamaño y con una imagen clave cada 0,5 s (saltar es instantáneo);
  · la barra dice cuánto falta («quedan ~3 min») y ya no repite el porcentaje («70 % · 71 %»).
Ejecutar:  .venv/Scripts/python.exe tests/test_proxies_fast.py <carpeta_salida>
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

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import proxies as PX
    ff = M.ffmpeg()
    fp = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    vid = os.path.join(out, "partida.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-shortest", "-pix_fmt", "yuv420p", vid], check=True)

    def check(paths, label):
        assert len(paths) == 2 and all(os.path.exists(x) for x in paths), paths
        for path, h in zip(sorted(paths, key=lambda x: "quarter" in x), (360, 180)):
            info = M.probe(path)
            assert info["height"] == h and abs(info["duration"] - 20) < 0.3, (path, info["height"], info["duration"])
            keys = subprocess.run([fp, "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                                   "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
                                  capture_output=True, text=True).stdout.split()
            keys = [float(k.split(",")[0]) for k in keys if k.split(",")[0]]
            gaps = [b - a for a, b in zip(keys, keys[1:])]
            assert gaps and max(gaps) <= 0.55, (label, max(gaps))
            assert info["has_audio"], "con sonido"

    hw = PX.hw_encoder()
    seen = []
    t0 = time.time()
    paths = PX.make_proxies(vid, 720, ["half", "quarter"], None, lambda f: seen.append(f), 20.0)
    took = time.time() - t0
    check(paths, "gráfica" if hw else "procesador")
    assert seen and max(seen) > 0.9
    print(f"✓ media y un cuarto de UNA pasada con {'la tarjeta gráfica (AMF)' if hw else 'el procesador'}: "
          f"{took:.1f} s para 20 s de video; imagen clave cada ≤0,5 s")
    for pth in paths:
        os.remove(pth)
    PX._HW = False                                      # como en un PC sin gráfica AMD
    paths = PX.make_proxies(vid, 720, ["half", "quarter"], None, None, 20.0)
    check(paths, "procesador")
    print("✓ sin gráfica AMD: lo mismo con el procesador (como antes)")
    PX._HW = None

    # --- la barra: «Copias ligeras 1/1 · quedan …» (el porcentaje lo pone la barra, una sola vez) ---
    for pth in paths:
        os.remove(pth)
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    ctrl, p = win.ctrl, win.ctrl.project
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    ctrl.add_media([mid], [t for t in p.tracks if t.kind == TRACK_VIDEO][-1].id, 0.0)
    texts = []
    pm = win.proxies
    pm.level = "half"
    pm.auto = True
    pm.ensure()
    pm.job.progress.connect(lambda _f, t: texts.append(t))
    t0 = time.time()
    while pm.job is not None and time.time() - t0 < 120:
        pump(app, 0.1)
    assert PX.has_proxy(vid, "half") and PX.has_proxy(vid, "quarter")
    assert texts and all("%" not in t for t in texts), texts[:3]
    assert any("quedan" in t for t in texts), texts[-3:]
    print(f"✓ barra: «{texts[-1]}» (sin el porcentaje repetido)")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
