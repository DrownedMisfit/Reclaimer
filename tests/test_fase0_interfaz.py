"""
Fase 0 de la reorganización de la interfaz (notas_claude/PROPUESTA_INTERFAZ.md, apartado e: «Arreglos de la sonda»):
  1. tras pasar por 🎬 Escenas y 🧭 Montaje guiado la ventana pedía ~2292 px (más que la pantalla) y seguía así al volver
     a Editar, con los laterales en ~175 px → recorrer las 10 páginas (de una en una desde Editar y seguidas) y volver:
     el ancho mínimo y el ancho de la ventana nunca pasan de la pantalla y los laterales vuelven a su ancho;
  2. después de 🔑 Palabras clave, su barra de pestañas «Buscar material · Carpetas · Descargado» quedaba pintada encima
     de la cabecera del visor (Audio, Transcripción) y de la barra de Miniatura → en cada página: los paneles a la vista
     son siempre los mismos (vengas de donde vengas), toda barra de pestañas a la vista es de paneles a la vista, ninguna
     barra pisa el centro y los grupos de pestañas de la página tienen su barra a la vista;
  3. exportar sin «📝 Crear también la descripción (.txt)» solo crea el video; con ella, también el .txt (y se recuerda).
Pantalla de prueba 1920×1080 (offscreen:configfile). Carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_fase0_interfaz.py
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
_CFG = f"_pruebas_tmp/pantalla_fase0_{os.getpid()}.json"
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
from PySide6.QtCore import QRect, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabBar  # noqa: E402

FALLOS = []
# (agrupación 20/11: Palabras clave, Audio y Transcripción ya no son páginas: abren «Voz y texto» / «Audio» —ver
#  test_nada_perdido—; aquí, las que cambian de pantalla y las que abren un panel de Editar)
PAGINAS = ["media", "effects", "edit", "scenes", "guided", "thumb", "deliver"]


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in list(st.allKeys()):
        if k.startswith(("paneles_pestana/", "paneles/lado/")) or k in ("ventana/paneles", "geometry", "exportar/crear_descripcion"):
            st.remove(k)
    st.setValue("ventana/biblioteca_alto", "false")       # (la línea de tiempo a todo el ancho, como de fábrica)
    st.setValue("descripcion/pie", "Pie de prueba")        # (para que la descripción nunca salga vacía)
    import editoria.ui.audit_dialog as AD
    import editoria.ui.main_window as MW
    AD.revision_previa = lambda _w: True                   # (🚀 Entrega: sin la revisión previa ni diálogos modales)
    MW.ExportDialog.exec = lambda self: 0
    win = MW.MainWindow()
    win.show()
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 1.0)
    win.go_page("edit")
    pump(app, 0.6)
    D = win.docks

    def vis():
        return sorted(k for k, d in D.items() if not d.isHidden() and not d.isFloating())

    def laterales():
        out = {}
        for area, nombre in ((Qt.LeftDockWidgetArea, "izq"), (Qt.RightDockWidgetArea, "der")):
            ds = [d for d in D.values() if d.isVisible() and not d.isFloating() and win.dockWidgetArea(d) == area
                  and not d.visibleRegion().isEmpty()]
            out[nombre] = max((d.width() for d in ds), default=0)
        return out

    def barras():
        return [b for b in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly) if b.isVisible()]

    def anchos_ok(donde):
        m = win.minimumSizeHint().width()
        chk(m <= ANCHO and win.width() <= ANCHO, f"{donde}: la ventana cabe (mínimo {m} px, ancho {win.width()} px "
            f"≤ {ANCHO})")

    def nada_de_otra_pagina(donde):
        problemas = []
        usados = {}
        punteros = {shiboken6.getCppPointer(d)[0]: k for k, d in D.items()}   # (✂ Corte de audio se crea después)
        centro = QRect(win.centralWidget().mapTo(win, win.centralWidget().rect().topLeft()),
                       win.centralWidget().size())
        for b in barras():
            claves = [punteros.get(b.tabData(i)) for i in range(b.count())]
            for i, k in enumerate(claves):
                d = D.get(k) if k else None
                if d is None or d.isHidden() or d.isFloating():
                    problemas.append(f"barra «{b.tabText(i)}» de un panel que no está a la vista")
                elif k in usados:
                    problemas.append(f"«{b.tabText(i)}» en dos barras")
                usados[k] = b
            if b.geometry().intersects(centro):
                problemas.append(f"barra {[b.tabText(i) for i in range(b.count())]} encima del centro")
        for k in vis():                                # (cada grupo de pestañas a la vista, con su barra a la vista)
            grupo = [o for o in win.tabifiedDockWidgets(D[k]) if not o.isHidden() and not o.isFloating()]
            if grupo and k not in usados:
                problemas.append(f"«{win._nombre_panel(D[k])}» en pestañas sin barra a la vista")
        pila = win.central_stack
        for i in range(pila.count()):
            w = pila.widget(i)
            if w is not pila.currentWidget() and w.isVisible():
                problemas.append(f"{type(w).__name__} a la vista fuera de su página")
        chk(not problemas, f"{donde}: nada de otra página a la vista {problemas[:4]}")

    def ir(pg):
        win.go_page(pg)
        pump(app, 0.5)

    V0, L0 = vis(), laterales()
    print(f"Editar: laterales {L0}")
    anchos_ok("Editar al abrir")
    nada_de_otra_pagina("Editar al abrir")
    propios = {}                                       # (los paneles a la vista de cada página, entrando desde Editar)

    print("— cada página desde Editar y vuelta —")
    for pg in PAGINAS:
        ir(pg)
        propios[pg] = vis()
        anchos_ok(pg)
        nada_de_otra_pagina(pg)
        ir("edit")
        anchos_ok(f"{pg}→Editar")
        nada_de_otra_pagina(f"{pg}→Editar")
        v = vis()
        # (🧭 Montaje guiado deja su panel en Editar, debajo del Inspector: es un panel de Editar que la página enseña)
        chk(set(v) - {"guided"} == set(V0) - {"guided"}, f"{pg}→Editar: los mismos paneles ({set(v) ^ set(V0)})")
        lat = laterales()
        chk(all(abs(lat[s] - L0[s]) <= 8 for s in L0), f"{pg}→Editar: laterales como al principio ({lat} / {L0})")

    print("— las 10 seguidas y vuelta a Editar —")
    for pg in PAGINAS:
        ir(pg)
        anchos_ok(f"seguidas: {pg}")
        nada_de_otra_pagina(f"seguidas: {pg}")
        if pg not in ("edit", "media", "guided", "deliver", "effects"):   # (estas enseñan Editar: dependen de lo de antes)
            chk(vis() == propios[pg], f"seguidas: {pg} con sus paneles ({set(vis()) ^ set(propios[pg])})")
    ir("edit")
    anchos_ok("seguidas → Editar")
    nada_de_otra_pagina("seguidas → Editar")
    lat = laterales()
    chk(all(abs(lat[s] - L0[s]) <= 8 for s in L0), f"seguidas → Editar: laterales como al principio ({lat} / {L0})")

    print("— los pasos de la sonda —")
    for camino in (("scenes", "guided"), ("thumb", "scenes"), ("scenes", "thumb"), ("guided", "thumb"),
                   ("effects", "scenes"), ("thumb", "effects", "scenes")):
        for pg in camino:
            ir(pg)
            nada_de_otra_pagina(" → ".join(camino[:camino.index(pg) + 1]))
            if pg in propios and pg not in ("guided", "effects"):
                chk(vis() == propios[pg], f"{' → '.join(camino[:camino.index(pg) + 1])}: sus paneles "
                    f"({set(vis()) ^ set(propios[pg])})")
            anchos_ok(" → ".join(camino[:camino.index(pg) + 1]))
        ir("edit")
        anchos_ok(" → ".join(camino) + " → Editar")
        lat = laterales()
        chk(all(abs(lat[s] - L0[s]) <= 8 for s in L0), f"{' → '.join(camino)} → Editar: laterales "
            f"({lat} / {L0})")

    print("— el barrido de barras se puede llamar las veces que sea (revisión) —")

    def firma_barras():
        return sorted(tuple(b.tabData(i) for i in range(b.count())) for b in barras() if b.count())
    for pg in ("edit",):
        ir(pg)
        antes = firma_barras()
        win._barras_sueltas_fuera()
        f1 = firma_barras()
        win._barras_sueltas_fuera()
        f2 = firma_barras()
        pump(app, 0.4)
        chk(antes == f1 == f2 == firma_barras() and len(antes) >= 1,
            f"{pg}: llamada directa ×1 y ×2 deja las mismas barras ({len(antes)}, {len(f1)}, {len(f2)})")
        nada_de_otra_pagina(f"{pg} tras el barrido directo")
    ir("edit")

    print("— maximizada, pantalla completa, 1300×760 y un panel suelto —")
    for modo in ("max", "completa", "1300"):
        if modo == "max":
            win.showMaximized()
        elif modo == "completa":
            win.showFullScreen()
        else:
            win.showNormal()
            pump(app, 0.3)
            win.resize(1300, 760)
        pump(app, 0.6)
        w0 = win.width()
        for pg in ("scenes", "thumb", "edit"):
            ir(pg)
            anchos_ok(f"{modo}: {pg}")
            nada_de_otra_pagina(f"{modo}: {pg}")
        chk(abs(win.width() - w0) <= 4, f"{modo}: tras las páginas, la ventana como estaba ({win.width()} / {w0})")
    win.showNormal()
    pump(app, 0.3)
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 0.6)
    D["history"].show()
    D["history"].setFloating(True)
    pump(app, 0.3)
    ir("scenes")
    chk(D["history"].isFloating() and not D["history"].isHidden(), "el panel suelto sigue suelto en Escenas")
    ir("edit")
    nada_de_otra_pagina("panel suelto → Escenas → Editar")
    chk(D["history"].isFloating() and not D["history"].isHidden(), "…y en Editar")
    D["history"].setFloating(False)
    pump(app, 0.3)

    print("— 📝 la descripción al exportar —")
    carpeta = tempfile.mkdtemp(prefix="exportar_", dir=_TMP)
    video = os.path.join(carpeta, "Mi video.mp4")
    txt = os.path.join(carpeta, "Mi video.descripcion.txt")
    from editoria.export.ffmpeg_export import ExportOptions

    def exportar_simulado():
        win.go_page("deliver")
        pump(app, 0.2)
        dlg = win._export_dlg
        dlg._opts = ExportOptions(path=video, width=1920, height=1080, fps=30.0, codec="h264", encoder="cpu",
                                  bitrate_mbps=10)
        dlg._partial = os.path.join(carpeta, "Mi video.parcial.mp4")
        with open(dlg._partial, "wb") as f:
            f.write(b"x" * 64)
        dlg._t0 = time.time()
        dlg._finished(0, None)                         # (como si FFmpeg hubiera terminado bien)
        return dlg

    dlg = exportar_simulado()
    chk(not dlg.desc_txt.isChecked(), "«📝 Crear también la descripción (.txt)» viene apagada")
    chk(bool(dlg.desc_txt.toolTip()), "…con su explicación en el tooltip")
    chk(os.path.isfile(video) and not os.path.exists(txt), f"sin la casilla: solo el video ({os.listdir(carpeta)})")
    dlg.desc_txt.setChecked(True)
    dlg.close()
    os.remove(video)
    dlg = exportar_simulado()
    chk(dlg.desc_txt.isChecked(), "la casilla se recuerda")
    chk(os.path.isfile(video) and os.path.isfile(txt), f"con la casilla: el video y el .txt ({os.listdir(carpeta)})")
    if os.path.isfile(txt):
        with open(txt, encoding="utf-8") as f:
            chk("Pie de prueba" in f.read(), "…con la descripción dentro")
    dlg.desc_txt.setChecked(False)
    dlg.close()

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
