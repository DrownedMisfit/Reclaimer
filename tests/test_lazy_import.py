"""
Prueba de «importar ligero»: al importar material solo se lee lo barato (ffprobe + miniatura). La forma de onda
(lo caro) se calcula cuando el medio entra en la línea de tiempo, o cuando una acción la necesita (ensure_peaks).
Las copias ligeras (proxies) solo son de lo que está en la línea de tiempo. Sin ventanas visibles.
Ejecutar:  .venv/Scripts/python.exe tests/test_lazy_import.py <carpeta_salida>
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
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def esperar(app, cond, secs, what):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.05)
    assert cond(), f"tiempo agotado esperando: {what}"


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    vids = []
    for i, freq in enumerate((220, 330, 440, 550, 660, 770)):
        v = os.path.join(out, f"clip_{i}.mp4")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4",
                        "-f", "lavfi", "-i", f"sine=f={freq}:d=4", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", "-shortest", v], check=True, timeout=180)
        vids.append(v)

    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("reproduccion/proxy", "reproduccion/copias_auto")}
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow

    # Contador de cada cálculo de forma de onda (lo caro) que de verdad se ejecuta
    cuenta = {"peaks": 0}
    orig_peaks = media_tools.waveform_peaks

    def contado(path):
        cuenta["peaks"] += 1
        return orig_peaks(path)
    media_tools.waveform_peaks = contado

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    ctrl = win.ctrl
    p = ctrl.project
    win.proxies.set_level("half")          # calidad «Media» (la que usa un PC modesto por defecto)
    pump(app, 0.2)

    # ------------------------------------------------ 1) importar: solo lo barato
    ids = ctrl.import_paths(vids)
    assert len(ids) == 6, ids
    esperar(app, lambda: all(p.media[i].probed for i in ids) and not ctrl.analyzing, 180, "ffprobe de los 6")
    for i in ids:
        m = p.media[i]
        assert m.duration > 3.0, (m.name, m.duration)
        assert i in ctrl.thumbs, f"sin miniatura: {m.name}"
    assert cuenta["peaks"] == 0, f"al importar no debe calcularse ninguna forma de onda: {cuenta}"
    assert not ctrl.peaks, f"sin picos al importar: {list(ctrl.peaks)}"
    assert win.proxies.pending() == [], "sin clips en la línea de tiempo no hay copias ligeras que hacer"
    print("✓ Importar 6 videos: duración y miniatura de todos; 0 formas de onda; 0 copias ligeras pendientes")

    # ------------------------------------------------ 2) colocar 1 en la línea de tiempo
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    a, b = ids[0], ids[1]
    made = ctrl.add_media([a], v1.id, 0.0)
    assert made, "no se colocó el clip"
    pend = win.proxies.pending()
    assert any(x[0] == a and x[4] == "half" for x in pend), pend
    assert all(x[0] == a for x in pend), f"solo el medio usado debe tener copia: {pend}"
    print("✓ Copia ligera pendiente (calidad Media) solo para el video que está en la línea de tiempo")

    esperar(app, lambda: a in ctrl.peaks, 120, "picos del medio colocado")
    assert cuenta["peaks"] == 1, cuenta
    assert set(ctrl.peaks) == {a}, list(ctrl.peaks)
    print("✓ Al colocarlo se calculan sus picos SOLO a él (1 cálculo)")

    esperar(app, lambda: not win.proxies.job and not win.proxies.pending(), 300,
            "copia ligera del medio colocado")
    print("✓ Su copia ligera se hizo y ya no está pendiente")

    # ------------------------------------------------ 3) pedir los picos de otro, al momento
    pk = ctrl.ensure_peaks(b, wait=True)
    assert pk is not None and len(pk) > 1000, pk
    assert cuenta["peaks"] == 2, cuenta
    assert b in ctrl.peaks
    assert ctrl.ensure_peaks(b, wait=True) is pk and cuenta["peaks"] == 2, "la segunda vez no vuelve a calcular"
    print("✓ ensure_peaks(otro, wait=True) los calcula al momento (1 cálculo más)")

    # ------------------------------------------------ 4) «Eliminar silencio» en un clip sin picos
    c_ids = ctrl.add_media([ids[2]], v1.id, 10.0)
    cid = c_ids[0]
    c_mid = ids[2]
    if c_mid in ctrl.peaks:                     # (por si acaso: la prueba quiere un medio sin picos)
        ctrl.peaks.pop(c_mid)
    antes = p.clips[cid].duration
    n = ctrl.remove_silence([cid], [(10.5, 11.0)], scope="all")
    assert n == 1, n
    assert p.clips[cid].duration < antes - 0.4, (antes, p.clips[cid].duration)
    print("✓ «Eliminar silencio» funciona en un clip cuyo medio no tenía picos")

    # ------------------------------------------------ 5) analizar a fondo lo seleccionado (manual)
    esperar(app, lambda: not ctrl.analyzing, 120, "análisis")
    antes_full = cuenta["peaks"]
    n_full = ctrl.analyze_full([ids[3]])
    assert n_full == 1, n_full
    esperar(app, lambda: ids[3] in ctrl.peaks, 120, "analizar a fondo")
    assert cuenta["peaks"] == antes_full + 1, (antes_full, cuenta)
    print("✓ «Analizar a fondo» de un medio no usado calcula sus picos a petición")

    # ------------------------------------------------ limpieza
    ctrl.shutdown(20000)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    media_tools.waveform_peaks = orig_peaks
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
