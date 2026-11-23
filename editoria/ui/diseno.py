"""
🎨 Sistema de diseño de Reclaimer (aspecto profesional, al estilo de DaVinci Resolve).

Una sola fuente de medidas, letras, colores e iconos para que todos los paneles se vean iguales:

  Medidas    ALTO_CONTROL (22) · ALTO_CAMPO (24) · ALTO_FILA (22) · ALTO_PRINCIPAL (26) · márgenes M1/M2/M3 (4/8/12)
             ANCHO_ETIQUETA (96, la columna de etiquetas del Inspector). Todo se multiplica por el tamaño de letra
             elegido en Ventana → Tamaño de letra (px()).
  Letras     LETRA_P / LETRA_M / LETRA_G (11 / 12 / 13 px) en Inter (OFL, assets/fuentes/interfaz: se carga la
             primera vez que se pide, no al arrancar) con cifras tabulares (los números no «bailan»). fuente(),
             poner_letra(). Por ahora solo en estos componentes: la letra general del programa sigue igual.
  Colores    colores(): los del tema y el acento DE AHORA (theme.ACCENT cambia en vivo con theme.poner_acento). Los
             componentes leen los colores al pintarse: al cambiar el acento, theme repinta todo y ya salen bien.
  Iconos     icono(nombre, color): SVG monocromos de Lucide (ISC, assets/iconos) teñidos del color que se pida.
  Profundidad fichas(): capas de gris calculadas desde el tema activo (fondo → bloques → controles → menús, como
             mucho 3 niveles a la vista), bisel de cabeceras, campos hundidos y degradados de botón;
             degradado_acento(): el del botón principal, calculado desde el acento elegido. qss_profundidad() es el
             bloque de la hoja general (theme.py lo añade al final) y qss_cabecera() el de las cabeceras plegables.
             Solo lo que flota lleva sombra (menús y tooltips: la sombra nativa de Windows; el clip que se arrastra:
             la pinta timeline.py). Listas, texto y tablas, planos.
  Escala     medida(w, fn): lo que depende del tamaño de letra se vuelve a aplicar con refrescar_escala() (Ventana →
             Tamaño de letra, al momento).

Componentes (reutilizables en todos los paneles):
  TituloSeccion   título de 11 px gris con una línea de 1 px encima y siempre el mismo margen
  FilaInspector   etiqueta gris en una columna fija + control
  ValorDeslizable deslizador fino de 2 px + número que se escribe o se arrastra («0,50 s»)
  TablaCasillas   filas con N columnas de casillas pequeñas (resalte suave al pasar el ratón)
  Casilla         casilla de 11 px apagada (solo la marcada lleva el acento) · CasillaTexto (con su texto)
  PuntoEstado     punto de 7 px: gris (nada) · ámbar (pendiente) · verde (listo)
  BotonIcono      botón pequeño de solo icono (siempre con tooltip)
  BotonPrincipal  EL botón de la acción principal: el único con el color de acento
  EtiquetaElidida texto de una línea que, si no cabe, acaba en «…» y se lee entero en el tooltip
  ListaAdaptable  lista (QListWidget) que reparte sus elementos en 1, 2 o 3 columnas según el ancho; los nombres se
                  parten en líneas (nunca se cortan); cabeceras de grupo plegables; recuerda su estado (QSettings)
  ColumnasEnlazadas  dos partes lado a lado, cada una con su barra, y 🔗 para desplazarlas juntas o por separado
  filas_compactas(vista)  filas de 22 px con la letra del diseño en una tabla o árbol
"""
from __future__ import annotations

import json
import weakref
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QBoxLayout, QCheckBox, QGridLayout, QHBoxLayout,
                               QLabel, QLayout,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import theme as T

def fila_fija(lay):
    """Una fila (QHBoxLayout) que responsive.py no debe partir en dos líneas: sus piezas ya se estrechan solas."""
    lay.setProperty("responsive_no_baja", True)
    return lay


class _RejillaFija(QGridLayout):
    """Rejilla cuyas columnas no se apilan en una sola (responsive.py deja tal cual las rejillas que cambian
    minimumSize): la tabla de casillas tiene que seguir siendo una tabla a cualquier ancho."""

    def minimumSize(self) -> QSize:            # noqa: N802
        return super().minimumSize()


# ------------------------------------------------------------------------------------------------ medidas (px a 100 %)
ALTO_CONTROL = 22        # deslizadores, botones pequeños
ALTO_CAMPO = 24          # filas etiqueta/campo
ALTO_FILA = 22           # filas de tablas
ALTO_PRINCIPAL = 26      # el botón principal
M1, M2, M3 = 4, 8, 12    # márgenes (siempre múltiplos de 4)
ANCHO_ETIQUETA = 96      # la columna fija de etiquetas
ANCHO_NUMERO, ALTO_NUMERO = 52, 20
ANCHO_COLUMNA = 52       # cada columna de casillas de TablaCasillas
CASILLA = 11
PUNTO = 7
LETRA_P, LETRA_M, LETRA_G = 11, 12, 13
GRIS_TITULO = "#8b8b92"
AMBAR, VERDE, GRIS_PUNTO = "#d6a24a", "#57ab5a", "#5b5e66"

FAMILIA_INTER = "Inter Variable"
FAMILIAS_SISTEMA = ["Segoe UI"]
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
DIR_ICONOS = _ASSETS / "iconos"
# (Inter va en una subcarpeta: theme.load_fonts NO la carga al arrancar; se carga la primera vez que un componente
#  del diseño pide su letra, y solo una vez)
ARCHIVO_INTER = _ASSETS / "fuentes" / "interfaz" / "InterVariable.ttf"
_inter: bool | None = None
_escala: float | None = None


def inter_disponible() -> bool:
    """Carga Inter (licencia OFL) la primera vez que se pide; False si no está (entonces, la letra del sistema)."""
    global _inter
    if _inter is None:
        from PySide6.QtGui import QFontDatabase
        _inter = ARCHIVO_INTER.is_file() and QFontDatabase.addApplicationFont(str(ARCHIVO_INTER)) >= 0
    return _inter


def familias() -> list[str]:
    return ([FAMILIA_INTER] if inter_disponible() else []) + FAMILIAS_SISTEMA


def escala() -> float:
    """El tamaño de letra de la interfaz (Ventana → Tamaño de letra): 1.0 = 100 %. Se lee una vez (refrescar_escala
    para volver a leerlo)."""
    global _escala
    if _escala is None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        pt = app.font().pointSizeF() if app is not None and app.styleSheet() else -1   # (con el tema puesto)
        if pt > 0:                              # (theme.apply_fonts pone la letra general a 9 pt × la escala: sin
            _escala = min(2.5, max(0.7, pt / 9.0))  #  leer QSettings otra vez)
        else:
            try:
                _escala = float(T.font_scales()[0])
            except Exception:  # noqa: BLE001  (sin ajustes legibles: 100 %)
                _escala = 1.0
    return _escala


_medidas: list = []          # [(weakref al control, fn)] lo que depende del tamaño de letra


def medida(w: QWidget, fn) -> QWidget:
    """Aplica fn(w) ahora y otra vez cada vez que cambie el tamaño de letra (refrescar_escala)."""
    fn(w)
    try:
        _medidas.append((weakref.ref(w), fn))
    except TypeError:
        pass
    return w


def refrescar_escala() -> None:
    """Ventana → Tamaño de letra: vuelve a leer la escala y rehace letras y medidas de los componentes vivos."""
    global _escala
    _escala = None
    _cache_pixmaps.clear()
    _cache_iconos.clear()
    vivos = []
    for ref, fn in _medidas:
        w = ref()
        if w is None:
            continue
        try:
            fn(w)
            w.updateGeometry()
            w.update()
        except RuntimeError:                    # (el control ya no existe)
            continue
        vivos.append((ref, fn))
    _medidas[:] = vivos


def px(n: float) -> int:
    """Una medida del diseño, en píxeles con el tamaño de letra elegido."""
    return max(1, int(round(n * escala())))


def colores() -> dict:
    """Los colores de ahora (tema + acento elegido). Léelos al pintar: el acento cambia en vivo."""
    return {
        "texto": T.TEXT, "tenue": T.TEXT_DIM, "apagado": T.TEXT_FAINT, "titulo": GRIS_TITULO,
        "fondo": T.BG, "campo": T.FIELD, "borde": T.BORDER, "borde_hi": T.BORDER_HI,
        "relieve": T.RAISED, "relieve_hi": T.RAISED_HI,
        "acento": T.ACCENT, "acento_hi": T.ACCENT_HI, "acento_pulsado": T.ACCENT_PRESS, "sobre_acento": T.ACCENT_ON,
        "acento_off": T.ACCENT_OFF, "acento_off_texto": T.ACCENT_OFF_TXT,
        "ambar": AMBAR, "verde": VERDE, "gris_punto": GRIS_PUNTO,
    }


# ------------------------------------------------------------------------------------------------ profundidad
PROFUNDIDAD = True           # (False = el aspecto plano de antes: para comparar y medir)


def fichas() -> dict:
    """Las capas de gris de ahora, calculadas desde el fondo del tema activo con los saltos de la maqueta aprobada
    (con el tema «Oscuro» salen casi sus valores: #1c1c1e → #222225 → controles #2c2c30–#37373c → menús #313136)."""
    bg = T.BG
    def claro(t):
        return T.mezcla(bg, "#ffffff", t)

    def oscuro(t):
        return T.mezcla(bg, "#000000", t)
    return {
        "fondo": bg,
        "bloque": claro(0.026), "bloque_borde": oscuro(0.25), "bloque_luz": "rgba(255,255,255,0.03)",
        "control_arriba": claro(0.12), "control_abajo": claro(0.07), "control_borde": oscuro(0.29),
        "control_luz": "rgba(255,255,255,0.07)", "control_hover_arriba": claro(0.155),
        "control_hover_abajo": claro(0.105), "control_pulsado": claro(0.035),
        "menu": claro(0.093), "menu_borde": oscuro(0.3),
        "cab_arriba": claro(0.088), "cab_abajo": claro(0.053), "cab_hover_arriba": claro(0.115),
        "cab_hover_abajo": claro(0.08), "bisel_luz": "rgba(255,255,255,0.06)", "bisel_sombra": oscuro(0.36),
        "campo": oscuro(0.21), "campo_borde": claro(0.044), "campo_borde_inf": claro(0.123),
        "campo_sombra": oscuro(0.45),
    }


def degradado_acento(acento: str | None = None) -> dict:
    """El degradado del botón principal desde el acento elegido (con «Acero»: #dfe5ec → #a7b2bf, borde #6f7a88)."""
    a = acento or T.ACCENT
    claro = T.luminancia(a) >= 0.31
    arriba = T.mezcla(a, "#ffffff", 0.68 if claro else 0.22)
    abajo = T.mezcla(a, "#ffffff", 0.15) if claro else T.mezcla(a, "#000000", 0.06)
    return {
        "arriba": arriba, "abajo": abajo, "borde": T.mezcla(a, "#000000", 0.27 if claro else 0.32),
        "luz": "rgba(255,255,255,0.35)" if claro else "rgba(255,255,255,0.22)",
        "hover_arriba": T.mezcla(arriba, "#ffffff", 0.25), "hover_abajo": T.mezcla(abajo, "#ffffff", 0.12),
        "pulsado": T.mezcla(abajo, "#000000", 0.1),
    }


def gradiente(arriba: str, abajo: str, luz: str | None = None) -> str:
    """Un degradado vertical para una hoja de estilo (con una línea de luz arriba si se pide)."""
    if luz:
        return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {luz}, stop:0.06 {arriba}, "
                f"stop:1 {abajo})")
    return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {arriba}, stop:1 {abajo})"


MARCA_QSS = "/* profundidad (ui/diseno.py) */"


