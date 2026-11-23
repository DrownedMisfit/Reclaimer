"""
⚡ Arranque rápido (23/11): abre Reclaimer como el acceso directo (main.py → editoria.app.run), SIN ventana visible y con
datos temporales, y mide:
  · la ventana de arranque oscura sale enseguida (antes de cargar la ventana principal) y se cierra al verse esta;
  · la imagen del logo en relieve queda en la caché (datos\\cache\\arranque) y la segunda vez se lee de ahí;
  · tiempo hasta el primer pintado de la ventana principal ≤ LIMITE_S (offscreen; en el PC del usuario, con caché);
  · el proyecto se abre DESPUÉS del primer pintado (try_recover tras pintar: nada en blanco mientras carga).
Ejecutar (con el turno):  turno.py tests/test_arranque_rapido.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

T0 = time.perf_counter()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(ROOT, "_pruebas_tmp"), exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_arranque_", dir=os.path.join(ROOT, "_pruebas_tmp"))
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

LIMITE_S = float(os.environ.get("ARRANQUE_LIMITE_S", "7.5"))   # (offscreen medía 6,8 s antes del 23/11 y ~4,8 s después)


def main():
    import runpy

    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication

    import editoria.app as A
    orden: list[tuple[str, float]] = []

    def marca(t):
        orden.append((t, time.perf_counter() - T0))

    v0 = A._ventana_de_arranque

    def ventana(app):
        sp = v0(app)
        marca("arranque visible" if sp is not None and sp.isVisible() else "sin ventana de arranque")
        return sp
    A._ventana_de_arranque = ventana
    t0 = A._tras_verse

    def tras(win, argv):
        marca("abre el proyecto")
        t0(win, argv)
    A._tras_verse = tras
    estado = {}

    class Pintado(QObject):
        def eventFilter(self, o, e):                    # noqa: N802
            if e.type() == QEvent.Paint and o is estado.get("win") and "pintado" not in estado:
                estado["pintado"] = True
                marca("primer pintado")
            return False
    filtro = Pintado()
    mw = None

    f0 = A._filtros_globales

    def filtros(app):
        nonlocal mw
        mw = sys.modules["editoria.ui.main_window"].MainWindow
        orig_show = mw.show

        def show(self):
            estado["win"] = self
            QApplication.instance().installEventFilter(filtro)
            orig_show(self)

            def fin():
                estado["arranque_abierta"] = any(w.objectName() == "ventana_de_arranque" and w.isVisible()
                                                 for w in QApplication.topLevelWidgets())
                self.ctrl.undo_stack.setClean()
                self.ctrl._media_dirty = False
                self.close()
            QTimer.singleShot(1500, fin)
        mw.show = show
        return f0(app)
    A._filtros_globales = filtros
    sys.argv = [os.path.join(ROOT, "main.py")]
    try:
        runpy.run_path(os.path.join(ROOT, "main.py"), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"salió con código {e.code}"
    nombres = [n for n, _ in orden]
    print("  " + " · ".join(f"{n} {t:.2f} s" for n, t in orden))
    assert nombres[:3] == ["arranque visible", "primer pintado", "abre el proyecto"], nombres
    print("✓ ventana de arranque → primer pintado → proyecto (en ese orden: nada en blanco mientras carga)")
    assert not estado.get("arranque_abierta"), "la ventana de arranque sigue abierta"
    t_pintado = dict(orden)["primer pintado"]
    assert dict(orden)["arranque visible"] < 1.5, orden
    assert t_pintado <= LIMITE_S, f"la ventana tardó {t_pintado:.2f} s en verse (límite {LIMITE_S} s)"
    print(f"✓ ventana de arranque en {dict(orden)['arranque visible']:.2f} s; ventana principal pintada en "
          f"{t_pintado:.2f} s (límite {LIMITE_S} s)")
    cache = os.path.join(_TMP, "EditorIA", "cache", "arranque")
    pngs = [f for f in os.listdir(cache) if f.startswith(f"arranque_v{A.ARRANQUE_VERSION}_")] if os.path.isdir(cache) \
        else []
    assert len(pngs) == 1, pngs
    app = QApplication.instance() or QApplication([])
    pintar0 = A._pintar_arranque

    def no_pintar(*_a):                                  # (con la caché, la imagen NO se vuelve a pintar)
        raise AssertionError("la imagen no salió de la caché")
    A._pintar_arranque = no_pintar
    t = time.perf_counter()
    try:
        pm = A._imagen_de_arranque(*(lambda p: (p.color(p.ColorRole.Window), p.color(p.ColorRole.WindowText)))(
            app.palette()), app.primaryScreen().devicePixelRatio())
    finally:
        A._pintar_arranque = pintar0
    ms = (time.perf_counter() - t) * 1000
    assert not pm.isNull() and round(pm.width() / pm.devicePixelRatio()) == A.ARRANQUE_TAM[0], pm.size()
    print(f"✓ logo en relieve en la caché ({pngs[0]}); leerla: {ms:.0f} ms")
    print("TODO OK")


if __name__ == "__main__":
    main()
