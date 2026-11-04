"""
Revisión de miniaturas: ¿se entiende en pequeño? ¿el texto se lee? ¿la cara se ve?

  simulate(doc, …)   → cómo se verá en YouTube (inicio, sugeridos, móvil) o en Shorts, a tamaño real
  analyze(doc)       → avisos claros, cada uno con su arreglo («Aplicar»)
  auto_improve(doc)  → ajustes suaves y razonables (no satura ni llena de efectos)
"""
from __future__ import annotations

import copy

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath

from . import thumbnail as T

# Tamaños reales en pantalla (ancho en píxeles) donde la gente ve tu miniatura
YT_SIZES = [("Inicio (escritorio)", 360), ("Móvil", 246), ("Videos sugeridos", 168)]
SHORTS_SIZES = [("Estante de Shorts", 180), ("Shorts en móvil", 140)]


def _lum(c: QColor) -> float:
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast_ratio(a: float, b: float) -> float:
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def simulate(doc: dict, width: int, title: str = "", duration: str = "12:34", dark: bool = True) -> QImage:
    """La miniatura a tamaño real con lo que YouTube pone encima (duración, o la interfaz de Shorts)."""
    short = doc["format"] == "short"
    img = T.render(doc, width / doc["w"])
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if short:   # Shorts: degradado y título abajo, como en el estante
        h = img.height()
        for i in range(int(h * 0.3)):
            a = int(150 * i / (h * 0.3))
            p.fillRect(QRectF(0, h - h * 0.3 + i, img.width(), 1), QColor(0, 0, 0, a))
        f = QFont("Segoe UI", max(6, int(width * 0.065)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(width * 0.06, h * 0.78, width * 0.88, h * 0.2), Qt.TextWordWrap, title[:60])
    else:       # sello de duración abajo a la derecha
        f = QFont("Segoe UI", max(6, int(width * 0.033)))
        f.setBold(True)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(duration) + width * 0.025
        th = p.fontMetrics().height() + 1
        r = QRectF(img.width() - tw - width * 0.02, img.height() - th - width * 0.02, tw, th)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        p.fillPath(path, QColor(0, 0, 0, 205))
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignCenter, duration)
    p.end()
    return img


# --------------------------------------------------------------------- análisis
def _visible(doc, kind=None):
    return [l for l in doc["layers"] if l.get("visible", True) and (kind is None or l["kind"] == kind)]


def _bbox(lay: dict) -> QRectF:
    from PySide6.QtGui import QPolygonF, QTransform
    img, cw, ch = T.render_layer(lay)
    t = T.layer_transform(lay, img)
    x0, y0 = (img.width() - cw) / 2, (img.height() - ch) / 2
    return t.map(QPolygonF(QRectF(x0, y0, cw, ch))).boundingRect()


def _is_background(doc, lay) -> bool:
    b = _bbox(lay)
    return lay["kind"] == "image" and b.width() >= doc["w"] * 0.95 and b.height() >= doc["h"] * 0.95


def _region_lum(doc: dict, rect: QRectF, without: str) -> float:
    d = copy.deepcopy(doc)
    d["layers"] = [l for l in d["layers"] if l["id"] != without]
    img = T.render(d, 0.25)
    arr = T.qimage_to_rgba(img).astype(np.float32)
    x0, y0 = int(max(0, rect.left() * 0.25)), int(max(0, rect.top() * 0.25))
    x1, y1 = int(min(arr.shape[1], rect.right() * 0.25)), int(min(arr.shape[0], rect.bottom() * 0.25))
    if x1 <= x0 or y1 <= y0:
        return 0.5
    reg = arr[y0:y1, x0:x1, :3].mean(axis=(0, 1))
    return _lum(QColor(int(reg[0]), int(reg[1]), int(reg[2])))


