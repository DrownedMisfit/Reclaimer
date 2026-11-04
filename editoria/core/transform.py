"""
Encuadre de los clips: ZOOM animado y DISPOSICIÓN en pantalla.

Zoom (fotogramas clave):
  Cada fotograma clave dice, en un momento del ARCHIVO ORIGINAL, cuánto zoom hay
  y a qué punto se mira: {"t": segundo del archivo, "z": 1.0–6.0, "x": 0–1, "y": 0–1}.
  Opcional "i": "linear" (paso uniforme hasta la siguiente clave; lo usa el tracking).
  Se guardan en tiempo del archivo (no de la timeline) para que sigan pegados al
  contenido aunque recortes o muevas el clip. Entre dos claves el paso es suave.

Disposición:
  Dónde va el clip en la pantalla: {"x", "y", "w", "h"} en fracciones de la pantalla
  y "fit": "contain" (se ve entero, con bandas), "cover" (llena la caja, recortando) o
  "stretch" (↔ deformado: la imagen se estira o se aplasta hasta llenar la caja exacta).
"""
from __future__ import annotations

FULL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "contain"}

LAYOUTS = {
    "Pantalla completa": FULL,
    "Mitad izquierda": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0, "fit": "cover"},
    "Mitad derecha": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0, "fit": "cover"},
    "Mitad izquierda (entero)": {"x": 0.0, "y": 0.25, "w": 0.5, "h": 0.5, "fit": "contain"},
    "Mitad derecha (entero)": {"x": 0.5, "y": 0.25, "w": 0.5, "h": 0.5, "fit": "contain"},
    "Mitad superior": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.5, "fit": "cover"},
    "Mitad inferior": {"x": 0.0, "y": 0.5, "w": 1.0, "h": 0.5, "fit": "cover"},
    "Esquina (imagen en imagen)": {"x": 0.66, "y": 0.05, "w": 0.3, "h": 0.3, "fit": "contain"},
    # Edits: el clip en el centro y arriba/abajo copias del mismo clip (como el original, sin voltear),
    # borrosas y algo oscuras. Con "flip": las copias van en espejo (volteadas).
    "Vertical con copias arriba y abajo": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "mirrorfill"},
    "Vertical con reflejo (espejo)": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "mirrorfill", "flip": True},
    # Capturas (tuits, páginas web…) encima del video, en el centro
    "Centro (superpuesta)": {"x": 0.07, "y": 0.3, "w": 0.86, "h": 0.4, "fit": "contain", "bg": "none"},
}
# Shorts: el clip horizontal entero en el centro y, detrás, el mismo clip ampliado y desenfocado. Ya no se ofrece en
# «En pantalla» (lo mismo, y ajustable, es ▦ Relleno); lo siguen usando los Shorts de la IA y los proyectos antiguos.
BLURFILL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "blurfill"}
HIDDEN_LAYOUTS = {"Vertical con fondo desenfocado": BLURFILL}   # solo se ve en la lista si el clip ya lo tiene
MIRROR = LAYOUTS["Vertical con copias arriba y abajo"]
MIRROR_FLIP = LAYOUTS["Vertical con reflejo (espejo)"]

# ⊞ Composición: cuántos huecos y cómo (columnas, filas) en horizontal; en vertical se giran
COMP_GRIDS = {2: (2, 1), 3: (3, 1), 4: (2, 2), 6: (3, 2), 9: (3, 3)}


def comp_slots(n: int, W: int, H: int, gap: float = 0.02) -> list[dict]:
    """Los huecos de una composición de n (2, 3, 4, 6 o 9) en fracciones del lienzo, con un pequeño margen."""
    cols, rows = COMP_GRIDS.get(n, (2, 2))
    if H > W:
        cols, rows = rows, cols          # vertical (Shorts): unos encima de otros
    out = []
    w = (1 - gap * (cols + 1)) / cols
    h = (1 - gap * (rows + 1)) / rows
    for r in range(rows):
        for c in range(cols):
            out.append({"x": round(gap + c * (w + gap), 4), "y": round(gap + r * (h + gap), 4),
                        "w": round(w, 4), "h": round(h, 4), "fit": "cover"})
    return out


