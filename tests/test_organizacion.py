"""
🧭 Organización de la interfaz (13/11, sin ventanas visibles):
  · menú «IA ✨» a la vista (B-roll, temas, edit musical, Shorts, primera versión…); «Voz» solo con lo de la voz;
  · barra de la línea de tiempo: ✨ B-roll, 🎬 Escenas, 📱 Vertical (solo en proyectos verticales), 🖼 Miniatura y
    ⬆ Exportar a la vista; ⚡ Ráfaga y 〰 Curvas dentro de «⋯ Más»; si no cabe, se compacta (primero lo menos usado);
  · ⇤ Huecos: el mismo menú en el visor y en Timeline, con «Juntar (Ctrl++)» el primero;
  · «🗣 Buscar lo que se dice» ya no se llama igual que 🔑 Palabras clave (tus carpetas).
Ejecutar:  .venv/Scripts/python.exe tests/test_organizacion.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_orden_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    pump(app, 0.3)

    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions() if a.menu() is not None}
    assert "IA ✨" in menus, list(menus)
    ia = [a.text() for a in menus["IA ✨"].actions()]
    voz = [a.text() for a in menus["Voz"].actions()]
    assert "🎬 Proponer B-roll" in ia and "✨ Primera versión automática…" in ia and "🎵 Crear edit musical…" in ia
    assert not any("B-roll" in t or "edit musical" in t for t in voz), voz
    titulos = list(menus)
    assert titulos.index("Voz") + 1 == titulos.index("IA ✨"), titulos
    print("✓ menú «IA ✨» a la vista, después de «Voz»; «Voz» solo con lo de la voz")

    for b in (win.btn_broll, win.btn_scenes, win.btn_thumb, win.btn_export, win.btn_more):
        assert b.isVisible(), b.text()
    assert not win.btn_burst.isVisible() and not win.tool_curves.isVisible()
    mas = [a.text() for a in win.btn_more.menu().actions()]
    assert "⚡ Ráfaga de cortes al ritmo" in mas and any(t.startswith("〰 Curvas") for t in mas), mas
    win.btn_more.menu().aboutToShow.emit()
    win.act_curves.trigger()
    assert win.tool_curves.isChecked()
    win.act_curves.trigger()
    assert not win.tool_curves.isChecked()
    print("✓ barra: ✨ B-roll, 🎬 Escenas, 🖼 Miniatura y ⬆ Exportar a la vista; ⚡ Ráfaga y 〰 Curvas en «⋯ Más»")

    assert not win.btn_vertical.isVisible(), "en YouTube (16:9) no tiene sentido"
    win.workspaces.switch("short")
    pump(app, 0.2)
    assert win.btn_vertical.isVisible(), "en Shorts sí"
    win.workspaces.switch("youtube")
    pump(app, 0.2)
    win.timeline.set_selection([])
    win.statusBar().clearMessage()
    win._toolbar_scenes()
    assert "Elige antes" in win.statusBar().currentMessage()
    print("✓ 📱 Vertical solo en proyectos verticales; 🎬 Escenas sin clips elegidos dice qué hacer")

    assert win.minimumSizeHint().width() < 2000, win.minimumSizeHint().width()
    bar = win._tl_bar
    bar.setParent(None)
    bar.installEventFilter(win)
    bar.resize(2600, 40)
    bar.show()
    pump(app, 0.1)
    win._tl_fit_bar()
    assert win.btn_export.text() == "⬆ Exportar" and win.btn_bars.text() == "▭ Quitar barras"
    bar.resize(1300, 40)
    pump(app, 0.1)
    win._tl_fit_bar()
    assert win.btn_bars.text() == "▭" and "Quitar barras" in win.btn_bars.toolTip()
    bar.resize(2600, 40)
    pump(app, 0.1)
    win._tl_fit_bar()
    ancho = bar.layout().sizeHint().width()
    bar.resize(ancho + 4, 40)
    pump(app, 0.1)
    win._tl_fit_bar()
    assert win.btn_export.text() == "⬆ Exportar"
    win._sync_cut_badge(3)                        # aparece «⚠ 3 cortes ◀ ▶»: ya no cabe → se vuelve a encajar
    pump(app, 0.1)
    assert bar.layout().sizeHint().width() <= bar.width(), (bar.layout().sizeHint().width(), bar.width())
    win._sync_cut_badge(0)
    win.tool_curves.setChecked(True)
    pump(app, 0.1)
    assert "〰" in win.btn_more.text(), win.btn_more.text()
    win.tool_curves.setChecked(False)
    pump(app, 0.1)
    assert "〰" not in win.btn_more.text()
    print("✓ si no cabe, la barra se compacta (primero lo menos usado) y no obliga a la ventana a ser más ancha")
    print("✓ la barra se vuelve a encajar cuando cambia lo que enseña; «⋯ Más» marca 〰 si las Curvas están activas")

    m = QMenu()
    win._fill_gaps_menu(m)
    primeros = [a.text() for a in m.actions() if not a.isSeparator()]
    tl_gaps = [x for x in menus["Timeline"].findChildren(QMenu) if x.title().startswith("⇤ Eliminar huecos")]
    assert primeros[0].startswith("⇤ Juntar (Ctrl++)") and tl_gaps
    assert [a.text() for a in tl_gaps[0].actions() if not a.isSeparator()] == primeros
    print("✓ ⇤ Huecos: el mismo menú en el visor y en Timeline, con «Juntar (Ctrl++)» el primero")

    from editoria.ui import ai_panel
    textos = " ".join(str(x) for x in vars(ai_panel).values() if isinstance(x, (list, tuple)))
    assert "🗣 Buscar lo que se dice" in textos and "🔑 Palabras clave\", \"Dónde" not in textos
    print("✓ «🗣 Buscar lo que se dice» ya no se llama igual que 🔑 Palabras clave")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
