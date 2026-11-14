"""
Página «🧭 Montaje guiado»: los pasos de un montaje de principio a fin, en orden. Cada paso tiene un número,
un título, una línea de estado (se actualiza sola) y su botón. La explicación va en los tooltips.

Trabaja sobre el mismo proyecto que las demás páginas: no guarda nada propio.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import help as AYUDA
from .theme import ACCENT, TEXT_DIM

VERDE = "#7fd1ae"


class _Paso(QFrame):
    """Una fila: número · título + estado · botón(es)."""

    def __init__(self, numero: int, titulo: str, tip: str, parent=None):
        super().__init__(parent)
        self.setObjectName("guided_step")
        self.setFrameShape(QFrame.StyledPanel)
        self.setToolTip(tip)
        g = QGridLayout(self)
        g.setContentsMargins(10, 8, 10, 8)
        g.setHorizontalSpacing(10)
        self.num = QLabel(str(numero))
        self.num.setStyleSheet(f"font-size: 20pt; font-weight: 700; color: {ACCENT};")
        self.num.setMinimumWidth(30)
        self.num.setAlignment(Qt.AlignCenter)
        g.addWidget(self.num, 0, 0, 2, 1)
        fila = QHBoxLayout()
        self.titulo = QLabel(titulo)
        self.titulo.setStyleSheet("font-weight: 600;")
        fila.addWidget(self.titulo)
        self.hecho = QLabel("✓")
        self.hecho.setStyleSheet(f"color: {VERDE}; font-weight: 700;")
        self.hecho.setToolTip("Hecho")
        self.hecho.hide()
        fila.addWidget(self.hecho)
        fila.addStretch()
        g.addLayout(fila, 0, 1)
        self.estado = QLabel("")
        self.estado.setObjectName("dim")
        self.estado.setWordWrap(True)
        g.addWidget(self.estado, 1, 1)
        self.botones = QHBoxLayout()
        self.botones.setSpacing(4)
        g.addLayout(self.botones, 0, 2, 2, 1)
        g.setColumnStretch(1, 1)

    def boton(self, texto: str, tip: str, slot) -> QPushButton:
        b = QPushButton(texto)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        self.botones.addWidget(b)
        return b

    def poner(self, estado: str, hecho: bool):
        self.estado.setText(estado)
        self.estado.setVisible(bool(estado))
        self.hecho.setVisible(hecho)


class GuidedPanel(QWidget):
    """Lista de pasos del montaje. win = la ventana principal (se usan sus paneles y acciones)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctrl = win.ctrl
        self.setObjectName("guided")
        AYUDA.set_help(self, "montaje_guiado")
        self._hubo_cortes = False          # ya hubo cortes dudosos: un 0 posterior cuenta como «revisado»
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.p1 = _Paso(1, "🗂 Importar", "Trae tus archivos (narración, gameplay, música…) a Medios.")
        self.p1.boton("Abrir Medios", "Ve a la página Medios para importar o revisar tus archivos.",
                      lambda: win.go_page("media"))
        self.p2 = _Paso(2, "✂ Quitar silencios", "Quita los silencios y las pausas de la narración.")
        self.p2.boton("Eliminar silencio…", "Abre «✂ Eliminar silencio» (el mismo diálogo que el menú).",
                      win.open_silence)
        self.p3 = _Paso(3, "⚠ Revisar cortes dudosos",
                        "Cortes de audio que pueden haber comido una palabra (líneas rojas de la línea de tiempo).")
        self.b3_revisar = self.p3.boton("Revisar", "Abre el primer corte dudoso para revisarlo.",
                                        lambda: win._open_cut_issue(0))
        self.b3_todas = self.p3.boton("Aplicar todas", "Aplica la sugerencia de cada corte dudoso (un solo "
                                      "Ctrl+Z las deshace todas).", self._aplicar_todas)
        self.p4 = _Paso(4, "🎬 Clips para lo que dices",
                        "Lo que dices en la narración y el material que tienes para cada palabra.")
        self.p4.boton("Ver", "Muestra el panel 🎬 Clips.", lambda: win.show_panel(win.clips))
        self.p5 = _Paso(5, "✓ Revisión guiada", "Recorre con teclas solo lo dudoso: la voz, los cortes, los avisos y "
                        "el B-roll que la IA no tiene claro.")
        self.p5.boton("Empezar", "Abre la revisión guiada (Ctrl+Shift+Q).", lambda: win.open_quick_review())
        self.p6 = _Paso(6, "🖼 Miniatura", "Diseña la miniatura del video.")
        self.p6.boton("Abrir", "Ve a la página Miniatura.", lambda: win.go_page("thumb"))
        self.p7 = _Paso(7, "🚀 Entrega", "Exporta el video terminado.")
        self.p7.boton("Exportar", "Ve a la página Entrega (exportar).", lambda: win.go_page("deliver"))
        self.pasos = [self.p1, self.p2, self.p3, self.p4, self.p5, self.p6, self.p7]
        for p in self.pasos:
            lay.addWidget(p)
        lay.addStretch()

        # Se actualiza sola: al cambiar la línea de tiempo o el proyecto, y cada segundo (lo que cambia en
        # Clips o en la revisión rápida no tiene señal propia).
        win.timeline.cut_issues_changed.connect(self._actualizar)
        self.ctrl.project_changed.connect(self._actualizar)
        self.ctrl.project_replaced.connect(self._actualizar)
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(1000)
        self._temporizador.timeout.connect(self._actualizar)   # (solo corre mientras el panel se ve)
        self._actualizar(forzar=True)

    def showEvent(self, e):
        super().showEvent(e)
        self._temporizador.start()
        self._actualizar(forzar=True)

    def hideEvent(self, e):
        self._temporizador.stop()
        super().hideEvent(e)

    # ------------------------------------------------------------------ estado
    def _actualizar(self, *_a, forzar: bool = False):
        if not forzar and not self.isVisible():        # oculto: no gasta nada (se pone al día al mostrarse)
            return
        p = self.ctrl.project
        win = self.win

        n_med = len(p.media)
        self.p1.poner(f"{n_med} archivo{'s' if n_med != 1 else ''} en Medios", n_med > 0)

        voz = [t for t in p.tracks if getattr(t, "role", "") == "voz"]
        if voz:
            n_cl = sum(1 for c in p.clips.values() if c.track_id == voz[0].id)
            if n_cl >= 2:
                estado2 = f"Cortada ({n_cl - 1} cortes)"
            elif n_cl == 1:
                estado2 = "Narración sin cortar"
            else:
                estado2 = "Listo para cortar"
        else:
            estado2 = "Listo para cortar"
        self.p2.poner(estado2, False)

        n_cut = len(win.timeline.cut_issues)
        if n_cut:
            self._hubo_cortes = True
        if n_cut:
            estado3 = f"{n_cut} corte{'s' if n_cut != 1 else ''} dudoso{'s' if n_cut != 1 else ''}"
        else:
            estado3 = "✓ Ningún corte dudoso"
        self.p3.poner(estado3, n_cut == 0 and self._hubo_cortes)
        self.b3_revisar.setEnabled(n_cut > 0)
        self.b3_todas.setEnabled(n_cut > 0)

        if self.isVisible():                           # el panel Clips puede estar oculto con un recálculo pendiente
            win.clips.ensure_fresh()
        menciones = [m for m in (getattr(win.clips, "menciones", []) or []) if not m.get("no_dicha")]
        con_carpeta = sum(1 for m in menciones if win.clips._carpeta_de(m["term"]) is not None)
        n_pal = len(menciones)
        self.p4.poner(f"{n_pal} palabras · {con_carpeta} con carpeta",
                      n_pal > 0 and con_carpeta == n_pal)

        from .quick_review import pending_suggestions
        n_pend = len(pending_suggestions(p))
        self.p5.poner(f"{n_pend} propuesta{'s' if n_pend != 1 else ''} pendiente{'s' if n_pend != 1 else ''}", False)

        self.p6.poner("", False)
        self.p7.poner("", False)

    def _aplicar_todas(self):
        """La misma acción que «✓ Aplicar todas las sugerencias» del panel de cortes (sin mostrar ese panel)."""
        from .cut_fix import CutFixPanel
        if self.win.cut_fix is None:
            self.win.cut_fix = CutFixPanel(self.win)
        self.win.cut_fix._apply_all()
        self._actualizar()
