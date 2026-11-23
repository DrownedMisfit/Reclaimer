"""
🔑 Palabras clave sin cierres: 👎 pulsado muy seguido y la lista de Edits rehecha a la vez no cierran Reclaimer;
  un proyecto nuevo no enseña palabras de otros proyectos; 🗑 Eliminar palabra clave (Papelera falsa).
Ejecutar:  .venv/Scripts/python.exe tests/test_palabras_sin_cierres.py
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
CP._a_papelera = lambda ruta: bool(shutil.move(ruta, os.path.join(PAPELERA, os.path.basename(ruta))))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

FRASE = "hoy hablamos de Ruinas Eternas y de Pradera Lunar con Vive Coding y otra vez Ruinas Eternas"


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    raiz = os.path.join(_TMP, "carpetas")
    for nombre in ("Ruinas Eternas", "Proyecto Viejo", "Otra Cosa Vieja"):
        os.makedirs(os.path.join(raiz, nombre), exist_ok=True)
        with open(os.path.join(raiz, nombre, "a.mp4"), "wb") as f:
            f.write(b"\0" * 2048)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    p = Project.new()
    words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(FRASE.split())]
    a1 = p.tracks[-1]
    p.media["nar"] = MediaItem(id="nar", path=os.path.join(_TMP, "nar.wav"), kind=KIND_AUDIO, name="nar.wav",
                               duration=20.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    from editoria.core.model import KIND_VIDEO
    for i in range(12):                                   # (la lista de clips de 🎵 Edits se rehace con Medios)
        ruta = os.path.join(_TMP, f"v{i}.mp4")
        with open(ruta, "wb") as f:
            f.write(b"\0" * 64)
        p.media[f"v{i}"] = MediaItem(id=f"v{i}", path=ruta, kind=KIND_VIDEO, name=f"v{i}.mp4", duration=5.0,
                                     probed=True)
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=20.0)
    win.ctrl.set_project(p) if hasattr(win.ctrl, "set_project") else setattr(win.ctrl, "project", p)
    cl = win.clips
    cl.raiz = raiz
    CP._ajustes().setValue("clips/ver_otras_carpetas", False)
    cl.recalcular()
    pump(app, 0.2)
    terms = [m["term"] for m in cl.menciones]
    assert "Ruinas Eternas" in terms and not any(m.get("no_dicha") for m in cl.menciones), terms
    assert "Proyecto Viejo" not in terms, terms
    print("✓ proyecto nuevo: solo sus palabras (las carpetas de otros proyectos no salen):", terms)
    cl._cambiar_ver_otras()
    pump(app, 0.3)
    assert any(m.get("no_dicha") and m["term"] == "Proyecto Viejo" for m in cl.menciones), cl.menciones
    menu = cl._menu_mencion(cl.lista_menciones.item(0))
    textos = [a.text() for a in menu.actions()]
    assert any(t.startswith("🗑 Eliminar palabra clave") for t in textos), textos
    assert any(t.startswith("👁 Ver también") and a.isChecked() for a in menu.actions() for t in [a.text()]), textos
    print("✓ clic derecho: «🗑 Eliminar palabra clave…» y «👁 Ver también las de otros proyectos» (marcada)")
    assert cl._eliminar_palabra("Proyecto Viejo", preguntar=False)
    pump(app, 0.3)
    assert os.path.isdir(os.path.join(PAPELERA, "Proyecto Viejo")), os.listdir(PAPELERA)
    assert "Proyecto Viejo" not in [m["term"] for m in cl.menciones]
    print("✓ 🗑 eliminar: su carpeta a la Papelera y fuera de la lista")
    cl._cambiar_ver_otras()
    pump(app, 0.3)

    # 💥 lo que cerraba Reclaimer: 👎 pulsado muy seguido mientras la lista se rehace, y Medios cambiando a la vez
    lista = cl.lista_menciones
    d = lista.itemDelegate()
    for vuelta in range(40):
        if lista.count() == 0:
            cl.recalcular()
            pump(app, 0.05)
        it = lista.item(vuelta % max(1, lista.count()))
        if it is None:
            continue
        r = lista.visualItemRect(it)
        _si, no = d.zonas(r) if hasattr(d, "zonas") else (r, r)
        QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())
        if vuelta % 3 == 0:
            QTest.mouseDClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, no.center())
        win.ctrl.media_changed.emit()
        app.processEvents()
        if vuelta % 5 == 0:
            cl.recalcular()
        app.processEvents()
    pump(app, 0.5)
    assert win.edit_panel.clips.count() > 0, "la lista de Edits no se llenó"
    print(f"✓ 40 clics seguidos en 👎 (con dobles) y Medios cambiando: sigue abierto ({lista.count()} palabras)")
    win.ctrl.undo_stack.setClean()
    win._media_dirty = False
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
