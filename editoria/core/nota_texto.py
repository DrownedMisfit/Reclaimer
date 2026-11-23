"""
📝 Nota de texto (Efectos → «📝 Nota de texto»): un texto en pantalla PROPIO (va a la pista de textos: no toca los
subtítulos ni la transcripción) con un FONDO BORROSO ALREDEDOR: un recuadro de esquinas suaves que desenfoca el video
de debajo. La barrita «Tamaño del borroso» lo lleva, de forma continua, de ajustado al texto (0) a TODA la pantalla (1).
El borroso sigue al texto si lo mueves (también si está 📌 pegado a un objeto).

Un mismo cálculo para el visor (ui/preview.LookEffect) y la exportación (export/ffmpeg_export): se ven igual.

Claves en clip.text (los textos de antes no las tienen = sin borroso alrededor):
  zone_blur (bool) · zone_size 0–1 (ajustado → toda la pantalla) · zone_strength 0–1 (fuerza) · zone_dark 0–1 (oscurecer)

  zone_of(text) -> dict | None                 lo que pide el texto (None = sin borroso)
  zone_rect(text, W, H) -> dict                el recuadro en píxeles (pares) + esquinas y borde suave
  zone_now(text, local, dur, W, H) -> dict     el de ese instante (con el desplazamiento si va pegado y el fundido)
  mask(w, h, r, f) -> np.ndarray               la transparencia del recuadro (1 dentro, borde suave)
  export_filters(...)                          el trozo del grafo de FFmpeg
  text_box(text, W, H) / text_from_box(...)    la caja del texto para moverlo y escalarlo en el visor
"""
from __future__ import annotations

import math

ZONE_DEFAULTS = {"zone_blur": False, "zone_size": 0.0, "zone_strength": 0.6, "zone_dark": 0.2}
ZONE_KEYS = tuple(ZONE_DEFAULTS)
DEFAULT_DUR = 4.0          # segundos que dura una nota nueva (se alarga o acorta en la línea de tiempo)

# Cómo nace una nota: letra blanca con sombra suave, sin caja (el borroso hace de fondo), en el centro
NOTE_STYLE = {"font": "Arial", "size": 5.0, "color": "#FFFFFF", "bold": True, "box": False, "stroke_size": 0.0,
              "shadow": True, "shadow_opacity": 0.6, "shadow_blur": 20.0, "blur_under": 0.0, "x": 0.5, "y": 0.5,
              "zone_blur": True, "zone_size": 0.0, "zone_strength": 0.6, "zone_dark": 0.2}


def _f(t: dict, k: str) -> float:
    try:
        return min(1.0, max(0.0, float(t.get(k, ZONE_DEFAULTS[k]))))
    except (TypeError, ValueError):
        return float(ZONE_DEFAULTS[k])


def zone_of(t: dict | None) -> dict | None:
    """{"size", "strength", "dark"} si el texto lleva fondo borroso alrededor; None si no."""
    if not t or not t.get("zone_blur"):
        return None
    return {"size": _f(t, "zone_size"), "strength": _f(t, "zone_strength"), "dark": _f(t, "zone_dark")}


def sigma_px(strength: float, H: int) -> float:
    """Cuánto desenfoca (sigma en píxeles del lienzo): de suave a muy borroso, proporcional al alto del video."""
    return (3.0 + 27.0 * min(1.0, max(0.0, strength))) * H / 1080.0


# ------------------------------------------------------------------ dónde queda el texto
_INK: dict = {}


def ink_rect(t: dict, W: int, H: int) -> tuple[float, float, float, float]:
    """(x, y, w, h) de las letras (y su caja, si la lleva) en el lienzo, SIN el desplazamiento de 📌 pegado."""
    key = (repr(sorted((k, v) for k, v in t.items() if k not in ZONE_KEYS and k != "pos_kf")), W, H)
    hit = _INK.get(key)
    if hit is None:
        from . import title_render
        r = title_render.ink_rect(t, W, H)
        if len(_INK) > 64:
            _INK.clear()
        hit = _INK[key] = (r.x(), r.y(), r.width(), r.height())
    return hit


def _px(t: dict, H: int) -> float:
    try:
        return max(1.0, float(t.get("size", 6.0)) / 100 * H)
    except (TypeError, ValueError):
        return 0.06 * H


