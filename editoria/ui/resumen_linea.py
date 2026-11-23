"""
🗺 BARRA RESUMEN DE TODO EL VIDEO (fase 8, como la página Cortar de DaVinci): una franja fina encima de la línea de
tiempo con el video entero: los clips de video (arriba) y de sonido (abajo) con su color, los temas, los marcadores
y el cabezal, y lo que se ve ahora como un recuadro. Clic = ver ese momento; arrastrar el recuadro = recorrerlo. Así
se navega una reseña de 30 min sin tocar el zoom.

Sin coste al pintar: lo del proyecto se dibuja una vez en un pixmap (200 ms después del último cambio); al pintar solo
se ponen el pixmap, el recuadro y el cabezal.

  ResumenLinea(ctrl, timeline)    el widget (alto fijo); visible según «timeline/resumen» (sí por defecto)
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..core.model import TRACK_AUDIO, TRACK_VIDEO

ALTO = 16


class ResumenLinea(QWidget):
    def __init__(self, ctrl, timeline, parent=None):
        super().__init__(parent)
        self.ctrl, self.tl = ctrl, timeline
        self._capa: QPixmap | None = None
        self._dur = 1.0
        self._arrastre = None                 # desfase (s) entre el ratón y el principio de lo visible
        self.setFixedHeight(ALTO)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Todo el video: los clips de video (arriba) y de sonido (abajo), los temas y los marcadores; "
                        "el recuadro es lo que se ve abajo.\nClic = ver ese momento · arrastra el recuadro = recorrer el "
                        "video sin cambiar el zoom.\nSe enseña o se esconde en Timeline → «Barra resumen de todo el "
                        "video».")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.rehacer)
        for sig in ("project_changed", "project_replaced", "media_changed"):
            s = getattr(ctrl, sig, None)
            if s is not None:
                s.connect(self._timer.start)
        timeline.vista_cambia.connect(self.update)
        self._x_cabezal = None
        self._ultimo_cabezal = 0.0
        self._cab_timer = QTimer(self)                # (el cabezal, a 30 fps como mucho y solo su trocito)
        self._cab_timer.setSingleShot(True)
        self._cab_timer.timeout.connect(self._pintar_cabezal)
        self.setVisible(False)
        self._timer.start(0)

    def encendida(self) -> bool:
        return str(QSettings("EditorIA", "EditorIA").value("timeline/resumen", "true")).lower() == "true"

    def _actualizar_visible(self):
        """Encendida y con clips: a la vista. Sin clips, escondida (nada de franjas vacías)."""
        quiero = self.encendida() and bool(self.ctrl.project.clips)
        if quiero != self.isVisible():
            self.setVisible(quiero)

    def cabezal_movido(self, *_a):
        """El cabezal se movió (reproduciendo o arrastrando): su raya, a 30 fps como mucho."""
        if not self.isVisible() or self._cab_timer.isActive():
            return
        import time as _t
        espera = max(0, int((self._ultimo_cabezal + 1 / 30 - _t.monotonic()) * 1000))
        self._cab_timer.start(espera)

    def _pintar_cabezal(self):
        import time as _t
        self._ultimo_cabezal = _t.monotonic()
        x = self.x_de(min(self.tl.playhead, self._dur))
        if self._x_cabezal is not None and abs(x - self._x_cabezal) < 0.5:
            return
        from PySide6.QtCore import QRect
        for xx in (self._x_cabezal, x):
            if xx is not None:
                self.update(QRect(int(xx) - 3, 0, 7, self.height()))
        self._x_cabezal = x

    # ------------------------------------------------------------ geometría
    def _x0(self) -> float:
        return float(self.tl.HEADER_W)         # (alineada con la regla de debajo)

    def _ancho(self) -> float:
        # (el mismo ancho que la línea de tiempo de debajo: sin la barra de desplazamiento vertical de su lado)
        return max(1.0, min(self.width(), self.tl.width()) - self._x0() - 2)

    def x_de(self, t: float) -> float:
        return self._x0() + t / self._dur * self._ancho()

    def t_de(self, x: float) -> float:
        return min(max((x - self._x0()) / self._ancho() * self._dur, 0.0), self._dur)

    def recuadro(self) -> QRectF:
        a = self.tl.scroll
        b = a + self.tl.segundos_visibles()
        x0, x1 = self.x_de(a), self.x_de(min(b, self._dur))
        return QRectF(x0, 0.5, max(4.0, x1 - x0), self.height() - 1)

    # ------------------------------------------------------------ lo del proyecto, una vez
    def rehacer(self):
        """Lo del proyecto en el pixmap: cada columna de píxeles con el color del último clip que la tapa (por pista:
        video arriba, sonido abajo) y se pinta por tramos del mismo color. ⚡ El color se pide una vez por TIPO de clip
        (archivo, nota, pista…), no por clip; y nada si la barra no se ve (se hace al enseñarla)."""
        self._actualizar_visible()
        if not self.isVisible():
            self._capa = None
            return
        import numpy as np
        p = self.ctrl.project
        self._dur = max(1.0, p.duration())
        w, h = max(1, self.width()), self.height()
        x0, ancho = self._x0(), self._ancho()
        esc = ancho / self._dur
        tipos = {t.id: t.kind for t in p.tracks}
        colores: list = []
        cache: dict = {}
        bandas = {TRACK_VIDEO: np.full(w, -1, np.int32), TRACK_AUDIO: np.full(w, -1, np.int32)}
        for c in p.clips.values():
            k = tipos.get(c.track_id)
            if k not in bandas or not c.enabled:
                continue
            clave = (c.media_id, c.note, c.track_id, c.label, c.text is None)
            idx = cache.get(clave)
            if idx is None:
                try:
                    col = self.tl._clip_base(c)[0]
                except Exception:  # noqa: BLE001
                    col = QColor("#5d6068")
                idx = cache[clave] = len(colores)
                colores.append(col)
            a = int(x0 + c.start * esc)
            b = max(a + 1, int(x0 + c.end * esc + 0.999))
            bandas[k][max(0, a):min(w, b)] = idx
        pm = QPixmap(w, h)
        pm.fill(QColor(24, 25, 28))
        q = QPainter(pm)
        medio = h / 2
        for k, fila in bandas.items():
            y = 2.0 if k == TRACK_VIDEO else medio + 1
            cambios = np.flatnonzero(np.diff(fila)) + 1
            inicios = np.concatenate(([0], cambios))
            fines = np.concatenate((cambios, [w]))
            for a, b in zip(inicios, fines):
                if fila[a] >= 0:
                    q.fillRect(QRectF(float(a), y, float(b - a), medio - 3), colores[fila[a]])
        for m in p.markers:                    # temas: raya de su color abajo · marcadores: palito
            col = QColor(m.color or "#f2b33d")
            if m.kind == "topic" and m.end is not None:
                q.fillRect(QRectF(self.x_de(m.time), h - 2, max(1.0, self.x_de(m.end) - self.x_de(m.time)), 2), col)
            elif not getattr(m, "resuelto", False):
                q.fillRect(QRectF(self.x_de(m.time) - 0.5, 0, 1.5, h), col)
        q.end()
        self._capa = pm
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._timer.start(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._timer.start(0)

    def paintEvent(self, _e):
        p = QPainter(self)
        if self._capa is not None and self._capa.width() == self.width():
            p.drawPixmap(0, 0, self._capa)
        else:
            p.fillRect(self.rect(), QColor(24, 25, 28))
        r = self.recuadro()                    # lo que se ve abajo
        p.setPen(QPen(QColor(255, 255, 255, 210), 1))
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRect(r)
        x = self.x_de(min(self.tl.playhead, self._dur))
        self._x_cabezal = x
        p.setPen(QPen(QColor("#e5413c"), 1.5))
        p.drawLine(int(x), 0, int(x), self.height())
        p.end()

    # ------------------------------------------------------------ ratón
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        t = self.t_de(e.position().x())
        r = self.recuadro()
        if r.contains(e.position()):
            self._arrastre = t - self.tl.scroll
        else:
            self.tl.centrar_en(t)
            self._arrastre = t - self.tl.scroll

    def mouseMoveEvent(self, e):
        if self._arrastre is None:
            return
        self.tl.scroll = max(0.0, self.t_de(e.position().x()) - self._arrastre)
        self.tl._update_scrollbar()
        self.tl.update()

    def mouseReleaseEvent(self, _e):
        self._arrastre = None

    def poner_visible(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue("timeline/resumen", "true" if on else "false")
        self._actualizar_visible()
        if self.isVisible():
            self.rehacer()
