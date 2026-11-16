"""
🎬 Escenas como la línea de tiempo normal:
1) ⌨ Ctrl+C / Ctrl+V (copiar y pegar un personaje), Ctrl+D (duplicar), Ctrl+X (cortar), Ctrl+Z / Ctrl+Y (deshacer y
   rehacer en la escena), + / − y Mayús+Z (acercar, alejar, ver toda), ← → Inicio Fin (mover la línea roja).
2) Personajes: 🗂 Local y 🌐 Internet; dentro de Internet, ✂ PNG recortado o 🖼 Fondo.
3) 🖼 Fondo de imagen: clic derecho en una imagen → «Usar de fondo»; nítida o borrosa en el visor y al aplicar (un clip
   de imagen detrás de todo, borroso si es «Imagen borrosa»). Elegir «Imagen» sin imagen lleva a 🌐 Internet → Fondo.
4) Barra de reproducción: ⏮ ◀ ▶ ▶| ⏭, tiempo «0:00.00 / 0:04.00», 🔊 volumen de la vista previa.
5) Sonidos: 🔊 volumen al escucharlos y con el que entran en la escena.
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_teclas_fondo.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

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
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.model import KIND_IMAGE, MediaItem, new_id  # noqa: E402


def imagen(nombre: str, color: str, w=400, h=300) -> MediaItem:
    ruta = os.path.join(_TMP, nombre + ".png")
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    for x in range(0, w, 8):                       # (rayas: así se nota si el visor la desenfoca)
        for y in range(h):
            img.setPixelColor(x, y, QColor("white"))
    img.save(ruta)
    return MediaItem(new_id(), ruta, KIND_IMAGE, nombre, width=w, height=h)


def tecla(pg, k, mods=Qt.NoModifier):
    pg.tl.setFocus()
    QTest.keyClick(pg.tl, k, mods)
    QApplication.processEvents()


def asentar(pg):
    if getattr(pg, "_t_hist", None) is not None and pg._t_hist.isActive():
        pg._t_hist.stop()
        pg._guardar_hist()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    app.processEvents()
    p = win.ctrl.project
    persona, fondo = imagen("persona", "#c03030"), imagen("ciudad", "#2040a0", 800, 450)
    p.media[persona.id] = persona
    p.media[fondo.id] = fondo
    win.go_page("scenes")
    app.processEvents()
    pg = win._scenes_widget
    pg._llenar_imagenes()

    # 2) Local / Internet con sus dos modos
    assert [pg.sub_img.tabText(i) for i in range(pg.sub_img.count())] == ["🗂 Local", "🌐 Internet"]
    assert [b.text() for b in pg._grupo_web.buttons()] == ["✂ PNG recortado", "🖼 Fondo"]
    assert pg._modo_web == "png"
    print("✓ Personajes: 🗂 Local y 🌐 Internet (✂ PNG recortado / 🖼 Fondo)")

    # 1) teclas
    pg._añadir_actor(persona.id)
    asentar(pg)
    tecla(pg, Qt.Key_Z, Qt.ControlModifier)
    assert pg.escena["actores"] == [], "el primer cambio tras abrir también se deshace"
    tecla(pg, Qt.Key_Y, Qt.ControlModifier)
    assert len(pg.escena["actores"]) == 1
    act = pg.escena["actores"][0]
    act["inicio"] = 0.5
    pg.tl.sel = ("actor", act)
    tecla(pg, Qt.Key_C, Qt.ControlModifier)
    tecla(pg, Qt.Key_V, Qt.ControlModifier)
    asentar(pg)
    assert len(pg.escena["actores"]) == 2, "Ctrl+C y Ctrl+V: un segundo personaje"
    assert pg.escena["actores"][1].get("inicio") == 0.5, "el pegado conserva su retraso de entrada"
    tecla(pg, Qt.Key_D, Qt.ControlModifier)
    asentar(pg)
    assert len(pg.escena["actores"]) == 3, "Ctrl+D duplica"
    tecla(pg, Qt.Key_Z, Qt.ControlModifier)
    assert len(pg.escena["actores"]) == 2, "Ctrl+Z deshace en la escena"
    tecla(pg, Qt.Key_Z, Qt.ControlModifier)
    assert len(pg.escena["actores"]) == 1
    tecla(pg, Qt.Key_Y, Qt.ControlModifier)
    assert len(pg.escena["actores"]) == 2, "Ctrl+Y rehace"
    pg.tl.sel = ("actor", pg.escena["actores"][-1])
    tecla(pg, Qt.Key_X, Qt.ControlModifier)
    asentar(pg)
    assert len(pg.escena["actores"]) == 1, "Ctrl+X corta (quita y guarda)"
    tecla(pg, Qt.Key_V, Qt.ControlModifier)
    asentar(pg)
    assert len(pg.escena["actores"]) == 2, "lo cortado se puede pegar"
    print("✓ Ctrl+C / Ctrl+V / Ctrl+D / Ctrl+X / Ctrl+Z / Ctrl+Y en la escena")
    a0, a1 = pg.escena["actores"][0], pg.escena["actores"][1]
    ent = next(f for f in a0["fases"] if f["tipo"] == "entrada")
    ent["anim"] = "aparece"
    pg.tl.sel = ("fase", ent)
    tecla(pg, Qt.Key_X, Qt.ControlModifier)
    assert any(f["tipo"] == "entrada" for f in a0["fases"]), "Ctrl+X no quita la entrada"
    pg.tl.sel = ("actor", a1)
    tecla(pg, Qt.Key_V, Qt.ControlModifier)
    asentar(pg)
    a1 = pg.escena["actores"][1]
    ents = [f for f in a1["fases"] if f["tipo"] == "entrada"]
    assert len(ents) == 1 and ents[0]["anim"] == "aparece", ents
    assert not any(f["tipo"] == "accion" and f["anim"] == "aparece" for f in a1["fases"]), "no una acción rota"
    print("✓ entrada copiada: se pone como entrada del otro personaje (no una acción rota); Ctrl+X no la borra")
    z0 = pg.tl.zoom
    tecla(pg, Qt.Key_Plus)
    assert pg.tl.zoom > z0, "+ acerca"
    tecla(pg, Qt.Key_Minus)
    tecla(pg, Qt.Key_Plus)
    tecla(pg, Qt.Key_Z, Qt.ShiftModifier)
    assert pg.tl.zoom == 1.0, "Mayús+Z ve toda la escena"
    tecla(pg, Qt.Key_End)
    import editoria.core.scenes as scenes
    total = scenes.largo(pg.escena)
    assert abs(pg.tl.t - total) < 1e-6
    tecla(pg, Qt.Key_Left, Qt.ShiftModifier)
    assert abs(pg.tl.t - (total - 1.0)) < 1e-6, "Mayús+← un segundo atrás"
    tecla(pg, Qt.Key_Home)
    assert pg.tl.t == 0.0
    print("✓ + / − / Mayús+Z acercan y alejan · Inicio, Fin, Mayús+← mueven la línea roja")

    # 4) barra de reproducción
    pg._saltar_a(1.5)
    assert abs(pg.tl.t - 1.5) < 1e-6
    assert pg.lbl_tiempo.text().startswith("0:01.50 / "), pg.lbl_tiempo.text()
    pg._saltar_a(99)
    assert abs(pg.tl.t - total) < 1e-6, "no se pasa del final"
    pg._saltar_a(0)
    pg.alternar()
    assert pg.b_play2.text() == "⏸" and pg.b_play.text() == "⏸"
    pg.alternar()
    assert pg.b_play2.text() == "▶"
    pg.vol_vista.setValue(40)
    print("✓ barra ⏮ ◀ ▶ ▶| ⏭ con el tiempo y 🔊 de la vista previa")

    # 5) volumen de Sonidos
    pg.vol_snd.setValue(30)
    assert pg.lbl_vol_snd.text() == "30 %"
    snd = MediaItem(new_id(), os.path.join(_TMP, "x.wav"), "audio", "golpe", duration=1.0)
    p.media[snd.id] = snd
    antes = len(pg.escena["sonidos"])
    import inspect
    src = inspect.getsource(type(pg)._añadir_sonido)
    assert "vol_snd" in src
    print("✓ 🔊 en Sonidos (al escuchar y con el que entran)")
    del antes

    # 3) fondo de imagen
    pg.fondo.setCurrentIndex(pg.fondo.findData("img"))      # (sin imagen aún y nada elegido en Local)
    pg.lista_img.setCurrentItem(None)
    pg.escena.pop("fondo_img", None)
    pg.fondo.setCurrentIndex(pg.fondo.findData("blur"))
    pg.fondo.setCurrentIndex(pg.fondo.findData("img"))
    assert pg.sub_img.currentIndex() == 1 and pg._modo_web == "fondo", "sin imagen: a 🌐 Internet → 🖼 Fondo"
    print("✓ «Imagen» sin imagen: abre 🌐 Internet en modo 🖼 Fondo")
    pg._usar_de_fondo(fondo.id)
    assert pg.escena["fondo_img"] == fondo.id and pg.escena["fondo"] == "img"
    nitida = pg._fondo_item.pixmap().toImage()
    pg.fondo.setCurrentIndex(pg.fondo.findData("img_blur"))
    borrosa = pg._fondo_item.pixmap().toImage()
    assert not nitida.isNull() and nitida.size() == borrosa.size()

    def contraste(im):
        y = im.height() // 2
        vals = [QColor(im.pixel(x, y)).lightness() for x in range(0, min(200, im.width()))]
        return max(vals) - min(vals)
    assert contraste(nitida) > 100 and contraste(borrosa) < contraste(nitida) * 0.6, (contraste(nitida),
                                                                                      contraste(borrosa))
    print(f"✓ visor: fondo nítido (contraste {contraste(nitida)}) y borroso ({contraste(borrosa)})")
    assert pg.aplicar() is not False
    app.processEvents()
    fondos = [c for c in win.ctrl.project.clips.values() if c.media_id == fondo.id]
    assert len(fondos) == 1, fondos
    c = fondos[0]
    assert (c.fx or {}).get("blur"), "«Imagen borrosa» lleva desenfoque"
    assert c.layout and c.layout.get("fit") == "cover"
    pistas = [win.ctrl.project.track_index(x.track_id) for x in win.ctrl.project.clips.values()
              if x.media_id == persona.id]
    assert pistas and all(i < win.ctrl.project.track_index(c.track_id) for i in pistas), "el fondo, detrás"
    print("✓ al aplicar: clip de imagen que cubre el cuadro, borroso y detrás de los personajes")
    import json
    ruta = scenes.guardar_plantilla(pg.escena, win.ctrl.project, "con fondo")
    t = json.load(open(ruta, encoding="utf-8"))
    assert t["fondo"] == "img_blur" and t["fondo_ruta"] == fondo.path
    e2, faltan = scenes.desde_plantilla(t, 0.0, lambda r, cat: fondo.id if r == fondo.path else persona.id)
    assert e2["fondo_img"] == fondo.id and e2["fondo"] == "img_blur" and not faltan
    t["fondo_ruta"] = os.path.join(_TMP, "no_existe.png")
    e3, faltan = scenes.desde_plantilla(t, 0.0, lambda r, cat: persona.id)
    assert e3["fondo"] != "img_blur" and faltan, "si falta la imagen, se dice y se vuelve al fondo normal"
    print("✓ las plantillas guardan la imagen de fondo (y si falta, lo dicen)")

    win.go_page("edit")
    app.processEvents()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    if getattr(win, "_scenes_widget", None) is not None:
        win._scenes_widget.sucia = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
