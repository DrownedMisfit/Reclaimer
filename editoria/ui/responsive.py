"""
↔ Paneles que se adaptan a cualquier ancho (queja del 17/11: «la pantalla se come las palabras»).

  adaptar(raiz)      → lo de dentro de raiz (y lo que se le añada después) nunca pide más ancho del que hay:
                       · etiquetas: se parten en varias líneas;
                       · botones, casillas y botones de radio: su texto se parte en varias líneas cuando no cabe
                         (si cabe, se ven exactamente igual que antes);
                       · desplegables: pueden estrecharse; si no cabe el texto, «…» y el texto entero al pasar el ratón;
                       · filas de botones/campos: bajan a la línea siguiente cuando no caben;
                       · rejillas de dos columnas: pasan a una columna cuando no caben;
                       · formularios: la etiqueta encima del campo cuando no cabe;
                       · listas y tablas: sin barra horizontal; lo que no cabe, con «…» y entero en la ayuda emergente.
  es_multilinea(w) / es_desplegable_que_acorta(w)   (para las pruebas)

Se hace sin cambiar el código de cada panel: cada widget pasa a una subclase con el mismo comportamiento cuando hay
sitio (Qt llama a sus métodos sustituidos). Lo que no se puede adaptar (dibujos propios, tiras de miniaturas) se marca
con la propiedad «responsive_horizontal» y se deja tal cual.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea, QCheckBox, QComboBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLayout,
                               QListView, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QStyle,
                               QStyleOptionButton, QStyleOptionComboBox, QStyleOptionToolButton, QStylePainter,
                               QLayoutItem, QTabBar, QToolBar, QToolButton, QToolTip, QWidget)

try:
    from shiboken6 import createdByPython as _de_python, isValid as _vivo
except ImportError:  # pragma: no cover
    def _de_python(_o):
        return True

    def _vivo(_o):
        return True

PALABRA_MAX = 90          # una palabra más ancha que esto se parte por donde haga falta (si no, por palabras)


# ------------------------------------------------------------------------------------------------ partir el texto
def _texto_visible(t: str) -> str:
    """El texto de un botón sin los «&» de los atajos («&&» = un «&»)."""
    return t.replace("&&", "\0").replace("&", "").replace("\0", "&")


def partir(texto: str, letra, ancho: int) -> list[str]:
    """Las líneas en que queda texto con esa letra y ese ancho (por palabras; una palabra que no cabe, por donde haga
    falta)."""
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(letra)
    ancho = max(8, int(ancho))
    out: list[str] = []
    for parrafo in texto.split(chr(10)):
        if not parrafo or fm.horizontalAdvance(parrafo) <= ancho:
            out.append(parrafo)
            continue
        tl = QTextLayout(parrafo, letra)
        op = QTextOption()
        op.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        tl.setTextOption(op)
        t16 = parrafo.encode("utf-16-le")          # (Qt cuenta en UTF-16: un emoji son dos posiciones)
        tl.beginLayout()
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(ancho)
            a = 2 * ln.textStart()
            out.append(t16[a:a + 2 * ln.textLength()].decode("utf-16-le", errors="ignore").rstrip())
        tl.endLayout()
    return out or [""]


def palabra_mas_ancha(texto: str, fm) -> int:
    return max((fm.horizontalAdvance(p) for p in texto.replace("\n", " ").split(" ") if p), default=0)


# ------------------------------------------------------------------------------------------------ botones y casillas
class _Multi:
    """(marca) Botón cuyo texto se parte en varias líneas cuando no cabe."""

    def _extra(self) -> int:
        """Lo que ocupa el botón aparte del texto (márgenes, icono, casilla)."""
        fm = self.fontMetrics()
        txt = _texto_visible(self.text())
        una = max((fm.horizontalAdvance(t) for t in txt.split("\n")), default=0)
        return max(10, self._una_linea().width() - una)

    def _una_linea(self) -> QSize:
        return self._qt.sizeHint(self)          # (el sizeHint de Qt: todo en una línea)

    def _lineas(self, ancho: int) -> list[str]:
        txt = _texto_visible(self.text())
        if not txt:
            return [""]
        return partir(txt, self.font(), ancho - self._extra())

    def _cabe(self) -> bool:
        return self.width() >= self._una_linea().width() - 1

    def sizeHint(self):
        return self._una_linea()

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        txt = _texto_visible(self.text())
        if not txt.strip():
            return base
        fm = self.fontMetrics()
        extra = self._extra()
        ancho = min(extra + min(palabra_mas_ancha(txt, fm), PALABRA_MAX), max(extra + 30, 110))
        return QSize(min(base.width(), ancho), base.height())

    def minimo_comodo(self) -> int:
        """El ancho con el que ninguna palabra se parte por la mitad (por debajo, se parte por donde haga falta)."""
        txt = _texto_visible(self.text())
        if not txt.strip():
            return self.minimumSizeHint().width()
        return min(self._una_linea().width(), self._extra() + palabra_mas_ancha(txt, self.fontMetrics()) + 2)

    def hasHeightForWidth(self):
        return bool(self.text())

    def heightForWidth(self, w):
        base = self._una_linea().height()
        n = len(self._lineas(w))
        return base + max(0, n - 1) * self.fontMetrics().lineSpacing()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def acortado(self) -> bool:
        """Sin alto para partirlo (un alto fijo puesto en el código): una línea con «…» y entero al pasar el ratón."""
        return not self._cabe() and self.heightForWidth(self.width()) > self.height() + 2

    def _texto_partido(self) -> str:
        if self.acortado():
            return self.fontMetrics().elidedText(_texto_visible(self.text()), Qt.ElideRight,
                                                 max(8, self.width() - self._extra())).replace("&", "&&")
        return "\n".join(t.replace("&", "&&") for t in self._lineas(self.width()))

    def event(self, ev):
        if ev.type() == QEvent.ToolTip and self.acortado():
            tip, txt = self.toolTip(), _texto_visible(self.text())
            QToolTip.showText(ev.globalPos(), txt if not tip or txt in tip else f"{txt}\n\n{tip}", self)
            return True
        return self._qt.event(self, ev)


class _BotonMulti(_Multi):
    def paintEvent(self, ev):
        if self._cabe():
            return self._qt.paintEvent(self, ev)
        p = QStylePainter(self)
        op = QStyleOptionButton()
        self.initStyleOption(op)
        op.text = self._texto_partido()
        p.drawControl(QStyle.CE_PushButton, op)


class _CasillaMulti(_Multi):
    def paintEvent(self, ev):
        if self._cabe():
            return self._qt.paintEvent(self, ev)
        p = QStylePainter(self)
        op = QStyleOptionButton()
        self.initStyleOption(op)
        op.text = self._texto_partido()
        p.drawControl(QStyle.CE_RadioButton if isinstance(self, QRadioButton) else QStyle.CE_CheckBox, op)


class _HerramientaMulti(_Multi):
    def paintEvent(self, ev):
        if self._cabe():
            return self._qt.paintEvent(self, ev)
        p = QStylePainter(self)
        op = QStyleOptionToolButton()
        self.initStyleOption(op)
        op.text = self._texto_partido()
        p.drawComplexControl(QStyle.CC_ToolButton, op)


def es_multilinea(w) -> bool:
    return isinstance(w, _Multi)


# ------------------------------------------------------------------------------------------------ desplegables
class _ComboAcorta:
    """(marca) Desplegable que se deja estrechar: si su texto no cabe, «…» y el texto entero al pasar el ratón."""

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        return QSize(min(base.width(), 72 + (self.iconSize().width() if self.count() else 0)), base.height())

    def _zona_texto(self, op) -> int:
        r = self.style().subControlRect(QStyle.CC_ComboBox, op, QStyle.SC_ComboBoxEditField, self)
        return r.width() - (op.iconSize.width() + 4 if not op.currentIcon.isNull() else 0)

    def _acortado(self) -> bool:
        op = QStyleOptionComboBox()
        self.initStyleOption(op)
        return self.fontMetrics().horizontalAdvance(op.currentText) > self._zona_texto(op)

    def paintEvent(self, ev):
        if self.isEditable():
            return self._qt.paintEvent(self, ev)
        p = QStylePainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        op = QStyleOptionComboBox()
        self.initStyleOption(op)
        if self.currentIndex() < 0 and self.placeholderText():
            op.currentText = self.placeholderText()
        p.drawComplexControl(QStyle.CC_ComboBox, op)
        op.currentText = self.fontMetrics().elidedText(op.currentText, Qt.ElideRight, max(8, self._zona_texto(op)))
        p.drawControl(QStyle.CE_ComboBoxLabel, op)

    def event(self, ev):
        if ev.type() == QEvent.ToolTip and not self.isEditable() and self._acortado():
            tip = self.toolTip()
            txt = self.currentText()
            QToolTip.showText(ev.globalPos(), txt if not tip or txt in tip else f"{txt}\n\n{tip}", self)
            return True
        return self._qt.event(self, ev)


def es_desplegable_que_acorta(w) -> bool:
    return isinstance(w, _ComboAcorta)


# ------------------------------------------------------------------------------------------------ lo que hay en un layout
# ⚠ NUNCA layout.itemAt() desde Python (causa de los cierres del 17/11 al vaciar «Dijiste…» y la lista de Edits).
#   PySide cuelga del layout, para siempre, el envoltorio de Python de cada QLayoutItem que devuelve itemAt(); pero Qt
#   borra ese QLayoutItem por su cuenta (al borrar su widget, al rehacer una página…) sin avisar a PySide: el envoltorio
#   sigue «vivo» apuntando a memoria libre. Cuando Qt pone otra cosa en esa misma dirección (un QListWidgetItem al
#   rehacer una lista, una ayuda emergente…), PySide le devuelve el envoltorio viejo → «'QWidgetItem' object has no
#   attribute 'isWidgetType'» o «access violation». Aquí se mira lo que hay en cada posición sin pedir su QLayoutItem:
#   los widgets (hijos del widget del layout) y los layouts hijos (QObject: PySide sí sabe cuándo se borran), con
#   layout.indexOf(). Los espaciadores no se ven (no hacen falta: se dejan fuera al colocar).
_MAXQ = 16777215


def _oculto(w) -> bool:
    return w.isWindow() or (w.isHidden() and not w.sizePolicy().retainSizeWhenHidden())


def _crece(pol) -> bool:
    return bool(pol.value & QSizePolicy.GrowFlag.value)


class _Pieza:
    """Lo que hay en una posición de un layout (un widget o un layout hijo), con lo que haría su QLayoutItem de Qt
    (QWidgetItem: sizeHint, mínimo «inteligente», alto según ancho, máximo) pero sin pedírselo a Qt."""
    __slots__ = ("obj", "indice", "es_lay")

    def __init__(self, obj, indice: int):
        self.obj = obj
        self.indice = indice
        self.es_lay = isinstance(obj, QLayout)

    def widget(self):
        return None if self.es_lay else self.obj

    def isEmpty(self) -> bool:
        return self.obj.isEmpty() if self.es_lay else _oculto(self.obj)

    def sizeHint(self) -> QSize:
        if self.es_lay:
            return self.obj.sizeHint()
        w = self.obj
        if _oculto(w):
            return QSize(0, 0)
        s = w.sizeHint().expandedTo(w.minimumSizeHint()).boundedTo(w.maximumSize()).expandedTo(w.minimumSize())
        sp = w.sizePolicy()
        if sp.horizontalPolicy() == QSizePolicy.Ignored:
            s.setWidth(0)
        if sp.verticalPolicy() == QSizePolicy.Ignored:
            s.setHeight(0)
        return s

    def minimumSize(self) -> QSize:
        if self.es_lay:
            return self.obj.minimumSize()
        w = self.obj
        if _oculto(w):
            return QSize(0, 0)
        sh, msh, sp = w.sizeHint(), w.minimumSizeHint(), w.sizePolicy()

        def eje(pol, a, b):                              # (qSmartMinSize de Qt)
            if pol == QSizePolicy.Ignored:
                return 0
            return b if pol.value & QSizePolicy.ShrinkFlag.value else max(a, b)
        s = QSize(eje(sp.horizontalPolicy(), sh.width(), msh.width()),
                  eje(sp.verticalPolicy(), sh.height(), msh.height())).boundedTo(w.maximumSize())
        mn = w.minimumSize()
        if mn.width() > 0:
            s.setWidth(mn.width())
        if mn.height() > 0:
            s.setHeight(mn.height())
        return s.expandedTo(QSize(0, 0))

    def crece_a_lo_ancho(self) -> bool:
        if self.es_lay:
            return bool(self.obj.expandingDirections() & Qt.Horizontal)
        w = self.obj
        if _oculto(w):
            return False
        sp = w.sizePolicy()
        if sp.expandingDirections() & Qt.Horizontal:
            return True
        lay = w.layout()
        return lay is not None and _crece(sp.horizontalPolicy()) and bool(lay.expandingDirections() & Qt.Horizontal)

    def hasHeightForWidth(self) -> bool:
        if self.es_lay:
            return self.obj.hasHeightForWidth()
        return not _oculto(self.obj) and self.obj.hasHeightForWidth()

    def heightForWidth(self, ancho: int) -> int:
        if self.es_lay:
            return self.obj.heightForWidth(ancho)
        w = self.obj
        lay = w.layout()
        h = lay.totalHeightForWidth(ancho) if lay is not None else w.heightForWidth(ancho)
        return max(0, min(max(h, w.minimumHeight()), w.maximumHeight()))

    def setGeometry(self, r: QRect):
        if self.es_lay:
            self.obj.setGeometry(r)
            return
        w = self.obj
        if _oculto(w):
            return
        sp = w.sizePolicy()
        mx = w.maximumSize()
        pista = w.sizeHint().expandedTo(w.minimumSize())
        mw = pista.width() if mx.width() == _MAXQ and not _crece(sp.horizontalPolicy()) else mx.width()
        mh = pista.height() if mx.height() == _MAXQ and not _crece(sp.verticalPolicy()) else mx.height()
        w.setGeometry(r.x(), r.y(), max(0, min(r.width(), mw)), max(0, min(r.height(), mh)))


def piezas(lay, con_ocultas: bool = False) -> list:
    """Lo que hay en el layout, en su orden (widgets y layouts hijos; sin espaciadores), SIN itemAt (ver arriba)."""
    try:
        if lay is None or not _vivo(lay) or lay.count() == 0:
            return []
        cand = []
        pw = lay.parentWidget()
        if pw is not None:
            cand.extend(c for c in pw.children() if c.isWidgetType())
        cand.extend(c for c in lay.children() if isinstance(c, QLayout))
        out = []
        faltan = lay.count()                             # (encontrado todo lo del layout: no se mira el resto de
        for c in cand:                                   #  hijos; contenedores con cientos de hijos y filas cortas)
            i = lay.indexOf(c)
            if i >= 0:
                p = _Pieza(c, i)
                if con_ocultas or not p.isEmpty():
                    out.append(p)
                faltan -= 1
                if faltan <= 0:
                    break
        out.sort(key=lambda p: p.indice)
        return out
    except RuntimeError:                                 # (algo ya borrado por Qt)
        return []


def widgets_en(lay) -> list:
    """Los widgets que hay directamente en el layout, en su orden (sin itemAt: ver arriba)."""
    return [p.obj for p in piezas(lay, con_ocultas=True) if not p.es_lay]


def layouts_hijos(lay) -> list:
    """Los layouts que hay dentro de lay (sin itemAt)."""
    try:
        return [c for c in lay.children() if isinstance(c, QLayout)]
    except RuntimeError:
        return []


def soltar_envoltorios_de_items() -> int:
    """(red de seguridad) Suelta los envoltorios de QLayoutItem que PySide crea y guarda POR SU CUENTA (p. ej.
    layout.addLayout(fila) con la fila ya llena crea uno para cada cosa de la fila). Nadie los usa y, si Qt borra ese
    QLayoutItem, se quedarían apuntando a memoria libre (ver arriba). Solo los que nadie más tiene; el objeto de Qt no se
    toca (shiboken6.invalidate: PySide lo olvida). Devuelve cuántos soltó."""
    try:
        from shiboken6 import getAllValidWrappers, invalidate, ownedByPython
    except ImportError:  # pragma: no cover
        return 0
    import sys
    n = 0
    for o in getAllValidWrappers():
        # (solo los de C++ que nadie tiene: la lista, el bucle, getrefcount y el layout que lo cuelga = 4; uno que es
        #  de Python, p. ej. lo que devuelve takeAt() guardado en un atributo, no se toca)
        if isinstance(o, QLayoutItem) and not isinstance(o, QObject) and not _de_python(o) and \
                not ownedByPython(o) and sys.getrefcount(o) <= 4:
            invalidate(o)
            n += 1
    return n


_T_SOLTAR = None


def _vigilar_envoltorios():
    """Cada pocos segundos (y al adaptar algo), soltar esos envoltorios (barato: solo recorre una lista)."""
    global _T_SOLTAR
    if _T_SOLTAR is not None:
        return
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    _T_SOLTAR = QTimer(app)
    _T_SOLTAR.setInterval(2000)
    _T_SOLTAR.timeout.connect(soltar_envoltorios_de_items)
    _T_SOLTAR.start()


# ------------------------------------------------------------------------------------------------ filas que bajan
class _FilaQueBaja:
    """(fila horizontal) Si cabe, exactamente como antes; si no, lo que no cabe baja a la línea siguiente."""

    def _base(self):
        return self._qt

    def _min_fila(self) -> int:
        """Desde qué ancho va todo en una fila como antes: cuando cabe cada cosa con su ancho de siempre (si no, lo
        que no cabe baja a la línea siguiente, en vez de aplastarlo y partir sus palabras por la mitad)."""
        return max(self._base().minimumSize(self).width(), self._base().sizeHint(self).width())

    def _piezas(self):
        return piezas(self)

    def _colocar(self, r: QRect, solo_medir: bool) -> int:
        m = self.contentsMargins()
        x0, y = r.x() + m.left(), r.y() + m.top()
        disp = max(1, r.width() - m.left() - m.right())
        esp = self.spacing() if self.spacing() >= 0 else 6
        lineas, linea, usado = [], [], 0
        for it in self._piezas():
            w = min(max(it.sizeHint().width(), it.minimumSize().width()), disp)
            if linea and usado + esp + w > disp:
                lineas.append(linea)
                linea, usado = [], 0
            linea.append([it, w])
            usado += (esp if len(linea) > 1 else 0) + w
        if linea:
            lineas.append(linea)
        for linea in lineas:
            usado = sum(w for _it, w in linea) + esp * (len(linea) - 1)
            sobra = disp - usado
            crecen = [p for p in linea if p[0].crece_a_lo_ancho() or self.stretch(p[0].indice) > 0]
            if not crecen and len(linea) == 1:
                crecen = linea
            for p in crecen:
                p[1] += sobra // len(crecen)
            alto = 0
            for it, w in linea:
                alto = max(alto, it.heightForWidth(w) if it.hasHeightForWidth() else it.sizeHint().height())
            x = x0
            for it, w in linea:
                if not solo_medir:
                    h = it.heightForWidth(w) if it.hasHeightForWidth() else min(alto, max(it.sizeHint().height(),
                                                                                           it.minimumSize().height()))
                    it.setGeometry(QRect(x, y, w, h))
                x += w + esp
            y += alto + esp
        return y - esp - r.y() + m.bottom() if lineas else m.top() + m.bottom()

    def setGeometry(self, r):
        if r.width() >= self._min_fila():
            return self._base().setGeometry(self, r)
        QLayout.setGeometry(self, r)
        self._colocar(r, False)

    def minimumSize(self):
        base = self._base().minimumSize(self)
        m = self.contentsMargins()
        ancho = max((it.minimumSize().width() for it in self._piezas()), default=0) + m.left() + m.right()
        return QSize(min(base.width(), ancho), base.height())

    def hasHeightForWidth(self):
        return True

    def invalidate(self):
        self.__dict__.pop("_cache_hfw", None)
        self._base().invalidate(self)

    def heightForWidth(self, w):
        cache = self.__dict__.setdefault("_cache_hfw", {})
        if w not in cache:
            if w >= self._min_fila():
                b = self._base()
                cache[w] = b.heightForWidth(self, w) if b.hasHeightForWidth(self) else b.sizeHint(self).height()
            else:
                cache[w] = self._colocar(QRect(0, 0, w, 0), True)
            if len(cache) > 8:
                cache.pop(next(iter(cache)))
        return cache[w]

    def minimumHeightForWidth(self, w):
        return self.heightForWidth(w)


# ------------------------------------------------------------------------------------------------ rejillas de 2 columnas
class _RejillaQueBaja:
    """(rejilla) Si caben todas sus columnas, exactamente como antes; si no, una sola columna (cada cosa debajo de la
    anterior, en el orden en que se lee). Con la propiedad «responsive_columnas» = n, en vez de eso se parte en
    bloques de columnas (como el ecualizador: B1 B2 B3 | B4 B5 B6), con las n últimas columnas en el primer bloque."""

    def _base(self):
        return self._qt

    def _celdas(self):
        out = []
        for it in piezas(self):
            r, c, rs, cs = self.getItemPosition(it.indice)
            out.append((r, c, rs, cs, it))
        out.sort(key=lambda x: (x[0], x[1]))
        return out

    def _esp(self):
        h = self.horizontalSpacing()
        v = self.verticalSpacing()
        return (h if h >= 0 else 6), (v if v >= 0 else 6)

    @staticmethod
    def _anchos_col(cel, n) -> list:
        cols = [0] * n
        for _r, c, _rs, cs, it in cel:
            if cs == 1 and c < n:
                cols[c] = max(cols[c], it.sizeHint().width(), it.minimumSize().width())
        return cols

    def _todas_caben(self, w: int) -> bool:
        n = self.columnCount()
        if n <= 1:
            return True
        cel = self._celdas()
        m = self.contentsMargins()
        eh, _ev = self._esp()
        need = sum(self._anchos_col(cel, n)) + eh * (n - 1) + m.left() + m.right()
        return w >= max(need, self._base().minimumSize(self).width())

    def _bloques(self, disp: int):
        """(modo por bloques) cuántas columnas por bloque caben."""
        n = self.columnCount()
        fijas = int(self.property("responsive_columnas") or 0)
        cols = self._anchos_col(self._celdas(), n)
        eh, _ev = self._esp()
        libres = cols[:n - fijas] if fijas else cols
        extra = (sum(cols[n - fijas:]) + eh * fijas) if fijas else 0
        k = len(libres)
        while k > 1 and sum(sorted(libres, reverse=True)[:k]) + eh * (k - 1) + extra > disp:
            k -= 1
        return max(1, k), fijas

    def _colocar(self, r: QRect, solo_medir: bool) -> int:
        m = self.contentsMargins()
        x0, y = r.x() + m.left(), r.y() + m.top()
        disp = max(1, r.width() - m.left() - m.right())
        eh, ev = self._esp()
        cel = self._celdas()

        def alto(it, w):
            return it.heightForWidth(w) if it.hasHeightForWidth() else max(it.sizeHint().height(),
                                                                             it.minimumSize().height())

        if self.property("responsive_columnas") is not None and self.columnCount() > 1:
            k, fijas = self._bloques(disp)
            n = self.columnCount()
            libres = n - fijas
            nb = max(1, -(-libres // k))
            filas = max((rr + rs for rr, _c, rs, _cs, _it in cel), default=0)
            for b in range(nb):
                cols = list(range(b * k, min(libres, b * k + k))) + (list(range(libres, n)) if b == 0 else [])
                if not cols:
                    continue
                ancho = max(1, (disp - eh * (len(cols) - 1)) // len(cols))
                for fila in range(filas):
                    en_fila = [(c, it) for rr, c, _rs, _cs, it in cel if rr == fila and c in cols]
                    if not en_fila:
                        continue
                    h = max(alto(it, ancho) for _c, it in en_fila)
                    for c, it in en_fila:
                        if not solo_medir:
                            it.setGeometry(QRect(x0 + cols.index(c) * (ancho + eh), y, ancho, h))
                    y += h + ev
            return y - ev - r.y() + m.bottom() if cel else m.top() + m.bottom()
        for _r, _c, _rs, _cs, it in cel:              # una columna, en el orden en que se lee
            h = alto(it, disp)
            if not solo_medir:
                it.setGeometry(QRect(x0, y, disp, h))
            y += h + ev
        return y - ev - r.y() + m.bottom() if cel else m.top() + m.bottom()

    def setGeometry(self, r):
        if self._todas_caben(r.width()):
            return self._base().setGeometry(self, r)
        QLayout.setGeometry(self, r)
        self._colocar(r, False)

    def minimumSize(self):
        base = self._base().minimumSize(self)
        m = self.contentsMargins()
        cel = self._celdas()
        if self.property("responsive_columnas") is not None:
            fijas = int(self.property("responsive_columnas") or 0)
            n = self.columnCount()
            cols = self._anchos_col(cel, n)
            eh, _ev = self._esp()
            uno = (max(cols[:n - fijas] or [0]) + sum(cols[n - fijas:]) + eh * fijas) if fijas else max(cols or [0])
        else:
            uno = max((it.minimumSize().width() for *_x, it in cel), default=0)
        return QSize(min(base.width(), uno + m.left() + m.right()), base.height())

    def hasHeightForWidth(self):
        return True

    def invalidate(self):
        self.__dict__.pop("_cache_hfw", None)
        self._base().invalidate(self)

    def heightForWidth(self, w):
        cache = self.__dict__.setdefault("_cache_hfw", {})
        if w not in cache:
            if self._todas_caben(w):
                b = self._base()
                cache[w] = b.heightForWidth(self, w) if b.hasHeightForWidth(self) else b.sizeHint(self).height()
            else:
                cache[w] = self._colocar(QRect(0, 0, w, 0), True)
            if len(cache) > 8:
                cache.pop(next(iter(cache)))
        return cache[w]

    def minimumHeightForWidth(self, w):
        return self.heightForWidth(w)


class _ZonaQueSube:
    """(zona con desplazamiento dentro de un panel) A lo ancho pide lo que pide su contenido: así el panel nunca la deja
    más estrecha y su contenido no se corta (a lo alto sigue desplazándose)."""

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        w = self.widget()
        if w is None or not self.widgetResizable():
            return base
        return QSize(max(base.width(), max(w.minimumSizeHint().width(), w.minimumWidth()) + _barra(self) +
                         2 * self.frameWidth()), base.height())

    def eventFilter(self, obj, ev):
        if obj is self.widget() and ev.type() == QEvent.LayoutRequest:
            self.updateGeometry()
        return self._qt.eventFilter(self, obj, ev)


# ------------------------------------------------------------------------------------------------ listas y tablas
class _VistaSinBarra(QObject):
    """Listas y tablas: sin barra horizontal; las columnas se estrechan para caber y lo cortado («…») sale entero al
    pasar el ratón."""

    def __init__(self, vista: QAbstractItemView):
        super().__init__(vista)
        self.vista = vista
        vista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        vista.setTextElideMode(Qt.ElideRight)
        vista.viewport().installEventFilter(self)
        vista.installEventFilter(self)
        if isinstance(vista, QListView) and vista.viewMode() == QListView.ListMode:
            vista.setWordWrap(True)
            vista.setResizeMode(QListView.Adjust)
            vista.setUniformItemSizes(False)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(0)
        self._t.timeout.connect(self.encajar)

    def encajar(self):
        v = self.vista
        if not _vivo(v):
            return
        h = getattr(v, "header", None)
        h = h() if callable(h) else getattr(v, "horizontalHeader", lambda: None)()
        if not isinstance(h, QHeaderView) or h.count() == 0:
            return
        disp = v.viewport().width()
        if disp <= 20:
            return
        vis = [i for i in range(h.count()) if not h.isSectionHidden(i)]
        if not vis:
            return
        # Cómo era la tabla antes de tocarla (para devolverla tal cual cuando vuelva a caber: antes una columna
        # estrechada en un momento estrecho se quedaba así para siempre: «Vi…», miniaturas recortadas)
        orig = getattr(self, "_orig", None)
        if orig is None or len(orig) != h.count():
            orig = self._orig = {i: (h.sectionResizeMode(i), h.sectionSize(i)) for i in range(h.count())}
            self._estira_ultima = h.stretchLastSection()
            self._min_seccion = h.minimumSectionSize()
            self._cambiado = False
        estiran = [i for i in vis if orig[i][0] == QHeaderView.Stretch]
        fijas = [i for i in vis if orig[i][0] == QHeaderView.Fixed]
        ajust = [i for i in vis if i not in estiran and i not in fijas]
        if not ajust:
            return
        quiero = {}
        for i in ajust:
            q = orig[i][1]
            if orig[i][0] == QHeaderView.ResizeToContents:
                try:                                # (lo de dentro o la cabecera, lo que pida más: nada cortado)
                    q = max(v.sizeHintForColumn(i), h.sectionSizeHint(i), 24)
                except Exception:  # noqa: BLE001
                    pass
            quiero[i] = q
        minimo = {i: self._minimo(v, h, i) for i in ajust}
        hace_falta = sum(h.sectionSize(i) for i in fijas) + sum(quiero.values()) + 56 * len(estiran)
        if hace_falta <= disp:                      # ✓ cabe: como era
            if self._cambiado:
                for i in ajust:
                    h.setSectionResizeMode(i, QHeaderView.Interactive)
                    h.resizeSection(i, quiero[i])
                    h.setSectionResizeMode(i, orig[i][0])
                h.setStretchLastSection(self._estira_ultima)
                h.setMinimumSectionSize(self._min_seccion)
                self._cambiado = False
            else:                                   # (el ancho que le pones tú a mano a una columna pasa a ser el
                for i in ajust:                     #  «de siempre»: no se pisa al estrecharla y volver a ensancharla)
                    if orig[i][0] == QHeaderView.Interactive and not (self._estira_ultima and i == vis[-1]) \
                            and h.sectionSize(i) != orig[i][1]:
                        orig[i] = (orig[i][0], h.sectionSize(i))
            return
        self._cambiado = True                       # ✗ no cabe: se estrecha primero la columna más ancha
        h.setMinimumSectionSize(min(self._min_seccion, 24))
        tam = dict(quiero)
        sobra = hace_falta - disp
        for i in sorted(ajust, key=tam.get, reverse=True):
            if sobra <= 0:
                break
            quita = min(sobra, max(0, tam[i] - minimo[i]))
            tam[i] -= quita
            sobra -= quita
        for i in ajust:
            if h.sectionResizeMode(i) != QHeaderView.Interactive:
                h.setSectionResizeMode(i, QHeaderView.Interactive)
            h.resizeSection(i, tam[i])
        if not estiran and orig[vis[-1]][0] != QHeaderView.Fixed:
            h.setStretchLastSection(True)

    @staticmethod
    def _minimo(v, h, i: int) -> int:
        """Lo mínimo de una columna: la primera de un árbol, su sangría + el icono entero + algo de texto."""
        from PySide6.QtWidgets import QTreeView
        if isinstance(v, QTreeView) and h.visualIndex(i) == 0:
            sangria = v.indentation() * (2 if v.rootIsDecorated() else 1)
            return sangria + max(0, v.iconSize().width()) + 56
        return 56

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Resize:
            self._t.start()
        elif t == QEvent.ToolTip and obj is self.vista.viewport():
            v = self.vista
            idx = v.indexAt(ev.pos())
            if idx.isValid() and not idx.data(Qt.ToolTipRole):
                txt = idx.data(Qt.DisplayRole)
                if isinstance(txt, str) and txt:
                    r = v.visualRect(idx)
                    if v.fontMetrics().horizontalAdvance(txt) + 8 > min(r.width(), v.viewport().width() - r.x()):
                        QToolTip.showText(ev.globalPos(), txt, v)
                        return True
        return False


class _Delegado:
    """(marca) El delegado de una lista: ningún elemento más ancho que la lista (así se acorta con «…»)."""

    def sizeHint(self, op, idx):
        s = self._qt.sizeHint(self, op, idx)
        v = self.parent()
        if isinstance(v, QAbstractItemView) and v.viewport().width() > 20:
            return QSize(min(s.width(), v.viewport().width() - 2), s.height())
        return s


# ------------------------------------------------------------------------------------------------ pestañas y divisores
class _AyudaPestana(QObject):
    """Las pestañas que no caben se acortan («🌐…», como hace Qt): al pasar el ratón, su nombre entero."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.ToolTip and isinstance(obj, QTabBar):
            i = obj.tabAt(ev.pos())
            if i >= 0 and not obj.tabToolTip(i) and obj.tabText(i):
                QToolTip.showText(ev.globalPos(), obj.tabText(i).replace("&&", "&"), obj)
                return True
        return False