MAX_ZOOM = 6.0


def smooth(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def sorted_kf(kf: list[dict]) -> list[dict]:
    return sorted(kf, key=lambda k: k["t"])


def value_at(kf: list[dict], t: float) -> tuple[float, float, float]:
    """(zoom, x, y) en el segundo t del archivo original."""
    if not kf:
        return 1.0, 0.5, 0.5
    kf = sorted_kf(kf)
    if t <= kf[0]["t"]:
        k = kf[0]
        return k["z"], k["x"], k["y"]
    if t >= kf[-1]["t"]:
        k = kf[-1]
        return k["z"], k["x"], k["y"]
    for a, b in zip(kf, kf[1:]):
        if a["t"] <= t <= b["t"]:
            u = (t - a["t"]) / max(b["t"] - a["t"], 1e-6)
            u = u if a.get("i") == "linear" else smooth(u)
            return tuple(a[k] + (b[k] - a[k]) * u for k in ("z", "x", "y"))  # type: ignore[return-value]
    k = kf[-1]
    return k["z"], k["x"], k["y"]


def window(z: float, x: float, y: float) -> tuple[float, float, float]:
    """Ventana visible del archivo (izquierda, arriba, tamaño), en fracciones 0–1."""
    z = max(1.0, z)
    size = 1.0 / z
    left = min(max(x - size / 2, 0.0), 1.0 - size)
    top = min(max(y - size / 2, 0.0), 1.0 - size)
    return left, top, size


def is_zoomed(kf: list[dict]) -> bool:
    return any(k["z"] > 1.001 for k in kf)


def upsert(kf: list[dict], t: float, z: float, x: float, y: float, tol: float = 0.05) -> list[dict]:
    # (las claves que pone el usuario a mano usan paso suave)
    """Pone (o cambia) un fotograma clave en el momento t."""
    out = [dict(k) for k in kf if abs(k["t"] - t) > tol]
    out.append({"t": round(t, 3), "z": round(min(max(z, 1.0), MAX_ZOOM), 4),
                "x": round(min(max(x, 0.0), 1.0), 4), "y": round(min(max(y, 0.0), 1.0), 4)})
    return sorted_kf(out)


def simplify(kf: list[dict], tol: float = 0.01) -> list[dict]:
    """Quita fotogramas clave que casi no aportan (los que genera el tracking son muchos)."""
    kf = sorted_kf(kf)
    if len(kf) <= 2:
        return kf
    out = [kf[0]]
    for i in range(1, len(kf) - 1):
        a, b, c = out[-1], kf[i], kf[i + 1]
        u = (b["t"] - a["t"]) / max(c["t"] - a["t"], 1e-6)
        pred = {k: a[k] + (c[k] - a[k]) * u for k in ("z", "x", "y")}
        if any(abs(pred[k] - b[k]) > tol * (1 if k != "z" else 3) for k in ("z", "x", "y")):
            out.append(b)
    out.append(kf[-1])
    return out


# ------------------------------------------------------------- FFmpeg
def _num(v: float) -> str:
    return f"{v:.5f}".rstrip("0").rstrip(".") or "0"


def ffmpeg_expr(kf: list[dict], key: str, tvar: str) -> str:
    """Expresión de FFmpeg con el valor animado (misma curva suave que el visor).
    Suma de tramos (sin anidar) para que funcione con cientos de fotogramas clave."""
    kf = sorted_kf(kf)
    if len(kf) == 1:
        return _num(kf[0][key])
    terms = [f"lt({tvar},{_num(kf[0]['t'])})*{_num(kf[0][key])}",
             f"gte({tvar},{_num(kf[-1]['t'])})*{_num(kf[-1][key])}"]
    for a, b in zip(kf, kf[1:]):
        if b["t"] - a["t"] < 1e-4:
            continue
        va, dv = a[key], b[key] - a[key]
        if abs(dv) < 1e-6:
            terms.append(f"gte({tvar},{_num(a['t'])})*lt({tvar},{_num(b['t'])})*{_num(va)}")
            continue
        u = f"(({tvar}-{_num(a['t'])})/{_num(b['t'] - a['t'])})"
        curve = u if a.get("i") == "linear" else f"{u}*{u}*(3-2*{u})"
        terms.append(f"gte({tvar},{_num(a['t'])})*lt({tvar},{_num(b['t'])})*"
                     f"({_num(va)}+{_num(dv)}*{curve})")
    return "+".join(terms)


def zoompan_filter(kf: list[dict], source_in: float, out_w: int, out_h: int, fps: str,
                   speed: float = 1.0, reverse: bool = False, src_len: float = 0.0) -> str:
    """Filtro zoompan: el tiempo del archivo es source_in + tiempo dentro del clip (× su velocidad;
    hacia atrás se cuenta desde el final; congelado = siempre el mismo instante)."""
    if speed <= 0:
        t = f"({_num(source_in)})"
    elif reverse:
        t = f"({_num(source_in + src_len)}-in_time*{_num(speed)})"
    elif speed != 1.0:
        t = f"(in_time*{_num(speed)}+{_num(source_in)})"
    else:
        t = f"(in_time+{_num(source_in)})"
    z = ffmpeg_expr(kf, "z", t)
    x = ffmpeg_expr(kf, "x", t)
    y = ffmpeg_expr(kf, "y", t)
    return (f"zoompan=z='max(1,{z})':"
            f"x='max(0,min(iw-iw/zoom,({x})*iw-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,({y})*ih-ih/zoom/2))':"
            f"d=1:s={out_w}x{out_h}:fps={fps}")


def even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def fit_size(src_w: int, src_h: int, box_w: int, box_h: int, fit: str) -> tuple[int, int]:
    """Tamaño al que se escala el clip para caber (contain) o llenar (cover) la caja."""
    if src_w <= 0 or src_h <= 0 or fit == "stretch":
        return even(box_w), even(box_h)
    s = (max if fit == "cover" else min)(box_w / src_w, box_h / src_h)
    return even(src_w * s), even(src_h * s)


# ------------------------------------------------------------------ 🎞 posición y tamaño animados (fotogramas clave)
LAYOUT_KEYS = ("x", "y", "w", "h")


def _ease(u: float, kind: str | None) -> float:
    u = min(max(u, 0.0), 1.0)
    return u if kind == "linear" else u * u * (3 - 2 * u)      # por defecto: suave al salir y al llegar


def layout_value_at(kf: list[dict], s: float) -> dict:
    """x, y, w, h en el segundo s (del archivo; en imágenes, desde el inicio del clip)."""
    pts = sorted(kf, key=lambda k: k["t"])
    if s <= pts[0]["t"]:
        return {k: float(pts[0][k]) for k in LAYOUT_KEYS}
    for a, b in zip(pts, pts[1:]):
        if s <= b["t"]:
            u = _ease((s - a["t"]) / max(b["t"] - a["t"], 1e-9), a.get("i"))
            return {k: float(a[k]) + (float(b[k]) - float(a[k])) * u for k in LAYOUT_KEYS}
    return {k: float(pts[-1][k]) for k in LAYOUT_KEYS}


def rot_of(box: dict | None) -> float:
    """⟳ Giro de la capa (grados, como «Ángulo de rotación» de Resolve)."""
    try:
        return float((box or {}).get("rot", 0) or 0) % 360
    except (TypeError, ValueError):
        return 0.0


def rot_size(bw: int, bh: int) -> int:
    """Lado del lienzo cuadrado donde cabe la capa girada sin cortarse."""
    import math
    return even(math.hypot(bw, bh) + 2)


def content_box(box: dict, src_w: int, src_h: int, W: int, H: int) -> dict:
    """La parte de la caja donde se VE la imagen (sin bandas), en fracciones de pantalla."""
    b = dict(box)
    if b.get("fit") in ("stretch", "cover") or src_w <= 0 or src_h <= 0:
        return b
    bw, bh = b["w"] * W, b["h"] * H
    s = min(bw / src_w, bh / src_h)
    cw, ch = src_w * s, src_h * s
    b.update(x=b["x"] + (bw - cw) / 2 / W, y=b["y"] + (bh - ch) / 2 / H, w=cw / W, h=ch / H)
    return b


def follow_at(box: dict | None, s: float) -> float | None:
    """🎯 Encuadre que sigue la acción: centro horizontal (0–1 del clip) del recorte en el segundo s del archivo.
    Solo cuenta con «fit» = «cover» (llenar recortando los lados). None = recorte centrado."""
    kf = (box or {}).get("follow") or []
    if not kf or (box or {}).get("fit") != "cover":
        return None
    pts = sorted(kf, key=lambda k: k["t"])
    if s <= pts[0]["t"]:
        return float(pts[0]["x"])
    for a, b in zip(pts, pts[1:]):
        if s <= b["t"]:
            u = _ease((s - a["t"]) / max(b["t"] - a["t"], 1e-9), a.get("i"))
            return float(a["x"]) + (float(b["x"]) - float(a["x"])) * u
    return float(pts[-1]["x"])


LIVE: dict = {}       # clip_id → caja mientras la arrastras en el visor (solo para verla; se guarda al soltar)


def layout_at(c, local: float, is_image: bool = False) -> dict | None:
    """La disposición del clip en ese momento (local = segundos desde que empieza el clip)."""
    if c.id in LIVE:
        return LIVE[c.id]
    if not getattr(c, "layout_kf", None):
        return c.layout
    s = local if is_image else c.src_at(min(max(local, 0.0), c.duration))
    box = dict(c.layout or FULL)
    box.update({k: round(v, 5) for k, v in layout_value_at(c.layout_kf, s).items()})
    return box


def layout_upsert(kf: list[dict], s: float, box: dict, tol: float = 0.02) -> list[dict]:
    out = [dict(k) for k in kf if abs(k["t"] - s) > tol]
    out.append({"t": round(s, 4), **{k: round(float(box.get(k, FULL[k])), 4) for k in LAYOUT_KEYS}})
    return sorted(out, key=lambda k: k["t"])


def layout_max(c) -> tuple[float, float]:
    """El tamaño más grande que llega a tener (al exportar se dibuja a ese tamaño y se reduce: sin perder nitidez)."""
    kf = getattr(c, "layout_kf", None) or []
    box = c.layout or FULL
    if not kf:
        return float(box["w"]), float(box["h"])
    return max(float(k["w"]) for k in kf), max(float(k["h"]) for k in kf)


def _n(x: float) -> str:
    return f"{x:.5f}".rstrip("0").rstrip(".") or "0"


def layout_expr(kf: list[dict], key: str, s_expr: str) -> str:
    """Expresión de FFmpeg con el valor de x / y / w / h según S (texto con el segundo del archivo)."""
    pts = sorted(kf, key=lambda k: k["t"])
    expr = _n(float(pts[-1][key]))
    for a, b in reversed(list(zip(pts, pts[1:]))):
        va, vb = float(a[key]), float(b[key])
        u = f"(({s_expr}-{_n(a['t'])})/{_n(max(b['t'] - a['t'], 1e-6))})"
        e = u if a.get("i") == "linear" else f"({u}*{u}*(3-2*{u}))"
        expr = f"if(lt({s_expr},{_n(b['t'])}),{_n(va)}+({_n(vb - va)})*{e},{expr})"
    return f"if(lt({s_expr},{_n(pts[0]['t'])}),{_n(float(pts[0][key]))},{expr})"

