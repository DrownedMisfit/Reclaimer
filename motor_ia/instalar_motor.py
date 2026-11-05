"""
Instala (o repara) el MOTOR DE IA de Reclaimer en esta carpeta (F:\\Reclaimer\\motor_ia), sin tocar nada fuera:
  · un Python aparte (.venv) con PyTorch: para tarjetas AMD, la versión ROCm de AMD (usa la gráfica);
    si no hay AMD, la versión para procesador;
  · SAM 2.1 (recortar sujetos) y Demucs (separar diálogos), con las versiones que se sabe que funcionan;
  · los modelos (SAM 2.1 grande ~900 MB y Demucs ~330 MB) en motor_ia\\modelos.
Se puede volver a ejecutar cuando quieras: lo que ya está, no se repite.
Registro: motor_ia\\instalar.log
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / "Scripts" / "python.exe"
MODELS = ROOT / "modelos"
LOG = ROOT / "instalar.log"
CACHE = ROOT / "pip_cache"
ROCM = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1"
ROCM_SDK = [f"{ROCM}/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl", f"{ROCM}/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
            f"{ROCM}/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl", f"{ROCM}/rocm-7.2.1.tar.gz"]
ROCM_TORCH = [f"{ROCM}/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
              f"{ROCM}/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
              f"{ROCM}/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"]
CUDA_TORCH = ["torch==2.9.1", "torchvision==0.24.1", "torchaudio==2.9.1", "--index-url",
              "https://download.pytorch.org/whl/cu128"]      # NVIDIA (controlador 570 o más nuevo)
CPU_TORCH = ["torch==2.9.1", "torchvision==0.24.1", "torchaudio==2.9.1", "--index-url",
             "https://download.pytorch.org/whl/cpu"]
SAM2 = "git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM_MODEL = ("https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
             MODELS / "sam2.1_hiera_large.pt")
SAM_FAST = ("https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt",
            MODELS / "sam2.1_hiera_base_plus.pt")


def say(msg: str):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def run(args: list[str], env: dict | None = None) -> bool:
    say("  $ " + " ".join(str(a) for a in args)[:200])
    with open(LOG, "a", encoding="utf-8") as f:
        r = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, env=env)
    return r.returncode == 0


def gpu_vendor() -> str:
    """«nvidia», «amd» o "" según las tarjetas del PC (con las dos, NVIDIA: suele ser la potente)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    if "NVIDIA" in r.stdout:
        return "nvidia"
    if any(w in r.stdout for w in ("Radeon", "AMD")):
        return "amd"
    return ""


def has_amd() -> bool:
    return gpu_vendor() == "amd"


def py_ok(code: str) -> bool:
    return PY.exists() and subprocess.run([str(PY), "-c", code], capture_output=True).returncode == 0


def download(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 1_000_000:
        say(f"✓ Ya está: {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".parcial")
    say(f"⬇ Descargando {dest.name}…")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r   {done / total * 100:5.1f} %  ({done >> 20} de {total >> 20} MB)", end="", flush=True)
    print()
    os.replace(tmp, dest)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows
    except (AttributeError, ValueError):
        pass
    if sys.version_info[:2] != (3, 12):
        say(f"✗ Hace falta Python 3.12 (este es {sys.version.split()[0]}). Instálalo y vuelve a ejecutarlo.")
        return 1
    say("=== Motor de IA de Reclaimer: instalación ===")
    env = dict(os.environ, PIP_CACHE_DIR=str(CACHE), SAM2_BUILD_CUDA="0", PIP_DISABLE_PIP_VERSION_CHECK="1")
    if not PY.exists():
        say("1/5 · Creando el Python del motor…")
        if not run([sys.executable, "-m", "venv", str(VENV)]):
            return 1
    run([str(PY), "-m", "pip", "install", "--upgrade", "pip"], env)
    vendor = gpu_vendor()
    amd = vendor == "amd"
    otra = {"nvidia": "import torch; assert torch.version.cuda", "amd": "import torch; assert torch.version.hip"}
    if vendor and py_ok("import torch") and not py_ok(otra[vendor]):
        say("· PyTorch está instalado para otra tarjeta: se instala el de la tuya…")   # (el PC cambió de tarjeta)
        run([str(PY), "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"], env)
    if not py_ok("import torch"):
        if vendor == "nvidia":
            say("2/5 · Tarjeta NVIDIA: instalando PyTorch para la gráfica (CUDA, varios GB)…")
            if not run([str(PY), "-m", "pip", "install", "--no-cache-dir"] + CUDA_TORCH, env):
                say("✗ No se pudo instalar PyTorch para NVIDIA. Mira instalar.log.")
                return 1
        elif amd:
            say("2/5 · Tarjeta AMD: instalando PyTorch para la gráfica (ROCm, varios GB)…")
            if not (run([str(PY), "-m", "pip", "install", "--no-cache-dir"] + ROCM_SDK, env)
                    and run([str(PY), "-m", "pip", "install", "--no-cache-dir"] + ROCM_TORCH, env)):
                say("✗ No se pudo instalar PyTorch para AMD. Mira instalar.log.")
                return 1
        else:
            say("2/5 · Sin tarjeta NVIDIA ni AMD: instalando PyTorch para el procesador…")
            if not run([str(PY), "-m", "pip", "install"] + CPU_TORCH, env):
                return 1
    else:
        say("✓ PyTorch ya está.")
    if not py_ok("import sam2"):
        say("3/5 · SAM 2.1 (recortar sujetos)…")
        if not run([str(PY), "-m", "pip", "install", "--no-deps", SAM2], env):
            return 1
    say("3/5 · Demucs y lo demás (versiones probadas)…")
    if not run([str(PY), "-m", "pip", "install", "-r", str(ROOT / "requisitos.txt")], env):
        return 1
    say("4/5 · Modelos…")
    download(*SAM_MODEL)
    download(*SAM_FAST)
    menv = dict(env, TORCH_HOME=str(MODELS))
    run([str(PY), "-c", "from demucs.pretrained import get_model; get_model('htdemucs_ft')"], menv)
    say("5/5 · Comprobando la tarjeta gráfica…")
    r = subprocess.run([str(PY), "-c", "import torch;print(torch.__version__);print(torch.cuda.is_available());"
                                       "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                       capture_output=True, text=True)
    lines = (r.stdout or "").split("\n")
    if len(lines) > 1 and lines[1].strip() == "True":
        say(f"✓ Listo: la IA usará tu {lines[2].strip()}.")
    elif amd:
        say("⚠ Instalado, pero la tarjeta AMD no se detecta: irá por el procesador (más lento).\n"
            "  Actualiza el controlador AMD Adrenalin a la versión 26.2.2 o más nueva y vuelve a ejecutar esto.")
    elif vendor == "nvidia":
        say("⚠ Instalado, pero la tarjeta NVIDIA no se detecta: irá por el procesador (más lento).\n"
            "  Actualiza el controlador de NVIDIA (570 o más nuevo) y vuelve a ejecutar esto.")
    else:
        say("✓ Listo (irá por el procesador).")
    shutil.rmtree(CACHE, ignore_errors=True)       # la caché de descargas no hace falta guardarla
    return 0


if __name__ == "__main__":
    code = main()
    if "--sin-pausa" not in sys.argv:
        input("\nPulsa Intro para cerrar…")
    sys.exit(code)
