"""
Ventana «✂ Shorts desde este video»: Reclaimer propone los mejores momentos de tu narración para Shorts (45–75 s).

  · ▶ Ver: reproduce ese tramo en el visor.
  · ✓ Crear Short: guarda un proyecto nuevo (formato Short) con SOLO ese tramo, en la carpeta del proyecto
    (o en datos/ si todavía no tiene archivo). El video largo no cambia.
  · Después puedes abrir el Short en la pestaña 📱 Shorts.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..ai import short_picker
from ..core.paths import app_data_dir
from . import help as help_ui


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60:02d}:{s % 60:02d}"


class ShortsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctrl = win.ctrl
        self.setWindowTitle("✂ Shorts desde este video")
        self.resize(640, 560)
        self.setModal(True)
        self.picks: list[dict] = []
        self.created: list[str] = []
        self.last: str | None = None
        self.rows: list[tuple[QPushButton, dict]] = []

        lay = QVBoxLayout(self)
        intro = QLabel("Mejores momentos de tu narración para Shorts (45–75 s)")
        intro.setToolTip("Cada Short se guarda como un proyecto aparte; el video largo no cambia.\n"
                         "Si editas el largo después, vuelve a abrir esta ventana.")
        help_ui.set_help(intro, "shorts_video")
        lay.addWidget(intro)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.box = QWidget()
        self.vbox = QVBoxLayout(self.box)
        self.vbox.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.box)
        lay.addWidget(scroll, 1)

        pie = QHBoxLayout()
        self.btn_all = QPushButton("✓ Crear todos")
        self.btn_all.setToolTip("Crea un Short por cada propuesta (los que ya creaste no se repiten).")
        self.btn_all.clicked.connect(self._create_all)
        self.btn_open = QPushButton("Abrir en la pestaña Shorts")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_last)
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        pie.addWidget(self.btn_all)
        pie.addWidget(self.btn_open)
        pie.addStretch(1)
        pie.addWidget(btn_close)
        lay.addLayout(pie)

        self._load()

    # ------------------------------------------------------------ propuestas
    def _load(self):
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # (los picos que falten se leen al momento: short_picker los pide si no están)
            peaks = dict(getattr(self.ctrl, "peaks", {}) or {})
            self.picks = short_picker.pick_shorts(self.ctrl.project, n=5, min_s=45, max_s=75, peaks=peaks)
        except Exception as exc:  # noqa: BLE001 - se explica en vez de cerrarse
            self.picks = []
            self.status.setText(f"No pude calcular las propuestas: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        if not self.picks:
            self.status.setText("No encuentro tramos de 45 a 75 segundos. Necesito una narración con voz "
                                "(transcrita con 🎙 Transcribir).")
            self.btn_all.setEnabled(False)
            return
        self.status.setText(f"{len(self.picks)} propuestas, de mejor a peor.")
        for i, pk in enumerate(self.picks, 1):
            self.vbox.addWidget(self._card(i, pk))

    def _card(self, i: int, pk: dict) -> QFrame:
        fr = QFrame()
        fr.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(fr)
        dur = pk["end"] - pk["start"]
        titulo = QLabel(f"<b>{i}. {pk['title']}</b>")
        titulo.setWordWrap(True)
        cuando = QLabel(f"{_mmss(pk['start'])} – {_mmss(pk['end'])} · {dur:.0f} s · "
                        f"puntuación {round(pk['score'] * 100)}")
        motivo = QLabel(pk["why"])
        motivo.setWordWrap(True)
        motivo.setStyleSheet("color: #9da2ab;")
        fila = QHBoxLayout()
        btn_ver = QPushButton("▶ Ver")
        btn_ver.clicked.connect(lambda _=False, p=pk: self._ver(p))
        btn_crear = QPushButton("✓ Crear Short")
        btn_crear.clicked.connect(lambda _=False, idx=i - 1: self._create_one(idx))
        self.rows.append((btn_crear, pk))
        fila.addWidget(btn_ver)
        fila.addWidget(btn_crear)
        fila.addStretch(1)
        v.addWidget(titulo)
        v.addWidget(cuando)
        v.addWidget(motivo)
        v.addLayout(fila)
        return fr

    # ------------------------------------------------------------ acciones
    def _ver(self, pk: dict):
        eng = self.win.engine
        eng.pause()
        eng.user_seek(pk["start"])
        eng.play_ranges([(pk["start"], pk["end"])])

    def _folder(self) -> str:
        if self.ctrl.path:
            return os.path.dirname(self.ctrl.path)
        return str(app_data_dir())

    def _create_one(self, idx: int) -> str | None:
        pk = self.picks[idx]
        try:
            path = short_picker.write_short(self.ctrl.project, pk, idx + 1, self._folder())
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo crear el Short", str(exc))
            return None
        self.created.append(path)
        self.last = path
        for btn, p in self.rows:
            if p is pk:
                btn.setText("✓ Creado")
                btn.setEnabled(False)
        self.btn_open.setEnabled(True)
        self.status.setText(f"Creado: {path}")
        return path

    def _create_all(self):
        nuevos = 0
        for idx, (btn, pk) in enumerate(self.rows):
            if not btn.isEnabled():
                continue
            if self._create_one(idx):
                nuevos += 1
        if nuevos:
            self.status.setText(f"Creados {nuevos} Shorts en {self._folder()}. "
                                f"Puedes abrir el último en la pestaña Shorts.")
        self.btn_all.setEnabled(False)

    def _open_last(self):
        if not self.last:
            return
        if self.win.workspaces.open_into(self.last):
            self.accept()


def open_shorts_dialog(win) -> None:
    """Abre la ventana (modal). Sin ventanas en las pruebas: se usa ShortsDialog directamente."""
    dlg = ShortsDialog(win)
    dlg.exec()
