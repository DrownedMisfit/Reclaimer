"""
📥 «Descargado»: las carpetas con lo que Reclaimer ha bajado de internet, para meterlo al proyecto en un momento.
(Va dentro de 🗂 Carpetas, en «Todo lo descargado», y se abre también con «Ver todo» de Buscar material.)

  🌐 Clips de internet   lo bajado con 🔑 Palabras clave (YouTube, X, Instagram, TikTok…): está en la carpeta de cada
                         palabra (lo reconoce su «.creditos.json»), y lo que no tenía palabra, en «Descargas/»
  🔊 Sonidos de internet lo guardado con 🌐 Buscar sonidos en internet (Efectos)
  🖼 Imágenes de internet lo guardado con ✓ en 🔎 Momentos (imágenes de la web)

Arriba las carpetas (con cuántos archivos tienen), abajo sus archivos con miniatura (también de los VIDEOS) y,
en pequeño sobre la miniatura, su duración: doble clic = ponerlo en el cabezal ·
➕ A Medios · ⏵ Poner en el cabezal · arrastrarlo a la línea de tiempo (o a Medios) · 🗑 Quitar (22/11): lo elegido
—o, sin nada elegido, la carpeta elegida— a la Papelera de Windows (recuperable), con sus créditos y con
confirmación; también con clic derecho y ⌫ Retroceso. Dentro de Carpetas (incrustado=True) no lleva cabecera propia:
abrir y recargar están en la de Carpetas.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSizePolicy, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, kind_for_path
from ..core.paths import PROGRAM_DIR, user_dir

ICONO = {KIND_VIDEO: "🎬", KIND_AUDIO: "🔊", KIND_IMAGE: "🖼"}
MINI = QSize(128, 72)
MAX_ARCHIVOS = 400                    # (por carpeta: lo más nuevo primero; una carpeta enorme no frena la página)


_DURACIONES: dict = {}                # (ruta, fecha) → segundos (ffprobe, una vez por archivo y sesión)


def duracion_de(ruta: str) -> float:
    """⏱ Duración de un video o sonido (en segundo plano: ffprobe). 0 si no se puede leer."""
    try:
        clave = (os.path.normcase(ruta), os.path.getmtime(ruta))
    except OSError:
        return 0.0
    if clave not in _DURACIONES:
        try:
            from ..core import media as MEDIA
            _DURACIONES[clave] = float(MEDIA.probe(ruta).get("duration") or 0.0)
        except Exception:  # noqa: BLE001 - sin duración, la miniatura va sin ella
            _DURACIONES[clave] = 0.0
    return _DURACIONES[clave]


def con_duracion(pm: QPixmap, dur: float) -> QIcon:
    """La miniatura con su duración pequeña abajo a la derecha (la misma que en 🌐 Internet → Resultados)."""
    try:
        from .clips_internet import InternetMixin
        return InternetMixin._con_duracion(pm, dur)
    except ImportError:
        pass
    if not dur or pm.isNull():
        return QIcon(pm)
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QPainter
    from ..core.keyword_place import mmss
    img = QPixmap(pm)
    p = QPainter(img)
    f = QFont(p.font())
    f.setPixelSize(max(10, img.height() // 7))
    f.setBold(True)
    p.setFont(f)
    txt = mmss(dur)
    fm = p.fontMetrics()
    w, h = fm.horizontalAdvance(txt) + 8, fm.height() + 2
    caja = QRectF(img.width() - w - 4, img.height() - h - 4, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 200))
    p.drawRoundedRect(caja, 3, 3)
    p.setPen(QColor("white"))
    p.drawText(caja, Qt.AlignCenter, txt)
    p.end()
    return QIcon(img)


def _descargas_dir() -> Path:
    """Donde baja los clips ai/clip_download (si ya está cargado, su valor: las pruebas lo cambian)."""
    mod = sys.modules.get("editoria.ai.clip_download")
    return Path(getattr(mod, "DESCARGAS_DIR", PROGRAM_DIR / "Descargas"))


def _imagenes_dir() -> Path:
    # (la misma que ai/web_images.folder(), sin crearla: aquí solo se mira)
    return Path(os.path.expanduser("~")) / "Videos" / "Reclaimer" / "Imágenes de internet"


def es_de_internet(ruta: str) -> bool:
    return os.path.isfile(os.path.splitext(ruta)[0] + ".creditos.json")


def fuentes(raiz_palabras: str | None) -> list[tuple[str, Path, bool]]:
    """[(nombre, carpeta, solo_lo_bajado)]: solo_lo_bajado = en esa carpeta también hay cosas tuyas (las carpetas de
    las palabras): solo cuentan los archivos con su «.creditos.json»."""
    out = []
    if raiz_palabras:
        out.append(("🌐 Clips de internet (por palabra)", Path(raiz_palabras), True))
    out += [("⬇ Clips de internet (sin palabra)", _descargas_dir(), False),
            ("🔊 Sonidos de internet", user_dir() / "Sonidos de internet", False),
            ("🖼 Imágenes de internet", _imagenes_dir(), False)]
    return out


def archivos_de(carpeta: str, solo_lo_bajado: bool, hondo: int = 2) -> list[str]:
    """Los videos, sonidos e imágenes de la carpeta (y sus subcarpetas, hasta «hondo» niveles), lo más nuevo primero."""
    out = []

    def mirar(d: str, nivel: int):
        try:
            entradas = list(os.scandir(d))
        except OSError:
            return
        for e in entradas:
            try:
                if e.is_dir(follow_symlinks=False):
                    if nivel < hondo:
                        mirar(e.path, nivel + 1)
                elif kind_for_path(e.name) and (not solo_lo_bajado or es_de_internet(e.path)):
                    out.append(e.path)
            except OSError:
                continue
    mirar(carpeta, 1)

    def fecha(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0
    out.sort(key=fecha, reverse=True)
    return out


def carpetas_de(base: Path, solo_lo_bajado: bool) -> list[tuple[str, str, int]]:
    """[(nombre, ruta, cuántos)] de las subcarpetas con algo (y «(sueltos)» si hay archivos en la propia carpeta)."""
    if not base.is_dir():
        return []
    out = []
    try:
        subs = sorted((e for e in os.scandir(base) if e.is_dir(follow_symlinks=False)), key=lambda e: e.name.lower())
    except OSError:
        subs = []
    for e in subs:
        n = len(archivos_de(e.path, solo_lo_bajado))
        if n:
            out.append((e.name, e.path, n))
    sueltos = [p for p in archivos_de(str(base), solo_lo_bajado, hondo=1)]
    if sueltos:
        out.insert(0, ("(sueltos)", str(base) + os.sep + "|sueltos", len(sueltos)))
    return out


def leer_fuentes(raiz_palabras: str | None, cancelado=None) -> list[dict]:
    """⚡ Todo lo que enseña el panel, leído de una vez (en un hilo: BackgroundJob; nunca en el de la interfaz):
    [{"nombre", "base", "solo", "subs": [(nombre, ruta, cuántos)], "archivos": {ruta: [archivos, lo más nuevo
    primero]}}]. «archivos» guarda lo de cada subcarpeta, lo «(sueltos)» y lo de la carpeta entera (clave = base): al
    elegir una carpeta no hace falta volver a recorrer el disco."""
    out = []
    for nombre, base, solo in fuentes(raiz_palabras):
        subs, archivos = [], {}
        if base.is_dir():
            try:
                dirs = sorted((e for e in os.scandir(base) if e.is_dir(follow_symlinks=False)),
                              key=lambda e: e.name.lower())
            except OSError:
                dirs = []
            for e in dirs:
                if cancelado is not None and cancelado():
                    return out
                fs = archivos_de(e.path, solo)
                if fs:
                    subs.append((e.name, e.path, len(fs)))
                    archivos[e.path] = fs
            sueltos = archivos_de(str(base), solo, hondo=1)
            if sueltos:
                clave = str(base) + os.sep + "|sueltos"
                subs.insert(0, ("(sueltos)", clave, len(sueltos)))
                archivos[clave] = sueltos

        def fecha(p):
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0.0
        archivos[str(base)] = sorted({p for fs in archivos.values() for p in fs}, key=fecha, reverse=True)
        out.append({"nombre": nombre, "base": str(base), "solo": solo, "subs": subs, "archivos": archivos})
    return out


class _ListaArchivos(QListWidget):
    """Sus archivos salen arrastrando como archivos de Windows (la línea de tiempo y Medios los aceptan)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items if it.data(Qt.UserRole)])
        return md


