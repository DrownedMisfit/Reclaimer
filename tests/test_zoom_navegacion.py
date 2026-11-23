"""
🔍 PRUEBA de la fase 8 de la línea de tiempo: zoom y navegación.
  · barra resumen de todo el video: clic = ver ese momento; arrastrar el recuadro = recorrerlo; pintar con ~1500
    clips cuesta poco (el proyecto se dibuja una vez);
  · deslizador de zoom (y al revés: − / + lo mueven), «Detalle» (10 s alrededor del cabezal; otra vez = el de antes);
  · «/» reproduce 2 s antes y después del cabezal y vuelve a dejarlo donde estaba; Mayús+S = oír al arrastrar;
  · los atajos nuevos no chocan con ninguno.
Sin ventanas visibles (offscreen), datos aislados. Ejecutar:  .venv/Scripts/python.exe tests/test_zoom_navegacion.py <c>
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
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None


def _vigilante(segundos: float = 420.0):
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


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "zoom_navegacion")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
    from PySide6.QtGui import QAction, QKeySequence, QMouseEvent
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    if not os.path.exists(vid):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                        "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                        "-shortest", vid], check=True)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    pump(app, 0.5)
    ctrl, tl, rs = win.ctrl, win.timeline, win.resumen
    (mid,) = ctrl.import_now([vid])
    t0 = time.time()
    while ctrl.analyzing and time.time() - t0 < 60:
        pump(app, 0.1)
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    n = 1500
    ctrl.insert_ranges([{"media_id": mid, "start": i * 1.2, "duration": 1.0, "source_in": (i % 18) * 1.0}
                        for i in range(n)], v1.id, "muchos")
    pump(app, 0.6)
    tl.fit()
    pump(app, 0.3)
    dur = ctrl.project.duration()
    assert rs.isVisible(), "la barra resumen, a la vista de entrada"

    # ---------------------------------------------------------------- 1) barra resumen
    t_a = time.perf_counter()
    rs.rehacer()
    t_rehacer = (time.perf_counter() - t_a) * 1000
    t_a = time.perf_counter()
    for _ in range(10):
        rs.repaint()
    t_pinta = (time.perf_counter() - t_a) * 100
    print(f"barra resumen con {len(ctrl.project.clips)} clips: dibujar el proyecto {t_rehacer:.0f} ms · "
          f"pintar {t_pinta:.2f} ms")
    assert t_rehacer < 15 and t_pinta < 8, (t_rehacer, t_pinta)     # (por píxel y un color por tipo de clip)
    tl.detalle()                                     # (de cerca: el recuadro es pequeño)
    pump(app, 0.1)

    def clic(w, x, y=None, tipo=QEvent.MouseButtonPress):
        y = w.height() / 2 if y is None else y
        ev = QMouseEvent(tipo, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                         Qt.LeftButton if tipo != QEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)
    objetivo = dur * 0.6
    clic(rs, rs.x_de(objetivo))
    clic(rs, rs.x_de(objetivo), tipo=QEvent.MouseButtonRelease)
    centro = tl.scroll + tl.segundos_visibles() / 2
    assert abs(centro - objetivo) < 1.0, (centro, objetivo)
    r = rs.recuadro()
    x_med = r.center().x()
    antes = tl.scroll
    clic(rs, x_med)
    clic(rs, x_med + 40, tipo=QEvent.MouseMove)
    clic(rs, x_med + 40, tipo=QEvent.MouseButtonRelease)
    esperado = antes + 40 / rs._ancho() * rs._dur
    assert abs(tl.scroll - esperado) < 0.5, (tl.scroll, esperado)
    rs.grab().save(os.path.join(out, "resumen.png"))
    print("✓ barra resumen: clic = ver ese momento; arrastrar el recuadro = recorrer")

    # ---------------------------------------------------------------- 2) deslizador y «Detalle»
    tl.fit()
    pump(app, 0.1)
    sl = win.zoom_slider
    v0 = sl.value()
    pps0 = tl.pps
    sl.setValue(min(1000, v0 + 300))
    assert tl.pps > pps0 * 2, (tl.pps, pps0)
    tl.zoom(1 / 1.5)
    assert sl.value() < v0 + 300, "− / + mueven el deslizador"
    tl.fit()
    tl.set_playhead(100.0)
    vista0 = (tl.pps, tl.scroll)
    assert tl.detalle() is True
    assert abs(tl.segundos_visibles() - 10.0) < 0.05 and tl.scroll <= 100.0 <= tl.scroll + 10.0
    assert tl.detalle() is False and (tl.pps, tl.scroll) == vista0, "otra vez = el zoom de antes"
    win.btn_detalle.click()
    assert abs(tl.segundos_visibles() - 10.0) < 0.05
    win.btn_detalle.click()
    tl.detalle()                                         # «Detalle» vuelve bien aunque el panel cambie de ancho entre medias
    win.resize(1300, 950)
    pump(app, 0.3)
    assert tl.detalle() is False and abs(tl.pps - vista0[0]) < 1e-9, "vuelve al zoom de antes"
    win.resize(1600, 950)
    pump(app, 0.3)
    print("✓ deslizador de zoom (en los dos sentidos) y «Detalle»")

    # ---------------------------------------------------------------- 3) «/» y Mayús+S
    acts = {a.text(): a for a in win.findChildren(QAction)}
    alrededor = acts["Reproducir alrededor del cabezal"]
    scrub = acts["🔊 Oír al arrastrar el cabezal"]
    eng = win.engine
    eng.seek(50.0)
    tl.set_playhead(50.0)
    pump(app, 0.1)
    alrededor.trigger()
    assert abs((eng._stop_at or 0) - 52.0) < 0.05, eng._stop_at
    eng.pause()                                      # (como si acabara: el cabezal vuelve a donde estaba)
    pump(app, 0.2)
    assert abs(eng.time - 50.0) < 0.05, eng.time
    alrededor.trigger()                              # «/» dos veces seguidas: el mismo sitio, no donde iba sonando
    eng.time = 51.3
    alrededor.trigger()
    assert abs((eng._stop_at or 0) - 52.0) < 0.05, eng._stop_at
    eng.pause()
    pump(app, 0.2)
    assert abs(eng.time - 50.0) < 0.05, eng.time
    # la barra resumen: sin clips, escondida (sin franjas vacías); el cabezal se repinta solo
    rs._pintar_cabezal()
    assert rs._x_cabezal is not None and abs(rs._x_cabezal - rs.x_de(tl.playhead)) < 1.0
    assert abs(rs._ancho() - (tl.width() - tl.HEADER_W - 2)) < 1.0, "el mismo ancho que la línea de tiempo"
    st = QSettings("EditorIA", "EditorIA")
    antes_scrub = str(st.value("reproduccion/oir_al_arrastrar", "true"))
    scrub.trigger()
    assert str(st.value("reproduccion/oir_al_arrastrar")) != antes_scrub
    scrub.trigger()
    todos = [a for a in win.findChildren(QAction) if not a.shortcut().isEmpty()]
    for k in ("/", "Shift+S"):
        con = [a.text() for a in todos if a.shortcut() == QKeySequence(k)]
        assert len(con) == 1, (k, con)
    print("✓ «/» reproduce alrededor y deja el cabezal; Mayús+S oír al arrastrar; sin choques de atajos")
    guardados = dict(ctrl.project.clips)
    ctrl.project.clips.clear()
    ctrl._bump_rev()
    ctrl.project_changed.emit()
    pump(app, 0.5)
    assert not rs.isVisible(), "sin clips, la barra resumen se esconde"
    ctrl.project.clips.update(guardados)
    ctrl._bump_rev()
    ctrl.project_changed.emit()
    pump(app, 0.5)
    assert rs.isVisible(), "con clips, otra vez a la vista"
    print("✓ «/» dos veces, «Detalle» con otro ancho y la barra resumen escondida sin clips")
    print("TODO OK")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)


if __name__ == "__main__":
    main()
