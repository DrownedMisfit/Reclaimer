"""
↔ Las columnas de una lista estrechada vuelven a su ancho cuando hay sitio (antes la de «Nombre» de Medios se quedaba
en ~20 px para siempre: «Vi…», «1…» y las miniaturas horizontales recortadas como si fueran verticales).
Ejecutar:  .venv/Scripts/python.exe tests/test_columnas_vuelven.py
"""
from __future__ import annotations

import os
import sys

# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidget, QTreeWidgetItem  # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import responsive as R
    t = QTreeWidget()
    t.setColumnCount(4)
    t.setHeaderLabels(["Nombre", "Duración", "Info", ""])
    t.setIconSize(QSize(64, 36))
    t.setColumnWidth(0, 200)
    t.setColumnWidth(1, 58)
    t.header().setStretchLastSection(False)
    t.header().setSectionResizeMode(2, QHeaderView.Stretch)
    t.header().setSectionResizeMode(3, QHeaderView.Fixed)
    t.setColumnWidth(3, 26)
    g = QTreeWidgetItem(t, ["Videos (8)"])
    for i in range(8):
        QTreeWidgetItem(g, [f"video_{i}.mp4", "01:30", "1920×1080", "⋮"])
    t.resize(600, 400)
    t.show()
    R._vista(t)
    h = t.header()
    for ancho in (180, 600, 160, 700):
        t.resize(ancho, 400)
        for _ in range(5):
            app.processEvents()
        t._sin_barra.encajar()
        app.processEvents()
        n = h.sectionSize(0)
        if ancho >= 600:
            assert n == 200, (ancho, n)
            assert h.sectionResizeMode(2) == QHeaderView.Stretch, h.sectionResizeMode(2)
        else:
            minimo = t.indentation() * 2 + 64 + 56
            assert n >= minimo, (ancho, n, minimo)
        print(f"✓ lista de {ancho} px: «Nombre» mide {n} px")
        if ancho >= 600:                             # (con sitio, las demás tampoco quedan por debajo de lo suyo)
            assert h.sectionSize(1) >= 58 and h.sectionSize(3) >= 26 and h.sectionSize(2) >= 56,                 [h.sectionSize(i) for i in range(4)]

    # ✋ el ancho que pones tú a mano a una columna se respeta (y vuelve a él tras estrecharla)
    def encajar(ancho):
        t.resize(ancho, 400)
        for _ in range(5):
            app.processEvents()
        t._sin_barra.encajar()
        app.processEvents()
    h.resizeSection(0, 260)
    encajar(700)
    assert h.sectionSize(0) == 260, h.sectionSize(0)
    encajar(160)
    assert h.sectionSize(0) < 260, h.sectionSize(0)
    encajar(700)
    assert h.sectionSize(0) == 260, h.sectionSize(0)
    print("✓ «Nombre» a 260 px puesto a mano: se respeta y vuelve a 260 tras estrechar la lista")

    # 📏 columna «según el contenido» con una cabecera más larga que lo de dentro: la cabecera no se corta
    t2 = QTreeWidget()
    t2.setColumnCount(3)
    t2.setHeaderLabels(["Nombre", "Duración total del clip", ""])
    h2 = t2.header()
    h2.setStretchLastSection(False)
    h2.setSectionResizeMode(0, QHeaderView.Stretch)
    h2.setSectionResizeMode(1, QHeaderView.ResizeToContents)
    h2.setSectionResizeMode(2, QHeaderView.Fixed)
    t2.setColumnWidth(2, 26)
    for i in range(5):
        QTreeWidgetItem(t2, [f"video_{i}.mp4", "1:30", "⋮"])
    t2.resize(700, 300)
    t2.show()
    R._vista(t2)
    for ancho in (700, 150, 700):
        t2.resize(ancho, 300)
        for _ in range(5):
            app.processEvents()
        t2._sin_barra.encajar()
        app.processEvents()
    cab = h2.sectionSizeHint(1)
    assert h2.sectionSize(1) >= cab, (h2.sectionSize(1), cab)
    assert h2.sectionSize(2) >= 26 and h2.sectionSize(0) >= 56, [h2.sectionSize(i) for i in range(3)]
    print(f"✓ columna según el contenido: {h2.sectionSize(1)} px ≥ su cabecera ({cab} px); las demás, con lo suyo")
    print("TODO OK")


if __name__ == "__main__":
    main()