def zone_rect(t: dict, W: int, H: int) -> dict:
    """El recuadro borroso: {"x0", "y0", "x1", "y1"} en píxeles PARES (FFmpeg recorta así), "r" esquinas y "f" borde
    suave (píxeles). Con zone_size 0 abraza al texto con un margen pequeño; con 1 es toda la pantalla."""
    z = zone_of(t) or {"size": 0.0}
    s = z["size"]
    x, y, w, h = ink_rect(t, W, H)
    px = _px(t, H)
    pad = max(4.0, 0.4 * px)
    tx0, ty0 = max(0.0, x - pad), max(0.0, y - pad)
    tx1, ty1 = min(float(W), x + w + pad), min(float(H), y + h + pad)
    if tx1 - tx0 < 4 or ty1 - ty0 < 4:          # (el texto está fuera de la pantalla)
        tx0, ty0, tx1, ty1 = W / 2 - 2, H / 2 - 2, W / 2 + 2, H / 2 + 2
    # De lo ajustado a toda la pantalla, cada borde a la vez (crece de forma continua)
    x0, y0 = tx0 * (1 - s), ty0 * (1 - s)
    x1, y1 = tx1 + (W - tx1) * s, ty1 + (H - ty1) * s
    X0, Y0 = int(math.floor(x0 / 2)) * 2, int(math.floor(y0 / 2)) * 2
    X1, Y1 = min(W - W % 2, int(math.ceil(x1 / 2)) * 2), min(H - H % 2, int(math.ceil(y1 / 2)) * 2)
    X1, Y1 = max(X1, X0 + 2), max(Y1, Y0 + 2)
    if s >= 0.999:                               # toda la pantalla: sin esquinas ni borde
        return {"x0": 0, "y0": 0, "x1": W - W % 2, "y1": H - H % 2, "r": 0.0, "f": 0.0}
    k = 1.0 - s
    f = max(1.0, 0.3 * pad) * k
    r = max(f, min(1.2 * pad, (X1 - X0) / 2, (Y1 - Y0) / 2) * k)
    return {"x0": X0, "y0": Y0, "x1": X1, "y1": Y1, "r": round(r, 2), "f": round(f, 2)}


def _fade(t: dict, dur: float) -> float:
    """El mismo fundido que el texto (visor: subtitle_item.paint_title · exportación: ffmpeg_export)."""
    try:
        fd = min(max(0.0, float(t.get("fade", 0.15))), dur / 3)
    except (TypeError, ValueError):
        fd = min(0.15, dur / 3)
    return max(fd, 0.001)


def _place(v: float, size: int, full: int) -> int:
    """Como en FFmpeg: clip(trunc(v/2)*2, 0, full-size)."""
    return int(min(max(math.trunc(v / 2) * 2, 0), max(0, full - size)))


def zone_now(t: dict, local: float, dur: float, W: int, H: int) -> dict | None:
    """El recuadro en el instante local (desde que empieza el texto): con el desplazamiento si va 📌 pegado a un
    objeto, el sigma del desenfoque, cuánto oscurece y la opacidad del fundido (la del texto)."""
    z = zone_of(t)
    if z is None:
        return None
    g = zone_rect(t, W, H)
    w, h = g["x1"] - g["x0"], g["y1"] - g["y0"]
    if t.get("pos_kf"):
        from .motion_track import text_offset_at
        dx, dy = text_offset_at(t, local)
        x0, y0 = _place(g["x0"] + W * dx, w, W), _place(g["y0"] + H * dy, h, H)
        g = dict(g, x0=x0, y0=y0, x1=x0 + w, y1=y0 + h)
    if g["r"] < 0.5 and g["f"] < 0.5:        # toda la pantalla: de golpe, como «Desenfocar lo de debajo» al exportar
        alpha = 1.0 if 0.0 <= local < dur else 0.0
    else:
        fd = _fade(t, dur)
        alpha = max(0.0, min(1.0, local / fd, (dur - local) / fd))
    return dict(g, sigma=sigma_px(z["strength"], H), dark=z["dark"], alpha=alpha)


_MASKS: dict = {}


