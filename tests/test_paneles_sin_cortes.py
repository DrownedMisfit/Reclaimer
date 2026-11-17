"""
↔ Ningún panel corta palabras, esté donde esté y mida lo que mida (queja del usuario del 17/11: «la pantalla se come las
palabras»). Para CADA panel (salvo la línea de tiempo), mostrado y al frente, suelto a 200/260/340/480 px de ancho,
acoplado a la derecha estrecho y acoplado ARRIBA con 220 px de alto, con todas sus secciones abiertas y cada pestaña:
  a) ningún widget se sale por la derecha de lo visible (ni de su contenedor),
  b) ninguna barra de desplazamiento horizontal a la vista,
  c) ningún texto recortado: etiquetas, botones, casillas y desplegables caben en una línea o se parten en varias
     (y lo partido cabe a lo alto); una elipsis solo si el texto entero sale al pasar el ratón,
  d) la ventana no pide más ancho que la pantalla con los paneles de entrada.
Se prueba con pantallas de 1920×1080 (ventana 1920×1040) y 1366×768 (ventana 1366×740).
Capturas de cada panel a 260 px: _pruebas_tmp/test_paneles_sin_cortes/<pantalla>/<panel>_260.png
Ejecutar:  .venv/Scripts/python.exe tests/test_paneles_sin_cortes.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANTALLAS = {"1920": (1920, 1080, 1920, 1040), "1366": (1366, 768, 1366, 740)}
ANCHOS = (200, 260, 340, 480)


def lanzar_todas(out):
    """Una ventana por pantalla (la pantalla sin ventana se elige al abrir Qt: un proceso para cada una)."""
    fallos = 0
    for nombre, (sw, sh, _ww, _wh) in PANTALLAS.items():
        cfg = os.path.join("_pruebas_tmp", f"pantalla_{nombre}.json")
        os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
        with open(os.path.join(RAIZ, cfg), "w", encoding="utf-8") as f:
            json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": sw, "height": sh, "logicalDpi": 96,
                                    "dpr": 1}]}, f)
        # (la ruta, relativa y con «/»: Qt separa las opciones de la plataforma por «:»)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=" + cfg.replace("\\", "/"),
                   PYTHONUTF8="1", EDITORIA_SIN_SONIDO="1")
        env.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
        print(f"— Pantalla {sw}×{sh} —", flush=True)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), out, "--pantalla", nombre], cwd=RAIZ, env=env)
        fallos += r.returncode != 0
    if fallos:
        print(f"✗ {fallos} pantalla(s) con cortes")
        sys.exit(1)
    print("TODO OK")


# ----------------------------------------------------------------------------------------------- la revisión
def revisar(dock, cortes: dict, vistos: set, modo: str):
    """Recorre lo que se ve del panel y apunta cada corte en «cortes» (clave = widget + tipo)."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea, QCheckBox, QComboBox,
                                   QLabel, QPushButton, QRadioButton, QScrollBar, QTabBar, QToolButton, QWidget)
    from editoria.ui import responsive as R

    def nombre(w):
        t = ""
        for attr in ("text", "currentText", "title"):
            try:
                t = getattr(w, attr)()
                break
            except Exception:  # noqa: BLE001
                pass
        return f"{type(w).__name__}«{str(t)[:40]}»"

    def apunta(w, tipo, det):
        cortes.setdefault((id(w), tipo), f"[{modo}] {tipo}: {nombre(w)} {det}")

    def contenedor(w):
        """El viewport con desplazamiento más cercano (lo que se ve de verdad) o el panel."""
        p = w.parentWidget()
        while p is not None and p is not dock:
            pp = p.parentWidget()
            if isinstance(pp, QAbstractScrollArea) and pp.viewport() is p:
                return p
            p = pp
        return dock

    def dentro_de_horizontal(w):
        p = w
        while p is not None and p is not dock:
            if p.property("responsive_horizontal"):
                return True
            p = p.parentWidget()
        return False

    for w in dock.findChildren(QWidget):
        try:
            if not w.isVisibleTo(dock) or isinstance(w, QScrollBar) or w.isWindow():
                continue
            if dentro_de_horizontal(w):
                continue
            par = w.parentWidget()
            if isinstance(par, QAbstractScrollArea) and w is not par.viewport() and not \
                    (hasattr(par, "widget") and callable(par.widget) and par.widget() is w):
                continue                       # (piezas internas de una zona con desplazamiento: esquinas, cabeceras)
            if par is not None and isinstance(par.parentWidget(), QAbstractItemView) and \
                    par is not par.parentWidget().viewport():
                continue
            vistos.add(id(w))
            # a) que no se salga por la derecha (de lo visible y de su contenedor)
            cont = contenedor(w)
            r = QRect(w.mapTo(cont, QPoint(0, 0)), QWidget.size(w))
            if QWidget.width(w) > 3 and QWidget.height(w) > 3 and r.right() + 1 > QWidget.width(cont) + 2 and r.left() < QWidget.width(cont):
                apunta(w, "se sale", f"(der. {r.right() + 1} > visible {QWidget.width(cont)})")
            elif par is not None and not isinstance(par, QAbstractScrollArea) and QWidget.width(w) > 3 and \
                    QWidget.geometry(w).right() + 1 > QWidget.width(par) + 2 and QWidget.geometry(w).left() < QWidget.width(par):
                apunta(w, "se sale", f"(der. {QWidget.geometry(w).right() + 1} > su contenedor {QWidget.width(par)})")
            # b) ninguna barra horizontal a la vista
            if isinstance(w, QAbstractScrollArea) and w.horizontalScrollBar().isVisible():
                apunta(w, "barra horizontal", f"({w.horizontalScrollBar().maximum()} px de más)")
            # c) ningún texto recortado
            fm = w.fontMetrics()
            if isinstance(w, QLabel):
                if w.pixmap() is not None and not w.pixmap().isNull():
                    continue
                if not w.text().strip():
                    continue
                if w.wordWrap():
                    alto = w.heightForWidth(QWidget.width(w))
                    if alto > QWidget.height(w) + 3:
                        apunta(w, "texto cortado a lo alto", f"(necesita {alto} px de alto, tiene {QWidget.height(w)})")
                elif QWidget.width(w) + 2 < w.sizeHint().width():
                    apunta(w, "texto cortado", f"(necesita {w.sizeHint().width()} px, tiene {QWidget.width(w)})")
            elif isinstance(w, QAbstractButton):
                if R.es_multilinea(w):
                    # (con alto fijo puesto en el código no se puede partir: «…» y entero al pasar el ratón; si no,
                    # el panel tiene que darle el alto que necesita su texto partido)
                    if w.hasHeightForWidth() and w.maximumHeight() >= 16777215:
                        alto = w.heightForWidth(QWidget.width(w))
                        if alto > QWidget.height(w) + 3:
                            apunta(w, "texto cortado a lo alto",
                                   f"(necesita {alto} px de alto, tiene {QWidget.height(w)})")
                    if not w._cabe():
                        comprobar_pintado(w, apunta)
                        if w.acortado() and _texto(w) not in ayuda(w):
                            apunta(w, "«…» sin el texto entero en la ayuda", "")
                    continue
                txt = w.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
                if not txt.strip():
                    continue
                if isinstance(w, QToolButton) and w.toolButtonStyle() == 0:      # Qt.ToolButtonIconOnly
                    continue
                lineas = txt.split("\n")
                need = max(fm.horizontalAdvance(t) for t in lineas)
                if not w.icon().isNull():
                    need += w.iconSize().width() + 4
                need += 20 if isinstance(w, (QCheckBox, QRadioButton)) else 8 if isinstance(w, QPushButton) else 4
                if QWidget.width(w) + 2 < need:
                    apunta(w, "texto cortado", f"(necesita {need} px, tiene {QWidget.width(w)})")
            elif isinstance(w, QComboBox) and not w.isEditable() and not R.es_desplegable_que_acorta(w):
                need = fm.horizontalAdvance(w.currentText()) + 30
                if QWidget.width(w) + 2 < need:
                    apunta(w, "texto cortado", f"(necesita {need} px, tiene {QWidget.width(w)})")
            elif R.es_desplegable_que_acorta(w) and not w.isEditable() and w._acortado():
                comprobar_pintado(w, apunta)
                if w.currentText() not in ayuda(w):
                    apunta(w, "«…» sin el texto entero en la ayuda", "")
            elif isinstance(w, QTabBar) and w.count() > 1:
                for i in range(w.count()):
                    if not w.isTabVisible(i):
                        continue
                    tr = w.tabRect(i)
                    if tr.right() + 1 > QWidget.width(w) + 2 or tr.left() < -2:
                        apunta(w, "pestaña escondida", f"(«{w.tabText(i)}» fuera de la fila de {QWidget.width(w)} px)")
                        break
        except RuntimeError:
            continue


