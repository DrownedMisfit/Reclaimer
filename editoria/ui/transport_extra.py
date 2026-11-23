"""
▶ Lo que la barra de transporte añade a los botones de siempre (en el visor de las tres pestañas —Video horizontal,
Edits y Vertical comparten el mismo visor— y en la barra de reproducción de 🎬 Escenas):

  · −5s / +5s       mueven el cabezal 5 segundos (sin pasar del principio ni del final), reproduciendo o en pausa.
                    Visor: Mayús+← / Mayús+→.
  · velocidad       botón que cicla 1× → 2× → 4× → 8× → 1×; su flechita abre el menú (1× normal de un clic). En el
                    visor es el MISMO mecanismo que J/K/L (PlaybackEngine.rate): el audio a 2×/4×/8× suena como con
                    L repetido (reproductores de Qt a esa velocidad; la mezcla en directo solo a 1×).
  · volumen         de ESCUCHA: solo lo que oyes aquí; NO cambia el proyecto ni lo exportado. Clic = silenciar,
                    rueda encima = subir/bajar, flechita = deslizador. Se recuerda (no el silencio).
  · LUFS            📊 sonoridad para plataformas: mide la mezcla entera (ebur128 de FFmpeg, en segundo plano;
                    core/loudness.measure_project) y dice cuántos dB subir o bajar para YouTube / Shorts / TikTok /
                    Instagram (−14 LUFS, pico verdadero ≤ −1 dBTP). «Aplicar» cambia el volumen de todos los clips
                    que suenan en un solo Ctrl+Z (controller.project_gain); «Solo informar» no toca nada. ANTES de
                    preguntar calcula lo que de verdad cabe (tope 400 % por clip, lo bloqueado no se toca: si algo
                    no llega, vuelve a medir la copia con esos volúmenes) y el diálogo dice el resultado real. Se
                    aplica a lo medido: si el proyecto cambió mientras medía, avisa y no aplica. Clic en ⏳ = cancelar.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QMessageBox, QSlider, QToolButton, QWidget,
                               QWidgetAction)

VELOCIDADES = (1.0, 2.0, 4.0, 8.0)
SALTO_S = 5.0                     # lo que mueven −5s / +5s
PLATAFORMAS = "YouTube, Shorts, TikTok e Instagram"


def siguiente_velocidad(v: float) -> float:
    """1× → 2× → 4× → 8× → 1× (desde una velocidad intermedia, a la siguiente de la lista)."""
    v = abs(float(v or 1.0))
    for x in VELOCIDADES:
        if x > v + 1e-6:
            return x
    return VELOCIDADES[0]


def texto_velocidad(v: float) -> str:
    return f"{abs(float(v or 1.0)):g}×"


def _num(x: float, signo: bool = False) -> str:
    """1,5 / −14,0 / +3,2 (coma decimal y signo menos de verdad, como el resto de la interfaz)."""
    s = f"{x:+.1f}" if signo else f"{x:.1f}"
    return s.replace(".", ",").replace("-", "−")


# ======================================================================= ↔ fila que no obliga a ensanchar
class FlexRow(QWidget):
    """Fila de botones que NUNCA obliga a una ventana más ancha (como la cabecera del visor, _ajustar_cabecera): su
    mínimo es el de lo imprescindible; lo opcional (prioridad 1, 2, 3…) se esconde por orden —primero el 1— cuando
    no cabe y vuelve al ensancharse. Lo escondido sigue en el menú Reproducción (y su nombre, en los tooltips)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._items: list[tuple[str, object, int | None]] = []     # ("w", widget, prioridad) · ("s", px, None)
        self._ajustando = False

    def add(self, w: QWidget, prioridad: int | None = None):
        self._lay.addWidget(w)
        self._items.append(("w", w, prioridad))

    def add_spacing(self, px: int):
        self._lay.addSpacing(px)
        self._items.append(("s", int(px), None))

    def _ancho(self, quitar=()) -> int:
        """Lo que ocupa la fila sin los opcionales de quitar (los widgets que otro esconde, como ◀◀ de J, no cuentan)."""
        sp = max(0, self._lay.spacing())
        total, n = 0, 0
        for tipo, x, prio in self._items:
            if tipo == "s":
                total += x
                continue
            if x in quitar or (prio is None and x.isHidden()):
                continue
            total += max(x.sizeHint().width(), x.minimumWidth())     # (el nivel tiene tamaño fijo y sin sizeHint)
            n += 1
        return total + sp * max(0, n - 1)

    def _opcionales(self) -> list:
        return [x for _t, x, p in sorted((i for i in self._items if i[2] is not None), key=lambda i: i[2])]

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        s.setWidth(self._ancho(set(self._opcionales())))
        return s

    def sizeHint(self):
        s = super().sizeHint()
        s.setWidth(self._ancho())
        return s

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ajustar(e.size().width())

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.LayoutRequest and self.isVisible():     # (◀◀ de J aparece, cambia la letra…)
            self._ajustar(self.width())
        return super().event(e)

    def _ajustar(self, ancho: int):
        if self._ajustando:
            return
        self._ajustando = True
        try:
            fuera = set()
            for prio in sorted({p for _t, _x, p in self._items if p is not None}):
                if self._ancho(fuera) <= ancho:
                    break
                fuera |= {x for _t, x, p in self._items if p == prio}     # (los de igual prioridad, juntos: −5s y +5s)
            for w in self._opcionales():
                if w.isHidden() != (w in fuera):
                    w.setVisible(w not in fuera)
        finally:
            self._ajustando = False


