"""
Prueba de la tarjeta gráfica para codificar (core/hw.py): NVIDIA (NVENC), AMD (AMF) e Intel (Quick Sync).
  · se elige la marca que funciona (simulado: este PC solo tiene una);
  · TODAS las opciones que se le pasan a cada codificador existen en el FFmpeg instalado (ffmpeg -h encoder=…),
    aunque aquí no haya esa tarjeta;
  · en ESTE equipo se detecta la tarjeta real y se exporta con ella;
  · Whisper: la tarjeta NVIDIA solo si están sus librerías; si no, el procesador.
Ejecutar:  .venv/Scripts/python.exe tests/test_hw.py <carpeta>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editoria.core import hw  # noqa: E402
from editoria.core import media as M  # noqa: E402


def options_of(encoder: str) -> set[str]:
    out = subprocess.run([M.ffmpeg(), "-hide_banner", "-h", f"encoder={encoder}"], capture_output=True,
                         text=True, errors="ignore").stdout
    return set(re.findall(r"^\s+-([\w-]+)\s", out, re.M))


GENERIC = {"c:v", "b:v", "maxrate", "profile:v", "tag:v", "bf", "g", "pix_fmt", "global_quality"}


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    # 1) elegir la marca
    for marca in ("nvidia", "amd", "intel"):
        hw._found.clear()
        real = hw._works
        hw._works = lambda enc, m=marca: enc in hw.ENCODERS[m].values()
        assert hw.video_encoder("h264") == hw.ENCODERS[marca]["h264"], marca
        assert hw.video_encoder("hevc") == hw.ENCODERS[marca]["hevc"] and hw.vendor() == marca
        hw._works = real
    hw._found.clear()
    hw._works = lambda enc: False
    assert hw.video_encoder("h264") is None and hw.label() == ""
    hw._works = real
    hw._found.clear()
    print("✓ se elige la tarjeta que funciona (NVIDIA, AMD o Intel) y, sin ninguna, el procesador")
    # 2) las opciones de cada codificador existen en este FFmpeg
    for marca, encs in hw.ENCODERS.items():
        for codec, enc in encs.items():
            have = options_of(enc)
            assert have, f"este FFmpeg no trae {enc}"
            args = hw.export_args(enc, False) + hw.export_args(enc, True) + hw.proxy_args(enc) + hw.quality_args(enc)
            used = {a[1:] for a in args if a.startswith("-") and not re.match(r"^-\d", a)}
            missing = sorted(o for o in used if o not in have and o not in GENERIC)
            assert not missing, (enc, missing)
    print("✓ todas las opciones de NVENC, AMF y Quick Sync existen en el FFmpeg instalado")
    # 3) este equipo
    enc = hw.video_encoder("h264")
    print(f"  este equipo: {hw.label() or 'sin tarjeta para video (procesador)'} → {enc or 'libx264'}")
    if enc:
        dst = os.path.join(out, "prueba.mp4")
        r = subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=s=1280x720:r=30:d=2", "-c:v", enc, "-b:v", "8M", "-maxrate", "12M",
                            "-bufsize", "16M", "-pix_fmt", "yuv420p"] + hw.export_args(enc, False) + [dst],
                           capture_output=True, text=True, errors="ignore")
        assert r.returncode == 0 and os.path.getsize(dst) > 10_000, r.stderr[-400:]
        r = subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=s=640x360:r=30:d=1"] + hw.proxy_args(enc) + ["-g", "15", "-pix_fmt", "yuv420p",
                                                                                 os.path.join(out, "proxy.mp4")],
                           capture_output=True, text=True, errors="ignore")
        assert r.returncode == 0, r.stderr[-400:]
        print(f"✓ exportado y copia ligera con {enc} (la tarjeta de este equipo)")
    dev, ctype = hw.whisper_device()
    assert (dev, ctype) in (("cpu", "int8"), ("cuda", "float16"))
    print(f"✓ Whisper: {'tarjeta NVIDIA' if dev == 'cuda' else 'procesador'} ({ctype})")
    print("TODO OK")


if __name__ == "__main__":
    main()