def qss_profundidad() -> str:
    """El bloque de «profundidad sutil» para la hoja general (lo añade theme.py al final): botones con relieve, campos
    hundidos, menús y tooltips un escalón más claros, bloques con su línea de luz y cabeceras con bisel."""
    if not PROFUNDIDAD:
        return qss_compacto()
    f = fichas()
    a = degradado_acento()
    # (con un acento de luz la línea de arriba se mezcla con él: para el degradado hace falta un color opaco)
    luz_c = T.mezcla(f["control_arriba"], "#ffffff", 0.08)
    luz_a = T.mezcla(a["arriba"], "#ffffff", 0.3)
    return f"""
{MARCA_QSS}
QPushButton {{ background: {gradiente(f["control_arriba"], f["control_abajo"], luz_c)};
    border: 1px solid {f["control_borde"]}; }}
QPushButton:hover:!checked {{ background: {gradiente(f["control_hover_arriba"], f["control_hover_abajo"], luz_c)};
    border-color: {f["control_borde"]}; }}
QPushButton:pressed:!checked {{ background: {f["control_pulsado"]}; padding-top: 4px/*s:bp*/;
    padding-bottom: 2px/*s:bm*/; }}
QPushButton#primary {{ background: {gradiente(a["arriba"], a["abajo"], luz_a)}; border: 1px solid {a["borde"]}; }}
QPushButton#primary:hover {{ background: {gradiente(a["hover_arriba"], a["hover_abajo"], luz_a)};
    border-color: {a["borde"]}; }}
QPushButton#primary:pressed {{ background: {a["pulsado"]}; padding-top: 4px/*s:bp*/;
    padding-bottom: 2px/*s:bm*/; }}
QComboBox:!editable {{ background: {gradiente(f["control_arriba"], f["control_abajo"], luz_c)};
    border: 1px solid {f["control_borde"]}; }}
QComboBox:!editable:hover {{ background: {gradiente(f["control_hover_arriba"], f["control_hover_abajo"], luz_c)}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox:editable {{ background: {f["campo"]};
    border: 1px solid {f["campo_borde"]}; border-top-color: {f["campo_sombra"]};
    border-bottom-color: {f["campo_borde_inf"]}; }}
QMenu {{ background: {f["menu"]}; border: 1px solid {f["menu_borde"]}; }}
QToolTip {{ background: {f["menu"]}; border: 1px solid {f["menu_borde"]}; }}
QComboBox QAbstractItemView {{ background: {f["menu"]}; border: 1px solid {f["menu_borde"]}; }}
QGroupBox {{ background: {gradiente(f["bloque"], f["bloque"], T.mezcla(f["bloque"], "#ffffff", 0.03))};
    border: 1px solid {f["bloque_borde"]}; }}
QDockWidget::title {{ background: {gradiente(f["cab_arriba"], f["cab_abajo"])}; padding-top: 2px;
    border-top: 1px solid {f["bisel_luz"]}; border-bottom: 1px solid {f["bisel_sombra"]}; }}
QWidget#panelheader {{ background: {gradiente(f["cab_arriba"], f["cab_abajo"])};
    border-top: 1px solid {f["bisel_luz"]}; border-bottom: 1px solid {f["bisel_sombra"]}; }}
QPushButton:checked {{ background: {T.acento_rgba(0.15)}; border-color: {T.acento_rgba(0.75)};
    color: {T.ACCENT_TINTE}; }}
QPushButton:checked:hover {{ background: {T.acento_rgba(0.24)}; border-color: {T.acento_rgba(0.9)}; }}
QPushButton:checked:disabled {{ background: {T.BG}; border-color: {T.BORDER}; color: {T.TEXT_FAINT}; }}
QComboBox:hover {{ border-color: {T.BORDER_HI}; }}
QComboBox:focus {{ border-color: {T.acento_rgba(0.8)}; }}
""" + qss_compacto()


def qss_compacto() -> str:
    """Los controles con el alto fijo del diseño (alto_fijo) van SIN el relleno vertical de la hoja general: con 24 px,
    5 px de relleno arriba y abajo y el borde solo quedaban 12 px para una letra de 16 («Agregar» se leía «Aqreqar»).
    Al pulsarlos bajan 1 px (como los demás), sin volver a comerse el alto."""
    return """
QPushButton[compacto="true"], QComboBox[compacto="true"], QSpinBox[compacto="true"],
QDoubleSpinBox[compacto="true"], QLineEdit[compacto="true"] { padding-top: 0px; padding-bottom: 0px; }
QPushButton[compacto="true"]:pressed:!checked, QPushButton#primary[compacto="true"]:pressed {
    padding-top: 1px; padding-bottom: 0px; }
"""


def alto_fijo(w: QWidget, alto: float = ALTO_CAMPO) -> QWidget:
    """El alto fijo del diseño (24 px por defecto, con la escala de «Letra») para un control con TEXTO —botón,
    desplegable, caja numérica, campo— sin cortarle la letra a lo alto: quita su relleno vertical (qss_compacto).
    Úsalo en vez de setFixedHeight(px(ALTO_CAMPO)) en cualquier control que lleve texto."""
    if not w.property("compacto"):
        w.setProperty("compacto", True)
        st = w.style()
        if st is not None:                        # (si ya estaba pulido con la hoja general: que relea la regla)
            st.unpolish(w)
            st.polish(w)
    return medida(w, lambda x: x.setFixedHeight(px(alto)))


def color_cabecera() -> str:
    """El texto de las cabeceras plegables (del tema activo: claro, sin llegar al blanco)."""
    return T.mezcla(T.TEXT, T.BG, 0.08)


_cabeceras: list = []        # [(weakref, selector, extra)] para rehacerlas con el tema o el acento


def poner_cabecera(w: QWidget, selector: str, extra="") -> QWidget:
    """Pone la hoja de cabecera a w y la recuerda: rehacer_cabeceras() la vuelve a calcular en vivo. extra puede ser
    una función (las medidas con la escala de «Letra» de ese momento)."""
    w.setStyleSheet(qss_cabecera(selector, extra))
    try:
        _cabeceras.append((weakref.ref(w), selector, extra))
    except TypeError:
        pass
    return w


_hojas: list = []             # [(weakref, fn)] hojas propias que llevan el acento (poner_hoja)


def poner_hoja(w: QWidget, fn) -> QWidget:
    """Pone a w la hoja de estilo fn() y la rehace con el acento o el tema nuevos (rehacer_cabeceras): para las hojas
    propias que llevan el color de acento (p. ej. el subrayado de la pestaña activa de arriba)."""
    w.setStyleSheet(fn())
    try:
        _hojas.append((weakref.ref(w), fn))
    except TypeError:
        pass
    return w


def rehacer_cabeceras() -> None:
    """Tras cambiar de tema o de acento: las cabeceras (y las hojas de poner_hoja) con los colores nuevos."""
    vivas_h = []
    for ref, fn in _hojas:
        w = ref()
        if w is None:
            continue
        try:
            w.setStyleSheet(fn())
        except RuntimeError:
            continue
        vivas_h.append((ref, fn))
    _hojas[:] = vivas_h
    vivas = []
    for ref, selector, extra in _cabeceras:
        w = ref()
        if w is None:
            continue
        try:
            w.setStyleSheet(qss_cabecera(selector, extra))
        except RuntimeError:
            continue
        vivas.append((ref, selector, extra))
    _cabeceras[:] = vivas


def qss_cabecera(selector: str, extra: str = "") -> str:
    """La hoja de una cabecera plegable (acordeón, secciones): degradado mínimo y bisel de 1 px; al pulsar, un tono
    más oscura. extra = sus medidas y su letra (padding, alineación…), o una función que las da. El color del texto
    sale del tema."""
    if callable(extra):
        extra = extra()
    f = fichas()
    extra = f"color: {color_cabecera()}; " + extra
    if not PROFUNDIDAD:
        return f"{selector} {{ background: {f['cab_abajo']}; border: none; {extra} }}"
    return (f"{selector} {{ background: {gradiente(f['cab_arriba'], f['cab_abajo'])}; border: none; "
            f"border-top: 1px solid {f['bisel_luz']}; border-bottom: 1px solid {f['bisel_sombra']}; {extra} }}"
            f"{selector}:hover {{ background: {gradiente(f['cab_hover_arriba'], f['cab_hover_abajo'])}; }}"
            f"{selector}:pressed {{ background: {f['cab_abajo']}; }}")


def grupo_sin_titulo(g: QWidget) -> QWidget:
    """Un recuadro (QGroupBox) que ya va dentro de su sección: sin título, sin marco y SIN el hueco que la hoja general
    reserva para el título (margin-top 14 + padding 10: el hueco de 30–45 px tras cada cabecera abierta)."""
    g.setProperty("sin_titulo", True)
    regla = 'QGroupBox[sin_titulo="true"] { margin-top: 0px; padding: 0px; border: none; }'
    if regla not in (g.styleSheet() or ""):
        g.setStyleSheet(((g.styleSheet() or "") + " " + regla).strip())
    return g


ALTO_CABECERA = 24       # (20/11) TODAS las cabeceras plegables: acordeón, secciones, Inspector
SANGRIA_SECCION = 8      # el contenido de cada sección, con esta sangría bajo su cabecera (una sola rejilla)


def cabecera_estandar(boton: QWidget, selector: str, derecha: int = 0) -> QWidget:
    """LA cabecera de sección del programa: 24 px de alto, el mismo relleno, la misma letra (negrita media) y el bisel
    común. derecha = lo reservado a la derecha para lo que va dentro (● ↺), en medidas del DISEÑO (se escala con
    «Letra», como el alto y el relleno: se rehacen al cambiarla). La jerarquía se marca con sangría."""
    def extra():
        return (f"border-radius: 3px; padding: 0px {px(derecha) if derecha else px(M2)}px 0px {px(6)}px; "
                f"text-align: left; font-weight: 600;")
    poner_cabecera(boton, selector, extra)
    medida(boton, lambda w: (w.setFixedHeight(px(ALTO_CABECERA)), w.setStyleSheet(qss_cabecera(selector, extra))))
    return boton


