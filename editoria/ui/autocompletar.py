"""
✨ «Autocompletar» (panel IA ✨ → Inicio; se ve en las tres pestañas: Video horizontal, Edits y Vertical): eliges un
video y tapa las partes de la línea de tiempo donde no se ve nada (todos los huecos, solo el tramo I/O o solo el
hueco elegido) SOLO con lo que aún no usas de él. A la vista: cuántas veces sale ya y qué tramos (de mm:ss a mm:ss ×N)
y cuánto queda libre. Usa las escenas de 🎬 «Escenas sin usar» (las comparte; si faltan, las busca antes con progreso),
al ritmo de la música si la tiene reconocida; un solo Ctrl+Z; los clips nuevos quedan elegidos.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSettings
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout)

from ..core import autocompletar as AC
from ..core import scene_pool as SP
from ..core.model import KIND_VIDEO, TRACK_VIDEO
from .common import fmt_time
from .jobs import BackgroundJob

DONDE = [("todos", "Todos los huecos"), ("io", "Solo el tramo marcado (I/O)"), ("elegido", "Solo lo elegido")]
DONDE_TIP = {
    "todos": "Donde hay voz o música y ningún clip de video encima (sin audio: hasta el final de la línea de tiempo).",
    "io": "Solo lo vacío entre la entrada (I) y la salida (O).",
    "elegido": "Solo el hueco que elegiste en la línea de tiempo (clic en un hueco entre clips).",
}


class _Combo(QComboBox):
    """Desplegable que se pone al día justo antes de abrirse."""
    def __init__(self, before_popup):
        super().__init__()
        self._before = before_popup

    def showPopup(self):
        self._before()
        super().showPopup()


class Autocompletar(QGroupBox):
    def __init__(self, ctrl, timeline=None, scenes: dict | None = None, parent=None):
        super().__init__("✨ Autocompletar", parent)
        self.ctrl = ctrl
        self.timeline = timeline
        self.scenes = scenes if scenes is not None else {}     # (las de 🎬 Escenas sin usar: mismo diccionario)
        self.settings = QSettings("EditorIA", "EditorIA")
        self.job: BackgroundJob | None = None
        self._lib_hooked = False
        self._manual_t = None                    # cuándo elegiste el video a mano (la línea de tiempo no lo pisa)
        self._cancelling = False
        self.last_missing = 0.0                  # (segundos que quedaron sin tapar la última vez)
        self.setToolTip("Tapa las partes donde no se ve nada con lo que aún no usas del video elegido.\n"
                        "Nunca repite un tramo ya usado; un Ctrl+Z lo deshace.")
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.addWidget(QLabel("Video"), 0, 0)
        self.video = _Combo(self.refresh_videos)
        self.video.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.video.setMinimumContentsLength(12)
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.video.setToolTip("El video con el que se rellena (de Medios). Sigue a lo que eliges en Medios o en la "
                              "línea de tiempo.")
        self.video.currentIndexChanged.connect(lambda _i: self.refresh_summary())
        self.video.activated.connect(self._picked_by_hand)
        g.addWidget(self.video, 0, 1, 1, 3)
        g.addWidget(QLabel("Dónde"), 1, 0)
        self.donde = _Combo(self.refresh_donde)
        for key, label in DONDE:
            self.donde.addItem(label, key)
            self.donde.setItemData(self.donde.count() - 1, DONDE_TIP[key], 3)     # (3 = Qt.ToolTipRole)
        self.donde.setToolTip("\n".join(f"• {label}: {DONDE_TIP[k]}" for k, label in DONDE))
        g.addWidget(self.donde, 1, 1, 1, 3)
        g.addWidget(QLabel("Trozos"), 2, 0)
        self.lo = QDoubleSpinBox()
        self.lo.setRange(0.5, 20.0)
        self.lo.setSingleStep(0.5)
        self.lo.setSuffix(" s")
        self.hi = QDoubleSpinBox()
        self.hi.setRange(0.5, 30.0)
        self.hi.setSingleStep(0.5)
        self.hi.setSuffix(" s")
        self.lo.setValue(float(self.settings.value("autocompletar/min", 2.0)))
        self.hi.setValue(float(self.settings.value("autocompletar/max", 6.0)))
        for w in (self.lo, self.hi):
            w.setToolTip("Cuánto dura cada trozo (de… a…). Con el ritmo de la canción reconocido, cada trozo "
                         "termina en un golpe.")
        rowt = QHBoxLayout()
        rowt.addWidget(self.lo)
        rowt.addWidget(QLabel("a"))
        rowt.addWidget(self.hi)
        g.addLayout(rowt, 2, 1)
        self.orden = QComboBox()
        self.orden.addItem("Variado", "variado")
        self.orden.addItem("En orden del video", "video")
        self.orden.setToolTip("Variado: salta de plano en plano (cada uno sigue por donde se quedó).\n"
                              "En orden del video: de principio a fin, como pasa en el video.")
        if self.settings.value("autocompletar/orden", "variado") == "video":
            self.orden.setCurrentIndex(1)
        g.addWidget(self.orden, 2, 2, 1, 2)
        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.btn = QPushButton("✨ Autocompletar")
        self.btn.setObjectName("primary")
        self.btn.setMinimumHeight(30)
        self.btn.setToolTip("Rellena el sitio elegido SOLO con partes no usadas del video, sin repetir ningún tramo. "
                            "Si sus escenas no están buscadas, las busca primero. Ctrl+Z lo deshace.")
        self.btn.clicked.connect(self.run)
        self.btn_cancel = QPushButton("✕ Cancelar")
        self.btn_cancel.setToolTip("Para la búsqueda de escenas (no se rellena nada).")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        self.info = QLabel("")
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(g)
        lay.addWidget(self.summary)
        lay.addWidget(self.progress)
        rowb = QHBoxLayout()
        rowb.addWidget(self.btn, 1)
        rowb.addWidget(self.btn_cancel)
        lay.addLayout(rowb)
        lay.addWidget(self.info)
        from .common import lazy_refresh
        self._lazy = lazy_refresh(self, self.refresh)
        ctrl.project_changed.connect(self._lazy)
        ctrl.media_changed.connect(self._lazy)
        ctrl.project_replaced.connect(self._lazy)
        if timeline is not None and hasattr(timeline, "selection_changed"):
            timeline.selection_changed.connect(self._follow_timeline)
        self.refresh()

    # ------------------------------------------------------------ estado
    def showEvent(self, e):
        super().showEvent(e)
        self._hook_library()
        self.refresh()

    def _library_tree(self):
        lib = getattr(self.window(), "library", None)
        return getattr(lib, "tree", lib)

    def _hook_library(self):
        if self._lib_hooked:
            return
        tree = self._library_tree()
        if tree is not None and hasattr(tree, "itemSelectionChanged"):
            tree.itemSelectionChanged.connect(self._follow_library)
            self._lib_hooked = True

    def _videos(self):
        return SP.video_media(self.ctrl.project, self.ctrl.missing)

    def media_id(self) -> str:
        return self.video.currentData() or ""

    def set_media(self, mid: str) -> bool:
        i = self.video.findData(mid)
        if i >= 0:
            self.video.setCurrentIndex(i)
        return i >= 0

    MANUAL_SECS = 20.0      # elegido a mano: la línea de tiempo no lo cambia durante este rato (Medios sí)

    def _picked_by_hand(self, _i=None):
        self._manual_t = time.monotonic()

    def _follow_library(self):
        tree = self._library_tree()
        ids = tree.selected_media_ids() if tree is not None and hasattr(tree, "selected_media_ids") else []
        p = self.ctrl.project
        for mid in ids:
            m = p.media.get(mid)
            if m is not None and m.kind == KIND_VIDEO and self.set_media(mid):
                self._manual_t = None                # (elegir en Medios manda sobre lo elegido a mano)
                return

    def _follow_timeline(self, ids):
        if self._manual_t is not None and time.monotonic() - self._manual_t < self.MANUAL_SECS:
            return
        p = self.ctrl.project
        for cid in ids or []:
            c = p.clips.get(cid)
            m = p.media_of(c) if c is not None else None
            if m is not None and m.kind == KIND_VIDEO and self.set_media(m.id):
                return

    def refresh(self):
        self.refresh_videos()
        self.refresh_donde()
        self.refresh_summary()

    def refresh_videos(self):
        cur = self.media_id()
        vids = self._videos()
        if [self.video.itemData(i) for i in range(self.video.count())] != [m.id for m in vids]:
            self.video.blockSignals(True)
            self.video.clear()
            for m in vids:
                self.video.addItem(m.name, m.id)
                self.video.setItemData(self.video.count() - 1, m.path, 3)
            self.video.blockSignals(False)
            if not self.set_media(cur):
                self._follow_library()
                if self.timeline is not None:
                    self._follow_timeline(sorted(getattr(self.timeline, "selected", ()) or ()))
        self.btn.setEnabled(bool(vids) and not (self.job is not None and self.job.isRunning()))

    def _gap(self):
        g = getattr(self.timeline, "gap", None) if self.timeline is not None else None
        if g is None:
            return None
        tr = self.ctrl.project.track(g[0])
        return g if tr is not None and tr.kind == TRACK_VIDEO else None

    def refresh_donde(self):
        model = self.donde.model()
        ok = {"todos": True, "io": self.ctrl.project.marked_range() is not None, "elegido": self._gap() is not None}
        if isinstance(model, QStandardItemModel):
            for i in range(self.donde.count()):
                it = model.item(i)
                if it is not None:
                    it.setEnabled(ok[self.donde.itemData(i)])
        if not ok.get(self.donde.currentData(), True):
            self.donde.setCurrentIndex(0)

    def refresh_summary(self):
        mid = self.media_id()
        m = self.ctrl.project.media.get(mid) if mid else None
        if m is not None and mid != getattr(self, "_huella_pedida", None):
            self._huella_pedida = mid        # 🧬 su huella (BAJA): no repetir un momento que ya sale desde otro archivo
            try:
                from . import repetidos_ui as _RU
                _RU.pedir_huellas_de(self.ctrl, [mid], "elegido en Autocompletar")
            except Exception:  # noqa: BLE001
                pass
        if m is None:
            self.summary.setText("Importa un video en Medios para autocompletar." if not self._videos() else "")
            self.summary.setToolTip("")
            return
        p = self.ctrl.project
        dur = float(m.duration or 0.0)
        tramos = AC.usos(p, mid)
        veces = AC.apariciones(p, mid)
        free = sum(b - a for a, b in AC.libre(dur, [(a, b) for a, b, _n in tramos]))
        t = lambda x: fmt_time(x, False)  # noqa: E731
        lines = [f"{t(a)}–{t(b)} ×{n}" for a, b, n in tramos]
        if not veces:
            text = f"Aún no sale en la línea de tiempo · libre todo ({t(dur)})"
        else:
            shown = ", ".join(lines[:6]) + (f" y {len(lines) - 6} más" if len(lines) > 6 else "")
            text = (f"Sale {veces} {'vez' if veces == 1 else 'veces'} · usado {shown} · libre {t(free)} de {t(dur)}")
        self.summary.setText(text)
        self.summary.setToolTip("Tramos del video que ya salen en la línea de tiempo (×N = cuántas veces):\n"
                                + ("\n".join(lines) if lines else "ninguno"))

    # ------------------------------------------------------------ autocompletar
    def run(self):
        if self.job is not None and self.job.isRunning():
            return
        mid = self.media_id()
        m = self.ctrl.project.media.get(mid) if mid else None
        if m is None:
            self.info.setText("Elige un video.")
            return
        self.settings.setValue("autocompletar/min", self.lo.value())
        self.settings.setValue("autocompletar/max", max(self.lo.value(), self.hi.value()))
        self.settings.setValue("autocompletar/orden", self.orden.currentData())
        if mid in self.scenes:
            self.fill()
            return
        path, dur = m.path, float(m.duration)

        def work(progress, cancelled):
            return SP.scenes_of(path, dur, lambda f: progress(f, "Buscando escenas…"), cancelled)

        self.job = BackgroundJob(work, self)
        self.job.title = "✨ Autocompletar: buscando escenas"
        self.job.progress.connect(lambda f, _t: self.progress.setValue(int(f * 1000)))
        self.job.done.connect(lambda sc, mid=mid: self._scanned(mid, sc))
        self.job.failed.connect(self._scan_failed)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.btn.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._cancelling = False
        self.info.setText(f"Buscando las escenas de «{m.name}»…")
        self.job.start()

    def cancel(self):
        if self.job is not None and self.job.isRunning():
            self._cancelling = True
            self.job.cancel()
            self.btn_cancel.setEnabled(False)
            self.info.setText("Cancelando…")

    def _scanned(self, mid, sc):
        self.progress.setVisible(False)
        self.btn.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if sc is None or self._cancelling:   # (cancelado)
            self.info.setText("Búsqueda cancelada: no se rellenó nada.")
            return
        self.scenes[mid] = list(sc)
        if self.media_id() == mid:
            self.fill()

    def _scan_failed(self, msg):
        self.progress.setVisible(False)
        self.btn.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.info.setText("Búsqueda cancelada: no se rellenó nada." if self._cancelling else
                          "No se pudieron buscar las escenas: " + msg)

    def fill(self) -> list[str] | None:
        """Rellena con lo libre del video elegido (escenas ya buscadas). Devuelve los clips nuevos."""
        p = self.ctrl.project
        mid = self.media_id()
        m = p.media.get(mid) if mid else None
        if m is None:
            return None
        self.refresh_donde()
        where = self.donde.currentData()
        g = self._gap() if where == "elegido" else None
        if where == "elegido" and g is None:
            self.info.setText("Elige antes un hueco en la línea de tiempo (clic entre dos clips).")
            return None
        rng = p.marked_range() if where == "io" else None
        if where == "io" and rng is None:
            self.info.setText("Marca antes la entrada (I) y la salida (O).")
            return None
        gap_track = g[0] if g is not None else None
        tr = AC.pista_destino(p, gap_track)
        if tr is None:
            self.info.setText("🔒 Esa pista está bloqueada." if gap_track else
                              "🔒 Todas las pistas de video están bloqueadas.")
            return None
        if g is not None:
            holes = AC.huecos(p, g[1], g[2], track_id=g[0])
        elif rng is not None:                  # (lo de la pista destino tapa siempre: nunca se borra nada de ella)
            holes = AC.huecos(p, rng[0], rng[1], destino=tr.id)
        else:
            holes = AC.huecos(p, destino=tr.id)
        if not holes:
            self.info.setText("No hay huecos: ahí ya se ve algo en todo momento.")
            return None
        need = sum(b - a for a, b in holes)
        # lo usado de ese video y, con la huella por plano, lo que repite un momento que ya sale desde otro archivo
        from ..core import repetidos
        usados = repetidos.usados_con_huella(p, mid, missing=getattr(self.ctrl, "missing", set()))
        mat = AC.material(self.scenes.get(mid, []), usados, float(m.duration))
        if not mat:
            self.info.setText(f"⚠ De «{m.name}» ya está todo usado: no queda material libre "
                              f"(faltaban {need:.1f} s).")
            return None
        beats = self.ctrl.song_beats(holes[0][0] - 1.0, holes[-1][1] + 1.0)
        lo, hi = self.lo.value(), max(self.lo.value(), self.hi.value())
        items, faltan = AC.plan(mid, mat, holes, lo, hi, beats, self.orden.currentData())
        if not items:
            self.info.setText(f"⚠ De «{m.name}» ya no queda material libre suficiente: solo trozos muy cortos "
                              f"(faltaban {need:.1f} s).")
            return None
        ids = self.ctrl.place_fill_items(items, f"✨ Autocompletar con «{m.name}»", tr.id)
        if not ids:
            return None
        if self.timeline is not None and hasattr(self.timeline, "set_selection"):
            self.timeline.set_selection(ids)
        msg = (f"✓ {len(ids)} trozo(s) de «{m.name}» en {len(holes)} hueco(s)"
               + (" al ritmo de la canción" if beats else "") + ". Ctrl+Z lo deshace.")
        if faltan > 0.05:
            msg += f"\n⚠ Faltó material libre: quedaron {faltan:.1f} s sin tapar."
        self.info.setText(msg)
        self.last_missing = faltan
        self.refresh_summary()
        return ids
