"""
🗣 Panel «Voz IA»: si no quieres hablar, pegas el guion entero, eliges la voz y Reclaimer lee la narración (Kokoro o
Piper, en tu PC; voces de «🎙 Narración» graves y calmadas para contar historia). «✓ Crear narración» la importa a Medios, la pone en la pista de voz en el cabezal (o en lugar de la narración IA
anterior) y le da YA su transcripción con el texto exacto: subtítulos, «💬 Subtítulos auto», palabras clave, Texto…
funcionan sin esperar a Whisper.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..ai import tts
from ..core.model import TRACK_AUDIO
from . import diseno as D
from .common import fmt_time
from .jobs import BackgroundJob


def _dim(text: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("dim")
    lb.setWordWrap(True)
    lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return lb


def _sin_sonido() -> bool:
    return bool(os.environ.get("EDITORIA_SIN_SONIDO")) or os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class DiccionarioDialog(QDialog):
    """📖 El diccionario de pronunciación: «palabra = como suena», una por línea."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 Pronunciación de la voz IA")
        self.resize(520, 440)
        v = QVBoxLayout(self)
        self.edit = QPlainTextEdit(tts.texto_diccionario())
        self.edit.setToolTip("Una palabra por línea:  palabra = como suena\n"
                             "Ejemplo: «online = onlain». No distingue mayúsculas y vale para varias palabras seguidas.\n"
                             "Solo cambia cómo se LEE: los subtítulos siguen con lo que escribiste.\n"
                             "Las líneas que empiezan por # no cuentan.")
        v.addWidget(self.edit, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._guardar)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _guardar(self):
        try:
            tts.guardar_diccionario(self.edit.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Pronunciación", f"No se pudo guardar el diccionario:\n{exc}")
            return
        self.accept()


class _Guion(QPlainTextEdit):
    """El cuadro del guion, con «📖 Cómo se pronuncia…» en el clic derecho sobre lo seleccionado."""

    pronunciar = Signal(str)

    def contextMenuEvent(self, e):
        m = self.createStandardContextMenu()
        sel = self.textCursor().selectedText().strip()
        if sel and len(sel) <= 60:
            m.addSeparator()
            m.addAction(f"📖 Cómo se pronuncia «{sel}»…", lambda s=sel: self.pronunciar.emit(s))
        m.exec(e.globalPos())


class VozIAPanel(QWidget):
    narracion_creada = Signal(str)        # id del medio nuevo (ya en Medios, en la línea de tiempo y transcrito)

    def __init__(self, win):
        super().__init__()
        self.win, self.ctrl = win, win.ctrl
        self.job: BackgroundJob | None = None
        self._tarea = ""                   # "muestra" | "crear"
        self._player = None
        self._muestra_ruta = ""
        self.ultimo: dict | None = None    # lo último creado (ruta, medio, clips): para la prueba y el estado
        st = QSettings("EditorIA", "EditorIA")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(D.M2), D.px(D.M2), D.px(D.M2), D.px(D.M2))
        lay.setSpacing(D.px(D.M1))
        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet("color: #e5a50a;")
        self.aviso.setVisible(False)
        lay.addWidget(self.aviso)
        self.b_descargar = QPushButton(f"Descargar esta voz ({tts.TAM_DESCARGA})")
        self.b_descargar.setObjectName("primary")
        self.b_descargar.setIcon(D.icono("download"))
        self.b_descargar.clicked.connect(self.descargar)
        self.b_descargar.setVisible(False)
        lay.addWidget(self.b_descargar)

        self.texto = _Guion()
        self.texto.setPlaceholderText("Pega aquí tu guion completo…")
        self.texto.setToolTip("El texto que leerá la voz. Puedes pegar el guion entero (Ctrl+V).\n"
                              "Cada frase se lee por separado; una línea en blanco = párrafo nuevo (pausa más larga).\n"
                              "Lo que escribas aquí será también el texto de los subtítulos.\n"
                              "Clic derecho sobre una palabra seleccionada → cómo se pronuncia.")
        self.texto.setMinimumHeight(220)
        self.texto.pronunciar.connect(self._pronunciar)
        lay.addWidget(self.texto, 1)
        fila = QHBoxLayout()
        self.contador = _dim("0 palabras")
        self.contador.setToolTip("Palabras del guion y cuánto durará la narración (aproximado, con la velocidad y las "
                                 "pausas elegidas).")
        fila.addWidget(self.contador, 1)
        b_pegar = D.BotonIcono("copy", "Pegar: pone en el cuadro el texto que tengas copiado (sustituye lo que "
                                       "haya).")
        b_pegar.clicked.connect(self._pegar)
        fila.addWidget(b_pegar)
        b_txt = D.BotonIcono("folder-open", "Abrir .txt: el guion desde un archivo de texto (.txt o .md).")
        b_txt.clicked.connect(self._abrir_txt)
        fila.addWidget(b_txt)
        b_vaciar = D.BotonIcono("trash-2", "Vaciar el cuadro del guion.")
        b_vaciar.clicked.connect(self.texto.clear)
        fila.addWidget(b_vaciar)
        lay.addLayout(fila)

        form = QVBoxLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(D.px(D.M1))
        # (21/11: filas del Inspector —FilaInspector—: la etiqueta en su columna y, si no cabe, ENCIMA; los
        #  desplegables se acortan con «…» y el texto entero al pasar el ratón)
        self.voz = QComboBox()
        self.voz.setMaxVisibleItems(24)
        for grupo in tts.GRUPOS:                       # agrupado: 🎙 Narración / Kokoro / Piper (títulos sin elegir)
            self.voz.addItem(f"── {grupo} ──")
            it = self.voz.model().item(self.voz.count() - 1)
            it.setFlags(it.flags() & ~(Qt.ItemIsSelectable | Qt.ItemIsEnabled))
            for clave, v in tts.CATALOGO.items():
                if v.grupo == grupo:
                    self.voz.addItem(("" if grupo == tts.GRUPOS[0] else "   ") + v.nombre, clave)
                    self.voz.setItemData(self.voz.count() - 1, tts.tooltip_voz(clave), Qt.ToolTipRole)
        guardada = st.value("voz_ia/voz", tts.VOZ_DEFECTO)
        i = self.voz.findData(guardada if guardada in tts.CATALOGO else tts.VOZ_DEFECTO)
        self.voz.setCurrentIndex(i if i >= 0 else self.voz.findData(tts.VOZ_DEFECTO))
        from . import responsive as _R          # (el desplegable se acorta con «…» y el texto entero al pasar el
        _R._desplegable(self.voz)               #  ratón: así la fila baja a 200 px sin cortar nada)
        form.addWidget(D.FilaInspector("Voz", self.voz))
        self.acento = QComboBox()
        for clave, nombre in tts.ACENTOS.items():
            self.acento.addItem(nombre, clave)
        self.acento.setCurrentIndex(max(0, self.acento.findData(st.value("voz_ia/acento", "es"))))
        self.acento.setToolTip("España: «z» y «ce/ci» como en España. Latinoamérica: con seseo.")
        _R._desplegable(self.acento)
        form.addWidget(D.FilaInspector("Acento", self.acento))
        self.velocidad = QDoubleSpinBox()
        self.velocidad.setRange(0.7, 1.6)
        self.velocidad.setSingleStep(0.05)
        self.velocidad.setDecimals(2)
        self.velocidad.setSuffix(" x")
        self.velocidad.setValue(float(st.value("voz_ia/velocidad", 1.10)))
        self.velocidad.setToolTip("Lo rápido que habla (1,00 = normal). Para Shorts suele ir bien 1,20–1,30.\n"
                                  "Se multiplica por el ritmo propio de la voz: las de «🎙 Narración» ya van más "
                                  "pausadas.")
        form.addWidget(D.FilaInspector("Velocidad", self.velocidad))
        self.pausa = QDoubleSpinBox()
        self.pausa.setRange(0.0, 1.5)
        self.pausa.setSingleStep(0.05)
        self.pausa.setDecimals(2)
        self.pausa.setSuffix(" s")
        self.pausa.setValue(float(st.value("voz_ia/pausa", 0.25)))
        self.pausa.setToolTip("Silencio entre una frase y la siguiente (las voces de «🎙 Narración» lo alargan un "
                              "poco).")
        form.addWidget(D.FilaInspector("Pausa entre frases", self.pausa))
        self.pausa_par = QDoubleSpinBox()
        self.pausa_par.setRange(0.0, 3.0)
        self.pausa_par.setSingleStep(0.1)
        self.pausa_par.setDecimals(2)
        self.pausa_par.setSuffix(" s")
        self.pausa_par.setValue(float(st.value("voz_ia/pausa_parrafo", 0.6)))
        self.pausa_par.setToolTip("Silencio al cambiar de párrafo (una línea en blanco en el guion).")
        form.addWidget(D.FilaInspector("Pausa entre párrafos", self.pausa_par))
        lay.addLayout(form)
        self.robot = D.CasillaTexto("Toque robótico")
        self.robot.setChecked(st.value("voz_ia/robot", False, type=bool))
        self.robot.setToolTip("Algo más aguda, con timbre de radio y un pelín metálica (estilo Loquendo). "
                              "La duración no cambia.")
        lay.addWidget(self.robot)
        self.afinar = D.CasillaTexto("Afinar cada palabra con la IA")
        self.afinar.setChecked(st.value("voz_ia/afinar", False, type=bool))
        self.afinar.setToolTip("Después de leer, el alineador escucha la narración y coloca cada palabra al centésimo "
                               "(subtítulos aún más exactos). Tarda más (más o menos lo que dura la narración).\n"
                               "Sin marcar, los tiempos salen de cada frase leída y ya van bien para subtítulos.")
        lay.addWidget(self.afinar)

        fila = QHBoxLayout()
        self.b_muestra = QPushButton("Muestra")
        self.b_muestra.setIcon(D.icono("play"))
        self.b_muestra.setToolTip("Lee solo la primera frase para oír cómo queda la voz, la velocidad y la "
                                  "pronunciación (no se añade nada al proyecto).")
        self.b_muestra.clicked.connect(self.muestra)
        fila.addWidget(self.b_muestra)
        self.b_crear = D.BotonPrincipal("Crear narración", "check")
        self.b_crear.setToolTip("Lee el guion entero, lo importa a Medios y lo pone en la pista de voz en el cabezal, "
                                "ya con su transcripción (subtítulos y palabras clave al momento). Ctrl+Z lo quita.\n"
                                "Si ya hay una narración IA en la línea de tiempo, te pregunta si reemplazarla.")
        self.b_crear.clicked.connect(lambda: self.crear())
        fila.addWidget(self.b_crear, 1)
        lay.addLayout(fila)
        fila = QHBoxLayout()
        b_dic = QPushButton("Pronunciación…")
        b_dic.setIcon(D.icono("book-open"))
        b_dic.setToolTip("Diccionario de pronunciación: cómo se debe leer una palabra («palabra = como suena»).")
        b_dic.clicked.connect(self.abrir_diccionario)
        fila.addWidget(b_dic)
        b_dir = D.BotonIcono("folder-open", "Carpeta: abre la carpeta donde se guardan las narraciones (junto al "
                                            "proyecto, «Grabaciones de voz»).")
        b_dir.clicked.connect(self._abrir_carpeta)
        fila.addWidget(b_dir)
        fila.addStretch()
        lay.addLayout(fila)
        self.b_muestras = QPushButton("Muestras de todas las voces")
        self.b_muestras.setIcon(D.icono("headphones"))
        self.b_muestras.setToolTip(
            "Lee el mismo texto corto de narración histórica con cada voz y guarda un WAV por voz (con su nombre) y un "
            f"LEEME.txt con qué es cada una y su licencia, en:\n{tts.carpeta_muestras()}\n"
            "Al terminar abre la carpeta para que las compares. Las voces sin descargar se saltan. Tarda ~1 min.")
        self.b_muestras.clicked.connect(lambda: self.muestras_todas())
        lay.addWidget(self.b_muestras)

        fila = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        fila.addWidget(self.progress, 1)
        self.b_cancelar = QPushButton("Cancelar")
        self.b_cancelar.setVisible(False)
        self.b_cancelar.clicked.connect(self.cancelar)
        fila.addWidget(self.b_cancelar)
        lay.addLayout(fila)
        self.status = _dim()
        lay.addWidget(self.status)

        borrador = tts.leer_borrador()
        if not borrador and st.contains("voz_ia/texto"):          # (de antes: estaba en el registro)
            borrador = str(st.value("voz_ia/texto", "") or "")
        st.remove("voz_ia/texto")
        if borrador:
            self.texto.setPlainText(borrador)
        self._borrador = self.texto.toPlainText()
        self._t_contar = QTimer(self)
        self._t_contar.setSingleShot(True)
        self._t_contar.setInterval(350)
        self._t_contar.timeout.connect(self._contar)
        self.texto.textChanged.connect(self._t_contar.start)
        for w in (self.velocidad, self.pausa, self.pausa_par):
            w.valueChanged.connect(self._t_contar.start)
        for w in (self.voz, self.acento):
            w.currentIndexChanged.connect(self._guardar_ajustes)
        self.voz.currentIndexChanged.connect(self._voz_cambiada)
        for w in (self.velocidad, self.pausa, self.pausa_par):
            w.valueChanged.connect(self._guardar_ajustes)
        for w in (self.robot, self.afinar):
            w.toggled.connect(self._guardar_ajustes)
        self._voz_cambiada()

    # ------------------------------------------------------------------ estado
    def voz_actual(self) -> str:
        clave = self.voz.currentData()
        return clave if clave in tts.CATALOGO else tts.VOZ_DEFECTO

    def _voz_cambiada(self, *_a):
        clave = self.voz_actual()
        self.voz.setToolTip("La voz que lee el guion. Cada una lleva su descripción al pasar el ratón por la lista.\n\n"
                            + tts.tooltip_voz(clave))
        kokoro = tts.voz_info(clave).motor == "kokoro"
        self.acento.setEnabled(kokoro)
        self.acento.setToolTip("España: «z» y «ce/ci» como en España. Latinoamérica: con seseo." if kokoro else
                               "Esta voz tiene su acento propio (el de su grabación).")
        self._comprobar()
        self._contar()

    def _comprobar(self) -> bool:
        clave = self.voz_actual()
        ok, why = tts.available(clave)
        # (las rutas de carpeta no tienen espacios: se pueden partir en cada barra para no cortar el panel)
        self.aviso.setText(("⚠ " + why).replace("\\", "\\​").replace("/", "/​") if not ok else "")
        self.aviso.setToolTip(why if not ok else "")
        self.aviso.setVisible(not ok)
        falta = tts.falta_modelo(clave)
        self.b_descargar.setVisible(falta)
        if falta:
            v = tts.voz_info(clave)
            self.b_descargar.setText(f"Descargar esta voz ({tts.tam_descarga(clave)})")
            self.b_descargar.setToolTip(
                "Baja el modelo de voz Kokoro (Apache 2.0) de su página oficial en GitHub, una sola vez. Sirve para "
                "Alex, Santa, Dora y sus variantes de narración." if v.motor == "kokoro" else
                f"Baja la voz Piper «{v.voz}» ({tts.PIPER_MODELOS[str(v.voz)]['licencia']}) de rhasspy/piper-voices "
                "(Hugging Face), una sola vez.")
            self.b_descargar.setToolTip(self.b_descargar.toolTip() + " Después funciona sin internet.")
        try:
            from ..ai import align
            al_ok = align.available()[0]
        except Exception:  # noqa: BLE001
            al_ok = False
        self.afinar.setEnabled(al_ok)
        if not al_ok:
            self.afinar.setToolTip("Hace falta el modelo alineador del motor de IA (motor_ia/alineador_es).")
        self._actualizar(ok)
        return ok

    def _actualizar(self, ok: bool | None = None):
        if ok is None:
            ok = tts.available(self.voz_actual())[0]
        libre = self.job is None
        self.b_muestra.setEnabled(ok and (libre or self._tarea == "muestra"))
        self.b_crear.setEnabled(ok and libre)
        self.b_muestras.setEnabled(libre)
        self.b_descargar.setEnabled(libre)
        self.b_muestra.setText("Parar" if self._sonando() else "Muestra")
        self.b_muestra.setIcon(D.icono("square" if self._sonando() else "play"))

    def _contar(self):
        texto = self.texto.toPlainText()
        try:
            n, seg = tts.contar(texto, self.velocidad.value(), self.pausa.value(), self.pausa_par.value(),
                                self.voz_actual())
        except Exception:  # noqa: BLE001 - un texto raro nunca rompe el panel
            n, seg = len(texto.split()), 0.0
        self.contador.setText(f"{n} palabra{'s' if n != 1 else ''} · ~{fmt_time(seg, frac=False)}" if n else
                              "0 palabras")
        if texto != self._borrador:              # 📝 el borrador, en datos/voz_ia/borrador.txt (no en el registro)
            try:
                tts.guardar_borrador(texto)
                self._borrador = texto
            except OSError:
                pass

    def _guardar_ajustes(self, *_a):
        st = QSettings("EditorIA", "EditorIA")
        st.setValue("voz_ia/voz", self.voz_actual())
        st.setValue("voz_ia/acento", self.acento.currentData())
        st.setValue("voz_ia/velocidad", round(self.velocidad.value(), 2))
        st.setValue("voz_ia/pausa", round(self.pausa.value(), 2))
        st.setValue("voz_ia/pausa_parrafo", round(self.pausa_par.value(), 2))
        st.setValue("voz_ia/robot", self.robot.isChecked())
        if self.afinar.isEnabled():
            st.setValue("voz_ia/afinar", self.afinar.isChecked())

    def opciones(self) -> dict:
        return {"voz": self.voz_actual(), "velocidad": round(self.velocidad.value(), 2),
                "pausa": round(self.pausa.value(), 2), "pausa_parrafo": round(self.pausa_par.value(), 2),
                "acento": self.acento.currentData() or "es", "robot": self.robot.isChecked()}

    # ------------------------------------------------------------------ texto
    def _pegar(self):
        from PySide6.QtWidgets import QApplication
        t = QApplication.clipboard().text()
        if t.strip():
            self.texto.setPlainText(t)
        else:
            self.status.setText("No hay texto copiado.")

    def _abrir_txt(self):
        ruta, _f = QFileDialog.getOpenFileName(self, "Abrir guion", "", "Texto (*.txt *.md);;Todos (*.*)")
        if not ruta:
            return
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                with open(ruta, encoding=enc) as f:
                    self.texto.setPlainText(f.read())
                return
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                QMessageBox.warning(self, "Abrir guion", f"No se pudo abrir el archivo:\n{exc}")
                return

    def _pronunciar(self, palabra: str):
        suena, ok = QInputDialog.getText(self, "📖 Pronunciación", f"¿Cómo se dice «{palabra}»? (escríbelo como suena)",
                                         text=palabra)
        if ok and suena.strip():
            tts.añadir_al_diccionario(palabra, suena)
            self.status.setText(f"«{palabra}» se leerá «{suena.strip()}». «Muestra» para oírlo.")

    def abrir_diccionario(self):
        from .herramientas import abrir_dialogo
        abrir_dialogo(self, "diccionario_voz", lambda: DiccionarioDialog(self), "Diccionario de la voz IA",
                      "Diccionario", "book-open")

    def carpeta(self) -> str:
        from ..core.voice_record import takes_dir
        return takes_dir(self.ctrl.path)

    def _abrir_carpeta(self):
        try:
            os.startfile(self.carpeta())       # noqa: S606
        except OSError as exc:
            self.status.setText(f"No se pudo abrir la carpeta: {exc}")

    # ------------------------------------------------------------------ trabajos
    def _empezar(self, tarea: str, fn, al_terminar, etiqueta: str):
        self._tarea = tarea
        self.job = BackgroundJob(fn, self)
        self.job.title = "🗣 Voz IA: " + {"muestra": "muestra", "descarga": "descargar la voz",
                                        "muestras": "muestras de todas las voces"}.get(tarea, "narración")
        self.job.progress.connect(self._progreso)
        self.job.done.connect(al_terminar)
        self.job.failed.connect(self._fallo)
        self.job.finished.connect(self._fin_trabajo)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.b_cancelar.setVisible(True)
        self.status.setText(etiqueta)
        self._actualizar()
        self.job.start()

    def _progreso(self, f: float, texto: str):
        if f <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(f * 1000))
        self.status.setText(texto)

    def _fallo(self, msg: str):
        if msg == "Cancelado.":
            self.status.setText("Cancelado: no se ha guardado nada.")
            return
        self.status.setText("✗ " + msg)
        if not _sin_sonido():
            QMessageBox.warning(self, "🗣 Voz IA", msg)

    def _fin_trabajo(self):
        job, self.job = self.job, None
        self._tarea = ""
        if job is not None:
            job.deleteLater()
        self.progress.setVisible(False)
        self.b_cancelar.setVisible(False)
        self._actualizar()

    def cancelar(self):
        if self.job is not None:
            self.job.cancel()
            self.status.setText("Cancelando… (termina la frase que está leyendo)")

    def ocupado(self) -> bool:
        return self.job is not None

    # ------------------------------------------------------------------ ⬇ descargar el modelo
    def descargar(self):
        """⬇ El modelo que le falta a la voz elegida (Kokoro ≈350 MB de kokoro-onnx; Piper ~60–80 MB de
        rhasspy/piper-voices), con progreso y cancelar."""
        if self.job is not None:
            return
        clave = self.voz_actual()

        def work(progress, cancelled):
            return str(tts.descargar(progress, cancelled, voz=clave))

        def hecho(carpeta):
            ok = self._comprobar()
            self.status.setText("✓ Voz descargada: ya puedes crear narraciones." if ok else
                                f"✓ Voz descargada en {carpeta}. " + tts.available(self.voz_actual())[1])
        self._empezar("descarga", work, hecho, "⬇ Conectando…")

    # ------------------------------------------------------------------ 🎧 muestras de todas las voces
    def muestras_todas(self, carpeta: str | None = None):
        """🎧 La misma narración con cada voz en «Muestras de voces» (en segundo plano); al terminar abre la carpeta
        (en las pruebas no se abre nada ni suena nada)."""
        if self.job is not None:
            return
        destino = str(carpeta or tts.carpeta_muestras())
        self.ultimas_muestras: list[str] = []

        def work(progress, cancelled):
            return tts.crear_muestras(destino, progress=progress, cancelled=cancelled)

        def hecho(rutas):
            self.ultimas_muestras = list(rutas)
            self.status.setText(f"{len(rutas)} muestras en «{destino}» (y un LEEME.txt con cada voz y su licencia).")
            if not _sin_sonido():
                try:
                    os.startfile(destino)      # noqa: S606
                except OSError:
                    pass
        self._empezar("muestras", work, hecho, "🎧 Preparando las muestras…")

    # ------------------------------------------------------------------ ▶ muestra
    def _sonando(self) -> bool:
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            return self._player is not None and self._player.playbackState() == QMediaPlayer.PlayingState
        except Exception:  # noqa: BLE001
            return False

    def parar(self):
        if self._player is not None:
            self._player.pause()           # (stop() a veces se cuelga en Windows)
            self._player.setSource(QUrl())      # (suelta el archivo)
        self._actualizar()

    def muestra(self):
        """▶ Solo la primera frase, para oír la voz y la velocidad (en las pruebas no suena)."""
        if self._sonando():
            self.parar()
            return
        if self.job is not None or not self._comprobar():
            return
        texto = self.texto.toPlainText()
        if not tts.frases(texto):
            self.status.setText("Pega primero el texto que quieres que lea.")
            return
        o = self.opciones()
        from ..core.paths import temp_dir
        viejo = self._muestra_ruta
        destino = os.path.join(str(temp_dir()), f"voz_ia_muestra_{int(time.time() * 1000)}.wav")

        def work(progress, cancelled):
            return tts.sintetizar(texto, o["voz"], o["velocidad"], o["pausa"], o["pausa_parrafo"], o["acento"],
                                  o["robot"], destino, progress, cancelled, solo_primera=True)

        def hecho(res):
            if viejo and viejo != res["ruta"]:
                try:
                    os.remove(viejo)
                except OSError:
                    pass
            self._muestra_ruta = res["ruta"]
            self.status.setText(f"Muestra: «{res['frases'][0]['texto'][:60]}» ({res['duracion']:.1f} s).")
            self.reproducir(res["ruta"])
        self._empezar("muestra", work, hecho, "Preparando la muestra…")

    def reproducir(self, ruta: str):
        if _sin_sonido():
            return                         # (pruebas: nunca suena)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.playbackStateChanged.connect(lambda _s: self._actualizar())
        self._player.setSource(QUrl.fromLocalFile(ruta))
        self._player.play()
        self._actualizar()

    # ------------------------------------------------------------------ ✓ crear narración
    def clips_ia(self) -> list:
        """Los clips de la línea de tiempo que son narraciones IA (por la etiqueta de su medio)."""
        p = self.ctrl.project
        out = []
        for c in p.clips.values():
            m = p.media.get(c.media_id)
            if m is not None and tts.ETIQUETA in (m.tags or []):
                out.append(c)
        return sorted(out, key=lambda c: c.start)

    def _preguntar_modo(self) -> str | None:
        """Ya hay una narración IA en la línea de tiempo: ¿reemplazarla o versión nueva?"""
        box = QMessageBox(self)
        box.setWindowTitle("🗣 Narración IA")
        box.setText("Ya hay una narración IA en la línea de tiempo.")
        box.setInformativeText("Reemplazar = la nueva va en su sitio y la anterior sale de la línea de tiempo (sigue en "
                               "Medios).\nVersión nueva = se añade en el cabezal y la anterior se queda.")
        b_rep = box.addButton("♻ Reemplazar la anterior", QMessageBox.AcceptRole)
        b_new = box.addButton("＋ Versión nueva", QMessageBox.ActionRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.setDefaultButton(b_rep)
        box.exec()
        return "reemplazar" if box.clickedButton() is b_rep else "nueva" if box.clickedButton() is b_new else None

    def crear(self, modo: str | None = None):
        """✓ Lee el guion entero y lo pone como narración. modo: "reemplazar" | "nueva" | None (pregunta si hace
        falta)."""
        if self.job is not None or not self._comprobar():
            return
        texto = self.texto.toPlainText()
        if not tts.frases(texto):
            self.status.setText("Pega primero el texto que quieres que lea.")
            return
        if modo is None:
            modo = self._preguntar_modo() if self.clips_ia() else "nueva"
            if modo is None:
                return
        if self._sonando():
            self.parar()
        o = self.opciones()
        afinar = self.afinar.isEnabled() and self.afinar.isChecked()
        try:
            destino = tts.ruta_nueva(self.carpeta(), o["voz"])
        except OSError as exc:
            self.status.setText(f"✗ No se puede escribir en la carpeta de grabaciones: {exc}")
            return
        proyecto = self.ctrl.project
        t_cab = float(getattr(self.win.engine, "time", 0.0) or 0.0)

        def work(progress, cancelled):
            def parte(lo, hi):
                return lambda f, t: progress(lo + (hi - lo) * f, t)
            res = tts.sintetizar(texto, o["voz"], o["velocidad"], o["pausa"], o["pausa_parrafo"], o["acento"],
                                 o["robot"], destino, parte(0.0, 0.7 if afinar else 1.0), cancelled)
            # (voz CC BY: sus créditos junto al WAV → apartado «🗣 Voz:» de la descripción del video)
            res["creditos"] = tts.escribir_creditos(destino, o["voz"])
            if afinar:
                try:
                    res["transcripcion"] = tts.afinar(destino, res["transcripcion"], parte(0.7, 1.0), cancelled)
                except BaseException:
                    for x in (destino, res["creditos"]):    # (cancelado al afinar: tampoco queda nada)
                        try:
                            if x:
                                os.remove(x)
                        except OSError:
                            pass
                    raise
            return res

        def hecho(res):
            if self.ctrl.project is not proyecto:
                self.status.setText(f"La narración se guardó en «{res['ruta']}», pero cambiaste de proyecto: "
                                    "impórtala desde Medios si la quieres aquí.")
                return
            self.colocar(res, modo, t_cab)
        self._empezar("crear", work, hecho, "Preparando la voz…")

    def colocar(self, res: dict, modo: str, t_cab: float | None = None) -> list:
        """La narración: a Medios (categoría Narración, etiqueta 🗣 Voz IA), con su transcripción, y a la pista de voz:
        en el cabezal o en lugar de la narración IA anterior. Todo lo de la línea de tiempo, un solo Ctrl+Z."""
        ctrl, win = self.ctrl, self.win
        ruta, tr = res["ruta"], res["transcripcion"]
        ids = ctrl.import_now([ruta], quiet=True)
        if not ids:
            self.status.setText(f"✗ No se pudo importar la narración ({ruta}).")
            return []
        mid = ids[0]
        ctrl.set_media_props([mid], category="Narración", tags=[tts.ETIQUETA])
        ctrl.set_transcript(mid, tr)                   # (ya transcrita: subtítulos y palabras clave al momento)
        voz = getattr(win, "voice", None)              # la narración elegida en Transcribir / Limpieza / Texto
        if voz is not None:
            i = voz.media_combo.findData(mid)
            if i >= 0:
                voz.media_combo.setCurrentIndex(i)
        p = ctrl.project
        anteriores = [c for c in self.clips_ia() if c.media_id != mid]
        if modo == "reemplazar" and anteriores:
            bloqueado = any(c.locked or (p.track(c.track_id) and p.track(c.track_id).locked) for c in anteriores)
            if bloqueado:
                self.status.setText("La narración anterior está bloqueada: la nueva va en el cabezal.")
                modo = "nueva"
        st = p.subtitles
        creados = None
        if modo == "reemplazar" and anteriores:
            t0 = anteriores[0].start
            tid = anteriores[0].track_id
            viejos = {c.media_id for c in anteriores}
            ctrl.undo_stack.beginMacro("🗣 Reemplazar la narración IA")
            try:
                ctrl.delete_clips([c.id for c in anteriores])
                creados = ctrl.add_media([mid], tid, t0)
                if creados and st.media_id in viejos:  # (los subtítulos salían de la anterior: ahora de la nueva)
                    ctrl.set_subtitle_style("Subtítulos de la narración IA", media_id=mid, emphasis=[])
            finally:
                ctrl.undo_stack.endMacro()
        else:
            t0 = float(win.engine.time if t_cab is None else t_cab)
            tid = ctrl._role_track(p, "voz", create=False) or next(
                (t.id for t in p.tracks if t.kind == TRACK_AUDIO and not t.locked), None)
            if tid is None:
                self.status.setText("✗ No hay ninguna pista de audio libre (¿están todas bloqueadas?). La narración "
                                    "está en Medios.")
                return []
            ctrl.undo_stack.beginMacro("🗣 Narración IA")
            try:
                creados = ctrl.add_media([mid], tid, t0)
                # (de dónde salen los subtítulos, si aún no salían de ninguna narración transcrita; «💬 Subtítulos
                # auto» de Vertical/Edits ya se lanzó al poner el clip y los encenderá con esta)
                if creados and st.media_id not in p.transcripts:
                    ctrl.set_subtitle_style("Texto de los subtítulos", media_id=mid)
            finally:
                ctrl.undo_stack.endMacro()
        if not creados:
            self.status.setText("✗ No se pudo poner en la línea de tiempo (¿pista bloqueada?). La narración está en "
                                "Medios, ya transcrita.")
            return []
        try:
            win.engine.seek(t0)
        except Exception:  # noqa: BLE001
            pass
        n = len(tr.get("words", []))
        self.ultimo = {"ruta": ruta, "media_id": mid, "clips": list(creados), "duracion": res["duracion"]}
        self.status.setText(f"✓ Narración de {fmt_time(res['duracion'], frac=False)} en la pista de voz, en "
                            f"{fmt_time(t0, frac=False)} ({n} palabras ya transcritas: subtítulos y palabras clave "
                            "listos). Ctrl+Z la quita.")
        self.narracion_creada.emit(mid)
        return list(creados)

    def shutdown(self):
        job = self.job
        if job is not None and job.isRunning():
            job.cancel()
            job.wait(5000)
        if self._player is not None:
            try:
                self._player.pause()
                self._player.setSource(QUrl())
            except RuntimeError:
                pass
        if self._muestra_ruta:
            try:
                os.remove(self._muestra_ruta)
            except OSError:
                pass