class _Sangria(QWidget):
    """El hueco de la sangría de sección: pide SANGRIA_SECCION × «Letra» de ancho y cede hasta 0 si no hay sitio. Es un
    QWidget (no un QSpacerItem creado desde Python: esos dejaban envoltorios de QLayoutItem vivos —test_sin_cierres_
    listas—); no recibe el ratón (los clics van a lo de debajo, como antes)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(px(SANGRIA_SECCION), 0)

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(0, 0)


def espacio_sangria(lay) -> None:
    """Añade a `lay` (horizontal) la sangría de sección (SANGRIA_SECCION, cede si no hay ancho) y la rehace con la
    escala de «Letra» (refrescar_escala vuelve a medir el hueco: su sizeHint ya lee la escala de ahora)."""
    hueco = _Sangria()
    lay.addWidget(hueco)
    medida(hueco, lambda _w: None)


def _pintar_relieve(p: QPainter, r: QRectF, arriba: str, abajo: str, borde: str, luz: str, radio: float = 3.0):
    """Un botón con relieve pintado a mano: degradado, borde y línea de luz arriba (sin efectos gráficos: barato)."""
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, QColor(arriba))
    g.setColorAt(1.0, QColor(abajo))
    p.setPen(QPen(QColor(borde), 1))
    p.setBrush(g)
    p.drawRoundedRect(r, radio, radio)
    c = QColor(luz) if not luz.startswith("rgba") else _rgba(luz)
    p.setPen(QPen(c, 1))
    p.drawLine(QPointF(r.left() + radio, r.top() + 1), QPointF(r.right() - radio, r.top() + 1))


def _rgba(txt: str) -> QColor:
    r, g, b, a = (x.strip() for x in txt[txt.index("(") + 1:txt.index(")")].split(","))
    return QColor(int(r), int(g), int(b), int(float(a) * 255))


def fuente(tam: int = LETRA_M, peso: int | QFont.Weight = QFont.Normal, tabular: bool = False) -> QFont:
    """Inter (si está cargada; si no, la del sistema) al tamaño del diseño. tabular = cifras de ancho fijo."""
    f = QFont()
    f.setFamilies(familias())
    f.setPixelSize(px(tam))
    f.setWeight(QFont.Weight(peso) if isinstance(peso, int) else peso)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError):      # (Qt < 6.7: sin cifras tabulares, pero funciona)
            pass
    return f


def poner_letra(w: QWidget, tam: int = LETRA_M, color: str | None = None, peso=QFont.Normal,
                tabular: bool = False, extra: str = "") -> QWidget:
    """Letra del diseño en un control con texto (la hoja de estilo general fija 9 pt: aquí manda la nuestra)."""
    def aplicar(x):
        x.setFont(fuente(tam, peso, tabular))
        x.setStyleSheet(f"font-size: {px(tam)}px;" + (f" color: {color};" if color else "") + extra)
    return medida(w, aplicar)


# ------------------------------------------------------------------------------------------------ iconos
_cache_iconos: dict = {}
_cache_pixmaps: dict = {}
_cache_svg: dict = {}


def icono(nombre: str, color: str | None = None, tam: int = 16) -> QIcon:
    """Un icono SVG monocromo de assets/iconos (Lucide), teñido de «color» (por defecto, el del texto tenue)."""
    color = color or T.TEXT_DIM
    clave = (nombre, color, tam)
    ic = _cache_iconos.get(clave)
    if ic is not None:
        return ic
    ic = QIcon(pixmap_icono(nombre, color, tam))
    _cache_iconos[clave] = ic
    return ic


def pixmap_icono(nombre: str, color: str, tam: int) -> QPixmap:
    """El icono pintado a doble resolución (nítido con escala de pantalla). Cada color se pinta una sola vez."""
    clave = (nombre, color, tam)
    pm = _cache_pixmaps.get(clave)
    if pm is not None:
        return pm
    pm = QPixmap(tam * 2, tam * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    _cache_pixmaps[clave] = pm
    texto = _cache_svg.get(nombre)
    if texto is None:
        try:
            texto = (DIR_ICONOS / f"{nombre}.svg").read_text(encoding="utf-8")
        except OSError:
            texto = ""
        _cache_svg[nombre] = texto
    if not texto:
        return pm
    from PySide6.QtSvg import QSvgRenderer          # (al pintar el primer icono, no al importar)
    r = QSvgRenderer(texto.replace("currentColor", color).encode("utf-8"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, tam, tam))
    p.end()
    return pm


def _mezcla(a: str, b: str, t: float) -> QColor:
    return QColor(T.mezcla(a, b, t))


# ------------------------------------------------------------------------------------------------ textos
class TituloSeccion(QLabel):
    """Título de sección: 11 px, gris, con una línea de 1 px encima y siempre el mismo margen."""

    def __init__(self, texto: str, parent=None, sangria: int = 0):
        super().__init__(texto, parent)
        self.setObjectName("titulo_seccion")
        self.setWordWrap(True)
        medida(self, lambda w: (w.setFont(fuente(LETRA_P, QFont.DemiBold)),
                                w.setContentsMargins(px(sangria) if sangria else 0, px(M3) - 4, 0, px(M1)),
                                w.setStyleSheet(f"font-size: {px(LETRA_P)}px; color: {GRIS_TITULO};")))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setPen(QPen(QColor(T.BORDER), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()
        super().paintEvent(ev)


class EtiquetaElidida(QLabel):
    """Una línea de texto: si no cabe acaba en «…» y el texto entero sale en el tooltip."""

    def __init__(self, texto: str = "", parent=None):
        super().__init__(parent)
        self._completo = ""
        self._tip_extra = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        medida(self, lambda w: (w.setMinimumWidth(px(24)), w._elidir() if hasattr(w, "_completo") else None))
        self.setProperty("responsive_una_linea", True)     # (responsive.py no la parte en líneas: ya acorta)
        self.setText(texto)

    def setText(self, texto: str):            # noqa: N802  (API de Qt)
        self._completo = texto or ""
        self._elidir()

    def texto_completo(self) -> str:           # (text() es lo que se ve; esto, el texto entero)
        return self._completo

    def poner_tooltip_extra(self, extra: str):
        self._tip_extra = extra or ""
        self._elidir()

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(px(24), super().minimumSizeHint().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elidir()

    def _elidir(self):
        fm = QFontMetrics(self.font())
        visible = fm.elidedText(self._completo, Qt.ElideRight, max(8, self.width() - 2))
        QLabel.setText(self, visible)
        tip = self._completo if visible != self._completo else ""
        if self._tip_extra:
            tip = (tip + "\n" if tip else "") + self._tip_extra
        self.setToolTip(tip)


def etiqueta(texto: str, tam: int = LETRA_P, color: str | None = None, ajustar: bool = True) -> QLabel:
    """Etiqueta del diseño (gris, 11 px por defecto) que se parte en varias líneas si no cabe."""
    lb = QLabel(texto)
    lb.setWordWrap(ajustar)
    poner_letra(lb, tam, color or T.TEXT_DIM)
    return lb


def _palabra_mas_ancha(texto: str, letra: QFont) -> int:
    fm = QFontMetrics(letra)
    return max((fm.horizontalAdvance(w) for w in texto.split()), default=0)


class _EtiquetaFila(QLabel):
    """La etiqueta de una FilaInspector: mide ANCHO_ETIQUETA si hay sitio; en un panel muy estrecho se estrecha
    (hasta su palabra más ancha) y el texto se parte en líneas: nunca se corta."""

    def __init__(self, texto: str):
        super().__init__(texto)
        self.setWordWrap(True)
        poner_letra(self, LETRA_P, T.TEXT_DIM)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        medida(self, lambda w: w.setMaximumWidth(px(ANCHO_ETIQUETA)))

    def _minimo(self) -> int:
        m = self.contentsMargins()
        return min(px(ANCHO_ETIQUETA), _palabra_mas_ancha(self.text(), self.font()) + m.left() + m.right() + 2)

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(px(ANCHO_ETIQUETA), max(px(ALTO_CAMPO), self.heightForWidth(px(ANCHO_ETIQUETA))))

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(self._minimo(), px(ALTO_CAMPO))


class FilaInspector(QWidget):
    """Fila etiqueta/control: la etiqueta, gris, en una columna de ANCHO_ETIQUETA a la izquierda (más estrecha solo
    si el panel no da para más); el control ocupa el resto. Si ni así caben los dos, la etiqueta pasa ENCIMA del
    control (como los formularios de responsive.py): la fila nunca pide más ancho que el mayor de los dos."""

    def __init__(self, texto: str, control: QWidget, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.etiqueta = _EtiquetaFila(texto)
        self.etiqueta.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        medida(self.etiqueta, lambda w: (w.setMinimumHeight(px(ALTO_CAMPO)),
                                         w.setContentsMargins(px(M1), 0, 0, 0)))   # (la sangría de las tablas)
        self.control = control
        lay = fila_fija(QHBoxLayout(self))
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSizeConstraint(QLayout.SetNoConstraint)   # (el mínimo lo dice minimumSizeHint: el apilado)
        lay.addWidget(self.etiqueta)
        lay.addWidget(control, 1)
        self._lay = lay
        medida(self, lambda w: (lay.setSpacing(px(M2)), w.setMinimumHeight(px(ALTO_CAMPO))))
        if tooltip:
            self.etiqueta.setToolTip(tooltip)
            if not control.toolTip():
                control.setToolTip(tooltip)

    def _min_control(self) -> int:
        c = self.control
        return max(c.minimumSizeHint().width(), c.minimumWidth())

    def _ancho_en_fila(self) -> int:
        return self.etiqueta._minimo() + self._lay.spacing() + self._min_control()

    def apilada(self) -> bool:
        return self._lay.direction() == QBoxLayout.TopToBottom

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(max(self.etiqueta._minimo(), self._min_control()), px(ALTO_CAMPO))

    def hasHeightForWidth(self) -> bool:       # noqa: N802
        return True

    def _alto_control(self, w: int) -> int:
        c = self.control
        h = c.heightForWidth(w) if c.hasHeightForWidth() else -1
        return max(h, c.sizeHint().height(), c.minimumHeight())

    def heightForWidth(self, w: int) -> int:   # noqa: N802
        if w >= self._ancho_en_fila():
            ae = min(px(ANCHO_ETIQUETA), max(self.etiqueta._minimo(), w - self._lay.spacing() - self._min_control()))
            return max(px(ALTO_CAMPO), self.etiqueta.heightForWidth(ae),
                       self._alto_control(max(1, w - ae - self._lay.spacing())))
        return self.etiqueta.heightForWidth(w) + self._lay.spacing() + self._alto_control(w)

    def resizeEvent(self, ev):                 # noqa: N802
        super().resizeEvent(ev)
        d = QBoxLayout.LeftToRight if ev.size().width() >= self._ancho_en_fila() else QBoxLayout.TopToBottom
        if self._lay.direction() != d:
            self._lay.setDirection(d)
            self.updateGeometry()


def campo_texto(placeholder: str = "", tooltip: str = "") -> QLineEdit:
    """Campo de texto de 24 px con la letra del diseño."""
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setToolTip(tooltip)
    return medida(e, lambda w: (w.setFixedHeight(px(ALTO_CAMPO)), w.setFont(fuente(LETRA_M)),
                                w.setStyleSheet(f"QLineEdit {{ font-size: {px(LETRA_M)}px; padding: 0 {px(M1)}px; }}")))


# ------------------------------------------------------------------------------------------------ valor deslizable
_TECLAS_PASO = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown)


class _DeslizadorFino(QWidget):
    """Pista de 2 px con un tirador pequeño (sin acento: sobrio). Clic o arrastre = valor; flechas = un paso
    (con Mayús, un décimo de paso)."""
    movido = Signal(float)                    # 0–1
    paso = Signal(float)                      # pasos (±1, o ±0,1 con Mayús)
    empieza = Signal()                        # (botón pulsado: empieza un arrastre)
    termina = Signal()                        # (botón suelto)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self._encima = False
        self.setFocusPolicy(Qt.StrongFocus)
        medida(self, lambda w: (w.setMinimumWidth(px(20)), w.setFixedHeight(px(ALTO_CONTROL))))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def event(self, ev):
        # (con el foco aquí, las flechas son del deslizador: no las atajos de la línea de tiempo)
        if ev.type() == QEvent.ShortcutOverride and ev.key() in _TECLAS_PASO:
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in _TECLAS_PASO:
            n = 1.0 if k in (Qt.Key_Right, Qt.Key_Up, Qt.Key_PageUp) else -1.0
            if k in (Qt.Key_PageUp, Qt.Key_PageDown):
                n *= 10
            elif ev.modifiers() & Qt.ShiftModifier:
                n *= 0.1
            self.paso.emit(n)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def poner(self, frac: float):
        self._frac = min(1.0, max(0.0, frac))
        self.update()

    def _desde_x(self, x: float):
        r = px(4)
        self.poner((x - r) / max(1.0, self.width() - 2 * r))
        self.movido.emit(self._frac)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.empieza.emit()
            self._desde_x(ev.position().x())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self._desde_x(ev.position().x())

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.termina.emit()
        super().mouseReleaseEvent(ev)

    def enterEvent(self, ev):
        self._encima = True
        self.update()

    def leaveEvent(self, ev):
        self._encima = False
        self.update()

    def paintEvent(self, _ev):
        c = colores()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = px(4)
        y = self.height() / 2
        x0, x1 = r, self.width() - r
        xh = x0 + (x1 - x0) * self._frac
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["borde_hi"]))
        p.drawRoundedRect(QRectF(x0, y - 1, x1 - x0, 2), 1, 1)
        p.setBrush(QColor(c["tenue"] if self.isEnabled() else c["borde_hi"]))
        p.drawRoundedRect(QRectF(x0, y - 1, xh - x0, 2), 1, 1)
        claro = "#ffffff" if (self._encima or self.hasFocus()) else c["texto"]
        p.setBrush(QColor(claro if self.isEnabled() else c["apagado"]))
        p.drawEllipse(QPointF(xh, y), r, r)
        p.end()


class _CampoNumero(QLineEdit):
    """El número: se escribe (clic) o se arrastra a izquierda/derecha (Mayús = más fino)."""
    arrastrado = Signal(float)                # pasos (positivos o negativos)
    escrito = Signal(str)
    empieza = Signal()                        # (empieza a arrastrarse a los lados)
    termina = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inicio = None
        self._arrastra = False
        self._acumulado = 0.0
        self._minimo = px(ANCHO_NUMERO)
        self._texto_ancho = ""
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        medida(self, _CampoNumero._aplicar)
        self.setCursor(Qt.SizeHorCursor)
        self.editingFinished.connect(lambda: self.escrito.emit(self.text()))

    def _aplicar(self):
        """Medidas, letra y aspecto (hundido: fondo oscuro, sombra arriba y luz abajo)."""
        self.setFixedHeight(px(ALTO_NUMERO))
        if not getattr(self, "_libre", False):      # (sin deslizador, el número ocupa todo su sitio)
            self.setMaximumWidth(px(ANCHO_NUMERO))
        self.setFont(fuente(LETRA_P, tabular=True))
        c, f = colores(), fichas()
        if PROFUNDIDAD:
            borde = (f"border: 1px solid {f['campo_borde']}; border-top-color: {f['campo_sombra']};"
                     f" border-bottom-color: {f['campo_borde_inf']};")
            fondo = f["campo"]
        else:
            borde, fondo = f"border: 1px solid {c['borde']};", c["campo"]
        self.setStyleSheet(
            f"QLineEdit {{ font-size: {px(LETRA_P)}px; background: {fondo}; color: {c['texto']};"
            f" {borde} border-radius: 3px; padding: 0 3px; }}"
            f" QLineEdit:hover {{ border-color: {c['borde_hi']}; }}"
            f" QLineEdit:focus {{ border-color: {c['apagado']}; }}")
        if self._texto_ancho:
            self.medir_para(self._texto_ancho)

    def medir_para(self, texto_mas_ancho: str):
        """El ancho mínimo: el número más ancho que puede salir, entero (en un panel estrecho, menos de 52 px)."""
        self._texto_ancho = texto_mas_ancho
        necesita = QFontMetrics(self.font()).horizontalAdvance(texto_mas_ancho) + 12
        self._minimo = necesita                 # (el texto más ancho siempre entero: nunca «justado» por «Ajustado»)
        self._ancho = max(px(ANCHO_NUMERO), necesita)
        if not getattr(self, "_libre", False):
            self.setMaximumWidth(self._ancho)
        self.updateGeometry()

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(getattr(self, "_ancho", px(ANCHO_NUMERO)), px(ALTO_NUMERO))

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(self._minimo, px(ALTO_NUMERO))

    def mousePressEvent(self, ev):
        if self.hasFocus() or ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        self._inicio = ev.position().x()
        self._arrastra = False
        self._acumulado = 0.0

    def mouseMoveEvent(self, ev):
        if self._inicio is None or self.hasFocus():
            super().mouseMoveEvent(ev)
            return
        dx = ev.position().x() - self._inicio
        if not self._arrastra and abs(dx) < 3:
            return
        if not self._arrastra:
            self.empieza.emit()
        self._arrastra = True
        por_paso = 16.0 if ev.modifiers() & Qt.ShiftModifier else 4.0
        pasos = int(dx / por_paso)
        if pasos:
            self._inicio += pasos * por_paso
            self.arrastrado.emit(float(pasos))

    def mouseReleaseEvent(self, ev):
        if self._inicio is not None and not self.hasFocus():
            arrastro = self._arrastra
            self._inicio = None
            self._arrastra = False
            if arrastro:
                self.termina.emit()
            if not arrastro:                    # un clic sin arrastrar: escribir el número
                self.setFocus(Qt.MouseFocusReason)
                self.selectAll()
            return
        super().mouseReleaseEvent(ev)

    def event(self, ev):
        if ev.type() == QEvent.ShortcutOverride and ev.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Escape):
            ev.accept()                          # (↑/↓ = un paso; Esc = deshacer lo escrito: no los atajos)
            return True
        return super().event(ev)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.setCursor(Qt.IBeamCursor)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.setCursor(Qt.SizeHorCursor)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.escrito.emit("")               # (vuelve a poner el valor de antes)
            self.clearFocus()
            return
        if ev.key() in (Qt.Key_Up, Qt.Key_Down):
            self.arrastrado.emit(1.0 if ev.key() == Qt.Key_Up else -1.0)
            return
        super().keyPressEvent(ev)


def QApplication_mouse_pulsado() -> bool:   # noqa: N802
    from PySide6.QtWidgets import QApplication
    return bool(QApplication.mouseButtons() & Qt.LeftButton)


class ValorDeslizable(QWidget):
    """Deslizador fino + número editable con su unidad y coma decimal («0,50 s»). Se usa como un QDoubleSpinBox
    (value(), setValue(), setRange(), valueChanged…) o como un QSpinBox (entero=True: value() y valueChanged dan
    enteros). También setSuffix/setDecimals/setSingleStep/setSpecialValueText/selectAll, para cambiar un control viejo
    por este sin tocar lo demás.
      factor      el número se enseña dividido entre factor (p. ej. el valor 40 con factor 100 = «0,40»)
      deslizador  False = solo el número (que se escribe o se arrastra): para rangos enormes (posiciones en px…)"""
    valueChanged = Signal(object)
    arrastre = Signal(bool)                   # True al empezar a arrastrar (deslizador o número), False al soltar
    antes_de_cambiar = Signal()               # (arrastrando, justo antes de valueChanged: para juntar los pasos)

    def __init__(self, minimo: float, maximo: float, paso: float = 0.1, decimales: int = 2, unidad: str = "",
                 parent=None, factor: float = 1.0, deslizador: bool = True, entero: bool = False,
                 formato=None, signo: bool = False):
        super().__init__(parent)
        self._min, self._max, self._paso, self._dec, self._unidad = minimo, maximo, paso, decimales, unidad
        self._factor, self._entero = float(factor or 1.0), bool(entero)
        self._formato, self._signo = formato, bool(signo)   # (formato(valor) → texto propio; signo = «+0,40»)
        self._prefijo = ""
        self._especial = ""
        self._especial_max = ""
        self._arrastrando = False
        self._valor = minimo
        self.deslizador = _DeslizadorFino()
        self.campo = _CampoNumero()
        lay = fila_fija(QHBoxLayout(self))
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.deslizador, 1)
        lay.addWidget(self.campo, 0 if deslizador else 1)
        if not deslizador:
            self.deslizador.hide()
            self.campo._libre = True
            self.campo.setMaximumWidth(16777215)
            self.campo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusProxy(self.campo)          # (setFocus/hasFocus: el número)
        medida(self, lambda w: (lay.setSpacing(px(M2)), w.setMinimumHeight(px(ALTO_CAMPO))))
        self.deslizador.movido.connect(self._desde_deslizador)
        self.deslizador.paso.connect(lambda n: self.setValue(self._valor + n * self._paso))
        self.campo.arrastrado.connect(lambda pasos: self.setValue(self._valor + pasos * self._paso))
        self.campo.escrito.connect(self._desde_texto)
        for w in (self.deslizador, self.campo):
            w.empieza.connect(lambda: self._poner_arrastre(True))
            w.termina.connect(lambda: self._poner_arrastre(False))
        self.campo.installEventFilter(self)
        self.deslizador.installEventFilter(self)
        self._medir()
        self._pintar()

    # ---- arrastre (deslizador o número): un solo paso de deshacer lo decide quien lo usa
    def arrastrando(self) -> bool:
        return self._arrastrando

    def _poner_arrastre(self, on: bool):
        if on != self._arrastrando:
            self._arrastrando = on
            self.arrastre.emit(on)

    def eventFilter(self, obj, ev):           # noqa: N802
        t = ev.type()
        if t == QEvent.Wheel and self.campo.hasFocus() and self.underMouse():
            # 🖱 rueda con el foco puesto y el ratón encima (como los QSpinBox con theme._WheelGuard): un paso por
            # muesca (Mayús = un décimo). Sin foco o con el ratón fuera, la rueda desplaza el panel.
            d = ev.angleDelta().y() or ev.angleDelta().x()
            if d:
                n = (1.0 if d > 0 else -1.0) * (0.1 if ev.modifiers() & Qt.ShiftModifier else 1.0)
                self.setValue(self._valor + n * self._paso)
            ev.accept()
            return True
        if self._arrastrando and (t == QEvent.Hide or (t == QEvent.FocusOut and not QApplication_mouse_pulsado())):
            # (por si el botón se soltó fuera: nunca queda un arrastre abierto. Oculto, se cierra SIEMPRE: un control
            # que no se ve no puede seguir arrastrándose, aunque el botón siga pulsado)
            self._poner_arrastre(False)
        return super().eventFilter(obj, ev)

    # ---- como QDoubleSpinBox / QSpinBox
    def value(self):
        return int(round(self._valor)) if self._entero else self._valor

    def _redondear(self, v: float) -> float:
        if self._entero:
            return float(round(v))
        extra = len(str(int(self._factor))) - 1 if self._factor >= 1 else 0
        return round(v, self._dec + extra)

    def setValue(self, v):                     # noqa: N802
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = self._valor
        v = self._redondear(min(self._max, max(self._min, v)))
        cambio = abs(v - self._valor) > 1e-9
        if cambio and self._arrastrando:
            self.antes_de_cambiar.emit()
        self._valor = v
        self._pintar()
        if cambio:
            self.valueChanged.emit(int(round(v)) if self._entero else v)

    def setRange(self, minimo: float, maximo: float):   # noqa: N802
        self._min, self._max = minimo, maximo
        self._medir()
        self.setValue(self._valor)

    def setMinimum(self, v: float):            # noqa: N802
        self.setRange(v, self._max)

    def setMaximum(self, v: float):            # noqa: N802
        self.setRange(self._min, v)

    def _medir(self):
        muestras = [self.texto(self._min), self.texto(self._max)]
        if self._formato is not None:          # (con un formato propio, el más ancho puede estar en medio)
            muestras += [self.texto(self._min + (self._max - self._min) * f) for f in (0.15, 0.35, 0.65, 0.85)]
        self.campo.medir_para(max(muestras, key=lambda t: self.campo.fontMetrics().horizontalAdvance(t)))

    def setSingleStep(self, paso: float):      # noqa: N802
        self._paso = paso

    def singleStep(self) -> float:             # noqa: N802
        return self._paso

    def setDecimals(self, n: int):             # noqa: N802
        self._dec = int(n)
        self._medir()
        self._pintar()

    def decimals(self) -> int:
        return self._dec

    def setSuffix(self, sufijo: str):          # noqa: N802
        self._unidad = (sufijo or "").strip()
        self._medir()
        self._pintar()

    def suffix(self) -> str:
        return self._unidad

    def setPrefix(self, prefijo: str):         # noqa: N802
        self._prefijo = prefijo or ""
        self._medir()
        self._pintar()

    def setSpecialValueText(self, t: str):     # noqa: N802  (lo que se ve en el mínimo, p. ej. «—»)
        self._especial = t or ""
        self._medir()
        self._pintar()

    def poner_texto_maximo(self, t: str):      # (lo que se ve en el máximo, p. ej. «Toda la pantalla»)
        self._especial_max = t or ""
        self._medir()
        self._pintar()

    def setKeyboardTracking(self, _on: bool):  # noqa: N802  (el número se aplica al terminar de escribir)
        pass

    def setButtonSymbols(self, *_a):           # noqa: N802
        pass

    def setAccelerated(self, *_a):             # noqa: N802
        pass

    def selectAll(self):                       # noqa: N802
        self.campo.selectAll()

    def lineEdit(self):                        # noqa: N802
        return self.campo

    def minimum(self) -> float:
        return self._min

    def maximum(self) -> float:
        return self._max

    def setToolTip(self, tip: str):            # noqa: N802  (el tooltip, también en sus partes)
        super().setToolTip(tip)
        self.deslizador.setToolTip(tip)
        self.campo.setToolTip(tip)

    # ---- texto
    def texto(self, v: float | None = None) -> str:
        v = self._valor if v is None else v
        if self._especial and abs(v - self._min) < 1e-9:
            return self._especial
        if self._especial_max and abs(v - self._max) < 1e-9:
            return self._especial_max
        if self._formato is not None:
            return self._formato(int(round(v)) if self._entero else v)
        t = f"{v / self._factor:{'+' if self._signo else ''}.{self._dec}f}".replace(".", ",")
        if self._signo and abs(v) < 1e-9:
            t = t.lstrip("+")
        t = self._prefijo + t
        return f"{t} {self._unidad}" if self._unidad else t

    def _leer_formato(self, limpio: str) -> float:
        """Un texto que no es un número: el especial del mínimo o del máximo, o el formato propio (I30 / C / D30)."""
        if self._especial and limpio == self._especial.strip():
            return self._min
        if self._especial_max and limpio == self._especial_max.strip():
            return self._max
        if self._formato is not None:
            for k in range(int(self._min), int(self._max) + 1):
                if self._formato(k).replace(" ", "").lower() == limpio.replace(" ", "").lower():
                    return float(k)
        return self._valor

    def _pintar(self):
        if not self.campo.hasFocus():
            self.campo.setText(self.texto())
        span = self._max - self._min
        self.deslizador.poner((self._valor - self._min) / span if span > 0 else 0.0)

    def _desde_deslizador(self, frac: float):
        v = self._min + frac * (self._max - self._min)
        self.setValue(round(v / self._paso) * self._paso if self._paso > 0 else v)

    def _desde_texto(self, t: str):
        limpio = (t or "")
        for quitar in (self._unidad, self._prefijo):
            if quitar:
                limpio = limpio.replace(quitar, "")
        limpio = limpio.replace(",", ".").strip()
        try:
            v = float(limpio) * self._factor
        except ValueError:
            v = self._leer_formato(limpio)
        self.campo.clearFocus()
        self.setValue(v)
        self.campo.setText(self.texto())


# ------------------------------------------------------------------------------------------------ casillas
def _pintar_casilla(p: QPainter, caja: QRectF, marcada: bool, encima: bool, activa: bool):
    c = colores()
    p.setRenderHint(QPainter.Antialiasing)
    if marcada and activa:
        p.setPen(QPen(QColor(c["acento"]), 1))
        p.setBrush(QColor(c["acento"]))
    else:
        borde = c["apagado"] if (encima and activa) else (c["borde_hi"] if activa else c["borde"])
        p.setPen(QPen(QColor(borde), 1))
        hundida = QColor(fichas()["campo"]) if PROFUNDIDAD else Qt.NoBrush
        p.setBrush(hundida if not marcada else QColor(c["borde_hi"]))
    p.drawRoundedRect(caja.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
    if marcada:
        pen = QPen(QColor(c["sobre_acento"] if activa else c["apagado"]), max(1.2, caja.width() / 8))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        w = caja.width()
        camino = QPainterPath(QPointF(caja.left() + w * 0.24, caja.top() + w * 0.52))
        camino.lineTo(caja.left() + w * 0.43, caja.top() + w * 0.70)
        camino.lineTo(caja.left() + w * 0.77, caja.top() + w * 0.32)
        p.setBrush(Qt.NoBrush)
        p.drawPath(camino)


class Casilla(QAbstractButton):
    """Casilla de 11 px, apagada; solo la marcada lleva el color de acento. Se usa como un QCheckBox sin texto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        medida(self, lambda w: (w.setFixedHeight(px(ALTO_FILA)), w.setMinimumWidth(px(CASILLA) + 8),
                                w.setMaximumWidth(px(ANCHO_COLUMNA))))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._encima = False

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(px(ANCHO_COLUMNA), px(ALTO_FILA))

    def minimumSizeHint(self) -> QSize:        # noqa: N802
        return QSize(px(CASILLA) + 8, px(ALTO_FILA))

    def enterEvent(self, ev):
        self._encima = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._encima = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        lado = px(CASILLA)
        caja = QRectF((self.width() - lado) / 2, (self.height() - lado) / 2, lado, lado)
        _pintar_casilla(p, caja, self.isChecked(), self._encima, self.isEnabled())
        if self.hasFocus():
            p.setPen(QPen(QColor(T.TEXT_FAINT), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(caja.adjusted(-2.5, -2.5, 2.5, 2.5), 3, 3)
        p.end()


class CasillaTexto(QCheckBox):
    """QCheckBox con la casilla de 11 px del diseño y su texto gris pequeño (si no cabe, se parte en líneas)."""

    def __init__(self, texto: str, tam: int = LETRA_P, parent=None):
        super().__init__(texto, parent)
        self._tam = tam
        self._encima = False
        medida(self, lambda w: (w.setFont(fuente(tam)), w.setStyleSheet(f"font-size: {px(tam)}px;")))
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def _medidas(self, ancho: int | None = None):
        fm = QFontMetrics(self.font())
        lado = px(CASILLA)
        hueco = px(M2) - 2
        ancho_txt = (ancho - lado - hueco) if ancho else fm.horizontalAdvance(self.text()) + 2
        r = fm.boundingRect(0, 0, max(10, ancho_txt), 10000, Qt.TextWordWrap, self.text())
        return lado, hueco, r

    def sizeHint(self) -> QSize:               # noqa: N802
        lado, hueco, r = self._medidas()
        return QSize(lado + hueco + r.width() + 2, max(px(ALTO_FILA), r.height() + 4))

    def minimumSizeHint(self) -> QSize:        # noqa: N802  (la palabra más larga cabe; lo demás, en líneas)
        fm = QFontMetrics(self.font())
        larga = max((fm.horizontalAdvance(w) for w in self.text().split()), default=0)
        return QSize(px(CASILLA) + px(M2) + larga + 2, px(ALTO_FILA))

    def hasHeightForWidth(self) -> bool:       # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:   # noqa: N802
        _l, _h, r = self._medidas(w)
        return max(px(ALTO_FILA), r.height() + 4)

    def hitButton(self, pos) -> bool:          # noqa: N802  (toda la fila, texto incluido)
        return self.rect().contains(pos)

    def enterEvent(self, ev):
        self._encima = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._encima = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        c = colores()
        p = QPainter(self)
        lado, hueco, _r = self._medidas(self.width())
        caja = QRectF(0, (min(self.height(), px(ALTO_FILA)) - lado) / 2, lado, lado)
        _pintar_casilla(p, caja, self.isChecked(), self._encima, self.isEnabled())
        p.setFont(self.font())
        p.setPen(QColor(c["tenue"] if self.isEnabled() else c["borde_hi"]))
        txt = QRectF(lado + hueco, 0, self.width() - lado - hueco, self.height())
        p.drawText(txt, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, self.text())
        p.end()


class TablaCasillas(QWidget):
    """Tabla de filas (texto a la izquierda) con N columnas de casillas pequeñas (filas de 22 px y resalte suave
    al pasar el ratón). Una celda sin casilla (no se puede) lleva un tooltip que explica por qué.

        t = TablaCasillas([("marcar", "Marcar", tip), ("quitar", "Quitar", tip)])
        t.agregar_fila("silence", "Silencios largos", tip, {"marcar": True, "quitar": None}, {"quitar": "por qué"})
        t.casilla("silence", "marcar").setChecked(True);  t.cambiado.connect(lambda fila, col, on: …)
    """
    cambiado = Signal(str, str, bool)

    def __init__(self, columnas: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self._cols = [c[0] for c in columnas]
        self._filas: list[str] = []
        self._etiquetas: dict[str, QLabel] = {}
        self._celdas: dict[tuple[str, str], QWidget] = {}
        self._encima: str | None = None
        self.cabeceras: dict[str, QLabel] = {}
        self._g = _RejillaFija(self)
        self._g.setContentsMargins(0, 0, 0, 0)
        self._g.setHorizontalSpacing(0)
        self._g.setVerticalSpacing(0)
        self._g.setColumnStretch(0, 1)
        for i, (clave, titulo, tip) in enumerate(columnas):
            cab = QLabel(titulo)
            poner_letra(cab, LETRA_P, GRIS_TITULO)
            cab.setAlignment(Qt.AlignCenter)
            cab.setProperty("responsive_una_linea", True)
            medida(cab, lambda w, t=titulo: (
                w.setMinimumWidth(min(px(ANCHO_COLUMNA), _palabra_mas_ancha(t, w.font()) + 4)),
                w.setMaximumWidth(px(ANCHO_COLUMNA)), w.setMinimumHeight(px(ALTO_FILA) - 4)))
            cab.setToolTip(tip)
            self._g.addWidget(cab, 0, i + 1)
            self.cabeceras[clave] = cab
        self.setMouseTracking(True)

    def agregar_fila(self, clave: str, texto: str, tooltip: str = "", valores: dict | None = None,
                     sin_casilla: dict | None = None):
        """valores = {columna: True/False (casilla) o None (sin casilla)}; sin_casilla = {columna: tooltip}."""
        valores = valores or {}
        fila = len(self._filas) + 1
        self._filas.append(clave)
        lb = QLabel(texto)
        lb.setWordWrap(True)
        poner_letra(lb, LETRA_M, T.TEXT_DIM)
        medida(lb, lambda w: (w.setMinimumHeight(px(ALTO_FILA)), w.setContentsMargins(px(M1), 0, 0, 0)))
        lb.setToolTip(tooltip)
        lb.setMouseTracking(True)
        lb.installEventFilter(self)
        self._g.addWidget(lb, fila, 0)
        self._etiquetas[clave] = lb
        for i, col in enumerate(self._cols):
            v = valores.get(col, False)
            if v is None:
                w = QWidget()
                medida(w, lambda x: (x.setFixedHeight(px(ALTO_FILA)), x.setMinimumWidth(px(CASILLA) + 8),
                                     x.setMaximumWidth(px(ANCHO_COLUMNA))))
                w.setToolTip((sin_casilla or {}).get(col, ""))
            else:
                w = Casilla()
                w.setChecked(bool(v))
                w.setToolTip(f"{self.cabeceras[col].text()}: {texto}" + (f"\n{tooltip}" if tooltip else ""))
                w.setAccessibleName(f"{self.cabeceras[col].text()} {texto}")
                w.toggled.connect(lambda on, f=clave, c=col: self.cambiado.emit(f, c, on))
            w.setMouseTracking(True)
            w.installEventFilter(self)
            self._g.addWidget(w, fila, i + 1)
            self._celdas[(clave, col)] = w
        return lb

    def filas(self) -> list[str]:
        return list(self._filas)

    def columnas(self) -> list[str]:
        return list(self._cols)

    def etiqueta(self, fila: str) -> QLabel | None:
        return self._etiquetas.get(fila)

    def casilla(self, fila: str, col: str) -> Casilla | None:
        w = self._celdas.get((fila, col))
        return w if isinstance(w, Casilla) else None

    def celda(self, fila: str, col: str) -> QWidget | None:
        return self._celdas.get((fila, col))

    def valores(self, col: str) -> dict[str, bool]:
        """{fila: marcada} de esa columna (solo las filas que tienen casilla)."""
        return {f: self.casilla(f, col).isChecked() for f in self._filas if self.casilla(f, col) is not None}

    # ---- resalte de la fila bajo el ratón
    def _fila_de(self, w) -> str | None:
        for (f, _c), cel in self._celdas.items():
            if cel is w:
                return f
        for f, lb in self._etiquetas.items():
            if lb is w:
                return f
        return None

    def _poner_encima(self, fila: str | None):
        if fila != self._encima:
            self._encima = fila
            self.update()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Enter:
            self._poner_encima(self._fila_de(obj))
        elif t == QEvent.Leave and self._encima == self._fila_de(obj):
            self._poner_encima(None)
        return super().eventFilter(obj, ev)

    def leaveEvent(self, ev):
        self._poner_encima(None)
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        if self._encima is None or self._encima not in self._etiquetas:
            return
        lb = self._etiquetas[self._encima]
        g = lb.geometry()
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(_mezcla(T.BG, T.TEXT, 0.06))
        p.drawRoundedRect(QRectF(0, g.top(), self.width(), g.height()), 3, 3)
        p.end()


# ------------------------------------------------------------------------------------------------ estado y botones
class PuntoEstado(QWidget):
    """Punto de 7 px: «nada» (gris) · «pendiente» (ámbar) · «listo» (verde)."""
    COLORES = {"nada": GRIS_PUNTO, "pendiente": AMBAR, "listo": VERDE}

    def __init__(self, estado: str = "nada", parent=None):
        super().__init__(parent)
        self._estado = estado
        medida(self, lambda w: w.setFixedSize(px(PUNTO) + 2, px(ALTO_CAMPO)))

    def estado(self) -> str:
        return self._estado

    def setEstado(self, estado: str):          # noqa: N802
        if estado != self._estado:
            self._estado = estado
            self.update()

    def color(self) -> QColor:
        return QColor(self.COLORES.get(self._estado, GRIS_PUNTO))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color())
        d = px(PUNTO)
        p.drawEllipse(QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d))
        p.end()


class BotonIcono(QPushButton):
    """Botón pequeño de solo icono (SVG monocromo teñido con el color del texto). Siempre con tooltip."""

    def __init__(self, nombre_icono: str, tooltip: str, tam: int = ALTO_CAMPO, plano: bool = False, parent=None):
        super().__init__(parent)
        self._icono = nombre_icono
        self._plano = plano
        self._encima = False
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip.split("\n")[0])
        self.setCursor(Qt.PointingHandCursor)
        medida(self, lambda w: w.setFixedSize(px(tam), px(tam)))

    def nombre_icono(self) -> str:
        return self._icono

    def poner_icono(self, nombre_icono: str, tooltip: str | None = None):
        """Otro icono (y su tooltip): p. ej. «Ignorar» ↔ «Recuperar» según lo elegido. Nunca texto a la vista."""
        if tooltip is not None and tooltip != self.toolTip():
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip.split("\n")[0])
        if nombre_icono != self._icono:
            self._icono = nombre_icono
            self.update()

    def enterEvent(self, ev):
        self._encima = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._encima = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        c = colores()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        activo = self.isEnabled()
        abajo = 1 if self.isDown() else 0              # (pulsado: un tono más oscuro y hundido 1 px)
        f = fichas()
        if PROFUNDIDAD and not self._plano and not self.isDown():
            enc = self._encima and activo
            _pintar_relieve(p, r, f["control_hover_arriba" if enc else "control_arriba"],
                            f["control_hover_abajo" if enc else "control_abajo"], f["control_borde"], f["control_luz"])
        else:
            if self.isDown():
                fondo = f["control_pulsado"] if PROFUNDIDAD else c["campo"]
            elif self._encima and activo:
                fondo = c["relieve_hi"]
            else:
                fondo = None if self._plano else c["relieve"]
            if fondo:
                p.setPen(QPen(QColor(f["control_borde"] if PROFUNDIDAD else c["borde"]), 1) if not self._plano
                         else Qt.NoPen)
                p.setBrush(QColor(fondo))
                p.drawRoundedRect(r, 3, 3)
        col = (c["texto"] if self._encima else c["tenue"]) if activo else c["borde_hi"]
        lado = px(14)
        p.drawPixmap(int((self.width() - lado) / 2), int((self.height() - lado) / 2) + abajo,
                     pixmap_icono(self._icono, col, lado))
        p.end()