# ======================================================================= 🔊 volumen de escucha
class ListenVolume(QObject):
    """Volumen de ESCUCHA (0–100 %, lineal) con silencio. Se guarda el nivel en QSettings[clave]; el silencio
    dura lo que dura la sesión (al abrir de nuevo, siempre suena). gain = lo que multiplica lo que oyes."""
    changed = Signal(float)          # la ganancia nueva (0 si está silenciado)

    def __init__(self, clave: str, defecto: int = 100, parent=None):
        super().__init__(parent)
        self.clave = clave
        try:
            v = int(float(QSettings("EditorIA", "EditorIA").value(clave, defecto)))
        except (TypeError, ValueError):
            v = defecto
        self._valor = max(0, min(100, v))
        self._mudo = False

    @property
    def value(self) -> int:
        return self._valor

    @property
    def muted(self) -> bool:
        return self._mudo

    @property
    def gain(self) -> float:
        return 0.0 if self._mudo else self._valor / 100.0

    def set_value(self, v) -> None:
        v = max(0, min(100, int(v)))
        cambia = v != self._valor or (self._mudo and v > 0)
        self._valor = v
        if v > 0:
            self._mudo = False           # (mover el volumen quita el silencio, como en cualquier reproductor)
        QSettings("EditorIA", "EditorIA").setValue(self.clave, v)
        if cambia:
            self.changed.emit(self.gain)

    def set_muted(self, on: bool) -> None:
        on = bool(on)
        if on != self._mudo:
            self._mudo = on
            self.changed.emit(self.gain)

    def toggle_mute(self) -> None:
        self.set_muted(not self._mudo)

    def step(self, d: int) -> None:
        self.set_value(self._valor + int(d))


_ESCUCHA: ListenVolume | None = None


def escucha() -> ListenVolume:
    """El volumen de escucha del visor (el mismo en las tres pestañas). Reproducción → no cambia el proyecto."""
    global _ESCUCHA
    if _ESCUCHA is None:
        _ESCUCHA = ListenVolume("reproduccion/volumen_escucha", 100)
    return _ESCUCHA


def ganancia_escucha() -> float:
    """Lo que multiplica el sonido del visor (lo usan sus reproductores y la mezcla en directo)."""
    return escucha().gain


