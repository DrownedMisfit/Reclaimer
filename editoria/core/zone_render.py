"""
⧉ Transiciones reales y ⚡ pre-render de zonas pesadas en el visor. El visor enseña un clip por pista y aproxima
algunos efectos: una transición (deslizar, barrido, zoom…) solo se podía ver como un fundido; el grano, el glitch, el
tono cálido/frío, el desenfoque de movimiento y la cámara lenta suave no se veían; y la máscara de la IA, la pantalla
verde, el desenfoque por zonas, los efectos de edit y las capas de ajuste se calculan fotograma a fotograma (lento).
Aquí se renderizan en segundo plano, con el MISMO motor que la exportación, esos tramos (en pequeño, solo imagen y
sin los textos ni los subtítulos, que el visor dibuja encima), en trozos de unos segundos. El visor los pone por
encima de las pistas mientras el cabezal está dentro (y deja de calcular lo de debajo: va fluido).

  zones(p, transitions, heavy) -> [Zone]   los tramos (la clave cambia si cambia algo que se ve)
  heavy_reason(p, c) -> texto o None       por qué un clip es «pesado» para el visor
  render(p, zone, width) -> ruta         lo renderiza (si no estaba ya en la caché)
  cached(zone, width) -> ruta o None     ¿ya está?
La caché vive en datos/cache/zonas (se puede borrar desde Diagnóstico; se rehace sola).
"""
from __future__ import annotations

import bisect
import hashlib
import math
import json
import os
import subprocess
from dataclasses import dataclass

from .model import TRACK_VIDEO, Project

MARGIN = 1.0       # segundos de más a cada lado al renderizar (las transiciones se recortan según el largo de sus clips)
MARGIN_FX = 0.25   # (en un trozo pesado sin transición basta con un poco)
CHUNK = 8.0        # los tramos pesados largos se renderizan en trozos de unos 8 s (lo cercano al cabezal, antes)
FX_MISSING = ("grain", "glitch", "warm", "cold", "motionblur")     # el visor no los enseña
FX_SLOW = ("rgbsplit", "glow", "punchy", "vhs", "duotone")          # el visor los calcula fotograma a fotograma
WIDTH = 960        # lado mayor del render (el visor rara vez es más grande; un 1/4 de los píxeles de 1080p)
VERSION = 2        # (si cambia cómo se renderiza, las claves cambian y la caché vieja no se usa)
NO_KEY_CLIP = ("volume", "vol_kf", "eq", "pan", "locked", "note", "label", "origin", "link")


@dataclass(frozen=True)
class Zone:
    t0: float          # dónde empieza a verse (timeline)
    t1: float
    a: float           # tramo renderizado [a, b] (con margen)
    b: float
    key: str
    why: str = "trans"     # "trans" (transición) | "fx" (efectos pesados)


def heavy_reason(p: Project, c) -> str | None:
    """Por qué el visor no puede enseñar (bien o con fluidez) este clip; None si puede."""
    if c.text is not None or not c.enabled:
        return None
    fx = c.fx or {}
    if c.smooth and c.speed and 0 < c.speed < 0.999:     # (como al exportar: solo la cámara lenta se interpola)
        return "cámara lenta suave"
    for k in FX_MISSING:
        if float(fx.get(k) or 0) > 0:
            return k
    for k in FX_SLOW:
        if float(fx.get(k) or 0) > 0:
            return k
    if fx.get("subject_mask") or fx.get("motion_key") or fx.get("chroma") or fx.get("blur_regions"):
        return "máscara / pantalla verde / zonas"
    return None                                # (una capa de ajuste solo con color: el visor la pinta bien y barata)


START_FX = ("fade_in", "flash", "glitch", "invert", "shake", "roll")   # lo que va «al empezar el clip» (segundos)


def _media_sig(p: Project, ids) -> list:
    out = []
    for mid in sorted(ids):
        m = p.media.get(mid)
        if m is None:
            continue
        extra = [m.width, m.height, m.gen]
        try:
            st = os.stat(m.path)
            out.append([mid, m.path, int(st.st_mtime), st.st_size] + extra)
        except OSError:
            out.append([mid, m.path, 0, 0] + extra)
    return out


