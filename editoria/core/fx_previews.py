"""
🎞 Vistas previas de los efectos que trae Reclaimer: cada efecto, de verdad, sobre la misma toma.

La toma de muestra sale de un panorama de Poly Haven («Venice Sunset», licencia CC0 = dominio público: uso
comercial, sin atribución, se puede redistribuir): se «filma» con una cámara virtual que se mueve por el
panorama (dos planos: la laguna al atardecer y un palacio), así se ven también los efectos de movimiento.
Cada vista previa se renderiza con el MISMO motor que la exportación (no es un dibujo aproximado).

  assets/efectos/<grupo>_<clave>.webp   animación en bucle (al pasar el ratón)
  assets/efectos/<grupo>_<clave>.jpg    fotograma representativo (el icono)
  grupos: look (Efectos de imagen) · trans (Transiciones) · edit (efectos del edit musical)

  python -m editoria.core.fx_previews [claves…]   (re)genera todo (o solo esas); el panorama se descarga solo
  thumb(grupo, clave) / anim(grupo, clave) -> ruta o None
"""
from __future__ import annotations

import os
import subprocess
import sys

import numpy as np

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "efectos")
W, H, FPS = 320, 180, 24
CREDIT = "Toma de muestra: «Venice Sunset» de Poly Haven (polyhaven.com), CC0."
PANO_URL = "https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/venice_sunset.jpg"


def ensure_pano() -> str:
    """El panorama CC0 (4,8 MB), descargado una vez en datos/cache/vistas_efectos."""
    import urllib.request

    from .paths import cache_dir
    p = os.path.join(str(cache_dir("vistas_efectos")), "venice_sunset.jpg")
    if not os.path.exists(p):
        tmp = p + ".part"
        urllib.request.urlretrieve(PANO_URL, tmp)
        os.replace(tmp, p)
    return p


def thumb(group: str, key: str) -> str | None:
    p = os.path.join(ASSETS, f"{group}_{key}.jpg")
    return p if os.path.exists(p) else None


def anim(group: str, key: str) -> str | None:
    p = os.path.join(ASSETS, f"{group}_{key}.webp")
    return p if os.path.exists(p) else None


