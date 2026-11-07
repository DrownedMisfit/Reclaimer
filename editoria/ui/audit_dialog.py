"""Ventana «Revisión del proyecto»: lista de posibles problemas. Antes de exportar sale solo si hay avisos importantes
(revision_previa); con «Ctrl+R» se abre siempre."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from ..ai.audit import run_audit, summary
from .common import fmt_time
from .help import set_help

ICONS = {"error": "⛔", "warning": "⚠️", "info": "ℹ️"}
COLORS = {"error": "#e5534b", "warning": "#e3b341", "info": "#9aa1ad"}
COL_IR = 4


class AuditDialog(QDialog):
    def __init__(self, ctrl, engine, timeline, parent=None, before_export: bool = False):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.timeline = timeline
        self.setWindowTitle("⚕ Revisión antes de exportar" if before_export else "Revisión del proyecto")
        self.resize(820, 540)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Momento", "Aviso", "Detalle", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 34)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 280)
        self.tree.setColumnWidth(COL_IR, 56)
        self.tree.itemDoubleClicked.connect(self._go)
        set_help(self, "revision")
        btn_refresh = QPushButton("↻ Revisar de nuevo")
        btn_refresh.clicked.connect(self.refresh)
        close = QPushButton("Exportar igual" if before_export else "Cerrar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(btn_refresh)
        row.addStretch()
        self.no_mostrar = QCheckBox("No volver a mostrar antes de exportar")
        self.no_mostrar.setToolTip("Antes de exportar ya no saldrá esta revisión. Sigue disponible con Ctrl+R.")
        self.no_mostrar.setVisible(before_export)
        if before_export:
            back = QPushButton("Revisar")
            back.setToolTip("Vuelve a la línea de tiempo para arreglar los avisos (no exporta).")
            back.clicked.connect(self.reject)
            row.addWidget(self.no_mostrar)
            row.addWidget(back)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self.issues: list[dict] = []
        self.refresh()

    def refresh(self):
        c = self.ctrl
        c.ensure_timeline_peaks(wait=True)      # la revisión de cortes necesita la voz de cada clip
        self.issues, checked = run_audit(c.project, c.missing, c.peaks, c.clip_vecs)
        self.title.setText("REVISIÓN DEL PROYECTO — " + summary(self.issues, checked))
        self.tree.clear()
        for i, issue in enumerate(self.issues):
            t = issue["time"]
            it = QTreeWidgetItem([ICONS[issue["severity"]], fmt_time(t, False) if t is not None else "—",
                                  issue["message"], issue["detail"]])
            it.setForeground(2, QColor(COLORS[issue["severity"]]))
            it.setToolTip(3, issue["detail"])
            it.setData(0, Qt.UserRole, i)
            self.tree.addTopLevelItem(it)
            if t is not None or issue.get("target"):
                btn = QPushButton("Ir")
                btn.setObjectName(f"ir_{i}")
                btn.setToolTip("Lleva el cabezal a este momento y selecciona el clip (el aviso no se cambia).")
                btn.clicked.connect(lambda _=False, k=i: self._ir(k))
                self.tree.setItemWidget(it, COL_IR, btn)
        if not self.issues:
            self.tree.addTopLevelItem(QTreeWidgetItem(["✓", "", "Todo bien: no se encontró ningún problema.", ""]))

    def _ir(self, i: int):
        issue = self.issues[i]
        if issue["time"] is not None:
            self.engine.user_seek(issue["time"])
        if issue.get("target") and issue["target"] in self.ctrl.project.clips:
            self.timeline.set_selection([issue["target"]])

    def _go(self, item, _col):
        i = item.data(0, Qt.UserRole)
        if i is not None:
            self._ir(i)


def revision_previa(win) -> bool:
    """Antes de exportar: si hay avisos importantes (⛔ o ⚠️) sale la revisión con «Exportar igual» y «Revisar».
    Devuelve True para seguir exportando. Sin avisos importantes, o con «No volver a mostrar» marcada antes, sale directo
    (QSettings «exportar/revisar_antes»)."""
    win.engine.pause()
    st = QSettings("EditorIA", "EditorIA")
    if str(st.value("exportar/revisar_antes", "true")) != "true":
        return True
    from ..ai.audit import run_audit
    c = win.ctrl
    issues, _n = run_audit(c.project, c.missing, c.peaks, c.clip_vecs)
    if not any(i["severity"] in ("error", "warning") for i in issues):
        return True
    dlg = AuditDialog(c, win.engine, win.timeline, win, before_export=True)
    ok = dlg.exec()
    if dlg.no_mostrar.isChecked():
        st.setValue("exportar/revisar_antes", "false")
    return bool(ok)
