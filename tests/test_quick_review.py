"""
Prueba de la ⚡ Revisión rápida con teclas y de las 📋 plantillas de proyecto:
  · la revisión recorre, en orden de video, las propuestas pendientes y los cortes dudosos;
  · Enter aplica la propuesta (baja la duración) o aplica la sugerencia del corte; O da por bueno el corte
    (desaparece su línea roja);
  · Supr rechaza; → salta sin decidir; ← vuelve; P vuelve a escuchar; Esc cierra;
  · el resumen cuenta bien; Ctrl+Z deshace una decisión;
  · una plantilla guarda formato, pistas, ajustes de audio y subtítulos, sin clips; «Nuevo desde plantilla» la aplica.
Sin ventanas visibles (QT_QPA_PLATFORM=offscreen). Ejecutar:  .venv/Scripts/python.exe tests/test_quick_review.py <carpeta_salida>
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import voice_cleanup  # noqa: E402
from editoria.core import cut_check  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core import project_templates as pt  # noqa: E402
from editoria.core.model import SUG_APPLIED, SUG_PENDING, SUG_REJECTED, TRACK_AUDIO, TRACK_VIDEO, Clip, Project  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def wait(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def make_av(out, wav):
    ff = media_tools.ffmpeg()
    p = os.path.join(out, "grabacion_prueba.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=31",
                    "-i", wav, "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", p],
                   check=True)
    return p


def new_project(app, ctrl, av, words):
    (mid,) = ctrl.import_now([av])
    wait(app, ctrl)
    ctrl.project.transcripts[mid] = {"words": words}
    v1 = next(t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO and t.name == "V1")
    ctrl.add_media([mid], v1.id, 0.0)
    a = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    return mid, a, v1


def press(app, w, key):
    QTest.keyClick(w, key)
    app.processEvents()


def cerrar(win):
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()


def prueba_plantillas_sin_ventanas():
    """Sin Qt: se guarda, se lista y se aplica una plantilla; nunca lleva clips."""
    p = Project.new()
    p.format = "short"
    p.width, p.height = 1080, 1920
    p.loudnorm = False
    p.tracks[-1].fx = {"eq": True, "compress": False}
    p.tracks[-1].role = "voz"
    p.subtitles.preset = "Mis Shorts"
    p.subtitles.size = 7.5
    p.subtitles.media_id = "narracion-x"
    p.subtitles.enabled = True
    p.clips["c1"] = Clip(id="c1", media_id="m", track_id=p.tracks[-1].id, start=0.0, source_in=0.0, duration=3.0)
    path = pt.save(p, "Prueba Short")
    check(os.path.isfile(path) and path.startswith(os.environ["EDITORIA_DATOS"]),
          "la plantilla se guarda en los datos de Reclaimer (datos/plantillas_proyecto)")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    check("clips" not in raw and "media" not in raw and "c1" not in json.dumps(raw),
          "la plantilla no guarda clips ni medios")
    lst = pt.list_templates()
    check(any(t["nombre"] == "Prueba Short" and t["formato"] == "short" for t in lst),
          "la plantilla aparece en la lista con su formato")
    q = Project.new()
    pt.apply(q, pt.load(path))
    check(q.format == "short" and q.width == 1080 and q.height == 1920, "la plantilla pone formato y resolución")
    check(q.loudnorm is False and abs(q.fps - 60.0) < 1e-9, "la plantilla pone normalizado y fotogramas")
    names = [(t.name, t.kind) for t in q.tracks]
    check(names == [(t.name, t.kind) for t in p.tracks], f"la plantilla pone las mismas pistas ({names})")
    check(q.tracks[-1].fx == {"eq": True, "compress": False} and q.tracks[-1].role == "voz",
          "la plantilla lleva los ajustes de audio de cada pista")
    check(q.subtitles.preset == "Mis Shorts" and abs(q.subtitles.size - 7.5) < 1e-9 and q.subtitles.enabled is False
          and q.subtitles.media_id == "", "subtítulos: estilo de la plantilla, apagados hasta elegir narración")
    check(not q.clips, "aplicar la plantilla no añade clips")
    try:
        pt.apply(p, pt.load(path))
        check(False, "no se aplica una plantilla sobre un proyecto con clips")
    except ValueError:
        check(True, "no se aplica una plantilla sobre un proyecto con clips")


def prueba_revision(app, win, ctrl, mid, A, V1, qr_mod):
    p = ctrl.project
    calls = []
    win.engine.play_ranges = lambda ranges: calls.append(ranges)      # sin sonido en la prueba
    win.engine.pause = lambda: None

    # Cortes y propuestas (tiempos del archivo; el corte de 1,5 s hace que lo de después se desplace 0,3 s)
    ctrl.remove_silence([c.id for c in p.clips_on(A.id)], [(1.5, 1.8)])    # aviso dudoso en 1,5 s
    cuttable = {k: v[1] for k, v in voice_cleanup.KINDS.items()}
    items = [{"kind": "silence", "start": 4.0, "end": 4.6, "label": "Silencio largo de 0,6 s", "detail": "Pausa."},
             {"kind": "filler", "start": 9.2, "end": 9.5, "label": "Muletilla «eh»", "detail": "Sobra."},
             {"kind": "silence", "start": 12.0, "end": 12.8, "label": "Silencio largo de 0,8 s", "detail": ""}]
    ctrl.set_suggestions(mid, items, {"silence", "filler"}, cuttable)
    sug = {s.start: s for s in p.suggestions}
    s_sil1, s_fil, s_sil2 = sug[4.0], sug[9.2], sug[12.0]
    check(all(s.status == SUG_PENDING for s in (s_sil1, s_fil, s_sil2)), "tres propuestas pendientes")

    qr = qr_mod(win)
    qr.start()
    kinds = [it.kind for it in qr.queue]
    check(kinds == ["cut", "sug", "sug", "sug"], f"la cola: primero el corte dudoso y luego las propuestas ({kinds})")
    ts = [it.t for it in qr.queue]
    check(ts == sorted(ts), "la cola va en orden de video")
    check(qr.counter.text() == "1 de 4", f"contador «1 de 4» ({qr.counter.text()})")
    check(calls, "al mostrar una propuesta se reproduce su entorno (escucha automática)")
    last = calls[-1][0]
    check(last[0] < qr.queue[0].t < last[1], "la reproducción incluye el momento del aviso (1,5 s antes y después)")

    # 1) O en el corte dudoso → «Está bien así»: su línea roja desaparece (Enter aplicaría su sugerencia)
    n_before = win.timeline.refresh_cut_issues()
    check(n_before == 1, f"un corte dudoso en la línea de tiempo ({n_before})")
    press(app, qr, Qt.Key_O)
    check(win.timeline.cut_issues == [], "O en el corte dudoso: desaparece su línea roja")
    check(len(p.cut_ok) == 1, "el corte queda dado por bueno en el proyecto")
    check(qr.i == 1, "tras decidir, pasa a la siguiente")

    # 2) Enter en la propuesta del silencio → se corta; la duración baja 0,6 s
    d0 = p.duration()
    press(app, qr, Qt.Key_Return)
    check(s_sil1.status == SUG_APPLIED, "Enter aplica el silencio (su estado pasa a aplicada)")
    check(abs((d0 - p.duration()) - 0.6) < 0.01, f"la duración baja 0,6 s ({d0 - p.duration():.3f})")

    # 3) Supr en la muletilla → se ignora
    press(app, qr, Qt.Key_Delete)
    check(s_fil.status == SUG_REJECTED, "Supr rechaza la muletilla")
    check(qr.i == 3, "tras rechazar, pasa a la siguiente (el último silencio)")

    # 4) → salta sin decidir; al final sale el resumen
    press(app, qr, Qt.Key_Right)
    check(qr.finished and s_sil2.status == SUG_PENDING, "→ salta sin decidir y llega al resumen")
    txt = qr.summary.text().lower()
    check("aceptadas 2" in txt and "rechazadas 1" in txt and "sin decidir 1" in txt,
          f"resumen: aceptadas 2, rechazadas 1, sin decidir 1 ({qr.summary.text()!r})")

    # 5) ← vuelve desde el resumen; otra ← a la muletilla ya decidida
    press(app, qr, Qt.Key_Left)
    check(qr.i == 3 and not qr.finished, "← desde el resumen vuelve al último elemento")
    press(app, qr, Qt.Key_Left)
    check(qr.i == 2 and "rechaz" in qr.note.text().lower(), "← vuelve a la muletilla y avisa que ya la decidiste")

    # 6) Enter con el silencio final; Ctrl+Z lo deshace
    press(app, qr, Qt.Key_Right)
    press(app, qr, Qt.Key_Return)
    check(s_sil2.status == SUG_APPLIED and qr.finished, "Enter aplica el último silencio y termina")
    check("aceptadas 3" in qr.summary.text().lower(), "resumen tras la tercera aceptación")
    ctrl.undo_stack.undo()
    # al deshacer se recrean los objetos: se busca la propuesta otra vez por su momento
    s_sil2 = next(s for s in p.suggestions if abs(s.start - 12.0) < 1e-6)
    check(s_sil2.status == SUG_PENDING, "Ctrl+Z devuelve la propuesta a pendiente")

    # 7) P vuelve a escuchar
    n_calls = len(calls)
    qr.i = 0
    qr.finished = False
    press(app, qr, Qt.Key_P)
    check(len(calls) > n_calls, "P vuelve a escuchar")

    # 8) Reabrir: solo queda lo pendiente (el silencio final, otra vez)
    qr.start()
    check(len(qr.queue) == 1 and qr.queue[0].kind == "sug", "al reabrir, solo queda lo pendiente")

    # 9) Esc cierra
    qr.show()
    press(app, qr, Qt.Key_Escape)
    check(not qr.isVisible(), "Esc cierra la revisión")


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.quick_review import QuickReview
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    with open(os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
        words = json.load(f)["words"]
    av = make_av(out, wav)

    prueba_plantillas_sin_ventanas()

    win = MainWindow()
    ctrl = win.ctrl
    mid, A, V1 = new_project(app, ctrl, av, words)
    prueba_revision(app, win, ctrl, mid, A, V1, QuickReview)
    cerrar(win)

    # ------------------------------------------- plantillas con la ventana (formato, subtítulos, sin clips)
    win2 = MainWindow()
    c2 = win2.ctrl
    c2.set_project_format("short")
    c2.set_subtitle_style("prueba", size=7.5, preset="Mis Shorts")
    _m, A2, _v = new_project(app, c2, av, words)
    path = pt.save(c2.project, "Plantilla de prueba con ventana")
    cerrar(win2)

    win3 = MainWindow()
    c3 = win3.ctrl
    c3.undo_stack.setClean()
    c3._media_dirty = False
    win3._fill_templates_menu()
    names = [a.text() for a in win3.menu_templates.actions()]
    check(any(n.startswith("Plantilla de prueba con ventana") for n in names),
          f"«Nuevo desde plantilla» lista la plantilla ({names})")
    win3.new_from_template(path)
    p3 = c3.project
    check(p3.format == "short" and p3.width == 1080 and p3.height == 1920,
          "Nuevo desde plantilla: proyecto de formato Short")
    check(abs(p3.subtitles.size - 7.5) < 1e-9 and p3.subtitles.preset == "Mis Shorts",
          "Nuevo desde plantilla: estilo de subtítulos de la plantilla")
    check(not p3.clips, "Nuevo desde plantilla: no trae clips")
    check(c3.undo_stack.canUndo(), "Nuevo desde plantilla: un paso de Ctrl+Z")
    cerrar(win3)

    print("TODO OK")


if __name__ == "__main__":
    main()
