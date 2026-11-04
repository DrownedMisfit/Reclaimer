"""
Dibuja los subtítulos en el visor con el mismo estilo que tendrán al exportar
(mismas medidas que el archivo .ass: tamaño, contorno, caja, posición, animaciones).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core.model import SubtitleStyle
from ..core.subtitles import Cue
from ..export.ass_subtitles import metrics

ANIM = 0.12  # duración de las animaciones de entrada/salida (s)


def active_word(cue: Cue, t: float) -> int | None:
    """Índice de la palabra que está sonando (modo karaoke)."""
    words = cue.words
    for i, w in enumerate(words):
        start = cue.start if i == 0 else w.start
        end = words[i + 1].start if i + 1 < len(words) else cue.end
        if start <= t < end:
            return w.index
    return None


def _resolve(family: str) -> QFont:
    """La fuente pedida; si Qt no conoce ese nombre («Segoe UI Black», «Arial Black»: nombres de Windows), se busca
    como familia + estilo («Segoe UI» + «Black») en vez de caer en Arial sin avisar."""
    from PySide6.QtGui import QFontDatabase, QFontInfo
    font = QFont(family)
    if QFontInfo(font).family().lower() == family.lower() or " " not in family:
        return font
    fam, style = family.rsplit(" ", 1)
    if style in QFontDatabase.styles(fam):
        f2 = QFont(fam)
        f2.setStyleName(style)
        return f2
    return font


def make_font(style: SubtitleStyle, size: float) -> QFont:
    font = _resolve(style.font)
    if not font.styleName():
        font.setBold(style.bold)
    font.setPixelSize(max(1, round(size)))
    # En ASS el tamaño equivale a la altura de línea: se ajusta para que coincida
    h = QFontMetricsF(font).height()
    if h > 0:
        font.setPixelSize(max(1, round(size * size / h)))
    return font


def paint_subtitle(p: QPainter, cue: Cue, style: SubtitleStyle, t: float, W: int, H: int):
    size, outline, margin = metrics(style, H)
    font = make_font(style, size)
    fm = QFontMetricsF(font)
    line_h = fm.height()
    space = fm.horizontalAdvance(" ")
    n = len(cue.lines)
    block_h = n * line_h
    if style.position == "top":
        top = margin
    elif style.position == "middle":
        top = (H - block_h) / 2
    else:
        top = H - margin - block_h

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    if style.animation == "fade":
        p.setOpacity(max(0.0, min(1.0, (t - cue.start) / ANIM, (cue.end - t) / ANIM)))
    elif style.animation == "pop":
        s = 0.8 + 0.2 * max(0.0, min(1.0, (t - cue.start) / ANIM))
        cx, cy = W / 2, top + block_h / 2
        p.translate(cx, cy)
        p.scale(s, s)
        p.translate(-cx, -cy)

    emph = set(style.emphasis)
    active = active_word(cue, t) if style.animation == "karaoke" else None
    normal, hl = QColor(style.color), QColor(style.highlight)
    paths: list[tuple[QPainterPath, QColor]] = []
    boxes: list[QRectF] = []
    for li, line in enumerate(cue.lines):
        widths = [fm.horizontalAdvance(w.text) for w in line]
        total = sum(widths) + space * (len(line) - 1)
        x = (W - total) / 2
        line_top = top + li * line_h
        if style.box:
            pad = max(outline, size * 0.18)
            boxes.append(QRectF(x - pad, line_top - pad * 0.35, total + 2 * pad, line_h + pad * 0.7))
        baseline = line_top + fm.ascent()
        for w, wd in zip(line, widths):
            path = QPainterPath()
            path.addText(QPointF(x, baseline), font, w.text)
            paths.append((path, hl if (w.index in emph or w.index == active) else normal))
            x += wd + space

    shadow = float(getattr(style, "shadow", 0.0) or 0.0) / 100 * H
    if shadow > 0 and not boxes:          # sombra suave: la letra desplazada abajo, oscura y difuminada
        for k in range(5, 0, -1):
            pen = QPen(QColor(0, 0, 0, 34), shadow * 0.45 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            for path, _c in paths:
                sp_ = path.translated(shadow * 0.35, shadow * 0.6)
                p.strokePath(sp_, pen)
                p.fillPath(sp_, QColor(0, 0, 0, 40))
    if boxes:
        c = QColor(style.box_color)
        c.setAlphaF(style.box_opacity)
        for r in boxes:
            p.fillRect(r, c)
    elif outline > 0:
        pen = QPen(QColor(style.outline_color), 2 * outline, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        for path, _c in paths:
            p.strokePath(path, pen)
    for path, color in paths:
        p.fillPath(path, color)
    p.restore()


class SubtitleItem(QGraphicsItem):
    """Capa de subtítulos encima del video en el visor."""

    def __init__(self):
        super().__init__()
        self.setZValue(10)
        self._W, self._H = 1920, 1080
        self._cue: Cue | None = None
        self._style: SubtitleStyle | None = None
        self._t = 0.0
        self._key = None

    def set_size(self, W: int, H: int):
        self.prepareGeometryChange()
        self._W, self._H = W, H
        self._key = None
        self.update()

    def set_state(self, cue: Cue | None, style: SubtitleStyle | None, t: float):
        self._cue, self._style, self._t = cue, style, t
        if cue is None or style is None:
            key = None
        else:
            animating = style.animation in ("fade", "pop") and (
                t - cue.start < ANIM or cue.end - t < ANIM)
            key = (cue.start, cue.text(), active_word(cue, t) if style.animation == "karaoke" else None,
                   repr(style), round(t, 2) if animating else None)
        if key != self._key:
            self._key = key
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._W, self._H)

    def paint(self, painter, _option, _widget=None):
        if self._cue is not None and self._style is not None:
            paint_subtitle(painter, self._cue, self._style, self._t, self._W, self._H)


_TITLE_CACHE: dict = {}


def paint_title(p: QPainter, text: dict, t_in_clip: float, duration: float, W: int, H: int):
    """Un texto en pantalla: el mismo dibujo que se exporta (core/title_render.py), con su fundido."""
    from ..core import title_render
    key = (repr(sorted(text.items())), W, H)
    hit = _TITLE_CACHE.get(key)
    if hit is None:
        if len(_TITLE_CACHE) > 80:
            _TITLE_CACHE.clear()
        hit = _TITLE_CACHE[key] = title_render.render(text, W, H)
    img, pos = hit
    fade = 0.15
    p.save()
    p.setOpacity(max(0.0, min(1.0, t_in_clip / fade, (duration - t_in_clip) / fade)))
    p.drawImage(pos, img)
    p.restore()


class TitlesItem(QGraphicsItem):
    """Capa de textos en pantalla en el visor."""

    def __init__(self):
        super().__init__()
        self.setZValue(9)
        self._W, self._H = 1920, 1080
        self._items: list[tuple[dict, float, float]] = []
        self._key = None

    def set_size(self, W: int, H: int):
        self.prepareGeometryChange()
        self._W, self._H = W, H
        self.update()

    def set_items(self, items: list[tuple[dict, float, float]]):
        """[(texto, segundos desde que empezó, duración)]"""
        key = tuple((repr(t), round(a, 2) if (a < 0.2 or d - a < 0.2) else None, d) for t, a, d in items)
        self._items = items
        if key != self._key:
            self._key = key
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._W, self._H)

    def paint(self, painter, _option, _widget=None):
        for text, a, d in self._items:
            paint_title(painter, text, a, d, self._W, self._H)
