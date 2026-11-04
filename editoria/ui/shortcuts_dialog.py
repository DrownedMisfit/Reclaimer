"""
«⌨ Personalizar atajos»: cambia el atajo de teclado de cualquier orden de los menús. Se guarda en tus ajustes
(QSettings «atajos/<menú>/<orden>») y se aplica al momento y cada vez que abres Reclaimer.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import help as help_ui

PREFIX = "atajos/"


def saved_shortcut(key: str) -> str | None:
    """El atajo que guardaste para esa orden ("" = sin atajo) o None si no la cambiaste."""
    v = QSettings("EditorIA", "EditorIA").value(PREFIX + key)
    return None if v is None else str(v)


class ShortcutsDialog(QDialog):
    """actions: {clave: (QAction, atajo_de_fábrica)} — la clave es «Menú/Orden»."""

    def __init__(self, actions: dict, parent=None):
        super().__init__(parent)
        self.actions = actions
        self.settings = QSettings("EditorIA", "EditorIA")
        self.setWindowTitle("⌨ Personalizar atajos de teclado")
        self.resize(640, 680)
        help_ui.set_help(self, "atajos")
        lay = QVBoxLayout(self)
        tip = QLabel("Clic en el atajo de una orden y pulsa la combinación nueva (p. ej. Ctrl+X). Se guarda al "
                     "momento y se mantiene cada vez que abres Reclaimer.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar orden o atajo…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Orden", "Atajo", ""])
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 170)
        lay.addWidget(self.tree, 1)
        self.editors: dict[str, QKeySequenceEdit] = {}
        groups: dict[str, QTreeWidgetItem] = {}
        for key, (action, _default) in actions.items():
            menu, _, name = key.partition("/")
            g = groups.get(menu)
            if g is None:
                g = QTreeWidgetItem([menu])
                g.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(g)
                g.setExpanded(True)
                groups[menu] = g
            it = QTreeWidgetItem([name.replace("&", "")])
            it.setData(0, Qt.UserRole, key)
            g.addChild(it)
            ed = QKeySequenceEdit(action.shortcut())
            ed.setMaximumSequenceLength(1) if hasattr(ed, "setMaximumSequenceLength") else None
            ed.editingFinished.connect(lambda k=key: self._changed(k))
            self.tree.setItemWidget(it, 1, ed)
            b = QPushButton("↺")
            b.setToolTip("Volver al atajo de fábrica")
            b.setFixedWidth(30)
            b.clicked.connect(lambda _=False, k=key: self._reset(k))
            self.tree.setItemWidget(it, 2, b)
            self.editors[key] = ed
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        b_all = QPushButton("↺ Restablecer todos")
        b_all.clicked.connect(self._reset_all)
        b_res = QPushButton("⬇ Traer mis atajos de DaVinci Resolve…")
        b_res.setToolTip("Lee tus atajos de DaVinci Resolve (solo lectura) y te enseña cuáles cambiarían aquí: "
                         "eliges los que quieres.")
        b_res.clicked.connect(self.import_resolve)
        row.addWidget(b_res)
        close = QPushButton("Cerrar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(b_all)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    def _filter(self, text: str):
        t = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            vis = 0
            for k in range(g.childCount()):
                it = g.child(k)
                key = it.data(0, Qt.UserRole)
                seq = self.editors[key].keySequence().toString(QKeySequence.NativeText).lower()
                show = not t or t in it.text(0).lower() or t in seq or t in g.text(0).lower()
                it.setHidden(not show)
                vis += show
            g.setHidden(vis == 0)

    def set_shortcut(self, key: str, seq: QKeySequence, ask: bool = True) -> bool:
        """Pone el atajo (y lo guarda). Si otra orden lo usa, pregunta y se lo quita a la otra."""
        action, _default = self.actions[key]
        if not seq.isEmpty():
            other = next((k for k, (a, _d) in self.actions.items() if k != key and a.shortcut() == seq), None)
            if other is not None:
                if ask and QMessageBox.question(
                        self, "Atajo en uso", f"«{seq.toString(QKeySequence.NativeText)}» ya es el atajo de "
                        f"«{other.replace('/', ' → ')}».\n¿Quitárselo y ponerlo aquí?") != QMessageBox.Yes:
                    self.editors[key].setKeySequence(action.shortcut())
                    return False
                self.actions[other][0].setShortcut(QKeySequence())
                self.settings.setValue(PREFIX + other, "")
                self.editors[other].setKeySequence(QKeySequence())
        action.setShortcut(seq)
        self.settings.setValue(PREFIX + key, seq.toString(QKeySequence.PortableText))
        self.editors[key].setKeySequence(seq)
        self.msg.setText(f"✓ «{key.split('/', 1)[1].replace('&', '')}»: "
                         f"{seq.toString(QKeySequence.NativeText) or 'sin atajo'}")
        return True

    def _changed(self, key: str):
        seq = self.editors[key].keySequence()
        if seq != self.actions[key][0].shortcut():
            self.set_shortcut(key, seq)

    def _reset(self, key: str):
        action, default = self.actions[key]
        self.settings.remove(PREFIX + key)
        seq = QKeySequence(default or "")
        action.setShortcut(seq)
        self.editors[key].setKeySequence(seq)
        self.msg.setText(f"↺ «{key.split('/', 1)[1].replace('&', '')}» vuelve a "
                         f"{seq.toString(QKeySequence.NativeText) or 'sin atajo'}")

    def import_resolve(self, preselect_all: bool = False):
        """⬇ Tus atajos de DaVinci Resolve: lista «Ahora / En tu Resolve» con casillas → aplicar los marcados."""
        import os
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        from ..core import resolve_keys
        if not os.path.exists(resolve_keys.PRESET):
            self.msg.setText("No encuentro la configuración de teclado de DaVinci Resolve en este PC.")
            return None
        try:
            rows = resolve_keys.plan(self.actions)
        except (OSError, ValueError, UnicodeError) as exc:
            self.msg.setText(f"No pude leer tus atajos de Resolve: {exc}")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("⬇ Tus atajos de DaVinci Resolve")
        dlg.resize(720, 560)
        lay = QVBoxLayout(dlg)
        lab = QLabel("Las órdenes de Reclaimer que también existen en tu Resolve. Marcadas: las que cambiarían "
                     "(si un atajo ya lo usa otra orden, se le quita a esa).")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Orden", "Ahora", "En tu Resolve"])
        tree.setColumnWidth(0, 360)
        tree.setColumnWidth(1, 130)
        for key, name, now, res in rows:
            native_now = QKeySequence(now).toString(QKeySequence.NativeText) or "—"
            native_res = QKeySequence(res).toString(QKeySequence.NativeText)
            it = QTreeWidgetItem([name, native_now, native_res])
            it.setData(0, Qt.UserRole, (key, res))
            differ = QKeySequence(now) != QKeySequence(res)
            it.setCheckState(0, Qt.Checked if (differ or preselect_all) else Qt.Unchecked)
            if not differ:
                it.setDisabled(True)
                it.setText(2, native_res + "  (igual)")
            tree.addTopLevelItem(it)
        lay.addWidget(tree, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Aplicar los marcados")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._resolve_dialog = dlg
        if dlg.exec() != QDialog.Accepted:
            return 0
        n = 0
        for i in range(tree.topLevelItemCount()):
            it = tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked and not it.isDisabled():
                key, res = it.data(0, Qt.UserRole)
                if self.set_shortcut(key, QKeySequence(res), ask=False):
                    n += 1
        self.msg.setText(f"⬇ {n} atajos traídos de tu DaVinci Resolve. «↺ Restablecer todos» vuelve a los de fábrica.")
        return n

    def _reset_all(self):
        if QMessageBox.question(self, "Restablecer", "¿Volver a los atajos de fábrica en todas las órdenes?") \
                != QMessageBox.Yes:
            return
        for key in self.actions:
            self._reset(key)
        self.msg.setText("↺ Todos los atajos de fábrica.")
