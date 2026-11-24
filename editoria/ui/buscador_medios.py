"""
🔎 Un solo buscador en Medios (23/11, sin la pestaña «IA»). La caja de Medios tiene tres modos compactos al lado:

  · Nombre          lo de siempre: filtra la lista por nombre, categoría, carpeta o contenido.
  · Lo que se ve    lo que hacía «🔎 Buscar momentos» (ui/moments_panel.MomentsPanel, el mismo panel: escenas en tus
                    clips, su lista y «poner en la línea de tiempo»), justo debajo de la caja.
  · Lo que se dice  lo que hacía «🗣 Buscar lo que se dice» (ui/keywords_dialog.KeywordsDialog, metido aquí): frases en
                    las transcripciones de tus videos y audios.
Sin resultados en ningún modo: «Buscar en internet» abre Descargas con el texto ya escrito. «🔑 Palabras clave» (el
panel de la derecha) no se toca: no es un buscador.

instalar(win) lo engancha (una línea en main_window); win.buscador_medios.poner_modo(modo, texto, foco=True) es lo
que usan las órdenes y atajos de antes (open_moments, open_keywords, Ctrl+Mayús+F…).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QStackedWidget, QToolButton, QWidget

from . import diseno as D

MODOS = (("nombre", "Nombre", "type", "Por nombre, categoría, carpeta o contenido de lo que tienes en Medios"),
         ("ve", "Lo que se ve", "eye", "Lo que se VE en tus clips: escenas de un personaje, objeto, lugar… con "
                                       "su momento exacto, listas para poner en la línea de tiempo (Enter busca)"),
         ("dice", "Lo que se dice", "mic", "Lo que se DICE en tus videos y audios: frases en sus transcripciones, "
                                          "con su momento (Enter busca)"))
PLACEHOLDER = {"nombre": "Buscar: nombre, categoría, carpeta o contenido…",
               "ve": "¿Qué se ve? Un personaje, objeto, lugar, escena…",
               "dice": "¿Qué se dice? Palabras o frases, separadas por comas"}
AJ_MODO = "medios/modo_busqueda"


class BuscadorMedios(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.lib = win.library
        self.modo = "nombre"
        self.kw = None                                     # (el de «Lo que se dice», al usarlo por primera vez)
        self._esperando = None                             # modo cuya búsqueda está en marcha
        lib = self.lib
        # ---- los modos, junto a la caja (en lugar del «Buscar» por contenido de antes)
        lib.btn_ai_search.hide()
        self.botones: dict[str, QToolButton] = {}
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        caja = QWidget()
        fila = QHBoxLayout(caja)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(D.px(1))
        for k, nombre, icono, tip in MODOS:
            b = QToolButton()
            b.setIcon(D.icono(icono))
            b.setText(nombre)
            b.setToolTip(f"{nombre}: {tip}")
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setCursor(Qt.PointingHandCursor)
            D.medida(b, lambda w: w.setFixedHeight(D.px(D.ALTO_CAMPO)))   # (a la altura de la caja: sin hueco)
            self.grupo.addButton(b)
            fila.addWidget(b)
            self.botones[k] = b
            b.clicked.connect(lambda _=False, kk=k: self.poner_modo(kk, foco=True))
        from PySide6.QtWidgets import QSizePolicy
        caja.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lib.fila_buscar.addWidget(caja, 0, Qt.AlignVCenter)
        self.btn_ve, self.btn_dice = self.botones["ve"], self.botones["dice"]     # (la guía los señala)
        self.caja_modos = caja
        # ---- los resultados de «Lo que se ve» y «Lo que se dice», debajo de la caja
        self.pila = QStackedWidget()
        self.mom = getattr(win, "moments", None)
        if self.mom is not None:
            self.mom.incrustar()
            self.pila.addWidget(self.mom)
        self.vacio_dice = QWidget()                        # (sitio del de «Lo que se dice» hasta que se use)
        self.pila.addWidget(self.vacio_dice)
        lib.zona_resultados.layout().addWidget(self.pila, 1)
        self.btn_internet = QPushButton("Buscar en internet")
        self.btn_internet.setIcon(D.icono("download"))
        self.btn_internet.setToolTip("No hay nada así en tus medios: abre Descargas con lo que escribiste")
        self.btn_internet.clicked.connect(self.buscar_en_internet)
        self.btn_internet.hide()
        lib.zona_resultados.layout().addWidget(self.btn_internet)
        # ---- la caja
        lib.search.returnPressed.connect(self._enter)
        lib.search.textChanged.connect(lambda _t: QTimer.singleShot(0, self._mirar_nombre))
        lib.btn_ai_search.toggled.connect(lambda on: self.poner_modo("ve" if on else "nombre"))
        self._vigia = QTimer(self)                          # (¿terminó la búsqueda y no encontró nada?)
        self._vigia.setInterval(250)
        self._vigia.timeout.connect(self._mirar_fin)
        modo = str(QSettings("EditorIA", "EditorIA").value(AJ_MODO, "nombre"))
        self.poner_modo(modo if modo in dict((m[0], 1) for m in MODOS) else "nombre")

    # ------------------------------------------------------------------ modos
    def _kw(self):
        if self.kw is None:
            from .keywords_dialog import KeywordsDialog
            self.kw = KeywordsDialog(self.win, "timeline")
            self.kw.incrustar()
            self.pila.addWidget(self.kw)
        return self.kw

    def poner_modo(self, modo: str, texto: str | None = None, foco: bool = False, media_ids=None,
                   scope: str | None = None):
        """El modo de la caja de Medios (y, si se da, el texto y para «Lo que se dice» dónde buscar)."""
        if modo not in ("nombre", "ve", "dice"):
            return
        lib = self.lib
        cambia = modo != self.modo
        self.modo = modo
        QSettings("EditorIA", "EditorIA").setValue(AJ_MODO, modo)
        b = self.botones[modo]
        if not b.isChecked():
            b.setChecked(True)
        for k, bb in self.botones.items():                # (el modo elegido, con su nombre; los otros, su icono)
            bb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if k == modo else Qt.ToolButtonIconOnly)
        lib.search.setPlaceholderText(PLACEHOLDER[modo])
        nombre = modo == "nombre"
        lib._lista_oculta = not nombre
        for w in (lib.btn_kw_new, lib.btn_kw_auto, lib.btn_kw_refresh):
            w.setVisible(nombre)
        if nombre:                                          # (la lista o su estado vacío, como decida Medios)
            lib.tree.setVisible(lib.tree.topLevelItemCount() > 0)
            lib.vacio.setVisible(lib.tree.topLevelItemCount() == 0)
            lib._update_footer()
        else:
            lib.tree.hide()
        if not nombre:                                      # (las bandejas y el filtro son de la lista de Medios)
            lib.zona_bandejas.setVisible(False)
            lib.fila_filtro.setVisible(False)
        else:
            lib.zona_bandejas.setVisible(lib.zona_bandejas.layout().count() > 0)
            lib.fila_filtro.setVisible(getattr(lib, "_filtro_ids", None) is not None)
        if not nombre:
            lib.vacio.hide()
        lib.zona_resultados.setVisible(not nombre)
        self.pila.setVisible(not nombre)
        if modo == "ve" and self.mom is not None:
            self.pila.setCurrentWidget(self.mom)
        elif modo == "dice":
            kw = self._kw()
            if media_ids or scope:
                i = kw.scope.findData("given" if media_ids else scope)
                if media_ids:
                    kw.media_ids = list(media_ids)
                    if i < 0:
                        kw.scope.addItem(f"En {len(media_ids)} archivo(s) elegido(s)", "given")
                        i = kw.scope.count() - 1
                if i >= 0:
                    kw.scope.setCurrentIndex(i)
            self.pila.setCurrentWidget(kw)
        if cambia:
            self.btn_internet.hide()
            lib._apply_filter()
        if texto is not None:
            lib.search.setText(texto)
            if texto and not nombre:
                self._enter()
        if foco:
            self.mostrar()
            QTimer.singleShot(0, lambda: (lib.search.setFocus(Qt.OtherFocusReason), lib.search.selectAll()))

    def mostrar(self):
        """Medios a la vista (su pestaña «Medios»)."""
        lib = self.lib
        try:
            lib.pestanas.setCurrentIndex(0)
        except Exception:  # noqa: BLE001
            pass
        dock = self.win.docks.get("media")
        if dock is not None:
            dock.show()
            dock.raise_()

    def contiene(self, w) -> bool:
        return w is not None and (w is self.mom or (self.mom is not None and self.mom.isAncestorOf(w))
                                  or (self.kw is not None and (w is self.kw or self.kw.isAncestorOf(w))))

    def mostrar_para(self, w):
        """Para show_panel / mostrar_widget: el modo donde vive ese widget, a la vista."""
        self.poner_modo("dice" if self.kw is not None and (w is self.kw or self.kw.isAncestorOf(w)) else "ve")
        self.mostrar()
        return self.win.docks.get("media")

    # ------------------------------------------------------------------ buscar
    def _enter(self):
        texto = self.lib.search.text().strip()
        self.btn_internet.hide()
        if not texto or self.modo == "nombre":
            return
        if self.modo == "ve" and self.mom is not None:
            self.mom.query.setText(texto)
            self.mom.search_text()
        elif self.modo == "dice":
            kw = self._kw()
            kw.query.setText(texto)
            kw.hits = []
            kw.search()
        self._esperando = self.modo
        self._vigia.start()

    def _mirar_fin(self):
        modo = self._esperando
        if modo is None or modo != self.modo:
            self._vigia.stop()
            self._esperando = None
            return
        if modo == "ve":
            ocupado = self.mom is not None and self.mom.job is not None
            vacio = self.mom is None or not self.mom.results
        else:
            ocupado = self.kw is not None and not self.kw.b_go.isEnabled()     # (se apaga mientras busca)
            vacio = not getattr(self.kw, "hits", [])
        if ocupado:
            return
        self._vigia.stop()
        self._esperando = None
        self.btn_internet.setVisible(vacio)

    def _mirar_nombre(self):
        if self.modo != "nombre":
            return
        lib = self.lib
        q = lib.search.text().strip()
        hay = False
        for i in range(lib.tree.topLevelItemCount()):
            top = lib.tree.topLevelItem(i)
            if not top.isHidden() and any(not top.child(j).isHidden() for j in range(top.childCount())):
                hay = True
                break
        lib.zona_resultados.setVisible(bool(q) and not hay)
        self.pila.setVisible(False if (q and not hay) else True)
        self.btn_internet.setVisible(bool(q) and not hay)

    def buscar_en_internet(self):
        texto = self.lib.search.text().strip()
        dw = getattr(self.win, "descargas_web", None)
        if dw is None:
            return
        self.win.show_panel(dw)
        try:
            dw.buscar_imagenes(texto)
        except Exception:  # noqa: BLE001 - al menos abierto, con el texto en su caja
            campo = getattr(dw, "campo_img", None) or getattr(dw, "campo", None)
            if campo is not None:
                campo.setText(texto)


def instalar(win) -> BuscadorMedios | None:
    try:
        return BuscadorMedios(win)
    except Exception:  # noqa: BLE001 - Medios sigue con su caja de siempre
        import traceback
        traceback.print_exc()
        return None
