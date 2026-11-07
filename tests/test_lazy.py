"""
Prueba de «solo trabajar cuando se usa»: con el panel oculto no se recalcula nada, y al mostrarlo se pone al día
una sola vez. Cubre: Clips, Texto (transcripción), guía (temporizador), copias ligeras (proxies) y el espectro del
ecualizador del Inspector. Sin ventanas visibles (QT_QPA_PLATFORM=offscreen).
Ejecutar:  .venv/Scripts/python.exe tests/test_lazy.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def contador(original, cuenta, clave):
    def envoltura(*a, **k):
        cuenta[clave] += 1
        return original(*a, **k)
    return envoltura


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.core import media as media_tools
    from editoria.core import proxies
    vid = os.path.join(out, "lazy_colores.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "smptebars=s=1280x720:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", vid], check=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "reproduccion/proxy", "reproduccion/copias_auto")}
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    import editoria.ui.clips_panel as clips_mod
    import editoria.ui.inspector as insp_mod
    from editoria.core import keyword_folders as KF
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    pump(app, 0.5)

    def dock_de(clave):
        d = win.findChild(QDockWidget, "dock_" + clave)
        assert d is not None, clave
        return d

    def ocultar(clave):
        dock_de(clave).hide()
        pump(app, 0.2)

    def mostrar(widget):
        win.show_panel(widget)
        pump(app, 0.2)

    ctrl = win.ctrl
    cuenta = {"fm": 0, "lf": 0, "rb": 0, "rq": 0}

    # ---------------------------------------------------------------- Clips
    clips = win.clips
    clips_mod.find_mentions = contador(clips_mod.find_mentions, cuenta, "fm")
    KF.list_folders = contador(KF.list_folders, cuenta, "lf")
    ocultar("clips")
    assert not clips.isVisible()
    for _ in range(3):
        ctrl.project_changed.emit()
        ctrl.transcript_changed.emit("")
        pump(app, 0.05)
    pump(app, 1.6)
    assert cuenta["fm"] == 0 and cuenta["lf"] == 0, cuenta
    print("✓ Clips oculto: varios cambios del proyecto no escanean carpetas ni buscan menciones")
    mostrar(clips)
    pump(app, 1.6)
    assert clips.isVisible()
    assert cuenta["fm"] == 1 and cuenta["lf"] == 1, cuenta
    print("✓ Clips al mostrarse se pone al día una sola vez (1 búsqueda de menciones, 1 lectura de carpetas)")

    # ---------------------------------------------------------------- Texto (transcripción)
    tp = win.transcript
    orig_rb = tp._rebuild

    def rb_contado():
        cuenta["rb"] += 1
        orig_rb()
    tp._rebuild = rb_contado
    ocultar("transcript")
    assert not tp.isVisible()
    # El texto solo se reconstruye si cambió algo que se ve (⚡ firma): por eso cada aviso va con un cambio real
    for i in range(3):
        ctrl.project.subtitles.highlight = "#00FFAA" if i % 2 else "#FF0000"   # (el último cambio debe ser distinto del de partida)
        ctrl.project_changed.emit()
        ctrl.transcript_changed.emit("")
        pump(app, 0.03)
    pump(app, 0.9)
    assert cuenta["rb"] == 0, cuenta
    print("✓ Texto oculto: no reconstruye la transcripción con cada cambio")
    mostrar(tp)
    pump(app, 0.3)
    assert cuenta["rb"] == 1, cuenta
    print("✓ Texto al mostrarse se reconstruye una vez")
    cuenta["rb"] = 0
    ctrl.project.subtitles.highlight = "#00FF00"
    ctrl.project_changed.emit()
    pump(app, 0.9)
    assert cuenta["rb"] == 1, cuenta
    print("✓ Texto visible: un cambio se refleja enseguida (una reconstrucción)")
    tp.ensure_built()

    # ---------------------------------------------------------------- Guía: temporizador
    guia = win.guided
    ocultar("guided")
    assert not guia.isVisible() and not guia._temporizador.isActive()
    print("✓ Montaje guiado oculto: su temporizador está parado")
    # con Clips oculto y un cambio pendiente, al mostrar la guía se recalcula (lo que pide su paso 4)
    ocultar("clips")
    clips._firma_ultima = None        # firma desconocida: así se prueba la búsqueda pendiente (sin cambios reales)
    ctrl.project_changed.emit()
    pump(app, 0.1)
    assert clips._pendiente, "Clips debería quedar pendiente"
    cuenta["fm"] = 0
    mostrar(guia)
    pump(app, 0.3)
    assert guia.isVisible() and guia._temporizador.isActive()
    assert cuenta["fm"] == 1 and not clips._pendiente, cuenta
    print("✓ Montaje guiado visible: su temporizador corre y pide el recálculo pendiente de Clips")
    ocultar("guided")
    assert not guia._temporizador.isActive()
    print("✓ Montaje guiado al ocultarse: el temporizador vuelve a parar")

    # ---------------------------------------------------------------- Copias ligeras
    pm = win.proxies
    orig_ensure = pm.ensure
    pm.ensure = lambda: None                      # solo miramos qué encolaría (sin lanzar ffmpeg)
    ids = ctrl.import_paths([vid])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.05)
    assert ids and ctrl.project.media[ids[0]].probed, "el video de prueba no quedó analizado"
    pm.set_level("full")
    assert pm.levels() == [] and pm.pending() == [], (pm.levels(), pm.pending())
    print("✓ Calidad «Completa»: no encola ninguna copia ligera para un video importado")
    cuenta["rq"] = 0
    orig_hw = proxies.hw_encoder
    proxies.hw_encoder = contador(orig_hw, cuenta, "rq")
    pm.ensure = orig_ensure
    pm.ensure()
    proxies.hw_encoder = orig_hw
    assert pm.job is None and cuenta["rq"] == 0, (pm.job, cuenta)
    print("✓ Sin nada que preparar, ensure() no consulta la tarjeta gráfica ni arranca trabajo")
    pm.ensure = lambda: None
    pm.set_level("half")
    assert pm.pending() == [], "en Medios sin usar: ninguna copia ligera (solo de lo que está en la línea de tiempo)"
    ctrl.add_media([ids[0]], None, 0.0)             # ahora sí está en la línea de tiempo
    niveles = {t[4] for t in pm.pending()}
    assert niveles == {"half"}, niveles
    print("✓ Calidad «Media»: encola solo la copia «Media» (no «Un cuarto»)")
    pm.set_level("full")
    pm.ensure = orig_ensure
    ctrl.ensure_peaks(ids[0], wait=True)          # (al entrar en la línea de tiempo se calcula su onda: que acabe)
    pump(app, 0.3)

    # ---------------------------------------------------------------- Inspector: espectro del ecualizador
    insp = win.inspector
    cuenta["rq"] = 0
    from editoria.ui import inspector as insp_mod      # (solo el ffmpeg DEL ESPECTRO: otros trabajos legítimos, como
    orig_rq = insp_mod._muestras_espectro               #  leer un fotograma del clip recién puesto, no cuentan)
    insp_mod._muestras_espectro = contador(orig_rq, cuenta, "rq")
    ocultar("inspector")
    assert not insp.eq_graph.isVisible()
    insp._update_spectrum()
    insp._spectrum_timer.start()
    pump(app, 0.8)
    insp_mod._muestras_espectro = orig_rq
    assert cuenta["rq"] == 0, cuenta
    print("✓ Inspector oculto (gráfica del ecualizador no visible): no lanza ffmpeg del espectro")

    # ---------------------------------------------------------------- limpieza
    for k in ("clips", "transcript", "guided", "inspector"):
        dock_de(k).show()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
