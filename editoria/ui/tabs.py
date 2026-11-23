"""
Subpestañas dentro de un panel (como Resolve: todo detrás de pestañas, sin una columna eterna de cosas).

  tabbed([(título, [widgets…]), …]) -> QTabWidget   (cada página se desplaza sola si no cabe)
  explain(label, target)  → la explicación pasa a la ayuda emergente de target y el texto se esconde
  sections([(título, widget, abierta), …]) → secciones plegables (▾/▸) una debajo de otra
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget


# Icono de cada sección (las que tenían pestaña: el nombre sigue igual para el código, el icono solo se ve)
ICONO_SECCION = {"Transcribir": "🎙", "Limpiar": "🧹", "Sugerencias": "💡", "Inicio": "🏠", "Temas": "🗂",
                 "B-roll": "🎬", "Zooms": "🔍", "Audio": "🔊", "Director": "🎞", "Imagen": "🖼",
                 "Transiciones": "🔀", "Sonidos": "🔉", "Letra": "🔤", "Colores": "🎨", "Posición": "📍",
                 "Animación": "✨"}


def tabbed(pages, name: str = "subtabs", clave: str = ""):
    """Las partes de un panel, una debajo de otra y plegables (clic en su título = abrir o cerrar; se recuerda).
    Antes eran subpestañas: se usa igual que un QTabWidget (count, tabText, setCurrentIndex = abrir esa parte…).
    (título, [widgets…], True) = el último widget ocupa todo el alto que sobre."""
    esc = Escalonado(clave or name)
    esc.setObjectName(name)
    for page in pages:
        title, widgets = page[0], page[1]
        grow = len(page) > 2 and page[2]
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(2, 2, 2, 6)
        v.setSpacing(6)
        ws = [w for w in widgets if w is not None]
        for i, w in enumerate(ws):
            v.addWidget(w, 1 if (grow and i == len(ws) - 1) else 0)
        esc.addTab(inner, title, grow=bool(grow))
    return esc


class Escalonado(QWidget):
    """Secciones plegables apiladas de arriba abajo, con la forma de usar de un QTabWidget (para no cambiar el código
    que las abre): setCurrentIndex(i) abre la sección i (las demás siguen como estén) y la trae a la vista."""
    from PySide6.QtCore import Signal as _Signal
    currentChanged = _Signal(int)

    def __init__(self, clave: str = ""):
        from PySide6.QtWidgets import QSizePolicy
        super().__init__()
        self._clave = clave
        self._secs: list = []                       # [Section] en orden
        self._grow: list = []
        self._actual = 0
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 2, 0, 2)
        self._v.setSpacing(4)
        self._v.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    # ---- como QTabWidget
    def count(self) -> int:
        return len(self._secs)

    def widget(self, i: int):
        return self._secs[i]._pagina if 0 <= i < len(self._secs) else None

    def indexOf(self, w) -> int:
        for i, s in enumerate(self._secs):
            if s._pagina is w or s is w:
                return i
        return -1

    def tabText(self, i: int) -> str:
        return self._secs[i]._titulo if 0 <= i < len(self._secs) else ""

    def setTabText(self, i: int, t: str):
        if 0 <= i < len(self._secs):
            self._secs[i]._titulo = t
            self._secs[i].head.setText(self._con_icono(t))

    def tabToolTip(self, i: int) -> str:
        return self._secs[i].head.toolTip() if 0 <= i < len(self._secs) else ""

    def setTabToolTip(self, i: int, t: str):
        if 0 <= i < len(self._secs):
            self._secs[i].head.setToolTip(t)

    def setTabVisible(self, i: int, on: bool):
        if 0 <= i < len(self._secs):
            self._secs[i].setVisible(on)

    def isTabVisible(self, i: int) -> bool:
        return 0 <= i < len(self._secs) and not self._secs[i].isHidden()

    def setTabEnabled(self, i: int, on: bool):
        if 0 <= i < len(self._secs):
            self._secs[i].setEnabled(on)

    def currentIndex(self) -> int:
        return self._actual if self._secs else -1

    def currentWidget(self):
        return self.widget(self._actual)

    def setCurrentWidget(self, w):
        i = self.indexOf(w)
        if i >= 0:
            self.setCurrentIndex(i)

    def setCurrentIndex(self, i: int):
        if not 0 <= i < len(self._secs):
            return
        s = self._secs[i]
        s.set_open(True, save=False)                # (lo abre el código: solo se recuerda lo que abres tú)
        self._estirar()
        cambia = i != self._actual
        self._actual = i
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._a_la_vista(s))
        if cambia:
            self.currentChanged.emit(i)

    def addTab(self, w, title: str, grow: bool = False) -> int:
        return self.insertTab(len(self._secs), w, title, grow)

    def insertTab(self, i: int, w, title: str, grow: bool = False) -> int:
        from PySide6.QtWidgets import QScrollArea
        if isinstance(w, QScrollArea) and w.widgetResizable() and w.widget() is not None:
            w = w.takeWidget()                      # (ya se desplaza todo el panel: sin barra dentro de otra)
        i = max(0, min(i, len(self._secs)))
        limpio = __import__("re").sub(r"[^\wáéíóúñü ]+", "", title, flags=__import__("re").I).strip() or title
        sec = Section(self._con_icono(title), w, i == 0 and not self._secs,
                      f"secciones/{self._clave}/{limpio}" if self._clave else "")
        sec._titulo, sec._pagina = title, w
        sec.abierta.connect(lambda on, s=sec: self._abierta(s, on))
        self._secs.insert(i, sec)
        self._grow.insert(i, grow)
        self._v.insertWidget(i, sec)
        if i <= self._actual and len(self._secs) > 1:
            self._actual += 1
        self._estirar()
        return i

    def removeTab(self, i: int):
        if 0 <= i < len(self._secs):
            s = self._secs.pop(i)
            self._grow.pop(i)
            self._v.removeWidget(s)
            s.hide()
            s.deleteLater()
            if self._actual >= len(self._secs):
                self._actual = max(0, len(self._secs) - 1)
            elif i < self._actual:
                self._actual -= 1
            self._estirar()

    def setDocumentMode(self, *_a):
        pass

    def setUsesScrollButtons(self, *_a):
        pass

    def secciones(self) -> list:
        return list(self._secs)

    # ---- por dentro
    @staticmethod
    def _con_icono(t: str) -> str:
        ic = ICONO_SECCION.get(t)
        return f"{ic}  {t}" if ic and not t.startswith(ic) else t

    def _abierta(self, s, on: bool):
        if on:
            i = self._secs.index(s) if s in self._secs else -1
            if i >= 0 and i != self._actual:
                self._actual = i
                self.currentChanged.emit(i)
        self._estirar()

    def quiere_crecer(self) -> bool:
        """¿Aprovecha alto extra? Solo si tiene abierta una sección que crece y que de verdad enseña algo que crece
        (una lista, un texto…): con sus subsecciones plegadas, no (el usuario, 20/11: con «Efectos» abierta y todo
        plegado quedaba un hueco enorme antes de «Filtros»)."""
        return any(self._grow[k] and s.is_open() and not s.isHidden() and quiere_crecer(s._pagina)
                   for k, s in enumerate(self._secs))

    def _revisar_crecer(self):
        """(lo llama avisar_contenido: algo de dentro se plegó, se abrió o cambió) → se reparte otra vez el alto."""
        t = getattr(self, "_t_crecer", None)
        if t is None:
            from PySide6.QtCore import QTimer
            t = self._t_crecer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(0)
            t.timeout.connect(self._estirar)
        t.start()

    def _estirar(self):
        """La sección que crece (listas largas) se queda con el alto que sobra; si no hay ninguna abierta —o la abierta
        solo tiene subsecciones plegadas—, el hueco va al final: las secciones, arriba y seguidas, sin huecos."""
        alguna = False
        for k, s in enumerate(self._secs):
            crece = self._grow[k] and s.is_open() and quiere_crecer(s._pagina)
            alguna |= crece
            self._v.setStretch(k, 1 if crece else 0)
        self._v.setStretch(len(self._secs), 0 if alguna else 1)
        avisar_contenido(self.parentWidget())       # (el Escalonado o el panel de fuera reparten también)

    def _a_la_vista(self, s):
        from PySide6.QtWidgets import QScrollArea
        p = self.parentWidget()
        while p is not None and not isinstance(p, QScrollArea):
            p = p.parentWidget()
        if p is not None:
            try:
                p.ensureWidgetVisible(s.head, 0, 0)
            except RuntimeError:
                pass


def quiere_crecer(w: QWidget) -> bool:
    """¿Hay en w, a la vista, algo que aproveche alto extra (una lista, un texto largo, una tabla…)? Los espaciadores y
    las zonas con desplazamiento que solo envuelven otro contenido no cuentan; dentro de un Escalonado decide él (sus
    secciones plegadas o que no crecen no piden alto). Lo usan los Escalonados, los paneles agrupados (Acordeon) y la
    ventana para dar el alto libre a lo que lo usa y ceder el resto (sin huecos)."""
    from PySide6.QtWidgets import QAbstractScrollArea, QScrollArea, QSizePolicy
    if w is None:
        return False
    if isinstance(w, Escalonado):
        return w.quiere_crecer()
    mira = getattr(w, "quiere_crecer", None)
    if callable(mira):
        return bool(mira())
    vistos: dict = {}
    for a in w.findChildren(QAbstractScrollArea):
        if isinstance(a, QScrollArea) or not a.isVisibleTo(w):
            continue
        if a.maximumHeight() < 2000 or not (a.sizePolicy().verticalPolicy().value & QSizePolicy.PolicyFlag.ExpandFlag.value):
            continue                                 # (alto fijo o que no crece: no aprovecha más)
        p, esc = a.parentWidget(), None
        while p is not None and p is not w:
            if isinstance(p, Escalonado):
                esc = p                              # (el más de fuera dentro de w)
            p = p.parentWidget()
        if esc is None:
            return True
        if esc not in vistos:
            vistos[esc] = esc.quiere_crecer()
        if vistos[esc]:
            return True
    return False


def avisar_contenido(w: QWidget | None):
    """Algo se plegó, se abrió o cambió de tamaño dentro de w: el primero de fuera que reparte alto (un Escalonado, un
    panel agrupado, la ventana) lo vuelve a repartir."""
    while w is not None:
        f = getattr(w, "_revisar_crecer", None)
        if callable(f):
            f()
            return
        w = w.parentWidget()


def explain(label: QLabel, target: QWidget):
    """Sin textos largos a la vista: la explicación se ve al pasar el ratón por target."""
    text = label.text()
    old = target.toolTip()
    target.setToolTip(text if not old else old + "\n\n" + text)
    label.hide()


def untitle(*groups):
    """Las cajas ya están en su sección (con su título): el título y el marco sobran (y así cabe más estrecho)."""
    from .diseno import grupo_sin_titulo
    for g in groups:
        g.setTitle("")
        g.setFlat(True)
        grupo_sin_titulo(g)                          # (sin el hueco que reservaba el título)
        lay = g.layout()
        if lay is not None:
            lay.setContentsMargins(2, 2, 2, 2)


# ------------------------------------------------------------------ secciones plegables (▾ / ▸)
from PySide6.QtCore import Signal as _Signal  # noqa: E402


class Section(QWidget):
    """Una sección con su cabecera: clic en la flecha = mostrar u ocultar (una debajo de otra, como Resolve)."""
    abierta = _Signal(bool)                         # (se abrió o se cerró, la abra quien la abra)

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
        from . import diseno as D                   # (🎨 LA cabecera de sección: 24 px, como el acordeón y el Inspector)
        D.cabecera_estandar(self.head, "QToolButton#sectionhead")
        self.head.toggled.connect(self._clic)       # (clic del usuario: se abre o cierra y se recuerda)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(self.head)
        # (una sola rejilla: el contenido, con SANGRIA_SECCION bajo su cabecera; las secciones de dentro quedan así
        #  un poco más a la derecha que las de fuera, con el mismo alto)
        self._marco = QWidget()
        mv = D.fila_fija(QHBoxLayout(self._marco))   # (la sangría con un espacio fijo: responsive recorta los márgenes)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        D.espacio_sangria(mv)                        # (cede si no hay ancho; se rehace al cambiar «Letra»)
        mv.addWidget(body, 1)
        v.addWidget(self._marco, 1)
        self.set_open(opened, save=False)

    def is_open(self) -> bool:
        return self.head.isChecked()

    def _clic(self, on: bool):
        self.set_open(on, save=True)

    def set_open(self, on: bool, save: bool = True):
        """Abre o cierra. save=True solo cuando lo hace el usuario (lo que abre el código no se recuerda)."""
        from PySide6.QtCore import QSettings, Qt
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        if self.head.isChecked() != on:
            self.head.blockSignals(True)
            self.head.setChecked(on)
            self.head.blockSignals(False)
        cambia = self.body.isHidden() == on
        self.body.setVisible(on)
        marco = getattr(self, "_marco", None)
        if marco is not None and marco.isHidden() == on:
            marco.setVisible(on)                    # (plegada: sin el hueco de la separación)
        if save and self._key:
            QSettings("EditorIA", "EditorIA").setValue(self._key, on)
        if cambia:
            self.abierta.emit(on)


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


class _Espejo(QWidget):
    """(interno) Hace que la sección se oculte cuando el código oculta su grupo (y vuelva al mostrarlo)."""

    def __init__(self, sec, grupo):
        super().__init__(sec)
        self.sec, self.grupo = sec, grupo
        self.hide()
        grupo.installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.grupo and ev.type() in (QEvent.HideToParent, QEvent.ShowToParent):
            self.sec.setVisible(not self.grupo.isHidden())
        return False


def plegar_grupos(pagina: QWidget, clave: str, abiertas=()) -> list:
    """Cada grupo con título (QGroupBox) que está directamente en la página pasa a ir detrás de su título, plegable
    como en Resolve: clic en la cabecera = abrir o cerrar; se recuerda cómo lo dejas (clave). Si el código oculta el
    grupo, se oculta también su sección. Devuelve las secciones creadas."""
    import re
    from PySide6.QtWidgets import QGroupBox
    lay = pagina.layout()
    if lay is None:
        return []
    hechas = []
    from .responsive import widgets_en               # (sin itemAt: ver «lo que hay en un layout» en responsive.py)
    for w in widgets_en(lay):
        i = lay.indexOf(w)
        if not isinstance(w, QGroupBox) or not w.title() or i < 0:
            continue
        titulo = w.title()
        limpio = re.sub(r"[^\wáéíóúñü ]+", "", titulo, flags=re.I).strip() or titulo
        oculto = w.isHidden()
        lay.removeWidget(w)
        w.setTitle("")
        w.setFlat(True)
        from .diseno import grupo_sin_titulo
        grupo_sin_titulo(w)                           # (sin el hueco que reservaba el título)
        caja = QWidget()                              # (lo que se pliega; el grupo dentro, con su propia visibilidad)
        cv = QVBoxLayout(caja)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(w)
        sec = Section(titulo, caja, titulo in abiertas, f"{clave}/{limpio}")
        sec._espejo = _Espejo(sec, w)
        sec.grupo = w
        if oculto:
            sec.setVisible(False)
        lay.insertWidget(i, sec)
        hechas.append(sec)
    return hechas
