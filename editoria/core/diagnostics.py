"""
Caché y diagnóstico: cuánto ocupa lo que guarda Reclaimer, qué se puede borrar sin perder nada, y un
informe del sistema (FFmpeg, tarjeta gráfica, disco, proyecto) por si algo falla.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

from . import media as media_tools
from .paths import app_data_dir

# (carpeta dentro de cache, nombre, para qué sirve, se puede borrar: "si" | "aviso" | "no", qué pasa si se borra)
CACHE: list[tuple[str, str, str, str, str]] = [
    ("proxies", "Copias ligeras (edición fluida)", "Las de «Calidad: Media / Un cuarto».", "si",
     "Se vuelven a crear solas en segundo plano si las usas."),
    ("formas_de_onda", "Formas de onda", "Las ondas del audio en la línea de tiempo.", "si",
     "Se recalculan al abrir el proyecto (segundos)."),
    ("miniaturas", "Miniaturas de la biblioteca", "La imagen pequeña de cada archivo.", "si",
     "Se vuelven a crear al abrir el proyecto."),
    ("momentos", "Imágenes del buscador de momentos", "Las miniaturas de los resultados.", "si", "Se vuelven a crear."),
    ("transiciones", "Vistas previas", "Lo de «▶ Ver la transición» y «▶ Ver cómo queda».", "si", "Nada."),
    ("color", "Tablas de color", "Las que se usan al exportar el color de los clips.", "si", "Se recrean al exportar."),
    ("estabilizar", "Análisis de estabilización", "El movimiento medido al «Estabilizar».", "aviso",
     "Los clips estabilizados usarán un estabilizador más simple hasta que lo vuelvas a activar."),
    ("huellas_clips", "Análisis de clips (IA)", "Lo que vio la IA en cada clip (◈).", "aviso",
     "La IA vuelve a mirar tus clips sola (unos minutos)."),
    ("movimiento", "Análisis de movimiento (edits)", "Dónde hay acción en cada clip (edits musicales).", "aviso",
     "Se recalcula la próxima vez que hagas un edit (unos minutos)."),
    ("huellas_a_fondo", "«Entender mi biblioteca a fondo»", "La revisión de cada segundo de tus videos.", "aviso",
     "Habría que volver a pasar «🔬 Entender mi biblioteca a fondo» (puede tardar mucho)."),
    ("entidades", "Nombres aprendidos (IA)", "Quién y qué reconoce la IA (Jefe Maestro…).", "aviso",
     "Se pierde lo aprendido hasta que vuelvas a «Entender mi biblioteca a fondo»."),
    ("recortes", "Recortes de miniaturas (quitar fondo)", "Los usan tus miniaturas.", "no",
     "Tus miniaturas perderían los recortes: no se borra desde aquí."),
    ("miniaturas_material", "Fotogramas de miniaturas", "Las imágenes que pusiste en tus miniaturas.", "no",
     "Tus miniaturas perderían sus imágenes: no se borra desde aquí."),
    ("efectos", "Sonidos de Reclaimer", "Los whooshes, impactos… generados (pueden estar en tus proyectos).", "no",
     "Tus proyectos podrían perder esos sonidos: no se borra desde aquí."),
]
OTHER = [  # (carpeta dentro de los datos del programa, nombre, nota)
    ("modelos", "Modelos de IA", "Transcripción, visión, recortes… Se descargaron una vez; borrarlos obliga a "
                                 "descargarlos otra vez."),
    ("copias_de_seguridad", "Copias de seguridad", "Una por cada vez que guardas (se conservan las 30 últimas)."),
    ("registros", "Registro de errores", "Sirve para averiguar qué pasó si algo falla."),
]


def folder_size(path: str) -> tuple[int, int]:
    """(bytes, número de archivos)."""
    total, n = 0, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return total, n


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def scan() -> list[dict]:
    """Tamaño de cada parte de la caché y de los datos del programa."""
    base = app_data_dir()
    out = []
    for sub, name, what, can, after in CACHE:
        path = str(base / "cache" / sub)
        size, n = folder_size(path) if os.path.isdir(path) else (0, 0)
        out.append({"key": sub, "name": name, "what": what, "can": can, "after": after, "path": path,
                    "bytes": size, "files": n})
    for sub, name, what in OTHER:
        path = str(base / sub)
        size, n = folder_size(path) if os.path.isdir(path) else (0, 0)
        out.append({"key": sub, "name": name, "what": what, "can": "no", "after": "", "path": path,
                    "bytes": size, "files": n, "other": True})
    return out


def clear(key: str) -> int:
    """Borra una parte de la caché (solo las que se pueden borrar). Devuelve los bytes liberados."""
    entry = next((e for e in CACHE if e[0] == key), None)
    if entry is None or entry[3] == "no":
        raise ValueError("Esa carpeta no se puede borrar desde aquí.")
    path = str(app_data_dir() / "cache" / key)
    size, _n = folder_size(path)
    for name in os.listdir(path) if os.path.isdir(path) else []:
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            else:
                os.remove(full)
        except OSError:
            pass          # un archivo en uso (p. ej. la copia ligera que se está viendo): se queda
    left, _ = folder_size(path)
    return max(0, size - left)


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                              errors="ignore", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None


def gpu_encoder_ok() -> bool:
    """¿La tarjeta gráfica puede codificar video (NVIDIA NVENC, AMD AMF o Intel Quick Sync)? Prueba real."""
    from . import hw
    return hw.video_encoder("h264") is not None


def report(ctrl=None, check_gpu: bool = True) -> list[tuple[str, str]]:
    """Informe en líneas (título, valor)."""
    from .. import __version__
    rows: list[tuple[str, str]] = [("Reclaimer", __version__),
                                   ("Sistema", f"{platform.system()} {platform.release()} ({platform.machine()})"),
                                   ("Python", sys.version.split()[0])]
    try:
        import PySide6
        rows.append(("PySide6 (interfaz)", PySide6.__version__))
    except ImportError:
        pass
    ff = media_tools.ffmpeg()
    r = _run([ff, "-version"])
    first = r.stdout.splitlines()[0] if r and r.stdout else ""
    rows.append(("FFmpeg", first.replace("ffmpeg version ", "").split(" Copyright")[0] or "no encontrado"))
    rows.append(("Ruta de FFmpeg", ff))
    if check_gpu:
        from . import hw
        rows.append(("Exportar con la tarjeta gráfica", f"✓ {hw.label()}" if gpu_encoder_ok() else
                     "✗ no disponible (exporta con «Procesador»)"))
        rows.append(("Equipo", hw.resumen_equipo()))
        dev, ctype = hw.whisper_device()
        rows.append(("Transcribir (Whisper)", "tarjeta NVIDIA (CUDA)" if dev == "cuda" else f"procesador ({ctype})"))
    try:
        import onnxruntime as ort
        rows.append(("IA local (onnxruntime)", f"{ort.__version__} · {', '.join(ort.get_available_providers())}"))
    except ImportError:
        rows.append(("IA local (onnxruntime)", "no instalado"))
    for label, path in (("Disco de los datos del programa", str(app_data_dir())),
                        ("Disco del proyecto", os.path.dirname(ctrl.path) if ctrl is not None and ctrl.path else "")):
        if path and os.path.exists(path):
            u = shutil.disk_usage(path)
            rows.append((label, f"{human(u.free)} libres de {human(u.total)} ({os.path.splitdrive(path)[0] or path})"))
    if ctrl is not None:
        p = ctrl.project
        missing = [p.media[m].name for m in ctrl.missing if m in p.media]
        rows.append(("Proyecto", f"«{p.name}» · {len(p.clips)} clips · {len(p.media)} archivos · "
                                 f"{p.duration() / 60:.1f} min"))
        rows.append(("Archivos que no se encuentran", ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "")
                     if missing else "ninguno ✓"))
        steps, size = ctrl.history_size()
        rows.append(("Historial de deshacer", f"{steps} pasos · {human(size)} (comprimido)"))
        rows.append(("Calidad de reproducción", {"full": "Completa", "half": "Media", "quarter": "Un cuarto"}
                     .get(getattr(ctrl, "proxy_level", "full"), "Completa")))
    return rows
