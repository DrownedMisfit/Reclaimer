"""
👤 Enseñar un personaje por su SILUETA: haces clic encima de él en un fotograma; SAM 2.1 recorta su figura y la
IA aprende su forma, sus líneas (sombras, armadura) y sus colores, sin el fondo. Con 2–5 ejemplos (otros
momentos u otros clips) lo reconoce mejor. Luego «🔎 Buscarlo en mis videos» (o en Momentos → «Lo que conoce la IA»).
Sin el motor de IA, se usa el recuadro que dibujes (arrastrando) como silueta.
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout)

from ..ai import silhouette_id as SI
from ..core import media as media_tools
from ..core import motor_ia
from ..core.model import new_id
from .subject_cut_dialog import _Marker


class SilhouetteTeachDialog(QDialog):
    def __init__(self, win, clip_id: str, t: float):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        p = self.ctrl.project
        self.c = p.clips[clip_id]
        self.m = p.media_of(self.c)
        self.setWindowTitle("👤 Enseñar un personaje (silueta)")
        from .help import set_help
        set_help(self, "silueta")
        lay = QVBoxLayout(self)
        tip = QLabel("<b>Clic encima del personaje</b>: verás en verde la silueta que va a aprender. Si le falta algo "
                     "(pelo, casco, arma), haz clic también ahí; clic derecho = esto no; arrastrar = recuadro. "
                     "2–5 ejemplos en momentos distintos lo hacen más fiable.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        row.addWidget(QLabel("Personaje:"))
        self.name = QComboBox()
        self.name.setEditable(True)
        for n, k in SI.names().items():
            self.name.addItem(n)
        self.name.setCurrentText("")
        self.name.lineEdit().setPlaceholderText("p. ej. Anya")
        row.addWidget(self.name, 1)
        lay.addLayout(row)
        self.local = min(max(t - self.c.start, 0.0), max(0.0, self.c.duration - 0.05))
        self.view = None
        self._ready = None                     # (marcas, silueta) ya calculada y mostrada
        self._busy = False
        self._again = QTimer(self)
        self._again.setSingleShot(True)
        self._again.setInterval(350)
        self._again.timeout.connect(self._preview)
        self.holder = QVBoxLayout()
        lay.addLayout(self.holder, 1)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Momento:"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(1, int(self.c.duration * 10)))
        self.slider.setValue(int(self.local * 10))
        self.slider.sliderReleased.connect(lambda: self._load(self.slider.value() / 10))
        srow.addWidget(self.slider, 1)
        lay.addLayout(srow)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.b_add = QPushButton("✓ Guardar este ejemplo")
        self.b_add.setObjectName("primary")
        self.b_add.clicked.connect(self.save_example)
        self.b_find = QPushButton("🔎 Buscarlo en mis videos")
        self.b_find.clicked.connect(self.find)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns.addWidget(self.b_add)
        btns.addWidget(self.b_find)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lay.addLayout(btns)
        self.resize(760, 640)
        self._load(self.local)

    def _load(self, local: float):
        self.local = local
        self.src_t = self.c.src_at(local)
        rgb = media_tools.frame_rgb(self.m.path, self.src_t, 960)
        if rgb is None:
            self.status.setText("No se pudo leer ese fotograma.")
            return
        self.rgb = rgb
        if self.view is not None:
            self.holder.removeWidget(self.view)
            self.view.deleteLater()
        self.view = _Marker(rgb)
        self.view.changed.connect(self._again.start)
        self.holder.addWidget(self.view, 1)
        self._ready = None

    def _key(self, marks: dict):
        return (marks["video"], round(marks["t0"], 3), str(marks["puntos"]), str(marks["caja"]))

    def _show_mask(self, view, mask: np.ndarray):
        h, w = mask.shape
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., 1] = 220
        rgba[..., 3] = (mask > 127) * 110                      # la silueta, en verde
        view.mask = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        view.update()

    def _preview(self):
        """Muestra en verde la silueta que aprenderá (con SAM 2.1), en cuanto marcas."""
        if self.view is None or not (self.view.points or self.view.box) or not motor_ia.available("sam")[0]:
            return
        if self._busy:
            self._again.start()
            return
        from .task_window import manager
        marks, view = self._marks(), self.view
        self._busy = True
        self.status.setText("👁 Recortando la silueta…")

        def done(mask):
            self._busy = False
            try:
                if view is not self.view or self._key(marks) != self._key(self._marks()):
                    return                      # ya marcaste otra cosa: se recalcula
                self._ready = (self._key(marks), mask)
                self._show_mask(view, mask)
                self.status.setText("En verde, lo que aprenderá. ¿Falta algo? Clic encima de lo que falte; clic "
                                    "derecho en lo que sobre. Si está bien: «✓ Guardar este ejemplo».")
            except RuntimeError:
                pass

        def fail(msg):
            self._busy = False
            try:
                self.status.setText("✗ " + msg)
            except RuntimeError:
                pass
        manager().start("👤 Ver silueta", lambda pr, ca: self.mask_of(marks, pr, ca), done, fail)

    # ------------------------------------------------------------ la silueta
    def _marks(self) -> dict:
        """Lo marcado ahora (se copia: el trabajo va en segundo plano y puedes mover «Momento» mientras)."""
        box = self.view.box
        return {"rgb": self.rgb, "video": self.m.path, "t0": self.src_t, "fps": float(self.m.fps or 30.0),
                "puntos": [list(pt) for pt in self.view.points],
                "caja": [box.left(), box.top(), box.right(), box.bottom()] if box else None}

    @staticmethod
    def mask_of(marks: dict, progress=None, cancelled=None) -> np.ndarray:
        """Silueta del personaje marcado: con SAM 2.1 si está el motor; si no, el recuadro dibujado."""
        h, w = marks["rgb"].shape[:2]
        ok, _why = motor_ia.available("sam")
        if ok and (marks["puntos"] or marks["caja"]):
            import cv2
            from ..core import subject_mask as SMK
            out = os.path.join(SMK.out_dir(), f"silueta_{new_id()}.png")
            fast = motor_ia.SAM_FAST_MODEL.exists()
            job = {"modo": "imagen", "ffmpeg": media_tools.ffmpeg(), "video": marks["video"], "t0": marks["t0"],
                   "fps": marks["fps"], "salida": out, "a": 0.0, "b": 0.0, "puntos": marks["puntos"],
                   "caja": marks["caja"], "modelo": str(motor_ia.SAM_FAST_MODEL if fast else motor_ia.SAM_MODEL),
                   "config": motor_ia.SAM_FAST_CONFIG if fast else motor_ia.SAM_CONFIG, "ancho": 960, "bordes": True,
                   "ahorro": __import__("editoria.core.hw", fromlist=["x"]).equipo()["poca_vram"]}
            path = motor_ia.run("recortar.py", job, progress, cancelled)
            m = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            try:
                os.remove(path)
            except OSError:
                pass
            if m is not None and (m > 127).any():
                return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
        b = marks["caja"]
        if b is not None:
            m = np.zeros((h, w), np.uint8)
            m[int(b[1] * h):int(b[3] * h), int(b[0] * w):int(b[2] * w)] = 255
            return m
        if marks["puntos"]:                     # sin motor y solo un clic: un recuadro alrededor del clic
            x, y = marks["puntos"][0][0], marks["puntos"][0][1]
            m = np.zeros((h, w), np.uint8)
            m[int(max(0, y - 0.3) * h):int(min(1, y + 0.3) * h), int(max(0, x - 0.15) * w):int(min(1, x + 0.15) * w)] = 255
            return m
        raise RuntimeError("Marca al personaje: clic encima (o arrastra un recuadro).")

    def save_example(self):
        from .task_window import manager
        name = self.name.currentText().strip()
        if not name:
            self.status.setText("Escribe antes el nombre del personaje.")
            self.name.setFocus()
            return
        if not (self.view.points or self.view.box):
            self.status.setText("Marca al personaje: clic encima (o arrastra un recuadro).")
            return
        marks = self._marks()
        view = self.view
        self.b_add.setEnabled(False)
        self.status.setText("👤 Recortando su silueta y aprendiendo…")

        ready = self._ready[1] if self._ready and self._ready[0] == self._key(marks) else None

        def work(progress, cancelled):
            mask = ready if ready is not None else self.mask_of(marks, progress, cancelled)
            n = SI.teach(name, marks["rgb"], mask, marks["video"], marks["t0"])
            return n, mask

        def done(res):
            n, mask = res
            try:
                self.b_add.setEnabled(True)
            except RuntimeError:                # se cerró la ventana: ya está guardado igualmente
                return
            if view is self.view:
                self._show_mask(view, mask)
            if self.name.findText(name) < 0:
                self.name.addItem(name)
            self.status.setText(f"✓ «{name}» tiene {n} ejemplo(s)." + (" Mueve «Momento» y marca otro para que lo "
                                                                        "reconozca mejor." if n < 3 else
                                                                        " Ya puedes buscarlo."))
            mp = getattr(self.win, "moments", None)
            if mp is not None and hasattr(mp, "refresh_known"):
                mp.refresh_known()

        def fail(msg):
            try:
                self.b_add.setEnabled(True)
                self.status.setText("✗ " + msg)
            except RuntimeError:
                pass
        manager().start(f"👤 Aprender «{name}»", work, done, fail)

    def find(self):
        name = self.name.currentText().strip()
        if name not in SI.names():
            self.status.setText("Guarda antes al menos un ejemplo de ese personaje.")
            return
        mp = getattr(self.win, "moments", None)
        if mp is not None:
            self.win.show_panel(mp)
            mp.search_silhouette(name)
            self.close()
