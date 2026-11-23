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

import bisect
import hashlib
import os

from PySide6.QtCore import QFileSystemWatcher, QMimeData, QSettings, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtCore import QElapsedTimer, QEvent, QRect
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QScrollArea
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
                               QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip, QVBoxLayout, QWidget)

ROL_LIKE = Qt.UserRole + 1        # en «Dijiste…»: "si" si la palabra ya está en el glosario como palabra clave
ROL_TERM = Qt.UserRole + 2        # en «Dijiste…»: la palabra de la fila (el 👍/👎 no depende del número de fila)
ROL_CABECERA = Qt.UserRole + 3    # en «Dijiste…»: la fila «▸ Menos dichas (N)» (pliega / despliega el resto)
ROL_FRASE = Qt.UserRole + 4       # en «Dijiste…»: un trozo de la frase donde se dice (gris, entre la carpeta y 👍 👎)
MENOS_DICHAS_DESDE = 8            # con más palabras que esto, la lista se parte: arriba las más dichas, el resto plegado
PLEGADO_CLAVE = "clips/menos_dichas_plegado"

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


def _corto(texto: str, largo: int = 48) -> str:
    """Texto de un menú sin hacerlo enorme: los nombres muy largos acaban en «…» (entero en su tooltip)."""
    return texto if len(texto) <= largo else texto[:largo - 1].rstrip() + "…"


def texto_variantes(m: dict, cuantas: int = 6) -> str:
    """«También dicho: lugar uno, Lugar 1» (las formas en que se oyó la palabra, sin repetir la que se ve)."""
    vs = [v for v in (m.get("variantes") or []) if KF.norm(v) != KF.norm(m.get("term", ""))]
    if not vs:
        return ""
    return "También dicho: " + ", ".join(vs[:cuantas]) + ("…" if len(vs) > cuantas else "")


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
    # («v2»: 22/11, las de antes podían ser un fotograma negro —el segundo 1 de un video que empieza con un fundido—)
    h = hashlib.md5(("v2|" + clave).encode("utf-8")).hexdigest()
    return os.path.join(str(cache_dir("clips_carpetas")), h + ".png")


def _brillo(img: QImage) -> float:
    """Brillo medio (0–255) de una imagen, mirando una versión diminuta (rápido)."""
    if img.isNull():
        return 0.0
    p = img.scaled(16, 9, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    vals = [p.pixelColor(x, y).value() for y in range(p.height()) for x in range(p.width())]
    return sum(vals) / max(1, len(vals))


NEGRO = 18.0                          # (brillo medio por debajo de esto: un fotograma negro o casi)


def _hacer_miniatura(ruta: str, salida: str) -> bool:
    """Miniatura de una imagen o de un fotograma de un video. Corre en segundo plano (sin Qt de ventanas).
    Video: un fotograma a ~10 % de su duración (no el segundo 0 ni el 1, que en muchos clips es negro: fundido de
    entrada); si sale negro, prueba a ~25 % y ~50 % y se queda con el que se vea."""
    try:
        if kind_for_path(ruta) == KIND_VIDEO:
            try:
                dur = float(MEDIA.probe(ruta).get("duration") or 0.0)
            except Exception:  # noqa: BLE001
                dur = 0.0
            tiempos = [dur * f for f in (0.1, 0.25, 0.5)] if dur > 1.5 else []
            tiempos += [1.0, 0.0]
            mejor, brillo_mejor = None, -1.0
            for t in tiempos:
                if dur and t > dur - 0.05:
                    continue
                MEDIA.run_quiet([MEDIA.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", ruta,
                                 "-frames:v", "1", "-vf", "scale=320:-2", salida], timeout=60)
                if not (os.path.isfile(salida) and os.path.getsize(salida) > 0):
                    continue
                cand = QImage(salida)
                b = _brillo(cand)
                if b > brillo_mejor:
                    mejor, brillo_mejor = cand, b
                if b >= NEGRO:
                    break
            img = mejor if mejor is not None else QImage()
        else:
            img = QImage(ruta)
        if img.isNull():
            return False
        img.scaled(MINI_W, MINI_H, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(salida, "PNG")
        return os.path.isfile(salida)
    except Exception:  # noqa: BLE001 - sin miniatura se muestra el hueco
        return False



class _Clic(QLabel):
    """Texto de una fila de momentos: al pulsarlo avisa (para ir a ese momento). (20/11) Si no cabe, acaba en «…» y se
    lee entero en el tooltip: nunca cortado por la derecha."""
    clicked = Signal()

    def __init__(self, texto: str = "", parent=None):
        super().__init__(texto, parent)
        self._completo = texto
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def resizeEvent(self, e):                  # noqa: N802
        super().resizeEvent(e)
        corto = self.fontMetrics().elidedText(self._completo, Qt.ElideRight, max(10, self.width() - 2))
        if corto != self.text():
            self.setText(corto)

    def sizeHint(self):                        # noqa: N802
        s = super().sizeHint()
        return QSize(min(s.width(), self.fontMetrics().horizontalAdvance(self._completo) + 4), s.height())

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
        self.alto_pedido = 0              # (>0: el alto que pide —el de sus filas, con tope—; ver _ajustar_alto_menciones)
        if arrastrar:
            self.setDragEnabled(True)
            self.setDragDropMode(QAbstractItemView.DragOnly)

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), self.alto_pedido) if self.alto_pedido > 0 else s

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



def _icono_dis(nombre: str):
    """Icono monocromo del diseño (Lucide)."""
    from . import diseno as D
    return D.icono(nombre)


class _ZonaListas(QScrollArea):
    """«Dijiste…»: la zona de las dos listas (y ◀ ▶). Pide como alto preferido solo su mínimo y se estira con el sitio
    que haya: así la zona con desplazamiento del panel nunca crece por ella (con el panel bajo se desplazaba todo y
    la cabecera quedaba fuera de la vista); con poco sitio se desplazan solo las listas."""

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), max(self.minimumHeight(), self.minimumSizeHint().height()))


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
        if index.data(ROL_CABECERA):         # «▸ Menos dichas (N)»: solo el texto, sin 👍/👎
            painter.save()
            f = QFont(option.font)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor("#8b8b93"))
            painter.drawText(option.rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                             str(index.data(Qt.DisplayRole) or ""))
            painter.setPen(QColor("#34343a"))
            painter.drawLine(option.rect.left(), option.rect.top(), option.rect.right(), option.rect.top())
            painter.restore()
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        estilo = opt.widget.style() if opt.widget is not None else None
        if estilo is not None:              # fondo (elegida / bajo el ratón) en toda la fila
            estilo.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)
        texto = QStyleOptionViewItem(option)
        texto.rect = option.rect.adjusted(0, 0, -2 * self.ANCHO - 4, 0)   # el texto no pisa los botones
        super().paint(painter, texto, index)
        si, no = self.zonas(option.rect)
        frase = str(index.data(ROL_FRASE) or "")
        if frase:                            # (20/11: el hueco de cada fila, con dónde lo dijiste; entera en el tooltip)
            fm = opt.fontMetrics
            x = option.rect.left() + 6 + fm.horizontalAdvance(str(index.data(Qt.DisplayRole) or "")) + 14
            ancho = si.left() - 6 - x
            if ancho > fm.horizontalAdvance("…") * 8:
                painter.save()
                painter.setPen(QColor("#7d808a"))
                painter.drawText(QRect(x, option.rect.top(), ancho, option.rect.height()),
                                 Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(frase, Qt.ElideRight, ancho))
                painter.restore()
        gusta = index.data(ROL_LIKE) == "si"
        painter.save()
        for zona, icono, encendido in ((si, "👍", gusta), (no, "👎", False)):
            painter.setOpacity(1.0 if encendido else 0.55)
            painter.drawText(zona, Qt.AlignCenter, icono)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if index.data(ROL_CABECERA):         # (la cabecera no tiene 👍/👎: su clic lo atiende la lista)
            return super().editorEvent(event, model, option, index)
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
        if event is not None and index.isValid() and not index.data(ROL_CABECERA):
            si, no = self.zonas(option.rect)
            if si.contains(event.pos()):
                QToolTip.showText(event.globalPos(), "👍 Me gusta: es palabra clave (se le crea su carpeta)", view)
                return True
            if no.contains(event.pos()):
                QToolTip.showText(event.globalPos(), "👎 No me gusta: no es palabra clave (deja de proponerse)", view)
                return True
        return super().helpEvent(event, view, option, index)


