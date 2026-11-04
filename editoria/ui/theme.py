"""Tema oscuro al estilo de DaVinci Resolve (página Edit): grises neutros por capas, el naranja solo para lo activo,
iconos de un solo color (los símbolos se dibujan con la fuente monocroma de Windows, no como emojis de colores)."""
from __future__ import annotations

import os
from pathlib import Path

# ⚠ Antes de crear la aplicación: sin esto, Qt dibuja ✂ 🎬 ✨… como emojis DE COLORES (Segoe UI Emoji). Con esto,
# salen con «Segoe UI Symbol», del color del texto: como iconos de un programa profesional.
os.environ.setdefault("QT_DISABLE_EMOJI_SEGMENTER", "1")

from PySide6.QtCore import QObject, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FONT_FAMILIES = ["Segoe UI", "Segoe UI Symbol"]      # el texto y, para los símbolos, la fuente monocroma

# Paleta (capas: lo más hondo es lo más oscuro)
BG = "#1d1e22"         # fondo de los paneles
BG_DEEP = "#141518"    # separaciones entre paneles y barras de arriba/abajo
HEADER = "#18191c"     # barras de título de los paneles
RAISED = "#2a2c31"     # botones
RAISED_HI = "#34363d"  # botones (ratón encima)
FIELD = "#16171a"      # campos de texto/números
BORDER = "#2f3137"
BORDER_HI = "#43464e"
TEXT = "#e4e5e9"
TEXT_DIM = "#a0a3ac"
TEXT_FAINT = "#71747d"  # ayudas cortas, títulos de sección
ACCENT = "#e8742f"     # naranja de Resolve (lo activo, el botón principal)
ACCENT_HI = "#f4884a"
RED = "#e5413c"        # cabezal

_UI = (Path(__file__).resolve().parent.parent / "assets" / "ui").as_posix()

