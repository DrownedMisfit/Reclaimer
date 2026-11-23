"""
🎙 «Edita desde tu voz» — la parte sin ventanas (23/11, plan notas_claude/PLAN_EDITA_DESDE_TU_VOZ.md).

Paso 1 «Tu voz»: de dónde sale la grabación y cómo se prepara antes de colocarla.
  · carpeta_obs(): la carpeta de grabaciones de OBS (perfil en uso; formato de siempre y el de OBS 31, user.ini).
  · carpeta_inicial(ultima, videos): OBS → la última usada → Vídeos.
  · recientes(carpeta): las grabaciones de esa carpeta, la más reciente primero.
  · ordenar_partes(rutas): varias partes de una voz, en orden por nombre (con números naturales) y fecha.
  · en_nube(ruta) / en_red(ruta) / copiar_a_cache(ruta): OneDrive sin bajar o una unidad de red → copia en la caché.
  · necesita_convertir(ruta) / convertir(ruta): formato que Reclaimer no abre → una copia en la caché, sin preguntar.
  · elegir_pista(ruta): qué pista de audio es la voz (OBS: la 2; si duda, quien llama deja escuchar cada una).
  · extraer_pista(ruta, k): esa pista sola, en la caché (copia exacta si es AAC).
  · mezclada(ruta, k): ¿la voz va mezclada con el juego o la música? (para ofrecer separarla).
  · ya_editada(proyecto, media_id, ruta): voz ya editada o clip compuesto → se salta «Pule tu voz».

Estado por proyecto (Project.edita_voz, se guarda con el proyecto; NO va al deshacer): ver estado()/progreso().
La transcripción temprana guarda lo hecho por archivo (cache_transcripcion), así cambiar de pestaña o cerrar a medias
no pierde nada y al volver sigue desde donde iba.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess

from . import media as media_tools
from .model import AUDIO_EXT, VIDEO_EXT, kind_for_path
from .paths import cache_dir

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASOS = 3
NOMBRES_PASO = {1: "Tu voz", 2: "Pule tu voz", 3: "Arma tu video"}
EXT_GRABACION = VIDEO_EXT | AUDIO_EXT
CODECS_AUDIO_OK = {"aac", "mp3", "flac", "opus", "vorbis", "alac", "ac3", "eac3", "wmav2", "mp2"}


# ------------------------------------------------------------------ estado del proyecto
def estado(proyecto) -> dict:
    """El estado de «Edita desde tu voz» de ese proyecto (se crea vacío): {"paso": 1–3, "voz": [rutas de la voz],
    "origen": [rutas elegidas], "modo": "voz"|"imagen", "saltar_pule": bool, "trans": {ruta: fracción hecha},
    "usado": bool}."""
    ev = getattr(proyecto, "edita_voz", None)
    if not isinstance(ev, dict):
        ev = {}
        try:
            proyecto.edita_voz = ev
        except AttributeError:
            pass
    ev.setdefault("paso", 1)
    return ev


def progreso(proyecto, duraciones: dict | None = None) -> float:
    """La fracción transcrita de toda la voz (0–1), ponderada por la duración de cada parte si se sabe."""
    ev = estado(proyecto)
    tr = ev.get("trans") or {}
    voz = ev.get("voz") or []
    if not voz:
        return 0.0
    pesos = [max(0.001, float((duraciones or {}).get(r, 1.0))) for r in voz]
    return sum(float(tr.get(r, 0.0)) * w for r, w in zip(voz, pesos)) / sum(pesos)


def texto_boton(proyecto, trabajando: bool = False, frac: float | None = None) -> str:
    """«Edita desde tu voz» o, con algo empezado, «Paso 2 de 3 · 40 %»."""
    ev = estado(proyecto)
    if not ev.get("voz"):
        return "Edita desde tu voz"
    paso = int(ev.get("paso", 1))
    f = progreso(proyecto) if frac is None else frac
    if f < 0.999 or trabajando:
        return f"Paso {paso} de {PASOS} · {int(round(f * 100))} %"
    return f"Paso {paso} de {PASOS}"


# ------------------------------------------------------------------ OBS y carpetas
def _ini(ruta: str) -> configparser.ConfigParser | None:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        with open(ruta, encoding="utf-8-sig", errors="replace") as f:
            cp.read_file(f)
    except (OSError, configparser.Error):
        return None
    return cp


def _val(cp, sec: str, clave: str) -> str:
    try:
        return (cp.get(sec, clave, fallback="") or "").strip()
    except configparser.Error:
        return ""


def _ruta_grabacion(basic: str) -> str:
    """La carpeta de grabación de un basic.ini (modo Sencillo o Avanzado, el que esté en uso)."""
    cp = _ini(basic)
    if cp is None:
        return ""
    modo = _val(cp, "Output", "Mode").lower()
    simple = _val(cp, "SimpleOutput", "FilePath")
    avanzada = _val(cp, "AdvOut", "RecFilePath") or _val(cp, "AdvOut", "FFFilePath")
    orden = [avanzada, simple] if modo == "advanced" else [simple, avanzada]
    for r in orden:
        if r:
            r = os.path.normpath(os.path.expandvars(r))
            if os.path.isdir(r):
                return r
    return ""


def carpeta_obs(appdata: str | None = None) -> str:
    """La carpeta de grabaciones de OBS ('' si no hay OBS o no se encuentra). Primero el perfil en uso (user.ini de
    OBS 31 o global.ini de antes, [Basic] ProfileDir / Profile); si no, el perfil tocado más recientemente."""
    base = os.path.join(appdata or os.environ.get("APPDATA", ""), "obs-studio")
    perfiles = os.path.join(base, "basic", "profiles")
    if not os.path.isdir(perfiles):
        return ""
    en_uso = ""
    for g in ("user.ini", "global.ini"):
        cp = _ini(os.path.join(base, g))
        if cp is not None:
            en_uso = _val(cp, "Basic", "ProfileDir") or _val(cp, "Basic", "Profile")
            if en_uso:
                break
    if en_uso:
        r = _ruta_grabacion(os.path.join(perfiles, en_uso, "basic.ini"))
        if r:
            return r
    candidatos = []
    try:
        for d in os.listdir(perfiles):
            b = os.path.join(perfiles, d, "basic.ini")
            if os.path.isfile(b):
                candidatos.append((os.path.getmtime(b), b))
    except OSError:
        return ""
    for _t, b in sorted(candidatos, reverse=True):
        r = _ruta_grabacion(b)
        if r:
            return r
    return ""


def carpeta_inicial(ultima: str = "", videos: str = "", appdata: str | None = None) -> tuple[str, str]:
    """(carpeta, de dónde): «obs», «ultima» o «videos»."""
    r = carpeta_obs(appdata)
    if r:
        return r, "obs"
    if ultima and os.path.isdir(ultima):
        return ultima, "ultima"
    v = videos or os.path.join(os.path.expanduser("~"), "Videos")
    return (v if os.path.isdir(v) else os.path.expanduser("~")), "videos"


def recientes(carpeta: str, n: int = 6) -> list[str]:
    """Las grabaciones de la carpeta (video o audio), la más reciente primero."""
    try:
        with os.scandir(carpeta) as it:
            fs = [(e.stat().st_mtime, e.path) for e in it
                  if e.is_file() and os.path.splitext(e.name)[1].lower() in EXT_GRABACION]
    except OSError:
        return []
    return [p for _t, p in sorted(fs, reverse=True)[:n]]


def _clave_natural(ruta: str):
    nombre = os.path.basename(ruta).lower()
    partes = re.split(r"(\d+)", nombre)
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        mt = 0.0
    return [int(x) if x.isdigit() else x for x in partes], mt


def ordenar_partes(rutas: list[str]) -> list[str]:
    """Varias partes de una misma voz: por nombre (parte 2 antes que parte 10) y, a igual nombre, por fecha."""
    return sorted(dict.fromkeys(rutas), key=_clave_natural)


def tamano(ruta: str) -> int:
    try:
        return os.path.getsize(ruta)
    except OSError:
        return -1


# ------------------------------------------------------------------ nube, red, formatos
_ATRIB_NUBE = 0x1000 | 0x40000 | 0x400000      # OFFLINE · RECALL_ON_OPEN · RECALL_ON_DATA_ACCESS (OneDrive sin bajar)


def _atributos(ruta: str) -> int:
    try:
        import ctypes
        a = ctypes.windll.kernel32.GetFileAttributesW(str(ruta))
        return 0 if a == 0xFFFFFFFF else int(a)
    except Exception:  # noqa: BLE001 - fuera de Windows: sin atributos
        return 0


def en_nube(ruta: str) -> bool:
    return bool(_atributos(ruta) & _ATRIB_NUBE)


def en_red(ruta: str) -> bool:
    r = os.path.abspath(ruta)
    if r.startswith("\\\\") or r.startswith("//"):
        return True
    try:
        import ctypes
        raiz = os.path.splitdrive(r)[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(raiz) == 4      # DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False


def _nombre_seguro(ruta: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', " ", os.path.basename(ruta)).strip() or "voz"


def copiar_a_cache(ruta: str, progress=None, cancelled=None) -> str:
    """Una copia local (caché) de un archivo en la nube o en red, por trozos (se puede cancelar). La segunda vez, al
    momento. progress(fracción, texto)."""
    destino_dir = str(cache_dir("voz_copias"))
    destino = os.path.join(destino_dir, f"{media_tools.cache_key(ruta)}_{_nombre_seguro(ruta)}")
    total = max(1, tamano(ruta))
    if os.path.exists(destino) and os.path.getsize(destino) == total:
        return destino
    tmp = destino + ".parcial"
    hecho = 0
    with open(ruta, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            if cancelled is not None and cancelled():
                fo.close()
                os.remove(tmp)
                from ..ai.base import Cancelled
                raise Cancelled()
            b = fi.read(4 << 20)
            if not b:
                break
            fo.write(b)
            hecho += len(b)
            if progress is not None:
                progress(hecho / total, f"Copiando la grabación a tu PC… {hecho * 100 // total} %")
    os.replace(tmp, destino)
    try:
        shutil.copystat(ruta, destino)
    except OSError:
        pass
    return destino


def flujos(ruta: str) -> list[dict]:
    """Los flujos del archivo (ffprobe): [{"codec_type", "codec_name", "channels", "sample_rate", …}]."""
    r = subprocess.run([media_tools.ffprobe(), "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name,channels,sample_rate,avg_frame_rate:"
                        "stream_disposition=attached_pic", "-of", "json", ruta],
                       capture_output=True, text=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    try:
        return json.loads(r.stdout or "{}").get("streams", [])
    except ValueError:
        return []


def tiene_video(fl: list[dict]) -> bool:
    return any(s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic") for s in fl)


def necesita_convertir(ruta: str, fl: list[dict] | None = None) -> bool:
    """Formato que Reclaimer no abre (extensión desconocida) o un códec de audio raro: se convierte en la caché.
    Mono, 44,1 kHz u otro fps NO hacen falta convertirlos: se adaptan solos al proyecto (los tiempos son segundos)."""
    if kind_for_path(ruta) is None:
        return True
    fl = flujos(ruta) if fl is None else fl
    aud = [s for s in fl if s.get("codec_type") == "audio"]
    return bool(aud) and not any(str(s.get("codec_name", "")).startswith("pcm_") or
                                 s.get("codec_name") in CODECS_AUDIO_OK for s in aud)


def convertir(ruta: str, fl: list[dict] | None = None) -> str:
    """Una copia que Reclaimer abre, en la caché: con imagen → MP4 (H.264 + AAC, todas las pistas de audio); sin
    imagen → M4A (AAC). Se guarda: la segunda vez, al momento."""
    fl = flujos(ruta) if fl is None else fl
    con_video = tiene_video(fl)
    base = os.path.splitext(_nombre_seguro(ruta))[0]
    out = os.path.join(str(cache_dir("voz_convertida")),
                       f"{media_tools.cache_key(ruta)}_{base}.{'mp4' if con_video else 'm4a'}")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    tmp = out + (".parcial.mp4" if con_video else ".parcial.m4a")
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", ruta]
    if con_video:
        args += ["-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    else:
        args += ["-map", "0:a", "-vn"]
    args += ["-c:a", "aac", "-b:a", "256k", tmp]
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError("No pude convertir «%s»: %s" % (os.path.basename(ruta),
                                                          r.stderr.decode(errors="replace").strip()[-200:]))
    os.replace(tmp, out)
    return out


# ------------------------------------------------------------------ la pista de la voz
def elegir_pista(ruta: str) -> dict:
    """Qué pista de audio es la voz: {"k": índice entre las de audio, "n": cuántas hay, "seguro": bool,
    "roles": {k: "voz"|"juego"}, "nota": texto}. OBS: la 2 (k=1). Si duda, seguro=False (quien llama deja elegir
    escuchando un trozo de cada una)."""
    from . import obs_tracks
    st = obs_tracks.audio_streams(ruta)
    n = len(st)
    if n == 0:
        return {"k": -1, "n": 0, "seguro": False, "roles": {}, "nota": "no tiene sonido"}
    if n == 1:
        return {"k": 0, "n": 1, "seguro": True, "roles": {0: "voz"}, "nota": ""}
    try:
        info = obs_tracks.classify(ruta)
    except Exception as exc:  # noqa: BLE001 - no se pudo escuchar: se pregunta
        info = {"keep": [], "note": str(exc)}
    roles = {k: r for k, r in info.get("keep", [])}
    voz = [k for k, r in roles.items() if r == "voz"]
    if voz:
        k = voz[0]
        # seguro si coincide con la 2 de OBS, o si es la única que suena (lo demás en silencio o duplicado)
        seguro = k == 1 or len(roles) == 1
        return {"k": k, "n": n, "seguro": seguro, "roles": roles, "nota": info.get("note", "")}
    return {"k": 1, "n": n, "seguro": False, "roles": roles, "nota": info.get("note", "")}


def extraer_pista(ruta: str, k: int) -> str:
    """La pista de audio k sola, en la caché (copia exacta si es AAC). Se guarda: la segunda vez, al momento."""
    from . import obs_tracks
    st = obs_tracks.audio_streams(ruta)
    codec = (st[k].get("codec_name") or "") if 0 <= k < len(st) else ""
    base = os.path.splitext(_nombre_seguro(ruta))[0]
    out = os.path.join(str(cache_dir("voz_pistas")), f"{media_tools.cache_key(ruta)}_{base} · pista {k + 1}.m4a")
    if os.path.exists(out) and os.path.getsize(out) > 200:
        return out
    tmp = out[:-4] + ".parcial.m4a"
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", ruta, "-map", f"0:a:{k}", "-vn"]
    args += ["-c:a", "copy"] if codec == "aac" else ["-c:a", "aac", "-b:a", "256k"]
    r = subprocess.run(args + [tmp], capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(f"No pude sacar la pista {k + 1}: " + r.stderr.decode(errors="replace").strip()[-200:])
    os.replace(tmp, out)
    return out


def trozo_pista(ruta: str, k: int, desde: float = 30.0, dura: float = 6.0) -> str:
    """Un trozo corto de la pista k (para escucharla al elegir), en la caché."""
    base = f"{media_tools.cache_key(ruta)}_k{k}_{int(desde)}.wav"
    out = os.path.join(str(cache_dir("voz_trozos")), base)
    if os.path.exists(out):
        return out
    r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{desde:.2f}", "-t",
                        f"{dura:.2f}", "-i", ruta, "-map", f"0:a:{k}", "-vn", "-ac", "2", "-ar", "48000", out],
                       capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0 and desde > 0:
        return trozo_pista(ruta, k, 0.0, dura)
    return out


def mezclada(ruta: str, k: int = 0) -> bool:
    """¿La voz va mezclada con el juego o la música? Una voz sola es casi mono (izquierda = derecha) y con la energía
    en las frecuencias de la voz; el juego o la música, estéreo y con todo tipo de sonidos."""
    from . import obs_tracks
    import numpy as np
    try:
        a = obs_tracks._pcm(ruta, k)
    except Exception:  # noqa: BLE001
        return False
    if len(a) < obs_tracks.SR * 2:
        return False
    a = a[: obs_tracks.SR * 120]
    if float(np.abs(a).max()) < 1e-3:
        return False
    lr = obs_tracks._corr(a[:, 0], a[:, 1])
    voz = obs_tracks._voice_ratio(a.mean(axis=1))
    return (lr < 0.9 and voz < 0.62) or voz < 0.42


PALABRAS_EDITADA = re.compile(r"(editad|final|export|montaje|render)", re.I)


def ya_editada(proyecto, media_id: str | None, ruta: str) -> bool:
    """Una voz ya editada (un clip compuesto, o un archivo que se llama «… editado / final / export…») se salta
    «Pule tu voz»."""
    if media_id and media_id in (getattr(proyecto, "compounds", None) or {}):
        return True
    return bool(PALABRAS_EDITADA.search(os.path.splitext(os.path.basename(ruta))[0]))


# ------------------------------------------------------------------ transcripción por archivo (caché)
def _f_trans(ruta: str) -> str:
    return os.path.join(str(cache_dir("voz_transcripcion")), f"{media_tools.cache_key(ruta)}.json")


def cache_transcripcion(ruta: str) -> dict | None:
    """Lo transcrito de ese archivo hasta ahora (con «hasta» si va a medias) o None."""
    try:
        with open(_f_trans(ruta), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("words") is not None else None
    except (OSError, ValueError):
        return None


def guardar_transcripcion(ruta: str, tr: dict) -> None:
    f = _f_trans(ruta)
    tmp = f + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fo:
            json.dump(tr, fo, ensure_ascii=False)
        os.replace(tmp, f)
    except OSError:
        pass
