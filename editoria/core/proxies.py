"""
Resolución de la línea de tiempo (proxies), como «Timeline Proxy Resolution» de DaVinci Resolve.

Para que la edición vaya fluida con material pesado (1440p, 4K, 60 fps), el visor puede reproducir
copias ligeras de cada video a media resolución o a un cuarto. La exportación usa SIEMPRE los
archivos originales: la calidad final no cambia.

Las copias se crean una vez (en segundo plano) y se guardan en la caché.
"""
from __future__ import annotations

import os
import subprocess

from . import media as media_tools
from .paths import cache_dir

LEVELS = {"full": ("Completa", 1), "half": ("Media", 2), "quarter": ("Un cuarto", 4)}


VIDEO_EXT_PROXY = (".mp4", ".mov", ".mxf", ".mkv", ".lrv", ".lrf")


def camera_proxy(path: str) -> str | None:
    """La copia ligera que YA graba la cámara junto al video (así no hay que crearla), como hace Shotcut:
      · GoPro: GX010123.MP4 → GL010123.LRV (o GH… → GL…) en la misma carpeta;
      · DJI: DJI_0001.MP4 → DJI_0001.LRF;
      · una subcarpeta «Proxy» o «Proxies» con un video del mismo nombre."""
    d, base = os.path.split(path)
    stem, _ext = os.path.splitext(base)
    cands = [os.path.join(d, stem + ext) for ext in (".LRV", ".lrv", ".LRF", ".lrf")]
    if len(stem) >= 4 and stem[:2].upper() in ("GX", "GH"):
        cands += [os.path.join(d, "GL" + stem[2:] + ext) for ext in (".LRV", ".lrv")]
    for sub in ("Proxy", "Proxies", "proxy", "proxies"):
        cands += [os.path.join(d, sub, stem + ext) for ext in (".mp4", ".MP4", ".mov", ".MOV")]
    seen = set()
    for c in cands:
        k = os.path.normcase(c)
        if k in seen or k == os.path.normcase(path):
            continue
        seen.add(k)
        if os.path.isfile(c) and os.path.getsize(c) > 0:
            return c
    return None


def _camera_ok(path: str, cam: str, height: int, levels: list[str]) -> list[str]:
    """Niveles para los que la copia de cámara sirve: se lee como video, dura lo mismo que el original (±0,5 s o 1 %),
    tiene audio si el original lo tiene y su alto llega al ~70 % del de ese nivel (si no, se codifica la nuestra)."""
    try:
        a, b = media_tools.probe(path), media_tools.probe(cam)
    except Exception:  # noqa: BLE001 - no se puede leer: no sirve
        return []
    if not b.get("has_video") or b.get("height", 0) <= 0:
        return []
    da, db = float(a.get("duration") or 0), float(b.get("duration") or 0)
    if da <= 0 or abs(da - db) > max(0.5, 0.01 * da):
        return []                                         # (truncada por la batería u otro video con el mismo nombre)
    if a.get("has_audio") and not b.get("has_audio"):
        return []                                         # (el visor suena desde la copia: sin audio sonaría mudo)
    alto = height or a.get("height") or 0
    return [lv for lv in levels if not alto or b["height"] >= 0.7 * alto / LEVELS[lv][1]]


