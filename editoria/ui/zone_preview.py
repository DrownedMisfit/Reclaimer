"""
⧉ Transiciones reales en el visor (ver core/zone_render.py): al poner o cambiar una transición, su tramo se
renderiza en segundo plano (de una en una, en prioridad baja) y el visor lo enseña por encima de las pistas mientras
el cabezal pasa por ahí. Hasta que esté listo se ve la aproximación de siempre (un fundido).
Reproducción → «⧉ Transiciones reales en el visor» lo apaga.
"""
from __future__ import annotations

import bisect
import os
import threading

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

KEY = "visor/transiciones_reales"
KEY_FX = "visor/prerender_efectos"
WINDOW = 120.0            # solo se preparan los tramos a menos de 2 min del cabezal (lo demás, cuando llegues)
BEHIND_FX = 20.0          # (de los pesados, lo que ya pasó solo un poco: 20 s atrás y 2 min por delante)
Z = 8.99                  # encima de las pistas, debajo de los textos (9) y los subtítulos (10)


def enabled() -> bool:
    return str(QSettings("EditorIA", "EditorIA").value(KEY, "true")).lower() == "true"


def fx_enabled() -> bool:
    return str(QSettings("EditorIA", "EditorIA").value(KEY_FX, "true")).lower() == "true"


