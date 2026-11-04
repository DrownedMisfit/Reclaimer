"""
Prueba del buscador de momentos (panel «🔎 Momentos») con material real si existe.
Ejecutar:  .venv/Scripts/python.exe tests/test_moments.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import library_understanding as LU  # noqa: E402
from editoria.ai import moments as MO  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_VIDEO  # noqa: E402

HALO = os.environ.get("RECLAIMER_VIDEO_1", "")    # un video de prueba tuyo (no viene con Reclaimer)
GEARS = os.environ.get("RECLAIMER_VIDEO_2", "")   # otro video de prueba


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def wait(app, panel, limit=120):
    t0 = time.time()
    pump(app, 0.2)
    while panel.job is not None and time.time() - t0 < limit:
        pump(app, 0.1)
    pump(app, 0.2)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    if not (os.path.exists(HALO) and os.path.exists(GEARS)):
        print("(sin material real: prueba omitida)")
        return
    # 1) Segmentación: segundos seguidos = una aparición; lejos = otra
    import numpy as np
    t = np.arange(0, 30, 1.0)
    s = np.zeros(30)
    s[[5, 6, 7, 8, 20, 21]] = 5.0
    seg = MO.segments(t, s, 3.0, 30.0)
    assert [(a, b) for a, b, _x, _y in seg] == [(4.5, 8.5), (19.5, 21.5)], seg
    print("✓ apariciones con inicio y fin; si vuelve a salir más tarde, es otra aparición")

    ff = media_tools.ffmpeg()
    ref = os.path.join(out, "referencia casco.png")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", "37.0", "-i", HALO, "-frames:v", "1",
                           "-vf", "crop=1080:1080:0:420", ref])
    app = QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    ctrl, panel = win.ctrl, win.moments
    halo, gears = ctrl.import_now([HALO, GEARS])
    for mid in (halo, gears):   # análisis a fondo (en caché tras la primera vez)
        m = ctrl.project.media[mid]
        ctrl.set_deep_analysis(mid, LU.analyze_deep(m.path, m.kind, m.duration))

    # 2) Buscar por imagen de referencia
    win.show_panel(panel)
    panel.search_image(ref)
    wait(app, panel)
    assert panel.results, "hay resultados"
    best = panel.results[0]
    assert best.media_id == halo and best.start <= 37.5 <= best.end + 1.0, best
    assert panel.grid.count() == len(panel.results)
    print(f"✓ por imagen: {len(panel.results)} apariciones; la mejor en el Halo edit "
          f"{best.start:.1f}→{best.end:.1f} s (el casco está a los 37 s)")
    win.grab().save(os.path.join(out, "momentos.png"))

    # 3) Insertar en el cabezal (sin tapar nada), reemplazar y añadir después
    p = ctrl.project
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    base = ctrl.add_media([gears], v1.id, 0.0)[0]
    win.engine.seek(5.0)
    pump(app, 0.2)
    panel.grid.setCurrentRow(0)
    panel.t_in.setValue(best.start)
    panel.t_out.setValue(min(best.end, best.start + 2.0))
    panel.place("insert")
    new = p.clips[sorted(win.timeline.selected)[0]]
    assert new.media_id == halo and abs(new.start - 5.0) < 0.05 and new.track_id != v1.id
    assert abs(p.clips[base].duration - p.media[gears].duration) < 0.1, "no tapó el clip de debajo"
    print("✓ insertar en el cabezal: en una pista libre, sin tapar el clip de debajo")
    win.timeline.set_selection([base])
    panel.place("after")
    after = p.clips[sorted(win.timeline.selected)[0]]
    assert abs(after.start - p.clips[base].end) < 0.05
    print("✓ añadir después del clip seleccionado")
    win.timeline.set_selection([base])
    dur0 = p.clips[base].duration
    panel.place("replace")
    rep = p.clips[base]
    assert rep.media_id == halo and abs(rep.start) < 1e-6 and rep.duration <= dur0 + 1e-6
    print("✓ reemplazar: mismo sitio, contenido del momento elegido")

    # 4) Favoritos
    panel._toggle_fav()
    assert len(p.favorites) == 1
    panel.show_favorites()
    assert panel.grid.count() == 1
    print("✓ favoritos: se guardan con el proyecto y se pueden volver a ver")

    # 5) Lo que conoce la IA (tras entender la biblioteca)
    from editoria.ui.understand_dialog import glossary_text, snapshot, understand
    refimg = ctrl.import_now([os.path.join(out, "jefe maestro.png")]) if os.path.exists(
        os.path.join(out, "jefe maestro.png")) else []
    if not refimg:
        import shutil
        shutil.copy(ref, os.path.join(out, "jefe maestro.png"))
        refimg = ctrl.import_now([os.path.join(out, "jefe maestro.png")])
    res = understand(snapshot(ctrl), glossary_text(), lambda *_a: None, lambda: False, None, deep=True)
    ctrl.understanding = res
    panel.refresh_known()
    i = next(i for i in range(panel.known.count()) if panel.known.itemData(i) == "Jefe Maestro")
    panel.known.setCurrentIndex(i)
    panel._known_selected(i)
    wait(app, panel)
    assert panel.results and any(r.media_id == halo for r in panel.results)
    print(f"✓ «Lo que conoce la IA» → Jefe Maestro: {len(panel.results)} apariciones")
    win.analyzer.shutdown()
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
