"""
🔎 Sección «Material por frases» (Medios, debajo de «Archivos / Carpeta»): buscar material conforme a frases y palabras
clave y ponerlo donde lo dices. La lógica está en ai/material_por_frases.py (sin Qt); aquí solo la interfaz.

Todo a la vista en una sola sección, sin ventanas emergentes:
  · tipo (Imágenes / Videos / Ambos) y duración del trozo (15 s / 30 s / 1 min), recordados; los videos solo salen en
    la versión con la parte privada (M.hay_videos());
  · el botón principal y ✕ para cancelar; progreso y una línea de estado;
  · una lista adaptable con dos grupos: «Resultados para «…»» (búsqueda manual de una frase: miniatura grande, vista
    grande al pasar el ratón, un clic = bajar y poner en el cabezal) y «Puesto en la línea de tiempo» (el resumen:
    ir, cambiar por otra, quitar; los botones salen sobre la miniatura al pasar el ratón).
El trabajo pesado (buscar, bajar, CLIP) va por la cola única de análisis (ui/cola_analisis.py, prioridad ALTA porque
lo estás esperando) y se puede cancelar; la colocación (un Ctrl+Z) se hace en el hilo de la interfaz.

  MaterialPorFrases(ctrl)                      el widget (se coloca donde se quiera)
  panel_activo() -> MaterialPorFrases | None   el que está en la ventana (para el botón de cada frase de «Dijiste…»)
  boton_por_frase(parent, mencion, hit)        el botón «Buscar material para esta frase» de una fila de «Dijiste…»
"""
from __future__ import annotations

import os
import weakref

from PySide6.QtCore import QRect, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListWidgetItem, QProgressBar, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..ai import material_por_frases as M
from . import diseno as D
from . import theme as T

CLAVE = "material_frases"
TIPOS = [("imagenes", "image", "Imágenes", "Solo imágenes con licencia libre (Openverse y Wikimedia Commons), con su "
                                          "autor y licencia en los créditos"),
         ("videos", "film", "Videos", ""),
         ("ambos", "copy-plus", "Ambos", "")]
TROZOS = [(15, "15 s"), (30, "30 s"), (60, "1 min")]
ROL = int(Qt.UserRole) + 60                     # ("res" | "sum", índice)
ICONO_W, ICONO_H = 128, 72                      # miniatura grande (16:9)
_PANELES: list = []                             # (weakref del panel que está en la ventana)


def panel_activo():
    """La sección que está en la ventana (colocada dentro de algo y a la vista); si no, la última creada viva."""
    vivos = []
    for ref in list(_PANELES):
        w = ref()
        try:
            if w is None:
                raise RuntimeError
            colocada = w.parent() is not None and w.isVisible()
        except RuntimeError:
            _PANELES.remove(ref)
            continue
        vivos.append((not colocada, w))
    if not vivos:
        return None
    return min(vivos, key=lambda x: x[0])[1]


def _tv_no_puesto(error: str | None) -> str:
    tv = M.textos_video()
    return tv.get("no_puesto", "No se pudo poner: {error}").format(
        error=error or tv.get("fallo_generico", "no se pudo"))


def _es_amable(txt: str) -> bool:
    """¿El error ya se entiende (frase en español, sin jerga)? Entonces se enseña tal cual."""
    t = txt.lower()
    return bool(txt) and not any(k in t for k in ("error", "exception", "traceback", "http", "errno", "winerror",
                                                     "none", "object", "attribute", "keyerror", "valueerror"))


def _mmss(t: float) -> str:
    from ..core.keyword_place import mmss
    return mmss(t)