def icono_volumen(model: ListenVolume) -> str:
    if model.muted or model.value == 0:
        return "🔇"
    return "🔈" if model.value < 34 else "🔉" if model.value < 67 else "🔊"


class VolumeButton(QToolButton):
    """🔊 compacto: clic = silenciar / quitar el silencio · rueda encima = ±5 % · flechita = deslizador (popup=True).
    Con popup=False es solo el botón de silencio (Escenas ya tiene su deslizador al lado)."""

    def __init__(self, model: ListenVolume, popup: bool = True, que: str = "lo que oyes en el visor", parent=None):
        super().__init__(parent)
        self.model = model
        self._que = que
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(True)
        self.slider = None
        if popup:
            self.setPopupMode(QToolButton.MenuButtonPopup)
            menu = QMenu(self)
            caja = QWidget()
            hl = QHBoxLayout(caja)
            hl.setContentsMargins(8, 4, 8, 4)
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(0, 100)
            self.slider.setFixedWidth(140)
            self.slider.setValue(model.value)
            self.slider.valueChanged.connect(model.set_value)
            self.lbl = QLabel()
            self.lbl.setMinimumWidth(40)
            hl.addWidget(self.slider)
            hl.addWidget(self.lbl)
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(caja)
            menu.addAction(wa)
            self.act_mudo = menu.addAction("🔇 Silenciar", model.toggle_mute)
            self.act_mudo.setCheckable(True)
            self.setMenu(menu)
        self.clicked.connect(model.toggle_mute)
        model.changed.connect(self._refrescar)
        self._refrescar()

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d:
            self.model.step(5 if d > 0 else -5)
        e.accept()

    def _refrescar(self, *_a):
        m = self.model
        self.setText(icono_volumen(m))
        estado = "silenciado" if m.muted else f"{m.value} %"
        self.setToolTip(f"Volumen de escucha: {estado}. Solo cambia {self._que}; NO cambia el proyecto ni lo "
                        f"exportado.\nClic = silenciar / quitar el silencio · rueda encima = subir / bajar"
                        + (" · flechita = deslizador" if self.slider is not None else ""))
        if self.slider is not None:
            if self.slider.value() != m.value:
                self.slider.blockSignals(True)
                self.slider.setValue(m.value)
                self.slider.blockSignals(False)
            self.lbl.setText(f"{m.value} %")
            self.act_mudo.setChecked(m.muted)


