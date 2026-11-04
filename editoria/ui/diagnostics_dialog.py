"""
Ayuda → ✧ Caché y diagnóstico.

  · Caché: cuánto ocupa cada cosa y botones para borrar lo que se puede rehacer (con aviso si rehacerlo cuesta).
    Lo que usan tus miniaturas o proyectos no se borra desde aquí.
  · Diagnóstico: FFmpeg, tarjeta gráfica, disco, proyecto e historial, con «📋 Copiar informe».
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core import diagnostics as D
from .jobs import BackgroundJob


class DiagnosticsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("✧ Caché y diagnóstico")
        self.resize(820, 560)
        self.entries: list[dict] = []
        self.rows: list[tuple[str, str]] = []
        self._jobs: list[BackgroundJob] = []
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._cache_tab(), "✧ Caché")
        self.tabs.addTab(self._diag_tab(), "⚕ Diagnóstico")
        lay.addWidget(self.tabs, 1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh_cache()
        self.refresh_report()

    # ---------------------------------------------------------------- caché
    def _cache_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.cache_total = QLabel("Calculando…")
        self.cache_total.setWordWrap(True)
        lay.addWidget(self.cache_total)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Qué es", "Ocupa", "", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_safe = QPushButton("✧ Borrar todo lo que se rehace solo")
        self.b_safe.setObjectName("primary")
        self.b_safe.setToolTip("Copias ligeras, formas de onda, miniaturas, vistas previas y tablas de color: "
                               "no pierdes nada, se vuelven a crear cuando hagan falta.")
        self.b_safe.clicked.connect(self.clear_safe)
        b_re = QPushButton("🔄 Volver a medir")
        b_re.clicked.connect(self.refresh_cache)
        row.addWidget(self.b_safe)
        row.addStretch()
        row.addWidget(b_re)
        lay.addLayout(row)
        return w

    def refresh_cache(self):
        job = BackgroundJob(lambda _p, _c: D.scan(), self)
        job.done.connect(self._show_cache)
        self._jobs.append(job)
        job.start()

    def _show_cache(self, entries):
        self.entries = entries
        self.table.setRowCount(len(entries))
        safe = sum(e["bytes"] for e in entries if e["can"] == "si")
        cache = sum(e["bytes"] for e in entries if not e.get("other"))
        for i, e in enumerate(entries):
            name = QTableWidgetItem(e["name"])
            name.setToolTip(e["what"] + ("\n" + e["after"] if e["after"] else ""))
            self.table.setItem(i, 0, name)
            size = QTableWidgetItem(D.human(e["bytes"]))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 1, size)
            if e["can"] == "no":
                lock = QLabel("🔒 en uso" if not e.get("other") else "")
                lock.setToolTip(e["after"] or e["what"])
                lock.setAlignment(Qt.AlignCenter)
                self.table.setCellWidget(i, 2, lock)
            else:
                b = QPushButton("⚠ Borrar…" if e["can"] == "aviso" else "Borrar")
                b.setEnabled(e["bytes"] > 0)
                b.setToolTip(e["after"])
                b.clicked.connect(lambda _=False, k=e["key"]: self.clear_one(k))
                self.table.setCellWidget(i, 2, b)
            op = QPushButton("📂")
            op.setFixedWidth(36)
            op.setToolTip("Abrir la carpeta")
            op.clicked.connect(lambda _=False, pth=e["path"]: QDesktopServices.openUrl(QUrl.fromLocalFile(pth)))
            self.table.setCellWidget(i, 3, op)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cache_total.setText(f"La caché ocupa <b>{D.human(cache)}</b>; de eso, <b>{D.human(safe)}</b> se puede "
                                 "borrar sin perder nada (se rehace solo). Pasa el ratón por cada fila para ver qué "
                                 "es y qué pasa si la borras.")
        self.b_safe.setEnabled(safe > 0)

    def clear_one(self, key: str, ask: bool = True):
        e = next((x for x in self.entries if x["key"] == key), None)
        if e is None:
            return
        if ask and e["can"] == "aviso":
            r = QMessageBox.question(self, "Borrar", f"¿Borrar «{e['name']}» ({D.human(e['bytes'])})?\n\n{e['after']}")
            if r != QMessageBox.Yes:
                return
        freed = D.clear(key)
        self._after_clear(key)
        self.cache_total.setText(f"✓ Liberados {D.human(freed)}.")
        self.refresh_cache()

    def clear_safe(self):
        freed = 0
        for e in self.entries:
            if e["can"] == "si" and e["bytes"] > 0:
                freed += D.clear(e["key"])
                self._after_clear(e["key"])
        self.cache_total.setText(f"✓ Liberados {D.human(freed)} (se rehacen solos cuando hagan falta).")
        self.refresh_cache()

    def _after_clear(self, key: str):
        """Que el programa no siga usando lo borrado."""
        ctrl = self.win.ctrl
        if key == "proxies" and hasattr(self.win, "proxies"):
            self.win.proxies.ensure()            # se vuelven a crear si estás usando «Media / Un cuarto»
            self.win.engine.refresh_sources()
        elif key == "huellas_clips":
            getattr(ctrl, "clip_vecs", {}).clear()

    # ---------------------------------------------------------------- diagnóstico
    def _diag_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.diag = QTableWidget(0, 2)
        self.diag.setHorizontalHeaderLabels(["", ""])
        self.diag.horizontalHeader().setVisible(False)
        self.diag.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.diag.verticalHeader().setVisible(False)
        self.diag.setEditTriggers(QTableWidget.NoEditTriggers)
        self.diag.setWordWrap(True)
        lay.addWidget(self.diag, 1)
        row = QHBoxLayout()
        b_copy = QPushButton("📋 Copiar informe")
        b_copy.setToolTip("Para pegarlo si algo falla y quieres que lo revisen.")
        b_copy.clicked.connect(self.copy_report)
        b_logs = QPushButton("📂 Abrir registros de errores")
        b_logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(
            os.path.dirname(__import__("editoria.core.paths", fromlist=["log_path"]).log_path()))))
        b_again = QPushButton("🔄 Volver a comprobar")
        b_again.clicked.connect(self.refresh_report)
        for b in (b_copy, b_logs):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_again)
        lay.addLayout(row)
        self.diag_status = QLabel("Comprobando (FFmpeg, tarjeta gráfica, disco…)")
        self.diag_status.setObjectName("dim")
        lay.addWidget(self.diag_status)
        return w

    def refresh_report(self):
        ctrl = self.win.ctrl
        job = BackgroundJob(lambda _p, _c: D.report(ctrl), self)
        job.done.connect(self._show_report)
        job.failed.connect(lambda m: self.diag_status.setText("✗ " + m))
        self._jobs.append(job)
        job.start()

    def _show_report(self, rows):
        self.rows = rows
        self.diag.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            a = QTableWidgetItem(k)
            a.setForeground(Qt.gray)
            self.diag.setItem(i, 0, a)
            self.diag.setItem(i, 1, QTableWidgetItem(v))
        self.diag.resizeColumnToContents(0)
        self.diag.resizeRowsToContents()
        bad = [k for k, v in rows if v.startswith("✗") or (k.startswith("Archivos que no") and "ninguno" not in v)]
        self.diag_status.setText("⚠ Revisa: " + ", ".join(bad) if bad else "✓ Todo en orden.")

    def report_text(self) -> str:
        return "\n".join(f"{k}: {v}" for k, v in self.rows)

    def copy_report(self):
        QGuiApplication.clipboard().setText(self.report_text())
        self.diag_status.setText("✓ Informe copiado: pégalo donde quieras (Ctrl+V).")

    def closeEvent(self, e):
        for j in self._jobs:
            if j.isRunning():
                j.wait(3000)
        super().closeEvent(e)
