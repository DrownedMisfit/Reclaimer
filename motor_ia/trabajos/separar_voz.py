"""
🗣 Separar los DIÁLOGOS del ruido de fondo (música del juego, explosiones, ambiente) con Demucs v4
(htdemucs_ft, Meta, licencia MIT) en la tarjeta gráfica. Deja solo las voces.

Uso:  python separar_voz.py trabajo.json
  {"ffmpeg": ruta, "entrada": archivo (video o audio), "salida": wav, "modelo": "htdemucs_ft"}
Escribe «PROGRESO f texto» y al final «LISTO ruta».
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import torch

SR = 44100
PIECE = 45.0        # segundos por trozo (con 2 s de solape y fundido: sin cortes)
OVERLAP = 2.0


def say(f, text):
    print(f"PROGRESO {max(0.0, min(1.0, f)):.4f} {text}", flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    say(0.01, "Leyendo el sonido…")
    r = subprocess.run([job["ffmpeg"], "-nostdin", "-v", "error", "-i", job["entrada"], "-vn", "-ac", "2",
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    wav = np.frombuffer(r.stdout, np.float32).reshape(-1, 2).T.copy()        # (2, n)
    n = wav.shape[1]
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    say(0.03, "Cargando Demucs…")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = get_model(job.get("modelo", "htdemucs_ft"))
    model.to(dev).eval()
    vi = model.sources.index("vocals")
    out = np.zeros_like(wav)
    weight = np.zeros(n, np.float32)
    step = int((PIECE - OVERLAP) * SR)
    size = int(PIECE * SR)
    ov = int(OVERLAP * SR)
    starts = list(range(0, max(1, n - ov), step))
    for i, s in enumerate(starts):
        e = min(n, s + size)
        seg = torch.from_numpy(wav[:, s:e])
        ref = seg.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        try:
            with torch.inference_mode():
                src = apply_model(model, ((seg - mean) / std)[None], device=dev, split=True, overlap=0.25,
                                  progress=False)[0]
        except torch.cuda.OutOfMemoryError:     # gráfica sin memoria (p. ej. 4 GB): seguir con el procesador
            torch.cuda.empty_cache()
            dev = "cpu"
            model.to(dev)
            say(0.05 + 0.9 * i / len(starts), "🗣 La tarjeta no tiene memoria suficiente: sigo con el procesador…")
            with torch.inference_mode():
                src = apply_model(model, ((seg - mean) / std)[None], device=dev, split=True, overlap=0.25,
                                  progress=False)[0]
        voc = (src[vi] * std + mean).cpu().numpy()
        w = np.ones(e - s, np.float32)
        if s > 0:
            k = min(ov, e - s)
            w[:k] = np.linspace(0, 1, k)
        if e < n:
            k = min(ov, e - s)
            w[-k:] = np.minimum(w[-k:], np.linspace(1, 0, k))
        out[:, s:e] += voc * w
        weight[s:e] += w
        say(0.05 + 0.9 * (i + 1) / len(starts), f"🗣 Separando los diálogos · {int(100 * e / n)} %")
    out /= np.maximum(weight, 1e-6)
    import soundfile as sf
    sf.write(job["salida"], out.T, SR, subtype="PCM_16")
    print(f"LISTO {job['salida']}", flush=True)


if __name__ == "__main__":
    main()
