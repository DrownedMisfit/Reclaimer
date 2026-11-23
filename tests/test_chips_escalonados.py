"""
🔑 PRUEBA de la fase 0 de la línea de tiempo (20/11): palabras clave escalonadas.

Las banderitas «Dijiste…» y los chips ⚡ de la regla se reparten en hasta 4 filas (la regla crece lo que haga falta y
todo lo de debajo baja eso mismo); si ni así caben, un chip «+N» los agrupa y su menú deja elegirlos. Comprueba:
  · 4 chips en el mismo segundo → 4 filas sin solaparse y la regla con el alto de 4 filas;
  · 6 chips → 4 filas + «+2», y el menú del «+2» elige bien (también una banderita) y trae «✂ Separar…» y
    «🔗 Unir con…» para cada término; el menú del chip también;
  · sin choques → 1 fila (la regla de siempre);
  · desplazar no cambia las filas; al cambiar de zoom el alto cambia con una transición corta (sin saltos atrás);
  · clic real en cada chip lo elige; resalte y tooltip (término entero y su tiempo) al pasar el ratón;
  · con 4 filas, clips y cabeceras siguen alineados: un clic en un clip lo elige y el cabezal va donde pulsas;
  · (retoques de Fable) los códigos de tiempo tienen su franja propia: ningún chip los tapa; la banderita elegida nunca
    queda escondida en un «+N»; solo con el panel muy bajo (< 150 px y sin sitio para pista y media) 2 filas y «+N».
Ejecutar:  .venv/Scripts/python.exe tests/test_chips_escalonados.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time


# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

# una pantalla de prueba de 1920×1080 (como test_barra_sin_cortes): sin ella la «offscreen» mide ~800–1000 px, la
# ventana no llega a 1600 y los chips de 0:05–0:25 a 30 px/s quedaban fuera de la línea de tiempo
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_chips_{os.getpid()}.json"
with open(os.path.join(_RAIZ, _CFG), "w", encoding="utf-8") as _f:
    _f.write('{"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, '
             '"dpr": 1}]}')
__import__("atexit").register(lambda: os.path.exists(os.path.join(_RAIZ, _CFG)) and os.remove(os.path.join(_RAIZ, _CFG)))
os.chdir(_RAIZ)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

QMenu.exec = lambda self, *a: None          # (ningún menú se queda abierto esperando)


def _vigilante(segundos: float = 420.0):
    """Si la prueba se cuelga (un diálogo o un menú de verdad), sale sola y libera el turno."""
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta (¿un menú o un diálogo esperando?)", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()

AVAIL = ["gameplay", "cinematic", "none"]
NOMBRES = ["Mundo abierto", "La ciudad", "Personaje", "Consola nueva", "El río", "Otra saga"]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def kw(t, k, nombre=None):
    return {"t": t, "term": nombre or NOMBRES[k % len(NOMBRES)], "kind": "gameplay", "key": f"k{k}",
            "avail": AVAIL, "dur": 3.0}


def disjuntos(rects):
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i].intersects(rects[j]), ("se tapan", i, j, rects[i], rects[j])


def real(tl, r):
    """Centro de un rectángulo de la regla en coordenadas reales del widget (la regla va fija arriba de lo visible)."""
    return (r.center() + QPointF(0, tl._vt())).toPoint()


def mover(tl, pt: QPoint):
    ev = QMouseEvent(QEvent.MouseMove, QPointF(pt), QPointF(tl.mapToGlobal(pt)), Qt.NoButton, Qt.NoButton,
                     Qt.NoModifier)
    tl.mouseMoveEvent(ev)


def textos_menu(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "chips_escalonados")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from PySide6.QtCore import QSettings
    _st = QSettings("EditorIA", "EditorIA")      # (nada de la ventana del usuario: distribución de fábrica,
    for _k in ("ventana/paneles", "geometry"):    #  sin «A todo el alto»: la línea de tiempo a todo el ancho)
        _st.remove(_k)
    _st.setValue("ventana/biblioteca_alto", "false")
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    pump(app, 1.0)
    tl = win.timeline
    # (sin carpetas de palabras clave, el ⚡ de verdad vaciaría estas marcas de prueba al cambiar algo: fuera)
    ka = win.kw_arranger
    tl.kw_kind_requested.disconnect(ka._kind)
    ka._timer.timeout.disconnect()
    tl.set_kw_visible(True)
    sa = tl._scroll_area()
    vh_real = sa.viewport().height() if sa is not None else tl.height()
    print(f"  (alto visible de la línea de tiempo en esta ventana: {vh_real} px; tope de filas {tl._filas_tope()})")
    tl.CHIP_PANEL_BAJO = 0                  # (las partes 1–8 con las 4 filas; el panel bajo se prueba en la 10)
    tl._revisar_alto_visible()
    tl.pps, tl.scroll = 30.0, 0.0
    tl._update_scrollbar()
    assert tl.RULER_H == tl._regla_base() == round(tl.RULER_BASE * tl.ui_k), "sin chips: la regla de siempre"
    paso = tl._chip_alto() + tl._chip_hueco()
    pedidos, saltos = [], []
    tl.kw_kind_requested.connect(lambda keys, kind: pedidos.append((list(keys), kind)))
    tl.seek_requested.connect(lambda t: saltos.append(float(t)))

    # 1) sin choques → 1 fila, la regla de siempre
    tl.set_hint_marks([])
    tl.set_kw_marks([kw(5.0 + 10 * k, k) for k in range(3)])
    pump(app, 0.2)
    base = tl._regla_base()                 # (con chips: + la franja propia de los tiempos)
    assert base == round(tl.RULER_BASE * tl.ui_k) + round(13 * tl.ui_k), base
    assert tl.chips_filas_n() == 1 and tl.RULER_H == base, (tl.chips_filas_n(), tl.RULER_H, base)
    rs = [tl._kw_rect(i)[0] for i in range(3)]
    assert len({round(r.top()) for r in rs}) == 1
    print(f"✓ sin chips, la regla de siempre ({round(tl.RULER_BASE * tl.ui_k)} px); sin choques, 1 fila ({base} px con la "
          "franja propia de los tiempos)")

    def tiempos_libres(n):
        fm = QFontMetrics(tl._f(8))
        caja = fm.tightBoundingRect("00:00:00:00 💥 drop")
        arriba, abajo = tl._tiempos_y() + caja.top(), tl._tiempos_y() + caja.bottom()
        assert tl._chip_y(n - 1) + tl._chip_alto() <= arriba, ("un chip tapa los tiempos", n, arriba)
        assert abajo <= tl.RULER_H - 12 + 1, ("los tiempos pisan las rayitas", abajo, tl.RULER_H)
        return arriba, abajo
    a1, b1 = tiempos_libres(1)

    # 2) 4 chips en el mismo segundo → 4 filas sin solaparse; la regla con el alto de 4 filas
    tl.set_kw_marks([kw(5.0, k) for k in range(4)])
    pump(app, 0.2)
    rs = [tl._kw_rect(i)[0] for i in range(4)]
    assert all(r is not None for r in rs), rs
    disjuntos(rs)
    assert len({round(r.top()) for r in rs}) == 4, "cuatro filas"
    assert tl.chips_filas_n() == 4 and tl.RULER_H == base + 3 * paso, (tl.chips_filas_n(), tl.RULER_H)
    assert all(r.top() >= tl.TOPIC_H and r.bottom() <= tl.RULER_H for r in rs), "ni temas ni pistas"
    assert all(tl._kw_rect(i)[1].endswith(NOMBRES[i]) for i in range(4)), "con su texto entero"
    assert not tl._chips_filas()[2], "sin «+N»"
    tl.repaint()
    tl.grab().copy(0, 0, 900, 260).save(os.path.join(out, "chips_4.png"))
    print(f"✓ 4 chips juntos: 4 filas sin solaparse, enteros, y la regla crece a {tl.RULER_H} px")
    a4, b4 = tiempos_libres(4)
    print(f"✓ los códigos de tiempo van en su franja propia (y {a1:.0f}–{b1:.0f} con 1 fila; {a4:.0f}–{b4:.0f} con 4): "
          "ningún chip los tapa ni pisan las rayitas")

    # 3) desplazar no cambia filas
    tops = [r.top() for r in rs]
    tl.scroll = 2.0
    assert [tl._kw_rect(i)[0].top() for i in range(4)] == tops and tl.RULER_H == base + 3 * paso
    tl.scroll = 0.0
    print("✓ desplazar no cambia las filas ni el alto de la regla")

    # 4) clic real en cada chip lo elige (el tipo siguiente) y la banderita queda elegida
    for i in range(4):
        pedidos.clear()
        QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, real(tl, tl._kw_rect(i)[0]))
        pump(app, 0.05)
        assert pedidos == [([f"k{i}"], "cinematic")], (i, pedidos)
    tl.set_hint_marks([(5.0, "🎬 La ciudad")])
    pump(app, 0.1)
    rh = tl._hint_rect(0)
    assert rh is not None
    disjuntos([rh] + [tl._kw_rect(i)[0] for i in range(4) if tl._kw_rect(i)[0] is not None])
    saltos.clear()
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, real(tl, rh))
    pump(app, 0.05)
    assert tl.hint_selected == 0 and saltos and abs(saltos[-1] - 5.0) < 1e-6, (tl.hint_selected, saltos)
    tl.select_hint(-1)
    # zona de clic más alta: un píxel por encima y por debajo del chip también vale
    r0 = tl._kw_rect(0)[0] if tl._kw_rect(0)[0] is not None else None
    if r0 is not None:
        assert tl.kw_mark_at(QPointF(r0.center().x(), r0.bottom() + 1)) == 0
    print("✓ clic real en cada chip ⚡ cambia su tipo; en la banderita, la elige y lleva el cabezal ahí")

    # 5) resalte y tooltip al pasar el ratón
    tl.set_hint_marks([])
    pump(app, 0.1)
    r2 = tl._kw_rect(2)[0]
    mover(tl, real(tl, r2))
    assert tl._chip_hover == ("kw", 2), tl._chip_hover
    tip = tl.toolTip()
    assert NOMBRES[2] in tip and "00:00:05" in tip, tip
    mover(tl, QPoint(tl.HEADER_W + 600, int(tl._vt() + tl.RULER_H + 30)))
    assert tl._chip_hover is None
    print(f"✓ al pasar el ratón: resalte y tooltip «{tip.splitlines()[0]}»")

    # 6) 6 chips → 4 filas + «+2»; su menú elige bien (también una banderita) y trae Separar / Unir con
    tl.set_kw_marks([kw(5.0, k) for k in range(5)])
    tl.set_hint_marks([(5.0 + 2.0 / tl.pps, "🎬 Otra saga")])
    pump(app, 0.2)
    grupos = tl._chips_filas()[2]
    assert len(grupos) == 1 and grupos[0]["texto"] == "+2", grupos
    assert set(grupos[0]["items"]) == {("kw", 4), ("hint", 0)}, grupos[0]["items"]
    assert tl.chips_filas_n() == 4 and tl.RULER_H == base + 3 * paso
    rm = tl._mas_rect(0)
    vis = [tl._kw_rect(i)[0] for i in range(4)]
    assert rm is not None and all(v is not None for v in vis) and tl._kw_rect(4)[0] is None and tl._hint_rect(0) is None
    disjuntos(vis + [rm])
    assert rm.width() >= tl.fontMetrics().horizontalAdvance("+2") + 4, "el «+2» entero"
    tl.repaint()
    tl.grab().copy(0, 0, 900, 260).save(os.path.join(out, "chips_6.png"))
    menu = tl._mas_menu_build(0)
    simples = [a for a in menu.actions() if a.menu() is None and not a.isSeparator()]
    assert len(simples) == 2, textos_menu(menu)
    a_kw = next(a for a in simples if NOMBRES[4] in a.text())
    a_h = next(a for a in simples if "Otra saga" in a.text() and "🎬" in a.text())
    assert "00:00:05" in a_kw.text(), a_kw.text()
    pedidos.clear()
    a_kw.trigger()
    assert pedidos == [(["k4"], "cinematic")], pedidos
    saltos.clear()
    a_h.trigger()
    assert tl.hint_selected == 0 and saltos and abs(saltos[-1] - (5.0 + 2.0 / tl.pps)) < 1e-6
    # (retoque 2) elegida desde el «+2»: sale de él y se ve en la fila 0, sin tapar a nadie
    rh = tl._hint_rect(0)
    assert rh is not None and round(rh.top()) == round(tl._chip_y(0)), rh
    gr = tl._chips_filas()[2]
    assert all(("hint", 0) not in G["items"] for G in gr), gr
    visibles = [rh] + [r for r in (tl._kw_rect(i)[0] for i in range(5)) if r is not None]
    visibles += [r for r in (tl._mas_rect(g) for g in range(len(gr))) if r is not None]
    disjuntos(visibles)
    assert sum(len(G["items"]) for G in gr) == 2 and tl.chips_filas_n() == 4, gr
    tl.repaint()
    tl.grab().copy(0, 0, 900, 260).save(os.path.join(out, "chips_6_elegida.png"))
    tl.select_hint(-1)
    print("✓ la banderita elegida nunca queda escondida en un «+N»: pasa a la fila 0 y otro chip va al «+N»")
    subs = [a.menu() for a in menu.actions() if a.menu() is not None]
    assert len(subs) == 2, textos_menu(menu)              # (dos términos: «El río» y «Otra saga»)
    for sm in subs:
        tx = textos_menu(sm)
        assert any("Separar" in t for t in tx) and any("Unir con" in t for t in tx), (sm.title(), tx)
    # clic real en el «+2»: abre su menú (y no mueve el cabezal)
    rm = tl._mas_rect(0)
    assert tl._chips_filas()[2][0]["texto"] == "+2"
    saltos.clear()
    abiertos = []
    tl._mas_menu = lambda g, gpos: abiertos.append(g)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, real(tl, rm))
    pump(app, 0.05)
    del tl._mas_menu
    assert abiertos == [0] and not saltos, (abiertos, saltos)
    mover(tl, real(tl, rm))
    assert tl._chip_hover == ("mas", 0) and "El río" in tl.toolTip() and "Otra saga" in tl.toolTip(), tl.toolTip()
    # menú del chip ⚡ (clic derecho): también Separar / Unir con
    mk = tl._kw_menu_build(1)
    tx = textos_menu(mk)
    assert any("Separar" in t for t in tx) and any("Unir con" in t for t in tx), tx
    print("✓ 6 chips: 4 filas + «+2»; su menú elige el chip ⚡ y la banderita como el clic, y trae «✂ Separar…» / "
          "«🔗 Unir con…» por término (también el menú del chip)")

    # 7) con 4 filas, clips y cabeceras siguen alineados: clic en un clip lo elige; el cabezal va donde pulsas
    tl.set_hint_marks([])
    tl.set_kw_marks([kw(5.0, k) for k in range(4)])
    win.ctrl.add_text(8.0, 3.0, "Texto de prueba")
    pump(app, 0.3)
    assert tl.RULER_H == base + 3 * paso
    c = next(c for c in win.ctrl.project.clips.values() if c.text is not None)
    ti = win.ctrl.project.track_index(c.track_id)
    assert tl.track_y(0) == tl.RULER_H and tl._grip_rect().top() == tl.RULER_H
    rc = tl.clip_rect(c)
    assert rc.top() >= tl.track_y(ti) - 1 and rc.bottom() <= tl.track_y(ti) + tl.track_h(ti) + 1, (rc, tl.track_y(ti))
    assert tl.track_index_at(rc.center().y()) == ti
    for k in range(len(win.ctrl.project.tracks)):
        b1, b2 = tl._header_buttons(k)
        if tl.track_h(k) > 0:
            assert tl.track_y(k) <= b1.top() and b1.bottom() <= tl.track_y(k) + tl.track_h(k) + 1, (k, b1)
    add = tl._corner_buttons()[0]
    assert add.geometry().bottom() < tl._vt() + tl.RULER_H and add.geometry().top() >= tl._vt() + tl.TOPIC_H
    tl.selected.clear()
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(rc.center().x()), int(rc.center().y())))
    pump(app, 0.1)
    assert c.id in tl.selected, tl.selected
    saltos.clear()
    x = tl.x_for(20.0)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(tl._vt() + tl.RULER_H - 4)))
    pump(app, 0.1)
    assert saltos and abs(saltos[0] - 20.0) < 2.0 / tl.pps, saltos
    print("✓ con 4 filas: pistas, cabeceras y botones de la esquina bajan juntos; clic en un clip lo elige y el "
          "cabezal va donde pulsas en la regla")

    # 8) al cambiar de zoom, el alto cambia con una transición corta (sin saltos atrás)
    tl.set_kw_marks([kw(5.0 + 0.5 * k, k) for k in range(4)])
    pump(app, 0.2)
    assert tl.chips_filas_n() == 4 and tl.RULER_H == base + 3 * paso
    tl.zoom(20.0, tl.x_for(5.0))
    vals = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.5:
        app.processEvents()
        vals.append(tl.RULER_H)
        time.sleep(0.005)
    assert tl.chips_filas_n() == 1 and vals[-1] == base, (tl.chips_filas_n(), vals[-1])
    assert all(b <= a for a, b in zip(vals, vals[1:])), "siempre hacia el mismo lado"
    medios = {v for v in vals if base < v < base + 3 * paso}
    assert medios, f"con transición (valores: {sorted(set(vals))})"
    print(f"✓ zoom: la regla pasa de {base + 3 * paso} a {base} px con una transición corta "
          f"({len(medios)} pasos intermedios, sin saltos atrás)")

    # 10) (retoque 3) panel bajo: solo 2 filas y el resto en «+N» (no se come las pistas)
    tl.zoom(1 / 20.0, tl.x_for(5.0))
    tl.set_kw_marks([kw(5.0, k) for k in range(4)])
    pump(app, 0.3)
    assert tl.chips_filas_n() == 4
    # a) con el umbral de verdad (150 px) y este panel (181 px): las 4 filas, aunque la línea de tiempo sea baja
    tl.CHIP_PANEL_BAJO = 150
    tl._revisar_alto_visible()
    vh = sa.viewport().height() if sa is not None else tl.height()
    if vh >= 150:
        assert tl._filas_tope() == 4 and tl.chips_filas_n() == 4, (vh, tl._filas_tope())
    # b) panel más bajo que el umbral y sin sitio para pista y media con 4 filas → 2 filas + «+2»
    tl.CHIP_PANEL_BAJO = vh + 50
    vv, aa = tl.video_h, tl.audio_h
    llena = tl._regla_base() + 3 * paso
    tl.video_h = tl.audio_h = int((vh - llena) / 1.5 / max(1.0, tl.ui_k)) + 8     # (pistas que no caben 1,5 veces)
    assert vh - llena < 1.5 * tl._alto_pista_tipo(), (vh, llena, tl._alto_pista_tipo())
    tl._revisar_alto_visible()
    assert tl.chips_filas_n() == 2 and tl.RULER_H == base + paso, (tl.chips_filas_n(), tl.RULER_H)
    gr = tl._chips_filas()[2]
    assert len(gr) == 1 and gr[0]["texto"] == "+2" and gr[0]["fila"] == 1, gr
    rs = [tl._kw_rect(i)[0] for i in range(4)]
    vis = [r for r in rs if r is not None] + [tl._mas_rect(0)]
    disjuntos(vis)
    assert all(r.bottom() <= tl.RULER_H for r in vis)
    tl.repaint()
    tl.grab().copy(0, 0, 900, 200).save(os.path.join(out, "chips_panel_bajo.png"))
    # c) igual de bajo pero con pistas finas (sí cabe pista y media debajo): vuelven las 4 filas
    tl.video_h = tl.audio_h = 20
    assert vh - llena >= 1.5 * tl._alto_pista_tipo(), (vh, llena, tl._alto_pista_tipo())
    tl._revisar_alto_visible()
    assert tl.chips_filas_n() == 4, tl.chips_filas_n()
    tl.video_h, tl.audio_h = vv, aa
    tl.CHIP_PANEL_BAJO = 0
    tl._revisar_alto_visible()
    assert tl.chips_filas_n() == 4 and tl.RULER_H == base + 3 * paso
    print(f"✓ con {vh} px visibles y el umbral de 150 px: las 4 filas; más bajo y sin sitio para pista y media: 2 filas + "
          "«+2»; con pistas finas (sí caben), otra vez 4")

    tl.set_kw_marks([])
    tl.set_hint_marks([])
    win.ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