class _Segmentado(QWidget):
    """🔑 Selector de varias partes en UNA sola pieza: con sitio, icono y texto; con poco ancho, solo el icono (el
    nombre sigue en su tooltip), nunca partido en dos líneas ni con el texto cortado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.botones: list = []
        self._solo_icono = False

    def _ancho(self, solo_icono: bool) -> int:
        """Ancho con texto o solo con icono, medido con un botón de prueba aparte (los de verdad no se tocan: así no
        se rehace la disposición al medir). Se recuerda mientras no cambie la letra."""
        from PySide6.QtWidgets import QToolButton
        clave = (solo_icono, self.font().key(), len(self.botones))
        memo = self.__dict__.setdefault("_anchos", {})
        if clave not in memo:
            tot = 0
            for b in self.botones:
                prueba = QToolButton()
                prueba.setFont(b.font())
                prueba.setStyleSheet(b.styleSheet())
                prueba.setIcon(b.icon())
                prueba.setText(b.text())
                prueba.setToolButtonStyle(Qt.ToolButtonIconOnly if solo_icono else Qt.ToolButtonTextBesideIcon)
                tot += prueba.sizeHint().width()
                prueba.deleteLater()
            m = self.layout().contentsMargins() if self.layout() is not None else None
            memo[clave] = tot + ((m.left() + m.right()) if m is not None else 0)
        return memo[clave]

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(self._ancho(False), s.height())

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        return QSize(self._ancho(True), s.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        solo = e.size().width() < self._ancho(False)
        if solo != self._solo_icono:
            self._solo_icono = solo
            for b in self.botones:
                b.setToolButtonStyle(Qt.ToolButtonIconOnly if solo else Qt.ToolButtonTextBesideIcon)


class ClipsPanel(InternetMixin, QWidget):
    seek_requested = Signal(float)
    hints_changed = Signal(list)      # [(segundo, texto)] → marcas de la línea de tiempo
    foco_changed = Signal(str)        # 🔑 la palabra elegida: sus marcas resaltadas, las demás atenuadas ("" = ninguna)
    modo_changed = Signal(str)        # 🔑 «todas» / «elegida» / «ninguna» (va a la par con el botón de la regla)
    fila_kw_changed = Signal(bool)    # ⚡ el botón «Material»: enseñar la fila de material por palabra clave

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
        from .hint_marks import modo_guardado
        self.modo = modo_guardado()       # 🔑 qué palabras se ven en la regla (ver hint_marks.MODOS)
        self.cabezal = 0.0                # (dónde está el cabezal: para «◀ ▶», más cercana y más lejana)
        self._ts_cache = None             # (🧭 los momentos a recorrer, ya ordenados: se rehacen en _marcas())
        self._nav_estado = None           # (🧭 lo último pintado en ◀ ▶ y más cercana / lejana)
        self._aviso_tope = False          # (el aviso de «demasiadas marcas» es nuestro: se borra al dejar de serlo)
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
                                         "(«Explosiones», «Persona»…) con tus videos e imágenes.")
        self.btn_cambiar_raiz.clicked.connect(self._cambiar_raiz)
        self.btn_abrir_raiz = QPushButton("Abrir")
        self.btn_abrir_raiz.setToolTip("Abre la carpeta raíz en el Explorador.")
        self.btn_abrir_raiz.clicked.connect(self._abrir_raiz)
        # (20/11, auditoría: de 5 filas de botones a 3 —carpeta · «Dijiste…» con lo de todas · modo y carpetas—;
        #  «Cambiar…» y «Abrir», iconos en la fila de la carpeta; solo cambia la disposición)
        from . import diseno as _D0
        for b_, ic, nombre in ((self.btn_cambiar_raiz, "square-pen", "Cambiar…"),
                               (self.btn_abrir_raiz, "folder-open", "Abrir")):
            b_.setIcon(_D0.icono(ic))
            b_.setToolTip(f"{nombre}: {b_.toolTip()}")
            b_.setAccessibleName(nombre)
        raiz.setSpacing(4)
        _D0.fila_fija(raiz)                      # (Cambiar… y Abrir pasan a solo icono si no caben: nunca bajan de fila)
        self.lbl_raiz.setWordWrap(True)          # (la ruta se parte en líneas: nunca empuja «Abrir» a otra fila)
        raiz.addWidget(self.lbl_raiz, 1)
        raiz.addWidget(self.btn_cambiar_raiz)
        raiz.addWidget(self.btn_abrir_raiz)
        v.addLayout(raiz)
        self._pintar_raiz()

        cab = QHBoxLayout()
        titulo = QLabel("<b>Dijiste…</b>")
        titulo.setToolTip("Palabras de tu narración que parecen nombres propios, compañías, tus carpetas o tus "
                          "palabras de vocabulario. Pulsa una para ir a donde la dices.")
        self.btn_recalc = QPushButton("Buscar")
        self.btn_recalc.setIcon(_icono_dis("refresh-cw"))
        self.btn_recalc.setToolTip("Volver a buscar: vuelve a leer la narración y las carpetas")
        self.btn_recalc.clicked.connect(self.recalcular)
        self.btn_quitar = QPushButton("Quitar marcas")
        self.btn_quitar.setIcon(_icono_dis("x"))
        self.btn_quitar.setToolTip("Quitar marcas: quita de la línea de tiempo las marcas de las palabras clave")
        self.btn_quitar.clicked.connect(self._quitar_marcas)
        self.btn_glosario = QPushButton("Glosario…")
        self.btn_glosario.setIcon(_icono_dis("book-open"))
        self.btn_glosario.setToolTip("Palabras que sí son palabras clave y palabras que no. Lo que confirmas aquí "
                                     "se respeta en «Dijiste…» y en «✨ Crear de lo que dices».")
        self.btn_glosario.clicked.connect(self._abrir_glosario)
        self.btn_todo = QPushButton("Agregar todo")
        self.btn_todo.setIcon(_icono_dis("wand-sparkles"))
        self.btn_todo.setToolTip("Agrega a la línea de tiempo, de una vez, el material de las carpetas (lo descargado "
                                 "y lo de tu computadora) justo donde dices cada palabra clave, con la duración de tu "
                                 "frase y sin repetir. Un Ctrl+Z lo quita.")
        self.btn_todo.clicked.connect(self.agregar_todo)
        self.btn_amplia = QPushButton("Carpetas")
        self.btn_amplia.setIcon(_icono_dis("folder-open"))
        self.btn_amplia.setToolTip("Muestra la pestaña «🗂 Carpetas» (a la derecha, junto al Inspector): la carpeta de "
                                   "la palabra elegida, con lo descargado y lo de tu computadora por separado (y para "
                                   "borrarlo fácil)")
        self.btn_amplia.clicked.connect(self.abrir_ventana)
        self.sel_modo = self._selector_modo()            # 🔑 Todas · Elegida · Ninguna (segmentado)
        from PySide6.QtWidgets import QToolButton
        from . import diseno as _D
        self.btn_fila_kw = QToolButton()                   # ⚡ la fila de material por palabra clave, aparte
        self.btn_fila_kw.setText("Material")
        self.btn_fila_kw.setIcon(_D.icono("rows-3"))
        self.btn_fila_kw.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_fila_kw.setCheckable(True)
        self.btn_fila_kw.setToolTip("Fila ⚡ en la regla: un chip por palabra clave con el material de su carpeta "
                                    "(gameplay o cinemática); clic en un chip = cambiarlo. Lo mismo que Timeline → "
                                    "«Fila ⚡ de material por palabra clave». Con «Ninguna» tampoco se ve")
        self.btn_fila_kw.toggled.connect(lambda on: self.fila_kw_changed.emit(bool(on)))
        self.btn_otras = QPushButton("Otras")
        self.btn_otras.setIcon(_icono_dis("eye"))
        self.btn_otras.setCheckable(True)
        self.btn_otras.setChecked(self._ver_otras())
        self.btn_otras.setToolTip("Enseña también, al final y atenuadas, tus carpetas de palabras de otros proyectos "
                                  "que no dices en esta narración. Apagado: solo las palabras de este proyecto.")
        self.btn_otras.toggled.connect(lambda on: (_ajustes().setValue("clips/ver_otras_carpetas", bool(on)),
                                                   self._recalcular_luego()))
        # (dos filas: el título con lo que vale para todas las palabras y ✕ ↻; debajo, cómo se ven en la línea de
        #  tiempo y las carpetas. Con poco ancho, responsive baja lo que no quepa a la línea siguiente)
        cab.setSpacing(4)
        cab.addWidget(titulo)
        for b in (self.btn_todo, self.btn_otras, self.btn_glosario):
            cab.addWidget(b)
        cab.addStretch(1)
        cab.addWidget(self.btn_quitar)
        cab.addWidget(self.btn_recalc)
        v.addLayout(cab)
        herr = QHBoxLayout()
        herr.setSpacing(4)
        for b in (self.sel_modo, self.btn_fila_kw, self.btn_amplia):
            herr.addWidget(b, 0, Qt.AlignVCenter)
        herr.addStretch(1)
        v.addLayout(herr)
        # (UN solo alto —24 px— y una base en las tres filas; cada botón con icono y texto corto si cabe, si no solo
        #  el icono, siempre con su tooltip: _textos_que_caben)
        self._filas_dijiste = [
            [self.btn_cambiar_raiz, self.btn_abrir_raiz],
            [self.btn_todo, self.btn_otras, self.btn_glosario, self.btn_quitar, self.btn_recalc],
            [self.btn_amplia]]
        self._textos_dijiste = {id(b): b.text() for fila in self._filas_dijiste for b in fila}
        alto = _D.px(_D.ALTO_CAMPO)
        for b in [b for fila in self._filas_dijiste for b in fila] + \
                [self.btn_fila_kw] + self.sel_modo.findChildren(QToolButton):
            _D.alto_fijo(b)          # (24 px SIN el relleno vertical: con él la letra quedaba cortada a lo alto)
        for b in [b for fila in self._filas_dijiste for b in fila]:
            # (su mínimo es el icono: con poco ancho pasan a solo icono —_textos_que_caben— y nunca obligan al panel
            #  a ser más ancho, tampoco mientras su sección está escondida)
            _D.medida(b, lambda w: w.setMinimumWidth(_D.px(_D.ALTO_CAMPO) + 6))
        self._alto_filas = alto

        self.lista_menciones = _Lista()
        self.lista_menciones.setMaximumHeight(130)
        self.lista_menciones.setMinimumHeight(self.ALTO_MIN_LISTA)   # (con el panel bajo encogen las listas, no la
        self.lista_menciones.setToolTip("Lo que se dice en la narración, con cuántas veces sale. "
                                        "📁 n = tienes carpeta con n archivos · ＋ = aún no tiene carpeta. "
                                        "👍 / 👎 a la derecha = me gusta / no me gusta esa palabra. "
                                        "Puedes soltar archivos sobre una palabra. "
                                        "Clic derecho = ¿es palabra clave?, separar o unir sus variantes (se "
                                        "guarda en el glosario).")
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
        self._filas: list = []            # fila de la lista → índice en self.menciones (None = «Menos dichas»)
        self.lista_menciones.currentRowChanged.connect(self._fila_elegida)
        self.lista_menciones.itemClicked.connect(self._clic_en_fila)
        self.lista_menciones.soltado.connect(
            lambda rutas, fila: self._soltar_archivos(rutas, self._indice_de_fila(fila)))
        self._bloque_listas = QWidget()       # (20/11: lista de palabras + ◀ ▶ + lista de frases; con el panel bajo
        self._lay_listas = QVBoxLayout(self._bloque_listas)   #  solo se desplaza esto: la cabecera y sus botones, fijos)
        self._lay_listas.setContentsMargins(0, 0, 0, 0)
        self._lay_listas.setSpacing(6)
        self._zona_listas = _ZonaListas()
        self._zona_listas.setWidgetResizable(True)
        self._zona_listas.setFrameShape(QScrollArea.NoFrame)
        self._zona_listas.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._zona_listas.setMinimumHeight(self.ALTO_MIN_LISTA + 12)
        self._zona_listas.setWidget(self._bloque_listas)
        self._lay_listas.addWidget(self.lista_menciones)
        v.addWidget(self._zona_listas)
        # (sin palabras: UNA línea gris en vez de las dos listas vacías con ◀ ▶ en medio —~150 px—; el porqué, en el
        #  tooltip. Vuelven solas en cuanto haya una palabra)
        self.vacio_dijiste = _D.aviso_vacio("Sin palabras clave en la narración")
        self.vacio_dijiste.setVisible(False)
        v.addWidget(self.vacio_dijiste)
        modelo = self.lista_menciones.model()
        for senal in (modelo.rowsInserted, modelo.rowsRemoved, modelo.modelReset, modelo.layoutChanged):
            senal.connect(self._revisar_vacio_dijiste)
        # 🧭 recorrer dónde se dice: la palabra elegida (o todas, sin elegir ninguna)
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        self.btn_ant = QPushButton("◀")
        self.btn_ant.setFixedWidth(34)
        self.btn_ant.setToolTip("Ir a la vez anterior (antes del cabezal) en que dices la palabra elegida")
        self.btn_ant.clicked.connect(lambda: self._ir_vecina(-1))
        self.btn_sig = QPushButton("▶")
        self.btn_sig.setFixedWidth(34)
        self.btn_sig.setToolTip("Ir a la vez siguiente (después del cabezal) en que dices la palabra elegida")
        self.btn_sig.clicked.connect(lambda: self._ir_vecina(1))
        self.btn_cerca = QPushButton("⇢ Más cercana")
        ancho = self.btn_cerca.fontMetrics().horizontalAdvance("⇢ Más cercana 0:00:00") + 24
        self.btn_cerca.setMinimumWidth(ancho)     # (que no bailen al reproducir)
        self.btn_cerca.setToolTip("Ir a la vez más cercana al cabezal en que dices la palabra elegida")
        self.btn_cerca.clicked.connect(lambda: self._ir_extremo(cerca=True))
        self.btn_lejos = QPushButton("⇢ Más lejana")
        self.btn_lejos.setMinimumWidth(ancho)
        self.btn_lejos.setToolTip("Ir a la vez más lejana del cabezal en que dices la palabra elegida")
        self.btn_lejos.clicked.connect(lambda: self._ir_extremo(cerca=False))
        for b in (self.btn_ant, self.btn_sig, self.btn_cerca, self.btn_lejos):
            nav.addWidget(b)
        nav.addStretch(1)
        self._lay_listas.addLayout(nav)
        self._act_nav()

        self.lista_momentos = QListWidget()
        self.lista_momentos.setMaximumHeight(120)
        self.lista_momentos.setMinimumHeight(self.ALTO_MIN_LISTA)    #  cabecera: ella y sus botones, a la vista)
        self.lista_momentos.setToolTip("Dónde sale la palabra elegida. Casilla = poner el clip ahí · "
                                       "pulsa el texto para ir a ese momento · 📍 = poner el clip solo ahí.")
        self._lay_listas.addWidget(self.lista_momentos)

        mi = self._construir_mi_carpeta()
        if HAY_INTERNET:
            self.pestanas = self._construir_pestanas(mi)
            self._busqueda_w = self.pestanas
        else:
            self._busqueda_w = mi
        v.addWidget(self._busqueda_w, 1)
        self._busqueda_aparte = None      # (en la página 🔑 Palabras clave, la búsqueda va en su propia columna)

        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.aviso.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.aviso.setVisible(False)      # (sin aviso, sin línea vacía)
        v.addWidget(self.aviso)
        self._revisar_vacio_dijiste()

    def _revisar_vacio_dijiste(self, *_a):
        """«Dijiste…» sin ninguna palabra: las listas (palabras, ◀ ▶ y frases) se esconden y queda una línea gris; con
        palabras, vuelven las listas. El texto dice si falta la narración transcrita o si no dices ninguna."""
        try:
            hay = self.lista_menciones.count() > 0
            vacio = getattr(self, "vacio_dijiste", None)
            if vacio is None:
                return
            if self._zona_listas.isHidden() == hay:
                self._zona_listas.setVisible(hay)
            if not hay:
                p = getattr(getattr(self, "ctrl", None), "project", None)
                transcrita = bool(getattr(p, "transcripts", None))
                vacio.setText("Sin palabras clave en la narración" if transcrita else "Sin narración transcrita")
                vacio.setToolTip(
                    "Aquí salen los nombres y palabras clave que dices en la narración, con cuántas veces y dónde, "
                    "y su carpeta de material. " + (
                        "En esta narración no sale ninguna de tu vocabulario: añádelas en «Glosario»."
                        if transcrita else "Transcribe la narración en «Voz y texto → 1 · Transcribir»."))
            if vacio.isHidden() == (not hay):
                vacio.setVisible(not hay)
        except RuntimeError:                   # (cerrando: ya no existen)
            return

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
        from .miniaturas import activar_scrub      # (🖼 al pasar el ratón por un video: sus fotogramas en la casilla)
        activar_scrub(self.lista_carpeta, lambda it: it.data(Qt.UserRole))
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

    def sacar_busqueda(self) -> QWidget:
        """🔑 Para la página «Palabras clave»: la búsqueda (📁 Mi carpeta | 🌐 Internet) sale de este panel y va en su
        propia columna; aquí se quedan las palabras («Dijiste…», dónde se dicen) y sus listas crecen en el sitio libre.
        Todo sigue funcionando igual (es el mismo widget, con la misma lógica de este panel)."""
        w = self._busqueda_w
        if self._busqueda_aparte is None:
            self.layout().removeWidget(w)
            w.setParent(None)
            caja = QWidget()                  # 🔒 arriba, fija y siempre a la vista: la barra de Material
            caja.setObjectName("material_buscar")
            cv = QVBoxLayout(caja)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(4)
            cv.addWidget(self._construir_barra_material())
            cv.addWidget(w, 1)
            self._busqueda_aparte = caja
            lay = self.layout()
            # (20/11, sin huecos: la lista de palabras mide lo que sus filas —con tope— y la de frases se queda el
            #  resto; antes, las dos a partes fijas dejaban la de palabras medio vacía y un hueco antes de ◀ ▶)
            self.lista_momentos.setMaximumHeight(16777215)
            self._lay_listas.setStretchFactor(self.lista_menciones, 0)
            self._lay_listas.setStretchFactor(self.lista_momentos, 1)
            lay.setStretchFactor(self._zona_listas, 1)
            self._ajustar_alto_menciones()
        return self._busqueda_aparte

    ALTO_MIN_LISTA = 48               # (dos filas: con el panel bajo, las listas encogen hasta aquí)
    FILAS_TOPE = 9                    # (la lista de palabras crece con sus filas hasta este tope; luego se desplaza)

    def _ajustar_alto_menciones(self):
        """La lista de palabras, tan alta como sus filas a la vista (hasta FILAS_TOPE); sin filas, dos."""
        lm = self.lista_menciones
        if self._busqueda_aparte is None:
            return
        altos = [lm.sizeHintForRow(f) for f in range(lm.count()) if not lm.item(f).isHidden()]
        fila = max(altos) if altos else max(22, lm.fontMetrics().height() + 6)
        visibles = max(2, min(len(altos), self.FILAS_TOPE))
        alto = sum(altos[:visibles]) + fila * max(0, visibles - len(altos))
        alto += 2 * lm.frameWidth() + 2 * lm.spacing() * visibles + 2
        if alto != lm.alto_pedido:
            lm.alto_pedido = alto
            lm.setMaximumHeight(alto)
            lm.updateGeometry()

    # ------------------------------------------------------------------ 🔒 barra fija de «Buscar material»
    def _construir_barra_material(self) -> QWidget:
        """Siempre a la vista encima de Mi carpeta / Internet: dónde se guarda lo que bajas (carpeta raíz: hay que
        elegirla la primera vez y se recuerda), «Ver todo» lo descargado (en Carpetas), «Borrar todo lo
        descargado…» (a la Papelera) y las descargas en curso / en cola con su contador."""
        barra = QWidget()
        barra.setObjectName("barra_material")
        v = QVBoxLayout(barra)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        f1, f2 = QHBoxLayout(), QHBoxLayout()
        for f in (f1, f2):
            f.setContentsMargins(0, 0, 0, 0)
            f.setSpacing(4)
        self.btn_raiz_barra = QPushButton()
        self.btn_raiz_barra.clicked.connect(self._cambiar_raiz)
        self.btn_descargas_barra = QPushButton("En cola")
        self.btn_descargas_barra.clicked.connect(self.ver_descargas)
        self.btn_ver_todo = QPushButton("Ver todo")
        self.btn_ver_todo.setToolTip("Enseña en «Carpetas» todo lo que Reclaimer ha bajado de internet (de todas las "
                                     "palabras), con su miniatura y su duración")
        self.btn_ver_todo.clicked.connect(self.ver_todo)
        # (21/11: «Borrar todo lo descargado…» vive en Carpetas —allí se ve lo bajado y cuánto ocupa—; aquí, un
        #  icono que lleva allí)
        from . import diseno as _Dm
        self.btn_borrar_todo = _Dm.BotonIcono("trash-2", "Borrar todo lo descargado…: está en «Carpetas», donde se "
                                                         "ve lo bajado y cuánto ocupa. Clic = ir allí")
        self.btn_borrar_todo.clicked.connect(self.ir_a_borrar_todo)
        f1.addWidget(self.btn_raiz_barra, 1)
        f1.addWidget(self.btn_descargas_barra)
        f2.addWidget(self.btn_ver_todo)
        f2.addStretch(1)
        f2.addWidget(self.btn_borrar_todo)
        v.addLayout(f1)
        v.addLayout(f2)
        self.btn_descargas_barra.setVisible(HAY_INTERNET)
        self._pintar_raiz()
        self.act_contador_descargas()
        return barra

    def raiz_elegida(self) -> bool:
        """¿Ya eligió el usuario dónde se guarda lo que baja (y esa carpeta existe)?"""
        guardada = str(_ajustes().value(RAIZ_CLAVE, "") or "").strip()
        if not os.path.isdir(self.raiz):
            return False                      # (la carpeta guardada ya no existe: se vuelve a pedir)
        if guardada or os.path.normcase(self.raiz) != os.path.normcase(KF.default_root()):
            return True
        try:                                  # la de siempre, ya con material: se da por elegida y se recuerda
            con_algo = any(True for _ in os.scandir(self.raiz))
        except OSError:
            con_algo = False
        if con_algo:
            _ajustes().setValue(RAIZ_CLAVE, self.raiz)
        return con_algo

    def _pedir_raiz(self) -> str:
        """Pregunta la carpeta raíz (aparte para que las pruebas la sustituyan). "" = cancelado."""
        inicio = self.raiz if os.path.isdir(self.raiz) else os.path.dirname(self.raiz)
        if not os.path.isdir(inicio):
            inicio = os.path.expanduser("~")
        return QFileDialog.getExistingDirectory(
            self, "Elige (o crea) la carpeta donde guardar lo que bajes · se recuerda", inicio)

    def asegurar_raiz(self) -> bool:
        """Antes de bajar nada: la carpeta raíz tiene que estar elegida (la primera vez se pide; luego se recuerda)."""
        if self.raiz_elegida():
            return True
        elegida = self._pedir_raiz()
        if not elegida:
            self._aviso("Elige primero la carpeta donde guardar lo que bajes (botón «Elegir carpeta…» de arriba).")
            return False
        try:
            os.makedirs(elegida, exist_ok=True)
        except OSError as exc:
            self._aviso(f"No pude crear la carpeta: {exc}")
            return False
        _ajustes().setValue(RAIZ_CLAVE, elegida)
        self.raiz = elegida
        self._pintar_raiz()
        self._leer_carpetas()
        return True

    def ver_todo(self):
        """«Ver todo»: Carpetas pasa a «Todo lo descargado» (con miniaturas y duración) y se pone delante."""
        dock = getattr(self, "carpetas_dock", None)
        if dock is None:
            from .keywords_window import abrir
            dock = abrir(self)
        if hasattr(dock, "ver_todo"):
            dock.ver_todo()
        win = self.window()
        if hasattr(win, "show_panel") and getattr(self, "carpetas_dock", None) is not None:
            win.show_panel(dock)
        return dock

    def borrar_todo_descargado(self, preguntar: bool = True) -> int:
        """«Borrar todo lo descargado…»: a la Papelera (con confirmación). La lógica es la de Carpetas."""
        from .keywords_window import borrar_todo_descargado
        n = borrar_todo_descargado(self, self, preguntar)
        dock = getattr(self, "carpetas_dock", None)
        if dock is not None and n:
            dock.refrescar(leer=False)
        return n

    def ir_a_borrar_todo(self):
        """El icono de la papelera de Buscar material: enseña Carpetas con «Borrar todo lo descargado…» a la vista."""
        dock = self.abrir_ventana()
        b = getattr(dock, "btn_limpiar", None)
        if b is not None:
            win = self.window()
            if hasattr(win, "abrir_para_usar"):
                win.abrir_para_usar(b, b)
            else:
                b.setFocus()
        return dock

    def ver_descargas(self):
        """Contador «En cola (n)»: lleva a 🌐 Internet → Descargas (las que bajan, en cola y las bajadas)."""
        if not HAY_INTERNET:
            return
        tabs = getattr(self, "pestanas", None)
        if tabs is not None and tabs.count() > 1:
            tabs.setCurrentIndex(1)
        if hasattr(self, "poner_modo_busqueda"):
            self.poner_modo_busqueda("video")
        pn = getattr(self, "pestanas_net", None)
        if pn is not None:
            pn.setCurrentIndex(1)
        win = self.window() if self._busqueda_aparte is None else self._busqueda_aparte.window()
        if hasattr(win, "show_panel") and self._busqueda_aparte is not None:
            win.show_panel(self._busqueda_aparte)      # (desde Carpetas: Buscar material, delante)

    def act_contador_descargas(self):
        """«En cola (n)»: n = las que se están bajando o esperan. Sin ninguna, solo «En cola»."""
        botones = [x for x in (getattr(self, "btn_descargas_barra", None),) if x is not None]
        ds = list(getattr(self, "descargas", []) or [])
        curso = sum(1 for d in ds if getattr(d, "estado", "") == "bajando")
        listas = sum(1 for d in ds if getattr(d, "estado", "") == "listo")
        fallos = sum(1 for d in ds if getattr(d, "estado", "") == "error")
        icono = getattr(getattr(self, "carpetas_dock", None), "btn_descargas", None)
        if icono is not None:                  # (en Carpetas, un icono que lleva aquí: la cuenta, en su tooltip)
            try:
                icono.setToolTip(f"Descargas en cola ({curso}) · bajadas en esta sesión: {listas}"
                                 + (f" · con error: {fallos}" if fallos else "") + "\nSe ven en «Buscar material». "
                                 "Clic = ir allí")
                if hasattr(icono, "poner_cuenta"):     # (22/11: y la cuenta pequeña sobre el icono)
                    icono.poner_cuenta(curso)
            except RuntimeError:
                pass
        for b in botones:
            try:
                # «Descargas en cola (n)» (lo pidió el usuario: conserva «Descargas» y no se confunde con el panel
                # Descargas). Si no cabe en el ancho del botón, se acorta a «En cola (n)» (el tooltip lo dice entero).
                largo = f"Descargas en cola ({curso})" if curso else "Descargas en cola"
                corto = f"En cola ({curso})" if curso else "En cola"
                ancho = b.width() if b.isVisible() else 0
                cabe = ancho <= 0 or b.fontMetrics().horizontalAdvance(largo) + 24 <= ancho
                b.setText(largo if cabe else corto)
                b.setStyleSheet("QPushButton { color: #f2a03d; font-weight: bold; }" if curso else "")
                b.setToolTip(f"Bajando o en cola: {curso} · bajadas en esta sesión: {listas}"
                             + (f" · con error: {fallos}" if fallos else "") + "\nClic = ver la lista de descargas")
            except RuntimeError:
                pass

    def _aviso(self, texto: str):
        self.aviso.setText(texto)
        self.aviso.setVisible(bool(texto))

    def resizeEvent(self, e):                  # noqa: N802
        super().resizeEvent(e)
        self._textos_que_caben()

    def _textos_que_caben(self):
        """Cada fila de botones de «Dijiste…» con su texto corto si cabe a lo ancho; si no, solo los iconos (el nombre
        y lo que hacen, en el tooltip). Nada cortado y nada que baje de fila sin necesidad."""
        filas = getattr(self, "_filas_dijiste", None)
        if not filas:
            return
        libre = self.width() - 24
        for k, fila in enumerate(filas):
            fm = fila[0].fontMetrics()
            extra = 0
            if k == 1:
                extra = fm.horizontalAdvance("Dijiste…") + 12
            elif k == 0:
                extra = 120                           # (la ruta de la carpeta, al menos algo)
            elif k == 2:
                extra = self.sel_modo.sizeHint().width() + self.btn_fila_kw.sizeHint().width() + 8

            def ancho(b, con_texto, fm=fm):
                return (fm.horizontalAdvance(self._textos_dijiste[id(b)]) + 16 if con_texto else 0) + 26 + 4
            # (por pasos: todos con texto; si no, los de la derecha —✕ ↻— solo icono; si no, todos solo icono)
            pasos = [[True] * len(fila)]
            if k == 1:
                pasos.append([True, True, True, False, False])
            pasos.append([False] * len(fila))
            elegido = pasos[-1]
            for paso in pasos:
                if extra + sum(ancho(b, t) for b, t in zip(fila, paso)) <= libre:
                    elegido = paso
                    break
            for b, con_texto in zip(fila, elegido):
                quiero = self._textos_dijiste[id(b)] if con_texto else ""
                if b.text() != quiero:
                    b.setText(quiero)

    def showEvent(self, e):
        super().showEvent(e)
        self._programar()                 # al mostrarse: relee la narración y las carpetas (lo soltado en el Explorador)
        self._act_nav()                   # (🧭 el cabezal pudo moverse con el panel oculto)

    # ------------------------------------------------------------------ carpeta raíz y carpetas por palabra
    def _pintar_raiz(self):
        self.lbl_raiz.setText("📁 " + _corta(self.raiz).replace("\\", "\\\u200b"))   # (se parte tras cada «\\»)
        self.lbl_raiz.setToolTip(self.raiz)
        b = getattr(self, "btn_raiz_barra", None)
        if b is None:
            return
        if self.raiz_elegida():
            nombre = os.path.basename(self.raiz.rstrip("\\/")) or self.raiz
            b.setText("Carpeta: " + _corta(nombre, 30))
            b.setStyleSheet("")
            b.setToolTip(f"Lo que bajas se guarda en:\n{self.raiz}\n(una subcarpeta por palabra) · clic = cambiarla "
                         "(se recuerda)")
        else:
            b.setText("Elegir carpeta…")
            b.setStyleSheet("QPushButton { color: #f2a03d; font-weight: bold; }")
            b.setToolTip("Aún no has elegido dónde guardar lo que bajas de internet: elige (o crea) una carpeta. Se "
                         "pide la primera vez que bajas algo y luego se recuerda.")

    def _cambiar_raiz(self):
        elegida = self._pedir_raiz()
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
        self._recalcular_luego()
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
                                                 getattr(self, "carpetas_dock", None),
                                                 getattr(self, "_busqueda_aparte", None)))

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
        if self._ver_otras():                                   # (al final: tus carpetas que no dices; de otros
            self.menciones += self._no_dichas(self.menciones)   #  proyectos, así que solo si lo pides)
        self._pintar_menciones(anterior)
        if not dichas and self.menciones:
            self._elegir_mencion(self._indice_actual(), buscar=False)
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
            self._aviso("No encuentro nombres ni palabras de tu vocabulario en la narración."
                        if self.ctrl.project.transcripts else "")
            self._avisar_ventana()
            return
        self._elegir_mencion(self._indice_actual(), buscar=False)
        self._aviso("")
        self._verificar_si_toca()
        self._avisar_ventana()

    def limpiar(self):
        """Proyecto nuevo o reinicio: nada de lo anterior (palabra elegida, momentos, búsqueda y resultados)."""
        self.mencion = None
        self.menciones = []
        self._desmarcados = set()
        self._firma_ultima = None
        self.lista_menciones.clear()
        self._filas = []
        self.lista_momentos.clear()
        self._casillas = []
        self._marcas()
        self._pintar_carpeta()
        self._aviso("")
        if HAY_INTERNET and hasattr(self, "limpiar_internet"):
            self.limpiar_internet()
        self._pendiente = True
        self._programar()

    def _avisar_ventana(self):
        for w in (getattr(self, "_ventana_amplia", None), getattr(self, "carpetas_dock", None)):
            if w is not None:
                w.al_dia()

    def _no_dichas(self, dichas: list[dict]) -> list[dict]:
        """Tus carpetas de palabras que no salen en la narración (sin momentos), para verlas y darles 👍/👎. Solo si el
        proyecto tiene narración: un proyecto nuevo o vacío no enseña ninguna palabra clave."""
        if not self.ctrl.project.transcripts:
            return []
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
            if os.path.normcase(c["path"]) in usadas or KG.is_no(c["label"], g, exacto=True):
                continue
            out.append({"term": c["label"], "count": 0, "hits": [], "known": True, "no_dicha": True})
        return out

    def _orden(self, m: dict) -> tuple:
        """Las MÁS DICHAS primero (veces que sale en la narración); a igualdad, las que tienen carpeta y luego la que
        sale antes. Las que internet descarta y las que no dices, al final."""
        if m.get("no_dicha"):
            return (2, 0, 0, 0.0)
        primero = next((_momento(h) for h in m.get("hits") or [] if _momento(h) is not None), None)
        return (1 if _descartada(m) else 0, -int(m.get("count") or 0), 0 if self._carpeta_de(m["term"]) else 1,
                primero if primero is not None else 1e12)

    def _cuantas_arriba(self) -> int:
        """Cuántas palabras van arriba (las más dichas); el resto va debajo de «▸ Menos dichas (N)». Con pocas
        palabras no se parte (todas arriba)."""
        n = len(self.menciones)
        if n <= MENOS_DICHAS_DESDE:
            return n
        rel = sum(1 for m in self.menciones if not m.get("no_dicha") and not _descartada(m))
        return min(n, max(min(rel, 4), (rel + 1) // 2))

    # (fila de la lista ↔ palabra: la cabecera «Menos dichas» ocupa una fila que no es ninguna palabra)
    def _indice_de_fila(self, fila: int) -> int:
        if 0 <= fila < len(self._filas) and self._filas[fila] is not None:
            return self._filas[fila]
        return -1

    def _fila_de_indice(self, i: int) -> int:
        try:
            return self._filas.index(i)
        except ValueError:
            return -1

    def _indice_actual(self) -> int:
        return self._indice_de_fila(self.lista_menciones.currentRow())

    def _plegado(self) -> bool:
        try:
            return _ajustes().value(PLEGADO_CLAVE, True, type=bool)
        except Exception:  # noqa: BLE001
            return True

    def cabecera_menos_dichas(self) -> int:
        return self._filas.index(None) if None in self._filas else -1

    def plegar_menos_dichas(self, plegar: bool, guardar: bool = True):
        """▸ / ▾ «Menos dichas (N)»: esconde o enseña las palabras que se dicen menos (se recuerda)."""
        cab = self.cabecera_menos_dichas()
        if cab < 0:
            return
        if guardar:
            _ajustes().setValue(PLEGADO_CLAVE, bool(plegar))
        it = self.lista_menciones.item(cab)
        n = self.lista_menciones.count() - cab - 1
        it.setText(f"{'▸' if plegar else '▾'} Menos dichas ({n})")
        for f in range(cab + 1, self.lista_menciones.count()):
            self.lista_menciones.item(f).setHidden(bool(plegar))
        self._ajustar_alto_menciones()

    def _clic_en_fila(self, it: QListWidgetItem):
        if it is not None and it.data(ROL_CABECERA):          # (fuera del clic: la lista no se toca en su evento)
            QTimer.singleShot(0, lambda: self.plegar_menos_dichas(not self._plegado()))
            return
        import time as _time
        if _time.monotonic() - getattr(self, "_t_elegida", 0.0) < 0.6:
            return                                # (el clic que la acaba de elegir: ya fue a su 1.ª vez)
        i = self._indice_de_fila(self.lista_menciones.row(it)) if it is not None else -1
        if 0 <= i < len(self.menciones) and self.menciones[i] is self.mencion:   # (otra vez la misma: a su 1.ª vez)
            if self.modo == "ninguna":
                self.set_modo("elegida")
            ts = sorted(self._tiempos_de(self.mencion))
            if ts:
                self._ir_a(ts[0])

    def _fila_elegida(self, fila: int):
        """El usuario elige una fila de «Dijiste…» (la cabecera «Menos dichas» no es una palabra: se queda la de
        antes)."""
        i = self._indice_de_fila(fila)
        if i < 0:
            if fila >= 0 and self.mencion is not None:
                previa = next((k for k, m in enumerate(self.menciones) if m is self.mencion), -1)
                f_prev = self._fila_de_indice(previa)
                destino = -1
                if QApplication.mouseButtons() == Qt.NoButton and f_prev >= 0:   # (teclado: cruzar la cabecera)
                    paso = 1 if fila > f_prev else -1
                    f = fila + paso
                    while 0 <= f < self.lista_menciones.count():
                        it = self.lista_menciones.item(f)
                        if not it.isHidden() and not it.data(ROL_CABECERA):
                            destino = f
                            break
                        f += paso
                if destino >= 0:
                    QTimer.singleShot(0, lambda f=destino: self.lista_menciones.setCurrentRow(f))
                else:
                    QTimer.singleShot(0, lambda k=previa: self._volver_a_fila(k))
            return
        import time as _time
        self._t_elegida = _time.monotonic()
        self._elegir_mencion(i, buscar=True)

    def _volver_a_fila(self, i: int):
        f = self._fila_de_indice(i)
        if f >= 0 and self.lista_menciones.currentRow() != f:
            self.lista_menciones.blockSignals(True)
            self.lista_menciones.setCurrentRow(f)
            self.lista_menciones.blockSignals(False)

    def _poner_fila_actual(self, i: int):
        """Deja elegida (sin señales) la fila de la palabra i; si está plegada, despliega «Menos dichas»."""
        f = self._fila_de_indice(i)
        if f < 0:
            return
        it = self.lista_menciones.item(f)
        if it is not None and it.isHidden():
            self.plegar_menos_dichas(False, guardar=False)
        self.lista_menciones.blockSignals(True)
        self.lista_menciones.setCurrentRow(f)
        self.lista_menciones.blockSignals(False)

    def elegir_indice(self, i: int, buscar: bool = False):
        """Elige la palabra i de self.menciones (por su índice, no por la fila de la lista)."""
        if not (0 <= i < len(self.menciones)):
            return
        self._poner_fila_actual(i)
        self._elegir_mencion(i, buscar=buscar)

    def _pintar_menciones(self, anterior: str | None):
        """Pinta «Dijiste…» con self.menciones: arriba las más dichas y, si hay muchas, debajo «▸ Menos dichas (N)»
        (plegable) con el resto. Deja elegida la palabra «anterior» si sigue, sin emitir señales."""
        self.menciones.sort(key=self._orden)
        try:
            si_glosario = set(KG.load()["si"])
        except Exception:  # noqa: BLE001
            si_glosario = set()
        self.lista_menciones.blockSignals(True)
        self.lista_menciones.clear()
        self._filas = []
        arriba = self._cuantas_arriba()
        fila_previa = -1
        for i, m in enumerate(self.menciones):
            if i == arriba:
                cab = QListWidgetItem(f"▸ Menos dichas ({len(self.menciones) - arriba})")
                cab.setFlags(Qt.ItemIsEnabled)
                cab.setData(ROL_CABECERA, True)
                cab.setToolTip("Las palabras que se dicen menos veces (y las que internet descarta). "
                               "Clic para enseñarlas u ocultarlas.")
                self.lista_menciones.addItem(cab)
                self._filas.append(None)
            self._filas.append(i)
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
            frase = " ".join(str(primero.get("context") or "").split())
            if frase:
                it.setData(ROL_FRASE, frase)
            pistas: list[str] = [f"Dijiste: «{frase}»"] if frase else []
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
            tambien = texto_variantes(m)
            if tambien:
                pistas.append(tambien)
            it.setToolTip("\n".join(pistas))
            self.lista_menciones.addItem(it)
            if anterior and m["term"] == anterior and fila_previa < 0:
                fila_previa = i
        self.lista_menciones.blockSignals(False)
        if self.cabecera_menos_dichas() >= 0:
            self.plegar_menos_dichas(self._plegado(), guardar=False)
        self._ajustar_alto_menciones()
        if self.menciones:
            self._poner_fila_actual(fila_previa if fila_previa >= 0 else 0)

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
        fila = self._indice_actual()
        if anterior is not None and 0 <= fila < len(self.menciones):
            self.mencion = self.menciones[fila]
        self._marcas()                               # (las menciones son otras: marcas y 🧭 al día)

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
        if (k in g["si"] or k in g["no"] or KF.norm(term) in KG.separadas(g)
                or KF.compacta(term) in KG.uniones(g) or KF.compacta(term) in map(KF.compacta, KG.uniones(g).values())):
            menu.addAction("↺ Quitar del glosario", lambda: self._glosario_cambia(KG.remove, term))
        menu.setToolTipsVisible(True)
        self._menu_variantes(menu, m)
        menu.addSeparator()
        car = self._carpeta_de(term)
        a = menu.addAction("🗑 Eliminar palabra clave…", lambda: self._eliminar_palabra(term))
        a.setToolTip("Sale de la lista y no vuelve a salir"
                     + (f"; su carpeta «{car['label']}» va a la Papelera de Windows (recuperable)" if car else ""))
        menu.setToolTipsVisible(True)
        a = menu.addAction("👁 Ver también las de otros proyectos (las que no dices)", self._cambiar_ver_otras)
        a.setCheckable(True)
        a.setChecked(self._ver_otras())
        AYUDA.add_help_action(menu, AYUDA.help_key_for(self.lista_menciones), self)
        return menu

    def _menu_variantes(self, menu: QMenu, m: dict, padre=None):
        """«✂ Separar…» y «🔗 Unir con…» de una palabra clave (se recuerdan en el glosario, como «No es palabra
        clave»). Lo usan «Dijiste…» y 🔑 Palabras clave."""
        term = m["term"]
        variantes = [v for v in (m.get("variantes") or []) if KF.norm(v) != KF.norm(term)]
        sub = menu.addMenu("✂ Separar…")
        sub.setToolTipsVisible(True)
        sub.menuAction().setToolTip("Saca del grupo una forma en que se oyó (por ejemplo, una palabra que la "
                                    "transcripción confundió): sale aparte en la lista. Se recuerda.")
        for v in variantes:
            a = sub.addAction(f"«{_corto(v)}»", lambda v=v: self._variante_cambia(
                KG.add_separacion, (v,), f"✂ «{v}» ya no cuenta como «{term}»."))
            a.setToolTip(f"«{v}» deja de contar como «{term}» y sale aparte. Se deshace con clic derecho en ella → "
                         "«↺ Quitar del glosario».")
        if not variantes:
            sub.setEnabled(False)
            sub.menuAction().setToolTip("Solo se ha oído de una forma: no hay nada que separar.")
        vistos = {KG.clave(term)}
        otros: list[str] = []
        for x in sorted((x for x in self.menciones if not x.get("no_dicha")), key=lambda x: -int(x.get("count", 0))):
            if KG.clave(x["term"]) not in vistos:
                vistos.add(KG.clave(x["term"]))
                otros.append(x["term"])
        for c in sorted(self.carpetas, key=lambda c: c["label"].lower()):     # (y tus carpetas, aunque no las digas)
            if KG.clave(c["label"]) not in vistos:
                vistos.add(KG.clave(c["label"]))
                otros.append(c["label"])
        sub2 = menu.addMenu("🔗 Unir con…")
        sub2.setToolTipsVisible(True)
        sub2.menuAction().setToolTip("Junta esta palabra (y cómo se oyó) con otra: cuentan como la misma palabra "
                                     "clave. Se recuerda.")
        mas = max(0, len(otros) - 40)
        for o in otros[:40]:
            a = sub2.addAction(_corto(o), lambda o=o: self._variante_cambia(
                KG.add_union, ([term] + variantes, o), f"🔗 «{term}» cuenta ahora como «{o}»."))
            a.setToolTip(f"«{term}» cuenta desde ahora como «{o}». Se deshace con «✂ Separar…» en «{o}».")
        if mas:
            a = sub2.addAction(f"(y {mas} más: une desde la otra palabra)")
            a.setEnabled(False)
        if not otros:
            sub2.setEnabled(False)
            sub2.menuAction().setToolTip("No hay otra palabra clave con la que unirla.")

    def _variante_cambia(self, fn, args: tuple, aviso: str):
        """Guarda un «Separar…» / «Unir con…» y rehace «Dijiste…» fuera del clic del menú."""
        try:
            fn(*args)
        except OSError as exc:
            self._aviso(f"No pude guardar el glosario: {exc}")
            return
        self._recalcular_luego()
        self._aviso(aviso)

    @staticmethod
    def _ver_otras() -> bool:
        """¿Enseñar también tus carpetas de palabras que NO dices en esta narración? Son de proyectos anteriores:
        por defecto, no (un proyecto nuevo solo enseña sus palabras)."""
        try:
            return _ajustes().value("clips/ver_otras_carpetas", False, type=bool)
        except Exception:  # noqa: BLE001
            return False

    def _cambiar_ver_otras(self, *_):
        b = getattr(self, "btn_otras", None)
        if b is not None:                            # (el botón de la cabecera guarda el ajuste y recalcula)
            b.setChecked(not self._ver_otras())
            return
        _ajustes().setValue("clips/ver_otras_carpetas", not self._ver_otras())
        self._recalcular_luego()

    def _recalcular_luego(self):
        """Rehace «Dijiste…» FUERA del clic que lo pidió (vaciar la lista dentro de su propio evento de ratón o de
        menú cerraba Reclaimer) y agrupando varios clics seguidos en uno solo."""
        t = getattr(self, "_t_recalc", None)
        if t is None:
            t = self._t_recalc = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(150)
            t.timeout.connect(self.recalcular)
        t.start()

    def _eliminar_palabra(self, term: str, preguntar: bool = True) -> bool:
        """🗑 Quita la palabra clave: su carpeta propia a la Papelera (las del PC enlazadas solo se desvinculan) y al
        glosario como «no», para que no vuelva a salir aunque la digas. Se deshace desde 📖 Glosario y la Papelera."""
        car = self._carpeta_de(term)
        usados = []                                  # ⚠ archivos de su carpeta propia que usa el proyecto
        own = (car or {}).get("own_path")
        if own:
            base = os.path.normcase(os.path.abspath(own)) + os.sep
            p = self.ctrl.project
            usados = [m.name for m in p.media.values()
                      if os.path.normcase(os.path.abspath(m.path)).startswith(base) and p.is_media_used(m.id)]
        if preguntar:
            extra = (f"\nSu carpeta «{car['label']}» ({car['count']} archivo(s)) irá a la Papelera de Windows "
                     "(se puede recuperar)." if car else "")
            if usados:
                extra += (f"\n⚠ {len(usados)} de sus archivos están en tu línea de tiempo y quedarían como «NO "
                          "ENCONTRADO» (se recuperan con clic derecho → «♻ Restaurar»).")
            r = QMessageBox.question(self, "Eliminar palabra clave",
                                     f"¿Eliminar la palabra clave «{term}»?{extra}",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return False
        try:
            if car:
                KF.delete_keyword(self.raiz, car["label"], _a_papelera)
        except OSError as exc:
            self._aviso(f"No pude mandar su carpeta a la Papelera: {exc}")
            return False
        try:
            KG.add_no(term)
        except OSError as exc:
            self._aviso(f"Su carpeta ya está en la Papelera, pero no pude guardarla en el glosario: {exc}")
        if self.mencion and self.mencion.get("term") == term:
            self.mencion = None
        self._recalcular_luego()
        self._aviso(f"✓ «{term}» eliminada" + (" (su carpeta, a la Papelera)." if car else "."))
        return True

    def _glosario_cambia(self, fn, term: str, *extra):
        """Aplica un cambio al glosario y recalcula «Dijiste…» (sin mirar la firma)."""
        try:
            fn(term, *extra)
        except OSError as exc:
            self._aviso(f"No pude guardar el glosario: {exc}")
            return
        self._recalcular_luego()
        self._aviso(f"✓ «{term}» actualizado en el glosario.")

    def _abrir_glosario(self):
        from .herramientas import abrir_dialogo
        caja = {}

        def fabrica():
            caja["dlg"] = GlosarioDialog(self)
            return caja["dlg"]
        return abrir_dialogo(self, "glosario", fabrica, "Glosario de palabras clave", "Glosario", "book-open",
                             al_terminar=lambda _r: self.recalcular()
                             if getattr(caja.get("dlg"), "cambiado", False) else None)

    def _elegir_mencion(self, fila: int, buscar: bool = True):
        """Muestra los momentos y la carpeta de la mención. buscar=True (la eligió el usuario): va al primer momento
        y, si hay parte opcional, busca."""
        if fila < 0 or fila >= len(self.menciones):
            return
        m = self.menciones[fila]
        cambio = not self.mencion or self.mencion.get("term") != m["term"]
        self.mencion = m
        if buscar and self.modo == "ninguna":       # (elegirla la enseña: pasa a «Elegida»)
            self.set_modo("elegida")
        self._llenar_momentos(m)
        self._marcas()
        self._pintar_carpeta()
        dock = getattr(self, "carpetas_dock", None)
        if dock is not None:
            dock._seguir(m["term"])                   # 🗂 Carpetas (a la derecha) enseña la de esta palabra
        if buscar:                                    # el cabezal a su primera mención (o a su corte)
            ts = sorted(self._tiempos_de(m))
            if ts:
                self._ir_a(ts[0])
        if not HAY_INTERNET:
            return
        if not buscar:
            if cambio:
                self._pintar_mods(m.get("mods") or [])
            return
        self._pintar_mods(m.get("mods") or [])
        self._buscar(m["term"], self._mods_marcados(), self._tipo())

    LOTE_MOMENTOS = 40                # (⚡ las primeras filas al momento; el resto, a tandas sin bloquear)

    def _llenar_momentos(self, m: dict):
        """Una fila por momento: casilla (poner el clip ahí), mm:ss + contexto (pulsar = ir) y 📍 (poner solo ahí).
        ⚡ Con cientos de momentos (2 h de narración), las primeras LOTE_MOMENTOS filas salen al momento y el resto se
        añade a tandas (antes, 441 filas tardaban ~0,6 s y «Dijiste…» se quedaba parado)."""
        self.lista_momentos.clear()
        self._casillas = []
        self._momentos_m = m
        self._momentos_gen = getattr(self, "_momentos_gen", 0) + 1
        self._llenar_tanda(m, 0, self._momentos_gen, self.LOTE_MOMENTOS)

    def _llenar_tanda(self, m: dict, desde: int, gen: int, cuantos: int = 120):
        if gen != getattr(self, "_momentos_gen", 0):
            return                                   # (ya se eligió otra palabra)
        hits = m["hits"]
        hasta = min(len(hits), desde + cuantos)
        for h in hits[desde:hasta]:
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
            try:                                # 🔎 buscar material para esta frase (sección de Medios)
                from .material_por_frases_panel import boton_por_frase
                hl.addWidget(boton_por_frase(self, m, h))
            except Exception:                   # (la fila sale igual; el fallo, UNA vez en registros\errores.log)
                if not getattr(ClipsPanel, "_mpf_fallo_apuntado", False):
                    ClipsPanel._mpf_fallo_apuntado = True
                    try:
                        import time as _t
                        import traceback as _tb
                        from ..core.paths import log_path as _log
                        with open(_log(), "a", encoding="utf-8") as _f:
                            _f.write(f"\n[{_t.strftime('%Y-%m-%d %H:%M:%S')}] Botón «Buscar material para esta "
                                     f"frase»:\n{_tb.format_exc()}")
                    except Exception:  # noqa: BLE001 - apuntarlo nunca debe romper «Dijiste…»
                        pass
            it = QListWidgetItem()
            it.setSizeHint(fila.sizeHint())
            self.lista_momentos.addItem(it)
            self.lista_momentos.setItemWidget(it, fila)
            self._casillas.append((cas, h))
        if hasta < len(hits):
            QTimer.singleShot(0, lambda: self._llenar_tanda(m, hasta, gen))

    MAX_MARCAS = 800                  # (con «📍 Todas»: como mucho estas marcas, para que la línea siga fluida)

    def _marcas(self):
        """🎬 Las banderitas en la línea de tiempo, según el modo: «todas» (la elegida, resaltada), «elegida» (solo la
        palabra elegida) o «ninguna». Lo dicho en una parte que quitaste va como muesca en su corte."""
        self._ts_cache = None
        self._clips_media = {}            # (⚡ los trozos de cada archivo, para los cortes: una vez por pasada)
        foco = self.mencion["term"] if self.mencion is not None else ""
        if self.modo == "todas":
            self.hints_changed.emit(self._marcas_todas(foco))
        else:
            self._tope_avisado(False)
            self.hints_changed.emit(self._marcas_de(self.mencion)
                                    if self.mencion is not None and self.modo == "elegida" else [])
        self.foco_changed.emit(foco)
        self._act_nav()

    def _t_hit(self, h: dict, m: dict | None) -> tuple[float | None, bool]:
        """(momento en la línea de tiempo, ¿cortado?) de una vez que lo dices: si está en una parte que quitaste, el
        corte donde quedó (None si no queda nada de ese archivo)."""
        if _momento(h) is not None:
            return float(h["tl"]), False
        mid = h.get("media_id") or (m or {}).get("media_id")
        if not mid or h.get("src") is None:
            return None, True
        cache = self.__dict__.setdefault("_clips_media", {})
        if mid not in cache:                     # (⚡ un índice ordenado por archivo, una vez por pasada)
            cache[mid] = mapping.CutIndex(self.ctrl.project, mid)
        return cache[mid].point(float(h["src"])), True

    def _tiempos_de(self, m: dict) -> list[float]:
        """Los momentos (o cortes) de la línea de tiempo donde está la palabra m."""
        return [t for t, _c in (self._t_hit(h, m) for h in m.get("hits") or []) if t is not None]

    def _marcas_de(self, m: dict) -> list[tuple[float, str]]:
        from .hint_marks import CORTADA
        out = []
        for h in m.get("hits") or []:
            t, cortada = self._t_hit(h, m)
            if t is not None:
                out.append((t, ("🎬" + CORTADA + " " if cortada else "🎬 ") + m["term"]))
        return out

    def _selector_modo(self) -> QWidget:
        """🔑 Todas · Elegida · Ninguna: qué palabras clave se ven en la regla (lo mismo que el botón de la esquina de
        la regla). Tres partes con icono monocromo y texto corto; el porqué, en el tooltip."""
        from . import diseno as _D
        from . import hint_marks as HM
        from PySide6.QtWidgets import QButtonGroup, QToolButton
        caja = _Segmentado()
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        caja.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._grupo_modo = QButtonGroup(caja)
        self._grupo_modo.setExclusive(True)
        self.btn_modo = {}
        for k in HM.MODOS:
            b = QToolButton(caja)
            b.setText(HM.NOMBRE_MODO[k])
            b.setIcon(_D.icono(HM.ICONO_MODO[k]))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setChecked(k == self.modo)
            b.setToolTip(HM.TIP_MODO[k] + ". Lo mismo que el botón de palabras clave de la esquina de la regla.")
            b.setProperty("segmento", k)
            self._grupo_modo.addButton(b)
            lay.addWidget(b)
            caja.botones.append(b)
            self.btn_modo[k] = b
        self.btn_todas = self.btn_modo["todas"]     # (el «📍 Todas» de antes)
        self._grupo_modo.buttonToggled.connect(lambda b, on: on and self.set_modo(b.property("segmento")))
        return caja

    def set_fila_kw(self, on: bool):
        """⚡ El botón «Material» al día (sin avisar otra vez): la fila se encendió o apagó desde otro sitio."""
        b = getattr(self, "btn_fila_kw", None)
        if b is not None and b.isChecked() != bool(on):
            b.blockSignals(True)
            b.setChecked(bool(on))
            b.blockSignals(False)

    def set_modo(self, modo: str):
        """🔑 Cambia qué palabras se ven en la regla (y avisa al botón de la regla: modo_changed). Se recuerda."""
        from .hint_marks import MODOS, guardar_modo
        if modo not in MODOS:
            return
        b = getattr(self, "btn_modo", {}).get(modo)
        if b is not None and not b.isChecked():
            self._grupo_modo.blockSignals(True)
            b.setChecked(True)
            self._grupo_modo.blockSignals(False)
        if modo == self.modo:
            return
        self.modo = modo
        guardar_modo(modo)
        self._marcas()
        self.modo_changed.emit(modo)

    def _marcas_todas(self, foco: str) -> list[tuple[float, str]]:
        """Las marcas de todas las palabras. Si pasan de MAX_MARCAS: todas las de la elegida y, con el resto del
        cupo, las demás repartidas a lo largo de todo el video."""
        mias, otras = [], []
        for m in self.menciones:
            dest = mias if foco and m["term"] == foco else otras
            dest += self._marcas_de(m)
        total = len(mias) + len(otras)
        if total <= self.MAX_MARCAS:
            self._tope_avisado(False)
            return sorted(mias + otras)
        otras.sort()
        cupo = max(0, self.MAX_MARCAS - len(mias))
        if cupo >= len(otras):
            elegidas = otras
        elif cupo <= 0:
            elegidas = []
        elif cupo == 1:
            elegidas = [otras[len(otras) // 2]]
        else:                             # (de la primera a la última, a pasos iguales)
            paso = (len(otras) - 1) / (cupo - 1)
            elegidas = [otras[round(k * paso)] for k in range(cupo)]
        marcas = sorted(mias + elegidas)
        self._tope_avisado(True, total, len(marcas), foco)
        return marcas

    def _tope_avisado(self, recortado: bool, total: int = 0, vistas: int = 0, foco: str = ""):
        if recortado:
            de = f"todas las de «{foco}» y las demás repartidas" if foco else "repartidas por todo el video"
            self._aviso(f"📍 Hay {total} marcas: se ven {vistas} ({de}) para que la línea de tiempo siga fluida.")
            self._aviso_tope = True
        elif self._aviso_tope:
            self._aviso_tope = False
            self._aviso("")

    def elegir_palabra(self, term: str):
        """🔑 Clic en la muesca de otra palabra en la línea de tiempo: «Dijiste…» pasa a esa palabra (sin mover el
        cabezal: ya fue a la muesca)."""
        key = str(term or "").casefold()
        fila = next((i for i, m in enumerate(self.menciones) if m["term"].casefold() == key), -1)
        if fila < 0 or (self.mencion is not None and self.mencion["term"].casefold() == key):
            return
        self.elegir_indice(fila, buscar=False)

    # ------------------------------------------------------------------ 🧭 recorrer dónde se dice
    def _nav_todas(self) -> bool:
        """🧭 Se recorren todas las palabras: sin palabra elegida (con «📍 Todas») o si la elegida no tiene momentos
        con hora."""
        if self.mencion is not None:
            return not self._tiempos_de(self.mencion)
        return self.modo == "todas"

    def _tiempos_nav(self) -> list[float]:
        """Los momentos a recorrer (ordenados): los de la palabra elegida; si no, los de todas (ver _nav_todas)."""
        clave = (id(self.mencion), id(self.menciones), len(self.menciones), self.modo)
        if self._ts_cache is not None and self._ts_cache[0] == clave:
            return self._ts_cache[1]
        if self._nav_todas():
            ts = [t for m in self.menciones for t in self._tiempos_de(m)]
        elif self.mencion is not None:
            ts = self._tiempos_de(self.mencion)          # (también los cortes de lo que quitaste)
        else:
            ts = []
        ts = sorted(set(round(t, 3) for t in ts))
        self._ts_cache = (clave, ts)
        return ts

    def al_cabezal(self, t: float):
        """El cabezal se movió: «más cercana / más lejana» se recalculan (barato: solo si se ve el panel)."""
        self.cabezal = float(t)
        if self.isVisible():
            self._act_nav()

    @staticmethod
    def _vecinas(ts: list[float], c: float):
        """(anterior, siguiente, más cercana, más lejana) respecto a c; None si no hay. «Más cercana» no cuenta la
        que está justo en el cabezal (<0,05 s)."""
        if not ts:
            return None, None, None, None
        i = bisect.bisect_left(ts, c - 0.05)
        ant = ts[i - 1] if i > 0 else None
        j = bisect.bisect_right(ts, c + 0.05)
        sig = ts[j] if j < len(ts) else None
        cand = [x for x in (ant, sig) if x is not None]
        cerca = min(cand, key=lambda x: abs(x - c)) if cand else None
        lejos = max((ts[0], ts[-1]), key=lambda x: abs(x - c))
        if abs(lejos - c) < 0.05:
            lejos = None
        return ant, sig, cerca, lejos

    def _act_nav(self):
        if not hasattr(self, "btn_cerca"):
            return
        ts = self._tiempos_nav()
        ant, sig, cerca, lejos = self._vecinas(ts, self.cabezal)
        todas = bool(ts) and self._nav_todas()
        estado = (ant, sig, cerca, lejos, todas)
        if estado == self._nav_estado:
            return                        # (nada cambió: no se repinta nada al reproducir)
        self._nav_estado = estado
        que = ("cualquiera de las palabras clave (la palabra elegida o todas: ahora, todas)" if todas
               else "la palabra elegida (o todas, sin elegir ninguna y con «📍 Todas»)")
        self.btn_ant.setEnabled(ant is not None)
        self.btn_sig.setEnabled(sig is not None)
        self.btn_ant.setToolTip(f"Ir a la vez anterior (antes del cabezal) en que dices {que}")
        self.btn_sig.setToolTip(f"Ir a la vez siguiente (después del cabezal) en que dices {que}")
        self.btn_cerca.setEnabled(cerca is not None)
        self.btn_lejos.setEnabled(lejos is not None)
        self.btn_cerca.setText("⇢ Más cercana" + (f" {_mmss(cerca)}" if cerca is not None else ""))
        self.btn_lejos.setText("⇢ Más lejana" + (f" {_mmss(lejos)}" if lejos is not None else ""))
        self.btn_cerca.setToolTip(f"Ir a la vez más cercana al cabezal en que dices {que}")
        self.btn_lejos.setToolTip(f"Ir a la vez más lejana del cabezal en que dices {que}")

    def _ir_a(self, t: float):
        self.cabezal = t
        self.seek_requested.emit(t)
        self._act_nav()

    def _ir_vecina(self, sentido: int):
        ant, sig, _c, _l = self._vecinas(self._tiempos_nav(), self.cabezal)
        t = sig if sentido > 0 else ant
        if t is None:
            self._aviso("No hay más veces " + ("después" if sentido > 0 else "antes") + " del cabezal.")
            return
        self._ir_a(t)

    def _ir_extremo(self, cerca: bool):
        _a, _s, c, lj = self._vecinas(self._tiempos_nav(), self.cabezal)
        t = c if cerca else lj
        if t is not None:
            self._ir_a(t)

    def _quitar_marcas(self):
        """✕: fuera las marcas = modo «Ninguna» (al elegir otra palabra vuelven, en «Elegida»)."""
        self.set_modo("ninguna")

    def _ir_momento(self, h: dict):
        t, cortada = self._t_hit(h, getattr(self, "_momentos_m", None) or self.mencion)
        if t is None:
            self._aviso("Ese momento está cortado y no queda nada de ese archivo en la línea de tiempo.")
            return
        if cortada:
            self._aviso("Dicho en una parte que quitaste: el cabezal va al corte donde estaba.")
        self.seek_requested.emit(t)

    # ------------------------------------------------------------------ 📍 poner donde lo dices
    def _cabezal(self) -> float:
        """Segundo de la línea de tiempo donde está el cabezal (la línea roja)."""
        return float(getattr(self.timeline, "playhead", 0.0) or 0.0)

    def _hits_cabezal(self) -> list[dict]:
        return [{"tl": self._cabezal(), "cabezal": True}]

    def _hits_marcados(self) -> list[dict]:
        """Los momentos marcados de la palabra elegida (también los de filas que aún no se han pintado)."""
        m = getattr(self, "_momentos_m", None)
        if m is None or m is not self.mencion:
            return [h for cas, h in self._casillas if cas.isChecked() and cas.isEnabled() and _momento(h) is not None]
        return [h for h in m["hits"] if _momento(h) is not None
                and (m["term"], round(float(h["src"]), 2)) not in self._desmarcados]

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
