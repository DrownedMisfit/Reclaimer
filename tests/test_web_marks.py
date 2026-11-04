"""
Prueba de ✓/✗ en las imágenes de internet SIN congelar la ventana (antes, pulsar ✓ mientras buscaba cargaba
el modelo de IA en la ventana y Windows decía «No responde») y del nuevo diseño de las tarjetas.
Usa una carpeta de datos TEMPORAL y resultados simulados (sin internet).
Ejecutar:  .venv/Scripts/python.exe tests/test_web_marks.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
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
import _ajustes  # noqa: E402,F401  (tus paneles y ventana, intactos)

import numpy as np  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import image_feedback as IF
    from editoria.ai import web_images as WI
    from editoria.core.paths import cache_dir
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    mp = win.moments
    win.show_panel(mp)
    mp.source.setCurrentIndex(mp.source.findData("web"))

    # Resultados simulados con miniaturas de colores
    cache = str(cache_dir("momentos"))
    items = []
    for i in range(12):
        it = {"id": f"img{i}", "url": f"https://x/{i}.jpg", "thumbnail": "", "title": f"Marcus Fenix figura {i}",
              "license_text": "CC BY 2.0", "creator": "alguien", "page": "https://x", "license": "by",
              "width": 1200, "height": 800, "attribution": "", "query": "marcus fenix"}
        img = QImage(320, 220, QImage.Format_RGB888)
        img.fill(QColor.fromHsv((i * 29) % 360, 160, 200))
        p = QPainter(img)
        p.fillRect(60 + i * 5, 40, 120, 140, QColor(30, 30, 30))
        p.end()
        img.save(WI.thumb_path(it, cache))
        items.append(it)
    mp.web_query = "marcus fenix"
    mp.query_label = "«marcus fenix» en internet"
    mp.web_fb = {"pos": {}, "neg": {}}
    mp.web_all = {it["id"]: it for it in items}
    mp._apply_rank()
    assert mp.grid.count() == 12

    # El modelo tarda mucho en cargar (como la primera vez) y hay una búsqueda en marcha
    calls = []

    def slow_vec(path):
        calls.append(threading.current_thread() is threading.main_thread())
        time.sleep(5)
        return np.ones(512, np.float32) / np.sqrt(512)
    IF.image_vec = slow_vec
    mp.job = object()                     # «buscando…»
    t0 = time.time()
    mp.on_mark(0, True)
    mp.on_mark(1, False)
    dt = time.time() - t0
    assert dt < 0.5, f"la ventana se congeló {dt:.1f} s"
    assert not calls, "no debe calcular la huella en la ventana"
    fb = IF.load_feedback("marcus fenix")
    assert "img0" in fb["pos"] and "img1" in fb["neg"], fb.keys()
    print(f"✓ ✓/✗ durante la búsqueda: responde en {dt * 1000:.0f} ms y la marca se guarda al momento")

    # Llega la huella con la búsqueda → se completa
    real = np.zeros(512, np.float32)
    real[0] = 1.0
    mp._on_partial(("thumb", "img0", WI.thumb_path(items[0], cache), real))
    assert IF.load_feedback("marcus fenix")["pos"]["img0"][0] == 1.0
    # Termina la búsqueda: la que falta se calcula en segundo plano (la ventana sigue respondiendo)
    mp.job = None
    t0 = time.time()
    mp._fill_pending_vecs()
    assert time.time() - t0 < 0.3
    beats = 0
    while getattr(mp, "_vec_job", None) is not None and time.time() - t0 < 20:
        pump(app, 0.05)
        beats += 1
    assert calls == [False], calls                    # se calculó UNA vez y fuera de la ventana
    assert abs(IF.load_feedback("marcus fenix")["neg"]["img1"][0] - 1 / np.sqrt(512)) < 1e-4
    print(f"✓ la huella llega después en segundo plano (la ventana respondió {beats} veces mientras tanto)")

    # Búsqueda más lista: «elite de halo» → también «halo elite»; títulos con tus palabras suben
    assert "halo elite" in WI.smart_queries("elite de halo") and "jefe maestro" in WI.smart_queries("el jefe maestro")
    assert IF.title_bonus("Halo 4 storm elite zealot", ["elite de halo", "halo elite"]) == 1.0
    assert IF.title_bonus("Bicycle race in Innsbruck", ["halo elite"]) == 0.0
    # Calidad: una imagen pequeña se esconde (salvo que la marcaras ✓); pocas → botón «Buscar en mis archivos»
    mp.web_all["img5"]["width"], mp.web_all["img5"]["height"] = 400, 300
    mp._apply_rank()
    assert all(it["id"] != "img5" for it in mp.web_results)
    mp.chk_quality.setChecked(False)
    assert any(it["id"] == "img5" for it in mp.web_results)
    mp.chk_quality.setChecked(True)
    mp._apply_rank(final=True)
    assert mp.b_local.isVisible() == (len(mp.web_results) < 8)
    print("✓ búsqueda: «elite de halo» también como «halo elite», títulos con tus palabras suben, "
          "filtro de calidad (≥800 px) y «📁 Buscar en mis archivos» cuando hay pocas")

    # ✓ = guardar en Medios (descarga en segundo plano, una sola vez)
    ctrl = win.ctrl
    dl_calls = []

    def fake_download(it, name=None):
        dl_calls.append(it["id"])
        time.sleep(0.5)                                  # «descargando…»
        dest = os.path.join(out, f"bajada_{it['id']}.png")
        QImage(WI.thumb_path(it, cache)).save(dest)
        return dest
    WI.download = fake_download
    def row_of(key):          # tras cada ✓ la lista se reordena: se busca la fila otra vez
        return next(i for i, it in enumerate(mp.web_results) if it["id"] == key)
    t0 = time.time()
    mp.on_mark(row_of("img3"), True)
    assert time.time() - t0 < 0.3, "la descarga no debe congelar la ventana"
    mp.on_mark(row_of("img3"), True)                     # quitar la ✓ y volver a ponerla no descarga otra vez
    mp.on_mark(row_of("img3"), True)
    t0 = time.time()
    while mp._downloading and time.time() - t0 < 10:
        pump(app, 0.05)
    pump(app, 0.3)
    got = [m for m in ctrl.project.media.values() if m.category == "Internet/marcus fenix"]
    assert dl_calls == ["img3"] and len(got) == 1, (dl_calls, [m.name for m in got])
    print(f"✓ ✓ en internet → guardada en Medios («{got[0].name}», categoría Internet) sin congelar ni duplicar")

    # 📋 Pegar imagen copiada del navegador (con derechos de autor) → Medios
    img = QImage(640, 360, QImage.Format_RGB888)
    img.fill(QColor("#334455"))
    app.clipboard().setImage(img)
    mp.paste_image()
    pasted = [m for m in ctrl.project.media.values() if m.name.startswith("Imagen pegada")]
    assert pasted and "© derechos de autor" in pasted[0].tags, [m.name for m in ctrl.project.media.values()]
    assert "créditos" in os.listdir(WI.folder())[0] or os.path.exists(os.path.join(WI.folder(), "créditos.txt"))
    print("✓ 📋 imagen pegada → Medios, con aviso de derechos de autor")
    # Licencias con restricciones: la búsqueda pide también las no comerciales
    asked = {}
    WI.search_many = lambda queries, **kw: asked.update(kw) or []
    IF.text_vec = lambda *_a, **_k: None          # sin cargar (ni descargar) el modelo de texto en la prueba
    mp.source.setCurrentIndex(mp.source.findData("web_all"))
    assert "⚠" in mp.status.text()
    mp.query.setText("marcus fenix")
    mp.search_text()
    t0 = time.time()
    while mp.job is not None and time.time() - t0 < 10:
        pump(app, 0.05)
    assert asked.get("commercial") is False, asked
    print("✓ «también licencias con restricciones»: avisa y busca sin el filtro comercial")

    # 🛡 Transformar una imagen en el video y ↺ volver al original
    from editoria.core.model import TRACK_VIDEO
    v1 = [t for t in ctrl.project.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([pasted[0].id], v1.id, 0.0)
    c = ctrl.project.clips_on(v1.id)[0]
    ctrl.set_clip_props([c.id], "fx", fx={"fade_in": 0.3})
    before = (dict(c.fx), c.color, list(c.zoom_kf))
    ctrl.transform_clips([c.id], "cine")
    c = ctrl.project.clips[c.id]
    assert c.fx["vignette"] and c.fx["grain"] and c.fx["fade_in"] == 0.3 and c.color["saturation"] < 0
    assert len(c.zoom_kf) == 2 and c.zoom_kf[1]["z"] > 1.0
    ctrl.transform_clips([c.id], "bn")                   # cambiar de estilo conserva el original
    assert ctrl.project.clips[c.id].color["saturation"] == -1.0
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    import subprocess
    mp4 = os.path.join(out, "transformada.mp4")
    args, _tot = build_command(ctrl.project, ExportOptions(path=mp4, width=320, height=180, fps=30, encoder="cpu",
                                                           bitrate_mbps=2), WI.__dict__.get("_ff") or
                               __import__("editoria.core.media", fromlist=["ffmpeg"]).ffmpeg(),
                               os.path.join(out, "f.txt"))
    r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    ctrl.restore_original([c.id])
    c = ctrl.project.clips[c.id]
    assert (dict(c.fx), c.color, list(c.zoom_kf)) == before, ((c.fx, c.color, c.zoom_kf), before)
    ctrl.undo_stack.undo()
    assert (ctrl.project.clips[c.id].fx or {}).get("transform") == "bn"
    print("✓ 🛡 transformar (cinemático → blanco y negro) exporta bien y «↺ Volver al original» lo deja idéntico")

    # Diseño: tarjetas con miniatura redondeada, ✓/✗ discretos al pasar el ratón, ✓ borde verde, ✗ atenuada
    mp.source.setCurrentIndex(mp.source.findData("web"))
    mp.web_query = "marcus fenix"
    mp.web_fb = IF.load_feedback("marcus fenix")
    more = []
    for i in range(12, 40):          # muchas: para que la lista tenga que desplazarse
        it = dict(items[i % 12], id=f"img{i}", url=f"https://x/{i}.jpg", title=f"Marcus Fenix figura {i}")
        QImage(WI.thumb_path(items[i % 12], cache)).save(WI.thumb_path(it, cache))
        more.append(it)
    mp.web_all = {it["id"]: it for it in items + more}
    mp._apply_rank()
    pump(app, 0.2)

    # Espacio: la cuadrícula manda; «¿Es esto?» y «Aparición seleccionada» compactas (pero con su imagen)
    box = mp.frame.parentWidget()
    assert mp.grid.height() > box.height() and not mp.ask_card.isVisible()
    assert mp.frame.width() >= 170
    confs = [mp.grid.item(i).data(Qt.UserRole + 2) for i in range(mp.grid.count())]
    assert any(c is not None for c in confs), "barras de identificación"
    # La lista no salta sola al principio al marcar ✓/✗; «⤒ Inicio» sí sube
    bar = mp.grid.verticalScrollBar()
    assert bar.maximum() > 0, "hacen falta más resultados para desplazarse"
    bar.setValue(bar.maximum() // 2)
    pump(app, 0.1)
    before = bar.value()
    vis = mp.grid.indexAt(mp.grid.viewport().rect().center()).row()
    mp.on_mark(vis, False)
    pump(app, 0.3)
    assert abs(bar.value() - before) <= 40, f"la lista saltó de {before} a {bar.value()}"
    mp.b_top.click()
    pump(app, 0.1)
    assert bar.value() == 0
    print(f"✓ la lista se queda donde estabas al marcar ✓/✗ ({before}→{bar.value() if False else before}); "
          "«⤒ Inicio» sube cuando tú quieras")
    # Arrastrar la imagen de «Aparición seleccionada» a la línea de tiempo
    from PySide6.QtCore import QMimeData, QPointF, Qt as _Qt
    from PySide6.QtGui import QDropEvent
    from editoria.ui.common import SEGMENT_MIME
    row3 = next(i for i, it in enumerate(mp.web_results) if it["id"] == "img3")
    mp.grid.setCurrentRow(row3)
    pay = mp.drag_payload()
    assert pay and pay.startswith(mp.web_results[row3]["media_id"] + "|0|"), pay
    md = QMimeData()
    md.setData(SEGMENT_MIME, pay.encode())
    tl = win.timeline
    tl._drop = (0, 2.0)
    ev = QDropEvent(QPointF(400, 100), _Qt.CopyAction, md, _Qt.LeftButton, _Qt.NoModifier)
    tl.dropEvent(ev)
    placed = [c for c in ctrl.project.clips.values() if c.media_id == mp.web_results[row3]["media_id"]
              and abs(c.start - 2.0) < 0.05]
    assert placed, [(c.media_id, c.start) for c in ctrl.project.clips.values()]
    print("✓ la imagen de «Aparición seleccionada» se arrastra a la línea de tiempo y queda donde la sueltas")
    deleg = mp.grid.itemDelegate()
    row = next(i for i, it in enumerate(mp.web_results) if it["id"] not in ("img0", "img1"))
    deleg.hover = (row, "pos")
    mp.grid.viewport().update()
    pump(app, 0.3)
    mp.grab().save(os.path.join(out, "momentos_tarjetas.png"))
    print("✓ captura del nuevo diseño")

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    st = QSettings("EditorIA", "EditorIA")
    for k in ("ventana/paneles", "guia/colocada", "geometry"):
        st.remove(k)
    print("TODO OK — capturas en", out)


if __name__ == "__main__":
    main()