_AYUDA_PESTANA = None


def _pestanas(tb: QTabBar):
    global _AYUDA_PESTANA
    if getattr(tb, "_responsive_pestanas", False):
        return
    tb._responsive_pestanas = True
    tb.setUsesScrollButtons(False)          # (sin flechas: todas a la vista; las que no caben, acortadas)
    tb.setElideMode(Qt.ElideRight)
    if not tb.styleSheet():                 # (un poco menos de relleno a los lados: caben más en un panel estrecho)
        tb.setStyleSheet("QTabBar::tab { padding-left: 7px; padding-right: 7px; }")
    if _AYUDA_PESTANA is None:
        _AYUDA_PESTANA = _AyudaPestana()
    tb.installEventFilter(_AYUDA_PESTANA)


class _AltoSegunAncho:
    """(lo que va dentro de un divisor) Un divisor no sabe que el texto partido necesita más alto: el mínimo de alto
    de esto es el que necesita a su ancho de ahora (así lo partido nunca se corta por abajo)."""

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        lay = self.layout()
        if lay is None or not lay.hasHeightForWidth() or self.width() < 10:
            return base
        # (lo que pide a ese ancho: un divisor reparte sin saber de textos partidos y los aplastaría)
        return QSize(base.width(), max(base.height(), lay.totalHeightForWidth(self.width())))

    def resizeEvent(self, ev):
        self._qt.resizeEvent(self, ev)
        if ev.oldSize().width() != ev.size().width():
            self.updateGeometry()


