"""
✨ «Toques finales» en el paso 3 de «Edita desde tu voz» (23/11): lo útil de «Primera versión automática», en una
sección plegable y compacta (su estado se recuerda). Se aplica al terminar «Armar mi video» o con «Aplicar toques»; cada
toque es UN Ctrl+Z. La lógica está en ai/toques_finales.py (la misma que usa la ventana de siempre).

  Temas (encendido) · Estilo Natural / Dinámico / Cinematográfico (Natural no toca nada) · Zooms (apagado) · Música
  («Ninguna»; en los huecos, baja al hablar −12 dB y los cortes del B-roll a su ritmo) · −14 LUFS (encendido) ·
  Subtítulos (apagado) · Revisión final (encendido; su resumen, en los avisos del paso 3).
Sin ecualizador ni «Mejorar la voz» (la voz de OBS ya viene igualada) ni limpieza automática (eso es el paso 2).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ..ai import toques_finales as TF
from . import diseno as D

PRE = "toques/"
CASILLAS = (("temas", "Temas", True, "Temas y capítulos: busca de qué hablas en cada parte y pone un marcador por "
                                     "tema (sirven de capítulos)."),
            ("zooms", "Zooms", False, "Zooms en los momentos clave: un acercamiento rápido donde dices algo fuerte "
                                      "(si hay una cara, a ella)."),
            ("lufs", "−14 LUFS", True, "Volumen final −14 LUFS al exportar (lo que pide YouTube)."),
            ("subs", "Subtítulos", False, "Subtítulos de tu voz, con el estilo del proyecto."),
            ("revision", "Revisión", True, "Revisión final del proyecto: su resumen sale en los avisos de este paso."))


def _aj() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


class SeccionToques(QWidget):
    """La sección plegable y quien aplica los toques, uno detrás de otro (los que piensan, en segundo plano)."""
    aviso = Signal(str)
    progreso = Signal(float, str)
    terminado = Signal()

    def __init__(self, ev, parent=None):
        super().__init__(parent)
        self.ev, self.win, self.ctrl = ev, ev.win, ev.ctrl
        self.job = None
        self._cola: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(4))
        self.cab = QToolButton()
        self.cab.setText("Toques finales")
        self.cab.setCheckable(True)
        self.cab.setAutoRaise(True)
        self.cab.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.cab.setToolTip("Temas, estilo, zooms, música, volumen, subtítulos y revisión: se aplican al terminar "
                            "«Armar mi video» o con «Aplicar toques». Cada toque se deshace con un Ctrl+Z.")
        self.cab.toggled.connect(self._plegar)
        lay.addWidget(self.cab)
        self.cuerpo = QWidget()
        cl = QVBoxLayout(self.cuerpo)
        cl.setContentsMargins(D.px(14), 0, 0, 0)
        cl.setSpacing(D.px(4))
        rej = QGridLayout()
        rej.setContentsMargins(0, 0, 0, 0)
        rej.setHorizontalSpacing(D.px(8))
        rej.setVerticalSpacing(D.px(2))
        self.casillas: dict[str, QCheckBox] = {}
        for i, (k, nombre, defecto, tip) in enumerate(CASILLAS):
            cb = QCheckBox(nombre)
            cb.setToolTip(tip)
            cb.setChecked(str(_aj().value(PRE + k, "true" if defecto else "false")).lower() == "true")
            cb.toggled.connect(lambda on, kk=k: _aj().setValue(PRE + kk, "true" if on else "false"))
            rej.addWidget(cb, i // 2, i % 2)
            self.casillas[k] = cb
        cl.addLayout(rej)
        self.estilo = QComboBox()
        for k, n in TF.ESTILOS:
            self.estilo.addItem(n, k)
            self.estilo.setItemData(self.estilo.count() - 1, TF.NOMBRE_ESTILO[k], Qt.ToolTipRole)
        self.estilo.setCurrentIndex(max(0, self.estilo.findData(str(_aj().value(PRE + "estilo", "natural")))))
        self.estilo.currentIndexChanged.connect(lambda _i: _aj().setValue(PRE + "estilo", self.estilo.currentData()))
        self.estilo.setToolTip("Natural no toca nada. Dinámico: más cambios y zooms de golpe. Cinematográfico: zoom "
                               "lento, fundido en cada cambio de tema y un whoosh.")
        self.musica = QComboBox()
        self.musica.setToolTip("Una canción de fondo en los huecos de la pista de música: baja sola cuando hablas "
                               "(−12 dB) y los cortes del B-roll caen a su ritmo.")
        for etiqueta, combo in (("Estilo", self.estilo), ("Música", self.musica)):
            fila = QHBoxLayout()
            fila.setSpacing(D.px(6))
            lb = QLabel(etiqueta)
            fila.addWidget(lb)
            fila.addWidget(combo, 1)
            cl.addLayout(fila)
        self.b_aplicar = QPushButton("Aplicar toques")
        self.b_aplicar.setToolTip("Aplica ahora los toques marcados (cada uno, un Ctrl+Z)")
        self.b_aplicar.clicked.connect(lambda: self.aplicar())
        cl.addWidget(self.b_aplicar)
        lay.addWidget(self.cuerpo)
        abierto = str(_aj().value(PRE + "abierto", "false")).lower() == "true"
        self.cab.setChecked(abierto)
        self._plegar(abierto)
        self.llenar_musica()

    # ------------------------------------------------------------------ aspecto y datos
    def _plegar(self, on: bool):
        _aj().setValue(PRE + "abierto", "true" if on else "false")
        self.cuerpo.setVisible(on)
        self.cab.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def llenar_musica(self):
        actual = self.musica.currentData()
        self.musica.blockSignals(True)
        self.musica.clear()
        self.musica.addItem("Ninguna", None)
        voces = set(self.ev.estado().get("voz_media") or [])
        p = self.ctrl.project
        for m in sorted(p.media.values(), key=lambda m: (not self.ctrl.is_music_media(m), m.name.lower())):
            if m.kind == "audio" and m.id not in voces and m.id not in self.ctrl.missing:
                self.musica.addItem(os.path.splitext(m.name)[0], m.id)
                self.musica.setItemData(self.musica.count() - 1, m.name, Qt.ToolTipRole)
        i = self.musica.findData(actual)
        self.musica.setCurrentIndex(max(0, i))
        self.musica.blockSignals(False)

    def opciones(self) -> dict:
        o = {k: cb.isChecked() for k, cb in self.casillas.items()}
        o["estilo"] = self.estilo.currentData() or "natural"
        o["musica"] = self.musica.currentData()
        return o

    @property
    def ocupado(self) -> bool:
        return self.job is not None or bool(self._cola)

    # ------------------------------------------------------------------ aplicar
    def _voz(self) -> str | None:
        ids = [m for m in self.ev.estado().get("voz_media") or [] if m in self.ctrl.project.media]
        return ids[0] if ids else None

    def _pista(self) -> str | None:
        try:
            from ..ai import armar_video as A
            t = A.pista_destino(self.ctrl.project)
            return t if isinstance(t, str) else getattr(t, "id", None)
        except Exception:  # noqa: BLE001
            return TF.pista_broll(self.ctrl, self._voz())

    def aplicar(self, opciones: dict | None = None):
        """Los toques marcados, uno detrás de otro (cada uno, un Ctrl+Z). Devuelve False si no hay nada que hacer."""
        if self.ocupado:
            return False
        o = opciones or self.opciones()
        mid = self._voz()
        cola = []
        if o.get("temas") and mid:
            cola.append(self._temas)
        if o.get("estilo", "natural") != "natural":
            cola.append(lambda: self._estilo(o["estilo"]))
        if o.get("zooms") and mid:
            cola.append(self._zooms)
        if o.get("musica"):
            cola.append(lambda: self._musica(o["musica"]))
        if o.get("lufs"):
            cola.append(self._volumen)
        if o.get("subs") and mid:
            cola.append(self._subs)
        if o.get("revision"):
            cola.append(self._revision)
        if not cola:
            return False
        self._cola = cola
        self.b_aplicar.setEnabled(False)
        self._siguiente()
        return True

    def cancelar(self):
        self._cola = []
        if self.job is not None:
            self.job.cancel()

    def _siguiente(self):
        if self.job is not None:
            return
        if not self._cola:
            self.b_aplicar.setEnabled(True)
            self.terminado.emit()
            return
        paso = self._cola.pop(0)
        try:
            paso()
        except Exception as exc:  # noqa: BLE001 - un toque que falla no para los demás
            self.aviso.emit(f"Un toque no se pudo aplicar: {exc}")
            self._siguiente()

    def _bg(self, trabajo, listo, texto: str):
        from .jobs import BackgroundJob
        self.job = BackgroundJob(trabajo, self.win)
        self.job.title = "✨ Toques finales"
        self.job.progress.connect(lambda f, t: self.progreso.emit(f, t))
        self.job.done.connect(lambda r: self._hecho(listo, r))
        self.job.failed.connect(self._fallo)
        self.progreso.emit(0.0, texto)
        self.job.start()

    def _hecho(self, listo, r):
        self.job = None
        try:
            listo(r)
        except Exception as exc:  # noqa: BLE001
            self.aviso.emit(f"Un toque no se pudo aplicar: {exc}")
        self._siguiente()

    def _fallo(self, msg: str):
        self.job = None
        if "ancel" in msg:
            self._cola = []
            self.aviso.emit("Toques parados: lo aplicado se queda (Ctrl+Z lo quita).")
        else:
            self.aviso.emit(f"Un toque no se pudo aplicar: {msg}")
        self._siguiente()

    # (cada toque)
    def _temas(self):
        mid = self._voz()
        words = list((self.ctrl.project.transcripts.get(mid) or {}).get("words") or [])
        if len(words) < 30:
            self._siguiente()
            return

        def listo(segs):
            n, nombres = TF.poner_temas(self.ctrl, mid, segs)
            if n:
                self.aviso.emit("Temas: " + ", ".join(nombres[:6]) + ("…" if len(nombres) > 6 else ""))
        self._bg(lambda prog, canc: TF.detectar_temas(words, prog, canc), listo, "Buscando de qué hablas…")

    def _estilo(self, estilo: str):
        linea = TF.poner_estilo(self.ctrl, estilo, self._pista())
        if linea:
            self.aviso.emit(linea.lstrip("🎞 "))
        self._siguiente()

    def _zooms(self):
        plan, _n = TF.plan_zooms(self.ctrl, self._voz())
        if not plan:
            self._siguiente()
            return

        def listo(items):
            n = TF.poner_zooms(self.ctrl, items)
            if n:
                self.aviso.emit(f"{n} zooms en momentos clave")
        self._bg(lambda prog, canc: TF.trabajo_zooms(plan, prog, canc), listo, "Preparando zooms…")

    def _musica(self, music_id: str):
        n = TF.poner_musica(self.ctrl, music_id)
        if not n:
            self._siguiente()
            return
        self.aviso.emit("Música de fondo (baja sola cuando hablas)")
        m = self.ctrl.project.media.get(music_id)
        tid = self._pista()
        if m is None or tid is None or not self.ctrl.project.clips_on(tid):
            self._siguiente()
            return

        def listo(res):
            k = TF.cortes_a_ritmo(self.ctrl, music_id, res, tid)
            if k:
                self.aviso.emit(f"{k} cortes al ritmo de la música")
        self._bg(lambda prog, canc: TF.ritmo(m.path), listo, "Escuchando el ritmo de la música…")

    def _volumen(self):
        TF.poner_volumen(self.ctrl)
        self._siguiente()

    def _subs(self):
        TF.poner_subtitulos(self.ctrl, self._voz())
        self._siguiente()

    def _revision(self):
        _avisos, resumen = TF.revision(self.ctrl)
        self.aviso.emit("Revisión: " + resumen)
        self._siguiente()
