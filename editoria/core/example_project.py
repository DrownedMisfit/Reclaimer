"""
🎓 Proyecto de ejemplo: un proyecto genérico de YouTube para aprender Reclaimer sin usar material propio.

  · la narración (voz sintética de Kokoro, licencia Apache 2.0) viene con el programa: assets/ejemplo/narracion.m4a,
    con pausas largas a propósito para probar «✂ Eliminar silencios»;
  · los clips son de Pexels (uso gratis; su licencia no deja redistribuirlos tal cual, por eso NO van en el programa):
    se descargan de Pexels al crear el ejemplo, con sus créditos al lado («<clip>.creditos.json» → descripción y
    exportación, ver core/credits.py);
  · la música la genera FFmpeg aquí mismo (propia: sin derechos de nadie), con un drop a los 16 s para probar 🥁.

  build(dest, progress, cancelled)  -> (ruta del .eia, [fallos]); lo ya descargado no se vuelve a bajar
  repair(dest, progress, cancelled) -> [fallos]: repone lo que falte SIN tocar el .eia (lo que practicaste se queda)
  missing(dest)                     -> ¿falta algún archivo del ejemplo?
  CLIPS                            -> los clips de Pexels con su autor y su página
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request

from ..ai.base import Cancelled

from . import media as M
from .model import (KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, MediaItem, Project, Track, new_id)

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ejemplo")
NARRACION = os.path.join(ASSETS, "narracion.m4a")
NOMBRE = "Proyecto de ejemplo"

_PX = "https://videos.pexels.com/video-files/"
# Clips de Pexels (720p, ~15 MB en total): archivo local, enlace directo, página, título y autor
CLIPS: list[dict] = [
    {"file": "mando en las manos.mp4", "url": _PX + "6739005/6739005-hd_1280_720_24fps.mp4",
     "page": "https://www.pexels.com/video/a-person-holding-a-wireless-game-controller-6739005/",
     "title": "A Person Holding a Wireless Game Controller", "author": "Joshua Malic",
     "author_url": "https://www.pexels.com/@joshua-malic-25131152/"},
    {"file": "escritorio gamer.mp4", "url": _PX + "7914785/7914785-hd_1280_720_30fps.mp4",
     "page": "https://www.pexels.com/video/a-coffee-cup-in-the-gaming-computer-desk-7914785/",
     "title": "A Coffee Cup in the Gaming Computer Desk", "author": "RDNE Stock project",
     "author_url": "https://www.pexels.com/@rdne/"},
    {"file": "jugando en el PC.mp4", "url": _PX + "7914936/7914936-hd_1280_720_30fps.mp4",
     "page": "https://www.pexels.com/video/man-playing-a-video-game-on-a-pc-7914936/",
     "title": "A Man Playing a Video Game on a PC", "author": "RDNE Stock project",
     "author_url": "https://www.pexels.com/@rdne/"},
    {"file": "persona con mando.mp4", "url": _PX + "8127818/8127818-hd_1280_720_25fps.mp4",
     "page": "https://www.pexels.com/video/person-holding-a-game-controller-8127818/",
     "title": "Person Holding a Game Controller", "author": "Alena Darmel",
     "author_url": "https://www.pexels.com/@a-darmel/"},
    {"file": "editando video.mp4", "url": _PX + "1536323/1536323-hd_1280_720_30fps.mp4",
     "page": "https://www.pexels.com/video/person-editing-a-video-1536323/",
     "title": "Person Editing A Video", "author": "Nino Souza", "author_url": "https://www.pexels.com/@ninosouza/"},
]

# 117 golpes por minuto: bombo, charles a contratiempo y, desde los 16 s, bajo y bombo fuerte (el «drop»)
_MUSICA = ("0.9*sin(2*PI*(45+90*exp(-25*mod(t,0.5)))*mod(t,0.5))*exp(-7*mod(t,0.5))*if(lt(t,16),0.35,1)"
           "+0.22*(random(0)*2-1)*exp(-55*mod(t+0.25,0.5))"
           "+if(gte(t,16),0.18*sin(2*PI*55*t)*exp(-3*mod(t,0.5)),0)"
           "+0.06*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*0.25*t))")
SEG_POR_CLIP = 6.0


Cancelado = Cancelled            # (BackgroundJob la reconoce: cancelar no es un error)


def _es_video(ruta: str) -> bool:
    """¿Es un mp4/mov de verdad? (una página HTML o un trozo cortado no: no se dan por buenos)"""
    try:
        with open(ruta, "rb") as f:
            cab = f.read(12)
    except OSError:
        return False
    return len(cab) >= 8 and cab[4:8] == b"ftyp"


def _bajar(url: str, destino: str, avisar, cancelled) -> None:
    """Descarga a «.part» y renombra al final: si se corta, se cancela o no es un video, no queda nada."""
    tmp = destino + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Reclaimer)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            hecho = 0
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                trozo = r.read(256 * 1024)
                if not trozo:
                    break
                f.write(trozo)
                hecho += len(trozo)
                if total:
                    avisar(hecho / total)
        if total and hecho != total:
            raise RuntimeError(f"la descarga se cortó ({hecho // 1024} de {total // 1024} KB)")
        if not _es_video(tmp):
            raise RuntimeError("lo descargado no es un video (¿una página de inicio de sesión del wifi?)")
        os.replace(tmp, destino)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _musica(destino: str) -> None:
    r = M.run_quiet([M.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"aevalsrc=exprs='{_MUSICA}':s=44100:d=45",
                     "-af", "volume=0.9,afade=t=out:st=42:d=3", "-ac", "2", "-c:a", "aac", "-b:a", "128k", destino],
                    timeout=120)
    if r.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError("no pude crear la música de ejemplo: " + r.stderr.decode(errors="replace")[-200:])


def _medio(path: str, kind: str) -> MediaItem:
    info = M.probe(path)
    return MediaItem(id=new_id(), path=path, kind=kind, name=os.path.basename(path), duration=info["duration"],
                     width=info["width"], height=info["height"], fps=info["fps"], has_audio=info["has_audio"],
                     channels=info["channels"], probed=True)


def _rutas(dest: str) -> tuple[str, str]:
    return os.path.join(dest, "narración de ejemplo.m4a"), os.path.join(dest, "música de ejemplo.m4a")


def missing(dest: str) -> bool:
    narr, musica = _rutas(dest)
    return not all(os.path.isfile(r) for r in [narr, musica] + [os.path.join(dest, c["file"]) for c in CLIPS])


def _preparar(dest: str, avisar, cancelled) -> tuple[str, str, list[MediaItem], list[str]]:
    """Narración, música y clips en «dest» (repone lo que falte o esté dañado). Devuelve sus medios y los fallos."""
    os.makedirs(dest, exist_ok=True)
    narr, musica = _rutas(dest)
    if not os.path.isfile(narr):
        if not os.path.isfile(NARRACION):
            raise RuntimeError("Falta la narración de ejemplo del programa (editoria/assets/ejemplo/narracion.m4a). "
                               "Vuelve a descargar Reclaimer completo.")
        shutil.copyfile(NARRACION, narr)
    if not os.path.isfile(musica):
        avisar(0.02, "Creando la música…")
        _musica(musica)
    videos: list[MediaItem] = []
    fallos: list[str] = []
    for i, c in enumerate(CLIPS):
        ruta = os.path.join(dest, c["file"])
        cred = os.path.splitext(ruta)[0] + ".creditos.json"
        mv = None
        for intento in (0, 1):                     # (uno dañado de antes: se borra y se baja otra vez)
            if not os.path.isfile(ruta):
                base, n = 0.05 + 0.9 * i / max(1, len(CLIPS)), 0.9 / max(1, len(CLIPS))
                try:
                    _bajar(c["url"], ruta, lambda f, b=base, n=n, t=c["title"]: avisar(b + n * f, f"Descargando «{t}»…"),
                           cancelled)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - sin internet o enlace caído: el ejemplo sale sin ese clip
                    fallos.append(f"{c['title']}: {exc}")
                    break
            try:
                mv = _medio(ruta, KIND_VIDEO) if _es_video(ruta) else None
            except Exception:  # noqa: BLE001
                mv = None
            if mv is not None and mv.duration > 1.0:
                break
            mv = None
            for r in (ruta, cred):
                try:
                    os.remove(r)
                except OSError:
                    pass
            if intento:
                fallos.append(f"{c['title']}: el archivo descargado está dañado")
        if mv is None:
            continue
        with open(cred, "w", encoding="utf-8") as f:
            json.dump({"title": c["title"], "channel": f"{c['author']} (Pexels)", "channel_url": c.get("author_url", ""),
                       "url": c["page"], "term": "proyecto de ejemplo", "audio": False}, f, ensure_ascii=False, indent=1)
        videos.append(mv)
    nota = os.path.join(dest, "no descargados.txt")
    if fallos:
        with open(nota, "w", encoding="utf-8") as f:
            f.write("\n".join(fallos) + "\n")
    elif os.path.isfile(nota):
        os.remove(nota)
    return narr, musica, videos, fallos


def repair(dest: str, progress=None, cancelled=None) -> list[str]:
    """Repone narración, música y clips que falten, sin reescribir el .eia (lo que hiciste en el ejemplo se queda)."""
    avisar = progress or (lambda _f, _t="": None)
    fallos = _preparar(dest, avisar, cancelled)[3]
    avisar(1.0, "Listo")
    return fallos


def build(dest: str, progress=None, cancelled=None) -> tuple[str, list[str]]:
    """Crea (o completa) el proyecto de ejemplo en «dest»: (ruta de su .eia, clips que no se pudieron bajar)."""
    avisar = progress or (lambda _f, _t="": None)
    narr, musica, mvs, fallos = _preparar(dest, avisar, cancelled)
    if CLIPS and not mvs:
        raise RuntimeError("No pude descargar los clips de Pexels (¿sin internet?).\n" + "\n".join(fallos[:3]))
    avisar(0.96, "Montando el proyecto…")

    p = Project.new()
    p.name, p.fps, p.width, p.height = NOMBRE, 30.0, 1920, 1080
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO and t.name == "V1")
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    a1.role = "voz"
    a2 = Track(new_id(), TRACK_AUDIO, "A2", role="musica", duck_db=-12.0)
    p.tracks.append(a2)
    mn = _medio(narr, KIND_AUDIO)
    mm = _medio(musica, KIND_AUDIO)
    p.media[mn.id], p.media[mm.id] = mn, mm
    for cl in (Clip(new_id(), mn.id, a1.id, 0.0, 0.0, mn.duration),
               Clip(new_id(), mm.id, a2.id, 0.0, 0.0, min(mm.duration, mn.duration + 1.0), volume=0.35)):
        p.clips[cl.id] = cl
    for mv in mvs:
        p.media[mv.id] = mv
    t, k = 0.0, 0
    while mvs and t < mn.duration - 0.05:          # los clips seguidos (y otra vez desde el primero) hasta el final
        mv = mvs[k % len(mvs)]
        vuelta = k // len(mvs)
        ini = min(vuelta * SEG_POR_CLIP, max(0.0, mv.duration - SEG_POR_CLIP))
        dur = min(SEG_POR_CLIP, mv.duration - ini, mn.duration - t)
        if dur > 0.2:
            cl = Clip(new_id(), mv.id, v1.id, round(t, 3), round(ini, 3), round(dur, 3), volume=0.0)
            p.clips[cl.id] = cl
            t += dur
        k += 1
        if k > 200:
            break
    ruta = os.path.join(dest, NOMBRE + ".eia")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p.to_dict(), f, ensure_ascii=False)
    os.replace(tmp, ruta)
    avisar(1.0, "Listo")
    return ruta, fallos
