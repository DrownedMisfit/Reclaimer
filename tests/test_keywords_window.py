"""
🗂 Ventana amplia de palabras clave (sin ventanas visibles; la Papelera es falsa: nada real va a la Papelera):
  · lista las palabras con 👍 / 👎 / ○; 👍 crea su carpeta y la guarda en el glosario; 👎 la guarda como «no»;
  · la carpeta de la palabra se ve en dos partes: 🌐 descargado de internet (con créditos) y 💻 de tu computadora;
  · borrar: lo descargado va a la Papelera con sus créditos; lo enlazado de tu PC solo se desvincula;
  · 🧹 borrar todo lo descargado de todas las palabras; 🗑 borrar una palabra y su carpeta;
  · la parte de internet del panel (si existe) se muestra en la ventana y vuelve al panel al cerrarla;
  · 👍 / 👎 en cada fila del panel lateral y «⚡ Agregar todo».
Ejecutar:  .venv/Scripts/python.exe tests/test_keywords_window.py
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_kwwin_", dir=_TMPROOT)
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

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editoria.ai import game_lookup  # noqa: E402
from editoria.ai import keyword_glossary as KG  # noqa: E402
from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core.model import KIND_AUDIO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import clips_panel as CP  # noqa: E402

game_lookup.classify = lambda term, timeout=4: {"tipo": "ninguno", "titulo": None, "fuente": "prueba"}
QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.Yes)
PAPELERA = os.path.join(_TMP, "papelera_falsa")
os.makedirs(PAPELERA, exist_ok=True)


def _papelera_falsa(ruta: str) -> bool:
    if not os.path.exists(ruta):
        return False
    shutil.move(ruta, os.path.join(PAPELERA, f"{len(os.listdir(PAPELERA))}_{os.path.basename(ruta)}"))
    return True


CP._a_papelera = _papelera_falsa
FRASE = "hoy jugamos Ruinas Eternas y luego Pradera Lunar pero Vive Coding no y Mesa Redonda tambien"


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def _archivo(ruta: str, n: int = 2048):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(b"\0" * n)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    raiz = os.path.join(_TMP, "carpetas")
    ruinas = os.path.join(raiz, "Ruinas Eternas")
    _archivo(os.path.join(ruinas, "bajado.mp4"))
    _archivo(os.path.join(ruinas, "bajado.creditos.json"), 20)
    _archivo(os.path.join(ruinas, "copiado.png"))
    mesa = os.path.join(raiz, "Mesa Redonda")
    _archivo(os.path.join(mesa, "otro.mp4"))
    _archivo(os.path.join(mesa, "otro.creditos.json"), 20)
    del_pc = os.path.join(_TMP, "mi_pc", "mio.mp4")
    _archivo(del_pc)
    KF.link_file(raiz, "Ruinas Eternas", del_pc)

    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    p = Project.new()
    words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(FRASE.split())]
    a1 = p.tracks[-1]
    p.media["nar"] = MediaItem(id="nar", path=os.path.join(_TMP, "nar.wav"), kind=KIND_AUDIO, name="nar.wav",
                               duration=20.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=20.0)
    win.ctrl.set_project(p) if hasattr(win.ctrl, "set_project") else setattr(win.ctrl, "project", p)
    panel = win.clips
    panel.raiz = raiz
    panel.recalcular()
    tenia_net = panel.pestanas is not None and panel.pestanas.count() > 1

    from editoria.ui.keywords_window import abrir as abrir_amplia
    w = abrir_amplia(panel)                         # (la ventana amplia sigue existiendo; el botón abre la pestaña)
    pump(app, 0.3)

    def textos():
        return [w.lista.item(i).text() for i in range(w.lista.count())]

    def elegir(term):
        for i in range(w.lista.count()):
            if w.lista.item(i).data(0x0100) == term:
                w.lista.setCurrentRow(i)
                w.lista.item(i).setSelected(True)
                return
        raise AssertionError((term, textos()))

    assert any(t.startswith("👍  Ruinas Eternas") for t in textos()), textos()
    assert any(t.startswith("○  Pradera Lunar") for t in textos()), textos()
    print("✓ la lista enseña cada palabra con 👍 / ○:", " | ".join(textos()[:4]))

    if tenia_net:
        assert panel.pestanas.count() == 1 and w._net is not None
        print("✓ la búsqueda en internet del panel se ve a la izquierda de la ventana")

    elegir("Ruinas Eternas")
    assert w.caja_net.title().startswith("🌐 Descargado de internet (1"), w.caja_net.title()
    assert w.caja_pc.title() == "💻 De tu computadora (2)", w.caja_pc.title()
    print(f"✓ la carpeta se ve en dos partes: «{w.caja_net.title()}» y «{w.caja_pc.title()}»")

    w.lista.clearSelection()
    elegir("Pradera Lunar")
    w.marcar("si")
    assert KG.clave("Pradera Lunar") in KG.load()["si"] and os.path.isdir(os.path.join(raiz, "Pradera Lunar"))
    assert any(t.startswith("👍  Pradera Lunar") for t in textos()), textos()
    w.lista.clearSelection()
    elegir("Vive Coding")
    w.marcar("no")
    assert KG.clave("Vive Coding") in KG.load()["no"]
    assert any(t.startswith("👎  Vive Coding") for t in textos()), textos()
    print("✓ 👍 crea la carpeta y la guarda en el glosario; 👎 la guarda como «no»")

    w.lista.clearSelection()
    elegir("Ruinas Eternas")
    assert w.borrar([del_pc]) == 1 and os.path.isfile(del_pc), "lo enlazado solo se desvincula"
    assert w.caja_pc.title() == "💻 De tu computadora (1)", w.caja_pc.title()
    bajado = os.path.join(ruinas, "bajado.mp4")
    assert w.borrar([bajado]) == 1
    assert not os.path.exists(bajado) and not os.path.exists(os.path.join(ruinas, "bajado.creditos.json"))
    assert os.path.isfile(os.path.join(ruinas, "copiado.png"))
    print("✓ borrar: lo enlazado de tu PC solo se desvincula; lo descargado va a la Papelera con sus créditos")

    assert w.borrar_todo_descargado() == 1 and not os.path.exists(os.path.join(mesa, "otro.mp4"))
    assert os.path.isfile(os.path.join(ruinas, "copiado.png")), "lo de tu computadora no se toca"
    print("✓ 🧹 borrar todo lo descargado: de todas las palabras, sin tocar lo de tu computadora")

    # la ventana pintada con un 🔗 que luego se desvincula fuera (Medios): nunca va a la Papelera
    otro_pc = os.path.join(_TMP, "mi_pc", "original.mp4")
    _archivo(otro_pc)
    KF.link_file(raiz, "Ruinas Eternas", otro_pc)
    w.lista.clearSelection()
    elegir("Ruinas Eternas")
    w.refrescar()
    assert any(w.grid_pc.item(i).data(0x0100) == otro_pc for i in range(w.grid_pc.count()))
    KF.unlink_file(raiz, "Ruinas Eternas", otro_pc)            # (la ventana no se ha enterado)
    assert w.borrar([otro_pc]) == 0 and os.path.isfile(otro_pc), "¡un archivo del PC fue a la Papelera!"
    print("✓ con la ventana desactualizada, un archivo de tu PC ya desvinculado NO va a la Papelera")

    w.lista.clearSelection()
    elegir("Pradera Lunar")
    assert w.borrar_palabra() and not os.path.isdir(os.path.join(raiz, "Pradera Lunar"))
    print("✓ 🗑 borrar la palabra: su carpeta a la Papelera")

    w.close()
    pump(app, 0.1)
    if tenia_net:
        assert panel.pestanas.count() == 2 and w._net is None
        print("✓ al cerrar la ventana, la búsqueda en internet vuelve al panel")

    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Mesa Redonda")
    panel.lista_menciones.setCurrentRow(fila)
    panel._elegir_mencion(fila, buscar=False)
    panel._like(False)
    assert KG.clave("Mesa Redonda") in KG.load()["no"], panel.aviso.text()
    print("✓ 👎 en el panel lateral, para la palabra elegida")

    # 👍 / 👎 en cada fila de «Dijiste…» (a la derecha, junto a la carpeta) y «⚡ Agregar todo» arriba
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    assert not hasattr(panel, "btn_si") and panel.btn_todo.text() == "⚡ Agregar todo"
    win.show_panel(panel) if hasattr(win, "show_panel") else None
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    lm = panel.lista_menciones
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Pradera Lunar")
    antes = panel.mencion["term"] if panel.mencion else None
    assert antes != "Pradera Lunar"
    rect = lm.visualItemRect(lm.item(fila))
    assert rect.width() > 60, rect
    si, no = lm.itemDelegate().zonas(rect)
    QTest.mouseClick(lm.viewport(), Qt.LeftButton, Qt.NoModifier, si.center())
    pump(app, 0.2)
    assert KG.clave("Pradera Lunar") in KG.load()["si"], panel.aviso.text()
    assert os.path.isdir(os.path.join(raiz, "Pradera Lunar")), "👍 le crea la carpeta"
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Pradera Lunar")
    assert lm.item(fila).data(CP.ROL_LIKE) == "si", "el 👍 queda encendido"
    assert (panel.mencion or {}).get("term") == antes, ("pulsar 👍 no cambia la palabra elegida", antes, panel.mencion)
    print("✓ 👍 en la fila de «Pradera Lunar» (sin elegirla antes): glosario + carpeta, y queda encendido")
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Ruinas Eternas")
    rect = lm.visualItemRect(lm.item(fila))
    si, no = lm.itemDelegate().zonas(rect)
    pump(app, 0.6)                                  # (más que un doble clic: si no, el 2.º clic no cuenta)
    vivas = [m["term"] for m in panel.menciones]
    QTest.mouseClick(lm.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())      # doble clic de verdad:
    QTest.mouseDClick(lm.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())     # pulsar, soltar, doble, soltar
    QTest.mouseRelease(lm.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())
    pump(app, 0.3)
    assert KG.clave("Ruinas Eternas") in KG.load()["no"], panel.aviso.text()
    assert all(m["term"] != "Ruinas Eternas" for m in panel.menciones)
    quitadas = [t for t in vivas if t not in [m["term"] for m in panel.menciones]]
    assert quitadas == ["Ruinas Eternas"], ("un doble clic en 👎 solo quita esa palabra", quitadas)
    print("✓ 👎 en la fila de «Ruinas Eternas» (aunque sea doble clic): deja de proponerse solo esa")
    lm.window().resize(lm.window().width(), lm.window().height())
    from PySide6.QtWidgets import QDockWidget
    lm.setFixedWidth(160)
    pump(app, 0.2)
    rect = lm.visualItemRect(lm.item(0))
    assert lm.itemDelegate().zonas(rect)[1].right() <= lm.viewport().width(), (rect, lm.viewport().width())
    assert not lm.horizontalScrollBar().isVisible()
    lm.setMinimumWidth(0)
    lm.setMaximumWidth(16777215)
    print("✓ con el panel estrecho, 👍/👎 siguen a la vista (el texto se recorta)")
    pedidos = []
    win.timeline.kw_arrange_requested.disconnect(win.kw_arranger.arrange)
    win.timeline.kw_arrange_requested.connect(lambda: pedidos.append(1))
    panel.btn_todo.click()
    assert pedidos == [1], (pedidos, panel.aviso.text())
    print("✓ «⚡ Agregar todo» lanza el acomodo de todas las palabras clave en la línea de tiempo")

    # 🗂 Carpetas: pestaña de la derecha que sigue a «Dijiste…»
    dock = win.kw_folders
    assert panel.carpetas_dock is dock and "kw_folders" in win.docks
    assert panel.abrir_ventana() is dock and dock.isVisible()
    assert not dock._col.isVisible() and not dock._izq.isVisible(), "acoplada: sin lista ni internet (están a la izquierda)"
    fila = next(i for i, m in enumerate(panel.menciones) if m["term"] == "Mesa Redonda")         if any(m["term"] == "Mesa Redonda" for m in panel.menciones) else 0
    panel.lista_menciones.setCurrentRow(fila)
    pump(app, 0.2)
    elegida = panel.menciones[panel.lista_menciones.currentRow()]["term"]
    assert dock.term == elegida, (dock.term, elegida)
    print(f"✓ la pestaña «🗂 Carpetas» (a la derecha) enseña la carpeta de la palabra elegida en «Dijiste…» ({elegida})")

    # «Dijiste…»: tus carpetas que no dices, al final y atenuadas
    os.makedirs(os.path.join(raiz, "Volcan Dormido"), exist_ok=True)
    _archivo(os.path.join(raiz, "Volcan Dormido", "lava.mp4"))
    panel.recalcular()
    pump(app, 0.2)
    ult = panel.menciones[-1]
    assert ult["term"] == "Volcan Dormido" and ult.get("no_dicha") and not ult["hits"], ult
    txt = panel.lista_menciones.item(len(panel.menciones) - 1).text()
    assert "no lo dices" in txt and "📁 1" in txt, txt
    panel.lista_menciones.setCurrentRow(len(panel.menciones) - 1)
    pump(app, 0.2)
    assert dock.term == "Volcan Dormido" and dock.grid_pc.count() + dock.grid_net.count() == 1
    print(f"✓ «Dijiste…» enseña al final las carpetas que no dices («{txt.strip()}») y se pueden elegir")
    car = panel._carpeta_de("Volcan Dormido")
    if car and car["count"]:
        g = dock.grid_pc if dock.grid_pc.count() else dock.grid_net
        g.item(0).setSelected(True)
        win.ctrl.project_changed.emit()
        pump(app, 1.6)
        assert g.count() and g.item(0).isSelected(), "un cambio del proyecto no borra lo elegido en 🗂 Carpetas"
        print("✓ lo elegido en «🗂 Carpetas» sigue elegido tras un cambio del proyecto")
    otra = next(m["term"] for m in panel.menciones if m["term"] != "Volcan Dormido")
    dock.elegir_palabra(otra)                      # (desde Medios: «🗂 Abrir en la ventana de carpetas…»)
    assert panel.mencion["term"] == otra and dock.term == otra, (panel.mencion["term"], dock.term, otra)
    print("✓ elegir una palabra desde fuera la elige también en «Dijiste…» (lo que bajes va a esa misma)")

    # lo descargado va a la carpeta de la palabra ELEGIDA aunque se busque otra cosa
    if hasattr(panel, "_bajar_resultado"):
        destinos = []
        panel._bajar_trabajo = lambda u, t, k, p_, c, a=True: (destinos.append(k), "")[1]
        panel.termino = "china ccp"
        panel._bajar_resultado({"title": "x", "url": "https://x"})
        pump(app, 0.5)
        assert destinos and os.path.basename(destinos[0]) == panel.mencion["term"], destinos
        assert not os.path.isdir(os.path.join(raiz, "china ccp")), "no crea una carpeta con lo buscado"
        print("✓ lo que bajas va a la carpeta de la palabra elegida (no a una nueva con lo que escribiste)")
    assert len(os.listdir(PAPELERA)) >= 4
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
