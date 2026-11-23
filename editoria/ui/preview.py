"""
Panel central: visor del video y motor de reproducción.

El "reloj" de la timeline manda. En cada momento se mira qué clip hay bajo el cabezal
(en la pista de video visible más alta y en cada pista de audio) y se sincroniza
un reproductor para cada uno.
"""
from __future__ import annotations

import bisect
import math
import os

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
from .transport_extra import ganancia_escucha as _ganancia_escucha


VIDEO_POOL = 3   # reproductores por pista de video (un archivo abierto en cada uno)
PROPIO_POOL = 2  # ⚡ videos extra de cada capa para el motor propio: lo pesado y la pausa (ver _MixedVideoLane)

# 🎞 Archivos que el reproductor de Qt NO puede decodificar (p. ej. AV1 de YouTube sin aceleración por la tarjeta: «Your
# platform doesn't support hardware accelerated AV1 decoding»): al ir a un segundo en pausa da «fin del archivo» y el
# visor se quedaba en NEGRO hasta tener la copia ligera. Para ellos el visor usa cualquier copia ligera que ya exista,
# pide una (aunque la calidad sea «Completa») y, mientras, enseña fotogramas sueltos sacados con FFmpeg.
NO_DECODIFICA: set = set()
_AVISOS_NO_DECODIFICA: list = []          # funciones(ruta) a las que se avisa al descubrir uno
# ⚡ Archivos que ESTE equipo no consigue reproducir a tiempo ni con el motor propio (4K de mucha tasa en un portátil
# modesto…): se pide su copia ligera (aunque la calidad sea «Completa») y, en cuanto existe, el visor la usa al
# reproducir. Exportar sigue usando el original.
LENTOS: set = set()
_AVISOS_LENTO: list = []


def _marcar_lento(path: str):
    if not path or path in LENTOS:
        return
    LENTOS.add(path)
    for f in list(_AVISOS_LENTO):
        try:
            f(path)
        except Exception:  # noqa: BLE001 - un aviso nunca para el visor
            pass


def _marcar_no_decodifica(path: str):
    if not path or path in NO_DECODIFICA:
        return
    NO_DECODIFICA.add(path)
    for f in list(_AVISOS_NO_DECODIFICA):
        try:
            f(path)
        except Exception:  # noqa: BLE001 - un aviso nunca para el visor
            pass