def _copiar(src: str, dest: str, cancelled=None, progress=None) -> bool:
    """Copia por trozos (cancelable, con avance) a «.tmp.mp4» y renombra al final. Siempre copia: un enlace duro haría
    que «liberar caché» no liberara nada y bloquearía borrar el archivo de la cámara."""
    tmp = dest + ".tmp.mp4"
    try:
        total = max(1, os.path.getsize(src))
        hecho = 0
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                if cancelled is not None and cancelled():
                    raise InterruptedError()
                trozo = fi.read(4 * 1024 * 1024)
                if not trozo:
                    break
                fo.write(trozo)
                hecho += len(trozo)
                if progress:
                    progress(min(1.0, hecho / total))
        os.replace(tmp, dest)
        return True
    except (OSError, InterruptedError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def clean_leftovers(min_age_s: float = 600.0) -> int:
    """Copias a medias de una sesión anterior (Reclaimer se cerró mientras las hacía): fuera. Devuelve cuántas."""
    import time
    n = 0
    try:
        for f in cache_dir("proxies").glob("*.tmp.mp4"):
            try:
                if time.time() - f.stat().st_mtime >= min_age_s:
                    f.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def proxy_path(path: str, level: str) -> str:
    return str(cache_dir("proxies") / f"{media_tools.cache_key(path)}_{level}.mp4")


_HAS: dict = {}          # (ruta, nivel) → (existe, cuándo se miró): el visor pregunta varias veces por fotograma


def has_proxy(path: str, level: str) -> bool:
    if level == "full":
        return False
    import time
    k = (path, level)
    got = _HAS.get(k)
    now = time.monotonic()
    if got is None or now - got[1] > 3.0:          # (se vuelve a mirar en el disco cada 3 s como mucho)
        got = _HAS[k] = (os.path.exists(proxy_path(path, level)), now)
    return got[0]


def forget_cache():
    """Una copia nueva o la caché borrada: que se vuelva a mirar en el disco ya."""
    _HAS.clear()


_HW: bool | None = None


def hw_encoder() -> bool:
    """¿Hay codificador de video por hardware (NVIDIA, AMD o Intel)? Se comprueba una vez (core/hw.py)."""
    from . import hw
    return hw.video_encoder("h264") is not None


def _video_args(hw_on: bool) -> list[str]:
    if hw_on:   # la tarjeta gráfica: ~3× más rápido y casi sin usar el procesador (sigues editando fluido)
        from . import hw
        return hw.proxy_args(hw.video_encoder("h264")) + ["-g", "15", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-g", "15", "-keyint_min", "15",
            "-pix_fmt", "yuv420p", "-threads", "4"]


def make_proxies(path: str, height: int, levels: list[str], cancelled=None, progress=None,
                 duration: float = 0.0) -> list[str]:
    """Crea de UNA pasada las copias ligeras de esos niveles (el video se lee una sola vez). Devuelve las rutas.
    GOP corto (una imagen clave cada 15 fotogramas): saltar por la copia es instantáneo."""
    want = [lv for lv in dict.fromkeys(levels) if LEVELS[lv][1] > 1 and not os.path.exists(proxy_path(path, lv))]
    if not want:
        return [proxy_path(path, lv) for lv in levels if LEVELS[lv][1] > 1]
    cam = camera_proxy(path)
    if cam is not None:                    # 📷 la cámara ya la grabó: se usa tal cual (copia, sin codificar)
        usables = _camera_ok(path, cam, height, want)
        for lv in usables:
            if not _copiar(cam, proxy_path(path, lv), cancelled, progress):
                return []                                 # (cancelado)
        want = [lv for lv in want if lv not in usables]
        if not want:
            return [proxy_path(path, lv) for lv in levels if LEVELS[lv][1] > 1]
    for hw in ([True, False] if hw_encoder() else [False]):
        outs = {lv: proxy_path(path, lv) for lv in want}
        tmps = {lv: o + ".tmp.mp4" for lv, o in outs.items()}
        scales = []
        for k, lv in enumerate(want):
            h = max(144, int(height / LEVELS[lv][1]) // 2 * 2) if height else 360
            scales.append(f"[s{k}]scale=-2:{h}[v{k}]")
        graph = (f"[0:v]split={len(want)}" + "".join(f"[s{k}]" for k in range(len(want))) + ";" + ";".join(scales)
                 if len(want) > 1 else scales[0].replace("[s0]", "[0:v]"))
        args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"]
        if hw:
            args += ["-hwaccel", "d3d11va"]               # también leer el video con la gráfica
        args += ["-i", path, "-filter_complex", graph]
        for k, lv in enumerate(want):
            args += ["-map", f"[v{k}]", "-map", "0:a?"] + _video_args(hw)
            args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmps[lv]]
        # sin prisa: prioridad baja (se hace mientras editas sin quitarte fluidez)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=flags, text=True)
        stopped = False
        for line in proc.stdout:      # el avance de verdad
            if cancelled is not None and cancelled():
                proc.kill()
                stopped = True
                break
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
        ok = not stopped and proc.returncode == 0 and all(os.path.exists(t) for t in tmps.values())
        if ok:
            for lv in want:
                os.replace(tmps[lv], outs[lv])
            return [proxy_path(path, lv) for lv in levels if LEVELS[lv][1] > 1]
        for t in tmps.values():
            if os.path.exists(t):
                os.remove(t)
        if stopped:
            return []
    return []


def make_proxy(path: str, height: int, level: str, cancelled=None, progress=None,
               duration: float = 0.0) -> str | None:
    """Crea la copia ligera (si no existe). Devuelve su ruta. progress(0–1) mientras la hace."""
    if LEVELS[level][1] == 1:
        return None
    out = make_proxies(path, height, [level], cancelled, progress, duration)
    return out[0] if out else None
