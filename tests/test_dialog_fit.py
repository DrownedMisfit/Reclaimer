"""
Prueba de que ninguna ventana se sale de la pantalla (el usuario: «este botón nunca debería estar fuera del encuadre; si
sobra espacio hay que quitar lo vacío»):
  · una ventana cualquiera más alta que la pantalla se encoge y se mete dentro: su botón de abajo se ve;
  · «Crear edit musical»: el botón «Crear edit» dentro de la pantalla; la lista de clips tan alta como sus filas (sin
    hueco vacío), sin barra lateral y con los nombres largos recortados por el medio; al cerrar una sección, la ventana
    encoge.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_dialog_fit.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QPushButton, QScrollArea,  # noqa: E402
                               QVBoxLayout)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def inside(scr, w) -> bool:
    return scr.contains(w.mapToGlobal(w.rect().topLeft())) and scr.contains(w.mapToGlobal(w.rect().bottomRight()))


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    scr = app.primaryScreen().availableGeometry()

    # 1) una ventana cualquiera, más alta que la pantalla
    d = QDialog()
    lay = QVBoxLayout(d)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setWidget(QLabel("\n".join(f"línea {i}" for i in range(200))))
    lay.addWidget(sc, 1)
    ok = QPushButton("Aceptar")
    lay.addWidget(ok)
    d.resize(600, scr.height() + 600)
    d.move(scr.left() + 50, scr.top() + 300)
    d.show()
    pump(app, 0.3)
    assert d.frameGeometry().height() <= scr.height() and inside(scr, ok), (d.frameGeometry(), scr)
    print(f"✓ una ventana de {scr.height() + 600} px en una pantalla de {scr.height()}: encogida a "
          f"{d.frameGeometry().height()} px y dentro; su botón de abajo se ve")
    d.close()

    # 1b) una ventana con un elemento propio llamado «screen» (como «Elegir tramos»): sin errores
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *a: errors.append(a[1])
    d2 = QDialog()
    d2.screen = QLabel("vista previa", d2)          # (tapa QWidget.screen(): daba «'QLabel' object is not callable»)
    QVBoxLayout(d2).addWidget(d2.screen)
    d2.resize(500, scr.height() + 300)
    d2.show()
    pump(app, 0.3)
    sys.excepthook = old_hook
    assert not errors and d2.frameGeometry().height() <= scr.height(), (errors, d2.frameGeometry())
    print("✓ una ventana con su propio «screen» (como «Elegir tramos») se ajusta sin ningún error")
    d2.close()

    # 2) «Crear edit musical»
    from editoria.core import media as M
    from editoria.core.controller import ProjectController
    from editoria.ui.edit_dialog import EditDialog
    paths = []
    for n in ("Video_de_prueba_con_un_nombre_bastante_largo_para_la_ventana_001_1080p.mp4",
              "Otro_video_de_prueba-CON-UN-NOMBRE-LARGUISIMO-QUE-NO-CABE-EN-LA-VENTANA-NI-DE-BROMA-"
              "Parte-200_001_1080p.mp4"):
        p = os.path.join(out, n)
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=2",
                        "-c:v", "libx264", "-preset", "ultrafast", p], check=True)
        paths.append(p)
    ctrl = ProjectController()
    ctrl.import_now(paths)
    while ctrl.analyzing:
        pump(app, 0.1)
    e = EditDialog(ctrl)
    for t in ("Canción y estilo", "Efectos", "Clips", "Frases"):
        e.sections[t].set_open(True)
    e.show()
    pump(app, 0.5)
    assert inside(scr, e.go) and inside(scr, e.cancel_btn), (e.frameGeometry(), scr)
    print("✓ «Crear edit musical» con todo abierto: «Crear edit» y «Cerrar» dentro de la pantalla")
    row = e.clips.sizeHintForRow(0)
    assert e.clips.height() <= row * 2 + 4 * e.clips.frameWidth() + 20, (e.clips.height(), row)
    assert not e.clips.horizontalScrollBar().isVisible()
    print(f"✓ la lista de 2 clips mide {e.clips.height()} px (antes, 240 fijos con hueco vacío); sin barra lateral")
    for t in ("Efectos", "Frases"):
        e.sections[t].set_open(False)
    pump(app, 0.4)
    h_closed = e.height()
    e.sections["Efectos"].set_open(True)
    pump(app, 0.4)
    assert e.height() > h_closed or e.frameGeometry().height() >= scr.height() - 40, (h_closed, e.height())
    e.sections["Efectos"].set_open(False)
    pump(app, 0.4)
    assert abs(e.height() - h_closed) <= 4 and inside(scr, e.go), (h_closed, e.height())
    assert not e.sections_area.horizontalScrollBar().isVisible()
    print(f"✓ al cerrar secciones la ventana encoge ({h_closed} px) y al abrirlas crece; nunca fuera de la pantalla")
    e.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
