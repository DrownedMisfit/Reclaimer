"""
«¿Qué me falta?»: cuando algo no se puede hacer porque falta un paso (seleccionar un clip, analizar tus clips,
escribir un nombre…), además de decirlo, Reclaimer RESALTA EN NARANJA el sitio exacto donde tienes que actuar
(el mismo recuadro tenue de la guía; los clics pasan a través y se va solo).
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QToolTip, QWidget

# (palabras del mensaje, a dónde llevar la vista en la ventana principal)
RULES = [
    (("analizar tus clips", "analizar tus medios", "botón ◈"), "library.btn_analyze"),
    (("importa", "importando", "panel izquierdo", "primero una canción"), "library"),
    (("efectos favoritos",), "effects.b_mem_add"),
    (("selecciona", "línea de tiempo", "timeline", "bajo el cabezal", "en el cabezal", "un corte"), "timeline"),
]


def main_window() -> QWidget | None:
    for w in QApplication.topLevelWidgets():
        if hasattr(w, "timeline") and hasattr(w, "library") and w.isVisible():
            return w
    return None


def _resolve(win, path: str):
    obj = win
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj if isinstance(obj, QWidget) else None


def reveal_tab(widget: QWidget | None):
    """Si el control está en una subpestaña que no se ve, se abre esa pestaña (y las de fuera)."""
    from PySide6.QtWidgets import QTabWidget
    w = widget
    while w is not None:
        p = w.parentWidget()
        tw = p.parentWidget() if p is not None else None       # pestaña → QStackedWidget → QTabWidget
        if isinstance(tw, QTabWidget):
            i = tw.indexOf(w)
            if i >= 0 and tw.currentIndex() != i:
                tw.setCurrentIndex(i)
        w = p


def nudge(widget: QWidget | None, tip: str | None = None, seconds: float = 4.0):
    """Resalta ese control en naranja unos segundos (y, si se da, explica qué falta junto a él)."""
    if widget is None:
        return
    from .guide import Highlighter, highlighter_of
    try:
        win = widget.window()
        hl = highlighter_of(win) or Highlighter(win)
        hl.show_on(widget, seconds)
        if tip:
            QToolTip.showText(widget.mapToGlobal(widget.rect().bottomLeft()), tip, widget)
        if widget.focusPolicy() and widget.isEnabled() and hasattr(widget, "selectAll"):
            widget.setFocus()
    except RuntimeError:        # el control ya no existe
        pass


# Solo se resalta cuando algo está BLOQUEADO (falta un paso antes): no con mensajes informativos
BLOCKED = ("selecciona", "primero", "antes ", "falta", "hace falta", "no hay ", "necesit", "elige ", "escribe ",
           "marca ", "pon el cabezal", "tiene que", "tienen que", "no se puede")


def is_blocking(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in BLOCKED)


def nudge_for(text: str, seconds: float = 4.0) -> bool:
    """Si el mensaje dice que falta un paso conocido (algo está bloqueado), resalta dónde se hace con un
    contorno naranja. Con mensajes que solo informan, no resalta nada. True si resaltó algo."""
    t = (text or "").lower()
    if not t or t.startswith(("✓", "⬇", "◈ ", "🥁 ritmo")) or not is_blocking(t):
        return False
    win = main_window()
    if win is None:
        return False
    for words, path in RULES:
        if any(w in t for w in words):
            target = _resolve(win, path)
            panel = getattr(win, path.split(".")[0], None)
            if target is not None and not target.isVisible() and panel is not None and hasattr(win, "show_panel") \
                    and panel is not getattr(win, "timeline", None):
                win.show_panel(panel)          # está en otra pestaña: se enseña primero
            if target is not None and not target.isVisible():
                reveal_tab(target)             # y si está en una subpestaña del panel, también
            if target is not None and target.isVisible():
                nudge(target, None, seconds)
                return True
    return False
