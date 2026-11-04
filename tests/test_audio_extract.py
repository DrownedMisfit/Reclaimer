"""
Prueba de «🎵 Convertir en solo audio» (Medios) y del análisis de movimiento que ya no se queda en 5 %:
  · AAC → se copia tal cual (.m4a, idéntico y rápido); otro sonido → AAC 256 kbps; nunca junto al original;
  · el audio aparece en Medios ▸ «Audio extraído»;
  · «Viendo el movimiento»: la barra avanza DENTRO del video y los videos largos solo miran fotogramas clave.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_audio_extract.py <carpeta_salida>
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
    from editoria.ai import edit_maker as E
    from editoria.core import audio_extract as AX
    from editoria.core import media as M
    ff = M.ffmpeg()
    v_aac = os.path.join(out, "con aac.mp4")
    v_pcm = os.path.join(out, "con pcm.mkv")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=f=440:d=6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", v_aac], check=True)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-f", "lavfi", "-i", "sine=f=660:d=5", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "pcm_s16le", "-shortest", v_pcm], check=True)

    # 1) Sacar el audio
    seen = []
    a1 = AX.extract(v_aac, 6.0, seen.append)
    a2 = AX.extract(v_pcm, 5.0)
    assert a1.endswith(".m4a") and AX.audio_codec(a1) == "aac" and os.path.dirname(a1) == AX.out_dir()
    assert a2.endswith(".m4a") and AX.audio_codec(a2) == "aac"
    assert abs(M.probe(a1)["duration"] - 6.0) < 0.3 and not M.probe(a1).get("has_video")
    assert os.path.exists(v_aac) and os.path.exists(v_pcm), "los originales no se tocan"
    a3 = AX.extract(v_aac, 6.0)
    assert a3 != a1 and "(2)" in a3, "no pisa uno anterior"
    print(f"✓ audio: AAC copiado tal cual ({os.path.basename(a1)}), otro sonido → AAC; en «{AX.out_dir()}»")

    # 2) Análisis de movimiento: progreso dentro del video y modo «video largo»
    prog = []
    E.LONG_VIDEO, real = 3.0, E.LONG_VIDEO        # «largo» a partir de 3 s, para probar con un video corto
    try:
        r = E.motion_profile(v_aac, 6.0, None, prog.append)
    finally:
        E.LONG_VIDEO = real
    assert len(r["motion"]) >= 20 and prog and all(0 <= f < 1 for f in prog), (len(r["motion"]), prog[:3])
    filled = E._fill_repeats([0.0, 5.0, 0.0, 0.0, 8.0, 0.0])
    assert filled[2] == 6.0 and filled[3] == 7.0, filled
    msgs = []
    E.make_edit.__globals__["motion_profile"](v_pcm, 5.0, None, lambda f: msgs.append(f))
    print(f"✓ «Viendo el movimiento»: la barra avanza dentro del video ({len(prog)} avisos); videos largos: solo "
          "fotogramas clave")

    # 3) En Medios
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1400, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        ids = ctrl.import_paths([v_aac, v_pcm])
        while ctrl.analyzing:
            pump(app, 0.1)
        lib = win.library
        before = set(ctrl.project.media)
        lib._to_audio(ids)
        t0 = time.time()
        while manager().tasks and time.time() - t0 < 60:
            pump(app, 0.1)
        pump(app, 0.5)
        while ctrl.analyzing:
            pump(app, 0.1)
        new = [ctrl.project.media[i] for i in set(ctrl.project.media) - before]
        assert len(new) == 2 and all(m.kind == "audio" and m.category == "Audio extraído" for m in new), \
            [(m.name, m.kind, m.category) for m in new]
        print("✓ Medios ▸ clic derecho ▸ «🎵 Convertir en solo audio»: aparecen en «Audio extraído»")
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
