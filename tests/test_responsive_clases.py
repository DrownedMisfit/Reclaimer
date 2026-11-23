"""
↔ Lo que hace responsive.py funciona de verdad en widgets YA mostrados, pintados y medidos (revisión de Fable 17/11:
¿no ignorará Qt los métodos nuevos si ya los llamó antes de cambiar la clase?). Para un botón, una casilla y un
desplegable que ya se pintaron, se midieron y recibieron su ayuda emergente:
  · tras adaptarlos y estrechar el panel, Qt llama al dibujo NUEVO (contador) y el texto sale partido en varias
    líneas (se cuentan las filas de píxeles con letra),
  · los mínimos nuevos los usa la distribución (el panel se deja estrechar),
  · la ayuda emergente da el texto entero (desplegable acortado y botón con alto fijo),
  · lo que se añade 60 ms después (vigía) también se adapta y se pinta partido.
Ejecutar:  .venv/Scripts/python.exe tests/test_responsive_clases.py
"""
from __future__ import annotations

import os
import sys
import time

# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QEvent, QPoint  # noqa: E402
from PySide6.QtGui import QHelpEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QPushButton, QToolTip, QVBoxLayout,  # noqa: E402
                               QWidget)


def pump(app, s=0.1):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def filas_con_letra(w) -> int:
    """Filas de píxeles con letra (más oscuras que el fondo del control): una línea de texto ≈ una altura de letra."""
    im = w.grab().toImage()
    x0 = 24 if isinstance(w, QCheckBox) else 6
    n = 0
    for y in range(2, im.height() - 2):
        if any(im.pixelColor(x, y).lightness() < 70 for x in range(x0, im.width() - 6)):
            n += 1
    return n


def ayuda(app, w) -> str:
    QToolTip.hideText()
    app.sendEvent(w, QHelpEvent(QEvent.ToolTip, QPoint(4, 4), w.mapToGlobal(QPoint(4, 4))))
    return QToolTip.text()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    from editoria.ui import responsive as R
    caja = QWidget()
    v = QVBoxLayout(caja)
    largo_b = "Texto de un botón bastante largo que no cabe"
    largo_c = "Casilla con un texto bastante largo que no cabe"
    largo_d = "Opción muy larga del desplegable que no cabe"
    b = QPushButton(largo_b)
    c = QCheckBox(largo_c)
    d = QComboBox()
    d.addItem(largo_d)
    b_fijo = QPushButton("Otro botón con texto largo y alto fijo")
    b_fijo.setFixedHeight(26)
    for w in (b, c, d, b_fijo):
        v.addWidget(w)
    v.addStretch()
    caja.resize(700, 300)
    caja.show()
    pump(app, 0.2)
    linea = filas_con_letra(c)
    for w in (b, c, d, b_fijo):                  # (ya pintados, medidos y con su ayuda: lo que podría «cachear»)
        w.grab()
        w.minimumSizeHint()
        w.sizeHint()
        ayuda(app, w)
    assert caja.minimumSizeHint().width() > 300, caja.minimumSizeHint().width()

    # contador en el dibujo nuevo (se mira la clase de la mezcla: la subclase lo hereda en cada llamada)
    pintados = {}
    originales = {}
    for mezcla in (R._BotonMulti, R._CasillaMulti, R._ComboAcorta):
        originales[mezcla] = mezcla.paintEvent

        def contar(self, ev, _o=originales[mezcla]):
            pintados[id(self)] = pintados.get(id(self), 0) + 1
            return _o(self, ev)
        mezcla.paintEvent = contar
    try:
        R.adaptar(caja)
        pump(app, 0.1)
        assert R.es_multilinea(b) and R.es_multilinea(c) and R.es_desplegable_que_acorta(d)
        mini = caja.minimumSizeHint().width()
        assert mini < 200, f"la distribución no usa los mínimos nuevos ({mini} px)"
        caja.setMinimumSize(0, 0)
        caja.resize(150, 420)
        pump(app, 0.2)
        assert caja.width() == 150 and b.width() <= 150 and c.width() <= 150, (caja.width(), b.width(), c.width())
        for w in (b, c, d):
            w.grab()
        assert pintados.get(id(b)) and pintados.get(id(c)) and pintados.get(id(d)), \
            f"Qt no llama al dibujo nuevo: {pintados}"
        assert len(b._lineas(b.width())) >= 3 and len(c._lineas(c.width())) >= 3
        assert b.height() >= b.heightForWidth(b.width()) - 2 and c.height() >= c.heightForWidth(c.width()) - 2
        filas = filas_con_letra(c)
        assert filas >= 2.5 * linea, f"la casilla no se pinta en varias líneas ({filas} filas con letra; una: {linea})"
        print(f"✓ ya mostrados y pintados: tras adaptarlos, Qt usa el dibujo nuevo y el texto sale en "
              f"{len(c._lineas(c.width()))} líneas ({filas} filas de píxeles con letra; antes {linea})")
        t = ayuda(app, d)
        assert largo_d in t, f"desplegable acortado sin el texto entero en la ayuda: {t!r}"
        assert b_fijo.acortado()
        t = ayuda(app, b_fijo)
        assert "Otro botón con texto largo y alto fijo" in t, f"botón de alto fijo: {t!r}"
        print("✓ ayuda emergente con el texto entero: desplegable acortado y botón de alto fijo («…»)")

        # lo que se añade después (vigía, 60 ms): también se adapta, se mide y se pinta partido
        tarde = QCheckBox("Casilla añadida más tarde con un texto bastante largo")
        v.insertWidget(2, tarde)
        tarde.show()
        pump(app, 0.4)
        assert R.es_multilinea(tarde), type(tarde)
        # (una ventana suelta se ensancha sola al recibir algo más ancho; un panel no, su zona la ajusta a su ancho)
        caja.setMinimumSize(0, 0)
        caja.resize(150, 480)
        pump(app, 0.2)
        tarde.grab()
        assert pintados.get(id(tarde)), "la casilla añadida después no usa el dibujo nuevo"
        assert tarde.width() <= 150 and len(tarde._lineas(tarde.width())) >= 3
        assert filas_con_letra(tarde) >= 2.5 * linea
        print("✓ lo añadido después (vigía) también se adapta y se pinta en varias líneas")
    finally:
        for mezcla, o in originales.items():
            mezcla.paintEvent = o
    caja.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
