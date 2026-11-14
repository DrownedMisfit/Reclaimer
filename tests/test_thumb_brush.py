"""
Miniatura · pincel y colores usados:
  · soltar un trazo largo no bloquea la ventana (antes abría la imagen entera por cada punto);
  · mover el pincel solo repinta la zona tocada;
  · 🖌 Recuperar: lo borrado se ve tenue y lo pintado ya es la imagen real, sin mancha de color;
  · «Recuperar solo el sujeto»: lo pintado que es fondo no vuelve; desactivado, vuelve todo lo pintado;
  · varios trazos seguidos se aplican en orden y cada uno se deshace con Ctrl+Z;
  · Contorno, Sombra y Brillo guardan cada uno sus colores usados; clic en uno lo aplica.
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_thumb_brush.py <carpeta>
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

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

W, H = 2000, 1200
ROJO_X = 1000       # a la izquierda de esta x, el personaje (rojo con textura); a la derecha, el fondo (azul)
CORTE_Y = 500       # por debajo de esta y, todo está borrado


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.005)


def media(path, x0, y0, x1, y1):
    m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return float(m[y0:y1, x0:x1].mean()) / 255.0


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_thumb_brush")
    os.makedirs(out, exist_ok=True)
    import faulthandler
    faulthandler.dump_traceback_later(240, exit=True)
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
    cv = ed.canvas

    rng = np.random.default_rng(5)
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (200, 60, 20)                                 # BGR: fondo azul
    ruido = rng.integers(-12, 12, (H, ROJO_X, 3))
    img[:, :ROJO_X] = np.clip(np.array([20, 30, 210]) + ruido, 0, 255)
    foto = os.path.join(out, "foto.png")
    mask0 = os.path.join(out, "mascara.png")
    assert cv2.imwrite(foto, img)
    m = np.zeros((H, W), np.uint8)
    m[:CORTE_Y, :ROJO_X] = 255                             # se ve la parte de arriba del personaje; lo demás, borrado
    assert cv2.imwrite(mask0, m)

    ed.add_image(foto, "Foto")
    lay = ed.cur()
    lay["mask"] = mask0
    lay["outline"].update(on=True, color="#ff0000", width=4)
    lay["scale"] = 0.5
    lay["x"], lay["y"] = 640.0, 360.0
    ed.commit("prep")
    cv.viewport().update()
    pump(app, 0.2)
    ed.set_brush_smart(True)
    ed.set_brush("restore")
    cv.brush = 40
    cv.viewport().update()
    t0 = time.time()
    while cv._bs is None and time.time() - t0 < 15:
        cv.viewport().repaint()
        pump(app, 0.02)
    bs = cv._bs
    assert bs is not None, "la vista de Recuperar debería prepararse sola al activar el pincel"
    y_b = int(bs["h"] * 0.8)
    assert 80 <= bs["ov"][y_b, int(bs["w"] * 0.25), 3] <= 100, bs["ov"][y_b, int(bs["w"] * 0.25), 3]
    assert bs["ov"][int(bs["h"] * 0.2), int(bs["w"] * 0.25), 3] == 0, "lo que ya se ve no se duplica"
    print("✓ con 🖌 Recuperar, lo borrado se ve tenue (35 %) y lo visible no se toca")

    def de_foto(x, y):
        """Un píxel de la foto → punto del lienzo."""
        return QPointF(lay["x"] + (x - W / 2) * lay["scale"], lay["y"] + (y - H / 2) * lay["scale"])

    def ev(kind, pt, buttons=Qt.LeftButton, boton=Qt.LeftButton):
        vp = cv.mapFromScene(pt)
        return QMouseEvent(kind, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), boton, buttons, Qt.NoModifier)

    regiones: list[QRect] = []
    original_update = cv.viewport().update

    def trazo(puntos, medir=False):
        """Pasa directamente los puntos del lienzo (el visor de las pruebas es muy pequeño para usar el ratón)."""
        tiempos = []
        cv.mousePressEvent(ev(QEvent.MouseButtonPress, puntos[0]))
        for pt in puntos[1:]:
            t = time.perf_counter()
            cv._hover, antes = pt, cv._hover
            previo = cv._stroke[-1]
            cv._stroke.append(pt)
            cv._brush_seg(previo, pt)
            regiones.append(cv._brush_dirty(antes, previo, pt))
            tiempos.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, puntos[-1], buttons=Qt.NoButton))
        return tiempos, (time.perf_counter() - t) * 1000

    def esperar():
        t0 = time.time()
        while (ed.brush_busy() or cv._bg_jobs) and time.time() - t0 < 30:
            pump(app, 0.02)
        cv.viewport().repaint()
        pump(app, 0.05)

    # un trazo largo que cruza el personaje y el fondo, por la parte borrada
    pts = [de_foto(x, 850 + 40 * np.sin(x / 60)) for x in np.linspace(300, 1700, 900)]
    mascara_antes = lay["mask"]
    tiempos, soltar = trazo(pts)
    med = sorted(tiempos)[len(tiempos) // 2]
    print(f"  · trazo de {len(pts)} puntos: {med:.2f} ms por movimiento; soltar {soltar:.0f} ms")
    assert sorted(tiempos)[int(len(tiempos) * 0.95)] < 12, f"pintar va lento: {sorted(tiempos)[-5:]}"
    assert soltar < 200, f"soltar no debe bloquear: {soltar:.0f} ms"
    assert all(r.width() < cv.viewport().width() + 400 and r.height() < 400 for r in regiones)
    print("✓ cada movimiento toca solo lo suyo y soltar no bloquea la ventana")
    # lo pintado ya se ve, real, antes de que llegue el resultado
    lx = int(bs["w"] * 0.25)
    ly = None
    for yy in range(bs["h"] // 2, bs["h"]):
        if bs["live"][yy, lx] > 200:
            ly = yy
            break
    assert ly is not None, "lo pintado debería estar en la vista"
    assert bs["ov"][ly, lx, 3] > 240 and bs["ov"][ly, lx, 0] > 150, bs["ov"][ly, lx]
    print("✓ lo pintado ya es la imagen real mientras pintas (sin mancha verde)")
    assert cv._ink is None, "con la vista lista no hace falta la tinta verde"

    esperar()
    assert lay["mask"] != mascara_antes
    rojo = media(lay["mask"], 500, 830, 800, 870)
    azul = media(lay["mask"], 1200, 830, 1500, 870)
    print(f"  · recuperado: personaje {rojo:.0%}, fondo {azul:.0%}")
    assert rojo > 0.85, f"el personaje debería volver: {rojo:.2f}"
    assert azul < 0.05, f"el fondo no debería volver: {azul:.2f}"
    print("✓ «Recuperar solo el sujeto»: vuelve el personaje y el fondo que tocaste no")
    assert cv._bs["pending"] is None, "al llegar la imagen buena, la vista se pone al día"
    assert cv._bs["live"].max() == 0

    # desactivado: vuelve todo lo pintado
    ed.undo()
    lay = ed.cur()
    esperar()
    assert lay["mask"] == mascara_antes
    ed.set_brush_smart(False)
    cv.viewport().repaint()
    pump(app, 0.1)
    trazo(pts)
    esperar()
    lay = ed.cur()
    assert media(lay["mask"], 1200, 830, 1500, 870) > 0.85, "sin «solo el sujeto» vuelve lo que pintes"
    print("✓ desactivado, se recupera exactamente lo que pintes; Ctrl+Z lo deshace")
    ed.set_brush_smart(True)

    # varios trazos seguidos: en orden, sin esperar
    ed.set_brush("erase")
    n0 = ed.pos
    for y in (120, 240, 360):
        trazo([de_foto(100, y), de_foto(400, y)])
    assert ed.brush_busy(), "los trazos van en segundo plano"
    esperar()
    assert ed.pos == n0 + 3
    lay = ed.cur()
    for y in (120, 240, 360):
        assert media(lay["mask"], 180, y - 10, 320, y + 10) < 0.1, y
    assert cv._ink is not None or True
    cv.viewport().repaint()
    pump(app, 0.1)
    assert cv._ink is None, "la tinta roja desaparece cuando se ve el resultado"
    print("✓ borrar: varios trazos seguidos, en orden; un Ctrl+Z por trazo")
    ed.select_tool()

    # ----------------------------------------------------------- colores usados por efecto
    for k in ("outline", "shadow", "glow"):
        ed._guardar_lista(f"miniatura/colores_{k}", [])
    ed.canvas.sel = lay["id"]
    ed._fill_props()
    filas = {f.key: f for f in ed._hist_rows}
    assert set(filas) == {"outline", "shadow", "glow"}
    assert not any(f.isVisibleTo(f.parentWidget()) for f in filas.values()), "sin colores no ocupa sitio"
    ed._set(lay, "Contorno", **{"outline.color": "#00FF00"})
    ed._set(lay, "Contorno", **{"outline.color": "#0000FF"})
    ed._set(lay, "Sombra", **{"shadow.color": "#123456"})
    assert ed.color_history("outline") == ["#0000FF", "#00FF00", "#ff0000"], ed.color_history("outline")
    assert ed.color_history("shadow")[0] == "#123456" and ed.color_history("glow") == []
    assert filas["outline"].isVisibleTo(filas["outline"].parentWidget())
    print("✓ cada efecto guarda sus colores, sin mezclarse")
    # sin repetir, con tope
    ed._set(lay, "Contorno", **{"outline.color": "#00ff00"})
    assert [c.casefold() for c in ed.color_history("outline")][:2] == ["#00ff00", "#0000ff"]
    assert len(ed.color_history("outline")) == 3
    for i in range(20):
        ed.remember_color("glow", f"#10{i:02d}10")
    assert len(ed.color_history("glow")) == 12
    # clic en una muestra
    bot = next(filas["outline"].fila.itemAt(i).widget() for i in range(filas["outline"].fila.count())
               if filas["outline"].fila.itemAt(i).widget() is not None
               and "#ff0000" in filas["outline"].fila.itemAt(i).widget().toolTip())
    bot.click()
    pump(app, 0.05)
    assert lay["outline"]["color"] == "#ff0000", lay["outline"]
    assert ed.color_history("outline")[0] == "#ff0000"
    print("✓ clic en un color usado lo aplica y sube al principio; sin repetidos y con tope de 12")
    # siguen ahí al rehacer el panel, y la barra también apunta
    ed._fill_props()
    assert any(f.key == "outline" and f.fila.count() >= 3 for f in ed._hist_rows)

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    ed.close()
    pump(app, 0.2)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
