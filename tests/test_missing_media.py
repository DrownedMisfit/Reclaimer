"""
Prueba de un archivo que DESAPARECE con Reclaimer abierto (lo movió o lo borró el usuario) y de la selección:
  · las copias ligeras (proxies) ya no dan «[WinError 2]»: el archivo se marca como no encontrado y se avisa;
  · la clave de caché y el ritmo de una canción que ya no está no fallan;
  · el mismo error repetido abre UNA sola ventana (antes salían tres iguales);
  · seleccionado = UN solo color (rojo), también en un clip de la IA.
Ejecutar:  .venv/Scripts/python.exe tests/test_missing_media.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import subprocess
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
        time.sleep(0.02)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    from editoria.ai import rhythm
    from editoria.core import media as M
    from editoria.core.model import ORIGIN_AI, TRACK_VIDEO
    from editoria.ui.common import COLORS
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    ff = M.ffmpeg()
    gone = os.path.join(out, "2026-10-05 13-28-06.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4",
                    "-pix_fmt", "yuv420p", gone], check=True)
    keep = os.path.join(out, "otro.mp4")
    shutil.copy(gone, keep)

    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    pump(app, 0.3)
    ctrl, p = win.ctrl, win.ctrl.project
    gid, kid = ctrl.import_now([gone, keep])
    while ctrl.analyzing:
        pump(app, 0.1)
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    ctrl.add_media([kid], v1.id, 0.0)
    from editoria.ui.task_window import stop_all
    stop_all(6000)
    os.remove(gone)                                   # lo borras (o lo mueves) con Reclaimer abierto
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *a: errors.append(a)
    todo = win.proxies.pending()
    sys.excepthook = old_hook
    assert not errors and gid in ctrl.missing and all(t[0] != gid for t in todo), (errors, ctrl.missing)
    assert M.cache_key(gone) and rhythm._cache_file(gone)
    print("✓ archivo borrado con Reclaimer abierto: sin «[WinError 2]»; queda «no encontrado» (y te avisa)")

    # --- el mismo error repetido: una sola ventana ---
    from editoria import app as A
    calls = []
    real = A.QMessageBox.critical
    A.QMessageBox.critical = staticmethod(lambda *a, **k: calls.append(a))
    hook0 = sys.excepthook
    try:
        A._install_error_handler()
        e = FileNotFoundError(2, "El sistema no puede encontrar el archivo especificado", gone)
        for _ in range(3):
            sys.excepthook(FileNotFoundError, e, None)
        sys.excepthook(ValueError, ValueError("otro distinto"), None)
    finally:
        A.QMessageBox.critical = real
        sys.excepthook = hook0
    assert len(calls) == 2, len(calls)
    print("✓ el mismo error repetido abre UNA ventana (los demás solo se anotan en el registro)")

    # --- seleccionado: un solo color (rojo), también en un clip de la IA ---
    c = next(x for x in p.clips.values() if x.track_id == v1.id)
    c.origin = ORIGIN_AI
    tl = win.timeline
    tl.set_selection([c.id])
    pump(app, 0.2)
    img = tl.grab().toImage()
    r = tl.clip_rect(c)
    oranges = 0
    for x in range(int(r.left()) + 2, int(min(r.right(), tl.width())) - 2, 3):
        for y in (int(r.top() + 3), int(r.top() + 4), int(r.bottom() - 4)):
            q = img.pixelColor(x, y)
            if q.red() > 200 and 120 < q.green() < 200 and q.blue() < 80:
                oranges += 1
    assert oranges < 3, f"no debe verse el naranja de la IA al estar seleccionado ({oranges})"
    assert COLORS["selection"].name() == COLORS["clip_sel"].name() == "#ec3a32"
    print("✓ seleccionado: un solo color (rojo), también en clips de la IA, la transición y el rectángulo")

    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(app, 0.2)
    stop_all(6000)
    print("TODO OK")


if __name__ == "__main__":
    main()
