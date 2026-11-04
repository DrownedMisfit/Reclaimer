"""
Subpestañas dentro de un panel (como Resolve: todo detrás de pestañas, sin una columna eterna de cosas).

  tabbed([(título, [widgets…]), …]) -> QTabWidget   (cada página se desplaza sola si no cabe)
  explain(label, target)  → la explicación pasa a la ayuda emergente de target y el texto se esconde
  sections([(título, widget, abierta), …]) → secciones plegables (▾/▸) una debajo de otra
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget


def tabbed(pages, name: str = "subtabs") -> QTabWidget:
    tw = QTabWidget()
    tw.setObjectName(name)
    tw.setDocumentMode(True)
    tw.setUsesScrollButtons(True)
    for page in pages:
        title, widgets = page[0], page[1]
        grow = len(page) > 2 and page[2]          # (título, widgets, True) = el último ocupa todo el alto
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        ws = [w for w in widgets if w is not None]
        for i, w in enumerate(ws):
            v.addWidget(w, 1 if (grow and i == len(ws) - 1) else 0)
        if not grow:
            v.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(inner)
        tw.addTab(sc, title)
    return tw


def explain(label: QLabel, target: QWidget):
    """Sin textos largos a la vista: la explicación se ve al pasar el ratón por target."""
    text = label.text()
    old = target.toolTip()
    target.setToolTip(text if not old else old + "\n\n" + text)
    label.hide()


def untitle(*groups):
    """Las cajas ya están en su pestaña: el título sobra."""
    for g in groups:
        g.setTitle("")


# ------------------------------------------------------------------ secciones plegables (▾ / ▸)
class Section(QWidget):
    """Una sección con su cabecera: clic en la flecha = mostrar u ocultar (una debajo de otra, como Resolve)."""

    def __init__(self, title: str, body: QWidget, opened: bool = False, key: str = ""):
        from PySide6.QtCore import QSettings, Qt
        from PySide6.QtWidgets import QSizePolicy, QToolButton
        super().__init__()
        self.body, self._key = body, key
        if key:
            v = QSettings("EditorIA", "EditorIA").value(key)
            if v is not None:
                opened = str(v).lower() in ("true", "1")
        self.head = QToolButton()
        self.head.setObjectName("sectionhead")
        self.head.setText(title)
        self.head.setCheckable(True)
        self.head.setChecked(opened)
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setStyleSheet("QToolButton#sectionhead { background: #26282e; border: none; border-radius: 4px; "
                                "padding: 6px 8px; text-align: left; font-weight: 600; color: #d8dbe2; }"
                                "QToolButton#sectionhead:hover { background: #2e3138; }")
        self.head.toggled.connect(self.set_open)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(self.head)
        v.addWidget(body, 1)
        self.set_open(opened, save=False)

    def is_open(self) -> bool:
        return self.head.isChecked()

    def set_open(self, on: bool, save: bool = True):
        from PySide6.QtCore import QSettings, Qt
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        if self.head.isChecked() != on:
            self.head.setChecked(on)
        self.body.setVisible(on)
        if save and self._key:
            QSettings("EditorIA", "EditorIA").setValue(self._key, on)


def sections(pages, key: str = "") -> tuple[QScrollArea, dict]:
    """[(título, widget, abierta_por_defecto), …] → (zona con las secciones una debajo de otra, {título: Section}).
    Se recuerda cuáles dejaste abiertas (key)."""
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(2, 2, 2, 2)
    v.setSpacing(6)
    out = {}
    for title, body, opened in pages:
        s = Section(title, body, opened, f"secciones/{key}/{title}" if key else "")
        out[title] = s
        v.addWidget(s)
    v.addStretch(1)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QScrollArea.NoFrame)
    sc.setWidget(inner)
    return sc, out
