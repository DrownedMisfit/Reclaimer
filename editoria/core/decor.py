"""
Detalles de una imagen o video puesto ENCIMA de otro (como lo haces en Resolve): entrada animada, sombra suave y
contorno. Lo mismo en el visor y al exportar.

  fx["enter"]   = {"from": "right"|"left"|"bottom"|"top"|"fade", "dur": 0.45}
  fx["shadow"]  = {"opacity": 0.6, "blur": 0.02, "dx": 0.008, "dy": 0.012}   (fracciones del lado corto)
                  (21/11, «Drop Shadow» de Resolve) + "color": "#RRGGBB" (sin él = negro), "angle" (−180…180°, como
                  una brújula: 0 = arriba, 90 = derecha, 135 = abajo a la derecha) y "distance" (fracción del lado
                  corto). Con ángulo y distancia, dx y dy salen de ellos (y se guardan también: lo de antes los lee).
                  La forma de la sombra es la del ALFA de la imagen (un PNG recortado da su silueta).
  fx["outline"] = {"width": 0.006, "color": "#FFFFFF"}
"""
from __future__ import annotations

import math

ENTRANCES = {"right": "desde la derecha", "left": "desde la izquierda", "bottom": "desde abajo",
             "top": "desde arriba", "fade": "apareciendo suave"}
SHADOW = {"opacity": 0.6, "blur": 0.02, "dx": 0.008, "dy": 0.012}
OUTLINE = {"width": 0.006, "color": "#FFFFFF"}
COLOR_SOMBRA = "#000000"
# ✦ Efectos → Sombra: pequeña y sutil, para dar profundidad (fuerza 55 %, abajo a la derecha, 1 % y 2 % del lado corto)
SOMBRA_EFECTO = {"opacity": 0.55, "angle": 135.0, "distance": 0.01, "blur": 0.02, "color": COLOR_SOMBRA}


def enter_of(fx) -> dict | None:
    e = (fx or {}).get("enter")
    return e if isinstance(e, dict) and e.get("from") in ENTRANCES else None


def dxdy(angle: float, distance: float) -> tuple[float, float]:
    """Ángulo (brújula: 0 = arriba, 90 = derecha) y distancia → desplazamiento (dx, dy) en fracciones del lado corto."""
    a = math.radians(float(angle))
    return float(distance) * math.sin(a), -float(distance) * math.cos(a)


def angulo_distancia(dx: float, dy: float) -> tuple[float, float]:
    """Lo contrario de dxdy: (ángulo en grados, distancia)."""
    d = math.hypot(float(dx), float(dy))
    return (round(math.degrees(math.atan2(float(dx), -float(dy))), 1) if d > 1e-9 else 135.0), d


def color_sombra(c) -> str:
    """El color guardado («#RRGGBB»); cualquier cosa rara (o nada: proyectos de antes) = negro."""
    t = str(c or "").strip().lstrip("#")
    if len(t) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in t):
        return "#" + t.upper()
    return COLOR_SOMBRA


def sombra(opacity: float, angle: float, distance: float, blur: float, color: str = COLOR_SOMBRA) -> dict:
    """El fx["shadow"] que se guarda (con dx y dy ya calculados, para Escenas, overlay y lo que lea los de antes)."""
    dx, dy = dxdy(angle, distance)
    return {"opacity": round(min(1.0, max(0.0, float(opacity))), 3), "blur": round(max(0.0, float(blur)), 4),
            "dx": round(dx, 5), "dy": round(dy, 5), "angle": round(float(angle), 1),
            "distance": round(max(0.0, float(distance)), 4), "color": color_sombra(color)}


def shadow_of(fx) -> dict | None:
    """La sombra completa (con todos sus valores) o None. Con «angle»/«distance», dx y dy salen de ellos; sin ellos
    (Escenas, overlay, proyectos de antes), el ángulo y la distancia salen de dx y dy. Sin «color» = negro."""
    s = (fx or {}).get("shadow")
    if not isinstance(s, dict):
        return None
    out = dict(SHADOW, **s)
    if "angle" in s or "distance" in s:
        a0, d0 = angulo_distancia(out["dx"], out["dy"])
        ang, dist = float(s.get("angle", a0)), float(s.get("distance", d0))
        out["dx"], out["dy"] = dxdy(ang, dist)
        out["angle"], out["distance"] = ang, dist
    else:
        out["angle"], out["distance"] = angulo_distancia(out["dx"], out["dy"])
    out["color"] = color_sombra(s.get("color"))
    return out