def _slice(p: Project, a: float, b: float) -> Project:
    """El tramo [a, b] sin textos ni subtítulos (el visor los dibuja encima) y sin sonido que importe. Los fundidos
    y entradas de un clip cortado por ese lado se quitan (si no, caerían enteros dentro del tramo)."""
    from .project_tools import slice_project
    cortados = {c.id: (c.start < a - 1e-6, c.end > b + 1e-6) for c in p.clips.values()}
    inicio = {c.id: c.start for c in p.clips.values()}
    q = slice_project(p, a, b)
    for c in q.clips.values():
        izq, der = cortados.get(c.id, (False, False))
        if c.fx and (izq or der):
            fx = dict(c.fx)
            if izq:
                # Lo que cuenta desde el inicio del clip sigue donde tocaba (_t0, ver core/effects._tt); los fundidos
                # de entrada ya acabaron (zones() nunca empieza un tramo en mitad de uno)
                fx["_t0"] = round(a - inicio.get(c.id, a), 4)
                for k in ("fade_in", "flash", "enter"):
                    fx.pop(k, None)
            if der:
                for k in ("fade_out", "exit"):
                    fx.pop(k, None)
            c.fx = fx or None
    q.clips = {k: c for k, c in q.clips.items() if c.text is None and
               (q.track(c.track_id) is not None and q.track(c.track_id).kind == TRACK_VIDEO)}
    q.subtitles.enabled = False
    q.markers = []
    return q


def light_copy(p: Project, a: float, b: float) -> Project:
    """⚡ Copia independiente con SOLO lo que se ve en [a, b] (clips de video que tocan el tramo, sus medios y las
    pistas): sin transcripciones ni el resto de clips. Sirve para la clave y para renderizar en otro hilo."""
    import copy as _copy
    r = _copy.copy(p)
    r.__dict__.pop("_lect", None)
    r.__dict__.pop("_lect_rev", None)
    vt = {t.id for t in p.tracks if t.kind == TRACK_VIDEO}
    r.clips = {k: c for k, c in p.clips.items() if c.track_id in vt and c.text is None and c.start < b and c.end > a}
    r.media = {m: p.media[m] for m in {c.media_id for c in r.clips.values()} if m in p.media}
    r.transcripts = {}
    r.markers = []
    return Project.from_dict(r.to_dict())


def zones(p: Project, width: int = WIDTH, transitions: bool = True, heavy: bool = False) -> list[Zone]:
    from . import transitions as TR
    tramos = []                                # [inicio, fin, media transición (0 = efecto pesado)]
    for tr in p.tracks:
        if tr.kind != TRACK_VIDEO or tr.hidden:
            continue
        if transitions:
            for left, right, t in TR.pairs(p, tr.id):
                cut = right.start
                half = float(t["dur"]) / 2
                tramos.append([cut - half, cut + half, half])
        if heavy:
            for c in p.clips_on(tr.id):
                if heavy_reason(p, c):
                    tramos.append([c.start, c.end, 0.0])
    tramos.sort()
    juntos: list[list[float]] = []
    for t0, t1, half in tramos:                # lo que se toca o se solapa: un solo tramo
        if juntos and t0 <= juntos[-1][1] + 0.05:
            juntos[-1][1] = max(juntos[-1][1], t1)
            juntos[-1][2] = max(juntos[-1][2], half)
            juntos[-1][3].append((t0, t1, half))
        else:
            juntos.append([t0, t1, half, [(t0, t1, half)]])
    # Tramos largos (un clip pesado de minutos): trozos de unos CHUNK s, sin cortar nunca dentro de una transición
    fps = float(p.fps or 30.0)
    rej = lambda s: round(round(float(s) * fps) / fps, 6)      # noqa: E731 - a la rejilla de fotogramas del proyecto
    trozos: list[list] = []
    for t0, t1, _half, partes in juntos:
        trans = [(a_, b_, h_) for a_, b_, h_ in partes if h_ > 0]
        x = t0
        while x < t1 - 1e-6:
            y = min(t1, rej(x + CHUNK))
            if t1 - y < CHUNK * 0.35:          # (un resto muy corto va con el trozo anterior)
                y = t1
            for a_, b_, _h in trans:
                if a_ < y < b_:
                    y = b_
            h = max([h_ for a_, b_, h_ in trans if a_ < y and b_ > x], default=0.0)
            fx = any(h_ == 0 and a_ < y and b_ > x for a_, b_, h_ in partes)
            trozos.append([x, y, h, "fx" if fx else "trans"])
            x = y
    from .model import fast_asdict
    vt = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    por_pista = []
    for t in vt:                               # ⚡ clips por pista ordenados (una vez): cada tramo busca con bisect
        lst = [c for c in p.clips_on(t.id) if c.text is None]
        por_pista.append(([c.start for c in lst], lst, max((c.duration for c in lst), default=0.0)))
    base = [VERSION, p.width, p.height, p.fps, width, [[t.id, t.hidden, (t.fx or {})] for t in vt]]
    out = []
    for t0, t1, half, why in trozos:
        t0 = max(0.0, t0)
        # (clamp_dur: 0,9 × el clip; con margen corto, una de 3 s salía de 2,25)
        margin = max(MARGIN, 1.3 * half) if half > 0 else MARGIN_FX
        a = max(0.0, math.floor((t0 - margin) * fps + 1e-6) / fps)     # (en la rejilla: sin medio fotograma de más)
        b = t1 + margin
        for starts, lst, maxd in por_pista:     # un clip cortado por «a» en mitad de su fundido/glitch: desde su inicio
            for c in lst[bisect.bisect_left(starts, a - maxd - 1e-6):bisect.bisect_right(starts, a)]:
                d = max((float((c.fx or {}).get(k) or 0) for k in START_FX), default=0.0)
                if c.start < a < c.start + d and a - c.start <= 6.0:
                    a = max(0.0, math.floor(c.start * fps + 1e-6) / fps)
        clips, medios = [], set()
        for starts, lst, maxd in por_pista:
            k0 = bisect.bisect_left(starts, a - maxd - 1e-6)
            for c in lst[k0:bisect.bisect_right(starts, b)]:
                if c.end <= a or c.start >= b:
                    continue
                d = {k: v for k, v in fast_asdict(c).items() if k not in NO_KEY_CLIP}   # (lo que no se ve, fuera)
                d["start"] = round(c.start - a, 4)        # (relativo al tramo: un ripple no obliga a renderizar)
                clips.append(d)
                medios.add(c.media_id)
        sig = json.dumps([base, clips, _media_sig(p, medios), round(b - a, 4),
                          {m: p.compounds[m] for m in medios if m in p.compounds}], sort_keys=True, default=str)
        out.append(Zone(round(t0, 4), round(t1, 4), round(a, 4), round(b, 4),
                        hashlib.md5(sig.encode("utf-8")).hexdigest()[:16], why))
    return out


