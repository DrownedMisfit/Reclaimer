"""
😂 Biblioteca de MEMES: tus videos, imágenes y sonidos cortos para reutilizar en TODOS tus proyectos.

Viven en su carpeta propia (datos\\memes, la misma para todos los proyectos), con un índice «memes.json»:
  {"id", "archivo", "nombre", "etiquetas": [...], "duracion", "audio", "tipo": video|image|audio, "origen", "fecha"}

  carpeta()                                  la carpeta (se crea)
  listar() / buscar(texto, tipo, audio)      los memes (los que perdieron su archivo no salen; un archivo suelto
                                             de la carpeta se adopta; un índice roto se aparta y se rehace)
  agregar_archivo(ruta, …)                   copia un archivo entero (sin su audio si audio=False)
  agregar_tramo(ruta, desde, dur, …)         guarda SOLO un tramo de un video o sonido (FFmpeg)
                                             (a su velocidad, al revés, solo su audio; velocidad 0 = fotograma)
  renombrar / etiquetar / quitar             (quitar = a la Papelera con la función que se le pase)
  es_meme(ruta) · al_cambiar(fn)             ¿es de la biblioteca? · avisar a quien la enseña (Medios, el panel)
Nada aquí usa ventanas (corre también en segundo plano).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid

from .model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, kind_for_path
from .paths import app_data_dir

INDICE = "memes.json"
CATEGORIA = "😂 Memes"            # (en Medios: siempre al final)
_lock = threading.Lock()
_AVISOS: list = []


def carpeta() -> str:
    d = os.path.join(str(app_data_dir()), "memes")
    os.makedirs(d, exist_ok=True)
    return d


def _ruta_indice() -> str:
    return os.path.join(carpeta(), INDICE)


_EN_CURSO: set = set()      # nombres de archivo reservados por un «Agregar» que aún está trabajando


def _entrada_de_archivo(archivo: str) -> dict:
    """Una entrada nueva para un archivo de la carpeta que no estaba en el índice (índice roto o archivo suelto)."""
    ruta = os.path.join(carpeta(), archivo)
    tipo = kind_for_path(ruta) or KIND_VIDEO
    try:
        fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(ruta)))
    except OSError:
        fecha = time.strftime("%Y-%m-%d %H:%M:%S")
    return {"id": uuid.uuid4().hex[:12], "archivo": archivo, "nombre": os.path.splitext(archivo)[0][:80],
            "etiquetas": [], "duracion": 0.0 if tipo == KIND_IMAGE else round(_duracion(ruta), 3),
            "audio": tipo == KIND_AUDIO or (tipo == KIND_VIDEO and _tiene_audio(ruta)), "tipo": tipo,
            "origen": "", "fecha": fecha}


def _sueltos(lista: list[dict]) -> list[str]:
    """Archivos de la carpeta (videos, imágenes, sonidos) que el índice no tiene."""
    tienen = {m.get("archivo") for m in lista}
    try:
        nombres = os.listdir(carpeta())
    except OSError:
        return []
    return [f for f in nombres if f not in tienen and f not in _EN_CURSO and ".part" not in f
            and kind_for_path(f) and os.path.getsize(os.path.join(carpeta(), f)) > 0]


def _leer() -> list[dict]:
    """El índice. Si está roto (no se puede leer), se guarda aparte como «memes.json.roto-<fecha>» y se rehace con
    los archivos de la carpeta: nunca se pierden memes."""
    ruta = _ruta_indice()
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, list):
            raise ValueError("no es una lista")
        return [d for d in datos if isinstance(d, dict) and d.get("archivo")]
    except (OSError, ValueError):
        try:
            os.replace(ruta, ruta + ".roto-" + time.strftime("%Y%m%d-%H%M%S"))
        except OSError:
            pass
        lista = [_entrada_de_archivo(f) for f in _sueltos([])]
        try:
            _guardar(lista)
        except OSError:
            pass
        return lista


def _guardar(lista: list[dict]) -> None:
    tmp = _ruta_indice() + f".{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())                 # (en el disco de verdad antes de sustituir el índice)
    os.replace(tmp, _ruta_indice())


def al_cambiar(fn) -> None:
    """fn() se llama cada vez que la biblioteca cambia (añadir, renombrar, quitar)."""
    if fn not in _AVISOS:
        _AVISOS.append(fn)


def _avisar() -> None:
    for fn in list(_AVISOS):
        try:
            fn()
        except Exception:  # noqa: BLE001 - quien escucha (una ventana cerrada…) nunca rompe la biblioteca
            try:
                _AVISOS.remove(fn)
            except ValueError:
                pass


def ruta_de(m: dict) -> str:
    return os.path.join(carpeta(), m["archivo"])


def listar() -> list[dict]:
    """Los memes cuyo archivo sigue ahí, los más nuevos primero (con «ruta»). Un archivo de la carpeta sin entrada se
    adopta (se le crea la suya)."""
    with _lock:
        lista = _leer()
        sueltos = _sueltos(lista)
        if sueltos:
            lista += [_entrada_de_archivo(f) for f in sueltos]
            _guardar(lista)
    out = []
    for m in lista:
        r = ruta_de(m)
        if os.path.isfile(r):
            out.append(dict(m, ruta=r))
    out.sort(key=lambda m: m.get("fecha", ""), reverse=True)
    return out


def _norm(t: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(t or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def buscar(texto: str = "", tipo: str | None = None, audio: bool | None = None) -> list[dict]:
    """Por nombre o etiqueta (sin tildes ni mayúsculas); tipo = video|image|audio; audio = con / sin."""
    q = _norm(texto).strip()
    out = []
    for m in listar():
        if tipo and m.get("tipo") != tipo:
            continue
        if audio is not None and bool(m.get("audio")) != audio:
            continue
        if q and not all(p in _norm(m.get("nombre", "") + " " + " ".join(m.get("etiquetas") or []))
                         for p in q.split()):
            continue
        out.append(m)
    return out


def es_meme(ruta: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(ruta)),
                                   os.path.normcase(carpeta())]) == os.path.normcase(carpeta())
    except ValueError:
        return False


def _reservar(nombre: str, ext: str) -> str:
    """Un nombre de archivo libre, RESERVADO mientras se trabaja (dos «Agregar» a la vez no chocan)."""
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", nombre or "meme").strip(" .")[:60] or "meme"
    with _lock:
        destino = f"{base}{ext}"
        n = 2
        while os.path.exists(os.path.join(carpeta(), destino)) or destino in _EN_CURSO:
            destino = f"{base} ({n}){ext}"
            n += 1
        _EN_CURSO.add(destino)
    return destino


def _liberar(archivo: str) -> None:
    with _lock:
        _EN_CURSO.discard(archivo)


def _temporal(archivo: str) -> str:
    base, ext = os.path.splitext(archivo)
    return os.path.join(carpeta(), f"{base}.{uuid.uuid4().hex[:8]}.part{ext}")


def _ffmpeg(args: list[str], salida: str, cancelado=None, timeout: float = 900.0) -> None:
    """FFmpeg que se puede cancelar (sondea cancelado(); si se cancela, lo mata y borra lo a medias)."""
    import subprocess
    from . import media as MEDIA
    proc = subprocess.Popen([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y"] + args + [salida],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    fin = time.monotonic() + timeout
    while proc.poll() is None:
        if (cancelado is not None and cancelado()) or time.monotonic() > fin:
            proc.kill()
            proc.wait()
            try:
                os.remove(salida)
            except OSError:
                pass
            from ..ai.base import Cancelled
            raise Cancelled()
        time.sleep(0.05)
    err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.returncode != 0 or not os.path.isfile(salida):
        try:
            os.remove(salida)
        except OSError:
            pass
        raise RuntimeError(err[-300:] or "FFmpeg falló")


def _atempo(v: float) -> str:
    """atempo solo acepta 0,5–2 por paso: se encadenan."""
    pasos = []
    while v > 2.0:
        pasos.append("atempo=2.0")
        v /= 2.0
    while v < 0.5:
        pasos.append("atempo=0.5")
        v /= 0.5
    pasos.append(f"atempo={v:.4f}")
    return ",".join(pasos)


def _etiquetas(etiquetas) -> list[str]:
    if isinstance(etiquetas, str):
        etiquetas = re.split(r"[,;#]+", etiquetas)
    return [e.strip() for e in (etiquetas or []) if e and e.strip()][:20]


def _duracion(ruta: str) -> float:
    try:
        from . import media as MEDIA
        return float(MEDIA.probe(ruta).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _tiene_audio(ruta: str) -> bool:
    try:
        from . import media as MEDIA
        return bool(MEDIA.probe(ruta).get("has_audio"))
    except Exception:  # noqa: BLE001
        return False


def _registrar(archivo: str, nombre: str, etiquetas, origen: str) -> dict:
    ruta = os.path.join(carpeta(), archivo)
    tipo = kind_for_path(ruta) or KIND_VIDEO
    m = {"id": uuid.uuid4().hex[:12], "archivo": archivo, "nombre": (nombre or os.path.splitext(archivo)[0])[:80],
         "etiquetas": _etiquetas(etiquetas), "duracion": 0.0 if tipo == KIND_IMAGE else round(_duracion(ruta), 3),
         "audio": tipo == KIND_AUDIO or (tipo == KIND_VIDEO and _tiene_audio(ruta)), "tipo": tipo,
         "origen": str(origen or "")[:300], "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
    with _lock:
        # (fuera las entradas viejas de ESTE archivo y las que perdieron el suyo: nunca dos memes con un archivo)
        lista = [x for x in _leer() if x.get("archivo") != archivo
                 and os.path.isfile(os.path.join(carpeta(), x.get("archivo", "")))]
        lista.append(m)
        _guardar(lista)
        _EN_CURSO.discard(archivo)
    _avisar()
    return dict(m, ruta=ruta)


def agregar_archivo(ruta: str, nombre: str = "", etiquetas=None, audio: bool = True, origen: str = "",
                    cancelado=None) -> dict:
    """Copia el archivo ENTERO a la biblioteca (un video sin audio, si audio=False: sin recodificar)."""
    if not os.path.isfile(ruta):
        raise FileNotFoundError(ruta)
    tipo = kind_for_path(ruta)
    if not tipo:
        raise ValueError("Solo videos, imágenes o sonidos.")
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    ext = os.path.splitext(ruta)[1].lower() or ".mp4"
    archivo = _reservar(nombre, ext)
    destino = os.path.join(carpeta(), archivo)
    tmp = _temporal(archivo)
    try:
        if tipo == KIND_VIDEO and not audio:
            _ffmpeg(["-i", ruta, "-map", "0:v:0?", "-c", "copy", "-an"], tmp, cancelado)
        else:
            shutil.copyfile(ruta, tmp)
        os.replace(tmp, destino)
    except BaseException:
        _liberar(archivo)
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return _registrar(archivo, nombre, etiquetas, origen or ruta)


def agregar_fotograma(ruta: str, t: float, nombre: str = "", etiquetas=None, origen: str = "",
                      cancelado=None) -> dict:
    """Un clip congelado (velocidad 0): su fotograma, como imagen."""
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    archivo = _reservar(nombre, ".png")
    destino = os.path.join(carpeta(), archivo)
    tmp = _temporal(archivo)
    try:
        _ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", ruta, "-frames:v", "1"], tmp, cancelado)
        os.replace(tmp, destino)
    except BaseException:
        _liberar(archivo)
        raise
    return _registrar(archivo, nombre, etiquetas, origen or ruta)


def agregar_tramo(ruta: str, desde: float, dur: float, nombre: str = "", etiquetas=None, audio: bool = True,
                  origen: str = "", velocidad: float = 1.0, reversa: bool = False, solo_audio: bool = False,
                  cancelado=None) -> dict:
    """Guarda SOLO el tramo [desde, desde+dur] (segundos DEL ARCHIVO) de un video o sonido, como se ve en la línea de
    tiempo: a su velocidad y, si va al revés, al revés. solo_audio: solo su sonido (la parte de audio de un video).
    Una imagen se copia entera; velocidad 0 (congelado) = su fotograma como imagen."""
    tipo = kind_for_path(ruta)
    if tipo == KIND_IMAGE:
        return agregar_archivo(ruta, nombre, etiquetas, True, origen, cancelado)
    if not os.path.isfile(ruta):
        raise FileNotFoundError(ruta)
    if velocidad <= 0:
        return agregar_fotograma(ruta, desde, nombre, etiquetas, origen, cancelado)
    if dur <= 0.04:
        raise ValueError("El tramo es demasiado corto.")
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    vel = float(velocidad)
    a_filt = ",".join(x for x in ("areverse" if reversa else "", _atempo(vel) if abs(vel - 1) > 1e-3 else "") if x)
    if tipo == KIND_AUDIO or solo_audio:
        archivo = _reservar(nombre, ".m4a")
        cod = ["-vn"] + (["-af", a_filt] if a_filt else []) + ["-c:a", "aac", "-b:a", "192k"]
    else:
        archivo = _reservar(nombre, ".mp4")
        v_filt = ",".join(x for x in ("reverse" if reversa else "",
                                     f"setpts=(PTS-STARTPTS)/{vel:.4f}" if abs(vel - 1) > 1e-3 else "") if x)
        cod = ["-map", "0:v:0"] + (["-vf", v_filt] if v_filt else [])
        cod += (["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"] + (["-af", a_filt] if a_filt else [])) \
            if audio else ["-an"]
        cod += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags",
                "+faststart"]
    destino = os.path.join(carpeta(), archivo)
    tmp = _temporal(archivo)
    try:
        _ffmpeg(["-ss", f"{max(0.0, desde):.3f}", "-t", f"{dur:.3f}", "-i", ruta] + cod, tmp, cancelado)
        os.replace(tmp, destino)
    except BaseException:
        _liberar(archivo)
        raise
    return _registrar(archivo, nombre, etiquetas, origen or ruta)


def _cambiar(mid: str, **cambios) -> dict | None:
    with _lock:
        lista = _leer()
        hecho = None
        for m in lista:
            if m.get("id") == mid:
                m.update(cambios)
                hecho = m
        if hecho is not None:
            _guardar(lista)
    if hecho is not None:
        _avisar()
    return hecho


def renombrar(mid: str, nombre: str) -> dict | None:
    nombre = str(nombre or "").strip()[:80]
    return _cambiar(mid, nombre=nombre) if nombre else None


def etiquetar(mid: str, etiquetas) -> dict | None:
    return _cambiar(mid, etiquetas=_etiquetas(etiquetas))


def quitar(mid: str, a_papelera) -> bool:
    """Saca el meme de la biblioteca y manda su archivo a la Papelera (a_papelera(ruta) -> bool). Si el archivo no se
    puede quitar (abierto en otro programa…), el meme se queda y devuelve False."""
    with _lock:
        m = next((x for x in _leer() if x.get("id") == mid), None)
    if m is None:
        return False
    r = ruta_de(m)
    if os.path.exists(r) and not a_papelera(r):          # (sin el cerrojo: a_papelera puede atender la ventana)
        return False
    with _lock:
        _guardar([x for x in _leer() if x.get("id") != mid])
    _avisar()
    return True
