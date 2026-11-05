"""
Tarjeta gráfica para codificar video: NVIDIA (NVENC), AMD (AMF) o Intel (Quick Sync). Se elige sola la que
funcione en este equipo (prueba real de 0,1 s con FFmpeg, una vez por sesión). Orden: NVIDIA → AMD → Intel, porque
en un portátil con NVIDIA + gráficos Intel la NVIDIA es la buena.

  video_encoder("h264" | "hevc") -> "h264_nvenc" | "h264_amf" | "h264_qsv" | … | None (sin tarjeta: procesador)
  vendor() -> "nvidia" | "amd" | "intel" | ""          label() -> «NVIDIA (NVENC)»…
  export_args(encoder, max_quality)   ajustes de calidad de cada marca para exportar (la tasa la pone quien llama)
  proxy_args(encoder)                 copias ligeras: lo más rápido posible
  quality_args(encoder)               convertir: alta calidad (16–24 Mbps)
"""
from __future__ import annotations

from . import media as media_tools

ENCODERS = {
    "nvidia": {"h264": "h264_nvenc", "hevc": "hevc_nvenc"},
    "amd": {"h264": "h264_amf", "hevc": "hevc_amf"},
    "intel": {"h264": "h264_qsv", "hevc": "hevc_qsv"},
}
LABELS = {"nvidia": "NVIDIA (NVENC)", "amd": "AMD (AMF)", "intel": "Intel (Quick Sync)"}
_found: dict[str, str | None] = {}


def _works(encoder: str) -> bool:
    try:
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                   "color=s=640x360:d=0.1", "-c:v", encoder, "-f", "null", "-"], timeout=20)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def video_encoder(codec: str = "h264") -> str | None:
    if codec not in _found:
        orden = list(ENCODERS)
        conocida = next((vendor_of(e) for e in _found.values() if e), "")
        if conocida:                                   # (la marca que ya funcionó, primero)
            orden.remove(conocida)
            orden.insert(0, conocida)
        _found[codec] = next((ENCODERS[v][codec] for v in orden if _works(ENCODERS[v][codec])), None)
    return _found[codec]


def vendor_of(encoder: str | None) -> str:
    for v, enc in ENCODERS.items():
        if encoder in enc.values():
            return v
    return ""


def vendor() -> str:
    return vendor_of(video_encoder("h264"))


def label() -> str:
    return LABELS.get(vendor(), "")


def export_args(encoder: str, max_quality: bool = False) -> list[str]:
    v = vendor_of(encoder)
    h264 = encoder.startswith("h264")
    tail = ["-profile:v", "high"] if h264 else ["-tag:v", "hvc1"]
    if v == "amd":
        # VBAQ: menos bloques en lo oscuro y en el movimiento. «Equilibrado» va ~2 veces más rápido que «calidad» +
        # pre-codificado; a 20–24 Mbps casi no se nota (YouTube y TikTok lo vuelven a comprimir).
        q = ["-quality", "quality", "-preencode", "true"] if max_quality else ["-quality", "balanced"]
        return q + ["-rc", "vbr_peak", "-vbaq", "true"] + tail
    if v == "nvidia":
        # p5 + «hq» con AQ espacial/temporal (lo mismo que hace VBAQ); máxima calidad: p7 y dos pasadas
        q = ["-preset", "p7", "-multipass", "fullres"] if max_quality else ["-preset", "p5", "-multipass", "qres"]
        return q + ["-tune", "hq", "-rc", "vbr", "-spatial-aq", "1", "-temporal-aq", "1", "-bf", "2"] + tail
    if v == "intel":
        q = ["-preset", "veryslow"] if max_quality else ["-preset", "medium"]
        return q + ["-extbrc", "1", "-look_ahead_depth", "40"] + tail
    return []


def proxy_args(encoder: str) -> list[str]:
    v = vendor_of(encoder)
    if v == "amd":
        return ["-c:v", encoder, "-quality", "speed", "-rc", "cqp", "-qp_i", "26", "-qp_p", "28"]
    if v == "nvidia":
        return ["-c:v", encoder, "-preset", "p1", "-tune", "ll", "-rc", "constqp", "-qp", "27"]
    if v == "intel":
        return ["-c:v", encoder, "-preset", "veryfast", "-global_quality", "27"]
    return []


def quality_args(encoder: str) -> list[str]:
    v = vendor_of(encoder)
    rate = ["-b:v", "16M", "-maxrate", "24M"]
    if v == "amd":
        return ["-c:v", encoder, "-quality", "quality", "-rc", "vbr_peak"] + rate
    if v == "nvidia":
        return ["-c:v", encoder, "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-spatial-aq", "1"] + rate
    if v == "intel":
        return ["-c:v", encoder, "-preset", "slow"] + rate
    return []


