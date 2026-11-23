"""
Detección avanzada de palabras clave en «Dijiste…» (20/11; el usuario: «algunas se van de "gta5" y otras de "gta
cinco", o se va como "el peor - peor"»). Casos reales:
  · «gta5», «gta cinco», «GTA V», «GTA-5» y «ge te a cinco» → UN grupo («GTA 5»; con una carpeta «GTA V», ese nombre);
  · «el peor, peor», «Bueno», «Cosa» → nada; tartamudeos («GTA, GTA cinco») cuentan una vez;
  · «Red Dead Redemption 2» entero (y «Red Dead» suelto se suma a él); «The Game Awards» de una pieza;
  · números en frases normales («cinco minutos», «dos gatos») no se pegan a nada;
  · el glosario manda: «No es palabra clave» quita todas las variantes; «Es palabra clave» saca hasta una corriente;
  · keyword_folders.match encuentra la carpeta «GTA V» desde «gta cinco»;
  · rendimiento: una narración de 2 h (~19 000 palabras) → find_mentions < 300 ms, y «Dijiste…» (recalcular del
    panel) < 300 ms.
Ejecutar (con el turno):  turno.py tests/test_deteccion_palabras.py
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(RAIZ, "_pruebas_tmp"), exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=os.path.join(RAIZ, "_pruebas_tmp"))
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
import _ajustes  # noqa: E402,F401

from editoria.ai import mentions as M  # noqa: E402
from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core.model import Project  # noqa: E402

FALLOS = []


def chk(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg, flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def _palabras(texto: str, t0: float = 0.0) -> list:
    """0,35 s por palabra y 0,05 s entre ellas. «|» = pausa de 1,2 s."""
    out, t = [], t0
    for tok in texto.split():
        if tok == "|":
            t += 1.2
            continue
        out.append([round(t, 2), round(t + 0.35, 2), tok, 0.9])
        t += 0.4
    return out


def _proyecto(texto: str) -> Project:
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(texto)}}
    return p


def _t(res, term):
    return next((m for m in res if m["term"] == term), None)


def _terminos(res):
    return [m["term"] for m in res]


def main():
    print("— variantes de la misma palabra clave: un grupo —")
    texto = ("Hoy jugamos gta5 con amigos. | Luego el gta cinco otra vez. | Y GTA V es enorme. | "
             "En la tienda ponía GTA-5 en grande. | Mi primo dijo ge te a cinco muy rápido.")
    res = M.find_mentions(_proyecto(texto), glossary={"si": {}, "no": [], "web": {}})
    g = _t(res, "GTA 5")
    chk(g is not None and g["count"] == 5, f"gta5 / gta cinco / GTA V / GTA-5 / ge te a cinco → «GTA 5» ×5 "
        f"({_terminos(res)}, {g and g['count']})")
    chk(not any(x for x in _terminos(res) if x != "GTA 5" and "gta" in x.lower()), f"ningún otro grupo de GTA "
        f"({_terminos(res)})")
    res = M.find_mentions(_proyecto(texto), extra_terms=["GTA V"], glossary={"si": {}, "no": [], "web": {}})
    g = _t(res, "GTA V")
    chk(g is not None and g["count"] == 5 and _t(res, "GTA 5") is None,
        f"con una carpeta «GTA V», el grupo se llama como la carpeta ({_terminos(res)})")
    momentos = sorted(h["src"] for h in (g or {}).get("hits", []))
    chk(len(momentos) == 5 and len(set(momentos)) == 5, f"…y conserva los 5 momentos ({momentos})")

    print("— nada de basura —")
    res = M.find_mentions(_proyecto("Esto es el peor, peor juego. | Peor no puede ser. | Bueno, Bueno. | "
                                    "La Cosa rara. | Mejor así."), glossary={"si": {}, "no": [], "web": {}})
    chk(not any(t.lower() in ("peor", "el peor", "peor peor", "bueno", "bueno bueno", "cosa", "mejor")
                for t in _terminos(res)), f"«el peor, peor», «Bueno», «Cosa», «Mejor» → nada ({_terminos(res)})")
    res = M.find_mentions(_proyecto("Vamos con GTA, GTA cinco ahora mismo."), glossary={"si": {}, "no": [], "web": {}})
    g = _t(res, "GTA 5")
    chk(g is not None and g["count"] == 1 and _t(res, "GTA") is None,
        f"tartamudeo «GTA, GTA cinco» → una mención de «GTA 5» ({_terminos(res)})")

    print("— nombres de varias palabras enteros —")
    res = M.find_mentions(_proyecto("Me encanta Red Dead Redemption 2 de verdad. | Red Dead es increíble. | "
                                    "Ayer vi The Game Awards completos."), glossary={"si": {}, "no": [], "web": {}})
    r = _t(res, "Red Dead Redemption 2")
    chk(r is not None, f"«Red Dead Redemption 2» entero ({_terminos(res)})")
    chk(_t(res, "Red Dead") is None and _t(res, "Red Dead Redemption") is None and _t(res, "Redemption") is None,
        f"sin trozos sueltos de Red Dead Redemption ({_terminos(res)})")
    chk(_t(res, "The Game Awards") is not None and _t(res, "Game Awards") is None and _t(res, "Awards") is None,
        f"«The Game Awards» de una pieza ({_terminos(res)})")

    print("— números en frases normales —")
    res = M.find_mentions(_proyecto("Espera cinco minutos y luego vuelve. | Tengo dos gatos y tres perros. | "
                                    "Son las seis de la tarde."), glossary={"si": {}, "no": [], "web": {}})
    chk(res == [] or not any(any(ch.isdigit() for ch in t) for t in _terminos(res)),
        f"«cinco minutos», «dos gatos»… no se pegan a nada ({_terminos(res)})")
    res = M.find_mentions(_proyecto("Jugué Fortnite dos horas seguidas."), glossary={"si": {}, "no": [], "web": {}})
    chk(_t(res, "Fortnite") is not None and _t(res, "Fortnite 2") is None, f"«Fortnite dos horas» → «Fortnite» "
        f"({_terminos(res)})")

    print("— el glosario manda —")
    res = M.find_mentions(_proyecto(texto), glossary={"si": {}, "no": ["gta v"], "web": {}})
    chk(not any("gta" in t.lower() for t in _terminos(res)), f"«No es palabra clave» en «GTA V» quita todas sus "
        f"variantes ({_terminos(res)})")
    res = M.find_mentions(_proyecto("Esto es lo peor. | El Peor llegó tarde."),
                          glossary={"si": {"peor": {"nombre": "Peor"}}, "no": [], "web": {}})
    chk(_t(res, "Peor") is not None and _t(res, "Peor")["known"], f"«Es palabra clave» saca hasta una palabra corriente "
        f"({_terminos(res)})")
    from editoria.ai import keyword_glossary as KG
    KG.add_no("GTA V")
    chk(KG.is_no("gta cinco") and KG.is_no("gta5"), "is_no reconoce las variantes («gta cinco», «gta5»)")
    KG.add_yes("GTA 5")
    chk(not KG.is_no("GTA V"), "«Es palabra clave» en «GTA 5» quita «GTA V» de «no»")
    KG.remove("GTA 5")

    print("— carpetas: las variantes encuentran la suya —")
    carpetas = [{"name": "GTA V", "label": "GTA V", "keys": KF.folder_keys("GTA V"), "path": "x"},
                {"name": "Red Dead Redemption 2", "label": "Red Dead Redemption 2",
                 "keys": KF.folder_keys("Red Dead Redemption 2"), "path": "y"}]
    chk((KF.match("gta cinco", carpetas) or {}).get("path") == "x" and
        (KF.match("GTA 5", carpetas) or {}).get("path") == "x" and (KF.match("gta5", carpetas) or {}).get("path") == "x",
        "KF.match: «gta cinco», «GTA 5», «gta5» → la carpeta «GTA V»")
    chk(KF.match("cinco", carpetas) is None, "KF.match: «cinco» solo no es ninguna carpeta")

    print("— rendimiento: narración de 2 h —")
    random.seed(3)
    frases = ["hoy vamos a ver el nuevo tráiler de GTA seis que salió ayer",
              "la verdad es que el peor juego del año fue otro", "en Fortnite metieron un mapa nuevo",
              "Red Dead Redemption 2 sigue siendo increíble", "espera cinco minutos que vuelvo",
              "Minecraft y Roblox son los más jugados", "el GTA V ya tiene doce años",
              "ayer vi The Game Awards con mi hermano", "bueno pues seguimos con el video",
              "Elden Ring Nightreign tiene jefes nuevos", "y eso es todo por hoy amigos"]
    largo = []
    while len(largo) < 19000:
        largo += (random.choice(frases) + ".").split()
    p = Project.new()
    p.transcripts = {"nar": {"language": "es", "words": _palabras(" ".join(largo))}}
    M.precargar()
    g = {"si": {}, "no": [], "web": {}}
    M.find_mentions(p, extra_terms=["GTA V", "Fortnite"], glossary=g)      # (la primera: calienta cachés)
    t0 = time.perf_counter()
    res = M.find_mentions(p, extra_terms=["GTA V", "Fortnite"], glossary=g)
    ms = (time.perf_counter() - t0) * 1000
    chk(ms < 300, f"find_mentions con {len(largo)} palabras (≈2 h): {ms:.0f} ms (< 300)")
    chk(_t(res, "GTA V") is not None and _t(res, "GTA 6") is not None, f"…y encuentra lo que toca "
        f"({_terminos(res)[:8]})")

    # «Dijiste…» de verdad: el recalcular del panel con la ventana abierta
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    for _ in range(30):
        app.processEvents()
    win.ctrl.project.transcripts = p.transcripts
    win.clips.recalcular()
    t0 = time.perf_counter()
    win.clips._firma_ultima = None
    win.clips.recalcular()
    ms = (time.perf_counter() - t0) * 1000
    chk(ms < 300, f"«Dijiste…» (recalcular del panel) con la narración de 2 h: {ms:.0f} ms (< 300)")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()

    if FALLOS:
        print(f"✗ {len(FALLOS)} fallo(s):")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
