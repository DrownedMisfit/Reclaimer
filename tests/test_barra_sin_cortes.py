"""
✂ PRUEBA (auditoría visual, 20/11): la barra de la línea de tiempo nunca corta el texto de sus botones («⋯ Más»,
Dividir, Eliminar…) en los espacios Video horizontal, Edits y Vertical, a 1920 y a 1366 de ancho: si no cabe con el
nombre, el botón se queda solo con su icono (y el nombre en el tooltip).
Ejecutar:  .venv/Scripts/python.exe tests/test_barra_sin_cortes.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time


# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar).
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

# (22/11) una pantalla de prueba de 1920×1080: sin ella, la pantalla «offscreen» mide ~1000 px y los anchos de 1920 y
# 1366 se quedaban en ~1003 (nunca se probaban)
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_barra_{os.getpid()}.json"
with open(os.path.join(_RAIZ, _CFG), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"dpr": 1}]}')
__import__("atexit").register(lambda: os.path.exists(os.path.join(_RAIZ, _CFG)) and os.remove(os.path.join(_RAIZ, _CFG)))
os.chdir(_RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402


def _vigilante(segundos: float = 420.0):
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


def main():
    _vigilante()
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    vistos = []
    for ancho in (1920, 1366, 1100):
        win.resize(ancho, 1000)
        win.show()
        pump(app, 0.5)
        for k, nombre in ((1, "Video horizontal"), (2, "Edits"), (3, "Vertical")):
            act = next(a for key, (a, _d) in win.shortcut_actions.items() if a.shortcut().toString() == f"Ctrl+{k}")
            act.trigger()
            pump(app, 0.6)
            bar = win._tl_bar
            cortados = []
            for w in bar.findChildren(QToolButton) + bar.findChildren(QPushButton):
                if not w.isVisible():
                    continue
                if w.text() and w.width() < w.sizeHint().width() - 1:
                    cortados.append((w.text(), w.width(), w.sizeHint().width()))
                if not w.text():                  # (solo icono: lleva icono y su nombre en el tooltip)
                    assert not w.icon().isNull() and w.toolTip(), (nombre, w.toolTip())
            assert not cortados, (ancho, nombre, cortados)
            b = win.btn_more
            assert b.isVisible() and b.width() >= b.sizeHint().width() - 1, (ancho, nombre, b.text(), b.width())
            assert b.toolTip()
            vistos.append(f"{win.width()} {nombre}: «{b.text()}»")
    print("  " + " · ".join(vistos))
    # ✂ y NADA SE MONTA (solapes) bajando hasta el ancho mínimo real de la ventana, con la letra al 100 % y al 140 %
    from PySide6.QtCore import QSettings
    from editoria.ui.responsive import widgets_en
    act1 = next(a for key, (a, _d) in win.shortcut_actions.items() if a.shortcut().toString() == "Ctrl+1")
    act1.trigger()
    pump(app, 0.4)
    st = QSettings("EditorIA", "EditorIA")
    letra_antes = st.value("letra/global")
    for letra in (100, 140):
        st.setValue("letra/global", letra)
        win.apply_font_scale()
        pump(app, 0.4)
        minimo = max(win.minimumSizeHint().width(), win.minimumWidth())
        for ancho in sorted({1366, 1100, 1000, 960, minimo + 1}, reverse=True):
            if ancho < minimo:
                continue
            win.resize(ancho, 900)
            pump(app, 0.5)
            bar = win._tl_bar
            vis = [x for x in widgets_en(bar.layout()) if x.isVisible()]
            sol = [((getattr(a_, "text", lambda: "")() or a_.toolTip()[:14]), (getattr(b_, "text", lambda: "")() or
                    b_.toolTip()[:14])) for a_, b_ in zip(vis, vis[1:])
                   if a_.geometry().intersects(b_.geometry()) or a_.geometry().right() >= b_.geometry().left() + 1]
            fuera = [x.toolTip()[:14] or x.objectName() for x in vis if x.geometry().right() > bar.width() + 1]
            if sol or fuera:
                for x in vis:
                    print('   ', (getattr(x, 'text', lambda: '')() or x.toolTip()[:14]), x.geometry().getRect(),
                          x.sizeHint().width(), x.minimumWidth(), x.font().pointSizeF(), x.isHidden(), x.parent() is bar,
                          bar.layout().indexOf(x), x in getattr(win, '_tl_a_mas', []))
                print('    layout', bar.layout().sizeHint().width(), bar.layout().minimumSize().width())
            assert not sol and not fuera, (letra, win.width(), bar.width(), sol, fuera)
            tc = win.tl_timecode
            assert tc.width() + 1 >= tc.fontMetrics().horizontalAdvance(tc.text()), (letra, ancho, "reloj cortado")
            for w in bar.findChildren(QPushButton) + bar.findChildren(QToolButton):
                if w.isVisible() and w.text():
                    assert w.width() >= w.sizeHint().width() - 1, (letra, ancho, w.text(), w.width())
        print(f"  letra {letra} %: sin solapes ni cortes hasta {minimo + 1} px de ventana "
              f"(lo que no cabe, en «⋯ Más»: {len(getattr(win, '_tl_a_mas', []))} botones)")
    if letra_antes is None:
        st.remove("letra/global")
    else:
        st.setValue("letra/global", letra_antes)
    win.apply_font_scale()
    print("✓ la barra de la línea de tiempo no corta ningún botón («⋯ Más», Dividir, Eliminar…) en los 3 espacios y "
          "a 3 anchos; sin sitio, solo el icono con su nombre en el tooltip")
    win.ctrl.project.modified = False
    print("TODO OK")
    try:
        os.remove(os.path.join(_RAIZ, _CFG))         # (os._exit no pasa por atexit)
    except OSError:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
