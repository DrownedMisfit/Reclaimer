"""
🎞 Material del clip (panel de la derecha en la pestaña YouTube): del clip elegido en la línea de tiempo, qué es, de dónde
sale (archivo y tramo), qué vio la IA y lo que se puede hacer con él: buscar momentos parecidos para cambiarlo, usarlo
como ejemplo, corregir lo que vio la IA o encontrarlo en Medios. Alt + rueda encima del clip cambia la parte que enseña.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO
from .common import fmt_time


class ClipMaterialPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctrl = win, win.ctrl
        self.clip_id = ""
        self._pic_key = None                  # (clip, parte que enseña): con Alt+rueda cambia y se recarga
        self._job = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setMinimumHeight(140)
        self.pic.setStyleSheet("background: #111; border-radius: 4px;")
        lay.addWidget(self.pic)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold; font-size: 13px;")
        lay.addWidget(self.title)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("dim")
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        g = QGridLayout()
        g.setSpacing(6)
        self.b_similar = self._btn("🔎 Momentos parecidos", "Busca en tus videos momentos que se parezcan a este clip "
                                   "(para cambiarlo por otro); salen en «🔎 Momentos»", self._similar)
        self.b_example = self._btn("🎯 Usar como ejemplo", "Enséñale a la IA lo que se ve en este clip para que lo "
                                   "encuentre en el resto de tu material", self._example)
        self.b_tags = self._btn("◈ Corregir lo que vio la IA", "Cambia o añade lo que la IA cree que se ve en este "
                                "archivo (mejora las búsquedas y el B-roll)", self._tags)
        self.b_media = self._btn("📂 Mostrarlo en Medios", "Selecciona su archivo en el panel Medios", self._media)
        for k, b in enumerate((self.b_similar, self.b_example, self.b_tags, self.b_media)):
            g.addWidget(b, k // 2, k % 2)
        lay.addLayout(g)
        lay.addStretch(1)
        win.timeline.selection_changed.connect(self.set_selection)
        self.ctrl.project_changed.connect(lambda: self.set_selection([self.clip_id] if self.clip_id else []))
        self.set_selection([])

    @staticmethod
    def _btn(text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(lambda _=False: slot())
        return b

    # ------------------------------------------------------------ qué se enseña
    def set_selection(self, ids):
        p = self.ctrl.project
        ids = [i for i in (ids or []) if i in p.clips]
        c = p.clips.get(ids[0]) if len(ids) == 1 else None
        m = p.media_of(c) if c is not None else None
        nuevo = c.id if c is not None else ""
        self.clip_id = nuevo
        for b in (self.b_similar, self.b_example, self.b_tags, self.b_media):
            b.setEnabled(m is not None)
        if c is None or m is None:
            self.title.setText("Ningún clip elegido" if len(ids) != 1 else "Clip de texto")
            self.info.setText("Haz clic en un clip de la línea de tiempo." if len(ids) != 1 else "")
            self.pic.clear()
            self.pic.setToolTip("")
            self._pic_key = None
            return
        self.b_similar.setEnabled(m.kind in (KIND_VIDEO, KIND_IMAGE))
        self.b_example.setEnabled(m.kind in (KIND_VIDEO, KIND_IMAGE))
        tipo = {KIND_VIDEO: "🎞 Video", KIND_IMAGE: "🖼 Imagen", KIND_AUDIO: "🔊 Audio"}.get(m.kind, m.kind)
        self.title.setText(m.name)
        lineas = [f"{tipo} · en la línea de tiempo del {fmt_time(c.start)} al {fmt_time(c.end)} "
                  f"({c.duration:.1f} s)"]
        if m.kind != KIND_IMAGE:
            a = c.source_in
            lineas.append(f"Del archivo: del {fmt_time(a)} al {fmt_time(a + c.duration * (c.speed or 1.0))}"
                          + (f" de {fmt_time(m.duration)}" if m.duration else "")
                          + ("  ·  ⇆ Alt + rueda encima del clip cambia la parte que enseña" if m.kind == KIND_VIDEO
                             else ""))
        if m.ai_type or m.ai_tags:
            lineas.append("◈ La IA ve: " + " · ".join([x for x in [m.ai_type] + list(m.ai_tags or []) if x]))
        elif m.kind in (KIND_VIDEO, KIND_IMAGE):
            lineas.append("◈ La IA aún no lo ha analizado (IA ✨ → Entender mis clips).")
        if m.tags:
            lineas.append("Tus etiquetas: " + ", ".join(m.tags))
        if (c.note or "").strip():
            lineas.append("Nota: " + c.note.strip())
        uso = sum(1 for o in p.clips.values() if o.media_id == m.id)
        if uso > 1:
            lineas.append(f"Este archivo sale {uso} veces en la línea de tiempo.")
        self.info.setText("\n".join(lineas))
        self.pic.setToolTip(m.path)
        key = (c.id, round(c.source_in, 2))
        if key != self._pic_key and m.kind in (KIND_VIDEO, KIND_IMAGE) and self.isVisible():
            self._pic_key = key                # (oculto no se abre el video; al enseñarse, sí)
            self._load_pic(m, c)

    def showEvent(self, e):
        super().showEvent(e)
        self.set_selection([self.clip_id] if self.clip_id else [])

    def _load_pic(self, m, c):
        """El fotograma del principio del clip, en segundo plano (abrir el video no frena la ventana)."""
        from ..core import media as media_tools
        from .jobs import BackgroundJob
        path, t, cid = m.path, (c.source_in + 0.05 if m.kind == KIND_VIDEO else 0.0), c.id
        w = max(240, self.pic.width())

        def work(_p, _c):
            if m.kind == KIND_IMAGE:
                return path
            return media_tools.frame_rgb(path, t, w)

        def fin(res=None):
            if self.clip_id != cid or res is None:
                return
            if isinstance(res, str):
                pix = QPixmap(res)
            else:
                h, ww = res.shape[:2]
                pix = QPixmap.fromImage(QImage(res.data, ww, h, ww * 3, QImage.Format_RGB888).copy())
            if not pix.isNull():
                self.pic.setPixmap(pix.scaled(self.pic.width(), max(140, self.pic.height()), Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
        job = BackgroundJob(work, self)
        job.done.connect(fin)
        job.failed.connect(lambda _m: None)
        self._job = job
        job.start()

    # ------------------------------------------------------------ acciones
    def _clip(self):
        return self.ctrl.project.clips.get(self.clip_id)

    def _similar(self):
        c = self._clip()
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.find_similar(c.id)

    def _example(self):
        c = self._clip()
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.timeline.example_requested.emit(c.id)

    def _tags(self):
        c = self._clip()
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.library._edit_ai_tags([c.media_id])
        self.set_selection([c.id])

    def _media(self):
        c = self._clip()
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.show_panel(self.win.library)
        self.win.library.select_media(c.media_id)