def _fotograma(path: str, t: float, alto: int = 540) -> QImage:
    """Un fotograma del archivo en el segundo t, decodificado con FFmpeg (que sí lee AV1): para el visor mientras se
    hace la copia ligera. Corre en segundo plano."""
    from ..core import media as _MT
    r = _MT.run_quiet([_MT.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
                       "-frames:v", "1", "-vf", f"scale=-2:{int(alto)}", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                      timeout=30)
    img = QImage()
    if r.returncode == 0 and r.stdout:
        img.loadFromData(r.stdout, "PNG")
    return img


def decodificar_grafica() -> bool:
    """Ajuste «Decodificar el video con la tarjeta gráfica». Por defecto: sí en PC modesto, no en uno normal."""
    try:
        v = QSettings("EditorIA", "EditorIA").value("reproduccion/decodificar_grafica", None)
        if v is not None:
            return str(v).lower() == "true"
        from ..core import hw
        return bool(hw.equipo().get("modesto"))
    except Exception:  # noqa: BLE001
        return False


def _ajustar_decodificacion():
    """Antes de crear ningún reproductor: con el ajuste en «procesador», Qt no crea un decodificador D3D11VA en el
    hilo de la interfaz al abrir cada archivo (~35–150 ms de parón). Si el usuario ya fijó la variable, no se toca."""
    if "QT_FFMPEG_DECODING_HW_DEVICE_TYPES" in os.environ:
        return
    try:
        if not decodificar_grafica():
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = "none"
    except Exception:  # noqa: BLE001
        pass


_ajustar_decodificacion()


def _decor_box(c, W: int, H: int, layout="clip"):
    """Con sombra o contorno, la imagen se encoge un poco dentro de su caja (igual que al exportar).
    layout: la disposición de ESE momento (🎞 si está animada); por defecto, la fija del clip."""
    from ..core import decor
    lay = c.layout if layout == "clip" else layout
    if not decor.has_frame(c.fx):
        return lay
    # (🌑 una sombra NUEVA sale por fuera: la caja se agranda su margen y luego se encoge lo mismo → el clip, igual)
    box = dict(decor.caja_con_sombra(lay, c.fx, W, H) or transform.FULL)
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


_LADO_SOMBRA = 768          # 🌑 la sombra se calcula a este lado como mucho (va desenfocada: no necesita más)
_SOMBRAS: dict = {}         # 🌑 sombras ya calculadas (forma + valores → imagen): ver TrackLayer._poner_sombra


def _pintar_sombra(bw: float, bh: float, s: float, R: int, rad: int, zona, caja, tr, pix, ow: float, color: str,
                   fuerza: float) -> QPixmap:
    """🌑 La imagen de la sombra (a escala s, con R px de margen): la forma (el alfa de `pix` colocado con `tr` dentro
    de `caja`; sin pix, el polígono `zona`; con contorno, también su marco), desenfocada con una caja de radio `rad`
    (la de boxblur al exportar), con su color y su fuerza."""
    from PySide6.QtGui import QPainterPath
    w_ = int(math.ceil(bw * s)) + 2 * R
    h_ = int(math.ceil(bh * s)) + 2 * R
    img = QImage(w_, h_, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    base = QTransform(s, 0, 0, s, R, R)
    p.setTransform(base)
    if pix is not None:
        recorte = QPainterPath()
        recorte.addPolygon(caja)
        p.setClipPath(recorte)
        p.setTransform(tr * base)
        p.drawPixmap(0, 0, pix)
        p.setClipping(False)
        p.setTransform(base)
    else:
        forma = QPainterPath()
        forma.addPolygon(zona)
        p.fillPath(forma, QColor(255, 255, 255))
    if ow > 0:                       # (con contorno: su marco también da sombra, como al exportar)
        marco = QPainterPath()
        marco.addRect(QRectF(0, 0, bw, bh))
        dentro = QPainterPath()
        dentro.addRect(QRectF(ow, ow, bw - 2 * ow, bh - 2 * ow))
        p.fillPath(marco.subtracted(dentro), QColor(255, 255, 255))
    p.end()
    try:
        import numpy as np
        a = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h_).reshape(h_, -1)[:, :w_ * 4]
        a = a.reshape(h_, w_, 4)[..., 3].astype(np.float32)
        k = int(round(rad * s))
        if k >= 1:
            try:
                import cv2
                a = cv2.blur(a, (2 * k + 1, 2 * k + 1))
            except Exception:  # noqa: BLE001 - sin OpenCV, sin desenfoque (nunca rompe el visor)
                pass
        a *= max(0.0, min(1.0, fuerza))
        c = QColor(color)
        out = np.empty((h_, w_, 4), np.uint8)
        for i, v in enumerate((c.blue(), c.green(), c.red())):     # (premultiplicado: B, G, R, A en memoria)
            out[..., i] = np.clip(a * (v / 255.0) + 0.5, 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(a + 0.5, 0, 255).astype(np.uint8)
        out = np.ascontiguousarray(out)
        return QPixmap.fromImage(QImage(out.data, w_, h_, 4 * w_, QImage.Format_ARGB32_Premultiplied).copy())
    except Exception:  # noqa: BLE001
        return QPixmap.fromImage(img)


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
        self._bg_every = 66          # ms entre fondos (se ajusta solo según lo que tarde: 66–200)
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
        for _i in range(VIDEO_POOL + PROPIO_POOL):      # (0–2: reproductores de Qt · 3–4: motor propio)
            v = QGraphicsVideoItem(self.clip)
            v.setAspectRatioMode(Qt.IgnoreAspectRatio)
            v.hide()
            self.videos.append(v)
        self.active = 0
        self.video = self.videos[0]
        # 🎞 fotograma suelto (FFmpeg) para un archivo que el reproductor no decodifica, mientras llega su copia ligera
        self.poster = QGraphicsPixmapItem(self.clip)
        self.poster.setTransformationMode(Qt.SmoothTransformation)
        self.poster.setZValue(1)
        self.poster.hide()
        self.image = QGraphicsPixmapItem(self.box)
        self.image.setTransformationMode(Qt.SmoothTransformation)
        # ▦ Relleno: la propia imagen ampliada y desenfocada en TODA la pantalla, justo detrás de la caja
        self.fill = QGraphicsPixmapItem()
        self.fill.setTransformationMode(Qt.SmoothTransformation)
        scene.addItem(self.fill)
        self.fill.hide()
        self._fill_p = None
        self._fill_ok = False        # la capa está colocada (con el tamaño de lienzo de AHORA) y a la vista
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

    def set_poster(self, pm: QPixmap | None):
        """🎞 Enseña (o quita, con None) el fotograma suelto encima del video, con su misma geometría."""
        if pm is None or pm.isNull() or self._geom is None or self._geom[0] != "video":
            self.poster.hide()
            return
        v = self.videos[self.active]
        sz = v.size()
        self.poster.setPixmap(pm)
        self.poster.setPos(v.pos())
        self.poster.setTransform(QTransform.fromScale(sz.width() / max(1, pm.width()),
                                                      sz.height() / max(1, pm.height())) * v.transform())
        self.poster.show()

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
        self._bg_every = int(min(200, max(66, self._bg_cost * 3)))

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
        # (capa oculta o apartada: un fotograma que llega tarde, de una precarga o de otro proyecto, no vuelve a
        # enseñar su relleno, que además tendría el tamaño de lienzo de antes: un 16:9 asomando en un Short)
        if not r or not self._fill_ok or src is None or src.isNull():
            self.fill.hide()
            return
        W, H = self._W, self._H
        qw, qh = max(2, int(W / 4)), max(2, int(H / 4))
        s = max(qw / src.width(), qh / src.height()) * r["zoom"]
        big = src.scaled(max(1, int(src.width() * s)), max(1, int(src.height() * s)), Qt.IgnoreAspectRatio,
                         Qt.SmoothTransformation)
        big = big.copy((big.width() - qw) // 2, (big.height() - qh) // 2, qw, qh)
        # El mismo desenfoque que al exportar (core/fill.py: boxblur de radio 1–10, dos pasadas, a 1/4 de tamaño):
        # antes el visor lo enseñaba tres veces menos borroso que el archivo exportado
        rad = max(1, int(round(1 + 9 * r["desenfoque"])))
        rad = min(rad, max(1, min(qw, qh) // 2 - 1))
        sig = (2 * ((2 * rad + 1) ** 2 - 1) / 12) ** 0.5 if r["desenfoque"] > 0.01 else 0.3
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
        # Ampliar para llenar la caja (cover) a 1/8 de tamaño y desenfoque gaussiano (solo vista previa: con 1/8 el
        # desenfoque es 3,5 px a 1/8 = 7 px a 1/4, el mismo aspecto que antes y mucho menos coste)
        k = 8.0
        s = max(bw / src.width(), bh / src.height())
        big = src.scaled(max(1, int(src.width() * s / k)), max(1, int(src.height() * s / k)),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pix = QPixmap.fromImage(_soft_blur(big, 3.5, 0.76))
        self.bg.setPixmap(pix)
        self.bg.setScale(k)
        self.bg.setPos((bw - pix.width() * k) / 2, (bh - pix.height() * k) / 2)

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
        trk = getattr(self, "_trk_regs", None) or []     # 🙈 zonas que siguen a un objeto (se mueven en set_effects)
        if trk:
            rkey = rkey + tuple((r["shape"], r["mode"], r["w"], r["h"], r["amount"]) for r in trk)
            regions = list(regions) + trk
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
        from ..core import decor as _DC
        suave = _DC.suavizar_of(fx)                  # 🌗 suavizar bordes (22/11): el borde se desvanece
        cont_s = None
        if suave > 0:
            cr_ = getattr(self, "content_rect", None)
            cont_s = (QRectF(cr_) if cr_ is not None else self.box.rect()).intersected(self.box.rect())
        extra = {k: float(fx.get(k) or 0) for k in ("rgbsplit", "glow", "punchy", "vhs", "duotone") if float(fx.get(k) or 0) > 0}
        post = [_post_look(pc, pfx, mix) for pc, pfx, mix in (getattr(self, "_post", None) or [])]
        post = [x for x in post if x is not None]
        focus = float(getattr(self, "_focus", 0.0) or 0.0)     # 🔍 entrar enfocando (cambia en cada fotograma)
        notes = getattr(self, "_note_zones", None) or []        # 📝 notas con fondo borroso (se mueven en set_effects)
        key = key + ((tuple(sorted(crop.items())) if crop else None), tuple(sorted(extra.items())),
                     tuple(x[0] for x in post), focus > 0, bool(notes),
                     (round(suave, 4), tuple(round(v, 1) for v in cont_s.getRect())) if suave > 0 else None)
        if key != getattr(self, "_look_key", (False, 0.0, None, "normal", (), (0, 0), None, None, None, None, (), ())):
            self._look_key = key
            bw, blur, _ck, _bl, _rk, _bs, _ch, _mk, _sm, _cr, _ex, _po, focus_on, notes_on, _sv = key
            eff = None
            if ckey is not None or blend != "normal" or regions or chroma or mkey or smask or crop or extra or post \
                    or focus_on or notes_on or suave > 0:
                eff = LookEffect(col, bw, blur, blend, regions, self.box.rect(), chroma, mkey, content, smask)
                eff.crop = crop
                eff.extra = extra
                eff.post = [x[1] for x in post]
                eff.focus = focus
                eff.item = self.box
                eff.note_zones = list(notes)
                eff.suave, eff.cont_s = suave, cont_s
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
        r0 = self.box.rect()                         # 🔍 entrar enfocando: sigma en fracción del ancho de la caja
        self._focus = effects.focus_sigma(fx, t, min(r0.width(), r0.height())) / max(1.0, r0.width())
        from ..core import motion_track as _MT
        self._trk_regs = _MT.regions_at(fx, src_t) if (fx and fx.get("tracked_blur")) else []
        self._set_look(fx)
        eff = self.box.graphicsEffect()
        if self._trk_regs and isinstance(eff, LookEffect):     # 🙈 la zona acompaña al objeto en cada fotograma
            base = [r for r in eff.regions if "mode" not in r]
            nuevas = base + self._trk_regs
            if nuevas != eff.regions:
                eff.regions = nuevas
                eff.update()
        if isinstance(eff, LookEffect) and abs(eff.focus - self._focus) > 1e-9:
            eff.focus = self._focus
            eff.update()
        notes = getattr(self, "_note_zones", None) or []
        if isinstance(eff, LookEffect) and eff.note_zones != notes:     # 📝 el borroso sigue a la nota
            eff.note_zones = list(notes)
            eff.update()
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
        self._shake = QPointF()
        if dx or dy:
            r = self.box.rect()
            self._shake = QPointF(dx * r.width(), dy * r.height())
            self.box.setPos(self.box.pos() + self._shake)
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
        # ⚡ Destello de líneas (las mismas franjas que al exportar). FUERA de la capa: su efecto (color, desenfoque…)
        # no las toca y no tiemblan ni giran con el temblor / giro de cámara (al exportar van encima de todo eso)
        bars = effects.lines_px(fx, t, int(round(self.box.rect().width())))
        if bars and not hasattr(self, "lines"):
            self.lines = _LinesItem()
            self.box.scene().addItem(self.lines)
        if hasattr(self, "lines") and bars != self.lines.bars:
            self.lines.bars = bars
            self.lines.update()
        self._sync_lines()

    def _sync_lines(self):
        """Coloca la capa de líneas donde está el clip, como al exportar: con su giro de capa, su entrada, su opacidad
        y su recorte de bordes, pero SIN voltear (al exportar se voltea la imagen antes de poner las líneas). Va por
        debajo de una zona pre-renderizada (Z 8,99), que ya las trae: no se ven dos veces."""
        it = getattr(self, "lines", None)
        if it is None:
            return
        if not it.bars or not self.box.isVisible():
            it.hide()
            return
        r = self.box.rect()
        if it.rect() != r:
            it.setRect(r)
        it.setPos(self.box.pos() - getattr(self, "_shake", QPointF()))
        if not it.transform().isIdentity():
            it.setTransform(QTransform())
        cr = getattr(self, "_crop", None) or {}
        keep = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                      r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                      r.height() * (1 - cr.get("t", 0) - cr.get("b", 0))) if cr else None
        if keep != it.keep:
            it.keep = keep
            it.update()
        if it.transformOriginPoint() != r.center():
            it.setTransformOriginPoint(r.center())
        it.setRotation(getattr(self, "_rot", 0.0))
        it.setOpacity(self.box.opacity())
        it.setZValue(self.box.zValue() + 0.02)
        it.show()

    def hide(self):
        self._fill_ok = False
        self.box.hide()
        self.fill.hide()
        if getattr(self, "lines", None) is not None:
            self.lines.hide()
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
        self._sync_lines()
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
            # 🌑 (21/11) la sombra es una imagen ya desenfocada con la FORMA de lo que se ve (el alfa de un PNG
            # recortado da su silueta), calculada una vez y guardada: ver _poner_sombra
            self._shadow = QGraphicsPixmapItem()
            self._shadow.setTransformationMode(Qt.SmoothTransformation)
            self._shadow.setAcceptedMouseButtons(Qt.NoButton)
            self._sombra_key = None
            scene.addItem(self._shadow)
            self._outline = QGraphicsRectItem()
            self._outline.setBrush(QBrush(Qt.NoBrush))
            scene.addItem(self._outline)
        z = self.box.zValue()
        _m, ow = decor.margins(fx, W, H)
        frame = content.adjusted(-ow, -ow, ow, ow)
        self._suave_sombra = decor.suavizar_of(fx)
        if sh and self._poner_sombra(sh, short, _m, ow):
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

    def _poner_sombra(self, sh: dict, short: int, m: int, ow: float) -> bool:
        """🌑 Sombra con la FORMA de lo que se ve, como al exportar (core/decor.ffmpeg_frame): el alfa de la imagen (un
        PNG recortado da su silueta; un video o una imagen opaca, su rectángulo), con el recorte de bordes, su color, su
        fuerza y el mismo desenfoque (boxblur de FFmpeg), desplazada por ángulo y distancia. Se calcula una vez y se
        guarda (aquí y en _SOMBRAS): solo se rehace si cambian el tamaño, la forma o sus valores; moverse de sitio
        (una entrada deslizando) no la rehace. False = no hay nada que sombrear."""
        from ..core import decor
        r = self.box.rect()
        cr = getattr(self, "_crop", None) or {}
        keep = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                      r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                      r.height() * (1 - cr.get("t", 0) - cr.get("b", 0))) if cr else r
        caja = self.box.mapToScene(keep)
        es_img = self.image.isVisible() and not self._pix.isNull()
        if es_img:
            cont = self.image.mapToScene(QRectF(self._pix.rect()))
        else:
            v = self.video
            cont = v.mapToScene(v.boundingRect())
            if self._bars is not None:
                cont = cont.intersected(self.clip.mapToScene(self.clip.rect()))
        zona = cont.intersected(caja)
        b0 = zona.boundingRect()
        if zona.isEmpty() or b0.width() < 1 or b0.height() < 1:
            return False
        sv = getattr(self, "_suave_sombra", 0.0)       # 🌗 con bordes suaves: la sombra sigue la forma desvanecida
        if sv > 0 and not (es_img and self._pix.hasAlphaChannel()):       # (por donde la imagen ya es medio
            mm = 0.5 * sv * min(b0.width(), b0.height())                   #  transparente: el borde a la mitad)
            from PySide6.QtGui import QPolygonF
            zona = QPolygonF(b0.adjusted(mm, mm, -mm, -mm))
            b0 = zona.boundingRect()
        b = b0.adjusted(-ow, -ow, ow, ow)
        rad = decor.blur_px(sh, short, b.width(), b.height(), m)
        s = min(1.0, _LADO_SOMBRA / max(b.width(), b.height()))
        R = int(math.ceil(rad * s)) + 2
        rel = QTransform.fromTranslate(-b.left(), -b.top())        # (todo respecto a su esquina: moverse no la rehace)
        alfa = es_img and self._pix.hasAlphaChannel()
        zona_r, caja_r = rel.map(zona), rel.map(caja)
        tr = self.image.sceneTransform() * rel if alfa else None

        def pts(poly):
            return tuple((round(p.x() * 4), round(p.y() * 4)) for p in poly)
        key = (self._image_path if alfa else None, pts(zona_r), pts(caja_r) if alfa else (),
               tuple(round(x, 4) for x in (tr.m11(), tr.m12(), tr.m21(), tr.m22(), tr.dx(), tr.dy())) if alfa else (),
               round(b.width() * 4), round(b.height() * 4), rad, round(s, 4), round(ow, 2), sh["color"],
               round(float(sh["opacity"]), 3))
        if key != self._sombra_key:
            pm = _SOMBRAS.get(key)
            if pm is None:
                pm = _pintar_sombra(b.width(), b.height(), s, R, rad, zona_r, caja_r, tr,
                                    self._pix if alfa else None, ow, sh["color"], float(sh["opacity"]))
                _SOMBRAS[key] = pm
                while len(_SOMBRAS) > 24:
                    _SOMBRAS.pop(next(iter(_SOMBRAS)))
            self._shadow.setPixmap(pm)
            self._sombra_key = key
        if abs(self._shadow.scale() - 1 / s) > 1e-9:
            self._shadow.setScale(1 / s)
        # (el desplazamiento en píxeles enteros, como al exportar)
        self._shadow.setPos(b.left() - R / s + round(sh["dx"] * short), b.top() - R / s + round(sh["dy"] * short))
        return True

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
        self._fill_ok = True
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
            self.poster.hide()
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
        if _w is not None and _w.property("clean_view"):   # segunda pantalla: sin guías ni asas
            return
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

    def set_modes(self, modes):
        """Marca los botones según «modes» sin avisar (al cambiar de pestaña)."""
        modes = set(modes)
        has_aspect = any(m.startswith("a:") for m in modes)
        for k, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(k in modes or (k == "a:" and not has_aspect))
            b.blockSignals(False)

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
        self.hot_mas: list[int] = []      # ⊞ los otros huecos que se llenarán al soltar varios a la vez
        self.ocupado_cb = None            # (idx) -> ¿se ve algo en ese hueco ahora? (lo pone el visor)
        self.cambiando: int | None = None  # ⇄ hueco elegido para cambiarlo por otro (el siguiente clic dice cuál)
        self.setZValue(5100)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setToolTip("Hueco vacío: clic en el «+» = elegir de Medios (Ctrl+clic = varios) · o arrastra desde Medios: "
                        "varios a la vez llenan los huecos en orden · fuera de los huecos = fondo.\n"
                        "Hueco ocupado: clic o doble clic = elegir su clip (Inspector → Transformar) · arrastrar = "
                        "mover lo de dentro · Ctrl+rueda = acercarlo o alejarlo · botones de la esquina: elegir otro "
                        "de Medios, encuadrar (vuelve a llenar el hueco), ⇄ cambiarlo con otro hueco y × vaciarlo.")
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

    def ocupado(self, i: int) -> bool:
        try:
            return bool(self.ocupado_cb and self.ocupado_cb(i))
        except RuntimeError:                      # (el visor se está cerrando)
            return False

    def botones(self, i: int) -> dict:
        """⊞ Los botones de la esquina de un hueco OCUPADO: elegir otro de Medios, ⇄ cambiar con otro hueco y × vaciar
        (en escena; siempre a la vista, del tamaño de un botón en pantalla)."""
        r = self.rect_of(self.slots[i])
        vista = self.scene().views()[0] if self.scene() is not None and self.scene().views() else None
        esc = abs(vista.transform().m11()) if vista is not None else 1.0
        lado = min(30.0 / max(esc, 1e-3), r.width() / 5.5, r.height() / 3)
        sep = lado * 0.2
        out = {}
        x = r.right() - sep - lado
        for nombre in ("vaciar", "cambiar", "encuadrar", "medios"):
            out[nombre] = QRectF(x, r.top() + sep, lado, lado)
            x -= lado + sep
        return out

    def boton_at(self, pt: QPointF):
        """(hueco, «medios» | «encuadrar» | «cambiar» | «vaciar») si el punto está en un botón de la esquina."""
        if not self.isVisible() or self.cambiando is not None:
            return None
        for i in range(len(self.slots)):
            if not self.ocupado(i):
                continue
            for nombre, r in self.botones(i).items():
                if r.contains(pt):
                    return i, nombre
        return None

    def plus_at(self, pt: QPointF) -> int:
        """El hueco VACÍO cuyo «+» (el círculo del centro) está en ese punto; -1 si ninguno. Clic ahí = elegir de
        Medios (en uno ocupado, el botón de su esquina)."""
        if not self.isVisible():
            return -1
        k = max(self.W, self.H) / 1080
        for i, s in enumerate(self.slots):
            if self.ocupado(i):
                continue
            r = self.rect_of(s)
            rad = max(60 * k, 0.22 * min(r.width(), r.height()))
            d = pt - r.center()
            if r.contains(pt) and (d.x() * d.x() + d.y() * d.y()) <= rad * rad:
                return i
        return -1

    def boundingRect(self):
        return QRectF(0, 0, self.W, self.H)

    def paint(self, p: QPainter, _opt, _w=None):
        if _w is not None and _w.property("clean_view"):   # segunda pantalla: sin guías ni asas
            return
        k = max(self.W, self.H) / 1080
        f = QFont("Segoe UI")
        f.setPixelSize(int(46 * k))
        f.setBold(True)
        if self.hot == -1:
            p.fillRect(QRectF(0, 0, self.W, self.H), QColor(242, 160, 61, 40))
        for i, s in enumerate(self.slots):
            r = self.rect_of(s)
            hot = i == self.hot or i in self.hot_mas
            lleno = self.ocupado(i)
            elegible = self.cambiando is not None and i != self.cambiando
            if lleno and not hot:                # (ocupado: se ve lo de dentro; solo un borde fino y su número)
                p.setPen(QPen(QColor(242, 160, 61, 255) if (i == self.cambiando or elegible) else
                              QColor(255, 255, 255, 90), (3 if i == self.cambiando else 1.5) * k,
                              Qt.SolidLine if i == self.cambiando else Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
            else:
                p.fillRect(r, QColor(242, 160, 61, 70) if (hot or elegible) else QColor(255, 255, 255, 18))
                p.setPen(QPen(QColor(242, 160, 61, 255) if (hot or elegible) else QColor(255, 255, 255, 160), 3 * k,
                              Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                if not lleno:
                    p.setFont(f)
                    p.setPen(QColor(255, 255, 255, 220))
                    p.drawText(r, Qt.AlignCenter, "+")
            f2 = QFont(f)
            f2.setPixelSize(int(22 * k))
            p.setFont(f2)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(r.adjusted(10 * k, 6 * k, -6 * k, -6 * k), Qt.AlignLeft | Qt.AlignTop, str(i + 1))
            if lleno and self.cambiando is None:
                self._pintar_botones(p, i)
        if self.slots:
            f3 = QFont(f)
            f3.setPixelSize(int(20 * k))
            f3.setBold(False)
            p.setFont(f3)
            p.setPen(QColor(255, 210, 160, 230))
            p.drawText(QRectF(0, self.H - 34 * k, self.W, 30 * k), Qt.AlignCenter,
                       "⇄ Clic en el hueco con el que cambiarlo (clic fuera = cancelar)"
                       if self.cambiando is not None else
                       "Arrastra aquí desde Medios (varios = uno en cada hueco) · fuera de los huecos = fondo")

    def _pintar_botones(self, p: QPainter, i: int):
        """Iconos monocromos (dibujados) en la esquina de un hueco ocupado: imagen = Medios, encuadrar (marco con sus
        esquinas), ⇄ y ×."""
        for nombre, r in self.botones(i).items():
            p.setPen(QPen(QColor(255, 255, 255, 70), max(1.0, r.width() / 30)))
            p.setBrush(QColor(20, 22, 26, 200))
            p.drawRoundedRect(r, r.width() * 0.18, r.width() * 0.18)
            g = r.adjusted(r.width() * 0.24, r.height() * 0.24, -r.width() * 0.24, -r.height() * 0.24)
            pen = QPen(QColor(235, 235, 240), max(1.2, r.width() / 14))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if nombre == "vaciar":
                p.drawLine(g.topLeft(), g.bottomRight())
                p.drawLine(g.topRight(), g.bottomLeft())
            elif nombre == "encuadrar":                  # (las cuatro esquinas de un encuadre y un punto en medio)
                a = g.width() * 0.32
                for cx, cy, sx, sy in ((g.left(), g.top(), 1, 1), (g.right(), g.top(), -1, 1),
                                       (g.left(), g.bottom(), 1, -1), (g.right(), g.bottom(), -1, -1)):
                    p.drawLine(QPointF(cx, cy), QPointF(cx + sx * a, cy))
                    p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * a))
                p.drawEllipse(g.center(), g.width() * 0.07, g.width() * 0.07)
            elif nombre == "cambiar":
                y1, y2 = g.top() + g.height() * 0.3, g.top() + g.height() * 0.7
                a = g.width() * 0.25
                p.drawLine(QPointF(g.left(), y1), QPointF(g.right(), y1))
                p.drawLine(QPointF(g.right() - a, y1 - a), QPointF(g.right(), y1))
                p.drawLine(QPointF(g.right() - a, y1 + a), QPointF(g.right(), y1))
                p.drawLine(QPointF(g.left(), y2), QPointF(g.right(), y2))
                p.drawLine(QPointF(g.left() + a, y2 - a), QPointF(g.left(), y2))
                p.drawLine(QPointF(g.left() + a, y2 + a), QPointF(g.left(), y2))
            else:                                # (imagen: marco con una montaña y un sol)
                p.drawRoundedRect(g, g.width() * 0.12, g.width() * 0.12)
                p.drawPolyline([QPointF(g.left(), g.bottom() - g.height() * 0.15),
                                QPointF(g.left() + g.width() * 0.4, g.top() + g.height() * 0.45),
                                QPointF(g.left() + g.width() * 0.65, g.top() + g.height() * 0.7),
                                QPointF(g.right(), g.top() + g.height() * 0.4)])
                p.drawEllipse(QPointF(g.left() + g.width() * 0.72, g.top() + g.height() * 0.25),
                              g.width() * 0.08, g.width() * 0.08)


class _MediosHueco(QWidget):
    """⊞ Al hacer clic en el «+» de un hueco de la composición: la lista de Medios (videos e imágenes, con miniatura)
    al lado del visor; un clic en uno = va a ese hueco (desde el cabezal). Se cierra sola (Esc o clic fuera)."""

    def __init__(self, canvas, idx: int, medios: list, parent=None):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout
        super().__init__(parent or canvas, Qt.Popup)
        self.canvas, self.idx = canvas, idx
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        t = QLabel(f"Hueco {idx + 1}: elige qué va aquí")
        t.setStyleSheet("font-weight: bold;")
        v.addWidget(t)
        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("Buscar en Medios…")
        self.filtro.setClearButtonEnabled(True)
        self.filtro.textChanged.connect(self._filtrar)
        v.addWidget(self.filtro)
        self.lista = QListWidget()
        self.lista.setViewMode(QListWidget.IconMode)
        self.lista.setIconSize(QSize(128, 72))
        self.lista.setGridSize(QSize(150, 112))
        self.lista.setResizeMode(QListWidget.Adjust)
        self.lista.setMovement(QListWidget.Static)
        self.lista.setWordWrap(True)
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.setToolTip("Clic = ponerlo en este hueco (desde el cabezal) · Ctrl+clic o Mayús+clic = elegir "
                              "varios y «Poner en los huecos»: uno en cada hueco, en orden, y a la vez")
        self.lista.itemClicked.connect(lambda it: self._clic(it))
        v.addWidget(self.lista, 1)
        from PySide6.QtWidgets import QPushButton
        self.b_varios = QPushButton("Poner en los huecos")
        self.b_varios.setObjectName("primary")
        self.b_varios.setToolTip("Pone los elegidos uno en cada hueco (empezando por este y siguiendo por los "
                                 "vacíos), todos a la vez desde el cabezal")
        self.b_varios.clicked.connect(lambda: self.elegir_varios([it.data(Qt.UserRole)
                                                                 for it in self.lista.selectedItems()]))
        self.b_varios.setVisible(False)
        self.lista.itemSelectionChanged.connect(lambda: self._sel_cambiada())
        v.addWidget(self.b_varios)
        self._items = {}
        for m in medios:
            it = QListWidgetItem(m.name)
            it.setData(Qt.UserRole, m.id)
            it.setToolTip(m.path)
            pm = self._miniatura(m)
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.lista.addItem(it)
            self._items[m.id] = it
        if not medios:
            vacio = QListWidgetItem("Medios está vacío: importa videos o imágenes primero")
            vacio.setFlags(Qt.NoItemFlags)
            self.lista.addItem(vacio)
        self.resize(520, 440)

    @staticmethod
    def _miniatura(m):
        """La miniatura que ya tiene Medios (sin crear ninguna aquí: nada de esperar al abrir)."""
        import os
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QImageReader
        from ..core import media as _MT
        from ..core.model import KIND_IMAGE as _KI
        from ..core.paths import cache_dir as _cd
        ruta = m.path if m.kind == _KI else str(_cd("miniaturas") / f"{_MT.cache_key(m.path)}.jpg")
        if not os.path.isfile(ruta):
            return None
        r = QImageReader(ruta)
        r.setAutoTransform(True)
        tam = r.size()
        if tam.isValid() and tam.width() > 0:
            r.setScaledSize(tam.scaled(QSize(128, 72), Qt.KeepAspectRatio))
        img = r.read()
        return None if img.isNull() else QPixmap.fromImage(img)

    def _filtrar(self, texto: str):
        t = texto.strip().casefold()
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            it.setHidden(bool(t) and t not in it.text().casefold())

    def _clic(self, it):
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return                                # (eligiendo varios: se ponen con el botón)
        self.elegir(it.data(Qt.UserRole))

    def _sel_cambiada(self):
        n = sum(1 for it in self.lista.selectedItems() if it.data(Qt.UserRole))
        self.b_varios.setText(f"Poner {n} en los huecos" if n > 1 else "Poner en los huecos")
        self.b_varios.setVisible(n > 1)

    def elegir(self, media_id):
        if not media_id:
            return
        slots = self.canvas.comp.slots
        box = dict(slots[self.idx]) if 0 <= self.idx < len(slots) else None
        self.close()
        if box is not None:
            self.canvas.comp_drop.emit([media_id], box)

    def elegir_varios(self, ids: list):
        """⊞ Varios de Medios a la vez: uno en cada hueco (este primero, luego los vacíos), todos desde el cabezal."""
        ids = [i for i in ids if i]
        if not ids:
            return
        canvas = self.canvas
        self.close()
        canvas.comp_poner(ids, self.idx)


class _OutsideMask(QGraphicsItem):
    """Fuera del cuadro del proyecto no se ve NADA del video (como al exportar): tapa con el fondo del visor lo que se
    salga del lienzo (▦ relleno, clips más grandes o movidos, sombras, textos…). Va encima de las pistas y debajo de
    las guías y las asas, así el encuadre y sus asas siguen a la vista."""

    E = 1.0e6                                    # (hasta dónde tapa: más que cualquier zoom del visor)

    def __init__(self):
        super().__init__()
        self.W, self.H = 1920, 1080
        self.setZValue(4500)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)

    def set_size(self, W, H):
        if (W, H) == (self.W, self.H):
            return
        self.prepareGeometryChange()
        self.W, self.H = W, H
        self.update()

    def boundingRect(self):
        e = self.E
        return QRectF(-e, -e, self.W + 2 * e, self.H + 2 * e)

    def shape(self):
        from PySide6.QtGui import QPainterPath
        return QPainterPath()                    # (no tapa los clics: solo se pinta)

    def paint(self, p: QPainter, _opt, w=None):
        view = w.parentWidget() if w is not None else None
        brush = view.backgroundBrush() if isinstance(view, QGraphicsView) else QBrush(QColor("#111316"))
        e, W, H = self.E, float(self.W), float(self.H)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(Qt.NoPen)
        for r in (QRectF(-e, -e, W + 2 * e, e), QRectF(-e, H, W + 2 * e, e),     # arriba · abajo
                  QRectF(-e, 0, e, H), QRectF(W, 0, e, H)):                     # izquierda · derecha
            p.fillRect(r, brush)
        p.restore()


class Canvas(QGraphicsView):
    """
    El "lienzo" del video, con el tamaño y formato del proyecto (16:9, vertical...).
    Capas: fondo negro, una capa por pista de video (con su caja y zoom), subtítulos.
    Con un clip seleccionado (como el «Transform» del visor de Resolve): cada capa es independiente.
    Arrastrar = mover la capa · esquinas o Ctrl+rueda = tamaño · Alt+arrastrar / Ctrl+Alt+rueda = mover/acercar la
    imagen DENTRO de su caja (encuadre) · doble clic = volver a pantalla completa.
    Vista: rueda = zoom · Alt+rueda = subir/bajar (con cualquier zoom: view_dy) · rueda pulsada + arrastrar = moverla.
    """
    framing_drag = Signal(float, float)   # desplazamiento en fracciones del lienzo
    transform_live = Signal(str, dict)    # la capa mientras la mueves (clip, caja) — solo para verla
    transform_done = Signal(str, object, object)   # al soltar: (clip, caja original o None, caja nueva o None)
    transform_started = Signal(str)       # al empezar a arrastrar la caja (clip)
    transform_cancel = Signal(str, object)   # al soltar sin haberla movido: (clip, caja original o None) = como antes
    comp_drop = Signal(list, object)      # ⊞ archivos soltados en un hueco (box), en varios (lista) o en el fondo (None)
    comp_accion = Signal(str, object)     # ⊞ en un hueco ocupado: (vaciar | intercambiar | mover_a_hueco | encuadrar |
    #                                       mover | escalar, [clip, …]) → core/composicion.accion
    layer_picked = Signal(str)            # 👆 clic en una capa del visor = seleccionar su clip (como en Resolve)
    pick_clip_cb = None                   # (id de pista) -> id del clip que se ve ahí ahora (lo pone la ventana)
    pick_text_cb = None                   # (x, y en fracciones) -> id del texto que se ve ahí ahora (o None)
    region_changed = Signal(str, list)    # desenfoque por zonas movido/redimensionado (clip, zonas)
    framing_wheel = Signal(float)         # pasos de rueda (+ acercar, - alejar)
    dynzoom_done = Signal(str, dict, dict)   # 🔍 zoom dinámico: (clip, rect inicio, rect final) en fracciones del archivo
    annotation_added = Signal(dict)       # ✏ un trazo nuevo (lo guarda la ventana principal)
    mode_changed = Signal(str)
    view_zoom_changed = Signal(float)     # zoom del VISOR (1 = ajustado a la ventana)
    subtitle_edit = Signal(object, int, object)   # ✏ doble clic en un subtítulo: (índices de sus palabras, la pulsada, rect en el visor)

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
        self.outside = _OutsideMask()         # lo que se sale del lienzo no se ve (como al exportar)
        self.scene().addItem(self.outside)
        self.layers: dict[str, TrackLayer] = {}
        self.subs = SubtitleItem()
        self.scene().addItem(self.subs)
        self.titles = TitlesItem()
        self.scene().addItem(self.titles)
        self.guides = GuidesItem()          # ▦ guías (solo en el visor)
        self.scene().addItem(self.guides)
        self.comp = CompositionItem()       # ⊞ huecos de la composición
        self.scene().addItem(self.comp)
        self.comp.ocupado_cb = self.hueco_ocupado
        self._comp_pan = None               # ⊞ arrastrando lo de dentro de un hueco: {"clip", "from"}
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
        self.snap_guides = _SnapGuides()      # 🧲 imán al mover una capa: centro y bordes del cuadro
        self.scene().addItem(self.snap_guides)
        self._tf_wheel = QTimer(self)          # la rueda: un solo paso de deshacer al parar de girar
        self._tf_wheel.setSingleShot(True)
        self._tf_wheel.setInterval(450)
        self._tf_wheel.timeout.connect(self._tf_commit)
        self.setMouseTracking(True)
        self._sized = False
        self.view_zoom = 1.0                   # 🔍 zoom de la vista (no cambia el video), como en Resolve
        self.view_dy = 0.0                     # ↕ Alt+rueda: cuánto está la vista desplazada en vertical (escena; 0 = centrada)
        self._pan_from = None
        self.set_canvas_size(1920, 1080)

    def layer(self, track_id: str) -> TrackLayer:
        if track_id not in self.layers:
            self.layers[track_id] = TrackLayer(self.scene())
        return self.layers[track_id]

    def remove_layer(self, track_id: str):
        layer = self.layers.pop(track_id, None)
        if layer:
            layer.hide()
            for it in (layer.box, layer.fill, getattr(layer, "_shadow", None), getattr(layer, "_outline", None)):
                if it is not None and it.scene() is self.scene():
                    self.scene().removeItem(it)        # (▦ el relleno y la sombra no son hijos de la caja)

    def set_canvas_size(self, W: int, H: int):
        if self._sized and (W, H) == (self.W, self.H):
            return
        self._sized = True
        self.W, self.H = W, H
        self.frame.setRect(QRectF(0, 0, W, H))
        self.outside.set_size(W, H)
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
        self._colocar_dy()

    # ---- ↕ desplazar la vista arriba / abajo (Alt + rueda, rueda pulsada + arrastrar), con CUALQUIER zoom: también
    # ajustado o alejado, cuando el video entero cabe y las barras de desplazamiento no tendrían recorrido
    def _medio_alto_visible(self) -> float:
        """Media altura de lo que se ve, en unidades de la escena (píxeles del video)."""
        return self.viewport().height() / 2 / max(1e-6, abs(self.transform().m22()))

    def _limites_dy(self) -> tuple[float, float]:
        """Hasta dónde se puede desplazar: siempre queda a la vista al menos un 20 % del video (o de lo que cabe)."""
        vh = self._medio_alto_visible()
        k = 0.2 * min(self.H, 2 * vh)
        return k - vh - self.H / 2, self.H / 2 - k + vh

    def _colocar_dy(self):
        """Pone el centro de la vista a view_dy del centro del video. El recorrido vertical de ESTA vista se amplía
        (setSceneRect de la vista, no de la escena: la 🖥 segunda pantalla y lo demás siguen igual); a lo ancho, como
        siempre (con el video entero a la vista, centrado)."""
        lo, hi = self._limites_dy()
        self.view_dy = min(hi, max(lo, self.view_dy))
        m = 2 * self._medio_alto_visible() + self.H        # (margen de sobra arriba y abajo)
        self.setSceneRect(QRectF(0, -m, self.W, self.H + 2 * m))
        c = self.mapToScene(self.viewport().rect().center())
        self.centerOn(QPointF(c.x(), self.H / 2 + self.view_dy))

    def _recoger_dy(self):
        """Tras mover la vista con las barras (rueda pulsada, zoom alrededor del cursor): su desplazamiento vertical."""
        c = self.mapToScene(self.viewport().rect().center())
        self.view_dy = c.y() - self.H / 2
        lo, hi = self._limites_dy()
        if not lo <= self.view_dy <= hi:
            self._colocar_dy()

    def desplazar_vista(self, pasos: float):
        """↕ Alt + rueda: pasos > 0 = la vista baja (como al desplazar una página: la imagen sube); cada paso, un 10 %
        de lo que se ve."""
        self.view_dy += pasos * 0.2 * self._medio_alto_visible()
        self._colocar_dy()

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
        self._colocar_dy()              # (↕ el desplazamiento vertical que tenía, dentro de sus límites)
        if before is not None:          # el punto bajo el cursor se queda bajo el cursor
            after = self.mapToScene(anchor)
            d = after - before
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x() * self.transform().m11()))
            # (a lo alto, como siempre: solo si el video no cabe entero; si cabe, se queda donde lo dejó Alt+rueda)
            if self.H * abs(self.transform().m22()) > self.viewport().height():
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y() * self.transform().m22()))
                self._recoger_dy()
        self._update_tf_overlay()
        self.view_zoom_changed.emit(new)

    def fit_view(self):
        self.view_zoom = 1.0
        self.view_dy = 0.0              # «Ajustar»: también vuelve a centrarlo a lo alto
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
        from .common import MEDIA_MIME
        i = self.comp.slot_at(self.mapToScene(e.position().toPoint()))
        n = len([x for x in e.mimeData().data(MEDIA_MIME).data().decode().split(",") if x])
        self.comp.hot = i
        self.comp.hot_mas = self._comp_reparto(n, i)[1:] if i >= 0 else []   # (se ven los que se llenarán)
        self.comp.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.comp.hot = None
        self.comp.hot_mas = []
        self.comp.update()

    def _comp_reparto(self, n: int, idx: int) -> list[int]:
        from ..core import composicion
        ocupados = {j for j in range(len(self.comp.slots)) if self.hueco_ocupado(j)}
        return composicion.repartir(n, idx, len(self.comp.slots), ocupados)

    def comp_poner(self, ids: list, idx: int):
        """⊞ Varios a la vez desde el hueco idx: uno en cada hueco (los vacíos que siguen), todos desde el cabezal;
        los que no caben se quedan fuera. idx = -1 → de fondo, como siempre."""
        if idx < 0:
            self.comp_drop.emit(list(ids), None)
            return
        huecos = self._comp_reparto(len(ids), idx)
        self.comp_fuera = max(0, len(ids) - len(huecos))   # (la ventana avisa de cuántos no cupieron)
        ids = list(ids)[:len(huecos)]
        if ids:
            self.comp_drop.emit(ids, [dict(self.comp.slots[j]) for j in huecos])

    def clip_de_hueco(self, idx: int) -> str | None:
        """El clip que se ve ahora en ese hueco (la capa de más arriba con su misma caja), o None."""
        if not (0 <= idx < len(self.comp.slots)) or self.pick_clip_cb is None:
            return None
        r = self.comp.rect_of(self.comp.slots[idx])
        tol = 0.03 * max(self.W, self.H)
        mejor = None
        for tid, layer in getattr(self, "layers", {}).items():
            b = layer.box
            if not b.isVisible():
                continue
            br = QRectF(b.pos(), b.rect().size())
            if abs(br.left() - r.left()) < tol and abs(br.top() - r.top()) < tol and \
                    abs(br.width() - r.width()) < tol and abs(br.height() - r.height()) < tol:
                cid = self.pick_clip_cb(tid)
                if cid and (mejor is None or b.zValue() > mejor[0]):
                    mejor = (b.zValue(), cid)
        return mejor[1] if mejor else None

    def _comp_press(self, e) -> bool:
        """⊞ Clic con la composición puesta: botones de la esquina, ⇄ elegir el otro hueco o arrastrar lo de dentro
        de un hueco ocupado. True = ya está atendido."""
        if e.button() != Qt.LeftButton or self.comp.n <= 0 or not self.comp.isVisible():
            return False
        sp = self.mapToScene(e.position().toPoint())
        if self.comp.cambiando is not None:              # ⇄ el segundo clic dice con qué hueco
            a, self.comp.cambiando = self.comp.cambiando, None
            j = self.comp.slot_at(sp)
            ca = self.clip_de_hueco(a)
            if j >= 0 and j != a and ca:
                cb = self.clip_de_hueco(j)
                if cb:
                    self.comp_accion.emit("intercambiar", [ca, cb])
                else:
                    self.comp_accion.emit("mover_a_hueco", [ca, dict(self.comp.slots[j])])
            self.comp.update()
            return True
        hit = self.comp.boton_at(sp)
        if hit is not None:
            i, nombre = hit
            cid = self.clip_de_hueco(i)
            if nombre == "medios":
                QTimer.singleShot(0, lambda i=i: self.abrir_medios_hueco(i))
            elif nombre == "cambiar":
                self.comp.cambiando = i
                self.comp.update()
            elif nombre == "vaciar" and cid:
                self.comp_accion.emit("vaciar", [cid])
            elif nombre == "encuadrar" and cid:
                self.comp_accion.emit("encuadrar", [cid])
            return True
        if self.mode != "transform" or e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier):
            return False
        i = self.comp.slot_at(sp)
        cid = self.clip_de_hueco(i) if i >= 0 else None
        if not cid:
            return False
        if cid != (self._tf or {}).get("clip"):
            self.layer_picked.emit(cid)                  # (se elige su clip: el Inspector lo enseña)
        self._comp_pan = {"clip": cid, "from": sp, "pulsado": e.position(), "activo": False}
        self.viewport().setCursor(Qt.ClosedHandCursor)
        return True

    def _medios_para_huecos(self) -> list:
        """Los videos e imágenes de Medios (los que se pueden poner en un hueco), como en la biblioteca."""
        from ..core.model import KIND_IMAGE as _KI, KIND_VIDEO as _KV
        ctrl = getattr(self.window(), "ctrl", None) or getattr(self, "ctrl", None)
        if ctrl is None:
            return []
        falta = getattr(ctrl, "missing", set())
        return sorted((m for m in ctrl.project.media.values()
                       if m.kind in (_KV, _KI) and m.id not in falta and not getattr(m, "gen", None)),
                      key=lambda m: m.name.casefold())

    def hueco_ocupado(self, idx: int) -> bool:
        """¿Ya se ve algo en ese hueco ahora (una capa con su misma caja)? Entonces el clic es para esa capa."""
        if not (0 <= idx < len(self.comp.slots)):
            return False
        r = self.comp.rect_of(self.comp.slots[idx])
        tol = 0.03 * max(self.W, self.H)
        for layer in getattr(self, "layers", {}).values():
            b = layer.box
            if not b.isVisible():
                continue
            br = QRectF(b.pos(), b.rect().size())
            if abs(br.left() - r.left()) < tol and abs(br.top() - r.top()) < tol and \
                    abs(br.width() - r.width()) < tol and abs(br.height() - r.height()) < tol:
                return True
        return False

    def abrir_medios_hueco(self, idx: int, gpos=None):
        """⊞ Clic en el «+» del hueco idx: la lista de Medios al lado del visor para elegir qué va en él."""
        if not (0 <= idx < len(self.comp.slots)):
            return None
        pop = _MediosHueco(self, idx, self._medios_para_huecos())
        r = self.mapFromScene(self.comp.rect_of(self.comp.slots[idx])).boundingRect()
        arriba_der = self.viewport().mapToGlobal(r.topRight())
        pantalla = self.screen().availableGeometry() if self.screen() is not None else None
        x, y = arriba_der.x() + 8, arriba_der.y()
        if pantalla is not None:              # (siempre dentro de la pantalla: si no cabe a la derecha, a la izquierda)
            if x + pop.width() > pantalla.right():
                x = max(pantalla.left(), self.viewport().mapToGlobal(r.topLeft()).x() - pop.width() - 8)
            y = max(pantalla.top(), min(y, pantalla.bottom() - pop.height()))
        pop.move(x, y)
        pop.show()
        pop.filtro.setFocus()
        self._pop_hueco = pop
        return pop

    def dropEvent(self, e):
        from .common import MEDIA_MIME
        if not self._comp_ok(e):
            e.ignore()
            return
        ids = [i for i in e.mimeData().data(MEDIA_MIME).data().decode().split(",") if i]
        i = self.comp.slot_at(self.mapToScene(e.position().toPoint()))
        self.comp.hot = None
        self.comp.hot_mas = []
        self.comp.update()
        self.comp_poner(ids, i)                     # (varios a la vez: uno en cada hueco, en orden)
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
        if b.get("_text") and self.mode != "transform":      # (un texto no se recorta)
            return None
        return QRectF(b["x"] * self.W, b["y"] * self.H, b["w"] * self.W, b["h"] * self.H)

    def _update_tf_overlay(self):
        self.tf_overlay.lienzo = QRectF(0, 0, self.W, self.H)
        crop = (self._tf or {}).get("box", {}).get("crop") if self.mode == "crop" else None
        from .diseno import escala
        k = self._k() * escala()                           # (asas del mismo tamaño en pantalla, con «Letra»)
        if self.mode == "crop":
            self.tf_overlay.set_rect(self._tf_rect(), k, crop)
        else:                                              # ⤧ el recuadro, en lo que SE VE (no en la caja entera)
            self.tf_overlay.set_rect(self._tf_vis(), k, None, bool((self._tf or {}).get("box", {}).get("_text")))
        if hasattr(self, "dz_overlay"):
            self._update_dz_overlay()

    def _crop_visible(self) -> QRectF | None:
        """✂ Lo que se queda de la capa elegida (caja menos el recorte) y SE VE: recortado al lienzo. Con una imagen
        más grande que el cuadro (p. ej. en vertical), sus bordes quedan fuera del lienzo y no se podían agarrar:
        las asas van en el borde de lo que se ve."""
        r = self._tf_rect()
        if r is None:
            return None
        cr = dict(self._tf["box"].get("crop") or {})
        inner = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                       r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                       r.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
        vis = inner.intersected(QRectF(0, 0, self.W, self.H))
        return vis if vis.width() > 1 and vis.height() > 1 else inner

    def _crop_hit(self, sp: QPointF) -> str | None:
        """El borde de recorte bajo el ratón ("l", "r", "t", "b"; el más cercano), solo a lo largo de su lado."""
        vis = self._crop_visible()
        if vis is None:
            return None
        hs = self._asa()
        dentro_v = vis.top() - hs <= sp.y() <= vis.bottom() + hs
        dentro_h = vis.left() - hs <= sp.x() <= vis.right() + hs
        cands = []
        if dentro_v:
            cands += [(abs(sp.x() - vis.left()), "l"), (abs(sp.x() - vis.right()), "r")]
        if dentro_h:
            cands += [(abs(sp.y() - vis.top()), "t"), (abs(sp.y() - vis.bottom()), "b")]
        cands = [c for c in cands if c[0] <= hs]
        return min(cands)[1] if cands else None

    def _k(self) -> float:
        """Píxeles del proyecto por píxel de pantalla, con cualquier formato y zoom de la vista. (Antes las asas se
        medían con el ANCHO del visor: en un proyecto vertical, con el cuadro ajustado por el alto, salían 3 veces más
        pequeñas de lo que tocaba y costaba agarrarlas.)"""
        return 1.0 / max(1e-6, self.transform().m11())

    def _asa(self) -> float:
        """Media zona de agarre de un asa (en píxeles del proyecto): 14 px de pantalla × «Letra»."""
        from .diseno import escala
        return 14.0 * escala() * self._k()

    def _tf_crel(self) -> tuple[float, float, float, float]:
        """Dónde está la IMAGEN dentro de la caja de la capa elegida (fracciones): con «encajar» (contain), un video
        horizontal en una caja vertical ocupa solo la franja del medio y las bandas de alrededor no son imagen. Con
        llenar, deformar o el fondo desenfocado / en espejo, la caja entera es lo que se ve."""
        b = (self._tf or {}).get("box") or {}
        if b.get("_text") or b.get("fit", "contain") != "contain" or b.get("_fill"):
            return (0.0, 0.0, 1.0, 1.0)
        d = self._tf_drag
        if d is not None and d.get("crel") is not None:      # (arrastrando: lo medido al empezar, no cambia)
            return d["crel"]
        return self._tf_content_rel()

    def _tf_vis(self) -> QRectF | None:
        """⤧ Lo que SE VE de la capa elegida (en píxeles del proyecto): la imagen sin las bandas de «encajar» y sin
        su recorte. El recuadro y las asas del visor van aquí (como en Resolve), no en la caja entera: antes, en un
        proyecto vertical, el recuadro punteado era todo el cuadro aunque la imagen fuera una franja pequeña."""
        r = self._tf_rect()
        if r is None:
            return None
        if self._tf["box"].get("_text"):
            return r
        cx, cy, cw, ch = self._tf_crel()
        cr = self._tf["box"].get("crop") or {}
        x0, y0 = max(cx, float(cr.get("l", 0))), max(cy, float(cr.get("t", 0)))
        x1, y1 = min(cx + cw, 1 - float(cr.get("r", 0))), min(cy + ch, 1 - float(cr.get("b", 0)))
        if x1 - x0 < 1e-3 or y1 - y0 < 1e-3:
            return r
        return QRectF(r.left() + x0 * r.width(), r.top() + y0 * r.height(), (x1 - x0) * r.width(),
                      (y1 - y0) * r.height())

    def _tf_normalizar(self, b: dict, crel) -> dict:
        """La caja pasa a ser la IMAGEN (sin las bandas de «encajar»): misma forma que la imagen, así que se ve
        exactamente igual; el recorte se recalcula para que lo recortado siga recortado. Desde ahí, escalar por la
        esquina y recortar por un lado actúan sobre lo que ves."""
        if tuple(crel) == (0.0, 0.0, 1.0, 1.0) or b.get("_text") or b.get("fit", "contain") != "contain":
            return dict(b)
        nx, ny = b["x"] + crel[0] * b["w"], b["y"] + crel[1] * b["h"]
        nw, nh = max(1e-4, crel[2] * b["w"]), max(1e-4, crel[3] * b["h"])
        cr = b.get("crop") or {}
        kl, kr = b["x"] + float(cr.get("l", 0)) * b["w"], b["x"] + (1 - float(cr.get("r", 0))) * b["w"]
        kt, kb = b["y"] + float(cr.get("t", 0)) * b["h"], b["y"] + (1 - float(cr.get("b", 0))) * b["h"]
        ncr = {"l": (kl - nx) / nw, "r": (nx + nw - kr) / nw, "t": (kt - ny) / nh, "b": (ny + nh - kb) / nh}
        ncr = {k: round(min(0.98, max(0.0, v)), 4) for k, v in ncr.items()}
        out = dict(b, x=round(nx, 5), y=round(ny, 5), w=round(nw, 5), h=round(nh, 5))
        if any(v > 1e-4 for v in ncr.values()):
            out["crop"] = ncr
        else:
            out.pop("crop", None)
        return out

    def _tf_hit(self, sp: QPointF):
        """Lo que hay bajo el ratón en la capa elegida: ("size", esquina 0–3) = tamaño SIN deformar · ("crop", lado)
        = recortar ese lado (todo el lado se puede agarrar, no solo el centro) · ("move", -1). Un texto: sus asas
        a media arista cambian el ancho («stretch»), como siempre. Alt al pulsar convierte la esquina y el lado en
        deformar (ver mousePressEvent)."""
        r = self._tf_rect()
        if r is None:
            return None
        hs = self._asa()
        if self._tf["box"].get("_text"):     # 📝 un texto pequeño: su interior siempre mueve (las asas, en el borde)
            m = min(hs, 0.25 * min(r.width(), r.height()))
            if r.adjusted(m, m, -m, -m).contains(sp):
                return "move", -1
            for k, c in enumerate((r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())):
                if abs(sp.x() - c.x()) <= hs and abs(sp.y() - c.y()) <= hs:
                    return "size", k
            cx, cy = r.center().x(), r.center().y()
            for edge, (hx, hy) in (("l", (r.left(), cy)), ("r", (r.right(), cy)),
                                   ("t", (cx, r.top())), ("b", (cx, r.bottom()))):
                if abs(sp.x() - hx) <= hs and abs(sp.y() - hy) <= hs:
                    return "stretch", edge
            return ("move", -1) if r.contains(sp) else None
        v = self._tf_vis()
        for k, c in enumerate((v.topLeft(), v.topRight(), v.bottomRight(), v.bottomLeft())):
            if abs(sp.x() - c.x()) <= hs * 1.15 and abs(sp.y() - c.y()) <= hs * 1.15:
                return "size", k
        fuera, dentro = hs, min(hs * 0.7, 0.2 * min(v.width(), v.height()))   # (por dentro, menos: deja mover)
        cands = []
        if v.top() <= sp.y() <= v.bottom():
            cands += [(abs(sp.x() - v.left()), "l", v.left() - fuera <= sp.x() <= v.left() + dentro),
                      (abs(sp.x() - v.right()), "r", v.right() - dentro <= sp.x() <= v.right() + fuera)]
        if v.left() <= sp.x() <= v.right():
            cands += [(abs(sp.y() - v.top()), "t", v.top() - fuera <= sp.y() <= v.top() + dentro),
                      (abs(sp.y() - v.bottom()), "b", v.bottom() - dentro <= sp.y() <= v.bottom() + fuera)]
        cands = [c for c in cands if c[2]]
        if cands:
            return "crop", min(cands)[1]
        if v.contains(sp):
            return "move", -1
        return None

    def _tf_tip(self, hit, alt: bool) -> str:
        """La pista discreta del asa bajo el ratón (tooltip de la capa en el visor)."""
        if not hit:
            return ""
        if hit[0] == "size":
            return ("Esquina: cambiar el tamaño sin deformar" if not alt else "Alt + esquina: tamaño libre (deforma)") \
                + "\nAlt al arrastrar = deformar · Ctrl+rueda = tamaño desde el centro"
        if hit[0] == "crop":
            return ("Lado: recortar este lado (la imagen no se mueve)" if not alt else "Alt + lado: estirar (deforma)") \
                + "\nAlt al arrastrar = estirar · Doble clic = pantalla completa"
        if hit[0] == "stretch":
            return "Lado: más ancho o más estrecho"
        return "Arrastra = mover (Ctrl = sin imán) · Alt+arrastrar = mover la imagen dentro de su caja"

    def _pick_layer(self, sp: QPointF, deeper: bool = False) -> str | None:
        """El clip de la capa que se ve en ese punto (la de más arriba); deeper: la que está debajo de la seleccionada
        (cada Ctrl+clic baja una; al llegar abajo vuelve arriba)."""
        if not deeper and self.pick_text_cb is not None:       # 📝 los textos van encima de todo
            cid = self.pick_text_cb(sp.x() / max(1, self.W), sp.y() / max(1, self.H))
            if cid:
                return cid
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

    def _tf_content_rel(self) -> tuple[float, float, float, float]:
        """🧲 Dónde está lo que SE VE del clip seleccionado dentro de su caja (fracciones 0–1 de la caja): con «encajar»,
        un video horizontal en una caja vertical solo ocupa la franja del medio, y el imán usa esos bordes."""
        cid = (self._tf or {}).get("clip")
        if cid and self.pick_clip_cb is not None:
            for tid, layer in self.layers.items():
                if not layer.box.isVisible() or self.pick_clip_cb(tid) != cid:
                    continue
                r, cr = layer.box.rect(), getattr(layer, "content_rect", None)
                if cr is None or r.width() <= 1 or r.height() <= 1:
                    break
                v = cr.intersected(QRectF(0, 0, r.width(), r.height()))
                if v.width() > 1 and v.height() > 1:
                    return (v.left() / r.width(), v.top() / r.height(), v.width() / r.width(),
                            v.height() / r.height())
                break
        return (0.0, 0.0, 1.0, 1.0)

    def _snap_move(self, box: dict, rel, off: bool = False) -> tuple[dict, list]:
        """🧲 Imán al mover (como en Resolve): el centro de lo que se ve se pega al centro del cuadro, y sus bordes a los
        bordes del cuadro, si quedan a menos de ~8 px de pantalla. Devuelve (caja, líneas guía en px del proyecto)."""
        if off:
            return box, []
        rel = rel or (0.0, 0.0, 1.0, 1.0)
        k = max(1e-6, self.transform().m11())             # px de pantalla por px del proyecto
        out, lines = dict(box), []
        for ax, size, r0, rs, full, kind in (("x", "w", rel[0], rel[2], self.W, "v"),
                                              ("y", "h", rel[1], rel[3], self.H, "h")):
            thr = 8.0 / (k * max(1, full))
            a = out[ax] + r0 * out[size]                  # borde de lo que se ve (izquierda / arriba)
            z = a + rs * out[size]                        # borde contrario
            cands = [(t - v, t) for v, t in (((a + z) / 2, 0.5), (a, 0.0), (z, 1.0))]
            delta, _t = min(cands, key=lambda c: abs(c[0]))
            if abs(delta) > thr:
                continue
            out[ax] += delta
            a, z = a + delta, z + delta
            for v, t in (((a + z) / 2, 0.5), (a, 0.0), (z, 1.0)):
                if abs(v - t) < 1e-6:
                    lines.append((kind, t * full))
        return out, lines

    def _tf_set(self, box: dict):
        """Caja nueva (con límites razonables): se ve al momento; se guarda al soltar."""
        lo = 0.004 if self._tf["box"].get("_text") else 0.05     # (un texto pequeño no salta al empezar a moverlo)
        w = min(4.0, max(lo, box["w"]))
        h = min(4.0, max(lo, box["h"]))
        x = min(0.98, max(-w + 0.02, box["x"]))
        y = min(0.98, max(-h + 0.02, box["y"]))
        if box.get("fit") == "stretch":        # ↔ deformar: la caja pasa a «estirada» (sin reflejo de los Shorts)
            self._tf["box"].pop("flip", None)
            self._tf["box"]["fit"] = "stretch"
        self._tf["box"].update(x=round(x, 4), y=round(y, 4), w=round(w, 4), h=round(h, 4))
        if self._tf["orig"] is None:        # era pantalla completa: sin bandas negras (se ve lo de debajo)
            self._tf["box"]["bg"] = "none"
        self._update_tf_overlay()
        if self._tf_drag is not None:
            self._tf_drag["live"] = True
        self.transform_live.emit(self._tf["clip"], dict(self._tf["box"]))

    def _tf_commit(self):
        if self._tf:
            self.transform_done.emit(self._tf["clip"], self._tf["orig"], dict(self._tf["box"]))
            if self._tf:                 # (la ventana pudo cambiar lo elegido al guardar)
                self._tf["orig"] = dict(self._tf["box"])

    def mouseDoubleClickEvent(self, e):
        sp = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.LeftButton and self.comp.n > 0:   # ⊞ doble clic en el «+» de un hueco vacío
            i = self.comp.plus_at(sp)
            if i >= 0:
                self._plus_press = None
                self.abrir_medios_hueco(i)
                return
            j = self.comp.slot_at(sp)                   # ⊞ en uno ocupado: elegir su clip (como en Miniaturas;
            cid = self.clip_de_hueco(j) if j >= 0 and self.comp.boton_at(sp) is None else None   # sin tocar su encuadre)
            if cid and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
                self._comp_pan = None
                self.layer_picked.emit(cid)
                return
        if e.button() == Qt.LeftButton:       # ✏ sobre el texto de un subtítulo: corregirlo (tiene prioridad)
            hit = self.subs.word_at(sp)
            if hit is not None:
                word, wr = hit
                self.subtitle_edit.emit([w.index for w in self.subs.cue_words()], word.index,
                                        self.mapFromScene(wr).boundingRect())
                return
        if e.button() == Qt.LeftButton and self._tf and self._tf_hit(sp) and self._tf["orig"] is not None:
            self.transform_done.emit(self._tf["clip"], self._tf["orig"], None)    # vuelve a pantalla completa
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:            # rueda pulsada + arrastrar = mover la vista (zoom)
            self._pan_from = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        self._plus_press = None
        if self._comp_press(e):                      # ⊞ botones de un hueco, ⇄ o arrastrar lo de dentro
            return
        if e.button() == Qt.LeftButton and self.comp.n > 0:   # ⊞ «+» de un hueco: se mira al soltar (sin moverse)
            i = self.comp.plus_at(self.mapToScene(e.position().toPoint()))
            if i >= 0:
                self._plus_press = (i, e.position())
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
        if e.button() == Qt.LeftButton and self.mode == "crop" and self._tf and self._tf_rect() is not None:
            sp = self.mapToScene(e.position().toPoint())
            edge = self._crop_hit(sp)
            if edge:
                self._crop_drag = {"edge": edge, "r": self._tf_rect(), "orig": dict(self._tf["box"])}
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
        alt_asa = False                              # Alt sobre un asa = deformar (Alt en el resto = el encuadre)
        if e.button() == Qt.LeftButton and self.mode == "transform" and self._tf and (e.modifiers() & Qt.AltModifier):
            h_ = self._tf_hit(self.mapToScene(e.position().toPoint()))
            alt_asa = bool(h_ and h_[0] in ("size", "crop", "stretch"))
        if e.button() == Qt.LeftButton and self.mode == "transform" and not (e.modifiers() & Qt.AltModifier):
            sp = self.mapToScene(e.position().toPoint())
            deeper = bool(e.modifiers() & Qt.ControlModifier)
            hit = self._tf_hit(sp) if (self._tf and not deeper) else None
            if self._tf and not deeper and not self._tf["box"].get("_text") and (hit is None or hit[0] == "move")                     and self.pick_text_cb is not None:     # 📝 un texto encima de la capa elegida: se elige el texto
                tid = self.pick_text_cb(sp.x() / max(1, self.W), sp.y() / max(1, self.H))
                if tid and tid != self._tf.get("clip"):
                    self.layer_picked.emit(tid)
                    return
            if hit is None:              # 👆 clic en otra capa: se selecciona (Ctrl+clic = la de debajo)
                cid = self._pick_layer(sp, deeper)
                if cid and cid != (self._tf or {}).get("clip"):
                    self.layer_picked.emit(cid)
                    return
        if e.button() == Qt.LeftButton and self._tf and self.mode == "transform" and \
                (alt_asa or not (e.modifiers() & Qt.AltModifier)):
            sp = self.mapToScene(e.position().toPoint())
            hit = self._tf_hit(sp)
            if hit is not None:
                es_texto = bool(self._tf["box"].get("_text"))
                mods = e.modifiers()
                mode = hit[0]
                if mode == "crop" and alt_asa:                 # ↔ ↕ Alt + lado = estirar (deforma)
                    mode = "stretch"
                libre = mode == "size" and bool(mods & (Qt.ShiftModifier | Qt.AltModifier))   # Alt/Mayús + esquina
                crel = self._tf_crel()
                orig_box = dict(self._tf["box"])
                if not es_texto and (mode == "stretch" or libre):
                    box = self._stretch_box()
                elif not es_texto and mode in ("size", "crop"):
                    box = self._tf_normalizar(orig_box, crel)       # (la caja = la imagen: se ve igual)
                    crel = (0.0, 0.0, 1.0, 1.0)
                    self._tf["box"] = dict(box)                     # (soltar sin mover vuelve a la de antes)
                else:
                    box = dict(orig_box)
                self._tf_drag = {"mode": mode, "corner": hit[1], "from": sp, "box": box, "orig_box": orig_box,
                                 "free": libre, "crel": crel,
                                 "rel": self._tf_content_rel() if mode == "move" else None,
                                 "live": False}
                self.transform_started.emit(self._tf["clip"])
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
            self._recoger_dy()                       # (↕ se recuerda al cambiar el tamaño; nunca se pierde el video)
            return
        sp = self.mapToScene(e.position().toPoint())
        if self._comp_pan is not None:               # ⊞ mover lo de dentro del hueco (su encuadre)
            if not self._comp_pan["activo"]:          # (desde 4 px: un clic con temblor no cambia el encuadre)
                m = e.position() - self._comp_pan["pulsado"]
                if abs(m.x()) + abs(m.y()) < 4:
                    return
                self._comp_pan["activo"] = True
            d = sp - self._comp_pan["from"]
            self._comp_pan["from"] = sp
            if d.x() or d.y():
                self.comp_accion.emit("mover", [self._comp_pan["clip"], d.x() / self.W, d.y() / self.H])
            return
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
            for k in ("l", "t", "r", "b"):            # (el lado contrario se queda quieto; queda al menos un 2 %)
                cr[k] = max(0.0, cr.get(k, 0.0))
            contrario = {"l": "r", "r": "l", "t": "b", "b": "t"}[d["edge"]]
            cr[d["edge"]] = min(cr[d["edge"]], 0.98 - cr.get(contrario, 0.0))
            for k in ("l", "t", "r", "b"):
                cr[k] = round(min(0.98, max(0.0, cr.get(k, 0.0))), 4)
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
            lo = 0.004 if b.get("_text") else 0.05          # (📝 un texto puede ser muy pequeño)
            dx, dy = (sp.x() - d["from"].x()) / self.W, (sp.y() - d["from"].y()) / self.H
            if not d.get("started"):         # (un clic con temblor no mueve nada: hace falta arrastrar ~3 px)
                k_ = max(1e-6, self.transform().m11())
                if abs(sp.x() - d["from"].x()) * k_ + abs(sp.y() - d["from"].y()) * k_ < 3:
                    return
                d["started"] = True
            if d["mode"] == "move":          # 🧲 se pega al centro y a los bordes del cuadro (Ctrl: sin imán)
                nb, lines = self._snap_move(dict(b, x=b["x"] + dx, y=b["y"] + dy), d.get("rel"),
                                            bool(e.modifiers() & Qt.ControlModifier))
                self.snap_guides.set_lines(lines, self.W, self.H, self.W / max(1, self.viewport().width()))
                self._tf_set(nb)
            elif d["mode"] == "stretch":     # ↔ ↕ media arista: solo ancho o solo alto (la arista contraria, quieta)
                px, py = sp.x() / self.W, sp.y() / self.H
                e_ = d["corner"]
                if e_ == "l":
                    right = b["x"] + b["w"]
                    w = max(lo, right - px)
                    self._tf_set(dict(b, x=right - w, w=w))
                elif e_ == "r":
                    self._tf_set(dict(b, w=max(lo, px - b["x"])))
                elif e_ == "t":
                    bottom = b["y"] + b["h"]
                    h = max(lo, bottom - py)
                    self._tf_set(dict(b, y=bottom - h, h=h))
                else:
                    self._tf_set(dict(b, h=max(lo, py - b["y"])))
            elif d["mode"] == "crop":        # ✂ lado: recorta ese lado; la imagen se queda donde está (Resolve)
                cr = {k: float((b.get("crop") or {}).get(k, 0.0)) for k in ("l", "t", "r", "b")}
                e_ = d["corner"]
                px, py = sp.x() / self.W, sp.y() / self.H
                if e_ == "l":
                    cr["l"] = (px - b["x"]) / max(1e-6, b["w"])
                elif e_ == "r":
                    cr["r"] = (b["x"] + b["w"] - px) / max(1e-6, b["w"])
                elif e_ == "t":
                    cr["t"] = (py - b["y"]) / max(1e-6, b["h"])
                else:
                    cr["b"] = (b["y"] + b["h"] - py) / max(1e-6, b["h"])
                contrario = {"l": "r", "r": "l", "t": "b", "b": "t"}[e_]
                cr[e_] = min(max(0.0, cr[e_]), 0.98 - cr[contrario])      # (queda al menos un 2 %)
                nb = dict(b, crop={k: round(v, 4) for k, v in cr.items()})
                if not any(v > 1e-4 for v in nb["crop"].values()):
                    nb.pop("crop")
                self._tf["box"].pop("crop", None)
                if nb.get("crop"):
                    self._tf["box"]["crop"] = dict(nb["crop"])
                self._tf_set(nb)
            elif d.get("free"):              # Alt/Mayús + esquina: ancho y alto por separado (deforma)
                k = d["corner"]
                ax = b["x"] + (b["w"] if k in (0, 3) else 0.0)
                ay = b["y"] + (b["h"] if k in (0, 1) else 0.0)
                px, py = sp.x() / self.W, sp.y() / self.H
                w, h = max(lo, abs(px - ax)), max(lo, abs(py - ay))
                self._tf_set(dict(b, x=ax - w if k in (0, 3) else ax, y=ay - h if k in (0, 1) else ay, w=w, h=h))
            else:     # esquina: tamaño SIN deformar; la esquina contraria de lo que SE VE se queda quieta
                k = d["corner"]
                cr = b.get("crop") or {}
                vl, vr = b["x"] + float(cr.get("l", 0)) * b["w"], b["x"] + (1 - float(cr.get("r", 0))) * b["w"]
                vt, vb = b["y"] + float(cr.get("t", 0)) * b["h"], b["y"] + (1 - float(cr.get("b", 0))) * b["h"]
                ax = vr if k in (0, 3) else vl                         # esquina fija (de lo que se ve)
                ay = vb if k in (0, 1) else vt
                px, py = sp.x() / self.W, sp.y() / self.H
                s = max(abs(px - ax) / max(1e-4, vr - vl), abs(py - ay) / max(1e-4, vb - vt))
                s = max((0.012 if b.get("_text") else 0.05) / max(1e-4, min(b["w"], b["h"])), s)
                self._tf_set(dict(b, x=ax + (b["x"] - ax) * s, y=ay + (b["y"] - ay) * s, w=b["w"] * s,
                                  h=b["h"] * s))
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
        elif self._tf and self._drag_from is None and self.mode == "crop":
            edge = self._crop_hit(sp)                 # ✂ sobre un borde de recorte: ↔ / ↕
            self.viewport().setCursor(Qt.SizeHorCursor if edge in ("l", "r") else Qt.SizeVerCursor if edge
                                      else Qt.ArrowCursor)
        elif self._tf and self._drag_from is None:
            hit = self._tf_hit(sp) if self.mode == "transform" else None
            alt = bool(e.modifiers() & Qt.AltModifier)
            lado = hit[1] if hit and hit[0] in ("crop", "stretch") else None
            if lado:          # ✂ recortar = cursor de «partir» (⇹) · ↔ estirar (Alt o un texto) = flechas
                estira = hit[0] == "stretch" or alt
                cur = ((Qt.SizeHorCursor if lado in ("l", "r") else Qt.SizeVerCursor) if estira else
                       (Qt.SplitHCursor if lado in ("l", "r") else Qt.SplitVCursor))
            elif hit and hit[0] == "size":
                cur = Qt.SizeFDiagCursor if hit[1] in (0, 2) else Qt.SizeBDiagCursor
            else:
                cur = Qt.SizeAllCursor if hit else (Qt.OpenHandCursor if self.framing_enabled else Qt.ArrowCursor)
            self.viewport().setCursor(cur)
            self.tf_overlay.set_hover((hit[0], hit[1]) if hit and hit[0] != "move" else None)
            tip = self._tf_tip(hit, alt)
            if self.tf_overlay.toolTip() != tip:
                self.tf_overlay.setToolTip(tip)
        if self._drag_from is not None:
            pos = self.mapToScene(e.position().toPoint())
            d = pos - self._drag_from
            self._drag_from = pos
            self.framing_drag.emit(d.x() / self.W, d.y() / self.H)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._comp_pan is not None and e.button() == Qt.LeftButton:
            self._comp_pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if self.framing_enabled else Qt.ArrowCursor)
            return
        pp, self._plus_press = getattr(self, "_plus_press", None), None
        if pp is not None and e.button() == Qt.LeftButton:
            d = e.position() - pp[1]
            if abs(d.x()) + abs(d.y()) < 4 and not self.hueco_ocupado(pp[0]):
                QTimer.singleShot(0, lambda i=pp[0]: self.abrir_medios_hueco(i))   # (tras soltar: lo demás, igual)
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
            d0, cur, live = self._tf_drag.get("orig_box") or self._tf_drag["box"], self._tf["box"], \
                self._tf_drag.get("live")
            # (un clic con temblor no es un movimiento: nada de pasos de deshacer por menos de 0,0003 del lienzo; la
            #  caja «normalizada» al pulsar una esquina o un lado se ve igual: sin arrastrar, no cuenta)
            moved = bool(self._tf_drag.get("started")) and (
                any(abs(float(d0.get(k, 0)) - float(cur.get(k, 0))) >= 0.0003 for k in ("x", "y", "w", "h"))
                or d0.get("fit") != cur.get("fit") or d0.get("crop") != cur.get("crop"))
            self._tf_drag = None
            self.snap_guides.set_lines([], self.W, self.H, self.snap_guides.k)
            if moved:
                self._tf_commit()
            else:                 # lo de antes, tal cual (lo que se vio al arrastrar era provisional)
                self._tf["box"] = dict(self._tf["orig"]) if self._tf["orig"] else dict(transform.FULL)
                self._update_tf_overlay()
                if live:
                    self.transform_cancel.emit(self._tf["clip"], self._tf["orig"])
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
        if self.comp.n > 0 and self.comp.isVisible() and (mods & Qt.ControlModifier) and \
                not (mods & Qt.AltModifier):                 # ⊞ Ctrl+rueda en un hueco ocupado = acercar lo de dentro
            j = self.comp.slot_at(self.mapToScene(e.position().toPoint()))
            cid = self.clip_de_hueco(j) if j >= 0 else None
            if cid:
                self.comp_accion.emit("escalar", [cid, (e.angleDelta().y() or e.angleDelta().x()) / 120])
                e.accept()
                return
        if not (mods & (Qt.ControlModifier | Qt.AltModifier)):   # rueda = acercar / alejar la VISTA (Resolve)
            steps = (e.angleDelta().y() or e.angleDelta().x()) / 120
            self.zoom_view(1.15 ** steps, e.position().toPoint())
            e.accept()
            return
        delta = e.angleDelta().y() or e.angleDelta().x()     # (en Windows, con Alt la rueda llega en X)
        if not (mods & Qt.ControlModifier):              # ↕ Alt+rueda = desplazar la vista arriba / abajo (cualquier
            if delta:                                    # zoom): rueda hacia abajo = la vista baja, como una página
                self.desplazar_vista(-delta / 120)
            e.accept()
            return
        if self.framing_enabled and (mods & Qt.AltModifier):   # Ctrl+Alt+rueda = acercar la imagen DENTRO de su caja
            self.framing_wheel.emit(delta / 120)
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
        self.setToolTip("Arrastra = mover la capa · esquinas o Ctrl+rueda = tamaño sin deformar · lados = recortar "
                        "ese lado (como en Resolve) · Alt + esquina o lado = deformar · doble clic = pantalla completa."
                        "\nAlt+arrastrar dentro = mover la imagen DENTRO de su caja · Ctrl+Alt+rueda = "
                        "acercarla dentro de su caja."
                        "\nRueda = acercar/alejar la vista · Alt+rueda = subir/bajar la vista · rueda pulsada + "
                        "arrastrar = mover la vista."
                        if on else "Rueda = acercar/alejar la vista · Alt+rueda = subir/bajar la vista · rueda pulsada "
                        "+ arrastrar = moverla · clic en el % = ajustar.")


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
        if _w is not None and _w.property("clean_view"):   # segunda pantalla: sin guías ni asas
            return
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
    """⤧ El contorno de lo que SE VE de la capa seleccionada con sus 4 esquinas (tamaño sin deformar) y un asa en
    cada lado (✂ recortar ese lado; con Alt, estirar). El asa bajo el ratón se resalta (más grande y con el acento) y
    su lado entero se marca. Un texto: asas a media arista para el ancho. En modo «Recortar», las 4 asas van en los
    bordes. Todo con el acento elegido y un halo oscuro (se ve sobre cualquier imagen) y del tamaño de «Letra»."""

    def __init__(self):
        super().__init__()
        self.r: QRectF | None = None
        self.k = 1.0
        self.crop = None
        self.texto = False
        self.hover = None                     # ("size", 0–3) | ("crop" / "stretch", lado) | None
        self.lienzo: QRectF | None = None     # el cuadro del proyecto (las asas de recorte no se salen de él)
        self.setZValue(4900)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_rect(self, r: QRectF | None, k: float, crop=None, texto: bool = False):
        # ⚡ igual que antes: no se repinta (se llama en cada cambio del proyecto y repintar recalcula el video de debajo)
        if (r, k, crop, texto) == (getattr(self, "r", 0), getattr(self, "k", None), getattr(self, "crop", 0),
                                   getattr(self, "texto", None)):
            return
        self.prepareGeometryChange()
        self.r, self.k, self.crop, self.texto = r, k, crop, texto
        self.update()

    def set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.update()

    def boundingRect(self):
        if self.r is None:
            return QRectF()
        m = 16 * self.k
        return self.r.adjusted(-m, -m, m, m)

    def paint(self, painter, _opt, _w=None):
        if _w is not None and _w.property("clean_view"):   # segunda pantalla: sin guías ni asas
            return
        r = self.r
        if r is None:
            return
        if self.crop is not None:          # ✂ Recortar: el rectángulo que se queda y sus 4 asas en los bordes
            cr = self.crop or {}
            inner = QRectF(r.left() + cr.get("l", 0) * r.width(), r.top() + cr.get("t", 0) * r.height(),
                           r.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                           r.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
            lz = getattr(self, "lienzo", None)    # (lo que se sale del lienzo no se ve: las asas, en su borde)
            if lz is not None:
                vis = inner.intersected(lz)
                if vis.width() > 1 and vis.height() > 1:
                    inner = vis
            acento = __import__("editoria.ui.theme", fromlist=["acento"]).acento()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 3.5 * self.k))
            painter.drawRect(inner)
            painter.setPen(QPen(acento, 1.8 * self.k))
            painter.drawRect(inner)
            for c, horiz in ((QPointF(inner.left(), inner.center().y()), False),
                             (QPointF(inner.right(), inner.center().y()), False),
                             (QPointF(inner.center().x(), inner.top()), True),
                             (QPointF(inner.center().x(), inner.bottom()), True)):
                self._pastilla(painter, c, horiz, acento, False)
            return
        acento = __import__("editoria.ui.theme", fromlist=["acento"]).acento()
        hv = self.hover
        k = self.k
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 3.5 * k))
        painter.drawRect(r)
        painter.setPen(QPen(acento, 1.5 * k))
        painter.drawRect(r)
        if hv and hv[0] in ("crop", "stretch"):         # el lado que se va a recortar (o estirar), marcado entero
            lados = {"l": (r.topLeft(), r.bottomLeft()), "r": (r.topRight(), r.bottomRight()),
                     "t": (r.topLeft(), r.topRight()), "b": (r.bottomLeft(), r.bottomRight())}
            a, b = lados[hv[1]]
            painter.setPen(QPen(acento, 4 * k))
            painter.drawLine(a, b)
        cx, cy = r.center().x(), r.center().y()          # ✂ una pastilla en cada lado (recortar; con Alt, estirar)
        for lado, c, horiz in (("l", QPointF(r.left(), cy), False), ("r", QPointF(r.right(), cy), False),
                               ("t", QPointF(cx, r.top()), True), ("b", QPointF(cx, r.bottom()), True)):
            self._pastilla(painter, c, horiz, acento, bool(hv and hv[0] in ("crop", "stretch") and hv[1] == lado))
        for i, c in enumerate((r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())):   # esquinas: tamaño
            activa = bool(hv and hv[0] == "size" and hv[1] == i)
            s = (7.5 if activa else 5.5) * k
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1.2 * k))
            painter.setBrush(acento if activa else QColor("#f4f4f6"))
            painter.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
            if not activa:                               # (borde del acento: se distingue de la imagen)
                painter.setPen(QPen(acento, 1.6 * k))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(QRectF(c.x() - s + 1.2 * k, c.y() - s + 1.2 * k, 2 * s - 2.4 * k, 2 * s - 2.4 * k))
        c = r.center()
        s = 6 * k
        painter.setPen(QPen(QColor(0, 0, 0, 150), 3 * k))
        painter.drawLine(QPointF(c.x() - 2 * s, c.y()), QPointF(c.x() + 2 * s, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - 2 * s), QPointF(c.x(), c.y() + 2 * s))
        painter.setPen(QPen(QColor("#f4f4f6"), 1.2 * k))
        painter.drawLine(QPointF(c.x() - 2 * s, c.y()), QPointF(c.x() + 2 * s, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - 2 * s), QPointF(c.x(), c.y() + 2 * s))

    def _pastilla(self, painter, c: QPointF, horiz: bool, acento, activa: bool):
        """Asa de un lado: una pastilla alargada a lo largo del lado, del acento, con halo oscuro."""
        k = self.k
        largo, ancho = (13.0 if activa else 10.0) * k, (4.0 if activa else 3.0) * k
        ww, hh = (largo, ancho) if horiz else (ancho, largo)
        rr = QRectF(c.x() - ww, c.y() - hh, 2 * ww, 2 * hh)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1.2 * k))
        painter.setBrush(acento if activa or not self.texto else QColor("#f4f4f6"))
        painter.drawRoundedRect(rr, ancho, ancho)


