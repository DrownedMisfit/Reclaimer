"""
Panel central: visor del video y motor de reproducción.

El "reloj" de la timeline manda. En cada momento se mira qué clip hay bajo el cabezal
(en la pista de video visible más alta y en cada pista de audio) y se sincroniza
un reproductor para cada uno.
"""
from __future__ import annotations

import bisect

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRectF, QSettings, QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (QLineEdit, QGraphicsEffect, QFrame, QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import audio_fx, curves, effects, transform, transitions
from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_TEXT, TRACK_VIDEO
from ..core.subtitles import styled_cues
from .common import fmt_tc, fmt_time
from .subtitle_item import SubtitleItem, TitlesItem


VIDEO_POOL = 3   # reproductores por pista de video (un archivo abierto en cada uno)


def _decor_box(c, W: int, H: int, layout="clip"):
    """Con sombra o contorno, la imagen se encoge un poco dentro de su caja (igual que al exportar).
    layout: la disposición de ESE momento (🎞 si está animada); por defecto, la fija del clip."""
    from ..core import decor
    lay = c.layout if layout == "clip" else layout
    if not decor.has_frame(c.fx):
        return lay
    box = dict(lay or transform.FULL)
    m, ow = decor.margins(c.fx, W, H)
    px = m + ow
    box.update(x=box["x"] + px / W, y=box["y"] + px / H, w=max(0.02, box["w"] - 2 * px / W),
               h=max(0.02, box["h"] - 2 * px / H), fit="contain", bg="none")
    return box


def _soft_blur(img: QImage, sigma: float, gain: float) -> QImage:
    """Desenfoque gaussiano suave (OpenCV) y un poco más oscuro; si no hay OpenCV, la imagen tal cual."""
    try:
        import cv2
        import numpy as np
        im = img.convertToFormat(QImage.Format_RGB888)
        w, h, bpl = im.width(), im.height(), im.bytesPerLine()
        arr = np.frombuffer(im.constBits(), np.uint8, bpl * h).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3)
        out = cv2.GaussianBlur(arr, (0, 0), sigma)
        out = cv2.convertScaleAbs(out, alpha=gain)
        out = np.ascontiguousarray(out)
        return QImage(out.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    except Exception:  # noqa: BLE001 - el fondo nunca debe romper el visor
        return img


class TrackLayer:
    """Una capa del visor por cada pista de video: una "caja" (su sitio en pantalla) con el
    video o la imagen dentro, con su zoom. Igual que al exportar."""

    def __init__(self, scene: QGraphicsScene):
        self.box = QGraphicsRectItem()
        self.box.setPen(QPen(Qt.NoPen))
        self.box.setBrush(QBrush(Qt.black))
        self.box.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        scene.addItem(self.box)
        # Fondo desenfocado (Shorts): el mismo clip, ampliado, borroso y algo más oscuro
        self.bg = QGraphicsPixmapItem(self.box)
        self.bg.setTransformationMode(Qt.SmoothTransformation)
        self.bg.hide()
        self._bg_src: QImage | None = None
        self._bg_time = QElapsedTimer()
        self._bg_time.start()
        self._want_bg = False
        self._bg_every = 33          # ms entre fondos (se ajusta solo según lo que tarde: 16–200)
        self._bg_cost = 0.0
        self._bw = self._bh = 1.0
        # Varios videos por pista (uno visible): cada archivo del edit queda abierto en el suyo, así cambiar
        # de plano no obliga a abrir el archivo otra vez (los cortes rápidos no se traban)
        # ▭ Marco del video: sin barras negras, recorta justo a la zona con imagen (el archivo entero queda detrás,
        # desplazado y ampliado, como al exportar); con barras, no recorta nada (igual que antes)
        self.clip = QGraphicsRectItem(self.box)
        self.clip.setPen(QPen(Qt.NoPen))
        self.clip.setBrush(QBrush(Qt.NoBrush))
        self._bars = None
        self.videos = []
        for _i in range(VIDEO_POOL):
            v = QGraphicsVideoItem(self.clip)
            v.setAspectRatioMode(Qt.IgnoreAspectRatio)
            v.hide()
            self.videos.append(v)
        self.active = 0
        self.video = self.videos[0]
        self.image = QGraphicsPixmapItem(self.box)
        self.image.setTransformationMode(Qt.SmoothTransformation)
        # ▦ Relleno: la propia imagen ampliada y desenfocada en TODA la pantalla, justo detrás de la caja
        self.fill = QGraphicsPixmapItem()
        self.fill.setTransformationMode(Qt.SmoothTransformation)
        scene.addItem(self.fill)
        self.fill.hide()
        self._fill_p = None
        self._W = self._H = 1.0
        self._image_path: str | None = None
        self._pix = QPixmap()
        # Capa de efectos encima del clip: destello blanco o fundido a negro
        self.fx = QGraphicsRectItem(self.box)
        self.fx.setPen(QPen(Qt.NoPen))
        self.fx.setZValue(10)
        self.fx.hide()
        self.vig = QGraphicsRectItem(self.box)   # viñeta (efecto de imagen)
        self.vig.setPen(QPen(Qt.NoPen))
        self.vig.setZValue(9)
        self.vig.hide()
        self.bars = [QGraphicsRectItem(self.box), QGraphicsRectItem(self.box)]   # barras de cine
        for b in self.bars:
            b.setPen(QPen(Qt.NoPen))
            b.setBrush(QBrush(Qt.black))
            b.setZValue(11)
            b.hide()
        self.neg = _InvertItem(self.box)           # «impact frame»: imagen en negativo
        self.neg.setZValue(10.5)   # debajo de las barras: el negativo no las vuelve blancas
        self.neg.hide()
        self._mirror = False
        self._fg_h = 0.0
        self.live_regions: list | None = None     # zonas mientras las arrastras en el visor
        for i, v in enumerate(self.videos):
            v.videoSink().videoFrameChanged.connect(lambda f, i=i: self._on_frame(f, i))
        self._geom = None
        self.hide()

    def set_active(self, i: int):
        """El video visible de la capa (el reproductor del plano que suena)."""
        if i == self.active:
            return
        self.active = i
        self.video = self.videos[i]
        if self._geom is not None and self._geom[0] == "video":
            for k, v in enumerate(self.videos):
                v.setVisible(k == i)

    def _on_frame(self, frame, i: int = 0):
        """El fondo desenfocado / el reflejo sigue al video fotograma a fotograma (antes, 5 veces por segundo:
        se veía a saltos). Si a tu PC le cuesta, se espacia solo para no frenar la imagen principal."""
        if i != self.active or not (self._want_bg or self._fill_p) or self._bg_time.elapsed() < self._bg_every:
            return
        self._bg_time.restart()
        t = QElapsedTimer()
        t.start()
        img = frame.toImage()
        if not img.isNull():
            self._set_bg_source(img)
        cost = t.nsecsElapsed() / 1e6
        self._bg_cost = cost if self._bg_cost == 0 else 0.8 * self._bg_cost + 0.2 * cost
        self._bg_every = int(min(200, max(16, self._bg_cost * 3)))

    def _set_bg_source(self, img: QImage):
        b = self._bars
        if b and not img.isNull():                 # ▭ sin barras: el fondo desenfocado tampoco las lleva
            w, h = img.width(), img.height()
            img = img.copy(int(b[0] * w), int(b[1] * h), max(2, int(b[2] * w)), max(2, int(b[3] * h)))
        self._bg_src = img.scaledToWidth(160, Qt.SmoothTransformation)   # (antes 48 px: se veía pixelado)
        self._update_bg()

    def _update_fill(self):
        """▦ Relleno en el visor (como al exportar): llena la pantalla (× zoom), desenfocado y oscurecido."""
        r = self._fill_p
        src = self._bg_src
        if not r or src is None or src.isNull():
            self.fill.hide()
            return
        W, H = self._W, self._H
        qw, qh = max(2, int(W / 4)), max(2, int(H / 4))
        s = max(qw / src.width(), qh / src.height()) * r["zoom"]
        big = src.scaled(max(1, int(src.width() * s)), max(1, int(src.height() * s)), Qt.IgnoreAspectRatio,
                         Qt.SmoothTransformation)
        big = big.copy((big.width() - qw) // 2, (big.height() - qh) // 2, qw, qh)
        sig = 0.3 + 2.6 * r["desenfoque"]
        pix = QPixmap.fromImage(_soft_blur(big, sig, max(0.05, 1.0 - 0.75 * r["oscurecer"])))
        self.fill.setPixmap(pix)
        self.fill.setScale(W / max(1, pix.width()))
        self.fill.setPos(0, 0)
        self.fill.setZValue(self.box.zValue() - 0.5)
        self.fill.show()

    def _update_bg(self):
        if self._bg_src is None or self._bg_src.isNull():
            return
        if self._fill_p:
            self._update_fill()
        if not self._want_bg:
            return
        bw, bh = self._bw, self._bh
        src = self._bg_src
        if self._mirror:
            self._update_mirror(src, bw, bh)
            return
        # Ampliar para llenar la caja (cover) a 1/4 de tamaño y desenfoque gaussiano de verdad (como al exportar)
        s = max(bw / src.width(), bh / src.height())
        big = src.scaled(max(1, int(src.width() * s / 4)), max(1, int(src.height() * s / 4)),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pix = QPixmap.fromImage(_soft_blur(big, 7.0, 0.76))
        self.bg.setPixmap(pix)
        self.bg.setScale(4.0)
        self.bg.setPos((bw - pix.width() * 4) / 2, (bh - pix.height() * 4) / 2)

    def _update_mirror(self, src: QImage, bw: float, bh: float):
        """Edits: el clip y, arriba y abajo, copias como el original (o en espejo si «flip»), borrosas."""
        k = 4.0
        w = max(1, int(bw / k))
        fh = max(1.0, self._fg_h / k)                 # alto del clip dentro de la caja
        img = QImage(w, max(1, int(bh / k)), QImage.Format_RGB32)
        img.fill(Qt.black)
        tile = src.scaled(w, max(1, int(round(fh))), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if getattr(self, "_flip", False):
            flipped = tile.flipped(Qt.Vertical) if hasattr(tile, "flipped") else tile.mirrored(False, True)
        else:
            flipped = tile                                  # copias como el original (sin voltear)
        painter = QPainter(img)
        y0 = (img.height() - fh) / 2
        i = 0
        while y0 - i * fh > -fh or y0 + i * fh < img.height():
            for y in {y0 - i * fh, y0 + i * fh}:
                painter.drawImage(QPointF(0, y), flipped if i % 2 else tile)
            i += 1
        painter.end()
        self.bg.setPixmap(QPixmap.fromImage(_soft_blur(img, 2.2, 0.73)))
        self.bg.setScale(k)
        self.bg.setPos(0, 0)

    def set_color(self, color: dict | None):
        """Corrección de color del clip (pestaña «Color» del Inspector)."""
        self._color = color

    def set_post(self, post: list):
        """🎨 Capas de ajuste que hay ENCIMA de esta capa ahora: [(color, fx, mezcla 0–1)] (se aplican después)."""
        self._post = post

    def set_blend(self, mode: str, opacity: float):
        """Modo de fusión (pantalla, multiplicar…) y opacidad del clip en este instante."""
        self._blend = mode or "normal"
        self.box.setOpacity(max(0.0, min(1.0, opacity)))

    def _set_look(self, fx: dict | None):
        """Efectos de imagen en el visor (aproximados): blanco y negro, desenfoque y viñeta, y el color del
        clip (exacto: la misma tabla que al exportar). El grano, el glitch y el tono se ven al exportar."""
        from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsColorizeEffect
        from ..core import color as C
        fx = fx or {}
        col = getattr(self, "_color", None)
        ckey = None if C.is_neutral(col) else C.key(col)
        blend = getattr(self, "_blend", "normal")
        regions = self.live_regions if self.live_regions is not None else effects.blur_regions(fx)
        rkey = tuple(tuple(sorted(r.items())) for r in regions)
        from ..core import chroma as CK
        from ..core import motion_key as MKY
        chroma = CK.of(fx)
        mkey = MKY.of(fx)
        from ..core import subject_mask as SMK
        smask = SMK.of(fx) if self._geom and self._geom[0] == "video" else None
        content = None
        if mkey or smask:
            item = self.image if self.image.isVisible() else self.video
            content = self.box.mapRectFromScene(item.sceneBoundingRect()).intersected(self.box.rect())
        key = (bool(fx.get("bw") or fx.get("oldfilm")), round(float(fx.get("blur", 0) or 0), 2), ckey, blend, rkey,
               (round(self.box.rect().width()), round(self.box.rect().height())),
               tuple(sorted(chroma.items())) if chroma else None,
               (tuple(sorted(mkey.items())), tuple(round(v) for v in content.getRect())) if mkey else None,
               (smask["mask"], bool(smask.get("invert")), tuple(round(v) for v in content.getRect())) if smask else None)
        crop = getattr(self, "_crop", None)
        extra = {k: float(fx.get(k) or 0) for k in ("rgbsplit", "glow", "punchy", "vhs", "duotone") if float(fx.get(k) or 0) > 0}
        post = [_post_look(pc, pfx, mix) for pc, pfx, mix in (getattr(self, "_post", None) or [])]
        post = [x for x in post if x is not None]
        key = key + ((tuple(sorted(crop.items())) if crop else None), tuple(sorted(extra.items())),
                     tuple(x[0] for x in post))
        if key != getattr(self, "_look_key", (False, 0.0, None, "normal", (), (0, 0), None, None, None, None, (), ())):
            self._look_key = key
            bw, blur, _ck, _bl, _rk, _bs, _ch, _mk, _sm, _cr, _ex, _po = key
            eff = None
            if ckey is not None or blend != "normal" or regions or chroma or mkey or smask or crop or extra or post:
                eff = LookEffect(col, bw, blur, blend, regions, self.box.rect(), chroma, mkey, content, smask)
                eff.crop = crop
                eff.extra = extra
                eff.post = [x[1] for x in post]
            elif blur > 0:
                eff = QGraphicsBlurEffect()
                eff.setBlurRadius(4 + 30 * blur)
            elif bw:
                eff = QGraphicsColorizeEffect()
                eff.setColor(QColor(128, 128, 128))
                eff.setStrength(1.0)
            self.box.setGraphicsEffect(eff)
        vig = float(fx.get("vignette", 0) or 0) or (0.6 if fx.get("oldfilm") else 0.0)
        if vig > 0:
            from PySide6.QtGui import QRadialGradient
            r = self.box.rect()
            g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.75)
            g.setColorAt(0.45, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, int(200 * vig)))
            self.vig.setRect(r)
            self.vig.setBrush(QBrush(g))
            self.vig.show()
        else:
            self.vig.hide()

    def set_effects(self, fx: dict | None, t: float, dur: float, src_t: float | None = None):
        """Destello / fundido / temblor del clip en el instante t (desde su inicio)."""
        self._set_look(fx)
        eff = self.box.graphicsEffect()
        if src_t is not None and getattr(eff, "smask", None) and abs(eff.src_t - src_t) > 1e-4:
            eff.src_t = src_t           # ✂ la máscara del fotograma que se ve
            eff.update()
        color, alpha = effects.overlay_at(fx, t, dur)
        fl = effects.flicker_at(fx, t)
        if alpha <= 0.002 and abs(fl) > 0.001:       # ⚡ parpadeo: un velo claro u oscuro que salta
            color, alpha = ("#FFFFFF" if fl > 0 else "#000000"), abs(fl)
        if alpha > 0.002:
            self.fx.setRect(self.box.rect())
            self.fx.setBrush(QBrush(QColor(color)))
            self.fx.setOpacity(min(1.0, alpha))
            self.fx.show()
        else:
            self.fx.hide()
        lb = float((fx or {}).get("letterbox", 0) or 0)
        r = self.box.rect()
        for k, b in enumerate(self.bars):
            if lb > 0:
                h = r.height() * min(0.3, lb)
                b.setRect(QRectF(r.left(), r.top() if k == 0 else r.bottom() - h, r.width(), h))
                b.show()
            else:
                b.hide()
        inv = float((fx or {}).get("invert", 0) or 0)
        if inv > 0 and t < inv:
            self.neg.setRect(r)
            self.neg.show()
        else:
            self.neg.hide()
        dx, dy = effects.shake_at(fx, t)
        if dx or dy:
            r = self.box.rect()
            self.box.setPos(self.box.pos() + QPointF(dx * r.width(), dy * r.height()))
        ang = effects.roll_at(fx, t)                 # ↻ giro de cámara (ampliado para no ver esquinas)
        r = self.box.rect()
        # ⚡ Solo si cambian: Qt repinta la capa (y recalcula su color) aunque se le den los mismos valores
        if self.box.transformOriginPoint() != r.center():
            self.box.setTransformOriginPoint(r.center())
        rot = getattr(self, "_rot", 0.0) + ang       # (+ el giro de la capa, si lo tiene)
        if abs(self.box.rotation() - rot) > 1e-6:
            self.box.setRotation(rot)
        sc = 1.22 if abs(ang) > 0.01 else 1.0
        if abs(self.box.scale() - sc) > 1e-9:
            self.box.setScale(sc)
        lk = float((fx or {}).get("lightleak", 0) or 0)
        if lk > 0:                                   # ☀ destello de luz cálida que cruza
            from PySide6.QtGui import QRadialGradient
            if not hasattr(self, "leak"):
                self.leak = QGraphicsRectItem(self.box)
                self.leak.setPen(QPen(Qt.NoPen))
                self.leak.setZValue(9.5)
            import math as _m
            cx = r.left() + r.width() * (0.15 + 0.7 * (0.5 + 0.5 * _m.sin(t * 0.6)))
            grad = QRadialGradient(QPointF(cx, r.top() + r.height() * 0.35), r.width() * 0.45)
            grad.setColorAt(0.0, QColor(255, 150, 60, int(170 * min(1.0, lk))))
            grad.setColorAt(1.0, QColor(255, 150, 60, 0))
            self.leak.setRect(r)
            self.leak.setBrush(QBrush(grad))
            self.leak.show()
        elif hasattr(self, "leak"):
            self.leak.hide()

    def hide(self):
        self.box.hide()
        self.fill.hide()
        for it in (getattr(self, "_shadow", None), getattr(self, "_outline", None)):
            if it is not None:
                it.hide()

    def set_decor(self, fx, local_t: float, W: int, H: int):
        """Entrada (desliza o aparece), sombra suave y contorno alrededor de lo que se ve (como al exportar)."""
        from ..core import decor
        r = self.box.rect()
        pos = self.box.pos()
        dx, dy, alpha = decor.offset_at(fx, local_t, pos.x(), pos.y(), r.width(), r.height(), W, H)
        if dx or dy:
            self.box.setPos(pos + QPointF(dx, dy))
        if alpha < 0.999:
            self.box.setOpacity(self.box.opacity() * alpha)
        sh, ol = decor.shadow_of(fx), decor.outline_of(fx)
        if not sh and not ol:
            for it in (getattr(self, "_shadow", None), getattr(self, "_outline", None)):
                if it is not None:
                    it.hide()
            return
        item = self.image if self.image.isVisible() else self.video
        content = item.sceneBoundingRect().intersected(self.box.sceneBoundingRect())
        scene = self.box.scene()
        short = min(W, H)
        if getattr(self, "_shadow", None) is None:
            from PySide6.QtWidgets import QGraphicsBlurEffect
            self._shadow = QGraphicsRectItem()
            self._shadow.setPen(QPen(Qt.NoPen))
            eff = QGraphicsBlurEffect()
            self._shadow.setGraphicsEffect(eff)
            scene.addItem(self._shadow)
            self._outline = QGraphicsRectItem()
            self._outline.setBrush(QBrush(Qt.NoBrush))
            scene.addItem(self._outline)
        z = self.box.zValue()
        _m, ow = decor.margins(fx, W, H)
        frame = content.adjusted(-ow, -ow, ow, ow)
        if sh:
            views = scene.views()
            k = views[0].transform().m11() if views else 1.0
            self._shadow.setRect(frame.translated(sh["dx"] * short, sh["dy"] * short))
            self._shadow.setBrush(QColor(0, 0, 0, int(255 * float(sh["opacity"]))))
            self._shadow.graphicsEffect().setBlurRadius(max(1.0, sh["blur"] * short * k * 2))
            self._shadow.setZValue(z - 0.01)
            self._shadow.setOpacity(self.box.opacity())
            self._shadow.show()
        else:
            self._shadow.hide()
        if ol and ow > 0:
            self._outline.setRect(frame.adjusted(ow / 2, ow / 2, -ow / 2, -ow / 2))
            self._outline.setPen(QPen(QColor(ol["color"]), ow))
            self._outline.setZValue(z + 0.01)
            self._outline.setOpacity(self.box.opacity())
            self._outline.show()
        else:
            self._outline.hide()

    def _geom_now(self):
        """Cómo está colocada la capa ahora mismo (para saber si alguien la movió desde el último place)."""
        return (self.box.rect(), self.box.pos(), self.box.isVisible(), self.image.isVisible(),
                tuple((v.size(), v.pos(), v.isVisible()) for v in self.videos))

    def place(self, W: int, H: int, layout: dict | None, src_w: int, src_h: int,
              zoom: tuple[float, float, float], image_path: str | None, z_value: float,
              bars: list[float] | None = None):
        """bars: ▭ la zona con imagen del archivo (sin barras negras), y src_w/src_h ya son su tamaño."""
        # ⚡ Si nada cambió (ni lo pedido ni la capa), no se toca: volver a darle el mismo tamaño al video hacía que Qt
        # lo repintara y recalculara su color en cada edición, aunque fuera lejos del cabezal
        sig = (W, H, repr(layout), src_w, src_h, tuple(zoom), image_path, z_value, getattr(self, "active", 0),
               tuple(bars or ()))
        if sig == self.__dict__.get("_place_sig") and self._geom_now() == self.__dict__.get("_place_geom"):
            return
        self._bars = bars if image_path is None else None
        self._place(W, H, layout, src_w, src_h, zoom, image_path, z_value)
        self._place_sig, self._place_geom = sig, self._geom_now()

    def _place(self, W: int, H: int, layout: dict | None, src_w: int, src_h: int,
               zoom: tuple[float, float, float], image_path: str | None, z_value: float):
        box = layout or transform.FULL
        cr = box.get("crop")
        self._crop = dict(cr) if cr and any(float(cr.get(k, 0)) > 1e-4 for k in ("l", "t", "r", "b")) else None
        bx, by, bw, bh = box["x"] * W, box["y"] * H, box["w"] * W, box["h"] * H
        self.box.setZValue(z_value)
        self.box.setRect(QRectF(0, 0, bw, bh))
        self.box.setPos(bx, by)
        if image_path is not None:
            if image_path != self._image_path:
                self._image_path = image_path
                self._pix = QPixmap(image_path)
                self.image.setPixmap(self._pix)
            if not self._pix.isNull():
                src_w, src_h = self._pix.width(), self._pix.height()
        if src_w <= 0 or src_h <= 0:
            src_w, src_h = int(bw) or 16, int(bh) or 9
        fit = box.get("fit", "contain")
        self._W, self._H = float(W), float(H)
        # ⟳ giro y ↔ ↕ voltear de la capa (Inspector → Transformar)
        self._rot = transform.rot_of(box)
        r0 = QRectF(0, 0, bw, bh)
        ftr = QTransform()
        if box.get("flip_h") or box.get("flip_v"):
            ftr.translate(r0.center().x(), r0.center().y())
            ftr.scale(-1 if box.get("flip_h") else 1, -1 if box.get("flip_v") else 1)
            ftr.translate(-r0.center().x(), -r0.center().y())
        self.box.setTransform(ftr)
        self.box.setTransformOriginPoint(r0.center())
        self.box.setRotation(self._rot)
        fill_p = box.get("_fill")
        if fill_p != self._fill_p:
            self._fill_p = fill_p
            if not fill_p:
                self.fill.hide()
        blurfill = fit in ("blurfill", "mirrorfill")
        self._mirror = fit == "mirrorfill"
        self._flip = bool(box.get("flip"))
        self._want_bg = blurfill
        self._bw, self._bh = bw, bh
        self._fg_h = src_h * min(bw / src_w, bh / src_h)
        self.bg.setVisible(blurfill)
        if box.get("bg") == "none":       # capturas superpuestas: sin bandas negras
            self.box.setBrush(QBrush(Qt.NoBrush))
        else:
            self.box.setBrush(QBrush(Qt.black))
        if (blurfill or fill_p) and image_path is not None and image_path != getattr(self, "_bg_image_path", None):
            self._bg_image_path = image_path
            self._set_bg_source(QImage(image_path))
        elif blurfill or fill_p:
            self._update_bg()
        if fit == "stretch":                  # ↔ deformado: llena la caja exacta (estirado o aplastado)
            cw, ch = bw, bh
        else:
            s = (max if fit == "cover" else min)(bw / src_w, bh / src_h)
            cw, ch = src_w * s, src_h * s
        x0, y0 = (bw - cw) / 2, (bh - ch) / 2
        if fit == "cover" and box.get("_cx") is not None and cw > bw:     # 🎯 el recorte sigue la acción
            x0 = min(0.0, max(bw - cw, bw / 2 - float(box["_cx"]) * cw))
        self.content_rect = QRectF(x0, y0, cw, ch)       # dónde está la imagen entera (sin zoom) en la caja
        z, fx, fy = zoom
        left, top, _size = transform.window(z, fx, fy)
        z = max(1.0, z)
        # El trozo visible del archivo ocupa todo el contenido (mismo cálculo que zoompan)
        if image_path is not None:
            kx, ky = z * cw / src_w, z * ch / src_h
            self.image.setTransform(QTransform(kx, 0, 0, ky, -left * cw * z, -top * ch * z))
            self.image.setPos(x0, y0)
            self.image.show()
            for v in self.videos:
                v.hide()
            self._geom = ("image",)
        else:
            # ▭ sin barras: el archivo entero se dibuja más grande y desplazado, y el marco deja ver solo su zona con
            # imagen (que ocupa todo el contenido)
            b = self._bars or (0.0, 0.0, 1.0, 1.0)
            fullw, fullh = cw / b[2], ch / b[3]
            tf = QTransform(z, 0, 0, z, -z * (left * cw + b[0] * fullw), -z * (top * ch + b[1] * fullh))
            self.clip.setFlag(QGraphicsItem.ItemClipsChildrenToShape, self._bars is not None)
            self.clip.setRect(QRectF(0, 0, cw, ch))
            self.clip.setPos(x0, y0)
            for k, v in enumerate(self.videos):
                v.setSize(QSizeF(fullw, fullh))
                v.setTransform(tf)
                v.setPos(0, 0)
                v.setVisible(k == self.active)
            self._geom = ("video",)
            self.image.hide()
        self.box.show()


class GuidesItem(QGraphicsItem):
    """▦ Guías del visor (no salen al exportar): tercios, centro, zona segura (en vertical: lo que tapan los
    botones y textos de Shorts/TikTok; en horizontal: márgenes seguros) y el borde del encuadre."""
    MODES = (("thirds", "Tercios"), ("center", "Centro"), ("safe", "Zona segura (Shorts / TikTok)"),
             ("frame", "Borde del encuadre"), ("action", "Acción (93 %)"), ("title", "Título (90 %)"),
             ("rulers", "Reglas"))
    # Relaciones de aspecto (como el menú de guías de Resolve): se oscurece lo que queda fuera
    SOCIAL = (("1:1", 1.0), ("4:5", 0.8), ("9:16", 9 / 16), ("1.91:1", 1.91), ("16:9", 16 / 9))
    CINE = (("1.33", 1.33), ("1.77", 1.77), ("1.85", 1.85), ("2.35", 2.35), ("2.39", 2.39), ("2.40", 2.40))

    def __init__(self):
        super().__init__()
        self.W, self.H = 1920, 1080
        self.modes: set[str] = set()
        self.setZValue(5000)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_size(self, W, H):
        self.prepareGeometryChange()
        self.W, self.H = W, H
        self.update()

    def set_modes(self, modes):
        self.modes = set(modes)
        self.setVisible(bool(self.modes))
        self.update()

    def boundingRect(self):
        return QRectF(-4, -4, self.W + 8, self.H + 8)

    def paint(self, p: QPainter, _opt, _w=None):
        W, H = self.W, self.H
        k = max(W, H) / 1080
        pen = QPen(QColor(255, 255, 255, 150), 2 * k)
        pen.setCosmetic(False)
        if "thirds" in self.modes:
            p.setPen(pen)
            for i in (1, 2):
                p.drawLine(QPointF(W * i / 3, 0), QPointF(W * i / 3, H))
                p.drawLine(QPointF(0, H * i / 3), QPointF(W, H * i / 3))
        if "center" in self.modes:
            p.setPen(QPen(QColor(242, 160, 61, 220), 2 * k))
            c = QPointF(W / 2, H / 2)
            p.drawLine(c - QPointF(30 * k, 0), c + QPointF(30 * k, 0))
            p.drawLine(c - QPointF(0, 30 * k), c + QPointF(0, 30 * k))
        if "safe" in self.modes:
            f = QFont("Segoe UI")
            f.setPixelSize(int(22 * k))
            p.setFont(f)
            if H > W:     # vertical: Shorts / TikTok tapan arriba, abajo y la columna de botones
                zones = [(QRectF(0, 0, W, H * 0.11), "título / cuenta"),
                         (QRectF(0, H * 0.75, W, H * 0.25), "descripción y música"),
                         (QRectF(W * 0.85, H * 0.40, W * 0.15, H * 0.35), "botones")]
                for r, label in zones:
                    p.fillRect(r, QColor(229, 72, 77, 55))
                    p.setPen(QColor(255, 210, 210, 220))
                    p.drawText(r.adjusted(8 * k, 4 * k, -4 * k, -4 * k), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                               label)
            else:          # horizontal: márgenes de acción (90 %) y de títulos (80 %)
                for frac, col in ((0.9, QColor(242, 160, 61, 200)), (0.8, QColor(255, 255, 255, 170))):
                    p.setPen(QPen(col, 2 * k, Qt.DashLine))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(QRectF(W * (1 - frac) / 2, H * (1 - frac) / 2, W * frac, H * frac))
        if "frame" in self.modes:
            p.setPen(QPen(QColor(242, 160, 61, 255), 4 * k))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(0, 0, W, H))
        for key, frac, col in (("action", 0.93, QColor(242, 160, 61, 210)), ("title", 0.90, QColor(255, 255, 255, 190))):
            if key in self.modes:
                p.setPen(QPen(col, 2 * k, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(W * (1 - frac) / 2, H * (1 - frac) / 2, W * frac, H * frac))
        asp = next((m for m in self.modes if m.startswith("a:")), None)
        if asp:
            try:
                r = float(asp[2:])
            except ValueError:
                r = 0.0
            if r > 0:
                if r >= W / H:
                    rw, rh = W, W / r
                else:
                    rw, rh = H * r, H
                rect = QRectF((W - rw) / 2, (H - rh) / 2, rw, rh)
                shade = QColor(0, 0, 0, 150)
                p.fillRect(QRectF(0, 0, W, rect.top()), shade)
                p.fillRect(QRectF(0, rect.bottom(), W, H - rect.bottom()), shade)
                p.fillRect(QRectF(0, rect.top(), rect.left(), rect.height()), shade)
                p.fillRect(QRectF(rect.right(), rect.top(), W - rect.right(), rect.height()), shade)
                p.setPen(QPen(QColor(255, 255, 255, 220), 2 * k))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect)
        if "rulers" in self.modes:
            f = QFont("Segoe UI")
            f.setPixelSize(int(14 * k))
            p.setFont(f)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.2 * k))
            for i in range(0, 21):
                x, y = W * i / 20, H * i / 20
                big = i % 5 == 0
                p.drawLine(QPointF(x, 0), QPointF(x, (18 if big else 9) * k))
                p.drawLine(QPointF(0, y), QPointF((18 if big else 9) * k, y))
                if big and 0 < i < 20:
                    p.drawText(QPointF(x + 3 * k, 32 * k), str(int(W * i / 20)))
                    p.drawText(QPointF(22 * k, y - 3 * k), str(int(H * i / 20)))


