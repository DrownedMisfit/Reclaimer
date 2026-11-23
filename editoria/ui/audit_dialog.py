"""Ventana «Revisión del proyecto»: lista de posibles problemas. Antes de exportar sale solo si hay avisos importantes
(revision_previa); con «Ctrl+R» se abre siempre."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
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
        btn_guiada = QPushButton("✓ Revisarlos uno a uno")
        btn_guiada.setToolTip("Revisión guiada: te lleva a cada aviso (y a lo demás que la IA no tiene claro) para "
                              "decidir con teclas: Enter lo que propone la IA, O está bien así, Supr quitar")
        btn_guiada.clicked.connect(self._guiada)
        self._before_export = before_export
        close = QPushButton("Exportar igual" if before_export else "Cerrar")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(btn_refresh)
        row.addWidget(btn_guiada)
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
        self._en_panel = False
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
            it.setToolTip(2, issue["message"] + (chr(10) + issue["detail"] if issue["detail"] else ""))
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
        self._ajustar_lista()

    def compactar(self):
        """🧰 En el panel (~300 px): «Momento», «Aviso» e «Ir»; el detalle, en el tooltip del aviso. Los botones,
        en filas que se parten; «No volver a mostrar», con texto corto."""
        from .diseno import FilaFluida
        self.tree.setColumnHidden(3, True)
        self.tree.setColumnWidth(0, 26)
        self.tree.setColumnWidth(1, max(52, self.tree.fontMetrics().horizontalAdvance("Momento") + 18))
        self.tree.setColumnWidth(COL_IR, 40)
        from PySide6.QtWidgets import QHeaderView
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(2, QHeaderView.Stretch)          # (el aviso, al ancho que quede; parte línea)
        for col in (0, 1, COL_IR):
            hd.setSectionResizeMode(col, QHeaderView.Fixed)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        self._en_panel = True
        self._ajustar_lista()
        self.no_mostrar.setText("No volver a mostrar")
        self.no_mostrar.setToolTip("No mostrar esta revisión antes de exportar. " + self.no_mostrar.toolTip())
        fila = FilaFluida(espacio=6, alinear_derecha=True)
        for b in self.findChildren(QPushButton):
            if b.parent() is self:
                fila.addWidget(b)
        if self.no_mostrar.isVisibleTo(self):
            fila.insertWidget(0, self.no_mostrar)
        self.layout().addWidget(fila)
        self.title.setWordWrap(True)

    ALTO_MAX_LISTA = 320

    def _ajustar_lista(self):
        """(en el panel) La lista mide lo que sus filas, hasta ALTO_MAX_LISTA: sin hueco debajo con pocos avisos."""
        if not getattr(self, "_en_panel", False):
            return
        from math import ceil
        fm = self.tree.fontMetrics()
        ancho = max(120, (self.width() or 300) - 26 - self.tree.columnWidth(1) - self.tree.columnWidth(COL_IR) - 24)
        alto = self.tree.header().sizeHint().height() + 6
        for i in range(self.tree.topLevelItemCount()):
            txt = self.tree.topLevelItem(i).text(2)
            lineas = max(1, ceil(fm.horizontalAdvance(txt) / ancho))
            alto += max(26, lineas * fm.lineSpacing() + 8)
        self.tree.setFixedHeight(min(self.ALTO_MAX_LISTA, alto))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ajustar_lista()

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

    def _guiada(self):
        """Cierra la lista (sin exportar) y abre la revisión guiada."""
        win = self.parent()
        self.reject() if self._before_export else self.accept()
        if win is not None and hasattr(win, "open_quick_review"):
            win.open_quick_review()


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
    # 🧰 (lote 2) la revisión va en el panel de herramientas, sin bloquear: «Exportar igual» sigue con la exportación
    # (win.export(revisado=True)); «Revisar» la cierra y no exporta. Mientras tanto, aquí se devuelve False.
    from .herramientas import abrir_dialogo
    caja = {}

    def fabrica():
        caja["dlg"] = AuditDialog(c, win.engine, win.timeline, win, before_export=True)
        return caja["dlg"]

    def al_terminar(r):
        dlg = caja.get("dlg")
        if dlg is not None and dlg.no_mostrar.isChecked():
            st.setValue("exportar/revisar_antes", "false")
        if r and hasattr(win, "export"):
            QTimer.singleShot(0, lambda: win.export(revisado=True))
    abrir_dialogo(win, "revision_exportar", fabrica, "Revisión antes de exportar", "Revisión", "list-checks",
                  al_terminar=al_terminar)
    return False
