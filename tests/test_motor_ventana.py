"""
Prueba de la ventana «◈ Motor de IA» (ui/motor_install_dialog.py): instala SIN consolas, con barra de progreso y
cancelar. No descarga nada: el instalador se sustituye por uno de mentira que habla igual («PASO …», «PROGRESO …»).
Ejecutar:  .venv\\Scripts\\python.exe tests\\test_motor_ventana.py [carpeta_temporal]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = sys.argv[1] if len(sys.argv) > 1 else None
if _BASE:
    os.makedirs(_BASE, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="motor_", dir=_BASE)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "datos")
os.environ["RECLAIMER_MOTOR_DATOS"] = os.path.join(_TMP, "motor")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

FALSO = r'''
import os, sys, time
assert os.environ.get("RECLAIMER_UI") == "1", "sin RECLAIMER_UI"
print("=== Motor de IA de Reclaimer: instalación ===", flush=True)
for n, txt in ((1, "Creando el Python del motor…"), (2, "Tarjeta AMD: instalando PyTorch…")):
    print(f"{n}/5 · {txt}", flush=True); print(f"PASO {n} 5 {txt}", flush=True)
    time.sleep(0.05)
for pct in (0, 25, 50, 100):
    print(f"PROGRESO {pct} {pct * 9} 900", flush=True); time.sleep(0.02)
if "--colgar" in os.environ.get("FALSO_MODO", ""):
    time.sleep(60)
print("5/5 · Comprobando la tarjeta gráfica…", flush=True); print("PASO 5 5 Comprobando la tarjeta gráfica…", flush=True)
print("✓ Listo: la IA usará tu AMD Radeon.", flush=True)
sys.exit(int(os.environ.get("FALSO_CODIGO", "0")))
'''


def pump(app, s=0.2):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication([])
    from editoria.ui import motor_install_dialog as MD
    falso = os.path.join(_TMP, "instalar_falso.py")
    with open(falso, "w", encoding="utf-8") as f:
        f.write(FALSO)
    # el de verdad: con el Python del programa, -E -s, --sin-pausa y SIN abrir consola
    orden = MD.orden_instalador()
    assert orden[1:3] == ["-E", "-s"] and orden[-1] == "--sin-pausa" and orden[-2].endswith("instalar_motor.py")
    assert os.path.basename(orden[0]).lower() == "python.exe"
    assert MD.SIN_VENTANA == getattr(subprocess, "CREATE_NO_WINDOW", 0) != 0
    src = open(os.path.join(ROOT, "motor_ia", "instalar_motor.py"), encoding="utf-8").read()
    assert src.count("creationflags=SIN_VENTANA") >= 4, "algún subproceso del instalador podría abrir una consola"
    MD.orden_instalador = lambda: [sys.executable, falso]

    win = QWidget()
    # ✓ bien instalado: lo dice y solo hay «Cerrar» (un «Reparar» sin nada que reparar confunde)
    from editoria.core import motor_ia
    from pathlib import Path
    falso_motor = Path(_TMP) / "motor"
    (falso_motor / ".venv" / "Scripts").mkdir(parents=True)
    motor_ia.PYTHON = falso_motor / ".venv" / "Scripts" / "python.exe"
    motor_ia.LISTO = falso_motor / "instalado.ok"
    motor_ia.SAM_MODEL = falso_motor / "modelos" / "sam.pt"
    motor_ia.PYTHON.write_text("")
    d0 = MD.MotorInstallDialog(win, reparar=True)          # a medias (su Python, sin marca ni SAM): continuar
    assert d0.b_ir.isVisibleTo(d0) and d0.b_ir.text() == "Continuar la instalación", d0.b_ir.text()
    d0.reject()
    motor_ia.LISTO.write_text("ok")
    d0 = MD.MotorInstallDialog(win, reparar=True)          # completo: nada que hacer
    assert not d0.b_ir.isVisibleTo(d0) and "ya está instalado" in d0.paso.text(), d0.paso.text()
    d0.reject()
    d0 = MD.MotorInstallDialog(win, reparar=True, forzar=True)   # completo pero con aviso ⚠ y pidió «Reparar»
    assert d0.b_ir.isVisibleTo(d0) and d0.b_ir.text() == "Reparar", d0.b_ir.text()
    d0.reject()
    motor_ia.PARCIAL = falso_motor / "instalando.parcial"
    motor_ia.PARCIAL.write_text("")                         # una reparación cortada a medias no cuenta
    assert not motor_ia.completo()
    motor_ia.PARCIAL.unlink()
    motor_ia.LISTO.unlink()
    motor_ia.PYTHON.unlink()
    print("✓ bien instalado: solo «Cerrar»; a medias: «Continuar la instalación»; nunca «Reparar» sin motivo")
    src_i = open(os.path.join(ROOT, "motor_ia", "instalar_motor.py"), encoding="utf-8").read()
    assert 'instalado.ok").write_text' in src_i and 'instalado.ok").unlink' in src_i
    assert 'instalando.parcial").write_text' in src_i and 'instalando.parcial").unlink' in src_i

    d = MD.MotorInstallDialog(win)
    assert d.b_ir.text() == "Instalar" and d.b_cancelar.text() == "Cerrar"
    d.empezar()
    vistos = set()
    t0 = time.time()
    while d._job is not None and time.time() - t0 < 30:
        pump(app, 0.05)
        vistos.add(d.barra.value())
    assert d.ok is True, d.paso.text()
    assert d.barra.value() == 1000 and "Listo" in d.paso.text() and "AMD" in d.detalle.text()
    assert not d.b_ir.isVisibleTo(d), "tras instalar bien no debe quedar «Reparar»"
    assert len({v for v in vistos if 0 < v < 1000}) >= 2, f"la barra no avanzó por pasos ({sorted(vistos)})"
    assert "PASO" not in d.log.toPlainText() and "PROGRESO" not in d.log.toPlainText(), "las líneas de control no "\
        "salen en los detalles"
    print("✓ instala con barra de progreso por pasos y descargas, sin consolas; los detalles, legibles")

    # un fallo: lo dice y se puede reintentar
    os.environ["FALSO_CODIGO"] = "1"
    d.empezar()
    t0 = time.time()
    while d._job is not None and time.time() - t0 < 30:
        pump(app, 0.05)
    assert d.ok is False and "No se terminó" in d.paso.text() and d.b_ir.isEnabled() and d.b_ir.isVisibleTo(d)
    os.environ.pop("FALSO_CODIGO")
    print("✓ si falla, lo dice y se puede volver a intentar")

    # cancelar a mitad: se para (y se mata lo que lanzó)
    os.environ["FALSO_MODO"] = "--colgar"
    d.empezar()
    t0 = time.time()
    while d._pid is None and time.time() - t0 < 10:
        pump(app, 0.05)
    pump(app, 0.5)
    d._cancelar_o_cerrar()
    t0 = time.time()
    while d._job is not None and time.time() - t0 < 30:
        pump(app, 0.1)
    assert d._job is None and d.ok is False, "cancelar no paró el instalador"
    os.environ.pop("FALSO_MODO")
    d.reject()
    print("✓ cancelar para el instalador")
    print("TODO OK")


if __name__ == "__main__":
    main()
