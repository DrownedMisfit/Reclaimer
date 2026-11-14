"""
Panel «🎬 Clips» (lateral): lo que dices en la narración → tu material de esa palabra.

  arriba:  la carpeta raíz (Cambiar… / Abrir) y «Dijiste…» (📁 n = ya tienes carpeta con n archivos; ＋ = aún no)
  medio:   los momentos de la palabra elegida (casilla = poner ahí · pulsar = ir · 📍 = poner solo ahí)
  abajo:   «📁 Mi carpeta»: sus videos e imágenes en miniaturas (suelta archivos aquí; doble clic = poner)
           Si existe la parte opcional, añade una segunda pestaña con más clips.

Señales: seek_requested(float) → segundo de la línea de tiempo al que ir;
         hints_changed(list)   → [(segundo, texto)] para las marcas de la línea de tiempo ([] = quitarlas).
Nada bloquea la ventana: las miniaturas y las caras van en segundo plano (BackgroundJob).
«📍 Poner donde lo dices» llama a controller.place_clip_at (un solo paso de Ctrl+Z por tanda).
"""
from __future__ import annotations

import hashlib
import os

from PySide6.QtCore import QFileSystemWatcher, QMimeData, QSettings, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtCore import QElapsedTimer, QEvent, QRect
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
                               QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip, QVBoxLayout, QWidget)

ROL_LIKE = Qt.UserRole + 1        # en «Dijiste…»: "si" si la palabra ya está en el glosario como palabra clave
ROL_TERM = Qt.UserRole + 2        # en «Dijiste…»: la palabra de la fila (el 👍/👎 no depende del número de fila)

from ..ai import keyword_glossary as KG
from ..ai.mentions import find_mentions, verify_online
from ..core import keyword_folders as KF
from ..core import keyword_place as KP
from ..core import mapping
from ..core import media as MEDIA
from ..core.model import KIND_VIDEO, kind_for_path
from ..core.paths import cache_dir
from . import help as AYUDA
from .common import modo_archivo_suelto
from .glossary_dialog import GlosarioDialog
from .jobs import BackgroundJob

try:    # parte opcional: solo existe en algunos equipos; sin ella el panel funciona con «Mi carpeta»
    from .clips_internet import InternetMixin
    HAY_INTERNET = True
except ImportError:
    class InternetMixin:  # noqa: D101
        pass
    HAY_INTERNET = False

MINI_W, MINI_H = 160, 90
DURACION_MIN, DURACION_MAX, DURACION_SIN_VOZ = KP.DURACION_MIN, KP.DURACION_MAX, KP.DURACION_SIN_VOZ
RAIZ_CLAVE = "clips/carpeta_raiz"


def _mmss(t: float) -> str:
    return KP.mmss(t)


def _momento(h: dict) -> float | None:
    return h.get("tl")


def _ajustes() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


def _raiz_guardada() -> str:
    raiz = str(_ajustes().value(RAIZ_CLAVE, "") or "").strip()
    return raiz or KF.default_root()


def _corta(ruta: str, largo: int = 44) -> str:
    return ruta if len(ruta) <= largo else "…" + ruta[-(largo - 1):]


_TIPOS_JUEGO = ("juego", "saga", "consola", "compañía")   # lo que internet confirma como juego o compañía
_TIPOS_NO = ("ninguno", "persona")                       # lo que internet dice que no es juego


def _verificada(m: dict) -> bool:
    """Un nombre que internet confirma como juego, saga, consola o compañía."""
    return bool(m.get("known")) and m.get("web") in _TIPOS_JUEGO


def _descartada(m: dict) -> bool:
    """Internet dice que no es juego, consola ni compañía (ni es palabra clave confirmada)."""
    return not m.get("known") and m.get("web") in _TIPOS_NO



def _a_papelera(ruta: str) -> bool:
    """A la Papelera de Windows (recuperable). Aparte para que las pruebas la sustituyan."""
    from .library import _to_trash
    return bool(_to_trash(ruta))


def _miniatura_ruta(ruta: str) -> str:
    """Dónde se guarda la miniatura (160×90) de un archivo de la carpeta de una palabra."""
    try:
        st = os.stat(ruta)
        clave = f"{os.path.normcase(os.path.abspath(ruta))}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        clave = os.path.normcase(os.path.abspath(ruta))
    h = hashlib.md5(clave.encode("utf-8")).hexdigest()
    return os.path.join(str(cache_dir("clips_carpetas")), h + ".png")


