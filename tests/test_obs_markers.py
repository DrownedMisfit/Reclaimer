"""
Prueba de las 🔖 Marcas de OBS (capítulos del MP4 → marcadores rojos → «Fallos marcados»):
  · read_chapters lee los capítulos con su título; el capítulo inicial sin título se ignora; sin título → «Marca N»;
  · suggest_cut: una marca en una pausa quita desde el inicio de la frase anterior hasta la palabra siguiente;
    una marca dentro de una palabra se lleva esa palabra entera (no deja media); sin transcripción, 3 s;
  · «Leer marcas» pone N marcadores rojos en su sitio y no duplica si se repite (un solo paso de Deshacer);
  · «✓ Quitar todos» acorta la narración lo esperado en un solo paso de Ctrl+Z;
  · un archivo sin capítulos da 0 y el mensaje de ayuda.
Sin ventanas visibles. Ejecutar:  .venv/Scripts/python.exe tests/test_obs_markers.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import obs_markers  # noqa: E402

TRANSCRIPCION = os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json")
WAV = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")

# Capítulos (ms). ffmpeg solo escribe bien el primer capítulo si empieza en 0 y con título, así que el primero es
# «Inicio» (0 s). Luego «NG» en una pausa (10,5 s), «Fallo» en una pausa (25,0 s) y uno sin título (30,0 s, dentro
# de la palabra «tiene»: pasa a ser «Marca 4»).
CAPITULOS = [(0, 10500, "Inicio"), (10500, 10600, "NG"), (25000, 25500, "Fallo"), (30000, 30500, "")]


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def wait(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def make_mp4(out):
    """Una grabación de prueba: fondo de color + la narración como sonido + capítulos como los pone OBS."""
    meta = os.path.join(out, "capitulos.txt")
    with open(meta, "w", encoding="utf-8") as f:
        f.write(";FFMETADATA1\n")
        for ini, fin, titulo in CAPITULOS:
            f.write("[CHAPTER]\nTIMEBASE=1/1000\nSTART=%d\nEND=%d\n" % (ini, fin))
            if titulo:
                f.write("title=%s\n" % titulo)
    mp4 = os.path.join(out, "grabacion_obs.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=navy:s=320x240:r=30:d=60", "-i", WAV, "-i", meta,
                    "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", mp4], check=True)
    return mp4, meta


def prueba_sin_qt(out, words):
    mp4, _meta = make_mp4(out)
    ch = obs_markers.read_chapters(mp4)
    print("capítulos:", ch)
    check([c["title"] for c in ch] == ["Inicio", "NG", "Fallo", "Marca 4"],
          "read_chapters: títulos Inicio, NG, Fallo y «Marca 4» (el sin título recibe su número)")
    check([round(c["t"], 2) for c in ch] == [0.0, 10.5, 25.0, 30.0], "read_chapters: tiempos 0 / 10,5 / 25,0 / 30,0 s")
    sin_ini = obs_markers.parse_chapters([{"start_time": "0.000000", "tags": {}},
                                          {"start_time": "5.000000", "tags": {"title": "NG"}}])
    check(sin_ini == [{"t": 5.0, "title": "NG"}],
          "el capítulo inicial sin título (OBS lo pone siempre) se ignora")
    check(obs_markers.read_chapters(WAV) == [], "un archivo sin capítulos da 0 marcas")
    check(obs_markers.read_chapters(os.path.join(out, "no_existe.mp4")) == [], "un archivo que no existe da 0 marcas")

    a, b = obs_markers.suggest_cut(10.5, words)                   # en la pausa entre «lento.» y «El»
    check(abs(a - 7.1) < 1e-6 and abs(b - 11.96) < 1e-6,
          f"marca en pausa: empieza en la frase anterior (7,1 s) y acaba en la palabra siguiente (11,96 s): {a}, {b}")
    a, b = obs_markers.suggest_cut(13.3, words)                   # dentro de «siente»
    check(abs(a - 11.96) < 1e-6 and b >= 13.3 + 0.05,
          f"marca dentro de una palabra: la palabra entera se va (no queda media palabra): {a}, {b}")
    a, b = obs_markers.suggest_cut(5.0, None)
    check(abs(a - 2.0) < 1e-6 and abs(b - 5.0) < 1e-6, "sin transcripción: los 3 s anteriores")
    return mp4


def prueba_ui(app, mp4, words, wav, MainWindow):
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui import obs_marks_ui

    win = MainWindow()
    ctrl = win.ctrl
    p = ctrl.project
    (mid,) = ctrl.import_now([mp4])
    wait(app, ctrl)
    ctrl.project.transcripts[mid] = {"words": words}
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO and t.name == "V1")
    ctrl.add_media([mid], v1.id, 0.0)
    wait(app, ctrl)
    check(len(p.clips) >= 1, "la grabación está en la línea de tiempo")
    dur0 = p.duration()
    marcadores0 = len(p.markers)

    # sin capítulos: 0 y el mensaje de ayuda (en un audio sin capítulos)
    (wid,) = ctrl.import_now([wav])
    wait(app, ctrl)
    n0 = obs_marks_ui.leer_marcas(win, [wid])
    msg0 = win.statusBar().currentMessage()
    check(n0 == 0 and "formato MP4 híbrido" in msg0 and "Añadir marcador de capítulo" in msg0,
          "sin capítulos: 0 marcas y la ayuda en la barra de estado")

    # «Leer marcas»: 3 marcadores rojos en su sitio, un solo paso de Deshacer
    stack = ctrl.undo_stack
    n_pasos = stack.count()
    n = obs_marks_ui.leer_marcas(win, [mid])
    check(n == 4, f"leer marcas: 4 marcas: {n}")
    rojos = sorted((m for m in p.markers if m.color == obs_marks_ui.MARK_COLOR), key=lambda m: m.time)
    check([m.label for m in rojos] == ["Inicio", "NG", "Fallo", "Marca 4"],
          "las 4 marcas son marcadores rojos con su nombre")
    check(all(abs(m.time - t) < 0.01 for m, t in zip(rojos, [0.0, 10.5, 25.0, 30.0])),
          "cada marcador está en su tiempo de la línea de tiempo")
    check(stack.count() == n_pasos + 1, "leer marcas ocupa un solo paso de Deshacer")
    check(obs_marks_ui.narration_ids(p) == [mid], "la narración es la grabación de la línea de tiempo")
    check("4 marcas de OBS" in win.statusBar().currentMessage(), "barra de estado: «4 marcas de OBS»")
    n2 = obs_marks_ui.leer_marcas(win, [mid])
    check(len(p.markers) - marcadores0 == 4 and n2 == 4, "leer otra vez no duplica los marcadores")

    # «✓ Quitar todos»: los tramos (7,1–11,96 y 21,1–30,0) → 13,76 s menos, en un paso de Deshacer
    panel = obs_marks_ui.fallos_panel(win)
    check(len(panel.marks) == 4, "el panel «Fallos marcados» tiene las 4 marcas")
    n_pasos = stack.count()
    marcas_antes = [dict(m_) for m_ in panel.marks]
    panel._cut_all()
    quitado = dur0 - p.duration()
    tramos = sorted((float(m_["a"]), float(m_["b"])) for m_ in marcas_antes)   # (lo que propone cada marca)
    unidos = []
    for a_, b_ in tramos:                                          # (los tramos que se tocan se quitan juntos)
        if b_ - a_ <= 0.05:
            continue
        if unidos and a_ <= unidos[-1][1] + 1e-6:
            unidos[-1][1] = max(unidos[-1][1], b_)
        else:
            unidos.append([a_, b_])
    esperado = sum(b_ - a_ for a_, b_ in unidos)
    check(abs(quitado - esperado) < 0.1, f"quitar todos acorta lo esperado ({esperado:.2f} s): {quitado:.3f} s")
    check(stack.count() == n_pasos + 1, "quitar todos ocupa un solo paso de Deshacer")
    check(not any(m.color == obs_marks_ui.MARK_COLOR for m in p.markers), "quitar todos retira las marcas rojas")
    ctrl.undo_stack.undo()
    check(abs(p.duration() - dur0) < 1e-3, "Ctrl+Z devuelve toda la narración de una vez")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    mp4 = prueba_sin_qt(out, words)

    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    prueba_ui(app, mp4, words, WAV, MainWindow)
    print("TODO OK")


if __name__ == "__main__":
    main()
