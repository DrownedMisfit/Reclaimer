"""
Dibuja los subtítulos en el visor con el mismo estilo que tendrán al exportar
(mismas medidas que el archivo .ass: tamaño, contorno, caja, posición, animaciones).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core.model import SubtitleStyle
from ..core.subtitles import Cue, CueWord, glow_color_at, scale_at, words_shown
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


def _layout(cue: Cue, style: SubtitleStyle, W: int, H: int, shown: int | None = None):
    """Dónde va cada palabra: (fuente, métricas, arriba, alto del bloque, [(palabra, x, arriba de su línea, ancho,
    nº de línea)]). Con «palabra a palabra» solo las «shown» primeras, cada línea centrada con lo que ya se ve (el
    alto del bloque es el de la frase entera: el texto no sube ni baja al aparecer la 2.ª línea)."""
    size, _outline, margin = metrics(style, H)
    font = make_font(style, size)
    fm = QFontMetricsF(font)
    line_h = fm.height()
    space = fm.horizontalAdvance(" ")
    block_h = len(cue.lines) * line_h
    if style.position == "top":
        top = margin
    elif style.position == "middle":
        top = (H - block_h) / 2
    else:
        top = H - margin - block_h
    left = len(cue.words) if shown is None else shown
    placed = []
    for li, line in enumerate(cue.lines):
        vis = line[:max(0, left)]
        left -= len(line)
        if not vis:
            continue
        widths = [fm.horizontalAdvance(w.text) for w in vis]
        total = sum(widths) + space * (len(vis) - 1)
        x = (W - total) / 2
        line_top = top + li * line_h
        for w, wd in zip(vis, widths):
            placed.append((w, x, line_top, wd, li))
            x += wd + space
    return font, fm, top, block_h, placed


_GLOW_SMALL = 3.0      # el resplandor se difumina en pequeño (rápido) y se amplía suave


def _paint_glow(p: QPainter, paths: list, color: str, radius: float):
    """Halo difuminado del color pedido alrededor de las letras (debajo de ellas). Mismo dibujo en el visor y al
    exportar (las imágenes de la exportación salen de esta misma función)."""
    import cv2
    import numpy as np
    from PySide6.QtGui import QImage
    if radius <= 0 or not paths:
        return
    br = QRectF()
    for path, _c in paths:
        br = br.united(path.boundingRect())
    br = br.adjusted(-3 * radius, -3 * radius, 3 * radius, 3 * radius)
    f = min(0.5, _GLOW_SMALL / radius)
    sw, sh = max(2, int(br.width() * f) + 2), max(2, int(br.height() * f) + 2)
    small = QImage(sw, sh, QImage.Format_ARGB32_Premultiplied)
    small.fill(0)
    q = QPainter(small)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(f, f)
    q.translate(-br.left(), -br.top())
    pen = QPen(QColor(255, 255, 255), radius * 0.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    for path, _c in paths:
        q.fillPath(path, QColor(255, 255, 255))
        q.strokePath(path, pen)
    q.end()
    bpl = small.bytesPerLine()
    alpha = np.frombuffer(small.constBits(), np.uint8, count=bpl * sh).reshape(sh, bpl // 4, 4)[:, :sw, 3]
    blur = cv2.GaussianBlur(alpha.astype(np.float32) / 255.0, (0, 0), max(0.8, radius * f))
    al = np.clip(blur * 1.4, 0.0, 1.0) * 0.85
    c = QColor(color)
    out = np.empty((sh, sw, 4), np.uint8)              # BGRA premultiplicado (Format_ARGB32_Premultiplied)
    out[..., 0] = np.round(al * c.blue()).astype(np.uint8)
    out[..., 1] = np.round(al * c.green()).astype(np.uint8)
    out[..., 2] = np.round(al * c.red()).astype(np.uint8)
    out[..., 3] = np.round(al * 255).astype(np.uint8)
    img = QImage(out.data, sw, sh, sw * 4, QImage.Format_ARGB32_Premultiplied).copy()
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF(br.left(), br.top(), sw / f, sh / f), img)
    p.restore()


def paint_subtitle(p: QPainter, cue: Cue, style: SubtitleStyle, t: float, W: int, H: int):
    size, outline, margin = metrics(style, H)
    font, fm, top, block_h, placed = _layout(cue, style, W, H, words_shown(cue, style, t))
    line_h = fm.height()

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    sx, sy = scale_at(cue, style, t)          # estirón al cambiar de frase y golpe final
    if style.animation == "fade":
        p.setOpacity(max(0.0, min(1.0, (t - cue.start) / ANIM, (cue.end - t) / ANIM)))
    elif style.animation == "pop":
        s = 0.8 + 0.2 * max(0.0, min(1.0, (t - cue.start) / ANIM))
        sx, sy = sx * s, sy * s
    if abs(sx - 1) > 1e-6 or abs(sy - 1) > 1e-6:
        cx, cy = W / 2, top + block_h / 2
        p.translate(cx, cy)
        p.scale(sx, sy)
        p.translate(-cx, -cy)

    emph = set(style.emphasis)
    active = active_word(cue, t) if style.animation == "karaoke" else None
    normal, hl = QColor(style.color), QColor(style.highlight)
    paths: list[tuple[QPainterPath, QColor]] = []
    boxes: list[QRectF] = []
    lines: dict[int, list] = {}
    for w, x, line_top, wd, li in placed:
        lines.setdefault(li, []).append((x, line_top, wd))
        path = QPainterPath()
        path.addText(QPointF(x, line_top + fm.ascent()), font, w.text)
        paths.append((path, hl if (w.index in emph or w.index == active) else normal))
    if style.box:
        pad = max(outline, size * 0.18)
        for row in lines.values():
            x0, line_top = row[0][0], row[0][1]
            total = row[-1][0] + row[-1][2] - x0
            boxes.append(QRectF(x0 - pad, line_top - pad * 0.35, total + 2 * pad, line_h + pad * 0.7))

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
    glow = float(getattr(style, "glow", 0.0) or 0.0) / 100 * H
    if glow > 0:                          # ✨ halo difuminado (blanco; magenta en las frases fuertes)
        _paint_glow(p, paths, glow_color_at(cue, style, t), glow)
    if not boxes and outline > 0:
        pen = QPen(QColor(style.outline_color), 2 * outline, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        for path, _c in paths:
            p.strokePath(path, pen)
    for path, color in paths:
        p.fillPath(path, color)
    p.restore()


def word_rects(cue: Cue, style: SubtitleStyle, W: int, H: int,
               t: float | None = None) -> list[tuple[CueWord, QRectF]]:
    """Dónde cae cada palabra del subtítulo: el mismo cálculo que paint_subtitle (sin la animación de entrada).
    Con «t» y «palabra a palabra», solo las que ya se ven (donde se ven en ese momento)."""
    shown = words_shown(cue, style, t) if t is not None else None
    _font, fm, _top, _bh, placed = _layout(cue, style, W, H, shown)
    return [(w, QRectF(x, line_top, wd, fm.height())) for w, x, line_top, wd, _li in placed]


def render_key(cue: Cue, style: SubtitleStyle, t: float) -> tuple:
    """Lo que cambia el dibujo de un subtítulo en t (si es igual, el dibujo es idéntico): sirve al visor para no
    repintar y a la exportación para hacer una imagen solo cuando cambia algo."""
    sx, sy = scale_at(cue, style, t)
    anim = None
    if style.animation in ("fade", "pop") and (t - cue.start < ANIM or cue.end - t < ANIM):
        anim = round(t, 3)
    return (words_shown(cue, style, t), round(sx, 4), round(sy, 4),
            glow_color_at(cue, style, t) if float(getattr(style, "glow", 0) or 0) > 0 else None,
            active_word(cue, t) if style.animation == "karaoke" else None, anim)


def subtitle_band(cues: list[Cue], style: SubtitleStyle, W: int, H: int) -> tuple[int, int]:
    """(arriba, alto) de la franja de la pantalla donde puede caer el texto de estas frases: el alto del bloque
    ×1,25 (el golpe final lo agranda) + el halo, el contorno y la sombra. Las imágenes de la exportación se recortan
    a esta franja (mucho más pequeñas que la pantalla entera) y se colocan con overlay y=."""
    from ..core.subtitles import PUNCH_S
    if not cues:
        return 0, 2
    size, outline, _margin = metrics(style, H)
    glow = float(getattr(style, "glow", 0.0) or 0.0) / 100 * H
    shadow = float(getattr(style, "shadow", 0.0) or 0.0) / 100 * H
    extra = 3 * glow + 2 * outline + 3.5 * shadow + size * 0.3
    k = max(1.25, PUNCH_S if getattr(style, "fx_punch", False) else 1.0)
    y0, y1 = float(H), 0.0
    seen = set()
    for c in cues:
        n = len(c.lines)
        if n in seen:
            continue
        seen.add(n)
        _f, _fm, top, block_h, _p = _layout(c, style, W, H, 0)
        cy = top + block_h / 2
        y0 = min(y0, cy - block_h * k / 2 - extra)
        y1 = max(y1, cy + block_h * k / 2 + extra)
    y0 = max(0, int(y0) // 2 * 2)
    y1 = min(H, int(y1 + 0.999))
    return y0, max(2, y1 - y0)


def _subs_key(cues: list[Cue], style: SubtitleStyle, W: int, H: int, fps: float, total: float) -> str:
    import hashlib
    sig = repr((W, H, round(fps, 4), round(total, 4), repr(style),
                [(round(c.start, 4), round(c.end, 4), c.punch,
                  [(round(w.start, 4), w.text, w.index) for w in c.words]) for c in cues]))
    return hashlib.md5(sig.encode("utf-8")).hexdigest()


def raster_subtitles(cues: list[Cue], style: SubtitleStyle, W: int, H: int, fps: float, total: float,
                     out_dir: str, progress=None, cancelled=None) -> str:
    """Para exportar los subtítulos que un .ass no sabe hacer igual (resplandor, palabra a palabra, estirón,
    golpe, cambio de color): una imagen PNG por cada cambio, dibujada con paint_subtitle (lo mismo que el visor) y
    recortada a la franja del texto (subtitle_band), y una lista «ffconcat» con cuándo empieza cada una. Se evalúa
    en cada fotograma de la exportación (n / fps), igual que el visor en ese instante. Va en segundo plano (nunca
    en el hilo de la ventana): progress(0–1) y cancelled() → RuntimeError("Cancelado."). Si ya está hecho lo mismo
    (p. ej. al reintentar con el procesador), no se repite. Devuelve la ruta de la lista."""
    import bisect
    import math
    import os
    import shutil
    from PySide6.QtGui import QImage
    lst = os.path.join(out_dir, "subtitulos.ffconcat")
    done = os.path.join(out_dir, "listo.txt")
    key = _subs_key(cues, style, W, H, fps, total)
    try:
        with open(done, encoding="utf-8") as f:
            if f.read().strip() == key and os.path.exists(lst):
                return lst
    except OSError:
        pass
    shutil.rmtree(out_dir, ignore_errors=True)          # (la carpeta es solo de esta exportación)
    os.makedirs(out_dir, exist_ok=True)
    y0, bh = subtitle_band(cues, style, W, H)
    blank = os.path.join(out_dir, "sub_vacio.png")
    img = QImage(W, bh, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    img.save(blank, "PNG")
    starts = [c.start for c in cues]
    fps = float(fps) or 30.0
    entries: list[tuple[float, str]] = []
    prev = ("—",)
    count = 0
    nframes = int(math.ceil(total * fps)) + 1
    for n in range(nframes):
        if n % 240 == 0:
            if cancelled is not None and cancelled():
                raise RuntimeError("Cancelado.")
            if progress is not None:
                progress(n / nframes)
        t = n / fps
        k = bisect.bisect_right(starts, t) - 1
        cue = cues[k] if k >= 0 and t < cues[k].end else None
        rk = None if cue is None else (k,) + render_key(cue, style, t)
        if rk == prev:
            continue
        prev = rk
        if cue is None:
            path = blank
        else:
            count += 1
            path = os.path.join(out_dir, f"sub_{count:05d}.png")
            img = QImage(W, bh, QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            ptr = QPainter(img)
            ptr.translate(0, -y0)
            paint_subtitle(ptr, cue, style, t, W, H)
            ptr.end()
            img.save(path, "PNG", 80)        # (poca compresión: mucho más rápido y casi igual de pequeño)
        # Empieza medio fotograma antes: el fotograma n la coge seguro (la lista va en milisegundos)
        entries.append((max(0.0, (n - 0.5) / fps) if entries else 0.0, path))
    entries.append((max(total, entries[-1][0] + 1.0 / fps), blank))
    out = ["ffconcat version 1.0"]
    for i, (a, path) in enumerate(entries):
        out.append(f"file {os.path.basename(path)}")
        out.append("option framerate 1000")       # (base de tiempo de 1 ms: si no, se redondea a 1/25 s)
        if i + 1 < len(entries):
            out.append(f"duration {entries[i + 1][0] - a:.6f}")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(done, "w", encoding="utf-8") as f:
        f.write(key)
    if progress is not None:
        progress(1.0)
    return lst


class SubtitleItem(QGraphicsItem):
    """Capa de subtítulos encima del video en el visor."""

    def __init__(self):
        super().__init__()
        self.setZValue(10)
        # Caché en coordenadas del dispositivo: el texto se dibuja solo al cambiar (set_state/set_size lo invalidan)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
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

    def cue_words(self) -> list[CueWord]:
        """Las palabras del subtítulo que se ve ahora (vacío si no hay ninguno)."""
        return self._cue.words if (self._cue is not None and self._style is not None) else []

    def word_at(self, pt: QPointF) -> tuple[CueWord, QRectF] | None:
        """La palabra del subtítulo bajo el punto (escena) y su rectángulo; también vale el hueco entre palabras
        dentro del texto (entonces, la más cercana en esa línea). None si el punto está fuera del texto."""
        rects = word_rects(self._cue, self._style, self._W, self._H, self._t) if self.cue_words() else []
        if not rects:
            return None
        pad = max(6.0, self._H * 0.008)
        for w, r in rects:
            if r.adjusted(-pad, -pad, pad, pad).contains(pt):
                return w, r
        box = QRectF()
        for _w, r in rects:
            box = box.united(r)
        if not box.adjusted(-pad, -pad, pad, pad).contains(pt):
            return None
        same_line = [(w, r) for w, r in rects if r.top() <= pt.y() <= r.bottom()] or rects
        return min(same_line, key=lambda wr: abs(wr[1].center().x() - pt.x()))

    def set_state(self, cue: Cue | None, style: SubtitleStyle | None, t: float):
        self._cue, self._style, self._t = cue, style, t
        if cue is None or style is None:
            key = None
        else:
            key = (cue.start, cue.text(), cue.punch, repr(style), render_key(cue, style, t))
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
    try:
        fade = max(0.001, min(float(text.get("fade", 0.15)), duration / 3 if duration > 0 else 0.15))
    except (TypeError, ValueError):
        fade = 0.15
    p.save()
    p.setOpacity(max(0.0, min(1.0, t_in_clip / fade, (duration - t_in_clip) / fade)))
    if text.get("pos_kf"):           # 📌 pegado a un objeto: se mueve con él (como al exportar)
        from ..core.motion_track import text_offset_at
        dx, dy = text_offset_at(text, t_in_clip)
        pos = QPointF(pos.x() + dx * W, pos.y() + dy * H)
    p.drawImage(pos, img)
    p.restore()


class TitlesItem(QGraphicsItem):
    """Capa de textos en pantalla en el visor."""

    def __init__(self):
        super().__init__()
        self.setZValue(9)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)   # (se invalida en set_items y set_size)
        self._W, self._H = 1920, 1080
        self._items: list[tuple[dict, float, float]] = []
        self._key = None

    def set_size(self, W: int, H: int):
        self.prepareGeometryChange()
        self._W, self._H = W, H
        self.update()

    def set_items(self, items: list[tuple[dict, float, float]]):
        """[(texto, segundos desde que empezó, duración)]"""
        key = tuple((repr(t), round(a, 2) if (a < 0.2 or d - a < 0.2 or t.get("pos_kf")) else None, d)
                    for t, a, d in items)          # (📌 un texto pegado a un objeto cambia en cada fotograma)
        self._items = items
        if key != self._key:
            self._key = key
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._W, self._H)

    def paint(self, painter, _option, _widget=None):
        for text, a, d in self._items:
            paint_title(painter, text, a, d, self._W, self._H)
