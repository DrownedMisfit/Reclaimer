"""
«Material» del taller de miniaturas al día: toda imagen que entra en «Medios» aparece sola (el usuario: «si yo subo
una imagen, esa tiene que aparecer automáticamente en materiales»):
  · importada con el taller abierto;
  · importada en la edición y volviendo a «Miniatura» (antes solo se leía la primera vez);
  · un .jfif (lo que baja Windows de internet) cuenta como imagen;
  · las imágenes que pones desde TUS carpetas (sin pasar por Medios) también salen («📁»);
  · clic derecho: quitar (de la lista / de Medios; el archivo se queda), borrar un «🔎 PNG», a la Papelera
    (preguntando). En la prueba la Papelera es de mentira: nada sale de la carpeta de la prueba.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_material_live.py <carpeta>
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

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def material_paths(ed) -> list[str]:
    return [os.path.normcase(str(ed.material.item(i).data(Qt.UserRole))) for i in range(ed.material.count())]


def item_de(ed, path):
    k = os.path.normcase(path)
    return next((ed.material.item(i) for i in range(ed.material.count())
                 if os.path.normcase(str(ed.material.item(i).data(Qt.UserRole))) == k), None)


def textos_menu(ed, it) -> list[str]:
    """Las opciones del clic derecho sobre una imagen (sin abrir el menú de verdad)."""
    from editoria.ui import help as H
    vistos = []
    original = H.exec_menu
    H.exec_menu = lambda menu, pos: vistos.extend(x.text() for x in menu.actions() if x.text())
    try:
        ed._material_menu(ed.material.visualItemRect(it).center())
    finally:
        H.exec_menu = original
    return vistos


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import kind_for_path
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    assert kind_for_path("foto.jfif") == "image" and kind_for_path("x.JPE") == "image"
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    imgs = []
    for i, ext in enumerate((".png", ".jpg", ".jfif")):
        p = os.path.join(out, f"foto_{i}{ext}")
        Image.fromarray((np.random.default_rng(i).random((90, 160, 3)) * 255).astype(np.uint8)).save(
            p, format="JPEG" if ext != ".png" else "PNG")
        imgs.append(p)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.4)
    # 1) con el taller abierto
    win.ctrl.import_paths([imgs[0]])
    pump(app, 0.8)
    assert os.path.normcase(imgs[0]) in material_paths(ed), material_paths(ed)
    print("✓ importada con el taller abierto: aparece sola en «Material»")
    # 2) en la edición, y de vuelta a «Miniatura»
    win.go_page("edit")
    pump(app, 0.3)
    win.ctrl.import_paths([imgs[1], imgs[2]])
    pump(app, 0.5)
    ed2 = win.open_thumbnail("youtube")
    pump(app, 0.8)
    got = material_paths(ed2)
    assert os.path.normcase(imgs[1]) in got and os.path.normcase(imgs[2]) in got, got
    assert got.index(os.path.normcase(imgs[2])) < got.index(os.path.normcase(imgs[0])), "las últimas, primero"
    print("✓ importadas en la edición: al volver a «Miniatura» ya están (también el .jfif), las últimas primero")
    # 3) 📁 de tus carpetas (sin pasar por Medios): al ponerla en la miniatura, se queda en «Material»
    from PySide6.QtWidgets import QMessageBox
    from editoria.core.paths import cache_dir
    from editoria.ui import thumbnail_editor as TE
    mia_dir = os.path.join(out, "mis_carpetas", "Fuego")
    os.makedirs(mia_dir, exist_ok=True)
    mia = os.path.join(mia_dir, "llama.png")
    Image.fromarray((np.random.default_rng(9).random((90, 160, 3)) * 255).astype(np.uint8)).save(mia)
    ed2.add_image(mia, "llama")
    pump(app, 0.6)
    it = item_de(ed2, mia)
    assert it is not None and it.text().startswith("📁"), material_paths(ed2)
    assert not any(os.path.normcase(m.path) == os.path.normcase(mia) for m in win.ctrl.project.media.values())
    print("✓ una imagen de tus carpetas puesta en la miniatura sale en «Material» como «📁 llama.png»")
    # 4) clic derecho
    papelera = []
    TE._a_papelera = lambda p: papelera.append(os.path.normcase(p)) or True     # Papelera de mentira
    assert textos_menu(ed2, it)[:2] == ["✕ Quitar de Material (el archivo se queda en tu carpeta)",
                                        "🗑 Eliminar el archivo (a la Papelera)…"], textos_menu(ed2, it)
    ed2._material_quitar(it)
    pump(app, 0.3)
    assert item_de(ed2, mia) is None and os.path.exists(mia) and not papelera
    ed2.doc["layers"] = [l for l in ed2.doc["layers"] if l.get("path") != mia]
    ed2._fill_material()
    assert item_de(ed2, mia) is None, "quitada: no vuelve sola"
    ed2.add_image(mia, "llama")                        # volver a ponerla la trae de nuevo
    pump(app, 0.6)
    assert item_de(ed2, mia) is not None
    print("✓ «✕ Quitar» la saca de «Material» y el archivo sigue en tu carpeta; si la vuelves a usar, vuelve")
    medio = imgs[1]
    it = item_de(ed2, medio)
    assert textos_menu(ed2, it)[0].startswith("✕ Quitar de Material y de Medios"), textos_menu(ed2, it)
    ed2._material_quitar(it)
    pump(app, 0.6)
    assert item_de(ed2, medio) is None and os.path.exists(medio)
    assert not any(os.path.normcase(m.path) == os.path.normcase(medio) for m in win.ctrl.project.media.values())
    print("✓ una de Medios: «✕ Quitar» la saca de Material y de Medios (el archivo se queda)")
    preguntas = []
    original_q = QMessageBox.question
    QMessageBox.question = lambda *a, **k: preguntas.append(a) or QMessageBox.No
    assert not ed2._material_papelera(item_de(ed2, mia)) and not papelera and item_de(ed2, mia) is not None
    QMessageBox.question = lambda *a, **k: preguntas.append(a) or QMessageBox.Yes
    assert ed2._material_papelera(item_de(ed2, mia))
    QMessageBox.question = original_q
    assert papelera == [os.path.normcase(os.path.abspath(mia))] and len(preguntas) == 2
    assert item_de(ed2, mia) is None
    print("✓ «🗑 Eliminar el archivo» pregunta antes; con «No» no toca nada, con «Sí» va a la Papelera")
    png = os.path.join(str(cache_dir("png_web")), "prueba_borrar.png")
    Image.fromarray(np.zeros((40, 40, 4), np.uint8)).save(png)
    ed2._fill_material()
    it = item_de(ed2, png)
    assert it is not None and textos_menu(ed2, it)[0] == "🗑 Borrar este PNG", textos_menu(ed2, it)
    ed2._material_quitar(it)
    assert papelera[-1] == os.path.normcase(png)
    print("✓ un «🔎 PNG»: «🗑 Borrar este PNG» lo manda a la Papelera")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