class _SnapGuides(QGraphicsItem):
    """🧲 Líneas guía (como en Resolve) mientras la capa que mueves se pega al centro o a un borde del cuadro."""

    def __init__(self):
        super().__init__()
        self.W, self.H = 1920, 1080
        self.lines: list = []                     # [("v", x) | ("h", y)] en píxeles del proyecto
        self.k = 1.0
        self.setZValue(4960)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_lines(self, lines: list, W: int, H: int, k: float):
        if (lines, W, H, k) == (self.lines, self.W, self.H, self.k):
            return
        self.prepareGeometryChange()
        self.lines, self.W, self.H, self.k = list(lines), W, H, k
        self.update()

    def boundingRect(self):
        m = 4 * self.k
        return QRectF(-m, -m, self.W + 2 * m, self.H + 2 * m)

    def paint(self, painter, _opt, _w=None):
        if not self.lines or (_w is not None and _w.property("clean_view")):
            return
        painter.setPen(QPen(QColor("#ff3b6b"), 1.4 * self.k))
        for kind, v in self.lines:
            if kind == "v":
                painter.drawLine(QPointF(v, 0), QPointF(v, self.H))
            else:
                painter.drawLine(QPointF(0, v), QPointF(self.W, v))


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
        if _w is not None and _w.property("clean_view"):   # segunda pantalla: sin guías ni asas
            return
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


