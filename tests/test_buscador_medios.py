"""
🔎 PRUEBA corta (23/11, sin la pestaña «IA»): un solo buscador en Medios y las dudas «¿Zoom aquí?» / «¿Comparación
aquí?» del paso 2.
  · Medios: modos Nombre / Lo que se ve / Lo que se dice junto a la caja; open_moments y open_keywords ponen su modo
    con el foco en la caja; «Lo que se ve» enseña los momentos (el panel de Buscar momentos, dentro de Medios);
    «Lo que se dice» encuentra frases de las transcripciones; sin resultados, «Buscar en internet» abre Descargas con
    el texto.
  · Paso 2: «fíjense» y «comparado con» dan «¿Zoom aquí?» y «¿Comparación aquí?» (con tope); ✓ en Zoom pone el zoom
    del momento y ✓ en Comparación lo marca y abre Comparación; un Ctrl+Z por duda.
Ejecutar:  .venv/Scripts/python.exe tests/test_buscador_medios.py <carpeta_salida>
"""
from __future__ import annotations

import json
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
_CFG = f"_pruebas_tmp/pantalla_buscador_{os.getpid()}.json"
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

from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

QMenu.exec = lambda self, *a: None
QDialog.exec = lambda self, *a: 0
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
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_buscador_medios")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import moments as MO
    from editoria.core import edita_voz as EV
    from editoria.core import media as M
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    clip = os.path.join(out, "clip_explosion.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=12", "-c:v", "libx264", "-preset", "ultrafast", clip], check=True)
    win = MainWindow()
    win.resize(1800, 1000)
    win.show()
    pump(app, 1.0)
    ctrl, lib, bm = win.ctrl, win.library, win.buscador_medios
    assert bm is not None, "no se instaló el buscador de Medios"
    voz = os.path.join("tests", "assets", "narracion_prueba.wav")
    ids = ctrl.import_now([clip, voz])
    while ctrl.analyzing:
        pump(app, 0.1)
    vid, mvoz = ids
    with open(os.path.join("tests", "assets", "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
        ctrl.set_transcript(mvoz, json.load(f))

    # 1) modos junto a la caja; Nombre de entrada
    bm.poner_modo("nombre")
    pump(app, 1.6)                                         # (la lista de Medios se rehace sola: 1,2 s tras el texto)
    assert set(bm.botones) == {"nombre", "ve", "dice"} and bm.caja_modos.isVisible()
    assert lib.tree.isVisible() and not lib.zona_resultados.isVisible()
    # 2) open_moments → «Lo que se ve» con el foco en la caja; el panel de momentos, dentro de Medios
    win.open_moments("")
    pump(app, 0.3)
    assert bm.modo == "ve" and app.focusWidget() is lib.search, app.focusWidget()
    assert not lib.tree.isVisible() and win.moments.isVisible() and not win.moments.query.isVisible()
    assert lib.isAncestorOf(win.moments), "Buscar momentos vive en Medios"
    # (los momentos, sin modelo: lo que encuentra la IA, fijo)
    mp = win.moments
    import numpy as np
    vecs = np.eye(3, 8, dtype=np.float32)
    mp._data = lambda: ({vid: {"times": np.array([0.0, 4.0, 8.0]), "vecs": vecs, "kind": "video",
                               "duration": 12.0}}, {})
    encontrar = {"explosión": [MO.Moment(vid, 2.0, 5.0, 3.0, 6.0), MO.Moment(vid, 7.0, 10.0, 8.0, 4.0)]}
    MO.search_text = lambda q, data, meta=None, paths=None, **k: encontrar.get(q, [])
    lib.search.setText("explosión")
    bm._enter()
    esperar(app, lambda: mp.job is None and mp.grid.count() > 0, 30, "momentos")
    pump(app, 0.6)
    assert mp.grid.count() == 2 and not bm.btn_internet.isVisible()
    win.grab().save(os.path.join(out, "medios_lo_que_se_ve_v2.png"))
    print("✓ «Lo que se ve»: open_moments pone el modo con el foco en la caja y los momentos salen en Medios")
    # sin resultados → «Buscar en internet» abre Descargas con el texto
    lib.search.setText("dragón dorado")
    bm._enter()
    esperar(app, lambda: bm.btn_internet.isVisible(), 20, "botón de internet")
    pedido = []
    win.descargas_web.buscar_imagenes = lambda texto=None: pedido.append(texto)
    bm.btn_internet.click()
    pump(app, 0.2)
    assert pedido == ["dragón dorado"], pedido
    print("✓ sin resultados: «Buscar en internet» abre Descargas con el texto ya escrito")

    # 3) open_keywords → «Lo que se dice»: frases de las transcripciones
    win.open_keywords(scope="all")
    pump(app, 0.3)
    assert bm.modo == "dice" and app.focusWidget() is lib.search and bm.kw is not None and bm.kw.isVisible()
    assert not bm.kw.query.isVisible()
    lib.search.setText("combate")
    bm._enter()
    esperar(app, lambda: bm.kw.b_go.isEnabled() and bm._esperando is None, 60, "lo que se dice")
    assert bm.kw.hits and not bm.btn_internet.isVisible(), bm.kw.status.text()
    win.grab().save(os.path.join(out, "medios_lo_que_se_dice.png"))
    print(f"✓ «Lo que se dice»: open_keywords pone el modo; «combate» → {len(bm.kw.hits)} momentos")
    # 4) Nombre sin nada así → «Buscar en internet»
    bm.poner_modo("nombre")
    lib.search.setText("zzzz nada así")
    pump(app, 0.3)
    assert bm.btn_internet.isVisible() and lib.zona_resultados.isVisible()
    lib.search.clear()
    pump(app, 0.2)
    assert not bm.btn_internet.isVisible()
    print("✓ «Nombre»: lo de siempre y, sin resultados, «Buscar en internet»")

    # 5) paso 2: «fíjense» → «¿Zoom aquí?»; «comparado con» → «¿Comparación aquí?»
    ws, t = [], 0.5
    for frase in ("Hoy hablamos del juego nuevo.", "Fíjense en este detalle del mapa.",
                  "Comparado con el original el remake se ve mucho mejor."):
        for p_ in frase.split():
            ws.append([round(t, 3), round(t + 0.3, 3), p_, 0.95])
            t += 0.35
        t += 1.2
    ctrl.set_project_format("short")
    vc = next(i for i in ctrl.add_media([vid], None, 0.0)
              if ctrl.project.track(ctrl.project.clips[i].track_id).kind == "video")
    ctrl.poner_voz([{"media_id": mvoz}], 0.0)
    ctrl.set_transcript(mvoz, {"language": "es", "words": ws, "segments": []})
    EV.estado(ctrl.project).update({"paso": 2, "voz": [voz], "voz_media": [mvoz], "trans": {voz: 1.0}, "dudas": []})
    ev, pg = win.edita_voz, win.edita_voz.pule
    ev.abrir(2)
    pg.analizar()
    esperar(app, lambda: pg.job is None and pg.dudas(), 60, "dudas")
    pump(app, 0.3)
    vis = {d["tipo"]: d for d in pg.dudas() if d["tipo"] in ("zoom", "comparacion")}
    assert set(vis) == {"zoom", "comparacion"}, [d["titulo"] for d in pg.dudas()]
    assert vis["comparacion"]["titulo"] == "¿Comparación aquí?" and vis["zoom"]["titulo"] == "¿Zoom aquí?"
    assert sum(1 for d in pg.dudas() if d["tipo"] in ("zoom", "comparacion")) <= 4
    pg.poner_actual(vis["comparacion"]["clave"])
    win.grab().save(os.path.join(out, "paso2_comparacion_v2.png"))
    # ✓ Comparación: marcador en ese momento + abre Comparación; un Ctrl+Z
    abiertas = []
    win.open_compare = lambda: abiertas.append(win.engine.time)
    n0, m0 = ctrl.undo_stack.index(), len(ctrl.project.markers)
    pg.aceptar(vis["comparacion"]["clave"])
    pump(app, 0.3)
    assert len(ctrl.project.markers) == m0 + 1 and abiertas and ctrl.undo_stack.index() == n0 + 1
    assert pg._duda(vis["comparacion"]["clave"])["estado"] == "hecha"
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    assert len(ctrl.project.markers) == m0 and pg._duda(vis["comparacion"]["clave"])["estado"] == "pendiente"
    # ✓ Zoom: el zoom del momento en el clip que se ve; un Ctrl+Z
    z0 = ctrl.project.clips[vc].zoom_kf
    pg.aceptar(vis["zoom"]["clave"])
    pump(app, 0.3)
    assert ctrl.project.clips[vc].zoom_kf and ctrl.project.clips[vc].zoom_kf != z0
    ctrl.undo_stack.undo()
    pump(app, 0.3)
    assert ctrl.project.clips[vc].zoom_kf == z0 and pg._duda(vis["zoom"]["clave"])["estado"] == "pendiente"
    print("✓ paso 2: «¿Zoom aquí?» y «¿Comparación aquí?» (con tope); ✓ pone el zoom / marca y abre Comparación; "
          "un Ctrl+Z por duda")
    ctrl.project.modified = False
    ctrl.undo_stack.setClean()
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
