"""
🎬 Capas de Escenas (sección «Capas» del lateral izquierdo de la página).

  · Lista de capas: miniatura, nombre entero, ojo (se ve o no: tampoco sale al aplicar ni al exportar) y candado (no se
    mueve ni se elige en el lienzo; sí desde la lista). La de ARRIBA se ve delante. Arrastrar una fila = ponerla delante
    o detrás. Clic = elegirla.
  · Alinear (izquierda, centro, derecha, arriba, medio, abajo) respecto al lienzo y repartir (en horizontal o en
    vertical, con el mismo espacio entre centros) las capas que se ven y no están bloqueadas. Duplicar (Ctrl+D).
  · iman(...): guías magnéticas al mover una capa en el lienzo: centro y bordes del lienzo y bordes y centros de las
    otras capas (Ctrl al arrastrar = sin imán). El visor dibuja las guías (_Visor.guias).
  · empujar(page, dx, dy): flechas = 1 px del proyecto, Mayús + flechas = 10 px.
Todo cambia la escena de la página (page.escena) y pasa por su Ctrl+Z propio (page._ensuciar).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import diseno as D
from . import theme as T

MINI = 36
IMAN_PX = 7          # (a cuántos píxeles de pantalla se pega)


# ------------------------------------------------------------------------------------------------ imán y guías
def iman(page, actor_id: str, x: float, y: float, w: float, h: float, escala: float):
    """(x, y) pegados a la guía más cercana (en unidades del visor de la escena) y las guías a dibujar
    [("v" | "h", posición)]. escala = píxeles de pantalla por unidad (para que el imán mida lo mismo con zoom)."""
    if QApplication.keyboardModifiers() & Qt.ControlModifier:
        return x, y, []
    W, H = float(page.W), float(page.H)
    xs, ys = [0.0, W / 2, W], [0.0, H / 2, H]
    for aid, it in page._items.items():
        act = page._actor(aid)
        if aid == actor_id or not it.isVisible() or act is None or act.get("oculto"):
            continue
        r = it.rect().translated(it.pos())
        xs += [r.left(), r.center().x(), r.right()]
        ys += [r.top(), r.center().y(), r.bottom()]
    lim = IMAN_PX / max(1e-3, escala)
    guias = []

    def pegar(v0: float, largo: float, cands: list[float], tipo: str) -> float:
        mejor = None
        for k, desde in ((0.0, v0), (0.5, v0 + largo / 2), (1.0, v0 + largo)):
            for c in cands:
                d = c - desde
                if abs(d) <= lim and (mejor is None or abs(d) < abs(mejor[0])):
                    mejor = (d, c)
        if mejor is None:
            return v0
        guias.append((tipo, mejor[1]))
        return v0 + mejor[0]
    return pegar(x, w, xs, "v"), pegar(y, h, ys, "h"), guias


# ------------------------------------------------------------------------------------------------ alinear / repartir
def _caja(act: dict) -> dict:
    return act["caja"]


def alinear(page, modo: str) -> bool:
    """La capa elegida respecto al lienzo: izquierda | centro_h | derecha | arriba | centro_v | abajo."""
    act = page._actor_elegido()
    if act is None or act.get("bloqueado"):
        page.win.statusBar().showMessage("Elige antes una capa (que no esté bloqueada).", 4000)
        return False
    c = _caja(act)
    w, h = float(c["w"]), float(c["h"])
    if modo == "izquierda":
        c["x"] = 0.0
    elif modo == "centro_h":
        c["x"] = round((1 - w) / 2, 4)
    elif modo == "derecha":
        c["x"] = round(1 - w, 4)
    elif modo == "arriba":
        c["y"] = 0.0
    elif modo == "centro_v":
        c["y"] = round((1 - h) / 2, 4)
    elif modo == "abajo":
        c["y"] = round(1 - h, 4)
    else:
        return False
    page._ensuciar()
    page._poner_en_reposo()
    return True


def repartir(page, eje: str) -> bool:
    """Las capas que se ven y no están bloqueadas, con el mismo espacio entre sus centros (de la primera a la última,
    que no se mueven). eje = "h" | "v". Hacen falta 3 o más."""
    acts = [a for a in page.escena["actores"] if not a.get("oculto") and not a.get("bloqueado")
            and not a.get("efecto")]
    if len(acts) < 3:
        page.win.statusBar().showMessage("Para repartir hacen falta 3 capas o más (visibles y sin bloquear).", 5000)
        return False
    k, t = ("x", "w") if eje == "h" else ("y", "h")
    acts.sort(key=lambda a: float(_caja(a)[k]) + float(_caja(a)[t]) / 2)
    c0 = float(_caja(acts[0])[k]) + float(_caja(acts[0])[t]) / 2
    c1 = float(_caja(acts[-1])[k]) + float(_caja(acts[-1])[t]) / 2
    paso = (c1 - c0) / (len(acts) - 1)
    for i, a in enumerate(acts[1:-1], start=1):
        _caja(a)[k] = round(c0 + paso * i - float(_caja(a)[t]) / 2, 4)
    page._ensuciar()
    page._poner_en_reposo()
    return True


def empujar(page, dx_px: int, dy_px: int) -> bool:
    """Flechas: la capa elegida se mueve dx, dy píxeles DEL PROYECTO (1 o 10 con Mayús)."""
    act = page._actor_elegido()
    if act is None or act.get("bloqueado"):
        return False
    p = page.ctrl.project
    c = _caja(act)
    c["x"] = round(float(c["x"]) + dx_px / max(1, p.width), 6)
    c["y"] = round(float(c["y"]) + dy_px / max(1, p.height), 6)
    page._ensuciar()
    page._poner_en_reposo()
    return True


# ------------------------------------------------------------------------------------------------ la lista
def _mini(pix: QPixmap | None, lado: int) -> QPixmap:
    pm = QPixmap(lado, lado)
    pm.fill(QColor("#15171a"))
    p = QPainter(pm)
    c = max(3, lado // 6)
    for y in range(0, lado, c):
        for x in range(0, lado, c):
            if (x // c + y // c) % 2:
                p.fillRect(x, y, c, c, QColor("#1d2024"))
    if pix is not None and not pix.isNull():
        im = pix.scaled(QSize(lado, lado), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap((lado - im.width()) // 2, (lado - im.height()) // 2, im)
    p.end()
    return pm


class FilaCapa(QWidget):
    """Una capa en la lista: miniatura · nombre (entero) · ojo · candado."""

    def __init__(self, panel, act: dict, nombre: str, pix: QPixmap | None):
        super().__init__()
        from .escenas_resultados import EtiquetaPartida
        self.panel, self.actor_id = panel, act["id"]
        h = D.fila_fija(QHBoxLayout(self))
        h.setContentsMargins(D.px(D.M1), D.px(2), D.px(D.M1), D.px(2))
        h.setSpacing(D.px(D.M2))
        self.mini = QLabel()
        self.mini.setPixmap(_mini(pix, D.px(MINI)))
        self.mini.setFixedSize(D.px(MINI), D.px(MINI))
        h.addWidget(self.mini)
        self.nombre = EtiquetaPartida(nombre)
        D.poner_letra(self.nombre, D.LETRA_M, T.TEXT_DIM if act.get("oculto") else None)
        h.addWidget(self.nombre, 1)
        oculto, bloq = bool(act.get("oculto")), bool(act.get("bloqueado"))
        self.b_ojo = D.BotonIcono("eye-off" if oculto else "eye",
                                  "Se ve. Clic = ocultarla (oculta NO sale en la línea de tiempo ni al exportar)" if not oculto
                                  else "Oculta: NO sale en la línea de tiempo ni al exportar (clic = que se vea)", plano=True)
        self.b_candado = D.BotonIcono("lock" if bloq else "lock-open",
                                      "Bloqueada: no se mueve ni se elige en el lienzo (clic = desbloquear)" if bloq
                                      else "Clic = bloquearla: no se mueve ni se elige en el lienzo (sí desde aquí)",
                                      plano=True)
        for b in (self.b_ojo, self.b_candado):
            b.setFocusPolicy(Qt.NoFocus)
            h.addWidget(b)
        self.b_ojo.clicked.connect(lambda: self.panel.alternar(self.actor_id, "oculto"))
        self.b_candado.clicked.connect(lambda: self.panel.alternar(self.actor_id, "bloqueado"))


class _ListaCapas(QListWidget):
    """Lista que se reordena arrastrando (la fila de arriba = delante)."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def dropEvent(self, e):
        super().dropEvent(e)
        self.panel.orden_cambiado([self.item(i).data(Qt.UserRole) for i in range(self.count())])


