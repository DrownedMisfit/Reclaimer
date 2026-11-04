"""
«◈ Aprendizaje IA»: el botón de arriba a la derecha y su ventana.

Learner: escucha SOLO los pasos de deshacer/rehacer del editor (si el aprendizaje está activado y sin pausa)
y, al guardar o cerrar, resume el proyecto (ai/style_learning.py). No hay procesos en segundo plano: al
cerrar Reclaimer se detiene todo.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

from ..ai import style_learning as SL
from . import help as help_ui


class Learner(QObject):
    changed = Signal()

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.data = SL.load()
        self.session = SL.Session()
        self.last_analysis = ""
        ctrl.undo_group.indexChanged.connect(self._on_index)     # (sigue al historial de la pestaña activa)
        ctrl.project_replaced.connect(self._new_session)
        ctrl.saved.connect(lambda _path: self.analyze())

    # ---------------------------------------------------------------- estado
    @property
    def enabled(self) -> bool:
        return bool(self.data["settings"].get("enabled"))

    @property
    def paused(self) -> bool:
        return bool(self.data["settings"].get("paused"))

    @property
    def active(self) -> bool:
        return self.enabled and not self.paused

    def set_enabled(self, on: bool):
        self.data["settings"]["enabled"] = bool(on)
        if not on:
            self.data["settings"]["paused"] = False
            self.session = SL.Session()       # lo observado de esta sesión se olvida
        SL.save(self.data)
        self.changed.emit()

    def set_paused(self, on: bool):
        self.data["settings"]["paused"] = bool(on)
        SL.save(self.data)
        self.changed.emit()

    def kind(self) -> str:
        return self.ctrl.project.format if self.ctrl.project.format in SL.KINDS else "youtube"

    def key(self) -> str | None:
        return SL.project_key(self.ctrl.path)

    def record(self) -> dict | None:
        k = self.key()
        return self.data["projects"].get(k) if k else None

    def set_project_learn(self, on: bool):
        k = self.key()
        if not k:
            return
        rec = self.data["projects"].setdefault(k, {"kind": self.kind(), "subtype": "", "learn": True,
                                                   "sessions": 0, "name": self.ctrl.project.name})
        rec["learn"] = bool(on)
        SL.refresh_prefs(self.data)
        SL.save(self.data)
        self.changed.emit()

    def set_subtype(self, sub: str):
        k = self.key()
        if k:
            rec = self.data["projects"].setdefault(k, {"kind": self.kind(), "subtype": "", "learn": True,
                                                       "sessions": 0, "name": self.ctrl.project.name})
            rec["subtype"] = sub
            SL.save(self.data)

    # ---------------------------------------------------------------- observar
    def _new_session(self):
        self.session = SL.Session()
        self.changed.emit()

    def _on_index(self, index: int):
        if not self.active or getattr(self.ctrl, "_switching", False):
            return
        st = self.ctrl.undo_stack
        cmd = st.command(index - 1) if index > 0 else None
        self.session.on_index(index, cmd.text() if cmd else "", self.ctrl.project)

    def analyze(self, force: bool = False) -> str:
        """Resume la sesión (al guardar, al cerrar o con «Analizar esta sesión»). Milisegundos."""
        if not self.active and not force:
            return ""
        if not self.enabled:
            return "El aprendizaje está desactivado."
        k = self.key()
        if not k:
            return "Guarda el proyecto para que cuente en tu estilo."
        rec = SL.end_session(self.data, k, self.ctrl.project, self.session, self.kind())
        SL.save(self.data)
        self.session = SL.Session()
        if rec is None:
            self.last_analysis = "Este proyecto está excluido del aprendizaje."
        else:
            n = sum(1 for r in self.data["projects"].values() if r.get("learn", True) and "final" in r)
            self.last_analysis = f"✓ Sesión analizada ({n} proyecto(s) en tu perfil)."
        self.changed.emit()
        return self.last_analysis

    def on_close(self):
        """Al cerrar Reclaimer: último resumen (si el proyecto está guardado) y se detiene todo."""
        if self.active and self.ctrl.path and not self.ctrl.dirty:
            self.analyze()


class LearningDialog(QDialog):
    """Panel pequeño de configuración: estado, mi estilo (con confianza), preferencias y privacidad."""

    def __init__(self, learner: Learner, parent=None):
        super().__init__(parent)
        self.L = learner
        self.ctrl = learner.ctrl
        self.setWindowTitle("◈ Aprendizaje de mi estilo de edición")
        self.resize(620, 700)
        help_ui.set_help(self, "aprendizaje")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.toggle = QCheckBox("Aprendizaje de mi estilo de edición")
        self.toggle.setStyleSheet("QCheckBox { font-weight: bold; }")
        self.toggle.toggled.connect(self._toggled)
        self.onoff = QLabel("")
        top.addWidget(self.toggle)
        top.addStretch(1)
        top.addWidget(self.onoff)
        lay.addLayout(top)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # --- Estado y privacidad
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        row = QHBoxLayout()
        self.b_pause = QPushButton("⏸ Pausar aprendizaje")
        self.b_pause.clicked.connect(lambda: self.L.set_paused(not self.L.paused))
        self.b_now = QPushButton("🔎 Analizar esta sesión")
        self.b_now.clicked.connect(lambda: self.msg.setText(self.L.analyze(force=True)))
        row.addWidget(self.b_pause)
        row.addWidget(self.b_now)
        v1.addLayout(row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v1.addWidget(self.msg)
        gp = QGroupBox("Este proyecto")
        fp = QFormLayout(gp)
        self.proj_learn = QComboBox()
        self.proj_learn.addItem("✓ Aprender de este proyecto", True)
        self.proj_learn.addItem("✗ No utilizar este proyecto para aprendizaje", False)
        self.proj_learn.currentIndexChanged.connect(lambda _i: self.L.set_project_learn(self.proj_learn.currentData()))
        fp.addRow("Uso", self.proj_learn)
        self.kind_label = QLabel("")
        fp.addRow("Tipo", self.kind_label)
        self.subtype = QComboBox()
        self.subtype.addItem("—", "")
        for s in SL.SUBTYPES:
            self.subtype.addItem(s, s)
        self.subtype.currentIndexChanged.connect(lambda _i: self.L.set_subtype(self.subtype.currentData()))
        fp.addRow("Contenido", self.subtype)
        self.proj_info = QLabel("")
        self.proj_info.setWordWrap(True)
        self.proj_info.setObjectName("dim")
        fp.addRow("", self.proj_info)
        v1.addWidget(gp)
        gr = QGroupBox("Recursos")
        fr = QFormLayout(gr)
        self.res_cpu = QLabel("…")
        self.res_ram = QLabel("…")
        self.res_impact = QLabel("Bajo")
        fr.addRow("CPU de Reclaimer", self.res_cpu)
        fr.addRow("RAM de Reclaimer", self.res_ram)
        fr.addRow("GPU del aprendizaje", QLabel("0 % (no usa la tarjeta gráfica)"))
        fr.addRow("Impacto en la edición", self.res_impact)
        note = QLabel("El aprendizaje solo cuenta acciones en memoria mientras editas y hace un resumen de "
                      "milisegundos al guardar o cerrar. No hay ningún modelo de IA funcionando por él.")
        note.setWordWrap(True)
        note.setObjectName("dim")
        fr.addRow(note)
        v1.addWidget(gr)
        priv = QLabel("🔒 <b>Privacidad</b>: solo analiza las acciones hechas <b>dentro del editor</b> (no el ratón "
                      "ni el teclado de Windows, ni otras ventanas o programas, ni carpetas que no hayas abierto "
                      "tú). Funciona solo con Reclaimer abierto: al cerrarlo se detiene. Todo queda en tu PC.")
        priv.setWordWrap(True)
        v1.addWidget(priv)
        b_del = QPushButton("🗑 Eliminar perfil aprendido (empezar de cero)")
        b_del.clicked.connect(self._delete)
        v1.addWidget(b_del)
        v1.addStretch(1)
        tabs.addTab(w1, "Estado")

        # --- Mi estilo (patrones con confianza)
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Ver"))
        self.scope = QComboBox()
        self.scope.addItem("Mi estilo general", "general")
        for k, name in SL.KINDS.items():
            self.scope.addItem(name, k)
        self.scope.addItem("Solo este proyecto", "proyecto")
        self.scope.currentIndexChanged.connect(lambda _i: self._fill_patterns())
        r2.addWidget(self.scope, 1)
        v2.addLayout(r2)
        self.pat_scroll = QScrollArea()
        self.pat_scroll.setWidgetResizable(True)
        self.pat_scroll.setFrameShape(QScrollArea.NoFrame)
        v2.addWidget(self.pat_scroll, 1)
        self.compare = QLabel("")
        self.compare.setWordWrap(True)
        v2.addWidget(self.compare)
        tabs.addTab(w2, "Mi estilo")

        # --- Preferencias aprendidas
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        tip = QLabel("La IA solo usa las preferencias que <b>aceptes</b>. Una acción suelta nunca se vuelve "
                     "regla: hacen falta varios proyectos parecidos.")
        tip.setWordWrap(True)
        v3.addWidget(tip)
        self.pref_scroll = QScrollArea()
        self.pref_scroll.setWidgetResizable(True)
        self.pref_scroll.setFrameShape(QScrollArea.NoFrame)
        v3.addWidget(self.pref_scroll, 1)
        tabs.addTab(w3, "Preferencias")
        self.tabs = tabs

        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self._usage_prev = None
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._update_usage)
        self._timer.start()
        learner.changed.connect(self.refresh)
        self.refresh()
        self._update_usage()

    # ----------------------------------------------------------------
    def _toggled(self, on: bool):
        if on != self.L.enabled:
            self.L.set_enabled(on)

    def _delete(self):
        if QMessageBox.question(self, "Eliminar perfil", "¿Borrar todo lo que la IA aprendió de tu estilo?\n"
                                "No se puede deshacer.") == QMessageBox.Yes:
            SL.delete_profile()
            self.L.data = SL.load()
            self.L.session = SL.Session()
            self.msg.setText("🗑 Perfil eliminado. Empieza de cero.")
            self.L.changed.emit()

    def refresh(self):
        L = self.L
        self.toggle.blockSignals(True)
        self.toggle.setChecked(L.enabled)
        self.toggle.blockSignals(False)
        self.onoff.setText("<b>ON</b>" if L.enabled else "<b>OFF</b>")
        if not L.enabled:
            self.state.setText("<span style='color:#71747d'>●</span> <b>Desactivado</b>: la IA no observa tus "
                               "acciones, no registra nada y no crea ni actualiza tu perfil.")
        elif L.paused:
            self.state.setText("⏸ <b>En pausa</b>: no se registra nada hasta que lo reanudes.")
        else:
            self.state.setText("<span style='color:#3ecf8e'>●</span> <b>Aprendiendo de tu edición</b> — analizando "
                               "únicamente las acciones realizadas dentro del editor.")
        self.b_pause.setText("▶ Reanudar aprendizaje" if L.paused else "⏸ Pausar aprendizaje")
        self.b_pause.setEnabled(L.enabled)
        self.b_now.setEnabled(L.enabled)
        rec = L.record()
        self.kind_label.setText(SL.KINDS.get(L.kind(), L.kind()))
        self.proj_learn.blockSignals(True)
        self.proj_learn.setCurrentIndex(0 if (rec is None or rec.get("learn", True)) else 1)
        self.proj_learn.setEnabled(bool(L.key()))
        self.proj_learn.blockSignals(False)
        self.subtype.blockSignals(True)
        self.subtype.setCurrentIndex(max(0, self.subtype.findData((rec or {}).get("subtype", ""))))
        self.subtype.setEnabled(bool(L.key()))
        self.subtype.blockSignals(False)
        acts = sum(v for v in L.session.actions.values() if v > 0)
        self.proj_info.setText(("Guarda el proyecto para que cuente en tu estilo." if not L.key() else
                                f"{(rec or {}).get('sessions', 0)} sesión(es) analizadas · en esta sesión: "
                                f"{acts} acciones") + (" · propuesta de la IA registrada para comparar"
                                                        if L.session.baseline or (rec or {}).get("baseline") else ""))
        if L.last_analysis and not self.msg.text():
            self.msg.setText(L.last_analysis)
        self._fill_patterns()
        self._fill_prefs()

    def _fill_patterns(self):
        box = QWidget()      # contenido nuevo cada vez (el anterior lo borra el QScrollArea)
        self.pat_grid = QGridLayout(box)
        sc = self.scope.currentData() or "general"
        pats = SL.patterns(self.L.data, sc, self.L.key())
        if not pats:
            self.pat_grid.addWidget(QLabel("Todavía no hay datos. Activa el aprendizaje, edita y guarda tus "
                                           "proyectos: aquí irá apareciendo tu estilo."), 0, 0, 1, 3)
        for i, p in enumerate(pats):
            self.pat_grid.addWidget(QLabel(p["name"]), i, 0)
            self.pat_grid.addWidget(QLabel(f"<b>{p['text']}</b>"), i, 1)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(p["confidence"] * 100)))
            bar.setFormat(f"{p['confidence']:.0%} · {p['n']} proyecto(s)")
            bar.setToolTip("Confianza: sube con más proyectos parecidos entre sí.")
            self.pat_grid.addWidget(bar, i, 2)
        self.pat_grid.setRowStretch(len(pats) + 1, 1)
        self.pat_scroll.setWidget(box)
        cmp = SL.compare(self.L.data, self.ctrl.project, self.L.kind()) if self.L.enabled else []
        self.compare.setText("💡 " + "<br>💡 ".join(cmp) if cmp else "")

    def _fill_prefs(self):
        box = QWidget()
        self.pref_lay = QVBoxLayout(box)
        prefs = sorted(self.L.data["prefs"].items(), key=lambda kv: ({"detectada": 0, "aceptada": 1, "editada": 1,
                                                                       "rechazada": 2}.get(kv[1].get("state"), 3),
                                                                      -kv[1].get("confidence", 0)))
        if not prefs:
            self.pref_lay.addWidget(QLabel("Aún no ha detectado patrones (hacen falta varios proyectos)."))
        for pid, p in prefs:
            box_p = QGroupBox()
            g = QGridLayout(box_p)
            st = p.get("state", "detectada")
            head = {"detectada": "🤔 Creo que he detectado este patrón:", "aceptada": "✓ Aceptada",
                    "editada": "✎ Editada por ti", "rechazada": "✗ Rechazada (no se usa)"}.get(st, st)
            scope = "general" if p.get("scope") == "general" else SL.KINDS.get(p.get("scope"), p.get("scope"))
            g.addWidget(QLabel(f"<span style='color:#9aa1ad'>{head} · {scope} · confianza "
                               f"{p.get('confidence', 0):.0%}</span>"), 0, 0, 1, 4)
            t = QLabel(f"«{p['text']}»")
            t.setWordWrap(True)
            g.addWidget(t, 1, 0, 1, 4)
            col = 0
            if st in ("detectada", "rechazada"):
                b = QPushButton("✓ Aceptar")
                b.clicked.connect(lambda _=False, k=pid: self._set_state(k, "aceptada"))
                g.addWidget(b, 2, col)
                col += 1
            if st in ("detectada", "aceptada", "editada"):
                b = QPushButton("✗ Rechazar")
                b.clicked.connect(lambda _=False, k=pid: self._set_state(k, "rechazada"))
                g.addWidget(b, 2, col)
                col += 1
            b = QPushButton("✎ Editar")
            b.clicked.connect(lambda _=False, k=pid: self._edit(k))
            g.addWidget(b, 2, col)
            col += 1
            b = QPushButton("🗑 Eliminar")
            b.clicked.connect(lambda _=False, k=pid: self._remove(k))
            g.addWidget(b, 2, col)
            self.pref_lay.addWidget(box_p)
        self.pref_lay.addStretch(1)
        self.pref_scroll.setWidget(box)

    def _set_state(self, pid: str, state: str):
        self.L.data["prefs"][pid]["state"] = state
        SL.save(self.L.data)
        self.L.changed.emit()

    def _edit(self, pid: str):
        p = self.L.data["prefs"][pid]
        if p.get("value") is not None and p.get("unit") == "s":
            v, ok = QInputDialog.getDouble(self, "Editar preferencia", p["text"] + "\n\nValor (segundos):",
                                           float(p["value"]), 0.3, 60.0, 1)
            if not ok:
                return
            import re
            p["value"] = round(v, 1)
            p["text"] = re.sub(r"≈[+-]?[\d.,]+ s", f"≈{v:.1f} s", p["text"])
        else:
            t, ok = QInputDialog.getText(self, "Editar preferencia", "Texto:", text=p["text"])
            if not ok or not t.strip():
                return
            p["text"] = t.strip()
        p["state"] = "editada"
        SL.save(self.L.data)
        self.L.changed.emit()

    def _remove(self, pid: str):
        self.L.data["prefs"].pop(pid, None)
        SL.save(self.L.data)
        self.L.changed.emit()

    def _update_usage(self):
        u, self._usage_prev = SL.process_usage(self._usage_prev)
        self.res_cpu.setText(f"{u['cpu']:.0f} %")
        self.res_ram.setText(f"{u['ram_mb']:.0f} MB · perfil en disco: {u['disk_kb']:.0f} KB")
        self.res_impact.setText("Bajo" if self.L.enabled else "Ninguno (desactivado)")
