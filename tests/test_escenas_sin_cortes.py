"""
🎬 La página Escenas, nada cortado ni salido (20/11, criterio del usuario): con pantallas de 1920×1080 y 1366×768, la
barra de arriba (nombre entero, ▶, Crear escena, ← Editor) y CADA sección del lateral izquierdo abierta (Escena,
Personajes, Plantillas, Capas, Sonidos, Prehechas, Palabras clave, PNGTuber), con el panel de la derecha (una capa
elegida, con «Recortar y ajustar») y Resultados con una escena: ningún widget se sale, ninguna barra horizontal y ningún
texto recortado (la misma revisión que tests/test_paneles_sin_cortes.py). Además la página no pide más ancho que la
ventana y las 8 cabeceras del lateral se ven a la vez.
Capturas: _pruebas_tmp/escenas_facil/sin_cortes_<pantalla>_<sección>.png
Ejecutar:  .venv/Scripts/python.exe tests/test_escenas_sin_cortes.py <carpeta_salida>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANTALLAS = {"1920": (1920, 1080, 1920, 1040), "1366": (1366, 768, 1366, 740)}


def lanzar_todas(out):
    fallos = 0
    for nombre, (sw, sh, _ww, _wh) in PANTALLAS.items():
        cfg = os.path.join("_pruebas_tmp", f"pantalla_escenas_{nombre}.json")
        os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
        with open(os.path.join(RAIZ, cfg), "w", encoding="utf-8") as f:
            json.dump({"screens": [{"name": "P", "x": 0, "y": 0, "width": sw, "height": sh, "logicalDpi": 96,
                                    "dpr": 1}]}, f)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=" + cfg.replace("\\", "/"),
                   PYTHONUTF8="1", EDITORIA_SIN_SONIDO="1")
        env.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
        print(f"— Pantalla {sw}×{sh} —", flush=True)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), out, "--pantalla", nombre], cwd=RAIZ, env=env,
                           timeout=400)
        fallos += r.returncode != 0
    if fallos:
        print(f"✗ {fallos} pantalla(s) con cortes")
        sys.exit(1)
    print("TODO OK")


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def una_pantalla(out, nombre, tmp):
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    import _ajustes  # noqa: F401
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from test_paneles_sin_cortes import revisar
    app = QApplication.instance() or QApplication(sys.argv)
    sw, sh, ww, wh = PANTALLAS[nombre]
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(ww, wh)
    win.show()
    pump(app, 0.5)
    ctrl = win.ctrl
    png = os.path.join(tmp, "Personaje con un nombre largo.png")
    Image.new("RGBA", (200, 300), (40, 80, 230, 255)).save(png)
    aid = ctrl.media_for_path(png, "Escenas")
    win.go_page("scenes")
    pump(app, 0.5)
    pg = win._scenes_widget
    pg.nombre.setText("Escena con un nombre bastante largo para ver si se corta")
    pg.escena["nombre"] = pg.nombre.text()
    pg._añadir_actor(aid)
    pg.crear_escena()
    pg._añadir_actor(aid)
    pump(app, 0.5)
    assert pg.width() <= ww + 2, (pg.width(), ww)
    anchos = {type(pg._split.widget(i)).__name__: pg._split.widget(i).minimumSizeHint().width()
              for i in range(pg._split.count())}
    cab = pg.findChild(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget, "escenas_cabecera")
    anchos["cabecera"] = cab.minimumSizeHint().width() if cab is not None else -1
    anchos["abajo"] = pg.tl.parentWidget().minimumSizeHint().width()
    assert pg.minimumSizeHint().width() <= min(ww, 964), (f"la página pide {pg.minimumSizeHint().width()} px "
                                                          f"(ventana {ww}; debe caber en 964)", anchos)
    nom = pg.nombre
    assert nom.width() + 2 >= nom.fontMetrics().horizontalAdvance(nom.text()), "el nombre se ve entero"
    ac = pg.lateral.acordeon
    if nombre == "1920":
        assert not ac.compacto() and all(ac._cab[k].isVisible() for k in ac._orden), "las 8 cabeceras a la vista"
    else:                                               # (con poco alto: la abierta usa el alto; las demás, en su menú)
        assert ac.compacto() or all(ac._cab[k].isVisible() for k in ac._orden)
    print(f"✓ barra de arriba con el nombre entero; lateral {'compacto' if ac.compacto() else 'con sus cabeceras'}; "
          f"la página pide {pg.minimumSizeHint().width()} px (ventana {ww}; cabe en 964)", flush=True)
    cortes: dict = {}
    vistos: set = set()
    for clave in ac._orden:
        ac.abrir(clave, guardar=False)
        pg.tl.sel = ("actor", pg.escena["actores"][-1])
        pg._elegir("actor", pg.escena["actores"][-1])
        pump(app, 0.25)
        revisar(pg, cortes, vistos, f"{nombre} · {clave}")
        pg.grab().save(os.path.join(out, f"sin_cortes_{nombre}_{clave}.png"))
    # con 3 resultados y una ventana de ~1117 px (lo que vio el revisor): nada cortado a la derecha
    for k in range(2):
        pg._cargar(pg._nueva_desde_marcas(), True)
        pg._añadir_actor(aid)
        pg.crear_escena()
    pg._añadir_actor(aid)
    win.resize(1117, wh)
    pump(app, 0.6)
    assert len(pg.resultados.tarjetas) >= 3
    for clave in ("escena", "capas"):
        ac.abrir(clave, guardar=False)
        pg.tl.sel = ("actor", pg.escena["actores"][-1])
        pg._elegir("actor", pg.escena["actores"][-1])
        for i in range(pg.a_pestanas.count()):
            pg.a_pestanas.setCurrentIndex(i)
            pump(app, 0.25)
            revisar(pg, cortes, vistos, f"{nombre} · 1117 px · {clave} · pestaña {i}")
    pg.grab().save(os.path.join(out, f"sin_cortes_{nombre}_1117_tres_resultados.png"))
    if cortes:
        for c in sorted(cortes.values()):
            print("  ✗", c)
    pg.sucia = False
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    assert not cortes, f"{len(cortes)} cortes"
    print(f"✓ {len(ac._orden)} secciones abiertas una a una, con una capa elegida y Resultados: 0 cortes "
          f"({len(vistos)} widgets)", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except (AttributeError, ValueError):
        pass
    salida = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
        os.path.join(RAIZ, "_pruebas_tmp", "escenas_facil")
    salida = os.path.abspath(salida)
    os.makedirs(salida, exist_ok=True)
    if "--pantalla" not in sys.argv:
        lanzar_todas(salida)
    else:
        import tempfile
        sys.path.insert(0, RAIZ)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=os.path.join(RAIZ, "_pruebas_tmp"))
        __import__("atexit").register(__import__("shutil").rmtree, tmp, True)
        os.environ.setdefault("EDITORIA_MODELOS", os.path.join(RAIZ, "datos", "modelos"))
        una_pantalla(salida, sys.argv[sys.argv.index("--pantalla") + 1], tmp)
