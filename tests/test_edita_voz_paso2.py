"""
🎙 PRUEBA corta de «Edita desde tu voz», fase 3 (23/11): el paso 2 «Pule tu voz».
Una narración fabricada con: tomas seguidas y una lejana (más de 1 min después), retomar a mitad de frase, una orden
hablada «quita esto» (vuelve a empezar la frase), una traba («el el») y una repetición a propósito («y otra vez, y otra
vez»). Comprueba:
  · la lista: orden ya marcada y que quita desde donde empezó la vez anterior; tarjeta de tomas con mapa de minutos y
    una franja por versión (la elegida = la última completa); la traba; «¿repetición a propósito?» sin marcar;
  · teclado: ↓ mueve, Enter = ✓ (un Ctrl+Z por duda, y al deshacer vuelve a pendiente), Supr = ✗;
  · clic en una versión = elegirla y saltar a ella en la línea de tiempo;
  · cortes que no se comen palabras (ajustar_corte); comprobación final (Whisper falso) con su minuto;
  · el paso 3 está enchufado (Armar mi video + carpeta de relleno a la vista).
Ejecutar:  .venv/Scripts/python.exe tests/test_edita_voz_paso2.py <carpeta_salida>
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
    os.environ["APPDATA"] = os.path.join(tmp, "Roaming")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_pule_{os.getpid()}.json"
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox  # noqa: E402

QMenu.exec = lambda self, *a: None
for _n in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
    setattr(QFileDialog, _n, staticmethod(lambda *a, **k: ""))
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.No))


def _vigilante(segundos: float = 300.0):
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


def narracion():
    """Palabras [inicio, fin, texto, confianza] de una narración fabricada (≈ 100 s)."""
    ws, t = [], 0.5
    for item in ["Hoy vamos a hablar del juego nuevo.", 1.0,
                 "El combate se siente bastante lento.", 1.0,
                 "El combate se siente demasiado lento, sobre todo al principio.", 1.0,
                 "La historia empieza en un pueblo pequeño.", 1.0, "quita esto", 1.0,
                 "La historia empieza en una ciudad enorme.", 1.0,
                 "Y por eso,", "y por eso la consola vende tanto.", 1.0,
                 "Y otra vez,", "y otra vez salta el personaje.", 1.0,
                 "El el problema es la música.", 60.0,
                 "El combate se siente demasiado lento, sobre todo al final del juego.", 1.0, "Nada más.", 1.0,
                 "Fíjense en este detalle del mapa.", 1.0,
                 "Comparado con el original el remake se ve mucho mejor."]:
        if isinstance(item, float):
            t += item
            continue
        for p in item.split():
            ws.append([round(t, 3), round(t + 0.3, 3), p, 0.95])
            t += 0.35
        t += 0.25
    return ws


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_edita_voz_paso2")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import pule_voz as PV
    from editoria.core import edita_voz as EV
    from editoria.core import mapping
    from editoria.core import media as M
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    W = narracion()
    # cortes que no se comen palabras: un corte que cae dentro de «combate» (que se queda) se aparta de ella
    w = W[8]                                                  # «combate» de la 2.ª toma
    a, b = PV.ajustar_corte(w[1] - 0.05, W[10][1] + 0.02, W)
    assert a >= w[1] and b > W[10][1], (a, b, w)
    assert PV.ajustar_corte(w[1] - 0.05, W[9][0] + 0.1, W) is None, "dentro de palabras que se quedan: nada"
    s_ = next(x for x in W if x[2] == "tanto.")               # (final suave en «s»… «tanto.» no; «demasiado» no)
    assert PV.ajustar_corte(s_[1] + 0.01, s_[1] + 0.3, W) is not None
    print("✓ ajustar_corte: un corte nunca se queda dentro de una palabra que se queda")

    voz = os.path.join(out, "voz_fabricada.wav")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=16000:cl=mono", "-t", f"{W[-1][1] + 2:.1f}", voz], check=True)

    from editoria.ai import transcription
    transcription.transcribe = lambda samples, *a, **k: {
        "language": "es", "model": "falso", "segments": [],
        "words": [[1.0, 1.3, "Esto", 0.9], [1.35, 1.6, "es", 0.9], [1.65, 1.9, "una", 0.9], [1.95, 2.3, "frase.", 0.9],
                  [3.0, 3.3, "Esto", 0.9], [3.35, 3.6, "es", 0.9], [3.65, 3.9, "una", 0.9], [3.95, 4.3, "frase", 0.9],
                  [4.35, 4.7, "repetida.", 0.9]]}

    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1800, 1000)
    win.show()
    pump(app, 1.0)
    ctrl, ev = win.ctrl, win.edita_voz
    ctrl.set_project_format("short")                          # (en vertical, el panel va en el hueco del visor)
    pump(app, 0.3)
    (mid,) = ctrl.import_now([voz])
    ctrl.poner_voz([{"media_id": mid}], 0.0)
    ctrl.set_transcript(mid, {"language": "es", "words": W, "segments": []})
    EV.estado(ctrl.project).update({"paso": 2, "voz": [voz], "voz_media": [mid], "trans": {voz: 1.0}})
    pg = ev.pule
    assert pg is not None and ev.panel.paginas[2] is pg
    ev.abrir(2)
    pg.analizar(final=True)
    esperar(app, lambda: pg.job is None and pg.dudas(), 60, "el análisis")
    pump(app, 0.3)
    ds = pg.dudas()
    tipos = [(d["tipo"], d["titulo"]) for d in ds]
    print("  dudas:", [f"{PV.minuto(d['t'])} {d['titulo']}" for d in ds])
    orden = next(d for d in ds if d["tipo"] == "orden")
    assert orden["marcada"] and "quita esto" in orden["titulo"], orden
    ini_pueblo = next(x for x in W if x[2] == "pueblo")
    assert orden["quitar"][0][0] < ini_pueblo[0] - 1.0, orden["quitar"]      # desde «La historia…» de la vez anterior
    tomas = next(d for d in ds if d["tipo"] == "tomas" and len(d["versiones"]) == 3)
    assert tomas["versiones"][-1]["a"] - tomas["versiones"][0]["a"] > 60, "una versión lejana (más de 1 min)"
    assert tomas["elegida"] == 2 and tomas["versiones"][2]["estado"] == "completa", tomas
    assert any(d["titulo"] == "Retomaste a mitad de frase" for d in ds), tipos
    assert any(d["tipo"] == "traba" for d in ds), tipos
    inten = next(d for d in ds if d["tipo"] == "intencion")
    assert not inten["marcada"], inten
    t_tomas = pg.tarjetas[tomas["clave"]]
    assert len(t_tomas.franjas) == 3
    from editoria.ui.pule_voz import MapaMinutos
    assert t_tomas.findChild(MapaMinutos) is not None
    win.grab().save(os.path.join(out, "paso2_lista.png"))
    # «Seguir: arma tu video» entero en lo que DE VERDAD se ve (la zona con desplazamiento del panel de
    # herramientas), también con las dudas de zoom y comparación en la lista (23/11: se cortaba)
    assert {"zoom", "comparacion"} <= {d["tipo"] for d in ds}, [d["titulo"] for d in ds]
    from PySide6.QtWidgets import QScrollArea
    pb, vp = pg.b_seguir, ev.panel.parentWidget()
    w_ = ev.panel
    while w_ is not None:
        if isinstance(w_.parentWidget(), QScrollArea) and w_ is w_.parentWidget().viewport():
            vp = w_
            break
        w_ = w_.parentWidget()
    abajo = vp.mapFromGlobal(pb.mapToGlobal(pb.rect().bottomLeft())).y()
    assert pb.isVisible() and abajo <= vp.height(), ("«Seguir: arma tu video» se ve entero", abajo, vp.height())
    print("✓ la lista: orden «quita esto» ya marcada (desde la vez anterior), tomas con una lejana y la última completa "
          "elegida, retomar a mitad de frase, traba y «¿repetición a propósito?» sin marcar")

    # teclado: la primera duda es la orden; Enter = ✓ (un Ctrl+Z), y al deshacer vuelve a pendiente
    pg.poner_actual(pg.orden_claves[0])
    pg.lista.setFocus()
    dur0 = ctrl.project.duration()
    n0 = ctrl.undo_stack.index()
    primera = pg._duda(pg.orden_claves[0])
    QTest.keyClick(pg.lista, Qt.Key_Return)
    pump(app, 0.2)
    assert primera["estado"] == "hecha" and ctrl.undo_stack.index() == n0 + 1, (primera["estado"],)
    assert ctrl.project.duration() < dur0 - 1.0, (dur0, ctrl.project.duration())
    assert pg.actual != primera["clave"], "pasa a la siguiente"
    ctrl.undo_stack.undo()
    pump(app, 0.2)
    assert primera["estado"] == "pendiente" and abs(ctrl.project.duration() - dur0) < 1e-6
    ctrl.undo_stack.redo()
    pump(app, 0.2)
    assert primera["estado"] == "hecha"
    pg.lista.setFocus()
    actual = pg.actual
    QTest.keyClick(pg.lista, Qt.Key_Delete)
    pump(app, 0.1)
    assert pg._duda(actual)["estado"] == "descartada"
    k0 = pg.actual
    QTest.keyClick(pg.lista, Qt.Key_Up)
    assert pg.actual != k0
    print("✓ teclado: Enter quita (un Ctrl+Z, y al deshacer la duda vuelve a pendiente), Supr la deja, ↑/↓ se mueve")

    # clic en una versión = elegirla y saltar a ella
    t_tomas = pg.tarjetas[tomas["clave"]]
    t_tomas.franjas[1].pulsada.emit(1)
    pump(app, 0.2)
    tomas = pg._duda(tomas["clave"])
    assert tomas["elegida"] == 1 and tomas["elegida_tuya"]
    esperado = mapping.map_time(ctrl.project, mid, tomas["versiones"][1]["a"])
    assert abs(pg._ultimo_salto - esperado) < 1e-6, (pg._ultimo_salto, esperado)
    assert [round(x[0], 1) for x in PV.quitar_de(tomas)] == [round(tomas["versiones"][0]["a"], 1),
                                                              round(tomas["versiones"][2]["a"], 1)]
    print("✓ clic en una versión: se queda esa (las otras se quitarán) y la línea de tiempo salta allí")

    # comprobación final (Whisper falso con una frase repetida)
    pg.comprobar()
    esperar(app, lambda: pg.job_cmp is None, 30, "la comprobación")
    pump(app, 0.2)
    assert pg.quedan and "0:00 · tomas" in pg.queda.text(), pg.queda.text()
    print(f"✓ comprobación final: «{pg.queda.text().splitlines()[1]}»")

    # paso 3 enchufado
    ev.ir_a_paso(3)
    pump(app, 0.2)
    from editoria.ui.paso_arma import PaginaArma
    p3 = ev.panel.paginas[3]
    assert isinstance(p3, PaginaArma) and p3.b_armar.isVisible() and p3.b_carpeta.isVisible()
    ev.panel.grab().save(os.path.join(out, "paso3_panel.png"))
    print("✓ paso 3: «Armar mi video» y la carpeta de relleno a la vista")
    ctrl.project.modified = False
    ctrl.undo_stack.setClean()
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
