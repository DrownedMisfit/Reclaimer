"""
Prueba de la limpieza de voz automática: la IA elige la MEJOR toma (no siempre la última), quita muletillas,
palabras repetidas y cortadas, respeta las repeticiones de énfasis («muy muy»), y «⚡ Limpiar automáticamente»
lo aplica en un solo paso (también solo, al terminar el análisis).
Ejecutar:  .venv/Scripts/python.exe tests/test_voice_auto.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.core.model import TRACK_AUDIO  # noqa: E402


def W(text, t0, probs=None):
    out, t = [], t0
    for i, w in enumerate(text.split()):
        out.append([round(t, 3), round(t + 0.3, 3), w, (probs or {}).get(i, 0.95)])
        t += 0.35
    return out, t


def kept(p, mid, a, b) -> float:
    """Cuánto del tramo [a, b] del archivo sigue en la línea de tiempo (0–1)."""
    tot = 0.0
    for c in p.clips.values():
        if c.media_id == mid:
            lo, hi = max(a, c.source_in), min(b, c.source_in + c.src_len)
            tot += max(0.0, hi - lo)
    return tot / (b - a)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    voz = os.path.join(out, "voz.wav")
    subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=40",
                    voz], check=True)
    # Guion: tres tomas de la misma frase (a medias / buena / con «eh»), luego muletilla, «el el», «muy muy»
    t = 0.5
    take1, t = W("Este juego tiene un problema", t)
    take2, t = W("Este juego tiene un problema muy grande con la cámara.", t + 0.8)
    take3, t = W("Este juego eh tiene un problema muy grande con la cámara.", t + 0.8)
    rest1, t = W("Y eh luego viene el el final", t + 0.8)
    rest2, t = W("que es muy muy bueno.", t + 0.1)
    words = take1 + take2 + take3 + rest1 + rest2
    span = lambda ws: (ws[0][0], ws[-1][1])   # noqa: E731

    st = QSettings("EditorIA", "EditorIA")
    keys = [f"limpieza_auto/{k}" for k in ("filler", "filler_soft", "repeat", "retake", "silence", "noise",
                                             "al_terminar")]
    saved = {k: st.value(k) for k in keys}
    try:
        for k in keys:
            st.remove(k)
        app = QApplication(sys.argv)
        from editoria.ai import voice_cleanup
        from editoria.ui.main_window import MainWindow
        win = MainWindow()
        win.show()
        c = win.ctrl
        p = c.project
        [mid] = c.import_now([voz])
        nar = [tr for tr in p.tracks if tr.kind == TRACK_AUDIO][0]
        c.add_media([mid], nar.id, 0.0)
        c.set_transcript(mid, {"language": "es", "words": words, "segments": []})
        vp = win.voice
        vp.media_combo.setCurrentIndex(vp.media_combo.findData(mid)) if hasattr(vp, "media_combo") else None
        samples = media_tools.decode_mono(voz, 16000)
        opts = voice_cleanup.CleanupOptions(silences=False, noises=False, doubtful=False, clipping=False)
        items = voice_cleanup.analyze(samples, 16000, words, opts)
        retakes = [d for d in items if d["kind"] == "retake"]
        assert len(retakes) == 2 and all("toma 2" in d["label"] for d in retakes), [d["label"] for d in retakes]
        assert "se quedó a medias" in retakes[0]["detail"] and "muletilla" in retakes[0]["detail"]
        reps = [d for d in items if d["kind"] == "repeat"]
        assert any("el el" in d["label"] for d in reps) and any("muy muy" in d["label"] and d["data"]["auto"] is False
                                                                 for d in reps)
        print("✓ 3 tomas de la misma frase: la IA se queda con la 2ª (la 1ª quedó a medias, la 3ª tiene «eh»)")
        print("✓ «el el» se quita; «muy muy» se avisa pero no se quita solo (puede ser a propósito)")

        vp._store_suggestions(mid, items, opts)
        assert vp.media_id() == mid
        cand = vp.auto_candidates()
        kinds = sorted({s.kind for s in cand})
        assert kinds == ["filler", "repeat", "retake"], kinds
        assert not any("muy muy" in s.label for s in cand)
        idx = c.undo_stack.index()
        n = vp.auto_clean(ask=False)
        assert n == len(cand) and c.undo_stack.index() == idx + 1
        assert kept(p, mid, *span(take2)) > 0.97, "la mejor toma debe quedarse"
        assert kept(p, mid, *span(take1)) < 0.05 and kept(p, mid, *span(take3)) < 0.05
        eh = next(w for w in rest1 if w[2] == "eh")
        assert kept(p, mid, eh[0], eh[1]) < 0.05
        muy = [w for w in rest2 if w[2] == "muy"]
        assert kept(p, mid, muy[0][0], muy[1][1]) > 0.97
        print(f"✓ «⚡ Limpiar automáticamente»: {n} cortes de una vez (un solo Ctrl+Z); queda la toma buena")

        # restaurar un corte suelto
        c.undo_stack.undo()
        assert kept(p, mid, *span(take1)) > 0.97
        # manual: elegir la otra toma a mano
        r = next(s for s in p.suggestions if s.kind == "retake" and s.status == "pending")
        c.apply_suggestions([r.id], keep_first=True)          # «quedarme con la toma 1» de ese par
        c.undo_stack.undo()
        print("✓ modo manual: puedes quedarte con otra toma; deshacer y restaurar funcionan")

        # solo, al terminar de analizar
        vp.auto_after.setChecked(True)
        vp._store_suggestions(mid, items, opts)
        assert kept(p, mid, *span(take1)) < 0.05 and kept(p, mid, *span(take2)) > 0.97
        print("✓ «Hacerlo solo al terminar»: limpia en cuanto acaba el análisis")
        win.analyzer.shutdown()
        c.undo_stack.setClean()
        c._media_dirty = False
        win.close()
    finally:
        for k, v in saved.items():
            if v is None:
                st.remove(k)
            else:
                st.setValue(k, v)
    print("TODO OK")


if __name__ == "__main__":
    main()