# ======================================================================= ⏩ velocidad
class SpeedButton(QToolButton):
    """«1×»: clic = siguiente velocidad (1× → 2× → 4× → 8× → 1×); flechita = menú (1× normal de un clic).
    Con otra velocidad que 1× se pinta resaltado para que se vea."""
    cycle = Signal()
    chosen = Signal(float)

    def __init__(self, tip_extra: str = "", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(True)
        self.setPopupMode(QToolButton.MenuButtonPopup)
        menu = QMenu(self)
        self._acts = {}
        for v in VELOCIDADES:
            a = menu.addAction(f"{texto_velocidad(v)}" + ("  (normal)" if v == 1.0 else ""),
                               lambda vv=v: self.chosen.emit(vv))
            a.setCheckable(True)
            self._acts[v] = a
        self.setMenu(menu)
        self._tip = ("Velocidad de reproducción: clic = 1× → 2× → 4× → 8× → 1× · flechita = elegir (1× = normal)."
                     + (("\n" + tip_extra) if tip_extra else ""))
        self.setToolTip(self._tip)
        self.clicked.connect(self.cycle.emit)
        self.show_speed(1.0)

    def show_speed(self, v: float):
        v = abs(float(v or 1.0))
        self.setText(texto_velocidad(v))
        for x, a in self._acts.items():
            a.setChecked(abs(x - v) < 1e-6)
        self.setStyleSheet("" if abs(v - 1.0) < 1e-6 else "QToolButton { color: #ffb347; font-weight: bold; }")
        self.setToolTip(f"Ahora: {texto_velocidad(v)}\n" + self._tip)


# ======================================================================= 📊 sonoridad para plataformas
class LoudnessButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(True)
        self.setText("LUFS")
        self._tip = (f"📊 Sonoridad para plataformas ({PLATAFORMAS}): mide el volumen percibido de toda la mezcla "
                     "(LUFS integrados y pico verdadero, en segundo plano) y te dice cuántos dB subir o bajar para "
                     "llegar a −14 LUFS con el pico ≤ −1 dBTP. Puedes aplicarlo (un Ctrl+Z lo deshace) o solo "
                     "mirarlo.")
        self.setToolTip(self._tip)

    def setToolTip(self, tip: str):
        if not tip.startswith("⏳"):
            self._tip = tip               # (Escenas le añade una línea: se conserva al acabar de medir)
        super().setToolTip(tip)

    def set_busy(self, on: bool):
        """Midiendo: «⏳» y un clic CANCELA la medición (el botón sigue activo)."""
        self.setText("⏳" if on else "LUFS")
        super().setToolTip("⏳ Midiendo la sonoridad… clic = cancelar." if on else self._tip)


def texto_sugerencia(m: dict | None, s: dict, normaliza_al_exportar: bool, plan: dict | None = None,
                     real: dict | None = None) -> str:
    """El mensaje de la sugerencia (HTML sencillo): cómo está la mezcla, el objetivo y qué hacer. plan = lo que de
    verdad se puede cambiar (loudness.plan_ganancia) y real = la medida de la copia con esos volúmenes: si algún clip
    no llega (tope de 400 %) o está bloqueado, el resultado que se dice es el REAL, no el ideal."""
    from ..core import loudness as LN
    if s.get("silencio"):
        return ("No hay sonido que medir: la mezcla está en silencio (o casi).<br>Añade voz, música o videos con "
                "sonido, o comprueba que las pistas no estén silenciadas.")
    partes = [f"<b>Tu mezcla:</b> {_num(m['lufs'])} LUFS integrados · pico verdadero {_num(m['peak'])} dBTP"
              + (f" · rango {_num(m['lra'])} LU" if "lra" in m else ""),
              f"<b>Objetivo</b> ({PLATAFORMAS}): {_num(LN.TARGET_LUFS)} LUFS, pico ≤ {_num(LN.CEILING_DBTP)} dBTP."]
    db = s["db"]
    topados = len((plan or {}).get("topados", ()))
    bloqueados = len((plan or {}).get("bloqueados", ()))
    cambia = bool((plan or {}).get("cambios", True))
    verbo = f"Súbelo {_num(db)} dB" if db > 0 else f"Bájalo {_num(-db)} dB"
    if abs(db) < 0.5 and not s["limitado"]:
        partes.append("✓ <b>Ya está bien</b> (a menos de 0,5 dB del objetivo): no hace falta cambiar nada.")
    elif plan is not None and not cambia:
        partes.append(f"→ Habría que {verbo[0].lower() + verbo[1:]}, pero 🔒 <b>todo el sonido está bloqueado</b> "
                      "(clips o pistas): desbloquéalo para poder aplicarlo.")
    elif topados or bloqueados:
        if real is not None:
            final = f"quedará en <b>{_num(real['lufs'])} LUFS</b> (pico {_num(real['peak'])} dBTP)"
        else:
            final = f"quedará por debajo de {_num(s['lufs_final'])} LUFS"
        motivos = []
        if topados:
            motivos.append(f"{topados} clip(s) ya están al máximo (400 %, +12 dB por clip)")
        if bloqueados:
            motivos.append(f"🔒 {bloqueados} clip(s) con sonido están bloqueados (o en pistas bloqueadas) y no se "
                           "tocan: se aplica al resto")
        partes.append(f"→ <b>{verbo}</b>: {final}, no en {_num(s['lufs_final'])}: " + "; ".join(motivos) + ".")
        if topados:
            partes.append("Para llegar al objetivo, sube sus pistas o activa «Normalizar el volumen a −14 LUFS» al "
                          "exportar.")
    else:
        partes.append(f"→ <b>{verbo}</b> (quedará en {_num(s['lufs_final'])} LUFS, pico "
                      f"{_num(s['pico_final'])} dBTP).")
    if s["limitado"]:
        partes.append(f"Para llegar a {_num(LN.TARGET_LUFS)} LUFS harían falta {_num(s['db_lufs'], True)} dB, pero el "
                      f"pico pasaría de {_num(LN.CEILING_DBTP)} dBTP: hace falta un limitador para el resto.")
    if normaliza_al_exportar:
        partes.append("ℹ «Normalizar el volumen a −14 LUFS» está activado: al exportar se ajusta solo (con limitador). "
                      "Aplicarlo ahora sirve para oírlo y verlo así mientras editas.")
    return "<br><br>".join(partes)


class LoudnessAssistant(QObject):
    """Mide en segundo plano (BackgroundJob: la ventana nunca se congela) y enseña la sugerencia. Uno por proyecto
    abierto (ver asistente_sonoridad): el visor y Escenas comparten la medición en curso."""
    busy = Signal(bool)
    measured = Signal(object)        # (medida, sugerencia) al terminar

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.job = None
        self.last = None             # (medida, sugerencia) de la última vez
        self.ask = self._dialogo     # (las pruebas lo cambian para no abrir ventanas)
        self._cancelado = False
        self._huella = None          # (cómo sonaba el proyecto al empezar a medir: si cambia, no se aplica)

    def _avisar(self, widget, texto: str):
        self.ask(widget, None, texto)          # (sin ganancia que aplicar: solo «Cerrar»)

    def cancel(self):
        """Para la medición en curso (clic en «⏳»): no se enseña ni se aplica nada."""
        if self.job is not None:
            self._cancelado = True
            self.job.cancel()
            self.ctrl.message.emit("📊 Cancelando la medición de la sonoridad…")

    def start(self, widget=None) -> bool:
        from ..core import loudness as LN
        if self.job is not None:     # (clic mientras mide = cancelar)
            self.cancel()
            return False
        p = self.ctrl.project
        if p.duration() <= 0 or not LN.has_sound(p):
            self._avisar(widget, "No hay audio en el proyecto: añade voz, música o videos con sonido (o quita el "
                                 "silencio de sus pistas) y vuelve a medir.")
            return False
        snap = type(p).from_dict(p.to_dict())     # (una copia: puedes seguir editando mientras mide)
        self._huella = LN.huella_sonido(p)
        self._cancelado = False
        from .jobs import BackgroundJob
        job = self.job = BackgroundJob(lambda progress, cancelled: self._medir(snap, progress, cancelled), widget)
        job.title = "📊 Midiendo la sonoridad"
        job.done.connect(lambda res, w=widget: self._hecho(res, w))
        job.failed.connect(lambda msg, w=widget: self._fallo(w, msg))
        job.finished.connect(self._fin)
        self.busy.emit(True)
        self.ctrl.message.emit("📊 Midiendo la sonoridad de la mezcla (en segundo plano)…")
        job.start()
        return True

    def _fin(self):
        job, self.job = self.job, None
        if job is not None:
            job.deleteLater()
        self.busy.emit(False)

    @staticmethod
    def _medir(snap, progress, cancelled) -> dict | None:
        """(En el hilo) mide la copia; si hay que cambiar algo, calcula lo que de verdad cabe (plan_ganancia) y, si
        algún clip no llega o está bloqueado, vuelve a medir la copia con esos volúmenes: el diálogo dirá el
        resultado REAL. None = cancelado."""
        from ..core import loudness as LN
        m = LN.measure_project(snap, progress, cancelled)
        if cancelled():
            return None
        out = {"m": m, "s": None, "plan": None, "real": None}
        if m is None:
            return out
        s = out["s"] = LN.suggest(m)
        if s["silencio"] or (abs(s["db"]) < 0.5 and not s["limitado"]):
            return out
        plan = out["plan"] = LN.plan_ganancia(snap, s["db"])
        if plan["cambios"] and (plan["topados"] or plan["bloqueados"]):
            copia = type(snap).from_dict(snap.to_dict())
            LN.aplicar_plan(copia, plan)
            out["real"] = LN.measure_project(
                copia, lambda f, _t: progress(f, f"📊 Comprobando cuánto sube de verdad… {int(100 * f)} %"), cancelled)
            if cancelled():
                return None
        return out

    def _fallo(self, widget, msg):
        if self._cancelado:
            self.ctrl.message.emit("📊 Medición de la sonoridad cancelada.")
            return
        self._avisar(widget, f"No pude medir la sonoridad: {msg}")

    def _hecho(self, res, widget):
        if self._cancelado or res is None:
            self.ctrl.message.emit("📊 Medición de la sonoridad cancelada.")
            return
        m, s, plan, real = res.get("m"), res.get("s"), res.get("plan"), res.get("real")
        if m is None or s is None:
            self._avisar(widget, "No pude medir la sonoridad (FFmpeg no devolvió el resumen).")
            return
        self.last = (m, s)
        self.measured.emit(self.last)
        texto = texto_sugerencia(m, s, bool(getattr(self.ctrl.project, "loudnorm", False)), plan, real)
        if s["silencio"] or (abs(s["db"]) < 0.5 and not s["limitado"]) or (plan is not None and not plan["cambios"]):
            self.ask(widget, None, texto)
            return
        if self.ask(widget, s["db"], texto):
            self.apply(s["db"], plan, widget)

    def apply(self, db: float, plan: dict | None = None, widget=None) -> bool:
        """Sube o baja todo lo que suena db dB (un Ctrl+Z lo deshace). plan = lo calculado sobre la copia medida: si
        el proyecto cambió mientras se medía, NO se aplica (se avisa: hay que volver a medir)."""
        from ..core import loudness as LN
        if plan is not None and self._huella is not None and LN.huella_sonido(self.ctrl.project) != self._huella:
            self._avisar(widget, "El proyecto cambió mientras medía la sonoridad, así que la medida ya no vale: "
                                 "<b>no he cambiado nada</b>. Vuelve a pulsar «LUFS» para medirlo otra vez.")
            return False
        if plan is None:
            plan = LN.plan_ganancia(self.ctrl.project, db)
        n = self.ctrl.project_gain(db, plan)
        if n is None:
            return False
        tope, bloq = len(plan["topados"]), len(plan["bloqueados"])
        aviso = (f" {tope} ya llegaron al máximo del clip (400 %, +12 dB): súbelos con su pista o con la "
                 "normalización al exportar." if tope else "")
        aviso += f" 🔒 {bloq} bloqueado(s), sin tocar." if bloq else ""
        self.ctrl.message.emit(f"📊 Volumen del proyecto {_num(db, True)} dB ({n} clips). Ctrl+Z lo deshace.{aviso}")
        return True

    @staticmethod
    def _dialogo(widget, db, texto) -> bool:
        box = QMessageBox(widget)
        box.setWindowTitle("📊 Sonoridad para plataformas")
        box.setTextFormat(Qt.RichText)
        box.setText(texto)
        if db is None:
            box.addButton("Cerrar", QMessageBox.AcceptRole)
            box.exec()
            return False
        si = box.addButton(f"Aplicar {_num(db, True)} dB", QMessageBox.AcceptRole)
        box.addButton("Solo informar", QMessageBox.RejectRole)
        box.setDefaultButton(si)
        box.exec()
        return box.clickedButton() is si


def asistente_sonoridad(ctrl) -> LoudnessAssistant:
    a = ctrl.__dict__.get("_asistente_sonoridad")
    if a is None:
        a = ctrl.__dict__["_asistente_sonoridad"] = LoudnessAssistant(ctrl, ctrl)
    return a
