"""
🎬 Plantillas de Escenas (sección «Plantillas» del lateral): empezar rápido sin montar nada desde cero.

  Pantalla dividida (2, 3 y 4) · Imagen en imagen (esquina) · Reacción (cámara pequeña + contenido grande) ·
  Antes / después · Meme (texto arriba y abajo) · Collage.

Al elegir una se crean sus HUECOS (capas con una imagen de «suelta aquí», act["hueco"] = True) y sus TEXTOS
(act["texto"], que se cambian en el panel de la derecha); solo queda soltar el material encima de cada hueco (desde
Personajes, Medios o la lista de capas), o elegir el hueco y «Cambiar imagen». Si la escena ya tenía algo, la plantilla
empieza una escena nueva (la de ahora no se pierde: si tenía cambios, te pregunta).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QListWidgetItem, QVBoxLayout, QWidget

from . import diseno as D

GAP = 0.02

PLANTILLAS = (
    ("dividida_2", "Pantalla dividida en 2", "Dos huecos lado a lado (en vertical, uno encima del otro)"),
    ("dividida_3", "Pantalla dividida en 3", "Tres huecos iguales"),
    ("dividida_4", "Pantalla dividida en 4", "Cuatro huecos en cuadrícula"),
    ("pip", "Imagen en imagen", "Un hueco grande y otro pequeño en la esquina, con borde y sombra"),
    ("reaccion", "Reacción", "El contenido grande y la cámara pequeña abajo, con esquinas suaves, borde y sombra"),
    ("antes_despues", "Antes / después", "Dos mitades con su texto «ANTES» y «DESPUÉS» (se cambia a la derecha)"),
    ("meme", "Meme", "Una imagen con texto arriba y abajo (el texto se cambia a la derecha)"),
    ("collage", "Collage", "Seis huecos en cuadrícula con un borde fino"),
)
NOMBRES = {k: n for k, n, _t in PLANTILLAS}


def _rejilla(cols: int, filas: int, gap: float = GAP) -> list[dict]:
    w = (1 - gap * (cols + 1)) / cols
    h = (1 - gap * (filas + 1)) / filas
    return [{"x": round(gap + c * (w + gap), 4), "y": round(gap + r * (h + gap), 4), "w": round(w, 4),
             "h": round(h, 4)} for r in range(filas) for c in range(cols)]


def piezas(clave: str, vertical: bool) -> list[dict]:
    """[{"caja", "tipo": "hueco" | "texto", "texto"?, "ajustes"?}] de la plantilla (de atrás adelante)."""
    def huecos(cajas, ajustes=None):
        return [{"caja": dict(c, fit="cover", bg="none"), "tipo": "hueco", "ajustes": dict(ajustes or {})}
                for c in cajas]
    if clave in ("dividida_2", "dividida_3"):
        n = 2 if clave == "dividida_2" else 3
        return huecos(_rejilla(1, n) if vertical else _rejilla(n, 1))
    if clave == "dividida_4":
        return huecos(_rejilla(2, 2))
    if clave == "collage":
        return huecos(_rejilla(2, 3) if vertical else _rejilla(3, 2), {"borde": 0.012})
    if clave == "pip":
        pequeña = {"x": 0.55, "y": 0.04, "w": 0.41, "h": 0.24} if vertical else {"x": 0.64, "y": 0.05, "w": 0.32,
                                                                                    "h": 0.32}
        return huecos([{"x": 0, "y": 0, "w": 1, "h": 1}]) + huecos([pequeña], {"borde": 0.012, "sombra": 0.45})
    if clave == "reaccion":
        cam = {"x": 0.52, "y": 0.66, "w": 0.44, "h": 0.3} if vertical else {"x": 0.66, "y": 0.56, "w": 0.3, "h": 0.4}
        return huecos([{"x": 0, "y": 0, "w": 1, "h": 1}]) + \
            huecos([cam], {"redondeo": 0.06, "borde": 0.012, "sombra": 0.45})
    if clave == "antes_despues":
        mitades = _rejilla(1, 2, 0.0) if vertical else _rejilla(2, 1, 0.0)
        out = huecos(mitades)
        for c, t in zip(mitades, ("ANTES", "DESPUÉS")):
            out.append({"caja": {"x": round(c["x"] + 0.02, 4), "y": round(c["y"] + 0.02, 4),
                                 "w": round(c["w"] - 0.04, 4), "h": round(min(0.14, c["h"] * 0.22), 4),
                                 "fit": "contain", "bg": "none"}, "tipo": "texto", "texto": t})
        return out
    if clave == "meme":
        return huecos([{"x": 0.06, "y": 0.18, "w": 0.88, "h": 0.64}]) + [
            {"caja": {"x": 0.03, "y": 0.02, "w": 0.94, "h": 0.15, "fit": "contain", "bg": "none"}, "tipo": "texto",
             "texto": "TEXTO DE ARRIBA"},
            {"caja": {"x": 0.03, "y": 0.83, "w": 0.94, "h": 0.15, "fit": "contain", "bg": "none"}, "tipo": "texto",
             "texto": "TEXTO DE ABAJO"}]
    return []


def ruta_hueco() -> str:
    """La imagen de «suelta aquí» de los huecos (con las de las prehechas: no sale en la lista de Local)."""
    from PIL import Image, ImageDraw

    from ..core.escenas_prehechas import _carpeta, _fuente
    ruta = os.path.join(_carpeta(), "Hueco para soltar.png")
    if os.path.isfile(ruta):
        return ruta
    im = Image.new("RGBA", (640, 640), (38, 42, 50, 215))
    d = ImageDraw.Draw(im)
    for i in range(0, 640, 32):                        # (borde de rayas)
        for x0, y0, x1, y1 in ((i, 0, i + 16, 6), (i, 634, i + 16, 640), (0, i, 6, i + 16), (634, i, 640, i + 16)):
            d.rectangle((x0, y0, x1, y1), fill=(230, 230, 235, 230))
    d.text((320, 300), "+", font=_fuente(220), anchor="mm", fill=(235, 235, 240, 240))
    d.text((320, 470), "Suelta aquí", font=_fuente(56), anchor="mm", fill=(235, 235, 240, 220))
    im.save(ruta)
    return ruta


def aplicar(page, clave: str) -> list[dict]:
    """Crea los huecos y textos de la plantilla en la escena de la página (una nueva si ya tenía algo)."""
    from ..core import escena_ajustes, scenes
    if clave not in NOMBRES:
        return []
    nueva = page._tiene_contenido()
    if nueva:                                          # (la plantilla empieza una escena nueva: Ctrl+Z vuelve a ella
        if page.sucia and not page._descartar_ok():    # vacía; la de antes, si tenía cambios, se pregunta)
            return []
        page._cargar(page._nueva_desde_marcas(), True)
    p = page.ctrl.project
    vertical = p.height > p.width
    total = scenes.largo(page.escena)
    hueco = page._media_de_ruta(ruta_hueco(), "Escenas")
    hechos = []
    for pz in piezas(clave, vertical):
        if pz["tipo"] == "texto":
            mid = page._media_de_ruta(escena_ajustes.texto_png(pz["texto"]), "Escenas")
        else:
            mid = hueco
        if not mid:
            continue
        act = scenes.nuevo_actor(page.escena, mid, pz["caja"])
        act["fases"] = [{"tipo": "accion", "anim": "ninguna", "dur": round(total, 3), "auto": True}]
        if pz["tipo"] == "texto":
            act["texto"] = {"t": pz["texto"], "color": "#FFFFFF"}
        else:
            act["hueco"] = True
            if pz.get("ajustes"):
                act["ajustes"] = dict(pz["ajustes"])
        hechos.append(act)
    if not page.escena.get("nombre") or page.escena["nombre"].startswith("Escena "):
        page.escena["nombre"] = NOMBRES[clave]
        page.nombre.setText(NOMBRES[clave])
    page._ensuciar()
    page._reconstruir()
    page.lateral.abrir("capas")
    page.win.statusBar().showMessage(f"«{NOMBRES[clave]}»: suelta tus imágenes o videos encima de cada hueco (o elige "
                                     "uno y «Cambiar imagen»). Ctrl+Z quita la plantilla."
                                     + (" Empezó como escena nueva: la de antes sigue en la lista de «Escena» si "
                                        "estaba aplicada." if nueva else ""), 10000)
    return hechos


def poner_en_hueco(page, act: dict, media_id: str) -> None:
    """El material soltado en un hueco: pasa a ser su imagen (con los ajustes de la plantilla: borde, sombra…)."""
    from .escenas_ajustes_ui import aplicar_ajustes
    act.pop("hueco", None)
    act["base_media"] = media_id
    act["media_id"] = media_id
    act.pop("horneado_de", None)
    aplicar_ajustes(page, act, ahora=True)


def _vista(clave: str) -> QPixmap:
    """La miniatura de la plantilla: sus cajas dibujadas en monocromo (16:9)."""
    w, h = D.px(64), D.px(36)
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(D.colores()["tenue"])
    p.setPen(QPen(col, 1))
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    for pz in piezas(clave, False):
        c = pz["caja"]
        r = QRectF(c["x"] * w + 1.5, c["y"] * h + 1.5, c["w"] * w - 3, c["h"] * h - 3)
        if pz["tipo"] == "texto":
            p.fillRect(QRectF(r.x() + r.width() * 0.2, r.center().y() - 1, r.width() * 0.6, 2), col)
        else:
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 70))
            p.drawRoundedRect(r, 2, 2)
    p.end()
    return pm


class PanelPlantillas(QWidget):
    def quiere_crecer(self) -> bool:
        return True

    def __init__(self, page):
        super().__init__()
        self.page = page
        v = QVBoxLayout(self)
        v.setContentsMargins(D.px(D.M1), D.px(D.M1), D.px(D.M1), D.px(D.M1))
        self.lista = D.ListaAdaptable(clave="", ancho_min=150, max_columnas=2)
        self.lista.setIconSize(QSize(D.px(64), D.px(36)))
        self.lista.setToolTip("Clic = crear sus huecos; luego suelta tu material encima de cada uno")
        for clave, nombre, tip in PLANTILLAS:
            it = QListWidgetItem(QIcon(_vista(clave)), nombre)
            it.setData(Qt.UserRole, clave)
            it.setToolTip(tip)
            self.lista.addItem(it)
        self.lista.itemClicked.connect(lambda it: aplicar(self.page, it.data(Qt.UserRole)))
        v.addWidget(self.lista, 1)
