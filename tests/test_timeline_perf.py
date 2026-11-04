"""
Prueba de RENDIMIENTO con muchos clips (el «cada vez se pone más lento»): con ~800 clips en la línea de tiempo,
mover el cabezal (lo que pasa en cada fotograma al reproducir), redibujar la línea de tiempo y hacer una edición
deben seguir siendo rápidos. Y el resaltado naranja: solo contorno y solo cuando algo está bloqueado.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_timeline_perf.py <carpeta_salida>
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui import nudge as NG
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Resaltado naranja: solo cuando algo está bloqueado
    assert NG.is_blocking("Selecciona antes el clip donde quieres desenfocar una zona.")
    assert NG.is_blocking("Primero transcribe tu narración (pestaña «Limpieza»).")
    assert not NG.is_blocking("Añadido en el cabezal de la línea de tiempo.")
    assert not NG.is_blocking("La IA puso 5 clips en la timeline.")
    print("✓ el contorno naranja solo sale cuando algo está bloqueado (no con mensajes que solo informan)")

    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        pump(app, 0.4)
        ctrl, tl = win.ctrl, win.timeline
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        n = 400
        ctrl.insert_ranges([{"media_id": mid, "start": i * 1.0, "duration": 1.0, "source_in": (i % 18) * 1.0}
                            for i in range(n)], v1.id, "muchos")
        for i in range(n // 10):
            ctrl.add_text(i * 10.0, 2.0, f"T{i}")
        pump(app, 1.0)
        tl.fit()
        pump(app, 0.5)
        clips = len(ctrl.project.clips)

        def avg(fn, reps=6):
            t0 = time.perf_counter()
            for _ in range(reps):
                fn()
                app.processEvents()
            return (time.perf_counter() - t0) / reps * 1000
        k = {"t": 100.0}

        def seek():
            k["t"] += 0.04
            win.engine.seek(k["t"])
        t_seek = avg(seek)
        t_paint = avg(lambda: tl.repaint())
        cid = next(c.id for c in ctrl.project.clips_on(v1.id))
        vol = {"v": 1.0}

        def edit():
            vol["v"] = 0.9 if vol["v"] == 1.0 else 1.0
            ctrl.set_clip_props([cid], "vol", volume=vol["v"])
        t_edit = avg(edit)
        print(f"  {clips} clips: mover el cabezal {t_seek:.0f} ms · redibujar {t_paint:.0f} ms · editar {t_edit:.0f} ms")
        # (antes: ~226, ~217 y ~272 ms) — con margen para PCs más lentos
        assert t_seek < 90, t_seek
        assert t_paint < 110, t_paint
        assert t_edit < 200, t_edit
        print(f"✓ con {clips} clips sigue fluido (antes se volvía lento con cada clip añadido)")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    finally:
        for k2, v in keep.items():
            if v is None:
                st.remove(k2)
            else:
                st.setValue(k2, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