STYLE = f"""
QWidget {{ font-size: 9pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QMenuBar {{ background: {BG_DEEP}; color: {TEXT_DIM}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 9px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {RAISED}; color: {TEXT}; }}
QMenu {{ background: #23252a; border: 1px solid #383b42; padding: 6px 0; }}
QMenu::item {{ padding: 6px 30px 6px 26px; margin: 0 5px; border-radius: 4px; color: {TEXT}; }}
QMenu::item:selected {{ background: #363941; color: white; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{ height: 1px; background: #33363d; margin: 5px 12px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 7px; }}
QMenu::right-arrow {{ width: 8px; height: 8px; }}
QToolTip {{ background: #25272c; color: {TEXT}; border: 1px solid #3a3d44; padding: 6px 8px; }}

QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 5px; padding: 5px 12px; }}
QPushButton:hover {{ background: {RAISED_HI}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: #232429; }}
QPushButton:checked {{ background: rgba(232,116,47,0.15); border-color: rgba(232,116,47,0.75); color: #ffbe94; }}
QPushButton:disabled {{ background: #212226; border-color: #26282d; color: #5b5e66; }}
QPushButton#tltool:checked {{ background: #44474f; border: 1px solid #5a5e67; color: white; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: #ffffff; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton#primary:pressed {{ background: #d2631f; }}
QPushButton#primary:disabled {{ background: #34291f; border-color: #34291f; color: #8a7a6d; }}
QPushButton#flat {{ background: transparent; border: none; color: {TEXT_DIM}; padding: 4px 8px; }}
QPushButton#flat:hover {{ color: white; }}
QPushButton#flat:checked {{ color: white; background: transparent; border-bottom: 2px solid {ACCENT}; border-radius: 0; }}
QToolButton#page, QPushButton#page {{ background: transparent; border: none; color: {TEXT_FAINT}; padding: 3px 16px;
                    font-size: 8pt; }}
QToolButton#page:hover, QPushButton#page:hover {{ color: {TEXT}; }}
QToolButton#page:checked, QPushButton#page:checked {{ color: white; background: transparent; border: none; }}
QPushButton#transport {{ background: transparent; border: none; font-size: 12pt; padding: 2px 8px; color: {TEXT}; }}
QPushButton#transport:hover {{ color: white; background: {RAISED}; border-radius: 5px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 5px; padding: 4px 6px;
    selection-background-color: #5a3a24; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {BORDER_HI}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: rgba(232,116,47,0.8); }}
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{_UI}/chevron_down.svg"); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{ background: #23252a; border: 1px solid #383b42; selection-background-color: #363941;
                               outline: none; padding: 4px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border: none; background: transparent; width: 16px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{_UI}/chevron_up.svg"); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{_UI}/chevron_down.svg"); width: 9px; height: 9px; }}

QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER_HI};
    background: {FIELD}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: #5d616b; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_UI}/check.svg"); }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_UI}/radio_dot.svg"); }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: #1f2024; border-color: #2c2e33; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: #5b5e66; }}

QTreeWidget, QListWidget, QTreeView, QListView, QTableView {{ background: {BG}; border: none;
    alternate-background-color: #212226; outline: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #25272c; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background: #3a3d46; color: white; }}
QHeaderView::section {{ background: {HEADER}; border: none; border-right: 1px solid {BG_DEEP}; padding: 4px 6px;
                        color: {TEXT_FAINT}; font-size: 8pt; }}

QTabWidget::pane {{ border: none; }}
QDockWidget {{ color: {TEXT_FAINT}; font-size: 8pt; }}
QDockWidget::title {{ background: {HEADER}; padding: 3px 8px; border-bottom: 1px solid {BG_DEEP}; }}
QMainWindow::separator {{ background: {BG_DEEP}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: {ACCENT}; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; padding: 7px 10px; color: {TEXT_DIM}; border: none;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: white; }}
QTabBar::tab:selected {{ color: white; border-bottom: 2px solid {ACCENT}; }}
QTabWidget#subtabs QTabBar {{ background: {HEADER}; }}
QTabWidget#subtabs QTabBar::tab {{ padding: 7px 12px; font-size: 8.5pt; }}
QTabWidget#subtabs::pane {{ border-top: 1px solid {BORDER}; }}
QTabWidget#subtabs QGroupBox {{ border: none; margin-top: 0; padding-top: 0; background: transparent; }}
QSplitter::handle {{ background: {BG_DEEP}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #3a3d44; border-radius: 3px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: #50545d; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{ background: {BG_DEEP}; color: {TEXT_DIM}; font-size: 8.5pt; }}
QStatusBar::item {{ border: none; }}
QLabel#title {{ font-weight: 600; color: {TEXT}; font-size: 10pt; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#hint {{ color: {TEXT_FAINT}; font-size: 8.5pt; }}
QLabel#sectionhead {{ color: {TEXT_FAINT}; font-size: 8pt; font-weight: 600; }}
QLabel#timecode {{ font-family: Consolas, 'Courier New'; font-size: 13pt; color: {TEXT}; }}
QLabel#bigtimecode {{ font-family: Consolas, 'Courier New'; font-size: 17pt; color: {ACCENT}; }}
QWidget#panelheader {{ background: {HEADER}; border-bottom: 1px solid {BG_DEEP}; }}
QWidget#topbar, QWidget#pagebar {{ background: {BG_DEEP}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 7px; margin-top: 14px; padding: 10px 6px 6px 6px;
             background: rgba(255,255,255,0.012); }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_DIM}; font-weight: 600; }}
QProgressBar {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 4px; text-align: center; height: 12px;
                color: {TEXT_DIM}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: #34373e; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: rgba(232,116,47,0.85); border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #e9eaee; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: white; }}
"""


def glyph_icon(ch: str, px: int = 20, color: str = TEXT_FAINT, on: str = "#ffffff") -> QIcon:
    """Un símbolo (✂, 🎞, ✨…) como icono de un solo color, como los de Resolve; con su versión «activa» (on)."""
    icon = QIcon()
    for state, col in ((QIcon.Off, color), (QIcon.On, on)):
        pm = QPixmap(px * 2, px * 2)               # (a doble resolución: nítido en pantallas con escala)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont()
        f.setFamilies(["Segoe UI Symbol", "Segoe UI"])
        f.setPixelSize(int(px * 0.82))
        p.setFont(f)
        p.setPen(QColor(col))
        p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, ch)
        p.end()
        icon.addPixmap(pm, QIcon.Normal, state)
    return icon


def scaled_style(scale: float) -> str:
    """El mismo tema con todas las letras escaladas (100 % = 1.0)."""
    import re
    return re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * scale:.1f}pt", STYLE)


def font_scales() -> tuple[float, float]:
    """(escala de paneles y menús, escala de la línea de tiempo) según Ventana → Tamaño de letra.
    «Global» agranda todo; «Paneles, menús y ventanas» agranda además todo lo que no es la línea de tiempo."""
    from PySide6.QtCore import QSettings
    st = QSettings("EditorIA", "EditorIA")
    try:
        ui = int(st.value("letra/interfaz", 100)) / 100
        glob = int(st.value("letra/global", 100)) / 100
    except (TypeError, ValueError):
        ui, glob = 1.0, 1.0
    ui, glob = min(2.5, max(0.7, ui)), min(2.5, max(0.7, glob))
    return ui * glob, glob


