"""
Prueba de 🔁 Convertir (menú junto a Ayuda) y de soltar archivos en el edit:
  · MKV con H.264 + AAC → MP4 sin recomprimir (instantáneo) · otro códec → MP4 recodificado · video → MP3;
  · la ventana: añadir archivos (como al arrastrarlos), elegir carpeta y convertir en segundo plano;
  · edit musical: soltar un VIDEO en «Canción» usa su sonido; soltar videos en la lista los marca;
  · «⚡ Exportar rápido» abre su menú sin errores.
Ejecutar:  .venv/Scripts/python.exe tests/test_convert.py <carpeta_salida>
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

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def codecs(ff, path):
    from editoria.core import media as M
    r = subprocess.run([M.ffprobe(), "-v", "error", "-show_entries", "stream=codec_name",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return r.stdout.split()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "convertir/carpeta")}
    app = QApplication(sys.argv)
    from editoria.core import convert as CV
    from editoria.core import media as M
    from editoria.ui.convert_window import ConvertWindow
    from editoria.ui.edit_dialog import EditDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    src = os.path.join(out, "fuente")
    os.makedirs(src, exist_ok=True)
    mkv = os.path.join(src, "partida.mkv")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", mkv], check=True)
    avi = os.path.join(src, "viejo.avi")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=f=330:d=3", "-c:v", "mpeg4", "-c:a", "mp3", "-shortest", avi],
                   check=True)
    dest = os.path.join(out, "convertidos")
    __import__("shutil").rmtree(dest, True)
    __import__("shutil").rmtree(os.path.join(out, "desde_ventana"), True)
    t0 = time.time()
    a = CV.convert(mkv, "mp4", dest, 4.0)
    assert a.endswith(".mp4") and codecs(ff, a)[:2] == ["h264", "aac"] and time.time() - t0 < 5, codecs(ff, a)
    b = CV.convert(avi, "mp4", dest, 3.0)
    assert codecs(ff, b)[0] == "h264" and codecs(ff, b)[1] == "aac", codecs(ff, b)
    c = CV.convert(mkv, "mp3", dest, 4.0)
    assert c.endswith(".mp3") and codecs(ff, c) == ["mp3"], codecs(ff, c)
    a2 = CV.convert(mkv, "mp4", dest, 4.0)
    assert a2 != a and "(2)" in a2, "no pisa lo que ya había"
    print("✓ MKV→MP4 sin recomprimir · AVI (mpeg4)→MP4 recodificado · video→MP3 · nunca pisa otro archivo")
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        dlg = ConvertWindow(win, "mp3")
        dlg.add_files([src])                 # como al arrastrar la carpeta
        assert dlg.list.count() == 2
        dlg._set_folder(os.path.join(out, "desde_ventana"))
        dlg.start()
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 60:
            pump(app, 0.2)
        got = sorted(os.listdir(os.path.join(out, "desde_ventana")))
        assert got == ["partida.mp3", "viejo.mp3"], got
        assert all(dlg.list.item(i).text().startswith("✓") for i in range(dlg.list.count()))
        print("✓ ventana Convertir: arrastrar, elegir carpeta y convertir en segundo plano")
        assert "&Convertir" in [a_.text() for a_ in win.menuBar().actions()]
        assert "IA ✨" in [a_.text() for a_ in win.menuBar().actions()], "13/11: menú «IA ✨» a la vista"
        print("✓ menú «Convertir» junto a Ayuda (y el menú «IA ✨» a la vista)")
        ed = EditDialog(win.ctrl, win)
        ed.use_song_file(mkv)
        t0 = time.time()
        while ed.song.count() == 0 and time.time() - t0 < 30:
            pump(app, 0.2)
        assert ed.song.count() >= 1 and "partida" in ed.song.currentText(), ed.song.currentText()
        ed.add_clip_files([avi])
        names = [ed.clips.item(i).text() for i in range(ed.clips.count())]
        assert any("viejo" in n_ for n_ in names), names
        print("✓ edit musical: soltar un video en «Canción» usa su sonido; soltar videos en la lista los añade")
        ed.close()
        QTimer.singleShot(300, lambda: app.activePopupWidget() and app.activePopupWidget().close())
        win.ctrl.add_media(win.ctrl.import_now([mkv]), None, 0.0)
        win.quick_export()
        print("✓ «⚡ Exportar rápido» abre su menú")
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
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
