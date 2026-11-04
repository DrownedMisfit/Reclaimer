"""
Detalles de una imagen o video puesto ENCIMA de otro (como lo haces en Resolve): entrada animada, sombra suave y
contorno. Lo mismo en el visor y al exportar.

  fx["enter"]   = {"from": "right"|"left"|"bottom"|"top"|"fade", "dur": 0.45}
  fx["shadow"]  = {"opacity": 0.6, "blur": 0.02, "dx": 0.008, "dy": 0.012}   (fracciones del lado corto)
  fx["outline"] = {"width": 0.006, "color": "#FFFFFF"}
"""
from __future__ import annotations

ENTRANCES = {"right": "desde la derecha", "left": "desde la izquierda", "bottom": "desde abajo",
             "top": "desde arriba", "fade": "apareciendo suave"}
SHADOW = {"opacity": 0.6, "blur": 0.02, "dx": 0.008, "dy": 0.012}
OUTLINE = {"width": 0.006, "color": "#FFFFFF"}


def enter_of(fx) -> dict | None:
    e = (fx or {}).get("enter")
    return e if isinstance(e, dict) and e.get("from") in ENTRANCES else None


def shadow_of(fx) -> dict | None:
    s = (fx or {}).get("shadow")
    return dict(SHADOW, **s) if isinstance(s, dict) else None


def outline_of(fx) -> dict | None:
    o = (fx or {}).get("outline")
    return dict(OUTLINE, **o) if isinstance(o, dict) else None


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
    blur = max(1, min(int(sh["blur"] * short), (min(w, h) + 2 * m) // 2 - 1))
    out = [first + f"format=rgba,split=2[dcc{k}][dcs{k}]",
           f"[dcs{k}]colorchannelmixer=rr=0:gg=0:bb=0:ra=0:ga=0:ba=0:aa={float(sh['opacity']):.3f},format=yuva420p,"
           f"pad={w + 2 * m}:{h + 2 * m}:{m + dx}:{m + dy}:color=black@0,"
           f"boxblur=luma_radius={blur}:luma_power=1:chroma_radius={blur}:alpha_radius={blur}[dsh{k}]",
           f"[dsh{k}][dcc{k}]overlay={m}:{m}:format=auto,format=yuva420p[dec{k}]"]
    return out, w + 2 * m, h + 2 * m
