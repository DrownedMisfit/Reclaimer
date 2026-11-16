"""
1) Un clip de video con muchos fotogramas clave de encuadre (el reencuadre automático de los Shorts pone decenas) NO
   dibuja al pie una fila amarilla/azul que parece una pista de audio: los rombos solo salen en el clip seleccionado y
   separados (en YouTube, Edits y Shorts es la misma línea de tiempo).
2) 🎬 Escenas, «➕ Añadir a la escena» (personajes): con una imagen elegida la añade; con la lista llena pero nada
   elegido avisa; con la lista vacía abre «📁» (elegir una imagen de tu PC).
Ejecutar:  .venv/Scripts/python.exe tests/test_rombos_y_escena.py <carpeta_salida>
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

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollBar  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, new_id  # noqa: E402


def amarillos(img, r) -> int:
    """Píxeles amarillos/azules de rombo en la franja de abajo del clip."""
    n = 0
    y0, y1 = int(r.bottom() - 24), int(r.bottom() - 1)
    for y in range(max(0, y0), min(img.height(), y1)):
        for x in range(int(r.left()) + 2, min(img.width(), int(r.right()) - 2), 2):
            c = QColor(img.pixel(x, y))
            if (c.red() > 220 and c.green() > 180 and c.blue() < 140) or \
                    (c.blue() > 220 and c.green() > 180 and c.red() < 120):
                n += 1
    return n


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from editoria.ui.timeline import TimelineWidget
    ctrl = ProjectController()
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    m = MediaItem(new_id(), "/falso/v.mp4", KIND_VIDEO, "v.mp4", duration=60.0, width=1280, height=720,
                  probed=True)
    p.media[m.id] = m
    c = Clip(new_id(), m.id, v1.id, 0.0, 0.0, 20.0)
    c.zoom_kf = [{"t": i * 0.33, "z": 1.2, "x": 0.5, "y": 0.5} for i in range(60)]
    c.layout_kf = [{"t": i * 1.0, "x": 0, "y": 0, "w": 1, "h": 1} for i in range(20)]
    p.clips[c.id] = c
    ctrl.project_changed.emit()
    tl = TimelineWidget(ctrl, QScrollBar())
    tl.resize(1400, 300)
    tl.pps, tl.scroll = 30.0, 0.0
    tl.set_selection([])
    img = tl.grab().toImage()
    r = tl.clip_rect(c)
    sin = amarillos(img, r)
    img.save(os.path.join(out, "sin_seleccion.png"))
    assert sin == 0, f"sin seleccionar no debe verse la fila de rombos ({sin} px)"
    print("✓ sin seleccionar: ni rastro de la fila amarilla/azul al pie del video")
    tl.set_selection([c.id])
    img = tl.grab().toImage()
    img.save(os.path.join(out, "seleccionado.png"))
    con = amarillos(img, r)
    assert con > 0, "seleccionado, los rombos se ven"
    # separados: como mucho uno cada 14 px (antes 60 en 600 px = uno cada 10 px, pegados)
    assert con < 60 * 40, con
    print("✓ seleccionado: rombos, pero separados (no una barra)")
    ctrl.quitar_encuadre([c.id])
    assert p.clips[c.id].zoom_kf == [] and p.clips[c.id].layout_kf == []
    ctrl.undo_stack.undo()
    assert len(p.clips[c.id].zoom_kf) == 60
    print("✓ clic derecho «Quitar los rombos del encuadre automático» (y Ctrl+Z los devuelve)")
    from editoria.core.model import KIND_AUDIO, TRACK_AUDIO
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ma = MediaItem(new_id(), "/falso/v.mp4#a", KIND_AUDIO, "v.mp4", duration=60.0, probed=True)
    p.media[ma.id] = ma
    ca = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 20.0)
    p = ctrl.project                             # (tras Ctrl+Z los clips son otros objetos: se leen de nuevo)
    p.clips[c.id].link = ca.link = "lnk1"
    p.clips[ca.id] = ca
    ctrl.quitar_sonido([c.id])
    assert ca.id not in p.clips and c.id in p.clips and p.clips[c.id].link == ""
    assert p.clips[c.id].volume == 0.0, "el video queda en silencio (si no, volvería a sonar por sí mismo)"
    ctrl.undo_stack.undo()
    assert ca.id in p.clips and p.clips[c.id].link == "lnk1"
    print("✓ clic derecho «Quitar el sonido de este video»: se va su audio, la imagen se queda")

    # 2) Escenas
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    app.processEvents()
    win.go_page("scenes")
    app.processEvents()
    pg = win._scenes_widget
    nombres = [pg.sub_img.tabText(i) for i in range(pg.sub_img.count())]
    assert nombres == ["🗂 Local", "✂ PNG", "🌐 Internet"], nombres
    print("✓ Personajes como en Miniatura: 🗂 Local, ✂ PNG y 🌐 Internet")
    llamado = []
    pg._desde_archivo = lambda tipo: llamado.append(tipo)
    pg.lista_img.clear()
    pg._boton_añadir_img()
    assert llamado == ["imagen"], "con la lista vacía debe abrir «📁» para elegir una imagen"
    print("✓ lista vacía: «Añadir a la escena» abre el explorador para elegir una imagen")
    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtCore import Qt
    it = QListWidgetItem("algo")
    it.setData(Qt.UserRole, "no_existe")
    pg.lista_img.addItem(it)
    pg.lista_img.setCurrentItem(None)
    n0 = len(pg.escena["actores"])
    pg._boton_añadir_img()
    assert len(pg.escena["actores"]) == n0 and "Elige primero" in win.statusBar().currentMessage()
    print("✓ lista con imágenes pero nada elegido: lo dice (antes no pasaba nada)")
    win.go_page("edit")
    app.processEvents()
    ctrl2 = win.ctrl
    ctrl2.undo_stack.setClean()
    ctrl2._media_dirty = False
    if getattr(win, "_scenes_widget", None) is not None:
        win._scenes_widget.sucia = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
