"""
↔ YouTube, Vertical y Edits caben en la pantalla con sus paneles de entrada (17/11: «lo de Video horizontal, que se
comía las palabras / la pantalla, arréglamelo también en Shorts y en Edits»). Antes, con la barra de Vertical / Edits
en la cabecera del visor, la ventana pedía 1322 px (Vertical) y 1257 px (Edits) y se cortaba la derecha (Inspector y
la línea de tiempo). Ahora la cabecera deja los botones solo con su icono y, si ni así cabe, la barra pasa a una segunda
fila. Comprueba en las tres pestañas:
  · la ventana pide ≤ 1280 px y cabe en pantallas de 1366 y 1920 px (win._que_quepa_en_pantalla);
  · en la ventana más estrecha posible, ningún botón ni texto de la cabecera del visor se corta y la barra de
    Vertical / Edits se ve entera.
Ejecutar:  .venv/Scripts/python.exe tests/test_ancho_pestanas.py <carpeta_salida>
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
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402


class _Pantalla:
    def __init__(self, ancho):
        self.ancho = ancho

    def availableGeometry(self):
        return QRect(0, 0, self.ancho, 728 if self.ancho < 1500 else 1040)


def pump(app, n=20):
    for _ in range(n):
        app.processEvents()


def nada_cortado_en_cabecera(win, app, nombre):
    pv = win.preview
    win.resize(win.minimumSizeHint().width(), 820)
    pump(app, 30)
    pv._ajustar_cabecera()
    pump(app, 10)
    h = pv.header
    for w in h.findChildren(QAbstractButton) + h.findChildren(QLabel):
        if not w.isVisibleTo(h) or w is pv.title_label or not w.text():
            continue
        necesita = w.fontMetrics().horizontalAdvance(w.text().replace("&&", "&"))
        assert w.width() >= necesita, f"{nombre}: «{w.text()}» se corta ({w.width()} < {necesita} px)"
        r = QRect(w.mapTo(h, QPoint(0, 0)), w.size())
        assert h.rect().contains(r), f"{nombre}: «{w.text()}» se sale de la cabecera ({r} fuera de {h.rect()})"
    if pv.shorts_bar.isVisibleTo(h):
        hijos = [b for b in pv.shorts_bar.findChildren(QAbstractButton) if b.isVisibleTo(pv.shorts_bar)]
        assert hijos, f"{nombre}: la barra de Vertical / Edits está vacía"
        assert pv.shorts_bar.width() >= pv.shorts_bar.sizeHint().width(), \
            f"{nombre}: la barra de Vertical / Edits está aplastada ({pv.shorts_bar.width()} px)"
    fila = "dos filas" if pv._segunda_fila else "una fila"
    print(f"   ✓ con la ventana a {win.width()} px: cabecera en {fila}, nada cortado "
          f"({'solo iconos' if pv._compacta else 'con nombres'})")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app)
    for fmt in ("youtube", "short", "edit"):
        win.workspaces.switch(fmt)
        pump(app, 40)
        win.preview._ajustar_cabecera()
        pump(app, 10)
        pide = win.minimumSizeHint().width()
        assert pide <= 1280, f"{fmt}: la ventana pide {pide} px (> 1280)"
        print(f"✓ {fmt}: la ventana pide {pide} px (cabecera del visor {win.preview.header.minimumSizeHint().width()})")
        for ancho in (1366, 1920):
            win.screen = (lambda a=ancho: _Pantalla(a))       # (pantalla de mentira: sin tocar la de verdad)
            win._que_quepa_en_pantalla()
            pump(app, 10)
            pide = win.minimumSizeHint().width()
            assert pide <= ancho - 16, f"{fmt}: en {ancho} px la ventana pide {pide} px"
            print(f"   ✓ pantalla de {ancho} px: pide {pide} px, cabe")
        del win.screen
        nada_cortado_en_cabecera(win, app, fmt)
        win.resize(1500, 900)
        pump(app, 20)
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
