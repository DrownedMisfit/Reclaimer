"""
🎬 «Escenas sin usar» (panel IA ✨ → Inicio, debajo de las herramientas): las escenas de tus videos que aún no salen
en la línea de tiempo, con su miniatura. Eliges las que quieras (Ctrl+clic para varias: el número es el orden en que
las elegiste) y:
  · «➕ Añadir a los huecos»: van a los huecos de la pista de video que tienen audio debajo, en tu orden (al ritmo
    de la canción si lo tiene reconocido; si no, cada escena dura lo que dura);
  · «Desde cero»: la pista de video se vacía en el tramo de la canción y se rellena SOLO con esas escenas, al ritmo.
Un Ctrl+Z lo deshace. Las escenas se detectan solas (y se guardan); la lista se pone al día al editar.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..core import scene_pool as SP
from .common import fmt_time
from .jobs import BackgroundJob


class UnusedScenes(QWidget):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.scenes: dict[str, list[tuple[float, float]]] = {}    # archivo → escenas (todas)
        self.thumbs: dict[tuple[str, float], str] = {}
        self.order: list[tuple[str, float, float]] = []           # lo elegido, en el orden en que lo elegiste
        self.job: BackgroundJob | None = None
        head = QHBoxLayout()
        title = QLabel("Escenas sin usar")
        title.setObjectName("title")
        self.count = QLabel("")
        self.count.setObjectName("hint")
        self.btn_scan = QPushButton("↻ Buscar")
        self.btn_scan.setToolTip("Busca las escenas (cortes de cámara) de tus videos; las ya buscadas salen al momento.")
        self.btn_scan.clicked.connect(self.scan)
        head.addWidget(title)
        head.addWidget(self.count)
        head.addStretch(1)
        head.addWidget(self.btn_scan)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(128, 72))
        self.list.setGridSize(QSize(140, 100))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWrapping(True)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setMinimumHeight(230)
        self.list.setToolTip("Las escenas de tus videos que aún no están en la línea de tiempo.\n"
                             "Ctrl+clic = elegir varias (el número es el orden en que las elegiste).")
        self.list.itemSelectionChanged.connect(self._selection_changed)
        row = QHBoxLayout()
        self.btn_fill = QPushButton("➕ Añadir a los huecos")
        self.btn_fill.setObjectName("primary")
        self.btn_fill.setToolTip("Las elegidas, en tu orden, en los huecos de la pista de video que tienen audio "
                                 "debajo. Con el ritmo de la canción reconocido, cada plano termina en un golpe.")
        self.btn_fill.clicked.connect(self.fill)
        self.btn_scratch = QPushButton("Desde cero")
        self.btn_scratch.setToolTip("Rehace la pista de video en el tramo de la canción SOLO con las elegidas, en tu "
                                    "orden y al ritmo (un plano por compás). Ctrl+Z lo devuelve.")
        self.btn_scratch.clicked.connect(self.scratch)
        self.btn_none = QPushButton("Ninguna")
        self.btn_none.setObjectName("flat")
        self.btn_none.clicked.connect(self.list.clearSelection)
        row.addWidget(self.btn_fill)
        row.addWidget(self.btn_scratch)
        row.addStretch(1)
        row.addWidget(self.btn_none)
        self.info = QLabel("")
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.addLayout(head)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        lay.addWidget(self.info)
        from .common import lazy_refresh
        self._lazy = lazy_refresh(self, self.rebuild)
        ctrl.project_changed.connect(self._lazy)
        self._scanned_once = False
        self._update_buttons()

    # ------------------------------------------------------------ buscar
    def showEvent(self, e):
        super().showEvent(e)
        if not self._scanned_once:            # la primera vez que se ve: buscar (lo ya buscado sale al momento)
            self._scanned_once = True
            self.scan()

    def scan(self):
        if self.job is not None and self.job.isRunning():
            return
        p = self.ctrl.project
        vids = [(m.id, m.path, float(m.duration)) for m in SP.video_media(p, self.ctrl.missing)]
        if not vids:
            self.count.setText("")
            self.info.setText("Importa videos en Medios para ver sus escenas.")
            return
        used = {mid: SP.used_ranges(p, mid) for mid, _p, _d in vids}

        def work(progress, cancelled, partial):
            for i, (mid, path, dur) in enumerate(vids):
                if cancelled():
                    return
                sc = SP.scenes_of(path, dur, lambda f, i=i: progress((i + f) / len(vids), "Buscando escenas…"),
                                  cancelled)
                partial(("scenes", mid, sc))
                for a, b in sc:                         # miniaturas: primero las no usadas
                    if cancelled():
                        return
                    if sum(max(0.0, min(b, y) - max(a, x)) for x, y in used.get(mid, [])) >= 0.3 * (b - a):
                        continue
                    th = SP.thumb(path, (a + b) / 2)
                    if th:
                        partial(("thumb", mid, a, th))

        self.job = BackgroundJob(work, self, with_partial=True)
        self.job.partial.connect(self._partial)
        self.job.progress.connect(lambda f, _t: self.count.setText(f"buscando… {int(f * 100)} %"))
        self.job.done.connect(lambda _r: self.rebuild())
        self.job.failed.connect(lambda msg: self.info.setText("No se pudieron buscar las escenas: " + msg))
        self.count.setText("buscando…")
        self.job.start()

    def _partial(self, msg):
        if msg[0] == "scenes":
            self.scenes[msg[1]] = list(msg[2])
            self.rebuild()
        else:
            _k, mid, a, path = msg
            self.thumbs[(mid, a)] = path
            for i in range(self.list.count()):
                it = self.list.item(i)
                d = it.data(Qt.UserRole)
                if d[0] == mid and abs(d[1] - a) < 1e-6:
                    it.setIcon(QIcon(QPixmap(path)))
                    break

    # ------------------------------------------------------------ lista
    def unused_list(self) -> list[tuple[str, float, float]]:
        p = self.ctrl.project
        out = []
        for m in SP.video_media(p, self.ctrl.missing):
            for a, b in SP.unused(p, m.id, self.scenes.get(m.id, [])):
                out.append((m.id, a, b))
        return out

    def rebuild(self):
        keep = list(self.order)
        items = self.unused_list()
        self.list.blockSignals(True)
        self.list.clear()
        p = self.ctrl.project
        for mid, a, b in items:
            it = QListWidgetItem(fmt_time(a, False))
            it.setData(Qt.UserRole, (mid, a, b))
            m = p.media.get(mid)
            it.setToolTip(f"{m.name if m else ''}\n{fmt_time(a, False)} – {fmt_time(b, False)}  ({b - a:.1f} s)")
            th = self.thumbs.get((mid, a))
            if th:
                it.setIcon(QIcon(QPixmap(th)))
            self.list.addItem(it)
        keys = {(mid, a) for mid, a, _b in items}
        self.order = [k for k in keep if (k[0], k[1]) in keys]
        for i in range(self.list.count()):
            it = self.list.item(i)
            if tuple(it.data(Qt.UserRole)) in {tuple(o) for o in self.order}:
                it.setSelected(True)
        self.list.blockSignals(False)
        self._number()
        total = sum(len(v) for v in self.scenes.values())
        if self.job is None or not self.job.isRunning():
            self.count.setText(f"{len(items)} de {total}" if total else "")
        self._update_buttons()

    def _selection_changed(self):
        sel = [tuple(it.data(Qt.UserRole)) for it in self.list.selectedItems()]
        now = set(sel)
        self.order = [o for o in self.order if tuple(o) in now]
        have = {tuple(o) for o in self.order}
        rows = {tuple(self.list.item(i).data(Qt.UserRole)): i for i in range(self.list.count())}
        for s in sorted((s for s in sel if s not in have), key=lambda s: rows.get(s, 0)):
            self.order.append(s)                       # las nuevas, detrás (en el orden de la lista si eran varias)
        self._number()
        self._update_buttons()

    def _number(self):
        pos = {tuple(o): k + 1 for k, o in enumerate(self.order)}
        for i in range(self.list.count()):
            it = self.list.item(i)
            d = tuple(it.data(Qt.UserRole))
            base = fmt_time(d[1], False)
            it.setText(f"{pos[d]} · {base}" if d in pos else base)

    def _update_buttons(self):
        n = len(self.order)
        self.btn_fill.setEnabled(n > 0)
        self.btn_scratch.setEnabled(n > 0)
        self.btn_none.setEnabled(n > 0)
        self.btn_fill.setText(f"➕ Añadir a los huecos ({n})" if n else "➕ Añadir a los huecos")

    # ------------------------------------------------------------ meterlas
    def fill(self):
        p = self.ctrl.project
        v1 = SP.main_video_track(p)
        if v1 is None or not self.order:
            return
        gaps = SP.gaps_over_audio(p, v1.id)
        if not gaps:
            self.info.setText("No hay huecos con audio debajo en la pista de video principal.")
            return
        beats = self.ctrl.song_beats(gaps[0][0] - 1.0, gaps[-1][1] + 1.0)
        items = SP.fill_items(list(self.order), gaps, beats)
        if not items:
            self.info.setText("Los huecos son demasiado cortos.")
            return
        self.ctrl.place_scene_items(items, "🎬 Escenas en los huecos")
        left = len(self.order) - len(items)
        self.info.setText(f"✓ {len(items)} escena(s) en los huecos" + (" al ritmo de la canción" if beats else "")
                          + (f"; {left} no cabían" if left > 0 else "") + ". Ctrl+Z lo deshace.")
        self.order = []

    def scratch(self):
        span = self.ctrl.song_span()
        if span is None:
            self.info.setText("Primero pon la canción (o un audio) en la línea de tiempo.")
            return
        a, b = span
        if QMessageBox.question(self, "Desde cero",
                                f"Se vacía la pista de video de {fmt_time(a, False)} a {fmt_time(b, False)} y se "
                                f"rellena solo con las {len(self.order)} escena(s) elegidas, al ritmo de la canción."
                                "\n\nCtrl+Z lo devuelve todo.") != QMessageBox.Yes:
            return
        beats = self.ctrl.song_beats(a, b)
        items = SP.scratch_items(list(self.order), a, b, beats)
        self.ctrl.place_scene_items(items, "🎬 Edit desde cero con tus escenas", clear=(a, b))
        self.info.setText(f"✓ Edit desde cero: {len(items)} planos con tus {len(self.order)} escena(s)"
                          + (" al ritmo de la canción." if beats else " (cada 2 s: la canción no tiene ritmo "
                                                                     "reconocido).") + " Ctrl+Z lo deshace.")
        self.order = []
