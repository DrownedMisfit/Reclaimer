"""
Prueba de la tira de miniaturas en la línea de tiempo: a lo largo de cada clip de video se ven sus fotogramas
(el del momento que toca, también recortado o acelerado), no solo el primero. Y el indicador de la IA debajo
del visor.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_filmstrip.py <carpeta_salida>
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
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui import filmstrip as FS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "color.mp4")
    # cada 3 s un color distinto: así se nota si la tira enseña el fotograma correcto
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=320x180:d=3,format=yuv420p[a];color=c=green:s=320x180:d=3,format=yuv420p[b];"
                    "color=c=blue:s=320x180:d=3,format=yuv420p[c];[a][b][c]concat=n=3:v=1:a=0",
                    "-c:v", "libx264", "-preset", "ultrafast", "-r", "30", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, tl = win.ctrl, win.timeline
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 0.0)
        tl.pps = (tl.width() - tl.HEADER_W - 30) / 9.0     # que se vea el clip entero
        tl.update()
        m = ctrl.project.media[mid]
        assert tl.filmstrips.get(m) is None, "primero se pide (en segundo plano)"
        t0 = time.time()
        while tl.filmstrips.get(m) is None and time.time() - t0 < 30:
            pump(app, 0.1)
        strip = tl.filmstrips.get(m)
        assert strip is not None and os.path.exists(FS.sprite_path(m.path, m.duration))
        pix, step, tile_w = strip
        img = pix.toImage()
        cols = [img.pixelColor(int(tile_w * (k + 0.5)), pix.height() // 2) for k in (0, 4, 7)]
        assert cols[0].red() > 150 and cols[1].green() > 100 and cols[2].blue() > 150, \
            [(c.red(), c.green(), c.blue()) for c in cols]
        pump(app, 0.3)
        grab = tl.grab().toImage()
        i = ctrl.project.tracks.index(v1)
        y = int(tl.track_y(i) + tl.track_h(i) * 0.7)
        xs = [int(tl.x_for(t)) for t in (1.0, 4.5, 7.5)]
        got = [grab.pixelColor(x, y) for x in xs]
        assert got[0].red() > got[0].blue() and got[1].green() > got[1].red() and got[2].blue() > got[2].red(), \
            [(c.red(), c.green(), c.blue()) for c in got]
        tl.grab().save(os.path.join(out, "tira.png"))
        print(f"✓ tira de miniaturas: {pix.width() // int(tile_w)} fotogramas; en la línea de tiempo se ve "
              "rojo → verde → azul a lo largo del clip (no solo el primero)")
        # El indicador de la IA está en la barra de debajo del visor
        chip = win.preview.task_chip
        chip.show()
        pump(app, 0.2)
        cv = win.preview.canvas
        assert chip.y() >= cv.y() + cv.height() - 2 and chip.x() > win.preview.width() / 2,             ("debajo de la imagen, a la derecha", chip.geometry(), cv.geometry())
        win.grab().save(os.path.join(out, "indicador.png"))
        chip.hide()
        print("✓ el indicador de la IA está en la barra de debajo de la imagen")
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
