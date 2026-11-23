"""
🔁 Material repetido en la interfaz (fase 4 + huella por plano). La lógica está en core/repetidos.py; aquí:

  · MapaVivo(ctrl): el mapa de clips repetidos al día SIN coste al pintar: se recalcula 300 ms después del último
    cambio (o cuando llega una huella nueva) y avisa (cambio) para repintar. Pide a la cola de análisis (prioridad
    BAJA: con el PC libre) la huella de los videos de la línea de tiempo que aún no la tienen. Nunca espera.
  · pintar_franja(p, r, tramos, ui_k) / pintar_boton(p, r, ui_k, derecha) -> QRectF: la franja discreta abajo del
    clip (solo en el trozo repetido) y el botón «Cambiar por otro tramo no usado» en su barra de título.
  · poner_en_menu(menu, ctrl, clip_id, mapa, avisar): la misma acción en el clic derecho (el menú se construye aparte).
  · Bandejas(ctrl): «No usados · N» y «Usados 2+ veces · N» para Medios (filtran la lista con el gancho de la
    biblioteca). instalar_bandejas(win) la pone si la biblioteca tiene el gancho.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..core import huella_plano as HP
from ..core import repetidos as R

COLOR_FRANJA = QColor(232, 176, 64)          # ámbar apagado: se ve sin gritar (la selección y la IA tienen el suyo)
DEBOUNCE_MS = 300
MIRAR_HUELLAS_MS = 5000


class MapaVivo(QObject):
    """El mapa de repetidos al día. Tras cada cambio (300 ms después del último) toma una instantánea de los clips
    (rápida, aquí) y calcula el mapa en OTRO hilo (con 40 archivos de 90 min eran ~650 ms en la interfaz); al acabar,
    si nadie cambió nada mientras tanto, lo pone y avisa (cambio). recalcular() lo hace al momento (pruebas, menús)."""
    cambio = Signal()
    _listo = Signal(int, object)          # (número de cálculo, mapa) desde el hilo de cálculo

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.mapa: dict[str, list] = {}
        self._clave = None                 # (versión del proyecto, huellas) del mapa que hay
        self._n = 0                        # número del último cálculo pedido (los viejos se tiran)
        self._pedidas: dict[str, tuple] = {}   # path -> (trabajo de la cola, intentos)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._en_segundo_plano)
        self._mirar = QTimer(self)
        self._mirar.setInterval(MIRAR_HUELLAS_MS)
        self._mirar.timeout.connect(self._huellas_nuevas)
        self._mirar.start()
        self._listo.connect(self._poner)
        ctrl.project_changed.connect(self._timer.start)
        ctrl.project_replaced.connect(self._timer.start)
        ctrl.media_changed.connect(self._timer.start)
        self._timer.start()

    def de(self, clip_id: str) -> list:
        return self.mapa.get(clip_id, ())

    def _clave_ahora(self):
        return (getattr(self.ctrl, "rev", None), getattr(self.ctrl, "proj_seq", 0), id(self.ctrl.project),
                HP.generacion)

    def _huellas_nuevas(self):
        if self._clave is not None and self._clave[3] != HP.generacion:     # (llegó una huella: hay que recalcular)
            self._timer.start()

    def recalcular(self):
        """Al momento, en este hilo."""
        clave = self._clave_ahora()
        if clave == self._clave:
            return
        self._n += 1
        missing = getattr(self.ctrl, "missing", set())
        try:
            nuevo = R.mapa(self.ctrl.project, missing, clave)
        except Exception:  # noqa: BLE001 - una ayuda visual nunca rompe la edición
            nuevo = {}
        self._poner_mapa(clave, nuevo)
        self._pedir_huellas(missing)

    def _en_segundo_plano(self):
        clave = self._clave_ahora()
        if clave == self._clave:
            return
        self._n += 1
        n = self._n
        missing = getattr(self.ctrl, "missing", set())
        try:
            foto = R.instantanea(self.ctrl.project, missing)
        except Exception:  # noqa: BLE001
            return
        self._pedir_huellas(missing)
        import threading

        def calcular():
            try:
                res = R.calcular_mapa_de(foto)
            except Exception:  # noqa: BLE001
                res = {}
            try:
                self._listo.emit(n, (clave, res))
            except RuntimeError:              # (la ventana ya se cerró)
                pass
        threading.Thread(target=calcular, daemon=True, name="mapa_repetidos").start()

    def _poner(self, n: int, dato):
        if n != self._n:
            return                             # (mientras tanto se pidió otro cálculo: este ya es viejo)
        clave, res = dato
        if clave != self._clave_ahora():
            self._timer.start()                # (el proyecto cambió durante el cálculo: otra vuelta)
            return
        self._poner_mapa(clave, res)

    def _poner_mapa(self, clave, nuevo):
        self._clave = clave
        cambio = nuevo != self.mapa
        self.mapa = nuevo
        if cambio:
            self.cambio.emit()

    def _pedir_huellas(self, missing):
        """La huella de los videos de la línea de tiempo que aún no la tienen, a la cola (BAJA). Si su análisis se
        cancela o falla, se vuelve a pedir (como mucho 3 veces). En las pruebas, no (salvo RECLAIMER_HUELLAS=1)."""
        if os.environ.get("EDITORIA_DATOS") and os.environ.get("RECLAIMER_HUELLAS") != "1":
            return
        try:
            from . import cola_analisis as CA
        except Exception:  # noqa: BLE001
            return
        vistos = set()
        for c, m in R._visuales(self.ctrl.project, missing):
            if m.kind != "video" or m.path in vistos:
                continue
            vistos.add(m.path)
            trabajo, intentos = self._pedidas.get(m.path, (None, 0))
            if trabajo is not None and CA.cola().buscar(trabajo.clave) is trabajo:
                continue                       # (sigue en la cola)
            if intentos >= 3 or HP.hecho(m.path) or not os.path.isfile(m.path):
                continue
            try:
                t = CA.analizar_archivo(m.path, float(m.duration or 0), CA.BAJA, ["huella"],
                                        f"🧬 Huella visual de «{os.path.basename(m.path)}» (con el PC libre)")
            except Exception:  # noqa: BLE001
                t = None
            self._pedidas[m.path] = (t, intentos + 1)


# ------------------------------------------------------------------ 🧬 huellas de lo que PUEDE entrar
_PEDIDAS_FUERA: dict = {}        # ruta → (trabajo, intentos): videos que aún no están en la línea de tiempo


def pedir_huellas_de(ctrl, media_ids, motivo: str = "") -> int:
    """🧬 La huella visual (BAJA, con el PC libre) de videos que aún NO están en la línea de tiempo pero pueden entrar:
    el elegido en Autocompletar y los candidatos del B-roll (22/11). Así, cuando entren, ya se sabe si repiten un
    momento que ya sale desde OTRO archivo. Como _pedir_huellas: sin repetir lo que sigue en la cola, como mucho 3
    intentos por archivo y, en las pruebas, nada (salvo RECLAIMER_HUELLAS=1). Devuelve cuántos se pidieron."""
    if os.environ.get("EDITORIA_DATOS") and os.environ.get("RECLAIMER_HUELLAS") != "1":
        return 0
    try:
        from . import cola_analisis as CA
    except Exception:  # noqa: BLE001
        return 0
    p, n = ctrl.project, 0
    for mid in dict.fromkeys(media_ids or []):
        m = p.media.get(mid)
        if m is None or m.kind != "video" or mid in getattr(ctrl, "missing", ()) or not os.path.isfile(m.path):
            continue
        trabajo, intentos = _PEDIDAS_FUERA.get(m.path, (None, 0))
        if trabajo is not None and CA.cola().buscar(trabajo.clave) is trabajo:
            continue
        if intentos >= 3 or HP.hecho(m.path):
            continue
        try:
            t = CA.analizar_archivo(m.path, float(m.duration or 0), CA.BAJA, ["huella"],
                                    f"🧬 Huella visual de «{os.path.basename(m.path)}»"
                                    + (f" ({motivo})" if motivo else "") + " (con el PC libre)")
        except Exception:  # noqa: BLE001
            t = None
        _PEDIDAS_FUERA[m.path] = (t, intentos + 1)
        n += t is not None
    return n


# ------------------------------------------------------------------ pintado (lo llama la línea de tiempo)
def pintar_franja(p: QPainter, r: QRectF, tramos: list[tuple[float, float]], ui_k: float = 1.0):
    """Franja de 3 px abajo del clip, solo en los trozos repetidos (x0, x1 en píxeles ya calculados)."""
    h = max(2.0, 3.0 * ui_k)
    for x0, x1 in tramos:                             # (fillRect: sin cambiar lápiz ni brocha del pintor)
        x0, x1 = max(r.left(), x0), min(r.right(), x1)
        if x1 - x0 >= 1.0:
            p.fillRect(QRectF(x0, r.bottom() - h - 1, x1 - x0, h), COLOR_FRANJA)


def rect_boton(r: QRectF, ui_k: float = 1.0, derecha: float | None = None) -> QRectF | None:
    """Dónde va el botón «Cambiar…»: en la barra de título del clip, pegado a «derecha» (por defecto, el borde
    derecho). Cabe con pistas bajas. None si el clip es demasiado estrecho (el nombre necesita su sitio)."""
    lado = 15.0 * ui_k - 3
    if r.width() < 60 * ui_k:
        return None
    x1 = r.right() - 3 if derecha is None else derecha
    if x1 - lado < r.left() + 20 * ui_k:
        return None
    return QRectF(x1 - lado, r.top() + 1.5, lado, lado)


def pintar_boton(p: QPainter, r: QRectF, ui_k: float = 1.0, encima: bool = False,
                 derecha: float | None = None) -> QRectF | None:
    """El botón monocromo (icono «replace») de «Cambiar por otro tramo no usado». Devuelve su rectángulo."""
    b = rect_boton(r, ui_k, derecha)
    if b is None:
        return None
    p.drawPixmap(b.topLeft(), _pixmap_boton(b.width(), encima))
    return b


_CACHE_BOTON: dict = {}


def _pixmap_boton(lado: float, encima: bool):
    """El botón entero (fondo redondeado + icono monocromo) en un pixmap a doble resolución, una vez por tamaño."""
    from PySide6.QtGui import QPixmap
    clave = (round(lado, 2), encima)
    pm = _CACHE_BOTON.get(clave)
    if pm is not None:
        return pm
    from . import diseno as D
    n = max(1, int(round(lado * 2)))
    pm = QPixmap(n, n)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.Antialiasing)
    q.setPen(QPen(QColor(0, 0, 0, 150), 1))
    q.setBrush(QBrush(QColor(28, 28, 30, 235 if encima else 200)))
    q.drawRoundedRect(QRectF(0.5, 0.5, lado - 1, lado - 1), 3, 3)
    tam = max(6, int(lado - 3))
    q.drawPixmap(QPointF((lado - tam) / 2, (lado - tam) / 2), D.pixmap_icono("replace", "#ffffff" if encima else
                                                                            "#d8d8dc", tam))
    q.end()
    _CACHE_BOTON[clave] = pm
    return pm


def tramos_px(c, reps, x_de) -> list[tuple[float, float]]:
    """Los trozos repetidos del clip c en píxeles (x_de: segundos de la línea de tiempo → x). Una imagen: entera."""
    out = []
    for rep in reps:
        if rep.b - rep.a <= 1e-6:
            t0, t1 = c.start, c.end
        else:
            t0, t1 = R.tramo_en_linea(c, rep.a, rep.b)
        out.append((x_de(t0), x_de(t1)))
    return out


# ------------------------------------------------------------------ clic derecho (se construye aparte de abrirse)
def poner_en_menu(menu, ctrl, clip_id: str, mapa: MapaVivo | None, avisar=None):
    """Añade «Cambiar por otro tramo no usado» al menú del clip si su tramo está repetido. Devuelve la acción."""
    from . import diseno as D
    reps = mapa.de(clip_id) if mapa is not None else ()
    if not reps:
        return None
    a = menu.addAction(D.icono("replace"), R.NOMBRE_CAMBIAR)
    a.setToolTip(R.texto_tooltip(ctrl.project, clip_id, list(reps)))
    a.triggered.connect(lambda _=False: cambiar(ctrl, clip_id, avisar))
    return a


def cambiar(ctrl, clip_id: str, avisar=None) -> str:
    msg = R.cambiar_por_no_usado(ctrl, clip_id)
    if msg:
        (avisar or ctrl.message.emit)(msg)
    return msg


# ------------------------------------------------------------------ bandejas de Medios
NOMBRE_BANDEJA = {"no_usados": "No usados", "usados_2": "Usados 2+ veces"}


class Bandejas(QWidget):
    """Dos botones con su cuenta: «No usados · N» y «Usados 2+ veces · N». Pulsar uno filtra la lista de Medios a esos
    archivos (gancho de la biblioteca: filtrar_por_ids(ids | None, nombre)); pulsarlo otra vez, todo."""
    filtro = Signal(object, str)          # (set de media_id | None, nombre de la bandeja)

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        from . import diseno as D
        self.ctrl = ctrl
        self.datos = {"no_usados": [], "usados_2": []}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(4))
        self.btn_no = QPushButton()
        self.btn_no.setIcon(D.icono("eye-off"))
        self.btn_no.setToolTip("No usados: los archivos de Medios que todavía no salen en la línea de tiempo.\n"
                               "Clic = ver solo esos · otra vez = ver todo.")
        self.btn_dos = QPushButton()
        self.btn_dos.setIcon(D.icono("copy"))
        self.btn_dos.setToolTip("Usados 2+ veces: los archivos que salen dos veces o más en la línea de tiempo (un "
                                "clip partido cuenta una vez).\nClic = ver solo esos · otra vez = ver todo.\n"
                                "En la línea de tiempo, la franja ámbar abajo de un clip marca el tramo que se "
                                "repite, también si es el mismo momento desde otro archivo.")
        for b in (self.btn_no, self.btn_dos):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        lay.addStretch(1)
        self.btn_no.toggled.connect(lambda on: self._elegir("no_usados", on))
        self.btn_dos.toggled.connect(lambda on: self._elegir("usados_2", on))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refrescar)
        ctrl.project_changed.connect(self._timer.start)
        ctrl.project_replaced.connect(self._timer.start)
        ctrl.media_changed.connect(self._timer.start)
        self.refrescar()

    def activa(self) -> str:
        return "no_usados" if self.btn_no.isChecked() else "usados_2" if self.btn_dos.isChecked() else ""

    def ids(self, cual: str) -> set[str]:
        lst = self.datos.get(cual, [])
        return {x[0] if isinstance(x, tuple) else x for x in lst}

    def refrescar(self):
        try:
            self.datos = R.bandejas(self.ctrl.project, getattr(self.ctrl, "missing", set()))
        except Exception:  # noqa: BLE001
            self.datos = {"no_usados": [], "usados_2": []}
        self.btn_no.setText(f"No usados · {len(self.datos['no_usados'])}")
        self.btn_dos.setText(f"Usados 2+ veces · {len(self.datos['usados_2'])}")
        for b in (self.btn_no, self.btn_dos):         # (el texto entero, nunca cortado)
            b.setMinimumWidth(b.sizeHint().width())
        cual = self.activa()
        if cual:
            self.filtro.emit(self.ids(cual), NOMBRE_BANDEJA[cual])

    def _elegir(self, cual: str, on: bool):
        otro = self.btn_dos if cual == "no_usados" else self.btn_no
        if on and otro.isChecked():
            otro.blockSignals(True)
            otro.setChecked(False)
            otro.blockSignals(False)
        if on:
            self.filtro.emit(self.ids(cual), NOMBRE_BANDEJA[cual])
        elif not self.activa():
            self.filtro.emit(None, "")


def instalar_bandejas(win) -> Bandejas | None:
    """Pone las bandejas en Medios si la biblioteca tiene el gancho (poner_bandejas + filtrar_por_ids). Una vez."""
    lib = getattr(win, "library", None)
    if lib is None or not hasattr(lib, "poner_bandejas"):
        return None
    ya = getattr(lib, "_bandejas_repetidos", None)
    if ya is not None:
        return ya
    w = Bandejas(win.ctrl)
    if hasattr(lib, "filtrar_por_ids"):
        w.filtro.connect(lib.filtrar_por_ids)
    lib.poner_bandejas(w)
    lib._bandejas_repetidos = w
    return w
