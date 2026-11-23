"""
🎬 ARMA TU VIDEO, la parte de la interfaz (paso 3 de «Edita desde tu voz»): lo que el panel llama. La lógica (sin Qt)
está en ai/armar_video.py.

  a = Armador(ctrl, ajustes=None, fuentes=None)
  a.empezar(desde=0.0, hasta=None, en_cadena=False)   arma ese tramo (segundos de la LÍNEA DE TIEMPO; hasta=None = hasta
                                                       el final). en_cadena=True: la transcripción sigue llegando;
                                                       se arma por trozos a medida que avisas con trozo_listo()
  a.trozo_listo(desde=None, hasta=None)   llegó otro trozo transcrito (sin datos: arma desde lo hecho hasta la última
                                          frase transcrita, salvo la última, que puede estar a medias)
  a.transcripcion_terminada()             ya está todo: arma lo que quede y termina
  a.cancelar()                            lo puesto se queda (un Ctrl+Z lo quita); nada a medias
  a.seguir()                              «Seguir armando» (si se cerró a medias: ai/armar_video.pendiente)
  Señales: progreso(fracción, texto) · trozo_puesto(desde, hasta, clips) · aviso(texto) · terminado(resumen)

Nunca bloquea: el plan va por la cola única de análisis (ui/cola_analisis, prioridad ALTA, cancelable) y espera
mientras reproduces o exportas (pausa_automatica); colocar va en el hilo de la interfaz, por trozos, cada uno solo en lo
que sigue vacío. Todo el armado es UN paso de Ctrl+Z (ai/armar_video.Sesion). Si cambias de pestaña, lo que ya está
buscado espera a que vuelvas a su proyecto (nunca se pone en otro).

  carpeta_relleno() / poner_carpeta_relleno(ruta)   el ajuste de la carpeta de relleno
  poner_en_menu(menu, ctrl, clip_id)                clic derecho en un clip armado → «Cambiar ▸» (2–3 alternativas)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from ..ai import armar_video as A

CLAVE_RELLENO = "armar/carpeta_relleno"
MARGEN_EN_CADENA = 1.0      # s: la última frase transcrita puede estar a medias; se arma hasta un poco antes


def _ajustes_qt() -> QSettings:
    return QSettings("EditorIA", "EditorIA")


def carpeta_relleno() -> str:
    return str(_ajustes_qt().value(CLAVE_RELLENO, "") or "")


def poner_carpeta_relleno(ruta: str | None) -> None:
    _ajustes_qt().setValue(CLAVE_RELLENO, ruta or "")


class Armador(QObject):
    progreso = Signal(float, str)
    trozo_puesto = Signal(float, float, int)
    aviso = Signal(str)
    terminado = Signal(dict)

    def __init__(self, ctrl, ajustes: dict | None = None, fuentes=None, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.ajustes = dict(ajustes or {})
        self.ajustes.setdefault("carpeta_relleno", carpeta_relleno() or None)
        self.fuentes = fuentes
        self.sesion: A.Sesion | None = None
        self._cola: list[tuple[float, float | None]] = []
        self._trabajo = None
        self._plan = None
        self._rango = None
        self._desde = 0.0
        self._hasta = None
        self._hecho_hasta = 0.0
        self._en_cadena = False
        self._completa = True
        self._cancelado = False
        self._activo = False
        self._resumen = {"puestos": 0, "faltan": 0.0, "avisos": [], "saltados": 0}
        self._avisado_antes = False

    # ---------------------------------------------------------------- lo que llama el panel
    def ocupado(self) -> bool:
        return self._activo

    def empezar(self, desde: float = 0.0, hasta: float | None = None, en_cadena: bool = False) -> bool:
        if self._activo:
            return False
        if self.fuentes is None:
            self.fuentes = A.Fuentes()
        self.sesion = A.Sesion(self.ctrl)
        self._desde, self._hasta = float(desde or 0.0), hasta
        self._hecho_hasta = self._desde
        self._en_cadena, self._completa = bool(en_cadena), not en_cadena
        self._cancelado, self._activo, self._avisado_antes = False, True, False
        self._resumen = {"puestos": 0, "faltan": 0.0, "avisos": [], "saltados": 0}
        self._cola = [] if en_cadena else [(self._desde, hasta)]
        if en_cadena:
            self.trozo_listo()
        self._siguiente()
        return True

    def seguir(self) -> bool:
        d = A.pendiente(self.ctrl)
        if not d:
            return False
        self.ajustes.update(d.get("ajustes") or {})
        return self.empezar(float(d.get("hecho_hasta") or 0.0), d.get("hasta"), en_cadena=False)

    def trozo_listo(self, desde: float | None = None, hasta: float | None = None):
        if not self._activo:
            return
        if hasta is None:                                  # hasta la última frase transcrita (sin la última)
            frases, _n = A._frases_en_linea(self.ctrl.project)
            if len(frases) < 2:
                return
            hasta = max(self._hecho_hasta, frases[-2]["t1"] + 0.3, frases[-1]["t0"] - MARGEN_EN_CADENA)
            if self._hasta is not None:
                hasta = min(hasta, self._hasta)
        a = max(self._ultimo_pedido(), float(desde) if desde is not None else 0.0)
        if hasta - a >= A.MIN_PIEZA:
            self._cola.append((a, float(hasta)))
            self._siguiente()

    def transcripcion_terminada(self):
        if not self._activo:
            return
        self._completa = True
        a = self._ultimo_pedido()
        if self._hasta is None or self._hasta - a > A.EPS:
            self._cola.append((a, self._hasta))
        self._siguiente()

    def cancelar(self):
        if not self._activo:
            return
        self._cancelado = True
        self._cola.clear()
        self._plan = None
        if self._trabajo is not None:
            from .cola_analisis import cola
            cola().cancelar(self._trabajo)
        else:
            self._fin()

    # ---------------------------------------------------------------- por dentro
    def _ultimo_pedido(self) -> float:
        hasta = [b for _a, b in self._cola if b is not None]
        if self._rango is not None and self._rango[1] is not None:
            hasta.append(self._rango[1])
        return max([self._hecho_hasta] + hasta)

    def _mismo_proyecto(self) -> bool:
        return self.sesion is not None and A.clave_proyecto(self.ctrl) == self.sesion.proyecto

    def _siguiente(self):
        if not self._activo or self._trabajo is not None or self._plan is not None:
            return
        if not self._cola:
            if self._completa:
                self._fin()
            return
        if not self._mismo_proyecto():                     # (otra pestaña: se espera a volver a su proyecto)
            QTimer.singleShot(1000, self._siguiente)
            return
        self._rango = self._cola.pop(0)
        desde, hasta = self._rango
        inst = A.instantanea(self.ctrl, desde, hasta, self.ajustes)
        if not self._avisado_antes:
            self._avisado_antes = True
            for t in A.avisos_previos(inst, self.fuentes):
                self.aviso.emit(t)
        if not inst["piezas"]:
            self._hecho_hasta = max(self._hecho_hasta, hasta if hasta is not None else self._hecho_hasta)
            self._rango = None
            QTimer.singleShot(0, self._siguiente)
            return
        from .cola_analisis import ALTA, cola, pausa_automatica
        fuentes = self.fuentes

        def fn(progress, control):
            return A.planear(inst, fuentes, progreso=lambda f, t: progress(f, t), cancelado=control,
                             pausado=pausa_automatica)

        def prog_ui():
            t = self._trabajo
            if t is not None:
                self.progreso.emit(float(t.progreso), t.texto or "")

        self._trabajo = cola().poner(fn, "🎬 Arma tu video", ALTA, clave=("armar", self.sesion.token, desde),
                                     pesado=True, al_terminar=self._plan_hecho, al_fallar=self._plan_fallo)
        if self._trabajo is None:                           # (la cola está cerrada: Reclaimer se cierra)
            self._fin()
            return
        try:
            cola().cambiado.connect(prog_ui)
            self._desconectar = lambda: cola().cambiado.disconnect(prog_ui)
        except (RuntimeError, TypeError):
            self._desconectar = None

    def _soltar_trabajo(self):
        self._trabajo = None
        if getattr(self, "_desconectar", None):
            try:
                self._desconectar()
            except (RuntimeError, TypeError):
                pass
            self._desconectar = None

    def _plan_fallo(self, msg):
        self._soltar_trabajo()
        if self._cancelado or "ancelad" in str(msg):
            self._fin()
            return
        self.aviso.emit(f"No pude armar un trozo: {msg}")
        self._rango = None
        self._siguiente()

    def _plan_hecho(self, plan):
        self._soltar_trabajo()
        if self._cancelado:
            self._fin()
            return
        self._plan = plan
        self._aplicar()

    def _aplicar(self):
        if self._plan is None or not self._activo:
            return
        from .cola_analisis import pausa_automatica
        if pausa_automatica() or not self._mismo_proyecto():   # (reproduciendo, exportando u otra pestaña: espera)
            QTimer.singleShot(700, self._aplicar)
            return
        plan, self._plan = self._plan, None
        res = A.colocar(self.ctrl, plan, self.sesion)
        if res.get("deshecho"):
            self.aviso.emit("Deshiciste el armado: lo paro.")
            self._cancelado = True
            self._fin()
            return
        for t in res.get("avisos") or []:
            if t not in self._resumen["avisos"]:
                self._resumen["avisos"].append(t)
                self.aviso.emit(t)
        self._resumen["puestos"] += len(res.get("puestos") or [])
        self._resumen["faltan"] += float(res.get("faltan") or 0.0)
        self._resumen["saltados"] += int(res.get("saltados") or 0)
        desde, hasta = self._rango or (self._hecho_hasta, None)
        fin = hasta if hasta is not None else max([self._hecho_hasta] + [p["t1"] for p in plan.get("piezas") or []])
        self._hecho_hasta = max(self._hecho_hasta, fin)
        self._rango = None
        A.guardar_estado(self.ctrl, self._desde, self._hasta, self._hecho_hasta, self.ajustes, self._completa)
        self.trozo_puesto.emit(float(desde), float(fin), len(res.get("puestos") or []))
        self._siguiente()

    def _fin(self):
        if not self._activo:
            return
        self._activo = False
        self._soltar_trabajo()
        if not self._cancelado and self._completa:
            A.guardar_estado(self.ctrl, self._desde, self._hasta, self._hecho_hasta, self.ajustes, True)
            A.borrar_estado(self.ctrl)                     # (terminado: ya no hay nada que seguir)
        res = dict(self._resumen, cancelado=self._cancelado)
        self.terminado.emit(res)


# ---------------------------------------------------------------- clic derecho → «Cambiar»
def poner_en_menu(menu, ctrl, clip_id: str):
    """Si el clip lo puso «Arma tu video» y guarda alternativas: «Cambiar ▸» con cada una (un clic cambia, un Ctrl+Z).
    Devuelve el submenú o None."""
    alts = A.alternativas_validas(ctrl, clip_id)        # (solo las que hoy no repiten nada)
    if not alts:
        return None
    sub = menu.addMenu("Cambiar")
    sub.setToolTipsVisible(True)
    for k, alt in alts:
        act = sub.addAction(A.texto_alternativa(alt))
        act.setToolTip(alt.get("motivo") or "")
        act.triggered.connect(lambda _=False, i=k: _cambiar(ctrl, clip_id, i))
    return sub


def _cambiar(ctrl, clip_id: str, k: int):
    if A.cambiar(ctrl, clip_id, k) is None:
        try:
            ctrl.message.emit("Esa alternativa ya sale en otro sitio de la línea de tiempo: elige otra.")
        except (RuntimeError, AttributeError):
            pass
