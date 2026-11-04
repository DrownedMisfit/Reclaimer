"""
✍ «Texto en pantalla» en la pestaña «Texto» (el usuario: «no me aparece la opción para escribir el texto… la quiero
ahí»): con un texto seleccionado en la línea de tiempo, aquí se escribe (con corrector de ortografía) y se ve al momento
en el visor. Es la misma función que el cuadro del Inspector (ctrl.set_text_props: Ctrl+Z lo deshace); el tamaño, el
color y la posición siguen en el Inspector. Sin texto seleccionado: cómo hacerlo y «T Añadir texto aquí».
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout


class OnScreenText(QFrame):
    def __init__(self, ctrl, engine, timeline, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine, self.timeline = ctrl, engine, timeline
        self.clip_id: str | None = None
        self._loading = False
        self.setObjectName("onscreentext")
        self.setStyleSheet("#onscreentext { border: 1px solid #2f3137; border-radius: 7px; "
                           "background: rgba(255,255,255,0.012); }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        title = QLabel("Texto en pantalla")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.b_add = QPushButton("T  Añadir")
        self.b_add.setToolTip("Un texto nuevo en el cabezal (también la tecla T); se escribe aquí mismo.\n"
                              "Tamaño, color y posición: en el Inspector.")
        self.b_add.clicked.connect(self.add_here)
        head.addWidget(self.b_add)
        lay.addLayout(head)
        self.info = QLabel("")
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.edit = QPlainTextEdit()
        self.edit.setFixedHeight(76)
        self.edit.setPlaceholderText("Escribe el texto (Enter = nueva línea)")
        lay.addWidget(self.edit)
        from .spellcheck import attach as _spell
        self.spell = _spell(self.edit)                # ✍ ortografía (español de México / inglés / mixto)
        lay.addWidget(self.spell)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._commit)
        self.edit.textChanged.connect(lambda: None if self._loading else self._timer.start())
        ctrl.project_changed.connect(self.refresh)
        self.set_selection(sorted(getattr(timeline, "selected", [])))

    # ------------------------------------------------------------------
    def set_selection(self, ids):
        p = self.ctrl.project
        texts = [i for i in ids if i in p.clips and p.clips[i].text is not None]
        if self._timer.isActive():                   # lo escrito en el texto anterior no se pierde
            self._timer.stop()
            self._commit()
        self.clip_id = texts[0] if len(texts) == 1 else None
        self._many = len(texts) > 1
        self.refresh()

    def refresh(self, *_):
        p = self.ctrl.project
        c = p.clips.get(self.clip_id) if self.clip_id else None
        if c is None or c.text is None:
            self.clip_id = None
        on = self.clip_id is not None
        self.edit.setVisible(on)
        self.spell.setVisible(on)
        if not on:
            self.info.setText("Varios textos seleccionados: elige uno." if getattr(self, "_many", False)
                              else "Selecciona un texto en la línea de tiempo o añade uno.")
            return
        self.info.setText(f"De {c.start:.1f} a {c.end:.1f} s · tamaño, color y posición en el Inspector")
        content = str(c.text.get("content", ""))
        # se pone al día siempre (Ctrl+Z, el Inspector…), salvo mientras escribes (lo último aún no se ha guardado)
        if not self._timer.isActive() and self.edit.toPlainText() != content:
            self._loading = True
            self.edit.setPlainText(content)
            cur = self.edit.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            self.edit.setTextCursor(cur)
            self._loading = False

    def _commit(self):
        if self.clip_id and self.clip_id in self.ctrl.project.clips:
            txt = self.edit.toPlainText()
            if txt != str(self.ctrl.project.clips[self.clip_id].text.get("content", "")):
                self.ctrl.set_text_props(self.clip_id, content=txt)

    def add_here(self):
        """Un texto nuevo en el cabezal, seleccionado y listo para escribir (lo de fábrica, «Texto», ya marcado)."""
        before = set(self.ctrl.project.clips)
        self.ctrl.add_text(self.engine.time, 4.0, "Texto")
        new = [i for i in self.ctrl.project.clips if i not in before]
        if new:
            self.timeline.set_selection(new)
            self.set_selection(new)
            self.edit.setFocus()
            self.edit.selectAll()
