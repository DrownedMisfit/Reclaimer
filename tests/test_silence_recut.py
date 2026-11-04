"""
Prueba de VOLVER A CORTAR los silencios (el usuario: «por más que le mueva a las opciones no elimina todos los espacios
vacíos»): tras cortar una vez, cada pausa queda repartida entre el final de un trozo y el principio del siguiente.
  · cortar con «Rápido y dinámico» (deja 10 fotogramas tras cada frase) y luego con «Pausas cortas, ritmo de Shorts»:
    la segunda pasada SÍ acorta las uniones (antes no hacía nada: medía cada mitad por separado contra el mínimo);
  · otra pasada con el mismo ajuste ya casi no encuentra nada (no se sigue comiendo audio);
  · en ningún momento se pierde voz (voz sintetizada de Windows con ruido y clics; se sabe dónde suena).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban.
Ejecutar:  .venv/Scripts/python.exe tests/test_silence_recut.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile

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

import numpy as np  # noqa: E402


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import test_silence_voz as T
    from editoria.core import silence as S
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO
    frases = [T.read(p) for p in T.tts(out)]
    path = os.path.join(out, "voz.wav")
    clean = T.build(frases, -60, path, seed=5)
    voice = np.abs(clean) > 10 ** (-60 / 20)
    ctrl = ProjectController()
    (mid,) = ctrl.import_now([path])
    while ctrl.analyzing:
        app.processEvents()
    tr = next(t for t in ctrl.project.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([mid], tr.id, 0.0)
    fps = ctrl.project.fps

    def kept_spans():
        p = ctrl.project
        return sorted((c.source_in, c.source_in + c.src_len, c.start, c.end) for c in p.clips_on(tr.id))

    def voice_lost_ms():
        keep = np.zeros(len(clean), bool)
        for a, b, _s, _e in kept_spans():
            keep[int(round(a * T.SR)):int(round(b * T.SR))] = True
        return float((voice & ~keep).sum()) / T.SR * 1000

    def joins():
        """Pausa (en la línea de tiempo) que queda entre el final de la voz de un trozo y el principio del siguiente."""
        res = []
        sp = np.abs(clean) > 10 ** (-55 / 20)
        spans = kept_spans()
        for (a1, b1, _s1, _e1), (a2, b2, _s2, _e2) in zip(spans, spans[1:]):
            s1 = np.nonzero(sp[int(a1 * T.SR):int(b1 * T.SR)])[0]
            s2 = np.nonzero(sp[int(a2 * T.SR):int(b2 * T.SR)])[0]
            if len(s1) and len(s2):
                res.append((b1 - (a1 + s1[-1] / T.SR)) + (s2[0] / T.SR))
        return np.array(res)

    def cut(name):
        st = dict(next(v for k, v in S.PRESETS.items() if k.startswith(name)), mode="voz")
        p = ctrl.project
        regs = S.plan(p, p.clips_on(tr.id), fps, st)
        if regs:
            ctrl.remove_silence([c.id for c in p.clips_on(tr.id)], regs, "all", True)
        return len(regs), sum(b - a for a, b in regs)

    n1, s1 = cut("Rápido")
    j1 = joins()
    assert voice_lost_ms() == 0, voice_lost_ms()
    n2, s2 = cut("Pausas cortas")
    j2 = joins()
    assert n2 > 0 and s2 > 0.2, (n2, s2)
    assert voice_lost_ms() == 0, voice_lost_ms()
    assert np.median(j2) < np.median(j1) - 0.05, (np.median(j1), np.median(j2))
    print(f"✓ volver a cortar con un ajuste más corto SÍ acorta las uniones: {n2} tramos ({s2:.2f} s); pausa típica "
          f"{np.median(j1) * 1000:.0f} → {np.median(j2) * 1000:.0f} ms; 0 ms de voz perdidos")
    n3, s3 = cut("Pausas cortas")
    assert s3 < 0.15, (n3, s3)
    assert voice_lost_ms() == 0, voice_lost_ms()
    print(f"✓ otra pasada con el mismo ajuste: casi nada más ({s3:.2f} s) y sin perder voz")
    print("TODO OK")


if __name__ == "__main__":
    main()
