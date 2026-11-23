"""
Fase 1 de la reorganización de la interfaz (notas_claude/PROPUESTA_INTERFAZ.md, apartado e: «Esqueleto»):
  1. la biblioteca de la izquierda a TODO el alto y la línea de tiempo a su derecha, igual de funcional (sin perder alto
     de pistas y con su barra entera); si a su derecha no cabe la barra de la línea de tiempo (ventana estrecha), la
     línea de tiempo vuelve a todo el ancho;
  2. interruptores de paneles con nombre en la barra de arriba: reflejan lo abierto y lo abren / cierran; nunca texto
     cortado (si no caben, solo icono con el nombre en el tooltip);
  3. pestañas de los paneles con su nombre completo: en una fila si cabe, si no en dos filas; nunca «…»; la etiqueta
     no cambia sola si nadie toca nada;
  4. 🎬 Escenas cabe en 1366 px.
Pantalla de prueba 1920×1080 (offscreen:configfile). Carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_fase1_interfaz.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
ANCHO, ALTO = 1920, 1080
_CFG = f"_pruebas_tmp/pantalla_fase1_{os.getpid()}.json"
with open(os.path.join(RAIZ, _CFG), "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": ANCHO, "height": ALTO, "logicalDpi": 96,
                            "dpr": 1}]}, _f)
__import__("atexit").register(lambda: os.path.exists(os.path.join(RAIZ, _CFG)) and os.remove(os.path.join(RAIZ, _CFG)))
os.chdir(RAIZ)                                   # (la ruta del configfile es relativa: «:» corta el argumento)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _CFG
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=os.path.join(RAIZ, "_pruebas_tmp"))
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401

import shiboken6  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QTabBar, QToolButton  # noqa: E402

FALLOS = []


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s):
    """Espera (hasta s segundos) a que se cumpla cond, procesando eventos (y un poco más para que se asiente)."""
    t0 = time.time()
    while time.time() - t0 < s and not cond():
        app.processEvents()
        time.sleep(0.01)
    pump(app, 0.3)


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in list(st.allKeys()):
        if k.startswith(("paneles_pestana/", "paneles/lado/")) or k in ("ventana/paneles", "geometry"):
            st.remove(k)
    st.setValue("ventana/biblioteca_alto", "false")       # (la línea de tiempo a todo el ancho, como de fábrica)
    import editoria.ui.main_window as MW
    win = MW.MainWindow()
    win.show()
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 1.2)
    win.go_page("edit")
    pump(app, 0.6)
    D = win.docks

    def geo(d):
        return d.mapTo(win, d.rect().topLeft()), d.size()

    def barra_tl_entera(donde):
        bar = win._tl_bar
        cortados = []
        for b in bar.findChildren(QAbstractButton):
            if not b.isVisibleTo(bar) or not b.text():
                continue
            if b.width() + 1 < b.sizeHint().width():
                cortados.append(f"{b.text()} {b.width()}<{b.sizeHint().width()}")
        tc = win.tl_timecode
        if tc.width() + 1 < tc.fontMetrics().horizontalAdvance(tc.text()):
            cortados.append(f"tiempo {tc.width()}")
        chk(not cortados, f"{donde}: la barra de la línea de tiempo entera {cortados[:4]}"
            + (f" (barra {bar.width()} px, necesita {win._tl_ancho_minimo()}, línea {D['timeline'].width()}, "
               f"esquina {win.corner(Qt.BottomLeftCorner)}, nombre {win.tl_name.isVisible()})" if cortados else ""))

    print("— 1. de entrada, la línea de tiempo a todo el ancho; «◧ A todo el alto», la biblioteca hasta abajo —")
    tl, med = D["timeline"], D["media"]
    chk(not win.biblioteca_alto() and not win._btn_alto.isChecked() and not win._act_alto.isChecked(),
        "de entrada «A todo el alto» apagado (botón y Ventana)")
    chk(win.corner(Qt.BottomLeftCorner) == Qt.BottomDockWidgetArea and
        win.corner(Qt.BottomRightCorner) == Qt.BottomDockWidgetArea, "de entrada, la línea de tiempo a todo el ancho")
    (pt, st_), (pm, sm) = geo(tl), geo(med)
    chk(pt.x() <= 2 and pm.y() + sm.height() <= pt.y() + 2, f"…empieza en el borde izquierdo ({pt.x()}) y Medios queda "
        "encima")
    barra_tl_entera("1920 de entrada")
    alto_antes = win.timeline.visibleRegion().boundingRect().height()
    win._btn_alto.click()
    esperar(app, lambda: win.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea, 2.0)
    chk(win.biblioteca_alto() and win._act_alto.isChecked() and
        str(QSettings("EditorIA", "EditorIA").value("ventana/biblioteca_alto")).lower() == "true",
        "el botón lo enciende, Ventana lo refleja y se recuerda")
    (pt, st_), (pm, sm) = geo(tl), geo(med)
    chk(win.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea, "1920: la esquina de abajo a la izquierda es de la "
        "biblioteca")
    chk(pm.y() + sm.height() >= pt.y() + st_.height() - 4, f"1920: Medios llega hasta abajo (hasta {pm.y() + sm.height()}"
        f", la línea de tiempo hasta {pt.y() + st_.height()})")
    chk(pt.x() >= pm.x() + sm.width(), f"1920: la línea de tiempo empieza a su derecha ({pt.x()} ≥ "
        f"{pm.x() + sm.width()})")
    chk(win.corner(Qt.BottomRightCorner) == Qt.BottomDockWidgetArea, "1920: el Inspector se queda encima de la línea "
        "de tiempo (como DaVinci)")
    barra_tl_entera("1920 a todo el alto")
    alto_izq = win.timeline.visibleRegion().boundingRect().height()
    chk(alto_izq >= alto_antes - 2, f"1920: la línea de tiempo no pierde alto de pistas ({alto_izq} / antes "
        f"{alto_antes} px)")
    print("— límites al arrastrar el borde entre la biblioteca y la línea de tiempo —")
    win.resizeDocks([med], [1600], Qt.Horizontal)       # (como arrastrar el borde muy a la derecha)
    pump(app, 1.2)
    (pt, st_), (pm, sm) = geo(tl), geo(med)
    chk(win.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea and st_.width() >= win._tl_ancho_minimo(),
        f"la biblioteca no se come la línea de tiempo (línea {st_.width()} px ≥ {win._tl_ancho_minimo()})")
    barra_tl_entera("biblioteca muy ancha")
    chk(win.preview.isVisible() and win.preview.canvas.width() > 100, f"el visor sigue a la vista "
        f"({win.preview.canvas.width()} px)")
    win.resizeDocks([med], [10], Qt.Horizontal)         # (y muy a la izquierda)
    pump(app, 0.6)
    chk(med.width() >= med.minimumSizeHint().width() - 1 and med.width() >= 150,
        f"la biblioteca no baja de lo que pide su contenido ({med.width()} px)")
    win.resizeDocks([med], [460], Qt.Horizontal)
    pump(app, 0.4)
    # funcional: un clip en la línea de tiempo y un clic sobre él lo elige
    from PySide6.QtTest import QTest
    cid = win.ctrl.add_text(0.0, 4.0, "Prueba")
    pump(app, 0.4)
    ids = [cid] if isinstance(cid, str) else list(cid or [])
    chk(bool(ids) and ids[0] in win.ctrl.project.clips, "se puede poner un texto en la línea de tiempo")
    if ids:
        c = win.ctrl.project.clips[ids[0]]
        tlw = win.timeline
        tlw.fit()
        pump(app, 0.2)
        r = tlw.clip_rect(c)
        tlw.set_selection([])
        pump(app, 0.1)
        pc = r.center()
        QTest.mouseClick(tlw, Qt.LeftButton, Qt.NoModifier, pc.toPoint() if hasattr(pc, "toPoint") else pc)
        pump(app, 0.2)
        chk(ids[0] in tlw.selected, f"a todo el alto: un clic en el clip de la línea de tiempo lo elige ({r.center()})")
        win.ctrl.undo_stack.undo()
        pump(app, 0.2)
    print("— ventana estrecha: la línea de tiempo vuelve a todo el ancho —")
    win.resize(1300, 760)
    pump(app, 0.8)
    chk(win.corner(Qt.BottomLeftCorner) == Qt.BottomDockWidgetArea, "1300 px: la línea de tiempo a todo el ancho "
        "(su barra no cabría a la derecha de la biblioteca)")
    barra_tl_entera("1300")
    chk(win.minimumSizeHint().width() <= 1366, f"1300 px: la ventana pide ≤ 1366 ({win.minimumSizeHint().width()})")
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.8)
    chk(win.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea, "otra vez 1920: biblioteca a todo el alto")
    for pg in ("scenes", "thumb", "edit"):
        win.go_page(pg)
        pump(app, 0.6)
        chk(win.minimumSizeHint().width() <= ANCHO and win.width() <= ANCHO, f"a todo el alto, {pg}: cabe")
    win._act_alto.trigger()                            # (Ventana lo apaga)
    pump(app, 0.6)
    chk(not win.biblioteca_alto() and not win._btn_alto.isChecked() and
        win.corner(Qt.BottomLeftCorner) == Qt.BottomDockWidgetArea and med.maximumWidth() > 10000,
        "Ventana lo apaga: la línea de tiempo vuelve a todo el ancho y la biblioteca sin límite")

    print("— interruptores con un nombre de proyecto largo y «Exportar miniatura» a la vista —")

    def interruptores_enteros(donde):
        inter_ = win.interruptores
        cortados = [b.text() for b in list(inter_.values()) + [win._btn_alto]
                    if b.toolButtonStyle() != Qt.ToolButtonIconOnly and b.width() + 1 < b.sizeHint().width()]
        chk(not cortados, f"{donde}: ningún interruptor cortado {cortados}")
    win.project_title.setText("·  " + "Un proyecto con un nombre larguísimo para ver qué pasa en la barra" * 1)
    pump(app, 0.6)
    interruptores_enteros("1916 + nombre largo")
    win.resize(1800, ALTO - 80)
    win.btn_export_thumb.setVisible(True)
    pump(app, 0.6)
    interruptores_enteros("1800 + «Exportar miniatura»")
    win.btn_export_thumb.setVisible(False)
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.6)
    print("— desde 🎬 Escenas, un interruptor lleva a Editar —")
    win.go_page("scenes")
    pump(app, 0.8)
    win.interruptores["media"].click()
    pump(app, 0.8)
    chk(getattr(win, "_scenes_state", None) is None and win.page_buttons["edit"].isChecked() and
        not D["media"].isHidden(), "Escenas + «Medios» → Editar con Medios")

    print("— 2. interruptores con nombre —")
    inter = win.interruptores
    chk(set(inter) >= {"media", "effects", "sounds", "ai", "voz_texto", "palabras", "audio", "inspector"}, f"están los principales "
        f"({sorted(inter)})")

    def interruptores_ok(donde):
        mal = [k for k, b in inter.items() if b.isChecked() != win._interruptor_abierto(k)]
        chk(not mal, f"{donde}: cada interruptor marcado si su panel está abierto {mal}")
        cortados = [b.text() for b in inter.values() if b.toolButtonStyle() != Qt.ToolButtonIconOnly
                    and b.width() + 1 < b.sizeHint().width()]
        chk(not cortados, f"{donde}: ningún interruptor cortado {cortados}")
    interruptores_ok("1920")
    chk(all(b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for b in inter.values()), "1920: con su nombre")
    k = "audio"
    d = D[k]
    if d.isHidden():
        inter[k].click()
        pump(app, 0.3)
    chk(not d.isHidden(), f"«{inter[k].text()}»: abierto")
    d.raise_()
    pump(app, 0.3)
    inter[k].click()                                   # (delante → se cierra)
    pump(app, 0.3)
    chk(d.isHidden() and not inter[k].isChecked(), f"«{inter[k].text()}»: clic estando delante → se cierra")
    inter[k].click()
    pump(app, 0.3)
    chk(not d.isHidden() and inter[k].isChecked() and not d.visibleRegion().isEmpty(),
        f"«{inter[k].text()}»: otro clic → se abre delante")
    D["voz_texto"].show()
    D["voz_texto"].raise_()                            # (Inspector abierto pero detrás de otro en su sitio)
    pump(app, 0.3)
    inter["inspector"].click()
    pump(app, 0.3)
    chk(not D["inspector"].isHidden() and not D["inspector"].visibleRegion().isEmpty(),
        "Inspector detrás de otra pestaña: el clic lo pone delante (no lo cierra)")
    win.go_page("keywords")                            # (22/11: su propio panel «Palabras clave»)
    pump(app, 0.5)
    chk(inter["palabras"].isChecked(), "«Palabras clave» → su panel")
    interruptores_ok("en Palabras clave")
    win.go_page("edit")
    pump(app, 0.5)
    win.resize(1300, 760)
    pump(app, 0.8)
    interruptores_ok("1300")
    chk(all(b.toolButtonStyle() == Qt.ToolButtonIconOnly for b in inter.values()) or
        all(b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for b in inter.values()),
        "1300: todos con nombre o todos con solo icono")
    chk(all(b.toolTip().startswith(n) for (k_, n) in win.INTERRUPTORES_IZQ + win.INTERRUPTORES_DER
            for b in [inter.get(k_)] if b is not None), "cada interruptor con su nombre en el tooltip")
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.8)

    print("— 3. pestañas con nombre completo —")
    punteros = {}

    def pestañas(donde):
        nonlocal punteros
        punteros = {shiboken6.getCppPointer(d_)[0]: d_ for d_ in D.values()}
        mal, modos = [], []
        for tb in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly):
            if not tb.isVisible() or not tb.count():
                continue
            capa = getattr(tb, "_dos_filas", None)
            docks = [punteros.get(tb.tabData(i)) for i in range(tb.count())]
            con_boton = all(d_ is not None and any(D.get(k_) is d_ for k_ in win.interruptores) for d_ in docks)
            en_pagina = False                          # (agrupación 20/11: ya no hay páginas con paneles propios)
            if tb.height() <= 2:                       # (sin fila de pestañas: el interruptor de arriba elige)
                modos.append("sin pestañas")
                if not con_boton or en_pagina:
                    mal.append(f"fila sin alto con paneles sin interruptor o en una página {[win._nombre_limpio(d_) for d_ in docks if d_]}")
                continue
            if con_boton and not en_pagina:
                mal.append(f"fila de pestañas repetida con los interruptores {[win._nombre_limpio(d_) for d_ in docks if d_]}")
            nombres = [win._nombre_limpio(d_) for d_ in docks if d_ is not None]
            import re as _re
            if any(not all(_re.search(r"\w", x) for x in n.split()) for n in nombres):
                mal.append(f"emoji en el nombre de una pestaña {nombres}")
            if capa is not None and capa.activa and capa.isVisible():
                modos.append("dos")
                rs = capa.rects()
                filas = {r.y() for _i, _n, r in rs}
                if len(filas) > 2 or len(rs) != tb.count():
                    mal.append(f"dos filas: {len(filas)} filas, {len(rs)} pestañas")
                for _i, n, r in rs:
                    if r.right() > capa.width() or r.width() < capa.fontMetrics().horizontalAdvance(n):
                        mal.append(f"«{n}» no cabe en su pestaña")
                if sorted(n for _i, n, _r in rs) != sorted(nombres):
                    mal.append("dos filas sin los nombres completos")
            else:
                textos = [tb.tabText(i) for i in range(tb.count())]
                if textos == nombres:
                    modos.append("una")
                    for i in range(tb.count()):
                        if tb.tabRect(i).width() < tb.fontMetrics().horizontalAdvance(textos[i]):
                            mal.append(f"«{textos[i]}» cortada")
                    if sum(tb.tabRect(i).width() for i in range(tb.count())) > tb.width() + 2:
                        mal.append("una fila más ancha que su sitio")
                else:
                    modos.append("iconos")
                    if [tb.tabToolTip(i) for i in range(tb.count())] != nombres:
                        mal.append("iconos sin el nombre en el tooltip")
            if any("…" in tb.tabText(i) for i in range(tb.count())):
                mal.append("«…» en una pestaña")
        chk(not mal, f"{donde}: pestañas con nombre completo ({modos}) {mal[:4]}")
        for tb in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly):
            if tb.isVisible() and tb.count() and getattr(tb, "_dos_filas", None) is None and \
                    [tb.tabText(i) for i in range(tb.count())] == [win._nombre_limpio(punteros.get(tb.tabData(i)))
                                                                for i in range(tb.count()) if punteros.get(tb.tabData(i))]:
                con = [not tb.tabIcon(i).isNull() for i in range(tb.count())]
                chk(all(con) or not any(con), f"{donde}: iconos en todas las pestañas del grupo o en ninguna")
                break
        return modos

    def titulos():
        return {k_: d_.windowTitle() for k_, d_ in D.items()}
    pump(app, 0.5)
    modos = pestañas("1920 Editar")
    chk(modos and all(m == "sin pestañas" for m in modos), f"1920 Editar: ninguna fila de pestañas (los interruptores "
        f"de arriba eligen) ({modos})")
    t0 = titulos()
    pump(app, 3.4)                                     # (dos vueltas del repaso de 1,5 s)
    chk(titulos() == t0, f"las etiquetas no cambian solas ({ {k_ for k_ in t0 if titulos()[k_] != t0[k_]} })")
    for pg in ("scenes", "thumb", "edit"):
        win.go_page(pg)
        pump(app, 0.8)
        pestañas(f"1920 {pg}")
    t0 = titulos()
    pump(app, 3.4)
    chk(titulos() == t0, "tras volver de las páginas, las etiquetas no cambian solas")
    win.resize(1300, 760)
    pump(app, 1.0)
    modos = pestañas("1300 Editar")
    print("    (1300:", modos, ")")
    # (paneles sin interruptor —Historial, Gráficas, Tareas— arrastrados por el usuario a la pestaña del Inspector: su
    #  grupo SÍ lleva pestañas; de fábrica Historial y Gráficas se abren debajo, sin esa fila)
    for k_ in ("history", "scopes", "tasks"):
        D[k_].setFloating(False)
        win.tabifyDockWidget(D["inspector"], D[k_])
        D[k_].show()
    pump(app, 1.2)
    modos = pestañas("1300 grupo mixto")
    print("    (1300 grupo mixto:", modos, ")")
    # dos filas: un clic en una pestaña de la capa pone delante su panel
    def capa_activa():
        return next((getattr(tb, "_dos_filas", None) for tb in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly)
                     if getattr(tb, "_dos_filas", None) is not None and tb._dos_filas.activa and tb.isVisible()
                     and tb.count()), None)
    capa = capa_activa()
    if capa is None:                                   # (si a 1300 caben en una fila: el lateral más estrecho)
        win.resizeDocks([D["inspector"]], [230], Qt.Horizontal)
        pump(app, 2.0)
        capa = capa_activa()
        modos = pestañas("1300, biblioteca estrecha")
    chk(capa is not None, "con poco sitio, un grupo en dos filas")
    if capa is not None:
        chk(capa.testAttribute(Qt.WA_TransparentForMouseEvents), "la capa de dos filas deja el ratón a la fila de Qt "
            "(arrastrar la pestaña saca o mueve el panel)")
        i, n, r = capa.rects()[-1]
        recibidos = []

        class _Mira(__import__("PySide6.QtCore", fromlist=["QObject"]).QObject):
            def eventFilter(self, o, e):
                if e.type() in (e.Type.MouseButtonPress, e.Type.MouseMove, e.Type.MouseButtonRelease):
                    recibidos.append((e.type(), e.position().toPoint()))
                return False
        mira = _Mira()
        QTest.mousePress(capa.barra, Qt.LeftButton, Qt.NoModifier, r.center())
        capa.barra.installEventFilter(mira)            # (después de la capa: ve lo que la capa le reenvía)
        QTest.mouseMove(capa.barra, r.center() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(12, 3))
        QTest.mouseRelease(capa.barra, Qt.LeftButton, Qt.NoModifier, r.center())
        capa.barra.removeEventFilter(mira)
        pump(app, 0.4)
        chk(any(t == __import__("PySide6.QtCore", fromlist=["QEvent"]).QEvent.Type.MouseMove and
                capa.barra.tabRect(i).adjusted(-20, -20, 20, 20).contains(pt) for t, pt in recibidos),
            f"dos filas: el arrastre llega a la pestaña de Qt de «{n}» ({recibidos[:3]})")
        d_ = punteros.get(capa.barra.tabData(i))
        chk(capa.barra.currentIndex() == i and d_ is not None and not d_.visibleRegion().isEmpty(),
            f"dos filas: clic en «{n}» lo pone delante (actual {capa.barra.currentIndex()} / {i}, "
            f"{d_.objectName() if d_ else None}, oculto {d_.isHidden() if d_ else None}, "
            f"región {d_.visibleRegion().boundingRect() if d_ else None}, capa {capa.isVisible()} {capa.geometry()})")
    win.go_page("edit")
    pump(app, 0.6)
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.8)

    print("— 3b. cabecera del visor: ningún texto cortado (1366 con laterales de entrada; Vertical y Edits) —")
    from PySide6.QtWidgets import QComboBox, QLabel, QStyle, QStyleOptionComboBox

    def cabecera_entera(donde):
        pv = win.preview
        h = pv.header
        pv._ajustar_cabecera()
        pump(app, 0.2)
        mal = []
        for w in h.findChildren(QLabel):
            if w.isVisibleTo(h) and w.text() and w.width() + 1 < w.fontMetrics().horizontalAdvance(w.text()):
                mal.append(f"«{w.text()}» {w.width()}<{w.fontMetrics().horizontalAdvance(w.text())}")
        for q in h.findChildren(QComboBox):
            if not q.isVisibleTo(h):
                continue
            op = QStyleOptionComboBox()
            q.initStyleOption(op)
            zona = q.style().subControlRect(QStyle.CC_ComboBox, op, QStyle.SC_ComboBoxEditField, q).width()
            for i in range(q.count()):
                if zona + 2 < q.fontMetrics().horizontalAdvance(q.itemText(i)):
                    mal.append(f"desplegable «{q.itemText(i)}» no cabe ({zona} px)")
        for b in h.findChildren(QAbstractButton):
            if b.isVisibleTo(h) and b.text() and b.width() + 1 < b.sizeHint().width():
                mal.append(f"botón «{b.text()}» {b.width()}<{b.sizeHint().width()}")
        t = pv.title_label
        fm = t.fontMetrics()
        if fm.horizontalAdvance(t.text()) > t._zona_texto().width() and not t.acortado():
            mal.append("nombre del proyecto cortado sin «…»")
        if t.text() and t.text() not in t.toolTip():
            mal.append("el nombre entero no está en el tooltip")
        chk(not mal, f"{donde}: cabecera del visor sin texto cortado (visor {pv.width()} px, nombre "
            f"{'con «…»' if t.acortado() else 'entero'}) {mal[:4]}")

    win.preview.title_label.show_name("Mi reseña con un nombre bastante largo para la cabecera")
    win.resize(1362, 728)
    pump(app, 0.5)
    win._apply_dock_sizes()                            # (los laterales de entrada en una pantalla de 1366)
    pump(app, 0.8)
    for tab in ("youtube", "short", "edit", "youtube"):
        win.workspaces.switch(tab)
        pump(app, 0.8)
        win.preview.title_label.show_name("Mi reseña con un nombre bastante largo para la cabecera")
        pump(app, 0.3)
        cabecera_entera(f"1366 · {tab}")
    for tab in ("youtube", "short"):                    # (laterales más anchos: el visor en su mínimo)
        win.workspaces.switch(tab)
        pump(app, 0.6)
        win.resizeDocks([D["media"], D["inspector"]], [420, 440], Qt.Horizontal)
        pump(app, 0.8)
        win.preview.title_label.show_name("Mi reseña con un nombre bastante largo para la cabecera")
        cabecera_entera(f"1366 laterales anchos · {tab}")
    win.workspaces.switch("youtube")
    pump(app, 0.6)
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.8)
    cabecera_entera("1920 · youtube")

    print("— solo a los lados del visor; sueltos encima o arriba/abajo, a su sitio al abrir —")
    lados = Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
    mal = [k for k, d_ in D.items() if k != "timeline" and d_.allowedAreas() != lados]
    chk(not mal, f"todos los paneles (salvo la línea de tiempo) solo a izquierda o derecha {mal}")
    win.docks["inspector"].setFloating(True)
    win.docks["inspector"].move(win.geometry().center())
    win.removeDockWidget(D["history"])
    win.addDockWidget(Qt.TopDockWidgetArea, D["history"])
    D["history"].show()
    pump(app, 0.4)
    chk(D["inspector"].isFloating() and win.dockWidgetArea(D["history"]) == Qt.TopDockWidgetArea,
        "(preparado: Inspector suelto encima de la ventana e Historial arriba)")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()                                        # (se guarda esta distribución, como al cerrar Reclaimer)
    pump(app, 0.3)
    win = MW.MainWindow()
    win.show()
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 1.5)
    D = win.docks
    chk(not D["inspector"].isFloating() and win.dockWidgetArea(D["inspector"]) == Qt.RightDockWidgetArea,
        f"al abrir, el Inspector suelto encima vuelve a la derecha (suelto {D['inspector'].isFloating()})")
    chk(win.dockWidgetArea(D["history"]) == Qt.RightDockWidgetArea,
        f"…y el Historial que estaba arriba, a su lado ({win.dockWidgetArea(D['history'])})")
    vacio = [k for k, d_ in D.items() if not d_.isHidden() and not d_.isFloating()
             and win.dockWidgetArea(d_) in (Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea) and k != "timeline"]
    chk(not vacio, f"ningún panel arriba ni abajo del visor {vacio}")
    D["memes"].setFloating(True)
    D["memes"].move(win.geometry().center())
    D["memes"].hide()
    pump(app, 0.3)
    win.interruptores["memes"].click()
    pump(app, 0.5)
    chk(not D["memes"].isFloating() and not D["memes"].isHidden(),
        "un panel suelto encima, al pulsar su interruptor, vuelve acoplado a su lado")
    win.go_page("edit")
    pump(app, 0.4)

    print("— 4. 🎬 Escenas cabe en 1366 —")
    win.resize(1300, 760)
    pump(app, 0.5)
    w0 = win.width()
    win.go_page("scenes")
    pump(app, 1.0)
    pg = win._scenes_widget
    chk(pg is not None and pg.minimumSizeHint().width() <= 1366 and win.minimumSizeHint().width() <= 1366,
        f"Escenas pide ≤ 1366 (página {pg.minimumSizeHint().width() if pg else '?'}, ventana "
        f"{win.minimumSizeHint().width()})")
    chk(win.width() <= w0 + 2, f"entrar en Escenas no ensancha la ventana ({win.width()} / {w0})")
    cortados = [b.text() for b in pg.findChildren(QToolButton) + pg.findChildren(QAbstractButton)
                if b.isVisibleTo(pg) and b.text() and b.parentWidget() is not None
                and b.parentWidget().parentWidget() is pg and b.width() + 1 < b.sizeHint().width()] if pg else []
    chk(not cortados, f"Escenas: nada cortado en su barra de arriba {cortados[:4]}")
    win.go_page("edit")
    pump(app, 0.6)
    chk(win.width() <= w0 + 2, f"…y al salir, la ventana como estaba ({win.width()} / {w0})")

    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