def hueco(kind: str) -> QPixmap:
    """La miniatura que falta (un sonido, o un video que no se pudo leer): gris oscuro con su icono, no un cuadro negro
    que parece un video roto."""
    from PySide6.QtGui import QPainter
    from . import diseno as D
    pm = QPixmap(MINI)
    pm.fill(QColor("#2a2c31"))
    p = QPainter(pm)
    ic = D.pixmap_icono("music" if kind == KIND_AUDIO else "film", D.colores()["tenue"], 28)
    p.drawPixmap((MINI.width() - 28) // 2, (MINI.height() - 28) // 2, 28, 28, ic)
    p.end()
    return pm


def D_icono(nombre: str) -> QIcon:
    from . import diseno as D
    return D.icono(nombre)


class DescargasPanel(QWidget):
    borrado = Signal()                   # (algo fue a la Papelera: quien lo contiene pone al día lo suyo)

    def __init__(self, win, parent=None, incrustado: bool = False):
        super().__init__(parent)
        self.incrustado = incrustado     # (dentro de Carpetas: sin cabecera propia; abrir y recargar, en la de Carpetas)
        self._aviso_tras_leer = ""
        self.win = win                   # la ventana principal (o una función que la devuelve)
        self._leido = False
        self._items: dict[str, QListWidgetItem] = {}
        self._tok_mini = 0
        self._job_mini = None
        self._job = None                 # (⚡ la lectura de las carpetas, en segundo plano)
        self._otra_vez = False           # (⟳ pulsado mientras leía: se vuelve a leer al acabar)
        self._cache = {}                 # ruta → sus archivos (de la última lectura)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        cab = QHBoxLayout()
        titulo = QLabel("<b>📥 Lo descargado de internet</b>")
        titulo.setToolTip("Las carpetas donde Reclaimer guarda lo que baja de internet (clips de YouTube, X, Instagram, "
                          "TikTok…, sonidos e imágenes). Elige una y mete sus archivos al proyecto.")
        self.btn_releer = QPushButton("⟳")
        self.btn_releer.setFixedWidth(34)
        self.btn_releer.setToolTip("Volver a leer las carpetas")
        self.btn_releer.clicked.connect(self.refrescar)
        self.btn_abrir = QPushButton("📂 Abrir")
        self.btn_abrir.setToolTip("Abre en el Explorador la carpeta elegida")
        self.btn_abrir.clicked.connect(self._abrir)
        cab.addWidget(titulo, 1)
        cab.addWidget(self.btn_abrir)
        cab.addWidget(self.btn_releer)
        cab.setContentsMargins(0, 0, 0, 0)
        self._cab = QWidget()
        self._cab.setLayout(cab)
        v.addWidget(self._cab)
        self._cab.setVisible(not incrustado)    # (22/11: «Abrir» desperdiciaba una fila; en Carpetas va arriba)

        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setRootIsDecorated(True)
        self.arbol.setToolTip("Dónde guarda Reclaimer lo que baja de internet. Elige una carpeta para ver sus archivos.")
        self.arbol.currentItemChanged.connect(lambda it, _p: self._pintar_archivos(it))
        self.arbol.setContextMenuPolicy(Qt.CustomContextMenu)
        self.arbol.customContextMenuRequested.connect(self._menu_arbol)
        self.lista = _ListaArchivos()
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setIconSize(MINI)
        self.lista.setGridSize(QSize(MINI.width() + 24, MINI.height() + 40))
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setWordWrap(True)
        self.lista.setToolTip("Doble clic = ponerlo en el cabezal · arrástralo a la línea de tiempo o a Medios · "
                              "clic derecho = más · ⌫ Retroceso = quitar (a la Papelera)")
        self.lista.itemDoubleClicked.connect(lambda it: self._poner([it.data(Qt.UserRole)]))
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_lista)
        self.lista.installEventFilter(self)
        from .miniaturas import activar_vista_grande              # 🖼 al pasar el ratón: en grande (y animado)
        activar_vista_grande(self.lista, lambda it: it.data(Qt.UserRole))
        partes = QSplitter(Qt.Vertical)
        partes.setChildrenCollapsible(False)
        partes.addWidget(self.arbol)
        partes.addWidget(self.lista)
        partes.setStretchFactor(0, 2)
        partes.setStretchFactor(1, 3)
        v.addWidget(partes, 1)

        fb = QHBoxLayout()
        self.btn_medios = QPushButton("➕ A Medios")
        self.btn_medios.setToolTip("Añade los archivos elegidos a Medios (sin ponerlos en la línea de tiempo)")
        self.btn_medios.clicked.connect(lambda: self._a_medios(self._elegidos()))
        self.btn_cabezal = QPushButton("⏵ Poner en el cabezal")
        self.btn_cabezal.setToolTip("Pone los archivos elegidos donde está el cabezal (la línea roja)")
        self.btn_cabezal.clicked.connect(lambda: self._poner(self._elegidos()))
        self.btn_quitar = QPushButton("Quitar")
        self.btn_quitar.setIcon(D_icono("trash-2"))
        self.btn_quitar.setToolTip("Manda a la Papelera de Windows (se puede recuperar) los archivos elegidos o, si no "
                                   "eliges ninguno, todo lo bajado de la carpeta elegida, con sus créditos. Antes "
                                   "pregunta. Lo tuyo (sin créditos) en las carpetas de las palabras no se toca.")
        self.btn_quitar.clicked.connect(lambda: self.quitar())
        fb.addWidget(self.btn_medios)
        fb.addWidget(self.btn_cabezal)
        fb.addStretch(1)
        fb.addWidget(self.btn_quitar)
        v.addLayout(fb)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        self.estado.setObjectName("dim")
        self.estado.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        v.addWidget(self.estado)

    # ------------------------------------------------------------------ leer
    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.al_verse)

    def al_verse(self):
        """La primera vez que se ve de verdad (en pestaña detrás de otra, Qt la deja «visible» fuera de la vista: no
        cuenta). La ventana lo llama también al elegir su pestaña (visibilityChanged). Luego, ⟳."""
        try:
            if self._leido or not self.isVisible() or self.visibleRegion().isEmpty():
                return
        except RuntimeError:
            return
        self.refrescar()

    def _w(self):
        w = self.win
        return w() if callable(w) else w

    def _raiz_palabras(self) -> str | None:
        return getattr(getattr(self._w(), "clips", None), "raiz", None)

    def refrescar(self):
        """⟳ Vuelve a leer las carpetas EN SEGUNDO PLANO (con muchas descargas, recorrerlas congelaba la ventana);
        al acabar se pinta el árbol (pintar_lectura)."""
        self._leido = True
        if self._job is not None:
            self._otra_vez = True
            return
        from .jobs import BackgroundJob
        raiz = self._raiz_palabras()
        job = self._job = BackgroundJob(lambda progress, cancelled: leer_fuentes(raiz, cancelled), self)
        job.title = "📥 Leyendo lo descargado"
        job.done.connect(self._leida)
        job.failed.connect(lambda msg: self.estado.setText(f"No pude leer las carpetas: {msg}"))
        job.finished.connect(self._fin_lectura)
        self.btn_releer.setEnabled(False)
        self.estado.setText("⏳ Leyendo las carpetas…")
        job.start()

    def _leida(self, lectura):
        try:
            self.pintar_lectura(lectura or [])
        except RuntimeError:             # (el panel se cerró mientras leía)
            pass

    def _fin_lectura(self):
        job, self._job = self._job, None
        if job is not None:
            job.deleteLater()
        try:
            self.btn_releer.setEnabled(True)
        except RuntimeError:
            return
        if self._otra_vez:
            self._otra_vez = False
            self.refrescar()

    def pintar_lectura(self, lectura: list[dict]):
        """Pinta el árbol con una lectura de leer_fuentes (sin tocar el disco)."""
        actual = self.arbol.currentItem().data(0, Qt.UserRole) if self.arbol.currentItem() else None
        self._cache = {}
        self.arbol.clear()
        total, elegir = 0, None
        for fu in lectura:
            nombre, base, solo, subs = fu["nombre"], Path(fu["base"]), fu["solo"], fu["subs"]
            self._cache.update(fu["archivos"])
            n = sum(c for _n, _r, c in subs)
            total += n
            top = QTreeWidgetItem([f"{nombre}  ({n})"])
            top.setData(0, Qt.UserRole, (str(base), solo, True))
            top.setToolTip(0, str(base))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.arbol.addTopLevelItem(top)
            for sub, ruta, c in subs:
                it = QTreeWidgetItem([f"📁 {sub}  ({c})"])
                it.setData(0, Qt.UserRole, (ruta, solo, False))
                it.setToolTip(0, ruta.split("|")[0])
                top.addChild(it)
                if actual and actual[0] == ruta:
                    elegir = it
            top.setExpanded(bool(subs) and len(subs) <= 12)
            if actual and actual[0] == str(base):
                elegir = top
        if elegir is None:
            elegir = next((self.arbol.topLevelItem(i).child(0) for i in range(self.arbol.topLevelItemCount())
                           if self.arbol.topLevelItem(i).childCount()), None)
        if elegir is not None:
            self.arbol.setCurrentItem(elegir)
        else:
            self._pintar_archivos(None)
        self.estado.setText(f"{total} archivo(s) bajados de internet." if total else
                            "Aún no has bajado nada de internet (🔎 Buscar → 🌐 Internet, o pega un enlace).")
        if self._aviso_tras_leer:                  # (tras quitar algo: lo que pasó, no solo la cuenta)
            self.estado.setText(self._aviso_tras_leer)
            self._aviso_tras_leer = ""

    def _pintar_archivos(self, it: QTreeWidgetItem | None):
        self.lista.clear()
        self._items = {}
        self._tok_mini += 1
        if it is None:
            return
        ruta, solo, es_raiz = it.data(0, Qt.UserRole)
        sueltos = ruta.endswith("|sueltos")
        carpeta = ruta.split("|")[0].rstrip(os.sep)
        rutas = self._cache.get(ruta)            # (⚡ de la última lectura: sin recorrer el disco otra vez)
        if rutas is None:
            rutas = archivos_de(carpeta, solo, hondo=3 if es_raiz else 1 if sueltos else 2)
        pendientes = []
        for p in rutas[:MAX_ARCHIVOS]:
            kind = kind_for_path(p)
            item = QListWidgetItem(f"{ICONO.get(kind, '•')} {os.path.basename(p)}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            if kind == KIND_IMAGE:
                r = QImageReader(p)
                r.setAutoTransform(True)
                tam = r.size()
                if tam.isValid() and tam.width() > 0:
                    r.setScaledSize(tam.scaled(MINI, Qt.KeepAspectRatio))
                    img = r.read()
                    if not img.isNull():
                        item.setIcon(QPixmap.fromImage(img))
            elif kind in (KIND_VIDEO, KIND_AUDIO):
                pendientes.append(p)          # 🎬 miniatura del video y ⏱ duración: en segundo plano
            self.lista.addItem(item)
            self._items[p] = item
        if pendientes:
            self._miniaturas(pendientes, self._tok_mini)
        if len(rutas) > MAX_ARCHIVOS:
            self.estado.setText(f"Se ven los {MAX_ARCHIVOS} más nuevos de {len(rutas)} (📂 Abrir para el resto).")

    def _miniaturas(self, rutas: list[str], tok: int):
        """🎬 Miniatura de cada video (un fotograma; la misma caché que Carpetas) y ⏱ su duración, sin frenar nada."""
        from .clips_panel import _hacer_miniatura, _miniatura_ruta
        from .jobs import BackgroundJob
        if self._job_mini is not None:
            self._job_mini.cancel()

        def trabajo(progreso, cancelado, emitir):
            for r in rutas:
                if cancelado():
                    return None
                png = ""
                if kind_for_path(r) == KIND_VIDEO:
                    png = _miniatura_ruta(r)
                    if not os.path.isfile(png) and not _hacer_miniatura(r, png):
                        png = ""
                emitir((r, png, duracion_de(r)))
            return None

        job = BackgroundJob(trabajo, self, with_partial=True)
        job.partial.connect(lambda par, t=tok: self._llego_miniatura(par, t))
        self._job_mini = job
        job.start()

    def _llego_miniatura(self, par, tok: int):
        if tok != self._tok_mini:
            return
        ruta, png, dur = par
        it = self._items.get(ruta)
        if it is None:
            return
        try:
            pm = QPixmap(png) if png else QPixmap()
            if pm.isNull():                    # (un sonido, o un video que no se pudo leer: su icono, no negro)
                pm = hueco(kind_for_path(ruta))
            it.setIcon(con_duracion(pm, dur))
            if dur:
                from ..core.keyword_place import mmss
                it.setToolTip(f"{ruta}\n⏱ {mmss(dur)}")
        except RuntimeError:
            pass

    # ------------------------------------------------------------------ meter al proyecto
    def _elegidos(self) -> list[str]:
        its = sorted(self.lista.selectedItems(), key=lambda it: self.lista.row(it))
        return [it.data(Qt.UserRole) for it in its if it.data(Qt.UserRole)]

    def _a_medios(self, rutas: list[str]) -> list[str]:
        if not rutas:
            self.estado.setText("Elige antes uno o varios archivos de la lista.")
            return []
        try:
            ids = self._w().ctrl.import_now(rutas)
        except Exception as exc:  # noqa: BLE001 - un archivo raro no rompe la página
            self.estado.setText(f"No pude añadirlo a Medios: {exc}")
            return []
        self.estado.setText(f"✓ En Medios: {len(ids)} archivo(s).")
        return ids

    def _poner(self, rutas: list[str]):
        ids = self._a_medios(rutas)
        win = self._w()
        if ids and hasattr(win, "_add_at_playhead"):
            win._add_at_playhead(ids)
            self.estado.setText(f"✓ Puesto en el cabezal: {len(ids)} archivo(s).")

    # ------------------------------------------------------------------ 🗑 quitar (a la Papelera)
    def _carpeta_elegida(self) -> tuple[list[str], str]:
        """(archivos bajados de la carpeta elegida en el árbol, su nombre)."""
        it = self.arbol.currentItem()
        if it is None:
            return [], ""
        ruta, solo, es_raiz = it.data(0, Qt.UserRole)
        sueltos = ruta.endswith("|sueltos")
        carpeta = ruta.split("|")[0].rstrip(os.sep)
        rutas = archivos_de(carpeta, solo, hondo=3 if es_raiz else 1 if sueltos else 2)
        return rutas, it.text(0).split("  (")[0].replace("📁", "").strip()

    def quitar(self, rutas: list[str] | None = None, preguntar: bool = True) -> int:
        """Lo elegido (o, sin nada elegido, lo bajado de la carpeta elegida) → Papelera, con sus créditos. Solo lo que
        enseña este panel: en las carpetas de las palabras, solo lo que tiene «.creditos.json» (lo bajado)."""
        from .keywords_window import _mb, a_papelera_con_creditos, texto_fallos
        que = ""
        if rutas is None:
            rutas = self._elegidos()
            if rutas:
                que = (f"los {len(rutas)} archivos elegidos" if len(rutas) > 1
                       else f"«{os.path.basename(rutas[0])}»")
            else:
                rutas, nombre = self._carpeta_elegida()
                que = f"todo lo bajado de «{nombre}» ({len(rutas)} archivo(s))"
        rutas = [r for r in rutas if r and os.path.exists(r)]
        if not rutas:
            self.estado.setText("Elige antes un archivo o una carpeta con algo dentro.")
            return 0
        if preguntar:
            que = que or f"{len(rutas)} archivo(s)"
            r = QMessageBox.question(self, "🗑 Quitar lo descargado",
                                     f"¿Mandar a la Papelera {que} ({_mb(rutas):.0f} MB)?\n\n"
                                     "Se puede recuperar desde la Papelera de Windows.",
                                     QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return 0
        hechos, fallos = a_papelera_con_creditos(rutas)
        self._aviso_tras_leer = (f"🗑 {hechos} archivo(s) a la Papelera." + (" " + texto_fallos(fallos)
                                                                           if fallos else ""))
        self.estado.setText(self._aviso_tras_leer)   # (la lectura nueva escribe su cuenta: el aviso se queda)
        self.refrescar()
        self.borrado.emit()
        return hechos

    def _menu_lista(self, pos):
        it = self.lista.itemAt(pos)
        if it is None:
            return None
        if not it.isSelected():
            self.lista.clearSelection()
            it.setSelected(True)
        menu = QMenu(self.lista)
        rutas = self._elegidos()
        menu.addAction("⏵ Poner en el cabezal", lambda: self._poner(rutas))
        menu.addAction("➕ A Medios", lambda: self._a_medios(rutas))
        menu.addAction("📂 Mostrar en la carpeta",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(rutas[0]))))
        menu.addSeparator()
        menu.addAction(D_icono("trash-2"), "Quitar (a la Papelera)…", lambda: self.quitar(rutas))
        menu.exec(self.lista.viewport().mapToGlobal(pos))
        return menu

    def _menu_arbol(self, pos):
        it = self.arbol.itemAt(pos)
        if it is None:
            return None
        self.arbol.setCurrentItem(it)
        menu = QMenu(self.arbol)
        menu.addAction("📂 Abrir la carpeta", self._abrir)
        menu.addSeparator()
        menu.addAction(D_icono("trash-2"), "Quitar todo lo bajado de esta carpeta (a la Papelera)…",
                       lambda: (self.lista.clearSelection(), self.quitar()))
        menu.exec(self.arbol.viewport().mapToGlobal(pos))
        return menu

    def eventFilter(self, obj, e):
        """⌫ Retroceso en la rejilla = quitar lo elegido (como en «Esta palabra»)."""
        if obj is getattr(self, "lista", None) and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Backspace \
                and not e.modifiers() and self._elegidos():
            self.quitar(self._elegidos())
            return True
        return super().eventFilter(obj, e)

    def _abrir(self):
        it = self.arbol.currentItem()
        ruta = it.data(0, Qt.UserRole)[0].split("|")[0] if it is not None else None
        if ruta and os.path.isdir(ruta):
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
        else:
            self.estado.setText("Esa carpeta aún no existe (se crea al bajar algo).")
