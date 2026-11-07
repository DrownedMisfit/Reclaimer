"""
🎬 «Mi intro y mi outro»: eliges tu archivo de intro y de outro para cada tipo de proyecto (YouTube · Shorts · Edits).
«➕ Poner mi intro y outro» (menú Editar) los coloca en la línea de tiempo; la primera versión automática también
puede hacerlo al final.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from ..core import intro_outro as IO

FILTRO = "Videos e imágenes (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg);;Todos los archivos (*.*)"


class IntroOutroDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("🎬 Mi intro y mi outro")
        self.resize(660, 260)
        self._vals = {f: list(IO.get(f)) for f, _label in IO.FORMATOS}
        actual = win.ctrl.project.format
        self._fmt = actual if actual in self._vals else "youtube"
        lay = QVBoxLayout(self)
        tip = QLabel("La intro va al principio de la línea de tiempo y la outro al final. Se guarda para cada tipo de "
                     "proyecto. Si el archivo no está en Medios, se importa al ponerlo.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo de proyecto:"))
        self.fmt = QComboBox()
        for f, label in IO.FORMATOS:
            self.fmt.addItem(label, f)
        self.fmt.setCurrentIndex(self.fmt.findData(self._fmt))
        self.fmt.currentIndexChanged.connect(self._cambiar)
        row.addWidget(self.fmt)
        row.addStretch()
        lay.addLayout(row)
        grid = QGridLayout()
        self.edits: dict[str, QLineEdit] = {}
        for r, (quien, titulo) in enumerate((("intro", "Intro (al principio)"), ("outro", "Outro (al final)"))):
            grid.addWidget(QLabel(titulo), r, 0)
            ed = QLineEdit()
            ed.setReadOnly(True)
            ed.setPlaceholderText("(ninguno)")
            b_elegir = QPushButton("Elegir…")
            b_elegir.clicked.connect(lambda _=False, k=quien: self._elegir(k))
            b_quitar = QPushButton("Quitar")
            b_quitar.clicked.connect(lambda _=False, k=quien: self.edits[k].clear())
            grid.addWidget(ed, r, 1)
            grid.addWidget(b_elegir, r, 2)
            grid.addWidget(b_quitar, r, 3)
            self.edits[quien] = ed
        lay.addLayout(grid)
        lay.addStretch()
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Guardar")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)
        self._cargar()

    def _cargar(self):
        intro, outro = self._vals[self._fmt]
        self.edits["intro"].setText(intro)
        self.edits["outro"].setText(outro)

    def _recoger(self):
        self._vals[self._fmt] = [self.edits["intro"].text(), self.edits["outro"].text()]

    def _cambiar(self, _i=0):
        self._recoger()
        self._fmt = self.fmt.currentData()
        self._cargar()

    def _elegir(self, quien: str):
        titulo = "Elige tu intro" if quien == "intro" else "Elige tu outro"
        ruta, _ = QFileDialog.getOpenFileName(self, titulo, os.path.expanduser("~"), FILTRO)
        if ruta:
            self.edits[quien].setText(os.path.normpath(ruta))

    def _guardar(self):
        self._recoger()
        for f, (intro, outro) in self._vals.items():
            IO.set_(f, intro, outro)
        self.accept()


def open_dialog(win):
    IntroOutroDialog(win).exec()


def put_now(win, fmt: str | None = None):
    """«➕ Poner mi intro y outro»: las pone en la línea de tiempo del proyecto abierto."""
    fmt = fmt or win.ctrl.project.format
    intro, outro = IO.get(fmt)
    if not (intro or outro):
        if QMessageBox.question(win, "Mi intro y mi outro", "Aún no has elegido tu intro ni tu outro para este tipo "
                                "de proyecto.\n\n¿Elegirlos ahora?") == QMessageBox.Yes:
            open_dialog(win)
        return
    win.engine.pause()
    IO.place(win.ctrl, intro, outro)
