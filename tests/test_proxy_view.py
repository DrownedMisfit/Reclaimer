"""
Prueba de «Calidad» (copias ligeras): al abrir, la lista muestra la calidad guardada de verdad, y al cambiar a
«Un cuarto» con el video en pausa el visor muestra la imagen (antes se quedaba en negro hasta reproducir).
Usa una carpeta de datos TEMPORAL.
Ejecutar:  .venv/Scripts/python.exe tests/test_proxy_view.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def brightness(widget) -> float:
    img = widget.grab().toImage().convertToFormat(widget.grab().toImage().Format.Format_RGB888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    arr = arr[:, :w * 3].reshape(h, w, 3)
    return float(arr[h // 4:3 * h // 4, w // 4:3 * w // 4].mean())


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.core import media as media_tools
    from editoria.core import proxies
    vid = os.path.join(out, "colores.mp4")
    if not os.path.exists(vid):
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "smptebars=s=1280x720:r=30:d=20", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", vid], check=True)
    st = QSettings("EditorIA", "EditorIA")
    saved = st.value("reproduccion/proxy")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "reproduccion/copias_auto")}
    st.setValue("reproduccion/proxy", "quarter")         # como lo tenías guardado
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    assert win.preview.quality.currentData() == "quarter" == win.ctrl.proxy_level, \
        (win.preview.quality.currentData(), win.ctrl.proxy_level)
    print("✓ al abrir, «Calidad» muestra la que se usa de verdad («Un cuarto»), no «Completa»")
    win.set_proxy_level("full")
    ctrl = win.ctrl
    ids = ctrl.import_paths([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    m = ctrl.project.media[ids[0]]
    proxies.make_proxy(m.path, m.height, "quarter")
    ctrl.add_media(ids, None, 0.0)
    win.engine.seek(5.0)
    pump(app, 1.5)
    canvas = win.preview.canvas
    full = brightness(canvas)
    win.preview.quality.setCurrentIndex(win.preview.quality.findData("quarter"))   # como lo haces tú
    pump(app, 1.5)
    assert ctrl.preview_path(m).endswith("_quarter.mp4")
    quarter = brightness(canvas)
    canvas.grab().save(os.path.join(out, "visor_un_cuarto.png"))
    print(f"brillo del visor: completa {full:.0f} · un cuarto {quarter:.0f}")
    if full > 40:     # solo se puede comprobar si el visor pinta video en esta prueba (sin pantalla)
        assert quarter > full * 0.6, f"el visor se quedó en negro al pasar a «Un cuarto» ({quarter:.0f})"
        print("✓ al pasar a «Un cuarto» en pausa, el visor muestra la imagen (no se queda en negro)")
    else:
        print("· (sin pantalla real no se pinta el video: comprobado solo el cambio de archivo)")
    # Automático: en «Completa» también se preparan solas las copias «Media» y «Un cuarto» (sin prisa)
    win.proxy_level_for_test = None
    win.set_proxy_level("full")
    pm = win.proxies
    pm.set_auto(True)
    assert set(t[4] for t in pm.pending()) >= {"half"}, pm.pending()
    t0 = time.time()
    while (pm.job is not None or pm.pending()) and time.time() - t0 < 120:
        pm.ensure()
        pump(app, 0.3)
    assert proxies.has_proxy(m.path, "half") and proxies.has_proxy(m.path, "quarter")
    pm.set_auto(False)
    print("✓ copias ligeras automáticas: en «Completa» se preparan «Media» y «Un cuarto» para cambiar al momento")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    if saved is None:
        st.remove("reproduccion/proxy")
    else:
        st.setValue("reproduccion/proxy", saved)
    for k, v in keep.items():          # tus ajustes, como estaban (antes se borraban los paneles y la ventana)
        if v is None:
            st.remove(k)
        else:
            st.setValue(k, v)
    st.remove("guia/colocada")
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
