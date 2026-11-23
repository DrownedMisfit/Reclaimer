"""
⚡ Menú rápido del clip en el hueco del visor (22/11, lo pidió el usuario).

En un proyecto Vertical (y en cualquier formato cuando sobra ancho) a los lados de la imagen queda un espacio negro
vacío. Con un clip de video o imagen elegido, ahí sale una columna con lo que más se usa con él: Transformar,
Recortar, Zoom dinámico, Encuadrar (vertical), Voltear, Velocidad, Opacidad, Sombra, Quitar bandas y Fundidos.

  · No duplica nada: cada botón llama a lo MISMO que el Inspector, el panel Efectos y el modo del visor, y abre su
    sección del Inspector con el foco donde se trabaja (regla «cada acción abre su panel»).
  · Sin clip elegido, no hay nada (ni un panel vacío).
  · Nunca tapa la imagen: va en el hueco de la DERECHA del cuadro. Si no cabe con nombres, solo iconos (tira fina);
    si ni así, se esconde. Si la columna no cabe de alto, pasa a dos columnas.
  · Iconos monocromos (Lucide), la explicación en el tooltip, medidas con «Letra».

instalar(win) lo engancha a la ventana principal (una línea en main_window).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QToolButton, QWidget

from . import diseno as D

# (clave, icono, nombre, explicación del tooltip)
ACCIONES = (
    ("transformar", "move", "Transformar",
     "Mover y cambiar el tamaño en el visor: esquinas = tamaño sin deformar, lados = recortar, Alt = deformar.\n"
     "Abre Inspector → Transformar."),
    ("recortar", "crop", "Recortar",
     "Recortar los bordes arrastrando en el visor (modo Recortar). Abre Inspector → Recorte."),
    ("suavizar", "square-dashed", "Suavizar bordes",
     "El borde (o lo recortado) se desvanece a transparente en vez de un corte seco (un 5 % del lado corto).\n"
     "Otra vez = corte seco. Con bordes suaves el contorno no se pinta. Ajuste fino: Inspector → Recorte."),
    ("zoom", "zoom-in", "Zoom dinámico",
     "Zoom que va del recuadro verde (al empezar el clip) al rojo (al acabar). Abre Inspector → Zoom dinámico."),
    ("encuadrar", "scan", "Encuadrar",
     "Proyecto vertical: el video entero en el centro con arriba y abajo borroso (su propia imagen).\n"
     "Abre Inspector → Reencuadre vertical (también «Seguir la acción»)."),
    ("voltear", "flip-horizontal-2", "Voltear",
     "Voltear la imagen en horizontal (como un espejo). Otra vez = como estaba. Ctrl+Z lo deshace."),
    ("velocidad", "gauge", "Velocidad",
     "Más rápido, más lento, marcha atrás o congelar. Abre Inspector → Velocidad (tecla R)."),
    ("opacidad", "blend", "Opacidad",
     "Transparencia y modo de fusión. Abre Inspector → Composición."),
    ("sombra", "sombra", "Sombra",
     "Sombra suave detrás (sigue la forma de un PNG recortado). Abre Inspector → Efectos → Sombra."),
    ("bandas", "quitar-bandas", "Quitar bandas",
     "Quitar las bandas negras grabadas dentro del video (se detectan solas). Otra vez = devolverlas."),
    ("fundidos", "fundidos", "Fundidos",
     "Fundido de entrada y de salida del clip. Abre Inspector → Efectos → Fundidos."),
)
MODOS = {"transformar": "transform", "recortar": "crop", "zoom": "dynzoom"}


class MenuRapido(QWidget):
    """La columna de botones, hija del área de dibujo del visor (posición calculada a mano: nunca encima del cuadro)."""

    def __init__(self, win):
        self.win = win
        self.canvas = win.preview.canvas
        super().__init__(self.canvas.viewport())
        self.setObjectName("menu_rapido_visor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.botones: dict[str, QToolButton] = {}
        for clave, icono, nombre, tip in ACCIONES:
            b = QToolButton(self)
            b.setText(nombre)
            b.setProperty("icono", icono)
            b.setProperty("expl", tip)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRaise(True)
            b.setCheckable(clave in MODOS)
            b.clicked.connect(lambda _on=False, k=clave: self.hacer(k))
            self.botones[clave] = b
        self._modo = None                   # "nombres" | "iconos" | None (escondido)
        self._geo = None
        self._clip = None
        D.medida(self, lambda w: (w._estilo(), setattr(w, "_geo", None), w.recolocar()))   # (con «Letra»)
        self.hide()
        self.canvas.viewport().installEventFilter(self)
        self.canvas.mode_changed.connect(lambda _m: self._marcar_modo())
        self.canvas.view_zoom_changed.connect(lambda _z: self.recolocar())
        self._t = QTimer(self)                # (varias señales seguidas = una sola actualización)
        self._t.setSingleShot(True)
        self._t.setInterval(0)
        self._t.timeout.connect(self.actualizar)

    # ------------------------------------------------------------------ aspecto
    def _estilo(self):
        c, f = D.colores(), D.fichas()
        self.setStyleSheet(
            f"#menu_rapido_visor {{ background: {f['bloque']}; border: 1px solid {f['bloque_borde']}; "
            f"border-radius: {D.px(6)}px; }}"
            f"#menu_rapido_visor QToolButton {{ color: {c['texto']}; border: 1px solid transparent; "
            f"border-radius: {D.px(4)}px; padding: {D.px(2)}px {D.px(5)}px; text-align: left; }}"
            f"#menu_rapido_visor QToolButton:hover {{ background: {f['control_hover_arriba']}; "
            f"border-color: {f['control_borde']}; }}"
            f"#menu_rapido_visor QToolButton:checked {{ background: {c['acento']}; color: {c['sobre_acento']}; }}"
            f"#menu_rapido_visor QToolButton[aviso=\"true\"] {{ border-color: {c['acento']}; }}")
        for b in self.botones.values():
            b.setFont(D.fuente(D.LETRA_P))
            b.setIconSize(QSize(D.px(16), D.px(16)))
            self._pintar_icono(b)

    def _pintar_icono(self, b):
        c = D.colores()
        col = c["sobre_acento"] if b.isChecked() else (c["acento"] if b.property("aviso") else c["texto"])
        b.setIcon(D.icono(b.property("icono"), col, 16))

    # ------------------------------------------------------------------ qué clip y qué se ve
    def _clip_elegido(self):
        """El clip de video o imagen elegido (uno solo) o None."""
        if not getattr(self.canvas, "framing_enabled", False):
            return None
        ids = list(getattr(self.win.inspector, "_ids", []) or [])
        p = self.win.ctrl.project
        c = p.clips.get(ids[0]) if len(ids) == 1 else None
        m = p.media_of(c) if c is not None else None
        return c if (c is not None and m is not None and m.kind in ("video", "image") and c.text is None) else None

    def pedir(self, *_a):
        self._t.start()

    def _host(self):
        return getattr(self.win, "herramientas", None)

    def alto_necesario(self) -> int:
        """Lo que mide la columna con los botones que se ven (para que el panel de herramientas no sea más alto)."""
        n = sum(1 for k, b in self.botones.items() if not b.isHidden()) or len(self.botones)
        sep = D.px(2)
        return n * (D.px(26) + sep) - sep + 2 * sep + 2 + 2 * D.px(6) + D.px(2)

    def actualizar(self):
        c = self._clip_elegido()
        self._clip = c.id if c is not None else None
        host = self._host()
        dentro = host.poner_clip(c is not None) if host is not None else False   # 🧰 delante, en el panel
        if c is None or (host is not None and not dentro and host.donde == "hueco" and host.visible):
            self.hide()                    # (sin clip, o la herramienta va delante en el mismo hueco)
            self._geo = None
            return
        p = self.win.ctrl.project
        m = p.media_of(c)
        es_video = m.kind == "video"
        self.botones["encuadrar"].setVisible(p.height > p.width)
        self.botones["velocidad"].setVisible(es_video)
        self.botones["bandas"].setVisible(es_video)
        aviso = False
        if es_video:                       # ▭ ¿ya se sabe que trae bandas grabadas (y no se han quitado)?
            from ..core import black_bars as BB
            try:
                hit, area = BB.cached(m.path)
            except Exception:  # noqa: BLE001 - sin caché legible: sin aviso
                hit, area = False, None
            quitadas = bool(BB.of(c.layout))
            aviso = bool(hit and area and not quitadas)
            b = self.botones["bandas"]
            b.setText("Devolver bandas" if quitadas else "Quitar bandas")
            b.setProperty("expl", "Devolver las bandas negras que se quitaron. Ctrl+Z también." if quitadas else
                          ("Este video trae bandas negras grabadas. " if aviso else "") + next(x[3] for x in ACCIONES if x[0] == "bandas"))
        self.botones["bandas"].setProperty("aviso", aviso)
        self.botones["bandas"].style().unpolish(self.botones["bandas"])
        self.botones["bandas"].style().polish(self.botones["bandas"])
        from ..core import decor
        sb = self.botones["suavizar"]
        sb.setProperty("aviso", decor.suavizar_of(c.fx) > 0)       # (encendido: con el borde del acento)
        sb.style().unpolish(sb)
        sb.style().polish(sb)
        self._marcar_modo()
        self._geo = None
        if host is not None and host.clip_delante():
            host.recolocar()               # (el panel, al alto de los botones de ESTE clip)
        self.recolocar()

    def _marcar_modo(self):
        modo = getattr(self.canvas, "mode", "transform")
        for k, m in MODOS.items():
            b = self.botones[k]
            if b.isChecked() != (modo == m):
                b.setChecked(modo == m)
        for b in self.botones.values():
            self._pintar_icono(b)

    def eventFilter(self, obj: QObject, ev) -> bool:
        if obj is self.canvas.viewport() and ev.type() in (QEvent.Resize, QEvent.Paint) and self._clip:
            self.recolocar()                 # (barato: solo se mueve si el cuadro cambió de sitio)
        return False

    def _hueco(self) -> QRect | None:
        """El hueco a la derecha del cuadro, en coordenadas del área de dibujo (None = no hay). Con el panel de
        herramientas abierto en el hueco, su sitio dentro del panel (va delante, en la pestaña «Clip»)."""
        host = self._host()
        if host is not None and host.clip_delante():
            r = host.rect_clip()
            if r is not None and r.width() > 0:
                QTimer.singleShot(0, self.recolocar)     # (el panel puede estar recolocándose: otra vez luego)
                return r
        vp = self.canvas.viewport()
        fr = self.canvas.mapFromScene(self.canvas.frame.rect()).boundingRect()
        izq = max(0, fr.right() + 1)
        if izq >= vp.width():
            return None
        return QRect(izq, 0, vp.width() - izq, vp.height())

    def recolocar(self):
        if not self._clip:
            return
        hueco = self._hueco()
        visibles = [b for b in self.botones.values() if not b.isHidden()]
        clave = (hueco.getRect() if hueco else None, len(visibles), D.escala())
        if clave == self._geo:
            return
        self._geo = clave
        if hueco is None or not visibles:
            self.hide()
            return
        m, sep = D.px(6), D.px(2)                       # margen con el borde
        mi = D.px(20)                                   # (con el cuadro: deja libre la zona de agarre de sus asas)
        alto_b = D.px(26)
        for modo in ("nombres", "iconos"):
            for b in visibles:
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if modo == "nombres" else Qt.ToolButtonIconOnly)
                b.setToolTip(b.property("expl") if modo == "nombres" else f"{b.text()}\n{b.property('expl')}")
            ancho_b = max(b.sizeHint().width() for b in visibles) if modo == "nombres" else D.px(30)
            filas = max(1, (hueco.height() - 2 * m - 2 * sep) // (alto_b + sep))
            cols = -(-len(visibles) // filas)
            filas = -(-len(visibles) // cols)
            w = cols * ancho_b + (cols - 1) * sep + 2 * sep + 2
            h = filas * (alto_b + sep) - sep + 2 * sep + 2
            if w + mi + m <= hueco.width() and h + 2 * m <= hueco.height():
                break
        else:
            self.hide()                                 # (ni la tira fina cabe: nunca encima de la imagen)
            self._modo = None
            return
        self._modo = modo
        for i, b in enumerate(visibles):
            col, fila = divmod(i, filas)
            b.setGeometry(sep + 1 + col * (ancho_b + sep), sep + 1 + fila * (alto_b + sep), ancho_b, alto_b)
        x = hueco.left() + mi
        y = max(m, min(hueco.height() - h - m, hueco.center().y() - h // 2))
        host = self._host()
        if host is not None and host.clip_delante():    # 🧰 dentro del panel: pegado arriba, sin hueco encima
            x, y = hueco.left() + D.px(2), hueco.top()
        self.setGeometry(x, y, w, h)
        self.show()
        self.raise_()

    # ------------------------------------------------------------------ hacer (lo MISMO que el resto de la app)
    def hacer(self, clave: str):
        win, ins, cv = self.win, self.win.inspector, self.canvas
        c = self.win.ctrl.project.clips.get(self._clip or "")
        if c is None:
            return
        if clave in MODOS:
            cv.set_mode(MODOS[clave])
            destino = {"transformar": (ins.transform_box, ins.transform_box.w),
                       "recortar": (ins.crop_box, ins.crop_spins.get("l")),
                       "zoom": (ins.frame_box, None)}[clave]
            win.abrir_para_usar(*destino)
        elif clave == "encuadrar":
            win.abrir_para_usar(ins.btn_reenc_borroso)
            ins.btn_reenc_borroso.click()
        elif clave == "voltear":
            win.abrir_para_usar(ins.transform_box, ins.transform_box.fh)
            ins.transform_box.fh.click()
        elif clave == "velocidad":
            win.abrir_para_usar(ins.speed_box, ins.speed)
        elif clave == "opacidad":
            win.abrir_para_usar(ins.blend_box, ins.opacity)
        elif clave == "sombra":
            win.effects.add_shadow()
        elif clave == "bandas":
            if set(win.timeline.selected) != {c.id}:
                win.timeline.set_selection([c.id])
            win.remove_black_bars()
        elif clave == "suavizar":
            on = not ins.suave_on.isChecked()
            win.abrir_para_usar(ins.crop_box, ins.suave_val)
            ins.suave_on.setChecked(on)
        elif clave == "fundidos":
            sp = ins.fx_spins.get("fade_in")
            win.abrir_para_usar(ins.effects_box, sp)
        self._marcar_modo()
        self.pedir()


def instalar(win) -> MenuRapido | None:
    """Crea el menú rápido del visor y lo engancha (elegir clips, cambios del proyecto, el cabezal)."""
    try:
        menu = MenuRapido(win)
    except Exception:  # noqa: BLE001 - el visor sigue funcionando sin el menú
        return None
    win.timeline.selection_changed.connect(menu.pedir)
    win.ctrl.project_changed.connect(menu.pedir)
    menu.pedir()
    return menu