PINTADOS: dict = {}           # id(widget) → veces que Qt llamó a SU dibujo nuevo (el de responsive.py)


def contar_pintados():
    """Un contador en el dibujo de cada adaptación: así se comprueba que Qt pinta con él (no solo que en Python las
    medidas cuadran)."""
    from editoria.ui import responsive as R
    for mezcla in (R._BotonMulti, R._CasillaMulti, R._HerramientaMulti, R._ComboAcorta):
        original = mezcla.paintEvent

        def contar(self, ev, _o=original):
            PINTADOS[id(self)] = PINTADOS.get(id(self), 0) + 1
            return _o(self, ev)
        mezcla.paintEvent = contar


def comprobar_pintado(w, apunta):
    antes = PINTADOS.get(id(w), 0)
    w.grab()
    if PINTADOS.get(id(w), 0) <= antes:
        apunta(w, "no se pinta con el dibujo nuevo", "(Qt no llama a su paintEvent)")


def _texto(w) -> str:
    return w.text().replace("&&", "\0").replace("&", "").replace("\0", "&")


def ayuda(w) -> str:
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication, QToolTip
    QToolTip.hideText()
    QApplication.sendEvent(w, QHelpEvent(QEvent.ToolTip, QPoint(4, 4), w.mapToGlobal(QPoint(4, 4))))
    return QToolTip.text()


