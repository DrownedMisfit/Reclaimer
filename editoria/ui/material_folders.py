"""
📁 Vista de carpetas de «Material» (taller de miniaturas): carpetas con su portada, en orden de abecedario; doble clic
= entrar; «⬅» = volver. Clic en una imagen = añadirla a la miniatura; doble clic = de fondo; arrastrarla = al lienzo.
Clic derecho: ⭐ Poner como principal · 🗑 Eliminar (a la Papelera; solo en las carpetas de Reclaimer) · Renombrar ·
Quitar de la lista (las tuyas vinculadas). Soltar aquí: carpetas del Explorador = vincularlas; imágenes = copiarlas a la
carpeta abierta (o a la carpeta sobre la que se sueltan).
Las miniaturas se cargan poco a poco (no se traba aunque la carpeta sea enorme).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..core import material_lib as M

ICON = 96
_icons: dict[str, QIcon] = {}


def _thumb(path: str, folder: bool = False) -> QIcon:
    key = ("📁" if folder else "") + (path or "")
    if key in _icons:
        return _icons[key]
    pm = QPixmap(ICON, ICON)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    if folder:                                               # carpeta: un fondo de carpeta con la portada dentro
        p.setBrush(QColor("#3a3b42"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 14, ICON - 8, ICON - 22, 8, 8)
        p.drawRoundedRect(4, 8, 36, 14, 4, 4)
    if path:
        r = QImageReader(path)
        r.setAutoTransform(True)
        s = r.size()
        box = ICON - 22 if folder else ICON
        if s.isValid() and s.width() > 0:
            k = min(box / s.width(), box / s.height())
            r.setScaledSize(QSize(max(1, int(s.width() * k)), max(1, int(s.height() * k))))
        img = r.read()
        if not img.isNull():
            x = (ICON - img.width()) // 2
            y = (ICON - img.height()) // 2 + (5 if folder else 0)
            p.drawImage(x, y, img)
    p.end()
    if len(_icons) > 3000:
        _icons.clear()
    _icons[key] = QIcon(pm)
    return _icons[key]


class _List(QListWidget):
    dropped = Signal(list, object)          # rutas soltadas, carpeta sobre la que se soltaron (o None)

    def mimeData(self, items):
        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)["path"]) for it in items
                   if it.data(Qt.UserRole) and it.data(Qt.UserRole).get("kind") == "image"])
        return m

    def _ext(self, e) -> bool:
        return e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()) and e.source() is not self

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if self._ext(e) else super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self._ext(e) else super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not self._ext(e):
            e.ignore()
            return
        e.acceptProposedAction()
        it = self.itemAt(e.position().toPoint())
        d = it.data(Qt.UserRole) if it is not None else None
        target = d["path"] if d and d.get("kind") == "folder" else None
        self.dropped.emit([os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()], target)


class FolderBrowser(QWidget):
    imageChosen = Signal(str)            # clic: añadir encima
    imageBackground = Signal(str)        # doble clic: de fondo
    message = Signal(str)                # para la barra de estado

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: str | None = None     # None = arriba del todo (las carpetas de Reclaimer y las tuyas)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.back = QPushButton("⬅")
        self.back.setToolTip("Volver a la carpeta de arriba")
        self.back.setFixedWidth(34)
        self.back.clicked.connect(self.go_up)
        self.where = QLabel("Carpetas")
        self.where.setObjectName("dim")
        self.where.setMinimumWidth(40)
        b_new = QPushButton("＋ Carpeta")
        b_new.setToolTip("Crear una carpeta de Reclaimer (p. ej. Fuego, Ojos, Agua). Dentro de una tuya, no se puede")
        b_new.clicked.connect(self.new_folder)
        b_link = QPushButton("🔗 Vincular…")
        b_link.setToolTip("Mostrar aquí una carpeta tuya del disco (sin copiar nada). También puedes soltarla aquí "
                          "desde el Explorador")
        b_link.clicked.connect(self.link_dialog)
        row.addWidget(self.back)
        row.addWidget(self.where, 1)
        row.addWidget(b_new)
        row.addWidget(b_link)
        v.addLayout(row)
        self.list = _List()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(ICON, ICON))
        self.list.setGridSize(QSize(ICON + 22, ICON + 34))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.setDragEnabled(True)
        self.list.setAcceptDrops(True)
        self.list.setDragDropMode(QListWidget.DragDrop)
        self.list.setDefaultDropAction(Qt.CopyAction)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._double)
        self.list.dropped.connect(self._dropped)
        v.addWidget(self.list, 1)
        self._pending: list[QListWidgetItem] = []
        self._loader = QTimer(self)
        self._loader.setInterval(15)
        self._loader.timeout.connect(self._load_some)
        self.populate()

    # ------------------------------------------------------------------ contenido
    def open(self, path: str | None):
        self.path = path
        self.populate()

    def go_up(self):
        if self.path is None:
            return
        tops = {os.path.normcase(r["path"]) for r in M.roots()}
        if os.path.normcase(self.path) in tops:
            self.open(None)
        else:
            self.open(os.path.dirname(self.path))

    def populate(self):
        self._loader.stop()
        self._pending = []
        self.list.clear()
        self.back.setEnabled(self.path is not None)
        if self.path is None:
            self.where.setText("Carpetas")
            self.where.setToolTip("")
            for r in M.roots():
                self._add_folder(r["path"], r["name"], r["managed"])
            for s in M.suggestions():
                it = QListWidgetItem(_thumb("", folder=True), "＋ " + (os.path.basename(s.rstrip("\\/")) or s))
                it.setData(Qt.UserRole, {"kind": "suggestion", "path": s})
                it.setForeground(QColor("#8a8f99"))
                it.setToolTip(f"Sugerencia: vincular {s} (clic)")
                self.list.addItem(it)
            if self.list.count() == 0:
                self.message.emit("Crea una carpeta («＋ Carpeta») o vincula una tuya («🔗 Vincular…»).")
        else:
            self.where.setText(os.path.basename(self.path.rstrip("\\/")) or self.path)
            self.where.setToolTip(self.path)
            subs, imgs = M.list_dir(self.path)
            managed = M.is_managed(self.path)
            for s in subs:
                self._add_folder(s, os.path.basename(s), managed)
            for p in imgs:
                it = QListWidgetItem(os.path.splitext(os.path.basename(p))[0][:22])
                it.setData(Qt.UserRole, {"kind": "image", "path": p, "managed": managed})
                it.setToolTip(p)
                self.list.addItem(it)
                self._pending.append(it)
        self._loader.start()

    def _add_folder(self, path: str, name: str, managed: bool):
        it = QListWidgetItem(name[:22])
        it.setData(Qt.UserRole, {"kind": "folder", "path": path, "managed": managed})
        it.setToolTip(("Carpeta de Reclaimer" if managed else "Carpeta tuya (vinculada)") + f"\n{path}")
        self.list.addItem(it)
        self._pending.append(it)

    def _load_some(self):
        """Las miniaturas, de pocas en pocas (la lista se ve enseguida aunque haya cientos)."""
        for _ in range(12):
            if not self._pending:
                self._loader.stop()
                return
            it = self._pending.pop(0)
            try:
                d = it.data(Qt.UserRole)
            except RuntimeError:                              # (la lista ya cambió)
                continue
            if d["kind"] == "folder":
                it.setIcon(_thumb(M.cover(d["path"]) or "", folder=True))
            else:
                it.setIcon(_thumb(d["path"]))

    # ------------------------------------------------------------------ clics
    def _clicked(self, it):
        d = it.data(Qt.UserRole)
        if d["kind"] == "image":
            self.imageChosen.emit(d["path"])
        elif d["kind"] == "suggestion":
            if M.link(d["path"]):
                self.message.emit(f"✓ Vinculada: {d['path']}")
            self.populate()

    def _double(self, it):
        d = it.data(Qt.UserRole)
        if d["kind"] == "folder":
            self.open(d["path"])
        elif d["kind"] == "image":
            self.imageBackground.emit(d["path"])

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        m = QMenu(self)
        if it is None:
            if self.path is None or M.is_managed(self.path):
                m.addAction("＋ Carpeta nueva…", self.new_folder)
            m.addAction("🔗 Vincular una carpeta mía…", self.link_dialog)
        else:
            d = it.data(Qt.UserRole)
            if d["kind"] == "image":
                m.addAction("⭐ Poner como principal", lambda: self.set_main(d["path"]))
                if d.get("managed"):
                    m.addAction("🗑 Eliminar (a la Papelera)", lambda: self.delete(d["path"]))
                m.addAction("Mostrar en el Explorador", lambda: self._explorer(d["path"]))
            elif d["kind"] == "folder":
                m.addAction("Abrir", lambda: self.open(d["path"]))
                if d.get("managed"):
                    m.addAction("Renombrar…", lambda: self.rename(d["path"]))
                    m.addAction("🗑 Eliminar carpeta (a la Papelera)", lambda: self.delete(d["path"]))
                elif self.path is None:
                    m.addAction("Quitar de la lista (no se borra nada)", lambda: (M.unlink(d["path"]),
                                                                                  self.populate()))
                m.addAction("Mostrar en el Explorador", lambda: self._explorer(d["path"]))
            else:
                m.addAction("🔗 Vincular", lambda: (M.link(d["path"]), self.populate()))
        m.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ acciones
    def set_main(self, image: str):
        folder = os.path.dirname(image)
        M.set_cover(folder, image)
        for k in [k for k in _icons if k.startswith("📁")]:
            _icons.pop(k, None)
        self.message.emit(f"⭐ Portada de «{os.path.basename(folder)}»: {os.path.basename(image)}")

    def new_folder(self, name: str | None = None) -> str | None:
        if self.path is not None and not M.is_managed(self.path):
            self.message.emit("Esta carpeta es tuya: las carpetas nuevas se crean en las de Reclaimer.")
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, "Carpeta nueva", "Nombre (p. ej. Fuego, Ojos, Agua):")
            if not ok or not name.strip():
                return None
        p = M.create(name, self.path)
        self.populate()
        return p

    def rename(self, folder: str):
        name, ok = QInputDialog.getText(self, "Renombrar", "Nombre nuevo:", text=os.path.basename(folder))
        if ok and name.strip() and M.rename(folder, name):
            self.populate()

    def delete(self, path: str, confirm: bool = True) -> bool:
        what = "la carpeta y lo que tiene dentro" if os.path.isdir(path) else "la imagen"
        if confirm and QMessageBox.question(self, "Eliminar", f"¿Mandar {what} a la Papelera?\n{path}") != \
                QMessageBox.StandardButton.Yes:
            return False
        ok = M.trash(path)
        self.message.emit("🗑 A la Papelera (se puede recuperar)." if ok else "No se pudo eliminar.")
        self.populate()
        return ok

    def link_dialog(self):
        sug = M.suggestions(1)
        d = QFileDialog.getExistingDirectory(self, "Vincular una carpeta tuya", sug[0] if sug else "")
        if d and M.link(d):
            self.message.emit(f"✓ Vinculada: {d}")
            self.open(None)

    def _dropped(self, paths: list[str], target: str | None) -> int:
        """Carpetas soltadas = vincularlas; imágenes = copiarlas a la carpeta (la de debajo o la abierta)."""
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p) and M.is_image(p)]
        n = 0
        if dirs and target is None and (self.path is None or not M.is_managed(self.path)):
            n += sum(1 for d in dirs if M.link(d))
            if n:
                self.message.emit(f"✓ {n} carpeta(s) vinculada(s) (se ven en su sitio, sin copiar)")
            self.open(None)
            return n
        dest = target or self.path
        for d in dirs:                                       # (una carpeta soltada DENTRO de una de Reclaimer)
            files += [os.path.join(r, f) for r, _s, fs in os.walk(d) for f in fs if M.is_image(f)][:500]
        if not files:
            return 0
        if dest is None:
            self.message.emit("Suelta las imágenes encima de una carpeta (o ábrela primero).")
            return 0
        if not M.is_managed(dest):
            self.message.emit("Esa carpeta es tuya: aquí no se copia nada en ella. Usa una carpeta de Reclaimer.")
            return 0
        n = len(M.add_files(dest, files))
        self.message.emit(f"✓ {n} imagen(es) en «{os.path.basename(dest)}»")
        self.populate()
        return n

    def _explorer(self, path: str):
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)] if os.path.isfile(path)
                         else ["explorer", os.path.normpath(path)])