# ---------------------------------------------------------------- IA: Whisper en la tarjeta NVIDIA
_whisper_dev: tuple[str, str] | None = None


def _cuda_dll_dirs() -> list[str]:
    """Carpetas de cuBLAS / cuDNN que instala INSTALAR.bat en una PC con NVIDIA (paquetes nvidia-*-cu12)."""
    import os
    import site
    dirs = []
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for sub in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
            d = os.path.join(sp, "nvidia", sub, "bin")
            if os.path.isdir(d):
                dirs.append(d)
    return dirs


def whisper_device() -> tuple[str, str]:
    """(dispositivo, tipo) para faster-whisper: ("cuda", "float16") con una NVIDIA lista (driver + cuBLAS + cuDNN);
    si no, ("cpu", "int8"), que va bien en procesadores Intel y AMD. Sin las DLL, CTranslate2 cerraría el programa
    de golpe al transcribir: por eso se comprueba que estén ANTES de usar la tarjeta."""
    global _whisper_dev
    if _whisper_dev is not None:
        return _whisper_dev
    _whisper_dev = ("cpu", "int8")
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:          # sin NVIDIA (o sin su controlador)
            return _whisper_dev
        import glob
        import os
        dirs = _cuda_dll_dirs()
        for d in dirs:
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        have = lambda pat: any(glob.glob(os.path.join(d, pat)) for d in dirs)   # noqa: E731
        if have("cublas64_12.dll") and have("cudnn_ops64_9.dll"):
            _whisper_dev = ("cuda", "int8_float16" if equipo()["poca_vram"] else "float16")
    except Exception:  # noqa: BLE001 - cualquier duda: el procesador
        pass
    return _whisper_dev


# ---------------------------------------------------------------- el equipo: ¿modesto? ¿gráfica de 4 GB?
# El usuario: «¿está optimizado para tarjetas de 4 GB y PCs de bajos recursos? … hazlo». Reclaimer mide el equipo
# una vez (se guarda en datos/cache/equipo.json) y elige solo los ajustes ligeros; todo se puede cambiar a mano.
# Para simular otro equipo (pruebas): RECLAIMER_EQUIPO="ram=8,nucleos=4,vram=4".
_equipo: dict | None = None


def _ram_gb() -> float:
    import ctypes

    class _MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        m = _MS()
        m.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _vram_gb() -> float:
    """Memoria de la gráfica más grande (el registro de Windows la da bien en NVIDIA, AMD e Intel; 0 = no se sabe)."""
    import subprocess
    cmd = ("Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\"
           "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue | "
           "ForEach-Object { $_.'HardwareInformation.qwMemorySize' }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        return round(max(vals) / 1024 ** 3, 1) if vals else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def equipo() -> dict:
    """{"ram": GB, "nucleos": n, "vram": GB (0 = no se sabe), "modesto": bool, "poca_vram": bool}."""
    global _equipo
    if _equipo is not None:
        return _equipo
    import json
    import os
    sim = os.environ.get("RECLAIMER_EQUIPO", "")
    if sim:
        d = {k.strip(): float(v) for k, v in (x.split("=") for x in sim.split(",") if "=" in x)}
        e = {"ram": d.get("ram", 16.0), "nucleos": int(d.get("nucleos", 8)), "vram": d.get("vram", 8.0)}
    else:
        from .paths import cache_dir
        f = cache_dir("equipo") / "equipo.json"
        e = None
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
            if e.get("nucleos") != (os.cpu_count() or 0):   # (otro PC con los mismos datos): medir de nuevo
                e = None
        except Exception:  # noqa: BLE001
            e = None
        if e is None:
            e = {"ram": _ram_gb(), "nucleos": os.cpu_count() or 0, "vram": _vram_gb()}
            try:
                f.write_text(json.dumps(e), encoding="utf-8")
            except OSError:
                pass
    e["modesto"] = (0 < e["ram"] < 12) or (0 < e["nucleos"] <= 4)
    e["poca_vram"] = 0 < e["vram"] < 6
    _equipo = e
    return e


def resumen_equipo() -> str:
    e = equipo()
    vram = f"gráfica {e['vram']:g} GB" if e["vram"] else "gráfica: no se sabe cuánta memoria"
    modo = []
    if e["modesto"]:
        modo.append("modo ligero (transcripción «Rápido», vista previa a media calidad)")
    if e["poca_vram"]:
        modo.append("IA con poca memoria de gráfica (recorte «Rápido», menos memoria en la tarjeta)")
    return f"{e['ram']:g} GB de RAM · {e['nucleos']} núcleos · {vram} → " + ("; ".join(modo) or "modo normal")
