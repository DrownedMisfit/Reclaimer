"""
🅣 Plantillas de título (sin ventanas visibles):
  · 8 de fábrica (título grande, rótulo inferior, capítulo, meme, destacado, cita, fuente, pregunta);
  · ponerla en el cabezal crea el texto con su estilo y su fundido (un paso de deshacer); en vertical, más pequeña;
  · aplicarla a un texto que ya existe cambia el estilo pero deja lo escrito;
  · «★ Guardar como plantilla» la guarda (sale en el botón 🅣 y en el Inspector) y se puede borrar;
  · el fundido del texto se usa al exportar (antes siempre 0,15 s).
Ejecutar:  .venv/Scripts/python.exe tests/test_plantillas_titulos.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="reclaimer_titulos_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
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


def main():
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("EditorIA", "EditorIA").remove("titulos/plantillas")
    from editoria.core import title_templates as TT
    from editoria.core.model import Project
    from editoria.ui.main_window import MainWindow
    assert len([k for k, _n in TT.all_templates() if not k.startswith("★")]) == 8
    g, gv = TT.get("grande"), TT.get("grande", vertical=True)
    assert g["style"]["fade"] == 0.25 and gv["style"]["size"] < g["style"]["size"]
    print("✓ 8 plantillas de fábrica; en vertical salen más pequeñas")

    win = MainWindow()
    win.ctrl._replace(Project.new(), None)
    ctrl = win.ctrl
    n0 = ctrl.undo_stack.count()
    cid = ctrl.add_text_template("capitulo", 2.0)
    c = ctrl.project.clips[cid]
    assert c.text["font"] == "Georgia" and c.text["italic"] and c.text["fade"] == 0.5 and c.text["content"] == \
        "Capítulo 1" and abs(c.duration - 3.0) < 1e-6 and ctrl.undo_stack.count() == n0 + 1
    print("✓ ponerla en el cabezal: texto con su estilo y su fundido, en un paso de deshacer")

    ctrl.set_text_props(cid, content="Parte 2: el jefe final")
    ctrl.apply_text_template([cid], "meme")
    c = ctrl.project.clips[cid]
    assert c.text["content"] == "Parte 2: el jefe final" and c.text["font"] == "Impact" and not c.text.get("italic")
    print("✓ aplicarla a un texto que ya existe cambia el estilo y deja lo escrito")

    from editoria.export.ffmpeg_export import ExportOptions, build_command
    ctrl.set_text_props(cid, fade=0.6)
    script = os.path.join(_TMP, "filtro.txt")
    build_command(ctrl.project, ExportOptions(path=os.path.join(_TMP, "x.mp4"), encoder="cpu"), "ffmpeg", script)
    txt = open(script, encoding="utf-8").read()
    assert "fade=t=in:st=0:d=0.600" in txt, txt[-600:]
    print("✓ al exportar, el texto entra y sale con su fundido (0,6 s)")

    win.timeline.set_selection([cid])
    app.processEvents()
    insp = win.inspector
    insp._ids = [cid]
    key = insp.save_text_template("Mi estilo de jefe")
    assert key == "★Mi estilo de jefe" and ("★Mi estilo de jefe", "★ Mi estilo de jefe") in TT.all_templates()
    assert insp.text_template.findData(key) >= 0
    menu = win.btn_titles.menu()
    menu.aboutToShow.emit()
    assert "★ Mi estilo de jefe" in [a.text() for a in menu.actions()]
    c2 = ctrl.add_text_template(key, 8.0)
    assert ctrl.project.clips[c2].text["font"] == "Impact" and ctrl.project.clips[c2].text["fade"] == 0.6
    assert TT.delete_user(key) and key not in dict(TT.all_templates())
    print("✓ «★ Guardar como plantilla»: sale en el botón 🅣 y en el Inspector, se usa y se borra")
    ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
