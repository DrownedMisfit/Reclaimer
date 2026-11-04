"""
Prueba del trabajo pesado de la IA SIN congelar el editor: el indicador naranja encima del visor (qué hace, % y ■),
el panel «◈ Tareas de la IA» (se abre al pulsar el indicador, se puede soltar y volver a su sitio), «Detener»
sin cierres inesperados, y «Completa / Media / Un cuarto» (los trabajos descansan para no quitar recursos).
Usa una carpeta de datos TEMPORAL y un modelo simulado (no descarga nada).
Ejecutar:  .venv/Scripts/python.exe tests/test_task_window.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class SlowEncoder:
    def encode(self, imgs):
        time.sleep(0.3)
        v = np.ones((len(imgs), 512), np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    saved_lvl = st.value("ia/recursos")
    app = QApplication(sys.argv)
    from editoria.ai import embeddings
    from editoria.core import media as media_tools
    from editoria.ui import jobs, task_window
    from editoria.ui.example_dialog import ExampleDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    jobs.set_resource_level("full")

    def slow_get(name, progress=None):
        for i in range(30):                   # «cargando el modelo» 3 s
            if progress:
                progress(i / 30, "Cargando…")
            time.sleep(0.1)
        return SlowEncoder()
    embeddings.get = slow_get
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=640x360:r=30:d=10", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl = win.ctrl
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        app.processEvents()
        time.sleep(0.05)
    assert ids[0] not in ctrl.clip_vecs, "el video NO está analizado (como en tu caso)"
    chip = win.preview.task_chip
    assert not chip.isVisible(), "sin trabajos, el indicador no se ve"

    # 1) Ejemplo con recuadro: el editor sigue respondiendo; indicador naranja con %
    dlg = ExampleDialog(ctrl, ids[0], 4.0, 0.0, 9.0, "jefe maestro", win)
    dlg._mtimer.stop()                    # («◈ Dónde sale» se prueba en test_example_match)
    dlg.show()
    t0 = time.time()
    while dlg.view.img is None and time.time() - t0 < 10:
        app.processEvents()
    dlg.view.rect_n = QRectF(0.3, 0.2, 0.3, 0.5)
    t1 = time.time()
    dlg._done(True)
    assert time.time() - t1 < 0.3, "el botón no debe esperar al trabajo"
    beats, pcts = [], []
    while time.time() - t1 < 1.5:
        app.processEvents()
        beats.append(time.time())
        pcts.append(chip.bar.value())
        time.sleep(0.02)
    gaps = np.diff(beats)
    assert chip.isVisible() and "Preparando" in chip.label.text() and "%" in chip.label.text(), chip.label.text()
    assert gaps.max() < 0.3, f"el editor se congeló {gaps.max():.2f} s"
    win.grab().save(os.path.join(out, "indicador.png"))
    print(f"✓ indicador naranja encima del visor: «{chip.label.text()}»; el editor respondió todo el rato "
          f"(pausa máxima {gaps.max() * 1000:.0f} ms)")

    # 2) Clic en el indicador → panel al lado; se puede soltar y volver a su sitio
    QTest.mouseClick(chip, Qt.LeftButton)
    app.processEvents()
    dock = win.docks["tasks"]
    assert dock.isVisible() and not dock.isFloating() and win.tasks_panel._rows, "el panel muestra la tarea"
    dock.setFloating(True)
    dock.move(100, 100)
    app.processEvents()
    assert dock.isFloating()
    dock.setFloating(False)
    assert not dock.isFloating() and win.dockWidgetArea(dock) == Qt.RightDockWidgetArea
    win.grab().save(os.path.join(out, "panel_tareas.png"))
    print("✓ clic en el indicador → panel «◈ Tareas de la IA» al lado; se suelta y vuelve a su sitio")

    # 3) ■ Detener: nada guardado, sin cierre inesperado
    task_window.manager().stop()
    app.processEvents()
    assert not dlg.examples and "Detenido" in dlg.msg.text() and dlg.b_yes.isEnabled(), dlg.msg.text()
    # tu trabajo se detuvo (puede quedar alguno automático, p. ej. las miniaturas de la línea de tiempo)
    assert not [t for t in task_window.manager().tasks if not t.auto]
    assert not chip.isVisible() or all(t.auto for t in task_window.manager().tasks)
    t0 = time.time()
    while task_window._ALIVE and time.time() - t0 < 10:
        app.processEvents()
        time.sleep(0.05)
    assert not task_window._ALIVE
    print("✓ ■ Detener: se corta al momento, no se guarda nada y el trabajo acaba solo sin cierre inesperado")

    # 4) Dejarlo terminar: el ejemplo se guarda
    dlg.view.rect_n = QRectF(0.3, 0.2, 0.3, 0.5)
    dlg._done(True)
    t0 = time.time()
    while not dlg.examples and time.time() - t0 < 15:
        app.processEvents()
        time.sleep(0.02)
    assert len(dlg.examples) == 1 and len(dlg.examples[0]["vec"]) == 512, dlg.msg.text()
    print("✓ dejándolo terminar, el ejemplo se guarda")

    # 5) Completa / Media / Un cuarto: el mismo trabajo tarda más y deja libre el PC
    def timed(level):
        jobs.set_resource_level(level)

        def work(progress, cancelled):
            for i in range(8):
                x = time.perf_counter()
                while time.perf_counter() - x < 0.05:   # «trabajo»
                    pass
                progress(i / 8, "paso")
            return 1
        t0 = time.time()
        ok, _r = task_window.run_task(win, "prueba", work)
        return time.time() - t0
    full, quarter = timed("full"), timed("quarter")
    assert quarter > full * 2.5, (full, quarter)
    jobs.set_resource_level("full")
    print(f"✓ «Un cuarto»: el mismo trabajo tarda {quarter:.1f} s en vez de {full:.1f} s (descansa para no "
          "quitarle recursos al editor)")

    dlg.reject()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    if saved_lvl is None:
        st.remove("ia/recursos")
    else:
        st.setValue("ia/recursos", saved_lvl)
    for k in ("ventana/paneles", "guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK")


if __name__ == "__main__":
    main()
