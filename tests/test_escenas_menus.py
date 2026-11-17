"""
🎬 Escenas, clic derecho en las listas de 🧍 Personajes (imágenes) y 🔊 Sonidos: la ruta del archivo, 📋 copiarla,
📂 abrir su carpeta y 🗑 quitar (de Medios; un sonido guardado de internet, a la papelera). No deja quitar lo que usa
la escena. Sonidos: ⏸ pausar / ▶ seguir y ⏹ parar al escuchar.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_menus.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.model import KIND_AUDIO, KIND_IMAGE, MediaItem, new_id  # noqa: E402


def wav(ruta):
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    vistos = []

    def textos_de(menu):                          # (se arma el menú sin abrirlo)
        vistos.append([x.text() for x in menu.actions()])
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    app.processEvents()
    p = win.ctrl.project
    rutas = {}
    for nombre in ("uno", "dos"):
        r = os.path.join(_TMP, nombre + ".png")
        img = QImage(200, 200, QImage.Format_ARGB32)
        img.fill(QColor("#c03030"))
        img.save(r)
        m = MediaItem(new_id(), r, KIND_IMAGE, nombre, width=200, height=200)
        p.media[m.id] = m
        rutas[nombre] = m
    ra = os.path.join(_TMP, "golpe.wav")
    wav(ra)
    ma = MediaItem(new_id(), ra, KIND_AUDIO, "golpe", duration=1.0, has_audio=True)
    p.media[ma.id] = ma
    win.go_page("scenes")
    app.processEvents()
    pg = win._scenes_widget
    pg._llenar_imagenes()
    pg.reload()

    # imágenes: menú con ruta, carpeta y quitar
    it = next(pg.lista_img.item(i) for i in range(pg.lista_img.count())
              if pg.lista_img.item(i).data(Qt.UserRole) == rutas["dos"].id)
    textos_de(pg._armar_menu_img(it.data(Qt.UserRole)))
    textos = vistos[-1]
    assert any(t.startswith("📄 ") and "dos.png" in t for t in textos), textos
    assert "📂 Abrir su carpeta" in textos and "📋 Copiar la ruta" in textos and "🗑 Quitar de Medios" in textos
    pg._abrir_carpeta(rutas["dos"].path)
    assert pg._ultima_carpeta == rutas["dos"].path
    print("✓ imagen: clic derecho con su ruta, 📋 copiar, 📂 abrir su carpeta y 🗑 quitar")
    pg._añadir_actor(rutas["uno"].id)
    assert not pg._quitar_de_medios(rutas["uno"].id) and rutas["uno"].id in p.media, "en uso en la escena: no"
    p.scenes["otra"] = {"id": "otra", "nombre": "Otra escena", "actores": [{"media_id": rutas["dos"].id}],
                        "sonidos": []}
    assert not pg._quitar_de_medios(rutas["dos"].id), "la usa otra escena guardada: no"
    assert "Otra escena" in win.statusBar().currentMessage()
    del p.scenes["otra"]
    assert pg._quitar_de_medios(rutas["dos"].id) and rutas["dos"].id not in win.ctrl.project.media
    assert os.path.isfile(rutas["dos"].path), "el archivo de tu PC no se borra"
    assert all(pg.lista_img.item(i).data(Qt.UserRole) != rutas["dos"].id for i in range(pg.lista_img.count()))
    win.ctrl.undo_stack.undo()
    assert rutas["dos"].id in win.ctrl.project.media, "Ctrl+Z lo devuelve"
    p = win.ctrl.project
    print("✓ 🗑 quitar de Medios (no lo que usa la escena; el archivo sigue en el PC)")

    # sonidos: de Medios, de internet (papelera) y ✦ (no se quitan)
    from editoria.core.paths import user_dir
    web = user_dir() / "Sonidos de internet"
    web.mkdir(parents=True, exist_ok=True)
    rw = str(web / "trueno.wav")
    wav(rw)
    pg.reload()

    def item_de(pred):
        return next(pg.lista_snd.item(i) for i in range(pg.lista_snd.count()) if pred(pg.lista_snd.item(i)))
    for pred, debe in ((lambda x: x.data(Qt.UserRole) == ra, "🗑 Quitar de Medios"),
                       (lambda x: x.data(Qt.UserRole) == rw, "🗑 Mandar a la papelera")):
        it_s = item_de(pred)
        textos_de(pg._armar_menu_snd(it_s.data(Qt.UserRole)))
        assert debe in vistos[-1] and "📂 Abrir su carpeta" in vistos[-1], vistos[-1]
    it_s = item_de(lambda x: str(x.data(Qt.UserRole)).startswith("sfx:"))
    textos_de(pg._armar_menu_snd(it_s.data(Qt.UserRole)))
    assert not any(t.startswith("🗑") for t in vistos[-1]) and "📂 Abrir su carpeta" in vistos[-1]
    print("✓ sonidos: Medios → quitar · internet → papelera · ✦ de Reclaimer → solo ruta y carpeta")
    from PySide6.QtCore import QFile
    a_papelera = []
    QFile.moveToTrash = staticmethod(lambda r: (a_papelera.append(r), os.remove(r), True)[-1])   # (sin la real)
    assert pg._sonido_a_papelera(rw) and a_papelera == [rw]
    assert all(pg.lista_snd.item(i).data(Qt.UserRole) != rw for i in range(pg.lista_snd.count()))
    print("✓ 🗑 un sonido de internet va a la papelera y sale de la lista")

    # ⏸ / ⏹
    assert pg.b_pausa_snd.text() in ("▶", "⏸") and pg.b_parar_snd.text() == "⏹"
    pg._parar_escucha()
    assert pg.b_pausa_snd.text() == "▶"
    print("✓ ⏸/▶ y ⏹ junto al volumen de Sonidos")

    pg.sucia = False
    win.go_page("edit")
    app.processEvents()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
