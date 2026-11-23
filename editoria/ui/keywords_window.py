"""
🔑 Ventana amplia de palabras clave (aparte, para no quitar sitio a la edición):

  izquierda:  🌐 buscar en internet (solo si este equipo tiene esa parte; si no, se explica)
  derecha:    las palabras clave con 👍 / 👎 (👍 = palabra clave: se le crea su carpeta · 👎 = no lo es)
              y, de la palabra elegida, su carpeta en dos partes:
                · 🌐 Descargado de internet (lo bajado, con sus créditos)  → 🗑 borrar elegidos / todo lo de la palabra
                · 💻 De tu computadora (copiado o 🔗 enlazado)             → 🗑 quitar (lo enlazado solo se desvincula)
                  arrastrar lo descargado a «💻 De tu computadora» (o clic derecho → «💻 Pasar a mi computadora…»)
                  lo MUEVE a una carpeta tuya (se pregunta cuál) y queda 🔗 enlazado a la misma palabra
              ⌫ Retroceso borra lo elegido (Supr ya no borra nada aquí).
              arriba, «🧹 Borrar todo lo descargado…» de todas las palabras (con cuánto ocupa).

Todo lo borrado va a la Papelera de Windows (se puede recuperar); los archivos enlazados del PC nunca se borran.
La lógica de buscar, bajar y poner en la línea de tiempo es la del panel «🔑 Palabras clave» (clips_panel): esta
ventana solo la muestra en grande.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..ai import keyword_glossary as KG
from ..core import keyword_folders as KF
from . import diseno as _D
from .jobs import BackgroundJob

ESTADOS = [("todas", "Todas"), ("?", "Por decidir"), ("si", "👍 Me gustan (con carpeta)"), ("no", "👎 No me gustan")]


def creditos_de(ruta: str) -> str:
    return os.path.splitext(ruta)[0] + ".creditos.json"


def es_de_internet(ruta: str) -> bool:
    """Lo bajado de internet lleva al lado su «.creditos.json» (lo escribe la descarga)."""
    return os.path.isfile(creditos_de(ruta))


def propio(ruta: str, car: dict | None) -> bool:
    """¿Está dentro de la subcarpeta PROPIA de la palabra (la de Reclaimer)? Solo eso se puede mandar a la Papelera."""
    own = (car or {}).get("own_path")
    if not own:
        return False
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(ruta)),
                                   os.path.normcase(os.path.abspath(own))]) == os.path.normcase(os.path.abspath(own))
    except ValueError:                      # (otra unidad)
        return False


def partes(car: dict | None) -> tuple[list[str], list[str]]:
    """(descargado de internet, de tu computadora) de la carpeta de una palabra."""
    if not car:
        return [], []
    enlazados = set(car.get("linked_files") or [])
    net = [f for f in car["files"] if f not in enlazados and propio(f, car) and es_de_internet(f)]
    pc = [f for f in car["files"] if f not in net]
    return net, pc


def _mb(rutas: list[str]) -> float:
    total = 0
    for r in rutas:
        try:
            total += os.path.getsize(r)
        except OSError:
            pass
    return total / (1024 * 1024)


def _sin_palabra() -> list[str]:
    """Lo bajado que se quedó en la carpeta «Descargas» de Reclaimer (sin carpeta de palabra)."""
    from .descargas_panel import _descargas_dir, archivos_de
    d = _descargas_dir()
    return archivos_de(str(d), False, hondo=3) if d.is_dir() else []


def a_papelera_con_creditos(rutas: list[str]) -> tuple[int, int]:
    """Cada archivo a la Papelera de Windows (recuperable) y, detrás, su «.creditos.json». → (hechos, no se pudieron:
    abiertos en otro programa, normalmente). Un «.creditos.json» suelto (su video ya no está) también va."""
    from .clips_panel import _a_papelera
    hechos = fallos = 0
    for ruta in rutas:
        if not os.path.exists(ruta):
            continue
        try:
            ok = _a_papelera(ruta)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            fallos += 1
            continue
        hechos += 1
        cred = creditos_de(ruta)
        if not ruta.endswith(".creditos.json") and os.path.isfile(cred):
            try:
                _a_papelera(cred)
            except Exception:  # noqa: BLE001
                pass
    return hechos, fallos


def texto_fallos(fallos: int) -> str:
    """El aviso de una línea cuando Windows no deja mover algo."""
    return (f"{fallos} no se pudieron mandar a la Papelera: están abiertos en otro programa (ciérralo y vuelve a "
            "probar)." if fallos else "")


def creditos_huerfanos(carpetas: list[str]) -> list[str]:
    """Los «.creditos.json» cuyo video ya no está (lo borraste fuera de Reclaimer, o quedó de antes): basura."""
    out = []
    for base in carpetas:
        if not base or not os.path.isdir(base):
            continue
        for d, _subs, nombres in os.walk(base):
            tallos = {os.path.splitext(n)[0] for n in nombres if not n.endswith(".creditos.json")}
            for n in nombres:
                if n.endswith(".creditos.json") and n[:-len(".creditos.json")] not in tallos:
                    out.append(os.path.join(d, n))
    return out


class _BotonCuenta(_D.BotonIcono):
    """El icono de «Descargas en cola» con su cuenta pequeña encima cuando hay algo bajando (y en el tooltip)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._cuenta = 0

    def poner_cuenta(self, n: int):
        n = max(0, int(n or 0))
        if n != self._cuenta:
            self._cuenta = n
            self.update()

    def paintEvent(self, ev):                  # noqa: N802
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont, QPainter
        D = _D
        super().paintEvent(ev)
        n = self._cuenta
        if not n:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(max(8, self.height() // 3))
        f.setBold(True)
        p.setFont(f)
        txt = str(n) if n < 100 else "99+"
        w = max(p.fontMetrics().horizontalAdvance(txt) + 4, p.fontMetrics().height())
        caja = QRectF(self.width() - w, 0, w, p.fontMetrics().height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(D.colores().get("acento", "#e07a2e")))
        p.drawRoundedRect(caja, caja.height() / 2, caja.height() / 2)
        p.setPen(QColor("white"))
        p.drawText(caja, Qt.AlignCenter, txt)
        p.end()


def borrar_todo_descargado(panel, parent, preguntar: bool = True, sin_palabra: bool = True) -> int:
    """🧹 Todo lo bajado de internet a la Papelera de Windows (se puede recuperar), con sus créditos: lo de cada
    palabra (su «.creditos.json» lo distingue de lo tuyo) y, con sin_palabra, lo que quedó en la carpeta «Descargas» de
    Reclaimer. Lo de tu computadora (copiado o enlazado) nunca se toca. Devuelve cuántos archivos fueron.
    (22/11) También los «.creditos.json» sueltos, cuyo video ya no está; y si Windows no deja mover alguno (abierto
    en otro programa), lo dice en una línea."""
    from .descargas_panel import _descargas_dir
    panel._leer_carpetas()
    de_palabras = []
    for car in panel.carpetas:
        de_palabras += partes(car)[0]
    sueltos = [r for r in (_sin_palabra() if sin_palabra else []) if r not in de_palabras]
    rutas = de_palabras + sueltos
    bases = [car.get("own_path") for car in panel.carpetas] + ([str(_descargas_dir())] if sin_palabra else [])
    huerfanos = creditos_huerfanos(bases)
    if not rutas and not huerfanos:
        panel._aviso("No hay nada descargado de internet que borrar.")
        return 0
    if not rutas:                              # (solo quedaban créditos sueltos: se limpian sin más preguntas)
        a_papelera_con_creditos(huerfanos)
        panel.recalcular()
        panel._aviso("No hay nada descargado de internet que borrar (quité sus créditos sueltos).")
        return 0
    if preguntar:
        p = panel.ctrl.project
        ns = {os.path.normcase(os.path.abspath(r)) for r in rutas}
        usados = sum(1 for m in p.media.values()
                     if os.path.normcase(os.path.abspath(m.path)) in ns and p.is_media_used(m.id))
        detalle = f"· de tus palabras: {len(de_palabras)}" + (f"\n· sin palabra (carpeta «Descargas» de Reclaimer): "
                                                            f"{len(sueltos)}" if sueltos else "")
        r = QMessageBox.question(
            parent, "Borrar todo lo descargado",
            f"¿Mandar a la Papelera los {len(rutas)} archivos bajados de internet ({_mb(rutas):.0f} MB)?\n{detalle}"
            "\n\nLo de tu computadora no se toca. Se puede recuperar desde la Papelera."
            + (f"\n⚠ {usados} están en tu proyecto: se quedarán sin archivo." if usados else ""),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if r != QMessageBox.Yes:
            return 0
    hechos, fallos = a_papelera_con_creditos(rutas)
    a_papelera_con_creditos(creditos_huerfanos(bases))
    panel.recalcular()
    panel._aviso(f"🧹 {hechos} archivo(s) descargado(s) a la Papelera." + (" " + texto_fallos(fallos) if fallos
                                                                           else ""))
    return hechos


class KeywordsWindow(QWidget):
    def __init__(self, panel, parent=None, acoplado: bool = False):
        # acoplado=True: la pestaña «🗂 Carpetas» de la derecha (sin internet ni lista: sigue a «Dijiste…»)
        if acoplado:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.Window)
        self.acoplado = acoplado
        self._firma_vista = None           # (palabra, archivos) que se ve ahora: si no cambia, no se repinta
        self.p = panel
        self.ctrl = panel.ctrl
        self.setWindowTitle("🔑 Palabras clave · carpetas e internet")
        self._net = None                   # la parte de internet del panel, mientras esta ventana está abierta
        self._tok = 0
        self._job = None
        self._items: dict[str, QListWidgetItem] = {}
        self.term = ""
        self._nombres: dict[str, str] = {}  # clave → cómo se escribe (el glosario «no» solo guarda la clave)
        self._construir()

    # ------------------------------------------------------------------ interfaz
    def _construir(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split)

        izq = self._izq = QWidget()
        iv = QVBoxLayout(izq)
        iv.setContentsMargins(0, 0, 6, 0)
        t = QLabel("<b>🌐 Buscar en internet</b>")
        iv.addWidget(t)
        self.lbl_net = QLabel()
        self.lbl_net.setWordWrap(True)
        self.lbl_net.setObjectName("dim")
        iv.addWidget(self.lbl_net)
        self.net_lay = QVBoxLayout()
        iv.addLayout(self.net_lay, 1)
        split.addWidget(izq)

        der = QWidget()
        dv = QVBoxLayout(der)
        dv.setContentsMargins(6, 0, 0, 0)
        self._fila_palabras = QWidget()        # (ventana amplia: el título de la lista y su filtro)
        fila = QHBoxLayout(self._fila_palabras)
        fila.setContentsMargins(0, 0, 0, 0)
        self._lbl_palabras = QLabel("<b>🔑 Tus palabras clave</b>")
        fila.addWidget(self._lbl_palabras)
        self.filtro = QComboBox()
        for dato, texto in ESTADOS:
            self.filtro.addItem(texto, dato)
        self.filtro.setToolTip("Qué palabras ver: las que aún no decidiste, las que te gustan o las que no")
        self.filtro.currentIndexChanged.connect(lambda _i: self.refrescar())
        fila.addWidget(self.filtro)
        fila.addStretch(1)
        dv.addWidget(self._fila_palabras)

        cuerpo = QSplitter(Qt.Horizontal)
        col = self._col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lista.setToolTip("👍 = palabra clave (tiene carpeta) · 👎 = no lo es · ○ = por decidir. "
                              "Elige una para ver su carpeta. Clic derecho = separar o unir sus variantes.")
        self.lista.currentItemChanged.connect(lambda it, _p: self._elegir(it))
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(lambda pos: self._menu_lista(pos))
        cv.addWidget(self.lista, 1)
        botones = QHBoxLayout()
        self.btn_si = QPushButton("👍 Me gusta")
        self.btn_si.setToolTip("Es palabra clave: se guarda en el glosario y se le crea su carpeta")
        self.btn_si.clicked.connect(lambda: self.marcar("si"))
        self.btn_no = QPushButton("👎 No")
        self.btn_no.setToolTip("No es palabra clave: deja de proponerse (su carpeta, si la tiene, no se borra)")
        self.btn_no.clicked.connect(lambda: self.marcar("no"))
        self.btn_nada = QPushButton("↺")
        self.btn_nada.setFixedWidth(34)
        self.btn_nada.setToolTip("Volver a «por decidir»")
        self.btn_nada.clicked.connect(lambda: self.marcar("?"))
        for b in (self.btn_si, self.btn_no, self.btn_nada):
            botones.addWidget(b)
        cv.addLayout(botones)
        cuerpo.addWidget(col)

        car = QWidget()
        kv = QVBoxLayout(car)
        kv.setContentsMargins(6, 0, 0, 0)
        # 🧭 (22/11, «acomodarlo para que se vea mejor») UNA cabecera: a la izquierda qué se ve (segmentado: «Esta
        # palabra | Todo lo descargado»; con poco ancho, solo sus iconos) y a la derecha sus acciones, iconos
        # monocromos con su nombre en el tooltip: Descargas en cola (con su cuenta) · Abrir la carpeta · Recargar ·
        # Borrar todo lo descargado…
        from PySide6.QtWidgets import QButtonGroup, QSizePolicy, QToolButton
        from . import diseno as _Dk
        from .clips_panel import HAY_INTERNET as _HAY
        from .clips_panel import _Segmentado
        vista = QHBoxLayout()
        vista.setSpacing(4)
        self._sel_vista = _Segmentado()
        sl = QHBoxLayout(self._sel_vista)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self._sel_vista.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)   # (no crece: el sitio, a los iconos)
        self._grupo_vista = QButtonGroup(self)
        self._grupo_vista.setExclusive(True)
        for nombre, texto, icono, tip in (
                ("btn_vista_palabra", "Esta palabra", "tag",
                 "La carpeta de la palabra elegida en «Dijiste…»: lo descargado y lo de tu computadora"),
                ("btn_vista_todo", "Todo lo descargado", "download",
                 "Todo lo que Reclaimer ha bajado de internet (clips de cada palabra y sin palabra, sonidos e "
                 "imágenes), con su miniatura y su duración")):
            b = QToolButton(self._sel_vista)
            b.setText(texto)
            b.setIcon(_Dk.icono(icono))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setProperty("segmento", nombre)
            self._grupo_vista.addButton(b)
            sl.addWidget(b)
            self._sel_vista.botones.append(b)
            setattr(self, nombre, b)
        self.btn_vista_palabra.setChecked(True)
        vista.addWidget(self._sel_vista)           # (los iconos, pegados a la derecha, se quedan el resto del ancho)
        self.btn_descargas = _BotonCuenta("download", "Descargas en cola: se ven en «Buscar material». Clic = ir allí")
        self.btn_descargas.clicked.connect(lambda: hasattr(self.p, "ver_descargas") and self.p.ver_descargas())
        self.btn_descargas.setVisible(_HAY)
        self.btn_abrir = _Dk.BotonIcono("folder-open", "Abrir la carpeta en el Explorador: la de la palabra o, en "
                                                       "«Todo lo descargado», la elegida")
        self.btn_abrir.clicked.connect(self._abrir_cabecera)
        self.btn_recargar = _Dk.BotonIcono("refresh-cw", "Recargar: vuelve a leer las carpetas")
        self.btn_recargar.clicked.connect(self._recargar)
        self.btn_limpiar = _Dk.BotonIcono(
            "trash-2", "Borrar todo lo descargado…: manda a la Papelera todo lo bajado de internet, de TODAS las "
                       "palabras y lo que quedó sin palabra (lo de tu computadora no se toca). Antes pregunta y dice "
                       "cuánto ocupa.")
        # (con lambda: clicked(bool) pasaba «False» a «preguntar» y se borraba SIN preguntar)
        self.btn_limpiar.clicked.connect(lambda: self.borrar_todo_descargado(True, True))
        self._iconos_cab = _Dk.FilaFluida(espacio=4, alinear_derecha=True)   # (sin sitio: siguen en otra línea)
        for b in (self.btn_descargas, self.btn_abrir, self.btn_recargar, self.btn_limpiar):
            self._iconos_cab.addWidget(b)
        vista.addWidget(self._iconos_cab, 1)
        self.btn_vista_todo.toggled.connect(self._cambiar_vista)
        kv.addLayout(vista)
        self._vista_palabra = QWidget()        # (lo de la palabra: título, botones, sus dos cajas y «poner»)
        kp = QVBoxLayout(self._vista_palabra)
        kp.setContentsMargins(0, 0, 0, 0)
        self.descargado = None                 # 📥 se crea la primera vez que se pide «Todo lo descargado»
        self._kv = kv
        kv.addWidget(self._vista_palabra, 1)
        kv = kp
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.titulo.setWordWrap(True)
        kv.addWidget(self.titulo)
        acc = QHBoxLayout()
        self.btn_buscar_net = QPushButton("🌐 Buscar en internet")
        self.btn_buscar_net.setToolTip("Busca clips de esta palabra (salen a la izquierda; lo que bajes va a su carpeta)")
        self.btn_buscar_net.clicked.connect(self.buscar_internet)
        self.btn_buscar_pc = QPushButton("💻 Buscar en tu computadora")
        self.btn_buscar_pc.setToolTip("Elige videos o imágenes de tu PC (o una carpeta entera) para esta palabra")
        self.btn_buscar_pc.clicked.connect(self._menu_pc)
        self.btn_borrar_palabra = QPushButton("🗑 Borrar palabra y carpeta…")    # («Abrir carpeta»: en la cabecera)
        self.btn_borrar_palabra.setToolTip("Manda su carpeta a la Papelera y quita sus enlaces (lo enlazado de tu PC "
                                           "no se borra)")
        self.btn_borrar_palabra.clicked.connect(lambda: self.borrar_palabra(True))   # (siempre pregunta)
        self.btn_buscar_net.setVisible(False)    # (repetido: la búsqueda está en «Buscar material» → 🌐 Internet)
        for b in (self.btn_buscar_pc, self.btn_borrar_palabra):
            acc.addWidget(b)
        acc.addStretch(1)
        kv.addLayout(acc)

        self.caja_net, self.grid_net = self._caja("🌐 Descargado de internet")
        self.grid_net.setToolTip("Doble clic = ponerlo en el cabezal · arrástralo a la línea de tiempo, o a «💻 De tu "
                                 "computadora» para moverlo a una carpeta tuya · clic derecho = más opciones · "
                                 "⌫ Retroceso = borrar")
        self.grid_net.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid_net.customContextMenuRequested.connect(self._menu_net)
        bn = QHBoxLayout()
        from . import diseno as _Dn
        self.btn_borrar_net = QPushButton("Borrar los elegidos")
        self.btn_borrar_net.setIcon(_Dn.icono("trash-2"))
        self.btn_borrar_net.clicked.connect(lambda: self.borrar(self._sel(self.grid_net)))
        self.btn_borrar_net_todo = QPushButton("Borrar todo lo descargado de esta palabra")
        self.btn_borrar_net_todo.setIcon(_Dn.icono("trash-2"))
        self.btn_borrar_net_todo.clicked.connect(lambda: self.borrar(partes(self._car())[0]))
        bn.addWidget(self.btn_borrar_net)
        bn.addWidget(self.btn_borrar_net_todo)
        bn.addStretch(1)
        self.caja_net.layout().addLayout(bn)
        kv.addWidget(self.caja_net, 1)

        self.caja_pc, self.grid_pc = self._caja("💻 De tu computadora")
        self.grid_pc.setToolTip("Doble clic = ponerlo en el cabezal · arrástralo a la línea de tiempo · suelta aquí lo "
                                "de «🌐 Descargado de internet» para moverlo a una carpeta de tu PC (te pregunta cuál) · "
                                "⌫ Retroceso = quitar")
        self.grid_pc.setAcceptDrops(True)                   # (soltar aquí: lo descargado pasa a tu computadora)
        self.grid_pc.viewport().setAcceptDrops(True)
        self.grid_pc.soltado.disconnect()
        self.grid_pc.soltado.connect(lambda rutas, _f: self._soltado_pc(rutas))
        bp = QHBoxLayout()
        self.btn_quitar_pc = QPushButton("🗑 Quitar los elegidos")
        self.btn_quitar_pc.setToolTip("Lo copiado va a la Papelera; lo 🔗 enlazado solo se desvincula (tu archivo "
                                      "sigue en su sitio)")
        self.btn_quitar_pc.clicked.connect(lambda: self.borrar(self._sel(self.grid_pc)))
        bp.addWidget(self.btn_quitar_pc)
        bp.addStretch(1)
        self.caja_pc.layout().addLayout(bp)
        kv.addWidget(self.caja_pc, 1)

        poner = QHBoxLayout()
        self.btn_cabezal = QPushButton("⏵ Poner en el cabezal")
        self.btn_cabezal.setToolTip("Pone los archivos elegidos donde está el cabezal (la línea roja)")
        self.btn_cabezal.clicked.connect(lambda: self.poner(True))
        self.btn_donde = QPushButton("📍 Poner donde lo dices")
        self.btn_donde.setToolTip("Pone los archivos elegidos donde dices esta palabra en la narración")
        self.btn_donde.clicked.connect(lambda: self.poner(False))
        poner.addWidget(self.btn_cabezal)
        poner.addWidget(self.btn_donde)
        poner.addStretch(1)
        kv.addLayout(poner)
        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self._kv.addWidget(self.aviso)
        cuerpo.addWidget(car)
        cuerpo.setStretchFactor(0, 1)
        cuerpo.setStretchFactor(1, 3)
        dv.addWidget(cuerpo, 1)
        split.addWidget(der)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        if self.acoplado:                      # (la lista y el 👍/👎 están en «Dijiste…»; internet, en su pestaña)
            for w in (self._izq, self._col, self._fila_palabras):
                w.hide()
            lay.setContentsMargins(4, 4, 4, 4)
            self.btn_buscar_net.setToolTip("Busca clips de esta palabra en la pestaña «🌐 Internet» de Palabras clave "
                                           "(lo que bajes va a su carpeta)")

    # ------------------------------------------------------------------ 📥 todo lo descargado
    def _ventana(self):
        """La ventana principal (la de Medios y la línea de tiempo), también si Carpetas o Palabras clave están
        sueltos (su window() es entonces el panel flotante: «Todo lo descargado» no veía las carpetas de las palabras
        ni podía poner nada en el cabezal)."""
        w = self.p.window()
        if hasattr(w, "ctrl") and hasattr(w, "clips"):
            return w
        from PySide6.QtWidgets import QApplication
        for top in QApplication.topLevelWidgets():
            if getattr(top, "clips", None) is self.p:
                return top
        return w

    def _abrir_cabecera(self):
        """📂 de la cabecera: en «Todo lo descargado», la carpeta elegida allí; si no, la de la palabra."""
        if self.btn_vista_todo.isChecked() and self.descargado is not None:
            self.descargado._abrir()
        elif self._car() is not None:
            self._abrir_carpeta()
        else:
            self._avisa("Esta palabra aún no tiene carpeta.")

    def _recargar(self):
        """⟳ de la cabecera: vuelve a leer las carpetas (las de las palabras y, si se ve, «Todo lo descargado»)."""
        if self.btn_vista_todo.isChecked() and self.descargado is not None:
            self.descargado.refrescar()
        else:
            self.p.recalcular()
            self.refrescar()

    def _despues_de_quitar(self):
        """«Todo lo descargado» mandó algo a la Papelera: las carpetas de las palabras, al día."""
        self.p.recalcular()
        self._firma_vista = None
        self.refrescar()

    def _todo_al_dia(self):
        """Algo se borró: «Todo lo descargado» vuelve a leer las carpetas (si ya existe)."""
        if self.descargado is not None:
            self.descargado.refrescar()

    def _cambiar_vista(self, todo: bool):
        if todo and self.descargado is None:
            from .descargas_panel import DescargasPanel
            self.descargado = DescargasPanel(self._ventana, incrustado=True)
            self.descargado.layout().setContentsMargins(0, 0, 0, 0)
            self.descargado.borrado.connect(self._despues_de_quitar)
            self._kv.insertWidget(self._kv.indexOf(self._vista_palabra) + 1, self.descargado, 1)
        self._vista_palabra.setVisible(not todo)
        if self.descargado is not None:
            self.descargado.setVisible(todo)
            if todo:
                self.descargado.refrescar()

    def ver_todo(self):
        """«Ver todo» (barra de Buscar material): Carpetas enseña todo lo descargado."""
        if not self.btn_vista_todo.isChecked():
            self.btn_vista_todo.setChecked(True)
        elif self.descargado is not None:
            self.descargado.refrescar()

    def _caja(self, titulo: str):
        from .clips_panel import MINI_H, MINI_W, _Lista
        caja = QGroupBox(titulo)
        v = QVBoxLayout(caja)
        g = _Lista(arrastrar=True)
        g.setViewMode(QListView.IconMode)
        g.setIconSize(QSize(MINI_W, MINI_H))
        g.setGridSize(QSize(MINI_W + 24, MINI_H + 40))
        g.setResizeMode(QListView.Adjust)
        g.setMovement(QListView.Static)
        g.setWordWrap(True)
        g.setSelectionMode(QAbstractItemView.ExtendedSelection)
        g.setToolTip("Doble clic = ponerlo en el cabezal · arrástralo a la línea de tiempo · ⌫ Retroceso = borrar")
        g.itemDoubleClicked.connect(lambda it: self.poner(True, [it.data(Qt.UserRole)]))
        g.soltado.connect(lambda rutas, _f: self._anadir(rutas))
        g.installEventFilter(self)                          # ⌫ Retroceso borra; Supr ya no (ver eventFilter)
        from .miniaturas import activar_vista_grande        # 🔍 vista grande al pasar el ratón (programador 2)
        activar_vista_grande(g, lambda it: it.data(Qt.UserRole))
        v.addWidget(g)
        return caja, g

    def _avisa(self, texto: str):
        self.aviso.setText(texto)

    # ------------------------------------------------------------------ abrir / cerrar
    def showEvent(self, e):
        super().showEvent(e)
        if not self.acoplado:
            self._tomar_internet()
            self.refrescar()
        else:
            # (acoplada, en pestaña con otros paneles: Qt la deja «visible» aunque su pestaña esté detrás, fuera de la
            # vista; solo se pone al día si de verdad se ve. Al elegir su pestaña: visibilityChanged → _al_verse)
            QTimer.singleShot(0, self._al_verse)

    def _al_verse(self):
        try:
            if not self.isVisible() or self.visibleRegion().isEmpty():
                return
        except RuntimeError:                   # (ya borrada)
            return
        self.p.ensure_fresh()                  # (el panel Palabras clave pudo estar oculto con un recálculo pendiente)
        self.refrescar()

    def closeEvent(self, e):
        self._devolver_internet()
        QSettings("EditorIA", "EditorIA").setValue("palabras_ventana/geom", self.saveGeometry())
        super().closeEvent(e)

    def hideEvent(self, e):
        self._devolver_internet()
        super().hideEvent(e)

    def _tomar_internet(self):
        """La parte de internet del panel se enseña aquí, en grande, mientras la ventana está abierta."""
        tabs = getattr(self.p, "pestanas", None)
        if self._net is None and tabs is not None and tabs.count() > 1:
            w = tabs.widget(1)
            tabs.removeTab(1)
            self.net_lay.addWidget(w)
            w.show()
            self._net = w
        if self._net is not None:
            self.lbl_net.setText("Elige una palabra a la derecha y pulsa «🌐 Buscar en internet» (o escribe tu "
                                 "búsqueda). Lo que bajes va a la carpeta de esa palabra.")
        else:
            self.lbl_net.setText("La búsqueda en internet no está instalada en este equipo. Puedes añadir tu "
                                 "material con «💻 Buscar en tu computadora».")

    def _devolver_internet(self):
        tabs = getattr(self.p, "pestanas", None)
        if self._net is not None and tabs is not None:
            tabs.insertTab(1, self._net, "🌐 Internet")
            self._net = None

    # ------------------------------------------------------------------ palabras
    def _palabras(self) -> list[dict]:
        """Las palabras de la narración, las que tienen carpeta y las del glosario, con su estado."""
        g = KG.load()
        todas: dict[str, dict] = {}

        def poner(term: str, veces: int = 0):
            k = KG.clave(term)
            if not k:
                return
            d = todas.setdefault(k, {"term": term, "veces": 0})
            d["veces"] = max(d["veces"], veces)

        for m in self.p.menciones:
            poner(m["term"], m.get("count", 0))
        for c in self.p.carpetas:
            poner(c["label"])
        for t in KG.yes_terms(g):
            poner(t)
        for k in g["no"]:                     # las de 👎 también (para verlas y deshacerlo)
            poner(self._nombres.get(k, k))
        for k, d in todas.items():
            self._nombres.setdefault(k, d["term"])
        out = []
        for k, d in todas.items():
            car = self.p._carpeta_de(d["term"])
            if k in g["no"]:
                estado = "no"
            elif k in g["si"] or car is not None:
                estado = "si"
            else:
                estado = "?"
            out.append(dict(d, clave=k, estado=estado, car=car))
        orden = {"si": 0, "?": 1, "no": 2}
        out.sort(key=lambda d: (orden[d["estado"]], -d["veces"], d["term"].lower()))
        return out

    def refrescar(self, leer: bool = True):
        if leer:
            self.p._leer_carpetas()
        if self.acoplado:                      # la palabra elegida en «Dijiste…»
            self.term = (self.p.mencion or {}).get("term") or ""
            self._mostrar()
            return
        filtro = self.filtro.currentData()
        actual = self.term
        from .clips_panel import texto_variantes
        dichas = {KG.clave(m["term"]): m for m in self.p.menciones if not m.get("no_dicha")}
        self.lista.blockSignals(True)
        self.lista.clear()
        fila = -1
        for d in self._palabras():
            if filtro != "todas" and d["estado"] != filtro:
                continue
            icono = {"si": "👍", "no": "👎", "?": "○"}[d["estado"]]
            n = d["car"]["count"] if d["car"] else 0
            partes_txt = [f"{icono}  {d['term']}"]
            if d["veces"]:
                partes_txt.append(f"· {d['veces']} {'vez' if d['veces'] == 1 else 'veces'}")
            if d["car"]:
                partes_txt.append(f"· 📁 {n}")
            it = QListWidgetItem(" ".join(partes_txt))
            it.setData(Qt.UserRole, d["term"])
            tambien = texto_variantes(dichas.get(d["clave"]) or {})
            if tambien:                        # «También dicho: …» (cómo se oyó esa palabra)
                it.setToolTip(tambien)
            if d["estado"] == "no":
                it.setForeground(QColor("#6b6f78"))
            self.lista.addItem(it)
            if KG.clave(d["term"]) == KG.clave(actual):
                fila = self.lista.count() - 1
        if self.lista.count():
            self.lista.setCurrentRow(fila if fila >= 0 else 0)
        self.lista.blockSignals(False)
        self._elegir(self.lista.currentItem())

    def elegir_palabra(self, term: str):
        """Deja elegida esa palabra (si el filtro la esconde, se pasa a «Todas»)."""
        if self.acoplado:
            p = self.p
            fila = next((i for i, m in enumerate(p.menciones) if KG.clave(m["term"]) == KG.clave(term)), -1)
            if fila >= 0:                      # así lo que bajes va a la misma palabra que se ve aquí
                p.elegir_indice(fila, buscar=False)
            else:
                self._seguir(term)
            return
        self.term = term
        if self.filtro.currentData() != "todas":
            self.filtro.setCurrentIndex(0)           # (refresca)
        else:
            self.refrescar()

    def _menu_lista(self, pos):
        """Clic derecho en una palabra: «✂ Separar…» y «🔗 Unir con…» (los mismos de «Dijiste…»)."""
        it = self.lista.itemAt(pos)
        if it is None:
            return
        term = it.data(Qt.UserRole)
        m = next((x for x in self.p.menciones if KG.clave(x["term"]) == KG.clave(term) and not x.get("no_dicha")),
                 None) or {"term": term, "variantes": []}
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self.p._menu_variantes(menu, m)
        menu.exec(self.lista.viewport().mapToGlobal(pos))

    def _terminos_elegidos(self) -> list[str]:
        its = self.lista.selectedItems() or ([self.lista.currentItem()] if self.lista.currentItem() else [])
        return [it.data(Qt.UserRole) for it in its if it is not None]

    def marcar(self, estado: str):
        terms = self._terminos_elegidos()
        if not terms:
            self._avisa("Elige antes una palabra de la lista.")
            return
        con_archivos = []
        try:
            for t in terms:
                if estado == "si":
                    KG.add_yes(t)
                    if self.p._carpeta_de(t) is None:
                        KF.create_folder(self.p.raiz, t)
                elif estado == "no":
                    KG.add_no(t)
                    car = self.p._carpeta_de(t)
                    if car and car["count"]:
                        con_archivos.append(t)
                else:
                    KG.remove(t)
        except OSError as exc:
            self._avisa(f"No pude guardarlo: {exc}")
            return
        self.term = terms[0]
        self.p.recalcular()
        self.refrescar()
        if estado == "si":
            self._avisa(f"👍 {', '.join(terms)}: ya es palabra clave y tiene su carpeta. Ahora busca su material "
                        "en internet o en tu computadora.")
        elif estado == "no":
            extra = (f" Su carpeta sigue ahí ({', '.join(con_archivos)}): bórrala con «🗑 Borrar palabra y "
                     "carpeta…» si ya no la quieres." if con_archivos else "")
            self._avisa(f"👎 {', '.join(terms)}: ya no se propone como palabra clave.{extra}")
        else:
            self._avisa(f"↺ {', '.join(terms)}: otra vez por decidir.")

    def _car(self) -> dict | None:
        return self.p._carpeta_de(self.term) if self.term else None

    def _seguir(self, term: str):
        """(acoplada) «Dijiste…» eligió otra palabra: se enseña su carpeta (solo si está a la vista)."""
        self.term = term
        if self.isVisible():
            self._mostrar()

    def _elegir(self, it):
        self.term = it.data(Qt.UserRole) if it is not None else ""
        self._mostrar()

    def _mostrar(self):
        car = self._car()
        firma = (self.term, tuple(car["files"]) if car else None)
        if self.acoplado and firma == self._firma_vista:
            return                             # (igual que antes: no se pierde lo elegido ni se rehacen miniaturas)
        self._firma_vista = firma
        hay = bool(self.term)
        for b in (self.btn_buscar_net, self.btn_buscar_pc):
            b.setEnabled(hay)
        self.btn_borrar_palabra.setEnabled(car is not None)
        if not hay:
            self.titulo.setText("Elige una palabra")                   # (20/11: una línea; el cómo, al tooltip)
            self.titulo.setToolTip("Elige una palabra en «Dijiste…» (o dale 👍 a una para crearle su carpeta)"
                                   if self.acoplado else "Elige una palabra (o dale 👍 a una para crearle su carpeta)")
        elif car is None:
            self.titulo.setText(f"«{self.term}» aún no tiene carpeta: dale 👍 o añade material y se crea sola.")
        else:
            self.titulo.setText(f"📁 {car['label']}  ·  {car['count']} archivo(s)")
            self.titulo.setToolTip(car["path"])
        net, pc = partes(car)
        self.caja_net.setTitle(f"🌐 Descargado de internet ({len(net)}" + (f" · {_mb(net):.0f} MB)" if net else ")"))
        self.caja_pc.setTitle(f"💻 De tu computadora ({len(pc)})")
        self.btn_borrar_net.setEnabled(bool(net))
        self.btn_borrar_net_todo.setEnabled(bool(net))
        self.btn_quitar_pc.setEnabled(bool(pc))
        self._pintar(net, pc, car)

    def _pintar(self, net: list[str], pc: list[str], car: dict | None):
        from .clips_panel import _miniatura_ruta
        self._tok += 1
        self._items = {}
        pendientes = []
        enlazados = set((car or {}).get("linked_files") or [])
        for grid, rutas in ((self.grid_net, net), (self.grid_pc, pc)):
            grid.clear()
            for r in rutas:
                it = QListWidgetItem(("🔗 " if r in enlazados else "") + os.path.basename(r))
                it.setData(Qt.UserRole, r)
                it.setToolTip(r + ("\nEnlazado de tu PC (no se copia; al quitarlo solo se desvincula)"
                                   if r in enlazados else ""))
                png = _miniatura_ruta(r)
                pm = QPixmap(png) if os.path.isfile(png) else QPixmap()
                if pm.isNull():
                    pendientes.append(r)
                else:
                    it.setIcon(QIcon(pm))
                grid.addItem(it)
                self._items[r] = it
        if pendientes:
            self._miniaturas(pendientes, self._tok)

    def _miniaturas(self, rutas: list[str], tok: int):
        from .clips_panel import _hacer_miniatura, _miniatura_ruta
        if self._job is not None:
            self._job.cancel()

        def trabajo(progreso, cancelado, emitir):
            for r in rutas:
                if cancelado():
                    return None
                salida = _miniatura_ruta(r)
                if _hacer_miniatura(r, salida):
                    emitir((r, salida))
            return None

        def llego(par, t=tok):
            if t != self._tok:
                return
            it = self._items.get(par[0])
            pm = QPixmap(par[1])
            if it is not None and not pm.isNull():
                it.setIcon(QIcon(pm))
        job = BackgroundJob(trabajo, self, with_partial=True)
        job.partial.connect(llego)
        self._job = job
        job.start()

    def al_dia(self):
        """El panel releyó las carpetas (una descarga, algo desvinculado…): la ventana también, si está a la vista."""
        if self.isVisible():
            self.refrescar(leer=not self.acoplado)   # (acoplada: el panel acaba de leer las carpetas)

    @staticmethod
    def _sel(grid: QListWidget) -> list[str]:
        return [it.data(Qt.UserRole) for it in grid.selectedItems() if it.data(Qt.UserRole)]

    _MODS = Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier

    def _tecla(self, e) -> bool:
        """⌫ Retroceso borra lo elegido; Supr ya no borra nada aquí (se pulsaba sin querer). True = atendida."""
        if e.modifiers() & self._MODS:
            return False
        rutas = self._sel(self.grid_net) + self._sel(self.grid_pc)
        if e.key() == Qt.Key_Backspace and rutas:
            self.borrar(rutas)
            return True
        if e.key() == Qt.Key_Delete and rutas:
            self._avisa("Para borrar lo elegido usa ⌫ Retroceso (la tecla de encima de Intro).")
            return True
        return False

    def eventFilter(self, obj, e):
        if hasattr(self, "grid_pc") and obj in (self.grid_net, self.grid_pc):
            t = e.type()
            if (t == QEvent.ShortcutOverride and e.key() in (Qt.Key_Backspace, Qt.Key_Delete)
                    and not (e.modifiers() & self._MODS) and (self._sel(self.grid_net) or self._sel(self.grid_pc))):
                e.accept()                     # (con algo elegido aquí, ⌫/Supr no borran clips de la línea de tiempo)
                return True
            if t == QEvent.KeyPress and self._tecla(e):
                return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        if self._tecla(e):
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------ buscar
    def buscar_internet(self):
        if not self.term:
            self._avisa("Elige antes una palabra.")
            return
        tabs = getattr(self.p, "pestanas", None)
        if self.acoplado and tabs is not None and tabs.count() > 1 and hasattr(self.p, "_buscar"):
            tabs.setCurrentIndex(1)                     # 🌐 Internet, en el panel Palabras clave
            win = self.p.window()
            if hasattr(win, "show_panel"):
                win.show_panel(self.p)
            if getattr(self.p, "campo", None) is not None:
                self.p.campo.setText(self.term)
            self.p._buscar(self.term, [], self.p._tipo())
            self._avisa(f"🌐 Buscando «{self.term}» en Palabras clave → 🌐 Internet: lo que bajes irá a su carpeta.")
            return
        if self._net is None or not hasattr(self.p, "_buscar"):
            self._avisa("La búsqueda en internet no está instalada en este equipo: usa «💻 Buscar en tu computadora».")
            return
        if getattr(self.p, "campo", None) is not None:
            self.p.campo.setText(self.term)
        self.p._buscar(self.term, [], self.p._tipo())
        self._avisa(f"🌐 Buscando «{self.term}»: los resultados salen a la izquierda; lo que bajes irá a su carpeta.")

    def _menu_pc(self):
        if not self.term:
            self._avisa("Elige antes una palabra.")
            return
        menu = QMenu(self)
        menu.addAction("🎞 Elegir videos o imágenes…", self._elegir_archivos)
        menu.addAction("🔗 Enlazar una carpeta entera (no se copia)…", self._elegir_carpeta)
        menu.exec(self.btn_buscar_pc.mapToGlobal(self.btn_buscar_pc.rect().bottomLeft()))

    def _elegir_archivos(self):
        rutas, _f = QFileDialog.getOpenFileNames(
            self, f"Material para «{self.term}»", "",
            "Videos e imágenes (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.png *.jpg *.jpeg *.webp *.gif);;Todo (*.*)")
        if rutas:
            self._anadir([os.path.normpath(r) for r in rutas])

    def _elegir_carpeta(self):
        d = QFileDialog.getExistingDirectory(self, f"Carpeta con material de «{self.term}»")
        if d:
            self._anadir([os.path.normpath(d)])

    def _anadir(self, rutas: list[str]):
        if not self.term:
            self._avisa("Elige antes una palabra para soltar ahí.")
            return
        self.p._soltar_archivos(rutas, term=self.term)
        self._avisa(self.p.aviso.text())
        self.refrescar()

    # ------------------------------------------------------------------ pasar a mi computadora
    def _armar_menu_net(self, rutas: list[str]) -> QMenu:
        """Menú del clic derecho en «🌐 Descargado de internet» (aparte del exec: las pruebas lo usan sin abrirlo)."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        a = menu.addAction("💻 Pasar a mi computadora…" + (f" ({len(rutas)})" if len(rutas) > 1 else ""),
                           lambda r=list(rutas): self.pasar_a_mi_pc(r))
        a.setToolTip("Mueve el archivo (con sus créditos) a una carpeta de tu PC que eliges; sigue en esta palabra")
        menu.addAction("⏵ Poner en el cabezal", lambda r=list(rutas): self.poner(True, r))
        menu.addAction("🗑 Borrar…", lambda r=list(rutas): self.borrar(r))
        return menu

    def _menu_net(self, pos):
        it = self.grid_net.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.grid_net.clearSelection()
            it.setSelected(True)
        rutas = self._sel(self.grid_net)
        if rutas:
            self._armar_menu_net(rutas).exec(self.grid_net.viewport().mapToGlobal(pos))

    def _soltado_pc(self, rutas: list[str]):
        """Algo soltado en «💻 De tu computadora»: lo de «🌐 Descargado» de esta palabra se MUEVE a una carpeta tuya
        (te pregunta cuál); lo que viene del Explorador se añade como siempre; lo que ya estaba aquí, nada."""
        self.p._leer_carpetas()
        net, pc = partes(self._car())

        def clave(r):
            return os.path.normcase(os.path.abspath(r))
        k_net, k_pc = {clave(r) for r in net}, {clave(r) for r in pc}
        desde_net = [r for r in rutas if clave(r) in k_net]
        otras = [r for r in rutas if clave(r) not in k_net and clave(r) not in k_pc]
        if otras:
            self._anadir(otras)
        if desde_net:                          # (después del soltar: un diálogo dentro del arrastre da problemas)
            QTimer.singleShot(0, lambda r=desde_net: self.pasar_a_mi_pc(r))

    def _pedir_carpeta_pc(self, n: int) -> str:
        """Pregunta a qué carpeta de tu PC van (empieza en la última usada). "" = cancelado. (Las pruebas lo cambian.)"""
        inicio = str(QSettings("EditorIA", "EditorIA").value("palabras_ventana/carpeta_pc", "") or "")
        if not os.path.isdir(inicio):
            inicio = os.path.join(os.path.expanduser("~"), "Videos")
        titulo = (f"¿En qué carpeta de tu computadora guardo este archivo de «{self.term}»?" if n == 1 else
                  f"¿En qué carpeta de tu computadora guardo estos {n} archivos de «{self.term}»?")
        return QFileDialog.getExistingDirectory(self, titulo, inicio) or ""

    def pasar_a_mi_pc(self, rutas: list[str], carpeta: str | None = None) -> int:
        """💻 Lo descargado de internet se MUEVE (con sus créditos) a una carpeta tuya y queda 🔗 enlazado a la misma
        palabra (sale en «💻 De tu computadora»). Si está en Medios, su ruta pasa a la nueva: sus clips siguen bien.
        Devuelve cuántos se movieron."""
        if not self.term:
            self._avisa("Elige antes una palabra.")
            return 0
        self.p._leer_carpetas()                     # (lo de ahora, no lo que había al pintar la rejilla)
        net = partes(self._car())[0]
        k_net = {os.path.normcase(os.path.abspath(r)): r for r in net}
        rutas = [k_net[k] for k in dict.fromkeys(os.path.normcase(os.path.abspath(r)) for r in rutas or [])
                 if k in k_net]
        if not rutas:
            self.refrescar()
            self._avisa("Elige antes archivos de «🌐 Descargado de internet» (clic; Ctrl+clic para varios).")
            return 0
        if carpeta is None:
            carpeta = self._pedir_carpeta_pc(len(rutas))
        if not carpeta:
            self._avisa("No se movió nada (no elegiste carpeta).")
            return 0
        carpeta = os.path.normpath(carpeta)
        if KF._inside(carpeta, self.p.raiz):
            self._avisa("Esa carpeta está dentro de las carpetas de palabras clave: elige una carpeta tuya, fuera de "
                        "ahí.")
            return 0
        QSettings("EditorIA", "EditorIA").setValue("palabras_ventana/carpeta_pc", carpeta)
        try:
            movidos, fallos = KF.move_files(rutas, carpeta)
        except OSError as exc:
            self._avisa(f"No pude usar esa carpeta: {exc}")
            return 0
        sin_enlace = 0
        en_medios = 0
        for src, dst in movidos:
            try:
                KF.link_file(self.p.raiz, self.term, dst)
            except (OSError, ValueError):
                sin_enlace += 1
            if hasattr(self.ctrl, "move_media_path") and src != dst:
                en_medios += self.ctrl.move_media_path(src, dst)
        self.p.recalcular()
        self.refrescar()
        nombre = os.path.basename(carpeta.rstrip("\\/")) or carpeta
        texto = f"💻 {len(movidos)} archivo(s) movidos a «{nombre}»; siguen en la palabra «{self.term}»"
        if en_medios:
            texto += " (en Medios también: sus clips siguen bien)"
        if sin_enlace:
            texto += f". ⚠ {sin_enlace} no se pudieron enlazar a la palabra (están en «{nombre}»)"
        if fallos:
            texto += f". {len(fallos)} no se pudieron mover (¿abiertos en otro programa?)"
        self._avisa(texto + ".")
        self.aviso.setToolTip(carpeta)
        return len(movidos)

    def _abrir_carpeta(self):
        car = self._car()
        if car is not None:
            self.p._abrir(car["path"])

    # ------------------------------------------------------------------ poner
    def poner(self, en_cabezal: bool, rutas: list[str] | None = None):
        rutas = rutas or (self._sel(self.grid_net) + self._sel(self.grid_pc))
        if not rutas:
            self._avisa("Elige antes uno o más archivos (clic; Ctrl+clic para varios).")
            return
        if en_cabezal:
            ok = self.p._poner_mis(rutas, self.p._hits_cabezal())
        else:
            fila = next((i for i, m in enumerate(self.p.menciones)
                         if KG.clave(m["term"]) == KG.clave(self.term) and m["hits"]), -1)
            if fila < 0:
                self._avisa(f"«{self.term}» no sale en tu narración: usa «⏵ Poner en el cabezal».")
                return
            self.p.elegir_indice(fila, buscar=False)
            ok = self.p._poner_mis(rutas)
        self._avisa(self.p.aviso.text() or ("✓ Puesto en la línea de tiempo." if ok else ""))

    # ------------------------------------------------------------------ borrar
    def _usados(self, rutas: list[str]) -> int:
        norm = {os.path.normcase(os.path.abspath(r)) for r in rutas}
        return sum(1 for m in self.ctrl.project.media.values()
                   if os.path.normcase(os.path.abspath(m.path)) in norm)

    def borrar(self, rutas: list[str], preguntar: bool = True) -> int:
        """Lo bajado y lo copiado → Papelera (con sus créditos); lo enlazado de tu PC → solo se desvincula."""
        from .clips_panel import _a_papelera
        if not rutas:
            self._avisa("Elige antes los archivos (clic; Ctrl+clic para varios) o usa «Borrar todo lo descargado».")
            return 0
        self.p._leer_carpetas()                     # (lo de ahora, no lo que había al pintar la rejilla)
        car = self._car()
        actuales = set((car or {}).get("files") or [])
        viejos = [r for r in rutas if r not in actuales]
        rutas = [r for r in rutas if r in actuales]
        if viejos and not rutas:
            self.refrescar()
            self._avisa("Esa carpeta cambió (¿desvinculaste algo en Medios?): ya está al día; vuelve a elegir.")
            return 0
        file_links = set((car or {}).get("file_links") or [])
        enlazados = set((car or {}).get("linked_files") or [])
        desv = [r for r in rutas if r in file_links]
        de_carpeta = [r for r in rutas if r in enlazados and r not in file_links]   # dentro de una carpeta enlazada
        papelera = [r for r in rutas if r not in enlazados and propio(r, car)]   # NUNCA algo de fuera de su carpeta
        if preguntar:
            usados = self._usados(papelera)
            lineas = []
            if papelera:
                lineas.append(f"· {len(papelera)} archivo(s) a la Papelera ({_mb(papelera):.0f} MB; se pueden "
                              "recuperar).")
            if desv:
                lineas.append(f"· {len(desv)} enlace(s) a tu PC se desvinculan (tus archivos no se tocan).")
            if de_carpeta:
                lineas.append(f"· {len(de_carpeta)} vienen de una carpeta enlazada: no se tocan (desvincula la "
                              "carpeta desde Medios → 🔑 Palabras clave).")
            if usados:
                lineas.append(f"⚠ {usados} de ellos están en tu proyecto: se quedarán sin archivo.")
            if not papelera and not desv:
                self._avisa(lineas[0] if lineas else "Nada que borrar.")
                return 0
            r = QMessageBox.question(self, "🗑 Borrar material", "¿Seguro?\n\n" + "\n".join(lineas),
                                     QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return 0
        hechos = 0
        fallos = 0
        for r in papelera:
            try:
                ok = _a_papelera(r)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                hechos += 1
                if os.path.isfile(creditos_de(r)):
                    try:
                        _a_papelera(creditos_de(r))
                    except Exception:  # noqa: BLE001
                        pass
            else:
                fallos += 1
        for r in desv:
            try:
                if KF.unlink_file(self.p.raiz, self.term, r):
                    hechos += 1
            except OSError:
                fallos += 1
        self.p.recalcular()
        self.refrescar()
        self._todo_al_dia()
        self._avisa(f"🗑 Listo: {hechos} quitado(s)" + (f"; {fallos} no se pudieron: están abiertos en otro programa "
                                                       "(ciérralo y vuelve a probar)" if fallos else "") + ".")
        return hechos

    def borrar_todo_descargado(self, preguntar: bool = True, sin_palabra: bool = False) -> int:
        """🧹 Todo lo bajado de internet, de todas las palabras, a la Papelera (ver borrar_todo_descargado)."""
        hechos = borrar_todo_descargado(self.p, self, preguntar, sin_palabra)
        self._firma_vista = None
        self.refrescar()
        self._todo_al_dia()                    # (antes «Todo lo descargado» seguía enseñando lo ya borrado)
        self._avisa(self.p.aviso.text())
        return hechos

    def borrar_palabra(self, preguntar: bool = True) -> bool:
        from .clips_panel import _a_papelera
        car = self._car()
        if car is None:
            self._avisa("Esta palabra no tiene carpeta.")
            return False
        if preguntar:
            suyos = [f for f in car["files"] if propio(f, car)]
            usados = self._usados(suyos)
            r = QMessageBox.question(
                self, "🗑 Borrar palabra y carpeta",
                f"¿Borrar «{car['label']}»?\n\n· Su carpeta ({len(suyos)} archivo(s)) va a la Papelera.\n"
                "· Lo enlazado de tu PC solo se desvincula (no se borra)."
                + (f"\n⚠ {usados} están en tu proyecto: se quedarán sin archivo." if usados else ""),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return False
        try:
            KF.delete_keyword(self.p.raiz, self.term, _a_papelera)
            KG.remove(self.term)
        except OSError as exc:
            self._avisa(f"No pude borrarla: {exc}")
            return False
        nombre = car["label"]
        self.p.recalcular()
        self.refrescar()
        self._avisa(f"🗑 «{nombre}» borrada (su carpeta está en la Papelera).")
        return True


def abrir(panel) -> KeywordsWindow:
    """Abre (o trae al frente) la ventana amplia del panel."""
    w = getattr(panel, "_ventana_amplia", None)
    if w is None:
        w = KeywordsWindow(panel, panel.window())
        panel._ventana_amplia = w
        geom = QSettings("EditorIA", "EditorIA").value("palabras_ventana/geom")
        if geom is None or not w.restoreGeometry(geom):
            scr = panel.screen().availableGeometry() if panel.screen() else None
            if scr is not None:
                w.resize(int(scr.width() * 0.85), int(scr.height() * 0.85))
    w.show()
    w.raise_()
    w.activateWindow()
    return w
