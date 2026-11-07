"""
📺 «En pantalla» (dentro del panel «Texto»): los bloques de texto que van saliendo en el video (a lo mucho 3 palabras
en los Shorts), en orden y sincronizados. Lo que está sonando AHORA se ve grande y resaltado y se queda en el centro;
lo que ya pasó, apagado; lo siguiente, debajo. Así no hay que buscar las palabras ni el momento exacto.
  · clic en un bloque: el cabezal salta ahí;
  · doble clic: corregirlo (con ortografía); los tiempos se mantienen.
Si los subtítulos aún no están puestos, muestra la SUGERENCIA (cómo quedarían con el estilo de los Shorts).
"""
from __future__ import annotations

import bisect
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from ..core import subtitles as SUBS
from ..core.model import SubtitleStyle
from .common import fmt_time

NOW_BG, NOW_FG = QColor("#ff8a1f"), QColor("#16181d")     # lo que suena ahora: naranja intenso, letra oscura
NEXT_FG, PAST_FG, NORM_FG = QColor("#f2f2f4"), QColor("#6b7080"), QColor("#c9ccd4")


class CaptionView(QWidget):
    def __init__(self, ctrl, engine, media_of, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine, self.media_of = ctrl, engine, media_of
        self.cues: list = []
        self._starts: list[float] = []
        self._cur = -1
        self._user_scroll = 0.0
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dim")
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(False)
        self.list.setSpacing(2)
        self.list.setStyleSheet("QListWidget { background: #1b1d22; border: none; padding: 4px; }"
                                "QListWidget::item { padding: 6px 8px; border-radius: 6px; }"
                                "QListWidget::item:selected { background: transparent; }")
        self.list.itemClicked.connect(self._seek)
        self.list.itemDoubleClicked.connect(self._edit)
        self.list.verticalScrollBar().sliderPressed.connect(self._touched)
        self.list.viewport().installEventFilter(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.info)
        lay.addWidget(self.list, 1)
        self._f_norm = QFont("Segoe UI", 12)
        self._f_now = QFont("Segoe UI", 17)
        self._f_now.setBold(True)
        self._f_next = QFont("Segoe UI", 13)
        self._f_next.setBold(True)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Wheel:              # si estás mirando más abajo/arriba, no te lo quita de la vista
            self._touched()
        return False

    def _touched(self):
        self._user_scroll = time.time()

    # ---------------------------------------------------------- datos
    def rebuild(self):
        p = self.ctrl.project
        mid = self.media_of()
        st = p.subtitles
        if mid and st.enabled and st.media_id == mid and mid in p.transcripts:
            self.cues = SUBS.styled_cues(p)
            self.info.setText(f"📺 Lo que sale en pantalla (estilo «{st.preset}»). Lo que suena ahora, en naranja. "
                              "Clic = ir ahí · doble clic = corregir.")
        elif mid and mid in p.transcripts:
            sug = SubtitleStyle(**SUBS.PRESETS[SUBS.SHORTS])
            self.cues = SUBS.build_cues(p, mid, max_chars=sug.max_chars, max_lines=sug.max_lines, style=sug,
                                        max_words=sug.max_words)
            self.info.setText("💡 Sugerencia de lo que saldría en pantalla (a lo mucho 3 palabras). Para ponerlo en "
                              "el video: pestaña «Subtítulos» → «⚡ Subtítulos para Short». Doble clic = corregir.")
        else:
            self.cues = []
            self.info.setText("Sin transcripción: transcríbela en «Limpieza».")
        self._starts = [c.start for c in self.cues]
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for k, c in enumerate(self.cues):
            it = QListWidgetItem(f"{fmt_time(c.start, False)}   {c.text(' ')}")
            it.setData(Qt.UserRole, k)
            self.list.addItem(it)
        self._cur = -1
        self.list.setUpdatesEnabled(True)
        self._style_all()
        self.highlight(self.engine.time, force=True)

    def _style(self, k: int, kind: str):
        it = self.list.item(k)
        if it is None:
            return
        if kind == "now":
            it.setFont(self._f_now)
            it.setBackground(QBrush(NOW_BG))
            it.setForeground(QBrush(NOW_FG))
            c = self.cues[k]
            it.setText(f"▶ {c.text(' ')}")
        else:
            it.setFont(self._f_next if kind == "next" else self._f_norm)
            it.setBackground(QBrush(Qt.transparent))
            it.setForeground(QBrush({"next": NEXT_FG, "past": PAST_FG}.get(kind, NORM_FG)))
            c = self.cues[k]
            it.setText(f"{fmt_time(c.start, False)}   {c.text(' ')}")

    def _style_all(self):
        for k in range(len(self.cues)):
            self._style(k, "past" if k < self._cur else "norm")

    def current_index(self, t: float) -> int:
        k = bisect.bisect_right(self._starts, t) - 1
        if k >= 0 and t < self.cues[k].end + 0.15:
            return k
        return -1 if k < 0 else -(k + 2)        # entre dos bloques: -(siguiente + 1)

    def highlight(self, t: float, force: bool = False):
        if not self.cues or not self.isVisible() and not force:
            return
        k = self.current_index(t)
        now = k if k >= 0 else -1
        if now == self._cur and not force:
            return
        old = self._cur
        self._cur = now
        if old >= 0:
            self._style(old, "past" if (now < 0 or old < now) else "norm")
            if old + 1 < len(self.cues) and old + 1 != now:
                self._style(old + 1, "norm" if now < 0 or old + 1 > now else "past")
        if now >= 0:
            if old >= 0 and now < old:                 # hacia atrás: lo que «ya pasó» vuelve a estar por delante
                for j in range(now + 1, min(old + 2, len(self.cues))):
                    self._style(j, "norm")
            self._style(now, "now")
            if now + 1 < len(self.cues):
                self._style(now + 1, "next")
            if time.time() - self._user_scroll > 3.0:
                self.list.scrollToItem(self.list.item(now), QListWidget.PositionAtCenter)

    # ---------------------------------------------------------- acciones
    def _seek(self, it: QListWidgetItem):
        k = it.data(Qt.UserRole)
        if 0 <= k < len(self.cues):
            self.engine.user_seek(self.cues[k].start + 0.001)

    def _edit(self, it: QListWidgetItem):
        k = it.data(Qt.UserRole)
        if not 0 <= k < len(self.cues):
            return
        cue = self.cues[k]
        dlg = QDialog(self)
        dlg.setWindowTitle("Corregir lo que sale en pantalla")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Texto correcto (los tiempos se mantienen; si cambia el número de palabras, se reparten "
                             "en el mismo tramo):"))
        ed = QPlainTextEdit(cue.text(" "))
        ed.setFixedHeight(64)
        lay.addWidget(ed)
        from .spellcheck import attach
        lay.addWidget(attach(ed))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted and ed.toPlainText().strip():
            self.apply_edit(k, ed.toPlainText())

    def apply_edit(self, k: int, text: str):
        cue = self.cues[k]
        mid = self.media_of()
        idxs = [w.index for w in cue.words]
        if mid and idxs:
            self.ctrl.edit_words(mid, idxs, " ".join(text.split()), label="Corregir subtítulo")
