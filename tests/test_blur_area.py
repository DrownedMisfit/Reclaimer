"""
Miniatura · 🌫 Zona borrosa (el usuario: «una opción de borroso: selecciono la opción y me da dos formas, circular o
cuadrada, y la puedo estirar conforme yo quiera con mi mouse»):
  · 🌫 Borroso ▾ → Círculo / Cuadrado: se arrastra el recuadro en el lienzo y se crea la zona (Mayús = perfecta);
  · la zona desenfoca lo que hay DEBAJO, dentro de su forma (el círculo no toca las esquinas de su recuadro);
  · las esquinas estiran en las dos direcciones; los lados, solo ancho o solo alto;
  · Ctrl+Z deshace; ocultarla quita el efecto; «Fuerza» en el panel;
  · mover la zona sobre dos imágenes grandes: menos de 30 ms por movimiento (media de 10).
Sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_blur_area.py <carpeta>
"""
from __future__ import annotations

import copy
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
from PySide6.QtGui import QImage, QMouseEvent, QPainter  # noqa: E402
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
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_blur_area")
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
    cv = ed.canvas
    cv.set_zoom(8.0)                    # (ventana chica: con zoom, el ratón tiene más precisión)
    pump(app, 0.1)

    # dos imágenes grandes de ruido (fondo + foto): el «detalle» es alto y el desenfoque se nota
    rng = np.random.default_rng(7)
    fondo = os.path.join(out, "ruido_fondo.png")
    Image.fromarray((rng.random((720, 1280, 3)) * 255).astype(np.uint8)).save(fondo)
    foto = os.path.join(out, "ruido_foto.png")
    Image.fromarray((rng.random((1250, 2000, 3)) * 255).astype(np.uint8)).save(foto)
    ed.add_image(fondo, "Fondo", fill=True)
    ed.add_image(foto, "Foto")
    foto_id = ed.cur()["id"]

    def ev(kind, pt, buttons=Qt.LeftButton, mods=Qt.NoModifier):
        vp = cv.mapFromScene(pt)
        return QMouseEvent(kind, QPointF(vp), QPointF(cv.viewport().mapToGlobal(vp)), Qt.LeftButton, buttons, mods)

    def alinear(pt):
        return cv.mapToScene(cv.mapFromScene(pt))

    def arrastrar(p0, p1, mods=Qt.NoModifier, pasos=4):
        p0, p1 = alinear(p0), alinear(p1)
        cv.mousePressEvent(ev(QEvent.MouseButtonPress, p0, mods=mods))
        for i in range(1, pasos + 1):
            cv.mouseMoveEvent(ev(QEvent.MouseMove, alinear(p0 + (p1 - p0) * (i / pasos)), mods=mods))
        cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, p1, Qt.NoButton, mods))
        pump(app, 0.05)
        return p0, p1

    def zona_por_id(zid):
        return ed.layer(zid)

    def sin_zona(zid):
        d = copy.deepcopy(ed.doc)
        d["layers"] = [l for l in d["layers"] if l["id"] != zid]
        return d

    # 1) 🌫 Borroso ▾ → Círculo: arrastrar el recuadro crea la zona (y queda elegida; la herramienta se apaga)
    ed.blur_btn.menu().actions()[0].trigger()
    assert cv.tool == "blurzone" and cv.blur_shape == "ellipse", (cv.tool, cv.blur_shape)
    arrastrar(QPointF(400, 200), QPointF(700, 500))
    assert cv.tool is None, "la herramienta debe apagarse al crear la zona"
    circ = ed.cur()
    assert circ.get("blur_area") and circ.get("shape") == "ellipse", circ
    assert circ["name"] == "🌫 Borroso (círculo)", circ["name"]
    assert abs(circ["w"] - 300) <= 3 and abs(circ["h"] - 300) <= 3, (circ["w"], circ["h"])
    assert abs(circ["x"] - 550) < 3 and abs(circ["y"] - 350) < 3, (circ["x"], circ["y"])
    assert circ["blur_area"]["radius"] == 18
    print("✓ 🌫 Borroso ▾ → Círculo: arrastrar crea la zona circular con ese tamaño y sitio; queda elegida")

    # 2) Cuadrado: otra zona, arriba a la izquierda (no se pisa demasiado con la del círculo)
    ed.blur_btn.menu().actions()[1].trigger()
    arrastrar(QPointF(80, 420), QPointF(380, 660))
    cuad = ed.cur()
    assert cuad.get("blur_area") and cuad.get("shape") == "rect" and cuad["name"] == "🌫 Borroso (cuadrado)", cuad
    print("✓ 🌫 Borroso ▾ → Cuadrado: crea la zona cuadrada")

    # 3) Un clic sin arrastrar: una zona de tamaño normal centrada en el clic
    ed.blur_btn.menu().actions()[0].trigger()
    cv.mousePressEvent(ev(QEvent.MouseButtonPress, QPointF(1000, 300)))
    cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, QPointF(1000, 300), Qt.NoButton))
    pequena = ed.cur()
    assert abs(pequena["w"] - 320) <= 3 and abs(pequena["x"] - 1000) < 3, (pequena["w"], pequena["x"])
    ed.undo()
    assert ed.layer(pequena["id"]) is None, "deshacer quita la zona de prueba"
    print("✓ un clic sin arrastrar crea una zona de tamaño normal centrada en el clic")

    # 4) Se nota solo dentro de su forma; fuera, nada cambia
    cv.sel = circ["id"]
    sin_c = sin_zona(circ["id"])
    base = T.qimage_to_rgba(T.render(sin_c))
    res = T.qimage_to_rgba(T.render(ed.doc))
    dentro = (slice(320, 380), slice(520, 580))          # el centro del círculo (550, 350)
    assert detalle(res[dentro]) < detalle(base[dentro]) * 0.4, (detalle(base[dentro]), detalle(res[dentro]))
    fuera = (slice(40, 200), slice(900, 1200))           # lejos de las dos zonas
    assert np.array_equal(res[fuera], base[fuera]), "fuera de la zona no debe cambiar nada"
    print(f"✓ dentro del círculo el detalle baja ({detalle(base[dentro]):.1f} → {detalle(res[dentro]):.1f}); "
          "fuera no cambia nada")

    # 5) El círculo no toca las esquinas de su recuadro; el cuadrado sí
    esq_c = (slice(203, 213), slice(403, 413))           # esquina del recuadro del círculo (400..700, 200..500)
    assert np.array_equal(res[esq_c], base[esq_c]), "el círculo no debe desenfocar las esquinas de su recuadro"
    esq_q = (slice(423, 463), slice(83, 123))            # esquina del recuadro del cuadrado (80..380, 420..660)
    s_c = T.qimage_to_rgba(T.render(sin_zona(cuad["id"])))
    res_q = T.qimage_to_rgba(T.render(ed.doc))
    assert detalle(res_q[esq_q]) < detalle(s_c[esq_q]) * 0.5, "el cuadrado sí desenfoca hasta su esquina"
    print("✓ el círculo no desenfoca las esquinas de su recuadro; el cuadrado sí hasta la esquina")

    # 6) Estirar con un lado: solo cambia ancho (lado derecho) o solo alto (lado de abajo)
    pump(app, 0.9)                                       # (que el deshacer no mezcle los pasos)
    cv.sel = circ["id"]
    cv.viewport().update()
    h = cv._handles(ed.layer(circ["id"]))
    lado_d = cv._side_points(h["corners"])["r"]
    p0, p1 = arrastrar(lado_d, lado_d + QPointF(80, 0))
    c1 = dict(ed.layer(circ["id"]))
    dx = p1.x() - p0.x()
    assert abs(c1["w"] - (300 + dx)) <= 3 and c1["h"] == 300, (c1["w"], c1["h"], dx)
    assert abs(c1["x"] - (550 + dx / 2)) <= 3 and abs(c1["y"] - 350) < 3, (c1["x"], c1["y"])
    print(f"✓ el lado derecho estira solo el ancho: {circ['w']}×{circ['h']} → {c1['w']}×{c1['h']}")
    pump(app, 0.9)
    h = cv._handles(ed.layer(circ["id"]))
    lado_b = cv._side_points(h["corners"])["b"]
    p0, p1 = arrastrar(lado_b, lado_b + QPointF(0, 60))
    c2 = dict(ed.layer(circ["id"]))
    dy = p1.y() - p0.y()
    assert c2["w"] == c1["w"] and abs(c2["h"] - (300 + dy)) <= 3, (c2["w"], c2["h"], dy)
    print(f"✓ el lado de abajo estira solo el alto: → {c2['w']}×{c2['h']}")

    # 7) Una esquina sin Mayús cambia ancho y alto de forma distinta
    pump(app, 0.9)
    h = cv._handles(ed.layer(circ["id"]))
    esquina = h["corners"][2]                            # abajo a la derecha
    p0, p1 = arrastrar(esquina, esquina + QPointF(50, 20))
    c3 = dict(ed.layer(circ["id"]))
    dw, dh = c3["w"] - c2["w"], c3["h"] - c2["h"]
    ex, ey = p1.x() - p0.x(), p1.y() - p0.y()
    assert abs(dw - ex) <= 3 and abs(dh - ey) <= 3 and abs(dw - dh) > 3, (dw, dh, ex, ey)
    print(f"✓ una esquina sin Mayús: ancho +{dw}, alto +{dh} (distinto, libre)")

    # 8) Ctrl+Z deshace ese último estirado
    pump(app, 0.9)
    ed.undo()
    u = ed.layer(circ["id"])
    assert u["w"] == c2["w"] and u["h"] == c2["h"], (u["w"], u["h"], c2["w"], c2["h"])
    print("✓ Ctrl+Z (deshacer) quita el último estirado")

    # 9) «Fuerza» en el panel: más fuerza = más borroso
    d_small = detalle(T.qimage_to_rgba(T.render(ed.doc))[dentro])
    ed._set(ed.layer(circ["id"]), "Fuerza", **{"blur_area.radius": 45})
    d_big = detalle(T.qimage_to_rgba(T.render(ed.doc))[dentro])
    assert d_big < d_small, (d_small, d_big)
    ed._set(ed.layer(circ["id"]), "Fuerza", **{"blur_area.radius": 18})
    print(f"✓ «Fuerza» en el panel: 45 → más borroso ({d_small:.1f} → {d_big:.1f})")

    # 10) Ocultar la zona quita el efecto
    cv.sel = circ["id"]
    ed.toggle_visible()
    oculta = T.qimage_to_rgba(T.render(ed.doc))
    assert not ed.layer(circ["id"])["visible"]
    assert np.array_equal(oculta[dentro], base[dentro]), "con la zona oculta no debe haber efecto"
    ed.toggle_visible()
    assert ed.layer(circ["id"])["visible"]
    print("✓ ocultar la zona quita el efecto; mostrarla lo devuelve")

    # 11) Rendimiento: mover la zona sobre las dos imágenes grandes (media de 10 movimientos)
    pump(app, 0.9)
    cv.sel = circ["id"]
    lay = ed.layer(circ["id"])
    arrastrar(QPointF(lay["x"], lay["y"]), QPointF(lay["x"] + 3, lay["y"] + 3), pasos=2)   # (calienta la caché)
    tiempos_move, tiempos_render, tiempos_lienzo = [], [], []
    for i in range(10):
        p0 = QPointF(ed.layer(circ["id"])["x"], ed.layer(circ["id"])["y"])
        cv.mousePressEvent(ev(QEvent.MouseButtonPress, p0))
        t0 = time.perf_counter()
        cv.mouseMoveEvent(ev(QEvent.MouseMove, p0 + QPointF(6 + i, 4)))
        tiempos_move.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        T.render(ed.doc)
        tiempos_render.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        cv.grab()
        tiempos_lienzo.append((time.perf_counter() - t0) * 1000)
        cv.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, p0 + QPointF(6 + i, 4), Qt.NoButton))
    # solo la zona: lo que cambia en cada movimiento (el lienzo entero va aparte)
    zona = ed.layer(circ["id"])
    idx = next(i for i, l in enumerate(ed.doc["layers"]) if l["id"] == circ["id"])
    t_zona = []
    for _ in range(10):
        img = QImage(1280, 720, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.black)
        p = QPainter(img)
        t0 = time.perf_counter()
        T.paint_blur_area(p, ed.doc, idx, zona, 1.0)
        t_zona.append((time.perf_counter() - t0) * 1000)
        p.end()
    m_move, m_render = np.mean(tiempos_move), np.mean(tiempos_render)
    m_lienzo, m_zona = np.mean(tiempos_lienzo), np.mean(t_zona)
    print(f"  tiempos (media de 10, ms): mover={m_move:.1f} · exportar={m_render:.1f} · lienzo (grab)={m_lienzo:.1f}"
          f" · solo la zona={m_zona:.1f}")
    assert m_move < 30 and m_zona < 30, (m_move, m_zona)
    print("✓ mover la zona: menos de 30 ms por movimiento (medido arriba)")

    # 12) Lo elegido lleva su recuadro y sus asas; sin elegir, solo se ve borroso
    cv.sel = circ["id"]
    assert cv._is_zone(ed.layer(circ["id"]))
    cv.sel = ""
    cv.viewport().update()

    win.go_page("edit")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
