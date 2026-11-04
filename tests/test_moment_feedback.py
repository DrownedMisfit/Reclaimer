"""
Prueba de ✓/✗ en los momentos de TUS videos y de la tarjeta «🤔 ¿Es esto?» (videos e internet):
con ✓ busca más apariciones parecidas, con ✗ aparta las parecidas, lo recuerda, y los ✓ de un nombre que la IA
conoce («Jefe Maestro») le enseñan cómo es (índice de «Entender mi biblioteca»).
Las huellas de los fotogramas son simuladas (se sabe dónde sale el personaje).
Ejecutar:  .venv/Scripts/python.exe tests/test_moment_feedback.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import image_feedback as IF  # noqa: E402
from editoria.ai import moments as MO  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402

QUERY = "jefe maestro"


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    paths = []
    for name in ("A", "B", "C"):
        p = os.path.join(out, f"juego_{name}.mp4")
        subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=320x180:r=30:d=20", "-c:v", "libx264", "-preset", "ultrafast", p], check=True)
        paths.append(p)
    rng = np.random.default_rng(7)
    chief, other, wall = (v / np.linalg.norm(v) for v in rng.normal(size=(3, 512)))

    def frames(spec):
        times = np.arange(0, 20, 1.0, np.float32)
        vecs = []
        for t in times:
            base = next((c for a, b, c in spec if a <= t < b), other)
            v = base + 0.3 * rng.normal(size=512) / np.sqrt(512)   # variación realista entre fotogramas
            vecs.append(v / np.linalg.norm(v))
        return times, np.asarray(vecs, np.float32)

    store = IF._store_path()
    backup = open(store, encoding="utf-8").read() if os.path.exists(store) else None
    try:
        app = QApplication(sys.argv)
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        ctrl = win.ctrl
        a, b, c = ctrl.import_now(paths)
        ctrl.analyzer_enabled = False
        pump(app, 0.3)
        ctrl.clip_vecs.clear()
        ctrl.clip_vecs[a] = frames([(5, 10, chief)])                 # sale en 5–10 s
        ctrl.clip_vecs[b] = frames([(0, 20, wall)])                  # nunca sale (otra cosa)
        ctrl.clip_vecs[c] = frames([(12, 16, chief), (0, 5, wall)])  # sale en 12–16 s
        panel = win.moments
        win.show_panel(panel)
        panel.source.setCurrentIndex(panel.source.findData("local"))
        panel.local_query = QUERY
        panel.query_label = f"«{QUERY}»"
        # La búsqueda por texto encontró esto (una buena y dos malas; no encontró la de C)
        text_hits = [MO.Moment(a, 6.0, 9.0, 7.0, 3.0), MO.Moment(b, 2.0, 4.0, 3.0, 2.9),
                     MO.Moment(b, 11.0, 13.0, 12.0, 2.8)]
        panel._on_partial(("results", text_hits))
        pump(app, 0.2)
        assert panel.marks_enabled() and not panel.ask_card.isVisible(), "ya no hay tarjeta arriba"
        confs = [panel.grid.item(i).data(Qt.UserRole + 2) for i in range(panel.grid.count())]
        assert all(c is not None and 0 <= c <= 1 for c in confs) and confs[0] == max(confs), confs
        print(f"✓ cada imagen lleva su barra «es lo que buscas»: {[round(c * 100) for c in confs]} %")

        # ✓ en la mejor (botón de su esquina) → busca MÁS apariciones parecidas (encuentra la de C)
        rect0 = panel.grid.visualItemRect(panel.grid.item(0))
        ok0, _no0 = panel.grid.itemDelegate().badges(rect0)
        QTest.mouseClick(panel.grid.viewport(), Qt.LeftButton, Qt.NoModifier, ok0.center())
        pump(app, 0.2)
        assert panel.grid.item(0).data(Qt.UserRole + 2) == 1.0, "la marcada ✓ queda al 100 %"
        keys = [(r.media_id, round(r.best)) for r in panel.results]
        assert keys[0] == (a, 7) and any(m == c and 12 <= t <= 16 for m, t in keys), keys
        print(f"✓ con ✓, encontró otra aparición que el texto no veía (en C): {keys[:4]}")

        # ✗ con el botón de la esquina en una de B → se apartan las de B (casi iguales)
        row = next(i for i, r in enumerate(panel.results) if r.media_id == b)
        item = panel.grid.item(row)
        rect = panel.grid.visualItemRect(item)
        _ok, no = panel.grid.itemDelegate().badges(rect)
        QTest.mouseClick(panel.grid.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())
        pump(app, 0.2)
        assert not any(r.media_id == b for r in panel.results), [(r.media_id, r.best) for r in panel.results]
        print("✓ ✗ en una de B (clic en su esquina): se apartan las parecidas")

        # «Saltar» (arriba a la izquierda de la imagen): la esconde sin enseñarle nada a la IA
        row = next((i for i in range(panel.grid.count()) if not panel.grid.item(i).data(Qt.UserRole + 1)), None)
        if row is not None:
            key = panel._mkey(panel.results[row])
            fb0 = IF.load_feedback(QUERY, "videos")
            sr = panel.grid.itemDelegate().skip_rect(panel.grid.visualItemRect(panel.grid.item(row)))
            QTest.mouseClick(panel.grid.viewport(), Qt.LeftButton, Qt.NoModifier, sr.center())
            pump(app, 0.2)
            assert all(panel._mkey(r) != key for r in panel.results), "saltada: ya no se ve"
            fb1 = IF.load_feedback(QUERY, "videos")
            assert len(fb1["pos"]) == len(fb0["pos"]) and len(fb1["neg"]) == len(fb0["neg"]), "no aprende nada"
        print("✓ «Saltar» (esquina superior izquierda) la esconde sin marcarla ✓ ni ✗")

        # se recuerda para la próxima vez
        fb = IF.load_feedback(QUERY, "videos")
        assert fb["pos"] and fb["neg"]
        panel._on_partial(("results", text_hits))
        pump(app, 0.2)
        assert panel.results[0].media_id == a and not any(r.media_id == b for r in panel.results)
        print("✓ al volver a buscar, recuerda lo que marcaste")

        # lo aprendido llega al nombre conocido («Entender mi biblioteca»): ejemplos para el índice
        from editoria.ai import library_understanding as LU
        pos, neg = IF.video_examples(["Jefe Maestro", "Master Chief"])
        assert pos is not None and neg is not None
        data = {m: {"times": t, "vecs": v, "kind": "video", "duration": 20.0, "shots": [[0, 10], [10, 20]]}
                for m, (t, v) in ctrl.clip_vecs.items()}
        ent = LU.Entity("Jefe Maestro", ["Master Chief"])
        hits = LU.build_index([ent], data, {m: "" for m in data}).get("Jefe Maestro", [])
        found = {h.media_id for h in hits}
        assert a in found and c in found and b not in found, [(h.media_id, h.time) for h in hits]
        print("✓ el índice de «Jefe Maestro» usa tus ✓/✗: aparece en A y C, no en B")

        # internet también pregunta (tarjeta)
        web_ranked = [{"id": "x1", "score": 2.0, "hidden": False, "why": "", "mark": ""},
                      {"id": "x2", "score": 0.1, "hidden": False, "why": "", "mark": "pos"},
                      {"id": "x3", "score": 0.3, "hidden": False, "why": "", "mark": ""},
                      {"id": "x4", "score": -2.0, "hidden": False, "why": "", "mark": ""}]
        assert IF.next_question(web_ranked, set()) == "x3"          # con un ✓: la más dudosa (cerca del medio)
        assert IF.next_question([dict(r, mark="") for r in web_ranked], set()) == "x1"   # sin ✓: la mejor
        win.grab().save(os.path.join(out, "momentos_marcas.png"))
        print("✓ en internet la tarjeta elige igual: sin ✓, la mejor; con ✓, la más dudosa")
        win.analyzer.shutdown()
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
    finally:
        if backup is None:
            if os.path.exists(store):
                os.remove(store)
        else:
            with open(store, "w", encoding="utf-8") as f:
                f.write(backup)
    print("TODO OK")


if __name__ == "__main__":
    main()
