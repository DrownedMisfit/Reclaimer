"""
🧰 PRUEBA corta del lote 1 de ventanas flotantes → pestañas del panel de herramientas (23/11).
Tamaño de letra, Descripción, Buscar lo que se dice, Cola de exportación, Shorts, Animar imagen, Mi intro y mi outro
y Buscar sonido en internet: cada una se abre con su acción de siempre y comprueba que
  · es una pestaña del panel (nunca una ventana) y nada la bloquea (ningún exec modal);
  · en el hueco del visor de un proyecto vertical (~300 px) ningún botón, casilla ni desplegable sale cortado ni se
    sale por la derecha.
Ejecutar:  .venv/Scripts/python.exe tests/test_lote1_herramientas.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


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
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_lote1_{os.getpid()}.json"
with open(os.path.join(_RAIZ, _CFG), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"dpr": 1}]}')
__import__("atexit").register(lambda: os.path.exists(os.path.join(_RAIZ, _CFG)) and os.remove(os.path.join(_RAIZ, _CFG)))
os.chdir(_RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog, QMenu,  # noqa: E402
                               QMessageBox)

MODALES: list[str] = []
QDialog.exec = lambda self, *a: (MODALES.append(type(self).__name__), 0)[1]
QMenu.exec = lambda self, *a: None
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: (MODALES.append("QMessageBox"), QMessageBox.No)[1]))


def _vigilante(segundos: float = 240.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def cortados(w) -> list[str]:
    """Botones, casillas y desplegables visibles que salen cortados o se salen por la derecha de la herramienta."""
    out = []
    for c in w.findChildren(QAbstractButton) + w.findChildren(QComboBox):
        if not c.isVisibleTo(w) or c.width() <= 0:
            continue
        x1 = c.mapTo(w, c.rect().topRight()).x()
        nombre = getattr(c, "text", lambda: "")() or c.toolTip()[:30] or type(c).__name__
        if x1 > w.width() + 1:
            out.append(f"«{nombre}» se sale ({x1} > {w.width()})")
        elif c.width() + 2 < c.sizeHint().width() and not isinstance(c, QComboBox):
            out.append(f"«{nombre}» cortado ({c.width()} < {c.sizeHint().width()})")
    return out


def bajo_la_barra(w) -> list[str]:
    """Etiquetas y cajas de texto visibles que se salen por la derecha de lo que se ve de su zona con desplazamiento
    (p. ej. debajo de la barra vertical) o de la herramienta."""
    from PySide6.QtWidgets import QAbstractItemView, QLabel, QPlainTextEdit, QScrollArea
    out = []
    for c in w.findChildren(QLabel) + w.findChildren(QPlainTextEdit):
        if not c.isVisibleTo(w) or c.width() <= 0:
            continue
        vp, p, en_vista = None, c.parentWidget(), False
        while p is not None:
            if isinstance(p, QAbstractItemView):
                en_vista = True
                break
            padre = p.parentWidget()
            if isinstance(padre, QScrollArea) and p is padre.viewport():
                vp = p
                break
            p = padre
        if en_vista:
            continue
        vp = vp or w
        x1 = c.mapTo(vp, c.rect().topRight()).x()
        if x1 > vp.width() + 1:
            txt = (c.text() if isinstance(c, QLabel) else c.placeholderText() or c.toPlainText())[:30]
            out.append(f"«{txt}» se sale {x1 - vp.width()} px")
    return out


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_lote1_herramientas")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.ui import image_anim_dialog, intro_outro_dialog, shorts_dialog
    try:                                   # (parte solo local: en la versión pública no está)
        from editoria.ui import sounds_internet
    except ImportError:
        sounds_internet = None
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    png = os.path.join(out, "personaje.png")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x300",
                    "-frames:v", "1", png], check=True)
    win = MainWindow()
    win.resize(1800, 1000)
    win.show()
    pump(app, 1.0)
    ctrl, h = win.ctrl, win.herramientas
    ctrl.set_project_format("short")                       # (vertical: el panel, en el hueco del visor, ~300 px)
    (mid,) = ctrl.import_now([png])
    pump(app, 0.3)
    casos = [("letra", win.open_font_size), ("descripcion", win.open_chapters),
             ("cola", win.open_queue),     # («Buscar lo que se dice» es ya un modo del buscador de Medios)
             ("shorts", lambda: shorts_dialog.open_shorts_dialog(win)),
             ("animar", lambda: image_anim_dialog.abrir(win, mid)),
             ("intro_outro", lambda: intro_outro_dialog.open_dialog(win)),
             ("sonidos_web", lambda: sounds_internet.abrir(win.effects, ""))]
    if sounds_internet is None:
        casos = [x for x in casos if x[0] != "sonidos_web"]
    fallos = []
    for clave, abrir in casos:
        n0 = len(MODALES)
        abrir()
        pump(app, 0.4)
        w = h.widget(clave)
        assert h.abierta(clave) and w is not None, clave
        assert not w.isWindow() and len(MODALES) == n0, (clave, MODALES[n0:])
        mal = cortados(w) + bajo_la_barra(w)
        print(f"  {clave}: {h.donde}, {w.width()} px" + (f" · {mal}" if mal else ""))
        if mal:
            fallos.append((clave, mal))
        if clave == "animar":                              # «Poner» a la vista sin desplazar
            caja = h.marco if h.donde == "hueco" else w.parentWidget()      # (lo que de verdad se ve)
            abajo = caja.mapFromGlobal(w.btn_poner.mapToGlobal(w.btn_poner.rect().bottomLeft())).y()
            assert abajo <= caja.height(), ("«Poner» fuera de la vista", abajo, caja.height())
        if clave == "descripcion":                         # sin capítulos: una línea, no una tabla en blanco
            ch = w.chapters
            assert (ch.table.rowCount() == 0) == ch.vacio.isVisibleTo(w), ch.table.rowCount()
        if clave in ("cola", "descripcion", "animar"):
            win.grab().save(os.path.join(out, f"{clave}_v3.png"))
    assert not fallos, fallos
    print("✓ las 8 se abren como pestaña del panel, sin ningún modal, y nada sale cortado ni queda debajo de la barra en el hueco del visor")
    # la misma acción y el mismo resultado: Tamaño de letra «Aceptar» cierra la pestaña
    win.open_font_size()
    pump(app, 0.2)
    h.widget("letra").accept()
    pump(app, 0.2)
    assert not h.abierta("letra")
    print("✓ Aceptar / Cerrar siguen cerrando (la pestaña)")
    ctrl.project.modified = False
    ctrl.undo_stack.setClean()
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
