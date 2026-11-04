"""
Prueba de:
  · Efectos que se ARRASTRAN encima de un clip (⭐ mis efectos, efectos de imagen, transiciones): se ponen en ese
    clip (o en todos los seleccionados si lo sueltas encima de uno de ellos); si el clip está bloqueado, lo dice.
  · 👎 en unos planos de un edit: quedan VETADOS (no vuelven a salir en Remix / Mix / edits nuevos); Ctrl+Z los
    vuelve a permitir; el elegidor de planos los esquiva.
  · ⧉ Clip compuesto acepta la lista de clips (antes: «unhashable type: 'Clip'»).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_fx_drop.py <carpeta_salida>
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
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "efectos/memoria")}
    app = QApplication(sys.argv)
    from editoria.ai.edit_maker import STEP, _Picker
    from editoria.core import compound as CP
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.common import EFFECT_MIME
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    vid = os.path.join(out, "v.mp4")
    subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vid], check=True)
    try:
        st.remove("efectos/memoria")
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl, tl, fxp = win.ctrl, win.timeline, win.effects
        p = ctrl.project
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        ids = ctrl.add_media([mid, mid, mid], v1.id, 0.0)
        a, b, c = sorted(ids, key=lambda i: p.clips[i].start)
        pump(app, 0.2)

        # 1) arrastrar ⭐ Glitch encima del clip b → solo b
        fxp.add_to_memory("look:glitch")
        md = fxp.mem_list.mimeData([fxp.mem_list.item(0)])
        assert md.data(EFFECT_MIME).data().decode() == "look:glitch"

        def drop(cid, mdata):
            cl = p.clips[cid]
            i = p.track_index(cl.track_id)
            pos = QPointF((tl.x_for(cl.start) + tl.x_for(cl.end)) / 2, tl.track_y(i) + tl.track_h(i) / 2)
            ev = QDropEvent(pos, Qt.CopyAction, mdata, Qt.LeftButton, Qt.NoModifier)
            tl.dropEvent(ev)
            pump(app, 0.1)
        tl.set_selection([])
        drop(b, md)
        assert (p.clips[b].fx or {}).get("glitch") and not (p.clips[a].fx or {}).get("glitch"), \
            ({k: p.clips[k].fx for k in (a, b)})
        print("✓ ⭐ arrastrado encima de un clip: se pone en ese clip")
        # encima de uno de varios seleccionados → en todos ellos
        md2 = QMimeData()
        md2.setData(EFFECT_MIME, b"look:vignette")
        tl.set_selection([a, c])
        drop(c, md2)
        assert (p.clips[a].fx or {}).get("vignette") and (p.clips[c].fx or {}).get("vignette")
        assert not (p.clips[b].fx or {}).get("vignette")
        print("✓ soltado encima de un clip seleccionado: se pone en todos los seleccionados")
        # transición desde la lista (prefijo trans:)
        tm = fxp.trans_list.mimeData([fxp.trans_list.item(1)])
        assert tm.data(EFFECT_MIME).data().decode().startswith("trans:")
        tl.set_selection([])
        drop(b, tm)
        assert (p.clips[b].fx or {}).get("trans"), p.clips[b].fx
        print("✓ transición arrastrada encima del clip: se pone en su corte")
        # bloqueado: lo dice
        ctrl.set_clip_props([a], "bloquear", locked=True)
        md3 = QMimeData()
        md3.setData(EFFECT_MIME, b"look:bw")
        drop(a, md3)
        assert "bloqueado" in fxp.fx_status.text() and not (p.clips[a].fx or {}).get("bw"), fxp.fx_status.text()
        ctrl.set_clip_props([a], "desbloquear", locked=False)
        print("✓ clip bloqueado: avisa en vez de no hacer nada")

        # 2) 👎 vetar planos
        p.edits.append({"id": "e1", "base": 0.0, "duration": p.clips[c].end, "clip_ids": [a, b, c],
                        "style": "phonk", "sources": [mid]})
        n = ctrl.ban_edit_clips("e1", [b])
        assert n == 1
        av = ctrl.edit_avoid()
        cb = p.clips[b]
        assert av[mid] == [(round(cb.source_in, 3), round(cb.source_in + cb.src_len, 3))], av
        ctrl.undo_stack.undo()
        assert not ctrl.edit_avoid(), "Ctrl+Z los vuelve a permitir"
        ctrl.undo_stack.redo()
        assert ctrl.edit_avoid()
        print("✓ 👎 veta esos planos (Ctrl+Z los vuelve a permitir)")
        # ⛔ «Aquí no»: el plano no va en SU tramo, pero sí puede salir en otras partes del edit
        bar_lay = win.edit_bar.layout()
        order = [bar_lay.itemAt(i).widget() for i in range(bar_lay.count())]
        assert order.index(win.edit_bar.b_not_here) == order.index(win.edit_bar.b_dislike) + 1, "a la derecha del 👎"
        cc = p.clips[c]
        assert ctrl.ban_edit_slot("e1", [c]) == 1
        here = ctrl.edit_slot_avoid("e1", cc.start, cc.end)
        assert here[mid] == [(round(cc.source_in, 3), round(cc.source_in + cc.src_len, 3))], here
        ca = p.clips[a]
        assert not ctrl.edit_slot_avoid("e1", ca.start, min(ca.end, cc.start)), "en otro tramo sí puede salir"
        assert ctrl.edit_avoid()[mid] == av[mid], "no se veta para siempre (eso es 👎)"
        ctrl.undo_stack.undo()
        assert not ctrl.edit_slot_avoid("e1", cc.start, cc.end), "Ctrl+Z lo vuelve a permitir ahí"
        ctrl.undo_stack.redo()
        assert ctrl.edit_slot_avoid("e1", cc.start, cc.end)
        print("✓ ⛔ Aquí no (a la derecha del 👎): ese plano ya no va en ESE tramo; en otros sí; Ctrl+Z lo deshace")
        # el botón: lo apunta y rehace ese tramo al momento pidiendo al motor que evite ese plano ahí
        got = {}
        eb = win.edit_bar
        old_run = eb._run
        eb._run = lambda title, rec, opts, on_plan: got.update(title=title, opts=opts)
        v1 = [t for t in p.tracks if t.kind == "video"][-1]
        if cc.track_id == v1.id:
            ctrl.undo_stack.undo()                      # (desde cero: el botón lo vuelve a apuntar)
            tl.set_selection([c])
            win.engine.seek(cc.start + 0.01)
            eb.b_not_here.click()
            assert ctrl.edit_slot_avoid("e1", cc.start, cc.end), "apuntado al pulsar el botón"
            spans = (got.get("opts") or {}).get("avoid", {}).get(mid, [])
            assert (round(cc.source_in, 3), round(cc.source_in + cc.src_len, 3)) in spans, got
            print("✓ el botón lo apunta y rehace ese tramo al momento pidiendo otro plano ahí")
        eb._run = old_run
        # el elegidor los esquiva: vídeo de 60 s, vetado todo menos 40–50 s
        nstep = int(60 / STEP)
        prof = {"motion": list(np.ones(nstep)), "bright": list(np.ones(nstep)), "cut": list(np.zeros(nstep))}
        src = {"media_id": "m", "kind": "video", "duration": 60.0, "profile": prof,
               "avoid": [(0.0, 40.0), (50.0, 60.0)]}
        pk = _Picker([src], seed=3)
        for _ in range(4):
            r = pk.pick(2.0, 0.5, "main")
            assert 40.0 - 0.2 <= r["source_in"] and r["source_in"] + 2.0 <= 50.0 + 0.2, r
        print("✓ el elegidor de planos no vuelve a usar los vetados")

        # 3) clip compuesto con objetos Clip (antes: unhashable type)
        assert CP.with_partners(p, [p.clips[a], p.clips[b]]) >= {a, b}
        print("✓ clip compuesto: acepta la lista de clips")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.2)
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
