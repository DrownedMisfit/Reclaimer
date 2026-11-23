"""
Prueba: cerrar Python con un trabajo en segundo plano que NO puede parar enseguida (como «🎯 Afinar palabras» cargando
su modelo Wav2Vec2) no acaba mal: se espera un poco y, si sigue, el hilo se suelta (ui/jobs.py, _al_salir). El proceso
sale con SU código (antes: «QThread: Destroyed while thread is still running», código 127 en test_phase3).
No abre ventanas; cada caso va en un proceso aparte. Ejecutar (por el turno):
  .venv/Scripts/python.exe tests/test_salida_con_hilo.py <carpeta>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLOS: list[str] = []

HIJO = r'''
import os, sys, time, tempfile, atexit, shutil
tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=os.path.join(r"{raiz}", "_pruebas_tmp"))
atexit.register(shutil.rmtree, tmp, True)
os.environ["LOCALAPPDATA"] = tmp
os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"{raiz}")
from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)
from editoria.ui import jobs
jobs.SALIDA_ESPERA = {espera}
marca = os.path.join(r"{raiz}", "_pruebas_tmp", "salida_marca_" + str(os.getpid()) + ".txt")
atexit.register(lambda: open(marca, "w").write("hecho"))
print("marca=" + marca, flush=True)
print("tmp=" + tmp, flush=True)


def cargar_modelo(progress, cancelled):
    if "{modo}" == "python":       # ocupado ejecutando Python puro (tampoco mira «cancelled»)
        x, fin = 0, time.time() + {carga}
        while time.time() < fin:
            x += 1
    else:
        time.sleep({carga})        # (no mira «cancelled»: como cargar un modelo)
    return "listo"
if "{colgar}" == "si":             # lo pendiente de guardar se cuelga al salir: el vigilante sale igual
    import types
    sys.modules["editoria.ai.image_feedback"] = types.SimpleNamespace(flush=lambda: time.sleep(60))
job = jobs.BackgroundJob(cargar_modelo)
job.start()
time.sleep(0.3)
print("saliendo con el trabajo en marcha", flush=True)
print("t_salida=" + repr(time.time()), flush=True)
sys.exit({codigo})
'''


def ok(cond, texto):
    print(("  ✓ " if cond else "  ✗ ") + texto, flush=True)
    if not cond:
        FALLOS.append(texto)


def caso(carga: float, espera: float, codigo: int, texto: str, texto_exit: bool = False, modo: str = "dormir",
         colgar: bool = False, ver_marca: bool = True):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=os.path.join(RAIZ, "_pruebas_tmp"),
                                     encoding="utf-8") as f:
        f.write(HIJO.format(raiz=RAIZ, carga=carga, espera=espera, modo=modo, colgar="si" if colgar else "no",
                            codigo=repr("salgo con texto") if texto_exit else codigo))
        script = f.name
    try:
        t0 = time.time()
        r = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PYTHONUTF8="1"))
        dt = time.time() - t0
        ts = next((float(ln[9:]) for ln in (r.stdout or "").splitlines() if ln.startswith("t_salida=")), None)
        salir = (time.time() - ts) if ts else dt      # lo que tarda en SALIR (sin contar el arranque de Python)
        err = (r.stdout or "").strip().splitlines()[-6:] + (r.stderr or "").strip().splitlines()[-8:]
        marca = next((ln[6:] for ln in (r.stdout or "").splitlines() if ln.startswith("marca=")), "")
        hecha = bool(marca) and os.path.exists(marca)
        if hecha:
            os.remove(marca)
        tmpd = next((ln[4:] for ln in (r.stdout or "").splitlines() if ln.startswith("tmp=")), "")
        if tmpd:      # (la carpeta temporal del hijo se registró antes que Reclaimer: se borra aquí)
            __import__("shutil").rmtree(tmpd, True)
        if ver_marca:
            ok(hecha, f"{texto}: las demás tareas de salida (atexit) se hacen")
        ok(r.returncode == codigo and "Destroyed while thread" not in (r.stderr or ""),
           f"{texto}: sale con código {r.returncode} (esperado {codigo}) en {dt:.1f} s {err if r.returncode != codigo else ''}")
        return salir
    finally:
        os.remove(script)


def main():
    print("▶ salir con un trabajo que tarda en parar")
    dt = caso(2.0, 5.0, 0, "termina de cargar dentro de la espera")
    ok(dt < 8, "espera solo lo necesario")
    dt = caso(30.0, 1.0, 0, "no termina a tiempo: se suelta el hilo")
    ok(dt < 10, f"no se queda esperando los 30 s ({dt:.1f} s)")
    caso(30.0, 1.0, 3, "y respeta el código de salida de la prueba")
    caso(30.0, 1.0, 1, "sys.exit con texto: código 1", texto_exit=True)
    print("\n▶ el hilo atascado está ejecutando Python (10 veces): nunca se cuelga")
    peor = 0.0
    for i in range(10):
        peor = max(peor, caso(30.0, 1.0, 3, f"Python puro, vez {i + 1}", modo="python"))
    ok(peor < 5.0, f"la peor salida tarda {peor:.1f} s desde sys.exit (máximo 5 s)")
    print("\n▶ una tarea de salida que se cuelga")
    dt = caso(30.0, 1.0, 4, "tarea colgada", colgar=True, ver_marca=False)
    ok(dt < 8.0, f"el vigilante sale igual en {dt:.1f} s")
    print("\n" + ("✓ TODO BIEN" if not FALLOS else f"✗ {len(FALLOS)} FALLOS:\n  " + "\n  ".join(FALLOS)))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
