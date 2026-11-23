"""
👋 PRUEBA de la guía de primer uso (ui/guia_primer_uso.py), sin ventanas (offscreen):
  · no sale sola en las pruebas ni sin ventana (debe_mostrarse = False aunque no se haya pedido «No volver a mostrar»);
  · desde Ayuda → «Guía de primer uso», con TODOS los paneles cerrados: recorre sus pasos (cada uno abre su panel,
    rodea un sitio que se ve y la burbuja cabe en la ventana sin taparlo), y al terminar todo vuelve a como estaba;
  · el texto de cada burbuja cabe entero (alto de su texto partido al ancho de la burbuja);
  · si a mitad se pasa a otra página (Escenas), al terminar vuelve a la de inicio y luego deja los paneles como estaban;
  · «Saltar» a mitad (y Esc, también tras pasar por otra página) lo deja como estaba; cualquier cierre = ya no sale
    sola al abrir (solo una vez);
  · se puede relanzar desde Ayuda las veces que haga falta.
Ejecutar:  .venv/Scripts/python.exe tests/test_guia_primer_uso.py <carpeta_salida>
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtCore import QRect, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _vigilante(segundos: float = 300.0):
    import threading

    def fin():
        print(f"✗ la prueba sigue tras {segundos:.0f} s: se corta", flush=True)
        os._exit(3)
    th = threading.Timer(segundos, fin)
    th.daemon = True
    th.start()


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


FALLOS: list[str] = []


def ok(cond, texto, detalle=""):
    print(("✓ " if cond else "✗ ") + texto + ("" if cond else f"  {detalle}"), flush=True)
    if not cond:
        FALLOS.append(texto)


def main():
    _vigilante()
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "guia_primer_uso")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    st.setValue("shorts/encuadre_auto", False)
    st.setValue("ventana/biblioteca_alto", "false")
    from editoria.ui import guia_primer_uso as G
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.reset_layout()
    pump(app, 1.6)                                    # (más que los 1,2 s del arranque: no debe salir sola)
    ok(win.guia_primer_uso is None and not win.findChildren(G._Burbuja), "no sale sola al abrir en las pruebas")
    st.setValue(G.CLAVE_NO_MOSTRAR, False)
    ok(not G.debe_mostrarse(st), "ni aunque no se haya pedido «No volver a mostrar» (offscreen / pruebas)")

    def visibles():
        return sorted(k for k, d in win.docks.items() if not d.isHidden())

    def secciones():
        return (win.voz_texto.abierta(), win.audio_panel.abierta())

    # el peor caso: todos los paneles cerrados (salvo la línea de tiempo)
    for k, d in win.docks.items():
        if k != "timeline":
            d.hide()
    pump(app, 0.3)
    antes, sec_antes = visibles(), secciones()
    lanzar = win.shortcut_actions["Ayuda/Guía de primer uso"][0].trigger
    lanzar()
    pump(app, 0.4)
    g = win.guia_primer_uso
    ok(g is not None and g.activa and g.burbuja.isVisible(), "Ayuda → «Guía de primer uso» la enseña")
    total = len(G.PASOS)
    n = 0
    while g is not None and g.activa and n < total + 2:
        b, obj = g.burbuja, g.anillo.objetivo
        r = g.anillo.rect_objetivo()
        clave = G.PASOS[g.i][0]
        ok(obj is not None and obj.isVisible() and r is not None, f"paso «{clave}»: su sitio se ve (abre su panel)")
        dentro = win.rect().contains(b.geometry())
        ok(dentro, f"paso «{clave}»: la burbuja cabe en la ventana", str(b.geometry()))
        if r is not None and r.height() < win.height() // 2:
            ok(not b.geometry().intersects(r), f"paso «{clave}»: la burbuja no tapa el sitio", f"{b.geometry()} {r}")
        ok(b.frase.text() and len(b.frase.text()) <= 140, f"paso «{clave}»: una frase corta")
        necesita = b.frase.heightForWidth(b.frase.width())
        ok(necesita <= b.frase.height() + 1 and b.frase.geometry().bottom() <= b.height(),
           f"paso «{clave}»: el texto cabe entero en la burbuja", f"(pide {necesita} px, tiene {b.frase.height()})")
        if g.i == total - 1:                       # (en el último paso, se va a otra página antes de «Terminar»)
            win.go_page("scenes")
            pump(app, 0.6)
            ok(G.pagina_actual(win) == "scenes", "(se pasó a Escenas a mitad de la guía)")
        win.grab().save(os.path.join(out, f"paso_{g.i + 1}_{clave}.png"))
        b.siguiente.click()
        pump(app, 0.3)
        n += 1
    ok(win.guia_primer_uso is None, "«Terminar» en el último paso la cierra")
    ok(len(set(g.vistos)) >= total - 1, f"recorre los pasos ({len(set(g.vistos))} de {total})", str(g.vistos))
    pump(app, 0.3)
    ok(G.pagina_actual(win) == "edit", "al terminar en otra página, vuelve a la de inicio (Editar)",
       G.pagina_actual(win))
    ok(visibles() == antes, "y los paneles vuelven a como estaban", f"{antes} → {visibles()}")
    ok(secciones() == sec_antes, "y las secciones abiertas de los paneles agrupados", f"{sec_antes} → {secciones()}")
    ok(str(st.value(G.CLAVE_NO_MOSTRAR)).lower() in ("true", "1"), "terminarla entera = no vuelve a salir al abrir")
    ok(not [w for w in win.findChildren(G._Burbuja) if w.isVisible()] and
       not [w for w in win.findChildren(G._Anillo) if w.isVisible()], "sin restos a la vista (ni burbuja ni anillo)")

    # «Saltar» a mitad: como estaba, y ya no sale sola al abrir
    st.setValue(G.CLAVE_NO_MOSTRAR, False)
    win.reset_layout()
    pump(app, 0.5)
    antes, sec_antes = visibles(), secciones()
    lanzar()
    pump(app, 0.3)
    g = win.guia_primer_uso
    g.burbuja.siguiente.click()
    pump(app, 0.2)
    g.burbuja.siguiente.click()
    pump(app, 0.2)
    ok(g.i >= 1, "avanza", str(g.i))
    g.burbuja.saltar.click()
    pump(app, 0.4)
    ok(win.guia_primer_uso is None and visibles() == antes and secciones() == sec_antes,
       "«Saltar» a mitad: se cierra y todo vuelve a como estaba", f"{antes} → {visibles()}")
    ok(str(st.value(G.CLAVE_NO_MOSTRAR)).lower() in ("true", "1"), "«Saltar» también = ya no sale sola al abrir")
    # Esc también la cierra (con el foco en cualquier sitio), y también tras pasar por otra página
    from PySide6.QtTest import QTest
    st.setValue(G.CLAVE_NO_MOSTRAR, False)
    lanzar()
    pump(app, 0.3)
    QTest.keyClick(win.timeline, Qt.Key_Escape)
    pump(app, 0.3)
    ok(win.guia_primer_uso is None, "Esc la cierra")
    ok(str(st.value(G.CLAVE_NO_MOSTRAR)).lower() in ("true", "1"), "Esc también = ya no sale sola al abrir")
    antes = visibles()
    lanzar()
    pump(app, 0.3)
    win.go_page("scenes")
    pump(app, 0.6)
    foco = QApplication.focusWidget() or win
    QTest.keyClick(foco, Qt.Key_Escape)
    pump(app, 0.5)
    ok(win.guia_primer_uso is None and G.pagina_actual(win) == "edit" and visibles() == antes,
       "Esc tras pasar a Escenas: se cierra, vuelve a Editar y los paneles como estaban",
       f"{G.pagina_actual(win)} {antes} → {visibles()}")
    # al arrancar: solo una vez y nunca con un diálogo a la vista (aquí, offscreen, nunca)
    st.setValue(G.CLAVE_NO_MOSTRAR, False)
    G.al_arrancar(win)
    pump(app, 0.2)
    ok(win.guia_primer_uso is None, "al_arrancar no la abre en las pruebas")
    ok(G.ocupado(win) == "", "sin diálogos ni tareas, «ocupado» no pone pegas", G.ocupado(win))
    # y se puede volver a ver desde Ayuda cuando quieras
    lanzar()
    pump(app, 0.3)
    ok(win.guia_primer_uso is not None and win.guia_primer_uso.burbuja.isVisible(), "se vuelve a ver desde Ayuda")
    win.guia_primer_uso.saltar()
    pump(app, 0.2)
    # textos: sin emojis de color ni nombres de juegos
    import re
    emoji = re.compile("[\U0001F300-\U0001FAFF]")
    textos = " ".join(t + " " + f for _k, t, f, _p in G.PASOS)
    ok(not emoji.search(textos), "textos sin emojis de color")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallos")
        os._exit(1)
    print(f"capturas en {out}")
    print("TODO OK")
    os._exit(0)


if __name__ == "__main__":
    main()
