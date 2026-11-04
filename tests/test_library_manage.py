"""
Prueba de organizar Medios: las imágenes de internet que marcas ✓ se guardan con el nombre de lo que buscaste y un
número (1, 2, 3…) en su carpeta, y en Medios aparecen en «Internet ▸ <búsqueda>»; mover (menú y arrastrando sobre una
carpeta), carpeta nueva, Supr = quitar de la biblioteca, y «Eliminar el archivo» a la Papelera (recuperable).
Usa una carpeta de datos TEMPORAL; no toca tus archivos.
Ejecutar:  .venv/Scripts/python.exe tests/test_library_manage.py <carpeta_salida>
"""
from __future__ import annotations

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

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import web_images as WI
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    # La carpeta de imágenes de internet, dentro de la carpeta temporal (no la tuya)
    base = os.path.join(out, "imagenes_internet")
    os.makedirs(base, exist_ok=True)
    WI.folder = lambda: base

    def fake_fetch(url, dest, timeout=30, limit=0):
        img = QImage(64, 48, QImage.Format_RGB888)
        img.fill(QColor("#336699"))
        img.save(dest, "JPG")
        return dest
    WI.fetch = fake_fetch

    # 1) Nombre de lo que buscaste + número, en su carpeta
    items = [{"id": f"i{k}", "url": f"https://x/{k}.jpg", "title": f"foto {k}", "creator": "a", "license": "by",
              "license_text": "CC BY", "page": "p", "attribution": ""} for k in range(3)]
    paths = [WI.download(it, "master chief halo") for it in items]
    names = [os.path.relpath(p, base) for p in paths]
    assert names == [os.path.join("master chief halo", f"master chief halo {k}.jpg") for k in (1, 2, 3)], names
    os.remove(paths[1])                                  # aunque borres el 2, el siguiente es el 4
    p4 = WI.download(dict(items[0], id="i9"), "master chief halo")
    assert p4.endswith("master chief halo 4.jpg"), p4
    print("✓ ✓ = se guarda como «master chief halo 1.jpg», «… 2.jpg»… en su carpeta (nunca se repite el número)")

    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    ctrl = win.ctrl
    ids = ctrl.import_paths([paths[0], paths[2], p4])
    while ctrl.analyzing:
        pump(app, 0.05)
    ctrl.set_media_props(ids, category="Internet/master chief halo")
    win.show_panel(win.library)
    pump(app, 0.2)
    tree = win.library.tree

    def folder_items():
        out_ = {}
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for k in range(top.childCount()):
                ch = top.child(k)
                if ch.childCount():
                    out_[ch.text(0)] = [ch.child(j).data(0, Qt.UserRole) for j in range(ch.childCount())]
        return out_
    fi = folder_items()
    key = next(k for k in fi if "master chief halo" in k)
    assert len(fi[key]) == 3, fi
    print(f"✓ en Medios: «Internet ▸ {key.strip()}»")

    # 2) Mover: menú (carpeta nueva) y arrastrando sobre una carpeta
    win.library._move_to([ids[0]], "Internet/arbiter")
    assert ctrl.project.media[ids[0]].category == "Internet/arbiter"
    tree.move_requested.emit([ids[1]], "Internet/arbiter")
    assert ctrl.project.media[ids[1]].category == "Internet/arbiter"
    pump(app, 0.2)
    fi = folder_items()
    assert any("arbiter" in k and len(v) == 2 for k, v in fi.items()), fi
    print("✓ mover a otra carpeta (menú «📂 Mover a…» y arrastrando sobre la carpeta)")

    # 3) Supr = quitar de la biblioteca (el archivo sigue en el disco)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    tree.clearSelection()
    win.library.select_media(ids[2])
    pump(app, 0.1)
    QTest.keyClick(tree, Qt.Key_Delete)
    assert ids[2] not in ctrl.project.media and os.path.exists(p4)
    print("✓ Supr quita el archivo de Medios (sin borrarlo del disco)")

    # 4) Eliminar el archivo → Papelera de Windows (y no si se está usando)
    ctrl.add_media([ids[0]], None, 0.0)
    win.library._trash([ids[0]])
    assert ids[0] in ctrl.project.media and os.path.exists(paths[0]), "si está en la línea de tiempo, no se borra"
    win.library._trash([ids[1]])
    assert ids[1] not in ctrl.project.media and not os.path.exists(paths[2])
    print("✓ «🗑 Eliminar el archivo» lo manda a la Papelera (recuperable); si se usa en la línea de tiempo, avisa")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    st = QSettings("EditorIA", "EditorIA")
    for k in ("ventana/paneles", "guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK")


if __name__ == "__main__":
    main()