def _hacer_miniatura(ruta: str, salida: str) -> bool:
    """Miniatura de una imagen o de un fotograma de un video. Corre en segundo plano (sin Qt de ventanas)."""
    try:
        if kind_for_path(ruta) == KIND_VIDEO:
            for t in (1.0, 0.0):
                MEDIA.run_quiet([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", ruta,
                                 "-frames:v", "1", "-vf", "scale=320:-2", salida], timeout=60)
                if os.path.isfile(salida) and os.path.getsize(salida) > 0:
                    break
            img = QImage(salida)
        else:
            img = QImage(ruta)
        if img.isNull():
            return False
        img.scaled(MINI_W, MINI_H, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(salida, "PNG")
        return os.path.isfile(salida)
    except Exception:  # noqa: BLE001 - sin miniatura se muestra el hueco
        return False



class _Clic(QLabel):
    """Texto de una fila de momentos: al pulsarlo avisa (para ir a ese momento)."""
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _Lista(QListWidget):
    """Lista que acepta archivos y carpetas soltados desde el Explorador: soltado(rutas, fila bajo el cursor o -1).
    arrastrar=True: sus elementos (con la ruta en UserRole) salen como archivos para soltarlos en la línea de tiempo."""
    soltado = Signal(list, int)

    def __init__(self, arrastrar: bool = False, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        if arrastrar:
            self.setDragEnabled(True)
            self.setDragDropMode(QAbstractItemView.DragOnly)

    @staticmethod
    def _rutas(mime) -> list[str]:
        if mime is None or not mime.hasUrls():
            return []
        return [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, e):
        if self._rutas(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        rutas = self._rutas(e.mimeData())
        if not rutas:
            e.ignore()
            return
        it = self.itemAt(e.position().toPoint())
        e.acceptProposedAction()
        self.soltado.emit(rutas, self.row(it) if it is not None else -1)

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items if it.data(Qt.UserRole)])
        from .common import NOAUDIO_MIME
        md.setData(NOAUDIO_MIME, b"1")          # 🔇 lo de Palabras clave entra en la línea de tiempo sin su audio
        return md



class _FilaLike(QStyledItemDelegate):
    """«Dijiste…»: cada fila lleva a su derecha 👍 / 👎 (clic = me gusta / no me gusta esa palabra)."""
    ANCHO = 26

    def __init__(self, al_pulsar, parent=None):
        super().__init__(parent)
        self.al_pulsar = al_pulsar        # al_pulsar(palabra, si)
        self._doble = False               # el soltar que sigue a un doble clic no cuenta otra vez

    def zonas(self, rect: QRect) -> tuple[QRect, QRect]:
        w = self.ANCHO
        no = QRect(rect.right() - w + 1, rect.top(), w, rect.height())
        si = QRect(no.left() - w, rect.top(), w, rect.height())
        return si, no

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(2 * self.ANCHO + 40, max(s.height(), 22))   # ancho del panel: el texto se recorta con «…»

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        estilo = opt.widget.style() if opt.widget is not None else None
        if estilo is not None:              # fondo (elegida / bajo el ratón) en toda la fila
            estilo.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)
        texto = QStyleOptionViewItem(option)
        texto.rect = option.rect.adjusted(0, 0, -2 * self.ANCHO - 4, 0)   # el texto no pisa los botones
        super().paint(painter, texto, index)
        si, no = self.zonas(option.rect)
        gusta = index.data(ROL_LIKE) == "si"
        painter.save()
        for zona, icono, encendido in ((si, "👍", gusta), (no, "👎", False)):
            painter.setOpacity(1.0 if encendido else 0.55)
            painter.drawText(zona, Qt.AlignCenter, icono)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) \
                and event.button() == Qt.LeftButton:
            si, no = self.zonas(option.rect)
            pos = event.position().toPoint()
            if si.contains(pos) or no.contains(pos):
                if event.type() == QEvent.MouseButtonDblClick:
                    self._doble = True
                return True                  # (el clic en el botón no elige la fila ni salta el cabezal)
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            si, no = self.zonas(option.rect)
            pos = event.position().toPoint()
            if si.contains(pos) or no.contains(pos):
                if self._doble:
                    self._doble = False      # (doble clic = un solo 👍/👎)
                    return True
                term, gusta = index.data(ROL_TERM), si.contains(pos)
                if term:                     # (después del evento: la lista se rehace al guardar)
                    QTimer.singleShot(0, lambda: self.al_pulsar(term, gusta))
                return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):
        if event is not None and index.isValid():
            si, no = self.zonas(option.rect)
            if si.contains(event.pos()):
                QToolTip.showText(event.globalPos(), "👍 Me gusta: es palabra clave (se le crea su carpeta)", view)
                return True
            if no.contains(event.pos()):
                QToolTip.showText(event.globalPos(), "👎 No me gusta: no es palabra clave (deja de proponerse)", view)
                return True
        return super().helpEvent(event, view, option, index)


