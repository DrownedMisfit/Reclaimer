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
# Atajos de más que vienen de fábrica, según el principal (main_window los añade con setShortcuts)
EXTRAS_DE_FABRICA = {"Ctrl+B": ["S"], "Ctrl+0": ["Shift+Z"]}
# Los de deshacer y rehacer no salen en la lista, pero no se pueden quitar
RESERVADOS = {"Ctrl+Z": "Deshacer", "Ctrl+Y": "Rehacer", "Ctrl+Shift+Z": "Rehacer"}


def extra_permitido(key: str, seq: str) -> bool:
    """¿Se puede añadir a esa orden el atajo de más «seq» (p. ej. S para dividir)? No si se lo quitaste, ni si otra
    orden ya lo tiene como suyo."""
    st = QSettings("EditorIA", "EditorIA")
    quitados = str(st.value("atajos_sin_extra/" + key, "") or "").split("|")
    if seq in quitados:
        return False
    st.beginGroup(PREFIX.rstrip("/"))
    try:
        otros = [str(st.value(k) or "") for k in st.allKeys()]
    finally:
        st.endGroup()
    return QKeySequence(seq).toString(QKeySequence.PortableText) not in otros


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
            self._tip_extras(ed, action)
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
        b_exp = QPushButton("⬆ Exportar…")
        b_exp.setToolTip("Guarda tus atajos en un archivo (para otro PC o para compartirlos)")
        b_exp.clicked.connect(lambda: self.export_file())
        b_imp = QPushButton("⬇ Importar…")
        b_imp.setToolTip("Pone los atajos de un archivo exportado desde Reclaimer")
        b_imp.clicked.connect(lambda: self.import_file())
        row.addWidget(b_exp)
        row.addWidget(b_imp)
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
            reservado = RESERVADOS.get(seq.toString(QKeySequence.PortableText))
            if reservado:
                if ask:
                    QMessageBox.information(self, "Atajo reservado", f"«{seq.toString(QKeySequence.NativeText)}» "
                                            f"es el atajo de «{reservado}»: elige otro.")
                self.editors[key].setKeySequence(action.shortcut())
                return False
            other = next((k for k, (a, _d) in self.actions.items() if k != key and seq in a.shortcuts()), None)
            if other is not None:
                if ask and QMessageBox.question(
                        self, "Atajo en uso", f"«{seq.toString(QKeySequence.NativeText)}» ya es el atajo de "
                        f"«{other.replace('/', ' → ')}».\n¿Quitárselo y ponerlo aquí?") != QMessageBox.Yes:
                    self.editors[key].setKeySequence(action.shortcut())
                    return False
                oa = self.actions[other][0]
                if oa.shortcuts() and oa.shortcuts()[0] != seq:     # (era uno de más: que no vuelva al reiniciar)
                    q = str(self.settings.value("atajos_sin_extra/" + other, "") or "")
                    self.settings.setValue("atajos_sin_extra/" + other,
                                           "|".join(x for x in set(q.split("|") + [seq.toString(
                                               QKeySequence.PortableText)]) if x))
                resto = [s for s in oa.shortcuts() if s != seq]     # (solo esa combinación; las demás se quedan)
                oa.setShortcuts(resto)
                self.settings.setValue(PREFIX + other, resto[0].toString(QKeySequence.PortableText) if resto else "")
                self.editors[other].setKeySequence(resto[0] if resto else QKeySequence())
                self._tip_extras(self.editors[other], oa)
        extras = [s for s in action.shortcuts()[1:] if s != seq]   # (los de más que tenía, se mantienen)
        action.setShortcuts([seq] + extras if not seq.isEmpty() else extras)
        self._tip_extras(self.editors[key], action)
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
        self.settings.remove("atajos_sin_extra/" + key)
        extras = [QKeySequence(x) for x in EXTRAS_DE_FABRICA.get(default or "", [])
                  if not any(QKeySequence(x) in a.shortcuts() for k, (a, _d) in self.actions.items() if k != key)]
        action.setShortcuts(([seq] if not seq.isEmpty() else []) + extras)
        self.editors[key].setKeySequence(seq)
        self._tip_extras(self.editors[key], action)
        self.msg.setText(f"↺ «{key.split('/', 1)[1].replace('&', '')}» vuelve a "
                         f"{seq.toString(QKeySequence.NativeText) or 'sin atajo'}")

    @staticmethod
    def _tip_extras(ed, action):
        """Los atajos de más de una orden (p. ej. S para dividir) se ven al pasar el ratón."""
        extras = [s.toString(QKeySequence.NativeText) for s in action.shortcuts()[1:]]
        ed.setToolTip("También: " + " · ".join(extras) if extras else "")

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

    def export_file(self, path: str | None = None) -> str | None:
        """⬆ Tus atajos (todos, como están ahora) en un archivo .json."""
        import json
        if path is None:
            from PySide6.QtWidgets import QFileDialog
            path, _f = QFileDialog.getSaveFileName(self, "Exportar atajos", "Atajos de Reclaimer.json",
                                                   "Atajos de Reclaimer (*.json)")
            if not path:
                return None
        data = {"programa": "Reclaimer", "tipo": "atajos", "version": 1,
                "atajos": {k: a.shortcut().toString(QKeySequence.PortableText) for k, (a, _d) in self.actions.items()}}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError as exc:
            self.msg.setText(f"No pude guardarlo: {exc}")
            return None
        self.msg.setText(f"⬆ {len(data['atajos'])} atajos guardados en «{path}».")
        return path

    def import_file(self, path: str | None = None) -> int:
        """⬇ Pone los atajos de un archivo exportado (las órdenes que no existen aquí se saltan). Devuelve cuántos."""
        import json
        if path is None:
            from PySide6.QtWidgets import QFileDialog
            path, _f = QFileDialog.getOpenFileName(self, "Importar atajos", "", "Atajos de Reclaimer (*.json)")
            if not path:
                return 0
        import os as _os
        try:
            if _os.path.getsize(path) > 1_000_000:
                raise ValueError("el archivo es demasiado grande para ser de atajos")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            atajos = data["atajos"] if isinstance(data, dict) and data.get("tipo") == "atajos" else None
            if not isinstance(atajos, dict):
                raise ValueError("no es un archivo de atajos de Reclaimer")
        except (OSError, ValueError, KeyError, RecursionError) as exc:
            self.msg.setText(f"No pude leerlo: {exc}")
            return 0
        validos: dict = {}
        malos = 0
        for k, txt in atajos.items():
            if k not in self.actions:
                continue
            if not isinstance(txt, str) or len(txt) > 64:
                malos += 1
                continue
            seq = QKeySequence(txt, QKeySequence.PortableText)
            if txt.strip() and (seq.isEmpty() or seq.count() > 1
                                or seq.toString(QKeySequence.PortableText).lower() != txt.strip().lower()):
                malos += 1                               # (no es un atajo de verdad: el actual se queda)
                continue
            validos[k] = seq
        antes = {k: a.shortcut() for k, (a, _d) in self.actions.items()}
        n = 0
        for k, seq in validos.items():
            if seq != self.actions[k][0].shortcut() and self.set_shortcut(k, seq, ask=False):
                n += 1
        sin = [k for k, a in antes.items() if not a.isEmpty() and self.actions[k][0].shortcut().isEmpty()
               and k not in validos]
        saltados = sum(1 for k in atajos if k not in self.actions)
        txt_msg = f"⬇ {n} atajo(s) cambiados"
        if saltados:
            txt_msg += f" ({saltados} de órdenes que no hay aquí)"
        if malos:
            txt_msg += f"; {malos} no válidos se ignoraron"
        if sin:
            txt_msg += (". Se quedaron sin atajo (lo usa otra orden del archivo): "
                        + ", ".join(k.split("/", 1)[-1].replace("&", "") for k in sin[:5]))
        self.msg.setText(txt_msg + ".")
        return n

    def _reset_all(self):
        if QMessageBox.question(self, "Restablecer", "¿Volver a los atajos de fábrica en todas las órdenes?") \
                != QMessageBox.Yes:
            return
        for _vuelta in range(2):                     # (la 2.ª: los de más, ya libres)
            for key in self.actions:
                self._reset(key)
        self.msg.setText("↺ Todos los atajos de fábrica.")
