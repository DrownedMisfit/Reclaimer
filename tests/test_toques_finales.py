"""
✨ PRUEBA corta de los «Toques finales» del paso 3 de «Edita desde tu voz» (23/11; ai/toques_finales.py +
ui/toques_ui.py):
  · Natural y todo apagado no cambia nada;
  · Temas pone los marcadores de tema; −14 LUFS enciende loudnorm; cada toque es un Ctrl+Z (y se deshacen);
  · la sección es plegable y recuerda si estaba abierta; «Mirar mis clips a fondo» está junto a la carpeta de relleno
    y apagada de entrada; Ctrl+Mayús+A (open_auto) y open_understand abren «Edita desde tu voz».
Ejecutar:  .venv/Scripts/python.exe tests/test_toques_finales.py <carpeta_salida>
"""
from __future__ import annotations

import os
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
_CFG = f"_pruebas_tmp/pantalla_toques_{os.getpid()}.json"
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

from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

QMenu.exec = lambda self, *a: None
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.No))


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


def esperar(app, cond, s=60.0, que=""):
    t0 = time.time()
    while not cond():
        if time.time() - t0 > s:
            raise AssertionError(f"no llegó a tiempo: {que}")
        app.processEvents()
        time.sleep(0.02)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_toques_finales")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import topic_detection
    from editoria.core import edita_voz as EV
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    # temas sin modelo de frases: dos temas fijos
    topic_detection.detect_topics = lambda words, progress=None, cancelled=None, **k: [
        {"start": 0.2, "end": 14.0, "topic": "Combate"}, {"start": 14.0, "end": 30.0, "topic": "Historia"}]

    win = MainWindow()
    win.resize(1800, 1000)
    win.show()
    pump(app, 1.0)
    ctrl, ev = win.ctrl, win.edita_voz
    ctrl.set_project_format("short")                       # (vertical: el panel, en el hueco del visor)
    voz = os.path.join("tests", "assets", "narracion_prueba.wav")
    (mid,) = ctrl.import_now([voz])
    ctrl.poner_voz([{"media_id": mid}], 0.0)
    palabras = [[0.3 + 0.7 * i, 0.3 + 0.7 * i + 0.5, f"palabra{i}", 0.9] for i in range(40)]
    ctrl.set_transcript(mid, {"language": "es", "words": palabras, "segments": []})
    EV.estado(ctrl.project).update({"paso": 3, "voz": [voz], "voz_media": [mid], "trans": {voz: 1.0}})
    ctrl.set_settings(loudnorm=False)
    pump(app, 0.2)

    # Ctrl+Mayús+A y «Entender a fondo» abren «Edita desde tu voz»
    win.open_auto()
    pump(app, 0.3)
    assert ev.abierto, "open_auto abre «Edita desde tu voz»"
    win.open_understand()
    pump(app, 0.3)
    p3 = ev.arma
    assert ev.panel.pila.currentWidget() is p3 and p3.chk_fondo.isVisible() and not p3.chk_fondo.isChecked()
    assert not win.ai_panel.btn_understand.isVisible()
    from editoria.ui.ai_panel import AI_CARDS
    assert not {"auto", "understand"} & {k for k, *_ in AI_CARDS}
    print("✓ open_auto / open_understand abren «Edita desde tu voz» (paso 3, «Mirar mis clips a fondo» apagada); "
          "fuera el botón y las tarjetas viejas")

    t = p3.toques
    t.cab.setChecked(False)
    pump(app, 0.1)
    win.grab().save(os.path.join(out, "paso3_toques_plegados.png"))
    t.cab.setChecked(True)
    pump(app, 0.2)
    assert t.cuerpo.isVisible()
    from editoria.ui.toques_ui import SeccionToques
    assert SeccionToques(ev).cab.isChecked(), "se recuerda abierta"
    win.grab().save(os.path.join(out, "paso3_toques_abiertos.png"))

    # 1) Natural y todo apagado: nada cambia
    antes = ctrl.project.timeline_state()
    n0 = ctrl.undo_stack.index()
    nada = {"temas": False, "zooms": False, "lufs": False, "subs": False, "revision": False, "estilo": "natural",
            "musica": None}
    assert t.aplicar(nada) is False
    pump(app, 0.2)
    assert ctrl.project.timeline_state() == antes and ctrl.undo_stack.index() == n0
    print("✓ Natural y todo apagado: no cambia nada")

    # 2) Temas + −14 LUFS: marcadores de tema y loudnorm; un Ctrl+Z cada uno
    assert t.aplicar(dict(nada, temas=True, lufs=True))
    esperar(app, lambda: not t.ocupado, 30, "los toques")
    pump(app, 0.2)
    temas = [m.label for m in ctrl.project.markers if m.kind == "topic"]
    assert temas == ["Combate", "Historia"] and ctrl.project.loudnorm, (temas, ctrl.project.loudnorm)
    assert ctrl.undo_stack.index() == n0 + 2, ctrl.undo_stack.index() - n0
    assert any("Temas" in x for x in p3.avisos.text().split("\n")), p3.avisos.text()
    ctrl.undo_stack.undo()
    pump(app, 0.1)
    assert not ctrl.project.loudnorm and [m for m in ctrl.project.markers if m.kind == "topic"]
    ctrl.undo_stack.undo()
    pump(app, 0.1)
    assert not [m for m in ctrl.project.markers if m.kind == "topic"]
    print("✓ Temas pone los marcadores y −14 LUFS enciende loudnorm; cada toque, un Ctrl+Z")
    ctrl.project.modified = False
    ctrl.undo_stack.setClean()
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
