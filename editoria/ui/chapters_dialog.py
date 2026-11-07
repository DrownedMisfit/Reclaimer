"""
📑 Capítulos para la descripción de YouTube: el texto «0:00 Intro · 3:12 Jugabilidad…».
Sale de tus marcadores con nombre (M en la línea de tiempo) o de los temas de la narración. Puedes cambiar los
nombres aquí (se guardan en los marcadores; Ctrl+Z) y quitar los que no quieras.

ChaptersPanel es la sección «Capítulos» de la ventana 📝 Descripción para YouTube (ver description_dialog.py).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import chapters as CH


class ChaptersPanel(QWidget):
    changed = Signal()          # cambian los capítulos (quitar uno, renombrar, otra fuente)

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
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
        self.table.setMinimumHeight(150)
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #e8c33a;")
        lay.addWidget(self.warn)
        self._loading = False
        self._last = ""
        self._avisos: list[str] = []
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
        self._last, self._avisos = txt, warn
        self.warn.setText("\n".join("⚠ " + w for w in warn))
        self.changed.emit()

    def text(self) -> str:
        """Los capítulos tal como saldrán en la descripción."""
        return self._last

    def warnings(self) -> list[str]:
        return list(self._avisos)


class ChaptersDialog(QDialog):
    """Solo los capítulos, en su propia ventana (la usa la prueba de la voz). La ventana principal abre
    la 📝 Descripción completa (description_dialog.py), que contiene este mismo panel."""

    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("📑 Capítulos para YouTube")
        self.resize(640, 560)
        self.panel = ChaptersPanel(win.ctrl, self)
        self.table = self.panel.table
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFixedHeight(130)
        self.panel.changed.connect(lambda: self.text.setPlainText(self.panel.text()))
        self.text.setPlainText(self.panel.text())
        b_copy = QPushButton("📋 Copiar")
        b_copy.setObjectName("primary")
        b_copy.clicked.connect(self.copy)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(b_copy)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.panel, 1)
        lay.addWidget(self.text)
        lay.addLayout(btns)

    def copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