def analyze(doc: dict) -> list[dict]:
    """[{level: "ok"|"warn"|"tip", text, fix: {...} | None}] — fix lo aplica apply_fix()."""
    out = []
    W, H = doc["w"], doc["h"]
    short = doc["format"] == "short"
    small_w = 168 if not short else 140
    texts = _visible(doc, "text")
    # 1) Cantidad de texto
    words = sum(len(l["text"].split()) for l in texts)
    if words > 5:
        out.append({"level": "warn", "text": f"Hay {words} palabras. En una miniatura suelen funcionar 1–4: "
                    "el título ya cuenta el resto.", "fix": None})
    elif texts:
        out.append({"level": "ok", "text": f"Poco texto ({words} palabras): bien.", "fix": None})
    for lay in texts:
        name = lay["text"].replace("\n", " ")[:24]
        b = _bbox(lay)
        # 2) ¿Se lee en pequeño? (altura de las letras a tamaño de «sugeridos»)
        px = lay["size"] * lay["scale"] * 0.72 * small_w / W
        if px < 9:
            k = 11 / max(px, 0.1)
            out.append({"level": "warn", "text": f"«{name}» se pierde en pequeño (letras de {px:.0f} px en "
                        "«sugeridos»).", "fix": {"layer": lay["id"], "action": "grow_text", "label": "Agrandar el texto"}})
        else:
            out.append({"level": "ok", "text": f"«{name}» se lee en pequeño.", "fix": None})
        # 3) Contraste con lo que tiene detrás
        bg_l = _region_lum(doc, b, lay["id"])
        fg_l = _lum(QColor(lay["color"]))
        cr = contrast_ratio(fg_l, bg_l)
        helped = lay["outline"]["on"] or lay["shadow"]["on"] or lay["glow"]["on"]
        if cr < 3 and not helped:
            # Fondo oscuro → letras blancas con contorno negro; fondo claro → letras oscuras con contorno blanco
            fill, line = ("#FFFFFF", "#000000") if bg_l < 0.4 else ("#111111", "#FFFFFF")
            out.append({"level": "warn", "text": f"«{name}» tiene poco contraste con el fondo ({cr:.1f}:1).",
                        "fix": {"layer": lay["id"], "color": fill, "outline.on": True, "outline.color": line,
                                "outline.width": max(6, int(lay["size"] * 0.07)), "label": "Dar contraste"}})
        # 4) Zonas que tapa YouTube
        if not short:
            stamp = QRectF(W * 0.82, H * 0.84, W * 0.18, H * 0.16)
            if b.intersects(stamp):
                out.append({"level": "warn", "text": f"La duración del video tapará parte de «{name}» "
                            "(esquina inferior derecha).", "fix": {"layer": lay["id"], "action": "avoid_zones",
                                                                  "label": "Apartarlo"}})
        else:
            if b.top() < H * 0.1 or b.bottom() > H * 0.75:
                out.append({"level": "warn", "text": f"En Shorts, la interfaz tapa arriba y abajo: «{name}» queda "
                            "en una zona tapada.", "fix": {"layer": lay["id"], "action": "avoid_zones",
                                                          "label": "Moverlo a la zona libre"}})
    # 5) Caras: ¿se ven?
    img = T.render(doc, 0.5)
    rgba = T.qimage_to_rgba(img)
    try:
        from ..ai.tracking import detect_faces
        faces = detect_faces(cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2BGR))
    except Exception:  # noqa: BLE001
        faces = []
    if faces:
        fx, fy, fw, fh, _c = faces[0]
        if fh < 0.2:
            cx, cy = (fx + fw / 2) * W, (fy + fh / 2) * H
            owner = next((l for l in reversed(_visible(doc, "image"))
                          if not _is_background(doc, l) and _bbox(l).contains(cx, cy)), None)
            fix = None
            if owner is not None:
                fix = {"layer": owner["id"], "scale": round(owner["scale"] * min(2.0, 0.28 / fh), 3),
                       "label": "Agrandar la cara"}
            out.append({"level": "warn", "text": f"La cara es pequeña ({fh * 100:.0f} % del alto). Las caras "
                        "grandes (25–40 %) se reconocen mejor en pequeño.", "fix": fix})
        else:
            out.append({"level": "ok", "text": f"La cara se ve bien ({fh * 100:.0f} % del alto).", "fix": None})
    # 6) Demasiados elementos
    elems = [l for l in doc["layers"] if l.get("visible", True) and not _is_background(doc, l)]
    if len(elems) > 5:
        out.append({"level": "tip", "text": f"Hay {len(elems)} elementos: con 2–4 el ojo entiende la miniatura "
                    "más rápido.", "fix": None})
    # 7) El fondo compite con el sujeto
    bgs = [l for l in _visible(doc, "image") if _is_background(doc, l)]
    if bgs and elems:
        bg = bgs[0]
        a = bg["adj"]
        if a.get("blur", 0) < 0.1 and a.get("exposure", 0) > -0.2:
            out.append({"level": "tip", "text": "El fondo compite con lo principal: desenfocarlo y oscurecerlo un "
                        "poco hace que destaque el sujeto.",
                        "fix": {"layer": bg["id"], "adj.blur": 0.22, "adj.exposure": -0.35, "label": "Separar el fondo"}})
    # 8) Contraste y saturación de toda la imagen
    lum = rgba[..., :3].astype(np.float32).mean(axis=2) / 255
    if lum.std() < 0.14:
        out.append({"level": "tip", "text": "La imagen en conjunto es plana (poco contraste): en pequeño se "
                    "verá apagada.", "fix": {"improve": True, "label": "Mejorar automáticamente"}})
    hsv = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2HSV)
    if hsv[..., 1].mean() / 255 > 0.62:
        out.append({"level": "tip", "text": "Está muy saturada: se ve más profesional con colores un poco "
                    "más moderados.", "fix": {"desaturate": True, "label": "Moderar colores"}})
    if not [o for o in out if o["level"] in ("warn", "tip")]:
        out.insert(0, {"level": "ok", "text": "✓ Todo en orden: se entiende a tamaño pequeño.", "fix": None})
    return out