def _miniatura(ruta: str) -> QIcon:
    """Miniatura recortada a 16:9 (la lista mide igual todas las filas)."""
    pm = QPixmap(ruta) if ruta and os.path.isfile(ruta) else QPixmap()
    w, h = D.px(ICONO_W), D.px(ICONO_H)
    if pm.isNull():
        out = QPixmap(w, h)
        out.fill(QColor(T.FIELD))
        return QIcon(out)
    pm = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = max(0, (pm.width() - w) // 2), max(0, (pm.height() - h) // 2)
    return QIcon(pm.copy(x, y, w, h))


# ---------------------------------------------------------------- botones que nunca cortan su texto
class _BotonPrincipalAdaptable(D.BotonPrincipal):
    """El botón principal del diseño que no impone ancho: con sitio dice la frase entera; si no cabe, una más corta
    («Buscar material por frases» → «Material por frases») y, muy estrecho, solo la lupa. La frase entera siempre está
    en el tooltip."""

    def __init__(self, nombre_icono: str = "", parent=None):
        super().__init__("", nombre_icono, "", parent)
        self._variantes: list[str] = [""]
        self._explicacion = ""

    def poner_variantes(self, variantes: list[str], explicacion: str = ""):
        self._variantes = [v for v in variantes if v] + [""]
        self._explicacion = explicacion
        self.setToolTip(self._variantes[0] + (chr(10) + explicacion if explicacion else ""))
        self.setAccessibleName(self._variantes[0])
        self._elegir()
        self.updateGeometry()

    def texto_completo(self) -> str:
        return self._variantes[0]

    def _ancho_para(self, texto: str) -> int:
        ic = (D.px(14) + (D.px(6) if texto else 0)) if self._icono else 0
        return ic + QFontMetrics(self.font()).horizontalAdvance(texto) + 2 * D.px(D.M2)

    def _elegir(self):
        w = self.width()
        texto = next((v for v in self._variantes if self._ancho_para(v) <= w), "")
        if texto != self.text():
            self.setText(texto)

    def sizeHint(self) -> QSize:               # noqa: N802  (lo que pide con la frase entera)
        return QSize(self._ancho_para(self._variantes[0]) + 2 * D.px(D.M1), D.px(D.ALTO_PRINCIPAL))

    def minimumSizeHint(self) -> QSize:        # noqa: N802  (solo la lupa: nunca ensancha el panel)
        return QSize(self._ancho_para(""), D.px(D.ALTO_PRINCIPAL))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elegir()

    def texto_cabe(self) -> bool:
        """(para las pruebas) ¿Cabe entero lo que dice ahora?"""
        return self._ancho_para(self.text()) <= self.width() + 1


class _BotonAdaptable(QPushButton):
    """Botón con icono y texto que, si no cabe, se queda solo con el icono (el texto, en el tooltip)."""

    def __init__(self, texto: str, nombre_icono: str, tooltip: str, parent=None):
        super().__init__(texto, parent)
        self._texto = texto
        self.setIcon(D.icono(nombre_icono))
        self.setToolTip(f"{texto}: {tooltip}" if tooltip else texto)
        self.setAccessibleName(texto)

    def _ancho_para(self, texto: str) -> int:
        ic = self.iconSize().width() + 4 if not self.icon().isNull() else 0
        return QFontMetrics(self.font()).horizontalAdvance(texto) + ic + D.px(14)

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(self._ancho_para(self._texto), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(self._ancho_para(""), super().minimumSizeHint().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        texto = self._texto if self._ancho_para(self._texto) <= self.width() else ""
        if texto != self.text():
            self.setText(texto)


# ---------------------------------------------------------------- lista con botones sobre la miniatura
class _ListaMaterial(D.ListaAdaptable):
    """ListaAdaptable con los botones de cada elemento (ir, cambiar, quitar / bajar y poner) sobre su miniatura: se
    ven al pasar el ratón y en el elegido."""
    accion = Signal(object, str)              # (item, clave de la acción)

    def __init__(self, panel, **k):
        super().__init__(**k)
        self._panel = panel

    def acciones_de(self, it) -> list[tuple[str, str, str]]:
        return self._panel._acciones(it) if it is not None else []

    def _rects(self, it) -> list[tuple[QRect, str, str, str]]:
        rect = self.visualItemRect(it)
        isz = self.iconSize()
        x0 = rect.left() + D.px(6)
        y0 = rect.top() + (rect.height() - isz.height()) // 2
        lado = D.px(22)
        acc = self.acciones_de(it)
        out = []
        x = x0 + isz.width() - D.px(3) - lado * len(acc) - D.px(2) * (len(acc) - 1)
        y = y0 + isz.height() - lado - D.px(3)
        for clave, icono, tip in acc:
            out.append((QRect(x, y, lado, lado), clave, icono, tip))
            x += lado + D.px(2)
        return out

    def _pintar(self, p, op, idx):
        super()._pintar(p, op, idx)
        it = self.item(idx.row())
        if it is None or self.es_grupo(it) or not (it.flags() & Qt.ItemIsEnabled):
            return
        p.save()                               # (siempre a la vista, en todas las tarjetas)
        p.setRenderHint(QPainter.Antialiasing)
        for r, _clave, icono, _tip in self._rects(it):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(QRectF(r), 3, 3)
            lado = D.px(14)
            p.drawPixmap(r.left() + (r.width() - lado) // 2, r.top() + (r.height() - lado) // 2,
                         D.pixmap_icono(icono, "#f0f0f0", lado))
        p.restore()

    def accion_en(self, pos) -> tuple[object, str] | None:
        it = self.itemAt(pos)
        if it is None or self.es_grupo(it):
            return None
        for r, clave, _i, _t in self._rects(it):
            if r.contains(pos):
                return it, clave
        return None

    def mousePressEvent(self, ev):             # noqa: N802
        hit = self.accion_en(ev.position().toPoint()) if ev.button() == Qt.LeftButton else None
        if hit is not None:
            self.setCurrentItem(hit[0])
            self.accion.emit(hit[0], hit[1])
            ev.accept()
            return
        super().mousePressEvent(ev)

    def viewportEvent(self, ev):               # noqa: N802
        if ev.type() == ev.Type.ToolTip:       # el tooltip del botón que está bajo el ratón
            hit = self.accion_en(ev.pos())
            if hit is not None:
                tip = next(t for _r, c, _i, t in self._rects(hit[0]) if c == hit[1])
                from PySide6.QtWidgets import QToolTip
                QToolTip.showText(ev.globalPos(), tip, self)
                return True
        return super().viewportEvent(ev)


# ---------------------------------------------------------------- la sección
class MaterialPorFrases(QWidget):
    """La sección completa (cabecera plegable + contenido). ctrl = ProjectController. fuentes = M.Fuentes (las pruebas
    pasan unas locales). con_videos=None: según M.hay_videos()."""
    ir_a = Signal(float)                      # (si la ventana no tiene motor: quien la coloque decide)

    def __init__(self, ctrl, fuentes=None, con_videos: bool | None = None, opciones: dict | None = None,
                 fuentes_video=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.fuentes = fuentes
        self.fuentes_video = fuentes_video     # (versión privada: material_videos.FuentesVideo; las pruebas, locales)
        self._oferta_seguir = None             # (clip, zona, ruta, desde, hasta) tras censurar algo que se mueve
        self.opciones = dict(opciones or {})   # (enc_texto / enc_imagen / detector: las pruebas)
        self.con_videos = M.hay_videos() if con_videos is None else bool(con_videos)
        self.resumen: list[dict] = []
        self.resultados: list[dict] = []
        self.res_frase: dict | None = None     # {"frase", "termino", "tl"} de la búsqueda manual
        self.trabajo = None
        self._ultimo_estado = ""
        _PANELES.insert(0, weakref.ref(self))
        st = QSettings("EditorIA", "EditorIA")
        self._st = st

        v = QVBoxLayout(self)
        v.setContentsMargins(0, D.px(D.M1), 0, 0)
        v.setSpacing(D.px(D.M1))

        # ---- cabecera plegable (como las secciones del Inspector)
        self.cabecera = QToolButton()
        self.cabecera.setObjectName("sectionhead")
        self.cabecera.setText("Material por frases")
        self.cabecera.setCheckable(True)
        self.cabecera.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.cabecera.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cabecera.setCursor(Qt.PointingHandCursor)
        self.cabecera.setToolTip("Busca material para lo que dices en la narración (frases y palabras clave), lo "
                                 "ordena por parecido real con lo que dices y lo pone en el momento en que lo dices")
        D.poner_cabecera(self.cabecera, "QToolButton#sectionhead", "border-radius: 4px; padding: 5px 6px; "
                         "text-align: left; font-weight: 600;")
        v.addWidget(self.cabecera)

        self.cuerpo = QWidget()
        cv = QVBoxLayout(self.cuerpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(D.px(D.M1))
        v.addWidget(self.cuerpo)
        v.addStretch(1)                      # (si le sobra alto, abajo: nunca huecos entre las filas)

        # ---- tipo y duración del trozo (solo con la parte de videos)
        self.fila_tipo = QWidget()
        ft = D.fila_fija(QHBoxLayout(self.fila_tipo))
        ft.setContentsMargins(0, 0, 0, 0)
        ft.setSpacing(D.px(D.M1))
        self.grupo_tipo = QButtonGroup(self)
        self.btn_tipo: dict[str, QPushButton] = {}
        tv = M.textos_video()                   # (los de videos, de la parte privada; sin ella, neutros)
        for clave, icono, texto, tip in TIPOS:
            b = _BotonAdaptable(texto, icono, tip or tv.get(f"tipo_{clave}", texto))
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.grupo_tipo.addButton(b)
            self.btn_tipo[clave] = b
            ft.addWidget(b)
            b.toggled.connect(lambda on, c=clave: on and self._poner_tipo(c))
        cv.addWidget(self.fila_tipo)

        self.fila_trozo = QWidget()
        fr = D.fila_fija(QHBoxLayout(self.fila_trozo))
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(D.px(D.M1))
        self.lb_trozo = D.etiqueta("Trozo", ajustar=False)
        self.lb_trozo.setToolTip(tv.get("trozo", "Duración de cada trozo"))
        fr.addWidget(self.lb_trozo)
        self.grupo_trozo = QButtonGroup(self)
        self.btn_trozo: dict[int, QPushButton] = {}
        for seg, texto in TROZOS:
            b = QPushButton(texto)
            b.setCheckable(True)
            b.setToolTip(tv.get("trozo_boton", "Trozos de {texto}").format(texto=texto))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.grupo_trozo.addButton(b)
            self.btn_trozo[seg] = b
            fr.addWidget(b)
            b.toggled.connect(lambda on, s=seg: on and self._poner_trozo(s))
        cv.addWidget(self.fila_trozo)

        # ---- botón principal + cancelar
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(D.px(D.M1))
        self.btn_buscar = _BotonPrincipalAdaptable("search")
        self.btn_buscar.clicked.connect(self.buscar_todo)
        self.btn_cancelar = D.BotonIcono("x", "Cancelar la búsqueda (lo ya puesto se queda)")
        self.btn_cancelar.clicked.connect(self.cancelar)
        self.btn_cancelar.setVisible(False)
        fila.addWidget(self.btn_buscar, 1)
        fila.addWidget(self.btn_cancelar)
        cv.addLayout(fila)

        self.progreso = QProgressBar()
        self.progreso.setTextVisible(False)
        self.progreso.setRange(0, 1000)
        D.medida(self.progreso, lambda w: w.setFixedHeight(D.px(4)))
        self.progreso.setVisible(False)
        cv.addWidget(self.progreso)
        self.estado = D.etiqueta("")
        self.estado.setVisible(False)
        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(0, 0, 0, 0)
        fila_estado.setSpacing(D.px(D.M1))
        self.icono_estado = QLabel()
        self.icono_estado.setVisible(False)
        fila_estado.addWidget(self.icono_estado, 0, Qt.AlignTop)
        fila_estado.addWidget(self.estado, 1)
        self.btn_seguir = QPushButton("Seguir")
        self.btn_seguir.setIcon(D.icono("crosshair"))
        self.btn_seguir.setToolTip("Lo censurado se mueve durante el trozo: el recuadro lo acompaña (seguimiento "
                                   "simple; un Ctrl+Z)")
        self.btn_seguir.clicked.connect(self.seguir)
        self.btn_seguir.setVisible(False)
        fila_estado.addWidget(self.btn_seguir, 0, Qt.AlignTop)
        cv.addLayout(fila_estado)

        # ---- resultados (manual) y resumen (automático), en una lista adaptable
        self.lista = _ListaMaterial(self, clave="", ancho_min=260, max_columnas=2, ajustar_alto=True, alto_max=300)
        self.lista.setIconSize(QSize(D.px(ICONO_W), D.px(ICONO_H)))
        self.lista.itemClicked.connect(self._clic)
        self.lista.accion.connect(self._accion)
        self.lista.setVisible(False)
        from . import miniaturas                  # (al pasar el ratón por un video: sus fotogramas en la casilla)
        miniaturas.activar_scrub(self.lista, self._dato_vista)
        cv.addWidget(self.lista)

        self.cabecera.toggled.connect(self._abrir)
        abierta = str(st.value(f"secciones/{CLAVE}", "true")).lower() in ("true", "1")
        self.cabecera.setChecked(abierta)
        self._abrir(abierta, guardar=False)
        tipo = str(st.value(f"{CLAVE}/tipo", "imagenes"))
        trozo = int(st.value(f"{CLAVE}/trozo", 30) or 30)
        self._tipo = tipo if (tipo in self.btn_tipo and (self.con_videos or tipo == "imagenes")) else "imagenes"
        self._trozo = trozo if trozo in self.btn_trozo else 30
        self.btn_tipo[self._tipo].setChecked(True)
        self.btn_trozo[self._trozo].setChecked(True)
        self._act_controles()

        self._t_proyecto = QTimer(self)
        self._t_proyecto.setSingleShot(True)
        self._t_proyecto.setInterval(150)
        self._t_proyecto.timeout.connect(self._refrescar_lista)
        ctrl.project_changed.connect(self._t_proyecto.start)
        if getattr(ctrl, "project_replaced", None) is not None:
            ctrl.project_replaced.connect(self.limpiar)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        w = self.width()
        k = 1.0 if w >= D.px(320) else 0.75 if w >= D.px(250) else 0.56      # (estrecho: miniatura más pequeña)
        tam = QSize(int(D.px(ICONO_W) * k), int(D.px(ICONO_H) * k))
        if self.lista.iconSize() != tam:
            self.lista.setIconSize(tam)

    # ---------------------------------------------------------------- estado de los controles
    def _abrir(self, on: bool, guardar: bool = True):
        self.cuerpo.setVisible(on)
        self.cabecera.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        if guardar:
            self._st.setValue(f"secciones/{CLAVE}", on)

    def _poner_tipo(self, clave: str):
        self._tipo = clave
        self._st.setValue(f"{CLAVE}/tipo", clave)
        self._act_controles()

    def _poner_trozo(self, seg: int):
        self._trozo = seg
        self._st.setValue(f"{CLAVE}/trozo", seg)

    def tipo(self) -> str:
        return self._tipo if self.con_videos else "imagenes"

    def trozo(self) -> int:
        return self._trozo

    def _act_controles(self):
        ocupado = self.trabajo is not None
        self.fila_tipo.setVisible(self.con_videos)
        self.fila_trozo.setVisible(self.con_videos and self.tipo() != "imagenes")
        if self.tipo() == "imagenes" and not self.con_videos:
            variantes = ["Buscar imágenes conforme a frases y palabras clave", "Buscar imágenes por frases",
                         "Imágenes por frases"]
        else:
            variantes = ["Buscar material conforme a frases y palabras clave", "Buscar material por frases",
                         "Material por frases"]
        self.btn_buscar.poner_variantes(variantes, (
            "Recorre tu narración: cada vez que dices una palabra clave (y las frases que nombran algo que se ve), "
            "busca material, lo ordena por parecido real con lo que dices, lo baja con sus créditos y lo pone en ese "
            "momento. Las imágenes van pequeñas, con sombra, sobre el video desenfocado. Todo se deshace con un "
            "Ctrl+Z y abajo queda la lista para cambiar o quitar cada una"))
        self.btn_buscar.setEnabled(not ocupado)
        self.btn_cancelar.setVisible(ocupado)
        for b in list(self.btn_tipo.values()) + list(self.btn_trozo.values()):
            b.setEnabled(not ocupado)
        self.btn_buscar.updateGeometry()

    def _poner_estado(self, texto: str, icono: str | None = None):
        self._ultimo_estado = texto
        self.estado.setText(texto)
        self.estado.setVisible(bool(texto))
        if icono and texto:
            self.icono_estado.setPixmap(D.pixmap_icono(icono, T.TEXT_DIM, D.px(14)))
        self.icono_estado.setVisible(bool(icono and texto))

    def _mensaje(self, texto: str, icono: str | None = None):
        self._poner_estado(texto, icono)
        try:
            self.ctrl.message.emit(texto)
        except (AttributeError, RuntimeError):
            pass

    # ---------------------------------------------------------------- la cola
    def _poner_en_cola(self, fn, titulo: str, al_terminar, clave: str):
        from . import cola_analisis
        self.progreso.setValue(0)
        self.progreso.setVisible(True)
        self._poner_estado(titulo)
        cola = cola_analisis.cola()

        def fin_ok(res):
            self._fin_trabajo()
            al_terminar(res)

        def fin_mal(err):
            self._fin_trabajo()
            txt = str(err or "").strip()
            if "ancel" in txt:
                self._mensaje("Búsqueda cancelada: lo ya puesto se queda.")
            elif _es_amable(txt):
                self._mensaje(f"⚠ {txt}")
            else:
                self._mensaje(f"⚠ No se pudo buscar: {txt}")
        self.trabajo = cola.poner(fn, titulo, prioridad=cola_analisis.ALTA, clave=f"{CLAVE}/{clave}", pesado=True,
                                  al_terminar=fin_ok, al_fallar=fin_mal)
        try:
            cola.cambiado.connect(self._progreso_cola, Qt.UniqueConnection)
        except (RuntimeError, TypeError):
            pass
        self._act_controles()

    def _progreso_cola(self):
        t = self.trabajo
        if t is None:
            return
        self.progreso.setValue(int(1000 * (t.progreso or 0.0)))
        if getattr(t, "texto", "") and t.texto != self._ultimo_estado:
            self._poner_estado(t.texto)

    def _fin_trabajo(self):
        self.trabajo = None
        self.progreso.setVisible(False)
        self._act_controles()

    def cancelar(self):
        if self.trabajo is not None:
            from . import cola_analisis
            cola_analisis.cola().cancelar(self.trabajo)

    def ocupado(self) -> bool:
        return self.trabajo is not None

    # ---------------------------------------------------------------- automático
    def _menciones(self) -> list[dict]:
        from ..ai import keyword_glossary as KG
        from ..ai.mentions import find_mentions
        from ..core import keyword_folders as KF
        try:
            from .library import _kw_root
            carpetas = KF.list_folders(_kw_root())
        except Exception:  # noqa: BLE001 - sin carpetas de palabras clave: solo lo detectado
            carpetas = []
        return find_mentions(self.ctrl.project, extra_terms=KF.terms(carpetas), glossary=KG.load())

    def buscar_todo(self):
        """El botón principal: momentos (aquí, rápido) → buscar y bajar (en la cola) → colocar (aquí, un Ctrl+Z)."""
        if self.trabajo is not None:
            return
        p = self.ctrl.project
        if not getattr(p, "transcripts", None):
            self._mensaje("Primero transcribe la narración: el material se busca por lo que dices.")
            return
        todos = M.momentos(p, self._menciones())
        if not todos:
            self._mensaje("No encontré frases con palabras clave ni cosas que se vean en tu narración.")
            return
        momentos = M.momentos_libres(p, todos)     # (los que ya tienen material de una pasada anterior, no)
        if not momentos:
            self._mensaje("Ya hay material en todas las frases (cámbialo o quítalo en la lista de abajo).")
            return
        # sin repetir: lo de esta sesión (claves y huellas del resumen), lo que ya está en la línea de tiempo (sus
        # créditos) y lo que ya tiene huella CLIP
        usados = M.huellas_en_proyecto(p) + [e["item"]["vec"] for e in self.resumen
                                              if isinstance(e.get("item"), dict) and e["item"].get("vec") is not None]
        urls = M.claves_en_proyecto(p) | {M._clave_item(e["item"]) for e in self.resumen
                                          if isinstance(e.get("item"), dict)}
        fuentes = self.fuentes or M.Fuentes()
        self._fuentes_pasada = fuentes
        tipo, trozo = self.tipo(), self.trozo()
        fv = (self.fuentes_video or M.nuevas_fuentes_video()) if tipo != "imagenes" else None
        if fv is not None:
            for k in ("fallos", "avisos"):
                if isinstance(getattr(fv, k, None), list):
                    getattr(fv, k).clear()
        self._fuentes_video_pasada = fv
        self._quitar_oferta_seguir()

        def trabajo(progress, cancelled):
            res = {"imagenes": [], "videos": []}
            if tipo in ("imagenes", "ambos"):
                res["imagenes"] = M.plan_automatico(momentos, fuentes, progress=progress, cancelled=cancelled,
                                                    usados=usados, urls_usadas=urls, **self._enc())
            if tipo in ("videos", "ambos"):
                res["videos"] = M.plan_videos(momentos, trozo, progress=progress, cancelled=cancelled,
                                              fuentes=fv, usados=usados,
                                              detector=self.opciones.get("detector"), **self._enc())
            return res
        self._poner_en_cola(trabajo, f"Buscando material para {len(momentos)} frases…", self._colocar, "todo")

    def _colocar(self, res: dict):
        p = self.ctrl.project                      # (por si editaste mientras se buscaba: cada frase, en su sitio)
        imagenes = M.momentos_libres_elegidos(p, M.actualizar_momentos(p, res.get("imagenes") or []))
        videos = M.actualizar_momentos(p, res.get("videos") or [])
        resumen = M.colocar_todo(self.ctrl, imagenes, videos)   # (un Ctrl+Z)
        fv = getattr(self, "_fuentes_video_pasada", None)
        no_bajados = [{"clip_id": None, "tl": float(a["momento"]["tl"]), "frase": a["momento"].get("frase", ""),
                       "termino": a["momento"].get("termino"), "tipo": "aviso", "item": a.get("item"),
                       "error": a.get("error") or ""} for a in (getattr(fv, "avisos", None) or [])]
        self.resumen = sorted(self.resumen + resumen + no_bajados, key=lambda e: e["tl"])
        self._refrescar_lista()
        fallos = list(getattr(getattr(self, "_fuentes_pasada", None), "fallos", None) or [])
        fallos_v = list(getattr(fv, "fallos", None) or [])
        avisos = []
        if fallos:
            avisos.append(f"⚠ La web de imágenes no respondió o limitó {len(fallos)} búsqueda(s): prueba otra vez "
                          "en un rato.")
        if fallos_v:
            avisos.append("⚠ " + M.textos_video().get("sin_conexion", "Sin conexión: prueba otra vez en un rato."))
        if no_bajados:
            avisos.append("⚠ " + M.textos_video().get("no_puestos", "{n} no se pudieron poner (lo ves en la "
                                                                   "lista).").format(n=len(no_bajados)))
        if resumen:
            self._mensaje(" ".join([f"✓ {len(resumen)} puestos donde lo dices (un Ctrl+Z los quita todos). "
                                    "Revísalos abajo."] + avisos))
        elif avisos:
            self._mensaje(" ".join(avisos))
        else:
            self._mensaje("No encontré material que se parezca a lo que dices.")

    # ---------------------------------------------------------------- manual (una frase de «Dijiste…»)
    def buscar_frase(self, frase: str, termino: str | None = None, tl: float | None = None):
        """«Buscar material para esta frase»: 4–6 resultados con miniatura grande; un clic baja y pone en el cabezal."""
        if self.trabajo is not None:
            self.cancelar()
            if self.trabajo is not None:
                self._mensaje("Espera a que se cancele la búsqueda anterior.")
                return
        if not self.cabecera.isChecked():
            self.cabecera.setChecked(True)
        self.res_frase = {"frase": frase, "termino": termino, "tl": tl}
        self.resultados = []
        self._refrescar_lista()
        fuentes = self.fuentes or M.Fuentes()
        tipo, trozo = self.tipo(), self.trozo()
        fv = (self.fuentes_video or M.nuevas_fuentes_video()) if tipo != "imagenes" else None
        if fv is not None and isinstance(getattr(fv, "fallos", None), list):
            fv.fallos.clear()
        self._fuentes_video_manual = fv
        self._quitar_oferta_seguir()

        def trabajo(progress, cancelled):
            progress(0.1, f"Buscando material para «{(termino or frase)[:40]}»…")
            res = []
            if tipo in ("imagenes", "ambos"):
                res += M.buscar_para_frase(frase, termino, fuentes, n=6 if tipo == "imagenes" else 3,
                                           cancelled=cancelled, **self._enc())
            if tipo in ("videos", "ambos"):
                res += M.buscar_videos_frase(frase, termino, trozo, fuentes=fv,
                                             n=6 if tipo == "videos" else 3, cancelled=cancelled, progress=progress,
                                             detector=self.opciones.get("detector"), **self._enc())
            return res

        def listo(res):
            self.resultados = list(res or [])
            self._refrescar_lista()
            sin_red = bool(getattr(fv, "fallos", None)) or bool(getattr(fuentes, "fallos", None))
            if self.resultados:
                self._poner_estado(f"{len(self.resultados)} resultados: un clic lo pone en el cabezal."
                                   + (" ⚠ Algunas búsquedas no respondieron." if sin_red else ""))
            elif sin_red:
                self._poner_estado("⚠ " + (M.textos_video().get("sin_conexion") if fv is not None else
                                           "La web de imágenes no respondió o limitó las búsquedas: prueba otra "
                                           "vez en un rato."))
            else:
                self._poner_estado("No encontré nada que se parezca a esa frase.")
        self._poner_en_cola(trabajo, f"Buscando material para «{(termino or frase)[:40]}»…", listo, "frase")

    def _enc(self) -> dict:
        return {k: v for k, v in self.opciones.items() if k in ("enc_texto", "enc_imagen")}

    def _cabezal(self) -> float:
        eng = getattr(self.window(), "engine", None)
        if eng is not None:
            return float(getattr(eng, "time", 0.0) or 0.0)
        tl = getattr(self.window(), "timeline", None)
        return float(getattr(tl, "playhead", 0.0) or 0.0)

    def _ir(self, t: float):
        eng = getattr(self.window(), "engine", None)
        if eng is not None and hasattr(eng, "user_seek"):
            eng.user_seek(float(t))
        self.ir_a.emit(float(t))

    def usar_resultado(self, i: int, t: float | None = None):
        """Baja el resultado i (en la cola) y lo pone en el cabezal (o en t)."""
        if not (0 <= i < len(self.resultados)) or self.trabajo is not None:
            return
        cand = self.resultados[i]
        rf = self.res_frase or {}
        donde = self._cabezal() if t is None else float(t)
        fuentes = self.fuentes or M.Fuentes()

        censurar = bool(cand.get("censurar"))
        detector = self.opciones.get("detector")
        es_video = cand.get("tipo") == "video"
        trozo = self.trozo()

        def trabajo(progress, cancelled):
            progress(0.2, "Preparando…")
            if es_video:
                ruta, mejor = M.bajar_video(cand, trozo, rf.get("termino"), rf.get("frase", ""),
                                            fuentes=self._fuentes_video_uso(), cancelled=cancelled, **self._enc())
                zona = M.zona_censura(ruta, True, max(0.0, mejor - 0.5), 6.0, detector=detector) if censurar else None
                return ruta, zona, mejor
            ruta = M.bajar_elegido(cand, fuentes, rf.get("termino"), rf.get("frase", ""))
            zona = M.zona_censura(ruta, detector=detector) if censurar else None
            return ruta, zona, 0.0

        def listo(res):
            ruta, zona, mejor = res
            cid = (M.poner_video_en(self.ctrl, ruta, donde, mejor, censura=zona) if es_video
                   else M.poner_en(self.ctrl, ruta, donde, censura=zona))
            if cid:
                self.resumen = sorted(self.resumen + [{
                    "clip_id": cid, "tl": donde, "frase": rf.get("frase", ""), "termino": rf.get("termino"),
                    "ruta": ruta, "item": cand, "tipo": "video" if es_video else "imagen",
                    "seccion": cand.get("seccion"),
                    "alternativas": [c for k, c in enumerate(self.resultados)
                                     if k != i and c.get("tipo", "imagen") == cand.get("tipo", "imagen")]}],
                    key=lambda e: e["tl"])
                self._refrescar_lista()
                if es_video:
                    self._mensaje(f"✓ Puesto en {_mmss(donde)}" + (" y censurado" if zona else "") +
                                  " (Ctrl+Z lo quita).")
                else:
                    self._mensaje(f"✓ Puesta en {_mmss(donde)}" + (" y censurada" if zona else "") +
                                  " (Ctrl+Z la quita).")
            else:
                self._mensaje("No se pudo poner en el cabezal.")
        self._poner_en_cola(trabajo, "Preparando el trozo elegido…" if es_video else "Bajando la imagen elegida…",
                            listo, "usar")

    # ---------------------------------------------------------------- resumen: ir, cambiar, quitar
    def quitar(self, i: int):
        if 0 <= i < len(self.resumen) and M.quitar(self.ctrl, self.resumen[i]):
            self._mensaje("Quitada de la línea de tiempo (Ctrl+Z la devuelve).")
        self._refrescar_lista()

    def cambiar(self, i: int):
        """La siguiente alternativa (sin repetir lo ya puesto), bajada en la cola."""
        if not (0 <= i < len(self.resumen)) or self.trabajo is not None:
            return
        e = self.resumen[i]
        puestos = {M._clave_item(x.get("item") or {}) for x in self.resumen}
        alts = [a for a in e.get("alternativas") or [] if M._clave_item(a) not in puestos]
        if not alts:
            self._mensaje("No quedan más opciones para esta frase.")
            return
        alt = alts[0]
        fuentes = self.fuentes or M.Fuentes()
        es_video = e.get("tipo") == "video"
        trozo = self.trozo()

        def trabajo(progress, cancelled):
            progress(0.2, "Preparando otra opción…")
            if es_video:
                return M.bajar_video(alt, trozo, e.get("termino"), e.get("frase", ""), fuentes=self._fuentes_video_uso(),
                                     cancelled=cancelled, **self._enc())
            return M.bajar_elegido(alt, fuentes, e.get("termino"), e.get("frase", "")), 0.0

        def listo(res):
            ruta, mejor = res
            antes = e.get("item")
            if es_video:
                nuevo = self._cambiar_video(e, ruta, mejor, alt)
            else:
                nuevo = M.cambiar(self.ctrl, e, ruta, alt)
            if nuevo:                              # (solo ahora se gasta la alternativa; la de antes, a la cola)
                e["alternativas"] = [a for a in e.get("alternativas") or [] if a is not alt] + \
                    ([antes] if antes else [])
                self._mensaje(f"✓ Cambiado lo de {_mmss(e['tl'])} (Ctrl+Z vuelve a lo anterior).")
            self._refrescar_lista()
        self._poner_en_cola(trabajo, "Preparando otra opción…", listo, "cambiar")

    def _cambiar_video(self, e: dict, ruta: str, mejor: float, alt: dict) -> str | None:
        """El trozo de ese momento por otro (un Ctrl+Z)."""
        self.ctrl.undo_stack.beginMacro("🔎 Cambiar el video de esta frase")
        try:
            cid = e.get("clip_id")
            if cid and cid in self.ctrl.project.clips:
                self.ctrl.delete_clips([cid])
            nuevo = M.poner_video_en(self.ctrl, ruta, float(e["tl"]), mejor)
        finally:
            self.ctrl.undo_stack.endMacro()
        if nuevo:
            e.update(clip_id=nuevo, ruta=ruta, item=alt, seccion=alt.get("seccion"))
        return nuevo

    def censurar(self, i: int):
        """🙈 Tapa la cara o la cámara del material ya puesto (un Ctrl+Z). Se mueve y cambia de tamaño en el visor;
        la forma, el tipo y la fuerza, en «Figuras geométricas → Tapar (censurar)»."""
        if not (0 <= i < len(self.resumen)) or self.trabajo is not None:
            return
        e = self.resumen[i]
        cid = e.get("clip_id")
        if not cid or cid not in self.ctrl.project.clips:
            return
        c = self.ctrl.project.clips[cid]
        es_video = e.get("tipo") == "video"
        detector = self.opciones.get("detector")
        ruta, desde, dur = e.get("ruta"), float(c.source_in), float(c.duration)

        def trabajo(progress, _cancelled):
            progress(0.3, "Buscando la cara o la cámara…")
            return M.zona_censura(ruta, es_video, desde, dur, detector=detector)

        def listo(zona):
            if cid not in self.ctrl.project.clips:
                return
            if M.aplicar_censura(self.ctrl, cid, zona):
                donde = ("encima de la cara" if zona.get("cara") else
                         "en la esquina, abajo a la derecha (no encontré ninguna cara)")
                mueve = bool(es_video and zona.get("se_mueve"))
                aviso = " Se mueve durante el trozo: pulsa «Seguir» para que el recuadro la acompañe." if mueve else ""
                if es_video:
                    self._mensaje(f"Censurado {donde}: mueve el recuadro o cambia su tamaño en el visor (Ctrl+Z lo "
                                  f"quita).{aviso}", "eye-off")
                else:
                    self._mensaje(f"Censurada {donde}: mueve el recuadro o cambia su tamaño en el visor (Ctrl+Z lo "
                                  f"quita).", "eye-off")
                self._oferta_seguir = (cid, zona, ruta, desde, desde + dur) if mueve else None
                self.btn_seguir.setVisible(mueve)
                if mueve and not self.cabecera.isChecked():   # (el aviso y «Seguir», a la vista aunque la sección
                    self.cabecera.blockSignals(True)          #  estuviera plegada; no se recuerda abierta)
                    self.cabecera.setChecked(True)
                    self.cabecera.blockSignals(False)
                    self._abrir(True, guardar=False)
                self._ir(e["tl"])
        self._poner_en_cola(trabajo, "Buscando qué tapar…", listo, "censurar")

    def seguir(self):
        """🎯 La censura fija pasa a seguir lo tapado (ai/tracking en la cola; un Ctrl+Z)."""
        if self._oferta_seguir is None or self.trabajo is not None:
            return
        cid, zona, ruta, desde, hasta = self._oferta_seguir
        self.btn_seguir.setVisible(False)

        def trabajo(progress, cancelled):
            progress(0.1, "Siguiendo lo censurado…")
            return M.plan_seguimiento(ruta, desde, hasta, zona, cancelled)

        def listo(trk):
            self._oferta_seguir = None
            if trk and cid in self.ctrl.project.clips and M.aplicar_seguimiento(self.ctrl, cid, trk):
                self._mensaje("El recuadro sigue a lo censurado (Ctrl+Z vuelve a la censura fija).", "crosshair")
            else:
                self._mensaje("No pude seguirlo: se queda la censura fija (muévela en el visor si hace falta).")
        self._poner_en_cola(trabajo, "Siguiendo lo censurado…", listo, "seguir")

    def _quitar_oferta_seguir(self):
        self._oferta_seguir = None
        self.btn_seguir.setVisible(False)

    def _fuentes_video_uso(self):
        fv = self.fuentes_video or getattr(self, "_fuentes_video_manual", None) or M.nuevas_fuentes_video()
        return fv

    def marcar_censura(self, i: int):
        """En un resultado (aún sin poner): se censura al ponerlo. Otro clic lo desmarca."""
        if 0 <= i < len(self.resultados):
            c = self.resultados[i]
            c["censurar"] = not c.get("censurar")
            self._refrescar_lista()

    def limpiar(self):
        self.cancelar()
        self._oferta_seguir = None
        self.btn_seguir.setVisible(False)
        self.resumen, self.resultados, self.res_frase = [], [], None
        self._poner_estado("")
        self._refrescar_lista()

    # ---------------------------------------------------------------- la lista
    def _acciones(self, it) -> list[tuple[str, str, str]]:
        dato = it.data(ROL)
        if not dato:
            return []
        if dato[0] == "aviso":
            return []
        if dato[0] == "res":
            marcado = dato[1] < len(self.resultados) and self.resultados[dato[1]].get("censurar")
            return [("censurar", "eye-off", "No censurar al ponerlo" if marcado else
                     "Censurar: al ponerlo, tapa la cara o la cámara con un recuadro borroso"),
                    ("usar", "download", "Bajar y poner en el cabezal")]
        return [("ir", "crosshair", "Ir a este momento"),
                ("censurar", "eye-off", "Censurar: tapa la cara o la cámara con un recuadro borroso (luego muévelo "
                                         "o cambia su tamaño en el visor; forma, tipo y fuerza en Figuras geométricas)"),
                ("cambiar", "replace", "Cambiar por otra opción"),
                ("quitar", "trash-2", "Quitar de la línea de tiempo")]

    def _accion(self, it, clave: str):
        dato = it.data(ROL)
        if not dato:
            return
        k, i = dato
        if k == "res" and clave == "usar":
            self.usar_resultado(i)
        elif k == "res" and clave == "censurar":
            self.marcar_censura(i)
        elif k == "sum" and clave == "censurar":
            self.censurar(i)
        elif k == "sum" and clave == "ir" and i < len(self.resumen):
            self._ir(self.resumen[i]["tl"])
        elif k == "sum" and clave == "cambiar":
            self.cambiar(i)
        elif k == "sum" and clave == "quitar":
            self.quitar(i)

    def _clic(self, it):
        dato = it.data(ROL)
        if not dato:
            return
        if dato[0] == "res":
            self.usar_resultado(dato[1])
        elif dato[1] < len(self.resumen):
            self._ir(self.resumen[dato[1]]["tl"])

    def _dato_vista(self, it):
        """El archivo de la casilla (el scrub solo cambia las de video; las imágenes se quedan como están)."""
        dato = it.data(ROL) if it is not None else None
        if not dato:
            return None
        if dato[0] == "res" and dato[1] < len(self.resultados):
            return self.resultados[dato[1]].get("thumb_local")
        if dato[0] == "sum" and dato[1] < len(self.resumen):
            return self.resumen[dato[1]].get("ruta")
        return None

    @staticmethod
    def _credito(item: dict | None) -> str:
        item = item or {}
        if item.get("tipo") == "video":
            partes = ["Oficial" if item.get("official") else "", item.get("channel") or ""]
        else:
            partes = [item.get("license_text") or "", item.get("creator") or ""]
        return " · ".join(x for x in partes if x and x != "desconocido")

    @staticmethod
    def _trozo_txt(seccion) -> str:
        if not seccion:
            return ""
        return f"Trozo {_mmss(seccion[0])}–{_mmss(seccion[1])}"

    def _refrescar_lista(self):
        lista = self.lista
        lista.setUpdatesEnabled(False)
        lista.clear()
        p = self.ctrl.project
        if self.res_frase is not None:
            quien = self.res_frase.get("termino") or self.res_frase.get("frase", "")
            g = lista.agregar_grupo(f"Resultados para «{quien}»")
            g.setToolTip(self.res_frase.get("frase", ""))
            for i, c in enumerate(self.resultados):
                texto = "\n".join(x for x in (c.get("title") or "(sin título)", self._credito(c),
                                              f"Parecido {round(100 * float(c.get('parecido', 0)))} %",
                                              (self._trozo_txt(c.get("seccion")) or "Trozo: se busca al ponerlo")
                                              if c.get("tipo") == "video" else "",
                                              "Se censura al ponerlo" if c.get("censurar") else "") if x)
                it = QListWidgetItem(_miniatura(c.get("thumb_local") or ""), texto)
                it.setData(ROL, ("res", i))
                it.setToolTip(f"{c.get('title') or ''}\n{c.get('attribution') or self._credito(c)}\n"
                              "Clic = bajar y poner en el cabezal")
                lista.agregar(it, g)
        if self._oferta_seguir is not None and self._oferta_seguir[0] not in p.clips:
            self._quitar_oferta_seguir()
        if self.resumen:
            vivos = sum(1 for e in self.resumen if e.get("clip_id") in p.clips)
            g = lista.agregar_grupo(f"Puesto en la línea de tiempo ({vivos})")
            g.setToolTip("Lo que se puso: clic = ir a ese momento; sobre la miniatura, cambiar por otra o quitar")
            for i, e in enumerate(self.resumen):
                if e.get("tipo") == "aviso":            # (no se pudo poner)
                    texto = "\n".join(x for x in (f"{_mmss(e['tl'])} · {e.get('termino') or 'Frase'}",
                                                  _tv_no_puesto(e.get("error")),
                                                  self._credito(e.get("item"))) if x)
                    it = QListWidgetItem(_miniatura((e.get("item") or {}).get("thumb_local") or ""), texto)
                    it.setData(ROL, ("aviso", i))
                    it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                    it.setToolTip(e.get("error") or "")
                    lista.agregar(it, g)
                    continue
                vivo = e.get("clip_id") in p.clips
                cab = f"{_mmss(e['tl'])} · {e.get('termino') or 'Frase'}" + ("" if vivo else " (quitado)")
                texto = "\n".join(x for x in (cab, f"«{e.get('frase', '')}»" if e.get("frase") else "",
                                              self._credito(e.get("item")),
                                              self._trozo_txt(e.get("seccion")) if e.get("tipo") == "video" else "")
                                 if x)
                es_video = e.get("tipo") == "video"
                mini = ((e.get("item") or {}).get("thumb_local") or "") if es_video else (e.get("ruta") or "")
                it = QListWidgetItem(_miniatura(mini), texto)
                it.setData(ROL, ("sum", i))
                if not vivo:
                    it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                it.setToolTip("Clic = ir a este momento")
                lista.agregar(it, g)
        lista.setUpdatesEnabled(True)
        lista.setVisible(lista.count() > 0)


# ---------------------------------------------------------------- el botón de cada frase de «Dijiste…»
def frase_de(project, mencion: dict, hit: dict) -> str:
    words = ((getattr(project, "transcripts", None) or {}).get(mencion.get("media_id")) or {}).get("words") or []
    fr = M.frase_en(words, float(hit.get("src", 0.0))) if words else None
    return fr[0] if fr else (hit.get("context") or mencion.get("term") or "")


def boton_por_frase(parent, mencion: dict, hit: dict) -> QWidget:
    """«Buscar material para esta frase» (icono monocromo): abre los resultados en la sección «Material por frases»."""
    b = D.BotonIcono("search", "Buscar material para esta frase: 4–6 resultados en «Material por frases» (Medios); "
                               "un clic en uno lo baja y lo pone en el cabezal")

    def pulsar():
        panel = panel_activo()
        ctrl = getattr(parent, "ctrl", None)
        if panel is None:
            if ctrl is not None:
                ctrl.message.emit("Abre Medios: ahí está «Material por frases».")
            return
        project = (ctrl or panel.ctrl).project
        panel.buscar_frase(frase_de(project, mencion, hit), mencion.get("term"), hit.get("tl"))
    b.clicked.connect(pulsar)
    return b


def instalar(win) -> "MaterialPorFrases | None":
    """Pone la sección en Medios (win.library.poner_material_frases), una sola vez. Lo llama la ventana al crearse."""
    lib = getattr(win, "library", None)
    if lib is None or not hasattr(lib, "poner_material_frases"):
        return None
    ya = getattr(lib, "_material_frases", None)
    if ya is not None:
        return ya
    panel = MaterialPorFrases(win.ctrl)
    lib.poner_material_frases(panel)
    lib._material_frases = panel
    return panel
