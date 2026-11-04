"""
Prueba de «◈ Dónde sale» en la ventana «🎯 Ejemplo»: la barra pinta en naranja los momentos que se parecen a lo
que escribiste (y a tus ✓/✗), ◀ ▶ saltan de uno a otro, la tira de fotogramas lo muestra, y al cambiar de
momento el recuadro se quita (era de otro fotograma).
Sin modelos: huellas inventadas (como si el clip ya estuviera analizado) y un vector de texto ya calculado.
Usa una carpeta de datos TEMPORAL; deja tu distribución como estaba.
Ejecutar:  .venv/Scripts/python.exe tests/test_example_match.py <carpeta_salida>
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
os.makedirs(_TMPROOT, exist_ok=True)       # en D: (junto al programa), nunca en el TEMP de C:
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)   # se borra al terminar
os.environ["LOCALAPPDATA"] = _TMP          # ¡antes de importar el programa!
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.ai import frame_match
    from editoria.core import media as media_tools
    from editoria.ui.example_dialog import ExampleDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)

    # 1) El cálculo: sale en 6–8 s y en 15–16 s; lo demás es otra cosa
    rng = np.random.default_rng(3)
    chief, other = rng.normal(size=512), rng.normal(size=512)
    times = np.arange(0.5, 20.0, 1.0, dtype=np.float32)
    vecs = np.stack([(chief if (6 <= t <= 8 or 15 <= t <= 16) else other) + 0.35 * rng.normal(size=512)
                     for t in times]).astype(np.float32)
    lv = frame_match.curve(vecs, chief)
    pk = frame_match.peaks(times, lv)
    assert len(pk) == 2 and 5.5 <= pk[0] <= 8.5 and 14.5 <= pk[1] <= 16.5, (pk, lv.round(2))
    assert lv[times.tolist().index(2.5)] < 0.2 and lv[times.tolist().index(7.5)] > 0.6
    # un ✗ en el segundo sitio lo baja
    neg_lv = frame_match.curve(vecs, chief, None, vecs[times.tolist().index(15.5)][None])
    assert neg_lv[15] < lv[15], "tu ✗ baja ese sitio"
    print(f"✓ dónde sale: sitios probables en {[round(t, 1) for t in pk]} s (✗ baja los que no son)")

    # 2) En la ventana
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    pump(app, 0.3)
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=20", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
    ctrl = win.ctrl
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    ctrl.clip_vecs[ids[0]] = (times, vecs)           # como si ya estuviera analizado
    dlg = ExampleDialog(ctrl, ids[0], 1.0, 0.0, 19.9, "", win)
    dlg._qvecs["jefe maestro"] = chief / np.linalg.norm(chief)    # el texto ya «calculado»
    dlg.show()
    t0 = time.time()
    while len(dlg.strip.frames) < 12 and time.time() - t0 < 30:
        pump(app, 0.1)
    assert not dlg.b_next.isEnabled() and dlg.match.times is None, "sin nombre no marca nada"
    dlg.name.setText("jefe maestro")
    pump(app, 1.3)                                   # espera a que dejes de escribir
    t0 = time.time()
    while (dlg.match.times is None or len(dlg.match.peaks) < 2) and time.time() - t0 < 10:
        pump(app, 0.1)                               # (con el PC ocupado puede tardar algo más)
    assert dlg.match.times is not None and len(dlg.match.peaks) == 2, dlg.match.peaks
    assert dlg.b_next.isEnabled() and "(2)" in dlg.match_label.text()
    assert dlg._level_at(7.0) > 0.6 and dlg._level_at(2.0) < 0.2
    dlg._jump(1)
    assert abs(dlg.t - dlg.match.peaks[0]) < 0.06, (dlg.t, dlg.match.peaks)
    dlg._jump(1)
    assert abs(dlg.t - dlg.match.peaks[1]) < 0.06
    dlg._jump(1)
    assert abs(dlg.t - dlg.match.peaks[0]) < 0.06, "al final vuelve al primero"
    dlg._jump(-1)
    assert abs(dlg.t - dlg.match.peaks[1]) < 0.06
    print("✓ ventana: barra naranja «◈ Dónde sale (2)», ◀ ▶ saltan de un sitio a otro, la tira lo muestra")

    # 3) El recuadro se quita al cambiar de momento
    pump(app, 0.4)
    dlg.view.rect_n = QRectF(0.3, 0.2, 0.3, 0.5)
    dlg.grab().save(os.path.join(out, "donde_sale.png"))
    dlg.slider.setValue(dlg.slider.value() + 10)
    assert dlg.view.rect_n is None, "al mover la barra, el recuadro se quita"
    dlg.view.rect_n = QRectF(0.3, 0.2, 0.3, 0.5)
    dlg.strip.picked.emit(3.0)
    assert dlg.view.rect_n is None and abs(dlg.t - 3.0) < 0.06, "también al elegir en la tira"
    dlg.view.rect_n = QRectF(0.3, 0.2, 0.3, 0.5)
    dlg._jump(1)
    assert dlg.view.rect_n is None, "y al saltar con ▶"
    print("✓ al moverte (barra, tira o ▶) el recuadro naranja desaparece: no confunde a la IA")

    # 4) Tus ✓ afinan (sin texto también funciona)
    dlg.name.setText("cosa nueva")
    dlg._mtimer.stop()
    good = vecs[times.tolist().index(15.5)]
    dlg.examples.append({"good": True, "name": "cosa nueva", "key": "k", "vec": good, "media_id": ids[0], "t": 15.5})
    dlg._qvecs["cosa nueva"] = other / np.linalg.norm(other)
    dlg._apply_match()
    assert dlg._level_at(7.0) > 0.5 and dlg._level_at(2.0) < 0.2, "tu ✓ manda aunque el texto no ayude"
    dlg.reject()
    pump(app, 0.2)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    for k, v in keep.items():
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    st.remove("guia/colocada")
    print("TODO OK — captura en", out)


if __name__ == "__main__":
    main()
