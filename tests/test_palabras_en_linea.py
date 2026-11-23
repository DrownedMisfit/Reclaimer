"""
🔑 PRUEBA (bug del usuario, 20/11): las palabras clave de «Dijiste…» se ven en la línea de tiempo.
  · elegir una palabra en la lista → sus banderitas en sus tiempos, la primera elegida y el cabezal en ella (también al
    volver a pulsar la misma);
  · modo «Todas» → las banderitas de TODAS las palabras, enteras y repartidas en filas (la elegida, resaltada);
  · una mención dicha en una parte que QUITASTE («cortado») → muesca en el corte, con su tooltip; al elegirla, el
    cabezal va a ese corte;
  · ◀ ▶ saltan entre las veces que la dices;
  · los 3 modos (Todas · Elegida · Ninguna): selector segmentado en «Dijiste…» y botón de la regla, a la par y
    recordados; «Ninguna» oculta banderitas y chips sin perder nada; elegir una palabra en «Ninguna» pasa a «Elegida».
Ejecutar:  .venv/Scripts/python.exe tests/test_palabras_en_linea.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
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
# ventana no llega a 1600 y los 40 s de la línea de tiempo no caben (la banderita de 0:20 quedaba fuera)
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = f"_pruebas_tmp/pantalla_palabras_{os.getpid()}.json"
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

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _vigilante(segundos: float = 420.0):
    """Si la prueba se cuelga (un diálogo o un menú de verdad), sale sola y libera el turno."""
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta (¿un menú o un diálogo esperando?)", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def cerca(a, b, tol=0.02):
    return a is not None and abs(a - b) <= tol


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "palabras_en_linea")
    os.makedirs(out, exist_ok=True)
    capturas = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp",
                            "palabras_en_linea")
    os.makedirs(capturas, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core.model import TRACK_AUDIO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    voz = os.path.join(out, "voz.wav")
    if not os.path.exists(voz):
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=40", voz],
                       check=True)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.8)
    ctrl, tl, cl = win.ctrl, win.timeline, win.clips
    (mv,) = ctrl.import_now([voz])
    while ctrl.analyzing:
        pump(app, 0.1)
    ya = {t.id for t in ctrl.project.tracks}
    ctrl.add_track(TRACK_AUDIO)
    an = next(t.id for t in ctrl.project.tracks if t.id not in ya)
    # en la línea de tiempo: [0, 15) del archivo y [25, 40); lo de 15–25 está quitado (ahí dice «Puerto Viejo»)
    ctrl.insert_ranges([{"media_id": mv, "start": 0.0, "source_in": 0.0, "duration": 15.0},
                        {"media_id": mv, "start": 15.0, "source_in": 25.0, "duration": 15.0}], an, "Narración")

    def w(t, s):
        return [t, t + 0.4, s]
    palabras = [w(1.0, "Hoy"), w(1.5, "hablamos"), w(2.0, "de"), w(2.5, "Valle"), w(2.9, "Azul"), w(4.0, "y"),
                w(8.0, "de"), w(8.5, "Torre"), w(8.9, "Norte"), w(12.0, "otra"), w(12.5, "vez"), w(13.0, "Torre"),
                w(13.4, "Norte"), w(18.0, "lo"), w(18.4, "cuenta"), w(18.8, "Puerto"), w(19.5, "Viejo"),
                w(30.0, "y"), w(30.5, "Isla"), w(31.0, "Roja")]
    ctrl.project.transcripts[mv] = {"language": "es", "words": palabras, "segments": [
        {"start": 1.0, "end": 4.4, "text": "Hoy hablamos de Valle Azul y"},
        {"start": 8.0, "end": 13.8, "text": "de Torre Norte otra vez Torre Norte"},
        {"start": 18.0, "end": 19.9, "text": "lo cuenta Puerto Viejo"},
        {"start": 30.0, "end": 31.4, "text": "y Isla Roja"}]}
    from editoria.ai import keyword_glossary as KG     # (nombres genéricos: el glosario dice que son palabras clave)
    for nombre in ("Valle Azul", "Torre Norte", "Puerto Viejo", "Isla Roja"):
        KG.add_yes(nombre)
    ctrl.transcript_changed.emit(mv)
    ctrl.project_changed.emit()
    pump(app, 0.4)
    cl.set_modo("elegida")
    cl.recalcular()
    pump(app, 0.3)
    terms = [m["term"] for m in cl.menciones]
    tl.pps, tl.scroll = 40.0, 0.0                       # (los 40 s a la vista)
    tl._update_scrollbar()
    pump(app, 0.1)
    assert {"Torre Norte", "Valle Azul", "Isla Roja", "Puerto Viejo"} <= set(terms), terms

    def fila_de(term):
        i = terms.index(term)
        return next(f for f in range(cl.lista_menciones.count()) if cl._indice_de_fila(f) == i)

    def elegir(term):
        f = fila_de(term)
        cl.lista_menciones.setCurrentRow(f)
        pump(app, 0.05)
        if cl.mencion is None or cl.mencion["term"] != term:
            raise AssertionError(("no se eligió", term, cl.mencion and cl.mencion["term"]))
        cl._clic_en_fila(cl.lista_menciones.item(f))    # (lo que hace el clic, además de cambiar la fila)
        pump(app, 0.05)

    def marcas_de(term):
        return sorted(t for t, l in tl.hint_marks if tl.hint_word(l) == term)

    # 1) elegir una palabra: sus banderitas, la primera elegida y el cabezal en ella (un solo salto)
    elegir("Isla Roja")
    saltos = []
    cl.seek_requested.connect(saltos.append)
    elegir("Torre Norte")
    assert saltos == [8.5], f"el cabezal debe saltar una sola vez: {saltos}"
    cl.seek_requested.disconnect(saltos.append)
    assert marcas_de("Torre Norte") == [8.5, 13.0] and len(tl.hint_marks) == 2, tl.hint_marks
    sel = tl.hint_selected
    assert sel >= 0 and tl.hint_marks[sel][0] == 8.5, (sel, tl.hint_marks)
    assert cerca(win.engine.time, 8.5), win.engine.time
    rs = [tl._hint_rect(i) for i in range(len(tl.hint_marks))]
    assert all(r is not None for r in rs), "las dos banderitas se ven en la regla"
    win.engine.user_seek(30.0)
    pump(app, 0.05)
    cl._t_elegida = 0.0                                 # (un clic más tarde, no el que la eligió)
    cl._clic_en_fila(cl.lista_menciones.item(fila_de("Torre Norte")))     # (otra vez la misma: a su primera vez)
    pump(app, 0.05)
    assert cerca(win.engine.time, 8.5), win.engine.time
    tl.repaint()
    tl.grab().copy(0, 0, 1400, 160).save(os.path.join(capturas, "elegida_gta6.png"))
    print("✓ elegir «Torre Norte»: sus 2 banderitas (8,5 y 13 s), la primera elegida y el cabezal en ella (también al "
          "volver a pulsarla)")

    # 2) ◀ ▶ entre las veces que la dices
    cl.al_cabezal(8.5)
    cl._ir_vecina(1)
    pump(app, 0.05)
    assert cerca(win.engine.time, 13.0), win.engine.time
    cl._ir_vecina(-1)
    pump(app, 0.05)
    assert cerca(win.engine.time, 8.5), win.engine.time
    print("✓ ◀ ▶ saltan entre las veces que dices la palabra")

    # 3) mención en una parte QUITADA: muesca en el corte, tooltip, y el cabezal va al corte
    elegir("Puerto Viejo")
    assert marcas_de("Puerto Viejo") == [15.0], tl.hint_marks
    i = next(k for k, (_t, l) in enumerate(tl.hint_marks) if tl.hint_word(l) == "Puerto Viejo")
    assert tl._hint_cortada(tl.hint_marks[i][1])
    assert cerca(win.engine.time, 15.0), win.engine.time
    assert tl.hint_selected == i and not tl._hint_notch(i), "elegida: entera"
    tip = tl._chip_tip(("hint", i))
    assert "Dicho en una parte que quitaste" in tip, tip
    assert cl._tiempos_nav() == [15.0]
    print("✓ «Puerto Viejo» (cortado): marca en el corte (15 s), tooltip «Dicho en una parte que quitaste» y el "
          "cabezal va al corte")

    # 4) «Todas»: todas las palabras, enteras y en filas; la cortada, muesca si no es la elegida
    elegir("Torre Norte")
    cl.btn_modo["todas"].click()
    pump(app, 0.1)
    assert cl.modo == "todas" and tl.marcas_modo == "todas"
    assert set(tl.hint_word(l) for _t, l in tl.hint_marks) == {"Torre Norte", "Valle Azul", "Isla Roja", "Puerto Viejo"}
    filas = tl._chips_filas()[0]
    for k, (t, l) in enumerate(tl.hint_marks):
        if tl._hint_cortada(l):
            assert tl._hint_notch(k), "la cortada (no elegida) es una muesca"
        else:
            assert not tl._hint_notch(k) and k in filas, (k, l)
            assert filas[k][0] >= 0 or any(k in g["items"] for g in tl._chips_filas()[2]), (k, filas[k])
    otras = [k for k, (_t, l) in enumerate(tl.hint_marks) if tl.hint_word(l) == "Isla Roja"]
    assert otras and tl._hint_dim(tl.hint_marks[otras[0]][1]) and tl._hint_rect(otras[0]) is not None
    tl.repaint()
    tl.grab().copy(0, 0, 1400, 160).save(os.path.join(capturas, "todas.png"))
    print("✓ «Todas»: las 4 palabras; las de otras palabras enteras (más tenues) y en filas; la cortada, muesca")

    # 5) los 3 modos: botón de la regla y selector, a la par y recordados; «Ninguna» oculta sin perder nada
    ver = tl._kw_buttons()[0]
    assert "Todas" in ver.toolTip() and not ver.icon().isNull()
    for k, b in cl.btn_modo.items():
        assert b.text() and not b.icon().isNull() and b.toolTip(), k
    tl.kw_marks = [{"t": 8.5, "term": "Torre Norte", "kind": "gameplay", "key": "torre"},
                   {"t": 20.5, "term": "Isla Roja", "kind": "cinematic", "key": "isla"}]
    tl.set_kw_visible(True)
    pump(app, 0.05)
    assert tl._kw_rect(0)[0] is not None and tl._kw_rect(1)[0] is not None
    ver.click()                                         # Todas → Elegida
    pump(app, 0.05)
    assert tl.marcas_modo == "elegida" and cl.modo == "elegida" and cl.btn_modo["elegida"].isChecked()
    assert set(tl.hint_word(l) for _t, l in tl.hint_marks) == {"Torre Norte"}
    assert tl._kw_rect(0)[0] is not None and tl._kw_rect(1)[0] is not None, "«Elegida» no toca la fila ⚡"
    assert "Elegida" in ver.toolTip()
    ver.click()                                         # Elegida → Ninguna
    pump(app, 0.05)
    assert tl.marcas_modo == "ninguna" and cl.btn_modo["ninguna"].isChecked()
    assert tl.hint_marks == [] and tl._kw_rect(0)[0] is None and len(tl.kw_marks) == 2, "oculto, no borrado"
    from editoria.ui.hint_marks import set_source as marcas_set
    marcas_set(tl, "buscar", [(20.0, "🔎 algo")])         # 🔎 Buscar sigue marcando aunque esté en «Ninguna»
    assert tl.hint_marks == [(20.0, "🔎 algo")], tl.hint_marks
    marcas_set(tl, "buscar", [])
    assert str(QSettings("EditorIA", "EditorIA").value("clips/modo_marcas")) == "ninguna"
    elegir("Isla Roja")                                  # elegir una palabra la enseña: pasa a «Elegida»
    assert cl.modo == "elegida" and tl.marcas_modo == "elegida", (cl.modo, tl.marcas_modo)
    assert marcas_de("Isla Roja") == [20.5] and cerca(win.engine.time, 20.5), (tl.hint_marks, win.engine.time)
    ver.click()
    ver.click()                                         # Elegida → Ninguna → Todas
    pump(app, 0.05)
    assert tl.marcas_modo == "todas" and cl.btn_todas.isChecked()
    sm = cl.sel_modo                                    # con poco ancho: una sola pieza, solo iconos
    win.show_panel(cl)                                  # (a la vista: un widget oculto no recibe su tamaño)
    pump(app, 0.3)
    assert sm.isVisible()
    estrecho, ancho = sm.minimumSizeHint().width(), sm.sizeHint().width()
    assert estrecho < ancho
    sm.setFixedWidth(estrecho)                          # (fijo: así manda sobre la fila de botones)
    pump(app, 0.05)
    assert all(b.toolButtonStyle() == Qt.ToolButtonIconOnly for b in cl.btn_modo.values())
    assert len({b.y() for b in cl.btn_modo.values()}) == 1, "una sola fila"
    sm.setFixedWidth(ancho)
    pump(app, 0.05)
    assert all(b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for b in cl.btn_modo.values())
    sm.setMinimumWidth(0)
    sm.setMaximumWidth(16777215)
    # la fila ⚡: su propio botón en «Dijiste…», en el menú Timeline y en el clic derecho de la regla, a la par
    act_fila = win._act_fila_kw
    assert cl.btn_fila_kw.isChecked() == tl.kw_visible == act_fila.isChecked()
    assert cl.btn_fila_kw.text() and not cl.btn_fila_kw.icon().isNull() and cl.btn_fila_kw.toolTip()
    cl.btn_fila_kw.click()
    pump(app, 0.05)
    assert tl.kw_visible == cl.btn_fila_kw.isChecked() == act_fila.isChecked()
    act_fila.trigger()
    pump(app, 0.05)
    assert tl.kw_visible == cl.btn_fila_kw.isChecked() == act_fila.isChecked()
    # la banderita de 🔎 Buscar que elegiste no se cambia por la primera de la palabra
    marcas_set(tl, "buscar", [(25.0, "🔎 otra cosa")])
    i_b = next(k for k, (_t, l) in enumerate(tl.hint_marks) if l.startswith("🔎"))
    tl.select_hint(i_b)
    cl._marcas()
    pump(app, 0.02)
    assert tl.hint_marks[tl.hint_selected][1].startswith("🔎"), tl.hint_marks[tl.hint_selected]
    marcas_set(tl, "buscar", [])
    # el índice de cortes da lo mismo que cut_point
    from editoria.core import mapping
    ix = mapping.CutIndex(ctrl.project, mv)
    for s in (0.5, 14.9, 15.0, 18.8, 24.9, 25.0, 33.0, 39.9):
        assert ix.point(s) == mapping.cut_point(ctrl.project, mv, s), s
    menu = tl._kw_boton_menu_build()                    # (el clic derecho del botón, sin abrirlo)
    assert [a.text() for a in menu.actions() if not a.isSeparator()][:3] == ["Todas", "Elegida", "Ninguna"]
    print("✓ 3 modos: selector de «Dijiste…» y botón de la regla a la par y recordados; «Elegida» = solo las banderitas de "
          "su palabra (la fila ⚡ va aparte, con su botón); «Ninguna» oculta sin borrar; elegir una palabra en «Ninguna» pasa a «Elegida»; con poco "
          "ancho, el selector queda en una pieza con solo iconos")

    ctrl.project.modified = False
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