def paint_lines(painter: QPainter, r: QRectF, bars, keep: QRectF | None = None):
    """⚡ Destello de líneas: franjas blancas (effects.lines_px) encima de la imagen, sin suavizar los bordes (como
    las filas de la exportación). keep: lo que queda tras el recorte de bordes de la capa."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    if keep is not None:
        painter.setClipRect(keep)
    for x, w, a in bars:
        painter.fillRect(QRectF(r.left() + x, r.top(), w, r.height()), QColor(255, 255, 255, int(round(255 * a))))
    painter.restore()


class _LinesItem(QGraphicsRectItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars: list = []
        self.keep: QRectF | None = None
        self.setPen(QPen(Qt.NoPen))

    def paint(self, painter, _option, _widget=None):
        paint_lines(painter, self.rect(), self.bars, self.keep)


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
        self.focus = 0.0                             # 🔍 entrar enfocando: sigma en fracción del ancho de la caja
        self.mkey, self.content = mkey, content     # 👤 fondo quieto fuera (y dónde está la imagen en la caja)
        self._plate = None
        self.color, self.bw, self.blur, self.blend = color, bw, blur, blend
        self.chroma = chroma              # 🟩 pantalla verde (misma fórmula que al exportar)
        self.regions = regions or []      # desenfoque por zonas (en fracciones de la caja)
        self.box = box or QRectF(0, 0, 1, 1)
        self.note_zones: list = []        # 📝 fondo borroso alrededor de las notas (en píxeles del LIENZO)
        self.suave, self.cont_s = 0.0, None   # 🌗 suavizar bordes: fracción del lado corto y dónde está la imagen
        self._mascara = None              # (la máscara del desvanecido, hecha una vez: (clave, matriz))
        self.item = None                  # (la caja de la capa: para pasar del lienzo a la pantalla)

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
        if self.focus > 0:               # 🔍 entrar enfocando: el mismo sigma que el gblur de la exportación
            s = self.focus * painter.worldTransform().mapRect(self.box).width()
            if s >= 0.3:
                rgba = px.view(np.uint8).reshape(h, w, 4)
                rgba[...] = effects.blur_bgra(rgba, s)
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
        if self.suave > 0:               # 🌗 el borde de lo que se ve se desvanece (igual que al exportar)
            self._suavizar(px, w, h, painter.worldTransform(), off)
        for adj in self.post:            # 🎨 capas de ajuste de encima: después de todo lo del propio clip
            px = _apply_post(px, w, h, adj, abs(painter.worldTransform().m11()) or 1.0)
        if self.note_zones and self.item is not None:      # 📝 notas con fondo borroso alrededor (lo último)
            self._note_zones(px, w, h, painter.worldTransform(), off)
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

    def _suavizar(self, px, w: int, h: int, tr, off):
        """🌗 Suavizar bordes: el alfa baja en línea recta hasta 0 en el borde de lo que se ve (la imagen dentro de su
        caja menos el recorte), en un ancho = suave × su lado corto. El mismo degradado que la exportación (un
        rectángulo desenfocado con boxblur). La máscara se calcula UNA vez y se guarda: en cada fotograma solo se
        multiplica."""
        import numpy as np
        b = self.box
        cr = self.crop or {}
        keep = QRectF(b.left() + cr.get("l", 0) * b.width(), b.top() + cr.get("t", 0) * b.height(),
                      b.width() * (1 - cr.get("l", 0) - cr.get("r", 0)),
                      b.height() * (1 - cr.get("t", 0) - cr.get("b", 0)))
        if self.cont_s is not None:
            keep = keep.intersected(self.cont_s)
        dev = tr.mapRect(keep).translated(-off.x(), -off.y())
        if dev.width() < 2 or dev.height() < 2:
            return
        F = max(1.0, self.suave * min(dev.width(), dev.height()))
        clave = (w, h, round(dev.left(), 1), round(dev.top(), 1), round(dev.width(), 1), round(dev.height(), 1),
                 round(F, 1))
        if self._mascara is None or self._mascara[0] != clave:
            xs = np.arange(w, dtype=np.float32) + 0.5
            ys = np.arange(h, dtype=np.float32) + 0.5
            ax = np.clip(np.minimum(xs - dev.left(), dev.right() - xs) / F, 0.0, 1.0)
            ay = np.clip(np.minimum(ys - dev.top(), dev.bottom() - ys) / F, 0.0, 1.0)
            self._mascara = (clave, (ay[:, None] * ax[None, :]).astype(np.float32))
        a = px.view(np.uint8).reshape(h, w, 4)
        a[..., 3] = (a[..., 3] * self._mascara[1]).astype(np.uint8)


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
    focus = round(float(fx.get("_focus_px", 0) or 0), 3)    # 🔍 entrar enfocando (sigma en píxeles del proyecto)
    mix = round(max(0.0, min(1.0, float(mix))), 2)
    if (col is None and not bw and blur <= 0 and not extra and focus <= 0) or mix <= 0.01:
        return None
    key = (C.key(col) if col else None, bw, blur, tuple(sorted(extra.items())), mix, focus)
    return key, {"color": col, "bw": bw, "blur": blur, "extra": extra, "mix": mix, "focus": focus}


def _apply_post(px, w, h, adj: dict, scale: float = 1.0):
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
    if adj.get("focus", 0) > 0:      # 🔍 entrar enfocando de la capa de ajuste (el mismo sigma que al exportar)
        rgba = px.view(np.uint8).reshape(h, w, 4)
        rgba[...] = effects.blur_bgra(rgba, adj["focus"] * scale)
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
        if r.get("mode") == "pixel":     # 🙈 pixelar (como el «pixelize» de la exportación: bloques del mismo tamaño)
            from ..core.motion_track import block_px
            bpx = block_px(sw, sh, r["amount"], "pixel")
            small = cv2.resize(sub_, (max(1, -(-sw // bpx)), max(1, -(-sh // bpx))), interpolation=cv2.INTER_AREA)
            blurred = cv2.resize(small, (sw, sh), interpolation=cv2.INTER_NEAREST)
        else:
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


def _note_zones_impl(self, px, w, h, tr, off):
    """📝 Fondo borroso alrededor de una nota: el recuadro (píxeles del lienzo, core/nota_texto.zone_now) se desenfoca
    con el mismo sigma que el gblur de la exportación, se oscurece y se mezcla con la misma máscara (esquinas suaves)."""
    import numpy as np
    from ..core import nota_texto as NT
    inv, ok = self.item.sceneTransform().inverted()
    if not ok:
        return
    m = inv * tr                                      # lienzo (escena) → pantalla
    k = (abs(m.m11()) + abs(m.m22())) / 2 or 1.0
    rgba = px.view(np.uint8).reshape(h, w, 4)
    for z in self.note_zones:
        dev = m.mapRect(QRectF(z["x0"], z["y0"], z["x1"] - z["x0"], z["y1"] - z["y0"])).translated(-off.x(), -off.y())
        X0, Y0 = int(round(dev.left())), int(round(dev.top()))
        X1, Y1 = int(round(dev.right())), int(round(dev.bottom()))
        if X1 - X0 < 2 or Y1 - Y0 < 2 or z["alpha"] <= 0.002:
            continue
        cx0, cy0, cx1, cy1 = max(0, X0), max(0, Y0), min(w, X1), min(h, Y1)
        if cx1 - cx0 < 2 or cy1 - cy0 < 2:
            continue
        sub = rgba[cy0:cy1, cx0:cx1]
        blurred = effects.blur_bgra(sub, z["sigma"] * k).astype(np.float32)
        if z["dark"] > 0.001:
            blurred[..., :3] *= (1.0 - z["dark"])
        a = NT.mask(X1 - X0, Y1 - Y0, z["r"] * k, z["f"] * k)[cy0 - Y0:cy1 - Y0, cx0 - X0:cx1 - X0]
        a = (a * z["alpha"])[..., None]
        sub[...] = np.clip(blurred * a + sub.astype(np.float32) * (1 - a) + 0.5, 0, 255).astype(np.uint8)


LookEffect._note_zones = _note_zones_impl


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
        self.setFocusPolicy(Qt.ClickFocus)        # (fuera de la cadena de Tab: S, Supr, Ctrl+Z… van al editor)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._shown = ""
        self._editando = False                    # (escribiendo: volver con Alt+Tab no lo cierra)
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

    AYUDA = ("Nombre del video / proyecto: clic para cambiarlo (Intro = listo, Esc = dejarlo).\n"
             "Se usa al guardar y como nombre del archivo al exportar. Ctrl+Z lo deshace.")

    def _zona_texto(self):
        from PySide6.QtWidgets import QStyle, QStyleOptionFrame
        op = QStyleOptionFrame()
        self.initStyleOption(op)
        r = self.style().subElementRect(QStyle.SE_LineEditContents, op, self)
        m = self.textMargins()
        return r.adjusted(m.left() + 2, m.top(), -m.right() - 2, -m.bottom())

    def acortado(self) -> bool:
        """¿El nombre no cabe entero? (entonces se ve con «…» y entero en el tooltip; al escribir, entero)."""
        return not self.hasFocus() and bool(self.text()) and \
            self.fontMetrics().horizontalAdvance(self.text()) > self._zona_texto().width()

    def show_name(self, text: str):
        self._shown = text
        self.setToolTip(f"{text}\n\n{self.AYUDA}" if text else self.AYUDA)   # (el nombre entero, siempre aquí)
        if not self.hasFocus():
            self.setText(text)
            self.setCursorPosition(0)

    def paintEvent(self, e):
        """Sin el foco y sin sitio: el nombre acortado con «…» (nunca cortado a media letra)."""
        if not self.acortado():
            return super().paintEvent(e)
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QStyle, QStyleOptionFrame
        p = QPainter(self)
        op = QStyleOptionFrame()
        self.initStyleOption(op)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit, op, p, self)
        r = self._zona_texto()
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, self.fontMetrics().elidedText(self.text(), Qt.ElideRight,
                                                                                     r.width()))
        p.end()

    def focusInEvent(self, e):
        if e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason) or \
                (e.reason() == Qt.ActiveWindowFocusReason and not self._editando):
            self.clearFocus()                     # (solo se escribe aquí si haces clic; si no, las teclas son del editor)
            return
        self._editando = True
        super().focusInEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.setText(self._shown)
            self.clearFocus()
            return
        super().keyPressEvent(e)
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.clearFocus()

    def focusOutEvent(self, e):
        if e.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            self._editando = False
        super().focusOutEvent(e)

    def editar(self):
        """✏ Cambiar el nombre con el teclado (F2): el cuadro queda listo para escribir, con todo elegido."""
        self._editando = True
        self.setFocus(Qt.OtherFocusReason)
        self.selectAll()

    def _done(self):
        from PySide6.QtWidgets import QApplication as _QA
        if self.hasFocus() and self._editando and _QA.activeWindow() is None:
            return                                # (se fue a otra ventana con Alt+Tab: sigue escribiendo al volver)
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
    motor_mixto_cambiado = Signal()      # ⚡ se cambió un interruptor del motor propio (menú del modo del visor)

    def set_composition(self, n: int):
        cv = self.canvas
        viejo = cv.comp.n or getattr(self, "_comp_ultimo", 0)   # (también tras pasar por «Sin composición»)
        antes = [dict(s) for s in cv.comp.slots] if cv.comp.n else []
        if not antes and viejo:
            from ..core import transform as _TR
            antes = _TR.comp_slots(viejo, cv.comp.W, cv.comp.H)
        cv.comp.cambiando = None
        cv.comp.set_count(n)
        if n and antes and viejo != n:                     # ⊞ lo de cada hueco viejo (a cualquier hora) pasa al hueco
            nuevos = cv.comp.slots                         # nuevo con su número; lo que no cabe, se avisa
            pares = [[dict(a), dict(nuevos[i]) if i < len(nuevos) else None] for i, a in enumerate(antes)]
            cv.comp_accion.emit("recolocar_huecos", pares)
        if n:
            self._comp_ultimo = n
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

    # ▦ Cada pestaña (YouTube / Edits / Shorts) recuerda SUS guías. Si nunca las cambiaste ahí: YouTube sin relación
    # de aspecto (16:9, «Predet.») y Edits / Shorts con la de 9:16 (el usuario: «por defecto las guías en Edits y
    # Shorts deberían ir en 9:16»). YouTube sigue usando la clave de siempre (visor/guias).
    GUIDES_DEFAULT = {"youtube": [], "edit": [f"a:{9 / 16:.4f}"], "short": [f"a:{9 / 16:.4f}"]}

    @staticmethod
    def guides_key(space: str) -> str:
        return "visor/guias" if space in ("", "youtube") else f"visor/guias_{space}"

    @classmethod
    def guides_for(cls, space: str) -> list[str]:
        s = QSettings("EditorIA", "EditorIA")
        key = cls.guides_key(space)
        if not s.contains(key):
            return list(cls.GUIDES_DEFAULT.get(space, []))
        return [m for m in str(s.value(key, "") or "").split(",") if m]

    def set_guides_space(self, space: str):
        """Al entrar en una pestaña: sus guías (las que elegiste allí, o las de por defecto)."""
        self._guides_space = str(space or "youtube")
        modes = self.guides_for(self._guides_space)
        self.canvas.guides.set_modes(modes)
        self.guides_panel.set_modes(modes)

    def _guides_set(self, modes):
        self.canvas.guides.set_modes(modes)
        QSettings("EditorIA", "EditorIA").setValue(self.guides_key(getattr(self, "_guides_space", "youtube")),
                                                   ",".join(modes))

    # ---------------------------------------------------------------- ↔ cabecera que cabe siempre
    @staticmethod
    def _texto_corto(texto: str) -> str:
        """«✂ Eliminar silencio» → «✂»; sin icono delante, se queda igual."""
        t = (texto or "").strip()
        if not t:
            return t
        primero = t.split(" ", 1)[0]
        return primero if (len(t) > len(primero) and not primero[:1].isalnum()) else t

    def _botones_cabecera(self):
        from PySide6.QtWidgets import QAbstractButton
        out = []
        for b in self.header.findChildren(QAbstractButton):
            if b is self.title_label or not b.isVisibleTo(self.header):
                continue
            if b.property("texto_completo") is None or (b.text() not in (b.property("texto_completo"),
                                                                         self._texto_corto(b.property("texto_completo")))):
                b.setProperty("texto_completo", b.text())     # (texto nuevo puesto por el programa: ese manda)
            if b.property("tip_puesto") is None or b.toolTip() != b.property("tip_puesto"):
                b.setProperty("tip_completo", b.toolTip())   # (el tooltip lo cambió el programa, no este ajuste)
            if b.text() == b.property("texto_completo"):     # (con el nombre: su ancho real, flecha de menú incluida)
                b.setProperty("ancho_completo", b.sizeHint().width())
            corto = self._texto_corto(b.property("texto_completo"))
            fm = b.fontMetrics()
            b.setMinimumWidth(min(fm.horizontalAdvance(corto) + 22, fm.horizontalAdvance(b.property("texto_completo")) + 22))
            out.append(b)
        return out

    @staticmethod
    def _ancho_con_nombre(w) -> int:
        """Lo que mide w con su nombre entero (los botones, aunque ahora estén solo con su icono)."""
        t = w.property("texto_completo")
        if t is None:
            return w.sizeHint().width()
        return max(int(w.property("ancho_completo") or 0), w.fontMetrics().horizontalAdvance(t) + 24)

    def poner_alto_cabecera(self, px: int):
        """El alto de UNA fila de la cabecera (Ventana → Tamaño de letra); con la segunda fila, el doble."""
        self._alto_fila_cab = int(px)
        self.header.setFixedHeight(self._alto_fila_cab * (2 if getattr(self, "_segunda_fila", False) else 1))
        self._calidad_entera()                           # (con otra letra, otro ancho)

    def _calidad_entera(self):
        """↔ El desplegable «Calidad» nunca se estrecha por debajo de su opción más larga: se ve entera («Completa»,
        «Un cuarto»), nunca cortada. (Antes podía bajar a 64 px y enseñaba «Compl».)"""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
        q = getattr(self, "quality", None)
        if q is None or not q.count():
            return
        q.ensurePolished()
        fm = q.fontMetrics()
        texto = max((q.itemText(i) for i in range(q.count())), key=fm.horizontalAdvance)
        op = QStyleOptionComboBox()
        q.initStyleOption(op)
        op.currentText = texto
        w = q.style().sizeFromContents(QStyle.CT_ComboBox, op, QSize(fm.horizontalAdvance(texto), fm.height()), q)
        q.setMinimumWidth(max(64, w.width()))

    def _poner_segunda_fila(self, on: bool):
        """La barra de Vertical / Edits, a su propia fila debajo (cuando ni con solo iconos cabe al lado del resto)."""
        barra = self.shorts_bar
        if on:
            self._hl_cab.removeWidget(barra)
            self._hl_cab2.insertWidget(0, barra)
        else:
            self._hl_cab2.removeWidget(barra)
            self._hl_cab.insertWidget(self._pos_barra_cab, barra)
        self._segunda_fila = on
        self.poner_alto_cabecera(getattr(self, "_alto_fila_cab", 30))

    def _ajustar_cabecera(self, ancho: int | None = None):
        """Pone los botones con nombre o solo con icono según quepan (sin bailar: decide con los anchos completos).
        En Vertical y Edits, si ni con solo iconos cabe su barra al lado del resto, la barra baja a una segunda fila:
        todo a la vista y nada cortado, y el visor nunca obliga a una ventana más ancha que la pantalla."""
        h = getattr(self, "header", None)
        if h is None:
            return
        from .responsive import piezas, widgets_en       # (sin itemAt: ver «lo que hay en un layout» en responsive.py)
        botones = self._botones_cabecera()
        hl, barra = self._hl_cab, self.shorts_bar
        en_hl = piezas(hl)
        fijo = hl.sizeHint().width() - sum(p.sizeHint().width() for p in en_hl)   # (márgenes, separaciones y huecos)
        fila1 = [p.obj for p in en_hl if p.obj is not barra and not p.es_lay]
        largo1 = fijo + sum(self._ancho_con_nombre(w) for w in fila1)
        if not self.lbl_calidad.isVisibleTo(h):
            largo1 += self.lbl_calidad.sizeHint().width() + max(0, hl.spacing())
        en_barra = [w for w in widgets_en(self.shorts_lay) if w.isVisibleTo(barra)] if barra.isVisibleTo(h) else []
        mb = self.shorts_lay.contentsMargins()
        fijo_b = (mb.left() + mb.right() + self.shorts_lay.spacing() * max(0, len(en_barra) - 1) +
                  max(0, hl.spacing())) if en_barra else 0
        largo_b = fijo_b + sum(self._ancho_con_nombre(w) for w in en_barra)
        disponible = h.width() if ancho is None else ancho
        compacta = disponible < largo1 + largo_b + (24 if self._compacta else 0)   # (margen: no alterna en la frontera)
        c1 = c2 = compacta
        segunda = False
        if compacta and en_barra:
            for b in botones:                            # (con solo iconos: lo que mide de verdad cada uno)
                self._poner_texto_cab(b, True)
            self.lbl_calidad.setVisible(False)
            corto = fijo + sum(w.sizeHint().width() for w in fila1 if w.isVisibleTo(h)) + \
                fijo_b + sum(w.sizeHint().width() for w in en_barra)
            segunda = disponible < corto + (24 if self._segunda_fila else 0)
            if segunda:                                  # (cada fila por su cuenta: con nombres si le caben)
                c1 = disponible < largo1 + (24 if self._compacta else 0)
                c2 = disponible < largo_b - max(0, hl.spacing()) + 20 + \
                    (24 if getattr(self, "_compacta_barra", False) else 0)
        if segunda != self._segunda_fila:
            self._poner_segunda_fila(segunda)
        if (c1, c2) == (self._compacta, getattr(self, "_compacta_barra", None)) and not botones:
            return
        self._compacta, self._compacta_barra = c1, c2
        for b in botones:
            self._poner_texto_cab(b, c2 if b.parentWidget() is barra else c1)
        self.lbl_calidad.setVisible(not c1)
        self._poner_total()                              # (⏱ la duración siempre a la vista; si no cabe, más corta)

    def _poner_texto_cab(self, b, corto: bool):
        """Un botón de la cabecera con su nombre o solo con su icono (entonces, el nombre en el tooltip)."""
        largo, tip = b.property("texto_completo"), b.property("tip_completo") or ""
        if corto:
            b.setText(self._texto_corto(largo))
            b.setToolTip(largo + ("\n" + tip if tip and tip != largo else ""))
        else:
            b.setText(largo)
            b.setToolTip(tip)
        b.setProperty("tip_puesto", b.toolTip())

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "transport", None) and ev.type() in (QEvent.Resize, QEvent.Show):
            self._ajustar_rapidos(ev.size().width() if ev.type() == QEvent.Resize else None)
            return super().eventFilter(obj, ev)
        if obj is getattr(self, "header", None) and ev.type() == QEvent.LayoutRequest:
            t = getattr(self, "_t_cabecera", None)       # (el tiempo cambia cada fotograma: agrupar, no recalcular cada vez)
            if t is None:
                from PySide6.QtCore import QTimer
                t = self._t_cabecera = QTimer(self)
                t.setSingleShot(True)
                t.setInterval(120)
                t.timeout.connect(self._ajustar_cabecera)
            if not t.isActive():
                t.start()
        elif obj is getattr(self, "header", None) and ev.type() in (QEvent.Resize, QEvent.Show):
            if not getattr(self, "_ajustando_cab", False):
                self._ajustando_cab = True
                try:
                    self._ajustar_cabecera()
                finally:
                    self._ajustando_cab = False
        return super().eventFilter(obj, ev)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = Canvas()
        self.fps = 30.0

        header = QWidget()
        header.setObjectName("panelheader")
        header.setFixedHeight(30)
        self.header = header
        self._alto_fila_cab = 30
        self._segunda_fila = False
        # (dos filas: la de siempre y, debajo, la de la barra de Vertical / Edits cuando no cabe al lado del resto)
        filas_cab = QVBoxLayout(header)
        filas_cab.setContentsMargins(0, 0, 0, 0)
        filas_cab.setSpacing(0)
        hl = self._hl_cab = QHBoxLayout()
        hl.setContentsMargins(10, 0, 10, 0)
        filas_cab.addLayout(hl)
        self._hl_cab2 = QHBoxLayout()
        self._hl_cab2.setContentsMargins(10, 0, 10, 0)
        self._hl_cab2.addStretch()
        filas_cab.addLayout(self._hl_cab2)
        self.title_label = _TitleEdit()
        self.title_label.show_name("Proyecto sin título")
        self.zoom_label = QPushButton("Ajustar")
        self.zoom_label.setObjectName("flat")
        self.zoom_label.setFocusPolicy(Qt.NoFocus)
        self.zoom_label.setToolTip("Zoom de la vista del visor (rueda del ratón) · Alt+rueda = subir/bajar la vista.\n"
                                   "Clic = ajustar a la ventana (y volver a centrarla).")
        self.zoom_label.clicked.connect(self.canvas.fit_view)
        self.canvas.view_zoom_changed.connect(
            lambda z: self.zoom_label.setText("Ajustar" if z == 1.0 else f"🔍 {z * 100:.0f} %"))
        self.time_label = QLabel("00:00:00:00")
        self.time_label.setObjectName("timecode")
        self.time_label.setToolTip("Tiempo del cabezal (horas:minutos:segundos:fotograma)")
        self.time_label.setMinimumWidth(self.time_label.sizeHint().width() + 4)   # (ancho fijo: no recoloca cada fotograma)
        hl.addWidget(self.title_label)
        hl.addSpacing(14)
        # Acciones rápidas: abajo, en la barra del transporte (más cerca de la línea de tiempo; ver más abajo). Iconos
        # monocromos con su nombre corto; la explicación, en el tooltip. Con el visor estrecho, solo el icono.
        self.quick: dict[str, QPushButton] = {}
        for key, text, tip, ic in (
                ("silence", "Silencios", "✂ Eliminar silencio (Ctrl+Mayús+Supr): quita los silencios de los clips "
                 "seleccionados (o de la narración), como en DaVinci Resolve", "scissors"),
                ("gaps", "Huecos", "⇤ Huecos: quitar los espacios vacíos entre clips", "arrow-left-to-line")):
            b = QPushButton(text)
            b.setObjectName("flat")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("nombre_corto", text)
            b.setProperty("tip_rapido", tip)
            try:
                from .diseno import icono
                b.setIcon(icono(ic))
            except Exception:  # noqa: BLE001 - sin el icono, con su nombre
                pass
            self.quick[key] = b
        hl.addStretch()
        # 📱 Barra de los Shorts (la llena la ventana; solo se ve en la pestaña Shorts)
        self.shorts_bar = QWidget()
        self.shorts_lay = QHBoxLayout(self.shorts_bar)
        self.shorts_lay.setContentsMargins(0, 0, 8, 0)
        self.shorts_lay.setSpacing(4)
        self.shorts_bar.setVisible(False)
        # (no obliga a una cabecera más ancha: si no cabe ni con solo iconos, pasa a la segunda fila)
        self.shorts_bar.setMinimumWidth(1)
        hl.addWidget(self.shorts_bar)
        self._pos_barra_cab = hl.indexOf(self.shorts_bar)
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
        # ⚡ interruptores del motor propio (visor mixto): visibles aquí, en el menú del visor
        mm.addSeparator()
        self.act_motor_pesados = mm.addAction("⚡ Motor propio para lo pesado (4K, AV1)")
        self.act_motor_pesados.setToolTip("Más de 1440p y AV1 se reproducen con el motor propio: al tamaño del visor y con "
                                          "la tarjeta gráfica (menos CPU y memoria). Apagado: los reproductores de siempre.")
        self.act_motor_pausa = mm.addAction("⚡ Motor propio en pausa (saltos más rápidos)")
        self.act_motor_pausa.setToolTip("En pausa (saltos, arrastrar el cabezal, paso a paso) el fotograma exacto lo da el "
                                        "motor propio, que llega antes. Al reproducir, lo normal sigue con su reproductor.")
        mm.setToolTipsVisible(True)
        for a, clave in ((self.act_motor_pesados, "video/motor_propio_pesados"),
                         (self.act_motor_pausa, "video/pausa_motor_propio")):
            a.setCheckable(True)
            a.setChecked(_ajuste_si(clave))
            a.toggled.connect(lambda on, k=clave: (QSettings("EditorIA", "EditorIA").setValue(k, "true" if on else
                                                                                              "false"),
                                                   self.motor_mixto_cambiado.emit()))
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
        self.lbl_calidad = QLabel("Calidad")
        hl.addWidget(self.lbl_calidad)
        hl.addWidget(self.quality)
        hl.addSpacing(12)
        hl.addWidget(self.zoom_label)
        hl.addSpacing(18)
        hl.addWidget(self.time_label)
        self.total_label = QLabel("/ 00:00:00:00")      # ⏱ la duración total del video, al lado del tiempo
        self.total_label.setObjectName("dim")
        self.total_label.setToolTip("Duración total del video")
        hl.addSpacing(6)
        hl.addWidget(self.total_label)
        # ↔ si la cabecera no cabe (visor estrecho, paneles a los lados, barra de Vertical): los botones se quedan con
        # su icono (el nombre, en el tooltip) y se esconde lo prescindible. Así el visor nunca obliga a una ventana
        # más ancha que la pantalla (antes pedía ~930 px y Qt cortaba la derecha de Reclaimer).
        self._calidad_entera()                           # (su valor siempre entero: «Completa», nunca «Compl»)
        self._compacta = None
        self._compacta_barra = None
        header.installEventFilter(self)

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
        # ⏪ −5 s / +5 s, ⏩ velocidad, 🔊 volumen de escucha y 📊 LUFS (ui/transport_extra.py; los conecta PlaybackEngine)
        from .transport_extra import LoudnessButton, SpeedButton, VolumeButton, escucha
        self.btn_back5 = btn("−5s", "Retroceder 5 segundos (Mayús+←), reproduciendo o en pausa")
        self.btn_fwd5 = btn("+5s", "Avanzar 5 segundos (Mayús+→), reproduciendo o en pausa")
        for b in (self.btn_back5, self.btn_fwd5):
            b.setStyleSheet("QPushButton { font-size: 10pt; padding: 2px 4px; }")   # (compactos: la barra cabe)
        self.btn_speed = SpeedButton("J / K / L también: J = hacia atrás, K = parar, L = adelante (otra vez = más "
                                     "rápido). A 2×, 4× y 8× el sonido va como con L.")
        self._vel_elegida = 1.0
        self.btn_vol = VolumeButton(escucha())
        self.btn_lufs = LoudnessButton()
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("timecode")
        self.rate_label.setToolTip("Velocidad de reproducción: J = hacia atrás, K = parar, L = hacia delante "
                                   "(pulsa otra vez para ir más rápido)")
        self.duration_label = QLabel("00:00:00:00")
        self.duration_label.setObjectName("dim")
        self.duration_label.setToolTip("Duración total")

        controls = QHBoxLayout()
        controls.setContentsMargins(10, 2, 10, 4)
        # (lo de la izquierda en su propio contenedor: si la fila no cabe entera, baja a una segunda fila y el
        #  transporte se queda con todo el ancho; nada del transporte se esconde por culpa de estos botones)
        self.transport_izq = QWidget()
        izq = QHBoxLayout(self.transport_izq)
        izq.setContentsMargins(0, 0, 0, 0)
        izq.addWidget(self.btn_mode)               # (como Resolve: el modo del visor, abajo a la izquierda)
        izq.addSpacing(6)
        izq.addWidget(self.duration_label)
        izq.addSpacing(10)
        for b in self.quick.values():              # ✂ Silencios · ⇤ Huecos (antes, en la cabecera de arriba)
            izq.addWidget(b)
        controls.addWidget(self.transport_izq)
        controls.addStretch()
        # ⏮ ◀ −5s ▶ +5s ▶| ⏭ 🔁 · 1× (◀◀ J) · nivel · 🔊 · LUFS, en una fila que nunca obliga a ensanchar la ventana:
        # si ni así cabe (antes, lo de la izquierda baja a otra fila: _ajustar_rapidos), se esconden por orden el
        # nivel, −5s/+5s y 🔊 (siguen en el menú Reproducción). La velocidad «1×», nunca.
        from .transport_extra import FlexRow
        self.meter = LevelMeter()
        fila = self.transport_row = FlexRow()
        for b in (self.btn_start, self.btn_back):
            fila.add(b)
        fila.add(self.btn_back5, 3)
        fila.add(self.btn_play)
        fila.add(self.btn_fwd5, 3)
        for b in (self.btn_fwd, self.btn_end, self.btn_loop):
            fila.add(b)
        fila.add_spacing(6)
        fila.add(self.btn_speed)                   # (imprescindible: la velocidad nunca se esconde)
        fila.add(self.rate_label)
        self.rate_label.setVisible(False)          # (solo hacia atrás, con J: hacia delante lo dice el botón 1×)
        fila.add_spacing(6)
        fila.add(self.meter, 1)
        fila.add(self.btn_vol, 5)
        # (agrupación 20/11: el transporte solo deja lo de ESCUCHAR; la sonoridad —medir LUFS— vive en Audio →
        #  Sonoridad. El botón sigue existiendo, oculto, porque el motor de reproducción se engancha a él)
        self.btn_lufs.setParent(self)
        self.btn_lufs.setVisible(False)
        controls.addWidget(fila)
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
        # ▶ La barra de transporte va en su propio contenedor de alto FIJO: nunca se aplasta ni se sale por abajo; si
        # falta sitio (barra divisoria con la línea de tiempo, ventana baja), el que se encoge es el lienzo
        from PySide6.QtWidgets import QSizePolicy
        self.transport = QWidget()
        self.transport.setObjectName("transport_bar")
        filas_t = QVBoxLayout(self.transport)
        filas_t.setContentsMargins(0, 0, 0, 0)
        filas_t.setSpacing(0)
        filas_t.addLayout(controls)
        self.transport_fila2 = QWidget()           # (segunda fila: lo de la izquierda cuando no cabe al lado)
        self._lay_fila2 = QHBoxLayout(self.transport_fila2)
        self._lay_fila2.setContentsMargins(10, 0, 10, 4)
        self._lay_fila2.addStretch()
        self.transport_fila2.setVisible(False)
        filas_t.addWidget(self.transport_fila2)
        self._controls = controls
        self._dos_filas = False
        self.transport.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.canvas.setMinimumHeight(40)            # (el lienzo sí puede quedarse pequeño)
        lay.addWidget(self.transport)
        self._rapidos_cortos = None
        self.transport.installEventFilter(self)     # (↔ Silencios / Huecos: con nombre o solo icono, según quepan)

    def _ajustar_rapidos(self, ancho: int | None = None):
        """↔ La barra del transporte, sin esconder nada del transporte por culpa de lo de la izquierda:
          1) todo en una fila con «Silencios» y «Huecos» con su nombre, si cabe;
          2) si no, esos dos solo con su icono (el nombre pasa al tooltip);
          3) si aun así no cabe, lo de la izquierda (modo, duración, Silencios, Huecos) baja a una segunda fila (con
             sus nombres) y el transporte se queda con todo el ancho de la primera.
        Decide con los anchos completos (sin bailar)."""
        bs = list(getattr(self, "quick", {}).values())
        if not bs or getattr(self, "_controls", None) is None:
            return
        ancho = self.transport.width() if ancho is None else ancho
        lay = self._controls
        m = lay.contentsMargins()
        sp = max(0, lay.spacing())
        isp = max(0, self.transport_izq.layout().spacing())
        nombres = iconos = 0
        for b in bs:
            nombre = b.property("nombre_corto") or ""
            nombres += b.iconSize().width() + b.fontMetrics().horizontalAdvance(nombre) + 30 + isp
            iconos += b.iconSize().width() + 22 + isp
        izq = self.btn_mode.sizeHint().width() + 6 + self.duration_label.sizeHint().width() + 10 + 4 * isp
        resto = m.left() + m.right() + self.transport_row.sizeHint().width() + 3 * sp
        if self.task_chip.isVisibleTo(self.transport):
            resto += self.task_chip.sizeHint().width() + sp
        margen = 24 if self._rapidos_cortos is not None else 0     # (no alterna en la frontera)
        if ancho >= resto + izq + nombres + (margen if self._rapidos_cortos or self._dos_filas else 0):
            estado = (False, False)                  # (una fila, con nombres)
        elif ancho >= resto + izq + iconos + (margen if self._dos_filas else 0):
            estado = (True, False)                   # (una fila, solo iconos)
        else:
            estado = (False, True)                   # (dos filas: abajo hay sitio para los nombres)
        if estado == (self._rapidos_cortos, self._dos_filas):
            return
        corto, dos = estado
        self._rapidos_cortos = corto
        if dos != self._dos_filas:
            if dos:
                self._controls.removeWidget(self.transport_izq)
                self._lay_fila2.insertWidget(0, self.transport_izq)
            else:
                self._lay_fila2.removeWidget(self.transport_izq)
                self._controls.insertWidget(0, self.transport_izq)
            self.transport_fila2.setVisible(dos)
            self._dos_filas = dos
        for b in bs:
            nombre, tip = b.property("nombre_corto") or "", b.property("tip_rapido") or ""
            b.setText("" if corto else nombre)
            b.setToolTip(f"{nombre}\n{tip}" if corto else tip)

    def set_playing(self, playing: bool):
        self.btn_play.setText("⏸" if playing else "▶")

    def set_rate(self, rate: float, playing: bool):
        if not playing or rate == 1.0:
            self.rate_label.setText("")
        else:
            arrows = "◀◀" if rate < 0 else "▶▶"
            self.rate_label.setText(f"{arrows} {abs(rate):g}×")
        self.rate_label.setVisible(playing and rate < 0)
        # ⏩ el botón de velocidad: reproduciendo, la de ahora (también con J/L); en pausa, la elegida para Espacio
        self.btn_speed.show_speed(abs(rate) if playing else self._vel_elegida)

    def set_speed_choice(self, v: float, playing: bool = False, rate: float = 1.0):
        """⏩ La velocidad elegida con el botón (la usa Espacio / ▶ la próxima vez)."""
        self._vel_elegida = abs(float(v or 1.0))
        self.set_rate(rate if playing else 1.0, playing)

    def set_title(self, text: str):
        self.title_label.show_name(text)

    def set_time(self, t: float, total: float):
        txt = fmt_tc(t, self.fps)
        self.time_label.setText(txt)
        w = self.time_label.fontMetrics().horizontalAdvance(txt) + 6    # (con la letra ya aplicada: nunca se corta)
        if w > self.time_label.minimumWidth():
            self.time_label.setMinimumWidth(w)
        self.duration_label.setText(fmt_tc(total, self.fps))
        self._total = total
        self._poner_total()

    def _poner_total(self):
        """⏱ «/ duración total» junto al tiempo del cabezal; en la cabecera estrecha, sin las horas si son 0."""
        lbl = getattr(self, "total_label", None)
        if lbl is None:
            return
        txt = fmt_tc(getattr(self, "_total", 0.0), self.fps)
        if getattr(self, "_compacta", False) and txt.startswith("00:"):
            txt = txt[3:]
        lbl.setText("/ " + txt)
        lbl.setToolTip("Duración total del video: " + fmt_tc(getattr(self, "_total", 0.0), self.fps))
        w = lbl.fontMetrics().horizontalAdvance(lbl.text()) + 4
        if lbl.minimumWidth() != w:
            lbl.setMinimumWidth(w)


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
        self.has_video = video_output is not None
        self.fps = 60.0            # fotogramas por segundo del archivo: los saltos caen en un fotograma exacto
        self._req_ms = None        # último salto pedido (ms); None si se reprodujo o cambió el archivo
        self._pending_ms = None    # destino pedido mientras el salto anterior aún se pintaba (arrastre)
        self._in_src = False       # dentro de setSource(): sus señales de estado son del archivo ANTERIOR
        self._vio_fotograma = False  # 🎞 ¿llegó algún fotograma de ESTE archivo? (si no, puede que no lo decodifique)
        self._seek_timer = QTimer()          # «el fotograma llegó»: 250 ms como seguro si no llega
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._resume_pending)
        self.player.mediaStatusChanged.connect(self._on_status)

    def _load(self, path: str, pos: float, playing: bool):
        """Abre un archivo nuevo. Un reproductor que estaba reproduciendo emite LoadedMedia del archivo VIEJO dentro
        de setSource(): esas señales se ignoran (ver _on_status), si no se daba por cargado el archivo nuevo."""
        from ..core.live_video import retenido
        if retenido(path):               # 🔓 se está borrando o moviendo (soltar_archivos): no se abre todavía
            self.path, self.loaded = None, False
            self.want_pos, self.want_play = pos, playing
            return
        self.path, self.loaded = path, False
        self._vio_fotograma = False
        self.loads += 1
        self.want_pos, self.want_play = pos, playing
        self._req_ms = None
        self._in_src = True
        try:
            self.player.setSource(QUrl.fromLocalFile(path))
        finally:
            self._in_src = False

    def _on_status(self, status):
        if self._in_src:
            return
        if status == QMediaPlayer.EndOfMedia and self.has_video and self.path and not self.want_play \
                and not self._vio_fotograma and self._req_ms is not None \
                and self.player.playbackState() != QMediaPlayer.PlayingState:
            dur = self.player.duration()          # «fin del archivo» en un salto en pausa, lejos del final y sin
            if dur > 0 and self._req_ms < dur - 600:   # ningún fotograma de este archivo = no lo decodifica
                _marcar_no_decodifica(self.path)
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and not self.loaded:
            self.loaded = True
            self._req_ms = None
            if self.want_play:
                self._set_pos(self._ms(self.want_pos))
                self._play()
            else:
                # En pausa: primero pausar y LUEGO ir al segundo; así se pinta el fotograma (antes, al cambiar
                # de archivo —p. ej. «Calidad: Un cuarto»— el visor se quedaba en negro hasta reproducir)
                self.player.pause()
                if self.has_video:            # (el audio no tiene imagen: se coloca al reproducir)
                    self._set_pos(self._ms(self.want_pos))
                    QTimer.singleShot(150, self._repaint_frame)

    def _repaint_frame(self):
        if self.loaded and self.player.playbackState() != QMediaPlayer.PlayingState:
            self._seek_paused(self._ms(self.want_pos))

    def _ms(self, pos: float) -> int:
        """Milisegundo del fotograma más cercano a pos (así ±1 fotograma se ve de verdad)."""
        return int(pos * 1000 + 500 / self.fps)

    def _set_pos(self, ms: int):
        """Salto del reproductor; se recuerda el destino para no repetir el mismo fotograma en pausa."""
        self._req_ms = ms
        self._pending_ms = None
        self.player.setPosition(ms)
        self._seek_timer.start(250)

    def _seek_paused(self, ms: int):
        """Salto en pausa. Mientras el anterior aún se pinta (arrastre del cabezal), solo se guarda el destino
        y se pide en cuanto llega el fotograma: así el visor sigue al cabezal sin tirar saltos a medias."""
        self._req_ms = ms
        if self._seek_timer.isActive():
            self._pending_ms = ms
        else:
            self._set_pos(ms)

    def _play(self):
        self._seek_timer.stop()
        self._pending_ms = None
        self._req_ms = None
        self.player.play()

    def _frame_arrived(self, _frame=None):
        """Llegó un fotograma del reproductor: si el salto en curso ya se pintó, va el destino pendiente."""
        if _frame is None or _frame.isValid():
            self._vio_fotograma = True
        if not self._seek_timer.isActive():
            return                     # (reproduciendo llegan muchos: nada que hacer)
        self._seek_timer.stop()
        self._resume_pending()

    def _resume_pending(self):
        ms, self._pending_ms = self._pending_ms, None
        if ms is not None and self.loaded and self.player.playbackState() != QMediaPlayer.PlayingState:
            self._set_pos(ms)

    def idle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self._req_ms = None          # se movió: el último salto pedido ya no vale
        self.want_play = False           # (en pausa, _req_ms se conserva: no se vuelve a pedir el mismo salto)

    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0,
              fps: float | None = None):
        self.audio.setVolume(max(0.0, min(1.0, volume * _ganancia_escucha())))   # (🔊 × volumen de escucha)
        if fps:
            self.fps = fps
        if playing and abs(self.player.playbackRate() - rate) > 1e-3:
            self.player.setPlaybackRate(rate)
        if path != self.path:
            self._load(path, pos, playing)
            return
        if not self.loaded:
            self.want_pos, self.want_play = pos, playing
            return
        cur = self.player.position() / 1000.0
        state = self.player.playbackState()
        if playing:
            self.want_play, self.want_pos = True, pos
            if state != QMediaPlayer.PlayingState:
                if abs(cur - pos) >= 1.0 / self.fps:     # ya está en ese fotograma: solo se reanuda
                    self._set_pos(self._ms(pos))
                self._play()
            elif abs(cur - pos) > 0.3 * max(1.0, rate):  # se desincronizó: corregir
                self._set_pos(self._ms(pos))
        else:
            if state == QMediaPlayer.PlayingState:
                self.player.pause()
                self._req_ms = None
            self.want_pos = pos
            # (el audio, en pausa, no se coloca: al reproducir se coloca solo)
            if self.has_video and self._ms(pos) != self._req_ms:
                self._seek_paused(self._ms(pos))
            if state == QMediaPlayer.StoppedState:
                self.player.pause()

    def dispose(self):
        self._seek_timer.stop()
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
        self.slots = [_Lane(parent, v) for v in layer.videos[:VIDEO_POOL]]
        for s, v in zip(self.slots, layer.videos):     # cada fotograma que llega confirma el salto en curso
            v.videoSink().videoFrameChanged.connect(s._frame_arrived)
        self.active = 0
        self._used = [0.0] * len(self.slots)
        self._n = 0

    def _slot_for(self, path: str, avoid: int | None = None) -> int:
        for i, s in enumerate(self.slots):
            if s.path == path:
                return i
        free = [i for i in range(len(self.slots)) if i != avoid]
        return min(free, key=lambda i: self._used[i])          # el que hace más que no se usa

    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0,
              fps: float | None = None):
        i = self._slot_for(path, avoid=None if self.slots[self.active].path == path else self.active)
        if i != self.active:
            old = self.slots[self.active]
            old.audio.setVolume(0.0)
            old.idle()
            self.active = i
            self.layer.set_active(i)
        self._n += 1
        self._used[i] = self._n
        self.slots[i].drive(path, pos, playing, volume, rate, fps)

    def preload(self, path: str, pos: float, fps: float | None = None):
        """Prepara el siguiente plano en otro reproductor (pausado en su punto, sin sonido)."""
        if path in NO_DECODIFICA:
            return                       # (🎞 no lo decodifica: se verán fotogramas sueltos al llegar)
        act = self.slots[self.active]
        if act.path == path:
            # Mismo archivo que el activo (V1 tapado por un B-roll): si la capa está oculta y en pausa, se coloca ya
            # en su punto; así al destaparse no hay que hacer setPosition+play y esperar la decodificación.
            if (self.layer.box.isVisible() or not act.loaded
                    or act.player.playbackState() == QMediaPlayer.PlayingState):
                return
            if fps:
                act.fps = fps
            act.want_pos = pos
            if act._ms(pos) != act._req_ms:
                act._seek_paused(act._ms(pos))
            return
        i = self._slot_for(path, avoid=self.active)
        s = self.slots[i]
        self._used[i] = self._n + 0.5
        s.audio.setVolume(0.0)
        if fps:
            s.fps = fps
        if s.path != path:
            s._load(path, pos, False)
            return
        if not s.loaded:
            s.want_pos = pos
            return
        if s.player.playbackState() == QMediaPlayer.PlayingState:
            s.player.pause()
            s._req_ms = None
        s.want_pos = pos
        if s._ms(pos) != s._req_ms:
            s._seek_paused(s._ms(pos))

    def idle(self):
        for s in self.slots:
            s.idle()

    def dispose(self):
        for s in self.slots:
            s.dispose()

    def park(self):
        for s in self.slots:
            s.park()


class _OwnVideoLane:
    """🎞 Pista de video con el motor propio (core/live_video.py): los mismos métodos que _VideoLane. Cada archivo se
    decodifica en su hilo y su imagen se pone en el mismo QGraphicsVideoItem de siempre (efectos, color, fondo
    desenfocado y relleno siguen igual). Sin sonido: el audio va por la mezcla en directo."""

    def __init__(self, parent: QObject, layer, base: int = 0, n: int = VIDEO_POOL):
        """base, n: qué videos de la capa usa (todo el motor propio: 0–2; con la pista mixta: 3–4)."""
        from PySide6.QtCore import QTimer as _QT
        self.engine = parent
        self.layer = layer
        self.base = base
        self.src: dict = {}
        self.size_for: dict = {}          # ruta → tamaño al que se decodifica (cada plano el suyo)
        self._want_active: int | None = None   # slot que pasa a verse en cuanto tenga su fotograma
        self._pend_t: dict = {}           # slot → desde cuándo espera (tope)
        self.paths: list = [None] * n
        self.active = 0
        self._used = [0.0] * n
        self._n = 0
        self._shown: list = [None] * n
        self.size = (960, 540)
        self._pend: dict = {}             # slot → segundo pedido cuyo fotograma aún no llegó
        self._a_tiempo: dict = {}         # ruta → [peticiones reproduciendo, cuántas sin su fotograma a tiempo]
        # ⚡ reproduciendo, el fotograma que cae ENTRE dos tics del motor (30 ms) se pone justo a su hora: sin esto, con
        # video de 30 fps el vaivén del temporizador saltaba alguno (y poner el motor a 15 ms gastaba ~50 % más CPU)
        self._entre = _QT()
        self._entre.setSingleShot(True)
        self._entre.setTimerType(Qt.PreciseTimer)
        self._entre.timeout.connect(self._push_entre)
        self._entre_dat = None
        self._timer = _QT()
        self._timer.setInterval(4)                 # (mientras espera un fotograma: mirar cada 4 ms)
        self._timer.timeout.connect(self._retry)

    def _slot_for(self, path: str, avoid: int | None = None) -> int:
        for i, p in enumerate(self.paths):
            if p == path:
                return i
        free = [i for i in range(len(self.paths)) if i != avoid]
        return min(free, key=lambda i: self._used[i])

    def _source(self, i: int, path: str):
        if self.paths[i] != path or self.src.get(i) is None or self.src[i].cerrado:
            # (🔓 cerrada por soltar_archivos: se abre otra; mientras el archivo esté retenido, espera sin abrirlo)
            old = self.src.pop(i, None)
            if old is not None:
                old.close()
            from ..core.live_video import FrameSource
            self.src[i] = FrameSource(path)
            self.paths[i] = path
            self._shown[i] = None
        return self.src[i]

    def failed(self, path: str) -> bool:
        return any(s.error for i, s in self.src.items() if self.paths[i] == path)

    def set_target(self, max_w: float, src_w: int, src_h: int, path: str | None = None):
        """Decodifica al tamaño con el que se ve (nunca más que el archivo; par para el escalado). Por plano: la
        precarga del siguiente usa SU tamaño (si no, al llegar el corte se perdería lo preparado)."""
        if src_w <= 0 or src_h <= 0:
            return
        w = int(min(src_w, max(160.0, max_w)))
        w -= w % 2
        h = max(2, int(round(w * src_h / src_w)))
        h -= h % 2
        prev = self.size_for.get(path, self.size) if path else self.size
        if abs(w - prev[0]) > 0.1 * prev[0] or abs(h - prev[1]) > 0.1 * prev[1]:
            prev = (w, h)
        if path:
            self.size_for[path] = prev
        else:
            self.size = prev

    def _push(self, i: int, pos: float) -> bool:
        s = self.src.get(i)
        if s is None:
            return True
        fr = s.frame_at(pos)
        if fr is None:
            return False
        pts, w, h, data = fr
        key = (self.paths[i], round(pts * 1000), w)
        if key != self._shown[i]:
            from PySide6.QtMultimedia import QVideoFrame
            img = QImage(data, w, h, w * 4, QImage.Format_RGBA8888)
            vf = QVideoFrame(img.copy())
            vf.setStartTime(int(round(pts * 1e6)))                     # (su tiempo, como los de Qt)
            vf.setEndTime(int(round((pts + 1.0 / max(1.0, s.fps)) * 1e6)))
            self.layer.videos[self.base + i].videoSink().setVideoFrame(vf)
            self._shown[i] = key
        return abs(pts - pos) <= 1.0 / max(1.0, s.fps)

    def visible(self) -> bool:
        """¿Se ve ahora su video activo? (con _MixedVideoLane, la capa puede estar enseñando un reproductor de Qt)."""
        return self.layer.active == self.base + self.active

    def _programar_entre(self, i: int, pos: float, rate: float, fps: float):
        import time as _t
        fps = max(1.0, fps or 30.0)
        nxt = (math.floor(pos * fps + 1e-6) + 1) / fps
        dt = (nxt - pos) / max(1e-3, rate)
        if dt < 0.04:
            self._entre_dat = (i, pos, rate, _t.perf_counter())
            self._entre.start(max(0, int(math.ceil(dt * 1000)) + 1))

    def _push_entre(self):
        import time as _t
        d, self._entre_dat = self._entre_dat, None
        if d is None or d[0] != self.active or not self.visible():
            return
        i, pos, rate, t0 = d
        self._push(i, pos + (_t.perf_counter() - t0) * rate)

    LENTO_N = 150          # peticiones reproduciendo (≈ 2–5 s) antes de decidir
    LENTO_FRAC = 0.25      # más de 1 de cada 4 sin su fotograma a tiempo → el equipo no da: copia ligera
    LENTO_GRACIA_S = 0.8   # tras ▶ o un salto, lo primero no cuenta (es normal que tarde: decodifica desde la clave)

    def _medir(self, path: str, listo: bool, pos: float = 0.0, rate: float = 1.0):
        """⚡ ¿Este equipo reproduce el archivo a tiempo? Si no (y no es por un salto: se cuenta en tandas largas y sin
        lo que sigue a ▶ o a un salto), se marca LENTO y se pide su copia ligera. Una copia ligera no se mide."""
        if path in LENTOS or os.path.basename(os.path.dirname(path)).lower() == "proxies":
            return
        import time as _t
        ahora = _t.monotonic()
        ult = self.__dict__.setdefault("_medir_ult", {}).get(path)
        if ult is None or ahora - ult[1] > 0.25 or abs(pos - (ult[0] + (ahora - ult[1]) * rate)) > 0.25:
            self.__dict__.setdefault("_medir_gracia", {})[path] = ahora + self.LENTO_GRACIA_S   # (▶ o salto)
        self._medir_ult[path] = (pos, ahora)
        if ahora < self.__dict__.get("_medir_gracia", {}).get(path, 0.0):
            return
        c = self._a_tiempo.setdefault(path, [0, 0])
        c[0] += 1
        c[1] += not listo
        if c[0] >= self.LENTO_N:
            if c[1] > self.LENTO_FRAC * c[0]:
                _marcar_lento(path)
            c[0] = c[1] = 0

    def _activate(self, i: int):
        if i != self.active or not self.visible():
            self.active = i
            self._shown[i] = None             # (se vuelve a poner: el fondo desenfocado y el relleno lo recogen)
            self.layer.set_active(self.base + i)

    def soltar(self):
        """Deja de pedir que se vea (otro reproductor pasa a enseñar la capa): nada pendiente de activar."""
        self._entre.stop()
        self._want_active = None
        self._pend.clear()
        self._pend_t.clear()
        self._timer.stop()

    def soltar_reposo(self):
        """💤 En reposo: se cierran los archivos que no se ven (cada uno guarda ~50 MB de su decodificador); el que se
        ve se queda con lo justo. Volver a abrir uno cuesta ~10 ms."""
        quedar = self.active if self.visible() and self.layer.box.isVisible() else None
        for i in list(self.src):
            if i == quedar:
                self.src[i].trim(1)
                continue
            self.src.pop(i).close()
            self.paths[i] = None
            self._shown[i] = None
            self._pend.pop(i, None)

    def rutas(self) -> list[str]:
        """Los archivos que tiene abiertos (🔓 soltar_archivos y lo que ya no se usa)."""
        return [p for i, p in enumerate(self.paths) if p and self.src.get(i) is not None and not self.src[i].cerrado]

    def soltar_rutas(self, claves) -> list[str]:
        """🔓 Cierra (sin esperar: core/soltar_archivos espera a todas juntas) los archivos de claves (rutas normalizadas,
        o carpetas) y olvida sus huecos. Vuelven a abrirse solos cuando hagan falta. Devuelve los que cerró."""
        from ..core.live_video import _toca, clave_ruta
        hechos = []
        for i, pth in enumerate(list(self.paths)):
            if not pth or not _toca(clave_ruta(pth), claves):
                continue
            src = self.src.pop(i, None)
            if src is not None:
                src.close()
            hechos.append(pth)
            self.paths[i] = None
            self._shown[i] = None
            self._pend.pop(i, None)
            self._pend_t.pop(i, None)
            if self._want_active == i:
                self._want_active = None
        if not self._pend:
            self._timer.stop()
        return hechos

    def _retry(self):
        import time as _t
        for i, pos in list(self._pend.items()):
            s = self.src.get(i)
            if s is not None and s.error:     # (falló: la pista vuelve a los reproductores de siempre)
                del self._pend[i]
                if i in (self.active, self._want_active):
                    self._pend.clear()
                    self._timer.stop()
                    QTimer.singleShot(0, self.engine._sync)
                    return
                continue                      # (un plano precargado roto: nada; se verá al llegar)
            if self._push(i, pos):
                del self._pend[i]
                self._pend_t.pop(i, None)
                if self._want_active == i:
                    self._activate(i)
                    self._want_active = None
                    self._push(i, pos)
            elif _t.monotonic() - self._pend_t.setdefault(i, _t.monotonic()) > 3.0:
                del self._pend[i]             # (tope: no esperar para siempre)
                self._pend_t.pop(i, None)
                if self._want_active == i:
                    self._want_active = None
        if not self._pend:
            self._timer.stop()

    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0,
              fps: float | None = None):
        i = self._slot_for(path, avoid=None if self.paths[self.active] == path else self.active)
        self._n += 1
        self._used[i] = self._n
        s = self._source(i, path)
        s.want(pos, playing and rate > 0, self.size_for.get(path, self.size))
        listo = self._push(i, pos)
        if playing and rate > 0:
            self._medir(path, listo, pos, rate)
            self._programar_entre(i, pos, rate, s.fps)
        else:
            self._entre.stop()
        if i != self.active or not self.visible():
            old = self.src.get(self.active) if i != self.active else None
            if listo or self._shown[i] is None and old is None and self.base == 0:
                if old is not None:
                    old.want(old._want_t, False)
                    old.trim(3)               # (el plano anterior: solo lo justo en memoria)
                self._activate(i)
                self._push(i, pos)
                self._want_active = None
            else:
                self._want_active = i         # (se verá en cuanto llegue su fotograma: nada de imagen vieja)
        if not listo:
            self._pend[i] = pos           # (aún decodificando: se pone en cuanto llegue)
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._pend.pop(i, None)

    def preload(self, path: str, pos: float, fps: float | None = None):
        """El siguiente plano, decodificado de antemano (y ya puesto en su video oculto): el corte es inmediato."""
        if self.paths[self.active] == path:
            if self.layer.box.isVisible() and self.visible():
                return
            i = self.active
        elif path in self.paths:
            i = self.paths.index(path)
            if i == self._want_active:
                return                        # (es el que se está a punto de enseñar: no se le cambia el segundo)
        else:
            # nunca el que se ve ni el que se está a punto de enseñar (esperando su fotograma): antes, con 2 huecos,
            # la precarga del plano siguiente le quitaba el archivo al recién pedido y el visor se quedaba sin imagen
            libres = [k for k in range(len(self.paths)) if k not in (self.active, self._want_active)]
            if not libres:
                return
            i = min(libres, key=lambda k: self._used[k])
            self._used[i] = self._n + 0.5
        s = self._source(i, path)
        if s.error:
            return                            # (roto: no se reintenta cada 8 ms)
        s.want(pos, False, self.size_for.get(path, self.size))
        if not self._push(i, pos):
            self._pend[i] = pos
            if not self._timer.isActive():
                self._timer.start()

    def idle(self):
        self._entre.stop()
        for s in self.src.values():
            s.want(s._want_t, False)
            s.trim(3)                     # (la pista no se ve: casi nada en memoria)

    def park(self, wait: float = 0.0):
        self._timer.stop()
        self._entre.stop()
        self._pend.clear()
        self._want_active = None
        for s in self.src.values():
            s.close(wait)
        self.src.clear()
        self.paths = [None] * len(self.paths)
        self._shown = [None] * len(self._shown)

    def dispose(self):
        self.park()


_CODEC: dict = {}          # ruta → códec de video («hevc», «libdav1d»…; "" mientras se mira, «?» si no se sabe)
_CODEC_COLA: list = []     # rutas por mirar (un solo hilo para todas)


def _codec_de(path: str) -> str:
    """Códec de video del archivo, mirado UNA vez en segundo plano (nunca para la interfaz); "" mientras tanto."""
    if path in _CODEC:
        return _CODEC[path]
    _CODEC[path] = ""
    _CODEC_COLA.append(path)
    if len(_CODEC_COLA) == 1:

        def mirar():
            while _CODEC_COLA:
                p = _CODEC_COLA[0]
                try:
                    import av
                    with av.open(p) as c:
                        _CODEC[p] = (str(c.streams.video[0].codec_context.name or "").lower() or "?"
                                     if c.streams.video else "?")
                except Exception:  # noqa: BLE001 - no se sabe: lo de siempre
                    _CODEC[p] = "?"
                try:                    # (y dónde empieza el archivo: lo necesita exportar con miles de piezas)
                    from ..export.ffmpeg_export import _inicio_audio
                    _inicio_audio(p)
                except Exception:  # noqa: BLE001
                    pass
                _CODEC_COLA.pop(0)
        __import__("threading").Thread(target=mirar, name="codec_visor", daemon=True).start()
    return ""


def _es_av1(path: str) -> bool:
    """AV1 (el decodificador de PyAV se llama «libdav1d»): Qt solo lo decodifica con tarjeta; el motor propio, siempre."""
    c = _codec_de(path)
    return "av1" in c or "dav1d" in c


def _hay_pyav() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _ajuste_si(clave: str) -> bool:
    try:
        import av  # noqa: F401
    except Exception:  # noqa: BLE001 - sin PyAV, nunca el motor propio
        return False
    from PySide6.QtCore import QSettings as _QS
    return str(_QS("EditorIA", "EditorIA").value(clave, "true")).lower() == "true"


def pesados_con_motor_propio() -> bool:
    """⚡ Ajuste «video/motor_propio_pesados» (sí por defecto): lo pesado va con el motor propio aunque el resto vaya con
    los reproductores de siempre. Sin PyAV, nunca."""
    return _ajuste_si("video/motor_propio_pesados")


def pausa_con_motor_propio() -> bool:
    """⚡ Ajuste «video/pausa_motor_propio» (sí por defecto): en pausa (saltos, arrastrar el cabezal, paso a paso, hacia
    atrás) la imagen la da el motor propio, que llega al fotograma exacto en ~30 ms (los reproductores de Qt, ~70–130)."""
    return _ajuste_si("video/pausa_motor_propio")


class _MixedVideoLane(_VideoLane):
    """⚡ Pista de video MIXTA (la de por defecto). Los reproductores de Qt (sus 3 videos de la capa) siguen haciendo lo
    que mejor hacen, REPRODUCIR lo normal con su sonido; el motor propio (core/live_video.py, en los videos 3–4 de la
    capa) hace lo demás:
      · lo PESADO, siempre: más que 1440p (4K…) al tamaño del visor y, al reproducir, con la tarjeta gráfica (HEVC 4K:
        de 1,2 núcleos a ~0,6, sin los fotogramas 4K enteros en memoria); y lo que Qt no decodifica (AV1 sin tarjeta,
        NO_DECODIFICA): se ve y se reproduce de verdad, sin fotogramas sueltos;
      · en PAUSA, todo: el fotograma exacto llega en ~30 ms. El reproductor de Qt se coloca en ese punto cuando paras
        de arrastrar (QT_TRAS_MS), así ▶ arranca al momento; y al darle a ▶ se sigue viendo el fotograma del motor propio
        hasta que llega el primero de Qt (ni negro ni imagen vieja).
    Un archivo que el motor propio no abre vuelve solo a Qt. Mientras el motor propio no tiene listo su fotograma, se
    sigue viendo lo de antes."""

    QT_TRAS_MS = 200            # en pausa: el reproductor de Qt se coloca cuando el cabezal lleva este rato quieto
    ESPERA_QT_MS = 400          # al darle a ▶: como mucho se espera esto al primer fotograma de Qt
    REPOSO_MS = 20000           # 💤 en pausa y sin tocar el visor: se sueltan los archivos del motor propio que no se ven

    def _en_reposo(self):
        if self.own is not None and not getattr(self.engine, "playing", False):
            self.own.soltar_reposo()

    def __init__(self, parent: QObject, layer):
        super().__init__(parent, layer)
        self.engine = parent
        self.own: _OwnVideoLane | None = None
        self.modo = "qt"                       # quién manda ahora: «qt» | «propio»
        self._pesado: dict = {}                # ruta → ¿va con el motor propio también al reproducir?
        self._malos: set = set()               # rutas que el motor propio no pudo abrir
        self.pausa_propia = pausa_con_motor_propio()
        self.pesados_on = pesados_con_motor_propio()
        self._qt_pend = None                   # (ruta, segundo, fps): dónde colocar Qt cuando pares de arrastrar
        self._qt_timer = QTimer()
        self._qt_timer.setSingleShot(True)
        self._qt_timer.setInterval(self.QT_TRAS_MS)
        self._qt_timer.timeout.connect(self._colocar_qt)
        self._esperando = False                # ▶ recién pulsado: Qt aún no dio su primer fotograma
        self._espera_timer = QTimer()
        self._espera_timer.setSingleShot(True)
        self._espera_timer.setInterval(self.ESPERA_QT_MS)
        self._espera_timer.timeout.connect(self._mostrar_qt)
        self._reposo = QTimer()                # 💤 sin tocar nada un rato: el motor propio suelta lo que no se ve
        self._reposo.setSingleShot(True)
        self._reposo.setInterval(self.REPOSO_MS)
        self._reposo.timeout.connect(self._en_reposo)
        for i, v in enumerate(layer.videos[:VIDEO_POOL]):
            v.videoSink().videoFrameChanged.connect(lambda f, i=i: self._llego_qt(i, f))

    # ------------------------------------------------------------ quién hace qué
    def clasificar(self, path: str, m) -> bool:
        """¿Esta ruta va con el motor propio también al reproducir (pesada)? (se recuerda por ruta)."""
        if path in self._malos or not self.pesados_on:
            return False
        v = self._pesado.get(path)
        if v is None or (not v and (path in NO_DECODIFICA or _es_av1(path))):
            grande = m is not None and path == m.path and m.width * m.height > 2560 * 1440
            v = grande or path in NO_DECODIFICA or _es_av1(path)
            if _CODEC.get(path, "") != "" or v:
                self._pesado[path] = v         # (con el códec aún por saber, se vuelve a mirar la próxima vez)
        return v

    def propio(self, path: str) -> bool:
        return bool(self._pesado.get(path)) and path not in self._malos

    def _own(self) -> _OwnVideoLane:
        if self.own is None:
            self.own = _OwnVideoLane(self.engine, self.layer, base=VIDEO_POOL, n=PROPIO_POOL)
        return self.own

    def set_target(self, max_w: float, src_w: int, src_h: int, path: str | None = None):
        self._own().set_target(max_w, src_w, src_h, path)

    QT_USADOS = 2               # ⚡ reproductores de Qt que llegan a abrir archivo (el que suena y el siguiente)

    def _slot_for(self, path: str, avoid: int | None = None) -> int:
        """Como en _VideoLane, pero solo con QT_USADOS reproductores: con la pausa en el motor propio, Qt solo hace falta
        para el plano que suena y el siguiente. Cada reproductor de Qt con un 1080p abierto ocupa ~130 MB (sus hilos
        de decodificación): el tercero, que solo guardaba un archivo «por si acaso», ya no se abre."""
        for i, s in enumerate(self.slots[:self.QT_USADOS]):
            if s.path == path:
                return i
        free = [i for i in range(min(self.QT_USADOS, len(self.slots))) if i != avoid] or [0]
        return min(free, key=lambda i: self._used[i])

    # ------------------------------------------------------------ Qt sin enseñarse
    def _drive_qt(self, path: str, pos: float, playing: bool, volume: float, rate: float, fps, mostrar: bool):
        """Lo mismo que _VideoLane.drive, pero la capa solo pasa a enseñar el reproductor de Qt si mostrar."""
        i = self._slot_for(path, avoid=None if self.slots[self.active].path == path else self.active)
        if i != self.active:
            old = self.slots[self.active]
            old.audio.setVolume(0.0)
            old.idle()
            self.active = i
        if mostrar:
            self.layer.set_active(i)
        self._n += 1
        self._used[i] = self._n
        self.slots[i].drive(path, pos, playing, volume, rate, fps)

    def _colocar_qt(self):
        """En pausa, con el cabezal quieto: el reproductor de Qt del plano, colocado en su punto (sin enseñarse)."""
        if self._qt_pend is None or self.modo != "propio":
            return
        path, pos, fps = self._qt_pend
        self._qt_pend = None
        self._qt_hecho = (path, round(pos, 4))
        self._drive_qt(path, pos, False, 0.0, 1.0, fps, mostrar=False)

    def _llego_qt(self, i: int, f):
        if self._esperando and self.modo == "qt" and i == self.active and f.isValid():
            self._mostrar_qt()

    def _mostrar_qt(self):
        if self._esperando and self.modo == "qt":
            self.layer.set_active(self.active)
        self._esperando = False
        self._espera_timer.stop()

    # ------------------------------------------------------------ lo que pide el motor
    def drive(self, path: str, pos: float, playing: bool, volume: float, rate: float = 1.0,
              fps: float | None = None):
        if self.own is not None and self.own.failed(path):
            self._malos.add(path)              # (el motor propio no puede: con los reproductores de siempre)
        clave = (path, round(pos, 4))
        if playing:
            self._reposo.stop()
            self._qt_hecho = None
        elif clave != self.__dict__.get("_ult_pausa") or not self._reposo.isActive():
            self._reposo.start()               # (en pausa quieta, repetir drive no lo aplaza: solo si algo cambió)
        self._ult_pausa = None if playing else clave
        pesado = self.propio(path)
        if pesado or (not playing and self.pausa_propia and path not in self._malos):
            if self.modo != "propio":
                act = self.slots[self.active]
                act.audio.setVolume(0.0)
                if pesado:
                    super().idle()             # (los reproductores de Qt, en pausa: no gastan)
                else:
                    act.idle()                 # (paraba de reproducir: Qt en pausa; se colocará al quedarse quieto)
                self.modo = "propio"
            self._esperando = False
            self._espera_timer.stop()
            if not pesado and clave != self.__dict__.get("_qt_hecho") and                     (self._qt_pend is None or (self._qt_pend[0], round(self._qt_pend[1], 4)) != clave):
                # (solo si cambió: un drive repetido con el cabezal quieto no reinicia la espera, así Qt llega a
                # colocarse y en reposo no se gasta nada)
                self._qt_pend = (path, pos, fps)
                self._qt_hecho = None
                self._qt_timer.start()
            self._own().drive(path, pos, playing, volume, rate, fps)
            return
        # reproducir lo normal: los reproductores de Qt (con su sonido)
        self._qt_timer.stop()
        self._qt_pend = None
        if self.modo == "propio":
            ver_propio = self.own is not None and self.own.visible() and self.layer.box.isVisible()
            if self.own is not None:
                self.own.soltar()
                self.own.idle()
            self.modo = "qt"
            if ver_propio:                     # (se sigue viendo su fotograma hasta que llegue el primero de Qt)
                self._esperando = True
                self._espera_timer.start()
        self._drive_qt(path, pos, playing, volume, rate, fps, mostrar=not self._esperando)

    def preload(self, path: str, pos: float, fps: float | None = None):
        if self.propio(path):
            self._own().preload(path, pos, fps)
        else:
            super().preload(path, pos, fps)

    def idle(self):
        self._qt_timer.stop()
        self._qt_pend = None
        self._qt_hecho = self._ult_pausa = None
        if not self._reposo.isActive():
            self._reposo.start()
        super().idle()
        if self.own is not None:
            self.own.idle()

    def park(self):
        self._qt_timer.stop()
        self._espera_timer.stop()
        self._reposo.stop()
        self._qt_pend = None
        self._esperando = False
        super().park()
        if self.own is not None:
            self.own.park()

    def dispose(self):
        self.park()
        super().dispose()
        if self.own is not None:
            self.own.dispose()


def scrub_activo() -> bool:
    """🔊 ¿Suena el audio al arrastrar el cabezal? (Reproducción → «Oír al arrastrar el cabezal»; sí por defecto)."""
    from PySide6.QtCore import QSettings as _QS
    return str(_QS("EditorIA", "EditorIA").value("reproduccion/oir_al_arrastrar", "true")).lower() == "true"


def _cola_reproduccion(playing: bool, quien=None):
    """▶ Mientras reproduces, los análisis automáticos (cola única: ui/cola_analisis.py) se pausan: el video va fluido.
    quien: qué motor (con dos visores, parar uno no quita la pausa)."""
    from .cola_analisis import al_reproducir
    al_reproducir(playing, quien)


_MOTORES = __import__("itertools").count(1)
_MOTORES_VIVOS = __import__("weakref").WeakSet()     # 🔓 los visores abiertos (soltar_archivos los recorre)


def _soltar_en_motores(claves) -> list[str]:
    """🔓 (core/soltar_archivos) Cada visor suelta esos archivos: reproductores de Qt, motor propio, fotograma suelto."""
    hechos: list[str] = []
    for eng in list(_MOTORES_VIVOS):
        try:
            hechos += eng.soltar_rutas(claves)
        except RuntimeError:          # (el visor ya no existe)
            continue
    return hechos


def _apuntar_soltador():
    from ..core import soltar_archivos as _SA
    _SA.registrar(_soltar_en_motores)


_apuntar_soltador()
GIL_S = 0.001            # ⚡ cada cuánto Python deja pasar a otro hilo (por defecto 0,005 s; en Windows, por debajo
#                          de 1 ms la espera queda en 0 y la interfaz con un hilo de Python de fondo iba 3 veces más lenta)


def _repartir_gil():
    """⚡ Los hilos que decodifican (motor propio, audio en directo) necesitan el GIL de Python entre fotograma y
    fotograma. Con el reparto de Python por defecto (cada 5 ms), mientras la interfaz trabaja en Python cada fotograma
    esperaba su turno: decodificar 1080p pasaba de ~0,7 ms a ~16–21 ms por fotograma (saltos de 60–170 ms en vez de
    ~30). Con 1 ms van mucho más deprisa sin castigar a la interfaz (con 0,5 ms, en Windows, sí la castigaba)."""
    import sys as _sys
    try:
        if _sys.getswitchinterval() > GIL_S:
            _sys.setswitchinterval(GIL_S)
    except Exception:  # noqa: BLE001
        pass


class PlaybackEngine(QObject):
    time_changed = Signal(float)
    playing_changed = Signal(bool)

    def __init__(self, ctrl, preview: PreviewPanel, parent=None):
        super().__init__(parent)
        _repartir_gil()
        # ▶ mientras suena, los análisis automáticos esperan (y si el motor desaparece sonando, deja de contar)
        k = f"motor {next(_MOTORES)}"   # (un nombre propio: id() se puede repetir cuando un motor desaparece)
        self.playing_changed.connect(lambda on, k=k: _cola_reproduccion(on, k))
        self.destroyed.connect(lambda *_a, k=k: _cola_reproduccion(False, k))
        self.mute_all = False          # 🎙 al grabar la voz en off: todo en silencio
        self.ctrl = ctrl
        self.preview = preview
        _MOTORES_VIVOS.add(self)       # (🔓 soltar_archivos lo encuentra)
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
        self._last_w: dict[str, float] = {}   # ancho en pantalla usado por pista (margen para no recargar)
        self._cue_key = None                  # con qué datos se calcularon los subtítulos (ver _refresh)
        self._audio: dict[str, _Lane] = {}
        self._ranges: list[tuple[float, float]] = []  # fragmentos pendientes de "Escuchar"
        self._stop_at: float | None = None
        self._cues = []        # subtítulos ya calculados
        self._speech: list[tuple[float, float]] = []
        self._cue_starts: list[float] = []
        self._bounds: list[float] = []        # inicios y fines de los clips de video (ver _arm_cut)
        self._cut_timer = QTimer(self)        # corte a tiempo: un _tick justo en el próximo inicio/fin de clip
        self._cut_timer.setSingleShot(True)
        self._cut_timer.setTimerType(Qt.PreciseTimer)
        self._cut_timer.timeout.connect(self._on_cut)

        # 🎧 audio en directo (EQ, volumen, curvas, ducking mientras suena); si no hay tarjeta, los reproductores
        self.live = None
        self._ids_vivos: set[str] = set()
        self._live_check = 0
        from PySide6.QtCore import QSettings as _QS
        self._own_video = str(_QS("EditorIA", "EditorIA").value("video/motor_propio", "false")).lower() == "true"
        _AVISOS_NO_DECODIFICA.append(self._al_no_decodificar)
        _AVISOS_LENTO.append(self._al_lento)
        if self._own_video:
            self._timer.setInterval(15)               # (🎞 hasta 60 fotogramas por segundo en el visor)
        from PySide6.QtWidgets import QApplication as _QA0
        if _QA0.instance() is not None:
            _QA0.instance().aboutToQuit.connect(self.shutdown_video)
        if str(_QS("EditorIA", "EditorIA").value("audio/en_directo", "true")).lower() == "true":
            self.live = self._crear_live()
        self.zones = None
        try:                                          # ⧉ transiciones reales en el visor (renderizadas en segundo plano)
            from .zone_preview import ZonePreview
            self.zones = ZonePreview(self)
        except Exception:  # noqa: BLE001 - sin esto, el visor sigue como siempre (fundidos)
            self.zones = None

        preview.btn_play.clicked.connect(self.toggle)
        preview.btn_start.clicked.connect(lambda: self.user_seek(0))
        preview.btn_end.clicked.connect(lambda: self.user_seek(self._proj().duration()))
        preview.btn_back.clicked.connect(lambda: self.step(-1))
        preview.btn_fwd.clicked.connect(lambda: self.step(1))
        preview.btn_loop.toggled.connect(self.set_loop)
        # ⏪ ⏩ 🔊 📊 lo nuevo de la barra (ui/transport_extra.py)
        from .transport_extra import SALTO_S, asistente_sonoridad, escucha
        self.vel = 1.0           # ⏩ velocidad elegida con el botón «1×» (la de Espacio / ▶; J/K/L van aparte)
        preview.btn_back5.clicked.connect(lambda: self.nudge(-SALTO_S))
        preview.btn_fwd5.clicked.connect(lambda: self.nudge(SALTO_S))
        preview.btn_speed.cycle.connect(self.cycle_speed)
        preview.btn_speed.chosen.connect(self.set_speed)
        escucha().changed.connect(self._on_escucha)
        if self.live is not None:
            self.live.mixer.monitor = escucha().gain
        self.loudness = asistente_sonoridad(ctrl)
        self.loudness.busy.connect(preview.btn_lufs.set_busy)
        preview.btn_lufs.clicked.connect(lambda: self.loudness.start(preview.window()))
        ctrl.project_changed.connect(self._refresh)
        ctrl.transcript_changed.connect(self._on_transcript)
        ctrl.project_replaced.connect(lambda: (self.pause(), self.seek(0)))
        preview.motor_mixto_cambiado.connect(self._motor_mixto)
        self._refresh()

    def _proj(self):
        """🎬 El proyecto que se pinta y suena: el de verdad con cada clip de escena desplegado (fondo, personajes y
        sonidos; core/escena_clip.py). Sin clips de escena es el mismo objeto."""
        from ..core import escena_clip
        return escena_clip.expandir(self.ctrl.project)

    def _on_transcript(self, _media_id=None):
        self._cue_key = None           # la transcripción cambió: se recalculan subtítulos y tramos de voz
        self._refresh()

    def _next_clip(self, track_id: str, c):
        best = None
        for o in self._proj().clips_on(track_id):
            if o.start >= c.end - 1e-3 and o.enabled and (best is None or o.start < best.start):
                best = o
        return best

    # ----------------------------------------------------------- control
    def toggle(self):
        self.pause() if self.playing else self.play(rate=getattr(self, "vel", 1.0))

    # ------------------------------------------- ⏪ ⏩ 🔊 botones nuevos de la barra (ui/transport_extra.py)
    def nudge(self, secs: float):
        """−5 s / +5 s: mueve el cabezal sin pasar del principio ni del final (seek lo limita); reproduciendo, sigue
        sonando desde ahí."""
        self.user_seek(self.time + float(secs))

    def set_speed(self, v: float):
        """⏩ Velocidad elegida (1×, 2×, 4×, 8×). Reproduciendo cambia ya (como J/K/L, mismo mecanismo; hacia atrás
        sigue hacia atrás); en pausa queda para la próxima vez que le des a Espacio / ▶."""
        v = abs(float(v or 1.0))
        self.vel = v
        if self.playing:
            self._cambiar_rate(-v if self.rate < 0 else v)
        self.preview.set_speed_choice(v, self.playing, self.rate)

    def cycle_speed(self):
        """Clic en «1×»: 1× → 2× → 4× → 8× → 1× (reproduciendo, desde la velocidad de ahora, también la de J/L)."""
        from .transport_extra import siguiente_velocidad
        self.set_speed(siguiente_velocidad(abs(self.rate) if self.playing else self.vel))

    def _on_escucha(self, gain: float):
        """🔊 Volumen de escucha: la mezcla en directo y los reproductores (estos, en el próximo _sync)."""
        live = getattr(self, "live", None)
        if live is not None:
            live.mixer.monitor = float(gain)
        if hasattr(self, "_audio"):
            self._sync()

    def _cambiar_rate(self, new: float):
        """Cambia la velocidad sin parar (J/K/L y el botón de velocidad)."""
        self._t0, self.rate = self.time, new
        self._clock.restart()
        self.preview.set_rate(self.rate, True)
        self._plan_al_dia()
        if self.live is not None:
            if self._live_on():
                self.live.start(self.time)
            else:
                self.live.stop()
        self._sync()

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
            self._cambiar_rate(new)
        else:
            self.play(rate=new)

    def play_marked(self):
        """Reproduce de la entrada a la salida (Alt+/)."""
        rng = self._proj().marked_range()
        if rng:
            self.play_ranges([rng])
        else:
            self.ctrl.message.emit("Marca antes la entrada (I) y la salida (O) del tramo que quieres ver.")

    def play(self, rate: float = 1.0):
        if self.playing:
            return
        total = self._proj().duration()
        if total <= 0:
            return
        self.rate = rate
        if rate > 0 and self.time >= total - 0.05:
            self.time = 0.0
        elif rate < 0 and self.time <= 0.05:
            self.time = total
        self._plan_al_dia()
        self.playing = True
        if self._live_on():
            self.live.wait_ready(self.time)      # (hasta 0,3 s: que no empiece mudo)
        self._t0 = self.time
        if self._live_on():
            self.live.start(self.time)
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
        self._cut_timer.stop()
        if not self.playing:
            return
        self.playing = False
        self._timer.stop()
        if self.live is not None:
            self.live.stop()
        self.rate = 1.0
        self.preview.set_playing(False)
        self.preview.set_rate(1.0, False)
        self.playing_changed.emit(False)
        self._sync()

    def seek(self, t: float):
        # ⚡ (22/11, ronda 2) todo el salto —el visor y quien escucha time_changed: línea de tiempo, Inspector, «clip en
        # el cabezal», transformar…— dentro de UNA lectura del proyecto: duration() y clip_at() no recorren ni ordenan
        # los ~2500 clips en cada llamada (arrastrar el cabezal hacía decenas por paso)
        with self._proj().lectura(getattr(self.ctrl, "rev", None)):
            self._seek(t)

    def _seek(self, t: float):
        self.time = max(0.0, min(t, max(self._proj().duration(), 0.0)))
        if self.playing:
            self._t0 = self.time
            self._clock.restart()
            if self._live_on():
                self.live.prepare(self.time)      # (pide ya lo del punto nuevo y cancela lo de antes)
                self.live.start(self.time)        # (salto mientras suena: la mezcla sigue desde ahí)
        elif self.live is not None:
            self.live.prepare(self.time)
        self._sync()
        self.time_changed.emit(self.time)

    def user_seek(self, t: float):
        """Salto pedido por el usuario: cancela cualquier «Escuchar» en curso."""
        self._stop_at = None
        self._ranges = []
        self.seek(t)

    SCRUB_MS = 90           # 🔊 lo que suena en cada posición al arrastrar el cabezal
    SCRUB_CADA_MS = 70      # (como mucho un trocito cada 70 ms: no se amontonan)

    def scrub(self, t: float):
        """🔊 Al ARRASTRAR la barra roja (en pausa) suena un trocito corto de lo que hay ahí, como en Resolve o
        Premiere: así se oyen los cortes sin darle a play. Con la mezcla en directo (la de siempre al reproducir)."""
        if self.playing or not self._live_on() or not scrub_activo():
            return
        import time as _time
        ahora = _time.monotonic()
        if ahora - getattr(self, "_scrub_ult", 0.0) < self.SCRUB_CADA_MS / 1000.0:
            self._scrub_pend = t                      # (el último que llegó suena en el siguiente hueco)
            if not getattr(self, "_scrub_armado", False):
                self._scrub_armado = True
                QTimer.singleShot(self.SCRUB_CADA_MS, self._scrub_pendiente)
            return
        self._scrub_ult = ahora
        self._plan_al_dia()
        live = self.live
        if not live.mixer.ready_at(t):                # (aún no decodificado: se pide y suena en el siguiente)
            live.prepare(t)
            return
        live.start(t)
        if getattr(self, "_scrub_fin", None) is None:
            self._scrub_fin = QTimer(self)
            self._scrub_fin.setSingleShot(True)
            self._scrub_fin.timeout.connect(self._scrub_parar)
        self._scrub_fin.start(self.SCRUB_MS)

    def _scrub_pendiente(self):
        self._scrub_armado = False
        t, self._scrub_pend = getattr(self, "_scrub_pend", None), None
        if t is not None:
            self.scrub(t)

    def _scrub_parar(self):
        if not self.playing and self.live is not None:
            self.live.stop()

    # ------------------------------------------------ ✂ ver un fotograma suelto (alargar un clip, como DaVinci)
    def mostrar_fotograma(self, media, src_t: float) -> bool:
        """El visor enseña el fotograma src_t (segundos DEL ARCHIVO) del medio, aunque no esté en la línea de tiempo:
        al alargar un clip arrastrando su borde, lo que se va a destapar. media: MediaItem o su id. Encima de todo, a
        pantalla completa (con bandas negras si no encaja). Barato: motor propio (el salto rápido y su caché; la copia
        ligera si la hay) y se puede llamar en cada movimiento del ratón (la última petición manda). En pausa; devuelve
        False si no puede (reproduciendo, medio de audio o que no existe). soltar_fotograma() vuelve al cabezal."""
        m = media if hasattr(media, "path") else self._proj().media.get(media)
        if self.playing or m is None or m.kind not in (KIND_VIDEO, KIND_IMAGE) or m.id in self.ctrl.missing:
            return False
        if m.kind == KIND_VIDEO:
            try:
                import av  # noqa: F401  (sin PyAV no hay motor propio: nada, en vez de una caja negra)
            except Exception:  # noqa: BLE001
                return False
        canvas = self.preview.canvas
        st = self.__dict__.get("_suelto")
        if st is None:
            caja = QGraphicsRectItem()
            caja.setPen(QPen(Qt.NoPen))
            caja.setBrush(QBrush(Qt.black))
            caja.setZValue(5000)                       # (encima de las capas, textos y subtítulos)
            canvas.scene().addItem(caja)
            img = QGraphicsPixmapItem(caja)
            img.setTransformationMode(Qt.SmoothTransformation)
            t = QTimer(self)
            t.setInterval(4)
            t.timeout.connect(self._suelto_mirar)
            st = self._suelto = {"caja": caja, "img": img, "timer": t, "src": None, "ruta": None, "pide": None}
        W, H = canvas.W, canvas.H
        st["caja"].setRect(QRectF(0, 0, W, H))
        st["caja"].show()
        if m.kind == KIND_IMAGE:
            st["timer"].stop()
            st["pide"] = None
            self._suelto_poner(QPixmap(m.path))
            return True
        ancho = max(160.0, canvas.transform().m11() * max(1.0, float(canvas.devicePixelRatioF())) * W)
        ruta = self.ctrl.preview_path(m, ancho)
        if st["ruta"] != ruta or st["src"] is None or st["src"].cerrado:     # (🔓 cerrada al soltar: otra)
            if st["src"] is not None:
                st["src"].close()
            from ..core.live_video import FrameSource
            st["src"], st["ruta"] = FrameSource(ruta), ruta
        sw, sh = max(1, m.width or 16), max(1, m.height or 9)
        k = min(1.0, ancho / sw, ancho * H / W / sh)
        w, h = max(2, int(sw * k) // 2 * 2), max(2, int(sh * k) // 2 * 2)
        st["src"].want(max(0.0, float(src_t)), False, (w, h))
        st["pide"] = max(0.0, float(src_t))
        if not self._suelto_mirar():
            st["timer"].start()
        return True

    def _suelto_mirar(self) -> bool:
        st = self.__dict__.get("_suelto")
        if st is None or st["pide"] is None or st["src"] is None:
            return True
        fr = st["src"].frame_at(st["pide"])
        if fr is None:
            if st["src"].error:                       # (no se puede decodificar: se queda lo que hubiera)
                st["timer"].stop()
                return True
            return False
        _pts, w, h, data = fr
        self._suelto_poner(QPixmap.fromImage(QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()))
        st["timer"].stop()
        return True

    def _suelto_poner(self, pm: QPixmap):
        st = self._suelto
        if pm.isNull():
            return
        W, H = self.preview.canvas.W, self.preview.canvas.H
        k = min(W / pm.width(), H / pm.height())
        st["img"].setPixmap(pm)
        st["img"].setTransform(QTransform.fromScale(k, k))
        st["img"].setPos((W - pm.width() * k) / 2, (H - pm.height() * k) / 2)

    def soltar_fotograma(self):
        """Fin de mostrar_fotograma: el visor vuelve a enseñar el cabezal (el archivo queda abierto un rato: si vuelves
        a alargar, sale de su caché)."""
        st = self.__dict__.get("_suelto")
        if st is None:
            return
        st["timer"].stop()
        st["pide"] = None
        st["caja"].hide()
        if st["src"] is not None:
            st["src"].trim(3)
        self._sync()

    def step(self, frames: int):
        self.pause()
        self.seek(self.time + frames / max(1.0, self._proj().fps))

    def _tick(self):
        with self._proj().lectura(getattr(self.ctrl, "rev", None)):    # ⚡ duración y clips, una vez
            self._tick_todo()

    def _tick_todo(self):
        t = self._t0 + self._clock.elapsed() / 1000.0 * self.rate
        total = self._proj().duration()
        if self.loop and self._stop_at is None:      # bucle: el tramo marcado (o todo el video)
            a, b = self._proj().marked_range() or (0.0, total)
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
            self._live_check += 1
            if self._live_check % 30 == 0 and self._live_on():        # (cada ~1 s)
                oido = self.live.position()
                if oido is not None and abs(oido - t) > 0.08:          # (margen: sin resincronizar de más)
                    self.live.start(t)
        self.time_changed.emit(self.time)
        self._arm_cut()

    def _on_cut(self):
        if self.playing:
            self._tick()

    def _arm_cut(self):
        """Corte a tiempo: si el próximo inicio/fin de clip de video cae antes del siguiente _tick (30 ms), se
        programa un _tick justo en ese milisegundo. Así el plano precargado entra en su fotograma y no hay que
        decodificar en el corte. Solo con reproducción hacia delante."""
        if not self.playing or self.rate <= 0 or self._cut_timer.isActive():
            return
        k = bisect.bisect_right(self._bounds, self.time + 1e-4)
        if k >= len(self._bounds):
            return
        dt = (self._bounds[k] - self.time) / self.rate
        if dt * 1000 < self._timer.interval() + 5:
            self._cut_timer.start(math.ceil(dt * 1000) + 1)

    def refresh_sources(self):
        """Se crearon copias ligeras (proxies): el visor pasa a usarlas."""
        from ..core import proxies as _PX
        _PX.forget_cache()
        self._sync()

    def _recycle(self):
        # Reproductores de pistas que ya no están: se APARTAN (en pausa) y los reutilizan las pistas nuevas. Nunca
        # se apagan durante la sesión: QMediaPlayer.stop() a veces se bloquea para siempre (congelaba Reclaimer al
        # cambiar de proyecto o de pestaña).
        spare_a = self.__dict__.setdefault("_spare_audio", [])
        spare_v = self.__dict__.setdefault("_spare_video", [])
        canvas = self.preview.canvas
        valid = {t.id for t in self._proj().tracks if t.kind == TRACK_AUDIO}
        for tid in list(self._audio):
            if tid not in valid:
                lane = self._audio.pop(tid)
                lane.park()
                spare_a.append(lane)
        vvalid = {t.id for t in self._proj().tracks if t.kind == TRACK_VIDEO}
        va = self.__dict__.get("_vaudio") or {}
        for tid in [t for t in va if t not in vvalid]:     # (🎞 su pista ya no existe: su audio auxiliar, fuera)
            va.pop(tid).park()
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
        p = self._proj()
        nuevos = [m.path for m in p.media.values() if m.kind in (KIND_VIDEO, KIND_AUDIO) and m.path not in _CODEC]
        if nuevos and _hay_pyav():
            for ruta in nuevos:            # ⚡ el códec de cada video, mirado ya en segundo plano (un AV1 va con el
                _codec_de(ruta)            # motor propio desde su primer fotograma, sin que Qt lo intente antes), y
                #                            dónde empieza cada archivo (exportar con miles de piezas: ffmpeg_export)
        self.preview.canvas.set_canvas_size(p.width, p.height)
        self.preview.fps = p.fps
        self.preview.set_title(p.name)
        vt = {t.id for t in p.tracks if t.kind == TRACK_VIDEO}
        self._bounds = sorted({round(x, 4) for c in p.clips.values() if c.track_id in vt and c.enabled
                               for x in (c.start, c.end)})
        # Tramos de voz y subtítulos: solo se recalculan si cambió algo que los afecta, cada uno con SU huella (⚡ 21/11,
        # ronda 2). Antes era una sola huella con todos los medios de las pistas de audio: mover un plano de V1 (su sonido
        # va vinculado en otra pista de audio) recalculaba la voz de los 65 min en cada edición.
        if self._cue_key is None:
            self.__dict__.pop("_voz_key", None)          # (la transcripción cambió: las dos cosas, otra vez)
            self.__dict__.pop("_subs_key", None)
            self._cue_key = True
        if not any(t.duck_db is not None for t in p.tracks if t.kind == TRACK_AUDIO):
            self._speech = []          # ⚡ (22/11) sin ninguna pista que baje al hablar, los tramos de voz no hacen falta
            self._voz_key = None       #   (se calculan cuando haya una; antes, ~30 ms en cada edición de la narración)
        else:
            clave_voz = self._huella_voz(p)
            if clave_voz != self.__dict__.get("_voz_key"):
                self._voz_key = clave_voz
                if self.playing:
                    self._speech = audio_fx.speech_intervals(p)   # para bajar la música cuando hablas
                else:                  # (en pausa no baja nada: se calcula al quedarse quieto o al sonar)
                    self._voz_pend = True
                    self._plan_sucio = True
        clave_subs = self._huella_subs(p)
        if clave_subs != self.__dict__.get("_subs_key"):
            self._subs_key = clave_subs
            self._cues = styled_cues(p) if p.subtitles.enabled else []
            self._cue_starts = [c.start for c in self._cues]
        if self.playing or self.live is None:
            self._live_plan()
        else:                      # ⚡ (22/11) en pausa, la mezcla en directo se prepara al quedarse quieto (o al dar a ▶
            self._plan_sucio = True  #  / scrub): editar ya no espera ~9 ms por los ~850 clips con sonido
            tp = self.__dict__.get("_t_plan")
            if tp is None:
                tp = self._t_plan = QTimer(self)
                tp.setSingleShot(True)
                tp.setInterval(250)
                tp.timeout.connect(self._plan_al_dia)
            tp.start()
        self._sync()
        self._programar_soltar_sin_uso()

    @property
    def _live_ids(self) -> set:
        """Los clips que suenan desde la mezcla en directo (al día: si una edición la dejó pendiente, se rehace)."""
        self._plan_al_dia()
        return self._ids_vivos

    @_live_ids.setter
    def _live_ids(self, v):
        self._ids_vivos = v

    def _plan_al_dia(self):
        """La mezcla en directo (y los tramos de voz) al día si una edición los dejó pendientes: antes de sonar."""
        if self.__dict__.pop("_voz_pend", False):
            self._speech = audio_fx.speech_intervals(self._proj())
        if self.__dict__.pop("_plan_sucio", False):
            self._live_plan()

    @staticmethod
    def _huella_voz(p) -> tuple:
        """De qué dependen los tramos de voz (audio_fx.speech_intervals): las pistas de voz (de audio, sin bajar como
        música y sin silenciar), sus medios de audio con transcripción o de «Narración» y dónde están TODOS los trozos de
        esos medios (en cualquier pista: el índice de palabras los usa todos)."""
        voz_t = {t.id for t in p.tracks if t.kind == TRACK_AUDIO and t.duck_db is None and not t.muted}
        mids = set()
        for c in p.clips.values():
            if c.track_id in voz_t:
                mids.add(c.media_id)
        medios = []
        for mid in mids:
            m = p.media.get(mid)
            if m is not None and m.kind == KIND_AUDIO and (mid in p.transcripts or m.category == "Narración"):
                medios.append((mid, m.category, id(p.transcripts.get(mid))))
        voz_m = {x[0] for x in medios}
        return (id(p), tuple(sorted(voz_t)), tuple(sorted(medios)),
                tuple((c.id, c.media_id, c.track_id, c.start, c.source_in, c.duration, c.speed, c.reverse, c.enabled)
                      for c in p.clips.values() if c.media_id in voz_m))

    @staticmethod
    def _huella_subs(p) -> tuple:
        """De qué dependen los subtítulos (styled_cues): su estilo y los trozos de su narración (y los cortes de plano si
        llevan «golpe final»). Apagados: nada."""
        st = p.subtitles
        if not st.enabled:
            return ("apagados", id(p))
        from ..core import subtitles as _SUBS
        mid = st.media_id
        return (id(p), repr(st), repr(p.tracks), id(p.transcripts.get(mid)),
                tuple(_SUBS.cut_times(p)) if getattr(st, "fx_punch", False) else None,
                tuple((c.id, c.track_id, c.start, c.source_in, c.duration, c.speed, c.reverse, c.enabled)
                      for c in p.clips.values() if c.media_id == mid))

    # -------------------------------------------------------- 🔓 soltar archivos (core/soltar_archivos.py)
    SIN_USO_MS = 400       # tras cambiar el proyecto (borrar clips, otro proyecto): se sueltan los archivos que sobran

    def _lanes_video(self) -> list:
        """Todas las pistas de video del visor: las de ahora, las apartadas y las de Qt guardadas."""
        lanes = list(self._vlanes.values())
        lanes += [ln for _l, ln in (self.__dict__.get("_spare_video") or []) if ln is not None]
        lanes += list((self.__dict__.get("_qt_lanes") or {}).values())
        return lanes

    def _lectores_qt(self) -> list:
        """Todos los reproductores de Qt (_Lane) del visor: de video, de audio y los auxiliares de audio."""
        out = []
        for lane in self._lanes_video():
            out += list(getattr(lane, "slots", []) or [])
        out += list(self._audio.values()) + list(self.__dict__.get("_spare_audio") or [])
        out += list((self.__dict__.get("_vaudio") or {}).values())
        return out

    def _propios(self) -> list:
        """Las partes con el motor propio (_OwnVideoLane) de cada pista."""
        out = []
        for lane in self._lanes_video():
            if isinstance(lane, _OwnVideoLane):
                out.append(lane)
            elif isinstance(lane, _MixedVideoLane) and lane.own is not None:
                out.append(lane.own)
        return out

    def rutas_abiertas(self, suelto_visible: bool = True) -> set[str]:
        """Los archivos que el visor tiene abiertos ahora (rutas normalizadas). Sin las transiciones renderizadas (son de
        la caché, no medios)."""
        from ..core.live_video import clave_ruta
        rutas = [s.path for s in self._lectores_qt() if getattr(s, "path", None)]
        for own in self._propios():
            rutas += own.rutas()
        st = self.__dict__.get("_suelto")
        if st is not None and st["src"] is not None and not st["src"].cerrado and st["ruta"] \
                and (suelto_visible or (st["pide"] is None and not st["caja"].isVisible())):
            rutas.append(st["ruta"])
        return {clave_ruta(r) for r in rutas if r}

    def soltar_rutas(self, claves) -> list[str]:
        """🔓 Suelta esos archivos (claves = rutas normalizadas o carpetas): motor propio, fotograma suelto,
        transiciones y reproductores de Qt. Sin esperar (core/soltar_archivos espera a todos juntos). Se vuelven a abrir
        solos cuando hagan falta. Devuelve los que tenía abiertos."""
        from ..core.live_video import _toca, clave_ruta
        claves = set(claves or ())
        hechos: list[str] = []
        if not claves:
            return hechos
        for own in self._propios():
            hechos += own.soltar_rutas(claves)
        st = self.__dict__.get("_suelto")
        if st is not None and st["ruta"] and _toca(clave_ruta(st["ruta"]), claves):
            st["timer"].stop()
            if st["src"] is not None:
                st["src"].close()
                hechos.append(st["ruta"])
            st["src"], st["ruta"], st["pide"] = None, None, None
        zp = self.__dict__.get("zones")
        fuentes = getattr(zp, "_sources", None) if zp is not None else None
        if isinstance(fuentes, dict):
            for pth in [p for p in fuentes if _toca(clave_ruta(p), claves)]:
                fuentes.pop(pth).close()
                hechos.append(pth)
        for s in self._lectores_qt():
            pth = getattr(s, "path", None)
            if not pth or not _toca(clave_ruta(pth), claves):
                continue
            try:
                s.player.setSource(QUrl())
            except RuntimeError:
                continue
            s.path, s.loaded = None, False
            hechos.append(pth)
        return hechos

    def _programar_soltar_sin_uso(self):
        t = self.__dict__.get("_sin_uso_timer")
        if t is None:
            t = self._sin_uso_timer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(self.SIN_USO_MS)
            t.timeout.connect(self.soltar_sin_uso)
        t.start()

    def soltar_sin_uso(self) -> list[str]:
        """🔓 Los archivos que el visor tiene abiertos y que ya no usa ningún clip del proyecto (los borraste, cambiaste
        de proyecto): se sueltan ya (antes se quedaban abiertos y Windows no dejaba borrarlos ni moverlos). Los que
        siguen en la línea de tiempo, no (los de debajo del cabezal y los cercanos se quedan listos)."""
        try:
            abiertas = self.rutas_abiertas(suelto_visible=False)
        except RuntimeError:
            return []
        if not abiertas:
            return []
        from ..core.live_video import clave_ruta
        p = self._proj()
        medios = {m.id: m for m in (p.media_of(c) for c in p.clips.values()) if m is not None and m.path}
        usadas = {clave_ruta(m.path) for m in medios.values()}
        if abiertas - usadas:                 # (¿alguna es una copia ligera de un medio que sí se usa?)
            from ..core.proxies import proxy_path
            for m in medios.values():
                if m.kind == KIND_VIDEO:
                    usadas.update(clave_ruta(proxy_path(m.path, lv)) for lv in ("half", "quarter"))
        sobran = abiertas - usadas
        return self.soltar_rutas(sobran) if sobran else []

    # -------------------------------------------------------- 🎧 audio en directo
    def _own_video_on(self) -> bool:
        return getattr(self, "_own_video", False)

    def _new_vlane(self, layer):
        """🎞 Pista de video: con el motor propio (beta) o con los reproductores de Qt de siempre."""
        if self._own_video_on():
            return _OwnVideoLane(self, layer)
        return self._qt_vlane(layer)

    def _qt_vlane(self, layer):
        """La pista con reproductores de Qt de esa capa: la de antes si la hay (se vuelve a conectar al visor)."""
        guardadas = self.__dict__.setdefault("_qt_lanes", {})
        lane = guardadas.pop(id(layer), None)
        if lane is not None:
            for s, v in zip(lane.slots, layer.videos):
                s.player.setVideoOutput(v)
            return lane
        # (la mixta siempre que haya PyAV: con sus dos interruptores apagados se porta como la de siempre)
        return _MixedVideoLane(self, layer) if _hay_pyav() else _VideoLane(self, layer)

    def _motor_mixto(self):
        """⚡ Un interruptor del motor propio cambió (menú del visor): se aplica al momento a las pistas mixtas."""
        lanes = list(self._vlanes.values()) + [ln for _l, ln in (self.__dict__.get("_spare_video") or [])]
        for lane in lanes:
            if not isinstance(lane, _MixedVideoLane):
                continue
            lane.pausa_propia = pausa_con_motor_propio()
            lane.pesados_on = pesados_con_motor_propio()
            lane._pesado.clear()
            if lane.modo == "propio" and lane.own is not None:
                lane.own.soltar()
                lane.own.idle()
                lane.modo = "qt"
                lane.layer.set_active(lane.active)
        self._sync()

    def _guardar_qt(self, lane):
        if isinstance(lane, _MixedVideoLane) and lane.own is not None:
            lane.own.park()                    # (su parte con el motor propio: hilos parados)
            lane.modo = "qt"
        for s in lane.slots:
            s.idle()
            s.player.setVideoOutput(None)
        self.__dict__.setdefault("_qt_lanes", {})[id(lane.layer)] = lane

    def shutdown_video(self):
        """Al cerrar: los hilos del motor de video, parados (sin dejar a FFmpeg a medias)."""
        if self.__dict__.get("zones") is not None:
            self.zones.shutdown()
        st = self.__dict__.get("_suelto")
        if st is not None and st["src"] is not None:
            st["src"].close(0.5)                       # (✂ el del fotograma suelto)
        for lane in list(self._vlanes.values()) + [ln for _l, ln in (self.__dict__.get("_spare_video") or [])]:
            if isinstance(lane, _OwnVideoLane):
                lane.park(0.5)
            elif isinstance(lane, _MixedVideoLane) and lane.own is not None:
                lane.own.park(0.5)
        for ln in list(self.__dict__.get("_vaudio", {}).values()):
            ln.park()

    def set_own_video(self, on: bool):
        """Reproducción → «🎞 Video con motor propio». Se aplica al momento (las pistas se rehacen)."""
        from PySide6.QtCore import QSettings as _QS
        _QS("EditorIA", "EditorIA").setValue("video/motor_propio", "true" if on else "false")
        if bool(on) == self._own_video_on():
            return
        self._own_video = bool(on)
        for tid, lane in list(self._vlanes.items()):
            if isinstance(lane, _VideoLane):
                self._guardar_qt(lane)            # (sus reproductores dejan de pintar en el visor; se reutilizan)
            else:
                lane.park()
        self._vlanes.clear()
        for k, (layer, lane) in enumerate(self.__dict__.get("_spare_video") or []):
            if lane is not None:
                if isinstance(lane, _VideoLane):
                    self._guardar_qt(lane)
                else:
                    lane.park()
                self._spare_video[k] = (layer, None)
        for ln in self.__dict__.get("_vaudio", {}).values():
            ln.idle()
        self._timer.setInterval(15 if self._own_video else 30)
        self._sync()

    def _crear_live(self):
        """Abre la mezcla en directo (None si no hay tarjeta o falla: el visor usa sus reproductores)."""
        try:
            from .live_audio import LiveAudio
            live = LiveAudio(self)
        except Exception:  # noqa: BLE001
            return None
        if not live.ok:
            live.close()
            return None
        live.mixer.monitor = _ganancia_escucha()      # (🔊 volumen de escucha de la barra)
        from PySide6.QtWidgets import QApplication as _QA
        if _QA.instance() is not None:
            _QA.instance().aboutToQuit.connect(live.close)
        import atexit
        atexit.register(live.close)                  # (también si se sale sin el bucle de Qt: pruebas, cierres raros)
        return live

    @property
    def mute_all(self) -> bool:
        return getattr(self, "_mute_all", False)

    @mute_all.setter
    def mute_all(self, on: bool):
        """🎙 Grabando la voz en off: el proyecto no suena (tampoco la mezcla en directo)."""
        self._mute_all = bool(on)
        live = getattr(self, "live", None)
        if live is not None:
            live.mixer.plan.mute = self._mute_all

    def set_live_audio(self, on: bool):
        """Reproducción → «🎧 Audio en directo». Apagado: suenan los reproductores de siempre (sin EQ al reproducir)."""
        from PySide6.QtCore import QSettings as _QS
        _QS("EditorIA", "EditorIA").setValue("audio/en_directo", "true" if on else "false")
        if not on and self.live is not None:
            self.live.stop()
            self._live_off = True
        else:
            self._live_off = False
            if on and self.live is None:
                self.live = self._crear_live()
                if self.live is None:
                    self.ctrl.message.emit("🎧 No pude abrir la salida de audio: suenan los reproductores de siempre "
                                           "(el ecualizador se oye al exportar o con «Escuchar con EQ»).")
            self._live_plan()
            if self.playing and self._live_on():
                self.live.start(self.time)
        self._sync()

    def _live_on(self) -> bool:
        return self.live is not None and not getattr(self, "_live_off", False) and self.rate == 1.0

    def _live_plan(self):
        """Qué clips suenan desde la mezcla en directo (velocidad normal, sin reversa) y con qué ajustes."""
        if self.live is None:
            self._ids_vivos = set()
            return
        import copy as _copy
        from ..core import live_mix as LM
        from ..core.model import Clip, _getter
        p = self._proj()
        fuentes, ids = [], set()
        # ⚡ (21/11, ronda 2) la Source de un clip que no cambió (mismos valores, mismo archivo y pista) es la de antes:
        # con 2500 clips ya no se copian ~850 en cada edición; y los clips de cada pista, ordenados una vez (lectura)
        previas = self.__dict__.get("_fuentes_previas") or {}
        nuevas: dict = {}
        leer, _nombres = _getter(Clip)
        with p.lectura(getattr(self.ctrl, "rev", None)):
            for tr in p.tracks:
                if tr.kind not in (TRACK_AUDIO, TRACK_VIDEO):
                    continue
                audible = p.audible(tr)
                for c in p.clips_on(tr.id):
                    m = p.media_of(c)
                    if not c.enabled or m is None or m.id in self.ctrl.missing:
                        continue
                    if tr.kind == TRACK_VIDEO and (c.link or m.kind != KIND_VIDEO or not m.has_audio):
                        continue
                    if tr.kind == TRACK_AUDIO and not (m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)):
                        continue
                    if abs((c.speed or 1.0) - 1.0) > 1e-6 or c.reverse:
                        continue                   # (cámara lenta, rápida o reversa: su reproductor de siempre)
                    vals = leer(c)
                    extra = (m.path, tr.duck_db if tr.kind == TRACK_AUDIO else None, audible, (m.channels or 2) == 1)
                    tipos = tuple(map(type, vals))
                    hit = previas.get(c.id)
                    if hit is not None and hit[1] == extra and hit[2] == tipos and hit[0] == vals:
                        src = hit[3]
                    else:
                        src = LM.Source(key=c.id, path=m.path, start=c.start, end=c.end, src_in=c.source_in,
                                        clip=_copy.copy(c), eq=c.eq, pan=float(c.pan or 0.0),
                                        duck_db=extra[1], audible=audible, mono=extra[3])
                    nuevas[c.id] = (vals, extra, tipos, src)
                    fuentes.append(src)
                    ids.add(c.id)
        self._fuentes_previas = nuevas
        self._ids_vivos = ids
        self.live.set_plan(LM.Plan(sources=fuentes, speech=list(self._speech), mute=self.mute_all))
        if not self.playing:
            self.live.prepare(self.time)

    # -------------------------------------------------------- sincronizar
    def _sync(self):
        with self._proj().lectura(getattr(self.ctrl, "rev", None)):    # ⚡ clips ordenados una vez
            self._sync_todo()
        cv = getattr(self.preview, "canvas", None)        # ⤧ el recuadro sigue a lo que se ve (la capa ya colocada)
        if cv is not None and cv._tf and cv._tf_drag is None:
            cv._update_tf_overlay()                       # (sin cambios, set_rect no repinta)
        zp = self.__dict__.get("zones")
        if zp is not None:
            try:
                zp.show_at(self.time, self.playing)
            except Exception:  # noqa: BLE001 - la vista previa de transiciones nunca para el visor
                zp.hide()

    def _sync_todo(self):
        self._recycle()               # pistas nuevas: con los reproductores apartados (nunca se crean de más)
        p = self._proj()
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
        # 📝 Notas con fondo borroso alrededor: el recuadro de ahora (lo desenfoca cada capa de video, en LookEffect)
        from ..core import nota_texto as _NT
        notes = []
        for tr in p.tracks:
            if tr.kind == TRACK_TEXT and not tr.hidden:
                tc = p.clip_at(tr.id, t)
                if tc is not None and tc.enabled and tc.text and tc.text.get("zone_blur"):
                    z = _NT.zone_now(tc.text, t - tc.start, tc.duration, self.preview.canvas.W,
                                     self.preview.canvas.H)
                    if z is not None and z["alpha"] > 0.002:
                        notes.append(z)
        self._notes_now = notes
        self._under_now = max(under, 1.0 if notes else 0.0)   # (⧉ la transición renderizada no lleva ese desenfoque)

        # Video: una capa por pista (de arriba a abajo). Si una capa tapa toda la pantalla,
        # las de debajo no se ven y no hace falta reproducirlas.
        canvas = self.preview.canvas
        vtracks = [tr for tr in p.tracks if tr.kind == TRACK_VIDEO]
        covered = False
        cover_end = 0.0                # cuándo termina lo que tapa la pantalla entera
        post: list = []                # 🎨 capas de ajuste de encima (se aplican a las capas de debajo)
        from ..core import generators as _GEN
        for depth, tr in enumerate(vtracks):
            layer = canvas.layer(tr.id)
            lane = self._vlanes.get(tr.id)
            c = None if (covered or tr.hidden) else p.clip_at(tr.id, t)
            m = p.media_of(c) if c else None
            va0 = self.__dict__.get("_vaudio")
            if va0 and tr.id in va0 and (c is None or not c.enabled or m is None or m.kind != KIND_VIDEO):
                va0[tr.id].idle()                 # (sin clip con sonido: el reproductor de audio auxiliar, quieto)
            if c is None or not c.enabled or m is None or m.id in self.ctrl.missing or m.kind == KIND_AUDIO:
                layer.hide()
                if lane:
                    lane.idle()
                self._prepare_ahead(tr, layer, t, covered, cover_end)   # sin trabas en el corte siguiente
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
                    lane = self._vlanes[tr.id] = self._new_vlane(layer)
                from ..core import black_bars as _BB
                bars = _BB.of(box_now)                # ▭ sin barras negras: se encuadra con el tamaño sin ellas
                sw_, sh_ = _BB.size_without(m, bars)
                layer.place(canvas.W, canvas.H, box_now, sw_, sh_, zoom, None, z_value, bars)
                vol = 0.0 if (not p.audible(tr) or c.link) else curves.gain(c, t)   # vinculado: suena desde su pista de audio
                if self._live_on() and c.id in self._ids_vivos:
                    vol = 0.0                  # (🎧 suena por la mezcla en directo)
                if self.mute_all:          # 🎙 grabando la voz: el proyecto no suena (no se cuela en el micro)
                    vol = 0.0
                run, rate = self._lane_motion(c)
                max_w = self._view_w(layer) * max(1.0, zoom[0])          # ancho en pantalla (px del visor)
                vpath = self._pick_path(tr.id, m, max_w)
                if isinstance(lane, _OwnVideoLane):
                    if lane.failed(vpath):            # (PyAV no lo abre: esta pista vuelve a los reproductores)
                        lane.park()
                        lane = self._vlanes[tr.id] = self._qt_vlane(layer)
                    else:
                        lane.set_target(max_w, sw_, sh_, vpath)       # (max_w ya va en píxeles reales)
                propio = isinstance(lane, _OwnVideoLane) or (isinstance(lane, _MixedVideoLane)
                                                            and lane.clasificar(vpath, m))
                if isinstance(lane, _MixedVideoLane):
                    lane.set_target(max_w, sw_, sh_, vpath)           # ⚡ motor propio: al tamaño del visor
                if vpath in NO_DECODIFICA and not propio:
                    lane.idle()                    # (🎞 no puede con él: ni lo intenta; se ven fotogramas sueltos)
                else:
                    lane.drive(vpath, src_t, run, vol if run else 0.0, rate, m.fps or p.fps)
                propio = propio and not (isinstance(lane, _MixedVideoLane) and not lane.propio(vpath))
                # 🎞 fotograma suelto solo si nadie puede con el archivo (con el motor propio, se ve de verdad)
                self._poster(layer, m, "" if propio else vpath, src_t)
                # 🎞 el motor propio no suena: si la mezcla en directo no cubre este clip (J/L rápido, velocidad,
                # audio en directo apagado), su sonido va por un reproductor solo de audio
                va = self.__dict__.setdefault("_vaudio", {})
                if propio and vol > 0 and run and m.has_audio \
                        and not (self._live_on() and c.id in self._ids_vivos):
                    al = va.get(tr.id)
                    if al is None:
                        al = va[tr.id] = _Lane(self)
                    al.drive(self.ctrl.preview_path(m), src_t, run, vol, rate)
                elif tr.id in va:
                    va[tr.id].idle()
                # El siguiente plano de la pista, preparado antes de que llegue (cortes sin trabas)
                nxt = self._next_clip(tr.id, c)
                if nxt is not None and nxt.start - t < 2.5:
                    nm = p.media_of(nxt)
                    if nm is not None and nm.kind == KIND_VIDEO and nm.id not in self.ctrl.missing:
                        npath = self.ctrl.preview_path(nm, max_w)
                        if isinstance(lane, _MixedVideoLane):
                            lane.clasificar(npath, nm)
                        if isinstance(lane, (_OwnVideoLane, _MixedVideoLane)):
                            nsw, nsh = _BB.size_without(nm, _BB.of(box_now))
                            lane.set_target(max_w, nsw, nsh, npath)
                        lane.preload(npath, nxt.src_at(0.0), nm.fps or p.fps)
            adj = _GEN.is_adjust(m)
            layer.set_color(None if (self.color_bypass or adj) else c.color)
            layer.set_post([] if adj else list(post))
            layer.set_blend(c.blend, 1.0 if adj else curves.opacity(c, t, m.kind == KIND_IMAGE))
            if adj:             # 🎨 su efecto va a lo de debajo; ella solo pone lo de pantalla entera (viñeta, destello)
                fx_adj = {k: v for k, v in (c.fx or {}).items() if k in ("vignette", "flash", "lines")}
                layer._note_zones = []
                layer.set_effects(fx_adj, t - c.start, c.duration, t - c.start)
                mix = curves.opacity(c, t, True) * effects.fade_gain(c.fx, t - c.start, c.duration)
                pfx = dict(c.fx or {})
                fs = effects.focus_sigma(c.fx, t - c.start, min(canvas.W, canvas.H))
                if fs > 0:
                    pfx["_focus_px"] = fs
                post.append((None if self.color_bypass else c.color, pfx, mix))
                continue
            fx_now = transitions.preview_fx(p, c)
            if under > 0.01:
                fx_now = dict(fx_now or {}, blur=max(float((fx_now or {}).get("blur", 0) or 0), round(under, 2)))
            layer._note_zones = notes
            layer.set_effects(fx_now, t - c.start, c.duration, c.src_at(t - c.start))
            layer.set_decor(c.fx, t - c.start, canvas.W, canvas.H)
            # Solo tapa lo de debajo si es opaco de verdad: con ✂ recorte de sujeto, pantalla verde, opacidad,
            # mezcla o recorte, la pista de debajo se tiene que ver (la misma regla que al exportar)
            if _full_frame(p, c) and zoom[0] >= 0.999:
                covered = True
                cover_end = c.end

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
            if self._live_on() and c.id in self._ids_vivos:
                if lane:
                    lane.idle()                # (🎧 suena por la mezcla en directo, con su EQ)
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

    def _view_w(self, layer) -> float:
        """Ancho que ocupa la capa en el visor, en píxeles REALES de pantalla (sin el zoom del clip): el mayor de las
        vistas que la enseñan (el visor y, si está, el de la segunda pantalla), con la escala de la interfaz (dpr)."""
        canvas = self.preview.canvas
        best = 0.0
        for v in canvas.scene().views():
            try:
                if v is not canvas and not v.isVisible():
                    continue
                best = max(best, v.transform().m11() * max(1.0, float(v.devicePixelRatioF())))
            except RuntimeError:
                continue
        if best <= 0:
            best = canvas.transform().m11() * max(1.0, float(canvas.devicePixelRatioF()))
        return best * layer.box.rect().width()

    def _pick_path(self, track_id: str, m, max_w: float) -> str:
        """Archivo del visor para una pista. Con un margen del 10 % para no recargar al redimensionar un poco.
        Un archivo que el reproductor no decodifica (NO_DECODIFICA) usa cualquier copia ligera que ya exista."""
        prev = self._last_w.get(track_id)
        if prev and abs(max_w - prev) <= 0.1 * prev:
            max_w = prev
        self._last_w[track_id] = max_w
        path = self.ctrl.preview_path(m, max_w)
        if path == m.path and (path in NO_DECODIFICA or (path in LENTOS and self.playing)):
            from ..core.proxies import has_proxy, proxy_path
            for lv in ("half", "quarter"):
                if has_proxy(m.path, lv):
                    return proxy_path(m.path, lv)
        return path

    def _al_no_decodificar(self, path: str):
        """El reproductor no puede con ese archivo: se pide su copia ligera (aunque la calidad sea «Completa») y el
        visor se pone al día (enseña fotogramas sueltos mientras tanto)."""
        try:
            win = self.preview.window()
        except RuntimeError:
            return
        px = getattr(win, "proxies", None)
        if px is not None:
            QTimer.singleShot(0, px.ensure)
        sb = getattr(win, "statusBar", None)
        if callable(sb):
            sb().showMessage(f"🎞 «{os.path.basename(path)}» no se puede reproducir tal cual (formato AV1 u otro sin "
                             "aceleración): preparando su copia ligera; mientras, se ven fotogramas sueltos.", 10000)
        QTimer.singleShot(0, self._sync)

    def _al_lento(self, path: str):
        """⚡ Este equipo no llega a tiempo con ese archivo: se prepara su copia ligera (en segundo plano, con prioridad
        baja) y se usa al reproducir en cuanto exista (en pausa, el original: misma calidad al parar)."""
        try:
            win = self.preview.window()
        except RuntimeError:
            return
        px = getattr(win, "proxies", None)
        if px is not None:
            QTimer.singleShot(0, px.ensure)
        sb = getattr(win, "statusBar", None)
        if callable(sb):
            sb().showMessage(f"⚡ «{os.path.basename(path)}» va justo en este equipo: preparando su copia ligera para que "
                             "se reproduzca fluido (exportar sigue usando el original).", 10000)

    def _poster(self, layer, m, path: str, src_t: float):
        """🎞 Fotograma suelto para un archivo que el reproductor no decodifica (se pide en segundo plano; si mientras
        tanto el cabezal se movió, al acabar se pide el último)."""
        st = layer.__dict__.setdefault("_poster_st", {"job": None, "want": None, "have": None, "pm": None})
        if path not in NO_DECODIFICA:
            st["want"] = None
            if layer.poster.isVisible():
                layer.poster.hide()
            return
        key = (path, int(round(src_t * (m.fps or 30.0))))
        st["want"] = (key, path, src_t)
        if st["have"] is not None and st["have"][0] != path and layer.poster.isVisible():
            layer.poster.hide()                    # (otro archivo: el fotograma de antes no vale)
        if st["have"] == key and st["pm"] is not None:
            layer.set_poster(st["pm"])             # (siempre: la caja pudo moverse o cambiar de tamaño)
            return
        if st["job"] is None:
            self._poster_job(layer)

    def _poster_job(self, layer):
        from .jobs import BackgroundJob
        st = layer._poster_st
        if st["want"] is None:
            return
        key, path, t = st["want"]
        job = BackgroundJob(lambda _p, _c, a=path, b=t: _fotograma(a, b), self)
        st["job"] = job

        def listo(img, key=key):
            st["job"] = None
            if st["want"] is None:                 # (ya se ve otra cosa: copia ligera, otro clip…)
                return
            if img is not None and not img.isNull() and st["want"][1] == key[0]:
                st["pm"], st["have"] = QPixmap.fromImage(img), key
                layer.set_poster(st["pm"])
            if st["want"][0] != key:
                self._poster_job(layer)

        def fallo(_msg):
            st["job"] = None
        job.done.connect(listo)
        job.failed.connect(fallo)
        job.start()

    def _first_clip_from(self, track_id: str, t: float):
        best = None
        for o in self._proj().clips_on(track_id):
            if o.enabled and o.start >= t - 1e-3 and (best is None or o.start < best.start):
                best = o
        return best

    def _prepare_ahead(self, tr, layer, t: float, covered: bool, cover_end: float):
        """Pista sin clip ahora (o tapada): si lo siguiente que se verá en ella llega en menos de 2,5 s, su
        reproductor se prepara ya, pausado en su punto (así el corte no se traba)."""
        if tr.hidden:
            return
        p = self._proj()
        if covered:                       # lo de debajo aparece cuando termina lo que tapa
            if cover_end - t >= 2.5:
                return
            at = cover_end
            c2 = p.clip_at(tr.id, at)
        else:
            c2 = self._first_clip_from(tr.id, t)
            if c2 is None or c2.start - t >= 2.5:
                return
            at = c2.start
        if c2 is None or not c2.enabled:
            return
        m2 = p.media_of(c2)
        if m2 is None or m2.kind != KIND_VIDEO or m2.id in self.ctrl.missing:
            return
        lane = self._vlanes.get(tr.id)
        if lane is None:
            lane = self._vlanes[tr.id] = self._new_vlane(layer)
        ppath = self.ctrl.preview_path(m2, self._view_w(layer))
        if isinstance(lane, _MixedVideoLane):
            lane.clasificar(ppath, m2)
        if isinstance(lane, (_OwnVideoLane, _MixedVideoLane)):
            lane.set_target(self._view_w(layer), m2.width, m2.height, ppath)
        lane.preload(ppath, c2.src_at(at - c2.start), m2.fps or p.fps)

    def _lane_motion(self, c) -> tuple[bool, float]:
        """¿El reproductor de este clip avanza solo, y a qué velocidad? Hacia atrás, congelado o con J
        se coloca fotograma a fotograma (sin sonido)."""
        rate = self.rate * c.speed
        if not self.playing or rate <= 0 or c.reverse:
            return False, 1.0
        return True, rate
