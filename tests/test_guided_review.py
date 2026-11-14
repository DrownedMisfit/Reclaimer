"""
✓ Revisión guiada (la antigua «Revisión rápida» + los avisos del proyecto + el B-roll dudoso), sin ventanas visibles:
  · la cola junta, en orden de video, los avisos con hora (no los cortes repetidos ni los avisos sin hora) y el B-roll que
    la IA puso solo por parecido (no el que nombras ni el gameplay de fondo); «voz» = solo lo de la voz;
  · O = está bien así: no vuelve a salir (project.review_ok, con Ctrl+Z);
  · Supr = quitar el clip del aviso; Enter = la IA pone otro clip en ese tramo / rellena el hueco;
  · los botones dicen lo que van a hacer.
Ejecutar:  .venv/Scripts/python.exe tests/test_guided_review.py <carpeta>
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
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import ORIGIN_AI, TRACK_VIDEO, Clip  # noqa: E402
from editoria.ui import quick_review as QR  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_guided_review")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    vid = os.path.join(out, "material.mp4")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=160x90:r=15:d=40", "-pix_fmt", "yuv420p", vid], check=True, timeout=120,
                   creationflags=0x08000000)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    pump(app, 0.3)
    ctrl = win.ctrl
    (mid,) = ctrl.import_now([vid])
    while ctrl.analyzing:
        pump(app, 0.05)
    p = ctrl.project
    vts = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    v1, v2 = vts[-1], vts[0]
    ctrl.add_media([mid], v1.id, 0.0)
    clips = {
        "dudoso": ("B-roll IA: Gameplay · se ve: combate · tema análisis", 4.0),
        "nombras": ("B-roll IA: mencionas «Halo» → aparece aquí (video)", 10.0),
        "fondo": ("B-roll IA: gameplay de fondo · Gameplay", 16.0),
        "repetido": ("B-roll IA: Gameplay · se ve: paisaje", 24.0),
    }
    for cid, (note, t) in clips.items():
        p.clips[cid] = Clip(id=cid, media_id=mid, track_id=v2.id, start=t, source_in=t, duration=3.0,
                            origin=ORIGIN_AI, note=note)
    ctrl.project_changed.emit()
    avisos = [
        {"severity": "warning", "category": "Repetición", "time": 24.0, "message": "Se repite un trozo",
         "detail": "material.mp4 0:24", "target": "repetido"},
        {"severity": "warning", "category": "Imagen", "time": 36.5, "message": "Pantalla negra 2.0 s", "detail": "",
         "target": None},
        {"severity": "warning", "category": "Cortes", "time": 3.0, "message": "corte", "detail": "", "target": None},
        {"severity": "info", "category": "Pistas", "time": None, "message": "pista oculta", "detail": "",
         "target": None},
    ]

    # ---------------------------------------------------------------- la cola
    q = QR.build_queue(p, [], avisos)
    kinds = [(it.kind, round(it.t, 1)) for it in q]
    assert kinds == [("broll", 4.0), ("audit", 24.0), ("audit", 36.5)], kinds
    assert QR.build_queue(p, [], avisos, scope="voz") == []
    print("✓ cola: B-roll solo-por-parecido + avisos con hora (sin cortes repetidos ni avisos sin hora), en orden")

    # ---------------------------------------------------------------- en la ventana (sin IA real)
    import editoria.ai.audit as AU
    AU.run_audit = lambda *a, **k: (list(avisos), 10)
    llamadas = []
    def falsa_ia(rng=None, apply=False, **k):            # (la IA de verdad no se lanza: se apunta y «trabaja»)
        llamadas.append((rng, apply))
        win.ai_panel.job = object()
    win.ai_panel.propose = falsa_ia
    for tr_ in (v1, v2):                                  # (para que la IA encuentre cada pista)
        if win.ai_panel.track.findData(tr_.id) < 0:
            win.ai_panel.track.addItem(tr_.name, tr_.id)
    win.open_quick_review()
    qr = win.quick_review
    pump(app, 0.2)
    assert qr.windowTitle() == "✓ Revisión guiada"
    assert [it.kind for it in qr.queue] == ["broll", "audit", "audit"], [it.kind for it in qr.queue]
    assert qr.btn_accept.text() == "🔁 Otro clip" and qr.btn_reject.text() == "✕ Quitar clip"
    print("✓ ventana «Revisión guiada»: botones con lo que hacen (🔁 Otro clip / ✕ Quitar clip)")

    # O = está bien así (y no vuelve a salir)
    QTest.keyClick(qr, Qt.Key_O)
    pump(app, 0.05)
    assert "broll|dudoso" in ctrl.project.review_ok and qr.i == 1
    print("✓ O = está bien así: queda apuntado en el proyecto")

    # Supr en el aviso de repetición = quitar ese clip (con Ctrl+Z)
    QTest.keyClick(qr, Qt.Key_Delete)
    pump(app, 0.05)
    assert "repetido" not in ctrl.project.clips and qr.i == 2
    ctrl.undo_stack.undo()
    assert "repetido" in ctrl.project.clips
    print("✓ Supr = quitar el clip del aviso (Ctrl+Z lo devuelve)")

    # Enter en la pantalla negra = la IA rellena el hueco
    principal = next(c for c in ctrl.project.clips.values() if c.track_id == v1.id)
    principal.duration = 30.0                        # un hueco negro de 30 s a 38 s en la pista principal
    ctrl.project.clips["fin"] = Clip(id="fin", media_id=mid, track_id=v1.id, start=38.0, source_in=30.0, duration=2.0)
    ctrl.project_changed.emit()
    qr.start()
    pump(app, 0.2)
    negra = next(i for i, it in enumerate(qr.queue) if it.kind == "audit" and it.data["category"] == "Imagen")
    qr.i = negra
    qr._show()
    assert qr.btn_accept.text() == "✚ Rellenar", qr.btn_accept.text()
    QTest.keyClick(qr, Qt.Key_Return)
    pump(app, 0.05)
    assert llamadas and llamadas[-1][1] is True and llamadas[-1][0] == (30.0, 38.0), llamadas
    n_ia = len(llamadas)
    qr.i = negra
    qr._show()
    QTest.keyClick(qr, Qt.Key_Return)                    # con la IA trabajando: no se pide otra vez
    pump(app, 0.05)
    assert len(llamadas) == n_ia and "sigue con el anterior" in qr.note.text(), qr.note.text()
    win.ai_panel.job = None
    print("✓ Enter en un hueco negro = la IA rellena justo ese negro (y no se pide dos veces mientras trabaja)")

    # Enter en el B-roll repetido = otro clip en ese tramo
    qr.start()
    pump(app, 0.2)
    rep = next(i for i, it in enumerate(qr.queue) if it.kind == "audit" and it.data["category"] == "Repetición")
    qr.i = rep
    qr._show()
    n0 = len(llamadas)
    QTest.keyClick(qr, Qt.Key_Return)
    pump(app, 0.05)
    assert len(llamadas) == n0 + 1 and llamadas[-1] == ((24.0, 27.0), True), llamadas[-1]
    assert win.ai_panel.track.currentData() == v2.id, "otro clip, en la pista del clip"
    win.ai_panel.job = None
    assert not any(it.ref == "broll|dudoso" for it in qr.queue), "lo dado por bueno no vuelve"
    print("✓ Enter en un B-roll dudoso = la IA pone otro clip en ese tramo; lo dado por bueno no vuelve a salir")

    qr.close()
    pump(app, 0.1)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