class _GuidesPanel(QWidget):
    """▦ El menú de guías como el de DaVinci Resolve: iconos por secciones (redes sociales, cine y televisión,
    áreas de seguridad, reglas y guías). Una sola relación de aspecto a la vez; lo demás, lo que quieras."""

    def __init__(self, modes, on_change):
        super().__init__()
        from PySide6.QtWidgets import QGridLayout, QToolButton
        self.on_change = on_change
        self.buttons: dict[str, QToolButton] = {}
        self.setStyleSheet("QToolButton { border: 1px solid transparent; border-radius: 4px; padding: 3px; "
                           "color: #9a9ea8; font-size: 11px; } QToolButton:checked { color: white; "
                           "border-color: #5fd8ff; background: rgba(95,216,255,0.12); } "
                           "QToolButton:hover { background: rgba(255,255,255,0.06); } "
                           "QLabel#gsec { color: #e8e8ea; font-weight: 600; padding-top: 6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)

        def section(title, items, cols=5):
            lab = QLabel(title)
            lab.setObjectName("gsec")
            lay.addWidget(lab)
            grid = QGridLayout()
            grid.setSpacing(4)
            for i, (key, text, icon) in enumerate(items):
                b = QToolButton()
                b.setText(text)
                b.setIcon(icon)
                b.setIconSize(QSizeF(34, 22).toSize())
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setCheckable(True)
                b.setChecked(key in modes or (key == "a:" and not any(m.startswith("a:") for m in modes)))
                b.toggled.connect(lambda on, k=key: self._toggled(k, on))
                b.setFixedWidth(62)
                grid.addWidget(b, i // cols, i % cols)
                self.buttons[key] = b
            lay.addLayout(grid)
        section("Redes sociales", [(f"a:{r:.4f}", name, self._aspect_icon(r)) for name, r in GuidesItem.SOCIAL])
        section("Cine y televisión", [("a:", "Predet.", self._aspect_icon(16 / 9, full=True))] +
                [(f"a:{r:.4f}", name, self._aspect_icon(r)) for name, r in GuidesItem.CINE])
        section("Guías (área de seguridad)", [("frame", "Completa", self._safe_icon(1.0)),
                                              ("action", "Acción", self._safe_icon(0.86)),
                                              ("title", "Título", self._safe_icon(0.72)),
                                              ("center", "Centro", self._center_icon()),
                                              ("safe", "Shorts", self._aspect_icon(9 / 16))])
        section("Reglas y guías", [("rulers", "Reglas", self._rulers_icon()), ("thirds", "Tercios", self._thirds_icon())])

    def _toggled(self, key, on):
        if key.startswith("a:"):               # relaciones de aspecto: una sola (o «Predet.» = ninguna)
            for k, b in self.buttons.items():
                if k.startswith("a:") and k != key:
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
            if not on:
                d = self.buttons["a:"]
                d.blockSignals(True)
                d.setChecked(True)
                d.blockSignals(False)
        modes = [k for k, b in self.buttons.items() if b.isChecked() and k != "a:"]
        self.on_change(modes)

    @staticmethod
    def _pix():
        pm = QPixmap(68, 44)
        pm.fill(Qt.transparent)
        return pm

    def _aspect_icon(self, r, full=False):
        from PySide6.QtGui import QIcon
        pm = self._pix()
        p = QPainter(pm)
        p.setPen(QPen(QColor("#8a8a90"), 2))
        p.drawRect(QRectF(4, 6, 60, 32))
        if not full:
            if r >= 60 / 32:
                h = 60 / r
                inner = QRectF(4, 22 - h / 2, 60, h)
            else:
                w = 32 * r
                inner = QRectF(34 - w / 2, 6, w, 32)
            p.fillRect(inner, QColor(200, 200, 205, 120))
        p.end()
        return QIcon(pm)

    def _safe_icon(self, frac):
        from PySide6.QtGui import QIcon
        pm = self._pix()
        p = QPainter(pm)
        p.setPen(QPen(QColor("#8a8a90"), 2))
        p.drawRect(QRectF(4, 6, 60, 32))
        if frac < 1:
            p.setPen(QPen(QColor("#d0d0d4"), 1.5, Qt.DashLine))
            p.drawRect(QRectF(34 - 30 * frac, 22 - 16 * frac, 60 * frac, 32 * frac))
        p.end()
        return QIcon(pm)

    def _center_icon(self):
        from PySide6.QtGui import QIcon
        pm = self._pix()
        p = QPainter(pm)
        p.setPen(QPen(QColor("#8a8a90"), 2))
        p.drawRect(QRectF(4, 6, 60, 32))
        p.setPen(QPen(QColor("#d0d0d4"), 2))
        p.drawLine(QPointF(28, 22), QPointF(40, 22))
        p.drawLine(QPointF(34, 16), QPointF(34, 28))
        p.end()
        return QIcon(pm)

    def _rulers_icon(self):
        from PySide6.QtGui import QIcon
        pm = self._pix()
        p = QPainter(pm)
        p.setPen(QPen(QColor("#8a8a90"), 2))
        p.drawRect(QRectF(4, 6, 60, 32))
        p.setPen(QPen(QColor("#d0d0d4"), 1))
        for i in range(1, 12):
            p.drawLine(QPointF(4 + i * 5, 6), QPointF(4 + i * 5, 10 if i % 2 else 13))
        p.end()
        return QIcon(pm)

    def _thirds_icon(self):
        from PySide6.QtGui import QIcon
        pm = self._pix()
        p = QPainter(pm)
        p.setPen(QPen(QColor("#8a8a90"), 2))
        p.drawRect(QRectF(4, 6, 60, 32))
        p.setPen(QPen(QColor("#d0d0d4"), 1))
        for i in (1, 2):
            p.drawLine(QPointF(4 + 20 * i, 6), QPointF(4 + 20 * i, 38))
            p.drawLine(QPointF(4, 6 + 32 * i / 3), QPointF(64, 6 + 32 * i / 3))
        p.end()
        return QIcon(pm)


class CompositionItem(QGraphicsItem):
    """⊞ Huecos de la composición en el visor: un «+» donde puede ir cada imagen/video; fuera de ellos, el fondo.
    Solo se ve en el visor (no se exporta)."""

    def __init__(self):
        super().__init__()
        self.W, self.H = 1920, 1080
        self.n = 0
        self.slots: list[dict] = []
        self.hot: int | None = None       # hueco bajo el ratón al arrastrar (-1 = fondo)
        self.setZValue(5100)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.hide()

    def set_size(self, W, H):
        self.prepareGeometryChange()
        self.W, self.H = W, H
        self.set_count(self.n)

    def set_count(self, n: int):
        from ..core import transform
        self.n = n
        self.slots = transform.comp_slots(n, self.W, self.H) if n else []
        self.setVisible(bool(n))
        self.update()

    def rect_of(self, s: dict) -> QRectF:
        return QRectF(s["x"] * self.W, s["y"] * self.H, s["w"] * self.W, s["h"] * self.H)

    def slot_at(self, pt: QPointF) -> int:
        for i, s in enumerate(self.slots):
            if self.rect_of(s).contains(pt):
                return i
        return -1

    def boundingRect(self):
        return QRectF(0, 0, self.W, self.H)

    def paint(self, p: QPainter, _opt, _w=None):
        k = max(self.W, self.H) / 1080
        f = QFont("Segoe UI")
        f.setPixelSize(int(46 * k))
        f.setBold(True)
        if self.hot == -1:
            p.fillRect(QRectF(0, 0, self.W, self.H), QColor(242, 160, 61, 40))
        for i, s in enumerate(self.slots):
            r = self.rect_of(s)
            hot = i == self.hot
            p.fillRect(r, QColor(242, 160, 61, 70) if hot else QColor(255, 255, 255, 18))
            p.setPen(QPen(QColor(242, 160, 61, 255) if hot else QColor(255, 255, 255, 160), 3 * k, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(r, Qt.AlignCenter, "+")
            f2 = QFont(f)
            f2.setPixelSize(int(22 * k))
            p.setFont(f2)
            p.drawText(r.adjusted(10 * k, 6 * k, -6 * k, -6 * k), Qt.AlignLeft | Qt.AlignTop, str(i + 1))
        if self.slots:
            f3 = QFont(f)
            f3.setPixelSize(int(20 * k))
            f3.setBold(False)
            p.setFont(f3)
            p.setPen(QColor(255, 210, 160, 230))
            p.drawText(QRectF(0, self.H - 34 * k, self.W, 30 * k), Qt.AlignCenter,
                       "Arrastra aquí desde Medios · fuera de los huecos = fondo")


class Canvas(QGraphicsView):
    """
    El "lienzo" del video, con el tamaño y formato del proyecto (16:9, vertical...).
    Capas: fondo negro, una capa por pista de video (con su caja y zoom), subtítulos.
    Con un clip seleccionado (como el «Transform» del visor de Resolve): cada capa es independiente.
    Arrastrar = mover la capa · esquinas o rueda = tamaño · Alt+arrastrar / Alt+rueda = mover/acercar la imagen
    DENTRO de su caja (encuadre) · doble clic = volver a pantalla completa.
    """
    framing_drag = Signal(float, float)   # desplazamiento en fracciones del lienzo
    transform_live = Signal(str, dict)    # la capa mientras la mueves (clip, caja) — solo para verla
    transform_done = Signal(str, object, object)   # al soltar: (clip, caja original o None, caja nueva o None)
    comp_drop = Signal(list, object)      # ⊞ archivos soltados en un hueco (box) o en el fondo (None)
    layer_picked = Signal(str)            # 👆 clic en una capa del visor = seleccionar su clip (como en Resolve)
    pick_clip_cb = None                   # (id de pista) -> id del clip que se ve ahí ahora (lo pone la ventana)
    region_changed = Signal(str, list)    # desenfoque por zonas movido/redimensionado (clip, zonas)
    framing_wheel = Signal(float)         # pasos de rueda (+ acercar, - alejar)
    dynzoom_done = Signal(str, dict, dict)   # 🔍 zoom dinámico: (clip, rect inicio, rect final) en fracciones del archivo
    annotation_added = Signal(dict)       # ✏ un trazo nuevo (lo guarda la ventana principal)
    mode_changed = Signal(str)
    view_zoom_changed = Signal(float)     # zoom del VISOR (1 = ajustado a la ventana)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#111316"))
        self.W, self.H = 1920, 1080
        self.frame = self.scene().addRect(QRectF(0, 0, self.W, self.H), QPen(Qt.NoPen), QBrush(Qt.black))
        self.frame.setZValue(-1000)
        self.layers: dict[str, TrackLayer] = {}
        self.subs = SubtitleItem()
        self.scene().addItem(self.subs)
        self.titles = TitlesItem()
        self.scene().addItem(self.titles)
        self.guides = GuidesItem()          # ▦ guías (solo en el visor)
        self.scene().addItem(self.guides)
        self.comp = CompositionItem()       # ⊞ huecos de la composición
        self.scene().addItem(self.comp)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.guides.set_modes(str(QSettings("EditorIA", "EditorIA").value("visor/guias", "") or "").split(",")
                              if QSettings("EditorIA", "EditorIA").value("visor/guias") else [])
        self.framing_enabled = False
        self._drag_from: QPointF | None = None
        self._reg: dict | None = None        # {"clip", "track", "regions"} del clip seleccionado
        self._reg_drag: dict | None = None
        self.reg_overlay = _RegionOverlay()
        self.scene().addItem(self.reg_overlay)
        self.mode = "transform"               # modo del visor: transform | crop | dynzoom | annotate (Resolve)
        self._crop_drag = None
        self._dz: dict | None = None          # 🔍 zoom dinámico: {"clip", "a": rect inicio, "b": rect final} (0–1)
        self._dz_drag = None
        self.annotations_now: list[dict] = []
        self._stroke = None
        self.ann_overlay = _AnnotationOverlay()
        self.scene().addItem(self.ann_overlay)
        self.dz_overlay = _DynZoomOverlay()
        self.scene().addItem(self.dz_overlay)
        self._tf: dict | None = None          # {"clip", "box", "orig"}: capa seleccionada que se puede mover
        self._tf_drag: dict | None = None
        self.tf_overlay = _TransformOverlay()
        self.scene().addItem(self.tf_overlay)
        self._tf_wheel = QTimer(self)          # la rueda: un solo paso de deshacer al parar de girar
        self._tf_wheel.setSingleShot(True)
        self._tf_wheel.setInterval(450)
        self._tf_wheel.timeout.connect(self._tf_commit)
        self.setMouseTracking(True)
        self._sized = False
        self.view_zoom = 1.0                   # 🔍 zoom de la vista (no cambia el video), como en Resolve
        self._pan_from = None
        self.set_canvas_size(1920, 1080)

    def layer(self, track_id: str) -> TrackLayer:
        if track_id not in self.layers:
            self.layers[track_id] = TrackLayer(self.scene())
        return self.layers[track_id]

    def remove_layer(self, track_id: str):
        layer = self.layers.pop(track_id, None)
        if layer:
            self.scene().removeItem(layer.box)

    def set_canvas_size(self, W: int, H: int):
        if self._sized and (W, H) == (self.W, self.H):
            return
        self._sized = True
        self.W, self.H = W, H
        self.frame.setRect(QRectF(0, 0, W, H))
        self.scene().setSceneRect(QRectF(0, 0, W, H))
        self.subs.set_size(W, H)
        self.titles.set_size(W, H)
        self.guides.set_size(W, H)
        self.comp.set_size(W, H)
        self._fit()

    def _fit(self):
        self.fitInView(self.frame, Qt.KeepAspectRatio)
        if self.view_zoom != 1.0:
            self.scale(self.view_zoom, self.view_zoom)

    def zoom_view(self, factor: float, anchor=None):
        """🔍 Acercar / alejar la VISTA del visor (rueda del ratón), alrededor del cursor."""
        new = min(16.0, max(0.25, self.view_zoom * factor))
        if abs(new - 1.0) < 0.04:
            new = 1.0
        if new == self.view_zoom:
            return
        before = self.mapToScene(anchor) if anchor is not None else None
        self.view_zoom = new
        self.fitInView(self.frame, Qt.KeepAspectRatio)
        self.scale(new, new)
        if before is not None:          # el punto bajo el cursor se queda bajo el cursor
            after = self.mapToScene(anchor)
            d = after - before
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x() * self.transform().m11()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y() * self.transform().m22()))
        self._update_tf_overlay()
        self.view_zoom_changed.emit(new)

    def fit_view(self):
        self.view_zoom = 1.0
        self._fit()
        self._update_tf_overlay()
        self.view_zoom_changed.emit(1.0)

    # ---- ⊞ soltar archivos de Medios en los huecos de la composición
    def _comp_ok(self, e) -> bool:
        from .common import MEDIA_MIME
        return self.comp.n > 0 and e.mimeData().hasFormat(MEDIA_MIME)

    def dragEnterEvent(self, e):
        if self._comp_ok(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._comp_ok(e):
            e.ignore()
            return
        self.comp.hot = self.comp.slot_at(self.mapToScene(e.position().toPoint()))
        self.comp.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.comp.hot = None
        self.comp.update()

    def dropEvent(self, e):
        from .common import MEDIA_MIME
        if not self._comp_ok(e):
            e.ignore()
            return
        ids = [i for i in e.mimeData().data(MEDIA_MIME).data().decode().split(",") if i]
        i = self.comp.slot_at(self.mapToScene(e.position().toPoint()))
        self.comp.hot = None
        self.comp.update()
        self.comp_drop.emit(ids, dict(self.comp.slots[i]) if i >= 0 else None)
        e.acceptProposedAction()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    # Desenfoque por zonas: se ve su contorno y se arrastra (dentro = mover, esquina = tamaño)
    def set_region_edit(self, clip_id: str | None, track_id: str | None, regions: list | None):
        if self._reg_drag is not None:
            return
        self._reg = {"clip": clip_id, "track": track_id, "regions": [dict(r) for r in regions]} \
            if clip_id and regions else None
        self._update_reg_overlay()

    def _reg_layer(self):
        return self.layers.get(self._reg["track"]) if self._reg else None

    def _reg_rects(self) -> list[QRectF]:
        layer = self._reg_layer()
        if layer is None or not layer.box.isVisible():
            return []
        b = layer.box.rect()
        out = []
        for r in self._reg["regions"]:
            local = QRectF(b.left() + (r["x"] - r["w"] / 2) * b.width(), b.top() + (r["y"] - r["h"] / 2) * b.height(),
                           r["w"] * b.width(), r["h"] * b.height())
            out.append(layer.box.mapRectToScene(local))
        return out

    def _update_reg_overlay(self):
        rects = self._reg_rects() if self._reg else []
        self.reg_overlay.set_shapes([(r, reg["shape"]) for r, reg in zip(rects, self._reg["regions"])]
                                    if rects else [], self.W / max(1, self.viewport().width()))

    def _reg_hit(self, scene_pos: QPointF):
        if not self._reg:
            return None
        hs = 18 * self.W / max(1, self.viewport().width())
        for i, r in reversed(list(enumerate(self._reg_rects()))):
            if (scene_pos - r.bottomRight()).manhattanLength() <= hs * 1.2:
                return i, "size"
            if r.contains(scene_pos):
                return i, "move"
        return None

    # ---- ⤧ Transformar la capa (posición y tamaño en pantalla), como en Resolve
    def set_transform_edit(self, clip_id: str | None, layout: dict | None):
        if self._tf_drag is not None or self._tf_wheel.isActive():
            return
        key = (clip_id, tuple(sorted((layout or {}).items())))
        if key == getattr(self, "_tf_key", None):        # nada cambió (se llama en cada fotograma)
            return
        self._tf_key = key
        self._tf = {"clip": clip_id, "box": dict(layout or transform.FULL),
                    "orig": dict(layout) if layout else None} if clip_id else None
        self._update_tf_overlay()

    # ---- modos del visor (como el menú de abajo a la izquierda del visor de Resolve)
    def set_mode(self, mode: str):
        self.mode = mode
        self._update_tf_overlay()
        self.dz_overlay.setVisible(mode == "dynzoom")
        self.viewport().setCursor(Qt.CrossCursor if mode == "annotate" else Qt.ArrowCursor)
        self.mode_changed.emit(mode)

    def set_dynzoom_edit(self, clip_id: str | None, content: QRectF | None, a: dict | None, b: dict | None):
        """🔍 Zoom dinámico: el rectángulo VERDE (inicio del clip) y el ROJO (final), sobre la imagen entera."""
        if self._dz_drag is not None:
            return
        self._dz = {"clip": clip_id, "content": content, "a": dict(a), "b": dict(b)} if clip_id and content else None
        self._update_dz_overlay()

    def _dz_rects(self):
        if not self._dz:
            return []
        c = self._dz["content"]
        out = []
        for k in ("a", "b"):
            r = self._dz[k]
            out.append(QRectF(c.left() + r["x"] * c.width(), c.top() + r["y"] * c.height(),
                              r["s"] * c.width(), r["s"] * c.height()))
        return out

    def _update_dz_overlay(self):
        self.dz_overlay.set_rects(self._dz_rects() if self.mode == "dynzoom" else [],
                                  self.W / max(1, self.viewport().width()))

    def set_annotations(self, items: list[dict]):
        self.annotations_now = items
        self.ann_overlay.set_items(items, self.W, self.H)

    def _tf_rect(self) -> QRectF | None:
        if not self._tf or self.mode not in ("transform", "crop"):
            return None
        b = self._tf["box"]
        return QRectF(b["x"] * self.W, b["y"] * self.H, b["w"] * self.W, b["h"] * self.H)

    def _update_tf_overlay(self):
        crop = (self._tf or {}).get("box", {}).get("crop") if self.mode == "crop" else None
        self.tf_overlay.set_rect(self._tf_rect(), self.W / max(1, self.viewport().width()),
                                 crop if self.mode == "crop" else None)
        if hasattr(self, "dz_overlay"):
            self._update_dz_overlay()

    def _tf_hit(self, sp: QPointF):
        r = self._tf_rect()
        if r is None:
            return None
        hs = 16 * self.W / max(1, self.viewport().width())
        for k, c in enumerate((r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())):
            if abs(sp.x() - c.x()) <= hs and abs(sp.y() - c.y()) <= hs:
                return "size", k
        cx, cy = r.center().x(), r.center().y()          # ↔ ↕ asas de deformar (a media arista)
        for edge, (hx, hy) in (("l", (r.left(), cy)), ("r", (r.right(), cy)),
                               ("t", (cx, r.top())), ("b", (cx, r.bottom()))):
            if abs(sp.x() - hx) <= hs and abs(sp.y() - hy) <= hs:
                return "stretch", edge
        if r.contains(sp):
            return "move", -1
        return None

    def _pick_layer(self, sp: QPointF, deeper: bool = False) -> str | None:
        """El clip de la capa que se ve en ese punto (la de más arriba); deeper: la que está debajo de la seleccionada
        (cada Ctrl+clic baja una; al llegar abajo vuelve arriba)."""
        if self.pick_clip_cb is None:
            return None
        hits = []
        for tid, layer in getattr(self, "layers", {}).items():
            b = layer.box
            if b.isVisible() and b.contains(b.mapFromScene(sp)):
                cid = self.pick_clip_cb(tid)
                if cid:
                    hits.append((b.zValue(), cid))
        if not hits:
            return None
        order = [cid for _z, cid in sorted(hits, key=lambda x: -x[0])]
        cur = (self._tf or {}).get("clip")
        if deeper and cur in order:
            return order[(order.index(cur) + 1) % len(order)]
        return order[0]

    def _stretch_box(self) -> dict:
        """La caja para empezar a deformar: si aún no estaba deformada, la caja pasa a ser la imagen que se ve
        (sin bandas negras) para que no salte al empezar; desde ahí se estira o se aplasta."""
        b = dict(self._tf["box"])
        if b.get("fit") == "stretch":
            return b
        r = self._tf_rect()
        for layer in getattr(self, "layers", {}).values():
            br = QRectF(layer.box.pos(), layer.box.rect().size())
            cr = getattr(layer, "content_rect", None)
            if r is None or cr is None or not layer.box.isVisible() or \
                    abs(br.left() - r.left()) > 2 or abs(br.top() - r.top()) > 2 or \
                    abs(br.width() - r.width()) > 2 or abs(br.height() - r.height()) > 2:
                continue
            vis = QRectF(br.left() + cr.left(), br.top() + cr.top(), cr.width(), cr.height()).intersected(br)
            if vis.width() > 4 and vis.height() > 4:
                b.update(x=vis.left() / self.W, y=vis.top() / self.H, w=vis.width() / self.W, h=vis.height() / self.H)
            break
        b["fit"] = "stretch"
        b.pop("flip", None)
        return b

    def _tf_set(self, box: dict):
        """Caja nueva (con límites razonables): se ve al momento; se guarda al soltar."""
        w = min(4.0, max(0.05, box["w"]))
        h = min(4.0, max(0.05, box["h"]))
        x = min(0.98, max(-w + 0.02, box["x"]))
        y = min(0.98, max(-h + 0.02, box["y"]))
        if box.get("fit") == "stretch":        # ↔ deformar: la caja pasa a «estirada» (sin reflejo de los Shorts)
            self._tf["box"].pop("flip", None)
            self._tf["box"]["fit"] = "stretch"
        self._tf["box"].update(x=round(x, 4), y=round(y, 4), w=round(w, 4), h=round(h, 4))
        if self._tf["orig"] is None:        # era pantalla completa: sin bandas negras (se ve lo de debajo)
            self._tf["box"]["bg"] = "none"
        self._update_tf_overlay()
        self.transform_live.emit(self._tf["clip"], dict(self._tf["box"]))

    def _tf_commit(self):
        if self._tf:
            self.transform_done.emit(self._tf["clip"], self._tf["orig"], dict(self._tf["box"]))
            self._tf["orig"] = dict(self._tf["box"])

    def mouseDoubleClickEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.LeftButton and self._tf and self._tf_hit(sp) and self._tf["orig"] is not None:
            self.transform_done.emit(self._tf["clip"], self._tf["orig"], None)    # vuelve a pantalla completa
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:            # rueda pulsada + arrastrar = mover la vista (zoom)
            self._pan_from = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton and self._reg:
            sp = self.mapToScene(e.position().toPoint())
            hit = self._reg_hit(sp)
            if hit is not None:
                i, mode = hit
                self._reg_drag = {"i": i, "mode": mode, "from": sp, "orig": dict(self._reg["regions"][i])}
                return
        if e.button() == Qt.LeftButton and self.mode == "annotate":
            sp = self.mapToScene(e.position().toPoint())
            self._stroke = [sp.x() / self.W, sp.y() / self.H]
            return
        if e.button() == Qt.LeftButton and self.mode == "crop" and self._tf:
            sp = self.mapToScene(e.position().toPoint())
            r = self._tf_rect()
            hs = 14 * self.W / max(1, self.viewport().width())
            cr = dict(self._tf["box"].get("crop") or {})
            inner = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                           r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                           r.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
            edge = None
            if abs(sp.x() - inner.left()) <= hs:
                edge = "l"
            elif abs(sp.x() - inner.right()) <= hs:
                edge = "r"
            elif abs(sp.y() - inner.top()) <= hs:
                edge = "t"
            elif abs(sp.y() - inner.bottom()) <= hs:
                edge = "b"
            if edge:
                self._crop_drag = {"edge": edge, "r": r, "orig": dict(self._tf["box"])}
                return
        if e.button() == Qt.LeftButton and self.mode == "dynzoom" and self._dz:
            sp = self.mapToScene(e.position().toPoint())
            hs = 14 * self.W / max(1, self.viewport().width())
            for k, r in reversed(list(zip(("a", "b"), self._dz_rects()))):
                corner = (sp - r.bottomRight()).manhattanLength() <= hs * 1.4
                if corner or r.contains(sp):
                    self._dz_drag = {"k": k, "mode": "size" if corner else "move", "from": sp,
                                     "orig": dict(self._dz[k])}
                    return
        if e.button() == Qt.LeftButton and self.mode == "transform" and not (e.modifiers() & Qt.AltModifier):
            sp = self.mapToScene(e.position().toPoint())
            deeper = bool(e.modifiers() & Qt.ControlModifier)
            hit = self._tf_hit(sp) if (self._tf and not deeper) else None
            if hit is None:              # 👆 clic en otra capa: se selecciona (Ctrl+clic = la de debajo)
                cid = self._pick_layer(sp, deeper)
                if cid and cid != (self._tf or {}).get("clip"):
                    self.layer_picked.emit(cid)
                    return
        if e.button() == Qt.LeftButton and self._tf and self.mode == "transform" and \
                not (e.modifiers() & Qt.AltModifier):
            sp = self.mapToScene(e.position().toPoint())
            hit = self._tf_hit(sp)
            if hit is not None:
                box = self._stretch_box() if hit[0] == "stretch" or (
                    hit[0] == "size" and e.modifiers() & Qt.ShiftModifier) else dict(self._tf["box"])
                self._tf_drag = {"mode": hit[0], "corner": hit[1], "from": sp, "box": box,
                                 "free": hit[0] == "size" and bool(e.modifiers() & Qt.ShiftModifier)}
                return
        if self.framing_enabled and e.button() == Qt.LeftButton:
            self._drag_from = self.mapToScene(e.position().toPoint())
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan_from is not None:
            d = e.position() - self._pan_from
            self._pan_from = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        sp = self.mapToScene(e.position().toPoint())
        if self._stroke is not None:
            self._stroke += [round(sp.x() / self.W, 4), round(sp.y() / self.H, 4)]
            self.ann_overlay.set_items(self.annotations_now + [{"color": "#e5413c", "strokes": [self._stroke]}],
                                       self.W, self.H)
            return
        if self._crop_drag is not None:
            d = self._crop_drag
            r = d["r"]
            cr = dict(d["orig"].get("crop") or {"l": 0.0, "t": 0.0, "r": 0.0, "b": 0.0})
            if d["edge"] == "l":
                cr["l"] = (sp.x() - r.left()) / r.width()
            elif d["edge"] == "r":
                cr["r"] = (r.right() - sp.x()) / r.width()
            elif d["edge"] == "t":
                cr["t"] = (sp.y() - r.top()) / r.height()
            else:
                cr["b"] = (r.bottom() - sp.y()) / r.height()
            for k in ("l", "t", "r", "b"):
                cr[k] = round(min(0.45, max(0.0, cr.get(k, 0.0))), 4)
            self._tf["box"]["crop"] = cr
            if self._tf["orig"] is None:
                self._tf["box"]["bg"] = "none"
            self._update_tf_overlay()
            self.transform_live.emit(self._tf["clip"], dict(self._tf["box"]))
            return
        if self._dz_drag is not None:
            d = self._dz_drag
            c = self._dz["content"]
            dx, dy = (sp.x() - d["from"].x()) / c.width(), (sp.y() - d["from"].y()) / c.height()
            o = d["orig"]
            if d["mode"] == "move":
                n = dict(o, x=min(1 - o["s"], max(0.0, o["x"] + dx)), y=min(1 - o["s"], max(0.0, o["y"] + dy)))
            else:
                s = min(1.0 - o["x"], 1.0 - o["y"], max(0.12, o["s"] + max(dx, dy)))
                n = dict(o, s=s)
            self._dz[d["k"]] = n
            self._update_dz_overlay()
            return
        if self._tf_drag is not None:
            d, b = self._tf_drag, self._tf_drag["box"]
            dx, dy = (sp.x() - d["from"].x()) / self.W, (sp.y() - d["from"].y()) / self.H
            if d["mode"] == "move":
                self._tf_set(dict(b, x=b["x"] + dx, y=b["y"] + dy))
            elif d["mode"] == "stretch":     # ↔ ↕ media arista: solo ancho o solo alto (la arista contraria, quieta)
                px, py = sp.x() / self.W, sp.y() / self.H
                e_ = d["corner"]
                if e_ == "l":
                    right = b["x"] + b["w"]
                    w = max(0.05, right - px)
                    self._tf_set(dict(b, x=right - w, w=w))
                elif e_ == "r":
                    self._tf_set(dict(b, w=max(0.05, px - b["x"])))
                elif e_ == "t":
                    bottom = b["y"] + b["h"]
                    h = max(0.05, bottom - py)
                    self._tf_set(dict(b, y=bottom - h, h=h))
                else:
                    self._tf_set(dict(b, h=max(0.05, py - b["y"])))
            elif d.get("free"):              # Shift + esquina: ancho y alto por separado (deforma)
                k = d["corner"]
                ax = b["x"] + (b["w"] if k in (0, 3) else 0.0)
                ay = b["y"] + (b["h"] if k in (0, 1) else 0.0)
                px, py = sp.x() / self.W, sp.y() / self.H
                w, h = max(0.05, abs(px - ax)), max(0.05, abs(py - ay))
                self._tf_set(dict(b, x=ax - w if k in (0, 3) else ax, y=ay - h if k in (0, 1) else ay, w=w, h=h))
            else:     # esquina: tamaño SIN deformar; la esquina contraria se queda quieta
                k = d["corner"]
                ax = b["x"] + (b["w"] if k in (0, 3) else 0.0)        # esquina fija
                ay = b["y"] + (b["h"] if k in (0, 1) else 0.0)
                px, py = sp.x() / self.W, sp.y() / self.H
                s = max(abs(px - ax) / max(1e-4, b["w"]), abs(py - ay) / max(1e-4, b["h"]))
                s = max(0.05 / max(1e-4, min(b["w"], b["h"])), s)
                w, h = b["w"] * s, b["h"] * s
                self._tf_set(dict(b, x=ax - w if k in (0, 3) else ax, y=ay - h if k in (0, 1) else ay, w=w, h=h))
            return
        if self._reg_drag is not None:
            d = self._reg_drag
            layer = self._reg_layer()
            if layer is not None:
                b = layer.box.rect()
                p0, p1 = layer.box.mapFromScene(d["from"]), layer.box.mapFromScene(sp)
                dx, dy = (p1.x() - p0.x()) / b.width(), (p1.y() - p0.y()) / b.height()
                o, r = d["orig"], self._reg["regions"][d["i"]]
                if d["mode"] == "move":
                    r["x"] = min(1 - o["w"] / 2, max(o["w"] / 2, o["x"] + dx))
                    r["y"] = min(1 - o["h"] / 2, max(o["h"] / 2, o["y"] + dy))
                else:                  # esquina: la esquina contraria se queda quieta
                    left, top = o["x"] - o["w"] / 2, o["y"] - o["h"] / 2
                    right = min(1.0, max(left + 0.03, o["x"] + o["w"] / 2 + dx))
                    bottom = min(1.0, max(top + 0.03, o["y"] + o["h"] / 2 + dy))
                    r["w"], r["h"] = right - left, bottom - top
                    r["x"], r["y"] = left + r["w"] / 2, top + r["h"] / 2
                from ..core import effects as _fx
                layer.live_regions = _fx.blur_regions({"blur_regions": self._reg["regions"]})
                layer.box.update()
                self._update_reg_overlay()
            return
        if self._reg and self._drag_from is None:
            hit = self._reg_hit(sp)
            self.viewport().setCursor(Qt.SizeFDiagCursor if hit and hit[1] == "size" else
                                      Qt.SizeAllCursor if hit else
                                      (Qt.OpenHandCursor if self.framing_enabled else Qt.ArrowCursor))
        elif self._tf and self._drag_from is None:
            hit = self._tf_hit(sp)
            self.viewport().setCursor((Qt.SizeHorCursor if hit[1] in ("l", "r") else Qt.SizeVerCursor)
                                      if hit and hit[0] == "stretch" else
                                      (Qt.SizeFDiagCursor if hit[1] in (0, 2) else Qt.SizeBDiagCursor)
                                      if hit and hit[0] == "size" else Qt.SizeAllCursor if hit else
                                      (Qt.OpenHandCursor if self.framing_enabled else Qt.ArrowCursor))
        if self._drag_from is not None:
            pos = self.mapToScene(e.position().toPoint())
            d = pos - self._drag_from
            self._drag_from = pos
            self.framing_drag.emit(d.x() / self.W, d.y() / self.H)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._stroke is not None:
            st, self._stroke = self._stroke, None
            if len(st) >= 4:
                self.annotation_added.emit({"color": "#e5413c", "strokes": [st]})
            return
        if self._crop_drag is not None:
            self._crop_drag = None
            self._tf_commit()
            return
        if self._dz_drag is not None:
            self._dz_drag = None
            self.dynzoom_done.emit(self._dz["clip"], dict(self._dz["a"]), dict(self._dz["b"]))
            return
        if self._pan_from is not None and e.button() == Qt.MiddleButton:
            self._pan_from = None
            self.viewport().setCursor(Qt.ArrowCursor)
            return
        if self._tf_drag is not None:
            moved = self._tf_drag["box"] != self._tf["box"]
            self._tf_drag = None
            if moved:
                self._tf_commit()
            return
        if self._reg_drag is not None:
            self._reg_drag = None
            layer = self._reg_layer()
            regions = [dict(r) for r in self._reg["regions"]]
            self.region_changed.emit(self._reg["clip"], regions)
            if layer is not None:
                layer.live_regions = None
            return
        self._drag_from = None
        self.setCursor(Qt.OpenHandCursor if self.framing_enabled else Qt.ArrowCursor)
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        mods = e.modifiers()
        if not (mods & (Qt.ControlModifier | Qt.AltModifier)):   # rueda = acercar / alejar la VISTA (Resolve)
            steps = (e.angleDelta().y() or e.angleDelta().x()) / 120
            self.zoom_view(1.15 ** steps, e.position().toPoint())
            e.accept()
            return
        if self._tf and (mods & Qt.ControlModifier):    # Ctrl+rueda = tamaño de la capa (desde su centro)
            b = self._tf["box"]
            k = 1.05 ** ((e.angleDelta().y() or e.angleDelta().x()) / 120)
            w, h = b["w"] * k, b["h"] * k
            self._tf_set(dict(b, x=b["x"] + (b["w"] - w) / 2, y=b["y"] + (b["h"] - h) / 2, w=w, h=h))
            self._tf_wheel.start()
            e.accept()
            return
        if self.framing_enabled:
            self.framing_wheel.emit(e.angleDelta().y() / 120)
            e.accept()
        else:
            super().wheelEvent(e)

    def set_framing_enabled(self, on: bool):
        self.framing_enabled = on
        self.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
        self.setToolTip("Arrastra = mover la capa · esquinas o Ctrl+rueda = tamaño (como en Resolve) · doble clic = "
                        "pantalla completa.\nAlt+arrastrar / Alt+rueda = mover o acercar la imagen DENTRO de su caja."
                        "\nRueda = acercar/alejar la vista · rueda pulsada + arrastrar = mover la vista."
                        if on else "Rueda = acercar/alejar la vista · rueda pulsada + arrastrar = moverla · "
                        "clic en el % = ajustar.")


class _AnnotationOverlay(QGraphicsItem):
    """✏ Las anotaciones del visor (trazos a mano). No salen al exportar."""

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self.W, self.H = 1920, 1080
        self.setZValue(5200)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_items(self, items, W, H):
        # ⚡ igual que antes: no se repinta (se llama en cada cambio del proyecto y repintar recalcula el video de debajo)
        if (items, W, H) == (getattr(self, "items", None), getattr(self, "W", None), getattr(self, "H", None)):
            return
        self.prepareGeometryChange()
        self.items, self.W, self.H = items, W, H
        self.update()

    def boundingRect(self):
        return QRectF(0, 0, self.W, self.H)

    def paint(self, p, _opt, _w=None):
        from PySide6.QtGui import QPainterPath
        k = max(self.W, self.H) / 1080
        for it in self.items:
            pen = QPen(QColor(it.get("color", "#e5413c")), 6 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for st in it.get("strokes", []):
                if len(st) < 4:
                    continue
                path = QPainterPath(QPointF(st[0] * self.W, st[1] * self.H))
                for i in range(2, len(st) - 1, 2):
                    path.lineTo(QPointF(st[i] * self.W, st[i + 1] * self.H))
                p.drawPath(path)


class _DynZoomOverlay(QGraphicsItem):
    """🔍 Zoom dinámico (como Resolve): rectángulo VERDE = cómo empieza, ROJO = cómo acaba."""

    def __init__(self):
        super().__init__()
        self.rects: list[QRectF] = []
        self.k = 1.0
        self.setZValue(4950)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.hide()

    def set_rects(self, rects, k):
        # ⚡ igual que antes: no se repinta (se llama en cada cambio del proyecto y repintar recalcula el video de debajo)
        if (rects, k) == (getattr(self, "rects", None), getattr(self, "k", None)):
            return
        self.prepareGeometryChange()
        self.rects, self.k = rects, k
        self.update()

    def boundingRect(self):
        if not self.rects:
            return QRectF()
        r = QRectF(self.rects[0])
        for x in self.rects[1:]:
            r = r.united(x)
        return r.adjusted(-20 * self.k, -20 * self.k, 20 * self.k, 20 * self.k)

    def paint(self, p, _opt, _w=None):
        for r, col, label in zip(self.rects, (QColor("#3ad16b"), QColor("#e5413c")), ("Inicio", "Final")):
            p.setPen(QPen(col, 3 * self.k))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            s = 7 * self.k
            p.setBrush(col)
            p.drawRect(QRectF(r.right() - s, r.bottom() - s, 2 * s, 2 * s))
            f = QFont("Segoe UI")
            f.setPixelSize(int(16 * self.k))
            p.setFont(f)
            p.drawText(QPointF(r.left() + 6 * self.k, r.top() + 20 * self.k), label)


class _TransformOverlay(QGraphicsItem):
    """⤧ El contorno de la capa seleccionada con sus 4 esquinas (tamaño sin deformar) y 4 asas a media arista
    (↔ ↕ estirar o aplastar: deforma la imagen). En modo «Recortar», las 4 asas van en los bordes."""

    def __init__(self):
        super().__init__()
        self.r: QRectF | None = None
        self.k = 1.0
        self.crop = None
        self.setZValue(4900)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_rect(self, r: QRectF | None, k: float, crop=None):
        # ⚡ igual que antes: no se repinta (se llama en cada cambio del proyecto y repintar recalcula el video de debajo)
        if (r, k, crop) == (getattr(self, "r", 0), getattr(self, "k", None), getattr(self, "crop", 0)):
            return
        self.prepareGeometryChange()
        self.r, self.k, self.crop = r, k, crop
        self.update()

    def boundingRect(self):
        if self.r is None:
            return QRectF()
        m = 12 * self.k
        return self.r.adjusted(-m, -m, m, m)

    def paint(self, painter, _opt, _w=None):
        r = self.r
        if r is None:
            return
        if self.crop is not None:          # ✂ Recortar: el rectángulo que se queda y sus 4 asas en los bordes
            cr = self.crop or {}
            inner = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                           r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                           r.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 3 * self.k))
            painter.drawRect(inner)
            painter.setPen(QPen(QColor("#e8742f"), 1.6 * self.k))
            painter.drawRect(inner)
            s = 6 * self.k
            painter.setBrush(QColor("#e8742f"))
            for c in (QPointF(inner.left(), inner.center().y()), QPointF(inner.right(), inner.center().y()),
                      QPointF(inner.center().x(), inner.top()), QPointF(inner.center().x(), inner.bottom())):
                painter.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
            return
        painter.setBrush(Qt.NoBrush)
        for col, width, style in ((QColor(0, 0, 0, 150), 3.0, Qt.SolidLine), (QColor("#e8e8ea"), 1.2, Qt.DashLine)):
            painter.setPen(QPen(col, width * self.k, style))
            painter.drawRect(r)
        s = 6 * self.k
        painter.setPen(QPen(QColor("black"), 1 * self.k))
        painter.setBrush(QColor("#e8e8ea"))
        for c in (r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()):
            painter.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
        painter.setBrush(QColor("#9fc4ff"))            # ↔ ↕ deformar: asas alargadas a media arista
        cx, cy = r.center().x(), r.center().y()
        for hx, hy, ww, hh in ((r.left(), cy, s * 0.8, s * 1.8), (r.right(), cy, s * 0.8, s * 1.8),
                               (cx, r.top(), s * 1.8, s * 0.8), (cx, r.bottom(), s * 1.8, s * 0.8)):
            painter.drawRect(QRectF(hx - ww, hy - hh, 2 * ww, 2 * hh))
        c = r.center()
        painter.setPen(QPen(QColor("#e8e8ea"), 1.2 * self.k))
        painter.drawLine(QPointF(c.x() - 3 * s, c.y()), QPointF(c.x() + 3 * s, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - 3 * s), QPointF(c.x(), c.y() + 3 * s))


class _RegionOverlay(QGraphicsItem):
    """Contorno discontinuo de cada zona desenfocada del clip seleccionado y su asa de tamaño."""

    def __init__(self):
        super().__init__()
        self.shapes: list[tuple[QRectF, str]] = []
        self.k = 1.0
        self.setZValue(5000)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_shapes(self, shapes, k: float):
        # ⚡ igual que antes: no se repinta (se llama en cada cambio del proyecto y repintar recalcula el video de debajo)
        if (shapes, k) == (getattr(self, "shapes", None), getattr(self, "k", None)):
            return
        self.prepareGeometryChange()
        self.shapes, self.k = shapes, k
        self.update()

    def boundingRect(self):
        if not self.shapes:
            return QRectF()
        r = QRectF(self.shapes[0][0])
        for s, _ in self.shapes[1:]:
            r = r.united(s)
        m = 20 * self.k
        return r.adjusted(-m, -m, m, m)

    def paint(self, painter, _opt, _w=None):
        for r, shape in self.shapes:
            for col, width in ((QColor(0, 0, 0, 160), 3.0), (QColor("#f2a03d"), 1.5)):
                pen = QPen(col, width * self.k, Qt.DashLine if width < 2 else Qt.SolidLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(r) if shape == "ellipse" else painter.drawRect(r)
            s = 7 * self.k
            painter.setPen(QPen(QColor("black"), 1 * self.k))
            painter.setBrush(QColor("#f2a03d"))
            painter.drawRect(QRectF(r.right() - s, r.bottom() - s, 2 * s, 2 * s))


class LevelMeter(QWidget):
    """Medidor de nivel (dB) con retención del pico, como el de Resolve: verde, amarillo (>-12) y rojo (>-3)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(130, 12)
        self.db = -90.0
        self.peak = -90.0
        self._peak_t = QElapsedTimer()
        self._peak_t.start()
        self.setToolTip("Nivel del sonido en el cabezal (dB). Rojo = cerca de saturar.")

    def set_level(self, value: float):
        import math
        db = 20 * math.log10(max(value, 1e-5))
        self.db = db
        if db >= self.peak or self._peak_t.elapsed() > 1200:
            self.peak = db
            self._peak_t.restart()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect().adjusted(0, 2, -1, -2)
        p.fillRect(r, QColor("#1a1a1c"))

        def x_of(db):
            return r.left() + r.width() * min(1.0, max(0.0, (db + 60) / 60))
        x = x_of(self.db)
        for lo, hi, col in ((-60, -12, "#3fb950"), (-12, -3, "#f2b33d"), (-3, 3, "#e5484d")):
            a, b = x_of(lo), min(x, x_of(hi))
            if b > a:
                p.fillRect(QRectF(a, r.top(), b - a, r.height()), QColor(col))
        if self.peak > -60:
            xp = x_of(self.peak)
            p.setPen(QPen(QColor("white"), 1))
            p.drawLine(QPointF(xp, r.top()), QPointF(xp, r.bottom()))
        p.end()


class _InvertItem(QGraphicsRectItem):
    """Invierte lo que hay debajo (blanco en modo «diferencia»): el impact frame de los edits."""

    def paint(self, painter, _option, _widget=None):
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Difference)
        painter.fillRect(self.rect(), QColor("white"))
        painter.restore()


class LookEffect(QGraphicsEffect):
    """Color del clip en el visor (la misma tabla 3D que se usa al exportar) + blanco y negro y desenfoque."""

    def __init__(self, color: dict | None, bw: bool, blur: float, blend: str = "normal",
                 regions: list | None = None, box: QRectF | None = None, chroma: dict | None = None,
                 mkey: dict | None = None, content: QRectF | None = None, smask: dict | None = None):
        super().__init__()
        self.smask, self.src_t = smask, 0.0         # ✂ recorte de sujeto (IA) y el segundo del archivo
        self.crop = None                             # ✂ Recortar bordes (fracciones de la caja)
        self.extra: dict = {}                        # efectos de edits: rgbsplit, glow, punchy, vhs
        self.post: list = []                         # 🎨 capas de ajuste de encima (ver _post_look)
        self.mkey, self.content = mkey, content     # 👤 fondo quieto fuera (y dónde está la imagen en la caja)
        self._plate = None
        self.color, self.bw, self.blur, self.blend = color, bw, blur, blend
        self.chroma = chroma              # 🟩 pantalla verde (misma fórmula que al exportar)
        self.regions = regions or []      # desenfoque por zonas (en fracciones de la caja)
        self.box = box or QRectF(0, 0, 1, 1)

    def draw(self, painter: QPainter):
        import numpy as np
        from ..core import color as C
        pix = self.sourcePixmap(Qt.DeviceCoordinates)
        if pix.isNull():
            return
        off = self.sourceBoundingRect(Qt.DeviceCoordinates).toAlignedRect().topLeft()
        img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        bpl = img.bytesPerLine() // 4
        px = np.frombuffer(img.constBits(), np.uint32, count=bpl * h).reshape(h, bpl)[:, :w].copy()
        if self.chroma:
            from ..core import chroma as CK
            px = CK.apply_argb32(px, self.chroma)
        if self.mkey and self.content is not None:
            px = self._apply_mkey(px, w, h, painter.worldTransform(), off)
        if self.smask and self.content is not None:
            px = self._apply_smask(px, w, h, painter.worldTransform(), off)
        if self.color and not C.is_neutral(self.color):
            px = C.apply_argb32(px, self.color)
        if self.extra:
            px = _edit_looks(px, w, h, self.extra)
        if self.bw or self.blur > 0:
            rgba = px.view(np.uint8).reshape(h, w, 4)
            if self.bw:
                g = (rgba[..., 2] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 0] * 0.0722).astype(np.uint8)
                rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = g
            if self.blur > 0:
                import cv2
                k = 1 + 2 * int(2 + 15 * self.blur)
                rgba[...] = cv2.GaussianBlur(rgba, (k, k), 0)
        if self.regions:
            self._blur_regions(px, w, h, painter.worldTransform(), off)
        if self.crop:
            cr = self.crop
            b = self.box
            keep = QRectF(b.left() + cr.get("l", 0) * b.width(), b.top() + cr.get("t", 0) * b.height(),
                          b.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                          b.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
            dev = painter.worldTransform().mapRect(keep).translated(-off.x(), -off.y())
            x0, y0 = max(0, int(round(dev.left()))), max(0, int(round(dev.top())))
            x1, y1 = min(w, int(round(dev.right()))), min(h, int(round(dev.bottom())))
            a = px.view(np.uint8).reshape(h, w, 4)
            a[:y0, :, 3] = 0
            a[y1:, :, 3] = 0
            a[:, :x0, 3] = 0
            a[:, x1:, 3] = 0
        for adj in self.post:            # 🎨 capas de ajuste de encima: después de todo lo del propio clip
            px = _apply_post(px, w, h, adj)
        out = QImage(px.data, w, h, w * 4, QImage.Format_ARGB32).copy()
        painter.save()
        painter.setWorldTransform(QTransform())
        if self.blend != "normal":
            from ..core.curves import BLEND_QT
            mode = getattr(QPainter, "CompositionMode_" + BLEND_QT.get(self.blend, "SourceOver"),
                           QPainter.CompositionMode_SourceOver)
            painter.setCompositionMode(mode)
        painter.drawImage(off, out)
        painter.restore()


def _apply_mkey_impl(self, px, w, h, tr, off):
    """👤 En el visor: fuera lo que es igual al fondo vacío (solo dentro de la imagen; las bandas, transparentes)."""
    import cv2
    import numpy as np
    from ..core import motion_key as MKY
    dev = tr.mapRect(self.content).translated(-off.x(), -off.y())
    x0, y0 = max(0, int(dev.left())), max(0, int(dev.top()))
    x1, y1 = min(w, int(dev.right())), min(h, int(dev.bottom()))
    bgra = px.view(np.uint8).reshape(h, w, 4)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return px
    if self._plate is None:
        data = np.fromfile(self.mkey["plate"], np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if len(data) else None
        self._plate = None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if self._plate is None:
        return px
    full_w, full_h = int(round(dev.width())), int(round(dev.height()))
    plate = cv2.resize(self._plate, (max(1, full_w), max(1, full_h)), interpolation=cv2.INTER_AREA)
    px0, py0 = x0 - int(dev.left()), y0 - int(dev.top())
    sub_ = np.ascontiguousarray(px[y0:y1, x0:x1])
    pl = plate[py0:py0 + (y1 - y0), px0:px0 + (x1 - x0)]
    if pl.shape[:2] != sub_.shape:
        return px
    MKY.apply_argb32(sub_, self.mkey, pl)
    mask = np.zeros((h, w), bool)
    mask[y0:y1, x0:x1] = True
    bgra[~mask, 3] = 0                     # bandas negras fuera de la imagen: transparentes
    px[y0:y1, x0:x1] = sub_
    return px


LookEffect._apply_mkey = _apply_mkey_impl


def _post_look(color, fx, mix):
    """🎨 Lo que una capa de ajuste le hace a lo de debajo en el visor: (clave, datos) o None si no hace nada."""
    from ..core import color as C
    fx = fx or {}
    col = None if C.is_neutral(color) else color
    bw = bool(fx.get("bw") or fx.get("oldfilm"))
    blur = round(float(fx.get("blur", 0) or 0), 2)
    extra = {k: float(fx.get(k) or 0) for k in ("rgbsplit", "glow", "punchy", "vhs", "duotone") if float(fx.get(k) or 0) > 0}
    mix = round(max(0.0, min(1.0, float(mix))), 2)
    if (col is None and not bw and blur <= 0 and not extra) or mix <= 0.01:
        return None
    key = (C.key(col) if col else None, bw, blur, tuple(sorted(extra.items())), mix)
    return key, {"color": col, "bw": bw, "blur": blur, "extra": extra, "mix": mix}


def _apply_post(px, w, h, adj: dict):
    import numpy as np
    from ..core import color as C
    orig = px.copy() if adj["mix"] < 0.999 else None
    if adj["color"]:
        px = C.apply_argb32(px, adj["color"])
    if adj["extra"]:
        px = _edit_looks(px, w, h, adj["extra"])
    if adj["bw"] or adj["blur"] > 0:
        rgba = px.view(np.uint8).reshape(h, w, 4)
        if adj["bw"]:
            g = (rgba[..., 2] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 0] * 0.0722).astype(np.uint8)
            rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = g
        if adj["blur"] > 0:
            import cv2
            k = 1 + 2 * int(2 + 15 * adj["blur"])
            rgba[...] = cv2.GaussianBlur(rgba, (k, k), 0)
    if orig is not None:          # opacidad / fundido de la capa de ajuste: el efecto, a medias
        a = orig.view(np.uint8).reshape(h, w, 4).astype(np.float32)
        b = px.view(np.uint8).reshape(h, w, 4).astype(np.float32)
        m = adj["mix"]
        mixed = (a * (1 - m) + b * m).astype(np.uint8)
        mixed[..., 3] = a[..., 3].astype(np.uint8)
        px = mixed.view(np.uint32).reshape(h, w)
    return px


def _edit_looks(px, w, h, ex: dict):
    """Efectos de edits en el visor (las mismas ideas que al exportar): RGB, contraste, brillo y VHS.
    Todo en 8 bits con OpenCV (antes con números decimales: ~30 ms por fotograma y el visor iba a tirones)."""
    import cv2
    import numpy as np
    a = px.view(np.uint8).reshape(h, w, 4)
    alpha = a[..., 3].copy()
    img = np.ascontiguousarray(a)
    if float(ex.get("duotone", 0) or 0) > 0:      # 🟣 duotono (la misma tabla que al exportar)
        from ..core.effects import DUO_A, DUO_B
        g = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY).astype(np.float32) / 255.0
        for ch, (lo, hi) in enumerate(((DUO_A[2], DUO_B[2]), (DUO_A[1], DUO_B[1]), (DUO_A[0], DUO_B[0]))):
            img[..., ch] = np.clip(lo + (hi - lo) * g, 0, 255).astype(np.uint8)
    p = float(ex.get("punchy", 0) or 0)
    if p > 0:
        k = 1 + 0.28 * p                              # contraste (una tabla: instantáneo)
        cv2.LUT(img, np.clip((np.arange(256) - 128) * k + 128, 0, 255).astype(np.uint8), dst=img)
        sat = 0.45 * p                                # saturación: alejarse del gris
        g4 = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY), cv2.COLOR_GRAY2BGRA)
        img = cv2.addWeighted(img, 1 + sat, g4, -sat, 0)
    g = float(ex.get("glow", 0) or 0)
    if g > 0:
        small = cv2.resize(img, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
        blur = cv2.resize(cv2.GaussianBlur(small, (0, 0), 2 + 5 * g), (w, h))
        blur = cv2.add(blur, (255 * 0.04 * g,) * 3 + (0,))
        o = 0.25 + 0.45 * g                           # «pantalla»: img + (255 - img) · brillo · o
        img = cv2.add(img, cv2.multiply(cv2.bitwise_not(img), blur, scale=o / 255.0))
    shift = 0
    for key, mult in (("rgbsplit", 1.0), ("vhs", 0.3)):
        v = float(ex.get(key, 0) or 0)
        if v > 0:
            shift = max(shift, max(1, int(round(w * 0.004 * (0.5 + 1.5 * v * mult)))))
    if shift:
        img[..., 2] = np.roll(img[..., 2], -shift, axis=1)      # rojo a la izquierda
        img[..., 0] = np.roll(img[..., 0], shift, axis=1)       # azul a la derecha
    q = float(ex.get("vhs", 0) or 0)
    if q > 0:
        step = max(3, h // 135)
        img[::step, :, :3] = (img[::step, :, :3] * (1 - (0.12 + 0.2 * q))).astype(np.uint8)
        noise = _noise_tex(h, w)                      # grano: una textura hecha una vez, movida al azar
        rng = np.random.default_rng()
        n = np.roll(noise, (int(rng.integers(0, h)), int(rng.integers(0, w))), axis=(0, 1))
        sd = (6 + 10 * q) / 32.0
        img = cv2.addWeighted(img, 1.0, cv2.cvtColor(n, cv2.COLOR_GRAY2BGRA), sd, -128 * sd)
    img[..., 3] = alpha
    a[...] = img
    return px


_NOISE: dict = {}


def _noise_tex(h: int, w: int):
    import numpy as np
    key = (h, w)
    if key not in _NOISE:
        _NOISE.clear()
        _NOISE[key] = np.clip(np.random.default_rng(1).normal(128, 32, (h, w)), 0, 255).astype(np.uint8)
    return _NOISE[key]


def _apply_smask_impl(self, px, w, h, tr, off):
    """✂ En el visor: la máscara de la IA en el sitio de la imagen (fuera de ella, transparente)."""
    import cv2
    import numpy as np
    from ..core import subject_mask as SMK
    m = SMK.frame_at(self.smask, self.src_t)
    if m is None:
        return px
    dev = tr.mapRect(self.content).translated(-off.x(), -off.y())
    fw, fh = max(1, int(round(dev.width()))), max(1, int(round(dev.height())))
    alpha = np.zeros((h, w), np.float32)
    big = cv2.resize(m, (fw, fh), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    x0, y0 = int(round(dev.left())), int(round(dev.top()))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw, ch = min(w - dx0, fw - sx0), min(h - dy0, fh - sy0)
    if cw > 0 and ch > 0:
        alpha[dy0:dy0 + ch, dx0:dx0 + cw] = big[sy0:sy0 + ch, sx0:sx0 + cw]
    bgra = px.view(np.uint8).reshape(h, w, 4)
    bgra[..., 3] = (bgra[..., 3].astype(np.float32) * alpha).astype(np.uint8)
    return px


LookEffect._apply_smask = _apply_smask_impl


def _full_frame(project, c) -> bool:
    from ..export.ffmpeg_export import _full_frame as ff
    return ff(project, c)


def _blur_regions_impl(self, px, w, h, tr, off):
    """Desenfoca las zonas (cuadro o círculo de borde suave) sobre la imagen ya pintada del clip."""
    import cv2
    import numpy as np
    rgba = px.view(np.uint8).reshape(h, w, 4)
    b = self.box
    for r in self.regions:
        local = QRectF(b.left() + (r["x"] - r["w"] / 2) * b.width(), b.top() + (r["y"] - r["h"] / 2) * b.height(),
                       r["w"] * b.width(), r["h"] * b.height())
        dev = tr.mapRect(local).translated(-off.x(), -off.y())
        x0, y0 = max(0, int(dev.left())), max(0, int(dev.top()))
        x1, y1 = min(w, int(dev.right())), min(h, int(dev.bottom()))
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        sub_ = rgba[y0:y1, x0:x1]
        sw, sh = x1 - x0, y1 - y0
        f = max(2, int(min(sw, sh) * (0.04 + 0.16 * r["amount"]) / 2))     # rápido: reducir y ampliar
        small = cv2.resize(sub_, (max(1, sw // f), max(1, sh // f)), interpolation=cv2.INTER_AREA)
        blurred = cv2.GaussianBlur(cv2.resize(small, (sw, sh), interpolation=cv2.INTER_LINEAR), (5, 5), 0)
        if r["shape"] == "ellipse":
            yy, xx = np.ogrid[:sh, :sw]
            d = np.sqrt(((xx - sw / 2) / (sw / 2)) ** 2 + ((yy - sh / 2) / (sh / 2)) ** 2)
            a = np.clip((1 - d) / 0.12, 0, 1)[..., None]
            sub_[...] = (blurred * a + sub_ * (1 - a)).astype(np.uint8)
        else:
            sub_[...] = blurred


LookEffect._blur_regions = _blur_regions_impl


class _TitleEdit(QLineEdit):
    """El nombre del video/proyecto en la cabecera del visor: parece un texto; clic = escribir otro nombre."""
    renamed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFrame(False)
        self.setObjectName("titleedit")
        self.setStyleSheet("QLineEdit#titleedit { background: transparent; color: #b8bcc4; border: none; "
                           "border-bottom: 1px solid transparent; padding: 0 2px; }"
                           "QLineEdit#titleedit:hover { border-bottom: 1px dashed #5a6070; }"
                           "QLineEdit#titleedit:focus { background: #15171c; color: #e8eaee; "
                           "border-bottom: 1px solid #4a8fe0; }")
        self.setToolTip("Nombre del video / proyecto: clic para cambiarlo (Intro = listo, Esc = dejarlo).\n"
                        "Se usa al guardar y como nombre del archivo al exportar. Ctrl+Z lo deshace.")
        self.setPlaceholderText("Nombre del video…")
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._shown = ""
        self.textChanged.connect(self._fit)
        self.editingFinished.connect(self._done)

    def _fit(self, _t=""):
        """Tan ancho como el nombre (hasta 360), pero cede sitio si la cabecera es estrecha (nunca pisa nada)."""
        self.updateGeometry()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        fm = self.fontMetrics()
        return QSize(min(360, max(90, fm.horizontalAdvance(self.text() or self.placeholderText()) + 18)),
                     super().sizeHint().height())

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(70, super().minimumSizeHint().height())

    def show_name(self, text: str):
        self._shown = text
        if not self.hasFocus():
            self.setText(text)
            self.setCursorPosition(0)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.setText(self._shown)
            self.clearFocus()
            return
        super().keyPressEvent(e)
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.clearFocus()

    def _done(self):
        try:
            name = " ".join(self.text().split()).strip()
        except RuntimeError:                      # se está cerrando la ventana
            return
        for ch in '<>:"/\\|?*':                   # no valen en un nombre de archivo
            name = name.replace(ch, "")
        if not name:
            self.setText(self._shown)
        elif name != self._shown:
            self.renamed.emit(name)
        self.setCursorPosition(0)


class PreviewPanel(QWidget):
    """Visor al estilo de DaVinci Resolve: cabecera con el nombre y el timecode, imagen,
    y los controles de reproducción centrados debajo."""

    def set_composition(self, n: int):
        self.canvas.comp.set_count(n)
        self._comp_acts[n].setChecked(True)
        self.btn_comp.setText("⊞ Composición" + (f" · {n}" if n else ""))

    def _mode_label(self, mode: str):
        names = {"transform": "⤧ Transformar", "crop": "✂ Recortar", "dynzoom": "🔍 Zoom dinámico",
                 "annotate": "✏ Anotaciones"}
        self.btn_mode.setText(names.get(mode, mode))
        for k, a in self._mode_acts.items():
            a.setChecked(k == mode)

    def _guides_changed(self):
        self._guides_set([k for k, a in self._guide_acts.items() if a.isChecked()])

    def _guides_set(self, modes):
        self.canvas.guides.set_modes(modes)
        QSettings("EditorIA", "EditorIA").setValue("visor/guias", ",".join(modes))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = Canvas()
        self.fps = 30.0

        header = QWidget()
        header.setObjectName("panelheader")
        header.setFixedHeight(30)
        self.header = header
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        self.title_label = _TitleEdit()
        self.title_label.show_name("Proyecto sin título")
        self.zoom_label = QPushButton("Ajustar")
        self.zoom_label.setObjectName("flat")
        self.zoom_label.setFocusPolicy(Qt.NoFocus)
        self.zoom_label.setToolTip("Zoom de la vista del visor (rueda del ratón). Clic = ajustar a la ventana.")
        self.zoom_label.clicked.connect(self.canvas.fit_view)
        self.canvas.view_zoom_changed.connect(
            lambda z: self.zoom_label.setText("Ajustar" if z == 1.0 else f"🔍 {z * 100:.0f} %"))
        self.time_label = QLabel("00:00:00:00")
        self.time_label.setObjectName("timecode")
        self.time_label.setToolTip("Tiempo del cabezal (horas:minutos:segundos:fotograma)")
        hl.addWidget(self.title_label)
        hl.addSpacing(14)
        # Acciones rápidas (la barra de encima de la imagen, como en Resolve)
        self.quick: dict[str, QPushButton] = {}
        for key, text, tip in (("silence", "✂ Eliminar silencio", "Quita los silencios de los clips seleccionados "
                                "(o de la narración), como en DaVinci Resolve"),
                               ("gaps", "⇤ Huecos", "Quitar los espacios vacíos entre clips")):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            hl.addWidget(b)
            self.quick[key] = b
        hl.addStretch()
        from PySide6.QtWidgets import QComboBox
        from ..core.proxies import LEVELS
        self.quality = QComboBox()
        for key, (label, _div) in LEVELS.items():
            self.quality.addItem(label, key)
        self.quality.setToolTip("Resolución de la línea de tiempo (como en Resolve): «Media» o «Un cuarto» "
                                "reproducen copias ligeras para editar con fluidez. Al exportar se usan "
                                "siempre los originales.")
        from PySide6.QtWidgets import QMenu, QToolButton
        self.btn_guides = QToolButton()
        self.btn_guides.setText("▦ Guías")
        self.btn_guides.setToolTip("Guías del visor (no salen al exportar): tercios, centro, zona segura de "
                                   "Shorts/TikTok y el borde del encuadre")
        self.btn_guides.setPopupMode(QToolButton.InstantPopup)
        gm = QMenu(self.btn_guides)
        from PySide6.QtWidgets import QWidgetAction
        wa = QWidgetAction(gm)
        self.guides_panel = _GuidesPanel(self.canvas.guides.modes, self._guides_set)
        wa.setDefaultWidget(self.guides_panel)
        gm.addAction(wa)
        self._guide_acts = self.guides_panel.buttons          # (compatibilidad: clave → botón marcable)
        self.btn_guides.setMenu(gm)
        # Modo del visor (Resolve: abajo a la izquierda): Transformar / Recortar / Zoom dinámico / Anotaciones
        self.btn_mode = QToolButton()
        self.btn_mode.setPopupMode(QToolButton.InstantPopup)
        self.btn_mode.setToolTip("Qué haces con el ratón en el visor (como en DaVinci Resolve)")
        mm = QMenu(self.btn_mode)
        self._mode_acts = {}
        for key, label in (("transform", "⤧ Transformar"), ("crop", "✂ Recortar"), ("dynzoom", "🔍 Zoom dinámico"),
                           ("annotate", "✏ Anotaciones")):
            a = mm.addAction(label, lambda k=key: self.canvas.set_mode(k))
            a.setCheckable(True)
            self._mode_acts[key] = a
        mm.addSeparator()
        self.act_clear_ann = mm.addAction("Borrar las anotaciones de aquí")
        self.btn_mode.setMenu(mm)
        self.canvas.mode_changed.connect(self._mode_label)
        self._mode_label("transform")
        hl.addWidget(self.btn_guides)
        self.btn_comp = QToolButton()
        self.btn_comp.setText("⊞ Composición")
        self.btn_comp.setToolTip("Varias imágenes o videos en pantalla a la vez: elige cuántos huecos y arrastra "
                                 "desde Medios a cada «+» (fuera de los huecos = fondo). Van en pistas propias "
                                 "«⊞ Composición» / «⊞ Fondo».")
        self.btn_comp.setPopupMode(QToolButton.InstantPopup)
        cm = QMenu(self.btn_comp)
        from PySide6.QtGui import QActionGroup
        grp = QActionGroup(cm)
        self._comp_acts = {}
        for n, label in ((0, "Sin composición"), (2, "2 huecos"), (3, "3 huecos"), (4, "4 (cuadrícula)"),
                         (6, "6 huecos"), (9, "9 (3 × 3)")):
            a = cm.addAction(label)
            a.setCheckable(True)
            a.setChecked(n == 0)
            grp.addAction(a)
            a.triggered.connect(lambda _on, nn=n: self.set_composition(nn))
            self._comp_acts[n] = a
        self.btn_comp.setMenu(cm)
        hl.addWidget(self.btn_comp)
        hl.addSpacing(10)
        hl.addWidget(QLabel("Calidad"))
        hl.addWidget(self.quality)
        hl.addSpacing(12)
        hl.addWidget(self.zoom_label)
        hl.addSpacing(18)
        hl.addWidget(self.time_label)

        def btn(text, tip):
            b = QPushButton(text)
            b.setObjectName("transport")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            return b

        self.btn_start = btn("⏮", "Ir al inicio (Inicio)")
        self.btn_back = btn("◀", "Fotograma anterior (←)")
        self.btn_play = btn("▶", "Reproducir / pausar (Espacio)")
        self.btn_fwd = btn("▶|", "Fotograma siguiente (→)")
        self.btn_end = btn("⏭", "Ir al final (Fin)")
        self.btn_loop = btn("🔁", "Repetir en bucle (Ctrl+/): el tramo marcado con I y O, o todo")
        self.btn_loop.setCheckable(True)
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("timecode")
        self.rate_label.setToolTip("Velocidad de reproducción: J = hacia atrás, K = parar, L = hacia delante "
                                   "(pulsa otra vez para ir más rápido)")
        self.duration_label = QLabel("00:00:00:00")
        self.duration_label.setObjectName("dim")
        self.duration_label.setToolTip("Duración total")

        controls = QHBoxLayout()
        controls.setContentsMargins(10, 2, 10, 4)
        controls.addWidget(self.btn_mode)          # (como Resolve: el modo del visor, abajo a la izquierda)
        controls.addSpacing(6)
        controls.addWidget(self.duration_label)
        controls.addStretch()
        for b in (self.btn_start, self.btn_back, self.btn_play, self.btn_fwd, self.btn_end, self.btn_loop):
            controls.addWidget(b)
        controls.addSpacing(8)
        controls.addWidget(self.rate_label)
        controls.addSpacing(8)
        self.meter = LevelMeter()
        controls.addWidget(self.meter)
        controls.addStretch()
        from .task_window import TaskChip
        # ◈ trabajos de la IA en marcha: en la barra de DEBAJO de la imagen, a la derecha (solo si hay alguno)
        self.task_chip = TaskChip()
        controls.addWidget(self.task_chip)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(controls)

    def set_playing(self, playing: bool):
        self.btn_play.setText("⏸" if playing else "▶")

    def set_rate(self, rate: float, playing: bool):
        if not playing or rate == 1.0:
            self.rate_label.setText("")
        else:
            arrows = "◀◀" if rate < 0 else "▶▶"
            self.rate_label.setText(f"{arrows} {abs(rate):g}×")

    def set_title(self, text: str):
        self.title_label.show_name(text)

    def set_time(self, t: float, total: float):
        self.time_label.setText(fmt_tc(t, self.fps))
        self.duration_label.setText(fmt_tc(total, self.fps))


class _Lane:
    """Un reproductor que sigue al clip activo de una pista."""

    def __init__(self, parent: QObject, video_output=None):
        self.player = QMediaPlayer(parent)
        self.audio = QAudioOutput(parent)
        self.player.setAudioOutput(self.audio)
        if video_output is not None:
            self.player.setVideoOutput(video_output)
        self.path: str | None = None
        self.loaded = False
        self.loads = 0           # cuántas veces abrió un archivo (diagnóstico: con cortes rápidos debe ser poco)
        self.want_pos = 0.0
        self.want_play = False
        self.player.mediaStatusChanged.connect(self._on_status)

    def _on_status(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and not self.loaded:
            self.loaded = True
            if self.want_play:
                self.player.setPosition(int(self.want_pos * 1000))
                self.player.play()
            else:
                # En pausa: primero pausar y LUEGO ir al segundo; así se pinta el fotograma (antes, al cambiar
                # de archivo —p. ej. «Calidad: Un cuarto»— el visor se quedaba en negro hasta reproducir)
                self.player.pause()
                self.player.setPosition(int(self.want_pos * 1000))
                QTimer.singleShot(150, self._repaint_frame)

    def _repaint_frame(self):
        if self.loaded and self.player.playbackState() != QMediaPlayer.PlayingState:
            self.player.setPosition(int(self.want_pos * 1000))

    def idle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()

    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0):
        self.audio.setVolume(max(0.0, min(1.0, volume)))
        if playing and abs(self.player.playbackRate() - rate) > 1e-3:
            self.player.setPlaybackRate(rate)
        if path != self.path:
            self.path, self.loaded = path, False
            self.loads += 1
            self.want_pos, self.want_play = pos, playing
            self.player.setSource(QUrl.fromLocalFile(path))
            return
        if not self.loaded:
            self.want_pos, self.want_play = pos, playing
            return
        cur = self.player.position() / 1000.0
        state = self.player.playbackState()
        if playing:
            if state != QMediaPlayer.PlayingState:
                self.player.setPosition(int(pos * 1000))
                self.player.play()
            elif abs(cur - pos) > 0.3 * max(1.0, rate):  # se desincronizó: corregir
                self.player.setPosition(int(pos * 1000))
        else:
            if state == QMediaPlayer.PlayingState:
                self.player.pause()
            if abs(cur - pos) > 0.02:
                self.player.setPosition(int(pos * 1000))
            if state == QMediaPlayer.StoppedState:
                self.player.pause()

    def dispose(self):
        self.player.stop()
        self.player.deleteLater()
        self.audio.deleteLater()

    def park(self):
        """Se aparta sin apagarlo (en pausa y sin sonido): QMediaPlayer.stop() a veces se queda BLOQUEADO para
        siempre (Reclaimer congelado al cambiar de proyecto o de pestaña). Luego se reutiliza en otra pista."""
        self.audio.setVolume(0.0)
        self.idle()
        self.want_play = False


class _VideoLane:
    """Reproductores de una pista de video: cada archivo en el suyo (hasta VIDEO_POOL) y el siguiente plano
    preparado de antemano (pausado en su punto), así los cortes son inmediatos aunque cambien de archivo."""

    def __init__(self, parent: QObject, layer):
        self.layer = layer
        self.slots = [_Lane(parent, v) for v in layer.videos]
        self.active = 0
        self._used = [0.0] * len(self.slots)
        self._n = 0

    def _slot_for(self, path: str, avoid: int | None = None) -> int:
        for i, s in enumerate(self.slots):
            if s.path == path:
                return i
        free = [i for i in range(len(self.slots)) if i != avoid]
        return min(free, key=lambda i: self._used[i])          # el que hace más que no se usa

    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0):
        i = self._slot_for(path, avoid=None if self.slots[self.active].path == path else self.active)
        if i != self.active:
            old = self.slots[self.active]
            old.audio.setVolume(0.0)
            old.idle()
            self.active = i
            self.layer.set_active(i)
        self._n += 1
        self._used[i] = self._n
        self.slots[i].drive(path, pos, playing, volume, rate)

    def preload(self, path: str, pos: float):
        """Prepara el siguiente plano en otro reproductor (pausado en su punto, sin sonido)."""
        if self.slots[self.active].path == path:
            return                     # mismo archivo: con las copias ligeras el salto es inmediato
        i = self._slot_for(path, avoid=self.active)
        s = self.slots[i]
        self._used[i] = self._n + 0.5
        s.audio.setVolume(0.0)
        if s.path != path:
            s.path, s.loaded = path, False
            s.loads += 1
            s.want_pos, s.want_play = pos, False
            s.player.setSource(QUrl.fromLocalFile(path))
            return
        if not s.loaded:
            s.want_pos = pos
            return
        if s.player.playbackState() == QMediaPlayer.PlayingState:
            s.player.pause()
        if abs(s.player.position() / 1000.0 - pos) > 0.04:
            s.want_pos = pos
            s.player.setPosition(int(pos * 1000))

    def idle(self):
        for s in self.slots:
            s.idle()

    def dispose(self):
        for s in self.slots:
            s.dispose()

    def park(self):
        for s in self.slots:
            s.park()


class PlaybackEngine(QObject):
    time_changed = Signal(float)
    playing_changed = Signal(bool)

    def __init__(self, ctrl, preview: PreviewPanel, parent=None):
        super().__init__(parent)
        self.mute_all = False          # 🎙 al grabar la voz en off: todo en silencio
        self.ctrl = ctrl
        self.preview = preview
        self.time = 0.0
        self.playing = False
        self.rate = 1.0          # J/K/L: negativa = hacia atrás; 2, 4, 8 = más rápido
        self.loop = False        # repetir el tramo marcado (o todo)
        self.color_bypass = False   # «ver sin corrección» (comparar el color)
        self._t0 = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._vlanes: dict[str, _Lane] = {}   # un reproductor de video por pista
        self._audio: dict[str, _Lane] = {}
        self._ranges: list[tuple[float, float]] = []  # fragmentos pendientes de "Escuchar"
        self._stop_at: float | None = None
        self._cues = []        # subtítulos ya calculados
        self._speech: list[tuple[float, float]] = []
        self._cue_starts: list[float] = []

        preview.btn_play.clicked.connect(self.toggle)
        preview.btn_start.clicked.connect(lambda: self.user_seek(0))
        preview.btn_end.clicked.connect(lambda: self.user_seek(self.ctrl.project.duration()))
        preview.btn_back.clicked.connect(lambda: self.step(-1))
        preview.btn_fwd.clicked.connect(lambda: self.step(1))
        preview.btn_loop.toggled.connect(self.set_loop)
        ctrl.project_changed.connect(self._refresh)
        ctrl.transcript_changed.connect(lambda _m: self._refresh())
        ctrl.project_replaced.connect(lambda: (self.pause(), self.seek(0)))
        self._refresh()

    def _next_clip(self, track_id: str, c):
        best = None
        for o in self.ctrl.project.clips_on(track_id):
            if o.start >= c.end - 1e-3 and o.enabled and (best is None or o.start < best.start):
                best = o
        return best

    # ----------------------------------------------------------- control
    def toggle(self):
        self.pause() if self.playing else self.play()

    def set_loop(self, on: bool):
        self.loop = on
        if self.preview.btn_loop.isChecked() != on:
            self.preview.btn_loop.setChecked(on)

    def jkl(self, key: str):
        """Como en Resolve: L = adelante (otra vez = 2×, 4×, 8×), J = atrás (igual), K = parar."""
        if key == "k":
            self.pause()
            return
        fwd = key == "l"
        if self.playing and (self.rate > 0) == fwd:
            new = max(-8.0, min(8.0, self.rate * 2))
        else:
            new = 1.0 if fwd else -1.0
        if self.playing:
            self._t0, self.rate = self.time, new
            self._clock.restart()
            self.preview.set_rate(self.rate, True)
            self._sync()
        else:
            self.play(rate=new)

    def play_marked(self):
        """Reproduce de la entrada a la salida (Alt+/)."""
        rng = self.ctrl.project.marked_range()
        if rng:
            self.play_ranges([rng])

    def play(self, rate: float = 1.0):
        if self.playing:
            return
        total = self.ctrl.project.duration()
        if total <= 0:
            return
        self.rate = rate
        if rate > 0 and self.time >= total - 0.05:
            self.time = 0.0
        elif rate < 0 and self.time <= 0.05:
            self.time = total
        self.playing = True
        self._t0 = self.time
        self._clock.restart()
        self._timer.start()
        self.preview.set_playing(True)
        self.preview.set_rate(self.rate, True)
        self.playing_changed.emit(True)
        self._sync()

    def play_ranges(self, ranges: list[tuple[float, float]]):
        """Reproduce uno o varios fragmentos seguidos y se detiene (botón «Escuchar»)."""
        ranges = [(max(0.0, a), b) for a, b in ranges if b > a]
        if not ranges:
            return
        self.pause()
        self._ranges = ranges[1:]
        self.seek(ranges[0][0])
        self._stop_at = ranges[0][1]
        self.play()

    def pause(self):
        self._stop_at = None
        self._ranges = []
        if not self.playing:
            return
        self.playing = False
        self._timer.stop()
        self.rate = 1.0
        self.preview.set_playing(False)
        self.preview.set_rate(1.0, False)
        self.playing_changed.emit(False)
        self._sync()

    def seek(self, t: float):
        self.time = max(0.0, min(t, max(self.ctrl.project.duration(), 0.0)))
        if self.playing:
            self._t0 = self.time
            self._clock.restart()
        self._sync()
        self.time_changed.emit(self.time)

    def user_seek(self, t: float):
        """Salto pedido por el usuario: cancela cualquier «Escuchar» en curso."""
        self._stop_at = None
        self._ranges = []
        self.seek(t)

    def step(self, frames: int):
        self.pause()
        self.seek(self.time + frames / max(1.0, self.ctrl.project.fps))

    def _tick(self):
        t = self._t0 + self._clock.elapsed() / 1000.0 * self.rate
        total = self.ctrl.project.duration()
        if self.loop and self._stop_at is None:      # bucle: el tramo marcado (o todo el video)
            a, b = self.ctrl.project.marked_range() or (0.0, total)
            if self.rate > 0 and t >= b:
                self.seek(a)
                self.time_changed.emit(self.time)
                return
            if self.rate < 0 and t <= a:
                self.seek(b)
                self.time_changed.emit(self.time)
                return
        if self.rate < 0 and t <= 0.0:
            self.time = 0.0
            self.pause()
        elif self._stop_at is not None and t >= self._stop_at:
            if self._ranges:  # siguiente fragmento
                a, b = self._ranges.pop(0)
                self._stop_at = b
                self.seek(a)
                return
            self.time = self._stop_at
            self.pause()
        elif t >= total:
            self.time = total
            self.pause()
        else:
            self.time = t
            self._sync()
        self.time_changed.emit(self.time)

    def refresh_sources(self):
        """Se crearon copias ligeras (proxies): el visor pasa a usarlas."""
        self._sync()

    def _recycle(self):
        # Reproductores de pistas que ya no están: se APARTAN (en pausa) y los reutilizan las pistas nuevas. Nunca
        # se apagan durante la sesión: QMediaPlayer.stop() a veces se bloquea para siempre (congelaba Reclaimer al
        # cambiar de proyecto o de pestaña).
        spare_a = self.__dict__.setdefault("_spare_audio", [])
        spare_v = self.__dict__.setdefault("_spare_video", [])
        canvas = self.preview.canvas
        valid = {t.id for t in self.ctrl.project.tracks if t.kind == TRACK_AUDIO}
        for tid in list(self._audio):
            if tid not in valid:
                lane = self._audio.pop(tid)
                lane.park()
                spare_a.append(lane)
        vvalid = {t.id for t in self.ctrl.project.tracks if t.kind == TRACK_VIDEO}
        for tid in list(canvas.layers):
            if tid not in vvalid:
                layer = canvas.layers.pop(tid)
                layer.hide()
                lane = self._vlanes.pop(tid, None)
                if lane is not None:
                    lane.park()
                spare_v.append((layer, lane))
        for tid in [t for t in vvalid if t not in canvas.layers]:     # pistas nuevas: con lo apartado
            if not spare_v:
                break
            layer, lane = spare_v.pop()
            canvas.layers[tid] = layer
            if lane is not None:
                self._vlanes[tid] = lane

    def _refresh(self):
        self._recycle()
        p = self.ctrl.project
        self.preview.canvas.set_canvas_size(p.width, p.height)
        self.preview.fps = p.fps
        self.preview.set_title(p.name)
        self._speech = audio_fx.speech_intervals(p)   # para bajar la música cuando hablas
        self._cues = styled_cues(p) if p.subtitles.enabled else []
        self._cue_starts = [c.start for c in self._cues]
        self._sync()

    # -------------------------------------------------------- sincronizar
    def _sync(self):
        self._recycle()               # pistas nuevas: con los reproductores apartados (nunca se crean de más)
        p = self.ctrl.project
        t = self.time
        self.preview.set_time(t, p.duration())

        # Subtítulos
        cue = None
        k = bisect.bisect_right(self._cue_starts, t) - 1
        if k >= 0 and t < self._cues[k].end:
            cue = self._cues[k]
        self.preview.canvas.subs.set_state(cue, p.subtitles if cue else None, t)

        # Textos en pantalla
        titles = []
        for tr in p.tracks:
            if tr.kind == TRACK_TEXT and not tr.hidden:
                c = p.clip_at(tr.id, t)
                if c is not None and c.enabled and c.text:
                    titles.append((c.text, t - c.start, c.duration))
        self.preview.canvas.titles.set_items(titles)

        # Textos con «Desenfocar lo de debajo»: mientras se ven, la imagen de debajo se desenfoca
        under = 0.0
        for tr in p.tracks:
            if tr.kind == TRACK_TEXT and not tr.hidden:
                tc = p.clip_at(tr.id, t)
                if tc is not None and tc.enabled and tc.text and float(tc.text.get("blur_under") or 0) > 0:
                    ramp = max(0.0, min(1.0, (t - tc.start) / 0.2, (tc.end - t) / 0.2))
                    under = max(under, float(tc.text["blur_under"]) * ramp)

        # Video: una capa por pista (de arriba a abajo). Si una capa tapa toda la pantalla,
        # las de debajo no se ven y no hace falta reproducirlas.
        canvas = self.preview.canvas
        vtracks = [tr for tr in p.tracks if tr.kind == TRACK_VIDEO]
        covered = False
        post: list = []                # 🎨 capas de ajuste de encima (se aplican a las capas de debajo)
        from ..core import generators as _GEN
        for depth, tr in enumerate(vtracks):
            layer = canvas.layer(tr.id)
            lane = self._vlanes.get(tr.id)
            c = None if (covered or tr.hidden) else p.clip_at(tr.id, t)
            m = p.media_of(c) if c else None
            if c is None or not c.enabled or m is None or m.id in self.ctrl.missing or m.kind == KIND_AUDIO:
                layer.hide()
                if lane:
                    lane.idle()
                continue
            src_t = c.src_at(t - c.start) if m.kind != KIND_IMAGE else t - c.start
            zoom = transform.value_at(c.zoom_kf, src_t)
            box_now = _decor_box(c, canvas.W, canvas.H, transform.layout_at(c, t - c.start, m.kind == KIND_IMAGE))
            cx = transform.follow_at(box_now, src_t)
            if cx is not None:                     # 🎯 encuadre que sigue la acción: dónde va el recorte ahora
                box_now = dict(box_now, _cx=round(cx, 4))
            from ..core import fill as _FILL
            rel = _FILL.of(c.fx)
            if rel is not None:                    # ▦ relleno detrás (toda la pantalla)
                box_now = dict(box_now or transform.FULL, _fill=rel, bg="none")
            z_value = len(vtracks) - depth
            if m.kind == KIND_IMAGE:
                if lane:
                    lane.idle()
                layer.place(canvas.W, canvas.H, box_now, m.width, m.height, zoom, m.path, z_value)
            else:
                if lane is None:
                    lane = self._vlanes[tr.id] = _VideoLane(self, layer)
                from ..core import black_bars as _BB
                bars = _BB.of(box_now)                # ▭ sin barras negras: se encuadra con el tamaño sin ellas
                sw_, sh_ = _BB.size_without(m, bars)
                layer.place(canvas.W, canvas.H, box_now, sw_, sh_, zoom, None, z_value, bars)
                vol = 0.0 if (not p.audible(tr) or c.link) else curves.gain(c, t)   # vinculado: suena desde su pista de audio
                if self.mute_all:          # 🎙 grabando la voz: el proyecto no suena (no se cuela en el micro)
                    vol = 0.0
                run, rate = self._lane_motion(c)
                lane.drive(self.ctrl.preview_path(m), src_t, run, vol if run else 0.0, rate)
                # El siguiente plano de la pista, preparado antes de que llegue (cortes sin trabas)
                nxt = self._next_clip(tr.id, c)
                if nxt is not None and nxt.start - t < 2.5:
                    nm = p.media_of(nxt)
                    if nm is not None and nm.kind == KIND_VIDEO and nm.id not in self.ctrl.missing:
                        lane.preload(self.ctrl.preview_path(nm), nxt.src_at(0.0))
            adj = _GEN.is_adjust(m)
            layer.set_color(None if (self.color_bypass or adj) else c.color)
            layer.set_post([] if adj else list(post))
            layer.set_blend(c.blend, 1.0 if adj else curves.opacity(c, t, m.kind == KIND_IMAGE))
            if adj:             # 🎨 su efecto va a lo de debajo; ella solo pone lo de pantalla entera (viñeta, destello)
                fx_adj = {k: v for k, v in (c.fx or {}).items() if k in ("vignette", "flash")}
                layer.set_effects(fx_adj, t - c.start, c.duration, t - c.start)
                mix = curves.opacity(c, t, True) * effects.fade_gain(c.fx, t - c.start, c.duration)
                post.append((None if self.color_bypass else c.color, dict(c.fx or {}), mix))
                continue
            fx_now = transitions.preview_fx(p, c)
            if under > 0.01:
                fx_now = dict(fx_now or {}, blur=max(float((fx_now or {}).get("blur", 0) or 0), round(under, 2)))
            layer.set_effects(fx_now, t - c.start, c.duration, c.src_at(t - c.start))
            layer.set_decor(c.fx, t - c.start, canvas.W, canvas.H)
            # Solo tapa lo de debajo si es opaco de verdad: con ✂ recorte de sujeto, pantalla verde, opacidad,
            # mezcla o recorte, la pista de debajo se tiene que ver (la misma regla que al exportar)
            if _full_frame(p, c) and zoom[0] >= 0.999:
                covered = True

        # Audio: un reproductor por pista de audio
        for tr in p.tracks:
            if tr.kind != TRACK_AUDIO:
                continue
            lane = self._audio.get(tr.id)
            c = p.clip_at(tr.id, t)
            m = p.media_of(c) if c else None
            if c is None or not c.enabled or m is None or m.id in self.ctrl.missing \
                    or not (m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)):
                if lane:
                    lane.idle()
                continue
            if lane is None:
                spare_a = self.__dict__.get("_spare_audio") or []
                lane = self._audio[tr.id] = spare_a.pop() if spare_a else _Lane(self)
            vol = 0.0 if (not p.audible(tr) or self.mute_all) else curves.gain(c, t) * effects.fade_gain(c.fx, t - c.start,
                                                                                                         c.duration)
            if tr.duck_db is not None:  # la música baja sola mientras hablas
                vol *= audio_fx.duck_gain(self._speech, t, tr.duck_db)
            # En pausa (o hacia atrás) no suena el audio: solo se coloca en su sitio.
            run, rate = self._lane_motion(c)
            lane.drive(self.ctrl.preview_path(m), c.src_at(t - c.start), run, vol if run else 0.0, rate)

    def _lane_motion(self, c) -> tuple[bool, float]:
        """¿El reproductor de este clip avanza solo, y a qué velocidad? Hacia atrás, congelado o con J
        se coloca fotograma a fotograma (sin sonido)."""
        rate = self.rate * c.speed
        if not self.playing or rate <= 0 or c.reverse:
            return False, 1.0
        return True, rate
