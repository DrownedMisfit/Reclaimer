"""
Miniatura · 🌫 Desenfocar la capa entera (el usuario: «necesito una opción que sea de desenfocar la imagen completa
que selecciono»):
  · clic derecho → «🌫 Desenfocar» desenfoca toda la capa (un paso de deshacer) y el menú pasa a «Quitar desenfoque»;
  · «Desenfoque» en el panel ajusta la fuerza; 0 = nítida;
  · una foto opaca sigue opaca hasta los bordes (sin bordes transparentes ni halos oscuros);
  · la exportación lleva el desenfoque.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_blur.py <carpeta>
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


def detalle(rgba) -> float:
    """Cuánto «detalle» tiene (diferencia media entre píxeles vecinos): baja al desenfocar."""
    g = rgba[..., :3].astype(np.float32).mean(axis=2)
    return float(np.abs(np.diff(g, axis=1)).mean())


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_thumb_blur")
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import thumbnail as T
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    p = os.path.join(out, "ruido.png")
    Image.fromarray((np.random.default_rng(1).random((500, 800, 3)) * 255).astype(np.uint8)).save(p)
    ed.add_image(p, "Foto")
    lay = ed.cur()
    nitida = T.qimage_to_rgba(T.render_layer(lay)[0])
    d0 = detalle(nitida)
    textos = [a.text() for a in ed.layer_menu(lay).actions()]
    assert "🌫 Desenfocar" in textos, textos
    assert ed.toggle_blur(lay) and float(ed.cur()["blur"]) == ed.BLUR_DEFAULT
    lay = ed.cur()
    borrosa = T.qimage_to_rgba(T.render_layer(lay)[0])
    d1 = detalle(borrosa)
    assert d1 < d0 * 0.4, (d0, d1)
    assert "🌫 Quitar desenfoque" in [a.text() for a in ed.layer_menu(lay).actions()]
    print(f"✓ clic derecho → «🌫 Desenfocar»: toda la capa se desenfoca (detalle {d0:.1f} → {d1:.1f}); el menú ofrece "
          "quitarlo")
    # opaca hasta los bordes: el contenido (sin el margen de efectos) sigue con alfa 255
    img, cw, ch = T.render_layer(lay)
    a = T.qimage_to_rgba(img)
    px, py = int((img.width() - cw) / 2), int((img.height() - ch) / 2)
    core = a[py + 1:py + int(ch) - 1, px + 1:px + int(cw) - 1, 3]
    assert core.min() >= 250, core.min()
    print("✓ una foto opaca sigue opaca hasta los bordes (sin bordes transparentes)")
    # más fuerza desde el panel = más borroso; 0 = nítida
    ed._set(lay, "Desenfoque", blur=40)
    d2 = detalle(T.qimage_to_rgba(T.render_layer(ed.cur())[0]))
    assert d2 < d1, (d1, d2)
    ed._set(ed.cur(), "Desenfoque", blur=0)
    d3 = detalle(T.qimage_to_rgba(T.render_layer(ed.cur())[0]))
    assert abs(d3 - d0) < 0.5, (d0, d3)
    print(f"✓ «Desenfoque» en el panel: 40 → más borroso ({d2:.1f}); 0 → nítida otra vez")
    # deshacer y exportar
    ed.toggle_blur(ed.cur())
    ed.undo()
    assert float(ed.cur().get("blur", 0) or 0) == 0
    ed.redo() if hasattr(ed, "redo") else ed.toggle_blur(ed.cur())
    if float(ed.cur().get("blur", 0) or 0) == 0:
        ed.toggle_blur(ed.cur())
    full = T.render(ed.doc)
    rgba = T.qimage_to_rgba(full)
    assert detalle(rgba[200:500, 300:900]) < d0 * 0.5
    print("✓ Ctrl+Z quita el desenfoque y la miniatura exportada lo lleva")
    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
