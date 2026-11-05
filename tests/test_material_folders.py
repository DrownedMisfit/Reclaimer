"""
Prueba de «📁 Carpetas» en «Material» (taller de miniaturas):
  · crear carpetas de Reclaimer (orden de abecedario, sin importar mayúsculas ni tildes), soltar imágenes encima
    (se copian), entrar, «⭐ Poner como principal» (portada), eliminar (a la Papelera: aquí simulada), renombrar;
  · vincular una carpeta «tuya» soltándola (se ve en su sitio: carpeta dentro de carpeta), sin copiar ni borrar nada
    en ella, y «Quitar de la lista»; sugerencias de carpetas de imágenes;
  · clic en una imagen = a la miniatura (los PNG transparentes, como elemento).
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_material_folders.py <carpeta>
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import material_lib as M  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def png(path, color, alpha=255):
    a = np.zeros((80, 80, 4), np.uint8)
    a[10:70, 10:70] = (*color, alpha)
    Image.fromarray(a).save(path)
    return path


def names(fb):
    return [fb.list.item(i).text() for i in range(fb.list.count())]


def main(out):
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    papelera = []
    M.trash = lambda p: (papelera.append(p), shutil.rmtree(p) if os.path.isdir(p) else os.remove(p), True)[-1] \
        if M.is_managed(p) else False                                   # (la Papelera de verdad no se toca)
    for p in M.linked():
        M.unlink(p)
    win = MainWindow()
    win.show()
    pump(app, 0.3)
    win.setGeometry(0, 0, 1600, 1000)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    assert ed.folders is None
    ed.btn_folders.setChecked(True)
    fb = ed.folders
    assert fb is not None and ed.mat_stack.currentWidget() is fb and fb.path is None
    for n in ("Ojos", "agua", "Fuego"):
        fb.new_folder(n)
    tops = [t for t in names(fb) if not t.startswith("＋")]
    assert tops == ["agua", "Fuego", "Ojos"], tops                       # abecedario sin importar mayúsculas
    print("✓ carpetas de Reclaimer, en orden de abecedario («agua», «Fuego», «Ojos»)")
    # soltar imágenes encima de «Fuego» (desde el Explorador) → se copian dentro
    srcs = [png(os.path.join(out, f"llama{i}.png"), (255, 80 + 40 * i, 0), 255 if i else 255) for i in range(3)]
    fuego = next(r["path"] for r in M.roots() if r["name"] == "Fuego")
    assert fb._dropped(srcs, fuego) == 3 and all(os.path.exists(s) for s in srcs), "se copian (el original queda)"
    fb.open(fuego)
    assert names(fb) == ["llama0", "llama1", "llama2"], names(fb)
    pump(app, 0.5)
    assert not fb.list.item(0).icon().isNull()
    imgs = M.list_dir(fuego)[1]
    assert M.cover(fuego) == imgs[0]
    fb.set_main(imgs[2])
    assert M.cover(fuego) == imgs[2], "⭐ la principal es la portada"
    fb.go_up()
    assert fb.path is None
    pump(app, 0.5)
    assert fb.delete(os.path.join(fuego, "llama1.png"), confirm=False) and len(M.list_dir(fuego)[1]) == 2
    print("✓ soltar imágenes en una carpeta (copia), entrar, «⭐ Poner como principal», eliminar (a la Papelera)")
    # vincular una carpeta «tuya» soltándola: carpeta dentro de carpeta, sin copiar ni borrar nada en ella
    mia = os.path.join(out, "Mis imágenes")
    os.makedirs(os.path.join(mia, "juegos", "halo"), exist_ok=True)
    os.makedirs(os.path.join(mia, "logos de compañías"), exist_ok=True)
    png(os.path.join(mia, "juegos", "halo", "casco.png"), (40, 160, 40))
    png(os.path.join(mia, "logos de compañías", "logo.png"), (40, 40, 200), 255)
    fb.open(None)
    assert fb._dropped([mia], None) == 1
    assert "Mis imágenes" in names(fb)
    assert M.cover(mia).endswith("logo.png"), M.cover(mia)          # (la primera imagen, buscando de arriba abajo)
    fb.open(mia)
    assert names(fb) == ["juegos", "logos de compañías"], names(fb)
    assert fb.new_folder("Nada") is None and not os.path.exists(os.path.join(mia, "Nada")), "en las tuyas no se crea"
    fb.open(os.path.join(mia, "juegos", "halo"))
    assert names(fb) == ["casco"]
    assert fb._dropped([srcs[0]], None) == 0 and not os.path.exists(os.path.join(mia, "juegos", "halo", "llama0.png"))
    assert not M.trash(os.path.join(mia, "juegos", "halo", "casco.png")) and \
        os.path.exists(os.path.join(mia, "juegos", "halo", "casco.png")), "en las tuyas no se borra nada"
    fb.go_up()
    assert os.path.normcase(fb.path) == os.path.normcase(os.path.join(mia, "juegos"))
    fb.go_up()
    fb.go_up()
    assert fb.path is None
    print("✓ vincular una carpeta tuya soltándola: carpeta dentro de carpeta, sin crear, copiar ni borrar nada en ella")
    # clic en una imagen = a la miniatura
    n = len(ed.doc["layers"])
    fb.open(fuego)
    fb._clicked(fb.list.item(0))
    assert len(ed.doc["layers"]) == n + 1 and os.path.normcase(ed.doc["layers"][-1]["path"]).startswith(
        os.path.normcase(fuego))
    fb.open(None)
    M.unlink(mia)
    fb.populate()
    assert "Mis imágenes" not in names(fb) and os.path.isdir(mia), "quitar de la lista no borra la carpeta"
    ojos = next(r["path"] for r in M.roots() if r["name"] == "Ojos")
    fb.delete(ojos, confirm=False)
    assert "Ojos" not in names(fb)
    agua = next(r["path"] for r in M.roots() if r["name"] == "agua")
    M.rename(agua, "Agua y olas")
    assert "Agua y olas" in [r["name"] for r in M.roots()]
    assert isinstance(M.suggestions(), list)
    ed.btn_folders.setChecked(False)
    assert ed.mat_stack.currentWidget() is ed.material
    print("✓ clic = a la miniatura; quitar de la lista, eliminar y renombrar carpetas; «📁 Carpetas» se oculta")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    out_ = sys.argv[1]
    os.makedirs(out_, exist_ok=True)
    main(out_)
    print("TODO OK")
