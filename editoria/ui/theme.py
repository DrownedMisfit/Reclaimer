"""Tema oscuro al estilo de DaVinci Resolve (página Edit): grises neutros por capas, el naranja solo para lo activo,
iconos de un solo color (los símbolos se dibujan con la fuente monocroma de Windows, no como emojis de colores)."""
from __future__ import annotations

import os
from pathlib import Path

# ⚠ Antes de crear la aplicación: sin esto, Qt dibuja ✂ 🎬 ✨… como emojis DE COLORES (Segoe UI Emoji). Con esto,
# salen con «Segoe UI Symbol», del color del texto: como iconos de un programa profesional.
os.environ.setdefault("QT_DISABLE_EMOJI_SEGMENTER", "1")

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QDialog,  # noqa: E402
                               QSlider, QTabBar)

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
RED = "#e5413c"        # cabezal (no es acento: no cambia con él)

# 🎨 Color de acento (lo activo, lo elegido y el botón principal): se elige en «🎨 Diseño» (barra de arriba) o en
# Ventana → «🎨 Color de acento» y se aplica AL MOMENTO (poner_acento). Clave → (nombre, color, color con el ratón).
ACENTO_KEY = "diseno/acento"
ACENTO_POR_DEFECTO = "acero"     # (lo eligió el usuario el 20/11; antes, el naranja)
ACENTOS = {
    "plata": ("Plata Resolve", "#c4c8cf", "#dfe2e7"),      # (el gris claro plateado de DaVinci sobre fondo oscuro)
    "cromo": ("Cromo frío", "#b2c0d3", "#cfd9e7"),         # (plata azulada)
    "acero": ("Acero", "#97a3b3", "#b3bdca"),              # (gris acero: destaca sobre los grises del tema)
    "naranja": ("Naranja", "#e8742f", "#f4884a"),          # (el de antes del 20/11)
    "azul": ("Azul acero", "#4a8fd9", "#68a4e6"),
    "cian": ("Cian", "#2bb3c0", "#4cc6d2"),
    "menta": ("Verde menta", "#3fbf8a", "#5ed0a0"),
    "violeta": ("Violeta", "#8b7cf0", "#a597f5"),
    "rojo": ("Rojo", "#e14b52", "#ec6d72"),                # (≠ el rojo de avisos y del botón de cerrar)
}
TEXTO_OSCURO = "#16171a"     # (el texto encima de un acento claro: plata, cromo…)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mezcla(a: str, b: str, t: float) -> str:
    """El color a mezclado con b (t = cuánto de b)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([x + (y - x) * t for x, y in zip(ra, rb)])


def saturacion(h: str) -> float:
    r, g, b = _rgb(h)
    return (max(r, g, b) - min(r, g, b)) / 255


def luminancia(h: str) -> float:
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def acento_guardado() -> str:
    try:
        from PySide6.QtCore import QSettings
        v = str(QSettings("EditorIA", "EditorIA").value(ACENTO_KEY, ACENTO_POR_DEFECTO))
    except Exception:  # noqa: BLE001
        v = ACENTO_POR_DEFECTO
    return v if v in ACENTOS else ACENTO_POR_DEFECTO


ACENTO = ACENTO_POR_DEFECTO
ACCENT = ACCENT_HI = ACCENT_ON = ACCENT_TINTE = ACCENT_PRESS = ACCENT_OFF = ACCENT_OFF_TXT = ACCENT_SEL = ""


def _poner_globales(clave: str) -> None:
    """Los colores que salen del acento (y el texto que va encima: oscuro si el acento es claro)."""
    global ACENTO, ACCENT, ACCENT_HI, ACCENT_ON, ACCENT_TINTE, ACCENT_PRESS, ACCENT_OFF, ACCENT_OFF_TXT, ACCENT_SEL
    ACENTO = clave if clave in ACENTOS else ACENTO_POR_DEFECTO
    _n, ACCENT, ACCENT_HI = ACENTOS[ACENTO]
    # (por luminancia: los claros —plata, cromo, acero, cian, menta— con texto oscuro, ≥ 6:1; los vivos —naranja,
    #  azul, violeta, rojo— con blanco, como hasta ahora y como DaVinci)
    ACCENT_ON = TEXTO_OSCURO if luminancia(ACCENT) >= 0.31 else "#ffffff"
    ACCENT_TINTE = mezcla(ACCENT, "#ffffff", 0.45)        # (texto de un botón marcado: el acento, más claro)
    ACCENT_PRESS = mezcla(ACCENT, "#000000", 0.12)
    ACCENT_OFF = mezcla(ACCENT, "#141518", 0.82)          # (botón principal deshabilitado)
    ACCENT_OFF_TXT = mezcla(ACCENT, "#5b5e66", 0.6)
    # (fondo de lo seleccionado en campos de texto: con un acento gris —plata, cromo, acero— más acento, para que se
    #  distinga de los botones y fondos grises del tema)
    ACCENT_SEL = mezcla(ACCENT, "#1d1e22", 0.7 if saturacion(ACCENT) > 0.25 else 0.5)


_poner_globales(acento_guardado())


def _rgba(a: float) -> str:
    r, g, b = _rgb(ACCENT)
    if saturacion(ACCENT) <= 0.25 and a < 0.3:      # (un acento gris, muy transparente, no se distinguía del fondo)
        a = round(min(0.3, a * 1.7), 3)
    return f"rgba({r},{g},{b},{a})"


def acento_rgba(a: float) -> str:
    """El acento de ahora como «rgba(r,g,b,a)» para una hoja de estilo."""
    return _rgba(a)


def acento(alfa: int | None = None) -> QColor:
    """El color de acento de ahora (para dibujar): úsalo en cada pintado, no lo guardes en una constante."""
    c = QColor(ACCENT)
    if alfa is not None:
        c.setAlpha(int(alfa))
    return c

# 🎨 Tema «gris» (de entrada desde el 14/11; ver ui/tema.py): grises más claros y bordes más marcados, para ver dónde
# empieza y termina cada cosa. Lo que tiene color (naranja, rojo, azul de los clips) no cambia.
from . import tema as _tema  # noqa: E402
if _tema.es_gris():
    _P = _tema.paleta()
    BG, BG_DEEP, HEADER = _P["BG"], _P["BG_DEEP"], _P["HEADER"]
    RAISED, RAISED_HI, FIELD = _P["RAISED"], _P["RAISED_HI"], _P["FIELD"]
    BORDER, BORDER_HI = _P["BORDER"], _P["BORDER_HI"]
    TEXT, TEXT_DIM, TEXT_FAINT = _P["TEXT"], _P["TEXT_DIM"], _P["TEXT_FAINT"]
_PALETA: set = set()          # (los colores que ya son del tema o del acento: el tema gris no los toca)


def _rehacer_paleta() -> None:
    _PALETA.clear()
    _PALETA.update({BG, BG_DEEP, HEADER, RAISED, RAISED_HI, FIELD, BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT, RED,
                    ACCENT, ACCENT_HI, ACCENT_ON, ACCENT_TINTE, ACCENT_PRESS, ACCENT_OFF, ACCENT_OFF_TXT, ACCENT_SEL,
                    TEXTO_OSCURO})


_rehacer_paleta()

_UI = (Path(__file__).resolve().parent.parent / "assets" / "ui").as_posix()

def _estilo() -> str:
    """La hoja de estilo de toda la interfaz con el acento de ahora (se rehace al cambiar de acento)."""
    check = "check_oscuro.svg" if ACCENT_ON == TEXTO_OSCURO else "check.svg"
    punto = "radio_dot_oscuro.svg" if ACCENT_ON == TEXTO_OSCURO else "radio_dot.svg"
    s = f"""
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

QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 5px; padding: 3px/*s:b*/ 12px; }}
QPushButton:hover {{ background: {RAISED_HI}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: #232429; }}
QPushButton:checked {{ background: {_rgba(0.15)}; border-color: {_rgba(0.75)}; color: {ACCENT_TINTE}; }}
QPushButton:disabled {{ background: #212226; border-color: #26282d; color: #5b5e66; }}
QPushButton#tltool:checked {{ background: #44474f; border: 1px solid #5a5e67; color: white; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: {ACCENT_ON}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton#primary:disabled {{ background: {ACCENT_OFF}; border-color: {ACCENT_OFF}; color: {ACCENT_OFF_TXT}; }}
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
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 5px; padding: 2px/*s:c*/ 6px;
    selection-background-color: {ACCENT_SEL}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {BORDER_HI}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {_rgba(0.8)}; }}
QComboBox {{ padding-right: 22px; }}
QSpinBox, QDoubleSpinBox {{ padding-top: 1px/*s:nt*/; padding-bottom: 0px/*s:nb*/; }}
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
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_UI}/{check}"); }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{_UI}/{punto}"); }}
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
QDockWidget {{ titlebar-close-icon: url("{_UI}/cerrar.svg"); titlebar-normal-icon: url("{_UI}/soltar.svg"); }}
QDockWidget::close-button {{ background: #c4373b; border: none; border-radius: 3px; padding: 1px; }}
QDockWidget::close-button:hover {{ background: #e5484d; }}
QDockWidget::close-button:pressed {{ background: #a12b2e; }}
QDockWidget::float-button {{ background: #3a3d46; border: none; border-radius: 3px; padding: 1px; }}
QDockWidget::float-button:hover {{ background: #4a4e59; }}
QMainWindow::separator {{ background: {BG_DEEP}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: {ACCENT}; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; padding: 7px 10px; color: {TEXT_DIM}; border: none;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: white; }}
QTabBar::tab:selected {{ color: white; border-bottom: 2px solid {ACCENT}; }}
QWidget#subtabs QGroupBox {{ border: none; background: transparent; }}
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
QSlider::sub-page:horizontal {{ background: {_rgba(0.85)}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #e9eaee; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: white; }}
"""
    if _tema.es_gris():                        # (los grises sueltos de la hoja, también más claros)
        s = _tema.aclarar_texto(s, _PALETA)
        # botones pulsados y deshabilitados que se distingan del normal (en gris quedaban casi iguales)
        s += (f"\nQPushButton:pressed {{ background: {BG_DEEP}; }}"
              f"\nQPushButton:disabled {{ background: {BG}; border-color: {BORDER}; color: {TEXT_FAINT}; }}\n")
    return s + globals().get("_profundidad", str)()   # (🎨 el bloque de profundidad: ver el final del archivo)


STYLE = _estilo()


def _variantes(color: str) -> list[str]:
    """Cómo puede estar escrito un color en una hoja de estilo (#abcdef, #ABCDEF, rgba(r,g,b,…)."""
    r, g, b = _rgb(color)
    return [color.lower(), color.upper(), f"rgba({r},{g},{b},", f"rgba({r}, {g}, {b},"]


def poner_acento(clave: str, app: QApplication | None = None, guardar: bool = True) -> bool:
    """🎨 Cambia el color de acento AL MOMENTO: la hoja de estilo general, las hojas propias de cada panel que lo
    llevaban escrito (se reescriben con el nuevo), el color de la línea de tiempo (common.COLORS) y un repintado.
    Se recuerda en QSettings («diseno/acento»). False si la clave no existe."""
    global STYLE
    if clave not in ACENTOS:
        return False
    if guardar:
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue(ACENTO_KEY, clave)
    viejo = (ACCENT, ACCENT_HI, ACCENT_TINTE)
    _poner_globales(clave)
    _rehacer_paleta()
    STYLE = _estilo()
    try:
        from .common import COLORS
        COLORS["accent"].setRgb(*_rgb(ACCENT))        # (el mismo QColor: quien lo tenga guardado ve el nuevo)
    except Exception:  # noqa: BLE001
        pass
    app = app or QApplication.instance()
    if app is None:
        return True
    cambios = []
    for old, new in zip(viejo, (ACCENT, ACCENT_HI, ACCENT_TINTE)):
        if old.lower() == new.lower():
            continue
        r, g, b = _rgb(new)
        for v_old, v_new in zip(_variantes(old), [new, new, f"rgba({r},{g},{b},", f"rgba({r}, {g}, {b},"]):
            cambios.append((v_old, v_new))
    app.setOverrideCursor(Qt.WaitCursor)               # (rehacer el estilo de ~3000 controles tarda un par de s)
    # (los filtros de eventos de toda la aplicación —rueda, «¿Qué hace esto?»— se apartan mientras: Qt manda cientos
    #  de miles de eventos al rehacer el estilo y pasaban por ellos; −40 % del tiempo)
    filtros = [f for f in (getattr(app, "_wheel_guard", None), getattr(app, "_help_filter", None)) if f is not None]
    for f in filtros:
        app.removeEventFilter(f)
    try:
        _aplicar_acento(app, cambios)
    finally:
        for f in filtros:
            app.installEventFilter(f)
        app.restoreOverrideCursor()
    return True


def _aplicar_acento(app, cambios) -> None:
    from PySide6.QtWidgets import QWidget
    if cambios:
        for w in app.allWidgets():                   # (hojas propias con el acento escrito: al nuevo)
            try:
                css = QWidget.styleSheet(w)
            except RuntimeError:
                continue
            if not css or w.property("color_contenido"):   # (un color que elegiste tú —figura, texto—: no se toca)
                continue
            nuevo = css
            for a, b_ in cambios:
                nuevo = nuevo.replace(a, b_)
            if nuevo != css:
                w.setStyleSheet(nuevo)
    pal = app.palette()
    pal.setColor(QPalette.Highlight, QColor(ACCENT_SEL))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    app.setPalette(pal)
    apply_fonts(app)                                   # (la hoja general, con el acento nuevo)
    for w in app.topLevelWidgets():
        try:
            w.update()
            for c in w.findChildren(QWidget):
                c.update()
        except RuntimeError:
            pass


def _hook_estilos():
    """En los temas grises, las hojas de estilo propias de cada panel (fondos y textos fijos) también pasan por el
    tema: sin esto, el panel de Texto, los avisos atenuados, los tiradores… quedaban oscuros o casi invisibles."""
    from PySide6.QtWidgets import QWidget
    if getattr(QWidget, "_reclaimer_tema", False):
        return
    orig = QWidget.setStyleSheet

    def setStyleSheet(self, css):
        if css:
            css = _tema.aclarar_texto(css, _PALETA)
        return orig(self, css)
    try:
        QWidget.setStyleSheet = setStyleSheet
        QWidget._reclaimer_tema = True
    except (TypeError, AttributeError):        # (si Qt no lo deja, solo la hoja general va en gris)
        pass


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
    s = re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * scale:.1f}pt", STYLE)
    return re.sub(r"(\d+)px/\*s:(\w+)\*/", lambda m: f"{relleno_alto(m.group(2), scale)}px/*s:{m.group(2)}*/", s)


def relleno_alto(tipo: str, escala: float) -> int:
    """📏 Un solo alto (auditoría, mejora 14): botón, campo, desplegable y caja numérica miden 24 px × la escala de
    «Letra». La letra mide ~16 px × escala; lo demás (borde y márgenes propios de cada control) es fijo, así que el
    relleno vertical de cada lado se calcula para que el TOTAL escale entero (Qt no lee rellenos con decimales):
      b = botón (2 px de borde) · c = campo y desplegable (borde + 2 px suyos) · nt/nb = caja numérica, arriba/abajo
      (borde + 5 px suyos, el impar arriba) · bp/bm = botón pulsado (1 px más abajo)."""
    libre = 8.0 * escala                      # (24 − 16 = 8 px de margen a la escala 1)
    if tipo in ("b", "bp", "bm"):
        r = int((libre - 2) / 2 + 0.5)
        return max(0, r + (1 if tipo == "bp" else -1 if tipo == "bm" else 0))
    if tipo == "c":
        return max(0, int((libre - 4) / 2 + 0.5))
    total = max(0, int(libre - 7 + 0.5))      # caja numérica
    return (total + 1) // 2 if tipo == "nt" else total // 2


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
    if app.font() != f:
        app.setFont(f)
    ss = scaled_style(ui)
    if app.styleSheet() != ss:               # (⚡ la misma: no se repasan otra vez todos los widgets, ~250 ms al abrir)
        app.setStyleSheet(ss)
    return ui, tl


class _WheelGuard(QObject):
    """La rueda del ratón NO cambia casillas de números, listas desplegables, deslizadores ni pestañas sin querer: así, al
    desplazar un panel con el ratón encima de «Escala» o «Giro», no se cambia. La rueda desplaza el panel; para
    cambiar un valor con la rueda, haz clic en él y gira la rueda sin sacar el ratón de encima. Tener el foco no
    basta (el usuario: «estoy tratando de bajar y termino cambiando valores»): en cuanto el ratón sale del control,
    la rueda vuelve a desplazar el panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._armed = None                         # el control al que le diste clic (mientras el ratón siga encima)

    @staticmethod
    def _target(obj):
        """El control con valor al que pertenece obj (la casilla de texto de un número es hija del número)."""
        w = obj
        for _ in range(3):
            if w is None or not hasattr(w, "parentWidget"):
                return None
            if isinstance(w, (QAbstractSpinBox, QComboBox, QSlider, QTabBar)):
                return w
            if w.isWindow():                       # (la lista abierta de un desplegable es su propia ventanita)
                return None
            w = w.parentWidget()
        return None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and obj.isWidgetType():
            self._armed = self._target(obj)
        elif t == QEvent.Leave and self._armed is not None and obj is self._armed:
            self._armed = None                     # el ratón salió: la rueda vuelve a ser para el panel
        elif t == QEvent.Wheel and obj.isWidgetType():
            tgt = self._target(obj)
            if tgt is not None and not (tgt is self._armed and tgt.hasFocus()):
                w = tgt.parentWidget()
                while w is not None and not isinstance(w, QAbstractScrollArea):
                    w = w.parentWidget()
                if w is not None:                  # que se desplace el panel, como esperas
                    QApplication.sendEvent(w.viewport(), ev)
                return True
        if ev.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow():
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
    if not hasattr(app, "_qt_es"):            # los diálogos de Qt (color, archivos, Aceptar/Cancelar…) en español
        from PySide6.QtCore import QLibraryInfo, QTranslator
        app._qt_es = QTranslator(app)
        if app._qt_es.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(app._qt_es)
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
        QPalette.BrightText: "#ffffff", QPalette.Highlight: ACCENT_SEL,
        QPalette.HighlightedText: "#ffffff", QPalette.Link: ACCENT,
        QPalette.PlaceholderText: "#5f626a", QPalette.Mid: BORDER, QPalette.Dark: BG_DEEP,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(_tema.aclarar(color) if _tema.es_gris() and color not in _PALETA else color))
    pal.setColor(QPalette.Disabled, QPalette.Text, _tema.qc("#5b5e66"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, _tema.qc("#5b5e66"))
    app.setPalette(pal)
    if _tema.es_gris():
        _hook_estilos()
    apply_fonts(app)


# ------------------------------------------------------------------------------------------------ 🎨 profundidad sutil
# (20/11, ui/diseno.py) _estilo() termina con el bloque de «profundidad sutil»: capas de gris calculadas desde este
# tema, botones con relieve, campos hundidos, menús un escalón más claros y cabeceras con bisel. Se rehace con el
# acento (poner_acento vuelve a llamar a _estilo, y aquí se rehacen también las cabeceras plegables). Si diseno.py
# se carga antes que este archivo, él mismo vuelve a calcular STYLE al terminar de cargarse.
def _profundidad() -> str:
    try:
        from . import diseno as _diseno
        _diseno.rehacer_cabeceras()
        return _diseno.qss_profundidad()
    except (ImportError, AttributeError):
        return ""


STYLE = _estilo()
