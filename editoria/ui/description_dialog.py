"""
📝 «Descripción para YouTube»: el texto completo de la descripción del video, con secciones que se activan o no:
párrafo inicial (por proyecto), capítulos, créditos de los clips bajados, tu pie fijo (Ko-fi, redes…) y hashtags.
Al exportar el video se guarda también «<video>.descripcion.txt» con la descripción (ver export_dialog.py).
"""
from __future__ import annotations

import hashlib
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core import credits as CR
from ..core import description as DS
from . import help as help_ui
from .chapters_dialog import ChaptersPanel


def _clave(project, path) -> str:
    return hashlib.md5(((path or project.name) or "").encode("utf-8")).hexdigest()[:12]


def prefs(project, path) -> tuple[str, str]:
    """(párrafo inicial de ESTE proyecto, pie fijo de tu cuenta) guardados en QSettings."""
    st = QSettings("EditorIA", "EditorIA")
    par = str(st.value(f"descripcion/parrafo/{_clave(project, path)}", "") or "")
    pie = str(st.value("descripcion/pie", "") or "")
    return par, pie


class DescriptionDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.project = self.ctrl.project
        self.setWindowTitle("📝 Descripción para YouTube")
        help_ui.set_help(self, "capitulos")
        self.resize(800, 780)
        par0, pie0 = prefs(self.project, self.ctrl.path)

        # ---- secciones (dentro de un área con barra, por si la ventana es baja)
        cuerpo = QWidget()
        bl = QVBoxLayout(cuerpo)
        bl.setSpacing(4)

        self.par = QPlainTextEdit(par0)
        self.par.setPlaceholderText("Presentación del video: qué se ve y por qué merece la pena. Vacío = no sale.")
        self.par.setFixedHeight(90)
        self.sec_par = self._seccion(bl, "✍ Párrafo inicial (solo para este proyecto)", self.par, activa=True)

        self.chapters = ChaptersPanel(self.ctrl)
        self.chapters.changed.connect(self._update)
        self.sec_caps = self._seccion(bl, "📑 Capítulos (marcadores con nombre o temas de la narración)",
                                      self.chapters, activa=True)

        creditos = CR.text(CR.collect(self.project))
        self.cred = QPlainTextEdit(creditos)
        self.cred.setPlaceholderText("No hay clips bajados en este proyecto.")
        self.cred.setFixedHeight(100)
        self.sec_cred = self._seccion(bl, "🎬 Créditos de los clips descargados", self.cred,
                                      activa=bool(creditos), habilitada=bool(creditos))

        self.pie = QPlainTextEdit(pie0)
        self.pie.setPlaceholderText("Tu Ko-fi, redes, aviso de suscripción… Se guarda y sale en todos tus videos.")
        self.pie.setFixedHeight(90)
        self.sec_pie = self._seccion(bl, "📌 Pie fijo (tu cuenta, para todos los videos)", self.pie, activa=True)

        tags = DS.hashtags(self.project)
        fila = QWidget()
        fl = QHBoxLayout(fila)
        fl.setContentsMargins(0, 0, 0, 0)
        self._tag_cbs: list[QCheckBox] = []
        for t in tags:
            cb = QCheckBox(t)
            cb.setChecked(True)
            cb.toggled.connect(self._update)
            fl.addWidget(cb)
            self._tag_cbs.append(cb)
        fl.addStretch(1)
        if not tags:
            fl.addWidget(QLabel("No hay menciones ni temas para sugerir."))
        self.sec_tags = self._seccion(bl, "#️⃣ Hashtags sugeridos (de las menciones y los temas)", fila,
                                      activa=bool(tags), habilitada=bool(tags))
        bl.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(cuerpo)
        area.setFrameShape(QScrollArea.NoFrame)

        # ---- vista previa y botones
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #e8c33a;")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(170)
        self.status = QLabel("")
        self.status.setObjectName("dim")
        b_copy = QPushButton("📋 Copiar")
        b_copy.setObjectName("primary")
        b_copy.clicked.connect(self.copy)
        b_save = QPushButton("💾 Guardar .txt…")
        b_save.clicked.connect(self.save)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(b_copy)
        btns.addWidget(b_save)
        btns.addStretch(1)
        btns.addWidget(b_close)

        lay = QVBoxLayout(self)
        lay.addWidget(area, 1)
        lay.addWidget(QLabel("Vista previa (así quedará en la descripción):"))
        lay.addWidget(self.preview)
        lay.addWidget(self.warn)
        lay.addLayout(btns)
        lay.addWidget(self.status)

        # Se guardan al cambiar: el párrafo por proyecto y el pie para todos los videos
        self.par.textChanged.connect(lambda: self._guardar(
            f"descripcion/parrafo/{_clave(self.project, self.ctrl.path)}", self.par.toPlainText()))
        self.pie.textChanged.connect(lambda: self._guardar("descripcion/pie", self.pie.toPlainText()))
        self.par.textChanged.connect(self._update)
        self.pie.textChanged.connect(self._update)
        self.cred.textChanged.connect(self._update)
        self._update()

    # ------------------------------------------------------------------ piezas
    def _seccion(self, bl, titulo: str, cuerpo: QWidget, activa: bool, habilitada: bool = True) -> QCheckBox:
        cb = QCheckBox(titulo)
        cb.setChecked(activa)
        cb.setEnabled(habilitada)
        cb.setToolTip("Quítala para que esta parte no salga en la descripción.")
        cuerpo.setEnabled(activa and habilitada)
        cb.toggled.connect(cuerpo.setEnabled)
        cb.toggled.connect(self._update)
        bl.addWidget(cb)
        bl.addWidget(cuerpo)
        return cb

    def _guardar(self, clave: str, valor: str) -> None:
        QSettings("EditorIA", "EditorIA").setValue(clave, valor)

    def texto(self) -> str:
        """La descripción final, con las secciones activadas."""
        return DS.compose(
            parrafo=self.par.toPlainText() if self.sec_par.isChecked() else "",
            capitulos=self.chapters.text() if self.sec_caps.isChecked() else "",
            creditos=self.cred.toPlainText() if self.sec_cred.isChecked() else "",
            pie=self.pie.toPlainText() if self.sec_pie.isChecked() else "",
            tags=[cb.text() for cb in self._tag_cbs if cb.isChecked()] if self.sec_tags.isChecked() else [])

    def _update(self, *_):
        self.preview.setPlainText(self.texto())
        avisos = self.chapters.warnings() if self.sec_caps.isChecked() else []
        self.warn.setText("\n".join("⚠ " + w for w in avisos))

    # ------------------------------------------------------------------ botones
    def copy(self):
        QApplication.clipboard().setText(self.texto())
        self.status.setText("📋 Copiado: pégalo en la descripción del video en YouTube.")

    def save(self):
        folder = os.path.dirname(self.ctrl.path) if self.ctrl.path else os.path.dirname(self.win.default_export_path())
        path, _ = QFileDialog.getSaveFileName(self, "Guardar la descripción",
                                              os.path.join(folder, f"{self.project.name} - descripción.txt"),
                                              "Texto (*.txt)")
        if path:
            self.guardar_en(path)

    def guardar_en(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.texto() + "\n")
        self.status.setText(f"💾 Guardado en {path}")
