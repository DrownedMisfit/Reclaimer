"""
Prueba de ◈ «el corte de silencios aprende de lo que haces» (el usuario: «que aprenda de mis acciones»), con la voz de
Windows (Sabina, es-MX):
  · se quitan los silencios; tú ALARGAS a mano el final de 3 trozos 0,1 s (se iba el final de la palabra) → aprende
    «+100 ms después» y la siguiente vez deja ese margen de más;
  · deshacer un retoque lo descuenta; partir un trozo no cuenta como retoque;
  · la ventana lo enseña («◈ Usar lo aprendido de tus retoques (+100 ms después …)») y lo aplica.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_silence_learn.py <carpeta_salida>
"""
from __future__ import annotations

import os
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


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import test_silence_voz as T
    from editoria.core import silence as S, silence_learn as SL
    from editoria.core.model import TRACK_AUDIO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.silence_dialog import SilenceDialog
    frases = [T.read(p) for p in T.tts(out)]
    path = os.path.join(out, "voz.wav")
    T.build(frases, -62, path, seed=21)
    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    (mid,) = ctrl.import_now([path])
    while ctrl.analyzing:
        pump(app, 0.1)
    tr = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([mid], tr.id, 0.0)
    p = ctrl.project
    st = dict(next(v for k, v in S.PRESETS.items() if k.startswith("Pausas cortas")), mode="hibrido", clicks=False)
    ids = [c.id for c in p.clips_on(tr.id)]
    regs0 = S.plan(p, p.clips_on(tr.id), p.fps, st)

    # quitar silencios (como «Eliminar» en la ventana) y apuntar los bordes nuevos
    before = SL.snapshot(p, ids)
    ctrl.remove_silence(ids, regs0, "all", False)
    edges = SL.new_edges(ctrl.project, before)
    win.track_silence_edges(edges)
    tails = [e for e in edges if e["side"] == "after"]
    assert len(tails) >= 4, edges
    print(f"✓ al cortar se apuntan {len(edges)} bordes nuevos (los de la voz)")

    # tú alargas el final de 3 trozos 0,1 s (ripple: lo de detrás se mueve)
    for e in tails[:3]:
        c = ctrl.project.clips[e["clip"]]
        ctrl.ripple_trim(c.id, "right", c.end + 0.1)
    pump(app, 2.0)                                 # (se mira con calma: 1,5 s después del último cambio)
    lr = SL.learned()
    assert lr["n_after"] == 3 and abs(lr["after"] - 0.1) < 0.01, lr
    assert SL.describe(lr) == "+100 ms después", SL.describe(lr)
    print(f"✓ alargaste 3 finales 0,1 s → aprende «{SL.describe(lr)}»")

    # deshacer un retoque lo descuenta
    ctrl.undo_stack.undo()
    pump(app, 2.0)
    lr2 = SL.learned()
    assert lr2["n_after"] == 2 and lr2["after"] == 0.0, lr2
    ctrl.undo_stack.redo()
    pump(app, 2.0)
    assert SL.learned()["n_after"] == 3
    print("✓ deshacer un retoque lo descuenta (y rehacerlo lo vuelve a contar)")

    # partir un trozo cerca de su final no cuenta como retoque
    c = ctrl.project.clips[tails[3]["clip"]]
    ctrl.split(c.end - 0.2, [c.id])
    pump(app, 2.0)
    assert SL.learned()["n_after"] == 3, SL.learned()
    print("✓ partir un trozo no cuenta como retoque")

    # la siguiente vez: ese margen de más
    from editoria.core.controller import ProjectController
    c2 = ProjectController()                       # (sobre la grabación sin cortar)
    (m2,) = c2.import_now([path])
    while c2.analyzing:
        pump(app, 0.1)
    t2 = next(t for t in c2.project.tracks if t.kind == TRACK_AUDIO)
    c2.add_media([m2], t2.id, 0.0)
    cl2 = c2.project.clips_on(t2.id)
    regs_l = S.plan(c2.project, cl2, c2.project.fps, dict(st, learned={"before": 0.0, "after": 0.1}))
    regs_n = S.plan(c2.project, cl2, c2.project.fps, st)
    tot_l, tot_n = sum(b - a for a, b in regs_l), sum(b - a for a, b in regs_n)
    assert tot_l < tot_n, (tot_l, tot_n)
    print(f"✓ con lo aprendido, el siguiente corte deja más margen tras cada frase ({tot_n:.2f} → {tot_l:.2f} s quitados)")

    # la ventana
    cid = ctrl.project.clips_on(tr.id)[0].id
    dlg = SilenceDialog(win, [cid])
    assert dlg.learn_cb.isEnabled() and dlg.learn_cb.isChecked() and "+100 ms después" in dlg.learn_cb.text()
    assert dlg.settings()["learned"]["after"] > 0.09
    print(f"✓ la ventana lo enseña: «{dlg.learn_cb.text()}» y lo aplica")
    dlg.reject()
    SL.reset()
    assert SL.learned()["n_after"] == 0
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
