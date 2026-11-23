"""
💥 Sin cierres al rehacer listas (17/11: «Windows fatal exception: access violation» al vaciar «Dijiste…» y la lista
de Edits). Causa: responsive.py pedía layout.itemAt() desde Python en cada redimensionado; PySide deja colgado del
layout el envoltorio de cada QLayoutItem, Qt lo borra por su cuenta y, cuando otra cosa ocupa esa memoria (un elemento
nuevo de una lista), PySide le da el envoltorio viejo → cierre. Esta prueba:
  1) adapta un panel, lo redimensiona y borra/añade widgets: ningún envoltorio de QLayoutItem queda vivo en PySide;
  2) el estrés del revisor (ventana principal con 63 palabras: desplazar la lista, redimensionar la ventana,
     recalcular «Dijiste…» y rehacer la lista de Edits muchas veces): antes se caía siempre antes de 400 vueltas.
Ejecutar:  .venv/Scripts/python.exe tests/test_sin_cierres_listas.py <carpeta_salida>
"""
from __future__ import annotations

import atexit
import faulthandler
import os
import random
import shutil
import sys
import tempfile
import time

faulthandler.enable()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_listas_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import shiboken6  # noqa: E402
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel, QLayoutItem, QMessageBox,  # noqa: E402
                               QPushButton, QVBoxLayout, QWidget)

VUELTAS = int(os.environ.get("VUELTAS_LISTAS", "900"))


def envoltorios_de_items() -> int:
    """Envoltorios de QLayoutItem (QWidgetItem, QSpacerItem…: no son QObject) que PySide cree vivos."""
    return sum(1 for o in shiboken6.getAllValidWrappers()
               if isinstance(o, QLayoutItem) and not hasattr(o, "metaObject"))


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def parte1(app):
    from editoria.ui import responsive as R
    antes = envoltorios_de_items()
    panel = QWidget()
    v = QVBoxLayout(panel)
    fila = QHBoxLayout()
    v.addLayout(fila)
    for i in range(5):
        fila.addWidget(QPushButton(f"🎙 Botón con un nombre largo número {i}"))
    rej = QGridLayout()
    v.addLayout(rej)
    for i in range(6):
        rej.addWidget(QLabel(f"Etiqueta larga de la rejilla {i}"), i // 2, (i % 2) * 2)
        rej.addWidget(QPushButton(f"Opción {i}"), i // 2, (i % 2) * 2 + 1)
    panel.resize(900, 400)
    panel.show()
    R.adaptar(panel)
    pump(app, 20)
    for k in range(40):
        panel.resize(150 + (k * 97) % 800, 400)
        pump(app, 3)
        if k % 5 == 0:                               # (widgets que Qt borra: sus QWidgetItem también)
            b = fila.parentWidget().findChildren(QPushButton)[0]
            b.deleteLater()
            fila.addWidget(QPushButton(f"Nuevo {k}"))
            pump(app, 3)
    assert R.ancho_minimo(panel) < 400, R.ancho_minimo(panel)
    despues = envoltorios_de_items()
    assert despues <= antes, f"quedan {despues - antes} envoltorios de QLayoutItem vivos (itemAt desde Python)"
    print(f"✓ panel adaptado, redimensionado 40 veces y con widgets borrados: 0 envoltorios de QLayoutItem colgando")
    panel.deleteLater()
    pump(app, 5)


def parte2(app):
    from editoria.ai import game_lookup
    from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem, Project
    from editoria.ui import clips_panel as CP
    game_lookup.classify = lambda term, timeout=4: {"tipo": "ninguno", "titulo": None, "fuente": "prueba"}
    QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.Yes)
    raiz = os.path.join(_TMP, "carpetas")
    nombres = [f"Carpeta Vieja Numero {i} con nombre bastante largo para partir" for i in range(60)]
    for nombre in nombres + ["Ruinas Eternas"]:
        os.makedirs(os.path.join(raiz, nombre), exist_ok=True)
        with open(os.path.join(raiz, nombre, "a.mp4"), "wb") as f:
            f.write(b"\0" * 64)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    p = Project.new()
    frase = ("hoy hablamos de Ruinas Eternas y de Pradera Lunar con Vive Coding y otra vez Ruinas Eternas " * 3).split()
    words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(frase)]
    a1 = p.tracks[-1]
    p.media["nar"] = MediaItem(id="nar", path=os.path.join(_TMP, "nar.wav"), kind=KIND_AUDIO, name="nar.wav",
                               duration=40.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    for i in range(40):
        ruta = os.path.join(_TMP, f"v{i}.mp4")
        with open(ruta, "wb") as f:
            f.write(b"\0" * 64)
        p.media[f"v{i}"] = MediaItem(id=f"v{i}", path=ruta, kind=KIND_VIDEO, name=f"video de prueba numero {i} largo.mp4",
                                     duration=5.0, probed=True)
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=40.0)
    if hasattr(win.ctrl, "set_project"):
        win.ctrl.set_project(p)
    else:
        win.ctrl.project = p
    cl = win.clips
    cl.raiz = raiz
    CP.ClipsPanel._ver_otras = staticmethod(lambda: True)      # (sin tocar los ajustes reales)
    cl.recalcular()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.005)
    lista = cl.lista_menciones
    assert lista.count() > 0, "«Dijiste…» vacía: la prueba no probaría nada"
    print(f"«Dijiste…» con {lista.count()} filas; {VUELTAS} vueltas de estrés…")
    rnd = random.Random(7)
    t0 = time.time()
    for k in range(VUELTAS):
        n = lista.count()
        if n and k % 2 == 0:
            lista.scrollToItem(lista.item(rnd.randrange(n)))
            lista.verticalScrollBar().setValue(rnd.randrange(lista.verticalScrollBar().maximum() + 1))
        if k % 5 == 0:
            win.resize(1100 + rnd.randrange(500), 700 + rnd.randrange(250))
        cl._firma_ultima = None
        cl.recalcular()                              # (vacía y rehace «Dijiste…»)
        win.edit_panel._firma_clips = None
        win.edit_panel._fill()                       # (vacía y rehace la lista de Edits)
        if k % 4 == 0:
            app.processEvents()
        if k % 150 == 0:
            print(f"  vuelta {k} ({time.time() - t0:.0f} s)")
    t1 = time.time()                                 # (la red de seguridad de responsive suelta cada 2 s los
    while time.time() - t1 < 2.6:                    #  envoltorios que PySide crea por su cuenta)
        app.processEvents()
        time.sleep(0.005)
    assert lista.count() > 0
    n_items = envoltorios_de_items()
    assert n_items == 0, f"{n_items} envoltorios de QLayoutItem vivos en la ventana principal (itemAt desde Python)"
    print(f"✓ {VUELTAS} vueltas rehaciendo «Dijiste…» y la lista de Edits mientras se redimensiona: sin cierres "
          "(antes se caía antes de 400)")
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    parte1(app)
    parte2(app)
    print("TODO OK")


if __name__ == "__main__":
    main()
