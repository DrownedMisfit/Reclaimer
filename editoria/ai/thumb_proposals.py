"""
Módulo de IA: PROPUESTAS DE MINIATURA y TEXTOS CORTOS.

  suggest_texts(título, temas, …) → frases cortas para la miniatura (no el título: algo que se lea de un
                                     vistazo, p. ej. «¿DÓNDE ESTÁN?» para un video sobre lo que falta)
  proposals(fmt, fotogramas, texto, estilo) → composiciones A/B/C listas para editar

Las propuestas usan tus preferencias (lo que cambias en ellas se recuerda: fuente, tamaño, lado del texto)
y, cuando exista, el estilo aprendido de tus miniaturas. La IA propone; tú decides.
"""
from __future__ import annotations

import re
import unicodedata

import cv2
import numpy as np
from PySide6.QtGui import QImage

from ..core import thumbnail as T

STOP = set("""el la los las un una unos unas de del al y o que en por para con sin se su sus lo le es son fue era
este esta estos estas ese esa eso esto más mas muy ya no sí si como pero todo toda todos todas otra otro otras
otros hay qué cómo por qué cuando donde quien sobre entre hasta desde también nuevo nueva video""".split())

# (palabras que lo delatan, frases propuestas — {X} = el nombre principal)
PATTERNS = [
    (r"\b(falta|faltan|sin|desaparec|perdi|quitaron|elimin)", ["¿DÓNDE ESTÁN?", "FALTA ALGO", "¿Y {X}?"]),
    (r"\b(mal|peor|malo|basura|decepci|fracas|error|problema|horrible|roto|desastre)",
     ["¿QUÉ PASÓ?", "TODO MAL", "{X} FALLÓ", "¿POR QUÉ?"]),
    (r"\b(vs|versus|contra|compar|remake|original|antes|ahora|diferencia)",
     ["ANTES vs AHORA", "¿MEJOR O PEOR?", "NO ES IGUAL"]),
    (r"\b(mejor|increíble|incre[ií]ble|bueno|obra maestra|perfect|brutal)", ["¡POR FIN!", "ESTO SÍ", "{X} LO LOGRÓ"]),
    (r"\b(anunci|despid|precio|sube|subi|cierr|cancel|oficial|filtr|leak)", ["¿OTRA VEZ?", "ES OFICIAL", "{X}… ¿EN SERIO?"]),
    (r"\b(woke|pol[ií]tic|censur)", ["¿POR QUÉ?", "SE PASARON", "{X} CAMBIÓ"]),
]


def _norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch))


CONNECT = {"of", "de", "del", "the", "la", "el", "los", "las"}


def main_name(title: str) -> str:
    """El nombre principal del título (el juego, la saga, la empresa…): el primer nombre propio.
    «Elden Ring Nightreign…» → ELDEN RING · «Nintendo sube los precios NUEVAMENTE» → NINTENDO ·
    «Resident Evil 9 no aporta…» → RESIDENT EVIL 9. Las palabras en MAYÚSCULAS que solo son énfasis
    (NUEVAMENTE, VISCERAL) no cuentan."""
    tokens = re.findall(r"[\w'’\-]+|[^\w\s]", title)
    seq: list[str] = []
    for i, tok in enumerate(tokens):
        word = re.sub(r"[^\w\-]", "", tok)
        is_cap = bool(word) and (word[0].isupper() or word[0].isdigit())
        emphasis = word.isupper() and len(word) > 5 and i > 0 and _norm(word) not in ("", )
        if is_cap and not emphasis and (_norm(word) not in STOP or i == 0 and word[0].isupper() and
                                        _norm(word) not in STOP):
            seq.append(word)
        elif seq and _norm(word) in CONNECT and i + 1 < len(tokens) and tokens[i + 1][:1].isupper():
            seq.append(word)
        elif seq:
            break
        if len([w for w in seq if _norm(w) not in CONNECT]) >= 3:
            break
    while seq and _norm(seq[-1]) in CONNECT:
        seq.pop()
    core = [w for w in seq if _norm(w) not in CONNECT]
    if len(core) > 2 and not core[2][0].isdigit():   # como mucho dos palabras (más un número: «Evil 9»)
        cut = seq.index(core[1]) + 1
        seq = seq[:cut]
    return " ".join(seq).upper()