class PanelCapas(QWidget):
    """La sección «Capas»: botones de alinear / repartir / duplicar y la lista de capas."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self._cargando = False
        v = QVBoxLayout(self)
        v.setContentsMargins(D.px(D.M1), D.px(D.M1), D.px(D.M1), D.px(D.M1))
        v.setSpacing(D.px(D.M1))
        fila = D.fila_fija(QHBoxLayout())
        fila.setSpacing(D.px(D.M1))
        self.botones = {}
        for clave, icono, tip in (
                ("izquierda", "alinear-izquierda", "Alinear a la izquierda del lienzo"),
                ("centro_h", "alinear-centro-h", "Centrar en horizontal"),
                ("derecha", "alinear-derecha", "Alinear a la derecha del lienzo"),
                ("arriba", "alinear-arriba", "Alinear arriba del lienzo"),
                ("centro_v", "alinear-centro-v", "Centrar en vertical"),
                ("abajo", "alinear-abajo", "Alinear abajo del lienzo")):
            b = D.BotonIcono(icono, tip + " (la capa elegida)")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=clave: alinear(self.page, k))
            fila.addWidget(b)
            self.botones[clave] = b
        fila.addStretch(1)
        v.addLayout(fila)
        fila2 = D.fila_fija(QHBoxLayout())
        fila2.setSpacing(D.px(D.M1))
        for clave, icono, tip, fn in (
                ("repartir_h", "repartir-h", "Repartir en horizontal: el mismo espacio entre las capas que se ven "
                                             "(3 o más; la primera y la última no se mueven)",
                 lambda: repartir(self.page, "h")),
                ("repartir_v", "repartir-v", "Repartir en vertical: el mismo espacio entre las capas que se ven",
                 lambda: repartir(self.page, "v")),
                ("duplicar", "copy-plus", "Duplicar la capa elegida (Ctrl+D)", lambda: self.page.duplicar())):
            b = D.BotonIcono(icono, tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            fila2.addWidget(b)
            self.botones[clave] = b
        fila2.addStretch(1)
        v.addLayout(fila2)
        self.vacio = QLabel("Sin capas todavía")
        self.vacio.setToolTip("Añade personajes o imágenes desde «Personajes», o elige una plantilla: cada uno es una "
                              "capa. La de arriba de esta lista se ve delante.")
        D.poner_letra(self.vacio, D.LETRA_P, D.GRIS_TITULO)
        v.addWidget(self.vacio)
        self.lista = _ListaCapas(self)
        self.lista.setToolTip("La capa de arriba se ve delante: arrastra una fila para ponerla delante o detrás · "
                              "clic = elegirla · en el lienzo, Alt+clic elige la de debajo · flechas = 1 px, Mayús + "
                              "flechas = 10 px")
        self.lista.itemClicked.connect(lambda it: self.page._elegir_actor(it.data(Qt.UserRole)))
        v.addWidget(self.lista, 1)
        self.refrescar()

    def quiere_crecer(self) -> bool:
        return True

    def refrescar(self):
        pg = self.page
        self._cargando = True
        try:
            self.lista.clear()
            acts = list(reversed(pg.escena.get("actores", [])))        # (arriba = delante)
            for act in acts:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, act["id"])
                fila = FilaCapa(self, act, pg.nombre_capa(act), pg._pixmap(act["media_id"]))
                it.setSizeHint(QSize(10, max(D.px(MINI) + D.px(6), fila.sizeHint().height())))
                self.lista.addItem(it)
                self.lista.setItemWidget(it, fila)
            self.vacio.setVisible(not acts)
            self.lista.setVisible(bool(acts))
            self.marcar(getattr(pg, "_act_sel", None) if pg.tl.sel[0] in ("actor", "fase") else None)
        finally:
            self._cargando = False

    def marcar(self, act: dict | None):
        aid = act["id"] if isinstance(act, dict) else None
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            if it.data(Qt.UserRole) == aid:
                self.lista.setCurrentItem(it)
                return
        self.lista.clearSelection()

    def alternar(self, actor_id: str, clave: str):
        act = self.page._actor(actor_id)
        if act is None:
            return
        if act.get(clave):
            act.pop(clave, None)
        else:
            act[clave] = True
        self.page._ensuciar()
        self.page._reconstruir()

    def orden_cambiado(self, ids_arriba_abajo: list):
        pg = self.page
        por_id = {a["id"]: a for a in pg.escena["actores"]}
        nuevo = [por_id[i] for i in reversed(ids_arriba_abajo) if i in por_id]
        if len(nuevo) != len(pg.escena["actores"]) or [a["id"] for a in nuevo] == \
                [a["id"] for a in pg.escena["actores"]]:
            self.refrescar()
            return
        pg.escena["actores"][:] = nuevo
        pg._ensuciar()
        pg._reconstruir()
        pg.win.statusBar().showMessage("Orden de capas cambiado (la de arriba se ve delante). Ctrl+Z lo deshace.",
                                       4000)
