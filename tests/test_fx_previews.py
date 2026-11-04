"""
Prueba de las vistas previas de los efectos (🎞):
  · cada efecto de imagen, cada transición y cada efecto del edit musical tiene su icono y su animación;
  · los botones/listas los muestran; al pasar el ratón sale la animación y se va al salir.
Ejecutar:  .venv/Scripts/python.exe tests/test_fx_previews.py <carpeta_salida>
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

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QEnterEvent, QImageReader  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication(sys.argv)
    from editoria.core import fx_previews as FP
    from editoria.core import transitions as TR
    from editoria.ui import fx_preview_ui as FXP
    from editoria.ui.edit_dialog import EditDialog
    from editoria.ui.effects_panel import LOOKS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    edit_keys = ("velocity", "shake", "punch", "glitch", "strobe", "freeze", "slowmo_calm", "transitions", "grade",
                 "grain", "vignette", "letterbox", "extras")
    want = [("look", k) for k, *_ in LOOKS] + [("trans", k) for k, *_ in TR.CATALOG] + [("edit", k) for k in edit_keys]
    missing = [f"{g}_{k}" for g, k in want if not (FP.thumb(g, k) and FP.anim(g, k))]
    assert not missing, missing
    r = QImageReader(FP.anim("edit", "velocity"))
    assert r.supportsAnimation() and r.imageCount() > 20, r.imageCount()
    total = sum(os.path.getsize(os.path.join(FP.ASSETS, f)) for f in os.listdir(FP.ASSETS))
    print(f"✓ {len(want)} efectos con icono y animación ({total / 1e6:.1f} MB, toma CC0 de Poly Haven)")

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ep = win.effects
    from editoria.ui.effects_panel import _FxButton
    btns = [b for b in ep.findChildren(_FxButton)]
    assert btns and all(not b.icon().isNull() for b in btns), "cada efecto de imagen con su icono"
    assert all(not ep.trans_list.item(i).icon().isNull() for i in range(ep.trans_list.count()))
    b = btns[0]
    app.sendEvent(b, QEnterEvent(b.rect().center().toPointF(), b.rect().center().toPointF(),
                                 b.mapToGlobal(b.rect().center()).toPointF()))
    pump(app, 0.3)
    pop = FXP.popup()
    assert pop.isVisible() and pop.movie is not None and pop.movie.frameCount() > 20
    app.sendEvent(b, QEvent(QEvent.Leave))
    assert not pop.isVisible()
    print("✓ Efectos: icono en cada botón y transición; al pasar el ratón, la animación (y se va al salir)")

    ed = EditDialog(win.ctrl, win)
    assert all(not cb.icon().isNull() for cb in ed.opt.values())
    scr = app.primaryScreen().availableGeometry()
    ed.sections["Efectos"].set_open(True, save=False)
    ed.resize(min(700, scr.width() - 360), min(560, scr.height() - 40))
    ed.move(scr.left(), scr.top())
    ed.show()
    pump(app, 0.3)
    cb = ed.opt["velocity"]
    app.sendEvent(cb, QEnterEvent(cb.rect().center().toPointF(), cb.rect().center().toPointF(),
                                  cb.mapToGlobal(cb.rect().center()).toPointF()))
    pump(app, 0.2)
    assert pop.isVisible() and pop.key == ("edit", "velocity") and "Velocity" in pop.caption.text()
    assert "Cámara lenta justo en el golpe" in pop.caption.text(), "con su breve descripción"
    fg = ed.frameGeometry()
    # (la ventana ya no se deja estrechar por debajo de lo que ocupa su contenido: en una pantalla pequeña puede no
    # quedar sitio a los lados; entonces la tarjeta sale fuera del panel, sin tapar el efecto)
    room = fg.right() + 8 + pop.width() <= scr.right() or fg.left() - 8 - pop.width() >= scr.left()
    if room:
        assert pop.geometry().left() > fg.right() or pop.geometry().right() < fg.left(), (pop.geometry(), fg, scr)
        where = "FUERA de la ventana, a su lado"
    else:
        tl = cb.mapToGlobal(cb.rect().topLeft())
        assert not pop.geometry().intersects(cb.rect().translated(tl)), (pop.geometry(), cb.rect().translated(tl))
        where = "sin tapar el efecto (en esta pantalla no cabe al lado de la ventana)"
    app.sendEvent(cb, QEvent(QEvent.ToolTip))
    print(f"✓ la tarjeta (animación + nombre + descripción) sale {where}")
    ed.close()
    assert not pop.isVisible(), "al cerrar la ventana, la animación se va"
    print("✓ Edit musical: cada efecto con su icono y su animación")
    win.ctrl.undo_stack.setClean()
    win.close()
    pump(app, 0.2)
    print("TODO OK")


if __name__ == "__main__":
    main()
