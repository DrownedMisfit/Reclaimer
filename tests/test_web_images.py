"""
Prueba de la búsqueda de imágenes en internet (Openverse) dentro del panel «🔎 Momentos».
Solo consulta la lista de resultados; las descargas (miniaturas e imagen) se simulan con una
imagen local para no bajar archivos durante la prueba.
Ejecutar:  .venv/Scripts/python.exe tests/test_web_images.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import web_images as WI  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    fake = os.path.join(out, "falsa.jpg")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "smptebars=s=640x360", "-frames:v", "1", fake], check=True)

    def fake_fetch(url, dest, timeout=30, limit=0):   # sin descargas reales
        import shutil
        shutil.copy(fake, dest)
        return dest
    WI.fetch = fake_fetch
    WI.folder = lambda: out   # lo «descargado» queda en la carpeta de la prueba

    # 1) La API devuelve resultados con licencia comercial
    try:
        res = WI.search("spartan helmet", page_size=6)
    except Exception as exc:  # noqa: BLE001
        print(f"(sin internet: prueba omitida — {exc})")
        return
    assert res and all("nc" not in r["license"] and "nd" not in r["license"] for r in res), res[:2]
    print(f"✓ Openverse: {len(res)} imágenes, todas con licencia de uso comercial "
          f"(p. ej. {res[0]['license_text']} · {res[0]['creator']})")

    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl, panel = win.ctrl, win.moments
    win.show_panel(panel)
    panel.source.setCurrentIndex(panel.source.findData("web"))
    assert panel.b_google.isVisible() and not panel.known.isEnabled()
    panel.query.setText("spartan helmet")
    panel.search_text()
    t0 = time.time()
    while (panel.job is not None) and time.time() - t0 < 60:
        pump(app, 0.1)
    pump(app, 0.3)
    assert panel.web_results and panel.grid.count() == len(panel.web_results), (panel.status.text(), len(panel.web_results), panel.grid.count())
    assert not ctrl.project.media, "buscar NO descarga ni importa nada"
    print(f"✓ resultados de internet separados de tus archivos: {panel.grid.count()} (nada descargado)")
    win.grab().save(os.path.join(out, "internet.png"))

    # 2) «Usar»: ahora sí se descarga, se importa y se coloca
    win.engine.seek(0.0)
    panel.grid.setCurrentRow(0)
    panel.place("insert")
    p = ctrl.project
    clips = [c for t in p.tracks if t.kind == TRACK_VIDEO for c in p.clips_on(t.id)]
    assert len(clips) == 1 and p.media[clips[0].media_id].category == "Internet"
    assert os.path.exists(os.path.join(out, "créditos.txt"))
    print("✓ «Usar»: se descarga en ese momento, va a la biblioteca («Internet») y a la línea de tiempo; "
          "su crédito queda en créditos.txt")
    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
