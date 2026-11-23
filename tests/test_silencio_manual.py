"""
Prueba de los retoques a mano de «✂ Eliminar silencio» y de las franjas oscuras de la onda:
  1) con la ventana abierta, arrastrar en la línea de tiempo el borde de un corte (o sobre el audio) lo retoca en vivo;
     arriba sale qué parámetro lo explicaría («Después del final: 4 → 7 fotogramas»…); «✓ Cambiar este parámetro para
     todo» lo aplica; los retoques sobreviven al recalcular, se deshacen con Ctrl+Z (sin tocar el historial del
     proyecto), avisan si cortan dentro de una palabra y se respetan al pulsar «Eliminar». Un clic sin arrastrar sigue
     moviendo el cabezal y, sin la ventana, la línea de tiempo funciona como siempre.
  2) clic derecho sobre una franja oscura de la onda: se elige entera aunque cruce clips pegados y el menú ofrece
     «✂ Eliminar este silencio» (y «Eliminar todos los silencios marcados»); quita solo eso, un solo Ctrl+Z.
Sin ventanas visibles (offscreen) y sin sonido.
Ejecutar:  .venv/Scripts/python.exe tests/test_silencio_manual.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_RAIZ_AISLADA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ_AISLADA, "datos", "modelos"))
os.makedirs(os.path.join(_RAIZ_AISLADA, "_pruebas_tmp"), exist_ok=True)
import atexit as _atexit, shutil as _shutil, tempfile as _tempfile  # noqa: E401,E402
_DATOS_AISLADOS = _tempfile.mkdtemp(prefix="reclaimer_datos_", dir=os.path.join(_RAIZ_AISLADA, "_pruebas_tmp"))
_atexit.register(_shutil.rmtree, _DATOS_AISLADOS, True)
os.environ["LOCALAPPDATA"] = _DATOS_AISLADOS
os.environ["EDITORIA_DATOS"] = os.path.join(_DATOS_AISLADOS, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core import silence as S  # noqa: E402
from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO  # noqa: E402

FPS = 30.0


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def mouse(w, kind, x, y, button=Qt.LeftButton):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    held = Qt.NoButton if kind == "release" else (button if kind != "move" or button != Qt.NoButton else Qt.NoButton)
    ev = QMouseEvent(t, QPointF(x, y), w.mapToGlobal(QPointF(x, y)), Qt.NoButton if kind == "move" else button,
                     held, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def drag(app, tl, x0, x1, y):
    mouse(tl, "press", x0, y)
    steps = 6
    for k in range(1, steps + 1):
        mouse(tl, "move", x0 + (x1 - x0) * k / steps, y, Qt.LeftButton)
    pump(app, 0.02)


def near(a, b, tol=1.01 / FPS):
    return abs(a - b) <= tol


def core_tests():
    r = S.apply_retouches([(1.0, 2.0), (3.0, 4.0)], [("keep", 1.0, 1.5), ("cut", 2.0, 3.0)])
    assert r == [(1.5, 4.0)], r
    assert S.edge_retouch((1.0, 2.0), "start", 1.2) == ("keep", 1.0, 1.2)
    assert S.edge_retouch((1.0, 2.0), "end", 2.3) == ("cut", 2.0, 2.3)
    ch = S.classify([(1.0, 2.0)], "keep", 1.0, 1.1, FPS)
    assert ch["kind"] == "start" and ch["frames"] == 3, ch
    st = {"threshold_db": -26.8, "before": 2, "after": 4, "min_frames": 14, "mode": "volumen"}
    sg = S.suggest(ch, st)
    assert sg["key"] == "after" and sg["old"] == 4 and sg["new"] == 7, sg
    sg = S.suggest(S.classify([(1.0, 2.0)], "keep", 1.9, 2.0, FPS), st)
    assert sg["key"] == "before" and sg["new"] == 5, sg
    sg = S.suggest(S.classify([(1.0, 2.0)], "keep", 1.0, 2.0, FPS), st)
    assert sg["key"] == "min_frames" and sg["new"] == 30 + 2 + 4 + 1, sg
    sg = S.suggest(S.classify([(1.0, 2.0)], "cut", 5.0, 5.2, FPS), st)
    assert sg["key"] == "min_frames" and sg["new"] == 6 + 6, sg
    sg = S.suggest(S.classify([(1.0, 2.0)], "cut", 5.0, 6.0, FPS), st, level_db=-20.2)
    assert sg["key"] == "threshold_db" and sg["new"] == -19.5, sg
    assert S.suggest(S.classify([(1.0, 2.0)], "keep", 1.4, 1.6, FPS), st, level_db=-110.0) is None
    sg = S.suggest(S.classify([(1.0, 2.0)], "keep", 1.4, 1.6, FPS), st, level_db=-35.0)
    assert sg["key"] == "threshold_db" and sg["new"] == -35.5, sg
    sg = S.suggest({"kind": "start", "frames": 40}, st)
    assert sg["new"] == 30 and sg["clamped"], sg
    print("✓ núcleo: retoques encima de los cortes y la propuesta de parámetro para cada caso")


def dialog_tests(app, out):
    ff = media_tools.ffmpeg()
    voz = os.path.join(out, "voz.wav")
    # voz de 12 s con silencios: 2–3,5 (1,5 s), 6–6,3 (0,3 s) y 9–11 (2 s)
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:d=12", "-af",
                    "volume='if(between(t,2,3.5)+between(t,6,6.3)+between(t,9,11),0,1)':eval=frame", voz], check=True)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    c = win.ctrl
    p = c.project
    p.fps = FPS
    (am,) = c.import_now([voz])
    nar = [t for t in p.tracks if t.kind == TRACK_AUDIO][0]
    aid = c.add_media([am], nar.id, 0.0)[0]
    mid = p.clips[aid].media_id
    dur0 = p.duration()
    tl = win.timeline
    assert tl.sil_editor is None

    from editoria.ui.silence_dialog import SilenceDialog
    dlg = SilenceDialog(win, [aid])
    for cb in (dlg.words_cb, dlg.voice_model, dlg.learn_cb, dlg.clicks, dlg.sug_cb):
        cb.blockSignals(True)
        cb.setChecked(False)
        cb.blockSignals(False)
    dlg.mode.setCurrentIndex(dlg.mode.findData("volumen"))
    dlg.show()
    assert tl.sil_editor is dlg, "con la ventana abierta, la línea de tiempo acepta retoques"
    assert dlg.man_box.isVisibleTo(dlg) and dlg.sug_lbl.isVisibleTo(dlg) and dlg.sug_cb.isVisibleTo(dlg)
    assert "Retoque a mano" in dlg.sug_lbl.text()
    t0 = time.time()
    while not dlg._ready and time.time() - t0 < 30:
        pump(app, 0.05)
    dlg._set(S.PRESETS["Equilibrado (-26.8 dB · 2 / 4 · mín. 14)"])
    pump(app, 0.4)
    assert len(dlg.regions) == 2, dlg.regions
    (a1, b1), (a2, b2) = dlg.regions
    assert near(a1, 2 + 4 / FPS) and near(b1, 3.5 - 2 / FPS), dlg.regions

    tl.pps = 60.0
    tl.scroll = 0.0
    tl._ty_cache = None
    ia = next(i for i, t in enumerate(p.tracks) if t.id == nar.id)
    y = tl.track_y(ia) + tl.track_h(ia) / 2
    assert tl.track_h(ia) > 10
    hist = c.undo_stack.index()

    # --- cursor de redimensionar en el borde
    mouse(tl, "move", tl.x_for(a1), y, Qt.NoButton)
    assert tl.cursor().shape() == Qt.SizeHorCursor, "en el borde de un corte: cursor ↔"
    mouse(tl, "move", tl.x_for(a1) + 40, y, Qt.NoButton)
    assert tl.cursor().shape() != Qt.SizeHorCursor
    print("✓ cursor ↔ al pasar por el borde de una zona de corte")

    # --- arrastrar el borde de inicio 3 fotogramas hacia dentro: «Después del final: 4 → 7»
    drag(app, tl, tl.x_for(a1), tl.x_for(a1 + 3 / FPS), y)
    assert near(tl.preview_regions[0][0], a1 + 3 / FPS), ("en vivo", tl.preview_regions)
    txt = dlg.sug_lbl.text()
    assert "Después del final" in txt and "4 → 7" in txt and "fotogramas" in txt, txt
    assert tl._sil_tip and "Después del final: 4 → 7" in tl._sil_tip[2], tl._sil_tip
    win.grab().save(os.path.join(out, "arrastrando_borde.png"))
    mouse(tl, "release", tl.x_for(a1 + 3 / FPS), y)
    pump(app, 0.05)
    assert dlg._retouches and near(dlg.regions[0][0], a1 + 3 / FPS), dlg.regions
    assert int(dlg.ctl["after"][1].value()) == 4, "sin la casilla, el parámetro no cambia"
    assert "Después del final" in dlg.sug_lbl.text(), "la propuesta queda escrita arriba"
    assert c.undo_stack.index() == hist, "un retoque no toca el proyecto"
    print(f"✓ arrastrar el borde: en vivo y arriba «{dlg._sug_text(dlg._last_sug['sug'], [], rich=False)}»")

    # --- se conserva al recalcular por otro motivo
    dlg.ctl["min_frames"][1].setValue(15)
    pump(app, 0.4)
    assert near(dlg.regions[0][0], a1 + 3 / FPS) and len(dlg.regions) == 2, dlg.regions
    print("✓ el retoque se conserva al recalcular (otro control movido)")

    # --- Ctrl+Z en la línea de tiempo: quita el retoque, no deshace el proyecto
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    assert tl.event(ev) and ev.isAccepted(), "Ctrl+Z es de los retoques mientras haya"
    tl.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier))
    pump(app, 0.05)
    assert not dlg._retouches and near(dlg.regions[0][0], a1), dlg.regions
    assert c.undo_stack.index() == hist
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    tl.event(ev)
    assert not dlg.sil_can_undo(), "sin retoques, Ctrl+Z vuelve a ser el de siempre"
    print("✓ Ctrl+Z quita el retoque (el historial del proyecto, intacto)")

    # --- con «✓ Cambiar este parámetro para todo»: borde final 3 fotogramas hacia dentro → Antes del inicio 2 → 5
    dlg.sug_cb.setChecked(True)
    drag(app, tl, tl.x_for(b1), tl.x_for(b1 - 3 / FPS), y)
    assert "Antes del inicio" in dlg.sug_lbl.text() and "2 → 5" in dlg.sug_lbl.text(), dlg.sug_lbl.text()
    mouse(tl, "release", tl.x_for(b1 - 3 / FPS), y)
    pump(app, 0.4)
    assert int(dlg.ctl["before"][1].value()) == 5 and not dlg._retouches
    assert near(dlg.regions[0][1], b1 - 3 / FPS) and near(dlg.regions[1][1], b2 - 3 / FPS), dlg.regions
    assert "cambiado para todo" in dlg.sug_lbl.text()
    dlg.sil_undo()
    pump(app, 0.4)
    assert int(dlg.ctl["before"][1].value()) == 2 and near(dlg.regions[0][1], b1)
    dlg.sug_cb.setChecked(False)
    print("✓ con la casilla, el parámetro cambia para todos los cortes (y se deshace)")

    # --- marcar la casilla DESPUÉS de soltar: se aplica la última propuesta
    drag(app, tl, tl.x_for(a1), tl.x_for(a1 + 2 / FPS), y)
    mouse(tl, "release", tl.x_for(a1 + 2 / FPS), y)
    pump(app, 0.05)
    assert dlg._retouches
    dlg.sug_cb.setChecked(True)
    pump(app, 0.4)
    assert int(dlg.ctl["after"][1].value()) == 6 and not dlg._retouches, dlg._retouches
    assert near(dlg.regions[1][0], a2 + 2 / FPS), dlg.regions
    dlg.sil_undo()
    pump(app, 0.4)
    dlg.sug_cb.setChecked(False)
    assert int(dlg.ctl["after"][1].value()) == 4 and dlg._retouches
    dlg._clear_retouches()
    assert not dlg._retouches and near(dlg.regions[0][0], a1)
    print("✓ la casilla marcada después de soltar aplica la última propuesta; ↺ Quitar retoques")

    # --- arrastrar sobre el audio: dentro de un corte = que se quede algo (split) → solo retoque
    drag(app, tl, tl.x_for(10.0), tl.x_for(10.2), y)
    assert "Solo retoque a mano" in dlg.sug_lbl.text(), dlg.sug_lbl.text()
    mouse(tl, "release", tl.x_for(10.2), y)
    pump(app, 0.05)
    assert len(dlg.regions) == 3, dlg.regions
    # fuera de un corte (la pausa de 0,3 s que se respetaba) = cortar → «Mínimo a eliminar: 15 → 12»
    drag(app, tl, tl.x_for(6.0 + 2 / FPS), tl.x_for(6.0 + 8 / FPS), y)
    assert "Mínimo a eliminar" in dlg.sug_lbl.text() and "15 → 12" in dlg.sug_lbl.text(), dlg.sug_lbl.text()
    mouse(tl, "release", tl.x_for(6.0 + 8 / FPS), y)
    pump(app, 0.05)
    assert len(dlg.regions) == 4, dlg.regions
    print("✓ arrastrar sobre el audio: dentro de un corte se queda, fuera se corta (con su propuesta)")

    # --- clic sin arrastrar: el cabezal, como siempre (sin retoque)
    seeks = []
    tl.seek_requested.connect(seeks.append)
    n_ret = len(dlg._retouches)
    mouse(tl, "press", tl.x_for(5.0), y)
    mouse(tl, "release", tl.x_for(5.0), y)
    pump(app, 0.05)
    assert len(dlg._retouches) == n_ret
    print(f"✓ clic sin arrastrar: nada retocado (cabezal: {seeks[-1]:.2f} s)" if seeks
          else "✓ clic sin arrastrar: nada retocado (lo de siempre: seleccionar el clip)")

    # --- aviso si el retoque corta dentro de una palabra
    p.transcripts[mid] = {"text": "hola mundo", "words": [[1.5, 2.25, "hola"], [3.6, 4.2, "mundo"]]}
    drag(app, tl, tl.x_for(a1), tl.x_for(2.0), y)
    assert "⚠ Corta dentro de «hola»" in dlg.sug_lbl.text(), dlg.sug_lbl.text()
    assert "⚠" in tl._sil_tip[2]
    mouse(tl, "release", tl.x_for(2.0), y)
    pump(app, 0.05)
    assert "«hola»" in dlg.sug_lbl.text()
    dlg.sil_undo()
    pump(app, 0.05)
    print("✓ avisa si el retoque se come una palabra transcrita")

    # --- «Eliminar» respeta los retoques
    regs = list(dlg.regions)
    assert len(regs) == 4
    removed = sum(b - a for a, b in regs)
    dlg._apply()
    pump(app, 0.1)
    assert abs(p.duration() - (dur0 - removed)) < 1e-3, (p.duration(), dur0, removed)
    assert tl.sil_editor is None and not tl.preview_regions
    print(f"✓ «Eliminar» con los retoques: quitó {removed:.2f} s ({len(regs)} tramos)")
    c.undo_stack.undo()

    # --- sin la ventana: el borde ya no es retocable (todo como siempre)
    mouse(tl, "move", tl.x_for(a1), y, Qt.NoButton)
    assert tl.cursor().shape() != Qt.SizeHorCursor or tl._sil_hit(QPointF(tl.x_for(a1), y)) is None
    assert tl._sil_hit(QPointF(tl.x_for(a1), y)) is None
    print("✓ cerrada la ventana, la línea de tiempo se comporta como siempre")
    return win


def stripe_tests(app, out, win):
    from editoria.core.media import PEAK_RATE
    from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem
    ctrl = win.ctrl
    p = ctrl.project
    p.clips.clear()
    p.fps = FPS
    p.media["aud"] = MediaItem(id="aud", path=os.path.join(out, "no_existe.wav"), kind=KIND_AUDIO, name="voz.wav",
                               duration=8.0, probed=True)
    p.media["vid"] = MediaItem(id="vid", path=os.path.join(out, "no_existe.mp4"), kind=KIND_VIDEO, name="clip.mp4",
                               duration=8.0, width=320, height=180, fps=FPS, probed=True)
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    # dos clips de audio PEGADOS (corte en 2,5 s) y el video de arriba entero
    p.clips["c1"] = Clip(id="c1", media_id="aud", track_id=a1.id, start=0.0, source_in=0.0, duration=2.5)
    p.clips["c2"] = Clip(id="c2", media_id="aud", track_id=a1.id, start=2.5, source_in=2.5, duration=5.5)
    p.clips["cv"] = Clip(id="cv", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=8.0)
    pk = np.full(int(8.0 * PEAK_RATE), 0.5, np.float32)
    pk[int(2.0 * PEAK_RATE):int(3.0 * PEAK_RATE)] = 0.0         # franja oscura que cruza el corte entre los dos clips
    pk[int(5.0 * PEAK_RATE):int(5.5 * PEAK_RATE)] = 0.0         # y otra
    ctrl.peaks["aud"] = pk
    tl = win.timeline
    tl._on_project_changed()
    tl.pps = 60.0
    tl.scroll = 0.0
    tl._ty_cache = None
    tl.wave_silence, tl.wave_style = True, "espejo"
    ia = next(i for i, t in enumerate(p.tracks) if t.id == a1.id)
    y = tl.track_y(ia) + tl.track_h(ia) / 2

    spans = tl.silence_spans(a1.id)
    assert len(spans) == 2, spans
    assert near(spans[0][0], 2.0, 0.02) and near(spans[0][1], 3.0, 0.02), spans
    # clic derecho (sin enseñar el menú: se arma aparte)
    menus = []
    tl._clip_menu = lambda clip, gp: menus.append(tl.build_clip_menu(clip, gp))
    mouse(tl, "press", tl.x_for(2.2), y, Qt.RightButton)
    assert tl._sil_span_sel and tl._sil_span_sel[0] == a1.id and near(tl._sil_span_sel[2], 3.0, 0.02), tl._sil_span_sel
    img = tl.grab().toImage()
    img.save(os.path.join(out, "franja_elegida.png"))
    acts = [a for a in menus[0].actions() if not a.isSeparator()]
    assert acts[0].text().startswith("Eliminar este silencio"), [a.text() for a in acts[:3]]
    assert acts[1].text().startswith("Eliminar todos los silencios marcados (2"), acts[1].text()
    # en otra parte del clip (con sonido): el menú de siempre, sin eso
    tl._sil_span_sel = None
    menus.clear()
    mouse(tl, "press", tl.x_for(1.0), y, Qt.RightButton)
    assert tl._sil_span_sel is None and not menus[0].actions()[0].text().startswith("Eliminar este")
    print("✓ clic derecho en la franja oscura: se elige entera aunque cruce dos clips pegados; arriba del menú, "
          "«✂ Eliminar este silencio» y «Eliminar todos»")

    idx = ctrl.undo_stack.index()
    tl._sil_span_sel = None
    menus.clear()
    mouse(tl, "press", tl.x_for(2.2), y, Qt.RightButton)
    first = [a for a in menus[0].actions() if not a.isSeparator()][0]
    first.trigger()
    assert ctrl.undo_stack.index() == idx + 1, "un solo paso de deshacer"
    assert abs(p.duration() - 7.0) < 1.5 / FPS, p.duration()
    a_clips = sorted(p.clips_on(a1.id), key=lambda x: x.start)
    assert len(a_clips) == 2 and abs(a_clips[0].end - 2.0) < 1.5 / FPS, [(x.start, x.end) for x in a_clips]
    assert abs(a_clips[1].start - a_clips[0].end) < 1e-6, "el hueco se cierra"
    assert abs(a_clips[1].source_in - 3.0) < 1.5 / FPS, a_clips[1].source_in
    vids = p.clips_on(v1.id)
    assert abs(max(x.end for x in vids) - p.duration()) < 1e-3, "el video también (sincronizados)"
    assert len(tl.silence_spans(a1.id)) == 1
    ctrl.undo_stack.undo()
    assert abs(p.duration() - 8.0) < 1e-6
    # todos los marcados de una vez
    tl._sil_span_sel = None
    menus.clear()
    mouse(tl, "press", tl.x_for(5.2), y, Qt.RightButton)
    todos = [a for a in menus[0].actions() if a.text().startswith("Eliminar todos")]   # (sin emoji: 20/11)
    assert todos, [a.text() for a in menus[0].actions()][:4]
    todos = todos[0]
    todos.trigger()
    assert ctrl.undo_stack.index() == idx + 1 and abs(p.duration() - 6.5) < 2.5 / FPS, p.duration()
    assert not tl.silence_spans(a1.id)
    ctrl.undo_stack.undo()
    print("✓ «Eliminar este silencio» quita solo lo oscuro (audio y video juntos) y «Eliminar todos» todas; "
          "un Ctrl+Z cada uno")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_silencio_manual")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    core_tests()
    win = dialog_tests(app, out)
    stripe_tests(app, out, win)
    win.analyzer.shutdown()
    win.ctrl.undo_stack.setClean()            # (sin «¿guardar los cambios?» al cerrar)
    win.ctrl._media_dirty = False
    win.close()
    print("✓ TODO BIEN")


if __name__ == "__main__":
    main()