def suggest_texts(title: str, topics: list[str] | None = None, extra: str = "", n: int = 6) -> list[str]:
    """Frases cortas (1–4 palabras) para la miniatura, distintas del título."""
    text = _norm(" ".join([title, extra] + list(topics or [])))
    name = main_name(title)
    out: list[str] = []
    for pat, phrases in PATTERNS:
        if re.search(pat, text):
            for ph in phrases:
                ph = ph.replace("{X}", name) if name else ph
                if "{X}" not in ph and ph not in out:
                    out.append(ph)
    q = re.search(r"¿([^?]+)\?", title)
    if q:   # el título ya es una pregunta: quedarse con lo esencial
        words = [w for w in q.group(1).split() if _norm(w) not in STOP][:3]
        if len(words) >= 2:   # con una sola palabra («¿VEZ?») no se entiende
            out.insert(0, "¿" + " ".join(words).upper() + "?")
    if name and name not in out:
        out.append(name)
    for t in topics or []:
        if t and t.upper() not in out and len(t.split()) <= 3:
            out.append(t.upper())
    if not out:
        words = [w for w in title.split() if _norm(w) not in STOP][:3]
        out.append(" ".join(words).upper() or "MIRA ESTO")
    # Nunca el título entero
    return [o for o in out if _norm(o) != _norm(title)][:n]


# ------------------------------------------------------------------- propuestas
def face_crop(path: str) -> tuple[list[float], float] | None:
    """Recorte alrededor de la cara más grande ([x0, y0, x1, y1] en 0–1) y su tamaño relativo."""
    from .tracking import detect_faces
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    k = 640 / max(w, h)
    small = cv2.resize(img, (int(w * k), int(h * k))) if k < 1 else img
    faces = detect_faces(small)
    if not faces:
        return None
    fx, fy, fw, fh, _c = faces[0]
    cx, cy = fx + fw / 2, fy + fh / 2
    side_h = min(1.0, fh * 2.6)            # la cara ocupa ~38 % del recorte: cabeza y hombros
    side_w = min(1.0, side_h * h / w * 0.85)
    x0 = min(max(0.0, cx - side_w / 2), 1 - side_w)
    y0 = min(max(0.0, cy - side_h * 0.42), 1 - side_h)
    return [round(x0, 4), round(y0, 4), round(x0 + side_w, 4), round(y0 + side_h, 4)], fh


def face_box(path: str) -> tuple[float, float, float, float] | None:
    """La cara más grande del fotograma: (x, y, ancho, alto) en 0–1."""
    from .tracking import detect_faces
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    k = 640 / max(w, h)
    faces = detect_faces(cv2.resize(img, (int(w * k), int(h * k))) if k < 1 else img)
    return faces[0][:4] if faces else None


def _to_canvas(lay: dict, box, doc) -> tuple[float, float, float, float]:
    """Una caja (0–1 de la imagen) en píxeles del lienzo, para una capa de imagen sin girar."""
    img = QImage(lay["path"])
    x0, y0, x1, y1 = lay.get("crop") or [0, 0, 1, 1]
    iw, ih = img.width() * (x1 - x0), img.height() * (y1 - y0)
    k = lay["scale"]
    bx, by, bw, bh = box
    px = lay["x"] + ((bx - x0) * img.width() - iw / 2) * k
    py = lay["y"] + ((by - y0) * img.height() - ih / 2) * k
    return px, py, px + bw * img.width() * k, py + bh * img.height() * k


def _overlap(a, b) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / area


def _bg(doc, path):
    lay = T.image_layer(path, doc, "Fondo", fill=True)
    lay["adj"].update(blur=0.22, exposure=-0.45, vignette=0.5, saturation=-0.1)
    return lay