def _en_divisor(w: QWidget):
    from PySide6.QtWidgets import QSplitter
    if isinstance(w.parentWidget(), QSplitter) and type(w) in (QWidget, QGroupBox, QFrame_()):
        if _cambiar(w, _AltoSegunAncho, type(w), "minimumSizeHint", "resizeEvent"):
            w.updateGeometry()


def QTabWidget_():
    from PySide6.QtWidgets import QTabWidget
    return QTabWidget


def QFrame_():
    from PySide6.QtWidgets import QFrame
    return QFrame


# ------------------------------------------------------------------------------------------------ cambiar de clase
_CLASES: dict = {}


def _clase(base: type, mezcla: type) -> type:
    k = (base, mezcla)
    if k not in _CLASES:
        _CLASES[k] = type(f"{mezcla.__name__.strip('_')}_{base.__name__}", (mezcla, base), {"_qt": base})
    return _CLASES[k]


def _propia(base: type, qt: type, *metodos) -> bool:
    """¿La clase de Python ya cambia alguno de estos métodos? (entonces se deja como está)"""
    for m in metodos:
        if getattr(base, m, None) is not getattr(qt, m, None):
            return True
    return False


def _cambiar(w, mezcla, qt, *metodos) -> bool:
    base = type(w)
    if isinstance(w, (_Multi, _ComboAcorta, _ZonaQueSube, _AltoSegunAncho, _CajaAcorta, _PilaActual, _PaginaApilada)):
        return False
    if not _de_python(w) or _propia(base, qt, *metodos):
        return False
    try:
        w.__class__ = _clase(base, mezcla)
    except TypeError:
        return False
    return True


