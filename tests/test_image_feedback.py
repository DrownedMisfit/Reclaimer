"""
Prueba del buscador de imágenes que aprende: orden por parecido (IA local), esconder las que no son,
✓ «esta es» (suben las parecidas) y ✗ «no es» (se quitan las casi iguales), con clics en los botones de la
esquina de cada imagen, «Buscar más como las ✓» y que lo recuerde. Sin internet (búsqueda simulada).
Ejecutar:  .venv/Scripts/python.exe tests/test_image_feedback.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.ai import image_feedback as IF  # noqa: E402
from editoria.ai import web_images as WI  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402

QUERY = "prueba reclaimer coche rojo"


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    ff = media_tools.ffmpeg()
    imgs = {}
    specs = [("rojo", "red", 6), ("azul", "blue", 6)]
    for name, col, n in specs:
        for i in range(n):
            p = os.path.join(out, f"{name}{i}.jpg")
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"color=c={col}:s=320x240,drawbox=x={20 + i * 8}:y=60:w=200:h=90:c=black@0.6:t=fill",
                            "-frames:v", "1", p], check=True)
            imgs[f"{name}{i}"] = p
    for i in range(3):
        p = os.path.join(out, f"ruido{i}.jpg")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"cellauto=s=320x240:rule={30 + i * 20}",
                        "-frames:v", "1", p], check=True)
        imgs[f"ruido{i}"] = p
    order = [f"ruido{i}" for i in range(3)] + [f"azul{i}" for i in range(6)] + [f"rojo{i}" for i in range(6)]

    def fake_item(k, q):
        return {"title": f"{k} car photo", "url": f"https://x/{k}.jpg", "thumbnail": f"https://x/t_{k}.jpg",
                "license": "cc0", "license_text": "CC0", "creator": "prueba", "page": "https://x", "attribution": "",
                "width": 320, "height": 240, "id": f"id_{k}", "query": q}

    calls = []

    def fake_many(queries, pages=3, seen=None, cancelled=None, **_kw):
        calls.append(list(queries))
        seen = set(seen or ())
        return [fake_item(k, queries[0]) for k in order if f"id_{k}" not in seen]

    def fake_fetch(url, dest, timeout=30, limit=0):
        k = url.rsplit("/", 1)[1].replace("t_", "").replace(".jpg", "")
        shutil.copy(imgs[k], dest)
        return dest
    WI.search_many, WI.fetch = fake_many, fake_fetch

    store = IF._store_path()
    backup = open(store, encoding="utf-8").read() if os.path.exists(store) else None
    try:
        app = QApplication(sys.argv)
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.resize(1600, 950)
        win.show()
        panel = win.moments
        win.show_panel(panel)
        panel.source.setCurrentIndex(panel.source.findData("web"))
        panel.chk_quality.setChecked(False)   # sus imágenes de prueba son pequeñas (320×240)
        cache = str(__import__("editoria.core.paths", fromlist=["cache_dir"]).cache_dir("momentos"))
        for k in order:                                  # miniaturas limpias para la prueba
            th = WI.thumb_path(fake_item(k, ""), cache)
            if os.path.exists(th):
                os.remove(th)

        def run_search(more=False):
            if more:
                panel.b_more.click()
            else:
                panel.query.setText(QUERY)
                panel.search_text()
            t0 = time.time()
            while panel.job is not None and time.time() - t0 < 120:
                pump(app, 0.1)
            pump(app, 0.3)

        run_search()
        keys = [it["id"][3:] for it in panel.web_results]
        assert len(panel.web_all) == 15 and panel.web_tvec is not None
        reds = [i for i, k in enumerate(keys) if k.startswith("rojo")]
        blues = [i for i, k in enumerate(keys) if k.startswith("azul")]
        assert reds and (not blues or sum(reds) / len(reds) < sum(blues) / len(blues)), keys
        print(f"✓ orden por parecido a «coche rojo»: primero {keys[:3]}; escondidas: "
              f"{15 - len(panel.web_results)}")

        def click_badge(key: str, good: bool):
            row = next(i for i, it in enumerate(panel.web_results) if it["id"] == f"id_{key}")
            item = panel.grid.item(row)
            panel.grid.scrollToItem(item)
            pump(app, 0.1)
            rect = panel.grid.visualItemRect(item)
            ok, no = panel.grid.itemDelegate().badges(rect)
            target = (ok if good else no).center()
            QTest.mouseClick(panel.grid.viewport(), Qt.LeftButton, Qt.NoModifier, target)
            pump(app, 0.2)

        # ✓ en una azul: las azules suben arriba
        before_sel = panel.grid.currentRow()
        click_badge("azul0", True)
        top = [it["id"][3:] for it in panel.web_results[:6]]
        assert top[0] == "azul0" and sum(k.startswith("azul") for k in top) >= 5, top
        assert panel.grid.item(0).data(Qt.UserRole + 1) == "pos"
        print(f"✓ ✓ en una azul (clic en el botón de su esquina): las azules suben → {top}")

        # ✗ en una roja: esa y las casi iguales desaparecen
        click_badge("rojo0", False)
        left = [it["id"][3:] for it in panel.web_results]
        assert "rojo0" not in left and sum(k.startswith("rojo") for k in left) <= 1, left
        panel.chk_hidden.setChecked(True)
        assert any(it["id"] == "id_rojo0" for it in panel.web_results)
        panel.chk_hidden.setChecked(False)
        print(f"✓ ✗ en una roja: se quita y también las casi iguales (quedan {len(left)}; «Mostrar las escondidas» "
              "las enseña)")

        # pulsar otra vez ✓ quita la marca
        click_badge("azul0", True)
        assert "id_azul0" not in panel.web_fb["pos"]
        panel.chk_hidden.setChecked(True)       # sin ✓, una azul ya no parece «coche rojo»: queda escondida
        click_badge("azul0", True)
        panel.chk_hidden.setChecked(False)
        assert "id_azul0" in panel.web_fb["pos"]

        # se recuerda: buscar otra vez lo mismo
        fb = IF.load_feedback(QUERY)
        assert "id_azul0" in fb["pos"] and "id_rojo0" in fb["neg"]
        panel.web_all = {}
        run_search()
        assert panel.web_results[0]["id"] == "id_azul0" and all(it["id"] != "id_rojo0" for it in panel.web_results)
        print("✓ se recuerda: al volver a buscar lo mismo, las ✓ arriba y las ✗ fuera")

        # «Buscar más como las ✓» añade búsquedas a partir de las marcadas
        run_search(more=True)
        assert calls[-1] and any("azul0" in q or "car" in q for q in calls[-1]), calls[-1]
        win.grab().save(os.path.join(out, "imagenes.png"))
        print(f"✓ «✨ Buscar más como las ✓» busca también: {calls[-1][:2]}")
        win.analyzer.shutdown()
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
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
