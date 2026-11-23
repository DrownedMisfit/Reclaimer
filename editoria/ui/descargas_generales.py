"""
🌐 Panel «Descargas»: buscar y bajar de internet LO QUE QUIERAS (sin palabra clave), como en 🔑 Palabras clave.

  (22/11, de arriba abajo) buscar (una fila) · filtros · UNA fila de pestañas con su cuenta · las acciones abajo:
  Resultados (n): la misma búsqueda de Palabras clave (Videos / PNG recortado / Imágenes, pegar un enlace de YouTube,
           X, Instagram o TikTok) — parte opcional (ui/clips_internet.py, privada): sin ella, el panel enseña solo
           la carpeta
  En cola (n): «Descargas en cola»: lo que baja o espera y lo bajado en esta sesión (🔞 con la sesión del navegador)
  Carpeta (n): «Carpeta: …» (la carpeta general de lo descargado; se recuerda) y lo que hay en ella, con miniatura y
           duración · clic derecho: Poner en el cabezal · A Medios · «Mover a…» (Medios · Carpetas de palabra clave ▸
           [palabra] · Otra carpeta…) · Agregar a memes

Lo bajado entra en Medios en la categoría «🌐 Descargas».
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QSizePolicy, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..core.model import KIND_AUDIO, KIND_IMAGE, kind_for_path

try:    # parte opcional (privada): buscar y bajar; sin ella, solo lo ya descargado y «Mover a…»
    from .clips_internet import InternetMixin
    HAY_INTERNET = True
except ImportError:
    class InternetMixin:  # noqa: D101
        pass
    HAY_INTERNET = False

CLAVE = "descargas_generales/carpeta"
CATEGORIA = "🌐 Descargas"
MINI = QSize(144, 81)


def _ajustes() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


def carpeta_por_defecto() -> str:
    return os.path.join(os.path.expanduser("~"), "Videos", "Reclaimer - Descargas")


def carpeta_guardada() -> str:
    v = str(_ajustes().value(CLAVE, "") or "").strip()
    return v or carpeta_por_defecto()


def es_descarga(ruta: str, carpeta: str | None = None) -> bool:
    base = carpeta or carpeta_guardada()
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(ruta)),
                                   os.path.normcase(os.path.abspath(base))]) == os.path.normcase(os.path.abspath(base))
    except ValueError:
        return False


def _a_papelera(ruta: str) -> bool:
    from .library import _to_trash
    return bool(_to_trash(ruta))


def _soltar_del_visor(ruta: str) -> None:
    """(antiguo nombre) = core/soltar_archivos.soltar_archivos([ruta]): el visor, el motor propio y los análisis sueltan
    el archivo (Windows no deja moverlo si está abierto: «WinError 32»)."""
    from ..core.soltar_archivos import soltar_archivos
    soltar_archivos([ruta])


def explicar_fallo(motivo: str) -> str:
    """El motivo de un archivo que no se pudo mover o quitar, en palabras de persona."""
    m = (motivo or "").lower()
    if ("winerror 32" in m or "being used" in m or "otro proceso" in m or "used by another" in m
            or "abierto en otro programa" in m):
        return "está abierto en otro programa (ciérralo y vuelve a probar)"
    if "ya no existe" in m or "winerror 2]" in m or "no such file" in m:
        return "ya no existe"
    if "winerror 5]" in m or "denied" in m or "denegado" in m:
        return "Windows no deja tocarlo (permisos)"
    if "espacio" in m or "no space" in m or "winerror 112" in m:
        return "no queda espacio en el disco"
    return (motivo or "error desconocido")[:120]


def mover_ya(rutas: list[str], carpeta: str, cancelado=None) -> tuple[list, list]:
    """Mueve SIN ventanas (sirve en segundo plano): (movidos [(origen, destino)], fallos [(origen, motivo)]). Si uno
    falla por estar abierto, lo reintenta un par de segundos (el visor tarda un momento en soltarlo)."""
    import time
    from ..core import keyword_folders as KF
    movidos, fallos = [], []
    for r in rutas:
        if not os.path.isfile(r):
            fallos.append((r, "ya no existe"))
            continue
        hechos, mal = KF.move_files([r], carpeta)
        fin = time.monotonic() + 2.0
        while mal and os.path.isfile(r) and time.monotonic() < fin and not (cancelado and cancelado()):
            time.sleep(0.1)
            hechos, mal = KF.move_files([r], carpeta)
        movidos += hechos
        fallos += mal
    return movidos, fallos


_TRABAJOS: list = []          # (los «Mover a…» en marcha; las pruebas esperan a que acaben)


def mover(ctrl, rutas: list[str], carpeta: str, al_acabar=None, parent=None):
    """Mueve los archivos (con sus créditos) a otra carpeta EN SEGUNDO PLANO (entre discos es copiar: no congela).
    Antes, el visor los suelta (si los tenía abiertos, Windows no deja moverlos). Al acabar, los medios con esas rutas
    pasan a las nuevas (sus clips siguen viéndose) y se llama al_acabar(nuevas, fallos [(ruta, motivo legible)]).
    Devuelve el trabajo (None si no había nada que mover)."""
    rutas = [r for r in rutas if r]
    if not rutas:
        if al_acabar:
            al_acabar([], [])
        return None
    from ..core.soltar_archivos import soltar_archivos
    soltar_archivos(rutas)                    # 🔓 (el visor, el motor propio y los análisis los sueltan)
    from .jobs import BackgroundJob
    job = BackgroundJob(lambda _p, cancelado: mover_ya(rutas, carpeta, cancelado), parent)
    job.title = "🌐 Moviendo archivos"

    def listo(res):
        movidos, fallos = res or ([], [])
        nuevas = []
        for origen, nueva in movidos:
            if os.path.normcase(origen) != os.path.normcase(nueva) and hasattr(ctrl, "move_media_path"):
                ctrl.move_media_path(origen, nueva)
            nuevas.append(nueva)
        if al_acabar:
            al_acabar(nuevas, [(r, explicar_fallo(m)) for r, m in fallos])

    def mal(msg):
        if al_acabar:
            al_acabar([], [(r, explicar_fallo(msg)) for r in rutas])

    def fuera(j=job):
        if j in _TRABAJOS:
            _TRABAJOS.remove(j)
        from ..core.soltar_archivos import dejar_de_retener
        dejar_de_retener(rutas)               # (bien o mal: el visor ya puede volver a abrirlos si siguen ahí)

    job.done.connect(listo)
    job.failed.connect(mal)
    job.finished.connect(fuera)
    _TRABAJOS.append(job)
    job.start()
    return job


def moviendo() -> bool:
    """¿Hay algún «Mover a…» trabajando?"""
    return bool(_TRABAJOS)


def a_medios(ctrl, rutas: list[str]) -> list[str]:
    """A Medios; SOLO los que entran nuevos van a «🌐 Descargas» (la categoría que ya le pusiste se respeta)."""
    antes = set(ctrl.project.media)
    try:
        ids = [i for i in ctrl.import_now(list(rutas)) if i in ctrl.project.media]
    except Exception:  # noqa: BLE001
        return []
    nuevos = [i for i in ids if i not in antes]
    if nuevos:
        ctrl.set_media_props(nuevos, category=CATEGORIA)
    return ids


def usos(ctrl, rutas: list[str]) -> int:
    """Cuántos de esos archivos se usan en la línea de tiempo de este proyecto."""
    claves = {os.path.normcase(os.path.abspath(r)) for r in rutas}
    p = ctrl.project
    usados = {c.media_id for c in p.clips.values()}
    return sum(1 for m in p.media.values() if m.id in usados and m.path
               and os.path.normcase(os.path.abspath(m.path)) in claves)


def marcar_que_faltan(ctrl, rutas: list[str]) -> None:
    """Los medios de esos archivos (ya en la Papelera) salen como «no encontrado» (y se pueden volver a enlazar)."""
    claves = {os.path.normcase(os.path.abspath(r)) for r in rutas}
    ids = [m.id for m in ctrl.project.media.values() if m.path and not os.path.exists(m.path)
           and os.path.normcase(os.path.abspath(m.path)) in claves and m.id not in ctrl.missing]
    if ids:
        ctrl.missing.update(ids)
        ctrl.media_changed.emit()
        ctrl.project_changed.emit()


def a_la_papelera(ctrl, rutas: list[str], papelera) -> tuple[list, list]:
    """Manda archivos a la Papelera soltándolos antes del visor (si no, Windows no deja). (hechos, fallos legibles)"""
    import time
    from PySide6.QtCore import QCoreApplication
    hechos, fallos = [], []
    from ..core.soltar_archivos import soltando
    with soltando(rutas):                     # 🔓 (el visor, el motor propio y los análisis los sueltan)
        for r in rutas:
            ok = False
            fin = time.monotonic() + 2.0
            while True:
                try:
                    ok = bool(papelera(r))
                except Exception:  # noqa: BLE001
                    ok = False
                if ok or not os.path.exists(r) or time.monotonic() > fin:
                    break
                QCoreApplication.processEvents()          # (el reproductor tarda un momento en soltarlo)
                time.sleep(0.1)
            if ok or not os.path.exists(r):
                hechos.append(r)
            else:
                fallos.append((r, "está abierto en otro programa (ciérralo y vuelve a probar)"))
    marcar_que_faltan(ctrl, hechos)
    return hechos, fallos


def palabras_clave() -> list[dict]:
    """Las carpetas de palabra clave (las de 🔑 Palabras clave)."""
    try:
        from ..core import keyword_folders as KF
        from .clips_panel import _raiz_guardada
        return KF.list_folders(_raiz_guardada())
    except Exception:  # noqa: BLE001
        return []


def menu_mover(menu: QMenu, ctrl, rutas_fn, parent, al_acabar=None) -> QMenu:
    """«Mover a…»: Medios (la carpeta general) · Carpetas de palabra clave ▸ [palabra] · Otra carpeta…"""
    sub = menu.addMenu("Mover a…")
    sub.setToolTipsVisible(True)

    def hecho(donde: str):
        def fin(nuevas: list, fallos: list):
            if al_acabar:
                al_acabar()
            partes = [f"✓ {len(nuevas)} archivo(s) movido(s) a {donde}"] if nuevas else []
            if fallos:
                nom, motivo = os.path.basename(fallos[0][0]), fallos[0][1]
                partes.append(f"no se pudo mover «{nom}»" + (f" (y {len(fallos) - 1} más)" if len(fallos) > 1 else "")
                              + f": {motivo}")
            texto = " · ".join(partes) or "No había nada que mover."
            win = parent.window() if parent is not None else None
            if win is not None and hasattr(win, "statusBar"):
                win.statusBar().showMessage(texto, 10000)
            fin.texto = texto
        return fin

    def a_general():
        def luego(nuevas, fallos):
            a_medios(ctrl, nuevas)
            hecho("Medios")(nuevas, fallos)
        mover(ctrl, rutas_fn(), carpeta_guardada(), luego, parent)
    a = sub.addAction("Medios (carpeta general de descargas)", a_general)
    a.setToolTip("A la carpeta general de lo descargado y a Medios («🌐 Descargas»)")
    kw = sub.addMenu("Carpetas de palabra clave")
    kw.setToolTipsVisible(True)
    folders = palabras_clave()
    if not folders:
        kw.addAction("(aún no tienes carpetas de palabra clave)").setEnabled(False)
    for f in folders:
        def a_palabra(f=f):
            from ..core import keyword_folders as KF
            from .clips_panel import _raiz_guardada
            destino = f.get("own_path") or KF.create_folder(_raiz_guardada(), f["label"])
            mover(ctrl, rutas_fn(), destino, hecho(f"«{f['label']}»"), parent)
        kw.addAction(f"{f['label']}  ({f['count']})", a_palabra)

    def otra():
        d = QFileDialog.getExistingDirectory(parent, "Mover a la carpeta…", carpeta_guardada())
        if d:
            mover(ctrl, rutas_fn(), d, hecho(d), parent)
    sub.addAction("Otra carpeta…", otra)
    return sub


def partir_en_lineas(fm, texto: str, ancho: int) -> str:
    """El texto en líneas que caben en «ancho» (por palabras; una palabra más larga que el ancho, por letras)."""
    lineas, actual = [], ""
    for palabra in str(texto or "").split(" "):
        prueba = f"{actual} {palabra}" if actual else palabra
        if fm.horizontalAdvance(prueba) <= ancho:
            actual = prueba
            continue
        if actual:
            lineas.append(actual)
        actual = ""
        while fm.horizontalAdvance(palabra) > ancho and len(palabra) > 1:
            k = len(palabra)
            while k > 1 and fm.horizontalAdvance(palabra[:k]) > ancho:
                k -= 1
            lineas.append(palabra[:k])
            palabra = palabra[k:]
        actual = palabra
    if actual:
        lineas.append(actual)
    return "\n".join(lineas)


class _BotonCarpeta(QPushButton):
    """«Carpeta: …» con el nombre ENTERO: si no cabe en el ancho que tiene, en varias líneas (ningún texto cortado)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completo = ""
        self._ancho_hecho = -1
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(60)

    def poner(self, texto: str):
        self._completo = texto
        self._ancho_hecho = -1
        self._partir()

    def texto_completo(self) -> str:
        return self._completo

    def sizeHint(self):
        h = super().sizeHint()
        return QSize(min(h.width(), self.fontMetrics().horizontalAdvance(self._completo) + 24), h.height())

    def minimumSizeHint(self):
        return QSize(60, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._partir()

    def _partir(self):
        libre = max(20, self.width() - 18)
        if libre == self._ancho_hecho:
            return
        self._ancho_hecho = libre
        texto = partir_en_lineas(self.fontMetrics(), self._completo, libre)
        if texto != super().text():
            self.setText(texto)
            self.updateGeometry()


class _ListaArchivos(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setIconSize(MINI)
        self.setGridSize(QSize(MINI.width() + 20, MINI.height() + 40))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.mime_extra = None                 # (fn(md, rutas): lo que añada el panel a lo arrastrado o copiado)

    def mimeData(self, items):
        rutas = [it.data(Qt.UserRole) for it in items if it is not None and it.data(Qt.UserRole)]
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(r) for r in rutas])
        if self.mime_extra is not None and rutas:
            self.mime_extra(md, rutas)
        return md

    def keyPressEvent(self, e):
        from PySide6.QtGui import QKeySequence
        if e.matches(QKeySequence.Copy):       # Ctrl+C: lo elegido (y Ctrl+V en la línea de tiempo lo pega)
            its = self.selectedItems() or ([self.currentItem()] if self.currentItem() is not None else [])
            if its:
                QApplication.clipboard().setMimeData(self.mimeData(its))
            e.accept()
            return
        super().keyPressEvent(e)

    def event(self, e):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeySequence
        if e.type() == QEvent.ShortcutOverride and e.matches(QKeySequence.Copy):
            e.accept()                         # (aquí Ctrl+C copia lo elegido, no los clips de la línea de tiempo)
            return True
        return super().event(e)