_QT_BOTON = {QPushButton: (_BotonMulti, QPushButton), QCheckBox: (_CasillaMulti, QCheckBox),
             QRadioButton: (_CasillaMulti, QRadioButton), QToolButton: (_HerramientaMulti, QToolButton)}


def _boton(w: QAbstractButton):
    for qt, (mezcla, base) in _QT_BOTON.items():
        if isinstance(w, qt):
            break
    else:
        return
    if isinstance(w, QToolButton) and (w.toolButtonStyle() == Qt.ToolButtonIconOnly or w.autoRaise()
                                       and not w.text()):
        return
    p = w.parentWidget()
    if isinstance(p, (QToolBar, QTabBar)):
        return
    if _cambiar(w, mezcla, base, "paintEvent", "sizeHint", "minimumSizeHint", "heightForWidth", "hasHeightForWidth"):
        sp = w.sizePolicy()
        if sp.verticalPolicy() == QSizePolicy.Fixed:
            sp.setVerticalPolicy(QSizePolicy.Minimum)
        _que_encoja(w, sp)
        sp.setHeightForWidth(True)
        w.setSizePolicy(sp)
        w.updateGeometry()


def _que_encoja(w, sp):
    """(Qt da a botones y casillas la política «Minimum»: nunca más estrechos que su texto en una línea. Con el texto
    que se parte, sí pueden: «Preferred».)"""
    h = sp.horizontalPolicy()
    if h == QSizePolicy.Minimum or (h == QSizePolicy.Fixed and w.maximumWidth() >= 16777215):
        sp.setHorizontalPolicy(QSizePolicy.Preferred)
    elif h == QSizePolicy.MinimumExpanding:
        sp.setHorizontalPolicy(QSizePolicy.Expanding)


