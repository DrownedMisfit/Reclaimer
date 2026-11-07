"""
⚖ Comparar A y B de la miniatura: las dos versiones lado a lado, como se verían en YouTube (grandes y en el móvil),
con un selector de tema oscuro o claro. Debajo de cada una, «Quedarme con A» / «Quedarme con B».
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core import thumb_review as R


class CompareDialog(QDialog):
    def __init__(self, parent, snap_a: str, snap_b: str, title: str, on_pick):
        """snap_a / snap_b: la miniatura guardada (json). on_pick(«A» o «B»): la pone en el taller."""
        super().__init__(parent)
        self.setWindowTitle("⚖ Comparar A y B")
        self.resize(1000, 620)
        self._snaps = {"A": snap_a, "B": snap_b}
        self._title = title
        self._on_pick = on_pick
        self._fmt = json.loads(snap_a)["format"]
        if self._fmt == "short":
            self._anchos = (270, R.SHORTS_SIZES[1][1])          # grande y «en móvil»
        else:
            self._anchos = (480, R.YT_SIZES[1][1])
        self._pics: dict[str, tuple[QLabel, QLabel]] = {}
        self._botones: dict[str, QPushButton] = {}

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tema:"))
        self._tema = QComboBox()
        self._tema.addItem("Oscuro", True)
        self._tema.addItem("Claro", False)
        self._tema.setToolTip("Cómo se ve en YouTube con el tema oscuro o el claro")
        self._tema.currentIndexChanged.connect(lambda _i: self._render())
        top.addWidget(self._tema)
        top.addStretch(1)
        lay.addLayout(top)

        cols = QHBoxLayout()
        for key in ("A", "B"):
            col = QVBoxLayout()
            titulo = QLabel(f"<b>{key}</b>")
            titulo.setStyleSheet("font-size: 13pt;")
            col.addWidget(titulo)
            grande = QLabel()
            pequeno = QLabel()
            col.addWidget(grande, alignment=Qt.AlignTop)
            fila = QHBoxLayout()
            fila.addWidget(pequeno, alignment=Qt.AlignTop)
            fila.addStretch(1)
            col.addLayout(fila)
            cap = QLabel("Grande · en el móvil")
            cap.setObjectName("dim")
            col.addWidget(cap)
            col.addStretch(1)
            boton = QPushButton(f"✓ Quedarme con {key}")
            boton.setToolTip(f"Pone la versión {key} en la miniatura (Ctrl+Z vuelve a la anterior)")
            boton.clicked.connect(lambda _=False, k=key: self._elegir(k))
            col.addWidget(boton)
            self._pics[key] = (grande, pequeno)
            self._botones[key] = boton
            cols.addLayout(col, 1)
        lay.addLayout(cols)
        self._render()

    def _render(self):
        oscuro = bool(self._tema.currentData())
        fondo, texto = ("#0f0f0f", "#f1f1f1") if oscuro else ("#f2f2f2", "#0f0f0f")
        self.setStyleSheet(f"QDialog {{ background: {fondo}; }} QLabel {{ color: {texto}; }}")
        for key in ("A", "B"):
            doc = json.loads(self._snaps[key])
            grande, pequeno = self._pics[key]
            grande.setPixmap(QPixmap.fromImage(R.simulate(doc, self._anchos[0], self._title, dark=oscuro)))
            pequeno.setPixmap(QPixmap.fromImage(R.simulate(doc, self._anchos[1], self._title, dark=oscuro)))

    def _elegir(self, key: str):
        self._on_pick(key)
        self.accept()
