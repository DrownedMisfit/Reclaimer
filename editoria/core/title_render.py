"""
Dibujo de los TEXTOS EN PANTALLA (como el «Texto» de DaVinci Resolve): el mismo dibujo se usa en el visor y al
exportar (se exporta como imagen encima del video), así lo que ves es exactamente lo que sale.

Opciones de cada texto (clip.text):
  content · font · font_style (Bold, Condensed…) · bold · italic · underline · strike · case (normal|upper|lower|title)
  color · size (% del alto) · tracking (interletrado, % del tamaño) · line_spacing (interlineado, % del tamaño)
  align (left|center|right) · x, y (centro, fracción del lienzo) · zoom_x, zoom_y · rotation (grados)
  stroke_color · stroke_size (% del tamaño) · stroke_outside
  shadow · shadow_color · shadow_x, shadow_y (% del tamaño) · shadow_blur · shadow_opacity
  box · box_color · box_outline_color · box_outline_width · box_width, box_height (margen, % del tamaño)
  box_radius (esquinas, % del alto de la caja) · box_cx, box_cy (desplazamiento) · box_opacity
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QTransform

# Valores de fábrica (los textos antiguos sin estas claves se ven igual que antes: ver _get)
FACTORY = {
    "content": "Texto", "font": "Arial", "font_style": "", "bold": True, "italic": False, "underline": False,
    "strike": False, "case": "normal", "color": "#FFFFFF", "size": 6.0, "tracking": 0.0, "line_spacing": 0.0,
    "align": "center", "x": 0.5, "y": 0.12, "zoom_x": 1.0, "zoom_y": 1.0, "rotation": 0.0,
    "stroke_color": "#000000", "stroke_size": 0.0, "stroke_outside": True,
    "shadow": False, "shadow_color": "#000000", "shadow_x": 4.0, "shadow_y": 4.0, "shadow_blur": 20.0,
    "shadow_opacity": 0.75,
    "box": True, "box_color": "#000000", "box_outline_color": "#000000", "box_outline_width": 0.0,
    "box_width": 22.0, "box_height": 10.0, "box_radius": 0.0, "box_cx": 0.0, "box_cy": 0.0, "box_opacity": 0.6,
    # mientras se ve el texto, lo que hay debajo (los videos/imágenes) se desenfoca (0 = no, 1 = mucho)
    "blur_under": 0.0,
}
BLUR_UNDER_DEFAULT = 0.5      # los textos que añades tú lo traen activado
STYLE_KEYS = [k for k in FACTORY if k != "content"]


def _get(t: dict, k: str):
    if k in t:
        return t[k]
    if k == "stroke_size" and not t.get("box", True):
        return 7.0           # los textos de antes sin caja llevaban un contorno negro
    return FACTORY[k]


def apply_case(s: str, case: str) -> str:
    if case == "upper":
        return s.upper()
    if case == "lower":
        return s.lower()
    if case == "title":
        return s.title()
    return s


def make_font(t: dict, px: float) -> QFont:
    fam = str(_get(t, "font"))
    style = str(_get(t, "font_style") or "")
    f = QFontDatabase.font(fam, style, 12) if style else QFont(fam)
    f.setPixelSize(max(1, int(round(px))))
    if not style:
        f.setBold(bool(_get(t, "bold")))
    f.setItalic(bool(_get(t, "italic")) or f.italic())
    f.setUnderline(bool(_get(t, "underline")))
    f.setStrikeOut(bool(_get(t, "strike")))
    tr = float(_get(t, "tracking"))
    if tr:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tr / 100 * px)
    return f


def render(t: dict, W: int, H: int) -> tuple[QImage, QPointF]:
    """El texto dibujado en una imagen transparente recortada a su tamaño, y dónde va en el lienzo."""
    px = float(_get(t, "size")) / 100 * H
    font = make_font(t, px)
    fm = QFontMetricsF(font)
    lines = apply_case(str(t.get("content", "")), str(_get(t, "case"))).split("\n")
    line_h = fm.height() + float(_get(t, "line_spacing")) / 100 * px
    widths = [fm.horizontalAdvance(s) for s in lines]
    tw = max(widths or [0.0])
    th = line_h * len(lines) - (line_h - fm.height())
    align = str(_get(t, "align"))
    # Trayectos de cada línea, con el bloque centrado en (0, 0)
    path = QPainterPath()
    for i, (s, w) in enumerate(zip(lines, widths)):
        x = -tw / 2 + (0 if align == "left" else (tw - w if align == "right" else (tw - w) / 2))
        path.addText(QPointF(x, -th / 2 + i * line_h + fm.ascent()), font, s)
    stroke = float(_get(t, "stroke_size")) / 100 * px
    box_on = bool(_get(t, "box"))
    pad_x = float(_get(t, "box_width")) / 100 * px
    pad_y = float(_get(t, "box_height")) / 100 * px
    box = QRectF(-tw / 2 - pad_x, -th / 2 - pad_y, tw + 2 * pad_x, th + 2 * pad_y).translated(
        float(_get(t, "box_cx")) / 100 * px, float(_get(t, "box_cy")) / 100 * px)
    sh_on = bool(_get(t, "shadow"))
    sdx, sdy = float(_get(t, "shadow_x")) / 100 * px, float(_get(t, "shadow_y")) / 100 * px
    sblur = max(0.0, float(_get(t, "shadow_blur"))) / 100 * px
    # Tamaño de la imagen: todo lo que se dibuja, con margen para el contorno y la sombra
    bound = path.boundingRect().united(box if box_on else QRectF())
    m = stroke + 4 + (abs(sdx) + abs(sdy) + 3 * sblur if sh_on else 0) + float(_get(t, "box_outline_width")) / 100 * px
    bound = bound.adjusted(-m, -m, m, m)
    zx, zy, rot = float(_get(t, "zoom_x")), float(_get(t, "zoom_y")), float(_get(t, "rotation"))
    tf = QTransform().rotate(-rot).scale(zx, zy)
    outer = tf.mapRect(bound)
    iw, ih = max(1, int(math.ceil(outer.width()))), max(1, int(math.ceil(outer.height())))
    img = QImage(iw, ih, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    base = QTransform().translate(-outer.left(), -outer.top()) * QTransform()
    p.setTransform(tf * base)

    def draw_main(painter: QPainter, solid: QColor | None = None):
        if box_on:
            c = QColor(solid or _get(t, "box_color"))
            c.setAlphaF(float(_get(t, "box_opacity")) if solid is None else c.alphaF())
            r = float(_get(t, "box_radius")) / 100 * box.height()
            ow = float(_get(t, "box_outline_width")) / 100 * px
            pen = QPen(QColor(solid or _get(t, "box_outline_color")), ow) if ow > 0 else Qt.NoPen
            painter.setPen(pen)
            painter.setBrush(c)
            painter.drawRoundedRect(box, r, r)
        outside = bool(_get(t, "stroke_outside"))
        sp = QPen(QColor(solid or _get(t, "stroke_color")), stroke * (2 if outside else 1),
                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if stroke > 0 and outside:      # solo afuera: el trazo va debajo de la letra
            painter.strokePath(path, sp)
        painter.fillPath(path, QColor(solid or _get(t, "color")))
        if stroke > 0 and not outside:  # centrado: encima del borde de la letra
            painter.strokePath(path, sp)

    if sh_on:   # sombra: la misma forma, de un color, desplazada y desenfocada
        sh = QImage(iw, ih, QImage.Format_ARGB32_Premultiplied)
        sh.fill(Qt.transparent)
        sp = QPainter(sh)
        sp.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        sp.setTransform(tf * QTransform().translate(-outer.left() + sdx, -outer.top() + sdy))
        col = QColor(_get(t, "shadow_color"))
        draw_main(sp, col)
        sp.end()
        if sblur > 0.5:
            import cv2
            import numpy as np
            a = np.frombuffer(sh.constBits(), np.uint8, count=sh.bytesPerLine() * ih).reshape(ih, sh.bytesPerLine())
            a = a[:, :iw * 4].reshape(ih, iw, 4)
            k = int(sblur) * 2 + 1
            blurred = cv2.GaussianBlur(a, (k, k), sblur / 2)
            sh = QImage(blurred.data, iw, ih, iw * 4, QImage.Format_ARGB32_Premultiplied).copy()
        p.save()
        p.resetTransform()
        p.setOpacity(float(_get(t, "shadow_opacity")))
        p.drawImage(0, 0, sh)
        p.restore()
    draw_main(p)
    p.end()
    cx, cy = float(_get(t, "x")) * W, float(_get(t, "y")) * H
    return img, QPointF(cx + outer.left(), cy + outer.top())


def text_rect(t: dict, W: int, H: int) -> QRectF:
    """Dónde queda el texto en el lienzo (para arrastrarlo en el visor)."""
    img, pos = render(t, W, H)
    return QRectF(pos.x(), pos.y(), img.width(), img.height())


# ------------------------------------------------------------------ «mi estilo» (memoria de tus valores)
def my_style() -> dict:
    """Tus valores recordados (lo último que cambiaste de cada opción)."""
    import json
    from PySide6.QtCore import QSettings
    try:
        d = json.loads(str(QSettings("EditorIA", "EditorIA").value("texto/mi_estilo", "{}")))
    except ValueError:
        d = {}
    return {k: v for k, v in d.items() if k in STYLE_KEYS}


def remember_style(props: dict):
    import json
    from PySide6.QtCore import QSettings
    d = my_style()
    d.update({k: v for k, v in props.items() if k in STYLE_KEYS})
    QSettings("EditorIA", "EditorIA").setValue("texto/mi_estilo", json.dumps(d))


def remembering() -> bool:
    from PySide6.QtCore import QSettings
    return str(QSettings("EditorIA", "EditorIA").value("texto/recordar", "true")).lower() == "true"
