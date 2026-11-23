"""
✍ Deshacer por TRAMOS en el cuadro del texto de un clip (Inspector → Texto), como en un editor de texto normal.

Con un solo historial (el del proyecto), cada «Editar texto» se juntaba con el anterior si iba a menos de 3 s, y un
Ctrl+Z se llevaba todo lo escrito de golpe. Aquí se decide cuándo empieza un paso nuevo (ctrl.cortar_paso_texto):
  · se junta solo mientras escribes seguido (menos de 1 s entre teclas) dentro de la misma palabra o tramo;
  · corta al escribir un espacio o un signo tras una pausa, al pasar de escribir a borrar (Retroceso/Supr) o al revés,
    al mover el cursor (flechas, Inicio, Fin…), al hacer clic en el cuadro y al volver a él;
  · pegar o cortar (con teclas o con el menú del clic derecho) es siempre un paso propio.
Lo escrito y aún sin guardar (el temporizador de 350 ms del Inspector) se guarda en su tramo antes de cortar.
Solo afecta al texto de los clips: los demás pasos que se juntan (tamaño, color…) siguen igual.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer

ENTRE_TECLAS = 1.0      # s: más que esto sin escribir = paso nuevo
PAUSA = 0.35            # s: un espacio o un signo tras esta pausa = paso nuevo
TECLAS_BORRAR = (Qt.Key_Backspace, Qt.Key_Delete)
TECLAS_MOVER = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp,
                Qt.Key_PageDown)


def donde_cambio(viejo: str, nuevo: str) -> int:
    """La posición, en `nuevo`, donde termina lo que cambió respecto a `viejo` (para dejar ahí el cursor tras Deshacer
    o Rehacer): tras deshacer lo escrito, donde empezaba; tras rehacerlo, al final de lo escrito."""
    n = min(len(viejo), len(nuevo))
    p = 0
    while p < n and viejo[p] == nuevo[p]:
        p += 1
    s = 0
    while s < n - p and viejo[len(viejo) - 1 - s] == nuevo[len(nuevo) - 1 - s]:
        s += 1
    return max(p, len(nuevo) - s)


class TramosTexto(QObject):
    def __init__(self, ctrl, inspector):
        super().__init__(inspector)
        self.ctrl, self.ins = ctrl, inspector
        self.ed = inspector.text_edit
        self._clase = None             # «escribir» / «borrar»: la última tecla que cambió el texto
        self._t = 0.0                  # cuándo fue
        self._pendiente = True         # cortar antes de la próxima tecla (cursor movido, clic, foco nuevo…)
        self._previo = self.ed.toPlainText()
        self._por_tecla = False        # (el cambio que llega ahora lo hizo una tecla de escribir o borrar)
        self.ed.installEventFilter(self)
        self.ed.viewport().installEventFilter(self)
        self.ed.document().contentsChange.connect(self._al_cambiar)

    # ------------------------------------------------------------------
    def _guardar_pendiente(self, texto: str | None = None):
        """Lo escrito y aún sin guardar, a su paso (el que se está juntando)."""
        tm = self.ins._txt_timer
        if tm.isActive():
            tm.stop()
            self.ins._set_text(content=self.ed.toPlainText() if texto is None else texto)

    def cortar(self):
        """Lo de antes queda en su paso; lo próximo que se escriba empieza otro."""
        self._guardar_pendiente()
        self.ctrl.cortar_paso_texto()
        self._clase = None
        self._pendiente = False

    # ------------------------------------------------------------------
    def eventFilter(self, obj, ev):
        tipo = ev.type()
        if tipo == QEvent.MouseButtonPress and obj is self.ed.viewport():
            self._pendiente = True                     # (clic en otra parte del texto)
        elif tipo == QEvent.FocusIn and obj is self.ed:
            self._pendiente = True                     # (vuelves al cuadro: empiezas otra cosa)
        elif tipo == QEvent.KeyPress and obj is self.ed:
            self._tecla(ev)
        return False                                   # (nunca se queda la tecla: solo mira)

    def _tecla(self, ev):
        self._por_tecla = False                        # (Ctrl+V, Ctrl+X… no son teclas de escribir)
        k = ev.key()
        if k in TECLAS_MOVER:
            self._pendiente = True
            return
        txt = ev.text()
        mods = ev.modifiers()
        if mods & Qt.ControlModifier and not mods & Qt.AltModifier:
            return                                     # (Ctrl+V, Ctrl+X…: no escriben; AltGr = Ctrl+Alt sí)
        if k in TECLAS_BORRAR:
            clase, signo = "borrar", False
        elif txt and (txt.isprintable() or txt in ("\r", "\n", "\t")):
            clase, signo = "escribir", not txt.isalnum()
        else:
            return                                     # (Ctrl+…, Mayús sola, etc.: no cambian el tramo)
        self._por_tecla = True                         # (lo que cambie ahora lo hizo esta tecla)
        QTimer.singleShot(0, self._fin_tecla)
        ahora = time.monotonic()
        hueco = ahora - self._t
        if self._pendiente or clase != self._clase or hueco >= ENTRE_TECLAS or (signo and hueco >= PAUSA):
            self.cortar()
        self._clase, self._t = clase, ahora

    def _fin_tecla(self):
        self._por_tecla = False

    def _al_cambiar(self, _pos: int, _quitados: int, _puestos: int):
        """📋 Lo que cambia SIN una tecla de escribir o borrar (pegar o cortar con Ctrl+V/Ctrl+X o con el menú del clic
        derecho, una sugerencia del corrector…): siempre un paso propio."""
        ahora = self.ed.toPlainText()
        previo, self._previo = self._previo, ahora
        if self.ins._loading or ahora == previo or self._por_tecla:
            return                                     # (lo pone el Inspector, solo cambió el formato, o se tecleó)
        self._guardar_pendiente(previo)                # (lo de antes de pegar, a su paso)
        self.ctrl.cortar_paso_texto()
        self.ins._set_text(content=ahora)              # (lo pegado o cortado, en un paso propio)
        self.ins._txt_timer.stop()
        self.ctrl.cortar_paso_texto()
        self._clase = None
        self._pendiente = False
