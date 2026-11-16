"""
⚖ Editor de una COMPARATIVA (página 🎬 Escenas → «＋ Nueva comparativa»): dos tomas, A y B (el original y el remake,
dos versiones, un fondo y otro…), desde qué segundo de cada una, su etiqueta, y cómo se ven:
lado a lado · arriba y abajo · fundido (de una a la otra) · alternar (una, otra, una… cada N segundos).
«🔗 Sincronizar con IA» busca en B el momento que más se parece al de A. A la izquierda, la vista previa con los dos
fotogramas. Lo aplica la página (controller.apply_scene: van encima de todo, sin tapar tu video).
"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core import scenes
from ..core.model import KIND_IMAGE, KIND_VIDEO

PW, PH = 640, 360


def fotograma(path: str, t: float, ancho: int = 480) -> QImage | None:
    """El fotograma del segundo t (un video) o la imagen, pequeño, para la vista previa."""
    if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
        img = QImage(path)
        return None if img.isNull() else img
    from ..core import media as media_tools
    try:
        r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
                            "-frames:v", "1", "-vf", f"scale={ancho}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    img = QImage.fromData(r.stdout, "PNG")
    return None if img.isNull() else img


class ComparativaEditor(QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self._cargando = False
        self._job = None
        self._imgs: dict[str, QImage | None] = {"A": None, "B": None}
        self.vista = QLabel()
        self.vista.setAlignment(Qt.AlignCenter)
        self.vista.setMinimumSize(PW // 2, PH // 2)
        self.vista.setToolTip("Así se verá (con el fotograma de cada toma desde su segundo).")
        self.campos = {}
        cols = QHBoxLayout()
        for lado, titulo in (("A", "Toma A (izquierda / arriba / primero)"), ("B", "Toma B (derecha / abajo / después)")):
            g = QGroupBox(titulo)
            f = QFormLayout(g)
            medio = QComboBox()
            medio.setToolTip("Un video o una imagen de Medios.")
            desde = QDoubleSpinBox()
            desde.setRange(0.0, 99999.0)
            desde.setDecimals(2)
            desde.setSuffix(" s")
            desde.setKeyboardTracking(False)
            desde.setToolTip("Desde qué segundo de esa toma (en un video).")
            etiqueta = QLineEdit()
            etiqueta.setPlaceholderText("Ej.: Original (1998)" if lado == "A" else "Ej.: Remake (2026)")
            etiqueta.setToolTip("El texto que sale encima de esa toma (vacío = sin etiqueta).")
            f.addRow("Toma", medio)
            f.addRow("Desde", desde)
            f.addRow("Etiqueta", etiqueta)
            if lado == "B":
                self.b_sync = QPushButton("🔗 Sincronizar con IA")
                self.b_sync.setToolTip("Busca en B el momento que más se parece al de A (para comparar lo mismo).")
                self.b_sync.clicked.connect(self._sincronizar)
                f.addRow(self.b_sync)
            medio.currentIndexChanged.connect(lambda _i, ld=lado: self._cambio(ld, "media_id"))
            desde.valueChanged.connect(lambda _v, ld=lado: self._cambio(ld, "src"))
            etiqueta.textEdited.connect(lambda _t, ld=lado: self._cambio(ld, "etiqueta"))
            self.campos[lado] = (medio, desde, etiqueta)
            cols.addWidget(g)
        self.modo = QComboBox()
        for k, n in scenes.MODOS_COMP:
            self.modo.addItem(n, k)
        self.modo.setToolTip("Cómo se ven las dos tomas.")
        self.modo.currentIndexChanged.connect(lambda _i: self._cambio_modo())
        self.cada = QDoubleSpinBox()
        self.cada.setRange(0.5, 30.0)
        self.cada.setSingleStep(0.5)
        self.cada.setSuffix(" s")
        self.cada.setToolTip("Al alternar: cuánto se ve cada toma antes de pasar a la otra.")
        self.cada.valueChanged.connect(lambda _v: self._cambio_modo())
        self.estado = QLabel("")
        self.estado.setObjectName("dim")
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Cómo"))
        fila.addWidget(self.modo, 1)
        self.l_cada = QLabel("cada")
        fila.addWidget(self.l_cada)
        fila.addWidget(self.cada)
        der = QVBoxLayout()
        der.addLayout(cols)
        der.addLayout(fila)
        der.addWidget(self.estado)
        der.addStretch(1)
        lay = QHBoxLayout(self)
        lay.addWidget(self.vista, 3)
        lay.addLayout(der, 2)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._pedir_fotogramas)

    # ---------------------------------------------------------------- datos
    def comp(self) -> dict:
        return self.page.escena["comp"]

    def cargar(self):
        """La comparativa que tiene la página (al abrirla o cambiarla)."""
        self._cargando = True
        try:
            p = self.page.ctrl.project
            medios = sorted((m for m in p.media.values() if m.kind in (KIND_VIDEO, KIND_IMAGE)
                             and m.id not in self.page.ctrl.missing and not getattr(m, "gen", None)),
                            key=lambda m: m.name.lower())
            c = self.comp()
            for lado in ("A", "B"):
                medio, desde, etiqueta = self.campos[lado]
                medio.clear()
                medio.addItem("(elige una toma)", "")
                for m in medios:
                    medio.addItem(("🖼 " if m.kind == KIND_IMAGE else "🎬 ") + m.name, m.id)
                medio.setCurrentIndex(max(0, medio.findData(c[lado].get("media_id") or "")))
                desde.setValue(float(c[lado].get("src", 0.0)))
                etiqueta.setText(c[lado].get("etiqueta", ""))
            self.modo.setCurrentIndex(max(0, self.modo.findData(c.get("modo", "lado"))))
            self.cada.setValue(float(c.get("cada", 2.0)))
        finally:
            self._cargando = False
        self._visibles()
        self._pedir_fotogramas()

    def _visibles(self):
        alt = self.modo.currentData() == "alternar"
        self.cada.setVisible(alt)
        self.l_cada.setVisible(alt)

    def _cambio(self, lado: str, campo: str):
        if self._cargando:
            return
        medio, desde, etiqueta = self.campos[lado]
        c = self.comp()[lado]
        if campo == "media_id":
            c["media_id"] = medio.currentData() or ""
            if not etiqueta.text().strip() and c["media_id"]:      # (etiqueta de entrada: el nombre de la toma)
                m = self.page.ctrl.project.media.get(c["media_id"])
                if m is not None:
                    etiqueta.setText(os.path.splitext(m.name)[0][:40])
                    c["etiqueta"] = etiqueta.text()
        elif campo == "src":
            c["src"] = round(desde.value(), 3)
        else:
            c["etiqueta"] = etiqueta.text()
        self.page._ensuciar()
        if campo in ("media_id", "src"):
            self._timer.start()
        else:
            self._pintar()

    def _cambio_modo(self):
        if self._cargando:
            return
        self.comp()["modo"] = self.modo.currentData()
        self.comp()["cada"] = round(self.cada.value(), 2)
        self._visibles()
        self.page._ensuciar()
        self._pintar()

    def listo(self) -> bool:
        c = self.comp()
        return bool(c["A"].get("media_id") and c["B"].get("media_id"))

    # ---------------------------------------------------------------- vista previa
    def _pedir_fotogramas(self):
        if not scenes.es_comparativa(self.page.escena):   # (el temporizador saltó tras abrir una escena normal)
            return
        p = self.page.ctrl.project
        pedidos = {}
        for lado in ("A", "B"):
            c = self.comp()[lado]
            m = p.media.get(c.get("media_id") or "")
            pedidos[lado] = (m.path, float(c.get("src", 0.0))) if m is not None else None

        def fn(_progress, _cancelled):
            return {ld: (fotograma(*x) if x else None) for ld, x in pedidos.items()}

        def listo(imgs):
            if not scenes.es_comparativa(self.page.escena):
                return                                     # (ya estás en otra escena)
            self._imgs = imgs
            self._pintar()
        if os.environ.get("RECLAIMER_SIN_FOTOGRAMAS"):
            listo({"A": None, "B": None})
            return
        from .jobs import BackgroundJob
        self._job = BackgroundJob(fn, parent=self)
        self._job.done.connect(listo)
        self._job.start()

    def _pintar(self):
        if not scenes.es_comparativa(self.page.escena):
            return
        img = QImage(PW, PH, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor("#101114"))
        pt = QPainter(img)
        pt.setRenderHint(QPainter.SmoothPixmapTransform)
        modo = self.modo.currentData() or "lado"
        p_ = self.page.ctrl.project
        if modo == "arriba" or (modo == "lado" and p_.height > p_.width):   # (en vertical, lado a lado va arriba/abajo)
            zonas = {"A": QRectF(0, 0, PW, PH / 2), "B": QRectF(0, PH / 2, PW, PH / 2)}
        else:
            zonas = {"A": QRectF(0, 0, PW / 2, PH), "B": QRectF(PW / 2, 0, PW / 2, PH)}
        for lado, r in zonas.items():
            im = self._imgs.get(lado)
            if im is not None:                         # (llenando la zona, recortando lo que sobra)
                k = max(r.width() / im.width(), r.height() / im.height())
                w, h = im.width() * k, im.height() * k
                pt.save()
                pt.setClipRect(r)
                pt.drawImage(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), im)
                pt.restore()
            else:
                pt.setPen(QColor("#6b6f78"))
                pt.drawText(r, Qt.AlignCenter, f"Toma {lado}")
            tx = (self.comp()[lado].get("etiqueta") or "").strip()
            if tx:
                f = QFont(self.font())
                f.setPointSize(13)
                f.setBold(True)
                pt.setFont(f)
                caja = QRectF(r.x() + 8, r.y() + 10, r.width() - 16, 30)
                pt.fillRect(caja.adjusted(caja.width() / 2 - pt.fontMetrics().horizontalAdvance(tx) / 2 - 10, 0,
                                          -(caja.width() / 2 - pt.fontMetrics().horizontalAdvance(tx) / 2 - 10), 0),
                            QColor(0, 0, 0, 170))
                pt.setPen(QColor("#ffffff"))
                pt.drawText(caja, Qt.AlignCenter, tx)
        if modo in ("fundido", "alternar"):            # (la vista previa enseña las dos; abajo, qué pasa)
            pt.setPen(QColor("#ffd166"))
            f = QFont(self.font())
            f.setPointSize(11)
            pt.setFont(f)
            txt = ("A se funde en B a mitad de la escena" if modo == "fundido" else
                   f"A, B, A… cada {self.cada.value():g} s")
            pt.fillRect(QRectF(0, PH - 30, PW, 30), QColor(0, 0, 0, 160))
            pt.drawText(QRectF(0, PH - 30, PW, 30), Qt.AlignCenter, txt)
        pt.end()
        self.vista.setPixmap(QPixmap.fromImage(img).scaled(self.vista.size(), Qt.KeepAspectRatio,
                                                           Qt.SmoothTransformation))
        self.estado.setText("" if self.listo() else "Elige las dos tomas (A y B).")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._pintar()

    # ---------------------------------------------------------------- 🔗 sincronizar con IA
    def _sincronizar(self):
        p = self.page.ctrl.project
        c = self.comp()
        ma, mb = p.media.get(c["A"].get("media_id") or ""), p.media.get(c["B"].get("media_id") or "")
        if ma is None or mb is None or mb.kind != KIND_VIDEO:
            self.estado.setText("Para sincronizar, elige dos tomas y que B sea un video.")
            return
        from .compare_dialog import find_matching_moment
        from .jobs import BackgroundJob
        ta = float(c["A"].get("src", 0.0))
        self.b_sync.setEnabled(False)
        self.estado.setText("🔗 Buscando en B el momento que más se parece…")

        def fn(progress, cancelled):
            return find_matching_moment(ma.path, ta, ma.width, ma.height, mb.path, mb.duration, mb.width, mb.height,
                                        progress, cancelled)

        def listo(res):
            self.b_sync.setEnabled(True)
            if not scenes.es_comparativa(self.page.escena):
                return
            t, parecido = res
            self.campos["B"][1].setValue(round(t, 2))
            self.estado.setText(f"✓ B desde {t:.2f} s (se parece un {parecido * 100:.0f} %)")

        def fallo(msg):
            self.b_sync.setEnabled(True)
            self.estado.setText(f"No se pudo sincronizar: {msg[-160:]}")
        self._job_sync = BackgroundJob(fn, parent=self)
        self._job_sync.done.connect(listo)
        self._job_sync.failed.connect(fallo)
        self._job_sync.start()
