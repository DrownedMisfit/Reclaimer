"""
◈ Instalar (o reparar) el MOTOR DE IA desde Reclaimer, como cualquier aplicación: una ventana con barra de progreso,
el paso que va, «▸ Ver detalles» y «Cancelar». Nada de consolas negras ni PowerShell a la vista: el instalador
(motor_ia/instalar_motor.py) corre oculto (RECLAIMER_UI=1, sin ventana) y avisa de su progreso con líneas
«PASO n total texto» y «PROGRESO % MB MB», que aquí se convierten en la barra.

  abrir(win)  · la ventana (no bloquea: puedes seguir editando mientras descarga)
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QToolButton,
                               QVBoxLayout)

from ..core import motor_ia
from ..core.paths import PROGRAM_DIR

SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_para_instalar() -> str:
    """El Python que ejecuta el instalador: el de la versión «todo en uno» si es esa; si no, el del programa (su
    python.exe, no pythonw)."""
    portatil = PROGRAM_DIR.parent / "python" / "python.exe"
    if os.environ.get("RECLAIMER_PORTABLE") == "1" and portatil.is_file():
        return str(portatil)
    exe = sys.executable
    hermano = os.path.join(os.path.dirname(exe), "python.exe")
    return hermano if os.path.basename(exe).lower() == "pythonw.exe" and os.path.isfile(hermano) else exe


def orden_instalador() -> list[str]:
    return [python_para_instalar(), "-E", "-s", str(motor_ia.ROOT / "instalar_motor.py"), "--sin-pausa"]


def matar_arbol(pid: int):
    """Cancelar: el instalador y lo que haya lanzado (pip), sin abrir ninguna consola."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=SIN_VENTANA,
                       timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


