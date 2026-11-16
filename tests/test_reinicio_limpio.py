"""
🔄 Reinicio y proyecto nuevo dejan TODO limpio (sin ventanas visibles):
  · Medios no enseña ningún medio ni ninguna palabra clave (las carpetas siguen en tu disco, pero no se ven);
  · «Dijiste…», la pestaña 🗂 Carpetas, la búsqueda de Medios, Momentos, el edit musical y la parte de internet
    (si existe) quedan vacíos;
  · con un proyecto con narración, Medios solo enseña las palabras clave que dices (no las 18 de tu disco);
  · si cancelas «Nuevo proyecto», no se limpia nada.
Ejecutar:  .venv/Scripts/python.exe tests/test_reinicio_limpio.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_limpio_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox  # noqa: E402

from editoria.ai import game_lookup  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, Clip, MediaItem, Project  # noqa: E402

game_lookup.classify = lambda term, timeout=4: {"tipo": "ninguno", "titulo": None, "fuente": "prueba"}
QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.Yes)


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def _archivo(ruta):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    open(ruta, "wb").write(b"\0" * 2048)


def textos_medios(lib):
    out = []

    def rec(it):
        out.append(it.text(0))
        for k in range(it.childCount()):
            rec(it.child(k))
    for i in range(lib.tree.topLevelItemCount()):
        rec(lib.tree.topLevelItem(i))
    return out


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    raiz = os.path.join(_TMP, "carpetas")
    for nombre in ("Ruinas Eternas", "Pradera Lunar", "Mesa Redonda"):
        _archivo(os.path.join(raiz, nombre, f"{nombre}.mp4"))
    from editoria.ui import clips_panel as CP
    QSettings("EditorIA", "EditorIA").setValue(CP.RAIZ_CLAVE, raiz)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    lib, panel = win.library, win.clips
    panel.raiz = raiz

    _archivo(os.path.join(_TMP, "nar.wav"))
    _archivo(os.path.join(_TMP, "clip.mp4"))

    def llenar():
        p = Project.new()
        frase = "hoy jugamos Ruinas Eternas y nada mas"
        words = [[round(i * 0.5, 2), round(i * 0.5 + 0.4, 2), w] for i, w in enumerate(frase.split())]
        p.media["nar"] = MediaItem(id="nar", path=os.path.join(_TMP, "nar.wav"), kind=KIND_AUDIO, name="nar.wav",
                                   duration=10.0, probed=True)
        p.media["v"] = MediaItem(id="v", path=os.path.join(_TMP, "clip.mp4"), kind=KIND_VIDEO, name="clip.mp4",
                                 duration=5.0, probed=True)
        p.transcripts = {"nar": {"language": "es", "words": words}}
        p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=p.tracks[-1].id, start=0.0, source_in=0.0, duration=10.0)
        win.ctrl._replace(p, None)
        win.ctrl.missing = set()
        pump(app, 0.3)
        lib._rebuild()
        panel.recalcular()
        lib.search.setText("algo")
        win.moments.grid.addItem(QListWidgetItem("resultado viejo"))
        if hasattr(panel, "lista_resultados"):
            panel.lista_resultados.addItem(QListWidgetItem("video de internet"))
            panel.campo.setText("china ccp")
        pump(app, 0.3)

    llenar()
    t = textos_medios(lib)
    assert any(x.startswith("Ruinas Eternas") for x in t), t
    assert not any(x.startswith(("Pradera Lunar", "Mesa Redonda")) for x in t), t
    assert any("Palabras clave  (1)" in x for x in t), t
    print("✓ con narración, Medios solo enseña las palabras clave que dices (1 de 3 carpetas)")

    def comprobar_limpio(que):
        pump(app, 1.5)
        t = textos_medios(lib)
        assert not t, (que, t)
        assert panel.lista_menciones.count() == 0 and panel.mencion is None, (que, panel.lista_menciones.count())
        assert lib.search.text() == "", que
        assert win.moments.grid.count() == 0, que
        assert win.kw_folders.term == "", (que, win.kw_folders.term)
        assert win.edit_panel.clips.count() == 0 and win.edit_panel.song.count() == 0, que
        if hasattr(panel, "lista_resultados"):
            assert panel.lista_resultados.count() == 0 and panel.campo.text() == "", que
        print(f"✓ {que}: Medios sin nada (ni palabras clave), «Dijiste…», 🗂 Carpetas, búsqueda, Momentos, edit "
              "musical e internet vacíos")

    win.reset_project()
    comprobar_limpio("🔄 Reinicio de proyecto")
    assert all(os.path.isdir(os.path.join(raiz, n)) for n in ("Ruinas Eternas", "Pradera Lunar", "Mesa Redonda"))
    print("✓ tus carpetas siguen en el disco (solo no se enseñan)")

    llenar()
    win.ctrl.path = None
    win.new_project()
    comprobar_limpio("Nuevo proyecto (Ctrl+N)")

    # la biblioteca común no vuelve a traer los medios a la pestaña reiniciada
    ws = win.workspaces
    llenar()
    ws.switch("short")
    pump(app, 0.3)
    assert win.ctrl.project.media, "Shorts recibe los medios (biblioteca común)"
    ws.switch("youtube")
    pump(app, 0.3)
    win.reset_project()
    pump(app, 0.3)
    ws.switch("short")
    pump(app, 0.3)
    assert win.ctrl.project.media, "Shorts conserva lo suyo"
    ws.switch("youtube")
    pump(app, 0.5)
    assert not win.ctrl.project.media, ("al volver, YouTube sigue vacío", list(win.ctrl.project.media))
    print("✓ ir a otra pestaña y volver no trae otra vez los medios a la pestaña reiniciada")
    lib._kw_create("Pradera Lunar, praderita")
    lib._rebuild()
    assert any(x.startswith("Pradera Lunar") for x in textos_medios(lib)), textos_medios(lib)
    print("✓ «＋ Palabra clave» con alias se ve en Medios aunque el proyecto esté vacío")
    win.reset_project()
    pump(app, 0.5)
    assert not textos_medios(lib), textos_medios(lib)

    llenar()
    win.ctrl.path = os.path.join(_TMP, "x.eia")
    win.ctrl.undo_stack.resetClean() if hasattr(win.ctrl.undo_stack, "resetClean") else None
    win.ctrl._media_dirty = True
    win._confirm_discard = lambda: False
    if win.ctrl.dirty:
        win.new_project()
        pump(app, 0.3)
        assert win.moments.grid.count() == 1 and lib.search.text() == "algo", "cancelar no limpia nada"
        print("✓ si cancelas «Nuevo proyecto», no se limpia nada")
    win.ctrl.path = None
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