def apply_fix(doc: dict, fix: dict) -> dict:
    d = copy.deepcopy(doc)
    if fix.get("improve"):
        return auto_improve(d)
    if fix.get("desaturate"):
        for l in d["layers"]:
            if l["kind"] == "image":
                l["adj"]["saturation"] = round(l["adj"].get("saturation", 0) - 0.15, 3)
        return d
    lay = next((l for l in d["layers"] if l["id"] == fix.get("layer")), None)
    if lay is None:
        return d
    act = fix.get("action")
    W, H = d["w"], d["h"]
    if act == "grow_text":   # que las letras midan ~11 px en «sugeridos» (calculado ahora, no antes)
        small_w = 140 if d["format"] == "short" else 168
        px = lay["size"] * lay["scale"] * 0.72 * small_w / W
        lay["scale"] = round(lay["scale"] * 11 / max(px, 0.1), 3)
        words = lay["text"].split()
        for n in (2, 3):   # si así no cabe a lo ancho, repartirlo en 2–3 líneas equilibradas
            if _bbox(lay).width() <= W * 0.94 or len(words) < n:
                break
            per = -(-len(words) // n)
            lay["text"] = "\n".join(" ".join(words[i:i + per]) for i in range(0, len(words), per))
        act = "avoid_zones"   # al crecer, que no se meta en las zonas tapadas ni se salga
    if act == "avoid_zones":
        for _ in range(3):
            b = _bbox(lay)
            m = 0.03 * W
            if b.width() > W - 2 * m:          # más ancho que el lienzo: reducir
                lay["scale"] = round(lay["scale"] * (W - 2 * m) / b.width(), 3)
                b = _bbox(lay)
            if d["format"] == "short":
                top, bottom = H * 0.1, H * 0.75
                if b.top() < top:
                    lay["y"] += top - b.top()
                elif b.bottom() > bottom:
                    lay["y"] -= b.bottom() - bottom
            else:
                stamp = QRectF(W * 0.82, H * 0.84, W * 0.18, H * 0.16)
                if b.intersects(stamp):   # moverlo lo mínimo: a la izquierda o hacia arriba
                    dx, dy = b.right() - stamp.left() + m, b.bottom() - stamp.top() + m
                    if dx < dy:
                        lay["x"] -= dx
                    else:
                        lay["y"] -= dy
            b = _bbox(lay)   # y dentro del lienzo
            if b.left() < m:
                lay["x"] += m - b.left()
            if b.right() > W - m:
                lay["x"] -= b.right() - (W - m)
            if b.top() < m:
                lay["y"] += m - b.top()
            if b.bottom() > H - m:
                lay["y"] -= b.bottom() - (H - m)
        return d
    for k, v in fix.items():
        if k in ("layer", "label", "action"):
            continue
        if "." in k:
            a, b = k.split(".")
            lay[a][b] = v
        else:
            lay[k] = v
    return d


def auto_improve(doc: dict) -> dict:
    """Ajustes suaves que casi siempre ayudan, sin cambiar el estilo: un poco más de contraste y nitidez en
    las imágenes, el fondo algo separado del sujeto y contorno en los textos que no se leen."""
    d = copy.deepcopy(doc)
    flat = float(T.qimage_to_rgba(T.render(d, 0.25))[..., :3].astype(np.float32).mean(axis=2).std()) / 255 < 0.14
    for l in d["layers"]:
        if l["kind"] != "image" or not l.get("visible", True):
            continue
        a = l["adj"]
        if _is_background(d, l) and len(d["layers"]) > 1:
            a["blur"] = max(a.get("blur", 0), 0.15)
            a["exposure"] = min(a.get("exposure", 0), -0.2)
            a["vignette"] = max(a.get("vignette", 0), 0.35)
        else:
            a["contrast"] = round(min(0.4, a.get("contrast", 0) + (0.22 if flat else 0.1)), 3)
            a["sharpen"] = round(max(a.get("sharpen", 0), 0.35), 3)
            a["saturation"] = round(min(0.25, a.get("saturation", 0) + 0.06), 3)
    for f in analyze(d):
        fx = f.get("fix") or {}
        if "outline.on" in fx:
            d = apply_fix(d, fx)
    return d
