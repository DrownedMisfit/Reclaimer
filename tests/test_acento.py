"""
🎨 Color de acento (opciones de diseño): «Acero» por defecto (elección del usuario del 20/11), y Plata Resolve, Cromo
frío, Naranja, Azul acero, Cian, Verde menta, Violeta y Rojo para elegir. Comprueba:
  · por defecto, Acero; cada acento cambia la hoja de estilo general y los colores dibujados (common.COLORS y
    theme.acento()), y el texto encima del acento se lee (acentos claros con texto oscuro, contraste ≥ 4,5:1);
  · se recuerda (QSettings «diseno/acento») y se aplica EN VIVO a la ventana abierta: el botón principal se pinta con el
    acento nuevo y las hojas propias de los paneles que lo llevaban escrito pasan al nuevo;
  · el menú «🎨 Diseño» de la barra de arriba y Ventana → «🎨 Color de acento» lo cambian y marcan el elegido.
Capturas de Editar con Acero, Plata Resolve, Cromo frío y Naranja en _pruebas_tmp/acento/.
Pantalla de prueba 1920×1080 (offscreen:configfile). Carpeta de datos TEMPORAL; ajustes en un .ini aparte.
Ejecutar (con el turno):  turno.py tests/test_acento.py
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
_CFG = f"_pruebas_tmp/pantalla_acento_{os.getpid()}.json"
with open(os.path.join(RAIZ, _CFG), "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": ANCHO, "height": ALTO, "logicalDpi": 96,
                            "dpr": 1}]}, _f)
__import__("atexit").register(lambda: os.path.exists(os.path.join(RAIZ, _CFG)) and os.remove(os.path.join(RAIZ, _CFG)))
os.chdir(RAIZ)
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

QSettings("EditorIA", "EditorIA").remove("diseno/acento")       # (antes de cargar theme: el de fábrica)
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

FALLOS = []
SALIDA = os.path.join(RAIZ, "_pruebas_tmp", "acento")


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
    os.makedirs(SALIDA, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import theme as TH
    from editoria.ui.common import COLORS
    TH.apply_dark_theme(app)
    chk(TH.ACENTO == "acero" and TH.ACCENT == TH.ACENTOS["acero"][1], f"por defecto, Acero ({TH.ACENTO} {TH.ACCENT})")
    chk(len(TH.ACENTOS) == 9 and {"plata", "cromo", "acero", "naranja", "azul", "cian", "menta", "violeta", "rojo"}
        == set(TH.ACENTOS), "los nueve acentos con nombre")

    print("— cada acento: hoja de estilo, colores dibujados y texto legible encima —")
    for clave, (nombre, color, _hi) in TH.ACENTOS.items():
        TH.poner_acento(clave, app)
        ss = app.styleSheet()
        chk(color.lower() in ss.lower() and TH.ACCENT == color, f"{nombre}: la hoja de estilo lleva {color}")
        chk(COLORS["accent"].name().lower() == color.lower() and TH.acento().name().lower() == color.lower(),
            f"{nombre}: los colores dibujados (COLORS y acento()) = {COLORS['accent'].name()}")
        c = TH.contraste(TH.ACCENT, TH.ACCENT_ON)
        minimo = 4.5 if TH.ACCENT_ON == TH.TEXTO_OSCURO else 3.0
        chk(c >= minimo, f"{nombre}: texto encima del acento {TH.ACCENT_ON} con contraste {c:.1f}:1 (≥ {minimo})")
        if clave in ("plata", "cromo", "acero"):
            chk(TH.ACCENT_ON == TH.TEXTO_OSCURO and c >= 4.5, f"{nombre}: acento claro → texto oscuro")
            chk("check_oscuro.svg" in ss, f"{nombre}: la marca de las casillas, oscura")
        chk(str(QSettings("EditorIA", "EditorIA").value("diseno/acento")) == clave and TH.acento_guardado() == clave,
            f"{nombre}: se recuerda")

    print("— en vivo, con la ventana abierta —")
    TH.poner_acento("acero", app)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(ANCHO - 4, ALTO - 80)
    pump(app, 1.2)
    win.go_page("edit")
    pump(app, 0.6)
    fila = win.interruptores["media"].parentWidget()
    chk(TH.ACCENT in fila.styleSheet(), "la barra de interruptores lleva el acento (Acero)")
    boton = QPushButton("Prueba", win)
    boton.setObjectName("primary")
    boton.setGeometry(10, 200, 140, 34)
    boton.show()
    pump(app, 0.2)

    def color_boton():
        img = boton.grab().toImage()
        return img.pixelColor(6, img.height() // 2).name()

    for clave in ("plata", "cromo", "naranja", "acero"):
        viejo = TH.ACCENT
        acts = [a for a in win._menu_diseno.actions() if a.data() == clave]
        chk(bool(acts), f"«🎨 Diseño» tiene «{TH.ACENTOS[clave][0]}» con su muestra")
        if acts:
            acts[0].trigger()
        pump(app, 0.4)
        nuevo = TH.ACENTOS[clave][1]
        chk(TH.ACCENT == nuevo and TH.acento_guardado() == clave, f"{TH.ACENTOS[clave][0]}: elegido desde «Diseño»")
        if viejo.lower() != nuevo.lower():
            chk(nuevo.lower() in fila.styleSheet().lower() and viejo.lower() not in fila.styleSheet().lower(),
                f"{TH.ACENTOS[clave][0]}: las hojas propias de los paneles, con el acento nuevo")
        pc = color_boton()
        # (con la «profundidad» del diseño el botón principal lleva un degradado hecho CON el acento —diseno.
        #  degradado_acento—: a media altura se ve la mitad del degradado, no el acento plano)
        from editoria.ui import diseno as _D
        dg = _D.degradado_acento(nuevo)
        medio = TH.mezcla(dg["arriba"], dg["abajo"], 0.5) if _D.PROFUNDIDAD else nuevo
        chk(TH.contraste(pc, medio) < 1.15, f"{TH.ACENTOS[clave][0]}: el botón principal se pinta con él ({pc} ≈ "
                                            f"{medio}, degradado de {nuevo})")
        marcadas = [a.data() for a in getattr(win, "_acciones_acento", []) if a.isChecked()]
        chk(marcadas and all(m == clave for m in marcadas), f"{TH.ACENTOS[clave][0]}: marcado en los menús ({marcadas})")
        if clave != "acero":
            boton.hide()                               # (la captura, sin el botón de la prueba)
            pump(app, 0.1)
            win.grab().save(os.path.join(SALIDA, f"editar_{clave}.png"))
            boton.show()
    boton.deleteLater()
    pump(app, 0.3)
    win.grab().save(os.path.join(SALIDA, "editar_acero.png"))
    ventana = [a for a in win._acciones_acento if a.data() == "cian" and a.parent() is not win._menu_diseno]
    chk(bool(ventana), "Ventana → «🎨 Color de acento» también lo tiene")
    if ventana:
        ventana[0].trigger()
        pump(app, 0.3)
        chk(TH.ACENTO == "cian", "desde Ventana se aplica igual")
    TH.poner_acento("acero", app)
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