def _fit(lay: dict, doc: dict, max_w_frac: float, wrap: bool = True):
    """Que el texto quepa en su zona (y en 2 líneas si hace falta)."""
    words = lay["text"].split()
    for _ in range(3):
        img, cw, _ch = T.render_layer(lay)
        if cw * lay["scale"] <= doc["w"] * max_w_frac:
            break
        if wrap and "\n" not in lay["text"] and len(words) >= 2:
            half = -(-len(words) // 2)
            lay["text"] = " ".join(words[:half]) + "\n" + " ".join(words[half:])
        else:
            lay["scale"] = round(doc["w"] * max_w_frac / cw, 3)


def _title(doc, text, prefs, x_frac, y_frac, max_w_frac) -> list[dict]:
    """El título con tu estilo: fuente, color, contorno, mayúsculas y, si lo usas, la PALABRA CLAVE en otro
    color (p. ej. blanco + la última palabra en rojo, en su propia línea y un poco más grande)."""
    def make(t):
        lay = T.text_layer(doc, t, "title")
        lay["font"] = prefs.get("font", lay["font"])
        lay["color"] = prefs.get("color", lay["color"])
        lay["size"] = int(130 * prefs.get("size_k", 1.0))
        lay["rotation"] = prefs.get("rotation", -3.0)
        if "outline" in prefs:
            lay["outline"]["on"] = bool(prefs["outline"])
        if prefs.get("outline_color"):
            lay["outline"]["color"] = prefs["outline_color"]
        if "uppercase" in prefs:
            lay["uppercase"] = bool(prefs["uppercase"])
        lay["x"], lay["y"] = doc["w"] * x_frac, doc["h"] * y_frac
        return lay
    words = text.split()
    accent = prefs.get("accent")
    if not accent or len(words) < 2 or "\n" in text:
        lay = make(text)
        _fit(lay, doc, max_w_frac)
        return [lay]
    k = 1 if len(words) <= 3 else 2                     # la(s) última(s) palabra(s) = la clave
    top, key = make(" ".join(words[:-k])), make(" ".join(words[-k:]))
    top["name"], key["name"] = "Título", "Palabra clave"
    key["color"] = accent
    key["size"] = int(top["size"] * 1.15)
    _fit(top, doc, max_w_frac)
    _fit(key, doc, max_w_frac, wrap=False)
    h1 = T.render_layer(top)[2] * top["scale"]
    h2 = T.render_layer(key)[2] * key["scale"]
    y = doc["h"] * y_frac - (h1 + h2) / 2
    top["y"], key["y"] = y + h1 / 2, y + h1 + h2 / 2 - h2 * 0.06
    return [top, key]


def subject_frame(frames: list[str]) -> str | None:
    """El fotograma que protagoniza la propuesta B (el mejor con cara; si no hay, el primero)."""
    frames = [f for f in frames if f]
    return next((f for f in frames if face_crop(f)), frames[0] if frames else None)


def proposals(fmt: str, frames: list[str], text: str, prefs: dict | None = None,
              cutouts: dict | None = None) -> list[tuple[str, dict]]:
    """[(nombre, documento)]: A personaje + texto grande · B personaje recortado (o rostro) + fondo
    desenfocado + texto · C dos elementos + texto central.
    cutouts = {ruta del fotograma: máscara del sujeto} (de bg_removal) para recortar al personaje."""
    prefs = prefs or {}
    cutouts = cutouts or {}
    frames = [f for f in frames if f]
    if not frames:
        return []
    side = prefs.get("text_side", "left")              # dónde sueles poner el texto
    tx = 0.30 if side == "left" else 0.70
    out = []
    short = fmt == "short"
    f0 = frames[0]
    fc = next((f for f in frames if face_crop(f)), None)   # el mejor fotograma con cara

    # A — Personaje + texto grande (el fotograma entero, degradado oscuro del lado del texto)
    d = T.new_doc(fmt)
    lay = T.image_layer(fc or f0, d, "Fotograma", fill=True)
    lay["adj"].update(contrast=0.12, sharpen=0.3, saturation=0.05)
    d["layers"].append(lay)
    g = T.shape_layer(d, "rect")
    g.update(name="Degradado", w=d["w"], h=d["h"], radius=0, x=d["w"] / 2, y=d["h"] / 2,
             gradient={"on": True, "c1": "#D9000000", "c2": "#00000000",
                       "angle": 0 if side == "left" else 180} if not short else
             {"on": True, "c1": "#00000000", "c2": "#D9000000", "angle": 270})
    zone = (0.5, 0.22, 0.9) if short else (tx, 0.5, 0.5)
    fb = face_box(fc or f0)
    if fb:   # el texto donde menos tape la cara (izquierda, derecha o abajo), calculado en el lienzo
        face = _to_canvas(lay, fb, d)
        best = None
        cands = [(0.5, 0.2, 0.9), (0.5, 0.82, 0.9)] if short else \
            [(0.30, 0.5, 0.5), (0.70, 0.5, 0.5), (0.5, 0.84, 0.9)]
        for cx, cy, mw in cands:
            box = (d["w"] * (cx - mw / 2), d["h"] * (cy - 0.13), d["w"] * (cx + mw / 2), d["h"] * (cy + 0.13))
            ov = _overlap(box, face)
            pref = 0.0 if (cx < 0.5) == (tx < 0.5) else 0.02      # a igualdad, el lado que prefieres
            if best is None or ov + pref < best[0]:
                best = (ov + pref, (cx, cy, mw))
        zone = best[1]
        if not short:
            g["gradient"]["angle"] = 0 if zone[0] < 0.45 else 180 if zone[0] > 0.55 else 270
    d["layers"].append(g)
    d["layers"] += _title(d, text, prefs, *zone)
    out.append(("A · Personaje + texto grande", d))

    # B — Personaje recortado (o rostro) + fondo desenfocado + texto
    d = T.new_doc(fmt)
    d["layers"].append(_bg(d, f0))
    src = fc or f0
    fg = T.image_layer(src, d, "Rostro")
    crop = face_crop(src)
    mask = cutouts.get(src)
    sb = None
    if mask:
        from .bg_removal import subject_box
        sb = subject_box(mask)
        # Si el recorte casi no dejó nada o lo dejó todo, no sirve como «pegatina»
        if sb and not (0.04 < (sb[2] - sb[0]) * (sb[3] - sb[1]) < 0.9):
            sb = None
    if sb:
        fg["name"] = "Personaje recortado"
        fg["mask"] = mask
        m = 0.01
        fg["crop"] = [max(0, sb[0] - m), max(0, sb[1] - m), min(1, sb[2] + m), min(1, sb[3] + m)]
        img = QImage(src)
        cw = img.width() * (fg["crop"][2] - fg["crop"][0])
        ch = img.height() * (fg["crop"][3] - fg["crop"][1])
        k = min(d["h"] * (0.62 if short else 0.92) / max(ch, 1), d["w"] * (0.95 if short else 0.55) / max(cw, 1))
        fg["scale"] = round(k, 4)
        crop = None
    if crop:
        fg["crop"] = crop[0]
        img = QImage(src)
        cw, ch = img.width() * (crop[0][2] - crop[0][0]), img.height() * (crop[0][3] - crop[0][1])
        fg["scale"] = round(d["h"] * (0.62 if short else 0.95) / max(ch, 1), 4)
    else:
        fg["scale"] = round(fg["scale"] * 0.8, 4)
    fg["x"] = d["w"] * (0.5 if short else (0.72 if side == "left" else 0.28))
    fg["y"] = d["h"] * (0.62 if short else 0.55)
    if sb:   # apoyado abajo, como un personaje que «sale» de la miniatura
        img_h = QImage(src).height() * (fg["crop"][3] - fg["crop"][1]) * fg["scale"]
        fg["y"] = d["h"] - img_h / 2 - d["h"] * (0.18 if short else 0.0)
    fg["outline"].update(on=True, color="#FFFFFF", width=6)
    fg["shadow"].update(on=True, blur=24, dx=0, dy=10, opacity=0.7)
    fg["adj"].update(contrast=0.15, sharpen=0.35)
    d["layers"].append(fg)
    d["layers"] += _title(d, text, prefs, 0.5 if short else tx, 0.2 if short else 0.5, 0.9 if short else 0.48)
    out.append(("B · Personaje recortado + fondo desenfocado" if sb else "B · Rostro + fondo desenfocado", d))

    # C — Dos elementos + texto central
    if len(frames) >= 2:
        d = T.new_doc(fmt)
        d["bg"] = {"type": "color", "color": "#000000"}
        for i, f in enumerate(frames[:2]):
            lay = T.image_layer(f, d, f"Elemento {i + 1}")
            img = QImage(f)
            if short:   # arriba y abajo
                k = max(d["w"] / img.width(), d["h"] / 2 / img.height())
                lay["scale"] = round(k, 4)
                lay["x"], lay["y"] = d["w"] / 2, d["h"] * (0.25 if i == 0 else 0.75)
                vis_h = d["h"] / 2 / (img.height() * k)
                lay["crop"] = [0.0, (1 - vis_h) / 2, 1.0, (1 + vis_h) / 2]
            else:       # izquierda y derecha
                k = max(d["w"] / 2 / img.width(), d["h"] / img.height())
                lay["scale"] = round(k, 4)
                lay["x"], lay["y"] = d["w"] * (0.25 if i == 0 else 0.75), d["h"] / 2
                vis_w = d["w"] / 2 / (img.width() * k)
                lay["crop"] = [(1 - vis_w) / 2, 0.0, (1 + vis_w) / 2, 1.0]
            lay["adj"].update(contrast=0.1, sharpen=0.25)
            d["layers"].append(lay)
        bar = T.shape_layer(d, "rect")
        bar.update(name="Separación", radius=0, fill="#E8742F",
                   w=d["w"] if short else 10, h=10 if short else d["h"], x=d["w"] / 2, y=d["h"] / 2)
        d["layers"].append(bar)
        d["layers"] += _title(d, text, prefs, 0.5, 0.5, 0.9 if short else 0.62)
        out.append(("C · Dos elementos + texto central", d))
    else:   # C con una sola imagen: la imagen entera y una banda oscura abajo con el texto
        d = T.new_doc(fmt)
        lay = T.image_layer(f0, d, "Imagen", fill=True)
        lay["adj"].update(contrast=0.15, sharpen=0.3, saturation=0.1)
        d["layers"].append(lay)
        bh = d["h"] * (0.22 if short else 0.3)
        band = T.shape_layer(d, "rect")
        band.update(name="Banda", radius=0, fill="#000000", w=d["w"], h=bh, x=d["w"] / 2, y=d["h"] - bh / 2)
        band["opacity"] = 0.78
        d["layers"].append(band)
        d["layers"] += _title(d, text, prefs, 0.5, 1 - bh / d["h"] / 2, 0.92)
        out.append(("C · Imagen + banda de texto abajo", d))
    return out


def learn(prefs: dict, before: dict, after: dict) -> dict:
    """Aprende de lo que cambiaste en una propuesta (fuente, color, tamaño y lado del texto, giro)."""
    p = dict(prefs)
    tb = next((l for l in before["layers"] if l["kind"] == "text"), None)
    ta = next((l for l in after["layers"] if l["kind"] == "text"), None)
    if tb is None or ta is None:
        return p
    if ta["font"] != tb["font"]:
        p["font"] = ta["font"]
    if ta["color"] != tb["color"]:
        p["color"] = ta["color"]
    k0 = tb["size"] * tb["scale"]
    k1 = ta["size"] * ta["scale"]
    if k0 > 0 and abs(k1 / k0 - 1) > 0.08:
        p["size_k"] = round(min(1.8, max(0.6, p.get("size_k", 1.0) * (k1 / k0) ** 0.5)), 3)
    if abs(ta["x"] - tb["x"]) > after["w"] * 0.15:
        p["text_side"] = "left" if ta["x"] < after["w"] / 2 else "right"
    if abs(ta["rotation"] - tb["rotation"]) > 1:
        p["rotation"] = round(ta["rotation"], 1)
    return p
