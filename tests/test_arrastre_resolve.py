"""
Arrastrar clips como en DaVinci Resolve:
  · un clip de video soltado POR ENCIMA de la pista de video más alta → pista de video nueva (arriba de todo);
  · un audio soltado POR DEBAJO de la última pista → pista de audio nueva;
  · soltar un clip encima de otro lo TAPA: lo de debajo se recorta o se quita (sobrescribir);
  · todo en un solo Ctrl+Z.
Ejecutar:  .venv/Scripts/python.exe tests/test_arrastre_resolve.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollBar  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, new_id  # noqa: E402


def media(p, kind, dur=60.0):
    m = MediaItem(new_id(), f"/falso/{kind}.mp4", kind, f"{kind}.mp4", duration=dur, probed=True)
    p.media[m.id] = m
    return m


def clip(p, m, track, start, dur):
    c = Clip(new_id(), m.id, track.id, start, 0.0, dur)
    p.clips[c.id] = c
    return c


def raton(tl, tipo, x, y):
    ev = QMouseEvent(tipo, QPointF(x, y), QPointF(x, y), Qt.LeftButton,
                     Qt.LeftButton if tipo != QEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
    {QEvent.MouseButtonPress: tl.mousePressEvent, QEvent.MouseMove: tl.mouseMoveEvent,
     QEvent.MouseButtonRelease: tl.mouseReleaseEvent}[tipo](ev)


def arrastrar(tl, c, dx, y_dest):
    tl.pps, tl.scroll = 40.0, 0.0                  # (10 s = 400 px: el clic cae en medio del clip, no en un borde)
    r = tl.clip_rect(c)
    x0, y0 = r.center().x(), r.center().y()
    raton(tl, QEvent.MouseButtonPress, x0, y0)
    for k in range(1, 6):
        raton(tl, QEvent.MouseMove, x0 + dx * k / 5, y0 + (y_dest - y0) * k / 5)
    nueva = (tl._drag or {}).get("nueva")
    raton(tl, QEvent.MouseButtonRelease, x0 + dx, y_dest)
    return nueva


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.ui.timeline import TimelineWidget
    ctrl = ProjectController()
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    mv, ma = media(p, KIND_VIDEO), media(p, KIND_AUDIO)
    c_v = clip(p, mv, v1, 0.0, 10.0)
    c_a = clip(p, ma, a1, 0.0, 10.0)
    ctrl.undo_stack.clear()
    ctrl.project_changed.emit()

    tl = TimelineWidget(ctrl, QScrollBar())
    tl.resize(1400, 400)
    tl.snapping = False
    tl.linked = False
    tl.pps = 40.0
    tl.scroll = 0.0
    n_v = sum(1 for t in p.tracks if t.kind == TRACK_VIDEO)

    # 1) video por encima de la pista de video más alta → pista nueva arriba de todo
    first_v = next(i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO)
    nueva = arrastrar(tl, c_v, 0, tl.track_y(first_v) - 5)
    assert nueva == "arriba", nueva
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    assert len(vids) == n_v + 1, "no se creó la pista de video"
    assert p.clips[c_v.id].track_id == vids[0].id, "el clip no está en la pista nueva de arriba"
    print("✓ video arrastrado por encima de todo: pista de video nueva arriba, con el clip")
    ctrl.undo_stack.undo()
    assert sum(1 for t in p.tracks if t.kind == TRACK_VIDEO) == n_v and p.clips[c_v.id].track_id == v1.id
    print("✓ un Ctrl+Z quita la pista y devuelve el clip")

    # 2) audio por debajo de la última pista → pista de audio nueva al final
    n_a = sum(1 for t in p.tracks if t.kind == TRACK_AUDIO)
    nueva = arrastrar(tl, p.clips[c_a.id], 0, tl.track_y(len(p.tracks)) + 20)
    assert nueva == "abajo", nueva
    assert sum(1 for t in p.tracks if t.kind == TRACK_AUDIO) == n_a + 1
    assert p.clips[c_a.id].track_id == p.tracks[-1].id
    print("✓ audio arrastrado por debajo de todo: pista de audio nueva al final")
    ctrl.undo_stack.undo()

    # 3) sobrescribir: un clip de V2 (12–20 s) se suelta encima del de V1 (0–10 s) en 4–12 s
    from editoria.core.model import Track
    v2 = Track(new_id(), TRACK_VIDEO, "V2")
    p.tracks.insert(next(i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO), v2)
    c_b = clip(p, mv, v2, 12.0, 8.0)
    ctrl.undo_stack.clear()
    ctrl.project_changed.emit()
    i_v1 = p.track_index(v1.id)
    arrastrar(tl, p.clips[c_b.id], -8.0 * tl.pps, tl.track_y(i_v1) + tl.track_h(i_v1) / 2)
    cb = p.clips[c_b.id]
    assert cb.track_id == v1.id and abs(cb.start - 4.0) < 0.05, (cb.track_id == v1.id, cb.start)
    abajo = p.clips[c_v.id]
    assert abs(abajo.start) < 1e-6 and abs(abajo.end - cb.start) < 0.05, (abajo.start, abajo.end)
    print("✓ soltado encima de otro clip: lo tapa y lo de debajo se recorta (como en Resolve)")
    ctrl.undo_stack.undo()
    assert abs(p.clips[c_v.id].end - 10.0) < 1e-6 and p.clips[c_b.id].track_id == v2.id
    print("✓ Ctrl+Z lo deja como estaba")
    ctrl.undo_stack.redo()
    assert p.clips[c_b.id].track_id == v1.id and abs(p.clips[c_v.id].end - p.clips[c_b.id].start) < 0.05
    ctrl.undo_stack.undo()
    print("✓ Ctrl+Y lo rehace igual")

    # 4) encima de un clip BLOQUEADO: no se mueve nada y no queda ninguna pista creada
    p.clips[c_v.id].locked = True
    n_pistas = len(p.tracks)
    arrastrar(tl, p.clips[c_b.id], -8.0 * tl.pps, tl.track_y(i_v1) + tl.track_h(i_v1) / 2)
    assert p.clips[c_b.id].track_id == v2.id and abs(p.clips[c_v.id].end - 10.0) < 1e-6 and len(p.tracks) == n_pistas
    print("✓ sobre un clip bloqueado: no lo tapa (y avisa)")
    print("TODO OK")


if __name__ == "__main__":
    main()
