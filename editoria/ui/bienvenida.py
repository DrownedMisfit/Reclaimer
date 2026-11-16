"""
👋 Bienvenida: la primera vez que se abre Reclaimer (también justo después de instalarlo), como el pequeño lanzador de
muchas aplicaciones: qué viene ya incluido y qué es OPCIONAL (con su tamaño y un botón para instalarlo, sin consolas).
Se vuelve a abrir en Ayuda → «👋 Bienvenida y componentes…».
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

KEY = "bienvenida/vista_v1"


def toca_mostrar() -> bool:
    """¿Es la primera vez? (las pruebas no la enseñan)."""
    if os.environ.get("EDITORIA_DATOS") and not os.environ.get("RECLAIMER_BIENVENIDA_PRUEBA"):
        return False
    return str(QSettings("EditorIA", "EditorIA").value(KEY, "false")).lower() != "true"


def _tarjeta(titulo: str, texto: str, derecha=None) -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.StyledPanel)
    h = QHBoxLayout(f)
    v = QVBoxLayout()
    t = QLabel(f"<b>{titulo}</b>")
    d = QLabel(texto)
    d.setWordWrap(True)
    d.setObjectName("dim")
    v.addWidget(t)
    v.addWidget(d)
    h.addLayout(v, 1)
    if derecha is not None:
        h.addWidget(derecha, 0, Qt.AlignVCenter)
    return f


class Bienvenida(QDialog):
    _texto_motor = Signal(str)                    # (desde el hilo que mira la tarjeta: Qt lo pasa al hilo de la ventana)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Bienvenido a Reclaimer")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        hola = QLabel("<h2>👋 Bienvenido a Reclaimer</h2>Ya está todo listo para editar. Aquí tienes lo que viene "
                      "incluido y lo que puedes añadir cuando quieras.")
        hola.setWordWrap(True)
        lay.addWidget(hola)
        lay.addWidget(QLabel("<b>✓ Ya incluido</b>"))
        lay.addWidget(_tarjeta("Editor, FFmpeg y exportar",
                               "Línea de tiempo, efectos, subtítulos, eliminar silencios y exportar para YouTube, "
                               "TikTok o Windows. No hace falta instalar nada más."))
        lay.addWidget(_tarjeta("Ajuste fino de palabras",
                               "Para que los cortes no se coman principios ni finales de palabra."))
        lay.addWidget(QLabel("<b>＋ Opcional</b>"))
        self.b_motor = QPushButton("Instalar ahora")
        self.b_motor.setToolTip("Abre la instalación del motor de IA (sin consolas; puedes seguir usando Reclaimer "
                                "mientras descarga).")
        self.b_motor.clicked.connect(self._motor)
        self.motor_txt = ("Recortar sujetos, separar diálogos y transcribir con la tarjeta gráfica. Descarga entre 3 "
                          "y 6 GB según tu tarjeta.")
        self.t_motor = _tarjeta("◈ Motor de IA (tarjeta gráfica)", self.motor_txt, self.b_motor)
        lay.addWidget(self.t_motor)
        lay.addWidget(_tarjeta("🎙 Modelos de transcripción",
                               "Se descargan solos la primera vez que transcribes (de 0,5 a 3 GB según la precisión "
                               "que elijas). No tienes que hacer nada ahora."))
        self.no_mas = QCheckBox("No volver a mostrar al abrir")
        self.no_mas.setChecked(True)
        self.no_mas.setToolTip("Siempre puedes volver a verla en Ayuda → «👋 Bienvenida y componentes…».")
        fila = QHBoxLayout()
        fila.addWidget(self.no_mas)
        fila.addStretch(1)
        b = QPushButton("Empezar")
        b.setObjectName("primary")
        b.setDefault(True)
        b.clicked.connect(self.accept)
        fila.addWidget(b)
        lay.addLayout(fila)
        self._texto_motor.connect(self._poner_texto)
        self._estado_motor()

    def _estado_motor(self):
        """¿Ya está el motor? ¿Qué tarjeta hay? (en segundo plano: mirarlo tarda un par de segundos)."""
        from ..core import motor_ia
        if motor_ia.completo():
            self.b_motor.setText("✓ Instalado")
            self.b_motor.setEnabled(False)
            self._poner_texto("✓ Ya está instalado. " + self.motor_txt)
        elif motor_ia.PYTHON.exists():
            self.b_motor.setText("Continuar la instalación")
        if os.environ.get("EDITORIA_DATOS"):
            return                                         # (en pruebas no se mira la tarjeta)

        def mirar():
            try:
                st = motor_ia.status()
            except Exception:  # noqa: BLE001
                return
            nombre = {"nvidia": "NVIDIA", "amd": "AMD"}.get(st.get("vendor") or "", "")
            extra = f" Tu tarjeta: {nombre}." if nombre else " No veo tarjeta NVIDIA ni AMD: iría por el procesador."
            try:
                self._texto_motor.emit(("✓ Ya está instalado. " if st.get("completo") else "") + self.motor_txt
                                       + extra)
            except RuntimeError:                           # (la ventana ya se cerró)
                pass
        threading.Thread(target=mirar, daemon=True).start()

    def _poner_texto(self, texto: str):
        for lab in self.t_motor.findChildren(QLabel):
            if lab.objectName() == "dim":
                lab.setText(texto)

    def _motor(self):
        from ..core import motor_ia
        if hasattr(self.win, "abrir_motor_instalador"):    # (una sola instalación a la vez)
            self.win.abrir_motor_instalador(reparar=motor_ia.PYTHON.exists())
        else:
            from . import motor_install_dialog
            self.win._motor_dlg = motor_install_dialog.abrir(self.win, reparar=motor_ia.PYTHON.exists())
        self.accept()

    def done(self, r):
        if self.no_mas.isChecked():
            QSettings("EditorIA", "EditorIA").setValue(KEY, "true")
        super().done(r)


def abrir(win):
    d = Bienvenida(win)
    d.setAttribute(Qt.WA_DeleteOnClose)
    d.show()
    return d
