"""
🎭 PNGTuber: tu avatar en PNG en el video, abriendo la boca cuando hablas y parpadeando.

Eliges (o creas y guardas en «Mis PNGTubers») las imágenes del avatar, de qué audio sale la voz, la sensibilidad, el
parpadeo, el rebote, el tamaño y la esquina; en «😄 Reacciones», a qué categorías de palabras reacciona (saluda con
«hola», salta de alegría con «genial», se sobresalta con «¿qué?»…; core/categorias_palabras.py) con una imagen opcional
para cada una y la lista de qué palabras activaron qué. «🎭 Crear y poner en la línea de tiempo» crea un video sobre verde
(core/pngtuber.py) en segundo plano, lo importa a Medios y lo pone en una pista de video por encima de todo, con la
🟩 Pantalla verde y sin sonido, en UN paso de Ctrl+Z. Se ve igual en el visor y al exportar.

Para abrirla: abrir(win, audio_clip_id=None).
"""
from __future__ import annotations

import os
import time

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import media as media_tools
from ..core import pngtuber as PT
from ..core.model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip, new_id
from .common import fmt_time

FPS = 30
VISTA = 210                 # alto de la vista previa (px)
BUCLE = 8.0                 # segundos de la vista previa en bucle
NUEVO = "__nuevo__"


# ------------------------------------------------------------------------------------------- piezas
class _Hueco(QToolButton):
    """Un botón por imagen del modelo, con su miniatura. Clic = elegir; clic derecho = quitar."""

    def __init__(self, clave: str, nombre: str, obligatoria: bool, ayuda: str, cambio):
        super().__init__()
        self.clave, self.nombre, self.obligatoria, self._cambio = clave, nombre, obligatoria, cambio
        self.ruta = ""
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(72, 72))
        self.setFixedSize(112, 112)
        self.setToolTip(ayuda + "\nClic: elegir el PNG (mejor con fondo transparente). Clic derecho: quitarla.")
        self.clicked.connect(self._elegir)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.poner("")

    def poner(self, ruta: str):
        self.ruta = ruta if ruta and os.path.isfile(ruta) else ""
        pix = QPixmap(self.ruta) if self.ruta else QPixmap()
        if not pix.isNull():
            self.setIcon(QIcon(pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        else:
            self.setIcon(QIcon())
        self.setText(self.nombre + (" *" if self.obligatoria and not self.ruta else ""))
        self.setStyleSheet("" if self.ruta or not self.obligatoria else "QToolButton { border: 1px dashed #c98; }")

    def _elegir(self):
        ruta, _ = QFileDialog.getOpenFileName(self, f"Elegir: {self.nombre}", os.path.dirname(self.ruta),
                                              "Imágenes (*.png *.webp *.gif *.jpg *.jpeg)")
        if ruta:
            self.poner(ruta)
            self._cambio()

    def _menu(self, pos):
        if not self.ruta:
            return
        m = QMenu(self)
        m.addAction("✕ Quitar esta imagen", lambda: (self.poner(""), self._cambio()))
        m.exec(self.mapToGlobal(pos))


class _HuecoMini(_Hueco):
    """La imagen opcional de una reacción: un botón pequeño (🖼 sin imagen; su miniatura con ella)."""

    def __init__(self, clave: str, nombre: str, ayuda: str, cambio):
        super().__init__(clave, nombre, False, ayuda, cambio)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setIconSize(QSize(30, 30))
        self.setFixedSize(40, 40)

    def poner(self, ruta: str):
        super().poner(ruta)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly if self.ruta else Qt.ToolButtonTextOnly)
        self.setText("" if self.ruta else "🖼")
        self.setStyleSheet("")


class _Onda(QWidget):
    """La forma de onda del audio elegido: en verde, donde la boca está abierta; la línea, el umbral."""

    def __init__(self):
        super().__init__()
        self.vol = np.zeros(0, np.float32)
        self.abierta = np.zeros(0, bool)
        self.umbral = 0.0
        self.escala = 1.0
        self.cabezal = -1
        self.texto = ""
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("La voz del audio elegido. En verde, donde el avatar abre la boca; la línea amarilla es el "
                        "volumen a partir del cual la abre (súbela o bájala con la sensibilidad). La raya blanca es "
                        "lo que se ve en la vista previa.")

    def poner(self, vol, abierta, umbral: float, ref: float):
        self.vol, self.abierta = vol, abierta
        self.escala = max(1e-4, ref * 1.25, float(vol.max()) if len(vol) else 0.0)
        self.umbral = umbral
        self.texto = ""
        self.update()

    def paintEvent(self, _e):
        q = QPainter(self)
        w, h = self.width(), self.height()
        q.fillRect(0, 0, w, h, QColor(24, 26, 30))
        n = len(self.vol)
        if self.texto or not n:
            q.setPen(QColor(170, 170, 170))
            q.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self.texto or "—")
            return
        idx = np.linspace(0, n, w + 1).astype(int)
        for x in range(w):
            a, b = idx[x], max(idx[x] + 1, idx[x + 1])
            v = float(self.vol[a:b].max()) / self.escala
            ab = bool(self.abierta[a:b].any())
            alto = max(1, int(min(1.0, v) * (h - 6)))
            q.setPen(QColor(90, 200, 110) if ab else QColor(110, 115, 125))
            q.drawLine(x, h - 3, x, h - 3 - alto)
        if np.isfinite(self.umbral):
            y = h - 3 - int(min(1.0, self.umbral / self.escala) * (h - 6))
            q.setPen(QPen(QColor(240, 200, 60), 1, Qt.DashLine))
            q.drawLine(0, y, w, y)
        if 0 <= self.cabezal < n:
            x = int(self.cabezal / n * w)
            q.setPen(QPen(QColor(255, 255, 255), 2))
            q.drawLine(x, 0, x, h)


