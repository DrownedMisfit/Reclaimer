"""
Barra flotante del texto elegido en el taller de miniaturas (como la barra de Canva): aparece encima del texto
(o debajo si no cabe), lo sigue al moverlo o hacer zoom, y ofrece lo de siempre a un clic: color, fuente, tamaño,
negrita, cursiva, contorno, sombra, brillo y «🔥 Mi estilo». Cada cambio es un paso de deshacer con su nombre.

No aparece si lo elegido no es texto, si está bloqueado, mientras se arrastra o con una herramienta activa.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import QFontDialog, QFrame, QHBoxLayout, QMenu, QPushButton

from ..core import thumbnail as T
from .common import pick_color

COLORES = [("Blanco", "#FFFFFF"), ("Negro", "#000000"), ("Amarillo", "#FFD400"), ("Rojo", T.MY_RED),
           ("Naranja", "#E8742F"), ("Azul", "#2F8CFF"), ("Verde", "#2ECC40"), ("Rosa", "#FF4FA3")]
FUENTES = ["Impact", "Anton", "Bahnschrift", "Arial Black", "Arial"]
GROSORES = (4, 8, 12, 16)
SOMBRAS = {
    "Suave": {"blur": 12, "dx": 4, "dy": 6, "opacity": 0.55},
    "Dura": {"blur": 0, "dx": 8, "dy": 8, "opacity": 0.9},
    "Larga": {"blur": 40, "dx": 10, "dy": 18, "opacity": 0.7},
}
_CLAVES_IMPACT = ("font", "size", "weight", "italic", "spacing", "align", "color", "uppercase", "line", "accent")

_ESTILO = ("QFrame#textBar { background: #22242a; border: 1px solid #43464e; border-radius: 7px; }"
           "QPushButton#tltool { padding: 2px 6px; min-height: 18px; }")


def _muestra(c: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(c))
    return QIcon(pm)


def _fuente_dialogo(actual: str, parent) -> str:
    """«Más fuentes…»: el diálogo de Windows. Devuelve la familia elegida o «» si se cancela."""
    f, ok = QFontDialog.getFont(QFont(actual), parent)
    return f.family() if ok else ""


def _color_dialogo(actual: str, parent) -> str:
    c = pick_color(actual, parent, "Color", alpha=False)
    return c.name() if c.isValid() else ""


class TextBar(QFrame):
    def __init__(self, editor):
        super().__init__(editor.canvas.viewport())
        self.editor = editor
        self.canvas = editor.canvas
        self.setObjectName("textBar")
        self.setStyleSheet(_ESTILO)
        self.setAttribute(Qt.WA_NoMousePropagation, True)     # clics en la barra no llegan al lienzo
        self._sig = None
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(3)

        # color de la fuente: muestra del color actual + menú de colores
        self.btn_color = self._menu_btn("", "Color de la letra: elige uno de estos o «Más colores…»")
        self.btn_color.setMenu(self._menu_colores(self.set_color, "color"))
        row.addWidget(self.btn_color)
        # fuente
        self.btn_fuente = self._boton("Fuente", "Fuente de la letra")
        self.btn_fuente.setMenu(self._menu_fuentes())
        row.addWidget(self.btn_fuente)
        # tamaño
        self.btn_menos = self._boton("A−", "Letra más pequeña (−10 %)", lambda: self.bump_size(-1))
        self.btn_mas = self._boton("A+", "Letra más grande (+10 %)", lambda: self.bump_size(1))
        row.addWidget(self.btn_menos)
        row.addWidget(self.btn_mas)
        # negrita y cursiva
        self.btn_b = self._boton("B", "Negrita", self.set_bold, checkable=True)
        self.btn_b.setStyleSheet("font-weight: 700;")
        self.btn_i = self._boton("I", "Cursiva", self.set_italic, checkable=True)
        self.btn_i.setStyleSheet("font-style: italic;")
        row.addWidget(self.btn_b)
        row.addWidget(self.btn_i)
        # alineación: izquierda / centrado / derecha (las líneas del texto entre sí)
        self.btn_align = {}
        for how, txt, tip in (("left", "⯇≡", "Alinear a la izquierda"), ("center", "≡", "Centrar"),
                              ("right", "≡⯈", "Alinear a la derecha")):
            b = self._boton(txt, tip, lambda _on=False, h=how: self.set_align(h), checkable=True)
            self.btn_align[how] = b
            row.addWidget(b)
        # contorno: interruptor + color + grosor
        self.btn_cont = self._boton("Contorno", "Contorno (borde) del texto: activar o quitar", self.set_outline_on,
                                    checkable=True)
        self.btn_cont_color = self._menu_btn("", "Color del contorno")
        self.btn_cont_color.setMenu(self._menu_colores(self.set_outline_color, "outline.color"))
        self.btn_cont_grosor = self._boton("Grosor", "Grosor del contorno")
        m = QMenu(self)
        for g in GROSORES:
            m.addAction(f"{g} px").triggered.connect(lambda _=False, g=g: self.set_outline_width(g))
        self.btn_cont_grosor.setMenu(m)
        row.addWidget(self.btn_cont)
        row.addWidget(self.btn_cont_color)
        row.addWidget(self.btn_cont_grosor)
        # sombra: interruptor + estilos
        self.btn_sombra = self._boton("Sombra", "Sombra: activar o quitar", self.set_shadow_on, checkable=True)
        self.btn_sombra_estilo = self._boton("▾", "Estilo de la sombra: suave, dura o larga")
        m = QMenu(self)
        for nombre in SOMBRAS:
            m.addAction(nombre).triggered.connect(lambda _=False, n=nombre: self.set_shadow_preset(n))
        m.addSeparator()
        m.addAction("Quitar sombra").triggered.connect(lambda: self.set_shadow_on(False))
        self.btn_sombra_estilo.setMenu(m)
        row.addWidget(self.btn_sombra)
        row.addWidget(self.btn_sombra_estilo)
        # brillo: interruptor + color
        self.btn_brillo = self._boton("Brillo", "Brillo (resplandor) alrededor del texto: activar o quitar",
                                      self.set_glow_on, checkable=True)
        self.btn_brillo_color = self._menu_btn("", "Color del brillo")
        self.btn_brillo_color.setMenu(self._menu_colores(self.set_glow_color, "glow.color"))
        row.addWidget(self.btn_brillo)
        row.addWidget(self.btn_brillo_color)
        # estilo de la casa
        self.btn_mi_estilo = self._boton("🔥 Mi estilo", "Aplica el estilo «Impact» (Anton, rojo, borde y resplandor) "
                                         "al texto elegido; conserva lo escrito y su sitio", self.apply_impact)
        row.addWidget(self.btn_mi_estilo)
        self.hide()

    # ------------------------------------------------------------ piezas
    def _boton(self, texto: str, tip: str, slot=None, checkable: bool = False) -> QPushButton:
        b = QPushButton(texto)
        b.setObjectName("tltool")
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    def _menu_btn(self, _texto: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("tltool")
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip)
        b.setFixedWidth(26)
        return b

    @staticmethod
    def _pinta(btn: QPushButton, c: str):
        btn.setStyleSheet(f"QPushButton#tltool {{ background: {c}; border: 1px solid #555; border-radius: 4px; }}")

    def _menu_colores(self, aplicar, campo: str) -> QMenu:
        """Menú de 8 colores rápidos + «Más colores…». campo: «color» o «outline.color» / «glow.color»."""
        m = QMenu(self)
        for nombre, hexc in COLORES:
            m.addAction(_muestra(hexc), nombre).triggered.connect(lambda _=False, c=hexc: aplicar(c))
        m.addSeparator()
        m.addAction("Más colores…").triggered.connect(lambda: self._mas_colores(aplicar, campo))
        return m

    def _menu_fuentes(self) -> QMenu:
        self._menu_font = QMenu(self)
        return self._menu_font

    def _rehacer_menu_fuentes(self, actual: str):
        m = self._menu_font
        m.clear()
        for fam in dict.fromkeys([actual] + FUENTES):         # la actual (si no está en la lista) va la primera
            m.addAction(fam).triggered.connect(lambda _=False, f=fam: self.set_font(f))
        m.addSeparator()
        m.addAction("Más fuentes…").triggered.connect(self._mas_fuentes)

    def _mas_colores(self, aplicar, campo: str):
        lay = self._target()
        if lay is None:
            return
        actual = lay
        for parte in campo.split("."):
            actual = actual.get(parte, {}) if isinstance(actual, dict) else {}
        c = _color_dialogo(actual if isinstance(actual, str) and actual else "#FFFFFF", self.canvas.window())
        if c:
            aplicar(c)

    def _mas_fuentes(self):
        lay = self._target()
        if lay is None:
            return
        fam = _fuente_dialogo(lay["font"], self.canvas.window())
        if fam:
            self.set_font(fam)

    # ------------------------------------------------------------ estado
    def _target(self) -> dict | None:
        lay = self.editor.cur()
        if lay is None or lay.get("kind") != "text":
            return None
        return lay

    def _apply(self, label: str, **kv):
        """Un cambio = un paso de deshacer con su nombre; repinta el lienzo y refresca el panel de propiedades."""
        lay = self._target()
        if lay is None or lay.get("locked"):
            return
        self.editor._set(lay, label, **kv)
        self.editor._fill_props()
        self.canvas.viewport().update()

    def set_color(self, c: str):
        self._apply("Color del texto", color=c)

    def set_font(self, fam: str):
        self._apply("Fuente", font=fam)

    def bump_size(self, sentido: int):
        lay = self._target()
        if lay is None:
            return
        s = float(lay["size"])
        n = round(s * 1.1) if sentido > 0 else round(s / 1.1)
        if n == s:                                  # (tamaños muy pequeños: que cambie al menos 1)
            n = int(s) + sentido
        n = max(8, min(600, int(n)))
        if n != int(s):
            self._apply("Tamaño", size=n)

    def set_bold(self, on: bool):
        self._apply("Negrita", weight=700 if on else 400)

    def set_italic(self, on: bool):
        self._apply("Cursiva", italic=bool(on))

    def set_align(self, how: str):
        lay = self._target()
        if lay is not None and lay.get("align", "center") != how:
            self._apply("Alineación", align=how)
        for h, b in self.btn_align.items():          # (como botones de radio: siempre uno marcado)
            b.setChecked(h == (self._target() or {}).get("align", "center"))

    def set_outline_on(self, on: bool):
        lay = self._target()
        if lay is not None:
            self._apply("Contorno", outline={**lay["outline"], "on": bool(on)})

    def set_outline_color(self, c: str):
        lay = self._target()
        if lay is not None:
            self._apply("Color del contorno", outline={**lay["outline"], "color": c, "on": True})

    def set_outline_width(self, w: int):
        lay = self._target()
        if lay is not None:
            self._apply("Grosor del contorno", outline={**lay["outline"], "width": int(w), "on": True})

    def set_shadow_on(self, on: bool):
        lay = self._target()
        if lay is not None:
            self._apply("Sombra", shadow={**lay["shadow"], "on": bool(on)})

    def set_shadow_preset(self, nombre: str):
        lay = self._target()
        if lay is not None:
            self._apply(f"Sombra ({nombre.lower()})", shadow={**lay["shadow"], **SOMBRAS[nombre], "on": True})

    def set_glow_on(self, on: bool):
        lay = self._target()
        if lay is not None:
            self._apply("Brillo", glow={**lay["glow"], "on": bool(on)})

    def set_glow_color(self, c: str):
        lay = self._target()
        if lay is not None:
            self._apply("Color del brillo", glow={**lay["glow"], "color": c, "on": True})

    def apply_impact(self):
        """🔥 Mi estilo: el preset «impact» de la casa, conservando el texto y su sitio (x, y)."""
        lay = self._target()
        if lay is None:
            return
        ref = T.text_layer(self.editor.doc, lay.get("text", ""), "impact")
        kv = {k: copy.deepcopy(ref[k]) for k in _CLAVES_IMPACT if k in ref}
        for k in ("outline", "glow", "shadow"):
            kv[k] = copy.deepcopy(ref[k])
        self._apply("Mi estilo", **kv)

    def _firma(self, lay: dict) -> tuple:
        return (lay["id"], lay.get("color"), lay.get("font"), lay.get("size"), lay.get("weight"),
                lay.get("italic"), lay.get("align"), repr(lay.get("outline")), repr(lay.get("shadow")),
                repr(lay.get("glow")))

    def _sincronizar(self, lay: dict):
        """Pone la barra como está el texto elegido (botones marcados, colores, fuente)."""
        self._pinta(self.btn_color, lay.get("color", "#FFFFFF"))
        self.btn_fuente.setText(f"{lay['font']} ▾")
        self._rehacer_menu_fuentes(lay["font"])
        self.btn_b.setChecked(int(lay.get("weight", 400)) >= 600)
        self.btn_i.setChecked(bool(lay.get("italic")))
        for h, b in self.btn_align.items():
            b.setChecked(h == lay.get("align", "center"))
        o, s, g = lay["outline"], lay["shadow"], lay["glow"]
        self.btn_cont.setChecked(bool(o.get("on")))
        self._pinta(self.btn_cont_color, o.get("color", "#000000"))
        self.btn_sombra.setChecked(bool(s.get("on")))
        self.btn_brillo.setChecked(bool(g.get("on")))
        self._pinta(self.btn_brillo_color, g.get("color", "#FF1E1E"))

    # ------------------------------------------------------------ posición
    def update_pos(self):
        """Se llama al repintar el lienzo (lo cubre todo: elegir, mover, zoom, desplazar, soltar)."""
        lay = self._target()
        vp = self.canvas.viewport()
        if (lay is None or lay.get("locked") or self.canvas.tool or self.canvas._drag is not None
                or vp.width() <= 0):
            self.hide()
            return
        firma = self._firma(lay)
        if firma != self._sig:
            self._sig = firma
            self._sincronizar(lay)
        r = self.canvas.mapFromScene(self.canvas._box(lay)).boundingRect()     # el recuadro del texto, en pantalla
        self.adjustSize()
        w, h = self.width(), self.height()
        x = r.center().x() - w / 2
        x = min(max(4, x), vp.width() - w - 4)
        y = r.top() - h - 8                                                    # encima del texto…
        if y < 4:
            y = r.bottom() + 8                                                 # …o debajo, si no cabe
        y = min(max(0, y), max(0, vp.height() - h))
        self.move(int(x), int(y))
        self.show()
        self.raise_()