def abrir_todo(dock):
    """Todas las secciones plegables abiertas (para revisarlas)."""
    from editoria.ui.tabs import Section
    for s in dock.findChildren(Section):
        try:
            if not s.is_open():
                s.set_open(True, save=False)
        except RuntimeError:
            pass
    for s in dock.findChildren(object):
        if type(s).__name__ == "_Section" and hasattr(s, "set_expanded") and s.header.isVisibleTo(s):
            s.set_expanded(True)


def pestañas(dock):
    from PySide6.QtWidgets import QTabWidget
    return [t for t in dock.findChildren(QTabWidget) if t.isVisibleTo(dock) and t.count() > 1]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def una_pantalla(out, nombre):
    os.environ["LOCALAPPDATA"] = TMP
    os.environ["EDITORIA_DATOS"] = os.path.join(TMP, "EditorIA")
    import _ajustes  # noqa: F401
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication(sys.argv)
    sw, sh, ww, wh = PANTALLAS[nombre]
    scr = app.primaryScreen().availableGeometry()
    assert scr.width() == sw, (scr, sw)
    carpeta = os.path.join(out, nombre)
    os.makedirs(carpeta, exist_ok=True)
    contar_pintados()
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)                        # (con el tema de verdad: sus letras y rellenos cambian los anchos)
    win = MainWindow()
    win.resize(ww, wh)
    win.show()
    win.reset_layout()
    pump(app, 0.6)
    win.cut_fix_panel()                          # (✂ Corte de audio: se crea más tarde, también debe adaptarse)
    pump(app, 0.3)

    # d) con los paneles de entrada, la ventana cabe en la pantalla
    win.reset_layout()
    pump(app, 0.6)
    pide = win.minimumSizeHint().width()
    assert pide <= scr.width(), f"la ventana pide {pide} px y la pantalla tiene {scr.width()}"
    print(f"✓ d) con los paneles de entrada la ventana pide {pide} px (pantalla {scr.width()} px)", flush=True)

    # todo se puede cerrar y volver a abrir (salvo la línea de tiempo): en «☰ Paneles» y en el menú «Ventana»
    from PySide6.QtWidgets import QDockWidget
    win._llenar_menu_paneles()
    win._llenar_menu_ventana()
    en_paneles = {a.text() for a in win._menu_paneles.actions()}
    en_ventana = set(win._menu_ventana.actions())
    for k, d in win.docks.items():
        if k == "timeline":
            continue
        assert d.features() & QDockWidget.DockWidgetClosable, f"«{d.nombre}» no se puede cerrar"
        assert d.toggleViewAction() in en_ventana, f"«{d.nombre}» no está en el menú Ventana"
        if not d.isFloating():
            assert any(d.nombre in t for t in en_paneles), f"«{d.nombre}» no está en ☰ Paneles"
    g = win.docks["guided"]
    g.show()
    pump(app, 0.1)
    g.close()
    pump(app, 0.1)
    assert not g.isVisible() and not g.toggleViewAction().isChecked(), "🧭 Montaje guiado no se cierra"
    g.toggleViewAction().trigger()
    pump(app, 0.1)
    assert g.isVisible(), "🧭 Montaje guiado no vuelve desde el menú"
    assert len(win.guided.secciones) == 3, "🧭 Montaje guiado: sus pasos en tres partes plegables"
    print("✓ todos los paneles (también 🧭 Montaje guiado) se cierran y están en «☰ Paneles» y en «Ventana»")
    win.reset_layout()
    pump(app, 0.4)

    estado0 = win.saveState(3)
    cortes: dict = {}
    vistos: set = set()
    alto_suelto = min(900, scr.height() - 80)
    claves = [k for k in win.docks if k != "timeline"]
    t0 = time.time()

    def captura(d, nombre):
        sc = d.widget()
        cont = sc.widget() if hasattr(sc, "widget") and callable(sc.widget) and sc.widget() else sc
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter, QPixmap
        pix = QPixmap(QWidget.size(cont))
        pix.fill(d.palette().color(d.backgroundRole()))       # (el fondo del panel, como en pantalla)
        pin = QPainter(pix)
        cont.render(pin, QPoint(0, 0))
        pin.end()
        pix.save(os.path.join(carpeta, f"{nombre}_260.png"))

    def poner(d, modo, w, h):
        win.restoreState(estado0, 3)
        if modo == "suelto":
            d.setFloating(True)
            d.show()
            d.resize(w, h)
        elif modo == "derecha":
            d.setFloating(False)
            win.removeDockWidget(d)
            win.addDockWidget(Qt.RightDockWidgetArea, d)
            d.show()
            win.resizeDocks([d], [w], Qt.Horizontal)
        else:
            d.setFloating(False)
            win.removeDockWidget(d)
            win.addDockWidget(Qt.TopDockWidgetArea, d)
            d.show()
            win.resizeDocks([d], [h], Qt.Vertical)
        d.raise_()
        pump(app, 0.05)
        abrir_todo(d)
        pump(app, 0.15)

    def revisar_panel(k, d, modos, nombre_captura, extra=""):
        for modo, w, h in modos:
            poner(d, modo, w, h)
            if modo == "suelto" and d.width() > w + 2:
                cortes[(k, extra, "ancho", w)] = (f"[{d.nombre}{extra}] el panel suelto no se deja poner a {w} px "
                                                  f"(mide {d.width()}, pide {d.minimumSizeHint().width()})")
            etiqueta = f"{d.nombre}{extra} · {modo} {d.width()}×{d.height()}"
            revisar(d, cortes, vistos, etiqueta)
            hueco(k, d, etiqueta)
            for tw in pestañas(d):
                actual = tw.currentIndex()
                for i in range(tw.count()):
                    if i == actual:
                        continue
                    tw.setCurrentIndex(i)
                    pump(app, 0.1)                  # (páginas que se rellenan al abrirse: también se adaptan)
                    abrir_todo(d)
                    pump(app, 0.1)
                    revisar(d, cortes, vistos, etiqueta + f" · pestaña «{tw.tabText(i)}»")
                    hueco(k, d, etiqueta + f" · pestaña «{tw.tabText(i)}»")
                tw.setCurrentIndex(actual)
                pump(app, 0.05)
            if modo == "suelto" and w == 260:
                captura(d, nombre_captura)

    def hueco(k, d, etiqueta):
        """Sin un hueco enorme debajo (las páginas que no se ven no deben dar su alto al panel)."""
        panel = d.panel
        lay = panel.layout()
        vp = d.widget().viewport().height() if hasattr(d.widget(), "viewport") else 0
        if lay is None or not lay.hasHeightForWidth():
            return
        necesita = lay.totalHeightForWidth(QWidget.width(panel))
        if QWidget.height(panel) > max(vp, necesita) + 4:
            cortes[(k, etiqueta, "hueco")] = f"[{etiqueta}] hueco debajo: mide {QWidget.height(panel)} px de alto " \
                                              f"y su contenido pide {necesita}"
        from PySide6.QtWidgets import QStackedWidget
        for st in panel.findChildren(QStackedWidget):
            if not st.isVisibleTo(d) or st.currentWidget() is None:
                continue
            pag = st.currentWidget()
            alto_pag = pag.heightForWidth(QWidget.width(pag)) if pag.hasHeightForWidth() else \
                pag.minimumSizeHint().height()
            if QWidget.height(st) > max(alto_pag, pag.sizeHint().height()) + 60 and QWidget.height(st) > vp:
                cortes[(k, etiqueta, "hueco", id(st))] = (
                    f"[{etiqueta}] hueco debajo de la página que se ve: {QWidget.height(st)} px para una página de "
                    f"{alto_pag} px (cuenta el alto de otra página que no se ve)")

    for k in claves:
        revisar_panel(k, win.docks[k], [("suelto", w, alto_suelto) for w in ANCHOS] +
                      [("derecha", 220, 0), ("arriba", 0, 220)], k)

    # el Inspector con un clip elegido: video (Clip · Video · Audio · Color), audio (ecualizador) y texto
    from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, new_id
    p = win.ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    mv = MediaItem(new_id(), "/falso/v.mp4", KIND_VIDEO, "un video con un nombre bastante largo.mp4", duration=60.0,
                   width=1280, height=720, has_audio=True, probed=True)
    ma = MediaItem(new_id(), "/falso/a.wav", KIND_AUDIO, "narración.wav", duration=60.0, probed=True)
    p.media[mv.id], p.media[ma.id] = mv, ma
    cv = Clip(new_id(), mv.id, v1.id, 0.0, 0.0, 10.0)
    ca = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 10.0)
    for c in (cv, ca):
        p.clips[c.id] = c
    win.ctrl.project_changed.emit()
    pump(app, 0.2)
    win.ctrl.add_text(20.0, 4.0, "Un texto en pantalla")
    pump(app, 0.2)
    ct = next(c for c in p.clips.values() if c.text is not None)
    d = win.docks["inspector"]
    for nombre, cid, pagina in (("video", cv.id, 1), ("audio", ca.id, 1), ("texto", ct.id, 3)):
        win.inspector.set_selection([cid])
        pump(app, 0.2)
        assert win.inspector.stack.currentIndex() == pagina, (nombre, win.inspector.stack.currentIndex())
        revisar_panel("inspector", d, [("suelto", 200, alto_suelto), ("suelto", 260, alto_suelto),
                                       ("arriba", 0, 220)], f"inspector_{nombre}", f" con un clip de {nombre}")
    win.inspector.set_selection([])
    win.restoreState(estado0, 3)
    print(f"  (revisados {len(vistos)} widgets distintos de {len(claves)} paneles en {time.time() - t0:.0f} s; "
          f"{len(PINTADOS)} pintados de verdad con el dibujo nuevo)")
    if cortes:
        for c in sorted(cortes.values()):
            print("  ✗", c)
        print(f"✗ {len(cortes)} cortes")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    assert not cortes, f"{len(cortes)} cortes"
    print(f"✓ a/b/c) {len(claves)} paneles × {len(ANCHOS) + 2} posiciones, y el Inspector con un clip de video, de "
          f"audio y de texto: 0 cortes, 0 huecos ({len(vistos)} widgets)")
    print(f"✓ capturas a 260 px en {carpeta}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except (AttributeError, ValueError):
        pass
    salida = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
        os.path.join(RAIZ, "_pruebas_tmp", "test_paneles_sin_cortes")
    salida = os.path.abspath(salida)
    if "--pantalla" not in sys.argv:
        lanzar_todas(salida)
    else:
        import tempfile
        sys.path.insert(0, RAIZ)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        _TMPROOT = os.path.join(RAIZ, "_pruebas_tmp")
        TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
        __import__("atexit").register(__import__("shutil").rmtree, TMP, True)
        una_pantalla(salida, sys.argv[sys.argv.index("--pantalla") + 1])
