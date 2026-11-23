"""
🎞 «Animar imagen»: pones una imagen (un personaje, un arma, un logo…) con una animación sencilla.

  · A la izquierda, la vista previa: el fotograma del visor de fondo, el recuadro punteado es DÓNDE va (arrástralo;
    la esquina de abajo a la derecha cambia el tamaño) y encima se ve la animación en bucle.
  · A la derecha: qué imagen, qué animación (o «según lo que digo»), cuánto dura y DÓNDE se pone: en el cabezal o
    en los momentos en que dices una palabra clave (los marcas en la lista).
Al aceptar, controller.add_animated_images lo pone todo en un paso de Ctrl+Z. Las animaciones son las de
core/image_anim.py (fotogramas clave de posición y tamaño, opacidad y temblor): lo que ves es lo que se exporta.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
                               QVBoxLayout)

from ..core import effects, image_anim, transform
from ..core.model import KIND_IMAGE
from .common import fmt_time

VW = 640               # ancho de la vista previa (px)
AUTO = "auto"          # «según lo que digo»


class _Caja(QGraphicsRectItem):
    """El recuadro punteado: dónde va la imagen. Se arrastra; la esquina de abajo a la derecha cambia el tamaño."""
    ESQUINA = 14

    def __init__(self, rect: QRectF, al_cambiar):
        super().__init__(QRectF(0, 0, rect.width(), rect.height()))
        self.setPos(rect.topLeft())
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPen(QPen(QColor("#f0c040"), 1.5, Qt.DashLine))
        self.setBrush(QBrush(QColor(240, 192, 64, 22)))
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(10)
        self._al_cambiar = al_cambiar
        self._redim = None

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        r = self.rect()
        painter.fillRect(QRectF(r.right() - self.ESQUINA, r.bottom() - self.ESQUINA, self.ESQUINA, self.ESQUINA),
                         QColor("#f0c040"))

    def _en_esquina(self, p: QPointF) -> bool:
        r = self.rect()
        return p.x() >= r.right() - self.ESQUINA and p.y() >= r.bottom() - self.ESQUINA

    def mousePressEvent(self, e):
        if self._en_esquina(e.pos()):
            self._redim = (e.pos(), QRectF(self.rect()))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._redim is not None:
            p0, r0 = self._redim
            d = e.pos() - p0
            self.prepareGeometryChange()
            self.setRect(QRectF(0, 0, max(20.0, r0.width() + d.x()), max(20.0, r0.height() + d.y())))
            self._al_cambiar()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._redim = None
        super().mouseReleaseEvent(e)
        self._al_cambiar()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            r, sr = self.rect(), self.scene().sceneRect()      # (al menos un trozo siempre dentro de la pantalla)
            x = min(max(value.x(), sr.left() - r.width() * 0.75), sr.right() - r.width() * 0.25)
            y = min(max(value.y(), sr.top() - r.height() * 0.75), sr.bottom() - r.height() * 0.25)
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._al_cambiar()
        return super().itemChange(change, value)


class ImageAnimDialog(QDialog):
    def __init__(self, win, media_id: str | None = None):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        p = self.ctrl.project
        self.setWindowTitle("🎞 Animar imagen")
        self.W, self.H = VW, max(120, int(round(VW * p.height / max(1, p.width))))
        self._t0 = 0.0
        self._pix: QPixmap | None = None
        self.creados: list[str] | None = None

        # ---- vista previa
        self.scene = QGraphicsScene(0, 0, self.W, self.H, self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.view.setFixedSize(self.W + 4, self.H + 4)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scene.addRect(QRectF(0, 0, self.W, self.H), QPen(Qt.NoPen), QBrush(Qt.black))
        fondo = self._fondo()
        if fondo is not None:
            self.scene.addPixmap(fondo)
        self.anim_item = QGraphicsPixmapItem()
        self.anim_item.setTransformationMode(Qt.SmoothTransformation)
        self.anim_item.setZValue(5)
        self.scene.addItem(self.anim_item)
        c = image_anim.CAJA_PERSONAJE
        self.caja = _Caja(QRectF(c["x"] * self.W, c["y"] * self.H, c["w"] * self.W, c["h"] * self.H), self._replan)
        self.scene.addItem(self.caja)
        self.view.setToolTip("Arrastra el recuadro punteado para elegir dónde va; la esquina amarilla cambia el "
                             "tamaño. La animación se repite en bucle tal como saldrá.")

        # ---- opciones
        self.media = QComboBox()
        self.media.setToolTip("La imagen que se anima (mejor un PNG con fondo transparente: un personaje recortado).")
        btn_otra = QPushButton("📂")
        btn_otra.setToolTip("Elegir otra imagen de tu PC (se añade a Medios).")
        btn_otra.clicked.connect(self._otra)
        self.anims = QListWidget()
        it = QListWidgetItem("✨ Según lo que digo")
        it.setData(Qt.UserRole, AUTO)
        it.setToolTip("En cada momento, la que pide lo que dices: «dispara» → disparar, «muere» → morir, "
                      "«llega» → entrar deslizando, «huye» → salir… Si no dices nada de eso, se queda quieta.")
        self.anims.addItem(it)
        for k, n, d in image_anim.ANIMS:
            it = QListWidgetItem(n)
            it.setData(Qt.UserRole, k)
            it.setToolTip(d)
            self.anims.addItem(it)
        self.anims.setCurrentRow(2)                                  # 🔫 Disparar
        self.anims.currentRowChanged.connect(self._replan)
        self.lado = QComboBox()
        for txt, v in (("Mira hacia el centro (automático)", 0), ("Mira a la derecha →", 1),
                       ("Mira a la izquierda ←", -1)):
            self.lado.addItem(txt, v)
        self.lado.setToolTip("Hacia dónde mira el personaje: el retroceso del disparo y la caída del golpe van hacia "
                             "su espalda; al entrar llega por detrás, al salir se va por delante.")
        self.lado.currentIndexChanged.connect(self._replan)
        self.dur = QDoubleSpinBox()
        self.dur.setRange(0.5, 30.0)
        self.dur.setSingleStep(0.5)
        self.dur.setDecimals(1)
        self.dur.setSuffix(" s")
        self.dur.setValue(3.0)
        self.dur.setToolTip("Cuánto dura cada imagen en la línea de tiempo.")
        self.dur.valueChanged.connect(self._replan)

        self.en_cabezal = QRadioButton(f"En el cabezal ({fmt_time(self._cabezal(), frac=False)})")
        self.en_cabezal.setToolTip("Donde está el cabezal al pulsar «Poner».")
        self.en_palabra = QRadioButton("Donde digo una palabra clave")
        self.en_cabezal.setChecked(True)
        self.palabra = QComboBox()
        self.palabra.setToolTip("Tus palabras clave (fila 🔑). Abajo salen los momentos en que la dices: marca dónde "
                                "va la imagen.")
        self.momentos = QListWidget()
        self.momentos.setToolTip("Los momentos en que dices la palabra (con lo que dices ahí). Marca en cuáles va.")
        self._menciones = self._leer_menciones()
        for folder in sorted({m["folder"] for m in self._menciones}, key=str.lower):
            self.palabra.addItem(folder)
        if not self._menciones:
            self.en_palabra.setEnabled(False)
            self.en_palabra.setToolTip("No hay palabras clave dichas todavía (hace falta la transcripción y "
                                       "carpetas de palabras clave).")
        self.palabra.currentIndexChanged.connect(self._llenar_momentos)
        self.palabra.currentIndexChanged.connect(self._replan)
        self.momentos.itemChanged.connect(self._replan)
        self.en_palabra.toggled.connect(self._donde)
        self.en_palabra.toggled.connect(self._replan)
        self._llenar_momentos()
        self._donde()

        der = QVBoxLayout()
        fila = QHBoxLayout()
        fila.addWidget(self.media, 1)
        fila.addWidget(btn_otra)
        der.addWidget(QLabel("Imagen"))
        der.addLayout(fila)
        der.addWidget(QLabel("Animación"))
        der.addWidget(self.anims, 1)
        der.addWidget(self.lado)
        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel("Duración"))
        fila2.addWidget(self.dur)
        fila2.addStretch(1)
        der.addLayout(fila2)
        der.addWidget(self.en_cabezal)
        der.addWidget(self.en_palabra)
        der.addWidget(self.palabra)
        der.addWidget(self.momentos, 1)
        botones = QDialogButtonBox()
        self.btn_poner = botones.addButton("Poner", QDialogButtonBox.AcceptRole)
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._poner)
        botones.rejected.connect(self.reject)
        self.aviso = QLabel("")
        self.aviso.setObjectName("dim")
        self.aviso.setWordWrap(True)
        der.addWidget(self.aviso)
        der.addWidget(botones)
        lay = QHBoxLayout(self)
        lay.addWidget(self.view, 0, Qt.AlignTop)
        lay.addLayout(der, 1)
        self._lay = lay

        self._llenar_medios(media_id)
        self.media.currentIndexChanged.connect(self._cargar_imagen)
        self._cargar_imagen()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._tiempo = 0.0
        self._timer.start()

    def compactar(self):
        """🧰 Como pestaña del panel de herramientas (lote 1, 23/11), en ~300 px: la vista previa arriba (a escala,
        el recuadro se sigue arrastrando igual) y las opciones debajo."""
        from . import compacto as _compacto
        _compacto.ajustar_zonas(self)     # (el contenido de cada zona, al ancho visible menos la barra)
        from PySide6.QtGui import QTransform
        from PySide6.QtWidgets import QBoxLayout
        from . import diseno as D
        # (tope de ancho Y de alto: en un proyecto vertical la vista ocupaba todo el panel y no se veía «Poner»)
        s = min(1.0, D.px(270) / float(self.W), D.px(130) / float(self.H))
        self.view.setTransform(QTransform.fromScale(s, s))
        self.view.setFixedSize(int(self.W * s) + 4, int(self.H * s) + 4)
        self._lay.setDirection(QBoxLayout.TopToBottom)
        self._lay.setAlignment(self.view, Qt.AlignHCenter | Qt.AlignTop)
        self.anims.setMaximumHeight(D.px(88))          # (la lista de animaciones se desplaza sola)
        self.momentos.setMaximumHeight(D.px(90))
        for w in (self.palabra, self.momentos):         # (solo con «Donde digo una palabra clave»)
            w.setVisible(self.en_palabra.isChecked())
            self.en_palabra.toggled.connect(w.setVisible)

    # ------------------------------------------------------------- datos
    def _fondo(self) -> QPixmap | None:
        """El fotograma que se ve ahora en el visor (sin ventanas nuevas: se dibuja su escena en una imagen)."""
        try:
            cv = self.win.preview.canvas
            img = QImage(self.W, self.H, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.black)
            pt = QPainter(img)
            cv.scene().render(pt, QRectF(0, 0, self.W, self.H), QRectF(0, 0, cv.W, cv.H))
            pt.end()
            return QPixmap.fromImage(img)
        except Exception:  # noqa: BLE001 - sin visor (pruebas): fondo negro
            return None

    def _cabezal(self) -> float:
        try:
            return float(self.win.engine.time)
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _leer_menciones(self) -> list[dict]:
        try:
            ms, _frases = self.win.kw_arranger._mentions()
            return [m for m in ms if m.get("folder")]
        except Exception:  # noqa: BLE001 - sin palabras clave o sin transcripción
            return []

    def _llenar_medios(self, media_id: str | None):
        p = self.ctrl.project
        imgs = sorted((m for m in p.media.values() if m.kind == KIND_IMAGE and m.id not in self.ctrl.missing),
                      key=lambda m: m.name.lower())
        for m in imgs:
            self.media.addItem(m.name, m.id)
        if media_id and self.media.findData(media_id) < 0 and media_id in p.media:
            self.media.addItem(p.media[media_id].name, media_id)
        if media_id:
            self.media.setCurrentIndex(max(0, self.media.findData(media_id)))

    def _otra(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir imagen", "", "Imágenes (*.png *.jpg *.jpeg *.webp *.gif)")
        if not ruta:
            return
        ids = self.ctrl.import_now([ruta], quiet=True)
        if ids:
            if self.media.findData(ids[0]) < 0:
                self.media.addItem(os.path.basename(ruta), ids[0])
            self.media.setCurrentIndex(self.media.findData(ids[0]))

    def _cargar_imagen(self):
        mid = self.media.currentData()
        m = self.ctrl.project.media.get(mid) if mid else None
        self._pix = QPixmap(m.path) if m is not None and os.path.isfile(m.path) else None
        if self._pix is not None and self._pix.isNull():
            self._pix = None
        if self._pix is not None and max(self._pix.width(), self._pix.height()) > 2 * max(self.W, self.H):
            self._pix = self._pix.scaled(2 * self.W, 2 * self.H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.btn_poner.setEnabled(self._pix is not None)
        self._replan()

    def _llenar_momentos(self):
        self.momentos.clear()
        folder = self.palabra.currentText()
        p = self.ctrl.project
        for m in sorted((m for m in self._menciones if m["folder"] == folder), key=lambda m: m["t"]):
            frase = image_anim.texto_en(p, m["t"], 0.6, 2.2)
            it = QListWidgetItem(f"{fmt_time(m['t'], frac=False)}  «{frase[:60]}»" if frase else
                                 fmt_time(m["t"], frac=False))
            it.setData(Qt.UserRole, float(m["t"]))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.momentos.addItem(it)

    def _donde(self):
        on = self.en_palabra.isChecked()
        self.palabra.setEnabled(on)
        self.momentos.setEnabled(on)

    # ------------------------------------------------------------- lo elegido
    def caja_elegida(self) -> dict:
        r = self.caja.rect().translated(self.caja.pos())
        x, y = r.x() / self.W, r.y() / self.H
        return {"x": round(x, 4), "y": round(y, 4), "w": round(r.width() / self.W, 4),
                "h": round(r.height() / self.H, 4), "fit": "contain", "bg": "none"}

    def clave(self) -> str:
        it = self.anims.currentItem()
        return it.data(Qt.UserRole) if it is not None else "ninguna"

    def momentos_elegidos(self) -> list[float]:
        if not self.en_palabra.isChecked():
            self.en_cabezal.setText(f"En el cabezal ({fmt_time(self._cabezal(), frac=False)})")
            return [self._cabezal()]
        return [self.momentos.item(i).data(Qt.UserRole) for i in range(self.momentos.count())
                if self.momentos.item(i).checkState() == Qt.Checked]

    def _replan(self, *_a):
        if not hasattr(self, "anims") or not hasattr(self, "momentos"):
            return                                       # (aún montando la ventana)
        k = self.clave()
        if k == AUTO:                       # (en la vista previa: la del primer momento, o disparar de ejemplo)
            ts = self.momentos_elegidos()
            k = (image_anim.elegir(image_anim.texto_en(self.ctrl.project, ts[0])) if ts else None) or "disparo"
        self._plan = image_anim.plan(k, self.caja_elegida(), self.dur.value(), self.lado.currentData())
        self._tiempo = 0.0

    # ------------------------------------------------------------- vista previa animada
    def _tick(self):
        if self._pix is None or not hasattr(self, "_plan"):
            self.anim_item.setVisible(False)
            return
        dur = self.dur.value()
        self._tiempo += self._timer.interval() / 1000.0
        if self._tiempo > dur + 0.6:                         # (una pausa corta y vuelve a empezar)
            self._tiempo = 0.0
        t = min(self._tiempo, dur)
        pl = self._plan
        box = dict(pl["layout"])
        if pl["layout_kf"]:
            box.update(transform.layout_value_at(pl["layout_kf"], t))
        op = _opacidad(pl["op_kf"], t)
        dx, dy = effects.shake_at(pl["fx"], t)
        bw, bh = box["w"] * self.W, box["h"] * self.H
        s = min(bw / self._pix.width(), bh / self._pix.height())
        pw, ph = max(1, int(self._pix.width() * s)), max(1, int(self._pix.height() * s))
        clave = f"{pw}x{ph}"
        if getattr(self, "_pix_clave", None) != (id(self._pix), clave):
            # (mientras cambia de tamaño —«Acercarse»— se reduce rápido; quieto, con suavizado)
            suave = not any(k.get("w") != pl["layout_kf"][0].get("w") for k in pl["layout_kf"])
            self._pix_esc = self._pix.scaled(pw, ph, Qt.IgnoreAspectRatio,
                                             Qt.SmoothTransformation if suave else Qt.FastTransformation)
            self._pix_clave = (id(self._pix), clave)
            self.anim_item.setPixmap(self._pix_esc)
        self.anim_item.setPos(box["x"] * self.W + (bw - pw) / 2 + dx * bw, box["y"] * self.H + (bh - ph) / 2 + dy * bh)
        self.anim_item.setOpacity(op)
        self.anim_item.setVisible(True)

    # ------------------------------------------------------------- poner
    def _poner(self):
        mid = self.media.currentData()
        ts = self.momentos_elegidos()
        if not mid or not ts:
            self.aviso.setText("Elige una imagen y marca al menos un momento.")
            return
        self.creados = self.ctrl.add_animated_images(mid, ts, self.dur.value(), self.caja_elegida(), self.clave(),
                                                     self.lado.currentData())
        if self.creados:
            self.accept()

    def done(self, r):
        self._timer.stop()
        super().done(r)


def _opacidad(op_kf: list[dict], t: float) -> float:
    if not op_kf:
        return 1.0
    pts = sorted(op_kf, key=lambda k: k["t"])
    if t <= pts[0]["t"]:
        return float(pts[0]["v"])
    for a, b in zip(pts, pts[1:]):
        if t <= b["t"]:
            u = (t - a["t"]) / max(1e-9, b["t"] - a["t"])
            return float(a["v"]) + (float(b["v"]) - float(a["v"])) * u
    return float(pts[-1]["v"])


def abrir(win, media_id: str | None = None):
    """Abre la herramienta (no bloquea la edición) y, al poner, selecciona lo creado. 🧰 (lote 1, 23/11) Como
    pestaña del panel de herramientas; si ya estaba abierta con otra imagen, se rehace con la nueva."""
    h = getattr(win, "herramientas", None)
    if h is not None and (h.abierta("animar") or h.guardada("animar")):
        viejo = h.widget("animar")
        if getattr(viejo, "_media_pedida", None) != media_id:
            h.cerrar("animar", por_usuario=False)

    def crear():
        d = ImageAnimDialog(win, media_id)
        d._media_pedida = media_id

        def listo(_r):
            if d.creados:
                win.timeline.set_selection(d.creados)
        d.finished.connect(listo)
        return d
    if h is None:
        d = crear()
        d.setAttribute(Qt.WA_DeleteOnClose)
        d.show()
        return d
    return h.dialogo("animar", crear, "Animar imagen", "Animar", "image")

