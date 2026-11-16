"""
🎞 Material del clip (panel de la derecha en la pestaña YouTube): lo que estás usando o seleccionando, qué es, de dónde
sale (archivo y tramo), qué vio la IA y lo que se puede hacer con él: buscar momentos parecidos para cambiarlo, usarlo
como ejemplo, corregir lo que vio la IA o encontrarlo en Medios. Alt + rueda encima del clip cambia la parte que enseña.
Qué enseña: el clip elegido en la línea de tiempo; si no hay, lo último que tocaste entre lo seleccionado en Medios y el
clip que está en el cabezal. Los botones solo aparecen cuando sirven para lo que se ve.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO
from .common import fmt_time


class ClipMaterialPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctrl = win, win.ctrl
        self.clip_id = ""
        self.media_id = ""                    # (lo que se enseña de Medios, sin clip)
        self._sel: list = []                  # lo elegido en la línea de tiempo
        self._ultimo = "cabezal"              # «medios» o «cabezal»: lo último que tocaste
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
        self.ctrl.project_changed.connect(lambda: self.set_selection(self._sel))
        self._seguir = QTimer(self)               # el cabezal: se mira poco a poco (no en cada fotograma)
        self._seguir.setSingleShot(True)
        self._seguir.setInterval(250)
        self._seguir.timeout.connect(lambda: self.set_selection(self._sel))
        eng = getattr(win, "engine", None)
        if eng is not None:
            eng.time_changed.connect(self._cabezal_movido)
            eng.playing_changed.connect(lambda _on: self.set_selection(self._sel))   # (al pausar: su fotograma)
        tree = getattr(getattr(win, "library", None), "tree", None)
        if tree is not None:                      # (solo un clic tuyo: si Medios se rehace solo, no cambia)
            tree.itemClicked.connect(lambda *_a: self._medios_elegido())
        self.set_selection([])

    def _reproduciendo(self) -> bool:
        return bool(getattr(getattr(self.win, "engine", None), "playing", False))

    def _cabezal_movido(self, _t=None):
        if not self._reproduciendo():             # (mover tú el cabezal = vuelves a lo del cabezal; reproducir, no)
            self._ultimo = "cabezal"
        if not self._sel and self.isVisible() and not self._seguir.isActive():
            self._seguir.start()

    def _medios_elegido(self):
        self._ultimo = "medios"
        if not self._sel:
            self.set_selection(self._sel)

    def _en_cabezal(self):
        """El clip que se ve ahora en el cabezal (la pista de video más alta con algo que no sea texto)."""
        eng = getattr(self.win, "engine", None)
        if eng is None:
            return None
        p = self.ctrl.project
        for tr in p.tracks:
            if tr.kind != "video" or tr.hidden:
                continue
            c = p.clip_at(tr.id, float(eng.time))
            if c is not None and c.text is None and c.enabled and p.media_of(c) is not None:
                return c
        return None

    def _de_medios(self):
        lib = getattr(self.win, "library", None)
        try:
            ids = lib.tree.selected_media_ids() if lib is not None else []
        except RuntimeError:
            ids = []
        return self.ctrl.project.media.get(ids[0]) if len(ids) == 1 else None

    def _botones(self, *visibles):
        for b in (self.b_similar, self.b_example, self.b_tags, self.b_media):
            b.setVisible(b in visibles)

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
        self._sel = ids
        c = p.clips.get(ids[0]) if len(ids) == 1 else None
        origen = "elegido"
        if not ids:                               # nada elegido: lo que estás usando o seleccionando
            mm = self._de_medios() if self._ultimo == "medios" else None
            if mm is not None:
                return self._enseñar_medio(mm)
            c = self._en_cabezal()
            origen = "cabezal"
            if c is None:
                mm = self._de_medios()
                if mm is not None:
                    return self._enseñar_medio(mm)
        m = p.media_of(c) if c is not None else None
        self.clip_id = c.id if c is not None else ""
        self.media_id = ""
        if c is None or m is None:
            self._botones()
            self.pic.setVisible(False)
            self.title.setText("Clip de texto" if len(ids) == 1 else ("Varios clips elegidos" if ids else
                                                                       "Nada en el cabezal"))
            self.info.setText("" if len(ids) == 1 else ("Elige solo uno para ver su material." if ids else
                              "Aquí sale el clip que está en el cabezal, el que elijas en la línea de tiempo o lo "
                              "que selecciones en Medios."))
            self.pic.clear()
            self.pic.setToolTip("")
            self._pic_key = None
            return
        self.pic.setVisible(m.kind in (KIND_VIDEO, KIND_IMAGE))
        visual = m.kind in (KIND_VIDEO, KIND_IMAGE)
        self._botones(*([self.b_similar, self.b_example] if visual else []), self.b_tags, self.b_media)
        tipo = {KIND_VIDEO: "🎞 Video", KIND_IMAGE: "🖼 Imagen", KIND_AUDIO: "🔊 Audio"}.get(m.kind, m.kind)
        self.title.setText(("▶ En el cabezal: " if origen == "cabezal" else "") + m.name)
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
            lineas.append("◈ La IA aún no lo ha analizado (pestaña IA ✨ → «✨ Más» → Analizar el contenido).")
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
            self.pic.clear()                   # (nada del clip anterior mientras llega el nuevo)
            if origen == "cabezal" and self._reproduciendo():
                self._pic_key = None           # (reproduciendo: solo el texto; el fotograma, al pausar)
                return
            self._pic_key = key                # (oculto no se abre el video; al enseñarse, sí)
            self._load_pic(m, c)

    def _enseñar_medio(self, m):
        """Lo seleccionado en Medios (sin clip): qué es, qué vio la IA; botones: ejemplo y corregir la IA."""
        p = self.ctrl.project
        self.clip_id, self.media_id = "", m.id
        visual = m.kind in (KIND_VIDEO, KIND_IMAGE)
        self.pic.setVisible(visual)
        self._botones(*([self.b_example] if visual else []), self.b_tags)
        tipo = {KIND_VIDEO: "🎞 Video", KIND_IMAGE: "🖼 Imagen", KIND_AUDIO: "🔊 Audio"}.get(m.kind, m.kind)
        self.title.setText("📂 En Medios: " + m.name)
        lineas = [tipo + (f" · {fmt_time(m.duration)}" if m.duration else "")]
        if m.ai_type or m.ai_tags:
            lineas.append("◈ La IA ve: " + " · ".join([x for x in [m.ai_type] + list(m.ai_tags or []) if x]))
        elif visual:
            lineas.append("◈ La IA aún no lo ha analizado (pestaña IA ✨ → «✨ Más» → Analizar el contenido).")
        if m.tags:
            lineas.append("Tus etiquetas: " + ", ".join(m.tags))
        uso = sum(1 for o in p.clips.values() if o.media_id == m.id)
        lineas.append(f"Sale {uso} veces en la línea de tiempo." if uso else "Aún no está en la línea de tiempo.")
        self.info.setText("\n".join(lineas))
        self.pic.setToolTip(m.path)
        key = ("medio", m.id)
        if key != self._pic_key and visual and self.isVisible():
            self.pic.clear()
            self._pic_key = key
            from types import SimpleNamespace
            self._load_pic(m, SimpleNamespace(id="", source_in=min(1.0, (m.duration or 0) * 0.1)))

    def showEvent(self, e):
        super().showEvent(e)
        self.set_selection(self._sel)

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

        mid = m.id

        def fin(res=None):
            if res is None or self.clip_id != cid or (not cid and self.media_id != mid):
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
        if c is None and self.media_id:           # (lo seleccionado en Medios)
            self.win.library.example_requested.emit(self.media_id, None)
            return
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.timeline.example_requested.emit(c.id)

    def _tags(self):
        c = self._clip()
        if c is None and self.media_id:
            self.win.library._edit_ai_tags([self.media_id])
            self.set_selection(self._sel)
            return
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.library._edit_ai_tags([c.media_id])
        self.set_selection(self._sel)

    def _media(self):
        c = self._clip()
        if c is None:
            self.win.statusBar().showMessage("Haz clic antes en un clip de la línea de tiempo.", 5000)
            return
        self.win.show_panel(self.win.library)
        self.win.library.select_media(c.media_id)