def mask(w: int, h: int, r: float, f: float):
    """Transparencia del recuadro (h × w, float32 0–1): 1 dentro, esquinas redondeadas de radio r y borde suave de f
    píxeles. Sin r ni f (toda la pantalla): todo 1."""
    import numpy as np
    key = (int(w), int(h), round(float(r), 2), round(float(f), 2))
    hit = _MASKS.get(key)
    if hit is not None:
        return hit
    w, h = max(1, int(w)), max(1, int(h))
    if f < 0.5 and r < 0.5:
        a = np.ones((h, w), np.float32)
    else:
        r = max(float(r), float(f), 0.5)
        f = max(float(f), 0.5)
        xs = np.abs(np.arange(w, dtype=np.float32) + 0.5 - w / 2) - (w / 2 - r)
        ys = np.abs(np.arange(h, dtype=np.float32) + 0.5 - h / 2) - (h / 2 - r)
        dx = np.maximum(xs, 0)[None, :]
        dy = np.maximum(ys, 0)[:, None]
        d = np.sqrt(dx * dx + dy * dy)
        a = np.clip((r - d) / f, 0.0, 1.0).astype(np.float32)
    if len(_MASKS) > 24:
        _MASKS.clear()
    _MASKS[key] = a
    return a


# ------------------------------------------------------------------ exportación (FFmpeg)
def export_filters(t: dict, a: float, b: float, W: int, H: int, i: int, last: str, add_input, F: str,
                   png_dir: str, total: float) -> tuple[list[str], str]:
    """El fondo borroso alrededor de un texto en el grafo de FFmpeg: se recorta el recuadro de lo que hay debajo
    [last], se desenfoca (gblur, el mismo sigma que el visor), se oscurece, se le pone la transparencia de las esquinas
    (la MISMA máscara que el visor, en un PNG que dura todo el video) y el fundido del texto, y se pega encima.
    Sin «trim»: con trim, el overlay esperaba al primer fotograma del recuadro guardando en memoria TODOS los anteriores
    (2,7 GB con la nota en el segundo 30 a 1080p); ahora cada filtro solo trabaja con enable entre a y b.
    Toda la pantalla: gblur con enable directamente sobre [last] (como «Desenfocar lo de debajo»).
    Devuelve (filtros, etiqueta)."""
    import os

    import numpy as np
    z = zone_of(t)
    if z is None or b - a <= 0.02:
        return [], last
    g = zone_rect(t, W, H)
    w, h = g["x1"] - g["x0"], g["y1"] - g["y0"]
    if w < 4 or h < 4:
        return [], last
    en = f"enable='between(t,{a:.3f},{b:.3f})'"
    sig = sigma_px(z["strength"], H)
    dark = ""
    if z["dark"] > 0.001:
        k = 1.0 - z["dark"]
        dark = f",colorchannelmixer=rr={k:.3f}:gg={k:.3f}:bb={k:.3f}:{en}"
    if g["r"] < 0.5 and g["f"] < 0.5:        # toda la pantalla: sin recorte, ni máscara, ni fundido (como el visor)
        return [f"[{last}]gblur=sigma={sig:.2f}:{en}{dark}[nzo{i}]"], f"nzo{i}"
    fd = _fade(t, b - a)
    from .motion_track import text_offset_expr
    off = text_offset_expr(t, f"(t-{a:.4f})")
    if off:       # 📌 pegado a un objeto: el recuadro se mueve con él (como el texto)
        xe = f"clip(trunc(({g['x0']}+{W}*({off[0]}))/2)*2,0,{W - w})"
        ye = f"clip(trunc(({g['y0']}+{H}*({off[1]}))/2)*2,0,{H - h})"
        xy_crop, xy_ov = f"x='{xe}':y='{ye}'", f"x='{xe}':y='{ye}':eval=frame"
    else:
        xy_crop = xy_ov = f"x={g['x0']}:y={g['y0']}"
    os.makedirs(png_dir, exist_ok=True)
    png = os.path.join(png_dir, f"borroso_{i}.png")
    from PIL import Image          # (Pillow: rutas con tildes sin problema, a diferencia de cv2.imwrite)
    Image.fromarray(np.round(mask(w, h, g["r"], g["f"]) * 255).astype(np.uint8), "L").save(png)
    k_in = add_input(["-loop", "1", "-framerate", F, "-t", f"{max(total, b) + 1:.3f}"], png)
    return [f"[{k_in}:v]format=gray[nzk{i}]",
            f"[{last}]split[nzm{i}][nzc{i}];[nzc{i}]crop=w={w}:h={h}:{xy_crop}:exact=1,gblur=sigma={sig:.2f}:{en}"
            f"{dark},format=yuva444p[nzb{i}];[nzb{i}][nzk{i}]alphamerge,"
            f"fade=t=in:st={a:.3f}:d={fd:.3f}:alpha=1,fade=t=out:st={b - fd:.3f}:d={fd:.3f}:alpha=1[nz{i}]",
            f"[nzm{i}][nz{i}]overlay={xy_ov}:eof_action=pass:{en}[nzo{i}]"], f"nzo{i}"


