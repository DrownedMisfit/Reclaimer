"""
📦 «Recopilar proyecto»: copia el proyecto con todos sus archivos a una carpeta (respaldo, otro disco u otro PC).
Tu proyecto abierto y tus archivos originales no cambian.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QRadioButton, QVBoxLayout)

from ..core import collect as CO
from .jobs import BackgroundJob


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


class CollectDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.job = None
        self.result_path = None
        self.setWindowTitle("📦 Recopilar proyecto")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel("Hace una COPIA del proyecto con todos sus archivos en una carpeta: para guardarlo de respaldo "
                       "o llevarlo a otro disco u otro PC. Tu proyecto y tus archivos no se tocan.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Carpeta"))
        st = QSettings("EditorIA", "EditorIA")
        default = os.path.join(os.path.expanduser("~"), "Videos", "Reclaimer", "Proyectos recopilados")
        self.dest = QLineEdit(str(st.value("recopilar/carpeta", "") or default))
        row.addWidget(self.dest, 1)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick)
        row.addWidget(b)
        lay.addLayout(row)
        self.r_full = QRadioButton("Archivos completos (rápido y exacto)")
        self.r_trim = QRadioButton(f"Solo lo que se usa de los videos largos (+{CO.MARGIN:.0f} s de margen; "
                                   "ocupa mucho menos, tarda más)")
        (self.r_trim if st.value("recopilar/trozos", "false") == "true" else self.r_full).setChecked(True)
        self.unused = QCheckBox("Incluir también lo de la biblioteca que no está en la línea de tiempo")
        for w in (self.r_full, self.r_trim, self.unused):
            lay.addWidget(w)
            (w.toggled if hasattr(w, "toggled") else w.stateChanged).connect(self._summary)
        self.dest.textChanged.connect(self._summary)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.b_open = QPushButton("📂 Abrir la carpeta")
        self.b_open.clicked.connect(self._open_folder)
        self.b_open.hide()
        self.b_go = QPushButton("📦 Recopilar")
        self.b_go.setObjectName("primary")
        self.b_go.clicked.connect(self._go)
        self.b_close = QPushButton("Cerrar")
        self.b_close.clicked.connect(self._close)
        btns.addWidget(self.b_open)
        btns.addStretch(1)
        btns.addWidget(self.b_close)
        btns.addWidget(self.b_go)
        lay.addLayout(btns)
        self._summary()

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "¿Dónde dejo la copia?", self.dest.text())
        if d:
            self.dest.setText(d)

    def _summary(self, *_a):
        p = self.ctrl.project
        items = CO.plan(p, self.r_trim.isChecked(), self.unused.isChecked())
        size = sum(it["bytes"] for it in items)
        n_trim = sum(1 for it in items if it["mode"] == "trim")
        miss = [p.media[it["media_id"]].name for it in items if not it["exists"]]
        txt = f"{len(items)} archivos · unos {_gb(size)}"
        if n_trim:
            txt += f" · {n_trim} video(s) recortados a lo que usas"
        try:
            base = self.dest.text().strip()
            while base and not os.path.exists(base):
                base = os.path.dirname(base)
            free = shutil.disk_usage(base).free if base else None
        except OSError:
            free = None
        if free is not None:
            txt += f" · libre en ese disco: {_gb(free)}"
        self._fits = free is None or free > size * 1.05
        if not self._fits:
            txt += "  ⚠️ No cabe: elige otra carpeta o «Solo lo que se usa»."
        if miss:
            txt += f"\n⚠️ No se encuentran {len(miss)} archivo(s) (no irán en la copia): {', '.join(miss[:3])}"
        self.info.setText(txt)
        self.b_go.setEnabled(bool(items) and self._fits and self.job is None)

    def _go(self):
        dest = self.dest.text().strip()
        if not dest:
            return
        os.makedirs(dest, exist_ok=True)
        st = QSettings("EditorIA", "EditorIA")
        st.setValue("recopilar/carpeta", dest)
        st.setValue("recopilar/trozos", "true" if self.r_trim.isChecked() else "false")
        trim, unused = self.r_trim.isChecked(), self.unused.isChecked()
        project = self.ctrl.project
        self.job = BackgroundJob(lambda prog, canc: CO.run(project, dest, trim, unused, prog, canc), self)
        self.job.title = "📦 Recopilar proyecto"
        self.job.progress.connect(lambda f, t: (self.bar.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(self._done)
        self.job.failed.connect(self._failed)
        for w in (self.r_full, self.r_trim, self.unused, self.dest, self.b_go):
            w.setEnabled(False)
        self.b_close.setText("Cancelar")
        self.bar.show()
        self.job.start()

    def _done(self, path):
        self.job = None
        self.result_path = path
        self.bar.setValue(1000)
        self.status.setText(f"✓ Listo: {path}\nÁbrelo con «Archivo → Abrir proyecto» cuando quieras (aunque muevas la "
                            "carpeta entera, encuentra sus archivos).")
        self.b_close.setText("Cerrar")
        self.b_open.show()

    def _failed(self, msg):
        self.job = None
        self.status.setText("Cancelado: no se dejó ninguna copia a medias." if msg == "Cancelado." else f"⚠️ {msg}")
        self.b_close.setText("Cerrar")
        for w in (self.r_full, self.r_trim, self.unused, self.dest):
            w.setEnabled(True)
        self._summary()

    def _open_folder(self):
        if self.result_path:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.result_path)])

    def _close(self):
        if self.job is not None:
            self.job.cancel()
            self.status.setText("Cancelando…")
            return
        self.accept()

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
        super().closeEvent(e)
