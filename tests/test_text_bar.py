"""
Barra flotante del texto elegido en el taller de miniaturas (editoria/ui/thumb_text_bar.py):
  · al elegir un texto aparece encima (o debajo) de su recuadro y no se aleja de él;
  · al elegir una imagen se oculta; también con una herramienta activa, bloqueado o mientras se arrastra;
  · color rápido (menú), contorno, sombra, brillo, tamaño, «🔥 Mi estilo»: cada uno es un paso de deshacer;
  · tras arrastrar el texto, la barra lo sigue.
Los menús no se abren: se disparan sus acciones (QAction.trigger), igual que si el usuario eligiera.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_text_bar.py <carpeta>
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
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import thumbnail as T  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def accion(menu, texto):
    """Dispara la acción de un menú por su texto (sin abrir el menú)."""
    for a in menu.actions():
        if a.text() == texto:
            a.trigger()
            return
    raise AssertionError(f"no hay «{texto}» en el menú")


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_text_bar")
    os.makedirs(out, exist_ok=True)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.setGeometry(0, 0, 1600, 1000)
    pump(app, 0.3)
    ed = win.open_thumbnail("youtube")
    pump(app, 0.3)
    cv = ed.canvas
    tb = ed.text_bar
    vp = cv.viewport()

    p = os.path.join(out, "fondo.png")
    Image.fromarray(np.full((600, 1000, 3), (40, 90, 160), np.uint8)).save(p)
    ed.add_image(p, "Fondo")
    img_id = ed.cur()["id"]
    ed.add_text("TEXTO DE PRUEBA", "title")
    txt_id = ed.cur()["id"]
    pump(app, 0.1)

    def elegir(lid):
        cv.sel = lid
        cv.selected.emit(lid)
        cv.viewport().repaint()
        pump(app, 0.05)

    def lay(lid=None):
        return ed.layer(lid or txt_id)

    def distancia_a_recuadro():
        r = cv.mapFromScene(cv._box(lay())).boundingRect()
        g = tb.geometry()
        dx = max(0, r.left() - g.right(), g.left() - r.right())
        dy = max(0, r.top() - g.bottom(), g.top() - r.bottom())
        return max(dx, dy)

    # 1) texto elegido → barra visible y cerca del recuadro
    elegir(txt_id)
    assert tb.isVisibleTo(vp), "la barra debería verse con el texto elegido"
    d = distancia_a_recuadro()
    assert d <= 80, f"la barra está a {d} px del texto"
    print(f"✓ con el texto elegido, la barra aparece junto al texto (a {d} px del recuadro)")

    # 2) imagen elegida → oculta
    elegir(img_id)
    assert not tb.isVisibleTo(vp), "con una imagen elegida la barra debe ocultarse"
    print("✓ con una imagen elegida la barra se oculta")

    # 3) color rápido amarillo y deshacer
    elegir(txt_id)
    color0 = lay()["color"]
    accion(tb.btn_color.menu(), "Amarillo")
    assert lay()["color"] == "#FFD400", lay()["color"]
    ed.undo()
    assert ed.layer(txt_id)["color"] == color0, ed.layer(txt_id)["color"]
    print(f"✓ color rápido amarillo (#FFD400); Ctrl+Z lo devuelve a {color0}")

    # 4) contorno: interruptor, color y grosor
    on0 = bool(lay()["outline"]["on"])
    tb.btn_cont.click()
    assert bool(lay()["outline"]["on"]) != on0, "el contorno no cambió"
    tb.btn_cont.click()
    assert bool(lay()["outline"]["on"]) == on0
    accion(tb.btn_cont_color.menu(), "Rojo")
    assert lay()["outline"]["color"] == T.MY_RED and lay()["outline"]["on"]
    accion(tb.btn_cont_grosor.menu(), "12 px")
    assert lay()["outline"]["width"] == 12
    print("✓ contorno se activa/desactiva, cambia de color y de grosor (12 px)")

    # 5) sombra: interruptor y estilo «Dura»
    son0 = bool(lay()["shadow"]["on"])
    tb.btn_sombra.click()
    assert bool(lay()["shadow"]["on"]) != son0
    tb.btn_sombra.click()
    accion(tb.btn_sombra_estilo.menu(), "Dura")
    s = lay()["shadow"]
    assert s["on"] and s["blur"] == 0 and s["dx"] == 8, s
    print("✓ sombra se activa/desactiva y tiene estilo «Dura»")

    # 6) brillo: interruptor y color
    gon0 = bool(lay()["glow"]["on"])
    tb.btn_brillo.click()
    assert bool(lay()["glow"]["on"]) != gon0
    accion(tb.btn_brillo_color.menu(), "Azul")
    assert lay()["glow"]["color"] == "#2F8CFF" and lay()["glow"]["on"]
    print("✓ brillo se activa y cambia de color (azul)")

    # 7) tamaño A+ / A−
    s0 = lay()["size"]
    tb.btn_mas.click()
    s1 = lay()["size"]
    assert s1 > s0, (s0, s1)
    tb.btn_menos.click()
    assert lay()["size"] < s1
    print(f"✓ A+ sube el tamaño ({s0} → {s1}) y A− lo baja")

    # 8) negrita y cursiva
    w0 = int(lay()["weight"])                       # (el texto del taller arranca en negrita: el botón lo marca)
    tb.btn_b.click()
    assert int(lay()["weight"]) == (400 if w0 >= 600 else 700), (w0, lay()["weight"])
    tb.btn_b.click()
    assert int(lay()["weight"]) == w0
    tb.btn_i.click()
    assert lay()["italic"] is True
    print("✓ negrita (700) y cursiva se aplican desde la barra")
    # 8b) alineación: izquierda / centrado / derecha (como botones de radio)
    assert tb.btn_align["center"].isChecked() and lay()["align"] == "center"
    tb.btn_align["left"].click()
    assert lay()["align"] == "left" and tb.btn_align["left"].isChecked() and not tb.btn_align["center"].isChecked()
    tb.btn_align["right"].click()
    assert lay()["align"] == "right" and [h for h, b in tb.btn_align.items() if b.isChecked()] == ["right"]
    tb.btn_align["right"].click()                   # (pulsar el ya marcado no lo desmarca)
    assert lay()["align"] == "right" and tb.btn_align["right"].isChecked()
    ed.undo()                                       # (cambios seguidos de alineación = un solo paso, como los deslizadores)
    assert lay()["align"] == "center", lay()["align"]
    assert tb.btn_align["center"].isChecked() or (tb.update_pos() or tb.btn_align["center"].isChecked())
    print("✓ alineación izquierda / centrado / derecha desde la barra; Ctrl+Z la devuelve")

    # 9) «🔥 Mi estilo»: Anton y conserva texto y sitio
    antes = dict(text=lay()["text"], x=lay()["x"], y=lay()["y"])
    tb.btn_mi_estilo.click()
    now = lay()
    assert now["font"] == "Anton", now["font"]
    assert (now["text"], now["x"], now["y"]) == (antes["text"], antes["x"], antes["y"]), (antes, now["x"])
    print("✓ «Mi estilo» pone la fuente Anton y conserva el texto, x e y")

    # 10) fuente desde el menú
    accion(tb.btn_fuente.menu(), "Bahnschrift")
    assert lay()["font"] == "Bahnschrift"
    print("✓ fuente desde el menú (Bahnschrift)")

    # 11) arrastrar el texto: la barra se oculta mientras se arrastra y luego lo sigue
    elegir(txt_id)
    lx, ly = float(lay()["x"]), float(lay()["y"])
    c = QPointF(lx, ly)

    def ev(kind, pt, buttons=Qt.LeftButton):
        v = cv.mapFromScene(pt)
        return QMouseEvent(kind, QPointF(v), QPointF(vp.mapToGlobal(v)), Qt.LeftButton, buttons, Qt.ControlModifier)

    cv.mousePressEvent(ev(QEvent.MouseButtonPress, c))
    cv.mouseMoveEvent(ev(QEvent.MouseMove, c + QPointF(60, 0)))
    vp.repaint()
    pump(app, 0.05)
    assert not tb.isVisibleTo(vp), "mientras se arrastra la barra debe ocultarse"
    cv.mouseMoveEvent(ev(QEvent.MouseMove, c + QPointF(260, 40)))
    cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, c + QPointF(260, 40), Qt.NoButton))
    vp.repaint()
    pump(app, 0.05)
    assert lay()["x"] != lx, "el texto no se movió"
    assert tb.isVisibleTo(vp), "al soltar, la barra vuelve"
    d = distancia_a_recuadro()
    assert d <= 80, f"tras mover, la barra está a {d} px"
    print(f"✓ arrastrar oculta la barra; al soltar la barra sigue al texto (a {d} px)")

    # 12) herramienta activa o capa bloqueada → oculta
    cv.tool = "erase"
    vp.repaint()
    assert not tb.isVisibleTo(vp)
    cv.tool = None
    lay()["locked"] = True
    vp.repaint()
    assert not tb.isVisibleTo(vp), "un texto bloqueado no debe tener barra"
    lay()["locked"] = False
    vp.repaint()
    assert tb.isVisibleTo(vp)
    print("✓ con una herramienta activa o un texto bloqueado la barra se oculta")

    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
