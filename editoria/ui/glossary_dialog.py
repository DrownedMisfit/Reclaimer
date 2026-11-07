"""📖 Glosario de «Dijiste…»: dos listas, «Sí son palabras clave» y «No son palabras clave».
Se trabaja en memoria y se guarda al cerrar (si cambió algo). Datos: editoria/ai/keyword_glossary.py."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from ..ai import keyword_glossary as KG
from . import help as AYUDA


class GlosarioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        AYUDA.set_help(self, "glosario")
        self.setWindowTitle("Glosario de palabras clave")
        self.setMinimumWidth(480)
        self.cambiado = False
        self._g = KG.load()
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Lo que confirmas aquí se respeta en «Dijiste…» y en «✨ Crear de lo que dices»."))
        cols = QHBoxLayout()
        self.lista_si = QListWidget()
        self.lista_no = QListWidget()
        for titulo, lista in (("Sí son palabras clave", self.lista_si), ("No son palabras clave", self.lista_no)):
            col = QVBoxLayout()
            col.addWidget(QLabel(f"<b>{titulo}</b>"))
            col.addWidget(lista)
            cols.addLayout(col)
        v.addLayout(cols)

        fila = QHBoxLayout()
        self.entrada = QLineEdit()
        self.entrada.setPlaceholderText("Palabra o frase, p. ej. Ruinas Eternas")
        self.tipo = QComboBox()
        self.tipo.addItem("(tipo: sin decir)")
        self.tipo.addItems(list(KG.TIPOS))
        self.tipo.setToolTip("Opcional: juego, saga, consola, compañía, persona u otro.")
        fila.addWidget(self.entrada, 1)
        fila.addWidget(self.tipo)
        v.addLayout(fila)

        botones = QHBoxLayout()
        self.btn_si = QPushButton("＋ A «Sí»")
        self.btn_si.setToolTip("Añade lo escrito a «Sí son palabras clave».")
        self.btn_si.clicked.connect(lambda: self._anadir_desde_campo("si"))
        self.btn_no = QPushButton("＋ A «No»")
        self.btn_no.setToolTip("Añade lo escrito a «No son palabras clave» (no volverá a salir en «Dijiste…»).")
        self.btn_no.clicked.connect(lambda: self._anadir_desde_campo("no"))
        self.btn_quitar = QPushButton("Quitar seleccionadas")
        self.btn_quitar.setToolTip("Quita de las dos listas lo que tengas seleccionado.")
        self.btn_quitar.clicked.connect(lambda: self.quitar_seleccion())
        botones.addWidget(self.btn_si)
        botones.addWidget(self.btn_no)
        botones.addStretch(1)
        botones.addWidget(self.btn_quitar)
        v.addLayout(botones)

        cierre = QDialogButtonBox(QDialogButtonBox.Close)
        cierre.rejected.connect(self.reject)
        v.addWidget(cierre)
        self._recargar()

    def _recargar(self):
        self.lista_si.clear()
        self.lista_no.clear()
        for k, v in sorted(self._g["si"].items(), key=lambda x: str(x[1].get("nombre") or x[0]).lower()):
            texto = str(v.get("nombre") or k) + (f"  · {v['tipo']}" if v.get("tipo") else "")
            it = QListWidgetItem(texto)
            it.setData(Qt.UserRole, ("si", k))
            self.lista_si.addItem(it)
        for k in sorted(self._g["no"]):
            it = QListWidgetItem(k)
            it.setData(Qt.UserRole, ("no", k))
            self.lista_no.addItem(it)

    def agregar(self, term: str, lista: str, tipo: str | None = None) -> bool:
        """lista: «si» o «no». Quita el término de la otra lista."""
        nombre = " ".join(str(term or "").split())
        k = KG.clave(nombre)
        if not k:
            return False
        if lista == "si":
            entrada = {"nombre": nombre}
            if tipo:
                entrada["tipo"] = tipo
            self._g["si"][k] = entrada
            self._g["no"] = [x for x in self._g["no"] if x != k]
        else:
            self._g["si"].pop(k, None)
            if k not in self._g["no"]:
                self._g["no"].append(k)
        self.cambiado = True
        self._recargar()
        return True

    def quitar_seleccion(self) -> int:
        """Quita de las listas lo seleccionado. Devuelve cuántos términos quitó."""
        quitados = 0
        for lista in (self.lista_si, self.lista_no):
            for it in lista.selectedItems():
                donde, k = it.data(Qt.UserRole)
                if donde == "si":
                    self._g["si"].pop(k, None)
                else:
                    self._g["no"] = [x for x in self._g["no"] if x != k]
                quitados += 1
        if quitados:
            self.cambiado = True
            self._recargar()
        return quitados

    def _anadir_desde_campo(self, lista: str):
        tipo = self.tipo.currentText() if self.tipo.currentIndex() > 0 else None
        if self.agregar(self.entrada.text(), lista, tipo if lista == "si" else None):
            self.entrada.clear()

    def done(self, r):
        """Al cerrar (Cerrar o Esc) se guarda lo cambiado."""
        if self.cambiado:
            try:
                KG.save(self._g)
            except OSError:
                pass
        super().done(r)
