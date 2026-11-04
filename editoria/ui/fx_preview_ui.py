"""
🎞 Cómo se ve cada efecto: icono pequeño con el efecto aplicado y, al pasar el ratón, la animación en bucle
(core/fx_previews.py; toma de muestra CC0 de Poly Haven).

  icon(grupo, clave) -> QIcon            (vacío si no hay vista previa)
  attach(widget, grupo, clave)           al pasar el ratón por el botón/casilla: la animación al lado
  attach_list(lista, clave_de(item))     lo mismo, por cada fila de una lista (clave_de → (grupo, clave) o None)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QIcon, QMovie
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ..core import fx_previews as FP

_icons: dict = {}


def icon(group: str, key: str) -> QIcon:
    k = (group, key)
    if k not in _icons:
        p = FP.thumb(group, key)
        _icons[k] = QIcon(p) if p else QIcon()
    return _icons[k]


def short(tip: str) -> str:
    """La breve descripción: el primer párrafo de la ayuda (sin las instrucciones de clic/arrastrar)."""
    return (tip or "").strip().split("\n")[0].strip()


def split_key(full: str):
    """«look:bw» / «trans:fade» → (grupo, clave) si tiene vista previa."""
    if not full or ":" not in full:
        return None
    g, k = full.split(":", 1)
    return (g, k) if g in ("look", "trans", "edit") and FP.anim(g, k) else None


class _Popup(QWidget):
    """La animación flotante (una sola para toda la aplicación)."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("background: #111317; border: 1px solid #4a8fe0;")
        from PySide6.QtWidgets import QGridLayout
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)
        # «Sin efecto» | «Con efecto», lado a lado y a la vez (el usuario no veía bien qué hacía cada efecto)
        g = QGridLayout()
        g.setSpacing(4)
        self.head_before, self.head_after = QLabel("Sin efecto"), QLabel("Con efecto")
        for lb in (self.head_before, self.head_after):
            lb.setStyleSheet("border: none; color: #8b8f98; font-size: 8pt; padding: 0 2px;")
        self.before = QLabel()
        self.before.setFixedSize(320, 180)
        self.before.setStyleSheet("border: none;")
        self.view = QLabel()
        self.view.setFixedSize(320, 180)
        self.view.setStyleSheet("border: none;")
        g.addWidget(self.head_before, 0, 0)
        g.addWidget(self.head_after, 0, 1)
        g.addWidget(self.before, 1, 0)
        g.addWidget(self.view, 1, 1)
        v.addLayout(g)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("border: none; color: #c8ccd4; padding: 2px 4px;")
        v.addWidget(self.caption)
        self.movie = None
        self.movie_before = None
        self.key = None

    def show_for(self, group: str, key: str, title: str, desc: str, w: QWidget, local=None):
        """La tarjeta (animación + nombre + breve descripción) FUERA de la ventana donde está el efecto: a su
        lado (derecha o izquierda). Si la ventana ocupa toda la pantalla, fuera de su panel."""
        path = FP.anim(group, key)
        if not path:
            self.hide_now()
            return
        if self.key != (group, key):
            self.key = (group, key)
            for mv in (self.movie, self.movie_before):
                if mv is not None:
                    mv.stop()
            self.movie = QMovie(path, parent=self)
            self.movie.setScaledSize(QSize(320, 180))
            self.view.setMovie(self.movie)
            plain = FP.anim_plain(group, key)
            self.movie_before = QMovie(plain, parent=self) if plain else None
            for wdg in (self.before, self.head_before, self.head_after):
                wdg.setVisible(plain is not None)
            if self.movie_before is not None:
                self.movie_before.setScaledSize(QSize(320, 180))
                self.before.setMovie(self.movie_before)
                self.movie_before.start()            # (a la vez: van sincronizadas, mismos cortes)
            self.movie.start()
        self.caption.setFixedWidth(648 if self.movie_before is not None else 320)
        self.caption.setText(f"<b>{title}</b>" + (f"<br>{desc}" if desc else ""))
        self.adjustSize()
        r = local if local is not None else w.rect()
        mid = w.mapToGlobal(r.center())
        scr = QApplication.screenAt(mid) or QApplication.primaryScreen()
        g = scr.availableGeometry()
        boxes = [w.window().frameGeometry()]
        p = w.parentWidget()
        from PySide6.QtWidgets import QDockWidget, QGroupBox, QScrollArea
        while p is not None and p is not w.window():
            if isinstance(p, (QDockWidget, QScrollArea, QGroupBox)):
                tl = p.mapToGlobal(QPoint(0, 0))
                boxes.append(p.rect().translated(tl))
                if isinstance(p, QDockWidget):
                    break
            p = p.parentWidget()
        y = min(max(g.top(), mid.y() - self.height() // 2), g.bottom() - self.height())
        for b in boxes + [None]:
            if b is None:              # sin sitio a los lados: debajo del efecto
                x = min(max(g.left(), mid.x() - self.width() // 2), g.right() - self.width())
                y = w.mapToGlobal(r.bottomLeft()).y() + 6
                if y + self.height() > g.bottom():
                    y = w.mapToGlobal(r.topLeft()).y() - self.height() - 6
                break
            if b.right() + 8 + self.width() <= g.right():
                x = b.right() + 8
                break
            if b.left() - 8 - self.width() >= g.left():
                x = b.left() - 8 - self.width()
                break
        self.move(x, y)
        self.show()
        self.raise_()

    def hide_now(self):
        for mv in (self.movie, self.movie_before):
            if mv is not None:
                mv.stop()
        self.key = None
        self.hide()


_popup: _Popup | None = None


def popup() -> _Popup:
    global _popup
    if _popup is None:
        _popup = _Popup()
    return _popup


def hide():
    if _popup is not None:
        _popup.hide_now()


class _Hover(QObject):
    def __init__(self, w: QWidget, group: str, key: str):
        super().__init__(w)
        self.w, self.group, self.key = w, group, key

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Enter:
            title = self.w.text().strip() if hasattr(self.w, "text") else ""
            popup().show_for(self.group, self.key, title, short(self.w.toolTip()), self.w)
        elif t == QEvent.ToolTip and popup().isVisible():
            return True                          # la descripción ya va en la tarjeta: sin globo aparte
        elif t in (QEvent.Leave, QEvent.Hide, QEvent.MouseButtonPress):
            hide()
        return False


def attach(w: QWidget, group: str, key: str, with_icon: bool = True):
    if not FP.anim(group, key):
        return
    if with_icon and hasattr(w, "setIcon"):
        w.setIcon(icon(group, key))
        w.setIconSize(QSize(64, 36))           # (antes 48×27: no se veía qué hacía)
        from PySide6.QtWidgets import QPushButton
        if isinstance(w, QPushButton):           # miniatura a la izquierda y el nombre detrás (no centrado)
            w.setStyleSheet("text-align: left; padding-left: 6px;")
    w.installEventFilter(_Hover(w, group, key))


class _ListHover(QObject):
    def __init__(self, lst, key_of):
        super().__init__(lst)
        self.lst, self.key_of = lst, key_of
        lst.setMouseTracking(True)
        lst.itemEntered.connect(self._entered)

    def _entered(self, it):
        k = self.key_of(it) if it is not None else None
        if not k:
            hide()
            return
        popup().show_for(k[0], k[1], it.text().strip(), short(it.toolTip()), self.lst.viewport(),
                         self.lst.visualItemRect(it))

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ToolTip and popup().isVisible():
            return True
        if e.type() in (QEvent.Leave, QEvent.Hide, QEvent.MouseButtonPress):
            hide()
        return False


def attach_list(lst, key_of):
    """Iconos y animación al pasar por cada fila de una lista."""
    lst.setIconSize(QSize(48, 27))
    for i in range(lst.count()):
        k = key_of(lst.item(i))
        if k:
            lst.item(i).setIcon(icon(*k))
    h = _ListHover(lst, key_of)
    lst.viewport().installEventFilter(h)
    return h
