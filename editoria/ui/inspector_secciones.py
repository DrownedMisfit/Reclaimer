"""
Inspector contextual (fase 2 de notas_claude/PROPUESTA_INTERFAZ.md): las piezas comunes.

  PESTANAS     las pestañas FIJAS del Inspector (las que no aplican a lo elegido salen apagadas, nunca desaparecen)
  Seccion      una sección plegable como en DaVinci: ● encender/apagar ese ajuste del clip (sin borrar sus valores),
               título (clic = abrir/cerrar, se recuerda) y ↺ restablecer la sección
  SPECS        qué guarda cada sección (atributos del clip, claves de fx, de la caja «layout» o del texto) para
               apagarla, encenderla o restablecerla: cambios_apagar / cambios_encender / cambios_restablecer
  apagada(c, clave)   ¿esa sección está apagada en el clip? (lo apagado se guarda en c.fx["apagado"][clave])

Apagar no borra nada: los valores se guardan en el propio clip y vuelven al encender (un Ctrl+Z por paso).
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget

# (clave, nombre visible, explicación en la ayuda emergente)
PESTANAS = [("video", "Video", "Cómo se ve el clip: transformar, recorte, encuadre, composición, velocidad, mejorar "
                               "imagen, seguimiento y color"),
            ("audio", "Audio", "Cómo suena el clip: volumen, balance, ecualizador y velocidad"),
            ("efectos", "Efectos", "Los efectos que lleva el clip: destello, fundidos, temblor y los de la página "
                                   "Efectos, cada uno con su interruptor"),
            ("transicion", "Transición", "La transición elegida en la línea de tiempo: tipo y duración"),
            ("texto", "Texto", "El texto en pantalla elegido: contenido, fuente, posición, trazo, sombra, fondo…"),
            ("archivo", "Archivo", "De dónde sale el clip, sus ajustes generales, la escena y la nota para la IA"),
            ("proyecto", "Proyecto", "El proyecto entero: formato, sonoridad, mezcla y música, narración y "
                                     "subtítulos")]
INDICE = {k: i for i, (k, _n, _t) in enumerate(PESTANAS)}

def acento_ahora() -> str:
    """El acento elegido AHORA (se puede cambiar en marcha: nunca se copia en una constante)."""
    from . import theme
    return getattr(theme, "ACCENT", "") or "#e8742f"
APAGADO = "apagado"         # c.fx["apagado"] = {clave de sección: lo que tenía antes de apagarla}
CLAVE_AJUSTES = "secciones/inspector2"

_LAYOUT_GEO = ("x", "y", "w", "h", "rot", "flip_h", "flip_v", "fit", "bg", "flip")

# ● / ↺ de cada sección. attrs = atributos del clip → valor de fábrica; off_attrs = lo que se pone al APAGAR (si no,
# el de fábrica); fx = claves de c.fx (apagar/restablecer = quitarlas); text = claves del texto (de fábrica:
# title_render.FACTORY; off_text = al apagar); layout_crop / layout_geo = el recorte / la posición y el tamaño.
SPECS: dict[str, dict] = {
    "transformar": {"layout_geo": True, "attrs": {"layout_kf": []}},
    "recorte": {"layout_crop": True},
    "encuadre": {"attrs": {"zoom_kf": []}},
    "composicion": {"attrs": {"opacity": 1.0, "op_kf": [], "blend": "normal"}},
    "mejorar": {"fx": ["denoise", "stab"]},
    "color": {"attrs": {"color": None}},
    "volumen": {"attrs": {"volume": 1.0, "pan": 0.0, "vol_kf": []}, "off_attrs": {"volume": 0.0}},
    "efectos_edits": {"fx": ["flash", "fade_in", "fade_out", "shake", "shake_amp", "lines", "focus_in"]},
    "texto_trazo": {"text": ["stroke_color", "stroke_size", "stroke_outside"], "off_text": {"stroke_size": 0}},
    "texto_desenfocar": {"text": ["blur_under"], "off_text": {"blur_under": 0.0}},
    "texto_animacion": {"text": ["fade"], "off_text": {"fade": 0.0}},
    "transicion": {"fx": ["trans"]},                 # (apagar = quitarla sin perderla)
    "sombra": {"fx": ["shadow"]},                    # 🌑 (apagar = quitarla sin perderla; ↺ y ● sin nada: inspector)
}


def spec_efecto(clave: str) -> dict:
    """La de un efecto de la página Efectos (con sus parámetros)."""
    from ..core import effects as EFX
    return {"fx": [clave, *EFX.PARAMS.get(clave, ())]}


def _spec(clave: str) -> dict:
    if clave.startswith("efecto:"):
        return spec_efecto(clave.split(":", 1)[1])
    return SPECS.get(clave, {})


def apagada(c, clave: str) -> bool:
    return bool(c is not None and clave in ((c.fx or {}).get(APAGADO) or {}))


def _fx_sin_apagado(fx: dict, clave: str) -> dict:
    ap = dict(fx.get(APAGADO) or {})
    ap.pop(clave, None)
    out = dict(fx)
    if ap:
        out[APAGADO] = ap
    else:
        out.pop(APAGADO, None)
    return out


def _layout_sin(c, quitar=(), poner: dict | None = None) -> dict | None:
    lay = dict(c.layout or {})
    for k in quitar:
        lay.pop(k, None)
    lay.update(poner or {})
    if not any(k in lay for k in ("x", "y", "w", "h")) and lay:
        lay = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, **lay}
    if set(lay) <= {"x", "y", "w", "h"} and (lay.get("x", 0), lay.get("y", 0), lay.get("w", 1), lay.get("h", 1)) \
            == (0.0, 0.0, 1.0, 1.0):
        return None
    return lay or None


def _de_fabrica_texto(keys) -> dict:
    from ..core.title_render import FACTORY
    return {k: FACTORY[k] for k in keys if k in FACTORY}


def _quitar_aplicado(c, spec: dict) -> dict:
    """Los cambios que dejan la sección como de fábrica (sin tocar lo de otras secciones)."""
    out: dict = {}
    fx = dict(c.fx or {})
    if spec.get("fx"):
        for k in spec["fx"]:
            fx.pop(k, None)
    for k, v in (spec.get("attrs") or {}).items():
        out[k] = copy.deepcopy(v)
    if spec.get("layout_crop"):
        out["layout"] = _layout_sin(c, quitar=("crop",))
    if spec.get("layout_geo"):
        crop = (c.layout or {}).get("crop")
        out["layout"] = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "crop": crop} if crop else None
    if spec.get("text") and c.text is not None:
        out["text"] = dict(c.text, **_de_fabrica_texto(spec["text"]))
    out["fx"] = fx
    return out


def cambios_apagar(c, clave: str) -> dict:
    """Props para set_clip_props que APAGAN la sección (guardando lo que tenía en c.fx["apagado"])."""
    spec = _spec(clave)
    if c is None or not spec or apagada(c, clave):
        return {}
    guardado: dict = {}
    fx0 = dict(c.fx or {})
    if spec.get("fx"):
        guardado["fx"] = {k: copy.deepcopy(fx0[k]) for k in spec["fx"] if k in fx0}
    if spec.get("attrs"):
        guardado["attrs"] = {k: copy.deepcopy(getattr(c, k)) for k in spec["attrs"]}
    if spec.get("layout_crop"):
        guardado["crop"] = copy.deepcopy((c.layout or {}).get("crop"))
    if spec.get("layout_geo"):
        lay0 = copy.deepcopy(c.layout)
        if lay0:
            lay0.pop("crop", None)
        guardado["layout"] = lay0 or None
    if spec.get("text") and c.text is not None:
        guardado["text"] = {k: copy.deepcopy(c.text.get(k)) for k in spec["text"] if k in c.text}
    out = _quitar_aplicado(c, spec)
    for k, v in (spec.get("off_attrs") or {}).items():
        out[k] = v
    if spec.get("off_text") and c.text is not None:
        out["text"] = dict(c.text, **spec["off_text"])
    fx = out["fx"]
    fx[APAGADO] = dict(fx.get(APAGADO) or {}, **{clave: guardado})
    out["fx"] = fx or None
    return out


def cambios_encender(c, clave: str) -> dict:
    """Props que vuelven a ENCENDER la sección con lo que tenía."""
    if c is None or not apagada(c, clave):
        return {}
    g = (c.fx or {})[APAGADO][clave] or {}
    fx = _fx_sin_apagado(dict(c.fx or {}), clave)
    fx.update(copy.deepcopy(g.get("fx") or {}))
    out: dict = dict(copy.deepcopy(g.get("attrs") or {}))
    if "crop" in g:
        out["layout"] = _layout_sin(c, poner={"crop": g["crop"]} if g["crop"] else None)
    if "layout" in g:
        crop = (c.layout or {}).get("crop")
        lay = dict(g["layout"] or {})
        lay.pop("crop", None)
        if crop:
            lay["crop"] = crop
            if not any(k in lay for k in ("x", "y", "w", "h")):
                lay.update(x=0.0, y=0.0, w=1.0, h=1.0)
        out["layout"] = lay or None
    if "text" in g and c.text is not None:
        out["text"] = dict(c.text, **g["text"])
    out["fx"] = fx or None
    return out


def cambios_restablecer(c, clave: str) -> dict:
    """Props que dejan la sección de fábrica (y encendida)."""
    spec = _spec(clave)
    if c is None or not spec:
        return {}
    out = _quitar_aplicado(c, spec)
    out["fx"] = _fx_sin_apagado(out["fx"], clave) or None
    return out


class _Espejo(QObject):
    """La sección se oculta cuando el código oculta lo que lleva dentro (y vuelve al mostrarlo)."""

    def __init__(self, sec, vigilado):
        super().__init__(sec)
        self.sec, self.w = sec, vigilado
        vigilado.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.w and ev.type() in (QEvent.HideToParent, QEvent.ShowToParent):
            self.sec.setVisible(not self.w.isHidden())
        return False


class Seccion(QWidget):
    """● (encender/apagar) · ▸ título (abrir/cerrar, se recuerda) · ↺ (restablecer). Misma forma que tabs.Section
    (head, body, is_open, set_open) para que lo de siempre siga funcionando."""
    encendida = Signal(bool)          # el usuario pulsó ●
    restablecer = Signal()            # el usuario pulsó ↺
    abierta = Signal(bool)

    def __init__(self, clave: str, titulo: str, body: QWidget, abierta: bool = False, interruptor: bool = False,
                 reinicio: bool = False, vigilar: QWidget | None = None, ayuda: str = ""):
        super().__init__()
        self.clave, self.body = clave, body
        self._key = f"{CLAVE_AJUSTES}/{clave}"
        v = QSettings("EditorIA", "EditorIA").value(self._key)
        if v is not None:
            abierta = str(v).lower() in ("true", "1")
        cab = QWidget()
        cab.setObjectName("seccion_cabecera")
        h = QHBoxLayout(cab)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.boton = BotonInterruptor()            # ●
        self.boton.toggled.connect(self._pulsado)
        self.head = QToolButton()
        self.head.setObjectName("sectionhead")
        self.head.setText(titulo)
        self.head.setCheckable(True)
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.head.setCursor(Qt.PointingHandCursor)
        from . import diseno as D                   # (🎨 LA cabecera de sección: 24 px; ● y ↺ dentro, a la derecha)
        D.cabecera_estandar(self.head, "QToolButton#sectionhead", derecha=52)   # (● ↺: escala sola)
        if ayuda:
            self.head.setToolTip(ayuda)
        self.head.toggled.connect(lambda on: self.set_open(on, save=True))
        self.btn_reset = QToolButton()
        from .diseno import icono                  # (icono monocromo en vez del símbolo ↺)
        self.btn_reset.setIcon(icono("rotate-ccw"))
        self.btn_reset.setAutoRaise(True)
        self.btn_reset.setFocusPolicy(Qt.NoFocus)
        D.medida(self.btn_reset, lambda w: w.setFixedWidth(D.px(22)))
        self.btn_reset.setToolTip(f"Restablecer «{titulo}»: sus valores de fábrica (Ctrl+Z lo deshace)")
        self.btn_reset.clicked.connect(self.restablecer.emit)
        h.addWidget(self.head, 1)
        dentro = QHBoxLayout(self.head)              # (● y ↺ dentro de la cabecera, a la derecha, con su tooltip)
        D.medida(self.head, lambda _w, l=dentro: (l.setContentsMargins(0, 0, D.px(4), 0), l.setSpacing(D.px(4))))
        dentro.addStretch(1)
        dentro.addWidget(self.boton)
        dentro.addWidget(self.btn_reset)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(cab)
        self._marco = QWidget()                      # (el contenido, con la sangría de sección: una sola rejilla)
        mv = D.fila_fija(QHBoxLayout(self._marco))   # (la sangría con un espacio fijo: responsive recorta los márgenes)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        D.espacio_sangria(mv)                        # (cede si no hay ancho; se rehace al cambiar «Letra»)
        mv.addWidget(body, 1)
        lay.addWidget(self._marco, 1)
        self.set_interruptor(interruptor)
        self.btn_reset.setVisible(reinicio)
        self.set_open(abierta, save=False)
        self._espejo = _Espejo(self, vigilar) if vigilar is not None else None
        if vigilar is not None and vigilar.isHidden():
            self.setVisible(False)

    # ---- abrir / cerrar
    def is_open(self) -> bool:
        return self.head.isChecked()

    def set_open(self, on: bool, save: bool = True):
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        if self.head.isChecked() != on:
            self.head.blockSignals(True)
            self.head.setChecked(on)
            self.head.blockSignals(False)
        cambia = self.body.isHidden() == on
        self.body.setVisible(on)
        marco = getattr(self, "_marco", None)
        if marco is not None and marco.isHidden() == on:
            marco.setVisible(on)
        if save:
            QSettings("EditorIA", "EditorIA").setValue(self._key, bool(on))
        if cambia:
            self.abierta.emit(on)

    # ---- ●
    def set_interruptor(self, aplica: bool):
        """aplica=False: la sección siempre está activa (● apagado, sin efecto)."""
        self._aplica = bool(aplica)
        self.boton.setEnabled(self._aplica)
        self.boton.setVisible(self._aplica)        # (si no se puede apagar, sin el punto gris suelto)
        nombre = self.head.text()
        self.boton.setToolTip(f"Encender / apagar «{nombre}» en lo elegido (apagar no borra sus valores)"
                              if self._aplica else f"«{nombre}» no se puede apagar: siempre está activa")

    def set_editable(self, editable: bool):
        """Clip bloqueado: ni ● ni ↺."""
        self.boton.setEnabled(bool(editable) and self._aplica)
        self.btn_reset.setEnabled(bool(editable))

    def set_on(self, on: bool):
        """Pone el ● sin avisar (al refrescar). Apagada = su contenido, sin tocar (gris)."""
        if self.boton.isChecked() != bool(on):
            self.boton.blockSignals(True)
            self.boton.setChecked(bool(on))
            self.boton.blockSignals(False)
        self.body.setEnabled(bool(on) or not self._aplica)

    def _pulsado(self, on: bool):
        self.body.setEnabled(bool(on) or not self._aplica)
        self.encendida.emit(bool(on))


from PySide6.QtWidgets import QTabWidget  # noqa: E402


# (20/11: una sola clase de pestañas ajustadas en todo el programa —también pone solo el icono cuando los nombres no
#  caben—; aquí se reexporta para quien la importe de este módulo)
from .paneles_agrupados import PestanasAjustadas  # noqa: E402,F401


def ajustar_a_pagina(tabs) -> None:
    """(se queda por si alguien la usa) Al cambiar de página, que el panel vuelva a medir."""
    tabs.currentChanged.connect(lambda _i: tabs.updateGeometry())


class _ConAcento:
    """(mezcla) Su hoja de estilo usa el acento del tema de AHORA: si cambia (el tema manda un cambio de estilo), se
    vuelve a poner."""
    _acento = None

    def _hoja(self, acento: str) -> str:
        return ""

    def _al_dia(self):
        a = acento_ahora()
        if a != self._acento:
            self._acento = a
            self.setStyleSheet(self._hoja(a))

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() in (QEvent.StyleChange, QEvent.PaletteChange):
            self._al_dia()

    def showEvent(self, ev):
        self._al_dia()
        super().showEvent(ev)


class BotonInterruptor(_ConAcento, QToolButton):
    """● de una sección: el acento cuando está encendida."""

    def __init__(self):
        super().__init__()
        self.setObjectName("seccion_interruptor")
        self.setText("●")
        self.setCheckable(True)
        self.setChecked(True)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedWidth(22)
        self._al_dia()

    def _hoja(self, a: str) -> str:
        return (f"QToolButton {{ color: #5a5d66; border: none; }} QToolButton:checked {{ color: {a}; }} "
                f"QToolButton:disabled {{ color: #34343a; }}")


class BotonPestana(_ConAcento, QPushButton):
    """Una pestaña fija del Inspector (botón con nombre; la elegida, subrayada con el acento)."""

    def __init__(self, texto: str):
        super().__init__(texto)
        self.setObjectName("pestana_inspector")
        self.setCheckable(True)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._al_dia()

    def _hoja(self, a: str) -> str:
        return (f"QPushButton {{ padding: 3px 4px; border: none; border-bottom: 2px solid transparent; }} "
                f"QPushButton:checked {{ border-bottom: 2px solid {a}; }} QPushButton:disabled {{ color: #5a5d66; }}")
