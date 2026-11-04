"""
📑 «Capítulos para YouTube»: el texto «0:00 Intro · 3:12 Jugabilidad…» listo para pegar en la descripción.
Sale de tus marcadores con nombre (M en la línea de tiempo) o de los temas de la narración. Puedes cambiar los
nombres aquí (se guardan en los marcadores; Ctrl+Z) y quitar los que no quieras.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHeaderView)

from ..core import chapters as CH
from . import help as help_ui


class ChaptersDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.setWindowTitle("📑 Capítulos para YouTube")
        help_ui.set_help(self, "capitulos")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Desde"))
        self.source = QComboBox()
        self.source.addItem("Lo mejor que haya (marcadores con nombre o, si no, los temas)", "auto")
        self.source.addItem("Mis marcadores", "marcadores")
        self.source.addItem("Los temas de la narración (IA)", "temas")
        self.source.currentIndexChanged.connect(self._fill)
        row.addWidget(self.source, 1)
        lay.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Empieza", "Nombre del capítulo (doble clic para cambiarlo)"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)
        lay.addWidget(QLabel("Para pegar en la descripción del video:"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFixedHeight(130)
        lay.addWidget(self.text)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #e8c33a;")
        lay.addWidget(self.warn)
        btns = QHBoxLayout()
        b_copy = QPushButton("📋 Copiar")
        b_copy.setObjectName("primary")
        b_copy.clicked.connect(self.copy)
        b_save = QPushButton("💾 Guardar .txt…")
        b_save.clicked.connect(self.save)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns.addWidget(b_copy)
        btns.addWidget(b_save)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lay.addLayout(btns)
        self.status = QLabel("")
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        self.resize(640, 560)
        self._loading = False
        self._fill()

    def _fill(self, *_):
        from .common import fmt_time
        self._loading = True
        self.rows = CH.candidates(self.ctrl.project, self.source.currentData())
        self.table.setRowCount(len(self.rows))
        for i, (t, title, mid) in enumerate(self.rows):
            it = QTableWidgetItem(fmt_time(t))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setToolTip("Quita la marca para no usarlo como capítulo")
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, QTableWidgetItem(title))
        self._loading = False
        self._update()

    def chosen(self) -> list[tuple[float, str]]:
        out = []
        for i, (t, _title, _mid) in enumerate(self.rows):
            if self.table.item(i, 0).checkState() == Qt.Checked:
                out.append((t, self.table.item(i, 1).text()))
        return out

    def _edited(self, it):
        if self._loading:
            return
        if it.column() == 1:              # el nombre nuevo se guarda en su marcador (Ctrl+Z)
            mid = self.rows[it.row()][2]
            name = it.text().strip()
            if name:
                self.ctrl.update_marker(mid, label=name)
        self._update()

    def _update(self):
        txt, warn = CH.build(self.chosen(), self.ctrl.project.duration())
        self.text.setPlainText(txt)
        self.warn.setText("\n".join("⚠ " + w for w in warn))

    def copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.status.setText("📋 Copiado: pégalo en la descripción del video en YouTube.")

    def save(self):
        folder = os.path.dirname(self.ctrl.path) if self.ctrl.path else os.path.dirname(self.win.default_export_path())
        path, _ = QFileDialog.getSaveFileName(self, "Guardar capítulos",
                                              os.path.join(folder, f"{self.ctrl.project.name} - capítulos.txt"),
                                              "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText() + "\n")
            self.status.setText(f"💾 Guardado en {path}")
