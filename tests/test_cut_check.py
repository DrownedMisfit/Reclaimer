"""
Prueba de las «líneas rojas» (cortes de audio que pueden estar mal) y de su ajuste a mano:
  · un corte que se come el principio de una palabra → aviso con «Se corta el principio»; un corte limpio → sin aviso;
  · «antes» +delta (recuperar audio) → el aviso desaparece y el proyecto crece delta en TODAS las pistas; el video de
    la misma grabación (otra pista) sigue sincronizado con el audio;
  · «antes» +hueco entero → se unen los clips (vuelve a quedar como antes del corte) y no hay aviso;
  · ✓ «Está bien así» quita el aviso y Ctrl+Z lo devuelve;
  · ◀ ▶ llevan el cabezal al aviso siguiente/anterior y abren el ajuste; la línea roja se dibuja en x del corte;
  · la revisión es rápida con cientos de cortes (sin ventanas);
  · cada aviso propone un arreglo (palabra cortada, pegado, voz en el borde) que nunca pasa del hueco quitado;
  · el panel tiene la lista de cortes (clic = ir ahí), «Aplicar sugerencia» (pasa al siguiente), «Aplicar todas»
    en un solo paso de Deshacer, y el indicador «⚠ N cortes» lo abre.
Sin ventanas visibles. Ejecutar:  .venv/Scripts/python.exe tests/test_cut_check.py <carpeta_salida>
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

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import cut_check  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO, Clip, Project, Track  # noqa: E402


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


def wait(app, ctrl):
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.02)


def synthetic_rules_and_speed():
    """Sin Qt: reglas de los avisos y velocidad con cientos de cortes."""
    p = Project()
    p.tracks = [Track("a", TRACK_AUDIO, "A1")]
    n = 600
    words = []
    for i in range(n):
        base = i * 2.0
        p.clips[f"l{i}"] = Clip(id=f"l{i}", media_id="m", track_id="a", start=base, source_in=base, duration=1.0)
        p.clips[f"r{i}"] = Clip(id=f"r{i}", media_id="m", track_id="a", start=base + 1.0,
                                source_in=base + 1.5, duration=0.5)
        words.append([base + 0.8, base + 1.2, f"w{i}", 1.0])          # cruza el corte (out = base + 1.0)
    p.transcripts = {"m": {"words": words}}
    peaks = np.full(int(n * 2.0 * 1000) + 10, 0.001, dtype=np.float32)
    cut_check.check(p, lambda mid: peaks)                           # primera vez (calienta cachés)
    t0 = time.perf_counter()
    issues = cut_check.check(p, lambda mid: peaks)
    dt = time.perf_counter() - t0
    check(len(issues) == n, f"sintético: los {n} cortes con palabra cortada tienen aviso ({len(issues)})")
    check(dt < 0.1, f"sintético: revisar {n} cortes tarda {dt * 1000:.0f} ms (pedido: menos de 100 ms)")

    # motivos exactos en un caso pequeño
    q = Project()
    q.tracks = [Track("a", TRACK_AUDIO, "A1")]
    q.clips = {"l": Clip(id="l", media_id="m", track_id="a", start=0.0, source_in=0.0, duration=1.2),
               "r": Clip(id="r", media_id="m", track_id="a", start=1.2, source_in=1.8, duration=1.0)}
    q.transcripts = {"m": {"words": [[1.0, 1.5, "hola", 1.0], [1.9, 2.2, "a", 1.0]]}}
    iss = cut_check.check(q, lambda mid: None)
    check(len(iss) == 1 and "Se corta el final de «hola»" in iss[0]["reasons"] and iss[0]["severity"] == "alta",
          f"sintético: corte a mitad de «hola» → «Se corta el final» ({iss[0]['reasons'] if iss else iss})")
    q.transcripts = {"m": {"words": [[0.5, 1.19, "fin", 1.0], [1.81, 2.5, "x", 1.0]]}}
    iss = cut_check.check(q, lambda mid: None)
    check(iss and "Sale demasiado pegado a «fin»" in iss[0]["reasons"]
          and "Entra demasiado pegado a «x»" in iss[0]["reasons"],
          "sintético: palabras pegadas al corte → «demasiado pegado» (sale y entra)")
    q.cut_ok = [cut_check.junction_key(cut_check.junctions(q)[0])]
    check(cut_check.check(q, lambda mid: None) == [], "sintético: un corte dado por bueno no tiene aviso")


def sugerencias_sin_ventanas():
    """Sin Qt: la sugerencia (lado, cuánto y texto) de cada motivo, y que nunca pasa del hueco quitado."""
    def proyecto(words=None, peaks=None):
        q = Project()
        q.tracks = [Track("a", TRACK_AUDIO, "A1")]
        # hueco de 1,2 s a 1,8 s: out = 1,2 y in = 1,8 (0,6 s quitados)
        q.clips = {"l": Clip(id="l", media_id="m", track_id="a", start=0.0, source_in=0.0, duration=1.2),
                   "r": Clip(id="r", media_id="m", track_id="a", start=1.2, source_in=1.8, duration=1.0)}
        q.transcripts = {"m": {"words": words or []}}
        return q

    def sugerencia(words=None, peaks=None):
        q = proyecto(words)
        iss = cut_check.check(q, lambda m: peaks)
        check(len(iss) == 1, f"sugerencias: un aviso ({len(iss)})")
        return iss[0]["fix"], iss[0]["reasons"]

    fix, _ = sugerencia([[1.0, 1.5, "hola", 1.0]])                       # corta el final de «hola»
    check(fix is not None and fix["side"] == "antes" and abs(fix["delta"] - 0.35) < 1e-6
          and fix["text"] == "Recuperar 350 ms antes del corte para no comerse «hola»",
          f"palabra cortada al final: recupera hasta 0,05 s después de la palabra ({fix})")
    fix, _ = sugerencia([[1.75, 2.2, "mundo", 1.0]])                     # corta el principio de «mundo»
    check(fix is not None and fix["side"] == "despues" and abs(fix["delta"] - 0.10) < 1e-6
          and fix["text"] == "Recuperar 100 ms después del corte para no comerse «mundo»",
          f"palabra cortada al principio: recupera hasta 0,05 s antes de la palabra ({fix})")
    fix, _ = sugerencia([[0.5, 1.19, "fin", 1.0]])                       # sale pegado a «fin»
    check(fix is not None and fix["side"] == "antes" and abs(fix["delta"] - 0.04) < 1e-6
          and fix["text"] == "Recuperar 40 ms antes del corte (sale muy pegado a «fin»)",
          f"pegado al salir: recupera 40 ms ({fix})")
    fix, _ = sugerencia([[1.0, 2.0, "largo", 1.0]])                      # quería 0,85 s; solo hay 0,6 s
    check(fix is not None and abs(fix["delta"] - 0.6) < 1e-6 and "600 ms" in fix["text"],
          f"la sugerencia nunca pasa del hueco quitado ({fix})")
    # voz sonando en el borde: el primer silencio hacia dentro del hueco (1,215 s) → 15 ms + 20 ms
    arr = np.full(3000, 0.001, dtype=np.float32)
    arr[1150:1215] = 0.5
    fix, reasons = sugerencia([], arr)
    check("El corte suena con la voz todavía sonando" in reasons and fix is not None and fix["side"] == "antes"
          and abs(fix["delta"] - 0.035) < 1e-6 and "ahí la voz todavía suena" in fix["text"],
          f"voz en el borde: sugiere llegar al primer silencio + 20 ms ({fix})")
    voz_toda = np.full(3000, 0.001, dtype=np.float32)
    voz_toda[1150:1800] = 0.5                                              # voz en todo el hueco: no hay silencio
    fix, _ = sugerencia([[1.0, 1.5, "x", 1.0]], voz_toda)
    check(fix is not None and fix["side"] == "antes" and abs(fix["delta"] - 0.35) < 1e-6,
          "con voz en todo el hueco, la sugerencia sigue siendo la de la palabra")
    fix, reasons = sugerencia([], voz_toda)
    check(fix is None and "El corte suena con la voz todavía sonando" in reasons,
          "sin silencio que buscar en el hueco no hay sugerencia (solo el motivo)")
    check(cut_check.check(proyecto(), None) == [], "sin transcripción ni sonido no hay avisos")


def make_av(out, wav):
    """Una grabación de prueba: video (sintético) + la narración como sonido, como una grabación de OBS."""
    ff = media_tools.ffmpeg()
    p = os.path.join(out, "grabacion_prueba.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=31",
                    "-i", wav, "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", p],
                   check=True)
    return p


def new_project(app, ctrl, av, words):
    """La grabación en la línea de tiempo: su video en V1 y su sonido en A1 (vinculados, como en Reclaimer)."""
    (mid,) = ctrl.import_now([av])
    wait(app, ctrl)
    ctrl.project.transcripts[mid] = {"words": words}
    v1 = next(t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO and t.name == "V1")
    ctrl.add_media([mid], v1.id, 0.0)
    a = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    return mid, a, v1


def clip_at(p, track_id, start, tol=1e-3):
    return next((c for c in p.clips_on(track_id) if abs(c.start - start) <= tol), None)


def cerrar(win):
    """Cierra la ventana sin el diálogo «¿guardar cambios?» (que bloquearía la prueba)."""
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()


def press(app, w, key):
    QTest.keyClick(w, key)
    app.processEvents()


def prueba_panel_sugerencias(app, av, words, MainWindow):
    """Panel de cortes: sugerencia, lista con clic, «Aplicar sugerencia», «Aplicar todas» (un paso) y el indicador."""
    win4 = MainWindow()
    c4, p4 = win4.ctrl, win4.ctrl.project
    _m4, A4, _V4 = new_project(app, c4, av, words)
    c4.remove_silence([c.id for c in p4.clips_on(A4.id)], [(1.5, 1.8)])    # aviso en 1.5 s (bienvenidos)
    c4.remove_silence([c.id for c in p4.clips_on(A4.id)], [(9.2, 9.7)])    # aviso en 9.2 s (lento.)
    tl4 = win4.timeline
    check(tl4.refresh_cut_issues() == 2, "panel: dos cortes dudosos en el proyecto")
    f1, f2 = tl4.cut_issues[0]["fix"], tl4.cut_issues[1]["fix"]
    check(f1 is not None and "bienvenidos" in f1["text"] and f1["side"] == "despues",
          "sugerencia del corte de 1,5 s: recuperar delante de «bienvenidos»")
    check(f2 is not None and f2["text"].startswith("Recuperar"), "sugerencia del corte de 9,2 s")

    # El indicador «⚠ N cortes» abre el panel con la lista (clic en el texto)
    check(not win4.cut_badge.isHidden(), "el indicador «⚠ 2 cortes» está visible")
    QTest.mouseClick(win4.cut_badge, Qt.LeftButton, Qt.NoModifier, QPoint(3, 3))
    panel = win4.cut_fix
    check(panel is not None and not panel.isHidden(), "clic en el indicador abre el panel de cortes")
    check(panel.list.count() == 2, f"la lista del panel tiene los 2 cortes ({panel.list.count()})")
    check(abs(panel.t - 1.5) < 0.01 and panel.counter.text() == "1 de 2",
          f"el panel muestra el primero y el contador «1 de 2» ({panel.counter.text()})")
    check(panel.btn_apply.isEnabled() and "Sugerencia" in panel.sugg.text(),
          "el panel muestra la sugerencia y el botón «Aplicar sugerencia»")

    # clic en el segundo elemento de la lista → cabezal y panel a 9,2 s
    panel.list.itemClicked.emit(panel.list.item(1))
    check(abs(win4.engine.time - tl4.cut_issues[1]["t"]) < 0.01 and abs(panel.t - tl4.cut_issues[1]["t"]) < 0.01,
          f"clic en la lista lleva el cabezal al corte de {tl4.cut_issues[1]['t']:.1f} s")
    check(panel.counter.text() == "2 de 2", "el contador pasa a «2 de 2»")
    panel.list.itemClicked.emit(panel.list.item(0))

    # «◀ ▶» del panel recorren los cortes
    panel.btn_next.click()
    check(panel.counter.text() == "2 de 2", "▶ del panel va al segundo corte")
    panel.btn_prev.click()
    check(panel.counter.text() == "1 de 2", "◀ del panel vuelve al primero")

    # «Aplicar sugerencia» en el de 1,5 s: quita su aviso y pasa solo al siguiente (9,2 s)
    idx0 = c4.undo_stack.index()
    panel.btn_apply.click()
    check(tl4.refresh_cut_issues() == 1, "«Aplicar sugerencia» quita el aviso de 1,5 s")
    check(abs(panel.t - tl4.cut_issues[0]["t"]) < 0.01 and panel.counter.text() == "1 de 1",
          "tras aplicar, el panel pasa solo al siguiente corte dudoso")
    check(c4.undo_stack.index() == idx0 + 1, "«Aplicar sugerencia» es un paso de Deshacer")
    c4.undo_stack.undo()
    check(tl4.refresh_cut_issues() == 2, "Ctrl+Z devuelve el aviso de 1,5 s")

    # «Aplicar todas»: deja 0 avisos y es UN solo paso de Deshacer
    idx0 = c4.undo_stack.index()
    panel.btn_apply_all.click()
    left = tl4.refresh_cut_issues()
    check(left == 0, f"«Aplicar todas las sugerencias» deja 0 avisos ({left})")
    check(c4.undo_stack.index() == idx0 + 1, "«Aplicar todas» ocupa UN solo paso de Deshacer")
    c4.undo_stack.undo()
    check(tl4.refresh_cut_issues() == 2, "Ctrl+Z devuelve los dos avisos de una vez")
    panel.hide()
    cerrar(win4)


def prueba_revision_sugerencia(app, av, words, MainWindow):
    """⚡ Revisión rápida: Enter aplica la sugerencia de un corte; O lo da por bueno."""
    win5 = MainWindow()
    c5, p5 = win5.ctrl, win5.ctrl.project
    _m5, A5, _V5 = new_project(app, c5, av, words)
    c5.remove_silence([c.id for c in p5.clips_on(A5.id)], [(1.5, 1.8)])
    win5.engine.play_ranges = lambda ranges: None
    win5.engine.pause = lambda: None
    from editoria.ui.quick_review import QuickReview
    qr = QuickReview(win5)
    qr.start()
    check(len(qr.queue) == 1 and qr.queue[0].kind == "cut", "revisión: un corte dudoso en la cola")
    check("Sugerencia" in qr.sugg.text() and "bienvenidos" in qr.sugg.text(),
          f"revisión: muestra la sugerencia del corte ({qr.sugg.text()!r})")
    check(qr.btn_accept.text() == "✓ Aplicar sugerencia" and qr.btn_ok.isEnabled(), "revisión: el botón dice «Aplicar»")
    d0 = p5.duration()
    delta = win5.timeline.cut_issues[0]["fix"]["delta"]
    press(app, qr, Qt.Key_Return)
    check(abs((p5.duration() - d0) - delta) < 1e-6,
          f"Enter aplica la sugerencia: el proyecto crece lo que dice ({delta:.3f} s)")
    check(win5.timeline.refresh_cut_issues() == 0, "Enter aplica la sugerencia y el aviso desaparece")
    check(qr.finished, "tras la única decisión, la revisión termina")
    check(len(p5.cut_ok) == 0, "aplicar no marca el corte como «está bien así»")
    c5.undo_stack.undo()
    check(win5.timeline.refresh_cut_issues() == 1, "Ctrl+Z devuelve el corte")

    # O: «Está bien así» sin tocarlo
    qr.start()
    d1 = p5.duration()
    press(app, qr, Qt.Key_O)
    check(len(p5.cut_ok) == 1 and win5.timeline.refresh_cut_issues() == 0,
          "O en un corte dudoso lo da por bueno sin tocarlo")
    check(abs(p5.duration() - d1) < 1e-9, "O no cambia la duración")
    qr.close()
    cerrar(win5)

def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    synthetic_rules_and_speed()
    sugerencias_sin_ventanas()

    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")
    with open(os.path.join(ROOT, "tests", "assets", "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
        words = json.load(f)["words"]
    av = make_av(out, wav)

    # ------------------------------------------------------------ 1) corte limpio → sin aviso; corte malo → aviso
    win = MainWindow()
    ctrl = win.ctrl
    p = ctrl.project
    mid, A, V1 = new_project(app, ctrl, av, words)
    dur0 = p.duration()
    ctrl.ensure_peaks(mid, wait=True)              # (la onda ya no se calcula al importar: se pide al usarla)
    peaks = ctrl.peaks
    check(mid in peaks, "la grabación tiene picos de volumen (análisis hecho)")
    # 4.0–6.9 s del archivo: silencio entre «análisis.» y «El combate»
    ctrl.remove_silence([c.id for c in p.clips_on(A.id)], [(4.0, 6.9)])
    iss = cut_check.check(p, lambda m: peaks.get(m))
    check(not any(abs(i["t"] - 4.0) < 0.01 for i in iss), "corte limpio en un silencio largo → sin aviso")
    # 1.5–1.8 s: se come el principio de «bienvenidos» (empieza en 1.69)
    ctrl.remove_silence([c.id for c in p.clips_on(A.id)], [(1.5, 1.8)])
    iss = cut_check.check(p, lambda m: peaks.get(m))
    mine = [i for i in iss if abs(i["t"] - 1.5) < 0.01]
    check(len(mine) == 1, f"corte en 1.5 s → un aviso ({[round(i['t'], 2) for i in iss]})")
    check("Se corta el principio de «bienvenidos»" in mine[0]["reasons"],
          f"motivo: «Se corta el principio de «bienvenidos»» ({mine[0]['reasons']})")
    dur_cut = p.duration()
    check(abs(dur_cut - (dur0 - 0.3 - 2.9)) < 1e-6, "duración tras los dos cortes")
    check(clip_at(p, V1.id, 1.5) is not None and abs(clip_at(p, V1.id, 1.5).source_in - 1.8) < 1e-6,
          "el video de V1 se cortó en el mismo sitio que el audio")

    # «despues» +0,2 s: recupera 200 ms antes de «bienvenidos» → sin aviso; todo se desplaza 0,2 s en TODAS las pistas
    check(ctrl.adjust_cut(A.id, 1.5, "despues", 0.2), "ajuste «después» +200 ms aplicado")
    iss = cut_check.check(p, lambda m: peaks.get(m))
    check(not any(abs(i["t"] - 1.5) < 0.01 for i in iss), "tras recuperar 200 ms, el aviso desaparece")
    check(abs(p.duration() - (dur_cut + 0.2)) < 1e-6, "el proyecto crece 0,2 s")
    aR, vR = clip_at(p, A.id, 1.5), clip_at(p, V1.id, 1.5)
    check(aR is not None and abs(aR.source_in - 1.6) < 1e-6, "el audio vuelve a empezar 200 ms antes en el archivo")
    check(vR is not None and abs(vR.source_in - aR.source_in) < 1e-6 and abs(vR.start - aR.start) < 1e-6,
          "el video de otra pista sigue sincronizado con el audio")

    # Ctrl+Z: vuelve el aviso y la duración de antes
    ctrl.undo_stack.undo()
    iss = cut_check.check(p, lambda m: peaks.get(m))
    check(any(abs(i["t"] - 1.5) < 0.01 for i in iss), "Ctrl+Z devuelve el aviso")
    check(abs(p.duration() - dur_cut) < 1e-6, "Ctrl+Z devuelve la duración")

    # ✓ Está bien así: quita el aviso; Ctrl+Z lo devuelve
    key = next(i["key"] for i in iss if abs(i["t"] - 1.5) < 0.01)
    ctrl.approve_cut(key)
    iss = cut_check.check(p, lambda m: peaks.get(m))
    check(not any(abs(i["t"] - 1.5) < 0.01 for i in iss), "✓ Está bien así quita el aviso")
    ctrl.undo_stack.undo()
    iss = cut_check.check(p, lambda m: peaks.get(m))
    check(any(abs(i["t"] - 1.5) < 0.01 for i in iss), "Ctrl+Z devuelve el aviso tras «Está bien así»")

    # recuperar más de lo cortado se rechaza y no cambia nada
    before = json.dumps(p.timeline_state(), sort_keys=True)
    r = ctrl.adjust_cut(A.id, 1.5, "antes", 5.0)
    check(r is None and json.dumps(p.timeline_state(), sort_keys=True) == before,
          "recuperar más silencio del cortado se rechaza y no cambia nada")
    cerrar(win)

    # ------------------------------------------------------- 2) «antes» con el hueco entero → vuelve a unirse
    win2 = MainWindow()
    c2, p2 = win2.ctrl, win2.ctrl.project
    _m2, A2, V2 = new_project(app, c2, av, words)
    d0 = p2.duration()
    n_v0 = len(p2.clips_on(V2.id))
    c2.remove_silence([c.id for c in p2.clips_on(A2.id)], [(1.5, 1.8)])
    check(c2.adjust_cut(A2.id, 1.5, "antes", 0.3), "«antes» +300 ms (hueco entero) aplicado")
    check(abs(p2.duration() - d0) < 1e-6, "tras recuperar el hueco entero, la duración es la de antes del corte")
    check(len(p2.clips_on(A2.id)) == 1, "el audio vuelve a ser un solo clip")
    check(len(p2.clips_on(V2.id)) == n_v0, "el video también vuelve a ser un solo clip")
    cerrar(win2)

    # ------------------------------------------------- 3) ◀ ▶, línea roja en pantalla, clic, ajuste y «está bien»
    win3 = MainWindow()
    c3, p3 = win3.ctrl, win3.ctrl.project
    _m3, A3, V3 = new_project(app, c3, av, words)
    c3.remove_silence([c.id for c in p3.clips_on(A3.id)], [(1.5, 1.8)])   # aviso en 1.5 s (bienvenidos)
    c3.remove_silence([c.id for c in p3.clips_on(A3.id)], [(9.2, 9.7)])   # aviso en 9.2 s (corta «lento.»)
    tl = win3.timeline
    n = tl.refresh_cut_issues()
    check(n == 2, f"dos avisos en la línea de tiempo ({n})")
    check(not win3.cut_badge.isHidden() and "2 cortes" in win3.cut_badge.text(), "contador «⚠ 2 cortes» visible")
    ts = sorted(i["t"] for i in tl.cut_issues)
    check(abs(ts[0] - 1.5) < 0.01 and abs(ts[1] - 9.2) < 0.01, f"avisos en 1.5 s y 9.2 s ({ts})")

    win3.engine.user_seek(0.0)
    win3.btn_cut_next.click()
    check(abs(win3.engine.time - 1.5) < 0.01, f"▶ lleva al primer aviso ({win3.engine.time:.3f} s)")
    win3.btn_cut_next.click()
    check(abs(win3.engine.time - 9.2) < 0.01, f"▶ otra vez lleva al segundo ({win3.engine.time:.3f} s)")
    win3.btn_cut_prev.click()
    check(abs(win3.engine.time - 1.5) < 0.01, f"◀ vuelve al anterior ({win3.engine.time:.3f} s)")
    check(win3.cut_fix is not None and win3.cut_fix.track_id == A3.id and abs(win3.cut_fix.t - 1.5) < 0.01,
          "el ajuste se abre en el aviso de 1.5 s")

    # la línea roja se dibuja: píxeles rojos en x del corte, dentro de la pista de audio
    tl.resize(1000, 400)
    tl.pps, tl.scroll = 100.0, 0.0
    tl.set_playhead(0.0)
    img = tl.grab().toImage()
    ai = p3.track_index(A3.id)
    y = int(tl.track_y(ai) + tl.track_h(ai) / 2)
    x = int(round(tl.x_for(1.5)))
    reds = 0
    for dx in range(-1, 2):
        c = img.pixelColor(x + dx, y)
        if c.red() > 190 and c.green() < 120 and c.blue() < 120:
            reds += 1
    check(reds > 0, f"la línea roja se dibuja en el corte de 1.5 s (píxel x={x}, y={y})")

    # clic en la línea roja: lleva el cabezal al corte y abre el ajuste
    win3.engine.user_seek(0.0)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    check(abs(win3.engine.time - 1.5) < 0.01, "clic en la línea roja lleva el cabezal al corte")
    check(abs(win3.cut_fix.t - 1.5) < 0.01, "clic en la línea roja abre el ajuste de ese corte")

    # «Está bien así» desde el panel: quita ese aviso (el contador baja a 1)
    win3.cut_fix.btn_ok.click()
    check(tl.refresh_cut_issues() == 1, "«✓ Está bien así» desde el panel quita ese aviso")
    check("1 corte" in win3.cut_badge.text() and "cortes" not in win3.cut_badge.text(),
          "el contador baja a «⚠ 1 corte»")
    c3.undo_stack.undo()
    check(tl.refresh_cut_issues() == 2, "Ctrl+Z devuelve el aviso")

    # «Devolver todo el silencio» desde el panel: se une y el aviso desaparece
    win3.engine.user_seek(0.0)
    win3.btn_cut_next.click()                      # 1.5 s
    win3.cut_fix.btn_all.click()
    check(tl.refresh_cut_issues() == 1, "«↺ Devolver todo el silencio» quita el aviso de 1.5 s")
    cerrar(win3)

    # ------------------------------------------- 4) sugerencias, panel con lista, aplicar y aplicar todas
    prueba_panel_sugerencias(app, av, words, MainWindow)
    prueba_revision_sugerencia(app, av, words, MainWindow)

    print("TODO OK")


if __name__ == "__main__":
    main()
