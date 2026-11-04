"""
🎚 «Analizar y proponer mezcla»: la IA escucha (y lee, si hay transcripción) los diálogos y la canción, y PROPONE
cómo debe ir la música tramo a tramo, con su motivo. No cambia nada hasta que pulsas «Aplicar lo marcado» (un solo
paso de Ctrl+Z). Puedes quitar cualquier tramo, cambiar cuánto baja, los límites y la velocidad.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..core import mix_plan as MX
from .jobs import BackgroundJob

KIND_COL = {"emotivo": "#d06cf0", "accion": "#f2a03d", "normal": "#5aa0f0", "silencio": "#8a8fa0",
            "cancion": "#3fb950", "final": "#3fb950"}


class _Chart(QWidget):
    """El nivel de la música propuesto (línea) sobre el tiempo, y los tramos de voz (colores por tipo)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.items: list[dict] = []
        self.opts = dict(MX.DEFAULTS)
        self.total = 1.0

    def set_data(self, items, opts, total):
        self.items, self.opts, self.total = items, opts, max(1.0, total)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 6, -6, -18)
        p.fillRect(self.rect(), QColor("#16161a"))
        lo = float(self.opts.get("min_db", -30))

        def y_of(db):
            return r.top() + r.height() * (min(0.0, db) / lo if lo < 0 else 0)
        for x in self.items:
            if x.get("kind") in ("cancion", "final"):
                continue
            col = QColor(KIND_COL.get(x["kind"], "#5aa0f0"))
            col.setAlpha(70)
            a = r.left() + r.width() * x["a"] / self.total
            b = r.left() + r.width() * x["b"] / self.total
            p.fillRect(QRectF(a, r.top(), max(1.0, b - a), r.height()), col)
        path = QPainterPath()
        n = 400
        for i in range(n + 1):
            t = self.total * i / n
            db = MX.level_db(self.items, t, self.opts)
            pt = QPointF(r.left() + r.width() * i / n, y_of(db))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor("#3fb950"), 2))
        p.drawPath(path)
        p.setPen(QColor("#8a8fa0"))
        p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), 14), Qt.AlignLeft, "Música: arriba = a tope")
        x = r.right()                                   # la leyenda, de derecha a izquierda, con el color de cada tipo
        fm = p.fontMetrics()
        for kind, name in (("silencio", "silencio importante"), ("accion", "acción"), ("normal", "voz"),
                           ("emotivo", "emotivo")):
            w = fm.horizontalAdvance(name)
            p.setPen(QColor("#8a8fa0"))
            p.drawText(QRectF(x - w, r.bottom() + 2, w, 14), Qt.AlignRight, name)
            x -= w + 12
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(KIND_COL[kind]))
            p.drawEllipse(QPointF(x + 6, r.bottom() + 9), 3.5, 3.5)
            x -= 10
        p.end()


class MixDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.job = None
        self.result: dict | None = None
        self.setWindowTitle("🎚 Analizar y proponer mezcla")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        intro = QLabel("La IA escucha los diálogos/narración y la canción y te PROPONE cómo debe ir la música, tramo a "
                       "tramo y con su motivo. No cambia nada hasta que aceptes. Las pistas bloqueadas nunca se tocan.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        p = self.ctrl.project
        self.track_checks: dict[str, QCheckBox] = {}
        row = QHBoxLayout()
        row.addWidget(QLabel("Pistas de música:"))
        music = set(MX.music_tracks(p))
        from ..core.model import TRACK_AUDIO
        for t in p.tracks:
            if t.kind != TRACK_AUDIO:
                continue
            chk = QCheckBox(t.name + (" 🔒" if t.locked else ""))
            chk.setChecked(t.id in music and not t.locked)
            chk.setEnabled(not t.locked)
            chk.toggled.connect(lambda _on: self._clear())
            self.track_checks[t.id] = chk
            row.addWidget(chk)
        row.addStretch(1)
        lay.addLayout(row)
        form = QFormLayout()
        self.spins = {}
        for key, label, lo, hi in (("duck_db", "Al hablar, la música baja", -40, 0),
                                   ("deep_db", "En frases emotivas / prioridad a la voz", -40, 0),
                                   ("action_db", "En frases de acción", -40, 0),
                                   ("min_db", "Lo más bajo que puede quedar", -60, 0),
                                   ("max_db", "Lo más alto (0 = como está)", -20, 6),
                                   ("attack", "Tarda en bajar (s)", 0.05, 3), ("release", "Tarda en subir (s)", 0.1, 5)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(1 if "db" in key else 0.1)
            sp.setDecimals(0 if "db" in key else 2)
            sp.setSuffix(" dB" if "db" in key else " s")
            sp.setValue(float(MX.DEFAULTS[key]))
            sp.valueChanged.connect(self._refresh_chart)
            self.spins[key] = sp
            form.addRow(label, sp)
        self.shape = QCheckBox("Seguir la forma de la canción (intro y pausas suaves, la subida y el drop arriba, "
                               "el final baja poco a poco)")
        self.shape.setChecked(True)
        self.shape.toggled.connect(lambda _on: self._clear())
        form.addRow(self.shape)
        lay.addLayout(form)
        self.chart = _Chart()
        lay.addWidget(self.chart)
        self.list = QListWidget()
        self.list.itemChanged.connect(lambda _i: self._refresh_chart())
        lay.addWidget(self.list, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("Pulsa «Analizar». Consejo: un marcador llamado «voz» o «música» le da prioridad a "
                             "ese tramo.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.b_remove = QPushButton("Quitar la mezcla de la IA")
        self.b_remove.clicked.connect(self._remove)
        self.b_remove.setEnabled(any((c.fx or {}).get("mix_orig") is not None for c in p.clips.values()))
        self.b_go = QPushButton("🔍 Analizar")
        self.b_go.clicked.connect(self.analyze)
        self.b_apply = QPushButton("✓ Aplicar lo marcado")
        self.b_apply.setObjectName("primary")
        self.b_apply.setEnabled(False)
        self.b_apply.clicked.connect(self.apply)
        b_close = QPushButton("Cerrar")
        b_close.clicked.connect(self.close)
        btns.addWidget(self.b_remove)
        btns.addStretch(1)
        btns.addWidget(b_close)
        btns.addWidget(self.b_go)
        btns.addWidget(self.b_apply)
        lay.addLayout(btns)

    def opts(self) -> dict:
        o = {k: float(sp.value()) for k, sp in self.spins.items()}
        o["song_shape"] = self.shape.isChecked()
        o["tracks"] = [tid for tid, chk in self.track_checks.items() if chk.isChecked()]
        return o

    def _clear(self):
        self.result = None
        self.list.clear()
        self.b_apply.setEnabled(False)
        self.chart.set_data([], self.opts(), self.ctrl.project.duration())

    def analyze(self):
        if self.job is not None:
            return
        o = self.opts()
        if not o["tracks"]:
            self.status.setText("Marca al menos una pista de música.")
            return
        import copy
        p = copy.deepcopy(self.ctrl.project)
        rhythm_known = dict(self.ctrl.rhythm)

        def work(progress, cancelled):
            rh = {}
            if o["song_shape"]:
                from ..ai import rhythm
                mids = {c.media_id for tid in o["tracks"] for c in p.clips_on(tid)}
                for i, mid in enumerate(mids):
                    progress(0.6 * i / max(1, len(mids)), "🎵 Escuchando la canción…")
                    rh[mid] = rhythm_known.get(mid) or rhythm.analyze(p.media[mid].path)
            progress(0.7, "🗣 Buscando dónde se habla y qué se dice…")
            return MX.propose(p, o, rh, cancelled)
        self.job = BackgroundJob(work, self)
        self.job.title = "🎚 Analizar y proponer mezcla"
        self.job.progress.connect(lambda f, t: (self.bar.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(self._done)
        self.job.failed.connect(lambda m: (self.status.setText(f"⚠️ {m}"), self._end()))
        self.bar.show()
        self.b_go.setEnabled(False)
        self.job.start()

    def _end(self):
        self.job = None
        self.bar.hide()
        self.b_go.setEnabled(True)

    def _done(self, res):
        self._end()
        self.result = res
        self.list.blockSignals(True)
        self.list.clear()
        for x in res["items"]:
            it = QListWidgetItem(x["label"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, x["id"])
            it.setForeground(QColor(KIND_COL.get(x["kind"], "#e8e8ea")))
            self.list.addItem(it)
        self.list.blockSignals(False)
        n = len(res["items"])
        lk = f" · {len(res['locked'])} pista(s) bloqueada(s): no se tocan" if res["locked"] else ""
        self.status.setText(f"{n} cambios propuestos ({res['n_speech']} tramos con voz, según {res['source']}){lk}. "
                            "Quita la marca de lo que no quieras y pulsa «Aplicar lo marcado»." if n else
                            "No hay nada que proponer (no se encontró voz ni partes de la canción).")
        self.b_apply.setEnabled(bool(n))
        self._refresh_chart()

    def accepted_items(self) -> list[dict]:
        if not self.result:
            return []
        on = {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
              if self.list.item(i).checkState() == Qt.Checked}
        return [x for x in self.result["items"] if x["id"] in on]

    def _refresh_chart(self, *_a):
        o = self.opts()
        # (los niveles de cada tramo siguen a los controles: se recalculan con su tipo)
        items = [dict(x, db=self._db_for(x, o)) for x in self.accepted_items()]
        self.chart.set_data(items, o, self.ctrl.project.duration())

    @staticmethod
    def _db_for(x: dict, o: dict) -> float:
        if x["kind"] == "emotivo" or "prioridad a la voz" in x["why"]:
            return o["deep_db"]
        if x["kind"] == "accion":
            return o["action_db"]
        if x["kind"] in ("normal", "silencio"):
            return o["duck_db"]
        if x["kind"] == "cancion" and x["db"] >= -0.01:
            return o["max_db"]
        return x["db"]

    def apply(self):
        o = self.opts()
        items = [dict(x, db=self._db_for(x, o)) for x in self.accepted_items()]
        tracks = (self.result or {}).get("tracks") or []
        cv = MX.curves(self.ctrl.project, items, o, tracks)
        if self.ctrl.apply_mix(cv, tracks):
            self.ctrl.message.emit(f"🎚 Mezcla aplicada ({len(items)} tramos). Ctrl+Z la deshace; «Quitar la mezcla "
                                   "de la IA» devuelve el volumen de antes.")
            self.b_remove.setEnabled(True)
            self.accept()

    def _remove(self):
        self.ctrl.remove_mix()
        self.b_remove.setEnabled(False)
        self.status.setText("Mezcla de la IA quitada (Ctrl+Z la vuelve a poner).")

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
        super().closeEvent(e)