def apply_fonts(app: QApplication) -> tuple[float, float]:
    ui, tl = font_scales()
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(9 * ui)
    app.setFont(f)
    app.setStyleSheet(scaled_style(ui))
    return ui, tl


class _WheelGuard(QObject):
    """La rueda del ratón NO cambia casillas de números, listas desplegables ni deslizadores que no hayas tocado: así,
    al desplazar el Inspector con el ratón encima de «Fundido de entrada», no se cambia (¡en todos los clips
    seleccionados!) sin querer. La rueda desplaza el panel; para cambiar el valor con la rueda, haz clic antes."""

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox, QSlider
        if ev.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox, QSlider))                 and not obj.hasFocus():
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:                      # que se desplace el panel, como esperas
                QApplication.sendEvent(w.viewport(), ev)
            return True
        if ev.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow():
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QDialog
            if isinstance(obj, QDialog):           # (y, de paso, ninguna ventana fuera de la pantalla)
                QTimer.singleShot(0, lambda d=obj: fit_on_screen(d))
        return False


def fit_on_screen(w) -> None:
    """Ninguna ventana más grande que la pantalla ni fuera de ella: sus botones de abajo («Crear edit», «Aceptar»…)
    siempre se ven. Si era más alta, se encoge (lo de dentro se desplaza, si lo tiene) y se mete dentro. Es solo una
    ayuda: si algo falla, no molesta con ningún error."""
    try:
        _fit_on_screen(w)
    except Exception:  # noqa: BLE001
        pass


def _fit_on_screen(w) -> None:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QWidget
    try:
        if not w.isVisible():
            return
        # (QWidget.screen(w), no w.screen(): alguna ventana tiene un elemento propio llamado «screen» — p. ej. la de
        # «Elegir tramos», un QLabel — y daba «'QLabel' object is not callable»)
        scr = (QWidget.screen(w) or QGuiApplication.primaryScreen()).availableGeometry()
        fg, g = w.frameGeometry(), w.geometry()
    except RuntimeError:                           # (ya se cerró)
        return
    fw, fh = fg.width() - g.width(), fg.height() - g.height()
    maxw, maxh = scr.width() - fw - 16, scr.height() - fh - 16
    if g.width() > maxw or g.height() > maxh:
        w.resize(min(g.width(), maxw), min(g.height(), maxh))
        fg = w.frameGeometry()
    x = max(scr.left() + 8, min(fg.left(), scr.right() - fg.width() - 8))
    y = max(scr.top() + 8, min(fg.top(), scr.bottom() - fg.height() - 8))
    if (x, y) != (fg.left(), fg.top()):
        w.move(x, y)


def load_fonts() -> list[str]:
    """Las fuentes que trae Reclaimer (assets/fuentes: Anton, licencia OFL), disponibles en todo el programa."""
    from PySide6.QtGui import QFontDatabase
    out = []
    d = Path(__file__).resolve().parent.parent / "assets" / "fuentes"
    for f in sorted(d.glob("*.ttf")) if d.is_dir() else []:
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            out += QFontDatabase.applicationFontFamilies(fid)
    return out


def apply_dark_theme(app: QApplication) -> None:
    if not getattr(app, "_fonts_loaded", False):
        app._fonts_loaded = load_fonts()
    if not hasattr(app, "_wheel_guard"):
        app._wheel_guard = _WheelGuard(app)
        app.installEventFilter(app._wheel_guard)
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT,
        QPalette.Base: FIELD, QPalette.AlternateBase: "#212226",
        QPalette.ToolTipBase: "#25272c", QPalette.ToolTipText: TEXT,
        QPalette.Text: TEXT, QPalette.Button: RAISED, QPalette.ButtonText: TEXT,
        QPalette.BrightText: "#ffffff", QPalette.Highlight: "#5a3a24",
        QPalette.HighlightedText: "#ffffff", QPalette.Link: ACCENT,
        QPalette.PlaceholderText: "#5f626a", QPalette.Mid: BORDER, QPalette.Dark: BG_DEEP,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5b5e66"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5b5e66"))
    app.setPalette(pal)
    apply_fonts(app)
