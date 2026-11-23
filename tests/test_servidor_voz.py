"""
⚡ Transcripción más rápida: el servidor de voz del motor de IA (modelo siempre cargado) y lo que lo rodea, SIN
descargar ni cargar ningún modelo (un servidor de mentira con el mismo protocolo):
  · una orden → «LISTO resultado»; el proceso SIGUE abierto para la siguiente (mismo proceso);
  · «FALLO» lanza un error pero el servidor sigue vivo; progreso y resultados a medias llegan a quien llama;
  · «Cancelar» corta al momento (cierra el proceso) y la siguiente orden lo vuelve a abrir;
  · precargar el mismo modelo dos veces no hace nada; los otros trabajos del motor (SAM…) lo cierran si está libre;
  · la red de seguridad (huecos con voz) mete lo oído solo dentro de cada hueco;
  · el alineador sin tarjeta calcula en el procesador (aquí con un modelo de mentira) y respeta «Cancelar».
Ejecutar:  .venv/Scripts/python.exe tests/test_servidor_voz.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (EDITORIA_TARJETA_MOTOR=0 y datos aislados)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402

from editoria.core import motor_ia  # noqa: E402
from pathlib import Path  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="reclaimer_servidor_voz_", dir=os.path.join(_RAIZ, "_pruebas_tmp"))
__import__("atexit").register(shutil.rmtree, _TMP, True)

FALSO = r'''
import json, sys, time, os
print("PREPARADO", flush=True)
for linea in sys.stdin:
    o = json.loads(linea)
    c = o.get("cmd")
    if c == "salir":
        break
    if c == "cargar":
        print("PROGRESO 0.5 cargando", flush=True)
        print("LISTO " + o.get("modelo", ""), flush=True)
    elif c == "pid":
        print("PARCIAL a_medias", flush=True)
        print("LISTO " + str(os.getpid()), flush=True)
    elif c == "fallar":
        print("FALLO ValueError: algo raro", flush=True)
    elif c == "lento":
        for i in range(300):
            print(f"PROGRESO {i / 300:.3f} pensando", flush=True)
            time.sleep(0.1)
        print("LISTO tarde", flush=True)
'''


def prueba_servidor():
    jobs = Path(_TMP) / "trabajos"
    jobs.mkdir()
    (jobs / "servidor_voz.py").write_text(FALSO, encoding="utf-8")
    viejo = motor_ia.PYTHON, motor_ia.JOBS, motor_ia.DATOS_MOTOR
    motor_ia.PYTHON, motor_ia.JOBS, motor_ia.DATOS_MOTOR = Path(sys.executable), jobs, Path(_TMP)
    voz = motor_ia._ServidorVoz()
    try:
        prog, parc = [], []
        assert voz.pedir({"cmd": "cargar", "modelo": "turbo"}, lambda f, t: prog.append((f, t))) == "turbo"
        assert prog == [(0.5, "cargando")] and voz.modelo == "turbo" and voz.activo()
        pid1 = voz.pedir({"cmd": "pid"}, partial=parc.append)
        pid2 = voz.pedir({"cmd": "pid"})
        assert pid1 == pid2 and parc == ["a_medias"], (pid1, pid2, parc)
        print("✓ el servidor sigue abierto entre órdenes (mismo proceso), con progreso y resultados a medias")

        voz.cargar("turbo")                           # (ya cargado: ni siquiera pregunta)
        try:
            voz.pedir({"cmd": "fallar"})
            raise AssertionError("debía fallar")
        except RuntimeError as exc:
            assert "algo raro" in str(exc), exc
        assert voz.activo() and voz.pedir({"cmd": "pid"}) == pid1
        print("✓ una orden que falla no tira el servidor")

        t0 = time.perf_counter()
        marca = {"t": None}

        def cancelar():
            if marca["t"] is None and time.perf_counter() - t0 > 0.5:
                marca["t"] = time.perf_counter()
            return marca["t"] is not None
        try:
            voz.pedir({"cmd": "lento"}, cancelled=cancelar)
            raise AssertionError("debía cancelarse")
        except RuntimeError as exc:
            assert "Cancelado" in str(exc), exc
        espera = time.perf_counter() - marca["t"]
        assert espera < 2.0 and not voz.activo() and voz.modelo == "", espera
        pid3 = voz.pedir({"cmd": "pid"})
        assert pid3 != pid1 and voz.activo()
        print(f"✓ «Cancelar» corta al momento ({espera:.2f} s) y la siguiente orden lo vuelve a abrir")

        motor_ia._voz, antes = voz, motor_ia._voz
        try:
            voz.cerrar(solo_si_libre=True)
            assert not voz.activo()
        finally:
            motor_ia._voz = antes
        print("✓ los otros trabajos del motor (SAM, Demucs) lo cierran si no está trabajando")
    finally:
        voz.cerrar()
        motor_ia.PYTHON, motor_ia.JOBS, motor_ia.DATOS_MOTOR = viejo


def prueba_huecos():
    from editoria.ai import transcription as T
    sr = 16000
    samples = np.zeros(20 * sr, np.float32)
    tr = {"language": "es", "model": "x", "words": [[0.5, 1.0, "hola", 0.9], [12.0, 12.5, "adiós", 0.9]],
          "segments": [[0.5, 1.0, 0, 1], [12.0, 12.5, 1, 2]]}
    found = [(1.0, 12.0)]
    clips = T._hole_clips(samples, found)
    assert clips == [[0.7, 12.3]], clips
    # lo oído: una palabra dentro del hueco y otra que se sale (de la palabra de al lado): solo entra la de dentro
    por_tramo = [[[5.0, 5.5, "dentro", 0.8], [0.6, 0.95, "hola", 0.8]]]
    out = T._merge_holes(tr, found, por_tramo)
    assert [w[2] for w in out["words"]] == ["hola", "dentro", "adiós"], out["words"]
    assert out["filled"] == [[1.0, 12.0]]
    assert all(0 <= a < b <= len(out["words"]) for _s, _e, a, b in out["segments"])
    assert T._merge_holes(tr, found, [[]]) is tr
    assert T.oir_tramos_tarjeta(samples, clips, "equilibrado") is None    # (sin motor: lo hace el procesador)
    print("✓ red de seguridad: lo oído se mete solo dentro del hueco; sin motor, al procesador")


def prueba_alineador_procesador():
    from editoria.ai import align
    llamadas = []

    def falso(seg):
        llamadas.append(len(seg))
        return np.zeros((max(1, len(seg) // 320), 4), np.float32)
    viejo = align._emissions
    align._emissions = falso
    try:
        audio = np.zeros(10 * 16000, np.float32)
        ems = align.emissions_many(audio, [(0.0, 2.0), (2.0, 2.05), (3.0, 6.0)])
        assert ems[1] is None and ems[0].shape[0] == 100 and ems[2].shape[0] == 150, [e is None for e in ems]
        assert len(llamadas) == 2
        corta = align.emissions_many(audio, [(0.0, 2.0), (3.0, 6.0)], cancelled=lambda: True)
        assert corta == [None, None]
    finally:
        align._emissions = viejo
    print("✓ alineador sin tarjeta: en el procesador, tramo a tramo (los muy cortos se saltan) y se puede cancelar")


def main():
    prueba_servidor()
    prueba_huecos()
    prueba_alineador_procesador()
    print("TODO BIEN")


if __name__ == "__main__":
    main()
