"""
🖼 Miniaturas con «hover scrub» (23/11, el usuario: «eliminar las dos vistas flotantes; en la misma casilla todo es
visible, solo hay que mostrar más fotogramas»). Sin ventana (offscreen), sin la ventana principal y sin sonido:
  · pasar el ratón NO crea ninguna ventana flotante;
  · en un video, la casilla cambia de fotograma según dónde está el ratón (rojo a la izquierda, azul a la derecha) y
    vuelve a su miniatura al salir; una imagen no cambia;
  · la segunda vez, la tira sale de la caché en disco (al momento); mover el ratón cuesta menos de 16 ms;
  · reproduciendo, apagado.
Ejecutar (con el turno):  turno.py tests/test_scrub_miniaturas.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(_RAIZ, "_pruebas_tmp"), exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_scrub_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QEvent, QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QIcon, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListView, QListWidget, QListWidgetItem  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=20.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        pump(app, 0.03)
    return cond()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as MEDIA
    from editoria.ui import cola_analisis as CA
    from editoria.ui import miniaturas as MINI
    video = os.path.join(_TMP, "rojo_verde_azul.mp4")
    MEDIA.run_quiet([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y",
                     "-f", "lavfi", "-i", "color=red:s=320x180:d=1:r=25",
                     "-f", "lavfi", "-i", "color=lime:s=320x180:d=1:r=25",
                     "-f", "lavfi", "-i", "color=blue:s=320x180:d=1:r=25",
                     "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", video], timeout=60)
    imagen = os.path.join(_TMP, "foto.png")
    pm = QPixmap(320, 180)
    pm.fill(QColor("gray"))
    pm.save(imagen)
    assert os.path.isfile(video) and os.path.isfile(imagen)

    lista = QListWidget()
    lista.setViewMode(QListView.IconMode)
    lista.setIconSize(QSize(144, 81))
    lista.setGridSize(QSize(164, 120))
    lista.setMovement(QListView.Static)
    for ruta in (video, imagen):
        it = QListWidgetItem(os.path.basename(ruta))
        it.setData(Qt.UserRole, ruta)
        base = QPixmap(144, 81)
        base.fill(QColor("black"))
        it.setIcon(QIcon(base))
        lista.addItem(it)
    cambios = []
    lista.itemChanged.connect(lambda it: cambios.append(it))
    sc = MINI.activar_scrub(lista, lambda it: it.data(Qt.UserRole))
    lista.resize(400, 200)
    lista.show()
    pump(app, 0.2)
    ventanas = {id(w) for w in app.topLevelWidgets() if w.isVisible()}
    vp = lista.viewport()
    it_v, it_i = lista.item(0), lista.item(1)
    k_v, k_i = it_v.icon().cacheKey(), it_i.icon().cacheKey()
    r = lista.visualItemRect(it_v)

    def color_en(it) -> QColor:
        img = it.icon().pixmap(QSize(144, 81)).toImage()
        return img.pixelColor(img.width() // 2, img.height() // 3)

    # 1) primera vez: la tira se saca en segundo plano; mientras, la miniatura normal
    t0 = time.time()
    QTest.mouseMove(vp, QPoint(r.left() + 3, r.center().y()))
    assert it_v.icon().cacheKey() == k_v, "mientras no está la tira, la miniatura de siempre"
    assert esperar(app, lambda: sc.tira is not None, 30), "la tira llega"
    t_tira = time.time() - t0
    QTest.mouseMove(vp, QPoint(r.left() + 4, r.center().y()))
    c_izq = color_en(it_v)
    QTest.mouseMove(vp, QPoint(r.right() - 3, r.center().y()))
    c_der = color_en(it_v)
    QTest.mouseMove(vp, QPoint(r.center().x(), r.center().y()))
    c_med = color_en(it_v)
    assert c_izq.red() > 150 and c_izq.blue() < 100, ("a la izquierda, el principio (rojo)", c_izq.name())
    assert c_der.blue() > 150 and c_der.red() < 100, ("a la derecha, el final (azul)", c_der.name())
    assert c_med.green() > 150 and c_med.red() < 100, ("en medio, el medio (verde)", c_med.name())
    assert {id(w) for w in app.topLevelWidgets() if w.isVisible()} <= ventanas, "ninguna ventana flotante"
    assert not cambios, "sin itemChanged (no se avisa al modelo)"
    print(f"✓ la casilla cambia de fotograma según el ratón (rojo → verde → azul) y sin ventanas flotantes; "
          f"tira hecha en {t_tira:.2f} s")

    # 2) al salir, la miniatura normal; una imagen no cambia
    app.sendEvent(vp, QEvent(QEvent.Leave))
    assert it_v.icon().cacheKey() == k_v, "al salir, la miniatura de siempre"
    ri = lista.visualItemRect(it_i)
    QTest.mouseMove(vp, ri.center())
    pump(app, 0.3)
    QTest.mouseMove(vp, ri.center() + QPoint(5, 0))
    assert it_i.icon().cacheKey() == k_i, "una imagen no cambia"
    print("✓ al salir vuelve la miniatura; las imágenes no cambian")

    # 3) segunda vez: de la caché en disco, al momento; cada movimiento < 16 ms
    MINI._MEM.clear()
    app.sendEvent(vp, QEvent(QEvent.Leave))
    t0 = time.perf_counter()
    QTest.mouseMove(vp, QPoint(r.left() + 5, r.center().y()))
    t_disco = time.perf_counter() - t0
    assert sc.tira is not None and it_v.icon().cacheKey() != k_v, "la segunda vez, al momento (caché en disco)"
    sc.medidas.clear()
    sc._medir = True
    for k in range(300):
        x = r.left() + 2 + (k * 7) % (r.width() - 4)
        QTest.mouseMove(vp, QPoint(x, r.center().y() + (k % 3)))
    sc._medir = False
    med = sorted(sc.medidas)
    assert med and med[-1] < 0.016, f"un movimiento tardó {med[-1] * 1000:.1f} ms"
    print(f"✓ segunda vez desde el disco en {t_disco * 1000:.1f} ms; {len(med)} movimientos: media "
          f"{sum(med) / len(med) * 1000:.2f} ms, máx. {med[-1] * 1000:.2f} ms")

    # 4) reproduciendo: apagado
    app.sendEvent(vp, QEvent(QEvent.Leave))
    CA.al_reproducir(True, "prueba")
    QTest.mouseMove(vp, QPoint(r.right() - 4, r.center().y()))
    QTest.mouseMove(vp, QPoint(r.right() - 6, r.center().y()))
    assert it_v.icon().cacheKey() == k_v, "reproduciendo, nada de scrub"
    CA.al_reproducir(False, "prueba")
    QTest.mouseMove(vp, QPoint(r.right() - 8, r.center().y()))
    assert it_v.icon().cacheKey() != k_v, "al parar, vuelve"
    app.sendEvent(vp, QEvent(QEvent.Leave))
    print("✓ reproduciendo (o exportando) el scrub se apaga")
    lista.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