class DescargasGenerales(InternetMixin, QWidget):
    def __init__(self, ctrl, timeline=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.timeline = timeline
        self.mencion = None               # (sin palabra clave: lo bajado va a la carpeta general)
        self.termino = ""
        self.raiz = carpeta_guardada()
        self.descargas = []
        self._items: dict[str, QListWidgetItem] = {}
        self._tok = 0
        self._job_mini = None
        if HAY_INTERNET:
            self._iniciar_estado()
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(4)
        self.btn_carpeta = _BotonCarpeta()
        self.btn_carpeta.clicked.connect(self._cambiar_carpeta)
        from . import diseno as D                  # (🎨 20/11: iconos monocromos y el sistema de diseño)
        # (22/11, el usuario: «Descargas está un poco revoltoso»; sin quitar ni esconder nada) UNA jerarquía:
        #   arriba buscar (una fila) y sus filtros · debajo UNA fila de pestañas «Resultados · En cola · Carpeta», cada
        #   una con su cuenta · abajo, en cada pestaña, las acciones de lo elegido (la principal primero).
        #   Antes había dos filas de pestañas (Buscar | Descargado y, dentro, Resultados | Descargas) y el contador
        #   «Descargas en cola (n)» repetía la pestaña «Descargas»: ahora la cuenta va en la pestaña.
        self.btn_descargas_barra = QPushButton("Descargas en cola")      # (la misma cuenta, para quien la pida)
        self.btn_descargas_barra.setIcon(D.icono("download"))
        self.btn_descargas_barra.clicked.connect(self.ver_descargas)
        self.btn_descargas_barra.setVisible(False)
        from .inspector_secciones import PestanasAjustadas
        if HAY_INTERNET:
            net = self._construir_pestana_net()
            # (las pestañas de internet salen de la caja de los videos —en los modos de imagen siguen a la vista— y las
            #  imágenes se buscan en «Resultados», como los videos)
            self._lay_video.removeWidget(self.pestanas_net)
            self._lay_net.addWidget(self.pestanas_net, 1)
            self._lay_net.setStretchFactor(self._caja_video, 0)
            self._lay_net.removeWidget(self._caja_img)
            self._lay_res.insertWidget(1, self._caja_img, 1)
            self.pestanas = self.pestanas_net
            self.pestanas.setTabText(1, "En cola")
            self.pestanas.setTabToolTip(0, "Lo que encuentras: videos o imágenes (según «Videos · PNG recortado · "
                                           "Imágenes»)")
            self.pestanas.setTabToolTip(1, "Descargas en cola: lo que se está bajando o espera, y lo bajado en esta "
                                           "sesión")
            v.addWidget(net, 1)
            self.campo.setPlaceholderText("Buscar videos…")
            i = self.combo_tipo.findData("any")
            if i >= 0:
                self.combo_tipo.setCurrentIndex(i)
        else:
            self.pestanas = PestanasAjustadas()
            self.pestanas.setDocumentMode(True)
            v.addWidget(self.pestanas, 1)
        desc = QWidget()
        dl = QVBoxLayout(desc)
        dl.setContentsMargins(0, 4, 0, 0)
        fila_car = QHBoxLayout()                   # (la carpeta y lo que se hace con ELLA, encima de lo que hay en ella)
        fila_car.setSpacing(D.px(D.M1))
        fila_car.addWidget(self.btn_carpeta, 1)
        dl.addLayout(fila_car)
        self.lista = _ListaArchivos()
        self.lista.setToolTip("Lo que has bajado · arrástralo a la línea de tiempo · doble clic = en el cabezal · "
                              "clic derecho = mover, agregar a memes…")
        self.lista.itemDoubleClicked.connect(lambda it: self.poner_en_cabezal([it.data(Qt.UserRole)]))
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_descargado)
        dl.addWidget(self.lista, 1)
        # (sin nada bajado: una línea, no una rejilla vacía enorme; la explicación, en el tooltip)
        self.vacio_d = QLabel("Aún no has bajado nada")
        self.vacio_d.setObjectName("dim")
        self.vacio_d.setToolTip("Busca arriba (o pega un enlace) y lo que bajes saldrá aquí, con su "
                                "miniatura y su duración, listo para arrastrarlo a la línea de tiempo")
        self.vacio_d.setVisible(False)
        dl.addWidget(self.vacio_d)
        from .miniaturas import activar_scrub      # 🖼 al pasar el ratón: los fotogramas en la misma casilla
        activar_scrub(self.lista, lambda it: it.data(Qt.UserRole))
        # (las acciones de siempre, a la vista: poner en el cabezal, a Medios y quitar —lo elegido, abajo—; abrir la
        #  carpeta y releerla, junto a la carpeta. El clic derecho las repite)
        fb = QHBoxLayout()
        fb.setSpacing(D.px(D.M1))
        self.btn_cabezal_d = D.BotonPrincipal("Poner en el cabezal", "arrow-down-to-line")
        self.btn_cabezal_d.setToolTip("Pone lo elegido donde está el cabezal (y en Medios, «Descargas»). Ctrl+Z "
                                      "lo quita. También: doble clic o arrastrarlo a la línea de tiempo")
        self.btn_cabezal_d.clicked.connect(lambda: self.poner_en_cabezal(self.elegidos()))
        self.btn_medios = QPushButton("A Medios")
        self.btn_medios.setIcon(D.icono("plus"))
        D.medida(self.btn_medios, lambda w: w.setMinimumHeight(D.px(D.ALTO_CAMPO)))
        self.btn_medios.setToolTip("Añade lo elegido a Medios («Descargas»)")
        self.btn_medios.clicked.connect(lambda: a_medios(self.ctrl, self.elegidos()))
        self.btn_abrir_d = D.BotonIcono("folder-open", "Abrir carpeta: abre en el Explorador la carpeta de lo "
                                                       "descargado")
        self.btn_abrir_d.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.raiz)))
        self.btn_quitar_d = D.BotonIcono("trash-2", "Quitar…: manda lo elegido a la Papelera de Windows (se puede "
                                                    "recuperar). Pregunta antes.")
        self.btn_quitar_d.clicked.connect(lambda: self.elegidos() and self.quitar(self.elegidos()))
        self.btn_releer = D.BotonIcono("refresh-cw", "Volver a leer la carpeta")
        self.btn_releer.clicked.connect(self.refrescar)
        fb.addWidget(self.btn_cabezal_d, 1)
        fb.addWidget(self.btn_medios)
        fb.addWidget(self.btn_quitar_d)
        fila_car.addWidget(self.btn_abrir_d)
        fila_car.addWidget(self.btn_releer)
        dl.addLayout(fb)
        dl.addStretch(0)                 # (sin nada bajado, el alto libre al final: ningún botón se estira)
        self.pestanas.addTab(desc, D.icono("folder-open"), "Carpeta")
        self.pestanas.setTabToolTip(self.pestanas.count() - 1, "Descargado: lo que hay en tu carpeta general de "
                                                               "descargas")
        self.pestanas.iconos_si_no_cabe(["search", "download", "folder-open"] if HAY_INTERNET else ["folder-open"])
        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.aviso.setObjectName("dim")
        self.aviso.setVisible(False)              # (sin aviso, sin línea vacía)
        v.addWidget(self.aviso)
        self._pintar_carpeta()
        self._textos_sin_palabra()
        self.act_contador_descargas()
        if HAY_INTERNET:                           # (arrastrar y Ctrl+C / Ctrl+V a la línea de tiempo, con su sonido)
            self._activar_arrastre_y_pegar()
            self.lista.mime_extra = self._mime_archivos
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(400)
        self._t.timeout.connect(self.refrescar)
        QTimer.singleShot(0, self.refrescar)

    # ---- lo que la parte de internet (clips_internet) pide al panel
    def _aviso(self, texto: str):
        self.aviso.setText(texto)
        self.aviso.setVisible(bool(texto))

    def _carpeta_de(self, _term):
        return None

    def _carpeta_para_bajar(self, _term: str) -> str | None:
        try:
            os.makedirs(self.raiz, exist_ok=True)
        except OSError:
            return None
        return self.raiz

    def asegurar_raiz(self) -> bool:
        """La carpeta general: si no se eligió, la de siempre (se recuerda en silencio)."""
        if not str(_ajustes().value(CLAVE, "") or "").strip():
            _ajustes().setValue(CLAVE, self.raiz)
        try:
            os.makedirs(self.raiz, exist_ok=True)
        except OSError as exc:
            self._aviso(f"No pude crear la carpeta de descargas: {exc}")
            return False
        return True

    def _programar(self, *_):
        self._t.start()

    def _cabezal(self) -> float:
        eng = getattr(self.window(), "engine", None)
        if eng is not None:
            return float(getattr(eng, "time", 0.0) or 0.0)
        return float(getattr(self.timeline, "playhead", 0.0) or 0.0)

    def _hits_cabezal(self) -> list[dict]:
        return [{"tl": self._cabezal(), "cabezal": True}]

    def _hits_marcados(self) -> list[dict]:
        return self._hits_cabezal()

    def _poner_elegido(self, hits=None):
        if HAY_INTERNET:
            self._poner_elegido_net(hits or self._hits_cabezal())

    def _colocar(self, media_id: str, hits: list[dict], avisar: bool = True) -> bool:
        from ..core import keyword_place as KP
        ok, texto = KP.colocar(self.ctrl, media_id, hits, avisar)
        if texto:
            self._aviso(texto)
        return ok

    def _clic_derecho(self, lista, pos):
        it = lista.itemAt(pos)
        if it is None or not HAY_INTERNET:
            return
        lista.setCurrentItem(it)
        menu = self._menu_para(lista, it)
        if menu is None:
            return
        d = self._descarga_de_item(it) if lista is getattr(self, "lista_descargas", None) else None
        if d is not None and d.estado == "listo" and d.ruta and os.path.isfile(d.ruta):
            menu.addSeparator()
            menu_mover(menu, self.ctrl, lambda r=d.ruta: [r], self, self.refrescar)
            menu.addAction("Agregar a memes…", lambda r=d.ruta: self._a_memes([r]))
        from . import help as AYUDA
        AYUDA.exec_menu(menu, lista.viewport().mapToGlobal(pos))

    def _textos_sin_palabra(self):
        """Aquí no hay palabra clave: fuera lo que solo sirve con ella y ayudas que hablen de lo que hace AQUÍ."""
        if not HAY_INTERNET:
            return
        for nombre in ("btn_poner", "btn_poner_desc", "lbl_mods"):
            w = getattr(self, nombre, None)
            if w is not None:
                w.setVisible(False)
                w.setEnabled(False)
        for c in getattr(self, "chips", []) or []:
            c.setVisible(False)
        donde = "a tu carpeta general de descargas (y a Medios, «🌐 Descargas»)"
        from .clips_internet import MODOS_BUSQUEDA
        for clave, _texto, tip in MODOS_BUSQUEDA:
            b = self.btns_modo.get(clave)
            if b is not None:
                b.setToolTip(f"{tip}. Lo que bajes va {donde}.")
        if getattr(self, "btn_bajar", None) is not None:
            self.btn_bajar.setToolTip(f"Baja el resultado elegido {donde}.")
        if getattr(self, "campo_img", None) is not None:
            self.campo_img.setToolTip("Lo que quieres buscar · Enter o «Buscar»")
        if getattr(self, "estado_img", None) is not None:
            self.estado_img.setToolTip("Clic derecho en una imagen → «Bajar a la carpeta». Se baja la imagen grande (de "
                                       "su página); en «PNG recortado», si tiene un fondo liso se le quita. Va " + donde
                                       + ".")

    def buscar_imagenes(self, texto: str | None = None):
        url = super().buscar_imagenes(texto)
        carpeta = os.path.basename(self.raiz.rstrip("\\/")) or self.raiz
        if getattr(self, "_vista_img", None) is not None:
            self._vista_img.texto_usar = f"⬇ Bajar a «{carpeta}»"
        self.campo_img.setToolTip(f"Clic derecho en una imagen de abajo → «Bajar a «{carpeta}»» (tu carpeta general "
                                  "de descargas)")
        return url

    def act_contador_descargas(self):
        """«Descargas en cola (n)» (como en Palabras clave → Buscar material; lo eligió el usuario). Si no cabe en el
        ancho del botón, «En cola (n)»; el tooltip lo dice entero."""
        ds = list(self.descargas or [])
        curso = sum(1 for d in ds if getattr(d, "estado", "") == "bajando")
        listas = sum(1 for d in ds if getattr(d, "estado", "") == "listo")
        fallos = sum(1 for d in ds if getattr(d, "estado", "") == "error")
        b = self.btn_descargas_barra
        largo = f"Descargas en cola ({curso})" if curso else "Descargas en cola"
        corto = f"En cola ({curso})" if curso else "En cola"
        ancho = b.width() if b.isVisible() else 0
        cabe = ancho <= 0 or b.fontMetrics().horizontalAdvance(largo) + 24 <= ancho
        b.setText(largo if cabe else corto)
        b.setStyleSheet("QPushButton { color: #f2a03d; font-weight: bold; }" if curso else "")
        b.setToolTip(f"Descargas en cola · bajando o en cola: {curso} · bajadas en esta sesión: {listas}"
                     + (f" · con error: {fallos}" if fallos else "") + "\nClic = ver la lista de descargas")
        if HAY_INTERNET:                           # (la misma cuenta, en su pestaña: «En cola (n)»)
            self.pestanas.poner_nombre(1, f"En cola ({curso})" if curso else "En cola")
            self.pestanas.tabBar().setTabTextColor(1, QColor("#f2a03d") if curso else QColor())

    def pegar_portapapeles(self, md, segundo: float) -> bool:
        """(MainWindow, Ctrl+V en la línea de tiempo) ¿Lo copiado es de este panel? Entonces lo pone en ese segundo."""
        f = getattr(self, "_pegar_internet", None)
        return bool(f is not None and f(md, segundo))

    def poner_modo_busqueda(self, modo: str):
        super().poner_modo_busqueda(modo)
        if HAY_INTERNET and modo != "video":       # (las imágenes se ven en «Resultados»)
            self.pestanas.setCurrentIndex(0)

    def _pintar_resultados(self):
        super()._pintar_resultados()
        por = getattr(self, "resultados_por", None) or {}       # (por fuentes: todos; si no, los de la lista)
        n = sum(len(v) for v in por.values()) or self.lista_resultados.count()
        self.pestanas.poner_nombre(0, f"Resultados ({n})" if n else "Resultados")

    def ver_descargas(self):
        if HAY_INTERNET:
            self.pestanas.setCurrentIndex(0)
            self.poner_modo_busqueda("video")
            self.pestanas_net.setCurrentIndex(1)

    def _bajada_lista(self, d, ruta: str):
        super()._bajada_lista(d, ruta)
        if getattr(d, "media_id", None) and d.media_id in self.ctrl.project.media:
            self.ctrl.set_media_props([d.media_id], category=CATEGORIA)

    # ---- carpeta general
    def _pintar_carpeta(self):
        nombre = os.path.basename(self.raiz.rstrip("\\/")) or self.raiz
        self.btn_carpeta.poner("Carpeta: " + nombre)
        self.btn_carpeta.setToolTip(f"Lo que bajas aquí se guarda en:\n{self.raiz}\nClic = cambiarla (se recuerda)")

    def _pedir_carpeta(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Carpeta general de descargas · se recuerda",
                                                self.raiz if os.path.isdir(self.raiz) else os.path.expanduser("~"))

    def _cambiar_carpeta(self):
        d = self._pedir_carpeta()
        if d:
            _ajustes().setValue(CLAVE, d)
            self.raiz = d
            self._pintar_carpeta()
            self.refrescar()

    # ---- lo descargado
    def elegidos(self) -> list[str]:
        its = sorted(self.lista.selectedItems(), key=lambda it: self.lista.row(it))
        return [it.data(Qt.UserRole) for it in its if it.data(Qt.UserRole)]

    def refrescar(self):
        """Relee la carpeta general (no toca Medios: la categoría que les pusiste se respeta)."""
        from .descargas_panel import archivos_de
        self._tok += 1
        self.lista.clear()
        self._items = {}
        rutas = archivos_de(self.raiz, False, hondo=2) if os.path.isdir(self.raiz) else []
        for r in rutas[:400]:
            it = QListWidgetItem(os.path.basename(r))
            it.setData(Qt.UserRole, r)
            it.setToolTip(r)
            self.lista.addItem(it)
            self._items[r] = it
        from .miniaturas import ajustar_rejilla
        ajustar_rejilla(self.lista, MINI.width() + 20, MINI.height())        # (ningún nombre cortado)
        self.lista.setVisible(bool(rutas))
        n_tab = self.pestanas.count() - 1          # (la cuenta, en su pestaña: «Carpeta (n)»)
        self.pestanas.poner_nombre(n_tab, f"Carpeta ({len(rutas)})" if rutas else "Carpeta")
        self.vacio_d.setVisible(not rutas)
        for b_ in (self.btn_cabezal_d, self.btn_medios, self.btn_quitar_d):
            b_.setEnabled(bool(rutas))
        if rutas:
            self._miniaturas(rutas[:400], self._tok)
        self.lista.setToolTip(f"{len(rutas)} archivo(s) en {self.raiz} · arrástralo a la línea de tiempo · doble clic "
                              "= en el cabezal · clic derecho = mover, agregar a memes…")

    def _miniaturas(self, rutas: list[str], tok: int):
        from .clips_panel import _hacer_miniatura, _miniatura_ruta
        from .descargas_panel import duracion_de
        from .jobs import BackgroundJob
        if self._job_mini is not None:
            self._job_mini.cancel()

        def trabajo(_p, cancelado, emitir):
            for r in rutas:
                if cancelado():
                    return None
                k = kind_for_path(r)
                png = ""
                if k != KIND_AUDIO:
                    png = _miniatura_ruta(r)
                    if not os.path.isfile(png) and not _hacer_miniatura(r, png):
                        png = ""
                emitir((r, png, 0.0 if k == KIND_IMAGE else duracion_de(r)))
            return None
        job = BackgroundJob(trabajo, self, with_partial=True)
        job.silencioso = True       # (las miniaturas de la lista no son un trabajo de la IA: sin indicador «Trabajando…»)
        job.partial.connect(lambda par, t=tok: self._llego(par, t))
        self._job_mini = job
        job.start()

    def _llego(self, par, tok: int):
        if tok != self._tok:
            return
        r, png, dur = par
        it = self._items.get(r)
        if it is None:
            return
        from .descargas_panel import con_duracion, hueco
        pm = QPixmap(png) if png else QPixmap()
        if pm.isNull():                        # (22/11: su icono sobre gris, no un cuadro negro)
            from ..core.model import kind_for_path
            pm = hueco(kind_for_path(r)).scaled(MINI, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        try:
            it.setIcon(con_duracion(pm, dur))
        except RuntimeError:
            pass

    def poner_en_cabezal(self, rutas: list[str]) -> list[str]:
        ids = a_medios(self.ctrl, [r for r in rutas if r])
        if not ids:
            self._aviso("Elige antes algo de lo descargado.")
            return []
        hechos = self.ctrl.add_media(ids, None, self._cabezal())
        self._aviso(f"✓ {len(ids)} en el cabezal (Ctrl+Z lo quita).")
        return hechos or []

    def _a_memes(self, rutas: list[str]):
        from . import memes_panel
        ids = a_medios(self.ctrl, rutas)
        if ids:
            memes_panel.agregar_medios(self, self.ctrl, ids)

    def quitar(self, rutas: list[str], preguntar: bool = True) -> int:
        if not rutas:
            return 0
        n_usos = usos(self.ctrl, rutas)
        if preguntar:
            extra = (f"\n⚠ {n_usos} se usa(n) en este proyecto: sus clips saldrán como «no encontrado»."
                     if n_usos else "")
            if QMessageBox.question(self, "Quitar lo descargado", f"¿Mandar {len(rutas)} archivo(s) a la Papelera de "
                                    f"Windows? (se pueden recuperar){extra}", QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) != QMessageBox.Yes:
                return 0
        hechos, fallos = a_la_papelera(self.ctrl, rutas, _a_papelera)
        for r in hechos:
            cred = os.path.splitext(r)[0] + ".creditos.json"
            if os.path.isfile(cred):
                _a_papelera(cred)
        texto = f"🗑 {len(hechos)} archivo(s) a la Papelera."
        if fallos:
            texto += f" No se pudo quitar «{os.path.basename(fallos[0][0])}»: {fallos[0][1]}."
        self._aviso(texto)
        self.refrescar()
        return len(hechos)

    def _menu_descargado(self, pos):
        it = self.lista.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.lista.setCurrentItem(it)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.addAction("Poner en el cabezal", lambda: self.poner_en_cabezal(self.elegidos()))
        menu.addAction("A Medios", lambda: a_medios(self.ctrl, self.elegidos()))
        menu_mover(menu, self.ctrl, self.elegidos, self, self.refrescar)
        menu.addAction("Agregar a memes…", lambda: self._a_memes(self.elegidos()))
        menu.addSeparator()
        r = it.data(Qt.UserRole)
        menu.addAction("Mostrar en el Explorador", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(r))))
        menu.addAction("Quitar (a la Papelera)…", lambda: self.quitar(self.elegidos()))
        from . import help as AYUDA
        AYUDA.exec_menu(menu, self.lista.viewport().mapToGlobal(pos))
