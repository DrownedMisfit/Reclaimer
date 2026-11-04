"""
⤧ «Transformar» en el Inspector (como la «Transformación» de Resolve, todo a la mano): Tamaño X / Y (con 🔗 para no
deformar), Posición X / Y, Rotación, Voltear ↔ ↕ y ▦ Relleno — cada fila con su ↺ para volver a lo normal.
Lo mismo que las asas del visor (son la misma caja). Con claves de posición/tamaño, lo que cambias es la clave de ESE
momento. Varios cambios seguidos = un solo Ctrl+Z.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QWidget)

from ..core import fill as FILL
from ..core import transform


def _spin(lo, hi, step, suffix, dec=1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def _reset_btn(tip: str, slot) -> QToolButton:
    b = QToolButton()
    b.setText("↺")
    b.setToolTip(tip)
    b.clicked.connect(slot)
    return b


class TransformBox(QGroupBox):
    def __init__(self, inspector):
        super().__init__("⤧ Transformar")
        self.ins, self.ctrl = inspector, inspector.ctrl
        self._loading = False
        f = QFormLayout(self)

        def row(label, widgets, reset_tip, reset_slot):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            for x in widgets:
                h.addWidget(x)
            h.addWidget(_reset_btn(reset_tip, reset_slot))
            f.addRow(label, w)
        self.w = _spin(1, 400, 1, " %", 1)
        self.h = _spin(1, 400, 1, " %", 1)
        self.link = QCheckBox("🔗")
        self.link.setChecked(True)
        self.link.setToolTip("Enlazado: ancho y alto juntos (sin deformar). Suéltalo para estirar o aplastar.")
        self.w.valueChanged.connect(lambda v: self._size("w", v))
        self.h.valueChanged.connect(lambda v: self._size("h", v))
        row("Tamaño", [QLabel("X"), self.w, self.link, QLabel("Y"), self.h], "Tamaño normal (pantalla completa, "
            "sin deformar)", self._reset_size)
        self.px = _spin(-8000, 8000, 10, " px", 0)
        self.py = _spin(-8000, 8000, 10, " px", 0)
        self.px.valueChanged.connect(lambda _v: self._pos())
        self.py.valueChanged.connect(lambda _v: self._pos())
        row("Posición", [QLabel("X"), self.px, QLabel("Y"), self.py], "Centrar", self._reset_pos)
        self.rot = _spin(-360, 360, 1, " °", 1)
        self.rot.valueChanged.connect(lambda v: self._set(rot=round(v, 2)))
        row("Rotación", [self.rot], "Sin girar", lambda: self.rot.setValue(0.0))
        self.fh = QPushButton("↔ Horizontal")
        self.fv = QPushButton("↕ Vertical")
        for b, key in ((self.fh, "flip_h"), (self.fv, "flip_v")):
            b.setCheckable(True)
            b.toggled.connect(lambda on, k=key: self._set(**{k: bool(on)}))
        row("Voltear", [self.fh, self.fv], "Sin voltear", lambda: (self.fh.setChecked(False),
                                                                   self.fv.setChecked(False)))
        # ▦ Relleno (el efecto de Resolve): la propia imagen, ampliada y desenfocada, en lo que queda vacío
        self.fill_on = QCheckBox("▦ Relleno con la propia imagen")
        self.fill_on.setToolTip("Lo que queda vacío alrededor (al aplastarla, hacerla pequeña o de otra forma que la "
                                "pantalla) se llena con la misma imagen ampliada y desenfocada.")
        self.fill_on.toggled.connect(self._fill_toggled)
        f.addRow(self.fill_on)
        self.fill_blur = _spin(0, 100, 5, " %", 0)
        self.fill_dark = _spin(0, 90, 5, " %", 0)
        self.fill_zoom = _spin(100, 300, 5, " %", 0)
        for s in (self.fill_blur, self.fill_dark, self.fill_zoom):
            s.valueChanged.connect(lambda _v: self._fill_params())
        self.fill_row = QWidget()
        h = QHBoxLayout(self.fill_row)
        h.setContentsMargins(0, 0, 0, 0)
        for lab, s in (("Desenfoque", self.fill_blur), ("Oscurecer", self.fill_dark), ("Zoom", self.fill_zoom)):
            h.addWidget(QLabel(lab))
            h.addWidget(s)
        f.addRow(self.fill_row)

    # ---- datos
    def _clip(self):
        return self.ins._clip()

    def _box_now(self, c) -> dict:
        p = self.ctrl.project
        m = p.media_of(c)
        local = min(max(self.ins._now() - c.start, 0.0), c.duration)
        return dict(transform.layout_at(c, local, bool(m and m.kind == "image")) or transform.FULL)

    def refresh(self):
        c = self._clip()
        self.setVisible(c is not None and c.text is None and not self.ins.frame_box.isHidden())
        if c is None or c.text is not None:
            return
        p = self.ctrl.project
        b = self._box_now(c)
        self._loading = True
        try:
            self.w.setValue(b["w"] * 100)
            self.h.setValue(b["h"] * 100)
            self.px.setValue(round((b["x"] + b["w"] / 2 - 0.5) * p.width))
            self.py.setValue(round((b["y"] + b["h"] / 2 - 0.5) * p.height))
            self.rot.setValue(transform.rot_of(b) if transform.rot_of(b) <= 180 else transform.rot_of(b) - 360)
            self.fh.setChecked(bool(b.get("flip_h")))
            self.fv.setChecked(bool(b.get("flip_v")))
            rel = FILL.of(c.fx)
            self.fill_on.setChecked(rel is not None)
            self.fill_row.setVisible(rel is not None)
            r = rel or FILL.DEFAULT
            self.fill_blur.setValue(r["desenfoque"] * 100)
            self.fill_dark.setValue(r["oscurecer"] * 100)
            self.fill_zoom.setValue(r["zoom"] * 100)
        finally:
            self._loading = False

    def _apply(self, box: dict, text="⤧ Transformar"):
        c = self._clip()
        if c is None or self._loading:
            return
        self.ctrl.set_clip_layout(c.id, box, self.ins._now(), text)

    def _set(self, **changes):
        c = self._clip()
        if c is None or self._loading:
            return
        b = self._box_now(c)
        if c.layout is None and any(changes.values()):
            b["bg"] = "none"
        b.update(changes)
        self._apply(b)

    def _size(self, which: str, v: float):
        c = self._clip()
        if c is None or self._loading:
            return
        p = self.ctrl.project
        b = self._box_now(c)
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        new = v / 100
        if self.link.isChecked():
            k = new / max(1e-6, b[which])
            b["w"], b["h"] = b["w"] * k, b["h"] * k
        else:                                 # sin enlazar: deformar (la caja pasa a ser la imagen que se ve)
            if b.get("fit") != "stretch":
                m = p.media_of(c)
                b = transform.content_box(b, m.width if m else 0, m.height if m else 0, p.width, p.height)
                b["fit"] = "stretch"
                cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
            b[which] = new
        b["x"], b["y"] = cx - b["w"] / 2, cy - b["h"] / 2
        if c.layout is None:
            b["bg"] = "none"
        self._apply(b)

    def _pos(self):
        c = self._clip()
        if c is None or self._loading:
            return
        p = self.ctrl.project
        b = self._box_now(c)
        b["x"] = 0.5 + self.px.value() / p.width - b["w"] / 2
        b["y"] = 0.5 + self.py.value() / p.height - b["h"] / 2
        if c.layout is None:
            b["bg"] = "none"
        self._apply(b)

    def _reset_size(self):
        c = self._clip()
        if c is None:
            return
        b = self._box_now(c)
        b.update(x=0.0, y=0.0, w=1.0, h=1.0)
        if b.get("fit") == "stretch":
            b["fit"] = "contain"
        self._apply(b, "⤧ Tamaño normal")

    def _reset_pos(self):
        c = self._clip()
        if c is None:
            return
        b = self._box_now(c)
        b.update(x=0.5 - b["w"] / 2, y=0.5 - b["h"] / 2)
        self._apply(b, "⤧ Centrar")

    # ---- relleno
    def _fill_toggled(self, on: bool):
        self.fill_row.setVisible(on)
        if self._loading:
            return
        c = self._clip()
        if c is not None:
            self.ctrl.set_fill([c.id], self._fill_dict() if on else None,
                               "▦ Poner relleno" if on else "▦ Quitar relleno")

    def _fill_dict(self) -> dict:
        return {"desenfoque": self.fill_blur.value() / 100, "oscurecer": self.fill_dark.value() / 100,
                "zoom": self.fill_zoom.value() / 100}

    def _fill_params(self):
        c = self._clip()
        if c is None or self._loading or not self.fill_on.isChecked():
            return
        self.ctrl.set_fill([c.id], self._fill_dict(), "▦ Ajustar relleno")
