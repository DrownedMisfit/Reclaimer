"""
Prueba del guardado como en Resolve: guardado en vivo (cada cambio se guarda solo), autoguardado si el proyecto no
tiene nombre, copias de seguridad periódicas (se conservan las últimas N) y «⟲ Abrir esta copia» (como copia).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_saving.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
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
    keep = {k: st.value(k) for k in ("guardado/vivo", "guardado/copias_min", "guardado/conservar")}
    for k in keep:
        st.remove(k)
    app = QApplication(sys.argv)
    from editoria.core.paths import autosave_path
    from editoria.ui.main_window import MainWindow
    from editoria.ui.saving import SaveSettingsDialog, backups_of
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    ctrl, sv = win.ctrl, win.saving
    path = os.path.join(out, "mi proyecto.eia")
    if os.path.exists(path):
        os.remove(path)

    # 1) Proyecto sin nombre: el cambio va al autoguardado
    ctrl.add_marker(1.0, "sin nombre")
    pump(app, 3.0)
    assert os.path.exists(autosave_path()) and "sin nombre" in open(autosave_path(), encoding="utf-8").read()
    assert "Ctrl+S" in sv.label.text(), sv.label.text()
    print(f"✓ sin nombre: se autoguarda solo («{sv.label.text()}»)")

    # 2) Con nombre: guardado en vivo (sin Ctrl+S)
    ctrl.save(path)
    ctrl.add_marker(2.0, "en vivo")
    assert ctrl.dirty
    pump(app, 3.0)
    data = json.load(open(path, encoding="utf-8"))
    assert any(m.get("label") == "en vivo" for m in data.get("markers", [])) and not ctrl.dirty
    assert "Guardado" in sv.label.text() and "en vivo" in sv.label.text(), sv.label.text()
    print(f"✓ guardado en vivo: el cambio ya está en el archivo sin pulsar Ctrl+S («{sv.label.text()}»)")

    # 3) Apagado: no se guarda solo
    st.setValue("guardado/vivo", "false")
    sv.apply_settings()
    ctrl.add_marker(3.0, "no vivo")
    pump(app, 3.0)
    assert ctrl.dirty and "no vivo" not in open(path, encoding="utf-8").read()
    st.setValue("guardado/vivo", "true")
    sv.apply_settings()
    ctrl.save(path)
    print("✓ con el guardado en vivo apagado, no se guarda solo")

    # 4) Copias de seguridad periódicas: solo si cambió algo; se conservan las últimas N
    st.setValue("guardado/conservar", 3)
    for k in range(5):
        ctrl.add_marker(4.0 + k, f"copia {k}")
        sv._changed_since_backup = True
        sv.periodic_backup()
        time.sleep(1.05)                 # copias con distinta hora
    sv.periodic_backup()                 # sin cambios: no hace otra
    bk = backups_of(path)
    assert len(bk) == 3, bk
    assert "copia 4" in open(bk[0], encoding="utf-8").read()
    print(f"✓ copias de seguridad con fecha y hora, solo si hubo cambios; se conservan las últimas 3 ({len(bk)})")

    # 5) ⟲ Abrir una copia (como copia: no pisa el original)
    dlg = SaveSettingsDialog(sv, win)
    assert dlg.list.count() == 3
    dlg.list.setCurrentRow(2)            # la más antigua
    win._confirm_discard = lambda: True
    dlg._open()
    assert ctrl.path is None and any(m.label == "copia 2" for m in ctrl.project.markers) and \
        not any(m.label == "copia 4" for m in ctrl.project.markers)
    print("✓ «⟲ Abrir esta copia»: abre la versión elegida como copia (al guardar pregunta dónde)")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    for k in ("ventana/paneles", "guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK")


if __name__ == "__main__":
    main()
