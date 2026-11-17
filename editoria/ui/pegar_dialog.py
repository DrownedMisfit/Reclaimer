"""📌 «Pegar a un objeto seguido…»: un texto, imagen, emoji, flecha o título sigue a un objeto del video de debajo.

Se elige el recorrido (los videos que coinciden en el tiempo y ya tienen uno, 🎯 Seguimiento) y el clip se mueve con
el objeto conservando el desfase con el que lo colocaste en el cabezal. Si todavía no hay ninguno, un botón abre el
🎯 Seguimiento del video de debajo con este clip ya elegido para pegarlo.
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.model import KIND_VIDEO, TRACK_VIDEO
from .common import fmt_time


def video_under(ctrl, overlay_id: str, t: float) -> str | None:
    """El clip de video que hay debajo del clip en el momento t (o el primero que coincida en el tiempo)."""
    p = ctrl.project
    oc = p.clips.get(overlay_id)
    if oc is None:
        return None
    t = min(max(t, oc.start), oc.end - 1e-3)
    oi = p.track_index(oc.track_id)
    best = None
    for c in p.clips.values():
        m = p.media_of(c)
        tr = p.track(c.track_id)
        if c.id == overlay_id or c.text is not None or m is None or m.kind != KIND_VIDEO or tr is None \
                or tr.kind != TRACK_VIDEO or c.end <= oc.start or c.start >= oc.end:
            continue
        score = (0 if c.start <= t < c.end else 1, 0 if p.track_index(c.track_id) > oi else 1,
                 p.track_index(c.track_id))
        if best is None or score < best[0]:
            best = (score, c.id)
    return best[1] if best else None


class PegarDialog(QDialog):
    def __init__(self, ctrl, overlay_id: str, t: float, parent=None):
        super().__init__(parent)
        self.ctrl, self.overlay_id, self.t = ctrl, overlay_id, t
        self.setWindowTitle("📌 Pegar a un objeto seguido")
        p = ctrl.project
        oc = p.clips[overlay_id]
        self.cands = ctrl.tracked_under(overlay_id)
        self.combo = QComboBox()
        self.combo.setToolTip("El objeto al que se pega (recorridos de los videos que coinciden con este clip)")
        for cid, trk in self.cands:
            c = p.clips[cid]
            m = p.media_of(c)
            self.combo.addItem(f"🎯 {trk.get('name', 'Objeto')}  ·  {m.name if m else 'video'}  ·  "
                               f"{p.track(c.track_id).name}  ·  {fmt_time(c.start)}", (cid, trk["id"]))
        info = ctrl.pinned_info(oc)
        if info:
            i = self.combo.findData((info.get("clip"), info.get("track")))
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.scale = QCheckBox("También el tamaño")
        self.scale.setToolTip("Crece y encoge con el objeto")
        self.scale.setVisible(oc.text is None)
        self.msg = QLabel()
        self.msg.setObjectName("dim")
        self.msg.setWordWrap(True)
        if info:
            self.msg.setText(f"📌 Ahora está pegado a «{info.get('name') or 'Objeto'}».")
        elif not self.cands:
            self.msg.setText("Ningún video de debajo tiene todavía un recorrido.")
        self.btn_pin = QPushButton("📌 Pegar")
        self.btn_pin.setObjectName("primary")
        self.btn_pin.setToolTip("El clip seguirá al objeto conservando el desfase que tiene en el cabezal (un Ctrl+Z)")
        self.btn_pin.clicked.connect(self.pin)
        self.btn_pin.setEnabled(bool(self.cands))
        self.btn_unpin = QPushButton("✕ Despegar")
        self.btn_unpin.setToolTip("Se queda quieto donde está en el cabezal")
        self.btn_unpin.clicked.connect(self.unpin)
        self.btn_unpin.setVisible(bool(info))
        self.btn_track = QPushButton("🎯 Seguir algo en el video de debajo…")
        self.btn_track.setToolTip("Abre el seguimiento del video de debajo con este clip ya elegido para pegarlo")
        self.btn_track.clicked.connect(self.open_tracking)
        self.btn_track.setEnabled(video_under(ctrl, overlay_id, t) is not None)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        if self.cands:
            row = QHBoxLayout()
            row.addWidget(QLabel("Objeto"))
            row.addWidget(self.combo, 1)
            lay.addLayout(row)
            lay.addWidget(self.scale)
        else:
            self.combo.hide()
            self.scale.hide()
        lay.addWidget(self.msg)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_track)
        row2.addStretch()
        row2.addWidget(self.btn_unpin)
        row2.addWidget(self.btn_pin)
        row2.addWidget(close)
        lay.addLayout(row2)
        self.resize(620, 150)

    def pin(self):
        data = self.combo.currentData()
        if not data:
            return
        cid, tid = data
        if self.ctrl.pin_to_track(self.overlay_id, cid, tid, self.t, self.scale.isChecked()) is not None:
            self.ctrl.message.emit("📌 El clip sigue al objeto (mantiene su desfase). Ctrl+Z lo deshace.")
            self.accept()

    def unpin(self):
        if self.ctrl.unpin(self.overlay_id, self.t) is not None:
            self.ctrl.message.emit("📌 Despegado: se queda donde estaba.")
            self.accept()

    def open_tracking(self):
        vid = video_under(self.ctrl, self.overlay_id, self.t)
        if vid is None:
            return
        from .tracking_dialog import TrackingDialog
        self.accept()
        try:
            TrackingDialog(self.ctrl, vid, self.t, self.parent(), use="pin", overlay_id=self.overlay_id).exec()
        except RuntimeError as exc:
            self.ctrl.message.emit(str(exc))


def abrir(ctrl, overlay_id: str, t: float, parent=None):
    """Abre la ventana (desde el clic derecho del clip o el Inspector)."""
    if overlay_id not in ctrl.project.clips:
        return
    PegarDialog(ctrl, overlay_id, t, parent).exec()
