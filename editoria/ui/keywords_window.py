"""
🔑 Ventana amplia de palabras clave (aparte, para no quitar sitio a la edición):

  izquierda:  🌐 buscar en internet (solo si este equipo tiene esa parte; si no, se explica)
  derecha:    las palabras clave con 👍 / 👎 (👍 = palabra clave: se le crea su carpeta · 👎 = no lo es)
              y, de la palabra elegida, su carpeta en dos partes:
                · 🌐 Descargado de internet (lo bajado, con sus créditos)  → 🗑 borrar elegidos / todo lo de la palabra
                · 💻 De tu computadora (copiado o 🔗 enlazado)             → 🗑 quitar (lo enlazado solo se desvincula)
              arriba, «🧹 Borrar todo lo descargado…» de todas las palabras (con cuánto ocupa).

Todo lo borrado va a la Papelera de Windows (se puede recuperar); los archivos enlazados del PC nunca se borran.
La lógica de buscar, bajar y poner en la línea de tiempo es la del panel «🔑 Palabras clave» (clips_panel): esta
ventana solo la muestra en grande.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..ai import keyword_glossary as KG
from ..core import keyword_folders as KF
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
        fila = QHBoxLayout()
        self._lbl_palabras = QLabel("<b>🔑 Tus palabras clave</b>")
        fila.addWidget(self._lbl_palabras)
        self.filtro = QComboBox()
        for dato, texto in ESTADOS:
            self.filtro.addItem(texto, dato)
        self.filtro.setToolTip("Qué palabras ver: las que aún no decidiste, las que te gustan o las que no")
        self.filtro.currentIndexChanged.connect(lambda _i: self.refrescar())
        fila.addWidget(self.filtro)
        fila.addStretch(1)
        self.btn_limpiar = QPushButton("🧹 Borrar todo lo descargado…")
        self.btn_limpiar.setToolTip("Manda a la Papelera todo lo bajado de internet de TODAS las palabras (lo de tu "
                                    "computadora no se toca). Antes dice cuánto ocupa.")
        self.btn_limpiar.clicked.connect(self.borrar_todo_descargado)
        fila.addWidget(self.btn_limpiar)
        dv.addLayout(fila)

        cuerpo = QSplitter(Qt.Horizontal)
        col = self._col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lista.setToolTip("👍 = palabra clave (tiene carpeta) · 👎 = no lo es · ○ = por decidir. "
                              "Elige una para ver su carpeta.")
        self.lista.currentItemChanged.connect(lambda it, _p: self._elegir(it))
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
        self.btn_abrir = QPushButton("📂 Abrir carpeta")
        self.btn_abrir.clicked.connect(self._abrir_carpeta)
        self.btn_borrar_palabra = QPushButton("🗑 Borrar palabra y carpeta…")
        self.btn_borrar_palabra.setToolTip("Manda su carpeta a la Papelera y quita sus enlaces (lo enlazado de tu PC "
                                           "no se borra)")
        self.btn_borrar_palabra.clicked.connect(self.borrar_palabra)
        for b in (self.btn_buscar_net, self.btn_buscar_pc, self.btn_abrir, self.btn_borrar_palabra):
            acc.addWidget(b)
        acc.addStretch(1)
        kv.addLayout(acc)

        self.caja_net, self.grid_net = self._caja("🌐 Descargado de internet")
        bn = QHBoxLayout()
        self.btn_borrar_net = QPushButton("🗑 Borrar los elegidos")
        self.btn_borrar_net.clicked.connect(lambda: self.borrar(self._sel(self.grid_net)))
        self.btn_borrar_net_todo = QPushButton("🗑 Borrar todo lo descargado de esta palabra")
        self.btn_borrar_net_todo.clicked.connect(lambda: self.borrar(partes(self._car())[0]))
        bn.addWidget(self.btn_borrar_net)
        bn.addWidget(self.btn_borrar_net_todo)
        bn.addStretch(1)
        self.caja_net.layout().addLayout(bn)
        kv.addWidget(self.caja_net, 1)

        self.caja_pc, self.grid_pc = self._caja("💻 De tu computadora")
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
        kv.addWidget(self.aviso)
        cuerpo.addWidget(car)
        cuerpo.setStretchFactor(0, 1)
        cuerpo.setStretchFactor(1, 3)
        dv.addWidget(cuerpo, 1)
        split.addWidget(der)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        if self.acoplado:                      # (la lista y el 👍/👎 están en «Dijiste…»; internet, en su pestaña)
            for w in (self._izq, self._col, self._lbl_palabras, self.filtro):
                w.hide()
            lay.setContentsMargins(4, 4, 4, 4)
            self.btn_buscar_net.setToolTip("Busca clips de esta palabra en la pestaña «🌐 Internet» de Palabras clave "
                                           "(lo que bajes va a su carpeta)")

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
        g.setToolTip("Doble clic = ponerlo en el cabezal · arrástralo a la línea de tiempo · Supr = borrar")
        g.itemDoubleClicked.connect(lambda it: self.poner(True, [it.data(Qt.UserRole)]))
        g.soltado.connect(lambda rutas, _f: self._anadir(rutas))
        v.addWidget(g)
        return caja, g

    def _avisa(self, texto: str):
        self.aviso.setText(texto)

    # ------------------------------------------------------------------ abrir / cerrar
    def showEvent(self, e):
        super().showEvent(e)
        if not self.acoplado:
            self._tomar_internet()
        else:
            self.p.ensure_fresh()              # (el panel Palabras clave pudo estar oculto con un recálculo pendiente)
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
                p.lista_menciones.blockSignals(True)
                p.lista_menciones.setCurrentRow(fila)
                p.lista_menciones.blockSignals(False)
                p._elegir_mencion(fila, buscar=False)
            else:
                self._seguir(term)
            return
        self.term = term
        if self.filtro.currentData() != "todas":
            self.filtro.setCurrentIndex(0)           # (refresca)
        else:
            self.refrescar()

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
        for b in (self.btn_abrir, self.btn_borrar_palabra):
            b.setEnabled(car is not None)
        if not hay:
            self.titulo.setText("Elige una palabra en «Dijiste…» (o dale 👍 a una para crearle su carpeta)"
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

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            rutas = self._sel(self.grid_net) + self._sel(self.grid_pc)
            if rutas:
                self.borrar(rutas)
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
            self.p.lista_menciones.blockSignals(True)
            self.p.lista_menciones.setCurrentRow(fila)
            self.p.lista_menciones.blockSignals(False)
            self.p._elegir_mencion(fila, buscar=False)
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
        self._avisa(f"🗑 Listo: {hechos} quitado(s)" + (f"; {fallos} no se pudieron (¿abiertos en otro programa?)"
                                                       if fallos else "") + ".")
        return hechos

    def borrar_todo_descargado(self, preguntar: bool = True) -> int:
        """🧹 Todo lo bajado de internet, de todas las palabras, a la Papelera."""
        from .clips_panel import _a_papelera
        self.p._leer_carpetas()
        rutas = []
        for car in self.p.carpetas:
            rutas += partes(car)[0]
        if not rutas:
            self._avisa("No hay nada descargado de internet en tus carpetas de palabras.")
            return 0
        if preguntar:
            usados = self._usados(rutas)
            r = QMessageBox.question(
                self, "🧹 Borrar todo lo descargado",
                f"¿Mandar a la Papelera los {len(rutas)} clips bajados de internet ({_mb(rutas):.0f} MB) de todas "
                "tus palabras?\n\nLo de tu computadora no se toca. Se puede recuperar desde la Papelera."
                + (f"\n⚠ {usados} están en tu proyecto: se quedarán sin archivo." if usados else ""),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return 0
        hechos = 0
        for ruta in rutas:
            try:
                if _a_papelera(ruta):
                    hechos += 1
                    if os.path.isfile(creditos_de(ruta)):
                        _a_papelera(creditos_de(ruta))
            except Exception:  # noqa: BLE001
                pass
        self.p.recalcular()
        self.refrescar()
        self._avisa(f"🧹 {hechos} clip(s) descargado(s) a la Papelera.")
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
