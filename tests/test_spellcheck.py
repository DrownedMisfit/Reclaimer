"""
Prueba de «✍ Ortografía» en lo que escribe el usuario (NO la transcripción): español de México, inglés y mixto.
  · el corrector: acepta el español de México («chido», «órale», «güey») y el vocabulario gamer («gameplay», «boss»);
    sugerencias en buen orden (despues → después, aora → ahora, porfavor → por favor, becuase → because);
  · en el Inspector (texto en pantalla): subrayado rojo bajo «dificil» y «despues» (no bajo «boss»); clic derecho →
    «difícil» lo corrige y el texto del clip cambia; «Añadir al diccionario» quita el subrayado y se guarda;
    cambiar a English marca las palabras españolas; «Sin corregir» no marca nada;
  · también está en las frases del edit musical y en la miniatura.
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_spellcheck.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def underlined(edit) -> list[str]:
    """Las palabras subrayadas del cuadro (lo que de verdad dibuja el subrayado)."""
    from PySide6.QtGui import QTextCharFormat
    out = []
    block = edit.document().firstBlock()
    while block.isValid():
        for fr in block.layout().formats():
            if fr.format.underlineStyle() == QTextCharFormat.SpellCheckUnderline:
                out.append(block.text()[fr.start:fr.start + fr.length])
        block = block.next()
    return out


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.core import spelling as SP
    from editoria.ui import spellcheck as SC
    SC.set_lang("mixto")
    t0 = time.time()
    while not SP.ready("mixto") and time.time() - t0 < 30:
        pump(app, 0.1)
    assert SP.ready("mixto")
    for w in ("chido", "órale", "güey", "neta", "computadora", "gameplay", "boss", "speedrun", "Fíjense"):
        assert SP.is_ok(w), w
    assert not SP.is_ok("dificil") and not SP.is_ok("despues")
    exp = {"despues": "después", "aora": "ahora", "porfavor": "por favor", "becuase": "because", "dificil": "difícil",
           "asta": "hasta", "Fijense": "Fíjense", "tambien": "también"}
    for w, good in exp.items():
        s = SP.suggest(w)
        assert s and s[0] == good, (w, s)
    assert "en serio" in SP.suggest("enserio")[:2], SP.suggest("enserio")
    assert not SP.misspelled("#GTAVI @amigo www.ejemplo.com 2x")
    print("✓ corrector: español de México, inglés y vocabulario gamer; sugerencias en buen orden "
          "(despues → después, aora → ahora, porfavor → por favor, becuase → because)")

    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    cid = ctrl.add_text(0.0, 3.0, "Hola")
    if not isinstance(cid, str):
        cid = next(c.id for c in ctrl.project.clips.values() if c.text)
    win.timeline.set_selection([cid])
    pump(app, 0.3)
    ed = win.inspector.text_edit
    ed.setFocus()
    ed.setPlainText("Hoy el boss final esta dificil, despues vemos")
    pump(app, 0.6)
    u = underlined(ed)
    assert set(u) == {"dificil", "despues"}, u
    print(f"✓ texto en pantalla: subrayadas {u} (no «boss»: es mixto)")

    # clic derecho sobre «dificil» → «difícil»
    from PySide6.QtGui import QTextCursor
    from editoria.ui import help as help_ui
    txt = ed.toPlainText()
    c = QTextCursor(ed.document())
    c.setPosition(txt.index("dificil") + 3)
    pos = ed.cursorRect(c).center()
    seen = {}
    orig = help_ui.exec_menu

    def fake(menu, _p):
        seen["acts"] = {a.text(): a for a in menu.actions()}
        seen["acts"]["difícil"].trigger()
    help_ui.exec_menu = fake
    try:
        SC._context_menu(ed, pos)
    finally:
        help_ui.exec_menu = orig
    assert "difícil" in seen["acts"] and any("Añadir" in k for k in seen["acts"]), list(seen["acts"])
    assert any(k.startswith("Copiar") or "Copy" in k for k in seen["acts"]), list(seen["acts"])   # el menú de siempre
    pump(app, 0.8)                                  # (el texto del clip se guarda al dejar de escribir)
    assert "difícil" in ed.toPlainText(), ed.toPlainText()
    assert "difícil" in ctrl.project.clips[cid].text["content"], ctrl.project.clips[cid].text
    assert underlined(ed) == ["despues"], underlined(ed)
    print("✓ clic derecho: «difícil» corrige la palabra y el texto del clip cambia (Ctrl+Z lo deshace)")

    # añadir al diccionario
    ed.setPlainText("Un gameplayazo")
    pump(app, 0.5)
    assert underlined(ed) == ["gameplayazo"], underlined(ed)
    SP.add_word("gameplayazo")
    SC._rehighlight_when_ready()
    pump(app, 0.3)
    assert underlined(ed) == [] and SP.is_ok("gameplayazo")
    assert "gameplayazo" in open(SP._personal_path(), encoding="utf-8").read()
    print("✓ «Añadir al diccionario»: deja de subrayarse y se guarda")

    # idiomas
    ed.setPlainText("Hoy jugamos el boss")
    SC.set_lang("en")
    t0 = time.time()
    while not SP.ready("en") and time.time() - t0 < 30:
        pump(app, 0.1)
    pump(app, 0.4)
    assert "Hoy" in underlined(ed) and "jugamos" in underlined(ed) and "boss" not in underlined(ed), underlined(ed)
    SC.set_lang("es")
    pump(app, 0.4)
    assert "boss" not in underlined(ed), underlined(ed)      # (el vocabulario gamer vale en todos)
    SC.set_lang("off")
    pump(app, 0.4)
    assert underlined(ed) == [], underlined(ed)
    SC.set_lang("mixto")
    pump(app, 0.3)
    print("✓ idiomas: English marca el español, «Sin corregir» no marca nada; el mismo idioma en todos los cuadros")

    # también en el edit musical
    from editoria.ui.edit_dialog import EditDialog
    dlg = EditDialog(ctrl, win)
    assert getattr(dlg.quotes, "_spell", None) is not None
    dlg.quotes.setPlainText("Esto no es el final\nEs solo el comiezo")
    pump(app, 0.4)
    assert underlined(dlg.quotes) == ["comiezo"], underlined(dlg.quotes)
    dlg.close()
    print("✓ frases del edit musical: también se corrigen («comiezo» subrayada)")
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.workspaces.started = False
    win.close()
    pump(app, 0.2)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