def _etiqueta(w: QLabel):
    if w.pixmap() is not None and not w.pixmap().isNull():
        return
    if w.movie() is not None or w.property("responsive_una_linea"):
        return
    if not w.wordWrap():
        w.setWordWrap(True)
        if w.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed and not w.maximumWidth() < 10000:
            sp = w.sizePolicy()
            sp.setHorizontalPolicy(QSizePolicy.Preferred)
            w.setSizePolicy(sp)


def _desplegable(w: QComboBox):
    if _cambiar(w, _ComboAcorta, QComboBox, "paintEvent", "minimumSizeHint"):
        if w.minimumWidth() > 90:
            w.setMinimumWidth(72)
        sp = w.sizePolicy()
        _que_encoja(w, sp)
        w.setSizePolicy(sp)
        w.updateGeometry()


class _CajaAcorta:
    """(grupo con título) El título no pide más ancho que lo de dentro: si no cabe, «…» y entero al pasar el ratón."""

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        return QSize(min(base.width(), QWidget.minimumSizeHint(self).width()), base.height())

    def _titulo_cabe(self) -> bool:
        return self.fontMetrics().horizontalAdvance(self.title()) + 24 <= self.width()

    def paintEvent(self, ev):
        if not self.title() or self._titulo_cabe():
            return self._qt.paintEvent(self, ev)
        from PySide6.QtWidgets import QStyleOptionGroupBox
        p = QStylePainter(self)
        op = QStyleOptionGroupBox()
        self.initStyleOption(op)
        op.text = self.fontMetrics().elidedText(self.title(), Qt.ElideRight, max(8, self.width() - 24))
        p.drawComplexControl(QStyle.CC_GroupBox, op)

    def event(self, ev):
        if ev.type() == QEvent.ToolTip and self.title() and not self._titulo_cabe():
            tip = self.toolTip()
            t = self.title().replace("&&", "&")
            QToolTip.showText(ev.globalPos(), t if not tip else f"{t}\n\n{tip}", self)
            return True
        return self._qt.event(self, ev)