class ZonePreview(QObject):
    _ready = Signal(str, str)          # (clave, ruta) desde el hilo que renderiza
    marks_changed = Signal(list)       # [(t0, t1, estado, por qué)] para la franja de la regla (ver marks())

    def __init__(self, engine):
        super().__init__(engine)
        self.engine = engine
        self.ctrl = engine.ctrl
        self.zones: list = []            # [Zone] ordenadas por t0
        self._t0s: list[float] = []
        self.ready: dict[str, str] = {}  # clave → ruta
        self._queue: list = []           # [(Zone, proyecto ligero)]
        self._busy = False
        self._gen = 0
        self._sources: dict[str, object] = {}     # ruta → FrameSource (las 3 últimas)
        self._shown_key = None
        self._rev_ok = None                       # versión del proyecto con la que se calcularon los tramos
        self._failed: set[str] = set()            # claves que FFmpeg no pudo renderizar (no se reintentan)
        self._closing = False
        self._thread = None
        self._center = None                       # dónde estaba el cabezal al preparar la cola
        self._doing = None                        # clave que se está renderizando ahora
        self._off: list = []                      # efectos del visor apagados mientras se ve un tramo
        self.item = QGraphicsPixmapItem()
        self.item.setZValue(Z)
        self.item.setTransformationMode(Qt.SmoothTransformation)   # (suave al escalar)
        self.item.hide()
        engine.preview.canvas.scene().addItem(self.item)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)             # (tras dejar de editar: no se renderiza en cada paso de un arrastre)
        self._timer.timeout.connect(self.recalc)
        for sig in (self.ctrl.project_changed, self.ctrl.project_replaced, self.ctrl.media_changed):
            sig.connect(self._changed)
        self._ready.connect(self._on_ready)
        self._timer.start()

    def _changed(self, *_a):
        """Algo cambió: lo renderizado puede no valer. Bajo el cabezal se vuelve a mirar YA (es barato) para no tapar
        lo que estás cambiando con la imagen de antes; el resto, al dejar de editar."""
        self._timer.start()
        if self._shown_key is not None or self.zone_at(self.engine.time) is not None:
            self.hide()
            self._rev_ok = None

    # ----------------------------------------------------------------- qué tramos hay
    def recalc(self):
        from ..core import zone_render as ZR
        self._gen += 1
        self._rev_ok = getattr(self.ctrl, "rev", None)
        if not enabled() and not fx_enabled():
            self.zones, self._t0s, self._queue = [], [], []
            self.hide()
            self._emit_marks()
            return
        try:
            from ..core import escena_clip             # 🎬 (los clips de escena, desplegados: su clave cambia al editarla)
            pq = escena_clip.expandir(self.ctrl.project)
            with pq.lectura(getattr(self.ctrl, "rev", None)):
                zs = ZR.zones(pq, transitions=enabled(), heavy=fx_enabled())
        except Exception:  # noqa: BLE001 - la vista previa nunca debe molestar al editar
            zs = []
        self.zones = zs
        self._t0s = [z.t0 for z in zs]
        self._fill_queue()
        self._emit_marks()
        t = self.engine.time
        ZR.clean({f"zona_{z.key}.mp4" for z in zs if z.t1 > t - WINDOW and z.t0 < t + WINDOW})
        self._next()
        self.engine._sync()                      # (lo que ya está listo se ve al momento)

    def _fill_queue(self):
        """La cola: lo que falta a menos de WINDOW s del cabezal, lo más cercano primero."""
        from ..core import zone_render as ZR
        t = self.engine.time
        self._center = t
        self._queue = []
        cerca = [z for z in self.zones if z.t0 < t + WINDOW and z.t1 > t - (BEHIND_FX if z.why == "fx" else WINDOW)]
        for z in cerca:
            if z.key == self._doing:
                continue
            if z.key in self.ready:
                if os.path.exists(self.ready[z.key]):
                    continue
                self.ready.pop(z.key, None)       # (borrado de la caché: se rehace)
            path = ZR.cached(z)
            if path:
                self.ready[z.key] = path
            elif z.key not in self._failed:
                self._queue.append((z, None))      # (la copia ligera se hace al ir a renderizarla)

    def _next(self):
        if self._busy or not self._queue:
            return
        t = self.engine.time                      # lo de delante del cabezal primero (y lo más cerca)
        self._queue.sort(key=lambda zq: (0 if zq[0].t0 <= t < zq[0].t1 else 1 if zq[0].t0 >= t else 2,
                                         min(abs(zq[0].t0 - t), abs(zq[0].t1 - t))))
        z, q = self._queue.pop(0)
        self._doing = z.key
        self._emit_marks()
        if q is None:
            from ..core import zone_render as ZR
            q = ZR.light_copy(self.ctrl.project, z.a, z.b)
        self._busy = True
        gen = self._gen

        def run():
            from ..core import zone_render as ZR
            path = ""
            try:
                path = ZR.render(q, z, cancelled=lambda: self._closing or (gen != self._gen and z.key not in
                                                                          {x.key for x in self.zones}))
            except Exception as ex:  # noqa: BLE001 - si no se puede, se ve la aproximación de siempre
                path = "" if "Cancelado" in str(ex) else "!"
            try:
                self._ready.emit(z.key, path)
            except RuntimeError:                  # (la ventana ya se cerró)
                pass
        self._thread = threading.Thread(target=run, name="zona_transicion", daemon=True)
        self._thread.start()

    def _on_ready(self, key: str, path: str):
        self._busy = False
        self._doing = None
        if path == "!":
            self._failed.add(key)
            path = ""
        if path:
            self.ready[key] = path
            if self.zone_at(self.engine.time) is not None:
                self.engine._sync()
        self._emit_marks()
        self._next()

    def marks(self) -> list:
        """Estado de cada tramo para la regla: «ok» listo, «work» preparándose ahora, «wait» en cola, «far» lejos del
        cabezal (se prepara cuando llegues), «fail» no se pudo (se ve la aproximación de siempre)."""
        en_cola = {z.key for z, _q in self._queue}
        out = []
        for z in self.zones:
            st = ("ok" if z.key in self.ready else "work" if z.key == self._doing else
                  "fail" if z.key in self._failed else "wait" if z.key in en_cola else "far")
            out.append((z.t0, z.t1, st, z.why))
        return out

    def _emit_marks(self):
        try:
            self.marks_changed.emit(self.marks())
        except RuntimeError:
            pass

    # ----------------------------------------------------------------- en el visor
    def zone_at(self, t: float):
        k = bisect.bisect_right(self._t0s, t) - 1
        if k >= 0 and t < self.zones[k].t1:
            return self.zones[k]
        return None

    def _calm_layers(self, on: bool):
        """Mientras se ve un tramo renderizado, los efectos del visor de debajo (máscara, zonas, color…) no se
        calculan: no se ven y eran lo que hacía ir lento."""
        if on:
            for layer in list(self.engine.preview.canvas.layers.values()):
                try:
                    eff = layer.box.graphicsEffect()
                    if eff is not None and eff.isEnabled():
                        eff.setEnabled(False)
                        self._off.append(eff)
                except RuntimeError:
                    pass
        else:
            for eff in self._off:
                try:
                    eff.setEnabled(True)
                except RuntimeError:              # (ya no existe: se cambió de efecto)
                    pass
            self._off = []

    def hide(self):
        self._calm_layers(False)
        if self.item.isVisible():
            self.item.hide()
        if self._shown_key is not None:
            src = self._sources.get(self._shown_key[0])
            if src is not None:
                src.trim()                        # (fuera del tramo: casi sin memoria)
        self._shown_key = None

    def show_at(self, t: float, playing: bool):
        if getattr(self.engine, "color_bypass", False) or getattr(self.engine, "_under_now", 0.0) > 0.01 \
                or self._live_edit():
            self.hide()                           # (👁 sin corrección, un texto que desenfoca lo de debajo, o lo estás
            return                                # moviendo/recortando en el visor: se ve en vivo, no lo renderizado)
        if self._rev_ok is None or self._rev_ok != getattr(self.ctrl, "rev", None):
            self.hide()                           # (cambiaste algo: hasta recalcular, lo de siempre, nunca lo viejo)
            if not self._timer.isActive() and (enabled() or fx_enabled()):
                self._timer.start()               # (versión nueva sin aviso, p. ej. al guardar: se recalcula)
            return
        if self._center is not None and abs(t - self._center) > WINDOW / 2:
            self._fill_queue()                    # (te has ido lejos: se preparan los tramos de allí)
            self._emit_marks()
            self._next()
        z = self.zone_at(t) if self.zones else None
        if playing:
            self._prefetch(t, z)
        path = self.ready.get(z.key) if z is not None else None
        if path is None:
            self.hide()
            return
        src = self._source(path)
        canvas = self.engine.preview.canvas
        src.want(t - z.a, playing, self._size())     # (mismo aspecto que el lienzo, nunca más que el render)
        fr = src.frame_at(t - z.a)
        if fr is None:
            self.hide()                          # (aún no hay fotograma: la aproximación, sin saltos raros)
            return
        pts, w, h, data = fr
        sig = (path, pts, w, h)
        if sig != self._shown_key:
            img = QImage(data, w, h, w * 4, QImage.Format_RGBA8888)
            self.item.setPixmap(QPixmap.fromImage(img))
            from PySide6.QtGui import QTransform
            self.item.setTransform(QTransform.fromScale(canvas.W / max(1, w), canvas.H / max(1, h)))
            self.item.setPos(0, 0)
            self._shown_key = sig
        if not self.item.isVisible():
            self.item.show()
        self._calm_layers(True)

    def _live_edit(self) -> bool:
        """¿Estás arrastrando algo en el visor (mover, recortar, zonas, zoom dinámico, rueda)? Esos cambios van en
        vivo sin pasar por el proyecto: el tramo renderizado los taparía."""
        cv = self.engine.preview.canvas
        if any(getattr(cv, k, None) is not None for k in ("_tf_drag", "_crop_drag", "_reg_drag", "_dz_drag")):
            return True
        tw = getattr(cv, "_tf_wheel", None)
        if tw is not None and tw.isActive():
            return True
        return any(getattr(lay, "live_regions", None) is not None for lay in cv.layers.values())

    def _size(self):
        from ..core import zone_render as ZR
        canvas = self.engine.preview.canvas
        vis = canvas.mapFromScene(canvas.frame.rect()).boundingRect()
        dpr = max(1.0, float(canvas.devicePixelRatioF()))     # (con la escala de la interfaz: píxeles de verdad)
        s = min(1.0, ZR.WIDTH / max(canvas.W, canvas.H, 1), max(vis.width() * dpr, 2) / max(canvas.W, 1))
        return max(2, int(canvas.W * s) // 2 * 2), max(2, int(canvas.H * s) // 2 * 2)

    def _prefetch(self, t: float, cur):
        """Reproduciendo: el tramo que empieza en menos de 0,6 s ya va decodificándose (se entra sin saltos)."""
        k = bisect.bisect_right(self._t0s, t)
        if k < len(self.zones) and self.zones[k] is not cur and self.zones[k].t0 - t < 0.6:
            z = self.zones[k]
            path = self.ready.get(z.key)
            if path:
                self._source(path).want(max(0.0, z.t0 - z.a), False, self._size())

    def _source(self, path: str):
        src = self._sources.get(path)
        if src is not None and src.cerrado:            # (🔓 cerrada por soltar_archivos: se abre otra)
            self._sources.pop(path, None)
            src = None
        if src is None:
            from ..core.live_video import FrameSource
            src = self._sources[path] = FrameSource(path)
            while len(self._sources) > 3:
                old = next(iter(self._sources))
                self._sources.pop(old).close()
        else:
            self._sources[path] = self._sources.pop(path)      # (la más reciente al final)
        return src

    def set_enabled(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue(KEY, "true" if on else "false")
        self.recalc()

    def set_fx_enabled(self, on: bool):
        QSettings("EditorIA", "EditorIA").setValue(KEY_FX, "true" if on else "false")
        self.recalc()

    def shutdown(self):
        self._closing = True
        self._gen += 1
        self._queue = []
        th = self._thread
        if th is not None and th.is_alive():
            th.join(2.0)                          # (FFmpeg se mata al ver «cerrando»: no queda nada a medias)
        for s in self._sources.values():
            s.close()
        self._sources.clear()
