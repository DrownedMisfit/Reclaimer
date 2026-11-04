"""
Miniaturas: el documento (formato, fondo y capas) y su dibujo.

Una miniatura es un diccionario sencillo (fácil de guardar con el proyecto y de deshacer):
  {"format": "youtube"|"short", "w": 1280, "h": 720,
   "bg": {"type": "color", "color": "#101014"} | {"type": "gradient", "c1", "c2", "angle"},
   "layers": [capa, …]}           (la primera capa queda al fondo; la última, delante)

Capa (común): id, kind ("image" | "text" | "shape"), name, x, y (centro, en píxeles del lienzo), scale,
  rotation (grados), opacity (0–1), visible, locked, flip,
  outline {on, color, width}, shadow {on, color, blur, dx, dy, opacity}, glow {on, color, radius, opacity}
  image: path, crop [x0, y0, x1, y1] (0–1), adj {exposure, contrast, saturation, temperature, shadows,
         highlights, sharpen, blur, vignette}, mask (ruta de un PNG en grises: lo blanco se ve)
  text:  text, font, size, weight (100–900), italic, spacing, align, color, uppercase, line
  shape: shape ("rect" | "ellipse" | "arrow"), w, h, fill, stroke, stroke_w, radius,
         gradient {on, c1, c2, angle}

render_layer() devuelve la capa ya dibujada (con sus efectos) como imagen; el lienzo y la exportación
usan exactamente lo mismo: lo que ves es lo que exportas.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform)

SIZES = {"youtube": (1280, 720), "short": (1080, 1920)}
MAX_BYTES = 2 * 1024 * 1024        # YouTube no acepta miniaturas de más de 2 MB

ADJ_DEFAULT = {"exposure": 0.0, "contrast": 0.0, "saturation": 0.0, "temperature": 0.0, "shadows": 0.0,
               "highlights": 0.0, "sharpen": 0.0, "blur": 0.0, "vignette": 0.0}


def new_doc(fmt: str = "youtube") -> dict:
    w, h = SIZES[fmt]
    return {"format": fmt, "w": w, "h": h, "bg": {"type": "color", "color": "#101014"}, "layers": []}


def _base(kind: str, name: str, x: float, y: float) -> dict:
    return {"id": uuid.uuid4().hex[:10], "kind": kind, "name": name, "x": x, "y": y, "scale": 1.0,
            "rotation": 0.0, "opacity": 1.0, "visible": True, "locked": False, "flip": False,
            "outline": {"on": False, "color": "#FFFFFF", "width": 8},
            "shadow": {"on": False, "color": "#000000", "blur": 18, "dx": 6, "dy": 8, "opacity": 0.6},
            "glow": {"on": False, "color": "#FFD400", "radius": 24, "opacity": 0.7}}


def image_layer(path: str, doc: dict, name: str = "Imagen", fill: bool = False) -> dict:
    img = QImage(path)
    w0, h0 = max(1, img.width()), max(1, img.height())
    lay = _base("image", name, doc["w"] / 2, doc["h"] / 2)
    lay.update(path=path, crop=[0.0, 0.0, 1.0, 1.0], adj=dict(ADJ_DEFAULT), mask=None)
    # Que entre en el lienzo (fill = que lo cubra entero, como fondo)
    k = (max if fill else min)(doc["w"] / w0, doc["h"] / h0)
    lay["scale"] = round(k if fill else min(1.0, k * 0.9), 4)
    return lay


def text_layer(doc: dict, text: str = "TEXTO", preset: str = "title") -> dict:
    lay = _base("text", text[:20], doc["w"] / 2, doc["h"] * (0.22 if doc["format"] == "short" else 0.25))
    base = {"text": text, "font": "Impact", "size": 130, "weight": 700, "italic": False, "spacing": 1.0,
            "align": "center", "color": "#FFFFFF", "uppercase": True, "line": 1.0}
    if preset == "title":
        lay["outline"].update(on=True, color="#000000", width=10)
        lay["shadow"].update(on=True, blur=12, dx=6, dy=8, opacity=0.65)
    elif preset == "subtitle":
        base.update(font="Bahnschrift", size=64, weight=700, uppercase=False)
        lay["shadow"].update(on=True, blur=10, dx=3, dy=4, opacity=0.6)
    elif preset == "label":
        base.update(font="Bahnschrift", size=48, weight=700, color="#111111")
    elif preset == "impact":
        # 🔥 el estilo del usuario: 2–3 palabras enormes en Anton, blanco y *rojo*, borde negro y resplandor rojo
        base.update(font="Anton", size=190, weight=400, spacing=1.02, line=0.92, accent="#E5232A")
        lay["outline"].update(on=True, color="#000000", width=14)
        lay["glow"].update(on=True, color="#FF1E1E", radius=28, opacity=0.7)
        lay["shadow"].update(on=True, blur=14, dx=0, dy=8, opacity=0.6)
    lay.update(base)
    return lay


MY_RED = "#E5232A"


def logo_box_layer(doc: dict) -> dict:
    """▭ El recuadro del logo del juego (arriba, negro con borde rojo): el logo va encima."""
    lay = shape_layer(doc, "rect")
    w = doc["w"] * (0.42 if doc["format"] != "short" else 0.7)
    lay.update(name="Recuadro del logo", w=round(w), h=round(w * 0.3), fill="#000000", stroke=MY_RED, stroke_w=8,
               radius=6, y=round(doc["h"] * (0.12 if doc["format"] != "short" else 0.08)))
    return lay


def red_frame(lay: dict) -> dict:
    """🟥 Marco rojo a una imagen (un producto o un personaje recortado), con su sombra."""
    lay["outline"].update(on=True, color=MY_RED, width=10)
    lay["shadow"].update(on=True, blur=16, dx=0, dy=8, opacity=0.6)
    return lay


def shape_layer(doc: dict, shape: str = "rect") -> dict:
    lay = _base("shape", {"rect": "Rectángulo", "ellipse": "Círculo", "arrow": "Flecha"}.get(shape, shape),
                doc["w"] / 2, doc["h"] / 2)
    w = doc["w"] * (0.3 if shape != "arrow" else 0.22)
    lay.update(shape=shape, w=w, h=w * (0.35 if shape == "rect" else 1.0 if shape == "ellipse" else 0.45),
               fill="#E8742F", stroke="#000000", stroke_w=0, radius=18,
               gradient={"on": False, "c1": "#E8742F", "c2": "#B13B1F", "angle": 90})
    return lay


def clone(lay: dict) -> dict:
    c = copy.deepcopy(lay)
    c["id"] = uuid.uuid4().hex[:10]
    c["x"] += 30
    c["y"] += 30
    c["name"] = lay["name"] + " (copia)"
    return c


# ----------------------------------------------------------------- imagen ↔ numpy
def qimage_to_rgba(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return arr[:, :w * 4].reshape(h, w, 4).copy()


def rgba_to_qimage(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def adjust(rgb: np.ndarray, adj: dict) -> np.ndarray:
    """Ajustes de imagen (rgb float 0–1). Todo suave: valores típicos −1…+1."""
    a = dict(ADJ_DEFAULT, **(adj or {}))
    x = rgb
    if a["blur"] > 0:
        k = max(1, int(a["blur"] * 25)) * 2 + 1
        x = cv2.GaussianBlur(x, (k, k), 0)
    if a["exposure"]:
        x = x * (2.0 ** a["exposure"])
    if a["shadows"]:
        x = x + a["shadows"] * 0.5 * x * (1 - x) ** 2 * 4
    if a["highlights"]:
        x = x + a["highlights"] * 0.5 * x ** 2 * (1 - x) * 4
    if a["contrast"]:
        x = (x - 0.5) * (1 + a["contrast"]) + 0.5
    if a["temperature"]:
        x = x + np.array([0.08, 0.0, -0.08]) * a["temperature"]
    if a["saturation"]:
        g = x.mean(axis=2, keepdims=True)
        x = g + (x - g) * (1 + a["saturation"])
    if a["sharpen"] > 0:
        soft = cv2.GaussianBlur(np.clip(x, 0, 1).astype(np.float32), (0, 0), 2.0)
        x = x + (x - soft) * a["sharpen"] * 1.5
    if a["vignette"] > 0:
        h, w = x.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
        x = x * (1 - a["vignette"] * np.clip(d - 0.35, 0, 1)[..., None] * 1.3)
    return np.clip(x, 0, 1)


# ------------------------------------------------------------------- contenido
def _image_content(lay: dict) -> np.ndarray:
    img = QImage(lay["path"])
    if img.isNull():
        return np.zeros((10, 10, 4), np.uint8)
    rgba = qimage_to_rgba(img)
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = lay.get("crop") or [0, 0, 1, 1]
    rgba = rgba[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
    rgb = adjust(rgba[..., :3].astype(np.float32) / 255.0, lay.get("adj"))
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    if lay.get("mask"):
        m = QImage(lay["mask"])
        if not m.isNull():
            mm = qimage_to_rgba(m)[..., 0].astype(np.float32) / 255.0
            mm = cv2.resize(mm, (img.width(), img.height()), interpolation=cv2.INTER_LINEAR)
            mm = mm[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
            alpha = alpha * mm
    out = np.dstack([rgb * 255, alpha * 255]).astype(np.uint8)
    return out


def _text_path(lay: dict) -> QPainterPath:
    return _text_paths(lay)[0]


def _text_paths(lay: dict) -> tuple[QPainterPath, QPainterPath]:
    """(todo el texto, lo que va en el color de acento). Lo escrito *entre asteriscos* sale en «accent» (p. ej.
    «ESTO ES *MALO*»: «MALO» en rojo, como en las miniaturas del usuario); los asteriscos no se ven."""
    f = QFont(lay.get("font", "Impact"))
    f.setPixelSize(max(4, int(lay.get("size", 100))))
    f.setWeight(QFont.Weight(int(lay.get("weight", 700))))
    f.setItalic(bool(lay.get("italic")))
    f.setLetterSpacing(QFont.PercentageSpacing, 100 * float(lay.get("spacing", 1.0)))
    text = lay.get("text", "")
    if lay.get("uppercase"):
        text = text.upper()
    fm = QFontMetricsF(f)
    raw_lines = text.split("\n") or [""]
    lines = [t.replace("*", "") for t in raw_lines]
    line_h = fm.height() * float(lay.get("line", 1.0))
    widths = [fm.horizontalAdvance(t) for t in lines]
    W = max(widths) if widths else 0
    path, accent = QPainterPath(), QPainterPath()
    for i, (raw, t, lw) in enumerate(zip(raw_lines, lines, widths)):
        x = {"left": 0.0, "right": W - lw}.get(lay.get("align", "center"), (W - lw) / 2)
        base = QPointF(x, fm.ascent() + i * line_h)
        path.addText(base, f, t)
        if "*" in raw:                             # los trozos entre asteriscos, en su sitio exacto
            pos, on = 0, False
            for run in raw.split("*"):
                if on and run:
                    accent.addText(QPointF(x + fm.horizontalAdvance(t[:pos]), base.y()), f, run)
                pos += len(run)
                on = not on
    return path, accent


def _shape_path(lay: dict) -> QPainterPath:
    w, h = float(lay.get("w", 200)), float(lay.get("h", 100))
    p = QPainterPath()
    s = lay.get("shape", "rect")
    if s == "ellipse":
        p.addEllipse(QRectF(0, 0, w, h))
    elif s == "arrow":
        t = h * 0.38
        p.addPolygon(QPolygonF([QPointF(0, h / 2 - t / 2), QPointF(w * 0.62, h / 2 - t / 2), QPointF(w * 0.62, 0),
                                QPointF(w, h / 2), QPointF(w * 0.62, h), QPointF(w * 0.62, h / 2 + t / 2),
                                QPointF(0, h / 2 + t / 2)]))
        p.closeSubpath()
    else:
        r = min(float(lay.get("radius", 0)), w / 2, h / 2)
        p.addRoundedRect(QRectF(0, 0, w, h), r, r)
    return p


def _vector_content(lay: dict, pad: int) -> np.ndarray:
    """Texto o forma dibujados con Qt (bordes nítidos); el contorno del texto, con trazo real."""
    path = _text_path(lay) if lay["kind"] == "text" else _shape_path(lay)
    br = path.boundingRect()
    ow = float(lay["outline"]["width"]) if lay["outline"].get("on") else 0.0
    sw = float(lay.get("stroke_w", 0)) if lay["kind"] == "shape" else 0.0
    m = int(ow + sw + 4)
    W, H = int(br.width() + 2 * m) + 2, int(br.height() + 2 * m) + 2
    img = QImage(max(2, W), max(2, H), QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.translate(m - br.left(), m - br.top())
    if ow > 0 and lay["kind"] == "text":     # contorno del texto: trazo grueso por debajo del relleno
        st = QPainterPathStroker()
        st.setWidth(ow * 2)
        st.setJoinStyle(Qt.RoundJoin)
        p.fillPath(st.createStroke(path), QColor(lay["outline"]["color"]))
    if lay["kind"] == "text":
        p.fillPath(path, QColor(lay.get("color", "#FFFFFF")))
        accent = _text_paths(lay)[1]
        if not accent.isEmpty():                   # *palabra clave* en el color de acento
            p.fillPath(accent, QColor(lay.get("accent", "#E5232A")))
    else:
        g = lay.get("gradient") or {}
        if g.get("on"):
            ang = math.radians(float(g.get("angle", 90)))
            c = br.center()
            d = max(br.width(), br.height()) / 2
            grad = QLinearGradient(c.x() - math.cos(ang) * d, c.y() - math.sin(ang) * d,
                                   c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d)
            grad.setColorAt(0, QColor(g.get("c1", "#E8742F")))
            grad.setColorAt(1, QColor(g.get("c2", "#B13B1F")))
            p.fillPath(path, QBrush(grad))
        else:
            p.fillPath(path, QColor(lay.get("fill", "#E8742F")))
        if sw > 0:
            p.setPen(QPen(QColor(lay.get("stroke", "#000000")), sw))
            p.drawPath(path)
    p.end()
    return qimage_to_rgba(img)


def _effects(rgba: np.ndarray, lay: dict, scale: float) -> tuple[np.ndarray, int]:
    """Contorno (imágenes recortadas), brillo y sombra a partir de la transparencia. Devuelve (imagen, margen)."""
    sh, gl, ol = lay["shadow"], lay["glow"], lay["outline"]
    pad = 2
    if lay["kind"] == "image" and ol.get("on"):
        pad += int(ol["width"] / max(scale, 1e-3)) + 2
    if gl.get("on"):
        pad += int(gl["radius"] / max(scale, 1e-3) * 2)
    if sh.get("on"):
        pad += int((sh["blur"] * 2 + max(abs(sh["dx"]), abs(sh["dy"]))) / max(scale, 1e-3))
    h, w = rgba.shape[:2]
    canvas = np.zeros((h + 2 * pad, w + 2 * pad, 4), np.float32)
    canvas[pad:pad + h, pad:pad + w] = rgba.astype(np.float32) / 255.0
    alpha = canvas[..., 3].copy()

    def comp(under_rgb, under_a, over):
        """Pone «over» (rgba) encima de una capa de color sólido con alfa under_a."""
        a_o = over[..., 3:4]
        a_u = under_a[..., None]
        a = a_o + a_u * (1 - a_o)
        rgb = (over[..., :3] * a_o + np.array(under_rgb) * a_u * (1 - a_o)) / np.maximum(a, 1e-6)
        return np.dstack([rgb, a[..., 0]])

    def col(c):
        q = QColor(c)
        return [q.redF(), q.greenF(), q.blueF()]
    out = canvas
    if lay["kind"] == "image" and ol.get("on"):     # contorno tipo «pegatina» alrededor del sujeto recortado
        r = max(1, int(ol["width"] / max(scale, 1e-3)))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        ring = cv2.dilate((alpha > 0.5).astype(np.uint8), k).astype(np.float32)
        ring = cv2.GaussianBlur(ring, (3, 3), 0)
        out = comp(col(ol["color"]), ring, out)
        alpha = out[..., 3].copy()
    if gl.get("on"):
        r = max(1, int(gl["radius"] / max(scale, 1e-3)))
        g = cv2.GaussianBlur(alpha, (0, 0), r) * float(gl.get("opacity", 0.7)) * 1.6
        out = comp(col(gl["color"]), np.clip(g, 0, 1), out)
    if sh.get("on"):
        b = max(1, int(sh["blur"] / max(scale, 1e-3)))
        dx, dy = int(sh["dx"] / max(scale, 1e-3)), int(sh["dy"] / max(scale, 1e-3))
        s = cv2.GaussianBlur(alpha, (0, 0), b)
        s = np.roll(np.roll(s, dy, axis=0), dx, axis=1) * float(sh.get("opacity", 0.6))
        out = comp(col(sh["color"]), np.clip(s, 0, 1), out)
    return np.clip(out * 255, 0, 255).astype(np.uint8), pad


_cache: dict[str, tuple[QImage, float, float]] = {}


def _key(lay: dict) -> str:
    skip = {"x", "y", "rotation", "opacity", "visible", "locked", "name", "flip", "warp"}   # (se aplican al colocar)
    data = {k: v for k, v in lay.items() if k not in skip}
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def render_layer(lay: dict) -> tuple[QImage, float, float]:
    """(imagen de la capa con sus efectos, ancho y alto «útiles» sin márgenes) — en píxeles de contenido;
    la escala y la rotación se aplican al colocarla."""
    k = _key(lay)
    if k in _cache:
        return _cache[k]
    scale = float(lay.get("scale", 1.0))
    if lay["kind"] == "image":
        rgba = _image_content(lay)
    else:
        rgba = _vector_content(lay, 0)
    core_h, core_w = rgba.shape[:2]
    rgba, _pad = _effects(rgba, lay, scale)
    img = rgba_to_qimage(rgba)
    if len(_cache) > 200:
        _cache.clear()
    _cache[k] = (img, core_w, core_h)
    return _cache[k]


def layer_transform(lay: dict, img: QImage, warp: bool = True) -> QTransform:
    """De píxeles de la imagen de la capa a píxeles del lienzo (centro en x, y). Con ◇ Deformar, antes la
    perspectiva de sus 4 esquinas (warp=False: sin ella, para saber dónde estaría la capa sin deformar)."""
    s = float(lay.get("scale", 1.0))
    t = QTransform()
    t.translate(float(lay["x"]), float(lay["y"]))
    t.rotate(float(lay.get("rotation", 0)))
    t.scale(-s if lay.get("flip") else s, s)
    t.translate(-img.width() / 2, -img.height() / 2)
    w = warp_transform(lay, img) if warp else None
    return w * t if w is not None else t


# ------------------------------------------------------------------ ◇ Deformar (las 4 esquinas, con perspectiva)
def warp_of(lay: dict) -> list[list[float]] | None:
    """Cuánto se ha movido cada esquina del contenido (sup. izq., sup. der., inf. der., inf. izq.), en fracciones
    de su ancho y alto; None si no está deformada."""
    w = lay.get("warp")
    if not w or len(w) != 4 or not any(abs(float(v)) > 1e-4 for c in w for v in c):
        return None
    return [[float(c[0]), float(c[1])] for c in w]


def content_quad(lay: dict, img: QImage) -> QPolygonF:
    """Las 4 esquinas del contenido (sin los márgenes de sombra o brillo), en píxeles de la imagen de la capa."""
    _img, cw, ch = render_layer(lay)
    x0, y0 = (img.width() - cw) / 2, (img.height() - ch) / 2
    return QPolygonF(QRectF(x0, y0, cw, ch))


def warp_transform(lay: dict, img: QImage) -> QTransform | None:
    w = warp_of(lay)
    if w is None:
        return None
    _img, cw, ch = render_layer(lay)
    src = content_quad(lay, img)
    dst = QPolygonF([QPointF(src.at(i).x() + w[i][0] * cw, src.at(i).y() + w[i][1] * ch) for i in range(4)])
    t = QTransform()
    return t if QTransform.quadToQuad(src, dst, t) else None


def paint_background(p: QPainter, doc: dict):
    bg = doc.get("bg") or {}
    r = QRectF(0, 0, doc["w"], doc["h"])
    if bg.get("type") == "gradient":
        ang = math.radians(float(bg.get("angle", 90)))
        c, d = r.center(), max(r.width(), r.height()) / 2
        g = QLinearGradient(c.x() - math.cos(ang) * d, c.y() - math.sin(ang) * d,
                            c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d)
        g.setColorAt(0, QColor(bg.get("c1", "#1b1b2b")))
        g.setColorAt(1, QColor(bg.get("c2", "#000000")))
        p.fillRect(r, QBrush(g))
    else:
        p.fillRect(r, QColor(bg.get("color", "#101014")))


def render(doc: dict, scale: float = 1.0) -> QImage:
    """La miniatura entera (para exportar o para la vista previa pequeña)."""
    W, H = int(doc["w"] * scale), int(doc["h"] * scale)
    out = QImage(max(1, W), max(1, H), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.black)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(scale, scale)
    paint_background(p, doc)
    for lay in doc["layers"]:
        if not lay.get("visible", True):
            continue
        img, _w, _h = render_layer(lay)
        p.save()
        p.setOpacity(float(lay.get("opacity", 1.0)))
        p.setTransform(layer_transform(lay, img) * QTransform().scale(scale, scale))
        p.drawImage(0, 0, img)
        p.restore()
    p.end()
    return out


def export(doc: dict, path: str) -> int:
    """Guarda la miniatura. En JPG baja la calidad lo justo para quedar por debajo de 2 MB (límite de YouTube).
    Devuelve el tamaño en bytes."""
    import os
    img = render(doc).convertToFormat(QImage.Format_RGB888)
    if path.lower().endswith(".png"):
        img.save(path, "PNG")
        if os.path.getsize(path) <= MAX_BYTES:
            return os.path.getsize(path)
        path = path[:-4] + ".jpg"
    for q in (95, 90, 85, 80, 72, 65):
        img.save(path, "JPG", q)
        if os.path.getsize(path) <= MAX_BYTES:
            break
    return os.path.getsize(path)