class _PilaActual:
    """(páginas apiladas) A lo alto pide lo de la página que se ve (no lo de la más alta: sin un hueco enorme debajo);
    a lo ancho, lo de la más ancha (así no baila al cambiar de página)."""

    def minimumSizeHint(self):
        p = self.currentWidget()
        f = 2 * self.frameWidth()
        ancho = max((self.widget(i).minimumSizeHint().width() for i in range(self.count())), default=0)
        return QSize(ancho + f, (p.minimumSizeHint().height() if p is not None else 0) + f)

    def sizeHint(self):
        base = self._qt.sizeHint(self)
        p = self.currentWidget()
        return QSize(base.width(), p.sizeHint().height() + 2 * self.frameWidth() if p is not None else base.height())

    def hasHeightForWidth(self):
        p = self.currentWidget()
        return p is not None and p.hasHeightForWidth()

    def heightForWidth(self, w):
        p = self.currentWidget()
        return p.heightForWidth(w - 2 * self.frameWidth()) + 2 * self.frameWidth() if p is not None else -1


class _PaginaApilada:
    """(página de unas páginas apiladas) Oculta, no pide alto: QStackedLayout pregunta el alto a todas sus páginas,
    también a las que no se ven, y el panel se quedaba con el hueco de la más alta (Inspector: 2700 px)."""

    def minimumSizeHint(self):
        base = self._qt.minimumSizeHint(self)
        return QSize(base.width(), 0) if self.isHidden() else base

    def sizeHint(self):
        base = self._qt.sizeHint(self)
        return QSize(base.width(), 0) if self.isHidden() else base

    def heightForWidth(self, w):
        return 0 if self.isHidden() else self._qt.heightForWidth(self, w)


