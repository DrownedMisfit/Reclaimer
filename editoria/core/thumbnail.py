"""
Miniaturas: el documento (formato, fondo y capas) y su dibujo.

Una miniatura es un diccionario sencillo (fácil de guardar con el proyecto y de deshacer):
  {"format": "youtube"|"short", "w": 1280, "h": 720,
   "bg": {"type": "color", "color": "#101014"} | {"type": "gradient", "c1", "c2", "angle"},
   "layers": [capa, …]}           (la primera capa queda al fondo; la última, delante)

Capa (común): id, kind ("image" | "text" | "shape"), name, x, y (centro, en píxeles del lienzo), scale,
  rotation (grados), opacity (0–1), visible, locked, flip,
  outline {on, color, width}, shadow {on, color, blur, dx, dy, opacity}, glow {on, color, radius, opacity}
  outlines [{color, width}, …] (opcional: más contornos apilados por fuera del primero; texto e imágenes)
  blend (opcional): modo de fusión con lo de debajo ("normal", "multiply", "screen", "overlay"…; ver BLENDS)
  image: path, crop [x0, y0, x1, y1] (0–1), adj {exposure, contrast, saturation, temperature, shadows,
         highlights, sharpen, blur, vignette}, mask (ruta de un PNG en grises: lo blanco se ve)
         feather (0–1: bordes suaves hacia dentro), fade {top, bottom, left, right} (0–1: fundido desde ese lado)
  text:  text, font, size, weight (100–900), italic, spacing, align, color, uppercase, line,
         word_styles {"índice de la palabra": {color, font, size, weight, italic, outline, shadow, glow}} (opcional:
         lo que esa palabra tiene distinto del resto del texto; ver word_view)
         text_fill {type: "color" | "gradient" | "image", c1, c2, angle, path} (opcional: relleno de las letras)
  shape: shape ("rect" | "ellipse" | "arrow"), w, h, fill, stroke, stroke_w, radius,
         gradient {on, c1, c2, angle}
         slot (opcional): 🖼 hueco de una plantilla, donde va una imagen (fill_box lo cambia por ella)

render_layer() devuelve la capa ya dibujada (con sus efectos) como imagen; el lienzo y la exportación
usan exactamente lo mismo: lo que ves es lo que exportas.
"""
from __future__ import annotations

import copy
import hashlib
import json
import difflib
import math
import os
import re
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


# 🎚 Modos de fusión (como en Photoshop): cómo se mezcla la capa con lo que tiene debajo
BLENDS = [("normal", "Normal", QPainter.CompositionMode_SourceOver),
          ("multiply", "Multiplicar (oscurece)", QPainter.CompositionMode_Multiply),
          ("screen", "Trama (aclara)", QPainter.CompositionMode_Screen),
          ("overlay", "Superponer", QPainter.CompositionMode_Overlay),
          ("softlight", "Luz suave", QPainter.CompositionMode_SoftLight),
          ("hardlight", "Luz fuerte", QPainter.CompositionMode_HardLight),
          ("lighten", "Aclarar", QPainter.CompositionMode_Lighten),
          ("darken", "Oscurecer", QPainter.CompositionMode_Darken),
          ("dodge", "Sobreexponer color", QPainter.CompositionMode_ColorDodge),
          ("burn", "Subexponer color", QPainter.CompositionMode_ColorBurn),
          ("difference", "Diferencia", QPainter.CompositionMode_Difference)]
_BLEND = {k: m for k, _l, m in BLENDS}
EXTRA_OUTLINES_MAX = 3


def blend_mode(lay: dict):
    """El modo de composición de QPainter de esa capa (normal si no tiene)."""
    return _BLEND.get(lay.get("blend") or "normal", QPainter.CompositionMode_SourceOver)


