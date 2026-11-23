"""
Prueba de la sección «Material por frases» (editoria/ui/material_por_frases_panel.py), SIN internet y sin ventanas:
  · se coloca en Medios con LibraryPanel.poner_material_frases (instalar), debajo de «Archivos / Carpeta»;
  · todo a la vista y sin cortar: el botón principal en una o dos líneas según el ancho (280, 360, 600 px), sin
    ensanchar el panel; tipo y duración del trozo solo con la parte privada de videos (y recordados);
  · el botón principal va por la cola de análisis, se puede cancelar, coloca con un Ctrl+Z y deja el resumen en la
    lista adaptable (miniatura grande, botones sobre la miniatura: ir, censurar, cambiar, quitar);
  · búsqueda manual de una frase («Dijiste…» → botón por frase): 4–6 resultados; «Censurar» marcado = se tapa al
    ponerlo; un clic baja y pone en el cabezal (un Ctrl+Z);
  · «Censurar» en el resumen: recuadro sobre la cara (un Ctrl+Z);
  · capturas antes / después en _pruebas_tmp/capturas_material_frases (o MPF_CAPTURAS).
Ejecutar:  .venv/Scripts/python.exe tests/test_material_por_frases_panel.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time


def _aislar_datos():
    import atexit
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.makedirs(os.environ["EDITORIA_DATOS"], exist_ok=True)
    os.environ["USERPROFILE"] = tmp
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import urllib.request  # noqa: E402


def _sin_internet(*_a, **_k):
    import traceback
    traceback.print_stack()                     # (desde dónde: para simular esa parte)
    print("FALLO: la prueba intentó conectarse a internet", _a[:1], flush=True)
    os._exit(1)


urllib.request.urlopen = _sin_internet

from _material_frases_comun import (FuentesLocales, ImagenFalsa, TextoFalso, check, detector_falso,  # noqa: E402
                                    fabricar, fabricar_cara, proyecto)


def _vigilante(segundos: float = 420.0):
    def fin():
        print(f"FALLO: la prueba tardó más de {segundos:.0f} s")
        os._exit(1)
    t = threading.Timer(segundos, fin)
    t.daemon = True
    t.start()


def esperar_panel(app, panel, maximo: float = 90.0):
    t0 = time.time()
    while panel.ocupado() and time.time() - t0 < maximo:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()
    return not panel.ocupado()


class AnalizadorFalso:
    """Lo mínimo que LibraryPanel pide al analizador de clips (sus señales)."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _S(QObject):
            status_changed = Signal(str)
            busy_changed = Signal(bool)
        self._s = _S()
        self.status_changed = self._s.status_changed
        self.busy_changed = self._s.busy_changed

    def __getattr__(self, nombre):
        return _Nada()


class _Nada:
    """Vale como función (devuelve "") y como valor vacío."""

    def __call__(self, *a, **k):
        return ""

    def __str__(self):
        return ""

    def __bool__(self):
        return False

    def __int__(self):
        return 0