# ------------------------------------------------------------------------------------------- ventana
class PNGTuberDialog(QDialog):
    def __init__(self, win, audio_clip_id: str | None = None):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.setWindowTitle("🎭 PNGTuber")
        self.job = None
        self.creado: str | None = None          # el clip del avatar puesto en la línea de tiempo
        self.resultado: dict | None = None
        self._modelo_archivo = ""
        self._ests: list = []
        self._pix: dict[str, QPixmap] = {}
        self._frame = 0
        self._bucle = (0, 0)
        self._esperando_picos = ""

        # ---- modelo
        self.modelos = QComboBox()
        self.modelos.setToolTip("📚 Mis PNGTubers: los avatares que guardaste. Sirven en cualquier proyecto.")
        self.modelos.setMinimumWidth(180)
        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Nombre del avatar")
        self.nombre.setToolTip("Con este nombre se guarda en «Mis PNGTubers».")
        self.btn_guardar = QPushButton("💾 Guardar modelo")
        self.btn_guardar.setToolTip("Guarda las imágenes elegidas y los ajustes con ese nombre, para usarlo otra vez.")
        self.btn_guardar.clicked.connect(self.guardar_modelo)
        self.btn_borrar = QToolButton()
        self.btn_borrar.setText("🗑")
        self.btn_borrar.setToolTip("Quitar este avatar de «Mis PNGTubers» (tus imágenes no se borran).")
        self.btn_borrar.clicked.connect(self._borrar_modelo)
        fila_modelo = QHBoxLayout()
        fila_modelo.addWidget(QLabel("Avatar:"))
        fila_modelo.addWidget(self.modelos, 1)
        fila_modelo.addWidget(self.btn_borrar)
        fila_modelo.addWidget(self.nombre, 1)
        fila_modelo.addWidget(self.btn_guardar)
        self.huecos: dict[str, _Hueco] = {}
        fila_huecos = QHBoxLayout()
        for clave, nombre, obligatoria, ayuda in PT.IMAGENES:
            hb = _Hueco(clave, nombre, obligatoria, ayuda, self._modelo_cambiado)
            self.huecos[clave] = hb
            fila_huecos.addWidget(hb)
        fila_huecos.addStretch(1)
        caja_modelo = QGroupBox("🎭 Avatar")
        lm = QVBoxLayout(caja_modelo)
        lm.addLayout(fila_modelo)
        lm.addLayout(fila_huecos)

        # ---- voz y ajustes
        self.audio = QComboBox()
        self.audio.setToolTip("El audio de la línea de tiempo del que sale tu voz (la narración). El avatar dura "
                              "lo mismo que ese clip y empieza donde empieza.")
        self.sens = QSlider(Qt.Horizontal)
        self.sens.setRange(0, 100)
        self.sens.setToolTip("Más a la derecha: abre la boca con la voz más baja. Más a la izquierda: solo cuando "
                             "hablas fuerte (útil si hay ruido o música en el mismo audio).")
        self.onda = _Onda()
        self.parpadeo = QComboBox()
        for k, n in (("nunca", "Nunca"), ("poco", "Poco (cada 4–8 s)"), ("normal", "Normal (cada 2,5–6 s)"),
                     ("mucho", "Mucho (cada 1,5–3,5 s)")):
            self.parpadeo.addItem(n, k)
        self.parpadeo.setToolTip("Cada cuánto parpadea (al azar, como una persona). Necesita la imagen "
                                 "«😌 Ojos cerrados».")
        self.rebote = QCheckBox("Rebote al hablar")
        self.rebote.setToolTip("El avatar sube unos píxeles mientras hablas, como en los PNGTubers de directo.")
        self.tamano = QSlider(Qt.Horizontal)
        self.tamano.setRange(10, 90)
        self.tamano.setToolTip("Alto del avatar en la pantalla (porcentaje del alto del video).")
        self.tam_lbl = QLabel()
        self.posicion = QComboBox()
        for k, n in PT.POSICIONES:
            self.posicion.addItem(n, k)
        self.posicion.setToolTip("Dónde va el avatar. Luego lo puedes mover y escalar en el visor como cualquier clip.")
        tam = QHBoxLayout()
        tam.addWidget(self.tamano, 1)
        tam.addWidget(self.tam_lbl)
        form = QFormLayout()
        form.addRow("🎙 Voz:", self.audio)
        form.addRow("Sensibilidad:", self.sens)
        form.addRow(self.onda)
        form.addRow("👁 Parpadeo:", self.parpadeo)
        form.addRow("", self.rebote)
        form.addRow("📏 Tamaño:", tam)
        form.addRow("📍 Posición:", self.posicion)
        caja_ajustes = QWidget()
        caja_ajustes.setLayout(form)
        self.pestanas = QTabWidget()
        self.pestanas.addTab(caja_ajustes, "⚙ Cómo se mueve")
        self.pestanas.addTab(self._tab_reacciones(), "😄 Reacciones")
        self.pestanas.setTabToolTip(1, "El avatar reacciona a lo que dices: saluda con «hola», salta de alegría con "
                                       "«genial», se sobresalta con «¿qué?», se encoge con «qué pena»… (necesita la "
                                       "transcripción de la voz)")

        # ---- vista previa
        self.vista = QLabel()
        self.vista.setFixedSize(VISTA + 40, VISTA + 20)
        self.vista.setAlignment(Qt.AlignCenter)
        self.vista.setToolTip("Vista previa en bucle (sin sonido) de un trozo de tu voz: así abrirá la boca, "
                              "parpadeará y rebotará en el video.")
        self.vista_t = QLabel()
        self.vista_t.setAlignment(Qt.AlignCenter)
        caja_vista = QGroupBox("▶ Vista previa")
        lv = QVBoxLayout(caja_vista)
        lv.addWidget(self.vista, 0, Qt.AlignCenter)
        lv.addWidget(self.vista_t)
        lv.addStretch(1)

        # ---- abajo
        self.estado = QLabel()
        self.estado.setWordWrap(True)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setVisible(False)
        self.btn_crear = QPushButton("🎭 Crear y poner en la línea de tiempo")
        self.btn_crear.setDefault(True)
        self.btn_crear.setToolTip("Crea el video del avatar (en segundo plano) y lo pone encima de todo, donde "
                                  "empieza la voz, con el fondo verde ya quitado. Un Ctrl+Z lo quita.")
        self.btn_crear.clicked.connect(self.crear)
        self.btn_cancelar = QPushButton("✕ Cancelar")
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.clicked.connect(self._cancelar)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.close)
        abajo = QHBoxLayout()
        abajo.addWidget(self.barra, 1)
        abajo.addWidget(self.btn_cancelar)
        abajo.addWidget(self.btn_crear)
        abajo.addWidget(btn_cerrar)

        medio = QGridLayout()
        medio.addWidget(self.pestanas, 0, 0)
        medio.addWidget(caja_vista, 0, 1)
        medio.setColumnStretch(0, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(caja_modelo)
        lay.addLayout(medio)
        lay.addWidget(self.estado)
        lay.addLayout(abajo)
        self.resize(820, 640)

        # ---- valores
        self._ajustes_a_ui(PT.AJUSTES)
        self._llenar_modelos()
        self._llenar_audios(audio_clip_id)
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / FPS))
        self.timer.timeout.connect(self._paso)
        self._recalc = QTimer(self)
        self._recalc.setSingleShot(True)
        self._recalc.setInterval(120)
        self._recalc.timeout.connect(self._recalcular)
        self.modelos.currentIndexChanged.connect(self._modelo_elegido)
        self.audio.currentIndexChanged.connect(lambda _i: self._recalc.start())
        self.sens.valueChanged.connect(lambda _v: self._recalc.start())
        self.parpadeo.currentIndexChanged.connect(lambda _i: self._recalc.start())
        self.rebote.toggled.connect(lambda _v: self._recalc.start())
        self.tamano.valueChanged.connect(self._tam_texto)
        for cb in self.reac_cb.values():
            cb.toggled.connect(lambda _v: self._recalc.start())
        self.ctrl.peaks_changed.connect(self._picos_llegaron)
        if self.modelos.count() > 1:
            self.modelos.setCurrentIndex(1)              # el primero de «Mis PNGTubers»
        self._modelo_cambiado()
        self._recalcular()
        self.timer.start()

    # ------------------------------------------------------------------ 😄 reacciones
    def _tab_reacciones(self) -> QWidget:
        from ..core import categorias_palabras as CP
        cont = QWidget()
        v = QVBoxLayout(cont)
        v.setContentsMargins(4, 4, 4, 4)
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(6)
        self.reac_cb: dict[str, QCheckBox] = {}
        self.reac_img: dict[str, _HuecoMini] = {}
        for i, (k, nombre, reac, dur) in enumerate(PT.REACCIONES):
            cat = CP.POR_CLAVE_PNGTUBER[k]
            cb = QCheckBox(nombre)
            cb.setToolTip(f"Cuando dices palabras como «{cat.get('ejemplos', '')}…», el avatar "
                          f"{PT.DESC_REACCION.get(reac, reac)} (unos {dur:g} s).\nQuítala si no la quieres.")
            hb = _HuecoMini("r_" + k, nombre, f"Imagen opcional para «{nombre}»: si la eliges, el avatar la "
                                              f"enseña mientras dura la reacción (p. ej. con los brazos arriba, "
                                              f"saludando con la mano…). Sin ella, se anima su imagen normal.",
                            self._modelo_cambiado)
            self.reac_cb[k] = cb
            self.reac_img[k] = hb
            fila, col = divmod(i, 2)
            rejilla.addWidget(hb, fila, col * 2)
            rejilla.addWidget(cb, fila, col * 2 + 1)
        rejilla.setColumnStretch(1, 1)
        rejilla.setColumnStretch(3, 1)
        v.addLayout(rejilla)
        t = QLabel("Qué palabras lo activan")
        t.setObjectName("dim")
        t.setWordWrap(True)
        v.addWidget(t)
        self.reac_lista = QListWidget()
        self.reac_lista.setWordWrap(True)
        self.reac_lista.setMinimumHeight(90)
        self.reac_lista.setToolTip("Cada reacción, con la palabra que la provoca y cuándo. Clic = verla en la vista "
                                   "previa.")
        self.reac_lista.itemClicked.connect(self._ver_reaccion)
        v.addWidget(self.reac_lista, 1)
        caja = QScrollArea()
        caja.setWidgetResizable(True)
        caja.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        caja.setFrameShape(QScrollArea.NoFrame)
        caja.setWidget(cont)
        caja.setMinimumWidth(cont.minimumSizeHint().width() + caja.verticalScrollBar().sizeHint().width() + 4)
        self._eventos: list[dict] = []
        self._pal_cache: tuple | None = None
        return caja

    def _palabras(self, c: Clip) -> list:
        """Lo que dices mientras dura ese clip (segundos de la línea de tiempo): su transcripción o, si no tiene, la
        de lo que suene en ese tramo."""
        from ..core import categorias_palabras as CP
        p = self.ctrl.project
        clave = (c.id, round(c.start, 3), round(c.duration, 3), round(c.source_in, 3),
                 tuple(sorted((k, len(v.get("words", []))) for k, v in (p.transcripts or {}).items())))
        if self._pal_cache is not None and self._pal_cache[0] == clave:
            return self._pal_cache[1]
        mid = c.media_id if c.media_id in (p.transcripts or {}) else None
        ws = CP.palabras_linea(p, c.start, c.start + c.duration, mid)
        self._pal_cache = (clave, ws)
        return ws

    def _reacciones(self, c: Clip, n: int) -> list[dict]:
        activas = [k for k, cb in self.reac_cb.items() if cb.isChecked()]
        if not activas:
            return []
        return PT.eventos_reaccion(self._palabras(c), c.start, n, activas, FPS)

    def _llenar_reacciones(self, c: Clip | None):
        self.reac_lista.clear()
        nombres = {k: n for k, n, _r, _d in PT.REACCIONES}
        if c is None:
            return
        if not self._eventos:
            if not self._palabras(c):
                txt = "Sin transcripción de esta voz: transcríbela (🎙) para que el avatar reaccione a lo que dices."
            elif not any(cb.isChecked() for cb in self.reac_cb.values()):
                txt = "Todas las reacciones están quitadas."
            else:
                txt = "No dices ninguna palabra de las categorías marcadas."
            it = QListWidgetItem(txt)
            it.setFlags(Qt.NoItemFlags)
            self.reac_lista.addItem(it)
            return
        for ev in self._eventos:
            it = QListWidgetItem(f"{fmt_time(ev['t'], frac=False)}  {nombres.get(ev['cat'], ev['cat'])} ← "
                                 f"«{ev['palabra']}»")
            it.setData(Qt.UserRole, ev["i0"])
            self.reac_lista.addItem(it)

    def _ver_reaccion(self, it):
        i0 = it.data(Qt.UserRole)
        if i0 is None or not self._ests:
            return
        n = len(self._ests)
        self._bucle = (max(0, int(i0) - FPS // 3), min(n, int(i0) + int(2.5 * FPS)))
        self._frame = self._bucle[0]

    # ------------------------------------------------------------------ modelo
    def modelo(self) -> dict:
        imgs = {k: h.ruta for k, h in self.huecos.items() if h.ruta}
        imgs.update({"r_" + k: h.ruta for k, h in self.reac_img.items() if h.ruta})
        return {"nombre": self.nombre.text().strip() or "Mi PNGTuber", "imagenes": imgs, "ajustes": self.ajustes()}

    def set_imagen(self, clave: str, ruta: str):
        hueco = self.huecos.get(clave) or self.reac_img[clave[2:]]
        hueco.poner(ruta)
        self._modelo_cambiado()

    def ajustes(self) -> dict:
        return {"sensibilidad": self.sens.value() / 100.0, "parpadeo": self.parpadeo.currentData(),
                "rebote": self.rebote.isChecked(), "tamano": self.tamano.value() / 100.0,
                "posicion": self.posicion.currentData(),
                "reacciones": [k for k, cb in self.reac_cb.items() if cb.isChecked()]}

    def _ajustes_a_ui(self, a: dict):
        a = dict(PT.AJUSTES, **(a or {}))
        self.sens.setValue(int(round(float(a["sensibilidad"]) * 100)))
        self.parpadeo.setCurrentIndex(max(0, self.parpadeo.findData(a["parpadeo"])))
        self.rebote.setChecked(bool(a["rebote"]))
        self.tamano.setValue(int(round(float(a["tamano"]) * 100)))
        self.posicion.setCurrentIndex(max(0, self.posicion.findData(a["posicion"])))
        activas = a.get("reacciones")
        activas = set(activas) if isinstance(activas, (list, tuple)) else set(PT.AJUSTES["reacciones"])
        for k, cb in self.reac_cb.items():
            cb.setChecked(k in activas)
        self._tam_texto()

    def _tam_texto(self, *_a):
        self.tam_lbl.setText(f"{self.tamano.value()} %")

    def _llenar_modelos(self, elegir: str | None = None):
        self.modelos.blockSignals(True)
        self.modelos.clear()
        self.modelos.addItem("＋ Nuevo avatar", NUEVO)
        for m in PT.listar():
            self.modelos.addItem("🎭 " + m["nombre"], m["archivo"])
        if elegir:
            i = self.modelos.findData(elegir)
            self.modelos.setCurrentIndex(max(0, i))
        self.modelos.blockSignals(False)
        self.btn_borrar.setEnabled(self.modelos.currentData() != NUEVO)

    def _modelo_elegido(self, _i=None):
        arch = self.modelos.currentData()
        self.btn_borrar.setEnabled(arch != NUEVO)
        if arch == NUEVO:
            self._modelo_archivo = ""
            self.nombre.clear()
            for h in list(self.huecos.values()) + list(self.reac_img.values()):
                h.poner("")
            self._modelo_cambiado()
            return
        m = PT.cargar(arch)
        if m is None:
            return
        self._modelo_archivo = arch
        self.nombre.setText(m["nombre"])
        for k, h in self.huecos.items():
            h.poner(m["imagenes"].get(k, ""))
        for k, h in self.reac_img.items():
            h.poner(m["imagenes"].get("r_" + k, ""))
        self._ajustes_a_ui(m["ajustes"])
        perdidas = [n for k, n, _o, _d in PT.IMAGENES if m["imagenes"].get(k) and not self.huecos[k].ruta]
        perdidas += [n for k, n in PT.IMAGENES_REACCION if m["imagenes"].get(k) and not self.reac_img[k[2:]].ruta]
        self._modelo_cambiado()
        if perdidas:
            self.estado.setText("⚠ No se encuentran: " + ", ".join(perdidas) + ". Vuelve a elegirlas.")

    def guardar_modelo(self) -> str | None:
        m = self.modelo()
        if PT.falta(m):
            self.estado.setText("Faltan: " + ", ".join(PT.falta(m)) + ".")
            return None
        destino = PT._archivo(m["nombre"])
        if os.path.exists(destino) and os.path.normcase(destino) != os.path.normcase(self._modelo_archivo):
            r = QMessageBox.question(self, "🎭 PNGTuber", f"Ya hay un avatar «{m['nombre']}». ¿Reemplazarlo?")
            if r != QMessageBox.Yes:
                return None
        ruta = PT.guardar(m)
        self._modelo_archivo = ruta
        self._llenar_modelos(ruta)
        self.estado.setText(f"💾 Guardado en «Mis PNGTubers»: {m['nombre']}")
        return ruta

    def _borrar_modelo(self):
        arch = self.modelos.currentData()
        if arch == NUEVO:
            return
        r = QMessageBox.question(self, "🎭 PNGTuber", f"¿Quitar «{self.modelos.currentText()[2:]}» de "
                                 "«Mis PNGTubers»? (Tus imágenes no se borran.)")
        if r == QMessageBox.Yes:
            PT.borrar({"archivo": arch})
            self._llenar_modelos()
            self._modelo_elegido()

    def _modelo_cambiado(self):
        """Nuevas imágenes: miniaturas de la vista previa y botón de crear."""
        self._pix = {}
        rs = PT.rutas(self.modelo())
        if "cerrada" in rs:
            base = QPixmap(rs["cerrada"])
            if not base.isNull():
                for k, r in rs.items():
                    px = QPixmap(r)
                    if px.isNull():
                        continue
                    if px.size() != base.size():
                        px = px.scaled(base.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._pix[k] = px.scaled(VISTA, VISTA, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._actualizar_boton()
        self._recalc.start()

    # ------------------------------------------------------------------ voz
    def _audios(self) -> list[tuple[Clip, str]]:
        """Los clips con sonido de la línea de tiempo: (clip, texto)."""
        p = self.ctrl.project
        out = []
        con_pareja = {c.link for c in p.clips.values() if c.link and p.track(c.track_id) is not None
                      and p.track(c.track_id).kind == TRACK_AUDIO}
        for c in sorted(p.clips.values(), key=lambda c: (c.start, p.track_index(c.track_id))):
            tr = p.track(c.track_id)
            m = p.media_of(c)
            if tr is None or m is None or c.is_text or getattr(m, "gen", None):
                continue
            if tr.kind == TRACK_AUDIO and m.kind in (KIND_AUDIO, KIND_VIDEO):
                pass
            elif tr.kind == TRACK_VIDEO and m.kind == KIND_VIDEO and m.has_audio and c.volume > 0 \
                    and not (c.link and c.link in con_pareja):
                pass
            else:
                continue
            voz = " 🎙" if tr.role == "voz" else ""
            out.append((c, f"{tr.name}{voz} · {m.name} · {fmt_time(c.start, frac=False)} → "
                           f"{fmt_time(c.end, frac=False)}"))
        return out

    def _llenar_audios(self, preferido: str | None):
        p = self.ctrl.project
        lista = self._audios()
        self.audio.blockSignals(True)
        self.audio.clear()
        for c, txt in lista:
            self.audio.addItem(txt, c.id)
        ids = [c.id for c, _t in lista]
        elegido = preferido if preferido in ids else None
        if elegido is None:
            sel = getattr(getattr(self.win, "timeline", None), "selected", None) or set()
            elegido = next((i for i in ids if i in sel), None)
        if elegido is None:
            voz = [c for c, _t in lista if p.track(c.track_id).role == "voz"]
            narr = [c for c, _t in lista if c.media_id in (p.transcripts or {}) or
                    c.media_id == getattr(p.subtitles, "media_id", "")]
            todos = voz or narr or [c for c, _t in lista]
            if todos:
                elegido = max(todos, key=lambda c: c.duration).id
        if elegido is not None:
            self.audio.setCurrentIndex(ids.index(elegido))
        self.audio.blockSignals(False)
        if not lista:
            self.estado.setText("No hay audio en la línea de tiempo: pon primero tu narración.")

    def clip_audio(self) -> Clip | None:
        cid = self.audio.currentData()
        return self.ctrl.project.clips.get(cid) if cid else None

    def _picos(self, c: Clip):
        mid = c.media_id
        pk = self.ctrl.peaks.get(mid)
        if pk is None:
            pk = self.ctrl.ensure_peaks(mid, wait=False)
        if pk is None:
            self._esperando_picos = mid
        return pk

    def _picos_llegaron(self):
        if self._esperando_picos and self._esperando_picos in self.ctrl.peaks:
            self._esperando_picos = ""
            self._recalc.start()

    def _parametros(self, c: Clip) -> dict:
        p = self.ctrl.project
        a = self.ajustes()
        alto = PT.alto_en_px(a["tamano"], p.height)
        tiene = PT.rutas(self.modelo())
        return {"sensibilidad": a["sensibilidad"], "fps": FPS,
                "parpadeo": PT.PARPADEO.get(a["parpadeo"]) if "ojos" in tiene else None,
                "media_boca": "media" in tiene,
                "rebote_px": PT.rebote_para(alto) if a["rebote"] else 0.0,
                "inicio": c.source_in, "fin": c.source_in + c.src_len, "velocidad": c.speed}

    def _recalcular(self):
        c = self.clip_audio()
        if c is None:
            self._ests = []
            self._eventos = []
            self._llenar_reacciones(None)
            self.onda.texto = "Sin audio"
            self.onda.update()
            self._actualizar_boton()
            return
        pk = self._picos(c)
        if pk is None:
            self._ests = []
            self.onda.texto = "Leyendo el sonido…"
            self.onda.update()
            self._actualizar_boton()
            return
        kw = self._parametros(c)
        ini, fin = kw.pop("inicio"), kw.pop("fin")
        self._ests = PT.estados(pk, media_tools.PEAK_RATE, ini, fin, **kw)
        self._eventos = self._reacciones(c, len(self._ests))
        self._ests = PT.aplicar_reacciones(self._ests, self._eventos, FPS)
        self._llenar_reacciones(c)
        vol = PT.volumen_por_fotograma(pk, media_tools.PEAK_RATE, ini, fin, FPS, kw["velocidad"])
        abrir, _cerrar, _entera, ref = PT.umbrales(vol, kw["sensibilidad"])
        abierta = np.array([e.boca_abierta for e in self._ests], bool)
        self.onda.poner(vol, abierta, abrir, ref)
        # bucle de la vista previa: 8 s desde un poco antes de la primera vez que hablas
        n = len(self._ests)
        primero = int(np.argmax(abierta)) if abierta.any() else 0
        a = max(0, primero - FPS // 2)
        self._bucle = (a, min(n, a + int(BUCLE * FPS)))
        self._frame = self._bucle[0]
        self._actualizar_boton()

    # ------------------------------------------------------------------ vista previa
    def _paso(self):
        a, b = self._bucle
        if not self._pix or not self._ests or b <= a:
            self._dibujar(None)
            return
        if not (a <= self._frame < b):
            self._frame = a
        e = self._ests[self._frame]
        self.onda.cabezal = self._frame
        self.onda.update()
        nombre = dict((k, n) for k, n, _r, _d in PT.REACCIONES).get(e.reaccion, "")
        self.vista_t.setText(fmt_time((self._frame) / FPS, frac=False) + (f"  ·  {nombre}" if nombre else ""))
        self._dibujar(e)
        self._frame += 1

    def _dibujar(self, e):
        W, H = self.vista.width(), self.vista.height()
        lienzo = QPixmap(W, H)
        lienzo.fill(QColor(40, 42, 48))
        q = QPainter(lienzo)
        paso = 12
        for y in range(0, H, paso):                              # cuadros: «aquí será transparente»
            for x in range((y // paso) % 2 * paso, W, 2 * paso):
                q.fillRect(x, y, paso, paso, QColor(52, 54, 60))
        if self._pix:
            tiene = set(self._pix)
            if "ojos" not in tiene:
                tiene.discard("ojos_abierta")
            if e is not None and "ojos" not in tiene:
                e = e._replace(ojos_cerrados=False)
            clave = PT.imagen_para(e, tiene) if e is not None else "cerrada"
            px = self._pix.get(clave) or self._pix.get("cerrada")
            if px is not None:
                alto_real = PT.alto_en_px(self.tamano.value() / 100, self.ctrl.project.height)
                zoom = 0.8 if self._eventos else 1.0     # (con reacciones: sitio para saltar sin salirse)
                k = px.height() * zoom / max(1, alto_real)
                sube = (e.rebote_px if e is not None else 0.0) * k
                q.save()
                q.setRenderHint(QPainter.SmoothPixmapTransform)
                ih = px.height() * zoom
                if e is not None and e.movido():
                    q.translate(W / 2 + e.dx * ih, H - sube + e.dy * ih)
                    q.rotate(e.giro)
                    q.scale(e.escala * zoom, e.escala * zoom)
                else:
                    q.translate(W / 2, H - sube)
                    q.scale(zoom, zoom)
                q.drawPixmap(int(-px.width() / 2), -px.height(), px)
                q.restore()
        else:
            q.setPen(QColor(170, 170, 170))
            q.drawText(QRectF(0, 0, W, H), Qt.AlignCenter, "Elige «😐 Boca cerrada»\ny «😮 Boca abierta»")
        q.end()
        self.vista.setPixmap(lienzo)

    # ------------------------------------------------------------------ crear
    def _actualizar_boton(self):
        ok = not PT.falta(self.modelo()) and self.clip_audio() is not None and self.job is None
        self.btn_crear.setEnabled(ok)
        if self.job is None:
            if PT.falta(self.modelo()):
                self.btn_crear.setToolTip("Falta: " + ", ".join(PT.falta(self.modelo())) + ".")
            elif self.clip_audio() is None:
                self.btn_crear.setToolTip("Elige de qué audio sale la voz.")
            else:
                self.btn_crear.setToolTip("Crea el video del avatar (en segundo plano) y lo pone encima de todo, "
                                          "donde empieza la voz, con el fondo verde ya quitado. Un Ctrl+Z lo quita.")

    def crear(self):
        """Crea el video en segundo plano; al terminar, lo pone en la línea de tiempo. Devuelve el trabajo."""
        from .jobs import BackgroundJob
        c = self.clip_audio()
        modelo = self.modelo()
        if c is None or PT.falta(modelo) or self.job is not None:
            return None
        p = self.ctrl.project
        m = p.media_of(c)
        kw = self._parametros(c)
        ini, fin = kw.pop("inicio"), kw.pop("fin")
        n = max(1, int(round((fin - ini) / max(1e-3, float(kw.get("velocidad") or 1.0)) * FPS)))
        eventos = self._reacciones(c, n)
        alto = PT.alto_en_px(self.tamano.value() / 100.0, p.height)
        fondo = PT.fondo_para(modelo)
        nombre = "".join(ch for ch in modelo["nombre"] if ch.isalnum() or ch in " -_")[:40].strip() or "PNGTuber"
        salida = os.path.join(PT.carpeta_videos(getattr(self.ctrl, "path", None)),
                              f"{nombre} {time.strftime('%Y-%m-%d %H-%M-%S')}.mp4")
        picos = self.ctrl.peaks.get(c.media_id)
        ruta_audio = m.path if m is not None else ""
        destino = {"proyecto": p, "clip": c.id, "start": c.start, "dur": c.duration, "fondo": fondo, "alto": alto,
                   "posicion": self.posicion.currentData(), "nombre": modelo["nombre"]}

        def work(progress, cancelled):
            pk = picos
            if pk is None:
                progress(0.0, "Leyendo el sonido…")
                pk = media_tools.waveform_peaks(ruta_audio)
            ests = PT.aplicar_reacciones(PT.estados(pk, media_tools.PEAK_RATE, ini, fin, **kw), eventos, FPS)
            return PT.renderizar(modelo, ests, salida, alto, FPS, progress, cancelled, verde=fondo)

        self.job = BackgroundJob(work, self)
        self.job.title = "🎭 PNGTuber"
        self.job.progress.connect(self._progreso)
        self.job.done.connect(lambda r, d=destino: self._poner(r, d))
        self.job.failed.connect(self._fallo)
        self.job.finished.connect(self._fin)
        self.barra.setValue(0)
        self.barra.setVisible(True)
        self.btn_cancelar.setVisible(True)
        self.btn_crear.setEnabled(False)
        self.estado.setText("🎭 Creando el avatar…")
        self.job.start()
        return self.job

    def _progreso(self, f: float, txt: str):
        self.barra.setValue(int(max(0.0, min(1.0, f)) * 1000))
        if txt:
            self.estado.setText(txt)

    def _cancelar(self):
        if self.job is not None:
            self.job.cancel()
            self.estado.setText("Cancelando…")

    def _fallo(self, msg: str):
        self.estado.setText("✗ " + (msg or "No se pudo crear el avatar."))

    def _fin(self):
        job, self.job = self.job, None
        if job is not None:
            job.deleteLater()
        self.barra.setVisible(False)
        self.btn_cancelar.setVisible(False)
        self._actualizar_boton()

    def _poner(self, res: dict, d: dict) -> str | None:
        """Importa el video a Medios y lo pone en una pista de video por encima de todo (un paso de Ctrl+Z)."""
        ctrl = self.ctrl
        self.resultado = res
        if d.get("proyecto") is not None and ctrl.project is not d["proyecto"]:
            ctrl.import_now([res["ruta"]], quiet=True)      # (cambiaste de proyecto mientras se creaba: a Medios)
            self.estado.setText("✓ Avatar creado y en Medios. No lo puse en la línea de tiempo porque cambiaste de "
                                "proyecto: arrástralo desde Medios.")
            return None
        ids = ctrl.import_now([res["ruta"]], quiet=True)
        if not ids:
            self.estado.setText("✗ No se pudo importar el video del avatar.")
            return None
        mid = ids[0]
        mm = ctrl.project.media[mid]
        if not mm.duration:
            mm.duration = float(res["duracion"])
        if not mm.width:
            mm.width, mm.height, mm.fps = int(res["ancho"]), int(res["alto"]), float(FPS)
        mm.has_audio = False
        fx = {"chroma": PT.chroma_para(d["fondo"])}

        def fn(p):
            from ..core.controller import EditError
            c = p.clips.get(d["clip"])
            a = c.start if c is not None else d["start"]
            dur = max(1.0 / FPS, min(float(res["duracion"]), float(mm.duration or res["duracion"])))
            vt = [t for t in p.tracks if t.kind == TRACK_VIDEO]
            if not vt:
                raise EditError("No hay pistas de video.")
            arriba = vt[0]
            libre = not arriba.locked and all(o.end <= a + 1e-6 or o.start >= a + dur - 1e-6
                                              for o in p.clips_on(arriba.id))
            tid = arriba.id if libre else ctrl._new_track_for(p, TRACK_VIDEO)
            lay = PT.layout(int(res["ancho"]), int(res["alto"]), p.width, p.height, d["posicion"])
            nc = Clip(new_id(), mid, tid, a, 0.0, dur, volume=0.0, layout=lay, fx=dict(fx),
                      note=f"🎭 PNGTuber · {d['nombre']}")
            p.clips[nc.id] = nc
            return nc.id

        cid = ctrl._edit("🎭 Poner PNGTuber", fn)
        if not cid:
            self.estado.setText("✗ No se pudo poner el avatar en la línea de tiempo.")
            return None
        self.creado = cid
        tl = getattr(self.win, "timeline", None)
        if tl is not None and hasattr(tl, "set_selection"):
            try:
                tl.set_selection([cid])
            except Exception:  # noqa: BLE001 - seleccionar es un extra
                pass
        self.estado.setText(f"✓ Avatar puesto en {fmt_time(d['start'], frac=False)} (Ctrl+Z lo quita). "
                            f"Video: {os.path.basename(res['ruta'])}")
        return cid

    def closeEvent(self, e):
        self.timer.stop()
        if self.job is not None:
            self.job.cancel()
        try:
            self.ctrl.peaks_changed.disconnect(self._picos_llegaron)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)


def abrir(win, audio_clip_id: str | None = None) -> PNGTuberDialog:
    """Abre la ventana 🎭 PNGTuber (no bloquea la edición) y la devuelve. audio_clip_id: el clip de la voz."""
    d = PNGTuberDialog(win, audio_clip_id)
    d.setAttribute(Qt.WA_DeleteOnClose)
    d.setModal(False)
    d.show()
    return d