# ------------------------------------------------------------------ la toma de muestra (cámara virtual)
def _view(pano: np.ndarray, yaw: float, pitch: float, fov: float, w: int, h: int) -> np.ndarray:
    """Lo que vería una cámara normal mirando hacia (yaw, pitch) dentro del panorama equirectangular."""
    import cv2
    ph, pw = pano.shape[:2]
    f = 0.5 * w / np.tan(np.radians(fov) / 2)
    xs, ys = np.meshgrid(np.arange(w) - w / 2 + 0.5, np.arange(h) - h / 2 + 0.5)
    d = np.stack([xs, -ys, np.full_like(xs, f)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    cp, sp = np.cos(np.radians(pitch)), np.sin(np.radians(pitch))
    y2 = d[..., 1] * cp + d[..., 2] * sp
    z2 = -d[..., 1] * sp + d[..., 2] * cp
    cy, sy = np.cos(np.radians(yaw)), np.sin(np.radians(yaw))
    x3 = d[..., 0] * cy + z2 * sy
    z3 = -d[..., 0] * sy + z2 * cy
    lon = np.arctan2(x3, z3)
    lat = np.arcsin(np.clip(y2, -1, 1))
    mx = ((lon / (2 * np.pi) + 0.5) * pw).astype(np.float32) % pw
    my = ((0.5 - lat / np.pi) * ph).astype(np.float32)
    return cv2.remap(pano, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def make_base(pano_path: str, out_dir: str) -> dict[str, str]:
    """Dos planos de 4 s (640×360) con la cámara en movimiento: «a» el paseo con el palacio, «b» el atardecer."""
    import cv2

    from . import media as M
    pano = cv2.cvtColor(cv2.imread(pano_path), cv2.COLOR_BGR2RGB)
    shots = {"a": dict(yaw=(104.0, 136.0), pitch=(-5.0, -3.0), fov=(70.0, 62.0)),
             "b": dict(yaw=(24.0, 44.0), pitch=(-13.0, -9.0), fov=(76.0, 70.0))}
    out = {}
    for name, s in shots.items():
        path = os.path.join(out_dir, f"muestra_{name}.mp4")
        proc = subprocess.Popen([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                 "-s", "640x360", "-r", "30", "-i", "-", "-c:v", "libx264", "-crf", "20",
                                 "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        n = 120
        for k in range(n):
            u = k / (n - 1)
            e = u * u * (3 - 2 * u)                       # suave al empezar y al acabar
            frame = _view(pano, s["yaw"][0] + e * (s["yaw"][1] - s["yaw"][0]),
                          s["pitch"][0] + e * (s["pitch"][1] - s["pitch"][0]),
                          s["fov"][0] + e * (s["fov"][1] - s["fov"][0]), 640, 360)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        proc.stdin.close()
        proc.wait()
        out[name] = path
    return out


# ------------------------------------------------------------------ qué se enseña de cada efecto
def _specs() -> list[tuple[str, str, list[dict], float]]:
    """(grupo, clave, planos, instante del icono). Plano = dict con shot (a/b), dur, src, y lo del Clip."""
    from ..ui.effects_panel import LOOKS
    from . import transitions as TR
    out = []
    entry = {"glitch", "flash", "shake", "roll", "fade_in"}
    for key, _text, val, _tip in LOOKS:
        if key in entry:              # efectos «al entrar»: dos planos para que se vea dos veces en el bucle
            plan = [dict(shot="a", dur=1.5, src=0.3, fx={key: val}), dict(shot="a", dur=1.5, src=2.0, fx={key: val})]
            at = 1.5 + min(0.12, val / 2)
        elif key == "fade_out":
            plan, at = [dict(shot="a", dur=3.0, src=0.5, fx={key: val})], 2.75
        else:
            plan, at = [dict(shot="a", dur=3.0, src=0.5, fx={key: val})], 1.5
        out.append(("look", key, plan, at))
    for key, _name, _d in TR.CATALOG:
        plan = [dict(shot="a", dur=1.5, src=0.5), dict(shot="b", dur=1.5, src=1.5, trans={"type": key, "dur": 0.9})]
        at = {"zoomin": 1.15, "fadeblack": 1.09, "fadewhite": 1.09, "circleopen": 1.42, "radial": 1.5}.get(key, 1.3)
        out.append(("trans", key, plan, at))           # a media transición: que se vean las dos imágenes
    pk = [dict(shot="a" if i % 2 == 0 else "b", dur=0.75, src=0.4 + 0.5 * i) for i in range(4)]
    vel = []                                       # lento en el golpe → normal → acelerón (como el edit)
    for sh, s0 in (("a", 0.3), ("b", 0.2)):
        for d, src, sp in ((0.6, s0, 0.35), (0.22, s0 + 0.21, 1.0), (0.68, s0 + 0.43, 2.4)):
            vel.append(dict(shot=sh, dur=d, src=src, speed=sp, smooth=sp < 1,
                            fx={"motionblur": 0.6} if sp > 2 else None))
    out.append(("edit", "velocity", vel, 0.3))
    out.append(("edit", "shake", [dict(p, fx={"shake": 0.3, "shake_amp": 0.018}) for p in pk], 0.08))
    out.append(("edit", "punch", [dict(p, zoom=[(0.0, 1.22), (0.3, 1.0)]) for p in pk], 0.05))
    out.append(("edit", "glitch", [dict(p, fx={"glitch": 0.15}) for p in pk], 0.05))
    strobe = [dict(shot="a" if i % 2 == 0 else "b", dur=0.18, src=0.5 + 0.18 * i, fx={"flash": 0.05})
              for i in range(10)] + [dict(shot="a", dur=1.2, src=2.4, fx={"flash": 0.2})]
    out.append(("edit", "strobe", strobe, 0.02))
    out.append(("edit", "freeze", [dict(shot="a", dur=1.0, src=0.5), dict(shot="a", dur=1.2, src=1.5, speed=0.0),
                                   dict(shot="a", dur=1.0, src=1.5)], 1.6))
    out.append(("edit", "slowmo_calm", [dict(shot="b", dur=3.0, src=0.5, speed=0.5, smooth=True)], 1.5))
    out.append(("edit", "transitions", [dict(shot="a", dur=1.5, src=0.5),
                                        dict(shot="b", dur=1.5, src=1.5, trans={"type": "fade", "dur": 1.0})], 1.5))
    out.append(("edit", "grade", [dict(shot="a", dur=3.0, src=0.5, color={
        "saturation": -1.0, "contrast": 0.55, "exposure": -0.05, "shadows": -0.25, "highlights": 0.15})], 1.5))
    out.append(("edit", "grain", [dict(shot="a", dur=3.0, src=0.5, fx={"grain": 0.6})], 1.5))
    out.append(("edit", "vignette", [dict(shot="a", dur=3.0, src=0.5, fx={"vignette": 0.75})], 1.5))
    out.append(("edit", "letterbox", [dict(shot="a", dur=3.0, src=0.5, fx={"letterbox": 0.11})], 1.5))
    out.append(("edit", "extras", [dict(shot="a", dur=1.5, src=0.5, fx={"rgbsplit": 0.4, "glow": 0.35, "punchy": 0.6}),
                                   dict(shot="b", dur=1.5, src=1.5, fx={"flicker": 0.6, "roll": 0.35})], 1.62))
    return out


def _project(plan: list[dict], base: dict[str, str]):
    from .model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project, Track, new_id
    p = Project(width=W, height=H, fps=float(FPS))
    p.loudnorm = False
    tr = Track(new_id(), TRACK_VIDEO, "V1")
    p.tracks.append(tr)
    mids = {}
    for name, path in base.items():
        m = MediaItem(new_id(), path, KIND_VIDEO, os.path.basename(path), duration=4.0, width=640, height=360,
                      fps=30.0, has_audio=False, probed=True)
        p.media[m.id] = m
        mids[name] = m.id
    t = 0.0
    for it in plan:
        sp = float(it.get("speed", 1.0))
        src = float(it["src"])
        kf = [{"t": round(src + rel * (sp if sp > 0 else 1.0), 4), "z": z, "x": 0.5, "y": 0.5}
              for rel, z in it.get("zoom", [])]
        c = Clip(new_id(), mids[it["shot"]], tr.id, round(t, 4), src, it["dur"], fx=None, speed=sp,
                 smooth=bool(it.get("smooth")), zoom_kf=kf, color=it.get("color"))
        fx = dict(it.get("fx") or {})
        if it.get("trans"):
            fx["trans"] = it["trans"]
        c.fx = fx or None
        p.clips[c.id] = c
        t += it["dur"]
    return p


def render(group: str, key: str, plan: list[dict], at: float, base: dict[str, str], out_dir: str = ASSETS):
    from ..export.ffmpeg_export import ExportOptions, build_command
    from . import media as M
    os.makedirs(out_dir, exist_ok=True)
    p = _project(plan, base)
    tmp = os.path.join(out_dir, f"_tmp_{group}_{key}.mp4")
    opts = ExportOptions(path=tmp, width=W, height=H, fps=float(FPS), encoder="cpu", bitrate_mbps=2.5,
                         subtitles=False, loudnorm=False, video_only=True)
    args, _total = build_command(p, opts, M.ffmpeg(), os.path.join(out_dir, "_filtro.txt"))
    r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(f"{group}/{key}: " + (r.stderr or "")[-400:])
    try:
        base_name = os.path.join(out_dir, f"{group}_{key}")
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", tmp, "-vf", "fps=15",
                        "-c:v", "libwebp_anim", "-quality", "45", "-compression_level", "6", "-loop", "0", "-an",
                        base_name + ".webp"], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", tmp, "-frames:v", "1",
                        "-q:v", "4", base_name + ".jpg"], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        for f in (tmp, os.path.join(out_dir, "_filtro.txt")):
            try:
                os.remove(f)
            except OSError:
                pass


SIN = "__sin"          # la misma toma SIN el efecto (para comparar: el usuario no veía bien qué hacía cada uno)


def plain(plan: list[dict]) -> list[dict]:
    """Los mismos planos (misma toma, mismos cortes) sin efecto, ni zoom, ni cámara lenta, ni color, ni transición."""
    return [dict(shot=it["shot"], dur=it["dur"], src=it["src"]) for it in plan]


_plain_index: dict | None = None


def anim_plain(group: str, key: str) -> str | None:
    """La animación «sin efecto» de ese efecto (varias comparten la misma: sin_índice.json dice cuál)."""
    global _plain_index
    if _plain_index is None:
        import json
        try:
            with open(os.path.join(ASSETS, "sin_indice.json"), encoding="utf-8") as f:
                _plain_index = json.load(f)
        except (OSError, ValueError):
            _plain_index = {}
    name = _plain_index.get(f"{group}_{key}")
    p = os.path.join(ASSETS, name) if name else None
    return p if p and os.path.exists(p) else None


def generate_plain(pano_path: str, out_dir: str = ASSETS, log=print):
    """Las versiones «sin efecto» de los efectos de imagen y del edit musical (las transiciones ya se ven solas).
    Las iguales (misma toma, mismos cortes) se guardan una sola vez."""
    import hashlib
    import json
    os.makedirs(out_dir, exist_ok=True)
    base = make_base(pano_path, out_dir)
    index, seen = {}, {}
    try:
        for group, key, plan, at in _specs():
            if group not in ("look", "edit"):
                continue
            pl = plain(plan)
            sig = json.dumps(pl, sort_keys=True)
            if sig not in seen:
                name = f"sin_{len(seen) + 1}"
                render("base", name, pl, at, base, out_dir)
                try:
                    os.remove(os.path.join(out_dir, f"base_{name}.jpg"))     # (el icono no hace falta)
                except OSError:
                    pass
                seen[sig] = f"base_{name}.webp"
                log(f"✓ base_{name} (sin efecto)")
            index[f"{group}_{key}"] = seen[sig]
    finally:
        for f in base.values():
            try:
                os.remove(f)
            except OSError:
                pass
    with open(os.path.join(out_dir, "sin_indice.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    return index


def generate(pano_path: str, out_dir: str = ASSETS, only: set | None = None, log=print):
    os.makedirs(out_dir, exist_ok=True)
    base = make_base(pano_path, out_dir)
    try:
        for group, key, plan, at in _specs():
            if only and key not in only and f"{group}_{key}" not in only:
                continue
            render(group, key, plan, at, base, out_dir)
            log(f"✓ {group}_{key}")
    finally:
        for f in base.values():
            try:
                os.remove(f)
            except OSError:
                pass


if __name__ == "__main__":
    if sys.argv[1:] == ["--sin"]:
        generate_plain(ensure_pano())
    else:
        generate(ensure_pano(), only=set(sys.argv[1:]) or None)