def outline_of(fx) -> dict | None:
    """El contorno (borde de color) o None. Con 🌗 «Suavizar bordes» no se pinta (una línea dura alrededor de un borde
    suave se ve mal), pero NO se borra: vuelve en cuanto se quita el desvanecido."""
    o = (fx or {}).get("outline")
    if not isinstance(o, dict) or suavizar_of(fx) > 0:
        return None
    return dict(OUTLINE, **o)


SUAVIZAR_DEFECTO = 0.05     # 🌗 al activarlo: el borde se desvanece en un 5 % del lado corto de lo que se ve
SUAVIZAR_MAX = 0.5


def suavizar_of(fx) -> float:
    """🌗 «Suavizar bordes» (22/11, la «Softness» del Recorte de Resolve): fracción del lado corto de lo que se ve
    (la imagen menos su recorte) en la que el borde se desvanece hasta transparente. 0 = corte seco."""
    try:
        v = float((fx or {}).get("suavizar") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(SUAVIZAR_MAX, max(0.0, v))


def has_frame(fx) -> bool:
    """¿Lleva sombra o contorno? (entonces la imagen se encoge un poco dentro de su caja para que quepan)"""
    return shadow_of(fx) is not None or outline_of(fx) is not None


def ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3          # sale rápido y frena suave


def margins(fx, W: int, H: int) -> tuple[int, int]:
    """(margen para la sombra, grosor del contorno) en píxeles (pares)."""
    short = min(W, H)
    sh = shadow_of(fx)
    ol = outline_of(fx)
    m = 0
    if sh:
        m = int(round((sh["blur"] * 1.6 + max(abs(sh["dx"]), abs(sh["dy"]))) * short / 2)) * 2
    ow = int(round(ol["width"] * short / 2)) * 2 if ol else 0
    return m, ow


def sombra_por_fuera(fx) -> bool:
    """¿Es una sombra NUEVA (Efectos → Sombra, con «angle»)? Esa sale POR FUERA de la caja: el clip no se encoge (como
    en Resolve). Las de antes (Escenas, overlay, proyectos guardados: sin «angle») encogen la imagen, como siempre."""
    s = (fx or {}).get("shadow")
    return isinstance(s, dict) and "angle" in s


def _ampliar(box: dict, mx: float, my: float, W: int, H: int) -> dict:
    b = dict(box)
    bw, bh = float(b.get("w", 1.0)) * W, float(b.get("h", 1.0)) * H
    b.update(x=float(b.get("x", 0.0)) - mx / W, y=float(b.get("y", 0.0)) - my / H, w=float(b.get("w", 1.0)) + 2 * mx / W,
             h=float(b.get("h", 1.0)) + 2 * my / H)
    cr = b.get("crop")
    if cr:                          # (el recorte sigue escondiendo lo mismo del clip: fracciones de la caja nueva)
        cr = dict(cr)
        for k, lado, m in (("l", bw, mx), ("r", bw, mx), ("t", bh, my), ("b", bh, my)):
            v = float(cr.get(k, 0) or 0)
            if v > 1e-6:
                cr[k] = round((m + v * lado) / (lado + 2 * m), 6)
        b["crop"] = cr
    return b


def caja_con_sombra(box, fx, W: int, H: int):
    """La caja del clip agrandada por el margen de una sombra NUEVA (luego decor la encoge ese mismo margen: el clip
    queda del tamaño y en el sitio de siempre y la sombra sale por fuera). Sin sombra nueva, la caja tal cual."""
    if not sombra_por_fuera(fx):
        return box
    m, _ow = margins(fx, W, H)
    if m <= 0:
        return box
    from . import transform
    return _ampliar(dict(box or transform.FULL), m, m, W, H)


def para_exportar(project, W: int, H: int):
    """El proyecto para exportar con la caja (y sus claves animadas) de cada clip con sombra NUEVA agrandada por su
    margen (ver caja_con_sombra). Sin ninguna, el mismo proyecto (sin copiar nada)."""
    import copy
    suyos = [c for c in project.clips.values() if sombra_por_fuera(c.fx)]
    if not suyos:
        return project
    q = copy.copy(project)
    for k in ("_lect", "_lect_rev"):
        q.__dict__.pop(k, None)
    q.clips = dict(project.clips)
    for c in suyos:
        m, _ow = margins(c.fx, W, H)
        if m <= 0:
            continue
        n = copy.copy(c)
        n.layout = caja_con_sombra(c.layout, c.fx, W, H)
        if getattr(c, "layout_kf", None):
            n.layout_kf = [_ampliar(k, m, m, W, H) if all(x in k for x in ("x", "y", "w", "h")) else dict(k)
                           for k in c.layout_kf]
        q.clips[c.id] = n
    return q


def offset_at(fx, local_t: float, bx: float, by: float, bw: float, bh: float, W: int, H: int):
    """En el visor: (dx, dy, opacidad) de la entrada en el instante local_t (0 = empieza el clip)."""
    e = enter_of(fx)
    if e is None:
        return 0.0, 0.0, 1.0
    k = 1 - ease(local_t / max(0.05, float(e.get("dur", 0.45))))
    f = e["from"]
    if f == "right":
        return (W - bx) * k, 0.0, 1.0
    if f == "left":
        return -(bx + bw) * k, 0.0, 1.0
    if f == "bottom":
        return 0.0, (H - by) * k, 1.0
    if f == "top":
        return 0.0, -(by + bh) * k, 1.0
    return 0.0, 0.0, 1 - k            # fade


def ffmpeg_xy(fx, start: float, bx: int, by: int, bw: int, bh: int) -> tuple[str, str] | None:
    """Al exportar: expresiones x/y del overlay para la entrada deslizando (None si no se mueve)."""
    e = enter_of(fx)
    if e is None or e["from"] == "fade":
        return None
    d = max(0.05, float(e.get("dur", 0.45)))
    k = f"(1-(1-pow(1-clip((t-{start:.3f})/{d:.3f},0,1),3)))"
    f = e["from"]
    if f == "right":
        return f"'{bx}+(W-{bx})*{k}'", str(by)
    if f == "left":
        return f"'{bx}-({bx}+{bw})*{k}'", str(by)
    if f == "bottom":
        return str(bx), f"'{by}+(H-{by})*{k}'"
    return str(bx), f"'{by}-({by}+{bh})*{k}'"


def blur_px(sh: dict, short: int, w: float, h: float, m: int) -> int:
    """Radio del desenfoque de la sombra en píxeles (el mismo en el visor y al exportar: boxblur de FFmpeg)."""
    return max(1, min(int(sh["blur"] * short), int(min(w, h) + 2 * m) // 2 - 1))


def ffmpeg_frame(k: int, fx, cw: int, ch: int, W: int, H: int, src: str) -> tuple[list[str], int, int]:
    """Contorno + sombra alrededor de una imagen ya escalada a cw×ch (entrada [src]). Devuelve (filtros que
    terminan en [dec{k}], ancho, alto) con transparencia alrededor."""
    m, ow = margins(fx, W, H)
    ol = outline_of(fx)
    sh = shadow_of(fx)
    short = min(W, H)
    w, h = cw + 2 * ow, ch + 2 * ow
    first = f"[{src}]"
    if ol:
        col = ol["color"].lstrip("#")
        first += f"pad={w}:{h}:{ow}:{ow}:color=0x{col},"
    if not sh:
        return [first + f"format=yuva420p[dec{k}]"], w, h
    dx, dy = int(round(sh["dx"] * short)), int(round(sh["dy"] * short))
    blur = blur_px(sh, short, w, h, m)
    # (la forma: el ALFA de la imagen —un PNG recortado da su silueta—; el color, en todo el lienzo de la sombra —también
    #  en lo transparente de alrededor— para que al desenfocar el borde no se oscurezca)
    col = sh.get("color", COLOR_SOMBRA)
    if col == COLOR_SOMBRA:            # (negro: la cadena de siempre, igual que antes)
        tinte, fondo = "", "black@0"
    else:
        r_, g_, b_ = (int(col[i:i + 2], 16) for i in (1, 3, 5))
        tinte, fondo = f"lutrgb=r={r_}:g={g_}:b={b_},", f"0x{col[1:]}@0"
    out = [first + f"format=rgba,split=2[dcc{k}][dcs{k}]",
           f"[dcs{k}]colorchannelmixer=rr=0:gg=0:bb=0:ra=0:ga=0:ba=0:aa={float(sh['opacity']):.3f},{tinte}"
           f"format=yuva420p,pad={w + 2 * m}:{h + 2 * m}:{m + dx}:{m + dy}:color={fondo},"
           f"boxblur=luma_radius={blur}:luma_power=1:chroma_radius={blur}:alpha_radius={blur}[dsh{k}]",
           f"[dsh{k}][dcc{k}]overlay={m}:{m}:format=auto,format=yuva420p[dec{k}]"]
    return out, w + 2 * m, h + 2 * m
