"""
🔑 Palabras clave: escribe palabras o frases («Marcus, traición, explosión») y te dice DÓNDE se dicen en tus
videos y audios, gastando poco (ver ai/keywords.py). Resultados: arrástralos a la línea de tiempo, ponlos en el
cabezal o, si buscaste en la línea de tiempo, márcalos con marcadores.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..ai import keywords as KW
from ..core.model import KIND_AUDIO, KIND_VIDEO
from .common import SEGMENT_MIME, fmt_time


class _Results(QTreeWidget):
    """Los resultados se arrastran a la línea de tiempo (el trozo del archivo con un poco de margen)."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):
        md = QMimeData()
        h = items[0].data(0, Qt.UserRole) if items else None
        if h:
            a, b = max(0.0, h["t0"] - 1.5), h["t1"] + 1.5
            md.setData(SEGMENT_MIME, f"{h['media_id']}|{a:.3f}|{b:.3f}".encode())
        return md


class KeywordsDialog(QDialog):
    def __init__(self, win, scope: str = "timeline", media_ids: list[str] | None = None):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.media_ids = media_ids
        self.setWindowTitle("🗣 Buscar lo que se dice")
        self.resize(760, 520)
        from .help import set_help
        set_help(self, "buscar_palabras")              # («¿Qué hace esto?» en cualquier parte del diálogo)
        lay = QVBoxLayout(self)
        tip = QLabel("Escribe palabras o frases separadas por comas. Solo se escucha donde hay voz (sin la música "
                     "ni el silencio) y con un modelo pequeño: gasta poco y puedes seguir editando. Lo escuchado "
                     "se guarda: buscar otra vez en el mismo archivo es instantáneo.")
        tip.setWordWrap(True)
        tip.setObjectName("dim")
        lay.addWidget(tip)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Marcus, la traición, explosión…")
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 1)
        self.scope = QComboBox()
        self.scope.addItem("En los clips de la línea de tiempo", "timeline")
        self.scope.addItem("En lo seleccionado en Medios", "selected")
        self.scope.addItem("En todos los videos y audios de Medios", "all")
        if media_ids:
            self.scope.addItem(f"En {len(media_ids)} archivo(s) elegido(s)", "given")
        self.scope.setCurrentIndex(max(0, self.scope.findData("given" if media_ids else scope)))
        row.addWidget(self.scope)
        self.b_go = QPushButton("🗣 Buscar")
        self.b_go.setObjectName("primary")
        self.b_go.clicked.connect(self.search)
        row.addWidget(self.b_go)
        lay.addLayout(row)
        self.tree = _Results()
        self.tree.setHeaderLabels(["Palabra", "Archivo", "Momento", "Lo que se dice"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 190)
        self.tree.setColumnWidth(2, 90)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.go(it))
        lay.addWidget(self.tree, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        self.b_put = QPushButton("➕ Poner en el cabezal")
        self.b_put.clicked.connect(self.put_selected)
        self.b_marks = QPushButton("📍 Marcadores en la línea de tiempo")
        self.b_marks.clicked.connect(self.add_markers)
        bottom.addWidget(self.b_put)
        bottom.addWidget(self.b_marks)
        bottom.addStretch(1)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        bottom.addWidget(b_close)
        lay.addLayout(bottom)
        self.hits: list[dict] = []

    # ------------------------------------------------------------ qué archivos
    def _targets(self) -> list[tuple[str, str]]:
        p = self.ctrl.project
        key = self.scope.currentData()
        if key == "given":
            ids = list(self.media_ids or [])
        elif key == "selected":
            ids = self.win.library.selected_media_ids()
        elif key == "all":
            ids = list(p.media)
        else:
            ids = list(dict.fromkeys(c.media_id for c in p.clips.values() if c.text is None))
        out = []
        for mid in ids:
            m = p.media.get(mid)
            if m is not None and mid not in self.ctrl.missing and (m.kind == KIND_AUDIO or
                                                                  (m.kind == KIND_VIDEO and m.has_audio)):
                out.append((mid, m.path))
        return out

    def search(self):
        from .task_window import manager
        query = KW.parse_query(self.query.text())
        if not query:
            self.status.setText("Escribe antes alguna palabra.")
            return
        targets = self._targets()
        if not targets:
            self.status.setText("No hay videos o audios con sonido donde buscar (elige otro «En…»).")
            return
        transcripts = {mid: self.ctrl.project.transcripts.get(mid) for mid, _p in targets}
        self.b_go.setEnabled(False)
        self.status.setText(f"🔑 Buscando en {len(targets)} archivo(s)…")

        def work(progress, cancelled):
            hits = []
            for k, (mid, path) in enumerate(targets):
                got = KW.find(path, query, transcripts.get(mid),
                              lambda f, t, k=k: progress((k + f) / len(targets), t), cancelled)
                hits += [dict(h, media_id=mid) for h in got]
            return hits

        def done(hits):
            self.b_go.setEnabled(True)
            self.show_hits(hits)

        def fail(msg):
            self.b_go.setEnabled(True)
            self.status.setText("✗ " + msg)
        manager().start("🗣 Buscar lo que se dice", work, done, fail)

    def _timeline_times(self, h) -> list[float]:
        """Dónde está ese instante del archivo en la línea de tiempo (si está puesto)."""
        out = []
        for c in self.ctrl.project.clips.values():
            if c.media_id != h["media_id"] or c.speed <= 0:
                continue
            lo, hi = sorted((c.src_at(0.0), c.src_at(c.duration)))
            if lo - 1e-3 <= h["t0"] <= hi + 1e-3:
                local = (h["t0"] - c.source_in) / c.speed if not c.reverse else \
                    c.duration - (h["t0"] - c.source_in) / c.speed
                out.append(round(c.start + local, 3))
        return sorted(set(out))

    def show_hits(self, hits: list[dict]):
        p = self.ctrl.project
        timeline = self.scope.currentData() == "timeline"
        if timeline:
            hits = [dict(h, tl=self._timeline_times(h)) for h in hits]
            hits = [h for h in hits if h["tl"]]
        self.hits = hits
        self.tree.clear()
        for h in hits:
            m = p.media.get(h["media_id"])
            when = fmt_time(h["tl"][0], False) if h.get("tl") else fmt_time(h["t0"], False)
            it = QTreeWidgetItem([h["word"], m.name if m else "?", when, h["context"]])
            it.setToolTip(3, f"Se oye: «{h['said']}» (parecido {int(h['score'] * 100)} %)")
            it.setData(0, Qt.UserRole, h)
            self.tree.addTopLevelItem(it)
        words = sorted({h["word"] for h in hits})
        self.status.setText(f"✓ {len(hits)} vez/veces: " + ", ".join(words) if hits else
                            "No se dice en esos archivos (prueba otra forma de decirlo).")
        self.b_marks.setEnabled(timeline and bool(hits))

    # ------------------------------------------------------------ acciones
    def go(self, it):
        h = it.data(0, Qt.UserRole)
        if h and h.get("tl"):
            self.win.engine.user_seek(h["tl"][0])
        elif h:
            self.put(h)

    def put(self, h):
        a, b = max(0.0, h["t0"] - 1.5), h["t1"] + 1.5
        cid = self.ctrl.place_segment(h["media_id"], a, b - a, "insert", self.win.engine.time,
                                      note=f"🔑 «{h['word']}»")
        if isinstance(cid, str):
            self.win.timeline.set_selection([cid])

    def put_selected(self):
        it = self.tree.currentItem()
        if it is None:
            self.status.setText("Elige un resultado de la lista (o arrástralo a la línea de tiempo).")
            return
        self.put(it.data(0, Qt.UserRole))

    def add_markers(self):
        from ..core.model import Marker, new_id
        items = [(t, h["word"]) for h in self.hits for t in h.get("tl", [])]
        if not items:
            return

        def fn(p):
            for t, w in items:
                if not any(abs(mk.time - t) < 0.05 and mk.label == f"🔑 {w}" for mk in p.markers):
                    p.markers.append(Marker(new_id(), t, f"🔑 {w}", "#5fd8ff"))
            return len(items)
        self.ctrl._edit("🔑 Marcadores de palabras clave", fn)
        self.status.setText(f"📍 {len(items)} marcador(es) puestos en la línea de tiempo (Ctrl+Z los quita).")
