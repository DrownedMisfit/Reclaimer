"""
🔁 Convertir (menú «Convertir», junto a Ayuda): arrastra videos o audios desde tus carpetas (o «➕ Añadir»),
elige MP4 o MP3 y a qué carpeta (botones rápidos: Escritorio, Descargas, Videos, Música, Exportados…).
Se convierten uno detrás de otro en segundo plano; el original nunca se toca.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QRadioButton, QVBoxLayout)

from ..core import convert as CV
from ..core import media as media_tools
from ..core.model import kind_for_path


def quick_folders() -> list[tuple[str, str]]:
    """Carpetas de tu PC para guardar con un clic."""
    from ..core.paths import PROGRAM_DIR
    out = []
    for name, loc in (("🖥 Escritorio", QStandardPaths.DesktopLocation),
                      ("⬇ Descargas", QStandardPaths.DownloadLocation),
                      ("🎬 Videos", QStandardPaths.MoviesLocation), ("🎵 Música", QStandardPaths.MusicLocation)):
        p = QStandardPaths.writableLocation(loc)
        if p and os.path.isdir(p):
            out.append((name, p))
    out.append(("📦 Exportados", str(PROGRAM_DIR / "Exportados")))
    return out


class _DropList(QListWidget):
    def __init__(self, add):
        super().__init__()
        self._add = add
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._add([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()


class ConvertWindow(QDialog):
    def __init__(self, parent=None, fmt: str = "mp4"):
        super().__init__(parent)
        self.setWindowTitle("🔁 Convertir videos y audios")
        self.setMinimumSize(620, 460)
        self.st = QSettings("EditorIA", "EditorIA")
        lay = QVBoxLayout(self)
        tip = QLabel("Arrastra aquí tus videos o audios (desde tus carpetas) o pulsa «➕ Añadir…». "
                     "El original no se toca.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.list = _DropList(self.add_files)
        self.list.setMinimumHeight(200)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_add = QPushButton("➕ Añadir…")
        b_add.clicked.connect(self._browse)
        b_clear = QPushButton("Vaciar")
        b_clear.clicked.connect(self.list.clear)
        row.addWidget(b_add)
        row.addWidget(b_clear)
        row.addStretch(1)
        row.addWidget(QLabel("Convertir a:"))
        self.mp4 = QRadioButton("MP4 (video)")
        self.mp3 = QRadioButton("MP3 (solo audio)")
        grp = QButtonGroup(self)
        grp.addButton(self.mp4)
        grp.addButton(self.mp3)
        (self.mp3 if fmt == "mp3" else self.mp4).setChecked(True)
        row.addWidget(self.mp4)
        row.addWidget(self.mp3)
        lay.addLayout(row)
        lay.addWidget(QLabel("Guardar en:"))
        chips = QHBoxLayout()
        chips.setSpacing(4)
        for name, path in quick_folders():
            b = QPushButton(name)
            b.setToolTip(path)
            b.setObjectName("flat")
            b.clicked.connect(lambda _=False, p=path: self._set_folder(p))
            chips.addWidget(b)
        b_other = QPushButton("📁 Otra…")
        b_other.setObjectName("flat")
        b_other.clicked.connect(self._choose_folder)
        chips.addWidget(b_other)
        chips.addStretch(1)
        lay.addLayout(chips)
        self.folder_lbl = QLabel("")
        self.folder_lbl.setObjectName("dim")
        lay.addWidget(self.folder_lbl)
        from ..core.paths import PROGRAM_DIR
        self._set_folder(str(self.st.value("convertir/carpeta", "") or (PROGRAM_DIR / "Exportados")))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        b_open = QPushButton("📂 Abrir la carpeta")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder)))
        self.b_go = QPushButton("🔁 Convertir")
        self.b_go.setObjectName("primary")
        self.b_go.clicked.connect(self.start)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        bottom.addWidget(b_open)
        bottom.addStretch(1)
        bottom.addWidget(b_close)
        bottom.addWidget(self.b_go)
        lay.addLayout(bottom)

    def add_files(self, paths):
        have = {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())}
        for p in paths:
            if os.path.isdir(p):
                self.add_files([os.path.join(p, f) for f in sorted(os.listdir(p))])
                continue
            if p in have or kind_for_path(p) not in ("video", "audio"):
                continue
            it = QListWidgetItem(f"⏳ {os.path.basename(p)}")
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
            have.add(p)

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Videos o audios para convertir", "",
                                                "Video y audio (*.mp4 *.mkv *.mov *.avi *.webm *.flv *.wmv *.m4v "
                                                "*.ts *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma)")
        self.add_files(paths)

    def _set_folder(self, path: str):
        self.folder = path
        self.st.setValue("convertir/carpeta", path)
        self.folder_lbl.setText(f"→ {path}")

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Guardar en…", self.folder)
        if d:
            self._set_folder(d)

    def start(self):
        from .task_window import manager
        items = [self.list.item(i) for i in range(self.list.count())
                 if self.list.item(i).text().startswith("⏳")]
        if not items:
            self.status.setText("Arrastra antes algún video o audio a la lista.")
            return
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        folder = self.folder
        jobs = [(it, it.data(Qt.UserRole)) for it in items]

        def work(progress, cancelled):
            done = []
            for k, (_it, path) in enumerate(jobs):
                try:
                    dur = float(media_tools.probe(path)["duration"])
                except Exception:  # noqa: BLE001
                    dur = 0.0
                name = os.path.basename(path)
                out = CV.convert(path, fmt, folder, dur,
                                 lambda f, k=k, name=name: progress((k + f) / len(jobs), f"🔁 {name} · {int(f * 100)} %"),
                                 cancelled)
                done.append((path, out))
            return done

        def done(results):
            outs = dict(results)
            for it, path in jobs:
                if path in outs:
                    it.setText(f"✓ {os.path.basename(path)} → {os.path.basename(outs[path])}")
            self.status.setText(f"✓ {len(results)} archivo(s) convertidos en {folder}")
            self.b_go.setEnabled(True)

        def fail(msg):
            self.status.setText("✗ " + msg)
            self.b_go.setEnabled(True)
        self.b_go.setEnabled(False)
        self.status.setText("Convirtiendo… (puedes seguir editando; el indicador naranja enseña cómo va)")
        manager().start(f"🔁 Convertir {len(jobs)} archivo(s) a {fmt.upper()}", work, done, fail)
