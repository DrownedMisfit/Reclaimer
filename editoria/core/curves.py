"""
Curvas (fotogramas clave) de VOLUMEN y OPACIDAD de un clip, y modos de fusión.

Clip.vol_kf / Clip.op_kf = [{"t": segundo DEL ARCHIVO, "v": valor}] (como el zoom: al dividir, recortar o
mover el clip, los puntos siguen pegados a su imagen/sonido). Volumen: 0–2 (1 = igual, multiplica a
Clip.volume). Opacidad: 0–1. Entre puntos, línea recta; antes del primero y después del último, su valor.
Clip.blend = "normal" | "screen" | "multiply" | … (modo de fusión con lo que hay debajo).
"""
from __future__ import annotations

from .model import Clip

BLEND_MODES = [  # (clave, nombre, modo de FFmpeg «blend», modo de QPainter)
    ("normal", "Normal", None, "SourceOver"),
    ("screen", "Pantalla (aclara: luces, destellos)", "screen", "Screen"),
    ("add", "Añadir (brillo intenso)", "addition", "Plus"),
    ("lighten", "Aclarar", "lighten", "Lighten"),
    ("multiply", "Multiplicar (oscurece: sombras, texturas)", "multiply", "Multiply"),
    ("darken", "Oscurecer", "darken", "Darken"),
    ("overlay", "Superponer (más contraste)", "overlay", "Overlay"),
    ("softlight", "Luz suave", "softlight", "SoftLight"),
    ("difference", "Diferencia", "difference", "Difference"),
]
BLEND_FFMPEG = {k: f for k, _n, f, _q in BLEND_MODES}
BLEND_QT = {k: q for k, _n, _f, q in BLEND_MODES}


def value_at(kf: list[dict], s: float, default: float = 1.0) -> float:
    if not kf:
        return default
    pts = sorted(kf, key=lambda k: k["t"])
    if s <= pts[0]["t"]:
        return float(pts[0]["v"])
    for a, b in zip(pts, pts[1:]):
        if s <= b["t"]:
            u = (s - a["t"]) / max(b["t"] - a["t"], 1e-9)
            return float(a["v"]) + (float(b["v"]) - float(a["v"])) * u
    return float(pts[-1]["v"])


def src_time(c: Clip, local: float, is_image: bool = False) -> float:
    return local if is_image else c.src_at(local)


def gain(c: Clip, t: float, is_image: bool = False) -> float:
    """Volumen del clip en el instante t de la timeline (Clip.volume × curva)."""
    return c.volume * value_at(c.vol_kf, src_time(c, t - c.start, is_image))


def opacity(c: Clip, t: float, is_image: bool = False) -> float:
    return c.opacity * value_at(c.op_kf, src_time(c, t - c.start, is_image))


def upsert(kf: list[dict], s: float, v: float, tol: float = 0.02) -> list[dict]:
    out = [dict(k) for k in kf if abs(k["t"] - s) > tol]
    out.append({"t": round(s, 4), "v": round(v, 4)})
    return sorted(out, key=lambda k: k["t"])


def _num(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def ffmpeg_expr(kf: list[dict], s_expr: str, default: float = 1.0) -> str:
    """Expresión de FFmpeg con el valor de la curva en función de S (texto con el segundo del archivo)."""
    if not kf:
        return _num(default)
    pts = sorted(kf, key=lambda k: k["t"])
    expr = _num(pts[-1]["v"])
    for a, b in reversed(list(zip(pts, pts[1:]))):
        slope = (float(b["v"]) - float(a["v"])) / max(b["t"] - a["t"], 1e-9)
        seg = f"({_num(a['v'])}+({s_expr}-{_num(a['t'])})*({_num(slope)}))"
        expr = f"if(lt({s_expr},{_num(b['t'])}),{seg},{expr})"
    return f"if(lt({s_expr},{_num(pts[0]['t'])}),{_num(pts[0]['v'])},{expr})"


def s_of_t(c: Clip, t_var: str, is_image: bool = False) -> str:
    """Segundo del archivo en función del tiempo local del filtro (t_var: «t» o «T»)."""
    if is_image:
        return t_var
    if c.speed <= 0:
        return _num(c.source_in)
    if c.reverse:
        return f"({_num(c.source_in + c.src_len)}-{t_var}*{_num(c.speed)})"
    return f"({_num(c.source_in)}+{t_var}*{_num(c.speed)})"