class ClipsPanel(InternetMixin, QWidget):
    seek_requested = Signal(float)
    hints_changed = Signal(list)      # [(segundo, texto)] → marcas de la línea de tiempo

    def __init__(self, ctrl, timeline=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.timeline = timeline          # guardado para quien lo conecte; el panel solo emite señales
        self.raiz = _raiz_guardada()      # carpeta con una subcarpeta por palabra
        self.carpetas: list[dict] = []
        self.carpeta: dict | None = None  # carpeta de la palabra elegida (None = todavía no tiene)
        self.menciones: list[dict] = []
        self._pendiente = False           # hay cambios sin recalcular (el panel estaba oculto)
        self._firma_ultima = None         # lo que había la última vez que se buscaron las menciones (ver _firma)
        self._firma_verificada = None     # la firma ya consultada en internet (ver _verificar_si_toca)
        self._job_web = None              # consulta a internet en segundo plano (nombres propios)
        self.mencion: dict | None = None
        self._items_carpeta: dict[str, QListWidgetItem] = {}
        self._tok_carpeta = 0
        self._job_carpeta = None
        self._marcas_quitadas = False     # ✕: no mostrar marcas hasta elegir otra mención
        self._desmarcados: set = set()    # momentos que el usuario desmarcó (término, segundo del archivo)
        self._casillas: list[tuple[QCheckBox, dict]] = []
        self.pestanas = None              # solo con la parte opcional: dos pestañas (ver _construir_pestanas)
        if HAY_INTERNET:
            self._iniciar_estado()
        self._construir()
        self._vigia = QFileSystemWatcher(self)
        self._vigia.directoryChanged.connect(self._programar)
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(1000)
        self._temporizador.timeout.connect(self._al_temporizador)
        if getattr(ctrl, "transcript_changed", None) is not None:
            ctrl.transcript_changed.connect(self._programar)
        for nombre in ("project_changed", "project_replaced"):
            senal = getattr(ctrl, nombre, None)
            if senal is not None:
                senal.connect(self._programar)
        self._pendiente = True            # se calcula al mostrarse (o cuando la guía lo pida: ensure_fresh)
        if HAY_INTERNET:
            self._pestana_cambiada()

    # ------------------------------------------------------------------ interfaz
    def _construir(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        raiz = QHBoxLayout()
        self.lbl_raiz = QLabel()
        self.btn_cambiar_raiz = QPushButton("Cambiar…")
        self.btn_cambiar_raiz.setToolTip("Elige la carpeta donde tienes una subcarpeta por palabra "
                                         "(«Fortnite», «Minecraft»…) con tus videos e imágenes.")
        self.btn_cambiar_raiz.clicked.connect(self._cambiar_raiz)
        self.btn_abrir_raiz = QPushButton("Abrir")
        self.btn_abrir_raiz.setToolTip("Abre la carpeta raíz en el Explorador.")
        self.btn_abrir_raiz.clicked.connect(self._abrir_raiz)
        raiz.addWidget(self.lbl_raiz, 1)
        raiz.addWidget(self.btn_cambiar_raiz)
        raiz.addWidget(self.btn_abrir_raiz)
        v.addLayout(raiz)
        self._pintar_raiz()

        cab = QHBoxLayout()
        titulo = QLabel("<b>Dijiste…</b>")
        titulo.setToolTip("Palabras de tu narración que parecen juegos, compañías, tus carpetas o tus palabras de "
                          "vocabulario. Pulsa una para ir a donde la dices.")
        self.btn_recalc = QPushButton("↻")
        self.btn_recalc.setFixedWidth(34)
        self.btn_recalc.setToolTip("Volver a leer la narración y las carpetas")
        self.btn_recalc.clicked.connect(self.recalcular)
        self.btn_quitar = QPushButton("✕")
        self.btn_quitar.setFixedWidth(34)
        self.btn_quitar.setToolTip("Quitar de la línea de tiempo las marcas de esta palabra")
        self.btn_quitar.clicked.connect(self._quitar_marcas)
        self.btn_glosario = QPushButton("📖 Glosario…")
        self.btn_glosario.setToolTip("Palabras que sí son palabras clave y palabras que no. Lo que confirmas aquí "
                                     "se respeta en «Dijiste…» y en «✨ Crear de lo que dices».")
        self.btn_glosario.clicked.connect(self._abrir_glosario)
        self.btn_todo = QPushButton("⚡ Agregar todo")
        self.btn_todo.setToolTip("Agrega a la línea de tiempo, de una vez, el material de las carpetas (lo descargado "
                                 "y lo de tu computadora) justo donde dices cada palabra clave, con la duración de tu "
                                 "frase y sin repetir. Un Ctrl+Z lo quita.")
        self.btn_todo.clicked.connect(self.agregar_todo)
        self.btn_amplia = QPushButton("🗂 Carpetas")
        self.btn_amplia.setToolTip("Muestra la pestaña «🗂 Carpetas» (a la derecha, junto al Inspector): la carpeta de "
                                   "la palabra elegida, con lo descargado y lo de tu computadora por separado (y para "
                                   "borrarlo fácil)")
        self.btn_amplia.clicked.connect(self.abrir_ventana)
        cab.addWidget(titulo)
        cab.addStretch(1)
        cab.addWidget(self.btn_todo)
        cab.addWidget(self.btn_amplia)
        cab.addWidget(self.btn_glosario)
        cab.addWidget(self.btn_quitar)
        cab.addWidget(self.btn_recalc)
        v.addLayout(cab)

        self.lista_menciones = _Lista()
        self.lista_menciones.setMaximumHeight(130)
        self.lista_menciones.setToolTip("Lo que se dice en la narración, con cuántas veces sale. "
                                        "📁 n = tienes carpeta con n archivos · ＋ = aún no tiene carpeta. "
                                        "👍 / 👎 a la derecha = me gusta / no me gusta esa palabra. "
                                        "Puedes soltar archivos sobre una palabra. "
                                        "Clic derecho = ¿es palabra clave? (se guarda en el glosario).")
        self.lista_menciones.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista_menciones.setProperty("own_menu", True)     # su propio menú (clic derecho)
        self.lista_menciones.customContextMenuRequested.connect(
            lambda pos: self._clic_derecho(self.lista_menciones, pos))
        AYUDA.set_help(self.lista_menciones, "clips_dijiste")
        self.lista_menciones.setMouseTracking(True)
        self.lista_menciones.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # 👍/👎 siempre a la vista
        self.lista_menciones.setTextElideMode(Qt.ElideRight)
        self._ultimo_like = QElapsedTimer()
        self.lista_menciones.setItemDelegate(_FilaLike(self._like_fila, self.lista_menciones))
        self.lista_menciones.currentRowChanged.connect(lambda fila: self._elegir_mencion(fila, buscar=True))
        self.lista_menciones.soltado.connect(self._soltar_archivos)
        v.addWidget(self.lista_menciones)

        self.lista_momentos = QListWidget()
        self.lista_momentos.setMaximumHeight(120)
        self.lista_momentos.setToolTip("Dónde sale la palabra elegida. Casilla = poner el clip ahí · "
                                       "pulsa el texto para ir a ese momento · 📍 = poner el clip solo ahí.")
        v.addWidget(self.lista_momentos)

        mi = self._construir_mi_carpeta()
        if HAY_INTERNET:
            self.pestanas = self._construir_pestanas(mi)
            v.addWidget(self.pestanas, 1)
        else:
            v.addWidget(mi, 1)

        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.aviso.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        v.addWidget(self.aviso)

    def _construir_mi_carpeta(self) -> QWidget:
        w = QWidget()
        mv = QVBoxLayout(w)
        mv.setContentsMargins(0, 4, 0, 0)
        mv.setSpacing(6)
        fila = QHBoxLayout()
        self.lbl_carpeta = QLabel("")
        self.lbl_carpeta.setWordWrap(True)
        self.btn_actualizar = QPushButton("⟳")
        self.btn_actualizar.setFixedWidth(34)
        self.btn_actualizar.setToolTip("Volver a leer esta carpeta (lo que añadiste desde el Explorador)")
        self.btn_actualizar.clicked.connect(self.recalcular)
        fila.addWidget(self.lbl_carpeta, 1)
        fila.addWidget(self.btn_actualizar)
        mv.addLayout(fila)

        self.btn_crear = QPushButton()
        self.btn_crear.setMinimumHeight(34)
        self.btn_crear.setToolTip("Crea la carpeta de esta palabra dentro de la carpeta raíz. Luego suelta ahí "
                                  "tus videos e imágenes (o suéltalos directamente aquí).")
        self.btn_crear.clicked.connect(lambda: self._crear_carpeta())
        self.btn_crear.setVisible(False)
        mv.addWidget(self.btn_crear)

        self.lista_carpeta = _Lista(arrastrar=True)
        self.lista_carpeta.setProperty("own_menu", True)     # su propio menú (clic derecho)
        self.lista_carpeta.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista_carpeta.customContextMenuRequested.connect(
            lambda pos: self._clic_derecho(self.lista_carpeta, pos))
        self.lista_carpeta.setViewMode(QListView.IconMode)
        self.lista_carpeta.setIconSize(QSize(MINI_W, MINI_H))
        self.lista_carpeta.setGridSize(QSize(MINI_W + 24, MINI_H + 40))
        self.lista_carpeta.setResizeMode(QListView.Adjust)
        self.lista_carpeta.setMovement(QListView.Static)
        self.lista_carpeta.setWordWrap(True)
        self.lista_carpeta.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lista_carpeta.setSpacing(4)
        self.lista_carpeta.setToolTip("Tu material para esta palabra. Doble clic = ponerlo donde lo dices · "
                                      "clic derecho = menú · arrastra o suelta archivos aquí.")
        self.lista_carpeta.itemDoubleClicked.connect(lambda it: self._poner_mis([it.data(Qt.UserRole)]))
        self.lista_carpeta.soltado.connect(lambda rutas, _f: self._soltar_archivos(rutas))
        mv.addWidget(self.lista_carpeta, 1)

        fb = QHBoxLayout()
        self.btn_cabezal_mio = QPushButton("⏵ Poner en el cabezal")
        self.btn_cabezal_mio.setToolTip("Pone los archivos seleccionados donde está el cabezal (la línea roja).")
        self.btn_cabezal_mio.clicked.connect(lambda: self._poner_elegido(self._hits_cabezal()))
        self.btn_poner_mio = QPushButton("📍 Poner donde lo dices")
        self.btn_poner_mio.setToolTip("Pone los archivos seleccionados en los momentos marcados de la palabra. "
                                      "Con varios, se reparten por orden.")
        self.btn_poner_mio.clicked.connect(lambda: self._poner_elegido())
        fb.addWidget(self.btn_cabezal_mio)
        fb.addWidget(self.btn_poner_mio)
        mv.addLayout(fb)
        return w

    def _aviso(self, texto: str):
        self.aviso.setText(texto)

    def showEvent(self, e):
        super().showEvent(e)
        self._programar()                 # al mostrarse: relee la narración y las carpetas (lo soltado en el Explorador)

    # ------------------------------------------------------------------ carpeta raíz y carpetas por palabra
    def _pintar_raiz(self):
        self.lbl_raiz.setText("📁 " + _corta(self.raiz))
        self.lbl_raiz.setToolTip(self.raiz)

    def _cambiar_raiz(self):
        elegida = QFileDialog.getExistingDirectory(self, "Carpeta de tus clips por palabra", self.raiz)
        if not elegida:
            return
        _ajustes().setValue(RAIZ_CLAVE, elegida)
        self.raiz = elegida
        self._pintar_raiz()
        self.recalcular()

    def _abrir_raiz(self):
        try:
            os.makedirs(self.raiz, exist_ok=True)
        except OSError as exc:
            self._aviso(f"No pude crear la carpeta: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.raiz))

    def _leer_carpetas(self):
        try:
            self.carpetas = KF.list_folders(self.raiz)
        except Exception:  # noqa: BLE001 - una carpeta rara no debe romper el panel
            self.carpetas = []

    def _carpeta_de(self, term: str) -> dict | None:
        if not term:
            return None
        try:
            return KF.match(term, self.carpetas)
        except Exception:  # noqa: BLE001
            return None

    def _vigilar(self):
        """Mira la carpeta raíz y la de la palabra elegida: lo que sueltes en el Explorador aparece solo."""
        for ruta in list(self._vigia.directories()):
            self._vigia.removePath(ruta)
        for ruta in (self.raiz, self.carpeta["path"] if self.carpeta else None):
            if ruta and os.path.isdir(ruta):
                self._vigia.addPath(ruta)

    def _pintar_carpeta(self):
        """La cuadrícula de la carpeta de la palabra elegida (miniaturas) o el botón de crearla."""
        term = self.mencion["term"] if self.mencion else ""
        car = self._carpeta_de(term)
        self.carpeta = car
        self._tok_carpeta += 1
        tok = self._tok_carpeta
        self.lista_carpeta.clear()
        self._items_carpeta = {}
        self._vigilar()
        if not term:
            self.lbl_carpeta.setText("Elige una palabra de «Dijiste…».")
            self.lbl_carpeta.setToolTip("")
            self.btn_crear.setVisible(False)
            return
        if car is None:
            self.lbl_carpeta.setText(f"«{term}» aún no tiene carpeta.")
            self.lbl_carpeta.setToolTip(f"Se creará dentro de {self.raiz}")
            self.btn_crear.setText(f"＋ Crear carpeta «{term}»")
            self.btn_crear.setVisible(True)
            return
        self.btn_crear.setVisible(False)
        n = car["count"]
        self.lbl_carpeta.setText(f"📁 «{car['label']}» · {n} {'archivo' if n == 1 else 'archivos'}")
        self.lbl_carpeta.setToolTip(car["path"])
        pendientes: list[str] = []
        enlazados = set(car.get("linked_files") or [])
        for ruta in car["files"]:
            es_enlace = ruta in enlazados
            it = QListWidgetItem(("🔗 " if es_enlace else "") + os.path.basename(ruta))
            it.setData(Qt.UserRole, ruta)
            it.setToolTip(ruta + ("\nCarpeta enlazada de tu PC (no se copia)" if es_enlace else ""))
            png = _miniatura_ruta(ruta)
            pm = QPixmap(png) if os.path.isfile(png) else QPixmap()
            if not pm.isNull():
                it.setIcon(QIcon(pm))
            else:
                pendientes.append(ruta)
            self.lista_carpeta.addItem(it)
            self._items_carpeta[ruta] = it
        if pendientes:
            self._cargar_miniaturas_carpeta(pendientes, tok)

    def _cargar_miniaturas_carpeta(self, rutas: list[str], tok: int):
        if self._job_carpeta is not None:
            self._job_carpeta.cancel()

        def trabajo(progreso, cancelado, emitir):
            for k, ruta in enumerate(rutas):
                if cancelado():
                    return None
                salida = _miniatura_ruta(ruta)
                if _hacer_miniatura(ruta, salida):
                    emitir((ruta, salida))
                progreso((k + 1) / len(rutas), "Miniaturas")
            return None

        job = BackgroundJob(trabajo, self, with_partial=True)
        job.partial.connect(lambda par, t=tok: self._llego_miniatura_carpeta(par, t))
        self._job_carpeta = job
        job.start()

    def _llego_miniatura_carpeta(self, par, tok: int):
        if tok != self._tok_carpeta:
            return
        ruta, png = par
        it = self._items_carpeta.get(ruta)
        pm = QPixmap(png)
        if it is not None and not pm.isNull():
            it.setIcon(QIcon(pm))

    def _crear_carpeta(self, term: str | None = None):
        term = term or (self.mencion["term"] if self.mencion else "")
        if not term:
            self._aviso("Elige primero una palabra de «Dijiste…».")
            return
        try:
            KF.create_folder(self.raiz, term)
        except Exception as exc:  # noqa: BLE001
            self._aviso(f"No pude crear la carpeta: {exc}")
            return
        self._aviso(f"✓ Carpeta «{term}» creada. Suelta ahí tus videos e imágenes.")
        self.recalcular()

    def abrir_ventana(self):
        """🗂 Carpetas: la pestaña de la derecha (o, si no la hay, la ventana amplia)."""
        dock = getattr(self, "carpetas_dock", None)
        win = self.window()
        if dock is not None and hasattr(win, "show_panel"):
            win.show_panel(dock)
            if not dock.isVisible():
                dock.refrescar()
            return dock
        from .keywords_window import abrir
        return abrir(self)

    def agregar_todo(self):
        """⚡ Agregar todo: el material de cada carpeta donde dices su palabra (el «⚡ Acomodar todo» de la fila 🔑)."""
        tl = self.timeline
        if tl is None or not hasattr(tl, "kw_arrange_requested"):
            self._aviso("No encuentro la línea de tiempo.")
            return
        if not self.carpetas:
            self._leer_carpetas()
        if not self.carpetas:
            self._aviso("Aún no hay carpetas: pulsa 👍 en una palabra (o 🗂 Carpetas) y añádele material.")
            return
        arr = getattr(self.window(), "kw_arranger", None)
        if arr is not None and getattr(arr, "_arr_job", None) is not None:
            self._aviso("⚡ Ya se está agregando: espera a que termine.")
            return
        self._aviso("⚡ Agregando el material donde dices cada palabra clave… el resultado sale abajo, en la barra "
                    "de estado (Ctrl+Z lo quita).")
        QTimer.singleShot(10000, lambda: self.aviso.text().startswith("⚡ Agregando") and self._aviso(""))
        tl.kw_arrange_requested.emit()

    def _like_fila(self, term: str, si: bool):
        """👍 / 👎 pulsado en una fila de «Dijiste…» (por la palabra, no por el número de fila)."""
        if self._ultimo_like.isValid() and self._ultimo_like.elapsed() < QApplication.doubleClickInterval():
            return                            # (dos clics seguidos: el segundo caería en otra palabra)
        self._ultimo_like.start()
        m = next((m for m in self.menciones if m["term"] == term), None)
        if m is not None:
            self._like(si, m)

    def _like(self, si: bool, mencion: dict | None = None):
        """👍 / 👎 de una palabra de «Dijiste…» (la elegida si no se dice cuál; 👍 además le crea su carpeta)."""
        mencion = mencion or self.mencion
        if not mencion:
            self._aviso("Elige antes una palabra de «Dijiste…».")
            return
        term = mencion["term"]
        try:
            if si:
                KG.add_yes(term, mencion.get("web") if mencion.get("web") in KG.TIPOS else None)
                if self._carpeta_de(term) is None:
                    KF.create_folder(self.raiz, term)
            else:
                KG.add_no(term)
        except OSError as exc:
            self._aviso(f"No pude guardarlo: {exc}")
            return
        self.recalcular()
        car = None if si else self._carpeta_de(term)
        extra = (f" Su carpeta sigue ahí ({car['count']} archivo(s)): bórrala en 🗂 Carpetas o deshazlo en el "
                 "📖 Glosario." if car and car["count"] else "")
        self._aviso(f"👍 «{term}» es palabra clave y ya tiene su carpeta: añádele material (o 🗂 Carpetas)." if si
                    else f"👎 «{term}» ya no se propone como palabra clave.{extra}")

    def _soltar_archivos(self, rutas: list, fila: int = -1, term: str | None = None):
        """Archivos o carpetas soltados: van a la carpeta de la palabra (term, fila de «Dijiste…» o la elegida)."""
        term = term or ""
        if term:
            pass
        elif 0 <= fila < len(self.menciones):
            term = self.menciones[fila]["term"]
        elif self.mencion:
            term = self.mencion["term"]
        if not term:
            self._aviso("Elige primero una palabra de «Dijiste…» para soltar ahí.")
            return
        enlazadas, sueltos = 0, [r for r in rutas if not os.path.isdir(r)]
        modo = modo_archivo_suelto(self) if sueltos else None   # archivo suelto: enlazar o copiar (pregunta una vez)
        enlazados_f, nuevos = 0, []
        try:
            for r in rutas:                 # una carpeta del Explorador se ENLAZA (no se copia)
                if os.path.isdir(r):
                    KF.link_folder(self.raiz, term, r)
                    enlazadas += 1
            if sueltos and modo == "enlazar":
                for r in sueltos:
                    try:
                        KF.link_file(self.raiz, term, r)
                        enlazados_f += 1
                    except ValueError:
                        pass
            elif sueltos and modo == "copiar":
                car = self._carpeta_de(term)
                carpeta = car["path"] if car else KF.create_folder(self.raiz, term)
                nuevos = KF.add_files(carpeta, sueltos)
        except Exception as exc:  # noqa: BLE001
            self._aviso(f"No pude añadir: {exc}")
            return
        partes = []
        if enlazadas:
            partes.append(f"🔗 {enlazadas} carpeta(s) enlazada(s) (no se copian)")
        if enlazados_f:
            partes.append(f"🔗 {enlazados_f} archivo(s) enlazado(s) (no se copian)")
        if nuevos:
            partes.append(f"{len(nuevos)} archivo(s) copiado(s)")
        if partes:
            self._aviso("✓ " + " y ".join(partes) + f" en «{term}».")
        else:
            self._aviso("Solo se pueden soltar videos, imágenes o carpetas.")
        self.recalcular()

    def _rutas_seleccion(self) -> list[str]:
        its = sorted(self.lista_carpeta.selectedItems(), key=lambda it: self.lista_carpeta.row(it))
        return [it.data(Qt.UserRole) for it in its if it.data(Qt.UserRole)]

    # ------------------------------------------------------------------ menciones
    def _a_la_vista(self) -> bool:
        return self.isVisible() or any(w is not None and w.isVisible()
                                       for w in (getattr(self, "_ventana_amplia", None),
                                                 getattr(self, "carpetas_dock", None)))

    def _programar(self, *_):
        """Un cambio (proyecto, carpeta vigilada…): con el panel oculto solo queda pendiente; no escanea nada."""
        if not self._a_la_vista():
            self._temporizador.stop()
            self._pendiente = True
            return
        self._temporizador.start()

    def _al_temporizador(self):
        if self._a_la_vista():
            self.recalcular(solo_si_cambio=True)
        else:
            self._pendiente = True

    def ensure_fresh(self):
        """Si hay un recálculo pendiente (el panel estuvo oculto), lo hace ya. Lo usa la guía al mostrar sus pasos."""
        if self._pendiente or self._temporizador.isActive():
            self.recalcular(solo_si_cambio=True)

    def _firma(self):
        """Lo que decide «Dijiste…»: la narración (su texto y dónde suena en la timeline) y las carpetas."""
        p = self.ctrl.project
        narr = tuple((mid, tr.get("words"), mapping.media_layout_key(p, mid))
                     for mid, tr in p.transcripts.items())
        return (narr, repr(self.carpetas), repr(KG.load()))   # el glosario también: cambia lo que sale

    def recalcular(self, solo_si_cambio: bool = False):
        """Vuelve a leer la narración del proyecto y las carpetas (rápido). Si ya había una mención elegida, sigue
        elegida sin buscar otra vez ni mover el cabezal: solo se refrescan sus momentos y su carpeta.
        solo_si_cambio: si nada de lo que cuenta cambió desde la última vez, no busca otra vez (⚡ con mucho texto)."""
        self._temporizador.stop()
        self._pendiente = False
        anterior = self.mencion["term"] if self.mencion else None
        self._leer_carpetas()
        firma = self._firma()
        if solo_si_cambio and firma == self._firma_ultima:
            self._verificar_si_toca()
            self._avisar_ventana()
            return
        self._firma_ultima = firma
        try:
            self.menciones = find_mentions(self.ctrl.project, extra_terms=KF.terms(self.carpetas),
                                           glossary=KG.load())
        except Exception as exc:  # noqa: BLE001 - el panel nunca debe romper el programa
            self.menciones = []
            self._aviso(f"No pude leer la narración: {exc}")
        dichas = bool(self.menciones)
        self.menciones += self._no_dichas(self.menciones)       # (al final: tus carpetas que no dices)
        self._pintar_menciones(anterior)
        if not dichas and self.menciones:
            self._elegir_mencion(self.lista_menciones.currentRow(), buscar=False)
            self._aviso("No dices ninguna de tus palabras clave en la narración (¿falta transcribirla?). "
                        "Abajo están tus carpetas.")
            self._avisar_ventana()
            return
        if not self.menciones:
            self.mencion = None
            self.lista_momentos.clear()
            self._casillas = []
            self._marcas()
            self._pintar_carpeta()
            self._aviso("No encuentro nombres ni palabras de tu vocabulario en la narración.")
            self._avisar_ventana()
            return
        self._elegir_mencion(self.lista_menciones.currentRow(), buscar=False)
        self._aviso("")
        self._verificar_si_toca()
        self._avisar_ventana()

    def _avisar_ventana(self):
        for w in (getattr(self, "_ventana_amplia", None), getattr(self, "carpetas_dock", None)):
            if w is not None:
                w.al_dia()

    def _no_dichas(self, dichas: list[dict]) -> list[dict]:
        """Tus carpetas de palabras que no salen en la narración (sin momentos), para verlas y darles 👍/👎."""
        usadas = set()
        for m in dichas:
            car = self._carpeta_de(m["term"])
            if car:
                usadas.add(os.path.normcase(car["path"]))
        try:
            g = KG.load()
        except Exception:  # noqa: BLE001
            g = {"no": []}
        out = []
        for c in self.carpetas:
            if os.path.normcase(c["path"]) in usadas or KG.is_no(c["label"], g):
                continue
            out.append({"term": c["label"], "count": 0, "hits": [], "known": True, "no_dicha": True})
        return out

    def _orden(self, m: dict) -> int:
        """Las palabras con carpeta, primero; luego las demás; las que internet descarta y las que no dices, al
        final."""
        if m.get("no_dicha"):
            return 3
        if _descartada(m):
            return 2
        return 0 if self._carpeta_de(m["term"]) else 1

    def _pintar_menciones(self, anterior: str | None):
        """Pinta «Dijiste…» con self.menciones. Deja elegida la palabra «anterior» si sigue, sin emitir señales."""
        self.menciones.sort(key=self._orden)
        try:
            si_glosario = set(KG.load()["si"])
        except Exception:  # noqa: BLE001
            si_glosario = set()
        self.lista_menciones.blockSignals(True)
        self.lista_menciones.clear()
        fila_previa = -1
        for i, m in enumerate(self.menciones):
            car = self._carpeta_de(m["term"])
            badge = f"📁 {car['count']}" if car else "＋"
            if m.get("no_dicha"):
                it = QListWidgetItem(f"{m['term']} · no lo dices    {badge}")
                it.setData(Qt.UserRole, i)
                it.setData(ROL_LIKE, "si" if KG.clave(m["term"]) in si_glosario else "")
                it.setData(ROL_TERM, m["term"])
                it.setForeground(QColor("#6b6f78"))
                it.setToolTip(f"Tienes carpeta «{car['label'] if car else m['term']}» pero no lo dices en la "
                              "narración. Su material se puede poner en el cabezal (🗂 Carpetas).")
                self.lista_menciones.addItem(it)
                if anterior and m["term"] == anterior and fila_previa < 0:
                    fila_previa = i
                continue
            primero = m["hits"][0]
            tl = _momento(primero)
            cuando = _mmss(tl) if tl is not None else "cortado"
            veces = f"{m['count']} {'vez' if m['count'] == 1 else 'veces'}"
            verificada = _verificada(m)
            sufijo = f"  ✓ {m['web']}" if verificada else ""
            it = QListWidgetItem(f"{m['term']} · {veces} · {cuando}    {badge}{sufijo}")
            it.setData(Qt.UserRole, i)
            it.setData(ROL_LIKE, "si" if KG.clave(m["term"]) in si_glosario else "")
            it.setData(ROL_TERM, m["term"])
            pistas: list[str] = []
            if verificada:
                pistas.append(f"✓ Según internet: {m['web']} (Wikidata o Wikipedia). Clic derecho para cambiarlo.")
            if _descartada(m):
                pistas.append("Según internet no es un juego, consola ni compañía. "
                              "Clic derecho si sí es palabra clave.")
                it.setForeground(QColor("#6b6f78"))
            elif car:
                pistas.append(f"Tienes {car['count']} archivo(s) en «{car['label']}». "
                              f"Primera vez en {_mmss(primero['src'])} del archivo.")
            else:
                pistas.append("Aún no tiene carpeta. Suelta archivos aquí o pulsa ＋ en «Mi carpeta» para crearla.")
                it.setForeground(QColor("#6b6f78"))
            it.setToolTip("\n".join(pistas))
            self.lista_menciones.addItem(it)
            if anterior and m["term"] == anterior and fila_previa < 0:
                fila_previa = i
        if self.menciones:
            self.lista_menciones.setCurrentRow(fila_previa if fila_previa >= 0 else 0)
        self.lista_menciones.blockSignals(False)

    # ------------------------------------------------------------------ internet y glosario
    def _verificar_si_toca(self):
        """Pregunta a internet por los nombres propios que aún no sabe (en segundo plano). Solo con el panel a la
        vista; una vez por cada narración y carpetas (la firma). Sin conexión no molesta: no avisa."""
        firma = self._firma_ultima
        if not self.isVisible() or firma is None or firma == self._firma_verificada or not self.menciones:
            return
        self._firma_verificada = firma
        pendientes = [m for m in self.menciones if not m.get("known") and "web" not in m]
        if not pendientes:
            return
        copia = [dict(m) for m in self.menciones]
        job = BackgroundJob(lambda _progreso, _cancelado: verify_online(copia, KG.load()), self)
        job.done.connect(lambda res, f=firma: self._web_listo(res, f))
        self._job_web = job
        job.start()

    def _web_listo(self, res, firma):
        """Llegó la respuesta de internet: vuelve a pintar la lista sin perder la palabra elegida ni sus marcas."""
        if firma != self._firma_ultima or not isinstance(res, list):
            return                                   # la narración o las carpetas cambiaron mientras tanto
        anterior = self.mencion["term"] if self.mencion else None
        self.menciones = res
        self._pintar_menciones(anterior)
        fila = self.lista_menciones.currentRow()
        if anterior is not None and 0 <= fila < len(self.menciones):
            self.mencion = self.menciones[fila]

    def _menu_mencion(self, it: QListWidgetItem) -> QMenu | None:
        """Clic derecho en «Dijiste…»: guardar en el glosario como palabra clave o como «no»."""
        fila = it.data(Qt.UserRole)
        if not isinstance(fila, int) or not (0 <= fila < len(self.menciones)):
            return None
        m = self.menciones[fila]
        term = m["term"]
        g = KG.load()
        k = KG.clave(term)
        tipo = m.get("web") if m.get("web") in KG.TIPOS else None
        menu = QMenu(self.lista_menciones)
        if k not in g["si"]:
            menu.addAction("👍 Es palabra clave (guardar en el glosario)",
                           lambda: self._glosario_cambia(KG.add_yes, term, tipo))
        menu.addAction("👎 No es palabra clave", lambda: self._glosario_cambia(KG.add_no, term))
        if k in g["si"] or k in g["no"]:
            menu.addAction("↺ Quitar del glosario", lambda: self._glosario_cambia(KG.remove, term))
        AYUDA.add_help_action(menu, AYUDA.help_key_for(self.lista_menciones), self)
        return menu

    def _glosario_cambia(self, fn, term: str, *extra):
        """Aplica un cambio al glosario y recalcula «Dijiste…» (sin mirar la firma)."""
        try:
            fn(term, *extra)
        except OSError as exc:
            self._aviso(f"No pude guardar el glosario: {exc}")
            return
        self.recalcular()
        self._aviso(f"✓ «{term}» actualizado en el glosario.")

    def _abrir_glosario(self):
        dlg = GlosarioDialog(self)
        dlg.exec()
        if dlg.cambiado:
            self.recalcular()

    def _elegir_mencion(self, fila: int, buscar: bool = True):
        """Muestra los momentos y la carpeta de la mención. buscar=True (la eligió el usuario): va al primer momento
        y, si hay parte opcional, busca."""
        if fila < 0 or fila >= len(self.menciones):
            return
        m = self.menciones[fila]
        cambio = not self.mencion or self.mencion.get("term") != m["term"]
        self.mencion = m
        if buscar:
            self._marcas_quitadas = False
        self._llenar_momentos(m)
        self._marcas()
        self._pintar_carpeta()
        dock = getattr(self, "carpetas_dock", None)
        if dock is not None:
            dock._seguir(m["term"])                   # 🗂 Carpetas (a la derecha) enseña la de esta palabra
        if not HAY_INTERNET:
            return
        if not buscar:
            if cambio:
                self._pintar_mods(m.get("mods") or [])
            return
        primero = next((h for h in m["hits"] if _momento(h) is not None), None)
        if primero is not None:
            self.seek_requested.emit(float(primero["tl"]))
        self._pintar_mods(m.get("mods") or [])
        self._buscar(m["term"], self._mods_marcados(), self._tipo())

    def _llenar_momentos(self, m: dict):
        """Una fila por momento: casilla (poner el clip ahí), mm:ss + contexto (pulsar = ir) y 📍 (poner solo ahí)."""
        self.lista_momentos.clear()
        self._casillas = []
        for h in m["hits"]:
            tl = _momento(h)
            cuando = _mmss(tl) if tl is not None else f"({_mmss(h['src'])} del archivo)"
            clave = (m["term"], round(float(h["src"]), 2))
            fila = QWidget()
            hl = QHBoxLayout(fila)
            hl.setContentsMargins(4, 0, 4, 0)
            hl.setSpacing(6)
            cas = QCheckBox()
            cas.setEnabled(tl is not None)
            cas.setChecked(tl is not None and clave not in self._desmarcados)
            cas.setToolTip("Poner el clip en este momento" if tl is not None else "Ese momento está cortado")
            cas.toggled.connect(lambda on, k=clave: self._desmarcados.discard(k) if on else self._desmarcados.add(k))
            lab = _Clic(f"{cuando}   {h['context']}")
            lab.setTextFormat(Qt.PlainText)
            lab.setToolTip(h["context"] + ("\nPulsa para ir a este momento" if tl is not None else ""))
            lab.clicked.connect(lambda h=h: self._ir_momento(h))
            btn = QPushButton("📍")
            btn.setFixedWidth(34)
            btn.setEnabled(tl is not None)
            btn.setToolTip("Poner el clip seleccionado solo en este momento")
            btn.clicked.connect(lambda _c=False, h=h: self._poner_elegido([h]))
            hl.addWidget(cas)
            hl.addWidget(lab, 1)
            hl.addWidget(btn)
            it = QListWidgetItem()
            it.setSizeHint(fila.sizeHint())
            self.lista_momentos.addItem(it)
            self.lista_momentos.setItemWidget(it, fila)
            self._casillas.append((cas, h))

    def _marcas(self):
        """🎬 Las banderitas de la mención elegida en la línea de tiempo (solo los momentos con hora)."""
        if self.mencion is None or self._marcas_quitadas:
            self.hints_changed.emit([])
            return
        self.hints_changed.emit([(float(h["tl"]), "🎬 " + self.mencion["term"])
                                 for h in self.mencion["hits"] if _momento(h) is not None])

    def _quitar_marcas(self):
        self._marcas_quitadas = True
        self.hints_changed.emit([])

    def _ir_momento(self, h: dict):
        if _momento(h) is None:
            self._aviso("Ese momento está cortado en la línea de tiempo.")
            return
        self.seek_requested.emit(float(h["tl"]))

    # ------------------------------------------------------------------ 📍 poner donde lo dices
    def _cabezal(self) -> float:
        """Segundo de la línea de tiempo donde está el cabezal (la línea roja)."""
        return float(getattr(self.timeline, "playhead", 0.0) or 0.0)

    def _hits_cabezal(self) -> list[dict]:
        return [{"tl": self._cabezal(), "cabezal": True}]

    def _hits_marcados(self) -> list[dict]:
        return [h for cas, h in self._casillas if cas.isChecked() and cas.isEnabled() and _momento(h) is not None]

    def _poner_elegido(self, hits: list[dict] | None = None):
        """Los archivos elegidos (Mi carpeta, o el clip de la segunda pestaña si está abierta) en los momentos dados
        (o los marcados)."""
        if hits is None:
            hits = self._hits_marcados()
        if HAY_INTERNET and self.pestanas is not None and self.pestanas.currentIndex() == 1:
            self._poner_elegido_net(hits)
        else:
            self._poner_mis(self._rutas_seleccion(), hits)

    def _poner_mis(self, rutas: list[str], hits: list[dict] | None = None) -> bool:
        """Archivos de Mi carpeta → Medios (import_now) → en los momentos dados (o los marcados)."""
        if hits is None:
            hits = self._hits_marcados()
        if not rutas:
            self._aviso("Elige uno o más archivos de la carpeta.")
            return False
        if not any(_momento(h) is not None for h in hits):
            if self.mencion and self.mencion.get("no_dicha"):
                self._aviso(f"«{self.mencion['term']}» no sale en tu narración: usa «⏵ Poner en el cabezal».")
            else:
                self._aviso("Elige primero una palabra de «Dijiste…» y marca al menos un momento con hora.")
            return False
        try:
            ids = [i for i in (self.ctrl.import_now(list(rutas)) or []) if i]
        except Exception as exc:  # noqa: BLE001
            self._aviso(f"No pude añadir a Medios: {exc}")
            return False
        if not ids:
            self._aviso("No pude añadir esos archivos a Medios.")
            return False
        return self._repartir(ids, hits)

    def _repartir(self, ids: list[str], hits: list[dict]) -> bool:
        """Momento 1 → archivo 1, momento 2 → archivo 2… (cíclico). Un solo paso de Ctrl+Z para toda la tanda."""
        puestos, aviso = KP.repartir(self.ctrl, ids, hits)
        if aviso:
            self._aviso(aviso)
        return bool(puestos)

    def _colocar(self, media_id: str, hits: list[dict], avisar: bool = True) -> bool:
        """Pone el clip de Medios en cada momento (con su frase: 2–6 s; sin transcripción, 4 s). Un paso de Ctrl+Z."""
        ok, texto = KP.colocar(self.ctrl, media_id, hits, avisar)
        if texto:
            self._aviso(texto)
        return ok

    # ------------------------------------------------------------------ menús del clic derecho
    def _clic_derecho(self, lista: QListWidget, pos):
        it = lista.itemAt(pos)
        if it is None:
            return
        lista.setCurrentItem(it)
        if lista is self.lista_carpeta:
            menu = self._menu_carpeta(it)
        elif lista is self.lista_menciones:
            menu = self._menu_mencion(it)
        elif HAY_INTERNET:
            menu = self._menu_para(lista, it)
        else:
            return
        if menu is not None:
            AYUDA.exec_menu(menu, lista.viewport().mapToGlobal(pos))

    def _menu_carpeta(self, it: QListWidgetItem) -> QMenu:
        """Menú de un archivo de Mi carpeta: poner, abrir, mostrarlo en su carpeta, quitarlo (a la Papelera)."""
        menu = QMenu(self.lista_carpeta)
        ruta = it.data(Qt.UserRole)
        rutas = self._rutas_seleccion() if it.isSelected() else [ruta]
        menu.addAction("📍 Poner donde lo dices", lambda: self._poner_mis(rutas))
        menu.addAction("⏵ Poner en el cabezal", lambda: self._poner_mis(rutas, self._hits_cabezal()))
        menu.addAction("▶ Abrir", lambda: self._abrir(ruta))
        menu.addAction("📂 Mostrar en la carpeta", lambda: self._abrir(os.path.dirname(ruta)))
        if ruta not in (self.carpeta or {}).get("linked_files", []):   # una carpeta del PC enlazada no se borra
            menu.addAction("🗑 Quitar de la carpeta (a la Papelera)…", lambda: self._quitar(ruta))
        AYUDA.add_help_action(menu, AYUDA.help_key_for(self.lista_carpeta), self)
        return menu

    def _abrir(self, ruta: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    def _quitar(self, ruta: str):
        nombre = os.path.basename(ruta)
        r = QMessageBox.question(self, "Quitar de la carpeta",
                                 f"¿Mandar «{nombre}» a la Papelera?\n"
                                 "Se puede recuperar desde la Papelera de Windows.",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            ok = _a_papelera(ruta)
        except Exception:  # noqa: BLE001
            ok = False
        self._aviso(f"✓ «{nombre}» a la Papelera." if ok else f"No pude mandar «{nombre}» a la Papelera.")
        self.recalcular()
