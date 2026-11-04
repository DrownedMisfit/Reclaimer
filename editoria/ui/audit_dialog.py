"""Ventana «Revisión del proyecto»: lista de posibles problemas antes de exportar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from ..ai.audit import run_audit, summary
from .common import fmt_time
from .help import set_help

ICONS = {"error": "⛔", "warning": "⚠️", "info": "ℹ️"}
COLORS = {"error": "#e5534b", "warning": "#e3b341", "info": "#9aa1ad"}


class AuditDialog(QDialog):
    def __init__(self, ctrl, engine, timeline, parent=None, before_export: bool = False):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.timeline = timeline
        self.setWindowTitle("Revisión del proyecto")
        self.resize(760, 520)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Momento", "Aviso", "Detalle"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 34)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 280)
        self.tree.itemDoubleClicked.connect(self._go)
        set_help(self, "revision")
        btn_refresh = QPushButton("↻ Revisar de nuevo")
        btn_refresh.clicked.connect(self.refresh)
        close = QPushButton("Exportar de todos modos" if before_export else "Cerrar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(btn_refresh)
        row.addStretch()
        if before_export:
            back = QPushButton("Volver a editar")
            back.clicked.connect(self.reject)
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
        if not self.issues:
            self.tree.addTopLevelItem(QTreeWidgetItem(["✓", "", "Todo bien: no se encontró ningún problema.", ""]))

    def _go(self, item, _col):
        i = item.data(0, Qt.UserRole)
        if i is None:
            return
        issue = self.issues[i]
        if issue["time"] is not None:
            self.engine.user_seek(issue["time"])
        if issue.get("target") and issue["target"] in self.ctrl.project.clips:
            self.timeline.set_selection([issue["target"]])
