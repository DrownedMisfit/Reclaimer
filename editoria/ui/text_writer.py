"""
✍ «Texto en pantalla» en la pestaña «Texto» (el usuario: «no me aparece la opción para escribir el texto… la quiero
ahí»): con un texto seleccionado en la línea de tiempo, aquí se escribe (con corrector de ortografía) y se ve al momento
en el visor. Es la misma función que el cuadro del Inspector (ctrl.set_text_props: Ctrl+Z lo deshace); el tamaño, el
color y la posición siguen en el Inspector. Sin texto seleccionado: cómo hacerlo y «T Añadir texto aquí».
🗑 Quitar: el texto seleccionado (o, sin selección, el que está en el cabezal); un Ctrl+Z lo devuelve. Mientras se
escribe aquí, Supr borra letras; con el cuadro ya vacío, Supr quita el texto. Esc = volver a la línea de tiempo.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


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
        lay.setContentsMargins(4, 2, 4, 2)
        # (20/11, auditoría: PLEGADO por defecto —está entero en Inspector → Texto—: así la transcripción, que va debajo,
        #  tiene el alto. Se recuerda como lo dejes; «T Añadir» y lo que pida escribir aquí lo abren solos)
        from .tabs import Section
        cuerpo = QWidget()
        cl = QVBoxLayout(cuerpo)
        cl.setContentsMargins(4, 0, 4, 4)
        head = QHBoxLayout()
        head.addStretch(1)
        self.b_add = QPushButton("T  Añadir")
        self.b_add.setToolTip("Un texto nuevo en el cabezal (también la tecla T); se escribe aquí mismo.\n"
                              "Tamaño, color y posición: en el Inspector.")
        self.b_add.clicked.connect(self.add_here)
        head.addWidget(self.b_add)
        # 🗑 (el usuario: «puedo añadir texto pero no eliminarlo»: al escribir aquí, Supr borraba letras, nunca el texto)
        self.b_quitar = QPushButton("🗑  Quitar")
        self.b_quitar.setToolTip("Quita el texto seleccionado (o, sin selección, el que está en el cabezal).\n"
                                 "También Supr en la línea de tiempo o en el visor. Ctrl+Z lo devuelve.")
        self.b_quitar.clicked.connect(self.quitar)
        head.addWidget(self.b_quitar)
        cl.addLayout(head)
        self.info = QLabel("")
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        cl.addWidget(self.info)
        self.edit = QPlainTextEdit()
        self.edit.setFixedHeight(76)
        self.edit.setPlaceholderText("Escribe el texto (Enter = nueva línea)")
        cl.addWidget(self.edit)
        from .spellcheck import attach as _spell
        self.spell = _spell(self.edit)                # ✍ ortografía (español de México / inglés / mixto)
        cl.addWidget(self.spell)
        self.seccion = Section("Texto en pantalla", cuerpo, False, "secciones/transcripcion/texto_en_pantalla")
        self.seccion.head.setToolTip("Escribir o quitar el texto en pantalla elegido (también en Inspector → Texto)")
        lay.addWidget(self.seccion)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._commit)
        self.edit.textChanged.connect(self._al_cambiar)
        self.edit.installEventFilter(self)            # (Supr con el cuadro vacío = quitar el texto · Esc = salir)
        ctrl.project_changed.connect(self.refresh)
        self._t_cabezal = QTimer(self)                # (🗑 activo o no según el cabezal: sin mirar en cada fotograma)
        self._t_cabezal.setSingleShot(True)
        self._t_cabezal.setInterval(200)
        self._t_cabezal.timeout.connect(self._act_quitar)
        tc = getattr(engine, "time_changed", None)
        if tc is not None:
            tc.connect(lambda *_: self._t_cabezal.isActive() or self._t_cabezal.start())
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
            self._act_quitar()
            return
        self._act_quitar()
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

    def _al_cambiar(self):
        """Lo escrito se guarda poco después; si solo cambió el formato (el corrector subraya al cargar su
        diccionario) no hay nada que guardar: así Ctrl+Z sigue poniendo el cuadro al día."""
        if self._loading:
            return
        c = self.ctrl.project.clips.get(self.clip_id) if self.clip_id else None
        if c is not None and c.text is not None and self.edit.toPlainText() == str(c.text.get("content", "")):
            self._timer.stop()
            return
        self._timer.start()

    def _commit(self):
        if self.clip_id and self.clip_id in self.ctrl.project.clips:
            txt = self.edit.toPlainText()
            if txt != str(self.ctrl.project.clips[self.clip_id].text.get("content", "")):
                self.ctrl.set_text_props(self.clip_id, content=txt)

    # ------------------------------------------------------------------ 🗑 quitar
    def _a_quitar(self) -> list[str]:
        """Los textos que quitaría 🗑: los seleccionados; si no hay, el del cabezal (el de la pista de más arriba)."""
        p = self.ctrl.project
        sel = [i for i in sorted(getattr(self.timeline, "selected", []) or [])
               if i in p.clips and p.clips[i].text is not None]
        if sel:
            return sel
        if self.clip_id and self.clip_id in p.clips:
            return [self.clip_id]
        t = float(getattr(self.engine, "time", 0.0) or 0.0)
        aqui = [c for c in p.clips.values() if c.text is not None and c.start - 1e-6 <= t < c.end]
        if not aqui:
            return []
        orden = {tr.id: i for i, tr in enumerate(p.tracks)}
        aqui.sort(key=lambda c: (orden.get(c.track_id, len(orden)), c.start))
        return [aqui[0].id]

    def _act_quitar(self):
        try:
            n = len(self._a_quitar())
        except RuntimeError:                         # (cerrando)
            return
        self.b_quitar.setEnabled(n > 0)
        self.b_quitar.setText("🗑  Quitar" if n <= 1 else f"🗑  Quitar {n}")

    def quitar(self):
        """🗑 Quita el texto seleccionado (o el del cabezal). Un paso de Ctrl+Z (ctrl.delete_clips)."""
        ids = self._a_quitar()
        if not ids:
            return False
        self._timer.stop()                           # (lo que se estaba escribiendo se va con el texto)
        self.ctrl.delete_clips(ids)
        if any(i in self.ctrl.project.clips for i in ids):
            return False                             # (bloqueado: el controlador ya lo ha dicho)
        if hasattr(self.timeline, "set_selection"):
            self.timeline.set_selection([])
        self.set_selection([])
        self.timeline.setFocus()                      # (Supr, Ctrl+Z… vuelven a ir al editor)
        return True

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() in (QEvent.ShortcutOverride, QEvent.KeyPress):
            k = ev.key()
            vacio = not self.edit.toPlainText()
            if (k == Qt.Key_Delete and vacio) or k == Qt.Key_Escape:
                ev.accept()
                if ev.type() == QEvent.KeyPress:
                    if k == Qt.Key_Delete:
                        self.quitar()                # (todo borrado y otra vez Supr: fuera el texto)
                    else:
                        self.timeline.setFocus()
                return True
        return super().eventFilter(obj, ev)

    def add_here(self):
        """Un texto nuevo en el cabezal, seleccionado y listo para escribir (lo de fábrica, «Texto», ya marcado)."""
        self.seccion.set_open(True, save=False)        # (plegado: se abre para escribir)
        before = set(self.ctrl.project.clips)
        with self.ctrl.sin_abrir_editor():           # (🧭 su editor es este cuadro: no salta al Inspector)
            self.ctrl.add_text(self.engine.time, 4.0, "Texto")
        new = [i for i in self.ctrl.project.clips if i not in before]
        if new:
            self.timeline.set_selection(new)
            self.set_selection(new)
            self.edit.setFocus()
            self.edit.selectAll()
