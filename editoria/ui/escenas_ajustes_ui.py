"""
🎬 Recortar y ajustar una capa de Escenas (en el panel de la derecha, con la capa elegida), como en Miniaturas:

  · Quitar el fondo (IA local, ai/bg_removal.py: la misma que en Miniaturas; la primera vez baja su modelo) y
    «Devolver».
  · Borde, sombra y esquinas redondeadas: deslizador + valores rápidos (core/escena_ajustes.RAPIDOS).
  · Texto (las capas de texto de las plantillas): se cambia aquí y se vuelve a dibujar.
  · Recortar: los tiradores del lienzo (Alt o «Recortar con los tiradores»), ya estaban.

El borde, las esquinas y el fondo quitado se HORNEAN en un PNG desde la imagen ORIGINAL (actor["base_media"]), pero sin
congelar nada: mientras mueves el deslizador el lienzo enseña una vista previa barata (la original con el borde y las
esquinas dibujados) y el horneado se hace al soltar (o tras una pausa) en segundo plano; solo el resultado final entra
en Medios (el anterior, si ya nadie lo usa, se quita). Antes de aplicar o crear la escena se termina lo pendiente.
La sombra va como fx del clip. En un video o un texto, el borde y las esquinas no se aplican (salen apagados y el
tooltip dice por qué); una capa bloqueada no se toca.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core import escena_ajustes as EA
from . import diseno as D


# ------------------------------------------------------------------------------------------------ la lógica
def _es_imagen(page, act: dict) -> bool:
    m = page.ctrl.project.media.get(act.get("base_media") or act.get("media_id"))
    return m is not None and m.kind == "image"


def al_dia(page, act: dict) -> bool:
    """¿La imagen de la capa ya corresponde a sus ajustes (o no necesita horneado)?"""
    if act.get("texto") or act.get("hueco") or not _es_imagen(page, act):
        return True
    aj = EA.de(act)
    base = act.get("base_media") or act["media_id"]
    if not EA.hay_horneado(aj):
        return act["media_id"] == base
    return act.get("horneado_de") == EA.clave(aj) and act["media_id"] != base and \
        act["media_id"] in page.ctrl.project.media


_APLICADOS: set = set()   # rutas (normcase) de PNG propios que han estado APLICADOS (en p.scenes) en esta sesión
_QUITADOS: dict = {}      # media_id → MediaItem que quitó la limpieza (para reponerlo si un deshacer lo vuelve a pedir)
_REVISADOS: set = set()   # media_id ya mirados por registrar_aplicados (un id no se repite entre medios)


def _clave(ruta: str) -> str:
    return os.path.normcase(os.path.abspath(ruta))


def registrar_aplicados(p) -> None:
    """Apunta los PNG propios de las escenas del proyecto (= aplicadas). Esos no los borra la limpieza de la página
    (volver, cargar otra escena, quitar una capa): un Ctrl+Z del editor puede traer esa escena. Se limpian al abrir el
    proyecto, cuando ya no hay deshacer (limpiar_al_abrir)."""
    # (corre en cada cambio del proyecto: cada medio se mira UNA vez —_REVISADOS—; lo demás son búsquedas en sets)
    for esc in list(p.scenes.values()):
        for a in esc.get("actores", ()):
            for mid in (a.get("media_id"), a.get("base_media")):
                if not mid or mid in _REVISADOS:
                    continue
                m = p.media.get(mid)
                if m is None:
                    continue
                _REVISADOS.add(mid)
                if EA.es_propia(m.path):
                    _APLICADOS.add(_clave(m.path))


def _rehacer_png(p, act: dict | None) -> str:
    """El PNG de una capa, otra vez (mismo archivo: se nombra por lo que lleva): su texto o su horneado desde la
    original. '' si no se puede."""
    if act is None:
        return ""
    try:
        if act.get("texto"):
            t = act["texto"]
            return EA.texto_png(t.get("t", ""), t.get("color", "#FFFFFF"))
        base = act.get("base_media")
        if base in p.media and EA.hay_horneado(EA.de(act)):
            ruta = EA.hornear(p.media[base].path, EA.de(act))
            return ruta if ruta != p.media[base].path else ""
    except Exception:  # noqa: BLE001 - (sin el original o sin poder hornear: se queda como estaba)
        return ""
    return ""


def reponer_faltantes(ctrl) -> int:
    """🛟 Red de seguridad: si el editor trae (deshacer, rehacer, pegar) una escena o un clip cuyo PNG propio quitó la
    limpieza, se repone en Medios con el MISMO id; si su archivo ya no está, se rehace (texto o horneado desde
    base_media). Cuántos repuso."""
    if not _QUITADOS:
        return 0
    p = ctrl.project
    for mid in [k for k in _QUITADOS if k in p.media]:     # (ya está otra vez: nada que reponer)
        _QUITADOS.pop(mid, None)
    if not _QUITADOS:
        return 0
    falta: dict = {}
    for esc in list(p.scenes.values()):
        for a in esc.get("actores", ()):
            mid = a.get("media_id")
            if mid in _QUITADOS:
                falta[mid] = a
    for c in list(p.clips.values()):
        if c.media_id in _QUITADOS:
            falta.setdefault(c.media_id, None)
    n = 0
    for mid, act in falta.items():
        m = _QUITADOS[mid]
        if not os.path.isfile(m.path):
            if act is None:
                act = next((a for esc in p.scenes.values() for a in esc.get("actores", [])
                            if a.get("media_id") == mid), None)
            ruta = _rehacer_png(p, act)
            if not ruta or not os.path.isfile(ruta):
                continue
            m.path = ruta
        p.media[mid] = m
        _QUITADOS.pop(mid, None)
        try:
            ctrl.missing.discard(mid)
        except AttributeError:
            pass
        n += 1
    if n:
        try:
            ctrl._set_media_dirty()
            ctrl.media_changed.emit()
        except Exception:  # noqa: BLE001
            pass
    return n


def limpiar_al_abrir(ctrl) -> int:
    """Al abrir un proyecto (sin nada que deshacer todavía): sus PNG propios que no usa ninguna escena ni ningún clip
    salen de Medios ▸ Escenas (los archivos se quedan: la carpeta es común a todos los proyectos)."""
    try:
        if ctrl.undo_stack.count():
            return 0
    except AttributeError:
        return 0
    p = ctrl.project
    usados = {c.media_id for c in p.clips.values()}
    for esc in list(p.scenes.values()):
        for a in esc.get("actores", []):
            usados.update({a.get("media_id"), a.get("base_media")})
    sobran = [mid for mid, m in p.media.items() if mid not in usados and EA.es_propia(m.path)]
    for mid in sobran:
        p.media.pop(mid, None)
    if sobran:
        try:
            ctrl.media_changed.emit()
        except Exception:  # noqa: BLE001
            pass
    return len(sobran)


def vigilar(ctrl) -> None:
    """Una vez por controlador: apunta lo aplicado y repone lo que falte en cada cambio del proyecto, y limpia lo
    que sobra al abrir otro proyecto."""
    if getattr(ctrl, "_escenas_vigiladas", False):
        return
    ctrl._escenas_vigiladas = True
    ctrl.project_changed.connect(lambda: (registrar_aplicados(ctrl.project), reponer_faltantes(ctrl)))
    ctrl.project_replaced.connect(lambda: limpiar_al_abrir(ctrl))


def _quitar_si_sobra(page, mid: str | None, contar_escena: bool = True):
    """Un PNG horneado (o un texto) que ya no usa nadie: fuera de Medios y de la carpeta (sin intermedios).
    contar_escena=False: la escena de la página se está descartando y ya no cuenta como «usado»."""
    p = page.ctrl.project
    m = p.media.get(mid) if mid else None
    if m is None or not EA.es_propia(m.path):
        return
    registrar_aplicados(p)
    if _clave(m.path) in _APLICADOS:
        return                     # (estuvo APLICADO: un Ctrl+Z del editor puede traerlo; se limpia al reabrir)
    usados = set()
    for esc in list(p.scenes.values()) + ([page.escena] if contar_escena and page.escena else []):
        for a in esc.get("actores", []):
            usados.update({a.get("media_id"), a.get("base_media")})
    # (lo de un Ctrl+Z de la página no se guarda: si vuelve, se hornea otra vez —mismo archivo— al deshacer)
    if mid in usados or any(c.media_id == mid for c in p.clips.values()):
        return
    p.media.pop(mid, None)
    _QUITADOS[mid] = m                 # (red de seguridad: si algo lo vuelve a pedir, reponer_faltantes lo repone)
    vigilar(page.ctrl)
    try:
        page.ctrl._set_media_dirty()
        page.ctrl.media_changed.emit()
    except Exception:  # noqa: BLE001 - (sin ventana: basta con quitarlo del proyecto)
        pass
    try:
        if os.path.isfile(m.path):
            from ..core.soltar_archivos import soltando
            with soltando([m.path]):                  # (🔓 suelto antes del visor y de los análisis)
                os.remove(m.path)
    except OSError:
        pass


def limpiar_restos(page, actores, con_texto: bool = True, contar_escena: bool = True) -> None:
    """Los PNG propios (horneados o de texto) de esas capas que ya no usa nadie, fuera (cada uno con el chequeo de
    «usado» de _quitar_si_sobra: otras escenas, la de la página si cuenta y los clips).
    · Al QUITAR una capa: con_texto=False. Un horneado se vuelve a hornear solo si un Ctrl+Z de la página trae la capa
      (al_dia lo ve faltar y page.pedir_horneado lo rehace, mismo archivo); un PNG de texto NO se rehace solo, así que
      se queda mientras la capa pueda volver con Ctrl+Z.
    · Al DESCARTAR o cerrar la escena sin aplicar: todo (también los textos), con contar_escena=False y las capas de
      todo su historial de Ctrl+Z (ya no puede volver)."""
    vistos = set()
    for a in actores or []:
        if a.get("texto") and not con_texto:
            continue
        for mid in (a.get("media_id"), a.get("base_media")):
            if mid and mid not in vistos:
                vistos.add(mid)
                _quitar_si_sobra(page, mid, contar_escena)


def _poner_horneado(page, act: dict, ruta: str, clave_aj: str):
    viejo = act.get("media_id")
    base = act.get("base_media") or viejo
    mid = page._media_de_ruta(ruta, "Escenas") if ruta and ruta != page.ctrl.project.media[base].path else base
    act["media_id"] = mid or base
    act["horneado_de"] = clave_aj
    if viejo not in (act["media_id"], base):
        _quitar_si_sobra(page, viejo)


def aplicar_ajustes(page, act: dict, ahora: bool = False) -> None:
    """Pone la imagen de la capa al día con sus ajustes. Sin «ahora», lo caro (hornear) se deja para después (en
    segundo plano: page.hornear_pendientes); el lienzo enseña mientras tanto la vista previa."""
    p = page.ctrl.project
    base = act.get("base_media") or act["media_id"]
    act["base_media"] = base
    if act.get("texto"):                               # (capa de texto: su imagen es el texto dibujado, barato)
        t = act["texto"]
        viejo = act["media_id"]
        mid = page._media_de_ruta(EA.texto_png(t.get("t", ""), t.get("color", "#FFFFFF")), "Escenas") or base
        act["base_media"] = mid
        act["media_id"] = mid
        if viejo != mid:
            _quitar_si_sobra(page, viejo)
        return
    if act.get("hueco") or base not in p.media:
        return
    aj = EA.de(act)
    if not EA.hay_horneado(aj) or not _es_imagen(page, act):
        viejo = act["media_id"]
        act["media_id"] = base
        act.pop("horneado_de", None)
        if viejo != base:
            _quitar_si_sobra(page, viejo)
        return
    if al_dia(page, act):
        return
    if ahora:
        _poner_horneado(page, act, EA.hornear(p.media[base].path, aj), EA.clave(aj))
    else:
        page.pedir_horneado()


def hornear_todo_ya(page) -> int:
    """Lo pendiente, ya (antes de aplicar o crear: la escena sale con su borde y sus esquinas). Rápido."""
    n = 0
    for act in page.escena.get("actores", []):
        if not al_dia(page, act):
            aplicar_ajustes(page, act, ahora=True)
            n += 1
    return n


class Horneador:
    """Los horneados pendientes de la página, de uno en uno en segundo plano (BackgroundJob), tras una pausa."""

    def __init__(self, page):
        self.page = page
        self.job = None
        self.t = QTimer(page)
        self.t.setSingleShot(True)
        self.t.setInterval(350)
        self.t.timeout.connect(self.siguiente)

    def pedir(self):
        self.t.start()

    def siguiente(self):
        pg = self.page
        if self.job is not None:
            return
        act = next((a for a in pg.escena.get("actores", []) if not al_dia(pg, a)), None)
        if act is None:
            return
        aj = EA.de(act)
        clave_aj, aid = EA.clave(aj), act["id"]
        ruta = pg.ctrl.project.media[act.get("base_media") or act["media_id"]].path
        from .jobs import BackgroundJob
        self.job = BackgroundJob(lambda _p, _c: EA.hornear(ruta, aj), parent=pg)
        self.job.title = "Preparando el borde y las esquinas…"
        self.job.done.connect(lambda r: self._hecho(aid, clave_aj, r))
        self.job.failed.connect(lambda m: self._fallo(m))
        self.job.start()

    def _hecho(self, aid, clave_aj, ruta):
        self.job = None
        pg = self.page
        act = pg._actor(aid)
        if act is not None and EA.clave(EA.de(act)) == clave_aj:   # (si cambió mientras tanto, se hornea otra vez)
            _poner_horneado(pg, act, ruta, clave_aj)
            pg._reconstruir()
        elif ruta and EA.es_propia(ruta) and ruta not in {pg.ctrl.project.media[m].path for m in pg.ctrl.project.media}:
            try:
                os.remove(ruta)                             # (ya no vale: nada de intermedios)
            except OSError:
                pass
        self.t.start()

    def _fallo(self, msg):
        self.job = None
        self.page.win.statusBar().showMessage(f"No se pudo preparar la imagen: {str(msg)[-160:]}", 8000)


# ------------------------------------------------------------------------------------------------ lo de la derecha
class SeccionAjustes(QWidget):
    """Lo de la derecha para recortar y ajustar la capa elegida."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self._cargando = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(D.px(D.M1))
        v.addWidget(D.TituloSeccion("Recortar y ajustar"))
        # texto (solo en las capas de texto)
        self.texto = D.campo_texto("Texto", "El texto de esta capa (se vuelve a dibujar al terminar de escribir)")
        self.texto.editingFinished.connect(self._texto_cambiado)
        self.fila_texto = D.FilaInspector("Texto", self.texto)
        v.addWidget(self.fila_texto)
        # quitar el fondo
        fila = QGridLayout()
        fila.setSpacing(D.px(D.M1))
        self.b_fondo = QPushButton("Quitar el fondo")
        self.b_fondo.setIcon(D.icono("eraser"))
        self.b_fondo.clicked.connect(lambda: self.quitar_fondo())
        self.b_devolver = QPushButton("Devolver")
        self.b_devolver.setIcon(D.icono("undo-2"))
        self.b_devolver.setToolTip("Vuelve a poner el fondo que se quitó")
        self.b_devolver.clicked.connect(self.devolver_fondo)
        for k, b in enumerate((self.b_fondo, self.b_devolver)):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setFocusPolicy(Qt.NoFocus)
            fila.addWidget(b, 0, k)
        v.addLayout(fila)
        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        D.poner_letra(self.estado, D.LETRA_P, D.GRIS_TITULO)
        self.estado.hide()
        v.addWidget(self.estado)
        # borde, sombra, redondeo: deslizador + rápidos
        self.valores, self.rapidos, self.filas = {}, {}, {}
        self.tips = {"borde": "Grosor del borde (en % del lado corto de la imagen); sigue su forma, también si le "
                              "quitaste el fondo",
                     "sombra": "Sombra suave detrás (opacidad); sigue la forma de la imagen",
                     "redondeo": "Esquinas redondeadas (50 % = círculo u óvalo)"}
        for clave, etiqueta, maximo in (("borde", "Borde", 8.0), ("sombra", "Sombra", 100.0),
                                        ("redondeo", "Esquinas", 50.0)):
            val = D.ValorDeslizable(0.0, maximo, 0.5 if clave == "borde" else 1.0, 1 if clave == "borde" else 0,
                                    " %")
            val.setToolTip(self.tips[clave])
            val.valueChanged.connect(lambda x, k=clave: self._cambio(k, float(x) / 100.0))
            val.arrastre.connect(lambda on: None if on else self.page.pedir_horneado())   # (al soltar, se hornea)
            fila_v = D.FilaInspector(etiqueta, val, self.tips[clave])
            v.addWidget(fila_v)
            rap = QGridLayout()                       # (valores rápidos en 2 columnas: el panel puede ser estrecho)
            rap.setSpacing(D.px(D.M1))
            botones = []
            for n_rap, (nombre, valor) in enumerate(EA.RAPIDOS[clave]):
                b = QPushButton(nombre)
                b.setToolTip(f"{etiqueta}: {nombre.lower()}")
                b.setFocusPolicy(Qt.NoFocus)
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                b.clicked.connect(lambda _c=False, k=clave, x=valor: self.poner(k, x))
                rap.addWidget(b, n_rap // 2, n_rap % 2)
                botones.append(b)
            v.addLayout(rap)
            self.valores[clave], self.rapidos[clave], self.filas[clave] = val, botones, fila_v
        self.color = QPushButton("Color del borde")
        self.color.setToolTip("Elegir el color del borde")
        self.color.setFocusPolicy(Qt.NoFocus)
        self.color.clicked.connect(self._elegir_color)
        v.addWidget(self.color)

    # ---- con la capa elegida
    def _act(self):
        return self.page._actor_elegido()

    def cargar(self, act: dict | None):
        self._cargando = True
        try:
            texto = bool(act and act.get("texto"))
            self.fila_texto.setVisible(texto)
            if texto:
                self.texto.setText(act["texto"].get("t", ""))
            aj = EA.de(act or {})
            for k, val in self.valores.items():
                val.setValue(float(aj.get(k, 0) or 0) * 100.0)
            bloq = bool(act and act.get("bloqueado"))
            hueco = bool(act and act.get("hueco"))
            imagen = bool(act) and _es_imagen(self.page, act) and not texto and not hueco
            por_que = ("Capa bloqueada: desbloquéala en Capas para tocarla" if bloq else
                       "Primero suelta una imagen en el hueco" if hueco else
                       "En una capa de texto no se usa" if texto else
                       "En un video no se aplica (solo en imágenes)" if act and not imagen else "")
            for k in ("borde", "redondeo"):
                ok = imagen and not bloq
                self.valores[k].setEnabled(ok)
                for b in self.rapidos[k]:
                    b.setEnabled(ok)
                self.filas[k].setToolTip(self.tips[k] if ok else f"{self.tips[k]}\n({por_que})")
            ok_s = bool(act) and not bloq and not hueco
            self.valores["sombra"].setEnabled(ok_s)
            for b in self.rapidos["sombra"]:
                b.setEnabled(ok_s)
            self.color.setEnabled(imagen and not bloq)
            self.b_fondo.setEnabled(imagen and not bloq)
            self.b_fondo.setToolTip("Recorta al personaje u objeto principal con la IA local (la misma que en "
                                    "Miniaturas; la primera vez baja su modelo, ~180 MB). Se ve igual al exportar."
                                    + (f"\n({por_que})" if not (imagen and not bloq) else ""))
            self.b_devolver.setEnabled(bool(aj.get("sin_fondo")) and not bloq)
            self.texto.setEnabled(not bloq)
        finally:
            self._cargando = False

    def poner(self, clave: str, valor: float):
        self.valores[clave].setValue(valor * 100.0)
        self.page.pedir_horneado()

    def _cambio(self, clave: str, valor: float):
        if self._cargando:
            return
        act = self._act()
        if act is None or act.get("bloqueado"):
            return
        aj = dict(act.get("ajustes") or {})
        aj[clave] = round(valor, 4)
        act["ajustes"] = aj
        aplicar_ajustes(self.page, act)                 # (lo caro, después; ahora solo la vista previa)
        self.page._ensuciar()
        self.page._poner_en_reposo()

    def _elegir_color(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        act = self._act()
        if act is None:
            return
        c = QColorDialog.getColor(QColor(EA.de(act).get("borde_color", "#FFFFFF")), self, "Color del borde")
        if c.isValid():
            self.poner_color(c.name())

    def poner_color(self, color: str):
        act = self._act()
        if act is None or act.get("bloqueado"):
            return
        aj = dict(act.get("ajustes") or {})
        aj["borde_color"] = color
        if float(aj.get("borde", 0) or 0) <= 0:
            aj["borde"] = 0.012
        act["ajustes"] = aj
        self.cargar(act)
        aplicar_ajustes(self.page, act)
        self.page._ensuciar()
        self.page._poner_en_reposo()
        self.page.pedir_horneado()

    def _texto_cambiado(self):
        act = self._act()
        if self._cargando or act is None or not act.get("texto") or act.get("bloqueado"):
            return
        if self.texto.text() == act["texto"].get("t"):
            return
        act["texto"]["t"] = self.texto.text()
        aplicar_ajustes(self.page, act)
        self.page._ensuciar()
        self.page._reconstruir()

    # ---- quitar el fondo (en segundo plano, por el mismo camino que el botón)
    def quitar_fondo(self):
        act = self._act()
        if act is None or act.get("bloqueado"):
            return
        m = self.page.ctrl.project.media.get(act.get("base_media") or act["media_id"])
        if m is None or m.kind != "image":
            self.page.win.statusBar().showMessage("Quitar el fondo funciona con imágenes.", 5000)
            return
        from ..ai import bg_removal as BR
        aid, ruta = act["id"], m.path

        def trabajo(progress, _cancelled):
            BR.download(progress)                        # (la primera vez, ~180 MB, con su progreso)
            return EA.guardar_mascara(BR.remove(ruta))    # (la máscara, fuera de la caché que se limpia)

        def hecho(mascara):
            a = self.page._actor(aid)
            if a is None or not mascara:
                return
            aj = dict(a.get("ajustes") or {})
            aj["sin_fondo"] = mascara
            a["ajustes"] = aj
            aplicar_ajustes(self.page, a, ahora=True)
            self.page._ensuciar()
            self.page._reconstruir()
            self.estado.setText("Fondo quitado (se ve igual al exportar)")
            self.estado.show()
        self.estado.setText("Quitando el fondo…")
        self.estado.show()
        self.page._lanzar(trabajo, hecho, "Quitando el fondo…", self.estado)

    def devolver_fondo(self):
        act = self._act()
        if act is None or act.get("bloqueado"):
            return
        aj = dict(act.get("ajustes") or {})
        if not aj.pop("sin_fondo", None):
            return
        act["ajustes"] = aj
        aplicar_ajustes(self.page, act, ahora=True)
        self.page._ensuciar()
        self.page._reconstruir()
        self.estado.hide()
