"""
Prueba de que ✓ / ✗ en 🔎 Momentos va FLUIDO y no se vuelve cada vez más lento (el usuario: «cada vez más lenta»):
  · biblioteca grande (6 videos de 1 h analizados) y un historial de 40 búsquedas con sus marcas;
  · 20 marcas seguidas: cada una por debajo de 120 ms y las últimas no más lentas que las primeras;
  · no se escribe el disco en cada marca (se guarda todo junto después) y lo marcado queda guardado.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_moments_speed.py <carpeta_salida>
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


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import image_feedback as IF
    from editoria.ai import moments as MO
    from editoria.core import media as M
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    rng = np.random.default_rng(0)
    for q in range(40):                     # historial: 40 búsquedas con sus marcas (el archivo pesa)
        fb = {"pos": {f"k{q}_{i}": rng.normal(size=512) for i in range(30)},
              "neg": {f"n{q}_{i}": rng.normal(size=512) for i in range(30)}}
        IF.save_feedback(f"búsqueda {q}", fb, "videos")
    IF.flush()
    vids = []
    for i in range(6):
        p = os.path.join(out, f"v{i}.mp4")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=160x90:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast", p], check=True)
        vids.append(p)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    ids = ctrl.import_now(vids)
    while ctrl.analyzing:
        pump(app, 0.1)
    for mid in ids:                          # huellas de 1 h de video (1 por segundo)
        v = rng.normal(size=(3600, 512)).astype(np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        ctrl.clip_vecs[mid] = (np.arange(3600, dtype=np.float32), v)
        ctrl.project.media[mid].duration = 3600.0
    mp = win.moments
    data, _meta = mp._data()
    mp.local_query = "soldado"
    mp._run(lambda: MO.search_image(np.asarray(next(iter(data.values()))["vecs"][:1]), data, top=60), "«soldado»")
    t0 = time.time()
    while mp.job is not None and time.time() - t0 < 120:
        pump(app, 0.05)
    assert len(mp.results) >= 20, len(mp.results)
    store = IF._store_path()
    mt0 = os.path.getmtime(store)
    times = []
    for k in range(20):
        row = (k * 3) % len(mp.results)
        a = time.perf_counter()
        mp.on_mark(row, k % 3 != 2)
        app.processEvents()
        times.append((time.perf_counter() - a) * 1000)
        pump(app, 0.05)
    assert os.path.getmtime(store) == mt0, "no se escribe el disco en cada ✓/✗"
    first, last = np.mean(times[1:6]), np.mean(times[-5:])
    assert max(times[1:]) < 120, [round(t) for t in times]
    assert last <= first * 1.5 + 10, (first, last)
    print(f"✓ 20 marcas: {np.mean(times[1:]):.0f} ms de media (máx {max(times[1:]):.0f} ms), sin crecer "
          f"({first:.0f} → {last:.0f} ms) · el disco no se toca en cada marca")
    pump(app, 1.6)                          # se guarda solo, todo junto, al dejar de marcar
    assert os.path.getmtime(store) > mt0
    n_marks = len(mp.local_fb["pos"]) + len(mp.local_fb["neg"])
    IF._MEM["data"] = None                  # como al abrir Reclaimer otra vez: se lee del disco
    fb = IF.load_feedback("soldado", "videos")
    assert len(fb["pos"]) + len(fb["neg"]) == n_marks > 0, (n_marks, fb.keys())
    assert len(IF.load_feedback("búsqueda 7", "videos")["pos"]) == 30, "el historial sigue entero"
    print("✓ lo marcado queda guardado (y el historial de búsquedas intacto)")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
