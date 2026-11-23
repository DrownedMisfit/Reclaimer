"""
😂 Panel «Memes»: tu biblioteca de memes, la MISMA en todos tus proyectos (ver core/memes.py).

  arriba:  buscador (nombre o etiqueta) · tipo (videos / imágenes / sonidos) · con o sin audio · «Añadir archivos…»
  medio:   rejilla de miniaturas con la duración pequeña; arrastrar a la línea de tiempo; doble clic = en el cabezal;
           al pasar el ratón por un video, sus fotogramas en la misma casilla (ui/miniaturas.py); los datos, en el
           tooltip; «Ver» lo reproduce aquí mismo (sin sonido en pruebas)
  abajo:   Poner en el cabezal · Renombrar · Etiquetas · Quitar (a la Papelera, preguntando) · Abrir carpeta

Para la ventana y otros paneles:
  agregar_clip(parent, ctrl, clip_id)      clic derecho en un clip → «Agregar a memes…»: guarda SOLO su tramo
  agregar_medios(parent, ctrl, media_ids)  clic derecho en Medios → «Agregar a memes»: el archivo entero
  importar(ctrl, ruta)                     un meme a Medios (categoría «😂 Memes»; sin copiar el archivo)
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..core import memes as MEMES
from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO

MINI = QSize(144, 81)
TIPOS = [("Todo", None), ("Videos", KIND_VIDEO), ("Imágenes", KIND_IMAGE), ("Sonidos", KIND_AUDIO)]
AUDIOS = [("Con y sin audio", None), ("Con audio", True), ("Sin audio", False)]


class _AvisoMemes(QObject):
    """La biblioteca cambió (puede ser desde un trabajo en segundo plano): la señal llega a la ventana en su hilo."""
    cambio = Signal()


_AVISO = None


def senal_memes() -> "_AvisoMemes":
    """La señal «la biblioteca de memes cambió» (conéctala a un método de un objeto de la ventana)."""
    global _AVISO
    if _AVISO is None:
        _AVISO = _AvisoMemes()
        MEMES.al_cambiar(_AVISO.cambio.emit)
    return _AVISO


def _a_papelera(ruta: str) -> bool:
    """A la Papelera de Windows (aparte para que las pruebas la sustituyan)."""
    from .library import _to_trash
    return bool(_to_trash(ruta))


def _mmss(t: float) -> str:
    from ..core.keyword_place import mmss
    return mmss(t)


def _aviso(parent, texto: str):
    win = parent.window() if parent is not None else None
    if win is not None and hasattr(win, "statusBar"):
        win.statusBar().showMessage(texto, 8000)


# ------------------------------------------------------------------------------------------------ diálogo
class AgregarMemeDialog(QDialog):
    """Nombre, etiquetas y ☐ con audio (si lo tiene)."""

    def __init__(self, nombre: str, con_audio: bool, puede_audio: bool, parent=None, titulo="Agregar a memes"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        f = QFormLayout(self)
        self.nombre = QLineEdit(nombre)
        self.nombre.setToolTip("Cómo se llamará en tu biblioteca de memes")
        self.etiquetas = QLineEdit()
        self.etiquetas.setPlaceholderText("risa, fallo, sorpresa…")
        self.etiquetas.setToolTip("Palabras para encontrarlo luego, separadas por comas")
        self.audio = QCheckBox("Con audio")
        self.audio.setChecked(bool(con_audio and puede_audio))
        self.audio.setEnabled(puede_audio)
        self.audio.setToolTip("Guardarlo con su sonido (desmárcalo para solo la imagen)" if puede_audio else
                              "Este archivo no tiene sonido")
        f.addRow("Nombre", self.nombre)
        f.addRow("Etiquetas", self.etiquetas)
        f.addRow(self.audio)
        bb = QDialogButtonBox()
        bb.addButton("Guardar", QDialogButtonBox.AcceptRole)
        bb.addButton("Cancelar", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def valores(self) -> dict:
        return {"nombre": self.nombre.text().strip(), "etiquetas": self.etiquetas.text(),
                "audio": self.audio.isChecked()}


def _pedir(parent, nombre: str, con_audio: bool, puede_audio: bool, titulo: str, luego) -> None:
    """🧰 Nombre, etiquetas y audio en el panel de herramientas (sin bloquear): al aceptar, luego(valores)."""
    from .herramientas import abrir_dialogo
    caja = {}

    def fabrica():
        caja["dlg"] = AgregarMemeDialog(nombre, con_audio, puede_audio, parent, titulo)
        return caja["dlg"]

    def al_terminar(r):
        if r == QDialog.Accepted and caja.get("dlg") is not None:
            luego(caja["dlg"].valores())
    abrir_dialogo(parent, "memes_agregar", fabrica, titulo, "Memes", "star", al_terminar=al_terminar)


def _en_segundo_plano(parent, fn, texto_ok: str):
    """fn(cancelado) en segundo plano (cancelado() = ¿se pidió parar? Lo de FFmpeg se corta y no deja nada a medias)."""
    from .jobs import BackgroundJob
    job = BackgroundJob(lambda _p, cancelado: fn(cancelado), parent)
    job.title = "😂 Guardando en memes"
    job.done.connect(lambda m: _aviso(parent, texto_ok.format(nombre=(m or {}).get("nombre", ""))))
    job.failed.connect(lambda msg: _aviso(parent, f"No se pudo guardar en memes: {msg[:160]}"))
    job.start()
    return job


def agregar_clip(parent, ctrl, clip_id: str, preguntar: bool = True, **valores):
    """Clic derecho en un clip → «Agregar a memes…»: SOLO su tramo, como se ve en la línea de tiempo (dónde empieza y
    cuánto dura en el archivo, a su velocidad y, si va al revés, al revés). Congelado (velocidad 0) = su fotograma
    como imagen. La parte de AUDIO de un video (un clip en una pista de audio) guarda solo su sonido. En segundo
    plano; devuelve el trabajo (None si se cancela o no se puede)."""
    from ..core.model import TRACK_AUDIO
    p = ctrl.project
    c = p.clips.get(clip_id)
    m = p.media_of(c) if c is not None else None
    if c is None or m is None or c.text is not None:
        _aviso(parent, "Elige un clip de video, imagen o sonido.")
        return None
    tr = p.track(c.track_id)
    solo_audio = m.kind == KIND_VIDEO and tr is not None and tr.kind == TRACK_AUDIO
    velocidad = float(getattr(c, "speed", 1.0) or 0.0)
    reversa = bool(getattr(c, "reverse", False))
    puede_audio = m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and bool(m.has_audio))
    congelado = velocidad <= 0 and m.kind == KIND_VIDEO and not solo_audio
    if preguntar:                                    # (se pregunta en el panel; al aceptar, sigue sin preguntar)
        _pedir(parent, m.name.rsplit(".", 1)[0][:60], True, puede_audio and not congelado, "Agregar el clip a memes",
               lambda v: agregar_clip(parent, ctrl, clip_id, preguntar=False, **v) if v else None)
        return None
    if velocidad <= 0 and not congelado:
        velocidad = 1.0                              # (un sonido «congelado» no existe: a su velocidad normal)
    desde = float(c.source_in)
    dur = float(c.src_len) if velocidad > 0 else 0.0
    audio = (bool(valores.get("audio", True)) and puede_audio) or solo_audio
    origen = f"{m.path} ({_mmss(desde)}–{_mmss(desde + dur)})"
    return _en_segundo_plano(parent, lambda cancelado: MEMES.agregar_tramo(
        m.path, desde, dur, valores.get("nombre", ""), valores.get("etiquetas"), audio, origen,
        velocidad=velocidad, reversa=reversa, solo_audio=solo_audio, cancelado=cancelado),
        "😂 «{nombre}» guardado en tus memes.")


def agregar_medios(parent, ctrl, media_ids: list[str], preguntar: bool = True, **valores):
    """Clic derecho en Medios → «Agregar a memes»: el archivo entero (uno o varios)."""
    p = ctrl.project
    ms = [p.media[i] for i in media_ids if i in p.media and os.path.isfile(p.media[i].path)
          and not MEMES.es_meme(p.media[i].path)]
    if not ms:
        _aviso(parent, "Eso ya está en tus memes (o no se encuentra el archivo).")
        return None
    puede_audio = any(m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio) for m in ms)
    if preguntar:                                    # (se pregunta en el panel; al aceptar, sigue sin preguntar)
        _pedir(parent, ms[0].name.rsplit(".", 1)[0][:60] if len(ms) == 1 else "", True, puede_audio,
               "Agregar a memes", lambda v: agregar_medios(parent, ctrl, media_ids, preguntar=False, **v) if v else None)
        return None

    def todo(cancelado):
        hechos = []
        for m in ms:
            if cancelado():
                break
            nombre = valores.get("nombre") if len(ms) == 1 and valores.get("nombre") else m.name.rsplit(".", 1)[0]
            hechos.append(MEMES.agregar_archivo(m.path, nombre, valores.get("etiquetas"),
                                                bool(valores.get("audio", True)), m.path, cancelado))
        return hechos[-1] if hechos else {}
    return _en_segundo_plano(parent, todo, f"😂 {len(ms)} archivo(s) guardado(s) en tus memes." if len(ms) > 1 else
                             "😂 «{nombre}» guardado en tus memes.")


def importar(ctrl, ruta: str) -> list[str]:
    """El meme a Medios (en «😂 Memes»), sin copiar el archivo."""
    try:
        ids = [i for i in ctrl.import_now([ruta]) if i in ctrl.project.media]
    except Exception:  # noqa: BLE001
        return []
    nuevos = [i for i in ids if ctrl.project.media[i].category != MEMES.CATEGORIA]
    if nuevos:
        ctrl.set_media_props(nuevos, category=MEMES.CATEGORIA)
    return ids


# ------------------------------------------------------------------------------------------------ panel
class _Rejilla(QListWidget):
    """Sus memes salen arrastrando como archivos (la línea de tiempo y Medios los aceptan)."""

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
        self.setMouseTracking(True)

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)["ruta"]) for it in items if it.data(Qt.UserRole)])
        return md


class MemesPanel(QWidget):
    def __init__(self, ctrl, win=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.win = win
        self._items: dict[str, QListWidgetItem] = {}
        self._tok = 0
        self._job = None
        self._reproductor = None
        # (🎨 20/11: con el sistema de diseño —ui/diseno.py—: campos de 24 px, iconos monocromos, UN botón principal
        #  «Poner en el cabezal» y el resto de acciones siempre a la vista como iconos con su tooltip; sin memes o sin
        #  resultados, una línea —nada de una rejilla vacía enorme—)
        from . import diseno as D
        v = QVBoxLayout(self)
        v.setContentsMargins(D.px(D.M2), D.px(D.M2), D.px(D.M2), D.px(D.M2))
        v.setSpacing(D.px(D.M1) + 2)
        f1 = QHBoxLayout()
        self.buscador = QLineEdit()
        self.buscador.setClearButtonEnabled(True)
        self.buscador.setPlaceholderText("Buscar memes…")
        self.buscador.setToolTip("Por su nombre o sus etiquetas")
        self.buscador.textChanged.connect(lambda _t: self.refrescar())
        f1.addWidget(self.buscador, 1)
        v.addLayout(f1)
        f2 = QHBoxLayout()
        self.filtro_tipo = QComboBox()
        for t, d in TIPOS:
            self.filtro_tipo.addItem(t, d)
        self.filtro_tipo.setToolTip("Qué memes ver")
        self.filtro_audio = QComboBox()
        for t, d in AUDIOS:
            self.filtro_audio.addItem(t, d)
        self.filtro_audio.setToolTip("Con o sin su sonido")
        for c in (self.filtro_tipo, self.filtro_audio):
            c.currentIndexChanged.connect(lambda _i: self.refrescar())
        for w_ in (self.buscador, self.filtro_tipo, self.filtro_audio):
            D.alto_fijo(w_)
        self.btn_anadir = QPushButton("Añadir archivos…")
        self.btn_anadir.setIcon(D.icono("plus"))
        self.btn_anadir.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)   # (nunca se estira a lo alto)
        D.medida(self.btn_anadir, lambda w: w.setMinimumHeight(D.px(D.ALTO_CAMPO)))
        self.btn_anadir.setToolTip("Copia videos, imágenes o sonidos de tu PC a tu biblioteca de memes")
        self.btn_anadir.clicked.connect(self._anadir_archivos)
        f2.addWidget(self.filtro_tipo)
        f2.addWidget(self.filtro_audio)
        f2.addWidget(self.btn_anadir)
        f2.addStretch(1)
        v.addLayout(f2)
        # («N de M memes» o «Sin memes» justo debajo de «Añadir archivos…»: sin memes, la línea y la barra de acciones
        #  seguidas, sin hueco —la rejilla vacía se esconde—)
        self.estado = QLabel("")
        self.estado.setObjectName("dim")
        self.estado.setWordWrap(True)
        v.addWidget(self.estado)
        self.rejilla = _Rejilla()
        self.rejilla.setToolTip("Arrastra un meme a la línea de tiempo · doble clic = en el cabezal · clic derecho = "
                                "más opciones")
        self.rejilla.itemDoubleClicked.connect(lambda it: self.poner_en_cabezal([it.data(Qt.UserRole)]))
        self.rejilla.itemSelectionChanged.connect(self.parar)
        self.rejilla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.rejilla.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.rejilla, 1)
        # (23/11: sin vista grande flotante ni imagen grande debajo: al pasar el ratón por un video, sus fotogramas en
        #  la misma casilla —ui/miniaturas.py—; nombre, duración, audio y ruta, en el tooltip de la casilla)
        from .miniaturas import activar_scrub
        activar_scrub(self.rejilla, lambda it: (it.data(Qt.UserRole) or {}).get("ruta"))
        self.caja_video = QVBoxLayout()           # (el «Ver»: el reproductor aparece aquí al pulsarlo)
        v.addLayout(self.caja_video)
        f3 = QHBoxLayout()                       # (estrecho: responsive baja los iconos a la línea siguiente)
        f3.setSpacing(D.px(D.M1))
        self.btn_cabezal = D.BotonPrincipal("Poner en el cabezal", "arrow-down-to-line")
        self.btn_cabezal.setToolTip("Pone los memes elegidos donde está el cabezal (Ctrl+Z lo "
                                    "quita). También: doble clic en un meme o arrastrarlo a la línea de tiempo")
        self.btn_cabezal.clicked.connect(lambda: self.poner_en_cabezal(self.elegidos()))
        self.btn_ver = D.BotonIcono("play", "Ver: reproduce el meme elegido aquí mismo")
        self.btn_ver.clicked.connect(self._ver)
        self.btn_renombrar = D.BotonIcono("square-pen", "Renombrar…: cambia el nombre con el que sale en tu "
                                                        "biblioteca (el archivo no se toca)")
        self.btn_renombrar.clicked.connect(lambda: self.renombrar())
        self.btn_etiquetas = D.BotonIcono("tag", "Etiquetas…: palabras para encontrarlo luego")
        self.btn_etiquetas.clicked.connect(lambda: self.etiquetar())
        self.btn_quitar = D.BotonIcono("trash-2", "Quitar…: lo saca de tus memes y manda su archivo a la Papelera de "
                                                  "Windows (se puede recuperar). Pregunta antes.")
        self.btn_quitar.clicked.connect(lambda: self.quitar())
        self.btn_carpeta = D.BotonIcono("folder-open", "Abrir carpeta: abre en el Explorador la carpeta de tus memes")
        self.btn_carpeta.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(MEMES.carpeta())))
        f3.addWidget(self.btn_cabezal, 1)
        for b in (self.btn_ver, self.btn_renombrar, self.btn_etiquetas, self.btn_quitar, self.btn_carpeta):
            f3.addWidget(b)
        v.addLayout(f3)
        v.addStretch(0)                  # (sin memes, el alto libre va aquí, al final: ningún botón se estira)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(150)
        self._t.timeout.connect(self.refrescar)
        senal_memes().cambio.connect(self._t.start)
        self.refrescar()

    # ---- lista
    def elegidos(self) -> list[dict]:
        its = sorted(self.rejilla.selectedItems(), key=lambda it: self.rejilla.row(it))
        return [it.data(Qt.UserRole) for it in its if it.data(Qt.UserRole)]

    def refrescar(self):
        sel = {m["id"] for m in self.elegidos()}
        self._tok += 1
        self.rejilla.clear()
        self._items = {}
        lista = MEMES.buscar(self.buscador.text(), self.filtro_tipo.currentData(), self.filtro_audio.currentData())
        pend = []
        for m in lista:
            it = QListWidgetItem(m.get("nombre") or os.path.basename(m["ruta"]))
            it.setData(Qt.UserRole, m)
            tags = ", ".join(m.get("etiquetas") or [])
            dur = float(m.get("duracion") or 0)
            it.setToolTip(f"{m.get('nombre')}\n" + (f"Duración: {_mmss(dur)}\n" if dur else "")
                          + (f"Etiquetas: {tags}\n" if tags else "")
                          + ("Con audio" if m.get("audio") else "Sin audio") + f" · {m['ruta']}")
            self.rejilla.addItem(it)
            self._items[m["ruta"]] = it
            if m["id"] in sel:
                it.setSelected(True)
            pend.append(m)
        from .miniaturas import ajustar_rejilla
        ajustar_rejilla(self.rejilla, MINI.width() + 20, MINI.height())      # (ningún nombre cortado)
        total = len(MEMES.listar())
        self.rejilla.setVisible(bool(lista))       # (sin nada que enseñar: la línea de estado, no una rejilla vacía)
        self.estado.setText(f"{len(lista)} de {total} memes" if lista else
                            ("Ningún meme con esa búsqueda" if total else "Sin memes"))
        self.estado.setToolTip("" if total else "Para guardar uno: clic derecho en un clip de la línea de tiempo → "
                               "«Agregar a memes…», o «Añadir archivos…» arriba")
        if pend:
            self._miniaturas(pend, self._tok)

    def _miniaturas(self, memes: list[dict], tok: int):
        from .clips_panel import _hacer_miniatura, _miniatura_ruta
        from .jobs import BackgroundJob
        if self._job is not None:
            self._job.cancel()

        def trabajo(_p, cancelado, emitir):
            for m in memes:
                if cancelado():
                    return None
                r = m["ruta"]
                png = _miniatura_ruta(r)
                if m.get("tipo") == KIND_AUDIO:
                    png = ""
                elif not os.path.isfile(png) and not _hacer_miniatura(r, png):
                    png = ""
                emitir((r, png, float(m.get("duracion") or 0)))
            return None

        job = BackgroundJob(trabajo, self, with_partial=True)
        job.partial.connect(lambda par, t=tok: self._llego(par, t))
        self._job = job
        job.start()

    def _llego(self, par, tok: int):
        if tok != self._tok:
            return
        ruta, png, dur = par
        it = self._items.get(ruta)
        if it is None:
            return
        from .descargas_panel import con_duracion
        pm = QPixmap(png) if png else QPixmap()
        if pm.isNull():
            pm = QPixmap(MINI)
            pm.fill(Qt.black)
            if not png:
                from PySide6.QtGui import QPainter
                p = QPainter(pm)
                p.setPen(Qt.gray)
                p.drawText(pm.rect(), Qt.AlignCenter, "♪")
                p.end()
        try:
            it.setIcon(con_duracion(pm, dur))
        except RuntimeError:
            pass

    def parar(self):
        """Para el «Ver» y suelta el archivo (si no, Windows no deja quitarlo ni moverlo)."""
        if self._reproductor is not None:
            try:
                self._reproductor.stop()
                self._reproductor.setSource(QUrl())
            except RuntimeError:
                pass

    def hideEvent(self, e):
        self.parar()
        super().hideEvent(e)

    def _ver(self):
        ms = self.elegidos()
        if not ms or ms[0].get("tipo") == KIND_IMAGE:
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        if self._reproductor is None:
            self._video = QVideoWidget()
            self._video.setMinimumHeight(120)
            self.caja_video.addWidget(self._video)
            self._reproductor = QMediaPlayer(self)
            self._salida = QAudioOutput(self)
            self._reproductor.setAudioOutput(self._salida)
            self._reproductor.setVideoOutput(self._video)
        self._salida.setVolume(0.0 if os.environ.get("EDITORIA_SIN_SONIDO") else 0.8)
        self._reproductor.setSource(QUrl.fromLocalFile(ms[0]["ruta"]))
        self._reproductor.play()

    # ---- acciones
    def _ventana(self):
        return self.win if self.win is not None else self.window()

    def poner_en_cabezal(self, ms: list[dict]) -> list[str]:
        ms = [m for m in ms if m]
        if not ms:
            self.estado.setText("Elige antes un meme.")
            return []
        ids = []
        for m in ms:
            ids += importar(self.ctrl, m["ruta"])
        if not ids:
            return []
        eng = getattr(self._ventana(), "engine", None)
        t = float(getattr(eng, "time", 0.0) or 0.0)
        hechos = self.ctrl.add_media(ids, None, t)
        self.estado.setText(f"✓ {len(ms)} meme(s) en el cabezal (Ctrl+Z lo quita).")
        return hechos or []

    def renombrar(self, nombre: str | None = None) -> bool:
        ms = self.elegidos()
        if not ms:
            return False
        if nombre is None:
            nombre, ok = QInputDialog.getText(self, "Renombrar meme", "Nombre:", text=ms[0].get("nombre", ""))
            if not ok:
                return False
        return MEMES.renombrar(ms[0]["id"], nombre) is not None

    def etiquetar(self, etiquetas: str | None = None) -> bool:
        ms = self.elegidos()
        if not ms:
            return False
        if etiquetas is None:
            etiquetas, ok = QInputDialog.getText(self, "Etiquetas", "Separadas por comas:",
                                                 text=", ".join(ms[0].get("etiquetas") or []))
            if not ok:
                return False
        for m in ms:
            MEMES.etiquetar(m["id"], etiquetas)
        return True

    def quitar(self, preguntar: bool = True) -> int:
        ms = self.elegidos()
        if not ms:
            return 0
        from . import descargas_generales as DG
        rutas = [m["ruta"] for m in ms]
        n_usos = DG.usos(self.ctrl, rutas)
        if preguntar:
            extra = (f"\n⚠ {n_usos} se usa(n) en este proyecto: sus clips saldrán como «no encontrado»."
                     if n_usos else "")
            r = QMessageBox.question(self, "Quitar memes",
                                     f"¿Quitar {len(ms)} meme(s) de tu biblioteca?\nSus archivos irán a la Papelera de "
                                     f"Windows (se pueden recuperar).{extra}", QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
            if r != QMessageBox.Yes:
                return 0
        self.parar()
        from ..core.soltar_archivos import soltando
        hechos, fallos = [], []
        with soltando(rutas):                 # 🔓 (el visor, el motor propio y los análisis los sueltan)
            for m in ms:
                (hechos if MEMES.quitar(m["id"], lambda ruta: bool(DG.a_la_papelera(self.ctrl, [ruta], _a_papelera)[0]))
                 else fallos).append(m)
        DG.marcar_que_faltan(self.ctrl, [m["ruta"] for m in hechos])
        texto = f"🗑 {len(hechos)} meme(s) a la Papelera."
        if fallos:
            texto += (f" No se pudo quitar «{fallos[0].get('nombre', '')}»: está abierto en otro programa (ciérralo y "
                      "vuelve a probar).")
        self.estado.setText(texto)
        return len(hechos)

    def _anadir_archivos(self):
        rutas, _ = QFileDialog.getOpenFileNames(self, "Añadir a memes", "",
                                                "Videos, imágenes y sonidos (*.mp4 *.mov *.mkv *.webm *.avi *.gif "
                                                "*.png *.jpg *.jpeg *.webp *.mp3 *.wav *.m4a *.ogg)")
        return self.anadir_rutas(rutas)

    def anadir_rutas(self, rutas: list[str]):
        """Copia esos archivos a tu biblioteca, en UN solo trabajo (uno tras otro)."""
        rutas = [r for r in rutas if r and os.path.isfile(r)]
        if not rutas:
            return None

        def todo(cancelado):
            hechos = []
            for r in rutas:
                if cancelado():
                    break
                try:
                    hechos.append(MEMES.agregar_archivo(r, origen=r, cancelado=cancelado))
                except (OSError, ValueError):
                    continue
            return hechos[-1] if hechos else {}
        return _en_segundo_plano(self, todo, f"😂 {len(rutas)} archivo(s) en tus memes." if len(rutas) > 1 else
                                 "😂 «{nombre}» en tus memes.")

    def _menu(self, pos):
        it = self.rejilla.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.rejilla.setCurrentItem(it)
        menu = QMenu(self)
        menu.addAction("Poner en el cabezal", lambda: self.poner_en_cabezal(self.elegidos()))
        menu.addAction("A Medios", lambda: [importar(self.ctrl, m["ruta"]) for m in self.elegidos()])
        menu.addSeparator()
        menu.addAction("Renombrar…", lambda: self.renombrar())
        menu.addAction("Etiquetas…", lambda: self.etiquetar())
        m = it.data(Qt.UserRole) or {}
        menu.addAction("Mostrar en el Explorador",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(m.get("ruta", "")))))
        menu.addSeparator()
        menu.addAction("Quitar (a la Papelera)…", lambda: self.quitar())
        from . import help as AYUDA
        AYUDA.exec_menu(menu, self.rejilla.viewport().mapToGlobal(pos))
