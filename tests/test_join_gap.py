"""
Prueba de los CANALES (como en DaVinci Resolve) con «⇤ Juntar» (Ctrl++), «✂ Dividir» (S) y el recorte:
  · clic en un clip, en la zona vacía de su pista o en la cabecera = ese canal (resaltado); otra vez en la cabecera o
    clic debajo de las pistas = ninguno (toda la línea de tiempo);
  · Ctrl++ (la tecla de verdad): TODO se pega a la izquierda sin huecos en el canal seleccionado (con su imagen o
    sonido vinculado: nada se desincroniza; los demás canales no se tocan) o, sin canal, en toda la línea de tiempo;
    un solo Ctrl+Z; si no hay huecos, avisa;
  · S corta lo que hay bajo el cabezal en el canal (y lo vinculado), aunque el trozo seleccionado esté en otro sitio;
  · al recortar un borde, el contenido no se estira: desaparece por el borde (onda e imagen en su sitio);
  · rápido con 1000 clips.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_join_gap.py <carpeta_salida>
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
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=20",
                    "-f", "lavfi", "-i", "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", vid], check=True)
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.activateWindow()
    pump(app, 0.3)
    ctrl, tl, p = win.ctrl, win.timeline, win.ctrl.project
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([mid], v1.id, 0.0)                       # 0–20 s, imagen + sonido vinculado
    p = ctrl.project
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO and p.clips_on(t.id))
    # quitar el tramo 5–8 s (un trozo del medio) SIN cerrar: queda un hueco de 3 s en imagen y sonido
    ctrl.split(5.0)
    ctrl.split(8.0)
    mids = [c.id for tr in (v1, a1) for c in ctrl.project.clips_on(tr.id) if abs(c.start - 5.0) < 1e-6]
    ctrl.delete_clips(mids)
    p = ctrl.project
    v2 = next(t for t in p.tracks if t.kind == TRACK_VIDEO and t.id != v1.id)
    ctrl.insert_ranges([{"media_id": mid, "start": 12.0, "source_in": 0.0, "duration": 3.0}], v2.id, "broll")
    p = ctrl.project

    def starts(tid):
        return [round(c.start, 3) for c in ctrl.project.clips_on(tid)]
    assert starts(v1.id) == [0.0, 8.0] and starts(a1.id) == [0.0, 8.0], (starts(v1.id), starts(a1.id))
    key = next(k for k, (a, d) in win.shortcut_actions.items() if "Juntar" in k)
    assert win.shortcut_actions[key][1] == "Ctrl++", win.shortcut_actions[key]

    # 1) elegir el canal con el ratón
    def click(x, y, mods=Qt.NoModifier):
        QTest.mouseClick(tl, Qt.LeftButton, mods, QPoint(int(x), int(y)))
        pump(app, 0.05)
    tl.set_selection([])
    left_v1 = ctrl.project.clips_on(v1.id)[0]
    r = tl.clip_rect(left_v1)
    click(r.center().x(), r.center().y())
    assert tl.channel_ids() == [v1.id], tl.channels
    ia = p.track_index(a1.id)
    hy = tl.track_y(ia) + tl.track_h(ia) - 6
    click(14, hy)
    assert tl.channel_ids() == [a1.id], tl.channels
    click(14, hy)
    assert tl.channel_ids() == [], tl.channels
    iv2 = p.track_index(v2.id)
    click(tl.x_for(2.0), tl.track_y(iv2) + tl.track_h(iv2) / 2)
    assert tl.channel_ids() == [v2.id], tl.channels
    click(tl.x_for(2.0), tl.track_y(ia) + tl.track_h(ia) / 2, Qt.ControlModifier)
    assert set(tl.channel_ids()) == {v2.id, a1.id}, tl.channels
    tl.grab()                                      # (se dibuja resaltado sin errores)
    print("✓ canal: clic en un clip, en su pista o en la cabecera (otra vez = ninguno; Ctrl = añadir)")

    # 2) Ctrl++ con el canal A1: se pega su sonido y su imagen vinculada; el B-roll de V2 no se mueve
    tl.set_channels([a1.id])
    win.engine.seek(15.0)
    pump(app, 0.1)
    idx = ctrl.undo_stack.index()
    QTest.keyClick(win, Qt.Key_Plus, Qt.ControlModifier)
    pump(app, 0.2)
    via = "la tecla Ctrl++"
    if starts(a1.id) != [0.0, 5.0]:              # (sin foco de ventana en modo de prueba: la misma acción)
        via = "la acción del atajo (sin foco de ventana en la prueba)"
        win.shortcut_actions[key][0].trigger()
        pump(app, 0.2)
    assert starts(v1.id) == [0.0, 5.0] and starts(a1.id) == [0.0, 5.0], (starts(v1.id), starts(a1.id))
    assert starts(v2.id) == [12.0], starts(v2.id)
    assert ctrl.undo_stack.index() == idx + 1
    left = ctrl.project.clips_on(v1.id)[0]
    assert abs(left.start) < 1e-9 and abs(left.end - 5.0) < 1e-6        # lo de la izquierda no se movió
    print(f"✓ Ctrl++ ({via}) en el canal A1: todo pegado a la izquierda, con su imagen; V2 no se tocó")
    ctrl.undo_stack.undo()
    assert starts(v1.id) == [0.0, 8.0] and starts(a1.id) == [0.0, 8.0] and starts(v2.id) == [12.0]
    print("✓ un solo Ctrl+Z lo devuelve")

    # 3) sin canal: toda la línea de tiempo
    tl.set_channels([])
    win._join_right()
    assert starts(v1.id) == [0.0, 5.0] and starts(a1.id) == [0.0, 5.0] and starts(v2.id) == [0.0],         (starts(v1.id), starts(a1.id), starts(v2.id))
    print("✓ sin canal: toda la línea de tiempo pegada a la izquierda")

    # 4) ya sin huecos: avisa y no cambia nada
    msgs = []
    ctrl.message.connect(msgs.append)
    idx = ctrl.undo_stack.index()
    win._join_right()
    assert ctrl.undo_stack.index() == idx and msgs and "hueco" in msgs[-1], msgs
    print(f"✓ sin huecos: avisa («{msgs[-1][:60]}…») y no toca nada")
    ctrl.undo_stack.undo()

    # 5) S por canal: el trozo seleccionado puede estar en otro sitio
    tl.set_selection([ctrl.project.clips_on(v1.id)[0].id])      # el trozo 0–5 s…
    tl.set_channels([v1.id])
    win.engine.seek(15.0)                                          # …y el cabezal en el otro trozo de V1
    pump(app, 0.1)
    n_v2 = len(ctrl.project.clips_on(v2.id))
    win._split()
    assert starts(v1.id) == [0.0, 8.0, 15.0] and starts(a1.id) == [0.0, 8.0, 15.0], (starts(v1.id), starts(a1.id))
    assert len(ctrl.project.clips_on(v2.id)) == n_v2
    tl.set_channels([v2.id])
    win.engine.seek(13.0)
    pump(app, 0.1)
    win._split()
    assert starts(v2.id) == [12.0, 13.0] and starts(v1.id) == [0.0, 8.0, 15.0], (starts(v2.id), starts(v1.id))
    print("✓ S corta en el canal (con su sonido vinculado), no en el trozo seleccionado ni en otros canales")
    ctrl.undo_stack.undo()
    ctrl.undo_stack.undo()

    # 6) recortar sin estirar
    c = ctrl.project.clips_on(v1.id)[1]          # 8–20 s, desde el segundo 8 del archivo
    t = tl._trimmed(c, 10.0, c.end)
    assert abs(t.source_in - (c.source_in + 2.0)) < 1e-9 and abs(t.end - c.end) < 1e-9
    t = tl._trimmed(c, c.start, 15.0)
    assert abs(t.source_in - c.source_in) < 1e-9 and abs(t.duration - 7.0) < 1e-9
    from dataclasses import replace as _rep
    t = tl._trimmed(_rep(c, reverse=True), c.start, 15.0)
    assert abs(t.source_in - (c.source_in + 5.0)) < 1e-9
    tl._drag = {"type": "trim", "clip": c.id, "edge": "left", "x0": 0, "new_start": 10.0, "new_end": c.end,
                "limits": (0, 20, 0, 40), "partners": ctrl.linked_ids([c.id])[1:], "linked": True, "active": True}
    tl.grab()
    tl._drag = None
    print("✓ recortar: el contenido desaparece por el borde (no se estira), también al revés")

    # 7) rápido con muchos clips (1000 huecos en un canal)
    v_extra = ctrl.add_track(TRACK_VIDEO) if hasattr(ctrl, "add_track") else None
    tid = v_extra if isinstance(v_extra, str) else next(t.id for t in ctrl.project.tracks
                                                         if t.kind == TRACK_VIDEO and not ctrl.project.clips_on(t.id))
    ctrl.insert_ranges([{"media_id": mid, "start": 40.0 + i * 1.5, "duration": 1.0, "source_in": (i % 15) * 1.0}
                        for i in range(1000)], tid, "muchos")
    p = ctrl.project
    pump(app, 0.3)
    tl.set_channels([tid])
    t0 = time.perf_counter()
    win._join_right()
    app.processEvents()
    ms = (time.perf_counter() - t0) * 1000
    st = starts(tid)                             # (su sonido vinculado no puede pisar el audio de A1: 0–20 s)
    assert st[0] == 20.0 and all(abs(b - a - 1.0) < 1e-6 for a, b in zip(st, st[1:])), st[:4]
    print(f"✓ con {len(p.clips)} clips: pegar 1000 huecos tarda {ms:.0f} ms")
    assert ms < 1500, ms
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
