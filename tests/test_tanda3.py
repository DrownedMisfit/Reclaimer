"""
Prueba de la tanda 3: historial de deshacer comprimido (y correcto) y la ventana «✧ Caché y diagnóstico».
Usa una carpeta de datos TEMPORAL: no toca la caché real del usuario.
Ejecutar:  .venv/Scripts/python.exe tests/test_tanda3.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core.paths import app_data_dir
    assert str(app_data_dir()).startswith(_TMP), app_data_dir()
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_VIDEO, Clip, new_id

    # --- historial comprimido: proyecto grande, muchos cambios
    ctrl = ProjectController()
    p = ctrl.project
    vt = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    for i in range(2000):
        c = Clip(new_id(), "m", vt.id, i * 2.0, 0.0, 2.0, zoom_kf=[{"t": 0.5, "z": 1.2, "x": 0.5, "y": 0.5}])
        p.clips[c.id] = c
    ids = list(p.clips)
    states = [p.timeline_state()]
    for k in range(40):
        ctrl.set_clip_props([ids[k * 7]], f"cambio {k}", note=f"nota {k}")
        states.append(p.timeline_state())
    steps, size = ctrl.history_size()
    assert steps == 40 and size < 40 * 2 * 120_000, (steps, size)     # comprimido y sin duplicar
    for k in range(40, 0, -1):          # deshacer todo: cada paso vuelve exactamente al estado anterior
        ctrl.undo_stack.undo()
        assert p.timeline_state() == states[k - 1], k
    for k in range(1, 41):
        ctrl.undo_stack.redo()
        assert p.timeline_state() == states[k], k
    ctrl.set_zoom_at(ids[0], 0.5, 1.4, 0.5, 0.5)
    ctrl.set_zoom_at(ids[0], 0.5, 1.6, 0.5, 0.5)       # arrastrar = un solo paso (se juntan)
    assert ctrl.undo_stack.count() == 41
    ctrl.undo_stack.undo()
    assert p.timeline_state() == states[40]
    print(f"✓ historial: 40 pasos de un proyecto de 2000 clips ocupan {size / 1024:.0f} KB (comprimido); "
          "deshacer y rehacer devuelven exactamente cada estado")

    # --- caché: archivos de prueba en la carpeta temporal
    base = app_data_dir() / "cache"
    for sub, n in (("proxies", 3), ("formas_de_onda", 5), ("huellas_a_fondo", 2), ("recortes", 2)):
        (base / sub).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (base / sub / f"x{i}.bin").write_bytes(b"0" * 100_000)
    from editoria.core import diagnostics as D
    entries = {e["key"]: e for e in D.scan()}
    assert entries["proxies"]["bytes"] == 300_000 and entries["recortes"]["can"] == "no"
    try:
        D.clear("recortes")
        raise AssertionError("no debía poder borrarse")
    except ValueError:
        pass
    assert D.clear("formas_de_onda") == 500_000
    print("✓ caché: mide cada parte; lo que usan tus miniaturas no se puede borrar")

    # --- la ventana
    from editoria.ui.main_window import MainWindow
    from editoria.ui.diagnostics_dialog import DiagnosticsDialog
    win = MainWindow()
    win.show()
    dlg = DiagnosticsDialog(win)
    dlg.show()
    t0 = time.time()
    while (not dlg.entries or not dlg.rows) and time.time() - t0 < 60:
        pump(app, 0.1)
    assert dlg.entries and dlg.rows
    names = [k for k, _v in dlg.rows]
    assert "FFmpeg" in names and "Historial de deshacer" in names and "Exportar con la tarjeta AMD" in names
    dlg.b_safe.click()
    pump(app, 0.5)
    left = {e["key"]: e for e in D.scan()}
    assert left["proxies"]["bytes"] == 0, left["proxies"]
    assert left["huellas_a_fondo"]["bytes"] == 200_000 and left["recortes"]["bytes"] == 200_000
    dlg.clear_one("huellas_a_fondo", ask=False)
    assert {e["key"]: e for e in D.scan()}["huellas_a_fondo"]["bytes"] == 0
    dlg.copy_report()
    assert "FFmpeg:" in QGuiApplication.clipboard().text()
    dlg.tabs.setCurrentIndex(0)
    dlg.grab().save(os.path.join(out, "cache.png"))
    dlg.tabs.setCurrentIndex(1)
    dlg.grab().save(os.path.join(out, "diagnostico.png"))
    print("✓ ventana: «Borrar todo lo que se rehace solo» no toca lo demás; lo del aviso se borra aparte; "
          "«Copiar informe» funciona")
    dlg.close()
    win.analyzer.shutdown()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    print("TODO OK")


if __name__ == "__main__":
    main()