class BotonPrincipal(QPushButton):
    """EL botón de la acción principal: el único con el color de acento (26 px de alto), con su icono."""

    def __init__(self, texto: str, nombre_icono: str = "", tooltip: str = "", parent=None):
        super().__init__(texto, parent)
        self._icono = nombre_icono
        self._encima = False
        self.setObjectName("principal")
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        medida(self, lambda w: (w.setFont(fuente(LETRA_M, QFont.DemiBold)),
                                w.setStyleSheet(f"font-size: {px(LETRA_M)}px;"),
                                w.setFixedHeight(px(ALTO_PRINCIPAL))))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _ancho_contenido(self) -> int:
        fm = QFontMetrics(self.font())
        ic = (px(14) + px(6)) if self._icono else 0
        return ic + fm.horizontalAdvance(self.text())

    def sizeHint(self) -> QSize:               # noqa: N802
        return QSize(self._ancho_contenido() + 2 * px(M3), px(ALTO_PRINCIPAL))

    def minimumSizeHint(self) -> QSize:        # noqa: N802  (el texto siempre cabe entero)
        return QSize(self._ancho_contenido() + 2 * px(M2), px(ALTO_PRINCIPAL))

    def enterEvent(self, ev):
        self._encima = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._encima = False
        self.update()
        super().leaveEvent(ev)

    def colores_ahora(self) -> tuple[str, str]:
        """(fondo, texto) según el estado y el acento de ahora."""
        c = colores()
        if not self.isEnabled():
            return c["acento_off"], c["acento_off_texto"]
        if self.isDown():
            return c["acento_pulsado"], c["sobre_acento"]
        return (c["acento_hi"] if self._encima else c["acento"]), c["sobre_acento"]

    def degradado_ahora(self) -> dict | None:
        """El degradado del botón ahora (desde el acento elegido); None si está deshabilitado o sin profundidad."""
        if not PROFUNDIDAD or not self.isEnabled():
            return None
        a = degradado_acento()
        if self.isDown():
            return dict(a, arriba=a["pulsado"], abajo=a["pulsado"])
        if self._encima:
            return dict(a, arriba=a["hover_arriba"], abajo=a["hover_abajo"])
        return a

    def paintEvent(self, _ev):
        fondo, tinta = self.colores_ahora()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = self.degradado_ahora()
        if g is not None:
            _pintar_relieve(p, r, g["arriba"], g["abajo"], g["borde"],
                            g["luz"] if not self.isDown() else "rgba(0,0,0,0.12)", 4)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(fondo))
            p.drawRoundedRect(QRectF(self.rect()), 4, 4)
        abajo = 1 if self.isDown() else 0              # (pulsado: hundido 1 px)
        ancho = self._ancho_contenido()
        x = max(px(M2), (self.width() - ancho) / 2)
        if self._icono:
            lado = px(14)
            p.drawPixmap(int(x), int((self.height() - lado) / 2) + abajo, pixmap_icono(self._icono, tinta, lado))
            x += lado + px(6)
        p.setFont(self.font())
        p.setPen(QColor(tinta))
        p.drawText(QRectF(x, abajo, self.width() - x, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(tinta), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5), 3, 3)
        p.end()