def _al_cambiar_pagina(pila):
    if not _vivo(pila):
        return
    for i in range(pila.count()):
        p = pila.widget(i)
        if p is None:
            continue
        p.updateGeometry()
        if p.layout() is not None:
            p.layout().invalidate()
    if pila.layout() is not None:
        pila.layout().invalidate()
    pila.updateGeometry()


def _pila(w):
    """Páginas apiladas (QStackedWidget) y pestañas (QTabWidget): a lo alto, solo cuenta la página que se ve."""
    from PySide6.QtWidgets import QStackedWidget
    if type(w) is QStackedWidget and _cambiar(w, _PilaActual, QStackedWidget, "minimumSizeHint", "sizeHint"):
        w.updateGeometry()
    if not isinstance(w, (_PilaActual, QTabWidget_())):
        return
    if not getattr(w, "_paginas_resp", False):
        w._paginas_resp = True
        w.currentChanged.connect(lambda _i, p=w: _al_cambiar_pagina(p))
    cambio = False
    for i in range(w.count()):
        p = w.widget(i)
        if p is not None and not isinstance(p, _PaginaApilada):
            cambio |= _cambiar(p, _PaginaApilada, type(p), "minimumSizeHint", "sizeHint", "heightForWidth")
    if cambio:
        _al_cambiar_pagina(w)


def _caja(w: QGroupBox):
    """Grupos: márgenes de los lados pequeños (más sitio dentro) y el título nunca pide más ancho."""
    lay = w.layout()
    if lay is not None:
        m = lay.contentsMargins()
        if m.left() > 4 or m.right() > 4:
            lay.setContentsMargins(min(m.left(), 4), m.top(), min(m.right(), 4), m.bottom())
    if _cambiar(w, _CajaAcorta, QGroupBox, "paintEvent", "minimumSizeHint"):
        w.updateGeometry()


def _fila(lay: QHBoxLayout):
    if isinstance(lay, _FilaQueBaja) or not _de_python(lay) or \
            _propia(type(lay), QHBoxLayout, "setGeometry", "minimumSize", "sizeHint", "heightForWidth"):
        return
    if len(piezas(lay, con_ocultas=True)) < 2:
        return
    if lay.property("responsive_no_baja"):     # (el código pide que esta fila no se parta: se estrecha entera)
        return
    try:
        lay.__class__ = _clase(type(lay), _FilaQueBaja)
    except TypeError:
        return
    lay.invalidate()


def _rejilla(lay: QGridLayout):
    if isinstance(lay, _RejillaQueBaja) or not _de_python(lay) or lay.columnCount() < 2 or \
            _propia(type(lay), QGridLayout, "setGeometry", "minimumSize", "sizeHint", "heightForWidth"):
        return
    try:
        lay.__class__ = _clase(type(lay), _RejillaQueBaja)
    except TypeError:
        return
    lay.invalidate()


def _vista(v: QAbstractItemView):
    if getattr(v, "_sin_barra", None) is not None or v.property("responsive_horizontal"):
        return
    if isinstance(v, QListView) and (v.viewMode() != QListView.ListMode or
                                     v.flow() == QListView.LeftToRight and not v.isWrapping()):
        return                                  # (cuadrículas de miniaturas y tiras horizontales: tal cual)
    v._sin_barra = _VistaSinBarra(v)
    d = v.itemDelegate()
    if isinstance(v, QListView) and d is not None and type(d).__name__ in ("QStyledItemDelegate", "QItemDelegate") \
            and _de_python(d):
        try:
            d.__class__ = _clase(type(d), _Delegado)
        except TypeError:
            pass


def _layouts(w: QWidget):
    lay = w.layout()
    if lay is None:
        return
    pila = [lay]
    while pila:
        lo = pila.pop()
        m = lo.contentsMargins()
        if m.left() > 4 or m.right() > 4:          # (márgenes de los lados pequeños: más sitio para lo de dentro)
            lo.setContentsMargins(min(m.left(), 4), m.top(), min(m.right(), 4), m.bottom())
        if isinstance(lo, QFormLayout):
            if lo.rowWrapPolicy() == QFormLayout.DontWrapRows:
                lo.setRowWrapPolicy(QFormLayout.WrapLongRows)
        elif isinstance(lo, QGridLayout):
            _rejilla(lo)
        elif isinstance(lo, QHBoxLayout):
            _fila(lo)
        pila.extend(layouts_hijos(lo))                  # (sin itemAt: ver «lo que hay en un layout»)


def _horizontal(w) -> bool:
    p = w
    while p is not None:
        if p.property("responsive_horizontal"):
            return True
        p = p.parentWidget()
    return False


def _en_otra_ventana(w, raiz) -> bool:
    """¿Está w dentro de un diálogo o menú hijo del panel (otra ventana)? Esos no se tocan."""
    p = w
    while p is not None and p is not raiz:
        if p.isWindow():
            return True
        p = p.parentWidget()
    return False


