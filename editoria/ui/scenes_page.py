"""
🎬 Página «Escenas» (como las páginas de Resolve: ocupa la ventana; al volver, el editor queda tal cual).

Montas una escena animada en un tramo de la línea de tiempo (del segundo 15 al 19, por ejemplo):
  · Arriba: qué escena, 📚 mis animaciones (guardar / usar), «Empieza» (la mueve) y «Dura» (la estira entera),
    📍 dónde (cabezal, tramo I/O, una palabra clave, copias), el fondo (desenfocado, normal u oscurecido), ▶ reproducir,
    ✓ aplicar a la línea de tiempo y ← volver al editor.
  · Izquierda, «Material»: tus imágenes (mejor PNG recortados) y sonidos; con la parte solo local, también 🌐 buscar
    personajes en las wikis de los juegos y 🌐 buscar sonidos en internet.
  · Centro: el visor de la escena. Arrastra a cada personaje (la esquina amarilla cambia el tamaño).
  · Derecha: lo elegido (personaje, fase o sonido) y sus opciones.
  · Abajo: la línea de tiempo de la escena: una fila por personaje con sus fases (🟦 entrada → 🟧 acciones → 🟥 salida;
    arrastra el borde derecho para cambiar la duración, el cuerpo de la primera fase para que empiece más tarde) y
    las filas de sonidos (arrástralos al segundo exacto).
  · ⚡ Prehechas (pestaña de «Material»): escenas de acción listas (se disparan, pelea, uno contra un grupo, huye…)
    con sus papeles, sonidos, temblores y destellos (core/escenas_prehechas.py); todo editable después.
  · ◆ Auto clave (barra de la línea de la escena): animar a mano por claves; los rombos salen en la fila del personaje.
Nada toca el proyecto hasta «✓ Aplicar» (controller.apply_scene: un paso de Ctrl+Z). Las escenas se guardan en el
proyecto: doble clic en uno de sus clips (o «🎬 Escena» en esta página) para volver a abrirla.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGraphicsItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSlider, QSplitter, QStackedWidget,
                               QTabWidget, QVBoxLayout, QWidget)

from ..core import effects, image_anim, scenes, transform
from ..core.model import KIND_AUDIO, KIND_IMAGE
from .common import COLORS, fmt_time

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".opus")


def _hay(modulo: str) -> bool:
    """¿Está esa parte solo local? (en la versión publicada no viene)."""
    import importlib
    try:
        importlib.import_module(modulo)
        return True
    except ImportError:
        return False


def _opacidad(op_kf: list[dict], t: float) -> float:
    if not op_kf:
        return 1.0
    pts = sorted(op_kf, key=lambda k: k["t"])
    if t <= pts[0]["t"]:
        return float(pts[0]["v"])
    for a, b in zip(pts, pts[1:]):
        if t <= b["t"]:
            u = (t - a["t"]) / max(1e-9, b["t"] - a["t"])
            return float(a["v"]) + (float(b["v"]) - float(a["v"])) * u
    return float(pts[-1]["v"])


_MINIS: dict[tuple, object] = {}


def _miniatura(ruta: str):
    """Icono de 72 px leído ya reducido (no carga la imagen entera), en caché por archivo y fecha."""
    from PySide6.QtGui import QIcon, QImageReader
    try:
        clave = (ruta, os.path.getmtime(ruta))
    except OSError:
        return None
    if clave not in _MINIS:
        rd = QImageReader(ruta)
        sz = rd.size()
        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
            k = 72.0 / max(sz.width(), sz.height())
            rd.setScaledSize(QSize(max(1, int(sz.width() * k)), max(1, int(sz.height() * k))))
        img = rd.read()
        _MINIS[clave] = QIcon(QPixmap.fromImage(img)) if not img.isNull() else None
    return _MINIS[clave]


def estado_en(escena: dict, t_local: float) -> dict[str, dict]:
    """Dónde está cada personaje en el segundo t de la escena: {actor_id: {"box", "op", "dx", "dy"}} (los que no se
    ven en ese momento no salen)."""
    T = float(escena["a"]) + t_local
    out = {}
    for pz in scenes.piezas(escena):
        if pz["actor"] in out or not (pz["a"] - 1e-6 <= T < pz["b"] + 1e-6):
            continue
        s = T - pz["a"]
        pl = pz["plan"]
        box = dict(pl["layout"])
        if pl["layout_kf"]:
            box.update(transform.layout_value_at(pl["layout_kf"], s))
        dx, dy = effects.shake_at(pl["fx"], s)
        out[pz["actor"]] = {"box": box, "op": _opacidad(pl["op_kf"], s), "dx": dx, "dy": dy}
    return out


class _MiniVista(QWidget):
    """⚡ Vista previa animada (en bucle) de una prehecha, con siluetas de colores en lugar de los personajes."""
    COLORES = {"A": QColor(70, 130, 230), "B": QColor(220, 80, 70), "G": QColor(70, 180, 110), "": QColor(240, 200, 60)}

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.escena = None
        self.t = 0.0
        self.setMinimumHeight(110)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        import time as _time
        self._t0 = _time.monotonic()

    def poner(self, escena: dict | None):
        import time as _time
        self.escena = escena
        self._t0 = _time.monotonic()
        self.t = 0.0
        if escena is not None and not self._timer.isActive():
            self._timer.start()
        self.update()

    def _tick(self):
        import time as _time
        if self.escena is None or not self.isVisible():
            self._timer.stop()
            return
        self.t = (_time.monotonic() - self._t0) % (scenes.largo(self.escena) + 0.7)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.escena is not None:
            self._timer.start()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.page.W, self.page.H
        k = min(self.width() / W, self.height() / H)
        cw, ch = W * k, H * k
        r0 = QRectF((self.width() - cw) / 2, (self.height() - ch) / 2, cw, ch)
        p.fillRect(r0, QColor(38, 42, 50))
        if self.escena is None:
            p.setPen(QColor(150, 150, 160))
            p.drawText(r0, Qt.AlignCenter, "⚡")
            p.end()
            return
        actores = {a["id"]: a for a in self.escena["actores"]}
        st = estado_en(self.escena, min(self.t, scenes.largo(self.escena) - 1e-3))
        for i, a in enumerate(self.escena["actores"]):
            e = st.get(a["id"])
            if e is None:
                continue
            b = e["box"]
            r = QRectF(r0.x() + (b["x"] + e["dx"] * b["w"]) * cw, r0.y() + (b["y"] + e["dy"] * b["h"]) * ch,
                       b["w"] * cw, b["h"] * ch)
            p.setOpacity(max(0.0, min(1.0, e["op"])))
            if a.get("efecto") == "destello":
                p.fillRect(r0, QColor(255, 255, 255))
            elif a.get("prop"):
                f = QFont(self.font())
                f.setBold(True)
                f.setPixelSize(max(6, int(r.height() * 0.7)))
                p.setFont(f)
                p.setPen(QColor(255, 205, 40) if a["prop"] == "vs" else QColor(255, 80, 60))
                p.drawText(r, Qt.AlignCenter, "VS" if a["prop"] == "vs" else "!")
            else:
                col = QColor(self.COLORES.get(actores[a["id"]].get("papel", "A"), self.COLORES["A"]))
                if a.get("grupo"):
                    col = col.lighter(100 + 12 * (i % 3))
                fw = min(r.width(), r.height() * 0.45)
                cx = r.center().x()
                cabeza = fw * 0.55
                p.setPen(QPen(col.darker(160), 1))
                p.setBrush(col)
                p.drawEllipse(QRectF(cx - cabeza / 2, r.top(), cabeza, cabeza))
                p.drawRoundedRect(QRectF(cx - fw / 2, r.top() + cabeza * 1.05, fw, r.height() - cabeza * 1.05),
                                  fw * 0.3, fw * 0.3)
        p.setOpacity(1.0)
        p.end()


# ============================================================ visor de la escena
class _Actor(QGraphicsRectItem):
    """Un personaje en el visor: su imagen dentro de la caja. Se arrastra; la esquina amarilla cambia el tamaño."""
    ESQ = 14

    def __init__(self, actor_id: str, pix: QPixmap | None, al_cambiar, al_elegir):
        super().__init__(QRectF(0, 0, 100, 100))
        self.actor_id, self.pix = actor_id, pix
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.SizeAllCursor)
        self._al_cambiar, self._al_elegir = al_cambiar, al_elegir
        self._redim = None
        self.elegido = False
        self.editable = True
        self.flip = False                 # (↔ voltear la imagen)
        self.grabar = None                # (🎥 grabando su movimiento: la página recibe «pulsa» y «suelta»)
        self._cache: tuple | None = None

    def paint(self, painter, option, widget=None):
        r = self.rect()
        if self.pix is not None and not self.pix.isNull():
            s = min(r.width() / self.pix.width(), r.height() / self.pix.height())
            pw, ph = max(1, int(self.pix.width() * s)), max(1, int(self.pix.height() * s))
            if self._cache is None or self._cache[0] != (pw, ph):
                self._cache = ((pw, ph), self.pix.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            img = self._cache[1]
            if self.flip:
                from PySide6.QtGui import QTransform
                img = img.transformed(QTransform().scale(-1, 1))
            painter.drawPixmap(QPointF(r.x() + (r.width() - pw) / 2, r.y() + (r.height() - ph) / 2), img)
        if self.editable:
            painter.setPen(QPen(QColor("#f0c040" if self.elegido else "#9aa0aa"), 1.5, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)
            if self.elegido:
                painter.fillRect(QRectF(r.right() - self.ESQ, r.bottom() - self.ESQ, self.ESQ, self.ESQ),
                                 QColor("#f0c040"))

    def mousePressEvent(self, e):
        if self.grabar is not None and self.grabar("pulsa", self):     # 🎥 empieza a grabar mientras lo mueves
            super().mousePressEvent(e)
            return
        self._al_elegir(self.actor_id)
        if not self.editable:
            e.ignore()
            return
        r = self.rect()
        if e.pos().x() >= r.right() - self.ESQ and e.pos().y() >= r.bottom() - self.ESQ:
            self._redim = (e.pos(), QRectF(r))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._redim is not None:
            p0, r0 = self._redim
            d = e.pos() - p0
            self.prepareGeometryChange()
            self.setRect(QRectF(0, 0, max(20.0, r0.width() + d.x()), max(20.0, r0.height() + d.y())))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._redim = None
        super().mouseReleaseEvent(e)
        if self.grabar is not None:
            self.grabar("suelta", self)
            return
        if self.editable:
            self._al_cambiar(self.actor_id)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None and self.editable:
            r, sr = self.rect(), self.scene().sceneRect()     # (al menos un trozo siempre dentro de la pantalla)
            return QPointF(min(max(value.x(), sr.left() - r.width() * 0.75), sr.right() - r.width() * 0.25),
                           min(max(value.y(), sr.top() - r.height() * 0.75), sr.bottom() - r.height() * 0.25))
        return super().itemChange(change, value)


class _Visor(QGraphicsView):
    """La escena siempre entera y lo más grande posible en su zona. Se le puede soltar una imagen de «🧍 Personajes»:
    el personaje aparece donde la sueltas."""
    page = None

    def __init__(self, *a):
        super().__init__(*a)
        self.setAcceptDrops(True)

    def _de_lista(self, e) -> bool:
        pg = self.page
        return pg is not None and e.source() in (getattr(pg, "lista_img", None), getattr(pg, "res_img", None))

    def dragEnterEvent(self, e):
        if self._de_lista(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._de_lista(e):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not self._de_lista(e):
            return
        pt = self.mapToScene(e.position().toPoint())
        self.page._soltar_personaje(e.source(), pt.x() / self.page.W, pt.y() / self.page.H)
        e.acceptProposedAction()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def showEvent(self, e):
        super().showEvent(e)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


# ============================================================ línea de tiempo de la escena
class SceneTimeline(QWidget):
    """Filas: una por personaje (sus fases) y una por sonido. Regla arriba con el cabezal de la escena. Funciona como la
    línea de tiempo del editor: Ctrl + rueda acerca/aleja, la rueda desplaza, 🧲 imán (los bordes se pegan a los de
    los demás y a la línea roja, como en DaVinci Resolve), Ctrl+B o S corta, Supr borra, y «＋» al final de cada fila
    añade cosas a ese personaje en la línea roja. Los sonidos de «🔊 Sonidos» se sueltan aquí, en el segundo exacto."""
    cambiado = Signal()
    elegido = Signal(str, object)          # ("actor"|"fase"|"sonido"|"", objeto)
    cabezal = Signal(float)
    menu = Signal(str, object, object)     # (tipo, objeto, posición global)
    mas = Signal(object, object)           # «＋» de una fila: (actor, posición global)
    IZQ, DER, REGLA, FILA = 150, 34, 22, 30
    IMAN_PX = 8

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.t = 0.0
        self.sel: tuple[str, object] = ("", None)
        self._arr = None
        self.zoom = 1.0                    # 1 = toda la escena a la vista
        self.off = 0.0                     # segundo de la escena en el borde izquierdo (al acercar)
        self.iman = True
        self._guia = None                  # (x de la línea del imán mientras arrastras)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setToolTip("Ctrl + rueda: acercar/alejar · rueda: desplazar · Ctrl+B o S: cortar en la línea roja · "
                        "Supr: borrar · «＋»: añadir a ese personaje · arrastra un sonido aquí para ponerlo")

    # ---- geometría
    def escena(self) -> dict:
        return self.page.escena

    def _ancho(self) -> float:
        return max(40.0, self.width() - self.IZQ - self.DER)

    def _pps(self) -> float:
        return max(4.0, self._ancho() / scenes.largo(self.escena()) * self.zoom)

    def _visible(self) -> float:
        return self._ancho() / self._pps()

    def _ajustar_off(self):
        self.off = max(0.0, min(self.off, max(0.0, scenes.largo(self.escena()) - self._visible())))

    def x_de(self, t: float) -> float:
        return self.IZQ + (t - self.off) * self._pps()

    def t_de(self, x: float) -> float:
        return max(0.0, min(scenes.largo(self.escena()), self.off + (x - self.IZQ) / self._pps()))

    def filas(self) -> list[tuple[str, object, str]]:
        e = self.escena()
        out = [("actor", a, self.page.nombre_medio(a["media_id"])) for a in e["actores"]]
        out += [("sonido", s, "🔊 " + self.page.nombre_medio(s["media_id"])) for s in e["sonidos"]]
        return out

    def bloques(self):
        """[(rect, tipo, actor_o_sonido, fase_o_None)]"""
        scenes.encajar(self.escena())
        out = []
        for i, (tipo, obj, _n) in enumerate(self.filas()):
            y = self.REGLA + i * self.FILA + 3
            if tipo == "actor":
                t = float(obj.get("inicio", 0.0))
                for f in obj["fases"]:
                    d = float(f["dur"])
                    out.append((QRectF(self.x_de(t), y, max(4.0, d * self._pps()), self.FILA - 6), "fase", obj, f))
                    t += d
            else:
                out.append((QRectF(self.x_de(float(obj["t"])), y, max(4.0, float(obj["dur"]) * self._pps()),
                                   self.FILA - 6), "sonido", obj, None))
        return out

    def _claves_vis(self) -> list:
        """[(centro, actor, fase, clave, segundo)] de los rombos ◆ de las animaciones a mano, fila a fila."""
        out = []
        for i, (tipo, obj, _n) in enumerate(self.filas()):
            if tipo != "actor":
                continue
            y = self.REGLA + i * self.FILA + self.FILA / 2
            for t, f, k in scenes.claves(self.escena(), obj):
                out.append((QPointF(self.x_de(t), y), obj, f, k, t))
        return out

    def _rect_mas(self, i: int) -> QRectF:
        y = self.REGLA + i * self.FILA
        return QRectF(self.width() - self.DER + 6, y + 5, self.DER - 12, self.FILA - 10)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(800, self.REGLA + max(3, len(self.filas())) * self.FILA + 8)

    def refrescar(self):
        self._ajustar_off()
        self.setMinimumHeight(self.REGLA + max(3, len(self.filas())) * self.FILA + 8)
        self.update()

    # ---- 🧲 imán: los bordes de todo lo demás y la línea roja
    def _puntos_iman(self, salvo=None) -> list[float]:
        pts = [self.t, 0.0, scenes.largo(self.escena())]
        for a in self.escena()["actores"]:
            t = float(a.get("inicio", 0.0))
            pts.append(t)
            for f in a["fases"]:
                t += float(f["dur"])
                if f is not salvo:
                    pts.append(t)
        for s in self.escena()["sonidos"]:
            if s is not salvo:
                pts += [float(s["t"]), float(s["t"]) + float(s["dur"])]
        return pts

    def _imantar(self, t: float, salvo=None) -> float:
        """El segundo t, pegado al punto más cercano si está a menos de IMAN_PX (Mayús = sin imán)."""
        from PySide6.QtWidgets import QApplication
        self._guia = None
        if not self.iman or QApplication.keyboardModifiers() & Qt.ShiftModifier:
            return t
        mejor = min(self._puntos_iman(salvo), key=lambda p: abs(p - t), default=None)
        if mejor is not None and abs(mejor - t) * self._pps() <= self.IMAN_PX:
            self._guia = self.x_de(mejor)
            return mejor
        return t

    # ---- dibujo
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), COLORS["bg"])            # (los colores de la línea de tiempo de Reclaimer)
        texto, linea = COLORS["text"], COLORS["line"]
        largo = scenes.largo(self.escena())
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(texto)
        pps = self._pps()
        paso = next((x for x in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0) if x * pps >= 60), 60.0)
        k = int(self.off / paso)
        while k * paso <= min(largo, self.off + self._visible()) + 1e-6:
            x = self.x_de(k * paso)
            if x >= self.IZQ - 1:
                p.drawLine(int(x), self.REGLA - 6, int(x), self.REGLA)
                p.drawText(int(x) + 2, self.REGLA - 8, f"{k * paso:g} s")
            k += 1
        for i, (tipo, obj, nombre) in enumerate(self.filas()):
            y = self.REGLA + i * self.FILA
            if self.sel[1] is obj:
                p.fillRect(QRectF(0, y, self.width(), self.FILA), QColor(240, 192, 64, 28))
            p.setPen(QPen(linea))
            p.drawLine(0, int(y + self.FILA), self.width(), int(y + self.FILA))
        p.save()
        p.setClipRect(QRectF(self.IZQ, 0, self._ancho(), self.height()))
        for r, tipo, obj, fase in self.bloques():
            col = QColor(scenes.COLORES[fase["tipo"]]) if fase else QColor("#5cb85c")
            elegido = self.sel[1] is (fase if fase else obj)
            p.setPen(QPen(QColor("#ffffff") if elegido else col.darker(150), 2 if elegido else 1))
            p.setBrush(col)
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#111111"))
            txt = (("◆ A mano" if fase.get("mano") else dict(image_anim.FASES[fase["tipo"]]).get(fase["anim"],
                                                                                                fase["anim"]))
                   if fase else "")
            p.drawText(r.adjusted(5, 0, -3, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(txt, Qt.ElideRight, int(r.width()) - 8))
        clave_sel = getattr(self, "clave_sel", None)      # ◆ claves a mano (arrastrables; clic derecho = curva)
        for c, _a, _f, k, _t in self._claves_vis():
            d = 6.0
            from PySide6.QtGui import QPolygonF
            p.setPen(QPen(QColor("#1a1a1a"), 1))
            p.setBrush(QColor("#ffffff") if k is clave_sel else QColor("#ffd166"))
            p.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - d), QPointF(c.x() + d, c.y()), QPointF(c.x(), c.y() + d),
                                     QPointF(c.x() - d, c.y())]))
        if self._guia is not None:                       # 🧲 dónde se pegó
            p.setPen(QPen(QColor("#ffd166"), 1, Qt.DashLine))
            p.drawLine(int(self._guia), self.REGLA, int(self._guia), self.height())
        x = self.x_de(self.t)
        p.setPen(QPen(QColor("#ff5050"), 2))
        p.drawLine(int(x), 0, int(x), self.height())
        p.restore()
        # los nombres de las filas (encima, a la izquierda) y el «＋» de cada personaje (a la derecha)
        p.fillRect(QRectF(0, self.REGLA, self.IZQ, self.height()), COLORS["bg"])
        p.fillRect(QRectF(self.width() - self.DER, self.REGLA, self.DER, self.height()), COLORS["bg"])
        for i, (tipo, obj, nombre) in enumerate(self.filas()):
            y = self.REGLA + i * self.FILA
            p.setPen(texto)
            p.drawText(QRectF(6, y, self.IZQ - 10, self.FILA), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(nombre, Qt.ElideRight, self.IZQ - 12))
            if tipo == "actor":
                rm = self._rect_mas(i)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#3a6df0"))
                p.drawRoundedRect(rm, 5, 5)
                p.setPen(QColor("#ffffff"))
                p.drawText(rm, Qt.AlignCenter, "＋")
        p.end()

    # ---- ratón y rueda
    def _en(self, pos):
        if pos.x() < self.IZQ or pos.x() > self.width() - self.DER:
            return None
        for r, tipo, obj, fase in reversed(self.bloques()):
            if r.adjusted(-3, 0, 3, 0).contains(pos):
                return r, tipo, obj, fase, pos.x() >= r.right() - 6
        return None

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        if e.modifiers() & Qt.ControlModifier:           # 🔍 Ctrl + rueda: acercar / alejar donde está el ratón
            t_raton = self.t_de(e.position().x())
            self.zoom = max(1.0, min(60.0, self.zoom * (1.25 if d > 0 else 0.8)))
            self.off = t_raton - (e.position().x() - self.IZQ) / self._pps()
        else:                                            # la rueda sola desplaza
            self.off -= (d / 120.0) * self._visible() * 0.15
        self._ajustar_off()
        self.update()
        e.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_S and not e.modifiers() or (e.key() == Qt.Key_B and e.modifiers() & Qt.ControlModifier):
            self.page.cortar()
            return
        if self.teclas_de_vista(e):
            return
        super().keyPressEvent(e)                          # (Espacio, Supr, Ctrl+Z/C/X/V: los recoge la página)

    def acercar(self, factor: float):
        """🔍 Acercar (>1) o alejar (<1) alrededor de la línea roja (como en la línea de tiempo normal)."""
        x = self.x_de(self.t) if self.IZQ <= self.x_de(self.t) <= self.width() - self.DER else \
            self.IZQ + (self.width() - self.DER - self.IZQ) / 2
        t0 = self.t_de(x)
        self.zoom = max(1.0, min(60.0, self.zoom * factor))
        self.off = t0 - (x - self.IZQ) / self._pps()
        self._ajustar_off()
        self.update()

    def teclas_de_vista(self, e) -> bool:
        """+ / − (o Ctrl + / Ctrl −) acercan y alejan · Mayús+Z ve toda la escena · ← → un fotograma (Mayús: 1 s) ·
        Inicio / Fin. Devuelve True si la tecla era suya."""
        k, mods = e.key(), e.modifiers()
        if k in (Qt.Key_Plus, Qt.Key_Equal):
            self.acercar(1.25)
        elif k in (Qt.Key_Minus, Qt.Key_Underscore):
            self.acercar(0.8)
        elif k == Qt.Key_Z and mods & Qt.ShiftModifier and not mods & Qt.ControlModifier:
            self.zoom, self.off = 1.0, 0.0
            self._ajustar_off()
            self.update()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            if self.page._timer.isActive():
                self.page.parar()
            total = scenes.largo(self.page.escena)
            if k == Qt.Key_Home:
                t = 0.0
            elif k == Qt.Key_End:
                t = total
            else:
                paso = 1.0 if mods & Qt.ShiftModifier else 1.0 / 30
                t = self.t + (paso if k == Qt.Key_Right else -paso)
            self.t = max(0.0, min(total, t))
            self.cabezal.emit(self.t)
            self.update()
        else:
            return False
        return True

    def mousePressEvent(self, e):
        pos = e.position()
        for i, (tipo, obj, _n) in enumerate(self.filas()):   # «＋» de la fila de un personaje
            if tipo == "actor" and self._rect_mas(i).contains(pos):
                self.sel = ("actor", obj)
                self.elegido.emit("actor", obj)
                self.update()
                self.mas.emit(obj, e.globalPosition().toPoint())
                return
        if pos.y() >= self.REGLA and self.IZQ <= pos.x() <= self.width() - self.DER:   # ◆ un rombo de clave
            for c, act, fase, k, _t in reversed(self._claves_vis()):
                if abs(pos.x() - c.x()) <= 7 and abs(pos.y() - c.y()) <= 9:
                    self.clave_sel = k
                    self.sel = ("fase", fase)
                    self.elegido.emit("fase", (act, fase))
                    if e.button() == Qt.RightButton:
                        self.update()
                        self.page._menu_clave(act, fase, k, e.globalPosition().toPoint())
                    else:
                        self._arr = ("clave", act, fase, k)
                    self.update()
                    return
        if pos.y() < self.REGLA or (pos.x() < self.IZQ or pos.x() > self.width() - self.DER) and not self._en(pos):
            if self.IZQ <= pos.x() <= self.width() - self.DER:
                self._arr = ("cabezal",)
                self.t = self.t_de(pos.x())
                self.cabezal.emit(self.t)
                self.update()
            elif pos.x() < self.IZQ:                          # (clic en el nombre de la fila: elegirla)
                i = int((pos.y() - self.REGLA) // self.FILA)
                fl = self.filas()
                if 0 <= i < len(fl):
                    self.sel = (fl[i][0], fl[i][1])
                    self.elegido.emit(fl[i][0], fl[i][1])
                    if e.button() == Qt.RightButton:
                        self.menu.emit(fl[i][0], fl[i][1], e.globalPosition().toPoint())
                    self.update()
            return
        hit = self._en(pos)
        if hit is None:
            self.sel = ("", None)
            self.elegido.emit("", None)
            self.update()
            return
        r, tipo, obj, fase, borde = hit
        if tipo == "fase":
            self.sel = ("fase", fase)
            self.elegido.emit("fase", (obj, fase))
        else:
            self.sel = ("sonido", obj)
            self.elegido.emit("sonido", obj)
        if e.button() == Qt.RightButton:
            self.menu.emit(tipo, (obj, fase) if fase else obj, e.globalPosition().toPoint())
        else:
            primera = fase is not None and obj["fases"] and fase is obj["fases"][0]
            inicio_fase = None
            if fase is not None:
                t_ = float(obj.get("inicio", 0.0))
                for f_ in obj["fases"]:
                    if f_ is fase:
                        inicio_fase = t_
                        break
                    t_ += float(f_["dur"])
            self._arr = (tipo, obj, fase, borde, pos.x(),
                         float(fase["dur"]) if (fase and borde) else float(obj.get("dur", 0.0)) if borde else
                         float(obj.get("inicio", 0.0)) if fase is not None else float(obj["t"]), primera, inicio_fase)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._arr is None:
            hit = self._en(pos)
            self.setCursor(Qt.SizeHorCursor if hit and hit[4] else Qt.ArrowCursor)
            return
        if self._arr[0] == "cabezal":
            self.t = self.t_de(pos.x())
            self.cabezal.emit(self.t)
            self.update()
            return
        if self._arr[0] == "clave":                       # ◆ mover la clave en el tiempo (dentro de su fase)
            _x, act, fase, k = self._arr
            scenes.mover_clave(self.escena(), act, fase, k, self._imantar(self.t_de(pos.x())))
            self.update()
            self.page.vista_previa_en(self.t)
            return
        tipo, obj, fase, borde, x0, v0, primera, inicio_fase = self._arr
        dt = (pos.x() - x0) / self._pps()
        if borde:
            if fase is not None:                          # el final de la fase, imantado
                fin = self._imantar(inicio_fase + v0 + dt, salvo=fase)
                scenes.fijar(fase)
                fase["dur"] = round(max(0.1, fin - inicio_fase), 3)
            else:
                fin = self._imantar(float(obj["t"]) + v0 + dt, salvo=obj)
                obj["dur"] = round(max(0.1, fin - float(obj["t"])), 3)
        elif fase is not None and primera:
            obj["inicio"] = round(max(0.0, self._imantar(v0 + dt, salvo=fase)), 3)
        elif fase is None:
            t = self._imantar(v0 + dt, salvo=obj)
            obj["t"] = round(max(0.0, min(scenes.largo(self.escena()) - 0.05, t)), 3)
        self.update()
        self.page.vista_previa_en(self.t)

    def mouseReleaseEvent(self, _e):
        if self._arr is not None and self._arr[0] != "cabezal":
            self.cambiado.emit()
        self._arr = None
        self._guia = None
        self.update()

    # ---- soltar un sonido de «🔊 Sonidos» en su segundo
    def dragEnterEvent(self, e):
        if e.source() is getattr(self.page, "lista_snd", None):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.source() is getattr(self.page, "lista_snd", None):
            self._imantar(self.t_de(e.position().x()))
            self.update()
            e.acceptProposedAction()

    def dropEvent(self, e):
        lista = getattr(self.page, "lista_snd", None)
        if e.source() is not lista or lista.currentItem() is None:
            return
        t = self._imantar(self.t_de(e.position().x()))
        self._guia = None
        self.page._añadir_sonido(lista.currentItem().data(Qt.UserRole), t)
        e.acceptProposedAction()


# ============================================================ la página
class ScenesPage(QWidget):
    closed = Signal(str)

    def __init__(self, win, escena: dict | None = None, aviso: str = ""):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.aviso_estado = aviso                         # (controller.scene_state: "" | "retocada" | "fuera")
        p = self.ctrl.project
        self.escena = scenes.copia(escena) if escena else self._nueva_desde_marcas()
        self.sucia = escena is None
        self._hist, self._pos_hist = [scenes.copia(self.escena)], 0     # (Ctrl+Z desde que se abre)
        self._job = None
        self._pix: dict[str, QPixmap] = {}
        self._items: dict[str, _Actor] = {}
        self.W, self.H = 640, max(120, int(round(640 * p.height / max(1, p.width))))
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self.player = QMediaPlayer(self)                 # (para escuchar sonidos; lo usa también 🌐 Buscar sonido)
        _sal = QAudioOutput(self)
        _sal.setVolume(0.5)                                # 🔊 al escuchar, a la mitad
        self.player.setAudioOutput(_sal)
        self._sonando: list = []

        # ---- barra de arriba
        self.sel_escena = QComboBox()
        self.sel_escena.setToolTip("Las escenas de este proyecto. «＋ Nueva» empieza otra en el tramo marcado.")
        self.nombre = QLineEdit(self.escena.get("nombre", "Escena"))
        self.nombre.setMinimumWidth(110)
        self.nombre.setMaximumWidth(180)
        self.nombre.setToolTip("Nombre de la escena (sale en el deshacer y en la lista).")
        self.nombre.textEdited.connect(lambda t: (self.escena.__setitem__("nombre", t), self._ensuciar()))
        self.desde = QDoubleSpinBox()
        self.dura = QDoubleSpinBox()
        for sp, tip in ((self.desde, "En qué segundo de la línea de tiempo empieza (la animación se mueve entera)."),
                        (self.dura, "Cuánto dura: la animación se estira o se encoge entera, en proporción (entradas, "
                                    "acciones y salidas; los sonidos se recolocan).")):
            sp.setRange(0.0, 99999.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.setToolTip(tip)
        self.dura.setMinimum(0.3)
        for sp in (self.desde, self.dura):
            sp.setKeyboardTracking(False)               # (al escribir «12.5», cambia al terminar, no en cada tecla)
        self.desde.setValue(self.escena["a"])
        self.dura.setValue(scenes.largo(self.escena))
        self.desde.valueChanged.connect(self._empieza)
        self.dura.valueChanged.connect(self._dura)
        b_io = QPushButton("📍 Dónde")
        b_io.setToolTip("Ponerla en el cabezal, en el tramo marcado (I/O) o donde dices una palabra clave; o poner "
                        "otra copia (también una en cada vez que dices la palabra).")
        self.menu_donde = QMenu(b_io)
        self.menu_donde.setToolTipsVisible(True)
        self.menu_donde.aboutToShow.connect(self._llenar_donde)
        b_io.setMenu(self.menu_donde)
        b_lib = QPushButton("📚")
        b_lib.setToolTip("Mis animaciones: guarda esta para usarla en cualquier proyecto, o usa una guardada (eliges "
                         "dónde va y cuánto dura).")
        self.menu_lib = QMenu(b_lib)
        self.menu_lib.setToolTipsVisible(True)
        self.menu_lib.aboutToShow.connect(self._llenar_biblioteca)
        b_lib.setMenu(self.menu_lib)
        self._b_lib = b_lib
        self.fondo = QComboBox()
        for k, n in scenes.FONDOS:
            self.fondo.addItem(n, k)
        self.fondo.setCurrentIndex(max(0, self.fondo.findData(self.escena.get("fondo", scenes.FONDO_POR_DEFECTO))))
        self.fondo.setToolTip("Lo de detrás mientras dura la escena: el video de debajo (desenfocado, normal u "
                              "oscurecido) o una imagen tuya (nítida o borrosa; se elige con clic derecho en una "
                              "imagen → «🖼 Usar de fondo», o en 🌐 Internet → 🖼 Fondo).")
        self.fondo.currentIndexChanged.connect(lambda _i: self._cambio_fondo())
        self.b_play = QPushButton("▶")
        self.b_play.setToolTip("Reproducir la escena (Espacio).")
        self.b_play.clicked.connect(self.alternar)
        self.b_aplicar = QPushButton("✓ Aplicar")
        self.b_aplicar.setToolTip("Pone la escena en la línea de tiempo (un paso de Ctrl+Z). Si ya estaba, la cambia.")
        self.b_aplicar.clicked.connect(self.aplicar)
        # 📤 A qué pestaña va la escena (de entrada, la pestaña en la que estás)
        self.destino = QComboBox()
        for etiqueta, clave in (("🎬 Video horizontal", "youtube"), ("🎵 Edits", "edit"), ("📱 Vertical", "short")):
            self.destino.addItem(etiqueta, clave)
        self.destino.setToolTip("A qué pestaña va la escena al aplicarla: Video horizontal, Edits o Vertical (se lleva "
                                "sus personajes y sonidos y se pone en el mismo tiempo)")
        self.destino.setFocusPolicy(Qt.NoFocus)
        b_png = QPushButton("🎭 PNGTuber")
        b_png.setToolTip("Tu avatar PNG que abre y cierra la boca cuando hablas y parpadea (se exporta así)")
        b_png.clicked.connect(lambda: __import__("editoria.ui.pngtuber_dialog", fromlist=["abrir"]).abrir(self.win))
        b_png.setFocusPolicy(Qt.NoFocus)
        self._b_png = b_png
        b_quitar = QPushButton("🗑")
        b_quitar.setToolTip("Quitar esta escena de la línea de tiempo y del proyecto.")
        b_quitar.clicked.connect(self.quitar)
        b_volver = QPushButton("← Editor")
        b_volver.setToolTip("Volver al editor (lo que no hayas aplicado se pierde: te lo pregunta).")
        b_volver.clicked.connect(self.volver)
        self.marca = QLabel("")
        self.marca.setObjectName("dim")
        arriba = QHBoxLayout()
        for w in (QLabel("🎬"), self.sel_escena, self.nombre, b_lib, QLabel("Empieza"), self.desde, QLabel("Dura"),
                  self.dura, b_io,
                  QLabel("Fondo"), self.fondo, self._b_png):
            arriba.addWidget(w)
        arriba.addStretch(1)
        for w in (self.marca, self.b_play, QLabel("Enviar a"), self.destino, self.b_aplicar, b_quitar, b_volver):
            arriba.addWidget(w)
        for b in (self.b_play, self.b_aplicar, b_quitar, b_volver, b_io, b_lib):
            b.setFocusPolicy(Qt.NoFocus)                 # (Espacio = reproducir, no «pulsar el último botón»)
        self.setFocusPolicy(Qt.StrongFocus)

        # ---- material (izquierda)
        self.material = QTabWidget()
        self.material.addTab(self._tab_personajes(), "🧍 Personajes")
        self.material.addTab(self._tab_sonidos(), "🔊 Sonidos")
        self.material.addTab(self._tab_prehechas(), "⚡ Prehechas")
        self.material.setTabToolTip(2, "Escenas de acción listas para usar: se disparan, pelea, uno contra un grupo, "
                                       "huye y le persiguen, sorpresa, victoria, cara a cara…")
        self.material.setMinimumWidth(260)

        # ---- visor (centro)
        self.vscene = QGraphicsScene(0, 0, self.W, self.H, self)
        self.view = _Visor(self.vscene)
        self.view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.view.setBackgroundBrush(QBrush(COLORS["bg"]))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMinimumSize(self.W // 2, self.H // 2)
        self.view.setToolTip("Arrastra a cada personaje a su sitio; la esquina amarilla cambia el tamaño.")
        self.vscene.addRect(QRectF(0, 0, self.W, self.H), QPen(Qt.NoPen), QBrush(Qt.black))
        self._fondo_item = self.vscene.addPixmap(QPixmap())
        self._velo = self.vscene.addRect(QRectF(0, 0, self.W, self.H), QPen(Qt.NoPen), QBrush(QColor(0, 0, 0, 0)))

        # ---- lo elegido (derecha)
        self.insp = QStackedWidget()
        self.insp.setMinimumWidth(230)
        self._insp_vacio()
        self._insp_actor()
        self._insp_fase()
        self._insp_sonido()

        # ---- línea de tiempo de la escena (abajo)
        self.tl = SceneTimeline(self)
        self.tl.cambiado.connect(self._tl_cambiado)
        self.tl.elegido.connect(self._elegir)
        self.tl.cabezal.connect(self.vista_previa_en)
        self.tl.menu.connect(self._menu)
        self.tl.mas.connect(self._menu_mas)
        self.tl.cabezal.connect(lambda _t: self._textos_añadir())
        self.view.page = self
        self.tl.setFocusPolicy(Qt.ClickFocus)

        centro = QSplitter(Qt.Horizontal)
        centro.addWidget(self.material)
        centro.addWidget(self.view)
        centro.addWidget(self.insp)
        centro.setStretchFactor(1, 1)
        abajo = QWidget()
        av = QVBoxLayout(abajo)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(2)
        av.addLayout(self._barra_reproduccion())
        av.addWidget(self.tl, 1)
        vert = QSplitter(Qt.Vertical)
        vert.addWidget(centro)
        vert.addWidget(abajo)
        vert.setStretchFactor(0, 3)
        vert.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.addLayout(arriba)
        from .comparativa_editor import ComparativaEditor
        self.cuerpo = QStackedWidget()                     # (animación: visor + línea · ⚖ comparativa: su editor)
        self.cuerpo.addWidget(vert)
        self.comp_editor = ComparativaEditor(self)
        self.cuerpo.addWidget(self.comp_editor)
        lay.addWidget(self.cuerpo, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._llenar_escenas()
        self._texto_aplicar()
        self._textos_añadir()
        self.sel_escena.currentIndexChanged.connect(self._cambiar_escena)
        self._avisar_estado()
        self._reconstruir()
        QTimer.singleShot(0, self._tomar_fondo)

    # ================================================================ datos
    def _nueva_desde_marcas(self) -> dict:
        p = self.ctrl.project
        if p.mark_in is not None and p.mark_out is not None and p.mark_out > p.mark_in + 0.3:
            return scenes.nueva(p.mark_in, p.mark_out, self._nombre_libre())
        t = float(getattr(self.win.engine, "time", 0.0) or 0.0)
        return scenes.nueva(t, t + 4.0, self._nombre_libre())

    def _nombre_libre(self) -> str:
        return f"Escena {len(self.ctrl.project.scenes) + 1}"

    def nombre_medio(self, media_id: str) -> str:
        m = self.ctrl.project.media.get(media_id)
        return os.path.splitext(m.name)[0] if m else "(falta)"

    def _pixmap(self, media_id: str) -> QPixmap | None:
        if media_id not in self._pix:
            m = self.ctrl.project.media.get(media_id)
            pix = QPixmap(m.path) if m is not None and os.path.isfile(m.path) else QPixmap()
            if not pix.isNull() and max(pix.width(), pix.height()) > 2 * self.W:
                pix = pix.scaled(2 * self.W, 2 * self.W, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._pix[media_id] = pix
        pix = self._pix[media_id]
        return None if pix.isNull() else pix

    def _media_de_ruta(self, ruta: str, categoria: str) -> str | None:
        """El medio de ese archivo (lo importa si hace falta, leyendo al momento su duración)."""
        return self.ctrl.media_for_path(ruta, categoria)

    def _avisar_estado(self):
        """Si la escena guardada se movió o se retocó en el editor, se dice (al abrirla ya está en su sitio nuevo)."""
        aviso = getattr(self, "aviso_estado", "")
        if aviso == "retocada":
            self.marca.setText("⚠ retocada en el editor")
            self.marca.setToolTip("Cambiaste a mano algún clip de esta escena en la línea de tiempo. Si pulsas "
                                  "«✓ Aplicar», se rehace tal como está aquí (esos retoques se pierden).")
        elif aviso == "fuera":
            self.marca.setText("⚠ no está en la línea de tiempo")
            self.marca.setToolTip("Sus clips se borraron. «✓ Aplicar» la vuelve a poner; «🗑» la quita del proyecto.")

    def _ensuciar(self):
        scenes.encajar(self.escena)
        if getattr(self, "_t_hist", None) is None:
            self._t_hist = QTimer(self)
            self._t_hist.setSingleShot(True)
            self._t_hist.setInterval(300)
            self._t_hist.timeout.connect(self._guardar_hist)
        self._t_hist.start()
        self.sucia = True
        self.marca.setText("● sin aplicar")
        self.marca.setToolTip("Hay cambios que aún no están en la línea de tiempo: pulsa «✓ Aplicar».")
        self._act_tiempo()

    # ================================================================ barra de arriba
    def _llenar_escenas(self):
        self.sel_escena.blockSignals(True)
        self.sel_escena.clear()
        p = self.ctrl.project
        for e in sorted(p.scenes.values(), key=lambda e: e["a"]):
            fuera = "" if self.ctrl.scene_clips(p, e["id"]) else "  · fuera de la línea de tiempo"
            self.sel_escena.addItem(f"{e.get('nombre') or 'Escena'}  ({fmt_time(e['a'], frac=False)}){fuera}", e["id"])
        if self.sel_escena.findData(self.escena["id"]) < 0:
            self.sel_escena.addItem(f"{self.escena.get('nombre') or 'Escena'} (nueva)", self.escena["id"])
        self.sel_escena.addItem("＋ Nueva escena", "__nueva__")
        self.sel_escena.addItem("＋ Nueva comparativa ⚖", "__nueva_comp__")
        self.sel_escena.setCurrentIndex(max(0, self.sel_escena.findData(self.escena["id"])))
        self.sel_escena.blockSignals(False)

    def _cambiar_escena(self, _i):
        clave = self.sel_escena.currentData()
        if clave == self.escena["id"]:
            return
        if self.sucia and self._tiene_contenido() and not self._descartar_ok():
            self._llenar_escenas()
            return
        if clave == "__nueva__":
            self._cargar(self._nueva_desde_marcas(), True)
        elif clave == "__nueva_comp__":
            base = self._nueva_desde_marcas()
            self._cargar(scenes.nueva_comparativa(base["a"], base["b"],
                                                  f"Comparativa {len(self.ctrl.project.scenes) + 1}"), True)
        else:
            esc, aviso = self.ctrl.scene_state(clave)
            self._cargar(esc, False, aviso)

    def _cargar(self, escena: dict, sucia: bool, aviso: str = ""):
        """Cambia la escena que se edita en la página."""
        self.parar()
        self.escena, self.sucia, self.aviso_estado = escena, sucia, aviso
        import copy as _c
        self._hist, self._pos_hist = [_c.deepcopy(escena)], 0     # (Ctrl+Z empieza aquí)
        self.tl.sel = ("", None)
        self.tl.t = 0.0
        self.marca.setText("● sin aplicar" if sucia else "")
        self.marca.setToolTip("")
        if not sucia:
            self._avisar_estado()
        self._recargar_barra()
        self._llenar_escenas()
        self._reconstruir()
        self._tomar_fondo()

    def _recargar_barra(self):
        for w, v in ((self.desde, self.escena["a"]), (self.dura, scenes.largo(self.escena))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.nombre.setText(self.escena.get("nombre", "Escena"))
        self.fondo.blockSignals(True)
        self.fondo.setCurrentIndex(max(0, self.fondo.findData(self.escena.get("fondo", "blur"))))
        self.fondo.blockSignals(False)
        self._act_tiempo()
        if self.escena.get("fondo") in ("img", "img_blur") and \
                (self.escena.get("fondo_img") or "") not in self.ctrl.project.media:
            self.win.statusBar().showMessage("⚠ Falta la imagen de fondo de la escena: elige otra (clic derecho en "
                                             "una imagen → «🖼 Usar de fondo») o cambia «Fondo».", 9000)
        self._texto_aplicar()
        self._textos_añadir()

    def _empieza(self, v: float):
        """Mover la animación entera a otro segundo."""
        if abs(v - float(self.escena["a"])) < 1e-6:
            return
        scenes.mover(self.escena, v)
        self._texto_aplicar()
        self._ensuciar()
        self.tl.refrescar()
        QTimer.singleShot(150, self._tomar_fondo)

    def _dura(self, v: float):
        """Estirarla o encogerla entera."""
        if abs(v - scenes.largo(self.escena)) < 1e-6:
            return
        scenes.estirar(self.escena, v)
        self._texto_aplicar()
        self._ensuciar()
        self.tl.refrescar()
        self._elegir(*((self.tl.sel[0], (self._buscar_actor_de(self.tl.sel[1]), self.tl.sel[1]))
                       if self.tl.sel[0] == "fase" else self.tl.sel))

    def _poner_en(self, a: float, dur: float | None = None):
        """Dónde (y cuánto dura, si se da): lo que hacen «📍 Dónde» y las marcas I/O."""
        if dur is not None:
            self.dura.setValue(dur)
        self.desde.setValue(a)

    def _usar_marcas(self):
        p = self.ctrl.project
        if p.mark_in is None or p.mark_out is None or p.mark_out <= p.mark_in + 0.3:
            self.win.statusBar().showMessage("Marca antes el tramo en la línea de tiempo: I (entrada) y O (salida).",
                                             6000)
            return
        self._poner_en(p.mark_in, p.mark_out - p.mark_in)

    # ================================================================ 📍 dónde · ⧉ copias
    def _cabezal(self) -> float:
        try:
            return float(self.win.engine.time)
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _menciones(self) -> list[dict]:
        try:
            ms, _f = self.win.kw_arranger._mentions()
            return [m for m in ms if m.get("folder")]
        except Exception:  # noqa: BLE001 - sin palabras clave o sin transcripción
            return []

    def _llenar_donde(self):
        m = self.menu_donde
        m.clear()
        t = self._cabezal()
        m.addAction(f"En el cabezal ({fmt_time(t, frac=False)})", lambda: self._poner_en(t))
        p = self.ctrl.project
        io = p.mark_in is not None and p.mark_out is not None and p.mark_out > p.mark_in + 0.3
        a = m.addAction("En el tramo marcado (I/O), estirada a lo que dura", self._usar_marcas)
        a.setEnabled(io)
        a.setToolTip("Empieza en la entrada (I) y se estira o encoge hasta la salida (O).")
        por_palabra: dict[str, list[float]] = {}
        for x in sorted(self._menciones(), key=lambda x: x["t"]):
            por_palabra.setdefault(x["folder"], []).append(float(x["t"]))
        if por_palabra:
            sub = m.addMenu("Donde digo una palabra clave")
            for palabra, ts in sorted(por_palabra.items(), key=lambda kv: kv[0].lower()):
                s2 = sub.addMenu(f"🔑 {palabra} ({len(ts)})" if len(ts) <= 40 else f"🔑 {palabra} (40 de {len(ts)})")
                for tt in ts[:40]:
                    s2.addAction(fmt_time(tt, frac=False), lambda x=tt: self._poner_en(x))
        m.addSeparator()
        a = m.addAction(f"⧉ Otra copia en el cabezal ({fmt_time(t, frac=False)})", lambda: self._copia_en(t))
        a.setToolTip("La misma animación como escena nueva en el cabezal; se abre aquí, sin aplicar todavía.")
        if por_palabra:
            sub = m.addMenu("⧉ Una copia cada vez que digo…")
            sub.setToolTipsVisible(True)
            for palabra, ts in sorted(por_palabra.items(), key=lambda kv: kv[0].lower()):
                a = sub.addAction(f"🔑 {palabra} ({len(ts)} veces)", lambda x=list(ts): self._copias_en(x))
                a.setToolTip("Pone esta animación (tal como está ahora) en cada momento en que dices la palabra, en "
                             "un solo paso de Ctrl+Z.")

    def _copia_en(self, t: float):
        """La misma animación como escena nueva en t (se abre aquí, sin aplicar todavía)."""
        if self.sucia and self._tiene_contenido() and not self._descartar_ok():
            return
        nueva = scenes.otra_copia(self.escena, t)
        base = (self.escena.get("nombre") or "Escena").removesuffix(" (copia)")
        nueva["nombre"] = f"{base} (copia)"
        self._cargar(nueva, True)

    def _copias_en(self, ts: list[float]):
        if not self._tiene_contenido():
            return
        copias, saltadas = [], 0
        p = self.ctrl.project
        largo = scenes.largo(self.escena)
        ocupado = [(float(self.escena["a"]), float(self.escena["b"]))]        # (la original: ahí no va otra)
        ya = [float(e["a"]) for e in p.scenes.values() if e["id"] != self.escena["id"]]
        for t in sorted(ts):
            if any(a - 1e-3 < t < b - 1e-3 or abs(t - a) < 1e-3 for a, b in ocupado) or \
                    any(abs(t - x) < 0.05 for x in ya):
                saltadas += 1                             # (se solaparía, o ya hay una escena ahí)
                continue
            ocupado.append((t, t + largo))
            c = scenes.otra_copia(self.escena, t)
            c["nombre"] = f"{self.escena.get('nombre') or 'Escena'} · {fmt_time(t, frac=False)}"
            copias.append(c)
        if not copias:
            self.win.statusBar().showMessage("No puse ninguna copia: todas caían encima de esta escena o de otra.",
                                             8000)
            return
        res = self.ctrl.apply_scenes(copias)
        if res:
            self._llenar_escenas()
            extra = f" ({saltadas} saltadas: se solapaban o ya había una escena ahí)" if saltadas else ""
            self.win.statusBar().showMessage(f"🎬 {len(copias)} copias puestas en la línea de tiempo{extra}. Ctrl+Z "
                                             "en el editor las quita.", 9000)

    # ================================================================ 📚 mis animaciones
    def _llenar_biblioteca(self):
        m = self.menu_lib
        m.clear()
        a = m.addAction("💾 Guardar esta como animación…", self._guardar_plantilla)
        a.setToolTip("La guarda (sin sitio en la línea de tiempo) para usarla en cualquier proyecto.")
        a.setEnabled(self._tiene_contenido())
        lista = scenes.plantillas()
        if lista:
            m.addSeparator()
        t = self._cabezal()
        for tp in lista:
            sub = m.addMenu(f"🎬 {tp['nombre']}  ({tp['dur']:g} s)")
            a = sub.addAction(f"Usar en el cabezal ({fmt_time(t, frac=False)})",
                              lambda x=tp: self._usar_plantilla(x, t))
            a.setToolTip("Se abre aquí como escena nueva (sin aplicar): ajusta «Dura» y lo demás y pulsa «✓ Aplicar».")
            p = self.ctrl.project
            if p.mark_in is not None and p.mark_out is not None and p.mark_out > p.mark_in + 0.3:
                sub.addAction("Usar en el tramo marcado (I/O)",
                              lambda x=tp: self._usar_plantilla(x, p.mark_in, p.mark_out - p.mark_in))
            sub.addSeparator()
            sub.addAction("🗑 Borrar de mis animaciones", lambda x=tp: self._borrar_plantilla(x))

    def _guardar_plantilla(self):
        from PySide6.QtWidgets import QInputDialog
        nombre = self.escena.get("nombre") or "Animación"
        if not (os.environ.get("EDITORIA_SIN_SONIDO") and os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            nombre, ok = QInputDialog.getText(self, "Guardar animación", "Nombre:", text=nombre)
            if not ok or not nombre.strip():
                return
        nombre = nombre.strip()
        if scenes.existe_plantilla(nombre) and not (os.environ.get("EDITORIA_SIN_SONIDO") and
                                                     os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            if QMessageBox.question(self, "Ya existe", f"Ya tienes una animación llamada «{nombre}». ¿La sustituyo "
                                    "por esta?") != QMessageBox.Yes:
                return
        try:
            scenes.guardar_plantilla(self.escena, self.ctrl.project, nombre)
        except OSError as exc:
            self.win.statusBar().showMessage(f"No se pudo guardar la animación: {exc}", 8000)
            return
        self.win.statusBar().showMessage(f"📚 «{nombre}» guardada en tus animaciones.", 6000)

    def _usar_plantilla(self, tp: dict, a: float, dur: float | None = None):
        if self.sucia and self._tiene_contenido() and not self._descartar_ok():
            return
        esc, faltan = scenes.desde_plantilla(tp, a, self.ctrl.media_for_path, dur)
        self._llenar_imagenes()
        self.reload()
        self._cargar(esc, True)
        if faltan:
            self.marca.setText(f"⚠ faltan {len(faltan)} archivos")
            self.marca.setToolTip("No se encuentran:\n" + "\n".join(faltan[:10]))

    def _borrar_plantilla(self, tp: dict):
        if not (os.environ.get("EDITORIA_SIN_SONIDO") and os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            if QMessageBox.question(self, "Borrar animación", f"¿Borro «{tp.get('nombre')}» de tus animaciones? "
                                    "(no toca lo que ya está en tus proyectos)") != QMessageBox.Yes:
                return
        scenes.borrar_plantilla(tp)

    # ================================================================ visor
    def _tomar_fondo(self):
        """El fotograma donde empieza la escena, SIN los clips de esta escena (si ya estaba aplicada), renderizado
        aparte con el motor de exportación: no mueve el cabezal del editor. Mientras tanto, lo que se ve en el visor."""
        self._pintar_fondo()
        from ..core import still
        from ..core import media as media_tools
        from ..core.model import Project
        from ..core.paths import temp_dir
        p = self.ctrl.project
        if p.duration() <= 0:
            return
        q = Project.from_dict(p.to_dict())
        for c in list(q.clips.values()):
            if scenes.id_de_nota(c.note) == self.escena["id"]:
                q.clips.pop(c.id, None)
        t = min(float(self.escena["a"]) + 0.05, max(0.0, q.duration() - 0.05))
        ruta = str(temp_dir() / f"fondo_escena_{self.escena['id']}.png")
        self._fondo_n = getattr(self, "_fondo_n", 0) + 1
        n = self._fondo_n
        from .jobs import BackgroundJob
        job = BackgroundJob(lambda _pr, _c: still.render_frame(q, t, ruta, media_tools.ffmpeg()), parent=self)
        job.done.connect(lambda r: self._fondo_listo(r, n))
        self._fondo_job = job
        job.start()

    def _fondo_listo(self, ruta, n):
        if n != getattr(self, "_fondo_n", 0) or not ruta or not os.path.isfile(str(ruta)):
            return                                       # (ya se pidió otro: el tramo cambió)
        pix = QPixmap(str(ruta))
        if not pix.isNull():
            self._fondo_pix = pix.scaled(self.W, self.H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._fondo_visor()

    def _pintar_fondo(self):
        try:
            cv = self.win.preview.canvas
            img = QImage(self.W, self.H, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.black)
            pt = QPainter(img)
            cv.scene().render(pt, QRectF(0, 0, self.W, self.H), QRectF(0, 0, cv.W, cv.H))
            pt.end()
            self._fondo_pix = QPixmap.fromImage(img)
        except Exception:  # noqa: BLE001 - sin visor (pruebas)
            self._fondo_pix = None
        self._fondo_visor()

    def _cambio_fondo(self):
        self.escena["fondo"] = self.fondo.currentData()
        if self.fondo.currentData() in ("img", "img_blur") and \
                (self.escena.get("fondo_img") or "") not in self.ctrl.project.media:
            self._ir_a_buscar_fondo()                                   # (aún no hay imagen: a buscar una)
        self._ensuciar()
        self._fondo_visor()

    def _ir_a_buscar_fondo(self):
        """Sin imagen de fondo todavía: abre 🌐 Internet en modo 🖼 Fondo y lo dice."""
        if hasattr(self, "material"):
            self.material.setCurrentIndex(0)                            # (🧍 Personajes, por si estabas en Sonidos)
        if hasattr(self, "sub_img") and hasattr(self, "_grupo_web"):
            self.sub_img.setCurrentIndex(self.sub_img.count() - 1)
            for bm in self._grupo_web.buttons():
                if bm.property("modo") == "fondo" and not bm.isChecked():
                    bm.click()
        self.win.statusBar().showMessage("🖼 Elige la imagen de fondo: búscala aquí (clic derecho → «Usar de fondo») "
                                         "o, en 🗂 Local, clic derecho en una de las tuyas.", 8000)

    def _usar_de_fondo(self, mid: str):
        """🖼 Esa imagen pasa a ser el fondo de la escena (nítida; en «Fondo» puedes elegir «Imagen borrosa»)."""
        if not mid or mid not in self.ctrl.project.media:
            return
        self.escena["fondo_img"] = mid
        if self.escena.get("fondo") not in ("img", "img_blur"):
            self.escena["fondo"] = "img"
        self.fondo.blockSignals(True)
        self.fondo.setCurrentIndex(max(0, self.fondo.findData(self.escena["fondo"])))
        self.fondo.blockSignals(False)
        self._ensuciar()
        self._fondo_visor()

    def _menu_lista_img(self, pos):
        it = self.lista_img.itemAt(pos)
        if it is None:
            return
        self._armar_menu_img(it.data(Qt.UserRole)).exec(self.lista_img.viewport().mapToGlobal(pos))

    def _armar_menu_img(self, mid: str):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("🎬 Añadir a la escena", lambda: self._añadir_actor(mid))
        menu.addAction("🖼 Usar de fondo de la escena", lambda: self._usar_de_fondo(mid))
        m = self.ctrl.project.media.get(mid)
        if m is not None:
            menu.addSeparator()
            self._menu_archivo(menu, m.path)
            menu.addSeparator()
            menu.addAction("🗑 Quitar de Medios", lambda: self._quitar_de_medios(mid))
        return menu

    # ---------------------------------------------------------------- clic derecho: ruta, carpeta, quitar
    def _menu_archivo(self, menu, ruta: str):
        """La ruta del archivo (a la vista, sin pulsar), 📋 copiarla y 📂 abrir su carpeta con el archivo marcado."""
        corta = ruta if len(ruta) <= 64 else "…" + ruta[-62:]
        a = menu.addAction("📄 " + corta)
        a.setEnabled(False)
        a.setToolTip(ruta)
        menu.setToolTipsVisible(True)
        from PySide6.QtWidgets import QApplication
        menu.addAction("📋 Copiar la ruta", lambda: QApplication.clipboard().setText(os.path.normpath(ruta)))
        menu.addAction("📂 Abrir su carpeta", lambda: self._abrir_carpeta(ruta))

    def _abrir_carpeta(self, ruta: str):
        import subprocess
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":       # (pruebas: sin abrir ventanas)
            self._ultima_carpeta = ruta
            return
        if os.path.isfile(ruta):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(ruta)])
        elif os.path.isdir(os.path.dirname(ruta)):
            subprocess.Popen(["explorer", os.path.normpath(os.path.dirname(ruta))])
        else:
            self.win.statusBar().showMessage("No encuentro esa carpeta en el disco.", 5000)

    @staticmethod
    def _usa(e: dict, mid: str) -> bool:
        if any(a.get("media_id") == mid for a in e.get("actores", [])) or e.get("fondo_img") == mid:
            return True
        if any(s.get("media_id") == mid for s in e.get("sonidos", [])):
            return True
        comp = e.get("comp") or {}
        return any((comp.get(k) or {}).get("media_id") == mid for k in ("A", "B"))

    def _escena_que_usa(self, mid: str) -> str | None:
        """El nombre de la escena (la abierta o una guardada del proyecto) que usa ese medio, o None."""
        if self._usa(self.escena, mid):
            return self.escena.get("nombre") or "esta escena"
        for e in (self.ctrl.project.scenes or {}).values():
            if e.get("id") != self.escena.get("id") and self._usa(e, mid):
                return e.get("nombre") or "otra escena"
        return None

    def _quitar_de_medios(self, mid: str) -> bool:
        """🗑 Quita la imagen o el sonido de Medios (el archivo de tu PC no se borra)."""
        m = self.ctrl.project.media.get(mid)
        if m is None:
            return False
        quien = self._escena_que_usa(mid)
        if quien:
            self.win.statusBar().showMessage(f"«{m.name}» se usa en la escena «{quien}»: quítalo antes de ella.", 6000)
            return False
        if self.ctrl.project.is_media_used(mid):
            self.win.statusBar().showMessage(f"«{m.name}» se está usando en la línea de tiempo: quita antes sus clips.",
                                             6000)
            return False
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen" and QMessageBox.question(
                self, "Quitar de Medios", f"¿Quitar «{m.name}» de Medios?\nEl archivo de tu PC NO se borra.") \
                != QMessageBox.Yes:
            return False
        if not self.ctrl.remove_all_media([mid], False):     # (un paso de Ctrl+Z en el editor)
            return False
        self._llenar_imagenes()
        self.reload()
        self.win.statusBar().showMessage(f"🗑 «{m.name}» quitado de Medios (el archivo sigue en tu PC; Ctrl+Z en el "
                                         "editor lo devuelve).", 6000)
        return True

    def _menu_lista_snd(self, pos):
        it = self.lista_snd.itemAt(pos)
        ref = it.data(Qt.UserRole) if it is not None else None
        if ref:
            self._armar_menu_snd(ref).exec(self.lista_snd.viewport().mapToGlobal(pos))

    def _armar_menu_snd(self, ref: str):
        from PySide6.QtWidgets import QMenu
        from ..core.paths import user_dir
        menu = QMenu(self)
        if ref == getattr(self, "_oyendo", None) and self._sonando_escucha():
            menu.addAction("⏸ Pausar", self._pausa_escucha)
            menu.addAction("⏹ Dejar de escuchar", self._parar_escucha)
        else:
            menu.addAction("▶ Escuchar", lambda: self._clic_sonido(ref))
        menu.addAction("➕ Añadir a la escena", lambda: self._añadir_sonido(ref))
        menu.addSeparator()
        ruta = self._ruta_sonido(ref)
        self._menu_archivo(menu, ruta)
        if not ref.startswith("sfx:"):            # (los ✦ de Reclaimer no se quitan)
            n = os.path.normcase(os.path.abspath(ruta))
            mid = next((m.id for m in self.ctrl.project.media.values()
                        if os.path.normcase(os.path.abspath(m.path)) == n), None)
            web = os.path.normcase(os.path.abspath(str(user_dir() / "Sonidos de internet")))
            menu.addSeparator()
            if mid is not None:
                menu.addAction("🗑 Quitar de Medios", lambda: self._quitar_de_medios(mid))
            elif n.startswith(web + os.sep):
                menu.addAction("🗑 Mandar a la papelera", lambda: self._sonido_a_papelera(ruta))
        return menu

    def _sonido_a_papelera(self, ruta: str) -> bool:
        """🗑 Un sonido guardado de 🌐 internet: a la papelera de Windows (se puede recuperar de ahí)."""
        from PySide6.QtCore import QFile
        nombre = os.path.basename(ruta)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen" and QMessageBox.question(
                self, "Mandar a la papelera", f"¿Mandar «{nombre}» a la papelera?\nSe puede recuperar desde la "
                                             "papelera de Windows.") != QMessageBox.Yes:
            return False
        if self._oyendo_ruta() == os.path.normcase(os.path.abspath(ruta)):
            from PySide6.QtCore import QUrl                  # (si se está escuchando, Windows no deja moverlo)
            try:
                self.player.pause()
                self.player.setSource(QUrl())
            except RuntimeError:
                pass
            self._oyendo = None
        if not QFile.moveToTrash(ruta):
            self.win.statusBar().showMessage(f"No se pudo mandar «{nombre}» a la papelera.", 6000)
            return False
        self.reload()
        self.win.statusBar().showMessage(f"🗑 «{nombre}» está en la papelera.", 5000)
        return True

    def _fondo_visor(self):
        pix = getattr(self, "_fondo_pix", None)
        if self.escena.get("fondo") in ("img", "img_blur"):    # 🖼 la imagen elegida de fondo (cubre el cuadro)
            m = self.ctrl.project.media.get(self.escena.get("fondo_img") or "")
            src = QPixmap(m.path) if m is not None and os.path.isfile(m.path) else QPixmap()
            if not src.isNull():
                img = src.scaled(self.W, self.H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                img = img.copy((img.width() - self.W) // 2, (img.height() - self.H) // 2, self.W, self.H)
                if self.escena["fondo"] == "img_blur":
                    peq = img.scaled(self.W // 10, self.H // 10, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    img = peq.scaled(self.W, self.H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self._fondo_item.setPixmap(img)
                self._velo.setBrush(QBrush(QColor(0, 0, 0, 0)))
                return
        if pix is None:
            self._fondo_item.setPixmap(QPixmap())
        elif self.escena.get("fondo") == "blur":       # (una idea de cómo quedará: el desenfoque de verdad, al aplicar)
            peq = pix.scaled(self.W // 10, self.H // 10, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._fondo_item.setPixmap(peq.scaled(self.W, self.H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            self._fondo_item.setPixmap(pix)
        self._velo.setBrush(QBrush(QColor(0, 0, 0, 130 if self.escena.get("fondo") == "dark" else 0)))

    def _tiene_contenido(self) -> bool:
        if scenes.es_comparativa(self.escena):
            c = self.escena["comp"]
            return bool(c["A"].get("media_id") or c["B"].get("media_id"))
        return bool(self.escena["actores"] or self.escena["sonidos"])

    def _modo_cuerpo(self):
        """Animación (visor y línea de la escena) o ⚖ comparativa (su editor): lo que no aplica, oculto."""
        comp = scenes.es_comparativa(self.escena)
        if hasattr(self, "cuerpo"):
            self.cuerpo.setCurrentIndex(1 if comp else 0)
            if comp:
                self.comp_editor.cargar()
        for w in (self.fondo, self.b_play, getattr(self, "_b_lib", None)):
            if w is not None:
                w.setVisible(not comp)

    def _reconstruir(self):
        """Vuelve a crear los personajes del visor y refresca todo (tras abrir otra escena o añadir/quitar)."""
        self._grab = None                                  # (una grabación a medias no sobrevive a rehacer el visor)
        self._modo_cuerpo()
        for it in self._items.values():
            self.vscene.removeItem(it)
        self._items = {}
        for z, act in enumerate(self.escena["actores"]):
            it = _Actor(act["id"], self._pixmap(act["media_id"]), self._actor_movido, self._elegir_actor)
            it.flip = bool(act["caja"].get("flip_h"))
            it.setZValue(10 + z)
            self.vscene.addItem(it)
            self._items[act["id"]] = it
        self._mostrar_visor()
        self.tl.refrescar()
        self._elegir(*self.tl.sel)

    def _mostrar_visor(self):
        """Modo edición (cada uno en su caja) o, con ◆ Auto clave, cómo está todo en la línea roja."""
        if getattr(self, "_auto_clave", False):
            self.vista_previa_en(self.tl.t)
        else:
            self._poner_en_reposo()

    def _actor(self, actor_id: str) -> dict | None:
        return next((a for a in self.escena["actores"] if a["id"] == actor_id), None)

    def _poner_en_reposo(self):
        """Modo edición: cada personaje en su caja (su sitio cuando no se mueve)."""
        for aid, it in self._items.items():
            act = self._actor(aid)
            if act is None:
                continue
            c = act["caja"]
            destello = act.get("efecto") == "destello"   # (⚡ el blanco del destello no tapa el visor al editar)
            it.editable = not destello
            it.flip = bool(c.get("flip_h"))
            it.setFlag(QGraphicsItem.ItemIsMovable, not destello)
            it.setAcceptedMouseButtons(Qt.NoButton if destello else Qt.AllButtons)
            it.prepareGeometryChange()
            it.setRect(QRectF(0, 0, c["w"] * self.W, c["h"] * self.H))
            it.setPos(c["x"] * self.W, c["y"] * self.H)
            it.setOpacity(0.08 if destello else 1.0)
            it.setVisible(True)
            it.update()

    def vista_previa_en(self, t: float):
        """Cómo se ve la escena en el segundo t (al reproducir o al arrastrar el cabezal de la escena)."""
        self.tl.t = t
        st = estado_en(self.escena, t)
        g = getattr(self, "_grab", None)
        quieto = g["actor"]["id"] if g else None          # (el que se graba lo mueve tu ratón)
        for aid, it in self._items.items():
            if aid == quieto:
                continue
            s = st.get(aid)
            it.editable = False
            it.setFlag(QGraphicsItem.ItemIsMovable, False)
            if s is None:
                it.setVisible(False)
                continue
            b = s["box"]
            bw, bh = b["w"] * self.W, b["h"] * self.H
            it.prepareGeometryChange()
            it.setRect(QRectF(0, 0, bw, bh))
            it.setPos(b["x"] * self.W + s["dx"] * bw, b["y"] * self.H + s["dy"] * bh)
            it.setOpacity(s["op"])
            it.flip = bool(b.get("flip_h"))            # (💨 huir le da la vuelta solo en esa fase)
            it.setVisible(True)
            it.update()
        act = self._actor_elegido() if getattr(self, "_auto_clave", False) and not self._timer.isActive() else None
        if act is not None and act["id"] in self._items and act["id"] != quieto:
            it = self._items[act["id"]]                 # ◆ con Auto clave, el elegido se arrastra en la línea roja
            if it.isVisible():
                it.editable = True
                it.setFlag(QGraphicsItem.ItemIsMovable, True)
                it.update()
        self.tl.update()

    def _actor_movido(self, actor_id: str):
        act, it = self._actor(actor_id), self._items.get(actor_id)
        if act is None or it is None:
            return
        r = it.rect().translated(it.pos())
        if getattr(self, "_auto_clave", False):          # ◆ Auto clave: se crea o cambia la clave en la línea roja
            caja = {"x": r.x() / self.W, "y": r.y() / self.H, "w": r.width() / self.W, "h": r.height() / self.H}
            if scenes.poner_clave(self.escena, act, self.tl.t, caja) is not None:
                self._tras_clave()
            return
        act["caja"].update(x=round(r.x() / self.W, 4), y=round(r.y() / self.H, 4), w=round(r.width() / self.W, 4),
                           h=round(r.height() / self.H, 4))
        self._ensuciar()

    def _elegir_actor(self, actor_id: str):
        if self._timer.isActive():
            self.parar()
        auto = getattr(self, "_auto_clave", False)
        if not auto and (not self._items.get(actor_id, None) or not self._items[actor_id].editable):
            self._poner_en_reposo()
        act = self._actor(actor_id)
        if act is not None:
            self.tl.sel = ("actor", act)
            self._elegir("actor", act)
            self.tl.update()
        if auto:
            self.vista_previa_en(self.tl.t)

    # ================================================================ reproducir
    def alternar(self):
        g = getattr(self, "_grab", None)
        if g and not g.get("grabando"):                   # (Espacio con la grabación preparada: se cancela)
            self._terminar_grabacion(cancelar=True)
            return
        if self._timer.isActive():
            self.parar()
        else:
            self.reproducir()

    def _barra_reproduccion(self) -> QHBoxLayout:
        """⏮ ◀ ▶ ▶| ⏭ · el tiempo · 🔊 volumen de la vista previa · 🔍 acercar / alejar / ver toda la escena."""
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QSlider
        fila = QHBoxLayout()
        fila.setContentsMargins(2, 0, 2, 0)

        def boton(texto, tip, fn):
            b = QPushButton(texto)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedWidth(34)
            b.clicked.connect(fn)
            fila.addWidget(b)
            return b
        boton("⏮", "Al principio de la escena (Inicio)", lambda: self._saltar_a(0.0))
        boton("◀", "Un segundo atrás (Mayús + ←; ← un fotograma)", lambda: self._saltar_a(self.tl.t - 1.0))
        self.b_play2 = boton("▶", "Reproducir / pausar la escena (Espacio)", self.alternar)
        boton("▶|", "Un segundo adelante (Mayús + →; → un fotograma)", lambda: self._saltar_a(self.tl.t + 1.0))
        boton("⏭", "Al final de la escena (Fin)", lambda: self._saltar_a(scenes.largo(self.escena)))
        self.lbl_tiempo = QLabel("0:00.00 / 0:00.00")
        self.lbl_tiempo.setToolTip("Dónde está la línea roja / lo que dura la escena")
        fila.addSpacing(8)
        fila.addWidget(self.lbl_tiempo)
        fila.addSpacing(12)
        self.b_auto = QPushButton("◆ Auto clave")
        self.b_auto.setCheckable(True)
        self.b_auto.setFocusPolicy(Qt.NoFocus)
        self.b_auto.setToolTip("Animar a mano (como After Effects o Resolve): elige un personaje, mueve la línea roja y "
                               "arrástralo o agrándalo en el visor; se crea o cambia una clave en ese instante y entre "
                               "claves se mueve solo. Los rombos ◆ salen en su fila: arrástralos en el tiempo; clic "
                               "derecho = curva o borrar.")
        self.b_auto.toggled.connect(self._auto)
        fila.addWidget(self.b_auto)
        boton("◆", "Clave aquí: guarda dónde está el personaje elegido en la línea roja", self._clave_aqui)
        boton("◇", "Quitar la clave del personaje elegido que hay en la línea roja", self._quitar_clave_aqui)
        boton("◀◆", "Ir a la clave anterior del personaje elegido", lambda: self._ir_clave(-1))
        boton("◆▶", "Ir a la clave siguiente del personaje elegido", lambda: self._ir_clave(1))
        fila.addStretch(1)
        fila.addWidget(QLabel("🔊"))
        self.vol_vista = QSlider(Qt.Horizontal)
        self.vol_vista.setRange(0, 100)
        self.vol_vista.setFixedWidth(110)
        self.vol_vista.setValue(int(QSettings("EditorIA", "EditorIA").value("escenas/volumen_vista", 80)))
        self.vol_vista.setToolTip("Volumen al reproducir la escena aquí (no cambia la escena ni lo exportado)")
        self.vol_vista.valueChanged.connect(self._vol_vista)
        fila.addWidget(self.vol_vista)
        fila.addSpacing(8)
        boton("−", "Alejar la línea de la escena (−, o Ctrl + rueda)", lambda: self.tl.acercar(0.8))
        boton("+", "Acercar la línea de la escena (+, o Ctrl + rueda)", lambda: self.tl.acercar(1.25))
        boton("⤢", "Ver toda la escena (Mayús + Z)", lambda: (setattr(self.tl, "zoom", 1.0),
                                                             setattr(self.tl, "off", 0.0), self.tl.update()))
        self.tl.cabezal.connect(self._act_tiempo)
        return fila

    # ---------------------------------------------------------------- ◆ animar a mano
    def _actor_elegido(self) -> dict | None:
        tipo, obj = self.tl.sel
        act = obj if tipo == "actor" else self._buscar_actor_de(obj) if tipo == "fase" and obj is not None else None
        if act is None:
            act = getattr(self, "_act_sel", None)
        return act if act is not None and act in self.escena["actores"] else None

    def _auto(self, on: bool):
        self._auto_clave = bool(on)
        self.parar()
        self._mostrar_visor()
        if on:
            self.win.statusBar().showMessage("◆ Auto clave: elige un personaje, mueve la línea roja y arrástralo en el "
                                             "visor.", 6000)

    def _sin_actor(self) -> bool:
        if self._actor_elegido() is None:
            self.win.statusBar().showMessage("Elige antes un personaje (en el visor o en su fila).", 5000)
            return True
        return False

    def _tras_clave(self):
        self._ensuciar()
        self.tl.refrescar()
        act = self._actor_elegido()
        if act is not None:
            self._elegir("actor", act) if self.tl.sel[0] != "fase" else None
        self._mostrar_visor()

    def _clave_aqui(self):
        if self._sin_actor():
            return
        if scenes.poner_clave(self.escena, self._actor_elegido(), self.tl.t) is None:
            self.win.statusBar().showMessage("En ese momento no se ve: mueve la línea roja a donde esté en pantalla.",
                                             5000)
            return
        self._tras_clave()

    def _quitar_clave_aqui(self):
        if self._sin_actor():
            return
        if scenes.quitar_clave(self.escena, self._actor_elegido(), self.tl.t):
            self.tl.clave_sel = None
            self._tras_clave()
        else:
            self.win.statusBar().showMessage("No hay ninguna clave en la línea roja (◀◆ ◆▶ saltan a ellas).", 5000)

    def _ir_clave(self, sentido: int):
        if self._sin_actor():
            return
        ts = [t for t, _f, _k in scenes.claves(self.escena, self._actor_elegido())]
        t0 = self.tl.t
        cand = [t for t in ts if t > t0 + 0.005] if sentido > 0 else [t for t in ts if t < t0 - 0.005]
        if cand:
            self._saltar_a(min(cand) if sentido > 0 else max(cand))
            if getattr(self, "_auto_clave", False):
                self.vista_previa_en(self.tl.t)

    def _menu_clave(self, act: dict, fase: dict, k: dict, gpos):
        """Clic derecho en un rombo: la curva del tramo que empieza en esa clave, llevar la línea roja o borrarla."""
        m = QMenu(self)
        m.setToolTipsVisible(True)
        cab = m.addAction("Curva hasta la clave siguiente:")
        cab.setEnabled(False)
        actual = k.get("i", "smooth")
        for c, nombre in image_anim.CURVAS_CLAVE:
            a = m.addAction(nombre, lambda cc=c: self._curva(k, cc))
            a.setCheckable(True)
            a.setChecked(actual == c)
        m.addSeparator()
        st, d = scenes.inicio_de(act, fase), float(fase["dur"])
        m.addAction("⏱ Llevar la línea roja aquí", lambda: self._saltar_a(st + float(k.get("t", 0)) * d))
        m.addAction("🗑 Borrar clave", lambda: self._borrar_clave(act, fase, k))
        m.exec(gpos)

    def _curva(self, k: dict, curva: str):
        scenes.curva_clave(k, curva)
        self._ensuciar()
        self.tl.update()
        self.vista_previa_en(self.tl.t)

    def _borrar_clave(self, act: dict, fase: dict, k: dict):
        scenes.borrar_clave(self.escena, act, fase, k)
        self.tl.clave_sel = None
        self._tras_clave()

    def _vol_vista(self, v: int):
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue("escenas/volumen_vista", int(v))
        for pl in self._sonando:                            # (lo que ya suena cambia al momento)
            try:
                out, s = pl.audioOutput(), getattr(pl, "_snd", None)
                if out is not None and s is not None:
                    out.setVolume(min(1.0, float(s.get("vol", 1.0)) * v / 100.0))
            except RuntimeError:
                pass

    def _act_tiempo(self, t: float | None = None):
        if not hasattr(self, "lbl_tiempo"):
            return
        t = float(self.tl.t if t is None else t)
        total = scenes.largo(self.escena)

        def f(x):
            return f"{int(x // 60)}:{x % 60:05.2f}"
        self.lbl_tiempo.setText(f"{f(t)} / {f(total)}")

    def _saltar_a(self, t: float):
        if self._timer.isActive():
            self.parar()
        self.tl.t = max(0.0, min(scenes.largo(self.escena), float(t)))
        self.tl.update()
        self.vista_previa_en(self.tl.t)
        self._act_tiempo()

    def reproducir(self):
        if self.tl.t >= scenes.largo(self.escena) - 0.05:
            self.tl.t = 0.0
        import time as _time
        self._t_prev = self.tl.t - 1e-3
        self._reloj = (_time.monotonic(), self.tl.t)
        self._timer.start()
        self.b_play.setText("⏸")
        if hasattr(self, "b_play2"):
            self.b_play2.setText("⏸")

    def parar(self):
        self._timer.stop()
        self.b_play.setText("▶")
        if hasattr(self, "b_play2"):
            self.b_play2.setText("▶")
        for pl in self._sonando:
            try:
                pl.pause()
            except RuntimeError:
                pass
        self._sonando = []

    def _tick(self):
        import time as _time
        t0, base = getattr(self, "_reloj", (_time.monotonic(), self.tl.t))
        t = base + (_time.monotonic() - t0)              # (reloj real: no se atrasa si un fotograma tarda)
        largo = scenes.largo(self.escena)
        if t >= largo:
            self.vista_previa_en(largo - 1e-3)
            self.parar()
            return
        for s in self.escena["sonidos"]:                   # (los sonidos que empiezan en este fotograma)
            if self._t_prev < float(s["t"]) <= t:
                self._sonar(s)
        self._t_prev = t
        self.vista_previa_en(t)
        self._act_tiempo(t)
        self._muestra_grabacion()

    def _sonar(self, s: dict):
        if os.environ.get("EDITORIA_SIN_SONIDO"):
            return
        m = self.ctrl.project.media.get(s["media_id"])
        if m is None or not os.path.isfile(m.path):
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        pl = QMediaPlayer(self)
        out = QAudioOutput(pl)
        maestro = self.vol_vista.value() / 100.0 if hasattr(self, "vol_vista") else 1.0
        out.setVolume(min(1.0, float(s.get("vol", 1.0)) * maestro))   # (🔊 de la barra: solo para escuchar aquí)
        pl.setAudioOutput(out)
        pl._snd = s
        pl.setSource(QUrl.fromLocalFile(m.path))
        pl.play()
        quedan = scenes.largo(self.escena) - float(s["t"])
        QTimer.singleShot(int(1000 * max(0.05, min(float(s["dur"]), quedan))), pl.pause)   # (como al exportar)
        pl.playbackStateChanged.connect(lambda st, x=pl: x.deleteLater() if st != QMediaPlayer.PlayingState else None)
        vivos = []
        for x in self._sonando:
            try:
                if x.playbackState() != QMediaPlayer.StoppedState:
                    vivos.append(x)
            except RuntimeError:
                pass
        self._sonando = vivos + [pl]

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and getattr(self, "_grab", None):
            self._terminar_grabacion(cancelar=True)
            return
        if e.key() == Qt.Key_Space:
            self.alternar()
            return
        if (e.key() == Qt.Key_B and e.modifiers() & Qt.ControlModifier) or (e.key() == Qt.Key_S and
                                                                               not e.modifiers()):
            self.cortar()                                  # (✂ también con el foco en el visor)
            return
        if self._teclas_de_edicion(e) or self.tl.teclas_de_vista(e):
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            f = self.focusWidget()
            if f is None or f in (self, self.view, self.tl) or isinstance(f, QGraphicsView):
                self._borrar_elegido()
            return
        super().keyPressEvent(e)

    # ================================================================ material: personajes
    def _tab_personajes(self) -> QWidget:
        """Personajes, como el buscador de 🖼 Miniatura: 🗂 Local (Medios y tu PC), ✂ PNG y 🌐 Internet."""
        from PySide6.QtWidgets import QTabWidget
        cont = QWidget()
        cv = QVBoxLayout(cont)
        cv.setContentsMargins(0, 0, 0, 0)
        self.sub_img = QTabWidget()
        self.sub_img.setDocumentMode(True)
        cv.addWidget(self.sub_img)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.sub_img.addTab(w, "🗂 Local")
        self._busq = {}
        web = self._tab_busqueda("web")
        self.sub_img.addTab(web, "🌐 Internet")
        self.sub_img.setTabToolTip(0, "Tus imágenes de Medios y las de tu PC")
        self.sub_img.setTabToolTip(1, "Buscar en internet: ✂ PNG recortado (personajes y objetos sin fondo) o "
                                      "🖼 Fondo (una imagen grande para el fondo de la escena)")
        self.lista_img = QListWidget()
        self.lista_img.setViewMode(QListWidget.IconMode)
        self.lista_img.setIconSize(QPixmap(72, 72).size())
        self.lista_img.setResizeMode(QListWidget.Adjust)
        self.lista_img.setGridSize(QSize(100, 104))
        self.lista_img.setWordWrap(True)
        self.lista_img.setToolTip("Tus imágenes (Medios). ✓ = recorte con fondo transparente. Doble clic = añadirla a "
                                  "la escena. Ctrl + clic elige varias (los papeles de ⚡ Prehechas las usan).")
        self.lista_img.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista_img.itemDoubleClicked.connect(lambda it: self._añadir_actor(it.data(Qt.UserRole)))
        self.lista_img.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista_img.customContextMenuRequested.connect(self._menu_lista_img)
        b = self.b_add_img = QPushButton("➕ Añadir a la escena")
        b.setObjectName("primary")
        b.setToolTip("Añade la imagen elegida como personaje (entra desde abajo y se queda; luego eliges qué hace con "
                     "el «＋» de su fila). También puedes arrastrarla al visor, donde quieras que esté.")
        self.lista_img.setDragEnabled(True)
        self.lista_img.setDragDropMode(QListWidget.DragOnly)
        b.clicked.connect(self._boton_añadir_img)
        b_arch = QPushButton("📁 Desde mi PC…")
        b_arch.setToolTip("Añadir una imagen de tu PC (PNG con fondo transparente, JPG…): va a Medios y a la escena.")
        b_arch.clicked.connect(lambda: self._desde_archivo("imagen"))
        v.addWidget(QLabel("En Medios"))
        v.addWidget(self.lista_img, 1)
        fila_b = QHBoxLayout()
        fila_b.addWidget(b, 1)
        fila_b.addWidget(b_arch)
        v.addLayout(fila_b)
        self._llenar_imagenes()
        if _hay("editoria.ai.character_search"):
            fila = QHBoxLayout()
            self.q_personaje = QLineEdit()
            self.q_personaje.setPlaceholderText("Personaje u objeto…")
            self.q_juego = QLineEdit()
            self.q_juego.setPlaceholderText("Saga o serie (opcional)…")
            self.q_juego.setText(str(self._ajuste("escenas/juego", "")))
            for q in (self.q_personaje, self.q_juego):
                q.returnPressed.connect(self._buscar_personajes)
            self.b_buscar_img = QPushButton("🌐")
            self.b_buscar_img.setToolTip("Buscar imágenes del personaje en la wiki de la saga o serie (Fandom): los «render» "
                                         "en PNG, que suelen venir recortados, salen primero.")
            self.b_buscar_img.clicked.connect(self._buscar_personajes)
            fila.addWidget(self.q_personaje, 2)
            fila.addWidget(self.q_juego, 1)
            fila.addWidget(self.b_buscar_img)
            self.res_img = QListWidget()
            self.res_img.setViewMode(QListWidget.IconMode)
            self.res_img.setIconSize(QPixmap(72, 72).size())
            self.res_img.setResizeMode(QListWidget.Adjust)
            self.res_img.setGridSize(QSize(100, 104))
            self.res_img.setWordWrap(True)
            self.res_img.setToolTip("Resultados de internet. Doble clic = bajarla y añadirla a la escena.")
            self.res_img.itemDoubleClicked.connect(lambda it: self._bajar_personaje(it))
            self.estado_img = QLabel("")
            self.estado_img.setObjectName("dim")
            self.estado_img.setWordWrap(True)
            b2 = QPushButton("⬇ Bajar y añadir")
            b2.setToolTip("La guarda en «Escenas/Personajes» (junto al programa), la añade a Medios y a la escena.")
            b2.clicked.connect(lambda: self._bajar_personaje(self.res_img.currentItem())
                               if self.res_img.currentItem() else None)
            wv = web.layout()                              # (en tu copia: también las wikis del juego, en 🌐)
            wv.addWidget(QLabel("🌐 En su wiki (Fandom)"))
            wv.addLayout(fila)
            wv.addWidget(self.res_img, 2)
            wv.addWidget(self.estado_img)
            wv.addWidget(b2)
        return cont

    # ---------------------------------------------------------------- ✂ PNG / 🌐 Internet (como en 🖼 Miniatura)
    _BUSQ_URL = {"png": "https://www.google.com/search?tbm=isch&tbs=ic:trans,ift:png&q={q}",
                 "fondo": "https://www.google.com/search?tbm=isch&tbs=isz:l,iar:{ar}&q={q}"}
    _MODO_TXT = {"png": ("🔎 persona, perro, coche…", "Clic derecho en una imagen → «Usar en la escena»",
                         "🎬 Usar en la escena"),
                 "fondo": ("🔎 ciudad de noche, bosque, playa…", "Clic derecho en una imagen → «Usar de fondo»",
                           "🖼 Usar de fondo de la escena")}

    def _tab_busqueda(self, modo: str = "web") -> QWidget:
        from PySide6.QtWidgets import QButtonGroup
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 6, 4, 4)
        modos = QHBoxLayout()                              # ✂ PNG recortado / 🖼 Fondo (como en 🖼 Miniatura)
        self._modo_web = "png"
        self._grupo_web = QButtonGroup(w)
        self._grupo_web.setExclusive(True)
        for clave, texto, tip in (("png", "✂ PNG recortado", "Personajes y objetos con fondo transparente (si tienen "
                                                              "un fondo liso, se les quita)"),
                                  ("fondo", "🖼 Fondo", "Imágenes grandes para el fondo de la escena (luego, en "
                                                         "«Fondo», elige si la quieres nítida o borrosa)")):
            bm = QPushButton(texto)
            bm.setCheckable(True)
            bm.setToolTip(tip)
            bm.setProperty("modo", clave)
            bm.setChecked(clave == "png")
            self._grupo_web.addButton(bm)
            modos.addWidget(bm)
        modos.addStretch(1)
        v.addLayout(modos)
        fila = QHBoxLayout()
        q = QLineEdit()
        q.setPlaceholderText(self._MODO_TXT["png"][0])
        q.setClearButtonEnabled(True)
        q.returnPressed.connect(lambda: self._buscar_web(self._modo_web))
        b = QPushButton("Buscar")
        b.setObjectName("primary")
        b.clicked.connect(lambda _c=False: self._buscar_web(self._modo_web))
        fila.addWidget(q, 1)
        fila.addWidget(b)
        v.addLayout(fila)
        estado = QLabel(self._MODO_TXT["png"][1])
        estado.setObjectName("hint")
        estado.setWordWrap(True)
        estado.setToolTip("Se baja la imagen grande (de su página); si tiene un fondo liso (blanco, negro), en ✂ PNG se "
                          "le quita. Va a Medios y a la escena.")
        v.addWidget(estado)
        caja = QVBoxLayout()
        v.addLayout(caja, 1)
        d = {"q": q, "estado": estado, "caja": caja, "vista": None, "job": None}
        for clave in ("png", "fondo", "web"):              # (los dos modos comparten el mismo buscador)
            self._busq[clave] = d

        def cambiar(bm):
            self._modo_web = bm.property("modo")
            q.setPlaceholderText(self._MODO_TXT[self._modo_web][0])
            estado.setText(self._MODO_TXT[self._modo_web][1])
            vista = getattr(self, "_vista_web", None)
            if vista is not None:
                vista.texto_usar = self._MODO_TXT[self._modo_web][2]
                if q.text().strip():
                    self._buscar_web(self._modo_web)
        self._grupo_web.buttonClicked.connect(cambiar)
        return w

    def _buscar_web(self, modo: str):
        import urllib.parse
        from PySide6.QtCore import QUrl
        d = self._busq[modo]
        texto = d["q"].text().strip()
        if not texto:
            return
        vista = getattr(self, "_vista_web", None)
        if vista is None:                                  # (UN navegador, creado la primera vez que buscas)
            from .thumbnail_editor import _PngView
            vista = self._vista_web = _PngView(self)
            vista.texto_usar = self._MODO_TXT.get(modo, self._MODO_TXT["png"])[2]
            vista.use_image.connect(lambda url, fb: self._usar_web(self._modo_web, url, fb))
        self._modo_web = modo
        for dd in self._busq.values():                     # (se pasa a la pestaña desde la que buscas)
            dd["vista"] = None
        d["vista"] = vista
        d["caja"].addWidget(vista, 1)
        if modo == "png" and "png" not in texto.lower():
            texto += " png"
        p = self.ctrl.project
        url = self._BUSQ_URL.get(modo, self._BUSQ_URL["png"])
        d["vista"].load(QUrl(url.format(q=urllib.parse.quote_plus(texto), ar="t" if p.height > p.width else "w")))

    def _usar_web(self, modo: str, url: str, fallback: str = ""):
        """Clic derecho → «Usar en la escena»: se baja (en ✂ PNG, sin su fondo liso), va a Medios y a la escena."""
        from ..ai import thumb_elements as E
        from .jobs import BackgroundJob
        d = self._busq[modo]
        if not url:
            return
        if d["job"] is not None and d["job"].isRunning():
            d["estado"].setText("⏳ Espera a que termine de bajar la anterior…")
            return
        keep = modo == "fondo"

        def work(_p, _c):
            try:
                return E.fetch(url, keep_bg=keep)
            except Exception:  # noqa: BLE001 - la web original no deja bajarla: la pequeña de Google
                if not fallback:
                    raise
                return E.fetch(fallback, keep_bg=keep)

        def listo(e):
            try:
                ids = self.ctrl.import_now([e["path"]], quiet=True)
            except Exception as exc:  # noqa: BLE001
                d["estado"].setText(f"✗ No se pudo añadir: {exc}")
                return
            mid = next((i for i in ids if i in self.ctrl.project.media), None)
            if mid:                                        # (con el nombre de lo que buscaste, no el del archivo)
                base = d["q"].text().strip()[:30] or "Imagen de internet"
                usados = {m.name for m in self.ctrl.project.media.values()}
                n = 1
                while f"{base} {n}" in usados:
                    n += 1
                self.ctrl.project.media[mid].name = f"{base} {n}"
            self._llenar_imagenes()
            if mid and modo == "fondo":                    # 🖼 de fondo de la escena (nítida; «Fondo» → borrosa)
                self._usar_de_fondo(mid)
                d["estado"].setText("✓ Fondo de la escena puesto (en «Fondo» puedes elegir «Imagen borrosa»)")
            elif mid:
                self._añadir_actor(mid)
                d["estado"].setText(f"✓ Añadida a la escena y a Medios · {e.get('badge', '')}")
            else:
                d["estado"].setText("✗ No se pudo usar esa imagen. Prueba con otra.")

        def fallo(msg):
            if d["vista"] is not None and url.startswith("http"):
                d["estado"].setText("⬇ La página no la deja bajar directo; probando con el navegador…")
                d["vista"].download(url, lambda path: self._usar_web(modo, path) if path else
                                    d["estado"].setText("✗ Esa página no deja bajar la imagen. Prueba con otra."))
                return
            d["estado"].setText("✗ No se pudo usar esa imagen. Prueba con otra.")
        d["estado"].setText("⬇ Bajando la imagen…")
        d["job"] = BackgroundJob(work, self)
        d["job"].done.connect(listo)
        d["job"].failed.connect(fallo)
        d["job"].start()

    def _ajuste(self, clave: str, defecto):
        from PySide6.QtCore import QSettings
        return QSettings("EditorIA", "EditorIA").value(clave, defecto)

    def _llenar_imagenes(self):
        self.lista_img.clear()
        p = self.ctrl.project
        from ..core import escenas_prehechas as PH
        imgs = sorted((m for m in p.media.values() if m.kind == KIND_IMAGE and m.id not in self.ctrl.missing
                       and not getattr(m, "gen", None) and not PH.es_propia(m.path)),
                      key=lambda m: (not image_anim.tiene_transparencia(m.path), m.name.lower()))
        for m in imgs:
            alfa = image_anim.tiene_transparencia(m.path)
            it = QListWidgetItem(("✓ " if alfa else "") + os.path.splitext(m.name)[0][:22])
            ico = _miniatura(m.path)
            if ico is not None:
                it.setIcon(ico)
            it.setData(Qt.UserRole, m.id)
            it.setToolTip(m.name + ("\nRecorte con fondo transparente" if alfa else "\nSin transparencia (se verá su "
                                                                                       "fondo rectangular)")
                          + "\n" + m.path + "\nClic derecho: añadir, de fondo, abrir su carpeta o quitar")
            self.lista_img.addItem(it)

    def _boton_añadir_img(self):
        """➕ La imagen elegida; sin ninguna elegida, lo dice; con la lista vacía, a elegir una de tu PC."""
        it = self.lista_img.currentItem()
        if it is not None:
            self._añadir_actor(it.data(Qt.UserRole))
        elif self.lista_img.count():
            self.win.statusBar().showMessage("Elige primero una imagen de la lista (o haz doble clic en ella).", 6000)
            self.lista_img.setFocus()
        else:
            self._desde_archivo("imagen")

    def _boton_añadir_snd(self):
        it = self.lista_snd.currentItem()
        if it is not None:
            self._añadir_sonido(it.data(Qt.UserRole))
        else:
            self.win.statusBar().showMessage("Elige primero un sonido de la lista (o haz doble clic en él).", 6000)
            self.lista_snd.setFocus()

    def _desde_archivo(self, tipo: str):
        """📁 Una imagen (personaje) o un sonido de tu PC: va a Medios y a la escena."""
        from PySide6.QtWidgets import QFileDialog
        if tipo == "imagen":
            rutas, _f = QFileDialog.getOpenFileNames(self, "Añadir imagen a la escena", "",
                                                     "Imágenes (*.png *.webp *.jpg *.jpeg *.gif *.bmp)")
        else:
            rutas, _f = QFileDialog.getOpenFileNames(self, "Añadir sonido a la escena", "",
                                                     "Sonidos (*.mp3 *.wav *.ogg *.m4a *.flac *.aac)")
        if not rutas:
            return
        if tipo == "sonido":
            for r in rutas:
                self._añadir_sonido(r)
            self.reload()
            return
        try:
            ids = self.ctrl.import_now(rutas, quiet=True)
        except Exception as exc:  # noqa: BLE001
            self.win.statusBar().showMessage(f"No se pudo añadir: {exc}", 8000)
            return
        self._llenar_imagenes()
        p = self.ctrl.project
        imgs = [i for i in ids if i in p.media and p.media[i].kind == KIND_IMAGE]
        for i in imgs:
            self._añadir_actor(i)
        if not imgs:
            self.win.statusBar().showMessage("Eso no es una imagen que se pueda usar.", 6000)

    def _añadir_actor(self, media_id: str | None, caja: dict | None = None):
        if not media_id:
            return
        act = scenes.nuevo_actor(self.escena, media_id, caja)
        self._ensuciar()
        self._reconstruir()
        self.tl.sel = ("actor", act)
        self._elegir("actor", act)

    def _lanzar(self, fn, listo, texto: str, estado: QLabel | None = None):
        from .jobs import BackgroundJob
        if self._job is not None:
            if estado is not None:
                estado.setText("Espera a que termine lo de antes…")
            return
        self._job = BackgroundJob(fn, parent=self)
        self._job.title = texto
        if estado is not None:
            estado.setText(texto)
            self._job.progress.connect(lambda _f, t: estado.setText(t))
        self._job.done.connect(lambda r: (setattr(self, "_job", None), listo(r)))
        self._job.failed.connect(lambda m: (setattr(self, "_job", None),
                                            (estado.setText(f"No se pudo: {m[-200:]}") if estado else None)))
        self._job.start()

    def _buscar_personajes(self):
        from ..ai import character_search as CS
        from ..core.paths import temp_dir
        quien, juego = self.q_personaje.text().strip(), self.q_juego.text().strip()
        if not quien:
            return
        from PySide6.QtCore import QSettings
        QSettings("EditorIA", "EditorIA").setValue("escenas/juego", juego)
        cache = str(temp_dir() / "personajes_miniaturas")

        def fn(progress, cancelled):
            res = CS.search(quien, juego, n=24, cancelled=cancelled)
            out = []
            for i, r in enumerate(res):
                if cancelled():
                    break
                progress((i + 1) / max(1, len(res)), f"Miniaturas… {i + 1}/{len(res)}")
                try:
                    out.append((r, CS.miniatura(r, cache)))
                except Exception:  # noqa: BLE001 - una miniatura que no baja: se salta
                    continue
            return out
        self.res_img.clear()
        self._lanzar(fn, self._resultados_personajes, f"Buscando «{quien}»" + (f" en la wiki de {juego}" if juego else "") + "…",
                     self.estado_img)

    def _resultados_personajes(self, res):
        from PySide6.QtGui import QIcon
        self.res_img.clear()
        for r, mini in res or []:
            alfa = image_anim.tiene_transparencia(mini)
            it = QListWidgetItem(("✓ " if alfa else "") + os.path.splitext(r["title"])[0][:22])
            pix = QPixmap(mini)
            if not pix.isNull():
                it.setIcon(QIcon(pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            it.setData(Qt.UserRole, r)
            it.setToolTip(f"{r['title']}\n{r['w']}×{r['h']} · {r['wiki']}.fandom.com" +
                          ("\nRecorte con fondo transparente" if alfa else ""))
            self.res_img.addItem(it)
        n = sum(1 for r, mini in res or [] if image_anim.tiene_transparencia(mini))
        self.estado_img.setText(f"{len(res or [])} imágenes · {n} recortadas (✓)" if res else
                                "No encontré nada: prueba otro nombre o escribe bien el juego.")

    def _bajar_personaje(self, it):
        if it is None:
            return
        from ..ai import character_search as CS
        from ..core.paths import user_dir
        r = it.data(Qt.UserRole)
        carpeta = str(user_dir() / "Escenas" / "Personajes" / r["wiki"])
        self._lanzar(lambda progress, cancelled: CS.download(r, carpeta, progress, cancelled),
                     self._personaje_bajado, f"Bajando «{r['title']}»…", self.estado_img)

    def _personaje_bajado(self, ruta: str):
        mid = self._media_de_ruta(ruta, "Escenas")
        self.estado_img.setText(f"✓ {os.path.basename(ruta)} (en Medios)")
        self._llenar_imagenes()
        self._añadir_actor(mid, getattr(self, "_caja_pendiente", None))
        self._caja_pendiente = None

    # ================================================================ ⚡ prehechas
    def _tab_prehechas(self) -> QWidget:
        from PySide6.QtWidgets import QSpinBox
        from ..core import escenas_prehechas as PH
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.pre_vista = _MiniVista(self)
        self.pre_vista.setToolTip("Así se mueve la prehecha (en bucle): azul = A, rojo = B, verde = el grupo")
        v.addWidget(self.pre_vista)
        self.pre_lista = QListWidget()
        self.pre_lista.setToolTip("Elige una: abajo, qué imagen hace cada papel. Doble clic = crearla.")
        negrita = QFont(self.pre_lista.font())
        negrita.setBold(True)
        for g in PH.GRUPOS:
            cab = QListWidgetItem(g)
            cab.setFlags(Qt.NoItemFlags)
            cab.setFont(negrita)
            self.pre_lista.addItem(cab)
            for t in PH.CATALOGO:
                if t["grupo"] != g:
                    continue
                it = QListWidgetItem("   " + t["nombre"])
                it.setData(Qt.UserRole, t["clave"])
                try:
                    it.setToolTip(PH.resumen(t))
                except Exception:  # noqa: BLE001 - un tooltip no tumba la página
                    it.setToolTip(t["desc"])
                self.pre_lista.addItem(it)
        self.pre_lista.currentItemChanged.connect(lambda it, _p: self._pre_elegir(it.data(Qt.UserRole) if it else None))
        self.pre_lista.itemDoubleClicked.connect(lambda it: self._crear_prehecha() if it.data(Qt.UserRole) else None)
        v.addWidget(self.pre_lista, 1)
        self.pre_papeles = QWidget()
        self.pre_form = QFormLayout(self.pre_papeles)
        self.pre_form.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.pre_papeles)
        self.pre_n = QSpinBox()
        self.pre_n.setRange(1, 12)
        self.pre_n.setPrefix("× ")
        self.pre_n.setToolTip("Cuántos hay en el grupo: el mismo PNG repetido, con pequeñas diferencias de sitio, "
                              "tamaño y momento")
        self.pre_n.valueChanged.connect(lambda _v: self._pre_elegir(self._pre_clave, rehacer_papeles=False))
        self._pre_combos: dict[str, QComboBox] = {}
        self._pre_clave = None
        fila = QHBoxLayout()
        self.b_pre_crear = QPushButton("⚡ Crear escena")
        self.b_pre_crear.setObjectName("primary")
        self.b_pre_crear.setToolTip("Crea la escena en el tramo marcado (I/O), estirada a lo que dura; sin tramo, en el "
                                    "cabezal con su duración. Si la escena de ahora está vacía, se hace en ella (Ctrl+Z "
                                    "la deshace); si no, como escena nueva. Todo queda editable.")
        self.b_pre_crear.clicked.connect(lambda: self._crear_prehecha())
        self.b_pre_añadir = QPushButton("＋ A esta escena")
        self.b_pre_añadir.setToolTip("Mete la prehecha dentro de la escena que estás editando, desde la línea roja "
                                     "(sus personajes y sonidos se suman a los que ya hay). Ctrl+Z la quita.")
        self.b_pre_añadir.clicked.connect(lambda: self._crear_prehecha(añadir=True))
        for b in (self.b_pre_crear, self.b_pre_añadir):
            b.setFocusPolicy(Qt.NoFocus)
            b.setEnabled(False)
        fila.addWidget(self.b_pre_crear, 1)
        fila.addWidget(self.b_pre_añadir)
        v.addLayout(fila)
        return w

    def _pre_imagenes(self) -> list:
        """Las imágenes que pueden hacer un papel (recortes con transparencia primero), sin las propias de prehechas."""
        from ..core import escenas_prehechas as PH
        p = self.ctrl.project
        return sorted((m for m in p.media.values() if m.kind == KIND_IMAGE and m.id not in self.ctrl.missing
                       and not getattr(m, "gen", None) and not PH.es_propia(m.path)),
                      key=lambda m: (not image_anim.tiene_transparencia(m.path), m.name.lower()))

    def _pre_candidatos(self) -> list[str]:
        """Los personajes para los papeles, por orden: los elegidos en 🗂 Local y los que ya están en la escena."""
        from ..core import escenas_prehechas as PH
        p = self.ctrl.project
        out = []
        elegidos = [self.lista_img.item(i) for i in range(self.lista_img.count())
                    if self.lista_img.item(i).isSelected()]
        for it in elegidos:
            out.append(it.data(Qt.UserRole))
        for a in self.escena.get("actores", []):
            m = p.media.get(a["media_id"])
            if m is not None and not a.get("prop") and not a.get("efecto") and not PH.es_propia(m.path):
                out.append(a["media_id"])
        vistos, res = set(), []
        for mid in out:
            if mid and mid in p.media and mid not in vistos:
                vistos.add(mid)
                res.append(mid)
        return res

    def _pre_medios(self) -> dict:
        return {papel: cb.currentData() for papel, cb in self._pre_combos.items()}

    def _pre_elegir(self, clave: str | None, rehacer_papeles: bool = True):
        """Elegir una prehecha: sus papeles (con los personajes que hay a mano) y su vista previa."""
        from ..core import escenas_prehechas as PH
        cambio = clave != self._pre_clave
        self._pre_clave = clave
        for b in (self.b_pre_crear, self.b_pre_añadir):
            b.setEnabled(bool(clave))
        if not clave:
            self.pre_vista.poner(None)
            return
        t = PH.POR_CLAVE[clave]
        grupo = next((x for x in t["papeles"] if x[2]), None)
        if rehacer_papeles or cambio:
            self.pre_n.setParent(None)                 # (que no se borre con las filas: se vuelve a poner)
            while self.pre_form.rowCount():
                self.pre_form.removeRow(0)
            self._pre_combos = {}
            imgs = self._pre_imagenes()
            cand = self._pre_candidatos()
            for i, (papel, nombre, n) in enumerate(t["papeles"]):
                cb = QComboBox()
                cb.addItem("👤 Marcador (falta)", None)
                for m in imgs:
                    cb.addItem(("✓ " if image_anim.tiene_transparencia(m.path) else "") +
                               os.path.splitext(m.name)[0][:28], m.id)
                if i < len(cand):
                    cb.setCurrentIndex(max(0, cb.findData(cand[i])))
                cb.setToolTip(f"Qué imagen hace de «{nombre}»" + (" (se repite en todo el grupo)" if n else "") +
                              ". Sin imagen queda un marcador (una silueta con su letra) que luego cambias con "
                              "«🔁 Cambiar imagen».")
                self._pre_combos[papel] = cb
                if n:
                    fila = QHBoxLayout()
                    fila.addWidget(cb, 1)
                    self.pre_n.blockSignals(True)
                    self.pre_n.setValue(int(n))
                    self.pre_n.blockSignals(False)
                    fila.addWidget(self.pre_n)
                    self.pre_form.addRow(f"{papel} · {nombre}", fila)
                else:
                    self.pre_form.addRow(f"{papel} · {nombre}", cb)
        e, _f = PH.construir(clave, 0.0, {}, None, self.ctrl.project.height > self.ctrl.project.width,
                             n_grupo=self.pre_n.value() if grupo else None)
        self.pre_vista.poner(e)

    def _crear_prehecha(self, clave: str | None = None, añadir: bool = False, medios: dict | None = None,
                        n_grupo: int | None = None) -> dict | None:
        """⚡ Crea la prehecha: en el tramo I/O (estirada) o en el cabezal; en esta escena si está vacía (Ctrl+Z la
        deshace) o como escena nueva; con «añadir», dentro de esta escena desde la línea roja."""
        from ..core import escenas_prehechas as PH
        clave = clave or self._pre_clave
        if not clave or scenes.es_comparativa(self.escena) and añadir:
            return None
        self.parar()
        t = PH.POR_CLAVE[clave]
        medios = self._pre_medios() if medios is None else medios
        if n_grupo is None and any(x[2] for x in t["papeles"]):
            n_grupo = self.pre_n.value()
        p = self.ctrl.project
        vertical = p.height > p.width
        if añadir and self._tiene_contenido():
            esc, faltan = PH.construir(clave, 0.0, medios, self.ctrl.media_for_path, vertical, n_grupo=n_grupo)
            PH.añadir_a(self.escena, esc, float(self.tl.t))
            self._ensuciar()
            self._recargar_barra()
            self._reconstruir()
        else:
            if p.mark_in is not None and p.mark_out is not None and p.mark_out > p.mark_in + 0.3:
                a, dur = float(p.mark_in), float(p.mark_out - p.mark_in)
            else:
                a, dur = self._cabezal(), None
            esc, faltan = PH.construir(clave, a, medios, self.ctrl.media_for_path, vertical, dur, n_grupo)
            if not self._tiene_contenido() and not scenes.es_comparativa(self.escena) and \
                    self.escena["id"] not in p.scenes:   # (la de ahora está vacía: se hace en ella → Ctrl+Z vuelve)
                for k in ("a", "b", "nombre", "fondo", "actores", "sonidos", "prehecha"):
                    self.escena[k] = esc[k]
                self.escena.pop("fondo_img", None)
                self.tl.sel = ("", None)
                self.tl.t = 0.0
                self._ensuciar()
                self._recargar_barra()
                self._llenar_escenas()
                self._reconstruir()
                self._tomar_fondo()
            else:
                if self.sucia and self._tiene_contenido() and not self._descartar_ok():
                    return None
                self._cargar(esc, True)
        self._llenar_imagenes()
        self.reload()
        if faltan:
            self.marca.setText(f"⚠ faltan: {', '.join(faltan)}")
            self.marca.setToolTip("Esos papeles llevan un marcador (una silueta con su letra). Elige al marcador y pulsa "
                                  "«🔁 Cambiar imagen», o elige antes las imágenes en «🗂 Local» (Ctrl + clic para "
                                  "varias) o en la lista de papeles.")
            self.win.statusBar().showMessage(f"⚡ «{t['nombre']}» creada; faltan personajes: {', '.join(faltan)} "
                                             "(llevan un marcador: cámbialo con «🔁 Cambiar imagen»).", 10000)
        else:
            self.win.statusBar().showMessage(f"⚡ «{t['nombre']}» creada: retócala y pulsa «✓ Aplicar».", 7000)
        return self.escena

    # ================================================================ material: sonidos
    def _tab_sonidos(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.lista_snd = QListWidget()
        self.lista_snd.setToolTip("Clic = escuchar · doble clic = ponerlo en el cabezal de la escena.")
        self.lista_snd.itemClicked.connect(lambda it: self._clic_sonido(it.data(Qt.UserRole)))
        self.lista_snd.itemDoubleClicked.connect(lambda it: self._añadir_sonido(it.data(Qt.UserRole)))
        self.lista_snd.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista_snd.customContextMenuRequested.connect(self._menu_lista_snd)
        b = self.b_add_snd = QPushButton("➕ Añadir a la escena")
        b.setObjectName("primary")
        b.setToolTip("Pone el sonido elegido donde está la línea roja de la escena. También puedes arrastrarlo a la "
                     "línea de la escena, al segundo que quieras.")
        self.lista_snd.setDragEnabled(True)
        self.lista_snd.setDragDropMode(QListWidget.DragOnly)
        self.lista_snd.currentItemChanged.connect(lambda *_a: self._textos_añadir())
        b.clicked.connect(self._boton_añadir_snd)
        b_arch_s = QPushButton("📁 Desde mi PC…")
        b_arch_s.setToolTip("Añadir un sonido de tu PC (MP3, WAV, OGG…) en la línea roja de la escena.")
        b_arch_s.clicked.connect(lambda: self._desde_archivo("sonido"))
        v.addWidget(self.lista_snd, 1)
        from PySide6.QtCore import QSettings as _QS
        from PySide6.QtWidgets import QSlider
        fv = QHBoxLayout()
        fv.addWidget(QLabel("🔊"))
        self.vol_snd = QSlider(Qt.Horizontal)
        self.vol_snd.setRange(0, 100)
        self.vol_snd.setValue(int(_QS("EditorIA", "EditorIA").value("escenas/volumen_sonidos", 50)))
        self.vol_snd.setToolTip("Volumen al escucharlos aquí y con el que entran en la escena (luego cada sonido se "
                                "ajusta en su panel)")
        self.lbl_vol_snd = QLabel(f"{self.vol_snd.value()} %")

        def vol_snd(v):
            self.lbl_vol_snd.setText(f"{v} %")
            _QS("EditorIA", "EditorIA").setValue("escenas/volumen_sonidos", int(v))
            try:
                self.player.audioOutput().setVolume(v / 100.0)
            except (AttributeError, RuntimeError):
                pass
        self.vol_snd.valueChanged.connect(vol_snd)
        fv.addWidget(self.vol_snd, 1)
        fv.addWidget(self.lbl_vol_snd)
        self.b_pausa_snd = QPushButton("⏸")
        self.b_pausa_snd.setFixedWidth(34)
        self.b_pausa_snd.setToolTip("Pausar / seguir escuchando (también: clic otra vez en el mismo sonido)")
        self.b_pausa_snd.clicked.connect(self._pausa_escucha)
        self.b_parar_snd = QPushButton("⏹")
        self.b_parar_snd.setFixedWidth(34)
        self.b_parar_snd.setToolTip("Dejar de escuchar")
        self.b_parar_snd.clicked.connect(self._parar_escucha)
        fv.addWidget(self.b_pausa_snd)
        fv.addWidget(self.b_parar_snd)
        try:
            self.player.playbackStateChanged.connect(lambda _s: self._estado_escucha())
        except (AttributeError, RuntimeError):
            pass
        self._estado_escucha()
        v.addLayout(fv)
        try:
            self.player.audioOutput().setVolume(self.vol_snd.value() / 100.0)
        except (AttributeError, RuntimeError):
            pass
        fila_s = QHBoxLayout()
        fila_s.addWidget(b, 1)
        fila_s.addWidget(b_arch_s)
        v.addLayout(fila_s)
        if _hay("editoria.ui.sounds_internet"):
            b2 = QPushButton("🌐 Buscar en internet…")
            b2.setToolTip("Busca un sonido concreto («motor de coche», «disparo de tanque»), lo "
                          "escuchas y lo pones en la escena.")
            b2.clicked.connect(self._buscar_sonidos)
            v.addWidget(b2)
        self.reload()
        return w

    def reload(self):
        """La lista de sonidos: los de Medios, los guardados de internet y los de Reclaimer (lo usa 🌐 Buscar sonido)."""
        from ..core import sfx
        from ..core.paths import user_dir
        self.lista_snd.clear()
        vistos = set()

        def poner(nombre, ruta, grupo):
            n = os.path.normcase(os.path.abspath(ruta))
            if n in vistos:
                return
            vistos.add(n)
            it = QListWidgetItem(f"{grupo}  {nombre}")
            it.setData(Qt.UserRole, ruta)
            it.setToolTip(ruta)
            self.lista_snd.addItem(it)
        for m in sorted(self.ctrl.project.media.values(), key=lambda m: m.name.lower()):
            if m.kind == KIND_AUDIO and m.id not in self.ctrl.missing and m.id not in self.ctrl.project.transcripts:
                poner(os.path.splitext(m.name)[0], m.path, "🗂")
        web = str(user_dir() / "Sonidos de internet")
        if os.path.isdir(web):
            for raiz, _d, fs in os.walk(web):
                for f in sorted(fs):
                    if f.lower().endswith(AUDIO_EXT):
                        poner(os.path.splitext(f)[0].rsplit(" [", 1)[0], os.path.join(raiz, f), "🌐")
        for k, (nombre, _cat, _d) in sfx.CATALOG.items():
            it = QListWidgetItem(f"✦  {nombre}")
            it.setData(Qt.UserRole, "sfx:" + k)
            self.lista_snd.addItem(it)

    # ---------------------------------------------------------------- ▶ ⏸ ⏹ escuchar sonidos de la lista
    def _sonando_escucha(self) -> bool:
        from PySide6.QtMultimedia import QMediaPlayer
        try:
            return self.player.playbackState() == QMediaPlayer.PlayingState
        except RuntimeError:
            return False

    def _clic_sonido(self, ref: str):
        """Clic en un sonido: lo escucha; clic otra vez en el MISMO mientras suena: pausa (y otra vez: sigue)."""
        from PySide6.QtMultimedia import QMediaPlayer
        if ref and ref == getattr(self, "_oyendo", None):
            try:
                st = self.player.playbackState()
            except RuntimeError:
                st = None
            if st == QMediaPlayer.PlayingState:
                self.player.pause()
                return
            if st == QMediaPlayer.PausedState:
                self.player.play()
                return
        self._escuchar(ref)

    def _pausa_escucha(self):
        from PySide6.QtMultimedia import QMediaPlayer
        try:
            st = self.player.playbackState()
            if st == QMediaPlayer.PlayingState:
                self.player.pause()
            elif st == QMediaPlayer.PausedState:
                self.player.play()
            else:
                it = self.lista_snd.currentItem()
                if it is not None and it.data(Qt.UserRole):
                    self._escuchar(it.data(Qt.UserRole))
        except RuntimeError:
            pass

    def _parar_escucha(self):
        try:
            self.player.pause()             # (stop() a veces se bloquea)
            self.player.setPosition(0)
        except RuntimeError:
            pass
        self._estado_escucha()                  # (sigue sabiendo cuál era: clic en él = seguir escuchándolo)

    def _oyendo_ruta(self) -> str:
        ref = getattr(self, "_oyendo", None)
        return os.path.normcase(os.path.abspath(self._ruta_sonido(ref))) if ref else ""

    def _estado_escucha(self):
        if not hasattr(self, "b_pausa_snd"):
            return
        try:
            sonando = self._sonando_escucha()
            self.b_pausa_snd.setText("⏸" if sonando else "▶")
            self.b_pausa_snd.setToolTip("Pausar (también: clic otra vez en el mismo sonido)" if sonando else
                                        "Escuchar / seguir escuchando el sonido elegido")
        except RuntimeError:
            pass

    def _ruta_sonido(self, ref: str) -> str:
        from ..core import sfx
        return sfx.path_for(ref[4:]) if ref.startswith("sfx:") else ref

    def _escuchar(self, ref: str, vol: float | None = None):
        """Escuchar un sonido: al volumen de 🔊 de la lista o, si se da, al suyo (el del sonido de la escena)."""
        if os.environ.get("EDITORIA_SIN_SONIDO") or not ref:
            return
        from PySide6.QtCore import QUrl
        try:
            if vol is None:
                vol = self.vol_snd.value() / 100.0 if hasattr(self, "vol_snd") else 0.5
            self.player.audioOutput().setVolume(min(1.0, max(0.0, vol)))
        except (AttributeError, RuntimeError):
            pass
        try:
            self.player.pause()             # (stop() a veces se bloquea)
            self.player.setSource(QUrl.fromLocalFile(self._ruta_sonido(ref)))
            self.player.play()
            self._oyendo = ref
        except RuntimeError:
            pass

    def _añadir_sonido(self, ref: str | None, t: float | None = None):
        if not ref:
            return
        if t is not None:
            self.tl.t = max(0.0, min(scenes.largo(self.escena), float(t)))
        ruta = self._ruta_sonido(ref)
        mid = self._media_de_ruta(ruta, "Efectos")
        if not mid:
            return
        m = self.ctrl.project.media[mid]
        dur = float(m.duration or 0) or 1.5
        vol = self.vol_snd.value() / 100.0 if hasattr(self, "vol_snd") else 0.5
        s = scenes.nuevo_sonido(self.escena, mid, self.tl.t, min(dur, scenes.largo(self.escena) - self.tl.t + 2.0),
                                vol)
        self._ensuciar()
        self.tl.sel = ("sonido", s)
        self._elegir("sonido", s)
        self.tl.refrescar()

    def add_at_playhead(self, it):
        """Lo que llama 🌐 Buscar sonido al pulsar «➕ Poner»: aquí, en el cabezal de la escena."""
        ref = it.data(0, Qt.UserRole) if it is not None else None
        if ref:
            self._añadir_sonido(ref[5:] if ref.startswith("file:") else ref)

    def _buscar_sonidos(self):
        from . import sounds_internet
        self._sound_dlg = sounds_internet.abrir(self)

    # ================================================================ lo elegido (derecha)
    def _insp_vacio(self):
        w = QLabel("Nada elegido")
        w.setToolTip("Elige un personaje (en el visor o en su fila) o un sonido. Añade personajes desde «🧍 "
                     "Personajes» y sonidos desde «🔊 Sonidos».")
        w.setWordWrap(True)
        w.setObjectName("dim")
        w.setAlignment(Qt.AlignTop)
        self.insp.addWidget(w)

    def _insp_actor(self):
        w = QWidget()
        f = QFormLayout(w)
        self.a_nombre = QLabel("")
        self.a_lado = QComboBox()
        for txt, v in (("Hacia el centro (automático)", 0), ("A la derecha →", 1), ("A la izquierda ←", -1)):
            self.a_lado.addItem(txt, v)
        self.a_lado.setToolTip("Hacia dónde mira: el retroceso del disparo y la caída van hacia su espalda.")
        self.a_lado.currentIndexChanged.connect(lambda _i: self._actor_prop("lado", self.a_lado.currentData()))
        self.a_inicio = QDoubleSpinBox()
        self.a_inicio.setRange(0.0, 9999.0)
        self.a_inicio.setDecimals(2)
        self.a_inicio.setSuffix(" s")
        self.a_inicio.setToolTip("Cuándo aparece, contado desde el principio de la escena.")
        self.a_inicio.valueChanged.connect(lambda v: self._actor_prop("inicio", round(v, 2)))
        self.a_entrada = QComboBox()
        self.a_entrada.addItem("Ninguna (ya está ahí)", "")
        for k, n in image_anim.ENTRADAS:
            self.a_entrada.addItem(n, k)
        self.a_entrada.setToolTip("Cómo llega a su sitio.")
        self.a_entrada.activated.connect(lambda _i: self._fase_extrema("entrada", self.a_entrada.currentData()))
        self.a_salida = QComboBox()
        self.a_salida.addItem("Ninguna (se queda hasta el final)", "")
        for k, n in image_anim.SALIDAS:
            self.a_salida.addItem(n, k)
        self.a_salida.setToolTip("Cómo se va (o cómo muere).")
        self.a_salida.activated.connect(lambda _i: self._fase_extrema("salida", self.a_salida.currentData()))
        from PySide6.QtWidgets import QCheckBox
        self.a_flip = QCheckBox("↔ Voltear la imagen")
        self.a_flip.setToolTip("La imagen en espejo (si el personaje mira al lado contrario del que quieres).")
        self.a_flip.toggled.connect(self._voltear)
        b_acc = QPushButton("＋ Añadir en la línea roja…")
        b_acc.setObjectName("primary")
        b_acc.setToolTip("Lo mismo que el «＋» de su fila: acciones de personaje, vehículo o efectos, «🎯 Disparar a…», "
                         "«🎥 Grabar mi movimiento», tus movimientos, entrada y salida.")
        b_acc.clicked.connect(lambda: self._menu_mas(self._act_sel, b_acc.mapToGlobal(b_acc.rect().bottomLeft()))
                              if getattr(self, "_act_sel", None) else None)
        b_quitar = QPushButton("🗑 Quitar personaje")
        b_quitar.setToolTip("Lo quita de la escena (al aplicar, también de la línea de tiempo).")
        b_quitar.clicked.connect(lambda: self._quitar_actor(self._act_sel) if getattr(self, "_act_sel", None)
                                 else None)
        b_img = QPushButton("🔁 Cambiar imagen")
        b_img.setToolTip("Otra imagen para este personaje (lo que hace no cambia). En un grupo de una prehecha, se cambia "
                         "en todo el grupo. Sirve para poner el personaje que falta en un marcador.")
        self.menu_img = QMenu(b_img)
        self.menu_img.aboutToShow.connect(self._llenar_menu_img)
        b_img.setMenu(self.menu_img)
        b_img.setFocusPolicy(Qt.NoFocus)
        f.addRow(self.a_nombre)
        f.addRow("Mira", self.a_lado)
        f.addRow("Aparece en", self.a_inicio)
        f.addRow("Entrada", self.a_entrada)
        f.addRow("Salida", self.a_salida)
        f.addRow(self.a_flip)
        f.addRow(b_acc)
        f.addRow(b_img)
        f.addRow(b_quitar)
        self.insp.addWidget(w)

    def _llenar_menu_img(self):
        m = self.menu_img
        m.clear()
        act = getattr(self, "_act_sel", None)
        if act is None or act not in self.escena["actores"]:
            return
        elegida = self.lista_img.currentItem()
        if elegida is not None and elegida.data(Qt.UserRole) != act["media_id"]:
            m.addAction(f"La elegida en 🗂 Local: {elegida.text()}",
                        lambda mid=elegida.data(Qt.UserRole): self._cambiar_imagen(act, mid))
            m.addSeparator()
        imgs = self._pre_imagenes()
        for im in imgs[:60]:
            a = m.addAction(("✓ " if image_anim.tiene_transparencia(im.path) else "") + os.path.splitext(im.name)[0][:40],
                            lambda mid=im.id: self._cambiar_imagen(act, mid))
            a.setEnabled(im.id != act["media_id"])
        if not imgs:
            m.addAction("(no hay imágenes en Medios: añádelas en «🧍 Personajes»)").setEnabled(False)

    def _cambiar_imagen(self, act: dict, media_id: str):
        """🔁 Otra imagen para el personaje (y para todo su grupo si es de una prehecha)."""
        if act not in self.escena["actores"] or media_id not in self.ctrl.project.media:
            return
        viejo = act["media_id"]
        cambiar = [act]
        if act.get("grupo"):
            cambiar += [a for a in self.escena["actores"] if a is not act and a.get("grupo") == act["grupo"]
                        and a["media_id"] == viejo]
        for a in cambiar:
            a["media_id"] = media_id
        self._ensuciar()
        self._reconstruir()
        from ..core import escenas_prehechas as PH
        quedan = sorted({a.get("papel") or "?" for a in self.escena["actores"]
                         if a["media_id"] in self.ctrl.project.media
                         and PH.es_propia(self.ctrl.project.media[a["media_id"]].path)
                         and not a.get("prop") and not a.get("efecto")})
        if self.marca.text().startswith("⚠ faltan"):
            self.marca.setText(f"⚠ faltan: {', '.join(quedan)}" if quedan else "● sin aplicar")
        self.win.statusBar().showMessage(f"🔁 Imagen cambiada en {len(cambiar)} personaje(s).", 5000)

    def _insp_fase(self):
        w = QWidget()
        f = QFormLayout(w)
        self.f_titulo = QLabel("")
        self.f_anim = QComboBox()
        self.f_anim.activated.connect(lambda _i: self._fase_prop("anim", self.f_anim.currentData()))
        self.f_dur = QDoubleSpinBox()
        self.f_dur.setRange(0.1, 600.0)
        self.f_dur.setDecimals(2)
        self.f_dur.setSingleStep(0.1)
        self.f_dur.setSuffix(" s")
        self.f_dur.setToolTip("Cuánto dura esta fase (también: arrastra el borde derecho del bloque).")
        self.f_dur.valueChanged.connect(lambda v: self._fase_prop("dur", round(v, 2)))
        b_q = QPushButton("🗑 Quitar fase")
        b_q.setToolTip("Quita esta fase del personaje (también con Supr).")
        b_q.clicked.connect(self._borrar_elegido)
        self.f_anim.setToolTip("Qué hace el personaje en esta fase.")
        self.b_guardar_mov = QPushButton("💾 Guardar en mis movimientos")
        self.b_guardar_mov.setToolTip("Guarda este movimiento grabado para usarlo con cualquier personaje o vehículo "
                                      "(«＋» de su fila → «📚 Mis movimientos»).")
        self.b_guardar_mov.clicked.connect(self._guardar_movimiento)
        b_act = QPushButton("← Personaje")
        b_act.setToolTip("Ver las opciones de este personaje.")
        b_act.clicked.connect(lambda: self._elegir("actor", self._fase_sel[0]) if getattr(self, "_fase_sel", None)
                              else None)
        f.addRow(self.f_titulo)
        f.addRow("Qué hace", self.f_anim)
        f.addRow("Duración", self.f_dur)
        f.addRow(self.b_guardar_mov)
        f.addRow(b_q)
        f.addRow(b_act)
        self.insp.addWidget(w)

    def _insp_sonido(self):
        w = QWidget()
        f = QFormLayout(w)
        self.s_nombre = QLabel("")
        self.s_nombre.setWordWrap(True)
        self.s_t = QDoubleSpinBox()
        self.s_t.setRange(0.0, 9999.0)
        self.s_t.setDecimals(2)
        self.s_t.setSuffix(" s")
        self.s_t.setToolTip("Cuándo suena, desde el principio de la escena (también: arrastra el bloque verde).")
        self.s_t.valueChanged.connect(lambda v: self._sonido_prop("t", round(v, 2)))
        self.s_dur = QDoubleSpinBox()
        self.s_dur.setRange(0.05, 600.0)
        self.s_dur.setDecimals(2)
        self.s_dur.setSuffix(" s")
        self.s_dur.setToolTip("Cuánto suena (como mucho, lo que dura el archivo).")
        self.s_dur.valueChanged.connect(lambda v: self._sonido_prop("dur", round(v, 2)))
        self.s_vol = QSlider(Qt.Horizontal)
        self.s_vol.setRange(0, 150)
        self.s_vol.setToolTip("Volumen (100 % = como está el archivo).")
        self.s_vol.valueChanged.connect(lambda v: self._sonido_prop("vol", round(v / 100.0, 2)))
        b_oir = QPushButton("▶ Escuchar")
        b_oir.clicked.connect(lambda: self._escuchar(self.ctrl.project.media[self._snd_sel["media_id"]].path,
                                                     float(self._snd_sel.get("vol", 1.0)))
                              if getattr(self, "_snd_sel", None) and self._snd_sel["media_id"] in
                              self.ctrl.project.media else None)
        b_oir.setToolTip("Escuchar este sonido.")
        b_q = QPushButton("🗑 Quitar sonido")
        b_q.setToolTip("Quita el sonido de la escena (también con Supr).")
        b_q.clicked.connect(self._borrar_elegido)
        f.addRow(self.s_nombre)
        f.addRow("Empieza", self.s_t)
        f.addRow("Dura", self.s_dur)
        f.addRow("Volumen", self.s_vol)
        f.addRow(b_oir)
        f.addRow(b_q)
        self.insp.addWidget(w)

    def _elegir(self, tipo: str, obj):
        """Muestra a la derecha las opciones de lo elegido. Una fase llega como (actor, fase) o solo la fase (la
        selección de la línea de la escena guarda solo la fase): se acepta de las dos formas."""
        if tipo == "fase" and isinstance(obj, dict):
            act = self._buscar_actor_de(obj)
            tipo, obj = ("fase", (act, obj)) if act is not None else ("", None)
        if tipo in ("actor", "sonido") and obj is not None and obj not in (self.escena["actores"] +
                                                                           self.escena["sonidos"]):
            tipo, obj = "", None                          # (ya no está en la escena: nada elegido)
        self._cargando = True
        try:
            for it in self._items.values():
                it.elegido = False
            if tipo == "actor" and obj is not None:
                self._act_sel = obj
                self.a_nombre.setText(f"<b>{self.nombre_medio(obj['media_id'])}</b>")
                self.a_lado.setCurrentIndex(max(0, self.a_lado.findData(int(obj.get("lado", 0)))))
                self.a_inicio.setValue(float(obj.get("inicio", 0.0)))
                ent = next((f["anim"] for f in obj["fases"] if f["tipo"] == "entrada"), "")
                sal = next((f["anim"] for f in obj["fases"] if f["tipo"] == "salida"), "")
                self.a_entrada.setCurrentIndex(max(0, self.a_entrada.findData(ent)))
                self.a_salida.setCurrentIndex(max(0, self.a_salida.findData(sal)))
                self.a_flip.setChecked(bool(obj["caja"].get("flip_h")))
                if obj["id"] in self._items:
                    self._items[obj["id"]].elegido = True
                self.insp.setCurrentIndex(1)
            elif tipo == "fase" and obj is not None:
                act, fase = obj
                self._fase_sel = (act, fase)
                self.f_titulo.setText(f"<b>{scenes.NOMBRE_TIPO[fase['tipo']]}</b> · {self.nombre_medio(act['media_id'])}")
                self.f_anim.clear()
                for k, n in image_anim.FASES[fase["tipo"]]:
                    self.f_anim.addItem(n, k)
                self.f_anim.setCurrentIndex(max(0, self.f_anim.findData(fase["anim"])))
                self.f_dur.setValue(float(fase["dur"]))
                self.b_guardar_mov.setVisible(fase.get("anim") == "propia")
                if act["id"] in self._items:
                    self._items[act["id"]].elegido = True
                self.insp.setCurrentIndex(2)
            elif tipo == "sonido" and obj is not None:
                self._snd_sel = obj
                self.s_nombre.setText(f"<b>🔊 {self.nombre_medio(obj['media_id'])}</b>")
                self.s_t.setValue(float(obj["t"]))
                m = self.ctrl.project.media.get(obj["media_id"])
                self.s_dur.setMaximum(float(m.duration) if m is not None and m.duration else 600.0)
                self.s_dur.setValue(float(obj["dur"]))
                self.s_vol.setValue(int(round(float(obj.get("vol", 1.0)) * 100)))
                self.insp.setCurrentIndex(3)
            else:
                self.insp.setCurrentIndex(0)
            for it in self._items.values():
                it.update()
        finally:
            self._cargando = False

    # ---- cambios desde la derecha
    def _actor_prop(self, k, v):
        if getattr(self, "_cargando", False) or not getattr(self, "_act_sel", None):
            return
        self._act_sel[k] = v
        self._ensuciar()
        self.tl.update()

    def _fase_extrema(self, tipo: str, anim: str):
        act = getattr(self, "_act_sel", None)
        if act is None:
            return
        f = next((f for f in act["fases"] if f["tipo"] == tipo), None)
        if not anim:
            if f is not None:
                scenes.quitar_fase(act, f)
        else:
            scenes.poner_fase(act, tipo, anim)
        self._ensuciar()
        self.tl.refrescar()

    def _añadir_accion(self, anim: str):
        act = getattr(self, "_act_sel", None)
        if act is None:
            return
        f = scenes.poner_fase(act, "accion", anim, 1.0)
        self._ensuciar()
        self.tl.sel = ("fase", f)
        self._elegir("fase", (act, f))
        self.tl.refrescar()

    def _fase_prop(self, k, v):
        if getattr(self, "_cargando", False) or not getattr(self, "_fase_sel", None):
            return
        if k == "dur":
            scenes.fijar(self._fase_sel[1])
        self._fase_sel[1][k] = v
        self._ensuciar()
        self.tl.update()

    def _sonido_prop(self, k, v):
        if getattr(self, "_cargando", False) or not getattr(self, "_snd_sel", None):
            return
        self._snd_sel[k] = v
        self._ensuciar()
        self.tl.update()

    def _tl_cambiado(self):
        self._ensuciar()
        self._elegir(*((self.tl.sel[0], (self._buscar_actor_de(self.tl.sel[1]), self.tl.sel[1]))
                       if self.tl.sel[0] == "fase" else self.tl.sel))

    def _buscar_actor_de(self, fase):
        return next((a for a in self.escena["actores"] if any(f is fase for f in a["fases"])), None)

    def _menu(self, tipo: str, obj, gpos):
        m = QMenu(self)
        if tipo == "fase":
            act, fase = obj
            m.addAction("✂ Cortar en la línea roja\tCtrl+B", self.cortar)
            m.addAction("＋ Añadir en la línea roja…", lambda a=act: self._menu_mas(a, gpos))
            m.addAction("🗑 Quitar esta fase\tSupr", self._borrar_elegido)
            m.addAction("🗑 Quitar personaje", lambda a=act: self._quitar_actor(a))
        elif tipo == "actor":
            m.addAction("＋ Añadir en la línea roja…", lambda a=obj: self._menu_mas(a, gpos))
            m.addAction("🗑 Quitar personaje", lambda a=obj: self._quitar_actor(a))
        elif tipo == "sonido":
            m.addAction("🗑 Quitar sonido", self._borrar_elegido)
        m.exec(gpos)

    # ---------------------------------------------------------------- «＋» de cada fila
    DUR_ACCION = {"disparo": 1.2, "golpe": 0.5, "salta": 1.0, "camina": 1.5, "corre": 1.2, "agacha": 1.0,
                  "tiembla": 1.0, "acerca": 1.5, "conduce": 2.0, "frena": 1.2, "flota": 2.0, "explota": 0.8,
                  "pop": 0.5, "destello": 0.4, "ninguna": 1.0, "ataca": 0.5, "esquiva": 0.6, "derribado": 1.0,
                  "retrocede": 1.0, "cruza_corre": 2.0, "cruza": 2.0, "huye": 1.2, "habla": 1.5, "susto": 0.5,
                  "celebra": 1.7, "abatido": 1.4, "sacudida": 0.35}

    def _menu_mas(self, actor: dict, gpos):
        """«＋»: qué añadir a ese personaje JUSTO en la línea roja de la escena."""
        if actor is None or actor not in self.escena["actores"]:
            return
        m = QMenu(self)
        m.setToolTipsVisible(True)
        t = self.tl.t
        cab = m.addAction(f"Añadir a «{self.nombre_medio(actor['media_id'])}» en {t:.2f} s (la línea roja):")
        cab.setEnabled(False)
        for cat, lista in image_anim.ACCIONES_CAT:
            sub = m.addMenu(cat)
            for k, n in lista:
                sub.addAction(n, lambda kk=k, a=actor: self._accion_en(a, kk))
        otros = [o for o in self.escena["actores"] if o is not actor]
        if otros:
            sub = m.addMenu("🎯 Disparar a…")
            sub.setToolTipsVisible(True)
            for o in otros:
                s2 = sub.addMenu(self.nombre_medio(o["media_id"]))
                a = s2.addAction("…y muere", lambda a=actor, oo=o: self._disparar(a, oo, True))
                a.setToolTip("Dispara desde la línea roja; al otro le llega el disparo, recibe el golpe y cae.")
                s2.addAction("…solo herido", lambda a=actor, oo=o: self._disparar(a, oo, False))
        a = m.addAction("📳 Temblor de cámara aquí (a todos)", self._temblor_aqui)
        a.setToolTip("Todos los que estén quietos en la línea roja se sacuden a la vez (una fase «📳 Sacudida»).")
        a = m.addAction("⚡ Destello de pantalla aquí", self._destello_aqui)
        a.setToolTip("Un fogonazo blanco a pantalla completa que se desvanece (va encima de todo).")
        m.addSeparator()
        a = m.addAction("🎥 Grabar mi movimiento desde aquí…", lambda a=actor: self._armar_grabacion(a))
        a.setToolTip("Mantén pulsado al personaje en el visor y muévelo con el ratón: se graba mientras lo mueves "
                     "(la escena se reproduce a la vez). Suelta para terminar.")
        movs = scenes.movimientos()
        if movs:
            sub = m.addMenu("📚 Mis movimientos")
            for mv in movs:
                sub.addAction(f"{mv['nombre']} ({mv['dur']:g} s)",
                              lambda a=actor, x=mv: self._insertar(a, scenes.fase_de_movimiento(x)))
        m.addSeparator()
        ent = m.addMenu("Entrada")
        ent.addAction("Ninguna (ya está ahí)", lambda a=actor: self._extrema_de(a, "entrada", ""))
        for k, n in image_anim.ENTRADAS:
            ent.addAction(n, lambda a=actor, kk=k: self._extrema_de(a, "entrada", kk))
        sal = m.addMenu("Salida")
        sal.addAction("Ninguna (se queda)", lambda a=actor: self._extrema_de(a, "salida", ""))
        for k, n in image_anim.SALIDAS:
            sal.addAction(n, lambda a=actor, kk=k: self._extrema_de(a, "salida", kk))
        m.addSeparator()
        m.addAction("🗑 Quitar personaje", lambda a=actor: self._quitar_actor(a))
        m.exec(gpos)

    def _temblor_aqui(self):
        if scenes.temblor_camara(self.escena, self.tl.t, 0.35):
            self._ensuciar()
            self.tl.refrescar()
            self.vista_previa_en(self.tl.t)
        else:
            self.win.statusBar().showMessage("Nadie está quieto en ese momento (el temblor solo se pone a los que están "
                                             "quietos, temblando o hablando).", 6000)

    def _destello_aqui(self):
        from ..core import escenas_prehechas as PH
        mid = self.ctrl.media_for_path(PH.ruta_imagen("blanco"), "Escenas")
        if not mid:
            return
        scenes.nuevo_destello(self.escena, mid, self.tl.t)
        self._ensuciar()
        self._reconstruir()

    def _insertar(self, actor: dict, fase: dict) -> dict:
        f = scenes.insertar_en(self.escena, actor, self.tl.t, fase)
        self._ensuciar()
        self.tl.sel = ("fase", f)
        self.tl.refrescar()
        self._elegir("fase", (actor, f))
        self.vista_previa_en(self.tl.t)
        return f

    def _accion_en(self, actor: dict, clave: str) -> dict:
        return self._insertar(actor, {"tipo": "accion", "anim": clave, "dur": self.DUR_ACCION.get(clave, 1.0)})

    def _disparar(self, tirador: dict, objetivo: dict, muere: bool):
        f, _r = scenes.disparar_a(self.escena, tirador, objetivo, self.tl.t, muere=muere)
        self._ensuciar()
        self.tl.sel = ("fase", f)
        self.tl.refrescar()
        self._elegir("fase", (tirador, f))
        self.vista_previa_en(self.tl.t)

    def _extrema_de(self, actor: dict, tipo: str, anim: str):
        self._act_sel = actor
        self._fase_extrema(tipo, anim)
        self._elegir("actor", actor)

    def cortar(self):
        """✂ Ctrl+B / S: corta en la línea roja la fase del personaje elegido (o la de todos, si no hay ninguno)."""
        tipo, obj = self.tl.sel
        act = obj if tipo == "actor" else self._buscar_actor_de(obj) if tipo == "fase" else None
        actores = [act] if act is not None else list(self.escena["actores"])
        n = sum(1 for a in actores if scenes.cortar_en(self.escena, a, self.tl.t))
        if n:
            self._ensuciar()
            self.tl.refrescar()
            self._tl_cambiado()
            self.vista_previa_en(self.tl.t)
        else:
            self.win.statusBar().showMessage("Nada que cortar ahí (no se cortan entradas, salidas ni movimientos "
                                             "propios).", 5000)

    def _voltear(self, on: bool):
        act = getattr(self, "_act_sel", None)
        if getattr(self, "_cargando", False) or act is None:
            return
        if on:
            act["caja"]["flip_h"] = True
        else:
            act["caja"].pop("flip_h", None)
        it = self._items.get(act["id"])
        if it is not None:
            it.flip = on
            it.update()
        self._ensuciar()

    # ---------------------------------------------------------------- 🎥 grabar mi movimiento
    def _armar_grabacion(self, actor: dict):
        self.parar()
        self.vista_previa_en(self.tl.t)
        it = self._items.get(actor["id"])
        if it is None or not it.isVisible():
            self.win.statusBar().showMessage("En ese momento el personaje no está en pantalla: mueve la línea roja "
                                             "a donde se vea.", 6000)
            return
        self._grab = {"actor": actor, "grabando": False}
        it.editable = True
        it.setFlag(QGraphicsItem.ItemIsMovable, True)
        it.grabar = self._grab_evento
        it.elegido = True
        it.update()
        self.marca.setText("🎥 Mantén pulsado al personaje y muévelo (suelta para terminar · Esc cancela)")
        self.marca.setToolTip("La escena se reproduce mientras lo mueves: así lo haces a su ritmo.")

    def _grab_evento(self, cual: str, item) -> bool:
        g = getattr(self, "_grab", None)
        if g is None or item.actor_id != g["actor"]["id"]:
            return False
        if cual == "pulsa" and not g["grabando"]:
            g.update(grabando=True, t0=self.tl.t, pos0=item.pos(), muestras=[(self.tl.t, 0.0, 0.0)])
            self.reproducir()
            return True
        if cual == "suelta" and g["grabando"]:
            self._terminar_grabacion()
        return False

    def _muestra_grabacion(self):
        g = getattr(self, "_grab", None)
        if not g or not g.get("grabando"):
            return
        it = self._items.get(g["actor"]["id"])
        if it is None:
            return
        d = it.pos() - g["pos0"]
        g["muestras"].append((self.tl.t, d.x() / self.W, d.y() / self.H))

    def _terminar_grabacion(self, cancelar: bool = False):
        g, self._grab = getattr(self, "_grab", None), None
        self.parar()
        if not g:
            return
        it = self._items.get(g["actor"]["id"])
        if it is not None:
            it.grabar = None
        self.marca.setText("● sin aplicar" if self.sucia else "")
        self.marca.setToolTip("")
        if cancelar or not g.get("grabando") or len(g.get("muestras") or []) < 2:
            self._poner_en_reposo()
            return
        self._muestra_grabacion()
        muestras = g["muestras"]
        if max(max(abs(m[1]), abs(m[2])) for m in muestras) < 0.003:   # (pulsar y soltar sin mover: nada)
            self._poner_en_reposo()
            self.win.statusBar().showMessage("🎥 No lo moviste: no se grabó nada.", 5000)
            return
        dur = max(0.2, muestras[-1][0] - g["t0"])
        fase = {"tipo": "accion", "anim": "propia", "dur": round(dur, 3),
                "kf": image_anim.simplificar_trazo(muestras, dur)}
        self.tl.t = g["t0"]
        self._insertar(g["actor"], fase)
        self.marca.setText(f"🎥 Movimiento grabado ({dur:.1f} s)")
        self.marca.setToolTip("«💾 Guardar en mis movimientos» (a la derecha) para usarlo con otros personajes.")

    def _guardar_movimiento(self):
        fs = getattr(self, "_fase_sel", None)
        if not fs or fs[1].get("anim") != "propia":
            return
        from PySide6.QtWidgets import QInputDialog
        nombre = "Mi movimiento"
        if not (os.environ.get("EDITORIA_SIN_SONIDO") and os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            nombre, ok = QInputDialog.getText(self, "Guardar movimiento", "Nombre:", text=nombre)
            if not ok or not nombre.strip():
                return
        try:
            scenes.guardar_movimiento(fs[1], nombre.strip())
        except OSError as exc:
            self.win.statusBar().showMessage(f"No se pudo guardar: {exc}", 6000)
            return
        self.win.statusBar().showMessage(f"📚 «{nombre.strip()}» guardado en tus movimientos.", 6000)

    # ---------------------------------------------------------------- soltar personajes · textos claros
    def _soltar_personaje(self, lista, fx: float, fy: float):
        """Una imagen soltada en el visor: el personaje aparece con su centro donde la soltaste."""
        it = lista.currentItem()
        if it is None:
            return
        caja = scenes.caja_libre(self.escena)
        caja.update(x=round(fx - caja["w"] / 2, 4), y=round(fy - caja["h"] / 2, 4))
        if lista is self.lista_img:
            self._añadir_actor(it.data(Qt.UserRole), caja)
        else:                                                # (de internet: se baja y luego se pone ahí)
            self._caja_pendiente = caja
            self._bajar_personaje(it)

    def _textos_añadir(self):
        t = self.tl.t
        if hasattr(self, "b_add_snd"):
            self.b_add_snd.setText(f"➕ Añadir a la escena en {t:.2f} s")

    def _texto_aplicar(self):
        a, b = float(self.escena["a"]), float(self.escena["b"])
        self.b_aplicar.setText(f"✓ Aplicar en {fmt_time(a)} → {fmt_time(b)}")
        self.b_aplicar.setToolTip(f"Pone la escena en la línea de tiempo, de {fmt_time(a)} a {fmt_time(b)} (un paso "
                                  "de Ctrl+Z). Si ya estaba, la cambia. Al volver al editor, sus clips se resaltan.")

    def _quitar_actor(self, act: dict):
        if act in self.escena["actores"]:
            self.escena["actores"].remove(act)
            self.tl.sel = ("", None)
            self._ensuciar()
            self._reconstruir()

    # ================================================================ ⌨ teclas como en la línea de tiempo normal
    def _teclas_de_edicion(self, e) -> bool:
        """Ctrl+Z / Ctrl+Y (o Ctrl+Mayús+Z) deshacer y rehacer en la escena · Ctrl+C copiar · Ctrl+X cortar ·
        Ctrl+V pegar en la línea roja · Ctrl+D duplicar. Devuelve True si la tecla era suya."""
        mods, k = e.modifiers(), e.key()
        if not mods & Qt.ControlModifier:
            return False
        from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit
        f = self.focusWidget()
        if isinstance(f, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)) or \
                (f is not None and f.__class__.__name__.startswith("QWebEngine")):
            return False                                   # (escribiendo en un cuadro o en la web: sus teclas)
        if k == Qt.Key_Z and not mods & Qt.ShiftModifier:
            self.deshacer()
        elif k == Qt.Key_Y or (k == Qt.Key_Z and mods & Qt.ShiftModifier):
            self.rehacer()
        elif k == Qt.Key_C:
            self.copiar()
        elif k == Qt.Key_X:
            tipo, obj = self.tl.sel
            if self.copiar():
                if tipo == "fase" and obj.get("tipo") in ("entrada", "salida"):
                    self.win.statusBar().showMessage("La entrada y la salida no se quitan: se copian (Ctrl+V la pone "
                                                     "en otro personaje) y se cambian en su panel.", 6000)
                else:
                    self._borrar_elegido()
        elif k == Qt.Key_V:
            self.pegar()
        elif k == Qt.Key_D:
            antes = getattr(self, "_portapapeles", None)
            if self.copiar():
                self.pegar()
            self._portapapeles = antes
        else:
            return False
        return True

    def _guardar_hist(self):
        """(cada cambio, ya asentado: una foto de la escena para Ctrl+Z)"""
        import copy as _c
        foto = _c.deepcopy(self.escena)
        h = getattr(self, "_hist", None)
        if h is None:
            self._hist, self._pos_hist = [foto], 0
            return
        if h and h[self._pos_hist] == foto:
            return
        self._hist = h[:self._pos_hist + 1] + [foto]
        self._hist = self._hist[-100:]
        self._pos_hist = len(self._hist) - 1

    def _volver_a(self, i: int):
        import copy as _c
        self.escena = _c.deepcopy(self._hist[i])
        self._pos_hist = i
        self.tl.sel = ("", None)
        self._elegir("", None)
        scenes.encajar(self.escena)
        self.sucia = True
        self.marca.setText("● sin aplicar")
        self._recargar_barra()
        self._reconstruir()
        self._fondo_visor()
        self._tomar_fondo()

    def deshacer(self):
        if getattr(self, "_t_hist", None) is not None and self._t_hist.isActive():
            self._t_hist.stop()
            self._guardar_hist()
        if getattr(self, "_hist", None) and self._pos_hist > 0:
            self._volver_a(self._pos_hist - 1)
            self.win.statusBar().showMessage("↶ Deshecho en la escena (Ctrl+Y lo rehace).", 3000)

    def rehacer(self):
        if getattr(self, "_hist", None) and self._pos_hist < len(self._hist) - 1:
            self._volver_a(self._pos_hist + 1)

    def copiar(self) -> bool:
        import copy as _c
        tipo, obj = self.tl.sel
        if tipo not in ("actor", "fase", "sonido") or obj is None:
            self.win.statusBar().showMessage("Elige antes un personaje, una fase o un sonido de la escena.", 4000)
            return False
        actor = self._buscar_actor_de(obj) if tipo == "fase" else None
        self._portapapeles = (tipo, _c.deepcopy(obj), actor["id"] if actor else None)
        return True

    def pegar(self):
        """En la línea roja: un sonido empieza ahí; una fase se mete ahí en su personaje (o en el elegido); un
        personaje sale al lado del original."""
        import copy as _c
        pp = getattr(self, "_portapapeles", None)
        if not pp:
            self.win.statusBar().showMessage("No hay nada copiado (Ctrl+C).", 4000)
            return
        tipo, obj, actor_id = pp
        t = float(self.tl.t)
        if tipo == "sonido":
            nuevo = scenes.nuevo_sonido(self.escena, obj["media_id"], t, obj.get("dur", 1.0), obj.get("vol", 0.5))
            self.tl.sel = ("sonido", nuevo)
        elif tipo == "fase":
            sel_t, sel_o = self.tl.sel
            actor = sel_o if sel_t == "actor" else (self._buscar_actor_de(sel_o) if sel_t == "fase" else None)
            actor = actor or next((a for a in self.escena["actores"] if a["id"] == actor_id), None)
            if actor is None:
                self.win.statusBar().showMessage("Elige el personaje donde pegar la fase.", 4000)
                return
            if obj.get("tipo") in ("entrada", "salida"):     # (la entrada / salida se cambia, no se duplica)
                scenes.poner_fase(actor, obj["tipo"], obj["anim"], obj.get("dur"))
            else:
                f = {k: v for k, v in obj.items() if k != "auto"}
                f["tipo"] = "accion"
                scenes.insertar_en(self.escena, actor, t, f)
        else:
            caja = dict(obj["caja"])
            caja["x"] = min(0.95, float(caja.get("x", 0)) + 0.06)
            nuevo = scenes.nuevo_actor(self.escena, obj["media_id"], caja)
            nid = nuevo["id"]
            nuevo.clear()
            nuevo.update(_c.deepcopy(obj), id=nid, caja=caja)  # (todo igual: fases, lado, retraso de entrada…)
            self._reconstruir()
            self.tl.sel = ("actor", nuevo)
        self._ensuciar()
        self.tl.refrescar()
        self._reconstruir()

    def _borrar_elegido(self):
        tipo, obj = self.tl.sel
        if tipo == "fase":
            act = self._buscar_actor_de(obj)
            if act is not None:
                if len(act["fases"]) <= 1:
                    self._quitar_actor(act)
                    return
                scenes.quitar_fase(act, obj)
        elif tipo == "actor":
            self._quitar_actor(obj)
            return
        elif tipo == "sonido" and obj in self.escena["sonidos"]:
            self.escena["sonidos"].remove(obj)
        else:
            return
        self.tl.sel = ("", None)
        self._elegir("", None)
        self._ensuciar()
        self.tl.refrescar()

    # ================================================================ aplicar / quitar / volver
    def showEvent(self, e):
        super().showEvent(e)
        ws = getattr(self.win, "workspaces", None)      # 📤 «Enviar a»: de entrada, la pestaña en la que estás
        if ws is not None and hasattr(self, "destino") and getattr(self, "_destino_de", None) != ws.current:
            self._destino_de = ws.current               # (solo al cambiar de pestaña: no pierde lo que elegiste)
            i = self.destino.findData(ws.current)
            if i >= 0:
                self.destino.setCurrentIndex(i)

    def aplicar(self) -> bool:
        ws = getattr(self.win, "workspaces", None)
        destino = self.destino.currentData() if hasattr(self, "destino") else None
        if ws is not None and destino and destino != ws.current:
            return self._aplicar_en(destino)
        if scenes.es_comparativa(self.escena) and not self.comp_editor.listo():
            self.win.statusBar().showMessage("Elige las dos tomas de la comparativa (A y B).", 6000)
            return False
        if not self._tiene_contenido():
            self.win.statusBar().showMessage("La escena está vacía: añade algún personaje o sonido.", 6000)
            return False
        self.parar()
        res = self.ctrl.apply_scene(self.escena)
        if not res:
            return False
        self.resaltar = (list(res), float(self.escena["a"]))   # (al volver al editor: ir ahí y resaltarlos)
        self.escena = scenes.copia(self.ctrl.project.scenes[self.escena["id"]])
        self.sucia = False
        self.marca.setText("✓ en la línea de tiempo")
        self.marca.setToolTip("")
        self._llenar_escenas()
        self._reconstruir()
        self.win.statusBar().showMessage(f"🎬 «{self.escena.get('nombre')}» puesta en la línea de tiempo "
                                         f"({len(res)} clips). Ctrl+Z en el editor la quita.", 8000)
        return True

    def _aplicar_en(self, destino: str) -> bool:
        """📤 La escena va a OTRA pestaña (Video horizontal, Edits o Vertical): se lleva sus personajes y sonidos (los
        medios que use), se cambia a esa pestaña y se pone ahí en el mismo tiempo (un paso de Ctrl+Z allí)."""
        if scenes.es_comparativa(self.escena) and not self.comp_editor.listo():
            self.win.statusBar().showMessage("Elige las dos tomas de la comparativa (A y B).", 6000)
            return False
        if not self._tiene_contenido():
            self.win.statusBar().showMessage("La escena está vacía: añade algún personaje o sonido.", 6000)
            return False
        self.parar()
        import copy
        esc = copy.deepcopy(self.escena)
        p = self.ctrl.project
        usados: dict[str, str] = {}                        # id del medio → su archivo

        def recoger(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("media_id", "fondo_img") and isinstance(v, str) and v in p.media:
                        usados[v] = p.media[v].path
                    else:
                        recoger(v)
            elif isinstance(x, list):
                for v in x:
                    recoger(v)
        recoger(esc)
        llevar = [p.media[mid] for mid in usados]
        ws = self.win.workspaces
        ocupado = ws._busy() if hasattr(ws, "_busy") else ""
        if ocupado:                                        # (antes de salir: si no se puede, no se pierde nada)
            self.win.statusBar().showMessage(f"Espera a que termine (está {ocupado}) para enviar la escena.", 7000)
            return False
        borrador = copy.deepcopy(self.escena)
        horizontal_antes = p.width >= p.height
        w0, h0 = p.width, p.height
        self.sucia = False                                 # (lo de aquí no se pierde: va a la otra pestaña)
        self.win.go_page("edit")
        if not ws.switch(destino):                         # (canceló al guardar: vuelve a Escenas con su borrador)
            self.win.go_page("scenes")
            pg = getattr(self.win, "_scenes_widget", None)
            if pg is not None:
                pg._cargar(borrador, True)
            self.win.statusBar().showMessage("No se cambió de pestaña: la escena sigue aquí, sin aplicar.", 7000)
            return False
        c = self.ctrl
        c.adopt_media(llevar)
        por_ruta = {os.path.normcase(os.path.abspath(m.path)): m.id for m in c.project.media.values()}
        nuevo = {mid: por_ruta.get(os.path.normcase(os.path.abspath(ruta))) for mid, ruta in usados.items()}

        def cambiar(x):
            if isinstance(x, dict):
                for k, v in list(x.items()):
                    if k in ("media_id", "fondo_img") and v in nuevo and nuevo[v]:
                        x[k] = nuevo[v]
                    else:
                        cambiar(v)
            elif isinstance(x, list):
                for v in x:
                    cambiar(v)
        cambiar(esc)
        recolocada = scenes.adaptar_formato(esc, w0, h0, c.project.width, c.project.height)   # (📐 otro formato)
        res = c.apply_scene(esc)
        nombre = self.destino.currentText()
        if not res:                                        # (no se pudo poner aquí: la escena sigue, sin perderse)
            self.win.go_page("scenes")
            pg = getattr(self.win, "_scenes_widget", None)
            if pg is not None:
                pg._cargar(esc, True)
            self.win.statusBar().showMessage(f"No se pudo poner la escena en {nombre}: sigue abierta aquí, sin "
                                             "aplicar (¿algún personaje que ya no existe o una pista bloqueada?).",
                                             9000)
            return False
        if res:
            try:
                self.win.engine.user_seek(float(esc["a"]))
                self.win.timeline.flash_clips(list(res))
            except Exception:  # noqa: BLE001 - resaltar es un extra
                pass
            aviso = ""
            if recolocada:
                aviso = " Los personajes se recolocaron para este formato (🎬 Editar la escena para retocarlos)."
            elif horizontal_antes != (c.project.width >= c.project.height):
                aviso = " Ojo: se hizo en otro formato, revisa dónde quedan los personajes (🎬 Editar la escena)."
            self.win.statusBar().showMessage(f"🎬 «{esc.get('nombre')}» puesta en {nombre} ({len(res)} clips). "
                                             f"Ctrl+Z la quita.{aviso}", 10000)
        return bool(res)

    def quitar(self):
        self.parar()
        self.resaltar = None
        eid = self.escena["id"]
        if eid in self.ctrl.project.scenes:
            if QMessageBox.question(self, "Quitar escena", "¿Quito esta escena de la línea de tiempo y del proyecto? "
                                    "(se puede deshacer con Ctrl+Z en el editor)") != QMessageBox.Yes:
                return
            self.ctrl.remove_scene(eid)
        self.escena, self.sucia = self._nueva_desde_marcas(), True
        self._recargar_barra()
        self._llenar_escenas()
        self._reconstruir()

    def _descartar_ok(self) -> bool:
        if os.environ.get("EDITORIA_SIN_SONIDO") and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return True                                   # (pruebas: sin preguntar)
        r = QMessageBox.question(self, "Escena sin aplicar", "Hay cambios sin aplicar en la escena. ¿Los aplico?",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Yes:
            ws = getattr(self.win, "workspaces", None)    # (al salir se aplica AQUÍ, no en otra pestaña a mitad de
            if ws is not None and hasattr(self, "destino"):   # un cambio de pestaña o de proyecto)
                i = self.destino.findData(ws.current)
                if i >= 0:
                    self.destino.setCurrentIndex(i)
            return self.aplicar()
        return True

    def volver(self, destino: str = "edit"):
        if self.sucia and self._tiene_contenido() and not self._descartar_ok():
            return False
        self.parar()
        if self._job is not None:
            self._job.cancel()
        self.closed.emit(destino)
        return True
