"""
🎙 PRUEBA corta de «Edita desde tu voz», fase 2 (23/11): el botón insignia y el paso 1.
  · OBS falso (user.ini + basic.ini): la carpeta de grabaciones sale de su perfil y las grabaciones, la más reciente
    arriba; varias partes en orden natural («parte 2» antes que «parte 10»);
  · el botón está arriba, junto al logo, con el acento, brilla hasta el primer uso y abre su panel en el hueco a la
    derecha del visor (no flotante) con el foco en «Elegir grabación»;
  · una grabación de OBS con imagen + 2 pistas (1 = mezcla, 2 = voz): se queda con la pista 2, pregunta en una barra
    «solo la voz / también su imagen» y, con cosas en la línea de tiempo, «al inicio / en el cabezal»; coloca la voz
    en «🎙 Micrófono» sin borrar nada (un Ctrl+Z) y la transcribe POR TROZOS (Whisper falso) sin bloquear: el botón
    dice «Paso 2 de 3 · N %» y el texto parcial ya está en el proyecto;
  · se guarda con el proyecto y, al abrirlo otra vez, el botón sigue en el paso 2 y la transcripción entra entera.
Ejecutar:  .venv/Scripts/python.exe tests/test_edita_voz_paso1.py <carpeta_salida>
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
    os.environ["APPDATA"] = os.path.join(tmp, "Roaming")          # (OBS falso: nunca el tuyo)
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_edita_voz_{os.getpid()}.json"
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

from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox  # noqa: E402

QMenu.exec = lambda self, *a: None
for _n in ("getOpenFileName", "getOpenFileNames", "getSaveFileName"):
    setattr(QFileDialog, _n, staticmethod(lambda *a, **k: ([], "") if "Names" in _n else ("", "")))
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


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_edita_voz_paso1")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import edita_voz as EV
    from editoria.core import media as M
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # 1) OBS falso: perfil en uso (user.ini de OBS 31) con su carpeta de grabaciones
    rec = os.path.join(TMP, "Grabaciones OBS ñ")
    os.makedirs(rec, exist_ok=True)
    perfil = os.path.join(os.environ["APPDATA"], "obs-studio", "basic", "profiles", "Mi_perfil")
    os.makedirs(perfil, exist_ok=True)
    with open(os.path.join(os.environ["APPDATA"], "obs-studio", "user.ini"), "w", encoding="utf-8") as f:
        f.write("[Basic]\nProfile=Mi perfil\nProfileDir=Mi_perfil\n")
    with open(os.path.join(perfil, "basic.ini"), "w", encoding="utf-8-sig") as f:
        f.write(f"[Output]\nMode=Advanced\n[AdvOut]\nRecFilePath={rec.replace(os.sep, '/')}\n"
                "[SimpleOutput]\nFilePath=C:/no/existe\n")
    assert os.path.normcase(EV.carpeta_obs()) == os.path.normcase(rec), EV.carpeta_obs()
    assert EV.carpeta_inicial("", "")[1] == "obs"

    voz = os.path.join("tests", "assets", "narracion_prueba.wav")
    grab = os.path.join(rec, "2026-11-23 20-00-00.mkv")       # imagen + pista 1 (mezcla) + pista 2 (voz)
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                    "-i", voz, "-f", "lavfi", "-i", "anoisesrc=d=20:c=pink:a=0.05",
                    "-filter_complex", "[1:a]atrim=0:20,aformat=channel_layouts=mono,asplit[v1][v2];"
                    "[2:a]aformat=channel_layouts=stereo[g];[v1]aformat=channel_layouts=stereo[vs];"
                    "[vs][g]amix=inputs=2:normalize=0[mix]",
                    "-map", "0:v", "-map", "[mix]", "-map", "[v2]", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-t", "20", grab], check=True)
    viejo = os.path.join(rec, "antigua.wav")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=1", viejo], check=True)
    os.utime(viejo, (time.time() - 3600, time.time() - 3600))
    assert EV.recientes(rec)[0] == grab, EV.recientes(rec)
    partes = [os.path.join(rec, n) for n in ("voz parte 10.wav", "voz parte 2.wav")]
    for pth in partes:
        open(pth, "wb").close()
    assert [os.path.basename(x) for x in EV.ordenar_partes(partes)] == ["voz parte 2.wav", "voz parte 10.wav"]
    for pth in partes:
        os.remove(pth)
    info = EV.elegir_pista(grab)
    assert info["n"] == 2 and info["k"] == 1, info
    print("✓ OBS: carpeta de su perfil en uso; la más reciente arriba; partes en orden natural; la voz = pista 2")

    # 2) Whisper falso, por trozos (sin modelo ni red)
    from editoria.ai import transcription
    with open(os.path.join("tests", "assets", "narracion_prueba.transcripcion.json"), encoding="utf-8") as f:
        TR = json.load(f)
    llamadas = []

    def falso(samples, model_key="equilibrado", language="es", progress=None, cancelled=None, fillers=True,
              partial=None, block=180.0, start_at=0.0, prev=None):
        dur = len(samples) / transcription.SAMPLE_RATE
        llamadas.append((round(dur, 1), block, start_at))
        for hasta in (8.0, 15.0):
            time.sleep(0.4)
            if cancelled and cancelled():
                from editoria.ai.base import Cancelled
                raise Cancelled()
            if progress:
                progress(hasta / dur, f"Transcribiendo… {hasta:.0f} s")
            ws = [w for w in TR["words"] if w[1] <= hasta]
            if partial:
                partial({"language": "es", "model": "falso", "words": ws, "segments": [], "hasta": hasta})
        time.sleep(0.3)
        return {"language": "es", "model": "falso", "words": [w for w in TR["words"] if w[1] <= dur],
                "segments": []}
    transcription.transcribe = falso

    from PySide6.QtCore import QSettings
    QSettings("EditorIA", "EditorIA").setValue("edita_voz/usado", "false")   # (como recién instalado: aún sin usar)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1800, 1000)
    win.show()
    pump(app, 1.0)
    ctrl, ev = win.ctrl, win.edita_voz
    assert ev is not None, "no se instaló «Edita desde tu voz»"
    b = win.btn_edita_voz
    bar = b.parentWidget()
    assert bar.objectName() == "topbar" and b.isVisible() and b.boton.text() == "Edita desde tu voz"
    assert b.brillando, "brilla hasta el primer uso"
    assert "#" in b.boton.styleSheet() and "background" in b.boton.styleSheet()
    # algo ya puesto en la línea de tiempo (para que pregunte dónde)
    (mid0,) = ctrl.import_now([viejo])
    ctrl.add_media([mid0], None, 0.0)
    antes = {c.id for c in ctrl.project.clips.values()}
    n_undo = ctrl.undo_stack.index()

    b.boton.click()
    pump(app, 0.3)
    assert not b.brillando, "deja de brillar al usarlo"
    vp = win.preview.canvas.viewport()
    print(f"  visor {vp.width()}×{vp.height()} · hueco {ev.anfitrion._hueco()} · en {ev.anfitrion.donde}")
    assert ev.abierto and ev.anfitrion.donde in ("hueco", "pestana") and ev.anfitrion.visible
    assert not ev.panel.isWindow() and not (ev.anfitrion.dock is not None and ev.anfitrion.dock.isFloating())
    if ev.anfitrion.donde == "pestana":               # (sin sitio: pestaña junto al Inspector; en vertical, el hueco)
        assert win.tabifiedDockWidgets(win.docks["inspector"]).count(ev.anfitrion.dock) == 1
        win.grab().save(os.path.join(out, "paso1_pestana.png"))
        ctrl.set_project_format("short")
        pump(app, 0.5)
        ev.cerrar_panel()
        b.boton.click()
        pump(app, 0.3)
        print(f"  vertical: visor {vp.width()}×{vp.height()} · hueco {ev.anfitrion._hueco()} · en {ev.anfitrion.donde}")
        assert ev.anfitrion.donde == "hueco" and not ev.anfitrion.dock.isVisible(), ev.anfitrion.donde
    assert ev.anfitrion.marco.parentWidget() is vp and ev.anfitrion.marco.isVisible()
    fr = win.preview.canvas.mapFromScene(win.preview.canvas.frame.rect()).boundingRect()
    assert ev.anfitrion.marco.geometry().left() > fr.right(), "nunca encima de la imagen"
    assert app.focusWidget() is ev.pagina.btn_elegir, app.focusWidget()
    filas = list(ev.pagina.filas)
    assert filas and filas[0].ruta == grab, [getattr(x, "ruta", None) for x in filas]
    win.grab().save(os.path.join(out, "paso1_panel.png"))

    # 3) elegir la grabación (clic en la reciente) → barras de preguntas → colocar y transcribir
    ev.ESPERA_CRECE = 300
    n_undo = ctrl.undo_stack.index()
    antes = {c.id for c in ctrl.project.clips.values()}
    filas[0].elegida.emit(grab)
    esperar(app, lambda: ev.pagina.barra.abierta, 60, "la pregunta «solo la voz / también su imagen»")
    assert "imagen" in ev.pagina.barra.texto.text(), ev.pagina.barra.texto.text()
    assert ev.job_trans is not None or llamadas, "la transcripción empieza ANTES de colocar"
    win.grab().save(os.path.join(out, "paso1_pregunta.png"))
    ev.pagina.barra.responder("voz")
    esperar(app, lambda: ev.pagina.barra.abierta, 10, "la pregunta «al inicio / en el cabezal»")
    assert "Dónde" in ev.pagina.barra.texto.text()
    ev.pagina.barra.responder("inicio")
    pump(app, 0.2)
    p = ctrl.project
    nuevos = [c for c in p.clips.values() if c.id not in antes]
    assert len(nuevos) == 1 and antes <= set(p.clips), "coloca la voz sin borrar nada"
    c = nuevos[0]
    assert p.track(c.track_id).role == "voz" and abs(c.start) < 1e-9, (p.track(c.track_id).name, c.start)
    assert "pista 2" in p.media[c.media_id].path, p.media[c.media_id].path
    assert ctrl.undo_stack.index() == n_undo + 1, "un solo Ctrl+Z"
    st = EV.estado(p)
    assert st["paso"] == 2 and st["voz"] and st["modo"] == "voz", st
    esperar(app, lambda: (p.transcripts.get(c.media_id) or {}).get("hasta") is not None, 20, "el primer trozo")
    txt = b.boton.text()
    assert txt.startswith("Paso 2 de 3 ·") and "%" in txt and b.x.isVisible(), txt
    print(f"✓ pregunta en barras (sin diálogos), coloca la voz en «🎙 Micrófono» sin borrar nada (un Ctrl+Z) y el "
          f"botón dice «{txt}» con el primer trozo ya en el proyecto")
    win.grab().save(os.path.join(out, "paso1_transcribiendo.png"))
    esperar(app, lambda: ev.job_trans is None, 30, "fin de la transcripción")
    trf = p.transcripts[c.media_id]
    assert trf.get("hasta") is None and trf["words"], trf.get("hasta")
    assert llamadas and llamadas[0][1] == 60.0, llamadas
    assert b.boton.text() == "Paso 2 de 3" and not b.x.isVisible(), b.boton.text()

    # 4) se guarda y, al reabrir, sigue en su paso (lo transcrito entra aunque no estuviera en el archivo)
    ruta = os.path.join(out, "proyecto.eia")
    ctrl.save(ruta)
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    assert d.get("edita_voz", {}).get("paso") == 2
    d["transcripts"] = {}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(d, f)
    ctrl.new_project()
    pump(app, 0.2)
    assert b.boton.text() == "Edita desde tu voz", b.boton.text()
    ctrl.load(ruta)
    pump(app, 0.3)
    p = ctrl.project
    mid = next(m.id for m in p.media.values() if "pista 2" in m.path)
    assert b.boton.text() == "Paso 2 de 3" and (p.transcripts.get(mid) or {}).get("words"), b.boton.text()
    print("✓ se guarda con el proyecto: al reabrirlo el botón sigue en «Paso 2 de 3» y su transcripción entra entera")

    # 5) cancelar: la «x» del botón para la transcripción y lo hecho se queda
    llamadas.clear()
    EV.guardar_transcripcion(EV.estado(p)["voz"][0], dict(TR, hasta=8.0, _dur=20.0))
    p.transcripts.pop(mid, None)
    ev.transcribir(EV.estado(p)["voz"])
    esperar(app, lambda: llamadas, 10, "sigue desde lo hecho")
    assert llamadas[0][2] == 8.0, llamadas
    b.x.click()
    esperar(app, lambda: ev.job_trans is None, 10, "cancelar")
    assert not b.x.isVisible()
    print("✓ sigue desde donde iba (8 s) y la «x» del botón cancela sin bloquear")
    ctrl.project.modified = False
    ctrl.undo_stack.setClean()
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