def adaptar_una_vez(raiz: QWidget, sub: QWidget | None = None):
    """Adapta lo que hay ahora dentro de raiz (o solo dentro de sub, una parte de raiz que cambió)."""
    if not _vivo(raiz) or (sub is not None and not _vivo(sub)):
        return
    base = sub if sub is not None else raiz
    if base is not raiz and _en_otra_ventana(base, raiz):
        return
    ws = [base] + base.findChildren(QWidget)
    nuevos = []
    for w in ws:
        try:
            if w is not raiz and _en_otra_ventana(w, raiz):
                continue
            if getattr(w, "_responsive", False):
                _layouts(w)                     # (filas o rejillas añadidas después a algo ya adaptado)
                _pila(w)                        # (y páginas nuevas en unas pestañas)
                continue
            if _horizontal(w):
                w._responsive = True
                continue
            if isinstance(w, QLabel):
                _etiqueta(w)
            elif isinstance(w, QAbstractButton):
                _boton(w)
            elif isinstance(w, QComboBox):
                _desplegable(w)
            elif isinstance(w, QAbstractItemView):
                _vista(w)
            elif isinstance(w, QScrollArea) and not isinstance(w, ZonaPanel):
                if w.widgetResizable():
                    w.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    _cambiar(w, _ZonaQueSube, QScrollArea, "minimumSizeHint", "eventFilter")
                    w.updateGeometry()
            elif isinstance(w, QTabBar):
                _pestanas(w)
            else:
                _en_divisor(w)
                _pila(w)
            if isinstance(w, QGroupBox):
                _caja(w)
            if w.layout() is not None or isinstance(w, (QTabWidget_(), QAbstractScrollArea)):
                sp = w.sizePolicy()                 # (un contenedor «Minimum» nunca se estrecharía: sí puede)
                h0 = sp.horizontalPolicy()
                _que_encoja(w, sp)
                if sp.horizontalPolicy() != h0:
                    w.setSizePolicy(sp)
            _layouts(w)
            w._responsive = True
            if w.layout() is not None:          # (solo los contenedores: ahí es donde se añaden cosas)
                w.installEventFilter(_vigia(raiz))
            nuevos.append(w)
        except RuntimeError:
            continue
    for w in reversed(nuevos):                   # (de dentro afuera: que Qt olvide los tamaños de antes)
        try:
            if w.layout() is not None:
                w.layout().invalidate()
            w.updateGeometry()
        except RuntimeError:
            pass
    soltar_envoltorios_de_items()
    _vigilar_envoltorios()


class _Vigia(QObject):
    """Lo que se añade después a un panel (páginas que se rellenan, paneles nuevos) también se adapta."""

    def __init__(self, raiz):
        super().__init__(raiz)
        self.raiz = raiz
        self.pendientes = []                     # (los contenedores que recibieron algo: solo se adapta eso)
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.setInterval(60)
        self.t.timeout.connect(self._adaptar)

    def _adaptar(self):
        pend, self.pendientes = self.pendientes, []
        for w in pend:
            if not _vivo(w) or any(o is not w and _vivo(o) and o.isAncestorOf(w) for o in pend):
                continue                             # (ya va dentro de otro que se adapta)
            adaptar_una_vez(self.raiz, w)

    def eventFilter(self, obj, ev):
        # (sin mirar ev.child(): en ChildAdded el hijo aún se está construyendo y pedir su envoltorio de Python a
        #  medio hacer es arriesgado; basta con saber qué contenedor recibió algo)
        if ev.type() == QEvent.ChildAdded:
            if obj.isWidgetType():
                if not any(o is obj for o in self.pendientes):
                    self.pendientes.append(obj)
                if not self.t.isActive():
                    self.t.start()
        return False


def _vigia(raiz) -> _Vigia:
    v = getattr(raiz, "_vigia_responsive", None)
    if v is None:
        v = raiz._vigia_responsive = _Vigia(raiz)
    return v


def adaptar(raiz: QWidget) -> QWidget:
    """Adapta raiz ahora y lo que se le añada después."""
    adaptar_una_vez(raiz)
    return raiz


def _barra(zona) -> int:
    """El ancho de la barra vertical de una zona, si ya se ha visto alguna vez (si no, 0: no se gasta ese sitio). La
    primera vez que aparece, la zona pide ese ancho de más (y lo sigue pidiendo: así no baila)."""
    pol = zona.verticalScrollBarPolicy()
    if pol == Qt.ScrollBarAlwaysOff:
        return 0
    sb = zona.verticalScrollBar()
    if not getattr(zona, "_vigila_barra", False):
        zona._vigila_barra = True
        zona._con_barra = False

        def rango(_a, b, z=zona):
            try:
                if b > 0 and not z._con_barra:
                    z._con_barra = True
                    z.updateGeometry()
                    if z.parentWidget() is not None:
                        z.parentWidget().updateGeometry()
            except RuntimeError:
                pass
        sb.rangeChanged.connect(rango)
        zona._con_barra = sb.maximum() > 0
    if pol == Qt.ScrollBarAlwaysOn or zona._con_barra:
        return zona.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, zona)
    return 0


class ZonaPanel(QScrollArea):
    """La zona con desplazamiento VERTICAL de cada panel. Nunca deja el panel más estrecho que lo que su contenido
    (adaptado) necesita —así nada se corta por la derecha— y, si hay sitio, tampoco más estrecho que «preferido»."""

    def __init__(self, contenido: QWidget, preferido: int = 0):
        super().__init__()
        self.preferido = preferido
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(contenido)
        lay = contenido.layout()
        if lay is not None:                           # (márgenes de los lados pequeños: más sitio para el contenido)
            m = lay.contentsMargins()
            if m.left() > 4 or m.right() > 4:
                lay.setContentsMargins(min(m.left(), 4), m.top(), min(m.right(), 4), m.bottom())

    def necesita(self) -> int:
        """Lo mínimo para que el contenido quepa a lo ancho (con su barra vertical)."""
        w = self.widget()
        if w is None:
            return 0
        return max(w.minimumSizeHint().width(), w.minimumWidth()) + _barra(self) + 2 * self.frameWidth() + 1

    def minimumSizeHint(self):
        base = super().minimumSizeHint()
        return QSize(max(self.preferido, self.necesita()), base.height())

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(max(base.width(), self.minimumSizeHint().width()), base.height())

    def eventFilter(self, obj, ev):
        if obj is self.widget() and ev.type() == QEvent.LayoutRequest:
            self.updateGeometry()                     # (el contenido pide otro ancho: el panel también)
        return super().eventFilter(obj, ev)

    def poner_preferido(self, px: int):
        if px != self.preferido:
            self.preferido = px
            self.updateGeometry()
            if self.parentWidget() is not None:
                self.parentWidget().updateGeometry()   # (el panel lo nota al momento, no en la próxima vuelta)


def ancho_minimo(raiz: QWidget) -> int:
    """Lo mínimo que pide raiz de ancho (ya adaptado)."""
    return raiz.minimumSizeHint().width()


__all__ = ["adaptar", "adaptar_una_vez", "es_multilinea", "es_desplegable_que_acorta", "partir", "ancho_minimo"]
