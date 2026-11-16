"""Carpetas donde el programa guarda caché, modelos de IA, autoguardado, copias de seguridad y registros.

Todo vive JUNTO al programa (F:/Reclaimer/datos), no en C: — así el disco del sistema no se llena.
(Antes estaba en %LOCALAPPDATA%/EditorIA: migrate_old_data() lo muda la primera vez que se abre.)
Las pruebas usan otra carpeta con la variable EDITORIA_DATOS.
📦 En la versión «todo en uno», Reclaimer.exe pone RECLAIMER_DATOS (<carpeta>\\datos) y RECLAIMER_RAIZ (la carpeta de
Reclaimer.exe): datos, exportados y grabaciones quedan FUERA de app\\, así actualizar (cambiar app\\) no borra nada.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

PROGRAM_DIR = Path(__file__).resolve().parents[2]
_MADE: set[str] = set()     # carpetas ya creadas: no se vuelve a tocar el disco (se llamaba cientos de veces al dibujar)


def _ensure(d: Path) -> Path:
    key = str(d)
    if key not in _MADE:
        d.mkdir(parents=True, exist_ok=True)
        _MADE.add(key)
    return d


_DATOS: dict[str, Path] = {}     # (por carpeta pedida: las pruebas la cambian sobre la marcha)


def app_data_dir() -> Path:
    """La carpeta de datos. Si no se puede escribir (Reclaimer dentro de «Archivos de programa», una carpeta de solo
    lectura…), la del usuario: %LOCALAPPDATA%\\Reclaimer\\datos (así nunca deja de abrir sin avisar)."""
    override = os.environ.get("EDITORIA_DATOS") or os.environ.get("RECLAIMER_DATOS")
    d = Path(override) if override else PROGRAM_DIR / "datos"
    hecho = _DATOS.get(str(d))
    if hecho is not None:
        return hecho
    pedido = str(d)
    prueba = d / f".escritura_{os.getpid()}"
    try:
        d.mkdir(parents=True, exist_ok=True)
        prueba.write_text("ok", encoding="utf-8")
    except OSError:
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Reclaimer" / "datos"
        d.mkdir(parents=True, exist_ok=True)
        os.environ["RECLAIMER_DATOS_MOVIDOS"] = str(d)  # (la ventana lo avisa)
    else:
        try:
            prueba.unlink(missing_ok=True)
        except OSError:                                 # (un antivirus que lo tiene abierto: da igual)
            pass
    _DATOS[pedido] = _ensure(d)
    return _DATOS[pedido]


def user_dir() -> Path:
    """Donde van tus cosas (Exportados, Audio extraído, Grabaciones de voz sin proyecto): junto al programa; en la
    versión «todo en uno», junto a Reclaimer.exe (y si ahí no se puede escribir, junto a los datos)."""
    raiz = os.environ.get("RECLAIMER_RAIZ")
    if not raiz:
        return PROGRAM_DIR
    app_data_dir()                                 # (comprueba si se puede escribir: si no, marca MOVIDOS)
    return app_data_dir().parent if os.environ.get("RECLAIMER_DATOS_MOVIDOS") else Path(raiz)


def temp_dir() -> Path:
    """Archivos de trabajo pasajeros (guiones de FFmpeg, audio de escucha…): también en D:, no en el TEMP de C:."""
    return _ensure(app_data_dir() / "temporal")


def old_data_dir() -> Path | None:
    """La carpeta de antes en C: (%LOCALAPPDATA%/EditorIA), si aún tiene algo que mudar."""
    if os.environ.get("EDITORIA_DATOS") or os.environ.get("RECLAIMER_PORTABLE"):   # (la portátil no se lleva lo de otro)
        return None
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    d = Path(base) / "EditorIA"
    try:
        if d.is_dir() and d.resolve() != app_data_dir().resolve() and any(d.iterdir()):
            return d
    except OSError:
        return None
    return None


def migrate_old_data(progress=None) -> tuple[int, int]:
    """Muda los datos de C: a la carpeta nueva (archivo por archivo; si ya está copiado igual, solo se quita de
    C:; si los dos existen y son distintos, gana el más reciente). progress(hechos, total, nombre).
    Devuelve (archivos mudados, archivos que no se pudieron mover — se quedan en C: y se reintenta otro día)."""
    old = old_data_dir()
    if old is None:
        return 0, 0
    new = app_data_dir()
    files = [p for p in old.rglob("*") if p.is_symlink() or p.is_file()]
    moved = failed = 0
    for i, src in enumerate(files):
        if progress:
            progress(i, len(files), src.name)
        dst = new / src.relative_to(old)
        try:
            if src.is_symlink():                     # enlaces de la caché de Hugging Face: no son datos
                src.unlink()
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                s, d = src.stat(), dst.stat()
                if s.st_size == d.st_size and abs(s.st_mtime - d.st_mtime) < 2:
                    src.unlink()                     # ya estaba copiado igual
                elif s.st_mtime > d.st_mtime:
                    shutil.copy2(src, dst)           # el de C: es más nuevo
                    src.unlink()
                else:
                    src.unlink()                     # el de D: es más nuevo
            else:
                shutil.move(str(src), str(dst))
            moved += 1
        except OSError:
            failed += 1
    for d in sorted((p for p in old.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        old.rmdir()
    except OSError:
        pass
    if progress:
        progress(len(files), len(files), "")
    return moved, failed


def cache_dir(sub: str) -> Path:
    return _ensure(app_data_dir() / "cache" / sub)


def backups_dir() -> Path:
    d = app_data_dir() / "copias_de_seguridad"
    d.mkdir(parents=True, exist_ok=True)
    return d


def autosave_path() -> Path:
    return app_data_dir() / "autoguardado.eia"


def session_lock_path() -> Path:
    """Existe mientras el programa está abierto. Si sigue ahí al arrancar, hubo un cierre inesperado."""
    return app_data_dir() / "sesion_abierta.lock"


def log_path() -> Path:
    d = app_data_dir() / "registros"
    d.mkdir(parents=True, exist_ok=True)
    return d / "errores.log"
