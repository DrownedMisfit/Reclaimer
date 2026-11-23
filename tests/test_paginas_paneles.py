"""
Las antiguas páginas con paneles propios (🔑 Palabras clave, 🎚 Audio, 📝 Transcripción y ✦ Efectos) tras la agrupación
del 20/11: ya no están en la barra de abajo; quien las pida (go_page, atajos, la guía, menús) llega a su sitio nuevo y
Editar queda tal cual (más el panel que se abre):
  · go_page("keywords") → «Voz y texto» → 4 · Palabras clave; «transcripcion» → 2 · Transcripción;
    «fairlight» → «Audio» → 1 · Limpieza; «effects» → el panel Efectos en Editar;
  · ☰ Paneles / Ventana nunca dejan sueltos los paneles absorbidos (Palabras clave, Carpetas, Buscar material, columnas
    de Efectos…): llevan a su sección;
  · «Restablecer distribución» desde cualquiera de ellas deja Editar de fábrica, sin paneles absorbidos;
  · cerrar Reclaimer tras cada una y volver a abrir: Editar igual.
Pantalla de prueba 1920×1080 (offscreen:configfile). Usa una carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_paginas_paneles.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
_CFG = f"_pruebas_tmp/pantalla_paginas_{os.getpid()}.json"
with open(os.path.join(RAIZ, _CFG), "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96,
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FALLOS = []


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


DESTINO = {"keywords": ("palabras", None), "transcripcion": ("voz_texto", "transcripcion"),
           "fairlight": ("audio", "limpieza"), "effects": ("effects", None)}


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("EditorIA", "EditorIA")
    for k in list(st.allKeys()):
        if k.startswith("paneles_pestana/") or k in ("ventana/paneles", "geometry"):
            st.remove(k)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1900, 1000)
    pump(app, 0.8)
    D = win.docks

    def vis():
        return sorted(k for k, d in D.items() if not d.isHidden())

    def absorbidos_fuera():
        return [k for k in win.ABSORBIDOS if not D[k].isHidden()]

    V0 = vis()
    chk(not absorbidos_fuera(), "en Editar no se ve ningún panel absorbido")

    print("— las antiguas páginas llevan a su sitio nuevo —")
    for pg, (panel, sec) in DESTINO.items():
        win.go_page(pg)
        pump(app, 0.4)
        chk(not D[panel].isHidden() and not D[panel].visibleRegion().isEmpty(),
            f"{pg}: «{D[panel].nombre}» a la vista")
        if sec is not None:
            acordeon = win.voz_texto if panel == "voz_texto" else win.audio_panel
            chk(acordeon.abierta() == sec, f"{pg}: en su sección ({acordeon.abierta()})")
        chk([k for k, b in win.page_buttons.items() if b.isChecked()] == ["edit"], f"{pg}: sigue «Editar» marcado")
        chk(win.preview.isVisible() and win.preview.canvas.height() > 60, f"{pg}: visor a la vista")
        chk(not absorbidos_fuera(), f"{pg}: ningún panel absorbido suelto ({absorbidos_fuera()})")
        extra = set(vis()) - set(V0)
        chk(extra <= {panel}, f"{pg}: Editar igual, más «{D[panel].nombre}» ({extra})")
        if panel not in V0:
            D[panel].hide()
        pump(app, 0.2)

    print("— ☰ Paneles y Ventana no dejan sueltos los absorbidos —")
    for clave, (panel, _sec) in (("fx_filtros", ("effects", None)), ("kw_buscar", ("palabras", None)),
                                 ("clips", ("palabras", None)), ("transcript", ("voz_texto", "transcripcion"))):
        win._mostrar_desde_menu(clave)
        pump(app, 0.4)
        chk(D[clave].isHidden() and not D[panel].isHidden(), f"☰ {clave} → «{D[panel].nombre}» (sin el panel suelto)")
        win._llenar_menu_ventana()
        chk(D[clave].toggleViewAction() not in win._menu_ventana.actions(), f"Ventana: sin «{clave}» suelto")

    print("— restablecer y volver a abrir —")
    for k in list(st.allKeys()):
        if k.startswith("paneles_pestana/"):
            st.remove(k)
    win.reset_layout()
    pump(app, 0.4)
    V0 = vis()
    for pg in DESTINO:
        win.go_page(pg)
        pump(app, 0.3)
        win.reset_layout()
        pump(app, 0.4)
        chk(vis() == V0 and not absorbidos_fuera(), f"restablecer tras {pg}: Editar de fábrica ({set(vis()) ^ set(V0)})")
    for pg in DESTINO:
        win.go_page(pg)
        pump(app, 0.3)
        abiertos = set(vis())
        win.ctrl.undo_stack.setClean()
        win.ctrl._media_dirty = False
        win.workspaces.started = False
        win.close()
        pump(app, 0.3)
        win = MainWindow()
        win.show()
        win.resize(1900, 1000)
        pump(app, 0.8)
        D = win.docks
        v2 = set(vis())
        # (lo abierto con go_page no se recuerda por pestaña: «Voz y texto» puede volver cerrado, como su pestaña dice)
        chk(not absorbidos_fuera() and v2 ^ abiertos <= {"cortes", DESTINO[pg][0]}, f"cerrar tras {pg} y reabrir: igual "
            f"({v2 ^ abiertos})")
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
