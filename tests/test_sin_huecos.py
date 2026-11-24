"""
↕ Sin huecos y con coherencia (el usuario, 20/11, con capturas: «espacio desperdiciado» y «falta de coherencia»; su
criterio, en notas_claude/PROPUESTA_INTERFAZ.md → «Criterio del usuario»). Comprueba, con la ventana a 1600×1000 y la
distribución de fábrica (fijada aquí: nunca la del usuario):
  1) LADO Y FILA: cada panel con interruptor se abre en el lado de su interruptor (el Inspector, interruptor de la
     derecha, se abría a la izquierda debajo de «Transiciones y efectos»); una distribución vieja incoherente se
     corrige sola al abrir; si el usuario ARRASTRA un panel al otro lado, su interruptor se muda a esa fila (y se
     recuerda) y al volver a pulsarlo se queda allí.
  2) SECCIONES PLEGADAS SEGUIDAS: en «Transiciones y efectos» con «Efectos» abierta y sus subsecciones plegadas, ningún
     hueco de más de 16 px entre cabeceras plegadas (antes, uno enorme antes de «Filtros»).
  3) ESTADOS VACÍOS CORTOS: «Voz y texto → 2 · Transcripción» sin transcripción: el aviso mide como mucho 60 px (antes,
     un recuadro oscuro gigante) y ofrece «Transcribir», que abre «1 · Transcribir».
  4) ALTO CEDIDO: «Voz y texto» encima de «Limpieza y mezcla» con Limpieza casi toda plegada: ningún panel con más del
     40 % de su alto vacío si el vecino del mismo lado lo puede usar (una lista o un texto); y lo que pongas a mano con
     el divisor no se pisa.
  5) «DIJISTE…» (Voz y texto → 4 · Palabras clave): cada fila usa su ancho (un trozo de la frase en gris entre la
     carpeta y 👍 👎), sin hueco entre la lista de palabras y ◀ ▶, y con el panel bajo la cabecera y sus botones se
     quedan a la vista (solo se desplazan las listas).
Capturas en _pruebas_tmp/diseno/huecos/<HUECOS_ETIQUETA>_*.png (HUECOS_ETIQUETA = antes / despues; por defecto
«despues»).
Ejecutar:  .venv/Scripts/python.exe tests/test_sin_huecos.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time


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
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

import faulthandler  # noqa: E402
faulthandler.dump_traceback_later(420, exit=True)       # (vigilante: nunca se queda colgada)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,  # noqa: E402
                               QApplication, QComboBox, QDialog, QLabel, QLineEdit, QListWidget, QMenu,
                               QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QTabBar, QTextEdit,
                               QWidget)

QDialog.exec = lambda self, *a: 0
for _n in ("question", "warning", "information", "critical"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.No))

ETIQUETA = os.environ.get("HUECOS_ETIQUETA", "despues")
CAPTURAS = os.environ.get("HUECOS_CAPTURAS") or os.path.join(RAIZ, "_pruebas_tmp", "diseno", "huecos")
HUECO_MAX = 16          # px entre cabeceras plegadas seguidas
VACIO_MAX = 60          # px de alto de un estado vacío
VACIO_FRAC = 0.40       # parte vacía de un panel con un vecino que la podría usar

FALLOS: list[str] = []


def ok(cond: bool, texto: str, detalle: str = ""):
    if cond:
        print(f"✓ {texto}", flush=True)
    else:
        print(f"✗ {texto} {detalle}", flush=True)
        FALLOS.append(f"{texto} {detalle}")


def pump(app, s: float = 0.3):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def captura(win, nombre: str):
    os.makedirs(CAPTURAS, exist_ok=True)
    win.grab().save(os.path.join(CAPTURAS, f"{ETIQUETA}_{nombre}.png"))


# ------------------------------------------------------------------------------------------- medidas generales
HOJAS = (QAbstractButton, QLabel, QLineEdit, QComboBox, QAbstractSlider, QAbstractSpinBox, QProgressBar, QTabBar)


def es_hoja(w) -> bool:
    if isinstance(w, QAbstractScrollArea):
        return not isinstance(w, QScrollArea)
    if isinstance(w, QLabel) and not (w.text() or w.pixmap() is not None and not w.pixmap().isNull()):
        return False
    return isinstance(w, HOJAS)


def fondo_contenido(panel, ref) -> int:
    """Lo más bajo (en coordenadas de ref) que enseña algo de verdad el panel: botones, textos, listas…"""
    abajo = 0
    for w in panel.findChildren(QWidget):
        if not es_hoja(w) or not w.isVisibleTo(panel) or w.height() <= 0:
            continue
        try:
            y = w.mapTo(ref, w.rect().bottomLeft()).y()
        except RuntimeError:
            continue
        abajo = max(abajo, y)
    return abajo


def usa_alto(panel) -> bool:
    """¿El panel enseña algo que aprovecharía alto extra (una lista o un texto que se estira)?"""
    for a in panel.findChildren(QAbstractScrollArea):
        if isinstance(a, QScrollArea) or not a.isVisibleTo(panel) or a.maximumHeight() < 2000:
            continue
        if a.sizePolicy().verticalPolicy().value & QSizePolicy.PolicyFlag.ExpandFlag.value:
            return True
    return False


def lado_de_fila(win, k: str) -> str:
    """En qué fila está el interruptor de k: la de la izquierda o la de la derecha de la barra de paneles."""
    b = win.interruptores[k]
    filas = getattr(win, "_filas_inter", None)
    if filas:                                         # (la fila de verdad donde está el botón)
        return "izq" if b.parentWidget() is filas["izq"] else "der"
    bar = win._barra_arriba
    x = b.mapTo(bar, b.rect().center()).x()
    return "izq" if x < bar.width() / 2 else "der"


def lado_de_dock(win, k: str) -> str | None:
    d = win.docks[k]
    if d.isFloating() or d.isHidden():
        return None
    a = win.dockWidgetArea(d)
    return {Qt.LeftDockWidgetArea: "izq", Qt.RightDockWidgetArea: "der"}.get(a)


def incoherentes(win) -> list[str]:
    malos = []
    for k in win.interruptores:
        if win.interruptores[k].isHidden():
            continue
        ld = lado_de_dock(win, k)
        if ld is not None and ld != lado_de_fila(win, k):
            malos.append(f"{k}: panel {ld}, interruptor {lado_de_fila(win, k)}")
    return malos


# ------------------------------------------------------------------------------------------------- los casos
def caso_lado(app, win):
    print("— 1) lado y fila —", flush=True)
    d = win.docks
    ok(not incoherentes(win), "de fábrica, cada panel en el lado de su interruptor", str(incoherentes(win)))
    # (una distribución vieja incoherente: el Inspector a la izquierda, debajo de «Transiciones y efectos»)
    win.show_panel(win.effects)
    pump(app, 0.3)
    win.removeDockWidget(d["inspector"])
    win.addDockWidget(Qt.LeftDockWidgetArea, d["inspector"])
    win.splitDockWidget(d["effects"], d["inspector"], Qt.Vertical)
    d["inspector"].show()
    pump(app, 0.4)
    captura(win, "1_lado_inspector_incoherente")
    win._paneles_a_su_sitio()                  # (lo que hace al abrir)
    pump(app, 0.4)
    ok(lado_de_dock(win, "inspector") == "der", "al abrir, un Inspector que quedó a la izquierda vuelve a la derecha",
       f"(está en {lado_de_dock(win, 'inspector')})")
    # (y al pulsar su interruptor, aunque se cuele otra vez a la izquierda)
    win.removeDockWidget(d["inspector"])
    win.addDockWidget(Qt.LeftDockWidgetArea, d["inspector"])
    win.splitDockWidget(d["effects"], d["inspector"], Qt.Vertical)
    d["inspector"].hide()
    pump(app, 0.3)
    win._interruptor("inspector")
    pump(app, 0.4)
    ok(lado_de_dock(win, "inspector") == "der" and not d["inspector"].isHidden(),
       "pulsar «Inspector» lo abre a la DERECHA (el lado de su interruptor)", f"(está en {lado_de_dock(win, 'inspector')})")
    der = [k for k in ("inspector", "palabras", "audio") if lado_de_dock(win, k) == "der"]
    ok("inspector" in der, "el lado derecho del visor no queda vacío con el Inspector abierto")
    captura(win, "1_lado_inspector_corregido")
    ok(not incoherentes(win), "tras corregirlo, fila y lado coinciden en todos", str(incoherentes(win)))
    # (el usuario ARRASTRA «Voz y texto» a la izquierda: su interruptor se muda a la fila izquierda y se recuerda)
    vt = d["palabras"]
    win._interruptor("palabras") if vt.isHidden() else None
    pump(app, 0.3)
    win.removeDockWidget(vt)
    vt._arrastre_usuario = True                # (como al soltarlo arrastrando con el ratón: se marca al soltarlo)
    win.addDockWidget(Qt.LeftDockWidgetArea, vt)
    vt.show()
    pump(app, 0.5)
    ok(lado_de_fila(win, "palabras") == "izq", "arrastrado a la izquierda, su interruptor pasa a la fila izquierda",
       f"(fila {lado_de_fila(win, 'palabras')})")
    ok(str(QSettings("EditorIA", "EditorIA").value("paneles/lado/palabras", "")) == "izq",
       "y se recuerda (paneles/lado/palabras = izq)")
    vt.hide()
    pump(app, 0.2)
    win._interruptor("palabras")
    pump(app, 0.4)
    ok(lado_de_dock(win, "palabras") == "izq", "al volver a pulsarlo se abre a la izquierda (donde lo dejaste)",
       f"(está en {lado_de_dock(win, 'palabras')})")
    captura(win, "1_lado_palabras_izquierda")
    ok(not incoherentes(win), "fila y lado siguen coincidiendo", str(incoherentes(win)))
    # (vuelta a la derecha arrastrándolo: el interruptor vuelve y la preferencia se borra)
    win.removeDockWidget(vt)
    vt._arrastre_usuario = True
    win.addDockWidget(Qt.RightDockWidgetArea, vt)
    win.tabifyDockWidget(d["inspector"], vt)
    vt.show()
    pump(app, 0.4)
    ok(lado_de_fila(win, "palabras") == "der" and
       QSettings("EditorIA", "EditorIA").value("paneles/lado/palabras") is None,
       "arrastrado de vuelta a la derecha, su interruptor vuelve a la fila derecha (lo de fábrica)")
    # (lo que mueve el programa no cambia la fila)
    win.removeDockWidget(d["memes"])
    win.addDockWidget(Qt.RightDockWidgetArea, d["memes"])
    pump(app, 0.3)
    ok(lado_de_fila(win, "memes") == "izq", "un movimiento del programa (no arrastrado) no muda el interruptor")
    win._paneles_a_su_sitio()
    pump(app, 0.3)
    ok(lado_de_dock(win, "memes") in ("izq", None), "y el panel vuelve a su lado", f"({lado_de_dock(win, 'memes')})")


def caso_secciones(app, win):
    print("— 2) secciones plegadas seguidas —", flush=True)
    from editoria.ui.tabs import Section
    fx = win.effects
    win.show_panel(fx)
    d = win.docks["effects"]
    win.resizeDocks([d], [420], Qt.Horizontal)              # (una debajo de otra, no lado a lado)
    pump(app, 0.4)
    if getattr(fx, "_modo_ancho", False):
        fx.poner_lado_a_lado(False)
    tabs = fx.tabs
    for s in tabs.secciones():
        s.set_open(s._titulo == "✦ Efectos", save=False)
    for s in fx.tabs_fx.secciones():
        s.set_open(False, save=False)
    pump(app, 0.6)
    captura(win, "2_efectos_plegados")
    secs = sorted((s for s in fx.findChildren(Section) if s.isVisibleTo(fx)),
                  key=lambda s: s.head.mapTo(fx, s.head.rect().topLeft()).y())
    huecos = []
    for a, b in zip(secs, secs[1:]):
        bajo_a = a.head.mapTo(fx, a.head.rect().bottomLeft()).y()
        alto_b = b.head.mapTo(fx, b.head.rect().topLeft()).y()
        dentro = a.body.isAncestorOf(b)
        if a.is_open() and not dentro:
            continue                               # (entre ellas va el contenido abierto de a)
        if dentro:
            bajo_a = max(bajo_a, max((c.head.mapTo(fx, c.head.rect().bottomLeft()).y() for c in secs
                                      if a.body.isAncestorOf(c) and c is not b and
                                      c.head.mapTo(fx, c.head.rect().topLeft()).y() < alto_b), default=bajo_a))
        hueco = alto_b - bajo_a
        if hueco > HUECO_MAX:
            huecos.append(f"{a._titulo if hasattr(a, '_titulo') else a.head.text()} → "
                          f"{b._titulo if hasattr(b, '_titulo') else b.head.text()}: {hueco} px")
    ok(not huecos, f"«Efectos» abierta y todo plegado: sin huecos de más de {HUECO_MAX} px entre cabeceras",
       str(huecos))
    ultima = secs[-1].head.mapTo(fx, secs[-1].head.rect().bottomLeft()).y() if secs else 0
    ok(fx.height() - ultima >= 0, "las secciones, arriba y seguidas (el alto libre, al final del panel)")


def caso_vacio(app, win):
    print("— 3) estados vacíos cortos —", flush=True)
    rs = getattr(win, "resumen", None)                  # 🗺 la barra resumen: sin clips, ni rastro (nada de franjas vacías)
    if rs is not None:
        rs.rehacer()
        pump(app, 0.2)
        ok(bool(win.ctrl.project.clips) or not rs.isVisible(), "sin clips, la barra resumen de la línea de tiempo "
           "no deja una franja vacía", f"visible={rs.isVisible()} clips={len(win.ctrl.project.clips)}")
    win.abrir_seccion("voz_texto", "transcripcion")
    pump(app, 0.8)
    tp = win.transcript
    captura(win, "3_transcripcion_vacia")
    grandes = []
    for w in tp.findChildren(QLabel) + tp.findChildren(QTextEdit):
        if not w.isVisibleTo(tp):
            continue
        txt = w.text() if isinstance(w, QLabel) else w.toPlainText()
        if "Sin transcripción" in txt and w.height() > VACIO_MAX:
            grandes.append(f"{type(w).__name__} {w.height()} px")
    for lw in tp.findChildren(QListWidget):
        if lw.isVisibleTo(tp) and lw.count() == 0 and lw.height() > VACIO_MAX:
            grandes.append(f"lista vacía {lw.height()} px")
    ok(not grandes, f"sin transcripción, el aviso mide como mucho {VACIO_MAX} px", str(grandes))
    boton = next((b for b in tp.findChildren(QAbstractButton) if b.isVisibleTo(tp) and "Transcribir" in b.text()),
                 None)
    ok(boton is not None, "y ofrece «Transcribir»")
    if boton is not None:
        boton.click()
        pump(app, 0.4)
        ok(win.voz_texto.abierta() == "transcribir", "«Transcribir» abre «1 · Transcribir»")
        win.abrir_seccion("voz_texto", "transcripcion")
        pump(app, 0.3)
    ok(bool(boton and boton.toolTip()) or bool([w for w in tp.findChildren(QLabel)
                                                if w.isVisibleTo(tp) and w.toolTip()]),
       "la explicación, en el tooltip")


def arrastrar(app, win, pasos):
    """Simula un arrastre con el botón izquierdo pulsado y al final lo suelta (como el usuario con un divisor). Cada
    paso: ([docks], [altos]) = resizeDocks · ([dock], None) = ese dock 2 px menos (el divisor de la línea de tiempo) ·
    ("ventana", None) = la ventana 2 px más alta · ("entre", n) = n px de «Limpieza y mezcla» a «Voz y texto»."""
    vt, au = win.docks["palabras"], win.docks["audio"]
    win._boton_pulsado = lambda: True
    try:
        for a, b in pasos:
            if a == "ventana":
                win.resize(win.width(), win.height() + 2)
            elif a == "entre":
                win.resizeDocks([vt, au], [vt.height() + b, au.height() - b], Qt.Vertical)
            elif b is None:
                win.resizeDocks(a, [a[0].height() - 2], Qt.Vertical)
            else:
                win.resizeDocks(a, b, Qt.Vertical)
            pump(app, 0.03)
    finally:
        del win._boton_pulsado                   # (se suelta el botón: el próximo arrastre se mide desde cero)
        pump(app, 0.3)
    if getattr(win, "_arrastre_divisor", None) is not None:
        win._fin_arrastre_divisor()


def caso_ceder(app, win):
    print("— 4) alto cedido al vecino —", flush=True)
    d = win.docks
    vt, au = d["palabras"], d["audio"]
    for k in ("inspector", "palabras", "audio"):
        d[k].hide()
    pump(app, 0.2)
    win.removeDockWidget(vt)
    win.removeDockWidget(au)
    win.addDockWidget(Qt.RightDockWidgetArea, vt)
    win.splitDockWidget(vt, au, Qt.Vertical)
    vt.show()
    au.show()
    win.audio_panel.abrir("limpieza")
    for s in getattr(win.voice, "tabs").secciones():
        s.set_open(False, save=False)
    pump(app, 0.3)
    total = vt.height() + au.height()
    win.resizeDocks([vt, au], [int(total * 0.35), total - int(total * 0.35)], Qt.Vertical)   # (como en su captura)
    pump(app, 1.2)
    captura(win, "4_apilados")
    vac = (au.height() - fondo_contenido(win.audio_panel, au)) / max(1, au.height())
    usa = usa_alto(win._pal_tabs)
    print(f"   «Limpieza y mezcla» {au.height()} px, {vac:.0%} vacío; «Voz y texto» {vt.height()} px "
          f"(usa más alto: {usa})", flush=True)
    ok(not (vac > VACIO_FRAC and usa), f"«Limpieza y mezcla» casi plegada no deja más del {VACIO_FRAC:.0%} vacío "
                                       "teniendo debajo/encima un vecino que lo usa", f"({vac:.0%} vacío)")
    # (lo que pones a mano con el divisor se respeta: un arrastre de verdad, con el botón pulsado)
    win._ceder_alto()                            # (vigila el divisor de esta columna)
    arrastrar(app, win, [([vt, au], [300, 560])])
    alto = au.height()
    if hasattr(win, "_ceder_alto"):
        win._ceder_alto()
    pump(app, 0.5)
    ok(abs(au.height() - alto) <= 8, "lo puesto a mano con el divisor no se pisa", f"({alto} → {au.height()})")
    if hasattr(win, "_altos_a_mano"):
        win._altos_a_mano.clear()
    # (al desplegar, vuelve a pedir su alto)
    win.audio_panel.abrir("sonoridad")
    pump(app, 0.8)
    vac = (au.height() - fondo_contenido(win.audio_panel, au)) / max(1, au.height())
    ok(not (vac > VACIO_FRAC and usa_alto(win._pal_tabs)), "con otra sección pequeña abierta, tampoco",
       f"({vac:.0%} vacío)")
    ok(not incoherentes(win), "fila y lado coinciden", str(incoherentes(win)))


def caso_dijiste(app, win):
    print("— 5) «Dijiste…» —", flush=True)
    cp = win.clips
    win.abrir_seccion("palabras", "palabras")
    win._pal_tabs.setCurrentWidget(cp)
    d = win.docks
    for k in ("audio",):
        d[k].hide()
    vt = d["palabras"]
    vt.show()
    vt.raise_()
    pump(app, 1.5)                                     # (que pase su relectura al mostrarse)
    cp._temporizador.stop()
    frases = ["…y en la escena final el objeto explota justo cuando la persona entra por la puerta…",
              "…la persona dice que el lugar es enorme y que se puede recorrer entero…",
              "…ese vehículo aparece dos veces en el tráiler y otra más al final…",
              "…el personaje principal vuelve a salir en la segunda parte…"]
    cp.menciones = [{"term": t, "count": n, "hits": [{"src": 5.0 + i * 7 + j, "tl": 5.0 + i * 7 + j,
                                                      "context": frases[i]} for j in range(n)]}
                    for i, (t, n) in enumerate((("Objeto", 3), ("Lugar", 2), ("Vehículo", 2), ("Personaje", 1)))]
    cp._pintar_menciones(None)
    cp._elegir_mencion(0, buscar=False)
    win.resizeDocks([vt], [520], Qt.Horizontal)
    pump(app, 0.8)
    captura(win, "5_dijiste")
    lm = cp.lista_menciones
    # a) cada fila usa su ancho: lo pintado llega cerca de los 👍 👎
    img = lm.viewport().grab().toImage()
    vacias = []
    for f in range(lm.count()):
        if f == lm.currentRow() or lm.item(f).isHidden():
            continue
        r = lm.visualItemRect(lm.item(f))
        zona_der = r.right() - 2 * 26 - 4
        fondo = img.pixelColor(r.left() + 1, r.center().y())
        ultimo = r.left()
        for x in range(r.left(), zona_der):
            for y in range(r.top() + 2, r.bottom() - 1, 2):
                c = img.pixelColor(x, y)
                if abs(c.red() - fondo.red()) + abs(c.green() - fondo.green()) + abs(c.blue() - fondo.blue()) > 60:
                    ultimo = x
                    break
        libre = (zona_der - ultimo) / max(1, zona_der - r.left())
        if libre > 0.35:
            vacias.append(f"fila {f}: {libre:.0%} libre")
    ok(not vacias, "cada fila de «Dijiste…» usa su ancho (la frase en gris entre la carpeta y 👍 👎)", str(vacias))
    tips = [lm.item(f).toolTip() for f in range(lm.count()) if not lm.item(f).isHidden()]
    ok(all(any(fr.strip("…")[:20] in t for fr in frases) for t in tips), "y la frase entera, en el tooltip")
    # b) sin hueco entre la lista de palabras y ◀ ▶ (la lista mide lo que su contenido, hasta un tope)
    abajo_lista = lm.mapTo(cp, lm.rect().bottomLeft()).y()
    arriba_nav = cp.btn_ant.mapTo(cp, cp.btn_ant.rect().topLeft()).y()
    filas = sum(lm.visualItemRect(lm.item(f)).height() for f in range(lm.count()) if not lm.item(f).isHidden())
    sobra = lm.viewport().height() - filas
    ok(arriba_nav - abajo_lista <= HUECO_MAX, f"entre la lista de palabras y ◀ ▶ como mucho {HUECO_MAX} px",
       f"({arriba_nav - abajo_lista} px)")
    ok(sobra <= 24, "la lista de palabras no deja alto vacío dentro (crece con su contenido)", f"({sobra} px vacíos)")
    lmo = cp.lista_momentos
    ok(lmo.height() >= 2 * 24, "la lista de frases de abajo se queda el resto", f"({lmo.height()} px)")
    # c) con el panel bajo, la cabecera y sus botones a la vista
    au = d["audio"]                                # (bajo: con «Limpieza y mezcla» debajo y «Voz y texto» a 280 px)
    win.removeDockWidget(au)
    win.splitDockWidget(vt, au, Qt.Vertical)
    au.show()
    win.audio_panel.abrir("mezcla")
    pump(app, 0.4)
    if hasattr(win, "_altos_a_mano"):
        win._altos_a_mano.add(frozenset((vt.objectName(), au.objectName())))   # (como puesto a mano)
    win.resizeDocks([vt, au], [280, vt.height() + au.height() - 280], Qt.Vertical)
    pump(app, 0.8)
    print(f"   «Voz y texto» a {vt.height()} px", flush=True)
    zona = vt.widget()
    if isinstance(zona, QScrollArea):              # (el peor caso: la zona del panel desplazada hasta abajo)
        zona.verticalScrollBar().setValue(zona.verticalScrollBar().maximum())
        pump(app, 0.2)
    captura(win, "5_dijiste_bajo")
    tapados = []
    for b in (cp.btn_todo, cp.btn_otras, cp.btn_todas, cp.btn_amplia, cp.btn_glosario, cp.btn_recalc):
        vis = b.visibleRegion().boundingRect()
        if vis.height() < b.height() - 1:
            tapados.append(f"{b.text()} ({vis.height()}/{b.height()} px)")
    ok(not tapados, "con el panel bajo, la cabecera de «Dijiste…» y sus botones se quedan a la vista", str(tapados))
    au.hide()
    pump(app, 0.3)


EMOJI = __import__("re").compile("[🀀-🫿☀-➿⬀-⯿⏩-⏺◈"   # (◈; las flechas ▸ ▾ de las cabeceras sí valen)
                                 "⟰-⟿️＋]")


def caso_paneles(app, win):
    """6) Los paneles con el estilo nuevo (Mezcla y música, Medios, Memes, Descargas): botones y pestañas sin emojis de
    color (iconos monocromos), ninguna lista vacía enorme, los botones de solo icono con su tooltip y las acciones de
    cada archivo de Medios a la vista al pasar el ratón."""
    print("— 6) paneles con el estilo nuevo —", flush=True)
    from PySide6.QtWidgets import QTabWidget
    d = win.docks
    paneles = (("Mezcla y música", lambda: win.abrir_seccion("audio", "mezcla"), lambda: win.audio_panel),
               ("Medios", lambda: win.show_panel(win.library), lambda: win.library),
               ("Memes", lambda: win.show_panel(d["memes"].panel), lambda: d["memes"].panel),
               ("Descargas", lambda: win.show_panel(d["descargas_web"].panel), lambda: d["descargas_web"].panel),
               ("IA", lambda: win.abrir_herramienta_ia("broll"), lambda: win.herramientas.widget("ia_broll")))
    for nombre, abrir, panel_de in paneles:
        abrir()
        pump(app, 0.8)
        pan = panel_de()
        if nombre == "Descargas":                     # (la pestaña de lo descargado)
            pan.pestanas.setCurrentIndex(pan.pestanas.count() - 1)
            pump(app, 0.3)
        captura(win, f"6_{nombre.split()[0].lower()}")
        con_emoji = [b.text() for b in pan.findChildren(QAbstractButton)
                     if b.isVisibleTo(pan) and EMOJI.search(b.text() or "")]
        for t in pan.findChildren(QTabWidget):
            if t.isVisibleTo(pan):
                con_emoji += [t.tabText(i) for i in range(t.count()) if EMOJI.search(t.tabText(i))]
        if nombre != "IA":                        # (IA aún con el estilo viejo: su tanda de iconos es otra)
            ok(not con_emoji, f"{nombre}: botones y pestañas sin emojis de color (iconos monocromos)", str(con_emoji))
        sin_tip = [type(b).__name__ for b in pan.findChildren(QAbstractButton)
                   if b.isVisibleTo(pan) and not (b.text() or "").strip() and not b.toolTip()]
        ok(not sin_tip, f"{nombre}: todo botón de solo icono con su tooltip", str(sin_tip))
        from PySide6.QtWidgets import QTreeWidget
        vacias = [f"{type(lw).__name__} {lw.height()} px" for lw in pan.findChildren(QListWidget)
                  if lw.isVisibleTo(pan) and lw.count() == 0 and lw.height() > VACIO_MAX]
        vacias += [f"{type(tw).__name__} {tw.height()} px" for tw in pan.findChildren(QTreeWidget)
                   if tw.isVisibleTo(pan) and tw.topLevelItemCount() == 0 and tw.height() > VACIO_MAX]
        ok(not vacias, f"{nombre}: ninguna lista vacía de más de {VACIO_MAX} px (estado vacío en una línea)",
           str(vacias))
        # (24/11: «IA» = la pestaña de herramientas de B-roll, de «Edita desde tu voz» › Más herramientas)
        estirados = []
        for b in pan.findChildren(QAbstractButton):
            if not b.isVisibleTo(pan) or b.height() <= 0:
                continue
            natural = b.heightForWidth(b.width()) if b.hasHeightForWidth() else b.sizeHint().height()
            if b.height() > max(40, natural + 10):
                estirados.append(f"«{(b.text() or b.toolTip())[:30]}» {b.height()} px (pide {natural})")
        ok(not estirados, f"{nombre}: ningún botón estirado a lo alto", str(estirados))
    win.herramientas.cerrar("ia_broll")             # (que su pestaña junto al Inspector no cambie las columnas de luego)
    pump(app, 0.4)
    from editoria.ui import library as L
    deleg = win.library.tree.itemDelegateForColumn(0)
    ok(isinstance(deleg, getattr(L, "_AccionesFila", ())), "Medios: cada archivo con «poner en el cabezal» y "
                                                            "«quitar» a la vista al pasar el ratón")


def caso_reservas(app, win):
    """7) Las reservas de la revisión (Fable): Restablecer distribución vuelve a los lados y filas de fábrica; «puesto a
    mano» solo si el total de la columna no cambia (y se olvida al cambiar sus paneles); NoDockWidgetArea sin botón
    baja el arrastre; un panel solo en un lado no se queda a 200 px; las pestañas de «Palabras clave» nunca recortadas."""
    print("— 7) reservas de la revisión —", flush=True)
    d = win.docks
    st = QSettings("EditorIA", "EditorIA")
    # a) mudar paneles de lado y «Restablecer distribución»
    for k in ("palabras", "audio", "inspector"):
        if d[k].isHidden():
            win._interruptor(k)
        pump(app, 0.2)
        win.removeDockWidget(d[k])
        d[k]._arrastre_usuario = True
        win.addDockWidget(Qt.LeftDockWidgetArea, d[k])
        d[k].show()
        pump(app, 0.3)
        if getattr(d[k], "_arrastre_usuario", False):    # (Qt no avisó del sitio nuevo: como al soltarlo el usuario)
            win._panel_cambio_de_lado(k, Qt.LeftDockWidgetArea)
            pump(app, 0.2)
    ok(all(lado_de_fila(win, k) == "izq" for k in ("palabras", "audio", "inspector")),
       "(preparación: tres paneles mudados a la izquierda con su interruptor)",
       str({k: (lado_de_fila(win, k), lado_de_dock(win, k)) for k in ("palabras", "audio", "inspector")}))
    pump(app, 0.4)
    ok(d["palabras"].width() >= 250 or d["inspector"].width() >= 250,
       "el panel mudado no se queda en una tira de 200 px", f"({d['inspector'].width()} px)")
    win.reset_layout()
    pump(app, 1.0)
    fabrica = [k for k in win.interruptores if lado_de_fila(win, k) != win._lado_de_fabrica(k)
               and not win.interruptores[k].isHidden()]
    ok(not fabrica, "«Restablecer distribución»: cada interruptor en la fila de su lado de fábrica", str(fabrica))
    st.beginGroup("paneles/lado")
    quedan = st.allKeys()
    st.endGroup()
    ok(not quedan, "y se olvidan los lados elegidos (paneles/lado/*)", str(quedan))
    ok(not incoherentes(win), "y fila y lado coinciden en todos", str(incoherentes(win)))
    # b) «puesto a mano» solo con el total de la columna igual
    vt, au = d["palabras"], d["audio"]
    for k in ("inspector", "palabras", "audio"):
        d[k].hide()
    win.removeDockWidget(vt)
    win.removeDockWidget(au)
    win.addDockWidget(Qt.RightDockWidgetArea, vt)
    win.splitDockWidget(vt, au, Qt.Vertical)
    vt.show()
    au.show()
    pump(app, 0.6)
    win._altos_a_mano.clear()
    win._ceder_alto()
    firma = frozenset((vt.objectName(), au.objectName()))
    # (arrastre LENTO del divisor de la línea de tiempo: 12 pasos de 2 px con el botón pulsado; el total de la columna
    #  cambia poco a poco y ningún paso suelto puede contar como «a mano»)
    tl = d["timeline"]
    total0 = vt.height() + au.height()
    arrastrar(app, win, [([tl], None)] * 12)
    cambio = vt.height() + au.height() - total0
    if abs(cambio) < 8:                          # (si la columna no llega a la línea de tiempo: estirar la ventana)
        arrastrar(app, win, [("ventana", None)] * 12)
        cambio = vt.height() + au.height() - total0
    ok(abs(cambio) >= 8, "el arrastre lento cambia de verdad el alto de la columna", f"({cambio:+d} px)")
    ok(firma not in win._altos_a_mano, "arrastrar DESPACIO el divisor de la línea de tiempo (pasos de 2 px) no cuenta "
                                       "como a mano", f"({cambio:+d} px en 12 pasos)")
    # (un solo paso de 2 px entre los dos paneles tampoco: no pasa de la tolerancia)
    arrastrar(app, win, [("entre", 2)])
    ok(firma not in win._altos_a_mano, "2 px entre los dos paneles (menos que la tolerancia) no cuentan")
    # (el divisor ENTRE los dos paneles, despacio: el total igual y lo acumulado pasa de la tolerancia → sí)
    arrastrar(app, win, [("entre", 2)] * 6)
    ok(firma in win._altos_a_mano, "arrastrar despacio el divisor entre los dos paneles (mismo total) sí cuenta")
    d["inspector"].show()
    win.tabifyDockWidget(vt, d["inspector"])
    pump(app, 0.3)
    win._ceder_alto()
    au.hide()
    pump(app, 0.3)
    win._ceder_alto()
    ok(firma not in win._altos_a_mano, "la marca se olvida al cambiar los paneles de la columna")
    # c) NoDockWidgetArea sin botón pulsado
    d["memes"]._arrastre_usuario = True
    win._panel_cambio_de_lado("memes", Qt.NoDockWidgetArea)
    ok(not d["memes"]._arrastre_usuario, "un panel que se suelta sin el ratón pulsado no queda como «arrastrado»")
    # d) pestañas de «Palabras clave» a 200 px: enteras o solo su icono, nunca recortadas
    win.reset_layout()
    pump(app, 0.8)
    win.abrir_seccion("palabras", "palabras")
    pump(app, 0.4)
    for ancho in (200, 260, 480):
        win.resizeDocks([d["palabras"]], [ancho], Qt.Horizontal)
        pump(app, 0.5)
        pal = win._pal_tabs
        bar = pal.tabBar()
        cortadas = []
        for i in range(pal.count()):
            t = pal.tabText(i)
            if t and bar.fontMetrics().horizontalAdvance(t) > bar.tabRect(i).width() - 6:
                cortadas.append(t)
            if not t and (pal.tabIcon(i).isNull() or not pal.tabToolTip(i)):
                cortadas.append(f"pestaña {i} sin nombre, icono o tooltip")
        ok(not cortadas, f"a {d['palabras'].width()} px, las pestañas «Dijiste… · Carpetas · Buscar material» sin "
                         "recortar", str(cortadas))
    captura(win, "7_palabras_estrecho")


def caso_cabeceras(app, win):
    """8) Una sola cabecera de sección (mismo alto ±1 px) en Limpieza y mezcla, Voz y texto, Transiciones y efectos y el
    Inspector; contenido alineado con su cabecera (8 px de sangría); «Dijiste…»: botones de un solo alto, alineados
    por fila; Inspector sin clip: sin la fila de pestañas grises."""
    print("— 8) cabeceras y rejilla común —", flush=True)
    from PySide6.QtWidgets import QToolButton, QPushButton
    from editoria.ui import diseno as D
    from editoria.ui.tabs import Section
    from editoria.ui.inspector_secciones import Seccion
    d = win.docks
    win.reset_layout()
    pump(app, 0.8)
    alturas, desalineadas = {}, []

    def medir(nombre, dock):
        win.resizeDocks([dock], [420], Qt.Horizontal)   # (con sitio: la sangría solo cede cuando no hay ancho)
        pump(app, 0.6)
        for b in dock.findChildren(QToolButton) + dock.findChildren(QPushButton):
            if b.isVisibleTo(dock) and b.objectName() in ("sectionhead", "seccionacordeon"):
                alturas.setdefault(b.height(), []).append(f"{nombre}: {b.text()[:24]}")
        for s in dock.findChildren(Section) + dock.findChildren(Seccion):
            if not s.isVisibleTo(dock) or not s.is_open() or not s.body.isVisibleTo(dock):
                continue
            dx = s.body.mapTo(dock, s.body.rect().topLeft()).x() - s.head.mapTo(dock, s.head.rect().topLeft()).x()
            if abs(dx - D.px(D.SANGRIA_SECCION)) > 2:
                desalineadas.append(f"{nombre}: «{s.head.text()[:20]}» contenido a {dx} px de su cabecera")
    win.abrir_seccion("audio", "limpieza")
    for s in win.voice.tabs.secciones():
        s.set_open(True, save=False)
    medir("Limpieza y mezcla", d["audio"])
    win.abrir_seccion("audio", "mezcla")
    medir("Mezcla", d["audio"])
    win.abrir_seccion("voz_texto", "transcripcion")
    medir("Voz y texto", d["voz_texto"])
    win.show_panel(win.effects)
    for s in win.effects.tabs.secciones():
        s.set_open(True, save=False)
    medir("Transiciones y efectos", d["effects"])
    win.timeline.set_selection([])
    win._interruptor("inspector") if d["inspector"].isHidden() else None
    medir("Inspector", d["inspector"])
    captura(win, "8_cabeceras")
    ok(len(alturas) == 1 or (max(alturas) - min(alturas) <= 1),
       "todas las cabeceras de sección miden lo mismo (±1 px)", str({k: v[:3] for k, v in alturas.items()}))
    ok(not desalineadas, "el contenido de cada sección, alineado bajo su cabecera (8 px)", str(desalineadas[:5]))
    ins = win.inspector
    ok(ins.fila_pestanas.isHidden(), "Inspector sin clip: sin la fila de pestañas grises (solo «Proyecto»)")
    # «Dijiste…»: un solo alto y alineados por fila
    win.abrir_seccion("voz_texto", "palabras")
    cp = win.clips
    win._pal_tabs.setCurrentWidget(cp)
    for ancho in (200, 360, 520):
        win.resizeDocks([d["palabras"]], [ancho], Qt.Horizontal)
        pump(app, 0.6)
        botones = [b for fila in cp._filas_dijiste for b in fila] + [cp.btn_fila_kw] +             cp.sel_modo.findChildren(QToolButton)
        altos = sorted({b.height() for b in botones if b.isVisibleTo(cp)})
        ok(altos and altos[-1] - altos[0] <= 1, f"«Dijiste…» a {d['palabras'].width()} px: todos sus botones con "
                                                 "el mismo alto", str(altos))
        torcidas = []
        for fila in cp._filas_dijiste + [[cp.btn_amplia, cp.btn_fila_kw]]:
            ys = {b.mapTo(cp, b.rect().center()).y() for b in fila if b.isVisibleTo(cp)}
            if ys and max(ys) - min(ys) > 2 and max(ys) - min(ys) < 20:
                torcidas.append(sorted(ys))
        ok(not torcidas, "y alineados por fila (misma base)", str(torcidas))
        sin_tip = [b.accessibleName() or "?" for b in botones if b.isVisibleTo(cp) and not b.toolTip()]
        ok(not sin_tip, "cada botón con su tooltip", str(sin_tip))
    captura(win, "8_dijiste")


ERRORES: list[str] = []


def caso_seleccion(app, win):
    """9) Cambiar la selección de la línea de tiempo con los paneles abiertos (Efectos, Inspector) no lanza ninguna
    excepción (antes: «_Etiquetas no tiene setToolTip» en cada cambio)."""
    print("— 9) cambiar la selección sin errores —", flush=True)
    antes = len(ERRORES)
    win.show_panel(win.effects)
    pump(app, 0.3)
    nuevos_ids = set(win.ctrl.project.clips)
    win.ctrl.add_text(0.0, 2.0, "Texto")
    ids = [i for i in win.ctrl.project.clips if i not in nuevos_ids]
    for sel in (ids, [], ids):
        win.timeline.set_selection(sel)
        pump(app, 0.3)
    ok(len(ERRORES) == antes, "cambiar la selección con Efectos abierto no lanza excepciones", str(ERRORES[antes:][:2]))


def main():
    import traceback
    sys.excepthook = lambda t, v, tb: ERRORES.append("".join(traceback.format_exception(t, v, tb))[-600:])
    app = QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    # (nada de la ventana del usuario: distribución de fábrica, sin «A todo el alto», lados de fábrica)
    for k in ("ventana/paneles", "geometry", "agrupados/voz_texto", "agrupados/audio"):
        st.remove(k)
    st.setValue("ventana/biblioteca_alto", "false")
    st.beginGroup("paneles/lado")
    st.remove("")
    st.endGroup()
    st.setValue("espacios/actual", "youtube")
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 1000)
    win.show()
    pump(app, 1.5)
    win.resize(1600, 1000)
    pump(app, 0.5)
    print(f"(ventana {win.width()}×{win.height()} · etiqueta «{ETIQUETA}»)", flush=True)
    for caso in (caso_lado, caso_secciones, caso_vacio, caso_ceder, caso_dijiste, caso_paneles, caso_reservas, caso_cabeceras, caso_seleccion):
        try:
            caso(app, win)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FALLOS.append(f"{caso.__name__}: {e!r}")
    win.ctrl.undo_stack.setClean()
    win.close()
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s)")
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
