"""
Curvas (fotogramas clave) de VOLUMEN y OPACIDAD de un clip, y modos de fusión.

Clip.vol_kf / Clip.op_kf = [{"t": segundo DEL ARCHIVO, "v": valor}] (como el zoom: al dividir, recortar o
mover el clip, los puntos siguen pegados a su imagen/sonido). Volumen: 0–2 (1 = igual, multiplica a
Clip.volume). Opacidad: 0–1. Entre puntos, línea recta; antes del primero y después del último, su valor.
Clip.blend = "normal" | "screen" | "multiply" | … (modo de fusión con lo que hay debajo).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

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


def _t(k: dict) -> float:
    return k["t"]


def ordenada(kf: list[dict]) -> bool:
    return all(a["t"] <= b["t"] for a, b in zip(kf, kf[1:]))


def value_at(kf: list[dict], s: float, default: float = 1.0) -> float:
    """El valor de la curva en el segundo s. ⚡ Las curvas se guardan ORDENADAS (upsert, voz pareja y podar() tras cada
    edición): con muchos puntos se busca por bisección; las cortas (≤ 16) se ordenan aquí por si acaso."""
    if not kf:
        return default
    pts = kf if len(kf) > 16 else sorted(kf, key=_t)
    if s <= pts[0]["t"]:
        return float(pts[0]["v"])
    if s > pts[-1]["t"]:
        return float(pts[-1]["v"])
    i = bisect_left(pts, s, key=_t)            # (el primer punto con t ≥ s; i ≥ 1)
    a, b = pts[i - 1], pts[i]
    u = (s - a["t"]) / max(b["t"] - a["t"], 1e-9)
    return float(a["v"]) + (float(b["v"]) - float(a["v"])) * u


def recortar(kf: list[dict], a: float, b: float) -> list[dict]:
    """Solo los puntos del tramo [a, b] (segundos del archivo) y, a cada lado, el vecino que hace falta para que la curva
    sea IDÉNTICA dentro del tramo (si ya hay un punto justo en el borde, ninguno). Copias nuevas, ordenadas."""
    pts = kf if ordenada(kf) else sorted(kf, key=_t)
    i0 = bisect_left(pts, a, key=_t)           # (el primero con t ≥ a)
    i1 = bisect_right(pts, b, key=_t)          # (el primero con t > b)
    if i0 > 0 and not (i0 < len(pts) and pts[i0]["t"] == a):
        i0 -= 1
    if i1 < len(pts) and not (i1 > 0 and pts[i1 - 1]["t"] == b):
        i1 += 1
    return [dict(k) for k in pts[i0:i1]]


def podar(p) -> int:
    """⚡ Tras cada edición (controller._edit) y al abrir un proyecto: las curvas de volumen y opacidad, ORDENADAS, y la
    de volumen de cada clip con sonido, solo con los puntos de SU tramo del archivo (más el borde: la ganancia en cada
    instante no cambia). Así, al dividir, recortar o eliminar silencios cada pieza se queda con lo suyo (antes, todas
    con la curva ENTERA: cientos de copias en el proyecto y el historial, y una exportación imposible). Devuelve
    cuántos clips cambió."""
    from .model import KIND_IMAGE
    n = 0
    visto = _VISTO
    if len(visto) > 4 * len(p.clips) + 2000:
        visto.clear()
    for c in p.clips.values():
        vk, ok = c.vol_kf, c.op_kf
        if not vk and not ok:
            continue
        # ⚡ (< 2 ms con 3000 clips) lo ya mirado y sin cambios se salta: mismas listas (guardadas aquí: su id no se
        #    reutiliza), mismo largo y mismo tramo. (Las curvas se cambian poniendo listas nuevas, nunca por dentro.)
        firma = (vk, ok, len(vk or ()), len(ok or ()), c.source_in, c.duration, c.speed, c.media_id)
        if visto.get(c.id) == firma:
            continue
        cambio = False
        if ok and not ordenada(ok):
            c.op_kf = sorted((dict(k) for k in ok), key=_t)
            cambio = True
        if vk:
            if not ordenada(vk):
                vk = c.vol_kf = sorted((dict(k) for k in vk), key=_t)
                cambio = True
            m = p.media.get(c.media_id) if c.media_id else None
            if m is not None and m.kind != KIND_IMAGE and len(vk) > 2:
                a = float(c.source_in)
                b = a + max(0.0, float(c.src_len))
                # (¿sobra algo? más de un punto antes del tramo o más de uno después)
                if (len(vk) > 1 and vk[1]["t"] < a) or (len(vk) > 1 and vk[-2]["t"] > b):
                    c.vol_kf = recortar(vk, a, b)
                    cambio = True
        visto[c.id] = (c.vol_kf, c.op_kf, len(c.vol_kf or ()), len(c.op_kf or ()), c.source_in, c.duration, c.speed,
                       c.media_id)
        n += cambio
    return n


_VISTO: dict = {}         # id del clip → firma de lo último que miró podar()


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


def _pend(x: float) -> str:
    return f"{x:.9f}".rstrip("0").rstrip(".") or "0"


def ffmpeg_expr(kf: list[dict], s_expr: str, default: float = 1.0, a: float | None = None,
                b: float | None = None) -> str:
    """Expresión de FFmpeg con el valor de la curva en función de S (texto con el segundo del archivo).
    a, b: el tramo del archivo que usa el clip: solo van sus puntos (y el vecino de cada lado para interpolar).
    ⚡ En ÁRBOL (21/11): if(lt(S, mitad), izquierda, derecha), con log2(n) niveles; antes era un if() por punto, uno dentro
    de otro, y FFmpeg no pasa de ~100 niveles («Error initializing filters: Invalid argument» con 100 puntos o más)."""
    if not kf:
        return _num(default)
    pts = kf if ordenada(kf) else sorted(kf, key=_t)
    if a is not None and b is not None:
        pts = recortar(pts, a, b)
    n = len(pts)
    if n == 1:
        return _num(pts[0]["v"])
    # trozo 0: antes del primer punto · trozo k (1…n-1): recta de pts[k-1] a pts[k] · trozo n: después del último.
    # El trozo k vale mientras S < pts[k].t (como antes: en el punto justo, el trozo siguiente; la curva es continua).
    trozos = [_num(pts[0]["v"])]
    for p0, p1 in zip(pts, pts[1:]):
        dv = float(p1["v"]) - float(p0["v"])
        if abs(dv) < 1e-12:
            trozos.append(_num(p0["v"]))
        else:
            slope = dv / max(p1["t"] - p0["t"], 1e-9)
            trozos.append(f"({_num(p0['v'])}+({s_expr}-{_num(p0['t'])})*({_pend(slope)}))")
    trozos.append(_num(pts[-1]["v"]))

    def arbol(lo: int, hi: int) -> str:
        if lo == hi:
            return trozos[lo]
        mid = (lo + hi + 1) // 2               # (izquierda lo…mid-1: S < pts[mid-1].t; derecha mid…hi)
        return f"if(lt({s_expr},{_num(pts[mid - 1]['t'])}),{arbol(lo, mid - 1)},{arbol(mid, hi)})"
    return arbol(0, n)


def tramo(c: Clip, is_image: bool = False) -> tuple[float, float]:
    """El tramo de la curva que usa el clip: segundos del archivo (en una imagen, desde su inicio)."""
    if is_image:
        return 0.0, max(0.0, float(c.duration))
    a = float(c.source_in)
    return a, a + max(0.0, float(c.src_len))


def s_of_t(c: Clip, t_var: str, is_image: bool = False) -> str:
    """Segundo del archivo en función del tiempo local del filtro (t_var: «t» o «T»)."""
    if is_image:
        return t_var
    if c.speed <= 0:
        return _num(c.source_in)
    if c.reverse:
        return f"({_num(c.source_in + c.src_len)}-{t_var}*{_num(c.speed)})"
    return f"({_num(c.source_in)}+{t_var}*{_num(c.speed)})"
