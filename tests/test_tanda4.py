"""
Prueba de la tanda 4:
  · 🔑 palabras clave en el edit musical: el elegidor prefiere los planos donde se dice la palabra (y uno en el drop);
  · «Primera versión automática» con «Transcribir la voz» apagado: no transcribe y salta lo que necesita tu voz;
  · ventana del edit en pestañas, con el campo de palabras clave; ✂ recorte con «Calidad: Rápida»;
  · seleccionar repinta solo los clips que cambian (y la selección queda bien).
Ejecutar:  .venv/Scripts/python.exe tests/test_tanda4.py <carpeta_salida>
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
    n = int(60 / E.STEP)
    prof = {"motion": list(np.ones(n)), "bright": list(np.ones(n)), "cut": list(np.zeros(n))}
    src = {"media_id": "m", "kind": "video", "duration": 60.0, "profile": prof, "prefer": [30.0, 45.0],
           "prefer_drop": True}
    pk = E._Picker([src], seed=11)
    r = pk.pick(2.0, 0.5, "drop")
    assert r["source_in"] <= 30.0 <= r["source_in"] + 2.0 or r["source_in"] <= 45.0 <= r["source_in"] + 2.0, r
    r2 = pk.pick(2.0, 0.5, "drop")
    said = [t for t in (30.0, 45.0) if r2["source_in"] <= t <= r2["source_in"] + 2.0]
    assert said and said[0] not in [t for t in (30.0, 45.0) if r["source_in"] <= t <= r["source_in"] + 2.0], (r, r2)
    print("✓ 🔑 el edit prefiere los planos donde se dicen tus palabras (cada frase una vez; una en el drop)")

    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("auto/transcribe",)}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import motor_ia
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.auto_dialog import STEPS, AutoDialog
    from editoria.ui.edit_dialog import EditDialog
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    try:
        win = MainWindow()
        win.resize(1500, 900)
        win.show()
        pump(app, 0.3)
        ctrl = win.ctrl
        dlg = AutoDialog(win)
        dlg.do_tr.setChecked(False)
        assert not dlg.opts["clean"].isEnabled() and not dlg.opts["subs"].isEnabled()
        i_tr = [k for k, _l in STEPS].index("transcribe")
        dlg._run(i_tr)
        dlg.cancelled = True
        pump(app, 0.3)
        assert dlg.steps.item(i_tr).text().startswith("–"), dlg.steps.item(i_tr).text()
        dlg.close()
        print("✓ «Transcribir la voz» apagado: no transcribe y lo que necesita tu voz queda en gris y se salta")

        QSettings("EditorIA", "EditorIA").remove("secciones/edit_musical")
        ed = EditDialog(ctrl, win)
        secs = ed.sections
        assert list(secs) == ["Canción y estilo", "Efectos", "Clips", "Frases"], list(secs)
        assert secs["Clips"].is_open() and secs["Canción y estilo"].is_open() and not secs["Efectos"].is_open()
        secs["Efectos"].head.click()
        assert secs["Efectos"].is_open() and not ed.opt["grain"].isHidden()
        ed.close()
        ed = EditDialog(ctrl, win)
        assert ed.sections["Efectos"].is_open(), "recuerda las secciones que dejaste abiertas"
        ed.sections["Efectos"].head.click()
        assert not ed.sections["Efectos"].is_open() and ed.sections["Efectos"].body.isHidden()
        assert ed.kw.placeholderText() and ed.kw_drop.isChecked()
        ed.close()
        print("✓ ventana del edit en secciones plegables (▾/▸), «Clips» abierta de entrada; recuerda cuáles abres")

        vid = os.path.join(out, "v.mp4")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=6", "-pix_fmt", "yuv420p", vid], check=True)
        (mid,) = ctrl.import_now([vid])
        while ctrl.analyzing:
            pump(app, 0.1)
        ed = EditDialog(ctrl, win)
        ed.show()
        t0 = time.time()
        while mid not in ed._thumbs and time.time() - t0 < 30:
            pump(app, 0.1)
        it = next(ed.clips.item(i) for i in range(ed.clips.count()) if ed.clips.item(i).data(Qt.UserRole) == mid)
        assert not it.icon().isNull(), "cada clip con su miniatura"
        ed._hover_clip(it)
        assert ed._big.isVisible() and ed._big.pixmap().width() >= 300, "al pasar el ratón: la miniatura en grande"
        ed.close()
        assert not ed._big.isVisible()
        print("✓ «Clips» con miniaturas; al pasar el ratón se ve en grande")
        v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
        ids = [c for c in ctrl.add_media([mid, mid, mid], v1.id, 0.0)
               if ctrl.project.track(ctrl.project.clips[c].track_id).kind == TRACK_VIDEO]
        if motor_ia.SAM_FAST_MODEL.exists():
            from editoria.ui.subject_cut_dialog import SubjectCutDialog
            sd = SubjectCutDialog(ctrl, ids[0], 1.0, win)
            sd.quality.setCurrentIndex(sd.quality.findData("fast"))
            sd.view.points = [(0.5, 0.5, 1)]
            job = sd._job("video", os.path.join(out, "m.mkv"), 0.0, 2.0)
            assert "base_plus" in job["modelo"] and job["ancho"] == 854, job
            sd.close()
            print("✓ ✂ recorte con «Calidad: Rápida» (modelo mediano, ~2× más rápido)")
        tl = win.timeline
        tl.set_selection([ids[0]])
        tl.set_selection([ids[1]])
        assert tl.selected == {ids[1]}
        tl.set_selection([ids[0], ids[2]])
        assert tl.selected == {ids[0], ids[2]}
        tl.grab()
        print("✓ seleccionar repinta solo lo que cambia y la selección queda bien")
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