# ------------------------------------------------------------------ mover y escalar el texto en el visor
def text_box(t: dict, local: float, W: int, H: int) -> dict:
    """La caja del texto en fracciones del lienzo (como la «layout» de un clip), para arrastrarla en el visor."""
    x, y, w, h = ink_rect(t, W, H)
    pad = max(3.0, 0.15 * _px(t, H))
    dx = dy = 0.0
    if t.get("pos_kf"):
        from .motion_track import text_offset_at
        dx, dy = text_offset_at(t, local)
    return {"x": round((x - pad) / W + dx, 4), "y": round((y - pad) / H + dy, 4),     # (4 decimales, como el visor)
            "w": round((w + 2 * pad) / W, 4), "h": round((h + 2 * pad) / H, 4), "_text": True}


def text_from_box(t: dict, orig: dict, box: dict) -> dict:
    """El texto con la caja movida/escalada en el visor: el centro mueve x, y; una esquina cambia el tamaño de la
    letra (sin deformar); una media arista (o Mayús + esquina) estira con el zoom X/Y."""
    out = dict(t)
    ow, oh = max(1e-5, float(orig["w"])), max(1e-5, float(orig["h"]))
    sx, sy = float(box["w"]) / ow, float(box["h"]) / oh
    ocx, ocy = orig["x"] + ow / 2, orig["y"] + oh / 2
    ncx, ncy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    tx, ty = float(t.get("x", 0.5)), float(t.get("y", 0.12))
    out["x"] = round(ncx + (tx - ocx) * sx, 4)
    out["y"] = round(ncy + (ty - ocy) * sy, 4)
    if abs(sx - 1) > 0.003 or abs(sy - 1) > 0.003:      # (moverlo no cambia el tamaño por redondeos)
        if abs(sx - sy) < 1e-3:
            out["size"] = round(min(40.0, max(1.0, float(t.get("size", 6.0)) * sx)), 3)
        else:
            out["zoom_x"] = round(min(10.0, max(0.05, float(t.get("zoom_x", 1.0)) * sx)), 3)
            out["zoom_y"] = round(min(10.0, max(0.05, float(t.get("zoom_y", 1.0)) * sy)), 3)
    return out


# ------------------------------------------------------------------ fuentes
def fuentes() -> list[str]:
    """Las fuentes de Reclaimer, en orden: las de la 🖼 Miniatura, las de las 🅣 plantillas de título y las de los
    estilos de subtítulos (sin repetir y solo las que hay en este PC)."""
    from PySide6.QtGui import QFontDatabase
    out: list[str] = []
    try:
        from ..ui.thumb_text_bar import FUENTES
        out += list(FUENTES)
    except Exception:  # noqa: BLE001 - (sin la Miniatura, las demás)
        pass
    try:
        from . import title_templates as TT
        for _k, _name, tpl in TT.FACTORY:
            f = (tpl.get("style") or {}).get("font")
            if f:
                out.append(f)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import subtitles as S
        for st in getattr(S, "PRESETS", {}).values():
            f = st.get("font") if isinstance(st, dict) else None
            if f:
                out.append(f)
    except Exception:  # noqa: BLE001
        pass
    out += ["Arial", "Georgia", "Impact", "Arial Black", "Segoe UI", "Segoe UI Black"]
    have = {f.lower() for f in QFontDatabase.families()}
    return [f for f in dict.fromkeys(out) if f.lower() in have] or ["Arial"]
