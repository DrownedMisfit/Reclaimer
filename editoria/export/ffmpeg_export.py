"""
Convierte la timeline en un comando de FFmpeg.

Cómo funciona:
  1. Se crea un lienzo negro del tamaño y duración del video.
  2. Cada clip de video/imagen se escala, se coloca en su momento y se superpone
     (las pistas de arriba tapan a las de abajo).
  3. Todos los audios (narración, música, efectos y audio de los clips) se mezclan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO, Project
from ..core import audio_fx, color, curves, effects, equalizer, transform, transitions
from ..core.subtitles import styled_cues
from .ass_subtitles import build_ass

FONTS_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FONT_FILES: dict[str, str] | None = None


def _installed_fonts() -> dict[str, str]:
    """{nombre (en minúsculas): archivo} de las fuentes instaladas (registro de Windows: para todos y solo tuyas)."""
    global _FONT_FILES
    if _FONT_FILES is None:
        _FONT_FILES = {}
        try:
            import winreg
        except ImportError:
            return _FONT_FILES
        key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, key) as k:
                    for i in range(winreg.QueryInfoKey(k)[1]):
                        name, val, _t = winreg.EnumValue(k, i)
                        path = val if os.path.isabs(str(val)) else os.path.join(FONTS_DIR, str(val))
                        base = str(name).split(" (")[0]
                        for n in base.split(" & "):
                            _FONT_FILES.setdefault(n.strip().lower(), path)
            except OSError:
                continue
    return _FONT_FILES


def subtitle_fonts_dir(ass_text: str) -> str:
    """Carpeta SOLO con las fuentes que usan los subtítulos. libass carga todas las de la carpeta que se le da al
    empezar: con las ~345 de Windows eran ~0,4 s en cada trozo de la exportación en paralelo (medido). Se guarda en la
    caché (una vez). Si algo falla, la carpeta de fuentes de Windows, como antes."""
    import hashlib
    import re
    import shutil
    fams = {f.strip().lower() for f in re.findall(r"^Style:\s*[^,]*,([^,]+),", ass_text, re.M)}
    fams |= {f.strip().lower() for f in re.findall(r"\\fn([^\\}]+)", ass_text)}
    fonts = _installed_fonts()
    files = sorted({p for name, p in fonts.items() for f in fams if name == f or name.startswith(f + " ")})
    if not fams or not files or not all(any(n == f or n.startswith(f + " ") for n in fonts) for f in fams):
        return FONTS_DIR
    try:
        from ..core.paths import cache_dir
        d = os.path.join(str(cache_dir("fuentes_subtitulos")),
                         hashlib.sha1("|".join(files).encode("utf-8")).hexdigest()[:12])
        os.makedirs(d, exist_ok=True)
        for p in files:
            dst = os.path.join(d, os.path.basename(p))
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(p):
                shutil.copyfile(p, dst)
        return d
    except OSError:
        return FONTS_DIR


def _filter_path(path: str) -> str:
    """Ruta de Windows escrita como la entiende un filtro de FFmpeg: 'C\\:/carpeta/archivo'."""
    p = path.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
    return f"'{p}'"

ENCODERS = {
    ("h264", "cpu"): "libx264",
    ("hevc", "cpu"): "libx265",
}


def video_encoder(codec: str, where: str) -> str:
    """«gpu» = la tarjeta de este equipo (NVIDIA NVENC, AMD AMF o Intel Quick Sync); sin ninguna, el procesador."""
    if where == "gpu":
        from ..core import hw
        enc = hw.video_encoder(codec)
        if enc:
            return enc
    return ENCODERS[(codec, "cpu")]

PRESETS = {
    "YouTube 1080p": (1920, 1080, 24),
    "YouTube 1440p": (2560, 1440, 40),
    "YouTube 4K": (3840, 2160, 80),
    "YouTube Shorts (vertical)": (1080, 1920, 24),
}

# Destinos de un clic (botones de la ventana Exportar). Lo que recomiendan YouTube y TikTok para subir:
# H.264 High, 4:2:0, BT.709, fotogramas constantes, un fotograma clave cada medio segundo, AAC-LC a 48 kHz y
# «faststart». bitrate = Mbps por tamaño (1080p, 1440p, 4K) a 60 FPS. Por encima del mínimo que piden: los edits
# (grano, destellos, mucho movimiento) se veían con bloques; la plataforma vuelve a comprimir y parte de algo mejor.
TARGETS = {
    "youtube": {"name": "▶ YouTube", "suffix": "YouTube", "codec": "h264", "audio": 384,
                "br": {1080: 24, 1440: 40, 2160: 80},
                "info": "H.264 High · {w}×{h} · {fps} FPS · {br} Mbps · audio AAC 320–384 kbps · color BT.709 — "
                        "lo que recomienda YouTube para subir (Shorts incluidos)."},
    "tiktok": {"name": "♪ TikTok", "suffix": "TikTok", "codec": "h264", "audio": 256, "vertical": True,
               "br": {1080: 20, 1440: 20, 2160: 20},
               "info": "H.264 High · {w}×{h} · {fps} FPS · {br} Mbps · audio AAC 256 kbps — vertical 9:16, "
                       "listo para TikTok, Reels o Shorts."},
    "windows": {"name": "⧉ Para ver en Windows", "suffix": "", "codec": "h264", "audio": 256,
                "br": {1080: 16, 1440: 25, 2160: 50},
                "info": "H.264 · {w}×{h} · {fps} FPS · {br} Mbps · audio AAC — se abre con doble clic en "
                        "Windows (Fotos / Reproductor multimedia), en el móvil y en cualquier programa."},
}


def target_size(target: str, pw: int, ph: int) -> tuple[int, int]:
    """Tamaño para un destino a partir del proyecto (vertical para TikTok)."""
    t = TARGETS.get(target, {})
    if t.get("vertical") and pw > ph:
        return 1080, 1920
    return pw // 2 * 2, ph // 2 * 2


def target_bitrate(target: str, w: int, h: int) -> float:
    t = TARGETS.get(target)
    if not t:
        return 16.0
    short = min(w, h)
    key = 2160 if short >= 2000 else (1440 if short >= 1300 else 1080)
    return float(t["br"][key])


@dataclass
class ExportOptions:
    path: str
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    codec: str = "h264"        # h264 | hevc
    encoder: str = "gpu"       # cpu | gpu (NVIDIA, AMD o Intel: la que tenga el equipo)
    bitrate_mbps: float = 16.0
    audio_kbps: int = 320
    subtitles: bool = True     # incrustar los subtítulos (si están activados en el proyecto)
    loudnorm: bool = True      # normalizar a -14 LUFS (si está activado en el proyecto)
    audio_only: bool = False   # solo el audio (para escuchar efectos/EQ al momento): sale un .wav
    target: str = "custom"     # youtube | tiktok | windows | custom (botones de destino)
    video_only: bool = False   # solo la imagen (los trozos de la exportación en paralelo)
    duration: float = 0.0      # duración exacta (0 = la del proyecto)
    max_quality: bool = False  # tarjeta gráfica en «máxima calidad» (con análisis previo): ~2 veces más lento
    low_priority: bool = False  # «Dejar libre el PC»: FFmpeg en prioridad baja (puedes usar el PC mientras exporta)


_AAC_MF: bool | None = None
STILLS_ONCE = True       # (imágenes quietas decodificadas una vez; las pruebas lo apagan para comparar con lo de antes)


def aac_args(kbps: int) -> list[str]:
    """Códec del sonido final (AAC). El de Windows (Media Foundation) si está: ~7–14× más rápido que el de FFmpeg con la
    misma calidad (medido: 5 min en 1,4 s frente a 9,9 s; fidelidad 42,3 frente a 43,5 dB). Su máximo es 320 kbps: con
    384 (YouTube) va a 320 (la plataforma recomprime el sonido de todas formas). Si no está, el de FFmpeg en modo rápido.
    (La comprobación escribía un MP4 a una tubería, que FFmpeg no permite: fallaba siempre y nunca se usaba.)"""
    global _AAC_MF
    if _AAC_MF is None:
        try:
            from ..core import media as media_tools
            r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                       "sine=d=0.2:sample_rate=48000", "-ac", "2", "-c:a", "aac_mf", "-b:a", "192k",
                                       "-f", "adts", "-"], timeout=20)
            _AAC_MF = r.returncode == 0
        except Exception:  # noqa: BLE001
            _AAC_MF = False
    if _AAC_MF:
        return ["-c:a", "aac_mf", "-b:a", f"{min(int(kbps), 320)}k"]
    return ["-c:a", "aac", "-aac_coder", "fast", "-b:a", f"{kbps}k"]


def _stills_once(filters: list[str], stills: dict[int, tuple[str, str]]) -> list[str]:
    """Cada imagen quieta entra como UN fotograma: aquí se repite (loop) a sus fps y se corta a su duración, con la
    etiqueta [im{k}] en lugar de [{k}:v] (cada entrada se usa una sola vez en el filtro)."""
    if not stills:
        return filters
    out = list(filters)
    pre = []
    for k, (fps, dur) in stills.items():
        src, new = f"[{k}:v]", f"[im{k}]"
        for i, f in enumerate(out):
            if src in f:
                out[i] = f.replace(src, new, 1)
                pre.append(f"{src}loop=loop=-1:size=1:start=0,setpts=N,trim=duration={dur}{new}")
                break
    return pre + out


def _num(x: float) -> str:
    """30.0 -> '30', 29.97 -> '29.97'"""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def clip_video_filters(k: int, c, m, W: int, H: int, F: str) -> list[str]:
    """Filtros de un clip. Con ✂ recorte de sujeto (IA), la máscara se pone lo primero (en tiempo del archivo).
    ▭ Sin barras negras: el archivo se recorta a su zona con imagen ANTES de todo, y el clip se encuadra con ese
    tamaño (como si el video no las tuviera: se amplía y el fondo desenfocado tampoco las lleva)."""
    from ..core import black_bars as BB
    from ..core import subject_mask as SMK
    bars = BB.of(c.layout) if m.kind == KIND_VIDEO and m.width and m.height else None
    mc = m
    if bars:
        bw_, bh_ = transform.even(m.width * bars[2]), transform.even(m.height * bars[3])
        bx_, by_ = transform.even(m.width * bars[0]) if bars[0] > 0 else 0, \
            transform.even(m.height * bars[1]) if bars[1] > 0 else 0
        bw_, bh_ = min(bw_, m.width - bx_), min(bh_, m.height - by_)
        mc = replace(m, width=bw_, height=bh_)
    out = _clip_video_filters(k, c, mc, W, H, F)
    box = c.layout or transform.FULL
    rot = transform.rot_of(box)
    if rot and not _anim(c):          # ⟳ girada: en un lienzo cuadrado transparente (se coloca centrada en su sitio)
        import math
        bw, bh = transform.even(box["w"] * W), transform.even(box["h"] * H)
        d = transform.rot_size(bw, bh)
        out[-1] = out[-1][: out[-1].rindex(f"[v{k}]")] + f"[v{k}rr]"
        out.append(f"[v{k}rr]format=yuva420p,rotate=a={math.radians(rot):.5f}:ow={d}:oh={d}:c=black@0[v{k}]")
    sm = SMK.of(c.fx) if m.kind == KIND_VIDEO else None
    if sm is None and not bars:
        return out

    def feed(src: str, new: str):                 # lo primero de la cadena pasa a leer de «new»
        for i, f in enumerate(out):
            if src in f:
                out[i] = f.replace(src, new, 1)
                break
    pre: list[str] = []
    src = f"[{k}:v]"
    if sm is not None:
        pre = SMK.ffmpeg_pre(k, sm, m.width, m.height, c.source_in)
        feed(src, f"[sa{k}]")
        src = f"[sa{k}]"
    if bars:
        feed(src, f"[nb{k}]")
        pre.append(f"{src}crop={mc.width}:{mc.height}:{bx_}:{by_}[nb{k}]")
    return pre + out


def _clip_video_filters(k: int, c, m, W: int, H: int, F: str) -> list[str]:
    """Filtros de un clip (terminan en [v{k}]): zoom animado → encajar en su caja → efectos → colocar.
    «blurfill» (Shorts): el clip entero en el centro y, detrás, el mismo clip ampliado y desenfocado.
    «mirrorfill» (edits): el clip en el centro y, arriba y abajo, copias (como el original; en espejo si
    "flip"), borrosas y algo oscuras."""
    box = c.layout or transform.FULL
    if _anim(c):        # 🎞 posición/tamaño animados: se dibuja a su tamaño más grande y luego se reduce
        wm, hm = transform.layout_max(c)
        box = dict(box, w=wm, h=hm)
    bw, bh = transform.even(box["w"] * W), transform.even(box["h"] * H)
    fit = box.get("fit", "contain")
    fxd = dict(c.fx or {})
    pre_list: list[str] = []
    fill_mode = fit in ("blurfill", "mirrorfill")
    if fill_mode:
        # ⚡ Rápido: en los verticales con copias/fondo, el color y los looks se aplican al CLIP (p. ej. 1080×608)
        # antes de montarlo, no a toda la pantalla (1080×1920): ~3 veces menos trabajo y las copias salen iguales
        sw0, sh0 = transform.fit_size(m.width, m.height, bw, bh, "contain")
        pre_d = {k: v for k, v in fxd.items() if k in FILL_PRE}
        fxd = {k: v for k, v in fxd.items() if k not in FILL_PRE}
        pre_list = effects.look_filters(pre_d, sw0, sh0)
    fx = ",".join(effects.ffmpeg_filters(fxd, c.duration, bw, bh))
    fx = fx + "," if fx else ""
    if c.color and not color.is_neutral(c.color):     # la misma tabla 3D que ves en el visor
        lut = color_lut(c.color)
        if fill_mode:
            pre_list.insert(0, lut)
        else:
            fx = lut + "," + fx
    pre = (",".join(pre_list) + ",") if pre_list else ""
    if float((c.fx or {}).get("glow", 0) or 0) > 0:    # brillo soñador: dos ramas y se vuelve a la cadena
        fx = fx + f"null[gz{k}];{effects.glow_graph(c.fx, k)};[go{k}]format=yuv420p,"
    regions = effects.blur_regions(c.fx)
    if regions:   # desenfoque por zonas: se sale de la cadena y se vuelve a ella con [ro{k}]
        fx = fx + f"null[rz{k}];{effects.region_blur_graph(regions, k)};[ro{k}]"
    alpha = opacity_filters(c, m)
    flips = ("hflip," if box.get("flip_h") else "") + ("vflip," if box.get("flip_v") else "")   # ↔ ↕ voltear
    place = f"{flips}{fx}setsar=1,format=yuv420p,{alpha}setpts=PTS-STARTPTS+{c.start:.3f}/TB"
    cr = box.get("crop")
    crop_f = ""
    if cr and any(float(cr.get(k, 0)) > 1e-4 for k in ("l", "t", "r", "b")):
        # ✂ Recortar (como Resolve): los bordes de la capa se esconden (transparentes); no cambia de tamaño
        l_, t_ = int(round(float(cr.get("l", 0)) * bw)), int(round(float(cr.get("t", 0)) * bh))
        r_, b_ = int(round(float(cr.get("r", 0)) * bw)), int(round(float(cr.get("b", 0)) * bh))
        cw_, ch_ = max(2, bw - l_ - r_), max(2, bh - t_ - b_)
        crop_f = f"format=yuva420p,crop={cw_}:{ch_}:{l_}:{t_},pad={bw}:{bh}:{l_}:{t_}:color=black@0,"
        place = place.replace("format=yuv420p,", crop_f, 1)
    zoom_src = 0.0 if m.kind == KIND_IMAGE else c.source_in

    def zoom_or_scale(w: int, h: int) -> str:
        if transform.is_zoomed(c.zoom_kf):
            if m.kind == KIND_IMAGE:
                return transform.zoompan_filter(c.zoom_kf, zoom_src, w, h, F)
            return transform.zoompan_filter(c.zoom_kf, zoom_src, w, h, F, c.speed, c.reverse, c.src_len)
        return f"scale={w}:{h}"

    # Velocidad: congelado (repite el primer fotograma), hacia atrás y más rápido/lento.
    # Va justo al principio para que lo demás (zoom, efectos, posición) cuente en tiempo de la timeline.
    rt = enhance_video(c, m) + retime_video(c, m, bw, F)

    if fit == "blurfill":
        sw, sh = transform.fit_size(m.width, m.height, bw, bh, "contain")
        cw, ch = transform.fit_size(m.width, m.height, bw, bh, "cover")
        small_w, small_h = transform.even(cw / 4), transform.even(ch / 4)
        return [
            f"[{k}:v]{rt}fps={F},split=2[bg{k}][fg{k}]",
            # Fondo: ampliado para llenar, muy desenfocado y un poco más oscuro (se hace a 1/4 de tamaño: rápido)
            f"[bg{k}]scale={small_w}:{small_h},crop={transform.even(bw / 4)}:{transform.even(bh / 4)},{pre}"
            f"boxblur=10:3,eq=brightness=-0.10:saturation=0.9,scale={bw}:{bh}:flags=fast_bilinear,setsar=1[bgb{k}]",
            f"[fg{k}]{zoom_or_scale(sw, sh)},setsar=1,{pre}null[fgs{k}]",
            f"[bgb{k}][fgs{k}]overlay=(W-w)/2:(H-h)/2,{place}[v{k}]",
        ]
    if fit == "mirrorfill":
        sw, sh = transform.fit_size(m.width, m.height, bw, bh, "contain")
        qw, qh = transform.even(sw / 4), transform.even(sh / 4)
        n = 1
        while n * qh < bh / 4 + qh:      # copias necesarias para cubrir el alto (siempre impar)
            n += 2
        # Centro normal; las copias, como el original (o volteadas en espejo si el encuadre lo pide)
        copies = [f"[r{k}_{i}]" for i in range(n)]
        mirror = bool(box.get("flip"))
        flips = "".join(f"[r{k}_{i}]vflip[f{k}_{i}];" if mirror and (i - n // 2) % 2 else f"[r{k}_{i}]null[f{k}_{i}];"
                        for i in range(n))
        stack = "".join(f"[f{k}_{i}]" for i in range(n))
        return [
            f"[{k}:v]{rt}fps={F},{zoom_or_scale(sw, sh)},setsar=1,{pre}split=2[fg{k}][mr{k}]",
            f"[mr{k}]scale={qw}:{qh},split={n}{''.join(copies)};{flips}"
            f"{stack}vstack={n},crop={qw}:{transform.even(bh / 4)},boxblur=4:2,"
            f"eq=brightness=-0.14:saturation=0.85,scale={sw}:{bh}:flags=fast_bilinear,pad={bw}:{bh}:(ow-iw)/2:0:color=black,"
            f"setsar=1[bgb{k}]",
            f"[bgb{k}][fg{k}]overlay=(W-w)/2:(H-h)/2,{place}[v{k}]",
        ]
    from ..core import decor
    ent = decor.enter_of(c.fx)
    if ent is not None and ent["from"] == "fade":     # entrada «apareciendo suave»: por transparencia
        place = place.replace("format=yuv420p,", f"format=yuva420p,fade=t=in:st=0:d={float(ent.get('dur', 0.45)):.3f}:"
                                                 "alpha=1,", 1)
    if decor.has_frame(c.fx):          # sombra / contorno: la imagen se encoge un poco para que quepan
        dm, dow = decor.margins(c.fx, W, H)
        iw_ = max(16, (bw - 2 * dm - 2 * dow) // 2 * 2)
        ih_ = max(16, (bh - 2 * dm - 2 * dow) // 2 * 2)
        sw, sh = transform.fit_size(m.width, m.height, iw_, ih_, "stretch" if fit == "stretch" else "contain")
        fl, _dw, _dh = decor.ffmpeg_frame(k, c.fx, sw, sh, W, H, f"dsrc{k}")
        place = place.replace("format=yuv420p,", "format=yuva420p,", 1)
        return ([f"[{k}:v]{rt}fps={F},{zoom_or_scale(sw, sh)},setsar=1[dsrc{k}]"] + fl +
                [f"[dec{k}]pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:color=black@0,{place}[v{k}]"])
    sw, sh = transform.fit_size(m.width, m.height, bw, bh, fit)
    chain = [f"fps={F}", zoom_or_scale(sw, sh)]
    from ..core import chroma, motion_key
    mkey = motion_key.of(c.fx)
    if mkey is not None:        # 👤 fondo quieto fuera: transparente donde la imagen es igual al fondo vacío
        place = place.replace("format=yuv420p,", "format=yuva420p,", 1)
        mk_end = (_cover_crop(c, m, box, bw, bh) if fit == "cover"
                  else f"pad={bw}:{bh}:({bw}-iw)/2:({bh}-ih)/2:color=black@0")
        return ([f"[{k}:v]{rt}fps={F},{zoom_or_scale(sw, sh)},setsar=1[mks{k}]"] +
                motion_key.ffmpeg_filter(k, mkey, f"mks{k}", sw, sh) + [f"[mk{k}]{mk_end},{place}[v{k}]"])
    ck = chroma.ffmpeg_filter(chroma.of(c.fx))
    from ..core import subject_mask as SMK
    if ck or (SMK.of(c.fx) and m.kind == KIND_VIDEO):
        # 🟩 pantalla verde / ✂ recorte de sujeto: lo de fuera se vuelve transparente (y lo de debajo se ve)
        if ck:
            chain.append(ck)
        place = place.replace("format=yuv420p,", "format=yuva420p,")
        if fit == "cover":
            chain.append(_cover_crop(c, m, box, bw, bh))
        else:
            chain.append(f"pad={bw}:{bh}:({bw}-iw)/2:({bh}-ih)/2:color=black@0")
        return [f"[{k}:v]{rt}" + ",".join(chain) + f",{place}[v{k}]"]
    if fit == "cover":
        chain.append(_cover_crop(c, m, box, bw, bh))
    elif box.get("bg") == "none":  # capturas superpuestas: sin bandas negras alrededor
        chain += ["format=yuva420p", f"pad={bw}:{bh}:({bw}-iw)/2:({bh}-ih)/2:color=black@0"]
        return [f"[{k}:v]{rt}" + ",".join(chain) + f",{flips}{fx}setsar=1,{crop_f}{alpha}setpts=PTS-STARTPTS+{c.start:.3f}/TB[v{k}]"]
    else:
        chain.append(f"pad={bw}:{bh}:({bw}-iw)/2:({bh}-ih)/2:color=black")
    return [f"[{k}:v]{rt}" + ",".join(chain) + f",{place}[v{k}]"]


def _cover_crop(c, m, box: dict, bw: int, bh: int) -> str:
    """Recorte al llenar la caja («cover»): centrado o, con 🎯 «seguir la acción», moviéndose con ella."""
    kf = (box or {}).get("follow") or []
    if not kf:
        return f"crop={bw}:{bh}:(iw-{bw})/2:(ih-{bh})/2"
    s_expr = curves.s_of_t(c, "t", m.kind == KIND_IMAGE)
    fx = transform.ffmpeg_expr([dict(k, z=1.0, y=0.5) for k in kf], "x", s_expr)
    return f"crop={bw}:{bh}:x='max(0,min(iw-{bw},({fx})*iw-{bw}/2))':y=(ih-{bh})/2"


# Looks «de píxel» que en los verticales con copias/fondo se aplican al clip antes de montarlo (ver arriba)
FILL_PRE = {"bw", "warm", "cold", "punchy", "rgbsplit", "duotone", "oldfilm", "grain", "motionblur", "glitch"}


def opacity_filters(c, m) -> str:
    """Opacidad del clip (fija o con curva). Con un modo de fusión la aplica el propio «blend»."""
    if c.blend != "normal" or (c.opacity >= 0.999 and not c.op_kf):
        return ""
    if not c.op_kf:
        return f"format=yuva420p,colorchannelmixer=aa={c.opacity:.4f},"
    s_expr = curves.s_of_t(c, "T", m.kind == KIND_IMAGE)
    a = f"{c.opacity:.4f}*({curves.ffmpeg_expr(c.op_kf, s_expr)})"
    return f"format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='alpha(X,Y)*clip({a},0,1)',"


def volume_curve(c) -> list[str]:
    """Curva de volumen (si tiene puntos): t es el tiempo dentro del clip (ya con su velocidad)."""
    if not c.vol_kf:
        return []
    return [f"volume='{curves.ffmpeg_expr(c.vol_kf, curves.s_of_t(c, 't'))}':eval=frame"]


def blend_filters(k: int, c, last: str, W: int, H: int, bx: int, by: int, box_w: int, box_h: int) -> list[str]:
    """Modo de fusión (pantalla, multiplicar…): la mezcla se hace en RGB sobre toda la imagen."""
    mode = curves.BLEND_FFMPEG.get(c.blend) or "normal"
    neutral = {"multiply": "white", "darken": "white", "overlay": "gray", "softlight": "gray"}.get(mode, "black")
    op = max(0.0, min(1.0, c.opacity))
    return [
        f"[v{k}]format=gbrp,pad={W}:{H}:{bx}:{by}:color={neutral},setpts=PTS-STARTPTS,"
        f"tpad=start_duration={c.start:.3f}:start_mode=add:color={neutral}[bl{k}]",
        f"[{last}]format=gbrp[bb{k}]",
        f"[bb{k}][bl{k}]blend=all_mode={mode}:all_opacity={op:.3f}:shortest=0:repeatlast=0:eof_action=pass:"
        f"enable='between(t,{c.start:.3f},{c.end:.3f})',format=yuv420p[o{k}]",
    ]


def enhance_video(c, m) -> str:
    """Reducir ruido y estabilizar (van primero: trabajan sobre los fotogramas originales)."""
    from ..core import enhance
    fx = c.fx or {}
    out = enhance.stab_filter(c) if (m.kind == KIND_VIDEO and c.speed > 0) else ""
    return out + enhance.denoise_filter(fx.get("denoise", 0) or 0)


def retime_video(c, m, box_w: int, F: str) -> str:
    """Filtros de velocidad de un clip de video (terminan en coma; vacío si va a velocidad normal)."""
    if m.kind != KIND_VIDEO or not c.retimed:
        return ""
    if c.speed <= 0:     # fotograma congelado
        return f"trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={c.duration + 0.5:.3f},"
    out = ""
    if c.reverse:        # hacia atrás: guarda los fotogramas en memoria (se reducen antes para no gastar de más)
        out += f"fps={F},scale=w='min(iw,{box_w})':h=-2,reverse,"
    if c.speed != 1.0:
        out += f"setpts=(PTS-STARTPTS)/{c.speed:.4f},"
    if c.smooth and 0 < c.speed < 0.999:   # cámara lenta suave: fotogramas inventados
        # Primero a la medida del video final (con margen para los zooms): inventar fotogramas cuesta por píxel
        if not c.reverse:      # margen solo para el zoom que de verdad tiene el clip (antes siempre ×1,5)
            zmax = max([1.0] + [float(k.get("z", 1.0)) for k in (c.zoom_kf or [])])
            out += f"scale=w='min(iw,{transform.even(box_w * min(1.5, zmax))})':h=-2,"
        out += f"minterpolate=fps={F}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
    return out


def retime_audio(c) -> list[str]:
    """Filtros de velocidad del sonido: al revés y más rápido/lento sin voz de ardilla (atempo)."""
    if not c.retimed or c.speed <= 0:
        return []
    out = ["areverse"] if c.reverse else []
    sp = c.speed
    while sp > 2.0:              # atempo admite 0.5–2 por paso: se encadena
        out.append("atempo=2.0")
        sp /= 2.0
    while sp < 0.5:
        out.append("atempo=0.5")
        sp /= 0.5
    if abs(sp - 1.0) > 1e-4:
        out.append(f"atempo={sp:.5f}")
    return out


def _src_args(c) -> list[str]:
    """Qué trozo del archivo se lee: con velocidad, src_len segundos (congelado: un instante)."""
    if c.speed <= 0:
        return ["-ss", f"{c.source_in:.3f}", "-t", "0.25"]
    return ["-ss", f"{c.source_in:.3f}", "-t", f"{c.src_len:.3f}"]


def chains_of(project: Project, track_id: str) -> list[tuple[list, list[dict]]]:
    """Grupos de clips seguidos unidos por transiciones: [([c0, c1, …], [trans0→1, …])]."""
    out: list[tuple[list, list[dict]]] = []
    for left, right, t in transitions.pairs(project, track_id):
        if out and out[-1][0][-1].id == left.id:
            out[-1][0].append(right)
            out[-1][1].append(t)
        else:
            out.append(([left, right], [t]))
    return out


def chain_filters(project: Project, members: list, trans: list[dict], W: int, H: int, F: str,
                  add_input) -> tuple[list[str], str]:
    """Filtros de una cadena de clips con transiciones (xfade). Cada clip se alarga dur/2 a cada lado
    con material del archivo (o, si no hay, repitiendo su primer/último fotograma). Termina en [label]
    colocado ya en el tiempo de la timeline."""
    filters: list[str] = []
    labels: list[str] = []
    n = len(members)
    for i, c in enumerate(members):
        m = project.media_of(c)
        lead = trans[i - 1]["dur"] / 2 if i > 0 else 0.0
        tail = trans[i]["dur"] / 2 if i < n - 1 else 0.0
        hb, ha = transitions.handles(project, c)
        take_lead, take_tail = min(lead, hb), min(tail, ha)
        ext = replace(c, start=0.0, duration=c.duration + take_lead + take_tail)
        if m.kind == KIND_VIDEO and c.speed > 0:
            ext.source_in = c.source_in - (take_tail if c.reverse else take_lead) * c.speed
        if m.kind == KIND_IMAGE:
            k = add_input(["-loop", "1", "-framerate", F, "-t", f"{ext.duration:.3f}"], m.path)
        else:
            k = add_input(_src_args(ext), m.path)
        filters += clip_video_filters(k, ext, m, W, H, F)
        pads = []
        if lead - take_lead > 1e-3:
            pads.append(f"start_mode=clone:start_duration={lead - take_lead:.3f}")
        if tail - take_tail > 1e-3:
            pads.append(f"stop_mode=clone:stop_duration={tail - take_tail:.3f}")
        pad = f"tpad={':'.join(pads)}," if pads else ""
        filters.append(f"[v{k}]{pad}format=yuva420p,fps={F}[c{k}]")
        labels.append(f"c{k}")
    start = members[0].start
    acc = labels[0]
    for i in range(1, n):
        t = trans[i - 1]
        offset = members[i].start - t["dur"] / 2 - start
        out = f"x{labels[i][1:]}"
        filters.append(f"[{acc}][{labels[i]}]xfade=transition={t['type']}:duration={t['dur']:.3f}:"
                       f"offset={offset:.3f}[{out}]")
        acc = out
    final = f"tr{labels[0][1:]}"
    filters.append(f"[{acc}]setpts=PTS-STARTPTS+{start:.3f}/TB[{final}]")
    return filters, final


def _anim(c) -> bool:
    """¿Posición/tamaño animados? (con un modo de fusión especial la capa se queda quieta, en su sitio)."""
    return bool(getattr(c, "layout_kf", None)) and not (c.blend != "normal" and curves.BLEND_FFMPEG.get(c.blend))


def _anim_place(k: int, c, m, W: int, H: int, last: str) -> list[str]:
    """🎞 Cada fotograma: el tamaño y la posición de las claves (suave entre ellas), sobre lo de debajo."""
    s_expr = curves.s_of_t(c, f"(t-{c.start:.4f})", m.kind == KIND_IMAGE)
    kf = c.layout_kf
    we = f"max(2,trunc({W}*({transform.layout_expr(kf, 'w', s_expr)})/2)*2)"
    he = f"max(2,trunc({H}*({transform.layout_expr(kf, 'h', s_expr)})/2)*2)"
    xe = f"{W}*({transform.layout_expr(kf, 'x', s_expr)})"
    ye = f"{H}*({transform.layout_expr(kf, 'y', s_expr)})"
    return [f"[v{k}]scale=w='{we}':h='{he}':eval=frame[va{k}]",
            f"[{last}][va{k}]overlay=x='{xe}':y='{ye}':eval=frame:eof_action=pass:"
            f"enable='between(t,{c.start:.3f},{c.end:.3f})'[o{k}]"]


def color_lut(col: dict) -> str:
    """La tabla de color 3D del clip. ⚡ Se aplica en 16 bits: FFmpeg tiene para eso código rápido del procesador
    (en 8 bits usa uno lento que gastaba más de 2 veces la CPU y era el mayor freno al exportar); sale igual o mejor."""
    return f"format=gbrp16le,lut3d=file={_filter_path(color.cube_file(col))}:interp=tetrahedral,format=yuv420p"


def adjust_filters(i: int, c, last: str, W: int, H: int) -> tuple[list[str], str]:
    """🎨 Capa de ajuste: su color y sus efectos se aplican a TODO lo de debajo mientras dura. Solo se procesa ese
    tramo (trim) y se vuelve a poner encima; su opacidad y sus fundidos suavizan el efecto (no funden a negro)."""
    a, b = c.start, c.end
    fx = dict(c.fx or {})
    fin, fout = float(fx.pop("fade_in", 0) or 0), float(fx.pop("fade_out", 0) or 0)
    chain = []
    if c.color and not color.is_neutral(c.color):
        chain.append(color_lut(c.color))
    chain += effects.ffmpeg_filters(fx, c.duration, W, H)
    glow = float(fx.get("glow", 0) or 0) > 0
    alpha = []
    if c.opacity < 0.999 or c.op_kf or fin > 0 or fout > 0:
        alpha.append("format=yuva420p")
        if c.opacity < 0.999 or c.op_kf:
            from types import SimpleNamespace
            op = opacity_filters(c, SimpleNamespace(kind=KIND_IMAGE))     # (tiempo desde el inicio del clip)
            if op:
                alpha.append(op.rstrip(","))
        if fin > 0:
            alpha.append(f"fade=t=in:st=0:d={fin:.3f}:alpha=1")
        if fout > 0:
            alpha.append(f"fade=t=out:st={max(0.0, c.duration - fout):.3f}:d={fout:.3f}:alpha=1")
    k = f"{i}a"
    head = f"[ajs{i}]trim=start={a:.4f}:end={b:.4f}," + ",".join(["setpts=PTS-STARTPTS"] + chain + ["setsar=1"])
    if glow:     # brillo: dos ramas (como en los clips)
        head += f",null[gz{k}];{effects.glow_graph(fx, k)};[go{k}]"
    else:
        head += ","
    head += ",".join(["format=yuv420p"] + alpha + [f"setpts=PTS+{a:.4f}/TB"]) + f"[ajf{i}]"
    out = [f"[{last}]split=2[ajm{i}][ajs{i}]", head,
           f"[ajm{i}][ajf{i}]overlay=x=0:y=0:eof_action=pass:enable='between(t,{a:.3f},{b:.3f})'[ajo{i}]"]
    return out, f"ajo{i}"


def _full_frame(project: Project, c) -> bool:
    """¿El clip ocupa toda la pantalla, opaco y sin mezclas? (entonces puede ir encadenado con concat)"""
    from ..core import chroma, decor, generators, motion_key, subject_mask
    if generators.is_adjust(project.media_of(c)):       # 🎨 capa de ajuste: transparente, no tapa nada
        return False
    box = c.layout or transform.FULL
    if transform.rot_of(box):                            # ⟳ girada: deja ver lo de debajo en las esquinas
        return False
    return (not getattr(c, "layout_kf", None) and motion_key.of(c.fx) is None and subject_mask.of(c.fx) is None and not box.get("crop") and not decor.enter_of(c.fx) and not decor.has_frame(c.fx) and box.get("x", 0) <= 1e-3 and box.get("y", 0) <= 1e-3 and box.get("w", 1) >= 0.999 and
            box.get("h", 1) >= 0.999 and box.get("bg") != "none" and c.blend == "normal" and c.opacity >= 0.999
            and not c.op_kf and chroma.of(c.fx) is None)


def _runs(project: Project, track_id: str) -> list[list]:
    """Bloques de la pista para encadenar (concat): unidades seguidas, sin huecos y a pantalla completa.
    Unidad = un clip suelto o una cadena de clips con transiciones. Solo bloques de 2 o más unidades."""
    units: list[tuple[float, float, list, list | None]] = []
    in_chain: set[str] = set()
    for members, trans in chains_of(project, track_id):
        units.append((members[0].start, members[-1].end, members, trans))
        in_chain.update(c.id for c in members)
    for c in project.clips_on(track_id):
        if c.id not in in_chain:
            units.append((c.start, c.end, [c], None))
    units.sort(key=lambda u: u[0])
    runs: list[list] = []
    cur: list = []
    for u in units:
        ok = all(c.enabled and project.media_of(c) is not None and os.path.exists(project.media_of(c).path)
                 and _full_frame(project, c) and project.media_of(c).kind in (KIND_VIDEO, KIND_IMAGE)
                 for c in u[2])
        if ok and cur and abs(u[0] - cur[-1][1]) < 2e-3:
            cur.append(u)
            continue
        if len(cur) >= 2:
            runs.append(cur)
        cur = [u] if ok else []
    if len(cur) >= 2:
        runs.append(cur)
    return runs



def build_command(project: Project, opts: ExportOptions, ffmpeg: str,
                  script_path: str) -> tuple[list[str], float]:
    """Devuelve (argumentos de ffmpeg, duración total). Escribe el filtro en script_path."""
    total = opts.duration or project.duration()
    if total <= 0:
        raise ValueError("La timeline está vacía: no hay nada que exportar.")
    W, H, F = opts.width, opts.height, _num(opts.fps)

    # -nostdin: FFmpeg no debe quedarse esperando al teclado (podía colgar la exportación)
    args = [ffmpeg, "-nostdin", "-y", "-hide_banner", "-nostats", "-progress", "pipe:1"]
    base_f = f"color=c=black:s={W}x{H}:r={F}:d={total:.3f},format=yuv420p[base]"
    filters = [] if opts.audio_only else [base_f]
    audio_inputs: list[tuple[int, float, float]] = []  # (índice de entrada, inicio, volumen)
    mono: set[int] = set()   # entradas de audio mono (se duplican a estéreo sin perder volumen)
    clip_eq: dict[int, str] = {}   # ecualizador y balance de cada clip
    n_inputs = 0
    last = "base"

    stills: dict[int, tuple[str, str]] = {}   # imágenes quietas: entrada → (fps, duración)

    def add_input(extra: list[str], path: str) -> int:
        nonlocal n_inputs
        # ⚡ Una imagen quieta se decodifica UNA vez y el fotograma se repite dentro del filtro (_stills_once): con
        # «-loop 1» se volvía a decodificar en cada fotograma (un PNG 1080p, 24 ms por fotograma; medido: −11 a −14 %
        # de CPU en una exportación con 8 imágenes, y la imagen sale idéntica). GIF y WEBP (pueden moverse), como antes.
        if (STILLS_ONCE and len(extra) == 6 and extra[0] == "-loop" and extra[2] == "-framerate" and extra[4] == "-t"
                and os.path.splitext(path)[1].lower() not in (".gif", ".webp", ".apng")):
            stills[n_inputs] = (extra[3], extra[5])
            extra = ["-framerate", extra[3]]   # (la base de tiempo 1/F: sin ella se redondeaba a 1/25 y a 60 FPS la imagen
            #                                     acababa un fotograma antes, dejando ver la capa de abajo; revisión de Fable)
        args.extend(extra + ["-i", path])
        n_inputs += 1
        return n_inputs - 1

    extra: dict[int, list[str]] = {}   # filtros adicionales de cada entrada de audio
    ran: set[str] = set()
    # --- video: de la pista de más abajo a la de más arriba ---
    video_tracks = [t for t in project.tracks if t.kind == TRACK_VIDEO]
    for tr in reversed(video_tracks):
        # Clips unidos por transiciones: se componen juntos (xfade) y se colocan de una vez
        chained: set[str] = set()
        if not tr.hidden and not opts.audio_only:
            # Rendimiento: los clips seguidos a pantalla completa se ENCADENAN (concat) y se colocan de una vez.
            # Antes cada clip era una capa encima de todo el video (139 planos = 139 capas sobre cada fotograma).
            for run in _runs(project, tr.id):
                segs = []
                for u_start, u_end, members, trans in run:
                    dur = u_end - u_start
                    if trans is not None:      # cadena con transiciones (xfade): ya sale como un solo trozo
                        fl, lab = chain_filters(project, members, trans, W, H, F, add_input)
                        filters += fl
                        src_lab = lab
                    else:
                        c = members[0]
                        m = project.media_of(c)
                        if m.kind == KIND_IMAGE:
                            k = add_input(["-loop", "1", "-framerate", F, "-t", f"{c.duration:.3f}"], m.path)
                        else:
                            k = add_input(_src_args(c), m.path)
                        filters += clip_video_filters(k, c, m, W, H, F)
                        src_lab = f"v{k}"
                        ran.add(c.id)              # su sonido (si tiene) se añade aquí, no en el bucle normal
                        if m.kind == KIND_VIDEO and m.has_audio and project.audible(tr) and c.volume > 0 \
                                and not c.link and c.speed > 0 and not opts.video_only:
                            audio_inputs.append((k, c.start, c.volume))     # su sonido, desde esta misma entrada
                            if m.channels == 1:
                                mono.add(k)
                            clip_eq[k] = equalizer.ffmpeg_chain(c.eq, c.pan)
                            extra[k] = retime_audio(c) + volume_curve(c)
                    seg = f"sg{len(segs)}_{src_lab}"
                    # duración EXACTA (si el archivo se queda corto, se repite su último fotograma: nada se desplaza)
                    filters.append(f"[{src_lab}]setpts=PTS-STARTPTS,format=yuv420p,fps={F},"
                                   f"tpad=stop_mode=clone:stop_duration=2,trim=duration={dur:.4f},"
                                   f"setpts=PTS-STARTPTS[{seg}]")
                    segs.append(seg)
                    chained.update(c.id for c in members)
                a, b = run[0][0], run[-1][1]
                rl = f"run{len(chained)}_{segs[0]}"
                cat = "".join(f"[{s_}]" for s_ in segs) + f"concat=n={len(segs)}:v=1:a=0"
                if last == "base" and a < 0.5 / opts.fps and b > total - 0.5 / opts.fps:
                    # ⚡ El bloque llena TODO el video desde abajo: él es el fondo (sin lienzo negro ni capa encima
                    # en cada fotograma). Pasa en casi todos los trozos de un video largo.
                    filters.remove(base_f)
                    filters.append(cat + f",setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,"
                                         f"trim=duration={total:.4f},setpts=PTS-STARTPTS[o{rl}]")
                else:
                    filters.append(cat + f",setpts=PTS-STARTPTS+{a:.3f}/TB[{rl}]")
                    filters.append(f"[{last}][{rl}]overlay=x=0:y=0:eof_action=pass:"
                                   f"enable='between(t,{a:.3f},{b:.3f})'[o{rl}]")
                last = f"o{rl}"
            in_runs = set(chained)
            for members, trans in chains_of(project, tr.id):
                if any(c.id in in_runs for c in members):
                    continue
                if not all(project.media_of(c) and os.path.exists(project.media_of(c).path) for c in members):
                    continue
                fl, lab = chain_filters(project, members, trans, W, H, F, add_input)
                filters += fl
                box = members[0].layout or transform.FULL
                bx, by = int(round(box["x"] * W)), int(round(box["y"] * H))
                a, b = members[0].start, members[-1].end
                filters.append(f"[{last}][{lab}]overlay=x={bx}:y={by}:eof_action=pass:"
                               f"enable='between(t,{a:.3f},{b:.3f})'[o{lab}]")
                last = f"o{lab}"
                chained.update(c.id for c in members)
        for c in project.clips_on(tr.id):
            m = project.media_of(c)
            if not c.enabled or m is None or not os.path.exists(m.path):
                continue
            # Si su sonido está separado (vinculado en una pista de audio), se exporta desde allí
            wants_audio = m.kind == KIND_VIDEO and m.has_audio and project.audible(tr) and c.volume > 0 and not c.link \
                and c.speed > 0 and not opts.video_only
            if (tr.hidden or opts.audio_only or c.id in chained) and not wants_audio:
                continue
            if c.id in ran:
                continue          # clip suelto que ya va en un bloque encadenado (con su sonido)
            from ..core import generators
            if generators.is_adjust(m):           # 🎨 capa de ajuste: actúa sobre todo lo que hay debajo
                if not tr.hidden and not opts.audio_only and c.id not in chained:
                    fl, last = adjust_filters(len(filters), c, last, W, H)
                    filters += fl
                continue
            if m.kind == KIND_IMAGE:
                k = add_input(["-loop", "1", "-framerate", F, "-t", f"{c.duration:.3f}"], m.path)
            elif m.kind == KIND_VIDEO:
                k = add_input(_src_args(c), m.path)
            else:
                continue
            if not tr.hidden and not opts.audio_only and c.id not in chained:
                from ..core import fill as FILL
                _box = c.layout or transform.FULL
                _rot = transform.rot_of(_box) if not _anim(c) else 0.0
                rel = FILL.of(c.fx)
                if rel is not None:      # ▦ relleno: la propia imagen, ampliada y desenfocada, detrás (toda la pantalla)
                    from dataclasses import replace as _rep
                    if m.kind == KIND_IMAGE:
                        kb = add_input(["-loop", "1", "-framerate", F, "-t", f"{c.duration:.3f}"], m.path)
                    else:
                        kb = add_input(_src_args(c), m.path)
                    rt_bg = retime_video(_rep(c, smooth=False), m, W, F)
                    filters.append(FILL.ffmpeg_bg(kb, rel, W, H, rt_bg, F, c.start, f"rl{kb}"))
                    filters.append(f"[{last}][rl{kb}]overlay=x=0:y=0:eof_action=pass:"
                                   f"enable='between(t,{c.start:.3f},{c.end:.3f})'[orl{kb}]")
                    last = f"orl{kb}"
                filters += clip_video_filters(k, c, m, W, H, F)
                box = c.layout or transform.FULL
                bx, by = int(round(box["x"] * W)), int(round(box["y"] * H))
                if _rot:                 # ⟳ el lienzo girado es más grande: centrado en el mismo sitio
                    _bw, _bh = transform.even(box["w"] * W), transform.even(box["h"] * H)
                    _d = transform.rot_size(_bw, _bh)
                    bx, by = bx - (_d - _bw) // 2, by - (_d - _bh) // 2
                if _anim(c):
                    filters += _anim_place(k, c, m, W, H, last)
                elif c.blend != "normal" and curves.BLEND_FFMPEG.get(c.blend):
                    filters += blend_filters(k, c, last, W, H, bx, by,
                                             transform.even(box["w"] * W), transform.even(box["h"] * H))
                else:
                    from ..core import decor
                    xy = decor.ffmpeg_xy(c.fx, c.start, bx, by, transform.even(box["w"] * W),
                                         transform.even(box["h"] * H))
                    if xy:      # entrada deslizando (desde la derecha, abajo…)
                        filters.append(
                            f"[{last}][v{k}]overlay=x={xy[0]}:y={xy[1]}:eval=frame:eof_action=pass:"
                            f"enable='between(t,{c.start:.3f},{c.end:.3f})'[o{k}]")
                    else:
                        filters.append(
                            f"[{last}][v{k}]overlay=x={bx}:y={by}:eof_action=pass:"
                            f"enable='between(t,{c.start:.3f},{c.end:.3f})'[o{k}]")
                last = f"o{k}"
            if wants_audio:
                audio_inputs.append((k, c.start, c.volume))
                if m.channels == 1:
                    mono.add(k)
                clip_eq[k] = equalizer.ffmpeg_chain(c.eq, c.pan)
                extra[k] = retime_audio(c) + volume_curve(c)

    # --- audio: pistas de audio (con sus efectos y el ducking de la música) ---
    speech = audio_fx.speech_intervals(project)
    for tr in project.tracks:
        if tr.kind != TRACK_AUDIO or not project.audible(tr) or opts.video_only:
            continue
        for c in project.clips_on(tr.id):
            m = project.media_of(c)
            if not c.enabled or m is None or c.volume <= 0 or not os.path.exists(m.path) or c.speed <= 0 \
                    or not (m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)):
                continue
            k = add_input(_src_args(c), m.path)
            audio_inputs.append((k, c.start, c.volume))
            if m.channels == 1:
                mono.add(k)
            clip_eq[k] = equalizer.ffmpeg_chain(c.eq, c.pan)
            chain = retime_audio(c) + volume_curve(c)
            if tr.fx:
                chain.append(audio_fx.fx_chain(tr.fx))
            if tr.duck_db is not None:
                duck = audio_fx.ffmpeg_duck_volume(speech, c.start, c.end, tr.duck_db)
                if duck:
                    chain.append(duck)
            fx = c.fx or {}
            if float(fx.get("fade_in", 0)) > 0:
                chain.append(f"afade=t=in:st=0:d={float(fx['fade_in']):.3f}")
            if float(fx.get("fade_out", 0)) > 0:
                fo = float(fx["fade_out"])
                chain.append(f"afade=t=out:st={max(0.0, c.duration - fo):.3f}:d={fo:.3f}")
            extra[k] = [x for x in chain if x]

    if audio_inputs:
        labels = []
        for k, start, vol in audio_inputs:
            ms = int(round(start * 1000))
            fx = "".join(f",{x}" for x in extra.get(k, []))
            eq = f"{clip_eq[k]}," if clip_eq.get(k) else ""
            # Mono → estéreo copiando el canal (la conversión estándar lo bajaría 3 dB)
            to_stereo = "pan=stereo|c0=c0|c1=c0," if k in mono else ""
            filters.append(
                f"[{k}:a]aresample=48000,{to_stereo}aformat=sample_fmts=fltp:channel_layouts=stereo,{eq}"
                f"volume={vol:.3f}{fx},adelay={ms}:all=1[a{k}]")
            labels.append(f"[a{k}]")
        final = f",{audio_fx.LOUDNORM},aresample=48000" if (project.loudnorm and opts.loudnorm) else ""
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:"
                       f"duration=longest{final},apad[aout]")
    elif not opts.video_only:
        filters.append("anullsrc=r=48000:cl=stereo[aout]")

    if opts.audio_only:  # solo audio: sin imagen, textos ni subtítulos
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(";\n".join(filters))
        args += ["-/filter_complex", script_path, "-map", "[aout]", "-t", f"{total:.3f}",
                 "-c:a", "pcm_s16le", "-ar", "48000", opts.path]
        return args, total

    # --- textos en pantalla (títulos, etiquetas) ---
    titles = [(c.start, c.end, c.text) for tr in project.tracks if tr.kind == TRACK_TEXT and not tr.hidden
              for c in project.clips_on(tr.id) if c.enabled and c.text]
    if titles:
        from ..core import title_render
        tdir = os.path.join(os.path.dirname(script_path), "editoria_textos")
        os.makedirs(tdir, exist_ok=True)
        for i, (a, b, t) in enumerate(titles):
            img, pos = title_render.render(t, W, H)
            png = os.path.join(tdir, f"texto_{i}.png")
            img.save(png, "PNG")
            dur = max(0.05, b - a)
            fd = min(0.15, dur / 3)
            bu = float(t.get("blur_under") or 0)
            if bu > 0:      # «Desenfocar lo de debajo»: la imagen se desenfoca mientras se ve el texto
                sig = (4 + 26 * min(1.0, bu)) * H / 1080
                filters.append(f"[{last}]gblur=sigma={sig:.1f}:enable='between(t,{a:.3f},{b:.3f})'[tb{i}]")
                last = f"tb{i}"
            k = add_input(["-loop", "1", "-framerate", F, "-t", f"{dur:.3f}"], png)
            filters.append(f"[{k}:v]format=rgba,fade=t=in:st=0:d={fd:.3f}:alpha=1,"
                           f"fade=t=out:st={dur - fd:.3f}:d={fd:.3f}:alpha=1,"
                           f"setpts=PTS-STARTPTS+{a:.3f}/TB[tx{i}]")
            filters.append(f"[{last}][tx{i}]overlay=x={int(round(pos.x()))}:y={int(round(pos.y()))}:"
                           f"eof_action=pass:enable='between(t,{a:.3f},{b:.3f})'[txo{i}]")
            last = f"txo{i}"

    # --- subtítulos incrustados ---
    if opts.subtitles and project.subtitles.enabled:
        cues = styled_cues(project)
        if cues:
            ass_path = os.path.join(os.path.dirname(script_path), "editoria_subtitulos.ass")
            ass_text = build_ass(cues, project.subtitles, W, H)
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_text)
            filters.append(f"[{last}]subtitles=filename={_filter_path(ass_path)}:"
                           f"fontsdir={_filter_path(subtitle_fonts_dir(ass_text))}[subs]")
            last = "subs"
    filters.append(f"[{last}]format=yuv420p[vout]")
    filters = _stills_once(filters, stills)

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(";\n".join(filters))

    codec = "h264" if opts.target in TARGETS else opts.codec     # los destinos: siempre H.264 (se ve en todos lados)
    encoder = video_encoder(codec, opts.encoder)
    br = opts.bitrate_mbps
    gop = max(1, int(round(opts.fps / 2)))       # un fotograma clave cada medio segundo (lo que pide YouTube)
    args += ["-/filter_complex", script_path, "-map", "[vout]"] + ([] if opts.video_only else ["-map", "[aout]"]) + [
             "-t", f"{total:.3f}", "-r", F, "-fps_mode", "cfr",
             "-c:v", encoder, "-b:v", f"{_num(br)}M", "-maxrate", f"{_num(br * 1.5)}M",
             "-bufsize", f"{_num(br * 2)}M", "-pix_fmt", "yuv420p", "-g", str(gop),
             "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
    # ⚡ Con el procesador: «faster» gasta ~30 % menos que «medium» y a 16–24 Mbps casi no se nota (medido: un trozo
    # de 12,5 s, 47,6 s de CPU frente a 69,8 s); con «máxima calidad», «medium» como antes
    if encoder == "libx264":
        args += ["-preset", "medium" if opts.max_quality else "faster", "-profile:v", "high", "-bf", "2",
                 "-flags", "+cgop"]
    elif encoder == "libx265":
        args += ["-preset", "medium" if opts.max_quality else "fast", "-tag:v", "hvc1"]
    else:                                        # tarjeta gráfica: cada marca con sus ajustes (core/hw.py)
        from ..core import hw
        args += hw.export_args(encoder, opts.max_quality)
    if opts.video_only:
        args += ["-an", opts.path]
        return args, total
    audio_k = TARGETS[opts.target]["audio"] if opts.target in TARGETS else opts.audio_kbps
    args += aac_args(audio_k) + ["-ar", "48000", "-ac", "2", "-movflags", "+faststart", opts.path]
    return args, total
