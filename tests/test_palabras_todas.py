"""
🔑 Palabras clave → «📍 Todas»: marcas de TODAS las palabras clave en la línea de tiempo; la elegida, resaltada (las
demás atenuadas); 🧭 ◀ / ▶ (anterior / siguiente al cabezal) y ⇢ más cercana / más lejana.
También: 🔎 Buscar no se atenúa, ✕ con «Todas», clic en muescas, tope de marcas.
Ejecutar:  .venv/Scripts/python.exe tests/test_palabras_todas.py <carpeta_salida>
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_palabras_todas")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    app.processEvents()
    cl, tl = win.clips, win.timeline
    from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, new_id
    p = win.ctrl.project                          # (un clip de 60 s: el cabezal puede ir a cualquier segundo)
    m = MediaItem(new_id(), os.path.join(_TMP, "falso.mp4"), KIND_VIDEO, "falso", duration=60.0, width=1280,
                  height=720, probed=True)
    p.media[m.id] = m
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    c = Clip(new_id(), m.id, v1.id, 0.0, 0.0, 60.0)
    p.clips[c.id] = c
    win.ctrl.project_changed.emit()
    app.processEvents()
    def h(t):
        return {"tl": t, "src": t, "context": f"… frase en el segundo {t:.0f} …", "media_id": ""}
    cl.menciones = [{"term": "La ciudad", "hits": [h(3.0), h(21.0), h(40.0)]},
                    {"term": "El río", "hits": [h(12.0), h(30.0)]}]
    cl.mencion = None
    cl.btn_todas.setChecked(False)
    cl._elegir_mencion(0, buscar=False)
    app.processEvents()
    assert [w for _t, w in tl.hint_marks] == ["🎬 La ciudad"] * 3, tl.hint_marks
    print("✓ sin «📍 Todas»: solo las marcas de la palabra elegida")
    cl.btn_todas.setChecked(True)
    app.processEvents()
    palabras = {tl.hint_word(w) for _t, w in tl.hint_marks}
    assert palabras == {"La ciudad", "El río"} and len(tl.hint_marks) == 5, tl.hint_marks
    assert tl.hint_focus == "La ciudad" and tl._hint_dim("🎬 El río") and not tl._hint_dim("🎬 La ciudad")
    tl.grab().save(os.path.join(out, "todas.png"))
    print("✓ «📍 Todas»: las 5 marcas de las 2 palabras; la elegida resaltada, la otra atenuada")
    cl._elegir_mencion(1, buscar=False)
    assert tl.hint_focus == "El río"
    print("✓ elegir otra palabra: se resaltan las suyas")

    # 🧭 navegación con la palabra «La ciudad» (3, 21, 40) y el cabezal en 10
    cl._elegir_mencion(0, buscar=False)
    cl.al_cabezal(10.0)
    assert cl.btn_cerca.text().endswith("00:03") or "0:03" in cl.btn_cerca.text(), cl.btn_cerca.text()
    assert "0:40" in cl.btn_lejos.text(), cl.btn_lejos.text()
    cl._ir_vecina(1)
    app.processEvents()
    assert abs(win.engine.time - 21.0) < 0.01 and abs(cl.cabezal - 21.0) < 0.01, win.engine.time
    cl._ir_vecina(-1)
    app.processEvents()
    assert abs(win.engine.time - 3.0) < 0.01, win.engine.time
    cl._ir_extremo(cerca=False)
    app.processEvents()
    assert abs(win.engine.time - 40.0) < 0.01, win.engine.time
    assert not cl.btn_sig.isEnabled() and cl.btn_ant.isEnabled(), "en la última no hay siguiente"
    print("✓ 🧭 ▶ siguiente, ◀ anterior, ⇢ más cercana / más lejana; los botones se apagan en los extremos")
    # «más cercana» no cuenta la que está justo en el cabezal
    cl.al_cabezal(21.0)
    cl._act_nav()
    assert "00:03" in cl.btn_cerca.text(), cl.btn_cerca.text()
    print("✓ «más cercana» no cuenta la del cabezal")

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from editoria.ui.hint_marks import set_source as marcas_set

    def clic(pos):
        ev = QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        tl.mousePressEvent(ev)
        app.processEvents()

    # 🔎 Buscar: sus marcas nunca se atenúan (ni con «📍 Todas» ni sin él)
    cl.btn_todas.setChecked(True)
    cl._elegir_mencion(0, buscar=False)
    marcas_set(tl, "buscar", [(50.0, "🔎 El río")])
    app.processEvents()
    assert tl.hint_focus == "La ciudad" and not tl._hint_dim("🔎 El río") and tl._hint_dim("🎬 El río")
    i50 = next(k for k, (t, _l) in enumerate(tl.hint_marks) if t == 50.0)
    assert not tl._hint_notch(i50)
    cl.btn_todas.setChecked(False)
    app.processEvents()
    assert tl.hint_focus == "", "sin «📍 Todas» no se atenúa nada"
    assert any(l == "🔎 El río" for _t, l in tl.hint_marks)
    marcas_set(tl, "buscar", [])
    print("✓ las marcas de 🔎 Buscar no se atenúan; sin «📍 Todas», ningún foco")

    # clic en una muesca pegada a una banderita resaltada: gana la que se ve
    cl.btn_todas.setChecked(True)
    cl._elegir_mencion(0, buscar=False)
    app.processEvents()
    tl.fit()                                  # (los 60 s a la vista)
    print("  ancho de la línea:", tl.width(), "px/s:", round(tl.pps, 2))
    x21 = tl.x_for(21.0)
    t_pegada = tl.t_for(x21 + 12)
    cl.menciones[1]["hits"].append(h(t_pegada))
    cl._marcas()
    app.processEvents()
    i21 = next(k for k, (t, l) in enumerate(tl.hint_marks) if t == 21.0 and l == "🎬 La ciudad")
    ip = next(k for k, (t, l) in enumerate(tl.hint_marks) if abs(t - t_pegada) < 1e-6)
    assert tl._hint_rect(i21) is not None and tl._hint_rect(ip) is not None
    assert tl._hint_notch(ip) and not tl._hint_notch(i21)
    pos = QPointF(tl.x_for(t_pegada) + 2, tl.TOPIC_H + 10)
    assert tl._hint_rect(i21).contains(pos), "la muesca debe quedar dentro de la banderita"
    assert tl.hint_mark_at(pos) == i21, (tl.hint_mark_at(pos), i21, ip)
    i12 = next(k for k, (t, _l) in enumerate(tl.hint_marks) if t == 12.0)
    pos12 = QPointF(tl.x_for(12.0) + 2, tl.TOPIC_H + 10)
    assert tl.hint_mark_at(pos12) == i12
    lejos = QPointF(tl.x_for(12.0) + 30, tl.TOPIC_H + 10)            # (donde iría su texto invisible: nada)
    assert tl.hint_mark_at(lejos) != i12
    snap = [t for t, _q in tl._snap_points(set()) if _q == "marca"]
    assert 21.0 in snap and 12.0 not in snap, "el imán no se pega a las atenuadas"
    tl.select_hint(-1)
    tgt = tl.keyword_target(21.0 + (t_pegada - 21.0) / 2, near=1.0)
    assert tgt and tgt["word"] == "La ciudad", tgt
    print("✓ clic junto a la banderita resaltada: gana la visible; la muesca sola responde; imán y "
          "«Añadir en…» sin las atenuadas")

    # clic en una muesca → «Dijiste…» pasa a esa palabra
    for m_ in cl.menciones:
        m_["count"] = len(m_["hits"])
    cl._pintar_menciones(cl.mencion["term"])  # (la lista «Dijiste…» con las dos palabras)
    clic(pos12)
    assert cl.mencion["term"] == "El río" and cl.lista_menciones.currentItem().text().startswith("El río")
    assert tl.hint_focus == "El río" and abs(win.engine.time - 12.0) < 0.01, (tl.hint_focus, win.engine.time)
    assert tl.hint_marks[tl.hint_selected][0] == 12.0
    print("✓ clic en una muesca atenuada: la lista pasa a esa palabra y el cabezal va ahí")

    # ✕ con «📍 Todas»: se apaga y no vuelven solas
    marcas_set(tl, "buscar", [(50.0, "🔎 El río")])
    cl._quitar_marcas()
    app.processEvents()
    assert not cl.btn_todas.isChecked() and tl.hint_focus == ""
    assert tl.hint_marks == [(50.0, "🔎 El río")], tl.hint_marks
    cl._elegir_mencion(0, buscar=False)
    assert tl.hint_marks == [(50.0, "🔎 El río")], "tras ✕ no deben volver solas"
    marcas_set(tl, "buscar", [])
    print("✓ ✕ con «📍 Todas»: lo apaga, quita las marcas y no vuelven solas (las de 🔎 se quedan)")

    # palabra elegida sin momentos con hora → se recorren todas
    cl.menciones.append({"term": "Sin hora", "hits": [], "no_dicha": True})
    cl._elegir_mencion(2, buscar=False)
    assert cl._tiempos_nav() and 40.0 in cl._tiempos_nav() and 12.0 in cl._tiempos_nav()
    assert "ahora, todas" in cl.btn_sig.toolTip(), cl.btn_sig.toolTip()
    print("✓ palabra sin momentos con hora: ◀ ▶ recorren todas")

    # tope: todas las de la elegida + el resto repartido por todo el video
    cl.MAX_MARCAS = 60
    cl.menciones = [{"term": "Elegida", "hits": [h(1.0 + k * 0.5) for k in range(40)]}]
    for n in range(3):
        cl.menciones.append({"term": f"Otra {n}", "hits": [h(0.2 + n * 0.05 + k * 0.6) for k in range(100)]})
    cl.mencion = None
    cl.btn_todas.setChecked(True)
    cl._elegir_mencion(0, buscar=False)
    app.processEvents()
    assert len(tl.hint_marks) == 60, len(tl.hint_marks)
    mias = [t for t, l in tl.hint_marks if l == "🎬 Elegida"]
    otras = sorted(t for t, l in tl.hint_marks if l != "🎬 Elegida")
    assert len(mias) == 40 and len(otras) == 20, (len(mias), len(otras))
    assert otras[0] < 1.0 and otras[-1] > 58.0, (otras[0], otras[-1])
    huecos = [b - a for a, b in zip(otras, otras[1:])]
    assert max(huecos) < 6.0, huecos
    assert "Hay 340 marcas" in cl.aviso.text(), cl.aviso.text()
    k0 = next(k for k, (_t, l) in enumerate(tl.hint_marks) if l == "🎬 Elegida")
    tl.select_hint(k0)
    assert len(tl.keyword_target(None)["times"]) == 40
    cl.MAX_MARCAS = 800
    cl._marcas()
    assert len(tl.hint_marks) == 340 and "Hay" not in cl.aviso.text()
    tl.grab().save(os.path.join(out, "tope.png"))
    print("✓ tope: todas las de la elegida, el resto repartido por todo el video y aviso; «Añadir en…» las ve todas")

    cl.btn_todas.setChecked(False)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
