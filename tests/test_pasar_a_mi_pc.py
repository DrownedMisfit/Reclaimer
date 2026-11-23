"""
💻 «Pasar a mi computadora» en la carpeta de una palabra clave (sin ventanas visibles, sin diálogos, sin Papelera real):
  · soltar en «💻 De tu computadora» lo de «🌐 Descargado de internet» → se pregunta la carpeta (aquí, sustituido) y
    los archivos se MUEVEN allí con su «.creditos.json» (nombre único si ya existe) y quedan 🔗 enlazados a la palabra;
  · si el archivo estaba en Medios, su ruta pasa a la nueva (sus clips no quedan «NO ENCONTRADO»);
  · clic derecho → «💻 Pasar a mi computadora…» hace lo mismo; cancelar no mueve nada; una carpeta dentro de las
    de palabras clave se rechaza;
  · ⌫ Retroceso borra lo elegido y Supr ya no borra nada en esa ventana.
Ejecutar:  .venv/Scripts/python.exe tests/test_pasar_a_mi_pc.py
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
os.environ.setdefault("EDITORIA_SIN_SONIDO", "1")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_pasarpc_", dir=_TMPROOT)
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

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from editoria.ai import game_lookup  # noqa: E402
from editoria.core import keyword_folders as KF  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem, Project  # noqa: E402
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
FRASE = "hoy jugamos Ruinas Eternas y luego Pradera Lunar"


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
    for n in ("bajado", "bajado2", "bajado3", "bajado4"):
        _archivo(os.path.join(ruinas, f"{n}.mp4"))
        _archivo(os.path.join(ruinas, f"{n}.creditos.json"), 20)
    _archivo(os.path.join(ruinas, "copiado.png"))
    mi_pc = os.path.join(_TMP, "mi_pc")
    _archivo(os.path.join(mi_pc, "bajado.mp4"), 10)            # ya hay uno con ese nombre: el movido será «(2)»
    bajado = os.path.join(ruinas, "bajado.mp4")
    bajado2 = os.path.join(ruinas, "bajado2.mp4")
    bajado3 = os.path.join(ruinas, "bajado3.mp4")
    bajado4 = os.path.join(ruinas, "bajado4.mp4")

    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    p = Project.new()
    words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(FRASE.split())]
    pista_v = next(t for t in p.tracks if t.kind == "video")
    a1 = p.tracks[-1]
    p.media["nar"] = MediaItem(id="nar", path=os.path.join(_TMP, "nar.wav"), kind=KIND_AUDIO, name="nar.wav",
                               duration=20.0, probed=True)
    p.media["m1"] = MediaItem(id="m1", path=bajado, kind=KIND_VIDEO, name="bajado.mp4", duration=5.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=20.0)
    p.clips["cv"] = Clip(id="cv", media_id="m1", track_id=pista_v.id, start=1.0, source_in=0.0, duration=3.0)
    win.ctrl.set_project(p) if hasattr(win.ctrl, "set_project") else setattr(win.ctrl, "project", p)
    panel = win.clips
    panel.raiz = raiz
    panel.recalcular()

    from editoria.ui.keywords_window import abrir as abrir_amplia
    w = abrir_amplia(panel)
    pump(app, 0.3)
    w.elegir_palabra("Ruinas Eternas")
    pump(app, 0.1)
    assert w.term == "Ruinas Eternas", w.term
    assert w.caja_net.title().startswith("🌐 Descargado de internet (4"), w.caja_net.title()
    assert w.caja_pc.title() == "💻 De tu computadora (1)", w.caja_pc.title()
    assert w.grid_pc.acceptDrops() and w.grid_pc.viewport().acceptDrops(), "«De tu computadora» acepta soltar"
    print("✓ la palabra tiene 4 descargados y 1 de tu computadora; «💻 De tu computadora» acepta soltar")

    # 1) soltar dos descargados en «De tu computadora» (un soltar de verdad: QDropEvent en la rejilla)
    pedidas = []
    w._pedir_carpeta_pc = lambda n: (pedidas.append(n), mi_pc)[1]
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(bajado), QUrl.fromLocalFile(bajado2)])
    entra = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.grid_pc.viewport(), entra)
    assert entra.isAccepted(), "«De tu computadora» acepta lo arrastrado"
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.grid_pc.viewport(), ev)
    assert not pedidas, "la carpeta se pregunta DESPUÉS del soltar (no dentro del arrastre)"
    pump(app, 0.3)
    assert pedidas == [2], pedidas
    nuevo1 = os.path.join(mi_pc, "bajado (2).mp4")
    nuevo2 = os.path.join(mi_pc, "bajado2.mp4")
    assert os.path.isfile(nuevo1) and os.path.isfile(nuevo2), os.listdir(mi_pc)
    assert os.path.getsize(os.path.join(mi_pc, "bajado.mp4")) == 10, "el que ya estaba no se pisa"
    assert os.path.isfile(os.path.join(mi_pc, "bajado (2).creditos.json")), os.listdir(mi_pc)
    assert os.path.isfile(os.path.join(mi_pc, "bajado2.creditos.json")), os.listdir(mi_pc)
    assert not os.path.exists(bajado) and not os.path.exists(bajado2)
    assert not os.path.exists(os.path.join(ruinas, "bajado.creditos.json"))
    enl = [os.path.normcase(x) for x in KF.linked_files(raiz, "Ruinas Eternas")]
    assert os.path.normcase(nuevo1) in enl and os.path.normcase(nuevo2) in enl, enl
    assert w.caja_net.title().startswith("🌐 Descargado de internet (2"), w.caja_net.title()
    assert w.caja_pc.title() == "💻 De tu computadora (3)", w.caja_pc.title()
    en_pc = {os.path.normcase(w.grid_pc.item(i).data(Qt.UserRole)) for i in range(w.grid_pc.count())}
    assert os.path.normcase(nuevo1) in en_pc and os.path.normcase(nuevo2) in en_pc, en_pc
    print("✓ soltar 2 descargados: movidos a la carpeta elegida con sus créditos (nombre único) y enlazados")
    m1 = win.ctrl.project.media["m1"]
    assert os.path.normcase(m1.path) == os.path.normcase(nuevo1), m1.path
    assert "m1" not in win.ctrl.missing and os.path.isfile(m1.path)
    assert win.ctrl.project.clips["cv"].media_id == "m1"
    print("✓ el que estaba en Medios ahora apunta al sitio nuevo: su clip sigue encontrando el archivo")
    txt = w.aviso.text()
    assert txt.startswith("💻 2 archivo(s) movidos a «mi_pc»; siguen en la palabra «Ruinas Eternas»"), txt
    print(f"✓ aviso: {txt}")

    # 2) clic derecho → «💻 Pasar a mi computadora…» (el menú se arma sin abrirlo)
    menu = w._armar_menu_net([bajado3])
    acc = next(a for a in menu.actions() if a.text().startswith("💻 Pasar a mi computadora"))
    w._pedir_carpeta_pc = lambda n: ""                             # cancelar: nada se mueve
    acc.trigger()
    assert os.path.isfile(bajado3) and "No se movió nada" in w.aviso.text(), w.aviso.text()
    w._pedir_carpeta_pc = lambda n: os.path.join(raiz, "Pradera Lunar")   # dentro de las de palabras: no
    acc.trigger()
    assert os.path.isfile(bajado3) and "fuera de" in w.aviso.text(), w.aviso.text()
    otra = os.path.join(_TMP, "otra carpeta")
    w._pedir_carpeta_pc = lambda n: otra                           # (la carpeta aún no existe: se crea)
    acc.trigger()
    assert os.path.isfile(os.path.join(otra, "bajado3.mp4")) and not os.path.exists(bajado3)
    assert os.path.isfile(os.path.join(otra, "bajado3.creditos.json"))
    assert w.aviso.text().startswith("💻 1 archivo(s) movidos a «otra carpeta»"), w.aviso.text()
    print("✓ clic derecho → «💻 Pasar a mi computadora…»: cancelar no mueve; dentro de las carpetas de palabras se "
          "rechaza; a una carpeta tuya se mueve")
    # algo de «De tu computadora» soltado en su misma rejilla: no hace nada (ni pregunta)
    pedidas.clear()
    w._pedir_carpeta_pc = lambda n: (pedidas.append(n), mi_pc)[1]
    w._soltado_pc([nuevo2])
    pump(app, 0.2)
    assert not pedidas and os.path.isfile(nuevo2)
    print("✓ soltar en «De tu computadora» algo que ya está ahí no hace nada")

    # 3) teclado: ⌫ Retroceso borra lo elegido; Supr ya no
    llamadas = []
    borrar_real = w.borrar
    w.borrar = lambda rutas, preguntar=True: (llamadas.append(list(rutas)), 0)[1]
    w.grid_net.clearSelection()
    w.grid_pc.clearSelection()
    fila = next(i for i in range(w.grid_net.count())
                if os.path.normcase(w.grid_net.item(i).data(Qt.UserRole)) == os.path.normcase(bajado4))
    w.grid_net.item(fila).setSelected(True)
    ov = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Delete, Qt.NoModifier)
    QApplication.sendEvent(w.grid_net, ov)
    assert ov.isAccepted(), "con algo elegido, Supr no llega a borrar clips de la línea de tiempo"
    QApplication.sendEvent(w.grid_net, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    assert not llamadas and os.path.isfile(bajado4), "Supr ya no borra"
    assert "Retroceso" in w.aviso.text(), w.aviso.text()
    QApplication.sendEvent(w.grid_net, QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier, "\b"))
    assert llamadas == [[bajado4]], llamadas
    w.borrar = borrar_real
    assert "Supr" not in w.grid_net.toolTip() and "Retroceso" in w.grid_net.toolTip()
    assert "Supr" not in w.grid_pc.toolTip() and "Retroceso" in w.grid_pc.toolTip()
    print("✓ ⌫ Retroceso borra lo elegido; Supr ya no (y los consejos lo dicen)")

    # 4) también en la pestaña acoplada «🗂 Carpetas»
    dock = getattr(win, "kw_folders", None)
    if dock is not None:
        assert dock.grid_pc.acceptDrops() and hasattr(dock, "pasar_a_mi_pc")
        print("✓ la pestaña «🗂 Carpetas» (acoplada) tiene lo mismo")

    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    w.close()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