class MotorInstallDialog(QDialog):
    def __init__(self, win, reparar: bool = False):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("◈ Motor de IA")
        self.setMinimumWidth(520)
        self._job = None
        self._pid = None
        self.ok = None
        lay = QVBoxLayout(self)
        que = QLabel("<b>Motor de IA (opcional)</b><br>Recortar sujetos (SAM 2.1), separar diálogos (Demucs) y "
                     "transcribir con la tarjeta gráfica. Reclaimer funciona sin esto.")
        que.setWordWrap(True)
        lay.addWidget(que)
        cuanto = QLabel("Descarga entre 3 y 6 GB según tu tarjeta (NVIDIA, AMD o solo el procesador).")
        cuanto.setObjectName("dim")
        cuanto.setWordWrap(True)
        lay.addWidget(cuanto)
        self.paso = QLabel("Listo para empezar." if not reparar else "Listo para reparar.")
        self.paso.setWordWrap(True)
        lay.addWidget(self.paso)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setValue(0)
        self.barra.setTextVisible(False)
        lay.addWidget(self.barra)
        self.detalle = QLabel("")
        self.detalle.setObjectName("dim")
        self.detalle.setWordWrap(True)
        lay.addWidget(self.detalle)
        self.b_ver = QToolButton()
        self.b_ver.setText("▸ Ver detalles")
        self.b_ver.setCheckable(True)
        self.b_ver.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.b_ver.toggled.connect(self._ver)
        lay.addWidget(self.b_ver)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setVisible(False)
        self.log.setMinimumHeight(160)
        lay.addWidget(self.log)
        fila = QHBoxLayout()
        fila.addStretch(1)
        self.b_cancelar = QPushButton("Cerrar")
        self.b_cancelar.clicked.connect(self._cancelar_o_cerrar)
        self.b_ir = QPushButton("Reparar" if reparar else "Instalar")
        self.b_ir.setObjectName("primary")
        self.b_ir.setToolTip("Descarga e instala lo que falte (lo que ya está no se repite). Puedes seguir editando "
                             "mientras tanto.")
        self.b_ir.clicked.connect(self.empezar)
        fila.addWidget(self.b_cancelar)
        fila.addWidget(self.b_ir)
        lay.addLayout(fila)
        self._paso_n, self._pasos = 0, 5
        self._log_timer = QTimer(self)                 # (lo que va escribiendo pip en instalar.log, como detalle)
        self._log_timer.setInterval(1500)
        self._log_timer.timeout.connect(self._ultima_del_log)

    def _ver(self, on: bool):
        self.b_ver.setText("▾ Ocultar detalles" if on else "▸ Ver detalles")
        self.log.setVisible(on)
        self.adjustSize()

    # ------------------------------------------------------------------ trabajo
    def empezar(self):
        if self._job is not None:
            return
        from .jobs import BackgroundJob
        self.b_ir.setEnabled(False)
        self.b_cancelar.setText("Cancelar")
        self.paso.setText("Empezando…")
        self.ok = None
        env = dict(os.environ, RECLAIMER_UI="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        orden = orden_instalador()

        def fn(progress, cancelled, partial):
            proc = subprocess.Popen(orden, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                    creationflags=SIN_VENTANA, cwd=str(motor_ia.ROOT))
            self._pid = proc.pid
            for linea in iter(proc.stdout.readline, b""):
                if cancelled():
                    matar_arbol(proc.pid)
                    break
                partial(linea.decode("utf-8", "replace").rstrip())
            proc.wait()
            return proc.returncode

        self._job = BackgroundJob(fn, parent=self, with_partial=True)
        self._job.title = "◈ Instalando el motor de IA"
        self._job.partial.connect(self._linea)
        self._job.done.connect(self._fin)
        self._job.failed.connect(lambda m: self._fin(None, m))
        self._job.start()
        self._log_timer.start()

    def _linea(self, linea: str):
        """Cada línea del instalador: los pasos y el progreso mueven la barra; lo demás, al registro."""
        if linea.startswith("PASO "):
            partes = linea.split(" ", 3)
            try:
                self._paso_n, self._pasos = int(partes[1]), max(1, int(partes[2]))
            except (IndexError, ValueError):
                return
            self.paso.setText(f"Paso {self._paso_n} de {self._pasos}: {partes[3] if len(partes) > 3 else ''}")
            self.barra.setValue(int((self._paso_n - 1) / self._pasos * 1000))
            return
        if linea.startswith("PROGRESO "):
            try:
                _p, pct, hecho, total = linea.split()
                frac = int(pct) / 100.0
            except ValueError:
                return
            base = (max(1, self._paso_n) - 1) / self._pasos
            self.barra.setValue(int((base + frac / self._pasos) * 1000))
            self.detalle.setText(f"Descargando… {pct} % ({hecho} de {total} MB)")
            return
        if linea.strip():
            self.log.appendPlainText(linea)
            if not linea.lstrip().startswith("$"):
                self.detalle.setText(linea.strip()[:160])

    def _ultima_del_log(self):
        """Mientras pip descarga (varios GB) no escribe aquí: se enseña lo último de instalar.log."""
        try:
            ruta = motor_ia.DATOS_MOTOR / "instalar.log"
            with open(ruta, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 4000))
                lineas = [x.strip() for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
        except OSError:
            return
        for x in reversed(lineas):
            if x.startswith(("Downloading", "Collecting", "Installing", "Successfully", "Requirement", "Building")):
                self.detalle.setText(x.replace("Downloading", "Descargando").replace("Collecting", "Buscando")
                                     .replace("Installing collected packages", "Instalando")
                                     .replace("Successfully installed", "✓ Instalado")[:160])
                return

    def _fin(self, codigo, error: str | None = None):
        self._job = None
        self._log_timer.stop()
        self.b_ir.setEnabled(True)
        self.b_cancelar.setText("Cerrar")
        if codigo == 0:
            self.ok = True
            self.barra.setValue(1000)
            self.paso.setText("✓ Listo: el motor de IA está instalado.")
            self.b_ir.setText("Reparar")
            ult = [x for x in self.log.toPlainText().splitlines() if x.startswith(("✓", "⚠"))]
            self.detalle.setText(ult[-1] if ult else "")
        else:
            self.ok = False
            self.paso.setText("✗ No se terminó de instalar." if error is None or "cancel" not in error.lower()
                              else "Cancelado.")
            self.detalle.setText((error or "Abre «▸ Ver detalles» para ver qué pasó. Puedes volver a intentarlo: lo "
                                  "que ya se bajó no se repite.")[:300])

    def _cancelar_o_cerrar(self):
        if self._job is None:
            self.reject()
            return
        self.paso.setText("Cancelando…")
        self._job.cancel()
        if self._pid:
            matar_arbol(self._pid)

    def done(self, r):
        if self._job is not None:                 # (cerrar mientras instala = cancelar)
            self._job.cancel()
            if self._pid:
                matar_arbol(self._pid)
        super().done(r)


def abrir(win, reparar: bool = False):
    d = MotorInstallDialog(win, reparar)
    d.setAttribute(Qt.WA_DeleteOnClose)
    d.show()
    return d
