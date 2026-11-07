"""
Prueba de la REVISIÓN antes de exportar (⚕). Sin ventanas (offscreen), sin red:
  · un corte de audio dudoso y un archivo que falta → la revisión los lista;
  · «Ir» lleva el cabezal al momento del aviso y selecciona su clip;
  · exportar con avisos importantes abre la revisión primero (el diálogo se parchea para no bloquear);
  · con «No volver a mostrar» marcada se guarda y ya no sale; sin avisos importantes exporta directo.
Ejecutar:  PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_audit_export.py _pruebas_tmp/test_audit_export
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.media import PEAK_RATE  # noqa: E402
from editoria.core.model import Clip, MediaItem  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


class _Engine:
    def __init__(self):
        self.seeks = []

    def pause(self):
        pass

    def user_seek(self, t):
        self.seeks.append(t)


class _Timeline:
    def __init__(self):
        self.sel = None

    def set_selection(self, ids):
        self.sel = list(ids)


def _preparar(win, carpeta):
    """Proyecto con: un clip de un archivo que falta, y dos trozos de narración pegados donde el primero acaba
    con la voz todavía sonando (corte dudoso)."""
    ctrl = win.ctrl
    p = ctrl.project
    pista_v = next(t for t in p.tracks if t.kind == "video")
    pista_a = next(t for t in p.tracks if t.kind == "audio")
    p.media["falta"] = MediaItem(id="falta", path=os.path.join(carpeta, "no_existe.mp4"), kind="video",
                                 name="clip_perdido.mp4", duration=10.0, width=1920, height=1080, probed=True)
    p.clips["cv1"] = Clip("cv1", "falta", pista_v.id, 0.0, 0.0, 10.0)
    ctrl.missing.add("falta")
    p.media["nar"] = MediaItem(id="nar", path=os.path.join(carpeta, "narracion.wav"), kind="audio",
                               name="narracion.wav", duration=20.0, has_audio=True, probed=True)
    p.clips["ca1"] = Clip("ca1", "nar", pista_a.id, 0.0, 0.0, 5.0)
    p.clips["ca2"] = Clip("ca2", "nar", pista_a.id, 5.0, 5.5, 5.0)     # se quitó 0.5 s de silencio en 5.0–5.5
    ruido = np.full(20 * PEAK_RATE, 0.01, dtype=np.float32)
    ruido[:int(5.0 * PEAK_RATE)] = 0.5                                  # voz hasta 5.0 s
    ruido[int(5.5 * PEAK_RATE):int(10.5 * PEAK_RATE)] = 0.5             # voz desde 5.5 s
    ctrl.peaks["nar"] = ruido


def prueba_lista_e_ir(app, win):
    from editoria.ui.audit_dialog import AuditDialog
    eng, tl = _Engine(), _Timeline()
    dlg = AuditDialog(win.ctrl, eng, tl, None, before_export=False)
    mensajes = [dlg.tree.topLevelItem(i).text(2) for i in range(dlg.tree.topLevelItemCount())]
    assert any("Falta el archivo" in m for m in mensajes), mensajes
    assert any("Corte de audio dudoso" in m for m in mensajes), mensajes
    print("✓ La revisión lista el archivo que falta y el corte de audio dudoso")

    fila = next(i for i in range(dlg.tree.topLevelItemCount())
                if dlg.tree.topLevelItem(i).text(2) == "Corte de audio dudoso")
    dlg.tree.itemWidget(dlg.tree.topLevelItem(fila), 4).click()          # botón «Ir»
    assert eng.seeks and abs(eng.seeks[-1] - 5.0) < 0.05, eng.seeks
    assert tl.sel == ["ca2"], tl.sel
    fila = next(i for i in range(dlg.tree.topLevelItemCount())
                if dlg.tree.topLevelItem(i).text(2).startswith("Falta el archivo"))
    dlg.tree.itemWidget(dlg.tree.topLevelItem(fila), 4).click()
    assert eng.seeks[-1] == 0.0 and tl.sel == ["cv1"], (eng.seeks, tl.sel)
    print("✓ «Ir» mueve el cabezal al momento del aviso (5.0 s / 0.0 s) y selecciona su clip")
    dlg.close()


def prueba_exportar(app, win):
    from editoria.ui import audit_dialog as AD
    from editoria.ui.export_dialog import ExportDialog
    st = QSettings("EditorIA", "EditorIA")
    n = {"revision": 0, "exporta": 0}

    def revision_cancel(self):
        n["revision"] += 1
        return 0                                                   # «Revisar»: no exporta

    def revision_igual(self):
        n["revision"] += 1
        return 1                                                   # «Exportar igual»

    def revision_no_mostrar(self):
        n["revision"] += 1
        self.no_mostrar.setChecked(True)
        return 1

    def exporta(self):
        n["exporta"] += 1
        return 0

    st.setValue("exportar/revisar_antes", "true")
    with mock.patch.object(AD.AuditDialog, "exec", revision_cancel), \
            mock.patch.object(ExportDialog, "exec", exporta):
        win.export()
    assert n == {"revision": 1, "exporta": 0}, n
    with mock.patch.object(AD.AuditDialog, "exec", revision_igual), \
            mock.patch.object(ExportDialog, "exec", exporta):
        win.export()
    assert n == {"revision": 2, "exporta": 1}, n
    with mock.patch.object(AD.AuditDialog, "exec", revision_no_mostrar), \
            mock.patch.object(ExportDialog, "exec", exporta):
        win.export()
    assert n == {"revision": 3, "exporta": 2}, n
    assert str(st.value("exportar/revisar_antes")) == "false"
    print("✓ Con avisos: sale la revisión primero; «Revisar» no exporta; «Exportar igual» sí")
    print("✓ «No volver a mostrar» se guarda (exportar/revisar_antes = false)")

    with mock.patch.object(AD.AuditDialog, "exec", revision_igual), \
            mock.patch.object(ExportDialog, "exec", exporta):
        win.export()                                               # con la casilla desactivada: no sale
    assert n == {"revision": 3, "exporta": 3}, n
    st.setValue("exportar/revisar_antes", "true")
    from editoria.ai import audit as AU
    with mock.patch.object(AD.AuditDialog, "exec", revision_igual), \
            mock.patch.object(ExportDialog, "exec", exporta), \
            mock.patch.object(AU, "run_audit", return_value=([], 10)):
        win.export()                                               # sin avisos: exporta directo
    assert n == {"revision": 3, "exporta": 4}, n
    print("✓ Con la casilla desactivada no sale; sin avisos importantes exporta directo")
    st.remove("exportar/revisar_antes")


def prueba_menu(win):
    from PySide6.QtGui import QAction
    textos = [a.text() for a in win.findChildren(QAction)]
    assert any(t.startswith("📝 Descripción para YouTube") for t in textos), "falta la entrada del menú"
    print("✓ Menú: «📝 Descripción para YouTube (capítulos, créditos…)»")


def main():
    carpeta = sys.argv[1]
    os.makedirs(carpeta, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    try:
        _preparar(win, carpeta)
        prueba_menu(win)
        prueba_lista_e_ir(app, win)
        prueba_exportar(app, win)
    finally:
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
