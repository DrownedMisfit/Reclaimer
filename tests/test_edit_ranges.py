"""
Prueba de ✂ elegir a mano los tramos de un video para el edit musical y de 🗑 Vaciar la línea de tiempo:
  · el elegidor de planos solo saca planos de los tramos elegidos (también sin análisis de movimiento);
  · la ventana de tramos: Entrada / Salida / Añadir (los que se tocan se juntan), quitar, usar todo;
  · los tramos se guardan con el video y llegan al motor del edit (y a Remix / Mix por las opciones);
  · 🗑 Vaciar: quita clips, textos y marcadores (lo bloqueado se queda); Ctrl+Z lo devuelve.
Ejecutar:  .venv/Scripts/python.exe tests/test_edit_ranges.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.ai import edit_maker as E
    STEP = E.STEP
    n = int(60 / STEP)
    prof = {"motion": list(np.ones(n)), "bright": list(np.ones(n)), "cut": list(np.zeros(n))}
    rs = [(10.0, 14.0), (40.0, 44.0)]
    pk = E._Picker([{"media_id": "m", "kind": "video", "duration": 60.0, "profile": prof, "only": rs}], seed=5)
    for _ in range(12):
        r = pk.pick(1.5, 0.5, "main")
        a, b = r["source_in"], r["source_in"] + 1.5
        assert any(ra - 1e-6 <= a and b <= rb + 1e-6 for ra, rb in rs), r
    pk2 = E._Picker([{"media_id": "m", "kind": "video", "duration": 60.0, "profile": None, "only": rs}], seed=5)
    for _ in range(8):
        r = pk2.pick(1.5, 0.5, "main")
        assert any(ra - 1e-6 <= r["source_in"] and r["source_in"] + 1.5 <= rb + 1e-6 for ra, rb in rs), r
    print("✓ los planos salen SOLO de los tramos elegidos (con y sin análisis de movimiento)")

    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.edit_dialog import EditDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.range_picker import RangePicker
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "partida.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=30",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        p = ctrl.project
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        m = p.media[mid]
        dlg = RangePicker(m, [], win)
        dlg.show()
        pump(app, 0.3)
        assert dlg.screen.pixmap() is not None and not dlg.screen.pixmap().isNull(), "se ve la imagen (antes: negro)"
        assert dlg.b_mark.text().startswith("[ Entrada")
        dlg.seek_to(5.0)
        dlg.b_mark.click()                                   # entrada
        assert dlg.b_mark.text().startswith("Salida") and dlg.bar.mark_in == 5.0
        dlg.seek_to(9.0)
        dlg.b_mark.click()                                   # salida: el tramo se añade solo
        assert dlg.ranges() == [[5.0, 9.0]] and dlg.b_mark.text().startswith("[ Entrada"), dlg.ranges()
        assert abs(dlg.t - 9.0) < 0.01, "sigue desde el final del tramo"
        dlg.seek_to(8.0)
        dlg.mark()
        dlg.seek_to(12.0)
        dlg.mark()                                           # 8–12 encima de 5–9: solo se añade 9–12
        assert dlg.ranges() == [[5.0, 12.0]], dlg.ranges()
        assert "ya estaban elegidos" in dlg.hint.text(), dlg.hint.text()
        dlg.seek_to(6.0)
        dlg.mark()
        dlg.seek_to(10.0)
        dlg.mark()
        assert dlg.ranges() == [[5.0, 12.0]] and "ya lo tenías" in dlg.hint.text(), dlg.hint.text()
        dlg.seek_to(25.0)
        dlg.mark()
        dlg.seek_to(20.0)
        dlg.mark()                                           # salida antes que la entrada: también vale
        assert dlg.ranges() == [[5.0, 12.0], [20.0, 25.0]], dlg.ranges()
        dlg.list.setCurrentRow(1)
        dlg.remove_selected()
        assert dlg.ranges() == [[5.0, 12.0]]
        print("✓ un solo botón [ Entrada → Salida ] (el tramo se añade solo); lo ya elegido no se duplica")
        # ↔ Arrastrar: arrastrar sobre la barra = un tramo, y «➕ Añadir tramo»
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        dlg.b_keep.setChecked(False)                         # sin «Continuar»: se apaga solo al añadir
        dlg.b_drag.setChecked(True)
        dlg.bar.sel = [24.0, 26.0]
        dlg._sel_changed()
        dlg.b_add.click()
        assert not dlg.b_drag.isChecked() and not dlg.bar.drag_mode and "Tramo añadido" in dlg.hint.text(), \
            dlg.hint.text()
        dlg.list.setCurrentRow(1)
        dlg.remove_selected()
        assert dlg.ranges() == [[5.0, 12.0]], dlg.ranges()
        dlg.b_keep.setChecked(True)                          # con «Continuar»: sigue activo (y se recuerda)
        from PySide6.QtCore import QSettings as _QS
        assert _QS("EditorIA", "EditorIA").value("tramos/seguir_arrastrando", False, type=bool)
        print("✓ tras «➕ Añadir tramo», Arrastrar se apaga solo; con «Continuar» marcado sigue activo")
        dlg.b_drag.setChecked(True)
        assert not dlg.b_add.isEnabled()
        bar = dlg.bar
        x_of = lambda t: int(round(6 + (bar.width() - 12) * t / bar.duration))
        y = bar.height() // 2
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(13.0), y))
        for t_ in (14.0, 15.0, 16.0):
            QTest.mouseMove(bar, QPoint(x_of(t_), y))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(16.0), y))
        pump(app, 0.1)
        assert dlg.b_add.isEnabled() and bar.sel and abs(bar.sel[0] - 13.0) < 0.3 and abs(bar.sel[1] - 16.0) < 0.3, bar.sel
        assert dlg.ranges() == [[5.0, 12.0]], "aún no se añade: lo añades tú"
        # soltado el tramo, pinchar SOBRE el cabezal rojo (al final del verde) y arrastrar = seguir, no empezar otro
        assert abs(bar.pos - bar.sel[1]) < 0.3, (bar.pos, bar.sel)
        xr = int(round(bar._x(bar.pos)))
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, QPoint(xr, y))
        QTest.mouseMove(bar, QPoint(x_of(18.0), y))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(18.0), y))
        assert abs(bar.sel[0] - 13.0) < 0.3 and abs(bar.sel[1] - 18.0) < 0.3, ("sigue desde el cabezal", bar.sel)
        xr = int(round(bar._x(bar.pos)))
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, QPoint(xr, y))   # y otra vez, hacia atrás (acortar)
        QTest.mouseMove(bar, QPoint(x_of(16.0), y))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(16.0), y))
        assert abs(bar.sel[0] - 13.0) < 0.3 and abs(bar.sel[1] - 16.0) < 0.3, bar.sel
        print("✓ pinchar sobre el cabezal rojo tras soltar el tramo verde lo sigue (alargar o acortar), no lo cancela")
        dlg.b_add.click()
        rs = dlg.ranges()
        assert len(rs) == 2 and abs(rs[1][0] - 13.0) < 0.3 and abs(rs[1][1] - 16.0) < 0.3, rs
        assert not dlg.b_add.isEnabled() and bar.sel is None and dlg.b_drag.isChecked(), "con «Continuar», sigue"
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(15.0), y))   # encima de lo elegido
        QTest.mouseMove(bar, QPoint(x_of(18.0), y))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, QPoint(x_of(18.0), y))
        dlg.b_add.click()
        rs = dlg.ranges()
        assert len(rs) == 2 and abs(rs[1][1] - 18.0) < 0.3 and "ya estaban elegidos" in dlg.hint.text(), (rs, dlg.hint.text())
        print("✓ ↔ Arrastrar: arrastras sobre la barra de dónde a dónde y «➕ Añadir tramo» (sin duplicar)")
        # con «Arrastrar», −1 s / +1 s (y ← →, y un fotograma) también arrastran, como el ratón
        dlg.seek_to(20.0)
        pump(app, 0.1)
        assert bar.sel is None
        plus, minus = dlg.step_btns[3], dlg.step_btns[0]
        for _ in range(3):
            plus.click()
        assert bar.sel and abs(bar.sel[0] - 20.0) < 1e-6 and abs(bar.sel[1] - 23.0) < 1e-6, bar.sel
        minus.click()
        assert abs(bar.sel[0] - 20.0) < 1e-6 and abs(bar.sel[1] - 22.0) < 1e-6, bar.sel
        dlg.step_btns[2].click()                       # un fotograma más
        fr = 1.0 / float(getattr(m, "fps", 0) or 30.0)
        assert abs(bar.sel[1] - (22.0 + fr)) < 1e-6, bar.sel
        QTest.keyClick(dlg, Qt.Key_Right)
        assert abs(bar.sel[1] - (23.0 + fr)) < 1e-6 and dlg.b_add.isEnabled(), bar.sel
        assert "→" in dlg.sel_label.text()
        dlg.b_add.click()
        rs = dlg.ranges()
        assert any(abs(a - 20.0) < 1e-3 and abs(b - (23.0 + fr)) < 1e-3 for a, b in rs), rs
        for _ in range(2):                             # hacia atrás desde un punto nuevo: el tramo crece a la izquierda
            minus.click()
        assert abs(bar.sel[0] - (21.0 + fr)) < 1e-6 and abs(bar.sel[1] - (23.0 + fr)) < 1e-6, bar.sel
        print("✓ con «↔ Arrastrar», −1 s / +1 s, un fotograma y ← → también arrastran el tramo verde (como el ratón)")
        dlg.b_drag.setChecked(False)
        dlg.bar.ranges = [[5.0, 12.0]]
        dlg._refresh()
        # Precisión: −1 s / +1 s / un fotograma
        dlg.seek_to(10.0)
        dlg.step_btns[3].click()
        assert abs(dlg.t - 11.0) < 1e-6
        dlg.step_btns[0].click()
        dlg.step_btns[2].click()                             # un fotograma adelante
        fr = 1.0 / float(m.fps or 30.0)
        assert abs(dlg.t - (10.0 + fr)) < 1e-6, dlg.t
        assert "10.0" in dlg.time.text(), dlg.time.text()      # con centésimas
        print(f"✓ precisión: −1 s / +1 s y de fotograma en fotograma ({fr:.3f} s); el tiempo con centésimas")

        # 🔍 Acercar / alejar la barra; a los lados, entre qué tiempos estás
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        from editoria.ui.common import fmt_time
        from editoria.ui.range_picker import MIN_SPAN

        def wheel(w, x, dy, mods=Qt.NoModifier):
            p_ = QPointF(x, w.height() / 2)
            app.sendEvent(w, QWheelEvent(p_, QPointF(w.mapToGlobal(p_.toPoint())), QPoint(0, 0), QPoint(0, dy),
                                         Qt.NoButton, mods, Qt.NoScrollPhase, False))
        D = bar.duration
        assert (dlg.view_from.text(), dlg.view_to.text()) == ("00:00", fmt_time(D, False)), dlg.view_to.text()
        assert not dlg.b_zoom_out.isEnabled() and dlg.b_zoom_in.isEnabled()
        g = dlg.zoom_gauge                                   # 🔍 la lupa de debajo: sin acercar, «Todo» y vacía
        assert g.text == "Todo" and g.level == 0.0, (g.text, g.level)
        dlg.seek_to(10.0)
        x10 = bar._x(10.0)
        dlg.b_zoom_in.click()                                # acercar: el cabezal se queda en su sitio
        assert abs((bar.v1 - bar.v0) - D / 2) < 1e-6 and abs(bar._x(10.0) - x10) < 1.0, (bar.v0, bar.v1)
        assert g.text.startswith("×2") and 0 < g.level < 1, (g.text, g.level)
        lvl2 = g.level
        assert dlg.view_from.text() == fmt_time(bar.v0, False) and dlg.view_to.text() == fmt_time(bar.v1, False)
        assert dlg.b_zoom_out.isEnabled() and bar.v0 > 0.5, bar.v0
        span, x12 = bar.v1 - bar.v0, bar._x(12.0)
        wheel(bar, x12, 120, Qt.ControlModifier)             # Ctrl+rueda sobre la barra: donde está el ratón
        assert abs((bar.v1 - bar.v0) - span / 1.25) < 1e-6 and abs(bar._x(12.0) - x12) < 1.0, (bar.v0, bar.v1)
        assert g.level > lvl2 and g.text.startswith("×2.5"), (g.text, g.level)   # más cerca: la lupa se llena más
        print(f"✓ 🔍 la lupa de debajo dice cuánto está acercada: «Todo» → «×2.0 · …» → «{g.text}»")
        v0 = bar.v0
        wheel(bar, x12, -120)                                # rueda sola = moverse por el video
        assert bar.v0 > v0 and abs(dlg.t - 10.0) < 1e-6, "se mueve la vista, no el cabezal"
        t_click = (bar.v0 + bar.v1) / 2
        QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, QPoint(int(round(bar._x(t_click))), y))
        assert abs(dlg.t - t_click) < 0.1, (dlg.t, t_click)  # clic con la barra acercada = ese momento
        dlg.seek_to(D - 1.0)                                 # el cabezal sale de la vista: la vista lo sigue
        assert bar.v0 <= D - 1.0 <= bar.v1 and dlg.view_to.text() == fmt_time(bar.v1, False), (bar.v0, bar.v1)
        dlg.grab().save(os.path.join(out, "tramos_acercada.png"))
        for _ in range(12):
            dlg.b_zoom_in.click()
        assert abs((bar.v1 - bar.v0) - MIN_SPAN) < 1e-6 and not dlg.b_zoom_in.isEnabled()
        for _ in range(20):                                  # Ctrl+rueda encima del video también vale (la rueda
            wheel(dlg, dlg.width() / 2, -120, Qt.ControlModifier)   # real sube del video a la ventana; la simulada no)
        assert (bar.v0, bar.v1) == (0.0, D) and not bar.zoomed() and not dlg.b_zoom_out.isEnabled()
        assert (dlg.view_from.text(), dlg.view_to.text()) == ("00:00", fmt_time(D, False))
        print("✓ 🔍 acercar / alejar (botones y Ctrl+rueda), a los lados entre qué tiempos estás; la rueda sola se "
              "mueve, el clic va al momento justo y la vista sigue al cabezal")
        # ⏱ la regla: números entre medias, con su unidad según lo acercada que esté
        from editoria.ui.range_picker import ruler_label
        assert [ruler_label(*a) for a in ((45, 5), (150, 30), (12.5, 0.5), (600, 60), (3900, 600), (7200, 3600),
                                          (3725, 5))] == ["45s", "2m 30s", "12.5s", "10m", "1h 05m", "2h",
                                                          "1h 02m 05s"]
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(bar._rfont)

        def no_overlap_on(b_, marks):
            xs = [(b_._x(t), fm.horizontalAdvance(lb)) for t, lb in marks]
            return all(x1 - x0 >= w0 + 6 for (x0, w0), (x1, _w) in zip(xs, xs[1:]))

        def no_overlap(marks):
            return no_overlap_on(bar, marks)
        step, _minor, marks = bar.ticks()                    # entera (30 s): cada pocos segundos, «5s», «10s»…
        assert 3 <= len(marks) <= 60 and marks[0] == (0.0, "0s") and no_overlap(marks), (step, marks)
        dlg.seek_to(12.0)
        for _ in range(12):
            dlg.b_zoom_in.click()                            # 3 s: décimas de segundo
        step2, _m, marks2 = bar.ticks()
        assert step2 < 1 and all(lb.endswith("s") and "." in lb for _t, lb in marks2) and no_overlap(marks2), marks2
        long_bar = type(bar)(3 * 3600 + 120.0)               # un video de 3 h, entero: horas
        long_bar.resize(800, long_bar.height())
        s3, _m, m3 = long_bar.ticks()
        assert s3 >= 600 and any("h " in lb for _t, lb in m3) and no_overlap_on(long_bar, m3), m3
        long_bar.zoom(40, 3600 + 30)                          # 4,5 min alrededor de la hora: «1h 01m»…
        s4, _m, m4 = long_bar.ticks()
        assert 15 <= s4 <= 60 and any(lb.startswith("1h ") and lb.endswith("s") for _t, lb in m4) \
            and no_overlap_on(long_bar, m4), (s4, m4)
        dlg.grab().save(os.path.join(out, "tramos_regla.png"))
        for _ in range(20):
            dlg.b_zoom_out.click()
        print(f"✓ ⏱ regla entre el principio y el final: {[lb for _t, lb in marks][:4]}… · acercada "
              f"{[lb for _t, lb in marks2][:3]}… · 3 h {[lb for _t, lb in m3][:3]}… (sin pisarse)")

        dlg.seek_to(2.0)
        dlg.toggle()                                         # ▶
        t_play = time.time()
        pump(app, 1.5)
        assert dlg.t > 2.6, ("reproduce y el tiempo avanza", dlg.t)
        dlg.mark()
        pump(app, 0.6)
        dlg.mark()                                           # marcar mientras se reproduce
        assert any(a_ < 3.5 and b_ > a_ for a_, b_ in dlg.ranges()), dlg.ranges()
        t0 = time.time()
        dlg.reject()
        assert time.time() - t0 < 3.0, "cerrar no se queda colgado"
        print(f"✓ reproduce con imagen (avanzó {dlg.t - 2.0:.1f} s en {time.time() - t_play:.1f} s), "
              "se marca reproduciendo y cerrar es al momento")

        # 🎬 Escenas: un video con 4 escenas (rojo 3 s, azul 3 s, verde 4 s, amarillo 4 s)
        from editoria.core.model import MediaItem
        sv = os.path.join(out, "escenas.mp4")
        cols = (("red", 3), ("blue", 3), ("green", 4), ("yellow", 4))
        args_ = [M.ffmpeg(), "-nostdin", "-v", "error", "-y"]
        for c_, d_ in cols:
            args_ += ["-f", "lavfi", "-i", f"color=c={c_}:s=320x180:r=30:d={d_}"]
        args_ += ["-filter_complex", "".join(f"[{k}:v]" for k in range(4)) + "concat=n=4:v=1:a=0[v]", "-map", "[v]",
                  "-pix_fmt", "yuv420p", sv]
        subprocess.run(args_, check=True)
        sm = MediaItem("esc", sv, "video", "escenas.mp4", duration=14.0, width=320, height=180, fps=30.0, probed=True)
        d2 = RangePicker(sm, [], win)
        d2.show()
        t0 = time.time()
        while not d2.bar.cuts and time.time() - t0 < 30:
            pump(app, 0.1)
        assert [round(c) for c in d2.bar.cuts] == [3, 6, 10], d2.bar.cuts
        assert d2.b_scenes.isEnabled() and "(4)" in d2.b_scenes.text(), d2.b_scenes.text()
        d2.b_scenes.setChecked(True)
        bar2 = d2.bar
        xo = lambda t: int(round(6 + (bar2.width() - 12) * t / bar2.duration))
        y2 = bar2.height() // 2
        QTest.mouseClick(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(4.5), y2))     # la escena azul
        QTest.mouseClick(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(12.0), y2))    # y la amarilla
        assert bar2.scene_sel == {1, 3} and "2 escenas" in d2.b_add.text(), (bar2.scene_sel, d2.b_add.text())
        QTest.mouseClick(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(12.0), y2))    # otra vez = desmarcar
        QTest.mouseClick(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(12.0), y2))
        d2.b_add.click()
        rs = d2.ranges()
        assert len(rs) == 2 and abs(rs[0][0] - 3) < 0.15 and abs(rs[0][1] - 6) < 0.15 and abs(rs[1][0] - 10) < 0.15 \
            and abs(rs[1][1] - 14) < 0.15, rs
        print("✓ 🎬 escenas detectadas solas (3 cortes); clic = marcar varias y «➕ Añadir 2 escenas» de una vez")
        d2.b_drag.setChecked(True)                                # arrastrar se pega al corte de escena cercano
        assert not d2.b_scenes.isChecked()
        QTest.mousePress(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(0.5), y2))
        QTest.mouseMove(bar2, QPoint(xo(3.0) + 3, y2))
        QTest.mouseRelease(bar2, Qt.LeftButton, Qt.NoModifier, QPoint(xo(3.0) + 3, y2))
        assert bar2.sel and abs(bar2.sel[1] - bar2.cuts[0]) < 1e-6, (bar2.sel, bar2.cuts)
        d2.b_add.click()
        d2.list.selectAll()                                       # quitar VARIOS a la vez
        d2.remove_selected()
        assert d2.ranges() == []
        print("✓ arrastrar se pega a los cambios de escena; en la lista se quitan varios a la vez")
        d2.reject()

        # ⬛ Imágenes negras: rayitas amarillas debajo de la barra (también un fotograma suelto; el gris oscuro no)
        bv = os.path.join(out, "negros.mp4")
        parts = (("testsrc2", 2), ("black", 1), ("testsrc2", 2), ("black", 0.0333), ("testsrc2", 2), ("0x404040", 1))
        args_ = [M.ffmpeg(), "-nostdin", "-v", "error", "-y"]
        for c_, d_ in parts:
            args_ += ["-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={d_}" if c_ == "testsrc2"
                      else f"color=c={c_}:s=320x180:r=30:d={d_}"]
        args_ += ["-filter_complex", "".join(f"[{k}:v]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]",
                  "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", bv]
        subprocess.run(args_, check=True)
        bm = MediaItem("neg", bv, "video", "negros.mp4", duration=8.03, width=320, height=180, fps=30.0, probed=True)
        d3 = RangePicker(bm, [], win)
        d3.show()
        t0 = time.time()
        while "sitio" not in d3.black_info.text() and time.time() - t0 < 60:
            pump(app, 0.1)
        bl = d3.bar.blacks
        assert len(bl) == 2 and abs(bl[0][0] - 2) < 0.05 and abs(bl[0][1] - 3) < 0.05 and abs(bl[1][0] - 5) < 0.05 \
            and bl[1][1] - bl[1][0] < 0.2, bl
        assert "Negro en 2 sitios" in d3.black_info.text(), d3.black_info.text()
        d3.b_drag.setChecked(True)                           # arrastrar de 1 a 7 s: el negro (amarillo) no entra
        d3.bar.sel = [1.0, 7.0]
        d3._sel_changed()
        assert "en negro: no entran" in d3.sel_label.text(), d3.sel_label.text()
        d3.add_dragged()
        rs = d3.ranges()
        assert len(rs) == 3 and abs(rs[0][0] - 1) < 1e-3 and abs(rs[0][1] - bl[0][0]) < 1e-3 \
            and abs(rs[1][0] - bl[0][1]) < 1e-3 and abs(rs[1][1] - bl[1][0]) < 1e-3 \
            and abs(rs[2][0] - bl[1][1]) < 1e-3 and abs(rs[2][1] - 7) < 1e-3, (rs, bl)   # ni el fotograma suelto
        assert "en negro" in d3.hint.text(), d3.hint.text()
        d3.bar.sel = [2.2, 2.8]                              # todo negro: no se añade nada
        d3.add_dragged()
        assert len(d3.ranges()) == 3 and "solo hay negro" in d3.hint.text(), d3.hint.text()
        d3.seek_to(2.2)                                      # con Entrada / Salida sí se puede coger el negro
        d3.mark()
        d3.seek_to(2.8)
        d3.mark()
        assert any(a_ <= 2.2 + 1e-3 and b_ >= 2.8 - 1e-3 for a_, b_ in d3.ranges()), d3.ranges()
        d3.grab().save(os.path.join(out, "tramos_negros.png"))
        d3.reject()
        from editoria.core import black_frames
        t0 = time.time()
        assert black_frames.detect(bv, 8.03) == bl and time.time() - t0 < 0.5, "la segunda vez, al momento (se guarda)"
        print("✓ ⬛ imágenes negras: rayitas amarillas debajo de la barra (un segundo en negro y un fotograma suelto; "
              "el gris oscuro no cuenta), y se guardan")

        # «✓ Listo» de verdad, abierta desde la ventana del edit (antes no pasaba nada)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication as _QA
        ed0 = EditDialog(ctrl, win)
        it0 = next(ed0.clips.item(i) for i in range(ed0.clips.count()) if ed0.clips.item(i).data(Qt.UserRole) == mid)

        def drive():
            d = next(w for w in _QA.topLevelWidgets() if isinstance(w, RangePicker) and w.isVisible())
            d.seek_to(3.0)
            d.mark()
            d.seek_to(7.0)
            d.mark()
            d.b_ok.click()
        QTimer.singleShot(600, drive)
        t0 = time.time()
        ed0.pick_ranges(it0)
        assert time.time() - t0 < 8, "Listo cierra"
        assert p.media[mid].edit_ranges == [[3.0, 7.0]], p.media[mid].edit_ranges
        assert "1 tramo" in ed0.status.text(), ed0.status.text()
        ed0.close()
        print("✓ «✓ Listo» guarda los tramos (desde la ventana del edit)")

        # 🎵 Un video de la lista «Clips» como canción (arrastrarlo a «Canción» / clic derecho → «Usar como canción»)
        mv = os.path.join(out, "videoclip.mp4")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8",
                        "-f", "lavfi", "-i", "sine=frequency=330:duration=8", "-c:v", "libx264", "-preset",
                        "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", mv], check=True)
        (vid_song,) = ctrl.import_now([mv])
        while ctrl.analyzing:
            pump(app, 0.1)
        ed1 = EditDialog(ctrl, win)
        ed1.show()
        pump(app, 0.2)
        n_media = len(p.media)
        it1 = next(ed1.clips.item(i) for i in range(ed1.clips.count()) if ed1.clips.item(i).data(Qt.UserRole) == vid_song)
        assert ed1.clips.dragEnabled() and ed1.song.acceptDrops()
        ed1.use_clip_as_song(vid_song)
        t0 = time.time()
        while (ed1.song.currentData() is None or p.media[ed1.song.currentData()].kind != "audio") and time.time() - t0 < 30:
            pump(app, 0.1)
        song_id = ed1.song.currentData()
        assert song_id and p.media[song_id].kind == "audio" and "videoclip" in p.media[song_id].name, ed1.song.currentText()
        it1 = next(ed1.clips.item(i) for i in range(ed1.clips.count()) if ed1.clips.item(i).data(Qt.UserRole) == vid_song)
        assert it1.checkState() == Qt.Unchecked, "el video de la canción deja de ser clip (se puede volver a marcar)"
        assert len(p.media) == n_media + 1
        ed1.song.setCurrentIndex(-1)
        ed1.use_clip_as_song(vid_song)                       # otra vez: se reutiliza lo ya sacado
        assert ed1.song.currentData() == song_id and len(p.media) == n_media + 1 and "ya estaba" in ed1.status.text()
        ed1.close()
        print("✓ 🎵 un video de «Clips» como canción: se saca su sonido, queda elegido y se desmarca de los clips; "
              "la segunda vez se reutiliza")

        ed = EditDialog(ctrl, win)
        ctrl.set_media_props([mid], edit_ranges=[[5.0, 12.0]])
        ed._fill()
        texts = [ed.clips.item(i).text() for i in range(ed.clips.count())]
        assert any("✂ 1 tramo" in t for t in texts), texts
        captured = {}
        from editoria.ai import edit_engine

        def fake_plan(song, sources, **kw):
            captured["sources"] = [dict(s) for s in sources]
            raise RuntimeError("parar aquí")
        old = edit_engine.plan_v2
        edit_engine.plan_v2 = fake_plan
        try:
            song = os.path.join(out, "cancion.wav")
            subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=f=220:d=20", song], check=True)
            try:
                E.make_edit(song, "s", [{"media_id": mid, "path": vid, "kind": "video", "duration": 30.0,
                                         "name": "partida"}], {"style": "phonk", "ranges": {mid: [[5.0, 12.0]]}})
            except RuntimeError:
                pass
        finally:
            edit_engine.plan_v2 = old
        assert captured["sources"][0].get("only") == [[5.0, 12.0]], captured
        print("✓ los tramos se guardan con el video, se ven en la lista y llegan al motor del edit")
        ed.close()

        # 🗑 Vaciar
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        made = ctrl.add_media([mid], v1.id, 0.0)
        ctrl.add_media([mid], v1.id, 30.0)
        ctrl.add_marker(3.0)
        ctrl.set_clip_props([made[0]], "lock", locked=True)
        n_clips = len(p.clips)
        win.clear_timeline(ask=False)
        assert set(p.clips) == {made[0]} and not p.markers, (len(p.clips), p.markers)
        ctrl.undo_stack.undo()
        assert len(p.clips) == n_clips and p.markers
        print("✓ 🗑 Vaciar: fuera clips y marcadores (lo bloqueado se queda) y Ctrl+Z lo devuelve")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
        from editoria.ui.task_window import stop_all
        stop_all(6000)
    finally:
        for k, v in keep.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
        st.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
