"""
Ventana «Comparación»: dos clips en pantalla dividida, con su etiqueta encima.
Sirve para cualquier comparación (original y remake, dos juegos, dos versiones, antes y después…).
Con «Sincronizar con IA» se busca en el clip derecho el momento que más se parece al del izquierdo.
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from ..ai import embeddings, tracking
from ..core.model import KIND_IMAGE, KIND_VIDEO, ORIGIN_USER
from .common import fmt_time
from .jobs import BackgroundJob


def find_matching_moment(path_a: str, t_a: float, wa: int, ha: int, path_b: str, dur_b: float,
                         wb: int, hb: int, progress=None, cancelled=None) -> tuple[float, float]:
    """Segundo del clip derecho (B) que más se parece al fotograma t_a del izquierdo (A), y su parecido 0–1."""
    enc = embeddings.get("clip_image", progress)

    def crops(path, start, dur, w, h, fps):
        size = tracking.work_size(w, h, 398)
        out_t, out_f = [], []
        for t, frame in tracking.read_frames(path, start, dur, size, fps):
            if cancelled and cancelled():
                break
            fh, fw = frame.shape[:2]
            x0, y0 = (fw - 224) // 2, max(0, (fh - 224) // 2)
            out_f.append(frame[y0:y0 + 224, x0:x0 + 224, ::-1])  # BGR → RGB, recorte central
            out_t.append(t)
        return out_t, out_f

    _ta, fa = crops(path_a, t_a, 0.1, wa, ha, 10)
    if not fa:
        raise RuntimeError("No se pudo leer el fotograma del clip izquierdo.")
    va = enc.encode(np.stack(fa[:1]))[0]
    fps = 2.0 if dur_b <= 600 else 1.0
    if progress:
        progress(0.2, "🔗 Buscando el momento parecido en el clip derecho…")
    tb, fb = crops(path_b, 0.0, dur_b, wb, hb, fps)
    if not fb:
        raise RuntimeError("No se pudieron leer fotogramas del clip derecho.")
    vb = enc.encode(np.stack(fb))
    sims = vb @ va
    k = int(sims.argmax())
    return float(tb[k]), float(sims[k])


class CompareDialog(QDialog):
    def __init__(self, ctrl, start: float, parent=None, origin: str = ORIGIN_USER):
        super().__init__(parent)
        self.ctrl = ctrl
        self.start = start
        self.origin = origin
        self.job: BackgroundJob | None = None
        self.setWindowTitle("Comparación")
        p = ctrl.project
        media = sorted((m for m in p.media.values() if m.kind in (KIND_VIDEO, KIND_IMAGE)
                        and m.id not in ctrl.missing), key=lambda m: m.name.lower())
        self.a = QComboBox()
        self.b = QComboBox()
        for combo in (self.a, self.b):
            for m in media:
                combo.addItem(m.name, m.id)
        if len(media) > 1:
            self.b.setCurrentIndex(1)
        self.ta = QDoubleSpinBox()
        self.tb = QDoubleSpinBox()
        for spin in (self.ta, self.tb):
            spin.setRange(0, 36000)
            spin.setDecimals(1)
            spin.setSuffix(" s")
        self.dur = QDoubleSpinBox()
        self.dur.setRange(1, 120)
        self.dur.setValue(6)
        self.dur.setSuffix(" s")
        # Las etiquetas empiezan con el nombre de cada clip; puedes escribir lo que quieras
        self.label_a = QLineEdit()
        self.label_b = QLineEdit()
        self.label_a.setPlaceholderText("Sin etiqueta")
        self.label_b.setPlaceholderText("Sin etiqueta")
        self._auto_labels = True
        self.label_a.textEdited.connect(lambda _t: setattr(self, "_auto_labels", False))
        self.label_b.textEdited.connect(lambda _t: setattr(self, "_auto_labels", False))
        self.a.currentIndexChanged.connect(self._fill_labels)
        self.b.currentIndexChanged.connect(self._fill_labels)
        self.btn_sync = QPushButton("🔗 Sincronizar con IA")
        self.btn_sync.setToolTip("Busca en el clip derecho el momento que más se parece al del izquierdo.")
        self.btn_sync.clicked.connect(self._sync)
        form = QFormLayout()
        form.addRow("Clip izquierdo", self.a)
        form.addRow("   desde el segundo", self.ta)
        form.addRow("Clip derecho", self.b)
        rb = QHBoxLayout()
        rb.addWidget(self.tb)
        rb.addWidget(self.btn_sync)
        form.addRow("   desde el segundo", rb)
        form.addRow("Duración", self.dur)
        form.addRow("Etiqueta izquierda", self.label_a)
        form.addRow("Etiqueta derecha", self.label_b)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = QLabel(f"Se colocará en {fmt_time(start)} de la timeline, en dos pistas de video.")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        ok = QPushButton("Crear comparación")
        ok.setObjectName("primary")
        ok.clicked.connect(self._create)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.setMinimumWidth(520)
        self._fill_labels()

    def _fill_labels(self):
        """Etiqueta por defecto = nombre del clip (mientras no escribas otra)."""
        if not self._auto_labels:
            return
        for combo, edit in ((self.a, self.label_a), (self.b, self.label_b)):
            m = self.ctrl.project.media.get(combo.currentData())
            edit.setText(os.path.splitext(m.name)[0].replace("_", " ").upper() if m else "")

    def _sync(self):
        p = self.ctrl.project
        ma, mb = p.media.get(self.a.currentData()), p.media.get(self.b.currentData())
        if not ma or not mb or ma.kind != KIND_VIDEO or mb.kind != KIND_VIDEO or self.job:
            return
        ta = self.ta.value()

        def work(progress, cancelled):
            return find_matching_moment(ma.path, ta, ma.width, ma.height, mb.path, mb.duration,
                                        mb.width, mb.height, progress, cancelled)

        def done(res):
            t, sim = res
            self.tb.setValue(round(t, 1))
            self.status.setText(f"✓ Momento más parecido en el clip derecho: {fmt_time(t)} (parecido {sim:.0%}). "
                                "Compruébalo en el visor después de crear la comparación.")

        self.job = BackgroundJob(work, self)
        self.job.progress.connect(lambda f, t: (self.progress.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(done)
        self.job.failed.connect(lambda msg: self.status.setText(f"✗ {msg}"))
        self.job.finished.connect(self._finished)
        self.progress.setVisible(True)
        self.btn_sync.setEnabled(False)
        self.job.start()

    def _finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.progress.setVisible(False)
        self.btn_sync.setEnabled(True)

    def _create(self):
        if self.a.currentData() == self.b.currentData():
            QMessageBox.information(self, "Comparar", "Elige dos clips distintos.")
            return
        ids = self.ctrl.add_comparison(self.a.currentData(), self.ta.value(), self.b.currentData(), self.tb.value(),
                                       self.start, self.dur.value(),
                                       (self.label_a.text().strip(), self.label_b.text().strip()), self.origin)
        if ids:
            self.accept()

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
        super().closeEvent(e)
