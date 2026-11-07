"""
🔎 Buscar FONDO (pestaña «🔎 PNG» del taller de miniaturas): dos modos, «✂ PNG recortado» (por defecto) y «🖼 Fondo».
  · Fondo: la búsqueda pide imágenes grandes y de la forma del lienzo (tbs=isz:l,iar:w en YouTube, iar:t en Shorts),
    sin «png»; al usarla va detrás de todo, sin quitarle el fondo liso.
  · PNG recortado: como siempre.
  · El modo se recuerda; el filtro «Sin marca de agua» vale en los dos.
Sin ventanas y sin red (las imágenes son de prueba, creadas aquí). Ejecutar:
  .venv/Scripts/python.exe tests/test_bg_search.py <carpeta>
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

import urllib.parse  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def esperar(app, cond, secs=20, info=lambda: ""):
    t0 = time.time()
    while not cond():
        if time.time() - t0 > secs:
            raise AssertionError("tiempo agotado esperando: " + info())
        app.processEvents()
        time.sleep(0.02)


def imagen(path: str, w: int, h: int, fondo=(255, 255, 255)):
    """Imagen de prueba: fondo liso y un cuadro de color en el centro."""
    im = Image.new("RGB", (w, h), fondo)
    d = ImageDraw.Draw(im)
    d.rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(200, 40, 40))
    im.save(path)
    return path


def main():
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ai import thumb_elements as E
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    st = QSettings("EditorIA", "EditorIA")
    st.remove("miniatura/busqueda_modo")          # (la prueba empieza con el modo por defecto)
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)

    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    assert ed.png_btn_png.isChecked() and not ed.png_btn_fondo.isChecked(), "por defecto debe ir PNG recortado"
    assert ed.png_btn_png.isCheckable() and ed.png_btn_fondo.isCheckable()
    print("✓ dos botones de modo («✂ PNG recortado» y «🖼 Fondo»); por defecto, PNG recortado")

    ed.png_nowm.setChecked(False)                 # (para leer las palabras de la búsqueda sin el filtro)
    u = ed._search_url("fuego")
    assert "ift:png" in u and "fuego+png" in u, u
    print("✓ modo PNG: la búsqueda sigue como antes (ift:png y la palabra «png»)")

    ed.png_btn_fondo.click()
    assert ed._png_mode == "fondo" and st.value("miniatura/busqueda_modo", type=str) == "fondo"
    assert "Buscar fondo" in ed.png_query.placeholderText()
    u = ed._search_url("ciudad de noche")
    assert "png" not in u.lower(), u
    assert "iar:w" in u and "isz:l" in u, u
    assert "wallpaper" in urllib.parse.unquote_plus(u), u
    print("✓ modo Fondo en YouTube: sin «png», con isz:l e iar:w (imágenes grandes y anchas)")

    ed.png_nowm.setChecked(True)
    u = ed._search_url("bosque")
    assert "-site:shutterstock.com" in urllib.parse.unquote_plus(u), u
    assert "isz:l" in u and "iar:w" in u
    print("✓ «Sin marca de agua» sigue valiendo en modo Fondo")
    ed.png_nowm.setChecked(False)

    ed.png_btn_png.click()
    assert ed._png_mode == "png" and st.value("miniatura/busqueda_modo", type=str) == "png"
    ed.png_nowm.setChecked(True)
    u = ed._search_url("fuego")
    assert "ift:png" in u and "iar:" not in u and "-site:" in urllib.parse.unquote_plus(u), u
    ed.png_nowm.setChecked(False)
    ed.png_btn_fondo.click()
    print("✓ el modo se guarda en los ajustes (PNG ↔ Fondo) y vuelve a PNG sin cambios")

    # Vertical (Shorts): imagen alta. (El taller es uno solo: al pedir «short» cambia de formato en el mismo.)
    ed_s = win.open_thumbnail("short")
    pump(app, 0.3)
    assert ed_s is ed and ed.png_btn_fondo.isChecked(), "el modo recordado (Fondo) debe seguir al cambiar de formato"
    ed.png_nowm.setChecked(False)
    u = ed._search_url("bosque")
    assert "iar:t" in u and "isz:l" in u and "png" not in u.lower(), u
    print("✓ Shorts en modo Fondo: iar:t (imágenes altas), isz:l, sin «png»")
    ed.png_btn_png.click()
    assert st.value("miniatura/busqueda_modo", type=str) == "png"
    ed.png_btn_fondo.click()
    ed = win.open_thumbnail("youtube")            # (vuelve a YouTube para lo que sigue)
    pump(app, 0.3)
    assert ed.doc["format"] == "youtube" and ed._png_mode == "fondo"

    # fetch: keep_bg no toca el fondo; el de siempre sí
    blanco = imagen(os.path.join(out, "fondo_blanco.png"), 1600, 900)
    r_kept = E.fetch(blanco, keep_bg=True)
    a_kept = np.asarray(Image.open(r_kept["path"]).convert("RGBA"))[..., 3]
    assert float((a_kept < 20).mean()) < 0.05 and not r_kept["cleaned"], "keep_bg=True no debe quitar el fondo"
    r_plain = E.fetch(blanco)
    a_plain = np.asarray(Image.open(r_plain["path"]).convert("RGBA"))[..., 3]
    assert r_plain["cleaned"] and float((a_plain < 20).mean()) > 0.1, "keep_bg=False debe quitar el fondo liso"
    assert r_kept["path"] != r_plain["path"], "la versión de fondo no se mezcla con la recortada"
    print("✓ thumb_elements.fetch: keep_bg=True deja el fondo blanco; keep_bg=False lo quita como siempre")

    # Uso como fondo: el flujo real (use_png) en modo Fondo
    ed.png_btn_fondo.click()
    n0, id0 = len(ed.doc["layers"]), (ed.doc["layers"][0]["id"] if ed.doc["layers"] else None)
    ed.use_png(blanco)
    esperar(app, lambda: len(ed.doc["layers"]) > n0 and ed._png_job is not None and not ed._png_job.isRunning(), info=lambda: ed.png_status.text())
    lay = ed.doc["layers"][0]
    assert lay["id"] != id0 and lay["kind"] == "image" and lay["name"] == "Fondo", "la capa de fondo debe ir en la posición 0"
    w0, h0 = E.measure(lay["path"])[:2]
    assert lay["scale"] * w0 >= ed.doc["w"] - 1 and lay["scale"] * h0 >= ed.doc["h"] - 1, "debe cubrir el lienzo"
    assert E.measure(lay["path"])[2] < 0.05, "en Fondo la imagen no se recorta"
    assert ed.png_status.text().startswith(f"✓ Puesta de fondo · {w0}×{h0}"), ed.png_status.text()
    assert "Es pequeña" not in ed.png_status.text()
    print(f"✓ modo Fondo: la imagen va detrás de todo (capa 0), cubre el lienzo · «{ed.png_status.text().splitlines()[0]}»")

    pequena = imagen(os.path.join(out, "fondo_pequeno.png"), 300, 200, fondo=(20, 20, 60))
    n1 = len(ed.doc["layers"])
    ed.use_png(pequena)
    esperar(app, lambda: len(ed.doc["layers"]) > n1 and not ed._png_job.isRunning())
    assert "⚠ Es pequeña: puede verse borrosa" in ed.png_status.text(), ed.png_status.text()
    print("✓ una imagen menor que el lienzo avisa: «⚠ Es pequeña: puede verse borrosa»")

    win.go_page("edit")                          # (como en test_material_live: sin el aviso de «cambios sin guardar»)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
