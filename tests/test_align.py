"""
Prueba de 🎯 «afinar palabras» (alineación con IA, como WhisperX): con la voz de Windows (Sabina, es-MX) y ruido de
fondo, se dan las palabras con tiempos MAL puestos a propósito (repartidas a ojo y movidas 0,3 s, como los errores de
Whisper) y la IA tiene que dejarlas donde suenan:
  · el principio de cada frase, a ±60 ms de donde empieza de verdad la voz; el final, a ±100 ms;
  · las palabras en orden, sin encimarse, y dentro de lo que suena;
  · «needs» / «refined»: solo se afina una vez.
Si el modelo no está (motor_ia/alineador_es) la prueba lo dice y no falla.
Ejecutar:  .venv/Scripts/python.exe tests/test_align.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

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
    from editoria.ai import align as A
    ok, why = A.available()
    if not ok:
        print("– sin modelo de alineación:", why)
        print("TODO OK")
        return
    import test_silence_voz as T
    frases = [T.read(p) for p in T.tts(out)]
    path = os.path.join(out, "voz.wav")
    clean = T.build(frases, -62, path, seed=4)
    # dónde empieza y acaba de verdad cada frase (como en T.build)
    spans, t = [], 0.8
    for f, pausa in zip(frases, T.PAUSAS):
        nz = np.nonzero(np.abs(f) > 1e-4)[0]
        d = (nz[-1] + 1 - nz[0]) / T.SR
        spans.append((t, t + d))
        t += d + pausa
    words = []
    for (a, b), text in zip(spans, T.FRASES):
        ws = text.split()
        step = (b - a) / len(ws)
        for i, w in enumerate(ws):                    # repartidas a ojo y movidas 0,3 s (como Whisper)
            words.append([a + 0.3 + i * step, a + 0.3 + (i + 1) * step, w, 0.9])
    t0 = time.time()
    new = A.align_words(path, words)
    el = time.time() - t0
    A.unload()
    assert len(new) == len(words)
    assert all(new[k][0] <= new[k][1] <= new[k + 1][0] + 1e-6 for k in range(len(new) - 1)), "encimadas"
    k = 0
    errs = []
    voice = np.abs(clean) > 10 ** (-50 / 20)
    for (a, b), text in zip(spans, T.FRASES):
        n = len(text.split())
        ws = new[k:k + n]
        k += n
        e0, e1 = ws[0][0] - a, ws[-1][1] - b
        errs.append((abs(e0), abs(e1)))
        assert abs(e0) <= 0.06, (text, "principio", round(e0, 3))
        assert abs(e1) <= 0.10, (text, "final", round(e1, 3))
        for w in ws:
            seg = voice[int(w[0] * T.SR):int(w[1] * T.SR)]
            assert len(seg) and seg.mean() > 0.15, (text, w)
    e = np.array(errs)
    print(f"✓ {len(words)} palabras afinadas en {el:.1f} s: principio de frase ±{e[:, 0].max() * 1000:.0f} ms (media "
          f"{e[:, 0].mean() * 1000:.0f}), final ±{e[:, 1].max() * 1000:.0f} ms (media {e[:, 1].mean() * 1000:.0f}); "
          "las de Whisper iban movidas 300 ms")
    tr = {"words": words}
    assert A.needs(tr) and not A.needs(A.refined(tr, new)) and A.refined(tr, new)["words"] is new
    print("✓ solo se afina una vez (queda marcada)")
    print("TODO OK")


if __name__ == "__main__":
    main()
