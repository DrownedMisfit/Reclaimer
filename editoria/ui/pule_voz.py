"""
🎙 «Edita desde tu voz», paso 2 «Pule tu voz» — la lista de dudas (23/11, plan secciones 1, 6 y 7).

  · Una sola lista: ▶ escuchar · ✓ quitar (un Ctrl+Z por duda) · ✗ dejar. Teclado: ↑/↓ moverse, Enter = ✓,
    Supr = ✗, Espacio = ▶. Nada se corta sin ✓ (salvo «aplicar solas mis órdenes habladas», apagado de entrada).
  · Las tomas son tarjetas grandes: mapa de minutos arriba (dónde cae cada versión en la narración), cada versión
    con su duración real (franja proporcional), su minuto, a qué distancia está de la elegida, un icono de estado
    (completa / traba / incompleta), sus primeras y últimas palabras; clic = elegirla y saltar ahí en la línea de
    tiempo; «Escuchar seguidas»; «Juntar» si lo mejor es el principio de una y el final de otra.
  · Opciones (plegadas): aplicar solas mis órdenes habladas, mis órdenes (lista editable), pegar el guion.
  · «Comprobar lo editado»: retranscribe lo que queda en la línea de tiempo y avisa de lo que sobre, con su minuto.
  · Las dudas salen de ai/pule_voz.analizar (que reutiliza repetition_detection y silence_detection); se guardan en
    Project.edita_voz["dudas"]; si deshaces un ✓ con Ctrl+Z, su duda vuelve a estar pendiente.
  · Por trozos: se analiza en cuanto llega cada minuto transcrito (la última frase, en el trozo siguiente).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..ai import pule_voz as PV
from . import diseno as D

AJ_SOLAS = "edita_voz/ordenes_solas"
AJ_ORDENES = "edita_voz/ordenes"
ICONO_TIPO = {"tomas": "copy", "orden": "megaphone", "traba": "scissors", "frase": "scissors", "pausa": "pause",
              "ruido": "audio-waveform", "intencion": "list-music", "queda": "triangle-alert"}
ICONO_ESTADO = {"completa": "circle-check", "traba": "triangle-alert", "incompleta": "circle-dashed"}
NOMBRE_ESTADO = {"completa": "completa y sin trabas", "traba": "con una traba o muletilla",
                 "incompleta": "incompleta (a medias)"}


def _aj() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


def _negrita():
    from PySide6.QtGui import QFont
    return QFont.DemiBold


def _normal():
    from PySide6.QtGui import QFont
    return QFont.Normal


def _distancia(s: float) -> str:
    if abs(s) < 1.0:
        return "la elegida"
    m = abs(s) / 60.0
    cuanto = f"{int(round(abs(s)))} s" if abs(s) < 90 else f"{m:.0f} min"
    return f"{cuanto} {'antes' if s > 0 else 'después'}"


def _icono_btn(nombre: str, tip: str, color: str | None = None) -> QToolButton:
    b = QToolButton()
    b.setIcon(D.icono(nombre, color or D.colores()["texto"], 16))
    b.setIconSize(QSize(D.px(16), D.px(16)))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    return b


# ====================================================================================== piezas de la tarjeta de tomas
class MapaMinutos(QWidget):
    """Una barra = toda la narración; una marca por versión (la elegida, con el acento)."""

    def __init__(self, total: float, versiones: list, elegida: int, parent=None):
        super().__init__(parent)
        self.total, self.vs, self.elegida = max(1.0, total), versiones, elegida
        self.setFixedHeight(D.px(16))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Dónde cae cada versión en tu narración (la elegida, resaltada)")

    def paintEvent(self, _e):            # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, f = D.colores(), D.fichas()
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(f["campo"]))
        p.drawRoundedRect(QRectF(0, h * 0.35, w, h * 0.3), 2, 2)
        for k, v in enumerate(self.vs):
            x0 = v["a"] / self.total * w
            x1 = max(x0 + 3, v["b"] / self.total * w)
            p.setBrush(QColor(c["acento"] if k == self.elegida else c["tenue"]))
            p.drawRoundedRect(QRectF(x0, 1, x1 - x0, h - 2), 2, 2)
        p.end()


class BarraDuracion(QWidget):
    """La duración real de una versión: una franja proporcional (una toma de 45 s se ve larga)."""

    def __init__(self, dur: float, maxima: float, elegida: bool, parent=None):
        super().__init__(parent)
        self.f, self.elegida = min(1.0, dur / max(0.1, maxima)), elegida
        self.setFixedHeight(D.px(5))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _e):            # noqa: N802
        p = QPainter(self)
        c = D.colores()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["acento"] if self.elegida else c["apagado"]))
        p.drawRoundedRect(QRectF(0, 0, max(4.0, self.width() * self.f), self.height()), 2, 2)
        p.end()


class FranjaVersion(QFrame):
    """Una versión de la toma: estado, minuto, duración, distancia, primeras y últimas palabras. Clic = elegirla."""
    pulsada = Signal(int)

    def __init__(self, k: int, v: dict, maxima: float, elegida: bool, parent=None):
        super().__init__(parent)
        self.k = k
        self.setObjectName("pv_version")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(4), D.px(2), D.px(4), D.px(3))
        lay.setSpacing(D.px(1))
        fila = QHBoxLayout()
        fila.setSpacing(D.px(4))
        ic = QLabel()
        c = D.colores()
        ic.setPixmap(D.pixmap_icono(ICONO_ESTADO.get(v["estado"], "circle-check"),
                                    c["acento"] if elegida else c["tenue"], D.px(14)))
        ic.setToolTip(NOMBRE_ESTADO.get(v["estado"], ""))
        fila.addWidget(ic)
        dur = v["b"] - v["a"]
        datos = QLabel(f"{PV.minuto(v['a'])} · {dur:.0f} s · {_distancia(v.get('distancia', 0.0))}")
        datos.setFont(D.fuente(D.LETRA_P, _negrita() if elegida else _normal()))
        datos.setWordWrap(True)
        fila.addWidget(datos, 1)
        lay.addLayout(fila)
        lay.addWidget(BarraDuracion(dur, maxima, elegida))
        txt = QLabel(v["ini"] + (f"  {v['fin']}" if v.get("fin") else ""))
        txt.setWordWrap(True)
        txt.setFont(D.fuente(D.LETRA_P))
        txt.setStyleSheet(f"color: {c['texto'] if elegida else c['tenue']};")
        lay.addWidget(txt)
        self.setToolTip(f"«{v['texto']}»\n{NOMBRE_ESTADO.get(v['estado'], '')}\nClic = quedarte con esta y verla en "
                        "la línea de tiempo")
        f = D.fichas()
        borde = c["acento"] if elegida else "transparent"
        self.setStyleSheet(f"#pv_version {{ border: 1px solid {borde}; border-radius: {D.px(4)}px; }}"
                           f"#pv_version:hover {{ background: {f['control_hover_arriba']}; }}")

    def mousePressEvent(self, e):        # noqa: N802
        if e.button() == Qt.LeftButton:
            self.pulsada.emit(self.k)
        super().mousePressEvent(e)


# ====================================================================================== una tarjeta (cualquier duda)
def _breve(d: dict) -> str:
    """Lo mínimo que se lee en la tarjeta (lo demás, en el tooltip): la cita de lo que se quitaría."""
    det = d.get("detalle") or ""
    if d["tipo"] in ("orden", "frase") and "«" in det:
        return det[det.index("«"):]
    if d["tipo"] == "traba" and "«" in det:
        return det[det.index("«"):]
    return ""


class Tarjeta(QFrame):
    """Una duda: cabecera (icono, título, minuto), detalle, versiones si son tomas, y ▶ ✓ ✗."""
    escuchar = Signal(str)
    seguidas = Signal(str)
    aceptar = Signal(str)
    descartar = Signal(str)
    elegir = Signal(str, int)
    activar = Signal(str)

    def __init__(self, d: dict, total: float, parent=None):
        super().__init__(parent)
        self.d = d
        self.clave = d["clave"]
        self.setObjectName("pv_tarjeta")
        self.setAttribute(Qt.WA_StyledBackground, True)
        c = D.colores()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(D.px(6), D.px(4), D.px(4), D.px(4))
        lay.setSpacing(D.px(2))
        # (fase 6, compacto: una sola fila con icono, título, minuto y ▶ ✓ ✗; la explicación, en el tooltip)
        cab = QHBoxLayout()
        cab.setSpacing(D.px(3))
        ic = QLabel()
        ic.setPixmap(D.pixmap_icono(ICONO_TIPO.get(d["tipo"], "scissors"), c["tenue"], D.px(14)))
        cab.addWidget(ic)
        tit = QLabel(d["titulo"])
        tit.setWordWrap(True)
        tit.setFont(D.fuente(D.LETRA_P, _negrita()))
        cab.addWidget(tit, 1)
        mn = QLabel(PV.minuto(d["t"]))
        mn.setFont(D.fuente(D.LETRA_P, tabular=True))
        mn.setStyleSheet(f"color: {c['tenue']};")
        cab.addWidget(mn)
        lay.addLayout(cab)
        # (2.ª fila: la cita de lo que se quita, y a su derecha ▶ ✓ ✗; el título cabe entero en la 1.ª)
        fila = QHBoxLayout()
        fila.setSpacing(D.px(2))
        breve = _breve(d)
        det = QLabel(breve)
        det.setWordWrap(True)
        det.setFont(D.fuente(D.LETRA_P))
        det.setStyleSheet(f"color: {c['tenue']};")
        fila.addWidget(det, 1)
        cab = fila
        self.b_oir = _icono_btn("play", "Escuchar (Espacio)")
        self.b_oir.clicked.connect(lambda: self.escuchar.emit(self.clave))
        cab.addWidget(self.b_oir, 0, Qt.AlignTop)
        if d.get("versiones"):
            b = _icono_btn("headphones", "Escuchar seguidas: todas las versiones, una tras otra")
            b.clicked.connect(lambda: self.seguidas.emit(self.clave))
            cab.addWidget(b)
        if d.get("juntar"):
            b = _icono_btn("merge", "Juntar: el principio de la primera y el final de la segunda, en su punto común"
                                    f"\n«{d['juntar']['texto']}»")
            b.setCheckable(True)
            b.setChecked(d.get("elegida") == -1)
            b.clicked.connect(lambda: self.elegir.emit(self.clave, -1))
            cab.addWidget(b)
        self.b_si = _icono_btn("check", "Quitar lo marcado (Enter). Un Ctrl+Z lo devuelve")
        self.b_si.clicked.connect(lambda: self.aceptar.emit(self.clave))
        self.b_no = _icono_btn("x", "Dejarlo como está (Supr)")
        self.b_no.clicked.connect(lambda: self.descartar.emit(self.clave))
        cab.addWidget(self.b_si, 0, Qt.AlignTop)
        cab.addWidget(self.b_no, 0, Qt.AlignTop)
        lay.addLayout(fila)
        self.tip = d.get("detalle") or ""
        self.franjas: list[FranjaVersion] = []
        if d.get("versiones"):
            vs = d["versiones"]
            e = d.get("elegida", 0)
            lay.addWidget(MapaMinutos(total, vs, e))
            maxima = max(v["b"] - v["a"] for v in vs)
            for k, v in enumerate(vs):
                fr = FranjaVersion(k, v, maxima, k == e)
                fr.pulsada.connect(lambda kk, cl=self.clave: self.elegir.emit(cl, kk))
                lay.addWidget(fr)
                self.franjas.append(fr)
        self.poner_estado(d.get("estado", "pendiente"), False)

    def poner_estado(self, estado: str, actual: bool):
        c, f = D.colores(), D.fichas()
        borde = c["acento"] if actual else f["bloque_borde"]
        fondo = f["bloque"] if estado == "pendiente" else f["fondo"]
        self.setStyleSheet(f"#pv_tarjeta {{ background: {fondo}; border: 1px solid {borde}; "
                           f"border-radius: {D.px(5)}px; }}")
        hecha = estado != "pendiente"
        self.b_si.setEnabled(not hecha)
        self.b_si.setIcon(D.icono("check-check" if estado == "hecha" else "check",
                                  c["acento"] if estado == "hecha" else c["texto"], 16))
        self.b_no.setIcon(D.icono("x", c["acento"] if estado == "descartada" else c["texto"], 16))
        extra = {"hecha": "Quitado (Ctrl+Z lo devuelve)", "descartada": "Lo dejaste como está (✗ otra vez = volver "
                 "a pensarlo)"}.get(estado, "")
        self.setToolTip("\n".join(x for x in (getattr(self, "tip", ""), extra) if x))
        for fr in self.franjas:
            fr.setEnabled(not hecha)

    def mousePressEvent(self, e):        # noqa: N802
        self.activar.emit(self.clave)
        super().mousePressEvent(e)


class ListaDudas(QScrollArea):
    """La lista con teclado: ↑/↓, Enter = ✓, Supr = ✗, Espacio = ▶."""
    tecla = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.caja = QWidget()
        self.vl = QVBoxLayout(self.caja)
        self.vl.setContentsMargins(0, 0, 0, 0)
        self.vl.setSpacing(D.px(5))
        self.vl.addStretch(1)
        self.setWidget(self.caja)

    TECLAS = {Qt.Key_Up: "arriba", Qt.Key_Down: "abajo", Qt.Key_Return: "si", Qt.Key_Enter: "si",
              Qt.Key_Delete: "no", Qt.Key_Space: "oir"}

    def event(self, e):                  # (Supr y Espacio son atajos de la ventana: aquí mandan las dudas)
        if e.type() == QEvent.ShortcutOverride and e.key() in self.TECLAS and not e.modifiers():
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):          # noqa: N802
        k = e.key()
        if k in self.TECLAS and not e.modifiers():
            self.tecla.emit(self.TECLAS[k])
            return
        super().keyPressEvent(e)


# ====================================================================================== la página del paso 2
class PaginaPule(QWidget):
    """Paso 2 «Pule tu voz». La lógica (análisis, ✓/✗, deshacer) vive aquí; el panel solo la aloja."""

    def __init__(self, ev):
        super().__init__()
        self.ev, self.win, self.ctrl = ev, ev.win, ev.ctrl
        self.tarjetas: dict[str, Tarjeta] = {}
        self.orden_claves: list[str] = []
        self.actual: str | None = None
        self.job = None
        self.job_cmp = None
        self._muestras: dict[str, object] = {}       # ruta → audio 16 kHz (para cortes finos y ruidos)
        self._aplicadas: dict[str, tuple] = {}       # clave → (pila, posición, texto) del ✓ (para Ctrl+Z)
        self._verbatim_hecho: set[str] = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(D.px(6))
        cab = QHBoxLayout()
        cab.setSpacing(D.px(3))
        self.resumen = QLabel("")
        self.resumen.setWordWrap(True)
        self.resumen.setFont(D.fuente(D.LETRA_P))
        cab.addWidget(self.resumen, 1)
        self.b_comprobar = _icono_btn("list-checks", "Comprobar lo editado: vuelve a transcribir lo que queda en la "
                                                     "línea de tiempo y avisa de lo que sobre, con su minuto")
        self.b_comprobar.clicked.connect(self.comprobar)
        cab.addWidget(self.b_comprobar)
        self.b_opciones = _icono_btn("sliders-horizontal", "Opciones: órdenes habladas y guion")
        self.b_opciones.setCheckable(True)
        self.b_opciones.toggled.connect(lambda on: self.opciones.setVisible(on))
        cab.addWidget(self.b_opciones)
        lay.addLayout(cab)
        # opciones (plegadas)
        self.opciones = QWidget()
        ol = QVBoxLayout(self.opciones)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(D.px(4))
        self.chk_solas = QCheckBox("Aplicar solas mis órdenes habladas")
        self.chk_solas.setToolTip("Si dices «quita esto», «otra vez»… mientras grabas, se quita solo (sin esperar tu ✓). "
                                  "Apagado: salen en la lista ya marcadas.")
        self.chk_solas.setChecked(str(_aj().value(AJ_SOLAS, "false")).lower() == "true")
        self.chk_solas.toggled.connect(lambda on: _aj().setValue(AJ_SOLAS, "true" if on else "false"))
        ol.addWidget(self.chk_solas)
        self.ordenes = QLineEdit(", ".join(self.lista_ordenes()))
        self.ordenes.setToolTip("Tus órdenes habladas, separadas por comas. Solo cuentan si las dices sueltas, con una "
                                "pausa antes y después.")
        self.ordenes.editingFinished.connect(self._guardar_ordenes)
        ol.addWidget(self.ordenes)
        self.guion = QPlainTextEdit()
        self.guion.setPlaceholderText("Pega tu guion (opcional)")
        self.guion.setToolTip("Con tu guion pegado, en cada grupo de tomas gana por defecto la que más se le parece.")
        self.guion.setFixedHeight(D.px(60))
        self.guion.textChanged.connect(lambda: self._t.start())
        ol.addWidget(self.guion)
        self.opciones.hide()
        lay.addWidget(self.opciones)
        self.lista = ListaDudas()
        self.lista.tecla.connect(self._tecla)
        self.lista.setMinimumHeight(D.px(60))       # (lo que sobre de alto, para la lista; «Seguir» siempre entero)
        lay.addWidget(self.lista, 1)
        self.vacio = QLabel("Esperando el primer minuto transcrito…")
        self.vacio.setWordWrap(True)
        self.vacio.setStyleSheet(f"color: {D.colores()['tenue']};")
        self.vacio.setToolTip("Las dudas salen por trozos, mientras se transcribe: puedes empezar por el principio.")
        lay.addWidget(self.vacio)
        self.queda = QLabel("")
        self.queda.setWordWrap(True)
        self.queda.setTextFormat(Qt.PlainText)
        self.queda.setFont(D.fuente(D.LETRA_P))
        self.queda.hide()
        lay.addWidget(self.queda)
        self.b_seguir = QPushButton("Seguir: arma tu video")
        self.b_seguir.setObjectName("primary")
        self.b_seguir.setToolTip("Pasar al paso 3 (las dudas que queden se pueden revisar luego)")
        self.b_seguir.clicked.connect(self._seguir)
        lay.addWidget(self.b_seguir)
        self.foco = self.lista
        self._t = QTimer(self)                     # (varios trozos seguidos = un solo análisis)
        self._t.setSingleShot(True)
        self._t.setInterval(1200)
        self._t.timeout.connect(self.analizar)
        ev.texto_parcial.connect(lambda _m: self._t.start())
        ev.transcripcion_lista.connect(lambda: self.analizar(final=True))
        ev.voz_colocada.connect(lambda _ids: self._t.start())
        self.ctrl.project_replaced.connect(self.recargar)
        self.ctrl.project_changed.connect(self._revisar_deshacer)
        self.recargar()

    # ------------------------------------------------------------------ datos
    def estado(self) -> dict:
        return self.ev.estado()

    def dudas(self) -> list[dict]:
        return self.estado().setdefault("dudas", [])

    def lista_ordenes(self) -> list[str]:
        v = _aj().value(AJ_ORDENES, "")
        lst = [x.strip() for x in str(v or "").split(",") if x.strip()]
        return lst or list(PV.ORDENES)

    def _guardar_ordenes(self):
        lst = [x.strip() for x in self.ordenes.text().split(",") if PV.es_orden_valida(x)]
        _aj().setValue(AJ_ORDENES, ", ".join(lst))
        self._t.start()

    def _media(self, ruta: str) -> str | None:
        return self.ev._media_de(ruta)

    def _duracion_voz(self, d: dict) -> float:
        tr = self.ctrl.project.transcripts.get(d.get("media_id") or "") or {}
        ws = tr.get("words") or []
        m = self.ctrl.project.media.get(d.get("media_id") or "")
        return max(float(m.duration) if m is not None else 0.0, ws[-1][1] if ws else 0.0, 1.0)

    # ------------------------------------------------------------------ análisis (hilo)
    def analizar(self, final: bool = False):
        ev = self.estado()
        voces = [r for r in ev.get("voz") or [] if self._media(r)]
        if not voces or ev.get("saltar_pule"):
            self.pintar()
            return
        if self.job is not None:
            self._t.start()
            return
        p = self.ctrl.project
        datos = []
        for r in voces:
            mid = self._media(r)
            tr = p.transcripts.get(mid) or {}
            if not tr.get("words"):
                continue
            hasta = None if tr.get("hasta") is None else max(0.0, float(tr["hasta"]) - 3.0)
            datos.append((r, mid, [list(w) for w in tr["words"]], hasta))
        if not datos:
            self.pintar()
            return
        guion = self.guion.toPlainText()
        ordenes = self.lista_ordenes()
        muestras = dict(self._muestras)
        modelo = self.ev._modelo()
        hacer_verbatim = final

        def fn(progress, cancelled):
            from ..ai import transcription
            from ..core import media as media_tools
            out = []
            for i, (r, mid, words, hasta) in enumerate(datos):
                progress(i / len(datos), "Buscando dudas en tu voz…")
                s = muestras.get(r)
                if s is None:
                    try:
                        s = media_tools.decode_mono(r, transcription.SAMPLE_RATE)
                    except Exception:  # noqa: BLE001 - sin audio: solo con las palabras
                        s = None
                    muestras[r] = s
                ds = PV.analizar(words, s, transcription.SAMPLE_RATE, guion, ordenes, None, hasta)
                nuevas = None
                if hacer_verbatim and hasta is None and s is not None:
                    try:
                        nuevas = PV.verbatim_en_dudas(s, transcription.SAMPLE_RATE, words, ds, modelo, "es",
                                                      cancelled)
                    except Exception:  # noqa: BLE001 - el oído literal es un extra
                        nuevas = None
                    if nuevas is not None:
                        ds = PV.analizar(nuevas, s, transcription.SAMPLE_RATE, guion, ordenes, None, None)
                out.append((r, mid, ds, nuevas))
            return out, muestras

        from .jobs import BackgroundJob
        self.job = BackgroundJob(fn, self.win)
        self.job.title = "🎙 Pule tu voz"
        self.job.done.connect(self._analizado)
        self.job.finished.connect(self._fin_job)
        self.job.start()

    def _fin_job(self):
        self.job = None

    def _analizado(self, res):
        out, muestras = res
        self._muestras.update({k: v for k, v in muestras.items() if v is not None})
        viejas = {d["clave"]: d for d in self.dudas()}
        nuevas: list[dict] = []
        solas = []
        for r, mid, ds, palabras in out:
            if mid not in self.ctrl.project.media:
                continue
            if palabras is not None:                  # (lo recuperado palabra por palabra, al texto)
                tr = dict(self.ctrl.project.transcripts.get(mid) or {}, words=palabras)
                self.ctrl.set_transcript(mid, tr)
            for d in ds:
                d["media_id"], d["ruta"] = mid, r
                v = viejas.pop(d["clave"], None)
                if v is not None and v.get("estado", "pendiente") != "pendiente":
                    nuevas.append(v)
                    continue
                if v is not None and "elegida" in v and v.get("elegida_tuya"):
                    d["elegida"], d["elegida_tuya"] = v["elegida"], True
                d["estado"] = "pendiente"
                nuevas.append(d)
                if d["tipo"] == "orden" and self.chk_solas.isChecked():
                    solas.append(d)
        nuevas += [v for v in viejas.values() if v.get("estado") != "pendiente"]   # (lo hecho se queda)
        nuevas.sort(key=lambda d: (d.get("ruta", ""), d["t"]))
        self.estado()["dudas"] = nuevas
        self.ctrl._set_media_dirty()
        if solas:
            self._aplicar_varias(solas, "🎙 Tus órdenes habladas")
        self.pintar()

    # ------------------------------------------------------------------ pintar
    def recargar(self):
        self._aplicadas.clear()
        self.pintar()
        if self.estado().get("voz") and not self.estado().get("dudas"):
            self._t.start()

    def pintar(self):
        ds = [d for d in self.dudas() if d.get("media_id") in self.ctrl.project.media]
        claves = [d["clave"] for d in ds]
        if claves != self.orden_claves or any(self.tarjetas.get(d["clave"]) is None
                                              or self.tarjetas[d["clave"]].d is not d for d in ds):
            for t in self.tarjetas.values():
                self.lista.vl.removeWidget(t)        # (fuera del orden ya: las nuevas van en su sitio)
                t.hide()
                t.deleteLater()
            self.tarjetas = {}
            for i, d in enumerate(ds):
                t = Tarjeta(d, self._duracion_voz(d))
                t.escuchar.connect(self.escuchar)
                t.seguidas.connect(self.escuchar_seguidas)
                t.aceptar.connect(self.aceptar)
                t.descartar.connect(self.descartar)
                t.elegir.connect(self.elegir_version)
                t.activar.connect(self.poner_actual)
                self.lista.vl.insertWidget(i, t)
                self.tarjetas[d["clave"]] = t
            self.orden_claves = claves
        if self.actual not in self.tarjetas:
            self.actual = next((d["clave"] for d in ds if d.get("estado", "pendiente") == "pendiente"),
                               claves[0] if claves else None)
        for d in ds:
            self.tarjetas[d["clave"]].poner_estado(d.get("estado", "pendiente"), d["clave"] == self.actual)
        pend = sum(1 for d in ds if d.get("estado", "pendiente") == "pendiente")
        hechas = sum(1 for d in ds if d.get("estado") == "hecha")
        trabajando = self.ev.job_trans is not None
        self.resumen.setText(f"{len(ds)} dudas · {pend} por revisar · {hechas} quitadas" if ds else "")
        self.resumen.setToolTip("Enter = quitar · Supr = dejar · ↑/↓ = moverse · Espacio = escuchar" +
                                ("\nSiguen llegando dudas mientras se transcribe el resto." if trabajando else ""))
        self.vacio.setVisible(not ds)
        if not ds:
            self.vacio.setText("Esperando el primer minuto transcrito…" if trabajando or self.job is not None
                               else "Sin dudas: tu voz está limpia.")
        self.lista.setVisible(bool(ds))

    # ------------------------------------------------------------------ teclado y selección
    def poner_actual(self, clave: str | None):
        self.actual = clave
        for k, t in self.tarjetas.items():
            t.poner_estado(t.d.get("estado", "pendiente"), k == clave)
        t = self.tarjetas.get(clave or "")
        if t is not None:
            self.lista.ensureWidgetVisible(t)

    def _tecla(self, que: str):
        if not self.orden_claves:
            return
        i = self.orden_claves.index(self.actual) if self.actual in self.orden_claves else 0
        if que in ("arriba", "abajo"):
            i = max(0, min(len(self.orden_claves) - 1, i + (-1 if que == "arriba" else 1)))
            self.poner_actual(self.orden_claves[i])
        elif que == "si":
            self.aceptar(self.orden_claves[i])
        elif que == "no":
            self.descartar(self.orden_claves[i])
        elif que == "oir":
            self.escuchar(self.orden_claves[i])

    def _duda(self, clave: str) -> dict | None:
        return next((d for d in self.dudas() if d["clave"] == clave), None)

    def _siguiente(self, clave: str):
        ds = [d for d in self.dudas() if d.get("media_id") in self.ctrl.project.media]
        i = next((k for k, d in enumerate(ds) if d["clave"] == clave), -1)
        sig = next((d["clave"] for d in ds[i + 1:] if d.get("estado", "pendiente") == "pendiente"), None)
        self.actual = sig or clave
        self.pintar()
        self.poner_actual(self.actual)
        self.lista.setFocus(Qt.OtherFocusReason)

    # ------------------------------------------------------------------ ✓ / ✗ / elegir
    def _rangos(self, d: dict, elegida=None) -> list:
        mid = d["media_id"]
        words = (self.ctrl.project.transcripts.get(mid) or {}).get("words") or []
        s = self._muestras.get(d.get("ruta", ""))
        out = []
        for a, b in PV.quitar_de(d, elegida):
            aj = PV.ajustar_corte(a, b, words, s)
            if aj is not None:
                out.append(list(aj))
        return out

    def aceptar(self, clave: str):
        d = self._duda(clave)
        if d is None or d.get("estado", "pendiente") != "pendiente":
            return
        self._aplicar_varias([d], f"🎙 {d['titulo']} · {PV.minuto(d['t'])}")
        self._siguiente(clave)

    def _aplicar_varias(self, ds: list, texto: str):
        por_media: dict[str, list] = {}
        for d in ds:
            por_media.setdefault(d["media_id"], []).extend(self._rangos(d))
        hecho = False
        for mid, rangos in por_media.items():
            if rangos and self.ctrl.quitar_voz(mid, rangos, texto):
                hecho = True
        if not hecho:
            return
        pila = self.ctrl.undo_stack
        reg = (pila, pila.index(), texto)
        for d in ds:
            d["estado"] = "hecha"
            self._aplicadas[d["clave"]] = reg
        self.ctrl._set_media_dirty()
        self.pintar()

    def descartar(self, clave: str):
        d = self._duda(clave)
        if d is None or d.get("estado") == "hecha":
            return
        d["estado"] = "pendiente" if d.get("estado") == "descartada" else "descartada"
        self.ctrl._set_media_dirty()
        if d["estado"] == "descartada":
            self._siguiente(clave)
        else:
            self.pintar()

    def elegir_version(self, clave: str, k: int):
        """Clic en una versión = quedarte con ella (y verla en la línea de tiempo)."""
        d = self._duda(clave)
        if d is None or d.get("estado", "pendiente") != "pendiente":
            return
        if k == -1 and d.get("elegida") == -1:
            k = len(d["versiones"]) - 1             # (Juntar otra vez = deshacer la unión)
        d["elegida"], d["elegida_tuya"] = k, True
        e = k if k >= 0 else 0
        for kk, v in enumerate(d["versiones"]):
            v["distancia"] = round(d["versiones"][e]["a"] - v["a"], 1)
        d["quitar"] = PV.quitar_de(d)
        self.ctrl._set_media_dirty()
        self.orden_claves = []                      # (se rehacen las tarjetas: la elegida, resaltada)
        self.actual = clave
        self.pintar()
        if k >= 0:
            self._saltar(d["media_id"], d["versiones"][k]["a"])

    def _revisar_deshacer(self):
        """Un Ctrl+Z que devuelve lo quitado deja su duda pendiente otra vez (y Ctrl+Y la vuelve a quitar). (Se mira
        cuando el historial ya movió su índice: el aviso de cambio llega dentro del propio deshacer.)"""
        if self._aplicadas:
            QTimer.singleShot(0, self._revisar_deshacer_ya)

    def _revisar_deshacer_ya(self):
        if not self._aplicadas:
            return
        cambio = False
        for clave, (pila, pos, texto) in list(self._aplicadas.items()):
            d = self._duda(clave)
            if d is None:
                continue
            activo = (pila is self.ctrl.undo_stack and pila.index() >= pos and pos >= 1
                      and pila.command(pos - 1) is not None and pila.command(pos - 1).text() == texto)
            nuevo = "hecha" if activo else "pendiente"
            if d.get("estado") != nuevo:
                d["estado"] = nuevo
                cambio = True
        if cambio:
            self.pintar()

    def _seguir(self):
        self.estado()["paso"] = 3
        self.ctrl._set_media_dirty()
        self.ev.refrescar()
        self.ev.ir_a_paso(3)

    # ------------------------------------------------------------------ escuchar y saltar
    def _tramos_linea(self, mid: str, rangos) -> list:
        from ..core import mapping
        p = self.ctrl.project
        out = []
        for a, b in rangos:
            out += [(ta, tb) for _c, ta, tb in mapping.map_range(p, mid, a, b)]
        out = sorted(set((round(a, 3), round(b, 3)) for a, b in out))
        return out

    def _reproducir(self, tramos):
        eng = getattr(self.win, "engine", None)
        if not tramos or eng is None or os.environ.get("EDITORIA_SIN_SONIDO"):
            self._ultimo_oido = tramos
            return
        self._ultimo_oido = tramos
        eng.play_ranges(tramos)

    def escuchar(self, clave: str):
        d = self._duda(clave)
        if d is None:
            return
        self.poner_actual(clave)
        if d.get("versiones"):
            e = max(0, d.get("elegida", 0))
            r = [[d["versiones"][e]["a"], d["versiones"][e]["b"]]]
        else:
            r = [[max(0.0, a - 1.0), b + 1.0] for a, b in d.get("quitar") or []]
        self._reproducir(self._tramos_linea(d["media_id"], r))

    def escuchar_seguidas(self, clave: str):
        d = self._duda(clave)
        if d is None:
            return
        self._reproducir(self._tramos_linea(d["media_id"], [[v["a"], v["b"]] for v in d["versiones"]]))

    def _saltar(self, mid: str, s: float):
        from ..core import mapping
        p = self.ctrl.project
        t = mapping.map_time(p, mid, s)
        if t is None:
            return
        eng = getattr(self.win, "engine", None)
        if eng is not None:
            eng.seek(t)
        tl = getattr(self.win, "timeline", None)
        if tl is not None:
            c = next((c for c in mapping.clips_of_media(p, mid) if c.start - 1e-6 <= t < c.end), None)
            if c is not None and hasattr(tl, "set_selection"):
                tl.set_selection([c.id])
        self._ultimo_salto = t

    # ------------------------------------------------------------------ comprobación final
    def comprobar(self):
        """Retranscribe lo que queda de tu voz en la línea de tiempo y avisa de lo que sobre, con su minuto."""
        if self.job_cmp is not None:
            return
        from ..core import mapping
        p = self.ctrl.project
        partes = []
        for r in self.estado().get("voz") or []:
            mid = self._media(r)
            if mid is None:
                continue
            for c in mapping.clips_of_media(p, mid):
                tr_ = p.track(c.track_id)
                if tr_ is not None and tr_.kind == "audio" and c.speed > 0:
                    partes.append((r, c.start, c.source_in, c.duration))
        if not partes:
            return
        muestras = dict(self._muestras)
        modelo = self.ev._modelo()
        ordenes = self.lista_ordenes()

        def fn(progress, cancelled):
            import numpy as np
            from ..ai import transcription
            from ..core import media as media_tools
            sr = transcription.SAMPLE_RATE
            fin = max(t + d for _r, t, _s, d in partes)
            out = np.zeros(int(fin * sr) + 1, np.float32)
            for r, t, s, d in partes:
                a = muestras.get(r)
                if a is None:
                    a = muestras[r] = media_tools.decode_mono(r, sr)
                trozo = a[int(s * sr):int((s + d) * sr)]
                out[int(t * sr):int(t * sr) + len(trozo)] = trozo[:len(out) - int(t * sr)]
            progress(0.05, "Transcribiendo lo editado…")
            tr = transcription.transcribe(out, modelo, "es", lambda f, x: progress(0.05 + 0.9 * f, x), cancelled,
                                          fillers=True)
            return PV.comprobar(tr.get("words") or [], ordenes)

        from .jobs import BackgroundJob
        self.job_cmp = BackgroundJob(fn, self.win)
        self.job_cmp.title = "🎙 Comprobar lo editado"
        self.job_cmp.progress.connect(lambda f, t: (self.queda.show(), self.queda.setText(t)))
        self.job_cmp.done.connect(self._comprobado)
        self.job_cmp.failed.connect(lambda m: self.queda.setText("No se pudo comprobar: " + m))
        self.job_cmp.finished.connect(lambda: setattr(self, "job_cmp", None))
        self.queda.setText("Comprobando lo editado…")
        self.queda.show()
        self.job_cmp.start()

    def _comprobado(self, quedan: list):
        self.quedan = quedan
        if not quedan:
            self.queda.setText("Comprobado: no queda nada que pulir.")
        else:
            self.queda.setText("Queda por revisar:\n" + "\n".join(
                f"{PV.minuto(d['t'])} · {d['titulo'][7:]}" + (f" «{d['versiones'][0]['ini']}»" if d.get('versiones')
                                                             else "") for d in quedan))
        self.queda.setToolTip("Minutos de la línea de tiempo (ya editada)")
        self.queda.show()


def instalar(ev) -> PaginaPule | None:
    """Crea la página del paso 2 y la enchufa en el panel de «Edita desde tu voz»."""
    try:
        pg = PaginaPule(ev)
    except Exception:  # noqa: BLE001 - el resto de la herramienta sigue
        import traceback
        traceback.print_exc()
        return None
    ev.poner_paso(2, pg)
    ev.pule = pg
    return pg
