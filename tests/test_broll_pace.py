"""
Prueba del ritmo del B-roll (YouTube y Shorts), más pausado como en los edits:
  · por defecto: YouTube 4–7 s por plano, Shorts 2,5–4 s; los valores por defecto viejos (más cortes) se cambian;
  · mínimo que nunca se rompe (ni con «Rápido»): YouTube 3 s, Shorts 2 s;
  · los huecos que se crean con la narración respetan esos tiempos.
Ejecutar:  .venv/Scripts/python.exe tests/test_broll_pace.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

KEYS = ("broll/min_short", "broll/max_short", "broll/min_youtube", "broll/max_youtube")


def main():
    st_q = QSettings("EditorIA", "EditorIA")
    keep = {k: st_q.value(k) for k in KEYS}            # tus ajustes del B-roll quedan como estaban
    app = QApplication(sys.argv)
    try:
        run(app, st_q)
    finally:
        for k, v in keep.items():
            st_q.remove(k) if v is None else st_q.setValue(k, v)


def run(app, st_q):
    from editoria.ai import broll_selection as B
    from editoria.ui.auto_dialog import PACES
    assert B.PACE_DEFAULT["youtube"] == (4.0, 7.0) and B.PACE_DEFAULT["short"] == (2.5, 4.0)
    assert dict((k, m) for k, _n, m in PACES)["fast"] >= 0.75
    st = B.floor_pace(B.BrollSettings(min_len=1.2, max_len=1.8), "short")
    assert (st.min_len, st.max_len) == (2.0, 3.0), (st.min_len, st.max_len)
    st = B.floor_pace(B.BrollSettings(min_len=2.0, max_len=3.0), "youtube")
    assert (st.min_len, st.max_len) == (3.0, 4.0), (st.min_len, st.max_len)
    st = B.floor_pace(B.BrollSettings(min_len=5.0, max_len=9.0), "youtube")
    assert (st.min_len, st.max_len) == (5.0, 9.0), "lo que pides más largo se respeta"
    print("✓ mínimo por formato (YouTube 3 s, Shorts 2 s), también con «Rápido» (×0,75)")

    # Narración de 120 s: una palabra cada 0,35 s y frases de ~2 s
    words, t = [], 0.0
    for i in range(340):
        w = "palabra." if i % 6 == 5 else "palabra"
        words.append((t, t + 0.3, w, i))
        t += 0.35
    for fmt in ("youtube", "short"):
        lo, hi = B.PACE_DEFAULT[fmt]
        slots = B.make_slots(words, B.BrollSettings(min_len=lo, max_len=hi), [])
        inner = [s["end"] - s["start"] for s in slots[:-1]]       # el último puede ser el final suelto
        lens = sorted(inner)
        med = lens[len(lens) // 2]
        assert med >= lo - 0.2 and min(lens) >= lo - 0.2, (fmt, med, lens[:5])
        print(f"✓ {fmt}: {len(slots)} planos en 120 s (mediana {med:.1f} s, el más corto {min(lens):.1f} s)")

    # Los valores por defecto VIEJOS guardados (2–3 s Shorts, 3–6 s YouTube) pasan a los nuevos
    st_q.setValue("broll/min_youtube", 3.0)
    st_q.setValue("broll/max_youtube", 6.0)
    from editoria.ui.main_window import MainWindow
    win = MainWindow()
    ai = win.ai_panel
    ai._load_settings()
    assert (ai.min_len.value(), ai.max_len.value()) == (4.0, 7.0), (ai.min_len.value(), ai.max_len.value())
    st_q.setValue("broll/min_youtube", 5.5)
    ai._load_settings()
    assert ai.min_len.value() == 5.5, "lo que elegiste tú se respeta"
    print("✓ el panel IA: los valores por defecto viejos pasan a los nuevos; los tuyos se respetan")
    win.ctrl.undo_stack.setClean()
    win.close()
    print("TODO OK")


if __name__ == "__main__":
    main()
