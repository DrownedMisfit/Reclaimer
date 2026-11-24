"""
🧰 «MÁS HERRAMIENTAS» (24/11, la mudanza de la pestaña «IA»): sección plegable al final del panel de «Edita desde tu
voz» (en los 3 pasos), cerrada de entrada. Cada botón abre su bloque de siempre del panel de IA (ui/ai_panel.py: los
MISMOS QGroupBox, sin duplicar lógica) como pestaña del panel de herramientas; las dos que ya tienen su sitio (Limpieza
y Mezcla y música) abren ese sitio.

  seccion(win) -> QWidget              la sección (cabecera plegable + botones con icono y nombre)
  abrir(win, clave) -> QWidget | None  abre una herramienta (también la usan los menús y la barra de la línea de tiempo)
  HERRAMIENTAS                         (clave, título, corto, icono, tooltip)
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QPushButton, QToolButton, QVBoxLayout, QWidget

from . import diseno as D

HERRAMIENTAS = (
    ("voz", "Voz y limpieza automática", "Limpieza", "eraser",
     "Quitar silencios, muletillas y repeticiones de tu voz (Limpieza y mezcla → Limpieza)"),
    ("broll", "B-roll", "B-roll", "film",
     "La IA elige clips tuyos que encajan con lo que dices y los pone encima (el B-roll de siempre)"),
    ("audio", "Audio inteligente", "Audio", "audio-waveform",
     "Mejorar tu voz, bajar la música cuando hablas y cortes a ritmo (Limpieza y mezcla → Mezcla y música)"),
    ("director", "Modo Director", "Director", "wand-sparkles",
     "Escribe lo que quieres para una parte del video y la IA lo monta"),
    ("temas", "Temas de la narración", "Temas", "list-filter",
     "Divide tu narración en partes (historia, combate…); doble clic en una = ir ahí"),
    ("zooms", "Zooms y comparaciones", "Zooms", "zoom-in",
     "Zoom cuando dices «miren»; comparación cuando comparas"),
    ("autocompletar", "Autocompletar", "Autocompletar", "copy-plus",
     "Tapa lo que se ve vacío con lo que aún no usas de un video"),
    ("escenas", "Escenas sin usar", "Escenas", "layout-template",
     "Las escenas de tus videos que aún no salen en la línea de tiempo"),
)
CLAVE_ABIERTA = "edita_voz/mas_herramientas"


def _bloque(win, clave: str) -> QWidget | None:
    ap = getattr(win, "ai_panel", None)
    if ap is None:
        return None
    return {"broll": ap._groups.get("broll"), "director": ap._groups.get("director"),
            "temas": ap._groups.get("topics"), "zooms": ap._groups.get("visual"),
            "autocompletar": getattr(ap, "autocompletar", None),
            "escenas": getattr(ap, "unused_scenes", None)}.get(clave)


def _caja(win, clave: str) -> QWidget | None:
    """La pestaña de una herramienta: su bloque de siempre (sacado de la pestaña IA, que ya no se ve) con el progreso
    y el estado de la IA encima. Se crea una vez y se reutiliza."""
    ap = win.ai_panel
    cajas = ap.__dict__.setdefault("_cajas_herramientas", {})
    if clave in cajas:
        return cajas[clave]
    bloque = _bloque(win, clave)
    if bloque is None:
        return None
    caja = QWidget()
    caja.setObjectName(f"ia_{clave}")
    v = QVBoxLayout(caja)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(D.px(4))
    v.addWidget(bloque)                        # (sale de su página de la pestaña IA: es el mismo, no una copia)
    bloque.show()
    from .herramientas import _partir_textos
    _partir_textos(caja)                       # (en ~300 px: textos que parten línea y filas de botones que se parten)
    cajas[clave] = caja
    return caja


def abrir(win, clave: str) -> QWidget | None:
    """Abre la herramienta: Limpieza y Mezcla y música, en su sitio; las demás, como pestaña del panel de
    herramientas (con el estado y el progreso de la IA arriba)."""
    if clave == "voz":
        return win.abrir_seccion("audio", "limpieza")
    if clave == "audio":
        return win.abrir_seccion("audio", "mezcla")
    datos = next((h for h in HERRAMIENTAS if h[0] == clave), None)
    caja = _caja(win, clave)
    if datos is None or caja is None:
        return None
    ap = win.ai_panel
    lay = caja.layout()
    for i, w in enumerate((ap.progress, ap.status)):       # (el estado de la IA, en la que se ve)
        lay.insertWidget(i, w)
    ap.status.setWordWrap(True)
    _k, titulo, corto, icono, _tip = datos
    return win.herramientas.abrir("ia_" + clave, caja, titulo, corto, icono, conservar=True,
                                  trabajando=lambda: ap.job is not None)


class _Seccion(QWidget):
    """Cabecera plegable «Más herramientas» y los botones (icono + nombre; la explicación, en el tooltip)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("mas_herramientas")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, D.px(4), 0, 0)
        v.setSpacing(D.px(4))
        self.cab = QToolButton()
        self.cab.setText("Más herramientas")
        self.cab.setCheckable(True)
        self.cab.setAutoRaise(True)
        self.cab.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.cab.setToolTip("Lo que antes estaba en la pestaña IA: B-roll, Modo Director, Temas, Zooms, "
                            "Autocompletar, Escenas sin usar, Limpieza y Audio inteligente")
        v.addWidget(self.cab)
        self.cuerpo = D.FilaFluida(espacio=D.px(4))
        self.botones: dict[str, QPushButton] = {}
        c = D.colores()
        for clave, titulo, corto, icono, tip in HERRAMIENTAS:
            b = QPushButton(corto)
            b.setIcon(D.icono(icono, c["texto"], 14))
            b.setToolTip(f"{titulo}: {tip}")
            b.clicked.connect(lambda _=False, k=clave: abrir(self.win, k))
            self.cuerpo.addWidget(b)
            self.botones[clave] = b
        v.addWidget(self.cuerpo)
        abierta = str(QSettings("EditorIA", "EditorIA").value(CLAVE_ABIERTA, "false")).lower() == "true"
        self.cab.setChecked(abierta)
        self._plegar(abierta, guardar=False)
        self.cab.toggled.connect(self._plegar)

    def resizeEvent(self, ev):                   # noqa: N802
        super().resizeEvent(ev)
        self._alto_cuerpo()

    def _alto_cuerpo(self):
        """El alto de los botones a este ancho, también como mínimo: el panel de «Edita desde tu voz» pide su mínimo
        (su lista ya se desplaza) y así la sección abierta nunca queda cortada abajo."""
        alto = self.cuerpo.heightForWidth(max(1, self.width())) if self.cuerpo.isVisibleTo(self) else 0
        if self.cuerpo.minimumHeight() != alto:
            self.cuerpo.setMinimumHeight(alto)

    def _plegar(self, on: bool, guardar: bool = True):
        self.cab.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.cuerpo.setVisible(on)
        self._alto_cuerpo()
        if guardar:
            QSettings("EditorIA", "EditorIA").setValue(CLAVE_ABIERTA, "true" if on else "false")


def seccion(win) -> QWidget:
    return _Seccion(win)
