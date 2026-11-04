"""
Prueba de la «📖 Guía»: cada paso de cada lección encuentra su opción, la hace visible, la marca en
naranja (sin bloquear los clics) y muestra su imagen real.
Ejecutar:  .venv/Scripts/python.exe tests/test_guide.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ui.guide import LESSONS, Highlighter, highlighter_of
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    qs = QSettings("EditorIA", "EditorIA")
    saved = qs.value("guia/colocada")
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    shortcuts = []
    win._show_shortcuts = lambda: shortcuts.append(1)      # sin ventanas modales en la prueba
    pump(app, 0.3)
    assert not win.docks["guide"].isVisible(), "la guía no debe estorbar al abrir"
    win.open_guide()
    pump(app, 0.3)
    g = win.guide
    assert win.docks["guide"].isVisible() and win.docks["guide"].isFloating()
    print(f"✓ F1 abre la guía flotante ({len(LESSONS)} lecciones)")

    # El buscador lleva a la lección
    g.search.setText("subtitulos")
    pump(app, 0.2)
    assert g.lesson and g.lesson[0] == "subs", g.lesson and g.lesson[0]
    g.search.setText("pesado")
    pump(app, 0.2)
    assert g.lesson[0] == "fluidez"
    g.search.clear()
    print("✓ buscador: «subtitulos» → Subtítulos, «pesado» → Editar con fluidez")

    total = 0
    for lid, title, _w, steps in LESSONS:
        g.open_lesson(lid)
        for i in range(len(steps)):
            g.go(i)
            pump(app, 0.6 if lid == "miniatura" else 0.25)
            target, do = g.current()
            obj = g.resolve(target)
            assert obj is not None, f"{title} · paso {i + 1}: no encuentro «{target}»"
            win_ = obj.window() if isinstance(obj, QWidget) else obj[0].window()
            hl = highlighter_of(win_)
            assert isinstance(hl, Highlighter) and hl.isVisible(), f"{title} · paso {i + 1}: sin marca"
            r = hl.target_rect()
            assert r is not None and r.width() > 4 and win_.rect().intersects(r), (title, i, target, r)
            assert hl.testAttribute(Qt.WA_TransparentForMouseEvents)
            has_img = g.image.pixmap() is not None and not g.image.pixmap().isNull()
            assert has_img or g.image.text().startswith("👉"), (title, i, target)
            total += 1
        if lid in ("inicio", "fluidez", "miniatura", "voz"):
            w = win_
            w.grab().save(os.path.join(out, f"guia_{lid}.png"))
    print(f"✓ los {total} pasos encuentran su opción, la abren, la marcan en naranja y muestran su imagen")
    pump(app, 0.6)
    assert shortcuts, "la lección de atajos debe abrir la lista"

    # Siguiente / Terminar
    g.open_lesson("cortar")
    for _ in range(10):
        g.b_next.click()
        pump(app, 0.05)
    assert "terminada" in g.counter.text()
    print("✓ «Siguiente ▶» recorre la lección y «✓ Terminar» la cierra")

    # Cerrar la guía quita la marca
    g.open_lesson("inicio")
    pump(app, 0.3)
    win.docks["guide"].toggleViewAction().trigger()
    pump(app, 0.2)
    assert all(not h.isVisible() for h in g._hl)
    print("✓ al cerrar la guía, la marca desaparece")

    ed = getattr(win, "_thumb_editor", None)
    if ed:
        ed.close()
    win.analyzer.shutdown()
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    if saved is None:
        qs.remove("guia/colocada")
    print("TODO OK")


if __name__ == "__main__":
    main()