class FilaFluida(QWidget):
    """Una fila de controles que, si no cabe, sigue en la línea de abajo (como el texto): nada queda cortado ni fuera
    del panel (22/11: «Sin audio» de Buscar material se salía por la derecha en un panel estrecho). Es un WIDGET que
    coloca a sus hijos él mismo (no un QLayout hecho en Python: sus QLayoutItem chocarían con la red de seguridad de
    responsive.soltar_envoltorios_de_items y cerraban el programa). Se llena como un QHBoxLayout: addWidget,
    insertWidget, addStretch (no hace falta: no estira), count, setSpacing, setContentsMargins.
    alinear_derecha=True: cada línea, pegada a la derecha."""

    def __init__(self, parent=None, espacio: int = 4, alinear_derecha: bool = False):
        super().__init__(parent)
        self._ws: list = []
        self._esp = espacio
        self._derecha = alinear_derecha
        pol = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        pol.setHeightForWidth(True)
        self.setSizePolicy(pol)

    # (lo de un QHBoxLayout que se usa para llenar filas)
    def addWidget(self, w: QWidget, *_a):        # noqa: N802
        self.insertWidget(len(self._ws), w)

    def insertWidget(self, indice: int, w: QWidget, *_a):   # noqa: N802
        oculto = w.isHidden() and w.testAttribute(Qt.WA_WState_ExplicitShowHide)
        if w in self._ws:
            self._ws.remove(w)
        indice = max(0, min(len(self._ws), indice if indice >= 0 else len(self._ws)))
        w.setParent(self)
        self._ws.insert(indice, w)
        w.installEventFilter(self)
        w.setVisible(not oculto)
        self._al_cambiar()

    def addStretch(self, *_a):                   # noqa: N802
        pass

    def count(self) -> int:
        return len(self._ws)

    def setSpacing(self, espacio: int):          # noqa: N802
        self._esp = int(espacio)
        self._al_cambiar()

    def spacing(self) -> int:
        return self._esp

    # (medidas)
    def _visibles(self) -> list:
        return [w for w in self._ws if w.parent() is self and w.isVisibleTo(self)]

    @staticmethod
    def _medida(w: QWidget) -> QSize:
        """Lo que ocupa: su tamaño preferido, sin bajar de su mínimo ni pasar de su máximo (un botón de icono de
        tamaño fijo dice preferir más ancho del que puede tener)."""
        return w.sizeHint().expandedTo(w.minimumSize()).boundedTo(w.maximumSize())

    def _lineas(self, ancho: int) -> list:
        lineas, linea, ancho_linea = [], [], 0
        for w in self._visibles():
            s = self._medida(w)
            if linea and ancho_linea + self._esp + s.width() > ancho:
                lineas.append((linea, ancho_linea))
                linea, ancho_linea = [], 0
            ancho_linea += (self._esp if linea else 0) + s.width()
            linea.append((w, s))
        if linea:
            lineas.append((linea, ancho_linea))
        return lineas

    def hasHeightForWidth(self):                 # noqa: N802
        return True

    def heightForWidth(self, ancho):             # noqa: N802
        m = self.contentsMargins()
        lineas = self._lineas(max(1, ancho - m.left() - m.right()))
        alto = sum(max(s.height() for _w, s in l) for l, _a in lineas) + self._esp * max(0, len(lineas) - 1)
        return alto + m.top() + m.bottom()

    def sizeHint(self):                          # noqa: N802
        m = self.contentsMargins()
        vis = [self._medida(w) for w in self._visibles()]
        ancho = sum(s.width() for s in vis) + self._esp * max(0, len(vis) - 1)
        alto = max((s.height() for s in vis), default=0)
        return QSize(ancho + m.left() + m.right(), alto + m.top() + m.bottom())

    def minimumSizeHint(self):                   # noqa: N802
        m = self.contentsMargins()
        vis = [self._medida(w) for w in self._visibles()]
        ancho = max((s.width() for s in vis), default=0)
        alto = max((s.height() for s in vis), default=0)
        return QSize(ancho + m.left() + m.right(), alto + m.top() + m.bottom())

    # (colocar)
    def _recolocar(self):
        m = self.contentsMargins()
        zona = self.rect().adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        y = zona.y()
        for linea, ancho in self._lineas(max(1, zona.width())):
            alto = max(s.height() for _w, s in linea)
            x = zona.x() + (max(0, zona.width() - ancho) if self._derecha else 0)
            for w, s in linea:
                ancho_w = min(s.width(), zona.width())
                w.setGeometry(x, y + (alto - s.height()) // 2, ancho_w, s.height())
                x += ancho_w + self._esp
            y += alto + self._esp

    def _al_cambiar(self):
        self.updateGeometry()
        self._recolocar()

    def resizeEvent(self, e):                    # noqa: N802
        super().resizeEvent(e)
        self._recolocar()

    def showEvent(self, e):                      # noqa: N802
        super().showEvent(e)
        self._recolocar()

    def event(self, e):
        if e.type() == QEvent.LayoutRequest:     # (un hijo cambió de tamaño)
            self._al_cambiar()
        return super().event(e)

    def eventFilter(self, obj, e):               # noqa: N802
        if e.type() in (QEvent.ShowToParent, QEvent.HideToParent):
            self._al_cambiar()                   # (un hijo se enseña o se esconde: las líneas cambian)
        return super().eventFilter(obj, e)


class LineaSeparadora(QWidget):
    """Línea fina de 1 px (encima del pie de un panel)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BORDER))
        p.end()


# ------------------------------------------------------------------------------------------------ filas compactas
class _DelegadoFilaCompacta(QStyledItemDelegate):
    """Filas de ALTO_FILA (22 px) en tablas y árboles (lo que no quepa, con «…» y entero en el tooltip)."""

    def sizeHint(self, op, idx):              # noqa: N802
        s = super().sizeHint(op, idx)
        return QSize(s.width(), px(ALTO_FILA))


def filas_compactas(vista: QAbstractItemView) -> QAbstractItemView:
    """Una tabla o árbol con filas de 22 px, la letra del diseño y los iconos pequeños."""
    vista.setItemDelegate(_DelegadoFilaCompacta(vista))
    if hasattr(vista, "setUniformRowHeights"):
        vista.setUniformRowHeights(True)

    def aplicar(v):
        v.setFont(fuente(LETRA_M))
        v.setIconSize(QSize(px(PUNTO) + 3, px(PUNTO) + 3))
        h = v.header() if hasattr(v, "header") else None
        if h is not None:
            h.setFont(fuente(LETRA_P, QFont.DemiBold))
            h.setStyleSheet(f"QHeaderView::section {{ font-size: {px(LETRA_P)}px; color: {GRIS_TITULO}; }}")
    return medida(vista, aplicar)


# ------------------------------------------------------------------------------------------------ lista adaptable
ROL_GRUPO = int(Qt.UserRole) + 40      # True = cabecera de grupo (ocupa toda la fila; clic = plegar o abrir)
ROL_DETALLE = int(Qt.UserRole) + 41    # texto de más que también se busca (p. ej. «para qué» de un sonido)
ROL_PLEGADO = int(Qt.UserRole) + 42    # (de la cabecera) su grupo está plegado
_PAD_X, _PAD_Y, _HUECO_ICONO = 6, 3, 6


class _DelegadoLista(QStyledItemDelegate):
    """El delegado de ListaAdaptable: mide y pinta con la MISMA función (lo medido es lo pintado: nada cortado)."""

    def __init__(self, lista):
        super().__init__(lista)
        self.lista = lista

    def sizeHint(self, op, idx):              # noqa: N802
        return self.lista._tam_fila(idx.row())

    def paint(self, p, op, idx):
        self.lista._pintar(p, op, idx)


class ListaAdaptable(QListWidget):
    """Lista que usa todo el ancho: 1 columna si el panel es estrecho; 2 o 3 al ensancharse (cada columna con un ancho
    mínimo). El orden de lectura no cambia (izquierda → derecha y luego abajo) y los nombres nunca se cortan: se
    parten en varias líneas (la fila mide lo que pida el más alto). Es un QListWidget de verdad: arrastrar
    (mimeData), clic derecho, doble clic, selección y los itemXxx de siempre funcionan igual; ← → van al anterior o
    al siguiente y ↑ ↓ a la fila de arriba o de abajo.

    Cabeceras de grupo (agregar_grupo): ocupan toda la fila; clic = plegar o abrir su grupo. filtrar(texto) deja a la
    vista lo que coincide. Con «clave», recuerda los grupos plegados, el elemento elegido y por dónde ibas.
    ajustar_alto=True: mide lo que su contenido (sin barra propia, hasta alto_max px)."""

    def __init__(self, clave: str = "", ancho_min: int = 150, max_columnas: int = 3, ajustar_alto: bool = False,
                 alto_max: int | None = None, parent=None):
        super().__init__(parent)
        self._clave = clave
        self._ancho_min, self._max_cols = ancho_min, max(1, max_columnas)
        self._ajustar, self._alto_max = ajustar_alto, alto_max
        self._tams: list = []                  # QSize de cada fila del modelo (la última vez que se colocó)
        self._celdas: list = []                # (fila visual, columna) de cada fila del modelo, o None
        self._filas_vis: list = []             # filas del modelo en cada fila visual
        self._cols, self._ancho_col, self._alto_total = 1, 100, 0
        self._cache_ancho: dict = {}
        self._cache_alto: dict = {}
        self._cache_palabra: dict = {}
        self._pulsada = None
        self._filtro = ""
        self._plegados: set[str] = set()
        self._restaurar_pendiente = bool(clave)
        self._desplazar_a: float | None = None
        self.medidas_colocar: list[float] = []  # (para medir: segundos de cada vez que se colocó)
        if clave:
            try:
                self._plegados = set(json.loads(str(QSettings("EditorIA", "EditorIA").value(
                    f"listas/{clave}/plegados", "[]"))))
            except (TypeError, ValueError):
                self._plegados = set()
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Fixed)    # (lo vuelve a colocar resizeEvent: al momento, sin la espera de Qt)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setWordWrap(False)                # (las líneas las parte el delegado)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setItemDelegate(_DelegadoLista(self))
        self._sin_barra = "lista_adaptable"    # (responsive.py no la toca: ya se adapta sola a cualquier ancho)
        medida(self, ListaAdaptable._letras)
        m = self.model()
        m.dataChanged.connect(lambda *_a: self._modelo_cambio(True))   # (otro texto o icono: otro alto)
        for sig in (m.rowsInserted, m.rowsRemoved, m.rowsMoved, m.modelReset, m.layoutChanged):
            sig.connect(lambda *_a: self._modelo_cambio(False))
        # (con muchos elementos, al arrastrar el borde se vuelve a colocar al parar: no en cada píxel)
        self._t_ancho = QTimer(self)
        self._t_ancho.setSingleShot(True)
        self._t_ancho.setInterval(70)
        self._t_ancho.timeout.connect(self.scheduleDelayedItemsLayout)
        self.currentItemChanged.connect(lambda it, _ant: self._guardar_actual(it))
        self._t_guardar = QTimer(self)
        self._t_guardar.setSingleShot(True)
        self._t_guardar.setInterval(400)
        self._t_guardar.timeout.connect(self._guardar_desplazamiento)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._t_guardar.start() if self._clave else None)

    MUCHOS = 800                               # (a partir de aquí, al arrastrar el borde, se coloca al parar)

    def _modelo_cambio(self, recolocar: bool):
        self._info = None
        if recolocar:
            self.scheduleDelayedItemsLayout()

    def _info_filas(self) -> list:
        """[(cabecera?, texto, sitio del icono)] de cada fila (caché: se rehace si cambian el modelo o el icono)."""
        clave = (self.iconSize().width(), self.count())
        if getattr(self, "_info", None) is None or self._info_clave != clave:
            iw = self.iconSize().width() + px(_HUECO_ICONO)
            info = []
            for r in range(self.count()):
                it = self.item(r)
                g, texto, ai = bool(it.data(ROL_GRUPO)), it.text(), 0 if it.icon().isNull() else iw
                # (lo que pide en una sola línea: si la columna es al menos así de ancha, su alto es el de una línea)
                una = self._una_linea(texto, "g" if g else "n") + 2 * px(_PAD_X) + (px(12) if g else ai)
                info.append((g, texto, ai, una if chr(10) not in texto else 1 << 30))
            self._info, self._info_clave = info, clave
        return self._info

    # ---- medidas
    def _letras(self):
        self._f_nombre = fuente(LETRA_M)
        self._f_grupo = fuente(LETRA_P, QFont.DemiBold)
        self._fm = {"n": QFontMetrics(self._f_nombre), "g": QFontMetrics(self._f_grupo)}
        self._cache_ancho.clear()
        self._cache_alto.clear()
        self._cache_palabra.clear()
        self._info = None
        self.setFont(self._f_nombre)
        self.scheduleDelayedItemsLayout()

    def ancho_disponible(self) -> int:
        """El ancho en que Qt coloca los elementos (con la barra vertical «si hace falta», Qt deja siempre su sitio)."""
        w = self.maximumViewportSize().width()
        if self.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded:
            w -= self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self.verticalScrollBar())
        return max(1, w)

    def _una_linea(self, texto: str, k: str) -> int:
        c = (texto, k)
        a = self._cache_ancho.get(c)
        if a is None:
            a = self._cache_ancho[c] = self._fm[k].horizontalAdvance(texto)
        return a

    def _palabra(self, texto: str, k: str) -> int:
        c = (texto, k)
        a = self._cache_palabra.get(c)
        if a is None:
            fm = self._fm[k]
            a = self._cache_palabra[c] = max((fm.horizontalAdvance(w) for w in texto.split()), default=0)
        return a

    def _banderas(self, texto: str, k: str, ancho: int) -> int:
        f = int(Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap)
        if self._palabra(texto, k) > ancho:
            f |= int(Qt.TextWrapAnywhere)      # (una palabra más ancha que la columna: se parte, no se corta)
        return f

    def _alto_texto(self, texto: str, k: str, ancho: int) -> int:
        fm = self._fm[k]
        if not texto or self._una_linea(texto, k) <= ancho and "\n" not in texto:
            return fm.height()
        c = (texto, k, ancho)
        h = self._cache_alto.get(c)
        if h is None:
            if len(self._cache_alto) > 20000:
                self._cache_alto.clear()
            h = self._cache_alto[c] = fm.boundingRect(QRect(0, 0, max(1, ancho), 1 << 20),
                                                      self._banderas(texto, k, ancho), texto).height()
        return h

    def _ancho_icono(self, it) -> int:
        return (self.iconSize().width() + px(_HUECO_ICONO)) if not it.icon().isNull() else 0

    def _alto_elemento(self, it, ancho_col: int) -> int:
        return self._alto_de(it.text(), self._ancho_icono(it), ancho_col)

    def _alto_de(self, texto: str, ai: int, ancho_col: int) -> int:
        h = self._alto_texto(texto, "n", ancho_col - 2 * px(_PAD_X) - ai)
        if ai:
            h = max(h, self.iconSize().height())
        return max(px(ALTO_FILA), h + 2 * px(_PAD_Y))

    def _alto_grupo(self, it, ancho: int) -> int:
        return self._alto_grupo_de(it.text(), ancho)

    def _alto_grupo_de(self, texto: str, ancho: int) -> int:
        tw = ancho - 2 * px(_PAD_X) - px(12)
        return max(px(ALTO_FILA), self._alto_texto(texto, "g", tw) + 2 * px(_PAD_Y))

    def columnas(self) -> int:
        return self._cols

    def ancho_columna(self) -> int:
        return self._ancho_col

    def alto_contenido(self) -> int:
        return self._alto_total

    # ---- colocar (Qt llama a doItemsLayout en cada cambio: filas nuevas, ocultas, otro ancho…)
    def _calcular(self):
        import time as _t
        t0 = _t.perf_counter()
        B = self.ancho_disponible()
        n_filas = self.count()
        info = self._info_filas()
        oculta = self.isRowHidden
        vivos = [(r,) + info[r] for r in range(n_filas) if not oculta(r)]   # (fila, cabecera?, texto, icono, una)
        # (cada columna mide como poco ancho_min; una palabra más ancha que su columna se parte —nunca se corta—)
        minimo = max(1, px(self._ancho_min))
        n = max(1, min(self._max_cols, (B - 1) // minimo))
        colw = max(1, (B - 1) // n)            # (n columnas de colw caben siempre en una fila de Qt: n·colw < B)
        tams = [QSize(colw, 0)] * n_filas
        celdas: list = [None] * n_filas
        filas_vis: list = []
        fila: list = []
        altos: list = []
        total = 0

        def cerrar():
            nonlocal total
            if fila:
                h = max(altos)
                tam = QSize(colw, h)
                for x in fila:
                    tams[x] = tam
                filas_vis.append(list(fila))
                total += h
                fila.clear()
                altos.clear()
        alto_de, ancho_fila = self._alto_de, colw * n
        h_una = {ai: None for ai in {v[3] for v in vivos}}     # (alto de una línea, con y sin icono)
        for ai in h_una:
            h_una[ai] = alto_de("", ai, colw)
        for r, g, texto, ai, una in vivos:
            if g:
                cerrar()
                h = self._alto_grupo_de(texto, ancho_fila)
                tams[r] = QSize(colw * n, h)   # (toda la fila: Qt la pone sola en su fila)
                celdas[r] = (len(filas_vis), 0)
                filas_vis.append([r])
                total += h
                continue
            celdas[r] = (len(filas_vis), len(fila))
            fila.append(r)
            altos.append(h_una[ai] if una <= colw else alto_de(texto, ai, colw))
            if len(fila) == n:
                cerrar()
        cerrar()
        self._tams, self._celdas, self._filas_vis = tams, celdas, filas_vis
        self._cols, self._ancho_col, self._alto_total = n, colw, total
        self.medidas_colocar.append(_t.perf_counter() - t0)
        del self.medidas_colocar[:-50]

    def _tam_fila(self, r: int) -> QSize:
        if 0 <= r < len(self._tams) and r < self.count():
            return self._tams[r]
        it = self.item(r)                      # (una fila nueva antes de volver a colocar: su tamaño suelto)
        if it is None:
            return QSize(self._ancho_col, px(ALTO_FILA))
        if it.data(ROL_GRUPO):
            return QSize(self._ancho_col * self._cols, self._alto_grupo(it, self._ancho_col * self._cols))
        return QSize(self._ancho_col, self._alto_elemento(it, self._ancho_col))

    def doItemsLayout(self):                   # noqa: N802
        self._calcular()
        super().doItemsLayout()
        if self._ajustar:
            self._ajustar_alto()
        if self._desplazar_a is not None and self.verticalScrollBar().maximum() > 0:
            sb = self.verticalScrollBar()
            sb.setValue(round(self._desplazar_a * sb.maximum()))
            self._desplazar_a = None

    def _ajustar_alto(self):
        h = self._alto_total + 2 * self.frameWidth()
        if self._alto_max:
            h = min(h, px(self._alto_max))
        h = max(h, px(ALTO_FILA) + 2 * self.frameWidth())
        if self.minimumHeight() != h or self.maximumHeight() != h:
            self.setFixedHeight(h)

    def poner_alto_max(self, alto_max: int | None):
        """El alto máximo con ajustar_alto (None = todo su contenido, sin barra propia)."""
        self._alto_max = alto_max
        if self._ajustar:
            self._ajustar_alto()

    def resizeEvent(self, ev):                 # noqa: N802
        super().resizeEvent(ev)
        if ev.oldSize().width() != ev.size().width():
            if self.count() >= self.MUCHOS:
                self._t_ancho.start()          # (miles de elementos: al parar de arrastrar el borde)
            else:
                self.scheduleDelayedItemsLayout()   # (en la siguiente vuelta: varios cambios = una sola vez)

    def sizeHint(self) -> QSize:               # noqa: N802
        s = super().sizeHint()
        if self._ajustar:
            return QSize(s.width(), self.maximumHeight() if self.maximumHeight() < 16777215 else s.height())
        return s

    def minimumSizeHint(self) -> QSize:        # noqa: N802  (estrecha: una columna con los nombres en líneas)
        return QSize(px(100), super().minimumSizeHint().height())

    # ---- teclado: ← → en orden de lectura, ↑ ↓ por filas; nunca una cabecera
    def _elegible(self, r: int) -> bool:
        it = self.item(r)
        return it is not None and not self.isRowHidden(r) and not it.data(ROL_GRUPO) and \
            bool(it.flags() & Qt.ItemIsEnabled) and bool(it.flags() & Qt.ItemIsSelectable)

    def _siguiente(self, r: int, paso: int):
        k = r + paso
        while 0 <= k < self.count():
            if self._elegible(k):
                return k
            k += paso
        return None

    def moveCursor(self, accion, mods):        # noqa: N802
        A = QAbstractItemView.CursorAction
        actual = self.currentIndex()
        r = actual.row() if actual.isValid() else -1
        if accion in (A.MoveLeft, A.MoveRight, A.MoveNext, A.MovePrevious):
            k = self._siguiente(r, 1 if accion in (A.MoveRight, A.MoveNext) else -1)
            return self.model().index(k, 0) if k is not None else actual
        if accion in (A.MoveUp, A.MoveDown):
            if not (0 <= r < len(self._celdas)) or self._celdas[r] is None:
                k = self._siguiente(r, 1 if accion == A.MoveDown else -1)
                return self.model().index(k, 0) if k is not None else actual
            fv, col = self._celdas[r]
            d = -1 if accion == A.MoveUp else 1
            fv += d
            while 0 <= fv < len(self._filas_vis):
                fila = [x for x in self._filas_vis[fv] if self._elegible(x)]
                if fila:
                    return self.model().index(fila[min(col, len(fila) - 1)], 0)
                fv += d
            return actual
        idx = super().moveCursor(accion, mods)
        if idx.isValid() and not self._elegible(idx.row()):
            haciaatras = accion in (A.MoveEnd, A.MovePageDown)
            k = self._siguiente(idx.row(), -1 if haciaatras else 1)
            if k is None:
                k = self._siguiente(idx.row(), 1 if haciaatras else -1)
            return self.model().index(k, 0) if k is not None else actual
        return idx

    # ---- grupos plegables
    def agregar_grupo(self, texto: str, clase=QListWidgetItem):
        """Una cabecera de grupo (toda la fila). Los elementos que vengan detrás son de su grupo."""
        it = clase(texto)
        it.setData(ROL_GRUPO, True)
        it.setFlags(Qt.ItemIsEnabled)
        it.setData(ROL_PLEGADO, texto in self._plegados)
        it.setToolTip("Clic: plegar o abrir")
        self.addItem(it)
        return it

    def agregar(self, it, grupo=None):
        """Añade un elemento (al final; si su grupo está plegado, oculto)."""
        self.addItem(it)
        if grupo is not None and grupo.data(ROL_PLEGADO) and not self._filtro:
            it.setHidden(True)
        return it

    def es_grupo(self, it) -> bool:
        return it is not None and bool(it.data(ROL_GRUPO))

    def miembros(self, grupo) -> list:
        out = []
        k = self.row(grupo) + 1
        while 0 < k < self.count():
            it = self.item(k)
            if it.data(ROL_GRUPO):
                break
            out.append(it)
            k += 1
        return out

    def plegar(self, grupo, on: bool):
        """Pliega (on) o abre el grupo de esa cabecera; se recuerda."""
        if not self.es_grupo(grupo):
            return
        grupo.setData(ROL_PLEGADO, bool(on))
        if not self._filtro:
            for it in self.miembros(grupo):
                it.setHidden(bool(on))
        (self._plegados.add if on else self._plegados.discard)(grupo.text())
        if self._clave:
            QSettings("EditorIA", "EditorIA").setValue(f"listas/{self._clave}/plegados",
                                                       json.dumps(sorted(self._plegados), ensure_ascii=False))

    def filtrar(self, texto: str):
        """A la vista solo lo que contiene el texto (nombre o ROL_DETALLE) y sus cabeceras; sin texto, todo (los
        grupos plegados, plegados)."""
        t = (texto or "").lower().strip()
        self._filtro = t
        grupo, n_vis = None, 0

        def cerrar_grupo():
            if grupo is not None:
                grupo.setHidden(bool(t) and n_vis == 0)
        for r in range(self.count()):
            it = self.item(r)
            if it.data(ROL_GRUPO):
                cerrar_grupo()
                grupo, n_vis = it, 0
                continue
            if t:
                ver = t in (it.text() + " " + str(it.data(ROL_DETALLE) or "")).lower()
            else:
                ver = not (grupo is not None and grupo.data(ROL_PLEGADO))
            it.setHidden(not ver)
            n_vis += ver
        cerrar_grupo()

    def mousePressEvent(self, ev):             # noqa: N802
        it = self.itemAt(ev.position().toPoint())
        self._pulsada = it if self.es_grupo(it) and ev.button() == Qt.LeftButton else None
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):           # noqa: N802
        it = self.itemAt(ev.position().toPoint())
        super().mouseReleaseEvent(ev)
        if self._pulsada is not None and it is self._pulsada:
            self.plegar(it, not it.data(ROL_PLEGADO))
        self._pulsada = None

    # ---- recordar cómo lo dejaste
    def _guardar_actual(self, it):
        # (hasta que se restaura lo de la última vez, nada se guarda: el setCurrentRow(0) de al crearla no lo pisa)
        if self._clave and it is not None and not self._restaurando() and not self._restaurar_pendiente:
            v = it.data(Qt.UserRole)
            if v is not None:
                QSettings("EditorIA", "EditorIA").setValue(f"listas/{self._clave}/actual", str(v))

    def _restaurando(self) -> bool:
        return getattr(self, "_en_restaurar", False)

    def _guardar_desplazamiento(self):
        sb = self.verticalScrollBar()
        if self._clave and sb.maximum() > 0:
            QSettings("EditorIA", "EditorIA").setValue(f"listas/{self._clave}/desplazamiento",
                                                       round(sb.value() / sb.maximum(), 4))

    def restaurar_estado(self):
        """El elemento elegido y por dónde ibas, como lo dejaste (los grupos plegados ya salen plegados)."""
        if not self._clave:
            return
        s = QSettings("EditorIA", "EditorIA")
        actual = s.value(f"listas/{self._clave}/actual")
        if actual is not None:
            for r in range(self.count()):
                it = self.item(r)
                if str(it.data(Qt.UserRole)) == str(actual) and self._elegible(r):
                    self._en_restaurar = True
                    try:
                        self.setCurrentItem(it)
                    finally:
                        self._en_restaurar = False
                    break
        try:
            frac = float(s.value(f"listas/{self._clave}/desplazamiento", -1))
        except (TypeError, ValueError):
            frac = -1
        if frac >= 0:
            self._desplazar_a = frac
            self.scheduleDelayedItemsLayout()

    def showEvent(self, ev):                   # noqa: N802
        super().showEvent(ev)
        if self._restaurar_pendiente:
            self._restaurar_pendiente = False
            self.restaurar_estado()

    # ---- pintar
    def _pintar(self, p: QPainter, op, idx):
        c = colores()
        it = self.item(idx.row())
        if it is None:
            return
        rect = op.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if it.data(ROL_GRUPO):
            if idx.row() > 0:
                p.setPen(QPen(QColor(T.BORDER), 1))
                p.drawLine(rect.left() + px(M1), rect.top(), rect.right() - px(M1), rect.top())
            plegado = bool(it.data(ROL_PLEGADO))
            x = rect.left() + px(_PAD_X)
            yc = rect.top() + px(ALTO_FILA) / 2
            t = px(4)
            camino = QPainterPath()
            if plegado:                         # ▸ plegado · ▾ abierto
                camino.moveTo(x, yc - t)
                camino.lineTo(x + t, yc)
                camino.lineTo(x, yc + t)
            else:
                camino.moveTo(x - 1, yc - t / 2)
                camino.lineTo(x + t + 1, yc - t / 2)
                camino.lineTo(x + t / 2, yc + t / 2)
            camino.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GRIS_TITULO))
            p.drawPath(camino)
            tw = rect.width() - 2 * px(_PAD_X) - px(12)
            p.setFont(self._f_grupo)
            p.setPen(QColor(GRIS_TITULO))
            p.drawText(QRectF(x + px(12), rect.top(), tw, rect.height()), self._banderas(it.text(), "g", tw),
                       it.text())
            p.restore()
            return
        activo = bool(it.flags() & Qt.ItemIsEnabled)
        sel = bool(op.state & QStyle.State_Selected)
        encima = bool(op.state & QStyle.State_MouseOver) and activo
        caja = QRectF(rect).adjusted(1, 1, -1, -1)
        if sel:
            p.setPen(QPen(_rgba(T.acento_rgba(0.55)), 1))
            p.setBrush(_rgba(T.acento_rgba(0.16)))
            p.drawRoundedRect(caja.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        elif encima:
            p.setPen(Qt.NoPen)
            p.setBrush(_mezcla(T.BG, T.TEXT, 0.07))
            p.drawRoundedRect(caja, 3, 3)
        elif op.state & QStyle.State_HasFocus and self.hasFocus():
            p.setPen(QPen(QColor(c["borde_hi"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(caja.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        x = rect.left() + px(_PAD_X)
        ai = self._ancho_icono(it)
        if ai:
            isz = self.iconSize()
            y = rect.top() + (rect.height() - isz.height()) // 2
            it.icon().paint(p, QRect(x, y, isz.width(), isz.height()), Qt.AlignCenter,
                            QIcon.Normal if activo else QIcon.Disabled)
            x += ai
        tw = rect.width() - 2 * px(_PAD_X) - ai
        texto = it.text()
        h = self._alto_texto(texto, "n", tw)
        y = rect.top() + (rect.height() - h) / 2
        p.setFont(self._f_nombre)
        p.setPen(QColor(c["texto"] if activo else c["apagado"]))
        p.drawText(QRectF(x, y, tw, h), self._banderas(texto, "n", tw), texto)
        p.restore()

    def texto_cabe(self, it) -> bool:
        """(para las pruebas) ¿Cabe entero su nombre en su sitio de ahora?"""
        r = self.visualItemRect(it)
        if it.data(ROL_GRUPO):
            tw = r.width() - 2 * px(_PAD_X) - px(12)
            return self._alto_texto(it.text(), "g", tw) + 2 * px(_PAD_Y) <= r.height() + 1
        tw = r.width() - 2 * px(_PAD_X) - self._ancho_icono(it)
        fm = self._fm["n"]
        br = fm.boundingRect(QRect(0, 0, max(1, tw), 1 << 20), self._banderas(it.text(), "n", tw), it.text())
        return br.width() <= tw + 1 and br.height() <= r.height() and r.right() < self.viewport().width() + 1


# ------------------------------------------------------------------------------------------------ columnas enlazadas
class ColumnasEnlazadas(QWidget):
    """Partes lado a lado (p. ej. Transiciones | Efectos), cada una con su título y su barra de desplazamiento, y un
    botón 🔗 entre las dos primeras: desplazarlas juntas (en proporción) o por separado. Recuerda el 🔗 y por dónde
    ibas en cada una (QSettings, «clave»)."""
    enlace_cambiado = Signal(bool)

    def __init__(self, clave: str, titulos: list[str], parent=None):
        super().__init__(parent)
        self._clave = clave
        self._sincronizando = False
        self._restaurado = False
        self.titulos: list[QLabel] = []
        self.zonas: list[QScrollArea] = []
        self._cajas: list[QWidget] = []
        g = QGridLayout(self)
        medida(self, lambda w: (g.setHorizontalSpacing(px(M1)), g.setVerticalSpacing(px(M1)),
                                g.setContentsMargins(px(M1), 0, px(M1), 0)))
        for i, t in enumerate(titulos):
            col = 2 * i
            tit = TituloSeccion(t, sangria=M2)    # (todos los títulos con la misma sangría)
            zona = QScrollArea()
            zona.setWidgetResizable(True)
            zona.setFrameShape(QScrollArea.NoFrame)
            zona.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            caja = QWidget()
            v = QVBoxLayout(caja)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            v.addStretch(1)                       # (lo que sobre de alto, debajo: el contenido mide lo suyo)
            zona.setWidget(caja)
            g.addWidget(tit, 0, col)
            g.addWidget(zona, 1, col)
            g.setColumnStretch(col, 1)
            zona.verticalScrollBar().valueChanged.connect(lambda val, k=i: self._desplazada(k, val))
            self.titulos.append(tit)
            self.zonas.append(zona)
            self._cajas.append(caja)
        g.setRowStretch(1, 1)
        s = QSettings("EditorIA", "EditorIA")
        on = str(s.value(f"{clave}/enlazadas", False)).lower() in ("true", "1")
        self.boton_enlace = BotonIcono("link" if on else "unlink", "", plano=True)
        self.boton_enlace.setCheckable(True)
        self.boton_enlace.setChecked(on)
        self._pintar_enlace()
        self.boton_enlace.toggled.connect(lambda v: self.poner_enlazadas(v))
        g.addWidget(self.boton_enlace, 0, 1, Qt.AlignCenter)
        self._t_guardar = QTimer(self)
        self._t_guardar.setSingleShot(True)
        self._t_guardar.setInterval(400)
        self._t_guardar.timeout.connect(self._guardar_desplazamiento)

    def poner_contenido(self, i: int, w: QWidget):
        """w pasa a la parte i (se desplaza con su barra), arriba; el alto que sobre queda debajo."""
        lay = self._cajas[i].layout()
        lay.insertWidget(max(0, lay.count() - 1), w)
        w.show()

    def contenido(self, i: int) -> QWidget:
        return self._cajas[i]

    def enlazadas(self) -> bool:
        return self.boton_enlace.isChecked()

    def poner_enlazadas(self, on: bool):
        if self.boton_enlace.isChecked() != on:
            self.boton_enlace.setChecked(on)      # (vuelve aquí por toggled)
            return
        self._pintar_enlace()
        QSettings("EditorIA", "EditorIA").setValue(f"{self._clave}/enlazadas", bool(on))
        if on:
            self._desplazada(0, self.zonas[0].verticalScrollBar().value())
        self.enlace_cambiado.emit(bool(on))

    def _pintar_enlace(self):
        if self.boton_enlace.isChecked():
            self.boton_enlace.poner_icono("link", "Se desplazan juntas\nClic: cada una con su barra, por separado")
        else:
            self.boton_enlace.poner_icono("unlink", "Cada una se desplaza por separado\nClic: desplazarlas juntas")

    def _desplazada(self, i: int, valor: int):
        if self._restaurado:
            self._t_guardar.start()
        if self._sincronizando or not self.boton_enlace.isChecked():
            return
        sb = self.zonas[i].verticalScrollBar()
        frac = valor / sb.maximum() if sb.maximum() > 0 else 0.0
        self._sincronizando = True
        try:
            for k, z in enumerate(self.zonas):
                if k != i:
                    o = z.verticalScrollBar()
                    o.setValue(round(frac * o.maximum()))
        finally:
            self._sincronizando = False

    def _guardar_desplazamiento(self):
        fr = []
        for z in self.zonas:
            sb = z.verticalScrollBar()
            fr.append(round(sb.value() / sb.maximum(), 4) if sb.maximum() > 0 else 0.0)
        QSettings("EditorIA", "EditorIA").setValue(f"{self._clave}/desplazamiento", json.dumps(fr))

    def restaurar_desplazamiento(self, intento: int = 0):
        try:
            fr = json.loads(str(QSettings("EditorIA", "EditorIA").value(f"{self._clave}/desplazamiento", "[]")))
        except (TypeError, ValueError):
            fr = []
        if intento < 5 and any(float(f) > 0 and z.verticalScrollBar().maximum() <= 0 for z, f in zip(self.zonas, fr)):
            QTimer.singleShot(100, lambda: self.restaurar_desplazamiento(intento + 1))   # (aún sin colocar)
            return
        self._sincronizando = True
        try:
            for z, f in zip(self.zonas, fr):
                sb = z.verticalScrollBar()
                sb.setValue(round(float(f) * sb.maximum()))
        finally:
            self._sincronizando = False
        self._restaurado = True

    def showEvent(self, ev):                   # noqa: N802
        super().showEvent(ev)
        if not self._restaurado:
            QTimer.singleShot(0, self.restaurar_desplazamiento)


# ------------------------------------------------------------------------------------------------ estados vacíos
def aviso_vacio(texto: str, tooltip: str = "") -> QLabel:
    """La línea gris de un estado vacío («Sin temas todavía»): la explicación, en el tooltip."""
    lb = QLabel(texto)
    lb.setObjectName("dim")
    lb.setWordWrap(True)
    lb.setToolTip(tooltip)
    medida(lb, lambda w: (w.setFont(fuente(LETRA_P)), w.setStyleSheet(f"font-size: {px(LETRA_P)}px; "
                                                                      f"color: {T.TEXT_DIM};")))
    return lb


def ocultar_si_vacia(vista: QAbstractItemView, aviso: QWidget | None = None) -> None:
    """Estados vacíos en una línea (criterio del usuario): la lista o tabla se esconde mientras no tenga filas y, si se
    da `aviso`, sale esa línea en su lugar. Se revisa sola al añadir o quitar filas."""
    modelo = vista.model()

    def revisar(*_a):
        try:
            hay = modelo.rowCount() > 0
            if vista.isHidden() == hay:
                vista.setVisible(hay)
            if aviso is not None and aviso.isHidden() == (not hay):
                aviso.setVisible(not hay)
        except RuntimeError:                   # (cerrando: la vista o el aviso ya no existen)
            return
    for senal in (modelo.rowsInserted, modelo.rowsRemoved, modelo.modelReset, modelo.layoutChanged):
        senal.connect(revisar)
    revisar()


# (si este archivo se cargó antes que theme.py, la hoja general se calculó sin el bloque de profundidad: ahora sí)
if MARCA_QSS not in T.STYLE and PROFUNDIDAD:
    T.STYLE = T._estilo()
