"""
Prueba de 🔑 Palabras clave (ligero): solo se escucha donde hay voz, con un modelo pequeño; tolera pequeños
errores («Marcos» encuentra «Marcus»); usa la transcripción completa si ya existe (instantáneo); en la línea de
tiempo dice el momento exacto y pone marcadores; los resultados se ponen en el cabezal.
Ejecutar:  .venv/Scripts/python.exe tests/test_keywords.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_ROOT, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_ROOT, "datos", "modelos"))   # el modelo, una sola vez
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from editoria.ai import keywords as KW
    words = [[0.0, 0.4, "Hola", 0.9], [0.5, 0.9, "Marcus,", 0.9], [1.0, 1.5, "traicionó", 0.9],
             [1.6, 2.0, "al", 0.9], [2.1, 2.6, "equipo.", 0.9]]
    q = KW.parse_query("Marcos, la traición; EQUIPO")
    assert q == ["marcos", "la traicion", "equipo"], q
    hits = KW.match(words, KW.parse_query("Marcos, traición, equipo, dinosaurio"))
    got = {h["word"]: h["t0"] for h in hits}
    assert got.get("marcos") == 0.5 and got.get("traicion") == 1.0 and got.get("equipo") == 2.1, hits
    assert "dinosaurio" not in got
    print("✓ sin acentos ni mayúsculas y tolerando errores: «Marcos»→«Marcus», «traición»→«traicionó»")

    st = QSettings("EditorIA", "EditorIA")
    keep = {k: st.value(k) for k in ("ventana/paneles", "geometry")}
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.task_window import manager
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    voice = os.path.join(ASSETS, "narracion_prueba.wav")
    vid = os.path.join(out, "gameplay_con_voz.mp4")    # 6 s de música/ruido y luego la voz
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=40",
                    "-i", voice, "-f", "lavfi", "-i", "sine=f=110:d=40",
                    "-filter_complex", "[1]adelay=6000:all=1,apad[v];[2]volume=0.05[m];[v][m]amix=inputs=2:"
                    "duration=longest:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-t", "40",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", vid], check=True)
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
        v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
        ctrl.add_media([mid], v1.id, 2.0)          # en la línea de tiempo empieza en el segundo 2
        from editoria.ui.keywords_dialog import KeywordsDialog
        dlg = KeywordsDialog(win, "timeline")
        dlg.query.setText("combate, cinemáticas, narrativa")
        t0 = time.time()
        dlg.search()
        while manager().tasks and time.time() - t0 < 300:
            pump(app, 0.2)
        took = time.time() - t0
        words = {h["word"] for h in dlg.hits}
        assert {"combate", "cinematicas", "narrativa"} <= words, (dlg.hits, dlg.status.text())
        comb = [h for h in dlg.hits if h["word"] == "combate"]
        assert len(comb) == 2 and abs(comb[0]["tl"][0] - (2.0 + 6.0 + 7.8)) < 0.6, comb
        print(f"✓ en la línea de tiempo: «combate» ×2, «cinemáticas», «narrativa» en su momento exacto "
              f"({took:.1f} s; solo escuchó donde hay voz)")
        speech = json.load(open(KW._cache_file(vid), encoding="utf-8"))["speech"]
        assert all(a >= 5.0 for a, _b in speech), ("la música del principio se salta", speech)
        dlg.add_markers()
        assert sum(1 for mk in p.markers if mk.label.startswith("🔑")) == len(dlg.hits)
        print("✓ 📍 marcadores donde se dice cada palabra")
        dlg.query.setText("ritmo")
        t0 = time.time()
        dlg.search()
        while manager().tasks and time.time() - t0 < 60:
            pump(app, 0.1)
        assert time.time() - t0 < 3 and dlg.hits and dlg.hits[0]["word"] == "ritmo"
        print("✓ buscar otra palabra en el mismo archivo es instantáneo (lo escuchado se guarda)")
        dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0))
        md = dlg.tree.mimeData([dlg.tree.topLevelItem(0)])
        from editoria.ui.common import SEGMENT_MIME
        assert md.hasFormat(SEGMENT_MIME)
        n = len(p.clips)
        win.engine.seek(40.0)
        dlg.put_selected()
        assert len(p.clips) > n
        print("✓ el resultado se pone en el cabezal (o se arrastra a la línea de tiempo)")
        dlg.close()
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
