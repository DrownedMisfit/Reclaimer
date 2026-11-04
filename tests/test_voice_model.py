"""
Prueba de ◈ «la IA aprende tu voz» (ai/voice_model.py), con la voz de Windows (Sabina, es-MX) como «tu voz»:
  · ejemplos: se guardan (solo la huella del sonido), se cuentan los minutos y se olvidan los más viejos;
  · entrena con 3 grabaciones y, en la más nueva (que no vio), acierta ≥ 90 % y marca los bordes a ≤ 40 ms;
  · el cálculo con numpy es el mismo que el de PyTorch (no hace falta PyTorch para usarlo);
  · al eliminar silencios (híbrido) con el modelo: no se come voz (y quita casi lo mismo o más).
Usa una carpeta de datos TEMPORAL; deja tus ajustes como estaban. Si falta PyTorch, lo dice y no falla.
Ejecutar:  .venv/Scripts/python.exe tests/test_voice_model.py <carpeta_salida>
"""
from __future__ import annotations

import importlib.util
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
    if importlib.util.find_spec("torch") is None:
        print("– sin PyTorch: no se puede entrenar aquí")
        print("TODO OK")
        return
    import test_silence_voz as T
    from editoria.ai import voice_model as VM
    from editoria.core import silence as S
    frases = [T.read(p) for p in T.tts(out)]
    paths = []
    for k, (nd, seed) in enumerate(((-62, 1), (-48, 2), (-62, 7))):
        path = os.path.join(out, f"voz{k}.wav")
        clean = T.build(frases, nd, path, seed=seed)
        # «palabras afinadas» = donde suena de verdad cada frase
        words, t = [], 0.8
        for f, pausa, text in zip(frases, T.PAUSAS, T.FRASES):
            nz = np.nonzero(np.abs(f) > 1e-4)[0]
            d = (nz[-1] + 1 - nz[0]) / T.SR
            words.append([t, t + d, text, 1.0])
            t += d + pausa
        mins = VM.add_example(f"ejemplo_{k}", T.read(path) if hasattr(T, "read") else None, words)
        paths.append((path, clean))
    assert abs(mins - 3 * len(T.read(paths[0][0])) / T.SR / 60) < 0.05, mins
    assert len(VM.examples()) == 3
    print(f"✓ 3 ejemplos guardados ({mins:.1f} min; solo la huella del sonido)")
    VM.MIN_TRAIN_MIN = 0.5                         # (la voz de prueba dura menos de un minuto por grabación)
    t0 = time.time()
    rep = VM.train_from_examples(epochs=10)
    el = time.time() - t0
    v = rep["val"]
    assert VM.available() and v["acierto"] >= 0.90 and v["borde_mediana_ms"] <= 40, rep
    print(f"✓ entrenada en {el:.0f} s: en la grabación que no vio, {v['acierto'] * 100:.1f} % de acierto y bordes a "
          f"{v['borde_mediana_ms']:.0f} ms (mediana)")

    import torch
    f = VM.features(T.read(paths[2][0]))
    w = {k: torch.from_numpy(np.asarray(x)) for k, x in np.load(VM.model_path()).items()}
    net = VM._net()
    net.load_state_dict({k.replace("__", "."): x for k, x in w.items() if k not in ("mu", "sd")})
    net.eval()
    with torch.no_grad():
        pt = torch.sigmoid(net(torch.from_numpy(((f - w["mu"].numpy()) / w["sd"].numpy()).T[None].astype(np.float32))))
    pn = VM._forward(f)
    assert np.abs(pt[0].numpy() - pn).max() < 1e-4
    print("✓ con numpy da lo mismo que con PyTorch (para usarla no hace falta PyTorch)")

    path, clean = paths[2]
    an = S.analyze(path)
    pv = S.voice_prob(path, len(an["full"]))
    assert pv is not None and len(pv) == len(an["full"])
    rows = []
    for name, st in S.PRESETS.items():
        args = (an, 60.0, st["threshold_db"], st["before"], st["after"], st["min_frames"])
        sin = S.silent_ranges_voice(*args, hybrid=True)
        con = S.silent_ranges_voice(*args, hybrid=True, pv=pv)
        e = T.eaten_ms(con, clean)
        assert e <= T.eaten_ms(sin, clean) + 1.0 and e <= 7.0, (name, e)
        tot_s, tot_c = sum(b - a for a, b in sin), sum(b - a for a, b in con)
        assert tot_c >= 0.9 * tot_s, (name, tot_s, tot_c)
        rows.append(f"{tot_s:.1f}→{tot_c:.1f} s")
    print("✓ al eliminar silencios con el modelo: sin comerse voz; quita " + ", ".join(rows))
    VM.EX_MAX_MIN = mins * 0.5                     # se olvidan los más viejos si pasan del máximo
    VM.add_example("ejemplo_3", T.read(paths[0][0]), words)
    assert len(VM.examples()) < 4
    print("✓ con demasiados ejemplos se olvidan los más viejos")
    print("TODO OK")


if __name__ == "__main__":
    main()
