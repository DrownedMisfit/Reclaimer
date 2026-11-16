"""
◈ Motor de IA avanzada (F:\\Reclaimer\\motor_ia): un Python aparte con PyTorch para la tarjeta gráfica (CUDA en
NVIDIA, ROCm en AMD; sin ninguna, el procesador)
y los modelos pesados (SAM 2.1 para recortar sujetos, Demucs para separar diálogos). Va aparte del programa para
que un fallo o un cierre del modelo nunca se lleve a Reclaimer por delante.

  available() -> (sí/no, por qué)
  run(script, job, progress, cancelled) -> ruta del resultado (o lanza RuntimeError)
Los trabajos escriben «PROGRESO f texto» y, al terminar, «LISTO ruta».
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .paths import PROGRAM_DIR

ROOT = PROGRAM_DIR / "motor_ia"
# 📦 En la versión «todo en uno», su Python y sus modelos van en <carpeta>\motor_ia_datos (fuera de app\): así no se
# pierden al actualizar Reclaimer. Si no, junto a los scripts, como siempre.
DATOS_MOTOR = Path(os.environ.get("RECLAIMER_MOTOR_DATOS") or ROOT)
PYTHON = DATOS_MOTOR / ".venv" / "Scripts" / "python.exe"
JOBS = ROOT / "trabajos"
MODELS = DATOS_MOTOR / "modelos"
SAM_MODEL = MODELS / "sam2.1_hiera_large.pt"
SAM_CONFIG = "configs/sam2.1/sam2.1_hiera_l.yaml"
SAM_FAST_MODEL = MODELS / "sam2.1_hiera_base_plus.pt"        # «Rápida»: ~2 veces más rápido, algo menos fino
SAM_FAST_CONFIG = "configs/sam2.1/sam2.1_hiera_b+.yaml"


INSTALLER = ROOT / "INSTALAR_MOTOR_IA.bat"


def _reparar_venv():
    """📦 Si la carpeta «todo en uno» se movió (otro disco, otra letra), el Python del motor apunta al Python de antes:
    se le dice dónde está ahora (pyvenv.cfg). Sin esto el motor dejaría de abrir hasta reinstalarlo."""
    cfg = DATOS_MOTOR / ".venv" / "pyvenv.cfg"
    nuevo = PROGRAM_DIR.parent / "python"
    if not os.environ.get("RECLAIMER_PORTABLE") or not cfg.is_file() or not (nuevo / "python.exe").is_file():
        return
    try:
        lineas = cfg.read_text(encoding="utf-8").splitlines()
        casa = next((ln.split("=", 1)[1].strip() for ln in lineas if ln.split("=")[0].strip() == "home"), "")
        if not casa or Path(casa, "python.exe").is_file():
            return
        out = []
        for ln in lineas:
            k = ln.split("=", 1)[0].strip()
            if k == "home":
                ln = f"home = {nuevo}"
            elif k == "executable":
                ln = f"executable = {nuevo / 'python.exe'}"
            elif k == "command":
                ln = f"command = {nuevo / 'python.exe'} -m venv {DATOS_MOTOR / '.venv'}"
            out.append(ln)
        cfg.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        pass


_reparar_venv()


def status() -> dict:
    """Cómo está el motor: {"installed", "torch", "gpu" (sí/no), "name", "amd" (hay tarjeta AMD en el PC)}.
    Tarda unos segundos (arranca su Python): llamar en segundo plano."""
    out = {"installed": PYTHON.exists(), "torch": "", "gpu": False, "name": "", "amd": False, "nvidia": False,
           "vendor": "", "sam": SAM_MODEL.exists()}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                           capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out["nvidia"] = "NVIDIA" in r.stdout
        out["amd"] = not out["nvidia"] and any(w in r.stdout for w in ("Radeon", "AMD"))
        out["vendor"] = "nvidia" if out["nvidia"] else "amd" if out["amd"] else ""
    except (OSError, subprocess.SubprocessError):
        pass
    if not out["installed"]:
        return out
    try:
        r = subprocess.run([str(PYTHON), "-c", "import torch;print(torch.__version__);print(torch.cuda.is_available());"
                                               "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                           capture_output=True, text=True, timeout=180,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = (r.stdout or "").split("\n")
        out["torch"] = lines[0].strip() if lines else ""
        out["gpu"] = len(lines) > 1 and lines[1].strip() == "True"
        out["name"] = lines[2].strip() if len(lines) > 2 else ""
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def open_installer():
    """Abre el instalador en su propia ventana (se ve cómo va)."""
    subprocess.Popen(["cmd", "/c", "start", "", str(INSTALLER)], cwd=str(ROOT))


def available(what: str = "sam") -> tuple[bool, str]:
    if not PYTHON.exists():
        return False, ("Falta el motor de IA: Ayuda → «◈ Motor de IA…» → «Instalar» (o ejecuta "
                       "motor_ia\\INSTALAR_MOTOR_IA.bat).")
    if what == "sam" and not SAM_MODEL.exists():
        return False, "Falta el modelo SAM 2.1 (motor_ia\\modelos)."
    return True, ""


class SinTarjeta(RuntimeError):
    """El motor no tiene tarjeta gráfica usable (el trabajo escribió «SIN_TARJETA»)."""


def whisper_ok() -> bool:
    """¿El motor puede transcribir (openai-whisper instalado)? Rápido: solo mira archivos."""
    return PYTHON.exists() and (DATOS_MOTOR / ".venv" / "Lib" / "site-packages" / "whisper" / "__init__.py").exists()


def run(script: str, job: dict, progress=None, cancelled=None, partial=None) -> str:
    ok, why = available("sam" if script == "recortar.py" else "")
    if not ok:
        raise RuntimeError(why)
    DATOS_MOTOR.mkdir(parents=True, exist_ok=True)
    fd, jp = tempfile.mkstemp(prefix="trabajo_", suffix=".json", dir=str(DATOS_MOTOR))
    os.close(fd)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(job, f)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", TORCH_HOME=str(MODELS), HF_HOME=str(MODELS / "hf"), TQDM_DISABLE="1",
               TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL="1",   # atención rápida en AMD: ~3 veces más rápido
               MIOPEN_USER_DB_PATH=str(DATOS_MOTOR / "miopen"), MIOPEN_CUSTOM_CACHE_DIR=str(DATOS_MOTOR / "miopen"))
    proc = subprocess.Popen([str(PYTHON), str(JOBS / script), jp], cwd=str(DATOS_MOTOR), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result, tail = None, []
    import queue
    import threading
    lines: queue.Queue = queue.Queue()

    def leer():                                      # (en un hilo: así «Cancelar» no espera a que el trabajo hable)
        buf = ""
        try:
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                if ch not in "\r\n":
                    buf += ch
                    continue
                lines.put(buf.strip())
                buf = ""
        except (OSError, ValueError):
            pass
        if buf.strip():
            lines.put(buf.strip())
        lines.put(None)

    threading.Thread(target=leer, daemon=True, name="motor_ia_salida").start()
    try:
        while True:
            if cancelled is not None and cancelled():
                proc.kill()
                proc.wait()
                raise RuntimeError("Cancelado.")
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith("PROGRESO ") and progress:
                parts = line.split(" ", 2)
                try:
                    progress(float(parts[1]), parts[2] if len(parts) > 2 else "")
                except ValueError:
                    pass
            elif line.startswith("LISTO "):
                result = line[6:].strip()
            elif line.startswith("PARCIAL ") and partial is not None:
                try:
                    partial(line[8:].strip())        # (lo hecho hasta ahora: ver trabajos/transcribir.py)
                except Exception:  # noqa: BLE001 - un parcial que falla no corta el trabajo
                    pass
            elif line == "SIN_TARJETA":
                tail.append(line)
            elif line and "it/s]" not in line and "s/it]" not in line and "Triton kernels" not in line \
                    and "slower DTW" not in line:
                tail = (tail + [line])[-15:]
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.SubprocessError:
                pass
        try:
            os.remove(jp)
        except OSError:
            pass
    if "SIN_TARJETA" in tail:
        raise SinTarjeta("El motor de IA no encuentra una tarjeta gráfica usable.")
    if proc.returncode != 0 or not result:
        raise RuntimeError("El motor de IA falló:\n" + "\n".join(tail[-8:]))
    return result
