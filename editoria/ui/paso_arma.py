"""
🎙 «Edita desde tu voz», paso 3 «Arma tu video» — la página del panel (23/11). El armado lo hace el Armador del
programador 2 (ui/armar_video.py); aquí solo se enchufa:
  · [Armar mi video] (un clic): sin huecos, por prioridad y sin repetir; en cadena si la transcripción sigue llegando
    (texto_parcial → trozo_listo, transcripcion_lista → transcripcion_terminada).
  · La imagen del juego como base (si en el paso 1 elegiste «También su imagen»): ajustes["base_media_id"].
  · La carpeta de relleno, a la vista: elegir / quitar (ajuste armar/carpeta_relleno).
  · «Seguir armando» si se cerró a medias (armar_video.pendiente). Progreso, avisos y cancelar dentro del panel.
  · «Mirar mis clips a fondo» (apagada: pesa): antes de armar, quién y qué aparece en cada clip (understand() de
    understand_dialog, en segundo plano); el armado pone el plano donde aparece lo que nombras. Si ya está
    analizado, se usa sin volver a mirar.
  · «Toques finales» (ui/toques_ui.py, plegable): se aplican al terminar el armado o con su botón.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from . import diseno as D


def _negrita():
    from PySide6.QtGui import QFont
    return QFont.DemiBold


class PaginaArma(QWidget):
    def __init__(self, ev):
        super().__init__()
        self.ev, self.win, self.ctrl = ev, ev.win, ev.ctrl
        self.armador = None
        c = D.colores()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(6))
        t = QLabel("Tu material donde lo nombras, sin huecos")
        t.setWordWrap(True)
        t.setFont(D.fuente(D.LETRA_G, _negrita()))
        lay.addWidget(t)
        self.b_armar = QPushButton("Armar mi video")
        self.b_armar.setObjectName("primary")
        self.b_armar.setIcon(D.icono("wand-sparkles", c["sobre_acento"], 16))
        self.b_armar.setToolTip("Un clic: pone material donde lo nombras, sin huecos y sin repetir escenas (primero el "
                                "momento exacto, luego tus clips, internet y tu carpeta de relleno). Solo en lo que "
                                "está vacío; todo el armado se deshace con un Ctrl+Z.")
        self.b_armar.clicked.connect(self.armar)
        lay.addWidget(self.b_armar)
        self.b_seguir = QPushButton("Seguir armando")
        self.b_seguir.setToolTip("El armado se quedó a medias (cerraste Reclaimer): sigue desde donde iba")
        self.b_seguir.clicked.connect(self.seguir)
        lay.addWidget(self.b_seguir)
        # carpeta de relleno
        fila = QHBoxLayout()
        fila.setSpacing(D.px(4))
        ic = QLabel()
        ic.setPixmap(D.pixmap_icono("folder-open", c["tenue"], D.px(14)))
        ic.setAlignment(Qt.AlignTop)
        fila.addWidget(ic)
        self.carpeta = QLabel("")
        self.carpeta.setWordWrap(True)
        self.carpeta.setFont(D.fuente(D.LETRA_P))
        fila.addWidget(self.carpeta, 1)
        self.b_carpeta = QToolButton()
        self.b_carpeta.setText("Elegir")
        self.b_carpeta.setToolTip("Tu carpeta de relleno: videos que pueden ir donde no haya nada mejor (lo último "
                                  "antes de dejar un hueco)")
        self.b_carpeta.clicked.connect(self.elegir_carpeta)
        fila.addWidget(self.b_carpeta)
        self.b_quitar = QToolButton()
        self.b_quitar.setIcon(D.icono("x", c["tenue"], 14))
        self.b_quitar.setAutoRaise(True)
        self.b_quitar.setToolTip("Sin carpeta de relleno")
        self.b_quitar.clicked.connect(lambda: self._poner_carpeta(""))
        fila.addWidget(self.b_quitar)
        lay.addLayout(fila)
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QCheckBox
        self.chk_fondo = QCheckBox("Mirar mis clips a fondo")
        self.chk_fondo.setToolTip("Antes de armar, la IA revisa cada segundo de tus clips y aprende quién y qué "
                                  "aparece: así pone el plano donde sale lo que nombras. Tarda (lo hace una vez: "
                                  "después se reutiliza).")
        self.chk_fondo.setChecked(str(QSettings("EditorIA", "EditorIA").value("armar/mirar_a_fondo", "false"))
                                  .lower() == "true")
        self.chk_fondo.toggled.connect(lambda on: QSettings("EditorIA", "EditorIA").setValue(
            "armar/mirar_a_fondo", "true" if on else "false"))
        lay.addWidget(self.chk_fondo)
        self.job_fondo = None
        self.base = QLabel("")
        self.base.setWordWrap(True)
        self.base.setFont(D.fuente(D.LETRA_P))
        self.base.setStyleSheet(f"color: {c['tenue']};")
        lay.addWidget(self.base)
        # progreso
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        self.estado.setFont(D.fuente(D.LETRA_P))
        self.estado.setStyleSheet(f"color: {c['tenue']};")
        lay.addWidget(self.estado)
        pf = QHBoxLayout()
        pf.setSpacing(D.px(4))
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(D.px(6))
        pf.addWidget(self.barra, 1)
        self.b_cancelar = QToolButton()
        self.b_cancelar.setIcon(D.icono("x", c["texto"], 14))
        self.b_cancelar.setAutoRaise(True)
        self.b_cancelar.setToolTip("Parar el armado (lo puesto se queda; un Ctrl+Z lo quita)")
        self.b_cancelar.clicked.connect(self.cancelar)
        pf.addWidget(self.b_cancelar)
        self.caja_prog = QWidget()
        self.caja_prog.setLayout(pf)
        pf.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.caja_prog)
        from .toques_ui import SeccionToques
        self.toques = SeccionToques(ev)
        self.toques.aviso.connect(self._aviso)
        self.toques.progreso.connect(self._progreso)
        self.toques.terminado.connect(self._fin_toques)
        lay.addWidget(self.toques)
        self.avisos = QLabel("")
        self.avisos.setWordWrap(True)
        self.avisos.setTextFormat(Qt.PlainText)
        self.avisos.setFont(D.fuente(D.LETRA_P))
        lay.addWidget(self.avisos)
        lay.addStretch(1)
        self.foco = self.b_armar
        ev.texto_parcial.connect(self._trozo)
        ev.transcripcion_lista.connect(self._fin_transcripcion)
        self.ctrl.project_replaced.connect(self.refrescar)
        self.refrescar()

    # ------------------------------------------------------------------ estado
    def _mod(self):
        from . import armar_video
        return armar_video

    def refrescar(self):
        av = self._mod()
        ocupado = ((self.armador is not None and self.armador.ocupado())
                   or getattr(self, "job_fondo", None) is not None
                   or (hasattr(self, "toques") and self.toques.ocupado))
        if hasattr(self, "toques") and not self.toques.ocupado:
            self.toques.llenar_musica()
        try:
            pend = bool(av.A.pendiente(self.ctrl)) and not ocupado
        except Exception:  # noqa: BLE001
            pend = False
        self.b_seguir.setVisible(pend)
        self.b_armar.setEnabled(not ocupado and bool(self.ev.estado().get("voz")))
        r = av.carpeta_relleno()
        self.carpeta.setText(os.path.basename(r.rstrip("\\/")) if r else "Sin carpeta de relleno")
        self.carpeta.setToolTip(r or "Elige una carpeta con videos para rellenar donde no haya nada mejor")
        self.b_quitar.setVisible(bool(r))
        b = self.ev.estado().get("base_media_id")
        m = self.ctrl.project.media.get(b) if b else None
        self.base.setVisible(m is not None)
        self.base.setText(f"La imagen de «{m.name}» hace de base donde no haya nada mejor." if m else "")
        self.caja_prog.setVisible(ocupado)
        if not ocupado and not self.avisos.text():
            self.estado.setText("")
        self.estado.setVisible(bool(self.estado.text()))     # (sin huecos: lo vacío no ocupa sitio)
        self.avisos.setVisible(bool(self.avisos.text()))

    def _poner_carpeta(self, ruta: str):
        self._mod().poner_carpeta_relleno(ruta or None)
        if self.armador is not None:
            self.armador.ajustes["carpeta_relleno"] = ruta or None
        self.refrescar()

    def elegir_carpeta(self):
        actual = self._mod().carpeta_relleno() or os.path.expanduser("~")
        r = QFileDialog.getExistingDirectory(self.win, "Carpeta de relleno", actual)
        if r:
            self._poner_carpeta(r)

    def _ajustes(self) -> dict:
        return {"base_media_id": self.ev.estado().get("base_media_id"),
                "carpeta_relleno": self._mod().carpeta_relleno() or None}

    def _nuevo(self):
        av = self._mod()
        self.armador = av.Armador(self.ctrl, ajustes=self._ajustes(), parent=self)
        self.armador.progreso.connect(self._progreso)
        self.armador.aviso.connect(self._aviso)
        self.armador.terminado.connect(self._terminado)
        self.avisos.setText("")
        return self.armador

    # ------------------------------------------------------------------ armar
    def armar(self):
        if self.armador is not None and self.armador.ocupado() or self.job_fondo is not None:
            return
        if self.chk_fondo.isChecked() and self.ctrl.understanding is None:
            self._mirar_a_fondo()
            return
        self._armar_ya()

    def _mirar_a_fondo(self):
        """🔬 Quién y qué aparece en cada clip, en segundo plano (con progreso y cancelar aquí). Lo ya analizado se
        reutiliza (sin volver a mirar)."""
        from ..ai import library_understanding as LU
        from .jobs import BackgroundJob
        from .understand_dialog import glossary_text, snapshot, understand
        snap, gloss = snapshot(self.ctrl), glossary_text()
        hondo = any(LU.load_deep(m["path"]) is None for m in snap["media"])

        def trabajo(progress, cancelled):
            return understand(snap, gloss, progress, cancelled, None, deep=hondo)

        def listo(res):
            self.ctrl.understanding = res
            try:
                self.win.ai_panel.refresh()
            except Exception:  # noqa: BLE001
                pass
            self._aviso(f"Clips mirados a fondo: {len(res.get('index') or {})} nombres reconocidos")
            self._armar_ya()

        def fallo(msg):
            self.estado.setText("Mirar a fondo parado: armo con lo que hay." if "ancel" in msg else
                                f"No pude mirar los clips a fondo ({msg}): armo con lo que hay.")
            self._armar_ya()
        self.job_fondo = BackgroundJob(trabajo, self.win)
        self.job_fondo.title = "🔬 Mirar mis clips a fondo"
        self.job_fondo.progress.connect(self._progreso)
        self.job_fondo.done.connect(listo)
        self.job_fondo.failed.connect(fallo)
        self.job_fondo.finished.connect(lambda: setattr(self, "job_fondo", None))
        self.estado.setText("Mirando tus clips a fondo…")
        self.caja_prog.show()
        self.job_fondo.start()

    def _armar_ya(self):
        en_cadena = self.ev.job_trans is not None
        if self._nuevo().empezar(0.0, None, en_cadena=en_cadena):
            self.estado.setText("Armando tu video…" + (" (mientras se transcribe el resto)" if en_cadena else ""))
        self.refrescar()

    def seguir(self):
        if self._nuevo().seguir():
            self.estado.setText("Siguiendo el armado desde donde iba…")
        self.refrescar()

    def cancelar(self):
        if self.job_fondo is not None:
            self.job_fondo.cancel()
        if self.armador is not None:
            self.armador.cancelar()
        self.toques.cancelar()

    def _trozo(self, _mid):
        if self.armador is not None and self.armador.ocupado():
            self.armador.trozo_listo()

    def _fin_transcripcion(self):
        if self.armador is not None and self.armador.ocupado():
            self.armador.transcripcion_terminada()

    def _progreso(self, f: float, t: str):
        self.caja_prog.show()
        self.estado.show()
        self.barra.setValue(int(max(0.0, min(1.0, f)) * 1000))
        self.estado.setText(t)

    def _aviso(self, t: str):
        lineas = [x for x in self.avisos.text().split("\n") if x]
        if t not in lineas:
            lineas.append(t)
        self.avisos.setText("\n".join(lineas[-6:]))
        self.avisos.show()

    def _terminado(self, res: dict):
        if res.get("cancelado"):
            self.estado.setText("Armado parado: lo puesto se queda (un Ctrl+Z lo quita).")
        else:
            n = int(res.get("puestos") or 0)
            falta = float(res.get("faltan") or 0.0)
            self.estado.setText(f"Listo: {n} trozos de material puestos." +
                                (f" Quedan {falta:.0f} s sin material." if falta > 0.5 else " Sin huecos."))
            if self.toques.aplicar():                   # (los toques finales, al terminar de armar)
                self.caja_prog.show()
        self.refrescar()

    def _fin_toques(self):
        self.estado.setText((self.estado.text() + " Toques aplicados.").strip())
        self.refrescar()


def instalar(ev) -> PaginaArma | None:
    try:
        pg = PaginaArma(ev)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return None
    ev.poner_paso(3, pg)
    ev.arma = pg
    return pg
