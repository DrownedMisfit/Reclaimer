"""
🔓 Soltar archivos antes de borrarlos, moverlos o renombrarlos (core/soltar_archivos.py), sin ventanas visibles.

En Windows un archivo abierto no se puede mandar a la Papelera, mover ni renombrar («WinError 32»). El visor (pista
mixta, motor propio en pausa) deja el archivo del clip bajo el cabezal abierto con PyAV. Comprueba, con un video en la
línea de tiempo y el visor en pausa con el motor propio activo:
  1) Medios → «Eliminar archivos» (library._trash) tras quitar sus clips: el archivo sale de verdad (antes «No se
     pudieron mover»);
  2) Carpetas → mover (KF.move_files, como keywords_window) con el clip BAJO EL CABEZAL: se mueve sin fallos y, con la
     ruta nueva, el visor vuelve a abrirlo solo;
  3) renombrar una carpeta de material (material_lib.rename) con un video de dentro bajo el cabezal;
  4) quitar un archivo de una palabra clave (library._kw_trash_file) con su clip bajo el cabezal;
  5) borrar los clips de un video → el visor lo suelta solo en poco tiempo (sin tocar nada más);
  6) soltar_archivos es rápido (nunca congela) y la cola de análisis no se queda con el archivo.
Ejecutar (por el turno):  .venv/Scripts/python.exe tests/test_soltar_archivos.py <carpeta>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_soltar_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (ajustes en un .ini temporal: nunca el registro)

import faulthandler  # noqa: E402
faulthandler.dump_traceback_later(600, exit=True)       # (vigilante: nunca se queda colgada)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QFile, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

FALLOS: list[str] = []


def ok(cond, texto, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + texto + (f"  [{extra}]" if extra and not cond else ""), flush=True)
    if not cond:
        FALLOS.append(texto)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=10.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        pump(app, 0.05)
    return cond()


def clave(r):
    return os.path.normcase(os.path.abspath(r))


def abierto_por_motor(ruta) -> bool:
    """¿Alguna FrameSource (motor propio) tiene ese archivo abierto?"""
    from editoria.core import live_video as LV
    return any(clave(s.path) == clave(ruta) for s in LV.fuentes_abiertas())


def video(ruta, color):
    from editoria.core import media as M
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=s=320x180:r=30:d=6,hue=h={color}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", ruta], check=True, creationflags=M.NO_WINDOW)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "_pruebas_tmp", "test_soltar_archivos")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in ("ventana/paneles", "geometry"):
        st.remove(k)
    st.beginGroup("paneles/lado")
    st.remove("")
    st.endGroup()
    st.setValue("ventana/biblioteca_alto", "false")
    st.setValue("shorts/encuadre_auto", True)
    st.setValue("espacios/actual", "youtube")
    st.setValue("video/pausa_motor_propio", "true")          # (lo que se prueba: la pausa con el motor propio)
    st.setValue("video/motor_propio", "false")                # (pista mixta, la de por defecto)

    # 🗑 Papelera de mentira: MUEVE el archivo a una carpeta (si está abierto, falla igual que la de verdad)
    papelera = os.path.join(TMP, "papelera")
    os.makedirs(papelera, exist_ok=True)

    def a_papelera_falsa(r):
        try:
            shutil.move(r, os.path.join(papelera, f"{time.time_ns()}_{os.path.basename(r)}"))
            return True
        except OSError:
            return False
    QFile.moveToTrash = staticmethod(a_papelera_falsa)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

    from editoria.core import keyword_folders as KF
    from editoria.core import material_lib as ML
    from editoria.core.soltar_archivos import libre, soltar_archivos
    medios = os.path.join(TMP, "medios")
    os.makedirs(medios, exist_ok=True)
    vids = [os.path.join(medios, f"video{n}.mp4") for n in range(4)]
    for n, v in enumerate(vids):
        video(v, n * 60)
    material = ML.create("Prueba soltar")                    # (una carpeta de material de Reclaimer)
    v_mat = os.path.join(material, "dentro.mp4")
    video(v_mat, 250)
    vids.append(v_mat)

    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    try:
        import editoria.ui.audit_dialog as AD
        AD.revision_previa = lambda _w: True
    except Exception:  # noqa: BLE001
        pass
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 1.5)
    win.go_page("edit")
    pump(app, 0.5)
    ctrl = win.ctrl
    ids = ctrl.import_now(vids)
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        pump(app, 0.3)
    pump(app, 1.0)
    mensajes: list[str] = []
    ctrl.message.connect(mensajes.append)

    def poner(i):
        """El video i en la línea de tiempo, el cabezal encima y en pausa: el motor propio lo abre."""
        win.engine.pause()
        win.engine.user_seek(0.0)
        pump(app, 0.2)
        win._add_at_playhead([ids[i]])
        pump(app, 0.6)
        win.engine.user_seek(1.0)
        esperar(app, lambda: abierto_por_motor(vids[i]), 8.0)
        pump(app, 0.5)

    def clips_de(i):
        return [c.id for c in ctrl.project.clips.values() if c.media_id == ids[i]]

    # ---------------------------------------------------------------- 1) Medios → «Eliminar archivos»
    print("1) Medios → «Eliminar archivos» tras quitar sus clips", flush=True)
    poner(0)
    ok(abierto_por_motor(vids[0]) and not libre(vids[0]),
       "(premisa) en pausa, el motor propio tiene abierto el archivo del cabezal")
    win.timeline.set_selection(clips_de(0))
    win._delete(False)
    pump(app, 0.1)                                   # (¡enseguida! antes de que el visor lo suelte por su cuenta)
    ok(not ctrl.project.is_media_used(ids[0]), "sus clips quitados")
    mensajes.clear()
    t = time.perf_counter()
    win.library._trash([ids[0]])
    dt = time.perf_counter() - t
    pump(app, 0.2)
    ok(not os.path.exists(vids[0]), "el archivo salió de verdad (a la Papelera)", str(mensajes[-1:]))
    ok(not any("No se pudieron" in m for m in mensajes), "sin «No se pudieron mover»", str(mensajes[-1:]))
    ok(dt < 3.0, f"rápido ({dt:.2f} s)")

    # ---------------------------------------------------------------- 2) Carpetas → mover (KF.move_files)
    print("2) Carpetas → mover con el clip bajo el cabezal (KF.move_files)", flush=True)
    poner(1)
    ok(abierto_por_motor(vids[1]), "(premisa) el motor propio lo tiene abierto")
    destino = os.path.join(TMP, "destino")
    t = time.perf_counter()
    movidos, fallos = KF.move_files([vids[1]], destino)
    dt = time.perf_counter() - t
    ok(len(movidos) == 1 and not fallos, "se movió sin WinError 32", str([f[1][:80] for f in fallos]))
    ok(not os.path.exists(vids[1]), "el original ya no está")
    ok(dt < 3.0, f"rápido ({dt:.2f} s)")
    if movidos:
        nueva = movidos[0][1]
        ctrl.move_media_path(vids[1], nueva)
        win.engine.user_seek(1.5)
        ok(esperar(app, lambda: abierto_por_motor(nueva), 8.0),
           "con la ruta nueva, el visor lo vuelve a abrir solo (motor propio)")

    # ---------------------------------------------------------------- 3) renombrar una carpeta de material
    print("3) Renombrar una carpeta de material con un video de dentro bajo el cabezal", flush=True)
    i_mat = vids.index(v_mat)
    poner(i_mat)
    ok(abierto_por_motor(v_mat), "(premisa) el motor propio tiene abierto el de dentro")
    nueva_carpeta = ML.rename(material, "Prueba soltar 2")
    ok(bool(nueva_carpeta) and os.path.isdir(nueva_carpeta) and not os.path.exists(material),
       "la carpeta se renombró sin WinError 32", str(nueva_carpeta))

    # ---------------------------------------------------------------- 4) quitar de una palabra clave
    print("4) Quitar un archivo de una palabra clave (library._kw_trash_file) con su clip bajo el cabezal", flush=True)
    poner(2)
    ok(abierto_por_motor(vids[2]), "(premisa) el motor propio lo tiene abierto")
    mensajes.clear()
    win.library._kw_trash_file(vids[2])
    pump(app, 0.2)
    ok(not os.path.exists(vids[2]), "el archivo salió (a la Papelera)", str(mensajes[-1:]))
    ok(not any("No pude" in m for m in mensajes), "sin «No pude mandar…»", str(mensajes[-1:]))

    # ---------------------------------------------------------------- 5) borrar los clips → el visor lo suelta solo
    print("5) Borrar los clips de un video: el visor lo suelta solo", flush=True)
    poner(3)
    ok(abierto_por_motor(vids[3]) and not libre(vids[3]), "(premisa) abierto por el motor propio")
    win.timeline.set_selection(clips_de(3))
    win._delete(False)
    t = time.time()
    suelto = esperar(app, lambda: not abierto_por_motor(vids[3]) and libre(vids[3]), 5.0)
    ok(suelto, f"suelto en poco tiempo ({time.time() - t:.1f} s; antes, ni a los 40 s)")
    ok(not (clave(vids[3]) in win.engine.rutas_abiertas()), "el visor ya no lo cuenta entre sus archivos abiertos")
    try:                                              # (y se puede renombrar de verdad)
        os.rename(vids[3], vids[3] + ".x")
        os.rename(vids[3] + ".x", vids[3])
        ok(True, "se puede renombrar a mano")
    except OSError as e:
        ok(False, "se puede renombrar a mano", repr(e))
    ctrl.undo_stack.undo()                            # (Ctrl+Z: vuelve el clip y el visor lo abre otra vez)
    win.engine.user_seek(1.2)
    ok(esperar(app, lambda: abierto_por_motor(vids[3]), 8.0), "con Ctrl+Z el visor lo vuelve a abrir")

    # ---------------------------------------------------------------- 6) soltar_archivos: rápido y la cola suelta
    print("6) soltar_archivos directo: rápido; nada nuevo lo abre mientras está retenido", flush=True)
    t = time.perf_counter()
    quedan = soltar_archivos([vids[3]])
    dt = time.perf_counter() - t
    ok(not quedan and libre(vids[3]), "suelto (también los análisis en segundo plano)", str(quedan))
    ok(dt < 2.0, f"rápido ({dt:.2f} s)")
    win.engine.user_seek(1.4)
    pump(app, 0.5)
    ok(libre(vids[3]), "mientras está retenido, el visor no lo vuelve a abrir")
    ok(esperar(app, lambda: abierto_por_motor(vids[3]) and not libre(vids[3]), 8.0),
       "pasada la retención, el visor lo vuelve a abrir solo")
    ok(soltar_archivos([os.path.join(TMP, "no_existe.mp4")]) == [], "una ruta que no existe: nada que esperar")

    # ---------------------------------------------------------------- 7) un hilo que mueve SIN soltar antes
    print("7) Un hilo mueve el archivo sin soltarlo antes en el principal (no cae; si falla, lo dice)", flush=True)
    import threading
    from editoria.core import live_video as LV
    from editoria.ui import descargas_generales as DG
    pump(app, 0.8)                                    # (el reproductor de Qt también se coloca: lo abre)
    ok(not libre(vids[3]), "(premisa) el visor lo tiene abierto")
    res: dict = {}
    destino_hilo = os.path.join(TMP, "destino_hilo")

    def en_hilo():
        try:
            res["r"] = KF.move_files([vids[3]], destino_hilo)
        except BaseException as e:  # noqa: BLE001
            res["error"] = repr(e)
    th = threading.Thread(target=en_hilo)
    th.start()
    while th.is_alive():
        pump(app, 0.05)
    ok("error" not in res, "el hilo no cae", res.get("error", ""))
    movidos, fallos = res.get("r", ([], []))
    if fallos:
        motivo = DG.explicar_fallo(fallos[0][1])
        print(f"    (falló, como se espera si Qt lo tenía: «{motivo}»)", flush=True)
        ok("abierto" in motivo, "avisa del fallo con un motivo claro", motivo)
        ok(os.path.exists(vids[3]) and not os.listdir(destino_hilo), "el archivo sigue en su sitio, sin copias a medias")
        ok(not LV.retenido(vids[3]), "al acabar (aunque falle) ya no está retenido")
        win.engine.user_seek(1.6)
        ok(esperar(app, lambda: not libre(vids[3]), 1.5), "y el visor lo vuelve a abrir enseguida (no 3 s congelado)")
    else:
        print("    (se movió: solo lo tenía el motor propio, que se suelta también desde otro hilo)", flush=True)
        ok(len(movidos) == 1 and not os.path.exists(vids[3]), "se movió entero")
        # y si otro (aquí, un archivo abierto a mano, como haría un reproductor de Qt sin soltar) lo tiene: falla y avisa
        nueva = movidos[0][1]
        ctrl.move_media_path(vids[3], nueva)
        win.engine.user_seek(1.7)
        esperar(app, lambda: abierto_por_motor(nueva), 8.0)
        destino_hilo2 = os.path.join(TMP, "destino_hilo2")
        res.clear()
        with open(nueva, "rb"):                           # (abierto sin compartir el borrado: Windows no deja moverlo)
            def en_hilo2():
                try:
                    res["r"] = KF.move_files([nueva], destino_hilo2)
                except BaseException as e:  # noqa: BLE001
                    res["error"] = repr(e)
            th = threading.Thread(target=en_hilo2)
            th.start()
            while th.is_alive():
                pump(app, 0.05)
            ok("error" not in res, "con el archivo abierto por otro: el hilo no cae", res.get("error", ""))
            _m, fallos2 = res.get("r", ([], []))
            motivo = DG.explicar_fallo(fallos2[0][1]) if fallos2 else ""
            ok(bool(fallos2) and "abierto" in motivo, "avisa del fallo con un motivo claro", motivo or str(res))
            ok(os.path.exists(nueva) and not os.listdir(destino_hilo2), "el archivo sigue en su sitio, sin copias a medias")
            ok(not LV.retenido(nueva), "al acabar (aunque falle) ya no está retenido")
            win.engine.user_seek(1.8)
            ok(esperar(app, lambda: abierto_por_motor(nueva), 1.5),
               "y el visor lo vuelve a abrir enseguida (no 3 s congelado)")

    ctrl.undo_stack.setClean()
    win.close()
    pump(app, 0.3)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s): {FALLOS}")
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
