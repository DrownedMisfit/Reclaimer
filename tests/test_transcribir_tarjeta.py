"""
🎙 Transcribir en la tarjeta gráfica por el motor de IA (AMD con ROCm): solo si este PC lo tiene (si no, se omite).
  · con la narración del proyecto de ejemplo y bloques cortos: palabras con tiempos, resultados a medias por bloque;
  · seguir desde donde se cortó (start_at + prev) no repite lo ya hecho;
  · si se apaga en los ajustes, transcribe con el procesador como siempre.
Ejecutar:  .venv/Scripts/python.exe tests/test_transcribir_tarjeta.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["EDITORIA_TARJETA_MOTOR"] = "1"           # (esta prueba es justo la de la tarjeta)
sys.path.insert(0, _RAIZ)
from editoria.core import media as M  # noqa: E402

_FF = M.ffmpeg()
os.environ["PATH"] = os.path.dirname(_FF) + os.pathsep + os.environ.get("PATH", "")
_TMP = tempfile.mkdtemp(prefix="reclaimer_tarjeta_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.ai import transcription as T  # noqa: E402
from editoria.core import example_project, motor_ia  # noqa: E402


def main():
    if not T._usar_tarjeta_motor("large-v3-turbo"):
        print("(omitida: este PC no transcribe con la tarjeta por el motor de IA)")
        print("TODO BIEN")
        return
    samples = M.decode_mono(example_project.NARRACION, 16000)
    parciales = []
    t0 = time.perf_counter()
    tr = T.transcribe(samples, "equilibrado", "es", partial=lambda p: parciales.append(p), block=15.0)
    dt = time.perf_counter() - t0
    assert tr.get("motor") == "tarjeta" and tr["model"] == "large-v3-turbo", (tr.get("motor"), tr["model"])
    texto = " ".join(w[2] for w in tr["words"]).lower()
    assert len(tr["words"]) > 40 and "silencios" in texto and "música" in texto, texto[:200]
    assert all(w[1] >= w[0] for w in tr["words"]) and all(b[0] >= a[0] for a, b in zip(tr["words"], tr["words"][1:]))
    assert parciales and all("hasta" in p for p in parciales), len(parciales)
    print(f"✓ transcrita en la tarjeta ({dt:.0f} s con la carga del modelo): {len(tr['words'])} palabras, "
          f"{len(parciales)} resultados a medias por bloque")

    corte = parciales[0]
    tr2 = T.transcribe(samples, "equilibrado", "es", block=15.0, start_at=corte["hasta"], prev=corte)
    n_antes = sum(1 for w in corte["words"] if w[1] <= corte["hasta"])
    assert tr2["words"][:n_antes] == [list(w) for w in corte["words"][:n_antes]]
    assert len(tr2["words"]) > n_antes + 20
    print("✓ seguir desde donde se cortó conserva lo hecho y añade el resto")

    from editoria.ai.base import Cancelled
    from editoria.core.paths import temp_dir
    marca = {"t": None}

    def cancelar():
        if marca["t"] is None and time.perf_counter() - t1 > 3.0:   # (a los 3 s: en plena carga del modelo)
            marca["t"] = time.perf_counter()
        return marca["t"] is not None
    t1 = time.perf_counter()
    try:
        T.transcribe(samples, "equilibrado", "es", cancelled=cancelar, block=15.0)
        raise AssertionError("debía cancelarse")
    except Cancelled:
        pass
    espera = time.perf_counter() - marca["t"]
    assert espera < 2.0, f"«Cancelar» tardó {espera:.1f} s"
    sobras = [f for f in os.listdir(temp_dir()) if f.startswith("voz_")]
    assert not sobras, sobras
    print(f"✓ «Cancelar» corta al momento ({espera:.2f} s, aunque el modelo esté cargando) y no deja archivos")

    from PySide6.QtCore import QSettings
    st = QSettings("EditorIA", "EditorIA")
    viejo = st.value("voz/tarjeta_motor")
    st.setValue("voz/tarjeta_motor", "false")
    try:
        assert not T._usar_tarjeta_motor("large-v3-turbo")
    finally:
        if viejo is None:
            st.remove("voz/tarjeta_motor")
        else:
            st.setValue("voz/tarjeta_motor", viejo)
    print("✓ se puede apagar (ajuste voz/tarjeta_motor): vuelve al procesador")
    assert motor_ia.whisper_ok()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
