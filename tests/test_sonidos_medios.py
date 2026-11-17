"""
🔊 Sonidos a mano en Medios (Video horizontal, Vertical y Edits): la pestaña «🔊 Sonidos» del panel de medios tiene
los mismos sonidos que «Efectos» (los de Reclaimer, los de internet, tu carpeta), buscador, ➕ al cabezal (en su pista
de efectos, a la mitad de volumen) y 🌐 buscar en internet (si está la parte local).
Ejecutar:  .venv/Scripts/python.exe tests/test_sonidos_medios.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


def pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    lib = win.library
    assert [lib.pestanas.tabText(i) for i in range(lib.pestanas.count())] == ["🎞 Medios", "🔊 Sonidos"]
    assert lib.sonidos is None, "se monta al abrirla (no gasta nada al arrancar)"
    lib.ver_sonidos()
    pump(app, 0.1)
    sb = lib.sonidos
    assert sb is not None and sb.tree.topLevelItemCount() > 0, "con los sonidos de Reclaimer"
    hojas = [sb.tree.topLevelItem(i).child(k) for i in range(sb.tree.topLevelItemCount())
             for k in range(sb.tree.topLevelItem(i).childCount())]
    assert len(hojas) >= 5
    nombre = hojas[0].text(0)
    sb.search.setText(nombre[:4])
    visibles = [h for h in hojas if not h.isHidden()]
    assert visibles and all(nombre[:4].lower() in (h.text(0) + " " + h.text(1)).lower() for h in visibles)
    sb.search.setText("zzzz_nada")
    assert all(h.isHidden() for h in hojas)
    sb.search.setText("")
    print(f"✓ 🔊 Sonidos en Medios: {len(hojas)} sonidos, buscador que filtra")
    try:
        from editoria.ui import sounds_internet  # noqa: F401
        assert sb.b_web is not None, "con la parte local, 🌐 Internet a la vista"
        print("✓ 🌐 Internet a la vista (parte local presente)")
    except ImportError:
        assert sb.b_web is None
        print("✓ sin la parte local: no sale 🌐 (versión pública)")
    win.effects.reload()                          # (la lista de Medios se actualiza con la de Efectos)
    assert sb.tree.topLevelItemCount() > 0
    p = win.ctrl.project
    antes = set(p.clips)
    primera = next(sb.tree.topLevelItem(i).child(0) for i in range(sb.tree.topLevelItemCount())
                   if sb.tree.topLevelItem(i).childCount())      # (tras recargar, los elementos son otros)
    sb.tree.setCurrentItem(primera)
    win.engine.seek(2.0) if hasattr(win.engine, "seek") else None
    win.effects.add_at_playhead(sb.tree.currentItem())
    t0 = time.time()
    while set(p.clips) == antes and time.time() - t0 < 10:
        pump(app, 0.1)
        p = win.ctrl.project
    nuevos = [p.clips[i] for i in set(p.clips) - antes]
    assert nuevos, "➕ al cabezal pone el sonido"
    assert all(abs(c.volume - 0.5) < 1e-6 for c in nuevos), [c.volume for c in nuevos]
    print("✓ ➕ al cabezal: el sonido entra en la línea de tiempo a la mitad de volumen")
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
