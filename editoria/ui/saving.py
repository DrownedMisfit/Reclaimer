"""
💾 Guardado como en DaVinci Resolve, para no perder nada:

  · Guardado en vivo («Live Save»): cada cambio se guarda solo en tu proyecto (2,5 s después del último cambio,
    para no molestar mientras arrastras). Si el proyecto aún no tiene nombre, va al autoguardado (y al abrir tras
    un cierre inesperado se ofrece recuperarlo).
  · Copias de seguridad («Project Backups»): cada X minutos mientras trabajas se guarda una copia con fecha y
    hora; se conservan las últimas N.
  · ⟲ Recuperar una copia: lista de copias de este proyecto con fecha y hora; se abre como copia (al guardar
    te pregunta dónde, así nunca se pisa el original sin querer).
Los ajustes se recuerdan (QSettings «guardado/…»).
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QObject, QSettings, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from ..core.paths import backups_dir
from . import help as help_ui


_CFG: dict | None = None      # ⚡ se lee una vez (antes, en cada edición); se vuelve a leer al cambiar los ajustes


def _cfg(fresh: bool = False):
    """fresh=True: se lee de nuevo (para lo que pasa de tarde en tarde, como las copias de seguridad)."""
    global _CFG
    if _CFG is None or fresh:
        s = QSettings("EditorIA", "EditorIA")
        _CFG = {"live": str(s.value("guardado/vivo", "true")).lower() == "true",
                "every": int(s.value("guardado/copias_min", 10)),
                "keep": int(s.value("guardado/conservar", 40))}
    return dict(_CFG)


def backups_of(name: str) -> list[str]:
    """Copias de seguridad de un proyecto (más recientes primero)."""
    stem = os.path.splitext(os.path.basename(name))[0]
    files = [str(p) for p in backups_dir().glob(f"{stem}_*.eia")]
    return sorted(files, key=os.path.getmtime, reverse=True)


class SaveManager(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.last_save: float | None = None
        self.stopped = False
        self.last_backup = time.time()
        self._changed_since_backup = False
        self.label = QLabel("")
        self.label.setObjectName("dim")
        self.label.setToolTip("Clic: ajustes de guardado y copias de seguridad")
        self.label.mousePressEvent = lambda _e: self.open_settings()
        win.statusBar().addPermanentWidget(self.label)
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(2500)
        self._live.timeout.connect(self.live_save)
        self._backup = QTimer(self)
        self._backup.timeout.connect(self.periodic_backup)
        self._tick = QTimer(self)
        self._tick.setInterval(5000)
        self._tick.timeout.connect(self._update_label)
        self._tick.start()
        self.ctrl.undo_group.indexChanged.connect(lambda _i: self._changed())
        self.ctrl.media_changed.connect(self._changed)
        self.ctrl.saved.connect(lambda _p: self._saved())
        self.apply_settings()

    def apply_settings(self):
        global _CFG
        _CFG = None
        c = _cfg()
        self._backup.setInterval(max(1, c["every"]) * 60_000)
        self._backup.start()
        self._update_label()

    def stop(self):
        """Al cerrar: se para todo (y se ignoran los avisos que lleguen mientras Qt va borrando cosas)."""
        self.stopped = True
        for t in (self._live, self._backup, self._tick):
            t.stop()

    def _dirty(self) -> bool | None:
        try:
            return bool(self.ctrl.dirty)
        except RuntimeError:          # el historial ya se borró (cerrando)
            return None

    def _changed(self):
        if self.stopped or self._dirty() is None or getattr(self.ctrl, "_switching", False):
            return
        self._changed_since_backup = True
        if _cfg()["live"] and self.ctrl.dirty:
            self._live.start()          # se reinicia con cada cambio: guarda cuando paras un momento
        self._update_label()

    def _saved(self):
        self.last_save = time.time()
        self._update_label()

    def live_save(self):
        """Guardado en vivo: al archivo del proyecto (o al autoguardado si aún no tiene nombre)."""
        if self.stopped or not self._dirty():
            return
        try:
            if self.ctrl.path:
                self.ctrl.save(self.ctrl.path, backup=False)
            else:
                self.ctrl.write_autosave()
                self.last_save = time.time()
        except OSError as exc:
            self.win.statusBar().showMessage(f"⚠ No se pudo guardar: {exc}", 8000)
        self._update_label()

    def periodic_backup(self):
        """Copia de seguridad con fecha y hora (solo si cambió algo desde la anterior)."""
        if self.stopped or not self._changed_since_backup or self._dirty() is None:
            return
        try:
            if self.ctrl.path and os.path.exists(self.ctrl.path):
                if self.ctrl.dirty:
                    self.ctrl.save(self.ctrl.path, backup=False)
                self.ctrl.backup_now(self.ctrl.path, keep=_cfg(fresh=True)["keep"])
            else:
                self.ctrl.write_autosave()
                from ..core.paths import autosave_path
                self.ctrl.backup_now(str(autosave_path()), keep=_cfg(fresh=True)["keep"],
                                     name=self.ctrl.project.name or "Proyecto sin guardar")
            self._changed_since_backup = False
            self.last_backup = time.time()
        except OSError:
            pass

    def _update_label(self):
        if self.stopped or self._dirty() is None:
            return
        live = _cfg()["live"]
        if not self.ctrl.path:
            txt = "💾 Sin nombre: se autoguarda · guárdalo una vez (Ctrl+S)" if live else "💾 Sin guardar"
        elif self.ctrl.dirty:
            txt = "💾 Guardando…" if (live and self._live.isActive()) else "● Cambios sin guardar"
        elif self.last_save:
            ago = int(time.time() - self.last_save)
            txt = "💾 Guardado " + ("ahora" if ago < 5 else (f"hace {ago} s" if ago < 60 else f"hace {ago // 60} min"))
        else:
            txt = "💾 Guardado"
        if live and self.ctrl.path:
            txt += " · en vivo"
        self.label.setText(txt)

    def open_settings(self):
        SaveSettingsDialog(self, self.win).exec()


class SaveSettingsDialog(QDialog):
    def __init__(self, mgr: SaveManager, parent=None):
        super().__init__(parent)
        self.mgr, self.ctrl = mgr, mgr.ctrl
        self.setWindowTitle("💾 Guardado y copias de seguridad")
        self.resize(560, 560)
        help_ui.set_help(self, "guardado")
        st = QSettings("EditorIA", "EditorIA")
        c = _cfg()
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.live = QCheckBox("Guardado en vivo: cada cambio se guarda solo (como el «Live Save» de Resolve)")
        self.live.setChecked(c["live"])
        self.live.toggled.connect(lambda v: (st.setValue("guardado/vivo", "true" if v else "false"),
                                             self.mgr.apply_settings()))
        f.addRow(self.live)
        self.every = QSpinBox()
        self.every.setRange(1, 120)
        self.every.setSuffix(" min")
        self.every.setValue(c["every"])
        self.every.valueChanged.connect(lambda v: (st.setValue("guardado/copias_min", v), self.mgr.apply_settings()))
        f.addRow("Copia de seguridad cada", self.every)
        self.keep = QSpinBox()
        self.keep.setRange(5, 500)
        self.keep.setValue(c["keep"])
        self.keep.valueChanged.connect(lambda v: (st.setValue("guardado/conservar", v), self.mgr.apply_settings()))
        f.addRow("Conservar las últimas", self.keep)
        lay.addLayout(f)
        name = self.ctrl.path or (self.ctrl.project.name or "Proyecto sin guardar")
        lay.addWidget(QLabel(f"<b>⟲ Copias de «{os.path.splitext(os.path.basename(name))[0]}»</b> "
                             "(doble clic = abrir como copia)"))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self._open())
        lay.addWidget(self.list, 1)
        for p in backups_of(name):
            t = time.localtime(os.path.getmtime(p))
            it = QListWidgetItem(f"{time.strftime('%d/%m/%Y  %H:%M:%S', t)}   ·   {os.path.getsize(p) / 1024:.0f} KB")
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
        if not self.list.count():
            it = QListWidgetItem("(todavía no hay copias: se crean solas mientras trabajas)")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        row = QHBoxLayout()
        b_open = QPushButton("⟲ Abrir esta copia")
        b_open.clicked.connect(self._open)
        b_now = QPushButton("💾 Hacer una copia ahora")
        b_now.clicked.connect(self._backup_now)
        b_dir = QPushButton("📂 Carpeta de copias")
        b_dir.clicked.connect(lambda: os.startfile(str(backups_dir())))
        close = QPushButton("Cerrar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        for b in (b_open, b_now, b_dir):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    def _backup_now(self):
        self.mgr._changed_since_backup = True
        self.mgr.periodic_backup()
        self.accept()
        self.mgr.open_settings()

    def _open(self):
        it = self.list.currentItem()
        p = it.data(Qt.UserRole) if it else None
        if not p:
            return
        win = self.mgr.win
        if not win._confirm_discard():
            return
        try:
            self.ctrl.load(p, recovered=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "No se pudo abrir", str(exc))
            return
        self.ctrl.path = None          # como copia: al guardar te pregunta dónde (no pisa el original)
        self.ctrl._set_media_dirty()
        win.statusBar().showMessage("⟲ Copia abierta. Guárdala (Ctrl+S) donde quieras.", 10000)
        self.accept()
