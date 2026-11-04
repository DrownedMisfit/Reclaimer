"""
Prueba de editar transiciones desde la línea de tiempo: clic = seleccionarla, Supr o Ctrl+X = quitarla, arrastrar
un borde = más larga / más corta, clic derecho = reemplazar / duración, y la escala de las que pone la IA
(más cortas / más largas, también las ya puestas). Todo con Ctrl+Z.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_trans_edit.py <carpeta_salida>
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

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def mouse(tl, kind, x, y, button=Qt.LeftButton):
    typ = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    btns = button if kind != "release" else Qt.NoButton
    ev = QMouseEvent(typ, QPointF(x, y), QPointF(x, y), button if kind != "move" else Qt.NoButton, btns,
                     Qt.NoModifier)
    {"press": tl.mousePressEvent, "move": tl.mouseMoveEvent, "release": tl.mouseReleaseEvent}[kind](ev)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry", "transiciones/escala_ia")}
    app = QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.core import transitions as TR
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        st.remove("transiciones/escala_ia")
        vid = os.path.join(out, "v.mp4")
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=8", "-c:v", "libx264", "-preset", "ultrafast", vid], check=True)
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        pump(app, 0.4)
        ctrl, tl = win.ctrl, win.timeline
        p = ctrl.project
        (mid,) = ctrl.import_now([vid])
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        A = ctrl.add_media([mid], v1.id, 0.0)[0]
        B = ctrl.add_media([mid], v1.id, 8.0)[0]
        B = next(c.id for c in p.clips_on(v1.id) if abs(c.start - 8.0) < 1e-6)
        ctrl.set_transition([B], "fade", 1.0)
        tl.pps = 80.0
        tl.offset = 0.0 if hasattr(tl, "offset") else None
        tl.update()
        pump(app, 0.2)
        i = p.tracks.index(v1)
        y = tl.track_y(i) + tl.track_h(i) / 2 + 6
        xc = tl.x_for(8.0)
        hit = tl.trans_at(QPointF(xc, y))
        assert hit and hit[0] == B and hit[2] is None, hit
        # 1) clic = seleccionar; Ctrl+X = quitar
        mouse(tl, "press", xc, y)
        mouse(tl, "release", xc, y)
        assert tl.sel_trans == B and not tl.selected, "la transición queda seleccionada (no los clips)"
        pump(app, 0.1)
        tl.grab().save(os.path.join(out, "transicion_seleccionada.png"))
        win._copy(True)                                       # Ctrl+X
        assert TR.of(p.clips[B]) is None and tl.sel_trans is None and len(p.clips_on(v1.id)) == 2
        ctrl.undo_stack.undo()
        assert TR.of(p.clips[B])["dur"] == 1.0
        mouse(tl, "press", xc, y)
        mouse(tl, "release", xc, y)
        win._delete(False)                                    # Supr
        assert TR.of(p.clips[B]) is None and len(p.clips_on(v1.id)) == 2, "solo la transición, no los clips"
        ctrl.undo_stack.undo()
        print("✓ clic = seleccionar la transición · Ctrl+X o Supr = quitarla (los clips quedan) · Ctrl+Z la devuelve")

        # 2) arrastrar el borde derecho = más larga
        r = tl.trans_at(QPointF(xc, y))[1]
        xr = r.right() - 2
        assert tl.trans_at(QPointF(xr, y))[2] == "r"
        mouse(tl, "press", xr, y)
        mouse(tl, "move", xc + 1.0 * tl.pps, y)               # mitad = 1 s → 2 s
        assert tl._trans_preview and abs(tl._trans_preview[1] - 2.0) < 0.06, tl._trans_preview
        mouse(tl, "release", xc + 1.0 * tl.pps, y)
        assert abs(TR.of(p.clips[B])["dur"] - 2.0) < 0.06, TR.of(p.clips[B])
        rl = tl.trans_at(QPointF(xc, y))[1]
        mouse(tl, "press", rl.left() + 2, y)
        mouse(tl, "move", xc - 0.25 * tl.pps, y)              # → 0,5 s
        mouse(tl, "release", xc - 0.25 * tl.pps, y)
        assert abs(TR.of(p.clips[B])["dur"] - 0.5) < 0.06, TR.of(p.clips[B])
        ctrl.undo_stack.undo()
        assert abs(TR.of(p.clips[B])["dur"] - 2.0) < 0.06
        print("✓ arrastrar un borde = más larga o más corta (se ve la duración mientras arrastras)")

        # 3) clic derecho: reemplazar / duración (sin abrir el menú de verdad)
        shown = []

        def grab_menu():
            m = app.activePopupWidget()
            if isinstance(m, QMenu):
                shown.append([a.text() for a in m.actions()])
                m.close()
            else:
                QTimer.singleShot(100, grab_menu)
        QTimer.singleShot(150, grab_menu)
        mouse(tl, "press", xc, y, Qt.RightButton)
        assert shown and any("Reemplazar" in t for t in shown[0]) and any("Quitar" in t for t in shown[0])
        assert any("IA" in t for t in shown[0])
        other = next(k for k, _n, _d in TR.CATALOG if k != "fade")
        d0 = float(TR.of(p.clips[B])["dur"])
        ctrl.set_transition([B], other, d0)                 # «Reemplazar por» hace esto
        assert TR.of(p.clips[B])["type"] == other and abs(TR.of(p.clips[B])["dur"] - d0) < 1e-6, "misma duración"
        print("✓ clic derecho: 🔁 Reemplazar por…, ⏱ Duración, ✕ Quitar y 🤖 las de la IA")

        # 4) las de la IA: más largas (también las ya puestas) — y el ajuste se recuerda
        prevc = TR.previous(p, p.clips[B])
        p.clips[B].fx = dict(p.clips[B].fx, trans=TR.ai_trans("fade", 0.5, prevc, p.clips[B]))
        assert TR.of(p.clips[B])["dur"] == 0.5 and TR.of(p.clips[B])["ai"]
        tl._set_ai_trans_scale(2.0)
        assert abs(TR.ai_scale() - 2.0) < 1e-6
        assert abs(TR.of(p.clips[B])["dur"] - 1.0) < 1e-6, TR.of(p.clips[B])
        assert TR.ai_trans("fade", 0.5, prevc, p.clips[B])["dur"] == 1.0, "las nuevas de la IA, también"
        tl._set_ai_trans_scale(0.5)
        assert abs(TR.of(p.clips[B])["dur"] - 0.25) < 1e-6
        ctrl.undo_stack.undo()
        assert abs(TR.of(p.clips[B])["dur"] - 1.0) < 1e-6
        print("✓ 🤖 transiciones de la IA más cortas / más largas: las nuevas y las que ya puso (Ctrl+Z)")

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