def extra_outlines(lay: dict) -> list[tuple[str, float]]:
    """Los contornos de más (por fuera del primero), del de dentro al de fuera: [(color, grosor)]."""
    out = []
    for o in (lay.get("outlines") or [])[:EXTRA_OUTLINES_MAX]:
        try:
            w = float(o.get("width", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if w > 0 and o.get("on", True):
            out.append((str(o.get("color", "#000000")), w))
    return out


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


def blur_area_layer(doc: dict, shape: str = "rect", x: float | None = None, y: float | None = None,
                    w: float | None = None, h: float | None = None) -> dict:
    """🌫 Zona borrosa: un círculo o un cuadrado que desenfoca lo que hay DEBAJO (no tiene relleno propio)."""
    ellipse = shape == "ellipse"
    lay = shape_layer(doc, "ellipse" if ellipse else "rect")
    lay.update(name="🌫 Borroso (círculo)" if ellipse else "🌫 Borroso (cuadrado)", blur_area={"radius": 18},
               radius=0, w=int(round(w if w is not None else doc["w"] * 0.25)),
               h=int(round(h if h is not None else doc["h"] * 0.25)))
    lay["x"] = float(x if x is not None else doc["w"] / 2)
    lay["y"] = float(y if y is not None else doc["h"] / 2)
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
def _image_content(lay: dict, k: float = 1.0) -> np.ndarray:
    """El contenido de una capa de imagen (recorte, ajustes, máscara). k < 1: ya reducido (ver shrink_k)."""
    img = QImage(lay["path"])
    if img.isNull():
        return np.zeros((10, 10, 4), np.uint8)
    rgba = qimage_to_rgba(img)
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = lay.get("crop") or [0, 0, 1, 1]
    rgba = rgba[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
    ch, cw = rgba.shape[:2]
    size = (max(1, round(cw * k)), max(1, round(ch * k)))
    if k < 1:
        rgba = cv2.resize(rgba, size, interpolation=cv2.INTER_AREA)
    rgb = adjust(rgba[..., :3].astype(np.float32) / 255.0, lay.get("adj"))
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    if lay.get("mask"):
        m = QImage(lay["mask"])
        if not m.isNull():
            mm = qimage_to_rgba(m)[..., 0].astype(np.float32) / 255.0
            mm = cv2.resize(mm, (img.width(), img.height()), interpolation=cv2.INTER_LINEAR)
            mm = mm[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))]
            if k < 1:
                mm = cv2.resize(mm, size, interpolation=cv2.INTER_AREA)
            alpha = alpha * mm
    alpha = soft_edges(alpha, float(lay.get("feather", 0) or 0), lay.get("fade"))
    out = np.dstack([rgb * 255, alpha * 255]).astype(np.uint8)
    return out


def _suave(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def soft_edges(alpha: np.ndarray, feather: float = 0.0, fade: dict | None = None) -> np.ndarray:
    """🌗 Bordes suaves: feather (0–1) difumina hacia dentro el borde de lo que se ve (el rectángulo de la foto o el
    sujeto recortado); fade {lado: 0–1} la funde desde ese lado (p. ej. el personaje que se funde con el fondo por abajo).
    Las cantidades son fracciones del lado de la imagen: no cambian al escalarla."""
    fade = {k: float(v or 0) for k, v in (fade or {}).items() if k in ("top", "bottom", "left", "right")}
    if feather <= 0 and not any(v > 0 for v in fade.values()):
        return alpha
    h, w = alpha.shape[:2]
    out = alpha.astype(np.float32)
    if feather > 0:
        F = max(1.0, float(feather) * 0.25 * min(w, h))
        dentro = cv2.copyMakeBorder((out > 0.5).astype(np.uint8), 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        d = cv2.distanceTransform(dentro, cv2.DIST_L2, 3)[1:-1, 1:-1]
        out = out * _suave(d / F)
    for lado, v in fade.items():
        if v <= 0:
            continue
        n = h if lado in ("top", "bottom") else w
        rampa = _suave(np.arange(n, dtype=np.float32) / max(1.0, v * n))
        if lado in ("bottom", "right"):
            rampa = rampa[::-1]
        out = out * (rampa[:, None] if lado in ("top", "bottom") else rampa[None, :])
    return out


def image_unmasked(lay: dict, k: float = 1.0) -> np.ndarray:
    """El contenido de la capa de imagen como si no tuviera máscara (🖌 Recuperar enseña lo borrado)."""
    limpia = {**lay, "mask": None}
    bk = _base_key(limpia) + f"|{k}"
    rgba = _base_cache.get(bk)
    if rgba is None:
        rgba = _image_content(limpia, k)
        _guardar(_base_cache, bk, rgba, lambda a: a.nbytes, _BASE_MAX)
    return rgba


def mask_core(lay: dict, k: float, w: int, h: int) -> np.ndarray:
    """La máscara de la capa (0–255) ya recortada y al tamaño (w, h) de su contenido dibujado."""
    q = QImage(lay.get("mask") or "")
    if q.isNull():
        return np.full((h, w), 255, np.uint8)
    mm = qimage_to_rgba(q)[..., 0]
    H, W = mm.shape[:2]
    x0, y0, x1, y1 = lay.get("crop") or [0, 0, 1, 1]
    mm = mm[int(y0 * H):max(int(y0 * H) + 1, int(y1 * H)), int(x0 * W):max(int(x0 * W) + 1, int(x1 * W))]
    return cv2.resize(mm, (w, h), interpolation=cv2.INTER_AREA)


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


_fill_imgs: dict[str, QImage] = {}


def _fill_image(path: str) -> QImage:
    q = _fill_imgs.get(path)
    if q is None:
        if len(_fill_imgs) > 8:
            _fill_imgs.clear()
        q = _fill_imgs[path] = QImage(path)
    return q


def text_brush(lay: dict, br: QRectF) -> QBrush:
    """El relleno de las letras: color, degradado (de c1 a c2, en su ángulo) o una imagen que cubre todo el texto."""
    tf = lay.get("text_fill") or {}
    t = tf.get("type", "color")
    if t == "gradient":
        ang = math.radians(float(tf.get("angle", 90)))
        c = br.center()
        d = max(br.width(), br.height()) / 2
        g = QLinearGradient(c.x() - math.cos(ang) * d, c.y() - math.sin(ang) * d,
                            c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d)
        g.setColorAt(0, QColor(tf.get("c1", "#FFD400")))
        g.setColorAt(1, QColor(tf.get("c2", "#E5232A")))
        return QBrush(g)
    if t == "image" and tf.get("path"):
        q = _fill_image(str(tf["path"]))
        if not q.isNull() and br.width() > 0 and br.height() > 0:
            k = max(br.width() / q.width(), br.height() / q.height()) * max(0.2, float(tf.get("zoom", 1.0)))
            b = QBrush(q)
            tr = QTransform()
            tr.translate(br.center().x() - q.width() * k / 2, br.center().y() - q.height() * k / 2)
            tr.scale(k, k)
            b.setTransform(tr)
            return b
    return QBrush(QColor(lay.get("color", "#FFFFFF")))


def _stroke(path: QPainterPath, width: float) -> QPainterPath:
    st = QPainterPathStroker()
    st.setWidth(width * 2)
    st.setJoinStyle(Qt.RoundJoin)
    return st.createStroke(path)


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


# ------------------------------------------------------------------ palabras con su propio estilo
WORD_KEYS = ("color", "font", "size", "weight", "italic", "outline", "shadow", "glow")
_PALABRA = re.compile(r"\S+")


def word_spans(text: str) -> list[tuple[int, int]]:
    """Dónde está cada palabra del texto: [(inicio, fin)], en orden (las líneas no reinician la cuenta)."""
    return [m.span() for m in _PALABRA.finditer(text or "")]


def words_in_span(text: str, a: int, b: int) -> set[int]:
    """Las palabras que toca el tramo [a, b) del texto."""
    return {i for i, (x, y) in enumerate(word_spans(text)) if x < b and a < y}


def word_view(lay: dict, i: int | None = None) -> dict:
    """La capa tal como la ve la palabra i: el estilo del texto con lo propio de esa palabra encima."""
    own = (lay.get("word_styles") or {}).get(str(i)) if i is not None else None
    return {**lay, **own} if own else lay


def set_word_style(lay: dict, words, **kv):
    """Da a esas palabras un estilo propio. kv: claves de WORD_KEYS, o «outline.color» y similares."""
    total = len(word_spans(lay.get("text", "")))
    styles = dict(lay.get("word_styles") or {})
    for i in words:
        if not 0 <= int(i) < total:
            continue
        own = copy.deepcopy(styles.get(str(int(i))) or {})
        for k, v in kv.items():
            if "." in k:
                a, b = k.split(".", 1)
                own[a] = {**word_view(lay, int(i))[a], **own.get(a, {}), b: v}
            else:
                own[k] = copy.deepcopy(v)
        styles[str(int(i))] = own
    lay["word_styles"] = styles


def clear_word_style(lay: dict, words):
    """Esas palabras vuelven al estilo del texto."""
    styles = {k: v for k, v in (lay.get("word_styles") or {}).items() if int(k) not in {int(i) for i in words}}
    if styles:
        lay["word_styles"] = styles
    else:
        lay.pop("word_styles", None)


def remap_word_styles(old: str, new: str, styles: dict | None) -> dict:
    """Al reescribir el texto, cada estilo sigue a SU palabra (aunque se añadan o quiten otras delante)."""
    if not styles:
        return {}
    def lista(t):
        return [t[a:b].replace("*", "").casefold() for a, b in word_spans(t)]
    va, vb = lista(old), lista(new)
    out: dict[str, dict] = {}
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(a=va, b=vb, autojunk=False).get_opcodes():
        if tag == "equal":
            pares = zip(range(a0, a1), range(b0, b1))
        elif tag == "replace" and a1 - a0 == b1 - b0:        # corregir una palabra no le quita su estilo
            pares = zip(range(a0, a1), range(b0, b1))
        else:
            continue
        for x, y in pares:
            if str(x) in styles:
                out[str(y)] = styles[str(x)]
    return out


def _font_of(v: dict) -> QFont:
    f = QFont(v.get("font", "Impact"))
    f.setPixelSize(max(4, int(v.get("size", 100))))
    f.setWeight(QFont.Weight(int(v.get("weight", 700))))
    f.setItalic(bool(v.get("italic")))
    f.setLetterSpacing(QFont.PercentageSpacing, 100 * float(v.get("spacing", 1.0)))
    return f


def word_layout(lay: dict) -> list[dict]:
    """Cada palabra colocada: [{"i", "rect" (su caja), "path", "accent" (lo que va *entre asteriscos*), "view"}]; las
    coordenadas son las del trazado del texto (ver _word_offset). Las palabras de una línea comparten la línea base y
    la línea mide lo que mida la palabra más alta; el espacio entre palabras es el de la fuente del texto."""
    base = _font_of(lay)
    fmb = QFontMetricsF(base)
    interl = float(lay.get("line", 1.0))
    text = lay.get("text", "")
    if lay.get("uppercase"):
        text = text.upper()
    filas = []
    n = 0
    for raw in text.split("\n"):
        piezas, pos, ancho, asc, alto, on = [], 0, 0.0, 0.0, 0.0, False
        for m in _PALABRA.finditer(raw):
            hueco = raw[pos:m.start()].replace("*", "")
            ancho += fmb.horizontalAdvance(hueco) if hueco else 0.0
            pos = m.end()
            v = word_view(lay, n)
            f = _font_of(v)
            fm = QFontMetricsF(f)
            visible = m.group().replace("*", "")
            w = fm.horizontalAdvance(visible)
            piezas.append({"i": n, "x": ancho, "w": w, "raw": m.group(), "txt": visible, "font": f, "fm": fm, "view": v,
                           "on": on})
            on ^= m.group().count("*") % 2 == 1
            ancho += w
            asc, alto = max(asc, fm.ascent()), max(alto, fm.height())
            n += 1
        cola = raw[pos:].replace("*", "")
        ancho += fmb.horizontalAdvance(cola) if cola else 0.0
        filas.append((piezas, ancho, asc or fmb.ascent(), (alto or fmb.height()) * interl))
    W = max((f[1] for f in filas), default=0.0)
    out, top = [], 0.0
    for piezas, ancho, asc, alto in filas:
        x0 = {"left": 0.0, "right": W - ancho}.get(lay.get("align", "center"), (W - ancho) / 2)
        y = top + asc
        for q in piezas:
            x = x0 + q["x"]
            path, accent = QPainterPath(), QPainterPath()
            path.addText(QPointF(x, y), q["font"], q["txt"])
            if "*" in q["raw"] or q["on"]:
                avance, on = 0, q["on"]
                for run in q["raw"].split("*"):
                    if on and run:
                        accent.addText(QPointF(x + q["fm"].horizontalAdvance(q["txt"][:avance]), y), q["font"], run)
                    avance += len(run)
                    on = not on
            out.append({"i": q["i"], "rect": QRectF(x, y - q["fm"].ascent(), q["w"], q["fm"].height()), "path": path,
                        "accent": accent, "view": q["view"]})
        top += alto
    return out


def _word_margin(lay: dict, ents: list[dict]) -> int:
    grueso = [float(e["view"]["outline"]["width"]) for e in ents if e["view"]["outline"].get("on")]
    return int(max(grueso, default=0.0) + sum(w for _c, w in extra_outlines(lay)) + 4)


def _words_bounds(ents: list[dict]) -> QRectF:
    br = QRectF()
    for e in ents:
        if not e["path"].isEmpty():
            br = br.united(e["path"].boundingRect())
    return br


def _words_content(lay: dict, only: set[int] | None = None) -> np.ndarray:
    """El texto con palabras con estilo propio. only: dibuja solo esas (mismo tamaño de imagen)."""
    ents = word_layout(lay)
    br = _words_bounds(ents)
    m = _word_margin(lay, ents)
    W, H = int(br.width() + 2 * m) + 2, int(br.height() + 2 * m) + 2
    img = QImage(max(2, W), max(2, H), QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.translate(m - br.left(), m - br.top())
    vivos = [e for e in ents if only is None or e["i"] in only]
    extra = extra_outlines(lay)
    for n in range(len(extra), 0, -1):               # los contornos de más, del de fuera al de dentro
        for e in vivos:
            o = e["view"]["outline"]
            base = float(o.get("width", 0)) if o.get("on") else 0.0
            p.fillPath(_stroke(e["path"], base + sum(w for _c, w in extra[:n])), QColor(extra[n - 1][0]))
    for e in vivos:                                  # primero todos los contornos: nunca tapan la letra de al lado
        o = e["view"]["outline"]
        if o.get("on") and float(o.get("width", 0)) > 0:
            p.fillPath(_stroke(e["path"], float(o["width"])), QColor(o["color"]))
    propios = lay.get("word_styles") or {}
    relleno = text_brush(lay, br)                    # (degradado o imagen: sobre todo el texto, sin cortes por palabra)
    for e in vivos:
        if "color" in (propios.get(str(e["i"])) or {}):
            p.fillPath(e["path"], QColor(e["view"].get("color", "#FFFFFF")))
        else:
            p.fillPath(e["path"], relleno)
        if not e["accent"].isEmpty() and "color" not in (propios.get(str(e["i"])) or {}):
            p.fillPath(e["accent"], QColor(lay.get("accent", "#E5232A")))
    p.end()
    return qimage_to_rgba(img)


def word_quads(lay: dict, img: QImage, cw: float, ch: float) -> list[tuple[int, QPolygonF]]:
    """Dónde se ve cada palabra en el lienzo: [(índice, cuadrilátero)], ya con el tamaño, el giro y la deformación."""
    ents = word_layout(lay)
    br = _words_bounds(ents)
    m = _word_margin(lay, ents)
    x0 = (img.width() - cw) / 2 + m - br.left()
    y0 = (img.height() - ch) / 2 + m - br.top()
    t = layer_transform(lay, img)
    return [(e["i"], t.map(QPolygonF(e["rect"].translated(x0, y0)))) for e in ents if not e["path"].isEmpty()]


def _word_fx_groups(lay: dict) -> list | None:
    """Si alguna palabra tiene su propia sombra o su propio brillo: [(transparencia, brillo, sombra)] por cada
    combinación distinta. None = todas las palabras comparten los del texto."""
    styles = lay.get("word_styles") or {}
    if lay.get("liquify") or float(lay.get("blur", 0) or 0) > 0:
        return None
    if not any("glow" in st or "shadow" in st for st in styles.values()):
        return None
    grupos: dict[str, tuple[dict, dict, set[int]]] = {}
    for i in range(len(word_spans(lay.get("text", "")))):
        v = word_view(lay, i)
        k = json.dumps([v["glow"], v["shadow"]], sort_keys=True)
        grupos.setdefault(k, (v["glow"], v["shadow"], set()))[2].add(i)
    return [(_words_content(lay, only)[..., 3].astype(np.float32) / 255.0, g, s) for g, s, only in grupos.values()]


def _vector_content(lay: dict, pad: int) -> np.ndarray:
    """Texto o forma dibujados con Qt (bordes nítidos); el contorno del texto, con trazo real."""
    if lay["kind"] == "text" and lay.get("word_styles"):
        return _words_content(lay)
    path = _text_path(lay) if lay["kind"] == "text" else _shape_path(lay)
    br = path.boundingRect()
    ow = float(lay["outline"]["width"]) if lay["outline"].get("on") else 0.0
    sw = float(lay.get("stroke_w", 0)) if lay["kind"] == "shape" else 0.0
    extra = extra_outlines(lay) if lay["kind"] == "text" else []
    m = int(ow + sum(w for _c, w in extra) + sw + 4)
    W, H = int(br.width() + 2 * m) + 2, int(br.height() + 2 * m) + 2
    img = QImage(max(2, W), max(2, H), QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.translate(m - br.left(), m - br.top())
    for n in range(len(extra), 0, -1):       # ➕ contornos apilados: del de fuera al de dentro
        p.fillPath(_stroke(path, ow + sum(w for _c, w in extra[:n])), QColor(extra[n - 1][0]))
    if ow > 0 and lay["kind"] == "text":     # contorno del texto: trazo grueso por debajo del relleno
        p.fillPath(_stroke(path, ow), QColor(lay["outline"]["color"]))
    if lay["kind"] == "text":
        p.fillPath(path, text_brush(lay, br))
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


def blur_rgba(rgba: np.ndarray, sigma: float) -> np.ndarray:
    """🌫 Desenfoque de una imagen con transparencia (sin halos oscuros: se hace con el color premultiplicado)."""
    if sigma < 0.3:
        return rgba
    a = rgba[..., 3].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * a[..., None]
    rgb = _blur(rgb, sigma)
    a2 = _blur(a, sigma)
    rgb = rgb / np.maximum(a2, 1e-4)[..., None]
    return np.dstack([np.clip(rgb, 0, 255), np.clip(a2 * 255.0, 0, 255)]).astype(np.uint8)


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Desenfoque gaussiano rápido: con sigma grande se hace en pequeño y se amplía (no se nota: es borroso)."""
    if sigma <= 6:
        return cv2.GaussianBlur(a, (0, 0), sigma)
    f = sigma / 6.0
    h, w = a.shape[:2]
    small = cv2.resize(a, (max(1, int(w / f)), max(1, int(h / f))), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 6.0)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _ring(alpha: np.ndarray, r: int) -> np.ndarray:
    """Lo que queda a ≤ r píxeles de lo visible (el contorno), con la distancia: igual de rápido con r grande."""
    dist = cv2.distanceTransform((alpha <= 0.5).astype(np.uint8), cv2.DIST_L2, 3)
    return np.clip(r + 1.0 - dist, 0.0, 1.0)


def _effects(rgba: np.ndarray, lay: dict, scale: float, groups: list | None = None) -> tuple[np.ndarray, int]:
    """Contorno (imágenes recortadas), brillo y sombra a partir de la transparencia. Devuelve (imagen, margen).
    groups (textos con palabras con su propia sombra o brillo): [(transparencia, brillo, sombra)].
    ⚡ En float32 y con OpenCV, que usa todos los núcleos y suelta el bloqueo de Python: antes, una imagen grande con
    sus efectos tardaba ~2 s; y con el color premultiplicado se compone sin dividir en cada capa."""
    k = max(scale, 1e-3)
    ol = lay["outline"]
    anillos = []                                    # contornos tipo «pegatina» (imágenes): el del panel y los de más
    if lay["kind"] == "image":
        if ol.get("on") and float(ol.get("width", 0)) > 0:
            anillos.append((ol["color"], float(ol["width"])))
        anillos += extra_outlines(lay)
    ring_on = bool(anillos)
    fx = groups if groups else [(None, lay["glow"], lay["shadow"])]
    glow_pad = max((int(g["radius"] / k * 2) for _a, g, _s in fx if g.get("on")), default=0)
    shadow_pad = max((int((s["blur"] * 2 + max(abs(s["dx"]), abs(s["dy"]))) / k) for _a, _g, s in fx if s.get("on")),
                     default=0)
    pad = 2 + (sum(int(w / k) + 2 for _c, w in anillos) if ring_on else 0) + glow_pad + shadow_pad
    h, w = rgba.shape[:2]
    if not (ring_on or any(g.get("on") or s.get("on") for _a, g, s in fx)):       # sin efectos: rápido
        return np.pad(rgba, ((pad, pad), (pad, pad), (0, 0))), pad
    H, W = h + 2 * pad, w + 2 * pad

    def con_margen(a_core: np.ndarray) -> np.ndarray:
        return cv2.copyMakeBorder(a_core, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    src = rgba.astype(np.float32) / 255.0
    canales = cv2.split(src)
    a = con_margen(canales[3])
    prem = [con_margen(cv2.multiply(canales[c], canales[3])) for c in range(3)]

    def col(c):
        q = QColor(c)
        return [float(q.redF()), float(q.greenF()), float(q.blueF())]

    def debajo(color, under: np.ndarray):
        """Pone un color sólido con transparencia «under» DEBAJO de lo que ya hay."""
        nonlocal a
        resto = cv2.multiply(under, 1.0 - a)
        for c in range(3):
            prem[c] = cv2.scaleAdd(resto, color[c], prem[c])
        a = cv2.add(a, resto)

    for color, ancho in anillos:                    # contorno tipo «pegatina» alrededor del sujeto (y los de más, por fuera)
        debajo(col(color), _ring(a, max(1, int(ancho / k))).astype(np.float32))
    alpha = a.copy()
    for grupo, g, _s in fx:
        if g.get("on"):
            r = max(1, int(g["radius"] / k))
            base = alpha if grupo is None else con_margen(grupo)
            debajo(col(g["color"]), np.clip(_blur(base, r) * float(g.get("opacity", 0.7)) * 1.6, 0, 1))
    for grupo, _g, sh in fx:
        if sh.get("on"):
            b = max(1, int(sh["blur"] / k))
            dx, dy = int(sh["dx"] / k), int(sh["dy"] / k)
            base = alpha if grupo is None else con_margen(grupo)
            m = _blur(base, b)
            t = np.float32([[1, 0, dx], [0, 1, dy]])
            m = cv2.warpAffine(m, t, (W, H), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP)
            debajo(col(sh["color"]), np.clip(m * float(sh.get("opacity", 0.6)), 0, 1))
    divisor = np.maximum(a, 1e-6)
    out = cv2.merge([cv2.divide(prem[c], divisor) for c in range(3)] + [a])
    return cv2.convertScaleAbs(out, alpha=255.0), pad


_cache: dict[str, tuple[QImage, float, float]] = {}
_base_cache: dict[str, np.ndarray] = {}     # contenido SIN licuar (el pincel «≈ Licuar» solo rehace lo último)
_CACHE_MAX = 500_000_000                    # bytes: con capas grandes, 200 imágenes guardadas podían ser >1 GB
_BASE_MAX = 400_000_000


def _guardar(cache: dict, clave: str, valor, tamano, maximo: int):
    """Guarda en la caché y olvida lo más antiguo si se pasa de memoria (a salvo si otro hilo también la usa)."""
    cache[clave] = valor
    total = sum(tamano(v) for v in list(cache.values()))
    for k in list(cache):
        if total <= maximo or k == clave:
            break
        v = cache.pop(k, None)
        if v is not None:
            total -= tamano(v)


def _key(lay: dict) -> str:
    skip = {"x", "y", "rotation", "opacity", "visible", "locked", "name", "flip", "warp", "blend"}   # (al colocar)
    data = {k: v for k, v in lay.items() if k not in skip}
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _base_key(lay: dict) -> str:
    """Clave del contenido sin licuar ni efectos que se ponen después (sombra, borde, resplandor)."""
    skip = {"x", "y", "rotation", "opacity", "visible", "locked", "name", "flip", "warp", "liquify", "blur", "blend"}
    if lay["kind"] == "image":                       # (en texto y formas el contorno es parte del dibujo)
        skip |= {"shadow", "outline", "outlines", "glow", "scale"}
    data = {k: v for k, v in lay.items() if k not in skip}
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def shrink_k(lay: dict) -> float:
    """Cuánto se reduce una imagen ANTES de dibujarla y de calcular sus efectos: una foto de 4200 px que se ve a ×0.17
    no se procesa a 4200 px (contorno + brillo + sombra tardaban ~10 s por cada cambio). Por saltos (½, ¼, ⅛…), para
    no recalcular con cada pequeño cambio de tamaño, y siempre con ≥ 1,25 veces la resolución con que se ve."""
    if lay["kind"] != "image":
        return 1.0
    need = float(lay.get("scale", 1.0)) * 1.25
    if need >= 1.0:
        return 1.0
    return min(1.0, 2.0 ** math.ceil(math.log2(max(need, 1 / 32))))


def image_k(img: QImage) -> float:
    """La reducción con que se dibujó la imagen de una capa (1 = a tamaño original)."""
    try:
        return float(img.text("k") or 1.0)
    except ValueError:
        return 1.0


def layer_scale(lay: dict, img: QImage) -> float:
    """La escala real de la imagen de la capa en el lienzo (la de la capa, contando la reducción)."""
    return float(lay.get("scale", 1.0)) / image_k(img)


_blank_cache: dict[tuple, QImage] = {}


def _zone_blank(lay: dict) -> tuple[QImage, float, float]:
    """Imagen transparente del tamaño de la zona borrosa (solo para saber su sitio y su recuadro)."""
    W = max(1, int(round(float(lay.get("w", 200)))))
    H = max(1, int(round(float(lay.get("h", 100)))))
    img = _blank_cache.get((W, H))
    if img is None:
        if len(_blank_cache) > 50:
            _blank_cache.clear()
        img = QImage(W, H, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        img.setText("k", "1.0")
        _blank_cache[(W, H)] = img
    return img, float(W), float(H)


def render_layer(lay: dict) -> tuple[QImage, float, float]:
    """(imagen de la capa con sus efectos, ancho y alto «útiles» sin márgenes) — en píxeles de esa imagen (que puede
    venir reducida: image_k); la escala y la rotación se aplican al colocarla (layer_transform)."""
    if lay.get("blur_area"):                         # 🌫 zona borrosa: sin imagen propia (paint_blur_area); solo su sitio
        return _zone_blank(lay)
    k = _key(lay)
    if k in _cache:
        return _cache[k]
    shrink = shrink_k(lay)
    scale = float(lay.get("scale", 1.0)) / shrink
    bk = _base_key(lay) + f"|{shrink}"
    rgba = _base_cache.get(bk)
    if rgba is None:
        rgba = _image_content(lay, shrink) if lay["kind"] == "image" else _vector_content(lay, 0)
        _guardar(_base_cache, bk, rgba, lambda a: a.nbytes, _BASE_MAX)
    if lay.get("liquify"):
        from . import liquify
        rgba = liquify.apply(rgba, lay)
    if float(lay.get("blur", 0) or 0) > 0:           # 🌫 desenfocar la capa entera (en píxeles del lienzo)
        rgba = blur_rgba(rgba, float(lay["blur"]) / max(scale, 1e-3))
    core_h, core_w = rgba.shape[:2]
    groups = _word_fx_groups(lay) if lay["kind"] == "text" and lay.get("word_styles") else None
    rgba, _pad = _effects(rgba, lay, scale, groups)
    # ⚡ el formato nativo de Qt: dibujarla en el lienzo no la convierte cada vez
    img = rgba_to_qimage(rgba).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    img.setText("k", repr(shrink))
    img.setText("cw", repr(float(core_w)))
    img.setText("ch", repr(float(core_h)))
    res = (img, core_w, core_h)
    _guardar(_cache, k, res, lambda v: v[0].sizeInBytes(), _CACHE_MAX)
    return res


_fx_cache: dict[str, tuple] = {}            # efectos ya hechos SIN licuar (vista rápida mientras se licua)


def is_rendered(lay: dict) -> bool:
    """¿La capa tal como está ya está dibujada (en caché)?"""
    return _key(lay) in _cache


def draft_k(lay: dict, view: float) -> float:
    """Reducción para la vista rápida: la resolución con que se VE en pantalla (view = píxeles de pantalla por píxel
    del lienzo), por octavos para no recalcular con cada pequeño movimiento; nunca más que shrink_k (la buena)."""
    sk = shrink_k(lay)
    if lay["kind"] != "image":
        return sk
    need = float(lay.get("scale", 1.0)) * max(float(view), 1e-3)     # px de pantalla por px de la imagen
    return min(sk, max(1 / 16, math.ceil(need * 8) / 8))


def render_layer_draft(lay: dict, kd: float | None = None) -> tuple[QImage, float, float]:
    """Vista rápida mientras se arrastra ≈ Licuar / ✋ Estirar: el contorno, el brillo y la sombra se calculan UNA vez
    (sin licuar) y en cada toque solo se deforma esa imagen ya hecha (~20–40 ms en vez de 1–3 s). Mismo tamaño y
    margen que render_layer, así que se coloca igual. Al soltar se dibuja la buena con render_layer.
    kd: la reducción de la vista rápida (draft_k); None = la de shrink_k."""
    if lay["kind"] != "image" or not lay.get("liquify"):
        return render_layer(lay)
    fx, pad, cw, ch, k = draft_effects(lay, kd)
    from . import liquify
    img = rgba_to_qimage(liquify.apply_padded(fx, lay, pad, cw, ch))
    img.setText("k", repr(k))
    return img, cw, ch


def draft_render(lay: dict, kd: float | None = None, prev: dict | None = None) -> tuple:
    """render_layer_draft con memoria: prev es el estado del toque anterior (de la misma capa y reducción). Si solo
    cambió el licuado, se rehace solo el rectángulo tocado (liquify.apply_padded_update). Devuelve
    (imagen, ancho, alto, estado para el siguiente toque)."""
    if lay["kind"] != "image" or not lay.get("liquify"):
        img, cw, ch = render_layer(lay)
        return img, cw, ch, None
    fx, pad, cw, ch, k = draft_effects(lay, kd)
    from . import liquify
    out = None
    if prev is not None and prev.get("fx") is fx and liquify.apply_padded_update(
            prev["out"], fx, lay, pad, cw, ch, prev["field"]):
        out = prev["out"]                                    # (se actualiza en sitio: solo lo tocado)
    if out is None:
        out = liquify.apply_padded(fx, lay, pad, cw, ch)
    img = rgba_to_qimage(out)
    img.setText("k", repr(k))
    return img, cw, ch, {"fx": fx, "out": out, "field": liquify.field(lay)}


def draft_effects(lay: dict, kd: float | None = None) -> tuple:
    """Los efectos de la capa SIN licuar (para la vista rápida). Se puede llamar antes, en segundo plano, al activar
    ≈ Licuar / ✋ Estirar: así el primer toque tampoco espera. kd: la reducción (draft_k); None = shrink_k."""
    kd = shrink_k(lay) if kd is None else float(kd)
    scale = float(lay.get("scale", 1.0)) / kd
    fk = _key({k: v for k, v in lay.items() if k != "liquify"}) + f"|{kd}"
    got = _fx_cache.get(fk)
    if got is None:
        bk = _base_key(lay) + f"|{kd}"
        rgba = _base_cache.get(bk)
        if rgba is None:
            rgba = _image_content(lay, kd)
            _guardar(_base_cache, bk, rgba, lambda a: a.nbytes, _BASE_MAX)
        ch, cw = rgba.shape[:2]
        if float(lay.get("blur", 0) or 0) > 0:       # 🌫 (también en la vista rápida, si la capa está desenfocada)
            rgba = blur_rgba(rgba, float(lay["blur"]) / max(scale, 1e-3))
        fx, pad = _effects(rgba, lay, scale)
        if len(_fx_cache) > 4:
            _fx_cache.clear()
        got = _fx_cache[fk] = (fx, pad, cw, ch)
    return (*got, kd)


def layer_transform(lay: dict, img: QImage, warp: bool = True) -> QTransform:
    """De píxeles de la imagen de la capa a píxeles del lienzo (centro en x, y). Con ◇ Deformar, antes la
    perspectiva de sus 4 esquinas (warp=False: sin ella, para saber dónde estaría la capa sin deformar)."""
    s = layer_scale(lay, img)
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


def _core_size(lay: dict, img: QImage) -> tuple[float, float]:
    """Ancho y alto del contenido de esa imagen (lo lleva apuntado: así no hay que volver a dibujar la capa)."""
    if img.text("cw"):
        return float(img.text("cw")), float(img.text("ch"))
    _img, cw, ch = render_layer(lay)
    return cw, ch


def content_quad(lay: dict, img: QImage) -> QPolygonF:
    """Las 4 esquinas del contenido (sin los márgenes de sombra o brillo), en píxeles de la imagen de la capa."""
    cw, ch = _core_size(lay, img)
    x0, y0 = (img.width() - cw) / 2, (img.height() - ch) / 2
    return QPolygonF(QRectF(x0, y0, cw, ch))


def warp_transform(lay: dict, img: QImage) -> QTransform | None:
    w = warp_of(lay)
    if w is None:
        return None
    cw, ch = _core_size(lay, img)
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


def render_alone(doc: dict, lay: dict) -> QImage:
    """Una sola capa, en su sitio, sobre transparente y al tamaño de la miniatura (para 🪄 Combinar)."""
    out = QImage(int(doc["w"]), int(doc["h"]), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    img, _w, _h = render_layer(lay)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setOpacity(float(lay.get("opacity", 1.0)))
    p.setTransform(layer_transform(lay, img))
    p.drawImage(0, 0, img)
    p.end()
    return out


# ------------------------------------------------------------- 🌫 zona borrosa (desenfoca lo que hay debajo)
_under_cache: dict[str, np.ndarray] = {}     # lo de debajo ya desenfocado (mover la zona no lo rehace)


def render_below(doc: dict, index: int, scale: float = 1.0) -> QImage:
    """Lo que hay DEBAJO de la capa número index: fondo y capas anteriores visibles, a la escala dada."""
    return render({**doc, "layers": doc["layers"][:index]}, scale)


def _under_key(doc: dict, index: int, scale: float) -> str:
    parts = [json.dumps(doc.get("bg") or {}, sort_keys=True), repr((doc["w"], doc["h"], scale))]
    for lay in doc["layers"][:index]:
        parts.append(_key(lay) + repr((lay.get("x"), lay.get("y"), lay.get("rotation"), lay.get("opacity"),
                                       lay.get("visible", True), lay.get("flip"), lay.get("warp"), lay.get("blend"))))
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def blurred_below(doc: dict, index: int, lay: dict, scale: float = 1.0) -> np.ndarray:
    """Lo de debajo de la zona, ya desenfocado con su fuerza (RGBA). Se guarda: mover la zona no lo rehace."""
    radius = float(lay["blur_area"].get("radius", 18))
    key = hashlib.md5(f"{_under_key(doc, index, scale)}|{radius}".encode()).hexdigest()
    got = _under_cache.get(key)
    if got is None:
        if len(_under_cache) > 6:
            _under_cache.clear()
        got = _under_cache[key] = blur_rgba(qimage_to_rgba(render_below(doc, index, scale)), radius * scale)
    return got


def paint_blur_area(p: QPainter, doc: dict, index: int, lay: dict, scale: float = 1.0):
    """Pinta una zona borrosa: lo de debajo desenfocado, recortado a su círculo o cuadrado con el borde suave (~1 px).
    p ya está en coordenadas del lienzo (como en render); scale: la escala de la exportación (1 en el lienzo)."""
    img, _cw, _ch = render_layer(lay)
    t = layer_transform(lay, img)
    s = float(scale)
    box = t.map(_shape_path(lay)).boundingRect()
    px0, py0 = max(0, int(math.floor(box.left() * s)) - 4), max(0, int(math.floor(box.top() * s)) - 4)
    px1, py1 = int(math.ceil(box.right() * s)) + 4, int(math.ceil(box.bottom() * s)) + 4
    under = blurred_below(doc, index, lay, s)
    px1, py1 = min(px1, under.shape[1]), min(py1, under.shape[0])
    if px1 <= px0 or py1 <= py0:
        return
    m = QImage(px1 - px0, py1 - py0, QImage.Format_ARGB32)
    m.fill(Qt.transparent)
    q = QPainter(m)
    q.setRenderHint(QPainter.Antialiasing)
    q.setTransform(t * QTransform().scale(s, s).translate(-px0 / s, -py0 / s))   # (lienzo → máscara, con la forma)
    q.fillPath(_shape_path(lay), QColor(255, 255, 255))
    q.end()
    alpha = qimage_to_rgba(m)[..., 3].astype(np.float32) / 255.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), max(0.5, s))         # borde suave
    out = np.dstack([under[py0:py1, px0:px1, :3], np.clip(alpha * 255, 0, 255).astype(np.uint8)])
    p.drawImage(QRectF(px0 / s, py0 / s, (px1 - px0) / s, (py1 - py0) / s), rgba_to_qimage(out))


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
    for i, lay in enumerate(doc["layers"]):
        if not lay.get("visible", True):
            continue
        p.save()
        p.setOpacity(float(lay.get("opacity", 1.0)))
        if lay.get("blur_area"):                 # 🌫 zona borrosa: lo de debajo, desenfocado
            paint_blur_area(p, doc, i, lay, scale)
            p.restore()
            continue
        img, _w, _h = render_layer(lay)
        p.setCompositionMode(blend_mode(lay))
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


# ------------------------------------------------------------------ 🖼 huecos (plantillas) y cambiar la imagen
FX_KEYS = ("outline", "outlines", "shadow", "glow", "blend", "feather", "fade")


def box_size(lay: dict) -> tuple[float, float]:
    """Ancho y alto de lo que se ve de la capa en el lienzo (sin girar ni deformar)."""
    if lay.get("slot") or lay["kind"] == "shape":
        return float(lay.get("w", 200)) * float(lay.get("scale", 1.0)), float(lay.get("h", 100)) * float(lay.get("scale", 1.0))
    img, cw, ch = render_layer(lay)
    s = layer_scale(lay, img)
    return cw * s, ch * s


def slot_from(lay: dict, size=None) -> dict:
    """La capa convertida en hueco del mismo tamaño y sitio (con sus efectos: al poner la imagen, los recupera).
    size: su ancho y alto en el lienzo, si ya se saben (p. ej. de una plantilla cuya imagen ya no está)."""
    w, h = size or box_size(lay)
    hueco = _base("shape", "🖼 Hueco", float(lay["x"]), float(lay["y"]))
    hueco.update(shape="rect", w=round(w, 1), h=round(h, 1), fill="#2A2A33", stroke="#8A8A99", stroke_w=3, radius=0,
                 gradient={"on": False, "c1": "#E8742F", "c2": "#B13B1F", "angle": 90}, slot=True)
    for k in ("rotation", "opacity", "warp") + FX_KEYS:
        if k in lay:
            hueco[k] = copy.deepcopy(lay[k])
    hueco["id"] = lay.get("id") or hueco["id"]
    return hueco


def fill_box(old: dict, path: str, doc: dict, name: str | None = None) -> dict:
    """Una capa de imagen nueva con esa foto que ocupa justo la caja de old (un hueco o una imagen): misma posición,
    giro y efectos; la foto se recorta por el centro para tener la misma forma (sin deformarse)."""
    W, H = box_size(old)
    nueva = image_layer(path, doc, (name or os.path.splitext(os.path.basename(path))[0])[:30])
    from PySide6.QtGui import QImageReader
    sz = QImageReader(path).size()
    iw, ih = max(1, sz.width()), max(1, sz.height())
    ar, iar = max(W, 1e-3) / max(H, 1e-3), iw / ih
    if iar > ar:
        c = ar / iar
        crop = [(1 - c) / 2, 0.0, (1 + c) / 2, 1.0]
    else:
        c = iar / ar
        crop = [0.0, (1 - c) / 2, 1.0, (1 + c) / 2]
    nueva["crop"] = [round(v, 5) for v in crop]
    nueva["scale"] = round(W / (iw * (crop[2] - crop[0])), 5)
    nueva["x"], nueva["y"] = float(old["x"]), float(old["y"])
    for k in ("rotation", "opacity", "flip", "warp") + FX_KEYS:
        if k in old:
            nueva[k] = copy.deepcopy(old[k])
    return nueva