class FuentesQueFallan(FuentesLocales):
    """La web no responde o limita (429): no trae nada y lo apunta en «fallos», como M.Fuentes."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fallos = []

    def buscar_imagenes(self, qs, cancelled=None):
        self.fallos.append("Openverse: HTTP Error 429: Too Many Requests")
        return []


class FuentesLentas(FuentesLocales):
    """Para cancelar: la búsqueda tarda (y mira si la cancelan)."""

    def buscar_imagenes(self, qs, cancelled=None):
        for _ in range(100):
            if cancelled and cancelled():
                from editoria.ai.base import Cancelled
                raise Cancelled()
            time.sleep(0.05)
        return super().buscar_imagenes(qs, cancelled)


def captura(w, carpeta: str, nombre: str, ancho: int = 380, alto: int = 720):
    w.resize(ancho, alto)
    w.show()                                   # (offscreen: no se ve ninguna ventana)
    from PySide6.QtWidgets import QApplication
    for _ in range(6):
        QApplication.processEvents()
    ruta = os.path.join(carpeta, nombre)
    w.grab().save(ruta)
    print("  captura:", ruta)
    return ruta


def botones_cortados(panel) -> list[str]:
    """La misma regla que test_paneles_sin_cortes para los botones con texto."""
    from PySide6.QtWidgets import QPushButton, QWidget
    out = []
    for w in panel.findChildren(QPushButton):
        if not w.isVisibleTo(panel) or not w.text().strip():
            continue
        fm = w.fontMetrics()
        need = fm.horizontalAdvance(w.text()) + (w.iconSize().width() + 4 if not w.icon().isNull() else 0) + 8
        if QWidget.width(w) + 2 < need:
            out.append(f"{w.text()} ({QWidget.width(w)} < {need})")
    return out


def textos_cortados(panel) -> list[str]:
    out = []
    if not panel.btn_buscar.texto_cabe():
        out.append(panel.btn_buscar.text())
    for i in range(panel.lista.count()):
        it = panel.lista.item(i)
        if not panel.lista.isRowHidden(i) and not panel.lista.texto_cabe(it):
            out.append(it.text())
    return out


def main():
    _vigilante(420)
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_pruebas_tmp", "mpf_panel"))
    os.makedirs(out, exist_ok=True)
    import atexit
    atexit.register(shutil.rmtree, out, True)
    capturas = os.environ.get("MPF_CAPTURAS") or os.path.join(ROOT, "_pruebas_tmp", "capturas_material_frases")
    os.makedirs(capturas, exist_ok=True)

    from types import SimpleNamespace

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)                      # (las capturas, con el aspecto de Reclaimer)
    from editoria.ai import material_por_frases as M
    from editoria.ui import material_por_frases_panel as P
    from editoria.ui.library import LibraryPanel

    rutas = fabricar(os.path.join(out, "material"))
    ruta_cara = fabricar_cara(os.path.join(out, "material"))
    rutas_busqueda = dict(rutas, cara=ruta_cara)
    ctrl, _v1, _w = proyecto(app, out, rutas)

    # ---- antes y después en Medios
    lib = LibraryPanel(ctrl, AnalizadorFalso())
    captura(lib, capturas, "1_antes_medios.png")
    min_antes = lib.minimumSizeHint().width()
    win = SimpleNamespace(library=lib, ctrl=ctrl)
    panel = P.instalar(win)
    check(panel is not None and P.instalar(win) is panel, "instalar() la pone en Medios una sola vez")
    check(lib.zona_material_frases.isVisibleTo(lib) and panel.parent() is lib.zona_material_frases,
          "va en el sitio de Medios, debajo de «Archivos / Carpeta»")
    check(P.panel_activo() is panel, "panel_activo() la encuentra (para el botón de cada frase)")
    panel.fuentes = FuentesLocales(rutas_busqueda, os.path.join(out, "bajadas"))
    panel.opciones = {"enc_texto": TextoFalso(), "enc_imagen": ImagenFalsa(), "detector": detector_falso}
    captura(lib, capturas, "2_despues_medios_vacio.png")
    check(lib.minimumSizeHint().width() <= min_antes + 2,
          f"no ensancha Medios (pide {lib.minimumSizeHint().width()} px; antes {min_antes})")
    check(not panel.lista.isVisible() and not panel.estado.isVisible() and not panel.progreso.isVisible(),
          "sin nada todavía: solo la cabecera y el botón (sin huecos)")
    lib.resize(600, 720)
    for _ in range(4):
        app.processEvents()
    check(panel.btn_buscar.text() == ("Buscar material conforme a frases y palabras clave" if panel.con_videos
                                      else "Buscar imágenes conforme a frases y palabras clave"),
          f"con sitio, el botón dice la frase entera ({panel.btn_buscar.text()})")
    check(panel.fila_tipo.isVisible() == panel.con_videos, "tipo (imágenes/videos/ambos) solo con la parte de videos")
    check(panel.minimumSizeHint().width() <= 200,
          f"la sección no impone ancho: cabe en 200 px (pide {panel.minimumSizeHint().width()})")
    for ancho in (360, 600):
        lib.resize(ancho, 720)
        for _ in range(4):
            app.processEvents()
        check(panel.btn_buscar.texto_cabe() and botones_cortados(panel) == [],
              f"Medios a {ancho} px: nada cortado; el botón dice «{panel.btn_buscar.text() or '(solo la lupa)'}» "
              f"({botones_cortados(panel)})")
        check(panel.btn_buscar.texto_completo() in panel.btn_buscar.toolTip(), "la frase entera, en el tooltip")
        captura(lib, capturas, f"2b_medios_{ancho}px.png", ancho, 720)
    suelta = P.MaterialPorFrases(ctrl)          # (LibraryPanel suelto no baja de su propio mínimo: la sección sola)
    for ancho in (200, 260, 360):
        captura(suelta, capturas, f"2c_seccion_{ancho}px.png", ancho, suelta.sizeHint().height())
        check(suelta.width() == ancho and suelta.btn_buscar.texto_cabe() and botones_cortados(suelta) == [],
              f"la sección a {ancho} px: nada cortado; el botón dice "
              f"«{suelta.btn_buscar.text() or '(solo la lupa)'}» ({botones_cortados(suelta)})")
    suelta.deleteLater()
    check(bool(panel.btn_buscar.toolTip()) and bool(panel.cabecera.toolTip()), "las explicaciones, en tooltips")

    # ---- con videos (la versión privada): tipo y trozo a la vista y recordados
    pv = P.MaterialPorFrases(ctrl, con_videos=True)
    pv.btn_tipo["ambos"].click()
    pv.btn_trozo[60].click()
    captura(pv, capturas, "3_con_videos_tipo_y_trozo.png", 380, pv.sizeHint().height())
    check(pv.fila_tipo.isVisible() and pv.fila_trozo.isVisible(), "con videos: tipo y duración del trozo a la vista")
    for ancho in (200, 260):
        captura(pv, capturas, f"3b_con_videos_{ancho}px.png", ancho, pv.sizeHint().height())
        check(botones_cortados(pv) == [], f"con videos a {ancho} px, nada cortado ({botones_cortados(pv)})")
    pv2 = P.MaterialPorFrases(ctrl, con_videos=True)
    check(pv2.tipo() == "ambos" and pv2.trozo() == 60, "tipo y trozo recordados")
    pv2.btn_tipo["imagenes"].click()
    check(not pv2.fila_trozo.isVisible(), "solo imágenes: sin la duración del trozo")
    pv.deleteLater()
    pv2.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    del pv, pv2
    check(P.panel_activo() is panel, "el panel de Medios sigue siendo el activo")

    # ---- automático por la cola, un Ctrl+Z, resumen
    lib.resize(380, 720)
    if panel.con_videos and panel.tipo() != "imagenes":     # (solo imágenes: los videos usarían la red de verdad)
        print(f"  (el tipo de la sección era «{panel.tipo()}»: se pasa a imágenes)")
        panel.btn_tipo["imagenes"].click()
    check(panel.tipo() == "imagenes", "la pasada automática, solo con imágenes (locales)")
    n_antes = len(ctrl.project.clips)
    pasos = ctrl.undo_stack.index()
    panel.buscar_todo()
    check(panel.ocupado() and panel.btn_cancelar.isVisible() and not panel.btn_buscar.isEnabled(),
          "buscando: ✕ cancelar a la vista y el botón apagado")
    from editoria.ui import cola_analisis
    check(any(t.clave == "material_frases/todo" for t in cola_analisis.cola()._trabajos),
          "va por la cola única de análisis")
    check(esperar_panel(app, panel), "termina (sin congelar: la interfaz sigue respondiendo)")
    check(len(panel.resumen) == 3 and ctrl.undo_stack.index() == pasos + 1,
          f"tres imágenes puestas en UN paso ({len(panel.resumen)})")
    check(panel.lista.isVisible() and panel.lista.count() == 4, "resumen en la lista adaptable (cabecera + 3)")
    panel.lista.setCurrentItem(panel.lista.item(1))     # (el elegido enseña sus botones)
    captura(lib, capturas, "4_despues_resumen.png")
    check(not textos_cortados(panel), f"nada cortado ({textos_cortados(panel)})")
    it = panel.lista.item(1)
    check(panel.lista.iconSize().width() >= 120, "miniatura grande")
    acc = [c for c, _i, _t in panel.lista.acciones_de(it)]
    check(acc == ["ir", "censurar", "cambiar", "quitar"], f"botones de cada puesto: {acc}")
    rects = panel.lista._rects(it)
    caja = panel.lista.visualItemRect(it)
    check(all(caja.contains(r) for r, *_x in rects), "los botones van sobre la miniatura, dentro de su fila")
    check(all(t for *_x, t in rects), "cada botón con su tooltip")

    # quitar desde la lista (como el clic en su botón)
    cid0 = panel.resumen[0]["clip_id"]
    panel.lista.accion.emit(it, "quitar")
    app.processEvents()
    check(cid0 not in ctrl.project.clips, "«Quitar» desde el resumen")
    panel._refrescar_lista()
    check("(quitado)" in panel.lista.item(1).text() and not (panel.lista.item(1).flags() & Qt.ItemIsEnabled),
          "el quitado se ve apagado en el resumen")
    ctrl.undo_stack.undo()
    panel._refrescar_lista()
    check(cid0 in ctrl.project.clips and "(quitado)" not in panel.lista.item(1).text(),
          "Ctrl+Z lo devuelve y el resumen lo ve")

    # ---- doble pulsación por el camino REAL del panel: no repite ni apila
    n = len(ctrl.project.clips)
    panel.buscar_todo()
    esperar_panel(app, panel)
    check(len(ctrl.project.clips) == n and "Ya hay material" in panel.estado.text(),
          f"pulsar otra vez no vuelve a poner nada encima ({panel.estado.text()})")
    quitado = panel.resumen[1]
    clave_quitada = M._clave_item(quitado["item"])
    panel.quitar(1)
    buenas = panel.fuentes
    panel.fuentes = FuentesQueFallan(rutas_busqueda, os.path.join(out, "bajadas_falla"))
    panel.buscar_todo()
    check(esperar_panel(app, panel), "con la web fallando, termina")
    check("⚠" in panel.estado.text() and quitado["clip_id"] not in ctrl.project.clips,
          f"si la web falla o limita, lo AVISA (no un «no encontré nada» callado): {panel.estado.text()}")
    panel.fuentes = buenas
    n = len(ctrl.project.clips)
    panel.buscar_todo()
    check(esperar_panel(app, panel), "otra pasada tras quitar una")
    nuestros = [c for c in ctrl.project.clips.values() if c.note == M.NOTA]
    check(len(ctrl.project.clips) == n + 1 and len(nuestros) == 3,
          f"solo rellena la frase que quedó libre ({len(nuestros)} puestas)")
    nuevo = next(e for e in panel.resumen if e is not quitado and abs(e["tl"] - quitado["tl"]) < 0.01)
    claves_vivas = [M._clave_item(e["item"]) for e in panel.resumen if e.get("clip_id") in ctrl.project.clips]
    check(M._clave_item(nuevo["item"]) != clave_quitada and len(set(claves_vivas)) == len(claves_vivas),
          "y con otra imagen: ninguna repetida")

    # ---- censurar un puesto: sobre la cara (detector falso), un Ctrl+Z
    i_cara = 2
    panel.resumen[i_cara]["ruta"] = ruta_cara
    pasos = ctrl.undo_stack.index()
    panel.censurar(i_cara)
    check(esperar_panel(app, panel), "censurar va por la cola")
    c = ctrl.project.clips[panel.resumen[i_cara]["clip_id"]]
    check(len((c.fx or {}).get("blur_regions") or []) == 1 and ctrl.undo_stack.index() == pasos + 1,
          "«Censurar» en el resumen: un recuadro borroso, un Ctrl+Z")
    check("encima de la cara" in panel.estado.text(), f"dice dónde lo puso ({panel.estado.text()})")

    # ---- manual: botón por frase de «Dijiste…» → resultados → censurar al ponerlo → clic = en el cabezal
    from editoria.ai.mentions import find_mentions
    men = next(m for m in find_mentions(ctrl.project) if m["term"] == "Elden Ring")
    b = P.boton_por_frase(SimpleNamespace(ctrl=ctrl), men, men["hits"][0])
    check(b.toolTip().startswith("Buscar material para esta frase"), "botón por frase con su tooltip")
    b.click()
    check(esperar_panel(app, panel), "la búsqueda de la frase va por la cola")
    check(4 <= len(panel.resultados) <= 6, f"4–6 resultados ({len(panel.resultados)})")
    check(panel.res_frase["frase"].startswith("En Elden Ring") and panel.res_frase["termino"] == "Elden Ring",
          "busca la frase entera de ese momento")
    grupo = panel.lista.item(0)
    check(panel.lista.es_grupo(grupo) and grupo.text() == "Resultados para «Elden Ring»", "resultados arriba")
    it_res = panel.lista.item(1)
    check([c for c, _i, _t in panel.lista.acciones_de(it_res)] == ["censurar", "usar"],
          "cada resultado: censurar y bajar/poner")
    panel.lista.accion.emit(it_res, "censurar")
    app.processEvents()
    check(panel.resultados[0].get("censurar") and "Se censura al ponerlo" in panel.lista.item(1).text(),
          "«Censurar» marcado en el resultado (se ve en la tarjeta)")
    panel.lista.setCurrentItem(panel.lista.item(1))     # (el elegido enseña sus botones)
    captura(lib, capturas, "5_despues_resultados_frase.png")
    check(not textos_cortados(panel), f"nada cortado con resultados ({textos_cortados(panel)})")
    check(panel._dato_vista(panel.lista.item(1)) == panel.resultados[0]["thumb_local"],
          "vista grande al pasar el ratón: la miniatura del resultado")
    pasos = ctrl.undo_stack.index()
    n_clips = len(ctrl.project.clips)
    panel._clic(panel.lista.item(1))
    check(esperar_panel(app, panel), "bajar y poner va por la cola")
    nuevos = [c for c in ctrl.project.clips.values() if abs(c.start - 0.0) < 0.01 and c.note == M.NOTA]
    check(len(ctrl.project.clips) > n_clips and nuevos and ctrl.undo_stack.index() == pasos + 1,
          "un clic: baja y pone en el cabezal, un Ctrl+Z")
    check(len((nuevos[0].fx or {}).get("blur_regions") or []) == 1, "y sale ya censurado")

    # ---- cancelar
    panel.fuentes = FuentesLentas(rutas_busqueda, os.path.join(out, "bajadas2"))
    for i, e in enumerate(list(panel.resumen)):     # (una frase libre: si no, no hay nada que buscar)
        if e["tl"] < 2.0 and e.get("clip_id") in ctrl.project.clips:
            panel.quitar(i)
    n_clips = len(ctrl.project.clips)
    panel.buscar_todo()
    t0 = time.time()
    while time.time() - t0 < 0.5:
        app.processEvents()
        time.sleep(0.02)
    panel.cancelar()
    check(esperar_panel(app, panel, 30), "✕ cancela")
    check(len(ctrl.project.clips) == n_clips and "cancelada" in panel.estado.text(),
          f"cancelado: no pone nada y lo dice ({panel.estado.text()})")
    check(panel.btn_buscar.isEnabled() and not panel.btn_cancelar.isVisible(), "vuelve a estar listo")
    print(f"Capturas en {capturas}")
    print("TODO BIEN")


if __name__ == "__main__":
    main()