def path_for(zone: Zone) -> str:
    from .paths import cache_dir
    return os.path.join(str(cache_dir("zonas")), f"zona_{zone.key}.mp4")


def cached(zone: Zone) -> str | None:
    p = path_for(zone)
    return p if os.path.exists(p) else None


def render(p: Project, zone: Zone, width: int = WIDTH, cancelled=None) -> str:
    """Renderiza el tramo (solo imagen, prioridad baja: no molesta mientras editas). Devuelve la ruta."""
    out = path_for(zone)
    if os.path.exists(out):
        return out
    from ..export.ffmpeg_export import ExportOptions, build_command
    from . import media as media_tools
    q = _slice(p, zone.a, zone.b)
    s = width / max(p.width, p.height, 1)                # (el lado MAYOR mide «width»: en vertical, igual de ligero)
    width = max(2, int(round(p.width * s / 2)) * 2)
    h = max(2, int(round(p.height * s / 2)) * 2)
    tmp = out[:-4] + ".tmp.mp4"
    opts = ExportOptions(path=tmp, width=width, height=h, fps=p.fps, encoder="cpu", bitrate_mbps=4,
                         subtitles=False, loudnorm=False, video_only=True, low_priority=True,
                         duration=round(zone.b - zone.a, 4))
    args, _total = build_command(q, opts, media_tools.ffmpeg(), out[:-4] + "_filtro.txt")
    log_path = out[:-4] + "_log.txt"
    log = open(log_path, "wb")                 # (a un archivo: una tubería llena dejaría a FFmpeg esperando)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log, stdin=subprocess.DEVNULL,
                            creationflags=flags)     # (prioridad baja: editar y reproducir van antes)
    try:
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancelled is not None and cancelled():
                    proc.kill()
                    proc.wait()
                    raise RuntimeError("Cancelado.")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
        try:
            with open(log_path, "rb") as f:
                err = f.read()[-2000:].decode("utf-8", "replace")
        except OSError:
            err = ""
        for x in (out[:-4] + "_filtro.txt", log_path):
            try:
                os.remove(x)
            except OSError:
                pass
    if proc.returncode != 0 or not os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("No se pudo preparar la transición: " + err.strip()[-200:])
    os.replace(tmp, out)
    return out


def clean(keep: set[str], max_files: int = 400, max_bytes: int = 1500 * 1024 * 1024):
    """Deja la caché con un tope (archivos y tamaño): fuera los más viejos que no se usan ahora."""
    from .paths import cache_dir
    d = str(cache_dir("zonas"))
    try:
        files = []
        for f in os.listdir(d):
            if f.startswith("zona_"):
                st = os.stat(os.path.join(d, f))
                files.append((st.st_mtime, st.st_size, os.path.join(d, f)))
    except OSError:
        return
    files.sort()
    n, total = len(files), sum(sz for _t, sz, _f in files)
    for _t, sz, f in files:
        if n <= max_files and total <= max_bytes:
            break
        if os.path.basename(f) in keep:
            continue
        try:
            os.remove(f)
            n -= 1
            total -= sz
        except OSError:
            pass
